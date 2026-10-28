"""
symbol_guard.py - Symbol-level loss quarantine.

Uses official Binance income ledger when available, and also reacts immediately
to freshly closed trade PnL. The goal is to stop repeatedly bad symbols without
tightening the whole strategy.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from config import (
    SYMBOL_GUARD_AKTIF,
    SYMBOL_GUARD_PNL_ESIK,
    SYMBOL_GUARD_ARDISIK_ZARAR,
    SYMBOL_GUARD_KARANTINA_SAAT,
    SYMBOL_GUARD_AGIR_ZARAR_ESIK,
    SYMBOL_GUARD_AGIR_KARANTINA_SAAT,
    SYMBOL_GUARD_MIN_ZARAR_USDT,
)

try:
    from runtime_status import status_yaz
except Exception:
    def status_yaz(guncelleme=None, event=None):  # type: ignore
        return {}


BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "symbol_guard_state.json"
DB_PATH = BASE_DIR / "trading_bot.db"
TRADING_INCOME_TYPES = {"REALIZED_PNL", "COMMISSION", "FUNDING_FEE"}
_SON_DB_TARAMA = 0.0
REALIZED_GRUP_PENCERESI_MS = 15_000


def _floatla(deger: Any, varsayilan: float = 0.0) -> float:
    try:
        return float(deger)
    except Exception:
        return varsayilan


def _sembol_normalize(sembol: str) -> str:
    temiz = str(sembol or "").replace(":USDT", "").strip().upper()
    base = temiz.replace("/USDT", "").replace("USDT", "")
    return f"{base}/USDT" if base else temiz


def _ledger_symbol(sembol: str) -> str:
    return _sembol_normalize(sembol).replace("/", "")


def _negatif_realized_gruplari(
    kayitlar: list[tuple[int, float]],
    pencere_ms: int = REALIZED_GRUP_PENCERESI_MS,
) -> list[float]:
    """Merge split Binance fills from one close into a single loss event."""
    gruplar: list[float] = []
    son_zaman: int | None = None
    grup_toplami = 0.0
    for zaman_ms, gelir in sorted(kayitlar, key=lambda item: item[0]):
        if son_zaman is None or zaman_ms - son_zaman <= int(pencere_ms):
            grup_toplami += float(gelir)
        else:
            gruplar.append(grup_toplami)
            grup_toplami = float(gelir)
        son_zaman = int(zaman_ms)
    if son_zaman is not None:
        gruplar.append(grup_toplami)
    return gruplar


def _durum_oku() -> dict[str, Any]:
    try:
        if STATE_PATH.exists():
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"symbols": {}}


def _durum_yaz(durum: dict[str, Any]) -> None:
    try:
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(durum, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except Exception:
        pass


def sembol_guard_yukle(karantina_listesi: dict, coin_zarar_sayaci: dict | None = None) -> dict[str, Any]:
    if not SYMBOL_GUARD_AKTIF:
        return {}
    durum = _durum_oku()
    simdi = datetime.now()
    degisti = False
    aktif = {}
    for sembol, veri in list((durum.get("symbols") or {}).items()):
        try:
            bitis = datetime.fromisoformat(str(veri.get("karantina_bitis") or ""))
        except Exception:
            bitis = simdi - timedelta(seconds=1)
        norm = _sembol_normalize(sembol)
        if bitis > simdi:
            karantina_listesi[norm] = bitis
            if coin_zarar_sayaci is not None:
                coin_zarar_sayaci[norm] = int(veri.get("ardisik_zarar") or 0)
            aktif[norm] = veri
        else:
            veri["aktif"] = False
            degisti = True
    if degisti:
        _durum_yaz(durum)
    return aktif


def _karantina_yaz(
    ctx: dict,
    sembol: str,
    saat: float,
    neden: str,
    *,
    net_pnl: float,
    ardisik_zarar: int,
) -> dict[str, Any]:
    norm = _sembol_normalize(sembol)
    bitis = datetime.now() + timedelta(hours=float(saat))
    ctx.setdefault("KARANTINA_LISTESI", {})[norm] = bitis
    ctx.setdefault("COIN_ZARAR_SAYACI", {})[norm] = int(ardisik_zarar)

    durum = _durum_oku()
    symbols = durum.setdefault("symbols", {})
    onceki = symbols.get(norm, {})
    symbols[norm] = {
        **onceki,
        "aktif": True,
        "karantina_bitis": bitis.isoformat(timespec="seconds"),
        "neden": neden,
        "net_pnl": round(float(net_pnl), 6),
        "ardisik_zarar": int(ardisik_zarar),
        "guncelleme": datetime.now().isoformat(timespec="seconds"),
    }
    _durum_yaz(durum)

    mesaj = f"{norm} symbol guard karantina: {neden} ({saat:.1f}h)"
    print(f"[SYMBOL GUARD] {mesaj} | net={net_pnl:+.2f} | ard={ardisik_zarar}")
    status_yaz(
        {"symbol_guard": {"son_karantina": symbols[norm], "aktif_sayisi": len([v for v in symbols.values() if v.get("aktif")])}},
        event={"tip": "symbol_guard", "mesaj": mesaj},
    )
    return symbols[norm]


def sembol_zararini_isle(ctx: dict, sembol: str, pnl_usdt: float, kapanma_sebebi: str = "") -> dict[str, Any]:
    if not SYMBOL_GUARD_AKTIF:
        return {}
    norm = _sembol_normalize(sembol)
    pnl = _floatla(pnl_usdt)
    durum = _durum_oku()
    symbols = durum.setdefault("symbols", {})
    veri = symbols.setdefault(norm, {})
    veri["son_pnl"] = round(pnl, 6)
    veri["son_kapanma_sebebi"] = kapanma_sebebi
    veri["guncelleme"] = datetime.now().isoformat(timespec="seconds")

    if pnl <= -SYMBOL_GUARD_MIN_ZARAR_USDT:
        veri["ardisik_zarar"] = int(veri.get("ardisik_zarar") or 0) + 1
        veri["session_pnl"] = round(_floatla(veri.get("session_pnl")) + pnl, 6)
    elif pnl > 0:
        veri["ardisik_zarar"] = 0
        # Positive trades can repair the session score, but do not erase prior loss completely.
        veri["session_pnl"] = round(min(0.0, _floatla(veri.get("session_pnl")) + pnl), 6)

    _durum_yaz(durum)

    ardisik = int(veri.get("ardisik_zarar") or 0)
    session_pnl = _floatla(veri.get("session_pnl"))
    if session_pnl <= -SYMBOL_GUARD_AGIR_ZARAR_ESIK:
        return _karantina_yaz(
            ctx, norm, SYMBOL_GUARD_AGIR_KARANTINA_SAAT,
            f"agir sembol zarari {session_pnl:+.2f}",
            net_pnl=session_pnl, ardisik_zarar=ardisik,
        )
    if session_pnl <= -SYMBOL_GUARD_PNL_ESIK:
        return _karantina_yaz(
            ctx, norm, SYMBOL_GUARD_KARANTINA_SAAT,
            f"sembol net zarari {session_pnl:+.2f}",
            net_pnl=session_pnl, ardisik_zarar=ardisik,
        )
    if ardisik >= SYMBOL_GUARD_ARDISIK_ZARAR and session_pnl <= -SYMBOL_GUARD_MIN_ZARAR_USDT:
        return _karantina_yaz(
            ctx, norm, SYMBOL_GUARD_KARANTINA_SAAT,
            f"{ardisik} ardisik zarar",
            net_pnl=session_pnl, ardisik_zarar=ardisik,
        )
    return veri


def resmi_zarar_karantinasi_tazele(ctx: dict, saat: float = 24.0, *, zorla: bool = False) -> dict[str, Any]:
    global _SON_DB_TARAMA
    if not SYMBOL_GUARD_AKTIF:
        return {}
    simdi = time.time()
    if not zorla and simdi - _SON_DB_TARAMA < 600:
        return {}
    _SON_DB_TARAMA = simdi

    sembol_guard_yukle(ctx.setdefault("KARANTINA_LISTESI", {}), ctx.setdefault("COIN_ZARAR_SAYACI", {}))
    if not DB_PATH.exists():
        return {}

    cutoff_ms = int((time.time() - float(saat) * 3600) * 1000)
    ozet: dict[str, dict[str, Any]] = {}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT symbol, income_type, income, time_ms
            FROM account_income_ledger
            WHERE time_ms >= ?
              AND income_type IN ('REALIZED_PNL', 'COMMISSION', 'FUNDING_FEE')
              AND COALESCE(symbol, '') != ''
            """,
            (cutoff_ms,),
        ).fetchall()
        conn.close()
    except Exception:
        return {}

    for row in rows:
        sym = _sembol_normalize(row["symbol"])
        rec = ozet.setdefault(
            sym,
            {"net": 0.0, "realized": 0.0, "neg_realized": 0, "count": 0, "neg_realized_rows": []},
        )
        income = _floatla(row["income"])
        typ = str(row["income_type"] or "")
        if typ in TRADING_INCOME_TYPES:
            rec["net"] += income
            rec["count"] += 1
        if typ == "REALIZED_PNL":
            rec["realized"] += income
            if income < 0:
                rec["neg_realized_rows"].append((int(row["time_ms"] or 0), income))

    for rec in ozet.values():
        gruplar = _negatif_realized_gruplari(rec.pop("neg_realized_rows", []))
        rec["neg_realized"] = sum(
            1 for grup_pnl in gruplar if grup_pnl <= -SYMBOL_GUARD_MIN_ZARAR_USDT
        )

    cezalar = {}
    for sym, rec in ozet.items():
        net = float(rec["net"])
        neg = int(rec["neg_realized"])
        if net <= -SYMBOL_GUARD_AGIR_ZARAR_ESIK:
            cezalar[sym] = _karantina_yaz(
                ctx, sym, SYMBOL_GUARD_AGIR_KARANTINA_SAAT,
                f"24s resmi net {net:+.2f}",
                net_pnl=net, ardisik_zarar=neg,
            )
        elif net <= -SYMBOL_GUARD_PNL_ESIK or (neg >= SYMBOL_GUARD_ARDISIK_ZARAR and net <= -SYMBOL_GUARD_MIN_ZARAR_USDT):
            cezalar[sym] = _karantina_yaz(
                ctx, sym, SYMBOL_GUARD_KARANTINA_SAAT,
                f"24s resmi net {net:+.2f}, zarar sayisi {neg}",
                net_pnl=net, ardisik_zarar=neg,
            )

    temizlenen = {}
    try:
        durum = _durum_oku()
        symbols = durum.setdefault("symbols", {})
        for sym, veri in list(symbols.items()):
            if not veri.get("aktif"):
                continue
            neden = str(veri.get("neden") or "")
            if not neden.startswith("24s resmi net"):
                continue
            rec = ozet.get(sym, {"net": 0.0, "neg_realized": 0})
            net = float(rec.get("net") or 0.0)
            neg = int(rec.get("neg_realized") or 0)
            halen_cezali = (
                net <= -SYMBOL_GUARD_AGIR_ZARAR_ESIK
                or net <= -SYMBOL_GUARD_PNL_ESIK
                or (neg >= SYMBOL_GUARD_ARDISIK_ZARAR and net <= -SYMBOL_GUARD_MIN_ZARAR_USDT)
            )
            if halen_cezali:
                continue
            veri["aktif"] = False
            veri["temizlenme"] = datetime.now().isoformat(timespec="seconds")
            veri["temizlenme_nedeni"] = (
                f"resmi zarar artik esik alti: net={net:+.2f}, zarar_sayisi={neg}"
            )
            ctx.setdefault("KARANTINA_LISTESI", {}).pop(sym, None)
            ctx.setdefault("COIN_ZARAR_SAYACI", {}).pop(sym, None)
            temizlenen[sym] = veri
        if temizlenen:
            _durum_yaz(durum)
            status_yaz({"symbol_guard": {"temizlenen_cezalar": temizlenen}})
    except Exception:
        pass

    if cezalar:
        status_yaz({"symbol_guard": {"aktif_cezalar": cezalar, "son_tarama_saat": saat}})
    return cezalar
