"""
Otomatik Piyasa Taraması (GitHub Actions için)
==============================================
1. stock_value_engine.tam_tarama_baslat() ile tüm kurumsal havuzu tarar.
2. En son tarama sonuçlarını (sadece ana model satırları) ve güncel model/performans
   özetlerini web/data/piyasa_tarama_son.json dosyasına yazar.
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")
OUT_PATH = os.path.join(PROJECT_ROOT, "web", "data", "piyasa_tarama_son.json")


def export_latest_scan(db_path: str = DB_PATH, out_path: str = OUT_PATH) -> int:
    """DB'deki en son as_of_date taramasını (paper shadow hariç) ve özet metrikleri JSON'a yazar."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    last_date = conn.execute(
        "SELECT MAX(as_of_date) FROM hisse_sinyalleri WHERE model_role IS NULL"
    ).fetchone()[0]
    if not last_date:
        conn.close()
        return 0

    rows = conn.execute(
        """
        SELECT sembol, sektor, ai_skor, decision, fiyat, rsi,
               quality_score, value_score, momentum_score, risk_score, as_of_date
        FROM hisse_sinyalleri
        WHERE as_of_date = ? AND model_role IS NULL
        ORDER BY ai_skor DESC
        """,
        (last_date,),
    ).fetchall()
    conn.close()

    seen, records = set(), []
    for r in rows:
        if r["sembol"] in seen:
            continue
        seen.add(r["sembol"])
        records.append({k: r[k] for k in r.keys()})

    shadow_sum = None
    perf_sum = None
    last_update_meta = None
    try:
        import stock_shadow_paper
        shadow_sum = stock_shadow_paper.shadow_performance_summary(db_path)
    except Exception:
        shadow_sum = None

    try:
        import stock_signal_tracker
        perf_sum = stock_signal_tracker.performans_ozeti(db_path)
    except Exception:
        perf_sum = None

    try:
        from stock_value_engine import vix_oku
        vix_val = vix_oku()
    except Exception:
        vix_val = None

    try:
        base_m = (shadow_sum or {}).get("models", {}).get("paper_baseline", {})
        chal_m = (shadow_sum or {}).get("models", {}).get("paper_m00_r15", {})
        b_ret = base_m.get("paired_mean_return", 0) or 0
        c_ret = chal_m.get("paired_mean_return", 0) or 0
        lider = "Challenger (m00_r15)" if c_ret > b_ret else "Baseline (v3.1)"
        last_update_meta = {
            "son_guncelleme": datetime.now(timezone.utc).isoformat(),
            "lider": lider,
            "vix": vix_val,
            "baseline_return": b_ret,
            "challenger_return": c_ret,
            "status": (shadow_sum or {}).get("status", "COLLECTING_GENUINELY_NEW_DATA"),
            "mature_cohorts": (shadow_sum or {}).get("paired_mature_cohorts", 2),
            "required_cohorts": (shadow_sum or {}).get("required_paired_mature_cohorts", 3),
        }
    except Exception:
        last_update_meta = None

    payload = {
        "as_of_date": last_date,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(records),
        "rows": records,
        "shadow_summary": shadow_sum,
        "performance_summary": perf_sum,
        "last_update": last_update_meta,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return len(records)


if __name__ == "__main__":
    export_only = "--export-only" in sys.argv
    if not export_only:
        os.environ.setdefault("STOCK_OUTCOME_TRACKING", "0")
        from stock_value_engine import tam_tarama_baslat

        print("Tam piyasa taraması başlatılıyor...")
        sinyaller = tam_tarama_baslat()
        print(f"Tarama bitti: {len(sinyaller) if sinyaller else 0} sinyal")

    n = export_latest_scan()
    print(f"JSON'a yazılan hisse sayısı: {n} → {OUT_PATH}")
    if n == 0:
        sys.exit(1)
