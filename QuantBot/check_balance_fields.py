import json
import ccxt

with open('ayar.json', 'r') as f:
    ayar = json.load(f)

testnet_key = ayar.get("testnet_api_key", "").strip()
testnet_secret = ayar.get("testnet_secret", "").strip()

borsa = ccxt.binanceusdm({
    'apiKey': testnet_key,
    'secret': testnet_secret,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
})
borsa.enable_demo_trading(True)

try:
    print("Fetching raw balance from Binance Futures Demo...")
    bal = borsa.fetch_balance({'type': 'future'})
    print(f"bal['total']['USDT'] = {bal.get('total', {}).get('USDT')}")
    print(f"bal['free']['USDT'] = {bal.get('free', {}).get('USDT')}")
    print(f"bal['used']['USDT'] = {bal.get('used', {}).get('USDT')}")
    
    usdt_info = bal.get('USDT', {})
    print("\nUSDT specific object:")
    for k, v in usdt_info.items():
        if k == 'info': continue
        print(f"  {k}: {v}")
        
    print("\nRaw info (Binance payload):")
    info = bal.get('info', {})
    assets = info.get('assets', [])
    for a in assets:
        if a.get('asset') == 'USDT':
            for k, v in a.items():
                print(f"  {k}: {v}")
except Exception as e:
    print("Error:", e)
