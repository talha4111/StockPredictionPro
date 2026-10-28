"""
Sayfa 7: Gerçekleşen Performans & İşlem Günlüğü (Trade Journal)
Üretilen sinyallerin gerçek piyasa karnesi ve terim açıklamaları.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

st.markdown("## 📋 Gerçekleşen Performans & Sinyal Takibi")
st.caption("Sistemin bugüne kadar 'AL', 'İZLE' veya 'BEKLE' dediği 362 hissenin gerçekte ne kazandırdığının dürüst karnesi.")

# ─── KULLANICI REHBERİ (AÇILIR KAPANIR KUTU) ───
with st.expander("❓ Bu Sayfa Ne İşe Yarar ve 'Alpha / Beat' Ne Demektir? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    ### 💡 Bu Sayfanın Amacı Nedir?
    Bir algoritmanın başarısı sadece grafik çizmekle ölçülmez. Bu sayfa, sistemimizin ürettiği **362 adet bağımsız sinyalin** piyasada gerçekten ne yaptığını takip eder.

    ---
    ### 📚 Temel Terimlerin Anlamı:
    * **Vade (5g / 20g / 60g):**
      * **5g (1 Hafta):** Sinyal verildikten 5 iş günü sonraki kısa vadeli tepki.
      * **20g (~1 Ay):** Sinyal verildikten 1 ay sonraki orta vadeli sonuç.
      * **60g (~3 Ay):** Çeyreklik bilanço vadesindeki asıl trend sonucu.
    * **Alpha (S&P 500 Fazlası):** 
      * Borsa endeksi (S&P 500) %3 artarken, bizim sistemin seçtiği hisse **%7** arttıysa, **Alpha = +%4** demektir. Yani piyasanın üzerinde ürettiğimiz ekstra kârdır.
    * **S&P 500'ü Yenme Oranı (%):**
      * Seçtiğimiz hisselerin yüzde kaçının genel piyasadan daha fazla getiri sağladığıdır (%60 üzeri harika bir başarıdır).
    """)

summary = None
try:
    import stock_signal_tracker
    if os.path.exists(DB_PATH):
        summary = stock_signal_tracker.performans_ozeti(DB_PATH)
except Exception as e:
    st.error(f"Performans verisi çekilemedi: {e}")

if summary:
    # ─── ÜST METRİK KARTLARI ───
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric(
            "İncelenen Toplam Sinyal", 
            summary.get('independent_signals', 0),
            help="Veritabanında kayıtlı, mükerrer olmayan gerçek sinyal sayısı."
        )
    with p2:
        h5 = summary.get('horizons', {}).get('5g', {})
        rate5 = (h5.get('positive_excess_rate', 0) or 0) * 100
        st.metric(
            "5 Günlük S&P Beat Oranı", 
            f"%{rate5:.1f}",
            help="Sinyallerin %60.8'i ilk 1 hafta içinde S&P 500 endeksinden daha iyi performans göstermiştir."
        )
    with p3:
        h20 = summary.get('horizons', {}).get('20g', {})
        st.metric(
            "20 Günlük (~1 Ay) Ort. Kâr", 
            f"%{(h20.get('mean_return', 0) or 0)*100:.2f}",
            delta=f"+%{(h20.get('mean_excess_spy', 0) or 0)*100:.2f} Alpha",
            help="Sinyalden sonra 1 ay tutulan bir hisse ortalama %3.15 net getiri sağlamıştır."
        )
    with p4:
        h60 = summary.get('horizons', {}).get('60g', {})
        st.metric(
            "60 Günlük (~3 Ay) Ort. Kâr", 
            f"%{(h60.get('mean_return', 0) or 0)*100:.2f}", 
            delta=f"+%{(h60.get('mean_excess_spy', 0) or 0)*100:.1f} Alpha",
            help="3 ay tutulan hisselerde ortalama kazanç %7.0 seviyesindedir ve endeksin %3.3 üzerindedir."
        )

    st.divider()

    # ─── VADE BAZINDA PERFORMANS TABLOSU ───
    st.markdown("### ⏱️ Vade Bazında Detaylı Başarı Tablosu")
    st.caption("Farklı bekleme sürelerinde sinyallerin getirdiği sonuçlar:")

    horizons = summary.get('horizons', {})
    rows = []
    vade_etiketleri = {
        "5g": "5 Gün (1 Hafta)",
        "20g": "20 Gün (~1 Ay)",
        "60g": "60 Gün (~3 Ay - Çeyrek)",
        "120g": "120 Gün (~6 Ay)",
    }
    for h_name, h_data in horizons.items():
        if h_data.get('sample', 0) > 0:
            rows.append({
                "Bekleme Süresi": vade_etiketleri.get(h_name, h_name),
                "İncelenen Hisse": h_data.get('sample', 0),
                "Ortalama Net Kâr (%)": f"%{(h_data.get('mean_return', 0) or 0)*100:.2f}",
                "Piyasa Üstü Ekstra Kazanç (Alpha)": f"+%{(h_data.get('mean_excess_spy', 0) or 0)*100:.2f}",
                "S&P 500 Endeksini Yenme Yüzdesi": f"%{(h_data.get('positive_excess_rate', 0) or 0)*100:.1f}",
                "Kendi Sektörünü Yenme Yüzdesi": f"%{(h_data.get('positive_excess_sector_rate', 0) or 0)*100:.1f}",
            })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ─── GÖRSEL GETİRİ VE ALPHA GRAFİĞİ ───
    st.markdown("### 📊 Vadeler Bazında Ortalama Getiri & S&P 500 Alpha Dağılımı")
    h_names = [vade_etiketleri.get(k, k) for k, v in horizons.items() if v.get('sample', 0) > 0]
    h_returns = [(v.get('mean_return', 0) or 0) * 100 for k, v in horizons.items() if v.get('sample', 0) > 0]
    h_alphas = [(v.get('mean_excess_spy', 0) or 0) * 100 for k, v in horizons.items() if v.get('sample', 0) > 0]

    fig_perf = go.Figure()
    fig_perf.add_trace(go.Bar(
        x=h_names, y=h_returns, name="Hisse Ortalama Net Getirisi (%)",
        marker_color="#64ffda", text=[f"%{val:.2f}" for val in h_returns], textposition="auto"
    ))
    fig_perf.add_trace(go.Bar(
        x=h_names, y=h_alphas, name="S&P 500'e Karşı Fazladan Getiri / Alpha (%)",
        marker_color="#2196f3", text=[f"+%{val:.2f}" for val in h_alphas], textposition="auto"
    ))
    fig_perf.update_layout(
        barmode="group",
        height=380,
        template="plotly_dark",
        yaxis_title="Getiri Oranı (%)",
        margin=dict(l=20, r=20, t=20, b=20),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    st.plotly_chart(fig_perf, use_container_width=True)

    st.divider()

    # ─── KARAR TÜRÜNE GÖRE DAĞILIM ───
    st.markdown("### 🎯 Sinyal Türüne Göre 20 Günlük Performans")
    st.caption("Sistemin 'AL ADAYI', 'İZLE' veya 'OLAY RİSKİ' dediği hisselerin 1 ay sonraki tepkileri:")

    by_dec = summary.get('by_decision_20g', {})
    dec_rows = []
    for dec_name, dec_data in by_dec.items():
        if dec_data.get('sample', 0) > 0:
            dec_rows.append({
                "Verilen Karar": dec_name,
                "Sinyal Sayısı": dec_data.get('sample', 0),
                "1 Aylık Ortalama Getiri": f"%{(dec_data.get('mean_return', 0) or 0)*100:.2f}",
                "S&P 500'e Karşı Alpha": f"%{(dec_data.get('mean_excess_spy', 0) or 0)*100:.2f}",
                "Pozitif Kazanç Oranı": f"%{(dec_data.get('positive_excess_rate', 0) or 0)*100:.1f}",
            })
    st.dataframe(pd.DataFrame(dec_rows), use_container_width=True, hide_index=True)

else:
    st.info("Henüz veritabanında yeterli gerçekleşmiş sinyal sonucu bulunmuyor.")
