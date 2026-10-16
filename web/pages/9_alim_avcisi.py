"""
Sayfa 9: Alım Noktası & Dönüş Avcısı (Dip Hunter & Telegram Alarm Merkezi)
Hisselerin "Alsam mı, daha da düşer mi?" kararsızlığını çözen,
karmaşık teknik terimler yerine tamamen anlaşılır sohbet diliyle
alım bölgelerini, dönüş onaylarını ve iptal sınırlarını gösteren modül.
"""
import os
import sys
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.dip_hunter import (
    load_dip_config,
    save_dip_config,
    analyze_stock_dip,
    format_plain_telegram_message,
    send_telegram_message,
    scan_and_notify_all,
)
from web.components.mobile import get_vix_status

st.markdown("""
<div style="margin-bottom: 1rem;">
    <h2 style="margin: 0; font-size: 1.55rem; font-weight: 800; color: #e6f1ff;">
        🎯 Alım Noktası & Dönüş Avcısı
    </h2>
    <p style="margin: 4px 0 0 0; color: #8892b0; font-size: 0.9rem;">
        "Şimdi alsam mı, yoksa daha da düşer mi?" sorusunu senin yerine çözen akıllı takip ve Telegram bildirim sistemi.
    </p>
</div>
""", unsafe_allow_html=True)

cfg = load_dip_config()
symbols = cfg.get("symbols", ["MU", "COHR", "MRVL", "RKLB", "VST", "AVGO"])
vix_val, vix_label, _ = get_vix_status()

# ─── ÜST KONTROL PANELİ: HİSSE EKLE/ÇIKAR & TELEGRAM AYARI ───
c_top1, c_top2 = st.columns([2, 1])

with c_top1:
    with st.expander("➕ Takip Edilen Hisseleri Düzenle", expanded=False):
        new_sym = st.text_input(
            "Yeni Hisse Kodu Ekle (Örn: NVDA, AMD, TSLA, PLTR)",
            placeholder="Sembol yazın...",
        ).strip().upper()
        if st.button("📌 Listeye Ekle", type="primary"):
            if new_sym and new_sym not in symbols:
                symbols.append(new_sym)
                cfg["symbols"] = symbols
                save_dip_config(cfg)
                st.success(f"{new_sym} takip listesine eklendi!")
                st.rerun()

        if symbols:
            remove_syms = st.multiselect("Listeden Çıkarmak İstediklerinizi Seçin:", symbols)
            if st.button("🗑️ Seçilenleri Çıkar") and remove_syms:
                cfg["symbols"] = [s for s in symbols if s not in remove_syms]
                save_dip_config(cfg)
                st.rerun()

with c_top2:
    tg_ready = bool(cfg.get("telegram_bot_token") and cfg.get("telegram_chat_id"))
    tg_status_text = "🟢 Telegram Bağlı ve Hazır" if tg_ready else "⚪ Telegram Ayarı Bekleniyor"
    with st.expander(f"📲 {tg_status_text}", expanded=False):
        bot_token_in = st.text_input(
            "Telegram Bot Token",
            value=cfg.get("telegram_bot_token", ""),
            type="password",
        )
        chat_id_in = st.text_input(
            "Telegram Chat ID",
            value=cfg.get("telegram_chat_id", ""),
        )
        notify_toggle = st.checkbox(
            "Otomatik Telegram Bildirimleri Aktif",
            value=cfg.get("notifications_enabled", True),
        )
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            if st.button("💾 Kaydet", use_container_width=True):
                cfg["telegram_bot_token"] = bot_token_in.strip()
                cfg["telegram_chat_id"] = chat_id_in.strip()
                cfg["notifications_enabled"] = notify_toggle
                save_dip_config(cfg)
                st.success("Ayarlar kaydedildi!")
                st.rerun()
        with col_s2:
            if st.button("🔔 Test Mesajı At", use_container_width=True):
                ok, msg = send_telegram_message(
                    bot_token_in,
                    chat_id_in,
                    "🎯 *StockPredictionPro — Alım Avcısı Aktif!*\n\n"
                    "Takip ettiğin hisseler ucuzluk bölgesine indiğinde ve dipten dönüş başladığında "
                    "sana buradan sade ve anlaşılır bir dille haber vereceğim."
                )
                if ok:
                    st.success("Test mesajı telefonuna gönderildi!")
                else:
                    st.error(msg)


@st.cache_data(ttl=120, show_spinner=False)
def _cached_dip_analyses(sym_tuple: tuple, vix: float) -> list[dict]:
    out = []
    for s in sym_tuple:
        r = analyze_stock_dip(s, vix_value=vix)
        if r:
            out.append(r)
    return out


with st.spinner("Hisselerin gün içi (15 dk) ve günlük alım bölgeleri hesaplanıyor..."):
    results = _cached_dip_analyses(tuple(symbols), float(vix_val))

# ─── ÖZET DURUM KARTLARI ───
cnt_buy = sum(1 for r in results if r["state_code"] == "ALIM_FIRSATI")
cnt_watch = sum(1 for r in results if r["state_code"] == "PUSUDA_IZLE")
cnt_wait = sum(1 for r in results if r["state_code"] == "BEKLEMEDE")
cnt_danger = sum(1 for r in results if r["state_code"] == "TEHLIKE")

k1, k2, k3, k4 = st.columns(4)
with k1:
    st.markdown(f"""
    <div class="metric-card" style="border-color: #00c853;">
        <h3>🟢 ŞİMDİ ALIM FIRSATI</h3>
        <h1 style="color: #00c853;">{cnt_buy} Hisse</h1>
        <span style="color: #8892b0; font-size: 0.75rem;">Dipten dönüş başladı</span>
    </div>
    """, unsafe_allow_html=True)
with k2:
    st.markdown(f"""
    <div class="metric-card" style="border-color: #ffa726;">
        <h3>🟡 UCUZLUK BÖLGESİNDE</h3>
        <h1 style="color: #ffa726;">{cnt_watch} Hisse</h1>
        <span style="color: #8892b0; font-size: 0.75rem;">Henüz alma, dönüşü bekle</span>
    </div>
    """, unsafe_allow_html=True)
with k3:
    st.markdown(f"""
    <div class="metric-card" style="border-color: #29b6f6;">
        <h3>🔵 BEKLEMEDE</h3>
        <h1 style="color: #29b6f6;">{cnt_wait} Hisse</h1>
        <span style="color: #8892b0; font-size: 0.75rem;">Fiyat henüz yüksek</span>
    </div>
    """, unsafe_allow_html=True)
with k4:
    st.markdown(f"""
    <div class="metric-card" style="border-color: #ef5350;">
        <h3>🔴 TEHLİKE / KIRILIM</h3>
        <h1 style="color: #ef5350;">{cnt_danger} Hisse</h1>
        <span style="color: #8892b0; font-size: 0.75rem;">Düşen bıçak, uzak dur</span>
    </div>
    """, unsafe_allow_html=True)

st.write("")

# ─── HIZLI TELEGRAM ÖZET BUTONU ───
b_col1, b_col2 = st.columns([1, 1])
with b_col1:
    if st.button("🔄 Fiyatları Şimdi Yenile", use_container_width=True):
        _cached_dip_analyses.clear()
        st.rerun()
with b_col2:
    if st.button("📲 Tüm Hisselerin Durumunu Şimdi Telegram'a Gönder", type="primary", use_container_width=True):
        if not tg_ready:
            st.warning("Önce sağ üstten Telegram Bot Token ve Chat ID ayarlarını kaydedin.")
        else:
            sent = 0
            for r in results:
                msg = format_plain_telegram_message(r)
                ok, _ = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                if ok:
                    sent += 1
            st.success(f"✅ {sent} hissenin anlaşılır analiz raporu telefonuna (Telegram) gönderildi!")

st.divider()

# ─── HİSSE KARTLARI (SADE TÜRKÇE REHBER) ───
# Önce Alım Fırsatı ve Pusuda olanları en üste sırala
priority_order = {"ALIM_FIRSATI": 0, "PUSUDA_IZLE": 1, "TEHLIKE": 2, "BEKLEMEDE": 3}
sorted_results = sorted(results, key=lambda x: priority_order.get(x["state_code"], 9))

for res in sorted_results:
    sym = res["symbol"]
    price = res["current_price"]
    chg = res["daily_change_pct"]
    chg_color = "#00c853" if chg >= 0 else "#ef5350"
    chg_sign = "+" if chg >= 0 else ""
    border_col = res["state_color"]

    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #0d1b2a 0%, #16263b 100%);
                border-left: 6px solid {border_col};
                border-top: 1px solid #233554;
                border-right: 1px solid #233554;
                border-bottom: 1px solid #233554;
                border-radius: 12px;
                padding: 1.2rem;
                margin-bottom: 1rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
            <div>
                <span style="font-size: 1.4rem; font-weight: 800; color: #ffffff;">{sym}</span>
                <span style="font-size: 1.25rem; font-weight: 700; color: #64ffda; margin-left: 10px;">${price:.2f}</span>
                <span style="font-size: 0.9rem; font-weight: 600; color: {chg_color}; margin-left: 6px;">({chg_sign}%{chg:.2f})</span>
            </div>
            <div style="background: {border_col}22; border: 1px solid {border_col}; color: {border_col};
                        padding: 5px 14px; border-radius: 20px; font-weight: 700; font-size: 0.82rem;">
                {res['state_badge']}
            </div>
        </div>
        <p style="color: #ccd6f6; font-size: 0.95rem; margin: 0.7rem 0 0.4rem 0; font-weight: 600;">
            🗣️ {res['headline']} <span style="color: #8892b0; font-weight: 400; font-size: 0.82rem;">(Son zirvesi ${res['recent_peak']:.2f} seviyesinden %{abs(res['drop_from_peak_pct']):.1f} uzakta)</span>
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Sade Türkçe Tavsiye Kutusu
    st.info(res["action_advice"])

    # 4'lü Seviye Haritası
    s1, s2, s3, s4 = st.columns(4)
    with s1:
        st.markdown(f"""
        <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #00c85355; text-align: center;">
            <div style="color: #8892b0; font-size: 0.75rem;">🟢 1. Parça Alım Yeri</div>
            <div style="color: #00c853; font-size: 1.05rem; font-weight: 700; margin-top: 4px;">
                ${res['zone1_low']:.2f} – ${res['zone1_high']:.2f}
            </div>
            <div style="color: #8892b0; font-size: 0.7rem;">İlk ucuzluk bölgesi</div>
        </div>
        """, unsafe_allow_html=True)
    with s2:
        st.markdown(f"""
        <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #64ffda55; text-align: center;">
            <div style="color: #8892b0; font-size: 0.75rem;">🛡️ 2. Parça (Çok Düşerse)</div>
            <div style="color: #64ffda; font-size: 1.05rem; font-weight: 700; margin-top: 4px;">
                ${res['zone2_low']:.2f} – ${res['zone2_high']:.2f}
            </div>
            <div style="color: #8892b0; font-size: 0.7rem;">Yedek kurşun yeri</div>
        </div>
        """, unsafe_allow_html=True)
    with s3:
        st.markdown(f"""
        <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #ef535055; text-align: center;">
            <div style="color: #8892b0; font-size: 0.75rem;">⛔ Kaçış / İptal Sınırı</div>
            <div style="color: #ef5350; font-size: 1.05rem; font-weight: 700; margin-top: 4px;">
                ${res['stop_level']:.2f} altı
            </div>
            <div style="color: #8892b0; font-size: 0.7rem;">Kırılırsa alım yapma</div>
        </div>
        """, unsafe_allow_html=True)
    with s4:
        st.markdown(f"""
        <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #29b6f655; text-align: center;">
            <div style="color: #8892b0; font-size: 0.75rem;">🎯 Kâr Alma Hedefi</div>
            <div style="color: #29b6f6; font-size: 1.05rem; font-weight: 700; margin-top: 4px;">
                ${res['target1']:.2f} – ${res['target2']:.2f}
            </div>
            <div style="color: #8892b0; font-size: 0.7rem;">+%{res['upside_pct']} kazanç potansiyeli</div>
        </div>
        """, unsafe_allow_html=True)

    # Kontrol Listesi ve Tekil Telegram Gönderimi
    with st.expander(f"📋 {sym} Güven Kontrol Listesi ({res['passed_count']}/4 Şart Hazır) & Telegram'a Gönder"):
        for item in res["checklist"]:
            icon = "✅" if item["ok"] else "⏳"
            st.markdown(f"{icon} **{item['kriter']}** — *{item['detay']}*")

        if st.button(f"📲 Sadece {sym} Raporunu Telegram'a Gönder", key=f"tg_single_{sym}"):
            if not tg_ready:
                st.warning("Telegram ayarları eksik.")
            else:
                msg = format_plain_telegram_message(res)
                ok, err = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                if ok:
                    st.success(f"{sym} raporu telefonuna gönderildi!")
                else:
                    st.error(err)

    st.markdown("<hr style='border-color: #1d3557; margin: 1.2rem 0;'>", unsafe_allow_html=True)
