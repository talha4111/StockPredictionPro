import os
import re

raise SystemExit("Bu dosya eski tek-dosya mimarisi icin yazilmis yama artigidir; calistirilmemelidir.")

MAIN_FILE = r"C:\Users\Talha\Desktop\StockPredictionPro\main.py"

with open(MAIN_FILE, "r", encoding="utf-8") as f:
    text = f.read()

# 1. Imports add
if "from ai_core import BeyinMotoru" not in text:
    text = text.replace("import pandas as pd", "import pandas as pd\nfrom ai_core import BeyinMotoru")

# 2. Sector Limits update
old_limit = """        hedef_sektor = SEKTORLER.get(sembol, 'Alternatif')
        if aktif_sektorler.get(hedef_sektor, 0) >= 2:
            print(f"⚠️ [{sembol}] İptal: '{hedef_sektor}' sektöründe zaten maximum(2) pozisyon açık!")
            return"""
new_limit = """        hedef_sektor = SEKTORLER.get(sembol, 'Alternatif')
        limit = 5 if hedef_sektor == 'Alternatif' else 2
        if aktif_sektorler.get(hedef_sektor, 0) >= limit:
            print(f"⚠️ [{sembol}] İptal: '{hedef_sektor}' sektöründe zaten maximum({limit}) pozisyon açık!")
            return"""
text = text.replace(old_limit, new_limit)

# 3. Completely replace from analiz_motoru to end
target_index = text.find("def analiz_motoru(hedef_coin):")
header_text = text[:target_index]

new_code = """def analiz_motoru(hedef_coin, beyin):
    # ── Değişken Sızıntısı Önleme ──
    guncel = None
    hedef_fiyat = None
    tahmin_olasilik = None
    yon = None
    df = None
    sl, tp, rr = 0, 0, 0
    btc_dom = 50.0  

    try:
        if makro_volatilite_beklentisi():
            print(f"[{datetime.now().strftime('%H:%M:%S')}] [SİSTEM] Beklemede (Önemli Makro Veri).")
            return

        try:
            df = veri_getir_dortlu(hedef_coin, REF)
        except Exception:
            return

        if df is None or df.empty:
            return

        features = ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'Kriz', 'Haber_Duygu_Puani', 'Faiz_Orani', 'Dolar_Kuru']
        eksik = [f for f in features if f not in df.columns]
        if eksik:
            return

        try:
            tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🧠 {hedef_coin} modeli eğitiliyor...")
                beyin.model_egit(hedef_coin, df, is_crypto=True)
                tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            
            if tahmin_olasilik is None:
                return
        except Exception:
            return

        guncel = float(df['Hedef_Close'].iloc[-1])
        atr = float(df['ATR'].iloc[-1])

        volatilite_katsayisi = (atr / guncel) * 100 
        dinamik_esik = 0.52 + (volatilite_katsayisi * 0.02)
        dinamik_esik = min(0.65, max(0.52, dinamik_esik))

        if tahmin_olasilik > dinamik_esik:
            yon = "YÜKSELİŞ 🚀"
        elif tahmin_olasilik < (1.0 - dinamik_esik):
            yon = "DÜŞÜŞ 📉"
        else:
            yon = "NÖTR ⚖️"
        
        sl_mult = RISK_AYAR["sl_atr_carpani"]
        tp_mult = RISK_AYAR["tp_atr_carpani"]
        
        if "YÜKSELİŞ" in yon:
            sl = guncel - (atr * sl_mult)
            tp = guncel + (atr * tp_mult)
            rr = (tp - guncel) / (guncel - sl) if (guncel - sl) != 0 else 0
        elif "DÜŞÜŞ" in yon:
            sl = guncel + (atr * sl_mult)
            tp = guncel - (atr * tp_mult)
            rr = (guncel - tp) / (sl - guncel) if (sl - guncel) != 0 else 0

        zaman = datetime.now().strftime('%H:%M:%S')
        hedef_fiyat = tp if tp != 0 else guncel
        
        guven_skoru_yuzde = tahmin_olasilik * 100
        if "DÜŞÜŞ" in yon:
            guven_skoru_yuzde = 100 - (tahmin_olasilik * 100)

        if "NÖTR" not in yon:
            if rr >= 1.4:
                print(f"[{zaman}] [{hedef_coin}] Güven: %{guven_skoru_yuzde:.1f} | Dinamik Eşik: %{dinamik_esik*100:.1f} -> DURUM: GİRİŞ UYGUN ({yon})")
            else:
                print(f"[{zaman}] [{hedef_coin}] Güven: %{guven_skoru_yuzde:.1f} | Dinamik Eşik: %{dinamik_esik*100:.1f} -> DURUM: R/R YETERSİZ ({rr:.2f} < 1.4)")

            try:
                btc_dom_req = requests.get("https://api.coingecko.com/api/v3/global", timeout=5)
                btc_dom = float(btc_dom_req.json()["data"]["market_cap_percentage"]["btc"])
            except:
                pass 

        if "NÖTR" not in yon and rr >= 1.4:
            fg_skor, _ = korku_acgozluluk_getir()
            korku_limiti = 10 if dinamik_esik < 0.58 else 18 
            
            if fg_skor < korku_limiti and "YÜKSELİŞ" in yon:
                return

            ana_trend_yon = ana_trend_getir(hedef_coin)
            esneklik_puani = guven_skoru_yuzde - (dinamik_esik * 100)
            if ("YÜKSELİŞ" in yon and ana_trend_yon != "UP") or ("DÜŞÜŞ" in yon and ana_trend_yon != "DOWN"):
                if esneklik_puani < 12.0:
                    return
                else:
                    print(f"[{zaman}] 🦅 {hedef_coin} Özel İzin! (Trend tersine özel sinyal)")

            if "YÜKSELİŞ" in yon and onchain_inflow_durumu("BTC/USDT"):
                if esneklik_puani < 12.0:
                    return
            
            margin_override = None
            if btc_dom > 56.0 and "BTC" not in hedef_coin:
                if guven_skoru_yuzde < 70.0:
                    return
                else:
                    margin_override = 0.02

            p_kelly = tahmin_olasilik if "YÜKSELİŞ" in yon else (1.0 - tahmin_olasilik)
            q_kelly = 1.0 - p_kelly
            b_kelly = rr
            
            kelly_orani = 0.0
            if b_kelly > 0:
                kelly_orani = (p_kelly * b_kelly - q_kelly) / b_kelly
            
            fractional_kelly = max(0.01, min(0.10, kelly_orani * 0.25)) 
            
            if margin_override is not None:
                margin_override = min(0.02, fractional_kelly)
            else:
                margin_override = fractional_kelly

            print(f"[{zaman}] 📐 Kelly Kriteri Hesaplandı -> Önerilen Pozisyon Büyüklüğü: Kasanın %{margin_override*100:.1f}'i")

            msg = f"🚨 *FIRSAT: {hedef_coin}*\n----------------\n🔮 Yön: {yon}\n📈 Güven Skoru: %{guven_skoru_yuzde:.1f}\n💰 Fiyat: {guncel:.2f}$\n🎯 Hedef: {tp:.2f}$\n🛑 İz Süren Stop: Aktif\n⚖️ R/R: {rr:.2f}\n📊 Kelly Kasa: %{margin_override*100:.1f}\n😨 Piyasa: {fg_skor}\n👑 BTC Dom: %{btc_dom:.1f}"
            telegrama_gonder(msg)
            
            islem_ac(yon, hedef_coin, guncel, tp, sl, margin_override)

    except ccxt.NetworkError as ne:
        borsa_baglantisini_yenile(hata_mesaji="Network Error")
    except Exception as e:
        if "ccxt" in str(e).lower() or "binance" in str(e).lower() or "timeout" in str(e).lower():
            borsa_baglantisini_yenile(hata_mesaji="Bilinmeyen CCXT Hatası")

def surekli_tarama_ve_analiz():
    beyin = BeyinMotoru()
    
    while True:
        try:
            print("\\n" + "="*70)
            print(f"🚀 [{datetime.now().strftime('%H:%M:%S')}] AŞAMA 1: SCOUT (Hafif Tarayıcı) Başlıyor...")
            
            tikler = borsa.fetch_tickers()
            
            pozisyonlar = borsa.fetch_positions()
            acik_semboller = [p.get('symbol') for p in pozisyonlar if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0]
            
            adaylar = []
            for sembol, veri in tikler.items():
                if '/USDT' in sembol or 'USDT' in sembol:
                    hacim = float(veri.get('quoteVolume', 0)) if veri.get('quoteVolume') is not None else 0
                    degisim = abs(float(veri.get('percentage', 0))) if veri.get('percentage') is not None else 0
                    
                    if hacim > 50000000:
                        adaylar.append({'sembol': sembol, 'hacim': hacim, 'degisim': degisim})
            
            adaylar.sort(key=lambda x: x['degisim'], reverse=True)
            sicak_coinler = [x['sembol'] for x in adaylar[:15]]
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Dinamik Tarayıcı Devrede: Piyasadan seçilen en sıcak coinler: {sicak_coinler}")
            
            print("\\n🎯 AŞAMA 2: SNIPER (Ağır Analiz) Başlıyor...")
            for coin in sicak_coinler:
                if coin in acik_semboller:
                    continue
                    
                analiz_motoru(coin, beyin)
                time.sleep(3) 
                
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            print(f"[{zaman}] ⚠️ Tarayıcı Hatası: {e}")
            borsa_baglantisini_yenile("Scout Hatası")
            time.sleep(10)
            
        print("\\n⏳ Tarama döngüsü tamamlandı, 5 dakika bekleniyor...")
        time.sleep(300)

def pozisyon_takip_paneli():
    while True:
        try:
            if not TESTNET_API_KEY or not TESTNET_SECRET:
                time.sleep(30)
                continue

            pozisyonlar = borsa.fetch_positions()
            aktifler = []
            for p in pozisyonlar:
                amt = float(p.get('contracts', p.get('info', {}).get('positionAmt', 0)))
                if amt != 0:
                    aktifler.append((p, amt))
            
            bakiye_bilgisi = borsa.fetch_balance()
            toplam_kasa = float(bakiye_bilgisi.get('USDT', {}).get('total', 0.0))
            
            print("\\n" + "="*50)
            if not aktifler:
                print(f"⏳ [{datetime.now().strftime('%H:%M:%S')}] Aktif İşlem Yok. Fırsatlar Taranıyor...")
            else:
                print(f"📊 AÇIK POZİSYONLAR | {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 50)
                
                toplam_pnl = 0
                for p, amt in aktifler:
                    sembol = p.get('symbol', 'Bilinmiyor')
                    guncel = float(p.get('markPrice', p.get('info', {}).get('markPrice', 0)))
                    pnl = float(p.get('unrealizedPnl', p.get('info', {}).get('unRealizedProfit', 0)))
                    toplam_pnl += pnl
                    
                    yon_str = "🟢 LONG" if amt > 0 else "🔴 SHORT"
                    print(f" {sembol:<10} | {yon_str} | Kâr/Zarar: {pnl:+.2f} USDT")
                
                print("-" * 50)
                print(f" KASA: {toplam_kasa:.2f} USDT | TOPLAM PNL: {toplam_pnl:+.2f} USDT")
            print("="*50 + "\\n")
            
        except Exception:
            pass
        
        time.sleep(30)

if __name__ == "__main__":
    print(f"\\n🚀 SİSTEM BAŞLATILIYOR (V7 - Dinamik Tarayıcı Modu)")
    
    t_panel = threading.Thread(target=pozisyon_takip_paneli, daemon=True)
    t_panel.start()
    
    surekli_tarama_ve_analiz()
"""

with open(MAIN_FILE, "w", encoding="utf-8") as f:
    f.write(header_text + new_code)

print("Patching complete!")
