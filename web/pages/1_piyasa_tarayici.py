"""
Sayfa 1: Piyasa Tarayıcı (Opportunity Scanner)
Veritabanındaki son taramayı anında gösterir, session_state ile filtreleme sırasında kaybolmaz,
istendiğinde 100 hisselik tam taramayı yeniden çalıştırır.
"""
import streamlit as st
import pandas as pd
import sqlite3
import sys
import os
import io

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

try:
    from stock_value_engine import (
        tam_tarama_baslat,
        vix_oku,
        son_tarama_durumu_oku,
        KURUMSAL_HAVUZ,
    )
    ENGINE_AVAILABLE = True
except ImportError as e:
    ENGINE_AVAILABLE = False
    st.error(f"Motor import hatası: {e}")

st.markdown("## 📊 Piyasa Tarayıcı")
st.caption("Kurumsal havuzdaki hisseleri 4-Sütunlu faktör modeline göre puanlar, sıralar ve en iyi fırsatları listeler.")

# ─── KULLANICI REHBERİ ───
with st.expander("❓ Bu Sayfa Nasıl Kullanılır ve Sıralama Neye Göre Yapılır? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    * **Otomatik Tarama:** Sistem her iş günü ABD borsası kapandıktan sonra (gece ~01:30 TSİ) tüm havuzu kendisi tarar; sayfa açıldığında en taze liste beklemeden gelir.
    * **Sıralama (Sıra 1, 2, 3...):** Hisseler Faktör Skoruna (%100 üzerinden) göre en iyiden en kötüye doğru dizilir. 1. sıradaki hisse tüm borsada puanı en yüksek olandır.
    * **Filtreler:** Aşağıdaki kutulardan sadece `AL_ADAYI` olanları veya sadece ilgilendiğiniz bir sektörü (örn. `Energy`, `Technology`) seçebilirsiniz.
    * **Yeni Tarama:** Eğer en taze verilerle tüm hisseleri tekrar taratmak isterseniz aşağıdaki **"Yeniden Tam Tarama Başlat"** butonuna basabilirsiniz.
    """)

# VIX göstergesi (önbellekli)
@st.cache_data(ttl=300)
def get_cached_scanner_vix():
    try:
        val = vix_oku()
        return val
    except Exception:
        return 18.5

vix = get_cached_scanner_vix()
if vix:
    vix_color = "🟢" if vix < 15 else ("🟡" if vix < 25 else "🔴")
    st.sidebar.metric("VIX Endeksi", f"{vix:.1f} {vix_color}", help="15 altı sakin, 25 üzeri yüksek dalgalanma.")

st.sidebar.markdown(f"**Havuz Büyüklüğü:** {len(KURUMSAL_HAVUZ) if ENGINE_AVAILABLE else 'N/A'} hisse")

from web.components.scan_data import load_latest_scan, scan_age_days, _load_local

def load_db_scan_results():
    """Otomatik (GitHub) veya yerel en taze tarama listesini döndürür."""
    df, _src = load_latest_scan()
    return df

# Her sayfa açılışında taze listeyi al (filtreleme sırasında kaybolmaması için session_state'te tut)
_fresh_df, _scan_source = load_latest_scan()
_prev = st.session_state.get('scan_data')
if _prev is None or (not _fresh_df.empty and not _prev.empty and str(_fresh_df['Tarama Tarihi'].iloc[0]) > str(_prev['Tarama Tarihi'].iloc[0])) or (_prev is not None and _prev.empty):
    st.session_state['scan_data'] = _fresh_df
# Tarama başlatma butonu
col_btn1, col_btn2 = st.columns([1, 2])
with col_btn1:
    yeni_tarama = st.button("🚀 Yeniden Tam Tarama Başlat", type="primary", use_container_width=True)

if yeni_tarama:
    if not ENGINE_AVAILABLE:
        st.error("Motor yüklenemedi.")
        st.stop()

    progress_container = st.empty()
    progress_container.info("⏳ 100+ hisse için canlı tam tarama başlatıldı... Lütfen bekleyin (2-4 dk).")

    with st.spinner("Piyasa taranıyor..."):
        try:
            old_stdout = sys.stdout
            sys.stdout = captured = io.StringIO()

            sinyaller = tam_tarama_baslat()

            sys.stdout = old_stdout

            if sinyaller:
                # Yeni verileri çek ve session state'e yaz
                _load_local.clear(); st.cache_data.clear(); st.session_state['scan_data'] = load_db_scan_results()
                progress_container.success(f"✅ Tarama tamamlandı! {len(sinyaller)} hisse başarıyla güncellendi.")
            else:
                progress_container.warning("Tarama tamamlandı ancak yeni kayıt eklenemedi.")
        except Exception as e:
            sys.stdout = old_stdout
            st.error(f"Tarama hatası: {e}")

df = st.session_state['scan_data']

if df is not None and not df.empty:
    tarama_tarihi = df['Tarama Tarihi'].iloc[0] if 'Tarama Tarihi' in df.columns else 'Güncel'
    st.caption(f"📅 Görüntülenen Tarama Tarihi: **{tarama_tarihi}** (Toplam **{len(df)}** hisse)")
    _age = scan_age_days(str(tarama_tarihi))
    if _age is not None and _age > 4:
        st.warning(
            f"⚠️ Bu liste **{_age} gün önceki** bir taramaya ait. Otomatik tarama her iş günü gece çalışır; "
            f"güncel liste için '🚀 Yeniden Tam Tarama Başlat' butonunu kullanabilirsin."
        )
    elif _scan_source == "otomatik":
        st.success("🟢 Liste otomatik gece taramasından geliyor (her iş günü ABD borsası kapandıktan sonra yenilenir).")

    # ─── FİLTRELER ───
    st.divider()
    filter_col1, filter_col2, filter_col3 = st.columns([2, 2, 2])
    with filter_col1:
        karar_listesi = sorted(df['Karar'].dropna().unique().tolist())
        karar_filter = st.multiselect(
            "Karar Filtresi",
            options=karar_listesi,
            default=karar_listesi,
            help="Sadece belirli kararları görmek için seçim yapın."
        )
    with filter_col2:
        sektor_listesi = sorted(df['Sektör'].dropna().unique().tolist())
        sektor_filter = st.multiselect(
            "Sektör Filtresi",
            options=sektor_listesi,
            default=sektor_listesi,
            help="Sadece ilgilendiğiniz sektörleri görmek için seçim yapın."
        )
    with filter_col3:
        min_skor = st.slider("Minimum Faktör Skoru", min_value=30, max_value=90, value=50, step=5)

    # Filtreleme Uygula
    filtered_df = df[
        (df['Karar'].isin(karar_filter)) & 
        (df['Sektör'].isin(sektor_filter)) &
        (df['Faktör Skor (%)'] >= min_skor)
    ].copy()

    # ─── ÖZET METRİK KARTLARI ───
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        al_sayisi = len(filtered_df[filtered_df['Karar'].str.contains('AL|TOP20|SHADOW', case=False, na=False)])
        st.metric("🟢 Alım / Paper Adayı", al_sayisi)
    with m2:
        bekle_sayisi = len(filtered_df[filtered_df['Karar'].str.contains('BEKLE', case=False, na=False)])
        st.metric("🟡 Geri Çekilme Bekle", bekle_sayisi)
    with m3:
        izle_sayisi = len(filtered_df[filtered_df['Karar'] == 'IZLE'])
        st.metric("🔵 İzle", izle_sayisi)
    with m4:
        red_sayisi = len(filtered_df[filtered_df['Karar'].str.contains('REDDET', case=False, na=False)])
        st.metric("🔴 Trend Reddi", red_sayisi)

    # ─── TABLO ───
    st.dataframe(
        filtered_df,
        use_container_width=True,
        hide_index=True,
        height=550,
    )

    # CSV İndirme
    csv_data = filtered_df.to_csv(index=False).encode('utf-8-sig')
    st.download_button(
        "📥 Bu Tabloyu CSV (Excel) Olarak İndir",
        data=csv_data,
        file_name=f"piyasa_tarama_{tarama_tarihi}.csv",
        mime="text/csv",
    )
else:
    st.info("Henüz taranmış veri bulunmuyor. 'Yeniden Tam Tarama Başlat' butonuna basarak ilk taramanızı yapabilirsiniz.")
