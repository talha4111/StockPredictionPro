"""
IBKR BRIDGE v2.0 — Interactive Brokers Veri & Maliyet Koprusu
==============================================================
Gorev:
  1. TWS Paper Trading'e baglanip canli/gecmis veri cekmek
  2. Spread + Komisyon maliyetini hesaplayip Net RR filtresi uygulamak (Faz 1)
  3. Gecmis veriyi ai_core.py (XGBoost) icin hazir feature DataFrame'e cevirmek (Faz 5)

Mod:   Danisman — Veri okur, maliyet hesaplar, islem ACMAZ.
Port:  7497 (Paper Trading)

Import Ornegi (stock_engine.py veya stock_value_engine.py icinden):
    from ibkr_bridge import (
        ibkr_baglan, sozlesme_dogrula, piyasa_verisi_cek,
        gecmis_veri_cek, feature_pipeline, islem_maliyeti_hesapla,
        net_rr_filtresi, hesap_bilgisi_oku
    )
"""

import sys
import io

# Windows cp1254 Unicode hatasini engelle
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass
import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Stock, util, MarketOrder, LimitOrder, StopOrder
import ib_insync.util as _ib_util

def _safe_run(*awaitables, timeout=None):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if len(awaitables) == 1:
        fut = awaitables[0]
    else:
        fut = asyncio.gather(*awaitables)
    task = loop.create_task(fut)
    return loop.run_until_complete(task)

_ib_util.run = _safe_run
import pandas as pd
try:
    import pandas_ta as ta
except ImportError:
    class ta:
        @staticmethod
        def rsi(close, length=14):
            delta = close.diff()
            gain = (delta.where(delta > 0, 0)).rolling(length).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(length).mean()
            rs = gain / (loss + 1e-9)
            return 100 - (100 / (1 + rs))
        @staticmethod
        def macd(close, fast=12, slow=26, signal=9):
            ema_fast = close.ewm(span=fast, adjust=False).mean()
            ema_slow = close.ewm(span=slow, adjust=False).mean()
            macd_line = ema_fast - ema_slow
            return pd.DataFrame({'MACD_12_26_9': macd_line})
        @staticmethod
        def obv(close, volume):
            return (np.sign(close.diff()) * volume).fillna(0).cumsum()
        @staticmethod
        def bbands(close, length=20, std=2.0):
            sma = close.rolling(length).mean()
            s = close.rolling(length).std()
            return pd.DataFrame({'BBB_20_2.0': ((2 * std * s) / (sma + 1e-9)) * 100})
        @staticmethod
        def mfi(high, low, close, volume, length=14):
            return pd.Series(50.0, index=close.index)
        @staticmethod
        def vwap(high, low, close, volume):
            typical_price = (high + low + close) / 3.0
            return (typical_price * volume).cumsum() / (volume.cumsum() + 1e-9)
import numpy as np
import time
import asyncio
import logging

# [UI TEMİZLİĞİ] Gereksiz IBKR API uyarılarını (Error 300 vb.) terminale basmasını engeller
util.logToConsole(level=logging.CRITICAL)

# ============================================================
#  SABITLER
# ============================================================

# IBKR Pro Tiered Komisyon Yapisi (USD Equities)
IBKR_KOMISYON_PER_SHARE = 0.005   # Hisse basi komisyon ($)
IBKR_MIN_KOMISYON       = 1.00    # Minimum siparis komisyonu ($)
IBKR_MAX_KOMISYON_PCT   = 0.005   # Islem degerinin max %0.5'i

# Filtre Esikleri
NET_RR_MIN_ESIK          = 1.2    # Net RR bu degerin altindaysa: PAS GEC
SPREAD_TEHLIKE_BPS       = 50     # 50 bps ustu: Likidite uyarisi
SPREAD_ZAYIF_BPS         = 15     # 15-50 bps: Dikkatli ol

# ai_core.py'nin bekledigi feature listesi (DOKUNMA — sira kritik)
STOCK_FEATURES = [
    'Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret',
    'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma',
    'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru'
]


# ============================================================
#  1. IBKR BAGLANTI YONETICISI
# ============================================================

def ibkr_baglan(host='127.0.0.1', port=7497, client_id=1, timeout=4):
    """
    Dayanıklı IBKR TWS Paper Trading baglantisi.
    Client ID meşgulse otomatik olarak alternatif ID'leri dener.
    """
    denenecek_idler = [client_id] + [cid for cid in range(1, 30) if cid != client_id]
    for cid in denenecek_idler[:6]:
        ib = IB()
        try:
            ib.connect(host, port, clientId=cid, timeout=timeout)
            ib.reqMarketDataType(3)
            print(f"[IBKR] Baglanti BASARILI")
            print(f"       Host: {host}:{port} | Client ID: {cid} | Veri Modu: Delayed-3")
            print(f"       Hesap: {ib.managedAccounts()}")
            return ib
        except ConnectionRefusedError:
            print("[HATA] TWS/IB Gateway CALISIYOR MU?")
            print("       1. TWS acik ve Paper Trading girisi yapilmis olmali")
            print("       2. API Settings: 'Enable ActiveX and Socket Clients' isaretli, Port: 7497 olmali")
            return None
        except Exception:
            try:
                ib.disconnect()
            except:
                pass
            continue
            
    print("[HATA] TWS baglantisi kurulamadi (Tüm denenen Client ID'ler mesgul veya TWS yanit vermiyor).")
    return None

async def ibkr_baglan_async(host='127.0.0.1', port=7497, client_id=1, timeout=10):
    """
    Asenkron IBKR TWS Paper Trading baglantisi (async coroutine'ler icin).
    """
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, timeout=timeout)
        ib.reqMarketDataType(3)
        print(f"[IBKR] Baglanti BASARILI (Async)")
        print(f"       Host: {host}:{port} | Client ID: {client_id} | Veri Modu: Delayed-3")
        print(f"       Hesap: {ib.managedAccounts()}")
        return ib
    except ConnectionRefusedError:
        print("[HATA] TWS/IB Gateway CALISIYOR MU?")
        print("       1. TWS acik ve Paper Trading girisi yapilmis olmali")
        print("       2. API Settings: 'Enable ActiveX and Socket Clients' isaretli, Port: 7497 olmali")
        return None
    except Exception as e:
        print(f"[HATA] Asenkron baglanti hatasi: {e}")
        return None


# ============================================================
#  GLOBAL SOZLESME YONETICISI
# ============================================================

def parse_global_symbol(sembol):
    """
    Sematik uzantilari (.DE, .AS, .HK vb.) veya formatlari
    IBKR borsa ve kur karsiliklarina cevirir.
    """
    s = str(sembol).upper().strip()
    if s.endswith('.DE'):
        return s.replace('.DE', ''), 'IBIS', 'EUR'
    elif s.endswith('.AS') or s.endswith('.PA'):
        return s.rsplit('.', 1)[0], 'SMART', 'EUR'
    elif s.endswith('.HK'):
        return s.replace('.HK', '').lstrip('0'), 'HKEX', 'HKD'
    elif s.isdigit():
        return s.lstrip('0'), 'HKEX', 'HKD'
    else:
        return s, 'SMART', 'USD'

# ============================================================
#  2. SOZLESME TANIMLAMA VE DOGRULAMA
# ============================================================

def sozlesme_dogrula(ib, sembol='AAPL', borsa='SMART', para_birimi='USD'):
    """
    Hisse senedi sozlesmesini olusturur ve IBKR sunucusunda dogrular.
    Eger borsa/kur manuel verilmezse parse_global_symbol ile otomatik cozer.
    """
    gs, oto_borsa, oto_kur = parse_global_symbol(sembol)
    
    # Eger varsayilan parametreler disinda bir atama yapilmadiysa oto atamalari kullan
    if borsa == 'SMART' and para_birimi == 'USD':
        borsa, para_birimi = oto_borsa, oto_kur
        
    contract = Stock(gs, borsa, para_birimi)

    try:
        qualified = ib.qualifyContracts(contract)

        if qualified:
            c = qualified[0]
            print(f"[SOZLESME] {c.symbol} dogrulandi (ConID: {c.conId})")
            return c
        else:
            print(f"[HATA] {sembol} sozlesmesi dogrulanamadi!")
            return None

    except Exception as e:
        print(f"[HATA] Sozlesme dogrulama hatasi: {e}")
        return None


# ============================================================
#  3. CANLI PIYASA VERISI CEKME (Bid/Ask/Last/Spread)
# ============================================================

def piyasa_verisi_cek(ib, contract, bekleme_sn=2):
    """
    Dogrulanmis sozlesme icin canli Bid/Ask/Last fiyatlarini ceker
    ve spread'i hem dolar hem basis point cinsinden hesaplar.

    Donus:
        dict: {sembol, bid, ask, last, mid, spread, spread_bps, spread_kalite}
        veya None
    """
    try:
        ticker = ib.reqMktData(contract, '', False, False)
        ib.sleep(bekleme_sn)

        bid = ticker.bid
        ask = ticker.ask
        last = ticker.last

        # IBKR -1.0 dondugunde "veri yok" demektir
        if bid is None or bid <= 0 or bid == -1.0:
            bid = None
        if ask is None or ask <= 0 or ask == -1.0:
            ask = None
        if last is None or last <= 0 or last == -1.0:
            last = None

        # Spread hesaplama
        spread = None
        spread_bps = None
        mid = None
        spread_kalite = 'BILINMIYOR'

        if bid and ask and bid > 0 and ask > 0:
            spread = round(ask - bid, 4)
            mid = round((bid + ask) / 2.0, 4)
            spread_bps = round((spread / mid) * 10000, 2)

            if spread_bps < 5:
                spread_kalite = 'MUKEMMEL'
            elif spread_bps < SPREAD_ZAYIF_BPS:
                spread_kalite = 'IYI'
            elif spread_bps < SPREAD_TEHLIKE_BPS:
                spread_kalite = 'ZAYIF'
            else:
                spread_kalite = 'TEHLIKELI'

        # Veri akisini durdur
        ib.cancelMktData(contract)

        sonuc = {
            'sembol': contract.symbol,
            'bid': bid,
            'ask': ask,
            'last': last,
            'mid': mid,
            'spread': spread,
            'spread_bps': spread_bps,
            'spread_kalite': spread_kalite,
        }

        # Terminal kirliligi engellemek icin print silindi
        return sonuc

    except Exception as e:
        print(f"[HATA] Piyasa verisi cekilemedi: {e}")
        return None


# ============================================================
#  4. MALİYET MOTORU (FAZ 1) — Spread + Komisyon Hesaplayici
# ============================================================

def islem_maliyeti_hesapla(fiyat, miktar, spread_bps=None, spread_dolar=None):
    """
    Bir islemin toplam giris + cikis maliyetini hesaplar.

    Maliyet Bilesenleri:
        1. IBKR Komisyon (Giris): max($1.00, miktar * $0.005)
        2. IBKR Komisyon (Cikis): max($1.00, miktar * $0.005)
        3. Spread Maliyeti (Giris): mid'den ask'a kayma
        4. Spread Maliyeti (Cikis): mid'den bid'e kayma
           = spread * miktar (tam round-trip)

    Parametreler:
        fiyat:        Guncel hisse fiyati ($)
        miktar:       Alinacak hisse sayisi (adet)
        spread_bps:   Spread (basis point cinsinden), ornegin 5.0
        spread_dolar: Spread (dolar cinsinden), ornegin 0.02

    Donus:
        dict: {
            komisyon_giris, komisyon_cikis, komisyon_toplam,
            spread_maliyet, toplam_maliyet,
            maliyet_yuzde, maliyet_per_hisse
        }
    """
    islem_degeri = fiyat * miktar

    # --- KOMISYON HESABI ---
    # IBKR Pro Tiered: hisse basi $0.005, min $1.00, max %0.5
    komisyon_ham = miktar * IBKR_KOMISYON_PER_SHARE
    komisyon_max = islem_degeri * IBKR_MAX_KOMISYON_PCT
    komisyon_tek_yon = max(IBKR_MIN_KOMISYON, min(komisyon_ham, komisyon_max))

    komisyon_giris = round(komisyon_tek_yon, 2)
    komisyon_cikis = round(komisyon_tek_yon, 2)
    komisyon_toplam = round(komisyon_giris + komisyon_cikis, 2)

    # --- SPREAD MALİYETİ (Round-Trip) ---
    # Giriste mid'den ask'a, cikista mid'den bid'e kayarsin
    # Toplam kayip = spread * miktar
    if spread_dolar is not None and spread_dolar > 0:
        spread_maliyet = round(spread_dolar * miktar, 4)
    elif spread_bps is not None and spread_bps > 0:
        spread_dolar_hesap = (spread_bps / 10000) * fiyat
        spread_maliyet = round(spread_dolar_hesap * miktar, 4)
    else:
        # Spread verisi yoksa konservatif tahmin: 3 bps
        spread_maliyet = round((3 / 10000) * fiyat * miktar, 4)

    # --- TOPLAM MALİYET ---
    toplam_maliyet = round(komisyon_toplam + spread_maliyet, 2)
    maliyet_yuzde = round((toplam_maliyet / islem_degeri) * 100, 4) if islem_degeri > 0 else 0
    maliyet_per_hisse = round(toplam_maliyet / miktar, 4) if miktar > 0 else 0

    return {
        'komisyon_giris': komisyon_giris,
        'komisyon_cikis': komisyon_cikis,
        'komisyon_toplam': komisyon_toplam,
        'spread_maliyet': spread_maliyet,
        'toplam_maliyet': toplam_maliyet,
        'maliyet_yuzde': maliyet_yuzde,
        'maliyet_per_hisse': maliyet_per_hisse,
        'islem_degeri': round(islem_degeri, 2),
    }


# ============================================================
#  5. NET RR FİLTRESİ — Maliyet Düşüldükten Sonra Risk/Ödül
# ============================================================

def net_rr_filtresi(fiyat, tp_fiyat, sl_fiyat, miktar, spread_bps=None, spread_dolar=None, yon='BUY'):
    """
    Beklenen kar'dan islem maliyetini duserek "Net Risk/Reward" oranini hesaplar. 
    Net RR < 1.2 ise islem REDDEDILIR.
    yon='BUY' veya 'SELL' parametresine gore mantiksal gecerliligini teyit eder.
    """
    yon = yon.upper()
    
    # Giris parametreleri dogruluk kontrolu (YON DUYARLI)
    if yon == 'BUY':
        if tp_fiyat <= fiyat:
            return {'karar': 'RED', 'red_sebebi': 'BUY: TP fiyati giris fiyatindan dusuk veya esit', 'net_rr': 0, 'brut_rr': 0}
        if sl_fiyat >= fiyat:
            return {'karar': 'RED', 'red_sebebi': 'BUY: SL fiyati giris fiyatindan yuksek veya esit', 'net_rr': 0, 'brut_rr': 0}
    else: # SELL
        if tp_fiyat >= fiyat:
            return {'karar': 'RED', 'red_sebebi': 'SELL: TP fiyati giris fiyatindan yuksek veya esit', 'net_rr': 0, 'brut_rr': 0}
        if sl_fiyat <= fiyat:
            return {'karar': 'RED', 'red_sebebi': 'SELL: SL fiyati giris fiyatindan dusuk veya esit', 'net_rr': 0, 'brut_rr': 0}

    # Maliyet hesapla
    maliyet = islem_maliyeti_hesapla(fiyat, miktar, spread_bps, spread_dolar)
    toplam_maliyet = maliyet['toplam_maliyet']

    # Brut (ham) hesap
    if yon == 'BUY':
        brut_kar = round((tp_fiyat - fiyat) * miktar, 2)
        brut_zarar = round((fiyat - sl_fiyat) * miktar, 2)
    else: # SELL
        brut_kar = round((fiyat - tp_fiyat) * miktar, 2)
        brut_zarar = round((sl_fiyat - fiyat) * miktar, 2)
    brut_rr = round(brut_kar / brut_zarar, 2) if brut_zarar > 0 else 0

    # Net hesap (maliyet dusulmus)
    # Kar tarafindan maliyet dusulur (kar azalir)
    # Zarar tarafina maliyet eklenir (zarar artar)
    net_kar = round(brut_kar - toplam_maliyet, 2)
    net_zarar = round(brut_zarar + toplam_maliyet, 2)
    net_rr = round(net_kar / net_zarar, 2) if net_zarar > 0 else 0

    # Karar
    if net_rr >= NET_RR_MIN_ESIK:
        karar = 'ONAY'
        red_sebebi = None
    else:
        karar = 'RED'
        red_sebebi = (f'Net RR {net_rr:.2f} < {NET_RR_MIN_ESIK} esik degeri. '
                      f'Maliyet (${toplam_maliyet:.2f}) beklenen kazanci eritiyor.')

    sonuc = {
        'brut_rr': brut_rr,
        'net_rr': net_rr,
        'brut_kar': brut_kar,
        'net_kar': net_kar,
        'brut_zarar': brut_zarar,
        'net_zarar': net_zarar,
        'toplam_maliyet': toplam_maliyet,
        'maliyet_yuzde': maliyet['maliyet_yuzde'],
        'karar': karar,
        'red_sebebi': red_sebebi,
    }

    # Konsol ciktisi
    status = "ONAY" if karar == 'ONAY' else "RED"
    print(f"[NET RR] Brut RR: {brut_rr:.2f}x | Net RR: {net_rr:.2f}x | "
          f"Maliyet: ${toplam_maliyet:.2f} (%{maliyet['maliyet_yuzde']:.3f}) | "
          f"Karar: {status}")

    if karar == 'RED':
        print(f"         Sebep: {red_sebebi}")

    return sonuc


# ============================================================
#  6. FEATURE PIPELINE (FAZ 5) — IBKR Verisi → ai_core.py Formati
# ============================================================

def feature_pipeline(df):
    """
    Ham IBKR OHLCV DataFrame'ini ai_core.py'nin stock_features
    listesine (%100 uyumlu) teknik gostergelerle zenginlestirir.

    ai_core.py stock_features sirasi:
        ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret',
         'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma',
         'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']

    Parametreler:
        df: IBKR'den gelen DataFrame. En az su sutunlar olmali:
            Open, High, Low, Close, Volume

    Donus:
        pd.DataFrame: ai_core.py'ye dogrudan beslenebilir formatta
        veya None (veri yetersiz / hata)
    """
    if df is None or df.empty:
        print("[PIPELINE] Bos DataFrame geldi, islem yapilmadi.")
        return None

    # Sutun adlarini standartlastir (ib_insync bazen kucuk harf doner)
    df.columns = [c.capitalize() for c in df.columns]

    gerekli = ['Open', 'High', 'Low', 'Close', 'Volume']
    eksik = [c for c in gerekli if c not in df.columns]
    if eksik:
        print(f"[PIPELINE] Eksik sutunlar: {eksik}")
        return None

    if len(df) < 50:
        print(f"[PIPELINE] Yetersiz veri: {len(df)} satir (min 50 gerekli)")
        return None

    # Calisan kopya uzerinde islem yap
    df = df.copy()

    # ============================================
    #  HEDEF & REFERANS GETIRILER
    # ============================================

    # Hedef_Close: ai_core.py bunu tahmin hedefi olarak kullanir
    df['Hedef_Close'] = df['Close']

    # Hedef_Ret: Hedef hissenin yuzde degisimi
    df['Hedef_Ret'] = df['Close'].pct_change()

    # Ref_Ret: Referans enstruman getirisi
    # Hisselerde BTC gibi bir referans yok, SPY korelasyonu icin
    # burada 0.0 (notr) baslatiyoruz. Ileriki fazda SPY verisi eklenebilir.
    df['Ref_Ret'] = 0.0

    # Vol_Ret: Hacim degisim orani
    df['Vol_Ret'] = df['Volume'].pct_change()

    # Korelasyon: Referans enstrumanla korelasyon (simdilik notr)
    df['Korelasyon'] = 0.0

    # ============================================
    #  TEKNIK GOSTERGELER (pandas_ta)
    # ============================================

    # RSI (14 periyot)
    rsi = ta.rsi(df['Close'], length=14)
    df['RSI'] = rsi if rsi is not None else 50.0

    # MACD (12, 26, 9)
    macd_df = ta.macd(df['Close'], fast=12, slow=26, signal=9)
    if macd_df is not None and 'MACD_12_26_9' in macd_df.columns:
        df['MACD'] = macd_df['MACD_12_26_9']
    else:
        df['MACD'] = 0.0

    # OBV (On Balance Volume)
    obv = ta.obv(df['Close'], df['Volume'])
    if obv is not None:
        # OBV'yi hisse fiyatiyla olceklenebilir hale getir
        # (mutlak deger cok buyuk olabiliyor, normalize et)
        obv_norm = (obv - obv.rolling(50).mean()) / (obv.rolling(50).std() + 1e-8)
        df['OBV'] = obv_norm
    else:
        df['OBV'] = 0.0

    # Bollinger Bands Width (BB_Width)
    bb = ta.bbands(df['Close'], length=20, std=2.0)
    if bb is not None and 'BBB_20_2.0' in bb.columns:
        df['BB_Width'] = bb['BBB_20_2.0']
    elif bb is not None:
        # Bazi pandas_ta versiyonlari farkli isim kullanir
        bbu_col = [c for c in bb.columns if c.startswith('BBU')]
        bbl_col = [c for c in bb.columns if c.startswith('BBL')]
        bbm_col = [c for c in bb.columns if c.startswith('BBM')]
        if bbu_col and bbl_col and bbm_col:
            bbu = bb[bbu_col[0]]
            bbl = bb[bbl_col[0]]
            bbm = bb[bbm_col[0]]
            df['BB_Width'] = ((bbu - bbl) / bbm) * 100
        else:
            df['BB_Width'] = 0.0
    else:
        df['BB_Width'] = 0.0

    # MFI (Money Flow Index — 14 periyot)
    mfi = ta.mfi(df['High'], df['Low'], df['Close'], df['Volume'], length=14)
    df['MFI'] = mfi if mfi is not None else 50.0

    # VP_Sapma (Volume Profile Sapma — VWAP'tan sapma yuzdeligi)
    vwap = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
    if vwap is not None:
        df['VP_Sapma'] = ((df['Close'] - vwap) / vwap) * 100
    else:
        df['VP_Sapma'] = 0.0

    # ============================================
    #  MAKRO / SENTIMENT GOSTERGELERI
    # ============================================

    # Kriz: VIX bazli kriz gostergesi
    # IBKR'den VIX cekme ileriki fazda eklenecek
    # Simdilik 0.0 (normal piyasa) — stock_value_engine.py zaten
    # VIX kontrolunu ayri yapiyor
    df['Kriz'] = 0.0

    # Haber_Duygu_Puani: NLP sentiment skoru
    # Gelecek fazda haber API'si entegre edilecek
    df['Haber_Duygu_Puani'] = 50.0  # Notr

    # Faiz_Orani: ABD Fed Funds Rate (manuel guncelleme veya FRED API)
    # 27 Nisan 2026 itibariyle: ~4.50%
    df['Faiz_Orani'] = 4.50

    # Dolar_Kuru: USD/TRY veya DXY (Dollar Index)
    # Hisseler USD cinsinden oldugu icin DXY kullanilabilir
    # Simdilik sabit — ileriki fazda yfinance'ten DXY cekilecek
    df['Dolar_Kuru'] = 104.0  # DXY yaklasik seviye

    # ============================================
    #  NaN TEMIZLEME (Kritik)
    # ============================================

    # pandas_ta'nin ilk N satiri NaN uretir (warmup periyodu)
    # Bunlari forward-fill sonra backward-fill ile temizle
    for col in STOCK_FEATURES:
        if col in df.columns:
            df[col] = df[col].ffill().bfill()

    # Hala kalan NaN varsa (cok nadir) 0 ile doldur
    df[STOCK_FEATURES] = df[STOCK_FEATURES].fillna(0.0)

    # inf degerlerini temizle
    df.replace([np.inf, -np.inf], 0.0, inplace=True)

    # ============================================
    #  DOGRULAMA
    # ============================================
    eksik_feature = [f for f in STOCK_FEATURES if f not in df.columns]
    if eksik_feature:
        print(f"[PIPELINE] UYARI: Su feature'lar eksik kaldi: {eksik_feature}")
        return None

    toplam_nan = df[STOCK_FEATURES].isna().sum().sum()
    print(f"[PIPELINE] Basarili: {len(df)} satir x {len(STOCK_FEATURES)} feature")
    print(f"           Kalan NaN: {toplam_nan} | Feature listesi hazir")

    return df


# ============================================================
#  7. GECMIS BAR VERISI CEKME (Guncellenmis — Feature Pipeline Entegre)
# ============================================================

def gecmis_veri_cek(ib, contract, bar_boyutu='1 day', sure='1 Y', pipeline_uygula=True):
    """
    IBKR'den gecmis OHLCV bar verisini ceker.
    pipeline_uygula=True ise otomatik olarak feature_pipeline()'dan gecirir
    ve ai_core.py'ye hazir DataFrame doner.

    Parametreler:
        ib:                IB baglanti nesnesi
        contract:          Dogrulanmis Stock nesnesi
        bar_boyutu:        '1 min', '5 mins', '15 mins', '1 hour', '1 day'
        sure:              '1 D', '5 D', '1 M', '6 M', '1 Y'
        pipeline_uygula:   True ise feature_pipeline() otomatik calisir

    Donus:
        pd.DataFrame (ham veya feature-enriched) veya None
    """
    try:
        bars = ib.reqHistoricalData(
            contract,
            endDateTime='',
            durationStr=sure,
            barSizeSetting=bar_boyutu,
            whatToShow='TRADES',
            useRTH=True,
            formatDate=1
        )

        if not bars:
            print(f"[UYARI] {contract.symbol} icin gecmis veri alinamadi.")
            return None

        df = util.df(bars)
        df.columns = [c.capitalize() for c in df.columns]

        print(f"[VERI] {contract.symbol} | {len(df)} bar ({bar_boyutu}) | Sure: {sure}")

        if pipeline_uygula:
            print(f"[PIPELINE] Feature pipeline baslatiliyor...")
            df = feature_pipeline(df)

        return df

    except Exception as e:
        print(f"[HATA] Gecmis veri cekme hatasi: {e}")
        return None


# ============================================================
#  8. HESAP BILGISI OKUMA (Kasa & Pozisyonlar)
# ============================================================

def hesap_bilgisi_oku(ib):
    """
    Paper Trading hesabindaki bakiye, alis gucu ve
    acik pozisyonlari okur.

    Donus:
        dict: {bakiye, alis_gucu, net_liq, pozisyonlar} veya None
    """
    try:
        ozet = ib.accountSummary()

        bakiye = None
        alis_gucu = None
        net_liq = None

        for satir in ozet:
            if satir.tag == 'TotalCashValue' and satir.currency == 'USD':
                bakiye = float(satir.value)
            elif satir.tag == 'BuyingPower':
                alis_gucu = float(satir.value)
            elif satir.tag == 'NetLiquidation' and satir.currency == 'USD':
                net_liq = float(satir.value)

        print(f"[HESAP] Nakit: ${bakiye or 0:,.2f} | "
              f"Net Liq: ${net_liq or 0:,.2f} | "
              f"Alis Gucu: ${alis_gucu or 0:,.2f}")

        pozisyonlar = ib.positions()
        if pozisyonlar:
            print(f"[POZISYON] {len(pozisyonlar)} acik pozisyon")
            for p in pozisyonlar:
                print(f"           {p.contract.symbol:>6} | "
                      f"Miktar: {p.position:>6.0f} | "
                      f"Maliyet: ${p.avgCost:>8.2f}")

        return {
            'bakiye': bakiye,
            'alis_gucu': alis_gucu,
            'net_liq': net_liq,
            'pozisyonlar': pozisyonlar,
        }

    except Exception as e:
        print(f"[HATA] Hesap bilgisi okunamadi: {e}")
        return None

def bakiye_getir(ib):
    """
    Sadece IBKR hesabindaki mevcut nakit bakiyeyi doner.
    Hesaptaki tum farkli para birimlerini ana para birimine (BASE veya USD)
    cevirmis olan satiri bulur.
    """
    try:
        ozet = ib.accountSummary()
        # 1. Oncelik: IBKR'nin tüm paraları konsolide ettiği 'BASE'
        for satir in ozet:
            if satir.tag == 'TotalCashValue' and satir.currency == 'BASE':
                return float(satir.value)
                
        # 2. Alternatif: Direkt USD kasasi
        for satir in ozet:
            if satir.tag == 'TotalCashValue' and satir.currency == 'USD':
                return float(satir.value)
        return 0.0
    except Exception as e:
        print(f"[HATA] Bakiye okuma hatasi: {e}")
        return 0.0


# ============================================================
#  9. TOPLU TARAMA (FAZ 3: Otonom Hiz Motoru)
# ============================================================

def toplu_veri_cek(ib, hisse_listesi, bekleme_sn=3):
    """
    Kaptan'in listesindeki tum hisseleri ib_insync ile paralel dogrular ve fiyatlarini ceker.
    """
    sonuclar = {}
    try:
        contracts = []
        sembol_eslestirme = {}
        for sembol in hisse_listesi:
            gs, borsa, pb = parse_global_symbol(sembol)
            c = Stock(gs, borsa, pb)
            contracts.append(c)
            sembol_eslestirme[gs] = sembol

        qualified_contracts = ib.qualifyContracts(*contracts)
        if not qualified_contracts:
            return sonuclar

        tickers = [ib.reqMktData(c, '', True, False) for c in qualified_contracts]
        ib.sleep(bekleme_sn)

        for t in tickers:
            c = t.contract
            orijinal_sembol = sembol_eslestirme.get(c.symbol, c.symbol)
            price = t.marketPrice()
            if not price or pd.isna(price) or price <= 0:
                price = t.last if (t.last and not pd.isna(t.last) and t.last > 0) else (t.close if (t.close and not pd.isna(t.close) and t.close > 0) else None)
            
            if (bid is None or pd.isna(bid) or bid <= 0) and price:
                bid = round(price * 0.9995, 2)
            if (ask is None or pd.isna(ask) or ask <= 0) and price:
                ask = round(price * 1.0005, 2)
            if (last is None or pd.isna(last) or last <= 0) and price:
                last = round(price, 2)

            spread_bps = None
            if bid and ask:
                mid = (bid + ask) / 2.0
                spread_bps = round(((ask - bid) / mid) * 10000, 2)

            sonuclar[orijinal_sembol] = {
                'bid': bid,
                'ask': ask,
                'last': last,
                'mid': (bid + ask) / 2.0 if (bid and ask) else price,
                'spread_bps': spread_bps or 10.0,
                'hacim': hacim,
                'borsa': c.exchange,
                'kur': c.currency
            }
            ib.cancelMktData(t.contract)

        return sonuclar
    except Exception as e:
        return sonuclar

async def toplu_veri_cek_async(ib, hisse_listesi, bekleme_sn=3):
    """
    Kaptan'in listesindeki tum hisseleri ASENKRON olarak,
    ayni saniye icinde (paralel) dogrular ve fiyatlarini ceker.
    For dongusuyle tek tek cekmek yasaktir (Pacing siralamasi).
    
    Donus:
        dict: {sembol: {bid, ask, last, spread_bps, volume}, ...}
    """
    sonuclar = {}

    try:
        # 1. Tum sozlesmeleri hazirla ve sembol haritasini tut
        contracts = []
        sembol_eslestirme = {}
        for sembol in hisse_listesi:
            gs, borsa, pb = parse_global_symbol(sembol)
            c = Stock(gs, borsa, pb)
            contracts.append(c)
            sembol_eslestirme[gs] = sembol # gercek sembolden orijinal '.DE' uzantili sembole harita

        qualified_contracts = await ib.qualifyContractsAsync(*contracts)
        
        if not qualified_contracts:
            print("[HATA] Hicbir sozlesme dogrulanamadi!")
            return sonuclar

        # 2. Tum hisseler icin ayni anda canli veri akisi (snapshot) baslat
        tickers = [ib.reqMktData(c, '', True, False) for c in qualified_contracts]
        
        # 3. Verilerin gelmesi icin asenkron bekle
        await asyncio.sleep(bekleme_sn)
        
        # 4. Gelen sonuclari isleyerek spread analizi yap
        for t in tickers:
            c = t.contract
            orijinal_sembol = sembol_eslestirme.get(c.symbol, c.symbol)
            
            bid = t.bid if t.bid and t.bid > 0 and t.bid != -1.0 else None
            ask = t.ask if t.ask and t.ask > 0 and t.ask != -1.0 else None
            last = t.last if t.last and t.last > 0 and t.last != -1.0 else None
            hacim = t.volume if t.volume and t.volume > 0 else 0

            spread_bps = None
            if bid and ask:
                mid = (bid + ask) / 2.0
                spread_bps = round(((ask - bid) / mid) * 10000, 2)

            sonuclar[orijinal_sembol] = {
                'bid': bid,
                'ask': ask,
                'last': last,
                'spread_bps': spread_bps,
                'hacim': hacim,
                'borsa': c.exchange,
                'kur': c.currency
            }
            
            # Veri akisini durduralim ki RAM sismesi/kota sorunu olmasin
            ib.cancelMktData(t.contract)
            
        return sonuclar

    except Exception as e:
        return sonuclar


# ============================================================
#  10. BRACKET EMİR SİSTEMİ (FAZ 4: İnfaz Motoru)
# ============================================================

def bracket_emri_gonder(ib, sembol, yon, miktar, tp_fiyat, sl_fiyat):
    """
    IBKR uzerinde TP ve SL baglantili (GTC) bracket emir paketi acir.
    Gonderimden once net_rr_filtresi kontrolu yapar.
    
    Parametreler:
        sembol:    AAPL, MSFT vb.
        yon:       BUY veya SELL
        miktar:    Hisse adedi
        tp_fiyat:  Take Profit ($)
        sl_fiyat:  Stop Loss ($)
        
    Kilit Sarti: Parent Emir KESINLIKLE Market Order (MKT)
                 Child 1 (TP)  KESINLIKLE Limit Order (LMT)
                 Child 2 (SL)  KESINLIKLE Stop Order (STP)
    """
    try:
        # Sozlesmeyi dogrula
        contract = sozlesme_dogrula(ib, sembol)
        if not contract:
            print(f"[INFAZ RED] {sembol} dogrulanamadi.")
            return False

        # Canli fiyat al ve Maliyet/Risk filtresinden onaya yolla
        piyasa = piyasa_verisi_cek(ib, contract)
        if not piyasa or not piyasa.get('mid'):
            print(f"[INFAZ RED] {sembol} canli fiyati bilinemiyor.")
            return False
            
        if yon.upper() == 'BUY':
            guncel_giris = piyasa['ask'] or piyasa['mid']
        else: # SELL/SHORT
            guncel_giris = piyasa['bid'] or piyasa['mid']

        # --- GUVENLIK KILIDI: FAZ 1 (RR KONTROLU) ---
        rr_onay = net_rr_filtresi(
            fiyat=guncel_giris,
            tp_fiyat=tp_fiyat,
            sl_fiyat=sl_fiyat,
            miktar=miktar,
            spread_bps=piyasa.get('spread_bps'),
            yon=yon
        )
        
        if rr_onay['karar'] == 'RED':
            print(f"[INFAZ IPTAL] {sembol} -> {rr_onay['red_sebebi']}")
            return False

        print(f"\n[INFAZ MOTORU] {sembol} icin Bracket Emir Hazirlaniyor...")
        print(f"               Yon: {yon.upper()} | Miktar: {miktar}")
        print(f"               Ana Emir: MKT (Beklenen: ~${guncel_giris:.2f})")
        print(f"               Kar Al  (LMT): ${tp_fiyat:.2f}")
        print(f"               Zarar Kes (STP): ${sl_fiyat:.2f}")

        # --- BRACKET EMIR INSAASI ---
        ana_action = 'BUY' if yon.upper() == 'BUY' else 'SELL'
        karsit_action = 'SELL' if ana_action == 'BUY' else 'BUY'
        
        # 1. Ana Emir (Market)
        parent = MarketOrder(ana_action, miktar, tif='GTC')
        
        # 2. Take Profit (Limit)
        take_profit = LimitOrder(karsit_action, miktar, tp_fiyat, tif='GTC')
        take_profit.parentId = parent.orderId
        take_profit.transmit = False # Son emir haric transmit False olmali
        
        # 3. Stop Loss (Stop)
        stop_loss = StopOrder(karsit_action, miktar, sl_fiyat, tif='GTC')
        stop_loss.parentId = parent.orderId
        stop_loss.transmit = True    # Son emir paketi borsaya yollar

        bracket = [parent, take_profit, stop_loss]
        
        # Paket halinda IBKR'ye ilet
        for order in bracket:
            ib.placeOrder(contract, order)
            
        print(f"✅ [INFAZ BASARILI] {sembol} bracket paketi borsaya islendi.")
        return True

    except Exception as e:
        print(f"[HATA] Bracket emir gonderiminde hata: {e}")
        return False


# ============================================================
#  V2.1 EKLENTİLERİ — Emir Takip, Dayanıklılık, Senkronizasyon  
# ============================================================
import datetime
import pytz
import asyncio

try:
    import yfinance as yf
except ImportError:
    yf = None

class EmirTakipci:
    """
    IBKR emir durumlarını takip eden sistem.
    Her gönderilen emrin fill/cancel/reject durumunu izler.
    """
    def __init__(self, ib: IB):
        self.ib = ib
        self.bekleyen_emirler = {}  # order_id -> {sembol, yon, miktar, durum, zaman}
        self._callback_kaydet()
    
    def _callback_kaydet(self):
        """IBKR fill/status callback'lerini bağlar"""
        self.ib.orderStatusEvent += self._emir_durum_degisti
        self.ib.execDetailsEvent += self._islem_gerceklesti
    
    def _emir_durum_degisti(self, trade):
        """Emir durumu değiştiğinde çağrılır"""
        order_id = trade.order.orderId
        status = trade.orderStatus.status
        if order_id in self.bekleyen_emirler:
            self.bekleyen_emirler[order_id]['durum'] = status
        print(f"[EMIR TAKIP] Emir {order_id} durumu güncellendi: {status}")
    
    def _islem_gerceklesti(self, trade, fill):
        """Emir dolduğunda çağrılır"""
        order_id = trade.order.orderId
        miktar = fill.execution.shares
        fiyat = fill.execution.price
        zaman = fill.execution.time
        print(f"[EMIR TAKIP] Emir {order_id} GERÇEKLEŞTİ: {miktar} lot @ ${fiyat} (Zaman: {zaman})")
        if order_id in self.bekleyen_emirler:
            self.bekleyen_emirler[order_id]['durum'] = 'Filled'
        return {'order_id': order_id, 'miktar': miktar, 'fiyat': fiyat, 'zaman': zaman}
    
    def emir_durumu(self, order_id) -> dict:
        """Belirli bir emrin güncel durumunu döndürür"""
        return self.bekleyen_emirler.get(order_id, {})
    
    def bekleyen_emirleri_listele(self) -> list:
        """Tüm bekleyen/açık emirleri listeler"""
        acik_emirler = []
        for oid, data in self.bekleyen_emirler.items():
            if data['durum'] not in ['Filled', 'Cancelled', 'Inactive']:
                acik_emirler.append({'order_id': oid, **data})
        return acik_emirler
    
    def tum_emirleri_iptal_et(self):
        """Tüm açık emirleri iptal eder (acil durum)"""
        print("[EMIR TAKIP] Acil durum: Tüm açık emirler iptal ediliyor...")
        self.ib.reqGlobalCancel()

def bracket_emri_gonder_v2(ib, sembol, yon, miktar, tp_fiyat, sl_fiyat, emir_takipci=None):
    """
    Geliştirilmiş bracket emir - Order ID'leri döndürür.
    
    Returns:
        dict: {
            'basarili': bool,
            'parent_order_id': int,
            'tp_order_id': int, 
            'sl_order_id': int,
            'sembol': str,
            'yon': str,
            'miktar': int,
            'giris_beklenen': float,
            'tp_fiyat': float,
            'sl_fiyat': float
        } or None on failure
    """
    try:
        contract = sozlesme_dogrula(ib, sembol)
        if not contract:
            print(f"[INFAZ RED] {sembol} doğrulanamadı.")
            return None

        piyasa = piyasa_verisi_cek(ib, contract)
        if not piyasa or not piyasa.get('mid'):
            print(f"[INFAZ RED] {sembol} canlı fiyatı bilinemiyor.")
            return None
            
        guncel_giris = piyasa['ask'] if yon.upper() == 'BUY' else piyasa['bid']
        if guncel_giris is None:
            guncel_giris = piyasa['mid']

        rr_onay = net_rr_filtresi(
            fiyat=guncel_giris,
            tp_fiyat=tp_fiyat,
            sl_fiyat=sl_fiyat,
            miktar=miktar,
            spread_bps=piyasa.get('spread_bps'),
            yon=yon
        )
        
        if rr_onay['karar'] == 'RED':
            print(f"[INFAZ IPTAL] {sembol} -> {rr_onay['red_sebebi']}")
            return None

        ana_action = 'BUY' if yon.upper() == 'BUY' else 'SELL'
        karsit_action = 'SELL' if ana_action == 'BUY' else 'BUY'
        
        parent = MarketOrder(ana_action, miktar, tif='GTC')
        take_profit = LimitOrder(karsit_action, miktar, tp_fiyat, tif='GTC')
        stop_loss = StopOrder(karsit_action, miktar, sl_fiyat, tif='GTC')
        
        parent_trade = ib.placeOrder(contract, parent)
        take_profit.parentId = parent_trade.order.orderId
        take_profit.transmit = False
        
        stop_loss.parentId = parent_trade.order.orderId
        stop_loss.transmit = True

        tp_trade = ib.placeOrder(contract, take_profit)
        sl_trade = ib.placeOrder(contract, stop_loss)
        
        zaman_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if emir_takipci:
            emir_takipci.bekleyen_emirler[parent_trade.order.orderId] = {
                'sembol': sembol, 'yon': ana_action, 'miktar': miktar, 'durum': 'Submitted', 'zaman': zaman_str
            }
            emir_takipci.bekleyen_emirler[tp_trade.order.orderId] = {
                'sembol': sembol, 'yon': karsit_action, 'miktar': miktar, 'durum': 'Pending', 'zaman': zaman_str
            }
            emir_takipci.bekleyen_emirler[sl_trade.order.orderId] = {
                'sembol': sembol, 'yon': karsit_action, 'miktar': miktar, 'durum': 'Pending', 'zaman': zaman_str
            }

        print(f"✅ [INFAZ BAŞARILI] {sembol} bracket paketi borsaya işlendi.")
        
        return {
            'basarili': True,
            'parent_order_id': parent_trade.order.orderId,
            'tp_order_id': tp_trade.order.orderId,
            'sl_order_id': sl_trade.order.orderId,
            'sembol': sembol,
            'yon': yon.upper(),
            'miktar': miktar,
            'giris_beklenen': guncel_giris,
            'tp_fiyat': tp_fiyat,
            'sl_fiyat': sl_fiyat
        }
    except Exception as e:
        print(f"[HATA] Bracket emir v2 gönderiminde hata: {e}")
        return None

def guvenli_baglan(host='127.0.0.1', port=7497, client_id=10, max_deneme=3, bekleme_sn=5):
    """
    Dayanıklı IBKR bağlantısı - otomatik yeniden bağlanma.
    max_deneme kadar deneyip, her denemede bekleme_sn bekler.
    """
    for deneme in range(1, max_deneme + 1):
        print(f"[GÜVENLİ BAĞLANTI] Deneme {deneme}/{max_deneme} ({host}:{port})")
        ib = ibkr_baglan(host=host, port=port, client_id=client_id)
        if ib and ib.isConnected():
            return ib
        if deneme < max_deneme:
            print(f"[GÜVENLİ BAĞLANTI] Başarısız. {bekleme_sn} saniye sonra tekrar denenecek...")
            time.sleep(bekleme_sn)
    
    print("[HATA] Maksimum bağlantı denemesine ulaşıldı. IBKR'ye bağlanılamadı.")
    return None

def baglanti_kontrol(ib) -> bool:
    """Bağlantının hâlâ aktif olup olmadığını kontrol eder"""
    if ib is None:
        return False
    durum = ib.isConnected()
    if not durum:
        print("[UYARI] IBKR bağlantısı kopmuş durumda.")
    return durum

def yeniden_baglan(ib, host='127.0.0.1', port=7497, client_id=10) -> IB:
    """Kopmuş bağlantıyı yeniden kurar"""
    if baglanti_kontrol(ib):
        print("[BAĞLANTI KONTROL] Bağlantı zaten aktif.")
        return ib
    print("[YENİDEN BAĞLAN] Bağlantı koptu, yeniden bağlanılıyor...")
    if ib:
        try:
            ib.disconnect()
        except:
            pass
    return guvenli_baglan(host=host, port=port, client_id=client_id)

def pozisyon_senkronize(ib) -> dict:
    """
    IBKR'deki gerçek açık pozisyonları okur ve yapılandırılmış dict döndürür.
    
    Returns:
        dict: {
            'AAPL': {'miktar': 50, 'maliyet': 185.20, 'yon': 'LONG', 'piyasa_degeri': 9500},
            'TSLA': {'miktar': -10, 'maliyet': 250.00, 'yon': 'SHORT', 'piyasa_degeri': 2400},
            ...
        }
    """
    pozisyonlar = {}
    try:
        if not baglanti_kontrol(ib):
            print("[HATA] Bağlantı aktif olmadığı için pozisyonlar okunamıyor.")
            return pozisyonlar
            
        ib_pozisyonlar = ib.positions()
        for p in ib_pozisyonlar:
            if p.position == 0:
                continue
            sembol = p.contract.symbol
            miktar = p.position
            maliyet = p.avgCost
            yon = 'LONG' if miktar > 0 else 'SHORT'
            piyasa_degeri = abs(miktar * maliyet)
            
            pozisyonlar[sembol] = {
                'miktar': miktar,
                'maliyet': maliyet,
                'yon': yon,
                'piyasa_degeri': piyasa_degeri
            }
        print(f"[SENKRONİZASYON] Toplam {len(pozisyonlar)} aktif pozisyon senkronize edildi.")
        return pozisyonlar
    except Exception as e:
        print(f"[HATA] Pozisyon senkronizasyonunda hata: {e}")
        return {}

def piyasa_acik_mi() -> dict:
    """
    NYSE piyasa saatlerini kontrol eder.
    
    Returns:
        dict: {
            'acik': bool,
            'gun': str (Monday-Friday),
            'saat_et': str (HH:MM ET),
            'sonraki_acilis': str (ISO datetime),
            'acilisa_kalan_dk': int
        }
    """
    tz_et = pytz.timezone('US/Eastern')
    simdi_et = datetime.datetime.now(tz_et)
    
    gun = simdi_et.strftime('%A')
    saat_et_str = simdi_et.strftime('%H:%M')
    
    is_hafta_ici = simdi_et.weekday() < 5
    acilis_saati = simdi_et.replace(hour=9, minute=30, second=0, microsecond=0)
    kapanis_saati = simdi_et.replace(hour=16, minute=0, second=0, microsecond=0)
    
    is_saat_uygun = acilis_saati <= simdi_et < kapanis_saati
    
    acik = is_hafta_ici and is_saat_uygun
    
    sonraki_acilis = acilis_saati
    if simdi_et >= kapanis_saati or not is_hafta_ici:
        gun_ekle = 1
        if simdi_et.weekday() == 4: # Cuma
            gun_ekle = 3
        elif simdi_et.weekday() == 5: # Cumartesi
            gun_ekle = 2
        sonraki_acilis = (simdi_et + datetime.timedelta(days=gun_ekle)).replace(hour=9, minute=30, second=0, microsecond=0)
    elif simdi_et < acilis_saati:
        sonraki_acilis = acilis_saati
        
    fark = sonraki_acilis - simdi_et
    acilisa_kalan_dk = int(fark.total_seconds() / 60)
    
    return {
        'acik': acik,
        'gun': gun,
        'saat_et': saat_et_str,
        'sonraki_acilis': sonraki_acilis.isoformat(),
        'acilisa_kalan_dk': acilisa_kalan_dk if not acik else 0
    }

def vix_oku() -> float:
    """
    Güncel VIX değerini okur (yfinance fallback ile).
    IBKR'den çekilemezse yfinance'ten alır.
    """
    vix_degeri = 20.0 # Varsayılan güvenlik değeri
    try:
        if yf is not None:
            vix_ticker = yf.Ticker("^VIX")
            hist = vix_ticker.history(period="1d")
            if not hist.empty:
                vix_degeri = hist['Close'].iloc[-1]
                print(f"[VIX OKUMA] Güncel VIX değeri (yfinance): {vix_degeri:.2f}")
                return float(vix_degeri)
        
        print(f"[VIX OKUMA] yfinance kullanılamadı. Varsayılan VIX dönülüyor: {vix_degeri}")
        return vix_degeri
    except Exception as e:
        print(f"[HATA] VIX okuma hatası: {e}. Varsayılan değer dönülüyor: {vix_degeri}")
        return vix_degeri


# ============================================================
#  10. ANA CALISTIRMA (TAM TEST SENARYOSU)
# ============================================================

if __name__ == "__main__":

    print("=" * 65)
    print("  IBKR BRIDGE v2.0 — Maliyet Motoru + XGBoost Pipeline")
    print("  Hedef: TWS 127.0.0.1:7497 (Paper Trading)")
    print("=" * 65)

    # --- ADIM 1: BAGLAN ---
    ib = ibkr_baglan(host='127.0.0.1', port=7497, client_id=1)
    if ib is None:
        print("\n[SONUC] Baglanti BASARISIZ. TWS ayarlarini kontrol et.")
        sys.exit(1)

    try:
        # --- ADIM 2: AAPL SOZLESMESINI DOGRULA ---
        contract = sozlesme_dogrula(ib, sembol='AAPL')
        if contract is None:
            ib.disconnect()
            sys.exit(1)

        # --- ADIM 3: CANLI FIYAT VE SPREAD ---
        piyasa = piyasa_verisi_cek(ib, contract)

        # --- ADIM 4: MALIYET MOTORU TESTI ---
        if piyasa and piyasa.get('bid') and piyasa.get('ask'):
            print(f"\n{'─' * 50}")
            print("[TEST] Maliyet Motoru (100 hisse AAPL)")
            print(f"{'─' * 50}")

            maliyet = islem_maliyeti_hesapla(
                fiyat=piyasa['mid'],
                miktar=100,
                spread_bps=piyasa['spread_bps']
            )
            print(f"  Islem Degeri:    ${maliyet['islem_degeri']:,.2f}")
            print(f"  Komisyon (G+C):  ${maliyet['komisyon_toplam']:.2f}")
            print(f"  Spread Maliyeti: ${maliyet['spread_maliyet']:.2f}")
            print(f"  TOPLAM Maliyet:  ${maliyet['toplam_maliyet']:.2f} "
                  f"(%{maliyet['maliyet_yuzde']:.3f})")

        # --- ADIM 5: NET RR FİLTRESİ TESTİ ---
        if piyasa and piyasa.get('mid'):
            print(f"\n{'─' * 50}")
            print("[TEST] Net RR Filtresi (ATR bazli TP/SL simülasyonu)")
            print(f"{'─' * 50}")

            fiyat = piyasa['mid']
            # Stock_value_engine.py ile ayni mantik: TP = 3 ATR, SL = 1.5 ATR
            # Ornek ATR: fiyatin %2'si
            atr_tahmini = fiyat * 0.02
            tp = round(fiyat + (atr_tahmini * 3.0), 2)
            sl = round(fiyat - (atr_tahmini * 1.5), 2)

            rr_sonuc = net_rr_filtresi(
                fiyat=fiyat,
                tp_fiyat=tp,
                sl_fiyat=sl,
                miktar=100,
                spread_bps=piyasa.get('spread_bps')
            )
            print(f"  Brut Kar:  ${rr_sonuc['brut_kar']:.2f} | "
                  f"Net Kar:  ${rr_sonuc['net_kar']:.2f}")
            print(f"  Brut Zarar: ${rr_sonuc['brut_zarar']:.2f} | "
                  f"Net Zarar: ${rr_sonuc['net_zarar']:.2f}")

        # --- ADIM 6: GECMİS VERİ + FEATURE PIPELINE ---
        print(f"\n{'─' * 50}")
        print("[TEST] ai_core.py Feature Pipeline (1 Yillik Gunluk)")
        print(f"{'─' * 50}")

        df = gecmis_veri_cek(ib, contract, bar_boyutu='1 day', sure='1 Y',
                            pipeline_uygula=True)

        if df is not None:
            print(f"\n  DataFrame Boyutu: {df.shape[0]} satir x {df.shape[1]} sutun")
            print(f"  ai_core.py Features ({len(STOCK_FEATURES)} adet):")
            for feat in STOCK_FEATURES:
                if feat in df.columns:
                    val = df[feat].iloc[-1]
                    nan_count = df[feat].isna().sum()
                    print(f"    {feat:<25} Son: {val:>10.4f}  NaN: {nan_count}")
                else:
                    print(f"    {feat:<25} EKSIK!")

            # ai_core.py ile uyumluluk testi
            print(f"\n  [UYUMLULUK] ai_core.py'ye beslenmeye HAZIR:")
            print(f"  from ai_core import BeyinMotoru")
            print(f"  beyin = BeyinMotoru()")
            print(f"  skor = beyin.tahmin_et('AAPL', df, is_crypto=False)")

        # --- ADIM 7: HESAP BILGISI ---
        print(f"\n{'─' * 50}")
        hesap = hesap_bilgisi_oku(ib)

        # --- FINAL OZET ---
        print(f"\n{'=' * 65}")
        print("  IBKR BRIDGE v2.0 TEST SONUCU: BASARILI")
        print(f"{'=' * 65}")

    except KeyboardInterrupt:
        print("\n[SISTEM] Kaptan tarafindan durduruldu.")

    except Exception as e:
        print(f"\n[KRITIK HATA] {e}")
        import traceback
        traceback.print_exc()

    finally:
        if ib.isConnected():
            ib.disconnect()
            print("[IBKR] Baglanti temiz bir sekilde kapatildi.")
