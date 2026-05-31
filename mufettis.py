import pandas as pd
import sqlite3
import os
from datetime import datetime
import numpy as np

def gunluk_rapor_olustur():
    print("=" * 60)
    print("🔍 KAPTAN KRİPTO - GÜNLÜK HATA VE PERFORMANS RAPORU 🔍")
    print("=" * 60)
    print(f"Rapor Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    bugun_str = datetime.now().strftime('%Y-%m-%d')
    df_list = []

    csv_dosya = 'trade_history.csv'
    if os.path.exists(csv_dosya):
        try:
            df_csv = pd.read_csv(csv_dosya)
            if not df_csv.empty:
                df_list.append(df_csv)
        except Exception as e:
            print(f"[!] CSV Okuma Hatası: {e}")

    db_dosya = 'trading_bot.db'
    if os.path.exists(db_dosya):
        try:
            conn = sqlite3.connect(db_dosya)
            df_db = pd.read_sql_query("SELECT * FROM closed_trades", conn)
            conn.close()
            if not df_db.empty:
                if 'id' in df_db.columns:
                    df_db = df_db.drop(columns=['id'])
                df_list.append(df_db)
        except Exception as e:
            print(f"[!] SQLite Okuma Hatası: {e}")

    if not df_list:
        print("⚠️ Henüz hiçbir işlem verisi (CSV/DB) bulunamadı.")
        return

    df_all = pd.concat(df_list, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=['Tarih_Saat', 'Parite', 'Hesap_Tipi']).reset_index(drop=True)

    beklenen_kolonlar = ['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Net_PNL_USDT', 'PNL_Yuzde']
    for col in beklenen_kolonlar:
        if col not in df_all.columns:
            if col == 'Hesap_Tipi' and 'Islem_Yonu' in df_all.columns:
                df_all['Hesap_Tipi'] = np.where(df_all['Islem_Yonu'].isin(['LIVE', 'DEMO']), df_all['Islem_Yonu'], 'DEMO')
            else:
                print(f"Kritik kolon eksik: {col}")
                return

    df_all['Tarih_Saat'] = df_all['Tarih_Saat'].astype(str)
    df_bugun = df_all[df_all['Tarih_Saat'].str.startswith(bugun_str)].copy()

    if df_bugun.empty:
        print(f"📊 Bugün ({bugun_str}) için kayıtlı bir işlem bulunamadı.")
        return

    def analiz_yap(df, hesap_tipi):
        if df.empty:
            return
            
        print(f"--- {hesap_tipi.upper()} İŞLEMLERİ ---")
        toplam_islem = len(df)
        
        karlar_list = df[df['Net_PNL_USDT'] > 0]['Net_PNL_USDT']
        zararlar_list = df[df['Net_PNL_USDT'] <= 0]['Net_PNL_USDT']
        
        kazanan_islem = len(karlar_list)
        kaybeden_islem = len(zararlar_list)
        
        win_rate = (kazanan_islem / toplam_islem) if toplam_islem > 0 else 0.0
        loss_rate = 1.0 - win_rate
        
        avg_kar = karlar_list.mean() if kazanan_islem > 0 else 0.0
        avg_zarar = abs(zararlar_list.mean()) if kaybeden_islem > 0 else 0.0
        
        expectancy = (win_rate * avg_kar) - (loss_rate * avg_zarar)
        
        net_pnl = df['Net_PNL_USDT'].sum()

        tahmini_komisyon = 0
        for _, row in df.iterrows():
            pnl_usdt = abs(row['Net_PNL_USDT'])
            pnl_yuzde = abs(row['PNL_Yuzde'])
            if pnl_yuzde > 0:
                hacim = pnl_usdt / (pnl_yuzde / 100)
                hacim = min(hacim, 500.0) 
                islem_komisyonu = hacim * 0.0005 * 2
            else:
                islem_komisyonu = 0.075 
            tahmini_komisyon += islem_komisyonu

        print(f"Toplam İşlem Sayısı: {toplam_islem}")
        print(f"Win-Rate (Kazanma): %{win_rate*100:.1f} ({kazanan_islem} Kâr / {kaybeden_islem} Zarar)")
        print(f"Ortalama Kazanç: {avg_kar:.4f} USDT | Ortalama Kayıp: {avg_zarar:.4f} USDT")
        print(f"Net PNL (Gerçekleşen): {net_pnl:+.4f} USDT")
        print(f"Tahmini Ödenen Komisyon: {tahmini_komisyon:.4f} USDT")
        print(f"Borsaya Kaptırılan Komisyon Sonrası Tahmini Net Kâr/Zarar: {(net_pnl - tahmini_komisyon if hesap_tipi == 'LIVE' else net_pnl):+.4f} USDT")
        
        print(f"👉 Matematiksel Beklenti (Expectancy): {expectancy:+.4f} USDT")

        df = df.sort_values(by='Tarih_Saat')
        losing_streak_max = 0
        guncel_streak = 0
        for pnl in df['Net_PNL_USDT']:
            if pnl <= 0:
                guncel_streak += 1
                if guncel_streak > losing_streak_max: losing_streak_max = guncel_streak
            else:
                guncel_streak = 0
                
        if losing_streak_max >= 3:
            print(f"🩸 DİKKAT KANAMA TESPİT EDİLDİ: Arka arkaya {losing_streak_max} kere ZARAR edilen bir dizi (Losing Streak) var!")
        elif losing_streak_max > 0:
            print(f"🩹 Kanama Kontrolü: Güvenli. (Maksimum ardışık zarar: {losing_streak_max})")
        else:
            print(f"🛡️ Kanama Kontrolü: MÜKEMMEL! Hiç ardışık zarar yok.")
            
        if expectancy < 0:
            print("\n⚠️ UYARI: SİSTEM MATEMATİKSEL OLARAK KASA ERİTİYOR!")
            
        print("-" * 40)

    df_live = df_bugun[df_bugun['Hesap_Tipi'] == 'LIVE']
    df_demo = df_bugun[df_bugun['Hesap_Tipi'] != 'LIVE']

    analiz_yap(df_live, "LIVE")
    analiz_yap(df_demo, "DEMO")

    print("\n🔍 Müfettiş Sistem Sağlığı Denetimi 🔍")
    print("-" * 40)
    log_dosyasi = "bot_rapor.txt"
    if os.path.exists(log_dosyasi):
        try:
            with open(log_dosyasi, "r", encoding="utf-8", errors="ignore") as f:
                satirlar = f.readlines()
            
            # Sadece son 5000 satırı incele
            satirlar = satirlar[-5000:]
            hata_sayaci = {}
            for satir in satirlar:
                if "❌" in satir or "Exception" in satir or "Error" in satir or "Traceback" in satir or "Kapanış hatası" in satir or "KRİTİK HATA" in satir:
                    # Hatayı gruplamak için temizle
                    temiz_hata = satir.strip().replace('\n', '')[:120] 
                    hata_sayaci[temiz_hata] = hata_sayaci.get(temiz_hata, 0) + 1
            
            if hata_sayaci:
                print("⚠️ DİKKAT: Bot loglarında aşağıdaki SISTEM HATALARI tespit edildi (Son 5000 satır):")
                # En çok tekrar eden 5 hatayı göster
                for hata, count in sorted(hata_sayaci.items(), key=lambda x: x[1], reverse=True)[:5]:
                    print(f"  [{count} kez] -> {hata}")
            else:
                print("✅ Sistem Sağlığı Mükemmel. Son kayıtlarda teknik hata (Exception/❌) bulunamadı.")
        except Exception as e:
            print(f"Log dosyası incelenirken hata: {e}")
    else:
        print("ℹ️ 'bot_rapor.txt' bulunamadı, yazılımsal denetim atlandı.")

    print("\n🔍 Müfettiş denetimi tamamlandı.")
    print("=" * 60)
    
    # --- LLM ANALİST KANCASI (HOOK) ---
    import subprocess
    if os.path.exists('llm_analist.py'):
        print("\n[AI HOOK] Dijital Quant Analiste veri devrediliyor...")
        try:
            subprocess.run(["python", "llm_analist.py"])
        except Exception as e:
            print(f"⚠️ LLM Analist tetiklenemedi: {e}")

if __name__ == "__main__":
    gunluk_rapor_olustur()
