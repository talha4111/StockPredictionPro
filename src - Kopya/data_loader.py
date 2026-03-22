# src/data_loader.py dosyasının tamamını bununla değiştir:

import yfinance as yf
import pandas as pd
import os

class StockDataLoader:
    def __init__(self, ticker, start_date, end_date, data_dir="data"):
        self.ticker = ticker
        self.start_date = start_date
        self.end_date = end_date
        self.data_dir = data_dir
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

    def load_data(self):
        file_path = f"{self.data_dir}/{self.ticker}.csv"
        
        # Eğer dosya varsa yerelden oku
        if os.path.exists(file_path):
            print(f"📂 Yerel dosyadan yükleniyor: {self.ticker}")
            df = pd.read_csv(file_path)
            df['Date'] = pd.to_datetime(df['Date'])
            return df
        
        # Dosya yoksa internetten indir
        else:
            print(f"📥 {self.ticker} için veri indiriliyor...")
            df = yf.download(self.ticker, start=self.start_date, end=self.end_date)
            
            # --- KRİTİK DÜZELTME BAŞLANGICI ---
            # yfinance bazen sütunları (Price, Ticker) şeklinde iki katmanlı getirir.
            # Biz sadece 'Price' (Close, Open vs.) istiyoruz.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            # --- KRİTİK DÜZELTME BİTİŞİ ---

            df.reset_index(inplace=True)
            
            # Tarih ve fiyatların düzgün olduğundan emin olalım
            df.to_csv(file_path, index=False)
            print(f"✅ Temiz veri kaydedildi: {file_path}")
            return df