import os, ccxt

if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k.strip()] = v.strip()

api = os.environ.get('LIVE_API_KEY', '').strip()
sec = os.environ.get('LIVE_SECRET_KEY', '').strip()

borsa = ccxt.binance({
    'apiKey': api,
    'secret': sec,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

try:
    poses = borsa.fetch_positions()
    active = [p for p in poses if float(p.get('contracts', 0) or 0) != 0]
    
    if not active:
        print("AKTIF_YOK")
    else:
        for p in active:
            sym = p['symbol']
            yon = 'LONG' if float(p['contracts']) > float(0) else 'SHORT'
            giris = float(p.get('entryPrice', 0))
            miktar = abs(float(p['contracts']))
            total_hacim = giris * miktar
            lev = float(p.get('leverage', 1) or 1)
            margin = total_hacim / lev if lev > 0 else 0

            pnl = p.get('unrealizedPnl', 0)

            print(f"SEMBOL: {sym}")
            print(f"YON: {yon}")
            print(f"MARGIN_RISK: {margin:.2f} USDT")
            print(f"HACIM: {total_hacim:.2f} USDT")
            print(f"KALDIRAC: {lev}x")
            print(f"PNL: {pnl}")
except Exception as e:
    print("HATA:", e)
