from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout

def model_olustur(input_shape):
    """
    LSTM Model Mimarisi
    
    Parametreler:
    - input_shape: (Pencere Boyutu, Özellik Sayısı) demektir.
      Örn: (60, 2) -> 60 günlük geçmişe bak, her gün için 2 veriye (SOL ve BTC) bak.
    """
    model = Sequential()

    # 1. LSTM KATMANI
    # return_sequences=True: Çünkü arkasından bir LSTM daha gelecek.
    # input_shape=input_shape: Otomatik olarak (60, 1) veya (60, 2) olduğunu buradan anlar.
    model.add(LSTM(units=64, return_sequences=True, input_shape=input_shape))
    
    # Dropout: Ezberlemeyi önlemek için nöronların %20'sini rastgele kapat.
    model.add(Dropout(0.2))

    # 2. LSTM KATMANI
    # return_sequences=False: Çünkü artık sonuca gidiyoruz, arkadan Dense gelecek.
    model.add(LSTM(units=32, return_sequences=False))
    model.add(Dropout(0.2))

    # 3. YOĞUN KATMANLAR (DENSE)
    # Karar mekanizması
    model.add(Dense(units=16, activation='relu'))