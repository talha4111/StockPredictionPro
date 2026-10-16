"""
StockPredictionPro — Alım Noktası & Dönüş Avcısı (Dip Hunter Engine)
Hisselerin ucuzluk (alım) bölgelerini hesaplar, 15 dakikalık ve günlük mumlarla
"düşen bıçak mı yoksa dipten dönüş mü?" sorusunu analiz eder ve teknik terimlerden
arındırılmış, sade ve anlaşılır Türkçe ile karar/Telegram bildirimi üretir.
"""
import json
import os
import time
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "web", "data")
CONFIG_PATH = os.path.join(DATA_DIR, "dip_hunter_config.json")
SECRET_PATH = os.path.join(DATA_DIR, "telegram_secret.json")
QUANTBOT_AYAR_PATH = os.path.join(PROJECT_ROOT, "QuantBot", "ayar.json")
STATE_PATH = os.path.join(DATA_DIR, "dip_alert_state.json")
WATCHLIST_PATH = os.path.join(DATA_DIR, "watchlist.json")

DEFAULT_SYMBOLS = ["MU", "COHR", "MRVL", "RKLB", "VST", "AVGO"]


def load_dip_config() -> dict:
    """Takip edilen hisseleri ve Telegram ayarlarını güvenli şekilde yükler."""
    os.makedirs(DATA_DIR, exist_ok=True)
    default_cfg = {
        "symbols": DEFAULT_SYMBOLS.copy(),
        "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""),
        "notifications_enabled": True,
    }
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if "symbols" in saved:
                default_cfg["symbols"] = saved["symbols"]
            if "notifications_enabled" in saved:
                default_cfg["notifications_enabled"] = saved["notifications_enabled"]
        except Exception:
            pass

    # 1. Yerel gizli dosyadan (git-ignored) Telegram bilgisi varsa oku
    if os.path.exists(SECRET_PATH):
        try:
            with open(SECRET_PATH, "r", encoding="utf-8") as f:
                sec = json.load(f)
            default_cfg["telegram_bot_token"] = sec.get("telegram_bot_token") or default_cfg["telegram_bot_token"]
            default_cfg["telegram_chat_id"] = sec.get("telegram_chat_id") or default_cfg["telegram_chat_id"]
        except Exception:
            pass

    # 2. QuantBot/ayar.json içinde mevcut Telegram ayarı varsa otomatik bağla
    if (not default_cfg["telegram_bot_token"] or not default_cfg["telegram_chat_id"]) and os.path.exists(QUANTBOT_AYAR_PATH):
        try:
            with open(QUANTBOT_AYAR_PATH, "r", encoding="utf-8") as f:
                qb = json.load(f)
            tg = qb.get("telegram", {})
            if tg.get("bot_token") and tg.get("chat_id"):
                default_cfg["telegram_bot_token"] = default_cfg["telegram_bot_token"] or tg["bot_token"]
                default_cfg["telegram_chat_id"] = default_cfg["telegram_chat_id"] or str(tg["chat_id"])
        except Exception:
            pass

    # 3. Streamlit secrets içinden Telegram bilgisi varsa yedek olarak oku
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if not default_cfg["telegram_bot_token"]:
                default_cfg["telegram_bot_token"] = (
                    st.secrets.get("TELEGRAM_BOT_TOKEN", "")
                    or st.secrets.get("telegram", {}).get("bot_token", "")
                )
            if not default_cfg["telegram_chat_id"]:
                default_cfg["telegram_chat_id"] = (
                    st.secrets.get("TELEGRAM_CHAT_ID", "")
                    or st.secrets.get("telegram", {}).get("chat_id", "")
                )
    except Exception:
        pass

    return default_cfg


def save_dip_config(cfg: dict):
    """Takip listesini herkese açık dosyaya, Telegram anahtarlarını ise gizli dosyaya kaydeder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        public_cfg = {
            "symbols": cfg.get("symbols", DEFAULT_SYMBOLS),
            "notifications_enabled": cfg.get("notifications_enabled", True),
        }
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(public_cfg, f, indent=2, ensure_ascii=False)

        if cfg.get("telegram_bot_token") or cfg.get("telegram_chat_id"):
            secret_cfg = {
                "telegram_bot_token": cfg.get("telegram_bot_token", ""),
                "telegram_chat_id": cfg.get("telegram_chat_id", ""),
            }
            with open(SECRET_PATH, "w", encoding="utf-8") as f:
                json.dump(secret_cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def load_alert_state() -> dict:
    """Son gönderilen bildirim durumlarını yükler (aynı mesajı tekrar tekrar atmamak için)."""
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_alert_state(state: dict):
    """Son bildirim durumlarını kaydeder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < 2:
        return 0.0
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    val = tr.rolling(min(period, len(df))).mean().iloc[-1]
    return float(val) if not np.isnan(val) else float(high_low.mean())


def analyze_stock_dip(symbol: str, vix_value: float = 18.0) -> dict | None:
    """
    Bir hisse için hem günlük (6 aylık) hem de gün içi (15 dakikalık) verileri tarar.
    Alım bölgelerini, kaçış (stop) noktasını, kâr hedeflerini ve dönüş onaylarını
    tamamen sade ve anlaşılır bir dille döndürür.
    """
    symbol = symbol.strip().upper()
    try:
        tk = yf.Ticker(symbol)
        df_daily = tk.history(period="6mo", interval="1d")
        if df_daily is None or len(df_daily) < 25:
            return None

        # Gün içi 15 dakikalık mumlar (son 5 işlem günü)
        try:
            df_intra = tk.history(period="5d", interval="15m")
        except Exception:
            df_intra = pd.DataFrame()

        close_s = df_daily["Close"]
        high_s = df_daily["High"]
        low_s = df_daily["Low"]
        vol_s = df_daily["Volume"]

        current_price = float(close_s.iloc[-1])
        if df_intra is not None and not df_intra.empty:
            current_price = float(df_intra["Close"].iloc[-1])

        prev_close = float(close_s.iloc[-2]) if len(close_s) >= 2 else current_price
        daily_change_pct = ((current_price / prev_close) - 1.0) * 100.0

        # Temel teknik referanslar (arka planda hesaplanır, kullanıcıya sade anlatılır)
        sma20 = float(close_s.rolling(20).mean().iloc[-1])
        sma50 = float(close_s.rolling(50).mean().iloc[-1]) if len(close_s) >= 50 else sma20
        sma200 = float(close_s.rolling(120).mean().iloc[-1]) if len(close_s) >= 120 else sma50 * 0.90
        atr = _calc_atr(df_daily, 14)

        rsi_daily_s = _calc_rsi(close_s, 14)
        rsi_daily = float(rsi_daily_s.iloc[-1]) if not np.isnan(rsi_daily_s.iloc[-1]) else 50.0

        # Son 30 günün zirvesi ve son 20 günün dibi
        recent_peak = float(high_s.tail(35).max())
        recent_swing_low = float(low_s.tail(20).min())
        drop_from_peak_pct = ((current_price / recent_peak) - 1.0) * 100.0

        # ── AKILLI ALIM BÖLGELERİ (KADEME 1, KADEME 2, İPTAL SINIRI, KÂR HEDEFİ) ──
        # Fibonacci geri çekilme seviyeleri + hareketli ortalamalar + son dip harmanı
        swing_range = max(recent_peak - recent_swing_low, atr * 2.5)
        fib_50 = recent_peak - swing_range * 0.50
        fib_618 = recent_peak - swing_range * 0.618

        # Hissenin mevcut konumuna göre dinamik destek tespiti
        candidates = sorted([sma50, fib_50, fib_618, recent_swing_low * 1.02])
        # Mevcut fiyata yakın veya altındaki en mantıklı ilk güçlü destek merkezi
        below_or_near = [c for c in candidates if c <= current_price * 1.03]
        if below_or_near:
            zone1_center = max(below_or_near)
        else:
            zone1_center = recent_swing_low * 1.015

        # Eğer zone1_center zirveye çok yakınsa (hisse hiç düşmemişse), en az 1.2 ATR aşağı çek
        if zone1_center > recent_peak - atr * 1.1:
            zone1_center = recent_peak - atr * 1.5

        band_half = max(atr * 0.35, current_price * 0.012)
        zone1_low = round(zone1_center - band_half, 2)
        zone1_high = round(zone1_center + band_half, 2)

        # Kademe 2 (Daha derin düşüş / 2. kurşun yeri)
        zone2_center = min(recent_swing_low, zone1_low - atr * 0.85)
        zone2_low = round(zone2_center - band_half * 0.9, 2)
        zone2_high = round(zone2_center + band_half * 0.9, 2)

        # Kaçış / İptal Sınırı (Bu kırılırsa düşen bıçaktır, alım yapılmaz)
        stop_level = round(min(zone2_low - atr * 0.6, recent_swing_low * 0.975), 2)

        # Kâr Alma Hedefleri
        target1 = round(max(current_price + atr * 1.8, zone1_high + atr * 2.0, sma20), 2)
        target2 = round(max(target1 + atr * 1.5, recent_peak * 0.96), 2)
        upside_pct = round(((target1 / current_price) - 1.0) * 100.0, 1)

        # ── GÜN İÇİ (15 DK) VE GÜNLÜK DÖNÜŞ ONAYLARI ──
        # 1. Fiyat Ucuzluk Bölgesinde mi?
        in_buy_zone = (stop_level <= current_price <= zone1_high * 1.01)
        near_buy_zone = (zone1_high * 1.01 < current_price <= zone1_high * 1.045)
        broken_support = current_price < stop_level

        # 2. Gün İçi Panik Satışı Durdu mu ve Dönüş Başladı mı? (15m + 1d analizi)
        intraday_bounce = False
        rsi_intra = rsi_daily
        if df_intra is not None and len(df_intra) >= 15:
            intra_close = df_intra["Close"]
            rsi_intra_s = _calc_rsi(intra_close, 14)
            if not np.isnan(rsi_intra_s.iloc[-1]):
                rsi_intra = float(rsi_intra_s.iloc[-1])
            # Son 3 mumda yükseliş veya aşırı satımdan yukarı kıvrılma
            last_3_closes = intra_close.tail(4).values
            intra_day_low = float(df_intra["Low"].tail(16).min())
            bounce_from_intra_low = (current_price - intra_day_low) / max(intra_day_low, 1e-6)
            if (last_3_closes[-1] > last_3_closes[-2] and rsi_intra >= rsi_intra_s.iloc[-3]) or bounce_from_intra_low >= 0.015:
                intraday_bounce = True
        else:
            # Günlük mumda çekiç / alttan tepki kontrolü
            day_low = float(low_s.iloc[-1])
            day_high = float(high_s.iloc[-1])
            day_range = max(day_high - day_low, 1e-6)
            close_pos = (current_price - day_low) / day_range
            if close_pos >= 0.55 or daily_change_pct > 0.5:
                intraday_bounce = True

        # 3. Büyük Alıcılar / Hacim Desteği Var mı?
        avg_vol_20 = float(vol_s.tail(20).mean())
        last_vol = float(vol_s.iloc[-1])
        day_low_today = float(low_s.iloc[-1])
        day_high_today = float(high_s.iloc[-1])
        lower_wick_ratio = (current_price - day_low_today) / max(day_high_today - day_low_today, 1e-6)
        strong_buyers = (last_vol >= avg_vol_20 * 0.95 and (lower_wick_ratio >= 0.45 or intraday_bounce)) or (rsi_daily < 35 and intraday_bounce)

        # 4. Genel Borsa Havası Güvenli mi? (VIX < 32)
        market_calm = vix_value < 32.0

        # Kontrol Listesi (Sade Türkçe)
        checklist = [
            {
                "kriter": "Fiyat hedeflediğimiz ucuzluk (alım) bölgesine indi",
                "ok": bool(in_buy_zone),
                "detay": f"Şu an ${current_price:.2f} (Hedef: ${zone1_low:.2f} – ${zone1_high:.2f})"
            },
            {
                "kriter": "Panik satışı durdu, grafikte yukarı tepki başladı",
                "ok": bool(intraday_bounce),
                "detay": "Son mumlarda alıcılar fiyatı yukarı itiyor" if intraday_bounce else "Hâlâ aşağı yönlü baskı var, düşüş durmadı"
            },
            {
                "kriter": "Diplerden güçlü alıcılar (hacim desteği) geldi",
                "ok": bool(strong_buyers),
                "detay": "Kurumsal alım tepkisi görülüyor" if strong_buyers else "Henüz güçlü bir alıcı dalgası görülmedi"
            },
            {
                "kriter": "Genel piyasa havası sakin (Büyük borsa paniği yok)",
                "ok": bool(market_calm),
                "detay": f"Korku endeksi normal seviyede ({vix_value:.1f})" if market_calm else f"Piyasada genel korku yüksek ({vix_value:.1f})"
            },
        ]
        passed_count = sum(1 for item in checklist if item["ok"])

        # ── 4 ANA DURUM KARARI VE SADE TÜRKÇE REHBER ──
        if broken_support:
            state_code = "TEHLIKE"
            state_badge = "🔴 TEHLİKE — DESTEK KIRILDI (ALMA!)"
            state_color = "#ef5350"
            headline = f"{symbol} güvenlik sınırımız olan ${stop_level:.2f} seviyesinin altına sarktı!"
            action_advice = (
                f"⛔ **Kesinlikle acele edip alım yapma!** Hisse şu an 'düşen bıçak' durumunda. "
                f"Satışların nerede duracağını görmeden ortalama düşürmeye çalışmak tehlikelidir. "
                f"Yeniden güvenli olması için fiyatın en az **${zone2_high:.2f}** üzerine çıkıp tutunmasını beklemelisin."
            )
        elif in_buy_zone and intraday_bounce and (strong_buyers or rsi_daily < 38 or rsi_intra < 40):
            state_code = "ALIM_FIRSATI"
            state_badge = "🟢 ŞİMDİ ALIM FIRSATI (DÖNÜŞ BAŞLADI)"
            state_color = "#00c853"
            which_tier = "1. Parça (Kademe 1)" if current_price >= zone2_high else "2. Parça (Derin İskonto)"
            headline = f"{symbol} alım bölgesine indi ve dipten alıcılar devreye girdi!"
            action_advice = (
                f"✅ **{which_tier} alımı için şartlar olgunlaştı!** Hisse son zirvesinden %{abs(drop_from_peak_pct):.1f} "
                f"ucuzladı ve **${current_price:.2f}** seviyesinde düşüş hızı kesilip yukarı dönüş başladı. "
                f"Tüm paranla tek seferde değil, planlanan ilk parçayla giriş yapabilirsin. "
                f"Olası terslikte kaçış (iptal) sınırımız **${stop_level:.2f}**, ilk kâr alma hedefimiz ise **${target1:.2f}** (+%{upside_pct})."
            )
        elif in_buy_zone or near_buy_zone:
            state_code = "PUSUDA_IZLE"
            state_badge = "🟡 UCUZLUK BÖLGESİNDE — HENÜZ ALMA, İZLE"
            state_color = "#ffa726"
            headline = f"{symbol} ucuzluk bölgesine girdi (${current_price:.2f}) ama düşüş henüz tam durmadı."
            action_advice = (
                f"⏳ **Elimiz tetikte ama henüz almıyoruz!** Fiyat istediğimiz **${zone1_low:.2f} – ${zone1_high:.2f}** "
                f"bölgesine geldi/yaklaştı fakat satış baskısı henüz bitmedi (daha da düşme ihtimali var). "
                f"Gün içinde satışların durup ilk yeşil dönüş mumunun yanmasını bekliyoruz. Dönüş başladığı an bildirim gelecek!"
            )
        else:
            state_code = "BEKLEMEDE"
            state_badge = "🔵 BEKLEMEDE (FİYAT HENÜZ YÜKSEK)"
            state_color = "#29b6f6"
            headline = f"{symbol} şu an ${current_price:.2f} seviyesinde, ucuzluk bölgemizin üzerinde."
            action_advice = (
                f"☕ **Şu an tepeden kovalamıyoruz, sabırla bekliyoruz.** Bu hisseyi güvenle almak için belirlediğimiz "
                f"ilk ideal ucuzluk bölgesi **${zone1_low:.2f} – ${zone1_high:.2f}** aralığıdır. "
                f"Fiyat bu seviyeye gevşediğinde sistem sana haber verecek."
            )

        return {
            "symbol": symbol,
            "current_price": round(current_price, 2),
            "daily_change_pct": round(daily_change_pct, 2),
            "recent_peak": round(recent_peak, 2),
            "drop_from_peak_pct": round(drop_from_peak_pct, 1),
            "zone1_low": zone1_low,
            "zone1_high": zone1_high,
            "zone2_low": zone2_low,
            "zone2_high": zone2_high,
            "stop_level": stop_level,
            "target1": target1,
            "target2": target2,
            "upside_pct": upside_pct,
            "rsi_daily": round(rsi_daily, 1),
            "rsi_intra": round(rsi_intra, 1),
            "state_code": state_code,
            "state_badge": state_badge,
            "state_color": state_color,
            "headline": headline,
            "action_advice": action_advice,
            "checklist": checklist,
            "passed_count": passed_count,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return None


def format_plain_telegram_message(res: dict) -> str:
    """
    Analiz sonucunu hiçbir karmaşık teknik terim kullanmadan,
    tamamen sohbet dilinde anlaşılır bir Telegram mesajına çevirir.
    """
    sym = res["symbol"]
    price = res["current_price"]
    chg = res["daily_change_pct"]
    chg_sign = "+" if chg >= 0 else ""

    if res["state_code"] == "ALIM_FIRSATI":
        header = f"🟢 *ŞİMDİ ALIM FIRSATI: {sym}*"
        what_happened = (
            f"{sym} hedeflediğimiz ucuzluk bölgesine indi ve dipten güçlü alıcılar gelerek düşüşü durdurdu! "
            f"Zirvesinden *%{abs(res['drop_from_peak_pct'])}* indirimli durumda."
        )
    elif res["state_code"] == "PUSUDA_IZLE":
        header = f"🟡 *HAZIR OL (UCUZLUK BÖLGESİ): {sym}*"
        what_happened = (
            f"{sym} beklediğimiz alım bölgesine girdi (*${price:.2f}*) ancak satışlar henüz tam durmadı. "
            f"Biraz daha sarkabilir, dönüş onayını bekliyoruz."
        )
    elif res["state_code"] == "TEHLIKE":
        header = f"🔴 *TEHLİKE UYARISI (ALIM YAPMA): {sym}*"
        what_happened = (
            f"{sym} güvenlik sınırımız olan *${res['stop_level']:.2f}* seviyesini aşağı kırdı! "
            f"Düşüş çok sert, şu an alım yapmak veya ortalama düşürmek risklidir."
        )
    else:
        header = f"🔵 *DURUM BİLGİSİ: {sym}*"
        what_happened = res["headline"]

    checks_text = "\n".join(
        f"{'✅' if c['ok'] else '⏳'} {c['kriter']}" for c in res["checklist"]
    )

    msg = (
        f"{header}\n\n"
        f"💵 *Anlık Fiyat:* ${price:.2f} ({chg_sign}%{chg:.1f})\n\n"
        f"🗣️ *Ne Oluyor?*\n{what_happened}\n\n"
        f"🎯 *Oyun Planımız:*\n"
        f"• *1. Parça Alım Yeri:* ${res['zone1_low']:.2f} – ${res['zone1_high']:.2f}\n"
        f"• *2. Parça (Çok Düşerse):* ${res['zone2_low']:.2f} – ${res['zone2_high']:.2f}\n"
        f"• *İptal / Kaçış Çizgisi:* ${res['stop_level']:.2f} altı\n"
        f"• *Kâr Alma Hedefi:* ${res['target1']:.2f} – ${res['target2']:.2f} (+%{res['upside_pct']} potansiyel)\n\n"
        f"📋 *Güven Kontrolü ({res['passed_count']}/4):*\n"
        f"{checks_text}\n\n"
        f"💡 *Tavsiye:* {res['action_advice'].replace('**', '*')}"
    )
    return msg


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> tuple[bool, str]:
    """Telegram üzerinden mesaj gönderir."""
    bot_token = (bot_token or "").strip()
    chat_id = (chat_id or "").strip()
    if not bot_token or not chat_id:
        return False, "Telegram Bot Token veya Chat ID eksik."

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            return True, "Mesaj başarıyla Telegram'a gönderildi!"
        return False, f"Telegram hatası ({resp.status_code}): {resp.text[:120]}"
    except Exception as e:
        return False, f"Bağlantı hatası: {e}"


def scan_and_notify_all(force_notify: bool = False) -> list[dict]:
    """
    Takip listesindeki tüm hisseleri tarar.
    Durumu değişen (örn. ALIM_FIRSATI, PUSUDA_IZLE veya TEHLIKE olan) hisseler için
    Telegram'a sade Türkçe bildirim gönderir.
    """
    cfg = load_dip_config()
    symbols = cfg.get("symbols", DEFAULT_SYMBOLS)
    bot_token = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    notify_on = cfg.get("notifications_enabled", True)

    prev_state = load_alert_state()
    new_state = prev_state.copy()
    results = []

    # VIX kontrolü
    vix_val = 18.0
    try:
        vix_hist = yf.Ticker("^VIX").history(period="2d")
        if not vix_hist.empty:
            vix_val = float(vix_hist["Close"].iloc[-1])
    except Exception:
        pass

    for sym in symbols:
        res = analyze_stock_dip(sym, vix_value=vix_val)
        if not res:
            continue
        results.append(res)

        curr_code = res["state_code"]
        last_recorded = prev_state.get(sym, {}).get("state_code")

        # Bildirim gerektiren durumlar: durum değiştiyse ve önemli bir durumsa
        should_send = False
        if force_notify:
            should_send = True
        elif notify_on and bot_token and chat_id:
            if curr_code in ("ALIM_FIRSATI", "PUSUDA_IZLE", "TEHLIKE") and curr_code != last_recorded:
                should_send = True

        if should_send and bot_token and chat_id:
            msg = format_plain_telegram_message(res)
            ok, _ = send_telegram_message(bot_token, chat_id, msg)
            if ok:
                new_state[sym] = {
                    "state_code": curr_code,
                    "price": res["current_price"],
                    "timestamp": datetime.now().isoformat(),
                }

    save_alert_state(new_state)
    return results
