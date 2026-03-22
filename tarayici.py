import pandas as pd
import pandas_ta as ta
import numpy as np
import ccxt
import time

# --- CCXT Global API ---
borsa_api = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}})

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

        # 3. Sütun Hazırlama (ccxt zaten tek boyutlu ve küçük harfli)
        df = df_hedef[['close', 'high', 'low', 'volume']].copy()
        df.rename(columns={'close': 'Hedef_Close'}, inplace=True)
        
        # Ref_Close ataması - index hizalayarak tek sütun olarak ekliyoruz
        ref_close = df_ref['close'].reindex(df.index)
        df['Ref_Close'] = ref_close.values

        # --- Epsilon Yaması (Sıfıra Bölünme / RuntimeWarning Koruması) ---
        # Eğer bir mumda High ve Low eşitse (True Range 0), payda belirsizliği yüzünden CHOP ve Squeeze motoru çöker.
        # Bu yüzden çok ufak bir Epsilon (1e-9) sapması ekliyoruz.
        mask_equal = (df['high'] == df['low'])
        df.loc[mask_equal, 'high'] += 1e-9
        df.loc[mask_equal, 'low'] -= 1e-9

        # 4. İndikatör Hesaplamaları
        df['RSI'] = df.ta.rsi(close='Hedef_Close', length=14)
        
        macd = df.ta.macd(close='Hedef_Close', fast=12, slow=26, signal=9)
        df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
        
        df['ATR'] = df.ta.atr(high='high', low='low', close='Hedef_Close', length=14)

        # Yeni Eklenen Kritik Sensörler
        df['OBV'] = df.ta.obv(close=df['Hedef_Close'], volume=df['volume'])
        
        bbands = df.ta.bbands(close=df['Hedef_Close'], length=20)
        df['BB_Width'] = bbands.iloc[:, 3] if bbands is not None else 0
        
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
        df['Hedef_Ret'] = df['Hedef_Close'].pct_change()
        df['Ref_Ret'] = df['Ref_Close'].pct_change()
        df['Vol_Ret'] = df['volume'].pct_change()
        df['Korelasyon'] = df['Hedef_Ret'].rolling(window=14).corr(df['Ref_Ret'])

        # --- YENİ EKLENEN MAKRO VE KRİZ İNDİKATÖRLERİ (XGBoost Uyumlu) ---
        df['Kriz'] = np.where(df['Hedef_Ret'] < -0.05, 1.0, 0.0) # Basit kriz simülasyonu
        df['Haber_Duygu_Puani'] = 50.0 
        df['Faiz_Orani'] = 50.0 
        df['Dolar_Kuru'] = df['Hedef_Close'] / 10.0 

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