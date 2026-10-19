"""
Sayfa 9: Alım & Satış Avcısı (Dip Hunter + Exit & Profit Shield + Telegram Alarm Merkezi)
Hisselerin hem "Alsam mı, daha da düşer mi?" hem de "Ne zaman satayım, bilanço kumarına gireyim mi?"
kararsızlığını çözen, karmaşık teknik terimler yerine tamamen anlaşılır sohbet diliyle
yol gösteren akıllı karar modülü.
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
    analyze_stock_exit,
    format_plain_telegram_message,
    format_plain_exit_telegram_message,
    send_telegram_message,
    sync_and_notify_from_ui,
)
from web.components.mobile import get_vix_status
from web.components.portfolio_tracker import calculate_fifo_portfolio

st.markdown("""
<div style="margin-bottom: 1rem;">
    <h2 style="margin: 0; font-size: 1.55rem; font-weight: 800; color: #e6f1ff;">
        🎯 Alım & Satış Avcısı (Akıllı Zamanlama Asistanı)
    </h2>
    <p style="margin: 4px 0 0 0; color: #8892b0; font-size: 0.9rem;">
        "Şimdi alsam mı?" ve "Ne zaman satıp kârı cebime koymalıyım?" sorularını teknik terime boğmadan çözen takip ve Telegram bildirim merkezi.
    </p>
</div>
""", unsafe_allow_html=True)

cfg = load_dip_config()
symbols = cfg.get("symbols", ["MU", "COHR", "MRVL", "RKLB", "VST", "AVGO"])
vix_val, vix_label, _ = get_vix_status()

try:
    open_positions, _ = calculate_fifo_portfolio()
except Exception:
    open_positions = {}

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
                    "🎯 *StockPredictionPro — Alım & Satış Avcısı Aktif!*\n\n"
                    "Takip ettiğin hisseler ucuzluk bölgesine indiğinde veya elindeki hisselerde "
                    "kâr alma / bilanço uyarısı geldiğinde sana buradan sade bir dille haber vereceğim."
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


@st.cache_data(ttl=120, show_spinner=False)
def _cached_exit_analyses(sym_tuple: tuple, pos_json: str) -> list[dict]:
    import json as _json
    pos_map = _json.loads(pos_json) if pos_json else {}
    out = []
    for s in sym_tuple:
        r = analyze_stock_exit(s, user_pos=pos_map.get(s))
        if r:
            out.append(r)
    return out


# ─── İKİ ANA SEKME: ALIM AVCISI & SATIŞ/KÂR KORUMA AVCISI ───
tab_buy, tab_sell = st.tabs([
    "🟢 Alım Avcısı (Ne Zaman Alayım?)",
    "💰 Satış & Kâr Koruma Avcısı (Ne Zaman Satayım?)",
])

# =========================================================================
# SEKME 1: ALIM AVCISI (NE ZAMAN ALAYIM?)
# =========================================================================
with tab_buy:
    with st.spinner("Hisselerin gün içi (15 dk) ve günlük alım bölgeleri hesaplanıyor..."):
        results = _cached_dip_analyses(tuple(symbols), float(vix_val))

    auto_sent_buy = sync_and_notify_from_ui(dip_results=results)
    if auto_sent_buy:
        st.success(f"📲 Yeni fırsat algılandı ve Telegram'a otomatik bildirim gönderildi: {', '.join(auto_sent_buy)}")

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

    b_col1, b_col2 = st.columns([1, 1])
    with b_col1:
        if st.button("🔄 Alım Analizlerini Şimdi Yenile", use_container_width=True, key="refresh_buy"):
            _cached_dip_analyses.clear()
            st.rerun()
    with b_col2:
        if st.button("📲 Tüm Alım Raporlarını Telegram'a Gönder", type="primary", use_container_width=True, key="tg_all_buy"):
            if not tg_ready:
                st.warning("Önce sağ üstten Telegram Bot Token ve Chat ID ayarlarını kaydedin.")
            else:
                sent = 0
                for r in results:
                    msg = format_plain_telegram_message(r)
                    ok, _ = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                    if ok:
                        sent += 1
                st.success(f"✅ {sent} hissenin anlaşılır alım raporu telefonuna (Telegram) gönderildi!")

    st.divider()

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

        st.info(res["action_advice"])

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

        with st.expander(f"📋 {sym} Güven Kontrol Listesi ({res['passed_count']}/4 Şart Hazır) & Telegram'a Gönder"):
            for item in res["checklist"]:
                icon = "✅" if item["ok"] else "⏳"
                st.markdown(f"{icon} **{item['kriter']}** — *{item['detay']}*")

            if st.button(f"📲 Sadece {sym} Alım Raporunu Telegram'a Gönder", key=f"tg_single_buy_{sym}"):
                if not tg_ready:
                    st.warning("Telegram ayarları eksik.")
                else:
                    msg = format_plain_telegram_message(res)
                    ok, err = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                    if ok:
                        st.success(f"{sym} alım raporu telefonuna gönderildi!")
                    else:
                        st.error(err)

        st.markdown("<hr style='border-color: #1d3557; margin: 1.2rem 0;'>", unsafe_allow_html=True)


# =========================================================================
# SEKME 2: SATIŞ & KÂR KORUMA AVCISI (NE ZAMAN SATAYIM?)
# =========================================================================
with tab_sell:
    import json as _json

    # Önce Midas portföyündeki açık hisseleri, sonra takip listesindekileri birleştir
    owned_syms = list(open_positions.keys())
    all_exit_syms = list(dict.fromkeys(owned_syms + list(symbols)))

    with st.spinner("Midas lotların, bilanço tarihlerin ve kâr alma/koruma noktaların hesaplanıyor..."):
        exit_results = _cached_exit_analyses(tuple(all_exit_syms), _json.dumps(open_positions))

    auto_sent_sell = sync_and_notify_from_ui(exit_results=exit_results)
    if auto_sent_sell:
        st.success(f"📲 Yeni satış/kâr koruma uyarısı algılandı ve Telegram'a otomatik gönderildi: {', '.join(auto_sent_sell)}")

    cnt_take_profit = sum(1 for r in exit_results if r["exit_code"] == "SIMDI_KAR_AL")
    cnt_earnings = sum(1 for r in exit_results if r["exit_code"] == "BILANCO_UYARISI")
    cnt_hold_shield = sum(1 for r in exit_results if r["exit_code"] == "KARI_KORU_TUT")
    cnt_bottom_wait = sum(1 for r in exit_results if r["exit_code"] == "DIPTE_SATILMAZ")

    e1, e2, e3, e4 = st.columns(4)
    with e1:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #00e676;">
            <h3>💰 ŞİMDİ KÂR AL</h3>
            <h1 style="color: #00e676;">{cnt_take_profit} Hisse</h1>
            <span style="color: #8892b0; font-size: 0.75rem;">Fiyat şişti, kârı cebe koy</span>
        </div>
        """, unsafe_allow_html=True)
    with e2:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #ff9100;">
            <h3>📅 BİLANÇO UYARISI</h3>
            <h1 style="color: #ff9100;">{cnt_earnings} Hisse</h1>
            <span style="color: #8892b0; font-size: 0.75rem;">Karne gününe &lt;5 gün kaldı</span>
        </div>
        """, unsafe_allow_html=True)
    with e3:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #29b6f6;">
            <h3>🛡️ KÂRI KORU / TUT</h3>
            <h1 style="color: #29b6f6;">{cnt_hold_shield} Hisse</h1>
            <span style="color: #8892b0; font-size: 0.75rem;">Yükseliş sürüyor, erken satma</span>
        </div>
        """, unsafe_allow_html=True)
    with e4:
        st.markdown(f"""
        <div class="metric-card" style="border-color: #ab47bc;">
            <h3>⏳ DİPTE SATILMAZ</h3>
            <h1 style="color: #ab47bc;">{cnt_bottom_wait} Hisse</h1>
            <span style="color: #8892b0; font-size: 0.75rem;">Ucuz bölgede, tepkiyi bekle</span>
        </div>
        """, unsafe_allow_html=True)

    st.write("")

    eb_col1, eb_col2 = st.columns([1, 1])
    with eb_col1:
        if st.button("🔄 Satış & Kâr Koruma Analizlerini Yenile", use_container_width=True, key="refresh_sell"):
            _cached_exit_analyses.clear()
            st.rerun()
    with eb_col2:
        if st.button("📲 Satış & Kâr Koruma Raporlarını Telegram'a Gönder", type="primary", use_container_width=True, key="tg_all_sell"):
            if not tg_ready:
                st.warning("Önce sağ üstten Telegram Bot Token ve Chat ID ayarlarını kaydedin.")
            else:
                sent_ex = 0
                for r in exit_results:
                    msg = format_plain_exit_telegram_message(r)
                    ok, _ = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                    if ok:
                        sent_ex += 1
                st.success(f"✅ {sent_ex} hissenin Satış & Kâr Koruma raporu telefonuna (Telegram) gönderildi!")

    st.divider()

    # Önce Midas portföyünde açık olanları, sonra acil satış/bilanço uyarısı olanları en üste diz
    exit_priority = {"BILANCO_UYARISI": 0, "SIMDI_KAR_AL": 1, "KARI_KORU_TUT": 2, "DIPTE_SATILMAZ": 3}
    sorted_exit_results = sorted(
        exit_results,
        key=lambda x: (0 if x["has_position"] else 1, exit_priority.get(x["exit_code"], 9)),
    )

    for res in sorted_exit_results:
        sym = res["symbol"]
        price = res["current_price"]
        chg = res["daily_change_pct"]
        chg_color = "#00c853" if chg >= 0 else "#ef5350"
        chg_sign = "+" if chg >= 0 else ""
        border_col = res["exit_color"]
        owned_tag = (
            f"<span style='background:#00e67622; border:1px solid #00e676; color:#00e676; "
            f"padding:3px 10px; border-radius:12px; font-size:0.76rem; font-weight:700; margin-left:10px;'>"
            f"💼 Midas Portföyünde ({res['total_qty']:g} Lot)</span>"
            if res["has_position"]
            else ""
        )

        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #0d1b2a 0%, #16263b 100%);
                    border-left: 6px solid {border_col};
                    border-top: 1px solid #233554;
                    border-right: 1px solid #233554;
                    border-bottom: 1px solid #233554;
                    border-radius: 12px;
                    padding: 1.2rem;
                    margin-bottom: 0.8rem;">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                <div>
                    <span style="font-size: 1.4rem; font-weight: 800; color: #ffffff;">{sym}</span>
                    <span style="font-size: 1.25rem; font-weight: 700; color: #64ffda; margin-left: 10px;">${price:.2f}</span>
                    <span style="font-size: 0.9rem; font-weight: 600; color: {chg_color}; margin-left: 6px;">({chg_sign}%{chg:.2f})</span>
                    {owned_tag}
                </div>
                <div style="background: {border_col}22; border: 1px solid {border_col}; color: {border_col};
                            padding: 5px 14px; border-radius: 20px; font-weight: 700; font-size: 0.82rem;">
                    {res['exit_badge']}
                </div>
            </div>
            <p style="color: #ccd6f6; font-size: 0.95rem; margin: 0.7rem 0 0.3rem 0; font-weight: 600;">
                🗣️ {res['headline']}
            </p>
        </div>
        """, unsafe_allow_html=True)

        # Eğer kullanıcının Midas portföyünde bu hisse varsa FIFO Lot Röntgenini göster
        if res["has_position"]:
            pnl_col = "#00e676" if res["pnl_usd"] >= 0 else "#ef5350"
            pnl_sign = "+" if res["pnl_usd"] >= 0 else ""
            fifo_col = "#00e676" if res["first_fifo_pnl_pct"] >= 0 else "#ef5350"
            st.markdown(f"""
            <div style="background: #0a192f; border: 1px dashed #64ffda66; border-radius: 10px;
                        padding: 10px 14px; margin-bottom: 0.8rem; display: flex; justify-content: space-between;
                        flex-wrap: wrap; gap: 12px; font-size: 0.86rem;">
                <div>📦 <b>Toplam Pozisyon:</b> {res['total_qty']:g} Lot (Ort. Maliyet: <b>${res['avg_cost']:.2f}</b>)</div>
                <div>💵 <b>Net Kâr/Zarar:</b> <span style="color:{pnl_col}; font-weight:700;">{pnl_sign}${res['pnl_usd']:,.2f} ({pnl_sign}%{res['pnl_pct']:.2f})</span></div>
                <div>🥇 <b>İlk Satılacak (FIFO) Lot:</b> ${res['first_fifo_lot_price']:.2f} maliyetli (<span style="color:{fifo_col}; font-weight:700;">%{res['first_fifo_pnl_pct']:+.1f}</span>)</div>
                <div>✅ <b>Kârda Olan Lotlar:</b> {res['profitable_lots_count']} / {res['total_lots_count']} Lot</div>
            </div>
            """, unsafe_allow_html=True)

        # Sade Türkçe Satış / Kâr Koruma Tavsiyesi
        st.info(res["action_advice"])

        # 4'lü Satış ve Kâr Koruma Haritası
        x1, x2, x3, x4 = st.columns(4)
        with x1:
            st.markdown(f"""
            <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #00e67655; text-align: center;">
                <div style="color: #8892b0; font-size: 0.75rem;">💰 1. Kâr Alma Yeri</div>
                <div style="color: #00e676; font-size: 1.08rem; font-weight: 700; margin-top: 4px;">
                    ${res['take_profit_1']:.2f}
                </div>
                <div style="color: #8892b0; font-size: 0.7rem;">İlk parça satış / direnç yeri</div>
            </div>
            """, unsafe_allow_html=True)
        with x2:
            st.markdown(f"""
            <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #ff910055; text-align: center;">
                <div style="color: #8892b0; font-size: 0.75rem;">🔥 2. Aşırı Şişme Tepesi</div>
                <div style="color: #ff9100; font-size: 1.08rem; font-weight: 700; margin-top: 4px;">
                    ${res['take_profit_2']:.2f}
                </div>
                <div style="color: #8892b0; font-size: 0.7rem;">Ana zirve / coşku tavanı</div>
            </div>
            """, unsafe_allow_html=True)
        with x3:
            st.markdown(f"""
            <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid #29b6f655; text-align: center;">
                <div style="color: #8892b0; font-size: 0.75rem;">🛡️ Kâr Koruma Çizgisi</div>
                <div style="color: #29b6f6; font-size: 1.08rem; font-weight: 700; margin-top: 4px;">
                    ${res['profit_shield_line']:.2f}
                </div>
                <div style="color: #8892b0; font-size: 0.7rem;">Altına inerse kârı geri verme</div>
            </div>
            """, unsafe_allow_html=True)
        with x4:
            if res.get("earnings_date_str"):
                earn_color = "#ff9100" if (res["days_to_earnings"] is not None and res["days_to_earnings"] <= 7) else "#64ffda"
                earn_sub = f"{res['days_to_earnings']} gün kaldı"
                earn_val = res["earnings_date_str"]
            else:
                earn_color = "#8892b0"
                earn_val = "Yakında Yok"
                earn_sub = "Bilanço sürprizi görünmüyor"
            st.markdown(f"""
            <div style="background: #112240; padding: 10px; border-radius: 10px; border: 1px solid {earn_color}55; text-align: center;">
                <div style="color: #8892b0; font-size: 0.75rem;">📅 Bilanço (Karne) Günü</div>
                <div style="color: {earn_color}; font-size: 1.08rem; font-weight: 700; margin-top: 4px;">
                    {earn_val}
                </div>
                <div style="color: #8892b0; font-size: 0.7rem;">{earn_sub}</div>
            </div>
            """, unsafe_allow_html=True)

        with st.expander(f"📋 {sym} Satış & Kâr Koruma Kontrol Listesi & Telegram'a Gönder"):
            for item in res["exit_checklist"]:
                icon = "⚠️" if item["ok"] else "✅"
                st.markdown(f"{icon} **{item['kriter']}** — *{item['detay']}*")

            if st.button(f"📲 Sadece {sym} Satış/Kâr Koruma Raporunu Telegram'a Gönder", key=f"tg_single_sell_{sym}"):
                if not tg_ready:
                    st.warning("Telegram ayarları eksik.")
                else:
                    msg = format_plain_exit_telegram_message(res)
                    ok, err = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                    if ok:
                        st.success(f"{sym} satış & kâr koruma raporu telefonuna gönderildi!")
                    else:
                        st.error(err)

        st.markdown("<hr style='border-color: #1d3557; margin: 1.2rem 0;'>", unsafe_allow_html=True)
