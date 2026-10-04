"""
StockPredictionPro — Siber Güvenlik & Kimlik Doğrulama Katmanı
NIST standardında Salted PBKDF2-SHA256 parola hashleme,
Brute-Force (kaba kuvvet) saldırı kalkanı ve çok kullanıcılı yetkilendirme.
"""
import hashlib
import os
import secrets
import sqlite3
import time
from datetime import datetime
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

# Brute-force koruma limitleri
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SEC = 300  # 5 dakika


def init_user_db():
    """Kullanıcılar tablosunu oluşturur (eğer yoksa)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            created_at TIMESTAMP NOT NULL,
            last_login TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def hash_password(password: str, salt: bytes = None) -> tuple[str, str]:
    """NIST SP 800-132 uyumlu PBKDF2-HMAC-SHA256 (100.000 iterasyon) ile hashler."""
    if salt is None:
        salt = secrets.token_bytes(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return pwd_hash.hex(), salt.hex()


def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
    """Parolayı tuzlanmış hash ile doğrular (zamanlama saldırılarına karşı güvenli karşılaştırma)."""
    salt = bytes.fromhex(salt_hex)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return secrets.compare_digest(pwd_hash.hex(), stored_hash)


def get_user_count() -> int:
    """Sistemde kayıtlı kullanıcı sayısını döndürür."""
    init_user_db()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count


def create_user(username: str, password: str, role: str = "user") -> tuple[bool, str]:
    """Yeni bir kullanıcı hesabı oluşturur."""
    init_user_db()
    username = username.strip().lower()
    if len(username) < 3:
        return False, "Kullanıcı adı en az 3 karakter olmalıdır."
    if len(password) < 6:
        return False, "Parola en az 6 karakter olmalıdır."

    pwd_hash, salt = hash_password(password)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT INTO users (username, password_hash, salt, role, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (username, pwd_hash, salt, role, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True, "Kullanıcı başarıyla oluşturuldu."
    except sqlite3.IntegrityError:
        return False, "Bu kullanıcı adı zaten mevcut."
    except Exception as e:
        return False, f"Veritabanı hatası: {e}"


def authenticate_user(username: str, password: str) -> tuple[bool, dict | None, str]:
    """
    Kullanıcı kimliğini doğrular.
    Döndürür: (basarili_mi, user_dict, mesaj)
    """
    init_user_db()
    username = username.strip().lower()

    # Kaba kuvvet (Brute Force) kontrolü
    now = time.time()
    failed_attempts = st.session_state.get("auth_failed_attempts", 0)
    lockout_until = st.session_state.get("auth_lockout_until", 0)

    if now < lockout_until:
        remaining = int(lockout_until - now)
        return False, None, f"⚠️ Çok fazla hatalı deneme! Lütfen {remaining} saniye bekleyin."

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, username, password_hash, salt, role FROM users WHERE username = ?", (username,))
    row = c.fetchone()

    if not row:
        conn.close()
        st.session_state["auth_failed_attempts"] = failed_attempts + 1
        if st.session_state["auth_failed_attempts"] >= MAX_FAILED_ATTEMPTS:
            st.session_state["auth_lockout_until"] = now + LOCKOUT_DURATION_SEC
        return False, None, "Hatalı kullanıcı adı veya parola."

    user_id, u_name, stored_hash, salt_hex, role = row

    if verify_password(password, stored_hash, salt_hex):
        # Başarılı giriş: Hatalı denemeleri sıfırla, son giriş tarihini güncelle
        st.session_state["auth_failed_attempts"] = 0
        st.session_state["auth_lockout_until"] = 0
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        user_info = {
            "id": user_id,
            "username": u_name,
            "role": role,
        }
        return True, user_info, "Giriş başarılı."
    else:
        conn.close()
        st.session_state["auth_failed_attempts"] = failed_attempts + 1
        if st.session_state["auth_failed_attempts"] >= MAX_FAILED_ATTEMPTS:
            st.session_state["auth_lockout_until"] = now + LOCKOUT_DURATION_SEC
            return False, None, "⚠️ Çok fazla hatalı deneme! Güvenlik nedeniyle hesap 5 dakika kilitlendi."
        kalan = MAX_FAILED_ATTEMPTS - st.session_state["auth_failed_attempts"]
        return False, None, f"Hatalı parola! Kalan hak: {kalan}"


def render_login_gate():
    """
    Kullanıcı oturumu açılmamışsa Bloomberg/Fintech tarzı
    güvenli giriş kapısını çizer. Oturum açılmadan diğer sayfalar kilitlidir.
    """
    if st.session_state.get("authenticated", False):
        return True  # Zaten oturum açık

    user_count = get_user_count()

    # Ortalanmış Giriş Kutusu
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("""
        <div style="text-align: center; margin-top: 2rem; margin-bottom: 1.5rem;">
            <div style="font-size: 2.8rem; margin-bottom: 0.2rem;">🏦</div>
            <h2 style="font-size: 1.6rem; font-weight: 800; background: linear-gradient(90deg, #64ffda 0%, #00b0ff 100%); -webkit-background-clip: text; -webkit-text-fill-color: transparent; margin: 0;">
                StockPredictionPro
            </h2>
            <p style="color: #8892b0; font-size: 0.85rem; margin-top: 4px;">
                Institutional Factor Engine & Secure Terminal
            </p>
            <div style="display: inline-block; background: rgba(100, 255, 218, 0.1); border: 1px solid rgba(100, 255, 218, 0.3); border-radius: 20px; padding: 4px 14px; font-size: 0.75rem; color: #64ffda; font-weight: 600;">
                🔒 256-Bit Salted SHA Güvenlik Kalkanı
            </div>
        </div>
        """, unsafe_allow_html=True)

        # ── EĞER HİÇ KULLANICI YOKSA: İLK KURULUM EKRANI ──
        if user_count == 0:
            st.info("👋 **İlk Kurulum:** Sistemin sahibi olarak yönetici (Admin) hesabınızı oluşturun.")
            with st.form("admin_setup_form"):
                admin_user = st.text_input("Yönetici Kullanıcı Adı (Örn: talha)").strip()
                admin_pwd = st.text_input("Güçlü Parola", type="password")
                admin_pwd_conf = st.text_input("Parolayı Tekrar Girin", type="password")
                setup_btn = st.form_submit_button("🛡️ Yönetici Hesabını Oluştur", type="primary", use_container_width=True)

                if setup_btn:
                    if admin_pwd != admin_pwd_conf:
                        st.error("Girdiğiniz parolalar birbiriyle eşleşmiyor!")
                    else:
                        ok, msg = create_user(admin_user, admin_pwd, role="admin")
                        if ok:
                            st.success(f"🎉 Yönetici hesabı oluşturuldu! Lütfen giriş yapın.")
                            st.rerun()
                        else:
                            st.error(msg)
            st.stop()

        # ── STANDART GİRİŞ EKRANI ──
        with st.form("login_form"):
            username_input = st.text_input("Kullanıcı Adı", placeholder="Kullanıcı adınızı girin").strip()
            password_input = st.text_input("Parola", type="password", placeholder="Parolanızı girin")
            login_btn = st.form_submit_button("🚀 Güvenli Giriş Yap", type="primary", use_container_width=True)

            if login_btn:
                if not username_input or not password_input:
                    st.warning("Lütfen kullanıcı adı ve parolanızı eksiksiz girin.")
                else:
                    success, user_dict, msg = authenticate_user(username_input, password_input)
                    if success:
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = user_dict
                        st.success("Giriş başarılı! Yönlendiriliyorsunuz...")
                        st.rerun()
                    else:
                        st.error(msg)

        st.caption("🔒 *Bu terminal yetkisiz erişimlere ve kaba kuvvet (brute-force) saldırılarına karşı korunmaktadır.*")

    st.stop()  # Giriş yapılana kadar sayfanın devamını ASLA çalıştırma!


def render_sidebar_user_profile():
    """Giriş yapmış kullanıcının profil rozetini ve Güvenli Çıkış butonunu çizer."""
    if not st.session_state.get("authenticated", False):
        return

    user = st.session_state.get("user", {})
    username = user.get("username", "Kullanıcı")
    role = user.get("role", "user")
    role_badge = "👑 Yönetici" if role == "admin" else "👤 Üye"

    st.sidebar.markdown(f"""
    <div style="background: rgba(100, 255, 218, 0.08); border: 1px solid rgba(100, 255, 218, 0.2); border-radius: 10px; padding: 10px; margin-bottom: 12px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <div style="font-weight: 700; color: #ffffff; font-size: 0.95rem;">{username.title()}</div>
            <div style="font-size: 0.72rem; color: #64ffda;">{role_badge}</div>
        </div>
        <div style="font-size: 1.2rem;">🛡️</div>
    </div>
    """, unsafe_allow_html=True)

    if st.sidebar.button("🚪 Güvenli Çıkış Yap", use_container_width=True):
        st.session_state.clear()
        st.rerun()
