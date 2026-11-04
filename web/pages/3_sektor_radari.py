"""
Sayfa 3: Sektör & Makro Radarı (Sector Radar)
Sektörel rotasyon grafiği, performans tablosu ve tematik sepetler.
"""
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import yfinance as yf
import pandas as pd
import numpy as np
import sys
import os
import sqlite3

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

try:
    from stock_value_engine import vix_oku, sektor_rotasyonu_radar
    ENGINE_AVAILABLE = True
except ImportError:
    ENGINE_AVAILABLE = False

# ─── Sektör ETF Tanımları ───
SECTOR_ETFS = {
    "XLK": "Teknoloji",
    "XLU": "Kamu Hizmetleri (AI Enerji)",
    "XLF": "Finans",
    "XLE": "Enerji (Petrol/Gaz)",
    "XLV": "Sağlık",
    "XLI": "Endüstriyel",
    "XLC": "İletişim",
    "XLY": "Tüketici (İsteğe Bağlı)",
    "XLRE": "Gayrimenkul",
    "XLP": "Tüketici (Temel)",
    "XLB": "Malzeme",
}

THEMATIC_BASKETS = {
    "AI Power & Enerji": ["BE", "VST", "CEG", "NRG", "FSLR", "NEE"],
    "Yarı İletken (Çip)": ["NVDA", "AVGO", "AMD", "MU", "MRVL", "QCOM", "LRCX", "AMAT"],
    "Veri Merkezi Altyapı": ["DELL", "HPE", "SMCI", "VRT", "COHR"],
    "Siber Güvenlik": ["CRWD", "PANW", "FTNT", "ZS", "S"],
    "Bulut & SaaS": ["MSFT", "AMZN", "GOOGL", "NOW", "SNOW", "DDOG"],
}

@st.cache_data(ttl=900)
def sektor_performans_tablosu():
    """11 sektör ETF'inin 1H, 1A, 3A performansını ve RSI'ını paralel hesaplar (15 dk önbellekli)."""
    results = []
    etf_list = list(SECTOR_ETFS.keys())
    raw_batch = None
    try:
        raw_batch = yf.download(etf_list, period="3mo", progress=False, threads=True, group_by="ticker")
    except Exception:
        raw_batch = None

    for ticker, name in SECTOR_ETFS.items():
        try:
            data = pd.DataFrame()
            if raw_batch is not None and not raw_batch.empty:
                if ticker in raw_batch.columns.get_level_values(0):
                    data = raw_batch[ticker].dropna(subset=["Close"])
            if data.empty or len(data) < 20:
                data = yf.Ticker(ticker).history(period="3mo")
            if len(data) < 20:
                continue

            current = float(data['Close'].iloc[-1])
            wk_ago = float(data['Close'].iloc[-6]) if len(data) >= 6 else float(data['Close'].iloc[0])
            mo_ago = float(data['Close'].iloc[-21]) if len(data) >= 21 else float(data['Close'].iloc[0])
            q_start = float(data['Close'].iloc[0])

            wk_ret = ((current - wk_ago) / wk_ago) * 100
            mo_ret = ((current - mo_ago) / mo_ago) * 100
            q_ret = ((current - q_start) / q_start) * 100

            # RSI
            delta = data['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = float((100 - (100 / (1 + rs))).iloc[-1])

            results.append({
                "Sektör": name,
                "ETF": ticker,
                "Fiyat": round(current, 2),
                "1 Hafta (%)": round(wk_ret, 2),
                "1 Ay (%)": round(mo_ret, 2),
                "3 Ay (%)": round(q_ret, 2),
                "RSI": round(rsi, 1),
            })
        except Exception:
            pass

    if not results:
        return pd.DataFrame()

    return pd.DataFrame(results).sort_values("1 Ay (%)", ascending=False)

def sektor_scatter(df):
    """Sektör rotasyon scatter grafiği (1 Hafta vs 1 Ay performansı)."""
    fig = go.Figure()

    for _, row in df.iterrows():
        color = '#00c853' if row['1 Ay (%)'] > 0 else '#f44336'
        fig.add_trace(go.Scatter(
            x=[row['1 Ay (%)']],
            y=[row['1 Hafta (%)']],
            mode='markers+text',
            marker=dict(size=max(15, abs(row['1 Ay (%)']) * 5), color=color, opacity=0.7),
            text=[row['ETF']],
            textposition='top center',
            textfont=dict(size=11, color='#ccd6f6'),
            name=row['Sektör'],
            hovertemplate=f"<b>{row['Sektör']}</b><br>1 Hafta: %{row['1 Hafta (%)']:.2f}<br>1 Ay: %{row['1 Ay (%)']:.2f}<br>RSI: {row['RSI']}<extra></extra>",
        ))

    # Çeyrek çizgileri
    fig.add_hline(y=0, line_dash='dash', line_color='#2a2a4a', line_width=1)
    fig.add_vline(x=0, line_dash='dash', line_color='#2a2a4a', line_width=1)

    # Kadran etiketleri
    fig.add_annotation(x=df['1 Ay (%)'].max() * 0.7, y=df['1 Hafta (%)'].max() * 0.8,
                       text="LEADING ✅", showarrow=False, font=dict(color='#00c853', size=14))
    fig.add_annotation(x=df['1 Ay (%)'].min() * 0.7, y=df['1 Hafta (%)'].max() * 0.8,
                       text="IMPROVING 📈", showarrow=False, font=dict(color='#ff9800', size=14))
    fig.add_annotation(x=df['1 Ay (%)'].min() * 0.7, y=df['1 Hafta (%)'].min() * 0.8,
                       text="LAGGING ⛔", showarrow=False, font=dict(color='#f44336', size=14))
    fig.add_annotation(x=df['1 Ay (%)'].max() * 0.7, y=df['1 Hafta (%)'].min() * 0.8,
                       text="WEAKENING ⚠️", showarrow=False, font=dict(color='#9c27b0', size=14))

    fig.update_layout(
        xaxis_title="1 Aylık Performans (%)",
        yaxis_title="1 Haftalık Performans (%)",
        height=500,
        template='plotly_dark',
        showlegend=False,
        margin=dict(l=50, r=20, t=20, b=50),
    )
    return fig

COMPANY_NAMES = {
    # Yarı İletken (Çip)
    "NVDA": "NVIDIA Corp.", "AVGO": "Broadcom Inc.", "AMD": "Advanced Micro Devices",
    "MU": "Micron Technology", "MRVL": "Marvell Technology", "QCOM": "Qualcomm Inc.",
    "LRCX": "Lam Research", "AMAT": "Applied Materials",
    # AI Power & Enerji
    "BE": "Bloom Energy", "VST": "Vistra Corp", "CEG": "Constellation Energy",
    "NRG": "NRG Energy", "FSLR": "First Solar", "NEE": "NextEra Energy",
    # Veri Merkezi Altyapı
    "DELL": "Dell Technologies", "HPE": "Hewlett Packard Enterprise", "SMCI": "Super Micro Computer",
    "VRT": "Vertiv Holdings", "COHR": "Coherent Corp",
    # Siber Güvenlik
    "CRWD": "CrowdStrike Holdings", "PANW": "Palo Alto Networks", "FTNT": "Fortinet Inc.",
    "ZS": "Zscaler Inc.", "S": "SentinelOne",
    # Bulut & SaaS
    "MSFT": "Microsoft Corp.", "AMZN": "Amazon.com Inc.", "GOOGL": "Alphabet Inc. (Google)",
    "NOW": "ServiceNow Inc.", "SNOW": "Snowflake Inc.", "DDOG": "Datadog Inc."
}

@st.cache_data(ttl=300)
def tematik_sepet_tablosu(basket_name, tickers):
    """Tematik sepetteki hisseleri güncel tarama ve toplu fiyat çekimiyle hızlıca tarar (5 dk önbellekli)."""
    from web.components.mobile import get_db_symbol_data, get_cached_quotes

    t_tuple = tuple(tickers)
    db_data = get_db_symbol_data(t_tuple)
    quotes = get_cached_quotes(t_tuple)

    results = []
    badge_map = {
        'AL_ADAYI': '🟢 AL ADAYI',
        'PAPER_TOP20': '🟢 PAPER TOP 20',
        'KALITELI_GERI_CEKILME': '🟡 GERİ ÇEKİLME',
        'BEKLE': '🟡 BEKLE',
        'IZLE': '🔵 İZLE',
        'REDDET': '🔴 UZAK DUR',
        'OLAY_RISKI': '🟣 BİLANÇO/RİSK',
    }

    for t in tickers:
        q = quotes.get(t, {})
        price = float(q.get("price", 0.0) or 0.0)
        change_pct = float(q.get("change_pct", 0.0) or 0.0)

        db_item = db_data.get(t, {})
        if (not price or price <= 0) and db_item.get('db_fiyat'):
            price = float(db_item['db_fiyat'])

        decision = db_item.get('decision') or 'IZLE'
        score = db_item.get('score')
        score_str = f"%{score:.1f}" if score is not None else "—"

        chg_emoji = "🟢" if change_pct >= 0 else "🔴"
        dec_label = badge_map.get(decision, f"🔵 {decision}")

        results.append({
            "Sembol": t,
            "Şirket": COMPANY_NAMES.get(t, t),
            "Fiyat": f"${price:.2f}" if price > 0 else "N/A",
            "Günlük Değişim": f"{chg_emoji} %{change_pct:+.2f}",
            "Faktör Skoru": score_str,
            "Sistem Kararı": dec_label,
        })
    return pd.DataFrame(results)

@st.cache_data(ttl=300)
def get_cached_macro():
    """VIX ve SPY yıllık getirisini 5 dk önbellekle çeker."""
    vix_val = None
    spy_ret = None
    try:
        vix_val = vix_oku()
    except Exception:
        pass
    try:
        spy_hist = yf.Ticker("SPY").history(period="1y")
        if not spy_hist.empty and len(spy_hist) > 1:
            spy_ret = ((spy_hist['Close'].iloc[-1] - spy_hist['Close'].iloc[0]) / spy_hist['Close'].iloc[0]) * 100
    except Exception:
        pass
    return vix_val, spy_ret

# ─── ANA İÇERİK ───
st.markdown("## 🌍 Piyasa Rejimi, Sektör & Makro Radarı")
st.caption("Piyasanın hangi rejimde (Boğa, Seçici, Düzeltme, Kriz) olduğunu, faiz/korku etkisini ve paranın hangi sektörlere aktığını görün.")

from web.components.investment_committee import get_market_regime_summary
from web.components.ui import md_to_html
reg = get_market_regime_summary()
rc = reg["regime_color"]

st.markdown(f"""
<div style="background: linear-gradient(135deg, #0b192c 0%, #162a45 100%);
            border-left: 6px solid {rc}; border: 1px solid #233554;
            border-radius: 12px; padding: 1.2rem; margin-bottom: 1rem;">
    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
        <span style="font-size:1.15rem; font-weight:800; color:#fff;">🧭 Piyasa Rejimi Motoru</span>
        <span style="background:{rc}22; border:1px solid {rc}; color:{rc};
                     padding:5px 14px; border-radius:20px; font-weight:700; font-size:0.86rem;">
            {reg['regime_badge']}
        </span>
    </div>
    <p style="color:#ccd6f6; font-size:0.95rem; margin:0.7rem 0 0.4rem 0;">{md_to_html(reg['summary'])}</p>
    <p style="color:#64ffda; font-size:0.9rem; margin:0;">💡 <b>Bu Rejimde Strateji:</b> {md_to_html(reg['hunter_rule'])}</p>
</div>
""", unsafe_allow_html=True)

# Makro kartlar
vix_val, spy_ret = get_cached_macro()
mcol1, mcol2, mcol3, mcol4 = st.columns(4)
with mcol1:
    v_show = vix_val if vix_val is not None else reg["vix_val"]
    vix_emoji = "🟢 Sakin" if v_show < 18 else ("🟡 Dikkatli" if v_show < 25 else "🔴 Yüksek Korku")
    st.metric("CBOE VIX (Korku Endeksi)", f"{v_show:.1f}", delta=vix_emoji)
with mcol2:
    st.metric("Çip Sektörü (SMH 2 Hafta)", f"%{reg['smh_2w_ret']:+.1f}", delta="Yarı İletken Momentum")
with mcol3:
    st.metric("ABD 10 Yıllık Tahvil Faizi", f"%{reg['tnx_val']:.2f}", delta=f"{reg['tnx_2w_chg']:+.2f} puan (2H)", delta_color="inverse")
with mcol4:
    if spy_ret is not None:
        st.metric("S&P 500 (12 Ay Getiri)", f"%{spy_ret:.1f}", delta=f"Son 2H: %{reg['spy_2w_ret']:+.1f}")
    else:
        st.metric("S&P 500 (2 Hafta)", f"%{reg['spy_2w_ret']:+.1f}")

# Sektör tablosu ve scatter
st.divider()
st.markdown("### 📡 Sektör Rotasyon Haritası")

with st.spinner("Sektör verileri yükleniyor..."):
    df_sectors = sektor_performans_tablosu()

if not df_sectors.empty:
    fig_scatter = sektor_scatter(df_sectors)
    st.plotly_chart(fig_scatter, use_container_width=True)

    st.markdown("### 📋 Sektör Performans Tablosu")
    st.dataframe(df_sectors, use_container_width=True, hide_index=True)
else:
    st.warning("Sektör verileri yüklenemedi.")

# Tematik Sepetler
st.divider()
st.markdown("### 🎯 Tematik Yatırım Sepetleri")
st.caption("Yapay zeka, çip, enerji gibi tematik alanlardaki önde gelen şirketler.")

selected_basket = st.selectbox(
    "Sepet Seçin",
    options=list(THEMATIC_BASKETS.keys()),
)

if selected_basket:
    tickers = THEMATIC_BASKETS[selected_basket]
    with st.spinner(f"{selected_basket} sepeti taranıyor..."):
        df_basket = tematik_sepet_tablosu(selected_basket, tickers)
    if not df_basket.empty:
        st.dataframe(df_basket, use_container_width=True, hide_index=True)
    else:
        st.warning("Sepet verileri yüklenemedi.")
