import sys
import os
# Windows cp1254 Türkçe encoding emoji çökmelerini önle
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

_INSTANCE_LOCK_HANDLE = None
if __name__ == "__main__":
    from instance_lock import InstanceAlreadyRunning, acquire_instance_lock

    try:
        _INSTANCE_LOCK_HANDLE = acquire_instance_lock()
    except InstanceAlreadyRunning as exc:
        print(f"[KRITIK] {exc}")
        raise SystemExit(73)

import numpy as np
import pandas as pd
from ai_core import BeyinMotoru

from tarayici import veri_getir_dortlu
from analist import korku_acgozluluk_getir, onchain_inflow_durumu, makro_volatilite_beklentisi
import json
from exit_rules import process_demo_exit_rules
import requests
import time
import threading 
from collections import Counter
from datetime import datetime
import joblib
import csv
import sqlite3
import websocket
import glob

from signal_engine import analiz_motoru
from order_engine import islem_ac, canli_islem_kapat
from position_tracker import pozisyon_takip_paneli
from scanner_loop import surekli_tarama_ve_analiz
from db_logger import (
    islem_kaydet, _detay_yukle, _detay_kaydet, _detay_senkronize,
    telegrama_gonder, gunluk_rapor_gonder,
    demo_journal_status_guncelle, demo_dispatch_ret_kaydet,
)
from account_sync import demo_muhasebe_baslat
from symbol_guard import sembol_guard_yukle, resmi_zarar_karantinasi_tazele
try:
    from runtime_status import olay_kaydet, status_yaz
except Exception:
    def status_yaz(guncelleme=None, event=None):
        return {}
    def olay_kaydet(tip, mesaj, **detay):
        return {}

try:
    from demo_trade_journal import (
        acilis_kaydet as demo_acilis_kaydet,
        rapor_kaydet as demo_rapor_kaydet,
    )
except Exception:
    def demo_acilis_kaydet(**detay):
        return {}
    def demo_rapor_kaydet(rapor):
        return {}

from config import *
from risk_manager import *
WSS_TICKERS = {}

def wss_on_message(ws, message):
    try:
        data = json.loads(message)
        for t in data:
            sym = t['s']
            if sym.endswith('USDT'):
                clean_sym = f"{sym[:-4]}/USDT"
                WSS_TICKERS[clean_sym] = float(t['c'])
    except:
        pass

def wss_on_error(ws, error): pass
def wss_on_close(ws, close_status_code, close_msg): 
    time.sleep(2)
    start_wss_thread()

def start_wss():
    ws = websocket.WebSocketApp("wss://fstream.binance.com/ws/!ticker@arr",
                                on_message=wss_on_message,
                                on_error=wss_on_error,
                                on_close=wss_on_close)
    ws.run_forever()

def start_wss_thread():
    t = threading.Thread(target=start_wss, daemon=True)
    t.start()

start_wss_thread()
print("[SİSTEM] WebSocket (WSS) Veri Nehri Başlatıldı! 🌊")

# CCXT Kutubhanesi Kontrolu
try:
    import ccxt
except ImportError:
    print("[!] Uyari: 'ccxt' kutuphanesi bulunamadi!")
    print("[!] Kripto islemleri hatasiz devam edebilmesi icin sanal (dummy) modda calistirilacak.")
    
    class DummyBorsa:
        def enable_demo_trading(self, *args, **kwargs): pass
        def load_markets(self): pass
        def fetch_tickers(self, symbols=None): return {}
        def fetch_positions(self): return []
        def fetch_balance(self): return {'USDT': {'total': 1000.0}}
        def set_leverage(self, *args, **kwargs): pass
        def amount_to_precision(self, symbol, amount): return round(amount, 3)
        def price_to_precision(self, symbol, price): return round(price, 2)
        def cancel_all_orders(self, symbol): pass
        def create_market_buy_order(self, *args, **kwargs): return {'average': 0, 'price': 0}
        def create_market_sell_order(self, *args, **kwargs): return {'average': 0, 'price': 0}
        def create_order(self, *args, **kwargs): pass

    class DummyCCXT:
        NetworkError = Exception
        def binance(self, *args, **kwargs): return DummyBorsa()
        
    sys.modules['ccxt'] = DummyCCXT()
    ccxt = DummyCCXT()

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Binance CCXT Bağlantısı (Sandbox Mode)
borsa_config = {
    'apiKey': TESTNET_API_KEY,
    'secret': TESTNET_SECRET,
    'enableRateLimit': True, 
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
}
borsa = ccxt.binanceusdm(borsa_config)
borsa.enable_demo_trading(True) # YENİ CCXT GÜNCELLEMESİ: enable_demo_trading

# LIVE Binance CCXT Bağlantısı
LIVE_API_KEY = os.environ.get('LIVE_API_KEY', '').strip()
LIVE_SECRET = os.environ.get('LIVE_SECRET_KEY', '').strip()
borsa_live_config = {
    'apiKey': LIVE_API_KEY,
    'secret': LIVE_SECRET,
    'enableRateLimit': True,
    'urls': {
        'api': {
            'public': 'https://api3.binance.com/api/v3',
            'private': 'https://api3.binance.com/api/v3',
        },
        'fapi': {
            'public': 'https://fapi.binance.com/fapi/v1',
            'private': 'https://fapi.binance.com/fapi/v1',
        }
    },
    'options': {
        'defaultType': 'future',
        'adjustForTimeDifference': True,
        'recvWindow': 60000,
    }
}
borsa_live = ccxt.binanceusdm(borsa_live_config)

# Piyasa Tarayıcı (Scout) için AYRI bir public CCXT instance (FUTURES - Ticker için)
scout_borsa = ccxt.binanceusdm({
    'enableRateLimit': True, 
    'urls': {
        'api': {'public': 'https://api3.binance.com/api/v3', 'private': 'https://api3.binance.com/api/v3'},
        'fapi': {'public': 'https://fapi.binance.com/fapi/v1', 'private': 'https://fapi.binance.com/fapi/v1'}
    },
    'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}
})

# Zaman Senkronizasyonunu başlar başlamaz KESİN olarak zorla
try:
    borsa.load_time_difference()
    scout_borsa.load_time_difference()
    if LIVE_MOD_AKTIF and LIVE_API_KEY: borsa_live.load_time_difference()
except Exception as e:
    print(f"⚠️ [Zaman Senkronizasyonu] CCXT load_time_difference hatası: {e}")

# Spot API (Veri Çekme ve Analiz Motoru için)
spot_borsa = ccxt.binance({'enableRateLimit': False, 'options': {'adjustForTimeDifference': True, 'recvWindow': 60000}})

# UI Paneli için AYRI CCXT instance (Hız ve Çakışma Önleme)
ui_borsa = ccxt.binanceusdm({
    'enableRateLimit': False, 
    'urls': {
        'api': {'public': 'https://api3.binance.com/api/v3', 'private': 'https://api3.binance.com/api/v3'},
        'fapi': {'public': 'https://fapi.binance.com/fapi/v1', 'private': 'https://fapi.binance.com/fapi/v1'}
    },
    'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}
})

# ============================================================
# CCXT Kendi Dinamik Time Difference Senkronizasyonunu Kullanır
# Manuel müdahaleler (TimeDifference'a dışarıdan veri yazma)
# CCXT'nin adjustForTimeDifference özelliğini bozduğu için kaldırıldı.
# ============================================================
try:
    spot_borsa.load_markets()
    SPOT_SEMBOLLER = set(spot_borsa.symbols)
    print(f"[SİSTEM] Spot piyasada {len(SPOT_SEMBOLLER)} sembol mevcut.")
except:
    SPOT_SEMBOLLER = set()
    print("[SİSTEM] Spot semboller yüklenemedi, filtre devre dışı.")

# Testnet'te mevcut olan sembolleri yükle (Scout filtresi için)
try:
    borsa.load_markets()
    TESTNET_SEMBOLLER = set(borsa.symbols)
    print(f"[SİSTEM] Testnet'te {len(TESTNET_SEMBOLLER)} sembol mevcut.")
except:
    TESTNET_SEMBOLLER = set()
    print("[SİSTEM] Testnet sembolleri yüklenemedi, filtre devre dışı.")

# --- Performans Karnesi (Win/Loss Tracker) ---
performans = {'kazanc': 0, 'kayip': 0}
CANLI_DEVRE_KESICI_AKTIF = False
LIVE_ARDISIK_ZARAR = 0
DEMO_ARDISIK_ZARAR = 0          # Demo ardisik zarar sayaci
DEMO_ARDISIK_KAR = 0
SON_ISLEMLER_PNL_LIVE = []
SON_ISLEMLER_PNL_DEMO = []       # Demo kayan pencere PNL takibi
GUN_BASLANGIC_BAKIYESI = None
SON_RESET_TARIHI = datetime.now().date()
SON_RAPOR_ZAMANI_10 = None
SON_RAPOR_ZAMANI_22 = None
LIVE_ISLEM_KILIDI = threading.RLock() # Race Condition kilidi
PING_MODU = False               # Test bitti, tüm paritelerde ava çıkıyoruz. (KAPALI)


# --- DİNAMİK KARANTİNA SİSTEMİ ---
KARANTINA_LISTESI = {}   # {sembol: karantina_bitis_datetime}
COIN_ZARAR_SAYACI = {}   # {sembol: ardisik_zarar_sayisi}
KARA_LISTE = {'ILV/USDT', 'ILVUSDT', 'NOM/USDT', 'NOMUSDT'}  # Kalıcı yasaklı pariteler
try:
    _sg_yuklu = sembol_guard_yukle(KARANTINA_LISTESI, COIN_ZARAR_SAYACI)
    _sg_cezalar = resmi_zarar_karantinasi_tazele(
        {'KARANTINA_LISTESI': KARANTINA_LISTESI, 'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI},
        zorla=True,
    )
    if _sg_yuklu or _sg_cezalar:
        print(f"[SYMBOL GUARD] aktif karantina: {sorted(KARANTINA_LISTESI.keys())}")
except Exception as _sg_hata:
    print(f"[SYMBOL GUARD] baslangic taramasi atlandi: {_sg_hata}")

# --- TESTNET CACHE SİSTEMİ (API yükünü azalt) ---
_DEMO_CACHE = {
    'bakiye': 0.0,
    'pozisyonlar': [],
    'son_guncelleme': 0,
    'bakiye_son_guncelleme': 0,
    'bakiye_ozeti': {},
    'muhasebe_ozeti': {},
}
ORDER_SYNC_STATE = {
    'ready': False,
    'last_run_ts': 0.0,
    'last_error': 'ilk pozisyon/emir senkronizasyonu bekleniyor',
}
_DEMO_CACHE_SURESI = 20  # 20 Saniye (Gerçek zamanlıya yakın, hata olursa önceki değeri gösterir)

SANAL_KRIPTO_KASA = 1000.0
KASA_DURUM = {'LIVE_KASA': 0.0, 'DEMO_KASA': 0.0, 'LIVE_EQUITY': 0.0, 'DEMO_EQUITY': 0.0}

# --- BAŞLANGIÇ SERMAYESİ (Binance ile birebir P&L eşleşmesi için) ---
# Bu değer, hesabına yatırdığın toplam USDT miktarıdır.
# Gerçek Net K/Z = Mevcut Toplam Varlık - BASLANGIC_SERMAYE
# Böylece komisyonlar, funding rate ve kapanmış işlemler otomatik dahil olur.
BASLANGIC_SERMAYE_LIVE = 27.0   # LIVE hesaba yatırılan toplam USDT
BASLANGIC_SERMAYE_DEMO = 0.0    # Demo başlangıç (ilk senkronizasyonda güncellenir)
DEMO_MUHASEBE_BASLANGIC = {
    "baslangic_ms": int(time.time() * 1000),
    "baslangic_zamani": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "baslangic_wallet": 0.0,
    "baslangic_equity": 0.0,
    "baslangic_acik_pnl": 0.0,
    "baslangic_acik_pozisyon": 0,
}

# --- DEMO BAKİYE SENKRONİZASYONU (Açılış - Gerçek bakiyeyi oku) ---
if TESTNET_API_KEY and TESTNET_SECRET:
    _sync_basarili = False
    _max_deneme = 10  # 10 deneme (toplam ~50 saniye)
    for _deneme in range(_max_deneme):
        try:
            _sync_bal = borsa.fetch_balance({'type': 'future'})
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
                _DEMO_CACHE['son_guncelleme'] = time.time()
                print(f"🔗 [SYNC] Demo kasa Binance Wallet Balance ile senkronize edildi: ${_testnet_bakiye:.2f}")
            else:
                # Bakiye gerçekten 0 olabilir (tüm para pozisyonlarda)
                # Yine de API'den gelen 0'ı kabul et, sanal kasaya DÜŞMEYİZ
                KASA_DURUM['DEMO_KASA'] = 0.0
                KASA_DURUM['DEMO_EQUITY'] = 0.0
                _DEMO_CACHE['bakiye'] = 0.0
                _DEMO_CACHE['son_guncelleme'] = time.time()
                print(f"⚠️ [SYNC] Demo bakiye $0 (tüm para pozisyonlarda olabilir)")
            _sync_basarili = True
            break
        except Exception as e:
            print(f"⏳ [SYNC] Demo bağlantısı deneniyor... ({_deneme+1}/{_max_deneme}) Hata: {e}")
            time.sleep(5)
    if not _sync_basarili:
        print(f"🛡️ [SYNC] API {_max_deneme} denemede ulaşılamadı — Sanal Kasa devrede: ${SANAL_KRIPTO_KASA:.2f}")
        KASA_DURUM['DEMO_KASA'] = SANAL_KRIPTO_KASA
        KASA_DURUM['DEMO_EQUITY'] = SANAL_KRIPTO_KASA
        _DEMO_CACHE['bakiye'] = SANAL_KRIPTO_KASA

try:
    DEMO_MUHASEBE_BASLANGIC = demo_muhasebe_baslat(borsa)
    _baslangic_wallet = float(DEMO_MUHASEBE_BASLANGIC.get("baslangic_wallet", 0.0) or 0.0)
    _baslangic_equity = float(DEMO_MUHASEBE_BASLANGIC.get("baslangic_equity", 0.0) or 0.0)
    if _baslangic_wallet > 0:
        BASLANGIC_SERMAYE_DEMO = _baslangic_wallet
        KASA_DURUM['DEMO_KASA'] = _baslangic_wallet
        KASA_DURUM['DEMO_EQUITY'] = _baslangic_equity or _baslangic_wallet
        _DEMO_CACHE['bakiye'] = _baslangic_wallet
        _DEMO_CACHE['bakiye_ozeti'] = {
            "wallet": _baslangic_wallet,
            "equity": _baslangic_equity or _baslangic_wallet,
        }
        _DEMO_CACHE['bakiye_son_guncelleme'] = time.time()
    print(
        "[MUHASEBE] Demo baslangic cizgisi: "
        f"wallet=${_baslangic_wallet:.2f}, "
        f"acikPnL=${float(DEMO_MUHASEBE_BASLANGIC.get('baslangic_acik_pnl', 0.0) or 0.0):+.2f}"
    )
    status_yaz({
        "demo_muhasebe": {
            "kaynak": "binance_income",
            "baslangic": DEMO_MUHASEBE_BASLANGIC,
        }
    })
except Exception as e:
    print(f"[MUHASEBE] Demo baslangic cizgisi alinamadi: {e}")

COOLDOWN_DICT = {} # {sembol: kapanis_datetime} - Tekrar girişi engellemek için
onceki_pozisyonlar = {}  # {sembol: pnl} - Trailing Stop ve kapanış takibi

# Aktif islem detaylari db_logger.py'den yuklenir
aktif_islemler_detay = _detay_yukle()



def borsa_baglantisini_yenile(hata_mesaji="Bilinmiyor", ctx=None):
    global borsa, scout_borsa
    try:
        zaman = datetime.now().strftime('%H:%M:%S')
        print(f"[{zaman}] 🔄 CCXT Bağlantısı Yenileniyor... (Hata: {hata_mesaji})")
        borsa = ccxt.binanceusdm(borsa_config)
        borsa.enable_demo_trading(True)
        # load_markets() burada kaldırıldı, surekli_tarama içinde otonom yapılacak
        scout_borsa = ccxt.binanceusdm({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})
        
        if ctx is not None:
            ctx['borsa'] = borsa
            ctx['scout_borsa'] = scout_borsa

        
        # Donanım saati bypass'ı (Yenileme için)
        try:
            borsa.load_time_difference()
            scout_borsa.load_time_difference()
            if LIVE_MOD_AKTIF and LIVE_API_KEY: borsa_live.load_time_difference()
        except: pass
    except Exception as e:
        print(f"[!] Borsa bağlantısı yenilenemedi: {e}")



# Risk yönetim fonksiyonları risk_manager.py içerisine taşındı.

if __name__ == "__main__":
    if TEK_DONGU_TANI_MODU:
        print("\n🧪 [TANI MODU] Tek döngü sinyal tanısı başlıyor. Emir gönderilmeyecek, model temizliği yapılmayacak.")
    else:
        if MODEL_YENIDEN_EGITIM_ZORLA:
            print("\n[SİSTEM BAKIMI] Zorunlu model yenilemesi istendi.")
            eski_modeller = glob.glob("beyin_*.pkl") + glob.glob("shadow_*.pkl")
            silinen_sayisi = 0
            for dosya in eski_modeller:
                try:
                    os.remove(dosya)
                    silinen_sayisi += 1
                except OSError:
                    pass
            print(f"[SİSTEM BAKIMI] {silinen_sayisi} model silindi; yeniden eğitim kademeli yapılacak.")
        else:
            print("\n[SİSTEM BAKIMI] Modeller korunuyor; yalnızca eski şemalı veya bayat modeller yenilenecek.")

        try:
            import subprocess
            print("\n📊 [AÇILIŞ OTOMASYONU] Sistem Raporları (Müfettiş ve LLM) arka planda hazırlanıyor...")
            subprocess.Popen([sys.executable, "mufettis.py"])
        except:
            pass

    print(f"\n🚀 SİSTEM BAŞLATILIYOR (Savaş Modu: V3 - Tam Otonom)")
    print(f"🔸 DEMO Analiz: AKTİF | Emir: {'AKTİF' if DEMO_EMIR_AKTIF else 'GÖLGE/KAPALI'}")
    print(f"🔸 DEMO Profil: {DEMO_CALISMA_PROFILI}")
    print(f"🔸 LIVE Bot: {'AKTİF' if LIVE_MOD_AKTIF else 'KAPALI (Sadece DEMO modu)'}")
    status_yaz({
        "faz": "BAŞLANGIÇ",
        "bot_durumu": "sistem başlatılıyor",
        "live_mod": LIVE_MOD_AKTIF,
        "live_tetik": ALIM_SATIM_TETIGI_ACIK,
        "ping_modu": PING_MODU,
        "demo_profil": DEMO_CALISMA_PROFILI,
        "demo_live_shadow": DEMO_LIVE_SHADOW_AKTIF,
        "demo_emir_aktif": DEMO_EMIR_AKTIF,
        "short_islem_aktif": SHORT_ISLEM_AKTIF,
        "tek_dongu_tani_modu": TEK_DONGU_TANI_MODU,
    }, event={"tip": "boot", "mesaj": "bot başlatıldı"})
    
    # --- BAŞLANGIÇ CANLI (LIVE) API DR-RUN (BAĞLANTI DOĞRULAMA) ---
    if LIVE_MOD_AKTIF and LIVE_API_KEY and hasattr(borsa_live, 'apiKey') and borsa_live.apiKey:
        print("\n⚙️ [API DRY-RUN] LIVE Cüzdan bağlantısı test ediliyor...")
        try:
            bakiye_bilgisi = borsa_live.fetch_balance({'type': 'future'})
            canli_bakiye = float(bakiye_bilgisi.get('USDT', {}).get('total', 0.0))
            KASA_DURUM['LIVE_KASA'] = canli_bakiye
            print(f"   ✅ CANLI BAKİYE: {canli_bakiye:.2f} USDT - API BAĞLANTISI BAŞARILI!")
            status_yaz({"live_kasa": round(canli_bakiye, 2), "bot_durumu": "LIVE bağlantı doğrulandı"})
            time.sleep(5)
        except Exception as e:
            hata_mesaji = str(e)
            print(f"   ❌ LIVE CÜZDAN BAĞLANTI HATASI: {hata_mesaji}\n")
            print("      Lütfen API yetkilerinizi, IP izinlerini ve Vadeli işlemler aktivasyonunu kontrol ediniz.")
            status_yaz({
                "bot_durumu": "LIVE bağlantı hatası",
                "son_hata": {
                    "modul": "live_api_dry_run",
                    "mesaj": hata_mesaji,
                    "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            }, event={"tip": "hata", "mesaj": f"LIVE bağlantı: {hata_mesaji}"})
            time.sleep(5)
    # ----------------------------------------
    
    if TEK_DONGU_TANI_MODU:
        try:
            ctx_scanner = {
                'SON_RAPOR_ZAMANI_10': SON_RAPOR_ZAMANI_10, 'SON_RAPOR_ZAMANI_22': SON_RAPOR_ZAMANI_22,
                'performans': performans, 'KASA_DURUM': KASA_DURUM, '_DEMO_CACHE': _DEMO_CACHE,
                'KARANTINA_LISTESI': KARANTINA_LISTESI, 'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF, 'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI, 'KARA_LISTE': KARA_LISTE, 'borsa_baglantisini_yenile': borsa_baglantisini_yenile, 'LIVE_MOD_AKTIF': LIVE_MOD_AKTIF,
                'ALIM_SATIM_TETIGI_ACIK': ALIM_SATIM_TETIGI_ACIK, 'PING_MODU': PING_MODU,
                'scout_borsa': scout_borsa, 'borsa_live': borsa_live, 'borsa': borsa,
                'aktif_islemler_detay': aktif_islemler_detay, 'COOLDOWN_DICT': COOLDOWN_DICT,
                'onceki_pozisyonlar': onceki_pozisyonlar,
                'ORDER_SYNC_STATE': ORDER_SYNC_STATE,
                'LIVE_ARDISIK_ZARAR': LIVE_ARDISIK_ZARAR, 'DEMO_ARDISIK_ZARAR': DEMO_ARDISIK_ZARAR,
                'SON_ISLEMLER_PNL_DEMO': SON_ISLEMLER_PNL_DEMO, 'SON_ISLEMLER_PNL_LIVE': SON_ISLEMLER_PNL_LIVE,
                'LIVE_ISLEM_KILIDI': LIVE_ISLEM_KILIDI, 'LIVE_API_KEY': LIVE_API_KEY, 'LIVE_SECRET': LIVE_SECRET,
                'SPOT_SEMBOLLER': SPOT_SEMBOLLER, 'TESTNET_SEMBOLLER': TESTNET_SEMBOLLER
            }
            surekli_tarama_ve_analiz(ctx_scanner)
            # Update primitives back to main scope (e.g. SON_RAPOR_ZAMANI) if they were changed
            SON_RAPOR_ZAMANI_10 = ctx_scanner['SON_RAPOR_ZAMANI_10']
            SON_RAPOR_ZAMANI_22 = ctx_scanner['SON_RAPOR_ZAMANI_22']
        except KeyboardInterrupt:
            print("\n🛑 Tanı modu manuel olarak durduruldu.")
        sys.exit(0)

    if BOOTCAMP_AKTIF:
        print(f"\n🎮 [BOOTCAMP] Yüksek hacimli 100 aktif (TRADING) coin için Ön-Eğitim başlatılıyor...")
        try:
            # Piyasaları yüklemek için 2 deneme (Rate limit koruması)
            try: scout_borsa.load_markets()
            except:
                time.sleep(2)
                scout_borsa.load_markets()

            tik_boot = scout_borsa.fetch_tickers()
            adaylar_boot = []
            for sembol, veri in tik_boot.items():
                if '/USDT' not in sembol: continue

                # --- Proaktif Radar Filtresi (Statü Kontrolü) ---
                if sembol in scout_borsa.markets:
                    m_info = scout_borsa.markets[sembol]
                    if m_info['info'].get('status') != 'TRADING':
                        continue # SXP, STRAX gibi ölü tahtaları ayıkla

                hacim = float(veri.get('quoteVolume') or 0)
                if hacim > 15_000_000: # 100 coine esnetmek icin baraj düştü
                    tsym = sembol.replace(':USDT', '')
                    if SPOT_SEMBOLLER and tsym not in SPOT_SEMBOLLER: continue
                    adaylar_boot.append((tsym, hacim))

            adaylar_boot.sort(key=lambda x: x[1], reverse=True)
            hedef_100 = [x[0] for x in adaylar_boot[:100]]
            b_motor = BeyinMotoru()

            print(f"✅ Filtre Tamamlandı: {len(hedef_100)} adet aktif tahta eğitime alınıyor.")
            for cc in hedef_100:
                try:
                    if b_motor.model_bayat_mi(cc, is_crypto=True):
                        df_b = veri_getir_dortlu(cc, REF)
                        if df_b is not None and not df_b.empty:
                            b_motor.model_egit(cc, df_b, is_crypto=True)
                    time.sleep(0.1)
                except Exception:
                    pass
            print("✅ [BOOTCAMP] Model ön eğitimi tamamlandı!")
        except Exception as e:
            print(f"⚠️ Bootcamp atlandı: {e}")
    else:
        print("\n[BOOTCAMP] Kapalı; modeller tarama sırasında ihtiyaç oldukça yenilenecek.")
        
    ctx_tracker = {
        'ALIM_SATIM_TETIGI_ACIK': ALIM_SATIM_TETIGI_ACIK,
        'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF, 'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI, 'KARA_LISTE': KARA_LISTE, 'borsa_baglantisini_yenile': borsa_baglantisini_yenile,
        'LIVE_ARDISIK_ZARAR': LIVE_ARDISIK_ZARAR,
        'DEMO_ARDISIK_ZARAR': DEMO_ARDISIK_ZARAR,
        'DEMO_ARDISIK_KAR': DEMO_ARDISIK_KAR,
        'SON_ISLEMLER_PNL_LIVE': SON_ISLEMLER_PNL_LIVE,
        'SON_ISLEMLER_PNL_DEMO': SON_ISLEMLER_PNL_DEMO,
        'GUN_BASLANGIC_BAKIYESI': GUN_BASLANGIC_BAKIYESI,
        'SON_RESET_TARIHI': SON_RESET_TARIHI,
        '_DEMO_CACHE': _DEMO_CACHE,
        '_DEMO_CACHE_SURESI': _DEMO_CACHE_SURESI,
        'aktif_islemler_detay': aktif_islemler_detay,
        'LIVE_MOD_AKTIF': LIVE_MOD_AKTIF,
        'borsa_live': borsa_live,
        'borsa': borsa,
        'BASLANGIC_SERMAYE_DEMO': BASLANGIC_SERMAYE_DEMO,
        'BASLANGIC_SERMAYE_LIVE': BASLANGIC_SERMAYE_LIVE,
        'MUHASEBE_BASLANGIC_MS': DEMO_MUHASEBE_BASLANGIC.get("baslangic_ms", int(time.time() * 1000)),
        'MUHASEBE_BASLANGIC_ACIK_PNL_DEMO': DEMO_MUHASEBE_BASLANGIC.get("baslangic_acik_pnl", 0.0),
        'DEMO_MUHASEBE_BASLANGIC': DEMO_MUHASEBE_BASLANGIC,
        'onceki_pozisyonlar': onceki_pozisyonlar,
        'ORDER_SYNC_STATE': ORDER_SYNC_STATE,
        'performans': performans,
        'KASA_DURUM': KASA_DURUM,
        'KARANTINA_LISTESI': KARANTINA_LISTESI,
        'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI,
        'KARA_LISTE': KARA_LISTE,
        'COOLDOWN_DICT': COOLDOWN_DICT
    }
    t_panel = threading.Thread(target=pozisyon_takip_paneli, args=(ctx_tracker,), daemon=True)
    t_panel.start()
    
    # --- Ölümsüzlük Döngüsü (Continuous Execution Engine) ---
    import sys
    while True:
        try:
            ctx_scanner = {
                'SON_RAPOR_ZAMANI_10': SON_RAPOR_ZAMANI_10, 'SON_RAPOR_ZAMANI_22': SON_RAPOR_ZAMANI_22,
                'performans': performans, 'KASA_DURUM': KASA_DURUM, '_DEMO_CACHE': _DEMO_CACHE,
                'KARANTINA_LISTESI': KARANTINA_LISTESI, 'CANLI_DEVRE_KESICI_AKTIF': CANLI_DEVRE_KESICI_AKTIF, 'COIN_ZARAR_SAYACI': COIN_ZARAR_SAYACI, 'KARA_LISTE': KARA_LISTE, 'borsa_baglantisini_yenile': borsa_baglantisini_yenile, 'LIVE_MOD_AKTIF': LIVE_MOD_AKTIF,
                'ALIM_SATIM_TETIGI_ACIK': ALIM_SATIM_TETIGI_ACIK, 'PING_MODU': PING_MODU,
                'scout_borsa': scout_borsa, 'borsa_live': borsa_live, 'borsa': borsa,
                'aktif_islemler_detay': aktif_islemler_detay, 'COOLDOWN_DICT': COOLDOWN_DICT,
                'onceki_pozisyonlar': onceki_pozisyonlar,
                'ORDER_SYNC_STATE': ORDER_SYNC_STATE,
                'LIVE_ARDISIK_ZARAR': LIVE_ARDISIK_ZARAR, 'DEMO_ARDISIK_ZARAR': DEMO_ARDISIK_ZARAR,
                'SON_ISLEMLER_PNL_DEMO': SON_ISLEMLER_PNL_DEMO, 'SON_ISLEMLER_PNL_LIVE': SON_ISLEMLER_PNL_LIVE,
                'LIVE_ISLEM_KILIDI': LIVE_ISLEM_KILIDI, 'LIVE_API_KEY': LIVE_API_KEY, 'LIVE_SECRET': LIVE_SECRET,
                'SPOT_SEMBOLLER': SPOT_SEMBOLLER, 'TESTNET_SEMBOLLER': TESTNET_SEMBOLLER
            }
            surekli_tarama_ve_analiz(ctx_scanner)
            # Update primitives back to main scope (e.g. SON_RAPOR_ZAMANI) if they were changed
            SON_RAPOR_ZAMANI_10 = ctx_scanner['SON_RAPOR_ZAMANI_10']
            SON_RAPOR_ZAMANI_22 = ctx_scanner['SON_RAPOR_ZAMANI_22']
        except KeyboardInterrupt:
            print("\n🛑 Sistem manuel olarak durduruldu.")
            sys.exit(0)
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            hata_mesaji = f"🔥 [{zaman}] [KRİTİK HATA] Ana Motor Şiddetli Hata Aldı:\n{str(e)}\n\n⏳ 10 Saniye sonra sistem otonom olarak yeniden başlatılacak."
            print(f"\n{hata_mesaji}")
            try: telegrama_gonder(hata_mesaji)
            except: pass
            time.sleep(10)
