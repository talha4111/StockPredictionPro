import ccxt
scout_borsa = ccxt.binance({'options': {'defaultType': 'future'}})
tikler = scout_borsa.fetch_tickers()
print("Total keys:", len(tikler.keys()))
print("Sample keys:")
for k in list(tikler.keys())[:10]:
    print(k)
