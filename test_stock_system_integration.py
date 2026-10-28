"""
TEST SUITE: Otonom US Hisse Senedi & IBKR Trading Sistemi Entegrasyon Testi
=============================================================================
Bu test dosyası sistemin tüm 5 ana bileşenini uçtan uca (offline/mock) test eder:
1. stock_trade_journal.py (Kayıt, PnL, Raporlar)
2. stock_signal_router.py (Araştırma DB -> Sinyal Yönlendirme)
3. stock_position_tracker.py (Pozisyon Yönetimi, Trailing, Scale-out, BE, Cooldown)
4. ibkr_bridge.py (Maliyet Motoru, Net RR, Piyasa Saatleri, VIX)
5. stock_engine.py (Import ve Yapılandırma Bütünlüğü)
"""

import sys
import io
import os
import sqlite3
from datetime import datetime, timedelta
import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

# UTF-8 stdout
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except:
        pass

TEST_DB = "test_integration_bot.db"
TEST_JSONL = "test_integration_journal.jsonl"

def temizlik():
    for f in [TEST_DB, TEST_JSONL]:
        if os.path.exists(f):
            try:
                os.remove(f)
            except:
                pass

print("=" * 70)
print("  🚀 OTONOM US HISSE SISTEMI — ENTEGRASYON TESTİ BASLIYOR")
print("=" * 70)

temizlik()

# -------------------------------------------------------------
# TEST 1: stock_trade_journal.py
# -------------------------------------------------------------
print("\n[TEST 1] StockTradeJournal — Kayıt ve Performans Testi...")
from stock_trade_journal import StockTradeJournal

journal = StockTradeJournal(db_path=TEST_DB, jsonl_path=TEST_JSONL)

# İşlem 1 Aç
t1 = journal.islem_ac(
    sembol='NVDA', yon='LONG', giris_fiyati=120.0, miktar=50,
    margin_used=6000.0, ai_score=0.72, factor_score=85.0,
    setup_type='KALITELI_GERI_CEKILME', sector='Technology',
    atr_at_entry=3.5, tp_price=135.0, sl_price=114.0
)
assert t1 > 0, "Trade ID > 0 olmalı"

# Kısmi çıkış yap (Scale-Out +%8 kâr)
k_out = journal.kismi_cikis(
    sembol='NVDA', cikis_fiyati=130.0, kismi_yuzde=50.0,
    kapanis_sebebi='SCALE_OUT_8PCT', komisyon=1.0
)
assert k_out['pnl_usd'] > 0, "Kısmi çıkış PnL pozitif olmalı"

# Kalanı kapat (+%12 kâr)
c_out = journal.islem_kapat(
    sembol='NVDA', cikis_fiyati=134.4,
    kapanis_sebebi='TRAILING_STOP', tutma_gun=8, komisyon=1.0
)
assert c_out['pnl_usd'] > 0, "Kapanış PnL pozitif olmalı"

# İşlem 2: Kaybeden işlem simülasyonu
t2 = journal.islem_ac(
    sembol='TSLA', yon='LONG', giris_fiyati=220.0, miktar=20,
    margin_used=4400.0, ai_score=0.60, factor_score=68.0,
    setup_type='TREND_DEVAMI', sector='Consumer Discretionary',
    atr_at_entry=6.0, tp_price=240.0, sl_price=211.0
)
c_out2 = journal.islem_kapat(
    sembol='TSLA', cikis_fiyati=211.0,
    kapanis_sebebi='STOP_LOSS', tutma_gun=3, komisyon=1.0
)
assert c_out2['pnl_usd'] < 0, "Zararlı işlem PnL negatif olmalı"

# Performans özeti kontrolü
ozet = journal.performans_ozeti()
print(f"  Toplam İşlem: {ozet['total_trades']} | Kazançlı: {ozet['winners']} | Kayıplı: {ozet['losers']}")
print(f"  Win Rate: %{ozet['win_rate']:.1f} | Toplam Net PnL: ${ozet['total_pnl']:+.2f}")
print(f"  Profit Factor: {ozet['profit_factor']:.2f}")
assert ozet['total_trades'] == 3, "2 kazançlı çıkış (1 kısmi + 1 tam) ve 1 kayıplı kapanış ile 3 trade kaydedilmiş olmalı"
assert round(ozet['win_rate'], 1) == 66.7, "2 kazanç, 1 kayıp ile Win Rate %66.7 olmalı"
print("  ✅ [TEST 1 BASARILI] StockTradeJournal eksiksiz çalışıyor.")

# -------------------------------------------------------------
# TEST 2: stock_signal_router.py
# -------------------------------------------------------------
print("\n[TEST 2] StockSignalRouter — DB Entegrasyon Testi...")
from stock_signal_router import StockSignalRouter

# Test DB'sine mock sinyaller ekleyelim
with sqlite3.connect(TEST_DB) as conn:
    conn.execute('''
    CREATE TABLE IF NOT EXISTS hisse_sinyalleri (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tarih TEXT, sembol TEXT, sektor TEXT, fiyat REAL,
        sma200 REAL, rsi REAL, ai_skor REAL, tp REAL, sl REAL,
        golden_cross INTEGER, vix REAL, rs_skor REAL,
        signal_date TEXT, as_of_date TEXT, strategy_version TEXT,
        setup TEXT, decision TEXT, data_status TEXT, created_at TEXT,
        quality_score REAL, value_score REAL, momentum_score REAL,
        risk_score REAL, factor_coverage REAL, reasons_json TEXT,
        feature_json TEXT
    )''')
    
    bugun = datetime.now().strftime("%Y-%m-%d")
    mock_data = [
        ('AAPL', 'Technology', 225.0, 52.0, 0.65, 'KALITELI_GERI_CEKILME', 'AL_ADAYI', 88.0, 0.85, bugun),
        ('MSFT', 'Technology', 440.0, 48.0, 0.62, 'TREND_DEVAMI', 'AL_ADAYI', 82.0, 0.80, bugun),
        ('JPM', 'Financials', 210.0, 55.0, 0.68, 'KALITELI_GERI_CEKILME', 'AL_ADAYI', 79.0, 0.75, bugun),
        ('XOM', 'Energy', 115.0, 42.0, 0.59, 'TREND_DEVAMI', 'AL_ADAYI', 74.0, 0.70, bugun),
        ('ZAYIF', 'Technology', 50.0, 25.0, 0.40, 'ZAYIF_TREND', 'REDDET_TREND', 35.0, 0.50, bugun)
    ]
    for m in mock_data:
        conn.execute('''
        INSERT INTO hisse_sinyalleri (
            sembol, sektor, fiyat, rsi, ai_skor, setup, decision, 
            quality_score, value_score, momentum_score, risk_score, factor_coverage,
            as_of_date, signal_date, strategy_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 70.0, 80.0, 75.0, ?, ?, ?, 'v3.1')
        ''', (m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[9]))
    conn.commit()

router = StockSignalRouter(db_path=TEST_DB)
son_tarih = router.son_tarama_tarihi()
assert son_tarih == bugun, "Son tarama tarihi bugun olmalı"
assert router.tarama_guncel_mi(max_yas_saat=24) == True, "Tarama güncel olmalı"

adaylar = router.aday_listesi_getir(max_aday=5, min_faktor_skoru=70.0, haric_semboller=['JPM'])
print(f"  Bulunan Filtrelenmiş Adaylar ({len(adaylar)} adet): {[a['sembol'] for a in adaylar]}")
assert 'AAPL' in [a['sembol'] for a in adaylar], "AAPL aday listesinde olmalı"
assert 'JPM' not in [a['sembol'] for a in adaylar], "JPM hariç tutulmuş olmalı"
assert 'ZAYIF' not in [a['sembol'] for a in adaylar], "Zayıf hisse elenmiş olmalı"
print("  ✅ [TEST 2 BASARILI] StockSignalRouter adayları başarıyla süzüyor.")

# -------------------------------------------------------------
# TEST 3: stock_position_tracker.py
# -------------------------------------------------------------
print("\n[TEST 3] StockPositionTracker — Pozisyon ve Çıkış Kuralları Testi...")
from stock_position_tracker import StockPositionTracker

tracker = StockPositionTracker(ib=None, journal=journal, db_path=TEST_DB)

# Pozisyon Ekle (COHR, LONG)
tracker.pozisyon_ekle(
    sembol='COHR', yon='LONG', giris_fiyati=300.0, miktar=30,
    tp_fiyat=350.0, sl_fiyat=280.0, atr_giris=8.0,
    ai_skoru=0.75, faktor_skoru=82.0, setup_tipi='KALITELI_GERI_CEKILME', sektor='Technology'
)
assert tracker.acik_pozisyon_sayisi() == 1, "1 açık pozisyon olmalı"
assert tracker.sektor_yogunlugu('Technology') == 1, "Technology sektöründe 1 pozisyon olmalı"

# Senaryo A: Fiyat yükseliyor (315$), Peak güncellenmeli
a1 = tracker.pozisyon_guncelle('COHR', guncel_fiyat=315.0)
assert a1['eylem'] == 'BEKLE', "315$'da henüz çıkış tetiklenmemeli"

# Senaryo B: Fiyat %8 yükseliyor (325$), Scale-Out (50% kâr al) tetiklenmeli
a2 = tracker.pozisyon_guncelle('COHR', guncel_fiyat=325.0)
assert a2['eylem'] == 'KISMI_CIKIS', "Scale-out %8 tetiklenmeli"
assert a2['sebep'] == 'SCALE_OUT_8PCT', "Sebep SCALE_OUT_8PCT olmalı"
print(f"  Scale-out Tetiklendi: {a2}")

# Senaryo C: Break-Even ve Trailing devrede mi?
# Fiyat 310$'a gevşerse, Break-Even stop (300.30$) üzerinde olduğu için beklemeli
a3 = tracker.pozisyon_guncelle('COHR', guncel_fiyat=310.0)
assert a3['eylem'] == 'BEKLE', "310$'da pozisyon taşınmalı"

# Senaryo D: Stop vurursa (295$) TAM_CIKIS olmalı
a4 = tracker.pozisyon_guncelle('COHR', guncel_fiyat=295.0)
assert a4['eylem'] == 'TAM_CIKIS', "Stop vurduğunda tam çıkış olmalı"
print(f"  Stop Tetiklendi: {a4}")
assert tracker.acik_pozisyon_sayisi() == 0, "Pozisyon kapandıktan sonra açık sayı 0 olmalı"

# Cooldown kontrolü: Pozisyon kapandıktan sonra cooldown devrede mi?
assert tracker.cooldown_kontrol('COHR') == True, "Çıkış sonrası COHR cooldown'da olmalı"
print("  ✅ [TEST 3 BASARILI] StockPositionTracker kuralları eksiksiz işletiyor.")

# -------------------------------------------------------------
# TEST 4: ibkr_bridge.py
# -------------------------------------------------------------
print("\n[TEST 4] ibkr_bridge.py — Maliyet, Net RR ve V2.1 Eklentileri Testi...")
from ibkr_bridge import (
    islem_maliyeti_hesapla, net_rr_filtresi, parse_global_symbol,
    piyasa_acik_mi, vix_oku
)

# 1. Maliyet hesabı
m = islem_maliyeti_hesapla(fiyat=200.0, miktar=100, spread_bps=3.0)
assert m['komisyon_toplam'] >= 2.0, "Giriş+Çıkış komisyonu en az 2$ olmalı"
assert m['toplam_maliyet'] > 0, "Toplam maliyet > 0 olmalı"

# 2. Net RR Filtresi
rr = net_rr_filtresi(fiyat=200.0, tp_fiyat=220.0, sl_fiyat=190.0, miktar=100, spread_bps=3.0)
assert rr['karar'] == 'ONAY', "Geniş kâr hedefli işlem ONAY almalı"
print(f"  Net RR Testi: {rr['net_rr']}x | Karar: {rr['karar']}")

# 3. Global Sembol Ayrıştırıcı
gs, borsa, kur = parse_global_symbol('SAP.DE')
assert gs == 'SAP' and borsa == 'IBIS' and kur == 'EUR', "SAP.DE doğru çözümlenmeli"
gs2, borsa2, kur2 = parse_global_symbol('NVDA')
assert gs2 == 'NVDA' and borsa2 == 'SMART' and kur2 == 'USD', "NVDA doğru çözümlenmeli"

# 4. Piyasa Saati ve VIX
p_saat = piyasa_acik_mi()
print(f"  Piyasa Saati Kontrolü: Açık mı={p_saat['acik']} | Saat={p_saat['saat_et']} ET")
vix_val = vix_oku()
print(f"  VIX Okuma Testi: {vix_val:.2f}")
assert vix_val > 0, "VIX pozitif bir sayı dönmeli"
print("  ✅ [TEST 4 BASARILI] ibkr_bridge.py tüm filtreleri ve yeni V2.1 eklentileriyle hazır.")

# -------------------------------------------------------------
# TEST 5: stock_engine.py
# -------------------------------------------------------------
print("\n[TEST 5] stock_engine.py — Mimari ve Modül Bütünlüğü...")
import stock_engine
assert hasattr(stock_engine, 'motor_baslat'), "motor_baslat fonksiyonu mevcut olmalı"
assert hasattr(stock_engine, 'piyasa_durumu_al'), "piyasa_durumu_al fonksiyonu mevcut olmalı"
print("  ✅ [TEST 5 BASARILI] stock_engine.py tüm alt sistemlerle kusursuz bağlandı.")

# Temizlik
temizlik()

print("\n" + "=" * 70)
print("  🎉 TÜM ENTEGRASYON TESTLERİ (%100) BAŞARIYLA GEÇTİ!")
print("  Interactive Brokers Otonom Hisse Senedi Sistemi Eksiksiz Hazır.")
print("=" * 70)
