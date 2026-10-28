import ccxt
import time
import os
import yfinance as yf

# API Keys
if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k] = v

LIVE_API = os.environ.get('LIVE_API_KEY', '')
LIVE_SEC = os.environ.get('LIVE_SECRET_KEY', '')

# Ayarlar (demo)
import json
try:
    with open('ayar.json') as f: a = json.load(f)
    DEMO_API = a.get('TESTNET_API_KEY', '')
    DEMO_SEC = a.get('TESTNET_SECRET', '')
except:
    DEMO_API = DEMO_SEC = ""

def stats():
    print("=== BINANCE TESTNET (DEMO) DURUMU ===")
    try:
        borsa = ccxt.binance({
            'apiKey': DEMO_API,
            'secret': DEMO_SEC,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True}
        })
        borsa.set_sandbox_mode(True)
        bal = borsa.fetch_balance()
        print(f"Kasa: {bal.get('USDT', {}).get('total', 'Yok')} USDT")
        pos = borsa.fetch_positions()
        acik = [p for p in pos if float(p.get('contracts', 0)) != 0]
        print(f"Acik Pozisyonlar ({len(acik)} adet):")
        for p in acik:
            print(f" - {p.get('symbol')} | Yon: {p.get('info', {}).get('positionSide', '')} | PNL: {p.get('unrealizedPnl')}")
    except Exception as e:
        print("Demo Hata:", e)

    print("\n=== AI MODELLERI ===")
    pkl = [f for f in os.listdir('.') if f.endswith('.pkl') or f.endswith('.keras')]
    for m in pkl[:10]:
        st = os.stat(m)
        print(f"{m} - Son Deg: {time.ctime(st.st_mtime)}")
        
stats()
