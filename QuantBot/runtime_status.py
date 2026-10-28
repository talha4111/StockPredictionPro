from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any


STATUS_PATH = Path(__file__).resolve().parent / "runtime_status.json"
_KILIT = threading.Lock()
_MAX_EVENT = 30


def _simdi() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _varsayilan_status() -> dict[str, Any]:
    return {
        "guncelleme_zamani": _simdi(),
        "faz": "başlatılıyor",
        "bot_durumu": "bilinmiyor",
        "live_mod": False,
        "live_tetik": False,
        "ping_modu": False,
        "demo_profil": "LIVE_SHADOW",
        "demo_live_shadow": True,
        "demo_emir_aktif": False,
        "short_islem_aktif": False,
        "hedge_sniper": {},
        "demo_kasa": 0.0,
        "demo_wallet": 0.0,
        "demo_equity": 0.0,
        "demo_pnl": 0.0,
        "demo_realized_pnl": 0.0,
        "demo_unrealized_pnl": 0.0,
        "live_kasa": 0.0,
        "live_equity": 0.0,
        "portfoy_isi_yuzde": 0.0,
        "son_ret": {},
        "ret_ozeti": {},
        "scout_ozeti": {},
        "sinyal_darbogaz": {},
        "model_karsilastirma": {},
        "emir_senkron": {},
        "demo_journal": {},
        "demo_analiz": {},
        "demo_muhasebe": {},
        "son_risk_ret": {},
        "son_islem": {},
        "son_dongu": {},
        "son_hata": {},
        "eventler": [],
    }


def status_oku() -> dict[str, Any]:
    if not STATUS_PATH.exists():
        return _varsayilan_status()
    try:
        with STATUS_PATH.open("r", encoding="utf-8") as f:
            veri = json.load(f)
        temel = _varsayilan_status()
        temel.update(veri if isinstance(veri, dict) else {})
        return temel
    except Exception:
        return _varsayilan_status()


def status_yaz(guncelleme: dict[str, Any] | None = None, event: dict[str, Any] | None = None) -> dict[str, Any]:
    with _KILIT:
        veri = status_oku()
        veri["guncelleme_zamani"] = _simdi()

        if guncelleme:
            veri.update(guncelleme)

        if event:
            olay = {"zaman": _simdi(), **event}
            eventler = veri.get("eventler", [])
            if not isinstance(eventler, list):
                eventler = []
            eventler.append(olay)
            veri["eventler"] = eventler[-_MAX_EVENT:]

        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_ad = tempfile.mkstemp(prefix="runtime_status_", suffix=".json", dir=str(STATUS_PATH.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(veri, f, ensure_ascii=False, indent=2)
            os.replace(tmp_ad, STATUS_PATH)
        finally:
            if os.path.exists(tmp_ad):
                try:
                    os.remove(tmp_ad)
                except OSError:
                    pass
        return veri


def olay_kaydet(tip: str, mesaj: str, **detay: Any) -> dict[str, Any]:
    return status_yaz(event={"tip": tip, "mesaj": mesaj, **detay})


if __name__ == "__main__":
    status_yaz({"faz": "kontrol", "bot_durumu": "runtime_status modülü hazır"}, {"tip": "selftest", "mesaj": "status yazıldı"})
    print(STATUS_PATH)
