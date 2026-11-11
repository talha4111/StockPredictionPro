"""
Sayfa 10: 🧠 AI Uzman Analist & Kalıcı Hafıza Merkezi
Soru odaklı kurumsal muhakeme motoru, tek tıkla anında yanıt paneli ve
tıklayınca açılan (kompakt) hafıza/sohbet mimarisi.
"""
import os
import sys
import streamlit as st
import streamlit.components.v1 as _components

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
    section,
)

# ─── KURUMSAL ARAYÜZ STİLLERİ (SADE, KOMPAKT, PROFESYONEL) ───
st.markdown(
    """
    <style>
    /* Tek tık hızlı analiz butonları için kurumsal kompakt görünüm */
    div[data-testid="stHorizontalBlock"] .stButton > button {
        border-radius: 8px !important;
        font-weight: 600 !important;
        font-size: 0.84rem !important;
        padding: 0.42rem 0.65rem !important;
        transition: all 0.18s ease-in-out !important;
        border: 1px solid rgba(148, 163, 184, 0.22) !important;
    }
    div[data-testid="stHorizontalBlock"] .stButton > button:hover {
        border-color: #38bdf8 !important;
        transform: translateY(-1px);
        box-shadow: 0 4px 12px rgba(56, 189, 248, 0.15) !important;
    }
    /* Tıklayınca büyüyen (Expander) kutular için sade başlık stili */
    div[data-testid="stExpander"] {
        border-radius: 10px !important;
        border: 1px solid rgba(148, 163, 184, 0.16) !important;
        background: rgba(15, 23, 42, 0.45) !important;
        margin-bottom: 6px !important;
    }
    div[data-testid="stExpander"] summary {
        font-size: 0.88rem !important;
        font-weight: 600 !important;
        padding: 0.55rem 0.85rem !important;
    }
    /* Aktif Analist Yanıt Kartı */
    .spp-active-answer-header {
        background: linear-gradient(90deg, rgba(16, 185, 129, 0.14) 0%, rgba(56, 189, 248, 0.08) 100%);
        border-left: 4px solid #10b981;
        border-radius: 8px;
        padding: 10px 14px;
        margin-bottom: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 8px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ─── ÜST BAŞLIK & KOMPAKT DURUM ŞERİDİ ───
page_header(
    "🧠 AI Uzman Analist · Soru Odaklı Quant Stratejist",
    "Sorduğun soruya doğrudan odaklanan, canlı Fibonacci/RSI/Bilanço ve Wall Street hedeflerini sentezleyen kurumsal analist masası.",
)

mem_data = load_ai_memory()
sessions_data = load_chat_sessions()
active_session = get_active_session()
ai_cfg = load_ai_provider_config()

mem_count = len(mem_data.get("memory_notes", []))
ctx_syms = active_session.get("context_symbols", []) or mem_data.get("last_context", {}).get("last_symbols", [])
has_cloud_key = any([ai_cfg.get("gemini_api_key"), ai_cfg.get("groq_api_key"), ai_cfg.get("openai_api_key")])
engine_status_txt = "Bulut LLM + Canlı Quant" if has_cloud_key else "Soru Odaklı Quant & Hafıza Motoru"

st.markdown(
    f"""
    <div class='spp-card' style='padding:10px 14px; margin-bottom:10px;'>
        <div class='spp-row'>
            <div style='display:flex; gap:8px; flex-wrap:wrap; align-items:center;'>
                {badge(f"🧠 Kalıcı Hafıza ({mem_count} Kayıt)", GREEN)}
                {badge(f"⚡ {engine_status_txt}", ACCENT)}
                {badge(f"🎯 Aktif Hisseler: {', '.join(ctx_syms[:5])}" if ctx_syms else "🎯 Bağlam: Genel Piyasa", BLUE)}
            </div>
            <div class='spp-muted' style='font-size:0.82rem;'>Oturum: <b>{esc(active_session.get('title', 'Ana Masa'))}</b></div>
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


def _render_structured_answer(ans: dict, key_suffix: str):
    """
    Asistan yanıtını sade ve düzenli çizer:
    - Doğrudan cevap (özet ve hedef seviyeler) hemen görünür.
    - Detaylı tablolar ve senaryo haritası ('<!-- DETAILS_SPLIT -->' sonrası) tıklayınca büyüyen kutuda yer alır.
    - Canlı telemetri rozetleri ve Hafızaya Sabitle butonu alt şeritte kompakt durur.
    """
    meta = []
    if ans.get("timestamp"):
        meta.append(f"🕒 {ans['timestamp']}")
    if ans.get("symbols"):
        meta.append(f"📌 {', '.join(ans['symbols'])}")
    if ans.get("engine"):
        meta.append(f"⚡ {ans['engine']}")
    if meta:
        st.caption(" · ".join(meta))

    raw_content = ans.get("content", "") or ans.get("response", "")
    if "<!-- DETAILS_SPLIT -->" in raw_content:
        main_part, detail_part = raw_content.split("<!-- DETAILS_SPLIT -->", 1)
        st.markdown(esc_dollars(main_part.strip()))
        if detail_part.strip():
            with st.expander("📐 Detaylı Teknik Tablo, Çarpanlar & Senaryo Haritası (Tıkla & Büyüt)", expanded=False):
                st.markdown(esc_dollars(detail_part.strip()))
    else:
        st.markdown(esc_dollars(raw_content))

    t_cards = ans.get("telemetry_cards", [])
    c_a, c_b = st.columns([3.2, 1])
    with c_a:
        if t_cards:
            with st.expander(f"📊 Canlı Piyasa Telemetri Özeti ({len(t_cards)} Hisse — Tıkla & Büyüt)", expanded=False):
                for tc in t_cards:
                    cur = tc.get("currency", "$")
                    fpe_txt = f"{tc['forward_pe']:.1f}x" if tc.get("forward_pe") else "—"
                    st.markdown(esc_dollars(
                        f"**`{tc['symbol']}`** — **{cur}{tc.get('price', 0):,.2f}** ({tc.get('daily_chg_pct', 0):+.2f}%) · "
                        f"RSI: **{tc.get('rsi14', 0):.0f}** · İleri F/K: **{fpe_txt}** · {tc.get('state_badge', '—')} · "
                        f"1. Kademe: `{tc.get('zone1', '—')}` · Hedef: `{tc.get('target1', '—')}` · Stop: `{tc.get('stop', '—')}`"
                    ))
    with c_b:
        if st.button("📌 Hafızaya Sabitle", key=f"pin_{key_suffix}", use_container_width=True):
            syms = ans.get("symbols", [])
            add_memory_note(
                title=f"Sabitlenen Analiz: {', '.join(syms) if syms else 'Strateji'} ({ans.get('timestamp', 'Canlı')})",
                content=raw_content.replace("<!-- DETAILS_SPLIT -->", " ")[:500].replace("\n", " "),
                category="SABITLENEN_ANALIZ",
                symbols=syms,
                pinned=True,
            )
            st.toast("Analiz kalıcı hafızaya sabitlendi!", icon="🧠")


# ═══════════════════════════════════════════════════════════════════════
# SEKME 1: SADE, HIZLI & SORU ODAKLI UZMAN ANALİST MASASI
# ═══════════════════════════════════════════════════════════════════════
with tab_chat:
    # ─── 1. HEDEF HİSSE SEÇİCİ & TEK TIKLA SORU ODAKLI ANALİZ ÇUBUĞU ───
    DEFAULT_WATCHLIST = ["MU", "COHR", "MRVL", "BE", "RKLB", "AVGO", "NVDA", "EOG", "SARAE.IS", "AMD", "PLTR", "TSLA", "AAPL", "MSFT"]
    default_sel = [s for s in (ctx_syms[:3] if ctx_syms else ["MU", "COHR", "MRVL"]) if s in DEFAULT_WATCHLIST] or ["MU", "COHR"]

    sel_col1, sel_col2, sel_col3 = st.columns([2.8, 1.3, 0.9])
    with sel_col1:
        selected_tickers = st.multiselect(
            "🎯 Hızlı Analiz İçin Hedef Hisse(ler)",
            options=DEFAULT_WATCHLIST,
            default=default_sel,
            help="Aşağıdaki tek tık analiz butonları burada seçtiğin hisse(ler) için anında canlı hesaplama yapar.",
        )
    with sel_col2:
        custom_ticker = st.text_input(
            "➕ Özel Sembol Ekle",
            placeholder="Örn: SMCI, THYAO.IS",
            help="Listede olmayan bir ABD veya BIST (.IS) hissesi yazabilirsin.",
        )
    with sel_col3:
        st.markdown("<div style='height:28px;'></div>", unsafe_allow_html=True)
        if st.button("🔄 Yeni Masa", key="btn_new_sess_top", use_container_width=True, help="Kalıcı hafızayı koruyarak temiz bir sohbet sayfası açar."):
            create_new_session()
            st.session_state.pop("active_answer_data", None)
            st.rerun()

    target_List = list(selected_tickers)
    if custom_ticker.strip():
        for ct in custom_ticker.replace(";", ",").split(","):
            ct_clean = ct.strip().upper()
            if ct_clean and ct_clean not in target_List:
                target_List.append(ct_clean)
    if not target_List:
        target_List = ["MU", "COHR"]
    target_str = ", ".join(target_List)

    # Tek Tıkla Odaklı Sorular (Uzun paragraf göstermez; tıklayınca doğrudan ilgili soruyu çalıştırıp cevaba atar)
    b1, b2, b3, b4, b5, b6 = st.columns(6)
    triggered_query: str | None = None

    with b1:
        if st.button("📈 Yükselişi Korur mu?", key="qa_dir", use_container_width=True, help=f"{target_str} yükselişi koruyarak ilerleyecek mi, daha düşme ihtimali var mı?"):
            triggered_query = f"{target_str} yükselişi koruyarak ilerleyecek mi, yoksa daha da düşme ihtimali var mı?"
    with b2:
        if st.button("📉 Şişti mi / Kaça Düşer?", key="qa_pull", use_container_width=True, help=f"{target_str} şu anda çok şişti mi, kar satışıyla toparlayıp ortalama kaçlara düşer?"):
            triggered_query = f"{target_str} şu anda çok şişti mi ve toparlayıp ortalama kaçlara düşer?"
    with b3:
        if st.button("🏦 Uzman Analist & Hedef", key="qa_anl", use_container_width=True, help=f"{target_str} için Wall Street uzman analistlerin görüşleri, hedef fiyatları ve son reytingleri ne?"):
            triggered_query = f"{target_str} için uzman analistlerin görüşleri, hedef fiyat aralığı ve son kurum tavsiyeleri neler?"
    with b4:
        if st.button("⚔️ Hisseleri Kıyasla", key="qa_cmp", use_container_width=True, help="Seçili hisseleri güncel verilerle kıyasla ve en güçlü adayları seç"):
            cmp_syms = target_str if len(target_List) >= 2 else "COHR, MRVL, BE, RKLB"
            triggered_query = f"{cmp_syms} hisselerini güncel verilerle kıyasla, hangisi daha güçlü ve alınır?"
    with b5:
        if st.button("📅 Bilanço & Takvim", key="qa_earn", use_container_width=True, help=f"{target_str} bilanço sonuçları, rehberlik (guidance) ve gelecek bilanço takvimi ne durumda?"):
            triggered_query = f"{target_str} bilanço sonuçları ne durumda, beklentileri aştı mı ve sıradaki bilanço takvimi ne?"
    with b6:
        if st.button("💼 Midas FIFO Portföyüm", key="qa_fifo", use_container_width=True, help="Midas portföyümdeki MU lotlarımı, FIFO kuralına göre ilk satılacak lotu ve kâr/zarar durumumu analiz et"):
            triggered_query = "Midas portföyümdeki MU lotlarımı, FIFO kuralına göre ilk satılacak lotu ve kâr/zarar durumumu analiz et."

    # ─── 2. HAZIR KISAYOL SORULARI & HAFIZA ÖZETİ (KAPALI KUTU — TIKLAYINCA BÜYÜR) ───
    with st.expander("⚡ Hazır Kısayol Soruları & Kayıtlı Hafıza Özeti (Tıkla & Büyüt)", expanded=False):
        st.caption("Sayfada kalabalık yapmaması için hazır detaylı sorular ve hafıza notları burada toplanmıştır. İstediğin soruya tıkladığında yanıt hemen üstteki ana ekranda açılır:")
        preset_questions = [
            ("🔬 Micron (MU) Dip & Trend Analizi", "MU uzun düşüşlerden sonra yükselişe başladı ama bu yükselişi koruyarak ilerleyecek mi, daha da düşme ihtimali var mı?"),
            ("🚀 COHR, MRVL & BE Ralli ve Soğuma Testi", "COHR, MRVL ve BE güzel artış yakaladılar; şu anda çok şiştiler mi, toparlayıp ortalama kaçlara düşerler ve uzman analist görüşleri ne?"),
            ("⚔️ COHR, MRVL, BE, RKLB 4'lü Seçim", "COHR, MRVL, BE, RKLB hisselerini güncel verilerle analiz et, iki tanesini alacağım hangileri olmalı?"),
            ("🇹🇷 SARAE.IS Toparlanma Takvimi", "SARAE enerji halka arzdan sonra ciddi düştü, 70-80 TL bandına geri toparlanması ne zaman olur?"),
            ("🎯 Günün Dip Avcısı & AI Fırsatları", "Bugün takip listemizde Dip Avcısı ve Üçlü Bariyer AI'ya göre en iyi alım fırsatları hangileri?"),
        ]
        p_cols = st.columns(2)
        for idx, (short_lbl, full_q) in enumerate(preset_questions):
            with p_cols[idx % 2]:
                if st.button(f"▶️ {short_lbl}", key=f"preset_q_{idx}", use_container_width=True, help=full_q):
                    triggered_query = full_q

        if mem_data.get("memory_notes"):
            st.markdown("---")
            st.caption("🧠 **Kalıcı Hafızadaki Son Kayıtlar (Özet):**")
            for mn in mem_data.get("memory_notes", [])[:4]:
                st.markdown(f"* **`[{mn.get('date', '')}] {mn.get('title', '')}`** — _{esc_dollars(mn.get('content', '')[:140])}..._")

    # ─── 3. SERBEST SORU GİRİŞ ÇUBUĞU ───
    user_input = st.chat_input(
        "Sorunu doğal dille yaz (Örn: COHR şu anda çok şişti mi, ortalama kaça düşer? / MU yükselişi korur mu? / MRVL uzman analist hedefleri ne?)"
    )
    if user_input:
        triggered_query = user_input

    # Eğer bekleyen bir sorgu tetiklendiyse tek adımda (çift rerun yapmadan) hemen çalıştır ve aktif yanıt paneline koy
    if "ai_pending_query" in st.session_state and not triggered_query:
        triggered_query = st.session_state.pop("ai_pending_query")

    st.markdown("<div id='active-analyst-answer-box'></div>", unsafe_allow_html=True)

    if triggered_query:
        with st.spinner(f"🔍 '{triggered_query[:75]}...' için canlı fiyat, Fibonacci durakları, RSI ve analist hedefleri hesaplanıyor..."):
            res = ask_ai_analyst(triggered_query)
            st.session_state["active_answer_data"] = {
                "question": triggered_query,
                "content": res.get("response", ""),
                "symbols": res.get("symbols", []),
                "engine": res.get("engine", ""),
                "telemetry_cards": res.get("telemetry_cards", []),
                "timestamp": "Şimdi (Canlı)",
            }
            # Güncel oturumu yeniden oku ki geçmiş listesi de güncellensin
            active_session = get_active_session()

        # Yanıt üretildiği anda doğrudan aktif cevap kutusuna kaydır
        _components.html(
            """
            <script>
            setTimeout(function () {
                const el = window.parent.document.getElementById('active-analyst-answer-box');
                if (el) { el.scrollIntoView({behavior: 'smooth', block: 'start'}); }
            }, 150);
            </script>
            """,
            height=0,
        )

    # ─── 4. AKTİF UZMAN ANALİST YANITI (HEMEN BUTONLARIN ALTINDA AÇIK) ───
    messages = active_session.get("messages", [])
    exchanges: list[tuple[dict, dict | None]] = []
    pending_u = None
    for m in messages:
        if m.get("role") == "user":
            if pending_u is not None:
                exchanges.append((pending_u, None))
            pending_u = m
        else:
            exchanges.append((pending_u or {"content": "", "timestamp": m.get("timestamp", "")}, m))
            pending_u = None
    if pending_u is not None:
        exchanges.append((pending_u, None))

    active_ans = st.session_state.get("active_answer_data")

    if active_ans:
        st.markdown(
            f"""
            <div class='spp-active-answer-header'>
                <div>
                    <span style='color:#10b981; font-weight:700;'>🎯 AKTİF UZMAN ANALİST YANITI</span>
                    <span style='color:#cbd5e1; font-size:0.9rem; margin-left:8px;'>— {esc(active_ans.get('question', ''))}</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.container(border=True):
            _render_structured_answer(active_ans, "active_top")
    else:
        # Henüz bu ekranda yeni bir soruya tıklanmadıysa eski uzun paragrafları ekrana yığma!
        st.markdown(
            """
            <div class='spp-card' style='padding:14px 18px; border-left:4px solid #38bdf8; margin-bottom:10px;'>
                <div style='font-weight:700; color:#f8fafc; margin-bottom:4px;'>👋 Uzman Analist Masası Hazır</div>
                <div style='color:#94a3b8; font-size:0.88rem;'>
                    Yukarıdan hedef hisseni seçip <b>tek tık analiz butonlarından</b> birine basabilir veya alttaki kutudan istediğin soruyu sorabilirsin.
                    <i>Sayfa karmaşasını önlemek için önceki konuşmalarımız aşağıda başlık halinde kapalı tutulmaktadır; istediğin konuşmaya tıklayarak büyütebilirsin.</i>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    # ─── 5. GEÇMİŞ KONUŞMALARIMIZ (TAMAMI KAPALI SATIRLAR — TIKLAYINCA BÜYÜR) ───
    # Eğer aktif yanıt en son mesajla aynıysa geçmiş listesinde tekrar etmemek için onu ayır
    history_items = exchanges[:-1] if (active_ans and exchanges) else exchanges

    if history_items:
        st.markdown(
            f"<div class='spp-muted' style='margin:14px 0 6px; font-size:0.86rem;'>"
            f"🗂️ <b>Geçmiş Konuşmalarımız ({len(history_items)} Kayıt)</b> — <i>Okumak istediğin sorunun üzerine tıklayınca büyür</i>"
            f"</div>",
            unsafe_allow_html=True,
        )
        sess_id = active_session.get("id", "s")
        for i, (q_msg, a_msg) in enumerate(reversed(history_items)):
            q_txt = (q_msg.get("content", "") or "").replace("\n", " ").strip()
            short_q = q_txt if len(q_txt) <= 92 else q_txt[:89] + "..."
            ts = q_msg.get("timestamp", "") or (a_msg or {}).get("timestamp", "")
            syms_badge = f" [{', '.join((a_msg or {}).get('symbols', [])[:3])}]" if (a_msg or {}).get("symbols") else ""
            exp_title = f"💬 {ts}{syms_badge} — {short_q}" if ts else f"💬 {short_q}"

            with st.expander(exp_title, expanded=False):
                st.markdown(f"**🧑‍💻 Soru:** {esc_dollars(q_txt)}")
                st.divider()
                if a_msg:
                    _render_structured_answer(a_msg, f"{sess_id}_hist_{i}")
                else:
                    st.caption("Bu soruya ait kayıtlı yanıt bulunamadı.")


# ═══════════════════════════════════════════════════════════════════════
# SEKME 2: KALICI HAFIZA DEFTERİ & GEÇMİŞ OTURUMLAR
# ═══════════════════════════════════════════════════════════════════════
with tab_memory:
    col_m1, col_m2 = st.columns([1.6, 1])

    with col_m1:
        section("🧠 Kalıcı Hafızadaki Kayıtlı Analizler & Kurallar")
        st.caption(
            "Buradaki kayıtlar asla silinmez; tümü başlık halinde kapalıdır, üzerine tıkladığında detayları büyür."
        )

        for note in mem_data.get("memory_notes", []):
            nid = note.get("id", "")
            cat = note.get("category", "GENEL")
            ndate = note.get("date", "")
            nsyms = ", ".join(note.get("symbols", []))
            ntitle = note.get("title", "")
            ncontent = note.get("content", "")

            with st.expander(f"{'📌 ' if note.get('pinned') else ''}{ntitle}  ·  {ndate}", expanded=False):
                st.markdown(
                    f"<div style='display:flex; gap:6px; margin-bottom:6px;'>{badge(cat, ACCENT)}{badge(nsyms, BLUE) if nsyms else ''}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(esc_dollars(ncontent))
                if st.button("🗑️ Bu kaydı sil", key=f"del_mem_{nid}"):
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
                    st.session_state.pop("active_answer_data", None)
                    st.rerun()
            with s_col2:
                if st.button("🗑️", key=f"del_sess_{sid}", help="Bu sohbet oturumunu sil", use_container_width=True):
                    delete_session(sid)
                    st.session_state.pop("active_answer_data", None)
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
            f"🟢 **Bulut LLM + Canlı Quant Motoru Aktif!** Şu an **{active_prov_label}** anahtarın tanımlı ve devrede."
        )
    else:
        st.info(
            "💡 **Bilgi:** Sistem şu an **Soru Odaklı Kurumsal Quant & Hafıza Motoru** ile hiçbir harici anahtara ihtiyaç duymadan "
            "sorunun tam odağını (düşüş/soğuma seviyesi, ralli devam olasılığı, uzman analist hedefleri, bilanço veya FIFO portföy) "
            "tespit edip canlı verilerle yanıtlamaktadır. İstersen aşağıdan ücretsiz **Google Gemini** veya **Groq** anahtarı da ekleyebilirsin."
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
                "auto": "🔄 Otomatik (Anahtar Varsa Bulut LLM + Canlı Quant, Yoksa Soru Odaklı Quant Motoru)",
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
