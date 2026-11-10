"""
StockPredictionPro Web Dashboard — Ana Uygulama
Streamlit çok sayfalı uygulama: 4 ana sayfa + Gelişmiş araçlar (mobil öncelikli).
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
    initial_sidebar_state="auto",
)

from web.components.ui import inject_global_css  # noqa: E402

inject_global_css()

# ─── Sayfa Tanımları ───
ana_sayfa = st.Page("pages/0_ana_sayfa.py", title="Ana Sayfa", icon="🏠", default=True)
ai_analist = st.Page("pages/10_ai_analist.py", title="AI Uzman Analist", icon="🧠")
tek_hisse = st.Page("pages/2_tek_hisse_analiz.py", title="Hisse Analizi", icon="🔎")
alim_avcisi = st.Page("pages/9_alim_avcisi.py", title="Alım & Satış Avcısı", icon="🎯")
portfoy_defteri = st.Page("pages/8_portfoy_defteri.py", title="Portföy & Risk", icon="💼")

piyasa_tarayici = st.Page("pages/1_piyasa_tarayici.py", title="Piyasa Tarayıcı", icon="📊")
sektor_radari = st.Page("pages/3_sektor_radari.py", title="Sektör Radarı", icon="🌍")
walkforward_lab = st.Page("pages/4_walkforward_lab.py", title="Walk-Forward Lab", icon="📈")
faktor_optimizasyonu = st.Page("pages/5_faktor_optimizasyonu.py", title="Faktör Optimizasyonu", icon="⚖️")
shadow_test = st.Page("pages/6_shadow_test.py", title="Shadow Test", icon="🧪")
performans = st.Page("pages/7_performans.py", title="Performans Takibi", icon="📋")

# ─── Navigasyon: Ana menü + Gelişmiş araçlar ───
pg = st.navigation({
    "Ana Menü": [ana_sayfa, ai_analist, tek_hisse, alim_avcisi, portfoy_defteri],
    "Gelişmiş": [piyasa_tarayici, sektor_radari, walkforward_lab, faktor_optimizasyonu, shadow_test, performans],
})

from web.components.security_shield import apply_security_shield, render_security_shield_widget  # noqa: E402
from web.components.auth import render_login_gate, render_sidebar_user_profile  # noqa: E402

# ─── SİBER GÜVENLİK KALKANI & WAF SAVUNMASI (LAYER 3) ───
apply_security_shield()

# ─── KİMLİK DOĞRULAMA & 2FA KAPISI (LAYER 1) ───
render_login_gate()

# ─── Sidebar: Kullanıcı Profili ───
with st.sidebar:
    render_sidebar_user_profile()

    # Yönetici (Admin) ise Güvenlik Kalkanı Denetim Widget'ını Göster
    user_session = st.session_state.get("user", {})
    if user_session.get("role") == "admin":
        render_security_shield_widget()

    st.caption("StockPredictionPro · v3.3")

# ─── Güvenli Çalıştırma & Hata Kalkanı ───
try:
    pg.run()
except Exception:
    st.error("Piyasa veri sağlayıcısı geçici olarak yanıt vermedi. Birkaç saniye sonra tekrar deneyin.")
    if st.button("Sayfayı Yeniden Yükle", type="primary", use_container_width=True):
        st.rerun()
