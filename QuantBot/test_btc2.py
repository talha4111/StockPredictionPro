import ccxt
borsa=ccxt.binance({'options': {'defaultType': 'future'}})
borsa.load_markets()
print('BTCDOMUSDT' in borsa.markets)
print('BTC/USDT' in borsa.markets)
