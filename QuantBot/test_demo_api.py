import ccxt
import json
import os

with open('ayar.json', 'r') as f:
    ayar = json.load(f)

# TESTNET API Ayarları
testnet_key = ayar.get("testnet_api_key", "").strip()
testnet_secret = ayar.get("testnet_secret", "").strip()

print(f"Key: {testnet_key[:5]}...")
print(f"Secret: {testnet_secret[:5]}...")

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
borsa.enable_demo_trading(True) # TESTNET AKTIF

try:
    print("Testnet bakiye çekiliyor...")
    bal = borsa.fetch_balance()
    print("BAŞARILI!")
    print(f"Bakiye: {bal.get('USDT', {}).get('total', 'YOK')} USDT")
except Exception as e:
    print(f"HATA: {e}")
