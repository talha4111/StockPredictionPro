#!/usr/bin/env python3
"""Binance vs Bot Hafıza Uyumsuzluk Teşhis Scripti"""
import ccxt, json, os, sys

if sys.stdout.encoding != 'utf-8':
    try:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except: pass

# Testnet
with open('ayar.json','r') as f:
    ayar = json.load(f)
tkey = ayar.get('testnet_api_key','')
tsec = ayar.get('testnet_secret','')

demo = ccxt.binanceusdm({
    'apiKey': tkey, 'secret': tsec,
    'options': {'defaultType':'future','adjustForTimeDifference':True,'recvWindow':60000}
})
demo.enable_demo_trading(True)

print("=" * 60)
print("  BINANCE TESTNET - GERCEK DURUM")
print("=" * 60)

acik_semboller = set()
try:
    bal = demo.fetch_balance({'type':'future'})
    usdt = float(bal.get('USDT',{}).get('total',0))
    print(f"  Bakiye: {usdt:.2f} USDT")
except Exception as e:
    print(f"  Bakiye HATA: {e}")

try:
    poz = demo.fetch_positions()
    for p in poz:
        amt = float(p.get('contracts', p.get('info',{}).get('positionAmt',0)))
        if amt != 0:
            sym = p.get('symbol','?')
            entry = float(p.get('entryPrice', p.get('info',{}).get('entryPrice',0)))
            mark = float(p.get('markPrice', p.get('info',{}).get('markPrice',0)))
            pnl = float(p.get('unrealizedPnl', p.get('info',{}).get('unRealizedProfit',0)))
            side = 'LONG' if amt > 0 else 'SHORT'
            lev = p.get('leverage', p.get('info',{}).get('leverage','?'))
            pnl_pct = ((mark - entry) / entry * 100) if entry > 0 else 0
            if side == 'SHORT':
                pnl_pct = -pnl_pct
            print(f"  {sym:20s} | {side:5s} | Amt: {amt:12.4f} | Entry: {entry:.6f} | Mark: {mark:.6f} | PNL: {pnl:+.4f} ({pnl_pct:+.2f}%) | Lev: {lev}x")
            acik_semboller.add(sym.replace(':USDT','').replace('/USDT',''))
    if not acik_semboller:
        print("  Acik pozisyon YOK")
    print(f"  Toplam acik: {len(acik_semboller)}")
except Exception as e:
    print(f"  Pozisyon HATA: {e}")

# Acik emirler
print()
print("=" * 60)
print("  BINANCE TESTNET - ACIK EMIRLER (TP/SL/TRAILING)")
print("=" * 60)
try:
    for sym_raw in acik_semboller:
        sym_full = sym_raw + '/USDT'
        orders = demo.fetch_open_orders(sym_full)
        for o in orders:
            otype = o.get('type','?')
            oside = o.get('side','?')
            oprice = o.get('stopPrice', o.get('price','?'))
            oamt = o.get('amount','?')
            print(f"  {sym_full:15s} | {otype:25s} | Side: {oside} | StopPrice: {oprice} | Amt: {oamt}")
    if not acik_semboller:
        print("  (Acik pozisyon yok, emir taramasi atlanıyor)")
except Exception as e:
    print(f"  Emir tarama HATA: {e}")

# Bot hafizasi
print()
print("=" * 60)
print("  BOT HAFIZASI - aktif_detay.json")
print("=" * 60)
hafiza_semboller = set()
try:
    with open('aktif_detay.json','r') as f:
        detay = json.load(f)
    real_keys = [k for k in detay if not k.startswith('_tsl')]
    for k in real_keys:
        v = detay[k]
        if isinstance(v, dict):
            yon = v.get('Islem_Yonu','?')
            giris = v.get('Giris_Fiyati',0)
            tp = v.get('TP_Fiyat',0)
            sl = v.get('SL_Fiyat',0)
            hesap = v.get('Hesap_Tipi','?')
            print(f"  {k:30s} | {yon:5s} | Giris: {giris:.6f} | TP: {tp:.6f} | SL: {sl:.6f} | Hesap: {hesap}")
            sem = k.split('/')[0] if '/' in k else k.split('_')[0]
            hafiza_semboller.add(sem)
    if not real_keys:
        print("  Hafiza BOS")
    tsl_keys = [k for k in detay if k.startswith('_tsl')]
    print(f"  Pozisyon kaydi: {len(real_keys)} | TSL kaydi: {len(tsl_keys)}")
except Exception as e:
    print(f"  Detay HATA: {e}")

# Uyumsuzluk
print()
print("=" * 60)
print("  UYUMSUZLUK ANALIZI")
print("=" * 60)
sadece_binance = acik_semboller - hafiza_semboller
sadece_hafiza = hafiza_semboller - acik_semboller

if sadece_binance:
    print(f"  [!] BINANCE'DA VAR ama HAFIZADA YOK: {sadece_binance}")
    print(f"      -> Bot bu pozisyonlari YONETMİYOR! TP/SL sadece Binance sunucu zırhına bağlı.")
if sadece_hafiza:
    print(f"  [!] HAFIZADA VAR ama BINANCE'DA YOK: {sadece_hafiza}")
    print(f"      -> HAYALET pozisyonlar! Bot olmayan pozisyonları kapatmaya calisiyor.")
if not sadece_binance and not sadece_hafiza:
    if acik_semboller:
        print("  ESLESME BASARILI - Uyumsuzluk yok")
    else:
        print("  Her ikisi de bos - Sorun yok")

# KASA durumu
print()
print("=" * 60)
print("  LIVE HESAP KONTROLU")
print("=" * 60)
try:
    live_key = os.environ.get('LIVE_API_KEY','')
    live_sec = os.environ.get('LIVE_SECRET_KEY','')
    if not live_key:
        # .env dosyasından oku
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
        if os.path.exists(env_path):
            with open(env_path) as ef:
                for line in ef:
                    if line.startswith('LIVE_API_KEY='):
                        live_key = line.strip().split('=',1)[1]
                    elif line.startswith('LIVE_SECRET_KEY='):
                        live_sec = line.strip().split('=',1)[1]
    
    if live_key:
        live = ccxt.binanceusdm({
            'apiKey': live_key, 'secret': live_sec,
            'options': {'defaultType':'future','adjustForTimeDifference':True,'recvWindow':60000}
        })
        lb = live.fetch_balance({'type':'future'})
        live_usdt = float(lb.get('USDT',{}).get('total',0))
        print(f"  LIVE Bakiye: {live_usdt:.2f} USDT")
        
        lpoz = live.fetch_positions()
        live_acik = [(p['symbol'], float(p.get('contracts',0)), float(p.get('unrealizedPnl',0)))
                     for p in lpoz if float(p.get('contracts',p.get('info',{}).get('positionAmt',0))) != 0]
        if live_acik:
            for s,c,pnl in live_acik:
                print(f"  LIVE ACIK: {s} | Miktar: {c} | PNL: {pnl:+.4f}")
        else:
            print("  LIVE acik pozisyon YOK (DOGRU - tetik kapali)")
    else:
        print("  LIVE API key bulunamadi")
except Exception as e:
    print(f"  LIVE HATA: {e}")

print()
print("=" * 60)
print("  TESHIS TAMAMLANDI")
print("=" * 60)
