"""
Sayfa 8: 💼 Portföy Defteri (FIFO + TL + Vergi)
Midas uyumlu FIFO lot eritme, Dolar & TL kâr/zarar takibi,
vergi taslağı ve Google Sheets kalıcı depolama.
"""
from datetime import datetime
import os
import sys
import pandas as pd
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import plotly.express as px
from web.components.portfolio_tracker import (
    add_transaction,
    calculate_fifo_portfolio,
    delete_transaction,
    get_current_usdtry,
    load_transactions,
)
from web.components.mobile import get_cached_quotes
from web.components.stress_test import calculate_portfolio_metrics, run_stress_scenarios

# ─── SAYFA BAŞLIĞI ───
st.markdown("## 💼 Gerçek Portföy Defteri (FIFO & Vergi)")
st.caption("Midas alım/satımlarınızı kaydedin; FIFO lot erimesini, TL bazlı reel getiriyi ve vergi taslağınızı görün.")

# Anlık Kur
usdtry = get_current_usdtry()
transactions = load_transactions()
open_positions, closed_trades = calculate_fifo_portfolio(transactions)

# Canlı Fiyatları Çek
open_symbols = tuple(open_positions.keys())
live_quotes = get_cached_quotes(open_symbols) if open_symbols else {}

# Genel Metrikler
toplam_maliyet_usd = sum(p["toplam_maliyet_usd"] for p in open_positions.values())
toplam_maliyet_tl = sum(p["toplam_maliyet_tl"] for p in open_positions.values())

toplam_guncel_usd = 0.0
for sym, p in open_positions.items():
    cur_p = live_quotes.get(sym, {}).get("price") or p["ortalama_fiyat_usd"]
    toplam_guncel_usd += p["toplam_adet"] * cur_p

toplam_guncel_tl = toplam_guncel_usd * usdtry
unrealized_pnl_usd = toplam_guncel_usd - toplam_maliyet_usd
unrealized_pnl_tl = toplam_guncel_tl - toplam_maliyet_tl
unrealized_pct = (unrealized_pnl_usd / toplam_maliyet_usd * 100) if toplam_maliyet_usd > 0 else 0.0

realized_pnl_usd = sum(t["kar_usd"] for t in closed_trades)
realized_pnl_tl = sum(t["kar_tl"] for t in closed_trades)

# ─── ÜST ÖZET KARTLARI ───
m1, m2, m3, m4 = st.columns(4)
with m1:
    st.metric("Toplam Varlık ($)", f"${toplam_guncel_usd:,.2f}", delta=f"{unrealized_pct:+.2f}%")
with m2:
    st.metric("Toplam Varlık (₺)", f"{toplam_guncel_tl:,.0f} ₺", delta=f"{unrealized_pnl_tl:+,.0f} ₺")
with m3:
    st.metric("Gerçekleşmiş Kâr ($)", f"${realized_pnl_usd:+,.2f}", help="Kapatılan pozisyonların toplam kâr/zararı")
with m4:
    st.metric("Anlık Kur (USD/TRY)", f"{usdtry:.4f} ₺", help="Piyasa kuru")

st.divider()

# ─── SEKMELER ───
tab1, tab_stres, tab2, tab3, tab4, tab5 = st.tabs([
    "📊 Açık Pozisyonlar & Lotlar",
    "⚠️ Yoğunlaşma & Stres Testi",
    "➕ Yeni İşlem Ekle",
    "💰 Kapanan İşlemler (FIFO)",
    "📜 Vergi Taslağı",
    "☁️ Bulut Senkronizasyonu",
])

# ─── TAB 1: AÇIK POZİSYONLAR & LOT RÖNTGENİ ───
with tab1:
    if not open_positions:
        st.info("Henüz açık pozisyonunuz bulunmuyor. '➕ Yeni İşlem Ekle' sekmesinden alımlarınızı kaydedebilirsiniz.")
    else:
        st.markdown("### 📈 Açık Pozisyon Özeti")
        summary_rows = []
        for sym, p in open_positions.items():
            cur_p = live_quotes.get(sym, {}).get("price") or p["ortalama_fiyat_usd"]
            cur_val = p["toplam_adet"] * cur_p
            pnl_u = cur_val - p["toplam_maliyet_usd"]
            pnl_pct = (pnl_u / p["toplam_maliyet_usd"] * 100) if p["toplam_maliyet_usd"] > 0 else 0.0
            pnl_t = (cur_val * usdtry) - p["toplam_maliyet_tl"]

            summary_rows.append({
                "Hisse": sym,
                "Adet": f"{p['toplam_adet']:g}",
                "Ort. Maliyet ($)": f"${p['ortalama_fiyat_usd']:.2f}",
                "Ort. Maliyet (₺)": f"{p['ortalama_maliyet_tl']:.2f} ₺",
                "Güncel Fiyat": f"${cur_p:.2f}",
                "Piyasa Değeri ($)": f"${cur_val:,.2f}",
                "Kâr/Zarar ($)": f"{pnl_u:+,.2f} ({pnl_pct:+.1f}%)",
                "Kâr/Zarar (₺)": f"{pnl_t:+,.0f} ₺",
                "Lot Sayısı": p["lot_sayisi"],
            })

        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.markdown("### 🔍 FIFO Lot Röntgeni (Midas Eritme Sırası)")
        st.caption("Midas'ta satış yaptığınızda ilk satılan lot en eski olandır. Aşağıda lotlarınızın bekleme sırasını görebilirsiniz:")

        for sym, p in open_positions.items():
            with st.expander(f"📌 {sym} — {p['toplam_adet']:g} Adet ({p['lot_sayisi']} Farklı Lot) — İncele"):
                lot_rows = []
                for idx, lot in enumerate(p["lotlar"]):
                    cur_p = live_quotes.get(sym, {}).get("price") or lot["fiyat_usd"]
                    l_val = lot["adet_kalan"] * cur_p
                    l_cost = lot["adet_kalan"] * lot["fiyat_usd"]
                    l_pnl = l_val - l_cost
                    l_pct = (l_pnl / l_cost * 100) if l_cost > 0 else 0.0

                    status = "🎯 İLK SATILACAK LOT" if idx == 0 else f"{idx + 1}. Sırada"
                    lot_rows.append({
                        "Sıra": status,
                        "Alış Tarihi": lot["tarih"],
                        "Kalan Adet": f"{lot['adet_kalan']:g}",
                        "Alış Fiyatı ($)": f"${lot['fiyat_usd']:.2f}",
                        "Alış Kuru (₺)": f"{lot['usdtry_kuru']:.2f} ₺",
                        "Güncel Kâr ($)": f"{l_pnl:+,.2f} ({l_pct:+.1f}%)",
                    })
                st.dataframe(pd.DataFrame(lot_rows), use_container_width=True, hide_index=True)

        # ─── MOD #6 & #12: YATIRIM TEZİ & OTOMATİK HEDEF TAKİBİ (THESIS MONITOR) ───
        st.divider()
        st.markdown("### 🎯 Yatırım Tezi & Otomatik Hedef Takibi (Thesis Monitor)")
        st.caption("Elindeki hisselerin kâr koruma sınırını, ilk satış hedefini ve yatırım tezinin bozulup bozulmadığını canlı izler.")

        from web.components.dip_hunter import analyze_stock_exit, load_dip_config
        for sym, p in open_positions.items():
            ex_info = analyze_stock_exit(sym, user_pos=p)
            if ex_info:
                # Son alış notlarını birleştir
                sym_notes = [
                    t.get("notlar", "").strip()
                    for t in transactions
                    if t.get("sembol") == sym and t.get("islem_tipi") == "ALIS" and t.get("notlar", "").strip()
                ]
                note_text = sym_notes[-1] if sym_notes else "Kademeli büyüme & değerleme tezi"
                b_col = ex_info["exit_color"]
                st.markdown(f"""
                <div style="background:#0d1b2a; border-left:5px solid {b_col}; border:1px solid #233554;
                            border-radius:10px; padding:12px 15px; margin-bottom:10px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
                        <span style="font-size:1.1rem; font-weight:800; color:#fff;">{sym} — Tez Durumu</span>
                        <span style="background:{b_col}22; border:1px solid {b_col}; color:{b_col};
                                     padding:4px 12px; border-radius:16px; font-size:0.8rem; font-weight:700;">
                            {ex_info['exit_badge']}
                        </span>
                    </div>
                    <div style="color:#8892b0; font-size:0.84rem; margin-top:6px;">
                        📓 <b>Kayıtlı Alım Notun / Tezin:</b> <i>"{note_text}"</i>
                    </div>
                    <div style="color:#ccd6f6; font-size:0.9rem; margin-top:6px;">
                        {ex_info['action_advice']}
                    </div>
                    <div style="display:flex; gap:18px; flex-wrap:wrap; margin-top:8px; font-size:0.84rem; color:#64ffda;">
                        <span>💰 <b>1. Kâr Hedefi:</b> ${ex_info['take_profit_1']:.2f}</span>
                        <span>🔥 <b>2. Ana Zirve Hedefi:</b> ${ex_info['take_profit_2']:.2f}</span>
                        <span>🛡️ <b>Kâr Koruma / Destek Sınırı:</b> ${ex_info['profit_shield_line']:.2f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

# ─── TAB 2 (STRES): RİSK KOMUTA MERKEZİ, YOĞUNLAŞMA & STRES TESTİ ───
with tab_stres:
    if not open_positions:
        st.info("Risk ve stres testi için henüz açık pozisyonunuz bulunmuyor.")
    else:
        st.markdown("### 🛡️ Portföy Risk Komuta Merkezi & Stres Testi")
        st.caption("Portföyünüzün günlük maksimum kayıp riskini (VaR), takip listenizle olan ikiz hareket (korelasyon) tehlikesini ve kriz senaryolarını inceleyin.")

        from web.components.dip_hunter import load_dip_config
        wl_syms = load_dip_config().get("symbols", ["MU", "COHR", "MRVL", "RKLB", "VST", "AVGO"])

        with st.spinner("VaR, beklenen kayıp, korelasyon ve pozisyon büyüklükleri hesaplanıyor..."):
            stress_metrics = calculate_portfolio_metrics(open_positions, live_quotes, watchlist_symbols=wl_syms)

        if stress_metrics:
            p_beta = stress_metrics["portfolio_beta"]
            p_val = stress_metrics["total_value_usd"]
            weights = stress_metrics["weights"]
            betas = stress_metrics["betas"]
            corr_mat = stress_metrics["correlation_matrix"]

            beta_renk = "🟢 Düşük Risk" if p_beta < 1.0 else ("🟡 Piyasa Paralel" if p_beta < 1.35 else "🔴 Yüksek Oynaklık")

            r1, r2, r3, r4 = st.columns(4)
            with r1:
                st.metric("Portföy Betası (S&P 500)", f"{p_beta:.2f}x", delta=beta_renk)
            with r2:
                st.metric(
                    "Günlük VaR (%95 Güven)",
                    f"-${stress_metrics['var_95_usd']:,.0f}",
                    delta=f"{stress_metrics['var_95_pct']:.1f}% (Normal Kötü Gün)",
                    delta_color="inverse",
                )
            with r3:
                st.metric(
                    "Kuyruk Riski (Expected Shortfall)",
                    f"-${stress_metrics['cvar_95_usd']:,.0f}",
                    delta=f"{stress_metrics['cvar_95_pct']:.1f}% (Sert Satış Günü)",
                    delta_color="inverse",
                )
            with r4:
                st.metric(
                    "1 Yıllık Maksimum Düşüş",
                    f"%{stress_metrics['max_dd_pct']:.1f}",
                    delta="Zirveden En Derin Çekilme",
                    delta_color="inverse",
                )

            if stress_metrics.get("high_corr_pairs"):
                pairs_txt = ", ".join(
                    f"**{a}–{b}** (%{c} benzer)" for a, b, c in stress_metrics["high_corr_pairs"][:5]
                )
                st.warning(
                    f"⚠️ **İkiz Hareket (Yüksek Korelasyon) Uyarısı:** Portföy ve takip listendeki şu hisseler "
                    f"birbiriyle neredeyse aynı gün düşüp aynı gün çıkıyor: {pairs_txt}. "
                    f"Bu hisselerin hepsine aynı anda yüklü girmek, tek bir hisseye bütün parayı yatırmakla aynı riski taşır!"
                )

            # Korelasyon Isı Haritası (Portföy + Takip Listesi)
            if not corr_mat.empty and len(corr_mat) >= 2:
                st.divider()
                st.markdown("#### 🔥 Portföy & Takip Listesi Korelasyon (İkiz Hareket) Haritası")
                st.caption("1.00'e yakın koyu kırmızı kutular, iki hissenin aynı anda düştüğünü (ikiz hareket ettiğini) gösterir.")
                fig_corr = px.imshow(
                    corr_mat, text_auto=True, aspect="auto",
                    color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                    template="plotly_dark", height=340
                )
                fig_corr.update_layout(margin=dict(l=10, r=10, t=10, b=10))
                st.plotly_chart(fig_corr, use_container_width=True)

            # Volatiliteye Göre Pozisyon Büyüklüğü Önerisi
            if stress_metrics.get("sizing_table"):
                st.divider()
                st.markdown("#### 📏 Oynaklığa (Volatiliteye) Göre İdeal Pozisyon Büyüklüğü Rehberi")
                st.caption("Çok sert dalgalanan (yüksek beta) hisselere portföyde daha küçük pay ayırarak ani düşüşlerde kasanızı koruyun:")
                st.dataframe(pd.DataFrame(stress_metrics["sizing_table"]), use_container_width=True, hide_index=True)

            # Kriz Simülasyonu
            st.divider()
            st.markdown("#### ⚡ Piyasa ve Sektör Şok Stres Testleri")
            st.caption("Piyasa -%5, Teknoloji/Çip sektörü -%10 veya -%20 düştüğünde mevcut portföyünüzün tahmini dolar ve TL kaybı:")

            sc_results = run_stress_scenarios(p_val, p_beta, usdtry)
            st.dataframe(pd.DataFrame(sc_results), use_container_width=True, hide_index=True)

# ─── TAB 3: YENİ İŞLEM EKLE ───
with tab2:
    st.markdown("### ➕ Alış veya Satış İşlemi Kaydet")
    with st.form("yeni_islem_formu", clear_on_submit=True):
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            tx_tipi = st.selectbox("İşlem Tipi", options=["ALIS", "SATIS"])
            tx_sembol = st.text_input("Hisse Sembolü", placeholder="Örn: MU, NVDA, BE, AVGO").upper().strip()
        with f_col2:
            tx_tarih = st.date_input("İşlem Tarihi", value=datetime.now())
            tx_adet = st.number_input("Adet (Lot)", min_value=0.0001, value=1.0, step=1.0)
        with f_col3:
            tx_fiyat = st.number_input("Fiyat ($)", min_value=0.01, value=100.0, step=1.0)
            tx_kur = st.number_input("O Günkü Dolar Kuru (₺)", min_value=1.0, value=float(usdtry), step=0.1)

        f_sub1, f_sub2 = st.columns([1, 2])
        with f_sub1:
            tx_komisyon = st.number_input("Komisyon ($)", min_value=0.0, value=1.50, step=0.5, help="Midas standart komisyonu: $1.50")
        with f_sub2:
            tx_not = st.text_input("Not (İsteğe bağlı)", placeholder="Örn: 1. Kademe, Bilanço öncesi kâr satışı vb.")

        submitted = st.form_submit_button("💾 İşlemi Deftere Kaydet", type="primary", use_container_width=True)
        if submitted:
            if not tx_sembol:
                st.error("Lütfen hisse sembolü girin!")
            else:
                success, msg, _ = add_transaction(
                    tarih=tx_tarih.strftime("%Y-%m-%d"),
                    sembol=tx_sembol,
                    islem_tipi=tx_tipi,
                    adet=tx_adet,
                    fiyat_usd=tx_fiyat,
                    komisyon_usd=tx_komisyon,
                    usdtry_kuru=tx_kur,
                    notlar=tx_not,
                )
                if success:
                    st.success(f"✅ {tx_sembol} {tx_tipi} işlemi başarıyla kaydedildi! ({msg})")
                    st.rerun()

    # Mevcut İşlemleri Listele & Silme
    if transactions:
        st.markdown("#### 📋 Kayıtlı Son İşlemler")
        tx_display = []
        for t in reversed(transactions[-15:]):
            tx_display.append({
                "ID": t.get("id"),
                "Tarih": t.get("tarih"),
                "Tip": "🟢 ALIŞ" if t.get("islem_tipi") == "ALIS" else "🔴 SATIŞ",
                "Sembol": t.get("sembol"),
                "Adet": t.get("adet"),
                "Fiyat ($)": f"${t.get('fiyat_usd'):.2f}",
                "Kur (₺)": f"{t.get('usdtry_kuru'):.2f} ₺",
                "Not": t.get("notlar", ""),
            })
        st.dataframe(pd.DataFrame(tx_display), use_container_width=True, hide_index=True)

        with st.expander("🗑️ Yanlış Girilen Bir İşlemi Sil"):
            del_id = st.text_input("Silinecek İşlem ID:", placeholder="Örn: a1b2c3d4")
            if st.button("Seçilen İşlemi Sil", type="secondary"):
                if del_id:
                    delete_transaction(del_id.strip())
                    st.warning("İşlem silindi!")
                    st.rerun()

# ─── TAB 3: KAPANAN İŞLEMLER (FIFO) ───
with tab3:
    st.markdown("### 💰 Kapatılan Pozisyonlar ve FIFO Kâr Analizi")
    if not closed_trades:
        st.info("Henüz gerçekleşmiş bir satış işleminiz bulunmuyor.")
    else:
        closed_rows = []
        for ct in closed_trades:
            closed_rows.append({
                "Hisse": ct["sembol"],
                "Satış Tarihi": ct["satis_tarihi"],
                "Alış Tarihi": ct["alis_tarihi"],
                "Adet": f"{ct['adet']:g}",
                "Alış Fiyatı": f"${ct['alis_fiyati_usd']:.2f}",
                "Satış Fiyatı": f"${ct['satis_fiyati_usd']:.2f}",
                "Kâr ($)": f"{ct['kar_usd']:+,.2f}",
                "Kâr (₺)": f"{ct['kar_tl']:+,.0f} ₺",
                "Tutma Süresi": f"{ct['tutma_gunu']} gün",
            })
        st.dataframe(pd.DataFrame(closed_rows), use_container_width=True, hide_index=True)

# ─── TAB 4: VERGİ TASLAĞI ───
with tab4:
    st.markdown("### 📜 Yurt Dışı Hisse Gelir Vergisi Taslağı (Türkiye)")
    st.info("""
    ℹ️ **Vergi Mevzuatı Hatırlatması:** Türkiye'de yurt dışı borsalarda elde edilen hisse alım-satım kazançları 'Değer Artış Kazancı' olarak beyan edilir. 
    Kazanç, satış tarihindeki TCMB alış kuru ile alış tarihindeki TCMB alış kuru arasındaki TL farkı üzerinden hesaplanır. 
    Eğer iki tarih arasındaki Yİ-ÜFE artışı %10'u aşmışsa maliyet endekslemesi yapılabilir.
    """)

    if not closed_trades:
        st.warning("Vergi hesabı için tamamlanmış (satılmış) bir işlem kaydı bulunmuyor.")
    else:
        yil_gruplari = {}
        for ct in closed_trades:
            yil = ct["satis_tarihi"][:4]
            yil_gruplari.setdefault(yil, []).append(ct)

        for yil, trades in yil_gruplari.items():
            st.markdown(f"#### 📅 {yil} Takvim Yılı Kazanç Özeti")
            y_kar_tl = sum(t["kar_tl"] for t in trades)
            y_kar_usd = sum(t["kar_usd"] for t in trades)

            vc1, vc2 = st.columns(2)
            with vc1:
                st.metric(f"{yil} Toplam TL Kazanç Matrahı", f"{y_kar_tl:+,.0f} ₺")
            with vc2:
                st.metric(f"{yil} Toplam Dolar Kazanç", f"${y_kar_usd:+,.2f}")

            st.caption("⚠️ *Not: Bu hesaplama genel bilgilendirme amaçlı bir ön taslaktır. Kesin vergi beyanınız için mali müşavirinize danışınız.*")

# ─── TAB 5: BULUT SENKRONİZASYONU (GOOGLE SHEETS) ───
with tab5:
    st.markdown("### ☁️ Kalıcı Google Sheets Bağlantısı")
    st.markdown("""
    Streamlit Cloud'un sunucusu sıfırlansa dahi portföyünüzün **asla silinmemesi** için Google Sheets entegrasyonu mevcuttur.
    
    #### 🚀 3 Adımda Bağlantı:
    1. Google Drive'ınızda yeni bir Google Sheets (E-Tablo) oluşturun ve adını `StockPredictionPro_Portfoy` yapın.
    2. İlk çalışma sayfasının (sekmesinin) adını **`Islemler`** yapın.
    3. Streamlit Cloud panelinizde:
       * **App Settings → Secrets** kısmına Google Sheets bağlantı bilgilerinizi yapıştırın.
    """)

    st.code("""
# Streamlit Cloud Secrets Örneği:
[connections.gsheets]
spreadsheet = "https://docs.google.com/spreadsheets/d/TABLO_ID_BURAYA/edit"
type = "service_account"
# (Google Cloud Service Account JSON bilgileri)
    """, language="toml")

    st.success("💡 **İyi Haber:** Google Sheets bağlamasanız bile sistem tüm işlemlerinizi yerel veritabanında güvenle saklamaya devam eder.")
