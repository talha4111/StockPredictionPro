"""
StockPredictionPro — Portföy Risk Komuta Merkezi, Stres Testi & Yoğunlaşma Röntgeni
- Mod #3: Portföy VaR (Value at Risk), Expected Shortfall (Kuyruk Riski), Maksimum Düşüş
- Portföy + Takip Listesi Korelasyon Isı Haritası ("İkiz hareket eden hisseler" uyarısı)
- Volatiliteye Göre Pozisyon Büyüklüğü Önerisi (Position Sizing)
- Tarihsel ve Sektörel Şok Stres Testleri (Piyasa -%5, Teknoloji/Çip -%10, Kriz senaryoları)
"""
import numpy as np
import pandas as pd
import yfinance as yf

try:
    import streamlit as st
    _cache_data = st.cache_data
except Exception:
    def _cache_data(**_kwargs):
        def _wrap(fn):
            return fn
        return _wrap


@_cache_data(ttl=600, show_spinner=False)
def get_historical_returns(symbols: tuple, benchmark: str = "SPY", period: str = "1y"):
    """
    Portföy/takip hisselerinin ve benchmark'ın (SPY) 1 yıllık günlük getirilerini çeker.
    """
    all_syms = list(dict.fromkeys(list(symbols) + [benchmark]))
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


def calculate_portfolio_metrics(
    open_positions: dict,
    live_quotes: dict,
    watchlist_symbols: list[str] | None = None,
    benchmark: str = "SPY",
):
    """
    Portföy ağırlıklarını, hisse betalarını, portföy betasını,
    VaR (%95), Expected Shortfall, Maksimum Düşüş, korelasyon matrisini
    ve volatiliteye göre ideal pozisyon büyüklüklerini hesaplar.
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

    # Korelasyon ve pozisyon büyüklüğü için hem portföy hem takip listesini birleştir
    extra_syms = watchlist_symbols or ["MU", "COHR", "MRVL", "RKLB", "VST", "AVGO"]
    combined_syms = list(dict.fromkeys(symbols + extra_syms))

    ret_df = get_historical_returns(tuple(combined_syms), benchmark=benchmark, period="1y")

    betas = {}
    vols_annual = {}
    corr_matrix = pd.DataFrame()
    portfolio_beta = 1.25
    var_95_pct = -0.032
    cvar_95_pct = -0.048
    max_dd_pct = -0.18
    high_corr_pairs = []
    sizing_rows = []

    if not ret_df.empty and benchmark in ret_df.columns:
        bench_ret = ret_df[benchmark]
        bench_var = bench_ret.var()

        for s in combined_syms:
            if s in ret_df.columns:
                cov = ret_df[s].cov(bench_ret)
                b = (cov / bench_var) if bench_var > 0 else 1.0
                betas[s] = round(float(b), 2)
                vol_d = float(ret_df[s].std())
                vols_annual[s] = round(vol_d * np.sqrt(252) * 100.0, 1)
            else:
                betas[s] = 1.30
                vols_annual[s] = 45.0

        # Portföy Ağırlıklı Betası ve Portföy Günlük Getiri Serisi
        portfolio_beta = sum(weights.get(s, 0) * betas.get(s, 1.2) for s in symbols)

        port_syms_in_df = [s for s in symbols if s in ret_df.columns]
        if port_syms_in_df:
            port_daily_ret = sum(ret_df[s] * weights[s] for s in port_syms_in_df)
            var_95_pct = float(np.percentile(port_daily_ret, 5))
            tail_losses = port_daily_ret[port_daily_ret <= var_95_pct]
            cvar_95_pct = float(tail_losses.mean()) if len(tail_losses) > 0 else var_95_pct * 1.35

            cum_curve = (1.0 + port_daily_ret).cumprod()
            peak_curve = cum_curve.cummax()
            dd_series = (cum_curve - peak_curve) / peak_curve
            max_dd_pct = float(dd_series.min())

        # Korelasyon Matrisi (Portföyde tek hisse olsa bile takip listesiyle birlikte göster!)
        sym_in_df = [s for s in combined_syms if s in ret_df.columns]
        if len(sym_in_df) >= 2:
            corr_matrix = ret_df[sym_in_df].corr().round(2)
            for i in range(len(sym_in_df)):
                for j in range(i + 1, len(sym_in_df)):
                    s1, s2 = sym_in_df[i], sym_in_df[j]
                    c_val = float(corr_matrix.loc[s1, s2])
                    if c_val >= 0.60:
                        high_corr_pairs.append((s1, s2, round(c_val * 100)))

        # Volatiliteye Göre Pozisyon Büyüklüğü Önerisi (Hedef: tek hissede günlük sarsıntı portföyü yıkmasın)
        for s in combined_syms:
            ann_vol = vols_annual.get(s, 45.0)
            beta_s = betas.get(s, 1.3)
            # Yıllık volatilitesi %30 olan hisseye max %25, %60 olan hisseye max %12.5 ağırlık önerisi
            rec_max_weight = round(min(28.0, max(8.0, (35.0 / max(ann_vol, 15.0)) * 22.0)), 1)
            risk_label = (
                "🔴 Çok Oynak (Küçük Lot Gir)"
                if ann_vol >= 55 or beta_s >= 1.6
                else ("🟡 Orta-Yüksek Oynaklık" if ann_vol >= 38 else "🟢 Dengeli Oynaklık")
            )
            sizing_rows.append({
                "Hisse": s,
                "Durum": "💼 Portföyde" if s in symbols else "👀 Takip Listesinde",
                "S&P 500 Betası": f"{beta_s:.2f}x",
                "Yıllık Dalgalanma (Volatilite)": f"%{ann_vol:.1f}",
                "Önerilen Maksimum Portföy Payı": f"En fazla %{rec_max_weight:.0f}",
                "Risk Notu": risk_label,
            })

    return {
        "total_value_usd": total_val,
        "weights": weights,
        "betas": betas,
        "portfolio_beta": round(portfolio_beta, 2),
        "var_95_pct": round(var_95_pct * 100.0, 2),
        "var_95_usd": round(total_val * abs(var_95_pct), 2),
        "cvar_95_pct": round(cvar_95_pct * 100.0, 2),
        "cvar_95_usd": round(total_val * abs(cvar_95_pct), 2),
        "max_dd_pct": round(max_dd_pct * 100.0, 1),
        "correlation_matrix": corr_matrix,
        "high_corr_pairs": sorted(high_corr_pairs, key=lambda x: x[2], reverse=True),
        "sizing_table": sizing_rows,
    }


def run_stress_scenarios(portfolio_value_usd: float, portfolio_beta: float, usdtry: float):
    """
    Kritik piyasa ve sektör şok senaryolarını simüle eder ve dolar/TL kaybını hesaplar.
    """
    scenarios = [
        {
            "isim": "📉 Piyasa Düzeltmesi (S&P 500 -%5)",
            "aciklama": "Borsa genelinde orta ölçekli bir satış dalgası (-%5) yaşandığında.",
            "portfoy_tahmini_kayip_pct": -0.05 * portfolio_beta,
        },
        {
            "isim": "🔌 Teknoloji & Çip Satışı (Sektör -%10)",
            "aciklama": "Bilanço sezonu veya sektör rotasyonuyla çip/teknoloji hisseleri -%10 düştüğünde.",
            "portfoy_tahmini_kayip_pct": -0.10 * max(1.0, portfolio_beta * 0.85),
        },
        {
            "isim": "🔄 AI & Yarı İletken Sert Düzeltmesi (-%20)",
            "aciklama": "Ekim ortasında yaşanan gibi çip sektöründe sert kâr realizasyonu dalgası.",
            "portfoy_tahmini_kayip_pct": -0.20 * max(1.0, portfolio_beta * 0.80),
        },
        {
            "isim": "⚡ Ani Panik / Korku Sıçraması (VIX 35+, Borsa -%15)",
            "aciklama": "Jeopolitik kriz veya faiz şokuyla küresel borsalarda panik satışı.",
            "portfoy_tahmini_kayip_pct": min(-0.08, -0.15 * portfolio_beta),
        },
    ]

    results = []
    for sc in scenarios:
        pct = sc["portfoy_tahmini_kayip_pct"]
        kayip_usd = portfolio_value_usd * pct
        yeni_deger_usd = portfolio_value_usd + kayip_usd
        kayip_tl = kayip_usd * usdtry

        results.append({
            "Senaryo": sc["isim"],
            "Açıklama": sc["aciklama"],
            "Beklenen Portföy Değişimi": f"%{pct * 100:.1f}",
            "Tahmini Kayıp ($)": f"${kayip_usd:,.2f}",
            "Tahmini Kayıp (₺)": f"{kayip_tl:,.0f} ₺",
            "Kalan Portföy ($)": f"${yeni_deger_usd:,.2f}",
        })

    return results
