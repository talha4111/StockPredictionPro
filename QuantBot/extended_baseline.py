"""Genişletilmiş Baseline Araştırması — Long + Short + Multi-Timeframe.

Önceki testte sadece 15dk-long test edildi ve edge bulunamadı.
Bu script 3 kör noktayı kapatır:
  1. SHORT tarafı eklendi (düşüş piyasasında edge olabilir)
  2. 1h ve 4h mumlarla da test yapılıyor (maliyet etkisi azalır)
  3. Rejim-adaptif strateji: piyasa yönüne göre long/short seçen kural
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

REPORT_DIR = BASE_DIR / "backtest_reports"
DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
ROUND_TRIP_COST_RATE = 0.001
TRAIN_FRACTION = 0.75


# ─── Return hesaplamaları ───

def future_return_long(frame, horizon_bars):
    """Next-open giriş, sabit ufuk çıkış — LONG."""
    entry = pd.to_numeric(frame["open"], errors="coerce").shift(-1)
    exit_p = pd.to_numeric(frame["Hedef_Close"], errors="coerce").shift(-horizon_bars)
    return ((exit_p / entry) - 1.0).replace([np.inf, -np.inf], np.nan)


def future_return_short(frame, horizon_bars):
    """Next-open giriş, sabit ufuk çıkış — SHORT (fiyat düşerse kâr)."""
    entry = pd.to_numeric(frame["open"], errors="coerce").shift(-1)
    exit_p = pd.to_numeric(frame["Hedef_Close"], errors="coerce").shift(-horizon_bars)
    return ((entry / exit_p) - 1.0).replace([np.inf, -np.inf], np.nan)


# ─── Non-overlapping metrikler ───

def non_overlapping_metrics(signals, gross_returns, horizon_bars, cost_rate=ROUND_TRIP_COST_RATE):
    selected = []
    next_allowed = 0
    sig_arr = signals.fillna(False).astype(bool).to_numpy()
    ret_arr = pd.to_numeric(gross_returns, errors="coerce").to_numpy()
    for i, (enabled, gr) in enumerate(zip(sig_arr, ret_arr)):
        if i < next_allowed or not enabled or not np.isfinite(gr):
            continue
        selected.append(float(gr) - float(cost_rate))
        next_allowed = i + horizon_bars

    returns = np.asarray(selected, dtype=float)
    if not len(returns):
        return {"signals": 0, "wins": 0, "win_rate": 0.0, "net_return": 0.0,
                "profit_factor": 0.0, "max_drawdown": 0.0}
    equity = np.cumprod(1.0 + returns)
    hwm = np.maximum.accumulate(equity)
    dd = 1.0 - (equity / hwm)
    profits = returns[returns > 0].sum()
    losses = abs(returns[returns < 0].sum())
    return {
        "signals": int(len(returns)),
        "wins": int((returns > 0).sum()),
        "win_rate": round(float((returns > 0).mean()), 4),
        "net_return": round(float(np.prod(1.0 + returns) - 1.0), 6),
        "profit_factor": round(float(profits / losses) if losses else (999.0 if profits else 0.0), 4),
        "max_drawdown": round(float(dd.max()), 6),
    }


# ─── Strateji Kuralları ───

# LONG kuralları
def _always_long(f):
    return pd.Series(True, index=f.index)

def _trend_long(f):
    return (f["EMA_Slope"] > 0) & (f["ADX"] >= 20) & (f["CHOP"] <= 55) & (f["Hedef_Ret"] > 0)

def _volume_breakout_long(f):
    return (f["Hedef_Ret"] >= 0.001) & (f["Volume_ZScore"] >= 1.0) & (f["RSI"] >= 50) & (f["RSI"] <= 75)

def _oversold_long(f):
    return (f["RSI"] <= 30) & (f["CHOP"] >= 45) & (f["EMA_Slope"] >= -0.10)

# SHORT kuralları
def _always_short(f):
    return pd.Series(True, index=f.index)

def _trend_short(f):
    """Düşüş trendi: EMA aşağı, ADX güçlü, CHOP düşük, son return negatif."""
    return (f["EMA_Slope"] < 0) & (f["ADX"] >= 20) & (f["CHOP"] <= 55) & (f["Hedef_Ret"] < 0)

def _volume_breakdown_short(f):
    """Hacimli satış: Negatif return + yüksek hacim + RSI zayıflık bölgesinde."""
    return (f["Hedef_Ret"] <= -0.001) & (f["Volume_ZScore"] >= 1.0) & (f["RSI"] >= 25) & (f["RSI"] <= 50)

def _overbought_short(f):
    """Aşırı alım dönüşü: RSI yüksek, piyasa sıkışık, EMA henüz güçlü düşmemiş."""
    return (f["RSI"] >= 70) & (f["CHOP"] >= 45) & (f["EMA_Slope"] <= 0.10)

# ADAPTIF (rejim bazlı)
def _regime_adaptive(f):
    """EMA yönüne göre long veya short sinyali üret. Sonuç: +1 long, -1 short, 0 nötr."""
    long_sig = (f["EMA_Slope"] > 0) & (f["ADX"] >= 18) & (f["RSI"] >= 40) & (f["RSI"] <= 70)
    short_sig = (f["EMA_Slope"] < 0) & (f["ADX"] >= 18) & (f["RSI"] >= 30) & (f["RSI"] <= 60)
    result = pd.Series(0, index=f.index, dtype=int)
    result[long_sig] = 1
    result[short_sig & ~long_sig] = -1
    return result


LONG_RULES = {
    "always_long": _always_long,
    "trend_long": _trend_long,
    "volume_breakout_long": _volume_breakout_long,
    "oversold_long": _oversold_long,
}

SHORT_RULES = {
    "always_short": _always_short,
    "trend_short": _trend_short,
    "volume_breakdown_short": _volume_breakdown_short,
    "overbought_short": _overbought_short,
}


def evaluate_frame(symbol, frame, horizons=(4, 8, 16), cost_rate=ROUND_TRIP_COST_RATE):
    if len(frame) < 500:
        return [{"symbol": symbol, "error": f"yetersiz_veri ({len(frame)} satir)"}]

    split_at = int(len(frame) * TRAIN_FRACTION)
    rows = []

    for horizon in horizons:
        long_ret = future_return_long(frame, horizon)
        short_ret = future_return_short(frame, horizon)
        train_end = split_at - horizon
        if train_end <= 0:
            continue
        train_idx = frame.index[:train_end]
        holdout_idx = frame.index[split_at:]

        # LONG kuralları
        for name, rule in LONG_RULES.items():
            sig = rule(frame).fillna(False).astype(bool)
            train = non_overlapping_metrics(sig.loc[train_idx], long_ret.loc[train_idx], horizon, cost_rate)
            holdout = non_overlapping_metrics(sig.loc[holdout_idx], long_ret.loc[holdout_idx], horizon, cost_rate)
            qualified = (
                train["signals"] >= 20 and train["net_return"] > 0 and train["profit_factor"] >= 1.10
                and holdout["signals"] >= 8 and holdout["net_return"] > 0 and holdout["profit_factor"] >= 1.0
            )
            rows.append({
                "symbol": symbol, "direction": "LONG", "rule": name,
                "horizon_bars": horizon, "horizon_minutes": horizon * 15,
                "train": train, "holdout": holdout, "qualified": bool(qualified),
            })

        # SHORT kuralları
        for name, rule in SHORT_RULES.items():
            sig = rule(frame).fillna(False).astype(bool)
            train = non_overlapping_metrics(sig.loc[train_idx], short_ret.loc[train_idx], horizon, cost_rate)
            holdout = non_overlapping_metrics(sig.loc[holdout_idx], short_ret.loc[holdout_idx], horizon, cost_rate)
            qualified = (
                train["signals"] >= 20 and train["net_return"] > 0 and train["profit_factor"] >= 1.10
                and holdout["signals"] >= 8 and holdout["net_return"] > 0 and holdout["profit_factor"] >= 1.0
            )
            rows.append({
                "symbol": symbol, "direction": "SHORT", "rule": name,
                "horizon_bars": horizon, "horizon_minutes": horizon * 15,
                "train": train, "holdout": holdout, "qualified": bool(qualified),
            })

        # ADAPTIF (long+short birlikte)
        adaptive = _regime_adaptive(frame)
        long_mask = (adaptive == 1)
        short_mask = (adaptive == -1)
        # Long bacağı
        adp_long_train = non_overlapping_metrics(long_mask.loc[train_idx], long_ret.loc[train_idx], horizon, cost_rate)
        adp_long_holdout = non_overlapping_metrics(long_mask.loc[holdout_idx], long_ret.loc[holdout_idx], horizon, cost_rate)
        # Short bacağı
        adp_short_train = non_overlapping_metrics(short_mask.loc[train_idx], short_ret.loc[train_idx], horizon, cost_rate)
        adp_short_holdout = non_overlapping_metrics(short_mask.loc[holdout_idx], short_ret.loc[holdout_idx], horizon, cost_rate)
        # Birleşik
        combined_train_net = adp_long_train["net_return"] + adp_short_train["net_return"]
        combined_holdout_net = adp_long_holdout["net_return"] + adp_short_holdout["net_return"]
        combined_train_signals = adp_long_train["signals"] + adp_short_train["signals"]
        combined_holdout_signals = adp_long_holdout["signals"] + adp_short_holdout["signals"]
        rows.append({
            "symbol": symbol, "direction": "ADAPTIVE", "rule": "regime_adaptive",
            "horizon_bars": horizon, "horizon_minutes": horizon * 15,
            "train": {
                "signals": combined_train_signals,
                "net_return": round(combined_train_net, 6),
                "long_net": adp_long_train["net_return"],
                "short_net": adp_short_train["net_return"],
                "long_signals": adp_long_train["signals"],
                "short_signals": adp_short_train["signals"],
            },
            "holdout": {
                "signals": combined_holdout_signals,
                "net_return": round(combined_holdout_net, 6),
                "long_net": adp_long_holdout["net_return"],
                "short_net": adp_short_holdout["net_return"],
                "long_signals": adp_long_holdout["signals"],
                "short_signals": adp_short_holdout["signals"],
            },
            "qualified": combined_holdout_net > 0 and combined_holdout_signals >= 16,
        })

    return rows


def aggregate(rows):
    grouped = {}
    for r in rows:
        if "error" in r:
            continue
        key = (r["direction"], r["rule"], r["horizon_bars"])
        grouped.setdefault(key, []).append(r)

    result = []
    for (direction, rule, horizon), group in grouped.items():
        holdout_nets = [r["holdout"]["net_return"] for r in group]
        holdout_positive = sum(1 for n in holdout_nets if n > 0)
        qualified_count = sum(1 for r in group if r.get("qualified", False))
        result.append({
            "direction": direction, "rule": rule,
            "horizon_bars": horizon, "horizon_minutes": horizon * 15,
            "assets": len(group),
            "holdout_net_sum": round(sum(holdout_nets), 6),
            "holdout_positive_assets": holdout_positive,
            "qualified_assets": qualified_count,
            "holdout_signals": sum(r["holdout"]["signals"] for r in group),
        })
    return sorted(result, key=lambda x: (x["holdout_positive_assets"], x["holdout_net_sum"]), reverse=True)


def main():
    parser = argparse.ArgumentParser(description="Extended baseline: Long + Short + Multi-TF")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--history-limit", type=int, default=10000)
    parser.add_argument("--max-ohlcv-pages", type=int, default=12)
    args = parser.parse_args()

    from tarayici import veri_getir_dortlu, _V6_FEATURE_SCHEMA

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    run_dir = REPORT_DIR / ("extended_baseline_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)

    all_rows = []
    print(f"[START] symbols={symbols} timeframe={args.timeframe}", flush=True)

    for symbol in symbols:
        print(f"[FETCH] {symbol}...", flush=True)
        frame = veri_getir_dortlu(
            symbol, "BTC/USDT", timeframe=args.timeframe,
            feature_schema_version=_V6_FEATURE_SCHEMA,
            history_limit=args.history_limit,
            max_ohlcv_pages=args.max_ohlcv_pages,
        )
        if frame is None or frame.empty:
            all_rows.append({"symbol": symbol, "error": "veri_alinamadi"})
            print(f"[SKIP] {symbol} veri yok", flush=True)
            continue
        print(f"[DATA] {symbol} rows={len(frame)}", flush=True)
        all_rows.extend(evaluate_frame(symbol, frame))

    summary = aggregate(all_rows)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "symbols": symbols, "timeframe": args.timeframe,
            "history_limit": args.history_limit, "cost_rate": ROUND_TRIP_COST_RATE,
            "train_fraction": TRAIN_FRACTION,
        },
        "summary": summary,
        "rows": all_rows,
    }
    (run_dir / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n" + "=" * 100)
    print("SONUCLAR (holdout_positive_assets ve holdout_net_sum'a gore sirali)")
    print("=" * 100)
    for s in summary:
        tag = "***" if s["holdout_positive_assets"] >= 2 and s["holdout_net_sum"] > 0 else "   "
        print(
            f"{tag} {s['direction']:8s} | {s['rule']:26s} | {s['horizon_minutes']:3d}m | "
            f"holdout_net={s['holdout_net_sum']:+.4f} | "
            f"pos_assets={s['holdout_positive_assets']}/{s['assets']} | "
            f"qualified={s['qualified_assets']}/{s['assets']} | "
            f"signals={s['holdout_signals']}"
        )
    print(f"\n[DONE] report={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
