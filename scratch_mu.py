import yfinance as yf
import pandas_ta as ta

ticker = yf.Ticker('MU')
df = ticker.history(period='1y')
close = df['Close']
high = df['High']
low = df['Low']

son_fiyat = close.iloc[-1]
rsi = ta.rsi(close, length=14).iloc[-1]
atr = ta.atr(high, low, close, length=14).iloc[-1]
sma_50 = ta.sma(close, length=50).iloc[-1]
sma_200 = ta.sma(close, length=200).iloc[-1]

tp = son_fiyat + (atr * 3.0)
sl = son_fiyat - (atr * 1.5)

print(f"--- MICRON (MU) TUTMA ANALIZI ---")
print(f"Guncel Fiyat: ${son_fiyat:.2f}")
print(f"RSI(14): {rsi:.1f}")
print(f"ATR(14): ${atr:.2f} (Gunluk dalgalanma)")
print(f"SMA 50: ${sma_50:.2f} (Kisa-orta vade destek)")
print(f"SMA 200: ${sma_200:.2f} (Ana trend destegi)")
print(f"----------------------------------")
print(f"Dinamik Hedef (TP - 3 ATR): ${tp:.2f}")
print(f"Zarar Kes (SL - 1.5 ATR): ${sl:.2f}")
print(f"----------------------------------")
if rsi > 70:
    print("YORUM: Hisse asiri alim bolgesinde sismis durumda.")
    print("Yeni alim onerilmez, ancak elinde varsa TP/SL seviyeleriyle takip edebilirsin.")
