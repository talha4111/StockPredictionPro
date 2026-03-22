import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
import matplotlib.pyplot as plt
import config  # Ayarlarımızı buradan çekiyoruz

class StockPredictor:
    def __init__(self, df, lookback=60):
        self.df = df
        self.lookback = lookback
        # V3.0: Modelin bakacağı tüm göstergeler burada!
        # Not: Bu sütunların features.py tarafından üretilmiş olması şart.
        self.feature_columns = ['Close', 'RSI', 'MACD', 'Volume'] 
        self.scaler = MinMaxScaler(feature_range=(0, 1))
        self.model = None

    def prepare_data(self):
        # 1. Sadece belirlediğimiz sütunları seç
        data = self.df[self.feature_columns].values
        
        # 2. Veriyi Ölçekle (0 ile 1 arasına sıkıştır)
        # Artık sadece Fiyatı değil, Hacmi ve RSI'ı da ölçekliyoruz.
        scaled_data = self.scaler.fit_transform(data)

        x, y = [], []
        # Geçmiş 60 güne bakarak (x), bugünün Kapanış Fiyatını (y) tahmin et
        for i in range(self.lookback, len(scaled_data)):
            x.append(scaled_data[i-self.lookback:i, :]) # Tüm özellikler (Close, RSI, Volume...)
            y.append(scaled_data[i, 0]) # Hedefimiz sadece 'Close' (0. indeks)

        self.x, self.y = np.array(x), np.array(y)
        
        # LSTM için boyut ayarı: (Veri Sayısı, 60 Gün, Özellik Sayısı)
        print(f"🧠 Veri Seti Hazırlandı: {self.x.shape}")

    def build_model(self):
        model = Sequential()
        # input_shape artık dinamik! (60, 4) gibi olacak.
        model.add(LSTM(units=50, return_sequences=True, input_shape=(self.x.shape[1], self.x.shape[2])))
        model.add(Dropout(0.2))
        model.add(LSTM(units=50, return_sequences=False))
        model.add(Dropout(0.2))
        model.add(Dense(units=1)) # Çıktı tek bir rakam (Fiyat)

        model.compile(optimizer='adam', loss='mean_squared_error')
        self.model = model

    def train(self, epochs=50, batch_size=32):
        print(f"🚀 {config.TICKER} için V3.0 Eğitimi Başlıyor (Hacim ve RSI Devrede)...")
        self.model.fit(self.x, self.y, epochs=epochs, batch_size=batch_size, verbose=1)
        self.model.save("beyin.keras")
        print("💾 YENİ MODEL KAYDEDİLDİ: beyin.keras")

    def _inverse_transform_price(self, scaled_price):
        """
        YARDIMCI FONKSİYON:
        Scaler 4 sütun (Close, RSI, MACD, Volume) bekliyor ama model tek sütun (Fiyat) üretiyor.
        Hata almamak için sahte bir tablo oluşturup sadece Fiyat kısmını dolduruyoruz.
        """
        # 1. Boş bir matris yarat (1 satır, Özellik Sayısı kadar sütun)
        dummy = np.zeros(shape=(1, len(self.feature_columns)))
        # 2. İlk sütuna (Close) tahmin ettiğimiz değeri koy
        dummy[0, 0] = scaled_price
        # 3. Geri dönüştür (Unscale)
        unscaled = self.scaler.inverse_transform(dummy)
        # 4. Sadece ilk sütunu (Fiyatı) al ve döndür
        return unscaled[0, 0]

    def plot_results(self):
        print("\n📈 V3.0 Grafik Analizi Hazırlanıyor...")
        predictions_scaled = self.model.predict(self.x)
        
        # Ölçekleri geri çevir (Normal Fiyata)
        predictions = []
        for p in predictions_scaled:
            predictions.append(self._inverse_transform_price(p[0]))
            
        actual_prices = []
        for a in self.y:
            actual_prices.append(self._inverse_transform_price(a))

        plt.figure(figsize=(14,7))
        plt.plot(actual_prices, color='blue', label=f'Gerçek {config.TICKER} Fiyatı')
        plt.plot(predictions, color='red', label='Yapay Zeka (V3.0) Tahmini')
        plt.title(f'{config.TICKER} - Fiyat, Hacim ve Teknik Göstergeli Analiz')
        plt.xlabel('Zaman (Gün)')
        plt.ylabel(f'Fiyat ({config.CURRENCY})')
        plt.legend()
        plt.show()

    def predict_next_day(self):          
        # 1. TAHMİN İÇİN VERİYİ HAZIRLA
        last_lookback_days = self.df[self.feature_columns].values[-self.lookback:]
        last_lookback_days_scaled = self.scaler.transform(last_lookback_days)
        
        x_input = np.array([last_lookback_days_scaled])
        x_input = np.reshape(x_input, (x_input.shape[0], x_input.shape[1], x_input.shape[2]))
        
        # 2. TAHMİNİ YAP
        prediction_scaled = self.model.predict(x_input)
        predicted_price = self._inverse_transform_price(prediction_scaled[0][0])
        
        # 3. TEKNİK GÖSTERGELERİ OKU (Rapor için)
        # Veri setindeki en son satırı (bugünü) alıyoruz
        son_durum = self.df.iloc[-1]
        
        rsi_degeri = son_durum['RSI']
        macd_degeri = son_durum['MACD']
        hacim_degeri = son_durum['Volume']
        
        # RSI Yorumu
        rsi_yorum = "NÖTR"
        if rsi_degeri > 70: rsi_yorum = "AŞIRI ALIM (Düşüş Riski) 🔴"
        elif rsi_degeri < 30: rsi_yorum = "AŞIRI SATIM (Yükseliş Fırsatı) 🟢"
        
        # MACD Yorumu
        macd_yorum = "SAT"
        if macd_degeri > son_durum['Signal_Line']: macd_yorum = "AL (Trend Pozitif) 🟢"

        # 4. DETAYLI RAPORU YAZDIR
        print("\n" + "█"*50)
        print(f"🔬 TEKNİK GÖSTERGE RAPORU ({config.TICKER})")
        print("█"*50)
        print(f"📊 RSI (Güç Endeksi): {rsi_degeri:.2f} -> {rsi_yorum}")
        print(f"🌊 MACD (Trend):      {macd_degeri:.4f} -> {macd_yorum}")
        print(f"🔊 Son Hacim:         {int(hacim_degeri):,}")
        print("-" * 50)
        print(f"🔮 GELECEK TAHMİNİ:   {config.CURRENCY}{predicted_price:.2f}")
        print("█"*50 + "\n")
        
        return predicted_price