"""
Sayfa 9: Alım & Satış Avcısı (Dip Hunter + Exit & Profit Shield + Telegram Alarm Merkezi)
Hisselerin hem "Alsam mı, daha da düşer mi?" hem de "Ne zaman satayım, bilanço kumarına gireyim mi?"
kararsızlığını çözen, karmaşık teknik terimler yerine tamamen anlaşılır sohbet diliyle
yol gösteren akıllı karar modülü.
"""
import json as _json
import os
import sys

import pandas as _pd
import streamlit as st
import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.dip_hunter import (
    analyze_stock_dip,
    analyze_stock_exit,
    format_plain_exit_telegram_message,
    format_plain_telegram_message,
    load_dip_config,
    save_dip_config,
    send_telegram_message,
    sync_and_notify_from_ui,
)
from web.components.investment_committee import analyze_earnings_catalyst, get_market_regime_summary
from web.components.mobile import COMPANY_NAMES, get_vix_status
from web.components.portfolio_tracker import calculate_fifo_portfolio
from web.components.ui import (
    esc_dollars,
    ACCENT,
    AMBER,
    BLUE,
    BORDER,
    CARD_2,
    GREEN,
    MUTED,
    RED,
    TEXT,
    decision_card,
    esc,
    page_header,
    price_chart_with_levels,
    prob_bar_html,
    regime_strip,
    stat_grid,
)

page_header(
    "🎯 Alım & Satış Avcısı",
    '"Şimdi alsam mı?" ve "Ne zaman satıp kârı cebime koymalıyım?" sorularını teknik terime boğmadan çözen takip ve Telegram bildirim merkezi.',
)

regime_info = get_market_regime_summary()
regime_strip(regime_info)

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
                    "kâr alma / bilanço uyarısı geldiğinde sana buradan sade bir dille haber vereceğim.",
                )
                if ok:
                    st.success("Test mesajı telefonuna gönderildi!")
                else:
                    st.error(msg)


from concurrent.futures import ThreadPoolExecutor

@st.cache_data(ttl=300, show_spinner=False)
def _cached_dip_analyses(sym_tuple: tuple, vix: float) -> list[dict]:
    v_rnd = round(float(vix or 18.0), 1)
    with ThreadPoolExecutor(max_workers=min(6, len(sym_tuple) or 1)) as ex:
        futs = [ex.submit(analyze_stock_dip, s, vix_value=v_rnd) for s in sym_tuple]
        out = []
        for f in futs:
            try:
                res = f.result(timeout=10)
                if res:
                    out.append(res)
            except Exception:
                pass
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _cached_exit_analyses(sym_tuple: tuple, pos_json: str) -> list[dict]:
    pos_map = _json.loads(pos_json) if pos_json else {}
    with ThreadPoolExecutor(max_workers=min(6, len(sym_tuple) or 1)) as ex:
        futs = [ex.submit(analyze_stock_exit, s, user_pos=pos_map.get(s)) for s in sym_tuple]
        out = []
        for f in futs:
            try:
                res = f.result(timeout=10)
                if res:
                    out.append(res)
            except Exception:
                pass
    return out


@st.cache_data(ttl=300, show_spinner=False)
def _cached_price_df(sym: str) -> _pd.DataFrame:
    try:
        return yf.Ticker(sym).history(period="9mo")
    except Exception:
        return _pd.DataFrame()


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

    st.markdown(
        stat_grid([
            ("🟢 Şimdi Alım Fırsatı", f"{cnt_buy} Hisse", "Dipten dönüş başladı", GREEN),
            ("🟡 Ucuzluk Bölgesinde", f"{cnt_watch} Hisse", "Henüz alma, dönüşü bekle", AMBER),
            ("🔵 Beklemede", f"{cnt_wait} Hisse", "Fiyat henüz yüksek", BLUE),
            ("🔴 Tehlike / Kırılım", f"{cnt_danger} Hisse", "Düşen bıçak, uzak dur", RED),
        ]),
        unsafe_allow_html=True,
    )
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

    with st.expander("🤖 Yapay Zeka (Üçlü Bariyer) Motoru Geçmiş Test Karnesi & Nasıl Çalışır?", expanded=False):
        st.markdown(
            """
            **QuantBot** içerisindeki **Üçlü Bariyer (Hedef / Stop / Zaman)** ve **Kalibre Olasılık** yapay zeka motorumuz, canlı sisteme bağlanmadan önce **20 ABD hissesinin 5 yıllık gerçek geçmiş verisinde (hiç görmediği 2.837 dip senaryosu üzerinde)** test edildi ve geliştirildi:
            - **Yapay Zeka Olmadan (Standart Ucuzluk Bölgesi):** Kazanma oranı **%54.9**, işlem başı 15 günlük ortalama getiri **+%1.03**.
            - **Yapay Zeka Onaylı İşlemler (15 Volatilite-Nötr Gösterge + Hibrit Lojistik/RF Modeli):** Kazanma oranı **%59.8**, işlem başı 15 günlük ortalama getiri **+%2.14** (**2 kattan fazla getiri artışı!**).
            - **Neye Bakıyor?** Hissenin sadece düşmüş olmasına değil; S&P 500 ve Çip ETF'ine (SMH) göre direncine, 6 aylık ana gücüne, dipteki hacimli alt fitil tepkisine ve o hissenin kendi geçmişindeki en benzer 25 günde (Tarihsel İkizler) ne yaptığına bakarak **"15 günde önce kâr hedefine mi ulaşır, yoksa stop sınırına mı çarpar?"** sorusuna yüzdelik ihtimal verir.
            """
        )

    st.write("")
    priority_order = {"ALIM_FIRSATI": 0, "PUSUDA_IZLE": 1, "TEHLIKE": 2, "BEKLEMEDE": 3}
    sorted_results = sorted(results, key=lambda x: priority_order.get(x["state_code"], 9))

    for res in sorted_results:
        sym = res["symbol"]
        comp = COMPANY_NAMES.get(sym, "")
        price = res["current_price"]
        chg = res["daily_change_pct"]
        border_col = res["state_color"]
        ai_pred = res.get("ai_pred") or {}

        extra_badges = []
        footer_html = ""
        if ai_pred.get("available"):
            wp = int(ai_pred.get("win_prob_pct", 50))
            sp = int(ai_pred.get("stop_prob_pct", 50))
            ac = ai_pred.get("ai_color", BLUE)
            extra_badges.append((ai_pred.get("ai_badge", "AI"), ac))
            footer_html = (
                "<div style='margin-top:12px;'>"
                + prob_bar_html(
                    wp,
                    f"🎯 15 Günde Önce Kâr Hedefine (${res['target1']:.2f}) Ulaşma İhtimali: %{wp}",
                    f"⛔ Önce Kaçış Sınırına (${res['stop_level']:.2f}) Değme Riski: %{sp}",
                )
                + f"<div class='spp-muted' style='margin-top:4px;'>"
                f"📊 <b>Geçmiş Benzer Günler:</b> {esc(sym)} son 2 yılda benzer duruma <b>{ai_pred['analog_count']} kez</b> geldi; "
                f"bunların <b>%{ai_pred['analog_win_rate_pct']:.0f}'inde</b> yukarı tepki verdi (15G ort. getiri: <b>{ai_pred['analog_avg_ret_pct']:+.1f}%</b>)."
                f"</div></div>"
            )

        card_stats = [
            ("🟢 1. Parça Alım Yeri", f"${res['zone1_low']:.2f} – ${res['zone1_high']:.2f}", "İlk ucuzluk bölgesi", GREEN),
            ("🛡️ 2. Parça (Çok Düşerse)", f"${res['zone2_low']:.2f} – ${res['zone2_high']:.2f}", "Yedek kurşun yeri", ACCENT),
            ("⛔ Kaçış / İptal Sınırı", f"${res['stop_level']:.2f} altı", "Kırılırsa alım yapma", RED),
            ("🎯 Kâr Alma Hedefi", f"${res['target1']:.2f} – ${res['target2']:.2f}", f"+%{res['upside_pct']} kazanç potansiyeli", BLUE),
        ]

        headline_txt = f"🗣️ {res['headline']} (Son zirvesi ${res['recent_peak']:.2f} seviyesinden %{abs(res['drop_from_peak_pct']):.1f} uzakta)"

        decision_card(
            symbol=sym,
            price=price,
            chg_pct=chg,
            status_text=res["state_badge"],
            status_color=border_col,
            headline=headline_txt,
            stats=card_stats,
            extra_badges=extra_badges,
            name=comp,
            footer_html=footer_html,
        )

        total_chk = res.get("total_checks", len(res["checklist"]))
        with st.expander(f"📋 {sym} Uzman Tavsiyesi, Güven Kontrol Listesi ({res['passed_count']}/{total_chk} Şart) & Seviye Grafiği"):
            st.info(esc_dollars(res["action_advice"]))

            c_chk, c_chart = st.columns([1.15, 1])
            with c_chk:
                st.markdown("##### ✅ 5 Adımlı Güven Kontrol Listesi")
                for item in res["checklist"]:
                    icon = "✅" if item["ok"] else "⏳"
                    st.markdown(f"{icon} **{item['kriter']}** — *{esc_dollars(item['detay'])}*")

            with c_chart:
                st.markdown("##### 📈 Fiyat & Alım Bölgeleri Grafiği")
                df_p = _cached_price_df(sym)
                fig_m = price_chart_with_levels(
                    df_p,
                    zone1=(res["zone1_low"], res["zone1_high"]),
                    zone2=(res["zone2_low"], res["zone2_high"]),
                    stop=res["stop_level"],
                    target1=res["target1"],
                    target2=res["target2"],
                    height=270,
                )
                if fig_m:
                    st.plotly_chart(fig_m, use_container_width=True, key=f"buy_chart_{sym}")

            if ai_pred.get("available"):
                st.markdown("---")
                st.markdown(esc_dollars(ai_pred.get("ai_summary_tr", "")))
                ac1, ac2 = st.columns(2)
                with ac1:
                    st.markdown("**➕ İhtimali Artıran Güçlü Yanlar:**")
                    for p_txt in ai_pred.get("positives", []):
                        st.markdown(f"- 🟢 {esc_dollars(p_txt)}")
                with ac2:
                    st.markdown("**➖ İhtimali Düşüren Riskler:**")
                    for n_txt in ai_pred.get("negatives", []):
                        st.markdown(f"- 🟠 {esc_dollars(n_txt)}")

            btn_c1, btn_c2 = st.columns(2)
            with btn_c1:
                if st.button(f"🔍 {sym} Tam Analiz Sayfasına Git", key=f"go_an_buy_{sym}", use_container_width=True):
                    st.session_state["selected_symbol"] = sym
                    st.session_state["auto_analyze"] = True
                    st.switch_page("pages/2_tek_hisse_analiz.py")
            with btn_c2:
                if st.button(f"📲 Sadece {sym} Alım Raporunu Telegram'a Gönder", key=f"tg_single_buy_{sym}", use_container_width=True):
                    if not tg_ready:
                        st.warning("Telegram ayarları eksik.")
                    else:
                        msg = format_plain_telegram_message(res)
                        ok, err = send_telegram_message(cfg["telegram_bot_token"], cfg["telegram_chat_id"], msg)
                        if ok:
                            st.success(f"{sym} alım raporu telefonuna gönderildi!")
                        else:
                            st.error(err)


# =========================================================================
# SEKME 2: SATIŞ & KÂR KORUMA AVCISI (NE ZAMAN SATAYIM?)
# =========================================================================
with tab_sell:
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

    st.markdown(
        stat_grid([
            ("💰 Şimdi Kâr Al", f"{cnt_take_profit} Hisse", "Fiyat şişti, kârı cebe koy", GREEN),
            ("📅 Bilanço Uyarısı", f"{cnt_earnings} Hisse", "Karne gününe <5 gün kaldı", AMBER),
            ("🛡️ Kârı Koru / Tut", f"{cnt_hold_shield} Hisse", "Yükseliş sürüyor, erken satma", BLUE),
            ("⏳ Dipte Satılmaz", f"{cnt_bottom_wait} Hisse", "Ucuz bölgede, tepkiyi bekle", MUTED),
        ]),
        unsafe_allow_html=True,
    )
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

    st.write("")
    exit_priority = {"BILANCO_UYARISI": 0, "SIMDI_KAR_AL": 1, "KARI_KORU_TUT": 2, "DIPTE_SATILMAZ": 3}
    sorted_exit_results = sorted(
        exit_results,
        key=lambda x: (0 if x["has_position"] else 1, exit_priority.get(x["exit_code"], 9)),
    )

    for res in sorted_exit_results:
        sym = res["symbol"]
        comp = COMPANY_NAMES.get(sym, "")
        price = res["current_price"]
        chg = res["daily_change_pct"]
        border_col = res["exit_color"]

        extra_badges = []
        fifo_footer = ""
        if res["has_position"]:
            extra_badges.append((f"💼 Midas Portföyünde ({res['total_qty']:g} Lot)", GREEN))
            pnl_col = GREEN if res["pnl_usd"] >= 0 else RED
            pnl_sign = "+" if res["pnl_usd"] >= 0 else ""
            fifo_col = GREEN if res["first_fifo_pnl_pct"] >= 0 else RED
            fifo_footer = (
                f"<div style='background:{CARD_2}; border:1px dashed {BORDER}; border-radius:10px; "
                f"padding:10px 12px; margin-top:10px; display:flex; justify-content:space-between; "
                f"flex-wrap:wrap; gap:10px; font-size:0.82rem; color:{TEXT};'>"
                f"<div>📦 <b>Pozisyon:</b> {res['total_qty']:g} Lot (Ort: <b>&#36;{res['avg_cost']:.2f}</b>)</div>"
                f"<div>💵 <b>Net K/Z:</b> <span style='color:{pnl_col}; font-weight:700;'>{pnl_sign}&#36;{res['pnl_usd']:,.2f} ({pnl_sign}{res['pnl_pct']:.2f}%)</span></div>"
                f"<div>🥇 <b>İlk FIFO Lot:</b> &#36;{res['first_fifo_lot_price']:.2f} (<span style='color:{fifo_col}; font-weight:700;'>{res['first_fifo_pnl_pct']:+.1f}%</span>)</div>"
                f"<div>✅ <b>Kârda Lot:</b> {res['profitable_lots_count']}/{res['total_lots_count']}</div>"
                f"</div>"
            )

        if res.get("earnings_date_str"):
            earn_color = AMBER if (res["days_to_earnings"] is not None and res["days_to_earnings"] <= 7) else ACCENT
            earn_sub = f"{res['days_to_earnings']} gün kaldı"
            earn_val = res["earnings_date_str"]
        else:
            earn_color = MUTED
            earn_val = "Yakında Yok"
            earn_sub = "Bilanço sürprizi görünmüyor"

        sell_stats = [
            ("💰 1. Kâr Alma Yeri", f"${res['take_profit_1']:.2f}", "İlk parça satış / direnç", GREEN),
            ("🔥 2. Aşırı Şişme Tepesi", f"${res['take_profit_2']:.2f}", "Ana zirve / coşku tavanı", AMBER),
            ("🛡️ Kâr Koruma Çizgisi", f"${res['profit_shield_line']:.2f}", "Altına inerse kârı koru", BLUE),
            ("📅 Bilanço (Karne) Günü", earn_val, earn_sub, earn_color),
        ]

        decision_card(
            symbol=sym,
            price=price,
            chg_pct=chg,
            status_text=res["exit_badge"],
            status_color=border_col,
            headline=f"🗣️ {res['headline']}",
            stats=sell_stats,
            extra_badges=extra_badges,
            name=comp,
            footer_html=fifo_footer,
        )

        with st.expander(f"📋 {sym} Satış Tavsiyesi, Kontrol Listesi, Geçmiş Bilanço Karnesi & Telegram"):
            st.info(esc_dollars(res["action_advice"]))

            for item in res["exit_checklist"]:
                icon = "⚠️" if item["ok"] else "✅"
                st.markdown(f"{icon} **{item['kriter']}** — *{esc_dollars(item['detay'])}*")

            e_cat = analyze_earnings_catalyst(sym)
            if e_cat and e_cat.get("history_rows"):
                st.markdown("---")
                st.markdown(f"#### 📅 {sym} Geçmiş Bilanço Karnesi (Son Bilançolarda Ertesi Gün Ne Yaptı?)")
                st.caption(e_cat["summary_text"])
                clean_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in e_cat["history_rows"][:6]]
                st.dataframe(_pd.DataFrame(clean_rows), use_container_width=True, hide_index=True)

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
