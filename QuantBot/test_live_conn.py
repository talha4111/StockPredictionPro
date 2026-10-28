import os, ccxt

# .env dosyasini oku
with open('.env', 'r') as f:
    for line in f:
        line = line.strip()
        if '=' in line and not line.startswith('#'):
            k, v = line.split('=', 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")

key = os.environ.get('LIVE_API_KEY', '')
secret = os.environ.get('LIVE_SECRET_KEY', '')

print(f"Key uzunluk: {len(key)}")
print(f"Secret uzunluk: {len(secret)}")

if not key or not secret:
    print("HATA: API key veya secret BOS!")
else:
    try:
        b = ccxt.binance({
            'apiKey': key,
            'secret': secret,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}
        })
        bal = b.fetch_balance()
        usdt = bal.get('USDT', {}).get('total', 'YOK')
        print(f"LIVE BAKIYE: {usdt} USDT")
        print("API BAGLANTISI BASARILI!")
    except Exception as e:
        print(f"API HATASI: {e}")
