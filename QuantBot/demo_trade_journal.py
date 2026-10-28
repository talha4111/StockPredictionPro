from __future__ import annotations

import json
import math
import os
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


JOURNAL_PATH = Path(__file__).resolve().parent / "demo_trade_journal.jsonl"
MAX_JOURNAL_BYTES = 5_000_000
MAX_OZET_SATIRI = 5000
_KILIT = threading.Lock()


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _temizle(deger: Any) -> Any:
    if deger is None or isinstance(deger, (str, int, float, bool)):
        if isinstance(deger, float) and not math.isfinite(deger):
            return None
        return deger
    if isinstance(deger, datetime):
        return deger.strftime("%Y-%m-%d %H:%M:%S")
    if hasattr(deger, "item"):
        try:
            return _temizle(deger.item())
        except Exception:
            pass
    if isinstance(deger, dict):
        return {str(k): _temizle(v) for k, v in deger.items()}
    if isinstance(deger, (list, tuple, set)):
        return [_temizle(v) for v in deger]
    return str(deger)


def _floatla(deger: Any, varsayilan: float = 0.0) -> float:
    try:
        sonuc = float(deger)
        return sonuc if math.isfinite(sonuc) else varsayilan
    except Exception:
        return varsayilan


def _demo_hesap_mi(hesap_tipi: Any) -> bool:
    return str(hesap_tipi or "").upper() in {"DEMO", "TESTNET", "PAPER"}


def _yon_sadelestir(yon: Any) -> str:
    metin = str(yon or "").upper()
    if "SHORT" in metin or "DUS" in metin or "DU\u015e" in metin or "D\u00dc\u015e" in metin:
        return "SHORT"
    if "LONG" in metin or "YUK" in metin or "Y\u00dcK" in metin:
        return "LONG"
    return metin or "BILINMIYOR"


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


def _rotate_gerekirse() -> None:
    try:
        if JOURNAL_PATH.exists() and JOURNAL_PATH.stat().st_size > MAX_JOURNAL_BYTES:
            eski = JOURNAL_PATH.with_name("demo_trade_journal.old.jsonl")
            if eski.exists():
                eski.unlink()
            os.replace(JOURNAL_PATH, eski)
    except OSError:
        pass


def olay_yaz(tip: str, **detay: Any) -> dict[str, Any]:
    kayit = {"zaman": _simdi(), "tip": tip, **_temizle(detay)}
    try:
        with _KILIT:
            JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
            _rotate_gerekirse()
            with JOURNAL_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(kayit, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        return {}
    return kayit


def rapor_kaydet(rapor: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(rapor, dict):
        return {}

    model_aciklama = rapor.get("model_aciklama") or {}
    model_kalite = rapor.get("model_kalite") or {}
    top_features = model_aciklama.get("top_features") or []
    top_feature_adlari = []
    for item in top_features[:5]:
        if isinstance(item, dict):
            top_feature_adlari.append(item.get("ad", "?"))
        else:
            top_feature_adlari.append(str(item))

    tip = "sinyal" if rapor.get("success") else "ret"
    red_sebebi = rapor.get("red_sebebi", "")
    demo_guven_min = _floatla(rapor.get("demo_guven_min"))
    demo_rr_min = _floatla(rapor.get("demo_rr_min"))
    guven = _floatla(rapor.get("guven_skoru"))
    rr = _floatla(rapor.get("rr"))
    return olay_yaz(
        tip,
        coin=rapor.get("coin"),
        success=bool(rapor.get("success")),
        demo_ok=bool(rapor.get("demo_ok")),
        live_ok=bool(rapor.get("live_ok")),
        yon=_yon_sadelestir(rapor.get("yon")),
        guven_skoru=round(guven, 4),
        dinamik_esik=round(_floatla(rapor.get("dinamik_esik")), 4),
        fiyat=_floatla(rapor.get("fiyat")),
        tp=_floatla(rapor.get("tp")),
        sl=_floatla(rapor.get("sl")),
        rr=round(rr, 4),
        demo_profil=rapor.get("demo_profil"),
        demo_live_shadow=bool(rapor.get("demo_live_shadow")),
        short_islem_aktif=bool(rapor.get("short_islem_aktif")),
        demo_rr_min=rapor.get("demo_rr_min"),
        demo_guven_min=rapor.get("demo_guven_min"),
        model_walk_forward_skoru=model_kalite.get("walk_forward_skoru"),
        min_model_walk_forward_skoru=rapor.get("min_model_walk_forward_skoru"),
        model_kalite_bolgesi=rapor.get("model_kalite_bolgesi"),
        model_kalite_sari=bool(rapor.get("model_kalite_sari")),
        model_kalite_sari_margin_carpani=rapor.get("model_kalite_sari_margin_carpani"),
        model_egitim_mum_sayisi=model_kalite.get("egitim_mum_sayisi"),
        model_kalite_okundu=bool(model_kalite.get("okundu")),
        guven_farki=None if demo_guven_min <= 0 else round(guven - demo_guven_min, 4),
        rr_farki=None if demo_rr_min <= 0 else round(rr - demo_rr_min, 4),
        ret_kategori=rapor.get("ret_kategori") or _ret_kategorisi(red_sebebi),
        ret_kategorileri=rapor.get("ret_kategorileri") or _ret_kategorileri(red_sebebi),
        red_sebebi=red_sebebi,
        veri_kalite=rapor.get("veri_kalite", {}),
        model_top_features=top_feature_adlari,
        rejim=rapor.get("piyasa_kalite", {}).get("rejim", "BILINMIYOR"),
    )


def acilis_kaydet(
    *,
    hesap_tipi: str,
    sembol: str,
    yon: str,
    giris: float,
    miktar: float,
    margin: float,
    kaldirac: float,
    ai_skoru: float,
    tp: float,
    sl: float,
    rr: float | None = None,
    risk_metni: str = "",
    tahmini_zarar: float = 0.0,
    demo_profil: str | None = None,
    demo_live_shadow: bool | None = None,
    short_islem_aktif: bool | None = None,
    model_walk_forward_skoru: float | None = None,
    min_model_walk_forward_skoru: float | None = None,
    model_kalite_bolgesi: str | None = None,
    model_kalite_sari: bool | None = None,
    model_kalite_sari_margin_carpani: float | None = None,
    rejim: str = "BILINMIYOR",
) -> dict[str, Any]:
    if not _demo_hesap_mi(hesap_tipi):
        return {}
    return olay_yaz(
        "acilis",
        hesap_tipi=hesap_tipi,
        coin=sembol,
        yon=_yon_sadelestir(yon),
        giris=_floatla(giris),
        miktar=_floatla(miktar),
        margin=_floatla(margin),
        kaldirac=_floatla(kaldirac),
        ai_skoru=_floatla(ai_skoru),
        tp=_floatla(tp),
        sl=_floatla(sl),
        rr=None if rr is None else _floatla(rr),
        risk_metni=risk_metni,
        tahmini_zarar=_floatla(tahmini_zarar),
        demo_profil=demo_profil,
        demo_live_shadow=None if demo_live_shadow is None else bool(demo_live_shadow),
        short_islem_aktif=None if short_islem_aktif is None else bool(short_islem_aktif),
        model_walk_forward_skoru=None if model_walk_forward_skoru is None else _floatla(model_walk_forward_skoru),
        min_model_walk_forward_skoru=None if min_model_walk_forward_skoru is None else _floatla(min_model_walk_forward_skoru),
        model_kalite_bolgesi=model_kalite_bolgesi,
        model_kalite_sari=None if model_kalite_sari is None else bool(model_kalite_sari),
        model_kalite_sari_margin_carpani=None if model_kalite_sari_margin_carpani is None else _floatla(model_kalite_sari_margin_carpani),
        rejim=rejim,
    )


def kapanis_kaydet(
    *,
    hesap_tipi: str,
    sembol: str,
    yon: str,
    giris: float,
    cikis: float,
    pnl_usdt: float,
    pnl_yuzde: float,
    ai_skoru: float,
    tp: float | None = None,
    sl: float | None = None,
    rr: float | None = None,
    risk_metni: str = "",
    tahmini_zarar: float = 0.0,
    demo_profil: str | None = None,
    demo_live_shadow: bool | None = None,
    short_islem_aktif: bool | None = None,
    model_walk_forward_skoru: float | None = None,
    min_model_walk_forward_skoru: float | None = None,
    model_kalite_bolgesi: str | None = None,
    model_kalite_sari: bool | None = None,
    model_kalite_sari_margin_carpani: float | None = None,
    kapanis_sebebi: str = "",
    rejim: str = "BILINMIYOR",
) -> dict[str, Any]:
    if not _demo_hesap_mi(hesap_tipi):
        return {}
    return olay_yaz(
        "kapanis",
        hesap_tipi=hesap_tipi,
        coin=sembol,
        yon=_yon_sadelestir(yon),
        giris=_floatla(giris),
        cikis=_floatla(cikis),
        pnl_usdt=_floatla(pnl_usdt),
        pnl_yuzde=_floatla(pnl_yuzde),
        ai_skoru=_floatla(ai_skoru),
        tp=None if tp is None else _floatla(tp),
        sl=None if sl is None else _floatla(sl),
        rr=None if rr is None else _floatla(rr),
        risk_metni=risk_metni,
        tahmini_zarar=_floatla(tahmini_zarar),
        demo_profil=demo_profil,
        demo_live_shadow=None if demo_live_shadow is None else bool(demo_live_shadow),
        short_islem_aktif=None if short_islem_aktif is None else bool(short_islem_aktif),
        model_walk_forward_skoru=None if model_walk_forward_skoru is None else _floatla(model_walk_forward_skoru),
        min_model_walk_forward_skoru=None if min_model_walk_forward_skoru is None else _floatla(min_model_walk_forward_skoru),
        model_kalite_bolgesi=model_kalite_bolgesi,
        model_kalite_sari=None if model_kalite_sari is None else bool(model_kalite_sari),
        model_kalite_sari_margin_carpani=None if model_kalite_sari_margin_carpani is None else _floatla(model_kalite_sari_margin_carpani),
        kapanis_sebebi=kapanis_sebebi,
        rejim=rejim,
    )


def _kayitlari_oku(limit: int = MAX_OZET_SATIRI) -> list[dict[str, Any]]:
    if not JOURNAL_PATH.exists():
        return []
    try:
        with JOURNAL_PATH.open("r", encoding="utf-8") as f:
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


def ozet_hesapla(limit: int = MAX_OZET_SATIRI) -> dict[str, Any]:
    kayitlar = _kayitlari_oku(limit)
    sayac = Counter(str(k.get("tip", "bilinmiyor")) for k in kayitlar)
    kapanislar = [k for k in kayitlar if k.get("tip") == "kapanis"]
    pnller = [_floatla(k.get("pnl_usdt")) for k in kapanislar]
    karlar = [p for p in pnller if p > 0]
    zararlar = [p for p in pnller if p <= 0]
    gross_profit = sum(karlar)
    gross_loss = abs(sum(zararlar))
    profit_factor = None
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = 999.0

    ret_nedenleri = Counter(
        str(k.get("red_sebebi") or "Belirsiz").split("|")[0].strip()
        for k in kayitlar
        if k.get("tip") == "ret"
    )
    ret_kategorileri = Counter(
        str(k.get("ret_kategori") or _ret_kategorisi(k.get("red_sebebi")))
        for k in kayitlar
        if k.get("tip") == "ret"
    )
    ret_kategorileri_tum = Counter()
    for kayit in kayitlar:
        if kayit.get("tip") != "ret":
            continue
        for kategori in kayit.get("ret_kategorileri") or _ret_kategorileri(kayit.get("red_sebebi")):
            ret_kategorileri_tum[str(kategori)] += 1

    toplam_kapanis = len(kapanislar)
    return {
        "kayit_sayisi": len(kayitlar),
        "ret": sayac.get("ret", 0),
        "dispatch_ret": sayac.get("dispatch_ret", 0),
        "sinyal": sayac.get("sinyal", 0),
        "acilis": sayac.get("acilis", 0),
        "kapanis": toplam_kapanis,
        "win_rate": round((len(karlar) / toplam_kapanis * 100.0) if toplam_kapanis else 0.0, 2),
        "net_pnl": round(sum(pnller), 4),
        "profit_factor": None if profit_factor is None else round(profit_factor, 4),
        "avg_pnl": round((sum(pnller) / toplam_kapanis) if toplam_kapanis else 0.0, 4),
        "son_olay": kayitlar[-1] if kayitlar else {},
        "en_cok_ret": dict(ret_nedenleri.most_common(3)),
        "en_cok_ret_kategori": dict(ret_kategorileri.most_common(5)),
        "en_cok_ret_kategori_tum": dict(ret_kategorileri_tum.most_common(8)),
    }


if __name__ == "__main__":
    print(json.dumps(ozet_hesapla(), ensure_ascii=False, indent=2))
