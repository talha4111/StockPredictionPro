"""
Haftalık Model Performans Güncelleme Betiği
============================================
Bu betik her Pazar saat 21:00'de Windows Task Scheduler tarafından
otomatik olarak çalıştırılır.  Ayrıca web panelindeki "Şimdi Güncelle"
düğmesi de aynı betiği import ederek kullanır.

Yaptığı işler:
  1. Sinyal sonuçlarını güncelle  (ileri vade getirilerini hesapla)
  2. Performans özetini oluştur   (baseline vs challenger kıyaslama)
  3. Shadow paper summary'yi yenile
  4. Son güncelleme tarihini JSON'a kaydet
"""
import json
import os
import sys
from datetime import datetime

# ── Proje kök dizinini sys.path'e ekle ──
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LAST_UPDATE_FILE = os.path.join(DATA_DIR, "last_update.json")


def guncelle(db_path: str | None = None) -> dict:
    """Ana güncelleme fonksiyonu.  Hem betik hem import olarak kullanılır."""
    db_path = db_path or DB_PATH

    from stock_value_engine import performans_takibini_guncelle

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Performans güncelleniyor …")
    result = performans_takibini_guncelle(db_path=db_path)

    # ── VIX bilgisini çek ──
    try:
        from stock_value_engine import vix_oku
        vix_val = vix_oku()
    except Exception:
        vix_val = None

    # ── Haftalık lideri belirle ──
    lider = "Belirsiz"
    shadow = result.get("shadow") or {}
    models = shadow.get("models") or {}
    base_ret = (models.get("paper_baseline", {}).get("paired_mean_return") or 0)
    chal_ret = (models.get("paper_m00_r15", {}).get("paired_mean_return") or 0)
    if chal_ret > base_ret:
        lider = "Challenger (m00_r15)"
    elif base_ret > chal_ret:
        lider = "Baseline (v3.1)"
    else:
        lider = "Berabere"

    # ── Son güncelleme bilgisini JSON'a kaydet ──
    os.makedirs(DATA_DIR, exist_ok=True)
    update_info = {
        "son_guncelleme": datetime.now().isoformat(),
        "lider": lider,
        "vix": vix_val,
        "baseline_return": base_ret,
        "challenger_return": chal_ret,
        "status": shadow.get("status", "VERI_TOPLANIYOR"),
        "mature_cohorts": shadow.get("paired_mature_cohorts", 0),
        "required_cohorts": shadow.get("required_paired_mature_cohorts", 3),
    }
    with open(LAST_UPDATE_FILE, "w", encoding="utf-8") as f:
        json.dump(update_info, f, ensure_ascii=False, indent=2)

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Güncelleme tamamlandı → {LAST_UPDATE_FILE}")
    print(f"  Lider: {lider}")
    print(f"  VIX:   {vix_val}")
    return update_info


def son_guncelleme_oku() -> dict | None:
    """last_update.json dosyasını oku.  Yoksa None döndür."""
    if os.path.exists(LAST_UPDATE_FILE):
        with open(LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


if __name__ == "__main__":
    info = guncelle()
    print(json.dumps(info, ensure_ascii=False, indent=2))
