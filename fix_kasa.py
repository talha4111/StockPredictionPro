import pandas as pd
import json

kasa = 10000.0
try:
    df = pd.read_csv('trade_history.csv')
    pnl = df[df['Hesap_Tipi'].str.contains('DEMO', na=False, case=False)]['Net_PNL_USDT'].sum()
    if pd.notna(pnl):
        kasa = 10000.0 + float(pnl)
    print(f"Kripto Trade History'den okunan PNL: {pnl} -> Kasa Hacmi: {kasa}")
except Exception as e:
    print("CSV okunamadi, kasa default 10k ->", e)

try:
    with open('sanal_kasa_kripto.json', 'w') as f:
        json.dump({'bakiye': kasa}, f)
    print("Kripto kasa basariyla geri yuklendi!")
except Exception as e:
    print("Kripto kasa kaydi basarisiz:", e)
