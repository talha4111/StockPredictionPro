"""
StockPredictionPro — Portföy Risk Freni & Yoğunlaşma Kontrolü
Aynı hissede kontrolsüz ortalama düşürmeyi engeller (en az %15 düşük fiyat,
temiz haber ve VIX < 25 şartı) ve tek hisse / tek sektör yoğunlaşmasını uyarır.
"""
from __future__ import annotations

from typing import Any
import yfinance as yf


SECTOR_MAP: dict[str, str] = {
    "MU": "Yarı İletken / AI Donanım",
    "MRVL": "Yarı İletken / AI Donanım",
    "COHR": "Yarı İletken / AI Donanım",
    "NVDA": "Yarı İletken / AI Donanım",
    "AVGO": "Yarı İletken / AI Donanım",
    "AMD": "Yarı İletken / AI Donanım",
    "TSM": "Yarı İletken / AI Donanım",
    "LITE": "Yarı İletken / AI Donanım",
    "SMCI": "Yarı İletken / AI Donanım",
    "ARM": "Yarı İletken / AI Donanım",
    "INTC": "Yarı İletken / AI Donanım",
    "QCOM": "Yarı İletken / AI Donanım",
    "RKLB": "Uzay",
    "BE": "Enerji / Altyapı",
    "VST": "Enerji / Altyapı",
    "CEG": "Enerji / Altyapı",
    "GEV": "Enerji / Altyapı",
    "VRT": "Enerji / Altyapı",
    "EOG": "Petrol",
}


def get_symbol_sector(symbol: str) -> str:
    sym = (symbol or "").strip().upper()
    if sym.endswith(".IS"):
        return "BIST"
    return SECTOR_MAP.get(sym, "Diğer")


def evaluate_buy_permission(
    symbol: str,
    current_price: float,
    open_positions: dict[str, Any] | None,
    news: dict[str, Any] | None,
    vix_value: float,
) -> dict[str, Any]:
    """
    Portföyde zaten açık olan bir hissede ekleme / ortalama düşürme izni verir.
    Üç şartın tamamı sağlanmazsa alımı frenler:
      1) Son alış fiyatının en az %15 altında olmak
      2) Son 7 günde çözülmemiş şirkete özel kötü haber şoku olmaması
      3) VIX < 25
    """
    sym = (symbol or "").strip().upper()
    positions = open_positions or {}
    if sym not in positions:
        return {
            "held": False,
            "allowed": True,
            "reasons": [],
            "last_buy_price": None,
            "drop_from_last_buy_pct": None,
            "lot_count": 0,
        }

    pos = positions[sym]
    lots = pos.get("lotlar") or []
    last_buy = float(lots[-1]["fiyat_usd"]) if lots else float(pos.get("ortalama_fiyat_usd") or 0.0)
    price = float(current_price or 0.0)
    drop_pct = ((last_buy - price) / last_buy) * 100.0 if (last_buy > 0 and price > 0) else 0.0
    vix = float(vix_value if vix_value is not None else 18.5)

    reasons: list[str] = []
    if drop_pct < 15.0:
        reasons.append(
            f"Son alışın (${last_buy:.2f}) sadece %{drop_pct:.1f} altında; en az %15 aşağıda olmalı"
        )
    if news and news.get("status") == "SOK" and not news.get("absorbed"):
        reasons.append("Son 7 günde şirkete özel kötü haber var")
    if vix >= 25.0:
        reasons.append(f"VIX {vix:.1f} (25'in altına inmeden ortalama düşürme yok)")

    return {
        "held": True,
        "allowed": len(reasons) == 0,
        "reasons": reasons,
        "last_buy_price": round(last_buy, 2),
        "drop_from_last_buy_pct": round(drop_pct, 1),
        "lot_count": len(lots) or int(pos.get("lot_sayisi", 0)),
    }


def portfolio_concentration(
    open_positions: dict[str, Any] | None,
    price_map: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Portföyün hisse ve sektör bazlı yoğunlaşmasını hesaplar ve eşik aşımında uyarır."""
    positions = open_positions or {}
    if not positions:
        return {
            "by_symbol": {},
            "by_sector": {},
            "warnings": [],
            "total_value_usd": 0.0,
        }

    prices = dict(price_map or {})
    sym_values: dict[str, float] = {}
    sector_values: dict[str, float] = {}
    total_val = 0.0

    for sym, pos in positions.items():
        qty = float(pos.get("toplam_adet") or 0.0)
        if qty <= 0:
            continue
        p = prices.get(sym)
        if not p or p <= 0:
            try:
                hist = yf.Ticker(sym).history(period="5d", interval="1d")
                if hist is not None and not hist.empty:
                    p = float(hist["Close"].dropna().iloc[-1])
            except Exception:
                p = None
        if not p or p <= 0:
            p = float(pos.get("ortalama_fiyat_usd") or 0.0)

        val = qty * float(p)
        sym_values[sym] = val
        sec = get_symbol_sector(sym)
        sector_values[sec] = sector_values.get(sec, 0.0) + val
        total_val += val

    if total_val <= 0:
        return {
            "by_symbol": {},
            "by_sector": {},
            "warnings": [],
            "total_value_usd": 0.0,
        }

    by_symbol = {
        sym: {
            "value_usd": round(val, 2),
            "weight_pct": round((val / total_val) * 100.0, 1),
            "sector": get_symbol_sector(sym),
        }
        for sym, val in sorted(sym_values.items(), key=lambda x: x[1], reverse=True)
    }
    by_sector = {
        sec: {
            "value_usd": round(val, 2),
            "weight_pct": round((val / total_val) * 100.0, 1),
        }
        for sec, val in sorted(sector_values.items(), key=lambda x: x[1], reverse=True)
    }

    warnings: list[str] = []
    for sym, info in by_symbol.items():
        w = info["weight_pct"]
        if w > 40.0:
            warnings.append(f"Portföyünün %{w:.0f}'i tek hissede ({sym})")
    for sec, info in by_sector.items():
        w = info["weight_pct"]
        if w > 60.0:
            warnings.append(f"Portföyünün %{w:.0f}'i {sec} sektöründe")

    return {
        "by_symbol": by_symbol,
        "by_sector": by_sector,
        "warnings": warnings,
        "total_value_usd": round(total_val, 2),
    }
