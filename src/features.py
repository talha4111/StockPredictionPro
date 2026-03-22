import pandas as pd
import numpy as np

class FeatureEngineer:
    def __init__(self, df):
        self.df = df.copy()

    def prepare_data(self):
        """
        V3.0: Çok Değişkenli (Multivariate) Özellik Mühendisliği
        """
        # 1. RSI Hesapla (Aşırı Alım/Satım Göstergesi)
        delta = self.df['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        self.df['RSI'] = 100 - (100 / (1 + rs))

        # 2. MACD Hesapla (Trend Takipçisi)
        ema12 = self.df['Close'].ewm(span=12, adjust=False).mean()
        ema26 = self.df['Close'].ewm(span=26, adjust=False).mean()
        self.df['MACD'] = ema12 - ema26
        self.df['Signal_Line'] = self.df['MACD'].ewm(span=9, adjust=False).mean()

        # 3. Hareketli Ortalamalar (Trendin Yönü)
        self.df['MA20'] = self.df['Close'].rolling(window=20).mean()
        self.df['MA50'] = self.df['Close'].rolling(window=50).mean()

        # 4. Hacim Değişimi (İştah Kontrolü)
        self.df['Vol_Change'] = self.df['Volume'].pct_change()

        # Boş satırları temizle
        self.df.dropna(inplace=True)
        
        return self.df