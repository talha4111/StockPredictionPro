import feedparser
import urllib.parse
from bs4 import BeautifulSoup # HTML temizliği için (Google bazen HTML kodu gönderir)

class NewsFetcher:
    def __init__(self, ticker="NVDA"):
        self.ticker = ticker
        # Google News RSS URL'si
        query = f"{ticker} stock news"
        encoded_query = urllib.parse.quote(query)
        self.rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"

    def clean_html(self, raw_html):
        """RSS özetindeki <b> gibi HTML etiketlerini temizler."""
        soup = BeautifulSoup(raw_html, "html.parser")
        return soup.get_text()

    def get_latest_news(self):
        print(f"📡 '{self.ticker}' için Google News (Başlık + Özet) taranıyor...")
        
        try:
            feed = feedparser.parse(self.rss_url)
            news_data = []
            
            # İlk 5 haberi al
            for entry in feed.entries[:5]:
                title = entry.title
                
                # ÖZETİ (Description) ALALIM
                # Google bazen özeti 'description' bazen 'summary' içine koyar
                raw_summary = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
                
                # HTML temizliği yap (Linkleri vs kaldır)
                clean_summary = self.clean_html(raw_summary)
                
                # Başlık ve Özeti Birleştir!
                # FinBERT'e "Başlık. Özet" şeklinde vereceğiz.
                full_text = f"{title}. {clean_summary}"
                
                news_data.append(full_text)
            
            if news_data:
                print(f"✅ {len(news_data)} adet detaylı haber çekildi.")
            else:
                print("⚠️ Haber bulunamadı.")

            return news_data

        except Exception as e:
            print(f"❌ Haber Çekme Hatası: {e}")
            return []

# --- Test Alanı ---
if __name__ == "__main__":
    fetcher = NewsFetcher("NVDA")
    haberler = fetcher.get_latest_news()
    
    print("\n--- DETAYLI HABER ANALİZİ ---")
    for i, h in enumerate(haberler):
        print(f"\nHABER {i+1}:")
        print(h[:200] + "...") # Çok uzunsa kısaltarak göster