import sqlite3, json

conn = sqlite3.connect('trading_bot.db')
cur = conn.cursor()

# Bugunku islemler
cur.execute("SELECT Tarih_Saat, Parite, Hesap_Tipi, Islem_Yonu, ROUND(Net_PNL_USDT,2), ROUND(AI_Guven_Skoru,1) FROM closed_trades WHERE Tarih_Saat >= '2026-03-25' ORDER BY id DESC")
rows = cur.fetchall()
print(f"=== BUGUN (25 Mart) KAPANAN ISLEM: {len(rows)} ===")
for r in rows:
    print(f"  {r[0]} | {r[1]} | {r[2]} | {r[3]} | PNL: {r[4]}$ | AI: %{r[5]}")

# Genel istatistik
cur.execute("SELECT COUNT(*), SUM(CASE WHEN Net_PNL_USDT > 0 THEN 1 ELSE 0 END), ROUND(SUM(Net_PNL_USDT),2) FROM closed_trades")
r = cur.fetchone()
wr = (r[1]/r[0]*100) if r[0] > 0 else 0
print(f"\n=== GENEL: {r[0]} islem | Win: {r[1]} | Win Rate: %{wr:.1f} | Toplam PNL: {r[2]}$ ===")

# Kasa durumu
try:
    with open('sanal_kasa_kripto.json') as f:
        kasa = json.load(f).get('bakiye', 0)
    print(f"\n=== DEMO KASA: {kasa:.2f}$ ===")
except: pass

conn.close()
