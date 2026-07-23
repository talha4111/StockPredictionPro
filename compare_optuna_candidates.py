from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from datetime import datetime
from pathlib import Path
from typing import Any

print("[BOOT] crypto_backtest import ediliyor...", flush=True)
import crypto_backtest
print("[BOOT] crypto_backtest import tamam.", flush=True)


CANDIDATES = [
    {"name": "mevcut_500_4", "n_estimators": 500, "max_depth": 4},
    {"name": "optuna_sampiyon_450_7", "n_estimators": 450, "max_depth": 7},
    {"name": "yakin_rakip_450_8", "n_estimators": 450, "max_depth": 8},
    {"name": "guclu_bolge_500_8", "n_estimators": 500, "max_depth": 8},
    {"name": "guclu_ama_derin_500_9", "n_estimators": 500, "max_depth": 9},
    {"name": "sade_stabil_400_5", "n_estimators": 400, "max_depth": 5},
]


def _ortalama(degerler: list[float]) -> float:
    return statistics.mean(degerler) if degerler else 0.0


def _std(degerler: list[float]) -> float:
    return statistics.stdev(degerler) if len(degerler) > 1 else 0.0


def _csv_yaz(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _veri_onbellege_al() -> dict[str, Any]:
    original_fetch = crypto_backtest.ccxt_gecmis_tam
    cache: dict[str, Any] = {}
    print("[CACHE] Ayni veri snapshot'i icin mumlar indiriliyor...", flush=True)
    for coin in crypto_backtest.coinler:
        df = original_fetch(coin, ref_coin="BTC/USDT", limit=1500, timeframe="1h")
        if df is None or df.empty:
            raise RuntimeError(f"{coin} icin veri alinamadi.")
        cache[coin] = df.copy()
        print(f"  - {coin}: {len(df)} bar", flush=True)

    def cached_fetch(coin, ref_coin="BTC/USDT", limit=1500, timeframe="1h"):
        df = cache.get(coin)
        return df.copy() if df is not None else None

    crypto_backtest.ccxt_gecmis_tam = cached_fetch
    return cache


def _aday_kos(aday: dict[str, Any], repeat: int) -> dict[str, Any]:
    params = {
        "n_estimators": int(aday["n_estimators"]),
        "max_depth": int(aday["max_depth"]),
    }
    baslangic = time.time()
    sonuc = crypto_backtest.backtest_calistir(params)
    sure = time.time() - baslangic
    return {
        "candidate": aday["name"],
        "repeat": repeat,
        "n_estimators": params["n_estimators"],
        "max_depth": params["max_depth"],
        "pnl": round(float(sonuc.get("pnl", 0.0)), 6),
        "total_trades": int(sonuc.get("total_trades", 0)),
        "win_rate_pct": round(float(sonuc.get("win_rate", 0.0)), 4),
        "final_equity": round(float(sonuc.get("son_kasa", 0.0)), 6),
        "duration_sec": round(sure, 2),
    }


def _ozetle(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        grouped.setdefault(str(row["candidate"]), []).append(row)

    summary = []
    for name, rows in grouped.items():
        pnls = [float(r["pnl"]) for r in rows]
        wins = [float(r["win_rate_pct"]) for r in rows]
        trades = [int(r["total_trades"]) for r in rows]
        durations = [float(r["duration_sec"]) for r in rows]
        first = rows[0]
        summary.append(
            {
                "candidate": name,
                "n_estimators": first["n_estimators"],
                "max_depth": first["max_depth"],
                "runs": len(rows),
                "avg_pnl": round(_ortalama(pnls), 6),
                "std_pnl": round(_std(pnls), 6),
                "best_pnl": round(max(pnls), 6),
                "worst_pnl": round(min(pnls), 6),
                "avg_trades": round(_ortalama([float(t) for t in trades]), 2),
                "avg_win_rate_pct": round(_ortalama(wins), 4),
                "avg_duration_sec": round(_ortalama(durations), 2),
            }
        )
    summary.sort(key=lambda row: float(row["avg_pnl"]), reverse=True)
    for i, row in enumerate(summary, start=1):
        row["rank"] = i
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Fixed Optuna candidate comparison.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args()

    repeats = max(1, int(args.repeats))
    base_dir = Path(args.out_dir) if args.out_dir else Path("QuantBot") / "backtest_reports"
    run_dir = base_dir / ("quick_optuna_compare_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)

    _veri_onbellege_al()

    onceki_cwd = Path.cwd()
    model_dir = run_dir / "model_artifacts"
    model_dir.mkdir(parents=True, exist_ok=True)
    raw_rows: list[dict[str, Any]] = []

    try:
        # Backtest model dosyalarini proje kokune degil rapor klasorune yazsin.
        os.chdir(model_dir)
        for repeat in range(1, repeats + 1):
            print(f"\n[RUN] Tekrar {repeat}/{repeats}", flush=True)
            for aday in CANDIDATES:
                print(
                    f"  -> {aday['name']} "
                    f"({aday['n_estimators']}/{aday['max_depth']})",
                    flush=True,
                )
                row = _aday_kos(aday, repeat)
                raw_rows.append(row)
                print(
                    f"     PnL={row['pnl']:+,.2f} | "
                    f"Islem={row['total_trades']} | "
                    f"Win=%{row['win_rate_pct']:.2f} | "
                    f"Sure={row['duration_sec']:.1f}s",
                    flush=True,
                )
    finally:
        os.chdir(onceki_cwd)

    summary = _ozetle(raw_rows)
    _csv_yaz(run_dir / "raw_results.csv", raw_rows)
    _csv_yaz(run_dir / "summary.csv", summary)
    (run_dir / "summary.json").write_text(
        json.dumps(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "repeats": repeats,
                "candidates": CANDIDATES,
                "summary": summary,
                "raw_results": raw_rows,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n=== OZET ===", flush=True)
    print("rank,candidate,n_estimators,max_depth,avg_pnl,avg_trades,avg_win_rate_pct,std_pnl", flush=True)
    for row in summary:
        print(
            f"{row['rank']},{row['candidate']},{row['n_estimators']},"
            f"{row['max_depth']},{row['avg_pnl']},{row['avg_trades']},"
            f"{row['avg_win_rate_pct']},{row['std_pnl']}",
            flush=True,
        )
    print(f"\nRapor klasoru: {run_dir.resolve()}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
