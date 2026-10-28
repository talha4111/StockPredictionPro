import ccxt
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
import sys
import os
from contextlib import contextmanager
from ai_core import BeyinMotoru
import warnings
from slippage_model import slippage_tahmini, slippage_uygula
from rejim import piyasa_rejimi_belirle

warnings.filterwarnings('ignore')

@contextmanager
def suppress_stdout():
    with open(os.devnull, "w", encoding='utf-8') as devnull:
        old_stdout = sys.stdout
        sys.stdout = devnull
        try:  
            yield
        finally:
            sys.stdout = old_stdout

# Hisseler ve Test Parametreleri
coinler = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
test_saati = 30 * 24 # 30 Günlük 1 Saatlik Veri
baslangic_kasa = 3800.0
BACKTEST_ROUND_TRIP_COST_RATE = 0.0015
MODEL_SIGNAL_THRESHOLD = 0.60

# 1.0 ATR Stop / 2.5 ATR Kar Al Sabit Stratejisi
rr_stop_carpan = 1.0
rr_target_carpan = 2.5

parametre_agı = [
    # Yüksek riskte farklı derinliklerde XGBoost modelleri
    {"n_estimators": 50, "max_depth": 3},
    {"n_estimators": 100, "max_depth": 6},
    {"n_estimators": 150, "max_depth": 4},
    {"n_estimators": 300, "max_depth": 5},
]

def ccxt_gecmis_tam(coin, ref_coin='BTC/USDT', limit=1500, timeframe='1h'):
    """
    Kripto backtesti için 1h boyutunda limitsiz CCXT geçmiş veri simülatörü
    ve indikatör üretim fonksiyonu
    """
    try:
        borsa = ccxt.binance({'enableRateLimit': True, 'options': {'adjustForTimeDifference': True, 'recvWindow': 60000}})
        # Hedef Coin
        bars = borsa.fetch_ohlcv(coin, timeframe, limit=limit)
        df_hedef = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_hedef['timestamp'] = pd.to_datetime(df_hedef['timestamp'], unit='ms')
        df_hedef.set_index('timestamp', inplace=True)

        # Referans Coin
        bars_ref = borsa.fetch_ohlcv(ref_coin, timeframe, limit=limit)
        df_ref = pd.DataFrame(bars_ref, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df_ref['timestamp'] = pd.to_datetime(df_ref['timestamp'], unit='ms')
        df_ref.set_index('timestamp', inplace=True)

        df = df_hedef[['close', 'high', 'low', 'volume']].copy()
        df.rename(columns={'close': 'Hedef_Close'}, inplace=True)
        
        ref_close = df_ref['close'].reindex(df.index)
        df['Ref_Close'] = ref_close.values

        # İndikatörler
        df['RSI'] = df.ta.rsi(close='Hedef_Close', length=14)
        macd = df.ta.macd(close='Hedef_Close', fast=12, slow=26, signal=9)
        df['MACD'] = macd.iloc[:, 0] if macd is not None else 0
        df['ATR'] = df.ta.atr(high='high', low='low', close='Hedef_Close', length=14)
        df['OBV'] = df.ta.obv(close=df['Hedef_Close'], volume=df['volume'])
        
        bbands = df.ta.bbands(close=df['Hedef_Close'], length=20)
        df['BB_Width'] = bbands.iloc[:, 3] if bbands is not None else 0
        df['MFI'] = df.ta.mfi(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'], length=14)

        vwap = df.ta.vwap(high=df['high'], low=df['low'], close=df['Hedef_Close'], volume=df['volume'])
        df['VWAP'] = vwap if vwap is not None else df['Hedef_Close']
        df['VP_Sapma'] = (df['Hedef_Close'] - df['VWAP']) / df['VWAP']

        df['Hedef_Ret'] = df['Hedef_Close'].pct_change()
        df['Ref_Ret'] = df['Ref_Close'].pct_change()
        df['Vol_Ret'] = df['volume'].pct_change()
        df['Korelasyon'] = df['Hedef_Ret'].rolling(window=14).corr(df['Ref_Ret'])
        df['Kriz'] = np.where(df['Hedef_Ret'] < -0.05, 1.0, 0.0)
        epsilon = 1e-9
        high_low_diff = df['high'] - df['low']
        high_low_diff = high_low_diff.replace(0, epsilon)
        
        tr = pd.concat([df['high'] - df['low'], (df['high'] - df['Hedef_Close'].shift()).abs(), (df['low'] - df['Hedef_Close'].shift()).abs()], axis=1).max(axis=1)
        tr = tr.replace(0, epsilon)
        df['CHOP'] = 100 * np.log10(tr.rolling(14).sum() / high_low_diff.rolling(14).max()) / np.log10(14)
        df['CHOP'].fillna(50, inplace=True)
        
        # Squeeze Momentum
        df['Squeeze_ON'] = (df['BB_Width'] < df.ta.atr(high='high', low='low', close='Hedef_Close', length=20) * 1.5).astype(int)
        
        # Sentimental Veriler (Backtestte geçmiş OI/Funding alınamadığı için hacimsel simüle edilir)
        df['Open_Interest'] = df['volume'].rolling(24).mean()
        df['Funding_Rate'] = df['Hedef_Ret'].rolling(8).mean()
        
        # Hisse motorundan kalma zorunlu yapıtaşı destekleyicileri
        df['Haber_Duygu_Puani'] = 50.0 
        df['Faiz_Orani'] = 50.0 
        df['Dolar_Kuru'] = df['Hedef_Close'] / 10.0

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.dropna(inplace=True)

        return df

    except Exception as e:
        print(f"❌ Veri Çekme Hatası ({coin}): {e}")
        return None

def backtest_calistir(params):
    toplam_islem = 0
    basarili_islem = 0
    toplam_pnl = 0.0
    kasa_bakiye = baslangic_kasa
    rejim_istatistikleri = {}
    
    n_est = params["n_estimators"]
    m_depth = params["max_depth"]
    
    for coin in coinler:
        try:
            with suppress_stdout():
                df_tam = ccxt_gecmis_tam(coin, ref_coin='BTC/USDT', limit=1500, timeframe='1h')
                
            if df_tam is None or len(df_tam) < test_saati + 200:
                print(f"  [X] Yeterli veri yok: {coin}")
                continue
                
            # Ekonomi / Kriz simülasyon uyumluluğu (BIST'deki altyapıyı Kriptoya uydurmak)
            df_tam['Kriz'] = np.where(df_tam['Hedef_Close'].pct_change() < -0.05, 1.0, 0.0)
            df_tam['Haber_Duygu_Puani'] = 50.0 
            
            aktif_pozisyon = None
            end_idx = len(df_tam)
            start_idx = end_idx - test_saati
            
            beyin = BeyinMotoru(n_estimators=n_est, max_depth=m_depth)
            
            for i in range(start_idx, end_idx):
                df_sim = df_tam.iloc[:i+1]
                
                if aktif_pozisyon is not None:
                    high = float(df_sim['high'].iloc[-1])
                    low = float(df_sim['low'].iloc[-1])
                    close = float(df_sim['Hedef_Close'].iloc[-1])
                    kapanma_fiyati = 0
                    is_stop = False
                    
                    p = aktif_pozisyon
                    
                    if p["yon"] == "LONG":
                        if low <= p["sl"]: 
                            kapanma_fiyati = p["sl"]
                            is_stop = True
                        elif high >= p["tp"]: kapanma_fiyati = p["tp"]
                    elif p["yon"] == "SHORT":
                        if high >= p["sl"]: 
                            kapanma_fiyati = p["sl"]
                            is_stop = True
                        elif low <= p["tp"]: kapanma_fiyati = p["tp"]
                        
                    if kapanma_fiyati != 0:
                        # Kripto margin işlem kar/zarar hesabı (Kaldıraç dahil edilmemiştir, 1x Spot mantığıyla K/Z hesaplanıp marjda yansıtılır)
                        hacim_24s = float(df_sim['volume'].iloc[-1]) * 24 * close
                        atr_pct = (float(df_sim['ATR'].iloc[-1]) / close) if 'ATR' in df_sim.columns else 0.02
                        notional = float(p["miktar"] * p["giris_fiyati"])
                        
                        kayma_yuzdesi = slippage_tahmini(hacim_24s, atr_pct, notional, is_stop)
                        kapanma_fiyati = slippage_uygula(kapanma_fiyati, kayma_yuzdesi, p["yon"], False)
                        
                        brut_kz = (kapanma_fiyati - p["giris_fiyati"]) * p["miktar"] 
                        if p["yon"] == "SHORT": brut_kz = -brut_kz
                        
                        islem_maliyeti = abs(p["giris_fiyati"] * p["miktar"]) * BACKTEST_ROUND_TRIP_COST_RATE
                        net_kz = brut_kz - islem_maliyeti
                        kasa_bakiye += net_kz
                        toplam_pnl += net_kz
                        toplam_islem += 1
                        
                        rj = p.get("rejim", "BILINMIYOR")
                        if rj not in rejim_istatistikleri:
                            rejim_istatistikleri[rj] = {"kazanc": 0, "kayip": 0, "pnl": 0.0}
                        rejim_istatistikleri[rj]["pnl"] += net_kz
                        
                        if net_kz > 0: 
                            basarili_islem += 1
                            rejim_istatistikleri[rj]["kazanc"] += 1
                        else:
                            rejim_istatistikleri[rj]["kayip"] += 1
                            
                        aktif_pozisyon = None
                    continue 
                    
                with suppress_stdout():
                    beyin.model_egit(coin, df_sim, is_crypto=True)
                    tahmin_olasilik = beyin.tahmin_et(coin, df_sim, is_crypto=True)
                    
                if tahmin_olasilik is None: continue
                
                yon = "NÖTR"
                if tahmin_olasilik >= MODEL_SIGNAL_THRESHOLD: yon = "LONG"
                elif tahmin_olasilik <= (1.0 - MODEL_SIGNAL_THRESHOLD): yon = "SHORT"
                
                if yon != "NÖTR":
                    anlik_fiyat = float(df_sim['Hedef_Close'].iloc[-1])
                    atr = float(df_sim['ATR'].iloc[-1]) if 'ATR' in df_sim.columns else (anlik_fiyat * 0.02)
                    
                    # Slippage uygula
                    hacim_24s = float(df_sim['volume'].iloc[-1]) * 24 * anlik_fiyat
                    atr_pct = atr / anlik_fiyat
                    notional_tahmini = kasa_bakiye * 0.20 * 5 # islem_boyutu * 5
                    
                    kayma_yuzdesi = slippage_tahmini(hacim_24s, atr_pct, notional_tahmini, False)
                    anlik_fiyat = slippage_uygula(anlik_fiyat, kayma_yuzdesi, yon, True)
                    
                    sl_mesafe = atr * rr_stop_carpan
                    tp_mesafe = atr * rr_target_carpan 
                    
                    if yon == "LONG":
                        tp_fiyat = anlik_fiyat + tp_mesafe
                        sl_fiyat = anlik_fiyat - sl_mesafe
                    else:
                        tp_fiyat = anlik_fiyat - tp_mesafe
                        sl_fiyat = anlik_fiyat + sl_mesafe
                        
                    # Agresif bir bakiye harcaması (Kaldıraçsız, %20 bakiyeyle teste sokalım, kasa toparlansın)
                    islem_boyutu = kasa_bakiye * 0.20
                    miktar = (islem_boyutu * 5) / anlik_fiyat # Kripto için %20 kasa kullanımı * 5x Kaldıraç etkisi (Sanal Hacim)
                    
                    mevcut_rejim = piyasa_rejimi_belirle(df_sim.iloc[-1])
                    aktif_pozisyon = {
                        "yon": yon, "giris_fiyati": anlik_fiyat, "miktar": miktar,
                        "tp": tp_fiyat, "sl": sl_fiyat,
                        "rejim": mevcut_rejim
                    }

            if aktif_pozisyon is not None:
                p = aktif_pozisyon
                son_fiyat = float(df_tam['Hedef_Close'].iloc[-1])
                brut_kz = (son_fiyat - p["giris_fiyati"]) * p["miktar"]
                kar_zarar = brut_kz if p["yon"] == "LONG" else -brut_kz
                islem_maliyeti = abs(p["giris_fiyati"] * p["miktar"]) * BACKTEST_ROUND_TRIP_COST_RATE
                net_kz = kar_zarar - islem_maliyeti
                kasa_bakiye += net_kz
                toplam_pnl += net_kz
                toplam_islem += 1
                
                rj = p.get("rejim", "BILINMIYOR")
                if rj not in rejim_istatistikleri:
                    rejim_istatistikleri[rj] = {"kazanc": 0, "kayip": 0, "pnl": 0.0}
                rejim_istatistikleri[rj]["pnl"] += net_kz
                
                if net_kz > 0: 
                    basarili_islem += 1
                    rejim_istatistikleri[rj]["kazanc"] += 1
                else:
                    rejim_istatistikleri[rj]["kayip"] += 1

        except Exception as e:
            print(f"  [X] Backtest hatasi ({coin}): {e}")
            
    basari_orani = (basarili_islem / toplam_islem * 100) if toplam_islem > 0 else 0
    return {"params": params, "total_trades": toplam_islem, "win_rate": basari_orani, "pnl": toplam_pnl, "son_kasa": kasa_bakiye, "rejim_istatistikleri": rejim_istatistikleri}

if __name__ == "__main__":
    print("="*70)
    print("🚀 KRİPTO XGBOOST ZAMAN MAKİNESİ BAŞLATILIYOR (1 Saatlik)")
    print(f"🔸 Strateji: 1.0 ATR Zırh / 2.5 ATR Kar Al | 5x Kaldıraç Etkisi")
    print(f"🔸 Başlangıç Kurtarma Kasası: {baslangic_kasa:,.2f} USDT")
    print("="*70)
    print("🧬 Parametre optimizasyon süreci çalışıyor, lütfen bekleyin...\n")

    en_iyi_sonuc = None

    for idx, p in enumerate(parametre_agı):
        r_isim = f"Model {idx+1} [Trees:{p['n_estimators']}, Depth:{p['max_depth']}]"
        print(f"🔄 Test Ediliyor -> {r_isim}...")
        
        sonuc = backtest_calistir(p)
        
        print(f"   => İşlem: {sonuc['total_trades']} | Başarı: %{sonuc['win_rate']:.1f} | K/Z: {sonuc['pnl']:+,.2f} USDT")
        
        if (en_iyi_sonuc is None) or (sonuc['pnl'] > en_iyi_sonuc['pnl'] and sonuc['total_trades'] > 5):
            en_iyi_sonuc = sonuc
            
        # WinRate %40 ve PNL 1000 USDT üzeri kurtarma olursa dur
        if sonuc['pnl'] > 1000.0 and sonuc['win_rate'] >= 40.0 and sonuc['total_trades'] > 0:
            print(f"✨ HEDEF BAŞARI YAKALANDI! Kasa Hızla Toparlandı.")
            break

    print("\n" + "="*70)
    print("🏆 KRİPTO OPTİMİZASYON SONUCU: EN İYİ XGBOOST MODELİ")
    print("="*70)
    
    if en_iyi_sonuc:
        p = en_iyi_sonuc['params']
        print(f"✅ Tavsiye Edilen n_estimators : {p['n_estimators']}")
        print(f"✅ Tavsiye Edilen max_depth    : {p['max_depth']}")
        print("-" * 70)
        print(f"📊 Toplam İşlem               : {en_iyi_sonuc['total_trades']}")
        print(f"🎯 WIN RATE (Başarı Oranı)    : %{en_iyi_sonuc['win_rate']:.2f}")
        print(f"💰 Sanal K/Z Net              : {en_iyi_sonuc['pnl']:+,.2f} USDT")
        print(f"💳 Süreç Sonu Kurtarılan Kasa : {en_iyi_sonuc['son_kasa']:,.2f} USDT")
    else:
        print("Geçerli bir sonuç üretilemedi.")
    print("="*70)
