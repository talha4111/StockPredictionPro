import numpy as np
import pandas as pd
from tarayici import veri_getir_dortlu
from ai_core import BeyinMotoru
import os
import json

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# Ayarları Yükle
try:
    with open('ayar.json', 'r', encoding='utf-8') as f: 
        AYAR = json.load(f)
        PORTFOY = AYAR["portfoy"]
        REF = AYAR["referans_varlik"]
except:
    print("❌ HATA: ayar.json okunamadı!")
    exit()

def model_egit(hedef_coin):
    print(f"\n🚀 {hedef_coin} İÇİN DİNAMİK EĞİTİM BAŞLIYOR...")
    
    # 1. Veriyi Çek
    df = veri_getir_dortlu(hedef_coin, REF)
    if df is None: return
    
    # 2. Motoru Kullan (XGBoost - Kripto Optimize: 50 Ağaç / 3 Derinlik)
    beyin = BeyinMotoru(n_estimators=50, max_depth=3)
    beyin.model_egit(hedef_coin, df, is_crypto=True)

if __name__ == "__main__":
    print(f"📋 EĞİTİLECEK PORTFÖY: {PORTFOY}")
    for coin in PORTFOY:
        model_egit(coin)
    print("\n🎉 TÜM DONANMA DİNAMİK OLARAK EĞİTİLDİ!")