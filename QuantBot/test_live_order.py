import ccxt
import os
import time

if os.environ.get('ALLOW_REAL_ORDER_TEST') != 'I_UNDERSTAND_REAL_ORDER':
    print('LIVE emir testi kilitli. Calistirmak icin ALLOW_REAL_ORDER_TEST=I_UNDERSTAND_REAL_ORDER gerekir.')
    raise SystemExit(0)

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
    print("LIVE Binance İstemcisi Başlatılıyor...")
    borsa_live = ccxt.binance(borsa_live_config)
    borsa_live.load_markets()
    
    print("\nBakiyen (USDT):")
    bakiye = borsa_live.fetch_balance()
    print(bakiye.get('USDT', {}).get('total', 'Alınamadı'))

    symbol = 'BTC/USDT'
    ticker = borsa_live.fetch_ticker(symbol)
    price = ticker['last']
    
    hedef_kasa = 10.0 # 10 USDT'lik işlem
    kaldirac = 5
    islem_hacmi = hedef_kasa * kaldirac
    amount = islem_hacmi / price
    amount_str = borsa_live.amount_to_precision(symbol, amount)
    
    try:
        borsa_live.set_leverage(kaldirac, symbol)
    except Exception as e:
        print(f"Kaldıraç ayarlanamadı: {e}")

    print(f"\n[Test] {symbol} için {hedef_kasa} USDT ({amount_str} adet) değerinde Market BUY (LONG) Emri Gönderiliyor...")
    
    # Gerçek emir gönderimi!
    order = borsa_live.create_market_buy_order(symbol, float(amount_str))
    print("\n✅ MÜKEMMEL! Emir Başarıyla İletildi:")
    print(order)
    
except Exception as e:
    print(f"\n❌ API HATASI (EMİR İLETİLEMEDİ): {e}")

