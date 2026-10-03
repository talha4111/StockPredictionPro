"""
StockPredictionPro — Mobil Bileşenler & Yardımcı Fonksiyonlar
Önbellekli veri çekimi, dokunmatik kartlar ve mobil navigasyon.
"""
import os
import sqlite3
import pandas as pd
import streamlit as st
import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

COMPANY_NAMES = {
    "NVDA": "NVIDIA Corporation",
    "AVGO": "Broadcom Inc.",
    "AMD": "Advanced Micro Devices",
    "MU": "Micron Technology",
    "MRVL": "Marvell Technology",
    "QCOM": "Qualcomm Inc.",
    "LRCX": "Lam Research",
    "AMAT": "Applied Materials",
    "BE": "Bloom Energy",
    "VST": "Vistra Corp",
    "CEG": "Constellation Energy",
    "NRG": "NRG Energy",
    "FSLR": "First Solar",
    "NEE": "NextEra Energy",
    "DELL": "Dell Technologies",
    "HPE": "Hewlett Packard Enterprise",
    "SMCI": "Super Micro Computer",
    "VRT": "Vertiv Holdings",
    "COHR": "Coherent Corp",
    "CRWD": "CrowdStrike Holdings",
    "PANW": "Palo Alto Networks",
    "FTNT": "Fortinet Inc.",
    "ZS": "Zscaler Inc.",
    "S": "SentinelOne",
    "MSFT": "Microsoft Corp.",
    "AMZN": "Amazon.com Inc.",
    "GOOGL": "Alphabet (Google)",
    "NOW": "ServiceNow Inc.",
    "SNOW": "Snowflake Inc.",
    "DDOG": "Datadog Inc.",
    "AAPL": "Apple Inc.",
    "TSLA": "Tesla Inc.",
    "EOG": "EOG Resources",
    "XOM": "Exxon Mobil",
    "CVX": "Chevron Corp",
    "JPM": "JPMorgan Chase",
    "LLY": "Eli Lilly and Co.",
    "UNH": "UnitedHealth Group",
    "COST": "Costco Wholesale",
    "WMT": "Walmart Inc.",
    "BMY": "Bristol-Myers Squibb",
    "UNP": "Union Pacific",
    "PM": "Philip Morris",
    "KO": "Coca-Cola Co.",
}

BADGE_STYLES = {
    "AL_ADAYI": ("🟢 AL ADAYI", "#00c853", "rgba(0,200,83,0.15)"),
    "KALITELI_GERI_CEKILME": ("🟢 AL ADAYI", "#00c853", "rgba(0,200,83,0.15)"),
    "TREND_DEVAMI": ("🟢 TREND", "#00c853", "rgba(0,200,83,0.15)"),
    "PAPER_TOP20": ("🟢 TOP 20", "#00c853", "rgba(0,200,83,0.15)"),
    "PAPER_SHADOW": ("🟢 GÖLGE", "#00c853", "rgba(0,200,83,0.15)"),
    "BEKLE": ("🟡 BEKLE", "#ffb300", "rgba(255,179,0,0.15)"),
    "BEKLE_GERI_CEKILME": ("🟡 BEKLE", "#ffb300", "rgba(255,179,0,0.15)"),
    "UZAMIS_TREND": ("🟡 DÜZELTME", "#ffb300", "rgba(255,179,0,0.15)"),
    "IZLE": ("🔵 İZLE", "#29b6f6", "rgba(41,182,246,0.15)"),
    "REDDET": ("🔴 UZAK DUR", "#ef5350", "rgba(239,83,80,0.15)"),
    "REDDET_TREND": ("🔴 AYI TRENDİ", "#ef5350", "rgba(239,83,80,0.15)"),
    "OLAY_RISKI": ("🟣 BİLANÇO", "#ab47bc", "rgba(171,71,188,0.18)"),
}


def badge_info(decision: str):
    """Karar dizesini etiket, renk ve arkaplan üçlüsüne dönüştürür."""
    if not decision:
        return ("🔵 İZLE", "#29b6f6", "rgba(41,182,246,0.15)")
    for key, val in BADGE_STYLES.items():
        if key in decision:
            return val
    return (f"🔵 {decision}", "#29b6f6", "rgba(41,182,246,0.15)")


@st.cache_data(ttl=60)
def get_cached_quotes(symbols: tuple):
    """
    Birden fazla hissenin anlık fiyat ve günlük değişimini
    60 saniye önbellek ile tek seferde çeker.
    """
    quotes = {}
    if not symbols:
        return quotes

    try:
        data = yf.download(list(symbols), period="5d", progress=False, group_by="ticker")
        for sym in symbols:
            try:
                if len(symbols) == 1:
                    df_sym = data
                else:
                    df_sym = data[sym] if sym in data else None

                if df_sym is not None and not df_sym.empty and "Close" in df_sym:
                    closes = df_sym["Close"].dropna()
                    if len(closes) >= 1:
                        price = float(closes.iloc[-1])
                        prev = float(closes.iloc[-2]) if len(closes) >= 2 else price
                        chg = price - prev
                        chg_pct = (chg / prev * 100) if prev > 0 else 0.0
                        quotes[sym] = {
                            "price": price,
                            "change": chg,
                            "change_pct": chg_pct,
                        }
            except Exception:
                pass
    except Exception:
        pass

    # Eksik kalanları fast_info ile tamamla
    for sym in symbols:
        if sym not in quotes:
            try:
                tk = yf.Ticker(sym)
                fast = getattr(tk, "fast_info", {})
                price = fast.get("lastPrice") or getattr(fast, "last_price", 0.0) or 0.0
                prev = fast.get("previousClose") or getattr(fast, "previous_close", 0.0) or 0.0
                if price and price > 0:
                    chg = price - prev if prev > 0 else 0.0
                    chg_pct = (chg / prev * 100) if prev > 0 else 0.0
                    quotes[sym] = {
                        "price": float(price),
                        "change": float(chg),
                        "change_pct": float(chg_pct),
                    }
                else:
                    quotes[sym] = {"price": 0.0, "change": 0.0, "change_pct": 0.0}
            except Exception:
                quotes[sym] = {"price": 0.0, "change": 0.0, "change_pct": 0.0}

    return quotes


@st.cache_data(ttl=300)
def get_db_symbol_data(symbols: tuple):
    """Veritabanından hisselerin son durumunu, kararını ve skorunu çeker."""
    result = {}
    if not os.path.exists(DB_PATH):
        return result
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        placeholders = ",".join(["?"] * len(symbols))
        c.execute(f"""
            SELECT sembol, decision, ai_skor, fiyat, as_of_date
            FROM hisse_sinyalleri
            WHERE sembol IN ({placeholders})
            ORDER BY id DESC
        """, list(symbols))
        for r in c.fetchall():
            sym = r[0]
            if sym not in result:  # en güncelini al
                result[sym] = {
                    "decision": r[1] or "IZLE",
                    "score": r[2] or 50.0,
                    "db_fiyat": r[3] or 0.0,
                    "as_of_date": r[4] or "",
                }
        conn.close()
    except Exception:
        pass
    return result


@st.cache_data(ttl=300)
def get_top_opportunities(limit: int = 5):
    """En son taramada en yüksek puanlı AL_ADAYI fırsatlarını döndürür."""
    if not os.path.exists(DB_PATH):
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT MAX(as_of_date) FROM hisse_sinyalleri")
        last_date = c.fetchone()[0]
        if not last_date:
            conn.close()
            return []

        c.execute("""
            SELECT sembol, sektor, ROUND(ai_skor, 1), decision, ROUND(fiyat, 2)
            FROM hisse_sinyalleri
            WHERE as_of_date = ? AND decision IN ('AL_ADAYI', 'PAPER_TOP20', 'KALITELI_GERI_CEKILME')
            ORDER BY ai_skor DESC
            LIMIT ?
        """, (last_date, limit))
        rows = c.fetchall()
        conn.close()
        return [
            {
                "sembol": r[0],
                "sektor": r[1],
                "skor": r[2],
                "karar": r[3],
                "fiyat": r[4],
            }
            for r in rows
        ]
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_vix_status():
    """VIX durumunu ve rengini önbellekli döndürür."""
    try:
        from stock_value_engine import vix_oku
        val = vix_oku()
        if val:
            if val < 15:
                return round(val, 1), "🟢 Sakin", "#00c853"
            elif val < 25:
                return round(val, 1), "🟡 Dikkatli", "#ffb300"
            else:
                return round(val, 1), "🔴 Panik", "#ef5350"
    except Exception:
        pass
    return 18.5, "🟡 Normal", "#ffb300"
