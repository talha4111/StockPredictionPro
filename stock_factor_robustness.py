"""Robustness matrix for the point-in-time Factor v3.1 walk-forward test."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from sec_point_in_time import SECCompanyFactsClient, SECPointInTimeProvider
from stock_walkforward import (
    WalkForwardConfig,
    _portfolio_metrics,
    download_price_histories,
    run_walk_forward,
)


def period_slice_metrics(periods: list[dict], start: str, end: str) -> dict:
    selected = [
        period for period in periods
        if start <= period["signal_date"] <= end
    ]
    strategy = _portfolio_metrics([period["net_return"] for period in selected])
    spy = _portfolio_metrics([period["spy_return"] for period in selected])
    equal_weight = _portfolio_metrics([
        period["equal_weight_return"] for period in selected
    ])
    strategy_equity = (
        1.0 + strategy["cumulative_return"]
        if strategy["cumulative_return"] is not None else None
    )
    spy_equity = 1.0 + spy["cumulative_return"] if spy["cumulative_return"] is not None else None
    equal_weight_equity = (
        1.0 + equal_weight["cumulative_return"]
        if equal_weight["cumulative_return"] is not None else None
    )
    return {
        "start": start,
        "end": end,
        "periods": len(selected),
        "strategy": strategy,
        "spy": spy,
        "equal_weight": equal_weight,
        "relative_vs_spy": (
            float(strategy_equity / spy_equity - 1.0)
            if strategy_equity is not None and spy_equity and spy_equity > 0 else None
        ),
        "relative_vs_equal_weight": (
            float(strategy_equity / equal_weight_equity - 1.0)
            if strategy_equity is not None and equal_weight_equity and equal_weight_equity > 0 else None
        ),
    }


def selection_concentration(periods: list[dict]) -> dict:
    counts: dict[str, int] = {}
    total = 0
    for period in periods:
        for selected in period.get("selected", []):
            symbol = selected["symbol"]
            counts[symbol] = counts.get(symbol, 0) + 1
            total += 1
    ordered = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    frequencies = np.asarray(list(counts.values()), dtype=float)
    frequency_weights = frequencies / frequencies.sum() if frequencies.size else np.asarray([])
    return {
        "unique_symbols": len(counts),
        "total_selections": total,
        "top_5_selection_share": (
            float(sum(count for _, count in ordered[:5]) / total) if total else None
        ),
        "selection_hhi": (
            float(np.sum(frequency_weights ** 2)) if frequency_weights.size else None
        ),
        "most_selected": [
            {"symbol": symbol, "months": count}
            for symbol, count in ordered[:10]
        ],
    }


def summarize_variant(
    name: str,
    result: dict,
    development_end: str = "2023-12-31",
    validation_start: str = "2024-01-01",
) -> dict:
    periods = result["periods"]
    first_date = periods[0]["signal_date"] if periods else ""
    last_date = periods[-1]["signal_date"] if periods else ""
    return {
        "name": name,
        "config": result["config"],
        "validity": result["validity"],
        "full_period": result["metrics"],
        "development": period_slice_metrics(periods, first_date, development_end),
        "validation": period_slice_metrics(periods, validation_start, last_date),
        "annual_summary": result["annual_summary"],
        "concentration": selection_concentration(periods),
    }


def robustness_decision(variants: list[dict]) -> dict:
    base_variants = [variant for variant in variants if variant["config"]["transaction_cost_bps"] == 10.0]
    validation_passes = [
        variant["validation"]["relative_vs_spy"] is not None
        and variant["validation"]["relative_vs_spy"] > 0
        for variant in base_variants
    ]
    equal_weight_passes = [
        variant["validation"]["relative_vs_equal_weight"] is not None
        and variant["validation"]["relative_vs_equal_weight"] > 0
        for variant in base_variants
    ]
    high_cost = next((variant for variant in variants if variant["name"] == "top12_cost25"), None)
    high_cost_pass = bool(
        high_cost
        and high_cost["validation"]["relative_vs_spy"] is not None
        and high_cost["validation"]["relative_vs_spy"] > 0
    )
    passed = bool(
        base_variants
        and all(validation_passes)
        and all(equal_weight_passes)
        and high_cost_pass
    )
    return {
        "status": "ROBUSTNESS_PASS" if passed else "MODEL_REVIEW_REQUIRED",
        "all_top_n_beat_spy_in_validation": bool(base_variants and all(validation_passes)),
        "all_top_n_beat_equal_weight_in_validation": bool(
            base_variants and all(equal_weight_passes)
        ),
        "top12_cost25_beats_spy_in_validation": high_cost_pass,
        "note": (
            "This decision does not remove current-universe survivorship bias."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor v3.1 robustness matrix")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--output", default="data/stock_factor_robustness.json")
    args = parser.parse_args()

    from stock_value_engine import KURUMSAL_HAVUZ

    sec_client = SECCompanyFactsClient.from_env()
    end = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    start = end - pd.DateOffset(years=args.years)
    fetch_start = start - pd.DateOffset(days=420)
    symbols = list(KURUMSAL_HAVUZ) + ["SPY"]
    histories = download_price_histories(
        symbols,
        fetch_start.date().isoformat(),
        end.date().isoformat(),
    )
    benchmark = histories.pop("SPY", pd.DataFrame())
    if benchmark.empty or len(histories) < 80:
        raise RuntimeError(f"Fiyat kapsami yetersiz: {len(histories)}/93")

    provider = SECPointInTimeProvider(sec_client, histories, progress=True)
    variant_specs = [
        ("top8_cost10", 8, 10.0),
        ("top12_cost10", 12, 10.0),
        ("top20_cost10", 20, 10.0),
        ("top12_cost25", 12, 25.0),
    ]
    variants = []
    for name, top_n, cost_bps in variant_specs:
        print(f"\nRobustness kosusu: {name}", flush=True)
        config = WalkForwardConfig(
            start_date=start.date().isoformat(),
            end_date=end.date().isoformat(),
            top_n=top_n,
            min_positions=min(5, top_n),
            max_position_weight=1.0 / top_n,
            transaction_cost_bps=cost_bps,
            strategy_mode="full_factor",
            fundamental_mode="point_in_time",
            selection_policy="factor_rank",
        )
        result = run_walk_forward(
            histories,
            KURUMSAL_HAVUZ,
            benchmark,
            config,
            fundamental_provider=provider,
        )
        variants.append(summarize_variant(name, result))
        metrics = result["metrics"]
        print(
            f"  Getiri %{metrics['strategy']['cumulative_return'] * 100:.2f} | "
            f"MaxDD %{metrics['strategy']['max_drawdown'] * 100:.2f} | "
            f"Turnover %{metrics['comparison']['average_monthly_turnover'] * 100:.1f}",
            flush=True,
        )

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": {"start": start.date().isoformat(), "end": end.date().isoformat()},
        "universe_mode": "current_static",
        "decision": robustness_decision(variants),
        "variants": variants,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=True, allow_nan=False),
        encoding="utf-8",
    )
    print(f"\nKarar: {report['decision']['status']}")
    print(f"Rapor: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
