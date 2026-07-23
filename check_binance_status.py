import ccxt
import os

if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

LIVE_API_KEY = os.environ.get('LIVE_API_KEY', '')
LIVE_SECRET = os.environ.get('LIVE_SECRET_KEY', '')

borsa_live_config = {
    'apiKey': LIVE_API_KEY,
    'secret': LIVE_SECRET,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
}

try:
    borsa = ccxt.binance(borsa_live_config)
    balance = borsa.fetch_balance()
    usdt_total = balance.get('USDT', {}).get('total', 0)
    usdt_free = balance.get('USDT', {}).get('free', 0)
    
    print(f"USDT Total: {usdt_total}")
    print(f"USDT Free: {usdt_free}")
    print(f"Used Margin: {usdt_total - usdt_free}")
    
    positions = borsa.fetch_positions()
    open_positions = [p for p in positions if p.get('contracts', 0) > 0]
    
    print(f"\nOpen Positions: {len(open_positions)}")
    for p in open_positions:
        symbol = p['info']['symbol']
        size = p['info']['positionAmt']
        entry = p['info']['entryPrice']
        pnl = p['info']['unRealizedProfit']
        print(f"Symbol: {symbol}, Size: {size}, Entry: {entry}, UnRealized PnL: {pnl}")
        
    trades = borsa.fetch_my_trades(limit=50)
    print("\nRecent Binance API Trades:")
    for t in trades[-10:]:
        print(f"{t['datetime']} | {t['symbol']} | {t['side']} | size: {t['amount']} | price: {t['price']} | fee: {t.get('fee')}")
except Exception as e:
    import traceback
    print(f"API Error Type: {type(e).__name__}")
    print(f"API Error: {e}")
    traceback.print_exc()
