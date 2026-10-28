import ccxt
borsa_config = {
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
}
exchange = ccxt.binance(borsa_config)
exchange.set_sandbox_mode(True)
try:
    ticker = exchange.fetch_ticker('BTC/USDT')
    print("SUCCESS, price:", ticker['last'])
except Exception as e:
    print("FAILED:", e)
