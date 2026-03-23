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

from tarayici import veri_getir_dortlu, ana_trend_getir
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
    TESTNET_API_KEY = AYAR.get("testnet_api_key", "")
    TESTNET_SECRET = AYAR.get("testnet_secret", "")
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
borsa.enable_demo_trading(True)

# LIVE Binance CCXT Bağlantısı
LIVE_API_KEY = os.environ.get('LIVE_API_KEY', '').strip()
LIVE_SECRET = os.environ.get('LIVE_SECRET_KEY', '').strip()
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
borsa_live = ccxt.binance(borsa_live_config)

# Piyasa Tarayıcı (Scout) için AYRI bir public CCXT instance (FUTURES - Ticker için)
scout_borsa = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})

# Spot API (Veri Çekme ve Analiz Motoru için)
spot_borsa = ccxt.binance({'enableRateLimit': True, 'options': {'adjustForTimeDifference': True, 'recvWindow': 60000}})

# UI Paneli için AYRI CCXT instance (Hız ve Çakışma Önleme)
ui_borsa = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})

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

ALIM_SATIM_TETIGI_ACIK = True   # CANLI SİSTEM ATEŞLENDİ! 🚀🔥 (Max 1 LIVE Pozisyon Sınırı Aktif)
LIVE_ISLEM_KILIDI = threading.Lock() # Race Condition kilidi
PING_MODU = False               # Test bitti, tüm paritelerde ava çıkıyoruz. (KAPALI)

SANAL_KASA_DOSYASI = 'sanal_kasa_kripto.json'
try:
    with open(SANAL_KASA_DOSYASI, 'r') as f:
        okunan_bakiye = float(json.load(f).get('bakiye', 10000.0))
        if okunan_bakiye < 5000:
            print(f"⚠️ [UYARI] Hayalet/Enkaz bakiye tespit edildi ({okunan_bakiye:.2f} USDT). Kasa 10000.0 $ olarak HARD-RESET atıldı!")
            SANAL_KRIPTO_KASA = 10000.0
        else:
            SANAL_KRIPTO_KASA = okunan_bakiye
except:
    SANAL_KRIPTO_KASA = 10000.0

def sanal_crypto_kasa_kaydet():
    try:
        with open(SANAL_KASA_DOSYASI, 'w') as f:
            json.dump({'bakiye': SANAL_KRIPTO_KASA}, f)
    except: pass

# Bot başlarken pırıl pırıl son halini mühürle
sanal_crypto_kasa_kaydet()
SANAL_KRIPTO_POZISYONLAR = {}
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
        borsa = ccxt.binance(borsa_config)
        borsa.enable_demo_trading(True)
        borsa.load_markets()
        scout_borsa = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})
    except Exception as e:
        print(f"[!] Borsa bağlantısı yenilenemedi: {e}")

def telegrama_gonder(mesaj):
    if not TELEGRAM_AYAR["aktif_mi"]: return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_AYAR['bot_token']}/sendMessage", 
                      data={"chat_id": TELEGRAM_AYAR['chat_id'], "text": mesaj, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def islem_ac(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, margin_override=None, ai_guven_skoru=0.0):
    global SANAL_KRIPTO_KASA, SANAL_KRIPTO_POZISYONLAR, ALIM_SATIM_TETIGI_ACIK, PING_MODU, COOLDOWN_DICT
    
    # 1. DEMO İŞLEM (LOKAL SANAL MOTOR) - Her zaman açık!
    try:
        # --- COOLDOWN KONTROLÜ (Aynı koine hemen geri girmeyi engelle) ---
        simdi = datetime.now()
        if sembol in COOLDOWN_DICT:
            gecen = (simdi - COOLDOWN_DICT[sembol]).total_seconds()
            if gecen < 300: # 5 Dakika Cooldown
                return
            else:
                del COOLDOWN_DICT[sembol]
        
        if len(SANAL_KRIPTO_POZISYONLAR) >= 7:
            return  # DEMO Max 7 İşlem Sınırı
            
        if sembol not in SANAL_KRIPTO_POZISYONLAR:
            # 1. Sabit İşlem Büyüklüğü (Lot Size Normalizasyonu)
            islem_boyutu = 11.5 # Maksimum bütçe
            
            # 2. Fizik Kuralı: Gerçek dünyadaki adet (Kaldıraç Çarpanı YOK)
            anlik_fiyat = float(anlik_fiyat)
            miktar = float(f"{islem_boyutu / anlik_fiyat:.6f}")
            
            atr_mesafe = abs(anlik_fiyat - hesaplanan_sl)
            volatilite_yuzde = (atr_mesafe / anlik_fiyat) * 100
            hedef_callback = max(0.5, min(4.0, 3.0 / max(0.1, volatilite_yuzde)))
            
            if "YÜKSELİŞ" in yon:
                islem_yonu = 'LONG'
                scale_out = anlik_fiyat + (atr_mesafe * 1.5)
            else:
                islem_yonu = 'SHORT'
                scale_out = anlik_fiyat - (atr_mesafe * 1.5)
                
            SANAL_KRIPTO_POZISYONLAR[sembol] = {
                'yon': islem_yonu, 'giris': anlik_fiyat, 'miktar': miktar,
                'hedef': hesaplanan_tp, 'zayiat': hesaplanan_sl,
                'scale_out': scale_out, 'scale_out_done': False,
                'tsl_guncel_en_iyi': anlik_fiyat, 'tsl_rate': hedef_callback / 100.0,
                'guven_skoru': ai_guven_skoru, 'margin': islem_boyutu
            }
            print(f"POZİSYON [DEMO-SANAL]: {sembol} | YÖN: {islem_yonu} | GİRİŞ: {anlik_fiyat} | SL: {hesaplanan_sl:.4f} | Scale-Out: {scale_out:.4f}")
            sanal_crypto_kasa_kaydet()
    except Exception as e:
        print(f"[!] DEMO İzole Hata ({sembol}): {e}")

    # 2. LIVE İŞLEM - Güvenlik Kilidine Tabi!
    if LIVE_API_KEY and LIVE_SECRET:
        if not ALIM_SATIM_TETIGI_ACIK:
            if PING_MODU and sembol == 'FDUSD/USDT':
                print(f"[{sembol}] ⚠️ PING MODU ONAYI: Mikro LIVE test işlemine izin veriliyor...")
            else:
                return # Canlı işlem tetiği kapalı!
        
        try:
            try: bakiye_bilgisi = borsa_live.fetch_balance()
            except: bakiye_bilgisi = {}
            toplam_kasa = float(bakiye_bilgisi.get('USDT', {}).get('total', 0.0))
            
            if toplam_kasa >= 10.5:
                _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, borsa_live, "LIVE", True, margin_override, ai_guven_skoru)
        except Exception as e:
            hata_mesaji = str(e)
            if "-2010" in hata_mesaji or "insufficient balance" in hata_mesaji.lower():
                print(f"[LIVE-UYARI] Bakiye yetersiz, LIVE işlem iptal.")
            else:
                print(f"[!] LIVE İzole Hata ({sembol}): {e}")

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
            kullanilacak_margin = min(11.5, toplam_kasa * 0.9)  # Max 11.5 USDT Fix
            kaldirac_orani = 2  # Güvenlik için Sanal ile aynı (2x)
            risk_metni = "LIVE 11.5 USDT Hard Limit (2x)"
        else:
            if margin_override is not None:
                margin_yuzdesi = margin_override
                kaldirac_orani = 2 
                risk_metni = f"Özel Kasa ({margin_override*100:.1f}%)"
            elif toplam_kasa > 4000.0:
                margin_yuzdesi = 0.10 
                kaldirac_orani = 5    
                risk_metni = "%10 (Agresif Mod)"
            else:
                margin_yuzdesi = 0.03 
                kaldirac_orani = 2    
                risk_metni = "%3 (Muhafazakar Mod)"
            kullanilacak_margin = toplam_kasa * margin_yuzdesi
            
        # 1. Kaldıraç Ayarlama
        try:
            borsa_istemci.set_leverage(kaldirac_orani, sembol)
        except Exception:
            pass

        kaldirac = kaldirac_orani
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
                
                # --- ATR Tabanlı Dinamik Ana Stop (Sabit % limitlerinden kurtarıldı) ---
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(gerceklesen_fiyat - sl_fiyat)
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                
                # --- Kısmi Kâr Alma (Scale Out - 1.5 ATR) ---
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat + (atr_mesafe * 1.5)))
                miktar_yari = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.5))
                kalan_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar - miktar_yari))
                
                # Volatilite yüksekse (örn %5) callback_rate düşer (%0.6), düşükse (örn %1) artar (%3.0)
                hedef_callback = 3.0 / max(0.1, volatilite_yuzde)
                callback_rate = round(hedef_callback, 1)
                callback_rate = max(0.5, min(4.0, callback_rate))
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                for deneme in range(max_deneme):
                    try:
                        # 1. ATR Tabanlı Hard Stop (Tüm miktar)
                        borsa_istemci.create_order(symbol=sembol, type='STOP_MARKET', side='sell', amount=miktar, params={'stopPrice': sl_fiyat, 'reduceOnly': True})
                        # 2. Scale Out (%50 Kâr Al, 1.5 ATR mesafesinde)
                        if miktar_yari > 0:
                            borsa_istemci.create_order(symbol=sembol, type='TAKE_PROFIT_MARKET', side='sell', amount=miktar_yari, params={'stopPrice': scale_out_fiyat, 'reduceOnly': True})
                        # 3. İz Süren Stop (Geri kalan %50 için)
                        if kalan_miktar > 0:
                            borsa_istemci.create_order(symbol=sembol, type='TRAILING_STOP_MARKET', side='sell', amount=kalan_miktar, params={'callbackRate': callback_rate, 'reduceOnly': True})
                        
                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: LONG | GİRİŞ: {gerceklesen_fiyat} | TSL: %{callback_rate} | ATR-SL: {sl_fiyat} | Scale-Out: {scale_out_fiyat} | ZIRH: ONAYLI")
                        try:
                            kasa = borsa_istemci.fetch_balance().get('USDT', {}).get('total', '?')
                            if isinstance(kasa, float): kasa = f"{kasa:.2f}"
                            print(f"GÜNCEL KASA: {kasa} USDT")
                        except: pass
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if "-4130" in hata_msg:
                            print(f"POZİSYON: {sembol} | LONG | GİRİŞ: {gerceklesen_fiyat} | ZIRH: Zaten Mevcut")
                            break
                        elif "-4136" in hata_msg:
                            print(f"[!] {sembol} TSL strateji uyumsuz (-4136), zırhlar eklendi.")
                            break
                        elif ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Zırh Hatası: {hata_msg}")
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
                
                # --- ATR Tabanlı Dinamik Ana Stop (Sabit % limitlerinden kurtarıldı) ---
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(sl_fiyat - gerceklesen_fiyat)
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                
                # --- Kısmi Kâr Alma (Scale Out - 1.5 ATR) ---
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat - (atr_mesafe * 1.5)))
                miktar_yari = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.5))
                kalan_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar - miktar_yari))
                
                # Volatilite yüksekse (örn %5) callback_rate düşer (%0.6), düşükse (örn %1) artar (%3.0)
                hedef_callback = 3.0 / max(0.1, volatilite_yuzde)
                callback_rate = round(hedef_callback, 1)
                callback_rate = max(0.5, min(4.0, callback_rate))
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                for deneme in range(max_deneme):
                    try:
                        # 1. ATR Tabanlı Hard Stop
                        borsa_istemci.create_order(symbol=sembol, type='STOP_MARKET', side='buy', amount=miktar, params={'stopPrice': sl_fiyat, 'reduceOnly': True})
                        # 2. Scale Out (%50 Kâr Al, 1.5 ATR)
                        if miktar_yari > 0:
                            borsa_istemci.create_order(symbol=sembol, type='TAKE_PROFIT_MARKET', side='buy', amount=miktar_yari, params={'stopPrice': scale_out_fiyat, 'reduceOnly': True})
                        # 3. İz Süren Stop (Geri kalan %50)
                        if kalan_miktar > 0:
                            borsa_istemci.create_order(symbol=sembol, type='TRAILING_STOP_MARKET', side='buy', amount=kalan_miktar, params={'callbackRate': callback_rate, 'reduceOnly': True})
                        
                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: SHORT | GİRİŞ: {gerceklesen_fiyat} | TSL: %{callback_rate} | ATR-SL: {sl_fiyat} | Scale-Out: {scale_out_fiyat} | ZIRH: ONAYLI")
                        try:
                            kasa = borsa_istemci.fetch_balance().get('USDT', {}).get('total', '?')
                            if isinstance(kasa, float): kasa = f"{kasa:.2f}"
                            print(f"GÜNCEL KASA: {kasa} USDT")
                        except: pass
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if "-4130" in hata_msg:
                            print(f"POZİSYON: {sembol} | SHORT | GİRİŞ: {gerceklesen_fiyat} | ZIRH: Zaten Mevcut")
                            break
                        elif "-4136" in hata_msg:
                            print(f"[!] {sembol} TSL strateji uyumsuz (-4136), zırhlar eklendi.")
                            break
                        elif ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Zırh Hatası: {hata_msg}")
                            break
            except Exception as e:
                print(f"[{zaman}] İŞLEM/ZIRH BAŞARISIZ ({sembol}): {e}")
            
    except Exception as e:
        raise e

def analiz_motoru(hedef_coin, beyin):
    # ── Değişken Sızıntısı Önleme ──
    guncel = None
    hedef_fiyat = None
    tahmin_olasilik = None
    yon = None
    df = None
    sl, tp, rr = 0, 0, 0
    btc_dom = 50.0  

    try:
        if makro_volatilite_beklentisi():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [SİSTEM] Beklemede (Önemli Makro Veri).")
            return

        try:
            df = veri_getir_dortlu(hedef_coin, REF)
        except Exception:
            return

        if df is None or df.empty:
            return

        features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']
        eksik = [f for f in features if f not in df.columns]
        if eksik:
            return

        try:
            tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧠 {hedef_coin} modeli eğitiliyor...")
                beyin.model_egit(hedef_coin, df, is_crypto=True)
                tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            
            if tahmin_olasilik is None:
                return
        except Exception:
            return

        guncel = float(df['Hedef_Close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1])

        volatilite_katsayisi = (atr / guncel) * 100 
        dinamik_esik = 0.53 + (volatilite_katsayisi * 0.02)
        dinamik_esik = min(0.60, max(0.53, dinamik_esik))

        if tahmin_olasilik > dinamik_esik:
            yon = "YÜKSELİŞ 🚀"
        elif tahmin_olasilik < (1.0 - dinamik_esik):
            yon = "DÜŞÜŞ 📉"
        else:
            yon = "NÖTR ⚖️"
        
        # --- Dinamik Risk Yönetimi (ATR 1.5x) ---
        tp_mult = RISK_AYAR["tp_atr_carpani"]
        
        if "YÜKSELİŞ" in yon:
            sl = guncel - (atr * 1.5)
            tp = guncel + (atr * tp_mult)
            rr = (tp - guncel) / (guncel - sl) if (guncel - sl) != 0 else 0
        elif "DÜŞÜŞ" in yon:
            sl = guncel + (atr * 1.5)
            tp = guncel - (atr * tp_mult)
            rr = (guncel - tp) / (sl - guncel) if (sl - guncel) != 0 else 0

        zaman = datetime.now().strftime('%H:%M:%S')
        hedef_fiyat = tp if tp != 0 else guncel
        
        guven_skoru_yuzde = tahmin_olasilik * 100
        if "DÜŞÜŞ" in yon:
            guven_skoru_yuzde = 100 - (tahmin_olasilik * 100)

        if "NÖTR" not in yon:
            if rr >= 1.4:
                print(f"[{zaman}] [{hedef_coin}] Güven: %{guven_skoru_yuzde:.1f} | Dinamik Eşik: %{dinamik_esik*100:.1f} -> DURUM: GİRİŞ UYGUN ({yon})")
            else:
                print(f"[{zaman}] [{hedef_coin}] Güven: %{guven_skoru_yuzde:.1f} | Dinamik Eşik: %{dinamik_esik*100:.1f} -> DURUM: R/R YETERSİZ ({rr:.2f} < 1.4)")

            try:
                btc_dom_req = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
                btc_dom = float(btc_dom_req.json()["data"]["market_cap_percentage"]["btc"])
            except:
                pass 

        if "NÖTR" not in yon and rr >= 1.4:
            fg_skor, _ = korku_acgozluluk_getir()
            korku_limiti = 10 if dinamik_esik < 0.58 else 18 
            
            if fg_skor < korku_limiti and "YÜKSELİŞ" in yon:
                return

            # --- 1. Makro Trend Filtresi (Kesin Kurallar) ---
            ana_trend_yon = ana_trend_getir(hedef_coin)
            if "YÜKSELİŞ" in yon and ana_trend_yon != "UP":
                print(f"[{zaman}] 🚫 Makro Trend Reddi: {hedef_coin} (4H: {ana_trend_yon}). LONG işlemi İPTAL!")
                return
            if "DÜŞÜŞ" in yon and ana_trend_yon != "DOWN":
                print(f"[{zaman}] 🚫 Makro Trend Reddi: {hedef_coin} (4H: {ana_trend_yon}). SHORT işlemi İPTAL!")
                return

            # --- 2. Yatay Piyasa Kalkanı (Choppy / Squeeze) ---
            son_chop = df['CHOP'].iloc[-1] if 'CHOP' in df.columns else 50.0
            sqz_on = df['Squeeze_ON'].iloc[-1] if 'Squeeze_ON' in df.columns else 0.0
            
            if son_chop > 61.8:
                print(f"[{zaman}] 🛑 Yatay Piyasa Reddi: {hedef_coin} Testere/Yönsüz Piyasa (CHOP: {son_chop:.1f} > 61.8).")
                return
                
            if sqz_on > 0:
                print(f"[{zaman}] 🛑 Sıkışma Reddi: {hedef_coin} Squeeze(ON) Rejiminde. Fiyatın patlaması bekleniyor.")
                return

            # --- 3. Dinamik Güven Skoru (Momentum + Hacim + RSI) ---
            son_rsi = df['RSI'].iloc[-1] if 'RSI' in df.columns else 50
            son_macd = df['MACD'].iloc[-1] if 'MACD' in df.columns else 0
            onceki_macd = df['MACD'].iloc[-2] if 'MACD' in df.columns else 0
            
            if 'volume' in df.columns:
                hacim_sma = df['volume'].rolling(window=10).mean().iloc[-1]
                son_hacim = df['volume'].iloc[-1]
                if son_hacim < (hacim_sma * 0.8):
                    print(f"[{zaman}] ⚠️ Hacim Zayıf: {hedef_coin} İşlem reddedildi.")
                    return

            if "YÜKSELİŞ" in yon:
                if son_rsi > 70 or son_macd <= onceki_macd:
                    print(f"[{zaman}] ⚠️ Mutabakat Yok: {hedef_coin} LONG iptal (RSI: {son_rsi:.1f}, MACD Zayıf).")
                    return
            elif "DÜŞÜŞ" in yon:
                if son_rsi < 30 or son_macd >= onceki_macd:
                    print(f"[{zaman}] ⚠️ Mutabakat Yok: {hedef_coin} SHORT iptal (RSI: {son_rsi:.1f}, MACD Zayıf).")
                    return
            
            margin_override = None
            if btc_dom > 56.0 and "BTC" not in hedef_coin:
                if guven_skoru_yuzde < 70.0:
                    return
                else:
                    margin_override = 0.02

            p_kelly = tahmin_olasilik if "YÜKSELİŞ" in yon else (1.0 - tahmin_olasilik)
            q_kelly = 1.0 - p_kelly
            b_kelly = rr
            
            kelly_orani = 0.0
            if b_kelly > 0:
                kelly_orani = (p_kelly * b_kelly - q_kelly) / b_kelly
            
            # --- Dinamik Bütçe Yönetimi: Güven Skoruna Göre Çarpan ---
            if guven_skoru_yuzde >= 70.0:
                kelly_carpan = 1.5
            elif guven_skoru_yuzde >= 60.0:
                kelly_carpan = 1.0
            else:
                kelly_carpan = 0.5
            
            fractional_kelly = max(0.01, min(0.20, kelly_orani * 0.25 * kelly_carpan)) 
            
            if margin_override is not None:
                margin_override = min(0.02, fractional_kelly)
            else:
                margin_override = fractional_kelly

            print(f"[{zaman}] 📐 Dinamik Risk Hesaplandı -> Önerilen Pozisyon Büyüklüğü: Kasanın %{margin_override*100:.1f}'i (Güven: %{guven_skoru_yuzde:.1f})")

            msg = f"🚨 *FIRSAT: {hedef_coin}*\n----------------\n🔮 Yön: {yon}\n📈 Güven: %{guven_skoru_yuzde:.1f} (Carpan: {kelly_carpan}x)\n💰 Fiyat: {guncel:.2f}$\n🎯 S.Out: +1.5 ATR\n🛑 Stop: ATR Tabanlı\n⚖️ R/R: {rr:.2f}\n📊 Bütçe: %{margin_override*100:.1f}\n😨 Piyasa: {fg_skor}\n👑 BTC Dom: %{btc_dom:.1f}"
            telegrama_gonder(msg)
            
            islem_ac(yon, hedef_coin, guncel, tp, sl, margin_override, guven_skoru_yuzde)

    except ccxt.NetworkError as ne:
        borsa_baglantisini_yenile(hata_mesaji="Network Error")
    except Exception as e:
        if "ccxt" in str(e).lower() or "binance" in str(e).lower() or "timeout" in str(e).lower():
            borsa_baglantisini_yenile(hata_mesaji="Bilinmeyen CCXT Hatası")

def surekli_tarama_ve_analiz():
    beyin = BeyinMotoru()
    
    while True:
        try:
            print("\n" + "="*70)
            print(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] AŞAMA 1: SCOUT (Hafif Tarayıcı) Başlıyor...")
            
            # Public (non-testnet) API ile TÜM Binance Futures USDT paritelerini çek
            tikler = scout_borsa.fetch_tickers()
            
            # -------------------------------------------------------------
            # LOKAL DEMO BİLGİ GÜNCELLEMESİ (Sadece referanslar temizlendi, asıl kontrol UI Loop'unda)
            # -------------------------------------------------------------
            acik_semboller = list(SANAL_KRIPTO_POZISYONLAR.keys())
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
                    # Futures formatı BTC/USDT:USDT -> Spot formatı BTC/USDT'ye çevir
                    temiz_sembol = sembol.replace(':USDT', '')
                    # Spot API'de mevcut mu? (Analiz motoru Spot'tan veri çeker)
                    if SPOT_SEMBOLLER and temiz_sembol not in SPOT_SEMBOLLER:
                        continue
                    adaylar.append({'sembol': temiz_sembol, 'hacim': hacim, 'degisim': degisim})
            
            adaylar.sort(key=lambda x: x['degisim'], reverse=True)
            sicak_coinler = [x['sembol'] for x in adaylar[:100]]
            
            # --- DURUM BİLGİSİ ---
            if not ALIM_SATIM_TETIGI_ACIK:
                if PING_MODU:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: PİNG MODU (Sadece FDUSD)]")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: KAPALI (Güvenlik Kilidi)]")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔥 [LIVE: AKTİF] - GERÇEK PARA İŞLEM TETİĞİ ONAYLANDI!")
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Dinamik Tarayıcı: Piyasadan seçilen en sıcak coinler:")
            for i, coin in enumerate(sicak_coinler, 1):
                aday = next((a for a in adaylar if a['sembol'] == coin), None)
                if aday:
                    print(f"  {i:2d}. {coin:<12} | Hacim: ${aday['hacim']/1e6:.0f}M | Değişim: %{aday['degisim']:.1f}")
            
            print(f"\n🎯 AŞAMA 2: SNIPER (Ağır Analiz) Başlıyor...")
            for coin in sicak_coinler:
                if coin in acik_semboller:
                    print(f"  ⏭️ {coin} zaten açık pozisyonda, atlanıyor.")
                    continue
                    
                analiz_motoru(coin, beyin)
                time.sleep(3) 
                
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            print(f"[{zaman}] ⚠️ Tarayıcı Hatası: {e}")
            borsa_baglantisini_yenile("Scout Hatası")
            time.sleep(10)
            
        print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Tarama döngüsü tamamlandı, 5 dakika bekleniyor...")
        time.sleep(300)

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
        print(f"👁️‍🗨️ [KÖRLÜK KALKANI] API Hatası veya Gecikme: {e}. Pozisyonlar korundu ve açık varsayılacak!")
        return False # API Hatası

def pozisyon_takip_paneli():
    global onceki_pozisyonlar, performans, SANAL_KRIPTO_KASA, SANAL_KRIPTO_POZISYONLAR, COOLDOWN_DICT
    while True:
        try:
            aktifler = []
            mevcut_semboller = set()
            
            # REST APİ Yerine WSS (WebSocket) Veri Nehrinden anlık çek
            tum_tikler = WSS_TICKERS
            
            # --- DEMO: SANAL KRİPTO POZİSYONLARI ---
            for sym, poz in list(SANAL_KRIPTO_POZISYONLAR.items()):
                try: 
                    # Güvenli Ticker Arama (WSS'den direkt)
                    temiz_sym = sym.replace(':USDT', '')
                    guncel = tum_tikler.get(f"{temiz_sym}/USDT") or tum_tikler.get(temiz_sym) 
                    
                    if not guncel:
                        try: guncel = float(ui_borsa.fetch_ticker(f"{temiz_sym}/USDT")['last'])
                        except:
                            try: guncel = float(ui_borsa.fetch_ticker(temiz_sym)['last'])
                            except: guncel = float(poz['giris'])
                    else:
                        guncel = float(guncel)
                    
                    # --- SANAL KRİPTO POZİSYON KONTROLÜ (UI Loop'una taşındı) ---
                    kapanma_fiyati = 0
                    sebep = ""
                    anlik = guncel
                    
                    if poz['yon'] == 'LONG':
                        if anlik > poz['tsl_guncel_en_iyi']: poz['tsl_guncel_en_iyi'] = anlik
                        dinamik_tsl_rate = poz['tsl_rate'] / 2.0 if poz['scale_out_done'] else poz['tsl_rate']
                        tsl_tetik = poz['tsl_guncel_en_iyi'] * (1.0 - dinamik_tsl_rate)
                        if poz['scale_out_done']: tsl_tetik = max(tsl_tetik, poz['giris'] * 1.002) # Kârda kalma garantisi

                        if not poz['scale_out_done'] and anlik >= poz['scale_out']:
                            net_kar_yuzde = ((anlik - poz['giris']) / poz['giris']) * 100 * 10.0 # 10x
                            if net_kar_yuzde >= 0.5:
                                poz['scale_out_done'] = True
                                kar_brut = (anlik - poz['giris']) * (poz['miktar'] / 2)
                                SANAL_KRIPTO_KASA += kar_brut
                                poz['miktar'] = poz['miktar'] / 2
                                print(f"✨ [SCALE-OUT] {sym} %50 Kâr Alındı. Yeni Kasa: {SANAL_KRIPTO_KASA:.2f}$")
                            
                        if anlik >= poz['hedef']:
                            net_kar_yuzde = ((anlik - poz['giris']) / poz['giris']) * 100 * 10.0
                            if net_kar_yuzde >= 0.5:
                                kapanma_fiyati = poz['hedef']
                                sebep = "TAKE PROFIT"
                        elif anlik <= tsl_tetik or anlik <= poz['zayiat']:
                            kapanma_fiyati = anlik
                            sebep = "STOP/TSL"
                    else: # SHORT
                        if anlik < poz['tsl_guncel_en_iyi']: poz['tsl_guncel_en_iyi'] = anlik
                        dinamik_tsl_rate = poz['tsl_rate'] / 2.0 if poz['scale_out_done'] else poz['tsl_rate']
                        tsl_tetik = poz['tsl_guncel_en_iyi'] * (1.0 + dinamik_tsl_rate)
                        if poz['scale_out_done']: tsl_tetik = min(tsl_tetik, poz['giris'] * 0.998)
                        
                        if not poz['scale_out_done'] and anlik <= poz['scale_out']:
                            net_kar_yuzde = ((poz['giris'] - anlik) / poz['giris']) * 100 * 10.0
                            if net_kar_yuzde >= 0.5:
                                poz['scale_out_done'] = True
                                kar_brut = (poz['giris'] - anlik) * (poz['miktar'] / 2)
                                SANAL_KRIPTO_KASA += kar_brut
                                poz['miktar'] = poz['miktar'] / 2
                                print(f"✨ [SCALE-OUT] {sym} %50 Kâr Alındı. Yeni Kasa: {SANAL_KRIPTO_KASA:.2f}$")
                            
                        if anlik <= poz['hedef']:
                            net_kar_yuzde = ((poz['giris'] - anlik) / poz['giris']) * 100 * 10.0
                            if net_kar_yuzde >= 0.5:
                                kapanma_fiyati = poz['hedef']
                                sebep = "TAKE PROFIT"
                        elif anlik >= tsl_tetik or anlik >= poz['zayiat']:
                            kapanma_fiyati = anlik
                            sebep = "STOP/TSL"

                    if kapanma_fiyati > 0:
                        kar_brut = (kapanma_fiyati - poz['giris']) * poz['miktar']
                        kar = kar_brut if poz['yon'] == 'LONG' else -kar_brut
                        
                        # --- PNL FİZİKSEL SİGORTA KALKANI ---
                        guncel_islem_butcesi = poz.get('margin', 11.5)
                        if kar < -guncel_islem_butcesi:
                            kar = -guncel_islem_butcesi
                            sebep = f"LİKİDASYON (-{guncel_islem_butcesi}$ SİGORTASI)"
                            
                        SANAL_KRIPTO_KASA += kar
                        sanal_crypto_kasa_kaydet()
                        COOLDOWN_DICT[sym] = datetime.now() # Cooldown başlat
                        if sym in SANAL_KRIPTO_POZISYONLAR: del SANAL_KRIPTO_POZISYONLAR[sym]
                        
                        if kar > 0: performans['kazanc'] += 1
                        else: performans['kayip'] += 1
                        islem_kaydet(sym, 'DEMO', poz['yon'], poz['giris'], kapanma_fiyati, kar, (kar/poz['margin'])*100, poz['guven_skoru'])
                        print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 KAPANIŞ [DEMO-SANAL]: {sym} | Sebep: {sebep} | K/Z: {kar:+.2f}$ | Yeni Kasa: {SANAL_KRIPTO_KASA:.2f}$")
                        continue # Pozisyon kapandı, aktifler listesine ekleme.

                except Exception as e: 
                    guncel = float(poz['giris'])
                
                pnl = (guncel - poz['giris']) * poz['miktar'] if poz['yon'] == 'LONG' else (poz['giris'] - guncel) * poz['miktar']
                p = {
                    'symbol': sym,
                    'markPrice': guncel,
                    'info': {'positionAmt': poz['miktar'], 'entryPrice': poz['giris'], 'markPrice': str(guncel)},
                    'unrealizedPnl': pnl,
                    'contracts': poz['miktar'],
                    'entryPrice': poz['giris'],
                    'positionSide': poz['yon'],
                    'Hesap_Tipi': 'DEMO'
                }
                aktifler.append((p, poz['miktar']))
                mevcut_semboller.add(f"{sym}_DEMO")

            # --- LIVE: GERÇEK POZİSYONLARI ÇEK ---
            live_api_ok = _hesap_pozisyon_cek(borsa_live, "LIVE", mevcut_semboller, aktifler)
            
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
                        print(f"✅ [{hesap_t}] {eski_sembol} KÂRLA KAPANDI! (Gerçekleşen Fatura: +{gercek_pnl:.2f} USDT)")
                    else:
                        performans['kayip'] += 1
                        print(f"❌ [{hesap_t}] {eski_sembol} ZARARLA KAPANDI! (Gerçekleşen Fatura: {gercek_pnl:.2f} USDT)")
                        
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
                        try: del aktif_islemler_detay[eski_key]
                        except: pass
            
            # Mevcut pozisyonları güncelle
            yeni_pozisyonlar = {}
            
            bakiye_demo = SANAL_KRIPTO_KASA
            
            try: bakiye_live = float(borsa_live.fetch_balance().get('USDT', {}).get('total', 0.0)) if hasattr(borsa_live, 'apiKey') and borsa_live.apiKey else 0.0
            except: bakiye_live = 0.0
            
            print("\n" + "="*50)
            if not aktifler and not SANAL_KRIPTO_POZISYONLAR:
                print(f"⏳ [{datetime.now().strftime('%H:%M:%S')}] Aktif İşlem Yok. Fırsatlar Taranıyor...")
            else:
                print(f"📊 AÇIK POZİSYONLAR | {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 50)
                
                toplam_pnl_demo = 0
                toplam_pnl_live = 0
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
                    
                    # Yön tespiti (Şık bir görsel için)
                    islem_yeri = p.get('positionSide', '').upper()
                    if islem_yeri == 'LONG':
                        yon_str = "🟢 LONG"
                    elif islem_yeri == 'SHORT':
                        yon_str = "🔴 SHORT"
                    else: # Fallback for cases where side is derived from amount
                        yon_str = "🟢 LONG" if amt > 0 else "🔴 SHORT"
                        
                    print(f" [{hesap_t}] {sembol:<12} | {yon_str} | K/Z: {pnl:+.2f} USDT")
                
                print("-" * 50)
                equity_demo = bakiye_demo + toplam_pnl_demo
                equity_live = bakiye_live + toplam_pnl_live
                print(f" 🏦 [DEMO] Kasa: {bakiye_demo:.2f} | K/Z: {toplam_pnl_demo:+.2f} | VARLIK: {equity_demo:.2f}")
                print(f" 🏦 [LIVE] Kasa: {bakiye_live:.2f} | K/Z: {toplam_pnl_live:+.2f} | VARLIK: {equity_live:.2f}")
            
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
    print(f"\n🚀 SİSTEM BAŞLATILIYOR (V8 - Hybrid Execution Çift Hatlı)")
    print(f"🔸 DEMO Bot: AKTİF")
    print(f"🔸 LIVE Bot: {'AKTİF (Max 10 USDT Hard Limit)' if LIVE_API_KEY else 'KAPALI (LIVE API Bulunamadı)'}")
    
    # --- BAŞLANGIÇ CANLI (LIVE) API DR-RUN (BAĞLANTI DOĞRULAMA) ---
    if LIVE_API_KEY and hasattr(borsa_live, 'apiKey') and borsa_live.apiKey:
        print("\n⚙️ [API DRY-RUN] LIVE Cüzdan bağlantısı test ediliyor...")
        try:
            bakiye_bilgisi = borsa_live.fetch_balance()
            canli_bakiye = float(bakiye_bilgisi.get('USDT', {}).get('total', 0.0))
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
        scout_borsa.load_markets() # Statü kontrolü için şart
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
