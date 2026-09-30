"""
SECTOR DEEP DIVE v1.0 — Sektör İçi Quant Değerleme & Sıralama Motoru
===================================================================
Belirli bir sektör, tematik havuz veya kullanıcı tanımlı hisse grubunu
çoklu faktör modeliyle (Kalite, Büyüme, Değer, Momentum) derinlemesine analiz eder
ve 3-6-12 aylık vadede en yüksek potansiyele sahip hisseleri 1'den N'e sıralar.
"""

import sys
import io
import argparse
import json
from typing import Dict, List, Optional
import pandas as pd
import numpy as np
import yfinance as yf

from thematic_baskets import tema_getir, tum_temalar, ozel_sepet_olustur

# Windows konsol Unicode ayarı
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass


def _guvenli_float(val, default=0.0):
    try:
        if val is None or np.isnan(val):
            return default
        return float(val)
    except Exception:
        return default


def hisse_metrikleri_hesapla(symbol: str, rol_aciklamasi: str = "") -> Optional[Dict[str, object]]:
    """Tek bir hisse için kapsamlı teknik, temel ve analist verilerini çeker ve skorlar."""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1y")
        if hist.empty or len(hist) < 50:
            return None
            
        cur_price = float(hist['Close'].iloc[-1])
        info = ticker.info or {}
        
        # 1. TEKNİK & MOMENTUM
        ret_3m = (cur_price / hist['Close'].iloc[-63] - 1) * 100 if len(hist) >= 63 else 0.0
        ret_6m = (cur_price / hist['Close'].iloc[-126] - 1) * 100 if len(hist) >= 126 else 0.0
        ret_1y = (cur_price / hist['Close'].iloc[0] - 1) * 100
        
        sma50 = float(hist['Close'].rolling(50).mean().iloc[-1])
        sma200 = float(hist['Close'].rolling(200).mean().iloc[-1]) if len(hist) >= 200 else sma50
        
        # RSI
        delta = hist['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = float(100 - (100 / (1 + rs)).iloc[-1])
        if np.isnan(rsi):
            rsi = 50.0
            
        if cur_price > sma50 > sma200:
            trend = "GÜÇLÜ BOĞA"
            mom_base = 80.0
        elif cur_price > sma200:
            trend = "BOĞA"
            mom_base = 65.0
        else:
            trend = "AYI / DİP"
            mom_base = 40.0
            
        mom_skor = np.clip(mom_base + (ret_6m * 0.2) + (10 if 45 <= rsi <= 65 else 0), 10, 100)
        
        # 2. TEMEL / KALİTE (Quality)
        op_margin = _guvenli_float(info.get("operatingMargins"), 0.15) * 100  # %
        roe = _guvenli_float(info.get("returnOnEquity"), 0.15) * 100          # %
        debt_to_eq = _guvenli_float(info.get("debtToEquity"), 100.0)
        
        kalite_skor = 50.0
        if op_margin > 20:
            kalite_skor += 20
        elif op_margin > 10:
            kalite_skor += 10
            
        if roe > 20:
            kalite_skor += 15
        elif roe > 10:
            kalite_skor += 8
            
        if debt_to_eq < 80:
            kalite_skor += 15
        elif debt_to_eq < 150:
            kalite_skor += 5
        else:
            kalite_skor -= 10
            
        kalite_skor = float(np.clip(kalite_skor, 10, 100))
        
        # 3. BÜYÜME (Growth)
        rev_growth = _guvenli_float(info.get("revenueGrowth"), 0.08) * 100  # %
        earn_growth = _guvenli_float(info.get("earningsGrowth"), 0.10) * 100 # %
        
        buyume_skor = 50.0
        if rev_growth > 25:
            buyume_skor += 30
        elif rev_growth > 12:
            buyume_skor += 20
        elif rev_growth > 5:
            buyume_skor += 10
        else:
            buyume_skor -= 10
            
        if earn_growth > 20:
            buyume_skor += 20
        elif earn_growth > 10:
            buyume_skor += 10
            
        buyume_skor = float(np.clip(buyume_skor, 10, 100))
        
        # 4. DEĞERLEME (Value)
        fwd_pe = _guvenli_float(info.get("forwardPE"), 0.0)
        peg = _guvenli_float(info.get("pegRatio"), 0.0)
        
        deger_skor = 50.0
        if 0 < fwd_pe < 20:
            deger_skor += 25
        elif 20 <= fwd_pe < 32:
            deger_skor += 10
        elif fwd_pe >= 45:
            deger_skor -= 15
            
        if 0 < peg < 1.5:
            deger_skor += 25
        elif 1.5 <= peg < 2.5:
            deger_skor += 10
        elif peg >= 3.0:
            deger_skor -= 10
            
        deger_skor = float(np.clip(deger_skor, 10, 100))
        
        # 5. KOMPOZİT QUANT SKORU (0 - 100)
        # Büyüme & Kalite temelli ağırlıklandırma:
        kompozit = (kalite_skor * 0.30) + (buyume_skor * 0.25) + (deger_skor * 0.20) + (mom_skor * 0.25)
        kompozit = round(float(kompozit), 1)
        
        # 6. ANALİST KONSENSÜSÜ
        target_mean = _guvenli_float(info.get("targetMeanPrice"), 0.0)
        upside = round(((target_mean / cur_price) - 1) * 100, 1) if (target_mean and cur_price) else 0.0
        rec_key = str(info.get("recommendationKey", "N/A")).replace("_", " ").upper()
        
        # 7. SİSTEM KARARI & SETUP
        if kompozit >= 75 and trend == "GÜÇLÜ BOĞA" and rsi <= 68:
            karar = "🟢 AL_ADAYI"
            setup = "LİDER_TREND"
        elif kompozit >= 70 and rsi > 68:
            karar = "🟡 BEKLE_GERİ_ÇEKİLME"
            setup = "AŞIRI_ALIM_DİNLENME"
        elif kompozit >= 65 and trend != "AYI / DİP":
            karar = "🟢 KADEMELİ_BİRİKTİR"
            setup = "BÜYÜME_POTANSİYELİ"
        elif kompozit >= 55:
            karar = "⚪ İZLE"
            setup = "GÖZLEM"
        else:
            karar = "🔴 PAS_GEÇ"
            setup = "ZAYIF_FAKTÖR"
            
        return {
            "Sembol": symbol,
            "Şirket": info.get("shortName", symbol),
            "Rol": rol_aciklamasi or info.get("industry", "Sektör Hissesi"),
            "Fiyat": round(cur_price, 2),
            "Piyasa Değ. ($B)": round(_guvenli_float(info.get("marketCap")) / 1e9, 1),
            "Kompozit Skor": kompozit,
            "Kalite": round(kalite_skor, 1),
            "Büyüme": round(buyume_skor, 1),
            "Değer": round(deger_skor, 1),
            "Momentum": round(mom_skor, 1),
            "3A Getiri (%)": round(ret_3m, 1),
            "6A Getiri (%)": round(ret_6m, 1),
            "1Y Getiri (%)": round(ret_1y, 1),
            "RSI": round(rsi, 1),
            "Trend": trend,
            "Fwd F/K": round(fwd_pe, 1) if fwd_pe > 0 else "-",
            "Ciro Büyüme (%)": round(rev_growth, 1) if rev_growth else "-",
            "Hedef Fiyat ($)": round(target_mean, 2) if target_mean > 0 else "-",
            "Analist Potansiyeli (%)": upside,
            "Tavsiye": rec_key,
            "Karar": karar,
            "Setup": setup
        }
    except Exception as e:
        print(f"Uyarı: {symbol} verisi işlenirken hata: {e}")
        return None


def sektor_derinlik_analizi(semboller: List[str], roller: Dict[str, str] = None) -> pd.DataFrame:
    """Tüm sembol listesi için paralel/sıralı faktör analizi yapar ve sıralar."""
    if roller is None:
        roller = {}
        
    print(f"\n⚡ Toplam {len(semboller)} hisse quant faktör motoruna alınıyor...")
    sonuclar = []
    
    for s in semboller:
        rol = roller.get(s, "")
        veri = hisse_metrikleri_hesapla(s, rol)
        if veri:
            sonuclar.append(veri)
            
    if not sonuclar:
        return pd.DataFrame()
        
    df = pd.DataFrame(sonuclar)
    # Kompozit skora göre büyükten küçüğe sırala
    df = df.sort_values(by=["Kompozit Skor", "Analist Potansiyeli (%)"], ascending=[False, False]).reset_index(drop=True)
    df.index = df.index + 1  # 1'den başlasın
    return df


def derinlik_raporu_yazdir(df: pd.DataFrame, baslik: str):
    """Konsola profesyonel kurumsal derinlik raporu basar."""
    print("\n" + "=" * 135)
    print(f"        KURUMSAL DERİNLİK ANALİZİ & LİDER TABLOSU: {baslik.upper()}")
    print("=" * 135)
    
    fmt = "{:<3} | {:<6} | {:<28} | {:>8} | {:>6} | {:>6} | {:>6} | {:>6} | {:>6} | {:<10} | {:>9} | {:<18}"
    print(fmt.format("#", "Kod", "Şirket / Rol", "Fiyat", "Skor", "Kalite", "Büy.", "Değ.", "Mom.", "Trend", "Potansiyel", "Sistem Kararı"))
    print("-" * 135)
    
    for idx, r in df.iterrows():
        print(fmt.format(
            idx,
            r["Sembol"],
            r["Rol"][:28] if r["Rol"] else r["Şirket"][:28],
            f"${r['Fiyat']}",
            f"{r['Kompozit Skor']}",
            f"{r['Kalite']}",
            f"{r['Büyüme']}",
            f"{r['Değer']}",
            f"{r['Momentum']}",
            r["Trend"],
            f"%{r['Analist Potansiyeli (%)']}",
            r["Karar"]
        ))
    print("=" * 135)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sektör İçi Quant Değerleme & Sıralama Motoru")
    parser.add_argument("--tema", type=str, help="Analiz edilecek tematik havuz kodu (örn: ai_enerji, yari_iletken, siber_guvenlik)")
    parser.add_argument("--semboller", type=str, help="Virgülle ayrılmış özel hisse listesi (örn: NVDA,AMD,AVGO)")
    parser.add_argument("--liste", action="store_true", help="Kayıtlı tüm tematik havuzları listeler")
    parser.add_argument("--json", action="store_true", help="Çıktıyı JSON formatında verir")
    
    args = parser.parse_args()
    
    if args.liste:
        print("\n=== KAYITLI TEMATİK HAVUZLAR ===")
        for kod, ad in tum_temalar().items():
            print(f"  • {kod:<25} -> {ad}")
        sys.exit(0)
        
    sembol_listesi = []
    roller = {}
    baslik = "ÖZEL HAVUZ"
    
    if args.tema:
        havuz = tema_getir(args.tema)
        if not havuz:
            print(f"🚨 Hata: '{args.tema}' adında bir tema bulunamadı! Mevcut temaları görmek için --liste kullanın.")
            sys.exit(1)
        sembol_listesi = havuz.get("semboller", [])
        roller = havuz.get("odak_alanlari", {})
        baslik = str(havuz.get("ad", args.tema))
    elif args.semboller:
        sembol_listesi = [s.strip().upper() for s in args.semboller.split(",") if s.strip()]
        baslik = f"ÖZEL HİSSE LİSTESİ ({len(sembol_listesi)} Sembol)"
    else:
        # Varsayılan: AI Enerji
        havuz = tema_getir("AI_ENERJI_GUC")
        sembol_listesi = havuz.get("semboller", [])
        roller = havuz.get("odak_alanlari", {})
        baslik = str(havuz.get("ad"))
        
    df_sonuc = sektor_derinlik_analizi(sembol_listesi, roller)
    
    if args.json:
        print(df_sonuc.to_json(orient="records", force_ascii=False, indent=2))
    else:
        derinlik_raporu_yazdir(df_sonuc, baslik)
