"""Rolling out-of-sample research grid for Factor v3.1 weights.

This module is a local shortlist tool. It deliberately keeps the result in
diagnostic status when the current static stock universe is used. Shortlisted
weights must still pass the historical-universe QuantConnect validation.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

import numpy as np
import pandas as pd

from sec_point_in_time import SECCompanyFactsClient, SECPointInTimeProvider
from stock_factor_robustness import (
    period_slice_metrics,
    selection_concentration,
)
from stock_walkforward import (
    WalkForwardConfig,
    _portfolio_metrics,
    download_price_histories,
    normalize_history,
    run_walk_forward,
)


WEIGHT_GRID_VERSION = "stock-factor-weight-grid-v1.0"
MOMENTUM_WEIGHTS = (0.0, 0.10, 0.20)
RISK_WEIGHTS = (0.05, 0.10, 0.15)
BASELINE_WEIGHTS = {
    "quality": 0.35,
    "value": 0.20,
    "momentum": 0.30,
    "risk": 0.15,
}


def candidate_specs() -> list[dict]:
    return [
        {
            "name": f"m{int(momentum * 100):02d}_r{int(risk * 100):02d}",
            "quality": 0.35,
            "value": 0.20,
            "momentum": momentum,
            "risk": risk,
        }
        for momentum in MOMENTUM_WEIGHTS
        for risk in RISK_WEIGHTS
    ]


def risk_adjusted_objective(metrics: Mapping[str, object]) -> Optional[float]:
    """Transparent training objective; costs are already included in returns."""
    annualized = metrics.get("annualized_return")
    drawdown = metrics.get("max_drawdown")
    sharpe = metrics.get("sharpe_zero_rf")
    periods = int(metrics.get("periods") or 0)
    values = (annualized, drawdown, sharpe)
    if periods < 12 or any(value is None for value in values):
        return None
    values = tuple(float(value) for value in values)
    if not all(math.isfinite(value) for value in values):
        return None
    annualized_value, drawdown_value, sharpe_value = values
    return float(annualized_value - abs(drawdown_value) + 0.05 * sharpe_value)


def _period_map(result: Mapping[str, object]) -> dict[str, dict]:
    return {period["signal_date"]: period for period in result.get("periods", [])}


def _relative_summary(periods: list[dict]) -> dict:
    strategy = _portfolio_metrics([row["net_return"] for row in periods])
    spy = _portfolio_metrics([row["spy_return"] for row in periods])
    equal_weight = _portfolio_metrics([row["equal_weight_return"] for row in periods])

    def relative(left: Mapping[str, object], right: Mapping[str, object]):
        left_return = left.get("cumulative_return")
        right_return = right.get("cumulative_return")
        if left_return is None or right_return is None or 1.0 + float(right_return) <= 0:
            return None
        return float((1.0 + float(left_return)) / (1.0 + float(right_return)) - 1.0)

    return {
        "strategy": strategy,
        "spy": spy,
        "equal_weight": equal_weight,
        "relative_vs_spy": relative(strategy, spy),
        "relative_vs_equal_weight": relative(strategy, equal_weight),
    }


def regime_summary(periods: list[dict]) -> dict:
    """Report results in contemporaneous SPY up/down months, never as a signal."""
    regimes = {
        "spy_up_months": [row for row in periods if row["spy_return"] >= 0],
        "spy_down_months": [row for row in periods if row["spy_return"] < 0],
    }
    return {
        name: _relative_summary(rows)
        for name, rows in regimes.items()
    }


def rolling_weight_selection(
    candidate_results: Mapping[str, Mapping[str, object]],
    baseline_result: Mapping[str, object],
    train_months: int = 24,
    test_months: int = 6,
) -> dict:
    if train_months < 12 or test_months < 1:
        raise ValueError("train_months en az 12, test_months en az 1 olmali")
    if not candidate_results:
        raise ValueError("En az bir aday sonucu gerekli")

    maps = {name: _period_map(result) for name, result in candidate_results.items()}
    common_dates = sorted(set.intersection(*(set(rows) for rows in maps.values())))
    if len(common_dates) <= train_months:
        raise ValueError("Rolling secim icin ortak donem sayisi yetersiz")

    folds = []
    stitched = []
    for test_start in range(train_months, len(common_dates), test_months):
        train_dates = common_dates[test_start - train_months:test_start]
        validation_dates = common_dates[test_start:test_start + test_months]
        if not validation_dates:
            continue

        ranked = []
        for name, period_map in maps.items():
            metrics = _portfolio_metrics([period_map[date]["net_return"] for date in train_dates])
            ranked.append({
                "name": name,
                "objective": risk_adjusted_objective(metrics),
                "metrics": metrics,
            })
        ranked.sort(key=lambda row: (
            row["objective"] is None,
            -(row["objective"] if row["objective"] is not None else -1e9),
            row["name"],
        ))
        winner = ranked[0]
        validation_rows = [dict(maps[winner["name"]][date]) for date in validation_dates]
        for row in validation_rows:
            row["selected_variant"] = winner["name"]
        stitched.extend(validation_rows)
        folds.append({
            "train_start": train_dates[0],
            "train_end": train_dates[-1],
            "validation_start": validation_dates[0],
            "validation_end": validation_dates[-1],
            "selected_variant": winner["name"],
            "training_objective": winner["objective"],
            "training_metrics": winner["metrics"],
            "validation": _relative_summary(validation_rows),
        })

    oos_dates = [row["signal_date"] for row in stitched]
    baseline_map = _period_map(baseline_result)
    baseline_periods = [baseline_map[date] for date in oos_dates if date in baseline_map]
    return {
        "train_months": train_months,
        "test_months": test_months,
        "folds": folds,
        "selection_frequency": dict(Counter(
            fold["selected_variant"] for fold in folds
        )),
        "stitched_out_of_sample": _relative_summary(stitched),
        "fixed_baseline_same_months": _relative_summary(baseline_periods),
        "regimes": regime_summary(stitched),
        "oos_start": oos_dates[0] if oos_dates else None,
        "oos_end": oos_dates[-1] if oos_dates else None,
    }


def summarize_candidate(name: str, result: dict) -> dict:
    periods = result["periods"]
    first_date = periods[0]["signal_date"] if periods else ""
    last_date = periods[-1]["signal_date"] if periods else ""
    development = period_slice_metrics(periods, first_date, "2023-12-31")
    validation = period_slice_metrics(periods, "2024-01-01", last_date)
    development_objective = risk_adjusted_objective(development["strategy"])
    validation_objective = risk_adjusted_objective(validation["strategy"])
    stability_score = (
        min(development_objective, validation_objective)
        if development_objective is not None and validation_objective is not None
        else None
    )
    return {
        "name": name,
        "raw_weights": {
            key.replace("_weight", ""): result["config"][key]
            for key in ("quality_weight", "value_weight", "momentum_weight", "risk_weight")
        },
        "normalized_weights": result["config"]["normalized_factor_weights"],
        "validity": result["validity"],
        "full_period": result["metrics"],
        "development": development,
        "validation": validation,
        "regimes": regime_summary(periods),
        "annual_summary": result["annual_summary"],
        "concentration": selection_concentration(periods),
        "development_objective": development_objective,
        "validation_objective": validation_objective,
        "stability_score": stability_score,
    }


def shortlist_candidates(summaries: list[dict], limit: int = 3) -> list[dict]:
    eligible = [
        row for row in summaries
        if row["stability_score"] is not None
        and row["validation"]["relative_vs_spy"] is not None
        and row["validation"]["relative_vs_spy"] > 0
    ]
    pool = eligible or [row for row in summaries if row["stability_score"] is not None]
    ordered = sorted(pool, key=lambda row: (-row["stability_score"], row["name"]))
    return [
        {
            "name": row["name"],
            "raw_weights": row["raw_weights"],
            "normalized_weights": row["normalized_weights"],
            "stability_score": row["stability_score"],
            "validation_relative_vs_spy": row["validation"]["relative_vs_spy"],
            "validation_max_drawdown": row["validation"]["strategy"]["max_drawdown"],
        }
        for row in ordered[:limit]
    ]


def _load_price_cache(path: Path) -> dict[str, pd.DataFrame]:
    payload = pd.read_pickle(path)
    if not isinstance(payload, Mapping):
        raise ValueError("Fiyat onbellegi sembol -> tablo eslemesi olmali")
    return {
        str(symbol): frame
        for symbol, source in payload.items()
        if not (frame := normalize_history(source)).empty
    }


def _run_variant(
    name: str,
    weights: Mapping[str, float],
    histories: Mapping[str, pd.DataFrame],
    sectors: Mapping[str, str],
    benchmark: pd.DataFrame,
    provider: SECPointInTimeProvider,
    start_date: str,
    end_date: str,
) -> dict:
    print(f"\nAgirlik kosusu: {name} {dict(weights)}", flush=True)
    config = WalkForwardConfig(
        start_date=start_date,
        end_date=end_date,
        top_n=20,
        min_positions=5,
        sector_cap=0.25,
        max_position_weight=0.05,
        transaction_cost_bps=25.0,
        cash_buffer=0.005,
        strategy_mode="full_factor",
        fundamental_mode="point_in_time",
        universe_mode="current_static",
        selection_policy="factor_rank",
        quality_weight=weights["quality"],
        value_weight=weights["value"],
        momentum_weight=weights["momentum"],
        risk_weight=weights["risk"],
    )
    result = run_walk_forward(
        histories,
        sectors,
        benchmark,
        config,
        fundamental_provider=provider,
    )
    metrics = result["metrics"]["strategy"]
    print(
        f"  Getiri %{metrics['cumulative_return'] * 100:.2f} | "
        f"CAGR %{metrics['annualized_return'] * 100:.2f} | "
        f"MaxDD %{metrics['max_drawdown'] * 100:.2f} | "
        f"Sharpe {metrics['sharpe_zero_rf']:.3f}",
        flush=True,
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor v3.1 rolling weight grid")
    parser.add_argument("--start-date", default="2021-07-01")
    parser.add_argument("--end-date", default="2026-04-17")
    parser.add_argument("--train-months", type=int, default=24)
    parser.add_argument("--test-months", type=int, default=6)
    parser.add_argument("--price-cache", default=None)
    parser.add_argument("--offline-sec-cache", action="store_true")
    parser.add_argument("--output", default="data/stock_factor_weight_grid.json")
    args = parser.parse_args()

    from stock_value_engine import KURUMSAL_HAVUZ

    if args.price_cache:
        histories = _load_price_cache(Path(args.price_cache))
    else:
        fetch_start = pd.Timestamp(args.start_date) - pd.DateOffset(days=420)
        histories = download_price_histories(
            list(KURUMSAL_HAVUZ) + ["SPY"],
            fetch_start.date().isoformat(),
            args.end_date,
        )
    benchmark = histories.pop("SPY", pd.DataFrame())
    if benchmark.empty or len(histories) < 80:
        raise RuntimeError(f"Fiyat kapsami yetersiz: {len(histories)}/93")

    client = SECCompanyFactsClient.from_env(offline_cache=args.offline_sec_cache)
    provider = SECPointInTimeProvider(client, histories, progress=True)
    baseline_result = _run_variant(
        "baseline",
        BASELINE_WEIGHTS,
        histories,
        KURUMSAL_HAVUZ,
        benchmark,
        provider,
        args.start_date,
        args.end_date,
    )

    results = {}
    for spec in candidate_specs():
        weights = {key: spec[key] for key in ("quality", "value", "momentum", "risk")}
        results[spec["name"]] = _run_variant(
            spec["name"],
            weights,
            histories,
            KURUMSAL_HAVUZ,
            benchmark,
            provider,
            args.start_date,
            args.end_date,
        )

    baseline_summary = summarize_candidate("baseline", baseline_result)
    summaries = [summarize_candidate(name, result) for name, result in results.items()]
    rolling = rolling_weight_selection(
        results,
        baseline_result,
        train_months=args.train_months,
        test_months=args.test_months,
    )
    shortlist = shortlist_candidates(summaries)
    report = {
        "engine_version": WEIGHT_GRID_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "LOCAL_SHORTLIST_ONLY",
        "production_valid": False,
        "period": {"start": args.start_date, "end": args.end_date},
        "controlled_conditions": {
            "top_n": 20,
            "max_position_weight": 0.05,
            "sector_cap": 0.25,
            "transaction_cost_bps": 25.0,
            "cash_buffer": 0.005,
            "fundamentals": "point-in-time SEC CompanyFacts",
            "universe": "current static stock pool",
        },
        "warning": (
            "Current static universe creates survivorship bias. This report may shortlist "
            "weights but cannot promote them to production."
        ),
        "baseline": baseline_summary,
        "candidates": summaries,
        "rolling_selection": rolling,
        "quantconnect_shortlist": shortlist,
        "next_gate": (
            "Run the shortlist in QuantConnect using historical SPY constituents and "
            "point-in-time Morningstar fundamentals."
        ),
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )

    print("\nKisa liste:", flush=True)
    for row in shortlist:
        print(
            f"  {row['name']}: {row['normalized_weights']} | "
            f"dogrulama SPY farki %{row['validation_relative_vs_spy'] * 100:.2f}",
            flush=True,
        )
    print(f"Rapor: {output.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
