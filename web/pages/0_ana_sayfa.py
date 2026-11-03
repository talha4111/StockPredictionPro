"""
Sayfa 0: 🏠 Ana Sayfa & AI Komuta Merkezi
Portföy takip kartları, hızlı hisse arama, günün fırsatları, aktif piyasa rejimi ve Üçlü Bariyer AI nabzı.
"""
import json
import os
import sys
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.dip_hunter import analyze_stock_dip, load_dip_config, save_dip_config
from web.components.investment_committee import get_market_regime_summary
from web.components.mobile import (
    COMPANY_NAMES,
    badge_info,
    get_cached_quotes,
    get_db_symbol_data,
    get_top_opportunities,
    get_vix_status,
)
from web.components.ui import (
    ACCENT,
    AMBER,
    BLUE,
    BORDER,
    CARD,
    CARD_2,
    GREEN,
    MUTED,
    RED,
    TEXT,
    badge,
    chg_html,
    esc,
    page_header,
    regime_strip,
    section,
)

WATCHLIST_PATH = os.path.join(PROJECT_ROOT, "web", "data", "watchlist.json")


def load_watchlist():
    if os.path.exists(WATCHLIST_PATH):
        try:
            with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return [s.upper().strip() for s in data]
        except Exception:
            pass
    return ["MU", "MRVL", "AVGO", "EOG", "BE", "COHR"]


def save_watchlist(symbols):
    try:
        os.makedirs(os.path.dirname(WATCHLIST_PATH), exist_ok=True)
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(symbols, f, indent=2)
        cfg = load_dip_config()
        cfg["symbols"] = symbols
        save_dip_config(cfg)
        return True
    except Exception:
        return False


def git_analiz(sembol: str):
    """Seçilen hisseyi analiz sayfasına taşır."""
    st.session_state["selected_symbol"] = sembol.upper().strip()
    st.session_state["auto_analyze"] = True
    try:
        st.switch_page("pages/2_tek_hisse_analiz.py")
    except Exception:
        pass


# ─── 1. ÜST BAŞLIK & AKTİF PİYASA REJİMİ ───
vix_val, vix_text, vix_color = get_vix_status()
page_header(
    "🏦 StockPredictionPro · AI Komuta Merkezi",
    "Takip ettiğin hisselerin anlık ucuzluk bölgesi, 15 günlük yapay zeka hedef olasılığı ve piyasa yönü tek ekranda.",
)

regime_info = get_market_regime_summary()
regime_strip(regime_info)

nav_c1, nav_c2, nav_c3 = st.columns(3)
with nav_c1:
    if st.button("🎯 Alım & Satış Avcısı (AI)", type="primary", use_container_width=True, key="home_nav_dip"):
        st.switch_page("pages/9_alim_avcisi.py")
with nav_c2:
    if st.button("💼 Portföy & Risk Merkezi", use_container_width=True, key="home_nav_port"):
        st.switch_page("pages/8_portfoy_defteri.py")
with nav_c3:
    if st.button("🔍 Hisse Analizi & Komite", use_container_width=True, key="home_nav_ic"):
        st.switch_page("pages/2_tek_hisse_analiz.py")

# ─── 2. HIZLI HİSSE ARAMA ───
section("🔍 Hızlı Hisse Sorgula")
col_s1, col_s2 = st.columns([3.2, 1])
with col_s1:
    search_query = st.text_input(
        "Hisse ara",
        placeholder="Hisse kodu yazın (Örn: MU, MRVL, COHR, BE, RKLB, VST, AVGO, NVDA...)",
        label_visibility="collapsed",
        key="mobile_search_input",
    )
with col_s2:
    if st.button("🚀 Analiz Et", type="primary", use_container_width=True, key="mobile_search_btn"):
        if search_query:
            git_analiz(search_query)

quick_tickers = ["MU", "MRVL", "COHR", "BE", "RKLB", "VST", "AVGO", "NVDA"]
q_cols = st.columns(len(quick_tickers))
for idx, q_sym in enumerate(quick_tickers):
    with q_cols[idx]:
        if st.button(q_sym, key=f"q_{q_sym}", use_container_width=True):
            git_analiz(q_sym)

# ─── 3. TAKİP LİSTEM & YAPAY ZEKA (ÜÇLÜ BARİYER) CANLI ÖZETİ ───
dip_cfg = load_dip_config()
watchlist = dip_cfg.get("symbols") or load_watchlist()

section("💼 Takip Listem & Yapay Zeka (15 Günlük Hedef / Stop) Özeti")
st.caption("Her hisse için Alım Avcısı ucuzluk bölgesi ve Üçlü Bariyer Yapay Zeka motorunun 15 günlük hedef başarı olasılığı:")


@st.cache_data(ttl=120, show_spinner=False)
def _home_dip_ai_scan(sym_tuple: tuple, vix_v: float) -> dict[str, dict]:
    out = {}
    for s in sym_tuple:
        r = analyze_stock_dip(s, vix_value=vix_v)
        if r:
            out[s] = r
    return out


with st.spinner("Canlı piyasa ve Yapay Zeka (Üçlü Bariyer) olasılıkları hesaplanıyor..."):
    quotes = get_cached_quotes(tuple(watchlist))
    db_info = get_db_symbol_data(tuple(watchlist))
    dip_ai_map = _home_dip_ai_scan(tuple(watchlist), float(vix_val))

for sym in watchlist:
    q = quotes.get(sym, {"price": 0.0, "change": 0.0, "change_pct": 0.0})
    db = db_info.get(sym, {})
    dip_r = dip_ai_map.get(sym, {})
    ai_p = dip_r.get("ai_pred") or {}

    price = dip_r.get("current_price") or (q["price"] if q["price"] > 0 else (db.get("db_fiyat") or 0.0))
    chg_pct = dip_r.get("daily_change_pct") if dip_r else q["change_pct"]

    if dip_r:
        b_label = dip_r["state_badge"]
        b_color = dip_r["state_color"]
    else:
        decision = db.get("decision") or "IZLE"
        b_label, b_color, _ = badge_info(decision)
    comp_name = COMPANY_NAMES.get(sym, sym)

    ai_badge_str = ""
    sub_row_html = ""
    if dip_r:
        if ai_p.get("available"):
            ac = ai_p.get("ai_color", BLUE)
            ai_badge_str = badge(ai_p["ai_badge"], ac)
            sub_row_html = (
                f"<div style='margin-top:8px; padding-top:8px; border-top:1px solid {BORDER}; "
                f"display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; font-size:0.8rem; color:{TEXT};'>"
                f"<span>🗣️ {esc(dip_r['headline'])}</span>"
                f"<span style='color:{MUTED};'>🟢 1. Alım: <b style='color:{GREEN};'>${dip_r['zone1_low']:.2f}–${dip_r['zone1_high']:.2f}</b> · "
                f"⛔ Stop: <b style='color:{RED};'>${dip_r['stop_level']:.2f}</b> · "
                f"🎯 Hedef: <b style='color:{BLUE};'>${dip_r['target1']:.2f}</b> · "
                f"📊 İkiz Kazanma: <b>%{ai_p['analog_win_rate_pct']:.0f}</b> ({ai_p['analog_avg_ret_pct']:+.1f}%)</span>"
                f"</div>"
            )
        else:
            sub_row_html = (
                f"<div style='margin-top:8px; padding-top:8px; border-top:1px solid {BORDER}; font-size:0.8rem; color:{MUTED};'>"
                f"🗣️ {esc(dip_r['headline'])} · 1. Alım: ${dip_r['zone1_low']:.2f}–${dip_r['zone1_high']:.2f} · Hedef: ${dip_r['target1']:.2f}"
                f"</div>"
            )

    card_col, btn_col = st.columns([4.4, 1])
    with card_col:
        price_str = f"${price:,.2f}" if price > 0 else "N/A"
        st.markdown(
            f"""
            <div class="spp-card accent" style="--c:{b_color}; padding:13px 16px; margin-bottom:8px;">
                <div class="spp-row">
                    <div>
                        <span class="spp-sym">{esc(sym)}</span>
                        <span class="spp-name">· {esc(comp_name)}</span>
                        <span style="margin-left:12px;" class="spp-price">{price_str}</span>
                        {chg_html(chg_pct) if price > 0 else ''}
                    </div>
                    <div style="display:flex; gap:6px; flex-wrap:wrap; align-items:center;">
                        {ai_badge_str}
                        {badge(b_label, b_color)}
                    </div>
                </div>
                {sub_row_html}
            </div>
            """,
            unsafe_allow_html=True,
        )
    with btn_col:
        if st.button("🔍 İncele", key=f"detay_{sym}", use_container_width=True):
            git_analiz(sym)

with st.expander("⚙️ Takip Listesini Düzenle"):
    new_sym = st.text_input("Yeni hisse ekle (örn: TSLA, AAPL):", key="add_sym_input")
    add_col, rem_col = st.columns(2)
    with add_col:
        if st.button("➕ Listeye Ekle", use_container_width=True):
            if new_sym:
                cleaned = new_sym.upper().strip()
                if cleaned not in watchlist:
                    watchlist.append(cleaned)
                    save_watchlist(watchlist)
                    st.success(f"{cleaned} eklendi!")
                    st.rerun()
    with rem_col:
        remove_sym = st.selectbox("Listeden Çıkar:", options=["Seçin..."] + watchlist, key="rem_sym_sel")
        if st.button("➖ Çıkar", use_container_width=True):
            if remove_sym and remove_sym != "Seçin...":
                watchlist = [s for s in watchlist if s != remove_sym]
                save_watchlist(watchlist)
                st.warning(f"{remove_sym} çıkarıldı!")
                st.rerun()

# ─── 4. BUGÜNÜN FIRSATLARI ───
section("🎯 Bugünün Fırsatları (Kurumsal AL Adayları)")
st.caption("Son kurumsal taramada en yüksek faktör puanını alan fırsat hisseleri:")

opps = get_top_opportunities(limit=4)
if opps:
    o_cols = st.columns(len(opps))
    for idx, opp in enumerate(opps):
        with o_cols[idx]:
            sym = opp["sembol"]
            score = opp["skor"]
            fiyat = opp["fiyat"]
            st.markdown(
                f"""
                <div class="spp-card accent" style="--c:{GREEN}; text-align:center; padding:12px;">
                    <div style="font-size:1.1rem; font-weight:800; color:{TEXT};">{esc(sym)}</div>
                    <div style="font-size:1.35rem; font-weight:800; color:{ACCENT}; margin:4px 0;">%{score:.1f}</div>
                    <div class="spp-muted">${fiyat:.2f} · {esc(opp['sektor'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button("Analiz Et", key=f"opp_btn_{sym}", use_container_width=True):
                git_analiz(sym)
else:
    st.info("Henüz taranmış AL adayı bulunamadı. Gelişmiş menüden Piyasa Tarayıcı'yı çalıştırabilirsiniz.")

# ─── 5. YAPAY ZEKA & MODEL NABZI ───
section("🤖 Hibrit Yapay Zeka (Üçlü Bariyer) & Model Nabzı")
st.markdown(
    f"""
    <div class="spp-card accent" style="--c:{ACCENT};">
        <div class="spp-row">
            <div>
                <div style="font-weight:700; color:{TEXT}; font-size:0.95rem;">
                    🏆 Aktif AI Motoru: Hibrit Üçlü Bariyer (Lojistik + Sığ RF + Tarihsel İkizler)
                </div>
                <div class="spp-muted" style="margin-top:4px;">
                    20 ABD Hissesi · 2.837 Geçmiş Dip Testi · AI Onaylı Kazanma Oranı: <b>%59.8</b> (Baz: %54.9) · 15G Ort. Getiri: <b>+%2.14</b> (Baz: +%1.03)
                </div>
            </div>
            <div>{badge("2.1x Getiri Avantajı", GREEN)}</div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

m_btn1, m_btn2 = st.columns(2)
with m_btn1:
    if st.button("🧪 Model Arenası (Shadow Test)", use_container_width=True):
        try:
            st.switch_page("pages/6_shadow_test.py")
        except Exception:
            pass
with m_btn2:
    if st.button("📊 Tüm Piyasayı Tara (S&P 500)", use_container_width=True):
        try:
            st.switch_page("pages/1_piyasa_tarayici.py")
        except Exception:
            pass
