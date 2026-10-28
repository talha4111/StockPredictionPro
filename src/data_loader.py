import yfinance as yf
import pandas as pd
from datetime import datetime

class StockDataLoader:
    def __init__(self, ticker, start_date, end_date):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date

    def load_data(self, period="max", interval="1d"):
        """
        Veriyi çekmek için kullanılan ana fonksiyon.
        interval: '1d' (Günlük), '4h' (4 Saatlik), '1h' (1 Saatlik)
        period: Verinin ne kadar geriye gideceği ('max', '1y', '60d' vb.)
        """
        try:
            print(f"📡 {self.ticker} verisi çekiliyor... (Vites: {interval})")
            
            # Kripto ve Hisse verilerini Yahoo Finance üzerinden çeker
            # period ve interval parametreleri burada hayati önem taşır
            data = yf.download(
                tickers=self.ticker,
                start=self.start_date if interval == "1d" else None, 
                end=self.end_date if interval == "1d" else None,
                period=period if interval != "1d" else None,
                interval=interval,
                progress=False,
                auto_adjust=True
            )

            if data.empty:
                print(f"❌ HATA: {self.ticker} için veri bulunamadı.")
                return None
            
            # Veriyi temizle ve hazırla
            data.reset_index(inplace=True)
            return data

        except Exception as e:
            print(f"❌ Veri yükleme hatası: {e}")
            return None