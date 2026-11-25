"""
StockPredictionPro — Sinyal Karnesi (Signal Journal)
Sistemin ürettiği 'AL' sinyallerini ve yeni güvenlik kurallarının engellediği
eski tip alım sinyallerini ('ENGELLENDI') kalıcı olarak kaydeder ve 5/10/15 işlem
günü sonraki gerçek piyasa sonuçlarını (Hedef / Stop / Getiri) otomatik puanlar.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
import uuid
from typing import Any

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

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_JOURNAL_PATH = os.path.join(PROJECT_ROOT, "web", "data", "signal_journal.json")
JOURNAL_PATH = os.environ.get("SIGNAL_JOURNAL_PATH") or DEFAULT_JOURNAL_PATH
REMOTE_URL = "https://raw.githubusercontent.com/talha4111/StockPredictionPro/alert-state/web/data/signal_journal.json"


def _resolve_path(path: str | None = None) -> str:
    return path or os.environ.get("SIGNAL_JOURNAL_PATH") or DEFAULT_JOURNAL_PATH


def load_journal(path: str | None = None) -> list[dict[str, Any]]:
    target = _resolve_path(path)
    if not os.path.exists(target):
        return []
    try:
        with open(target, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def save_journal(records: list[dict[str, Any]], path: str | None = None) -> None:
    target = _resolve_path(path)
    parent = os.path.dirname(os.path.abspath(target))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def record_signal(res: dict[str, Any], path: str | None = None) -> dict[str, Any] | None:
    """Alım fırsatlarını ('AL') ve yeni kilitlerin durdurduğu sinyalleri ('ENGELLENDI') kaydeder."""
    if not isinstance(res, dict) or not res.get("symbol"):
        return None

    if res.get("state_code") == "ALIM_FIRSATI":
        sig_type = "AL"
    elif res.get("legacy_buy"):
        sig_type = "ENGELLENDI"
    else:
        return None

    sym = str(res["symbol"]).strip().upper()
    today_dt = datetime.now()
    today_str = today_dt.strftime("%Y-%m-%d")

    records = load_journal(path)
    for rec in records:
        if rec.get("symbol") == sym and rec.get("type") == sig_type:
            try:
                rec_d = datetime.strptime(str(rec.get("date", ""))[:10], "%Y-%m-%d").date()
                if 0 <= (today_dt.date() - rec_d).days <= 5:
                    return None
            except Exception:
                continue

    ai_pred = res.get("ai_pred") or {}
    news = res.get("news") or {}
    diag = res.get("diagnosis") or {}

    record: dict[str, Any] = {
        "id": uuid.uuid4().hex[:8],
        "symbol": sym,
        "type": sig_type,
        "date": today_str,
        "ts": today_dt.isoformat(),
        "entry_price": round(float(res.get("current_price") or 0.0), 2),
        "zone1_low": res.get("zone1_low"),
        "zone1_high": res.get("zone1_high"),
        "zone2_low": res.get("zone2_low"),
        "zone2_high": res.get("zone2_high"),
        "stop_level": res.get("stop_level"),
        "target1": res.get("target1"),
        "ai_win_prob": int(ai_pred.get("win_prob_pct", 50)),
        "vix_value": res.get("vix_value"),
        "regime_code": res.get("regime_code"),
        "news_status": news.get("status", "TEMIZ"),
        "news_score": news.get("score", 0),
        "diagnosis_code": diag.get("code") if isinstance(diag, dict) else None,
        "gates": list(res.get("gates") or []),
        "size_hint": res.get("size_hint", "YOK"),
        "status": "ACIK",
        "ret_5d": None,
        "ret_10d": None,
        "ret_15d": None,
        "result": None,
        "max_drawdown_pct": None,
        "evaluated_at": None,
    }
    records.append(record)
    save_journal(records, path)
    return record


def evaluate_signals(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Açık sinyalleri gerçek fiyat verileriyle değerlendirip güncellenmiş kopyalarını döndürür."""
    updated = [dict(r) for r in records]
    open_syms = sorted({
        str(r["symbol"]).upper()
        for r in updated
        if r.get("symbol") and (r.get("status") == "ACIK" or r.get("realized_ret_pct") is None or r.get("ret_15d") is None)
    })
    if not open_syms:
        return updated

    hist_map: dict[str, pd.DataFrame] = {}
    for sym in open_syms:
        try:
            df = yf.Ticker(sym).history(period="3mo", interval="1d")
            if df is not None and not df.empty:
                hist_map[sym] = df
        except Exception:
            pass

    now_iso = datetime.now().isoformat()
    for rec in updated:
        if rec.get("status") != "ACIK" and rec.get("realized_ret_pct") is not None and rec.get("ret_15d") is not None:
            continue
        sym = str(rec.get("symbol") or "").upper()
        df = hist_map.get(sym)
        if df is None or df.empty:
            continue

        try:
            sig_date = datetime.strptime(str(rec.get("date", ""))[:10], "%Y-%m-%d").date()
            idx_dates = pd.Index([pd.Timestamp(ts).date() for ts in df.index])
            bars = df.loc[idx_dates > sig_date]
            if bars.empty:
                continue

            entry = float(rec.get("entry_price") or 0.0)
            stop_lvl = float(rec.get("stop_level") or 0.0)
            target1 = float(rec.get("target1") or 0.0)
            if entry <= 0:
                continue

            closes = pd.to_numeric(bars["Close"], errors="coerce")
            lows = pd.to_numeric(bars["Low"], errors="coerce")
            highs = pd.to_numeric(bars["High"], errors="coerce")

            if len(closes) >= 5 and pd.notna(closes.iloc[4]):
                rec["ret_5d"] = round(((float(closes.iloc[4]) / entry) - 1.0) * 100.0, 2)
            if len(closes) >= 10 and pd.notna(closes.iloc[9]):
                rec["ret_10d"] = round(((float(closes.iloc[9]) / entry) - 1.0) * 100.0, 2)
            if len(closes) >= 15 and pd.notna(closes.iloc[14]):
                rec["ret_15d"] = round(((float(closes.iloc[14]) / entry) - 1.0) * 100.0, 2)

            if rec.get("status") != "ACIK":
                # Önceden kapanmış kaydın eksik realized_ret_pct alanını tamamla
                if rec.get("realized_ret_pct") is None:
                    res_t = rec.get("result")
                    if res_t == "STOP" and stop_lvl > 0:
                        rec["realized_ret_pct"] = round(((stop_lvl / entry) - 1.0) * 100.0, 2)
                    elif res_t == "HEDEF" and target1 > 0:
                        rec["realized_ret_pct"] = round(((target1 / entry) - 1.0) * 100.0, 2)
                    elif rec.get("ret_15d") is not None:
                        rec["realized_ret_pct"] = rec["ret_15d"]
                continue

            eval_len = min(15, len(bars))
            result = None
            realized_ret = None
            exit_bar_count = eval_len
            for i in range(eval_len):
                b_low = float(lows.iloc[i]) if pd.notna(lows.iloc[i]) else entry
                b_high = float(highs.iloc[i]) if pd.notna(highs.iloc[i]) else entry
                if stop_lvl > 0 and b_low <= stop_lvl:
                    result = "STOP"
                    realized_ret = round(((stop_lvl / entry) - 1.0) * 100.0, 2)
                    exit_bar_count = i + 1
                    break
                if target1 > 0 and b_high >= target1:
                    result = "HEDEF"
                    realized_ret = round(((target1 / entry) - 1.0) * 100.0, 2)
                    exit_bar_count = i + 1
                    break

            if result is None and len(bars) >= 15:
                result = "SURE_DOLDU"
                realized_ret = rec.get("ret_15d")

            eval_lows = lows.iloc[:exit_bar_count].dropna()
            if not eval_lows.empty:
                min_low = float(eval_lows.min())
                rec["max_drawdown_pct"] = round(((min_low / entry) - 1.0) * 100.0, 2)

            if result is not None:
                rec["result"] = result
                rec["realized_ret_pct"] = realized_ret
                rec["status"] = "KAPANDI"
            rec["evaluated_at"] = now_iso
        except Exception:
            continue

    return updated


def evaluate_open_signals(path: str | None = None) -> list[dict[str, Any]]:
    records = load_journal(path)
    if not records:
        return []
    updated = evaluate_signals(records)
    save_journal(updated, path)
    return updated


@_cache_data(ttl=600, show_spinner=False)
def _fetch_remote_journal() -> list[dict[str, Any]]:
    try:
        resp = requests.get(REMOTE_URL, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
    except Exception:
        pass
    return []


def load_journal_for_ui() -> list[dict[str, Any]]:
    remote = _fetch_remote_journal()
    local = load_journal()
    chosen = remote if len(remote) >= len(local) else local
    if not chosen:
        return []
    return evaluate_signals(chosen)


def journal_summary(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """'AL' ve 'ENGELLENDI' grupları için ayrı başarı istatistikleri hesaplar."""
    out: dict[str, dict[str, Any]] = {}
    for sig_type in ("AL", "ENGELLENDI"):
        group = [r for r in records if r.get("type") == sig_type]
        closed = [r for r in group if r.get("status") == "KAPANDI"]
        hedef_cnt = sum(1 for r in closed if r.get("result") == "HEDEF")
        stop_cnt = sum(1 for r in closed if r.get("result") == "STOP")
        sure_cnt = sum(1 for r in closed if r.get("result") == "SURE_DOLDU")
        closed_cnt = len(closed)

        r15 = [
            float(r["realized_ret_pct"] if r.get("realized_ret_pct") is not None else r["ret_15d"])
            for r in closed
            if (r.get("realized_ret_pct") is not None or r.get("ret_15d") is not None)
        ]
        r5 = [float(r["ret_5d"]) for r in group if r.get("ret_5d") is not None]

        out[sig_type] = {
            "total": len(group),
            "closed": closed_cnt,
            "hedef": hedef_cnt,
            "hedef_pct": round((hedef_cnt / closed_cnt) * 100.0, 1) if closed_cnt else 0.0,
            "stop": stop_cnt,
            "stop_pct": round((stop_cnt / closed_cnt) * 100.0, 1) if closed_cnt else 0.0,
            "sure_doldu": sure_cnt,
            "avg_ret_15d": round(sum(r15) / len(r15), 2) if r15 else None,
            "avg_ret_5d": round(sum(r5) / len(r5), 2) if r5 else None,
        }
    return out
