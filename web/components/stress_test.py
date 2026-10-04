"""
StockPredictionPro — Portföy Stres Testi & Yoğunlaşma Röntgeni
Açık pozisyonlar üzerinden sektör yoğunlaşması, hisseler arası korelasyon,
portföy betası ve tarihsel piyasa kriz şok simülasyonları.
"""
import numpy as np
import pandas as pd
import yfinance as yf
import streamlit as st


@st.cache_data(ttl=600)
def get_historical_returns(symbols: tuple, benchmark: str = "SPY", period: str = "1y"):
    """
    Portföy hisselerinin ve benchmark'ın (SPY) 1 yıllık günlük getirilerini çeker.
    """
    all_syms = list(set(list(symbols) + [benchmark]))
    try:
        data = yf.download(all_syms, period=period, progress=False, group_by="ticker")
        closes = pd.DataFrame()
        for s in all_syms:
            try:
                if len(all_syms) == 1:
                    closes[s] = data["Close"]
                elif s in data and "Close" in data[s]:
                    closes[s] = data[s]["Close"]
            except Exception:
                pass
        closes = closes.dropna(how="all").ffill().dropna()
        returns = closes.pct_change().dropna()
        return returns
    except Exception:
        return pd.DataFrame()


def calculate_portfolio_metrics(open_positions: dict, live_quotes: dict, benchmark: str = "SPY"):
    """
    Portföy ağırlıklarını, hisse betalarını, portföy betasını
    ve korelasyon matrisini hesaplar.
    """
    symbols = list(open_positions.keys())
    if not symbols:
        return None

    # Değerler ve Ağırlıklar
    values = {}
    total_val = 0.0
    for sym, p in open_positions.items():
        cur_p = live_quotes.get(sym, {}).get("price") or p["ortalama_fiyat_usd"]
        val = p["toplam_adet"] * cur_p
        values[sym] = val
        total_val += val

    if total_val <= 0:
        return None

    weights = {s: values[s] / total_val for s in symbols}

    # Tarihsel Getiriler
    ret_df = get_historical_returns(tuple(symbols), benchmark=benchmark, period="1y")

    betas = {}
    corr_matrix = pd.DataFrame()
    portfolio_beta = 1.25  # varsayılan

    if not ret_df.empty and benchmark in ret_df.columns:
        bench_ret = ret_df[benchmark]
        bench_var = bench_ret.var()

        for s in symbols:
            if s in ret_df.columns:
                cov = ret_df[s].cov(bench_ret)
                b = (cov / bench_var) if bench_var > 0 else 1.0
                betas[s] = round(float(b), 2)
            else:
                betas[s] = 1.30

        # Portföy Ağırlıklı Betası
        portfolio_beta = sum(weights.get(s, 0) * betas.get(s, 1.2) for s in symbols)

        # Korelasyon Matrisi (sadece portföy hisseleri)
        sym_in_df = [s for s in symbols if s in ret_df.columns]
        if len(sym_in_df) >= 2:
            corr_matrix = ret_df[sym_in_df].corr().round(2)

    return {
        "total_value_usd": total_val,
        "weights": weights,
        "betas": betas,
        "portfolio_beta": round(portfolio_beta, 2),
        "correlation_matrix": corr_matrix,
    }


def run_stress_scenarios(portfolio_value_usd: float, portfolio_beta: float, usdtry: float):
    """
    Kritik piyasa şok senaryolarını simüle eder ve dolar/TL kaybını hesaplar.
    """
    scenarios = [
        {
            "isim": "📉 2022 Fed Faiz & Teknoloji Satışı",
            "aciklama": "S&P 500 %-18, Nasdaq %-33, Yarıiletkenler %-36 gerilediğinde.",
            "piyasa_sok": -0.22,
            "portfoy_tahmini_kayip_pct": min(-0.10, -0.22 * portfolio_beta),
        },
        {
            "isim": "⚡ Ani Resesyon / Panik Satışı (VIX 35+)",
            "aciklama": "Piyasa geneli sert likidasyon dalgası, S&P 500 %-15 düştüğünde.",
            "piyasa_sok": -0.15,
            "portfoy_tahmini_kayip_pct": min(-0.08, -0.15 * portfolio_beta),
        },
        {
            "isim": "🔄 AI & Çip Döngüsel Düzeltmesi",
            "aciklama": "AI balonu/döngü endişesiyle yarıiletken fonlarının (SOXX) %-25 düzeltmesi.",
            "piyasa_sok": -0.25,
            # Çip ağırlıklı portföy doğrudan çip şokunu emer
            "portfoy_tahmini_kayip_pct": -0.25 * max(1.0, portfolio_beta * 0.8),
        },
        {
            "isim": "🛡️ Hafif Düzeltme & Sağlıklı Kâr Satışı",
            "aciklama": "Zirveden 50 günlük ortalamalara %-5 ila %-8 normal geri çekilme.",
            "piyasa_sok": -0.06,
            "portfoy_tahmini_kayip_pct": -0.06 * portfolio_beta,
        },
    ]

    results = []
    for sc in scenarios:
        pct = sc["portfoy_tahmini_kayip_pct"]
        kayip_usd = portfolio_value_usd * pct
        yeni_deger_usd = portfolio_value_usd + kayip_usd
        kayip_tl = kayip_usd * usdtry
        yeni_deger_tl = yeni_deger_usd * usdtry

        results.append({
            "Senaryo": sc["isim"],
            "Açıklama": sc["aciklama"],
            "Beklenen Portföy Değişimi": f"%{pct * 100:.1f}",
            "Tahmini Kayıp ($)": f"${kayip_usd:,.2f}",
            "Tahmini Kayıp (₺)": f"{kayip_tl:,.0f} ₺",
            "Kalan Portföy ($)": f"${yeni_deger_usd:,.2f}",
        })

    return results
