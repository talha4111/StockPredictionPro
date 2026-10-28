#!/usr/bin/env python3
"""Binance DEMO vs LIVE Ortam Karsilastirma Testi"""
import ccxt, json, os, sys, io

if sys.stdout.encoding != 'utf-8':
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except: pass

with open('ayar.json','r') as f:
    ayar = json.load(f)
tkey = ayar.get('testnet_api_key','')
tsec = ayar.get('testnet_secret','')

# ===== TEST 1: DEMO ORTAMI =====
print("=" * 60)
print("  TEST 1: DEMO ORTAMI (demo-fapi.binance.com)")
print("  -> Botun islem yaptigi sanal ortam")
print("=" * 60)
d1 = ccxt.binanceusdm({
    'apiKey': tkey, 'secret': tsec, 'enableRateLimit': True,
    'options': {'defaultType':'future','adjustForTimeDifference':True,'recvWindow':60000}
})
d1.enable_demo_trading(True)
fapi_url = d1.urls.get('api',{})
print(f"  API URL: {fapi_url.get('fapiPrivate','?')}")
try:
    b1 = d1.fetch_balance({'type':'future'})
    bakiye1 = float(b1.get('USDT',{}).get('total',0))
    print(f"  Bakiye: {bakiye1:.2f} USDT")
    p1 = d1.fetch_positions()
    cnt1 = 0
    for p in p1:
        amt = float(p.get('contracts', p.get('info',{}).get('positionAmt',0)))
        if amt != 0:
            sym = p.get('symbol','?')
            entry = float(p.get('entryPrice', p.get('info',{}).get('entryPrice',0)))
            pnl = float(p.get('unrealizedPnl', p.get('info',{}).get('unRealizedProfit',0)))
            side = 'LONG' if amt > 0 else 'SHORT'
            print(f"    {sym:20s} | {side} | PNL: {pnl:+.2f}")
            cnt1 += 1
    if cnt1 == 0:
        print("    Acik pozisyon YOK")
    print(f"  Toplam: {cnt1} pozisyon")
except Exception as e:
    print(f"  HATA: {e}")

# ===== TEST 2: LIVE ORTAMI =====
print()
print("=" * 60)
print("  TEST 2: LIVE ORTAMI (fapi.binance.com)")
print("  -> Binance uygulamasinda gordugun gercek hesap")
print("=" * 60)

live_key = ''
live_sec = ''
try:
    with open('../.env') as ef:
        for line in ef:
            line = line.strip()
            if line.startswith('LIVE_API_KEY='):
                live_key = line.split('=',1)[1]
            elif line.startswith('LIVE_SECRET_KEY='):
                live_sec = line.split('=',1)[1]
except:
    pass

if live_key:
    d2 = ccxt.binanceusdm({
        'apiKey': live_key, 'secret': live_sec, 'enableRateLimit': True,
        'options': {'defaultType':'future','adjustForTimeDifference':True,'recvWindow':60000}
    })
    fapi_url2 = d2.urls.get('api',{})
    print(f"  API URL: {fapi_url2.get('fapiPrivate','?')}")
    try:
        b2 = d2.fetch_balance({'type':'future'})
        bakiye2 = float(b2.get('USDT',{}).get('total',0))
        print(f"  Bakiye: {bakiye2:.2f} USDT")
        p2 = d2.fetch_positions()
        cnt2 = 0
        for p in p2:
            amt = float(p.get('contracts', p.get('info',{}).get('positionAmt',0)))
            if amt != 0:
                sym = p.get('symbol','?')
                pnl = float(p.get('unrealizedPnl', p.get('info',{}).get('unRealizedProfit',0)))
                side = 'LONG' if amt > 0 else 'SHORT'
                print(f"    {sym:20s} | {side} | PNL: {pnl:+.2f}")
                cnt2 += 1
        if cnt2 == 0:
            print("    Acik pozisyon YOK")
        print(f"  Toplam: {cnt2} pozisyon")
    except Exception as e:
        print(f"  HATA: {e}")
else:
    print("  LIVE key bulunamadi")

# ===== SONUC =====
print()
print("=" * 60)
print("  SONUC VE ACIKLAMA")
print("=" * 60)
print("  Sen Binance uygulamasinda TEST 2 (LIVE) hesabini goruyorsun.")
print("  Bot ise TEST 1 (DEMO) ortaminda islem yapiyor.")
print("  KITE, HOME gibi pozisyonlar DEMO ortaminda acilmis.")
print("  Binance uygulamasinda goremezsin cunku ayri ortamlar!")
print("  Binance uygulamasinda Demo Trading moduna gecersen gorebilirsin.")
