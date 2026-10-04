"""
StockPredictionPro Web Dashboard — Ana Uygulama
Streamlit multipage uygulaması (8 Modül, Mobil Öncelikli).
"""
import os
import sys
import streamlit as st

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
    /* ── Genel & Streamlit Süslerini Gizleme ── */
    .block-container { 
        padding-top: 1rem; 
        padding-bottom: 3rem;
    }
    [data-testid="stSidebar"] { background-color: #0a192f; }
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { 
        background: transparent; 
        z-index: 10;
    }
    .stDeployButton { display: none !important; }

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
        .block-container {
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
            padding-top: 0.5rem !important;
            padding-bottom: 5rem !important;
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
            border-radius: 10px;
            min-height: 80px;
        }
        .metric-card h3 { font-size: 0.7rem; }
        .metric-card h1 { font-size: 1.25rem; }
        .metric-card span { font-size: 0.68rem !important; }

        /* Butonları dokunmaya uygun büyüt (parmak dostu) */
        .stButton > button {
            min-height: 46px !important;
            font-size: 0.92rem !important;
            border-radius: 10px !important;
            font-weight: 600 !important;
        }

        /* Dataframe yatay kaydır */
        [data-testid="stDataFrame"] {
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }

        /* Sidebar genişliği */
        [data-testid="stSidebar"][aria-expanded="true"] {
            min-width: 250px !important;
            max-width: 250px !important;
        }

        .streamlit-expanderHeader { font-size: 0.85rem !important; }
    }

    /* ── Çok küçük ekranlar (< 480px) → tek sütun ── */
    @media (max-width: 480px) {
        [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
            flex: 0 0 100% !important;
            min-width: 100% !important;
            max-width: 100% !important;
        }
        .metric-card h1 { font-size: 1.15rem; }
    }
</style>
""", unsafe_allow_html=True)

# ─── 9 Sayfa Tanımları (Ana Sayfa Varsayılan) ───
ana_sayfa = st.Page("pages/0_ana_sayfa.py", title="Ana Sayfa", icon="📱", default=True)
portfoy_defteri = st.Page("pages/8_portfoy_defteri.py", title="Portföy & FIFO Defteri", icon="💼")
tek_hisse = st.Page("pages/2_tek_hisse_analiz.py", title="Tek Hisse Analiz", icon="🔍")
piyasa_tarayici = st.Page("pages/1_piyasa_tarayici.py", title="Piyasa Tarayıcı", icon="📊")
sektor_radari = st.Page("pages/3_sektor_radari.py", title="Sektör & Makro Radarı", icon="🌍")

walkforward_lab = st.Page("pages/4_walkforward_lab.py", title="Walk-Forward Lab", icon="📈")
faktor_optimizasyonu = st.Page("pages/5_faktor_optimizasyonu.py", title="Faktör Optimizasyonu", icon="⚖️")

shadow_test = st.Page("pages/6_shadow_test.py", title="Shadow Test & Model Terfi", icon="🧪")
performans = st.Page("pages/7_performans.py", title="Performans & Sinyal Takibi", icon="📋")

# ─── Navigasyon Menüsü ───
pg = st.navigation({
    "📱 Mobil & Hızlı Erişim": [ana_sayfa, portfoy_defteri],
    "🔍 Analiz & Tarama": [tek_hisse, piyasa_tarayici, sektor_radari],
    "📐 Strateji & Backtest": [walkforward_lab, faktor_optimizasyonu],
    "🛡️ Model Denetimi & Performans": [shadow_test, performans],
})

from web.components.auth import render_login_gate, render_sidebar_user_profile

# ─── SİBER GÜVENLİK KAPISI (AUTHENTICATION GATE) ───
render_login_gate()

# ─── Sidebar Branding & Hızlı Geçiş ───
with st.sidebar:
    render_sidebar_user_profile()
    st.markdown("### 🏦 StockPredictionPro")
    st.caption("Factor Research & Equity Engine v3.1")
    st.divider()
    st.markdown("**Hızlı Menü**")
    st.page_link("pages/0_ana_sayfa.py", label="Ana Sayfa", icon="📱")
    st.page_link("pages/8_portfoy_defteri.py", label="Portföy Defteri (FIFO)", icon="💼")
    st.page_link("pages/2_tek_hisse_analiz.py", label="Tek Hisse Analiz", icon="🔍")
    st.page_link("pages/1_piyasa_tarayici.py", label="Piyasa Tarayıcı", icon="📊")
    st.page_link("pages/3_sektor_radari.py", label="Sektör Radarı", icon="🌍")
    st.divider()

# ─── Güvenli Çalıştırma & Hata Kalkanı ───
try:
    pg.run()
except Exception as e:
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #1f1220 0%, #2e1622 100%); border: 1px solid #ef5350; border-radius: 12px; padding: 1.5rem; text-align: center; margin: 1.5rem 0;">
        <h3 style="color: #ef5350; margin: 0;">⚠️ Geçici Bağlantı / Veri Uyarısı</h3>
        <p style="color: #ccd6f6; margin: 0.8rem 0; font-size: 0.95rem;">
            Piyasa veri sağlayıcısı geçici olarak meşgul veya ağ yanıt vermedi.<br>
            Lütfen birkaç saniye sonra tekrar deneyin.
        </p>
    </div>
    """, unsafe_allow_html=True)
    if st.button("🔄 Sayfayı Yeniden Yükle", type="primary", use_container_width=True):
        st.rerun()
