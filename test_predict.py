import numpy as np
import pandas as pd
from tensorflow.keras.models import load_model
from sklearn.preprocessing import MinMaxScaler
from tarayici import veri_getir_dortlu
import os

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

hedef_coin = 'AVAX-USD'
REF = 'BTC-USD'
model_adi = f'beyin_{hedef_coin}.keras'

print(f"Loading {model_adi}...")
ozel_model = load_model(model_adi)

print(f"Fetching data for {hedef_coin}...")
df = veri_getir_dortlu(hedef_coin, REF)

features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon']
scaler = MinMaxScaler(feature_range=(-1, 1))
dataset = scaler.fit_transform(df[features].values)
giris = np.reshape(dataset[-60:], (1, 60, 6))

print("Predicting...")
tahmin_scaled = ozel_model.predict(giris, verbose=0)
print(f"Raw prediction (scaled): {tahmin_scaled}")

dummy = np.zeros((1, 6))
dummy[0, 0] = tahmin_scaled[0][0]
tahmin_yuzde = scaler.inverse_transform(dummy)[0][0]

print(f"Inverse transformed prediction (tahmin_yuzde): {tahmin_yuzde}")

guncel = df['Hedef_Close'].iloc[-1]
print(f"Current Price: {guncel}")

predicted_price = guncel * (1 + tahmin_yuzde)
print(f"Predicted Price calculating from return: {predicted_price}")
