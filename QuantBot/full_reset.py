"""
FULL RESET: Tum pozisyonlari kapat, kasayi 100$'a ayarla, tum gecmisi sifirla.
"""
import json
import ccxt
import sqlite3
import os
import sys
import time

if os.environ.get('ALLOW_DEMO_FULL_RESET') != 'I_UNDERSTAND_DEMO_FULL_RESET':
    print('Demo full reset kilitli. Acik onay olmadan pozisyon/gecmis silinmeyecek.')
    raise SystemExit(0)

# Windows encoding fix
sys.stdout.reconfigure(encoding='utf-8')

print("=" * 60)
print("FULL RESET BASLIYOR")
print("=" * 60)

with open('ayar.json', 'r') as f:
    ayar = json.load(f)

testnet_key = ayar.get("testnet_api_key", "").strip()
testnet_secret = ayar.get("testnet_secret", "").strip()

borsa = ccxt.binance({
    'apiKey': testnet_key,
    'secret': testnet_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
})
borsa.enable_demo_trading(True)
borsa.load_markets()

# ADIM 1: TUM POZISYONLARI KAPAT
print("\n[ADIM 1] Acik pozisyonlar kapatiliyor...")
try:
    poses = borsa.fetch_positions()
    active = [p for p in poses if float(p.get('contracts', 0) or 0) != 0]
    
    if not active:
        print("  OK: Acik pozisyon yok.")
    else:
        print(f"  UYARI: {len(active)} acik pozisyon bulundu!")
        for p in active:
            sym = p['symbol']
            amt = float(p.get('contracts', 0))
            side = 'sell' if amt > 0 else 'buy'
            abs_amt = abs(amt)
            print(f"  Kapatiliyor: {sym} | Miktar: {amt} | Yon: {side}")
            
            # Emirleri iptal et
            try:
                borsa.cancel_all_orders(sym)
                print(f"    Emirler iptal edildi.")
            except:
                pass
            
            try:
                market_id = borsa.market_id(sym)
                borsa.fapiPrivateDeleteAllOpenOrders({'symbol': market_id})
            except:
                pass
            
            time.sleep(1)
            
            # Market emri ile kapat
            try:
                borsa.create_order(
                    symbol=sym, type='MARKET', side=side,
                    amount=abs_amt, params={'reduceOnly': True}
                )
                print(f"    OK: {sym} kapatildi (reduceOnly)!")
            except Exception as e1:
                print(f"    UYARI: reduceOnly basarisiz: {e1}")
                try:
                    borsa.create_order(
                        symbol=sym, type='MARKET', side=side,
                        amount=abs_amt
                    )
                    print(f"    OK: {sym} kapatildi (normal)!")
                except Exception as e2:
                    print(f"    HATA: Normal kapanis da basarisiz: {e2}")
            
            time.sleep(1)
    
    # Dogrulama
    time.sleep(2)
    poses2 = borsa.fetch_positions()
    active2 = [p for p in poses2 if float(p.get('contracts', 0) or 0) != 0]
    if active2:
        print(f"\n  UYARI: HALA {len(active2)} pozisyon acik!")
        for p in active2:
            print(f"    {p['symbol']}: {p.get('contracts')}")
    else:
        print("\n  OK: Tum pozisyonlar basariyla kapatildi!")

except Exception as e:
    print(f"  HATA: Pozisyon kapatma hatasi: {e}")

# ADIM 2: BAKIYE KONTROLU VE OFFSET
print("\n[ADIM 2] Bakiye kontrol ediliyor...")
offset = 0.0
try:
    bal = borsa.fetch_balance({'type': 'future'})
    usdt_total = float(bal.get('USDT', {}).get('total', 0.0))
    usdt_free = float(bal.get('USDT', {}).get('free', 0.0))
    print(f"  Gercek Testnet Bakiye (total): {usdt_total:.2f} USDT")
    print(f"  Kullanilabilir (free): {usdt_free:.2f} USDT")
    
    offset = usdt_total - 100.0
    print(f"  Offset hesaplandi: {offset:.2f} (Hedef: 100.00$)")
    
    ayar['demo_bakiye_offset'] = offset
    with open('ayar.json', 'w') as f:
        json.dump(ayar, f, indent=4)
    print(f"  OK: ayar.json guncellendi (demo_bakiye_offset = {offset:.2f})")
    
except Exception as e:
    print(f"  HATA: Bakiye hatasi: {e}")

# ADIM 3: TUM HAFIZA DOSYALARINI TEMIZLE
print("\n[ADIM 3] Hafiza dosyalari temizleniyor...")

# aktif_detay.json
try:
    with open('aktif_detay.json', 'w') as f:
        json.dump({}, f)
    print("  OK: aktif_detay.json temizlendi")
except Exception as e:
    print(f"  HATA: aktif_detay.json: {e}")

# performans.json
try:
    with open('performans.json', 'w') as f:
        json.dump({"kazanc": 0, "kayip": 0}, f)
    print("  OK: performans.json sifirlandi")
except Exception as e:
    print(f"  HATA: performans.json: {e}")

# trade_history.csv
try:
    with open('trade_history.csv', 'r') as f:
        header = f.readline()
    with open('trade_history.csv', 'w') as f:
        f.write(header)
    print("  OK: trade_history.csv temizlendi (header korundu)")
except Exception as e:
    print(f"  UYARI: trade_history.csv: {e}")

# trading_bot.db
try:
    conn = sqlite3.connect('trading_bot.db')
    conn.execute("DELETE FROM closed_trades")
    conn.commit()
    conn.close()
    print("  OK: trading_bot.db temizlendi")
except Exception as e:
    print(f"  UYARI: trading_bot.db: {e}")

# sanal_kasa_kripto.json
parent_kasa = os.path.join('..', 'sanal_kasa_kripto.json')
try:
    with open(parent_kasa, 'w') as f:
        json.dump({"bakiye": 100.0}, f)
    print("  OK: sanal_kasa_kripto.json = 100.0$")
except Exception as e:
    print(f"  UYARI: sanal_kasa_kripto.json: {e}")

print("\n" + "=" * 60)
print("FULL RESET TAMAMLANDI!")
print(f"  Demo Kasa Hedefi: 100.00 USDT")
print(f"  Tum gecmis islemler silindi")
print(f"  Offset: {offset:.2f}")
print("=" * 60)
print("\nSimdi 'python main.py' ile botu yeniden baslatabilirsiniz.")
