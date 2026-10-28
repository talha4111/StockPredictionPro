import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from tensorflow.keras.models import load_model
from sklearn.preprocessing import MinMaxScaler
from tarayici import veri_getir_dortlu
import json

try:
    with open('ayar.json', 'r') as f: AYAR = json.load(f)
    RISK = AYAR["risk_yonetimi"]
    HEDEF, REF = AYAR["hedef_varlik"], AYAR["referans_varlik"]
except: exit()

def backtest_baslat():
    print(f"\n⏳ BACKTEST (V4 - Delta Modeli) | {HEDEF}")
    
    try: model = load_model('beyin_v4.keras')
    except: print("❌ Model yok!"); return

    df = veri_getir_dortlu(HEDEF, REF)
    if df is None: return

    # Veri Hazırlığı
    features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon']
    scaler = MinMaxScaler(feature_range=(-1, 1))
    dataset = scaler.fit_transform(df[features].values)
    
    X_test, gercek_fiyatlar, tarihler = [], [], []
    look_back = 60
    
    for i in range(look_back, len(dataset)):
        X_test.append(dataset[i-look_back:i, :])
        # İşlem simülasyonu için gerçek kapanış fiyatlarını sakla
        gercek_fiyatlar.append(df['Hedef_Close'].iloc[i])
        tarihler.append(df.index[i])
        
    X_test = np.array(X_test)
    
    # 1. Tahmin Et (Yüzde Değişimi Verir)
    tahmin_ret_scaled = model.predict(X_test, verbose=0)
    
    # 2. Ölçeği Tersine Çevir
    dummy = np.zeros((len(tahmin_ret_scaled), 6))
    dummy[:, 0] = tahmin_ret_scaled[:, 0]
    tahmin_ret = scaler.inverse_transform(dummy)[:, 0] # Örn: 0.015 (%1.5)

    # 3. Fiyata Çevir (Bugünkü Fiyat * (1 + Tahmini Yüzde))
    tahmin_fiyatlar = []
    # Dikkat: i. gündeki tahmin, i+1. günün yüzdesidir.
    # Tahmin[i] = Yarınki değişim oranı.
    # Biz X_test'i hazırlarken bugüne kadar olan veriyi verdik.
    
    cuzdan = 1000
    islem_gecmisi = []
    kazanan, kaybeden = 0, 0

    print("⚔️ SİMÜLASYON BAŞLIYOR...")
    
    for i in range(len(tahmin_ret) - 1):
        bugun_fiyat = gercek_fiyatlar[i]
        
        # Model diyor ki: Yarın %X değişecek
        tahmini_yuzde = tahmin_ret[i]
        hedef_fiyat = bugun_fiyat * (1 + tahmini_yuzde)
        
        # Yön Kararı (Eşik Değeri Koyuyoruz: %0.5'ten küçük oynamaları ciddiye alma)
        esik = 0.005 
        
        yon = "NÖTR"
        if tahmini_yuzde > esik: yon = "LONG"
        elif tahmini_yuzde < -esik: yon = "SHORT"
        
        # Sonuç Kontrolü (Yarın ne oldu?)
        yarin_fiyat = gercek_fiyatlar[i+1]
        degisim = (yarin_fiyat - bugun_fiyat) / bugun_fiyat
        
        kar_zarar = 0
        
        # Basit Simülasyon (Stop/TP olmadan saf yön başarısı)
        # Eğer Long dediysek ve arttıysa kazanırız.
        if yon == "LONG":
            kar_zarar = (yarin_fiyat - bugun_fiyat) 
        elif yon == "SHORT":
            kar_zarar = (bugun_fiyat - yarin_fiyat)
            
        # Kaldıraçsız, 1 adet SOL ile işlem yapmış gibi
        if yon != "NÖTR":
            cuzdan += kar_zarar
            if kar_zarar > 0: kazanan += 1
            else: kaybeden += 1
        
        islem_gecmisi.append(cuzdan)
        tahmin_fiyatlar.append(hedef_fiyat)

    # --- GRAFİK ---
    print(f"💰 Net Bakiye: ${cuzdan - 1000:.2f}")
    
    plt.style.use('dark_background')
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    
    # Fiyat Grafiği
    # Son 100 günü göster
    ax1.plot(tarihler[-100:], gercek_fiyatlar[-100:], label='Gerçek', color='white')
    ax1.plot(tarihler[-100:], tahmin_fiyatlar[-100:], label='Model (Delta)', color='cyan', linestyle='--')
    ax1.set_title('Gerçek vs Model (Kopyasız Tahmin)')
    ax1.legend()
    
    # Cüzdan
    ax2.plot(islem_gecmisi, color='green' if cuzdan > 1000 else 'red')
    ax2.set_title('Cüzdan Bakiyesi')
    
    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    backtest_baslat()