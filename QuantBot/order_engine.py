"""
order_engine.py — Emir İletim ve İşlem Açma Motoru.
XGBoost analizini geçmiş coinleri borsaya (Live/Demo) gönderir,
TP/SL hesaplar, bütçe ve kaldıraç ayarlarını yaparak işlemi açar.
"""
from datetime import datetime
import time
import json
import re
import uuid
from enum import Enum

class OrderState(Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"

from config import (
    MAX_LIVE_MARGIN_YUZDESI, MAX_DEMO_MARGIN_YUZDESI,
    DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF, SHORT_ISLEM_AKTIF,
    DEMO_MIN_MARGIN_YUZDESI, DEMO_DEFANSIF_MARGIN_CARPANI,
    DEMO_EMIR_AKTIF,
)
from risk_manager import _gunluk_zarar_kapisi_acik_mi, _savunma_margin_carpani, _risk_kapisi_kontrolu, _planlanan_rr
from db_logger import _detay_kaydet, demo_journal_status_guncelle
from order_sync import cancel_symbol_orders, ensure_single_hard_stop

try:
    from runtime_status import status_yaz
except Exception:
    def status_yaz(guncelleme=None, event=None): return {}

try:
    from demo_trade_journal import acilis_kaydet as demo_acilis_kaydet
except Exception:
    def demo_acilis_kaydet(**detay): return {}


def _borsa_sembol_destekli_mi(borsa_istemci, sembol):
    try:
        if not getattr(borsa_istemci, "markets", None):
            borsa_istemci.load_markets()
        temiz = str(sembol or "").replace(":USDT", "")
        base = temiz.replace("/USDT", "").replace("USDT", "")
        adaylar = {
            temiz,
            temiz.replace("/", ""),
            f"{base}/USDT",
            f"{base}/USDT:USDT",
            f"{base}USDT",
        }
        marketler = set(getattr(borsa_istemci, "markets", {}) or {})
        semboller = set(getattr(borsa_istemci, "symbols", []) or [])
        return any(aday in marketler or aday in semboller for aday in adaylar)
    except Exception:
        return False


def _gecersiz_sembol_kara_listeye_al(ctx, sembol, hata_str):
    hata = str(hata_str)
    if "-1121" not in hata and "invalid symbol" not in hata.lower():
        return False
    temiz = str(sembol or "").replace(":USDT", "").strip().upper()
    base = temiz.replace("/USDT", "").replace("USDT", "")
    kara_liste = ctx.get('KARA_LISTE')
    if isinstance(kara_liste, set):
        for aday in (temiz, temiz.replace("/", ""), f"{base}/USDT", f"{base}USDT"):
            if aday:
                kara_liste.add(aday)
    try:
        ctx['COOLDOWN_DICT'][sembol] = datetime.now()
    except Exception:
        pass
    print(f"[SEMBOL KORUMA] {sembol} gecersiz/reddedilen sembol; bu oturumda tekrar denenmeyecek.")
    status_yaz(event={"tip": "sembol_koruma", "mesaj": f"{sembol} invalid symbol nedeniyle kara listeye alindi"})
    return True


def _piyasa_referans_fiyati(borsa_istemci, sembol, varsayilan):
    try:
        ticker = borsa_istemci.fetch_ticker(sembol)
        info = ticker.get("info", {}) if isinstance(ticker, dict) else {}
        for alan in ("markPrice", "lastPrice", "indexPrice"):
            deger = info.get(alan)
            if deger:
                return float(deger)
        for alan in ("last", "close", "bid", "ask"):
            deger = ticker.get(alan)
            if deger:
                return float(deger)
    except Exception:
        pass
    try:
        return float(varsayilan)
    except Exception:
        return 0.0


def _stop_on_kontrol(pozisyon_yonu, sembol, stop_fiyat, referans_fiyat, buffer_yuzde=0.0015):
    try:
        stop_fiyat = float(stop_fiyat)
        referans_fiyat = float(referans_fiyat)
    except Exception:
        return False
    if stop_fiyat <= 0 or referans_fiyat <= 0:
        return False
    if pozisyon_yonu == "LONG" and stop_fiyat >= referans_fiyat * (1 - buffer_yuzde):
        print(f"🛑 [ZIRH ÖN KONTROL] {sembol} LONG iptal: SL anlık fiyata çok yakın/üstte. SL={stop_fiyat}, Piyasa={referans_fiyat}")
        return False
    if pozisyon_yonu == "SHORT" and stop_fiyat <= referans_fiyat * (1 + buffer_yuzde):
        print(f"🛑 [ZIRH ÖN KONTROL] {sembol} SHORT iptal: SL anlık fiyata çok yakın/altta. SL={stop_fiyat}, Piyasa={referans_fiyat}")
        return False
    return True


def _binance_limit_siniri_duzelt(hata_str, limit_fiyat):
    try:
        eslesme = re.search(r"can't be (lower|higher) than ([0-9]+(?:\.[0-9]+)?)", str(hata_str))
        if not eslesme:
            return None
        yon, sinir = eslesme.group(1), float(eslesme.group(2))
        if yon == "lower":
            return max(float(limit_fiyat), sinir)
        return min(float(limit_fiyat), sinir)
    except Exception:
        return None


def _koruma_kapatma_emri_gonder(borsa_istemci, sembol, side, miktar):
    try:
        return borsa_istemci.create_order(symbol=sembol, type='MARKET', side=side, amount=miktar, params={'reduceOnly': True})
    except Exception as market_hata:
        hata_str = str(market_hata)
        if "-4131" not in hata_str and "PERCENT_PRICE" not in hata_str:
            raise
        referans = _piyasa_referans_fiyati(borsa_istemci, sembol, 0.0)
        if referans <= 0:
            raise
        limit_fiyat = referans * (0.995 if side == 'sell' else 1.005)
        try:
            limit_fiyat = float(borsa_istemci.price_to_precision(sembol, limit_fiyat))
        except Exception:
            pass
        print(f"🧯 [KORUMA] Market kapatma fiyat filtresine takıldı; agresif LIMIT/IOC deneniyor: {limit_fiyat}")
        params = {'reduceOnly': True, 'timeInForce': 'IOC'}
        try:
            return borsa_istemci.create_order(
                symbol=sembol, type='LIMIT', side=side, amount=miktar, price=limit_fiyat,
                params=params
            )
        except Exception as limit_hata:
            duzeltilmis_fiyat = _binance_limit_siniri_duzelt(str(limit_hata), limit_fiyat)
            if duzeltilmis_fiyat is None:
                raise
            try:
                duzeltilmis_fiyat = float(borsa_istemci.price_to_precision(sembol, duzeltilmis_fiyat))
            except Exception:
                pass
            print(f"🧯 [KORUMA] Binance fiyat sınırı uygulandı; LIMIT/IOC tekrar deneniyor: {duzeltilmis_fiyat}")
            return borsa_istemci.create_order(
                symbol=sembol, type='LIMIT', side=side, amount=miktar, price=duzeltilmis_fiyat,
                params=params
            )


def _fill_sapma_yuzde(beklenen_fiyat, gerceklesen_fiyat):
    try:
        beklenen_fiyat = float(beklenen_fiyat)
        gerceklesen_fiyat = float(gerceklesen_fiyat)
        if beklenen_fiyat <= 0 or gerceklesen_fiyat <= 0:
            return 0.0
        return abs(gerceklesen_fiyat - beklenen_fiyat) / beklenen_fiyat * 100.0
    except Exception:
        return 0.0


def _hedefleri_fill_fiyatina_tasi(pozisyon_yonu, beklenen_giris, gercek_giris, tp, sl):
    try:
        beklenen_giris = float(beklenen_giris)
        gercek_giris = float(gercek_giris)
        tp = float(tp)
        sl = float(sl)
        stop_mesafe = abs(beklenen_giris - sl)
        tp_mesafe = abs(tp - beklenen_giris)
        if beklenen_giris <= 0 or gercek_giris <= 0 or stop_mesafe <= 0 or tp_mesafe <= 0:
            return tp, sl
        if pozisyon_yonu == "LONG":
            return gercek_giris + tp_mesafe, gercek_giris - stop_mesafe
        return gercek_giris - tp_mesafe, gercek_giris + stop_mesafe
    except Exception:
        return tp, sl


def islem_ac(sinyal, ctx):
    """
    Sinyali alır ve LIVE veya DEMO hesapta işlem açar.
    ctx: İçinde borsa bağlantıları ve global durum değişkenlerini taşıyan sözlük.
    """
    sembol = sinyal['coin']
    yon = sinyal['yon']
    anlik_fiyat = sinyal['fiyat']
    hesaplanan_tp = sinyal['tp']
    hesaplanan_sl = sinyal['sl']
    ai_guven_skoru = sinyal['guven_skoru']
    live_ok = sinyal.get('live_ok', False)
    demo_ok = sinyal.get('demo_ok', False)
    acilan_hesap_var = False

    if demo_ok and not DEMO_EMIR_AKTIF:
        demo_ok = False
        print(f"[DEMO GOLGE KILIDI] {sembol} sinyali ölçüldü; emir gönderimi kapalı.")
        status_yaz({
            "demo_emir_aktif": False,
            "son_risk_ret": {
                "sembol": sembol,
                "neden": "Demo gölge kilidi",
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        })

    sync_state = ctx.get('ORDER_SYNC_STATE')
    if demo_ok and isinstance(sync_state, dict) and not sync_state.get('ready', False):
        demo_ok = False
        neden = sync_state.get('last_error') or 'pozisyon/emir senkronizasyonu hazir degil'
        print(f"[EMIR SYNC KILIDI] {sembol} DEMO girisi engellendi: {neden}")
        status_yaz({
            "son_risk_ret": {
                "sembol": sembol,
                "neden": "Emir senkronizasyon kilidi",
                "detay": neden,
                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        })
    
    # --- COOLDOWN KONTROLÜ (Akıllı Bekleme Sistemi) ---
    simdi = datetime.now()
    if sembol in ctx['COOLDOWN_DICT']:
        gecen = (simdi - ctx['COOLDOWN_DICT'][sembol]).total_seconds()
        # 4H Swing modunda aynı coinde inatlaşmayı/overtrading'i önlemek için 18-24 saatlik bekleme süresi
        bekleme_suresi = 86400 if ctx.get('DEMO_ARDISIK_ZARAR', 0) >= 1 else 64800
        if gecen < bekleme_suresi:
            return False
        else:
            del ctx['COOLDOWN_DICT'][sembol]

    # --- KANAL GÖNDERİMİ (BIFURCATION) ---
    if demo_ok:
        try:
            if not _gunluk_zarar_kapisi_acik_mi("DEMO", sembol, ctx['KASA_DURUM']):
                demo_ok = False
            if demo_ok:
                if hasattr(ctx['borsa'], 'apiKey') and ctx['borsa'].apiKey:
                    demo_acildi = _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, ctx['borsa'], "TESTNET", False, sinyal.get('margin_override_demo', DEMO_MIN_MARGIN_YUZDESI), ai_guven_skoru, ctx, sinyal)
                else:
                    # Kağıt Üstü Gölge Demo İşlem Kaydı (Testnet API Key Olmadan Canlı İzleme)
                    toplam_kasa = float(ctx.get('KASA_DURUM', {}).get('DEMO_KASA', 1000.0))
                    
                    # Dinamik Risk Paritesi Boyutlandırması (Hedef Sabit Dolar Riski: ~%3.0 Kasa)
                    hedef_risk_usdt = toplam_kasa * 0.03
                    sl_mesafesi_pct = abs(anlik_fiyat - hesaplanan_sl) / anlik_fiyat if (anlik_fiyat > 0 and hesaplanan_sl > 0) else 0.035
                    sl_mesafesi_pct = max(0.02, min(0.08, sl_mesafesi_pct))
                    
                    kaldirac = 4.0
                    risk_parity_margin = (hedef_risk_usdt / sl_mesafesi_pct) / kaldirac
                    kullanilacak_margin = max(120.0, min(225.0, risk_parity_margin))
                    
                    miktar = (kullanilacak_margin * kaldirac) / anlik_fiyat if anlik_fiyat > 0 else 0.0
                    rejim_etiketi = sinyal.get("piyasa_kalite", {}).get("rejim", "BILINMIYOR")
                    demo_acilis_kaydet(
                        hesap_tipi="DEMO",
                        sembol=sembol,
                        yon=yon,
                        giris=anlik_fiyat,
                        miktar=miktar,
                        margin=kullanilacak_margin,
                        kaldirac=kaldirac,
                        ai_skoru=ai_guven_skoru,
                        tp=hesaplanan_tp,
                        sl=hesaplanan_sl,
                        rr=sinyal.get('rr', 0.0),
                        risk_metni="Shadow Demo Paper",
                        demo_profil=DEMO_CALISMA_PROFILI,
                        demo_live_shadow=DEMO_LIVE_SHADOW_AKTIF,
                        short_islem_aktif=SHORT_ISLEM_AKTIF,
                        rejim=rejim_etiketi,
                    )
                    demo_acildi = True
                if demo_acildi:
                    acilan_hesap_var = True
                    print(f"POZİSYON [DEMO-GÖLGE]: {sembol} | YÖN: {'LONG' if 'YÜKSELİŞ' in yon else 'SHORT'} | GİRİŞ: {anlik_fiyat:.4f} | TP: {hesaplanan_tp:.4f} | SL: {hesaplanan_sl:.4f}")
                    status_yaz({
                        "son_islem": {
                            "hesap": "DEMO",
                            "sembol": sembol,
                            "yon": yon,
                            "fiyat": anlik_fiyat,
                            "guven": ai_guven_skoru,
                            "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    }, event={"tip": "islem", "mesaj": f"DEMO {sembol} {yon}"})
        except Exception as e:
            print(f"[!] DEMO Emir Hatası ({sembol}): {e}")

    if live_ok and ctx['LIVE_MOD_AKTIF']:
        if ctx['LIVE_API_KEY'] and ctx['LIVE_SECRET']:
            if ctx['ALIM_SATIM_TETIGI_ACIK'] or (ctx['PING_MODU'] and sembol == 'FDUSD/USDT'):
                if not _gunluk_zarar_kapisi_acik_mi("LIVE", sembol, ctx['KASA_DURUM']):
                    return acilan_hesap_var
                if not ctx['ALIM_SATIM_TETIGI_ACIK'] and ctx['PING_MODU']:
                    print(f"[{sembol}] ⚠️ PING MODU ONAYI: Mikro LIVE test işlemine izin veriliyor...")
                try:
                    with ctx['LIVE_ISLEM_KILIDI']:
                        live_acildi = _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, ctx['borsa_live'], "LIVE", True, sinyal.get('margin_override_live', 0.1), ai_guven_skoru, ctx, sinyal)
                    if live_acildi:
                        acilan_hesap_var = True
                        print(f"POZİSYON [LIVE-GERÇEK]: {sembol} | YÖN: {'LONG' if 'YÜKSELİŞ' in yon else 'SHORT'} | GİRİŞ: {anlik_fiyat}")
                        status_yaz({
                            "son_islem": {
                                "hesap": "LIVE",
                                "sembol": sembol,
                                "yon": yon,
                                "fiyat": anlik_fiyat,
                                "guven": ai_guven_skoru,
                                "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            }
                        }, event={"tip": "islem", "mesaj": f"LIVE {sembol} {yon}"})
                except Exception as e:
                    hata_mesaji = str(e)
                    if "-2010" in hata_mesaji or "insufficient balance" in hata_mesaji.lower():
                        print(f"[LIVE-UYARI] Bakiye yetersiz, LIVE işlem iptal.")
                    else:
                        print(f"[!] LIVE İzole Hata ({sembol}): {e}")
            else:
               pass # Canlı işlem tetiği kapalı!
    return acilan_hesap_var


def _islem_ac_core(yon, sembol, anlik_fiyat, hesaplanan_tp, hesaplanan_sl, borsa_istemci, hesap_tipi, is_live, margin_override, ai_guven_skoru, ctx, sinyal_detay=None):
    if not hasattr(borsa_istemci, 'apiKey') or not borsa_istemci.apiKey:
        return False

    try:
        if not _borsa_sembol_destekli_mi(borsa_istemci, sembol):
            print(f"🛑 [{hesap_tipi}] {sembol} iptal: Bu sembol bu borsa ortamında desteklenmiyor.")
            return False

        sinyal_detay = sinyal_detay or {}
        model_kalite_detay = sinyal_detay.get('model_kalite') or {}
        model_walk_forward_skoru = model_kalite_detay.get('walk_forward_skoru')
        min_model_walk_forward_skoru = sinyal_detay.get('min_model_walk_forward_skoru')
        model_kalite_bolgesi = sinyal_detay.get('model_kalite_bolgesi')
        model_kalite_sari = bool(sinyal_detay.get('model_kalite_sari'))
        model_kalite_sari_margin_carpani = sinyal_detay.get('model_kalite_sari_margin_carpani')
        rejim_etiketi = sinyal_detay.get("piyasa_kalite", {}).get("rejim", "BILINMIYOR")

        # ━━━━━━ AI GÜVEN SKORU A+ KALİTE KALKANI KALDIRILDI ━━━━━━
        # Güven skoru ve eşik kontrolleri (dinamik_esik, vb) Signal Engine'de yapılır.
        # Sinyal motoru demo_ok = True dediyse, Emir Motoru emri basmalıdır.
        
        if not _gunluk_zarar_kapisi_acik_mi("LIVE" if is_live else "DEMO", sembol, ctx['KASA_DURUM']):
            return False

        with ctx['LIVE_ISLEM_KILIDI']:
            borsa_istemci.load_markets()
            pozisyonlar = borsa_istemci.fetch_positions()
            acik_sayisi = sum(1 for p in pozisyonlar if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0)
            
            if is_live and acik_sayisi >= 1:
                print(f"⚠️ [LIVE-GÜVENLİK] İptal: LIVE modda aynı anda KESİNLİKLE SADECE 1 İŞLEM açık kalabilir!")
                return False
        
        try:
            bakiye_bilgisi = borsa_istemci.fetch_balance()
            toplam_kasa_raw = float(bakiye_bilgisi.get('USDT', {}).get('total', 1000.0))
            if not is_live:
                try:
                    with open('ayar.json', 'r') as _f:
                        _demo_offset = float(json.load(_f).get('demo_bakiye_offset', 0.0))
                except:
                    _demo_offset = 0.0
                toplam_kasa = max(10.0, toplam_kasa_raw - _demo_offset)
            else:
                toplam_kasa = toplam_kasa_raw
        except Exception as e:
            hesap_etiketi = "LIVE" if is_live else "DEMO"
            print(f"🛑 [{hesap_etiketi}-GÜVENLİK] Bakiye okunamadı, emir iptal: {e}")
            return False
            
        if is_live:
            margin_yuzdesi = margin_override if margin_override is not None else MAX_LIVE_MARGIN_YUZDESI
            margin_yuzdesi = max(0.0, min(float(margin_yuzdesi), MAX_LIVE_MARGIN_YUZDESI))
            kullanilacak_margin = toplam_kasa * margin_yuzdesi
            kaldirac_orani = 5 
            risk_metni = f"LIVE Bütçe: {kullanilacak_margin:.2f}$ (Max %{MAX_LIVE_MARGIN_YUZDESI*100:.0f}, Hedef: 5x)"
        else:
            # ━━━━━━ DEMO: DİNAMİK MARJİN (Kelly / Signal Engine) ━━━━━━
            kaldirac_orani = 4
            override_margin_pct = sinyal_detay.get('margin_override_demo')
            if override_margin_pct is not None:
                margin_yuzdesi = override_margin_pct
            else:
                margin_yuzdesi = DEMO_MIN_MARGIN_YUZDESI

            kullanilacak_margin = toplam_kasa * margin_yuzdesi
            sl_pct = abs(anlik_fiyat - hesaplanan_sl) / anlik_fiyat if (anlik_fiyat > 0 and hesaplanan_sl > 0) else 0.035
            hedef_risk = (kullanilacak_margin * kaldirac_orani) * sl_pct
            risk_metni = f"Kelly Margin: ${kullanilacak_margin:.0f} (SL%{sl_pct*100:.1f}, Risk ${hedef_risk:.0f})"
            
        aktif_ardisik = ctx['DEMO_ARDISIK_ZARAR'] if not is_live else ctx['LIVE_ARDISIK_ZARAR']
        savunma_carpani = _savunma_margin_carpani(aktif_ardisik, "LIVE" if is_live else "DEMO")
        if savunma_carpani < 1.0:
            kullanilacak_margin *= savunma_carpani
            risk_metni += f" (SAVUNMA x{savunma_carpani:.0%} | {aktif_ardisik} ardisik zarar)"
            print(f"\n[SAVUNMA MODU] {aktif_ardisik} ardisik zarar -> margin x{savunma_carpani:.0%} dusuruldu.")
            
        pnl_listesi = ctx['SON_ISLEMLER_PNL_DEMO'] if not is_live else ctx['SON_ISLEMLER_PNL_LIVE']
        if pnl_listesi and sum(pnl_listesi) < 0 and toplam_kasa > 100:
            kullanilacak_margin *= DEMO_DEFANSIF_MARGIN_CARPANI if not is_live else 0.50
            risk_metni += f" (DEFANSIF: Son islemler negatif x{(DEMO_DEFANSIF_MARGIN_CARPANI if not is_live else 0.50):.0%})"
            
        try:
            borsa_istemci.set_leverage(kaldirac_orani, sembol)
            kaldirac = kaldirac_orani
        except Exception as e:
            if _gecersiz_sembol_kara_listeye_al(ctx, sembol, e):
                return False
            print(f"⚠️ [DİKKAT] Binance API Kaldıraç Ayarını Reddetti! (Hata: {e})")
            kaldirac = kaldirac_orani 

        risk_sonuc = _risk_kapisi_kontrolu(yon, sembol, anlik_fiyat, hesaplanan_sl, toplam_kasa, kullanilacak_margin, kaldirac, borsa_istemci, risk_metni)
        if not risk_sonuc:
            return False

        kullanilacak_margin = risk_sonuc['kullanilacak_margin']
        islem_hacmi = risk_sonuc['islem_hacmi']
        miktar = risk_sonuc['miktar']
        risk_metni = risk_sonuc['risk_metni']
        tahmini_zarar = risk_sonuc['tahmini_zarar']
        referans_fiyat = _piyasa_referans_fiyati(borsa_istemci, sembol, anlik_fiyat)
        if "YÜKSELİŞ" in yon and not _stop_on_kontrol("LONG", sembol, hesaplanan_sl, referans_fiyat):
            return False
        if "DÜŞÜŞ" in yon and not _stop_on_kontrol("SHORT", sembol, hesaplanan_sl, referans_fiyat):
            return False
        
        zaman = datetime.now().strftime('%H:%M:%S')
        print(f"[{zaman}] İşlem Büyüklüğü: {kullanilacak_margin:.2f} USDT | Kaldıraç: {kaldirac}x | Tahmini SL Riski: {tahmini_zarar:.2f}$ | Risk: {risk_metni}")

        if "YÜKSELİŞ" in yon:
            market_emri_acildi = False
            acilis_ms = int(time.time() * 1000)
            client_order_id = uuid.uuid4().hex
            print(f"[{sembol}] Emir durumu: {OrderState.CREATED.value} - ID: {client_order_id}")
            params = {'newClientOrderId': client_order_id}
            try:
                max_deneme = 3
                emir = None
                for deneme in range(max_deneme):
                    try:
                        print(f"[{sembol}] Emir durumu: {OrderState.SUBMITTED.value} (Deneme {deneme+1}/{max_deneme})")
                        emir = borsa_istemci.create_market_buy_order(sembol, miktar, params)
                        market_emri_acildi = True
                        print(f"[{sembol}] Emir durumu: {OrderState.FILLED.value}")
                        break
                    except Exception as e:
                        if deneme == max_deneme - 1:
                            print(f"[{sembol}] Emir durumu: {OrderState.REJECTED.value} - Hata: {e}")
                            raise
                        print(f"[{sembol}] Emir hatası: {e}. Tekrar deneniyor...")
                        time.sleep(1)
                gerceklesen_fiyat = emir.get('average') or emir.get('price') or anlik_fiyat
                time.sleep(0.5) 
                sapma_yuzde = _fill_sapma_yuzde(anlik_fiyat, gerceklesen_fiyat)
                if sapma_yuzde > 1.0:
                    print(f"[FILL SAPMASI] {sembol} LONG iptal: sinyal={anlik_fiyat}, fill={gerceklesen_fiyat}, sapma=%{sapma_yuzde:.2f}")
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'sell', miktar)
                        print(f"[FILL SAPMASI] {sembol} LONG guvenlik icin kapatildi.")
                    except Exception as kapatma_hata:
                        print(f"[FILL SAPMASI] {sembol} LONG kapatma basarisiz: {kapatma_hata}")
                    return False

                hesaplanan_tp, hesaplanan_sl = _hedefleri_fill_fiyatina_tasi(
                    "LONG", anlik_fiyat, gerceklesen_fiyat, hesaplanan_tp, hesaplanan_sl
                )
                if not _stop_on_kontrol("LONG", sembol, hesaplanan_sl, gerceklesen_fiyat):
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'sell', miktar)
                        print(f"[FILL KORUMA] {sembol} LONG stop gecersiz oldugu icin kapatildi.")
                    except Exception as kapatma_hata:
                        print(f"[FILL KORUMA] {sembol} LONG kapatma basarisiz: {kapatma_hata}")
                    return False

                planlanan_rr = _planlanan_rr("LONG", gerceklesen_fiyat, hesaplanan_tp, hesaplanan_sl)
                
                ctx['aktif_islemler_detay'][f"{sembol}_{hesap_tipi}"] = {
                    'Giris_Fiyati': gerceklesen_fiyat, 'Islem_Yonu': 'LONG', 'Miktar': miktar,
                    'AI_Guven_Skoru': ai_guven_skoru, 'Hesap_Tipi': hesap_tipi,
                    'TP_Fiyat': hesaplanan_tp, 'SL_Fiyat': hesaplanan_sl,
                    'Planlanan_RR': planlanan_rr, 'Risk_Metni': risk_metni,
                    'Tahmini_Zarar': tahmini_zarar, 'Kullanilan_Margin': kullanilacak_margin,
                    'Kaldirac': kaldirac, 'Demo_Profil': DEMO_CALISMA_PROFILI,
                    'Demo_Live_Shadow': DEMO_LIVE_SHADOW_AKTIF,
                    'Short_Islem_Aktif': SHORT_ISLEM_AKTIF,
                    'Model_Walk_Forward_Skoru': model_walk_forward_skoru,
                    'Min_Model_Walk_Forward_Skoru': min_model_walk_forward_skoru,
                    'Model_Kalite_Bolgesi': model_kalite_bolgesi,
                    'Model_Kalite_Sari': model_kalite_sari,
                    'Model_Kalite_Sari_Margin_Carpani': model_kalite_sari_margin_carpani,
                    'Acilis_Zamani': datetime.now(), 'Acilis_Ms': acilis_ms,
                    'Scale_Out_Yapildi': False
                }
                _detay_kaydet(ctx['aktif_islemler_detay']) 
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                sabit_stop_ok, stop_detay = ensure_single_hard_stop(
                    borsa_istemci, sembol, "LONG", miktar, sl_fiyat
                )
                if not sabit_stop_ok:
                    raise RuntimeError(
                        f"Tek sabit stop dogrulanamadi: {stop_detay.get('error', 'bilinmeyen hata')}"
                    )
                print(f"[EMIR SYNC] {sembol} LONG | Tek tam-miktar stop aktif: {sl_fiyat}")
                demo_acilis_kaydet(
                    hesap_tipi=hesap_tipi, sembol=sembol, yon="LONG",
                    giris=gerceklesen_fiyat, miktar=miktar, margin=kullanilacak_margin,
                    kaldirac=kaldirac, ai_skoru=ai_guven_skoru, tp=hesaplanan_tp,
                    sl=hesaplanan_sl, rr=planlanan_rr, risk_metni=risk_metni,
                    tahmini_zarar=tahmini_zarar, demo_profil=DEMO_CALISMA_PROFILI,
                    demo_live_shadow=DEMO_LIVE_SHADOW_AKTIF, short_islem_aktif=SHORT_ISLEM_AKTIF,
                    model_walk_forward_skoru=model_walk_forward_skoru,
                    min_model_walk_forward_skoru=min_model_walk_forward_skoru,
                    model_kalite_bolgesi=model_kalite_bolgesi, model_kalite_sari=model_kalite_sari,
                    model_kalite_sari_margin_carpani=model_kalite_sari_margin_carpani,
                    rejim=rejim_etiketi,
                )
                demo_journal_status_guncelle()
                return True
                tp_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_tp))
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(gerceklesen_fiyat - sl_fiyat)
                
                scale_out_fark = atr_mesafe * 1.2
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat + scale_out_fark))
                yari_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.3))
                
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                callback_rate = round(max(2.0, min(5.0, volatilite_yuzde * 2.5)), 1)
                activation_price = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat + atr_mesafe))
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                sabit_stop_ok = False
                for deneme in range(max_deneme):
                    try:
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='STOP_MARKET', side='sell', amount=miktar,
                                params={'stopPrice': sl_fiyat, 'reduceOnly': True}
                            )
                            sabit_stop_ok = True
                            print(f"✅ [ÇİFT KALKAN] {sembol} | Sabit Stop Aktif: {sl_fiyat}")
                        except Exception as sl_err:
                            print(f"⚠️ [ZIRH UYARISI] Sabit Stop Kurulamadı: {sl_err}")
                            raise

                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TAKE_PROFIT_MARKET', side='sell', amount=yari_miktar,
                                params={'stopPrice': scale_out_fiyat, 'reduceOnly': True}
                            )
                            print(f"💰 [SCALE-OUT] {sembol} | %30 Kâr Alım Aktif (1.2R): {scale_out_fiyat}")
                        except Exception as tp_err:
                            if "-4130" not in str(tp_err): print(f"⚠️ [ZIRH UYARISI] Scale-Out Kurulamadı: {tp_err}")

                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TRAILING_STOP_MARKET', side='sell', amount=miktar,
                                params={'callbackRate': callback_rate, 'activationPrice': activation_price, 'reduceOnly': True}
                            )
                            print(f"🎯 [SUNUCU GÜVENLİĞİ] {sembol} | Trailing Stop Aktif: %{callback_rate:.2f} | Aktivasyon: {activation_price}")
                        except Exception as tsl_error:
                            if "-4130" not in str(tsl_error): print(f"⚠️ [ZIRH UYARISI] Trailing Stop başarısız: {tsl_error}")

                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: LONG | GİRİŞ: {gerceklesen_fiyat} | ZIRH: SABİT STOP ONAYLI")
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        elif deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Ana Zırh Çöktü: {hata_msg}")
                            raise
                if not sabit_stop_ok:
                    raise RuntimeError("Sabit stop emri doğrulanamadı")
                demo_acilis_kaydet(
                    hesap_tipi=hesap_tipi, sembol=sembol, yon="LONG",
                    giris=gerceklesen_fiyat, miktar=miktar, margin=kullanilacak_margin,
                    kaldirac=kaldirac, ai_skoru=ai_guven_skoru, tp=hesaplanan_tp,
                    sl=hesaplanan_sl, rr=planlanan_rr, risk_metni=risk_metni,
                    tahmini_zarar=tahmini_zarar, demo_profil=DEMO_CALISMA_PROFILI,
                    demo_live_shadow=DEMO_LIVE_SHADOW_AKTIF, short_islem_aktif=SHORT_ISLEM_AKTIF,
                    model_walk_forward_skoru=model_walk_forward_skoru, min_model_walk_forward_skoru=min_model_walk_forward_skoru,
                    model_kalite_bolgesi=model_kalite_bolgesi, model_kalite_sari=model_kalite_sari,
                    model_kalite_sari_margin_carpani=model_kalite_sari_margin_carpani,
                    rejim=rejim_etiketi,
                )
                demo_journal_status_guncelle()
                return True
            except Exception as e:
                hata = f"❌ İŞLEM/ZIRH BAŞARISIZ ({sembol} - LONG):\n{str(e)}"
                print(f"[{zaman}] {hata}")
                hata_str = str(e)
                if _gecersiz_sembol_kara_listeye_al(ctx, sembol, hata_str):
                    return False
                if not market_emri_acildi and any(kod in hata_str for kod in ("-4131", "PERCENT_PRICE", "502 Bad Gateway")):
                    ctx['COOLDOWN_DICT'][sembol] = datetime.now()
                    print(f"🧊 [COOLDOWN] {sembol} emir kabul hatası nedeniyle kısa beklemeye alındı.")
                if market_emri_acildi:
                    cancel_symbol_orders(borsa_istemci, sembol)
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'sell', miktar)
                        print(f"🛑 [KORUMA] {sembol} LONG pozisyonu stop kurulamadığı için kapatıldı.")
                    except Exception as kapatma_hata:
                        print(f"🚨 [KORUMA] {sembol} LONG kapatma denemesi başarısız: {kapatma_hata}")
                return False
                
        elif "DÜŞÜŞ" in yon:
            market_emri_acildi = False
            acilis_ms = int(time.time() * 1000)
            client_order_id = uuid.uuid4().hex
            print(f"[{sembol}] Emir durumu: {OrderState.CREATED.value} - ID: {client_order_id}")
            params = {'newClientOrderId': client_order_id}
            try:
                max_deneme = 3
                emir = None
                for deneme in range(max_deneme):
                    try:
                        print(f"[{sembol}] Emir durumu: {OrderState.SUBMITTED.value} (Deneme {deneme+1}/{max_deneme})")
                        emir = borsa_istemci.create_market_sell_order(sembol, miktar, params)
                        market_emri_acildi = True
                        print(f"[{sembol}] Emir durumu: {OrderState.FILLED.value}")
                        break
                    except Exception as e:
                        if deneme == max_deneme - 1:
                            print(f"[{sembol}] Emir durumu: {OrderState.REJECTED.value} - Hata: {e}")
                            raise
                        print(f"[{sembol}] Emir hatası: {e}. Tekrar deneniyor...")
                        time.sleep(1)
                gerceklesen_fiyat = emir.get('average') or emir.get('price') or anlik_fiyat
                time.sleep(0.5) 
                sapma_yuzde = _fill_sapma_yuzde(anlik_fiyat, gerceklesen_fiyat)
                if sapma_yuzde > 1.0:
                    print(f"[FILL SAPMASI] {sembol} SHORT iptal: sinyal={anlik_fiyat}, fill={gerceklesen_fiyat}, sapma=%{sapma_yuzde:.2f}")
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'buy', miktar)
                        print(f"[FILL SAPMASI] {sembol} SHORT guvenlik icin kapatildi.")
                    except Exception as kapatma_hata:
                        print(f"[FILL SAPMASI] {sembol} SHORT kapatma basarisiz: {kapatma_hata}")
                    return False

                hesaplanan_tp, hesaplanan_sl = _hedefleri_fill_fiyatina_tasi(
                    "SHORT", anlik_fiyat, gerceklesen_fiyat, hesaplanan_tp, hesaplanan_sl
                )
                if not _stop_on_kontrol("SHORT", sembol, hesaplanan_sl, gerceklesen_fiyat):
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'buy', miktar)
                        print(f"[FILL KORUMA] {sembol} SHORT stop gecersiz oldugu icin kapatildi.")
                    except Exception as kapatma_hata:
                        print(f"[FILL KORUMA] {sembol} SHORT kapatma basarisiz: {kapatma_hata}")
                    return False

                planlanan_rr = _planlanan_rr("SHORT", gerceklesen_fiyat, hesaplanan_tp, hesaplanan_sl)
                
                ctx['aktif_islemler_detay'][f"{sembol}_{hesap_tipi}"] = {
                    'Giris_Fiyati': gerceklesen_fiyat, 'Islem_Yonu': 'SHORT', 'Miktar': miktar,
                    'AI_Guven_Skoru': ai_guven_skoru, 'Hesap_Tipi': hesap_tipi,
                    'TP_Fiyat': hesaplanan_tp, 'SL_Fiyat': hesaplanan_sl,
                    'Planlanan_RR': planlanan_rr, 'Risk_Metni': risk_metni,
                    'Tahmini_Zarar': tahmini_zarar, 'Kullanilan_Margin': kullanilacak_margin,
                    'Kaldirac': kaldirac, 'Demo_Profil': DEMO_CALISMA_PROFILI,
                    'Demo_Live_Shadow': DEMO_LIVE_SHADOW_AKTIF,
                    'Short_Islem_Aktif': SHORT_ISLEM_AKTIF,
                    'Model_Walk_Forward_Skoru': model_walk_forward_skoru,
                    'Min_Model_Walk_Forward_Skoru': min_model_walk_forward_skoru,
                    'Model_Kalite_Bolgesi': model_kalite_bolgesi,
                    'Model_Kalite_Sari': model_kalite_sari,
                    'Model_Kalite_Sari_Margin_Carpani': model_kalite_sari_margin_carpani,
                    'Acilis_Zamani': datetime.now(), 'Acilis_Ms': acilis_ms,
                    'Scale_Out_Yapildi': False
                }
                _detay_kaydet(ctx['aktif_islemler_detay']) 
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                sabit_stop_ok, stop_detay = ensure_single_hard_stop(
                    borsa_istemci, sembol, "SHORT", miktar, sl_fiyat
                )
                if not sabit_stop_ok:
                    raise RuntimeError(
                        f"Tek sabit stop dogrulanamadi: {stop_detay.get('error', 'bilinmeyen hata')}"
                    )
                print(f"[EMIR SYNC] {sembol} SHORT | Tek tam-miktar stop aktif: {sl_fiyat}")
                demo_acilis_kaydet(
                    hesap_tipi=hesap_tipi, sembol=sembol, yon="SHORT",
                    giris=gerceklesen_fiyat, miktar=miktar, margin=kullanilacak_margin,
                    kaldirac=kaldirac, ai_skoru=ai_guven_skoru, tp=hesaplanan_tp,
                    sl=hesaplanan_sl, rr=planlanan_rr, risk_metni=risk_metni,
                    tahmini_zarar=tahmini_zarar, demo_profil=DEMO_CALISMA_PROFILI,
                    demo_live_shadow=DEMO_LIVE_SHADOW_AKTIF, short_islem_aktif=SHORT_ISLEM_AKTIF,
                    model_walk_forward_skoru=model_walk_forward_skoru,
                    min_model_walk_forward_skoru=min_model_walk_forward_skoru,
                    model_kalite_bolgesi=model_kalite_bolgesi, model_kalite_sari=model_kalite_sari,
                    model_kalite_sari_margin_carpani=model_kalite_sari_margin_carpani,
                    rejim=rejim_etiketi,
                )
                demo_journal_status_guncelle()
                return True
                tp_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_tp))
                sl_fiyat = float(borsa_istemci.price_to_precision(sembol, hesaplanan_sl))
                atr_mesafe = abs(gerceklesen_fiyat - sl_fiyat)
                
                scale_out_fark = atr_mesafe * 1.2
                scale_out_fiyat = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat - scale_out_fark))
                yari_miktar = float(borsa_istemci.amount_to_precision(sembol, miktar * 0.3))
                
                volatilite_yuzde = (atr_mesafe / gerceklesen_fiyat) * 100
                callback_rate = round(max(2.0, min(5.0, volatilite_yuzde * 2.5)), 1)
                activation_price = float(borsa_istemci.price_to_precision(sembol, gerceklesen_fiyat - atr_mesafe))
                
                try: borsa_istemci.cancel_all_orders(sembol)
                except Exception: pass

                max_deneme = 3
                sabit_stop_ok = False
                for deneme in range(max_deneme):
                    try:
                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='STOP_MARKET', side='buy', amount=miktar,
                                params={'stopPrice': sl_fiyat, 'reduceOnly': True}
                            )
                            sabit_stop_ok = True
                            print(f"✅ [ÇİFT KALKAN] {sembol} | Sabit Stop Aktif: {sl_fiyat}")
                        except Exception as sl_err:
                            print(f"⚠️ [ZIRH UYARISI] Sabit Stop Kurulamadı: {sl_err}")
                            raise

                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TAKE_PROFIT_MARKET', side='buy', amount=yari_miktar,
                                params={'stopPrice': scale_out_fiyat, 'reduceOnly': True}
                            )
                            print(f"💰 [SCALE-OUT] {sembol} | %30 Kâr Alım Aktif (1.2R): {scale_out_fiyat}")
                        except Exception as tp_err:
                            if "-4130" not in str(tp_err): print(f"⚠️ [ZIRH UYARISI] Scale-Out Kurulamadı: {tp_err}")

                        try:
                            borsa_istemci.create_order(
                                symbol=sembol, type='TRAILING_STOP_MARKET', side='buy', amount=miktar,
                                params={'callbackRate': callback_rate, 'activationPrice': activation_price, 'reduceOnly': True}
                            )
                            print(f"🎯 [SUNUCU GÜVENLİĞİ] {sembol} | Trailing Stop Aktif: %{callback_rate:.2f} | Aktivasyon: {activation_price}")
                        except Exception as tsl_error:
                            if "-4130" not in str(tsl_error): print(f"⚠️ [ZIRH UYARISI] Trailing Stop başarısız: {tsl_error}")

                        print(f"POZİSYON [{hesap_tipi}]: {sembol} | YÖN: SHORT | GİRİŞ: {gerceklesen_fiyat} | ZIRH: SABİT STOP ONAYLI")
                        break
                    except Exception as zirh_hata:
                        hata_msg = str(zirh_hata)
                        if ("-4509" in hata_msg or "position" in hata_msg.lower()) and deneme < max_deneme - 1:
                            time.sleep(2)
                        elif deneme < max_deneme - 1:
                            time.sleep(2)
                        else:
                            print(f"[!] {sembol} Ana Zırh Çöktü: {hata_msg}")
                            raise
                if not sabit_stop_ok:
                    raise RuntimeError("Sabit stop emri doğrulanamadı")
                demo_acilis_kaydet(
                    hesap_tipi=hesap_tipi, sembol=sembol, yon="SHORT",
                    giris=gerceklesen_fiyat, miktar=miktar, margin=kullanilacak_margin,
                    kaldirac=kaldirac, ai_skoru=ai_guven_skoru, tp=hesaplanan_tp,
                    sl=hesaplanan_sl, rr=planlanan_rr, risk_metni=risk_metni,
                    tahmini_zarar=tahmini_zarar, demo_profil=DEMO_CALISMA_PROFILI,
                    demo_live_shadow=DEMO_LIVE_SHADOW_AKTIF, short_islem_aktif=SHORT_ISLEM_AKTIF,
                    model_walk_forward_skoru=model_walk_forward_skoru, min_model_walk_forward_skoru=min_model_walk_forward_skoru,
                    model_kalite_bolgesi=model_kalite_bolgesi, model_kalite_sari=model_kalite_sari,
                    model_kalite_sari_margin_carpani=model_kalite_sari_margin_carpani,
                    rejim=rejim_etiketi,
                )
                demo_journal_status_guncelle()
                return True
            except Exception as e:
                hata = f"❌ İŞLEM/ZIRH BAŞARISIZ ({sembol} - SHORT):\n{str(e)}"
                print(f"[{zaman}] {hata}")
                hata_str = str(e)
                if _gecersiz_sembol_kara_listeye_al(ctx, sembol, hata_str):
                    return False
                if not market_emri_acildi and any(kod in hata_str for kod in ("-4131", "PERCENT_PRICE", "502 Bad Gateway")):
                    ctx['COOLDOWN_DICT'][sembol] = datetime.now()
                    print(f"🧊 [COOLDOWN] {sembol} emir kabul hatası nedeniyle kısa beklemeye alındı.")
                if market_emri_acildi:
                    cancel_symbol_orders(borsa_istemci, sembol)
                    try:
                        _koruma_kapatma_emri_gonder(borsa_istemci, sembol, 'buy', miktar)
                        print(f"🛑 [KORUMA] {sembol} SHORT pozisyonu stop kurulamadığı için kapatıldı.")
                    except Exception as kapatma_hata:
                        print(f"🚨 [KORUMA] {sembol} SHORT kapatma denemesi başarısız: {kapatma_hata}")
                return False
            
    except Exception as e:
        raise e

def canli_islem_kapat(borsa_istemci, sembol, islem_yonu, miktar):
    try:
        zit_yon = 'sell' if islem_yonu == 'LONG' else 'buy'
        print(f"⚠️ [DETERMINİSTİK EXIT] {sembol} için Zıt Yön ({zit_yon.upper()}) Fiziksel Kapanış Emri (Reduce-Only) gönderiliyor...")
        emir = borsa_istemci.create_order(symbol=sembol, type='MARKET', side=zit_yon, amount=miktar, params={'reduceOnly': True})
        
        cancel_symbol_orders(borsa_istemci, sembol)
        print(f"✅ {sembol} BAŞARIYLA FİZİKSEL OLARAK KAPATILDI!")
        return emir
    except Exception as e:
        print(f"❌ [KAPANIŞ HATASI] {sembol} Fiziksel Kapanış İletilemedi: {e}")
        return None
