import yfinance as yf
import pandas_ta as ta
import pandas as pd

ticker = yf.Ticker('GARAN.IS')

# Fundamental data
info = ticker.info
pe = info.get('trailingPE', 'N/A')
pb = info.get('priceToBook', 'N/A')

# Technical data (Daily)
df = ticker.history(period="2y", interval="1d")
if not df.empty:
    df['SMA50'] = ta.sma(df['Close'], length=50)
    df['SMA200'] = ta.sma(df['Close'], length=200)

    sma50 = df['SMA50'].iloc[-1]
    sma200 = df['SMA200'].iloc[-1]
    close = df['Close'].iloc[-1]
else:
    sma50 = sma200 = close = 'N/A'

print(f"=====================================")
print(f" GARAN.IS HAM VERİLER ")
print(f"=====================================")
print(f" Güncel Fiyat : {close:.2f} TL" if isinstance(close, float) else f" Güncel Fiyat : {close}")
print(f" F/K (P/E)    : {pe:.2f}" if isinstance(pe, float) else f" F/K (P/E)    : {pe}")
print(f" PD/DD (P/B)  : {pb:.2f}" if isinstance(pb, float) else f" PD/DD (P/B)  : {pb}")
print(f" SMA 50 Gün.  : {sma50:.2f} TL" if isinstance(sma50, float) else f" SMA 50 Gün.  : {sma50}")
print(f" SMA 200 Gün. : {sma200:.2f} TL" if isinstance(sma200, float) else f" SMA 200 Gün. : {sma200}")
print(f"=====================================")
