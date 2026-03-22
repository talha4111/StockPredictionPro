import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import joblib
from tarayici import veri_getir_dortlu
import json
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

try:
    with open('ayar.json', 'r') as f: AYAR = json.load(f)
    PORTFOY = AYAR["portfoy"]
    REF = AYAR["referans_varlik"]
except: exit()

def classification_backtest():
    fig, axes = plt.subplots(len(PORTFOY), 1, figsize=(14, 4 * len(PORTFOY)))
    if len(PORTFOY) == 1: axes = [axes]
    
    fig.suptitle('🚀 Donanma Modu - Olasılık ve Yön Analizi (Sınıflandırma)', fontsize=16)

    for idx, hedef_coin in enumerate(PORTFOY):
        try:
            safe_name = hedef_coin.replace('/', '-')
            model = joblib.load(f'beyin_{safe_name}.pkl')
            df = veri_getir_dortlu(hedef_coin, REF)
            
            features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']
            
            eksikler = [f for f in features if f not in df.columns]
            if eksikler:
                print(f"❌ {hedef_coin} Eksik Veri: {14-len(eksikler)}/14 (İndikatörler oluşmadı, atlanıyor)")
                continue
                
            # Test için son 100 satırı doğrudan alıyoruz
            test_X = df[features].values[-100:-1]
            test_y_ham = df['Hedef_Ret'].values[-99:]
            
            y_gercek_yon = [1 if val > 0 else 0 for val in test_y_ham]
            
            olasiliklar_tum = model.predict_proba(test_X)
            olasiliklar = [p[1] for p in olasiliklar_tum] # 1 (Yükseliş) olma olasılığı
            
            # Başarı hesaplama (Olasılık 0.5'ten büyükse Yükseliş tahmini say)
            dogru_tahmin = sum(1 for i in range(len(y_gercek_yon)) if (olasiliklar[i] > 0.5 and y_gercek_yon[i] == 1) or (olasiliklar[i] < 0.5 and y_gercek_yon[i] == 0))
            basari = (dogru_tahmin / len(y_gercek_yon)) * 100
            
            # Grafiği Çiz (Arka Plan Gölgelendirmesi + Tahmin Çizgisi)
            axes[idx].fill_between(range(len(y_gercek_yon)), 0, 1, where=(np.array(y_gercek_yon)==1), color='green', alpha=0.15, label='Gerçek Yükseliş')
            axes[idx].fill_between(range(len(y_gercek_yon)), 0, 1, where=(np.array(y_gercek_yon)==0), color='red', alpha=0.15, label='Gerçek Düşüş')
            axes[idx].plot(olasiliklar, label='Modelin Yükseliş İhtimali', color='blue', linestyle='-', linewidth=1.5)
            axes[idx].axhline(y=0.5, color='red', linestyle='--', alpha=0.5, label='Kararsızlık Sınırı') # 0.5 Sınırı
            axes[idx].axhline(y=0.7, color='green', linestyle=':', alpha=0.5, label='LONG Sinyal Sınırı') # %70 Sınırı
            axes[idx].axhline(y=0.3, color='orange', linestyle=':', alpha=0.5, label='SHORT Sinyal Sınırı') # %30 Sınırı
            
            axes[idx].set_title(f"{hedef_coin} | İsabet Oranı: %{basari:.1f}")
            axes[idx].set_yticks([0, 0.3, 0.5, 0.7, 1.0])
            axes[idx].legend(loc='upper right')
            axes[idx].grid(True, alpha=0.2)
            
        except Exception as e:
            print(f"❌ {hedef_coin} için hata: {e}")

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.show()

if __name__ == "__main__":
    classification_backtest()