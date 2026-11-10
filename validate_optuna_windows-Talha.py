from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from QuantBot.experiment_manifest import deney_manifesti_yaz


CANDIDATES = [
    {"name": "mevcut_500_4", "n_estimators": 500, "max_depth": 4},
    {"name": "sade_stabil_400_5", "n_estimators": 400, "max_depth": 5},
    {"name": "yakin_rakip_450_8", "n_estimators": 450, "max_depth": 8},
]

WINDOW_CACHE: dict[int, dict[str, Any]] = {}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def parse_offsets(raw: str) -> list[int]:
    values = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        values.append(max(0, int(float(part))))
    return values or [0, 30]


def select_candidates(raw: str | None) -> list[dict[str, Any]]:
    if not raw:
        return CANDIDATES
    wanted = {part.strip() for part in raw.replace(";", ",").split(",") if part.strip()}
    selected = [candidate for candidate in CANDIDATES if candidate["name"] in wanted]
    missing = sorted(wanted - {candidate["name"] for candidate in selected})
    if missing:
        known = ", ".join(candidate["name"] for candidate in CANDIDATES)
        raise ValueError(f"Unknown candidate(s): {', '.join(missing)}. Known: {known}")
    return selected


def get_window_cache(crypto_backtest: Any, offset_days: int) -> dict[str, Any]:
    if offset_days in WINDOW_CACHE:
        return WINDOW_CACHE[offset_days]

    import ccxt
    import numpy as np
    import pandas as pd
    import pandas_ta as ta  # noqa: F401 - registers the pandas .ta accessor

    def fetch_ohlcv_range(exchange: Any, symbol: str, timeframe: str, since_ms: int, until_ms: int) -> Any:
        step_ms = int(exchange.parse_timeframe(timeframe) * 1000)
        cursor = since_ms
        rows: list[list[float]] = []
        seen: set[int] = set()
        while cursor < until_ms:
            batch = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
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
            time.sleep(0.25)

        if not rows:
            return pd.DataFrame()
        frame = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
        frame = frame.drop_duplicates("timestamp").sort_values("timestamp").tail(1500)
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms")
        frame.set_index("timestamp", inplace=True)
        for column in ["open", "high", "low", "close", "volume"]:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        return frame.dropna()

    def build_feature_frame(exchange: Any, coin: str, ref_coin: str, since_ms: int, until_ms: int) -> Any:
        df_hedef = fetch_ohlcv_range(exchange, coin, "1h", since_ms, until_ms)
        df_ref = fetch_ohlcv_range(exchange, ref_coin, "1h", since_ms, until_ms)
        if df_hedef.empty or df_ref.empty:
            return None

        df = df_hedef[["close", "high", "low", "volume"]].copy()
        df.rename(columns={"close": "Hedef_Close"}, inplace=True)
        ref_close = df_ref["close"].reindex(df.index)
        df["Ref_Close"] = ref_close.values

        df["RSI"] = df.ta.rsi(close="Hedef_Close", length=14)
        macd = df.ta.macd(close="Hedef_Close", fast=12, slow=26, signal=9)
        df["MACD"] = macd.iloc[:, 0] if macd is not None else 0
        df["ATR"] = df.ta.atr(high="high", low="low", close="Hedef_Close", length=14)
        df["OBV"] = df.ta.obv(close=df["Hedef_Close"], volume=df["volume"])

        bbands = df.ta.bbands(close=df["Hedef_Close"], length=20)
        df["BB_Width"] = bbands.iloc[:, 3] if bbands is not None else 0
        df["MFI"] = df.ta.mfi(high=df["high"], low=df["low"], close=df["Hedef_Close"], volume=df["volume"], length=14)

        vwap = df.ta.vwap(high=df["high"], low=df["low"], close=df["Hedef_Close"], volume=df["volume"])
        df["VWAP"] = vwap if vwap is not None else df["Hedef_Close"]
        df["VP_Sapma"] = (df["Hedef_Close"] - df["VWAP"]) / df["VWAP"]

        df["Hedef_Ret"] = df["Hedef_Close"].pct_change()
        df["Ref_Ret"] = df["Ref_Close"].pct_change()
        df["Vol_Ret"] = df["volume"].pct_change()
        df["Korelasyon"] = df["Hedef_Ret"].rolling(window=14).corr(df["Ref_Ret"])
        df["Kriz"] = np.where(df["Hedef_Ret"] < -0.05, 1.0, 0.0)
        epsilon = 1e-9
        high_low_diff = (df["high"] - df["low"]).replace(0, epsilon)

        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["Hedef_Close"].shift()).abs(),
                (df["low"] - df["Hedef_Close"].shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        tr = tr.replace(0, epsilon)
        df["CHOP"] = 100 * np.log10(tr.rolling(14).sum() / high_low_diff.rolling(14).max()) / np.log10(14)
        df["CHOP"].fillna(50, inplace=True)

        df["Squeeze_ON"] = (
            df["BB_Width"] < df.ta.atr(high="high", low="low", close="Hedef_Close", length=20) * 1.5
        ).astype(int)
        df["Open_Interest"] = df["volume"].rolling(24).mean()
        df["Funding_Rate"] = df["Hedef_Ret"].rolling(8).mean()
        df["Haber_Duygu_Puani"] = 50.0
        df["Faiz_Orani"] = 50.0
        df["Dolar_Kuru"] = df["Hedef_Close"] / 10.0

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)
        return df

    timeframe_ms = 60 * 60 * 1000
    until_ms = int(time.time() * 1000) - (offset_days * 24 * timeframe_ms)
    since_ms = until_ms - (1550 * timeframe_ms)
    exchange = ccxt.binance(
        {
            "enableRateLimit": True,
            "options": {"adjustForTimeDifference": True, "recvWindow": 60000},
        }
    )
    needed = crypto_backtest.test_saati + 200
    cache: dict[str, Any] = {}
    for coin in crypto_backtest.coinler:
        df = build_feature_frame(exchange, coin, "BTC/USDT", since_ms, until_ms)
        if df is None or len(df) < needed:
            rows = 0 if df is None else len(df)
            raise RuntimeError(f"insufficient_data {coin}: rows={rows}")
        cache[coin] = df.copy()

    WINDOW_CACHE[offset_days] = cache
    return cache


def run_one_candidate(
    *,
    candidate: dict[str, Any],
    offset_days: int,
    run_dir: Path,
    root: Path,
) -> dict[str, Any]:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    import crypto_backtest

    artifact_dir = run_dir / "model_artifacts" / f"offset_{offset_days}" / str(candidate["name"])
    artifact_dir.mkdir(parents=True, exist_ok=True)

    cache = get_window_cache(crypto_backtest, offset_days)

    def cached_fetch(coin: str, ref_coin: str = "BTC/USDT", limit: int = 1500, timeframe: str = "1h") -> Any:
        df = cache.get(coin)
        return df.copy() if df is not None else None

    params = {"n_estimators": int(candidate["n_estimators"]), "max_depth": int(candidate["max_depth"])}
    original_fetch = crypto_backtest.ccxt_gecmis_tam
    old_cwd = Path.cwd()
    started = time.time()
    try:
        crypto_backtest.ccxt_gecmis_tam = cached_fetch
        os.chdir(artifact_dir)
        result = crypto_backtest.backtest_calistir(params)
    finally:
        crypto_backtest.ccxt_gecmis_tam = original_fetch
        os.chdir(old_cwd)

    duration = time.time() - started
    return {
        "candidate": candidate["name"],
        "offset_days": offset_days,
        "n_estimators": params["n_estimators"],
        "max_depth": params["max_depth"],
        "pnl": float(result.get("pnl", 0.0)),
        "total_trades": int(result.get("total_trades", 0)),
        "win_rate_pct": float(result.get("win_rate", 0.0)),
        "final_equity": float(result.get("son_kasa", 0.0)),
        "duration_sec": duration,
        "wall_sec": round(duration, 2),
    }


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["candidate"]), []).append(row)
    summary = []
    for candidate, items in grouped.items():
        pnls = [float(i["pnl"]) for i in items]
        trades = [float(i["total_trades"]) for i in items]
        wins = [float(i["win_rate_pct"]) for i in items]
        first = items[0]
        positive = sum(1 for pnl in pnls if pnl > 0)
        avg = sum(pnls) / len(pnls)
        variance = sum((pnl - avg) ** 2 for pnl in pnls) / max(1, len(pnls) - 1)
        stability_penalty = math.sqrt(variance)
        summary.append(
            {
                "candidate": candidate,
                "n_estimators": int(first["n_estimators"]),
                "max_depth": int(first["max_depth"]),
                "windows": len(items),
                "positive_windows": positive,
                "avg_pnl": round(avg, 6),
                "min_pnl": round(min(pnls), 6),
                "max_pnl": round(max(pnls), 6),
                "std_pnl": round(stability_penalty, 6),
                "avg_trades": round(sum(trades) / len(trades), 2),
                "avg_win_rate_pct": round(sum(wins) / len(wins), 4),
                "robust_score": round(avg - (0.35 * stability_penalty), 6),
            }
        )
    summary.sort(key=lambda row: float(row["robust_score"]), reverse=True)
    for idx, row in enumerate(summary, start=1):
        row["rank"] = idx
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Optuna candidates on multiple time windows.")
    parser.add_argument("--offset-days", default="0,30", help="Comma separated window end offsets, e.g. 0,15,30")
    parser.add_argument("--candidates", default=None, help="Comma separated candidate names to run")
    parser.add_argument("--python", default=None, help="Unused legacy option kept for old commands")
    args = parser.parse_args()

    root = Path.cwd()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import crypto_backtest

    offsets = parse_offsets(args.offset_days)
    candidates = select_candidates(args.candidates)
    run_dir = root / "QuantBot" / "backtest_reports" / ("window_validate_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)

    print("[DATA] Deney veri snapshot'lari hazırlanıyor...", flush=True)
    manifest_datasets: dict[str, Any] = {}
    for offset in offsets:
        cache = get_window_cache(crypto_backtest, offset)
        for symbol, frame in cache.items():
            manifest_datasets[f"offset_{offset}:{symbol}"] = frame

    feature_names = sorted(
        {
            str(column)
            for frame in manifest_datasets.values()
            for column in frame.columns
        }
    )
    manifest = deney_manifesti_yaz(
        run_dir / "experiment_manifest.json",
        experiment_type="multi_window_model_candidate_validation",
        parameters={
            "candidates": candidates,
            "offset_days": offsets,
            "symbols": list(crypto_backtest.coinler),
            "timeframe": "1h",
            "test_hours": int(crypto_backtest.test_saati),
            "initial_equity": float(crypto_backtest.baslangic_kasa),
            "rr_stop_multiplier": float(crypto_backtest.rr_stop_carpan),
            "rr_target_multiplier": float(crypto_backtest.rr_target_carpan),
        },
        datasets=manifest_datasets,
        code_paths=[
            Path(__file__),
            root / "crypto_backtest.py",
            root / "ai_core.py",
        ],
        features=feature_names,
        validation={
            "method": "fixed historical end-date windows",
            "selection_metric": "mean_pnl_minus_0.35_std_pnl",
            "minimum_history_rows": int(crypto_backtest.test_saati + 200),
        },
        cost_assumptions={
            "commission": "not modeled by this legacy root backtest",
            "slippage": "not modeled by this legacy root backtest",
            "funding": "proxy feature only; cash-flow cost not modeled",
        },
        random_seed=42,
        trial_count=len(candidates) * len(offsets),
        root=root,
        notes=[
            "Manifest records the exact in-memory feature frames before candidate evaluation.",
            "Legacy cost omissions are explicit; these results must not be used alone for promotion.",
        ],
    )
    print(f"[MANIFEST] {manifest['experiment_id'][:12]} -> {run_dir / 'experiment_manifest.json'}", flush=True)

    rows: list[dict[str, Any]] = []
    print(f"[START] offsets={offsets} candidates={[c['name'] for c in candidates]}", flush=True)
    print(f"[REPORT] {run_dir}", flush=True)
    for offset in offsets:
        print(f"\n[WINDOW] offset_days={offset}", flush=True)
        if offset not in WINDOW_CACHE:
            print("  [DATA] Mum verisi hazırlanıyor...", flush=True)
        for candidate in candidates:
            print(
                f"  -> {candidate['name']} ({candidate['n_estimators']}/{candidate['max_depth']})",
                flush=True,
            )
            row = run_one_candidate(
                candidate=candidate,
                offset_days=offset,
                run_dir=run_dir,
                root=root,
            )
            rows.append(row)
            write_csv(run_dir / "raw_results.csv", rows)
            print(
                f"     PnL={row['pnl']:+,.2f} | Islem={row['total_trades']} | "
                f"Win=%{row['win_rate_pct']:.2f} | Sure={row['wall_sec']:.1f}s",
                flush=True,
            )

    summary = summarize(rows)
    write_csv(run_dir / "summary.csv", summary)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "offset_days": offsets,
                "candidates": candidates,
                "summary": summary,
                "raw_results": rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("\n=== ROBUST OZET ===", flush=True)
    print("rank,candidate,avg_pnl,min_pnl,std_pnl,robust_score,avg_trades,avg_win_rate_pct", flush=True)
    for row in summary:
        print(
            f"{row['rank']},{row['candidate']},{row['avg_pnl']},{row['min_pnl']},"
            f"{row['std_pnl']},{row['robust_score']},{row['avg_trades']},{row['avg_win_rate_pct']}",
            flush=True,
        )
    print(f"\nRapor klasoru: {run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
