"""
SECTOR MACRO RADAR v1.0 — Sektör Rotasyonu & Makro Trend Radarı
==============================================================
3, 6 ve 12 aylık zaman ufuklarında ABD borsa sektörlerini SPY endeksine karşı
Göreceli Güç (Relative Strength) ve RRG (Relative Rotation Graph) mantığıyla analiz eder.
Paranın hangi sektörlere aktığını ve önümüzdeki 3-12 ayda hangi temaların öne çıkacağını belirler.
"""

import sys
import io
import argparse
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

# Windows konsol Unicode ayarı
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

# Sektör ETF Evreni
SEKTORLER: Dict[str, str] = {
    "SMH": "Yarı İletkenler & Çip Tasarım",
    "XLK": "Bilgi Teknolojileri & Yazılım",
    "XLU": "Kamu Hizmetleri & AI Güç Altyapısı",
    "XLI": "Sanayi, İletim & Altyapı İnşaatı",
    "XLE": "Klasik Enerji (Petrol, Doğalgaz)",
    "XLF": "Finans, Bankacılık & Sigorta",
    "XLV": "Sağlık, Biyoteknoloji & İlaç",
    "XLB": "Temel Maddeler, Kimya & Metaller",
    "XLY": "Tüketici İsteğe Bağlı (Amazon/Tesla)",
    "XLP": "Temel Tüketim & Defansif Perakende",
    "XLC": "İletişim Servisleri (Google/Meta)",
    "XLRE": "Gayrimenkul Yatırım Ortaklıkları (REITs)"
}

BENCHMARK = "SPY"


def sektor_rotasyon_verisi_cek() -> pd.DataFrame:
    """Tüm sektör ETF'leri ve SPY için son 1 yıllık kapanış verilerini çeker."""
    tum_semboller = list(SEKTORLER.keys()) + [BENCHMARK]
    df = yf.download(tum_semboller, period="1y", interval="1d", progress=False)
    
    if isinstance(df.columns, pd.MultiIndex):
        closes = df['Close']
    else:
        closes = df
        
    return closes.ffill().dropna()


def rrg_hesapla(closes: pd.DataFrame, etf: str) -> Tuple[float, float, str]:
    """
    Sektör ETF'sinin SPY'a karşı RS-Ratio ve RS-Momentum değerlerini hesaplar.
    Döndürür: (rs_ratio, rs_momentum, kadran)
    """
    if etf not in closes.columns or BENCHMARK not in closes.columns:
        return 100.0, 100.0, "BİLİNMİYOR"
        
    # Göreceli Fiyat (RS)
    rs = closes[etf] / closes[BENCHMARK]
    
    # 50 günlük ortalamaya normalize edilmiş RS-Ratio
    rs_mean_50 = rs.rolling(window=50).mean()
    rs_ratio = (rs / rs_mean_50) * 100.0
    
    # RS-Ratio'nun 20 günlük momentumu
    rs_ratio_mean_20 = rs_ratio.rolling(window=20).mean()
    rs_momentum = (rs_ratio / rs_ratio_mean_20) * 100.0
    
    son_ratio = float(rs_ratio.iloc[-1])
    son_mom = float(rs_momentum.iloc[-1])
    
    if son_ratio >= 100.0 and son_mom >= 100.0:
        kadran = "LİDER (Leading)"
    elif son_ratio >= 100.0 and son_mom < 100.0:
        kadran = "ZAYIFLAYAN (Weakening)"
    elif son_ratio < 100.0 and son_mom < 100.0:
        kadran = "GERİDE KALAN (Lagging)"
    else:
        kadran = "GELİŞEN / TOPARLANAN (Improving)"
        
    return son_ratio, son_mom, kadran


def sektor_radari_calistir() -> pd.DataFrame:
    """
    Tüm sektörlerin 3M, 6M, 12M performanslarını ve RRG kadranlarını hesaplar,
    Makro Strateji önerisi ile sıralı bir DataFrame üretir.
    """
    closes = sektor_rotasyon_verisi_cek()
    spy_closes = closes[BENCHMARK]
    
    # SPY Getirileri
    spy_cur = spy_closes.iloc[-1]
    spy_3m = (spy_cur / spy_closes.iloc[-63] - 1) * 100 if len(spy_closes) >= 63 else 0
    spy_6m = (spy_cur / spy_closes.iloc[-126] - 1) * 100 if len(spy_closes) >= 126 else 0
    spy_1y = (spy_cur / spy_closes.iloc[0] - 1) * 100
    
    sonuclar = []
    
    for etf, ad in SEKTORLER.items():
        if etf not in closes.columns:
            continue
            
        s_closes = closes[etf]
        cur = s_closes.iloc[-1]
        
        ret_3m = (cur / s_closes.iloc[-63] - 1) * 100 if len(s_closes) >= 63 else 0
        ret_6m = (cur / s_closes.iloc[-126] - 1) * 100 if len(s_closes) >= 126 else 0
        ret_1y = (cur / s_closes.iloc[0] - 1) * 100
        
        # SPY Alfa (Excess Return)
        alfa_3m = ret_3m - spy_3m
        alfa_6m = ret_6m - spy_6m
        alfa_1y = ret_1y - spy_1y
        
        # Hareketli Ortalamalar
        sma50 = s_closes.rolling(50).mean().iloc[-1]
        sma200 = s_closes.rolling(200).mean().iloc[-1]
        trend = "GÜÇLÜ BOĞA" if cur > sma50 > sma200 else ("BOĞA" if cur > sma200 else "AYI / ZAYIF")
        
        # RRG Kadranı
        rs_ratio, rs_mom, kadran = rrg_hesapla(closes, etf)
        
        # Makro Tahsis Önerisi
        if "LİDER" in kadran or "GELİŞEN" in kadran:
            if ret_6m > 0 and cur > sma50:
                oneri = "🟢 AĞIRLIK ARTIR (Overweight)"
            else:
                oneri = "🟡 TAKİBE AL / SEÇİCİ AL"
        elif "ZAYIFLAYAN" in kadran:
            oneri = "🟡 NÖTR / KÂR AL (Market Weight)"
        else:
            oneri = "🔴 AĞIRLIK AZALT (Underweight)"
            
        sonuclar.append({
            "ETF": etf,
            "Sektör": ad,
            "Fiyat": round(cur, 2),
            "3A Getiri (%)": round(ret_3m, 1),
            "6A Getiri (%)": round(ret_6m, 1),
            "1Y Getiri (%)": round(ret_1y, 1),
            "3A Alfa (vs SPY)": round(alfa_3m, 1),
            "6A Alfa (vs SPY)": round(alfa_6m, 1),
            "Trend": trend,
            "Kadran (RRG)": kadran,
            "Makro Strateji": oneri,
            "_skor": (alfa_3m * 0.4) + (alfa_6m * 0.4) + (alfa_1y * 0.2)
        })
        
    df_res = pd.DataFrame(sonuclar)
    df_res = df_res.sort_values(by="_skor", ascending=False).drop(columns=["_skor"])
    return df_res


def raporu_yazdir(df: pd.DataFrame):
    """Konsola profesyonel kurumsal makro raporu basar."""
    print("=" * 115)
    print("                      ABD SEKTÖR ROTASYONU & MAKRO TREND RADARI (3M - 6M - 12M)")
    print("=" * 115)
    
    fmt = "{:<5} | {:<32} | {:>7} | {:>7} | {:>7} | {:<12} | {:<25} | {:<28}"
    print(fmt.format("ETF", "Sektör Adı", "3A Get.", "6A Get.", "1Y Get.", "Trend", "RRG Rotasyon Kadranı", "3-12 Aylık Makro Strateji"))
    print("-" * 115)
    
    for _, r in df.iterrows():
        print(fmt.format(
            r["ETF"],
            r["Sektör"][:32],
            f"%{r['3A Getiri (%)']}",
            f"%{r['6A Getiri (%)']}",
            f"%{r['1Y Getiri (%)']}",
            r["Trend"],
            r["Kadran (RRG)"],
            r["Makro Strateji"]
        ))
    print("=" * 115)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ABD Sektör Rotasyon & Makro Radarı")
    parser.add_argument("--json", action="store_true", help="Çıktıyı JSON formatında bas")
    args = parser.parse_args()
    
    df_rapor = sektor_radari_calistir()
    
    if args.json:
        print(df_rapor.to_json(orient="records", force_ascii=False, indent=2))
    else:
        raporu_yazdir(df_rapor)
