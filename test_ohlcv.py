import ccxt
import pandas as pd
import time

borsa = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True}})

symbols = ['ALPACA/USDT', 'BTC/USDT', 'ETH/USDT']

for sym in symbols:
    try:
        print(f"Checking {sym}...")
        bars = borsa.fetch_ohlcv(sym, timeframe='15m', limit=100)
        print(f"  Bars count: {len(bars)}")
        if bars:
            print(f"  First bar: {bars[0]}")
    except Exception as e:
        print(f"  Error: {e}")
    time.sleep(1)
