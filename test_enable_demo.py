import ccxt
borsa_config = {
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
}
exchange = ccxt.binanceusdm(borsa_config)
try:
    exchange.enable_demo_trading(True)
    ticker = exchange.fetch_ticker('BTC/USDT')
    print("enable_demo_trading SUCCESS on binanceusdm! Price:", ticker['last'])
except Exception as e:
    print("enable_demo_trading FAILED on binanceusdm:", e)

# Test on just binance
exchange = ccxt.binance(borsa_config)
try:
    exchange.enable_demo_trading(True)
    ticker = exchange.fetch_ticker('BTC/USDT')
    print("enable_demo_trading SUCCESS on binance! Price:", ticker['last'])
except Exception as e:
    print("enable_demo_trading FAILED on binance:", e)

