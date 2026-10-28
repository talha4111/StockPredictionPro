import yfinance as yf
import pandas as pd
import numpy as np
import time
import sys
import os
from contextlib import contextmanager
from ai_core import BeyinMotoru
from stock_engine import hisse_verisi_getir
import warnings

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

hisseler = ['THYAO.IS', 'EREGL.IS', 'ASELS.IS', 'TUPRS.IS']
test_gunu = 30
baslangic_kasa = 10000.0

print("="*60)
print(f"🚀 BIST ADIM ADIM BACKTEST BAŞLIYOR (Son {test_gunu} Gün)")
print(f"📉 Hisseler: {', '.join(hisseler)}")
print("="*60)

toplam_islem = 0
basarili_islem = 0
toplam_pnl = 0.0

kasa_bakiye = baslangic_kasa

for hisse in hisseler:
    print(f"\n[⏳] {hisse} verileri indiriliyor ve simülasyon başlatılıyor...")
    # Veriyi geniş çekiyoruz çünkü teknik indikatörler ve model eğitimi geriye dönük yüklü veri ister
    df_tam = hisse_verisi_getir(hisse, periyot="1y", interval="1d")
    
    if df_tam is None or len(df_tam) < test_gunu + 120:
        print(f"  [X] Yeterli veri yok ({len(df_tam) if df_tam is not None else 0} gün), atlanıyor.")
        continue

    aktif_pozisyon = None
    
    end_idx = len(df_tam)
    start_idx = end_idx - test_gunu
    
    beyin = BeyinMotoru()
    
    for i in range(start_idx, end_idx):
        tarih = df_tam.index[i].strftime('%Y-%m-%d')
        
        # O güne kadarki veri (Gelecek sızıntısını engelleyen dilimleme)
        df_sim = df_tam.iloc[:i+1]
        
        # 1. Açık pozisyon varsa, o gün TP/SL kontrolü yap
        if aktif_pozisyon is not None:
            # Günlük en yüksek ve en düşük fiyatlar üzerinden stop/tp kontrolü
            high = float(df_sim['High'].iloc[-1])
            low = float(df_sim['Low'].iloc[-1])
            kapanma_fiyati = 0
            
            p = aktif_pozisyon
            if p["yon"] == "LONG":
                if low <= p["sl"]: kapanma_fiyati = p["sl"]
                elif high >= p["tp"]: kapanma_fiyati = p["tp"]
            elif p["yon"] == "SHORT":
                if high >= p["sl"]: kapanma_fiyati = p["sl"]
                elif low <= p["tp"]: kapanma_fiyati = p["tp"]
                
            if kapanma_fiyati != 0:
                # İşlem sonlandı
                brut_kz = (kapanma_fiyati - p["giris_fiyati"]) * p["miktar"]
                kar_zarar = brut_kz if p["yon"] == "LONG" else -brut_kz
                
                kasa_bakiye += kar_zarar
                toplam_pnl += kar_zarar
                toplam_islem += 1
                if kar_zarar > 0:
                    basarili_islem += 1
                
                durum = "TP Alındı (KÂR) 🟢" if kar_zarar > 0 else "SL Vuruldu (ZARAR) 🔴"
                print(f"  [{tarih}] SONUÇ: {durum} | K/Z: {kar_zarar:+.2f} ₺")
                aktif_pozisyon = None
                
            continue # Pozisyon varsa kapanana kadar bekle
            
        # 2. Pozisyon yoksa, o güne kadarki verilerle modeli eğit ve tahmin iste
        try:
            # Yapay Zeka her gün uyanıp o güne kadar olan grafiği inceliyor (Eğitim sırasındaki logları gizledik)
            with suppress_stdout():
                beyin.model_egit(hisse, df_sim, is_crypto=False)
                tahmin_olasilik = beyin.tahmin_et(hisse, df_sim, is_crypto=False)
        except Exception as e:
            continue
            
        if tahmin_olasilik is None:
            continue
            
        yon = "NÖTR"
        if tahmin_olasilik > 0.51:
            yon = "LONG"
        elif tahmin_olasilik < 0.49:
            yon = "SHORT"
            
        if yon != "NÖTR":
            anlik_fiyat = float(df_sim['Close'].iloc[-1])
            atr = float(df_sim['ATR'].iloc[-1]) if 'ATR' in df_sim.columns else (anlik_fiyat * 0.02)
            
            sl_mesafe = atr * 1.20 # Borsa Hisse Stop Dinamiği
            tp_mesafe = atr * 1.50 # Borsa Hisse Kar Dinamiği
            
            tp_fiyat = 0
            sl_fiyat = 0
            
            if yon == "LONG":
                tp_fiyat = anlik_fiyat + tp_mesafe
                sl_fiyat = anlik_fiyat - sl_mesafe
            else:
                tp_fiyat = anlik_fiyat - tp_mesafe
                sl_fiyat = anlik_fiyat + sl_mesafe
                
            # Sermayenin %10'unu kullanarak işlem aç
            islem_boyutu = kasa_bakiye * 0.10
            miktar = islem_boyutu / anlik_fiyat
            
            aktif_pozisyon = {
                "yon": yon,
                "giris_fiyati": anlik_fiyat,
                "miktar": miktar,
                "tp": tp_fiyat,
                "sl": sl_fiyat,
                "acilis_tarih": tarih
            }
            print(f"  [{tarih}] 🎯 YENİ SİNYAL: {yon} | Fiyat: {anlik_fiyat:.2f} ₺ | Puan: %{tahmin_olasilik*100:.1f}")

    # Simülasyon bittiğinde hissenin hala açık pozisyonu kalmışsa Onu en son günün fiyatından kapat (Mark to Market)
    if aktif_pozisyon is not None:
        p = aktif_pozisyon
        son_fiyat = float(df_tam['Close'].iloc[-1])
        brut_kz = (son_fiyat - p["giris_fiyati"]) * p["miktar"]
        kar_zarar = brut_kz if p["yon"] == "LONG" else -brut_kz
        kasa_bakiye += kar_zarar
        toplam_pnl += kar_zarar
        toplam_islem += 1
        if kar_zarar > 0: basarili_islem += 1
        durum = "Süre Bitti (KÂR) 🟢" if kar_zarar > 0 else "Süre Bitti (ZARAR) 🔴"
        print(f"  [Simülasyon Sonu] SONUÇ: Geçerlilik Sonu Kapanışı - {durum} | K/Z: {kar_zarar:+.2f} ₺")

print("\n" + "="*60)
print("📊 BIST ADIM ADIM BACKTEST RAPORU")
print("="*60)
print(f"🔸 Toplam İşlem Sayısı  : {toplam_islem}")
basari_orani = (basarili_islem / toplam_islem * 100) if toplam_islem > 0 else 0
print(f"🔸 Başarı Oranı (%)     : %{basari_orani:.2f}")
print("-" * 60)
print(f"💵 Başlangıç Kasası     : {baslangic_kasa:,.2f} ₺")
print(f"💰 Toplam Sanal K/Z     : {toplam_pnl:+,.2f} ₺")
print(f"💳 Süreç Sonu Kasa      : {kasa_bakiye:,.2f} ₺")
print("="*60)
