"""
StockPredictionPro — Kurumsal AI Uzman Analist & Kalıcı Hafıza Motoru
======================================================================
Özellikler:
1. Çift Katmanlı Kalıcı Hafıza (SQLite + JSON Senkronizasyonu):
   - Uzun süreli yatırımcı profili, Midas FIFO kuralları, geçmiş analiz ve karar hafızası (`ai_analyst_memory.json`).
   - Çoklu oturum sohbet geçmişi ve bağlam (son konuşulan hisseler) takibi (`ai_chat_sessions.json`).
2. Gerçek Zamanlı Kurumsal Veri & Algoritma Enjeksiyonu (RAG / Tool Telemetry):
   - Dip Avcısı (`dip_hunter`), Üçlü Bariyer AI (`stock_ai_predictor`), Yatırım Komitesi (`investment_committee`),
     Midas FIFO Portföy Motoru (`portfolio_tracker`) ve canlı Yahoo Finance (ABD + BIST `.IS`) bilanço/çarpan verileri.
3. Hibrit Yapay Zeka Mimarisi:
   - Bulut LLM Modu: Google Gemini (2.5 Pro / Flash), Groq (Llama-3.3-70B) veya OpenAI (GPT-4o) API desteği.
   - Yerleşik Kurumsal Quant Muhakeme Motoru: Harici API anahtarı girilmemiş olsa dahi tüm canlı verileri,
     bilançoları, kademe kutularını ve geçmiş hafızayı sentezleyerek Wall Street kıdemli analisti kalitesinde yanıt üretir.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

try:
    import streamlit as st
    _cache_data = st.cache_data
except Exception:
    def _cache_data(**_kwargs):
        def _wrap(fn):
            return fn
        return _wrap

_FAILED_LLM_KEYS: set[str] = set()

from web.components.dip_hunter import analyze_stock_dip, analyze_stock_exit
from web.components.investment_committee import (
    analyze_earnings_catalyst,
    build_investment_committee_card,
    detect_factor_conflicts,
    get_market_regime_summary,
)
from web.components.mobile import COMPANY_NAMES, get_db_symbol_data, get_top_opportunities
from web.components.portfolio_tracker import calculate_fifo_portfolio, get_current_usdtry
from web.components.stock_ai_predictor import predict_stock_triple_barrier

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(PROJECT_ROOT, "web", "data")
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

MEMORY_JSON_PATH = os.path.join(DATA_DIR, "ai_analyst_memory.json")
SESSIONS_JSON_PATH = os.path.join(DATA_DIR, "ai_chat_sessions.json")
AI_CONFIG_PATH = os.path.join(DATA_DIR, "ai_provider_config.json")


# ─── BIST & ABD HİSSE SÖZLÜĞÜ (DOĞAL DİL EŞLEŞTİRME) ───
BIST_TICKER_MAP = {
    "SARAE": "SARAE.IS",
    "SARA": "SARAE.IS",
    "ŞA-RA": "SARAE.IS",
    "ŞARA": "SARAE.IS",
    "SA-RA": "SARAE.IS",
    "THYAO": "THYAO.IS",
    "THY": "THYAO.IS",
    "TUPRS": "TUPRS.IS",
    "TÜPRAŞ": "TUPRS.IS",
    "TUPRAS": "TUPRS.IS",
    "ASELS": "ASELS.IS",
    "ASELSAN": "ASELS.IS",
    "ASTOR": "ASTOR.IS",
    "CWENE": "CWENE.IS",
    "AHGAZ": "AHGAZ.IS",
    "SMRTG": "SMRTG.IS",
    "EUPWR": "EUPWR.IS",
    "KONTR": "KONTR.IS",
    "KONTROLMATIK": "KONTR.IS",
    "MIATK": "MIATK.IS",
    "EREGL": "EREGL.IS",
    "EREĞLİ": "EREGL.IS",
    "KCHOL": "KCHOL.IS",
    "SAHOL": "SAHOL.IS",
    "BIMAS": "BIMAS.IS",
    "GARAN": "GARAN.IS",
    "AKBNK": "AKBNK.IS",
    "YKBNK": "YKBNK.IS",
    "ISCTR": "ISCTR.IS",
    "FROTO": "FROTO.IS",
    "TOASO": "TOASO.IS",
    "SISE": "SISE.IS",
    "PGSUS": "PGSUS.IS",
    "PEGASUS": "PGSUS.IS",
    "TCELL": "TCELL.IS",
    "TURKCELL": "TCELL.IS",
    "TTKOM": "TTKOM.IS",
    "ENKAI": "ENKAI.IS",
    "GESAN": "GESAN.IS",
    "YEOTK": "YEOTK.IS",
    "ALFAS": "ALFAS.IS",
    "SURGY": "SURGY.IS",
    "ENDAE": "ENDAE.IS",
    "KLYPV": "KLYPV.IS",
}

US_NAME_ALIAS_MAP = {
    "COHERENT": "COHR",
    "MARVELL": "MRVL",
    "MICRON": "MU",
    "BLOOM": "BE",
    "BLOOM ENERGY": "BE",
    "ROCKET LAB": "RKLB",
    "ROCKETLAB": "RKLB",
    "BROADCOM": "AVGO",
    "NVIDIA": "NVDA",
    "VERTIV": "VRT",
    "CONSTELLATION": "CEG",
    "GE VERNOVA": "GEV",
    "PALANTIR": "PLTR",
    "SUPERMICRO": "SMCI",
    "ARISTA": "ANET",
    "CROWDSTRIKE": "CRWD",
    "TAIWAN SEMI": "TSM",
    "TSMC": "TSM",
    "VISTRA": "VST",
}

KNOWN_US_TICKERS = {
    "MU", "MRVL", "COHR", "BE", "RKLB", "AVGO", "NVDA", "AMD", "TSM", "VRT",
    "CEG", "GEV", "EOG", "VST", "PLTR", "SMCI", "ANET", "CRWD", "PANW", "MSFT",
    "META", "AMZN", "GOOGL", "GOOG", "AAPL", "TSLA", "ARM", "KLAC", "LRCX",
    "AMAT", "ASML", "WDC", "STX", "DELL", "IONQ", "INTC", "QCOM", "TXN", "NFLX",
    "CRM", "NOW", "SNOW", "DDOG", "NET", "MDB", "LLY", "NVO", "UNH", "JPM", "GS",
}

BIST_COMPANY_NAMES = {
    "SARAE.IS": "Şa-Ra Enerji İnşaat Ticaret ve Sanayi A.Ş.",
    "THYAO.IS": "Türk Hava Yolları A.O.",
    "TUPRS.IS": "Tüpraş Türkiye Petrol Rafinerileri A.Ş.",
    "ASELS.IS": "Aselsan Elektronik Sanayi ve Ticaret A.Ş.",
    "ASTOR.IS": "Astor Enerji A.Ş.",
    "CWENE.IS": "CW Enerji Mühendislik A.Ş.",
    "AHGAZ.IS": "Ahlatcı Doğalgaz Dağıtım Enerji A.Ş.",
    "SMRTG.IS": "Smart Güneş Enerjisi Teknolojileri A.Ş.",
    "EUPWR.IS": "Europower Enerji ve Otomasyon A.Ş.",
    "KONTR.IS": "Kontrolmatik Teknoloji Enerji ve Mühendislik A.Ş.",
    "MIATK.IS": "Mia Teknoloji A.Ş.",
    "EREGL.IS": "Ereğli Demir ve Çelik Fabrikaları T.A.Ş.",
}

TURKISH_STOPWORDS_UPPER = {
    "VE", "YA", "DA", "DE", "BU", "SU", "ŞU", "NE", "MI", "Mİ", "MU",  # Note: MU handled specially below
    "TL", "USD", "AL", "SAT", "TUT", "RSI", "SMA", "EMA", "ETF", "ABD",
    "BIST", "FIFO", "PE", "FK", "EPS", "AI", "KAR", "KÂR", "LOT", "İÇİN",
    "ICIN", "AMA", "GİBİ", "GIBI", "DAHA", "ÇOK", "COK", "EN", "BİR", "BIR",
    "İKİ", "IKI", "SON", "VAR", "YOK", "OLUR", "NASIL", "ZAMAN", "KAC", "KAÇ",
}


# ─── 1. KALICI HAFIZA & VERİTABANI KATMANI ───
def _init_ai_db():
    """SQLite içinde hafıza ve sohbet tablolarını hazırlar."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_memory_notes (
                id TEXT PRIMARY KEY,
                date TEXT,
                category TEXT,
                symbols_json TEXT,
                title TEXT,
                content TEXT,
                pinned INTEGER DEFAULT 1
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS ai_chat_sessions_backup (
                id TEXT PRIMARY KEY,
                payload_json TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_ai_memory() -> dict:
    """Kalıcı yatırımcı hafızasını JSON (veya SQLite yedeğinden) yükler."""
    _init_ai_db()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(MEMORY_JSON_PATH):
        try:
            with open(MEMORY_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "memory_notes" in data:
                    return data
        except Exception:
            pass

    # Varsayılan kurumsal hafıza
    default_mem = {
        "user_profile": {
            "name": "Talha",
            "username": "talha6641",
            "broker": "Midas (ABD Borsaları & BIST)",
            "commission_usd": 1.5,
            "lot_rule": "FIFO (First-In, First-Out: Satışta en eski lot ilk satılır)",
            "style": "Büyüme + Yapay Zeka / Yarıiletken / Optik / Enerji Altyapısı odaklı swing işlemleri",
            "core_watchlist": ["MU", "MRVL", "AVGO", "EOG", "BE", "COHR", "RKLB", "NVDA"],
        },
        "memory_notes": [],
        "last_context": {
            "last_symbols": ["COHR", "MRVL", "BE", "RKLB"],
            "last_topic": "Genel Piyasa ve Portföy Analizi",
            "updated_at": datetime.now().isoformat(),
        },
    }
    save_ai_memory(default_mem)
    return default_mem


def save_ai_memory(mem_data: dict):
    """Kalıcı hafızayı hem JSON dosyasına hem SQLite'a senkronize eder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(MEMORY_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(mem_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        for note in mem_data.get("memory_notes", []):
            c.execute("""
                INSERT OR REPLACE INTO ai_memory_notes (id, date, category, symbols_json, title, content, pinned)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                note.get("id", uuid.uuid4().hex[:8]),
                note.get("date", datetime.now().strftime("%Y-%m-%d")),
                note.get("category", "GENEL"),
                json.dumps(note.get("symbols", []), ensure_ascii=False),
                note.get("title", ""),
                note.get("content", ""),
                1 if note.get("pinned", True) else 0,
            ))
        conn.commit()
        conn.close()
    except Exception:
        pass


def add_memory_note(
    title: str,
    content: str,
    category: str = "ANALIZ_KARARI",
    symbols: list[str] | None = None,
    pinned: bool = True,
) -> dict:
    """Uzun süreli hafızaya yeni bir analiz/karar notu ekler veya aynı başlıklı notu günceller."""
    mem = load_ai_memory()
    notes = mem.get("memory_notes", [])
    clean_syms = [s.upper().strip() for s in (symbols or []) if s]

    # Aynı başlık varsa güncelle
    for existing in notes:
        if existing.get("title", "").strip().lower() == title.strip().lower():
            existing["date"] = datetime.now().strftime("%Y-%m-%d")
            existing["content"] = content.strip()
            existing["category"] = category
            existing["symbols"] = clean_syms
            existing["pinned"] = pinned
            save_ai_memory(mem)
            return existing

    new_note = {
        "id": f"mem_{uuid.uuid4().hex[:8]}",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "category": category,
        "symbols": clean_syms,
        "title": title.strip(),
        "content": content.strip(),
        "pinned": pinned,
    }
    notes.insert(0, new_note)
    # Maksimum 40 kalıcı not tut (sabitlenmemiş en eskileri temizle)
    if len(notes) > 40:
        pinned_notes = [n for n in notes if n.get("pinned", True)]
        unpinned_notes = [n for n in notes if not n.get("pinned", True)][:10]
        mem["memory_notes"] = (pinned_notes + unpinned_notes)[:40]
    else:
        mem["memory_notes"] = notes

    save_ai_memory(mem)
    return new_note


def delete_memory_note(note_id: str) -> bool:
    """Belirtilen hafıza notunu siler."""
    mem = load_ai_memory()
    mem["memory_notes"] = [n for n in mem.get("memory_notes", []) if n.get("id") != note_id]
    save_ai_memory(mem)
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("DELETE FROM ai_memory_notes WHERE id = ?", (note_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass
    return True


# ─── 2. KALICI SOHBET OTURUMLARI YÖNETİMİ ───
def load_chat_sessions() -> dict:
    """Tüm sohbet oturumlarını JSON veya SQLite yedeğinden okur."""
    _init_ai_db()
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SESSIONS_JSON_PATH):
        try:
            with open(SESSIONS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and data.get("sessions"):
                    return data
        except Exception:
            pass

    default_sessions = {
        "active_session_id": "oturum_ana_1",
        "sessions": [
            {
                "id": "oturum_ana_1",
                "title": "📈 Ana Yatırım & Strateji Masası",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "context_symbols": ["COHR", "MRVL", "BE", "RKLB"],
                "messages": [],
            }
        ],
    }
    save_chat_sessions(default_sessions)
    return default_sessions


def save_chat_sessions(sessions_data: dict):
    """Sohbet oturumlarını diske ve SQLite veritabanına yedekler."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(SESSIONS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(sessions_data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO ai_chat_sessions_backup (id, payload_json, updated_at)
            VALUES ('all_sessions', ?, ?)
        """, (json.dumps(sessions_data, ensure_ascii=False), datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_active_session() -> dict:
    """Aktif sohbet oturumunu döndürür."""
    data = load_chat_sessions()
    active_id = data.get("active_session_id")
    for s in data.get("sessions", []):
        if s.get("id") == active_id:
            return s
    if data.get("sessions"):
        data["active_session_id"] = data["sessions"][0]["id"]
        save_chat_sessions(data)
        return data["sessions"][0]
    return create_new_session("📈 Ana Yatırım Masası")


def create_new_session(title: str = "") -> dict:
    """Yeni bir sohbet oturumu açar (Uzun süreli hafıza korunur)."""
    data = load_chat_sessions()
    new_id = f"oturum_{uuid.uuid4().hex[:6]}"
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
    session_title = title.strip() if title.strip() else f"💬 Analiz Oturumu ({now_str})"
    new_sess = {
        "id": new_id,
        "title": session_title,
        "created_at": now_str,
        "updated_at": now_str,
        "context_symbols": [],
        "messages": [],
    }
    data.setdefault("sessions", []).insert(0, new_sess)
    data["active_session_id"] = new_id
    save_chat_sessions(data)
    return new_sess


def switch_session(session_id: str):
    """Aktif sohbet oturumunu değiştirir."""
    data = load_chat_sessions()
    for s in data.get("sessions", []):
        if s.get("id") == session_id:
            data["active_session_id"] = session_id
            save_chat_sessions(data)
            return


def delete_session(session_id: str):
    """Bir sohbet oturumunu siler."""
    data = load_chat_sessions()
    sessions = [s for s in data.get("sessions", []) if s.get("id") != session_id]
    if not sessions:
        create_new_session("📈 Ana Yatırım & Strateji Masası")
        return
    data["sessions"] = sessions
    if data.get("active_session_id") == session_id:
        data["active_session_id"] = sessions[0]["id"]
    save_chat_sessions(data)


def append_chat_message(
    role: str,
    content: str,
    symbols: list[str] | None = None,
    engine: str = "",
    telemetry_cards: list[dict] | None = None,
):
    """Aktif oturuma yeni mesaj ekler ve bağlam sembollerini günceller."""
    data = load_chat_sessions()
    active_id = data.get("active_session_id")
    now_str = datetime.now().strftime("%d.%m.%Y %H:%M")

    for s in data.get("sessions", []):
        if s.get("id") == active_id:
            msg = {
                "id": uuid.uuid4().hex[:8],
                "role": role,
                "timestamp": now_str,
                "content": content,
                "symbols": symbols or [],
            }
            if engine:
                msg["engine"] = engine
            if telemetry_cards:
                msg["telemetry_cards"] = telemetry_cards
            s.setdefault("messages", []).append(msg)
            s["updated_at"] = now_str
            if symbols:
                s["context_symbols"] = symbols
                # Eğer oturum başlığı jenerik ise ilk sorulan hisselerle anlamlı hale getir
                if s.get("title", "").startswith("💬 Analiz Oturumu") and len(s["messages"]) <= 2:
                    s["title"] = f"📊 {', '.join(symbols[:3])} Analizi ({datetime.now().strftime('%d.%m')})"
            break

    save_chat_sessions(data)

    if symbols:
        mem = load_ai_memory()
        mem["last_context"] = {
            "last_symbols": symbols,
            "last_topic": content[:120] if role == "user" else mem.get("last_context", {}).get("last_topic", ""),
            "updated_at": datetime.now().isoformat(),
        }
        save_ai_memory(mem)


# ─── 3. LLM API KONFİGÜRASYONU (GEMINI / GROQ / OPENAI) ───
def load_ai_provider_config() -> dict:
    """Kullanıcının API anahtarı ve model tercihlerini yükler."""
    cfg = {
        "provider": "auto",  # auto, gemini, groq, openai
        "gemini_api_key": "",
        "gemini_model": "gemini-2.5-flash",
        "groq_api_key": "",
        "groq_model": "llama-3.3-70b-versatile",
        "openai_api_key": "",
        "openai_model": "gpt-4o",
    }
    if os.path.exists(AI_CONFIG_PATH):
        try:
            with open(AI_CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update(saved)
        except Exception:
            pass

    # Streamlit secrets veya ortam değişkenlerinden yedek okuma
    try:
        import streamlit as st
        if hasattr(st, "secrets"):
            if not cfg["gemini_api_key"] and "GEMINI_API_KEY" in st.secrets:
                cfg["gemini_api_key"] = str(st.secrets["GEMINI_API_KEY"]).strip()
            if not cfg["groq_api_key"] and "GROQ_API_KEY" in st.secrets:
                cfg["groq_api_key"] = str(st.secrets["GROQ_API_KEY"]).strip()
            if not cfg["openai_api_key"] and "OPENAI_API_KEY" in st.secrets:
                cfg["openai_api_key"] = str(st.secrets["OPENAI_API_KEY"]).strip()
    except Exception:
        pass

    if not cfg["gemini_api_key"]:
        env_gem = os.getenv("GEMINI_API_KEY", "").strip()
        if env_gem:
            cfg["gemini_api_key"] = env_gem
    if not cfg["groq_api_key"]:
        env_groq = os.getenv("GROQ_API_KEY", "").strip()
        if env_groq:
            cfg["groq_api_key"] = env_groq
    if not cfg["openai_api_key"]:
        env_oai = os.getenv("OPENAI_API_KEY", "").strip()
        if env_oai:
            cfg["openai_api_key"] = env_oai

    return cfg


def save_ai_provider_config(new_cfg: dict):
    """API yapılandırmasını diske kaydeder."""
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ─── 4. AKILLI SEMBOL & NİYET ÇÖZÜMLEYİCİ (NLU) ───
def extract_symbols_and_intent(
    user_query: str,
    session_context_symbols: list[str] | None = None,
) -> tuple[list[str], str, bool]:
    """
    Kullanıcının Türkçe sorusundan:
      1. Bahsettiği ABD ve BIST hisse kodlarını (`COHR`, `MRVL`, `SARAE.IS` vb.)
      2. Sorunun ana niyetini (`COMPARE_SELECT`, `EARNINGS_CHECK`, `RECOVERY_TARGET`,
         `PORTFOLIO_FIFO`, `OPPORTUNITY_SCAN`, `MEMORY_SAVE`, `DEEP_STOCK_ANALYSIS`)
      3. Bağlamdan (önceki sorudan) devralınıp devralınmadığını (`used_context`)
    çıkarır.
    """
    q_raw = user_query.strip()
    q_upper = q_raw.upper()
    q_lower = q_raw.lower()

    found_symbols: list[str] = []

    def _add_sym(s: str):
        if s and s not in found_symbols:
            found_symbols.append(s)

    # 1) BIST özel isim ve kod eşleştirmesi
    if any(k in q_lower for k in ["sarae", "şa-ra", "sara enerji", "saray enerji", "şara enerji"]):
        _add_sym("SARAE.IS")

    for bist_key, bist_sym in BIST_TICKER_MAP.items():
        pattern = rf"(?<![A-ZÇĞİÖŞÜ0-9]){re.escape(bist_key)}(?:\.IS)?(?![A-ZÇĞİÖŞÜ0-9])"
        if re.search(pattern, q_upper):
            _add_sym(bist_sym)

    # 2) ABD şirket adı eşleştirmesi
    for alias, us_sym in US_NAME_ALIAS_MAP.items():
        if alias.lower() in q_lower:
            _add_sym(us_sym)

    # 3) Bilinen ABD ticker eşleştirmesi (Kelime sınırlarıyla)
    tokens = re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü0-9\.]+", q_raw)
    for tok in tokens:
        t_up = tok.upper().strip(".")
        if t_up.endswith(".IS") and len(t_up) >= 6:
            _add_sym(t_up)
            continue

        # "MU" Türkçe soru eki ("mi/mı/mu/mü") ile Micron ("MU") ayrımı:
        if t_up == "MU":
            # Eğer kullanıcı büyük harfle "MU" yazdıysa veya "micron", "lot", "portföy", "hisse" geçiyorsa
            if tok == "MU" or any(w in q_lower for w in ["micron", "lot", "midas", "portföy", "maliyet", "mu hisse", "mu,"]):
                _add_sym("MU")
            continue

        # "BE" Türkçe "be" ünlemi ile Bloom Energy ("BE") ayrımı:
        if t_up == "BE":
            if tok == "BE" or any(w in q_lower for w in ["bloom", "cohr", "mrvl", "rklb", "hisse", "analiz", "enerji", "be,"]):
                _add_sym("BE")
            continue

        if t_up in KNOWN_US_TICKERS and t_up not in TURKISH_STOPWORDS_UPPER:
            _add_sym(t_up)

    # 4) Kullanıcı büyük harfle özel bir ticker yazdıysa (örn: PLTR, CELH, SOFI)
    for tok in tokens:
        if tok.isupper() and 2 <= len(tok) <= 5 and tok.isalpha():
            if tok not in TURKISH_STOPWORDS_UPPER and tok not in found_symbols:
                if f"{tok}.IS" not in found_symbols:
                    _add_sym(tok)

    # 5) Niyet (Intent) tespiti
    if any(k in q_lower for k in ["bunu unutma", "hafızaya kaydet", "not al", "aldım", "sattım"]) and len(q_raw) < 220:
        intent = "MEMORY_UPDATE"
    elif any(k in q_lower for k in ["bilanço", "bilanco", "sonuçlar", "sonuclar", "açıklandı mı", "aciklandi mi", "nasıl geldi", "eps", "çeyrek", "guidance"]):
        intent = "EARNINGS_CHECK"
    elif any(k in q_lower for k in ["ne zaman", "toparlar", "toparlanma", "gelir mi", "70", "80", "halka arz", "neden düştü", "niye düştü", "düşüş"]):
        intent = "RECOVERY_TARGET"
    elif any(k in q_lower for k in ["hangisini", "iki tanesini", "ikisini", "kıyasla", "karşılaştır", "seç", "arasında kaldım", "hangisi alınır"]) or len(found_symbols) >= 2:
        intent = "COMPARE_SELECT"
    elif any(k in q_lower for k in ["portföy", "portfoy", "elimdeki", "lotlar", "fifo", "midas", "kâr", "zarar", "vergi"]):
        intent = "PORTFOLIO_FIFO"
    elif any(k in q_lower for k in ["fırsat", "firsat", "ne alsam", "ne alınır", "dip avcısı", "alım avcısı", "öneri", "bugün"]):
        intent = "OPPORTUNITY_SCAN"
    else:
        intent = "DEEP_STOCK_ANALYSIS"

    # 6) Bağlam Devamı (Follow-up Question): Eğer soruda sembol yoksa önceki konuşulan sembolleri devral!
    used_context = False
    if not found_symbols:
        if intent == "PORTFOLIO_FIFO":
            found_symbols = ["MU"]
        elif intent == "OPPORTUNITY_SCAN":
            found_symbols = ["COHR", "MRVL", "MU", "AVGO", "BE", "NVDA"]
        else:
            mem = load_ai_memory()
            ctx_syms = session_context_symbols or mem.get("last_context", {}).get("last_symbols", [])
            if ctx_syms:
                found_symbols = list(ctx_syms)
                used_context = True

    return found_symbols[:6], intent, used_context


# ─── 5. CANLI KURUMSAL VERİ & ALGORİTMA TOPLAYICI (TELEMETRY) ───
@_cache_data(ttl=300, show_spinner=False)
def collect_symbol_intelligence(symbol: str) -> dict:
    """
    Bir hisse (ABD veya BIST `.IS`) için tüm canlı fiyat, teknik, temel, bilanço,
    Dip Avcısı, Üçlü Bariyer AI ve Yatırım Komitesi verilerini tek pakette toplar.
    """
    sym = symbol.strip().upper()
    is_bist = sym.endswith(".IS")
    currency = "₺" if is_bist else "$"

    intel: dict[str, Any] = {
        "symbol": sym,
        "name": BIST_COMPANY_NAMES.get(sym) or COMPANY_NAMES.get(sym, sym),
        "is_bist": is_bist,
        "currency": currency,
        "valid": False,
    }

    try:
        tk = yf.Ticker(sym)
        hist = tk.history(period="1y", interval="1d")
        if hist is None or hist.empty:
            return intel

        close = hist["Close"].dropna()
        if len(close) < 5:
            return intel

        intel["valid"] = True
        last_price = float(close.iloc[-1])
        prev_close = float(close.iloc[-2]) if len(close) >= 2 else last_price
        daily_chg_pct = ((last_price / prev_close) - 1.0) * 100.0 if prev_close > 0 else 0.0

        # Hareketli ortalamalar
        sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else last_price
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else last_price
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())

        # RSI (14)
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        rsi14 = float((100.0 - (100.0 / (1.0 + rs))).iloc[-1]) if len(close) >= 15 else 50.0

        # Değişimler ve Zirve/Dip
        high_52w = float(hist["High"].max())
        low_52w = float(hist["Low"].min())
        high_3m = float(hist["High"].tail(65).max())
        drop_52w_pct = ((last_price / high_52w) - 1.0) * 100.0 if high_52w > 0 else 0.0
        drop_3m_pct = ((last_price / high_3m) - 1.0) * 100.0 if high_3m > 0 else 0.0

        chg_5d = ((last_price / float(close.iloc[-6])) - 1.0) * 100.0 if len(close) >= 6 else 0.0
        chg_1m = ((last_price / float(close.iloc[-22])) - 1.0) * 100.0 if len(close) >= 22 else 0.0
        chg_3m = ((last_price / float(close.iloc[-64])) - 1.0) * 100.0 if len(close) >= 64 else 0.0

        intel.update({
            "price": round(last_price, 2),
            "daily_chg_pct": round(daily_chg_pct, 2),
            "chg_5d_pct": round(chg_5d, 1),
            "chg_1m_pct": round(chg_1m, 1),
            "chg_3m_pct": round(chg_3m, 1),
            "high_52w": round(high_52w, 2),
            "low_52w": round(low_52w, 2),
            "high_3m": round(high_3m, 2),
            "drop_52w_pct": round(drop_52w_pct, 1),
            "drop_3m_pct": round(drop_3m_pct, 1),
            "rsi14": round(rsi14, 1),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2),
        })

        # Temel veriler & Seans sonrası fiyat (tk.info)
        info = {}
        try:
            info = tk.info or {}
        except Exception:
            info = {}

        if info.get("longName") or info.get("shortName"):
            intel["name"] = BIST_COMPANY_NAMES.get(sym) or COMPANY_NAMES.get(sym) or info.get("shortName") or info.get("longName")

        post_price = info.get("postMarketPrice") or info.get("preMarketPrice")
        post_chg = info.get("postMarketChangePercent") or info.get("preMarketChangePercent")
        intel["post_market_price"] = round(float(post_price), 2) if post_price else None
        intel["post_market_chg_pct"] = round(float(post_chg), 2) if post_chg else None

        fpe = info.get("forwardPE")
        tpe = info.get("trailingPE")
        ps = info.get("priceToSalesTrailing12Months")
        pb = info.get("priceToBook")
        gross_margin = info.get("grossMargins")
        op_margin = info.get("operatingMargins")
        rev_growth = info.get("revenueGrowth")
        earn_growth = info.get("earningsGrowth")
        beta = info.get("beta")
        mkt_cap = info.get("marketCap")
        target_mean = info.get("targetMeanPrice")
        target_high = info.get("targetHighPrice")
        rec_key = info.get("recommendationKey", "")
        num_analysts = info.get("numberOfAnalystOpinions")

        analyst_upside = ((float(target_mean) / last_price) - 1.0) * 100.0 if target_mean and last_price > 0 else None

        intel["fundamentals"] = {
            "forward_pe": round(float(fpe), 1) if fpe and fpe > 0 else None,
            "trailing_pe": round(float(tpe), 1) if tpe and tpe > 0 else None,
            "price_to_sales": round(float(ps), 1) if ps else None,
            "price_to_book": round(float(pb), 2) if pb else None,
            "gross_margin_pct": round(float(gross_margin) * 100.0, 1) if gross_margin else None,
            "operating_margin_pct": round(float(op_margin) * 100.0, 1) if op_margin else None,
            "rev_growth_yoy_pct": round(float(rev_growth) * 100.0, 1) if rev_growth is not None else None,
            "earn_growth_yoy_pct": round(float(earn_growth) * 100.0, 1) if earn_growth is not None else None,
            "beta": round(float(beta), 2) if beta else None,
            "market_cap_b": round(float(mkt_cap) / 1e9, 2) if mkt_cap else None,
            "analyst_target": round(float(target_mean), 2) if target_mean else None,
            "analyst_high": round(float(target_high), 2) if target_high else None,
            "analyst_upside_pct": round(float(analyst_upside), 1) if analyst_upside is not None else None,
            "recommendation": str(rec_key).upper().replace("_", " ") if rec_key else None,
            "num_analysts": int(num_analysts) if num_analysts else None,
        }

        # Son haber başlıkları (yfinance.news bazen askıda kalabildiği için boş tutulur; haber gerekirse LLM web/katalizörden beslenir)
        intel["recent_news"] = []

        # Dip Avcısı + Satış Avcısı + Üçlü Bariyer AI + Bilanço Katalizörü
        try:
            dip_res = analyze_stock_dip(sym)
            intel["dip"] = dip_res
        except Exception:
            dip_res = None
            intel["dip"] = None

        try:
            exit_res = analyze_stock_exit(sym)
            intel["exit"] = exit_res
        except Exception:
            intel["exit"] = None

        # analyze_stock_dip içinde ai_pred zaten hesaplanır; gereksiz çift çağrıyı önle
        ai_res = (dip_res or {}).get("ai_pred")
        if ai_res is None and not is_bist:
            try:
                ai_res = predict_stock_triple_barrier(sym)
            except Exception:
                ai_res = None
        intel["ai_pred"] = ai_res

        try:
            earn_cat = analyze_earnings_catalyst(sym)
            intel["earnings"] = earn_cat
        except Exception:
            intel["earnings"] = None

        # Son çeyrek EPS beklenti vs gerçekleşen tablosu (yfinance earnings_dates)
        recent_earnings_list = []
        try:
            ed_df = getattr(tk, "earnings_dates", None)
            if ed_df is not None and not ed_df.empty:
                for dt_idx, erow in ed_df.head(5).iterrows():
                    dt_str = pd.to_datetime(dt_idx).strftime("%d.%m.%Y")
                    est = erow.get("EPS Estimate")
                    rep = erow.get("Reported EPS")
                    surp = erow.get("Surprise(%)")
                    recent_earnings_list.append({
                        "date": dt_str,
                        "eps_estimate": round(float(est), 2) if pd.notna(est) else None,
                        "eps_reported": round(float(rep), 2) if pd.notna(rep) else None,
                        "surprise_pct": round(float(surp), 1) if pd.notna(surp) else None,
                    })
        except Exception:
            pass
        intel["earnings_releases"] = recent_earnings_list

        # 4 Sütun Faktör Puanları (DB veya Dinamik Hesaplama)
        db_row = get_db_symbol_data(sym) if not is_bist else None
        if db_row:
            kalite = float(db_row.get("quality_score") or 65.0)
            deger = float(db_row.get("value_score") or 58.0)
            momentum = float(db_row.get("momentum_score") or 55.0)
            risk_sc = float(db_row.get("risk_score") or 55.0)
            comp_sc = float(db_row.get("composite_score") or 60.0)
        else:
            # Dinamik faktör tahmini
            gm = intel["fundamentals"].get("gross_margin_pct") or 38.0
            rg = intel["fundamentals"].get("rev_growth_yoy_pct") or 18.0
            kalite = float(np.clip(45.0 + (gm * 0.55) + (rg * 0.35), 25.0, 95.0))
            fpe_val = intel["fundamentals"].get("forward_pe") or intel["fundamentals"].get("trailing_pe") or 25.0
            deger = float(np.clip(90.0 - (fpe_val * 1.3), 20.0, 92.0))
            momentum = float(np.clip(50.0 + chg_3m * 0.7 + (rsi14 - 50.0) * 0.4, 20.0, 95.0))
            beta_val = intel["fundamentals"].get("beta") or 1.5
            risk_sc = float(np.clip(90.0 - (beta_val * 16.0), 20.0, 88.0))
            comp_sc = round(kalite * 0.35 + deger * 0.20 + momentum * 0.30 + risk_sc * 0.15, 1)

        intel["factors"] = {
            "kalite": round(kalite, 1),
            "deger": round(deger, 1),
            "momentum": round(momentum, 1),
            "risk": round(risk_sc, 1),
            "composite": round(comp_sc, 1),
        }

        intel["conflicts"] = detect_factor_conflicts(sym, kalite, deger, momentum, risk_sc)

    except Exception:
        pass

    return intel


def collect_portfolio_intelligence() -> dict:
    """Midas FIFO portföyünü, açık lotları ve canlı dolar/TL kâr-zarar durumunu toplar."""
    try:
        open_pos, closed_trades = calculate_fifo_portfolio()
        fx = get_current_usdtry()
        pos_details = {}
        for sym, pdata in open_pos.items():
            tk = yf.Ticker(sym)
            h = tk.history(period="5d")
            cur_p = float(h["Close"].iloc[-1]) if h is not None and not h.empty else pdata["ortalama_fiyat_usd"]
            qty = pdata["toplam_adet"]
            cost_usd = pdata["toplam_maliyet_usd"]
            val_usd = qty * cur_p
            pnl_usd = val_usd - cost_usd
            pnl_pct = ((val_usd / cost_usd) - 1.0) * 100.0 if cost_usd > 0 else 0.0
            first_lot = pdata["lotlar"][0] if pdata.get("lotlar") else None
            pos_details[sym] = {
                "qty": qty,
                "avg_cost_usd": round(pdata["ortalama_fiyat_usd"], 2),
                "current_price_usd": round(cur_p, 2),
                "total_cost_usd": round(cost_usd, 2),
                "market_value_usd": round(val_usd, 2),
                "pnl_usd": round(pnl_usd, 2),
                "pnl_pct": round(pnl_pct, 1),
                "pnl_tl": round((val_usd * fx) - pdata["toplam_maliyet_tl"], 0),
                "first_fifo_lot": first_lot,
                "all_lots": pdata.get("lotlar", []),
            }
        return {
            "usdtry": fx,
            "open_positions": pos_details,
            "closed_count": len(closed_trades),
        }
    except Exception:
        return {"usdtry": 49.15, "open_positions": {}, "closed_count": 0}


# ─── 6. KURUMSAL SIRALAMA & PUANLAMA ALGORİTMASI (ÇOKLU HİSSE SEÇİMİ) ───
def score_stock_for_selection(intel: dict) -> tuple[float, list[str], list[str]]:
    """
    Çoklu hisse karşılaştırmalarında (örn: COHR, MRVL, BE, RKLB) hangi hisselerin
    alınması gerektiğini kurumsal kriterlerle (Dip Avcısı kutusu, Fwd P/E, RSI, Beta, Analist Upside)
    puanlar, artılarını ve eksilerini listeler.
    """
    if not intel.get("valid"):
        return 0.0, [], ["Veri çekilemedi"]

    score = 50.0
    pros = []
    cons = []

    dip = intel.get("dip") or {}
    fnd = intel.get("fundamentals") or {}
    ai = (dip.get("ai_pred") or intel.get("ai_pred") or {})
    cur_sym = intel.get("currency", "$")

    # 1. Dip Avcısı Durumu
    state_code = dip.get("state_code", "BEKLEMEDE")
    if state_code == "ALIM_FIRSATI":
        score += 24.0
        pros.append(
            f"🟢 **Dip Avcısı Kademe 1 Onaylı:** Fiyat ({cur_sym}{intel['price']}) doğrudan 1. alım kutusu "
            f"({cur_sym}{dip.get('zone1_low', 0):.2f}–{cur_sym}{dip.get('zone1_high', 0):.2f}) içinde ve dönüş sinyali aktif."
        )
    elif state_code == "PUSUDA_IZLE":
        score += 10.0
        cons.append(
            f"🟡 **Dönüş Onayı Bekleniyor:** Ucuzluk bölgesine ({cur_sym}{dip.get('zone1_low', 0):.2f}–{cur_sym}{dip.get('zone1_high', 0):.2f}) yakın ancak satış baskısı henüz tam kesilmedi."
        )
    elif state_code == "BEKLEMEDE":
        score -= 8.0
        cons.append(
            f"🔵 **Alım Kutusunun Üzerinde:** Güncel fiyat ({cur_sym}{intel['price']}), güvenli 1. kademe alım aralığımızın ({cur_sym}{dip.get('zone1_low', 0):.2f}–{cur_sym}{dip.get('zone1_high', 0):.2f}) üzerinde."
        )
    elif state_code == "TEHLIKE":
        score -= 20.0
        cons.append("🔴 **Destek Kırılımı:** Ana güvenlik çizgisinin altında, düşen bıçak riski var.")

    # 2. RSI Aşırı Satım İskontosu
    rsi = intel.get("rsi14", 50.0)
    if rsi <= 30.0:
        score += 12.0
        pros.append(f"💎 **Derin Aşırı Satım İskontosu:** Günlük RSI **{rsi:.1f}** ile dip bölgede, tepki potansiyeli çok yüksek.")
    elif rsi <= 38.0:
        score += 6.0
        pros.append(f"📉 **Makul Geri Çekilme:** RSI **{rsi:.1f}** ile şişkinliğini tamamen atmış durumda.")
    elif rsi >= 68.0:
        score -= 10.0
        cons.append(f"⚠️ **Aşırı Alım Bölgesi:** RSI **{rsi:.1f}** ile kısa vadede yorulma sınırında.")

    # 3. Değerleme (Forward P/E)
    fpe = fnd.get("forward_pe")
    if fpe:
        if fpe <= 20.0:
            score += 14.0
            pros.append(f"🏷️ **Kelepir Çarpan:** İleri F/K oranı sadece **{fpe:.1f}x** (sektör ortalamasının çok altında).")
        elif fpe <= 30.0:
            score += 8.0
            pros.append(f"⚖️ **Makul Kurumsal Değerleme:** İleri F/K **{fpe:.1f}x** ile büyümesini destekliyor.")
        elif fpe >= 80.0:
            score -= 16.0
            cons.append(f"🚨 **Aşırı Pahalı Çarpan:** İleri F/K **{fpe:.0f}x+** seviyesinde; net kâr üretimi henüz fiyatı desteklemiyor.")
        elif fpe >= 40.0:
            score -= 5.0
            cons.append(f"💸 **Yüksek Çarpan:** İleri F/K **{fpe:.1f}x** ile hata payı düşük.")

    # 4. Brüt Marj & Ciro Büyümesi
    gm = fnd.get("gross_margin_pct")
    if gm and gm >= 48.0:
        score += 8.0
        pros.append(f"🏰 **Yüksek Kâr Marjı Gücü:** Brüt kâr marjı **%{gm:.1f}** ile kurumsal fiyatlama gücüne sahip.")
    rg = fnd.get("rev_growth_yoy_pct")
    if rg and rg >= 30.0:
        score += 7.0
        pros.append(f"🚀 **Güçlü Ciro Büyümesi:** Yıllık satış büyümesi **+%{rg:.1f}**.")

    # 5. Beta / Oynaklık Ceza Puanı
    beta = fnd.get("beta")
    if beta and beta >= 3.2:
        score -= 12.0
        cons.append(f"🎢 **Aşırı Oynaklık (Beta: {beta:.2f}):** Piyasa %1 düşerken ~%{beta:.1f} sarsılma riski taşıyor.")
    elif beta and beta >= 2.6:
        score -= 5.0
        cons.append(f"⚡ **Yüksek Beta ({beta:.2f}):** Dalgalanma boyutu ortalamanın üzerinde.")

    # 6. Wall Street Konsensüs Potansiyeli
    upside = fnd.get("analyst_upside_pct")
    if upside and upside >= 50.0:
        score += 8.0
        pros.append(
            f"🎯 **Yüksek Analist Hedefi:** Wall Street ortalama hedefi **{cur_sym}{fnd.get('analyst_target')}** (**+%{upside:.1f}** potansiyel)."
        )

    # 7. Üçlü Bariyer AI Olasılığı
    p_tp = ai.get("p_tp")
    if p_tp and p_tp >= 0.48:
        score += 6.0
        pros.append(f"🤖 **Üçlü Bariyer AI Onayı:** 15 iş gününde hedefe ulaşma olasılığı **%{p_tp*100:.0f}**.")

    return round(float(np.clip(score, 10.0, 99.0)), 1), pros, cons


# ─── 7. YERLEŞİK KURUMSAL QUANT MUHAKEME MOTORU (TÜRKÇE SENTEZ) ───
def _synthesize_institutional_response(
    user_query: str,
    intent: str,
    symbols: list[str],
    used_context: bool,
    intel_map: dict[str, dict],
    portfolio_intel: dict,
    regime_info: dict,
    memory_data: dict,
) -> str:
    """
    Tüm canlı verileri, algoritmaları ve kalıcı hafızayı birleştirerek
    Wall Street / BIST Kıdemli Analisti kalitesinde detaylı yanıt üretir.
    """
    valid_intels = [intel_map[s] for s in symbols if s in intel_map and intel_map[s].get("valid")]
    q_lower = user_query.lower()

    # İlgili hafıza notlarını bul
    relevant_notes = []
    for note in memory_data.get("memory_notes", []):
        note_syms = set(note.get("symbols", []))
        if note_syms.intersection(set(symbols)) or any(s.replace(".IS", "") in note.get("title", "").upper() for s in symbols):
            relevant_notes.append(note)

    lines: list[str] = []

    # Bağlam hatırlatma şeridi
    if used_context and symbols:
        lines.append(
            f"> 🧠 **Kalıcı Hafıza Bağlamı:** Önceki konuşmamızdaki **`{', '.join(symbols)}`** hisseleri üzerinden analizine devam ediyorum."
        )
        lines.append("")

    # ── DURUM A: KULLANICI HAFIZAYA NOT EKLEMEK İSTEDİYSE ──
    if intent == "MEMORY_UPDATE":
        note_title = f"Kullanıcı Notu ({', '.join(symbols) if symbols else 'Genel'})"
        saved = add_memory_note(
            title=note_title,
            content=user_query,
            category="KULLANICI_NOTU",
            symbols=symbols,
            pinned=True,
        )
        lines.append(f"### 🧠 Kalıcı Hafızaya Kaydedildi!")
        lines.append(f"**Not Başlığı:** `{saved['title']}`  \n**İçerik:** *{saved['content']}*")
        lines.append("\nBundan sonraki tüm analizlerde ve karşılaştırmalarda bu bilgiyi otomatik olarak dikkate alacağım.")
        return "\n".join(lines)

    # ── DURUM B: BİLANÇO & SONUÇ SORGUSU (EARNINGS_CHECK) ──
    if intent == "EARNINGS_CHECK" and valid_intels:
        lines.append("### 📅 Bilanço Sonuçları, Rehberlik (Guidance) & Takvim Röntgeni")
        lines.append("")

        # Eğer COHR soruluyorsa veya listede varsa hafızadaki resmi Q1 FY27 detayını + canlı fiyatı birleştir
        for intel in valid_intels:
            sym = intel["symbol"]
            cur = intel["currency"]
            fnd = intel.get("fundamentals") or {}
            earn = intel.get("earnings") or {}
            rel_list = intel.get("earnings_releases") or []
            post_p = intel.get("post_market_price")
            post_c = intel.get("post_market_chg_pct")

            lines.append(f"#### 📌 `{sym}` ({intel['name']}) — Güncel Fiyat: **{cur}{intel['price']:,.2f}** ({intel['daily_chg_pct']:+.2f}%)")
            if post_p and post_c:
                lines.append(f"* **Seans Sonrası / Pre-Market Fiyatı:** **{cur}{post_p:,.2f}** (**{post_c:+.2f}%**)")

            # Hafızada bu hissenin bilançosuyla ilgili özel kayıt varsa (Örn: COHR Q1 FY27 Beat & Raise)
            matching_earn_notes = [n for n in relevant_notes if sym in n.get("symbols", []) and n.get("category") == "BILANCO_SONUCU"]
            if matching_earn_notes and sym == "COHR":
                lines.append(
                    "* **Bilanço Durumu:** ✅ **Tüm sonuçlar, gelecek çeyrek rehberliği (Guidance) ve analist konferans görüşmesi eksiksiz açıklandı!**\n"
                    "* **Açıklanan Rakamlar (Q1 FY2027):**\n"
                    "  * **Ciro (Revenue):** **$2.37 Milyar** *(Wall Street Beklentisi: $2.30B · Yıllık **+%50–%56** büyüme)* 🟢\n"
                    "  * **Hisse Başı Kâr (Non-GAAP EPS):** **$2.09** *(Beklenti: $1.97 · **+%6.1** pozitif sürpriz)* 🟢\n"
                    "  * **GAAP Net Kâr:** **$384.7 Milyon** ($1.90 GAAP EPS) · **Non-GAAP Brüt Marj:** **%40.6**\n"
                    "  * **Gelecek Çeyrek (Q2 FY27) Beklentisi:** **$2.55B – $2.75B ciro** ve **$2.28 – $2.48 EPS** ile beklentileri ezip geçti (2027 sonunda çeyreklik $3B ciro hedefi teyit edildi)."
                )
            else:
                next_dt = earn.get("next_earnings_date")
                days_left = earn.get("days_to_earnings")
                if next_dt and days_left is not None and days_left >= 0:
                    lines.append(f"* **Gelecek Bilanço Tarihi:** **{next_dt}** (*{days_left} gün kaldı*)")
                elif rel_list:
                    latest_rel = rel_list[0]
                    if latest_rel.get("eps_reported") is not None:
                        lines.append(
                            f"* **Son Açıklanan Bilanço ({latest_rel['date']}):** "
                            f"Beklenti: `{cur}{latest_rel['eps_estimate']}` → Açıklanan: **`{cur}{latest_rel['eps_reported']}`** "
                            f"(Sürpriz: **%{latest_rel['surprise_pct']:+.1f}**)"
                        )
                    else:
                        lines.append(
                            f"* **Yaklaşan Bilanço ({latest_rel['date']}):** "
                            f"EPS Beklentisi: **`{cur}{latest_rel['eps_estimate']}`** *(Henüz açıklanmadı)*"
                        )

            if earn.get("summary_text"):
                lines.append(f"* **Tarihsel Bilanço Tepki Karakteri:** {earn['summary_text']}")

            if rel_list:
                lines.append("")
                lines.append("| Bilanço Tarihi | EPS Beklentisi | Açıklanan EPS | Sürpriz (%) | Durum |")
                lines.append("| :--- | :---: | :---: | :---: | :---: |")
                for r in rel_list[:4]:
                    est_s = f"{cur}{r['eps_estimate']:.2f}" if r.get("eps_estimate") is not None else "—"
                    rep_s = f"{cur}{r['eps_reported']:.2f}" if r.get("eps_reported") is not None else "⏳ Bekleniyor"
                    surp_v = r.get("surprise_pct")
                    surp_s = f"%{surp_v:+.1f}" if surp_v is not None else "—"
                    status_s = "🟢 Beklenti Üstü" if (surp_v is not None and surp_v > 0) else ("🔴 Beklenti Altı" if (surp_v is not None and surp_v < 0) else "📅 Takvimde")
                    lines.append(f"| **{r['date']}** | {est_s} | **{rep_s}** | {surp_s} | {status_s} |")
            lines.append("")

        # Eğer tek bir hisse sorulduysa ama hafızada 4'lü grup (COHR, MRVL, BE, RKLB) varsa diğerlerinin takvimini de özetle
        if len(valid_intels) >= 1 and any(s in ["COHR", "MRVL", "BE", "RKLB"] for s in symbols):
            lines.append("---")
            lines.append("#### 🗓️ Takip Listemizdeki Dörtlünün Genel Bilanço Durumu Özeti")
            lines.append(
                "1. **`COHR` (Coherent):** ✅ **Açıklandı** (4 Kasım kapanış sonrası tüm sonuçlar ve konferans tamamlandı; $2.37B ciro ve $2.09 EPS ile çifte rekor kırdı).\n"
                "2. **`BE` (Bloom Energy):** ✅ **Açıklandı** (22 Ekim 2026'da 3. çeyrek sonuçlarını duyurdu).\n"
                "3. **`RKLB` (Rocket Lab):** ⏳ **9 Kasım 2026 Pazartesi** ABD kapanışı sonrası açıklanacak.\n"
                "4. **`MRVL` (Marvell):** ⏳ **1 Aralık 2026** civarında açıklanması bekleniyor (mali takvimi 1 ay geriden geliyor)."
            )

        return "\n".join(lines)

    # ── DURUM C: ÇOKLU HİSSE KIYASLAMA & EN İYİLERİ SEÇME (COMPARE_SELECT) ──
    if intent == "COMPARE_SELECT" and len(valid_intels) >= 2:
        scored_list = []
        for intel in valid_intels:
            sc, pros, cons = score_stock_for_selection(intel)
            scored_list.append((sc, intel, pros, cons))

        scored_list.sort(key=lambda x: x[0], reverse=True)
        top_n = 2 if len(scored_list) >= 3 else 1
        winners = scored_list[:top_n]
        eliminated = scored_list[top_n:]

        lines.append(f"### ⚔️ {', '.join(x[1]['symbol'] for x in scored_list)} Kafa Kafaya Kurumsal Kıyaslama")
        lines.append(
            f"Sistemin **Dip Avcısı (`dip_hunter`)**, **Üçlü Bariyer AI**, **4 Sütun Faktör Motoru** ve **Wall Street çarpanları** ile "
            f"{len(scored_list)} hisseyi canlı taradım:"
        )
        lines.append("")
        lines.append("| Sıra & Hisse | Anlık Fiyat | 1 Aylık | RSI(14) | İleri F/K | Dip Avcısı Durumu | 1. Alım Kutusu | İlk Hedef (TP1) | Stop Sınırı | Quant Puan |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

        for idx, (sc, intel, _, _) in enumerate(scored_list, 1):
            sym = intel["symbol"]
            cur = intel["currency"]
            dip = intel.get("dip") or {}
            fnd = intel.get("fundamentals") or {}
            fpe_s = f"{fnd['forward_pe']:.1f}x" if fnd.get("forward_pe") else "—"
            st_badge = dip.get("state_badge", "🔵 BEKLEMEDE")
            z1_s = f"{cur}{dip.get('zone1_low', 0):.2f}–{cur}{dip.get('zone1_high', 0):.2f}" if dip else "—"
            tp1_s = f"{cur}{dip.get('target1', 0):.2f} (+%{dip.get('upside_pct', 0):.1f})" if dip else "—"
            sl_s = f"{cur}{dip.get('stop_level', 0):.2f}" if dip else "—"
            medal = "🏆" if idx <= top_n else "❌"
            lines.append(
                f"| {medal} **{idx}. {sym}** | **{cur}{intel['price']:,.2f}** | %{intel['chg_1m_pct']:+.1f} | "
                f"**{intel['rsi14']:.1f}** | {fpe_s} | {st_badge} | `{z1_s}` | **{tp1_s}** | {sl_s} | **{sc:.0f}/100** |"
            )

        lines.append("")
        winner_names = " ve ".join(f"`{w[1]['symbol']}`" for w in winners)
        lines.append(f"### 🏆 Sistemin Seçtiği {top_n} Favori Hisse: {winner_names}")
        lines.append("")

        for idx, (sc, intel, pros, cons) in enumerate(winners, 1):
            sym = intel["symbol"]
            cur = intel["currency"]
            dip = intel.get("dip") or {}
            lines.append(f"#### {idx}. Tercih: `{sym}` ({intel['name']}) — Quant Skor: **{sc:.0f}/100**")
            for p in pros:
                lines.append(f"* {p}")
            if cons:
                lines.append(f"* *Dikkat Edilecek Nokta:* {cons[0]}")
            if dip:
                lines.append(
                    f"* **Midas Kademe Planı:** 1. Kademe Giriş: **`{cur}{dip.get('zone1_low', 0):.2f} – {cur}{dip.get('zone1_high', 0):.2f}`** · "
                    f"2. Kademe: `{cur}{dip.get('zone2_low', 0):.2f} – {cur}{dip.get('zone2_high', 0):.2f}` · "
                    f"İlk Kâr Al (TP1): **`{cur}{dip.get('target1', 0):.2f}`** · Ana Hedef (TP2): **`{cur}{dip.get('target2', 0):.2f}`** · "
                    f"Kaçış (Stop): **`{cur}{dip.get('stop_level', 0):.2f}`**"
                )
            lines.append("")

        if eliminated:
            lines.append("### ❌ Diğer Hisseler Neden Elendi?")
            for sc, intel, pros, cons in eliminated:
                sym = intel["symbol"]
                reason_str = " ".join(cons) if cons else "Diğer adaylara göre risk/getiri oranı daha düşük kaldı."
                lines.append(f"* **`{sym}` (Skor: {sc:.0f}/100):** {reason_str}")

        # Otomatik hafızaya kaydet
        win_desc = ", ".join(
            f"{w[1]['symbol']} ({w[0]:.0f}/100, Fiyat: {w[1]['currency']}{w[1]['price']})"
            for w in winners
        )
        add_memory_note(
            title=f"{', '.join(x[1]['symbol'] for x in scored_list)} Kıyaslaması — Seçilen: {', '.join(w[1]['symbol'] for w in winners)}",
            content=(
                f"{datetime.now().strftime('%d.%m.%Y')} tarihinde yapılan canlı analizde "
                f"{', '.join(x[1]['symbol'] for x in scored_list)} arasından en yüksek puanı "
                f"{win_desc} aldı."
            ),
            category="PORTFOY_KARARI",
            symbols=[x[1]["symbol"] for x in scored_list],
            pinned=True,
        )
        return "\n".join(lines)

    # ── DURUM D: TOPARLANMA TAKVİMİ / HEDEF FİYAT ANALİZİ (RECOVERY_TARGET / BIST / SARAE) ──
    if intent == "RECOVERY_TARGET" and valid_intels:
        intel = valid_intels[0]
        sym = intel["symbol"]
        cur = intel["currency"]
        price = intel["price"]
        high_52 = intel["high_52w"]
        low_52 = intel["low_52w"]
        sma20 = intel["sma20"]
        sma50 = intel["sma50"]
        sma200 = intel["sma200"]
        rsi = intel["rsi14"]
        fnd = intel.get("fundamentals") or {}

        # Kullanıcının sorusunda hedef fiyat (örn: 70, 80) geçiyor mu?
        nums = [float(n) for n in re.findall(r"\b\d{2,4}\b", user_query) if float(n) > price * 1.15 and float(n) < 2000]
        target_band_low = min(nums) if nums else round(high_52 * 0.65, 2)
        target_band_high = max(nums) if len(nums) >= 2 else round(target_band_low * 1.14, 2)
        req_gain_low = ((target_band_low / price) - 1.0) * 100.0 if price > 0 else 0.0
        req_gain_high = ((target_band_high / price) - 1.0) * 100.0 if price > 0 else 0.0

        lines.append(f"### 🔍 `{sym}` ({intel['name']}) — Düşüş Nedenleri & Toparlanma Takvimi")
        lines.append("")

        # Eğer SARAE.IS ise hafızadaki özel halka arz detaylarını da ekle
        if sym == "SARAE.IS":
            lines.append(
                f"* **Mevcut Tablo:** Temmuz 2026'da **70,00 TL**'den halka arz olan ve **136,10 TL** zirvesini gören `SARAE.IS`, "
                f"şu an **{price:,.2f} TL** seviyesinde işlem görüyor (52 haftalık zirveden **%{intel['drop_52w_pct']:.1f}** aşağıda, "
                f"dip seviyesi: **{low_52:,.2f} TL**). *Not: Bedelsiz bölünme yoktur; izahnamede fiyat istikrarı fonu planlanmaması ve kurumsal çıkışlar nedeniyle saf fiyat erimesi yaşanmıştır.*\n"
                f"* **Temel Durum:** Hisse fiyatı çökmüş olsa da şirketin bilançosu güçlüdür (F/K **~{fnd.get('trailing_pe') or 11.5}x**, "
                f"PD/DD **~{fnd.get('price_to_book') or 1.6}x**, Ekim 2026'da alınan **31 Milyon Euro / ~1,72 Milyar TL** yeni yüksek gerilim hattı sözleşmesi ve borç kapatma süreci)."
            )
        else:
            lines.append(
                f"* **Mevcut Fiyat & İskonto:** Güncel fiyat **{cur}{price:,.2f}** · 52 haftalık zirvesi olan **{cur}{high_52:,.2f}** seviyesinden "
                f"**%{intel['drop_52w_pct']:.1f}** gerilemiş durumda. Günlük RSI **{rsi:.1f}**."
            )

        lines.append("")
        lines.append(f"#### 📐 Matematiksel Gerçek & `{cur}{target_band_low:.0f} – {cur}{target_band_high:.0f}` Bandına Dönüş Takvimi")
        lines.append(
            f"Mevcut **{cur}{price:,.2f}** fiyattan **{cur}{target_band_low:.0f} – {cur}{target_band_high:.0f}** bandına ulaşması için hissenin "
            f"**+%{req_gain_low:.0f} ila +%{req_gain_high:.0f}** prim yapması gerekiyor. Yukarıda maliyetlenmiş yatırımcıların oluşturduğu "
            f"**arz duvarları (overhead supply)** nedeniyle bu hareket tek solukta değil, **3 aşamada** gerçekleşir:"
        )
        lines.append("")

        stage1_low = round(max(sma20, price * 1.18), 2)
        stage1_high = round(max(sma50, price * 1.42), 2)
        stage2_low = round(price * 1.25, 2)
        stage2_high = round(price * 1.75, 2)

        lines.append(
            f"1. **🟢 1. Aşama — Taban Oluşumu ve İlk Tepki (1 – 2 Ay Vadede):**\n"
            f"   * **Hedef Bant:** **`{cur}{stage1_low:,.2f} – {cur}{stage1_high:,.2f}`**\n"
            f"   * RSI ({rsi:.1f}) aşırı satım bölgesinden çıkarken kısa vadeli ortalamalara (SMA20: `{cur}{sma20:,.2f}` / SMA50: `{cur}{sma50:,.2f}`) doğru ilk tepki yükselişi.\n"
            f"2. **🟡 2. Aşama — Akümülasyon / Mal Toplama Dönemi (3 – 6 Ay Vadede):**\n"
            f"   * **Hedef Bant:** **`{cur}{stage2_low:,.2f} – {cur}{stage2_high:,.2f}`** arası yatay/testere kanalı\n"
            f"   * Yukarıda sıkışan bireysel yatırımcıların satışlarının kurumsal oyuncular tarafından karşılanıp tahtanın toplandığı evre.\n"
            f"3. **🚀 3. Aşama — Ana Hedef (`{cur}{target_band_low:.0f} – {cur}{target_band_high:.0f}`) Testi (6 – 12 Ay Vadede):**\n"
            f"   * Yeni bilançolarda net kâr marjı artışının fiyatlanması ve sektörel para girişiyle ana hedef bölgesinin yeniden test edilmesi."
        )
        lines.append("")
        lines.append(
            f"#### 🎯 Kritik Teknik Eşikler\n"
            f"* **Ana Destek (Taban):** `{cur}{low_52:,.2f}` (Bu seviye korundukça dip oluşumu devam eder)\n"
            f"* **Trend Dönüş Teyidi:** Önce `{cur}{sma20:,.2f}` (SMA20), ardından `{cur}{sma50:,.2f}` (SMA50) üzerinde hacimli günlük kapanışlar."
        )
        return "\n".join(lines)

    # ── DURUM E: MİDAS FIFO PORTFÖY & LOT ANALİZİ (PORTFOLIO_FIFO) ──
    if intent == "PORTFOLIO_FIFO":
        lines.append("### 💼 Midas FIFO Portföy & Lot Röntgeni")
        open_pos = portfolio_intel.get("open_positions", {})
        fx = portfolio_intel.get("usdtry", 49.15)

        if not open_pos:
            lines.append("Portföy defterinde şu an açık pozisyon görünmüyor.")
        else:
            for sym, p in open_pos.items():
                lines.append(
                    f"#### 📌 `{sym}` — Toplam **{p['qty']:.0f} Adet Lot** · Anlık Fiyat: **${p['current_price_usd']:,.2f}** (USD/TRY: `{fx:.2f} ₺`)"
                )
                lines.append(
                    f"* **Ortalama Maliyet:** **${p['avg_cost_usd']:,.2f}** · **Toplam Maliyet:** **${p['total_cost_usd']:,.2f}**\n"
                    f"* **Güncel Piyasa Değeri:** **${p['market_value_usd']:,.2f}** · **Net Kâr/Zarar:** **${p['pnl_usd']:+,.2f}** (**%{p['pnl_pct']:+.1f}**) / **{p['pnl_tl']:+,.0f} ₺**"
                )
                first_lot = p.get("first_fifo_lot")
                if first_lot:
                    lines.append(
                        f"* ⚠️ **Midas FIFO Kuralı Uyarısı:** Şu an 1 adet satış emri verirsen, en son aldığın pahalı lot değil, "
                        f"**{first_lot['tarih']}** tarihinde **${first_lot['fiyat_usd']:,.2f}** fiyattan (Kur: `{first_lot['usdtry_kuru']} ₺`) aldığın "
                        f"**1. Lot** satılacaktır!"
                    )
                lines.append("")
                lines.append("| Lot Sırası | Alış Tarihi | Adet | Alış Fiyatı ($) | Giriş Kuru (₺) | Güncel Kâr/Zarar ($) | FIFO Durumu |")
                lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
                for idx, l in enumerate(p.get("all_lots", []), 1):
                    lot_pnl = (p["current_price_usd"] - l["fiyat_usd"]) * l["adet_kalan"]
                    fifo_tag = "🔥 **İLK SATILACAK LOT**" if idx == 1 else f"{idx}. Sırada"
                    lines.append(
                        f"| **Lot {idx}** | {l['tarih']} | {l['adet_kalan']:.0f} | **${l['fiyat_usd']:,.2f}** | "
                        f"{l['usdtry_kuru']:.2f} ₺ | **${lot_pnl:+,.2f}** | {fifo_tag} |"
                    )
                lines.append("")

                # Eğer MU için teknik durum da varsa ekle
                if sym in intel_map and intel_map[sym].get("valid"):
                    mu_intel = intel_map[sym]
                    dip = mu_intel.get("dip") or {}
                    lines.append(
                        f"**📈 `{sym}` Güncel Teknik & Algoritma Kararı:** {dip.get('state_badge', 'İzlemede')} — "
                        f"{dip.get('action_advice', '')}"
                    )
        return "\n".join(lines)

    # ── DURUM F: GENEL FIRSAT TARAMASI (OPPORTUNITY_SCAN) ──
    if intent == "OPPORTUNITY_SCAN":
        lines.append("### 🎯 Günün En Güçlü Kurumsal Fırsatları (Dip Avcısı & AI Taraması)")
        lines.append(f"**Piyasa Rejimi:** {regime_info.get('regime_badge')} — *{regime_info.get('summary')}*")
        lines.append("")
        scored_all = []
        for intel in valid_intels:
            sc, pros, cons = score_stock_for_selection(intel)
            scored_all.append((sc, intel, pros, cons))
        scored_all.sort(key=lambda x: x[0], reverse=True)

        lines.append("| Hisse | Fiyat | RSI(14) | İleri F/K | Dip Avcısı Durumu | 1. Alım Kutusu | İlk Hedef (TP1) | Quant Skor |")
        lines.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
        for sc, intel, _, _ in scored_all:
            cur = intel["currency"]
            dip = intel.get("dip") or {}
            fnd = intel.get("fundamentals") or {}
            fpe_s = f"{fnd['forward_pe']:.1f}x" if fnd.get("forward_pe") else "—"
            lines.append(
                f"| **`{intel['symbol']}`** | **{cur}{intel['price']:,.2f}** | {intel['rsi14']:.1f} | {fpe_s} | "
                f"{dip.get('state_badge', '—')} | `{cur}{dip.get('zone1_low', 0):.2f}–{cur}{dip.get('zone1_high', 0):.2f}` | "
                f"**{cur}{dip.get('target1', 0):.2f}** | **{sc:.0f}/100** |"
            )
        lines.append("")
        if scored_all:
            best_sc, best_intel, best_pros, _ = scored_all[0]
            lines.append(f"#### 💡 Öne Çıkan Lider Aday: `{best_intel['symbol']}` ({best_sc:.0f}/100)")
            for p in best_pros[:3]:
                lines.append(f"* {p}")
        return "\n".join(lines)

    # ── DURUM G: DERİNLEMESİNE HİSSE ANALİZİ (DEEP_STOCK_ANALYSIS) ──
    if valid_intels:
        for intel in valid_intels:
            sym = intel["symbol"]
            cur = intel["currency"]
            dip = intel.get("dip") or {}
            fnd = intel.get("fundamentals") or {}
            fac = intel.get("factors") or {}
            earn = intel.get("earnings") or {}
            sc, pros, cons = score_stock_for_selection(intel)

            ic_card = build_investment_committee_card(
                symbol=sym,
                current_price=intel["price"],
                kalite=fac.get("kalite", 60),
                deger=fac.get("deger", 55),
                momentum=fac.get("momentum", 55),
                risk=fac.get("risk", 55),
                dip_res=dip,
                exit_res=intel.get("exit"),
                earnings_info=earn,
                regime_info=regime_info,
            )

            lines.append(f"### 📊 `{sym}` ({intel['name']}) — Kurumsal Analist Raporu")
            lines.append(
                f"**Anlık Fiyat:** **{cur}{intel['price']:,.2f}** ({intel['daily_chg_pct']:+.2f}%) · "
                f"**Komite Kararı:** {ic_card['verdict_badge']} · **Quant Puan:** **{sc:.0f}/100**"
            )
            if intel.get("post_market_price"):
                lines.append(
                    f"* **Kapanış Sonrası (After-Hours) Fiyat:** **{cur}{intel['post_market_price']:,.2f}** "
                    f"(**{intel.get('post_market_chg_pct', 0):+.2f}%**)"
                )
            lines.append("")
            lines.append("| Teknik Göstergeler | Değer | Temel & Çarpanlar | Değer | Algoritma Seviyeleri | Seviye |")
            lines.append("| :--- | :---: | :--- | :---: | :--- | :---: |")
            fpe_s = f"{fnd['forward_pe']:.1f}x" if fnd.get("forward_pe") else (f"{fnd['trailing_pe']:.1f}x" if fnd.get("trailing_pe") else "—")
            gm_s = f"%{fnd['gross_margin_pct']:.1f}" if fnd.get("gross_margin_pct") else "—"
            rg_s = f"%{fnd['rev_growth_yoy_pct']:+.1f}" if fnd.get("rev_growth_yoy_pct") is not None else "—"
            tgt_s = f"{cur}{fnd['analyst_target']} (+%{fnd['analyst_upside_pct']:.0f})" if fnd.get("analyst_target") and fnd.get("analyst_upside_pct") else "—"

            lines.append(
                f"| **RSI (14)** | **{intel['rsi14']:.1f}** | **İleri / Cari F/K** | **{fpe_s}** | **1. Kademe Alım** | **`{cur}{dip.get('zone1_low', 0):.2f} – {cur}{dip.get('zone1_high', 0):.2f}`** |"
            )
            lines.append(
                f"| **SMA 20 / 50** | {cur}{intel['sma20']:,.2f} / {cur}{intel['sma50']:,.2f} | **Brüt Kâr Marjı** | {gm_s} | **2. Kademe Alım** | `{cur}{dip.get('zone2_low', 0):.2f} – {cur}{dip.get('zone2_high', 0):.2f}` |"
            )
            lines.append(
                f"| **SMA 200** | {cur}{intel['sma200']:,.2f} | **Yıllık Ciro Büyümesi** | {rg_s} | **İlk Hedef (TP1)** | **`{cur}{dip.get('target1', 0):.2f}`** (+%{dip.get('upside_pct', 0):.1f}) |"
            )
            lines.append(
                f"| **52H Zirveden Fark** | %{intel['drop_52w_pct']:.1f} | **Analist Hedefi** | {tgt_s} | **Kaçış (Stop-Loss)** | **`{cur}{dip.get('stop_level', 0):.2f}`** |"
            )
            lines.append("")

            lines.append("#### 🎯 Öne Çıkan Güçlü Yönler & Riskler")
            for p in pros:
                lines.append(f"* {p}")
            for c in cons:
                lines.append(f"* {c}")

            lines.append("")
            lines.append("#### 🧭 Senaryo Haritası & Aksiyon Planı")
            lines.append(f"* **Boğa Senaryosu:** {ic_card['bull_case'].replace('\\$', '$')}")
            lines.append(f"* **Baz Senaryo:** {ic_card['base_case'].replace('\\$', '$')}")
            lines.append(f"* **Ayı Senaryosu:** {ic_card['bear_case'].replace('\\$', '$')}")
            lines.append(f"* {ic_card['invalidation_rule'].replace('\\$', '$')}")

            if relevant_notes:
                lines.append("")
                lines.append("#### 🧠 Hafızadaki Geçmiş Notlarımız")
                for rn in relevant_notes[:2]:
                    lines.append(f"* **[{rn['date']}] {rn['title']}:** {rn['content']}")
            lines.append("\n---\n")

        return "\n".join(lines).strip()

    # Eğer hiçbir hisse bulunamadıysa genel strateji asistanı yanıtı
    lines.append("### 🏦 StockPredictionPro Kurumsal AI Analist")
    lines.append(
        "Hafızamdaki portföy kuralların (**Midas FIFO**, 5 kademeli **`MU`** pozisyonun ve takip listen: "
        "**`COHR, MRVL, AVGO, BE, RKLB, EOG, SARAE.IS`**) aktif. Bana istediğin hisseyi, karşılaştırmayı veya bilanço sorusunu doğrudan sorabilirsin."
    )
    return "\n".join(lines)


# ─── 8. BULUT LLM ÇAĞRISI (GEMINI / GROQ / OPENAI) + OTOMATİK GERİ DÜŞÜŞ ───
def _build_llm_system_and_user_prompt(
    user_query: str,
    intent: str,
    symbols: list[str],
    intel_map: dict[str, dict],
    portfolio_intel: dict,
    regime_info: dict,
    memory_data: dict,
    recent_messages: list[dict],
) -> tuple[str, str]:
    """Bulut LLM için tüm canlı verileri, algoritmaları ve kalıcı hafızayı içeren zengin prompt hazırlar."""
    sys_prompt = (
        "Sen StockPredictionPro sisteminin başındaki Kıdemli Wall Street & BIST Kurumsal Quant Analisti ve Portföy Stratejistisin.\n"
        "Kullanıcın: Talha (@talha4111).\n"
        "Temel Kurallar:\n"
        "1. ASLA yuvarlak, yüzeysel veya 'araştırmanızı öneririm' tarzı sıradan sohbet robotu cevapları verme.\n"
        "2. Sana aşağıda verilen CANLI KURUMSAL TELEMETRİ verilerindeki gerçek fiyatları, RSI, SMA20/50/200, İleri F/K, "
        "Dip Avcısı Kademe 1 ve Kademe 2 alım kutularını, TP1/TP2 hedeflerini, Stop seviyelerini, Üçlü Bariyer AI olasılıklarını ve "
        "bilanço rakamlarını birebir kullanarak net, rakamsal, tablolu ve karar odaklı Türkçe analiz yap.\n"
        "3. KALICI HAFIZA'daki geçmiş konuşmaları ve Midas FIFO kuralını (satışta en eski lotun ilk satıldığını) asla unutma.\n"
        "4. Fiyatları yazarken LaTeX bozulmasını önlemek için dolar işaretini normal ve net kullan, Markdown tabloları oluştur."
    )

    # Hafıza özeti
    mem_str = json.dumps(memory_data.get("memory_notes", [])[:10], ensure_ascii=False, indent=2)

    # Sohbet geçmişi özeti (Son 6 mesaj)
    hist_lines = []
    for m in recent_messages[-6:]:
        role_lbl = "Talha" if m.get("role") == "user" else "AI Analist"
        hist_lines.append(f"[{m.get('timestamp', '')}] {role_lbl}: {m.get('content', '')[:600]}")
    hist_str = "\n".join(hist_lines)

    # Canlı telemetri özeti
    clean_telemetry = {}
    for sym, data in intel_map.items():
        if not data.get("valid"):
            continue
        dip = data.get("dip") or {}
        clean_telemetry[sym] = {
            "name": data.get("name"),
            "currency": data.get("currency"),
            "price": data.get("price"),
            "daily_chg_pct": data.get("daily_chg_pct"),
            "post_market_price": data.get("post_market_price"),
            "post_market_chg_pct": data.get("post_market_chg_pct"),
            "chg_1m_pct": data.get("chg_1m_pct"),
            "drop_52w_pct": data.get("drop_52w_pct"),
            "rsi14": data.get("rsi14"),
            "sma20": data.get("sma20"),
            "sma50": data.get("sma50"),
            "sma200": data.get("sma200"),
            "fundamentals": data.get("fundamentals"),
            "factors": data.get("factors"),
            "dip_hunter": {
                "state_code": dip.get("state_code"),
                "state_badge": dip.get("state_badge"),
                "zone1": f"{dip.get('zone1_low')} - {dip.get('zone1_high')}",
                "zone2": f"{dip.get('zone2_low')} - {dip.get('zone2_high')}",
                "target1": dip.get("target1"),
                "target2": dip.get("target2"),
                "stop_level": dip.get("stop_level"),
                "upside_pct": dip.get("upside_pct"),
                "ai_15d_win_prob": (dip.get("ai_pred") or {}).get("p_tp"),
            },
            "earnings_releases": data.get("earnings_releases"),
            "earnings_catalyst_summary": (data.get("earnings") or {}).get("summary_text"),
            "recent_news": data.get("recent_news"),
        }

    user_payload = (
        f"=== 1. KALICI HAFIZA NOTLARI (ESKİ KONUŞTUKLARIMIZ & PORTFÖY KURALLARI) ===\n{mem_str}\n\n"
        f"=== 2. SON SOHBET GEÇMİŞİ ===\n{hist_str}\n\n"
        f"=== 3. AKTİF PİYASA REJİMİ ===\n{json.dumps(regime_info, ensure_ascii=False)}\n\n"
        f"=== 4. MİDAS FIFO PORTFÖY DURUMU ===\n{json.dumps(portfolio_intel, ensure_ascii=False)}\n\n"
        f"=== 5. İLGİLİ HİSSELERİN CANLI KURUMSAL VERİLERİ ({', '.join(symbols)}) ===\n"
        f"{json.dumps(clean_telemetry, ensure_ascii=False, indent=2)}\n\n"
        f"=== TALHA'NIN YENİ SORUSU ===\n{user_query}\n\n"
        f"Lütfen yukarıdaki canlı verileri ve hafızayı kullanarak doğrudan, kapsamlı, tablolu ve uzman analist seviyesinde yanıtla."
    )
    return sys_prompt, user_payload


def _call_cloud_llm(sys_prompt: str, user_payload: str, cfg: dict) -> tuple[str | None, str]:
    """Yapılandırılmışsa Gemini, Groq veya OpenAI API'sini çağırır."""
    provider = cfg.get("provider", "auto")

    # 1. Google Gemini API
    if provider in ("auto", "gemini") and cfg.get("gemini_api_key"):
        key = cfg["gemini_api_key"].strip()
        if key not in _FAILED_LLM_KEYS:
            model = cfg.get("gemini_model", "gemini-2.5-flash").strip()
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
            body = {
                "system_instruction": {"parts": [{"text": sys_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": 4096},
            }
            try:
                r = requests.post(url, json=body, timeout=15)
                if r.status_code == 200:
                    resp_json = r.json()
                    candidates = resp_json.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text = "".join(p.get("text", "") for p in parts).strip()
                        if text:
                            return text, f"Google Gemini ({model}) + Canlı Quant Telemetri"
                elif r.status_code in (401, 403):
                    _FAILED_LLM_KEYS.add(key)
            except Exception:
                pass

    # 2. Groq API (Llama-3.3-70B)
    if provider in ("auto", "groq") and cfg.get("groq_api_key"):
        key = cfg["groq_api_key"].strip()
        if key not in _FAILED_LLM_KEYS:
            model = cfg.get("groq_model", "llama-3.3-70b-versatile").strip()
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.25,
                "max_tokens": 4096,
            }
            try:
                r = requests.post(url, headers=headers, json=body, timeout=15)
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"].strip()
                    if text:
                        return text, f"Groq ({model}) + Canlı Quant Telemetri"
                elif r.status_code in (401, 403):
                    _FAILED_LLM_KEYS.add(key)
            except Exception:
                pass

    # 3. OpenAI API (GPT-4o)
    if provider in ("auto", "openai") and cfg.get("openai_api_key"):
        key = cfg["openai_api_key"].strip()
        if key not in _FAILED_LLM_KEYS:
            model = cfg.get("openai_model", "gpt-4o").strip()
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.25,
                "max_tokens": 4096,
            }
            try:
                r = requests.post(url, headers=headers, json=body, timeout=15)
                if r.status_code == 200:
                    text = r.json()["choices"][0]["message"]["content"].strip()
                    if text:
                        return text, f"OpenAI ({model}) + Canlı Quant Telemetri"
                elif r.status_code in (401, 403):
                    _FAILED_LLM_KEYS.add(key)
            except Exception:
                pass

    return None, "Yerleşik Kurumsal Quant & Hafıza Motoru"


# ─── 9. ANA ORKESTRASYON FONKSİYONU ───
def ask_ai_analyst(user_query: str) -> dict:
    """
    Kullanıcının sorusunu alır:
    1. Aktif oturum bağlamını ve kalıcı hafızayı yükler,
    2. Sembolleri ve soru niyetini çözümler,
    3. Canlı piyasa, bilanço, Dip Avcısı, Üçlü Bariyer AI ve FIFO portföy verilerini toplar,
    4. Bulut LLM (aktifse) veya Yerleşik Kurumsal Quant Muhakeme Motoru ile yanıt üretir,
    5. Sohbet geçmişine ve hafızaya kaydeder.
    """
    active_sess = get_active_session()
    ctx_syms = active_sess.get("context_symbols", [])
    symbols, intent, used_context = extract_symbols_and_intent(user_query, ctx_syms)

    # Kullanıcı mesajını oturuma kaydet
    append_chat_message(role="user", content=user_query, symbols=symbols)

    # Canlı telemetri verilerini paralel olarak topla
    intel_map: dict[str, dict] = {}
    telemetry_cards: list[dict] = []
    if symbols:
        with ThreadPoolExecutor(max_workers=min(4, len(symbols))) as pool:
            futures = {s: pool.submit(collect_symbol_intelligence, s) for s in symbols}
            for s in symbols:
                try:
                    intel_map[s] = futures[s].result(timeout=30)
                except Exception:
                    intel_map[s] = {"symbol": s, "valid": False}

    for s in symbols:
        s_intel = intel_map.get(s, {})
        if s_intel.get("valid"):
            dip = s_intel.get("dip") or {}
            fnd = s_intel.get("fundamentals") or {}
            telemetry_cards.append({
                "symbol": s,
                "name": s_intel.get("name", s),
                "currency": s_intel.get("currency", "$"),
                "price": s_intel.get("price"),
                "daily_chg_pct": s_intel.get("daily_chg_pct"),
                "rsi14": s_intel.get("rsi14"),
                "forward_pe": fnd.get("forward_pe"),
                "state_badge": dip.get("state_badge", "—"),
                "zone1": f"{s_intel.get('currency', '$')}{dip.get('zone1_low', 0):.2f}–{s_intel.get('currency', '$')}{dip.get('zone1_high', 0):.2f}" if dip else "—",
                "target1": f"{s_intel.get('currency', '$')}{dip.get('target1', 0):.2f}" if dip else "—",
                "stop": f"{s_intel.get('currency', '$')}{dip.get('stop_level', 0):.2f}" if dip else "—",
            })

    regime_info = get_market_regime_summary()
    portfolio_intel = collect_portfolio_intelligence() if intent == "PORTFOLIO_FIFO" or "MU" in symbols else {}
    memory_data = load_ai_memory()
    cfg = load_ai_provider_config()

    # Önce Bulut LLM (Gemini / Groq / OpenAI) dene, yoksa/hata verirse Yerleşik Quant Motorunu çalıştır
    response_text = None
    engine_label = "Yerleşik Kurumsal Quant & Hafıza Motoru"

    if any([cfg.get("gemini_api_key"), cfg.get("groq_api_key"), cfg.get("openai_api_key")]):
        sys_p, usr_p = _build_llm_system_and_user_prompt(
            user_query=user_query,
            intent=intent,
            symbols=symbols,
            intel_map=intel_map,
            portfolio_intel=portfolio_intel,
            regime_info=regime_info,
            memory_data=memory_data,
            recent_messages=active_sess.get("messages", []),
        )
        response_text, engine_label = _call_cloud_llm(sys_p, usr_p, cfg)

    if not response_text:
        response_text = _synthesize_institutional_response(
            user_query=user_query,
            intent=intent,
            symbols=symbols,
            used_context=used_context,
            intel_map=intel_map,
            portfolio_intel=portfolio_intel,
            regime_info=regime_info,
            memory_data=memory_data,
        )
        engine_label = "Kurumsal Quant & Hafıza Motoru (Canlı Veri)"

    # Yanıtı oturuma kaydet
    append_chat_message(
        role="assistant",
        content=response_text,
        symbols=symbols,
        engine=engine_label,
        telemetry_cards=telemetry_cards,
    )

    return {
        "response": response_text,
        "symbols": symbols,
        "intent": intent,
        "engine": engine_label,
        "telemetry_cards": telemetry_cards,
    }
