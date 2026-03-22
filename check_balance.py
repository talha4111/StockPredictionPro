import ccxt
import json
import os

with open('ayar.json', 'r') as f:
    ayar = json.load(f)

borsa_config = {
    'apiKey': ayar['testnet_api_key'],
    'secret': ayar['testnet_secret'],
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
}

try:
    borsa = ccxt.binance(borsa_config)
    borsa.enable_demo_trading(True)

    bal = borsa.fetch_balance()
    print("Mevcut Kasa (USDT):", bal.get('USDT', {}).get('total', 'Yok'))

    positions = borsa.fetch_positions()
    aciklar = [p for p in positions if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0]
    print("\nAçık Pozisyonlar:")
    for p in aciklar:
        print(f"{p['symbol']} | Yön: {'LONG' if float(p['contracts']) > 0 else 'SHORT'} | PnL: {p.get('unrealizedPnl')} | Miktar: {p['contracts']}")

    print("\nSon Kapatilan Islemler (MyTrades):")
    # Fetch some closed trades from recent history, maybe the last day. 
    # fetch_my_trades doesn't always show PNL explicitly but we can see execution info.
    # Alternatively fetch_closed_orders? fetch_account_income?
    
    # In testnet, income history shows REALIZED_PNL
    income = borsa.sapiGetAccountIncome(params={'incomeType': 'REALIZED_PNL', 'limit': 15})
    for inc in income:
        print(f"[{inc['time']}] {inc['symbol']} -> PNL: {inc['income']} | Varlik: {inc['asset']}")

except Exception as e:
    print("Hata:", e)
