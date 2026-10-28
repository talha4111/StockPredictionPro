"""
StockPredictionPro — Uygulama Katmanı Siber Güvenlik Kalkanı & WAF Savunması
Rate Limiting (Kayan Pencere İstek Sınırlayıcı), Anti-Scraping Bot Savunması,
Girdi Sanitizasyonu (Anti-SQLi / Anti-XSS) ve Güvenlik Denetim Günlüğü (Audit Log).
"""
import html
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

# ── Savunma Sabitleri ──
MAX_REQUESTS_PER_MINUTE = 40     # Dakika başına izin verilen azami sayfa yenileme/etkileşim
BURST_LIMIT_3SEC = 10            # 3 saniye içinde insan üstü azami istek sınırı (bot koruması)
RATE_LIMIT_COOLDOWN_SEC = 30     # Limit aşıldığında geçici soğuma cezası (saniye)

# Şüpheli ve kötü niyetli bot / tarayıcı imzaları
KNOWN_BOT_SIGNATURES = [
    "sqlmap", "nikto", "nmap", "gobuster", "dirbuster", "masscan",
    "wpscan", "burpcollaboration", "scrapy", "bytespider", "petalbot",
]

# Zararlı girdi (Injection) regex kalıpları
SUSPICIOUS_QUERY_PATTERNS = [
    r"(?i)(union\s+select|insert\s+into|drop\s+table|;\s*drop|or\s+1\s*=\s*1|information_schema|benchmark\()",  # SQLi
    r"(?i)(<script|javascript:|onload\s*=|onerror\s*=|eval\(|document\.cookie)",                                # XSS
    r"(?i)(\.\./|\.\.\\|/etc/passwd|windows/system32)",                                                          # Path Traversal
]


def init_security_audit_db():
    """Güvenlik olayları denetim tablosunu (audit log) oluşturur."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS security_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            event_type TEXT NOT NULL,
            client_id TEXT,
            ip_address TEXT,
            details TEXT
        )
    """)
    conn.commit()
    conn.close()


def log_security_event(event_type: str, details: str, ip_address: str = "", client_id: str = ""):
    """Güvenlik olayını SQLite denetim günlüğüne kaydeder."""
    try:
        init_security_audit_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO security_audit_log (timestamp, event_type, client_id, ip_address, details)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), event_type, client_id, ip_address, details))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_recent_security_events(limit: int = 15) -> list[dict]:
    """Son gerçekleşen güvenlik olaylarını döndürür."""
    try:
        init_security_audit_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT id, timestamp, event_type, client_id, ip_address, details
            FROM security_audit_log
            ORDER BY id DESC LIMIT ?
        """, (limit,))
        rows = c.fetchall()
        conn.close()
        return [
            {
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "client_id": r[3],
                "ip_address": r[4],
                "details": r[5],
            }
            for r in rows
        ]
    except Exception:
        return []


def get_security_summary() -> dict:
    """Güvenlik kalkanı özet istatistiklerini hesaplar."""
    try:
        init_security_audit_db()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM security_audit_log")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM security_audit_log WHERE event_type LIKE '%BLOCKED%' OR event_type LIKE '%EXCEEDED%'")
        blocks = c.fetchone()[0]
        conn.close()
        return {"total_events": total, "total_blocks": blocks}
    except Exception:
        return {"total_events": 0, "total_blocks": 0}


def get_client_info() -> tuple[str, str, str]:
    """
    Kullanıcının IP adresi, oturum UUID'si ve User-Agent bilgisini döner.
    Streamlit 1.37+ st.context.headers desteği varsa gerçek HTTP başlıklarını okur.
    """
    # Oturum UUID'si
    if "_shield_client_uuid" not in st.session_state:
        st.session_state["_shield_client_uuid"] = str(uuid.uuid4())[:8]
    client_id = st.session_state["_shield_client_uuid"]

    ip_address = "127.0.0.1"
    user_agent = "Unknown"

    try:
        if hasattr(st, "context") and hasattr(st.context, "headers"):
            headers = st.context.headers
            if headers:
                ip_address = (
                    headers.get("x-forwarded-for", "")
                    or headers.get("cf-connecting-ip", "")
                    or headers.get("x-real-ip", "")
                    or "127.0.0.1"
                )
                if "," in ip_address:
                    ip_address = ip_address.split(",")[0].strip()
                user_agent = headers.get("user-agent", "Unknown")
    except Exception:
        pass

    return client_id, ip_address, user_agent


def inject_security_headers():
    """
    Tarayıcı düzeyinde güvenlik için meta etiketleri ve iframe kalkanı enjekte eder.
    (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP)
    """
    st.markdown("""
    <head>
        <meta http-equiv="X-Content-Type-Options" content="nosniff">
        <meta http-equiv="X-Frame-Options" content="SAMEORIGIN">
        <meta name="referrer" content="strict-origin-when-cross-origin">
        <meta http-equiv="Permissions-Policy" content="camera=(), microphone=(), geolocation=()">
    </head>
    """, unsafe_allow_html=True)


def sanitize_and_inspect_query_params(client_id: str, ip_address: str) -> bool:
    """
    URL Query parametrelerinde SQL Injection, XSS ve Path Traversal taraması yapar.
    Zararlı parametre bulunursa parametreleri temizler ve olayı günlüğe kaydeder.
    """
    try:
        query_params = st.query_params
        if not query_params:
            return True

        for key, value in query_params.items():
            val_str = str(value)
            for pattern in SUSPICIOUS_QUERY_PATTERNS:
                if re.search(pattern, val_str) or re.search(pattern, key):
                    log_security_event(
                        event_type="MALICIOUS_INPUT_BLOCKED",
                        details=f"Param: {key}={val_str[:50]} Pattern: {pattern}",
                        ip_address=ip_address,
                        client_id=client_id,
                    )
                    st.query_params.clear()
                    st.toast("⚠️ Şüpheli URL parametresi tespit edildi ve temizlendi.", icon="🛡️")
                    return False
    except Exception:
        pass
    return True


def inspect_bot_user_agent(user_agent: str, client_id: str, ip_address: str) -> bool:
    """
    Kötü niyetli otomatik güvenlik tarayıcısı veya scraping botu olup olmadığını denetler.
    """
    ua_lower = user_agent.lower()
    for sig in KNOWN_BOT_SIGNATURES:
        if sig in ua_lower:
            log_security_event(
                event_type="BOT_BLOCKED",
                details=f"Imza: {sig} | UA: {user_agent[:80]}",
                ip_address=ip_address,
                client_id=client_id,
            )
            return False
    return True


def check_rate_limits(client_id: str, ip_address: str) -> tuple[bool, str]:
    """
    Kayan pencere (Sliding Window) ve patlama (Burst) hız sınırlayıcı.
    Yahoo Finance kotasını korur ve DoS/Scraping amaçlı aşırı yüklenmeleri durdurur.
    """
    now = time.time()

    # Eğer aktif bir ceza süresi varsa
    blocked_until = st.session_state.get("_shield_blocked_until", 0)
    if now < blocked_until:
        kalan = int(blocked_until - now)
        return False, f"⚠️ Aşırı istek algılandı! Sistem koruması nedeniyle {kalan} saniye beklemelisiniz."

    # İstek zaman geçmişi listesini al ve temizle (son 60 saniye dışındakileri at)
    if "_shield_request_log" not in st.session_state:
        st.session_state["_shield_request_log"] = []

    request_log = [t for t in st.session_state["_shield_request_log"] if now - t < 60]

    # Patlama (Burst) Denetimi: Son 3 saniyede 10'dan fazla istek mi?
    burst_count = sum(1 for t in request_log if now - t < 3)
    if burst_count >= BURST_LIMIT_3SEC:
        st.session_state["_shield_blocked_until"] = now + RATE_LIMIT_COOLDOWN_SEC
        log_security_event(
            event_type="BURST_LIMIT_EXCEEDED",
            details=f"3 sn içinde {burst_count} istek (Limit: {BURST_LIMIT_3SEC})",
            ip_address=ip_address,
            client_id=client_id,
        )
        return False, f"⚠️ Çok hızlı işlem yapıldı! Bot koruması gereği {RATE_LIMIT_COOLDOWN_SEC} saniye duraklatıldınız."

    # 1 Dakikalık Toplam İstek Denetimi
    if len(request_log) >= MAX_REQUESTS_PER_MINUTE:
        st.session_state["_shield_blocked_until"] = now + RATE_LIMIT_COOLDOWN_SEC
        log_security_event(
            event_type="RATE_LIMIT_EXCEEDED",
            details=f"60 sn içinde {len(request_log)} istek (Limit: {MAX_REQUESTS_PER_MINUTE})",
            ip_address=ip_address,
            client_id=client_id,
        )
        return False, f"⚠️ Dakikalık istek sınırı ({MAX_REQUESTS_PER_MINUTE}) aşıldı! Lütfen {RATE_LIMIT_COOLDOWN_SEC} saniye bekleyin."

    # İsteği kayda ekle
    request_log.append(now)
    st.session_state["_shield_request_log"] = request_log
    return True, ""


def apply_security_shield() -> bool:
    """
    Ana Güvenlik Kalkanı & WAF Savunma Fonksiyonu.
    Uygulama açılır açılmaz en başta çağrılır. Herhangi bir ihlalde yürütmeyi st.stop() ile keser.
    """
    inject_security_headers()
    client_id, ip_address, user_agent = get_client_info()

    # 1. URL Query Parametre Taraması (Anti-SQLi / Anti-XSS)
    sanitize_and_inspect_query_params(client_id, ip_address)

    # 2. Otomatik Tarayıcı / Scraper Bot Kalkanı
    is_human = inspect_bot_user_agent(user_agent, client_id, ip_address)
    if not is_human:
        st.markdown("""
        <div style="background: linear-gradient(135deg, #2e1622 0%, #1f1220 100%); border: 2px solid #ef5350; border-radius: 12px; padding: 2rem; text-align: center; margin: 3rem auto; max-width: 600px;">
            <div style="font-size: 3rem; margin-bottom: 0.5rem;">⛔</div>
            <h2 style="color: #ef5350; margin: 0;">Erişim Engellendi (403 Forbidden)</h2>
            <p style="color: #ccd6f6; margin-top: 1rem; font-size: 0.95rem;">
                Güvenlik kalkanı tarafından yetkisiz otomatik tarayıcı veya kazıyıcı (scraper) imzası tespit edildi.
            </p>
            <div style="font-size: 0.75rem; color: #8892b0; margin-top: 1rem;">
                Security Shield Layer 3 Active &bull; IP Logged
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.stop()

    # 3. Kayan Pencere İstek Hız Sınırlayıcı (Rate Limiter)
    allowed, rate_msg = check_rate_limits(client_id, ip_address)
    if not allowed:
        st.markdown(f"""
        <div style="background: linear-gradient(135deg, #2a2012 0%, #1f1a10 100%); border: 2px solid #ffa726; border-radius: 12px; padding: 2rem; text-align: center; margin: 3rem auto; max-width: 600px;">
            <div style="font-size: 3rem; margin-bottom: 0.5rem;">⏳</div>
            <h2 style="color: #ffa726; margin: 0;">İstek Sınırı Aşıldı (429 Too Many Requests)</h2>
            <p style="color: #ccd6f6; margin-top: 1rem; font-size: 0.95rem;">
                {html.escape(rate_msg)}
            </p>
            <p style="color: #8892b0; font-size: 0.8rem; margin-top: 0.5rem;">
                Sistem kararlılığı ve borsa veri sağlayıcısı kota koruması için geçici olarak sınırlandırıldınız.
            </p>
        </div>
        """, unsafe_allow_html=True)
        time.sleep(2)
        if st.button("🔄 Tekrar Dene", use_container_width=True):
            st.rerun()
        st.stop()

    return True


def render_security_shield_widget():
    """
    Yöneticiler için aktif güvenlik kalkanı durumunu ve son audit loglarını gösteren arayüz.
    """
    client_id, ip_address, _ = get_client_info()
    summary = get_security_summary()
    request_log = st.session_state.get("_shield_request_log", [])
    now = time.time()
    active_requests = sum(1 for t in request_log if now - t < 60)

    st.markdown("""
    <div style="background: rgba(100, 255, 218, 0.05); border: 1px solid rgba(100, 255, 218, 0.2); border-radius: 10px; padding: 12px; margin-bottom: 12px;">
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div style="font-weight: 700; color: #64ffda; font-size: 0.95rem;">🛡️ Siber Güvenlik Kalkanı</div>
            <div style="font-size: 0.75rem; background: #00c853; color: white; padding: 2px 8px; border-radius: 10px; font-weight: bold;">AKTİF</div>
        </div>
        <div style="color: #8892b0; font-size: 0.8rem; margin-top: 6px;">
            Rate Limiter, Anti-Scraping & Input Sanitization
        </div>
    </div>
    """, unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        st.metric("İstek Yükü (60s)", f"{active_requests} / {MAX_REQUESTS_PER_MINUTE}")
    with c2:
        st.metric("Engellenen İhlal", summary["total_blocks"])

    with st.expander("📜 Güvenlik Denetim Günlüğü (Audit Log)"):
        events = get_recent_security_events(limit=10)
        if not events:
            st.caption("Henüz kayıtlı bir güvenlik ihlali bulunmuyor.")
        else:
            for ev in events:
                t_short = ev["timestamp"].split("T")[1][:8] if "T" in ev["timestamp"] else ev["timestamp"]
                st.markdown(f"**`{t_short}`** | `{ev['event_type']}` — *{ev['details']}*")
