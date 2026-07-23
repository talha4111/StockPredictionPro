"""
STOCK VALUE ENGINE v3.1 - Cross-sectional stock research engine.
Mode: Advisor. It scans and analyzes equities but never sends orders.
Horizon: Daily/weekly observations for a 3-12 month research horizon.

The active model ranks quality, value, momentum and risk across the current
universe, then classifies trend continuation, quality pullback and wait states.
The legacy absolute score remains only for backward-compatible imports.
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
import numpy as np
import time
import json
import os
import requests
import sqlite3
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv

    load_dotenv(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
        override=False,
    )
except ImportError:
    pass

from stock_scan_report import generate_stock_scan_report

from stock_signal_tracker import (
    performans_ozeti,
    sinyal_sonuclarini_guncelle,
    sonuc_semasini_hazirla,
)
from stock_shadow_paper import (
    BASELINE_MODEL_ID,
    CHALLENGER_MODEL_ID,
    MODEL_SPECS as PAPER_MODEL_SPECS,
    cohort_month_from_rows,
    select_monthly_top20,
    shadow_performance_summary,
)


class _TechnicalIndicators:
    @staticmethod
    def sma(series, length):
        return series.astype(float).rolling(window=length, min_periods=length).mean()

    @staticmethod
    def rsi(series, length=14):
        delta = series.astype(float).diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
        rs = avg_gain / avg_loss.replace(0.0, np.nan)
        result = 100.0 - (100.0 / (1.0 + rs))
        result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
        return result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)

    @staticmethod
    def obv(close, volume):
        direction = np.sign(close.astype(float).diff()).fillna(0.0)
        return (direction * volume.astype(float)).cumsum()

    @staticmethod
    def atr(high, low, close, length=14):
        previous_close = close.astype(float).shift(1)
        ranges = pd.concat(
            [
                high.astype(float) - low.astype(float),
                (high.astype(float) - previous_close).abs(),
                (low.astype(float) - previous_close).abs(),
            ],
            axis=1,
        )
        true_range = ranges.max(axis=1)
        return true_range.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()

    @staticmethod
    def macd(close, fast=12, slow=26, signal=9):
        values = close.astype(float)
        fast_ema = values.ewm(span=fast, adjust=False, min_periods=fast).mean()
        slow_ema = values.ewm(span=slow, adjust=False, min_periods=slow).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
        histogram = macd_line - signal_line
        return pd.concat(
            [
                macd_line.rename('MACD'),
                signal_line.rename('MACD_SIGNAL'),
                histogram.rename('MACD_HIST'),
            ],
            axis=1,
        )

    @staticmethod
    def bbands(close, length=20, std=2):
        values = close.astype(float)
        middle = values.rolling(window=length, min_periods=length).mean()
        deviation = values.rolling(window=length, min_periods=length).std(ddof=0)
        return pd.concat(
            [
                (middle - std * deviation).rename('BB_LOWER'),
                middle.rename('BB_MIDDLE'),
                (middle + std * deviation).rename('BB_UPPER'),
            ],
            axis=1,
        )


ta = _TechnicalIndicators()


def _pozitif_env_int(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        return value if value > 0 else default
    except (TypeError, ValueError):
        return default


ENGINE_VERSION = '3.1-factor-v1'
MAX_DAILY_DATA_BUSINESS_DAYS = _pozitif_env_int('STOCK_MAX_DATA_BUSINESS_DAYS', 3)
YFINANCE_CACHE_DIR = os.getenv(
    'YFINANCE_CACHE_DIR',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache', 'yfinance'),
)

try:
    os.makedirs(YFINANCE_CACHE_DIR, exist_ok=True)
    yf.set_tz_cache_location(YFINANCE_CACHE_DIR)
except OSError:
    pass


@dataclass(frozen=True)
class VeriSonucu:
    value: Any = None
    status: str = 'ERROR'
    source: str = 'yfinance'
    as_of: Optional[str] = None
    error: Optional[str] = None

    @property
    def uygun(self):
        return self.status == 'OK' and self.value is not None


SON_TARAMA_DURUMU = {
    'status': 'NOT_STARTED',
    'message': 'Tarama henuz baslamadi',
    'updated_at': None,
}


def _tarama_durumu_guncelle(status, message):
    global SON_TARAMA_DURUMU
    SON_TARAMA_DURUMU = {
        'status': status,
        'message': message,
        'updated_at': datetime.now().isoformat(timespec='seconds'),
    }


def son_tarama_durumu_oku():
    return dict(SON_TARAMA_DURUMU)


def _indeks_tarihi(index_value):
    try:
        return pd.Timestamp(index_value).date().isoformat()
    except Exception:
        return None


def gunluk_veri_taze_mi(df, now=None, max_business_days=None):
    """Return data freshness and its last trading date for a daily price frame."""
    if df is None or df.empty:
        return False, None

    veri_tarihi = _indeks_tarihi(df.index[-1])
    if veri_tarihi is None:
        return False, None

    bugun = (now or datetime.now()).date()
    son_gun = pd.Timestamp(veri_tarihi).date()
    if son_gun > bugun:
        return False, veri_tarihi

    esik = MAX_DAILY_DATA_BUSINESS_DAYS if max_business_days is None else max_business_days
    is_gunu_farki = int(np.busday_count(son_gun.isoformat(), bugun.isoformat()))
    return is_gunu_farki <= esik, veri_tarihi


def tamamlanmis_gunluk_veri(df, now=None):
    """Exclude today's US daily bar until the regular session has settled."""
    if df is None or df.empty:
        return df
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current_ny = current.astimezone(ZoneInfo('America/New_York'))
    last_date = pd.Timestamp(df.index[-1]).date()
    if last_date == current_ny.date() and (current_ny.hour, current_ny.minute) < (16, 15):
        return df.iloc[:-1].copy()
    return df


def temettu_verimi_normalize(info):
    """Return dividend yield as a decimal ratio regardless of yfinance display units."""
    trailing_yield = info.get('trailingAnnualDividendYield')
    if trailing_yield is not None and np.isfinite(trailing_yield) and trailing_yield >= 0:
        return float(trailing_yield)

    dividend_rate = info.get('dividendRate')
    current_price = info.get('currentPrice') or info.get('regularMarketPrice')
    if dividend_rate is not None and current_price and current_price > 0:
        return max(0.0, float(dividend_rate) / float(current_price))

    displayed_yield = info.get('dividendYield')
    if displayed_yield is not None and np.isfinite(displayed_yield) and displayed_yield >= 0:
        return float(displayed_yield) / 100.0
    return None

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

def vix_verisi_oku():
    """Fetch VIX with provenance. Missing data never becomes a neutral value."""
    try:
        vix = yf.Ticker('^VIX')
        df = vix.history(period='5d')
        df = tamamlanmis_gunluk_veri(df)
        if df is not None and not df.empty:
            taze, veri_tarihi = gunluk_veri_taze_mi(df)
            if not taze:
                return VeriSonucu(as_of=veri_tarihi, error='VIX verisi guncel degil')
            deger = float(df['Close'].iloc[-1])
            if np.isfinite(deger) and deger > 0:
                return VeriSonucu(value=deger, status='OK', as_of=veri_tarihi)
        return VeriSonucu(error='VIX verisi bos veya gecersiz')
    except Exception as exc:
        return VeriSonucu(error=f'{type(exc).__name__}: {str(exc)[:120]}')


def vix_oku():
    return vix_verisi_oku().value


def spy_12ay_verisi_oku():
    """Fetch SPY 12-month return with provenance and explicit failure state."""
    try:
        spy = yf.Ticker('SPY')
        df = spy.history(period='1y')
        df = tamamlanmis_gunluk_veri(df)
        if df is not None and len(df) > 20:
            taze, veri_tarihi = gunluk_veri_taze_mi(df)
            if not taze:
                return VeriSonucu(as_of=veri_tarihi, error='SPY verisi guncel degil')
            ilk = float(df['Close'].iloc[0])
            son = float(df['Close'].iloc[-1])
            if np.isfinite(ilk) and np.isfinite(son) and ilk > 0:
                getiri = (son - ilk) / ilk
                return VeriSonucu(value=getiri, status='OK', as_of=veri_tarihi)
        return VeriSonucu(error='SPY verisi bos veya yetersiz')
    except Exception as exc:
        return VeriSonucu(error=f'{type(exc).__name__}: {str(exc)[:120]}')


def spy_12ay_getiri():
    return spy_12ay_verisi_oku().value

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

def sektor_rotasyonu_radar():
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
            df = tamamlanmis_gunluk_veri(df)
            if df is not None and len(df) > 2:
                getiri = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0] * 100
                if np.isfinite(getiri):
                    performanslar[sektor] = round(float(getiri), 2)
            time.sleep(0.3)
        except Exception:
            continue
    # En güçlüden en zayıfa sırala
    return dict(sorted(performanslar.items(), key=lambda x: x[1], reverse=True))

def sektor_pe_ortalamalari():
    """
    Her sektördeki havuz hisselerinin F/K ortalamasını hesaplar.
    yfinance API çağrısını minimize etmek için cache'li çalışır.
    """
    cache_dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sektor_pe_cache.json')
    # Cache 24 saat geçerliyse disk'ten oku
    if os.path.exists(cache_dosya):
        try:
            with open(cache_dosya, 'r') as f:
                cache = json.load(f)
            cached_data = cache.get('data', {})
            if time.time() - cache.get('ts', 0) < 86400 and cached_data:
                return cached_data
        except Exception:
            pass

    sektor_pe = defaultdict(list)
    for sembol, sektor in KURUMSAL_HAVUZ.items():
        try:
            info = yf.Ticker(sembol).fast_info
            pe = getattr(info, 'pe_ratio', None) or getattr(info, 'trailing_pe', None)
            if pe and pe > 0 and pe < 200:
                sektor_pe[sektor].append(pe)
            time.sleep(0.2)
        except Exception:
            pass

    ortalamalar = {}
    for sektor, pe_listesi in sektor_pe.items():
        if pe_listesi:
            ortalamalar[sektor] = round(np.median(pe_listesi), 2)

    # Cache'e kaydet
    try:
        with open(cache_dosya, 'w') as f:
            json.dump({'ts': time.time(), 'data': ortalamalar}, f)
    except:
        pass

    return ortalamalar

# ============================================================
#  3. ANA FİLTRELEME VE SKORLAMA MOTORU
# ============================================================

def hisse_analiz_et(sembol, sektor, vix_degeri, spy_getiri, sektor_pe_map, sektor_momentum):
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
        df_daily = tamamlanmis_gunluk_veri(df_daily)
        if df_daily is None or df_daily.empty or len(df_daily) < 200:
            return {
                'sembol': sembol,
                'karar': 'VERI_YETERSIZ',
                'veri_hatasi': True,
                'red_sebebi': 'Gunluk fiyat verisi bos veya 200 gunden kisa',
            }

        veri_taze, veri_tarihi = gunluk_veri_taze_mi(df_daily)
        if not veri_taze:
            return {
                'sembol': sembol,
                'karar': 'VERI_YETERSIZ',
                'veri_hatasi': True,
                'red_sebebi': f'Gunluk fiyat verisi eski (son veri: {veri_tarihi or "bilinmiyor"})',
            }

        close = df_daily['Close']
        volume = df_daily['Volume']
        high = df_daily['High']
        low = df_daily['Low']
        son_fiyat = float(close.iloc[-1])
        
        # --- YENİ İNDİKATÖRLER (v2.0) ---
        # MACD (12, 26, 9)
        macd_df = ta.macd(close, fast=12, slow=26, signal=9)
        macd_val, macd_signal, macd_hist = None, None, None
        macd_bullish = False
        if macd_df is not None and not macd_df.empty:
            macd_val = float(macd_df.iloc[-1, 0]) if not pd.isna(macd_df.iloc[-1, 0]) else None
            macd_signal = float(macd_df.iloc[-1, 1]) if not pd.isna(macd_df.iloc[-1, 1]) else None
            macd_hist = float(macd_df.iloc[-1, 2]) if not pd.isna(macd_df.iloc[-1, 2]) else None
            if macd_val is not None and macd_signal is not None:
                macd_bullish = macd_val > macd_signal  # MACD çizgisi sinyal çizgisinin üstünde
        
        # Bollinger Bands (20, 2)
        bbands = ta.bbands(close, length=20, std=2)
        bb_pozisyon = None  # Alt banda yakın = ucuz, üst banda yakın = pahalı
        if bbands is not None and not bbands.empty:
            bb_lower = float(bbands.iloc[-1, 0]) if not pd.isna(bbands.iloc[-1, 0]) else None
            bb_upper = float(bbands.iloc[-1, 2]) if not pd.isna(bbands.iloc[-1, 2]) else None
            if bb_lower and bb_upper and bb_upper > bb_lower:
                bb_pozisyon = (son_fiyat - bb_lower) / (bb_upper - bb_lower)  # 0=alt, 1=üst
        
        # Hacim SMA20 (Kurumsal İlgi)
        vol_sma20 = ta.sma(volume, length=20)
        hacim_ortalamanin_ustu = False
        if vol_sma20 is not None and not pd.isna(vol_sma20.iloc[-1]):
            hacim_ortalamanin_ustu = float(volume.iloc[-1]) > float(vol_sma20.iloc[-1])

        # ========================================
        #  KATMAN 1: SMA 200 KALKANI (Aşılamaz)
        # ========================================
        sma_200 = ta.sma(close, length=200)
        if sma_200 is None or pd.isna(sma_200.iloc[-1]):
            return None
        sma_200_val = float(sma_200.iloc[-1])

        if son_fiyat < sma_200_val:
            return {'sembol': sembol, 'red_sebebi': f'SMA200 Altında ({son_fiyat:.2f} < {sma_200_val:.2f})'}

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

        if obv_guncel < obv_sma_val:
            return {'sembol': sembol, 'red_sebebi': 'OBV < OBV_SMA20 (Kurumsal çıkış)'}

        # ========================================
        #  KATMAN 3: RSI FIRSAT BÖLGESİ (v2.0: Genişletildi)
        # ========================================
        rsi = ta.rsi(close, length=14)
        if rsi is None or pd.isna(rsi.iloc[-1]):
            return None
        rsi_val = float(rsi.iloc[-1])

        if rsi_val > 70:
            return {'sembol': sembol, 'red_sebebi': f'RSI Aşırı Alım ({rsi_val:.1f} > 70)'}
        if rsi_val < 30:
            return {'sembol': sembol, 'red_sebebi': f'RSI Aşırı Düşük ({rsi_val:.1f} < 30) — Düşen bıçak riski'}

        # ========================================
        #  KATMAN 4: MEAN REVERSION (Sapma Kontrolü)
        # ========================================
        sapma_yuzde = ((son_fiyat - sma_200_val) / sma_200_val) * 100

        if sapma_yuzde > 40.0:
            return {'sembol': sembol, 'red_sebebi': f'Aşırı Primllenmiş (%{sapma_yuzde:.1f} > %40)'}

        # ========================================
        #  KATMAN 5: BİLANÇO BLACKOUT (7 Gün)
        # ========================================
        if bilanco_yakin_mi(sembol, gun_esik=7):
            return {'sembol': sembol, 'red_sebebi': 'Bilanço Blackout (7 gün içinde kazanç açıklaması)'}

        # ============================================================
        #  SKORLAMA MOTORU — Tüm filtreleri geçti, puan topla
        # ============================================================
        baz_skor = 50.0  # Filtreleri geçmenin ödülü

        # --- RSI Pozisyon Bonusu (v2.0: Genişletildi) ---
        if 30 <= rsi_val <= 40:
            baz_skor += 15   # Dip fırsatı
        elif 40 < rsi_val <= 50:
            baz_skor += 10   # Toparlanma
        elif 50 < rsi_val <= 60:
            baz_skor += 5    # Güçlü trend
        elif 60 < rsi_val <= 70:
            baz_skor += 0    # Nötr — reddedilmez ama bonus yok

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

        # --- Temel Analiz Çarpanı (v2.0: Genişletildi) ---
        pe_orani = None
        ebitda_buyume = None
        borc_ozkaynak = None
        fcf_getiri = None
        gelir_buyume = None
        temettu_verimi = None
        temel_bonus = 0
        temel_veri_durumu = 'OK'
        try:
            info = ticker.info
            pe_orani = info.get('trailingPE', None)
            ebitda_buyume = info.get('ebitdaMargins', None)
            borc_ozkaynak = info.get('debtToEquity', None)        # Borç/Özkaynak
            temettu_verimi = temettu_verimi_normalize(info)      # Ondalik temettu verimi
            gelir_buyume = info.get('revenueGrowth', None)        # Gelir Büyümesi (YoY)
            
            # FCF Getirisi hesapla (Serbest Nakit Akışı / Piyasa Değeri)
            fcf = info.get('freeCashflow', None)
            market_cap = info.get('marketCap', None)
            if fcf and market_cap and market_cap > 0:
                fcf_getiri = (fcf / market_cap) * 100

            # F/K sektör ortalamasının altındaysa
            sektor_pe_ort = sektor_pe_map.get(sektor)
            if sektor_pe_ort and pe_orani and pe_orani > 0 and pe_orani < sektor_pe_ort:
                temel_bonus += 10
                baz_skor += 10

            # EBITDA marjı pozitifse
            if ebitda_buyume and ebitda_buyume > 0:
                temel_bonus += 5
                baz_skor += 5
            
            # v2.0: Düşük Borç (D/E < 100 = Sağlıklı bilanço)
            if borc_ozkaynak is not None and borc_ozkaynak < 100:
                temel_bonus += 5
                baz_skor += 5
            elif borc_ozkaynak is not None and borc_ozkaynak > 200:
                baz_skor -= 5  # Aşırı borçlu
            
            # v2.0: Pozitif Serbest Nakit Akışı (FCF > %3)
            if fcf_getiri is not None and fcf_getiri > 3.0:
                temel_bonus += 5
                baz_skor += 5
            
            # v2.0: Gelir Büyümesi (YoY > %10)
            if gelir_buyume is not None and gelir_buyume > 0.10:
                temel_bonus += 5
                baz_skor += 5
            elif gelir_buyume is not None and gelir_buyume < -0.05:
                baz_skor -= 5  # Küçülen gelir
            
            # v2.0: Temettü Verimi (> %1.5 = Uzun vade dostu)
            if temettu_verimi is not None and temettu_verimi > 0.015:
                temel_bonus += 3
                baz_skor += 3
        except Exception:
            temel_veri_durumu = 'MISSING'

        # --- Relatif Güç (RS) — IBD Stili (v2.0: Bug düzeltildi) ---
        rs_skor = 50  # Varsayılan
        try:
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
        sektor_perf = sektor_momentum.get(sektor)
        if sektor_perf is not None and sektor_perf > 3.0:
            baz_skor += 5    # Para bu sektöre akıyor
        elif sektor_perf is not None and sektor_perf < -3.0:
            baz_skor -= 5    # Para bu sektörden kaçıyor
        
        # --- v2.0: MACD Momentum Bonusu ---
        if macd_bullish:
            baz_skor += 10   # MACD sinyal çizgisinin üstünde = Momentum güçlü
        elif macd_val is not None and macd_signal is not None and macd_val < macd_signal:
            baz_skor -= 5    # MACD zayıf
        
        # --- v2.0: Bollinger Band Pozisyon Bonusu ---
        if bb_pozisyon is not None:
            if bb_pozisyon <= 0.3:
                baz_skor += 10   # Alt banda yakın = ucuz fırsat
            elif bb_pozisyon >= 0.8:
                baz_skor -= 5    # Üst banda yakın = aşırı gerilmiş
        
        # --- v2.0: Hacim Teyidi (Kurumsal İlgi) ---
        if hacim_ortalamanin_ustu:
            baz_skor += 5    # Hacim ortalamanın üstünde = Kurumsal ilgi var

        # --- Çoklu Zaman Dilimi Teyidi (MTF — Haftalık RSI) ---
        mtf_uyumlu = True
        try:
            df_weekly = ticker.history(period='2y', interval='1wk')
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
            'sma_200': round(sma_200_val, 2),
            'sma_50': round(sma_50_val, 2) if sma_50_val else None,
            'sapma_yuzde': round(sapma_yuzde, 1),
            'rsi': round(rsi_val, 1),
            'obv_durum': 'Pozitif ✅',
            'golden_cross': golden_cross,
            'vix_penalti': vix_penalti,
            # Temel Analiz (v2.0: Genişletildi)
            'pe_orani': round(pe_orani, 1) if pe_orani else None,
            'borc_ozkaynak': round(borc_ozkaynak, 1) if borc_ozkaynak else None,
            'fcf_getiri': round(fcf_getiri, 1) if fcf_getiri else None,
            'gelir_buyume': round(gelir_buyume * 100, 1) if gelir_buyume else None,
            'temettu_verimi': round(temettu_verimi * 100, 2) if temettu_verimi else None,
            'temel_bonus': temel_bonus,
            # Teknik (v2.0: Yeni indikatörler)
            'macd_bullish': macd_bullish,
            'macd_hist': round(macd_hist, 3) if macd_hist else None,
            'bb_pozisyon': round(bb_pozisyon * 100, 1) if bb_pozisyon is not None else None,
            'hacim_teyit': hacim_ortalamanin_ustu,
            'rs_skor': round(rs_skor, 1),
            'mtf_uyumlu': mtf_uyumlu,
            'sektor_momentum': round(sektor_perf, 2) if sektor_perf is not None else None,
            'teknik_skor': final_skor,  # v2.0: ai_skor → teknik_skor (daha dürüst adlandırma)
            'tp': tp_fiyat,
            'sl': sl_fiyat,
            'rr': rr_orani,
            'atr': round(atr_val, 2),
            # Kademeli Alım
            'faz1_butce_yuzde': 0.30,  # %30 anında
            'faz2_butce_yuzde': 0.70,  # %70 pullback
            'pullback_hedef': pullback_hedef,
            'veri_tarihi': veri_tarihi,
            'veri_durumu': 'OK' if temel_veri_durumu == 'OK' and sektor_perf is not None else 'PARTIAL',
            'motor_surumu': ENGINE_VERSION,
            'kurulum': 'LEGACY_COMBINED',
            'karar': 'AL_ADAYI',
            'sinyal': 'AL',
            'success': True,
        }

    except Exception as e:
        return {'sembol': sembol, 'red_sebebi': f'Analiz Hatası: {str(e)[:80]}'}


# ============================================================
#  4. CROSS-SECTIONAL FACTOR ENGINE
# ============================================================

FAKTOR_TANIMLARI = {
    'kalite': (
        ('roe', True, True),
        ('roa', True, True),
        ('profit_margin', True, True),
        ('gross_margin', True, True),
        ('revenue_growth', True, True),
        ('earnings_growth', True, True),
        ('debt_to_equity', False, True),
    ),
    'deger': (
        ('earnings_yield', True, True),
        ('fcf_yield', True, True),
        ('dividend_yield', True, True),
    ),
    'momentum': (
        ('momentum_12_1', True, False),
        ('momentum_6_1', True, False),
        ('distance_52w_high', True, False),
    ),
    'risk': (
        ('realized_vol_63d', False, False),
        ('downside_vol_63d', False, False),
        ('max_drawdown_1y', True, False),
    ),
}

FAKTOR_AGIRLIKLARI = {
    'kalite': 0.35,
    'deger': 0.20,
    'momentum': 0.30,
    'risk': 0.15,
}

FAKTOR_MIN_METRIK = {
    'kalite': 2,
    'deger': 1,
    'momentum': 2,
    'risk': 2,
}

FAKTOR_ETIKETLERI = {
    'kalite_skor': 'Kalite',
    'deger_skor': 'Deger',
    'momentum_skor': 'Momentum',
    'risk_skor': 'Risk dayanimi',
}


def _sonlu_float(value, alt=None, ust=None):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(result):
        return None
    if alt is not None and result < alt:
        return None
    if ust is not None and result > ust:
        return None
    return result


def faktor_agirliklarini_normalize_et(agirliklar=None):
    """Validate research weights while preserving the production defaults."""
    aliases = {
        'quality': 'kalite',
        'value': 'deger',
        'momentum': 'momentum',
        'risk': 'risk',
        'kalite': 'kalite',
        'deger': 'deger',
    }
    source = FAKTOR_AGIRLIKLARI if agirliklar is None else dict(agirliklar)
    unknown = set(source) - set(aliases)
    if unknown:
        raise ValueError(f'Bilinmeyen faktor agirliklari: {sorted(unknown)}')

    normalized_source = {factor: 0.0 for factor in FAKTOR_AGIRLIKLARI}
    for key, raw_value in source.items():
        value = _sonlu_float(raw_value, alt=0.0)
        if value is None:
            raise ValueError(f'Gecersiz faktor agirligi: {key}={raw_value!r}')
        normalized_source[aliases[key]] += value

    total = sum(normalized_source.values())
    if total <= 0:
        raise ValueError('En az bir faktor agirligi pozitif olmali')
    return {
        factor: value / total
        for factor, value in normalized_source.items()
    }


def hisse_faktorlerini_hesapla(sembol, sektor, vix_degeri, spy_getiri, sektor_momentum):
    """Collect point-in-time-like raw features without assigning an absolute score."""
    try:
        ticker = yf.Ticker(sembol)
        df = ticker.history(period='2y', interval='1d')
        df = tamamlanmis_gunluk_veri(df)
        if df is None or df.empty or len(df) < 252:
            return {
                'sembol': sembol,
                'karar': 'VERI_YETERSIZ',
                'veri_hatasi': True,
                'red_sebebi': 'En az 252 gunluk fiyat gecmisi bulunamadi',
            }

        veri_taze, veri_tarihi = gunluk_veri_taze_mi(df)
        if not veri_taze:
            return {
                'sembol': sembol,
                'karar': 'VERI_YETERSIZ',
                'veri_hatasi': True,
                'red_sebebi': f'Gunluk fiyat verisi eski (son veri: {veri_tarihi or "bilinmiyor"})',
            }

        close = df['Close'].astype(float)
        high = df['High'].astype(float)
        low = df['Low'].astype(float)
        volume = df['Volume'].astype(float)
        fiyat = float(close.iloc[-1])

        sma_50 = ta.sma(close, 50)
        sma_200 = ta.sma(close, 200)
        rsi = ta.rsi(close, 14)
        atr = ta.atr(high, low, close, 14)
        if any(series is None or pd.isna(series.iloc[-1]) for series in (sma_50, sma_200, rsi, atr)):
            return {
                'sembol': sembol,
                'karar': 'VERI_YETERSIZ',
                'veri_hatasi': True,
                'red_sebebi': 'Temel teknik gostergeler hesaplanamadi',
            }

        sma_50_val = float(sma_50.iloc[-1])
        sma_200_val = float(sma_200.iloc[-1])
        rsi_val = float(rsi.iloc[-1])
        atr_val = float(atr.iloc[-1])
        sapma_yuzde = ((fiyat / sma_200_val) - 1.0) * 100.0
        sma50_atr_uzaklik = (fiyat - sma_50_val) / atr_val if atr_val > 0 else None

        momentum_12_1 = float(close.iloc[-22] / close.iloc[-252] - 1.0)
        momentum_6_1 = float(close.iloc[-22] / close.iloc[-126] - 1.0)
        high_52w = float(close.iloc[-252:].max())
        distance_52w_high = float(fiyat / high_52w - 1.0) if high_52w > 0 else None

        returns = close.pct_change().dropna()
        recent_returns = returns.iloc[-63:]
        downside_returns = recent_returns[recent_returns < 0]
        realized_vol = _sonlu_float(recent_returns.std(ddof=0) * np.sqrt(252), 0, 5)
        downside_vol = _sonlu_float(downside_returns.std(ddof=0) * np.sqrt(252), 0, 5)
        rolling_peak = close.iloc[-252:].cummax()
        max_drawdown = _sonlu_float((close.iloc[-252:] / rolling_peak - 1.0).min(), -1, 0)
        avg_dollar_volume = _sonlu_float((close * volume).iloc[-20:].mean(), 0)

        if avg_dollar_volume is None or avg_dollar_volume < 5_000_000:
            return {
                'sembol': sembol,
                'karar': 'REDDET_LIKIDITE',
                'red_sebebi': '20 gunluk ortalama dolar hacmi 5 milyon USD altinda',
            }

        info = {}
        temel_veri_durumu = 'OK'
        try:
            info = ticker.info or {}
        except Exception:
            temel_veri_durumu = 'MISSING'

        pe_orani = _sonlu_float(info.get('trailingPE'), 0.01, 500)
        market_cap = _sonlu_float(info.get('marketCap'), 1)
        free_cashflow = _sonlu_float(info.get('freeCashflow'))
        fcf_yield = free_cashflow / market_cap if free_cashflow is not None and market_cap else None
        earnings_yield = 1.0 / pe_orani if pe_orani else None
        dividend_yield = temettu_verimi_normalize(info)

        roe = _sonlu_float(info.get('returnOnEquity'), -1, 3)
        roa = _sonlu_float(info.get('returnOnAssets'), -1, 1)
        profit_margin = _sonlu_float(info.get('profitMargins'), -2, 1)
        gross_margin = _sonlu_float(info.get('grossMargins'), -1, 1)
        revenue_growth = _sonlu_float(info.get('revenueGrowth'), -1, 5)
        earnings_growth = _sonlu_float(info.get('earningsGrowth'), -1, 10)
        debt_to_equity = _sonlu_float(info.get('debtToEquity'), 0, 1000)

        temel_metrikler = (
            roe, roa, profit_margin, gross_margin, revenue_growth,
            earnings_growth, debt_to_equity, earnings_yield, fcf_yield,
        )
        if sum(value is not None for value in temel_metrikler) < 3:
            temel_veri_durumu = 'MISSING'

        macd_df = ta.macd(close)
        macd_val = _sonlu_float(macd_df['MACD'].iloc[-1])
        macd_signal = _sonlu_float(macd_df['MACD_SIGNAL'].iloc[-1])
        macd_hist = _sonlu_float(macd_df['MACD_HIST'].iloc[-1])
        macd_bullish = (
            macd_val is not None and macd_signal is not None and macd_val > macd_signal
        )

        bbands = ta.bbands(close)
        bb_lower = _sonlu_float(bbands['BB_LOWER'].iloc[-1])
        bb_upper = _sonlu_float(bbands['BB_UPPER'].iloc[-1])
        bb_pozisyon = None
        if bb_lower is not None and bb_upper is not None and bb_upper > bb_lower:
            bb_pozisyon = (fiyat - bb_lower) / (bb_upper - bb_lower)

        obv = ta.obv(close, volume)
        obv_sma = ta.sma(obv, 20)
        obv_pozitif = not pd.isna(obv_sma.iloc[-1]) and float(obv.iloc[-1]) >= float(obv_sma.iloc[-1])
        volume_sma = ta.sma(volume, 20)
        hacim_teyit = not pd.isna(volume_sma.iloc[-1]) and float(volume.iloc[-1]) > float(volume_sma.iloc[-1])

        weekly_close = close.resample('W-FRI').last().dropna()
        weekly_rsi = ta.rsi(weekly_close, 14)
        weekly_rsi_val = _sonlu_float(weekly_rsi.iloc[-1]) if len(weekly_rsi) else None
        mtf_uyumlu = weekly_rsi_val is not None and 40 <= weekly_rsi_val <= 75

        bilanco_riski = bilanco_yakin_mi(sembol, gun_esik=7)
        sektor_perf = sektor_momentum.get(sektor)
        tp_fiyat = round(fiyat + atr_val * 3.0, 2)
        sl_fiyat = round(fiyat - atr_val * 1.5, 2)

        return {
            'sembol': sembol,
            'sektor': sektor,
            'fiyat': round(fiyat, 2),
            'sma_50': round(sma_50_val, 2),
            'sma_200': round(sma_200_val, 2),
            'sapma_yuzde': round(sapma_yuzde, 2),
            'sma50_atr_uzaklik': round(sma50_atr_uzaklik, 3) if sma50_atr_uzaklik is not None else None,
            'rsi': round(rsi_val, 2),
            'atr': round(atr_val, 3),
            'golden_cross': sma_50_val > sma_200_val,
            'obv_durum': 'Pozitif' if obv_pozitif else 'Zayif',
            'macd_bullish': macd_bullish,
            'macd_hist': round(macd_hist, 4) if macd_hist is not None else None,
            'bb_pozisyon': round(bb_pozisyon * 100, 1) if bb_pozisyon is not None else None,
            'hacim_teyit': hacim_teyit,
            'mtf_uyumlu': mtf_uyumlu,
            'vix_penalti': vix_degeri > 25,
            'sektor_momentum': round(sektor_perf, 2) if sektor_perf is not None else None,
            'pe_orani': round(pe_orani, 2) if pe_orani is not None else None,
            'borc_ozkaynak': round(debt_to_equity, 2) if debt_to_equity is not None else None,
            'fcf_getiri': round(fcf_yield * 100, 2) if fcf_yield is not None else None,
            'gelir_buyume': round(revenue_growth * 100, 2) if revenue_growth is not None else None,
            'temettu_verimi': round(dividend_yield * 100, 2) if dividend_yield is not None else None,
            'roe': roe,
            'roa': roa,
            'profit_margin': profit_margin,
            'gross_margin': gross_margin,
            'revenue_growth': revenue_growth,
            'earnings_growth': earnings_growth,
            'debt_to_equity': debt_to_equity,
            'earnings_yield': earnings_yield,
            'fcf_yield': fcf_yield,
            'dividend_yield': dividend_yield,
            'momentum_12_1': momentum_12_1,
            'momentum_6_1': momentum_6_1,
            'distance_52w_high': distance_52w_high,
            'realized_vol_63d': realized_vol,
            'downside_vol_63d': downside_vol,
            'max_drawdown_1y': max_drawdown,
            'avg_dollar_volume': avg_dollar_volume,
            'spy_12ay_getiri': spy_getiri,
            'bilanco_riski': bilanco_riski,
            'tp': tp_fiyat,
            'sl': sl_fiyat,
            'rr': 2.0,
            'pullback_hedef': round(sma_50_val, 2),
            'veri_tarihi': veri_tarihi,
            'veri_durumu': 'PARTIAL' if temel_veri_durumu != 'OK' or sektor_perf is None else 'OK',
            'motor_surumu': ENGINE_VERSION,
            'success': True,
        }
    except Exception as exc:
        return {
            'sembol': sembol,
            'karar': 'VERI_YETERSIZ',
            'veri_hatasi': True,
            'red_sebebi': f'Faktor analiz hatasi: {str(exc)[:120]}',
        }


def _yuzdelik_sirala(index_degerleri, higher_is_better):
    if not index_degerleri:
        return {}
    if len(index_degerleri) == 1:
        only_index = next(iter(index_degerleri))
        return {only_index: 50.0}

    series = pd.Series(index_degerleri, dtype=float)
    ranks = series.rank(method='average', ascending=higher_is_better)
    return {
        index: round(float((rank - 1.0) / (len(series) - 1.0) * 100.0), 2)
        for index, rank in ranks.items()
    }


def _metrik_yuzdelikleri(analizler, metrik, higher_is_better, sector_neutral):
    global_values = {
        index: analiz.get(metrik)
        for index, analiz in enumerate(analizler)
        if _sonlu_float(analiz.get(metrik)) is not None
    }
    global_scores = _yuzdelik_sirala(global_values, higher_is_better)
    if not sector_neutral:
        return global_scores

    result = dict(global_scores)
    sektorler = defaultdict(dict)
    for index, value in global_values.items():
        sektorler[analizler[index].get('sektor', 'Bilinmiyor')][index] = value
    for sektor_values in sektorler.values():
        if len(sektor_values) >= 4:
            result.update(_yuzdelik_sirala(sektor_values, higher_is_better))
    return result


def kurulum_karari_belirle(analiz):
    skor = analiz.get('faktor_skor')
    kalite = analiz.get('kalite_skor')
    kapsam = analiz.get('faktor_kapsami', 0.0)
    fiyat = analiz.get('fiyat')
    sma_50 = analiz.get('sma_50')
    sma_200 = analiz.get('sma_200')
    rsi = analiz.get('rsi')
    momentum = analiz.get('momentum_12_1')
    atr_uzaklik = analiz.get('sma50_atr_uzaklik')

    if skor is None or kapsam < 0.50:
        return 'VERI_YETERSIZ', 'VERI_YETERSIZ'
    if analiz.get('bilanco_riski'):
        return 'OLAY_RISKI', 'OLAY_RISKI'

    trend = (
        fiyat is not None and sma_50 is not None and sma_200 is not None
        and fiyat > sma_200 and sma_50 > sma_200 and momentum is not None and momentum > 0
    )
    uzamis = atr_uzaklik is not None and atr_uzaklik > 3.0
    kaliteli_pullback = (
        kalite is not None and kalite >= 60
        and fiyat is not None and sma_50 is not None and sma_200 is not None
        and fiyat >= sma_200 * 0.95
        and atr_uzaklik is not None and -1.5 <= atr_uzaklik <= 1.5
        and rsi is not None and 35 <= rsi <= 60
    )

    if kaliteli_pullback and skor >= 65:
        return 'KALITELI_GERI_CEKILME', 'AL_ADAYI'
    if trend and (uzamis or (rsi is not None and rsi > 72)):
        return 'UZAMIS_TREND', 'BEKLE_GERI_CEKILME' if skor >= 55 else 'IZLE'
    if trend and skor >= 70:
        return 'TREND_DEVAMI', 'AL_ADAYI'
    if skor >= 60:
        return 'IZLE', 'IZLE'

    zayif_trend = (
        fiyat is not None and sma_50 is not None and sma_200 is not None
        and fiyat < sma_200 and sma_50 < sma_200
    )
    if zayif_trend and skor < 45:
        return 'ZAYIF_TREND', 'REDDET_TREND'
    return 'IZLE', 'IZLE'


def _karar_nedenleri(analiz):
    faktorler = [
        (FAKTOR_ETIKETLERI[key], analiz.get(key))
        for key in FAKTOR_ETIKETLERI
        if analiz.get(key) is not None
    ]
    olumlu = [f'{label} %{score:.0f}' for label, score in sorted(faktorler, key=lambda x: x[1], reverse=True) if score >= 60][:3]
    olumsuz = [f'{label} %{score:.0f}' for label, score in sorted(faktorler, key=lambda x: x[1]) if score <= 40][:3]

    if analiz.get('kurulum') == 'UZAMIS_TREND':
        olumsuz.append('Fiyat SMA50 uzerinde fazla uzamis')
    if analiz.get('karar') == 'OLAY_RISKI':
        olumsuz.append('Yedi gun icinde bilanco riski')
    if analiz.get('golden_cross'):
        olumlu.append('SMA50, SMA200 uzerinde')
    return olumlu[:3], olumsuz[:3]


def faktor_siralama_uygula(analizler, faktor_agirliklari=None):
    """Rank raw observations across the current universe and assign setup decisions."""
    if not analizler:
        return []

    kullanilan_agirliklar = faktor_agirliklarini_normalize_et(faktor_agirliklari)

    metric_scores = {}
    for faktor_metrics in FAKTOR_TANIMLARI.values():
        for metrik, higher_is_better, sector_neutral in faktor_metrics:
            metric_scores[metrik] = _metrik_yuzdelikleri(
                analizler, metrik, higher_is_better, sector_neutral
            )

    toplam_metrik = sum(len(metrics) for metrics in FAKTOR_TANIMLARI.values())
    for index, analiz in enumerate(analizler):
        mevcut_metrik = 0
        for faktor, metrics in FAKTOR_TANIMLARI.items():
            skorlar = []
            for metrik, _, _ in metrics:
                skor = metric_scores[metrik].get(index)
                if skor is not None:
                    skorlar.append(skor)
                    mevcut_metrik += 1
            faktor_skor = (
                round(float(np.mean(skorlar)), 2)
                if len(skorlar) >= FAKTOR_MIN_METRIK[faktor]
                else None
            )
            analiz[f'{faktor}_skor'] = faktor_skor

        agirlikli_toplam = 0.0
        kullanilan_agirlik = 0.0
        for faktor, agirlik in kullanilan_agirliklar.items():
            faktor_skor = analiz.get(f'{faktor}_skor')
            if faktor_skor is not None:
                agirlikli_toplam += faktor_skor * agirlik
                kullanilan_agirlik += agirlik

        analiz['faktor_kapsami'] = round(mevcut_metrik / toplam_metrik, 3)
        analiz['faktor_skor'] = (
            round(agirlikli_toplam / kullanilan_agirlik, 1)
            if kullanilan_agirlik > 0 else None
        )
        analiz['teknik_skor'] = analiz['faktor_skor']
        analiz['rs_skor'] = analiz.get('momentum_skor')
        analiz['temel_bonus'] = analiz.get('kalite_skor')
        analiz['motor_surumu'] = ENGINE_VERSION

        kurulum, karar = kurulum_karari_belirle(analiz)
        analiz['kurulum'] = kurulum
        analiz['karar'] = karar
        analiz['sinyal'] = {
            'AL_ADAYI': 'AL',
            'BEKLE_GERI_CEKILME': 'BEKLE',
            'IZLE': 'IZLE',
            'OLAY_RISKI': 'OLAY_RISKI',
            'REDDET_TREND': 'REDDET',
            'VERI_YETERSIZ': 'VERI_YETERSIZ',
        }.get(karar, 'IZLE')
        analiz['veri_durumu'] = 'OK' if analiz['faktor_kapsami'] >= 0.75 else 'PARTIAL'
        olumlu, olumsuz = _karar_nedenleri(analiz)
        analiz['olumlu_nedenler'] = olumlu
        analiz['olumsuz_nedenler'] = olumsuz

    karar_onceligi = {
        'AL_ADAYI': 0,
        'BEKLE_GERI_CEKILME': 1,
        'IZLE': 2,
        'OLAY_RISKI': 3,
        'REDDET_TREND': 4,
        'VERI_YETERSIZ': 5,
    }
    return sorted(
        analizler,
        key=lambda item: (
            karar_onceligi.get(item.get('karar'), 9),
            -(item.get('faktor_skor') or 0),
        ),
    )


# ============================================================
#  5. PORTFÖY ISI SINIRI (Sektör Ağırlık Kontrolü)
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
    """Render factor ranks and setup decisions without implying an executed trade."""
    baslik = f"""
╔══════════════════════════════════════════════════════════════════╗
║  🏦 HİSSE FAKTÖR BÜLTENİ — {datetime.now().strftime('%d/%m/%Y %H:%M')}
║  📊 VIX: {vix_degeri:.1f} {'🟢 NORMAL' if vix_degeri < 25 else '🟡 YÜKSEK RİSK'}
║  🎯 Mod: DANIŞMAN (Tarar ve analiz eder, işlem açmaz)
╚══════════════════════════════════════════════════════════════════╝"""
    print(baslik)

    if not sinyaller:
        print("\n  ⏳ Faktör ve kurulum şartlarını karşılayan aday bulunamadı.\n")
        return baslik + "\n  ⏳ Aday yok."

    if sektor_perf:
        print("\n  📡 SEKTÖR ROTASYONU (Son 1 Ay):")
        print("  " + "─" * 50)
        for sek, perf in list(sektor_perf.items())[:5]:
            ikon = "🟢" if perf > 0 else "🔴"
            print(f"    {ikon} {sek:<20} {perf:+.2f}%")
        print("  " + "─" * 50)

    karar_etiketleri = {
        'AL_ADAYI': 'AL ADAYI',
        'BEKLE_GERI_CEKILME': 'GERİ ÇEKİLME BEKLE',
        'IZLE': 'İZLE',
        'OLAY_RISKI': 'OLAY RİSKİ',
    }
    bulten_metin = baslik
    print(f"\n  🏆 EN YÜKSEK FAKTÖR SIRASINDAKİ {len(sinyaller)} ADAY:\n")

    for i, s in enumerate(sinyaller, 1):
        skor = s.get('faktor_skor') or 0
        karar = karar_etiketleri.get(s.get('karar'), s.get('karar', 'İZLE'))
        olumlu = ', '.join(s.get('olumlu_nedenler') or ['Belirgin üstünlük yok'])
        olumsuz = ', '.join(s.get('olumsuz_nedenler') or ['Belirgin zayıflık yok'])
        satir = f"""  {'━' * 64}
  📈 #{i} {s['sembol']} | {karar} | Faktör Skoru: %{skor:.1f}
  {'━' * 64}
     Kurulum: {s.get('kurulum', 'IZLE')} | Sektör: {s.get('sektor', 'N/A')}
     Kalite: {s.get('kalite_skor') if s.get('kalite_skor') is not None else 'N/A'} | Değer: {s.get('deger_skor') if s.get('deger_skor') is not None else 'N/A'}
     Momentum: {s.get('momentum_skor') if s.get('momentum_skor') is not None else 'N/A'} | Risk: {s.get('risk_skor') if s.get('risk_skor') is not None else 'N/A'}
     Fiyat: ${s['fiyat']:.2f} | SMA50: ${s['sma_50']:.2f} | SMA200: ${s['sma_200']:.2f}
     RSI: {s['rsi']:.1f} | SMA50 Uzaklık: {s.get('sma50_atr_uzaklik', 'N/A')} ATR
     Güçlü: {olumlu}
     Zayıf: {olumsuz}
     İzleme Seviyeleri: Üst ${s['tp']:.2f} | Alt ${s['sl']:.2f}
  {'━' * 64}"""
        print(satir)
        bulten_metin += "\n" + satir

    print(f"\n  📋 Toplam: {len(sinyaller)} aday | Model: {ENGINE_VERSION} | Mod: Danışman")
    print("  ⚠️ Bu bülten yatırım tavsiyesi değildir; faktör araştırma çıktısıdır.\n")
    return bulten_metin


def telegram_bulten_gonder(bulten_metin, sinyaller):
    """Telegram'a özet sinyal bilgisi gönderir."""
    if os.getenv('STOCK_TELEGRAM_BULLETIN', '1') != '1':
        return
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
            mesaj += "⏳ Faktör şartlarını karşılayan aday yok.\n"
        else:
            for i, s in enumerate(sinyaller[:5], 1):  # Max 5 sinyal
                mesaj += f"\n📈 *#{i} {s['sembol']}* | Faktör: %{s['faktor_skor']:.1f}\n"
                mesaj += f"   Karar: {s.get('karar', 'IZLE')}\n"
                mesaj += f"   Kurulum: {s.get('kurulum', 'IZLE')}\n"
                mesaj += f"   Fiyat: ${s['fiyat']:.2f} | RSI: {s['rsi']:.0f}\n"

            if len(sinyaller) > 5:
                mesaj += f"\n...+{len(sinyaller)-5} sinyal daha\n"

        mesaj += f"\n⚠️ _Danışman Modu — Tarar ve analiz eder, işlem açmaz._"

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

HISSE_SIGNAL_EXTRA_COLUMNS = {
    'signal_date': 'TEXT',
    'as_of_date': 'TEXT',
    'strategy_version': 'TEXT',
    'setup': 'TEXT',
    'decision': 'TEXT',
    'data_status': 'TEXT',
    'created_at': 'TEXT',
    'quality_score': 'REAL',
    'value_score': 'REAL',
    'momentum_score': 'REAL',
    'risk_score': 'REAL',
    'factor_coverage': 'REAL',
    'reasons_json': 'TEXT',
    'feature_json': 'TEXT',
    'model_role': 'TEXT',
    'cohort_month': 'TEXT',
    'cohort_rank': 'INTEGER',
    'target_weight': 'REAL',
    'factor_weights_json': 'TEXT',
}

FAKTOR_FEATURE_KEYS = tuple(
    metrik
    for faktor_metrics in FAKTOR_TANIMLARI.values()
    for metrik, _, _ in faktor_metrics
)


def _hisse_veritabani_hazirla(conn):
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS hisse_sinyalleri (
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

    mevcut = {row[1] for row in cursor.execute('PRAGMA table_info(hisse_sinyalleri)')}
    for kolon, kolon_tipi in HISSE_SIGNAL_EXTRA_COLUMNS.items():
        if kolon not in mevcut:
            cursor.execute(f'ALTER TABLE hisse_sinyalleri ADD COLUMN {kolon} {kolon_tipi}')

    cursor.execute('''CREATE UNIQUE INDEX IF NOT EXISTS ux_hisse_sinyal_identity
        ON hisse_sinyalleri(sembol, as_of_date, strategy_version, setup)''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS ix_hisse_sinyal_asof
        ON hisse_sinyalleri(as_of_date, sembol)''')

    sonuc_semasini_hazirla(conn)


def sinyal_kaydet(
    sinyaller,
    vix_degeri=None,
    db_path=None,
    now=None,
    connection=None,
    raise_on_error=False,
):
    """Store versioned signals once per symbol, market date and setup."""
    owns_connection = connection is None
    conn = connection
    try:
        db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db'
        )
        kayit_zamani = now or datetime.now()
        created_at = kayit_zamani.isoformat(timespec='seconds')
        if owns_connection:
            conn = sqlite3.connect(db_path)
            _hisse_veritabani_hazirla(conn)
        cursor = conn.cursor()
        eklenen = 0

        for s in sinyaller:
            as_of_date = str(
                s.get('veri_tarihi') or kayit_zamani.date().isoformat()
            ).split('T')[0]
            cursor.execute('''INSERT OR IGNORE INTO hisse_sinyalleri
                (tarih, sembol, sektor, fiyat, sma200, rsi, ai_skor, tp, sl,
                 golden_cross, vix, rs_skor, signal_date, as_of_date,
                 strategy_version, setup, decision, data_status, created_at,
                 quality_score, value_score, momentum_score, risk_score,
                 factor_coverage, reasons_json, feature_json, model_role,
                 cohort_month, cohort_rank, target_weight, factor_weights_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (kayit_zamani.strftime('%Y-%m-%d %H:%M'),
                 s['sembol'], s['sektor'], s['fiyat'], s['sma_200'],
                 s['rsi'], s['teknik_skor'], s['tp'], s['sl'],
                 1 if s.get('golden_cross') else 0,
                 vix_degeri, s.get('rs_skor'), kayit_zamani.date().isoformat(),
                 as_of_date, s.get('motor_surumu', ENGINE_VERSION),
                 s.get('kurulum', 'LEGACY_COMBINED'),
                 s.get('karar', 'AL_ADAYI'), s.get('veri_durumu', 'UNKNOWN'),
                 created_at, s.get('kalite_skor'), s.get('deger_skor'),
                 s.get('momentum_skor'), s.get('risk_skor'),
                 s.get('faktor_kapsami'),
                 json.dumps({
                     'olumlu': s.get('olumlu_nedenler', []),
                     'olumsuz': s.get('olumsuz_nedenler', []),
                 }, ensure_ascii=False),
                 json.dumps(
                     {key: s.get(key) for key in FAKTOR_FEATURE_KEYS},
                     ensure_ascii=False,
                 ),
                 s.get('paper_model_role'), s.get('paper_cohort_month'),
                 s.get('paper_rank'), s.get('paper_target_weight'),
                 json.dumps(s.get('paper_factor_weights'), ensure_ascii=True)
                 if s.get('paper_factor_weights') is not None else None))
            eklenen += cursor.rowcount

        if owns_connection:
            conn.commit()
        return eklenen
    except Exception as exc:
        if owns_connection and conn is not None:
            conn.rollback()
        if raise_on_error:
            raise
        print(f"  Sinyal kayit hatasi: {exc}")
        return 0
    finally:
        if owns_connection and conn is not None:
            conn.close()

def performans_takibini_guncelle(db_path=None):
    """Update mature outcomes and return a deduplicated performance snapshot."""
    db_path = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db'
    )
    update_summary = sinyal_sonuclarini_guncelle(
        db_path=db_path,
        sector_etfs=SEKTOR_ETFLERI,
    )
    report = performans_ozeti(db_path)
    shadow = shadow_performance_summary(db_path)
    return {'update': update_summary, 'report': report, 'shadow': shadow}


# ============================================================
#  8. ANA TARAMA DÖNGÜSÜ
# ============================================================

def aylik_golge_kohortlarini_kaydet(
    baseline_ranked,
    challenger_ranked,
    vix_degeri=None,
    db_path=None,
    now=None,
):
    """Atomically store one matched monthly Top20 pair without side effects."""
    summary = {
        'status': 'DISABLED',
        'cohort_month': None,
        'models': {},
        'errors': [],
    }
    if os.getenv('STOCK_SHADOW_PAPER', '1') != '1':
        return summary
    if not baseline_ranked or not challenger_ranked:
        summary['status'] = 'NO_ELIGIBLE_ROWS'
        return summary

    db_path = db_path or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db'
    )
    conn = None
    try:
        baseline_month = cohort_month_from_rows(baseline_ranked)
        challenger_month = cohort_month_from_rows(challenger_ranked)
        if baseline_month != challenger_month:
            raise ValueError(
                f'Paper model months differ: {baseline_month} != {challenger_month}'
            )
        cohort_month = baseline_month
        summary['cohort_month'] = cohort_month

        model_rows = {
            BASELINE_MODEL_ID: baseline_ranked,
            CHALLENGER_MODEL_ID: challenger_ranked,
        }
        cohorts = {}
        for model_id, ranked_rows in model_rows.items():
            cohort = select_monthly_top20(
                ranked_rows,
                model_id=model_id,
                cohort_month=cohort_month,
            )
            if not cohort:
                summary['models'][model_id] = {
                    'status': 'INSUFFICIENT_ELIGIBLE_ROWS',
                    'inserted': 0,
                }
            else:
                cohorts[model_id] = cohort
        if len(cohorts) != len(model_rows):
            summary['status'] = 'FAILED_CLOSED'
            return summary

        conn = sqlite3.connect(db_path)
        _hisse_veritabani_hazirla(conn)
        conn.execute('BEGIN IMMEDIATE')

        version_to_model = {
            spec['strategy_version']: model_id
            for model_id, spec in PAPER_MODEL_SPECS.items()
        }
        versions = tuple(version_to_model)
        placeholders = ', '.join('?' for _ in versions)
        existing_rows = conn.execute(
            f'''SELECT DISTINCT strategy_version FROM hisse_sinyalleri
                WHERE cohort_month = ?
                  AND strategy_version IN ({placeholders})''',
            [cohort_month, *versions],
        ).fetchall()
        recorded = {
            version_to_model[row[0]]
            for row in existing_rows
            if row[0] in version_to_model
        }
        expected_models = set(model_rows)
        if recorded:
            conn.rollback()
            if recorded != expected_models:
                raise RuntimeError(
                    f'Incomplete existing paper pair for {cohort_month}: '
                    f'{sorted(recorded)}'
                )
            for model_id in model_rows:
                summary['models'][model_id] = {
                    'status': 'ALREADY_RECORDED',
                    'inserted': 0,
                }
            summary['status'] = 'ALREADY_RECORDED'
            return summary

        for model_id, cohort in cohorts.items():
            inserted = sinyal_kaydet(
                cohort,
                vix_degeri=vix_degeri,
                now=now,
                connection=conn,
                raise_on_error=True,
            )
            if inserted != len(cohort):
                raise RuntimeError(
                    f'Atomic paper write rejected for {model_id}: '
                    f'{inserted}/{len(cohort)}'
                )
            summary['models'][model_id] = {
                'status': 'RECORDED',
                'inserted': inserted,
                'selected': len(cohort),
                'strategy_version': PAPER_MODEL_SPECS[model_id]['strategy_version'],
            }
        conn.commit()
        summary['status'] = 'RECORDED'
        return summary
    except Exception as exc:
        if conn is not None:
            conn.rollback()
        summary['status'] = 'FAILED_CLOSED'
        summary['models'] = {}
        summary['errors'].append(f'{type(exc).__name__}: {str(exc)[:180]}')
        return summary
    finally:
        if conn is not None:
            conn.close()

def tam_tarama_baslat():
    """
    Ana tarama fonksiyonu. Tüm havuzu filtreleme pipeline'ından geçirir,
    skorlar, sıralar ve sinyal bülteni üretir.
    """
    _tarama_durumu_guncelle('RUNNING', 'Hisse taramasi calisiyor')
    print("\n" + "🔵" * 30)
    print("  🏦 STOCK VALUE ENGINE — DANIŞMAN MODU")
    print("  📊 Wall Street Kalibresinde Değer & Momentum Tarayıcı")
    print("  ⏰ Timeframe: Günlük (1D) + Haftalık (1W)")
    print("  🎯 Hedef: 3-12 Ay Elde Tutma")
    print("🔵" * 30)

    # --- ÖN HAZIRLIK ---
    print("\n  ⚙️ Makro veriler hazırlanıyor...")

    vix_sonuc = vix_verisi_oku()
    if not vix_sonuc.uygun:
        mesaj = f'Veri yetersiz: VIX okunamadi ({vix_sonuc.error})'
        _tarama_durumu_guncelle('DATA_INCOMPLETE', mesaj)
        print(f"\n  ⚠️ {mesaj}. Tarama güvenli biçimde durduruldu.")
        return []

    vix_degeri = vix_sonuc.value
    print(f"    📊 VIX: {vix_degeri:.1f} — {'🟢 NORMAL' if vix_degeri < 25 else '🟡 PANİK' if vix_degeri < 35 else '🔴 CRASH'}")

    if vix_degeri > 35:
        _tarama_durumu_guncelle('RISK_PAUSED', f'VIX {vix_degeri:.1f} nedeniyle tarama durduruldu')
        print("\n  🔴 [CRASH MODU] VIX > 35! Tarama iptal edildi. Nakit pozisyonda kal Kaptan!")
        return []

    spy_sonuc = spy_12ay_verisi_oku()
    if not spy_sonuc.uygun:
        mesaj = f'Veri yetersiz: SPY okunamadi ({spy_sonuc.error})'
        _tarama_durumu_guncelle('DATA_INCOMPLETE', mesaj)
        print(f"\n  ⚠️ {mesaj}. Tarama güvenli biçimde durduruldu.")
        return []

    spy_getiri = spy_sonuc.value
    print(f"    📈 S&P 500 (12 Ay): %{spy_getiri*100:.1f}")

    if os.getenv('STOCK_OUTCOME_TRACKING', '1') == '1':
        try:
            print("    🧭 Eski sinyallerin ileri dönem sonuçları güncelleniyor...")
            takip = performans_takibini_guncelle()
            update = takip['update']
            report = takip['report']
            shadow = takip.get('shadow', {})
            print(
                f"      Paper A/B: {shadow.get('status', 'UNKNOWN')} | "
                f"Olgun aylik kohort: {shadow.get('paired_mature_cohorts', 0)}/"
                f"{shadow.get('required_paired_mature_cohorts', 3)}"
            )
            horizons = update.get('horizons', {})
            print(
                "      "
                f"Kayıt: {update.get('signals_found', 0)} | "
                f"5g: {horizons.get('5g', 0)} | 20g: {horizons.get('20g', 0)} | "
                f"60g: {horizons.get('60g', 0)} | 120g: {horizons.get('120g', 0)}"
            )
            metrics_20g = report.get('horizons', {}).get('20g', {})
            if metrics_20g.get('sample'):
                median_excess = metrics_20g.get('median_excess_spy')
                excess_text = (
                    f"%{median_excess * 100:+.2f}" if median_excess is not None else 'N/A'
                )
                print(
                    f"      Bağımsız 20g gözlem: {metrics_20g['sample']} | "
                    f"Medyan SPY üzeri: {excess_text}"
                )
        except Exception as exc:
            print(f"    ⚠️ Performans takip hatası: {str(exc)[:140]}")

    print("    🏭 Sektör rotasyonu hesaplanıyor...")
    sektor_perf = sektor_rotasyonu_radar()
    for sek, perf in list(sektor_perf.items())[:3]:
        ikon = "↑" if perf > 0 else "↓"
        print(f"      {ikon} {sek}: {perf:+.1f}%")

    # --- ANA TARAMA ---
    havuz_listesi = list(KURUMSAL_HAVUZ.items())
    toplam = len(havuz_listesi)
    print(f"\n  🔍 TARAMA BAŞLIYOR — {toplam} hisse analiz edilecek...\n")

    ham_analizler = []
    reddedilen_log = []
    veri_hatalari = []
    islenen = 0

    for sembol, sektor in havuz_listesi:
        islenen += 1

        # İlerleme göstergesi (her 10 hissede bir)
        if islenen % 10 == 0 or islenen == toplam:
            print(f"    [{islenen}/{toplam}] Taranıyor... ({sembol})")

        sonuc = hisse_faktorlerini_hesapla(
            sembol, sektor, vix_degeri, spy_getiri, sektor_perf
        )

        if sonuc is None:
            continue

        if sonuc.get('veri_hatasi'):
            veri_hatalari.append(sonuc)
        elif sonuc.get('success'):
            ham_analizler.append(sonuc)
        elif 'red_sebebi' in sonuc:
            reddedilen_log.append(sonuc)

        # Rate limit koruması (yfinance ban önleme)
        time.sleep(0.5)

    baseline_input = [dict(row) for row in ham_analizler]
    skorlananlar = faktor_siralama_uygula(baseline_input)
    golge_skorlananlar = []
    if os.getenv('STOCK_SHADOW_PAPER', '1') == '1':
        challenger_input = [dict(row) for row in ham_analizler]
        golge_skorlananlar = faktor_siralama_uygula(
            challenger_input,
            faktor_agirliklari=PAPER_MODEL_SPECS[CHALLENGER_MODEL_ID]['weights'],
        )
    rapor_adaylari = [
        analiz for analiz in skorlananlar
        if analiz.get('karar') in {
            'AL_ADAYI', 'BEKLE_GERI_CEKILME', 'IZLE', 'OLAY_RISKI'
        }
        and (analiz.get('faktor_skor') or 0) >= 55
    ][:20]

    karar_sayac = defaultdict(int)
    for analiz in skorlananlar:
        karar_sayac[analiz.get('karar', 'BILINMIYOR')] += 1

    # --- REDDEDILEN LOG (Debug) ---
    print(f"\n  📋 TARAMA SONUCU: {toplam} hisse tarandı")
    print(f"    ✅ Faktör sıralamasına giren: {len(skorlananlar)}")
    print(f"    🎯 AL adayı: {karar_sayac['AL_ADAYI']}")
    print(f"    ⏳ Geri çekilme bekleyen: {karar_sayac['BEKLE_GERI_CEKILME']}")
    print(f"    👁 İzle: {karar_sayac['IZLE']}")
    print(f"    📅 Olay riski: {karar_sayac['OLAY_RISKI']}")
    print(f"    📉 Trend reddi: {karar_sayac['REDDET_TREND']}")
    print(f"    ❌ Reddedilen: {len(reddedilen_log)}")
    print(f"    ⚠️ Veri nedeniyle analiz edilemeyen: {len(veri_hatalari)}")

    if reddedilen_log:
        print(f"\n  🔍 [DEBUG] En Sık Red Sebepleri (Top 5):")
        sebep_sayac = defaultdict(int)
        for r in reddedilen_log:
            # Sebebin ilk kelimelerini gruplayarak say
            sebep = r.get('red_sebebi', 'Bilinmiyor').split('(')[0].strip()
            sebep_sayac[sebep] += 1
        for sebep, sayi in sorted(sebep_sayac.items(), key=lambda x: x[1], reverse=True)[:5]:
            print(f"    • {sebep}: {sayi} hisse")

    # --- BÜLTENİ ÜRET ---
    if os.getenv('STOCK_SCAN_REPORT', '1') == '1':
        try:
            rapor_dosyasi = generate_stock_scan_report(
                skorlananlar,
                golge_skorlananlar,
                vix_degeri,
            )
            print(f"    HTML raporu: {rapor_dosyasi}")
        except Exception as exc:
            print(
                f"    Rapor olusturma hatasi: "
                f"{type(exc).__name__}: {str(exc)[:140]}"
            )
    bulten = sinyal_bulteni_olustur(rapor_adaylari, vix_degeri, sektor_perf)

    # --- TELEGRAM'A GÖNDER ---
    telegram_bulten_gonder(bulten, rapor_adaylari)

    # --- VERİTABANINA KAYDET ---
    if skorlananlar:
        eklenen = sinyal_kaydet(skorlananlar, vix_degeri=vix_degeri)
        print(f"    💾 Yeni ve benzersiz sinyal kaydı: {eklenen}")

    if golge_skorlananlar:
        golge_kayit = aylik_golge_kohortlarini_kaydet(
            skorlananlar,
            golge_skorlananlar,
            vix_degeri=vix_degeri,
        )
        print(
            f"    Paper A/B kohortu: {golge_kayit['status']} | "
            f"Ay: {golge_kayit.get('cohort_month') or 'N/A'}"
        )
    _tarama_durumu_guncelle(
        'COMPLETE',
        f"{karar_sayac['AL_ADAYI']} AL adayi, {len(veri_hatalari)} veri hatasi",
    )

    return rapor_adaylari


# ============================================================
#  9. TEK HİSSE SORGULAMA MODU
# ============================================================

def tek_hisse_analiz(sembol_listesi):
    """Show raw factor inputs; four or more symbols also receive relative ranks."""
    print(f"\n{'━' * 60}")
    print(f"  🔬 TEK HİSSE DERİN ANALİZ — {', '.join(sembol_listesi)}")
    print(f"{'━' * 60}")
    
    vix_sonuc = vix_verisi_oku()
    spy_sonuc = spy_12ay_verisi_oku()
    if not vix_sonuc.uygun or not spy_sonuc.uygun:
        print("  ⚠️ VIX veya SPY verisi eksik. Analiz güvenli biçimde durduruldu.")
        return

    vix_degeri = vix_sonuc.value
    spy_getiri = spy_sonuc.value
    sektor_perf = sektor_rotasyonu_radar()
    print(f"  📊 VIX: {vix_degeri:.1f} | S&P 500 (12Ay): %{spy_getiri*100:.1f}")

    ham_analizler = []
    for sembol in sembol_listesi:
        sembol = sembol.upper().strip()
        sektor = KURUMSAL_HAVUZ.get(sembol, 'Bilinmiyor')
        sonuc = hisse_faktorlerini_hesapla(
            sembol, sektor, vix_degeri, spy_getiri, sektor_perf
        )
        if 'red_sebebi' in sonuc and not sonuc.get('success'):
            print(f"  ⚠️ {sembol}: {sonuc['red_sebebi']}")
            continue
        ham_analizler.append(sonuc)

    skorlananlar = faktor_siralama_uygula(ham_analizler) if len(ham_analizler) >= 4 else ham_analizler
    if len(ham_analizler) < 4:
        print("  ℹ️ Göreceli faktör puanı için en az dört hisse gerekir; ham görünüm gösteriliyor.")

    for s in skorlananlar:
        skor = f"%{s['faktor_skor']:.1f}" if s.get('faktor_skor') is not None else 'Tam taramada belirlenir'
        karar = s.get('karar', 'HAM_GORUNUM')
        print(f"""
  {'═' * 60}
  🔍 {s['sembol']} ({s['sektor']}) | {karar} | Faktör: {skor}
  {'═' * 60}
     Fiyat: ${s['fiyat']:.2f}  |  SMA200: ${s['sma_200']:.2f}  |  SMA50: ${s.get('sma_50', 'N/A')}
     SMA200 Sapma: %{s['sapma_yuzde']:.1f}  |  SMA50 Uzaklık: {s.get('sma50_atr_uzaklik', 'N/A')} ATR
     RSI(14): {s['rsi']:.1f}  |  OBV: {s['obv_durum']}  |  ATR: ${s['atr']:.2f}
     12-1 Momentum: %{s.get('momentum_12_1', 0)*100:.1f}  |  6-1 Momentum: %{s.get('momentum_6_1', 0)*100:.1f}
     F/K: {s.get('pe_orani', 'N/A')}  |  Borç/Özkaynak: {s.get('borc_ozkaynak', 'N/A')}
     FCF Getirisi: %{s.get('fcf_getiri', 'N/A')}  |  Gelir Büyümesi: %{s.get('gelir_buyume', 'N/A')}
     Kalite: {s.get('kalite_skor', 'N/A')} | Değer: {s.get('deger_skor', 'N/A')} | Momentum: {s.get('momentum_skor', 'N/A')} | Risk: {s.get('risk_skor', 'N/A')}
  {'═' * 60}""")


# ============================================================
#  10. ÇALIŞTIRILMA MODU
# ============================================================

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════╗")
    print("║  🏦 STOCK VALUE ENGINE v3.1                        ║")
    print("║  Danışman Modu — Tarar, analiz eder, işlem açmaz   ║")
    print("║  Kalite + Değer + Momentum + Risk Faktör Modeli    ║")
    print("╚══════════════════════════════════════════════════════╝\n")

    try:
        # Tek hisse modu: python stock_value_engine.py NVDA TSLA AAPL
        if len(sys.argv) > 1:
            semboller = sys.argv[1:]
            tek_hisse_analiz(semboller)
        else:
            # Tam tarama modu
            sinyaller = tam_tarama_baslat()

            if sinyaller:
                print(f"\n  ✅ {len(sinyaller)} faktör adayı raporlandı.")
            else:
                print("\n  ⏳ Rapor eşiğini karşılayan faktör adayı bulunamadı.")

            # Haftalık rebalancing raporu (isteğe bağlı)
            if datetime.now().weekday() == 6:  # Pazar günü
                haftalik_rebalancing_raporu()

    except KeyboardInterrupt:
        print("\n  🛑 Tarama Kaptan tarafından manuel olarak durduruldu.")
    except Exception as e:
        print(f"\n  ❌ Kritik Hata: {e}")
