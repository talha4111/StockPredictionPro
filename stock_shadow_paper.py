"""Monthly shadow cohorts for genuinely new stock-factor observations."""

from __future__ import annotations

import json
import math
import os
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Mapping, Sequence


BASELINE_MODEL_ID = "paper_baseline"
CHALLENGER_MODEL_ID = "paper_m00_r15"
BASELINE_VERSION = "3.1-paper-baseline-v1"
CHALLENGER_VERSION = "3.1-paper-m00-r15-v1"

MODEL_SPECS = {
    BASELINE_MODEL_ID: {
        "role": "BASELINE",
        "strategy_version": BASELINE_VERSION,
        "weights": {
            "quality": 0.35,
            "value": 0.20,
            "momentum": 0.30,
            "risk": 0.15,
        },
    },
    CHALLENGER_MODEL_ID: {
        "role": "CHALLENGER",
        "strategy_version": CHALLENGER_VERSION,
        "weights": {
            "quality": 0.35,
            "value": 0.20,
            "momentum": 0.00,
            "risk": 0.15,
        },
    },
}

DECISION_RULE = {
    "horizon_business_days": 20,
    "minimum_paired_mature_cohorts": 3,
    "minimum_names_per_mature_cohort": 10,
    "minimum_challenger_excess_win_rate": 2.0 / 3.0,
    "maximum_average_mae_deterioration": 0.02,
}


def _finite(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def cohort_month_from_rows(rows: Sequence[Mapping[str, object]]) -> str:
    if not rows:
        raise ValueError("Paper cohort requires completed market dates")

    dates = []
    for row in rows:
        raw_date = row.get("veri_tarihi")
        if not raw_date:
            raise ValueError("Paper cohort contains a missing market date")
        try:
            market_date = datetime.strptime(
                str(raw_date)[:10], "%Y-%m-%d"
            ).date().isoformat()
        except ValueError as exc:
            raise ValueError(f"Invalid paper market date: {raw_date}") from exc
        dates.append(market_date)

    unique_dates = set(dates)
    if len(unique_dates) != 1:
        raise ValueError(
            f"Paper cohort contains mixed market dates: {sorted(unique_dates)}"
        )
    return dates[0][:7]


def select_monthly_top20(
    ranked_rows: Sequence[Mapping[str, object]],
    model_id: str,
    cohort_month: str,
    top_n: int = 20,
    min_positions: int = 10,
    max_position_weight: float = 0.05,
    sector_cap: float = 0.25,
) -> list[dict]:
    """Select the pure factor Top20 and attach an auditable paper contract."""
    if model_id not in MODEL_SPECS:
        raise ValueError(f"Unknown paper model: {model_id}")
    eligible = [
        dict(row)
        for row in ranked_rows
        if _finite(row.get("faktor_skor")) is not None
        and _finite(row.get("faktor_kapsami")) is not None
        and float(row["faktor_kapsami"]) >= 0.75
    ]
    eligible.sort(key=lambda row: (-float(row["faktor_skor"]), str(row.get("sembol", ""))))
    selected = eligible[:top_n]
    if len(selected) < min_positions:
        return []

    spec = MODEL_SPECS[model_id]
    base_weight = min(1.0 / len(selected), max_position_weight)
    sector_counts = Counter(str(row.get("sektor", "Bilinmiyor")) for row in selected)
    result = []
    for rank, row in enumerate(selected, start=1):
        sector = str(row.get("sektor", "Bilinmiyor"))
        item = dict(row)
        item.update({
            "motor_surumu": spec["strategy_version"],
            "kurulum": "PAPER_TOP20",
            "karar": "PAPER_SHADOW",
            "paper_model_id": model_id,
            "paper_model_role": spec["role"],
            "paper_cohort_month": cohort_month,
            "paper_rank": rank,
            "paper_target_weight": min(base_weight, sector_cap / sector_counts[sector]),
            "paper_factor_weights": dict(spec["weights"]),
        })
        result.append(item)
    return result


def recorded_models_for_month(db_path: str, cohort_month: str) -> set[str]:
    if not os.path.exists(db_path):
        return set()
    conn = sqlite3.connect(db_path)
    try:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(hisse_sinyalleri)")
        }
        if "cohort_month" not in columns or "strategy_version" not in columns:
            return set()
        versions = tuple(spec["strategy_version"] for spec in MODEL_SPECS.values())
        placeholders = ", ".join("?" for _ in versions)
        rows = conn.execute(
            f"""SELECT DISTINCT strategy_version FROM hisse_sinyalleri
                WHERE cohort_month = ? AND strategy_version IN ({placeholders})""",
            [cohort_month, *versions],
        ).fetchall()
        by_version = {
            spec["strategy_version"]: model_id
            for model_id, spec in MODEL_SPECS.items()
        }
        return {by_version[row[0]] for row in rows if row[0] in by_version}
    finally:
        conn.close()


def _empty_summary() -> dict:
    return {
        "status": "COLLECTING_GENUINELY_NEW_DATA",
        "production_valid": False,
        "paired_mature_cohorts": 0,
        "required_paired_mature_cohorts": DECISION_RULE[
            "minimum_paired_mature_cohorts"
        ],
        "paired_months": [],
        "models": {},
        "comparison": None,
    }


def shadow_performance_summary(db_path: str) -> dict:
    """Compare paired portfolio-weighted 20-day cohorts, never individual rows."""
    result = _empty_summary()
    if not os.path.exists(db_path):
        return result

    conn = sqlite3.connect(db_path)
    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if not {"hisse_sinyalleri", "hisse_sinyal_sonuclari"}.issubset(tables):
            return result
        signal_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(hisse_sinyalleri)")
        }
        if not {"cohort_month", "target_weight"}.issubset(signal_columns):
            return result

        versions = tuple(spec["strategy_version"] for spec in MODEL_SPECS.values())
        placeholders = ", ".join("?" for _ in versions)
        rows = conn.execute(
            f"""SELECT s.strategy_version, s.cohort_month, s.sembol,
                       s.target_weight,
                       o.getiri_20g, o.excess_spy_20g, o.mae_20g
                FROM hisse_sinyalleri s
                JOIN hisse_sinyal_sonuclari o ON o.signal_id = s.id
                WHERE s.strategy_version IN ({placeholders})
                  AND s.cohort_month IS NOT NULL""",
            versions,
        ).fetchall()
    finally:
        conn.close()

    grouped = defaultdict(list)
    for version, month, symbol, target_weight, stock_return, excess_spy, mae in rows:
        values = tuple(
            _finite(value)
            for value in (target_weight, stock_return, excess_spy, mae)
        )
        if any(value is None for value in values):
            continue
        if values[0] <= 0:
            continue
        grouped[(version, month)].append({
            "symbol": symbol,
            "weight": values[0],
            "return": values[1],
            "excess_spy": values[2],
            "mae": values[3],
        })

    minimum_names = DECISION_RULE["minimum_names_per_mature_cohort"]
    cohorts = defaultdict(dict)
    for (version, month), observations in grouped.items():
        if len(observations) < minimum_names:
            continue
        invested_weight = sum(row["weight"] for row in observations)
        portfolio_return = sum(
            row["weight"] * row["return"] for row in observations
        )
        spy_return = mean(
            row["return"] - row["excess_spy"] for row in observations
        )
        cohorts[version][month] = {
            "names": len(observations),
            "invested_weight": invested_weight,
            "mean_return": portfolio_return,
            "mean_excess_spy": portfolio_return - spy_return,
            "mean_mae": sum(
                row["weight"] * row["mae"] for row in observations
            ),
        }

    baseline = cohorts[BASELINE_VERSION]
    challenger = cohorts[CHALLENGER_VERSION]
    paired_months = sorted(set(baseline) & set(challenger))
    result["paired_mature_cohorts"] = len(paired_months)
    result["paired_months"] = paired_months

    for model_id, spec in MODEL_SPECS.items():
        model_cohorts = cohorts[spec["strategy_version"]]
        paired_rows = [model_cohorts[month] for month in paired_months]
        result["models"][model_id] = {
            "strategy_version": spec["strategy_version"],
            "mature_cohorts": len(model_cohorts),
            "paired_mean_return": (
                mean(row["mean_return"] for row in paired_rows) if paired_rows else None
            ),
            "paired_median_return": (
                median(row["mean_return"] for row in paired_rows) if paired_rows else None
            ),
            "paired_mean_excess_spy": (
                mean(row["mean_excess_spy"] for row in paired_rows)
                if paired_rows else None
            ),
            "paired_mean_mae": (
                mean(row["mean_mae"] for row in paired_rows) if paired_rows else None
            ),
        }

    required = DECISION_RULE["minimum_paired_mature_cohorts"]
    if len(paired_months) < required:
        return result

    comparisons = []
    for month in paired_months:
        base = baseline[month]
        challenger_row = challenger[month]
        comparisons.append({
            "cohort_month": month,
            "return_delta": challenger_row["mean_return"] - base["mean_return"],
            "excess_spy_delta": (
                challenger_row["mean_excess_spy"] - base["mean_excess_spy"]
            ),
            "mae_delta": challenger_row["mean_mae"] - base["mean_mae"],
        })

    excess_wins = sum(row["excess_spy_delta"] > 0 for row in comparisons)
    excess_win_rate = excess_wins / len(comparisons)
    average_return_delta = mean(row["return_delta"] for row in comparisons)
    average_excess_delta = mean(row["excess_spy_delta"] for row in comparisons)
    average_mae_delta = mean(row["mae_delta"] for row in comparisons)
    passed = (
        excess_win_rate >= DECISION_RULE["minimum_challenger_excess_win_rate"]
        and average_return_delta > 0
        and average_excess_delta > 0
        and average_mae_delta
        >= -DECISION_RULE["maximum_average_mae_deterioration"]
    )
    result["status"] = (
        "PAPER_REVIEW_PASS_RESEARCH_ONLY"
        if passed else "PAPER_MODEL_REVIEW_REQUIRED"
    )
    result["comparison"] = {
        "challenger_excess_wins": excess_wins,
        "challenger_excess_win_rate": excess_win_rate,
        "average_return_delta": average_return_delta,
        "average_excess_spy_delta": average_excess_delta,
        "average_mae_delta": average_mae_delta,
        "passed": passed,
    }
    return result


def update_manifest(path: str | Path, summary: Mapping[str, object]) -> None:
    manifest_path = Path(path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["status"] = summary["status"]
    manifest["production_valid"] = False
    manifest["last_checked_at"] = datetime.now(timezone.utc).isoformat()
    manifest["latest_summary"] = dict(summary)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
