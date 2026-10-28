import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import json
from datetime import datetime

AYAR_DOSYASI = 'ayar.json'
LOG_DOSYASI = 'sistem_loglari.txt'

def log_tut(mesaj):
    zaman = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_DOSYASI, "a", encoding="utf-8") as f:
        f.write(f"[{zaman}] {mesaj}\n")

def ayarlari_guncelle(yeni_sl, yeni_tp, en_iyi_skor, win_rate):
    try:
        with open(AYAR_DOSYASI, 'r', encoding='utf-8') as f:
            mevcut = json.load(f)
        
        mevcut["risk_yonetimi"]["sl_atr_carpani"] = float(yeni_sl)
        mevcut["risk_yonetimi"]["tp_atr_carpani"] = float(yeni_tp)
        
        with open(AYAR_DOSYASI, 'w', encoding='utf-8') as f:
            json.dump(mevcut, f, indent=4, ensure_ascii=False)
            
        print(f"\n✅ SİSTEM PRO MODA GÜNCELLENDİ!")
        print(f"   Yeni Strateji: SL {yeni_sl} | TP {yeni_tp}")
        print(f"   Beklenen Başarı Oranı: %{win_rate:.2f}")
        log_tut(f"PRO OPTİMİZASYON: SL({yeni_sl}), TP({yeni_tp}), WinRate: %{win_rate:.2f}")

    except Exception as e:
        print(f"❌ Hata: {e}")

def en_iyi_ayari_bul():
    try:
        with open(AYAR_DOSYASI, 'r') as f: sembol = json.load(f)["hedef_varlik"]
    except: sembol = "SOL-USD"

    print(f"\n🏛️ PRO FON YÖNETİCİ OPTİMİZASYONU BAŞLADI | {sembol}")
    
    # --- 1. VERİ HAZIRLIĞI ---
    try:
        df = yf.download(sembol, period="1y", interval="1d", progress=False)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.droplevel(1)
        df.rename(columns={'Close': 'close', 'High': 'high', 'Low': 'low', 'Open': 'open'}, inplace=True)
        df['ATR'] = df.ta.atr(length=14)
        df['RSI'] = df.ta.rsi(length=14)
        df.dropna(inplace=True)
    except: return

    # --- 2. PARAMETRE UZAYI (Tutarlılık Odaklı Dar Aralık) ---
    # Profesyonel modda SL ve TP birbirine daha yakındır (Scalp/Swing dengesi)
    sl_secenekleri = [0.8, 1.0, 1.2] 
    tp_secenekleri = [0.8, 1.0, 1.2, 1.5] # 75$ hedeflerini eleyen dar makas

    en_iyi_skor = -99999
    en_iyi_ayar = None
    final_win_rate = 0
    
    print("-" * 65)
    print(f"{'SL':<6} | {'TP':<6} | {'WinRate':<8} | {'Net R':<10} | {'Pro Skor':<10}")
    print("-" * 65)

    # --- 3. SİMÜLASYON (Probabilistik Yaklaşım) ---
    for sl in sl_secenekleri:
        for tp in tp_secenekleri:
            toplam_puan = 0
            kazanan, toplam_islem = 0, 0
            rr_orani = tp / sl

            for i in range(len(df) - 15):
                rsi = df['RSI'].iloc[i]
                if rsi < 35 or rsi > 65: # Hem Long hem Short test et
                    giris = df['close'].iloc[i]
                    atr = df['ATR'].iloc[i]
                    yon = "LONG" if rsi < 35 else "SHORT"
                    
                    h_tp = giris + (atr * tp) if yon == "LONG" else giris - (atr * tp)
                    h_sl = giris - (atr * sl) if yon == "LONG" else giris + (atr * sl)
                    
                    for j in range(1, 10):
                        low, high = df['low'].iloc[i+j], df['high'].iloc[i+j]
                        if (yon == "LONG" and low <= h_sl) or (yon == "SHORT" and high >= h_sl):
                            toplam_puan -= 1.0
                            toplam_islem += 1
                            break
                        elif (yon == "LONG" and high >= h_tp) or (yon == "SHORT" and low <= h_tp):
                            toplam_puan += rr_orani
                            kazanan += 1
                            toplam_islem += 1
                            break
            
            if toplam_islem >= 10:
                win_rate = (kazanan / toplam_islem) * 100
                # PRO SKOR: Sadece kara değil, başarı oranına da bakar (Kelly Kriteri benzeri)
                pro_skor = toplam_puan * (win_rate / 100) 
                
                print(f"{sl:<6} | {tp:<6} | %{win_rate:<7.1f} | {toplam_puan:<10.2f} | {pro_skor:<10.2f}")
                
                if pro_skor > en_iyi_skor:
                    en_iyi_skor = pro_skor
                    en_iyi_ayar = (sl, tp)
                    final_win_rate = win_rate

    # --- 4. FİNAL ---
    if en_iyi_ayar:
        print("-" * 65)
        ayarlari_guncelle(en_iyi_ayar[0], en_iyi_ayar[1], en_iyi_skor, final_win_rate)
    else:
        print("❌ Kriterlere uygun stabil ayar bulunamadı.")

if __name__ == "__main__":
    en_iyi_ayari_bul()