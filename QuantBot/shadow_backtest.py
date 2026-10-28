from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import ccxt
import numpy as np
import pandas as pd
from slippage_model import slippage_tahmini, slippage_uygula
from rejim import piyasa_rejimi_belirle


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "backtest_reports"

DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
    "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "LTC/USDT",
    "BCH/USDT", "UNI/USDT", "AAVE/USDT", "APT/USDT", "ARB/USDT",
    "OP/USDT", "INJ/USDT", "FIL/USDT", "PENDLE/USDT", "EIGEN/USDT",
    "WLD/USDT", "FET/USDT", "TAO/USDT", "SUI/USDT", "TIA/USDT",
    "ENA/USDT", "PUMP/USDT", "PENGU/USDT", "TRUMP/USDT", "WIF/USDT",
    "WLFI/USDT", "VANRY/USDT", "BANANA/USDT", "DEXE/USDT", "XLM/USDT",
]


@dataclass(frozen=True)
class Variant:
    name: str
    min_confidence: float
    min_rr: float
    min_adx: float
    max_chop: float
    require_volume: bool
    symbol_guard: bool
    margin_pct: float
    max_positions: int
    max_new_per_bar: int
    guard_loss_threshold: float = 8.0
    guard_consecutive_losses: int = 2
    guard_cooldown_hours: float = 18.0
    guard_min_loss: float = 1.0
    guard_heavy_loss_threshold: float = 15.0
    guard_heavy_cooldown_hours: float = 24.0


@dataclass
class Position:
    variant: str
    symbol: str
    entry_ts: int
    entry_time: str
    entry: float
    stop: float
    target: float
    rr: float
    confidence: float
    qty: float
    notional: float
    entry_fee: float
    entry_slippage: float = 0.0
    rejim: str = "BILINMIYOR"


VARIANTS = [
    Variant(
        name="legacy_loose",
        min_confidence=58.0,
        min_rr=1.5,
        min_adx=0.0,
        max_chop=100.0,
        require_volume=False,
        symbol_guard=False,
        margin_pct=0.07,
        max_positions=10,
        max_new_per_bar=5,
    ),
    Variant(
        name="hedge_sniper",
        min_confidence=62.0,
        min_rr=2.4,
        min_adx=16.0,
        max_chop=65.0,
        require_volume=True,
        symbol_guard=False,
        margin_pct=0.07 * 0.75,
        max_positions=5,
        max_new_per_bar=3,
    ),
    Variant(
        name="hedge_symbol_guard",
        min_confidence=62.0,
        min_rr=2.4,
        min_adx=16.0,
        max_chop=65.0,
        require_volume=True,
        symbol_guard=True,
        margin_pct=0.07 * 0.75,
        max_positions=5,
        max_new_per_bar=3,
    ),
    Variant(
        name="hedge_symbol_guard_soft",
        min_confidence=62.0,
        min_rr=2.4,
        min_adx=16.0,
        max_chop=65.0,
        require_volume=True,
        symbol_guard=True,
        margin_pct=0.07 * 0.75,
        max_positions=5,
        max_new_per_bar=3,
        guard_loss_threshold=10.0,
        guard_consecutive_losses=3,
        guard_cooldown_hours=12.0,
        guard_min_loss=1.0,
        guard_heavy_loss_threshold=20.0,
        guard_heavy_cooldown_hours=18.0,
    ),
]


def clean_symbol(symbol: str) -> str:
    raw = str(symbol or "").replace(":USDT", "").strip().upper()
    if not raw:
        return ""
    base = raw.replace("/USDT", "").replace("USDT", "")
    return f"{base}/USDT"


def symbol_candidates(symbol: str) -> list[str]:
    norm = clean_symbol(symbol)
    base = norm.replace("/USDT", "")
    return [f"{base}/USDT:USDT", f"{base}/USDT", f"{base}USDT"]


def ms_to_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="minutes")


def timeframe_ms(exchange: ccxt.Exchange, timeframe: str) -> int:
    return int(exchange.parse_timeframe(timeframe) * 1000)


def make_exchange() -> ccxt.Exchange:
    return ccxt.binanceusdm(
        {
            "enableRateLimit": True,
            "timeout": 20000,
            "options": {"defaultType": "future"},
        }
    )


def resolve_symbols(exchange: ccxt.Exchange, symbols: list[str], limit: int) -> dict[str, str]:
    exchange.load_markets()
    resolved: dict[str, str] = {}
    for requested in symbols:
        norm = clean_symbol(requested)
        if not norm or norm in resolved:
            continue
        for candidate in symbol_candidates(norm):
            if candidate in exchange.markets:
                market = exchange.markets[candidate]
                if market.get("active") is False:
                    continue
                resolved[norm] = candidate
                break
        if len(resolved) >= limit:
            break
    return resolved


def fetch_ohlcv_df(
    exchange: ccxt.Exchange,
    market_symbol: str,
    timeframe: str,
    since_ms: int,
    until_ms: int,
) -> pd.DataFrame:
    step_ms = timeframe_ms(exchange, timeframe)
    rows: list[list[float]] = []
    cursor = since_ms
    seen: set[int] = set()
    while cursor < until_ms:
        batch = exchange.fetch_ohlcv(market_symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        for row in batch:
            ts = int(row[0])
            if since_ms <= ts <= until_ms and ts not in seen:
                rows.append(row)
                seen.add(ts)
        next_cursor = int(batch[-1][0]) + step_ms
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if int(batch[-1][0]) >= until_ms - step_ms:
            break
        time.sleep(exchange.rateLimit / 1000)

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    high = out["high"]
    low = out["low"]
    close = out["close"]
    volume = out["volume"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    out["atr"] = tr.rolling(14).mean()
    out["atr_pct"] = out["atr"] / close.replace(0, np.nan)
    out["ema20"] = close.ewm(span=20, adjust=False).mean()
    out["ema50"] = close.ewm(span=50, adjust=False).mean()
    out["ret3"] = close.pct_change(3)
    out["ret12"] = close.pct_change(12)

    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    atr_smooth = tr.ewm(alpha=1 / 14, adjust=False).mean().replace(0, np.nan)
    plus_di = 100 * pd.Series(plus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr_smooth
    minus_di = 100 * pd.Series(minus_dm, index=out.index).ewm(alpha=1 / 14, adjust=False).mean() / atr_smooth
    dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
    out["adx"] = dx.ewm(alpha=1 / 14, adjust=False).mean()

    tr_sum = tr.rolling(14).sum()
    range_hl = (high.rolling(14).max() - low.rolling(14).min()).replace(0, np.nan)
    out["chop"] = 100 * np.log10((tr_sum / range_hl).replace([np.inf, -np.inf], np.nan)) / math.log10(14)

    vol_mean = volume.rolling(48).mean()
    vol_std = volume.rolling(48).std().replace(0, np.nan)
    out["vol_z"] = (volume - vol_mean) / vol_std
    return out.dropna()


def enrich_with_btc(symbol_frames: dict[str, pd.DataFrame]) -> None:
    btc = symbol_frames.get("BTC/USDT")
    if btc is None or btc.empty:
        for df in symbol_frames.values():
            df["btc_ret12"] = 0.0
            df["btc_trend_ok"] = True
        return
    btc_features = btc[["ret12", "ema20", "ema50", "close"]].copy()
    btc_features["btc_ret12"] = btc_features["ret12"]
    btc_features["btc_trend_ok"] = (
        (btc_features["close"] > btc_features["ema50"])
        & (btc_features["ema20"] > btc_features["ema50"])
    )
    btc_features = btc_features[["btc_ret12", "btc_trend_ok"]]
    for symbol, df in list(symbol_frames.items()):
        merged = df.join(btc_features, how="left")
        merged["btc_ret12"] = merged["btc_ret12"].fillna(0.0)
        merged["btc_trend_ok"] = merged["btc_trend_ok"].fillna(True)
        symbol_frames[symbol] = merged


def confidence_and_rr(row: pd.Series) -> tuple[float, float]:
    trend = float(row["ema20"] / row["ema50"] - 1.0)
    ret3 = float(row["ret3"])
    ret12 = float(row["ret12"])
    adx = float(row["adx"])
    chop = float(row["chop"])
    vol_z = float(row["vol_z"])
    btc_ret = float(row.get("btc_ret12", 0.0))
    btc_ok = bool(row.get("btc_trend_ok", True))

    confidence = 50.0
    confidence += float(np.clip(trend * 1800, -12, 12))
    confidence += float(np.clip(ret3 * 900, -9, 9))
    confidence += float(np.clip(ret12 * 450, -10, 10))
    confidence += float(np.clip((adx - 14) * 0.55, -6, 10))
    confidence += float(np.clip((60 - chop) * 0.28, -8, 8))
    confidence += float(np.clip(vol_z * 3.0, -5, 8))
    confidence += 4.0 if btc_ok and btc_ret > -0.008 else 0.0
    confidence -= 7.0 if btc_ret < -0.018 else 0.0

    rr = 1.55
    rr += float(np.clip((adx - 14) / 18, 0, 0.95))
    rr += float(np.clip((66 - chop) / 23, 0, 0.75))
    rr += float(np.clip(vol_z / 2.5, 0, 0.45))
    rr += float(np.clip((ret12 * 100), 0, 0.45))
    if confidence >= 72:
        rr += 0.35
    elif confidence >= 66:
        rr += 0.18
    return round(confidence, 3), round(min(max(rr, 1.1), 3.6), 3)


def signal_candidate(row: pd.Series, variant: Variant) -> dict[str, Any] | None:
    atr = float(row.get("atr", 0.0))
    close = float(row.get("close", 0.0))
    if close <= 0 or atr <= 0:
        return None
    if not (0.0015 <= float(row.get("atr_pct", 0.0)) <= 0.12):
        return None
    if not (close > float(row["ema20"]) and float(row["ema20"]) >= float(row["ema50"]) * 0.998):
        return None
    if float(row["ret3"]) <= -0.002 or float(row["ret12"]) <= -0.012:
        return None

    confidence, rr = confidence_and_rr(row)
    if confidence < variant.min_confidence or rr < variant.min_rr:
        return None
    if float(row["adx"]) < variant.min_adx or float(row["chop"]) > variant.max_chop:
        return None
    if variant.require_volume and float(row["vol_z"]) < 0.0 and confidence < 72.0:
        return None

    stop_distance = max(atr * 1.15, close * 0.0065)
    return {
        "confidence": confidence,
        "rr": rr,
        "stop_distance": stop_distance,
        "score": confidence + (rr * 8.0) + max(0.0, float(row["vol_z"])) * 1.5,
    }


def guard_allows(guard_state: dict[str, Any], symbol: str, ts: int) -> bool:
    state = guard_state.setdefault(symbol, {"cooldown_until": 0, "history": []})
    return int(state.get("cooldown_until") or 0) <= ts


def update_guard(variant: Variant, guard_state: dict[str, Any], symbol: str, ts: int, pnl: float) -> None:
    state = guard_state.setdefault(symbol, {"cooldown_until": 0, "history": []})
    history = list(state.get("history") or [])
    history.append({"ts": int(ts), "pnl": float(pnl)})
    cutoff = int(ts) - 24 * 60 * 60 * 1000
    history = [item for item in history if int(item["ts"]) >= cutoff]
    state["history"] = history
    net = sum(float(item["pnl"]) for item in history)
    neg_count = sum(1 for item in history if float(item["pnl"]) <= -variant.guard_min_loss)
    if net <= -variant.guard_heavy_loss_threshold:
        state["cooldown_until"] = int(ts) + int(variant.guard_heavy_cooldown_hours * 60 * 60 * 1000)
    elif net <= -variant.guard_loss_threshold or (
        neg_count >= variant.guard_consecutive_losses and net <= -variant.guard_min_loss
    ):
        state["cooldown_until"] = int(ts) + int(variant.guard_cooldown_hours * 60 * 60 * 1000)


def close_position(
    position: Position,
    row: pd.Series,
    ts: int,
    equity: float,
    fee_rate: float,
    reason_override: str | None = None,
) -> tuple[float, dict[str, Any]] | None:
    low = float(row["low"])
    high = float(row["high"])
    close = float(row["close"])
    exit_price = None
    reason = reason_override or ""

    exit_slippage_pct = 0.0
    if reason_override:
        hacim_24s = float(row.get("volume", 0.0)) * 96 * close
        atr_pct = float(row.get("atr_pct", 0.0))
        kayma = slippage_tahmini(hacim_24s, atr_pct, position.notional, is_stop=False)
        exit_price = slippage_uygula(close, kayma, "LONG", False)
        exit_slippage_pct = kayma
    else:
        hit_stop = low <= position.stop
        hit_target = high >= position.target
        
        hacim_24s = float(row.get("volume", 0.0)) * 96 * close
        atr_pct = float(row.get("atr_pct", 0.0))
        
        if hit_stop and hit_target:
            kayma = slippage_tahmini(hacim_24s, atr_pct, position.notional, is_stop=True)
            exit_price = slippage_uygula(position.stop, kayma, "LONG", False)
            reason = "stop_first_same_bar"
            exit_slippage_pct = kayma
        elif hit_stop:
            kayma = slippage_tahmini(hacim_24s, atr_pct, position.notional, is_stop=True)
            exit_price = slippage_uygula(position.stop, kayma, "LONG", False)
            reason = "stop"
            exit_slippage_pct = kayma
        elif hit_target:
            kayma = slippage_tahmini(hacim_24s, atr_pct, position.notional, is_stop=False)
            exit_price = slippage_uygula(position.target, kayma, "LONG", False)
            reason = "target"
            exit_slippage_pct = kayma

    if exit_price is None:
        return None

    exit_notional = position.qty * exit_price
    exit_fee = exit_notional * fee_rate
    gross = position.qty * (exit_price - position.entry)
    pnl = gross - position.entry_fee - exit_fee
    new_equity = equity + gross - exit_fee
    trade = {
        "variant": position.variant,
        "symbol": position.symbol,
        "entry_time": position.entry_time,
        "exit_time": ms_to_iso(ts),
        "entry": round(position.entry, 8),
        "exit": round(exit_price, 8),
        "stop": round(position.stop, 8),
        "target": round(position.target, 8),
        "reason": reason,
        "rr": position.rr,
        "confidence": position.confidence,
        "notional": round(position.notional, 4),
        "entry_fee": round(position.entry_fee, 6),
        "exit_fee": round(exit_fee, 6),
        "pnl": round(pnl, 6),
        "equity_after": round(new_equity, 6),
        "entry_slippage": round(position.entry_slippage, 6),
        "exit_slippage": round(exit_slippage_pct, 6),
        "rejim": position.rejim,
    }
    return new_equity, trade


def summarize_trades(trades: list[dict[str, Any]], initial_capital: float, final_equity: float) -> dict[str, Any]:
    pnl_values = [float(t["pnl"]) for t in trades]
    wins = [p for p in pnl_values if p > 0]
    losses = [p for p in pnl_values if p <= 0]
    curve = [initial_capital]
    rejimler = {}
    for trade in trades:
        curve.append(float(trade["equity_after"]))
        rj = trade.get("rejim", "BILINMIYOR")
        if rj not in rejimler:
            rejimler[rj] = {"kazanc": 0, "kayip": 0, "pnl": 0.0, "trades": 0}
        rejimler[rj]["trades"] += 1
        pnl = float(trade["pnl"])
        rejimler[rj]["pnl"] += pnl
        if pnl > 0:
            rejimler[rj]["kazanc"] += 1
        else:
            rejimler[rj]["kayip"] += 1
            
    for rj, istatistik in rejimler.items():
        if istatistik["trades"] > 0:
            istatistik["win_rate"] = round(istatistik["kazanc"] / istatistik["trades"] * 100, 2)
        else:
            istatistik["win_rate"] = 0.0
            
    peak = curve[0]
    max_dd = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round((len(wins) / len(trades) * 100) if trades else 0.0, 2),
        "net_pnl": round(final_equity - initial_capital, 6),
        "return_pct": round(((final_equity / initial_capital) - 1.0) * 100, 3),
        "final_equity": round(final_equity, 6),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "profit_factor": round((gross_profit / gross_loss) if gross_loss else 999.0, 3),
        "avg_trade": round((sum(pnl_values) / len(pnl_values)) if pnl_values else 0.0, 6),
        "fees": round(sum(float(t["entry_fee"]) + float(t["exit_fee"]) for t in trades), 6),
        "total_slippage_pct": round(sum(float(t.get("entry_slippage", 0)) + float(t.get("exit_slippage", 0)) for t in trades) * 100, 4),
        "rejim_istatistikleri": rejimler,
    }


def run_variant(
    variant: Variant,
    frames: dict[str, pd.DataFrame],
    initial_capital: float,
    leverage: float,
    fee_rate: float,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    equity = float(initial_capital)
    positions: list[Position] = []
    trades: list[dict[str, Any]] = []
    guard_state: dict[str, Any] = {}
    all_ts = sorted({int(ts) for df in frames.values() for ts in df.index})
    index_positions = {symbol: {int(ts): i for i, ts in enumerate(df.index)} for symbol, df in frames.items()}

    for ts in all_ts:
        # Close positions that hit stop or target on this bar.
        remaining: list[Position] = []
        for pos in positions:
            df = frames.get(pos.symbol)
            if df is None or ts not in df.index:
                remaining.append(pos)
                continue
            closed = close_position(pos, df.loc[ts], ts, equity, fee_rate)
            if closed is None:
                remaining.append(pos)
                continue
            equity, trade = closed
            trades.append(trade)
            if variant.symbol_guard:
                update_guard(variant, guard_state, pos.symbol, ts, float(trade["pnl"]))
        positions = remaining

        slots = variant.max_positions - len(positions)
        if slots <= 0 or equity <= initial_capital * 0.25:
            continue

        open_symbols = {p.symbol for p in positions}
        candidates: list[dict[str, Any]] = []
        for symbol, df in frames.items():
            if symbol in open_symbols:
                continue
            pos_map = index_positions[symbol]
            i = pos_map.get(ts)
            if i is None or i < 80:
                continue
            if variant.symbol_guard and not guard_allows(guard_state, symbol, ts):
                continue
            signal_row = df.iloc[i - 1]
            current_row = df.iloc[i]
            signal = signal_candidate(signal_row, variant)
            if not signal:
                continue
            entry = float(current_row["open"])
            
            # Slippage tahmini ve uygulamasi
            hacim_24s = float(current_row.get("volume", 0.0)) * 96 * entry
            atr_pct = float(current_row.get("atr_pct", 0.0))
            notional_tahmini = max(5.0, equity * variant.margin_pct * leverage)
            
            kayma_yuzdesi = slippage_tahmini(hacim_24s, atr_pct, notional_tahmini, False)
            entry = slippage_uygula(entry, kayma_yuzdesi, "LONG", True)
            
            stop_distance = max(float(signal["stop_distance"]), entry * 0.006)
            stop = entry - stop_distance
            target = entry + (stop_distance * float(signal["rr"]))
            if stop <= 0:
                continue
            candidates.append(
                {
                    "symbol": symbol,
                    "entry": entry,
                    "stop": stop,
                    "target": target,
                    **signal,
                    "kayma_yuzdesi": kayma_yuzdesi,
                }
            )

        candidates.sort(key=lambda item: float(item["score"]), reverse=True)
        for item in candidates[: min(slots, variant.max_new_per_bar)]:
            notional = max(5.0, equity * variant.margin_pct * leverage)
            entry_fee = notional * fee_rate
            equity -= entry_fee
            qty = notional / float(item["entry"])
            
            symbol_df = frames.get(item["symbol"])
            rejim_val = "BILINMIYOR"
            if symbol_df is not None:
                pos_idx = index_positions[item["symbol"]].get(ts)
                if pos_idx is not None:
                    rejim_val = piyasa_rejimi_belirle(symbol_df.iloc[pos_idx])
            
            positions.append(
                Position(
                    variant=variant.name,
                    symbol=str(item["symbol"]),
                    entry_ts=ts,
                    entry_time=ms_to_iso(ts),
                    entry=float(item["entry"]),
                    stop=float(item["stop"]),
                    target=float(item["target"]),
                    rr=float(item["rr"]),
                    confidence=float(item["confidence"]),
                    qty=qty,
                    notional=notional,
                    entry_fee=entry_fee,
                    entry_slippage=item.get("kayma_yuzdesi", kayma_yuzdesi),
                    rejim=rejim_val,
                )
            )

    # Mark open positions to market on the final available bar.
    for pos in positions:
        df = frames.get(pos.symbol)
        if df is None or df.empty:
            continue
        final_ts = int(df.index[-1])
        closed = close_position(pos, df.iloc[-1], final_ts, equity, fee_rate, reason_override="end_of_test")
        if closed is None:
            continue
        equity, trade = closed
        trades.append(trade)
        if variant.symbol_guard:
            update_guard(variant, guard_state, pos.symbol, final_ts, float(trade["pnl"]))

    summary = summarize_trades(trades, initial_capital, equity)
    summary.update({"variant": variant.name, "settings": asdict(variant)})
    return summary, trades


def symbol_breakdown(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trade in trades:
        grouped.setdefault((str(trade["variant"]), str(trade["symbol"])), []).append(trade)
    rows = []
    for (variant, symbol), items in grouped.items():
        pnl = sum(float(t["pnl"]) for t in items)
        wins = sum(1 for t in items if float(t["pnl"]) > 0)
        rows.append(
            {
                "variant": variant,
                "symbol": symbol,
                "trades": len(items),
                "wins": wins,
                "win_rate_pct": round(wins / len(items) * 100, 2),
                "pnl": round(pnl, 6),
            }
        )
    return sorted(rows, key=lambda row: (row["variant"], row["pnl"]))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_symbols(raw: str | None) -> list[str]:
    if not raw:
        return DEFAULT_SYMBOLS
    return [clean_symbol(part) for part in raw.replace(";", ",").split(",") if clean_symbol(part)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only shadow backtest for QuantBot variants.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--limit-symbols", type=int, default=30)
    parser.add_argument("--symbols", default=None)
    parser.add_argument("--capital", type=float, default=1420.0)
    parser.add_argument("--leverage", type=float, default=5.0)
    parser.add_argument("--fee-rate", type=float, default=0.0005)
    args = parser.parse_args()

    exchange = make_exchange()
    requested = parse_symbols(args.symbols)
    resolved = resolve_symbols(exchange, requested, args.limit_symbols)
    if "BTC/USDT" not in resolved:
        btc_resolved = resolve_symbols(exchange, ["BTC/USDT"], 1)
        resolved.update(btc_resolved)

    now_ms = exchange.milliseconds()
    since_ms = now_ms - int(args.days * 24 * 60 * 60 * 1000)
    frames: dict[str, pd.DataFrame] = {}
    skipped: dict[str, str] = {}

    for display_symbol, market_symbol in resolved.items():
        try:
            raw = fetch_ohlcv_df(exchange, market_symbol, args.timeframe, since_ms, now_ms)
            if len(raw) < 120:
                skipped[display_symbol] = f"not enough bars ({len(raw)})"
                continue
            frames[display_symbol] = add_indicators(raw)
            print(f"[data] {display_symbol}: {len(frames[display_symbol])} bars")
        except Exception as exc:
            skipped[display_symbol] = f"{type(exc).__name__}: {exc}"
            print(f"[skip] {display_symbol}: {skipped[display_symbol]}")

    if not frames:
        print("No usable market data fetched.")
        return 2

    enrich_with_btc(frames)
    run_dir = REPORT_DIR / datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir.mkdir(parents=True, exist_ok=True)

    summaries: list[dict[str, Any]] = []
    all_trades: list[dict[str, Any]] = []
    for variant in VARIANTS:
        summary, trades = run_variant(
            variant,
            frames,
            initial_capital=float(args.capital),
            leverage=float(args.leverage),
            fee_rate=float(args.fee_rate),
        )
        summaries.append({k: v for k, v in summary.items() if k != "settings"})
        all_trades.extend(trades)

    breakdown = symbol_breakdown(all_trades)
    summary_path = run_dir / "summary.csv"
    trades_path = run_dir / "trades.csv"
    symbol_path = run_dir / "symbol_breakdown.csv"
    json_path = run_dir / "summary.json"
    write_csv(summary_path, summaries)
    write_csv(trades_path, all_trades)
    write_csv(symbol_path, breakdown)
    json_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "args": vars(args),
                "symbols": sorted(frames.keys()),
                "skipped": skipped,
                "summaries": summaries,
                "variant_settings": [asdict(v) for v in VARIANTS],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print("\nVariant summary")
    print("variant,trades,win_rate_pct,net_pnl,return_pct,max_drawdown_pct,profit_factor,fees")
    for row in summaries:
        print(
            f"{row['variant']},{row['trades']},{row['win_rate_pct']},"
            f"{row['net_pnl']},{row['return_pct']},{row['max_drawdown_pct']},"
            f"{row['profit_factor']},{row['fees']}"
        )
    print(f"\nReport directory: {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
