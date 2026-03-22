import yfinance as yf
from datetime import datetime
import pytz
import time
import pandas as pd
import pandas_ta as ta
import numpy as np
from ai_core import BeyinMotoru

# --- AYARLAR ---
HISSE_LISTESI = ['NVDA', 'AAPL', 'TSLA', 'MSFT', 'THYAO.IS', 'EREGL.IS', 'TUPRS.IS', 'ASELS.IS', 'SASA.IS']
ZAMAN_DILIMI = pytz.timezone('Europe/Istanbul') # TSİ (Türkiye Saati)

def piyasa_acik_mi():
    """
    Çoklu piyasa (BIST, Euro, ABD) taraması yapıldığı için genel iş günleri kontrol edilir.
    """
    suan = datetime.now(ZAMAN_DILIMI)
    if suan.weekday() >= 5:
        return False, "Hafta Sonu Kapalı"
    return True, "Çoklu Piyasa Taraması Aktif"

def hisse_verisi_getir(sembol, periyot="1y", interval="1d"):
    """
    Belirtilen hisse için yfinance üzerinden geçmiş verileri çeker ve indikatörleri hesaplar.
    """
    try:
        ticker = yf.Ticker(sembol)
        df = ticker.history(period=periyot, interval=interval)
        if df.empty:
            return None
            
        # --- İndikatör Hesaplamaları (Kripto yapısına uyum) ---
        df['RSI'] = df.ta.rsi(close='Close', length=14)
        
        macd = df.ta.macd(close='Close', fast=12, slow=26, signal=9)
        if macd is not None:
            df['MACD'] = macd.iloc[:, 0]
        else:
            df['MACD'] = 0.0
            
        df['ATR'] = df.ta.atr(high='High', low='Low', close='Close', length=14)
            
        df['OBV'] = df.ta.obv(close=df['Close'], volume=df['Volume'])
        
        bbands = df.ta.bbands(close=df['Close'], length=20)
        if bbands is not None:
            df['BB_Width'] = bbands.iloc[:, 3] 
        else:
            df['BB_Width'] = 0.0
            
        df['MFI'] = df.ta.mfi(high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume'], length=14)
        
        vwap = df.ta.vwap(high=df['High'], low=df['Low'], close=df['Close'], volume=df['Volume'])
        df['VWAP'] = vwap if vwap is not None else df['Close']
        df['VP_Sapma'] = (df['Close'] - df['VWAP']) / df['VWAP']
        
        # Günlük Kapanış (Momentum) Filtresi İçin Önceki Günün Verisini İndir
        df_daily = ticker.history(period="5d", interval="1d")
        if not df_daily.empty and len(df_daily) >= 2:
            df['Onceki_Gun_Kapanis'] = df_daily['Close'].iloc[-2]
        else:
            df['Onceki_Gun_Kapanis'] = df['Close'].iloc[0] # Yedek değer

        # Kripto tarafındaki özellik (feature) isimleriyle tam uyum sağla ve eksiklere varsayılan değer ata
        if 'Hedef_Ret' not in df.columns:
            df['Hedef_Ret'] = df['Close'].pct_change()
        if 'Ref_Ret' not in df.columns:
            df['Ref_Ret'] = 0.0
        if 'Vol_Ret' not in df.columns:
            df['Vol_Ret'] = df['Volume'].pct_change() if 'Volume' in df.columns else 0.0
        if 'Korelasyon' not in df.columns:
            df['Korelasyon'] = 0.0
            
        # Makro İndikatörleri ve Siyasi Filtreleri Canlıda Tanımlı Hale Getir!
        if 'Kriz' not in df.columns:
            df['Kriz'] = np.where(df['Hedef_Ret'] < -0.05, 1.0, 0.0)
        if 'Haber_Duygu_Puani' not in df.columns:
            df['Haber_Duygu_Puani'] = 50.0 
        if 'Faiz_Orani' not in df.columns:
            df['Faiz_Orani'] = 50.0
        if 'Dolar_Kuru' not in df.columns:
            df['Dolar_Kuru'] = df['Close'] / 10.0

        gerekli_kolonlar = ['RSI', 'MACD', 'ATR', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Hedef_Ret', 'Vol_Ret', 'Ref_Ret', 'Korelasyon', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']
        for col in gerekli_kolonlar:
            if col not in df.columns:
                df[col] = 0.0

        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.fillna(0.0, inplace=True)
        return df
    except Exception as e:
        print(f"[X] Veri Cekme Hatasi ({sembol}): {e}")
        return None

def motor_baslat():
    print("[>] BORSA CEPHESI: 'SANAL KASA' TAKIBI BASLADI (PAPER TRADING)")
    print("-" * 50)
    
    import json
    
    try:
        with open("sanal_kasa_borsa.json", "r") as f:
            sanal_kasa_bakiye = float(json.load(f).get("bakiye", 10000.0))
    except:
        sanal_kasa_bakiye = 10000.0
        
    sanal_pozisyonlar = {}
    
    def kasa_kaydet():
        try:
            with open("sanal_kasa_borsa.json", "w") as fd:
                json.dump({"bakiye": sanal_kasa_bakiye}, fd)
        except: pass
    
    while True:
        acik_mi, piyasa_mesaj = piyasa_acik_mi()
        suan_str = datetime.now(ZAMAN_DILIMI).strftime('%H:%M:%S')
        print(f"\n[+] GÜNCEL BORSA KASASI: {sanal_kasa_bakiye:,.2f}$")

        if not acik_mi:
            print(f"[{suan_str}] [!] {piyasa_mesaj}. ACILIS BEKLENIYOR...")

        beyin = BeyinMotoru()

        for hisse in HISSE_LISTESI:
            print(f"  [>] {hisse:<8} | Kasa: {sanal_kasa_bakiye:,.2f} USD | Analiz Ediliyor...")
            df = hisse_verisi_getir(hisse, periyot="5d", interval="1m")
            if df is not None:
                anlik_fiyat = df['Close'].iloc[-1]
                onceki_gun = df['Onceki_Gun_Kapanis'].iloc[-1]
                hacim = int(df['Volume'].iloc[-1])
                rsi = float(df['RSI'].iloc[-1]) if 'RSI' in df.columns else 50.0
                
                # --- Basit Momentum Filtresi (Hisse özel) ---
                if anlik_fiyat < onceki_gun:
                    momentum = "ZAYIF"
                else:
                    momentum = "GUCLU"
                    
                # Model Tahmini Al
                tahmin_olasiligi = beyin.tahmin_et(hisse, df, is_crypto=False)
                if tahmin_olasiligi is None:
                    # Model yoksa önce bir kere eğit
                    print(f"  [>] {hisse:<5} icin model henuz egitilmemis. Hemen egitiliyor...")
                    beyin.model_egit(hisse, df, is_crypto=False)
                    tahmin_olasiligi = beyin.tahmin_et(hisse, df, is_crypto=False)
                
                # --- Makro-Ekonomik Sinyal Çarpanı (%20 Etki Artışı) ---
                if tahmin_olasiligi is not None:
                    kriz_durumu = df['Kriz'].iloc[-1]
                    duygu_puani = df['Haber_Duygu_Puani'].iloc[-1]
                    faiz_orani = df['Faiz_Orani'].iloc[-1]
                    
                    # Eğer kriz varsa DÜŞÜŞ ihtimalini %20 (0.10 puan) artır
                    if kriz_durumu == 1.0 or faiz_orani > 45.0 or duygu_puani < 30.0:
                        tahmin_olasiligi -= 0.10 # Short lehine bük
                    # Haberler çok iyiyse YÜKSELİŞ ihtimalini %20 (0.10 puan) artır (0.50 nötr bazdır)
                    elif duygu_puani > 70.0:
                        tahmin_olasiligi += 0.10 # Long lehine bük
                        
                # --- 1. Agresif Sabit Eşik (%52 Threshold) --- 
                atr = float(df['ATR'].iloc[-1]) if 'ATR' in df.columns else (anlik_fiyat * 0.02)
                dinamik_esik = 0.52
                
                # Sinyal Yönü Çıkar
                yon = "Notr"
                if tahmin_olasiligi is not None:
                    if tahmin_olasiligi > dinamik_esik:
                        yon = "LONG"
                    elif tahmin_olasiligi < (1.0 - dinamik_esik):
                        yon = "SHORT"
                
                # Scalping Modu (Kısa Vade Al-Sat TP/SL)
                sl_mesafe = atr * 0.60 
                tp_mesafe = atr * 0.75
                
                hedef = 0.0
                zayiat = 0.0
                if "LONG" in yon:
                    hedef = anlik_fiyat + tp_mesafe
                    zayiat = anlik_fiyat - sl_mesafe
                elif "SHORT" in yon:
                    hedef = anlik_fiyat - tp_mesafe
                    zayiat = anlik_fiyat + sl_mesafe
                if "Notr" not in yon:
                    atr_dakika = max(0.001, atr / 390.0) # Borsa 390 dk açık
                    mesafe = abs(hedef - anlik_fiyat)
                    sure_dk = int(mesafe / atr_dakika)
                    sure_metni = f"Beklenen süre: {int(sure_dk*0.8)}-{int(sure_dk*1.2)} dk"

                    print(f"  [>] {hisse:<5} | Fiyat: {anlik_fiyat:>8.2f}$ | RSI: {rsi:.1f} | AI Yon: {yon} | Hedef: ~{hedef:.2f}$ ({sure_metni}) | Stop: ~{zayiat:.2f}$")
                    
                    # Eğer pozisyon yoksa SANAL IŞLEM AC
                    if hisse not in sanal_pozisyonlar:
                        # --- 2. Kelly Kriteri İle Kasa Yönetimi (Fractional Kelly) ---
                        rr_orani = (hedef - anlik_fiyat) / (anlik_fiyat - zayiat) if yon == "LONG" and (anlik_fiyat - zayiat) != 0 else 0
                        if yon == "SHORT" and (zayiat - anlik_fiyat) != 0:
                            rr_orani = (anlik_fiyat - hedef) / (zayiat - anlik_fiyat)
                            
                        # b: Ödül/Risk, p: XGBoost Kazanma Skoru, q: Kaybetme
                        p_kelly = tahmin_olasiligi if yon == "LONG" else (1.0 - tahmin_olasiligi)
                        q_kelly = 1.0 - p_kelly
                        
                        kelly_orani = 0.0
                        if rr_orani > 0:
                            kelly_orani = (p_kelly * rr_orani - q_kelly) / rr_orani
                            
                        # Çeyrek Kelly - Alt limit %5, Üst limit %20'ye (0.20) yükseltildi (Agresif Paper Trading)
                        fractional_kelly = max(0.05, min(0.20, kelly_orani * 0.25))
                        islem_boyutu = sanal_kasa_bakiye * fractional_kelly
                        
                        # --- 5x Sanal Kaldıraç Simülasyonu ---
                        kaldirac_etkisi = 5.0
                        islem_hacmi = islem_boyutu * kaldirac_etkisi
                        
                        if islem_boyutu > 0:
                            miktar = islem_hacmi / anlik_fiyat
                            sanal_pozisyonlar[hisse] = {
                                "yon": yon, "giris": anlik_fiyat, "miktar": miktar, 
                                "hedef": hedef, "zayiat": zayiat
                            }
                            print(f"      [SANAL İŞLEM] {hisse} Alındı - Kasa: %{fractional_kelly*100:.1f} x 5x Kaldıraç - Miktar: {miktar:.2f} Adet")
                else:
                    pass # 'Analiz Ediliyor' logu yukarıda verildi, 'Bekleniyor' yerine sadece sonuç beklenir.
                
                # Sanal Kasa TP/SL Kontrolü
                if hisse in sanal_pozisyonlar:
                    poz = sanal_pozisyonlar[hisse]
                    poz["guncel"] = anlik_fiyat # Gunceli kaydet
                    kapanma_fiyati = 0
                    if poz["yon"] == "LONG":
                        if anlik_fiyat >= poz["hedef"]: kapanma_fiyati = poz["hedef"]
                        elif anlik_fiyat <= poz["zayiat"]: kapanma_fiyati = poz["zayiat"]
                    elif poz["yon"] == "SHORT":
                        if anlik_fiyat <= poz["hedef"]: kapanma_fiyati = poz["hedef"]
                        elif anlik_fiyat >= poz["zayiat"]: kapanma_fiyati = poz["zayiat"]

                    if kapanma_fiyati > 0:
                        kar_z_brut = (kapanma_fiyati - poz["giris"]) * poz["miktar"]
                        kar_zarar = kar_z_brut if poz["yon"] == "LONG" else -kar_z_brut
                        sanal_kasa_bakiye += kar_zarar
                        kasa_kaydet()
                        durum_str = "KARLA KAPANDI [TPSL]" if kar_zarar > 0 else "STOP OLDU [TPSL]"
                        print(f"      {durum_str} [{hisse}] Yön: {poz['yon']} | K/Z: {kar_zarar:+.2f}$ | Yeni Kasa: {sanal_kasa_bakiye:.2f}$")
                        del sanal_pozisyonlar[hisse]

            else:
                print(f"  [!] {hisse:<5} | Veri alinamadi veya hesaplanamadi!")
        
        print("\n  ==== ÖZET: SANAL KASA (PAPER TRADING) ====")
        print(f"  💰 GÜNCEL KASA: {sanal_kasa_bakiye:,.2f} USD")
        if sanal_pozisyonlar:
            print("  " + "-"*65)
            print(f"  {'SEMBOL':<8} | {'YÖN':<5} | {'GİRİŞ':<8} | {'GÜNCEL':<8} | {'NET PNL':<9} | {'İLERLEME':<8}")
            print("  " + "-"*65)
            for sym, p in sanal_pozisyonlar.items():
                guncel_fiyati = p.get('guncel', p['giris'])
                
                kar_z_brut = (guncel_fiyati - p["giris"]) * p["miktar"]
                pnl = kar_z_brut if p["yon"] == "LONG" else -kar_z_brut
                pnl_str = f"+{pnl:.2f}$" if pnl > 0 else f"{pnl:.2f}$"
                
                if p['yon'] == 'LONG':
                    raw_prog = (guncel_fiyati - p['giris']) / (p['hedef'] - p['giris']) * 100 if (p['hedef'] - p['giris']) != 0 else 0
                else:
                    raw_prog = (p['giris'] - guncel_fiyati) / (p['giris'] - p['hedef']) * 100 if (p['giris'] - p['hedef']) != 0 else 0
                
                print(f"  {sym:<8} | {p['yon']:<5} | {p['giris']:<7.2f}$| {guncel_fiyati:<7.2f}$| {pnl_str:<9} | %{raw_prog:.1f}")
            print("  " + "-"*65)
        else:
            print("  [Henüz Açık Bir Sanal İşlem Yok]")
        print("\n--------------------\n")
        time.sleep(60) # Taramalar arası 60 saniye bekle

if __name__ == "__main__":
    motor_baslat()
