"""
Teşhis Scripti: Botun demo bakiyesini neden 0$ gördüğünü tespit eder.
"""
import ccxt
import os
import json
import sys

# 1. Ayarları yükle (aynı main.py gibi)
try:
    with open('ayar.json', 'r', encoding='utf-8') as f:
        AYAR = json.load(f)
    TESTNET_API_KEY = AYAR.get("testnet_api_key", "").strip()
    TESTNET_SECRET = AYAR.get("testnet_secret", "").strip()
except:
    TESTNET_API_KEY = ""
    TESTNET_SECRET = ""

TESTNET_API_KEY = os.environ.get('TESTNET_API_KEY', TESTNET_API_KEY).strip()
TESTNET_SECRET = os.environ.get('TESTNET_SECRET', TESTNET_SECRET).strip()

print("=" * 60)
print("🔍 DEMO BAKİYE TEŞHİS RAPORU")
print("=" * 60)
print(f"API Key (ilk 8 karakter): {TESTNET_API_KEY[:8]}..." if TESTNET_API_KEY else "API Key: BOŞ!")
print(f"Secret  (ilk 8 karakter): {TESTNET_SECRET[:8]}..." if TESTNET_SECRET else "Secret: BOŞ!")

# 2. CCXT versiyonunu göster
print(f"\nCCXT Versiyonu: {ccxt.__version__}")

# 3. enable_demo_trading ile bağlan (main.py ile aynı)
borsa = ccxt.binanceusdm({
    'apiKey': TESTNET_API_KEY,
    'secret': TESTNET_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
})
borsa.enable_demo_trading(True)

# 4. Hangi URL'ye bağlanıyor?
print(f"\n📡 API Base URL: {borsa.urls.get('api', {})}")
if hasattr(borsa, 'hostname'):
    print(f"📡 Hostname: {borsa.hostname}")

# 5. Bakiye çek
print("\n--- fetch_balance() sonucu ---")
try:
    bal = borsa.fetch_balance({'type': 'future'})
    usdt = bal.get('USDT', {})
    print(f"USDT total:  {usdt.get('total', 'YOK')}")
    print(f"USDT free:   {usdt.get('free', 'YOK')}")
    print(f"USDT used:   {usdt.get('used', 'YOK')}")
    
    # RAW info
    info = bal.get('info', {})
    print(f"\n--- RAW Binance info ---")
    print(f"totalWalletBalance:  {info.get('totalWalletBalance', 'YOK')}")
    print(f"totalMarginBalance:  {info.get('totalMarginBalance', 'YOK')}")
    print(f"availableBalance:    {info.get('availableBalance', 'YOK')}")
    print(f"totalUnrealizedProfit: {info.get('totalUnrealizedProfit', 'YOK')}")
    
    # Assets dizisinden USDT'yi bul
    assets = info.get('assets', [])
    for a in assets:
        if a.get('asset') == 'USDT':
            print(f"\n--- RAW USDT Asset ---")
            print(f"  walletBalance:      {a.get('walletBalance')}")
            print(f"  marginBalance:      {a.get('marginBalance')}")
            print(f"  availableBalance:   {a.get('availableBalance')}")
            break
    else:
        print("\n⚠️ RAW assets içinde USDT bulunamadı!")
        if assets:
            print(f"   Mevcut assetler: {[a.get('asset') for a in assets[:5]]}")
    
except Exception as e:
    print(f"❌ HATA: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
