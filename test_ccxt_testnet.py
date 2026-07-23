import ccxt
print("CCXT version:", ccxt.__version__)
exchange = ccxt.binanceusdm()
exchange.set_sandbox_mode(True)
try:
    ticker = exchange.fetch_ticker('BTC/USDT')
    print("set_sandbox_mode fetch_ticker succeeded:", ticker['last'])
except Exception as e:
    print("set_sandbox_mode fetch_ticker failed:", e)

# Test binance testnet
try:
    exchange = ccxt.binance({
        'options': {'defaultType': 'future'}
    })
    exchange.set_sandbox_mode(True)
    ticker = exchange.fetch_ticker('BTC/USDT')
    print("binance future sandbox fetch_ticker succeeded:", ticker['last'])
except Exception as e:
    print("binance future sandbox failed:", e)
