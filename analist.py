import requests
try:
    import feedparser
    FEEDPARSER_AVAIL = True
except ImportError:
    print("[!] 'feedparser' kutuphanesi bulunamadi! Haber (duygu) analizi yedek (notr) modda calisacak.")
    FEEDPARSER_AVAIL = False

try:
    from textblob import TextBlob
    TEXTBLOB_AVAIL = True
except ImportError:
    print("[!] 'textblob' kutuphanesi bulunamadi! Haber (duygu) analizi yedek (notr) modda calisacak.")
    TEXTBLOB_AVAIL = False

import ccxt
from datetime import datetime
# --- ÖZEL FİNANSAL SÖZLÜK ---
# Standart yapay zeka bu kelimelerin borsadaki ağırlığını bilmez, biz öğretiyoruz.
POZITIF_KELIMELER = [
    "bull", "bullish", "surge", "soar", "jump", "skyrocket", "high", "record", 
    "breakout", "gain", "profit", "partner", "adoption", "launch", "upgrade", 
    "approval", "etf", "buy", "long", "support", "rally", "moon"
]

NEGATIF_KELIMELER = [
    "bear", "bearish", "crash", "drop", "plunge", "collapse", "low", "loss", 
    "sell", "dump", "ban", "hack", "scam", "fraud", "lawsuit", "sec", 
    "reject", "delay", "down", "resistance", "correction", "panic"
]

def korku_acgozluluk_getir():
    """
    Fear and Greed Index verisini çeker.
    """
    try:
        url = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=10)
        data = response.json()
        deger = int(data['data'][0]['value'])
        durum = data['data'][0]['value_classification']
        return deger, durum
    except Exception as e:
        print(f"⚠️ Korku Endeksi Hatası: {e}")
        return 50, "Nötr (Veri Yok)"

def haberleri_analiz_et(coin_adi="crypto"):
    """
    Google News üzerinden başlıkları çeker ve ÖZEL SÖZLÜK ile puanlar.
    """
    # GÜNCELLEME: textblob ve feedparser aktif edildi, simülasyon yerine canlı çalışacak
    rss_url = f"https://news.google.com/rss/search?q={coin_adi}+price+crypto+news&hl=en-US&gl=US&ceid=US:en"
    
    try:
        feed = feedparser.parse(rss_url)
        toplam_skor = 0
        haber_sayisi = 0
        basliklar = []

        # İlk 7 haberi al (Daha geniş tarama)
        for entry in feed.entries[:7]:
            baslik = entry.title.lower()
            ozet = entry.summary.lower() if 'summary' in entry else ""
            tam_metin = baslik + " " + ozet # Sadece başlığa değil, içeriğe de bak
            
            # 1. Aşama: Standart Analiz (TextBlob)
            if TEXTBLOB_AVAIL:
                blob_skoru = TextBlob(entry.title).sentiment.polarity
            else:
                blob_skoru = 0.0
            
            # 2. Aşama: Finansal Sözlük Kontrolü (Bizim eklediğimiz zeka)
            sozluk_skoru = 0
            
            for k in POZITIF_KELIMELER:
                if k in tam_metin: 
                    sozluk_skoru += 0.3 # Her olumlu kelime puanı artırır
            
            for k in NEGATIF_KELIMELER:
                if k in tam_metin: 
                    sozluk_skoru -= 0.3 # Her olumsuz kelime puanı düşürür

            # Final Skor: Standart + Sözlük
            # (Sözlük skorunun etkisi daha yüksek olsun istiyoruz)
            final_skor = blob_skoru + sozluk_skoru
            
            # Skoru -1 ile +1 arasına sıkıştır (Normalize et)
            final_skor = max(-1, min(1, final_skor))

            toplam_skor += final_skor
            haber_sayisi += 1
            basliklar.append((entry.title, final_skor))

        if haber_sayisi == 0:
            return 0, []

        ortalama_skor = toplam_skor / haber_sayisi
        return ortalama_skor, basliklar

    except Exception as e:
        print(f"⚠️ Haber Analiz Hatası: {e}")
        return 0, []

def onchain_inflow_durumu(coin="BTC/USDT"):
    """
    Ücretsiz/Açık kaynak proxy kullanarak On-Chain BTC Inflow (Borsaya Giriş) tespiti yapar.
    Gerçek on-chain veriler ücretli olduğu için, bu sistem fiyat düşerken son 1 saatin 
    hacminin günlük ortalamayı %300 aşıp aşmadığına (Balina Satışı/Borsaya Yarıldığına) bakar.
    Büyük giriş var ve satılıyorsa True (Tehlike) döner.
    """
    try:
        borsa = ccxt.binance({'enableRateLimit': True, 'options': {'adjustForTimeDifference': True, 'recvWindow': 60000}})
        # Son 24 saatin saatlik mumlarını çek
        bars = borsa.fetch_ohlcv(coin, '1h', limit=24)
        if not bars: return False
        
        hacimler = [b[5] for b in bars[:-1]]
        ort_hacim = sum(hacimler) / len(hacimler) if hacimler else 0
        
        son_mum_hacim = bars[-1][5]
        son_mum_fiyat_degisimi = bars[-1][4] - bars[-1][1] # Kapanış - Açılış
        
        # Eğer çok sert bir satış mumu (Kırmızı) varsa VE hacim ortalamanın 3 katıysa:
        if son_mum_fiyat_degisimi < 0 and son_mum_hacim > (ort_hacim * 3):
            return True # Inflow şüphesi / Balina Satış Baskısı Tespiti
            
        return False
    except Exception as e:
        print(f"⚠️ On-Chain Proxy Hatası: {e}")
        return False

def makro_volatilite_beklentisi():
    """
    Önemli ekonomik takvim verilerini (FED vb.) kontrol etmek için zaman/gün kontrolörü.
    Büyük veri saatlerinde botu işlem açmaktan korur (Örn: Çarşamba 21:00 FOMC veya TSİ 15:30 CPI/Core Open)
    """
    try:
        now = datetime.now()
        saat = now.hour
        dakika = now.minute
        gun = now.weekday() # 0: Pazartesi, ..., 6: Pazar
        
        # 1- ABD Piyasa Açılışı ve CPI/NFP Saatleri (Genelde TSİ 15:30 - 16:00 arası çok volatil)
        if saat == 15 and 30 <= dakika <= 59:
            return True
            
        # 2- Çarşamba günleri FED Kararları / Tutanaklar (Genelde TSİ 21:00 - 21:30)
        if gun == 2 and saat == 21 and dakika <= 30:
            return True
            
        return False
    except:
        return False

if __name__ == "__main__":
    # Test Et
    coin = "solana"
    print(f"🔍 {coin.upper()} İçin Detaylı Analiz Yapılıyor...")
    skor, haberler = haberleri_analiz_et(coin)
    
    print(f"\nOrtalama Duygu Skoru: {skor:.2f}")
    print("-" * 30)
    for h in haberler:
        durum = "NÖTR"
        if h[1] > 0.2: durum = "POZİTİF 🟢"
        elif h[1] < -0.2: durum = "NEGATİF 🔴"
        print(f"[{durum}] {h[0][:60]}... (Puan: {h[1]:.2f})")