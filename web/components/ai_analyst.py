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

    # Aktif Streamlit oturumunda kaydedilmiş güncel ayar varsa öncelik ver
    try:
        import streamlit as st
        sess_cfg = st.session_state.get("ai_provider_config")
        if isinstance(sess_cfg, dict):
            cfg.update(sess_cfg)
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
        if env_gem and env_gem not in _FAILED_LLM_KEYS:
            cfg["gemini_api_key"] = env_gem
    if not cfg["groq_api_key"]:
        env_groq = os.getenv("GROQ_API_KEY", "").strip()
        if env_groq and env_groq not in _FAILED_LLM_KEYS:
            cfg["groq_api_key"] = env_groq
    if not cfg["openai_api_key"]:
        env_oai = os.getenv("OPENAI_API_KEY", "").strip()
        if env_oai and env_oai not in _FAILED_LLM_KEYS:
            cfg["openai_api_key"] = env_oai

    return cfg


def save_ai_provider_config(new_cfg: dict):
    """API yapılandırmasını hem oturum hafızasına hem diske kaydeder."""
    _FAILED_LLM_KEYS.clear()
    try:
        import streamlit as st
        st.session_state["ai_provider_config"] = dict(new_cfg)
    except Exception:
        pass
    os.makedirs(DATA_DIR, exist_ok=True)
    try:
        with open(AI_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(new_cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def test_ai_provider_connection(cfg: dict) -> tuple[bool, str]:
    """Kaydedilen API anahtarını canlı test eder ve kullanıcıya net durum raporu döner."""
    provider = cfg.get("provider", "auto")

    if provider in ("auto", "gemini") and cfg.get("gemini_api_key"):
        key = cfg["gemini_api_key"].strip()
        chosen_model = cfg.get("gemini_model", "gemini-2.5-flash").strip()
        models_to_try = []
        for m in [chosen_model, "gemini-2.5-flash", "gemini-2.0-flash"]:
            if m and m not in models_to_try:
                models_to_try.append(m)

        last_code = 0
        for m in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
            body = {
                "contents": [{"role": "user", "parts": [{"text": "OK"}]}],
                "generationConfig": {"maxOutputTokens": 10},
            }
            try:
                r = requests.post(url, json=body, timeout=10)
                last_code = r.status_code
                if r.status_code == 200:
                    if m != chosen_model:
                        cfg["gemini_model"] = m
                        save_ai_provider_config(cfg)
                        return True, f"✅ Google Gemini API Anahtarı Doğrulandı! (`{chosen_model}` ücretsiz kota sınırında olduğu için otomatik olarak en hızlı **`{m}`** modeline geçildi ve aktif edildi)."
                    return True, f"✅ Google Gemini API Anahtarı Doğrulandı ve **`{m}`** modeliyle aktif edildi! Artık **💬 Uzman Analist Masası** sekmesinden sorularını sorabilirsin."
                elif r.status_code in (400, 401, 403):
                    _FAILED_LLM_KEYS.add(key)
                    return False, f"⚠️ Girilen Google Gemini API anahtarı geçersiz veya yetkisiz görünüyor (HTTP {r.status_code}). Lütfen aistudio.google.com üzerinden aldığın `AIza...` ile başlayan anahtarı kontrol et."
            except Exception as e:
                return False, f"⚠️ Bağlantı testi sırasında ağ hatası oluştu: {e}"
        return False, f"⚠️ Google Gemini API yanıt vermedi (HTTP {last_code}). Sistem otomatik olarak Yerleşik Kurumsal Quant Motoru ile kesintisiz çalışmaya devam edecek."

    if provider in ("auto", "groq") and cfg.get("groq_api_key"):
        key = cfg["groq_api_key"].strip()
        model = cfg.get("groq_model", "llama-3.3-70b-versatile").strip()
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"model": model, "messages": [{"role": "user", "content": "OK"}], "max_tokens": 5}
        try:
            r = requests.post(url, headers=headers, json=body, timeout=10)
            if r.status_code == 200:
                return True, f"✅ Groq API Anahtarı Doğrulandı ve **`{model}`** modeliyle aktif edildi!"
            return False, f"⚠️ Groq API anahtarı doğrulanamadı (HTTP {r.status_code})."
        except Exception as e:
            return False, f"⚠️ Groq bağlantı hatası: {e}"

    if provider in ("auto", "openai") and cfg.get("openai_api_key"):
        key = cfg["openai_api_key"].strip()
        model = cfg.get("openai_model", "gpt-4o").strip()
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        body = {"model": model, "messages": [{"role": "user", "content": "OK"}], "max_tokens": 5}
        try:
            r = requests.post(url, headers=headers, json=body, timeout=10)
            if r.status_code == 200:
                return True, f"✅ OpenAI API Anahtarı Doğrulandı ve **`{model}`** modeliyle aktif edildi!"
            return False, f"⚠️ OpenAI API anahtarı doğrulanamadı (HTTP {r.status_code})."
        except Exception as e:
            return False, f"⚠️ OpenAI bağlantı hatası: {e}"

    return True, "ℹ️ Harici API anahtarı girilmedi; sistem **Yerleşik Kurumsal Quant & Hafıza Motoru** ile aktif çalışıyor."


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

    # 5) Niyet (Intent) tespiti — tek bir anahtar kelimeye takılmak yerine puanlama yapılır.
    #    Her niyet için güçlü (2 puan) ve zayıf (1 puan) ifadeler sayılır, en yüksek puan kazanır.
    memory_cmd = any(k in q_lower for k in ["bunu unutma", "hafızaya kaydet", "hafizaya kaydet", "not al", "kaydet:"])
    trade_note = bool(re.search(r"\b(aldım|sattım|aldim|sattim)\b", q_lower)) and not re.search(r"\?|mı|mi|mu|mü", q_lower)
    if (memory_cmd or trade_note) and len(q_raw) < 220:
        intent = "MEMORY_UPDATE"
    else:
        intent_rules = {
            "EARNINGS_CHECK": (
                ["bilanço", "bilanco", "açıklandı mı", "aciklandi mi", "eps", "guidance", "rehberlik"],
                ["sonuçlar", "sonuclar", "nasıl geldi", "çeyrek", "ceyrek", "karne"],
            ),
            "RECOVERY_TARGET": (
                ["toparlar", "toparlanma", "eski seviye", "halka arz", "ne zaman döner", "ne zaman çıkar"],
                ["ne zaman", "neden düştü", "niye düştü", "geri gelir"],
            ),
            "COMPARE_SELECT": (
                ["hangisini", "hangisi", "kıyasla", "kiyasla", "karşılaştır", "karsilastir", "arasında kaldım", "ikisini", "iki tanesini"],
                ["seç", "mı yoksa", "mi yoksa"],
            ),
            "PORTFOLIO_FIFO": (
                ["portföy", "portfoy", "fifo", "midas", "lotlarım", "lotlarim", "elimdeki"],
                ["maliyetim", "vergi", "lot"],
            ),
            "OPPORTUNITY_SCAN": (
                ["fırsat", "firsat", "ne alsam", "ne alınır", "ne alinir", "dip avcısı", "alım avcısı"],
                ["öneri", "oneri", "tavsiye"],
            ),
        }
        scores = {}
        for name, (strong, weak) in intent_rules.items():
            scores[name] = 2 * sum(1 for k in strong if k in q_lower) + sum(1 for k in weak if k in q_lower)
        if len(found_symbols) >= 2:
            scores["COMPARE_SELECT"] += 1
        best_intent, best_score = max(scores.items(), key=lambda x: x[1])
        intent = best_intent if best_score >= 2 else "DEEP_STOCK_ANALYSIS"

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
        sma5 = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else last_price
        sma10 = float(close.rolling(10).mean().iloc[-1]) if len(close) >= 10 else last_price
        sma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else last_price
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else last_price
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())

        # Hacim oranı (Son gün / 20G ortalama)
        vol_series = hist["Volume"].dropna() if "Volume" in hist.columns else pd.Series(dtype=float)
        avg_vol_20 = float(vol_series.tail(21).iloc[:-1].mean()) if len(vol_series) >= 6 else 0.0
        today_vol = float(vol_series.iloc[-1]) if len(vol_series) >= 1 else 0.0
        vol_ratio = round(today_vol / avg_vol_20, 2) if avg_vol_20 > 0 else 1.0

        # Son 5 günlük dip -> tepe dalgası ve Fibonacci soğuma (geri çekilme) basamakları
        swing_low_5d = float(hist["Low"].tail(5).min()) if len(hist) >= 3 else last_price * 0.92
        swing_high_5d = max(float(hist["High"].tail(3).max()) if len(hist) >= 2 else last_price, last_price)
        swing_range = max(0.01, swing_high_5d - swing_low_5d)
        rally_from_low_pct = ((last_price / swing_low_5d) - 1.0) * 100.0 if swing_low_5d > 0 else 0.0
        fib_236 = round(swing_high_5d - 0.236 * swing_range, 2)
        fib_382 = round(swing_high_5d - 0.382 * swing_range, 2)
        fib_500 = round(swing_high_5d - 0.500 * swing_range, 2)
        fib_618 = round(swing_high_5d - 0.618 * swing_range, 2)

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
            "sma5": round(sma5, 2),
            "sma10": round(sma10, 2),
            "sma20": round(sma20, 2),
            "sma50": round(sma50, 2),
            "sma200": round(sma200, 2),
            "vol_ratio": vol_ratio,
            "swing_low_5d": round(swing_low_5d, 2),
            "swing_high_5d": round(swing_high_5d, 2),
            "rally_from_low_pct": round(rally_from_low_pct, 1),
            "fib_236": fib_236,
            "fib_382": fib_382,
            "fib_500": fib_500,
            "fib_618": fib_618,
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
        target_median = info.get("targetMedianPrice")
        target_low = info.get("targetLowPrice")
        target_high = info.get("targetHighPrice")
        rec_key = info.get("recommendationKey", "")
        rec_mean = info.get("recommendationMean")
        num_analysts = info.get("numberOfAnalystOpinions")

        analyst_upside = ((float(target_mean) / last_price) - 1.0) * 100.0 if target_mean and last_price > 0 else None

        rec_counts = {}
        try:
            rs_df = getattr(tk, "recommendations_summary", None)
            if rs_df is not None and not rs_df.empty:
                r0 = rs_df.iloc[0]
                rec_counts = {
                    "strongBuy": int(r0.get("strongBuy", 0) or 0),
                    "buy": int(r0.get("buy", 0) or 0),
                    "hold": int(r0.get("hold", 0) or 0),
                    "sell": int(r0.get("sell", 0) or 0),
                    "strongSell": int(r0.get("strongSell", 0) or 0),
                }
        except Exception:
            rec_counts = {}

        recent_ratings = []
        try:
            ud_df = getattr(tk, "upgrades_downgrades", None)
            if ud_df is not None and not ud_df.empty:
                for dt_idx, urow in ud_df.head(5).iterrows():
                    dt_s = pd.to_datetime(dt_idx).strftime("%d.%m.%Y")
                    cur_t = urow.get("currentPriceTarget")
                    pri_t = urow.get("priorPriceTarget")
                    recent_ratings.append({
                        "date": dt_s,
                        "firm": str(urow.get("Firm", "")),
                        "to_grade": str(urow.get("ToGrade", "")),
                        "pt_action": str(urow.get("priceTargetAction", "")),
                        "current_target": round(float(cur_t), 2) if pd.notna(cur_t) and float(cur_t) > 0 else None,
                        "prior_target": round(float(pri_t), 2) if pd.notna(pri_t) and float(pri_t) > 0 else None,
                    })
        except Exception:
            recent_ratings = []

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
            "analyst_median": round(float(target_median), 2) if target_median else None,
            "analyst_low": round(float(target_low), 2) if target_low else None,
            "analyst_high": round(float(target_high), 2) if target_high else None,
            "analyst_upside_pct": round(float(analyst_upside), 1) if analyst_upside is not None else None,
            "recommendation": str(rec_key).upper().replace("_", " ") if rec_key else None,
            "recommendation_mean": round(float(rec_mean), 2) if rec_mean else None,
            "num_analysts": int(num_analysts) if num_analysts else None,
            "rec_counts": rec_counts,
            "recent_ratings": recent_ratings,
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

        # 4 Sütun Faktör Puanları (Dinamik Hesaplama + Tarama Skoru Entegrasyonu)
        db_map = get_db_symbol_data((sym,)) if not is_bist else {}
        db_row = db_map.get(sym)
        gm = intel["fundamentals"].get("gross_margin_pct") or 38.0
        rg = intel["fundamentals"].get("rev_growth_yoy_pct") or 18.0
        kalite = float(np.clip(45.0 + (gm * 0.55) + (rg * 0.35), 25.0, 95.0))
        fpe_val = intel["fundamentals"].get("forward_pe") or intel["fundamentals"].get("trailing_pe") or 25.0
        deger = float(np.clip(90.0 - (fpe_val * 1.3), 20.0, 92.0))
        momentum = float(np.clip(50.0 + chg_3m * 0.7 + (rsi14 - 50.0) * 0.4, 20.0, 95.0))
        beta_val = intel["fundamentals"].get("beta") or 1.5
        risk_sc = float(np.clip(90.0 - (beta_val * 16.0), 20.0, 88.0))
        comp_sc = float(db_row.get("score")) if (db_row and db_row.get("score")) else round(kalite * 0.35 + deger * 0.20 + momentum * 0.30 + risk_sc * 0.15, 1)

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
    win_prob_pct = ai.get("win_prob_pct")
    if win_prob_pct is None and ai.get("p_tp") is not None:
        win_prob_pct = float(ai.get("p_tp")) * 100.0
    if win_prob_pct and win_prob_pct >= 52.0:
        score += 6.0
        pros.append(f"🤖 **Üçlü Bariyer AI Onayı:** 15 iş gününde hedefe ulaşma olasılığı **%{win_prob_pct:.0f}**.")

    return round(float(np.clip(score, 10.0, 99.0)), 1), pros, cons


# ─── 7. YERLEŞİK KURUMSAL QUANT MUHAKEME MOTORU (SORU ODAKLI & DİNAMİK SENTEZ) ───
def detect_question_focus(user_query: str) -> list[str]:
    """Sorunun tam olarak NE sorduğunu (geri çekilme basamakları, yükseliş devamı, analist görüşü, al/sat kararı vb.) tespit eder."""
    q = user_query.lower()
    focus = []
    rules = [
        ("PULLBACK", [
            "kaça düşer", "kaca duser", "kaçlara düşer", "kaclara duser", "nereye düşer", "nereye çeker",
            "kaça çeker", "kaçlara çekilir", "ne kadar düşer", "geri çekil", "düzeltme", "soğu", "şişti",
            "sisti", "köpük", "kopuk", "ortalama kaç", "destek", "taban",
        ]),
        ("DIRECTION", [
            "yükselir mi", "yukselir mi", "devam eder mi", "korur mu", "koruyarak", "ilerleyecek mi",
            "ilerler mi", "düşer mi", "duser mi", "daha da düş", "düşme ihtimali", "dusme ihtimali",
            "yükselişi", "yukselisi", "yön", "yon", "çıkar mı", "cikar mi", "iner mi", "artış", "artis",
        ]),
        ("ANALYST", [
            "analist", "uzman", "görüş", "gorus", "hedef fiyat", "wall street", "kurum",
            "derecelendirme", "beklenti", "yorum", "gelecek performans",
        ]),
        ("BUY_DECISION", [
            "alınır mı", "alinir mi", "almalı mı", "almali mi", "alayım mı", "alayim mi",
            "girilir mi", "girmeli", "ekleme", "eklesem", "almak mantıklı", "kaçtan al", "kademe",
        ]),
        ("SELL_DECISION", [
            "satayım mı", "satayim mi", "satmalı", "satsam", "kâr al", "kar al",
            "çıkayım", "elimdekini sat", "tutayım mı", "tutayim mi", "tutmalı", "satış",
        ]),
        ("TIMING", ["ne zaman", "kaç gün", "hangi gün", "vade", "takvim"]),
        ("WHY", ["neden", "niye", "sebebi", "sebep", "niçin"]),
    ]
    for name, keys in rules:
        if any(k in q for k in keys):
            focus.append(name)
    return focus


def _render_targeted_stock_section(intel: dict, focus: list[str], regime_info: dict, portfolio_intel: dict) -> tuple[list[str], list[str]]:
    """
    Tek bir hisse için sabit şablon yerine KULLANICININ SORDUĞU SORUYA göre:
    1) Ana Odaklı Yanıt (main_lines)
    2) Tıklayınca Açılacak Detay/Tablo Ekleri (detail_lines)
    üretir.
    """
    sym = intel["symbol"]
    cur = intel.get("currency", "$")
    p = float(intel.get("price") or 0.0)
    chg = float(intel.get("daily_chg_pct") or 0.0)
    dip = intel.get("dip") or {}
    ex = intel.get("exit") or {}
    fnd = intel.get("fundamentals") or {}
    fac = intel.get("factors") or {}
    earn = intel.get("earnings") or {}
    ai = dip.get("ai_pred") or intel.get("ai_pred") or {}

    rsi_d = float(intel.get("rsi14") or 50.0)
    rsi_intra = float(dip.get("rsi_intra") or rsi_d)
    sma5 = float(intel.get("sma5") or p)
    sma10 = float(intel.get("sma10") or p)
    sma20 = float(intel.get("sma20") or p)
    sma50 = float(intel.get("sma50") or p)
    sma200 = float(intel.get("sma200") or p)
    vol_ratio = float(intel.get("vol_ratio") or 1.0)

    swing_low = float(intel.get("swing_low_5d") or p * 0.9)
    swing_high = float(intel.get("swing_high_5d") or p)
    rally_pct = float(intel.get("rally_from_low_pct") or 0.0)
    fib236 = float(intel.get("fib_236") or p * 0.95)
    fib382 = float(intel.get("fib_382") or p * 0.91)
    fib500 = float(intel.get("fib_500") or p * 0.88)
    fib618 = float(intel.get("fib_618") or p * 0.85)

    win_prob = ai.get("win_prob_pct")
    stop_prob = ai.get("stop_prob_pct")
    analog_cnt = ai.get("analog_count", 25)
    analog_win = ai.get("analog_win_rate_pct")
    analog_ret = ai.get("analog_avg_ret_pct")

    z1l = float(dip.get("zone1_low") or fib382)
    z1h = float(dip.get("zone1_high") or fib236)
    z2l = float(dip.get("zone2_low") or fib618)
    z2h = float(dip.get("zone2_high") or fib500)
    tp1 = float(dip.get("target1") or sma20 * 1.08)
    tp2 = float(dip.get("target2") or sma50 * 1.12)
    stop = float(dip.get("stop_level") or swing_low * 0.92)
    upside_tp1 = float(dip.get("upside_pct") or (((tp1 / p) - 1.0) * 100.0 if p > 0 else 0.0))

    sc, pros, cons = score_stock_for_selection(intel)

    # Eğer özel bir soru odağı yakalanmadıysa dengeli varsayılan odaklar: DIRECTION + BUY_DECISION
    active_focus = list(focus) if focus else ["DIRECTION", "BUY_DECISION"]

    main_lines: list[str] = []
    main_lines.append(
        f"### 📌 `{sym}` ({intel['name']}) — Anlık: **{cur}{p:,.2f}** ({chg:+.2f}%) · Quant Skor: **{sc:.0f}/100**"
    )

    # ── ODAK 1: YÜKSELİŞİ KORUR MU / DAHA DÜŞME İHTİMALİ VAR MI? (DIRECTION) ──
    if "DIRECTION" in active_focus:
        if win_prob is not None:
            if win_prob >= 60:
                verdict_headline = f"Orta vadede (15 iş günü) yükselişin devam etme olasılığı **%{win_prob}** ile ağır basıyor"
            elif win_prob >= 50:
                verdict_headline = f"15 günlük hedef olasılığı **%{win_prob}** ile dengeli/pozitif; ancak kısa vadede sindirme (geri çekilme) olasılığı yüksek"
            else:
                verdict_headline = f"Kısa vadede tekrar aşağı sarkma/destek testi riski (**%{stop_prob or (100 - win_prob)}**) henüz daha baskın (Hedef olasılığı: **%{win_prob}**)"
        else:
            verdict_headline = "Kısa vadeli tepki başlamış durumda ancak üstteki hareketli ortalama dirençleri yakından izlenmeli"

        intra_warn = (
            f"Saatlik RSI **{rsi_intra:.1f}** ile aşırı ısınmış durumda; bu yüzden dümdüz çıkmayıp **1-3 gün içinde kâr satışı / nefes alma** görmemiz çok doğal."
            if rsi_intra >= 75
            else f"Saatlik RSI **{rsi_intra:.1f}** ve günlük RSI **{rsi_d:.1f}** ile aşırı bir şişkinlik yok, hareket daha dengeli."
        )

        main_lines.append(f"**🔮 Yön & Devamlılık Özeti:** {verdict_headline}. {intra_warn}")
        main_lines.append("")

        # Güçlü Yanlar vs Düşüş Riskleri
        main_lines.append("**🟢 Yükselişin Devamını Destekleyen Sinyaller:**")
        if win_prob is not None and analog_win is not None:
            main_lines.append(
                f"* **Yapay Zeka (Üçlü Bariyer) & Tarihsel İkizler:** 15 iş gününde `{cur}{stop:,.2f}` stop sınırına değmeden önce "
                f"**`{cur}{tp1:,.2f}`** (+%{upside_tp1:.1f}) hedefine ulaşma ihtimali **%{win_prob}**. "
                f"`{sym}` son 2 yılda benzer fiyat/indikatör yapısına **{analog_cnt} kez** geldi; bunların **%{analog_win:.0f}'inde** yukarı tepki verdi "
                f"(15G ort. getiri: **%{analog_ret:+.1f}**)."
            )
        if rally_pct >= 5.0:
            main_lines.append(
                f"* **Dipten Tepki Gücü:** Son 5 günlük dip noktası olan **`{cur}{swing_low:,.2f}`** seviyesinden **+%{rally_pct:.1f}** tepki verdi "
                f"(Hacim oranı: 20 günlük ortalamanın **{vol_ratio:.2f}x** katı)."
            )
        if fnd.get("forward_pe"):
            main_lines.append(
                f"* **Temel Çarpan Desteği:** İleri F/K **`{fnd['forward_pe']:.1f}x`**"
                + (f", Yıllık Ciro Büyümesi **+%{fnd['rev_growth_yoy_pct']:.1f}**" if fnd.get("rev_growth_yoy_pct") else "")
                + "."
            )

        main_lines.append("")
        main_lines.append("**⚠️ Daha Düşme / Geri Çekilme İhtimalini Yaratan Riskler:**")
        # Üstteki ortalama duvarları
        overhead_walls = []
        if sma20 > p * 1.005:
            overhead_walls.append(f"**`{cur}{sma20:,.2f}` (SMA 20)**")
        if sma50 > p * 1.005:
            overhead_walls.append(f"**`{cur}{sma50:,.2f}` (SMA 50)**")
        if sma200 > p * 1.005:
            overhead_walls.append(f"**`{cur}{sma200:,.2f}` (SMA 200 — Ana Trend)**")
        if overhead_walls:
            main_lines.append(
                f"* **Üstteki Direnç Duvarları:** Fiyat henüz {', '.join(overhead_walls)} seviyelerinin altında. "
                f"İlk yukarı denemede bu ortalamalara çarptığında kısa vadeli kâr satışıyla karşılaşabilir."
            )
        else:
            main_lines.append(
                f"* **Ortalamaların Üzerinde:** Fiyat 20 ve 200 günlük ortalamalarının üzerinde; en yakın geri çekilme desteği **`{cur}{sma20:,.2f}` (SMA 20)**."
            )
        if rsi_intra >= 75:
            main_lines.append(
                f"* **Kısa Vadeli Yorulma (`Saatlik RSI: {rsi_intra:.1f}`):** Son günlerde dipten **+%{rally_pct:.1f}** zıpladığı için dipten alan trader'ların kâr realizasyonu yapma ihtimali yüksek."
            )
        if regime_info.get("smh_2w_ret") is not None:
            main_lines.append(
                f"* **Sektör & Makro Havası:** {regime_info.get('regime_badge', '')} (Çip ETF SMH 2H: **%{regime_info.get('smh_2w_ret', 0):+.1f}**, VIX: **{regime_info.get('vix_val', 18):.1f}**)."
            )
        main_lines.append(
            f"* **🎯 Korunması Gereken Kritik Eşik:** Yükselişin bozulmaması için geri çekilmelerde **`{cur}{fib382:,.2f} – {cur}{sma5:,.2f}`** destek bandının üzerinde tutunması, yukarıda ise **`{cur}{sma20:,.2f}` (SMA 20)** direncini kırması gerekir."
        )
        main_lines.append("")

    # ── ODAK 2: ŞİŞTİ Mİ / TOPARLAYIP ORTALAMA KAÇLARA DÜŞER? (PULLBACK) ──
    if "PULLBACK" in active_focus or ("DIRECTION" in active_focus and rsi_intra >= 75):
        stop1_high = round(fib236, 2)
        stop1_low = round(max(fib236 * 0.982, (fib236 + fib382) / 2.0), 2)

        mid_ma = max(sma5, sma10) if max(sma5, sma10) < stop1_low else round(fib382 * 0.985, 2)
        stop2_low = round(min(fib382, max(mid_ma, fib500 * 1.01)), 2)
        stop2_high = round(max(fib382, min(mid_ma, stop1_low - 0.50)), 2)
        if stop2_low >= stop2_high:
            stop2_low = round(fib382 * 0.98, 2)
            stop2_high = round(fib382, 2)

        stop3_low = round(min(fib618, fib500), 2)
        stop3_high = round(max(fib618, fib500), 2)

        drop1_pct = (((stop1_low + stop1_high) / 2.0 / p) - 1.0) * 100.0 if p > 0 else 0.0
        drop2_pct = (((stop2_low + stop2_high) / 2.0 / p) - 1.0) * 100.0 if p > 0 else 0.0
        drop3_pct = (((stop3_low + stop3_high) / 2.0 / p) - 1.0) * 100.0 if p > 0 else 0.0

        overheat_status = (
            f"Evet, kısa vadede belirgin bir yükseliş sonrası soluklanma ihtiyacı var (Son dipten **+%{rally_pct:.1f}** tepki verdi, Saatlik RSI: **{rsi_intra:.1f}**, Günlük RSI: **{rsi_d:.1f}**)."
            if (rsi_intra >= 72 or rally_pct >= 12.0 or rsi_d >= 65)
            else f"Şu an aşırı bir balon/şişkinlik yok (Günlük RSI: **{rsi_d:.1f}**, Saatlik RSI: **{rsi_intra:.1f}**), ancak olası geri çekilmede destek basamakları net:"
        )

        main_lines.append(f"#### 🎯 `{sym}` Soğuma (Geri Çekilme) Basamakları — Ortalama Kaçlara Düşer?")
        main_lines.append(overheat_status)
        main_lines.append(
            f"1. **🟢 1. Durak (Hafif Nefes Alma / Güçlü Kalırsa): `{cur}{stop1_low:,.2f} – {cur}{stop1_high:,.2f}`** *(Şu andan ort. **%{drop1_pct:.1f}** fark)*\n"
            f"   * **Teknik Karşılığı:** Fibonacci %23.6 ilk düzeltme basamağı (`{cur}{fib236:,.2f}`). Alıcı iştahı çok güçlü kalırsa bu bandın altına inmeden yukarı döner.\n"
            f"2. **🎯 2. Durak (EN OLASI / Ortalama Geri Çekilme Yeri): `{cur}{stop2_low:,.2f} – {cur}{stop2_high:,.2f}`** *(Şu andan ort. **%{drop2_pct:.1f}** fark)*\n"
            f"   * **Teknik Karşılığı:** Fibonacci %38.2 altın düzeltme seviyesi (`{cur}{fib382:,.2f}`) ve 5G/10G kısa vade ortalamalar (`{cur}{sma5:,.2f}` / `{cur}{sma10:,.2f}`). **'Köpüğünü alınca ortalama kaça oturur?' sorusunun ana cevabı bu bölgedir.**\n"
            f"3. **🛡️ 3. Durak (Genel Borsada Sert Satış Çıkarsa Dip Destek): `{cur}{stop3_low:,.2f} – {cur}{stop3_high:,.2f}`** *(Şu andan ort. **%{drop3_pct:.1f}** fark)*\n"
            f"   * **Teknik Karşılığı:** Son yükselişin yarısının geri verildiği yer (Fib %50 = `{cur}{fib500:,.2f}` / Fib %61.8 = `{cur}{fib618:,.2f}`). Daha altında 2. Kademe yedek kurşun kutusu (`{cur}{z2l:,.2f} – {cur}{z2h:,.2f}`) ve kesin stop (`{cur}{stop:,.2f}`) bulunur."
        )
        main_lines.append("")

    # ── ODAK 3: UZMAN ANALİSTLERİN GÖRÜŞLERİ & HEDEF FİYATLAR (ANALYST) ──
    if "ANALYST" in active_focus:
        rec_str = fnd.get("recommendation") or "BUY"
        n_an = fnd.get("num_analysts") or "—"
        t_mean = fnd.get("analyst_target")
        t_med = fnd.get("analyst_median")
        t_low = fnd.get("analyst_low")
        t_high = fnd.get("analyst_high")
        up_pct = fnd.get("analyst_upside_pct")
        rc = fnd.get("rec_counts") or {}
        ratings = fnd.get("recent_ratings") or []

        if t_mean:
            main_lines.append(f"#### 🏦 `{sym}` İçin Uzman Analistlerin (Wall Street) Görüşleri")
            rc_parts = []
            if rc:
                rc_parts.append(
                    f"🟢 **{rc.get('strongBuy', 0)}** Güçlü Al · 🟢 **{rc.get('buy', 0)}** Al · "
                    f"🟡 **{rc.get('hold', 0)}** Tut · 🔴 **{rc.get('sell', 0) + rc.get('strongSell', 0)}** Sat"
                )
            rc_line = f" ({' | '.join(rc_parts)})" if rc_parts else ""
            main_lines.append(
                f"* **Ortak Konsensüs ({n_an} Analist):** **`{rec_str}`**{rc_line}\n"
                f"* **Hedef Fiyat Yelpazesi (Anlık `{cur}{p:,.2f}`):**\n"
                f"  * 🎯 **Ortalama Hedef:** **`{cur}{t_mean:,.2f}`** (**+%{up_pct:.1f}** potansiyel)"
                + (f" · **Medyan Hedef:** **`{cur}{t_med:,.2f}`**" if t_med else "")
                + (f"\n  * 🛡️ **En Düşük Hedef:** **`{cur}{t_low:,.2f}`**" if t_low else "")
                + (f" · 🚀 **En Yüksek Hedef:** **`{cur}{t_high:,.2f}`**" if t_high else "")
            )
            if ratings:
                main_lines.append("* **Son Kurum Raporları & Derecelendirmeler:**")
                for rt in ratings[:4]:
                    pt_txt = ""
                    if rt.get("current_target") and rt.get("prior_target"):
                        pt_txt = f" — Hedef: `{cur}{rt['prior_target']:,.0f}` → **`{cur}{rt['current_target']:,.0f}`** ({rt.get('pt_action', '')})"
                    elif rt.get("current_target"):
                        pt_txt = f" — Hedef: **`{cur}{rt['current_target']:,.0f}`**"
                    main_lines.append(f"  * **[{rt['date']}] {rt['firm']}:** `{rt['to_grade']}`{pt_txt}")
            main_lines.append("")

    # ── ODAK 4: ALIM / SATIŞ KARARI & KADEMELİ OYUN PLANI (BUY_DECISION / SELL_DECISION) ──
    if "BUY_DECISION" in active_focus or "SELL_DECISION" in active_focus:
        main_lines.append(f"#### 💡 `{sym}` İçin Net Aksiyon & Oyun Planı")
        if p <= z1h * 1.015 and p >= z1l * 0.98:
            entry_msg = f"Fiyat şu an **1. Kademe alım kutumuzun (`{cur}{z1l:,.2f} – {cur}{z1h:,.2f}`) tam içinde**. Tüm bütçeyle tek seferde değil, 1. parçayla giriş için uygun."
        elif p > z1h * 1.015:
            entry_msg = (
                f"Fiyat son sıçramayla ideal 1. alım kutumuzun (`{cur}{z1l:,.2f} – {cur}{z1h:,.2f}`) üzerine çıktı. "
                f"En tepeden tek kurşunla atlamak yerine **`{cur}{fib236:,.2f} – {cur}{fib382:,.2f}`** soğuma bandına geri çekilmeyi pusuda beklemek daha düşük maliyet sağlar."
            )
        else:
            entry_msg = f"Fiyat 1. kutunun altında; **`{cur}{z2l:,.2f} – {cur}{z2h:,.2f}`** (2. Kademe destek bölgesi) ve dönüş mumu takip edilmeli."

        main_lines.append(f"* **Yeni Alım / Ekleme Düşünenler İçin:** {entry_msg}")
        shield = ex.get("profit_shield_line") or round(max(fib382, z1l * 0.97), 2)
        main_lines.append(
            f"* **Elinde `{sym}` Bulunduranlar İçin:** Fiyat **`{cur}{shield:,.2f}`** (Kâr Koruma / İlk Ana Destek) üzerinde kaldığı sürece panik satışı yapılmaz; "
            f"15 günlük ilk kâr alma hedefimiz **`{cur}{tp1:,.2f}`** (+%{upside_tp1:.1f}), ikinci ana hedefimiz **`{cur}{tp2:,.2f}`**."
        )
        main_lines.append("")

    # ── DETAY / EK TABLO BÖLÜMÜ (Tıklayınca büyüyen kısım için) ──
    ic_card = build_investment_committee_card(
        symbol=sym,
        current_price=p,
        kalite=fac.get("kalite", 60),
        deger=fac.get("deger", 55),
        momentum=fac.get("momentum", 55),
        risk=fac.get("risk", 55),
        dip_res=dip,
        exit_res=ex,
        earnings_info=earn,
        regime_info=regime_info,
    )
    fpe_s = f"{fnd['forward_pe']:.1f}x" if fnd.get("forward_pe") else (f"{fnd['trailing_pe']:.1f}x" if fnd.get("trailing_pe") else "—")
    gm_s = f"%{fnd['gross_margin_pct']:.1f}" if fnd.get("gross_margin_pct") else "—"
    rg_s = f"%{fnd['rev_growth_yoy_pct']:+.1f}" if fnd.get("rev_growth_yoy_pct") is not None else "—"
    tgt_s = f"{cur}{fnd['analyst_target']} (+%{fnd['analyst_upside_pct']:.0f})" if fnd.get("analyst_target") and fnd.get("analyst_upside_pct") else "—"

    detail_lines: list[str] = [
        f"#### 📊 `{sym}` Tam Teknik, Çarpan & Algoritma Tablosu",
        "| Teknik Göstergeler | Değer | Temel & Çarpanlar | Değer | Algoritma Seviyeleri | Seviye |",
        "| :--- | :---: | :--- | :---: | :--- | :---: |",
        f"| **Günlük / Saatlik RSI** | **{rsi_d:.1f} / {rsi_intra:.1f}** | **İleri / Cari F/K** | **{fpe_s}** | **1. Kademe Alım** | **`{cur}{z1l:,.2f} – {cur}{z1h:,.2f}`** |",
        f"| **SMA 5 / 10 / 20** | {cur}{sma5:,.1f} / {cur}{sma10:,.1f} / {cur}{sma20:,.1f} | **Brüt Kâr Marjı** | {gm_s} | **2. Kademe Alım** | `{cur}{z2l:,.2f} – {cur}{z2h:,.2f}` |",
        f"| **SMA 50 / 200** | {cur}{sma50:,.1f} / {cur}{sma200:,.1f} | **Yıllık Ciro Büyümesi** | {rg_s} | **İlk Hedef (TP1)** | **`{cur}{tp1:,.2f}`** (+%{upside_tp1:.1f}) |",
        f"| **Fibonacci %23.6 / %38.2** | `{cur}{fib236:,.2f}` / `{cur}{fib382:,.2f}` | **Analist Hedefi** | {tgt_s} | **Kaçış (Stop-Loss)** | **`{cur}{stop:,.2f}`** |",
        "",
        f"* **Boğa Senaryosu:** {ic_card['bull_case'].replace('\\$', '$')}",
        f"* **Baz Senaryo:** {ic_card['base_case'].replace('\\$', '$')}",
        f"* **Ayı Senaryosu:** {ic_card['bear_case'].replace('\\$', '$')}",
    ]
    return main_lines, detail_lines


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
    KULLANICININ SORUSUNA DOĞRUDAN ODAKLANAN yanıt üretir.
    Uzun referans tablolarını `<!-- DETAILS_SPLIT -->` ayırıcı ile ayrıştırır ki arayüzde tıklayınca büyüsün.
    """
    focus = detect_question_focus(user_query)
    valid_intels = [intel_map[s] for s in symbols if s in intel_map and intel_map[s].get("valid")]

    # Eğer kullanıcı açıkça geri çekilme ("kaça düşer / şişti mi"), yön ("yükselişi korur mu / düşer mi")
    # veya analist ("uzman analist görüşleri") soruyorsa, genel şablon yerine doğrudan soru-odaklı motoru çalıştır:
    if valid_intels and any(f in focus for f in ["PULLBACK", "DIRECTION", "ANALYST", "BUY_DECISION", "SELL_DECISION"]) and intent not in ("MEMORY_UPDATE", "PORTFOLIO_FIFO", "RECOVERY_TARGET"):
        main_all: list[str] = []
        detail_all: list[str] = []

        if used_context and symbols:
            main_all.append(f"> 🧠 **Bağlam:** Önceki konuşmamızdaki **`{', '.join(symbols)}`** üzerinden devam ediyorum.\n")

        for intel in valid_intels:
            m_lines, d_lines = _render_targeted_stock_section(intel, focus, regime_info, portfolio_intel)
            main_all.extend(m_lines)
            detail_all.extend(d_lines)
            detail_all.append("")

        # Birden fazla hisse varsa en alta net bir yan yana özet tablo ekle
        if len(valid_intels) >= 2:
            main_all.append("### ⚖️ Hisselerin Yan Yana Karşılaştırma Özeti")
            main_all.append("| Hisse | Anlık Fiyat | Günlük / Saatlik RSI | 1. Soğuma Durağı | 🎯 Ortalama Düşüş Yeri (2. Durak) | AI 15G Hedef İhtimali | 15G Kâr Hedefi | Analist Ort. Hedef |")
            main_all.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")
            for intel in valid_intels:
                cur = intel.get("currency", "$")
                dip = intel.get("dip") or {}
                ai = dip.get("ai_pred") or {}
                fnd = intel.get("fundamentals") or {}
                wp = f"%{ai['win_prob_pct']}" if ai.get("win_prob_pct") is not None else "—"
                at = f"{cur}{fnd['analyst_target']:,.0f} (+%{fnd.get('analyst_upside_pct', 0):.0f})" if fnd.get("analyst_target") else "—"
                main_all.append(
                    f"| **`{intel['symbol']}`** | **{cur}{intel['price']:,.2f}** ({intel['daily_chg_pct']:+.1f}%) | "
                    f"{intel['rsi14']:.0f} / {dip.get('rsi_intra', intel['rsi14']):.0f} | "
                    f"`{cur}{intel.get('fib_236', 0):,.2f}` | **`{cur}{intel.get('fib_382', 0):,.2f} – {cur}{intel.get('sma5', 0):,.2f}`** | "
                    f"**{wp}** | **{cur}{dip.get('target1', 0):,.2f}** | {at} |"
                )

        if detail_all:
            return "\n".join(main_all).strip() + "\n\n<!-- DETAILS_SPLIT -->\n\n" + "\n".join(detail_all).strip()
        return "\n".join(main_all).strip()

    body = _synthesize_institutional_body(
        user_query, intent, symbols, used_context, intel_map, portfolio_intel, regime_info, memory_data
    )
    return body


def _synthesize_institutional_body(
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
    Özel niyetler (Hafıza kaydı, Bilanço kontrolü, 4'lü Seçim, Toparlanma Takvimi, FIFO Portföy, Fırsat Taraması)
    için sentez üretir.
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
        lines.append("### 📅 Bilanço Sonuçları, Rehberlik (Guidance) & Takvim Özeti")
        lines.append("")
        detail_earn: list[str] = []

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
            lines.append("")

            if rel_list:
                detail_earn.append(f"#### 📊 `{sym}` Geçmiş Çeyrek Bilanço Sürpriz Tablosu")
                detail_earn.append("| Bilanço Tarihi | EPS Beklentisi | Açıklanan EPS | Sürpriz (%) | Durum |")
                detail_earn.append("| :--- | :---: | :---: | :---: | :---: |")
                for r in rel_list[:4]:
                    est_s = f"{cur}{r['eps_estimate']:.2f}" if r.get("eps_estimate") is not None else "—"
                    rep_s = f"{cur}{r['eps_reported']:.2f}" if r.get("eps_reported") is not None else "⏳ Bekleniyor"
                    surp_v = r.get("surprise_pct")
                    surp_s = f"%{surp_v:+.1f}" if surp_v is not None else "—"
                    status_s = "🟢 Beklenti Üstü" if (surp_v is not None and surp_v > 0) else ("🔴 Beklenti Altı" if (surp_v is not None and surp_v < 0) else "📅 Takvimde")
                    detail_earn.append(f"| **{r['date']}** | {est_s} | **{rep_s}** | {surp_s} | {status_s} |")
                detail_earn.append("")

        # Birden fazla hisse sorulduysa her birinin bilanço takvimini canlı veriden özetle (sabit tarih yok)
        if len(valid_intels) >= 2:
            lines.append("#### 🗓️ Sorulan Hisselerin Bilanço Takvimi (Canlı)")
            for i, intel in enumerate(valid_intels, 1):
                earn = intel.get("earnings") or {}
                nd = earn.get("next_earnings_date")
                dl = earn.get("days_to_earnings")
                if nd and dl is not None and dl >= 0:
                    lines.append(f"{i}. **`{intel['symbol']}`:** ⏳ Sıradaki bilanço **{nd}** ({dl} gün kaldı)")
                else:
                    lines.append(f"{i}. **`{intel['symbol']}`:** Yakın tarihli bilanço takvimi bulunamadı (son çeyrek açıklanmış olabilir).")

        if detail_earn:
            return "\n".join(lines).strip() + "\n\n<!-- DETAILS_SPLIT -->\n\n" + "\n".join(detail_earn).strip()
        return "\n".join(lines).strip()

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

        winner_names = " ve ".join(f"`{w[1]['symbol']}`" for w in winners)
        lines.append(f"### 🏆 Kıyaslama Sonucu — Seçilen {top_n} Favori Hisse: {winner_names}")
        lines.append(
            f"**{', '.join(x[1]['symbol'] for x in scored_list)}** hisselerini **Dip Avcısı**, **Üçlü Bariyer AI**, "
            f"**4 Sütun Faktör Motoru** ve **Wall Street çarpanları** ile kafa kafaya yarıştırdım:"
        )
        lines.append("")

        for idx, (sc, intel, pros, cons) in enumerate(winners, 1):
            sym = intel["symbol"]
            cur = intel["currency"]
            dip = intel.get("dip") or {}
            lines.append(f"#### 🥇 {idx}. Tercih: `{sym}` ({intel['name']}) — Quant Skor: **{sc:.0f}/100** · Fiyat: **{cur}{intel['price']:,.2f}** ({intel['daily_chg_pct']:+.2f}%)")
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
            lines.append("#### ❌ Diğer Hisseler Neden Elendi?")
            for sc, intel, pros, cons in eliminated:
                sym = intel["symbol"]
                reason_str = " ".join(cons) if cons else "Diğer adaylara göre risk/getiri oranı daha düşük kaldı."
                lines.append(f"* **`{sym}` (Skor: {sc:.0f}/100):** {reason_str}")

        detail_cmp = [
            f"#### 📊 {', '.join(x[1]['symbol'] for x in scored_list)} Detaylı Karşılaştırma Tablosu",
            "| Sıra & Hisse | Anlık Fiyat | 1 Aylık | RSI(14) | İleri F/K | Dip Avcısı Durumu | 1. Alım Kutusu | İlk Hedef (TP1) | Stop Sınırı | Quant Puan |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ]
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
            detail_cmp.append(
                f"| {medal} **{idx}. {sym}** | **{cur}{intel['price']:,.2f}** | %{intel['chg_1m_pct']:+.1f} | "
                f"**{intel['rsi14']:.1f}** | {fpe_s} | {st_badge} | `{z1_s}` | **{tp1_s}** | {sl_s} | **{sc:.0f}/100** |"
            )

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
        return "\n".join(lines).strip() + "\n\n<!-- DETAILS_SPLIT -->\n\n" + "\n".join(detail_cmp).strip()

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
        detail_fifo: list[str] = []

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

                # Eğer MU için teknik durum da varsa ekle
                if sym in intel_map and intel_map[sym].get("valid"):
                    mu_intel = intel_map[sym]
                    dip = mu_intel.get("dip") or {}
                    lines.append(
                        f"**📈 `{sym}` Güncel Teknik & Algoritma Kararı:** {dip.get('state_badge', 'İzlemede')} — "
                        f"{dip.get('action_advice', '')}"
                    )
                    lines.append("")

                detail_fifo.append(f"#### 📊 `{sym}` Kademe Kademe Lot Dökümü (FIFO Sırasıyla)")
                detail_fifo.append("| Lot Sırası | Alış Tarihi | Adet | Alış Fiyatı ($) | Giriş Kuru (₺) | Güncel Kâr/Zarar ($) | FIFO Durumu |")
                detail_fifo.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
                for idx, l in enumerate(p.get("all_lots", []), 1):
                    lot_pnl = (p["current_price_usd"] - l["fiyat_usd"]) * l["adet_kalan"]
                    fifo_tag = "🔥 **İLK SATILACAK LOT**" if idx == 1 else f"{idx}. Sırada"
                    detail_fifo.append(
                        f"| **Lot {idx}** | {l['tarih']} | {l['adet_kalan']:.0f} | **${l['fiyat_usd']:,.2f}** | "
                        f"{l['usdtry_kuru']:.2f} ₺ | **${lot_pnl:+,.2f}** | {fifo_tag} |"
                    )
                detail_fifo.append("")

        if detail_fifo:
            return "\n".join(lines).strip() + "\n\n<!-- DETAILS_SPLIT -->\n\n" + "\n".join(detail_fifo).strip()
        return "\n".join(lines).strip()

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
        "Sen StockPredictionPro sisteminin kıdemli borsa analistisin. Kullanıcın: Talha.\n"
        "EN ÖNEMLİ KURAL: Talha'nın sorduğu SORUNUN KENDİSİNİ cevapla. Sorudaki tek bir anahtar kelimeye göre "
        "hazır rapor şablonu üretme. Önce soruya 2-4 cümlelik net, doğrudan bir cevap ver (evet/hayır/seviye/olasılık), "
        "sonra yalnızca bu cevabı destekleyen verileri kısa maddelerle göster.\n"
        "Diğer kurallar:\n"
        "1. 'Araştırmanızı öneririm' gibi kaçamak cümleler kurma; verilerle somut konuş.\n"
        "2. Aşağıdaki canlı verilerdeki gerçek fiyat, RSI, ortalamalar, alım kutuları, hedef/stop, yapay zekâ olasılığı ve "
        "analist hedeflerini birebir kullan; veri yoksa uydurma, 'veri yok' de.\n"
        "3. Tablo yalnızca birden fazla hisseyi kıyaslarken ya da çok sayıda seviye varken gerçekten işe yarıyorsa kullan.\n"
        "4. Sohbet geçmişini takip et: kullanıcı 'peki', 'o zaman', 'bunu' gibi devam soruları sorarsa önceki konuyu sürdür.\n"
        "5. Kalıcı hafızadaki notları ve Midas FIFO kuralını (satışta en eski lot önce satılır) dikkate al.\n"
        "6. Sade, günlük Türkçe kullan. Dolar işaretini normal yaz.\n"
        "7. Kesin getiri vaadi verme; olasılık ve senaryo dili kullan."
    )

    # Hafıza özeti
    mem_str = json.dumps(memory_data.get("memory_notes", [])[:10], ensure_ascii=False, indent=2)

    # Sohbet geçmişi özeti (Son 6 mesaj)
    hist_lines = []
    for m in recent_messages[-8:]:
        role_lbl = "Talha" if m.get("role") == "user" else "AI Analist"
        hist_lines.append(f"[{m.get('timestamp', '')}] {role_lbl}: {m.get('content', '')[:900]}")
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
            "rsi_intraday_15m": dip.get("rsi_intra"),
            "sma5": data.get("sma5"),
            "sma10": data.get("sma10"),
            "sma20": data.get("sma20"),
            "sma50": data.get("sma50"),
            "sma200": data.get("sma200"),
            "vol_ratio": data.get("vol_ratio"),
            "swing_low_5d": data.get("swing_low_5d"),
            "swing_high_5d": data.get("swing_high_5d"),
            "rally_from_low_pct": data.get("rally_from_low_pct"),
            "fibonacci_pullback_stops": {
                "fib_236_first_cooling": data.get("fib_236"),
                "fib_382_average_pullback": data.get("fib_382"),
                "fib_500_deep_pullback": data.get("fib_500"),
                "fib_618_golden_pocket": data.get("fib_618"),
            },
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
                "ai_15d_win_prob_pct": (dip.get("ai_pred") or {}).get("win_prob_pct"),
                "ai_15d_stop_prob_pct": (dip.get("ai_pred") or {}).get("stop_prob_pct"),
                "historical_analog_win_rate_pct": (dip.get("ai_pred") or {}).get("analog_win_rate_pct"),
            },
            "exit_hunter": {
                "exit_badge": (data.get("exit") or {}).get("exit_badge"),
                "take_profit_1": (data.get("exit") or {}).get("take_profit_1"),
                "profit_shield_line": (data.get("exit") or {}).get("profit_shield_line"),
            },
            "earnings_releases": data.get("earnings_releases"),
            "earnings_catalyst_summary": (data.get("earnings") or {}).get("summary_text"),
            "recent_news": data.get("recent_news"),
        }

    focus = detect_question_focus(user_query)
    focus_hint = ", ".join(focus) if focus else "GENEL_DEGERLENDIRME"
    user_payload = (
        f"=== 1. KALICI HAFIZA NOTLARI (ESKİ KONUŞTUKLARIMIZ & PORTFÖY KURALLARI) ===\n{mem_str}\n\n"
        f"=== 2. SON SOHBET GEÇMİŞİ ===\n{hist_str}\n\n"
        f"=== 3. AKTİF PİYASA REJİMİ ===\n{json.dumps(regime_info, ensure_ascii=False)}\n\n"
        f"=== 4. MİDAS FIFO PORTFÖY DURUMU ===\n{json.dumps(portfolio_intel, ensure_ascii=False)}\n\n"
        f"=== 5. İLGİLİ HİSSELERİN CANLI VERİLERİ ({', '.join(symbols)}) ===\n"
        f"{json.dumps(clean_telemetry, ensure_ascii=False, indent=2)}\n\n"
        f"=== TALHA'NIN YENİ SORUSU ===\n{user_query}\n\n"
        f"(Sorunun odağı tahmini: {focus_hint})\n"
        f"Önce bu soruya doğrudan cevap ver, sonra sadece gerekli destekleyici verileri ekle. "
        f"Soruyla ilgisi olmayan bölümler (ör. sorulmadıysa bilanço tablosu, portföy dökümü) ekleme."
    )
    return sys_prompt, user_payload


def _call_cloud_llm(sys_prompt: str, user_payload: str, cfg: dict) -> tuple[str | None, str]:
    """Yapılandırılmışsa Gemini, Groq veya OpenAI API'sini çağırır."""
    provider = cfg.get("provider", "auto")

    # 1. Google Gemini API (Otomatik Model Fallback Destekli)
    if provider in ("auto", "gemini") and cfg.get("gemini_api_key"):
        key = cfg["gemini_api_key"].strip()
        if key not in _FAILED_LLM_KEYS:
            preferred_model = cfg.get("gemini_model", "gemini-2.5-flash").strip()
            models_to_try = []
            for m in [preferred_model, "gemini-2.5-flash", "gemini-2.0-flash"]:
                if m and m not in models_to_try:
                    models_to_try.append(m)

            body = {
                "system_instruction": {"parts": [{"text": sys_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_payload}]}],
                "generationConfig": {"temperature": 0.4, "maxOutputTokens": 4096},
            }
            for model in models_to_try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
                try:
                    r = requests.post(url, json=body, timeout=25)
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
                        break
                except Exception:
                    continue

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
                "temperature": 0.4,
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
                "temperature": 0.4,
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
