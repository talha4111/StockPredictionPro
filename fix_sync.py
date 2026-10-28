"""
SYNC FIX: main.py ve position_tracker.py'deki bakiye senkronizasyon sorunlarını düzeltir.

SORUN: DEMO_KASA, fetch_balance().USDT.total'dan alınıyordu.
Bu değer Binance'in "Margin Balance"'ıdır (unrealized PnL dahil),
"Wallet Balance" DEĞİLDİR. Bu yüzden bot $1683, Binance $1495 gösteriyordu.

ÇÖZÜM: Her yerde Binance RAW API'nin totalWalletBalance'ını kullan.
"""
import re

# ============================================================
# FIX 1: main.py — Başlangıç senkronizasyonu
# ============================================================
with open('QuantBot/main.py', 'r', encoding='utf-8') as f:
    main_text = f.read()

# Eski kod bloğunu bul ve değiştir
old_sync = '''            _sync_bal = borsa.fetch_balance({'type': 'future'})
            _testnet_bakiye_raw = float(_sync_bal.get('USDT', {}).get('total', 0))
            try:
                with open('ayar.json', 'r') as _f:
                    _demo_offset = float(json.load(_f).get('demo_bakiye_offset', 0.0))
            except:
                _demo_offset = 0.0
            
            _testnet_bakiye = _testnet_bakiye_raw - _demo_offset
            
            if _testnet_bakiye > 0:
                KASA_DURUM['DEMO_KASA'] = _testnet_bakiye
                KASA_DURUM['DEMO_EQUITY'] = _testnet_bakiye
                _DEMO_CACHE['bakiye'] = _testnet_bakiye
                _DEMO_CACHE['son_guncelleme'] = time.time()'''

new_sync = '''            _sync_bal = borsa.fetch_balance({'type': 'future'})
            _sync_raw = _sync_bal.get('info', {})
            try:
                with open('ayar.json', 'r') as _f:
                    _demo_offset = float(json.load(_f).get('demo_bakiye_offset', 0.0))
            except:
                _demo_offset = 0.0
            
            # TEK KAYNAK: totalWalletBalance (komisyon/funding dahil, PnL haric)
            _raw_wallet = float(_sync_raw.get('totalWalletBalance', 0) or 0)
            if _raw_wallet > 0:
                _testnet_bakiye = _raw_wallet - _demo_offset
            else:
                _testnet_bakiye = float(_sync_bal.get('USDT', {}).get('total', 0)) - _demo_offset
            
            if _testnet_bakiye > 0:
                KASA_DURUM['DEMO_KASA'] = _testnet_bakiye
                KASA_DURUM['DEMO_EQUITY'] = _testnet_bakiye
                _DEMO_CACHE['bakiye'] = _testnet_bakiye
                _DEMO_CACHE['raw'] = _sync_raw
                _DEMO_CACHE['son_guncelleme'] = time.time()'''

if old_sync in main_text:
    main_text = main_text.replace(old_sync, new_sync)
    print("FIX 1: main.py baslangic sync DUZELTILDI")
else:
    print("FIX 1: UYARI - main.py'de eski sync blogu bulunamadi!")

# Sync mesajini da guncelle
main_text = main_text.replace(
    'Demo kasa Binance ile senkronize edildi: ${_testnet_bakiye:.2f} (Offset: -${_demo_offset:.2f})',
    'Demo kasa Binance Wallet Balance ile senkronize edildi: ${_testnet_bakiye:.2f}'
)

with open('QuantBot/main.py', 'w', encoding='utf-8') as f:
    f.write(main_text)

# ============================================================
# FIX 2: position_tracker.py — Bakiye guncelleme blogu
# ============================================================
with open('QuantBot/position_tracker.py', 'r', encoding='utf-8') as f:
    pt_text = f.read()

# FIX 2a: Bakiye cache blogu — totalWalletBalance'a oncelik ver
old_balance = '''                    bakiye_demo_raw = float(_demo_bal_full.get('USDT', {}).get('total', 0.0))
                    bakiye_demo = bakiye_demo_raw - _demo_offset if bakiye_demo_raw > 0 else 0.0
                    _demo_bal_raw = _demo_bal_full.get('info', {})'''

new_balance = '''                    _demo_bal_raw = _demo_bal_full.get('info', {})
                    
                    # ONCELIK: RAW API totalWalletBalance > CCXT total
                    _raw_wallet_fresh = float(_demo_bal_raw.get('totalWalletBalance', 0) or 0)
                    if _raw_wallet_fresh > 0:
                        bakiye_demo = _raw_wallet_fresh - _demo_offset
                    else:
                        bakiye_demo_raw = float(_demo_bal_full.get('USDT', {}).get('total', 0.0))
                        bakiye_demo = bakiye_demo_raw - _demo_offset if bakiye_demo_raw > 0 else 0.0'''

if old_balance in pt_text:
    pt_text = pt_text.replace(old_balance, new_balance)
    print("FIX 2a: position_tracker.py bakiye cache DUZELTILDI")
else:
    print("FIX 2a: UYARI - position_tracker.py'de eski bakiye blogu bulunamadi!")

# FIX 2b: Kasa durumu blogu — wallet_demo hesaplamasi
old_kasa = '''            # Offset'i sadece gerçek değer geldiğinde uygula (RAW boşsa uygulamadan fallback'e düş)
            if _raw_margin > 0:
                margin_demo = _raw_margin - _demo_offset
            else:
                margin_demo = bakiye_demo  # bakiye_demo zaten offset uygulanmış
                
            if _raw_wallet > 0:
                wallet_demo = _raw_wallet - _demo_offset
            else:
                wallet_demo = bakiye_demo - toplam_pnl_demo  # bakiye_demo zaten offset uygulanmış
            
            # Binance'de Varlık (Equity/Margin Balance) zaten PNL'i içerir.
            # O yüzden toplam_pnl'yi tekrar eklemiyoruz (Double-counting önlendi)!
            equity_demo = margin_demo'''

new_kasa = '''            # Wallet Balance: Binance'in gosterdigi gercek USDT bakiyesi (unrealized PnL HARIC)
            if _raw_wallet > 0:
                wallet_demo = _raw_wallet - _demo_offset
            else:
                wallet_demo = bakiye_demo  # API bossa cache'den al
                
            # Equity (Margin Balance): Wallet + Unrealized PnL = Binance'in gosterdigi Toplam Varlik
            if _raw_margin > 0:
                equity_demo = _raw_margin - _demo_offset
            else:
                equity_demo = wallet_demo + toplam_pnl_demo'''

if old_kasa in pt_text:
    pt_text = pt_text.replace(old_kasa, new_kasa)
    print("FIX 2b: position_tracker.py kasa durumu DUZELTILDI")
else:
    print("FIX 2b: UYARI - position_tracker.py'de eski kasa blogu bulunamadi!")

with open('QuantBot/position_tracker.py', 'w', encoding='utf-8') as f:
    f.write(pt_text)

print("\nTum duzeltmeler tamamlandi.")
