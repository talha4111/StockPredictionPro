if __name__ == "__main__":
    import os as _os
    import runpy as _runpy
    import sys as _sys

    _BOT_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "QuantBot")
    _BOT_MAIN = _os.path.join(_BOT_DIR, "main.py")
    if not _os.path.exists(_BOT_MAIN):
        raise FileNotFoundError(f"Kanonik bot girisi bulunamadi: {_BOT_MAIN}")

    if _BOT_DIR not in _sys.path:
        _sys.path.insert(0, _BOT_DIR)
    _os.chdir(_BOT_DIR)
    _runpy.run_path(_BOT_MAIN, run_name="__main__")
    raise SystemExit

import sys
import os
# Windows cp1254 Türkçe encoding emoji çökmelerini önle
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
from ai_core import BeyinMotoru

from tarayici import veri_getir_dortlu
from analist import korku_acgozluluk_getir, onchain_inflow_durumu, makro_volatilite_beklentisi
import json
import requests
import time
import threading 
from datetime import datetime
import joblib
import csv
import sqlite3
import websocket
import glob

# --- .env Dosyasını Otomatik Yükle (LIVE_API_KEY vb. için) ---
try:
    from dotenv import load_dotenv
    load_dotenv(override=False)  # Zaten set edilmiş env var'ları ezme
except ImportError:
    # dotenv kurulu değilse manuel oku
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as _ef:
            for _line in _ef:
                _line = _line.strip()
                if '=' in _line and not _line.startswith('#'):
                    _k, _v = _line.split('=', 1)
                    if _k.strip() not in os.environ:
                        os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

# --- WSS (WebSocket) VERİ NEHRİ ---
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

if os.path.exists('.env'):
    with open('.env') as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                k, v = line.strip().split('=', 1)
                os.environ[k.strip()] = v.strip()

try:
    with open('ayar.json', 'r', encoding='utf-8') as f: AYAR = json.load(f)
    PORTFOY = AYAR["portfoy"]
    REF = AYAR["referans_varlik"]
    RISK_AYAR = AYAR["risk_yonetimi"]
    TELEGRAM_AYAR = AYAR["telegram"]
    
    # CCXT Testnet Ayarları
    TESTNET_API_KEY = AYAR.get("testnet_api_key", "").strip()
    TESTNET_SECRET = AYAR.get("testnet_secret", "").strip()
    ISLEM_MIKTARI_USDT = AYAR.get("islem_miktari_usdt", 50)
    SL_YUZDE = AYAR.get("sl_yuzde", 0.01)
    TP_YUZDE = AYAR.get("tp_yuzde", 0.02)
except Exception as e: 
    print(f"⚠️ [KRİTİK UYARI] ayar.json okunamadı veya bozuk! Bot varsayılan ayarlar ile zorla başlatılıyor... Hata: {e}")
    PORTFOY = []
    REF = "BTC/USDT"
    RISK_AYAR = {"tp_atr_carpani": 2.0}
    TELEGRAM_AYAR = {"aktif_mi": False}
    TESTNET_API_KEY = ""
    TESTNET_SECRET = ""
    ISLEM_MIKTARI_USDT = 11.5
    SL_YUZDE = 0.01
    TP_YUZDE = 0.02

# Kaptan, bu liste senin yeni ordun ve sektörleri:
SEKTORLER = {
    'BTC/USDT': 'Piyasa Lideri', 'BTCUSDT': 'Piyasa Lideri',
    'ETH/USDT': 'Katman-1', 'ETHUSDT': 'Katman-1',
    'SOL/USDT': 'Katman-1', 'SOLUSDT': 'Katman-1',
    'BNB/USDT': 'Borsa/L1', 'BNBUSDT': 'Borsa/L1',
    'AVAX/USDT': 'Katman-1', 'AVAXUSDT': 'Katman-1',
    'LINK/USDT': 'Oracle', 'LINKUSDT': 'Oracle',
    'DOT/USDT': 'Interoperability', 'DOTUSDT': 'Interoperability',
    'ADA/USDT': 'Katman-1', 'ADAUSDT': 'Katman-1',
    'LTC/USDT': 'Ödeme', 'LTCUSDT': 'Ödeme',
    'XRP/USDT': 'Ödeme', 'XRPUSDT': 'Ödeme'
}

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
borsa = ccxt.binance(borsa_config)
borsa.set_sandbox_mode(True) # Orijinal CCXT Sandbox metodu

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
import requests
import time
max_sync_deneme = 5
for i in range(max_sync_deneme):
    try:
        # Global fapi yerine api3.binance.com kullanarak engelleri asmaya calisiyoruz
        res = requests.get("https://api3.binance.com/api/v3/time", timeout=5).json()
        server_msec = res['serverTime']
        local_msec = int(time.time() * 1000)
        diff = server_msec - local_msec
        
        # CCXT dahili mekanizmasini ve manuel diff'i ayarla
        borsa.options['timeDifference'] = diff
        if LIVE_API_KEY: borsa_live.options['timeDifference'] = diff
        scout_borsa.options['timeDifference'] = diff
        ui_borsa.options['timeDifference'] = diff
        
        # Manuel senkronizasyon basarili
        break
    except Exception as e:
        time.sleep(2)

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

ALIM_SATIM_TETIGI_ACIK = False  # Legacy kopyada da varsayilan guvenli mod: LIVE tetik kapali.
CANLI_DEVRE_KESICI_AKTIF = False
LIVE_ARDISIK_ZARAR = 0
DEMO_ARDISIK_KAR = 0
SON_ISLEMLER_PNL_LIVE = []
GUN_BASLANGIC_BAKIYESI = None
SON_RESET_TARIHI = datetime.now().date()
LIVE_ISLEM_KILIDI = threading.Lock() # Race Condition kilidi
PING_MODU = False               # Test bitti, tüm paritelerde ava çıkıyoruz. (KAPALI)

# --- DİNAMİK KARANTİNA SİSTEMİ ---
KARANTINA_LISTESI = {}   # {sembol: karantina_bitis_datetime}
COIN_ZARAR_SAYACI = {}   # {sembol: ardisik_zarar_sayisi}
KARA_LISTE = {'ILV/USDT', 'ILVUSDT'}  # Kalıcı yasaklı pariteler

# --- TESTNET CACHE SİSTEMİ (API yükünü azalt) ---
_DEMO_CACHE = {'bakiye': 0.0, 'pozisyonlar': [], 'son_guncelleme': 0}
_DEMO_CACHE_SURESI = 20  # 20 Saniye (Gerçek zamanlıya yakın, hata olursa önceki değeri gösterir)

KASA_DURUM = {'LIVE_KASA': 0.0, 'DEMO_KASA': 0.0}

# --- BAŞLANGIÇ SERMAYESİ (Binance ile birebir P&L eşleşmesi için) ---
# Bu değer, hesabına yatırdığın toplam USDT miktarıdır.
# Gerçek Net K/Z = Mevcut Toplam Varlık - BASLANGIC_SERMAYE
# Böylece komisyonlar, funding rate ve kapanmış işlemler otomatik dahil olur.
BASLANGIC_SERMAYE_LIVE = 27.0   # LIVE hesaba yatırılan toplam USDT
BASLANGIC_SERMAYE_DEMO = 0.0    # Demo başlangıç (ilk senkronizasyonda güncellenir)

# --- TESTNET BAKİYE SENKRONİZASYONU (Açılış) ---
if TESTNET_API_KEY and TESTNET_SECRET:
    for _deneme in range(3):
        try:
            _sync_bal = borsa.fetch_balance()
            _testnet_bakiye = float(_sync_bal.get('USDT', {}).get('total', 0))
            if _testnet_bakiye > 0:
                KASA_DURUM['DEMO_KASA'] = _testnet_bakiye
                _DEMO_CACHE['bakiye'] = _testnet_bakiye
                _DEMO_CACHE['son_guncelleme'] = time.time()
                print(f"🔗 [SYNC] Demo kasa Binance Testnet ile senkronize edildi: ${_testnet_bakiye:.2f}")
                break
        except Exception as e:
            if _deneme < 2:
                print(f"⏳ [SYNC] Testnet bağlantısı deneniyor... ({_deneme+1}/3) Hata: {e}")
                time.sleep(5)
            else:
                print(f"⚠️ [SYNC] Testnet 3 denemede başarısız ({e})")

COOLDOWN_DICT = {} # {sembol: kapanis_datetime} - Tekrar girişi engellemek için
onceki_pozisyonlar = {}  # {sembol: pnl} - Trailing Stop ve kapanış takibi
aktif_islemler_detay = {}

csv_dosya_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_history.csv')
if not os.path.exists(csv_dosya_yolu):
    try:
        with open(csv_dosya_yolu, mode='w', newline='', encoding='utf-8') as f:
            import csv
            writer = csv.writer(f)
            writer.writerow(['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT', 'PNL_Yuzde', 'AI_Guven_Skoru'])
    except Exception as e:
        print(f"[!] CSV Olusturulamadi: {e}")

def islem_kaydet(sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru):
    tarih_saat = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    csv_dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_history.csv')
    db_dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db')
    uyari = not os.path.exists(csv_dosya)
    
    # CSV Kayıt
    try:
        with open(csv_dosya, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if uyari:
                writer.writerow(['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT', 'PNL_Yuzde', 'AI_Guven_Skoru'])
            writer.writerow([tarih_saat, sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru])
    except: pass
    
    # SQLite Database Kayıt
    try:
        baglanti = sqlite3.connect(db_dosya)
        cursor = baglanti.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS closed_trades (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            Tarih_Saat TEXT, Parite TEXT, Hesap_Tipi TEXT, Islem_Yonu TEXT, Giris_Fiyati REAL,
                            Cikis_Fiyati REAL, Net_PNL_USDT REAL, PNL_Yuzde REAL, AI_Guven_Skoru REAL
                        )''')
        cursor.execute("INSERT INTO closed_trades (Tarih_Saat, Parite, Hesap_Tipi, Islem_Yonu, Giris_Fiyati, Cikis_Fiyati, Net_PNL_USDT, PNL_Yuzde, AI_Guven_Skoru) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (tarih_saat, sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru))
        baglanti.commit()
        baglanti.close()
    except: pass

def borsa_baglantisini_yenile(hata_mesaji="Bilinmiyor"):
    global borsa, scout_borsa
    try:
        zaman = datetime.now().strftime('%H:%M:%S')
        print(f"[{zaman}] 🔄 CCXT Bağlantısı Yenileniyor... (Hata: {hata_mesaji})")
        borsa = ccxt.binanceusdm(borsa_config)
        borsa.set_sandbox_mode(True)
        # load_markets() burada kaldırıldı, surekli_tarama içinde otonom yapılacak
        scout_borsa = ccxt.binanceusdm({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})
        
        # Donanım saati bypass'ı (Yenileme için)
        import requests, time
        try:
            res = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=5).json()
            diff = res['serverTime'] - int(time.time() * 1000)
            borsa.options['timeDifference'] = diff
            scout_borsa.options['timeDifference'] = diff
            if LIVE_API_KEY: borsa_live.options['timeDifference'] = diff
        except: pass
    except Exception as e:
        print(f"[!] Borsa bağlantısı yenilenemedi: {e}")

def telegrama_gonder(mesaj):
    if not TELEGRAM_AYAR["aktif_mi"]: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_AYAR['bot_token']}/sendMessage", 
                      data={"chat_id": TELEGRAM_AYAR['chat_id'], "text": mesaj, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def gunluk_rapor_gonder():
    """Gece 00:00'da otomatik tetiklenen Telegram performans raporu."""
    try:
        toplam_islem = performans['kazanc'] + performans['kayip']
        win_rate = (performans['kazanc'] / toplam_islem * 100) if toplam_islem > 0 else 0
        
        demo_kasa = KASA_DURUM.get('DEMO_KASA', 0.0)
        acik_poz = len([p for p in _DEMO_CACHE.get('pozisyonlar', [])]) if _DEMO_CACHE else 0
        karantina_sayisi = len(KARANTINA_LISTESI)
        
        # SQLite'dan bugünkü işlem detaylarını çek
        bugunun_islemleri = ""
        try:
            conn = sqlite3.connect('trading_bot.db')
            cursor = conn.cursor()
            bugun_str = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT Parite, Islem_Yonu, Net_PNL_USDT, PNL_Yuzde FROM closed_trades WHERE Tarih_Saat LIKE ?", (f"{bugun_str}%",))
            satirlar = cursor.fetchall()
            conn.close()
            if satirlar:
                bugunun_islemleri = "\n*📋 Bugünkü İşlemler:*\n"
                toplam_pnl = 0
                for s in satirlar[-10:]:  # Son 10 işlem
                    pnl_str = f"+{s[2]:.2f}" if s[2] >= 0 else f"{s[2]:.2f}"
                    bugunun_islemleri += f"  `{s[0]}` {s[1]} → {pnl_str}$ (%{s[3]:.1f})\n"
                    toplam_pnl += s[2]
                bugunun_islemleri += f"  *Toplam P&L: {toplam_pnl:+.2f}$*\n"
        except:
            pass
        
        rapor = f"""
🌙 *GECE RAPORU — {datetime.now().strftime('%d.%m.%Y')}*
━━━━━━━━━━━━━━━━━━━
🎮 *DEMO Kasa:* ${demo_kasa:.2f}
📊 *Toplam İşlem:* {toplam_islem}
✅ *Kazanç:* {performans['kazanc']} | ❌ *Kayıp:* {performans['kayip']}
🏆 *Win Rate:* %{win_rate:.0f}
📂 *Açık Pozisyon:* {acik_poz}
🚫 *Karantina:* {karantina_sayisi} coin
━━━━━━━━━━━━━━━━━━━{bugunun_islemleri}
⚡ _Savaş Modu V9.2 — Tam Otonom_
"""
        telegrama_gonder(rapor.strip())
        print("📨 [TELEGRAM] Gece raporu başarıyla gönderildi!")
    except Exception as e:
        print(f"⚠️ [TELEGRAM] Rapor gönderilemedi: {e}")

def islem_ac(sinyal):
    global ALIM_SATIM_TETIGI_ACIK, PING_MODU, COOLDOWN_DICT
    
    sembol = sinyal['coin']
    yon = sinyal['yon']
    anlik_fiyat = sinyal['fiyat']
    hesaplanan_tp = sinyal['tp']
    hesaplanan_sl = sinyal['sl']
    ai_guven_skoru = sinyal['guven_skoru']
    live_ok = sinyal.get('live_ok', False)
    demo_ok = sinyal.get('demo_ok', False)
    
    # --- COOLDOWN KONTROLÜ (Akıllı Bekleme Sistemi) ---
    simdi = datetime.now()
    if sembol in COOLDOWN_DICT:
        gecen = (simdi - COOLDOWN_DICT[sembol]).total_seconds()
        # 2+ ardışık zarar sonrası 1 saat bekleme, normal ise 3 dakika
        bekleme_suresi = 3600 if LIVE_ARDISIK_ZARAR >= 2 else 180
        if gecen < bekleme_suresi:
            return
        else:
            del COOLDOWN_DICT[sembol]

    # --- KANAL GÖNDERİMİ (BIFURCATION) ---
    if demo_ok:
        try:
            if hasattr(borsa, 'apiKey') and borsa.apiKey:
                print(f"POZİSYON [DEMO-TESTNET]: {sembol} | YÖN: {'LONG' if 'YÜKSELİŞ' in yon else 'SHORT'} | GİRİŞ: {anlik_fiyat}")
                _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, borsa, "TESTNET", False, sinyal.get('margin_override_demo', 0.04), ai_guven_skoru)
        except Exception as e:
            print(f"[!] TESTNET API Emir Hatası ({sembol}): {e}")

    if live_ok:
        if LIVE_API_KEY and LIVE_SECRET:
            if ALIM_SATIM_TETIGI_ACIK or (PING_MODU and sembol == 'FDUSD/USDT'):
                if not ALIM_SATIM_TETIGI_ACIK and PING_MODU:
                    print(f"[{sembol}] ⚠️ PING MODU ONAYI: Mikro LIVE test işlemine izin veriliyor...")
                try:
                    _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, borsa_live, "LIVE", True, sinyal.get('margin_override_live', 0.1), ai_guven_skoru)
                    print(f"POZİSYON [LIVE-GERÇEK]: {sembol} | YÖN: {'LONG' if 'YÜKSELİŞ' in yon else 'SHORT'} | GİRİŞ: {anlik_fiyat}")
                except Exception as e:
                    hata_mesaji = str(e)
                    if "-2010" in hata_mesaji or "insufficient balance" in hata_mesaji.lower():
                        print(f"[LIVE-UYARI] Bakiye yetersiz, LIVE işlem iptal.")
                    else:
                        print(f"[!] LIVE İzole Hata ({sembol}): {e}")
            else:
               pass # Canlı işlem tetiği kapalı!

def _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, borsa_istemci, hesap_tipi, is_live, margin_override, ai_guven_skoru):
    if not hasattr(borsa_istemci, 'apiKey') or not borsa_istemci.apiKey:
        return

    try:
        with LIVE_ISLEM_KILIDI:
            # Piyasaları yükle (Futures)
            borsa_istemci.load_markets()
            
            # --- 1. Fiziksel Sigorta: Max 1 Canlı İşlem Kontrolü ---
            pozisyonlar = borsa_istemci.fetch_positions()
            acik_sayisi = sum(1 for p in pozisyonlar if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0)
            
            if is_live and acik_sayisi >= 1:
                print(f"⚠️ [LIVE-GÜVENLİK] İptal: LIVE modda aynı anda KESİNLİKLE SADECE 1 İŞLEM açık kalabilir!")
                return
        # ------------------------------
        
        # --- 2. Hard-Coded Bütçe Sigortası ---
        try:
            bakiye_bilgisi = borsa_istemci.fetch_balance()
            toplam_kasa = float(bakiye_bilgisi.get('USDT', {}).get('total', 1000.0))
        except:
            toplam_kasa = 1000.0
            
        if is_live:
            if margin_override is not None:
                kullanilacak_margin = toplam_kasa * margin_override
            else:
                kullanilacak_margin = toplam_kasa * 0.90
                
            kullanilacak_margin = min(kullanilacak_margin, toplam_kasa * 0.90) # Kasanın max %90'ı kullanılabilir
            kaldirac_orani = 5 # 5x Kaldıraç (küçük kasa için optimize)
            risk_metni = f"LIVE Bütçe: {kullanilacak_margin:.2f}$ (Hedef: 5x)"
        else:
            if margin_override is not None:
                margin_yuzdesi = margin_override
                kaldirac_orani = 10 # Demo sabit 10x per request
                risk_metni = f"Özel Kasa ({margin_override*100:.1f}%)"
            elif toplam_kasa > 4000.0:
                margin_yuzdesi = 0.07 # Portföy / Sepet Dağılımı (%7)
                kaldirac_orani = 10   
                risk_metni = "%7 (Sepet Modu)"
            else:
                margin_yuzdesi = 0.07 
                kaldirac_orani = 10    
                risk_metni = "%7 (Sepet Modu)"
            kullanilacak_margin = toplam_kasa * margin_yuzdesi
            
        if sum(SON_ISLEMLER_PNL_LIVE) < 0 and toplam_kasa > 100:
            kullanilacak_margin *= 0.50
            risk_metni += " (⚠️ DEFANSİF MOD: Marjin %50 Düşürüldü)"
            print("\n⚠️ [DEFANSİF MOD] Negatif performans nedeniyle pozisyon büyüklüğü %50 düşürüldü.")
            
        # 1. Kaldıraç Ayarlama (Çökerse sessiz gitmesin, uyaralım)
        try:
            borsa_istemci.set_leverage(kaldirac_orani, sembol)
            kaldirac = kaldirac_orani
        except Exception as e:
            print(f"⚠️ [DİKKAT] Binance API Kaldıraç Ayarını Reddetti! (Hata: {e})")
            print(f"⚠️ Binance mobil uygulamasındaki varsayılan kaldıracınız (Örn: 5x veya 20x) geçerli olacak. Bu yüzden cüzdandan kesilen blokaj tutarı (Marjin) beklediğinizden daha düşük veya yüksek görünebilir!")
            kaldirac = kaldirac_orani # Hesaplama için varsayılanı kullanmaya devam (Notional boyutu sabit tutmak için)

        islem_hacmi = kullanilacak_margin * kaldirac 
        
        miktar_hesap = islem_hacmi / anlik_fiyat
        miktar = float(borsa_istemci.amount_to_precision(sembol, miktar_hesap))
        
        # 3. YZ ve ATR Tabanlı Dinamik TP/SL Kullanımı
        # Artık sabit %5 yerine, modelin belirlediği volatilite (ATR) hedefleri kullanılıyor!
        
        zaman = datetime.now().strftime('%H:%M:%S')
        print(f"[{zaman}] İşlem Büyüklüğü: {kullanilacak_margin:.2f} USDT | Kaldıraç: {kaldirac}x | Risk: {risk_metni}")

        # Market emri gönderimi ve TP/TSL (Ayrı Şartlı Emir) hazırlığı
        
        # %2 Maksimum Kasa Zararı (Hard Stop Limit)
        max_zarar_tutari = toplam_kasa * 0.02
        
        if "YÜKSELİŞ" in yon:
            try:
                emir = borsa_istemci.create_market_buy_order(sembol, miktar)
                gerceklesen_fiyat = emir.get('average') or emir.get('price') or anlik_fiyat
                time.sleep(0.5) # Emir iletim hızını artırmak için 2sn -> 0.5sn düşürüldü
                
                aktif_islemler_detay[f"{sembol}_{hesap_tipi}"] = {'Giris_Fiyati': gerceklesen_fiyat, 'Islem_Yonu': 'LONG', 'Miktar': miktar, 'AI_Guven_Skoru': ai_guven_skoru, 'Hesap_Tipi': hesap_tipi}
                
                tp_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_tp))
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(gerceklesen_fiyat - sl_fiyat)
                
                # --- ÇİFT KALKAN & KISMİ KÂR ALIM (VARYASYON 2) ---
                # 1. Kısmi Kâr Alım (2.5 ATR - Scale Out, %30 pozisyon)
                scale_out_fark = atr_mesafe * 2.5
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat + scale_out_fark))
                yari_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.3))
                
                # 2. Dinamik Trailing Stop Esnekliği (Min 2.5, Max 5.0)
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                callback_rate_hesap = 3.0 / max(0.1, volatilite_yuzde)
                callback_rate = max(2.5, min(5.0, callback_rate_hesap))
                activation_price = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat * 1.005)) # %0.5 Kârda Aktifleş
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                for deneme in range(max_deneme):
                    try:
                        # 🛡️ Kalkan 1: KESİN SABİT STOP (Hard Stop Garantisi)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='STOP_MARKET', side='sell', amount=miktar,
                                params={'stopPrice': sl_fiyat, 'reduceOnly': True}
                            )
                            print(f"✅ [ÇİFT KALKAN] {sembol} | Sabit Stop Aktif: {sl_fiyat}")
                        except Exception as sl_err:
                            if "-4130" not in str(sl_err): print(f"⚠️ [ZIRH UYARISI] Sabit Stop Kurulamadı: {sl_err}")

                        # 🛡️ Kalkan 2: Kısmi Kâr Alım (Scale-Out - 2.0 ATR)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TAKE_PROFIT_MARKET', side='sell', amount=yari_miktar,
                                params={'stopPrice': scale_out_fiyat, 'reduceOnly': True}
                            )
                            print(f"💰 [SCALE-OUT] {sembol} | %50 Kâr Alım Aktif: {scale_out_fiyat}")
                        except Exception as tp_err:
                            if "-4130" not in str(tp_err): print(f"⚠️ [ZIRH UYARISI] Scale-Out Kurulamadı: {tp_err}")

                        # 🛡️ Kalkan 3: Trailing Stop (Geri Kalanlar İçin Kâr Takibi)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TRAILING_STOP_MARKET', side='sell', amount=miktar,
                                params={'callbackRate': callback_rate, 'activationPrice': activation_price, 'reduceOnly': True}
                            )
                            print(f"🎯 [SUNUCU GÜVENLİĞİ] {sembol} | Trailing Stop Aktif: %{callback_rate:.2f} | Aktivasyon: {activation_price}")
                        except Exception as tsl_error:
                            if "-4130" not in str(tsl_error): print(f"⚠️ [ZIRH UYARISI] Trailing Stop başarısız: {tsl_error}")

                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: LONG | GİRİŞ: {gerceklesen_fiyat} | ZIRH: SABİT STOP ONAYLI")
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Ana Zırh Çöktü: {hata_msg}")
                            break
            except Exception as e:
                print(f"[{zaman}] İŞLEM/ZIRH BAŞARISIZ ({sembol}): {e}")
                
        elif "DÜŞÜŞ" in yon:
            try:
                emir = borsa_istemci.create_market_sell_order(sembol, miktar)
                gerceklesen_fiyat = emir.get('average') or emir.get('price') or anlik_fiyat
                time.sleep(0.5) 
                
                aktif_islemler_detay[f"{sembol}_{hesap_tipi}"] = {'Giris_Fiyati': gerceklesen_fiyat, 'Islem_Yonu': 'SHORT', 'Miktar': miktar, 'AI_Guven_Skoru': ai_guven_skoru, 'Hesap_Tipi': hesap_tipi} 
                
                tp_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_tp))
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(gerceklesen_fiyat - sl_fiyat)
                
                # --- ÇİFT KALKAN & KISMİ KÂR ALIM (VARYASYON 2) ---
                # 1. Kısmi Kâr Alım (2.5 ATR - Scale Out, %30 pozisyon)
                scale_out_fark = atr_mesafe * 2.5
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat - scale_out_fark))
                yari_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.3))
                
                # 2. Dinamik Trailing Stop Esnekliği (Min 2.5, Max 5.0)
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                callback_rate_hesap = 3.0 / max(0.1, volatilite_yuzde)
                callback_rate = max(2.5, min(5.0, callback_rate_hesap))
                activation_price = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat * 0.995)) # %0.5 Kârda Aktifleş (Short için Aşağı)
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                for deneme in range(max_deneme):
                    try:
                        # 🛡️ Kalkan 1: KESİN SABİT STOP (Hard Stop Garantisi)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='STOP_MARKET', side='buy', amount=miktar,
                                params={'stopPrice': sl_fiyat, 'reduceOnly': True}
                            )
                            print(f"✅ [ÇİFT KALKAN] {sembol} | Sabit Stop Aktif: {sl_fiyat}")
                        except Exception as sl_err:
                            if "-4130" not in str(sl_err): print(f"⚠️ [ZIRH UYARISI] Sabit Stop Kurulamadı: {sl_err}")

                        # 🛡️ Kalkan 2: Kısmi Kâr Alım (Scale-Out - 2.0 ATR)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TAKE_PROFIT_MARKET', side='buy', amount=yari_miktar,
                                params={'stopPrice': scale_out_fiyat, 'reduceOnly': True}
                            )
                            print(f"💰 [SCALE-OUT] {sembol} | %50 Kâr Alım Aktif: {scale_out_fiyat}")
                        except Exception as tp_err:
                            if "-4130" not in str(tp_err): print(f"⚠️ [ZIRH UYARISI] Scale-Out Kurulamadı: {tp_err}")

                        # 🛡️ Kalkan 3: Trailing Stop (Geri Kalanlar İçin Kâr Takibi)
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TRAILING_STOP_MARKET', side='buy', amount=miktar,
                                params={'callbackRate': callback_rate, 'activationPrice': activation_price, 'reduceOnly': True}
                            )
                            print(f"🎯 [SUNUCU GÜVENLİĞİ] {sembol} | Trailing Stop Aktif: %{callback_rate:.2f} | Aktivasyon: {activation_price}")
                        except Exception as tsl_error:
                            if "-4130" not in str(tsl_error): print(f"⚠️ [ZIRH UYARISI] Trailing Stop başarısız: {tsl_error}")

                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: SHORT | GİRİŞ: {gerceklesen_fiyat} | ZIRH: SABİT STOP ONAYLI")
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Ana Zırh Çöktü: {hata_msg}")
                            break
            except Exception as e:
                print(f"[{zaman}] İŞLEM/ZIRH BAŞARISIZ ({sembol}): {e}")
            
    except Exception as e:
        raise e

def analiz_motoru(hedef_coin, beyin):
    """
    Coin'i analiz eder ve bir sonuç raporu döndürür.
    success: True ise tüm filtrelerden geçmiş ve işlem açılabilir demektir.
    """
    guncel, tahmin_olasilik, yon, dinamik_esik = None, None, None, 0.55
    df = None
    sl, tp, rr = 0, 0, 0
    btc_dom = 50.0  

    try:
        if makro_volatilite_beklentisi(): return None

        try:
            df = veri_getir_dortlu(hedef_coin, REF)
        except: return None

        if df is None or df.empty: return None

        # --- KARANTİNA & KARA LİSTE KONTROLÜ ---
        if hedef_coin in KARA_LISTE:
            return None  # Kalıcı yasak
        if hedef_coin in KARANTINA_LISTESI:
            if datetime.now() < KARANTINA_LISTESI[hedef_coin]:
                return None  # Sessizce reddet
            else:
                del KARANTINA_LISTESI[hedef_coin]
                if hedef_coin in COIN_ZARAR_SAYACI: del COIN_ZARAR_SAYACI[hedef_coin]
                print(f"✅ [KARANTİNA BİTTİ] {hedef_coin} tekrar taranmaya başlandı.")

        features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'ADX', 'EMA_Slope']
        # 'open' sütunu teknik analiz fitil kontrolü için şarttır!
        if 'open' not in df.columns or any(f not in df.columns for f in features):
            eksik = [f for f in features + ['open'] if f not in df.columns]
            print(f"⚠️ Veri Hatası ({hedef_coin}): Eksik Kolonlar: {eksik}")
            return None

        try:
            tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None:
                beyin.model_egit(hedef_coin, df, is_crypto=True)
                tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None: return None
        except: return None

        guncel = float(df['Hedef_Close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1])
        volat_kat = (atr / guncel) * 100 
        dinamik_esik = 0.55 # XGBoost giriş eşiği kalite odaklı yükseltildi (%50.5 -> %55)

        guven_skoru_yuzde = tahmin_olasilik * 100
        if tahmin_olasilik > dinamik_esik: yon = "YÜKSELİŞ 🚀"
        elif tahmin_olasilik < (1.0 - dinamik_esik):
            yon = "DÜŞÜŞ 📉"
            guven_skoru_yuzde = 100 - (tahmin_olasilik * 100)
        else:
            yon = "NÖTR ⚖️"
            if tahmin_olasilik < 0.5: guven_skoru_yuzde = (1.0 - tahmin_olasilik) * 100

        # Rapor Hazırla (Base Sözlük)
        rapor = {
            'coin': hedef_coin, 'live_ok': False, 'demo_ok': False,
            'guven_skoru': guven_skoru_yuzde, 'yon': yon, 'fiyat': guncel,
            'margin_override': 0.04  # Fallback margin
        }

        if yon == "NÖTR ⚖️": return rapor
        
        # --- TREND KALKANI (Trend Shield) ---
        from tarayici import ana_trend_getir, btc_kalkan_kontrol, ema_mesafe_kontrol
        ana_trend = ana_trend_getir(hedef_coin)
        if "YÜKSELİŞ" in yon and ana_trend == "DOWN":
            return rapor
        elif "DÜŞÜŞ" in yon and ana_trend == "UP":
            return rapor

        # --- 🛡️ BTC KORELASYON KALKANI (Altcoin'in Kral'a Bağımlılığı) ---
        # BTC düşüyorsa altcoin LONG açma, BTC yükseliyorsa SHORT açma
        if hedef_coin != 'BTC/USDT':  # BTC'nin kendisi hariç
            btc_yon = btc_kalkan_kontrol()
            if "YÜKSELİŞ" in yon and btc_yon == "DOWN":
                return rapor  # BTC düşerken altcoin LONG açma
            elif "DÜŞÜŞ" in yon and btc_yon == "UP":
                return rapor  # BTC yükselirken altcoin SHORT açma

        # --- 1h Trend kaldırıldı (Uzman tavsiyesi: overfiltering riski) ---
        # 4h trend + 15m sinyal yeterli, 1h arada kalıyor ve lag yaratıyor

        # --- 🛡️ GİRİŞ ZAMANLAMASI (EMA Mesafe Kontrolü) ---
        # Fiyat EMA20'den çok uzaklaşmışsa treni kaçırmışsın, girme
        if not ema_mesafe_kontrol(df, yon, atr):
            return rapor  # Fiyat çok uzakta, tepe/dip kovalama riski

        # --- 🛡️ FUNDING RATE FİLTRESİ (Squeeze Riski Önleme) ---
        # Aşırı pozitif funding → long açma (short squeeze riski)
        # Aşırı negatif funding → short açma (long squeeze riski)
        son_funding = df['Funding_Rate'].iloc[-1] if 'Funding_Rate' in df.columns else 0.0001
        if "YÜKSELİŞ" in yon and son_funding > 0.001:  # %0.1+ = aşırı kalabalık long
            return rapor
        elif "DÜŞÜŞ" in yon and son_funding < -0.001:  # -%0.1 = aşırı kalabalık short
            return rapor

        # --- 🎯 MARKET REGIME ADAPTIF ATR ÇARPANI ---
        # Volatilite yüksekse geniş SL/TP, düşükse dar SL/TP
        volat_yuzde = (atr / guncel) * 100  # ATR'nin fiyata oranı
        if volat_yuzde > 1.5:  # Yüksek volatilite rejimi
            atr_carpani = 3.0
            tp_mult = 2.5  # Yüksek vol'de kâr daha hızlı al
        elif volat_yuzde < 0.5:  # Düşük volatilite rejimi
            atr_carpani = 1.8
            tp_mult = 3.5  # Düşük vol'de kâr hedefini geniş tut
        else:  # Normal rejim
            atr_carpani = 2.5
            tp_mult = 3.0

        # Pazar Gürültüsü (Spread/Taker Fee) Kalkanı:
        min_guvenli_mesafe = guncel * 0.0075
        hesaplanan_mesafe = atr * atr_carpani
        final_mesafe = max(hesaplanan_mesafe, min_guvenli_mesafe)
        if "YÜKSELİŞ" in yon:
            sl, tp = guncel - final_mesafe, guncel + (final_mesafe * tp_mult)
            rr = (tp - guncel) / (guncel - sl) if (guncel - sl) != 0 else 0
        else:
            sl, tp = guncel + final_mesafe, guncel - (final_mesafe * tp_mult)
            rr = (guncel - tp) / (sl - guncel) if (sl - guncel) != 0 else 0

        rapor.update({'tp': tp, 'sl': sl, 'rr': rr})

        # Base Filters
        son_adx = df['ADX'].iloc[-1] if 'ADX' in df.columns else 25.0
        son_chop = df['CHOP'].iloc[-1] if 'CHOP' in df.columns else 50.0
        fg_skor, _ = korku_acgozluluk_getir()
        
        if 'volume' in df.columns:
            hacim_sma = df['volume'].rolling(window=20).mean().iloc[-1]  # RVOL: 20 mum ortalaması (daha güvenilir)
            anlik_hacim = df['volume'].iloc[-1]
            hacim_patlamasi = (anlik_hacim / hacim_sma) - 1.0 if hacim_sma > 0 else 0
        else:
            hacim_patlamasi = 0

        # Fitil ve RSI Mutabakatı (Bifurcated kontrol öncesi genel red sebepleri)
        son_rsi = df['RSI'].iloc[-1] if 'RSI' in df.columns else 50
        son_macd = df['MACD'].iloc[-1] if 'MACD' in df.columns else 0
        onceki_macd = df['MACD'].iloc[-2] if 'MACD' in df.columns else 0
        anlik_mum = df.iloc[-1] 
        vucut = abs(anlik_mum['Hedef_Close'] - anlik_mum['open'])
        
        genel_red = False
        # MACD Histogram kontrolü (önceki katı filtre yerine histogram yönü)
        macd_histogram = son_macd - (df['MACD'].rolling(9).mean().iloc[-1] if 'MACD' in df.columns else 0)
        if "YÜKSELİŞ" in yon:
            ust_fitil = anlik_mum['high'] - max(anlik_mum['open'], anlik_mum['Hedef_Close'])
            if ust_fitil > (vucut * 1.5) and ust_fitil > (atr * 0.5): genel_red = True
            if son_rsi > 70 or macd_histogram < 0: genel_red = True
            if fg_skor < 18: genel_red = True
        else:
            alt_fitil = min(anlik_mum['open'], anlik_mum['Hedef_Close']) - anlik_mum['low']
            if alt_fitil > (vucut * 1.5) and alt_fitil > (atr * 0.5): genel_red = True
            if son_rsi < 30 or macd_histogram > 0: genel_red = True
            
        sqz_on = df['Squeeze_ON'].iloc[-1] if 'Squeeze_ON' in df.columns else 0.0
        if sqz_on > 0: genel_red = True
        
        if genel_red:
            return rapor

        # =========================================================
        # BİFURCATION (LIVE vs DEMO ŞARTLARI)
        # =========================================================
        # LIVE Şartları (Kalite Odaklı - Daha az ama daha isabetli)
        _live_prob = tahmin_olasilik if "YÜKSELİŞ" in yon else (1 - tahmin_olasilik)
        live_ok = (
            son_adx > 22.0 and
            son_chop < 58.0 and
            rr >= 2.0 and
            hacim_patlamasi > 0.30 and
            _live_prob > 0.60
        )

        # DEMO Şartları (Dengeli)
        _demo_prob = tahmin_olasilik if "YÜKSELİŞ" in yon else (1 - tahmin_olasilik)
        demo_ok = (
            son_adx > 18.0 and
            son_chop < 62.0 and
            rr >= 1.5 and
            hacim_patlamasi > 0.10 and
            _demo_prob > 0.55
        )

        if not live_ok and not demo_ok:
            return rapor

        # Bütçe (Aynı rr ve ihtimalleri kullandığımız için tek frac_kelly hesaplanıyor, 
        # LIVE mod zaten kendi algoritmasını `margin_override` üzerinden limitliyor.)
        p_kelly = tahmin_olasilik if "YÜKSELİŞ" in yon else (1.0 - tahmin_olasilik)
        kelly_orani = max(0, (p_kelly * rr - (1-p_kelly)) / rr) if rr > 0 else 0
        
        # Testnet (Demo) işlemleri için sabit bütçe %4
        # Live işlemleri için max %95 kelly, islem_ac içinde hesaplanıyor veya burada kullanılıyor.
        frac_kelly_live = max(0.01, min(0.95, kelly_orani))
        frac_kelly_demo = 0.04

        rapor.update({
            'success': True,  # Genel Success flag ki sinyal havuzuna eklensin
            'live_ok': live_ok,
            'demo_ok': demo_ok,
            'margin_override_live': frac_kelly_live,
            'margin_override_demo': frac_kelly_demo,
            'fg_skor': fg_skor
        })
        return rapor

    except Exception as e:
        print(f"⚠️ Analiz Hatası ({hedef_coin}): {e}")
        return None

# ============================================================
# 🏦 PORTFÖY ISI SINIRI (Portfolio Heat Limit)
# Açık pozisyonların toplam büyüklüğü, toplam kasanın %80'ini geçemez.
# ============================================================
MAX_PORTFOY_ISI_YUZDESI = 0.95  # Kasanın max %95'i aynı anda risk altında olabilir (20+ Pozisyon Kapasitesi)

def portfoy_isi_hesapla():
    """Açık demo pozisyonların sayısına göre harcanan yaklaşık bütçeyi döndürür."""
    # Testnet portföy kapasitesi her açılan pozisyon %4 bakiye yediği için:
    if 'pozisyonlar' in _DEMO_CACHE:
        demo_poz_sayisi = len([p for p in _DEMO_CACHE['pozisyonlar'] if 'DEMO' in p[0].get('Hesap_Tipi', '')])
        return demo_poz_sayisi * (KASA_DURUM.get('DEMO_KASA', 1000) * 0.04)
    return 0.0

def surekli_tarama_ve_analiz():
    beyin = BeyinMotoru()
    
    while True:
        try:
            print("\n" + "="*70)
            print(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] AŞAMA 1: SCOUT (Hafif Tarayıcı) Başlıyor...")
            
            # Public (non-testnet) API ile TÜM Binance Futures USDT paritelerini çek
            tikler = scout_borsa.fetch_tickers()
            if not tikler:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ SCOUT: Ticker verisi boş geldi, döngü atlanıyor.")
                time.sleep(30)
                continue
            
            # -------------------------------------------------------------
            # LOKAL DEMO BİLGİ GÜNCELLEMESİ
            # -------------------------------------------------------------
            acik_semboller = []
            try:
                # Cache pozisyonlarini acik kabul et
                for p, a in _DEMO_CACHE.get('pozisyonlar', []):
                    acik_semboller.append(p.get('symbol'))
            except: pass
            try:
                pozisyonlar = borsa_live.fetch_positions()
                for p in pozisyonlar:
                    if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0:
                        acik_semboller.append(p.get('symbol'))
            except: pass
            # -------------------------------------------------------------
            
            adaylar = []
            for sembol, veri in tikler.items():
                if '/USDT' not in sembol:
                    continue
                hacim = float(veri.get('quoteVolume') or 0)
                degisim = abs(float(veri.get('percentage') or 0))
                if hacim > 15_000_000:
                    temiz_sembol = sembol.replace(':USDT', '')
                    if SPOT_SEMBOLLER and temiz_sembol not in SPOT_SEMBOLLER:
                        continue
                    adaylar.append({'sembol': temiz_sembol, 'hacim': hacim, 'degisim': degisim})
            
            adaylar.sort(key=lambda x: x['degisim'], reverse=True)
            sicak_coinler = [x['sembol'] for x in adaylar[:100]] # Liste 100'e genisletildi (Agresif Tarama)
            
            # --- DURUM BİLGİSİ ---
            if CANLI_DEVRE_KESICI_AKTIF:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 [LIVE: DEVRE KESİCİ AKTİF - Uyanış Bekleniyor]")
            elif not ALIM_SATIM_TETIGI_ACIK:
                if PING_MODU:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: PİNG MODU (Sadece FDUSD)]")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: KAPALI (Güvenlik Kilidi)]")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔥 [LIVE: AKTİF] - GERÇEK PARA İŞLEM TETİĞİ ONAYLANDI!")
            
            # --- Portföy Isı Durumu ---
            mevcut_isi = portfoy_isi_hesapla()
            demo_kasa = KASA_DURUM.get('DEMO_KASA', 1000)
            mevcut_isi_yuzde = (mevcut_isi / demo_kasa * 100) if demo_kasa > 0 else 0
            max_isi = demo_kasa * MAX_PORTFOY_ISI_YUZDESI
            kalan_kapasite = max(0, max_isi - mevcut_isi)
            print(f"🌡️  Portföy Isı: %{mevcut_isi_yuzde:.1f} / %{MAX_PORTFOY_ISI_YUZDESI*100:.0f} | Kullanılan: {mevcut_isi:.2f}$ | Kalan Kapasite: {kalan_kapasite:.2f}$")
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Dinamik Tarayıcı: Piyasadan seçilen en sıcak coinler:")
            for i, coin in enumerate(sicak_coinler[:20], 1):  # İlk 20'yi göster
                aday = next((a for a in adaylar if a['sembol'] == coin), None)
                if aday:
                    print(f"  {i:2d}. {coin:<12} | Hacim: ${aday['hacim']/1e6:.0f}M | Değişim: %{aday['degisim']:.1f}")
            
            # ============================================================
            # 🎯 AŞAMA 2: SNIPER — Sinyal Toplama (Signal Collection)
            # Tüm coinleri analiz et, sinyalleri topla ama hemen işlem AÇMA.
            # ============================================================
            print(f"\n🎯 AŞAMA 2: SNIPER (Sinyal Toplama) Başlıyor... (Toplam {len(sicak_coinler)} coin)")
            sinyal_havuzu = []    # Tüm geçerli sinyaller (Filtreleri geçenler)
            tahmin_havuzu = []    # Tüm tahmin sonuçları (Debug Log için)
            
            for index, coin in enumerate(sicak_coinler, 1):
                if coin in acik_semboller:
                    continue
                
                # İlerleme Logu (Kullanıcı botun çalıştığını görsün)
                print(f"  [{index}/{len(sicak_coinler)}] {coin} analiz ediliyor...", flush=True)
                    
                rapor = analiz_motoru(coin, beyin)
                if rapor is not None:
                    tahmin_havuzu.append(rapor)
                    if rapor.get('success'):
                        sinyal_havuzu.append(rapor)
                time.sleep(3)
            
            # ============================================================
            # 🔍 DEBUG LOG: En Yüksek Tahmin Skorları
            # Neden işlem açılmadığını anlamak için en iyi 3 skoru göster.
            # ============================================================
            if tahmin_havuzu:
                tahmin_havuzu.sort(key=lambda x: x['guven_skoru'], reverse=True)
                print(f"\n🔍 [DEBUG LOG] En Yüksek Sinyal Skorları (Top 3):")
                for i, t in enumerate(tahmin_havuzu[:3], 1):
                    esik = t.get('dinamik_esik', 55.0)
                    skor = t.get('guven_skoru', 0.0)
                    durum = "✅ EŞİK ÜSTÜ" if skor >= esik else "❌ YETERSİZ"
                    print(f"  {i}. {t['coin']}: %{skor:.1f} (Eşik: %{esik:.1f}) -> {durum}")
                
                if not sinyal_havuzu:
                    top_skor = tahmin_havuzu[0]['guven_skoru']
                    top_esik = tahmin_havuzu[0]['dinamik_esik']
                    if top_skor < top_esik:
                        print(f"📢 Sinyal yetersiz, en yüksek skor %{top_skor:.1f} (Gereken: %{top_esik:.1f})")
                    else:
                        print(f"📢 Skorlar yeterli ama diğer filtreler (Hacim, RSI, TSL vb.) engelledi.")
            else:
                print(f"📢 Veri alınamadığı için tahmin yapılamadı.")
            
            # ============================================================
            # 🏆 AŞAMA 3: RANK & SORT — Sinyal Sıralama (Signal Ranking)
            # XGBoost Güven Skoruna göre en yüksekten en düşüğe sırala.
            # ============================================================
            if sinyal_havuzu:
                sinyal_havuzu.sort(key=lambda x: x['guven_skoru'], reverse=True)
                
                print(f"\n" + "═"*70)
                print(f"🏆 [{datetime.now().strftime('%H:%M:%S')}] AŞAMA 3: RANK & EXECUTE — {len(sinyal_havuzu)} Sinyal Sıralandı!")
                print(f"{'SIRA':<5} | {'COİN':<12} | {'YÖN':<10} | {'GÜVEN':<8} | {'R/R':<6} | {'BÜTÇE':<8}")
                print("-" * 70)
                for i, s in enumerate(sinyal_havuzu, 1):
                    print(f"  {i:<3} | {s['coin']:<12} | {s['yon']:<10} | %{s['guven_skoru']:<6.1f} | {s['rr']:<5.2f} | %{s['margin_override']*100:<6.1f}")
                print("═"*70)
                
                # ============================================================
                # 🏦 AŞAMA 4: AKILLI BÜTÇE DAĞITIMI (Smart Budget Dispatch)
                # Her emirden önce Portföy Isısını kontrol et.
                # Kasanın %80'ını aşarsa sıradaki işlemi iptal et.
                # ============================================================
                print(f"\n🏦 AŞAMA 4: Akıllı Bütçe Dağıtımı (Heat Limit: %{MAX_PORTFOY_ISI_YUZDESI*100:.0f})")
                gonderilen_sinyal_sayisi = 0
                
                for sinyal in sinyal_havuzu:
                    # Anlık ısı kontrolü (her emirden önce yeniden hesapla)
                    mevcut_isi = portfoy_isi_hesapla()
                    demo_kasa = KASA_DURUM.get('DEMO_KASA', 1000)
                    max_isi = demo_kasa * MAX_PORTFOY_ISI_YUZDESI
                    kalan_kapasite = max(0, max_isi - mevcut_isi)
                    
                    tahmini_marjin = demo_kasa * sinyal.get('margin_override_demo', 0.04)
                    
                    if tahmini_marjin > kalan_kapasite and sinyal.get('demo_ok'):
                        print(f"  🛑 {sinyal['coin']} DEMO İPTAL: Portföy Isı Sınırı! (Gereken: {tahmini_marjin:.2f}$ > Kalan: {kalan_kapasite:.2f}$)")
                        sinyal['demo_ok'] = False
                        if not sinyal.get('live_ok'):
                            continue # Hem demo kapandı, hem live yoksa iptal
                    
                    # İşlemi gönder
                    islem_mesaji = f"  ✅ {sinyal['coin']} -> Güven: %{sinyal['guven_skoru']:.1f}"
                    if sinyal.get('demo_ok'): islem_mesaji += f" | Demo Bütçe: {tahmini_marjin:.2f}$"
                    if sinyal.get('live_ok'): islem_mesaji += f" | Live ONAYLI"
                    print(islem_mesaji)
                    
                    islem_ac(sinyal)
                    gonderilen_sinyal_sayisi += 1
                    time.sleep(1)  # Rate limit koruması
                
                print(f"\n📊 Döngü Sonu: {len(sinyal_havuzu)} sinyal toplandı, {gonderilen_sinyal_sayisi} işlem açıldı.")
            else:
                print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Filtrelerden geçen sinyal bulunamadı.")
                
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            print(f"[{zaman}] ⚠️ Tarayıcı Hatası: {e}")
            borsa_baglantisini_yenile("Scout Hatası")
            time.sleep(10)
            
        print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Tarama döngüsü tamamlandı, 60 saniye bekleniyor...")
        time.sleep(60)  # 30s -> 60s (Agresif Demo Modu)

def borsa_gerceklesen_pnl_getir(borsa_istemci, sembol, max_deneme=3):
    for _ in range(max_deneme):
        try:
            trades = borsa_istemci.fetch_my_trades(symbol=sembol, limit=10)
            simdi_ms = time.time() * 1000
            net_pnl = 0.0
            found = False
            for t in reversed(trades): 
                t_time = t.get('timestamp', 0)
                if (simdi_ms - t_time) < (120 * 60 * 1000): # Son 2 saat
                    rpnl = float(t.get('info', {}).get('realizedPnl', 0.0))
                    if rpnl != 0.0:
                        net_pnl += rpnl
                        found = True
            if found: return net_pnl
            time.sleep(1)
        except: time.sleep(1)
    return None

def canli_islem_kapat(borsa_istemci, sembol, islem_yonu, miktar):
    try:
        zit_yon = 'sell' if islem_yonu == 'LONG' else 'buy'
        print(f"⚠️ [DETERMINİSTİK EXIT] {sembol} için Zıt Yön ({zit_yon.upper()}) Fiziksel Kapanış Emri (Reduce-Only) gönderiliyor...")
        emir = borsa_istemci.create_order(symbol=sembol, type='MARKET', side=zit_yon, amount=miktar, params={'reduceOnly': True})
        
        try: borsa_istemci.cancel_all_orders(sembol)
        except: pass
        print(f"✅ {sembol} BAŞARIYLA FİZİKSEL OLARAK KAPATILDI!")
        return emir
    except Exception as e:
        print(f"❌ [KAPANIŞ HATASI] {sembol} Fiziksel Kapanış İletilemedi: {e}")
        return None

def _hesap_pozisyon_cek(borsa_istemci, hesap_tipi, mevcut_semboller, aktifler):
    try:
        if not hasattr(borsa_istemci, 'apiKey') or not borsa_istemci.apiKey:
            return True
        pozisyonlar = borsa_istemci.fetch_positions()
        if type(pozisyonlar) is not list:
            raise Exception("API Hatalı Format")
            
        for p in pozisyonlar:
            amt = float(p.get('contracts', p.get('info', {}).get('positionAmt', 0)))
            if amt != 0:
                p['Hesap_Tipi'] = hesap_tipi
                aktifler.append((p, amt))
                sembol = p.get('symbol', 'Bilinmiyor')
                mevcut_semboller.add(f"{sembol}_{hesap_tipi}")
        return True # API Başarılı
    except Exception as e:
        if hesap_tipi == 'LIVE':  # Sadece LIVE hataları göster, DEMO sessiz kalsın
            print(f"⏳ [Bağlantı Bekleniyor...] {hesap_tipi} API geçici olarak ulaşılamıyor. (Detay: {e})")
        return False # API Hatası

def pozisyon_takip_paneli():
    global onceki_pozisyonlar, performans, KASA_DURUM, COOLDOWN_DICT
    global ALIM_SATIM_TETIGI_ACIK, CANLI_DEVRE_KESICI_AKTIF, LIVE_ARDISIK_ZARAR, DEMO_ARDISIK_KAR, SON_ISLEMLER_PNL_LIVE
    global GUN_BASLANGIC_BAKIYESI, SON_RESET_TARIHI
    while True:
        try:
            aktifler = []
            mevcut_semboller = set()
            
            # REST APİ Yerine WSS (WebSocket) Veri Nehrinden anlık çek
            tum_tikler = WSS_TICKERS
            
            # --- LIVE: GERÇEK POZİSYONLARI ÇEK ---
            live_api_ok = _hesap_pozisyon_cek(borsa_live, "LIVE", mevcut_semboller, aktifler)
            # --- TESTNET (DEMO): CACHE İLE POZİSYONLARİ ÇEK (5dk aralıkla) ---
            simdi_ts = time.time()
            if simdi_ts - _DEMO_CACHE['son_guncelleme'] > _DEMO_CACHE_SURESI:
                demo_api_ok = _hesap_pozisyon_cek(borsa, "DEMO", mevcut_semboller, aktifler)
                if demo_api_ok:
                    # Cache'e kaydet
                    _DEMO_CACHE['pozisyonlar'] = [(p, a) for p, a in aktifler if p.get('Hesap_Tipi') == 'DEMO' and p.get('symbol','') not in [s.replace('_DEMO','') for s in mevcut_semboller if s.endswith('_DEMO') and (p, a) not in aktifler]]
                    _DEMO_CACHE['son_guncelleme'] = simdi_ts
            else:
                # Cache'den oku (API'ye dokunma)
                for cp, ca in _DEMO_CACHE.get('pozisyonlar', []):
                    sym = cp.get('symbol', '')
                    if f"{sym}_DEMO" not in mevcut_semboller:
                        aktifler.append((cp, ca))
                        mevcut_semboller.add(f"{sym}_DEMO")
            
            # --- Kapanan Pozisyon Tespiti (Win/Loss Tracker) ---
            for eski_key, eski_pnl in list(onceki_pozisyonlar.items()):
                if eski_key not in mevcut_semboller:
                    eski_sembol = eski_key.split('_')[0]
                    hesap_t = eski_key.split('_')[1] if '_' in eski_key else 'DEMO'
                    if hesap_t == 'DEMO':
                        continue # Demo Sanal Motor kapanışları kendi Loop'unda halletti.
                        
                    if not live_api_ok:
                        mevcut_semboller.add(eski_key) # Körlük Kalkanı: API çöktü, işlem AÇIK!
                        continue
                        
                    # Gerçekçi Fatura Denetimi (Deterministic Engine)
                    gercek_pnl = borsa_gerceklesen_pnl_getir(borsa_live, eski_sembol)
                    if gercek_pnl is None: 
                        gercek_pnl = eski_pnl # Fatura okunamadıysa geçici olarak eski PNL kullan
                        
                    if gercek_pnl >= 0:
                        performans['kazanc'] += 1
                        LIVE_ARDISIK_ZARAR = 0
                        print(f"✅ [{hesap_t}] {eski_sembol} KÂRLA KAPANDI! (Gerçekleşen Fatura: +{gercek_pnl:.2f} USDT)")
                    else:
                        performans['kayip'] += 1
                        LIVE_ARDISIK_ZARAR += 1
                        print(f"❌ [{hesap_t}] {eski_sembol} ZARARLA KAPANDI! (Gerçekleşen Fatura: {gercek_pnl:.2f} USDT)")
                        
                    if LIVE_ARDISIK_ZARAR >= 3:
                        ALIM_SATIM_TETIGI_ACIK = False
                        CANLI_DEVRE_KESICI_AKTIF = True
                        print("🛑 [DEVRE KESİCİ] 3 Ardışık Canlı Zarar! LIVE işlemler kilitlendi, uyanış için Demo kanıtı bekleniyor...")

                    # --- ANLIK BEKLENTİ (EXPECTANCY) KONTROLÜ ---
                    SON_ISLEMLER_PNL_LIVE.append(gercek_pnl)
                    if len(SON_ISLEMLER_PNL_LIVE) > 10:
                        SON_ISLEMLER_PNL_LIVE.pop(0)

                    if len(SON_ISLEMLER_PNL_LIVE) == 10:
                        _karlar = [p for p in SON_ISLEMLER_PNL_LIVE if p > 0]
                        _zararlar = [p for p in SON_ISLEMLER_PNL_LIVE if p <= 0]
                        _win_rate = len(_karlar) / 10.0
                        _loss_rate = len(_zararlar) / 10.0
                        _avg_kar = sum(_karlar) / len(_karlar) if _karlar else 0.0
                        _avg_zarar = abs(sum(_zararlar) / len(_zararlar)) if _zararlar else 0.0
                        _expectancy = (_win_rate * _avg_kar) - (_loss_rate * _avg_zarar)
                        
                        if _expectancy < -0.2 and not CANLI_DEVRE_KESICI_AKTIF:
                            ALIM_SATIM_TETIGI_ACIK = False
                            CANLI_DEVRE_KESICI_AKTIF = True
                            print(f"🛑 [DEVRE KESİCİ] Matematiksel Beklenti Çöktü (E: {_expectancy:.2f}) HEDEF: > -0.2! LIVE işlemler kilitlendi...")
                        
                    # --- Trade Logger Kaydı ---
                    detay = aktif_islemler_detay.get(eski_key, {})
                    if detay:
                        giris = detay.get('Giris_Fiyati', 0.0)
                        miktar = detay.get('Miktar', 1.0)
                        islem_yonu = detay.get('Islem_Yonu', 'Bilinmiyor')
                        ai_skoru = detay.get('AI_Guven_Skoru', 0.0)
                        
                        cikis = 0.0
                        pnl_yuzde = 0.0
                        if islem_yonu == 'LONG':
                            cikis = giris + (gercek_pnl / miktar) if miktar > 0 else 0
                            pnl_yuzde = ((cikis - giris) / giris) * 100 if giris > 0 else 0
                        elif islem_yonu == 'SHORT':
                            cikis = giris - (gercek_pnl / miktar) if miktar > 0 else 0
                            pnl_yuzde = ((giris - cikis) / giris) * 100 if giris > 0 else 0
                        
                        islem_kaydet(eski_sembol, hesap_t, islem_yonu, round(giris, 6), round(cikis, 6), round(gercek_pnl, 2), round(pnl_yuzde, 2), round(ai_skoru, 2))
                        
                        if hesap_t == 'LIVE':
                            try:
                                borsa_live.cancel_all_orders(eski_sembol)
                                print(f"🧹 [{eski_sembol}] Otonom Temizlik: Arkada kalan şarta bağlı (Stop/TP) emirler iptal edildi.")
                            except: pass
                            
                        try: del aktif_islemler_detay[eski_key]
                        except: pass
            
            # Mevcut pozisyonları güncelle
            yeni_pozisyonlar = {}
            
            # --- BAKİYE GÜNCELLEME (CACHE + API) ---
            simdi_ts2 = time.time()
            if simdi_ts2 - _DEMO_CACHE['son_guncelleme'] < _DEMO_CACHE_SURESI and _DEMO_CACHE['bakiye'] > 0:
                bakiye_demo = _DEMO_CACHE['bakiye']
            else:
                try:
                    bakiye_demo = float(borsa.fetch_balance({'type': 'future'}).get('USDT', {}).get('total', 0.0)) if hasattr(borsa, 'apiKey') and borsa.apiKey else KASA_DURUM.get('DEMO_KASA', 0.0)
                    KASA_DURUM['DEMO_KASA'] = bakiye_demo
                    _DEMO_CACHE['bakiye'] = bakiye_demo
                    _DEMO_CACHE['son_guncelleme'] = simdi_ts2
                except:
                    bakiye_demo = _DEMO_CACHE['bakiye'] if _DEMO_CACHE['bakiye'] > 0 else SANAL_KRIPTO_KASA

            try:
                bakiye_live = float(borsa_live.fetch_balance({'type': 'future'}).get('USDT', {}).get('total', 0.0)) if hasattr(borsa_live, 'apiKey') and borsa_live.apiKey else 0.0
                KASA_DURUM['LIVE_KASA'] = bakiye_live
            except:
                bakiye_live = 0.0
            
            # --- OTONOM RESET (GECE 00:00) VE DRAWDOWN (KANAMA) KONTROLÜ ---
            bugun = datetime.now().date()
            if bugun != SON_RESET_TARIHI:
                SON_RESET_TARIHI = bugun
                GUN_BASLANGIC_BAKIYESI = bakiye_live
                LIVE_ARDISIK_ZARAR = 0
                DEMO_ARDISIK_KAR = 0
                SON_ISLEMLER_PNL_LIVE.clear()
                ALIM_SATIM_TETIGI_ACIK = False
                CANLI_DEVRE_KESICI_AKTIF = False
                print(f"🌅 [YENİ GÜN] Sistem sayaçları sıfırlandı. Yeni Gün Başlangıç Bakiyesi: {GUN_BASLANGIC_BAKIYESI:.2f} USDT")
                
                # --- TELEGRAM GECE RAPORU ---
                gunluk_rapor_gonder()
                
                try:
                    import subprocess
                    print("📊 [GECE YARISI OTOMASYONU] Müfettiş ve Dijital Analist otonom olarak tetikleniyor...")
                    subprocess.Popen([sys.executable, "mufettis.py"])
                except:
                    pass
                
            if GUN_BASLANGIC_BAKIYESI is None and bakiye_live > 0:
                GUN_BASLANGIC_BAKIYESI = bakiye_live
                
            if GUN_BASLANGIC_BAKIYESI is not None and bakiye_live > 0:
                drawdown_yuzde = ((GUN_BASLANGIC_BAKIYESI - bakiye_live) / GUN_BASLANGIC_BAKIYESI) * 100
                if drawdown_yuzde >= 10.0 and ALIM_SATIM_TETIGI_ACIK:
                    ALIM_SATIM_TETIGI_ACIK = False
                    CANLI_DEVRE_KESICI_AKTIF = True
                    print(f"🚨 [KRİTİK ZARAR EŞİĞİ] Günlük bakiye %{drawdown_yuzde:.2f} eridi (Limit: %10)! Sistem güvenlik için durduruldu.")
                    
            print("\n" + "="*50)
            
            toplam_pnl_demo = 0
            toplam_pnl_live = 0
            
            if not aktifler:
                print(f"⏳ [{datetime.now().strftime('%H:%M:%S')}] Aktif İşlem Yok. Fırsatlar Taranıyor...")
            else:
                print(f"📊 AÇIK POZİSYONLAR | {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 50)
                
                for p, amt in aktifler:
                    sembol = p.get('symbol', 'Bilinmiyor').replace(':USDT', '')
                    hesap_t = p.get('Hesap_Tipi', 'Bilinmiyor')
                    guncel_fiyat = float(p.get('markPrice', p.get('info', {}).get('markPrice', 0)))
                    pnl = float(p.get('unrealizedPnl', p.get('info', {}).get('unRealizedProfit', 0)))
                    key = f"{sembol}_{hesap_t}"
                    
                    if hesap_t == 'LIVE':
                        toplam_pnl_live += pnl
                    else:
                        toplam_pnl_demo += pnl
                        
                    yeni_pozisyonlar[key] = pnl
                    
                    # --- Trailing Stop Görünürlüğü ---
                    eski_pnl = onceki_pozisyonlar.get(key)
                    if eski_pnl is not None and pnl > 0 and pnl > eski_pnl and eski_pnl > 0:
                        giris_fiyat = float(p.get('entryPrice', p.get('info', {}).get('entryPrice', 0)))
                        if giris_fiyat > 0:
                            if amt > 0:  # LONG
                                tsl_seviye = guncel_fiyat * 0.985
                            else:  # SHORT
                                tsl_seviye = guncel_fiyat * 1.015
                            print(f"  🛡️ TSL Güncellendi: [{hesap_t}] {sembol} | Yeni Stop ~{tsl_seviye:.2f}$ (Kâr büyüyor!)")
                    
                    # Yön tespiti
                    islem_yeri = p.get('positionSide', '').upper()
                    if islem_yeri == 'LONG':
                        yon_str = "🟢 LONG"
                    elif islem_yeri == 'SHORT':
                        yon_str = "🔴 SHORT"
                    else:
                        yon_str = "🟢 LONG" if amt > 0 else "🔴 SHORT"
                        
                    print(f" [{hesap_t}] {sembol:<12} | {yon_str} | K/Z: {pnl:+.2f} USDT")
                
                print("-" * 50)

            # --- KASA DURUMU (Her zaman basılır - Commander Header için) ---
            # Binance ile birebir eşleşen GERÇEK Net P&L:
            # Toplam Varlık (bakiye + açık pozisyon PnL) - Başlangıç Sermaye
            equity_demo = bakiye_demo + toplam_pnl_demo
            equity_live = bakiye_live + toplam_pnl_live
            
            # DEMO başlangıç sermayesi henüz ayarlanmadıysa, ilk okunan değeri kullan
            global BASLANGIC_SERMAYE_DEMO
            if BASLANGIC_SERMAYE_DEMO == 0.0 and bakiye_demo > 0:
                BASLANGIC_SERMAYE_DEMO = bakiye_demo
            
            # Gerçek Net K/Z (Komisyon + Funding + Kapanmış işlemler DAHİL)
            gercek_pnl_live = equity_live - BASLANGIC_SERMAYE_LIVE if equity_live > 0 else 0.0
            gercek_pnl_demo = equity_demo - BASLANGIC_SERMAYE_DEMO if BASLANGIC_SERMAYE_DEMO > 0 else toplam_pnl_demo
            
            # Not: Commander Interceptor "$" işaretini ve "|" ayırıcıyı arar
            print(f" 🏦 [DEMO] Kasa: ${equity_demo:.2f} | K/Z: ${gercek_pnl_demo:+.2f} | VARLIK: ${equity_demo:.2f}")
            print(f" 🏦 [LIVE] Kasa: ${equity_live:.2f} | K/Z: ${gercek_pnl_live:+.2f} | VARLIK: ${equity_live:.2f}")
            
            # --- Performans Karnesi ---
            toplam_islem = performans['kazanc'] + performans['kayip']
            win_rate = (performans['kazanc'] / toplam_islem * 100) if toplam_islem > 0 else 0
            print(f"📊 PERFORMANS: Kazanma Oranı: %{win_rate:.0f} | Başarılı: {performans['kazanc']} | Başarısız: {performans['kayip']}")
            print("="*50 + "\n")
            
            onceki_pozisyonlar = yeni_pozisyonlar
            
        except Exception:
            pass
        
        time.sleep(30)

if __name__ == "__main__":
    print("\n🧹 [SİSTEM BAKIMI] Otonom İmha Protokolü Başlatılıyor...")
    eski_modeller = glob.glob("*.pkl")
    silinen_sayisi = 0
    for dosya in eski_modeller:
        try:
            os.remove(dosya)
            silinen_sayisi += 1
        except:
            pass
    print(f"✅ {silinen_sayisi} adet eski/bayat XGBoost modeli (pkl) kalıcı olarak silindi. Taze veriyle yeni beyinler inşa edilecek.")

    try:
        import subprocess
        print("\n📊 [AÇILIŞ OTOMASYONU] Sistem Raporları (Müfettiş ve LLM) arka planda hazırlanıyor...")
        subprocess.Popen([sys.executable, "mufettis.py"])
    except:
        pass

    print(f"\n🚀 SİSTEM BAŞLATILIYOR (Savaş Modu: V3 - Tam Otonom)")
    print(f"🔸 DEMO Bot: AKTİF")
    print(f"🔸 LIVE Bot: {'AKTİF (Agresif Mod - Max %95 Risk / 3x Kaldıraç)' if LIVE_API_KEY else 'KAPALI (LIVE API Bulunamadı)'}")
    
    # --- BAŞLANGIÇ CANLI (LIVE) API DR-RUN (BAĞLANTI DOĞRULAMA) ---
    if LIVE_API_KEY and hasattr(borsa_live, 'apiKey') and borsa_live.apiKey:
        print("\n⚙️ [API DRY-RUN] LIVE Cüzdan bağlantısı test ediliyor...")
        try:
            bakiye_bilgisi = borsa_live.fetch_balance({'type': 'future'})
            canli_bakiye = float(bakiye_bilgisi.get('USDT', {}).get('total', 0.0))
            KASA_DURUM['LIVE_KASA'] = canli_bakiye
            print(f"   ✅ CANLI BAKİYE: {canli_bakiye:.2f} USDT - API BAĞLANTISI BAŞARILI!")
            time.sleep(5)
        except Exception as e:
            hata_mesaji = str(e)
            print(f"   ❌ LIVE CÜZDAN BAĞLANTI HATASI: {hata_mesaji}\n")
            print("      Lütfen API yetkilerinizi, IP izinlerini ve Vadeli işlemler aktivasyonunu kontrol ediniz.")
            time.sleep(5)
    # ----------------------------------------
    
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
                df_b = veri_getir_dortlu(cc, REF)
                if df_b is not None and not df_b.empty:
                    b_motor.model_egit(cc, df_b, is_crypto=True)
                time.sleep(0.1) 
            except: pass
        print("✅ [BOOTCAMP] 100 Aktif Model savaşa hazır!")
    except Exception as e:
        print(f"⚠️ Bootcamp atlandı: {e}")
        
    t_panel = threading.Thread(target=pozisyon_takip_paneli, daemon=True)
    t_panel.start()
    
    # --- Ölümsüzlük Döngüsü (Continuous Execution Engine) ---
    import sys
    while True:
        try:
            surekli_tarama_ve_analiz()
        except KeyboardInterrupt:
            print("\n🛑 Sistem manuel olarak durduruldu.")
            sys.exit(0)
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            print(f"\n🔥 [{zaman}] [KRİTİK HATA] Ana Motor Şiddetli Hata Aldı: {e}")
            print("⏳ 10 Saniye sonra sistem kendi kendini otonom olarak yeniden başlatacak (Rate Limit ve CPU Koruması)...")
            time.sleep(10)
