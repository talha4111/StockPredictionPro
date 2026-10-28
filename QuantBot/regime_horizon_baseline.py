"""Maliyet sonrası, kronolojik rejim/ufuk referans araştırması.

Bu çalışma model seçmez ve emir üretmez. Amaç, V6 modelinin başarısız olduğu
1 saatlik long hipotezinde basit, anlaşılabilir stratejilerin dahi tekrar eden
bir edge taşıyıp taşımadığını görmek; böylece sonraki model hipotezini veriye
dayandırmaktır.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "backtest_reports"
DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
HORIZONS = (4, 8, 16)  # 15 dakikalık veride 1, 2 ve 4 saat
ROUND_TRIP_COST_RATE = 0.001
TRAIN_FRACTION = 0.75


def parse_symbols(raw: str) -> list[str]:
    symbols: list[str] = []
    for item in str(raw or "").replace(";", ",").split(","):
        symbol = item.strip().upper().replace(":USDT", "")
        if not symbol:
            continue
        if "/" not in symbol and symbol.endswith("USDT"):
            symbol = f"{symbol[:-4]}/USDT"
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def future_return_next_open(
    frame: pd.DataFrame,
    horizon_bars: int,
) -> pd.Series:
    """Kararı kapanışta verip bir sonraki açılıştan sabit ufukta çıkar."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars en az 1 olmalı.")
    required = {"open", "Hedef_Close"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Gerekli kolonlar eksik: {sorted(missing)}")
    entry = pd.to_numeric(frame["open"], errors="coerce").shift(-1)
    exit_price = pd.to_numeric(frame["Hedef_Close"], errors="coerce").shift(
        -horizon_bars
    )
    result = (exit_price / entry) - 1.0
    return result.replace([np.inf, -np.inf], np.nan)


def non_overlapping_metrics(
    signals: pd.Series,
    gross_returns: pd.Series,
    *,
    horizon_bars: int,
    cost_rate: float = ROUND_TRIP_COST_RATE,
) -> dict[str, float | int]:
    """Aynı anda pozisyon taşımayan sabit-ufuk long işlemlerini ölçer."""
    if horizon_bars < 1:
        raise ValueError("horizon_bars en az 1 olmalı.")
    selected: list[float] = []
    next_allowed = 0
    signal_values = signals.fillna(False).astype(bool).to_numpy()
    return_values = pd.to_numeric(gross_returns, errors="coerce").to_numpy()
    for index, (enabled, gross_return) in enumerate(
        zip(signal_values, return_values)
    ):
        if index < next_allowed or not enabled or not np.isfinite(gross_return):
            continue
        selected.append(float(gross_return) - float(cost_rate))
        next_allowed = index + horizon_bars

    returns = np.asarray(selected, dtype=float)
    if not len(returns):
        return {
            "signals": 0,
            "wins": 0,
            "win_rate": 0.0,
            "net_return": 0.0,
            "profit_factor": 0.0,
            "max_drawdown": 0.0,
        }
    equity = np.cumprod(1.0 + returns)
    high_watermark = np.maximum.accumulate(equity)
    drawdown = 1.0 - (equity / high_watermark)
    profits = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    return {
        "signals": int(len(returns)),
        "wins": int((returns > 0).sum()),
        "win_rate": round(float((returns > 0).mean()), 6),
        "net_return": round(float(np.prod(1.0 + returns) - 1.0), 8),
        "profit_factor": round(
            float(profits / losses) if losses else (999.0 if profits else 0.0),
            6,
        ),
        "max_drawdown": round(float(drawdown.max()), 8),
    }


def _always_long(frame: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=frame.index)


def _trend_continuation(frame: pd.DataFrame) -> pd.Series:
    return (
        (frame["EMA_Slope"] > 0.0)
        & (frame["ADX"] >= 20.0)
        & (frame["CHOP"] <= 55.0)
        & (frame["Hedef_Ret"] > 0.0)
    )


def _volume_breakout(frame: pd.DataFrame) -> pd.Series:
    return (
        (frame["Hedef_Ret"] >= 0.001)
        & (frame["Volume_ZScore"] >= 1.0)
        & (frame["RSI"] >= 50.0)
        & (frame["RSI"] <= 75.0)
    )


def _oversold_reversion(frame: pd.DataFrame) -> pd.Series:
    return (
        (frame["RSI"] <= 30.0)
        & (frame["CHOP"] >= 45.0)
        & (frame["EMA_Slope"] >= -0.10)
    )


RULES: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "always_long": _always_long,
    "trend_continuation": _trend_continuation,
    "volume_breakout": _volume_breakout,
    "oversold_reversion": _oversold_reversion,
}


def evaluate_frame(
    symbol: str,
    frame: pd.DataFrame,
    *,
    horizons: tuple[int, ...] = HORIZONS,
    cost_rate: float = ROUND_TRIP_COST_RATE,
) -> list[dict[str, object]]:
    """Her kuralı sızıntısız araştırma ve son holdout diliminde ölçer."""
    if len(frame) < 500:
        raise ValueError("Kronolojik test için en az 500 satır gerekli.")
    split_at = int(len(frame) * TRAIN_FRACTION)
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        gross_returns = future_return_next_open(frame, horizon)
        train_end = split_at - horizon
        if train_end <= 0:
            raise ValueError("Eğitim bölümü ufuk için yetersiz.")
        train_index = frame.index[:train_end]
        holdout_index = frame.index[split_at:]
        for rule_name, rule in RULES.items():
            signal = rule(frame).fillna(False).astype(bool)
            train = non_overlapping_metrics(
                signal.loc[train_index],
                gross_returns.loc[train_index],
                horizon_bars=horizon,
                cost_rate=cost_rate,
            )
            holdout = non_overlapping_metrics(
                signal.loc[holdout_index],
                gross_returns.loc[holdout_index],
                horizon_bars=horizon,
                cost_rate=cost_rate,
            )
            qualified = (
                train["signals"] >= 20
                and train["net_return"] > 0
                and train["profit_factor"] >= 1.10
                and holdout["signals"] >= 8
                and holdout["net_return"] > 0
                and holdout["profit_factor"] >= 1.0
            )
            rows.append(
                {
                    "symbol": symbol,
                    "rule": rule_name,
                    "horizon_bars": horizon,
                    "horizon_minutes": horizon * 15,
                    "train": train,
                    "holdout": holdout,
                    "qualified_single_asset": bool(qualified),
                }
            )
    return rows


def aggregate(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int], list[dict[str, object]]] = {}
    for row in rows:
        if "rule" not in row:
            continue
        grouped.setdefault((str(row["rule"]), int(row["horizon_bars"])), []).append(row)
    result = []
    for (rule, horizon), group in grouped.items():
        train = [item["train"] for item in group]
        holdout = [item["holdout"] for item in group]
        holdout_positive_assets = sum(
            float(item["net_return"]) > 0 and int(item["signals"]) >= 8
            for item in holdout
        )
        result.append(
            {
                "rule": rule,
                "horizon_bars": horizon,
                "horizon_minutes": horizon * 15,
                "assets": len(group),
                "train_net_return_sum": round(
                    sum(float(item["net_return"]) for item in train), 8
                ),
                "holdout_net_return_sum": round(
                    sum(float(item["net_return"]) for item in holdout), 8
                ),
                "holdout_signal_count": sum(
                    int(item["signals"]) for item in holdout
                ),
                "holdout_positive_assets": holdout_positive_assets,
                "qualified_assets": sum(
                    bool(item["qualified_single_asset"]) for item in group
                ),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            int(item["holdout_positive_assets"]),
            float(item["holdout_net_return_sum"]),
        ),
        reverse=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Regime/horizon baseline research (order-free)"
    )
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--history-limit", type=int, default=10000)
    parser.add_argument("--max-ohlcv-pages", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = parse_symbols(args.symbols)
    if not symbols:
        raise ValueError("En az bir sembol gerekli.")
    config = {
        "symbols": symbols,
        "timeframe": args.timeframe,
        "history_limit": max(500, int(args.history_limit)),
        "max_ohlcv_pages": min(32, max(1, int(args.max_ohlcv_pages))),
        "feature_schema_version": 6,
        "horizons": list(HORIZONS),
        "round_trip_cost_rate": ROUND_TRIP_COST_RATE,
        "train_fraction": TRAIN_FRACTION,
        "rules": list(RULES),
        "live_prediction_enabled": False,
    }
    if args.dry_run:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    from tarayici import veri_getir_dortlu

    run_dir = REPORT_DIR / (
        "regime_baseline_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    print(f"[START] symbols={symbols}", flush=True)
    for symbol in symbols:
        frame = veri_getir_dortlu(
            symbol,
            "BTC/USDT",
            timeframe=args.timeframe,
            feature_schema_version=6,
            history_limit=config["history_limit"],
            max_ohlcv_pages=config["max_ohlcv_pages"],
        )
        if frame is None or frame.empty:
            rows.append({"symbol": symbol, "error": "veri_alinamadi"})
            continue
        print(f"[DATA] {symbol} rows={len(frame)}", flush=True)
        rows.extend(evaluate_frame(symbol, frame))

    summary = aggregate(rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": config,
        "summary": summary,
        "rows": rows,
    }
    (run_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for item in summary:
        print(
            f"[RESULT] {item['rule']} {item['horizon_minutes']}m "
            f"holdout={item['holdout_net_return_sum']:+.4f} "
            f"positive_assets={item['holdout_positive_assets']}/{item['assets']}",
            flush=True,
        )
    print(f"[DONE] report={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
