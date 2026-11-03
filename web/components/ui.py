"""
StockPredictionPro — Ortak Arayüz Bileşenleri (Tasarım Dili)
=============================================================
Tüm sayfalar aynı renk paleti, kart, rozet ve metrik stilini buradan kullanır.
Böylece sayfalar birbirine benzer, sade ve tutarlı görünür.
"""
from __future__ import annotations

import html

import pandas as pd
import streamlit as st

# ─── RENK PALETİ (4 anlamlı renk + nötrler) ───
GREEN = "#22c55e"   # Al / olumlu
AMBER = "#f59e0b"   # İzle / dikkat
RED = "#ef4444"     # Risk / tehlike
BLUE = "#3b82f6"    # Bilgi / bekle
ACCENT = "#2dd4bf"  # Vurgu (marka)
TEXT = "#e6edf7"
MUTED = "#8b9bb4"
CARD = "#111a2e"
CARD_2 = "#0d1526"
BORDER = "#1f2a44"

STATE_STYLE = {
    # Alım Avcısı durumları
    "ALIM_FIRSATI": ("Alım Fırsatı", GREEN),
    "PUSUDA_IZLE": ("Ucuzluk Bölgesi · İzle", AMBER),
    "BEKLEMEDE": ("Beklemede", BLUE),
    "TEHLIKE": ("Destek Kırıldı", RED),
    # Satış Avcısı durumları
    "SIMDI_KAR_AL": ("Kâr Al", GREEN),
    "BILANCO_UYARISI": ("Bilanço Yakın", AMBER),
    "KARI_KORU_TUT": ("Tut · Kârı Koru", BLUE),
    "DIPTE_SATILMAZ": ("Dipte Satma", MUTED),
    # Yapay zeka durumları
    "AI_GUCLU_ONAY": ("AI Güçlü", GREEN),
    "AI_OLUMLU": ("AI Olumlu", BLUE),
    "AI_KARARSIZ": ("AI Kararsız", AMBER),
    "AI_TEHLIKE": ("AI Riskli", RED),
}


def state_label(code: str) -> tuple[str, str]:
    """Durum kodunu sade etiket ve renge çevirir."""
    return STATE_STYLE.get(code, (code.replace("_", " ").title(), MUTED))


def esc(text) -> str:
    return html.escape(str(text)) if text is not None else ""


# ─── GLOBAL CSS ───
GLOBAL_CSS = f"""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
    html, body, [class*="css"], .stMarkdown, .stText, button, input {{
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }}
    .block-container {{ padding-top: 1.2rem; padding-bottom: 3rem; max-width: 1180px; }}
    [data-testid="stSidebar"] {{ background-color: #0a1120; border-right: 1px solid {BORDER}; }}
    #MainMenu, footer, .stDeployButton {{ visibility: hidden; display: none !important; }}
    header[data-testid="stHeader"] {{ background: transparent; }}

    /* Başlık */
    .spp-header {{ margin: 0 0 1rem 0; }}
    .spp-header h1 {{ font-size: 1.45rem; font-weight: 800; color: {TEXT}; margin: 0; letter-spacing: -0.01em; }}
    .spp-header p {{ color: {MUTED}; font-size: 0.88rem; margin: 4px 0 0 0; }}

    /* Kart */
    .spp-card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; padding: 16px 18px; margin-bottom: 12px; }}
    .spp-card.accent {{ border-left: 4px solid var(--c); }}
    .spp-row {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .spp-sym {{ font-size: 1.35rem; font-weight: 800; color: {TEXT}; }}
    .spp-name {{ font-size: 0.8rem; color: {MUTED}; margin-left: 6px; font-weight: 500; }}
    .spp-price {{ font-size: 1.25rem; font-weight: 700; color: {TEXT}; }}
    .spp-chg {{ font-size: 0.85rem; font-weight: 600; margin-left: 6px; }}
    .spp-headline {{ color: #cbd5e1; font-size: 0.93rem; line-height: 1.5; margin: 10px 0 2px 0; }}

    /* Rozet */
    .spp-badge {{ display: inline-block; padding: 4px 11px; border-radius: 999px; font-size: 0.76rem; font-weight: 700;
                 color: var(--c); background: color-mix(in srgb, var(--c) 14%, transparent); border: 1px solid color-mix(in srgb, var(--c) 45%, transparent); white-space: nowrap; }}

    /* Metrik ızgarası (telefonda 2x2) */
    .spp-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }}
    .spp-stat {{ background: {CARD_2}; border: 1px solid {BORDER}; border-radius: 10px; padding: 10px 12px; }}
    .spp-stat .l {{ color: {MUTED}; font-size: 0.72rem; font-weight: 500; text-transform: uppercase; letter-spacing: 0.03em; }}
    .spp-stat .v {{ color: var(--c, {TEXT}); font-size: 1.05rem; font-weight: 700; margin-top: 3px; }}
    .spp-stat .s {{ color: {MUTED}; font-size: 0.72rem; margin-top: 2px; }}

    /* Olasılık çubuğu */
    .spp-bar {{ height: 8px; border-radius: 6px; background: color-mix(in srgb, {RED} 35%, transparent); overflow: hidden; margin: 6px 0 4px 0; }}
    .spp-bar > div {{ height: 100%; background: {GREEN}; border-radius: 6px; }}
    .spp-bar-lbl {{ display: flex; justify-content: space-between; font-size: 0.76rem; color: {MUTED}; }}

    /* Liste satırı */
    .spp-list-row {{ display: grid; grid-template-columns: 1.1fr 1fr 1.4fr 0.9fr 0.8fr; gap: 8px; align-items: center;
                    padding: 10px 4px; border-bottom: 1px solid {BORDER}; font-size: 0.88rem; color: {TEXT}; }}
    .spp-list-head {{ color: {MUTED}; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.03em; font-weight: 600; }}

    .spp-section {{ font-size: 1.02rem; font-weight: 700; color: {TEXT}; margin: 1.4rem 0 0.6rem 0; }}
    .spp-muted {{ color: {MUTED}; font-size: 0.8rem; }}

    /* Streamlit bileşen ince ayarları */
    div[data-testid="stExpander"] {{ border: 1px solid {BORDER}; border-radius: 12px; background: {CARD_2}; }}
    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{ padding: 6px 12px; font-size: 0.88rem; }}
    .stButton > button {{ border-radius: 10px; font-weight: 600; }}
    [data-testid="stMetricValue"] {{ font-size: 1.25rem; }}

    /* Eski sayfalarla uyumluluk (Gelişmiş menüdeki sayfalar) */
    .metric-card {{ background: {CARD}; border-radius: 12px; padding: 1rem; border: 1px solid {BORDER}; text-align: center; min-height: 90px; }}
    .metric-card h3 {{ color: {MUTED}; font-size: 0.78rem; margin: 0; font-weight: 600; }}
    .metric-card h1 {{ color: {TEXT}; font-size: 1.5rem; margin: 0.3rem 0 0 0; }}
    .badge-al {{ background: {GREEN}; color: #fff; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }}
    .badge-bekle {{ background: {AMBER}; color: #fff; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }}
    .badge-izle {{ background: {BLUE}; color: #fff; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }}
    .badge-reddet {{ background: {RED}; color: #fff; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }}
    .badge-olay {{ background: #8b5cf6; color: #fff; padding: 3px 10px; border-radius: 999px; font-weight: 700; font-size: 0.8rem; }}

    @media (max-width: 768px) {{
        .block-container {{ padding-left: 0.7rem !important; padding-right: 0.7rem !important; padding-bottom: 5rem !important; }}
        .spp-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
        .spp-sym {{ font-size: 1.2rem; }}
        .spp-list-row {{ grid-template-columns: 1fr 1fr 1.3fr; }}
        .spp-list-row .hide-m {{ display: none; }}
        .stButton > button {{ min-height: 44px; }}
        [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap !important; gap: 0.5rem !important; }}
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{ flex: 1 1 100% !important; min-width: 100% !important; }}
    }}
</style>
"""


def inject_global_css():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ─── BİLEŞENLER ───
def page_header(title: str, subtitle: str = ""):
    sub = f"<p>{esc(subtitle)}</p>" if subtitle else ""
    st.markdown(f"<div class='spp-header'><h1>{esc(title)}</h1>{sub}</div>", unsafe_allow_html=True)


def section(title: str):
    st.markdown(f"<div class='spp-section'>{esc(title)}</div>", unsafe_allow_html=True)


def badge(text: str, color: str) -> str:
    return f"<span class='spp-badge' style='--c:{color}'>{esc(text)}</span>"


def stat_html(label: str, value: str, sub: str = "", color: str = TEXT) -> str:
    sub_html = f"<div class='s'>{esc(sub)}</div>" if sub else ""
    return (
        f"<div class='spp-stat' style='--c:{color}'><div class='l'>{esc(label)}</div>"
        f"<div class='v'>{esc(value)}</div>{sub_html}</div>"
    )


def stat_grid(stats: list[tuple]) -> str:
    """stats: [(label, value, sub, color), ...] → masaüstünde 4'lü, telefonda 2x2 ızgara."""
    return "<div class='spp-grid'>" + "".join(stat_html(*s) for s in stats) + "</div>"


def prob_bar_html(win_pct: int, left_label: str, right_label: str) -> str:
    win_pct = max(0, min(100, int(win_pct)))
    return (
        f"<div class='spp-bar'><div style='width:{win_pct}%'></div></div>"
        f"<div class='spp-bar-lbl'><span>{esc(left_label)}</span><span>{esc(right_label)}</span></div>"
    )


def chg_html(chg_pct: float) -> str:
    color = GREEN if chg_pct >= 0 else RED
    return f"<span class='spp-chg' style='color:{color}'>{chg_pct:+.2f}%</span>"


def decision_card(
    symbol: str,
    price: float,
    chg_pct: float,
    status_text: str,
    status_color: str,
    headline: str,
    stats: list[tuple] | None = None,
    extra_badges: list[tuple] | None = None,
    name: str = "",
    footer_html: str = "",
):
    """Sayfanın en üstündeki tek karar kartı: durum + tek cümle + 4 sayı."""
    badges = badge(status_text, status_color)
    for txt, col in (extra_badges or []):
        badges = badge(txt, col) + " " + badges
    name_html = f"<span class='spp-name'>{esc(name)}</span>" if name else ""
    grid = stat_grid(stats) if stats else ""
    st.markdown(
        f"""
        <div class='spp-card accent' style='--c:{status_color}'>
            <div class='spp-row'>
                <div><span class='spp-sym'>{esc(symbol)}</span>{name_html}</div>
                <div style='display:flex; gap:6px; flex-wrap:wrap; align-items:center;'>{badges}</div>
            </div>
            <div style='margin-top:4px;'><span class='spp-price'>${price:,.2f}</span>{chg_html(chg_pct)}</div>
            <div class='spp-headline'>{esc(headline)}</div>
            {grid}
            {footer_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def regime_strip(regime_info: dict):
    """Piyasa rejimini tek satırlık sade bir şerit olarak gösterir."""
    code = regime_info.get("regime_code", "")
    regime_map = {
        "GUCLU_BOGA": ("Güçlü Yükseliş · Risk İştahı Açık", GREEN),
        "SECICI_YATAY": ("Seçici / Dalgalı Piyasa", AMBER),
        "DUZELTME_BASKISI": ("Sektörel Düzeltme · Riskten Kaçış", RED),
        "KRIZ_YUKSEK_RISK": ("Yüksek Korku · Savunma", RED),
    }
    badge_txt, color = regime_map.get(code, ("Piyasa Rejimi", AMBER))
    st.markdown(
        f"""
        <div class='spp-card' style='padding:12px 16px;'>
            <div class='spp-row'>
                <div>{badge(badge_txt, color)}</div>
                <div class='spp-muted'>S&amp;P 500 (2H) {regime_info.get('spy_2w_ret', 0):+.1f}% · Çip ETF (2H) {regime_info.get('smh_2w_ret', 0):+.1f}% · VIX {regime_info.get('vix_val', 0):.1f}</div>
            </div>
            <div class='spp-headline' style='margin-top:8px;'>{esc(regime_info.get('hunter_rule', ''))}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def info_note(text: str):
    st.markdown(f"<div class='spp-muted' style='margin:4px 0 10px 0;'>{esc(text)}</div>", unsafe_allow_html=True)


# ─── GRAFİK: FİYAT + ALIM BÖLGESİ / STOP / HEDEF ───
def price_chart_with_levels(
    df: pd.DataFrame,
    zone1: tuple[float, float] | None = None,
    zone2: tuple[float, float] | None = None,
    stop: float | None = None,
    target1: float | None = None,
    target2: float | None = None,
    height: int = 360,
):
    """Mum grafiğinin üzerine alım bölgesini (yeşil bant), stopu (kırmızı) ve hedefleri (mavi) çizer."""
    import plotly.graph_objects as go

    if df is None or df.empty:
        return None
    d = df.tail(130).copy()
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=d.index, open=d["Open"], high=d["High"], low=d["Low"], close=d["Close"],
        increasing_line_color=GREEN, decreasing_line_color=RED, name="Fiyat", showlegend=False,
    ))
    sma20 = df["Close"].rolling(20).mean().reindex(d.index)
    sma50 = df["Close"].rolling(50).mean().reindex(d.index)
    sma200 = df["Close"].rolling(200).mean().reindex(d.index)
    fig.add_trace(go.Scatter(x=d.index, y=sma20, line=dict(color=AMBER, width=1, dash="dot"), name="SMA 20"))
    fig.add_trace(go.Scatter(x=d.index, y=sma50, line=dict(color=BLUE, width=1.4), name="SMA 50"))
    fig.add_trace(go.Scatter(x=d.index, y=sma200, line=dict(color="#a855f7", width=1.8), name="SMA 200"))

    if zone1:
        fig.add_hrect(y0=zone1[0], y1=zone1[1], fillcolor=GREEN, opacity=0.13, line_width=0,
                      annotation_text="1. Alım", annotation_position="top left", annotation_font_color=GREEN, annotation_font_size=11)
    if zone2:
        fig.add_hrect(y0=zone2[0], y1=zone2[1], fillcolor=GREEN, opacity=0.07, line_width=0,
                      annotation_text="2. Alım", annotation_position="top left", annotation_font_color=GREEN, annotation_font_size=11)
    if stop:
        fig.add_hline(y=stop, line_color=RED, line_width=1.2, line_dash="dash",
                      annotation_text=f"Stop ${stop:,.2f}", annotation_position="bottom right", annotation_font_color=RED, annotation_font_size=11)
    if target1:
        fig.add_hline(y=target1, line_color=BLUE, line_width=1.2, line_dash="dash",
                      annotation_text=f"Hedef ${target1:,.2f}", annotation_position="top right", annotation_font_color=BLUE, annotation_font_size=11)
    if target2:
        fig.add_hline(y=target2, line_color=BLUE, line_width=0.8, line_dash="dot",
                      annotation_text=f"Hedef 2 ${target2:,.2f}", annotation_position="top right", annotation_font_color=BLUE, annotation_font_size=10)

    fig.update_layout(
        height=height,
        margin=dict(l=6, r=6, t=10, b=6),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_rangeslider_visible=False,
        font=dict(color=MUTED, size=11),
        legend=dict(orientation="h", y=1.04, x=0, font=dict(size=10)),
        xaxis=dict(gridcolor="rgba(255,255,255,0.04)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.05)", side="right"),
    )
    return fig
