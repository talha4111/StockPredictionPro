"""
StockPredictionPro — Siber Güvenlik & Kimlik Doğrulama Katmanı
NIST standardında Salted PBKDF2-SHA256 parola hashleme,
RFC 6238 TOTP İki Adımlı Doğrulama (Google / Microsoft Authenticator),
Brute-Force (kaba kuvvet) saldırı kalkanı ve çok kullanıcılı yetkilendirme.
"""
import json
import base64
import hashlib
import io
import os
import secrets
import sqlite3
import time
from datetime import datetime
import pyotp
import qrcode
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")
USERS_JSON_PATH = os.path.join(PROJECT_ROOT, "web", "data", "users.json")

# Brute-force koruma limitleri
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_SEC = 300  # 5 dakika


def sync_users_to_json():
    """Kullanıcı hesaplarını Streamlit Cloud konteyner sıfırlamalarına karşı web/data/users.json dosyasına yedekler."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id, username, password_hash, salt, role, totp_secret, is_2fa_enabled, created_at, last_login FROM users")
        rows = c.fetchall()
        conn.close()

        users_list = []
        for r in rows:
            users_list.append({
                "id": r[0],
                "username": r[1],
                "password_hash": r[2],
                "salt": r[3],
                "role": r[4],
                "totp_secret": r[5],
                "is_2fa_enabled": r[6],
                "created_at": r[7],
                "last_login": r[8],
            })

        os.makedirs(os.path.dirname(USERS_JSON_PATH), exist_ok=True)
        with open(USERS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(users_list, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def restore_users_from_json_or_secrets():
    """
    Streamlit Cloud yeniden başladığında SQLite sıfırlanırsa:
    1. web/data/users.json dosyasından kullanıcıları geri yükler.
    2. Veya st.secrets içerisindeki admin ayarlarından hesabı otomatik oluşturur.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        count = c.fetchone()[0]

        if count == 0:
            # 1. users.json dosyasından geri yükle
            if os.path.exists(USERS_JSON_PATH):
                try:
                    with open(USERS_JSON_PATH, "r", encoding="utf-8") as f:
                        users_list = json.load(f)
                    if users_list and isinstance(users_list, list):
                        for u in users_list:
                            c.execute("""
                                INSERT OR REPLACE INTO users 
                                (id, username, password_hash, salt, role, totp_secret, is_2fa_enabled, created_at, last_login)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                u.get("id"),
                                u.get("username"),
                                u.get("password_hash"),
                                u.get("salt"),
                                u.get("role", "user"),
                                u.get("totp_secret"),
                                u.get("is_2fa_enabled", 0),
                                u.get("created_at", datetime.now().isoformat()),
                                u.get("last_login")
                            ))
                        conn.commit()
                except Exception:
                    pass

            # 2. Hala kullanıcı yoksa st.secrets kontrol et
            c.execute("SELECT COUNT(*) FROM users")
            if c.fetchone()[0] == 0:
                try:
                    sec_user = None
                    sec_pwd = None
                    if hasattr(st, "secrets"):
                        if "auth" in st.secrets:
                            sec_user = st.secrets["auth"].get("admin_username")
                            sec_pwd = st.secrets["auth"].get("admin_password")
                        elif "admin_username" in st.secrets:
                            sec_user = st.secrets.get("admin_username")
                            sec_pwd = st.secrets.get("admin_password")

                    if sec_user and sec_pwd:
                        pwd_hash, salt = hash_password(str(sec_pwd))
                        c.execute("""
                            INSERT INTO users (username, password_hash, salt, role, created_at)
                            VALUES (?, ?, ?, 'admin', ?)
                        """, (str(sec_user).strip().lower(), pwd_hash, salt, datetime.now().isoformat()))
                        conn.commit()
                        sync_users_to_json()
                except Exception:
                    pass

        conn.close()
    except Exception:
        pass


def init_user_db():
    """Kullanıcılar tablosunu oluşturur ve 2FA sütunlarını güvenle ekler (migration)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user',
            totp_secret TEXT,
            is_2fa_enabled INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            last_login TIMESTAMP
        )
    """)
    # Var olan tablolarda sütun eksikse ekle
    cols = [col[1] for col in c.execute("PRAGMA table_info(users)").fetchall()]
    if "totp_secret" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN totp_secret TEXT")
    if "is_2fa_enabled" not in cols:
        c.execute("ALTER TABLE users ADD COLUMN is_2fa_enabled INTEGER NOT NULL DEFAULT 0")
    conn.commit()
    conn.close()

    # Bulut konteyner sıfırlanmışsa users.json veya st.secrets'tan otomatik kurtar
    restore_users_from_json_or_secrets()


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


# ════════════════════════════════════════════════════════════════
# 🔑 İKİ ADIMLI DOĞRULAMA (TOTP / GOOGLE AUTHENTICATOR) FONKSİYONLARI
# ════════════════════════════════════════════════════════════════

def generate_totp_secret() -> str:
    """RFC 6238 uyumlu rastgele Base32 TOTP gizli anahtarı üretir."""
    return pyotp.random_base32()


def get_totp_uri(username: str, secret: str) -> str:
    """Google Authenticator / Microsoft Authenticator için standart otpauth URI üretir."""
    return pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name="StockPredictionPro"
    )


def generate_qr_code_bytes(totp_uri: str) -> bytes:
    """OTPAuth URI için PNG formatında QR kod görsel verisi üretir."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0a192f", back_color="#ffffff")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def verify_totp_code(secret: str, code: str) -> bool:
    """
    Kullanıcının girdiği 6 haneli TOTP kodunu doğrular.
    valid_window=1 ile saat kaymalarına karşı +/- 30 saniye tolerans tanır.
    """
    if not secret or not code:
        return False
    clean_code = str(code).strip().replace(" ", "").replace("-", "")
    totp = pyotp.TOTP(secret)
    return bool(totp.verify(clean_code, valid_window=1))


def enable_user_2fa(user_id: int, secret: str) -> tuple[bool, str]:
    """Kullanıcının 2FA durumunu veritabanında aktif eder."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET totp_secret = ?, is_2fa_enabled = 1 WHERE id = ?", (secret, user_id))
        conn.commit()
        conn.close()
        sync_users_to_json()
        return True, "İki Adımlı Doğrulama (2FA) başarıyla aktif edildi."
    except Exception as e:
        return False, f"Veritabanı hatası: {e}"


def disable_user_2fa(user_id: int) -> tuple[bool, str]:
    """Kullanıcının 2FA durumunu pasife alır."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE users SET is_2fa_enabled = 0 WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        sync_users_to_json()
        return True, "İki Adımlı Doğrulama (2FA) devre dışı bırakıldı."
    except Exception as e:
        return False, f"Veritabanı hatası: {e}"


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
        sync_users_to_json()
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
    c.execute("""
        SELECT id, username, password_hash, salt, role, totp_secret, is_2fa_enabled 
        FROM users WHERE username = ?
    """, (username,))
    row = c.fetchone()

    if not row:
        conn.close()
        st.session_state["auth_failed_attempts"] = failed_attempts + 1
        if st.session_state["auth_failed_attempts"] >= MAX_FAILED_ATTEMPTS:
            st.session_state["auth_lockout_until"] = now + LOCKOUT_DURATION_SEC
        return False, None, "Hatalı kullanıcı adı veya parola."

    user_id, u_name, stored_hash, salt_hex, role, totp_secret, is_2fa_enabled = row

    if verify_password(password, stored_hash, salt_hex):
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        user_info = {
            "id": user_id,
            "username": u_name,
            "role": role,
            "is_2fa_enabled": bool(is_2fa_enabled),
            "totp_secret": totp_secret or "",
        }
        return True, user_info, "Giriş başarılı."
    else:
        conn.close()
        st.session_state["auth_failed_attempts"] = failed_attempts + 1
        if st.session_state["auth_failed_attempts"] >= MAX_FAILED_ATTEMPTS:
            st.session_state["auth_lockout_until"] = now + LOCKOUT_DURATION_SEC
            return False, None, "⚠️ Çok fazla hatalı deneme! Güvenlik nedeniyle hesap 5 dakika kilitlendi."
        kalan = MAX_FAILED_ATTEMPTS - st.session_state["auth_failed_attempts"]
        return False, None, f"Hatalı parola! Kalan deneme hakkı: {kalan}"


def render_login_gate():
    """
    Kullanıcı oturumu açılmamışsa kurumsal düzeyde 2FA destekli
    güvenli giriş kapısını çizer. Oturum açılmadan diğer sayfalar çalıştırılmaz.
    """
    if st.session_state.get("authenticated", False):
        return True  # Zaten oturum açık

    user_count = get_user_count()

    # Ortalanmış Giriş Kartı
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
                🔒 PBKDF2-SHA256 & RFC 6238 TOTP (2FA) Korumalı
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
                            st.success("🎉 Yönetici hesabı oluşturuldu! Lütfen giriş yapın.")
                            st.rerun()
                        else:
                            st.error(msg)
            st.stop()

        # ── 2FA ONAY EKRANI (İLK AŞAMA GEÇİLDİKTEN SONRA) ──
        if st.session_state.get("2fa_pending"):
            pending = st.session_state["2fa_pending"]
            user_info = pending["user"]
            totp_secret = pending["secret"]

            st.markdown(f"""
            <div style="background: rgba(100, 255, 218, 0.05); border: 1px solid rgba(100, 255, 218, 0.25); border-radius: 12px; padding: 1.2rem; margin-bottom: 1.2rem; text-align: center;">
                <div style="font-size: 2rem; margin-bottom: 0.5rem;">📲</div>
                <div style="font-weight: 700; color: #ffffff; font-size: 1.05rem;">İki Adımlı Doğrulama (2FA)</div>
                <div style="color: #8892b0; font-size: 0.85rem; margin-top: 4px;">
                    <b>{user_info['username'].title()}</b> hesabı Google Authenticator ile korunmaktadır.
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.form("totp_verification_form"):
                totp_input = st.text_input(
                    "6 Haneli Doğrulama Kodu",
                    max_chars=6,
                    placeholder="Örn: 123456",
                    help="Google Authenticator veya Microsoft Authenticator uygulamanızdaki 6 haneli kodu girin."
                )
                c_sub, c_can = st.columns([1, 1])
                with c_sub:
                    verify_btn = st.form_submit_button("✅ Kodu Doğrula", type="primary", use_container_width=True)
                with c_can:
                    cancel_btn = st.form_submit_button("⬅️ İptal / Geri Dön", use_container_width=True)

                if cancel_btn:
                    del st.session_state["2fa_pending"]
                    st.rerun()

                if verify_btn:
                    if verify_totp_code(totp_secret, totp_input):
                        st.session_state["authenticated"] = True
                        st.session_state["user"] = user_info
                        st.session_state["auth_failed_attempts"] = 0
                        st.session_state["auth_lockout_until"] = 0
                        del st.session_state["2fa_pending"]
                        st.success("✅ 2FA Doğrulandı! Terminale giriş yapılıyor...")
                        st.rerun()
                    else:
                        st.session_state["auth_failed_attempts"] = st.session_state.get("auth_failed_attempts", 0) + 1
                        st.error("❌ Hatalı veya süresi dolmuş 2FA kodu! Lütfen tekrar deneyin.")

            st.caption("ℹ️ *Kod her 30 saniyede bir otomatik yenilenir.*")
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
                        # 2FA Aktif mi kontrol et
                        if user_dict.get("is_2fa_enabled") and user_dict.get("totp_secret"):
                            st.session_state["2fa_pending"] = {
                                "user": user_dict,
                                "secret": user_dict["totp_secret"],
                            }
                            st.rerun()
                        else:
                            # 2FA yoksa doğrudan oturum aç
                            st.session_state["authenticated"] = True
                            st.session_state["user"] = user_dict
                            st.session_state["auth_failed_attempts"] = 0
                            st.session_state["auth_lockout_until"] = 0
                            st.success("Giriş başarılı! Yönlendiriliyorsunuz...")
                            st.rerun()
                    else:
                        st.error(msg)

        st.caption("🔒 *Bu terminal yetkisiz erişimlere ve kaba kuvvet (brute-force) saldırılarına karşı korunmaktadır.*")

    st.stop()  # Giriş yapılana kadar sayfanın devamını ASLA çalıştırma!


def render_sidebar_user_profile():
    """Giriş yapmış kullanıcının profil rozetini, 2FA ayarlarını ve Güvenli Çıkış butonunu çizer."""
    if not st.session_state.get("authenticated", False):
        return

    user = st.session_state.get("user", {})
    user_id = user.get("id")
    username = user.get("username", "Kullanıcı")
    role = user.get("role", "user")
    is_2fa_enabled = user.get("is_2fa_enabled", False)
    role_badge = "👑 Yönetici" if role == "admin" else "👤 Üye"
    fa_badge = "🟢 2FA Aktif" if is_2fa_enabled else "⚪ 2FA Kapalı"

    st.sidebar.markdown(f"""
    <div style="background: rgba(100, 255, 218, 0.08); border: 1px solid rgba(100, 255, 218, 0.2); border-radius: 10px; padding: 10px; margin-bottom: 10px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <div style="font-weight: 700; color: #ffffff; font-size: 0.95rem;">{username.title()}</div>
            <div style="font-size: 0.72rem; color: #64ffda; margin-top: 2px;">{role_badge} &nbsp;|&nbsp; {fa_badge}</div>
        </div>
        <div style="font-size: 1.2rem;">🛡️</div>
    </div>
    """, unsafe_allow_html=True)

    # ── 2FA GÜVENLİK AYARLARI GENİŞLETİCİ ──
    with st.sidebar.expander("🔐 2FA Güvenlik Ayarları"):
        if is_2fa_enabled:
            st.success("✅ Google Authenticator 2FA aktif.")
            st.caption("Hesabınız her girişte 6 haneli dinamik kod ile doğrulanır.")
            if st.button("❌ 2FA'yı Devre Dışı Bırak", key="btn_disable_2fa", use_container_width=True):
                ok, msg = disable_user_2fa(user_id)
                if ok:
                    st.session_state["user"]["is_2fa_enabled"] = False
                    st.warning("2FA devre dışı bırakıldı.")
                    st.rerun()
                else:
                    st.error(msg)
        else:
            st.info("📲 İki Adımlı Doğrulama (2FA) kurarak hesabınızı banka düzeyinde koruyun.")
            
            # Kurulum durumu
            if "setup_totp_secret" not in st.session_state:
                if st.button("🚀 Google Authenticator Kur", key="btn_start_2fa_setup", type="primary", use_container_width=True):
                    st.session_state["setup_totp_secret"] = generate_totp_secret()
                    st.rerun()
            else:
                setup_secret = st.session_state["setup_totp_secret"]
                totp_uri = get_totp_uri(username, setup_secret)
                qr_bytes = generate_qr_code_bytes(totp_uri)

                st.write("**1. QR Kodu Tarayın:**")
                st.image(qr_bytes, caption="Google Authenticator ile Okutun", use_container_width=True)
                st.caption(f"Manuel Kurulum Anahtarı: `{setup_secret}`")

                st.write("**2. 6 Haneli Kodu Doğrulayın:**")
                verify_code_input = st.text_input("Uygulamadaki Kodu Girin", max_chars=6, key="input_verify_setup_2fa")
                c_ok, c_cancel = st.columns([1, 1])
                with c_ok:
                    if st.button("Aktif Et", key="btn_confirm_enable_2fa", type="primary", use_container_width=True):
                        if verify_totp_code(setup_secret, verify_code_input):
                            ok, msg = enable_user_2fa(user_id, setup_secret)
                            if ok:
                                st.session_state["user"]["is_2fa_enabled"] = True
                                st.session_state["user"]["totp_secret"] = setup_secret
                                del st.session_state["setup_totp_secret"]
                                st.success("🎉 2FA Başarıyla Aktif Edildi!")
                                st.rerun()
                            else:
                                st.error(msg)
                        else:
                            st.error("Hatalı kod! Lütfen telefonunuzdaki güncel kodu girin.")
                with c_cancel:
                    if st.button("İptal", key="btn_cancel_setup_2fa", use_container_width=True):
                        del st.session_state["setup_totp_secret"]
                        st.rerun()

    # Çıkış Butonu
    if st.sidebar.button("🚪 Güvenli Çıkış Yap", use_container_width=True):
        st.session_state.clear()
        st.rerun()
