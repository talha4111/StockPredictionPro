"""
STOCK VALUE ENGINE - Wall Street Kalibresinde Deger & Momentum Motoru
Mod: DANISMAN (Advisor) - Sinyal uretir, otomatik islem ACMAZ.
Timeframe: Gunluk (1d) + Haftalik (1wk)
Hedef: 3-12 Ay Elde Tutma Suresi
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

import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import json
import os
import requests
import sqlite3
from datetime import datetime, timedelta
from collections import defaultdict

STOCK_SCORING_MODE = 'rule_based_v2'
STOCK_SCORE_VERSION = 2
US_MARKET_TIMEZONE = 'America/New_York'
MIN_INTRADAY_SESSION_BARS = 180
QUOTE_CLOSE_TOLERANCE = 0.02

# ============================================================
#  1. KURUMSAL HAVUZ (Top 100 — S&P 500 + NASDAQ Seçkinleri)
# ============================================================
# Sektör bilgileri havuzda gömülü: yfinance API çağrısını azaltır.
KURUMSAL_HAVUZ = {
    # --- Teknoloji (Technology) ---
    'AAPL':  'Technology', 'MSFT':  'Technology', 'NVDA':  'Technology',
    'AVGO':  'Technology', 'ADBE':  'Technology', 'CRM':   'Technology',
    'AMD':   'Technology', 'INTC':  'Technology', 'CSCO':  'Technology',
    'ORCL':  'Technology', 'IBM':   'Technology', 'QCOM':  'Technology',
    'TXN':   'Technology', 'NOW':   'Technology', 'AMAT':  'Technology',
    'MU':    'Technology', 'LRCX':  'Technology', 'KLAC':  'Technology',
    'MRVL':  'Technology', 'SNPS':  'Technology',
    # --- İletişim / Medya (Communication Services) ---
    'GOOGL': 'Communication', 'META': 'Communication', 'NFLX': 'Communication',
    'DIS':   'Communication', 'CMCSA': 'Communication', 'TMUS': 'Communication',
    'VZ':    'Communication', 'T':     'Communication',
    # --- Tüketici İhtiyari (Consumer Discretionary) ---
    'AMZN':  'Consumer Disc.', 'TSLA': 'Consumer Disc.', 'HD':   'Consumer Disc.',
    'NKE':   'Consumer Disc.', 'MCD':  'Consumer Disc.', 'SBUX': 'Consumer Disc.',
    'LOW':   'Consumer Disc.', 'TJX':  'Consumer Disc.', 'BKNG': 'Consumer Disc.',
    'CMG':   'Consumer Disc.',
    # --- Tüketici Temel (Consumer Staples) ---
    'PG':    'Consumer Stap.', 'KO':   'Consumer Stap.', 'PEP':  'Consumer Stap.',
    'COST':  'Consumer Stap.', 'WMT':  'Consumer Stap.', 'PM':   'Consumer Stap.',
    'CL':    'Consumer Stap.', 'MDLZ': 'Consumer Stap.',
    # --- Sağlık (Healthcare) ---
    'UNH':   'Healthcare', 'JNJ':  'Healthcare', 'LLY':  'Healthcare',
    'ABBV':  'Healthcare', 'MRK':  'Healthcare', 'PFE':  'Healthcare',
    'TMO':   'Healthcare', 'ABT':  'Healthcare', 'DHR':  'Healthcare',
    'BMY':   'Healthcare', 'AMGN': 'Healthcare', 'GILD': 'Healthcare',
    'ISRG':  'Healthcare', 'VRTX': 'Healthcare', 'MDT':  'Healthcare',
    # --- Finans (Financials) ---
    'JPM':   'Financials', 'V':    'Financials', 'MA':   'Financials',
    'BAC':   'Financials', 'WFC':  'Financials', 'GS':   'Financials',
    'MS':    'Financials', 'BLK':  'Financials', 'AXP':  'Financials',
    'SPGI':  'Financials',
    # --- Enerji (Energy) ---
    'XOM':   'Energy', 'CVX':  'Energy', 'COP':  'Energy',
    'SLB':   'Energy', 'EOG':  'Energy',
    # --- Endüstriyel (Industrials) ---
    'CAT':   'Industrials', 'HON':  'Industrials', 'UNP':  'Industrials',
    'RTX':   'Industrials', 'BA':   'Industrials', 'GE':   'Industrials',
    'DE':    'Industrials', 'LMT':  'Industrials',
    # --- Malzeme (Materials) ---
    'LIN':   'Materials', 'APD':  'Materials', 'SHW':  'Materials',
    # --- Gayrimenkul (Real Estate) ---
    'AMT':   'Real Estate', 'PLD':  'Real Estate', 'CCI':  'Real Estate',
    # --- Kamu Hizmetleri (Utilities) ---
    'NEE':   'Utilities', 'DUK':  'Utilities', 'SO':   'Utilities',
}

# Sektör ETF'leri (Sektör Rotasyonu Radarı için)
SEKTOR_ETFLERI = {
    'Technology':       'XLK',
    'Communication':    'XLC',
    'Consumer Disc.':   'XLY',
    'Consumer Stap.':   'XLP',
    'Healthcare':       'XLV',
    'Financials':       'XLF',
    'Energy':           'XLE',
    'Industrials':      'XLI',
    'Materials':        'XLB',
    'Real Estate':      'XLRE',
    'Utilities':        'XLU',
}

# ============================================================
#  2. YARDIMCI FONKSİYONLAR
# ============================================================

def _borsa_zamani(now=None, timezone=US_MARKET_TIMEZONE):
    """Verilen zamanı borsanın yerel saatine çevirir."""
    zaman = pd.Timestamp.now(tz=timezone) if now is None else pd.Timestamp(now)
    if zaman.tzinfo is None:
        return zaman.tz_localize(timezone)
    return zaman.tz_convert(timezone)


def _tamamlanmis_barlari_sec(df, interval, now=None, timezone=US_MARKET_TIMEZONE):
    """Günlük/haftalık seriden henüz kapanmamış son barı çıkarır."""
    if df is None or df.empty:
        return df

    sonuc = df.copy()
    sonuc = sonuc[~sonuc.index.duplicated(keep='last')].sort_index()
    indeks = pd.DatetimeIndex(sonuc.index)
    if indeks.tz is None:
        yerel_indeks = indeks.tz_localize(timezone)
    else:
        yerel_indeks = indeks.tz_convert(timezone)

    simdi = _borsa_zamani(now, timezone)
    bugun = simdi.normalize()

    if interval == '1d':
        bugunun_kapanisi = bugun + pd.Timedelta(hours=16, minutes=15)
        ilk_tamamlanmamis_gun = bugun if simdi < bugunun_kapanisi else bugun + pd.Timedelta(days=1)
        maske = yerel_indeks.normalize() < ilk_tamamlanmamis_gun
    elif interval == '1wk':
        hafta_basi = bugun - pd.Timedelta(days=simdi.weekday())
        haftanin_kapanisi = hafta_basi + pd.Timedelta(days=4, hours=16, minutes=15)
        ilk_tamamlanmamis_hafta = (
            hafta_basi if simdi < haftanin_kapanisi else hafta_basi + pd.Timedelta(days=7)
        )
        maske = yerel_indeks.normalize() < ilk_tamamlanmamis_hafta
    else:
        raise ValueError(f'Desteklenmeyen bar aralığı: {interval}')

    return sonuc.loc[maske]


def _bar_tarihi(df):
    if df is None or df.empty:
        return None
    return str(pd.Timestamp(df.index[-1]).date())


def _beklenen_son_tamamlanmis_is_gunu(now=None, timezone=US_MARKET_TIMEZONE):
    """Tatil bilgisini veriyle doğrulamak üzere en yakın hafta içi adayını döndürür."""
    simdi = _borsa_zamani(now, timezone)
    bugun = simdi.normalize()
    kapanis_tamponu = bugun + pd.Timedelta(hours=16, minutes=15)
    aday = bugun if simdi.weekday() < 5 and simdi >= kapanis_tamponu else bugun - pd.Timedelta(days=1)
    while aday.weekday() >= 5:
        aday -= pd.Timedelta(days=1)
    return aday.date()


def _sayisal_alan_oku(nesne, alan):
    deger = _alan_oku(nesne, alan)
    try:
        sayi = float(deger)
    except (TypeError, ValueError):
        return None
    return sayi if np.isfinite(sayi) and sayi > 0 else None


def _canli_fiyat_bilgisi(ticker):
    try:
        fast_info = ticker.fast_info
    except Exception:
        fast_info = None
    return {
        'canli_fiyat': _sayisal_alan_oku(fast_info, 'last_price'),
        'onceki_kapanis': (
            _sayisal_alan_oku(fast_info, 'previous_close')
            or _sayisal_alan_oku(fast_info, 'regular_market_previous_close')
        ),
    }


def _dakikalik_barlari_gunluge_cevir(
    intraday,
    now=None,
    timezone=US_MARKET_TIMEZONE,
    min_session_bars=MIN_INTRADAY_SESSION_BARS,
):
    """Tamamlanmış 1 dakikalık seansları günlük OHLCV barlarına toplar."""
    gerekli = {'Open', 'High', 'Low', 'Close', 'Volume'}
    if intraday is None or intraday.empty or not gerekli.issubset(intraday.columns):
        return pd.DataFrame(columns=sorted(gerekli))

    veri = intraday.copy().sort_index()
    indeks = pd.DatetimeIndex(veri.index)
    if indeks.tz is None:
        yerel_indeks = indeks.tz_localize(timezone)
    else:
        yerel_indeks = indeks.tz_convert(timezone)
    veri['_session_date'] = yerel_indeks.date
    beklenen_son_gun = _beklenen_son_tamamlanmis_is_gunu(now, timezone)

    satirlar = []
    indeksler = []
    for tarih, grup in veri.groupby('_session_date', sort=True):
        if tarih > beklenen_son_gun or len(grup) < min_session_bars:
            continue
        satirlar.append({
            'Open': float(grup['Open'].iloc[0]),
            'High': float(grup['High'].max()),
            'Low': float(grup['Low'].min()),
            'Close': float(grup['Close'].iloc[-1]),
            'Volume': float(grup['Volume'].sum()),
        })
        indeksler.append(pd.Timestamp(tarih).tz_localize(timezone))

    return pd.DataFrame(satirlar, index=pd.DatetimeIndex(indeksler))


def _gunluk_veriyi_hazirla(ticker, df, now=None, timezone=US_MARKET_TIMEZONE):
    """
    Günlük seriyi kapanmış barlara indirger, eksik son seansı 1m veriden onarır.

    Onarım veya tazelik doğrulaması mümkün değilse ``ok=False`` döner; sinyal
    motoru böylece bayat veriyle karar üretmez.
    """
    tamamlanmis = _tamamlanmis_barlari_sec(df, '1d', now=now, timezone=timezone)
    beklenen = _beklenen_son_tamamlanmis_is_gunu(now, timezone)
    meta = {
        'ok': False,
        'veri_durumu': 'yetersiz',
        'beklenen_son_tamamlanmis_bar': str(beklenen),
        'last_completed_daily_bar': _bar_tarihi(tamamlanmis),
        'onarilan_gunluk_barlar': [],
    }
    if tamamlanmis is None or tamamlanmis.empty:
        return tamamlanmis, meta

    son_tarih = pd.Timestamp(tamamlanmis.index[-1]).date()
    if son_tarih >= beklenen:
        meta.update(ok=True, veri_durumu='guncel')
        return tamamlanmis, meta

    try:
        intraday = ticker.history(period='5d', interval='1m', prepost=False)
    except Exception:
        intraday = None
    gunluk_onarim = _dakikalik_barlari_gunluge_cevir(
        intraday,
        now=now,
        timezone=timezone,
    )

    if gunluk_onarim is not None and not gunluk_onarim.empty:
        mevcut_tarihler = set(pd.DatetimeIndex(tamamlanmis.index).date)
        eklenecek = gunluk_onarim[
            [tarih not in mevcut_tarihler for tarih in pd.DatetimeIndex(gunluk_onarim.index).date]
        ]
        if not eklenecek.empty:
            tamamlanmis = pd.concat([tamamlanmis, eklenecek], axis=0, sort=False)
            tamamlanmis = tamamlanmis[~tamamlanmis.index.duplicated(keep='last')].sort_index()
            meta['onarilan_gunluk_barlar'] = [
                str(tarih) for tarih in pd.DatetimeIndex(eklenecek.index).date
            ]

    son_tarih = pd.Timestamp(tamamlanmis.index[-1]).date()
    meta['last_completed_daily_bar'] = _bar_tarihi(tamamlanmis)
    if son_tarih >= beklenen:
        meta.update(ok=True, veri_durumu='dakikalik_veriden_onarildi')
        return tamamlanmis, meta

    # Resmî tatil gibi işlem olmayan günlerde aday tarih ileri kalabilir.
    # Son kapanışın kotasyonla uyumu, eldeki son seansın güncel olduğunu doğrular.
    fiyat_bilgisi = _canli_fiyat_bilgisi(ticker)
    onceki_kapanis = fiyat_bilgisi['onceki_kapanis']
    son_kapanis = float(tamamlanmis['Close'].iloc[-1])
    if onceki_kapanis is not None:
        fark = abs(son_kapanis - onceki_kapanis) / onceki_kapanis
        if fark <= QUOTE_CLOSE_TOLERANCE:
            meta.update(ok=True, veri_durumu='kotasyonla_dogrulandi')
            return tamamlanmis, meta

    meta['veri_durumu'] = 'bayat_veya_eksik'
    return tamamlanmis, meta


def _gecerli_pe(deger):
    try:
        pe = float(deger)
    except (TypeError, ValueError):
        return None
    return pe if np.isfinite(pe) and 0 < pe < 200 else None


def _alan_oku(nesne, alan):
    if nesne is None:
        return None
    try:
        if hasattr(nesne, 'get'):
            deger = nesne.get(alan)
            if deger is not None:
                return deger
    except Exception:
        pass
    try:
        return getattr(nesne, alan, None)
    except Exception:
        return None


def _ticker_trailing_pe(ticker, info=None):
    """fast_info yetersizse ticker.info üzerinden doğrulanmış trailing P/E döndürür."""
    try:
        fast_info = ticker.fast_info
    except Exception:
        fast_info = None

    for alan in ('trailing_pe', 'pe_ratio', 'trailingPE'):
        pe = _gecerli_pe(_alan_oku(fast_info, alan))
        if pe is not None:
            return pe

    if info is None:
        try:
            info = ticker.info
        except Exception:
            info = None
    return _gecerli_pe(_alan_oku(info, 'trailingPE'))


def _skor_degeri(sinyal):
    """Yeni kural skoru alanını, eski kayıtlarla geriye uyumlu biçimde okur."""
    return sinyal.get('kural_skoru', sinyal.get('ai_skor', 0))


def vix_oku():
    """VIX (Korku Endeksi) değerini çeker. Hata durumunda 20 (nötr) döner."""
    try:
        vix = yf.Ticker('^VIX')
        df = vix.history(period='5d')
        if df is not None and not df.empty:
            return float(df['Close'].iloc[-1])
    except:
        pass
    return 20.0  # Varsayılan: Normal piyasa

def spy_12ay_getiri(now=None):
    """S&P 500'ün son 12 aylık getirisini hesaplar (RS Skoru için)."""
    try:
        spy = yf.Ticker('SPY')
        df = spy.history(period='1y')
        df, veri_meta = _gunluk_veriyi_hazirla(spy, df, now=now)
        if veri_meta['ok'] and df is not None and len(df) > 20:
            return (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0]
    except:
        pass
    return 0.10  # Varsayılan: %10

def bilanco_yakin_mi(sembol, gun_esik=7):
    """Bilanço açıklamasına 7 gün kala True döner (Earnings Blackout)."""
    try:
        ticker = yf.Ticker(sembol)
        calendar = ticker.calendar
        bugun = datetime.now().date()
        esik_tarih = bugun + timedelta(days=gun_esik)

        if isinstance(calendar, dict) and "Earnings Date" in calendar:
            for tar in calendar["Earnings Date"]:
                t_date = tar.date() if hasattr(tar, 'date') else tar
                if bugun <= t_date <= esik_tarih:
                    return True
        elif isinstance(calendar, pd.DataFrame) and 'Earnings Date' in calendar.index:
            date_val = calendar.loc['Earnings Date'].iloc[0]
            t_date = date_val.date() if hasattr(date_val, 'date') else date_val
            if bugun <= t_date <= esik_tarih:
                return True
    except:
        pass
    return False

def sektor_rotasyonu_radar(now=None):
    """
    Sektör ETF'lerinin son 1 aylık performanslarını karşılaştırır.
    Paranın hangi sektöre aktığını tespit eder.
    Dönüş: {sektor_adi: performans_yuzde}  (Sıralı)
    """
    performanslar = {}
    for sektor, etf in SEKTOR_ETFLERI.items():
        try:
            t = yf.Ticker(etf)
            df = t.history(period='1mo')
            df, veri_meta = _gunluk_veriyi_hazirla(t, df, now=now)
            if veri_meta['ok'] and df is not None and len(df) > 2:
                getiri = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0] * 100
                performanslar[sektor] = round(getiri, 2)
            else:
                performanslar[sektor] = 0.0
            time.sleep(0.3)
        except:
            performanslar[sektor] = 0.0
    # En güçlüden en zayıfa sırala
    return dict(sorted(performanslar.items(), key=lambda x: x[1], reverse=True))

def sektor_pe_ortalamalari(havuz=None, cache_dosya='sektor_pe_cache.json', sleep_seconds=0.2):
    """Sektör medyan F/K değerlerini doğrulanmış veriyle ve sürümlü cache ile üretir."""
    havuz = KURUMSAL_HAVUZ if havuz is None else havuz

    if os.path.exists(cache_dosya):
        try:
            with open(cache_dosya, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            cache_data = cache.get('data', {})
            if (
                cache.get('schema_version') == 2
                and isinstance(cache_data, dict)
                and cache_data
                and time.time() - cache.get('ts', 0) < 86400
            ):
                return cache_data
        except Exception:
            pass

    sektor_pe = defaultdict(list)
    for sembol, sektor in havuz.items():
        try:
            pe = _ticker_trailing_pe(yf.Ticker(sembol))
            if pe is not None:
                sektor_pe[sektor].append(pe)
            if sleep_seconds:
                time.sleep(sleep_seconds)
        except Exception:
            pass

    ortalamalar = {
        sektor: round(float(np.median(pe_listesi)), 2)
        for sektor, pe_listesi in sektor_pe.items()
        if pe_listesi
    }

    # Boş sonuç cache'lenmez; geçici API sorunu 24 saat boyunca gizlenmesin.
    if ortalamalar:
        try:
            with open(cache_dosya, 'w', encoding='utf-8') as f:
                json.dump({
                    'schema_version': 2,
                    'ts': time.time(),
                    'data': ortalamalar,
                    'sample_counts': {k: len(v) for k, v in sektor_pe.items()},
                }, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    return ortalamalar

# ============================================================
#  3. ANA FİLTRELEME VE SKORLAMA MOTORU
# ============================================================

def hisse_analiz_et(
    sembol,
    sektor,
    vix_degeri,
    spy_getiri,
    sektor_pe_map,
    sektor_momentum,
    now=None,
):
    """
    Tek bir hisse için tam analiz pipeline'ı çalıştırır.

    AŞILAMAZ FİLTRELER:
      1. SMA 200 Kalkanı
      2. OBV Kurumsal Para Kontrolü
      3. RSI Fırsat Bölgesi (30-55)
      4. Aşırı Primi Reddi (Sapma > %40)

    SKORLAMA:
      - Baz Skor + RSI Bonusu + Mean Reversion + VIX Çarpanı
      - Golden Cross + Temel Analiz + Relatif Güç + Sektör Momentum

    Dönüş: Sinyal dict veya None (reddedildiyse)
    """
    try:
        ticker = yf.Ticker(sembol)

        # --- VERİ ÇEKİMİ (Günlük — 1 yıl) ---
        df_daily = ticker.history(period='1y', interval='1d')
        df_daily, veri_meta = _gunluk_veriyi_hazirla(ticker, df_daily, now=now)
        if not veri_meta['ok']:
            neden = (
                'Günlük veri bayat/eksik '
                f"(son={veri_meta['last_completed_daily_bar']}, "
                f"beklenen={veri_meta['beklenen_son_tamamlanmis_bar']})"
            )
            return {
                'sembol': sembol,
                'success': False,
                'red_sebebi': neden,
                'red_sebepleri': [neden],
                'veri_durumu': veri_meta['veri_durumu'],
                'last_completed_daily_bar': veri_meta['last_completed_daily_bar'],
                'beklenen_son_tamamlanmis_bar': veri_meta['beklenen_son_tamamlanmis_bar'],
                'onarilan_gunluk_barlar': veri_meta['onarilan_gunluk_barlar'],
                'kural_skoru': None,
                'scoring_mode': STOCK_SCORING_MODE,
                'score_version': STOCK_SCORE_VERSION,
            }
        if df_daily is None or df_daily.empty or len(df_daily) < 200:
            return None  # Yetersiz veri
        son_gunluk_bar = _bar_tarihi(df_daily)
        fiyat_bilgisi = _canli_fiyat_bilgisi(ticker)

        close = df_daily['Close']
        volume = df_daily['Volume']
        high = df_daily['High']
        low = df_daily['Low']
        son_fiyat = float(close.iloc[-1])

        # ========================================
        #  KATMAN 1: SMA 200 KALKANI (Aşılamaz)
        # ========================================
        sma_200 = ta.sma(close, length=200)
        if sma_200 is None or pd.isna(sma_200.iloc[-1]):
            return None
        sma_200_val = float(sma_200.iloc[-1])

        # ========================================
        #  KATMAN 2: OBV KURUMSAL PARA (Aşılamaz)
        # ========================================
        obv = ta.obv(close, volume)
        if obv is None or len(obv) < 20:
            return None
        obv_sma_20 = ta.sma(obv, length=20)
        if obv_sma_20 is None or pd.isna(obv_sma_20.iloc[-1]):
            return None

        obv_guncel = float(obv.iloc[-1])
        obv_sma_val = float(obv_sma_20.iloc[-1])

        # ========================================
        #  KATMAN 3: RSI FIRSAT BÖLGESİ (Aşılamaz)
        # ========================================
        rsi = ta.rsi(close, length=14)
        if rsi is None or pd.isna(rsi.iloc[-1]):
            return None
        rsi_val = float(rsi.iloc[-1])

        # ========================================
        #  KATMAN 4: MEAN REVERSION (Sapma Kontrolü)
        # ========================================
        sapma_yuzde = ((son_fiyat - sma_200_val) / sma_200_val) * 100

        red_sebepleri = []
        if son_fiyat < sma_200_val:
            red_sebepleri.append(f'SMA200 Altında ({son_fiyat:.2f} < {sma_200_val:.2f})')
        if obv_guncel < obv_sma_val:
            red_sebepleri.append('OBV < OBV_SMA20 (Kurumsal çıkış)')
        if rsi_val > 55:
            red_sebepleri.append(f'RSI Yüksek ({rsi_val:.1f} > 55)')
        elif rsi_val < 30:
            red_sebepleri.append(
                f'RSI Aşırı Düşük ({rsi_val:.1f} < 30) — Düşen bıçak riski'
            )
        if sapma_yuzde > 40.0:
            red_sebepleri.append(f'Aşırı Primlenmiş (%{sapma_yuzde:.1f} > %40)')

        if red_sebepleri:
            return {
                'sembol': sembol,
                'success': False,
                'red_sebebi': red_sebepleri[0],
                'red_sebepleri': red_sebepleri,
                'fiyat': round(son_fiyat, 2),
                'sma_200': round(sma_200_val, 2),
                'sapma_yuzde': round(sapma_yuzde, 1),
                'rsi': round(rsi_val, 1),
                'obv': round(obv_guncel, 2),
                'obv_sma_20': round(obv_sma_val, 2),
                'kural_skoru': None,
                'scoring_mode': STOCK_SCORING_MODE,
                'score_version': STOCK_SCORE_VERSION,
                'last_completed_daily_bar': son_gunluk_bar,
                'beklenen_son_tamamlanmis_bar': veri_meta['beklenen_son_tamamlanmis_bar'],
                'veri_durumu': veri_meta['veri_durumu'],
                'onarilan_gunluk_barlar': veri_meta['onarilan_gunluk_barlar'],
                'karar_fiyati': round(son_fiyat, 2),
                'canli_fiyat': (
                    round(fiyat_bilgisi['canli_fiyat'], 2)
                    if fiyat_bilgisi['canli_fiyat'] is not None else None
                ),
                'price_basis': 'completed_daily_close',
            }

        # ========================================
        #  KATMAN 5: BİLANÇO BLACKOUT (7 Gün)
        # ========================================
        if bilanco_yakin_mi(sembol, gun_esik=7):
            neden = 'Bilanço Blackout (7 gün içinde kazanç açıklaması)'
            return {
                'sembol': sembol,
                'success': False,
                'red_sebebi': neden,
                'red_sebepleri': [neden],
                'kural_skoru': None,
                'scoring_mode': STOCK_SCORING_MODE,
                'score_version': STOCK_SCORE_VERSION,
                'last_completed_daily_bar': son_gunluk_bar,
                'beklenen_son_tamamlanmis_bar': veri_meta['beklenen_son_tamamlanmis_bar'],
                'veri_durumu': veri_meta['veri_durumu'],
                'onarilan_gunluk_barlar': veri_meta['onarilan_gunluk_barlar'],
                'karar_fiyati': round(son_fiyat, 2),
                'canli_fiyat': (
                    round(fiyat_bilgisi['canli_fiyat'], 2)
                    if fiyat_bilgisi['canli_fiyat'] is not None else None
                ),
                'price_basis': 'completed_daily_close',
            }

        # ============================================================
        #  SKORLAMA MOTORU — Tüm filtreleri geçti, puan topla
        # ============================================================
        baz_skor = 50.0  # Filtreleri geçmenin ödülü

        # --- RSI Pozisyon Bonusu ---
        if 30 <= rsi_val <= 40:
            baz_skor += 15   # Dip fırsatı
        elif 40 < rsi_val <= 50:
            baz_skor += 10   # Toparlanma
        elif 50 < rsi_val <= 55:
            baz_skor += 5    # Nötr-güçlü

        # --- Mean Reversion Bonusu ---
        if 5.0 <= sapma_yuzde <= 10.0:
            baz_skor += 10   # İdeal alım bölgesi
        elif 10.0 < sapma_yuzde <= 20.0:
            baz_skor += 5    # Makul
        elif sapma_yuzde > 20.0:
            baz_skor -= 10   # Riskli (ama %40 altında olduğu için reddedilmedi)

        # --- VIX Makro Risk Çarpanı ---
        vix_penalti = False
        if vix_degeri > 25:
            baz_skor *= 0.85  # %15 kesinti
            vix_penalti = True

        # --- SMA 50 ve Golden Cross Çarpanı ---
        sma_50 = ta.sma(close, length=50)
        golden_cross = False
        sma_50_val = None
        if sma_50 is not None and not pd.isna(sma_50.iloc[-1]):
            sma_50_val = float(sma_50.iloc[-1])
            if sma_50_val > sma_200_val:
                baz_skor += 15  # Golden Cross aktif
                golden_cross = True

        # --- Temel Analiz Çarpanı ---
        pe_orani = None
        ebitda_marji = None
        sektor_pe_ort = _gecerli_pe(sektor_pe_map.get(sektor))
        temel_bonus = 0
        try:
            info = ticker.info
            pe_orani = _ticker_trailing_pe(ticker, info=info)
            # Bu alan büyüme değil, EBITDA marjıdır.
            ebitda_marji = info.get('ebitdaMargins', None)

            # F/K sektör ortalamasının altındaysa
            if pe_orani is not None and sektor_pe_ort is not None and pe_orani < sektor_pe_ort:
                temel_bonus += 10
                baz_skor += 10

            # EBITDA marjı pozitifse
            if ebitda_marji is not None and ebitda_marji > 0:
                temel_bonus += 5
                baz_skor += 5
        except:
            pass

        # --- Relatif Güç (RS) — IBD Stili ---
        rs_skor = 50  # Varsayılan
        try:
            if len(df_daily) >= 252:  # 1 yıllık veri varsa
                hisse_getiri = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]
            else:
                hisse_getiri = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]

            if spy_getiri > 0:
                rs_ham = (hisse_getiri / spy_getiri) * 50 + 50  # 0-100 arası normalize
                rs_skor = max(0, min(100, rs_ham))

            if rs_skor >= 80:
                baz_skor += 10   # Kurumsal favori
            elif rs_skor >= 60:
                baz_skor += 5
        except:
            pass

        # --- Sektör Momentum Bonusu ---
        sektor_perf = sektor_momentum.get(sektor, 0.0)
        if sektor_perf > 3.0:
            baz_skor += 5    # Para bu sektöre akıyor
        elif sektor_perf < -3.0:
            baz_skor -= 5    # Para bu sektörden kaçıyor

        # --- Çoklu Zaman Dilimi Teyidi (MTF — Haftalık RSI) ---
        mtf_uyumlu = True
        rsi_weekly = None
        son_haftalik_bar = None
        try:
            df_weekly = ticker.history(period='2y', interval='1wk')
            df_weekly = _tamamlanmis_barlari_sec(df_weekly, '1wk', now=now)
            son_haftalik_bar = _bar_tarihi(df_weekly)
            if df_weekly is not None and len(df_weekly) >= 14:
                rsi_w = ta.rsi(df_weekly['Close'], length=14)
                if rsi_w is not None and not pd.isna(rsi_w.iloc[-1]):
                    rsi_weekly = float(rsi_w.iloc[-1])
                    if rsi_weekly > 70:
                        baz_skor -= 10  # Haftalık aşırı alım — sinyal zayıflatıldı
                        mtf_uyumlu = False
                    elif rsi_weekly < 40:
                        baz_skor += 5   # Haftalık RSI de dipte — güçlü teyit
        except:
            pass

        # Final skor (0-100 arası sınırla)
        final_skor = max(0, min(100, round(baz_skor, 1)))

        # --- ATR Tabanlı TP/SL Hesaplaması ---
        atr = ta.atr(high, low, close, length=14)
        atr_val = float(atr.iloc[-1]) if atr is not None and not pd.isna(atr.iloc[-1]) else son_fiyat * 0.02
        tp_fiyat = round(son_fiyat + (atr_val * 3.0), 2)   # 3 ATR (Uzun vadeli)
        sl_fiyat = round(son_fiyat - (atr_val * 1.5), 2)    # 1.5 ATR
        rr_orani = round((tp_fiyat - son_fiyat) / (son_fiyat - sl_fiyat), 2) if (son_fiyat - sl_fiyat) > 0 else 0

        # --- KADEMELİ ALIM PLANI ---
        pullback_hedef = round(sma_50_val, 2) if sma_50_val else round(son_fiyat * 0.97, 2)

        return {
            'sembol': sembol,
            'sektor': sektor,
            'fiyat': round(son_fiyat, 2),
            'karar_fiyati': round(son_fiyat, 2),
            'canli_fiyat': (
                round(fiyat_bilgisi['canli_fiyat'], 2)
                if fiyat_bilgisi['canli_fiyat'] is not None else None
            ),
            'price_basis': 'completed_daily_close',
            'sma_200': round(sma_200_val, 2),
            'sma_50': round(sma_50_val, 2) if sma_50_val else None,
            'sapma_yuzde': round(sapma_yuzde, 1),
            'rsi': round(rsi_val, 1),
            'obv_durum': 'Pozitif ✅',
            'golden_cross': golden_cross,
            'vix_penalti': vix_penalti,
            'pe_orani': round(pe_orani, 1) if pe_orani else None,
            'sektor_pe_ort': round(sektor_pe_ort, 1) if sektor_pe_ort else None,
            'ebitda_marji': round(float(ebitda_marji), 4) if ebitda_marji is not None else None,
            'temel_bonus': temel_bonus,
            'rs_skor': round(rs_skor, 1),
            'mtf_uyumlu': mtf_uyumlu,
            'sektor_momentum': round(sektor_perf, 2),
            'kural_skoru': final_skor,
            'ai_skor': final_skor,  # Eski tüketiciler için geçici uyumluluk alanı.
            'scoring_mode': STOCK_SCORING_MODE,
            'score_version': STOCK_SCORE_VERSION,
            'last_completed_daily_bar': son_gunluk_bar,
            'beklenen_son_tamamlanmis_bar': veri_meta['beklenen_son_tamamlanmis_bar'],
            'veri_durumu': veri_meta['veri_durumu'],
            'onarilan_gunluk_barlar': veri_meta['onarilan_gunluk_barlar'],
            'last_completed_weekly_bar': son_haftalik_bar,
            'weekly_rsi': round(rsi_weekly, 1) if rsi_weekly is not None else None,
            'tp': tp_fiyat,
            'sl': sl_fiyat,
            'rr': rr_orani,
            'atr': round(atr_val, 2),
            # Kademeli Alım
            'faz1_butce_yuzde': 0.30,  # %30 anında
            'faz2_butce_yuzde': 0.70,  # %70 pullback
            'pullback_hedef': pullback_hedef,
            'sinyal': 'AL',
            'success': True,
        }

    except Exception as e:
        return {'sembol': sembol, 'red_sebebi': f'Analiz Hatası: {str(e)[:80]}'}


# ============================================================
#  4. PORTFÖY ISI SINIRI (Sektör Ağırlık Kontrolü)
# ============================================================

# Mevcut portföydeki açık pozisyonları takip eder
PORTFOY_POZISYONLARI = {}  # {sembol: {sektor, butce_yuzde, ...}}

def sektor_agirligi_kontrol(sektor, yeni_butce_yuzde=0.05):
    """
    Sektör ağırlığının %30 sınırını aşıp aşmadığını kontrol eder.
    True: Alıma izin var.  False: Sektör dolu.
    """
    mevcut_agirlik = 0.0
    for sym, poz in PORTFOY_POZISYONLARI.items():
        if poz.get('sektor') == sektor:
            mevcut_agirlik += poz.get('butce_yuzde', 0.05)

    if mevcut_agirlik + yeni_butce_yuzde > 0.30:
        return False, round(mevcut_agirlik * 100, 1)
    return True, round(mevcut_agirlik * 100, 1)


# ============================================================
#  5. SİNYAL BÜLTENİ OLUŞTURUCU
# ============================================================

def sinyal_bulteni_olustur(sinyaller, vix_degeri, sektor_perf):
    """Terminale ve Telegram'a gönderilecek formatlı sinyal bülteni oluşturur."""

    baslik = f"""
╔══════════════════════════════════════════════════════════════════╗
║  🏦 HİSSE SİNYAL BÜLTENİ — {datetime.now().strftime('%d/%m/%Y %H:%M')}
║  📊 VIX: {vix_degeri:.1f} {'🟢 NORMAL' if vix_degeri < 25 else '🟡 PANİK' if vix_degeri < 35 else '🔴 CRASH'}
║  🎯 Mod: DANIŞMAN (Sinyal Üretir, İşlem Açmaz)
╚══════════════════════════════════════════════════════════════════╝"""

    print(baslik)

    if not sinyaller:
        print("\n  ⏳ Tüm filtreleri geçen sinyal bulunamadı. Piyasa koşulları uygun değil.")
        print("     Sabırlı ol Kaptan, asimetrik fırsat gelecek.\n")
        return baslik + "\n  ⏳ Sinyal yok."

    # Sektör rotasyonu özeti
    print("\n  📡 SEKTÖR ROTASYONU (Son 1 Ay):")
    print("  " + "─" * 50)
    for sek, perf in list(sektor_perf.items())[:5]:
        ikon = "🟢" if perf > 0 else "🔴"
        print(f"    {ikon} {sek:<20} {perf:+.2f}%")
    print("  " + "─" * 50)

    # Sinyaller tablosu
    bulten_metin = baslik
    print(f"\n  🏆 FİLTRELERDEN GEÇEN {len(sinyaller)} SİNYAL (Skor > %70):\n")

    for i, s in enumerate(sinyaller, 1):
        # Sektör ağırlığı kontrolü
        sektor_izin, mevcut_agirlik = sektor_agirligi_kontrol(s['sektor'])
        sektor_durum = f"✅ %{mevcut_agirlik}" if sektor_izin else f"🛑 DOLU %{mevcut_agirlik}"

        gc = "✅ Aktif" if s.get('golden_cross') else "❌ Yok"
        mtf = "✅ Uyumlu" if s.get('mtf_uyumlu') else "⚠️ Uyumsuz"
        vix_d = "⚠️ -15%" if s.get('vix_penalti') else "✅ Temiz"

        satir = f"""  {'━' * 58}
  📈 #{i}  {s['sembol']}  |  LONG  |  🎯 Kural Skoru: %{_skor_degeri(s):.0f}
  {'━' * 58}
     Karar Kapanışı: ${s['fiyat']:.2f}   |  Canlı: {f"${s['canli_fiyat']:.2f}" if s.get('canli_fiyat') else 'N/A'}
     SMA200: ${s['sma_200']:.2f}  |  SMA50: ${s.get('sma_50', 'N/A')}
     RSI(14): {s['rsi']:.1f}      |  OBV: {s['obv_durum']}  |  ATR: ${s['atr']:.2f}
     Sapma: %{s['sapma_yuzde']:.1f}    |  R/R: {s['rr']:.1f}x
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
     🏛️ Sektör: {s['sektor']:<18}  |  Ağırlık: {sektor_durum}
     📊 F/K: {s.get('pe_orani', 'N/A')}  |  Temel Bonus: +{s.get('temel_bonus', 0)}
     💪 RS Skoru: {s.get('rs_skor', 50):.0f}/100  |  Sektör Mom.: {s.get('sektor_momentum', 0):+.1f}%
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
     🔍 Golden Cross: {gc}  |  MTF: {mtf}  |  VIX: {vix_d}
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
     🎯 TP: ${s['tp']:.2f}   |  🛑 SL: ${s['sl']:.2f}
     💰 Faz 1: %30 Bütçe → HEMEN (${s['fiyat']:.2f})
     ⏳ Faz 2: %70 Bütçe → Pullback Bekle (${s.get('pullback_hedef', 0):.2f})
  {'━' * 58}"""

        print(satir)
        bulten_metin += satir

    print(f"\n  📋 Toplam: {len(sinyaller)} sinyal | Minimum Skor: %70 | Mod: Danışman")
    print(f"  ⚠️  Bu bülten yatırım tavsiyesi DEĞİLDİR. Nihai karar Kaptan'a aittir.\n")

    return bulten_metin


def telegram_bulten_gonder(bulten_metin, sinyaller):
    """Telegram'a özet sinyal bilgisi gönderir."""
    try:
        # ayar.json'dan Telegram konfigürasyonu oku
        with open('ayar.json', 'r', encoding='utf-8') as f:
            ayar = json.load(f)

        tg = ayar.get('telegram', {})
        if not tg.get('aktif_mi', False):
            return

        bot_token = tg.get('bot_token', '')
        chat_id = tg.get('chat_id', '')
        if not bot_token or not chat_id:
            return

        # Kısa Telegram özeti oluştur
        mesaj = f"🏦 *HİSSE SİNYAL BÜLTENİ*\n"
        mesaj += f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        mesaj += f"{'─' * 30}\n"

        if not sinyaller:
            mesaj += "⏳ Filtrelerden geçen sinyal yok.\n"
        else:
            for i, s in enumerate(sinyaller[:5], 1):  # Max 5 sinyal
                mesaj += f"\n📈 *#{i} {s['sembol']}* | Kural Skoru: %{_skor_degeri(s):.0f}\n"
                mesaj += f"   Kapanış: ${s['fiyat']:.2f}"
                if s.get('canli_fiyat'):
                    mesaj += f" | Canlı: ${s['canli_fiyat']:.2f}"
                mesaj += f" | RSI: {s['rsi']:.0f}\n"
                mesaj += f"   TP: ${s['tp']:.2f} | SL: ${s['sl']:.2f}\n"

            if len(sinyaller) > 5:
                mesaj += f"\n...+{len(sinyaller)-5} sinyal daha\n"

        mesaj += f"\n⚠️ _Danışman Modu — Otomatik işlem açılmaz._"

        requests.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            data={"chat_id": chat_id, "text": mesaj, "parse_mode": "Markdown"},
            timeout=10
        )
    except:
        pass


# ============================================================
#  6. HAFTALIK PORTFÖY REBALANCING RAPORU
# ============================================================

def haftalik_rebalancing_raporu():
    """
    Her Pazar gecesi çalıştırılması önerilen portföy kontrol raporu.
    Sektör yoğunlaşması ve pozisyon durumlarını kontrol eder.
    """
    print("\n" + "=" * 60)
    print("  📊 HAFTALIK PORTFÖY REBALANCİNG RAPORU")
    print(f"  📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("=" * 60)

    if not PORTFOY_POZISYONLARI:
        print("  ℹ️ Portföyde açık pozisyon bulunmuyor.\n")
        return

    # Sektör dağılımı
    sektor_toplam = defaultdict(float)
    for sym, poz in PORTFOY_POZISYONLARI.items():
        sektor_toplam[poz.get('sektor', 'Bilinmiyor')] += poz.get('butce_yuzde', 0.05)

    print("\n  🏭 SEKTÖR DAĞILIMI:")
    for sek, agirlik in sorted(sektor_toplam.items(), key=lambda x: x[1], reverse=True):
        bar = "█" * int(agirlik * 100 / 3) + "░" * (10 - int(agirlik * 100 / 3))
        uyari = " ⚠️ SINIRA YAKIN!" if agirlik >= 0.25 else ""
        print(f"    {sek:<20} [{bar}] %{agirlik*100:.0f}{uyari}")

    print("\n  📋 AKTİF POZİSYONLAR:")
    for sym, poz in PORTFOY_POZISYONLARI.items():
        print(f"    {sym:<8} | {poz.get('sektor', 'N/A'):<18} | Bütçe: %{poz.get('butce_yuzde', 0)*100:.0f}")

    print("\n" + "=" * 60 + "\n")


# ============================================================
#  7.  İŞLEM KAYIT SİSTEMİ (SQLite)
# ============================================================

def sinyal_kaydet(sinyaller):
    """Üretilen sinyalleri SQLite veritabanına kaydeder (geçmiş takibi için)."""
    try:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db')
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS hisse_sinyalleri (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tarih TEXT, sembol TEXT, sektor TEXT, fiyat REAL,
            sma200 REAL, rsi REAL, ai_skor REAL, tp REAL, sl REAL,
            golden_cross INTEGER, vix REAL, rs_skor REAL
        )''')

        for s in sinyaller:
            cursor.execute('''INSERT INTO hisse_sinyalleri
                (tarih, sembol, sektor, fiyat, sma200, rsi, ai_skor, tp, sl, golden_cross, vix, rs_skor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (datetime.now().strftime('%Y-%m-%d %H:%M'),
                 s['sembol'], s['sektor'], s['fiyat'], s['sma_200'],
                 s['rsi'], _skor_degeri(s), s['tp'], s['sl'],
                 1 if s.get('golden_cross') else 0,
                 vix_oku(), s.get('rs_skor', 50)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"  ⚠️ Sinyal kayıt hatası: {e}")


# ============================================================
#  8. ANA TARAMA DÖNGÜSÜ
# ============================================================

def tam_tarama_baslat():
    """
    Ana tarama fonksiyonu. Tüm havuzu filtreleme pipeline'ından geçirir,
    skorlar, sıralar ve sinyal bülteni üretir.
    """
    print("\n" + "🔵" * 30)
    print("  🏦 STOCK VALUE ENGINE — DANIŞMAN MODU")
    print("  📊 Wall Street Kalibresinde Değer & Momentum Tarayıcı")
    print("  ⏰ Timeframe: Günlük (1D) + Haftalık (1W)")
    print("  🎯 Hedef: 3-12 Ay Elde Tutma")
    print("🔵" * 30)

    # --- ÖN HAZIRLIK ---
    print("\n  ⚙️ Makro veriler hazırlanıyor...")

    vix_degeri = vix_oku()
    print(f"    📊 VIX: {vix_degeri:.1f} — {'🟢 NORMAL' if vix_degeri < 25 else '🟡 PANİK' if vix_degeri < 35 else '🔴 CRASH'}")

    if vix_degeri > 35:
        print("\n  🔴 [CRASH MODU] VIX > 35! Tarama iptal edildi. Nakit pozisyonda kal Kaptan!")
        return []

    spy_getiri = spy_12ay_getiri()
    print(f"    📈 S&P 500 (12 Ay): %{spy_getiri*100:.1f}")

    print("    🏭 Sektör rotasyonu hesaplanıyor...")
    sektor_perf = sektor_rotasyonu_radar()
    for sek, perf in list(sektor_perf.items())[:3]:
        ikon = "↑" if perf > 0 else "↓"
        print(f"      {ikon} {sek}: {perf:+.1f}%")

    print("    📊 Sektör P/E ortalamaları hesaplanıyor...")
    sektor_pe_map = sektor_pe_ortalamalari()

    # --- ANA TARAMA ---
    havuz_listesi = list(KURUMSAL_HAVUZ.items())
    toplam = len(havuz_listesi)
    print(f"\n  🔍 TARAMA BAŞLIYOR — {toplam} hisse analiz edilecek...\n")

    basarili_sinyaller = []
    reddedilen_log = []
    islenen = 0

    for sembol, sektor in havuz_listesi:
        islenen += 1

        # İlerleme göstergesi (her 10 hissede bir)
        if islenen % 10 == 0 or islenen == toplam:
            print(f"    [{islenen}/{toplam}] Taranıyor... ({sembol})")

        sonuc = hisse_analiz_et(sembol, sektor, vix_degeri, spy_getiri, sektor_pe_map, sektor_perf)

        if sonuc is None:
            continue

        if sonuc.get('success'):
            # %70 skor eşiği kontrolü
            skor = _skor_degeri(sonuc)
            if skor >= 70:
                basarili_sinyaller.append(sonuc)
            else:
                reddedilen_log.append({
                    'sembol': sembol,
                    'red_sebebi': f"Yetersiz Kural Skoru (%{skor:.0f} < %70)"
                })
        elif 'red_sebebi' in sonuc:
            reddedilen_log.append(sonuc)

        # Rate limit koruması (yfinance ban önleme)
        time.sleep(0.5)

    # --- SIRALAMA (Kural Skoru — Yüksekten düşüğe) ---
    basarili_sinyaller.sort(key=_skor_degeri, reverse=True)

    # --- REDDEDILEN LOG (Debug) ---
    print(f"\n  📋 TARAMA SONUCU: {toplam} hisse tarandı")
    print(f"    ✅ Filtrelerden geçen: {len(basarili_sinyaller)}")
    print(f"    ❌ Reddedilen: {len(reddedilen_log)}")

    if reddedilen_log:
        print(f"\n  🔍 [DEBUG] En Sık Red Sebepleri (Top 5):")
        sebep_sayac = defaultdict(int)
        for r in reddedilen_log:
            sebepler = r.get('red_sebepleri') or [r.get('red_sebebi', 'Bilinmiyor')]
            for red_sebebi in sebepler:
                # Sebebin ilk kelimelerini gruplayarak say
                sebep = red_sebebi.split('(')[0].strip()
                sebep_sayac[sebep] += 1
        for sebep, sayi in sorted(sebep_sayac.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"    • {sebep}: {sayi} hisse")

    # --- BÜLTENİ ÜRET ---
    bulten = sinyal_bulteni_olustur(basarili_sinyaller, vix_degeri, sektor_perf)

    # --- TELEGRAM'A GÖNDER ---
    telegram_bulten_gonder(bulten, basarili_sinyaller)

    # --- VERİTABANINA KAYDET ---
    if basarili_sinyaller:
        sinyal_kaydet(basarili_sinyaller)

    return basarili_sinyaller


# ============================================================
#  9. ÇALIŞTIRILMA MODU
# ============================================================

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════╗")
    print("║  🏦 STOCK VALUE ENGINE v1.0                        ║")
    print("║  Danışman Modu — Sinyal Üretir, İşlem Açmaz        ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    try:
        sinyaller = tam_tarama_baslat()

        if sinyaller:
            print(f"\n  ✅ {len(sinyaller)} sinyal üretildi ve veritabanına kaydedildi.")
        else:
            print("\n  ⏳ Filtre kriterlerini karşılayan sinyal bulunamadı.")

        # Haftalık rebalancing raporu (isteğe bağlı)
        if datetime.now().weekday() == 6:  # Pazar günü
            haftalik_rebalancing_raporu()

    except KeyboardInterrupt:
        print("\n  🛑 Tarama Kaptan tarafından manuel olarak durduruldu.")
    except Exception as e:
        print(f"\n  ❌ Kritik Hata: {e}")
