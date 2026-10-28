from __future__ import annotations

import json
import math
import os
import sqlite3
import tempfile
import csv
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent
JOURNAL_PATH = BASE_DIR / "demo_trade_journal.jsonl"
REPORT_PATH = BASE_DIR / "demo_analysis_report.json"
DB_PATH = BASE_DIR / "trading_bot.db"
ROOT_DB_PATH = ROOT_DIR / "trading_bot.db"
CSV_PATH = BASE_DIR / "trade_history.csv"
ROOT_CSV_PATH = ROOT_DIR / "trade_history.csv"
MAX_KAYIT = 10000
MIN_KAPANIS_INCELEME = 20
MIN_KAPANIS_LIVE_ADAYI = 50
MODEL_KALITE_SARI_ESIK = 0.55
MODEL_KALITE_VARSAYILAN_KIRMIZI_ESIK = 0.50
MODEL_KALITE_ALANLARI = (
    "model_walk_forward_skoru",
    "min_model_walk_forward_skoru",
    "model_kalite_bolgesi",
    "model_kalite_sari",
    "model_kalite_sari_margin_carpani",
)


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _floatla(deger: Any, varsayilan: float = 0.0) -> float:
    try:
        sonuc = float(deger)
        return sonuc if math.isfinite(sonuc) else varsayilan
    except Exception:
        return varsayilan


def _oran(pay: float, payda: float) -> float:
    return (pay / payda) if payda else 0.0


def _medyan(degerler: list[float]) -> float:
    if not degerler:
        return 0.0
    sirali = sorted(degerler)
    orta = len(sirali) // 2
    if len(sirali) % 2:
        return sirali[orta]
    return (sirali[orta - 1] + sirali[orta]) / 2.0


def _ana_neden(neden: Any) -> str:
    metin = str(neden or "Belirsiz").split("|")[0].strip()
    return metin[:90] if metin else "Belirsiz"


def _ret_kategorisi(neden: Any) -> str:
    metin = str(neden or "").lower()
    if not metin:
        return "belirsiz"
    if "veri" in metin or "mum" in metin or "kolon" in metin or "feature" in metin:
        return "veri"
    if "model" in metin or "tahmini" in metin or "eğitim" in metin or "egitim" in metin:
        return "model"
    if "rr(" in metin or "_rr" in metin:
        return "rr"
    if "güven" in metin or "guven" in metin or "eşik" in metin or "esik" in metin:
        return "guven"
    if "anatrend" in metin or "btcz" in metin:
        return "trend_btc"
    if "short_kapali" in metin:
        return "short_kapisi"
    if "funding" in metin:
        return "funding"
    if "volatilite" in metin or "atr/fiyat" in metin:
        return "volatilite"
    if "makro" in metin:
        return "makro"
    if "kara liste" in metin or "karantina" in metin:
        return "karantina"
    if "nötr" in metin or "notr" in metin:
        return "notr"
    if "portfoy" in metin or "portföy" in metin or "sektor" in metin or "sert tavan" in metin:
        return "dispatch"
    return "diger"


def _ret_kategorileri(neden: Any) -> list[str]:
    parcalar = [p.strip() for p in str(neden or "").split("|") if p.strip()]
    if not parcalar:
        return [_ret_kategorisi(neden)]
    kategoriler: list[str] = []
    for parca in parcalar:
        kategori = _ret_kategorisi(parca)
        if kategori not in kategoriler:
            kategoriler.append(kategori)
    return kategoriler or ["belirsiz"]


def _yon(yon: Any) -> str:
    metin = str(yon or "").upper()
    if "SHORT" in metin or "DUS" in metin or "DU\u015e" in metin or "D\u00dc\u015e" in metin:
        return "SHORT"
    if "LONG" in metin or "YUK" in metin or "Y\u00dcK" in metin:
        return "LONG"
    return metin or "BILINMIYOR"


def _kapanis_sebebi_kategorisi(kayit: dict[str, Any]) -> str:
    sebep = str(kayit.get("kapanis_sebebi") or "").upper()
    if not sebep:
        return "BELIRSIZ"
    if "HARD STOP" in sebep or "STOP-LOSS" in sebep:
        return "HARD_STOP"
    if "TRAILING" in sebep:
        return "TRAILING_STOP"
    if "SCALE-OUT" in sebep or "KISMİ" in sebep:
        return "SCALE_OUT"
    if "ZAMAN" in sebep or "TIME-OUT" in sebep or "AÇIMI" in sebep:
        return "TIME_OUT"
    if "BREAK-EVEN" in sebep:
        return "BREAK_EVEN"
    if "MAX ZARAR" in sebep or "LİMİT" in sebep:
        return "MAX_ZARAR"
    if "BORSADA_KAPANDI" in sebep or "BORSADA KAPANDI" in sebep:
        return "BORSA_TP"
    if "ZATEN_KAPALI" in sebep or "ZATEN KAPALI" in sebep:
        return "BORSA_TP"
    return "DIGER"


def _guven_bandi(skor: Any) -> str:
    s = _floatla(skor)
    if s < 60:
        return "<60"
    if s < 65:
        return "60-65"
    if s < 70:
        return "65-70"
    if s < 75:
        return "70-75"
    return "75+"


def _zaman_bandi(kayit: dict[str, Any]) -> str:
    zaman_str = str(kayit.get("zaman") or "")
    try:
        if len(zaman_str) >= 13: # e.g. "2026-07-02 21:00:00"
            saat = int(zaman_str[11:13])
            if 0 <= saat < 8:
                return "ASYA (00-08)"
            elif 8 <= saat < 15:
                return "AVRUPA (08-15)"
            else:
                return "ABD (15-24)"
    except Exception:
        pass
    return "BILINMIYOR"


def _model_kalite_bolgesi(kayit: dict[str, Any]) -> str:
    bolge = str(kayit.get("model_kalite_bolgesi") or "").strip().lower()
    if bolge in {"kirmizi", "sari", "yesil", "bilinmiyor"}:
        return bolge
    if kayit.get("model_kalite_sari"):
        return "sari"

    wf = kayit.get("model_walk_forward_skoru")
    if wf is None or str(wf).strip() == "":
        return "bilinmiyor"

    wf_float = _floatla(wf)
    min_wf = _floatla(kayit.get("min_model_walk_forward_skoru"), MODEL_KALITE_VARSAYILAN_KIRMIZI_ESIK)
    if wf_float < min_wf:
        return "kirmizi"
    if wf_float < MODEL_KALITE_SARI_ESIK:
        return "sari"
    return "yesil"


def _model_kalite_alanlari(kayit: dict[str, Any]) -> dict[str, Any]:
    alanlar = {ad: kayit.get(ad) for ad in MODEL_KALITE_ALANLARI if kayit.get(ad) not in (None, "")}
    bolge = _model_kalite_bolgesi(kayit)
    if bolge != "bilinmiyor" or alanlar:
        alanlar["model_kalite_bolgesi"] = bolge
    return alanlar


def _model_kalite_eksik_mi(kayit: dict[str, Any]) -> bool:
    return not any(kayit.get(ad) not in (None, "") for ad in MODEL_KALITE_ALANLARI)


def _kapanislari_model_etiketiyle_zenginlestir(kayitlar: list[dict[str, Any]]) -> list[dict[str, Any]]:
    son_model: dict[tuple[str, str], dict[str, Any]] = {}
    kapanislar: list[dict[str, Any]] = []

    for kayit in kayitlar:
        tip = kayit.get("tip")
        coin = str(kayit.get("coin") or "")
        yon = _yon(kayit.get("yon"))
        anahtar = (coin, yon)

        if tip in {"sinyal", "acilis"}:
            alanlar = _model_kalite_alanlari(kayit)
            if alanlar:
                son_model[anahtar] = alanlar

        if tip == "kapanis":
            kapanis = dict(kayit)
            if _model_kalite_eksik_mi(kapanis):
                for ad, deger in son_model.get(anahtar, {}).items():
                    kapanis.setdefault(ad, deger)
            kapanis["model_kalite_bolgesi"] = _model_kalite_bolgesi(kapanis)
            kapanislar.append(kapanis)

    return kapanislar


def _json_oku(path: Path, limit: int = MAX_KAYIT) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as f:
            satirlar = f.readlines()[-limit:]
    except OSError:
        return []

    kayitlar: list[dict[str, Any]] = []
    for satir in satirlar:
        satir = satir.strip()
        if not satir:
            continue
        try:
            kayit = json.loads(satir)
            if isinstance(kayit, dict):
                kayitlar.append(kayit)
        except json.JSONDecodeError:
            continue
    return kayitlar


def _db_kapanislari_oku(path: Path = DB_PATH) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='closed_trades'")
        if cur.fetchone() is None:
            return []
        cur.execute(
            """
            SELECT Tarih_Saat, Parite, Hesap_Tipi, Islem_Yonu, Giris_Fiyati,
                   Cikis_Fiyati, Net_PNL_USDT, PNL_Yuzde, AI_Guven_Skoru
            FROM closed_trades
            ORDER BY id ASC
            """
        )
        sonuc = []
        for row in cur.fetchall():
            hesap = str(row["Hesap_Tipi"] or "").upper()
            if hesap not in {"DEMO", "TESTNET", "PAPER"}:
                continue
            sonuc.append(
                {
                    "zaman": row["Tarih_Saat"],
                    "tip": "kapanis",
                    "hesap_tipi": hesap,
                    "coin": row["Parite"],
                    "yon": _yon(row["Islem_Yonu"]),
                    "giris": _floatla(row["Giris_Fiyati"]),
                    "cikis": _floatla(row["Cikis_Fiyati"]),
                    "pnl_usdt": _floatla(row["Net_PNL_USDT"]),
                    "pnl_yuzde": _floatla(row["PNL_Yuzde"]),
                    "ai_skoru": _floatla(row["AI_Guven_Skoru"]),
                }
            )
        return sonuc
    except sqlite3.Error:
        return []
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _csv_kapanislari_oku(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", newline="") as f:
            satirlar = list(csv.reader(f))
    except OSError:
        return []

    sonuc: list[dict[str, Any]] = []
    for row in satirlar[1:]:
        if len(row) >= 9:
            tarih, parite, hesap, yon, giris, cikis, pnl, pnl_yuzde, ai_skoru = row[:9]
        elif len(row) >= 8:
            tarih, parite, yon, giris, cikis, pnl, pnl_yuzde, ai_skoru = row[:8]
            hesap = "TESTNET"
        else:
            continue

        hesap_norm = str(hesap or "").upper()
        if hesap_norm not in {"DEMO", "TESTNET", "PAPER"}:
            continue
        sonuc.append(
            {
                "zaman": tarih,
                "tip": "kapanis",
                "hesap_tipi": hesap_norm,
                "coin": parite,
                "yon": _yon(yon),
                "giris": _floatla(giris),
                "cikis": _floatla(cikis),
                "pnl_usdt": _floatla(pnl),
                "pnl_yuzde": _floatla(pnl_yuzde),
                "ai_skoru": _floatla(ai_skoru),
            }
        )
    return sonuc


def _max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0
    zirve = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0
    for equity in equity_curve:
        zirve = max(zirve, equity)
        dd = zirve - equity
        dd_pct = _oran(dd, zirve)
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct
    return max_dd, max_dd_pct


def _max_ardisik_zarar(pnller: list[float]) -> int:
    en_uzun = 0
    seri = 0
    for pnl in pnller:
        if pnl <= 0:
            seri += 1
            en_uzun = max(en_uzun, seri)
        else:
            seri = 0
    return en_uzun


def _metrik(kapanislar: list[dict[str, Any]], baslangic_kasa: float = 1000.0) -> dict[str, Any]:
    pnller = [_floatla(k.get("pnl_usdt")) for k in kapanislar]
    pnl_yuzdeler = [_floatla(k.get("pnl_yuzde")) for k in kapanislar]
    toplam = len(pnller)
    karlar = [p for p in pnller if p > 0]
    zararlar = [p for p in pnller if p <= 0]
    gross_profit = sum(karlar)
    gross_loss = abs(sum(zararlar))
    win_rate = _oran(len(karlar), toplam)
    loss_rate = _oran(len(zararlar), toplam)
    avg_kar = _oran(gross_profit, len(karlar))
    avg_zarar = _oran(gross_loss, len(zararlar))
    expectancy = (win_rate * avg_kar) - (loss_rate * avg_zarar)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    equity_curve = [float(baslangic_kasa)]
    for pnl in pnller:
        equity_curve.append(equity_curve[-1] + pnl)
    max_dd, max_dd_pct = _max_drawdown(equity_curve)

    return {
        "toplam_islem": toplam,
        "kazanan_islem": len(karlar),
        "kaybeden_islem": len(zararlar),
        "win_rate": round(win_rate * 100.0, 2),
        "net_pnl": round(sum(pnller), 4),
        "net_pnl_yuzde_toplam": round(sum(pnl_yuzdeler), 4),
        "avg_pnl_yuzde": round(_oran(sum(pnl_yuzdeler), len(pnl_yuzdeler)), 4),
        "medyan_pnl": round(_medyan(pnller), 4),
        "medyan_pnl_yuzde": round(_medyan(pnl_yuzdeler), 4),
        "gross_profit": round(gross_profit, 4),
        "gross_loss": round(gross_loss, 4),
        "profit_factor": round(profit_factor, 4),
        "avg_kar": round(avg_kar, 4),
        "avg_zarar": round(avg_zarar, 4),
        "expectancy": round(expectancy, 4),
        "max_drawdown": round(max_dd, 4),
        "max_drawdown_pct": round(max_dd_pct * 100.0, 2),
        "max_ardisik_zarar": _max_ardisik_zarar(pnller),
        "son_kasa": round(equity_curve[-1], 4),
    }


def _grup_metrikleri(
    kapanislar: list[dict[str, Any]],
    anahtar_fn: Callable[[dict[str, Any]], str],
    min_islem: int = 1,
) -> dict[str, Any]:
    gruplar: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kayit in kapanislar:
        gruplar[anahtar_fn(kayit)].append(kayit)

    sonuc = {}
    for ad, liste in sorted(gruplar.items(), key=lambda item: len(item[1]), reverse=True):
        if len(liste) < min_islem:
            continue
        sonuc[ad] = _metrik(liste)
    return sonuc


def _model_kalite_bolge_metrikleri(kapanislar: list[dict[str, Any]]) -> dict[str, Any]:
    gruplar: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for kayit in kapanislar:
        gruplar[_model_kalite_bolgesi(kayit)].append(kayit)

    sirali_bolgeler = ["kirmizi", "sari", "yesil", "bilinmiyor"]
    return {
        bolge: _metrik(gruplar[bolge])
        for bolge in sirali_bolgeler
        if gruplar.get(bolge)
    }


def _model_kalite_karnesi(
    kapanislar: list[dict[str, Any]],
    temiz_kapanislar: list[dict[str, Any]],
) -> dict[str, Any]:
    bolge_sayac = Counter(_model_kalite_bolgesi(k) for k in kapanislar)
    etiketli = sum(adet for bolge, adet in bolge_sayac.items() if bolge != "bilinmiyor")
    temiz_bolge_metrikleri = _model_kalite_bolge_metrikleri(temiz_kapanislar)

    adaylar = {
        bolge: metrik
        for bolge, metrik in temiz_bolge_metrikleri.items()
        if bolge != "bilinmiyor" and metrik.get("toplam_islem", 0) >= 3
    }
    en_iyi_bolge = None
    if adaylar:
        en_iyi_bolge = max(
            adaylar.items(),
            key=lambda item: (
                _floatla(item[1].get("expectancy")),
                _floatla(item[1].get("profit_factor")),
                _floatla(item[1].get("win_rate")),
            ),
        )[0]

    riskli_bolgeler = [
        bolge
        for bolge, metrik in adaylar.items()
        if _floatla(metrik.get("profit_factor")) < 1.0 or _floatla(metrik.get("expectancy")) <= 0.0
    ]

    return {
        "kapanis_sayisi": len(kapanislar),
        "etiketli_kapanis": etiketli,
        "bilinmeyen_kapanis": bolge_sayac.get("bilinmiyor", 0),
        "bilinmeyen_orani": round(_oran(bolge_sayac.get("bilinmiyor", 0), len(kapanislar)) * 100.0, 2),
        "bolge_sayaci": {bolge: bolge_sayac.get(bolge, 0) for bolge in ["kirmizi", "sari", "yesil", "bilinmiyor"] if bolge_sayac.get(bolge, 0)},
        "bolge_metrikleri": _model_kalite_bolge_metrikleri(kapanislar),
        "temiz_bolge_metrikleri": temiz_bolge_metrikleri,
        "en_iyi_bolge": en_iyi_bolge,
        "riskli_bolgeler": riskli_bolgeler,
        "not": "Kirmizi/sari/yesil ayrimi kapanan demo islemlerinin model walk-forward kalitesine gore hesaplanir.",
    }


def _outlier_mi(kayit: dict[str, Any], parasal_esik: float) -> bool:
    pnl = abs(_floatla(kayit.get("pnl_usdt")))
    pnl_yuzde = abs(_floatla(kayit.get("pnl_yuzde")))
    return pnl_yuzde > 100.0 or pnl > parasal_esik


def _kayit_ozeti(kayit: dict[str, Any]) -> dict[str, Any]:
    return {
        "zaman": kayit.get("zaman"),
        "coin": kayit.get("coin"),
        "yon": _yon(kayit.get("yon")),
        "giris": _floatla(kayit.get("giris")),
        "cikis": _floatla(kayit.get("cikis")),
        "pnl_usdt": round(_floatla(kayit.get("pnl_usdt")), 4),
        "pnl_yuzde": round(_floatla(kayit.get("pnl_yuzde")), 4),
        "ai_skoru": round(_floatla(kayit.get("ai_skoru")), 4),
        "model_kalite_bolgesi": _model_kalite_bolgesi(kayit),
    }


def _outlier_analizi(kapanislar: list[dict[str, Any]]) -> dict[str, Any]:
    mutlak_pnller = [abs(_floatla(k.get("pnl_usdt"))) for k in kapanislar]
    medyan_abs = _medyan(mutlak_pnller)
    parasal_esik = max(5000.0, medyan_abs * 20.0)
    outlierlar = [k for k in kapanislar if _outlier_mi(k, parasal_esik)]
    temiz = [k for k in kapanislar if k not in outlierlar]

    en_kotu = sorted(kapanislar, key=lambda k: _floatla(k.get("pnl_usdt")))[:8]
    en_iyi = sorted(kapanislar, key=lambda k: _floatla(k.get("pnl_usdt")), reverse=True)[:5]

    return {
        "parasal_esik": round(parasal_esik, 4),
        "outlier_sayisi": len(outlierlar),
        "outlier_orani": round(_oran(len(outlierlar), len(kapanislar)) * 100.0, 2),
        "outlier_net_pnl": round(sum(_floatla(k.get("pnl_usdt")) for k in outlierlar), 4),
        "temiz_kayit_sayisi": len(temiz),
        "temiz_performans": _metrik(temiz),
        "en_kotu_islemler": [_kayit_ozeti(k) for k in en_kotu],
        "en_iyi_islemler": [_kayit_ozeti(k) for k in en_iyi],
        "not": "Mutlak PNL yuzdesi %100 ustu veya parasal dagilimdan asiri sapan kayitlar outlier sayilir.",
    }


def _sinyal_kalitesi(kayitlar: list[dict[str, Any]]) -> dict[str, Any]:
    sayac = Counter(str(k.get("tip", "bilinmiyor")) for k in kayitlar)
    retler = [k for k in kayitlar if k.get("tip") == "ret"]
    dispatch_retler = [k for k in kayitlar if k.get("tip") == "dispatch_ret"]
    sinyal = sayac.get("sinyal", 0)
    acilis = sayac.get("acilis", 0)
    kapanis = sayac.get("kapanis", 0)
    aday = sayac.get("ret", 0) + sinyal

    feature_sayac: Counter[str] = Counter()
    profil_sayac: Counter[str] = Counter()
    ret_kategori_sayac: Counter[str] = Counter()
    ret_kategori_tum_sayac: Counter[str] = Counter()
    ret_yon_sayac: Counter[str] = Counter()
    model_kalite_sayac: Counter[str] = Counter()
    model_kalite_kayitlari: list[dict[str, Any]] = []
    for kayit in kayitlar:
        if kayit.get("demo_profil"):
            profil_sayac[str(kayit.get("demo_profil"))] += 1
        for feature in kayit.get("model_top_features") or []:
            feature_sayac[str(feature)] += 1
        if kayit.get("tip") == "ret":
            ret_kategori_sayac[str(kayit.get("ret_kategori") or _ret_kategorisi(kayit.get("red_sebebi")))] += 1
            for kategori in kayit.get("ret_kategorileri") or _ret_kategorileri(kayit.get("red_sebebi")):
                ret_kategori_tum_sayac[str(kategori)] += 1
            ret_yon_sayac[_yon(kayit.get("yon"))] += 1
        if kayit.get("tip") in {"ret", "sinyal"}:
            wf = kayit.get("model_walk_forward_skoru")
            min_wf = _floatla(kayit.get("min_model_walk_forward_skoru"), MODEL_KALITE_VARSAYILAN_KIRMIZI_ESIK)
            bolge = _model_kalite_bolgesi(kayit)
            if wf is None:
                model_kalite_sayac[bolge] += 1
            else:
                wf_float = _floatla(wf)
                model_kalite_sayac[bolge] += 1
                model_kalite_kayitlari.append(
                    {
                        "coin": kayit.get("coin"),
                        "tip": kayit.get("tip"),
                        "yon": _yon(kayit.get("yon")),
                        "model_kalite_bolgesi": bolge,
                        "model_kalite_sari": bool(kayit.get("model_kalite_sari")),
                        "walk_forward_skoru": round(wf_float, 4),
                        "min_skor": round(min_wf, 4),
                        "guven_skoru": round(_floatla(kayit.get("guven_skoru")), 4),
                        "rr": round(_floatla(kayit.get("rr")), 4),
                    }
                )

    en_yakin_retler = sorted(
        retler,
        key=lambda k: (_floatla(k.get("guven_skoru")), _floatla(k.get("rr"))),
        reverse=True,
    )[:8]

    return {
        "aday": aday,
        "ret": sayac.get("ret", 0),
        "sinyal": sinyal,
        "dispatch_ret": sayac.get("dispatch_ret", 0),
        "acilis": acilis,
        "kapanis": kapanis,
        "sinyal_orani": round(_oran(sinyal, aday) * 100.0, 2),
        "sinyalden_acilisa_oran": round(_oran(acilis, sinyal) * 100.0, 2),
        "acilistan_kapanisa_oran": round(_oran(kapanis, acilis) * 100.0, 2),
        "en_cok_ret": dict(Counter(_ana_neden(k.get("red_sebebi")) for k in retler).most_common(5)),
        "en_cok_dispatch_ret": dict(Counter(_ana_neden(k.get("red_sebebi")) for k in dispatch_retler).most_common(5)),
        "ret_kategori_sayaci": dict(ret_kategori_sayac.most_common()),
        "ret_kategori_tum_sayaci": dict(ret_kategori_tum_sayac.most_common()),
        "ret_yon_sayaci": dict(ret_yon_sayac.most_common()),
        "model_kalite_sayaci": dict(model_kalite_sayac.most_common()),
        "en_zayif_model_sinyalleri": sorted(model_kalite_kayitlari, key=lambda k: k.get("walk_forward_skoru", 1.0))[:8],
        "en_yakin_retler": [
            {
                "coin": k.get("coin"),
                "yon": _yon(k.get("yon")),
                "kategori": k.get("ret_kategori") or _ret_kategorisi(k.get("red_sebebi")),
                "kategoriler": k.get("ret_kategorileri") or _ret_kategorileri(k.get("red_sebebi")),
                "guven_skoru": round(_floatla(k.get("guven_skoru")), 4),
                "rr": round(_floatla(k.get("rr")), 4),
                "guven_farki": None if k.get("guven_farki") is None else round(_floatla(k.get("guven_farki")), 4),
                "rr_farki": None if k.get("rr_farki") is None else round(_floatla(k.get("rr_farki")), 4),
                "red_sebebi": str(k.get("red_sebebi") or "")[:160],
            }
            for k in en_yakin_retler
        ],
        "profil_sayaci": dict(profil_sayac.most_common()),
        "model_driver_sayaci": dict(feature_sayac.most_common(8)),
    }


def _live_kapilari(performans: dict[str, Any]) -> tuple[bool, list[str]]:
    nedenler: list[str] = []
    if performans.get("toplam_islem", 0) < MIN_KAPANIS_LIVE_ADAYI:
        nedenler.append(f"En az {MIN_KAPANIS_LIVE_ADAYI} kapanis gerekir")
    if _floatla(performans.get("profit_factor")) < 1.20:
        nedenler.append("Profit factor 1.20 altinda")
    if _floatla(performans.get("expectancy")) <= 0:
        nedenler.append("Expectancy pozitif degil")
    if _floatla(performans.get("max_drawdown_pct")) > 12.0:
        nedenler.append("Max drawdown %12 ustunde")
    if int(performans.get("max_ardisik_zarar", 0)) > 4:
        nedenler.append("Ardisik zarar sayisi 4 ustunde")
    if _floatla(performans.get("win_rate")) < 42.0:
        nedenler.append("Win rate %42 altinda")
    return not nedenler, nedenler


def _tavsiyeler(
    performans: dict[str, Any],
    kalite: dict[str, Any],
    yon_metrikleri: dict[str, Any],
    model_kalite_karnesi: dict[str, Any] | None = None,
    kapanis_sebebi_metrikleri: dict[str, Any] | None = None,
) -> list[str]:
    tavsiyeler: list[str] = []
    kapanis = int(performans.get("toplam_islem", 0))
    pf = _floatla(performans.get("profit_factor"))
    expectancy = _floatla(performans.get("expectancy"))

    if kapanis < MIN_KAPANIS_INCELEME:
        tavsiyeler.append("Kapanis sayisi dusuk; esik degistirmeden once demo veri biriktir.")
    elif pf < 1.0 or expectancy <= 0:
        tavsiyeler.append("Demo edge zayif; guven/RR filtrelerini gevsetmek yerine sikilastirma adaylarini incele.")
    elif pf >= 1.2 and expectancy > 0:
        tavsiyeler.append("Demo metrikleri umut veriyor; ayni ayarlari daha uzun orneklemde izle.")

    if kalite.get("sinyal", 0) and kalite.get("sinyalden_acilisa_oran", 0.0) < 50.0:
        tavsiyeler.append("Basarili sinyallerin yaridan fazlasi acilisa donusmuyor; dispatch ret nedenlerini incele.")

    en_cok_ret = kalite.get("en_cok_ret", {})
    if en_cok_ret:
        ilk_neden = next(iter(en_cok_ret))
        tavsiyeler.append(f"En cok ret nedeni: {ilk_neden}. Once bu filtrenin davranisini gozlemle.")

    ret_kategorileri = kalite.get("ret_kategori_sayaci", {}) or {}
    if ret_kategorileri:
        ilk_kategori = next(iter(ret_kategorileri))
        if ilk_kategori == "rr":
            tavsiyeler.append("Sinyal darboğazı RR tarafında; TP/SL mesafesi ve ATR carpani birlikte incelenmeli.")
        elif ilk_kategori == "guven":
            tavsiyeler.append("Sinyal darboğazı model guveni tarafında; feature kalitesi ve model validasyonu incelenmeli.")
        elif ilk_kategori == "veri":
            tavsiyeler.append("Sinyal darboğazı veri kalitesinde; mum sayisi, bayat veri ve eksik kolonlar oncelikli.")
        elif ilk_kategori == "trend_btc":
            tavsiyeler.append("Sinyal darboğazı trend/BTC kalkaninda; live-shadow icin bu filtrenin etkisi izlenmeli.")
        elif ilk_kategori == "short_kapisi":
            tavsiyeler.append("SHORT kapisi sinyal sayisini dusuruyor; SHORT tekrar acilmadan once yon bazli edge kaniti beklenmeli.")

    if kapanis_sebebi_metrikleri:
        if "HARD_STOP" in kapanis_sebebi_metrikleri and _floatla(kapanis_sebebi_metrikleri["HARD_STOP"].get("net_pnl", 0)) < -10.0:
            tavsiyeler.append("Hard stop kayiplari yuksek; piyasa kosullarina gore ATR carpanini (suan ~2.5) genisletmeyi dusun.")
        if "TRAILING_STOP" in kapanis_sebebi_metrikleri and _floatla(kapanis_sebebi_metrikleri["TRAILING_STOP"].get("net_pnl", 0)) < 0.0:
            tavsiyeler.append("Trailing stop islemleri karli degil; stop cok erken tetiklenip iyi pozisyonlari boguyor olabilir.")
        if "TIME_OUT" in kapanis_sebebi_metrikleri and _floatla(kapanis_sebebi_metrikleri["TIME_OUT"].get("net_pnl", 0)) < 0.0:
            tavsiyeler.append("Time-out (zaman asimi) kapanislari net zarar uretmis; momentum olmadan kapanis parametresini izle.")

    model_kalite = kalite.get("model_kalite_sayaci", {}) or {}
    if model_kalite.get("kirmizi", 0) > 0:
        tavsiyeler.append("Kirmizi model kalite sinyalleri var; bu bolge LIVE_SHADOW icin ret kalmali.")
    if model_kalite.get("sari", 0) > 0:
        tavsiyeler.append("Sari model kalite sinyalleri var; demo margin kirpma ile izlenmeli, live icin beklemeli.")

    karne = model_kalite_karnesi or {}
    if karne:
        etiketli = int(karne.get("etiketli_kapanis", 0))
        if etiketli < 5:
            tavsiyeler.append("Model kalite karnesi icin etiketli kapanis az; sari/yesil karari icin veri biriktir.")
        if _floatla(karne.get("bilinmeyen_orani")) > 40.0:
            tavsiyeler.append("Kapanislarin onemli kismi model kalite etiketsiz; yeni demo journal verisiyle takip edilmeli.")

        temiz_bolge_metrikleri = karne.get("temiz_bolge_metrikleri", {}) or {}
        sari = temiz_bolge_metrikleri.get("sari", {})
        yesil = temiz_bolge_metrikleri.get("yesil", {})
        if sari.get("toplam_islem", 0) >= 5:
            if _floatla(sari.get("profit_factor")) < 1.0 or _floatla(sari.get("expectancy")) <= 0.0:
                tavsiyeler.append("Sari bolge kapanislari zayifsa margin kirpma yetmeyebilir; sari bolge daha sert izne baglanmali.")
            else:
                tavsiyeler.append("Sari bolge simdilik demo gozlemde kalabilir; live icin yine yesil bolge kaniti beklenmeli.")
        if yesil.get("toplam_islem", 0) >= 5 and _floatla(yesil.get("profit_factor")) >= 1.2 and _floatla(yesil.get("expectancy")) > 0.0:
            tavsiyeler.append("Yesil bolge temiz metrikleri guclu gorunuyor; ayni ayarla orneklem buyutulmeli.")

    for yon, metrik in yon_metrikleri.items():
        if metrik.get("toplam_islem", 0) >= 10 and _floatla(metrik.get("expectancy")) < 0:
            tavsiyeler.append(f"{yon} yonu negatif expectancy uretiyor; bu yon icin ekstra filtre dusun.")

    if int(performans.get("max_ardisik_zarar", 0)) >= 3:
        tavsiyeler.append("Ardisik zarar 3+; demo margin veya cooldown daha savunmaci olabilir.")

    return tavsiyeler[:8]


def _kaynak_ozetleri(kaynak_adaylari: list[tuple[str, Path, Callable[[Path], list[dict[str, Any]]]]]) -> list[dict[str, Any]]:
    ozetler = []
    for kaynak_tipi, kaynak_path, okuyucu in kaynak_adaylari:
        kayitlar = okuyucu(kaynak_path)
        ozetler.append(
            {
                "tip": kaynak_tipi,
                "path": str(kaynak_path),
                "var": kaynak_path.exists(),
                "kapanis_sayisi": len(kayitlar),
            }
        )
    return ozetler


def _rapor_yaz(path: Path, rapor: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_ad = tempfile.mkstemp(prefix="demo_analysis_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(rapor, f, ensure_ascii=False, indent=2)
        os.replace(tmp_ad, path)
    finally:
        if os.path.exists(tmp_ad):
            try:
                os.remove(tmp_ad)
            except OSError:
                pass


def analiz_uret(
    journal_path: Path = JOURNAL_PATH,
    report_path: Path | None = REPORT_PATH,
    db_path: Path = DB_PATH,
    limit: int = MAX_KAYIT,
) -> dict[str, Any]:
    kayitlar = _json_oku(journal_path, limit=limit)
    kapanislar = [k for k in kayitlar if k.get("tip") == "kapanis"]
    kapanis_kaynagi = "journal"
    kaynak_adaylari = [
        ("db", db_path, _db_kapanislari_oku),
        ("db", ROOT_DB_PATH, _db_kapanislari_oku),
        ("csv", CSV_PATH, _csv_kapanislari_oku),
        ("csv", ROOT_CSV_PATH, _csv_kapanislari_oku),
    ]
    kaynak_ozetleri = _kaynak_ozetleri(kaynak_adaylari)
    if not kapanislar:
        en_iyi_kaynak = max(kaynak_adaylari, key=lambda item: len(item[2](item[1])))
        kaynak_tipi, kaynak_path, okuyucu = en_iyi_kaynak
        kapanislar = okuyucu(kaynak_path)
        kapanis_kaynagi = f"{kaynak_tipi}:{kaynak_path}" if kapanislar else "yok"
    elif kapanis_kaynagi == "journal":
        kapanislar = _kapanislari_model_etiketiyle_zenginlestir(kayitlar) or kapanislar

    performans = _metrik(kapanislar)
    outlier = _outlier_analizi(kapanislar)
    degerlendirme_performansi = outlier["temiz_performans"] if outlier["temiz_kayit_sayisi"] >= MIN_KAPANIS_INCELEME else performans
    temiz_kapanislar = [k for k in kapanislar if not _outlier_mi(k, _floatla(outlier.get("parasal_esik")))]
    model_kalite_karnesi = _model_kalite_karnesi(kapanislar, temiz_kapanislar)
    kalite = _sinyal_kalitesi(kayitlar)
    yon_metrikleri = _grup_metrikleri(kapanislar, lambda k: _yon(k.get("yon")))
    temiz_yon_metrikleri = _grup_metrikleri(temiz_kapanislar, lambda k: _yon(k.get("yon")))
    guven_metrikleri = _grup_metrikleri(kapanislar, lambda k: _guven_bandi(k.get("ai_skoru")))
    kapanis_sebebi_metrikleri = _grup_metrikleri(kapanislar, _kapanis_sebebi_kategorisi)
    zaman_bandi_metrikleri = _grup_metrikleri(kapanislar, _zaman_bandi)
    coin_metrikleri = _grup_metrikleri(kapanislar, lambda k: str(k.get("coin") or "BILINMIYOR"), min_islem=2)
    coin_metrikleri = dict(
        sorted(
            coin_metrikleri.items(),
            key=lambda item: (_floatla(item[1].get("net_pnl")), item[1].get("toplam_islem", 0)),
            reverse=True,
        )[:10]
    )
    problemli_coin_metrikleri = _grup_metrikleri(
        temiz_kapanislar or kapanislar,
        lambda k: str(k.get("coin") or "BILINMIYOR"),
        min_islem=2,
    )
    problemli_coin_metrikleri = dict(
        sorted(
            problemli_coin_metrikleri.items(),
            key=lambda item: (_floatla(item[1].get("net_pnl")), -item[1].get("toplam_islem", 0)),
        )[:10]
    )
    short_metrik = temiz_yon_metrikleri.get("SHORT", {})
    short_guvenlik_notu = ""
    if short_metrik and (
        _floatla(short_metrik.get("profit_factor")) < 1.0
        or _floatla(short_metrik.get("expectancy")) <= 0
    ):
        short_guvenlik_notu = "Temiz veride SHORT yonu pozitif edge gostermiyor; SHORT kapisi kapali tutulmali."

    live_adayi, live_blok_nedenleri = _live_kapilari(degerlendirme_performansi)
    if outlier["outlier_sayisi"] > 0 and kapanis_kaynagi != "journal":
        live_adayi = False
        live_blok_nedenleri.append("Eski veride outlier/olcek sorunu var; yeni demo journal ile dogrula")

    if degerlendirme_performansi["toplam_islem"] < MIN_KAPANIS_INCELEME:
        karar = "veri_toplanmali"
    elif outlier["outlier_sayisi"] > 0 and kapanis_kaynagi != "journal":
        karar = "gecmis_veri_olcek_sorunu_incele"
    elif live_adayi:
        karar = "demo_guclu_live_icin_inceleme"
    elif degerlendirme_performansi["profit_factor"] < 1.0 or degerlendirme_performansi["expectancy"] <= 0:
        karar = "riskli_iyilestirme_gerekli"
    else:
        karar = "izle_ve_iyilestir"

    rapor = {
        "olusturma_zamani": _simdi(),
        "kaynak": {
            "journal": str(journal_path),
            "kapanis_kaynagi": kapanis_kaynagi,
            "okunan_journal_kaydi": len(kayitlar),
            "kaynak_ozetleri": kaynak_ozetleri,
        },
        "karar": karar,
        "live_adayi": live_adayi,
        "live_blok_nedenleri": live_blok_nedenleri,
        "sinyal_kalitesi": kalite,
        "performans": performans,
        "degerlendirme_performansi": degerlendirme_performansi,
        "outlier_analizi": outlier,
        "yon_metrikleri": yon_metrikleri,
        "temiz_yon_metrikleri": temiz_yon_metrikleri,
        "guven_bandi_metrikleri": guven_metrikleri,
        "kapanis_sebebi_metrikleri": kapanis_sebebi_metrikleri,
        "zaman_bandi_metrikleri": zaman_bandi_metrikleri,
        "model_kalite_karnesi": model_kalite_karnesi,
        "coin_metrikleri": coin_metrikleri,
        "problemli_coin_metrikleri": problemli_coin_metrikleri,
        "short_guvenlik_notu": short_guvenlik_notu,
        "tavsiyeler": _tavsiyeler(degerlendirme_performansi, kalite, temiz_yon_metrikleri or yon_metrikleri, model_kalite_karnesi, kapanis_sebebi_metrikleri),
    }

    if report_path is not None:
        _rapor_yaz(report_path, rapor)
    return rapor


if __name__ == "__main__":
    sonuc = analiz_uret()
    perf = sonuc["performans"]
    print(
        "Karar: {karar} | Islem: {islem} | Win: %{win:.1f} | Net: {net:+.2f} | PF: {pf:.2f} | E: {e:+.4f}".format(
            karar=sonuc["karar"],
            islem=perf["toplam_islem"],
            win=perf["win_rate"],
            net=perf["net_pnl"],
            pf=perf["profit_factor"],
            e=perf["expectancy"],
        )
    )
