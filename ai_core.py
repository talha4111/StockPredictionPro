import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
import joblib
import os

class BeyinMotoru:
    def __init__(self, n_estimators=300, max_depth=4):
        # Ortak model hiperparametreleri (Overfit önlemleri alınmış V6 Ayarları)
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.min_samples_split = 20
        self.min_samples_leaf = 10
        self.random_state = 42
        
        # Kullanılacak Özellik Sütunları Ayrıştırıldı (Borsa vs Kripto)
        self.stock_features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']
        self.crypto_features = self.stock_features + ['Open_Interest', 'Funding_Rate', 'CHOP', 'Squeeze_ON']

    def df_hazirla(self, df):
        """
        Gelen ham DataFrame'i (Kripto veya Hisse) modelin anlayacağı eğitim formatına çevirir.
        Geleceği (1 saat / 4 mum sonrası) tahmin eden hedef değişkenini (Y) üretir.
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
            df['Korelasyon'] = 0.0 # Boşsa nötr referans korelasyonu doldur
        if 'Kriz' not in df.columns:
            df['Kriz'] = 0.0 
        if 'Haber_Duygu_Puani' not in df.columns:
            df['Haber_Duygu_Puani'] = 50.0 
        if 'Faiz_Orani' not in df.columns:
            df['Faiz_Orani'] = 50.0  # Varsayılan TR Politika Faizi %50
        if 'Dolar_Kuru' not in df.columns:
            df['Dolar_Kuru'] = df['Hedef_Close'] / 10.0 # Sembolik
            
        # Yeni Eklenen Güçlü Metrikler (Eksikse Baseline Doldurur)
        if 'Open_Interest' not in df.columns: df['Open_Interest'] = 0.0
        if 'Funding_Rate' not in df.columns: df['Funding_Rate'] = 0.0001
        if 'CHOP' not in df.columns: df['CHOP'] = 50.0
        if 'Squeeze_ON' not in df.columns: df['Squeeze_ON'] = 0.0
            
        # Data Leakage olmadan 4 mum sonrasının getiri oranını hesapla
        df['Gelecek_Ret'] = (df['Hedef_Close'].shift(-4) - df['Hedef_Close']) / df['Hedef_Close']
        df.dropna(inplace=True)
        
        # 0'dan büyükse Yükseliş(1), değilse Düşüş(0)
        df['Hedef_Yön'] = np.where(df['Gelecek_Ret'] > 0, 1, 0)
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
        Dönüş: Tahmin Olasılığı (Float, 0.0 ile 1.0 arası)
        """
        safe_name = sembol.replace('/', '-')
        prefix = "beyin" if is_crypto else "stock_beyin"
        model_adi = f'{prefix}_{safe_name}.pkl'
        
        try:
            model = joblib.load(model_adi)
        except:
            print(f"❌ {model_adi} bulunamadı! Lütfen önce model_egit fonksiyonunu çalıştırın.")
            return None
            
        # Son satırdaki canlı teknik göstergeleri al
        aktif_features = self.crypto_features if is_crypto else self.stock_features
        giris = df[aktif_features].values[-1:]
        olasiliklar = model.predict_proba(giris)
        
        # 1 (Yükseliş) sınıfının olasılığını döndür
        return float(olasiliklar[0][1])
