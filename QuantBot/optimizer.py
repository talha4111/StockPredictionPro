"""
🔬 GÖLGE OPTİMİZASYON (Shadow Optimization) Motoru v2
====================================================
Optuna ile RSI, MACD, ATR ve XGBoost eşik parametrelerini
gerçek piyasa verisi üzerinde vektörel backtest ile optimize eder.
Hedef: Matematiksel Beklenti (Expectancy) Maksimizasyonu.

v2: Veri önbellekleme (caching) ile API Rate Limit sorunu çözüldü.
    Tüm veri SADECE 1 KERE çekilir, 500 deneme lokal RAM üzerinde koşar.
"""

import optuna
import pandas as pd
import pandas_ta as ta
import numpy as np
import warnings
import time
import json

# Tarayıcıdaki veri çekme fonksiyonunu içeri aktar
from tarayici import _ccxt_veri_getir
from performance_metrics import metrik_ozeti, metrik_satiri, trade_metriklerini_hesapla, train_forward_bol

# Optuna ve pandas uyarılarını bastır
optuna.logging.set_verbosity(optuna.logging.WARNING)
warnings.filterwarnings('ignore')

# ============================================================
# Sabitler
# ============================================================
TEST_COINLERI = ['BTC/USDT', 'ETH/USDT']
BASLANGIC_KASA = 1000.0
KALDIRAC = 3
KOMISYON_ORANI = 0.0005  # Taker Fee (%0.05)
FORWARD_TEST_ORANI = 0.30

# ============================================================
# GLOBAL ÖN BELLEK (Cache) — API'den 1 kere doldurulur
# ============================================================
ONBELLEK: dict[str, pd.DataFrame] = {}


def onbellek_doldur():
    """
    Tüm test coinleri için son 7 günlük 5m OHLCV verisini
    Binance API'den SADECE 1 KEZ çeker ve ONBELLEK sözlüğüne yazar.
    """
    print("📡 [CACHE] Veriler Binance'ten indiriliyor (tek seferlik)...")
    for coin in TEST_COINLERI:
        for deneme in range(3):
            df = _ccxt_veri_getir(coin, timeframe='5m', limit=2016)
            if df is not None and len(df) > 100:
                ONBELLEK[coin] = df.copy()
                print(f"  ✅ {coin}: {len(df)} bar önbelleğe alındı.")
                break
            else:
                print(f"  ⚠️ {coin} çekme denemesi {deneme+1}/3 başarısız, yeniden deneniyor...")
                time.sleep(3)

        if coin not in ONBELLEK:
            print(f"  ❌ {coin}: Veri çekilemedi, bu coin optimizasyondan çıkarılacak.")

    print(f"📦 [CACHE] Önbellek hazır: {len(ONBELLEK)}/{len(TEST_COINLERI)} coin yüklendi.\n")


def indikator_hesapla(df_raw: pd.DataFrame, rsi_length: int, macd_fast: int) -> pd.DataFrame | None:
    """
    Önceden indirilmiş ham OHLCV DataFrame üzerinde
    Optuna'nın belirlediği parametrelerle indikatör hesaplar.
    API ÇAĞRISI YAPMAZ — sadece lokal matematik.
    """
    df = df_raw.copy()

    df['RSI'] = ta.rsi(df['close'], length=rsi_length)
    macd_df = ta.macd(df['close'], fast=macd_fast, slow=26, signal=9)
    if macd_df is not None:
        df['MACD'] = macd_df.iloc[:, 0]
        df['MACD_Signal'] = macd_df.iloc[:, 2]
    else:
        df['MACD'] = 0.0
        df['MACD_Signal'] = 0.0

    df['ATR'] = ta.atr(df['high'], df['low'], df['close'], length=14)
    df.dropna(inplace=True)

    if len(df) < 50:
        return None
    return df


def vektorel_backtest(df: pd.DataFrame, atr_multiplier: float, xgboost_threshold: float) -> dict:
    """
    Vektörel backtest — bellekteki DataFrame üzerinde çalışır.
    API çağrısı SIFIR.
    """
    islemler = []
    pozisyon = None

    closes = df['close'].values
    highs = df['high'].values
    lows = df['low'].values
    rsi_vals = df['RSI'].values
    macd_vals = df['MACD'].values
    macd_sig = df['MACD_Signal'].values
    atr_vals = df['ATR'].values

    kasa = BASLANGIC_KASA

    for i in range(1, len(df)):
        fiyat = closes[i]
        high = highs[i]
        low = lows[i]
        atr = atr_vals[i]

        if atr <= 0 or fiyat <= 0:
            continue

        # --- Pozisyon açıkken kontrol ---
        if pozisyon is not None:
            if pozisyon['yon'] == 'LONG':
                if high >= pozisyon['tp']:
                    pnl_brut = (pozisyon['tp'] - pozisyon['giris']) * pozisyon['miktar']
                    komisyon = pozisyon['hacim'] * KOMISYON_ORANI * 2
                    islemler.append({'yon': 'LONG', 'pnl': pnl_brut - komisyon})
                    kasa += pnl_brut - komisyon
                    pozisyon = None
                elif low <= pozisyon['sl']:
                    pnl_brut = (pozisyon['sl'] - pozisyon['giris']) * pozisyon['miktar']
                    komisyon = pozisyon['hacim'] * KOMISYON_ORANI * 2
                    islemler.append({'yon': 'LONG', 'pnl': pnl_brut - komisyon})
                    kasa += pnl_brut - komisyon
                    pozisyon = None
            else:  # SHORT
                if low <= pozisyon['tp']:
                    pnl_brut = (pozisyon['giris'] - pozisyon['tp']) * pozisyon['miktar']
                    komisyon = pozisyon['hacim'] * KOMISYON_ORANI * 2
                    islemler.append({'yon': 'SHORT', 'pnl': pnl_brut - komisyon})
                    kasa += pnl_brut - komisyon
                    pozisyon = None
                elif high >= pozisyon['sl']:
                    pnl_brut = (pozisyon['giris'] - pozisyon['sl']) * pozisyon['miktar']
                    komisyon = pozisyon['hacim'] * KOMISYON_ORANI * 2
                    islemler.append({'yon': 'SHORT', 'pnl': pnl_brut - komisyon})
                    kasa += pnl_brut - komisyon
                    pozisyon = None
            continue

        # --- Sinyal Üretimi (Simüle XGBoost Skoru) ---
        rsi = rsi_vals[i]
        macd = macd_vals[i]
        macd_s = macd_sig[i]

        if rsi < 40 and macd > macd_s:
            guven = 0.5 + (40 - rsi) / 200 + min(0.1, abs(macd - macd_s) / fiyat * 1000)
            if guven > xgboost_threshold:
                margin = kasa * 0.30
                hacim = margin * KALDIRAC
                miktar = hacim / fiyat
                pozisyon = {
                    'yon': 'LONG', 'giris': fiyat,
                    'tp': fiyat + (atr * atr_multiplier),
                    'sl': fiyat - (atr * 1.0),
                    'miktar': miktar, 'hacim': hacim
                }

        elif rsi > 60 and macd < macd_s:
            guven = 0.5 + (rsi - 60) / 200 + min(0.1, abs(macd_s - macd) / fiyat * 1000)
            if guven > xgboost_threshold:
                margin = kasa * 0.30
                hacim = margin * KALDIRAC
                miktar = hacim / fiyat
                pozisyon = {
                    'yon': 'SHORT', 'giris': fiyat,
                    'tp': fiyat - (atr * atr_multiplier),
                    'sl': fiyat + (atr * 1.0),
                    'miktar': miktar, 'hacim': hacim
                }

    sonuc = trade_metriklerini_hesapla(islemler, BASLANGIC_KASA)
    if sonuc['toplam_islem'] == 0:
        sonuc['expectancy'] = -1.0
    return sonuc


def objective(trial):
    """
    Optuna Objective — İnternete DOKUNMAZ.
    Sadece ONBELLEK'teki DataFrameler üzerinde çalışır.
    """
    rsi_length = trial.suggest_int("rsi_length", 7, 21)
    macd_fast = trial.suggest_int("macd_fast", 8, 15)
    atr_multiplier = trial.suggest_float("atr_multiplier", 1.0, 3.0)
    xgboost_threshold = trial.suggest_float("xgboost_threshold", 0.51, 0.58)

    toplam_expectancy = 0.0
    gecerli_coin = 0

    for coin in TEST_COINLERI:
        if coin not in ONBELLEK:
            continue

        # Lokal indikatör hesaplama (API çağrısı YOK)
        df = indikator_hesapla(ONBELLEK[coin], rsi_length, macd_fast)
        if df is None:
            continue
        try:
            df_train, _ = train_forward_bol(df, forward_oran=FORWARD_TEST_ORANI, min_train=250, min_forward=100)
        except ValueError:
            continue

        sonuc = vektorel_backtest(df_train, atr_multiplier, xgboost_threshold)

        if sonuc['toplam_islem'] < 5:
            toplam_expectancy += -1.0
        else:
            toplam_expectancy += sonuc['expectancy']
        gecerli_coin += 1

    if gecerli_coin == 0:
        return -100.0

    return toplam_expectancy / gecerli_coin


# ============================================================
# ANA ÇALIŞTIRMA BLOĞU
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("🔬 GÖLGE OPTİMİZASYON MOTORU v2 BAŞLATILIYOR")
    print("=" * 60)
    print(f"Test Coinleri : {TEST_COINLERI}")
    print(f"Deneme Sayısı : 500")
    print(f"Hedef         : Expectancy Maksimizasyonu")
    print(f"Veri Ayrımı   : %{(1-FORWARD_TEST_ORANI)*100:.0f} train / %{FORWARD_TEST_ORANI*100:.0f} forward")
    print(f"API Stratejisi: TEK SEFER İNDİR → 500x LOKAL ÇALIŞTIR")
    print("=" * 60)

    # ========== ADIM 1: VERİ ÖN BELLEĞİ DOLDUR (Tek seferlik API) ==========
    onbellek_doldur()

    if not ONBELLEK:
        print("❌ Hiçbir coin verisi indirilemedi. Çıkılıyor.")
        exit(1)

    # ========== ADIM 2: 500 DENEME (Sıfır API — Tamamen Lokal) ==========
    print("⚡ 500 deneme başlıyor (tamamen lokal, API çağrısı SIFIR)...\n")
    baslangic = time.time()

    study = optuna.create_study(
        direction="maximize",
        study_name="kaptan_kripto_golge_v2"
    )
    study.optimize(objective, n_trials=500, show_progress_bar=True)

    sure = time.time() - baslangic

    # ========== ADIM 3: SONUÇLAR ==========
    best = study.best_trial
    print("\n" + "=" * 60)
    print("🏆 OPTİMİZASYON TAMAMLANDI - EN İYİ PARAMETRELER")
    print("=" * 60)
    print(f"  RSI Length       : {best.params['rsi_length']}")
    print(f"  MACD Fast        : {best.params['macd_fast']}")
    print(f"  ATR Multiplier   : {best.params['atr_multiplier']:.2f}")
    print(f"  XGBoost Threshold: {best.params['xgboost_threshold']:.4f}")
    print(f"  En İyi Beklenti  : {best.value:.4f}")
    print(f"  Toplam Süre      : {sure:.1f} saniye")
    print("=" * 60)

    # Detaylı rapor
    print("\n📊 EN İYİ PARAMETRELERLE TRAIN / FORWARD RAPORU:")
    print("-" * 50)
    forward_raporu = []
    for coin in TEST_COINLERI:
        if coin not in ONBELLEK:
            continue
        df = indikator_hesapla(ONBELLEK[coin], best.params['rsi_length'], best.params['macd_fast'])
        if df is not None:
            try:
                df_train, df_forward = train_forward_bol(df, forward_oran=FORWARD_TEST_ORANI, min_train=250, min_forward=100)
            except ValueError as e:
                print(f"\n  {coin}: forward ayrımı yapılamadı: {e}")
                continue

            train_sonuc = vektorel_backtest(df_train, best.params['atr_multiplier'], best.params['xgboost_threshold'])
            forward_sonuc = vektorel_backtest(df_forward, best.params['atr_multiplier'], best.params['xgboost_threshold'])
            print(f"\n  {coin}:")
            print(f"    Train   : {metrik_satiri(train_sonuc)}")
            print(f"    Forward : {metrik_satiri(forward_sonuc)}")
            if train_sonuc['expectancy'] > 0 and forward_sonuc['expectancy'] <= 0:
                print("    Uyarı   : Train pozitif ama forward beklenti negatif; overfit riski yüksek.")
            forward_raporu.append({
                "coin": coin,
                "params": dict(best.params),
                "train": metrik_ozeti(train_sonuc),
                "forward": metrik_ozeti(forward_sonuc),
                "overfit_uyarisi": bool(train_sonuc['expectancy'] > 0 and forward_sonuc['expectancy'] <= 0),
            })

    if forward_raporu:
        with open("forward_test_report.json", "w", encoding="utf-8") as f:
            json.dump(forward_raporu, f, ensure_ascii=False, indent=2)
        print("\n🧾 Forward raporu yazıldı: forward_test_report.json")
    print("\n" + "=" * 60)
    print("🔬 Gölge Optimizasyon Tamamlandı. Sonuçları main.py'ye uygulayabilirsiniz.")
    print("=" * 60)
