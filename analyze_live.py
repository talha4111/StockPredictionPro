import pandas as pd

try:
    df = pd.read_csv('trade_history.csv')
    live_df = df[df['Islem_Yonu'] == 'LIVE'].copy() if 'Islem_Yonu' in df.columns else df[df['Parite'].str.contains('LIVE') | df['Islem_Yonu'].str.contains('LIVE')]
    
    # Wait, the column Islem_Yonu has DEMO vs LIVE?
    # Let me check the header: Tarih_Saat,Parite,Islem_Yonu,Giris_Fiyati,Cikis_Fiyati,Net_PNL_USDT,PNL_Yuzde,AI_Guven_Skoru
    
    # In row 31: 2026-03-19 18:30:10,KAT/USDT,LIVE,SHORT,0.01035,0.01035,0.0,0.0,100.0
    # Wait, Islem_Yonu is column 3 (index 2)? No, the header is:
    # Tarih_Saat(0), Parite(1), Islem_Yonu(2), Giris_Fiyati(3), Cikis_Fiyati(4), Net_PNL_USDT(5), PNL_Yuzde(6), AI_Guven_Skoru(7)
    # Ah, the values are: 2026-03-19 18:30:10 (0), KAT/USDT (1), LIVE (2 - Wait, LIVE is in the Islem_Yonu spot? But then where is LONG/SHORT?)
    # "2026-03-19 23:29:21,DEGO/USDT,LIVE,LONG,0.6299,0.6309,0.04,0.16,90.34"
    # Wait! The header is: Tarih_Saat,Parite,Islem_Yonu,Giris_Fiyati,Cikis_Fiyati,Net_PNL_USDT,PNL_Yuzde,AI_Guven_Skoru (8 columns)
    # But row has: 2026-03-19 23:29:21, DEGO/USDT, LIVE, LONG, 0.6299, 0.6309, 0.04, 0.16, 90.34 (9 values!)
    # That means there is an extra column, perhaps 'Mod' (LIVE/DEMO) and 'Yon' (LONG/SHORT) but the header is missing 'Mod'.
    # Let's read the first line again: Tarih_Saat,Parite,Islem_Yonu,Giris_Fiyati,Cikis_Fiyati,Net_PNL_USDT,PNL_Yuzde,AI_Guven_Skoru
    
    with open('trade_history.csv', 'r', encoding='utf-8') as f:
        lines = f.readlines()
        if len(lines) > 1:
            header = lines[0].strip().split(',')
            parts = lines[1].strip().split(',')
            print(f"Header length: {len(header)}")
            print(f"Row length: {len(parts)}")
            print(f"Header: {header}")
            print(f"Row 1: {parts}")
            
    # Calculate live PnL anyway
    live_trades = []
    for line in lines[1:]:
        parts = line.strip().split(',')
        if len(parts) >= 9 and parts[2] == 'LIVE':
            live_trades.append({
                'Tarih': parts[0],
                'Parite': parts[1],
                'Mod': parts[2],
                'Yon': parts[3],
                'Giris': float(parts[4]),
                'Cikis': float(parts[5]),
                'PNL': float(parts[6]),
                'PNL_Yuzde': float(parts[7]),
                'Guven': float(parts[8])
            })
            
    if live_trades:
        df_live = pd.DataFrame(live_trades)
        print("\n--- LIVE TRADES ---")
        print(df_live)
        print(f"\nTotal LIVE PNL USDT: {df_live['PNL'].sum()}")
        print(f"Total LIVE Trades: {len(df_live)}")
        print(f"Win trades: {len(df_live[df_live['PNL'] > 0])}")
        print(f"Loss trades: {len(df_live[df_live['PNL'] < 0])}")
    else:
        print("No LIVE trades found.")
        
except Exception as e:
    print(f"Error: {e}")
