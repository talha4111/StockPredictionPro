"""
STOCK VALUE ENGINE v2.0 — Wall Street Kalibresinde Değer & Momentum Motoru
Mod: DANIŞMAN (Advisor) - Sinyal üretir, otomatik işlem AÇMAZ.
Timeframe: Günlük (1d) + Haftalık (1wk)
Hedef: 3-12 Ay Elde Tutma Süresi

v2.0 Yenilikler:
  - MACD, Bollinger Bands, Hacim SMA20 indikatörleri eklendi
  - Temel analiz genişletildi (D/E, FCF, Gelir Büyümesi, Temettü)
  - RSI filtresi genişletildi (55→70 — güçlü hisseler kaçırılmıyor)
  - Tek hisse sorgulama modu eklendi
  - Kural bazlı skorlama dürüstçe 'Teknik Skor' olarak adlandırıldı
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

def spy_12ay_getiri():
    """S&P 500'ün son 12 aylık getirisini hesaplar (RS Skoru için)."""
    try:
        spy = yf.Ticker('SPY')
        df = spy.history(period='1y')
        if df is not None and len(df) > 20:
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
            if df is not None and len(df) > 2:
                getiri = (df['Close'].iloc[-1] - df['Close'].iloc[0]) / df['Close'].iloc[0] * 100
                performanslar[sektor] = round(getiri, 2)
            time.sleep(0.3)
        except:
            performanslar[sektor] = 0.0
    # En güçlüden en zayıfa sırala
    return dict(sorted(performanslar.items(), key=lambda x: x[1], reverse=True))

def sektor_pe_ortalamalari():
    """
    Her sektördeki havuz hisselerinin F/K ortalamasını hesaplar.
    yfinance API çağrısını minimize etmek için cache'li çalışır.
    """
    cache_dosya = 'sektor_pe_cache.json'
    # Cache 24 saat geçerliyse disk'ten oku
    if os.path.exists(cache_dosya):
        try:
            with open(cache_dosya, 'r') as f:
                cache = json.load(f)
            if time.time() - cache.get('ts', 0) < 86400:  # 24 saat
                return cache.get('data', {})
        except:
            pass

    sektor_pe = defaultdict(list)
    for sembol, sektor in KURUMSAL_HAVUZ.items():
        try:
            info = yf.Ticker(sembol).fast_info
            pe = getattr(info, 'pe_ratio', None) or getattr(info, 'trailing_pe', None)
            if pe and pe > 0 and pe < 200:
                sektor_pe[sektor].append(pe)
            time.sleep(0.2)
        except:
            pass

    ortalamalar = {}
    for sektor, pe_listesi in sektor_pe.items():
        if pe_listesi:
            ortalamalar[sektor] = round(np.median(pe_listesi), 2)
        else:
            ortalamalar[sektor] = 25.0  # Varsayılan

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
        if df_daily is None or df_daily.empty or len(df_daily) < 200:
            return None  # Yetersiz veri

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
        try:
            info = ticker.info
            pe_orani = info.get('trailingPE', None)
            ebitda_buyume = info.get('ebitdaMargins', None)
            borc_ozkaynak = info.get('debtToEquity', None)        # Borç/Özkaynak
            temettu_verimi = info.get('dividendYield', None)      # Temettü Verimi
            gelir_buyume = info.get('revenueGrowth', None)        # Gelir Büyümesi (YoY)
            
            # FCF Getirisi hesapla (Serbest Nakit Akışı / Piyasa Değeri)
            fcf = info.get('freeCashflow', None)
            market_cap = info.get('marketCap', None)
            if fcf and market_cap and market_cap > 0:
                fcf_getiri = (fcf / market_cap) * 100

            # F/K sektör ortalamasının altındaysa
            sektor_pe_ort = sektor_pe_map.get(sektor, 25.0)
            if pe_orani and pe_orani > 0 and pe_orani < sektor_pe_ort:
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
        except:
            pass

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
        sektor_perf = sektor_momentum.get(sektor, 0.0)
        if sektor_perf > 3.0:
            baz_skor += 5    # Para bu sektöre akıyor
        elif sektor_perf < -3.0:
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
            'sektor_momentum': round(sektor_perf, 2),
            'teknik_skor': final_skor,  # v2.0: ai_skor → teknik_skor (daha dürüst adlandırma)
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
  📈 #{i}  {s['sembol']}  |  LONG  |  🎯 Teknik Skor: %{s['teknik_skor']:.0f}
  {'━' * 58}
     Fiyat: ${s['fiyat']:.2f}   |  SMA200: ${s['sma_200']:.2f}  |  SMA50: ${s.get('sma_50', 'N/A')}
     RSI(14): {s['rsi']:.1f}      |  OBV: {s['obv_durum']}  |  ATR: ${s['atr']:.2f}
     Sapma: %{s['sapma_yuzde']:.1f}    |  R/R: {s['rr']:.1f}x
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
     🏛️ Sektör: {s['sektor']:<18}  |  Ağırlık: {sektor_durum}
     📊 F/K: {s.get('pe_orani', 'N/A')}  |  Temel Bonus: +{s.get('temel_bonus', 0)}
     💪 RS Skoru: {s.get('rs_skor', 50):.0f}/100  |  Sektör Mom.: {s.get('sektor_momentum', 0):+.1f}%
  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
     📉 MACD: {'✅ Bullish' if s.get('macd_bullish') else '❌ Bearish'}  |  BB: %{s.get('bb_pozisyon', 'N/A')}  |  Hacim: {'✅ Üst' if s.get('hacim_teyit') else '❌ Alt'}
     🏦 D/E: {s.get('borc_ozkaynak', 'N/A')}  |  FCF: %{s.get('fcf_getiri', 'N/A')}  |  Gelir: %{s.get('gelir_buyume', 'N/A')}
     💵 Temettü: %{s.get('temettu_verimi', 'N/A')}
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
                mesaj += f"\n📈 *#{i} {s['sembol']}* | Skor: %{s['teknik_skor']:.0f}\n"
                mesaj += f"   Fiyat: ${s['fiyat']:.2f} | RSI: {s['rsi']:.0f}\n"
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
                 s['rsi'], s['teknik_skor'], s['tp'], s['sl'],
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
            if sonuc['teknik_skor'] >= 70:
                basarili_sinyaller.append(sonuc)
            else:
                reddedilen_log.append({
                    'sembol': sembol,
                    'red_sebebi': f"Yetersiz Skor (%{sonuc['teknik_skor']:.0f} < %70)"
                })
        elif 'red_sebebi' in sonuc:
            reddedilen_log.append(sonuc)

        # Rate limit koruması (yfinance ban önleme)
        time.sleep(0.5)

    # --- SIRALAMA (AI Skor — Yüksekten düşüğe) ---
    basarili_sinyaller.sort(key=lambda x: x['teknik_skor'], reverse=True)

    # --- REDDEDILEN LOG (Debug) ---
    print(f"\n  📋 TARAMA SONUCU: {toplam} hisse tarandı")
    print(f"    ✅ Filtrelerden geçen: {len(basarili_sinyaller)}")
    print(f"    ❌ Reddedilen: {len(reddedilen_log)}")

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
    bulten = sinyal_bulteni_olustur(basarili_sinyaller, vix_degeri, sektor_perf)

    # --- TELEGRAM'A GÖNDER ---
    telegram_bulten_gonder(bulten, basarili_sinyaller)

    # --- VERİTABANINA KAYDET ---
    if basarili_sinyaller:
        sinyal_kaydet(basarili_sinyaller)

    return basarili_sinyaller


# ============================================================
#  9. TEK HİSSE SORGULAMA MODU (v2.0)
# ============================================================

def tek_hisse_analiz(sembol_listesi):
    """
    Belirli hisse(ler) için detaylı analiz raporu üretir.
    Kullanım: python stock_value_engine.py NVDA TSLA AAPL
    """
    print(f"\n{'━' * 60}")
    print(f"  🔬 TEK HİSSE DERİN ANALİZ — {', '.join(sembol_listesi)}")
    print(f"{'━' * 60}")
    
    vix_degeri = vix_oku()
    spy_getiri = spy_12ay_getiri()
    sektor_perf = sektor_rotasyonu_radar()
    sektor_pe_map = sektor_pe_ortalamalari()
    
    print(f"  📊 VIX: {vix_degeri:.1f} | S&P 500 (12Ay): %{spy_getiri*100:.1f}")
    
    for sembol in sembol_listesi:
        sembol = sembol.upper().strip()
        sektor = KURUMSAL_HAVUZ.get(sembol, 'Bilinmiyor')
        
        print(f"\n{'═' * 60}")
        print(f"  🔍 ANALİZ: {sembol} ({sektor})")
        print(f"{'═' * 60}")
        
        sonuc = hisse_analiz_et(sembol, sektor, vix_degeri, spy_getiri, sektor_pe_map, sektor_perf)
        
        if sonuc is None:
            print(f"  ⚠️ Yetersiz veri — {sembol} analiz edilemedi.")
            continue
        
        if 'red_sebebi' in sonuc and not sonuc.get('success'):
            print(f"  ❌ REDDEDİLDİ: {sonuc['red_sebebi']}")
            continue
        
        s = sonuc
        gc = "✅ Aktif" if s.get('golden_cross') else "❌ Yok"
        mtf = "✅ Uyumlu" if s.get('mtf_uyumlu') else "⚠️ Uyumsuz"
        macd_d = "✅ Bullish" if s.get('macd_bullish') else "❌ Bearish"
        hacim_d = "✅ Ortalamanın Üstü" if s.get('hacim_teyit') else "❌ Ortalamanın Altı"
        
        print(f"""
  📊 FİYAT BİLGİSİ:
     Fiyat: ${s['fiyat']:.2f}  |  SMA200: ${s['sma_200']:.2f}  |  SMA50: ${s.get('sma_50', 'N/A')}
     SMA200 Sapma: %{s['sapma_yuzde']:.1f}  |  R/R: {s['rr']:.1f}x
  
  📉 TEKNİK İNDİKATÖRLER:
     RSI(14): {s['rsi']:.1f}  |  OBV: {s['obv_durum']}  |  ATR: ${s['atr']:.2f}
     MACD: {macd_d}  |  Histogram: {s.get('macd_hist', 'N/A')}
     Bollinger Band Pozisyonu: %{s.get('bb_pozisyon', 'N/A')}  (0=Alt Bant, 100=Üst Bant)
     Hacim: {hacim_d}  |  Golden Cross: {gc}  |  MTF: {mtf}
  
  🏦 TEMEL ANALİZ:
     F/K: {s.get('pe_orani', 'N/A')}  |  Borç/Özkaynak: {s.get('borc_ozkaynak', 'N/A')}
     FCF Getirisi: %{s.get('fcf_getiri', 'N/A')}  |  Gelir Büyümesi: %{s.get('gelir_buyume', 'N/A')}
     Temettü Verimi: %{s.get('temettu_verimi', 'N/A')}  |  Temel Bonus: +{s.get('temel_bonus', 0)}
  
  💪 GÖRECELI GÜÇ:
     RS Skoru: {s.get('rs_skor', 50):.0f}/100  |  Sektör Momentum: {s.get('sektor_momentum', 0):+.1f}%
  
  {'━' * 58}
  🎯 TEKNİK SKOR: %{s['teknik_skor']:.0f}  {'✅ AL SİNYALİ' if s['teknik_skor'] >= 70 else '⏳ BEKLE' if s['teknik_skor'] >= 50 else '❌ REDDET'}
  🎯 TP: ${s['tp']:.2f}  |  🛑 SL: ${s['sl']:.2f}  |  R/R: {s['rr']:.1f}x
  💰 Faz 1: %30 Bütçe → HEMEN (${s['fiyat']:.2f})
  ⏳ Faz 2: %70 Bütçe → Pullback Bekle (${s.get('pullback_hedef', 0):.2f})
  {'━' * 58}""")


# ============================================================
#  10. ÇALIŞTIRILMA MODU
# ============================================================

if __name__ == "__main__":
    print("╔══════════════════════════════════════════════════════╗")
    print("║  🏦 STOCK VALUE ENGINE v2.0                        ║")
    print("║  Danışman Modu — Sinyal Üretir, İşlem Açmaz        ║")
    print("║  v2.0: MACD, BB, Hacim, D/E, FCF, Gelir Büyümesi  ║")
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

