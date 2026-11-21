"""
StockPredictionPro — Tek Birleşik Nihai Karar Motoru (Unified Verdict Engine)
Haber Şoku Radarı, Piyasa Rejimi (VIX), Dip Avcısı (8 Şartlı Kalkan),
Yapay Zeka (Üçlü Bariyer), Bilanço Takvimi ve Portföy Risk Frenini tek bir
hiyerarşik karar ağacında birleştirir; çelişkili yan yana uyarılar yerine
kullanıcıya tek, tutarlı ve anlaşılır bir nihai hüküm sunar.
"""
from __future__ import annotations

from typing import Any

from web.components.ui import AMBER, BLUE, BORDER, CARD_2, GREEN, MUTED, RED, TEXT, esc


def build_unified_verdict(
    symbol: str,
    dip_res: dict[str, Any] | None,
    regime_info: dict[str, Any] | None = None,
    exit_res: dict[str, Any] | None = None,
    earnings_info: dict[str, Any] | None = None,
    portfolio_brake: dict[str, Any] | None = None,
    factors: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Tüm alt motorların sonuçlarını alır ve tek bir nihai karar,
    tek birleşik Türkçe gerekçe paragrafı ve 6'lı alt-motor oy şeridi döndürür.
    """
    sym = (symbol or "").strip().upper()
    dip = dip_res or {}
    reg = regime_info or {}
    ex = exit_res or {}
    earn = earnings_info or {}
    brake = portfolio_brake or {}
    fac = factors or {}

    price = float(dip.get("current_price") or ex.get("current_price") or 0.0)
    state_code = str(dip.get("state_code") or "BEKLEMEDE")
    news = dip.get("news") or {}
    diag = dip.get("diagnosis") or {}
    ai_pred = dip.get("ai_pred") or {}
    gates = list(dip.get("gates") or [])
    rr_ratio = dip.get("rr_ratio")
    size_hint = str(dip.get("size_hint") or "YOK")

    vix = float(dip.get("vix_value") if dip.get("vix_value") is not None else reg.get("vix_val", 18.5))
    regime_code = str(dip.get("regime_code") or reg.get("regime_code") or "SECICI_YATAY")
    crisis = (regime_code == "KRIZ_YUKSEK_RISK") or vix >= 25.0

    days_e = dip.get("days_to_earnings")
    if days_e is None:
        days_e = earn.get("days_to_earnings")

    ai_avail = bool(ai_pred.get("available"))
    ai_wp = int(ai_pred.get("win_prob_pct", 50)) if ai_avail else None

    z1_l = float(dip.get("zone1_low") or 0.0)
    z1_h = float(dip.get("zone1_high") or 0.0)
    z2_l = float(dip.get("zone2_low") or 0.0)
    z2_h = float(dip.get("zone2_high") or 0.0)
    stop_lvl = float(dip.get("stop_level") or 0.0)
    tp1 = float(dip.get("target1") or 0.0)
    new_low_recent = bool(dip.get("new_low_recent", False))

    held = bool(brake.get("held", False))
    brake_blocked = held and not bool(brake.get("allowed", True))

    # ─── 1. ALTI ALT-MOTORUN OYLARI (TEK BAKIŞTA ÖZET ŞERİT) ───
    news_status = news.get("status", "TEMIZ")
    news_absorbed = bool(news.get("absorbed", False))
    if news_status == "SOK" and not news_absorbed:
        v_news = ("🗞️ Haber", "🔴 Şok", RED)
    elif news_status == "SOK" and news_absorbed:
        v_news = ("🗞️ Haber", "🟡 Sindirildi", AMBER)
    elif news_status == "BASKI":
        v_news = ("🗞️ Haber", "🟠 Baskı", "#ff9100")
    elif news_status == "POZITIF":
        v_news = ("🗞️ Haber", "🟢 Pozitif", GREEN)
    else:
        v_news = ("🗞️ Haber", "🟢 Temiz", "#2dd4bf")

    if crisis:
        v_regime = ("🌍 Piyasa", f"🔴 Kriz ({vix:.0f})", RED)
    elif regime_code == "DUZELTME_BASKISI" or vix >= 21.5:
        v_regime = ("🌍 Piyasa", f"🟠 Baskı ({vix:.0f})", "#ff9100")
    elif regime_code == "GUCLU_BOGA":
        v_regime = ("🌍 Piyasa", f"🟢 Boğa ({vix:.0f})", GREEN)
    else:
        v_regime = ("🌍 Piyasa", f"🟡 Seçici ({vix:.0f})", BLUE)

    if ai_wp is None:
        v_ai = ("🤖 AI 15G", "⚪ Veri Yok", MUTED)
    elif ai_wp >= 58:
        v_ai = ("🤖 AI 15G", f"🟢 %{ai_wp}", GREEN)
    elif ai_wp >= 50:
        v_ai = ("🤖 AI 15G", f"🟡 %{ai_wp}", AMBER)
    else:
        v_ai = ("🤖 AI 15G", f"🔴 %{ai_wp}", RED)

    if state_code == "TEHLIKE":
        v_tech = ("📉 Teknik", "🔴 Stop Kırıldı", RED)
    elif new_low_recent:
        v_tech = ("📉 Teknik", "🔴 Düşen Bıçak", RED)
    elif state_code == "ALIM_FIRSATI":
        v_tech = ("📉 Teknik", "🟢 Dönüş Onaylı", GREEN)
    elif z2_h > 0 and price <= z2_h:
        v_tech = ("📉 Teknik", "🟡 2. Kademe", AMBER)
    elif z1_h > 0 and price <= z1_h * 1.015:
        v_tech = ("📉 Teknik", "🟡 1. Kademe", AMBER)
    else:
        v_tech = ("📉 Teknik", "🔵 Yüksek", BLUE)

    if days_e is not None and 0 <= days_e <= 14:
        v_earn = ("📅 Bilanço", f"🔴 {days_e}g Yakın", RED)
    elif days_e is not None and days_e <= 25:
        v_earn = ("📅 Bilanço", f"🟡 {days_e}g", AMBER)
    elif days_e is not None:
        v_earn = ("📅 Bilanço", f"🟢 {days_e}g", GREEN)
    else:
        v_earn = ("📅 Bilanço", "⚪ Uzak/Yok", MUTED)

    if brake_blocked:
        v_port = ("💼 Portföy", f"🛑 Fren ({brake.get('lot_count', 0)} lot)", RED)
    elif held:
        v_port = ("💼 Portföy", f"🟢 Açık ({brake.get('lot_count', 0)} lot)", GREEN)
    else:
        v_port = ("💼 Portföy", "⚪ Lot Yok", MUTED)

    votes = [
        {"label": lbl, "short": sh, "color": col}
        for (lbl, sh, col) in (v_news, v_regime, v_ai, v_tech, v_earn, v_port)
    ]

    # ─── 2. HİYERARŞİK TEK NİHAİ KARAR AĞACI (SIFIR ÇELİŞKİ) ───
    ai_caveat = (
        f"Yapay zeka 15 günlük tepki ihtimalini **%{ai_wp}** görse de, "
        if (ai_wp is not None and ai_wp >= 58)
        else ""
    )
    port_note = ""
    if brake_blocked:
        b_reasons = "; ".join(brake.get("reasons", []))
        port_note = (
            f" Ayrıca portföyünde zaten **{brake.get('lot_count', 0)} lot** mevcut "
            f"(son alış: **${brake.get('last_buy_price', 0):.2f}**) — {b_reasons}."
        )
    elif held:
        port_note = f" Portföyünde mevcut **{brake.get('lot_count', 0)} lot** bulunuyor."

    top_red = (news.get("red_events") or [{}])[0] if news.get("red_events") else None
    exit_code = str(ex.get("exit_code") or "")

    if state_code == "TEHLIKE":
        verdict_code = "ALMA_DESTEK_KIRILDI"
        verdict_badge = "🔴 ALMA — DESTEK KIRILDI"
        verdict_color = RED
        summary_tr = (
            f"{ai_caveat}{sym} ana güvenlik sınırı olan **${stop_lvl:.2f}** altına sarktı; "
            f"hisse 'düşen bıçak' durumunda olduğu için alım ve ortalama düşürme durduruldu.{port_note}"
        )
        next_trigger_tr = f"Fiyatın en az **${z2_h:.2f}** üzerine çıkıp günlük kapanışla tutunması."

    elif state_code == "HABER_VETOSU":
        verdict_code = "ALMA_HABER_SOKU"
        verdict_badge = "⛔ ALMA — HABER ŞOKU VETOSU"
        verdict_color = RED
        red_cat = top_red.get("category_label", "kötü haber") if top_red else "kötü haber"
        red_title = top_red.get("title", "") if top_red else ""
        post_l = news.get("post_shock_low")
        extra_blocks = []
        if crisis:
            extra_blocks.append(f"piyasanın yüksek korku rejiminde olması (VIX {vix:.1f})")
        if new_low_recent:
            extra_blocks.append("son 3 günde yeni dip yapılması")
        extra_str = (" ve " + ", ".join(extra_blocks)) if extra_blocks else ""
        title_snippet = f" (*\"{red_title[:90]}\"*)" if red_title else ""
        lead_son5 = "son 5 günde" if ai_caveat else "Son 5 günde"
        summary_tr = (
            f"{ai_caveat}{lead_son5} şirkete özel **{red_cat}**{title_snippet} tespit edilmesi{extra_str} "
            f"nedeniyle **alım durduruldu**. Kötü haberle düşen hisse ucuzlamış değil, hasar almış kabul edilir.{port_note}"
        )
        dip_txt = f" (**${post_l:.2f}**)" if post_l else ""
        next_trigger_tr = (
            f"Haber sonrası dibin{dip_txt} üzerinde **3–5 işlem günü** yeni dip yapmadan tutunması"
            + (" ve VIX'in 25 altına inmesi." if crisis else ".")
        )

    elif state_code == "BEKLEMEDE" and exit_code == "SIMDI_KAR_AL":
        verdict_code = "KAR_AL_SISKIN"
        verdict_badge = "💰 YENİ ALIM YOK — KÂR ALMA BÖLGESİ"
        verdict_color = "#00e676"
        summary_tr = (
            f"{sym} kısa vadede sert yükselip alım bölgesinin (**${z1_l:.2f}–${z1_h:.2f}**) "
            f"üzerine taştı ve yorulma sinyali veriyor. Yeni alım yapılmaz; elde kârlı lot varsa kademeli kâr realizasyonu düşünülür."
        )
        next_trigger_tr = f"Yeni giriş için **${z1_l:.2f}–${z1_h:.2f}** aralığına geri çekilme."

    elif state_code == "ALIM_FIRSATI" and brake_blocked:
        verdict_code = "EKLEME_PORTFOY_FRENI"
        verdict_badge = "🛑 EKLEME YAPMA — PORTFÖY FRENİ"
        verdict_color = RED
        summary_tr = (
            f"{sym} teknik, AI (**%{ai_wp or 58}+**) ve haber kalkanlarından geçti; ancak "
            f"portföyünde zaten **{brake.get('lot_count', 0)} lot** bulunduğu için **Portföy Freni** devreye girdi: "
            f"{'; '.join(brake.get('reasons', []))}."
        )
        next_trigger_tr = "VIX 25 altına inip son alışından en az %15 aşağıda temiz fırsat oluşması (veya başka sektörde fırsat aranması)."

    elif state_code == "ALIM_FIRSATI":
        which_tier = "1. Kademe" if price >= z2_h else "2. Kademe (Derin İskonto)"
        if size_hint == "YARIM":
            verdict_code = "AL_YARIM"
            verdict_badge = f"🟢 KADEMELİ AL — YARIM PARÇA ({which_tier})"
        else:
            verdict_code = "AL_KADEMELI"
            verdict_badge = f"🟢 KADEMELİ AL ({which_tier})"
        verdict_color = GREEN
        abs_note = (
            f" Önceki haber şoku fiyatlandı (dip **${news['post_shock_low']:.2f}** üzerinde tutunuyor)."
            if news_absorbed and news.get("post_shock_low")
            else ""
        )
        size_note = " Mevcut piyasa/haber ortamında planlanan parçanın **yarısıyla** giriş önerilir." if size_hint == "YARIM" else ""
        rr_txt = f", Ödül/Risk **{rr_ratio:.2f}R**" if rr_ratio is not None else ""
        summary_tr = (
            f"{sym} haber, rejim, dönüş onayı ve yapay zeka (**%{ai_wp or 58}** hedef olasılığı{rr_txt}) dahil "
            f"tüm kalkanlardan geçti. Kaçış sınırı **${stop_lvl:.2f}**, ilk hedef **${tp1:.2f}**.{abs_note}{size_note}"
        )
        next_trigger_tr = f"Stop (**${stop_lvl:.2f}**) altında kapanış olmadıkça ilk hedef **${tp1:.2f}** izlenir."

    elif state_code == "PUSUDA_IZLE":
        if days_e is not None and 0 <= days_e <= 14:
            verdict_code = "BEKLE_BILANCO"
            verdict_badge = f"⚠️ BEKLE — BİLANÇO KİLİDİ ({days_e} Gün)"
            verdict_color = "#ff9100"
        elif crisis and z2_h > 0 and price > z2_h:
            verdict_code = "BEKLE_KRIZ"
            verdict_badge = f"🟠 BEKLE — KRİZ REJİMİ (VIX {vix:.1f})"
            verdict_color = "#ff9100"
        else:
            verdict_code = "IZLE_KILIT_EKSIK"
            verdict_badge = f"🟡 İZLE — {len(gates)} ŞART EKSİK" if gates else "🟡 İZLE — DÖNÜŞ ONAYI BEKLENİYOR"
            verdict_color = AMBER

        diag_txt = f" Düşüş teşhisi: **{diag.get('label', '')}**." if diag.get("label") else ""
        top_gates = "; ".join(gates[:3]) if gates else "günlük kapanış dönüş onayı bekleniyor"
        summary_tr = (
            f"{ai_caveat}{sym} ucuzluk bölgesine indi (**${price:.2f}**) ancak güvenlik kilitleri alıma izin vermiyor: "
            f"{top_gates}.{diag_txt}{port_note}"
        )
        if days_e is not None and 0 <= days_e <= 14:
            next_trigger_tr = "Bilanço sonuçları açıklanıp ilk gün tepkisi netleştikten sonra tekrar değerlendirme."
        elif crisis and z2_h > 0 and price > z2_h:
            next_trigger_tr = f"2. kademe (**${z2_l:.2f}–${z2_h:.2f}**) testi veya VIX'in 25 altına gevşemesi + günlük dönüş mumu."
        else:
            next_trigger_tr = "Son 3 günde yeni dip yapmadan güçlü yeşil günlük kapanış ve tüm kilitlerin açılması."

    else:
        verdict_code = "BEKLE_FIYAT_YUKSEK"
        verdict_badge = "🔵 BEKLE — FİYAT HENÜZ YÜKSEK"
        verdict_color = BLUE
        summary_tr = (
            f"{sym} şu an **${price:.2f}** seviyesinde; ideal 1. alım bölgesi (**${z1_l:.2f}–${z1_h:.2f}**) "
            f"üzerinde olduğu için tepeden kovalamıyoruz.{port_note}"
        )
        next_trigger_tr = f"Fiyatın **${z1_l:.2f}–${z1_h:.2f}** aralığına geri çekilmesi."

    # Faktör skoru (varsa kısa not için)
    comp_score = fac.get("composite")

    return {
        "symbol": sym,
        "verdict_code": verdict_code,
        "verdict_badge": verdict_badge,
        "verdict_color": verdict_color,
        "summary_tr": summary_tr,
        "next_trigger_tr": next_trigger_tr,
        "votes": votes,
        "gates": gates,
        "size_hint": size_hint,
        "composite_score": comp_score,
    }


def render_vote_strip_html(votes: list[dict[str, Any]], next_trigger_tr: str = "") -> str:
    """6 alt-motorun oyunu tek satırda gösteren kompakt HTML şeridi."""
    if not votes:
        return ""
    chips = []
    for v in votes:
        col = v.get("color", MUTED)
        lbl = esc(v.get("label", ""))
        sh = esc(v.get("short", ""))
        chips.append(
            f"<span style='display:inline-flex; align-items:center; gap:5px; padding:4px 9px; "
            f"border-radius:8px; background:{CARD_2}; border:1px solid {BORDER}; font-size:0.75rem; color:{TEXT};'>"
            f"<span style='color:{MUTED};'>{lbl}:</span>"
            f"<b style='color:{col};'>{sh}</b></span>"
        )
    trigger_html = ""
    if next_trigger_tr:
        from web.components.ui import md_to_html
        trigger_html = (
            f"<div style='margin-top:8px; font-size:0.8rem; color:{MUTED};'>"
            f"🎯 <b style='color:{TEXT};'>Ne Beklenmeli?</b> {md_to_html(next_trigger_tr)}"
            f"</div>"
        )
    return (
        "<div style='display:flex; flex-wrap:wrap; gap:6px; margin-top:10px;'>"
        + "".join(chips)
        + "</div>"
        + trigger_html
    )
