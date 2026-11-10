"""
Sayfa 10: 🧠 AI Uzman Analist & Kalıcı Hafıza Merkezi
Tamamen borsa, trading, bilanço analizi ve Midas FIFO portföy yönetimine odaklanmış,
eski konuşmaları ve alınan kararları asla unutmayan kurumsal yapay zeka analisti.
"""
import os
import sys
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.ai_analyst import (
    add_memory_note,
    ask_ai_analyst,
    create_new_session,
    delete_memory_note,
    delete_session,
    get_active_session,
    load_ai_memory,
    load_ai_provider_config,
    load_chat_sessions,
    save_ai_provider_config,
    switch_session,
    test_ai_provider_connection,
)
from web.components.investment_committee import get_market_regime_summary
from web.components.ui import (
    ACCENT,
    AMBER,
    BLUE,
    BORDER,
    CARD,
    CARD_2,
    GREEN,
    MUTED,
    RED,
    TEXT,
    badge,
    esc,
    esc_dollars,
    page_header,
    regime_strip,
    section,
    stat_grid,
)

# ─── ÜST BAŞLIK & DURUM ÖZETİ ───
page_header(
    "🧠 AI Uzman Analist · Kalıcı Hafızalı Quant Stratejist",
    "Dip Avcısı, Üçlü Bariyer AI, Bilanço Motoru ve Midas FIFO portföyüne doğrudan bağlı; eski konuştuklarımızı unutmayan kurumsal analistin.",
)

mem_data = load_ai_memory()
sessions_data = load_chat_sessions()
active_session = get_active_session()
ai_cfg = load_ai_provider_config()

mem_count = len(mem_data.get("memory_notes", []))
ctx_syms = active_session.get("context_symbols", []) or mem_data.get("last_context", {}).get("last_symbols", [])
has_cloud_key = any([ai_cfg.get("gemini_api_key"), ai_cfg.get("groq_api_key"), ai_cfg.get("openai_api_key")])
engine_status_txt = "Bulut LLM + Canlı Quant" if has_cloud_key else "Kurumsal Quant & Hafıza Motoru"

st.markdown(
    f"""
    <div class='spp-card' style='padding:12px 16px; margin-bottom:12px;'>
        <div class='spp-row'>
            <div style='display:flex; gap:8px; flex-wrap:wrap; align-items:center;'>
                {badge(f"🧠 Kalıcı Hafıza Aktif ({mem_count} Kayıt)", GREEN)}
                {badge(f"⚡ {engine_status_txt}", ACCENT)}
                {badge(f"🎯 Bağlam: {', '.join(ctx_syms[:5])}" if ctx_syms else "🎯 Bağlam: Genel Piyasa", BLUE)}
            </div>
            <div class='spp-muted'>Oturum: <b>{esc(active_session.get('title', 'Ana Masa'))}</b></div>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

tab_chat, tab_memory, tab_settings = st.tabs([
    "💬 Uzman Analist Masası",
    f"🧠 Kalıcı Hafıza & Oturumlar ({mem_count})",
    "⚙️ AI Motoru Ayarları",
])

# ═══════════════════════════════════════════════════════════════════════
# SEKME 1: CANLI SOHBET & HIZLI ANALİZ MASASI
# ═══════════════════════════════════════════════════════════════════════
with tab_chat:
    # ─── Tek Tık Hızlı Analiz Komutları ───
    st.markdown("<div class='spp-muted' style='margin-bottom:6px;'>⚡ <b>Tek Tık Hızlı Analiz Soruları:</b></div>", unsafe_allow_html=True)
    qc1, qc2, qc3 = st.columns(3)
    quick_prompt_triggered = None

    with qc1:
        if st.button("⚔️ COHR, MRVL, BE, RKLB Kıyasla (2'sini Seç)", use_container_width=True, key="qp_compare4"):
            quick_prompt_triggered = "COHR, MRVL, BE, RKLB hisselerini güncel verilerle analiz et, iki tanesini alacağım hangileri olmalı?"
    with qc2:
        if st.button("📅 COHR & Takip Listem Bilanço Sonuçları", use_container_width=True, key="qp_earnings"):
            quick_prompt_triggered = "COHR bilanço sonuçları ne durumda, hepsi açıklandı mı ve nasıl geldi? Diğer hisselerin bilanço takvimi ne?"
    with qc3:
        if st.button("💼 Midas FIFO Portföyüm & 5 MU Lotum", use_container_width=True, key="qp_portfolio"):
            quick_prompt_triggered = "Midas portföyümdeki 5 adet MU lotumu, FIFO kuralına göre ilk satılacak lotu ve kâr/zarar durumumu analiz et."

    qc4, qc5, qc6 = st.columns(3)
    with qc4:
        if st.button("🎯 Bugün Dip Avcısı'nda En İyi Fırsatlar", use_container_width=True, key="qp_opps"):
            quick_prompt_triggered = "Bugün takip listemizde Dip Avcısı ve Üçlü Bariyer AI'ya göre en iyi alım fırsatları hangileri?"
    with qc5:
        if st.button("🇹🇷 SARAE.IS 70-80 TL Toparlanma Takvimi", use_container_width=True, key="qp_sarae"):
            quick_prompt_triggered = "SARAE enerji halka arzdan sonra ciddi düştü, 70-80 TL bandına geri toparlanması ne zaman olur?"
    with qc6:
        if st.button("➕ Yeni Sohbet Başlığı Aç (Hafıza Korunur)", use_container_width=True, key="qp_new_sess"):
            create_new_session()
            st.rerun()

    st.divider()

    # ─── Sohbet Geçmişini Göster ───
    messages = active_session.get("messages", [])
    if not messages:
        st.info(
            "👋 **Selam Talha!** Kalıcı hafızamdaki tüm geçmiş analizlerimiz (`COHR`, `MRVL`, `BE`, `RKLB`, `SARAE.IS` ve 5 kademeli `MU` Midas FIFO portföyün) hazır. "
            "Yukarıdaki hızlı butonlardan birine tıklayabilir veya aşağıdan istediğin soruyu sorabilirsin."
        )

    for idx, msg in enumerate(messages):
        role = msg.get("role", "assistant")
        avatar = "🧑‍💻" if role == "user" else "🏦"
        with st.chat_message(role, avatar=avatar):
            ts = msg.get("timestamp", "")
            syms = msg.get("symbols", [])
            eng = msg.get("engine", "")
            meta_parts = []
            if ts:
                meta_parts.append(f"🕒 {ts}")
            if syms:
                meta_parts.append(f"📌 {', '.join(syms)}")
            if eng and role == "assistant":
                meta_parts.append(f"⚡ {eng}")
            if meta_parts:
                st.caption(" · ".join(meta_parts))

            st.markdown(esc_dollars(msg.get("content", "")))

            # Eğer asistansa ve canlı telemetri kartları varsa expander içinde göster
            t_cards = msg.get("telemetry_cards", [])
            if role == "assistant" and t_cards:
                with st.expander(f"📊 Arka Planda Çekilen Canlı Kurumsal Veri Özeti ({len(t_cards)} Hisse)", expanded=False):
                    for tc in t_cards:
                        cur = tc.get("currency", "$")
                        fpe_txt = f"{tc['forward_pe']:.1f}x" if tc.get("forward_pe") else "—"
                        st.markdown(
                            f"**`{tc['symbol']}`** ({tc.get('name', '')}) — Fiyat: **{cur}{tc.get('price', 0):,.2f}** ({tc.get('daily_chg_pct', 0):+.2f}%) · "
                            f"RSI(14): **{tc.get('rsi14', 0):.1f}** · İleri F/K: **{fpe_txt}** · "
                            f"Durum: {tc.get('state_badge', '—')} · 1. Kademe: `{tc.get('zone1', '—')}` · "
                            f"Hedef: `{tc.get('target1', '—')}` · Stop: `{tc.get('stop', '—')}`"
                        )

            # Asistan cevabını kalıcı hafızaya tek tıkla sabitleme butonu
            if role == "assistant":
                pin_key = f"pin_msg_{active_session.get('id')}_{idx}"
                if st.button("📌 Bu Analizi Kalıcı Hafızaya Sabitle", key=pin_key):
                    summary_txt = msg.get("content", "")[:500].replace("\n", " ")
                    title_syms = ", ".join(syms) if syms else "Genel Strateji"
                    add_memory_note(
                        title=f"Sabitlenen Analiz: {title_syms} ({ts})",
                        content=summary_txt,
                        category="SABITLENEN_ANALIZ",
                        symbols=syms,
                        pinned=True,
                    )
                    st.toast("Analiz kalıcı hafızaya sabitlendi!", icon="🧠")
                    st.rerun()

    # ─── Yeni Soru Girişi (Chat Input veya Hızlı Buton) ───
    user_input = st.chat_input(
        "Uzman analistine sor (Örn: COHR ve MRVL son durum ne? / NVDA ve AVGO kıyasla / Bunu unutma: MRVL 196$'dan aldım)..."
    )

    final_query = quick_prompt_triggered or user_input
    if final_query:
        with st.chat_message("user", avatar="🧑‍💻"):
            st.markdown(esc_dollars(final_query))

        with st.chat_message("assistant", avatar="🏦"):
            with st.spinner("Canlı piyasa verileri, Dip Avcısı seviyeleri, bilanço takvimi ve kalıcı hafıza taranıyor..."):
                result = ask_ai_analyst(final_query)
            st.markdown(esc_dollars(result["response"]))
        st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# SEKME 2: KALICI HAFIZA DEFTERİ & GEÇMİŞ OTURUMLAR
# ═══════════════════════════════════════════════════════════════════════
with tab_memory:
    col_m1, col_m2 = st.columns([1.6, 1])

    with col_m1:
        section("🧠 Kalıcı Hafızadaki Kayıtlı Analizler & Kurallar")
        st.caption(
            "Buradaki kayıtlar asla silinmez; yeni bir sohbet açsan veya uygulamayı kapatıp haftalar sonra girsen bile "
            "yapay zeka bu hafızayı okuyarak sana cevap verir."
        )

        for note in mem_data.get("memory_notes", []):
            nid = note.get("id", "")
            cat = note.get("category", "GENEL")
            ndate = note.get("date", "")
            nsyms = ", ".join(note.get("symbols", []))
            ntitle = note.get("title", "")
            ncontent = note.get("content", "")

            st.markdown(
                f"""
                <div class='spp-card' style='padding:14px 16px; margin-bottom:10px;'>
                    <div class='spp-row'>
                        <div><b>{esc(ntitle)}</b></div>
                        <div style='display:flex; gap:6px;'>
                            {badge(cat, ACCENT)}
                            {badge(nsyms, BLUE) if nsyms else ""}
                            <span class='spp-muted'>{esc(ndate)}</span>
                        </div>
                    </div>
                    <div class='spp-headline' style='font-size:0.86rem; margin-top:8px;'>{esc(ncontent)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"🗑️ Kaydı Sil ({ntitle[:28]}...)", key=f"del_mem_{nid}"):
                delete_memory_note(nid)
                st.rerun()

    with col_m2:
        section("➕ Hafızaya Yeni Kural / Not Ekle")
        with st.form("add_manual_memory_form", clear_on_submit=True):
            m_title = st.text_input("Başlık", placeholder="Örn: COHR 1. Kademe Alımım")
            m_syms = st.text_input("İlgili Hisseler (virgülle)", placeholder="Örn: COHR, MRVL")
            m_cat = st.selectbox("Kategori", ["PORTFOY_KARARI", "STRATEJI_KURALI", "BILANCO_SONUCU", "BIST_ANALIZ", "KULLANICI_NOTU"])
            m_content = st.text_area("Detay / Kural", placeholder="Örn: COHR hissesinden $209 maliyetle 2 adet aldım, hedefim $260.")
            if st.form_submit_button("💾 Kalıcı Hafızaya Kaydet", type="primary", use_container_width=True):
                if m_title.strip() and m_content.strip():
                    sym_list = [s.strip().upper() for s in m_syms.split(",") if s.strip()]
                    add_memory_note(m_title, m_content, m_cat, sym_list, pinned=True)
                    st.success("Kalıcı hafızaya eklendi!")
                    st.rerun()
                else:
                    st.warning("Başlık ve içerik alanlarını doldurun.")

        st.divider()
        section("🗂️ Sohbet Oturumları Geçmişi")
        for sess in sessions_data.get("sessions", []):
            sid = sess.get("id")
            is_active = sid == sessions_data.get("active_session_id")
            msg_cnt = len(sess.get("messages", []))
            s_col1, s_col2 = st.columns([3.5, 1])
            with s_col1:
                btn_lbl = f"{'🟢 ' if is_active else '💬 '}{sess.get('title')} ({msg_cnt} mesaj)"
                if st.button(btn_lbl, key=f"sw_sess_{sid}", use_container_width=True, type="primary" if is_active else "secondary"):
                    switch_session(sid)
                    st.rerun()
            with s_col2:
                if st.button("🗑️", key=f"del_sess_{sid}", help="Bu sohbet oturumunu sil", use_container_width=True):
                    delete_session(sid)
                    st.rerun()


# ═══════════════════════════════════════════════════════════════════════
# SEKME 3: AI MOTORU & BULUT LLM AYARLARI
# ═══════════════════════════════════════════════════════════════════════
with tab_settings:
    section("⚙️ Yapay Zeka Motoru & Opsiyonel Bulut LLM Bağlantısı")

    if "ai_settings_saved_msg" in st.session_state:
        saved_ok, saved_msg = st.session_state.pop("ai_settings_saved_msg")
        if saved_ok:
            st.success(saved_msg)
        else:
            st.warning(saved_msg)

    if has_cloud_key:
        active_prov_label = (
            f"Google Gemini ({ai_cfg.get('gemini_model', 'gemini-2.5-flash')})"
            if ai_cfg.get("gemini_api_key")
            else (
                f"Groq ({ai_cfg.get('groq_model', 'llama-3.3-70b-versatile')})"
                if ai_cfg.get("groq_api_key")
                else f"OpenAI ({ai_cfg.get('openai_model', 'gpt-4o')})"
            )
        )
        st.success(
            f"🟢 **Bulut LLM + Canlı Quant Motoru Aktif!** Şu an **{active_prov_label}** anahtarın tanımlı ve devrede. "
            f"Soldaki **💬 Uzman Analist Masası** sekmesine geçip sorularını doğrudan sorabilirsin."
        )
    else:
        st.info(
            "💡 **Bilgi:** Sistem şu an **Yerleşik Kurumsal Quant & Hafıza Motoru** ile hiçbir harici anahtara ihtiyaç duymadan "
            "tüm canlı fiyatları, Dip Avcısı seviyelerini, bilançoları ve kalıcı hafızayı sentezleyerek tam kapasite çalışmaktadır. "
            "İstersen aşağıdan ücretsiz **Google Gemini (AI Studio)** veya **Groq** anahtarı ekleyerek bulut LLM katmanını da aktif edebilirsin."
        )

    gem_models = ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"]
    saved_gem_model = ai_cfg.get("gemini_model", "gemini-2.5-flash")
    gem_idx = gem_models.index(saved_gem_model) if saved_gem_model in gem_models else 0

    groq_models = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
    saved_groq_model = ai_cfg.get("groq_model", "llama-3.3-70b-versatile")
    groq_idx = groq_models.index(saved_groq_model) if saved_groq_model in groq_models else 0

    oai_models = ["gpt-4o", "gpt-4o-mini"]
    saved_oai_model = ai_cfg.get("openai_model", "gpt-4o")
    oai_idx = oai_models.index(saved_oai_model) if saved_oai_model in oai_models else 0

    with st.form("ai_provider_settings_form"):
        prov = st.selectbox(
            "Tercih Edilen Motor",
            options=["auto", "gemini", "groq", "openai"],
            index=["auto", "gemini", "groq", "openai"].index(ai_cfg.get("provider", "auto")) if ai_cfg.get("provider") in ["auto", "gemini", "groq", "openai"] else 0,
            format_func=lambda x: {
                "auto": "🔄 Otomatik (Anahtar Varsa Bulut LLM + Canlı Quant, Yoksa Yerleşik Quant Motoru)",
                "gemini": "✨ Google Gemini (2.5 Flash / Pro) + Canlı Quant Telemetri",
                "groq": "⚡ Groq (Llama-3.3-70B Versatile) + Canlı Quant Telemetri",
                "openai": "🧠 OpenAI (GPT-4o) + Canlı Quant Telemetri",
            }[x],
        )

        c_g1, c_g2 = st.columns([2, 1])
        with c_g1:
            gem_key = st.text_input("Google Gemini API Key (Ücretsiz: aistudio.google.com)", value=ai_cfg.get("gemini_api_key", ""), type="password")
        with c_g2:
            gem_model = st.selectbox("Gemini Modeli", gem_models, index=gem_idx)

        c_q1, c_q2 = st.columns([2, 1])
        with c_q1:
            groq_key = st.text_input("Groq API Key (Ücretsiz: console.groq.com)", value=ai_cfg.get("groq_api_key", ""), type="password")
        with c_q2:
            groq_model = st.selectbox("Groq Modeli", groq_models, index=groq_idx)

        c_o1, c_o2 = st.columns([2, 1])
        with c_o1:
            oai_key = st.text_input("OpenAI API Key (Opsiyonel)", value=ai_cfg.get("openai_api_key", ""), type="password")
        with c_o2:
            oai_model = st.selectbox("OpenAI Modeli", oai_models, index=oai_idx)

        if st.form_submit_button("💾 AI Motor Ayarlarını Kaydet ve Bağlantıyı Doğrula", type="primary", use_container_width=True):
            new_cfg = {
                "provider": prov,
                "gemini_api_key": gem_key.strip(),
                "gemini_model": gem_model,
                "groq_api_key": groq_key.strip(),
                "groq_model": groq_model,
                "openai_api_key": oai_key.strip(),
                "openai_model": oai_model,
            }
            save_ai_provider_config(new_cfg)
            ok, status_msg = test_ai_provider_connection(new_cfg)
            st.session_state["ai_settings_saved_msg"] = (ok, status_msg)
            st.rerun()
