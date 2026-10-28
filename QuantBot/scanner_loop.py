"""
scanner_loop.py — Ana Tarama ve Sinyal Koordinasyon Motoru
Sürekli piyasayı tarar, uygun coinleri seçer, analiz motoruna gönderir
ve sinyal üretildiğinde emir motorunu (order_engine) tetikler.
"""
from datetime import datetime
import time
import re

import pandas as pd

from config import (
    MAX_PORTFOY_ISI_YUZDESI, MAX_ESANLI_POZISYON, SEKTORLER,
    TEK_DONGU_TANI_MODU, MIN_SCOUT_QUOTE_VOLUME_USDT, MAX_SCOUT_COIN_SAYISI,
    TANI_MAX_COIN_SAYISI, DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF,
    SHORT_ISLEM_AKTIF, REF, DEMO_MIN_MARGIN_YUZDESI,
    HEDGE_SNIPER_MODU_AKTIF, HEDGE_MAX_ESANLI_POZISYON,
    HEDGE_MAX_DONGU_ISLEM, HEDGE_MIN_RR, HEDGE_MIN_GUVEN,
    HEDGE_DEFANSIF_PNL_PENCERE, HEDGE_DEFANSIF_ZARAR_ESIK
)
from db_logger import gunluk_rapor_gonder
from signal_engine import analiz_motoru
from risk_manager import _sinyal_darbogaz_ozeti, SINYAL_RET_ISTATISTIKLERI
from demo_trade_journal import rapor_kaydet as demo_rapor_kaydet
from db_logger import demo_dispatch_ret_kaydet, demo_journal_status_guncelle
from tarayici import veri_getir_dortlu
from ai_core import BeyinMotoru
from live_model_compare import LiveModelComparator
from order_engine import islem_ac
from symbol_guard import resmi_zarar_karantinasi_tazele

try:
    from runtime_status import status_yaz
except:
    def status_yaz(a, event=None): pass

def portfoy_isi_hesapla(ctx, _BU_TUR_ACILAN):
    """Açık demo pozisyonların sayısına göre harcanan yaklaşık bütçeyi döndürür."""
    demo_poz_sayisi = 0
    detay_margin = 0.0
    detayli_pozisyon_sayisi = 0
    if 'pozisyonlar' in ctx['_DEMO_CACHE']:
        demo_pozisyonlar = [p for p in ctx['_DEMO_CACHE']['pozisyonlar'] if 'DEMO' in p[0].get('Hesap_Tipi', '')]
        demo_poz_sayisi = len(demo_pozisyonlar)
        aktif_detay = ctx.get('aktif_islemler_detay', {})
        for poz, _amt in demo_pozisyonlar:
            sembol = str(poz.get('symbol', '')).replace(':USDT', '')
            detay = aktif_detay.get(f"{sembol}_TESTNET") or aktif_detay.get(f"{sembol}_DEMO") or {}
            try:
                margin = float(detay.get('Kullanilan_Margin') or 0.0)
                if margin > 0:
                    detay_margin += margin
                    detayli_pozisyon_sayisi += 1
            except Exception:
                pass
    # Aynı tur içinde açılanları da saymalıyız (cache güncellemeden)
    fallback_margin = ctx['KASA_DURUM'].get('DEMO_KASA', 1000) * DEMO_MIN_MARGIN_YUZDESI
    eksik_detay_sayisi = max(0, demo_poz_sayisi - detayli_pozisyon_sayisi)
    return detay_margin + ((eksik_detay_sayisi + _BU_TUR_ACILAN) * fallback_margin)


def _sembol_kumesinde_var_mi(sembol, sembol_kumesi):
    if not sembol_kumesi:
        return True
    temiz = str(sembol or "").replace(":USDT", "")
    base = temiz.replace("/USDT", "").replace("USDT", "")
    adaylar = {
        temiz,
        temiz.replace("/", ""),
        f"{base}/USDT",
        f"{base}/USDT:USDT",
        f"{base}USDT",
    }
    return any(aday in sembol_kumesi for aday in adaylar)


def _sembol_normalize(sembol):
    temiz = str(sembol or "").replace(":USDT", "").strip().upper()
    if not temiz:
        return ""
    base = temiz.replace("/USDT", "").replace("USDT", "")
    return f"{base}/USDT" if base else temiz


def _standart_usdt_sembol_mu(sembol):
    return bool(re.match(r"^[A-Z0-9]{2,20}/USDT$", _sembol_normalize(sembol)))


def _floatla(deger, varsayilan=0.0):
    try:
        return float(deger)
    except Exception:
        return varsayilan


def _sinyal_siralama_puani(sinyal):
    guven = _floatla(sinyal.get('guven_skoru'))
    rr = _floatla(sinyal.get('rr'))
    hedge = _floatla(sinyal.get('hedge_skor'))
    return (hedge * 10.0) + (rr * 6.0) + guven


def _hedge_defansif_mi(ctx):
    pencere = ctx.get('SON_ISLEMLER_PNL_DEMO', [])[-HEDGE_DEFANSIF_PNL_PENCERE:]
    if len(pencere) < max(3, min(HEDGE_DEFANSIF_PNL_PENCERE, 3)):
        return False
    return sum(_floatla(p) for p in pencere) <= -HEDGE_DEFANSIF_ZARAR_ESIK


def _hedge_dispatch_kontrol(sinyal, ctx):
    if not HEDGE_SNIPER_MODU_AKTIF:
        return True, ""
    if _floatla(sinyal.get('rr')) < HEDGE_MIN_RR:
        return False, f"Hedge RR yetersiz ({_floatla(sinyal.get('rr')):.2f}<{HEDGE_MIN_RR:.1f})"
    if _floatla(sinyal.get('guven_skoru')) < HEDGE_MIN_GUVEN:
        return False, f"Hedge guven yetersiz ({_floatla(sinyal.get('guven_skoru')):.1f}<{HEDGE_MIN_GUVEN:.0f})"
    if _hedge_defansif_mi(ctx):
        if _floatla(sinyal.get('rr')) < HEDGE_MIN_RR + 0.30:
            return False, "Defansif mod: RR tamponu yetersiz"
        if _floatla(sinyal.get('guven_skoru')) < HEDGE_MIN_GUVEN + 3.0:
            return False, "Defansif mod: guven tamponu yetersiz"
        sinyal['margin_override_demo'] = max(
            DEMO_MIN_MARGIN_YUZDESI * 0.50,
            _floatla(sinyal.get('margin_override_demo'), DEMO_MIN_MARGIN_YUZDESI) * 0.65,
        )
        sinyal['hedge_defansif'] = True
    return True, ""


def surekli_tarama_ve_analiz(ctx):
    _BU_TUR_ACILAN = 0
    beyin = BeyinMotoru(n_estimators=200, max_depth=4, base_timeframe="4h")
    golge_beyin = BeyinMotoru(n_estimators=150, max_depth=3, model_prefix="shadow_150_3", base_timeframe="4h")
    v6_1h_beyin = BeyinMotoru(n_estimators=200, max_depth=3, model_prefix="v6_1h_200_3", base_timeframe="4h")
    model_karsilastirici = LiveModelComparator()
    
    while True:
        try:
            simdi = datetime.now()
            try:
                resmi_zarar_karantinasi_tazele(ctx)
            except Exception as sg_hata:
                print(f"[SYMBOL GUARD] tarama tazeleme atlandi: {sg_hata}")
            
            # --- OTONOM ARA RAPORLAR (12 Saatte Bir: 10:00 ve 22:00) ---
            if simdi.hour == 10 and simdi.date() != ctx['SON_RAPOR_ZAMANI_10']:
                ctx['SON_RAPOR_ZAMANI_10'] = simdi.date()
                print(f"📊 [{simdi.strftime('%H:%M:%S')}] Sabah 10:00 Ara Raporu Gönderiliyor...")
                gunluk_rapor_gonder(ctx['performans'], ctx['KASA_DURUM'], ctx['_DEMO_CACHE'], ctx['KARANTINA_LISTESI'])
            
            if simdi.hour == 22 and simdi.date() != ctx['SON_RAPOR_ZAMANI_22']:
                ctx['SON_RAPOR_ZAMANI_22'] = simdi.date()
                print(f"📊 [{simdi.strftime('%H:%M:%S')}] Akşam 22:00 Ara Raporu Gönderiliyor...")
                gunluk_rapor_gonder(ctx['performans'], ctx['KASA_DURUM'], ctx['_DEMO_CACHE'], ctx['KARANTINA_LISTESI'])

            print("\n" + "="*70)
            print(f"🚀 [{simdi.strftime('%H:%M:%S')}] AŞAMA 1: SCOUT (Hafif Tarayıcı) Başlıyor...")
            status_yaz({
                "faz": "SCOUT",
                "bot_durumu": "tarama başladı",
                "live_mod": ctx['LIVE_MOD_AKTIF'],
                "live_tetik": ctx['ALIM_SATIM_TETIGI_ACIK'],
                "ping_modu": ctx['PING_MODU'],
                "demo_profil": DEMO_CALISMA_PROFILI,
                "demo_live_shadow": DEMO_LIVE_SHADOW_AKTIF,
                "short_islem_aktif": SHORT_ISLEM_AKTIF,
                "hedge_sniper": {
                    "aktif": HEDGE_SNIPER_MODU_AKTIF,
                    "min_rr": HEDGE_MIN_RR,
                    "min_guven": HEDGE_MIN_GUVEN,
                    "max_pozisyon": HEDGE_MAX_ESANLI_POZISYON,
                    "max_dongu_islem": HEDGE_MAX_DONGU_ISLEM,
                },
            })
            
            # Public (non-testnet) API ile TÜM Binance Futures USDT paritelerini çek
            tikler = ctx['scout_borsa'].fetch_tickers()
            fiyatlar = {}
            for ticker_sembol, ticker_veri in tikler.items():
                fiyat = ticker_veri.get('last') or ticker_veri.get('close')
                if fiyat:
                    fiyatlar[ticker_sembol] = fiyat
            if model_karsilastirici.label_schema_version == 6:
                ab_bar_frames = {}
                for ab_sembol, ab_istek in (
                    model_karsilastirici.due_bar_requests().items()
                ):
                    try:
                        ab_bars = ctx['scout_borsa'].fetch_ohlcv(
                            ab_sembol,
                            timeframe=model_karsilastirici.base_timeframe,
                            since=ab_istek['since_ms'],
                            limit=ab_istek['limit'],
                        )
                        if not ab_bars:
                            continue
                        ab_frame = pd.DataFrame(
                            ab_bars,
                            columns=[
                                'timestamp',
                                'open',
                                'high',
                                'low',
                                'close',
                                'volume',
                            ],
                        )
                        ab_frame['timestamp'] = pd.to_datetime(
                            ab_frame['timestamp'],
                            unit='ms',
                        )
                        ab_frame.set_index('timestamp', inplace=True)
                        ab_bar_frames[ab_sembol] = ab_frame
                    except Exception as ab_bar_hata:
                        print(
                            f"[MODEL A/B V6] {ab_sembol} bar verisi "
                            f"alınamadı: {ab_bar_hata}"
                        )
                kapanan_ab = model_karsilastirici.settle_due_bars(
                    ab_bar_frames
                )
            else:
                kapanan_ab = model_karsilastirici.settle_due(fiyatlar)
            if kapanan_ab:
                if model_karsilastirici.label_schema_version == 6:
                    print(
                        f"[MODEL A/B V6] {kapanan_ab} ortak tahmin "
                        "kanonik ufuk sonucuyla kapandı."
                    )
                else:
                    print(
                        f"[MODEL A/B] {kapanan_ab} ortak tahmin "
                        "1 saatlik sonucuyla kapandi."
                    )
            status_yaz({"model_karsilastirma": model_karsilastirici.summary()})
            if not tikler:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ SCOUT: Ticker verisi boş geldi, döngü atlanıyor.")
                status_yaz({"faz": "SCOUT", "bot_durumu": "ticker verisi boş"}, event={"tip": "uyari", "mesaj": "SCOUT ticker verisi boş"})
                if TEK_DONGU_TANI_MODU:
                    status_yaz({
                        "faz": "TANI_TAMAMLANDI",
                        "bot_durumu": "tek döngü tanı tamamlandı, ticker verisi boş",
                        "sinyal_darbogaz": {
                            "aday_sayisi": 0,
                            "tahmin_sayisi": 0,
                            "ret_sayisi": 0,
                            "sinyal_sayisi": 0,
                            "sinyal_orani": 0.0,
                            "ret_kategorileri": {"veri": 1},
                            "en_cok_ret": {"SCOUT ticker verisi boş": 1},
                            "demo_profil": DEMO_CALISMA_PROFILI,
                            "short_islem_aktif": SHORT_ISLEM_AKTIF,
                        },
                    })
                    return
                time.sleep(30)
                continue
            
            # -------------------------------------------------------------
            # LOKAL DEMO BİLGİ GÜNCELLEMESİ
            # -------------------------------------------------------------
            acik_semboller = set()
            try:
                # Cache pozisyonlarini acik kabul et
                for p, a in ctx['_DEMO_CACHE'].get('pozisyonlar', []):
                    acik_semboller.add(_sembol_normalize(p.get('symbol')))
            except: pass
            try:
                for poz_key in ctx.get('onceki_pozisyonlar', {}):
                    acik_semboller.add(_sembol_normalize(str(poz_key).split('_')[0]))
            except: pass
            try:
                for detay_key, detay in ctx.get('aktif_islemler_detay', {}).items():
                    if isinstance(detay, dict):
                        acik_semboller.add(_sembol_normalize(str(detay_key).split('_')[0]))
            except: pass
            try:
                if ctx['LIVE_MOD_AKTIF'] and ctx['ALIM_SATIM_TETIGI_ACIK']:
                    pozisyonlar = ctx['borsa_live'].fetch_positions()
                    for p in pozisyonlar:
                        if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0:
                            acik_semboller.add(_sembol_normalize(p.get('symbol')))
            except: pass
            # -------------------------------------------------------------
            
            adaylar = []
            scout_ozeti = {
                "ticker_sayisi": len(tikler),
                "usdt_ticker_sayisi": 0,
                "spot_uygun_sayisi": 0,
                "testnet_uygun_sayisi": 0,
                "testnet_dislanan_sayisi": 0,
                "hacim_ustu_sayisi": 0,
                "hacim_esigi_usdt": int(MIN_SCOUT_QUOTE_VOLUME_USDT),
                "max_aday": int(MAX_SCOUT_COIN_SAYISI),
            }
            for sembol, veri in tikler.items():
                if '/USDT' not in sembol:
                    continue
                scout_ozeti["usdt_ticker_sayisi"] += 1
                hacim = float(veri.get('quoteVolume') or 0)
                degisim = abs(float(veri.get('percentage') or 0))
                temiz_sembol = sembol.replace(':USDT', '')
                if not _standart_usdt_sembol_mu(temiz_sembol):
                    continue
                if ctx['SPOT_SEMBOLLER'] and temiz_sembol not in ctx['SPOT_SEMBOLLER']:
                    continue
                scout_ozeti["spot_uygun_sayisi"] += 1
                if ctx.get('TESTNET_SEMBOLLER') and not _sembol_kumesinde_var_mi(temiz_sembol, ctx['TESTNET_SEMBOLLER']):
                    scout_ozeti["testnet_dislanan_sayisi"] += 1
                    continue
                scout_ozeti["testnet_uygun_sayisi"] += 1
                if hacim > MIN_SCOUT_QUOTE_VOLUME_USDT:
                    scout_ozeti["hacim_ustu_sayisi"] += 1
                    adaylar.append({'sembol': temiz_sembol, 'hacim': hacim, 'degisim': degisim})
            
            # Sıralama: Hacim ağırlıklı momentum (Likit ve gerçek trendi olan coinler öncelikli)
            adaylar.sort(key=lambda x: x['hacim'] * (1.0 + min(x['degisim'], 20.0) / 100.0), reverse=True)
            etkin_aday_limiti = min(MAX_SCOUT_COIN_SAYISI, TANI_MAX_COIN_SAYISI) if TEK_DONGU_TANI_MODU else MAX_SCOUT_COIN_SAYISI
            sicak_coinler = [x['sembol'] for x in adaylar[:etkin_aday_limiti]]
            scout_ozeti["aday_sayisi"] = len(sicak_coinler)
            scout_ozeti["tani_modu"] = TEK_DONGU_TANI_MODU
            scout_ozeti["etkin_aday_limiti"] = int(etkin_aday_limiti)
            
            # --- DURUM BİLGİSİ ---
            if ctx['CANLI_DEVRE_KESICI_AKTIF']:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛑 [LIVE: DEVRE KESİCİ AKTİF - Uyanış Bekleniyor]")
            elif not ctx['ALIM_SATIM_TETIGI_ACIK']:
                if ctx['PING_MODU']:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: PİNG MODU (Sadece FDUSD)]")
                else:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] 🛡️ [SANAL: AÇIK] | [CANLI: KAPALI (Güvenlik Kilidi)]")
            else:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔥 [LIVE: AKTİF] - GERÇEK PARA İŞLEM TETİĞİ ONAYLANDI!")
            
            # --- Portföy Isı Durumu ---
            mevcut_isi = portfoy_isi_hesapla(ctx, _BU_TUR_ACILAN)
            demo_kasa = ctx['KASA_DURUM'].get('DEMO_KASA', 1000)
            mevcut_isi_yuzde = (mevcut_isi / demo_kasa * 100) if demo_kasa > 0 else 0
            max_isi = demo_kasa * MAX_PORTFOY_ISI_YUZDESI
            kalan_kapasite = max(0, max_isi - mevcut_isi)
            print(f"🌡️  Portföy Isı: %{mevcut_isi_yuzde:.1f} / %{MAX_PORTFOY_ISI_YUZDESI*100:.0f} | Kullanılan: {mevcut_isi:.2f}$ | Kalan Kapasite: {kalan_kapasite:.2f}$")
            status_yaz({
                "faz": "SCOUT",
                "bot_durumu": "adaylar seçildi",
                "portfoy_isi_yuzde": round(mevcut_isi_yuzde, 2),
                "scout_ozeti": scout_ozeti,
                "son_dongu": {
                    "baslangic": simdi.strftime("%Y-%m-%d %H:%M:%S"),
                    "aday_sayisi": len(sicak_coinler),
                    "acik_pozisyon_sayisi": len(acik_semboller),
                }
            })
            
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🔍 Dinamik Tarayıcı: Piyasadan seçilen en sıcak coinler:")
            for i, coin in enumerate(sicak_coinler[:20], 1):
                aday = next((a for a in adaylar if a['sembol'] == coin), None)
                if aday:
                    print(f"  {i:2d}. {coin:<12} | Hacim: ${aday['hacim']/1e6:.0f}M | Değişim: %{aday['degisim']:.1f}")
            
            # ============================================================
            print(f"\n🎯 AŞAMA 2: SNIPER (Sinyal Toplama) Başlıyor... (Toplam {len(sicak_coinler)} coin)")
            status_yaz({"faz": "ANALİZ", "bot_durumu": f"{len(sicak_coinler)} coin analiz ediliyor"})
            sinyal_havuzu = []    # Tüm geçerli sinyaller (Filtreleri geçenler)
            tahmin_havuzu = []    # Tüm tahmin sonuçları (Debug Log için)
            
            for index, coin in enumerate(sicak_coinler, 1):
                if _sembol_normalize(coin) in acik_semboller:
                    continue
                
                # İlerleme Logu (Kullanıcı botun çalıştığını görsün)
                print(f"  [{index}/{len(sicak_coinler)}] {coin} analiz ediliyor...", flush=True)
                    
                rapor = analiz_motoru(
                    coin,
                    beyin,
                    ctx['KARANTINA_LISTESI'],
                    ctx['COIN_ZARAR_SAYACI'],
                    ctx['KARA_LISTE'],
                    golge_beyin=golge_beyin,
                    model_karsilastirici=model_karsilastirici,
                    v6_1h_beyin=v6_1h_beyin,
                )
                if rapor is not None:
                    tahmin_havuzu.append(rapor)
                    demo_rapor_kaydet(rapor)
                    if rapor.get('success'):
                        sinyal_havuzu.append(rapor)
                time.sleep(1)
            demo_journal_status_guncelle(force=True)
            sinyal_darbogaz = _sinyal_darbogaz_ozeti(tahmin_havuzu, sinyal_havuzu, len(sicak_coinler), scout_ozeti)
            status_yaz({
                "sinyal_darbogaz": sinyal_darbogaz,
                "scout_ozeti": scout_ozeti,
                "model_karsilastirma": model_karsilastirici.summary(),
            })
            if TEK_DONGU_TANI_MODU:
                print("\n🧪 [TANI MODU] Tek döngü tamamlandı; emir gönderimi bilinçli olarak atlandı.")
                status_yaz({
                    "faz": "TANI_TAMAMLANDI",
                    "bot_durumu": "tek döngü tanı tamamlandı, emir gönderilmedi",
                    "son_dongu": {
                        "baslangic": simdi.strftime("%Y-%m-%d %H:%M:%S"),
                        "bitis": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "aday_sayisi": len(sicak_coinler),
                        "tahmin_sayisi": len(tahmin_havuzu),
                        "sinyal_sayisi": len(sinyal_havuzu),
                        "gonderilen_sinyal_sayisi": 0,
                        "sinyal_orani": sinyal_darbogaz.get("sinyal_orani", 0.0),
                        "en_buyuk_darbogaz": next(iter(sinyal_darbogaz.get("ret_kategorileri", {}) or {}), ""),
                        "tani_modu": True,
                    }
                }, event={"tip": "tani", "mesaj": "tek döngü tanı tamamlandı"})
                return
            
            # ============================================================
            # 🔍 DEBUG LOG: En Yüksek Tahmin Skorları
            # Neden işlem açılmadığını anlamak için en iyi 3 skoru göster.
            # ============================================================
            if tahmin_havuzu:
                tahmin_havuzu.sort(key=lambda x: x['guven_skoru'], reverse=True)
                print(f"\n🔍 [DEBUG LOG] En Yüksek Sinyal Skorları (Top 3):")
                for i, t in enumerate(tahmin_havuzu[:3], 1):
                    esik = t.get('dinamik_esik', 55.0)
                    skor = t.get('guven_skoru', 0.0)
                    durum = "✅ EŞİK ÜSTÜ" if skor >= esik else "❌ YETERSİZ"
                    red_mesaji = f" | 🔴 SEBEP: {t.get('red_sebebi')}" if t.get('red_sebebi') else ""
                    kalite = t.get('veri_kalite', {}) or {}
                    kalite_mesaji = f" | Veri: {kalite.get('mum_sayisi', '?')} mum"
                    if kalite.get('son_mum_yasi_dk') is not None:
                        kalite_mesaji += f", {kalite.get('son_mum_yasi_dk')}dk"
                    top_features = ((t.get('model_aciklama') or {}).get('top_features') or [])[:3]
                    driver_mesaji = f" | Driver: {', '.join(f.get('ad', '?') for f in top_features)}" if top_features else ""
                    print(f"  {i}. {t['coin']}: %{skor:.1f} (Eşik: %{esik:.1f}) -> {durum}{red_mesaji}{kalite_mesaji}{driver_mesaji}")

                if SINYAL_RET_ISTATISTIKLERI:
                    ret_ozeti = sorted(SINYAL_RET_ISTATISTIKLERI.items(), key=lambda x: x[1], reverse=True)[:3]
                    print("  Ret Özeti: " + " | ".join(f"{neden}: {adet}" for neden, adet in ret_ozeti))
                darbogaz_kategorileri = sinyal_darbogaz.get("ret_kategorileri", {})
                if darbogaz_kategorileri:
                    ilkler = list(darbogaz_kategorileri.items())[:4]
                    print("  Darboğaz: " + " | ".join(f"{ad}: {adet}" for ad, adet in ilkler))
                
                if not sinyal_havuzu:
                    top_skor = tahmin_havuzu[0]['guven_skoru']
                    top_esik = tahmin_havuzu[0]['dinamik_esik']
                    if top_skor < top_esik:
                        print(f"📢 Sinyal yetersiz, en yüksek skor %{top_skor:.1f} (Gereken: %{top_esik:.1f})")
                    else:
                        print(f"📢 Skorlar yeterli ama diğer filtreler (Hacim, RSI, TSL vb.) engelledi.")
            else:
                print(f"📢 Veri alınamadığı için tahmin yapılamadı.")
            
            # ============================================================
            # 🏆 AŞAMA 3: RANK & SORT — Sinyal Sıralama (Signal Ranking)
            # XGBoost Güven Skoruna göre en yüksekten en düşüğe sırala.
            # ============================================================
            if sinyal_havuzu:
                sinyal_havuzu.sort(key=_sinyal_siralama_puani, reverse=True)
                
                print(f"\n" + "═"*70)
                print(f"🏆 [{datetime.now().strftime('%H:%M:%S')}] AŞAMA 3: RANK & EXECUTE — {len(sinyal_havuzu)} Sinyal Sıralandı!")
                print(f"{'SIRA':<5} | {'COİN':<12} | {'YÖN':<10} | {'GÜVEN':<8} | {'R/R':<6} | {'HEDGE':<6} | {'BÜTÇE':<8}")
                print("-" * 70)
                for i, s in enumerate(sinyal_havuzu, 1):
                    butce_yuzde = s.get('margin_override_demo', s.get('margin_override', DEMO_MIN_MARGIN_YUZDESI)) * 100
                    print(f"  {i:<3} | {s['coin']:<12} | {s['yon']:<10} | %{s['guven_skoru']:<6.1f} | {s['rr']:<5.2f} | {s.get('hedge_skor', 0):<6} | %{butce_yuzde:<6.1f}")
                print("═"*70)
                
                # ============================================================
                # 🏦 AŞAMA 4: AKILLI BÜTÇE DAĞITIMI (Smart Budget Dispatch)
                # Her emirden önce Portföy Isısını kontrol et.
                # Kasanın %80'ını aşarsa sıradaki işlemi iptal et.
                # ============================================================
                print(f"\n🏦 AŞAMA 4: Akıllı Bütçe Dağıtımı (Heat Limit: %{MAX_PORTFOY_ISI_YUZDESI*100:.0f})")
                status_yaz({"faz": "DISPATCH", "bot_durumu": f"{len(sinyal_havuzu)} sinyal dağıtılıyor"})
                gonderilen_sinyal_sayisi = 0
                _BU_TUR_ACILAN = 0  # Her tur başında sıfırla
                sektor_sayaci = {}  # Sektör Korelasyon Limiti takibi
                
                # Mevcut açık pozisyonların sektör dağılımını hesapla
                for poz_sembol in acik_semboller:
                    sektor = SEKTORLER.get(poz_sembol, SEKTORLER.get(poz_sembol.replace('/', ''), 'Diğer'))
                    sektor_sayaci[sektor] = sektor_sayaci.get(sektor, 0) + 1
                bu_tur_acilan_semboller = set()
                
                for sinyal in sinyal_havuzu:
                    etkin_max_pozisyon = min(MAX_ESANLI_POZISYON, HEDGE_MAX_ESANLI_POZISYON) if HEDGE_SNIPER_MODU_AKTIF else MAX_ESANLI_POZISYON
                    if HEDGE_SNIPER_MODU_AKTIF and gonderilen_sinyal_sayisi >= HEDGE_MAX_DONGU_ISLEM:
                        print(f"  🛑 Hedge döngü limiti: Bu tur {HEDGE_MAX_DONGU_ISLEM} işlem açıldı, kalan sinyaller bekletiliyor.")
                        break

                    sinyal_sembol_norm = _sembol_normalize(sinyal['coin'])
                    if sinyal_sembol_norm in acik_semboller or sinyal_sembol_norm in bu_tur_acilan_semboller:
                        print(f"  🟡 {sinyal['coin']} İPTAL: Bu sembolde zaten açık pozisyon var.")
                        demo_dispatch_ret_kaydet(sinyal, "Ayni sembolde acik pozisyon var")
                        continue

                    hedge_ok, hedge_neden = _hedge_dispatch_kontrol(sinyal, ctx)
                    if not hedge_ok:
                        print(f"  🛡️ {sinyal['coin']} HEDGE İPTAL: {hedge_neden}")
                        demo_dispatch_ret_kaydet(sinyal, hedge_neden)
                        continue

                    # --- SEKTÖR KORELASYON LİMİTİ (Max 4 pozisyon/sektör — Agresif Mod) ---
                    coin_sektor = SEKTORLER.get(sinyal['coin'], SEKTORLER.get(sinyal['coin'].replace('/', ''), 'Diğer'))
                    if sektor_sayaci.get(coin_sektor, 0) >= 4:
                        print(f"  🏷️ {sinyal['coin']} İPTAL: Sektör limiti! ({coin_sektor} sektöründe zaten 4 pozisyon var)")
                        demo_dispatch_ret_kaydet(sinyal, f"Sektor limiti: {coin_sektor}")
                        continue

                    # Anlık ısı kontrolü (her emirden önce yeniden hesapla)
                    mevcut_isi = portfoy_isi_hesapla(ctx, _BU_TUR_ACILAN)
                    demo_kasa = ctx['KASA_DURUM'].get('DEMO_KASA', 1000)
                    max_isi = demo_kasa * MAX_PORTFOY_ISI_YUZDESI
                    kalan_kapasite = max(0, max_isi - mevcut_isi)

                    tahmini_marjin = demo_kasa * sinyal.get('margin_override_demo', DEMO_MIN_MARGIN_YUZDESI)
                    
                    if tahmini_marjin > kalan_kapasite and sinyal.get('demo_ok'):
                        print(f"  🛑 {sinyal['coin']} DEMO İPTAL: Portföy Isı Sınırı! (Gereken: {tahmini_marjin:.2f}$ > Kalan: {kalan_kapasite:.2f}$)")
                        status_yaz({"son_risk_ret": {"sembol": sinyal['coin'], "neden": "Portföy ısı sınırı", "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}})
                        demo_dispatch_ret_kaydet(sinyal, "Portfoy isi siniri")
                        sinyal['demo_ok'] = False
                        if not sinyal.get('live_ok'):
                            continue # Hem demo kapandı, hem live yoksa iptal
                    
                    # İşlemi gönder
                    islem_mesaji = f"  ✅ {sinyal['coin']} ({coin_sektor}) -> Güven: %{sinyal['guven_skoru']:.1f}"
                    if sinyal.get('demo_ok'): islem_mesaji += f" | Demo Bütçe: {tahmini_marjin:.2f}$"
                    if sinyal.get('live_ok') and ctx.get('LIVE_MOD_AKTIF'): islem_mesaji += f" | Live ONAYLI"
                    print(islem_mesaji)
                    
                    # Sert tavan kontrolü (cache gecikmesinden bağımsız)
                    toplam_acik = len(ctx.get('onceki_pozisyonlar', {})) + gonderilen_sinyal_sayisi
                    if toplam_acik >= etkin_max_pozisyon:
                        print(f"  🛑 {sinyal['coin']} İPTAL: Sert tavan! (Zaten {toplam_acik} pozisyon açık, max {etkin_max_pozisyon})")
                        status_yaz({"son_risk_ret": {"sembol": sinyal['coin'], "neden": "Eşzamanlı pozisyon sert tavanı", "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}})
                        demo_dispatch_ret_kaydet(sinyal, "Eszamanli pozisyon sert tavani")
                        break
                    
                    islem_acildi = islem_ac(sinyal, ctx)
                    if islem_acildi:
                        gonderilen_sinyal_sayisi += 1
                        _BU_TUR_ACILAN += 1
                        bu_tur_acilan_semboller.add(sinyal_sembol_norm)
                        sektor_sayaci[coin_sektor] = sektor_sayaci.get(coin_sektor, 0) + 1
                    else:
                        demo_dispatch_ret_kaydet(sinyal, "Emir motoru islemi acmadi")
                    time.sleep(1)  # Rate limit koruması
                
                print(f"\n📊 Döngü Sonu: {len(sinyal_havuzu)} sinyal toplandı, {gonderilen_sinyal_sayisi} işlem açıldı.")
                status_yaz({
                    "faz": "BEKLEME",
                    "bot_durumu": "döngü tamamlandı",
                    "son_dongu": {
                        "baslangic": simdi.strftime("%Y-%m-%d %H:%M:%S"),
                        "bitis": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "aday_sayisi": len(sicak_coinler),
                        "tahmin_sayisi": len(tahmin_havuzu),
                        "sinyal_sayisi": len(sinyal_havuzu),
                        "gonderilen_sinyal_sayisi": gonderilen_sinyal_sayisi,
                        "sinyal_orani": sinyal_darbogaz.get("sinyal_orani", 0.0),
                        "en_buyuk_darbogaz": next(iter(sinyal_darbogaz.get("ret_kategorileri", {}) or {}), ""),
                    }
                })
            else:
                print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Filtrelerden geçen sinyal bulunamadı.")
                status_yaz({
                    "faz": "BEKLEME",
                    "bot_durumu": "filtrelerden geçen sinyal yok",
                    "son_dongu": {
                        "baslangic": simdi.strftime("%Y-%m-%d %H:%M:%S"),
                        "bitis": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "aday_sayisi": len(sicak_coinler),
                        "tahmin_sayisi": len(tahmin_havuzu),
                        "sinyal_sayisi": 0,
                        "gonderilen_sinyal_sayisi": 0,
                        "sinyal_orani": sinyal_darbogaz.get("sinyal_orani", 0.0),
                        "en_buyuk_darbogaz": next(iter(sinyal_darbogaz.get("ret_kategorileri", {}) or {}), ""),
                    }
                })
                
        except Exception as e:
            zaman = datetime.now().strftime('%H:%M:%S')
            print(f"[{zaman}] ⚠️ Tarayıcı Hatası: {e}")
            status_yaz({
                "faz": "HATA",
                "bot_durumu": "tarayıcı hatası",
                "son_hata": {
                    "modul": "surekli_tarama_ve_analiz",
                    "mesaj": str(e),
                    "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            }, event={"tip": "hata", "mesaj": f"tarayıcı: {e}"})
            if TEK_DONGU_TANI_MODU:
                return
            ctx['borsa_baglantisini_yenile']("Scout Hatası", ctx)
            time.sleep(10)
            
        print(f"\n⏳ [{datetime.now().strftime('%H:%M:%S')}] Tarama döngüsü tamamlandı, 180 saniye bekleniyor...")
        status_yaz({"faz": "BEKLEME", "bot_durumu": "sonraki tarama bekleniyor"})
        time.sleep(180)  # 15m mum kullandığımız için 3 dakika optimal (gereksiz API yükü azaltıldı)

def borsa_gerceklesen_pnl_getir(borsa_istemci, sembol, max_deneme=3):
    for _ in range(max_deneme):
        try:
            trades = borsa_istemci.fetch_my_trades(symbol=sembol, limit=10)
            simdi_ms = time.time() * 1000
            net_pnl = 0.0
            found = False
            for t in reversed(trades): 
                t_time = t.get('timestamp', 0)
                if (simdi_ms - t_time) < (120 * 60 * 1000): # Son 2 saat
                    rpnl = float(t.get('info', {}).get('realizedPnl', 0.0))
                    if rpnl != 0.0:
                        net_pnl += rpnl
                        found = True
            if found: return net_pnl
            time.sleep(1)
        except: time.sleep(1)
    return None

