"""
BAGIMSIZ DEBUG ARACI: XGBoost AI Skorlarini Dogrudan Goster
Commander'dan bagimsiz calisir. Direkt terminalde sonuclari gosterir.
"""
import sys, os
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

sys.stdout.write(">>> Debug araci baslatiliyor...\n")
sys.stdout.flush()

import json
import time

# ayar.json oku
with open('ayar.json', 'r', encoding='utf-8') as f:
    AYAR = json.load(f)
REF = AYAR["referans_varlik"]
RISK_AYAR = AYAR["risk_yonetimi"]

sys.stdout.write(">>> Ayarlar yuklendi.\n")
sys.stdout.flush()

import ccxt
import numpy as np
import pandas as pd
from ai_core import BeyinMotoru
from tarayici import veri_getir_dortlu

sys.stdout.write(">>> Kutuphaneler yuklendi.\n")
sys.stdout.flush()

# Public Futures API
scout = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future', 'adjustForTimeDifference': True}})

# Spot API (veri cekme icin)
spot = ccxt.binance({'enableRateLimit': True, 'options': {'adjustForTimeDifference': True}})
try:
    spot.load_markets()
    SPOT = set(spot.symbols)
except:
    SPOT = set()

sys.stdout.write(f">>> Spot piyasada {len(SPOT)} sembol. Ticker cekiliyor...\n")
sys.stdout.flush()

# En sicak 20 coini bul
tikler = scout.fetch_tickers()
adaylar = []
for sembol, veri in tikler.items():
    if '/USDT' not in sembol: continue
    hacim = float(veri.get('quoteVolume') or 0)
    degisim = abs(float(veri.get('percentage') or 0))
    if hacim > 15_000_000:
        tsym = sembol.replace(':USDT', '')
        if SPOT and tsym not in SPOT: continue
        adaylar.append({'sembol': tsym, 'hacim': hacim, 'degisim': degisim})

adaylar.sort(key=lambda x: x['degisim'], reverse=True)
hedefler = [x['sembol'] for x in adaylar[:20]]

sys.stdout.write(f"\n>>> {len(adaylar)} aday bulundu, en sicak 20 coin analiz edilecek.\n")
sys.stdout.flush()

# Beyin motoru
beyin = BeyinMotoru()

# Her coin icin skor hesapla
sonuclar = []
features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']

for i, coin in enumerate(hedefler, 1):
    sys.stdout.write(f"  [{i}/20] {coin} analiz ediliyor...\n")
    sys.stdout.flush()
    
    try:
        df = veri_getir_dortlu(coin, REF)
        if df is None or df.empty:
            sys.stdout.write(f"    -> VERI YOK (df bos)\n")
            sys.stdout.flush()
            continue
        
        eksik = [f for f in features if f not in df.columns]
        if eksik:
            sys.stdout.write(f"    -> EKSIK FEATURE: {eksik[:3]}...\n")
            sys.stdout.flush()
            continue
        
        tahmin = beyin.tahmin_et(coin, df, is_crypto=True)
        if tahmin is None:
            beyin.model_egit(coin, df, is_crypto=True)
            tahmin = beyin.tahmin_et(coin, df, is_crypto=True)
        
        if tahmin is None:
            sys.stdout.write(f"    -> MODEL BASARISIZ\n")
            sys.stdout.flush()
            continue
        
        guncel = float(df['Hedef_Close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1])
        volat = (atr / guncel) * 100
        esik = min(0.65, max(0.55, 0.55 + (volat * 0.02)))
        
        if tahmin > esik:
            yon = "YUKSELIS"
            skor = tahmin * 100
        elif tahmin < (1.0 - esik):
            yon = "DUSUS"
            skor = (1.0 - tahmin) * 100
        else:
            yon = "NOTR"
            skor = max(tahmin, 1.0 - tahmin) * 100
        
        sonuclar.append({
            'coin': coin, 'ham_tahmin': tahmin, 'skor': skor,
            'esik': esik * 100, 'yon': yon, 'fiyat': guncel, 'volat': volat
        })
        
        durum = "ESIK USTU" if skor >= esik * 100 else "YETERSIZ"
        sys.stdout.write(f"    -> Skor: %{skor:.1f} | Esik: %{esik*100:.1f} | Yon: {yon} | {durum}\n")
        sys.stdout.flush()
        
    except Exception as e:
        sys.stdout.write(f"    -> HATA: {e}\n")
        sys.stdout.flush()
    
    time.sleep(1)

# SONUC TABLOSU
sys.stdout.write("\n" + "="*70 + "\n")
sys.stdout.write("  DEBUG RAPORU: XGBoost AI Tahmin Skorlari (En Yuksekten En Dusuge)\n")
sys.stdout.write("="*70 + "\n")

if sonuclar:
    sonuclar.sort(key=lambda x: x['skor'], reverse=True)
    sys.stdout.write(f"{'SIRA':<5} {'COIN':<14} {'SKOR':<10} {'ESIK':<10} {'YON':<10} {'DURUM':<12}\n")
    sys.stdout.write("-"*70 + "\n")
    
    for i, s in enumerate(sonuclar, 1):
        durum = "GIRIS UYGUN" if s['skor'] >= s['esik'] else "YETERSIZ"
        sys.stdout.write(f"  {i:<3} {s['coin']:<14} %{s['skor']:<8.1f} %{s['esik']:<8.1f} {s['yon']:<10} {durum}\n")
    
    top = sonuclar[0]
    sys.stdout.write("\n" + "-"*70 + "\n")
    if top['skor'] < top['esik']:
        sys.stdout.write(f"  SONUC: Sinyal yetersiz! En yuksek skor %{top['skor']:.1f} (Gereken: %{top['esik']:.1f})\n")
    else:
        gecenler = [s for s in sonuclar if s['skor'] >= s['esik']]
        sys.stdout.write(f"  SONUC: {len(gecenler)} coin esigi gecti! En guclu: {gecenler[0]['coin']} (%{gecenler[0]['skor']:.1f})\n")
else:
    sys.stdout.write("  HICBIR COIN ICIN TAHMIN YAPILAMADI!\n")

sys.stdout.write("="*70 + "\n")
sys.stdout.flush()
