import json

with open(r'c:\Users\talha\OneDrive\Desktop\StockPredictionPro\QuantBot\backtest_reports\extended_baseline_20260729_141604\results.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

print("=" * 100)
print("1 HAKİKİ TREND & ALWAYS LONG (240m = 4 Saat Ufuk) DETAYLARI")
print("=" * 100)

for row in data['rows']:
    if row.get('horizon_minutes') == 240 and row.get('rule') in ('always_long', 'trend_long', 'regime_adaptive', 'trend_short'):
        sym = row['symbol']
        rule = row['rule']
        direction = row['direction']
        t = row['train']
        h = row['holdout']
        print(f"{sym:10s} | {direction:6s} | {rule:22s} | Train: Net={t['net_return']:+.4f} PF={t.get('profit_factor',0):.2f} | Holdout: Net={h['net_return']:+.4f} PF={h.get('profit_factor',0):.2f} Sig={h['signals']}")
