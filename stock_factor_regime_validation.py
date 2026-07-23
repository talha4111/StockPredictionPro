"""Evaluate pre-registered QuantConnect factor-weight regime runs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Mapping


REQUIRED_METRICS = (
    "total_return_pct",
    "max_drawdown_pct",
    "sharpe_ratio",
)


def _finite_number(value: object, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def expected_run_keys(manifest: Mapping[str, object]) -> set[tuple[str, str]]:
    variants = [row["id"] for row in manifest.get("variants", [])]
    regimes = [row["id"] for row in manifest.get("regimes", [])]
    if not variants or variants[0] != "baseline":
        raise ValueError("The first registered variant must be baseline")
    if len(variants) != len(set(variants)) or len(regimes) != len(set(regimes)):
        raise ValueError("Variant and regime ids must be unique")
    return {(variant, regime) for variant in variants for regime in regimes}


def evaluate_results(manifest: Mapping[str, object]) -> dict:
    expected = expected_run_keys(manifest)
    indexed: dict[tuple[str, str], Mapping[str, object]] = {}
    for row in manifest.get("results", []):
        key = (row.get("variant_id"), row.get("regime_id"))
        if key not in expected:
            raise ValueError(f"Unexpected cloud result: {key}")
        if key in indexed:
            raise ValueError(f"Duplicate cloud result: {key}")
        for field in REQUIRED_METRICS:
            _finite_number(row.get(field), field)
        indexed[key] = row

    missing = sorted(expected - set(indexed))
    if missing:
        return {
            "status": "AWAITING_CLOUD_RESULTS",
            "production_valid": False,
            "completed_runs": len(indexed),
            "required_runs": len(expected),
            "missing_runs": [
                {"variant_id": variant, "regime_id": regime}
                for variant, regime in missing
            ],
        }

    rule = manifest["decision_rule"]
    return_threshold = int(rule["minimum_regimes_beating_baseline_return"])
    sharpe_threshold = int(rule["minimum_regimes_beating_baseline_sharpe"])
    drawdown_limit = float(
        rule["maximum_drawdown_deterioration_percentage_points"]
    )
    regime_ids = [row["id"] for row in manifest["regimes"]]
    variant_ids = [row["id"] for row in manifest["variants"]]
    comparisons = []
    for variant_id in variant_ids[1:]:
        return_deltas = []
        sharpe_deltas = []
        drawdown_deltas = []
        for regime_id in regime_ids:
            baseline = indexed[("baseline", regime_id)]
            candidate = indexed[(variant_id, regime_id)]
            return_deltas.append(
                float(candidate["total_return_pct"])
                - float(baseline["total_return_pct"])
            )
            sharpe_deltas.append(
                float(candidate["sharpe_ratio"])
                - float(baseline["sharpe_ratio"])
            )
            drawdown_deltas.append(
                float(candidate["max_drawdown_pct"])
                - float(baseline["max_drawdown_pct"])
            )

        return_wins = sum(delta > 0 for delta in return_deltas)
        sharpe_wins = sum(delta > 0 for delta in sharpe_deltas)
        drawdown_pass = all(delta <= drawdown_limit for delta in drawdown_deltas)
        passed = (
            return_wins >= return_threshold
            and sharpe_wins >= sharpe_threshold
            and drawdown_pass
        )
        comparisons.append({
            "variant_id": variant_id,
            "return_wins": return_wins,
            "sharpe_wins": sharpe_wins,
            "average_return_delta_percentage_points": sum(return_deltas) / len(return_deltas),
            "average_sharpe_delta": sum(sharpe_deltas) / len(sharpe_deltas),
            "worst_drawdown_deterioration_percentage_points": max(drawdown_deltas),
            "drawdown_guard_pass": drawdown_pass,
            "passed": passed,
        })

    passing = [row for row in comparisons if row["passed"]]
    passing.sort(key=lambda row: (
        -row["return_wins"],
        -row["sharpe_wins"],
        -row["average_return_delta_percentage_points"],
        row["variant_id"],
    ))
    return {
        "status": (
            rule["best_possible_status"]
            if passing else "MODEL_REVIEW_REQUIRED"
        ),
        "production_valid": False,
        "completed_runs": len(indexed),
        "required_runs": len(expected),
        "recommended_candidate": passing[0]["variant_id"] if passing else None,
        "comparisons": comparisons,
        "note": (
            "The candidates were selected on the enclosing period. Even a pass "
            "remains research-only until genuinely new paper observations accrue."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate cloud regime results")
    parser.add_argument(
        "--manifest",
        default="data/stock_factor_regime_manifest.json",
    )
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()

    path = Path(args.manifest)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    decision = evaluate_results(manifest)
    if args.update:
        manifest["decision"] = decision
        manifest["status"] = decision["status"]
        path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(decision, indent=2, ensure_ascii=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
