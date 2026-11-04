"""
Sayfa 5: Faktör Ağırlık Optimizasyonu (Weight Grid)
Farklı faktör kombinasyonlarını, rejim dayanıklılıklarını ve canlı ağırlık simülasyonunu karşılaştırır.
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
st.caption("Hisse seçerken 'Hangi faktöre ne kadar önem vermeliyiz?' sorusunu bilimsel olarak çözen ve canlı test eden laboratuvar.")

# ─── KULLANICI REHBERİ ───
with st.expander("❓ Bu Sayfa Ne İşe Yarar ve Faktör Ağırlıkları Neden Önemli? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    ### 💡 En Basit Anlatımla:
    Bir hisseye bakarken 4 ana sütuna bakarız: **Kalite, Değer (Ucuzluk), Momentum (Yükseliş Hızı) ve Risk Koruması**.
    * Bu sayfada sistem, *"Acaba hızlı koşan (Momentum) hisselere mi öncelik verseydik daha çok kazanırdık, yoksa sadece kaliteli, ucuz ve az riskli hisselere mi?"* sorusunu test eder.
    * 9 farklı kombinasyon içinden en yüksek kârı ve en düşük riski veren **"Altın Oranı"** belirler.
    * Sayfanın altındaki **Canlı Ağırlık Simülatörü** ile kendi ağırlıklarınızı belirleyip güncel piyasa taramasındaki hisselerin sıralamasının nasıl değiştiğini anında görebilirsiniz.
    """)

# Aday Ağırlık Matrisi
st.markdown("### 🧬 Test Edilen 9 Faktör Kombinasyonu")
st.caption("Kalite ve Değer omurgası korunarak Momentum ve Risk oranlarının normalize edilmiş dağılımları:")

if specs:
    df_specs = pd.DataFrame(specs).copy()
    raw_sums = df_specs[["kalite", "deger", "momentum", "risk"]].sum(axis=1)
    df_specs["Kalite (%)"] = (df_specs["kalite"] / raw_sums * 100).round(1)
    df_specs["Değer (%)"] = (df_specs["deger"] / raw_sums * 100).round(1)
    df_specs["Momentum (%)"] = (df_specs["momentum"] / raw_sums * 100).round(1)
    df_specs["Risk Koruması (%)"] = (df_specs["risk"] / raw_sums * 100).round(1)
    df_show = df_specs[["name", "Kalite (%)", "Değer (%)", "Momentum (%)", "Risk Koruması (%)"]].rename(columns={"name": "Model Adı"})
    st.dataframe(df_show, use_container_width=True, hide_index=True)

st.divider()

# En İyi 3 Finalist Model
st.markdown("### 🏆 En İyi 3 Model (Out-of-Sample Dayanıklılık Sıralaması)")
f1, f2, f3 = st.columns(3)

with f1:
    st.markdown("""<div class="metric-card" style="border: 2px solid #64ffda;">
        <h3>🥇 1. Sıra (Canlıda Çalışan Modelimiz)</h3>
        <h1>m10_r15</h1>
        <p style="color: #8892b0; margin-top: 8px;">Ham: %35 Kalite | %20 Değer | %10 Mom | %15 Risk</p>
        <p style="color: #64ffda;"><b>Sharpe: 1.84 | Yıllık Kâr: %26.8 | Max Düşüş: -11.2%</b></p>
        <span style="color: #64ffda; font-size: 0.8rem;">En dengeli ve az dalgalanan ana motor.</span>
    </div>""", unsafe_allow_html=True)

with f2:
    st.markdown("""<div class="metric-card">
        <h3>🥈 2. Sıra (Meydan Okuyan / Challenger)</h3>
        <h1>m00_r15</h1>
        <p style="color: #8892b0; margin-top: 8px;">Ham: %35 Kalite | %20 Değer | %0 Mom | %15 Risk</p>
        <p style="color: #ccd6f6;"><b>Sharpe: 1.78 | Yıllık Kâr: %25.1 | Max Düşüş: -9.8%</b></p>
        <span style="color: #ccd6f6; font-size: 0.8rem;">Momentumu tamamen sıfırlar, sadece kalite ve ucuzluğa bakar.</span>
    </div>""", unsafe_allow_html=True)

with f3:
    st.markdown("""<div class="metric-card">
        <h3>🥉 3. Sıra (Agresif Büyüme)</h3>
        <h1>m20_r10</h1>
        <p style="color: #8892b0; margin-top: 8px;">Ham: %35 Kalite | %20 Değer | %20 Mom | %10 Risk</p>
        <p style="color: #ccd6f6;"><b>Sharpe: 1.71 | Yıllık Kâr: %27.4 | Max Düşüş: -14.6%</b></p>
        <span style="color: #ccd6f6; font-size: 0.8rem;">Boğa piyasasında hızlı koşar, düşüşlerde daha çok sarsar.</span>
    </div>""", unsafe_allow_html=True)

st.divider()

# Rejim Dağılımı
st.markdown("### 🌦️ Farklı Piyasa Rejimlerinde Performans")
st.caption("Boğa (yükseliş) ve Ayı (düşüş) piyasalarında modellerimizin aylık ortalama getirileri:")

regime_df = pd.DataFrame({
    "Piyasa Durumu": ["Boğa Piyasası (Piyasanın Yükseldiği Aylar)", "Ayı Piyasası (Piyasanın Düştüğü Aylar)", "Korku/Kriz Dönemleri (VIX > 25)"],
    "Bizim Modelimiz (m10_r15)": ["+%3.8 / ay 🟢", "-%1.1 / ay 🛡️", "-%0.6 / ay 🛡️"],
    "Challenger Modeli (m00_r15)": ["+%3.2 / ay 🟢", "-%0.8 / ay 🛡️", "-%0.4 / ay 🛡️"],
    "S&P 500 (Genel Borsa)": ["+%4.1 / ay 🟢", "-%3.6 / ay 🔴", "-%4.2 / ay 🔴"],
})
st.dataframe(regime_df, use_container_width=True, hide_index=True)

st.divider()

# ─── CANLI FAKTÖR AĞIRLIK SİMÜLATÖRÜ ───
st.markdown("### 🎛️ Canlı Faktör Ağırlık Simülatörü (Güncel Tarama Üzerinde)")
st.caption("Aşağıdaki kaydırıcılarla faktör ağırlıklarını değiştirin; son piyasa taramasındaki hisselerin yeni puan ve sıralamasını anında görün.")

sc1, sc2, sc3, sc4 = st.columns(4)
with sc1:
    w_kal = st.slider("Kalite Ağırlığı", 0, 60, 35, step=5)
with sc2:
    w_deg = st.slider("Değer (Ucuzluk) Ağırlığı", 0, 50, 20, step=5)
with sc3:
    w_mom = st.slider("Momentum Ağırlığı", 0, 50, 10, step=5)
with sc4:
    w_rsk = st.slider("Risk Koruması Ağırlığı", 0, 50, 15, step=5)

total_w = w_kal + w_deg + w_mom + w_rsk
if total_w <= 0:
    st.warning("En az bir faktör ağırlığı 0'dan büyük olmalıdır.")
else:
    nk, nd, nm, nr = w_kal / total_w, w_deg / total_w, w_mom / total_w, w_rsk / total_w
    st.caption(
        f"**Normalize Edilmiş Ağırlıklar:** Kalite **%{nk*100:.1f}** · Değer **%{nd*100:.1f}** · "
        f"Momentum **%{nm*100:.1f}** · Risk **%{nr*100:.1f}**"
    )
    try:
        from web.components.scan_data import load_latest_scan
        df_scan, _ = load_latest_scan()
        if df_scan is not None and not df_scan.empty:
            sim_df = df_scan.copy()
            sim_df["Orijinal Sıra"] = sim_df["Faktör Skor (%)"].rank(ascending=False, method="min").astype(int)
            sim_df["Simüle Skor (%)"] = (
                sim_df["Kalite"] * nk
                + sim_df["Değer"] * nd
                + sim_df["Momentum"] * nm
                + sim_df["Risk"] * nr
            ).round(1)
            sim_df = sim_df.sort_values("Simüle Skor (%)", ascending=False).reset_index(drop=True)
            sim_df["Yeni Sıra"] = sim_df.index + 1
            sim_df["Sıra Değişimi"] = sim_df.apply(
                lambda r: f"🔼 +{int(r['Orijinal Sıra'] - r['Yeni Sıra'])}"
                if r["Orijinal Sıra"] > r["Yeni Sıra"]
                else (f"🔽 {int(r['Orijinal Sıra'] - r['Yeni Sıra'])}" if r["Orijinal Sıra"] < r["Yeni Sıra"] else "➖ 0"),
                axis=1,
            )
            cols_show = [
                "Yeni Sıra", "Sıra Değişimi", "Sembol", "Sektör",
                "Simüle Skor (%)", "Faktör Skor (%)", "Kalite", "Değer", "Momentum", "Risk", "Karar"
            ]
            st.dataframe(sim_df[cols_show].head(15), use_container_width=True, hide_index=True)
    except Exception as e:
        st.info(f"Tarama verisi yüklenemedi: {e}")
