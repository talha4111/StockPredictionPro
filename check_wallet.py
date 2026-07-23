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
    # Get all income history: REALIZED_PNL, FUNDING_FEE, COMMISSION etc.
    since = borsa.parse8601('2026-03-01T00:00:00Z')
    limit = 1000
    params = {}
    
    # fetch_income is a unified method or binance specific
    if borsa.has['fetchIncome']:
        incomes = borsa.fetch_income(since=since, limit=limit, params=params)
    else:
        incomes = borsa.fapiPrivateGetIncome({'limit': limit})
        
    summary = {}
    for item in incomes:
        # ccxt unified format or raw binance format depending on what it returns
        # binance raw format: {'symbol': '...', 'incomeType': 'COMMISSION', 'income': '-0.01', ...}
        # ccxt format: {'info': {'incomeType': '...', 'income': '...'}, ...}
        info = item.get('info', item)
        itype = info.get('incomeType', 'UNKNOWN')
        amount = float(info.get('income', 0))
        summary[itype] = summary.get(itype, 0) + amount

    print("\nIncome Summary since March 1, 2026:")
    for k, v in summary.items():
        print(f"  {k}: {v:.4f} USDT")
        
    total_change = sum(summary.values())
    print(f"\nNet Change: {total_change:.4f} USDT")

except Exception as e:
    print(f"API Error: {e}")
