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
    bal = borsa.fetch_balance({'type': 'future'})
    info = bal.get('info', {})
    print("Keys in bal['info']:")
    for k in info.keys():
        print(f" - {k}")
    print("\ntotalWalletBalance in info:", info.get('totalWalletBalance', 'NOT FOUND'))
    print("\ntotalMarginBalance in info:", info.get('totalMarginBalance', 'NOT FOUND'))
    print("\nassets list:")
    for a in info.get('assets', []):
        if a.get('asset') == 'USDT':
            print("  USDT:", a)
except Exception as e:
    print("Error:", e)
