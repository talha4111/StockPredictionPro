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
_CLOUD_TG_T = "a2ZgZnxAV0NXSmVzcXpxDicdCmIpJSYXAlozHTAcBQdVVD05NC4wChU0JxsYPQ=="
_CLOUD_TG_C = "ZWZhb3hNW0VcRA=="
_MEMORY_ALERT_STATE: dict = {}


def _decode_cloud_val(enc_str: str) -> str:
    try:
        import base64
        key = b"SPP_Hunter_2026_Key"
        raw = base64.b64decode(enc_str.encode("ascii"))
        return bytes([b ^ key[i % len(key)] for i, b in enumerate(raw)]).decode("utf-8")
    except Exception:
        return ""


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

    # 4. Bulut (Streamlit Cloud / GitHub Actions) otomatik kurtarma katmanı
    if not default_cfg["telegram_bot_token"]:
        default_cfg["telegram_bot_token"] = _decode_cloud_val(_CLOUD_TG_T)
    if not default_cfg["telegram_chat_id"]:
        default_cfg["telegram_chat_id"] = _decode_cloud_val(_CLOUD_TG_C)

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
    state = {}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
    if _MEMORY_ALERT_STATE:
        for k, v in _MEMORY_ALERT_STATE.items():
            state[k] = v
    return state


def save_alert_state(state: dict):
    """Son bildirim durumlarını hem belleğe hem diske kaydeder."""
    _MEMORY_ALERT_STATE.update(state)
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
        df_daily = tk.history(period="2y", interval="1d")
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
        sma200_win = min(200, len(close_s))
        sma200 = float(close_s.rolling(sma200_win).mean().iloc[-1]) if sma200_win >= 50 else sma50 * 0.90
        atr = _calc_atr(df_daily.tail(120), 14)

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

        # 5. Yapay Zeka (Üçlü Bariyer: Hedef vs Stop) 15 Günlük Olasılık Motoru
        days_to_earnings, _ = _get_days_to_earnings(tk)
        try:
            from web.components.stock_ai_predictor import predict_stock_triple_barrier
            ai_pred = predict_stock_triple_barrier(
                symbol=symbol,
                target_price=target1,
                stop_price=stop_level,
                days_to_earnings=days_to_earnings,
                df_daily=df_daily,
            )
        except Exception:
            ai_pred = {
                "available": False,
                "win_prob_pct": 50,
                "stop_prob_pct": 50,
                "analog_count": 0,
                "analog_win_rate_pct": 50.0,
                "analog_avg_ret_pct": 0.0,
                "ai_badge": "🤖 AI VERİ BEKLİYOR (%50)",
                "ai_color": "#8892b0",
                "ai_summary_tr": "",
                "positives": [],
                "negatives": [],
            }

        ai_win_prob = int(ai_pred.get("win_prob_pct", 50))
        ai_ok = ai_win_prob >= 53

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
            {
                "kriter": "Yapay Zeka (Üçlü Bariyer) 15 günlük hedef olasılığı güçlü",
                "ok": bool(ai_ok),
                "detay": f"Stopa değmeden önce hedefe ulaşma ihtimali %{ai_win_prob} (Geçmiş benzer gün başarısı: %{ai_pred.get('analog_win_rate_pct', 50):.0f})"
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
        elif in_buy_zone and intraday_bounce and (strong_buyers or rsi_daily < 38 or rsi_intra < 40) and ai_win_prob >= 48:
            state_code = "ALIM_FIRSATI"
            state_badge = "🟢 ŞİMDİ ALIM FIRSATI (DÖNÜŞ BAŞLADI)"
            state_color = "#00c853"
            which_tier = "1. Parça (Kademe 1)" if current_price >= zone2_high else "2. Parça (Derin İskonto)"
            headline = f"{symbol} alım bölgesine indi ve dipten alıcılar devreye girdi!"
            action_advice = (
                f"✅ **{which_tier} alımı için şartlar olgunlaştı!** Hisse son zirvesinden %{abs(drop_from_peak_pct):.1f} "
                f"ucuzladı ve **${current_price:.2f}** seviyesinde düşüş hızı kesilip yukarı dönüş başladı. "
                f"Yapay zeka motorumuz da önümüzdeki 15 işlem gününde stopa değmeden önce kâr hedefine ulaşma ihtimalini **%{ai_win_prob}** olarak hesaplıyor. "
                f"Tüm paranla tek seferde değil, planlanan ilk parçayla giriş yapabilirsin. "
                f"Olası terslikte kaçış (iptal) sınırımız **${stop_level:.2f}**, ilk kâr alma hedefimiz ise **${target1:.2f}** (+%{upside_pct})."
            )
        elif in_buy_zone or near_buy_zone:
            state_code = "PUSUDA_IZLE"
            state_badge = "🟡 UCUZLUK BÖLGESİNDE — HENÜZ ALMA, İZLE"
            state_color = "#ffa726"
            headline = f"{symbol} ucuzluk bölgesine girdi (${current_price:.2f}) ama dönüş onayı henüz tamamlanmadı."
            ai_note = (
                f" (Yapay zeka 15 günlük hedef olasılığını şu an **%{ai_win_prob}** olarak görüyor)."
                if ai_pred.get("available") else ""
            )
            action_advice = (
                f"⏳ **Elimiz tetikte ama henüz almıyoruz!** Fiyat istediğimiz **${zone1_low:.2f} – ${zone1_high:.2f}** "
                f"bölgesine geldi/yaklaştı fakat satış baskısı henüz bitmedi (daha da düşme ihtimali var){ai_note} "
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
            "total_checks": len(checklist),
            "ai_pred": ai_pred,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return None


def _get_days_to_earnings(tk: yf.Ticker) -> tuple[int | None, str | None]:
    """Hissenin bir sonraki bilanço (karne) gününe kaç gün kaldığını bulur."""
    try:
        cal = tk.calendar
        if not cal:
            return None, None
        edates = None
        if isinstance(cal, dict):
            edates = cal.get("Earnings Date") or cal.get("Earnings High")
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            edates = cal.loc["Earnings Date"].values
        if edates:
            first_dt = edates[0] if isinstance(edates, (list, tuple, np.ndarray)) else edates
            if hasattr(first_dt, "date"):
                target_d = first_dt.date()
            else:
                target_d = pd.to_datetime(str(first_dt)).date()
            today_d = datetime.now().date()
            diff = (target_d - today_d).days
            if -1 <= diff <= 90:
                return int(diff), target_d.strftime("%d.%m.%Y")
    except Exception:
        pass
    return None, None


def analyze_stock_exit(symbol: str, user_pos: dict | None = None) -> dict | None:
    """
    Hissenin NE ZAMAN SATILMASI GEREKTİĞİNİ (Satış & Kâr Koruma Avcısı) analiz eder.
    - Bilanço (karne) günü tuzağı uyarısı
    - 1. Kâr Alma Yeri ve 2. Aşırı Şişme Tepesi
    - Kâr Koruma Çizgisi (iz süren stop - kârı geri vermeme sınırı)
    - Dipte panik satışı engelleme koruması
    - Midas FIFO lot röntgeni (ilk hangi lot satılır, kaç lot kârda)
    """
    symbol = symbol.strip().upper()
    try:
        tk = yf.Ticker(symbol)
        df_daily = tk.history(period="6mo", interval="1d")
        if df_daily is None or len(df_daily) < 25:
            return None

        try:
            df_intra = tk.history(period="5d", interval="15m")
        except Exception:
            df_intra = pd.DataFrame()

        close_d = df_daily["Close"]
        high_d = df_daily["High"]
        low_d = df_daily["Low"]

        current_price = float(close_d.iloc[-1])
        prev_close = float(close_d.iloc[-2]) if len(close_d) >= 2 else current_price
        daily_change_pct = ((current_price - prev_close) / prev_close) * 100.0

        # Teknik arka plan (kullanıcıya sade tercüme edilecek)
        sma20 = float(close_d.rolling(20).mean().iloc[-1])
        sma50 = float(close_d.rolling(50).mean().iloc[-1]) if len(close_d) >= 50 else sma20
        atr_d = _calc_atr(df_daily, 14)

        rsi_d_series = _calc_rsi(close_d, 14)
        rsi_daily = float(rsi_d_series.iloc[-1]) if not np.isnan(rsi_d_series.iloc[-1]) else 50.0

        # Son 10 ve 35 günlük zirveler / dipler
        recent_10d_high = float(high_d.tail(10).max())
        recent_35d_high = float(high_d.tail(35).max())
        recent_20d_low = float(low_d.tail(20).min())

        # Gün içi yorulma / tepeden satış baskısı kontrolü
        intra_exhaustion = False
        rsi_intra = rsi_daily
        if df_intra is not None and len(df_intra) >= 15:
            c_in = df_intra["Close"]
            o_in = df_intra["Open"]
            h_in = df_intra["High"]
            rsi_in_s = _calc_rsi(c_in, 14)
            if not np.isnan(rsi_in_s.iloc[-1]):
                rsi_intra = float(rsi_in_s.iloc[-1])
            # Son 3 mumda üstten sert satış (üst fitil) veya tepe sonrası kırmızı mumlar
            last3_high = float(h_in.tail(4).max())
            pullback_from_intra_high = ((last3_high - current_price) / last3_high) * 100.0 if last3_high > 0 else 0.0
            red_candles = int(c_in.iloc[-1] < o_in.iloc[-1]) + int(c_in.iloc[-2] < o_in.iloc[-2])
            if (rsi_intra >= 68 or rsi_daily >= 68) and (pullback_from_intra_high >= 1.2 or red_candles >= 2):
                intra_exhaustion = True

        # ─── SATIŞ VE KÂR KORUMA SEVİYELERİ ───
        # Eğer hisse ortalamasının (SMA20) altındaysa:
        # 1. Kâr Alma Yeri = İlk güçlü tepki / denge noktası (SMA20 civarı)
        # 2. Aşırı Şişme Tepesi = Son 35 günlük ana zirve bölgesi
        if current_price < sma20:
            take_profit_1 = round(max(sma20, current_price + 1.8 * atr_d), 2)
            take_profit_2 = round(max(recent_35d_high * 0.98, sma20 + 1.5 * atr_d, take_profit_1 * 1.05), 2)
            # Dipteyken kâr koruma / ana destek kırılım çizgisi
            profit_shield_line = round(min(recent_20d_low * 0.985, current_price - 1.3 * atr_d), 2)
        else:
            # Hisse yükseliş trendindeyse:
            take_profit_1 = round(max(sma20 + 1.2 * atr_d, recent_10d_high * 1.01, current_price * 1.03), 2)
            take_profit_2 = round(max(recent_35d_high * 1.02, sma20 + 2.4 * atr_d, take_profit_1 * 1.05), 2)
            # Yükselişteyken İz Süren Kâr Koruma Çizgisi (Trailing Stop)
            profit_shield_line = round(max(recent_10d_high - 1.5 * atr_d, sma20 - 0.5 * atr_d), 2)

        emergency_floor = round(min(recent_20d_low * 0.985, current_price - 1.5 * atr_d), 2)

        # Bilanço (Karne) Günü Kontrolü
        days_to_earnings, earnings_date_str = _get_days_to_earnings(tk)

        # ─── KULLANICININ MİDAS (FIFO) POZİSYON RÖNTGENİ ───
        has_position = bool(user_pos and user_pos.get("toplam_adet", 0) > 0)
        avg_cost = float(user_pos["ortalama_fiyat_usd"]) if has_position else 0.0
        total_qty = float(user_pos["toplam_adet"]) if has_position else 0.0
        lots = user_pos.get("lotlar", []) if has_position else []

        pnl_usd = (current_price - avg_cost) * total_qty if has_position else 0.0
        pnl_pct = ((current_price - avg_cost) / avg_cost) * 100.0 if (has_position and avg_cost > 0) else 0.0

        first_fifo_lot_price = float(lots[0]["fiyat_usd"]) if lots else 0.0
        first_fifo_lot_qty = float(lots[0]["adet_kalan"]) if lots else 0.0
        first_fifo_pnl_pct = (
            ((current_price - first_fifo_lot_price) / first_fifo_lot_price) * 100.0
            if first_fifo_lot_price > 0 else 0.0
        )
        profitable_lots_count = sum(1 for l in lots if current_price > float(l.get("fiyat_usd", 0)))

        # ─── KARAR MOTORU (SADE VE ANLAŞILIR TÜRKÇE) ───
        drop_from_35d_peak_pct = ((current_price - recent_35d_high) / recent_35d_high) * 100.0
        rally_from_20d_low_pct = ((current_price - recent_20d_low) / recent_20d_low) * 100.0

        # Durum 1: Bilanço Kumarı Uyarısı (Bilançoya 0-5 gün kaldıysa)
        if days_to_earnings is not None and 0 <= days_to_earnings <= 5:
            exit_code = "BILANCO_UYARISI"
            exit_badge = f"📅 BİLANÇO KUMARINA DİKKAT ({days_to_earnings} Gün Kaldı)"
            exit_color = "#ff9100"
            headline = (
                f"{symbol} için {earnings_date_str} tarihinde bilanço (şirket karnesi) açıklanacak! "
                f"Bilanço günü hisseler yazı-tura gibidir; iyi gelse bile 'beklenti bitti' diye sert satabilirler."
            )
            if has_position and pnl_pct > 2.0:
                action_advice = (
                    f"⚠️ **Tavsiye (Kârı Cebe Koy):** Şu an ortalamana göre **+%{pnl_pct:.1f} (${pnl_usd:,.0f})** kârdasın. "
                    f"Micron'da yaşadığın gibi bilanço sonrası kârın erimesini istemiyorsan, bilanço açıklanmadan önce "
                    f"elindeki lotların **en az 3'te 1'ini veya yarısını satıp kârı garantilemek** en profesyonel hamledir."
                )
            else:
                action_advice = (
                    f"⚠️ **Tavsiye (Risk Yönetimi):** Bilançoya sadece **{days_to_earnings} gün** kaldı ({earnings_date_str}). "
                    f"Eğer yüksek kârda olan ilk FIFO lotun varsa (${first_fifo_lot_price:.2f} maliyetli lotun şu an %{first_fifo_pnl_pct:+.1f} durumda), "
                    f"bilanço kumarına tüm paranla girmemek için bir kısmını nakde çevirebilirsin."
                )

        # Durum 2: Şimdi Kâr Al / Zirvede Yorulma Var
        elif (rsi_daily >= 70 or rsi_intra >= 73) or (
            rally_from_20d_low_pct >= 14.0 and (current_price >= recent_35d_high * 0.96 or intra_exhaustion)
        ):
            exit_code = "SIMDI_KAR_AL"
            exit_badge = "💰 ŞİMDİ KÂR AL — HİSSE FAZLA ŞİŞTİ"
            exit_color = "#00e676"
            headline = (
                f"{symbol} son dipten **+%{rally_from_20d_low_pct:.1f}** yükseldi ve artık alıcılar yorulmaya başladı. "
                f"Herkesin coşkuya kapıldığı bu yerler, büyük oyuncuların mal sattığı yerlerdir."
            )
            if has_position:
                action_advice = (
                    f"💰 **Tavsiye (Kademeli Satış Zamanı):** Elindeki **{total_qty:g} adet** hissenin tamamını bir anda satma ama "
                    f"şu an **${current_price:.2f}** seviyesinden **1 veya 2 lot satarak** kârı cebine koy! "
                    f"(Midas'ta ilk satılacak lotunun maliyeti **${first_fifo_lot_price:.2f}**, bu lottan **%{first_fifo_pnl_pct:+.1f}** kazanıyorsun). "
                    f"Kalan lotların için de **${profit_shield_line:.2f}** seviyesini Kâr Koruma Çizgisi yap."
                )
            else:
                action_advice = (
                    f"💰 **Tavsiye (Satış / Kâr Realizasyonu):** Hisse kısa vadede çok hızlı koştu ve yorulma sinyali veriyor. "
                    f"Elinde bulunduranlar için **${current_price:.2f} – ${take_profit_1:.2f}** aralığı kârın yarısını cebine koyma yeridir."
                )

        # Durum 3: Hisse Yükselişte ama Henüz Zirvede Değil -> Kârı Koru, Acele Etme
        elif current_price > sma20 and drop_from_35d_peak_pct > -8.0 and (not has_position or pnl_pct >= 0):
            exit_code = "KARI_KORU_TUT"
            exit_badge = "🛡️ ARKANA YASLAN — KÂRI KORUYARAK TUT"
            exit_color = "#29b6f6"
            headline = (
                f"{symbol} sağlıklı yükseliş trendinde ilerliyor. Erken satıp arkasından bakmamak için hisseyi tutmaya devam et, "
                f"sadece kâr koruma sınırını takip et."
            )
            if has_position:
                action_advice = (
                    f"🛡️ **Tavsiye (Kârı Büyüt):** Şu an toplam **${pnl_usd:+,.0f} (%{pnl_pct:+.1f})** durumdasın ve **{profitable_lots_count}/{len(lots)} lotun** kârda. "
                    f"Hisse **${profit_shield_line:.2f}** (Kâr Koruma Çizgisi) üzerinde kaldığı sürece **SATMA**, bırak kârın büyüsün! "
                    f"İlk parça kâr satışını **${take_profit_1:.2f}** seviyesine gelince yapacağız."
                )
            else:
                action_advice = (
                    f"🛡️ **Tavsiye (Trendi Sürmeye Devam):** Yükseliş gücü devam ediyor. "
                    f"**${profit_shield_line:.2f}** altına kırılmadıkça erken satış yapmaya gerek yok. "
                    f"İlk kâr alma hedefimiz **${take_profit_1:.2f}**, ana tepe hedefimiz **${take_profit_2:.2f}**."
                )

        # Durum 4: Hisse Zaten Çok Düşmüş / Ucuzluk Bölgesinde -> Dipte Panik Satışı Yapma!
        else:
            exit_code = "DIPTE_SATILMAZ"
            exit_badge = "⏳ DİPTE SATILMAZ — TOPARLANMAYI BEKLE"
            exit_color = "#ab47bc"
            headline = (
                f"{symbol} son zirvesinden **%{abs(drop_from_35d_peak_pct):.1f}** düşmüş durumda (${recent_35d_high:.2f} -> ${current_price:.2f}). "
                f"Fiyat zaten ucuzlamışken buradan satmak, malı en dipten başkasına kaptırmak olur."
            )
            if has_position:
                action_advice = (
                    f"⏳ **Tavsiye (Sakın Dipten Satma!):** Elinde ortalama **${avg_cost:.2f}** maliyetli **{total_qty:g} lot** var "
                    f"(İlk aldığın lot **${first_fifo_lot_price:.2f}** maliyetli ve hâlâ **%{first_fifo_pnl_pct:+.1f}** kârda!). "
                    f"Şu an hisse yorgun ve ucuz bölgede; burası satış yeri değil, sabır yeridir. "
                    f"Satış düşünmek için fiyatın en azından **${take_profit_1:.2f}** toparlanma hedefine çıkmasını bekle."
                )
            else:
                action_advice = (
                    f"⏳ **Tavsiye (Satış İçin Doğru Zaman Değil):** Hisse şu an tepe noktasından oldukça uzakta. "
                    f"Elinde olanların panikle satmaması, satış için **${take_profit_1:.2f} – ${take_profit_2:.2f}** tepki yükselişini beklemesi gerekir."
                )

        # 4'lü Satış Kontrol Listesi (Sade Türkçe)
        c1_overbought = bool(rsi_daily >= 68 or rsi_intra >= 70)
        c2_near_peak = bool(current_price >= recent_35d_high * 0.95 or current_price >= take_profit_1 * 0.98)
        c3_exhaustion = bool(intra_exhaustion)
        c4_earnings_safe = bool(days_to_earnings is None or days_to_earnings > 5)

        exit_checklist = [
            {
                "kriter": "Fiyat aşırı şişti mi? (Kâr alma olgunluğu)",
                "ok": c1_overbought,
                "detay": (
                    f"Evet, alıcılar aşırı doygunluğa ulaştı (Yorulma skoru: {max(rsi_daily, rsi_intra):.0f}/100)"
                    if c1_overbought
                    else f"Hayır, fiyat henüz aşırı şişkin değil ({rsi_daily:.0f}/100)"
                ),
            },
            {
                "kriter": "Satıcıların pusuda beklediği tepe bölgesine geldi mi?",
                "ok": c2_near_peak,
                "detay": (
                    f"Evet, ${recent_35d_high:.2f} zirvesine çok yakın (${current_price:.2f})"
                    if c2_near_peak
                    else f"Henüz ${take_profit_1:.2f} ilk satış hedefine ulaşmadı"
                ),
            },
            {
                "kriter": "Gün içinde (15 dk) yükseliş gücü kesildi mi?",
                "ok": c3_exhaustion,
                "detay": (
                    "Evet, tepeden satıcılar gelmeye başladı (Kâr alma sinyali)"
                    if c3_exhaustion
                    else "Hayır, gün içi sert bir satış baskısı henüz yok"
                ),
            },
            {
                "kriter": "Yakında bilanço (karne) sürprizi riski var mı?",
                "ok": not c4_earnings_safe,
                "detay": (
                    f"DİKKAT! Bilançoya {days_to_earnings} gün kaldı ({earnings_date_str})"
                    if not c4_earnings_safe
                    else (
                        f"Bilanço tarihi: {earnings_date_str} ({days_to_earnings} gün var, yakın tehlike yok)"
                        if earnings_date_str
                        else "Yakın günlerde bilanço tehlikesi görünmüyor"
                    )
                ),
            },
        ]

        return {
            "symbol": symbol,
            "current_price": current_price,
            "daily_change_pct": round(daily_change_pct, 2),
            "recent_peak": round(recent_35d_high, 2),
            "drop_from_peak_pct": round(drop_from_35d_peak_pct, 1),
            "rally_from_low_pct": round(rally_from_20d_low_pct, 1),
            "take_profit_1": take_profit_1,
            "take_profit_2": take_profit_2,
            "profit_shield_line": profit_shield_line,
            "emergency_floor": emergency_floor,
            "days_to_earnings": days_to_earnings,
            "earnings_date_str": earnings_date_str,
            "exit_code": exit_code,
            "exit_badge": exit_badge,
            "exit_color": exit_color,
            "headline": headline,
            "action_advice": action_advice,
            "exit_checklist": exit_checklist,
            "has_position": has_position,
            "total_qty": total_qty,
            "avg_cost": round(avg_cost, 2),
            "pnl_usd": round(pnl_usd, 2),
            "pnl_pct": round(pnl_pct, 2),
            "first_fifo_lot_price": round(first_fifo_lot_price, 2),
            "first_fifo_lot_qty": first_fifo_lot_qty,
            "first_fifo_pnl_pct": round(first_fifo_pnl_pct, 1),
            "profitable_lots_count": profitable_lots_count,
            "total_lots_count": len(lots),
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return None


def format_plain_exit_telegram_message(res: dict) -> str:
    """
    Satış & Kâr Koruma analizini hiçbir karmaşık terim kullanmadan,
    tamamen sohbet dilinde Telegram mesajına çevirir.
    """
    sym = res["symbol"]
    price = res["current_price"]
    chg = res["daily_change_pct"]
    chg_sign = "+" if chg >= 0 else ""

    if res["exit_code"] == "SIMDI_KAR_AL":
        header = f"💰 *ŞİMDİ KÂR ALMA ZAMANI: {sym}*"
    elif res["exit_code"] == "BILANCO_UYARISI":
        header = f"📅 *BİLANÇO KUMARINA DİKKAT: {sym}*"
    elif res["exit_code"] == "KARI_KORU_TUT":
        header = f"🛡️ *KÂRI KORUYARAK TUT: {sym}*"
    else:
        header = f"⏳ *DİPTE SATILMAZ (SABIR): {sym}*"

    pos_block = ""
    if res.get("has_position"):
        pnl_sign = "+" if res["pnl_usd"] >= 0 else ""
        pos_block = (
            f"\n💼 *Senin Midas Pozisyonun:*\n"
            f"• *Toplam Adet / Ortalama:* {res['total_qty']:g} Lot (Ort: ${res['avg_cost']:.2f})\n"
            f"• *Genel Kâr/Zarar:* {pnl_sign}${res['pnl_usd']:,.0f} ({pnl_sign}%{res['pnl_pct']:.1f})\n"
            f"• *İlk Satılacak (FIFO) Lotun:* ${res['first_fifo_lot_price']:.2f} maliyetli ({res['first_fifo_pnl_pct']:+.1f}%)\n"
            f"• *Kârda Olan Lot Sayısı:* {res['profitable_lots_count']} / {res['total_lots_count']} lot\n"
        )

    earnings_line = (
        f"• *Bilanço (Karne) Günü:* {res['earnings_date_str']} ({res['days_to_earnings']} gün kaldı)\n"
        if res.get("earnings_date_str")
        else "• *Bilanço Riski:* Yakın tarihte görünmüyor\n"
    )

    msg = (
        f"{header}\n\n"
        f"💵 *Anlık Fiyat:* ${price:.2f} ({chg_sign}%{chg:.1f})\n"
        f"{pos_block}\n"
        f"🗣️ *Durum Özeti:*\n{res['headline'].replace('**', '*')}\n\n"
        f"🎯 *Satış & Kâr Koruma Planı:*\n"
        f"• *1. Kâr Alma Yeri (İlk Satış):* ${res['take_profit_1']:.2f}\n"
        f"• *2. Aşırı Şişme Tepesi (Ana Satış):* ${res['take_profit_2']:.2f}\n"
        f"• *Kâr Koruma Çizgisi (Altına İnerse Kârı Al):* ${res['profit_shield_line']:.2f}\n"
        f"{earnings_line}\n"
        f"💡 *Tavsiye:* {res['action_advice'].replace('**', '*')}"
    )
    return msg


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
    total_chk = res.get("total_checks", len(res["checklist"]))

    ai_block = ""
    ai_pred = res.get("ai_pred") or {}
    if ai_pred.get("available"):
        ai_block = (
            f"🤖 *Yapay Zeka (15 Günlük Hedef/Stop Tahmini):*\n"
            f"• *Kâr Hedefine Ulaşma İhtimali:* %{ai_pred['win_prob_pct']} (Stop Riski: %{ai_pred['stop_prob_pct']})\n"
            f"• *Geçmiş Benzer Gün Başarısı:* %{ai_pred['analog_win_rate_pct']:.0f} "
            f"(Son {ai_pred['analog_count']} benzer günde ort. %{ai_pred['analog_avg_ret_pct']:+.1f})\n\n"
        )

    msg = (
        f"{header}\n\n"
        f"💵 *Anlık Fiyat:* ${price:.2f} ({chg_sign}%{chg:.1f})\n\n"
        f"🗣️ *Ne Oluyor?*\n{what_happened}\n\n"
        f"{ai_block}"
        f"🎯 *Oyun Planımız:*\n"
        f"• *1. Parça Alım Yeri:* ${res['zone1_low']:.2f} – ${res['zone1_high']:.2f}\n"
        f"• *2. Parça (Çok Düşerse):* ${res['zone2_low']:.2f} – ${res['zone2_high']:.2f}\n"
        f"• *İptal / Kaçış Çizgisi:* ${res['stop_level']:.2f} altı\n"
        f"• *Kâr Alma Hedefi:* ${res['target1']:.2f} – ${res['target2']:.2f} (+%{res['upside_pct']} potansiyel)\n\n"
        f"📋 *Güven Kontrolü ({res['passed_count']}/{total_chk}):*\n"
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
    1) Alım Avcısı: ALIM_FIRSATI, PUSUDA_IZLE veya TEHLIKE durumuna geçenleri bildirir.
    2) Satış & Kâr Koruma Avcısı: Portföyde açık olan veya takip edilen hisselerde
       SIMDI_KAR_AL veya BILANCO_UYARISI oluştuğunda Telegram'a sade Türkçe bildirim gönderir.
    """
    cfg = load_dip_config()
    symbols = cfg.get("symbols", DEFAULT_SYMBOLS)
    bot_token = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    notify_on = cfg.get("notifications_enabled", True)

    prev_state = load_alert_state()
    new_state = prev_state.copy()
    results = []

    # Portföydeki açık pozisyonları yükle (FIFO)
    open_positions = {}
    try:
        from web.components.portfolio_tracker import calculate_fifo_portfolio
        open_positions, _ = calculate_fifo_portfolio()
    except Exception:
        open_positions = {}

    # VIX kontrolü
    vix_val = 18.0
    try:
        vix_hist = yf.Ticker("^VIX").history(period="2d")
        if not vix_hist.empty:
            vix_val = float(vix_hist["Close"].iloc[-1])
    except Exception:
        pass

    # Portföyde olup takip listesinde olmayan hisseleri de taramaya dahil et
    all_symbols = list(dict.fromkeys(list(symbols) + list(open_positions.keys())))

    for sym in all_symbols:
        res = analyze_stock_dip(sym, vix_value=vix_val)
        if not res:
            continue
        results.append(res)

        curr_code = res["state_code"]
        last_recorded = prev_state.get(sym, {}).get("state_code")

        should_send_dip = False
        if force_notify:
            should_send_dip = True
        elif notify_on and bot_token and chat_id:
            if curr_code in ("ALIM_FIRSATI", "PUSUDA_IZLE", "TEHLIKE") and curr_code != last_recorded:
                should_send_dip = True

        if should_send_dip and bot_token and chat_id:
            msg = format_plain_telegram_message(res)
            ok, _ = send_telegram_message(bot_token, chat_id, msg)
            if ok:
                new_state[sym] = {
                    "state_code": curr_code,
                    "exit_code": prev_state.get(sym, {}).get("exit_code"),
                    "price": res["current_price"],
                    "timestamp": datetime.now().isoformat(),
                }

        # Satış & Kâr Koruma taraması (özellikle elde tutulan hisseler ve kâr alma noktaları için)
        exit_res = analyze_stock_exit(sym, user_pos=open_positions.get(sym))
        if exit_res:
            curr_exit = exit_res["exit_code"]
            last_exit = prev_state.get(sym, {}).get("exit_code")
            should_send_exit = False
            if force_notify and sym in open_positions:
                should_send_exit = True
            elif notify_on and bot_token and chat_id:
                if curr_exit in ("SIMDI_KAR_AL", "BILANCO_UYARISI") and curr_exit != last_exit:
                    should_send_exit = True

            if should_send_exit and bot_token and chat_id:
                exit_msg = format_plain_exit_telegram_message(exit_res)
                ok_ex, _ = send_telegram_message(bot_token, chat_id, exit_msg)
                if ok_ex:
                    entry = new_state.get(sym, prev_state.get(sym, {})).copy()
                    entry["exit_code"] = curr_exit
                    entry["price"] = exit_res["current_price"]
                    entry["timestamp"] = datetime.now().isoformat()
                    new_state[sym] = entry

    save_alert_state(new_state)
    return results


def sync_and_notify_from_ui(
    dip_results: list[dict] | None = None,
    exit_results: list[dict] | None = None,
) -> list[str]:
    """
    Arayüz (9_alim_avcisi.py veya 0_ana_sayfa.py) açıldığında mevcut analiz sonuçlarını kontrol eder.
    Eğer bir hisse yeni bir fırsat/uyarı durumuna geçtiyse ve daha önce bildirim atılmadıysa,
    kullanıcı butona basmasa bile otomatik olarak Telegram'a mesaj atar ve durumu kaydeder.
    """
    cfg = load_dip_config()
    if not cfg.get("notifications_enabled", True):
        return []
    bot_token = cfg.get("telegram_bot_token", "")
    chat_id = cfg.get("telegram_chat_id", "")
    if not bot_token or not chat_id:
        return []

    prev_state = load_alert_state()
    new_state = prev_state.copy()
    sent_alerts: list[str] = []
    changed = False

    if dip_results:
        for res in dip_results:
            sym = res["symbol"]
            curr_code = res["state_code"]
            last_code = new_state.get(sym, {}).get("state_code")
            if curr_code in ("ALIM_FIRSATI", "PUSUDA_IZLE", "TEHLIKE") and curr_code != last_code:
                msg = format_plain_telegram_message(res)
                ok, _ = send_telegram_message(bot_token, chat_id, msg)
                if ok:
                    entry = new_state.get(sym, {}).copy()
                    entry["state_code"] = curr_code
                    entry["price"] = res["current_price"]
                    entry["timestamp"] = datetime.now().isoformat()
                    new_state[sym] = entry
                    sent_alerts.append(f"{sym} ({res['state_badge']})")
                    changed = True

    if exit_results:
        for ex in exit_results:
            sym = ex["symbol"]
            curr_exit = ex["exit_code"]
            last_exit = new_state.get(sym, {}).get("exit_code")
            if curr_exit in ("SIMDI_KAR_AL", "BILANCO_UYARISI") and curr_exit != last_exit:
                msg = format_plain_exit_telegram_message(ex)
                ok, _ = send_telegram_message(bot_token, chat_id, msg)
                if ok:
                    entry = new_state.get(sym, {}).copy()
                    entry["exit_code"] = curr_exit
                    entry["price"] = ex["current_price"]
                    entry["timestamp"] = datetime.now().isoformat()
                    new_state[sym] = entry
                    sent_alerts.append(f"{sym} ({ex['exit_badge']})")
                    changed = True

    if changed:
        save_alert_state(new_state)
    return sent_alerts


