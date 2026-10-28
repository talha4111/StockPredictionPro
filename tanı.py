"""
Botun neden işleme girmediğini teşhis eden script.
"""
import sys
sys.path.insert(0, '.')

try:
    from tarayici import veri_hazirla
except Exception as e:
    print(f"IMPORT HATASI: {e}")
    sys.exit(1)

TEST_COINLER = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT', 'BNB/USDT', 'XRP/USDT']
REF = 'BTC/USDT'

print("=" * 65)
print("  TANI RAPORU: Neden İşleme Girmiyor?")
print("=" * 65)

for coin in TEST_COINLER:
    print(f"\n--- {coin} ---")
    try:
        df = veri_hazirla(coin, REF, '1m', limit=250)
        if df is None or df.empty:
            print("  ❌ Veri GELMEDİ!")
            continue
        
        son = df.iloc[-1]
        close   = float(son.get('Hedef_Close', 0))
        atr     = float(son.get('ATR', 0))
        adx     = float(son.get('ADX_14', son.get('ADX', 0)))
        bb_w    = float(son.get('BB_Width', 1))
        bb_mean = float(son.get('BB_Width_Mean_100', 1))
        rsi     = float(son.get('RSI', 50))
        vol     = float(son.get('volume', 0))
        vol_sma = float(df['volume'].rolling(5).mean().iloc[-1])

        min_mesafe = close * 0.0075
        squeeze_ok = bb_w >= (bb_mean * 0.80)
        adx_ok     = adx >= 20.0
        vol_ok     = vol >= (vol_sma * 1.05)

        print(f"  ADX      : {adx:.2f}   {'✅ OK' if adx_ok else '❌ VETO (<20)'}")
        print(f"  Squeeze  : BB_W={bb_w:.4f} / Ort={bb_mean:.4f}   {'✅ OK' if squeeze_ok else '❌ VETO (Squeeze)'}")
        print(f"  Volume   : {vol:.0f} / SMA5={vol_sma:.0f}   {'✅ OK' if vol_ok else '❌ VETO (Hacim Düşük)'}")
        print(f"  ATR%     : {(atr/close)*100:.3f}%   MinMesafe%={0.75:.3f}%   {'✅ OK' if atr >= min_mesafe else '⚠️ Min mesafe devreye girer'}")
        print(f"  RSI      : {rsi:.1f}")

        if adx_ok and squeeze_ok and vol_ok:
            print("  >>> 🟢 Bu coin filtreleri GEÇER, XGBoost kararına gider")
        else:
            print("  >>> 🔴 Bu coin filtre AŞAMASINDA Veto yiyor")

    except Exception as e:
        print(f"  HATA: {e}")

print("\n" + "=" * 65)
print("Teşhis tamamlandı.")
