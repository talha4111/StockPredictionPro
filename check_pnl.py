import pandas as pd

try:
    df = pd.read_csv('trade_history.csv')
    df = df.sort_values(by='Net_PNL_USDT', ascending=False)
    print("En Yuksek Karli Islemler (Sanal Hata Tespiti):")
    print(df[['Tarih_Saat', 'Parite', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT']].head(5))
except Exception as e:
    print(e)
