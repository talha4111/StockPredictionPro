import numpy as np
import pandas as pd
try:
    from sklearn.ensemble import RandomForestClassifier
except Exception:
    class RandomForestClassifier:
        def __init__(self, *args, **kwargs): pass
        def fit(self, X, y): return self
        def predict_proba(self, X): return np.full((len(X), 2), 0.5)
import joblib
import os

class BeyinMotoru:
    def __init__(self, n_estimators=450, max_depth=8):
        # Optuna window validation winner (2026-07-11): 450 trees, depth 8.
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = 20
        self.min_samples_leaf = 10
        self.random_state = 42
        
        # Kullanılacak Özellik Sütunları (Sadece GERÇEK verİ — sahte/sabit değerler çıkarıldı)
        self.stock_features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'ADX', 'EMA_Slope']
        self.crypto_features = self.stock_features + ['Open_Interest', 'Funding_Rate', 'CHOP', 'Squeeze_ON']

    @staticmethod
    def _triple_barrier_etiketle(df, horizon_bars, min_target_return):
        close_p = df['Hedef_Close'].values
        high_p = df['High'].values if 'High' in df.columns else close_p
        low_p = df['Low'].values if 'Low' in df.columns else close_p
        
        n = len(df)
        labels = np.full(n, np.nan)
        actual_returns = np.full(n, np.nan)
        
        upper_barrier = close_p * (1 + min_target_return)
        lower_barrier = close_p * (1 - min_target_return)
        
        unresolved = np.ones(n, dtype=bool)
        
        for step in range(1, horizon_bars + 1):
            if step >= n:
                break
                
            curr_high = np.zeros(n)
            curr_low = np.zeros(n)
            curr_high[:-step] = high_p[step:]
            curr_low[:-step] = low_p[step:]
            
            valid = unresolved & (np.arange(n) < n - step)
            
            hit_l = valid & (curr_low <= lower_barrier)
            hit_u = valid & (curr_high >= upper_barrier) & ~hit_l
            
            labels[hit_l] = 0.0
            actual_returns[hit_l] = (curr_low[hit_l] - close_p[hit_l]) / close_p[hit_l]
            unresolved[hit_l] = False
            
            labels[hit_u] = 1.0
            actual_returns[hit_u] = (curr_high[hit_u] - close_p[hit_u]) / close_p[hit_u]
            unresolved[hit_u] = False

        valid_vertical = unresolved & (np.arange(n) < n - horizon_bars)
        if np.any(valid_vertical):
            curr_close = np.zeros(n)
            curr_close[:-horizon_bars] = close_p[horizon_bars:]
            actual_returns[valid_vertical] = (curr_close[valid_vertical] - close_p[valid_vertical]) / close_p[valid_vertical]
            
        return labels, actual_returns

    def df_hazirla(self, df, horizon_bars=8, min_target_return=0.015):
        """
        Gelen ham DataFrame'i (Kripto veya Hisse) modelin anlayacağı eğitim formatına çevirir.
        Triple-Barrier Labeling kullanılarak hedef değişkeni (Y) üretilir.
        """
        # Hisselerde "Hedef_Close", "Ref_Ret" gibi isimlendirmeler olmayabilir, eksikleri tamamla
        if 'Hedef_Close' not in df.columns and 'Close' in df.columns:
            df['Hedef_Close'] = df['Close']
        if 'Hedef_Ret' not in df.columns:
            df['Hedef_Ret'] = df['Hedef_Close'].pct_change()
        if 'Ref_Ret' not in df.columns:
            df['Ref_Ret'] = 0.0 # Hisselerde referans coin yoksa 0 (Nötr) geç
        if 'Vol_Ret' not in df.columns and 'Volume' in df.columns:
            df['Vol_Ret'] = df['Volume'].pct_change()
        if 'Korelasyon' not in df.columns:
            df['Korelasyon'] = 0.0
        if 'Kriz' not in df.columns:
            df['Kriz'] = 0.0 
        if 'ADX' not in df.columns:
            df['ADX'] = 25.0  # Nötr ADX değeri
        if 'EMA_Slope' not in df.columns:
            df['EMA_Slope'] = 0.0  # Nötr trend
            
        # Kripto Özel Metrikler (Eksikse Baseline Doldurur)
        if 'Open_Interest' not in df.columns: df['Open_Interest'] = 0.0
        if 'Funding_Rate' not in df.columns: df['Funding_Rate'] = 0.0001
        if 'CHOP' not in df.columns: df['CHOP'] = 50.0
        if 'Squeeze_ON' not in df.columns: df['Squeeze_ON'] = 0.0
            
        # Triple-Barrier Yöntemi ile etiketleme yap
        etiketler, gercek_getiriler = self._triple_barrier_etiketle(df, horizon_bars, min_target_return)
        
        df['Gelecek_Ret'] = gercek_getiriler
        df['Hedef_Yön'] = etiketler
        
        # NaN etiketleri (nötr durumları) ve diğer NaN içeren satırları at
        df.dropna(subset=['Hedef_Yön'], inplace=True)
        df.dropna(inplace=True)
        
        df['Hedef_Yön'] = df['Hedef_Yön'].astype(int)
        return df

    def model_egit(self, sembol, df, is_crypto=True):
        """
        Verilen DataFrame üzerinden XGBoost modelini eğitir ve kaydeder.
        """
        import time
        baslama_zamani = time.time()
        
        df = self.df_hazirla(df)
        
        # Karantina: Son 100 periyodu test için bırak, ezberlemesin (Out-of-Sample)
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        X = df[aktif_features].values[:-100]
        y = df['Hedef_Yön'].values[:-100]

        kullanilacak_estimators = self.n_estimators
        
        # XGBoost Classifier geçiş yapıldı (Süper Zeka 3.0)
        # BIST'in karmaşık doğasına uygun olarak daha agresif ve isabetli bir karar ağacı
        import xgboost as xgb
        
        model = xgb.XGBClassifier(
            n_estimators=kullanilacak_estimators,
            max_depth=self.max_depth,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=1.0, # Sınıf dengesizliği için
            random_state=self.random_state,
            eval_metric="logloss"
        )
        
        tip = "Kripto" if is_crypto else "Hisse"
        print(f"⏳ {sembol} ({tip}) XGBoost modeli eğitime alındı...")
        model.fit(X, y)
        
        # İsmi kaydet
        safe_name = sembol.replace('/', '-')
        prefix = "beyin" if is_crypto else "stock_beyin"
        dosya_adi = f'{prefix}_{safe_name}.pkl'
        
        joblib.dump(model, dosya_adi)
        gecen_sure = time.time() - baslama_zamani
        print(f"✅ {sembol} DİNAMİK MODEL HAZIR (Süre: {gecen_sure:.2f} Saniye)")
        return model

    def tahmin_et(self, sembol, df, is_crypto=True):
        """
        Önceden eğitilmiş modeli yükler ve gelen ANLIK veri (df) üzerinden son satırı okuyarak tahminde bulunur.
        Model dosyası yoksa otomatik olarak eğitir (Auto-Train).
        Dönüş: Tahmin Olasılığı (Float, 0.0 ile 1.0 arası)
        """
        safe_name = sembol.replace('/', '-')
        prefix = "beyin" if is_crypto else "stock_beyin"
        model_adi = f'{prefix}_{safe_name}.pkl'
        
        model = None
        try:
            model = joblib.load(model_adi)
        except:
            # Model dosyası yok → Otomatik eğit (sessiz mod)
            try:
                model = self.model_egit(sembol, df.copy(), is_crypto)
            except Exception as e:
                print(f"⚠️ {sembol} model eğitimi başarısız: {e}")
                return None
            
        if model is None:
            return None
            
        # Son satırdaki canlı teknik göstergeleri al
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        giris = df[aktif_features].values[-1:]
        olasiliklar = model.predict_proba(giris)
        
        # 1 (Yükseliş) sınıfının olasılığını döndür
        return float(olasiliklar[0][1])
