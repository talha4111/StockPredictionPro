"""
Piyasa tarama verisi yükleyici.
Öncelik sırası:
  1. GitHub'daki `scan-data` dalında otomatik güncellenen taze JSON (her iş günü)
  2. Yerel veritabanındaki en son tarama (yedek)
Paper-shadow (model_role dolu) satırlar ve aynı hissenin tekrarları listeden elenir.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")
REMOTE_URL = "https://raw.githubusercontent.com/talha4111/StockPredictionPro/scan-data/web/data/piyasa_tarama_son.json"

COLUMN_MAP = {
    "sembol": "Sembol",
    "sektor": "Sektör",
    "ai_skor": "Faktör Skor (%)",
    "decision": "Karar",
    "fiyat": "Fiyat ($)",
    "rsi": "RSI",
    "quality_score": "Kalite",
    "value_score": "Değer",
    "momentum_score": "Momentum",
    "risk_score": "Risk",
    "as_of_date": "Tarama Tarihi",
}


def _frame_from_rows(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df = df.rename(columns=COLUMN_MAP)
    for col in ["Faktör Skor (%)", "Fiyat ($)", "RSI", "Kalite", "Değer", "Momentum", "Risk"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").round(1 if col != "Fiyat ($)" else 2)
    df = df.sort_values("Faktör Skor (%)", ascending=False).drop_duplicates("Sembol").reset_index(drop=True)
    df.insert(0, "Sıra", range(1, len(df) + 1))
    return df[["Sıra"] + [c for c in COLUMN_MAP.values() if c in df.columns]]


@st.cache_data(ttl=600, show_spinner=False)
def _load_remote_payload() -> dict:
    try:
        r = requests.get(REMOTE_URL, timeout=8)
        if r.status_code == 200:
            payload = r.json()
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return {}


@st.cache_data(ttl=600, show_spinner=False)
def _load_remote() -> tuple[pd.DataFrame, str]:
    payload = _load_remote_payload()
    if payload:
        df = _frame_from_rows(payload.get("rows", []))
        if not df.empty:
            return df, payload.get("generated_at", "")
    return pd.DataFrame(), ""


def load_remote_metadata() -> dict:
    """Uzaktaki scan-data JSON'ından shadow_summary, performance_summary ve last_update bilgilerini döndürür."""
    payload = _load_remote_payload()
    if not payload:
        return {}
    return {
        "as_of_date": payload.get("as_of_date"),
        "generated_at": payload.get("generated_at"),
        "shadow_summary": payload.get("shadow_summary"),
        "performance_summary": payload.get("performance_summary"),
        "last_update": payload.get("last_update"),
    }


@st.cache_data(ttl=120, show_spinner=False)
def _load_local() -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        last = conn.execute(
            "SELECT MAX(as_of_date) FROM hisse_sinyalleri WHERE model_role IS NULL"
        ).fetchone()[0]
        if not last:
            conn.close()
            return pd.DataFrame()
        rows = conn.execute(
            """SELECT sembol, sektor, ai_skor, decision, fiyat, rsi, quality_score, value_score,
                      momentum_score, risk_score, as_of_date
               FROM hisse_sinyalleri WHERE as_of_date = ? AND model_role IS NULL""",
            (last,),
        ).fetchall()
        conn.close()
        return _frame_from_rows([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


def load_latest_scan() -> tuple[pd.DataFrame, str]:
    """(DataFrame, kaynak) döndürür. Uzak ve yerelden hangisi daha yeniyse onu seçer."""
    remote_df, _ = _load_remote()
    local_df = _load_local()

    def _d(df):
        return str(df["Tarama Tarihi"].iloc[0]) if not df.empty else ""

    if not remote_df.empty and _d(remote_df) >= _d(local_df):
        return remote_df, "otomatik"
    if not local_df.empty:
        return local_df, "yerel"
    return remote_df, "yok"


def scan_age_days(scan_date: str) -> int | None:
    try:
        return (date.today() - datetime.strptime(str(scan_date)[:10], "%Y-%m-%d").date()).days
    except Exception:
        return None
