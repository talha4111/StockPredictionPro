"""Run the Top-N factor walk-forward with Norgate's historical S&P universe."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from sec_point_in_time import SECCompanyFactsClient, SECPointInTimeProvider
from stock_norgate_data import NorgateDataAdapter
from stock_walkforward import WalkForwardConfig, _json_default, run_walk_forward


def main() -> int:
    parser = argparse.ArgumentParser(description="Survivorship-aware Norgate factor test")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=20)
    parser.add_argument("--cost-bps", type=float, default=25.0)
    parser.add_argument(
        "--sector-mode",
        choices=("global", "current_gics"),
        default="global",
    )
    parser.add_argument("--output", default="data/stock_walkforward_norgate_top20.json")
    parser.add_argument("--check", action="store_true", help="Yalniz Norgate hazirligini kontrol et")
    args = parser.parse_args()

    adapter = NorgateDataAdapter()
    if args.check:
        print(json.dumps(adapter.readiness(), indent=2, ensure_ascii=True))
        return 0

    end = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    start = end - pd.DateOffset(years=args.years)
    fetch_start = start - pd.DateOffset(days=420)
    bundle = adapter.load_bundle(
        fetch_start,
        end,
        sector_mode=args.sector_mode,
    )

    sec_client = SECCompanyFactsClient.from_env()
    fundamentals = SECPointInTimeProvider(
        sec_client,
        bundle.histories,
        progress=True,
    )
    config = WalkForwardConfig(
        start_date=start.date().isoformat(),
        end_date=end.date().isoformat(),
        top_n=args.top_n,
        min_positions=max(5, args.top_n // 2),
        sector_cap=1.0 if args.sector_mode == "global" else 0.25,
        max_position_weight=min(0.10, 1.0 / args.top_n),
        transaction_cost_bps=args.cost_bps,
        strategy_mode="full_factor",
        fundamental_mode="point_in_time",
        universe_mode="point_in_time",
        selection_policy="factor_rank",
    )
    result = run_walk_forward(
        bundle.histories,
        {},
        bundle.benchmark,
        config,
        fundamental_provider=fundamentals,
        universe_provider=bundle.universe_provider,
    )
    result["norgate_diagnostics"] = bundle.diagnostics

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False, default=_json_default),
        encoding="utf-8",
    )
    strategy = result["metrics"]["strategy"]
    print(f"Rapor: {output.resolve()}")
    print(f"Sinif: {result['validity']['classification']}")
    print(f"Toplam getiri: %{strategy['cumulative_return'] * 100:.2f}")
    print(f"Maksimum dusus: %{strategy['max_drawdown'] * 100:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
