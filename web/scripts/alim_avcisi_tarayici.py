"""
Alım Noktası & Dönüş Avcısı — Otomatik Arka Plan Tarayıcı Betiği
ABD borsası açıkken (Pazartesi-Cuma 16:30 - 23:15 TSİ) periyodik olarak çalışır,
takip listesindeki hisseler ucuzluk bölgesine indiğinde veya dipten dönüş
başladığında Telegram'a anlaşılır, sade Türkçe ile bildirim gönderir.
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.dip_hunter import scan_and_notify_all


def main():
    parser = argparse.ArgumentParser(description="StockPredictionPro Alım Avcısı Tarayıcı")
    parser.add_argument("--force", action="store_true", help="Durum değişmese bile tüm hisseleri Telegram'a gönder")
    args = parser.parse_args()

    print("=== StockPredictionPro Alım Avcısı Taraması Başladı ===")
    results = scan_and_notify_all(force_notify=args.force)
    for r in results:
        print(
            f"[{r['symbol']}] Fiyat: ${r['current_price']:.2f} | "
            f"Durum: {r['state_badge']} | "
            f"1. Alım Yeri: ${r['zone1_low']:.2f}-${r['zone1_high']:.2f}"
        )
    print(f"=== Tarama Tamamlandı ({len(results)} hisse incelendi) ===")


if __name__ == "__main__":
    main()
