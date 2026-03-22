import os
import ccxt

if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k.strip()] = v.strip()

api = os.environ.get('LIVE_API_KEY', '').strip()
sec = os.environ.get('LIVE_SECRET_KEY', '').strip()

try:
    # 1. Check Spot
    borsa_spot = ccxt.binance({'apiKey': api, 'secret': sec})
    bal_spot = borsa_spot.fetch_balance()
    usdt_spot = bal_spot.get('USDT', {}).get('total', 0.0)
    print(f"SPOT USDT: {usdt_spot}")

    # 2. Check Futures
    borsa_future = ccxt.binance({'apiKey': api, 'secret': sec, 'options': {'defaultType': 'future'}})
    bal_future = borsa_future.fetch_balance()
    usdt_future = bal_future.get('USDT', {}).get('total', 0.0)
    print(f"FUTURES USDT: {usdt_future}")

except Exception as e:
    print(f"ERROR: {e}")
