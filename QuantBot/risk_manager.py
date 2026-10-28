import os
import json
import pandas as pd
import numpy as np
import unicodedata
from datetime import datetime, timezone
from collections import Counter
from config import *
from model_contract import FeatureCoverageSpec

# Runtime status için (Eğer yoksa dummy yaratılır)
try:
    from runtime_status import status_yaz, olay_kaydet
except Exception:
    def status_yaz(guncelleme=None, event=None): return {}
    def olay_kaydet(tip, mesaj, **detay): return {}

SINYAL_RET_ISTATISTIKLERI = {}
_GUNLUK_RISK_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gunluk_risk_durumu.json')
_V6_FEATURE_COVERAGE = FeatureCoverageSpec(
    schema_version=6,
    base_timeframe='15m',
)

def _yon_ascii(yon):
    metin = unicodedata.normalize("NFKD", str(yon or ""))
    return metin.encode("ascii", "ignore").decode("ascii").upper()

def _savunma_margin_carpani(ardisik_zarar, hesap="DEMO"):
    """
    Ardisik zarar sayisina gore kademeli margin dusurme.
    0-1 zarar  -> 1.00 (normal)
    2 zarar    -> 0.70 (%30 dusur)
    3 zarar    -> 0.50 (%50 dusur)
    4+ zarar   -> 0.30 (%70 dusur, minimum pozisyon)
    """
    if ardisik_zarar <= 1:
        return 1.0
    elif ardisik_zarar == 2:
        return 0.70
    elif ardisik_zarar == 3:
        return 0.50
    else:
        return 0.30

def _risk_ret(sembol, neden, **detay):
    print(f"🛑 [RİSK KAPISI] {sembol} iptal: {neden}")
    status_yaz({
        "son_risk_ret": {
            "sembol": sembol,
            "neden": neden,
            "detay": detay,
            "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    }, event={"tip": "risk_ret", "mesaj": f"{sembol}: {neden}"})
    return None

def _gunluk_risk_yukle():
    try:
        if os.path.exists(_GUNLUK_RISK_DOSYA):
            with open(_GUNLUK_RISK_DOSYA, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"[RISK] gunluk risk durumu okunamadi; yeni risk durumu kilitli baslatilacak: {e}")
        return {"_risk_state_load_error": str(e)}
    return {}

def _gunluk_risk_kaydet(durum):
    try:
        tmp = _GUNLUK_RISK_DOSYA + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(durum, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _GUNLUK_RISK_DOSYA)
    except Exception as e:
        print(f"[RISK] gunluk risk durumu yazilamadi: {e}")

def _gunluk_risk_limit_yuzdesi(hesap):
    return LIVE_GUNLUK_ZARAR_LIMITI_YUZDESI if str(hesap).upper() == "LIVE" else DEMO_GUNLUK_ZARAR_LIMITI_YUZDESI

def _gunluk_risk_bos(hesap):
    return {
        "aktif": bool(GUNLUK_ZARAR_LIMITI_AKTIF),
        "hesap": str(hesap).upper(),
        "tarih": datetime.now().strftime("%Y-%m-%d"),
        "kilitli": False,
        "neden": "",
        "baslangic_equity": 0.0,
        "anlik_equity": 0.0,
        "gunluk_pnl": 0.0,
        "limit_yuzde": round(_gunluk_risk_limit_yuzdesi(hesap) * 100.0, 4),
        "limit_usdt": 0.0,
        "kalan_zarar_hakki": 0.0,
        "acik_pozisyon_dahil": bool(GUNLUK_ZARAR_ACIK_POZISYON_DAHIL),
    }

def _gunluk_risk_guncelle(hesap, wallet, equity=None):
    hesap = "LIVE" if str(hesap).upper() == "LIVE" else "DEMO"
    bugun = datetime.now().strftime("%Y-%m-%d")
    durum = _gunluk_risk_yukle()
    if durum.get("_risk_state_load_error"):
        hesap_durum = _gunluk_risk_bos(hesap)
        hesap_durum.update({
            "kilitli": True,
            "neden": "gunluk risk durumu okunamadi",
            "veri_yok": True,
        })
        return hesap_durum
    anahtar = hesap.lower()
    hesap_durum = durum.get(anahtar, {})
    if not isinstance(hesap_durum, dict):
        hesap_durum = {}

    if not GUNLUK_ZARAR_LIMITI_AKTIF:
        hesap_durum = _gunluk_risk_bos(hesap)
        hesap_durum["aktif"] = False
        durum[anahtar] = hesap_durum
        _gunluk_risk_kaydet(durum)
        return hesap_durum

    try:
        wallet = float(wallet or 0.0)
    except Exception:
        wallet = 0.0
    try:
        equity = float(equity if equity is not None else wallet)
    except Exception:
        equity = wallet

    anlik = equity if GUNLUK_ZARAR_ACIK_POZISYON_DAHIL and equity > 0 else wallet
    if anlik <= 0:
        if hesap_durum.get("tarih") == bugun:
            hesap_durum.setdefault("aktif", True)
            hesap_durum.setdefault("hesap", hesap)
            hesap_durum.setdefault("veri_yok", True)
            return hesap_durum
        return _gunluk_risk_bos(hesap)

    baslangic = float(hesap_durum.get("baslangic_equity") or 0.0)
    if hesap_durum.get("tarih") != bugun or baslangic <= 0:
        baslangic = anlik
        hesap_durum = _gunluk_risk_bos(hesap)
        hesap_durum["baslangic_equity"] = round(baslangic, 4)

    limit_yuzde = _gunluk_risk_limit_yuzdesi(hesap)
    limit_usdt = max(0.0, baslangic * limit_yuzde)
    gunluk_pnl = anlik - baslangic
    onceki_kilit = bool(hesap_durum.get("kilitli"))
    kilitli = limit_usdt > 0 and gunluk_pnl <= -limit_usdt
    neden = ""
    if kilitli:
        neden = f"{hesap} gunluk zarar limiti asildi ({gunluk_pnl:.2f} <= -{limit_usdt:.2f})"

    hesap_durum.update({
        "aktif": True,
        "hesap": hesap,
        "tarih": bugun,
        "kilitli": bool(kilitli),
        "neden": neden,
        "baslangic_equity": round(float(baslangic), 4),
        "anlik_equity": round(float(anlik), 4),
        "wallet": round(float(wallet), 4),
        "equity": round(float(equity), 4),
        "gunluk_pnl": round(float(gunluk_pnl), 4),
        "limit_yuzde": round(float(limit_yuzde) * 100.0, 4),
        "limit_usdt": round(float(limit_usdt), 4),
        "kalan_zarar_hakki": round(max(0.0, limit_usdt + gunluk_pnl), 4),
        "acik_pozisyon_dahil": bool(GUNLUK_ZARAR_ACIK_POZISYON_DAHIL),
        "veri_yok": False,
        "guncelleme": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    durum[anahtar] = hesap_durum
    _gunluk_risk_kaydet(durum)

    if kilitli and not onceki_kilit:
        status_yaz(event={"tip": "risk_kilit", "mesaj": neden})
    return hesap_durum

def _gunluk_risk_ozeti():
    durum = _gunluk_risk_yukle()
    return {
        "aktif": bool(GUNLUK_ZARAR_LIMITI_AKTIF),
        "acik_pozisyon_dahil": bool(GUNLUK_ZARAR_ACIK_POZISYON_DAHIL),
        "demo": durum.get("demo", _gunluk_risk_bos("DEMO")),
        "live": durum.get("live", _gunluk_risk_bos("LIVE")),
    }

def _gunluk_zarar_kapisi_acik_mi(hesap, sembol, kasa_durum):
    hesap = "LIVE" if str(hesap).upper() == "LIVE" else "DEMO"
    wallet = kasa_durum.get(f"{hesap}_KASA", 0.0)
    equity = kasa_durum.get(f"{hesap}_EQUITY", wallet)
    durum = _gunluk_risk_guncelle(hesap, wallet, equity)
    status_yaz({"gunluk_risk": _gunluk_risk_ozeti()})
    if durum.get("kilitli"):
        _risk_ret(sembol, durum.get("neden") or f"{hesap} gunluk zarar limiti", hesap=hesap, gunluk_risk=durum)
        return False
    return True

def _risk_kapisi_kontrolu(yon, sembol, anlik_fiyat, hesaplanan_sl, toplam_kasa, kullanilacak_margin, kaldirac, borsa_istemci, risk_metni):
    try:
        anlik_fiyat = float(anlik_fiyat)
        hesaplanan_sl = float(hesaplanan_sl)
        toplam_kasa = float(toplam_kasa)
        kullanilacak_margin = float(kullanilacak_margin)
        kaldirac = max(1, int(kaldirac))

        yon_sade = _yon_ascii(yon)
        long_mu = "YUKSELIS" in yon_sade or "LONG" in yon_sade
        short_mu = "DUSUS" in yon_sade or "SHORT" in yon_sade

        if anlik_fiyat <= 0 or hesaplanan_sl <= 0 or toplam_kasa <= 0:
            return _risk_ret(sembol, "fiyat, SL veya kasa değeri geçersiz", fiyat=anlik_fiyat, sl=hesaplanan_sl, kasa=toplam_kasa)
        if not long_mu and not short_mu:
            return _risk_ret(sembol, f"yön okunamadı ({yon})")
        if long_mu and hesaplanan_sl >= anlik_fiyat:
            return _risk_ret(sembol, "LONG için SL giriş fiyatının altında değil", fiyat=anlik_fiyat, sl=hesaplanan_sl)
        if short_mu and hesaplanan_sl <= anlik_fiyat:
            return _risk_ret(sembol, "SHORT için SL giriş fiyatının üstünde değil", fiyat=anlik_fiyat, sl=hesaplanan_sl)

        stop_mesafe = abs(anlik_fiyat - hesaplanan_sl)
        if stop_mesafe <= 0:
            return _risk_ret(sembol, "stop mesafesi geçersiz", fiyat=anlik_fiyat, sl=hesaplanan_sl)

        max_zarar_tutari = toplam_kasa * MAX_POZISYON_ZARAR_YUZDESI
        hedef_zarar_tutari = min(toplam_kasa * HEDEF_POZISYON_RISK_YUZDESI, max_zarar_tutari)

        max_margin_hacmi = kullanilacak_margin * kaldirac
        max_margin_miktar = float(borsa_istemci.amount_to_precision(sembol, max_margin_hacmi / anlik_fiyat))
        risk_bazli_miktar = float(borsa_istemci.amount_to_precision(sembol, hedef_zarar_tutari / stop_mesafe))
        if max_margin_miktar <= 0 or risk_bazli_miktar <= 0:
            return _risk_ret(
                sembol,
                "risk bazlı emir miktarı sıfır",
                max_margin_hacmi=max_margin_hacmi,
                hedef_zarar=hedef_zarar_tutari,
                stop_mesafe=stop_mesafe,
            )

        miktar = min(max_margin_miktar, risk_bazli_miktar)
        islem_hacmi = miktar * anlik_fiyat
        kullanilacak_margin = islem_hacmi / kaldirac
        tahmini_zarar = miktar * stop_mesafe
        risk_metni += f" | Risk hedefi: %{HEDEF_POZISYON_RISK_YUZDESI*100:.2f}"

        if tahmini_zarar > max_zarar_tutari:
            ayarlanmis_miktar = float(borsa_istemci.amount_to_precision(sembol, max_zarar_tutari / stop_mesafe))
            if ayarlanmis_miktar <= 0:
                return _risk_ret(sembol, "%2 zarar limitine göre miktar sıfıra düştü", max_zarar=max_zarar_tutari, stop_mesafe=stop_mesafe)
            miktar = ayarlanmis_miktar
            islem_hacmi = miktar * anlik_fiyat
            kullanilacak_margin = islem_hacmi / kaldirac
            tahmini_zarar = miktar * stop_mesafe
            risk_metni += f" | Risk kapısı: max %{MAX_POZISYON_ZARAR_YUZDESI*100:.1f} zarar"

        if islem_hacmi < MIN_EMIR_NOTIONAL_USDT:
            return _risk_ret(sembol, f"emir büyüklüğü {islem_hacmi:.2f}$ < {MIN_EMIR_NOTIONAL_USDT:.2f}$", islem_hacmi=islem_hacmi)

        return {
            'kullanilacak_margin': kullanilacak_margin,
            'islem_hacmi': islem_hacmi,
            'miktar': miktar,
            'risk_metni': risk_metni,
            'tahmini_zarar': tahmini_zarar,
            'max_zarar_tutari': max_zarar_tutari
        }
    except Exception as e:
        return _risk_ret(sembol, f"risk hesabı yapılamadı ({e})")

def _planlanan_rr(pozisyon_yonu, giris_fiyati, tp_fiyati, sl_fiyati):
    try:
        giris_fiyati = float(giris_fiyati)
        tp_fiyati = float(tp_fiyati)
        sl_fiyati = float(sl_fiyati)
        if str(pozisyon_yonu).upper() == "LONG":
            risk = giris_fiyati - sl_fiyati
            odul = tp_fiyati - giris_fiyati
        else:
            risk = sl_fiyati - giris_fiyati
            odul = giris_fiyati - tp_fiyati
        return round(odul / risk, 4) if risk > 0 else 0.0
    except Exception:
        return 0.0

def _ret_nedeni_kaydet(neden):
    ana_neden = (neden or "Belirsiz").split("|")[0].strip()
    SINYAL_RET_ISTATISTIKLERI[ana_neden] = SINYAL_RET_ISTATISTIKLERI.get(ana_neden, 0) + 1
    status_yaz({"ret_ozeti": dict(SINYAL_RET_ISTATISTIKLERI)})

def _ret_kategorisi(neden):
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

def _ret_kategorileri(neden):
    parcalar = [p.strip() for p in str(neden or "").split("|") if p.strip()]
    if not parcalar:
        return [_ret_kategorisi(neden)]
    kategoriler = []
    for parca in parcalar:
        kategori = _ret_kategorisi(parca)
        if kategori not in kategoriler:
            kategoriler.append(kategori)
    return kategoriler or ["belirsiz"]

def _yon_sadelestir(yon):
    metin = str(yon or "").upper()
    if "SHORT" in metin or "DÜŞ" in metin or "DUS" in metin:
        return "SHORT"
    if "LONG" in metin or "YÜK" in metin or "YUK" in metin:
        return "LONG"
    if "NÖTR" in metin or "NOTR" in metin:
        return "NOTR"
    return metin or "BILINMIYOR"

def _float_guvenli(deger, varsayilan=0.0):
    try:
        sonuc = float(deger)
        return sonuc if np.isfinite(sonuc) else varsayilan
    except Exception:
        return varsayilan

def _model_kalite_oku(sembol, is_crypto=True):
    safe_name = str(sembol).replace('/', '-')
    prefix = "beyin" if is_crypto else "stock_beyin"
    meta_dosya = f"{prefix}_{safe_name}_meta.json"
    kalite = {
        "meta_dosya": meta_dosya,
        "walk_forward_skoru": None,
        "model_schema_version": None,
        "egitim_mum_sayisi": None,
        "sinif_sayilari": None,
        "recent_balanced_accuracy": None,
        "recent_brier_score": None,
        "recent_holdout_rows": None,
        "recent_profitable_up_count": None,
        "recent_signal_count": None,
        "recent_signal_win_rate": None,
        "recent_strategy_net_return": None,
        "recent_strategy_profit_factor": None,
        "recent_strategy_max_drawdown": None,
        "okundu": False,
    }
    try:
        with open(meta_dosya, "r", encoding="utf-8") as f:
            meta = json.load(f)
        kalite.update({
            "walk_forward_skoru": meta.get("walk_forward_skoru"),
            "model_schema_version": meta.get("model_schema_version"),
            "egitim_mum_sayisi": meta.get("egitim_mum_sayisi"),
            "sinif_sayilari": meta.get("sinif_sayilari"),
            "recent_balanced_accuracy": meta.get("recent_balanced_accuracy"),
            "recent_brier_score": meta.get("recent_brier_score"),
            "recent_holdout_rows": meta.get("recent_holdout_rows"),
            "recent_profitable_up_count": meta.get("recent_profitable_up_count"),
            "recent_signal_count": meta.get("recent_signal_count"),
            "recent_signal_win_rate": meta.get("recent_signal_win_rate"),
            "recent_strategy_net_return": meta.get("recent_strategy_net_return"),
            "recent_strategy_profit_factor": meta.get("recent_strategy_profit_factor"),
            "recent_strategy_max_drawdown": meta.get("recent_strategy_max_drawdown"),
            "okundu": True,
        })
    except Exception as e:
        kalite["hata"] = str(e)[:120]
    return kalite

def _sinyal_darbogaz_ozeti(tahmin_havuzu, sinyal_havuzu, aday_sayisi, scout_ozeti=None):
    kategori_sayaci = Counter()
    tum_kategori_sayaci = Counter()
    ana_ret_sayaci = Counter()
    yon_sayaci = Counter()
    sinyal_yon_sayaci = Counter()
    ret_adaylari = []

    for rapor in tahmin_havuzu:
        yon = _yon_sadelestir(rapor.get("yon"))
        yon_sayaci[yon] += 1
        if rapor.get("success"):
            sinyal_yon_sayaci[yon] += 1
            continue

        neden = str(rapor.get("red_sebebi") or "Belirsiz")
        kategori = rapor.get("ret_kategori") or _ret_kategorisi(neden)
        kategoriler = rapor.get("ret_kategorileri") or _ret_kategorileri(neden)
        kategori_sayaci[kategori] += 1
        for tek_kategori in kategoriler:
            tum_kategori_sayaci[tek_kategori] += 1
        ana_ret_sayaci[neden.split("|")[0].strip()[:80] or "Belirsiz"] += 1
        ret_adaylari.append(
            {
                "coin": rapor.get("coin"),
                "yon": yon,
                "guven": round(_float_guvenli(rapor.get("guven_skoru")), 2),
                "rr": round(_float_guvenli(rapor.get("rr")), 3),
                "kategori": kategori,
                "kategoriler": kategoriler,
                "neden": neden[:140],
            }
        )

    ret_adaylari.sort(key=lambda x: (x["guven"], x["rr"]), reverse=True)
    tahmin_sayisi = len(tahmin_havuzu)
    sinyal_sayisi = len(sinyal_havuzu)
    ozet = {
        "aday_sayisi": int(aday_sayisi),
        "tahmin_sayisi": tahmin_sayisi,
        "ret_sayisi": max(0, tahmin_sayisi - sinyal_sayisi),
        "sinyal_sayisi": sinyal_sayisi,
        "sinyal_orani": round((sinyal_sayisi / tahmin_sayisi * 100.0) if tahmin_sayisi else 0.0, 2),
        "ret_kategorileri": dict(kategori_sayaci.most_common()),
        "ret_kategorileri_tum": dict(tum_kategori_sayaci.most_common()),
        "en_cok_ret": dict(ana_ret_sayaci.most_common(5)),
        "yon_dagilimi": dict(yon_sayaci.most_common()),
        "sinyal_yon_dagilimi": dict(sinyal_yon_sayaci.most_common()),
        "en_yakin_retler": ret_adaylari[:5],
        "demo_profil": DEMO_CALISMA_PROFILI,
        "short_islem_aktif": SHORT_ISLEM_AKTIF,
        "demo_rr_min": 1.5 if DEMO_LIVE_SHADOW_AKTIF else 1.2,
        "demo_guven_min": 58.0 if DEMO_LIVE_SHADOW_AKTIF else 60.0,
    }
    if scout_ozeti:
        ozet["scout"] = scout_ozeti
    return ozet

def _ret_raporu(hedef_coin, neden, guven_skoru=0.0, yon="NÖTR ⚖️", fiyat=0.0, dinamik_esik=60.0, ekstra=None):
    _ret_nedeni_kaydet(neden)
    rapor = {
        'coin': hedef_coin,
        'live_ok': False,
        'demo_ok': False,
        'success': False,
        'guven_skoru': float(guven_skoru or 0.0),
        'yon': yon,
        'fiyat': float(fiyat or 0.0),
        'tp': 0.0,
        'sl': 0.0,
        'rr': 0.0,
        'margin_override': DEMO_MIN_MARGIN_YUZDESI,
        'dinamik_esik': dinamik_esik,
        'demo_profil': DEMO_CALISMA_PROFILI,
        'demo_live_shadow': DEMO_LIVE_SHADOW_AKTIF,
        'short_islem_aktif': SHORT_ISLEM_AKTIF,
        'ret_kategori': _ret_kategorisi(neden),
        'ret_kategorileri': _ret_kategorileri(neden),
        'red_sebebi': neden
    }
    if ekstra:
        rapor.update(ekstra)
    status_yaz({
        "son_ret": {
            "coin": hedef_coin,
            "neden": neden,
            "guven_skoru": rapor["guven_skoru"],
            "yon": yon,
            "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    })
    return rapor

def _veri_kalitesi_kontrol(hedef_coin, df, gerekli_kolonlar):
    kalite = {'mum_sayisi': 0, 'son_mum_yasi_dk': None}
    if df is None or df.empty:
        return False, "Veri yok", kalite

    kalite['mum_sayisi'] = int(len(df))
    if len(df) < MIN_ANALIZ_MUM_SAYISI:
        return False, f"Yetersiz veri({len(df)}<{MIN_ANALIZ_MUM_SAYISI})", kalite

    eksik = [kolon for kolon in gerekli_kolonlar if kolon not in df.columns]
    if eksik:
        return False, f"Eksik kolonlar: {eksik}", kalite

    try:
        son_ts = df.index[-1]
        if hasattr(son_ts, 'to_pydatetime'):
            son_dt = son_ts.to_pydatetime()
        else:
            son_dt = son_ts
        if getattr(son_dt, 'tzinfo', None) is not None:
            son_dt = son_dt.astimezone(timezone.utc).replace(tzinfo=None)
        simdi_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        yas_dk = (simdi_utc - son_dt).total_seconds() / 60
        kalite['son_mum_yasi_dk'] = round(float(yas_dk), 1)
        if yas_dk > MAX_VERI_YASI_DAKIKA:
            return False, f"Bayat veri({yas_dk:.0f}dk>{MAX_VERI_YASI_DAKIKA}dk)", kalite
    except Exception:
        kalite['son_mum_yasi_dk'] = None

    sayisal = df[gerekli_kolonlar].tail(1).copy()
    for kolon in gerekli_kolonlar:
        sayisal[kolon] = pd.to_numeric(sayisal[kolon], errors='coerce')
    sayisal.replace([np.inf, -np.inf], np.nan, inplace=True)
    if sayisal.isna().any(axis=None):
        return False, "Son mumda geçersiz feature değeri", kalite

    if float(sayisal['Hedef_Close'].iloc[0]) <= 0:
        return False, "Geçersiz fiyat", kalite
    if float(sayisal['ATR'].iloc[0]) <= 0:
        return False, "Geçersiz ATR", kalite

    schema_marker = df.attrs.get('feature_schema_version')
    if schema_marker is None and any(
        column in df.columns
        for column in (
            'Open_Interest_Available',
            'Funding_Rate_Available',
        )
    ):
        return False, "V6 feature schema provenance eksik", kalite
    try:
        feature_schema_version = int(
            5 if schema_marker is None else schema_marker
        )
    except (TypeError, ValueError):
        return False, "Geçersiz feature schema provenance", kalite
    if feature_schema_version == 6:
        coverage_contract_id = str(df.attrs.get('coverage_contract_id') or '')
        if coverage_contract_id != _V6_FEATURE_COVERAGE.contract_id:
            return False, "V6 coverage sözleşmesi eksik veya uyumsuz", kalite
        feature_quality = df.attrs.get('feature_quality')
        if not isinstance(feature_quality, dict):
            return False, "V6 feature quality raporu eksik", kalite
        try:
            for feature_name in ('Open_Interest', 'Funding_Rate'):
                _V6_FEATURE_COVERAGE.validate_frame_report(
                    df,
                    feature_name=feature_name,
                    report=feature_quality.get(feature_name),
                )
                mask_column = f'{feature_name}_Available'
                latest_mask = pd.to_numeric(
                    df[mask_column].tail(1),
                    errors='coerce',
                ).iloc[0]
                if not np.isfinite(latest_mask) or int(latest_mask) != 1:
                    raise ValueError(f"{mask_column} son mumda kapalı.")
        except (TypeError, ValueError) as exc:
            return False, f"V6 dış veri kalitesi başarısız: {exc}", kalite
        kalite['coverage_contract_id'] = coverage_contract_id
        kalite['feature_quality'] = feature_quality

    return True, "", kalite
