import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import time
from textblob import TextBlob

def get_sentiment_score(text):
    """Metin (Haber başlığı) için NLP duygu analizi yapar (-1.0 ile 1.0 arası)."""
    try:
        analiz = TextBlob(text)
        return analiz.sentiment.polarity
    except Exception:
        return 0.0

def run_makro_radar():
    print("\n🔍 MAKRO RADAR BAŞLATILIYOR... Sistematik Tarama Başlıyor.")
    print("----------------------------------------------------------------------")
    
    # 1. Aday Havuzu (Watchlist) - 40 Hisse
    hisse_havuzu = [
        # BIST 30 (Hacimli Kağıtlar)
        'THYAO.IS', 'EREGL.IS', 'TUPRS.IS', 'ASELS.IS', 'SASA.IS', 
        'BIMAS.IS', 'KCHOL.IS', 'SISE.IS', 'AKBNK.IS', 'YKBNK.IS',
        'GARAN.IS', 'SAHOL.IS', 'ISCTR.IS', 'ENKAI.IS', 'PGSUS.IS', 'FROTO.IS',
        # ABD (Endeks Devleri, S&P 500 ve Nasdaq)
        'AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'TSLA', 'BRK-B', 
        'UNH', 'JNJ', 'JPM', 'V', 'PG', 'MA', 'HD', 'CVX', 
        'ABBV', 'LLY', 'PEP', 'KO', 'MRK', 'AVGO', 'COST', 'XOM'
    ]
    
    print(f"[!] 1. Aşama - Teknik & Temel Matris (%80 Etki) Hesaplamaları Başladı. Hedef Havuz: {len(hisse_havuzu)} Hisse")
    sonuclar = []

    for idx, sembol in enumerate(hisse_havuzu):
        # Bilgi mesajı
        if idx % 5 == 0 and idx > 0:
            print(f"    ... {idx} hisse tarandı.")
            
        try:
            ticker = yf.Ticker(sembol)
            # Uzun Vade (3-6 Ay yatırım) için haftalık (1wk) veri indiriyoruz. 5 Yıllık veri.
            df = ticker.history(period="5y", interval="1wk")
            if df.empty or len(df) < 52:
                # 1 yıllık veri (52 hafta) şart
                continue

            info = ticker.fast_info
            
            # Eski info formatı yavaş olduğu için önce basic dataları alıyoruz.
            # Fundamental verileri ayrı çağırıyoruz (P/E vb. için)
            temel_info = ticker.info
            sektor = temel_info.get('sector', 'Bilinmiyor')

            # --- 2. FİNANS SEKTÖRÜ İZOLASYONU ---
            if 'financial' in sektor.lower() or 'bank' in sektor.lower() or 'finance' in sektor.lower():
                continue

            # =========================================================
            # A) TEKNİK ANALİZ MATRİSİ (Maksimum 40 Puan)
            # =========================================================
            teknik_puan = 0.0

            # 1. SMA 50 ve SMA 200 Golden Cross (Haftalıkta 10 ve 40 EMA/SMA genelde günlükteki 50-200 EMA'ya denk gelir)
            # Fakat garanti olsun diye direkt haftalıkta da SMA20 (Kısa Vade), SMA50 (Orta Vade) bakarız.
            df['SMA10'] = ta.sma(df['Close'], length=10) # 10 Hafta (Yaklaşık 50 Gün)
            df['SMA40'] = ta.sma(df['Close'], length=40) # 40 Hafta (Yaklaşık 200 Gün)
            
            fiyat = df['Close'].iloc[-1]
            sma10 = df['SMA10'].iloc[-1]
            sma40 = df['SMA40'].iloc[-1]

            if pd.isna(sma10) or pd.isna(sma40):
                continue
                
            # --- 1. HARD TREND FİLTRESİ (200 SMA KONTROLÜ) ---
            # Fiyat 200 Günlük (40 Haftalık) ortalamanın altındaysa DİREKT ELENİR! Düşüş trendi kabul edilemez.
            if fiyat < sma40:
                continue

            # --- 3. TEKNİK ONAY ŞARTI (50 SMA ONAYI) ---
            if fiyat > sma10:
                teknik_puan += 20 # Ana Trend Onayı (Trend üstünde kalmanın dev ödülü)
                
            if sma10 > sma40:
                teknik_puan += 5 # Golden Cross ivme desteği
            
            # 2. RSI: Haftalık periyotta diplerden dönüş (Oversold Area = 30-45 arası iyidir dönüş için)
            df['RSI'] = ta.rsi(df['Close'], length=14)
            rsi = df['RSI'].iloc[-1]
            if pd.notna(rsi):
                if 30 <= rsi <= 50:
                    teknik_puan += 15 # Güçlü Dip Dönüşü
                elif 50 < rsi <= 65:
                    teknik_puan += 7  # Sağlıklı Trend
                elif rsi < 30:
                    teknik_puan += 5  # Fazla Oversold (Düşen bıçak olabilir)

            # 3. MACD
            macd = ta.macd(df['Close'], fast=12, slow=26, signal=9)
            if macd is not None and not macd.empty:
                macd_cizgi = macd['MACD_12_26_9'].iloc[-1]
                signal_cizgi = macd['MACDs_12_26_9'].iloc[-1]
                
                if pd.notna(macd_cizgi) and pd.notna(signal_cizgi):
                    if macd_cizgi > signal_cizgi:
                        teknik_puan += 10 # MACD Al veriyor
            
            # Puan sınırını aşmasına izin verme
            teknik_puan = min(40.0, teknik_puan)
            
            # =========================================================
            # B) TEMEL ANALİZ MATRİSİ (Maksimum 40 Puan)
            # =========================================================
            temel_puan = 0.0
            
            fk_orani = temel_info.get('trailingPE', None)
            pd_dd = temel_info.get('priceToBook', None)

            # 1. F/K (P/E Ratio) - Yüksek kâr çarpanı pahalılığı gösterir
            if fk_orani is not None and fk_orani > 0:
                if fk_orani < 12.0:
                    temel_puan += 20 # Çok ucuz
                elif 12.0 <= fk_orani <= 25.0:
                    temel_puan += 10 # Kabul edilebilir
                elif 25.0 < fk_orani <= 45.0:
                    temel_puan += 5  # Büyüme şirketi pahalılığı
            else:
                # F/K Yok veya zarar eden şirket -> Temel zayıf.
                pass

            # 2. PD/DD (P/B Ratio) - Defter değerine yakınlık
            if pd_dd is not None and pd_dd > 0:
                if pd_dd < 2.0:
                    temel_puan += 20 # Defter değerine oldukça yakın (Fırsat)
                elif 2.0 <= pd_dd <= 4.0:
                    temel_puan += 10
                elif 4.0 < pd_dd <= 8.0:
                    temel_puan += 2
                    
            # 1. Aşama Toplam Matris Puanı (Maksimum 80)
            matris_skoru = teknik_puan + temel_puan

            sonuclar.append({
                'sembol': sembol,
                'sektor': sektor,
                'teknik_puan': teknik_puan,
                'temel_puan': temel_puan,
                'matris_skoru': matris_skoru
            })

        except Exception as hata:
            # Piyasadan silinmiş, hata veren kâğıtları atla.
            continue
            
    # Hisseleri ilk aşamaya göre puanlayıp "Ön Filtre (Top 10)"e al
    sonuclar.sort(key=lambda x: x['matris_skoru'], reverse=True)
    top10_adaylar = sonuclar[:10]

    print(f"\n[!] İlk Aşama (Matris) Tamamlandı! En Yüksek Puanlı 10 Hisse NLP (Haber) Taramasına Gidiyor...")
    
    # 2. Aşama - NLP Haber Analizi (Sentiment - %20 Etki)
    final_tablo = []
    
    for sira, aday in enumerate(top10_adaylar, 1):
        sembol = aday['sembol']
        ticker = yf.Ticker(sembol)
        
        haber_skoru = 0.0
        try:
            haberler = ticker.news
            toplam_duygu = 0.0
            
            if haberler and len(haberler) > 0:
                is_sayisi = 0
                for haber in haberler[:5]: # Son 5 haber başlığı
                    baslik = haber.get('title', '')
                    duygu_degeri = get_sentiment_score(baslik)
                    toplam_duygu += duygu_degeri
                    is_sayisi += 1
                
                # Ortalama Duygu -1 (Facia) ile 1.0 (Harika) arasında çıkar.
                ortalama_duygu = (toplam_duygu / is_sayisi) if is_sayisi > 0 else 0.0
                
                # Bu +1,-1 aralığındaki sonucu 0 ile 20 puan arasına normalize et
                # Eğer ortalama 0 ise (nötr), %50 = 10 puan alır. 
                # Eğer full 1.0 ise (harika) %100 = 20 puan alır.
                skor_normalize = (ortalama_duygu + 1.0) * 10
                haber_skoru = max(0.0, min(20.0, skor_normalize))
            else:
                # İnternette haber yoksa Nötr davranıp sabit puan verilir (10 puan)
                haber_skoru = 10.0
                
        except Exception as e:
            haber_skoru = 10.0

        # Nihai Algoritma Birleşimi (100 Üzerinden)
        nihai_puan = aday['matris_skoru'] + haber_skoru

        final_tablo.append({
            'Hisse Adı': sembol,
            'Sektörü': aday['sektor'],
            'Teknik Puan': round(aday['teknik_puan'], 1),
            'Temel Puan': round(aday['temel_puan'], 1),
            'Haber Skoru': round(haber_skoru, 1),
            'Nihai Toplam Puan': round(nihai_puan, 1) # Max 100
        })

    # Pandas Tablosunu Çıkar, Nihai Puanıyla Sırala
    df_rapor = pd.DataFrame(final_tablo)
    df_rapor = df_rapor.sort_values(by='Nihai Toplam Puan', ascending=False).reset_index(drop=True)
    
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 200)

    print("\n" + "="*85)
    print(" 🚀 MAKRO RADAR (KV KIYASLAMA) -> 3-6 AYLIK YATIRIM İÇİN TOP 10 (100 Üzerinden Puan)")
    print("="*85)
    print(df_rapor.to_string())
    print("=====================================================================================\n")

if __name__ == "__main__":
    run_makro_radar()
