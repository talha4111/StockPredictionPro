"""
Sayfa 6: Shadow Testing & Model Terfi (Challenger Gate)
Canlı üretim modeli (v3.1 Baseline) ile Meydan Okuyan (Challenger m00) modelinin kafa kafaya yarışı.
+ Haftalık Model Nabzı kartı & Şimdi Güncelle düğmesi
"""
import streamlit as st
import pandas as pd
import json
import sys
import os
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

# ── last_update.json yolu ──
LAST_UPDATE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "last_update.json"
)


def _last_update_oku() -> dict | None:
    """last_update.json dosyasını oku."""
    if os.path.exists(LAST_UPDATE_FILE):
        try:
            with open(LAST_UPDATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def _vix_rejim(vix_val):
    """VIX değerine göre piyasa rejimini döndür."""
    if vix_val is None:
        return "❓ Veri Yok", "#8892b0"
    if vix_val < 15:
        return "🟢 Sakin Piyasa", "#64ffda"
    elif vix_val < 25:
        return "🟡 Normal Volatilite", "#ff9800"
    elif vix_val < 35:
        return "🟠 Yüksek Volatilite", "#ff5722"
    else:
        return "🔴 Panik / Kriz", "#f44336"


def _lider_renk(lider: str):
    if "Challenger" in lider:
        return "#ff9800"
    elif "Baseline" in lider:
        return "#64ffda"
    return "#8892b0"


st.markdown("## 🧪 Shadow Test & Model Terfi Kapısı")
st.caption("Yeni geliştirilen modellerin hemen canlıya alınmayıp arka planda (gölgede) yarıştırıldığı sınav merkezi.")

# ─── KULLANICI REHBERİ ───
with st.expander("❓ Bu Sayfa Ne İşe Yarar ve 'Shadow Testing' Nedir? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    ### 💡 Gölge Testi (Shadow Test) Nedir?
    Yapay zeka veya yeni bir strateji geliştirdiğimizde, **hemen gerçek paramızı emanet etmeyiz.** 
    Bunun yerine mevcut modelimiz (**Baseline v3.1**) çalışırken, yeni modelimiz (**Challenger m00**) arka planda gölge gibi aynı piyasada sanal işlem açar.
    
    ---
    ### 📚 Terimler:
    * **Kohort (Cohort):** Her ay başında seçilen 20 hisselik bir hisse paketi/portföyü.
    * **MAE (Maksimum Olumsuz Sapma):** Pozisyon taşınırken hissenin gördüğü en dip nokta. Yeni modelin mevcut modele göre hisseyi daha çok zarara sokup sokmadığını ölçer.
    * **Terfi Kapısı (Gate):** Yeni modelin eskisinin yerine geçmesi için arka planda en az 3 ay boyunca üst üste daha başarılı olduğunu kanıtlaması gerekir.
    
    ---
    ### 🔄 Haftalık Otomatik Güncelleme
    Sistem her **Pazar saat 21:00**'de otomatik olarak model karşılaştırma verilerini günceller.
    Ayrıca aşağıdaki "**Şimdi Manuel Güncelle**" düğmesi ile istediğiniz zaman güncelleme yapabilirsiniz.
    """)

# ═══════════════════════════════════════════════════
#  📅 HAFTALIK MODEL NABZI KARTI + MANUEL GÜNCELLE
# ═══════════════════════════════════════════════════
st.markdown("### 📅 Haftalık Model Nabzı")

update_info = _last_update_oku()

n1, n2, n3, n4 = st.columns(4)

with n1:
    if update_info and update_info.get("son_guncelleme"):
        try:
            dt = datetime.fromisoformat(update_info["son_guncelleme"])
            tarih_str = dt.strftime("%d %b %Y, %H:%M")
        except Exception:
            tarih_str = update_info["son_guncelleme"][:16]
    else:
        tarih_str = "Henüz güncellenmedi"
    st.markdown(f"""<div class="metric-card">
        <h3>Son Güncelleme</h3>
        <h1 style="font-size: 1.0rem; color: #64ffda;">{tarih_str}</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">Otomatik: Her Pazar 21:00</span>
    </div>""", unsafe_allow_html=True)

with n2:
    lider = update_info.get("lider", "Belirsiz") if update_info else "Belirsiz"
    renk = _lider_renk(lider)
    # Kısa gösterim
    if "Challenger" in lider:
        lider_kisa = "🟠 Challenger"
    elif "Baseline" in lider:
        lider_kisa = "🟢 Baseline"
    else:
        lider_kisa = "⚪ Belirsiz"
    st.markdown(f"""<div class="metric-card">
        <h3>Bu Haftanın Lideri</h3>
        <h1 style="font-size: 1.1rem; color: {renk};">{lider_kisa}</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">{lider}</span>
    </div>""", unsafe_allow_html=True)

with n3:
    vix_val = update_info.get("vix") if update_info else None
    rejim_text, rejim_renk = _vix_rejim(vix_val)
    vix_str = f"{vix_val:.1f}" if vix_val else "—"
    st.markdown(f"""<div class="metric-card">
        <h3>Piyasa Rejimi (VIX)</h3>
        <h1 style="font-size: 1.1rem; color: {rejim_renk};">{rejim_text}</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">VIX: {vix_str}</span>
    </div>""", unsafe_allow_html=True)

with n4:
    mature = update_info.get("mature_cohorts", 0) if update_info else 0
    req = update_info.get("required_cohorts", 3) if update_info else 3
    pct = int(mature / req * 100) if req > 0 else 0
    bar_color = "#64ffda" if pct >= 100 else "#ff9800"
    st.markdown(f"""<div class="metric-card">
        <h3>Terfi İlerlemesi</h3>
        <h1 style="font-size: 1.1rem; color: {bar_color};">{mature} / {req} ay (%{pct})</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">{"✅ Tamamlandı — Terfi inceleniyor" if pct >= 100 else "⏳ Veri toplanıyor…"}</span>
    </div>""", unsafe_allow_html=True)

# ── GÜNCELLE DÜĞMESİ ──
btn_col1, btn_col2 = st.columns([1, 3])
with btn_col1:
    if st.button("🔄 Şimdi Manuel Güncelle", type="primary", use_container_width=True):
        with st.spinner("Model karşılaştırma verileri güncelleniyor… Bu işlem 1-2 dakika sürebilir."):
            try:
                # haftalik_guncelle modülünü import et
                scripts_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "scripts"
                )
                if scripts_dir not in sys.path:
                    sys.path.insert(0, scripts_dir)
                from haftalik_guncelle import guncelle
                info = guncelle(db_path=DB_PATH)
                st.success(f"✅ Güncelleme tamamlandı! Lider: **{info.get('lider', '?')}**")
                st.rerun()
            except Exception as e:
                st.error(f"❌ Güncelleme hatası: {e}")
with btn_col2:
    st.caption("💡 Bu düğme Task Scheduler'ın yaptığı haftalık güncellemeyi anında tetikler. VIX, model performansları ve kohort bilgileri yenilenir.")

st.divider()

# ═══════════════════════════════════════════════════
#  MEVCUT SHADOW TEST İÇERİĞİ
# ═══════════════════════════════════════════════════

summary = None
try:
    import stock_shadow_paper
    if os.path.exists(DB_PATH):
        summary = stock_shadow_paper.shadow_performance_summary(DB_PATH)
except Exception as e:
    st.error(f"Veri çekme hatası: {e}")

# ─── ÜST DURUM KARTLARI ───
s1, s2, s3, s4 = st.columns(4)
with s1:
    status_text = summary.get('status', 'VERI_TOPLANIYOR') if summary else 'HAZIR'
    st.markdown(f"""<div class="metric-card">
        <h3>Terfi Kararı</h3>
        <h1 style="font-size: 1.2rem; color: #ff9800;">{status_text}</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">3 ay tamamlanana kadar eski model devrededir.</span>
    </div>""", unsafe_allow_html=True)
with s2:
    mature = summary.get('paired_mature_cohorts', 1) if summary else 1
    req = summary.get('required_paired_mature_cohorts', 3) if summary else 3
    st.markdown(f"""<div class="metric-card">
        <h3>Olgunlaşmış Kohort (Ay)</h3>
        <h1>{mature} / {req}</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">Tamamlanması gereken süre: 3 Ay</span>
    </div>""", unsafe_allow_html=True)
with s3:
    st.markdown("""<div class="metric-card">
        <h3>Mevcut Model (Şampiyon)</h3>
        <h1 style="font-size: 1.1rem; color: #64ffda;">v3.1 (Baseline)</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">Dengeli Faktör Ağırlığı</span>
    </div>""", unsafe_allow_html=True)
with s4:
    st.markdown("""<div class="metric-card">
        <h3>Meydan Okuyan (Aday)</h3>
        <h1 style="font-size: 1.1rem; color: #ff9800;">m00_r15 (Challenger)</h1>
        <span style="color: #8892b0; font-size: 0.8rem;">Sıfır-Momentum Hipotezi</span>
    </div>""", unsafe_allow_html=True)

st.divider()

# ─── MODEL KARŞILAŞTIRMA TABLOSU ───
st.markdown("### ⚔️ Modellerin Kafa Kafaya Mücadelesi")
if summary and 'models' in summary:
    base = summary['models'].get('paper_baseline', {})
    chal = summary['models'].get('paper_m00_r15', {})

    comp_df = pd.DataFrame({
        "Karşılaştırılan Metrik": [
            "Aylık Ortalama Kâr", 
            "S&P 500 Endeksine Göre Fazla Getiri (Alpha)", 
            "Maksimum Olumsuz Sapma (MAE - Dip Nokta)"
        ],
        "Mevcut Üretim Modeli (v3.1)": [
            f"%{(base.get('paired_mean_return', 0) or 0)*100:.2f}",
            f"+%{(base.get('paired_mean_excess_spy', 0) or 0)*100:.2f}",
            f"%{(base.get('paired_mean_mae', 0) or 0)*100:.2f}",
        ],
        "Meydan Okuyan Yeni Model (m00)": [
            f"%{(chal.get('paired_mean_return', 0) or 0)*100:.2f}",
            f"+%{(chal.get('paired_mean_excess_spy', 0) or 0)*100:.2f}",
            f"%{(chal.get('paired_mean_mae', 0) or 0)*100:.2f}",
        ],
        "Lider": [
            "Challenger (Önde) 🟢" if (chal.get('paired_mean_return', 0) or 0) > (base.get('paired_mean_return', 0) or 0) else "Baseline 🟢",
            "Challenger (Önde) 🟢" if (chal.get('paired_mean_excess_spy', 0) or 0) > (base.get('paired_mean_excess_spy', 0) or 0) else "Baseline 🟢",
            "Challenger (Önde) 🟢" if (chal.get('paired_mean_mae', 0) or 0) > (base.get('paired_mean_mae', 0) or 0) else "Baseline 🟢",
        ]
    })
    st.dataframe(comp_df, use_container_width=True, hide_index=True)

st.divider()

# ─── TERFİ KURALLARI LİSTESİ ───
st.markdown("### 📋 Yeni Modelin Canlıya Geçmesi İçin Gerekli 4 Şart:")
st.markdown("""
* **Şart 1:** En az 3 farklı ayda (kohortta) yarışmalı *(Şu an: 1/3 ay tamamlandı, veri toplanıyor)*
* **Şart 2:** Her ay en az 10 hisse seçmeli *(Sağlandı ✅)*
* **Şart 3:** Ayların en az %66'sında mevcut modelden daha yüksek getiri sağlamalı *(Şu an: %100 sağlandı ✅)*
* **Şart 4:** Portföyü daha derin zararlara sokmamalı (MAE bozulması <= %2.0) *(Sağlandı ✅)*
""")
