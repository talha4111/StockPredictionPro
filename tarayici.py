import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt
import time

# --- CCXT Global API ---
borsa_api = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})
try: borsa_api.load_markets()
except: pass

def _ccxt_veri_getir(coin, timeframe='15m', limit=1000):
    for deneme in range(3):
        try:
            bars = borsa_api.fetch_ohlcv(coin, timeframe, limit=limit)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            return df
        except Exception as e:
            if deneme == 2:
                print(f"❌ ccxt Hatası ({coin}): {e}")
                return None
            time.sleep(2)

def veri_getir_dortlu(hedef_coin, referans_coin, timeframe='15m'):
    try:
        # 1. Veri İndirme (ccxt)
        df_hedef = _ccxt_veri_getir(hedef_coin, timeframe=timeframe, limit=1000)
        df_ref = _ccxt_veri_getir(referans_coin, timeframe=timeframe, limit=1000)
        
        if df_hedef is None or df_ref is None or df_hedef.empty or df_ref.empty:
            return None

        # 3. SÜTUN HAZIRLAMA (Analiz motoru için 'open' sütunu ŞARTTIR!)
        df = df_hedef[['open', 'high', 'low', 'close', 'volume']].copy()
        df.rename(columns={'close': 'Hedef_Close'}, inplace=True)
        
        # Ref_Close hizalaması (ffill saniyelik boşlukları korur)
        ref_series = df_ref['close'].reindex(df.index, method='ffill')
        df['Ref_Close'] = ref_series.values

        # --- Epsilon Yaması (Sıfıra Bölünme / RuntimeWarning Koruması) ---
        # Eğer bir mumda High ve Low eşitse (True Range 0), payda belirsizliği yüzünden CHOP ve Squeeze motoru çöker.
        # Bu yüzden çok ufak bir Epsilon (1e-9) sapması ekliyoruz.
        mask_equal = (df['high'] == df['low'])
        df.loc[mask_equal, 'high'] += 1e-9
        df.loc[mask_equal, 'low'] -= 1e-9

        # 4. İndikatör Hesaplamaları
        df['RSI'] = df.ta.rsi(close='Hedef_Close', length=11)
        
        macd = df.ta.macd(close='Hedef_Close', fast=15, slow=26, signal=9)
        df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
        
        df['ATR'] = df.ta.atr(high='high', low='low', close='Hedef_Close', length=14)
        
        adx = df.ta.adx(high='high', low='low', close='Hedef_Close', length=14)
        if adx is not None and not adx.empty:
            df['ADX'] = adx.iloc[:, 0].fillna(0)
            df['DMP'] = adx.iloc[:, 1].fillna(0)  # +DI (Pozitif Yön Göstergesi)
            df['DMN'] = adx.iloc[:, 2].fillna(0)  # -DI (Negatif Yön Göstergesi)
        else:
            df['ADX'] = 0.0
            df['DMP'] = 0.0
            df['DMN'] = 0.0

        # Yeni Eklenen Kritik Sensörler
        df['OBV'] = df.ta.obv(close=df['Hedef_Close'], volume=df['volume'])
        
        bbands = df.ta.bbands(close=df['Hedef_Close'], length=20)
        df['BB_Width'] = bbands.iloc[:, 3] if bbands is not None else 0
        df['BB_Width_Mean_100'] = df['BB_Width'].rolling(window=50).mean()  # Pencere 100->50 (Daha reaktif)
        
        df['MFI'] = df.ta.mfi(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'], length=14)

        # --- Hacim Profili (Volume Profile) / VWAP Analizi ---
        vwap = df.ta.vwap(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'])
        df['VWAP'] = vwap if vwap is not None else df['Hedef_Close']
        df['VP_Sapma'] = (df['Hedef_Close'] - df['VWAP']) / df['VWAP']

        # --- YATAY PİYASA KALKANI (CHOP & SQUEEZE) ---
        chop = df.ta.chop(high=df['high'], low=df['low'], close=df['Hedef_Close'], length=14)
        df['CHOP'] = chop if chop is not None else 50.0

        sqz = df.ta.squeeze(high=df['high'], low=df['low'], close=df['Hedef_Close'], length=20, lazybear=True)
        if sqz is not None:
            on_col = [c for c in sqz.columns if 'ON' in c]
            df['Squeeze_ON'] = sqz[on_col[0]] if on_col else 0.0
        else:
            df['Squeeze_ON'] = 0.0

        # --- SÜRÜ PSİKOLOJİSİ (Funding Rate & Open Interest) ---
        df['Open_Interest'] = 0.0
        df['Funding_Rate'] = 0.0001
        
        try:
            oi_bars = borsa_api.fetch_open_interest_history(hedef_coin, timeframe=timeframe, limit=1000)
            if oi_bars:
                oi_df = pd.DataFrame(oi_bars)
                oi_df['timestamp'] = pd.to_datetime(oi_df['timestamp'], unit='ms')
                oi_df.set_index('timestamp', inplace=True)
                df['Open_Interest'] = oi_df['openInterestValue']
        except:
            pass

        try:
            fr_bars = borsa_api.fetch_funding_rate_history(hedef_coin, limit=100)
            if fr_bars:
                fr_df = pd.DataFrame(fr_bars)
                fr_df['timestamp'] = pd.to_datetime(fr_df['timestamp'], unit='ms')
                fr_df.set_index('timestamp', inplace=True)
                df['Funding_Rate'] = fr_df['fundingRate']
        except:
            pass
            
        df['Open_Interest'] = df['Open_Interest'].ffill().bfill().fillna(0)
        df['Funding_Rate'] = df['Funding_Rate'].ffill().bfill().fillna(0.0001)

        # 5. Delta (Değişim) ve Korelasyon
        df['Hedef_Ret'] = df['Hedef_Close'].pct_change().fillna(0)
        df['Ref_Ret'] = df['Ref_Close'].pct_change().fillna(0)
        df['Vol_Ret'] = df['volume'].pct_change().fillna(0)
        df['Korelasyon'] = df['Hedef_Ret'].rolling(window=14).corr(df['Ref_Ret']).fillna(0)

        # --- TREND GÜCÜ (EMA Slope - Modelin trend yönünü öğrenmesi için) ---
        ema20 = df.ta.ema(close='Hedef_Close', length=20)
        if ema20 is not None:
            df['EMA_Slope'] = ema20.pct_change(periods=5).fillna(0) * 100  # Son 5 mumda EMA değişim yüzdesi
        else:
            df['EMA_Slope'] = 0.0

        # --- KRİZ İNDİKATÖRÜ (Gerçekçi - son 10 mumda %3+ düşüş varsa) ---
        df['Kriz'] = np.where(df['Hedef_Close'].pct_change(periods=10) < -0.03, 1.0, 0.0)

        # 6. Hatalı Verileri Temizle
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)

        return df

    except Exception as e:
        print(f"❌ Veri Çekme Hatası ({hedef_coin}): {e}")
        return None

def ana_trend_getir(coin):
    """
    4 Saatlik (4h) grafikte ana trendin yönünü belirler.
    Basitçe EMA50 kullanımıyla. Fiyat EMA50'nin üzerindeyse UP, altındaysa DOWN kabul edilir.
    """
    try:
        df = _ccxt_veri_getir(coin, timeframe='4h', limit=100)
        if df is None or df.empty:
            return "NÖTR"
        
        # 50 periyotluk üstel hareketli ortalama (EMA)
        ema50 = ta.ema(df['close'], length=50)
        if ema50 is None:
            return "NÖTR"
        
        son_kapanis = df['close'].iloc[-1]
        son_ema50 = ema50.iloc[-1]
        
        if son_kapanis > son_ema50:
            return "UP"
        elif son_kapanis < son_ema50:
            return "DOWN"
        else:
            return "NÖTR"
            
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 1: BTC KORELASYON KALKANI
# Altcoin piyasası BTC'ye %85+ korelasyonla bağlıdır.
# BTC düşüyorsa altcoin LONG açma, BTC yükseliyorsa SHORT açma.
# ============================================================
_BTC_KALKAN_CACHE = {'yon': 'NÖTR', 'son_guncelleme': 0}

def btc_kalkan_kontrol():
    """
    BTC'nin son 1 saatlik trendini kontrol eder.
    Dönüş: 'UP', 'DOWN' veya 'NÖTR'
    Cache: 5 dakika (aynı döngüde tekrar API çağrısı yapmaz)
    """
    import time as _t
    simdi = _t.time()
    
    # 5 dakika cache (her coin için tekrar çağırmayı önle)
    if simdi - _BTC_KALKAN_CACHE['son_guncelleme'] < 300:
        return _BTC_KALKAN_CACHE['yon']
    
    try:
        df = _ccxt_veri_getir('BTC/USDT', timeframe='1h', limit=20)
        if df is None or df.empty:
            return "NÖTR"
        
        # EMA8 ve EMA21 ile kısa vadeli BTC trend yönü
        ema8 = ta.ema(df['close'], length=8)
        ema21 = ta.ema(df['close'], length=21)
        
        if ema8 is None or ema21 is None:
            return "NÖTR"
        
        son_ema8 = ema8.iloc[-1]
        son_ema21 = ema21.iloc[-1]
        son_kapanis = df['close'].iloc[-1]
        
        # Son 3 mumun yönünü de kontrol et (momentum)
        son_3_degisim = (df['close'].iloc[-1] - df['close'].iloc[-3]) / df['close'].iloc[-3] * 100
        
        if son_ema8 > son_ema21 and son_kapanis > son_ema8 and son_3_degisim > 0:
            yon = "UP"
        elif son_ema8 < son_ema21 and son_kapanis < son_ema8 and son_3_degisim < 0:
            yon = "DOWN"
        else:
            yon = "NÖTR"
        
        _BTC_KALKAN_CACHE['yon'] = yon
        _BTC_KALKAN_CACHE['son_guncelleme'] = simdi
        return yon
        
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 2: 1 SAATLİK ORTA VADELİ TREND HIZALAMASI
# 15m sinyal + 1h trend + 4h trend = hepsi aynı yön olmalı
# ============================================================
def orta_trend_getir(coin):
    """
    1 Saatlik (1h) grafikte orta vadeli trendin yönünü belirler.
    EMA20 kullanılır. Fiyat EMA20'nin üzerindeyse UP, altındaysa DOWN.
    """
    try:
        df = _ccxt_veri_getir(coin, timeframe='1h', limit=50)
        if df is None or df.empty:
            return "NÖTR"
        
        ema20 = ta.ema(df['close'], length=20)
        if ema20 is None:
            return "NÖTR"
        
        son_kapanis = df['close'].iloc[-1]
        son_ema20 = ema20.iloc[-1]
        
        # EMA20'nin eğimi de kontrol et (yataysa NÖTR)
        ema_slope = (ema20.iloc[-1] - ema20.iloc[-3]) / ema20.iloc[-3] * 100 if len(ema20) > 3 else 0
        
        if son_kapanis > son_ema20 and ema_slope > 0.05:
            return "UP"
        elif son_kapanis < son_ema20 and ema_slope < -0.05:
            return "DOWN"
        else:
            return "NÖTR"
            
    except Exception:
        return "NÖTR"

# ============================================================
# 🛡️ FİLTRE 3: GİRİŞ ZAMANLAMASI (EMA MESAFE KONTROLÜ)
# Fiyat EMA20'den çok uzaklaşmışsa → treni kaçırmışsın, girme!
# ============================================================
def ema_mesafe_kontrol(df, yon, atr):
    """
    Fiyatın EMA20'ye olan mesafesini kontrol eder.
    ATR x 1.5'ten fazla uzaklaşmışsa → giriş yapmak riskli.
    Dönüş: True = giriş uygun, False = çok uzak, girme
    """
    try:
        ema20 = ta.ema(df['Hedef_Close'], length=20)
        if ema20 is None:
            return True  # Hesaplanamıyorsa engelleme
        
        son_fiyat = df['Hedef_Close'].iloc[-1]
        son_ema20 = ema20.iloc[-1]
        mesafe = abs(son_fiyat - son_ema20)
        max_mesafe = atr * 1.5  # ATR'nin 1.5 katından fazla uzaksa tehlike
        
        if "YÜKSELİŞ" in yon and son_fiyat > son_ema20 + max_mesafe:
            return False  # LONG için: fiyat çok yukarıda, tepeyi kovalama
        elif "DÜŞÜŞ" in yon and son_fiyat < son_ema20 - max_mesafe:
            return False  # SHORT için: fiyat çok aşağıda, dibi kovalama
        
        return True  # Mesafe uygun, giriş yapılabilir
        
    except Exception:
        return True  # Hata durumunda engelleme