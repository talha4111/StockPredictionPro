"""
ACİL POZİSYON KAPATMA — HOME/USDT ve KITE/USDT
Önce tüm bekleyen emirleri iptal eder, sonra market emriyle kapatır.
"""
import sys
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import ccxt
import json
import os
import time

# --- API KEY YÜKLE ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, 'ayar.json'), 'r', encoding='utf-8') as f:
    ayar = json.load(f)

API_KEY = ayar.get('testnet_api_key', '').strip()
SECRET = ayar.get('testnet_secret', '').strip()

if not API_KEY:
    print("❌ API key bulunamadı!")
    sys.exit(1)

# --- BORSA BAĞLANTISI ---
borsa = ccxt.binanceusdm({
    'apiKey': API_KEY,
    'secret': SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
})
borsa.enable_demo_trading(True)

print("🔗 Binance Demo bağlantısı kuruldu.")
borsa.load_markets()

# --- KAPATILACAK SEMBOLLERİ BELİRLE ---
HEDEF_SEMBOLLER = ['KITE/USDT', 'HOME/USDT']

for sembol in HEDEF_SEMBOLLER:
    print(f"\n{'='*50}")
    print(f"🎯 {sembol} İŞLENİYOR...")
    print(f"{'='*50}")
    
    # ADIM 1: TÜM AÇIK EMİRLERİ İPTAL ET
    try:
        acik_emirler = borsa.fetch_open_orders(sembol)
        if acik_emirler:
            print(f"  📋 {len(acik_emirler)} açık emir bulundu, iptal ediliyor...")
            for emir in acik_emirler:
                try:
                    borsa.cancel_order(emir['id'], sembol)
                    print(f"  ✅ Emir iptal edildi: {emir['id']} ({emir.get('type', '?')})")
                except Exception as e:
                    print(f"  ⚠️ Emir iptal hatası ({emir['id']}): {e}")
        else:
            print(f"  ℹ️ Açık emir yok.")
    except Exception as e:
        print(f"  ⚠️ Emir listesi alınamadı: {e}")
    
    # Ek güvenlik: cancel_all_orders
    try:
        borsa.cancel_all_orders(sembol)
        print(f"  🧹 cancel_all_orders çağrıldı.")
    except Exception as e:
        print(f"  ⚠️ cancel_all_orders hatası: {e}")
    
    # Binance özel API ile tüm şartlı emirleri temizle
    try:
        market_id = borsa.market_id(sembol)
        borsa.fapiPrivateDeleteAllOpenOrders({'symbol': market_id})
        print(f"  🧹 Binance özel API ile tüm emirler silindi.")
    except Exception as e:
        print(f"  ⚠️ Özel API temizleme: {e}")
    
    print(f"  ⏳ 3 saniye bekleniyor (emirlerin temizlenmesi için)...")
    time.sleep(3)
    
    # ADIM 2: POZİSYON BİLGİSİNİ ÇEK
    try:
        pozisyonlar = borsa.fetch_positions([sembol])
        acik_poz = None
        for p in pozisyonlar:
            amt = float(p.get('info', {}).get('positionAmt', 0))
            if abs(amt) > 0:
                acik_poz = p
                break
        
        if not acik_poz:
            print(f"  ℹ️ {sembol} pozisyonu zaten kapalı (miktar = 0).")
            continue
        
        miktar = abs(float(acik_poz['info']['positionAmt']))
        yon = 'LONG' if float(acik_poz['info']['positionAmt']) > 0 else 'SHORT'
        pnl = float(acik_poz.get('unrealizedPnl', 0))
        giris = float(acik_poz.get('entryPrice', 0))
        guncel = float(acik_poz.get('markPrice', 0))
        
        print(f"\n  📊 POZİSYON DETAYI:")
        print(f"     Yön: {yon}")
        print(f"     Miktar: {miktar}")
        print(f"     Giriş: {giris}")
        print(f"     Güncel: {guncel}")
        print(f"     PNL: {pnl:+.2f}$")
        
        # ADIM 3: MARKET EMRİ İLE KAPAT
        zit_yon = 'sell' if yon == 'LONG' else 'buy'
        
        print(f"\n  🔥 {sembol} KAPATILIYOR... ({zit_yon.upper()} x {miktar})")
        
        emir = borsa.create_order(
            symbol=sembol,
            type='MARKET',
            side=zit_yon,
            amount=miktar,
            params={'reduceOnly': True}
        )
        
        print(f"  ✅ {sembol} BAŞARIYLA KAPATILDI!")
        print(f"     PNL: {pnl:+.2f}$")
        
    except Exception as e:
        print(f"  ❌ KAPATIŞ HATASI: {e}")
        
        print(f"  ❌ {sembol} reduce-only kapatma başarısız; pozisyon büyütme riski nedeniyle ikinci emir gönderilmiyor.")
        print(f"  ⚠️ Binance arayüzünden pozisyonu ve açık emirleri manuel doğrulayın.")

print(f"\n{'='*50}")
print(f"✅ İşlem tamamlandı!")
print(f"{'='*50}")
