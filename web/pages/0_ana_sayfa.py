"""
Sayfa 0: 📱 Mobil & Ana Kontrol Paneli (Mobile Home)
Portföy takip kartları, hızlı hisse arama, günün fırsatları ve VIX nabzı.
"""
import json
import os
import sys
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.mobile import (
    COMPANY_NAMES,
    badge_info,
    get_cached_quotes,
    get_db_symbol_data,
    get_top_opportunities,
    get_vix_status,
)

WATCHLIST_PATH = os.path.join(PROJECT_ROOT, "web", "data", "watchlist.json")
LAST_UPDATE_PATH = os.path.join(PROJECT_ROOT, "web", "data", "last_update.json")


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


# ─── MOBİL ANA SAYFA CSS ───
st.markdown("""
<style>
    /* Üst Başlık & VIX Şeridi */
    .mobile-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.2rem 0 0.8rem 0;
        border-bottom: 1px solid rgba(255, 255, 255, 0.08);
        margin-bottom: 1rem;
    }
    .mobile-title {
        font-size: 1.35rem;
        font-weight: 800;
        background: linear-gradient(90deg, #64ffda 0%, #00b0ff 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin: 0;
    }
    .vix-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 5px 12px;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 700;
        border: 1px solid rgba(255, 255, 255, 0.15);
    }

    /* Hisse Kartı (Fintech Style) */
    .stock-card {
        background: linear-gradient(135deg, #0e1e38 0%, #132744 100%);
        border: 1px solid rgba(100, 255, 218, 0.12);
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 8px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: transform 0.15s ease, border-color 0.15s ease;
    }
    .stock-card:hover {
        border-color: rgba(100, 255, 218, 0.4);
    }
    .stock-info {
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .stock-symbol {
        font-size: 1.15rem;
        font-weight: 800;
        color: #ffffff;
        letter-spacing: 0.5px;
    }
    .stock-name {
        font-size: 0.75rem;
        color: #8892b0;
        max-width: 130px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .stock-price-col {
        text-align: right;
        display: flex;
        flex-direction: column;
        gap: 2px;
    }
    .stock-price {
        font-size: 1.1rem;
        font-weight: 700;
        color: #f1f5f9;
    }
    .stock-change-pos {
        font-size: 0.8rem;
        font-weight: 700;
        color: #00e676;
    }
    .stock-change-neg {
        font-size: 0.8rem;
        font-weight: 700;
        color: #ff5252;
    }
    .stock-badge {
        padding: 4px 10px;
        border-radius: 16px;
        font-size: 0.72rem;
        font-weight: 700;
        text-align: center;
        white-space: nowrap;
        margin-left: 10px;
    }

    /* Fırsat Yatay Kartları */
    .opp-card {
        background: linear-gradient(145deg, #0d1e36 0%, #152d4d 100%);
        border: 1px solid rgba(0, 230, 118, 0.25);
        border-radius: 12px;
        padding: 12px;
        text-align: center;
        min-height: 110px;
    }
    .opp-sym {
        font-size: 1.1rem;
        font-weight: 800;
        color: #ffffff;
    }
    .opp-score {
        font-size: 1.4rem;
        font-weight: 800;
        color: #64ffda;
        margin: 4px 0;
    }
    .opp-sub {
        font-size: 0.72rem;
        color: #8892b0;
    }

    /* Model Nabzı Şerit Kartı */
    .model-strip {
        background: linear-gradient(135deg, #10233f 0%, #19385c 100%);
        border: 1px solid rgba(100, 255, 218, 0.15);
        border-radius: 12px;
        padding: 12px 14px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-top: 6px;
    }
</style>
""", unsafe_allow_html=True)

# ─── 1. ÜST ŞERİT (App Başlığı + Canlı VIX) ───
vix_val, vix_text, vix_color = get_vix_status()
st.markdown(f"""
<div class="mobile-header">
    <div class="mobile-title">🏦 StockPredictionPro</div>
    <div class="vix-pill" style="background: rgba(0,0,0,0.3); color: {vix_color};">
        <span>VIX {vix_val:.1f}</span>
        <span>{vix_text.split()[-1]}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ─── 2. HIZLI HİSSE ARAMA ───
col_s1, col_s2 = st.columns([3, 1])
with col_s1:
    search_query = st.text_input(
        "Hisse ara",
        placeholder="🔍 Hisse ara (MU, NVDA, AVGO...)",
        label_visibility="collapsed",
        key="mobile_search_input",
    )
with col_s2:
    if st.button("Analiz", type="primary", use_container_width=True, key="mobile_search_btn"):
        if search_query:
            git_analiz(search_query)

# Hızlı hap butonlar
quick_tickers = ["MU", "NVDA", "AVGO", "BE", "EOG", "COHR"]
q_cols = st.columns(len(quick_tickers))
for idx, q_sym in enumerate(quick_tickers):
    with q_cols[idx]:
        if st.button(q_sym, key=f"q_{q_sym}", use_container_width=True):
            git_analiz(q_sym)

st.write("")

# ─── 3. PORTFÖYÜM & TAKİP LİSTESİ ───
watchlist = load_watchlist()

st.markdown("### 💼 Portföyüm")

with st.spinner("Canlı piyasa verileri yükleniyor..."):
    quotes = get_cached_quotes(tuple(watchlist))
    db_info = get_db_symbol_data(tuple(watchlist))

for sym in watchlist:
    q = quotes.get(sym, {"price": 0.0, "change": 0.0, "change_pct": 0.0})
    db = db_info.get(sym, {})
    
    price = q["price"] if q["price"] > 0 else (db.get("db_fiyat") or 0.0)
    chg = q["change"]
    chg_pct = q["change_pct"]
    chg_class = "stock-change-pos" if chg >= 0 else "stock-change-neg"
    chg_sign = "+" if chg >= 0 else ""
    
    decision = db.get("decision") or "IZLE"
    b_label, b_color, b_bg = badge_info(decision)
    comp_name = COMPANY_NAMES.get(sym, sym)

    card_col, btn_col = st.columns([4, 1])
    with card_col:
        price_str = f"${price:.2f}" if price > 0 else "N/A"
        chg_str = f"{chg_sign}{chg_pct:.2f}%" if price > 0 else "—"
        st.markdown(f"""
        <div class="stock-card">
            <div class="stock-info">
                <span class="stock-symbol">{sym}</span>
                <span class="stock-name" title="{comp_name}">{comp_name}</span>
            </div>
            <div style="display: flex; align-items: center;">
                <div class="stock-price-col">
                    <span class="stock-price">{price_str}</span>
                    <span class="{chg_class}">{chg_str}</span>
                </div>
                <div class="stock-badge" style="color: {b_color}; background: {b_bg}; border: 1px solid {b_color}40;">
                    {b_label}
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with btn_col:
        if st.button("İncele", key=f"detay_{sym}", use_container_width=True):
            git_analiz(sym)

# Takip listesi düzenleme expander'ı
with st.expander("⚙️ Portföy Listesini Düzenle"):
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

st.divider()

# ─── 4. BUGÜNÜN FIRSATLARI ───
st.markdown("### 🎯 Bugünün Fırsatları (AL Adayları)")
st.caption("Son kurumsal taramada en yüksek faktör puanını alan fırsat hisseleri:")

opps = get_top_opportunities(limit=4)
if opps:
    o_cols = st.columns(len(opps))
    for idx, opp in enumerate(opps):
        with o_cols[idx]:
            sym = opp["sembol"]
            score = opp["skor"]
            fiyat = opp["fiyat"]
            st.markdown(f"""
            <div class="opp-card">
                <div class="opp-sym">{sym}</div>
                <div class="opp-score">%{score:.1f}</div>
                <div class="opp-sub">${fiyat:.2f} · {opp['sektor']}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button("Analiz Et", key=f"opp_btn_{sym}", use_container_width=True):
                git_analiz(sym)
else:
    st.info("Henüz taranmış AL adayı bulunamadı. Piyasa Tarayıcı'dan yeni tarama başlatabilirsiniz.")

st.divider()

# ─── 5. MODEL NABZI ───
st.markdown("### 🧪 Model Nabzı")

last_update = {}
if os.path.exists(LAST_UPDATE_PATH):
    try:
        with open(LAST_UPDATE_PATH, "r", encoding="utf-8") as f:
            last_update = json.load(f)
    except Exception:
        pass

lider = last_update.get("lider", "Challenger (m00_r15)")
tarih = last_update.get("son_guncelleme", "29.09.2026")
ch_ret = last_update.get("challenger_1m", 4.15)
bl_ret = last_update.get("baseline_1m", 3.29)

st.markdown(f"""
<div class="model-strip">
    <div>
        <div style="font-weight: 700; color: #f1f5f9; font-size: 0.95rem;">🏆 Lider: {lider}</div>
        <div style="font-size: 0.75rem; color: #8892b0;">Son güncelleme: {tarih} · Getiri: Challenger %{ch_ret:.2f} vs Baseline %{bl_ret:.2f}</div>
    </div>
    <div style="font-size: 1.1rem; color: #64ffda; font-weight: 800;">
        +%{ch_ret - bl_ret:.2f}
    </div>
</div>
""", unsafe_allow_html=True)

m_btn1, m_btn2 = st.columns(2)
with m_btn1:
    if st.button("🧪 Model Arenası", use_container_width=True):
        try:
            st.switch_page("pages/6_shadow_test.py")
        except Exception:
            pass
with m_btn2:
    if st.button("📊 Tüm Piyasayı Tara", use_container_width=True):
        try:
            st.switch_page("pages/1_piyasa_tarayici.py")
        except Exception:
            pass
