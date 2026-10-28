import sys
sys.path.insert(0, '/root/QuantBot')
import json
from config import DEMO_API_KEY, DEMO_SECRET
import ccxt

borsa = ccxt.binanceusdm({
    'apiKey': DEMO_API_KEY,
    'secret': DEMO_SECRET,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'},
})
borsa.set_sandbox_mode(True)

bakiye = borsa.fetch_balance()
usdt = bakiye.get('USDT', {})
print("=== BINANCE TESTNET GERCEK BAKIYE ===")
print(f"  Toplam (Total): {usdt.get('total', 0):.2f} USDT")
print(f"  Kullanilabilir (Free): {usdt.get('free', 0):.2f} USDT")
print(f"  Kilit (Used/Margin): {usdt.get('used', 0):.2f} USDT")

pozisyonlar = borsa.fetch_positions()
print("\n=== ACIK POZISYONLAR ===")
toplam_upnl = 0.0
toplam_marjin = 0.0
for p in pozisyonlar:
    contracts = float(p.get('contracts', 0))
    if contracts == 0:
        continue
    sembol = p.get('symbol', '?')
    side = p.get('side', '?')
    upnl = float(p.get('unrealizedPnl', 0))
    marjin = float(p.get('initialMargin', 0) or p.get('collateral', 0) or 0)
    entry = float(p.get('entryPrice', 0))
    mark = float(p.get('markPrice', 0))
    leverage = p.get('leverage', '?')
    toplam_upnl += upnl
    toplam_marjin += marjin
    print(f"  {sembol:<15} | {side:<6} | Giris: {entry:.4f} | Mark: {mark:.4f} | uPnL: {upnl:+.2f} | Marjin: {marjin:.2f} | Kaldirac: {leverage}x")

print(f"\n  TOPLAM Unrealized PnL: {toplam_upnl:+.2f} USDT")
print(f"  TOPLAM Marjin (Kilitli): {toplam_marjin:.2f} USDT")

wallet = float(usdt.get('total', 0))
print(f"\n=== HESAPLAMA ===")
print(f"  Wallet Balance (Binance gosterdigi): {wallet:.2f} USDT")
print(f"  + Unrealized PnL: {toplam_upnl:+.2f} USDT")
print(f"  = Equity (Toplam Varlik): {wallet + toplam_upnl:.2f} USDT")
print(f"  Bot raporladigi DEMO_KASA: ~1683 USDT (dahili takip)")
print(f"  FARK: {wallet - 1683:.2f} USDT")
