from __future__ import annotations

import json
import math
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "trading_bot.db"
TRADING_INCOME_TYPES = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _floatla(deger: Any, varsayilan: float = 0.0) -> float:
    try:
        sonuc = float(deger)
        return sonuc if math.isfinite(sonuc) else varsayilan
    except Exception:
        return varsayilan


def _ms_to_str(ms: int | float | None) -> str:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _sembol_id(sembol: Any) -> str:
    temiz = str(sembol or "").upper().replace(":USDT", "").replace("/", "")
    if temiz and not temiz.endswith("USDT"):
        temiz = f"{temiz}USDT"
    return temiz


def demo_offset_oku(path: str | Path = "ayar.json") -> float:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _floatla(json.load(f).get("demo_bakiye_offset", 0.0))
    except Exception:
        return 0.0


def _usdt_asset(info: dict[str, Any]) -> dict[str, Any]:
    assets = info.get("assets") if isinstance(info, dict) else []
    if isinstance(assets, list):
        for asset in assets:
            if isinstance(asset, dict) and asset.get("asset") == "USDT":
                return asset
    return {}


def bakiye_ozeti_getir(borsa_istemci, offset: float | None = None) -> dict[str, Any]:
    offset = demo_offset_oku() if offset is None else _floatla(offset)
    bakiye = borsa_istemci.fetch_balance({"type": "future"})
    info = bakiye.get("info", {}) if isinstance(bakiye, dict) else {}
    usdt = bakiye.get("USDT", {}) if isinstance(bakiye, dict) else {}
    usdt_asset = _usdt_asset(info)

    raw_wallet = (
        _floatla(info.get("totalWalletBalance"))
        or _floatla(usdt_asset.get("walletBalance"))
        or _floatla(usdt.get("total"))
    )
    raw_unrealized = (
        _floatla(info.get("totalUnrealizedProfit"))
        or _floatla(usdt_asset.get("unrealizedProfit"))
    )
    raw_margin = (
        _floatla(info.get("totalMarginBalance"))
        or _floatla(usdt_asset.get("marginBalance"))
        or (raw_wallet + raw_unrealized if raw_wallet else _floatla(usdt.get("total")))
    )
    raw_available = (
        _floatla(info.get("availableBalance"))
        or _floatla(usdt_asset.get("availableBalance"))
        or _floatla(usdt.get("free"))
    )
    raw_initial_margin = (
        _floatla(info.get("totalInitialMargin"))
        or _floatla(usdt_asset.get("initialMargin"))
        or _floatla(usdt.get("used"))
    )

    return {
        "zaman": _simdi(),
        "wallet": raw_wallet - offset if raw_wallet else 0.0,
        "equity": raw_margin - offset if raw_margin else 0.0,
        "available": raw_available,
        "initial_margin": raw_initial_margin,
        "unrealized": raw_unrealized,
        "offset": offset,
        "raw": info,
        "ccxt_usdt": usdt,
    }


def acik_pozisyon_pnli_getir(borsa_istemci) -> tuple[float, int]:
    toplam = 0.0
    adet = 0
    try:
        for poz in borsa_istemci.fetch_positions():
            info = poz.get("info") or {}
            miktar = _floatla(info.get("positionAmt") or poz.get("contracts"))
            if miktar == 0:
                continue
            toplam += _floatla(poz.get("unrealizedPnl") or info.get("unRealizedProfit"))
            adet += 1
    except Exception:
        pass
    return toplam, adet


def demo_muhasebe_baslat(borsa_istemci, offset: float | None = None) -> dict[str, Any]:
    baslangic_ms = int(time.time() * 1000)
    bakiye = bakiye_ozeti_getir(borsa_istemci, offset)
    acik_pnl, acik_adet = acik_pozisyon_pnli_getir(borsa_istemci)
    return {
        "baslangic_ms": baslangic_ms,
        "baslangic_zamani": _ms_to_str(baslangic_ms),
        "baslangic_wallet": round(float(bakiye.get("wallet", 0.0)), 8),
        "baslangic_equity": round(float(bakiye.get("equity", 0.0)), 8),
        "baslangic_acik_pnl": round(float(acik_pnl), 8),
        "baslangic_acik_pozisyon": acik_adet,
    }


def gelirleri_cek(
    borsa_istemci,
    since_ms: int | float | None = None,
    until_ms: int | float | None = None,
    sembol: str | None = None,
    max_pages: int = 5,
) -> list[dict[str, Any]]:
    if not hasattr(borsa_istemci, "fapiPrivateGetIncome"):
        return []

    tumu: list[dict[str, Any]] = []
    sonraki_ms = int(since_ms) if since_ms else None
    onceki_son = None
    for _ in range(max_pages):
        params: dict[str, Any] = {"limit": 1000}
        if sonraki_ms:
            params["startTime"] = sonraki_ms
        if until_ms:
            params["endTime"] = int(until_ms)
        if sembol:
            params["symbol"] = _sembol_id(sembol)

        ham = borsa_istemci.fapiPrivateGetIncome(params) or []
        if not ham:
            break

        sirali = sorted(ham, key=lambda item: int(item.get("time") or 0))
        for item in sirali:
            zaman_ms = int(item.get("time") or 0)
            if since_ms and zaman_ms < int(since_ms):
                continue
            if until_ms and zaman_ms > int(until_ms):
                continue
            tumu.append(item)

        son_ms = max(int(item.get("time") or 0) for item in sirali)
        if len(ham) < 1000 or son_ms == onceki_son:
            break
        onceki_son = son_ms
        sonraki_ms = son_ms + 1

    return tumu


def gelir_defteri_senkronize(kayitlar: list[dict[str, Any]], db_path: str | Path = DB_PATH) -> int:
    if not kayitlar:
        return 0

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS account_income_ledger (
                uid TEXT PRIMARY KEY,
                time_ms INTEGER,
                time_text TEXT,
                symbol TEXT,
                income_type TEXT,
                income REAL,
                asset TEXT,
                trade_id TEXT,
                tran_id TEXT,
                raw_json TEXT
            )
            """
        )
        eklenen = 0
        for item in kayitlar:
            zaman_ms = int(item.get("time") or 0)
            symbol = str(item.get("symbol") or "")
            income_type = str(item.get("incomeType") or "")
            income = _floatla(item.get("income"))
            trade_id = str(item.get("tradeId") or "")
            tran_id = str(item.get("tranId") or "")
            uid = tran_id or f"{zaman_ms}:{symbol}:{income_type}:{trade_id}:{income:.12f}"
            cur.execute(
                """
                INSERT OR IGNORE INTO account_income_ledger
                (uid, time_ms, time_text, symbol, income_type, income, asset, trade_id, tran_id, raw_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    zaman_ms,
                    _ms_to_str(zaman_ms),
                    symbol,
                    income_type,
                    income,
                    str(item.get("asset") or ""),
                    trade_id,
                    tran_id,
                    json.dumps(item, ensure_ascii=False, sort_keys=True),
                ),
            )
            eklenen += cur.rowcount
        conn.commit()
        return eklenen
    finally:
        conn.close()


def gelir_ozeti_hesapla(
    borsa_istemci,
    since_ms: int | float | None,
    *,
    baseline_open_pnl: float = 0.0,
    current_open_pnl: float = 0.0,
    wallet: float = 0.0,
    baseline_wallet: float = 0.0,
    db_path: str | Path = DB_PATH,
) -> dict[str, Any]:
    kayitlar = gelirleri_cek(borsa_istemci, since_ms)
    eklenen = gelir_defteri_senkronize(kayitlar, db_path=db_path)

    by_type: dict[str, float] = {}
    by_symbol: dict[str, float] = {}
    count_by_type: dict[str, int] = {}
    for item in kayitlar:
        income_type = str(item.get("incomeType") or "UNKNOWN")
        symbol = str(item.get("symbol") or "-")
        income = _floatla(item.get("income"))
        by_type[income_type] = by_type.get(income_type, 0.0) + income
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + income
        count_by_type[income_type] = count_by_type.get(income_type, 0) + 1

    realized_net = sum(v for k, v in by_type.items() if k in TRADING_INCOME_TYPES)
    open_delta = _floatla(current_open_pnl) - _floatla(baseline_open_pnl)
    mtm_net = realized_net + open_delta
    wallet_delta = _floatla(wallet) - _floatla(baseline_wallet) if baseline_wallet else 0.0

    return {
        "kaynak": "binance_income",
        "baslangic_ms": int(since_ms or 0),
        "baslangic_zamani": _ms_to_str(int(since_ms or 0)) if since_ms else "",
        "guncelleme_zamani": _simdi(),
        "income_kayit_sayisi": len(kayitlar),
        "income_db_eklenen": eklenen,
        "income_by_type": {k: round(v, 6) for k, v in sorted(by_type.items())},
        "income_count_by_type": dict(sorted(count_by_type.items())),
        "income_by_symbol": {k: round(v, 6) for k, v in sorted(by_symbol.items())},
        "realized_net": round(realized_net, 6),
        "baseline_open_pnl": round(_floatla(baseline_open_pnl), 6),
        "current_open_pnl": round(_floatla(current_open_pnl), 6),
        "open_pnl_delta": round(open_delta, 6),
        "net_pnl_mtm": round(mtm_net, 6),
        "wallet_delta": round(wallet_delta, 6),
    }


def sembol_gelir_net(
    borsa_istemci,
    sembol: str,
    since_ms: int | float,
    until_ms: int | float | None = None,
) -> dict[str, Any]:
    kayitlar = gelirleri_cek(borsa_istemci, since_ms, until_ms, sembol=sembol, max_pages=2)
    by_type: dict[str, float] = {}
    for item in kayitlar:
        income_type = str(item.get("incomeType") or "UNKNOWN")
        by_type[income_type] = by_type.get(income_type, 0.0) + _floatla(item.get("income"))
    net = sum(v for k, v in by_type.items() if k in TRADING_INCOME_TYPES)
    return {
        "kayit_sayisi": len(kayitlar),
        "income_by_type": {k: round(v, 6) for k, v in sorted(by_type.items())},
        "net": round(net, 6),
    }
