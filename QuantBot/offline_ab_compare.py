"""Cost-aware offline comparison using the production schema-4 model pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import os
import time
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "backtest_reports"
CANDIDATES = (
    {"name": "450_8", "n_estimators": 450, "max_depth": 8, "prefix": "offline_450_8"},
    {"name": "400_5", "n_estimators": 400, "max_depth": 5, "prefix": "offline_400_5"},
)
DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")


def parse_symbols(raw: str) -> list[str]:
    symbols = []
    for item in str(raw or "").replace(";", ",").split(","):
        symbol = item.strip().upper().replace(":USDT", "")
        if not symbol:
            continue
        if "/" not in symbol and symbol.endswith("USDT"):
            symbol = f"{symbol[:-4]}/USDT"
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    for candidate in CANDIDATES:
        selected = [row for row in rows if row.get("candidate") == candidate["name"]]
        if not selected:
            continue
        holdout_rows = sum(int(row["holdout_rows"]) for row in selected)
        signals = sum(int(row["signals"]) for row in selected)
        wins = sum(int(row["wins"]) for row in selected)
        net_pnl = sum(float(row["net_pnl_usdt"]) for row in selected)
        weighted_brier = sum(
            float(row["brier_score"]) * int(row["holdout_rows"]) for row in selected
        ) / max(holdout_rows, 1)
        weighted_accuracy = sum(
            float(row["balanced_accuracy"]) * int(row["holdout_rows"])
            for row in selected
        ) / max(holdout_rows, 1)
        summary.append(
            {
                "candidate": candidate["name"],
                "symbols": len(selected),
                "holdout_rows": holdout_rows,
                "signals": signals,
                "wins": wins,
                "win_rate_pct": round(100.0 * wins / signals, 2) if signals else 0.0,
                "net_pnl_usdt": round(net_pnl, 6),
                "weighted_brier": round(weighted_brier, 6),
                "weighted_balanced_accuracy": round(weighted_accuracy, 6),
                "max_drawdown_pct": round(
                    100.0 * max(float(row["max_drawdown"]) for row in selected), 4
                ),
                "quality_passes": sum(float(row["walk_forward_score"]) >= 0.50 for row in selected),
            }
        )
    summary.sort(
        key=lambda row: (float(row["net_pnl_usdt"]), -float(row["weighted_brier"])),
        reverse=True,
    )
    for rank, row in enumerate(summary, 1):
        row["rank"] = rank
    return summary


def run_candidate(
    *,
    symbol: str,
    frame,
    candidate: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    from ai_core import BeyinMotoru

    artifact_dir.mkdir(parents=True, exist_ok=True)
    motor = BeyinMotoru(
        n_estimators=int(candidate["n_estimators"]),
        max_depth=int(candidate["max_depth"]),
        model_prefix=str(candidate["prefix"]),
    )
    safe_symbol = symbol.replace("/", "-")
    meta_path = artifact_dir / f"{candidate['prefix']}_{safe_symbol}_meta.json"
    old_cwd = Path.cwd()
    started = time.time()
    try:
        os.chdir(artifact_dir)
        with open(os.devnull, "w", encoding="utf-8") as quiet_output:
            with redirect_stdout(quiet_output):
                motor.model_egit(symbol, frame.copy(), is_crypto=True)
    finally:
        os.chdir(old_cwd)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    signals = int(meta.get("recent_signal_count", 0))
    win_rate = float(meta.get("recent_signal_win_rate", 0.0))
    return {
        "candidate": candidate["name"],
        "symbol": symbol,
        "n_estimators": candidate["n_estimators"],
        "max_depth": candidate["max_depth"],
        "schema": meta.get("model_schema_version"),
        "training_rows": int(meta.get("egitim_mum_sayisi", 0)),
        "holdout_rows": int(meta.get("recent_holdout_rows", 0)),
        "signals": signals,
        "wins": int(round(signals * win_rate)),
        "win_rate_pct": round(100.0 * win_rate, 4),
        "net_pnl_usdt": round(100.0 * float(meta.get("recent_strategy_net_return", 0.0)), 6),
        "profit_factor": float(meta.get("recent_strategy_profit_factor", 0.0)),
        "max_drawdown": float(meta.get("recent_strategy_max_drawdown", 0.0)),
        "brier_score": float(meta.get("recent_brier_score", 1.0)),
        "balanced_accuracy": float(meta.get("recent_balanced_accuracy", 0.0)),
        "walk_forward_score": float(meta.get("walk_forward_skoru", 0.0)),
        "threshold": float(meta.get("signal_threshold", motor.signal_threshold)),
        "target_min_return": float(meta.get("target_min_return", motor.min_target_return)),
        "round_trip_cost_rate": float(
            meta.get("round_trip_cost_rate", motor.round_trip_cost_rate)
        ),
        "duration_sec": round(time.time() - started, 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Production-equivalent 450/8 vs 400/5 offline holdout")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        raise ValueError("En az bir sembol gerekli.")
    config = {
        "symbols": symbols,
        "timeframe": args.timeframe,
        "candidates": list(CANDIDATES),
        "schema": 4,
        "horizon_bars": 4,
        "signal_threshold": 0.60,
        "target_min_return": 0.0015,
        "round_trip_cost_rate": 0.001,
        "trade_mode": "LONG_ONLY",
        "holdout_bars": 200,
    }
    if args.dry_run:
        print(json.dumps(config, ensure_ascii=True, indent=2))
        return 0

    from tarayici import veri_getir_dortlu

    run_dir = REPORT_DIR / ("offline_ab_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    artifact_root = run_dir / "model_artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    print(f"[START] symbols={symbols} timeframe={args.timeframe}", flush=True)
    print(f"[REPORT] {run_dir}", flush=True)
    for symbol in symbols:
        print(f"[DATA] {symbol}", flush=True)
        frame = veri_getir_dortlu(symbol, "BTC/USDT", timeframe=args.timeframe)
        if frame is None or frame.empty:
            errors.append({"symbol": symbol, "candidate": "all", "error": "veri alinamadi"})
            continue
        print(f"  rows={len(frame)}", flush=True)
        for candidate in CANDIDATES:
            print(f"  [MODEL] {candidate['name']}", flush=True)
            try:
                row = run_candidate(
                    symbol=symbol,
                    frame=frame,
                    candidate=candidate,
                    artifact_dir=artifact_root / symbol.replace("/", "-") / candidate["name"],
                )
                rows.append(row)
                write_csv(run_dir / "raw_results.csv", rows)
                print(
                    f"    signals={row['signals']} net={row['net_pnl_usdt']:+.4f} "
                    f"brier={row['brier_score']:.4f}",
                    flush=True,
                )
            except Exception as exc:
                errors.append(
                    {
                        "symbol": symbol,
                        "candidate": str(candidate["name"]),
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(f"    ERROR {type(exc).__name__}: {exc}", flush=True)

    summary = aggregate(rows)
    write_csv(run_dir / "summary.csv", summary)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": config,
        "summary": summary,
        "raw_results": rows,
        "errors": errors,
    }
    (run_dir / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("[SUMMARY]", flush=True)
    for row in summary:
        print(
            f"  #{row['rank']} {row['candidate']} signals={row['signals']} "
            f"net={row['net_pnl_usdt']:+.4f} brier={row['weighted_brier']:.4f}",
            flush=True,
        )
    print(f"[DONE] {run_dir}", flush=True)
    return 0 if rows and not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
