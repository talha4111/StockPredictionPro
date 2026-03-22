import ccxt
borsa=ccxt.binance()
borsa.load_markets()
print('BTCDOM/USDT' in borsa.markets)
