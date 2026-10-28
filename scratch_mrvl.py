import yfinance as yf
import pandas_ta as ta

ticker = yf.Ticker('COHR')
df = ticker.history(period='1y')
close = df['Close']
vol = df['Volume']

rsi = ta.rsi(close, length=14).iloc[-1]
obv = ta.obv(close, vol)
obv_sma20 = ta.sma(obv, length=20).iloc[-1]
obv_val = obv.iloc[-1]

macd = ta.macd(close, fast=12, slow=26, signal=9)
macd_val = macd.iloc[-1, 0]
macd_sig = macd.iloc[-1, 1]

bb = ta.bbands(close, length=20, std=2)
bb_low = bb.iloc[-1, 0]
bb_high = bb.iloc[-1, 2]
pos = (close.iloc[-1] - bb_low) / (bb_high - bb_low) if bb_high > bb_low else 0

info = ticker.info
print(f"Fiyat: {close.iloc[-1]:.2f}")
print(f"RSI: {rsi:.1f}")
print(f"OBV Durumu: {'Pozitif (Kurumsal Para Girisi Var)' if obv_val > obv_sma20 else 'Negatif (Para Cikisi)'}")
print(f"MACD: {'Bullish (Alim Yonde)' if macd_val > macd_sig else 'Bearish (Satis Yonde)'}")
print(f"Bollinger Band Poz: %{pos*100:.1f} (0=Alt, 100=Ust)")
print(f"F/K (PE Orani): {info.get('trailingPE', 'Bilinmiyor')}")
print(f"Borc/Ozkaynak: {info.get('debtToEquity', 'Bilinmiyor')}")
print(f"Temettu Verimi: %{(info.get('dividendYield', 0) or 0)*100:.2f}")

fcf = info.get('freeCashflow')
mc = info.get('marketCap')
if fcf and mc:
    print(f"FCF Getirisi: %{(fcf/mc)*100:.2f}")
else:
    print("FCF Getirisi: Bilinmiyor")
