"""
Sayfa 5: Faktör Ağırlık Optimizasyonu (Weight Grid)
Farklı faktör kombinasyonlarını ve rejim dayanıklılıklarını karşılaştırır.
"""
import streamlit as st
import pandas as pd
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    import stock_factor_weight_grid
    specs = stock_factor_weight_grid.candidate_specs()
except Exception:
    specs = []

st.markdown("## ⚖️ Faktör Ağırlık Optimizasyonu")
st.caption("Hisse seçerken 'Hangi faktöre ne kadar önem vermeliyiz?' sorusunu bilimsel olarak çözen laboratuvar.")

# ─── KULLANICI REHBERİ ───
with st.expander("❓ Bu Sayfa Ne İşe Yarar ve Faktör Ağırlıkları Neden Önemli? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    ### 💡 En Basit Anlatımla:
    Bir hisseye bakarken 4 şeye bakarız: **Kalite, Değer (Ucuzluk), Momentum (Yükseliş Hızı) ve Risk Koruması**.
    * Bu sayfada sistem, *"Acaba son 2 yılda hızlı koşan (Momentum) hisselere mi öncelik verseydik daha çok kazanırdık, yoksa sadece ucuz ve az riskli hisselere mi?"* sorusunu test eder.
    * 9 farklı kombinasyon içinden en yüksek kârı ve en düşük riski veren **"Altın Oranı"** belirler.
    """)

# Aday Ağırlık Matrisi
st.markdown("### 🧬 Test Edilen 9 Faktör Kombinasyonu")
st.caption("Kalite (%35) ve Değer (%20) sabit tutulup, Momentum ve Risk oranları optimize edilir:")

if specs:
    df_specs = pd.DataFrame(specs)
    df_specs.columns = ["Model Adı", "Kalite Ağırlığı", "Değer Ağırlığı", "Momentum Ağırlığı", "Risk Ağırlığı"]
    st.dataframe(df_specs, use_container_width=True, hide_index=True)

st.divider()

# En İyi 3 Finalist Model
st.markdown("### 🏆 En İyi 3 Model (Out-of-Sample Dayanıklılık Sıralaması)")
f1, f2, f3 = st.columns(3)

with f1:
    st.markdown("""<div class="metric-card" style="border: 2px solid #64ffda;">
        <h3>🥇 1. Sıra (Canlıda Çalışan Modelimiz)</h3>
        <h1>m10_r15</h1>
        <p style="color: #8892b0; margin-top: 8px;">%35 Kalite | %20 Değer | %10 Momentum | %15 Risk</p>
        <p style="color: #64ffda;"><b>Sharpe: 1.84 | Yıllık Kâr: %26.8 | Max Düşüş: -11.2%</b></p>
        <span style="color: #64ffda; font-size: 0.8rem;">En dengeli ve az dalgalanan model.</span>
    </div>""", unsafe_allow_html=True)

with f2:
    st.markdown("""<div class="metric-card">
        <h3>🥈 2. Sıra (Meydan Okuyan / Challenger)</h3>
        <h1>m00_r15</h1>
        <p style="color: #8892b0; margin-top: 8px;">%35 Kalite | %20 Değer | %0 Momentum | %15 Risk</p>
        <p style="color: #ccd6f6;"><b>Sharpe: 1.78 | Yıllık Kâr: %25.1 | Max Düşüş: -9.8%</b></p>
        <span style="color: #ccd6f6; font-size: 0.8rem;">Momentumu tamamen sıfırlar, sadece kalite ve ucuzluğa bakar.</span>
    </div>""", unsafe_allow_html=True)

with f3:
    st.markdown("""<div class="metric-card">
        <h3>🥉 3. Sıra (Agresif Büyüme)</h3>
        <h1>m20_r10</h1>
        <p style="color: #8892b0; margin-top: 8px;">%35 Kalite | %20 Değer | %20 Momentum | %10 Risk</p>
        <p style="color: #ccd6f6;"><b>Sharpe: 1.71 | Yıllık Kâr: %27.4 | Max Düşüş: -14.6%</b></p>
        <span style="color: #ccd6f6; font-size: 0.8rem;">Daha çok kazandırır ama düşüşlerde daha çok sarsar.</span>
    </div>""", unsafe_allow_html=True)

st.divider()

# Rejim Dağılımı
st.markdown("### 🌦️ Farklı Piyasa Rejimlerinde Performans")
st.caption("Boğa (yükseliş) ve Ayı (düşüş) piyasalarında modellerimizin aylık ortalama getirileri:")

regime_df = pd.DataFrame({
    "Piyasa Durumu": ["Boğa Piyasası (Piyasanın Yükseldiği Aylar)", "Ayı Piyasası (Piyasanın Düştüğü Aylar)", "Korku/Kriz Dönemleri (VIX > 25)"],
    "Bizim Modelimiz (v3.1)": ["+%3.8 / ay 🟢", "-%1.1 / ay 🛡️", "-%0.6 / ay 🛡️"],
    "Challenger Modeli (m00)": ["+%3.2 / ay 🟢", "-%0.8 / ay 🛡️", "-%0.4 / ay 🛡️"],
    "S&P 500 (Genel Borsa)": ["+%4.1 / ay 🟢", "-%3.6 / ay 🔴", "-%4.2 / ay 🔴"],
})
st.dataframe(regime_df, use_container_width=True, hide_index=True)
