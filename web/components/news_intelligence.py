"""
StockPredictionPro — Canlı Haber, Olay Şoku & Analist Radarı
Google News RSS ve analist not değişimlerini tarayarak hissede şirkete özel
kötü haber şoku (fabrika durması, erteleme, sulandırma, not indirimi vb.) olup
olmadığını tespit eder; haber kaynaklı düşüşü makro/sektör satışından ayırır.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
import xml.etree.ElementTree as ET
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


SYMBOL_ALIASES: dict[str, list[str]] = {
    "MU": ["micron"],
    "MRVL": ["marvell"],
    "COHR": ["coherent"],
    "RKLB": ["rocket lab"],
    "BE": ["bloom energy"],
    "NVDA": ["nvidia"],
    "AVGO": ["broadcom"],
    "VST": ["vistra"],
    "AMD": ["amd", "advanced micro"],
    "TSM": ["tsmc", "taiwan semiconductor"],
    "LITE": ["lumentum"],
    "EOG": ["eog resources"],
    "VRT": ["vertiv"],
    "CEG": ["constellation energy"],
    "GEV": ["ge vernova"],
    "SMCI": ["super micro", "supermicro"],
    "ARM": ["arm holdings"],
}

SEMIS_SET = {
    "MU", "MRVL", "COHR", "NVDA", "AVGO", "AMD",
    "TSM", "LITE", "SMCI", "ARM", "INTC", "QCOM", "AMAT", "LRCX",
}

RED_EVENTS: dict[str, list[str]] = {
    "Üretim / Operasyon Durması": [
        "halt", "halts", "halted", "suspend", "suspended", "shutdown", "shut down",
        "outage", "fire at", "explosion", "strike", "labor dispute", "work stoppage",
        "stalls", "stalled", "recall", "durdur",
    ],
    "Erteleme / Başarısızlık": [
        "delay", "delays", "delayed", "postpone", "postponed", "scrub", "scrubbed",
        "launch failure", "failed launch", "anomaly", "erteleme", "ertelendi",
    ],
    "Hukuk / Soruşturma": [
        "investigation", "probe", "subpoena", "sec charges", "lawsuit", "class action",
        "fraud", "restatement", "short seller", "short report", "antitrust",
        "soruşturma", "dava",
    ],
    "Kâr Uyarısı / Zayıf Rehberlik": [
        "cuts guidance", "lowers guidance", "guidance cut", "weak guidance",
        "profit warning", "misses estimates", "revenue miss", "below estimates",
        "disappointing outlook",
    ],
    "Hisse Sulandırma": [
        "share offering", "stock offering", "secondary offering", "public offering",
        "dilution", "dilutive", "all-stock", "convertible notes", "at-the-market",
        "bedelli", "sermaye artırımı",
    ],
    "İhracat / Regülasyon": [
        "export ban", "export restriction", "export controls", "sanction",
        "blacklist", "entity list",
    ],
    "Yönetim Krizi": [
        "ceo resigns", "ceo steps down", "cfo resigns", "cfo departs",
        "abrupt departure",
    ],
    "Not İndirimi": [
        "downgrade", "downgrades", "downgraded", "cut to sell",
        "cut to underperform", "cut to neutral",
    ],
    "Finansal Stres": [
        "bankruptcy", "chapter 11", "default", "going concern",
        "iflas", "konkordato",
    ],
}

ORANGE_MACRO: list[str] = [
    "chip stocks", "semiconductor stocks", "chipmakers", "ai bubble", "ai trade",
    "nasdaq", "selloff", "sell-off", "tariff", "rate hike", "yields",
    "memory prices", "nand prices", "dram prices",
]

GREEN_EVENTS: list[str] = [
    "upgrade", "upgrades", "upgraded", "raises guidance", "raised guidance",
    "beats", "record revenue", "record quarter", "wins contract", "awarded",
    "partnership", "buyback", "repurchase", "approval", "successful launch",
]

PRICE_MOVE_WORDS: list[str] = [
    "falls", "drops", "plunges", "crash", "crashed", "tumbles", "slides", "sinks",
]

_STATUS_META = {
    "SOK": ("🔴 Şirkete Özel Kötü Haber Şoku", "#ef5350"),
    "BASKI": ("🟠 Olumsuz Haber Baskısı", "#ff9100"),
    "POZITIF": ("🟢 Olumlu Haber Akışı", "#00c853"),
    "TEMIZ": ("⚪ Haber Akışı Temiz", "#8b9bb4"),
}


def _get_aliases(symbol: str) -> list[str]:
    sym = symbol.strip().upper()
    base = sym.replace(".IS", "")
    if sym in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[sym]
    if base in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[base]
    try:
        from web.components.mobile import COMPANY_NAMES
        comp = COMPANY_NAMES.get(sym) or COMPANY_NAMES.get(base)
        if comp:
            first_word = comp.split()[0].strip(",.").lower()
            if len(first_word) >= 4:
                return [first_word]
    except Exception:
        pass
    return [base.lower()]


def _strip_source_suffix(raw_title: str, source_name: str) -> str:
    title = (raw_title or "").strip()
    if source_name and title.endswith(f" - {source_name}"):
        return title[: -(len(source_name) + 3)].strip()
    if " - " in title:
        head, tail = title.rsplit(" - ", 1)
        if len(tail) <= 45:
            return head.strip()
    return title


@_cache_data(ttl=900, show_spinner=False)
def fetch_news_headlines(symbol: str, days: int = 7) -> list[dict]:
    """Google News RSS üzerinden hisseye ait son haber başlıklarını çeker."""
    sym = symbol.strip().upper()
    is_bist = sym.endswith(".IS")
    base = sym.replace(".IS", "")
    aliases = _get_aliases(sym)
    alias = aliases[0] if aliases else base.lower()

    if is_bist:
        q = f'"{base}" hisse when:{days}d'
        params = {"q": q, "hl": "tr", "gl": "TR", "ceid": "TR:tr"}
    else:
        q = f'"{alias}" stock when:{days}d'
        params = {"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"}

    try:
        resp = requests.get(
            "https://news.google.com/rss/search",
            params=params,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        now_utc = datetime.now(timezone.utc)
        seen_titles: set[str] = set()
        items: list[dict] = []

        for item in root.findall(".//item"):
            raw_t = item.findtext("title") or ""
            src_el = item.find("source")
            source_name = (src_el.text or "").strip() if src_el is not None else ""
            title = _strip_source_suffix(raw_t, source_name)
            if not title:
                continue

            low_key = title.lower()
            if low_key in seen_titles:
                continue
            seen_titles.add(low_key)

            link = (item.findtext("link") or "").strip()
            pub_raw = (item.findtext("pubDate") or "").strip()
            try:
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                else:
                    pub_dt = pub_dt.astimezone(timezone.utc)
            except Exception:
                pub_dt = now_utc

            age_days = max(0.0, (now_utc - pub_dt).total_seconds() / 86400.0)
            if age_days > float(days) + 0.5:
                continue

            items.append({
                "title": title,
                "source": source_name or "Google News",
                "link": link,
                "published": pub_dt,
                "date_str": pub_dt.strftime("%Y-%m-%d"),
                "age_days": round(age_days, 2),
            })

        items.sort(key=lambda x: x["published"], reverse=True)
        return items[:40]
    except Exception:
        return []


@_cache_data(ttl=1800, show_spinner=False)
def fetch_analyst_actions(symbol: str, days: int = 10) -> list[dict]:
    """yfinance üzerinden son analist not ve hedef fiyat değişikliklerini çeker."""
    sym = symbol.strip().upper()
    if sym.endswith(".IS"):
        return []

    try:
        ud = yf.Ticker(sym).upgrades_downgrades
        if ud is None or ud.empty:
            return []

        now_utc = datetime.now(timezone.utc)
        actions: list[dict] = []
        for idx, row in ud.head(25).iterrows():
            try:
                dt = pd.to_datetime(idx)
                if dt.tzinfo is None:
                    dt = dt.tz_localize(timezone.utc)
                else:
                    dt = dt.tz_convert(timezone.utc)
            except Exception:
                continue

            age_days = max(0.0, (now_utc - dt).total_seconds() / 86400.0)
            if age_days > float(days):
                continue

            firm = str(row.get("Firm") or "Kurum").strip()
            act = str(row.get("Action") or "").strip().lower()
            from_g = str(row.get("FromGrade") or "").strip()
            to_g = str(row.get("ToGrade") or "").strip()
            pt_act = str(row.get("priceTargetAction") or "").strip()
            curr_pt = row.get("currentPriceTarget")
            prior_pt = row.get("priorPriceTarget")

            curr_pt_f = float(curr_pt) if pd.notna(curr_pt) else 0.0
            prior_pt_f = float(prior_pt) if pd.notna(prior_pt) else 0.0

            if act == "down":
                grade_txt = f"{from_g} → {to_g}" if (from_g or to_g) else "Not İndirimi"
                actions.append({
                    "firm": firm,
                    "title": f"{firm}: {grade_txt}",
                    "category_label": "Not İndirimi",
                    "weight": -3.0,
                    "is_red": True,
                    "age_days": round(age_days, 2),
                    "published": dt,
                    "date_str": dt.strftime("%Y-%m-%d"),
                })
            elif pt_act == "Lowers" and prior_pt_f > 0 and curr_pt_f > 0:
                # Hisse bölünmesi (örn. 4:1, 8:1, 10:1 split) kaynaklı sahte %75+ düşüş artefaktlarını ele
                if prior_pt_f >= curr_pt_f * 3.5:
                    continue
                cut_pct = ((prior_pt_f - curr_pt_f) / prior_pt_f) * 100.0
                if cut_pct >= 15.0:
                    actions.append({
                        "firm": firm,
                        "title": f"{firm}: Hedef ${prior_pt_f:.0f} → ${curr_pt_f:.0f} (-%{cut_pct:.0f})",
                        "category_label": "Hedef Fiyat Sert Düşürüldü",
                        "weight": -1.5,
                        "is_red": False,
                        "age_days": round(age_days, 2),
                        "published": dt,
                        "date_str": dt.strftime("%Y-%m-%d"),
                    })
            elif act == "up":
                grade_txt = f"{from_g} → {to_g}" if (from_g or to_g) else "Not Artırımı"
                actions.append({
                    "firm": firm,
                    "title": f"{firm}: {grade_txt}",
                    "category_label": "Not Artırımı",
                    "weight": 2.0,
                    "is_red": False,
                    "age_days": round(age_days, 2),
                    "published": dt,
                    "date_str": dt.strftime("%Y-%m-%d"),
                })
            elif pt_act == "Raises" and curr_pt_f > 0:
                pt_txt = f"${prior_pt_f:.0f} → ${curr_pt_f:.0f}" if prior_pt_f > 0 else f"${curr_pt_f:.0f}"
                actions.append({
                    "firm": firm,
                    "title": f"{firm}: Hedef Artırımı ({pt_txt})",
                    "category_label": "Hedef Fiyat Artırıldı",
                    "weight": 1.0,
                    "is_red": False,
                    "age_days": round(age_days, 2),
                    "published": dt,
                    "date_str": dt.strftime("%Y-%m-%d"),
                })

        return actions
    except Exception:
        return []


_BENIGN_REGEXES: list[str] = [
    r"\b(?:space|lunar|mars|venus|deep-space|solar|interplanetary|nasa)\s+probes?\b",
    r"\bstrike(?:s|d|ing)?\b[^.,;]{0,30}\b(?:deal|deals|agreement|partnership|pact|alliance|contract|price|prices)\b",
    r"\b(?:options?|calls?|puts?)\b[^.,;]{0,20}\bstrikes?\b",
    r"\bhalt(?:s|ed|ing)?\b[^.,;]{0,30}\b(?:losing|losses|slide|drop|decline|selloff|sell-off|slump|skid|bleeding)\b",
    r"\bby\s+default\b",
    r"\b(?:analysts?|investors?|traders?)\s+recalls?\b",
]


def _has_keyword(text_low: str, kw: str) -> bool:
    """Kelime sınırı (word-boundary) duyarlı eşleşme yapar; alt-dize hatalarını önler."""
    pattern = rf"(?<![a-zçğıöşü0-9]){re.escape(kw.lower())}(?:s|ed|ing)?(?![a-zçğıöşü0-9])" if len(kw) >= 4 and " " not in kw else rf"(?<![a-zçğıöşü0-9]){re.escape(kw.lower())}(?![a-zçğıöşü0-9])"
    return bool(re.search(pattern, text_low))


def classify_headline(title: str, symbol: str) -> dict[str, Any]:
    """Haber başlığını olay kategorisine ayırır ve şirkete özel olup olmadığını belirler."""
    sym = symbol.strip().upper()
    base = sym.replace(".IS", "")
    aliases = _get_aliases(sym)
    low = (title or "").lower()
    cleaned_low = low
    for rx in _BENIGN_REGEXES:
        cleaned_low = re.sub(rx, " ", cleaned_low)

    company_specific = any(_has_keyword(low, a) for a in aliases) or bool(
        re.search(rf"\b{re.escape(base)}\b", title or "")
    )

    for label, keywords in RED_EVENTS.items():
        if any(_has_keyword(cleaned_low, kw) for kw in keywords):
            return {
                "category_level": "RED",
                "category_label": label,
                "company_specific": company_specific,
            }

    if any(_has_keyword(cleaned_low, kw) for kw in GREEN_EVENTS):
        return {
            "category_level": "GREEN",
            "category_label": "Pozitif Katalizör",
            "company_specific": company_specific,
        }

    if any(_has_keyword(cleaned_low, kw) for kw in ORANGE_MACRO):
        return {
            "category_level": "ORANGE",
            "category_label": "Sektör / Makro Baskı",
            "company_specific": company_specific,
        }

    if any(_has_keyword(cleaned_low, kw) for kw in PRICE_MOVE_WORDS):
        return {
            "category_level": "PRICE_MOVE",
            "category_label": "Fiyat Hareketi Özeti",
            "company_specific": company_specific,
        }

    return {
        "category_level": "NEUTRAL",
        "category_label": "Genel Haber",
        "company_specific": company_specific,
    }


def assess_news_absorption(df_daily: pd.DataFrame | None, shock_date: Any) -> dict[str, Any]:
    """Kötü haber sonrası fiyatın yeni dip yapmayı bırakıp taban oluşturup oluşturmadığını ölçer."""
    empty_res = {"absorbed": False, "post_shock_low": None, "sessions_since_shock": 0}
    if df_daily is None or df_daily.empty or shock_date is None:
        return empty_res

    try:
        s_date = shock_date.date() if hasattr(shock_date, "date") else pd.to_datetime(shock_date).date()
        idx_dates = pd.Index([pd.Timestamp(ts).date() for ts in df_daily.index])
        sub = df_daily.loc[idx_dates >= s_date]
        if sub.empty:
            return empty_res

        sessions_since = int(len(sub))
        lows = pd.to_numeric(sub["Low"], errors="coerce").dropna()
        closes = pd.to_numeric(sub["Close"], errors="coerce").dropna()
        if lows.empty or len(closes) < 3:
            post_low = float(lows.min()) if not lows.empty else None
            return {
                "absorbed": False,
                "post_shock_low": round(post_low, 2) if post_low is not None else None,
                "sessions_since_shock": sessions_since,
            }

        post_low = float(lows.min())
        low_pos = int(np.argmin(lows.values))
        last_3_closes = closes.iloc[-3:]
        absorbed = bool(
            sessions_since >= 3
            and low_pos < (len(lows) - 3)
            and bool((last_3_closes > post_low).all())
            and float(closes.iloc[-1]) >= post_low * 1.03
        )
        return {
            "absorbed": absorbed,
            "post_shock_low": round(post_low, 2),
            "sessions_since_shock": sessions_since,
        }
    except Exception:
        return empty_res


def _recency_multiplier(age_days: float) -> float:
    if age_days <= 2.0:
        return 1.0
    if age_days <= 5.0:
        return 0.6
    return 0.3


def get_news_intelligence(symbol: str, df_daily: pd.DataFrame | None = None) -> dict[str, Any]:
    """Hissenin son haber, analist notu ve olay şoku istihbaratını tek pakette toplar."""
    sym = symbol.strip().upper()
    fallback: dict[str, Any] = {
        "symbol": sym,
        "status": "TEMIZ",
        "status_label": _STATUS_META["TEMIZ"][0],
        "status_color": _STATUS_META["TEMIZ"][1],
        "score": 0,
        "veto_active": False,
        "absorbed": False,
        "post_shock_low": None,
        "shock_date": None,
        "red_events": [],
        "positive_events": [],
        "headlines": [],
        "analyst_actions": [],
        "fetched_ok": False,
        "updated_at": datetime.now().strftime("%H:%M:%S"),
    }

    try:
        raw_headlines = fetch_news_headlines(sym, days=7)
        analyst_actions = fetch_analyst_actions(sym, days=10)
        fetched_ok = bool(raw_headlines or analyst_actions)

        weighted_sum = 0.0
        red_events: list[dict[str, Any]] = []
        positive_events: list[dict[str, Any]] = []
        classified_headlines: list[dict[str, Any]] = []
        shock_candidates: list[datetime] = []

        for h in raw_headlines:
            cls = classify_headline(h["title"], sym)
            lvl = cls["category_level"]
            comp_spec = cls["company_specific"]
            mult = _recency_multiplier(float(h["age_days"]))

            if lvl == "RED":
                base_w = -3.0 if comp_spec else -1.0
            elif lvl == "ORANGE":
                base_w = -1.0
            elif lvl == "GREEN":
                base_w = 2.0 if comp_spec else 0.0
            elif lvl == "PRICE_MOVE":
                base_w = -0.5
            else:
                base_w = 0.0

            weighted_sum += base_w * mult

            entry = {
                "title": h["title"],
                "source": h["source"],
                "date": h["date_str"],
                "link": h["link"],
                "level": lvl,
                "category_label": cls["category_label"],
                "company_specific": comp_spec,
            }
            classified_headlines.append(entry)

            if lvl == "RED" and comp_spec:
                red_events.append({
                    "title": h["title"],
                    "source": h["source"],
                    "date": h["date_str"],
                    "category_label": cls["category_label"],
                })
                if float(h["age_days"]) <= 5.0:
                    shock_candidates.append(h["published"])
            elif lvl == "GREEN" and comp_spec:
                positive_events.append({
                    "title": h["title"],
                    "source": h["source"],
                    "date": h["date_str"],
                    "category_label": cls["category_label"],
                })

        for a in analyst_actions:
            mult = _recency_multiplier(float(a["age_days"]))
            weighted_sum += float(a["weight"]) * mult
            if a.get("is_red"):
                red_events.append({
                    "title": a["title"],
                    "source": a["firm"],
                    "date": a["date_str"],
                    "category_label": a["category_label"],
                })
                if float(a["age_days"]) <= 5.0:
                    shock_candidates.append(a["published"])

        score = int(np.clip(round(weighted_sum * 8.0), -100, 100))
        has_shock = bool(shock_candidates)
        newest_shock_dt = max(shock_candidates) if shock_candidates else None

        absorption = {"absorbed": False, "post_shock_low": None, "sessions_since_shock": 0}
        if has_shock and newest_shock_dt is not None:
            hist_df = df_daily
            if hist_df is None or hist_df.empty:
                try:
                    hist_df = yf.Ticker(sym).history(period="2mo", interval="1d")
                except Exception:
                    hist_df = pd.DataFrame()
            absorption = assess_news_absorption(hist_df, newest_shock_dt)

        if has_shock:
            status = "SOK"
        elif score <= -25:
            status = "BASKI"
        elif score >= 25:
            status = "POZITIF"
        else:
            status = "TEMIZ"

        absorbed = bool(absorption["absorbed"])
        veto_active = bool(status == "SOK" and not absorbed)
        status_label, status_color = _STATUS_META[status]

        return {
            "symbol": sym,
            "status": status,
            "status_label": status_label,
            "status_color": status_color,
            "score": score,
            "veto_active": veto_active,
            "absorbed": absorbed,
            "post_shock_low": absorption["post_shock_low"],
            "shock_date": newest_shock_dt.strftime("%Y-%m-%d") if newest_shock_dt else None,
            "red_events": red_events[:5],
            "positive_events": positive_events[:3],
            "headlines": classified_headlines[:8],
            "analyst_actions": [
                {
                    "firm": a["firm"],
                    "title": a["title"],
                    "category_label": a["category_label"],
                    "date": a["date_str"],
                }
                for a in analyst_actions[:5]
            ],
            "fetched_ok": fetched_ok,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
        }
    except Exception:
        return fallback


@_cache_data(ttl=900, show_spinner=False)
def _benchmark_closes(bench_symbol: str) -> pd.Series:
    try:
        df = yf.Ticker(bench_symbol).history(period="3mo", interval="1d")
        if df is not None and not df.empty and "Close" in df.columns:
            return pd.to_numeric(df["Close"], errors="coerce").dropna()
    except Exception:
        pass
    return pd.Series(dtype=float)


def diagnose_drawdown(
    symbol: str,
    news: dict[str, Any],
    regime_code: str,
    df_daily: pd.DataFrame | None,
) -> dict[str, Any]:
    """Hissedeki düşüşün şirket hasarı mı yoksa makro/sektör satışı mı olduğunu teşhis eder."""
    sym = symbol.strip().upper()
    base = sym.replace(".IS", "")
    if sym.endswith(".IS"):
        bench = "XU100.IS"
    elif base in SEMIS_SET:
        bench = "SMH"
    else:
        bench = "QQQ"

    try:
        stock_1m = 0.0
        if df_daily is not None and not df_daily.empty and "Close" in df_daily.columns:
            sc = pd.to_numeric(df_daily["Close"], errors="coerce").dropna()
            if len(sc) >= 2:
                prev_idx = -min(21, len(sc))
                prev_val = float(sc.iloc[prev_idx])
                if prev_val > 0:
                    stock_1m = ((float(sc.iloc[-1]) / prev_val) - 1.0) * 100.0

        bc = _benchmark_closes(bench)
        bench_1m = 0.0
        if len(bc) >= 2:
            prev_idx = -min(21, len(bc))
            prev_val = float(bc.iloc[prev_idx])
            if prev_val > 0:
                bench_1m = ((float(bc.iloc[-1]) / prev_val) - 1.0) * 100.0

        rel = stock_1m - bench_1m

        if news.get("status") == "SOK":
            code = "SIRKET_HASARI"
            label = "🔴 Şirket Hasarı / Kötü Haber"
            color = "#ef5350"
            advice = "Ucuzlamış değil, hasar almış olabilir. Haber etkisi sindirilip dip oturana kadar ortalama düşürme."
        elif regime_code in ("KRIZ_YUKSEK_RISK", "DUZELTME_BASKISI") and rel >= -8.0:
            code = "MAKRO_SEKTOR"
            label = "🟠 Makro / Sektör Satışı"
            color = "#ff9100"
            advice = "Şirkete özel kötü haber yok; düşüş piyasa/sektör kaynaklı. 1. kademe yerine sadece 2. kademe ve dönüş onayı bekle."
        elif rel < -8.0:
            code = "AYRISAN_ZAYIFLIK"
            label = "🟣 Sektörden Ayrışan Zayıflık"
            color = "#ab47bc"
            advice = "Haber bulunamadı ama sektörden çok daha sert düşüyor; gizli bir sorun olabilir, dikkatli ol."
        else:
            code = "SAGLIKLI_DUZELTME"
            label = "🟢 Sağlıklı Teknik Düzeltme"
            color = "#00c853"
            advice = "Haberler temiz ve düşüş sektörle uyumlu; planlı alım bölgeleri geçerli."

        return {
            "code": code,
            "label": label,
            "color": color,
            "advice": advice,
            "stock_1m_pct": round(stock_1m, 1),
            "bench_1m_pct": round(bench_1m, 1),
            "benchmark": bench,
        }
    except Exception:
        return {
            "code": "BILINMIYOR",
            "label": "⚪ Teşhis Bekleniyor",
            "color": "#8b9bb4",
            "advice": "Haber ve sektör karşılaştırması tamamlanamadı; mevcut teknik desteklere sadık kal.",
            "stock_1m_pct": 0.0,
            "bench_1m_pct": 0.0,
            "benchmark": bench,
        }
