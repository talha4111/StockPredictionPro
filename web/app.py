"""
StockPredictionPro Web Dashboard — Ana Uygulama
Streamlit multipage uygulaması (7 Modül, 3 Bölüm).
"""
import streamlit as st
import sys
import os

# Proje kök dizinini Python path'ine ekle
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ─── Sayfa Konfigürasyonu ───
st.set_page_config(
    page_title="StockPredictionPro",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Karanlık Tema + Mobil Uyumlu CSS ───
st.markdown("""
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<style>
    /* ── Genel ── */
    .block-container { padding-top: 1rem; }
    [data-testid="stSidebar"] { background-color: #0a192f; }

    /* ── Metrik Kartları ── */
    .metric-card {
        background: linear-gradient(135deg, #112240 0%, #1d3557 100%);
        border-radius: 12px;
        padding: 1.2rem;
        border: 1px solid #233554;
        text-align: center;
        min-height: 100px;
    }
    .metric-card h3 { color: #8892b0; font-size: 0.85rem; margin: 0; }
    .metric-card h1 { color: #64ffda; font-size: 1.8rem; margin: 0.3rem 0 0 0; }

    /* ── Rozetler ── */
    .badge-al { background: #00c853; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .badge-bekle { background: #ff9800; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .badge-izle { background: #2196f3; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .badge-reddet { background: #f44336; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold; }
    .badge-olay { background: #9c27b0; color: white; padding: 4px 12px; border-radius: 20px; font-weight: bold; }

    /* ══════════════════════════════════════════════════════
       📱 MOBİL UYUM (max-width: 768px)
       ══════════════════════════════════════════════════════ */
    @media (max-width: 768px) {
        /* Padding azalt */
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 0.5rem !important;
        }

        /* Sütunları 2'li grid yap */
        [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap !important;
            gap: 0.4rem !important;
        }
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 0 0 48% !important;
            min-width: 48% !important;
            max-width: 48% !important;
        }

        /* Metrik kartları küçült */
        .metric-card {
            padding: 0.7rem;
            border-radius: 8px;
            min-height: 80px;
        }
        .metric-card h3 { font-size: 0.7rem; }
        .metric-card h1 { font-size: 1.2rem; }
        .metric-card span { font-size: 0.65rem !important; }

        /* Butonları dokunmaya uygun büyüt */
        .stButton > button {
            min-height: 48px !important;
            font-size: 0.9rem !important;
        }

        /* Dataframe yatay kaydır */
        [data-testid="stDataFrame"] {
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }

        /* Sidebar varsayılan daralt */
        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 240px !important;
            max-width: 240px !important;
        }

        /* Expander başlıkları küçült */
        .streamlit-expanderHeader { font-size: 0.85rem !important; }
    }

    /* ── Çok küçük ekranlar (< 480px) → tek sütun ── */
    @media (max-width: 480px) {
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 0 0 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        .metric-card h1 { font-size: 1.1rem; }
    }
</style>
""", unsafe_allow_html=True)

# ─── 7 Sayfa Tanımları ───
tek_hisse = st.Page("pages/2_tek_hisse_analiz.py", title="Tek Hisse Analiz", icon="🔍", default=True)
piyasa_tarayici = st.Page("pages/1_piyasa_tarayici.py", title="Piyasa Tarayıcı", icon="📊")
sektor_radari = st.Page("pages/3_sektor_radari.py", title="Sektör & Makro Radarı", icon="🌍")

walkforward_lab = st.Page("pages/4_walkforward_lab.py", title="Walk-Forward Lab", icon="📈")
faktor_optimizasyonu = st.Page("pages/5_faktor_optimizasyonu.py", title="Faktör Optimizasyonu", icon="⚖️")

shadow_test = st.Page("pages/6_shadow_test.py", title="Shadow Test & Model Terfi", icon="🧪")
performans = st.Page("pages/7_performans.py", title="Performans & Sinyal Takibi", icon="📋")

# ─── Navigasyon Menüsü (3 Mantıksal Bölüm) ───
pg = st.navigation({
    "🔍 Analiz & Tarama": [tek_hisse, piyasa_tarayici, sektor_radari],
    "📐 Strateji & Backtest": [walkforward_lab, faktor_optimizasyonu],
    "🛡️ Model Denetimi & Performans": [shadow_test, performans],
})

# ─── Sidebar Branding ───
with st.sidebar:
    st.markdown("### 🏦 StockPredictionPro")
    st.caption("Factor Research & Equity Engine v3.1")
    st.divider()

pg.run()
