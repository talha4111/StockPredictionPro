"""
position_tracker.py — Gerçek Zamanlı Pozisyon Takip ve Raporlama Motoru
main.py'den ayrıştırıldı.
"""
from datetime import datetime
import time
import re
from db_logger import (
    islem_kaydet, _detay_kaydet, _detay_senkronize,
    telegrama_gonder, gunluk_rapor_gonder,
)
from config import DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF, SHORT_ISLEM_AKTIF
from exit_rules import process_demo_exit_rules
from risk_manager import _gunluk_risk_guncelle, _gunluk_risk_ozeti
from scanner_loop import borsa_gerceklesen_pnl_getir
from account_sync import (
    bakiye_ozeti_getir,
    gelir_ozeti_hesapla,
    sembol_gelir_net,
)
from symbol_guard import sembol_zararini_isle
from order_sync import (
    cancel_symbol_orders,
    ensure_single_hard_stop,
    reconcile_protective_orders,
)

try:
    from runtime_status import status_yaz
except:
    def status_yaz(a, event=None): pass

def _piyasa_referans_fiyati(borsa_istemci, sembol, varsayilan=0.0):
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

def _kapatma_emri_gonder(borsa_istemci, sembol, side, miktar, referans_fiyat=0.0, reduce_only=True):
    try:
        return borsa_istemci.create_order(
            symbol=sembol, type='MARKET', side=side, amount=miktar,
            params={'reduceOnly': reduce_only} if reduce_only else {}
        )
    except Exception as market_hata:
        hata_str = str(market_hata)
        if "-4131" not in hata_str and "PERCENT_PRICE" not in hata_str:
            raise
        referans = _piyasa_referans_fiyati(borsa_istemci, sembol, referans_fiyat)
        if referans <= 0:
            raise
        limit_fiyat = referans * (0.995 if side == 'sell' else 1.005)
        try:
            limit_fiyat = float(borsa_istemci.price_to_precision(sembol, limit_fiyat))
        except Exception:
            pass
        print(f"  🧯 Market kapatma fiyat filtresine takıldı; agresif LIMIT/IOC deneniyor: {limit_fiyat}")
        params = {'reduceOnly': reduce_only, 'timeInForce': 'IOC'} if reduce_only else {'timeInForce': 'IOC'}
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
            print(f"  🧯 Binance fiyat sınırı uygulandı; LIMIT/IOC tekrar deneniyor: {duzeltilmis_fiyat}")
            return borsa_istemci.create_order(
                symbol=sembol, type='LIMIT', side=side, amount=miktar, price=duzeltilmis_fiyat,
                params=params
            )

def _market_limitleri(borsa_istemci, sembol):
    max_qty = float('inf')
    min_amount = 0.0
    try:
        if not getattr(borsa_istemci, "markets", None):
            borsa_istemci.load_markets()
        m_info = borsa_istemci.markets.get(f"{sembol}:USDT") or borsa_istemci.markets.get(sembol)
        if m_info:
            m_max = m_info.get('limits', {}).get('market', {}).get('max')
            m_min = m_info.get('limits', {}).get('amount', {}).get('min')
            if m_max:
                max_qty = float(m_max)
            if m_min:
                min_amount = float(m_min)
    except Exception:
        pass
    return max_qty, min_amount

def _pozisyon_miktari_oku(pozisyon):
    info = pozisyon.get('info', {}) or {}
    raw_amt = info.get('positionAmt')
    if raw_amt in (None, ''):
        contracts = float(pozisyon.get('contracts', 0) or 0)
        if str(pozisyon.get('side', '')).lower() == 'short':
            contracts = -contracts
        raw_amt = contracts
    return float(raw_amt or 0.0)

def _pozisyon_miktari_cek(borsa_istemci, sembol):
    pozisyonlar = borsa_istemci.fetch_positions([sembol])
    if not isinstance(pozisyonlar, list):
        raise RuntimeError('pozisyon API cevabi liste degil')

    hedef = str(sembol or '').replace(':USDT', '')
    for pozisyon in pozisyonlar:
        info = pozisyon.get('info', {}) or {}
        sembol_raw = pozisyon.get('symbol') or info.get('symbol') or ''
        mevcut = str(sembol_raw).replace(':USDT', '')
        if mevcut == hedef:
            return abs(_pozisyon_miktari_oku(pozisyon))

    if not pozisyonlar:
        return 0.0
    raise RuntimeError(f'{sembol} pozisyonu API cevabinda bulunamadi')

def _koruma_stop_emri_kur(borsa_istemci, sembol, islem_yonu, miktar, sl_hedef, referans_fiyat=0.0):
    try:
        miktar = abs(float(miktar))
        sl_hedef = float(sl_hedef or 0)
    except Exception:
        return False
    if miktar <= 0 or sl_hedef <= 0:
        return False

    _, min_amount = _market_limitleri(borsa_istemci, sembol)
    try:
        miktar = float(borsa_istemci.amount_to_precision(sembol, miktar))
        sl_fiyat = float(borsa_istemci.price_to_precision(sembol, sl_hedef))
    except Exception:
        sl_fiyat = sl_hedef

    if miktar < min_amount:
        print(f"  [ZIRH] {sembol} stop miktari Binance minimumundan kucuk ({miktar} < {min_amount}), stop kurulamayacak.")
        return False

    referans = _piyasa_referans_fiyati(borsa_istemci, sembol, referans_fiyat)
    if referans > 0:
        if islem_yonu == 'LONG' and sl_fiyat >= referans:
            print(f"  [ZIRH] {sembol} stop fiyati piyasanin ustunde/yaninda, kurulum atlandi. SL={sl_fiyat}, Piyasa={referans}")
            return False
        if islem_yonu == 'SHORT' and sl_fiyat <= referans:
            print(f"  [ZIRH] {sembol} stop fiyati piyasanin altinda/yaninda, kurulum atlandi. SL={sl_fiyat}, Piyasa={referans}")
            return False

    try:
        ok, detay = ensure_single_hard_stop(
            borsa_istemci, sembol, islem_yonu, miktar, sl_fiyat
        )
        if not ok:
            raise RuntimeError(detay.get('error', 'stop verify failed'))
        print(f"  [ZIRH] {sembol} kalan pozisyon icin sabit stop yeniden kuruldu: {sl_fiyat}")
        return True
    except Exception as e:
        print(f"  [ZIRH-UYARI] {sembol} sabit stop yeniden kurulamadı: {e}")
        return False

def _hesap_pozisyon_cek(borsa_istemci, hesap_tipi, mevcut_semboller, aktifler, live_tetik_acik=False):
    try:
        # Eğer canlı işlem kapalıysa Live API'yi hiç yorma ve hata verme
        if hesap_tipi == 'LIVE' and not live_tetik_acik:
            return True
            
        if not hasattr(borsa_istemci, 'apiKey') or not borsa_istemci.apiKey:
            return True
        pozisyonlar = borsa_istemci.fetch_positions()
        if type(pozisyonlar) is not list:
            raise Exception("API Hatalı Format")
            
        for p in pozisyonlar:
            info = p.get('info', {}) or {}
            raw_amt = info.get('positionAmt')
            if raw_amt in (None, ''):
                contracts = float(p.get('contracts', 0) or 0)
                raw_amt = -contracts if str(p.get('side', '')).lower() == 'short' else contracts
            amt = float(raw_amt or 0)
            sembol_raw = p.get('symbol', 'Bilinmiyor')
            sembol = sembol_raw.replace(':USDT', '')
            
            # Binance Testnet MITO/USDT likidite bug'ı nedeniyle kapanmayan pozisyonu yoksay
            if amt != 0:
                p['Hesap_Tipi'] = hesap_tipi
                aktifler.append((p, amt))
                mevcut_semboller.add(f"{sembol}_{hesap_tipi}")
        return True # API Başarılı
    except Exception as e:
        if hesap_tipi == 'LIVE':  # Sadece LIVE hataları göster, DEMO sessiz kalsın
            print(f"⏳ [Bağlantı Bekleniyor...] {hesap_tipi} API geçici olarak ulaşılamıyor. (Detay: {e})")
        return False # API Hatası

def _fatura_baslangic_ms(detay, fallback_seconds=86400):
    """Return the precise entry timestamp used to invoice one position."""
    if isinstance(detay, dict):
        try:
            acilis_ms = int(float(detay.get('Acilis_Ms') or 0))
            if acilis_ms > 0:
                return acilis_ms
        except (TypeError, ValueError):
            pass

        raw_zaman = detay.get('Acilis_Zamani')
        try:
            if isinstance(raw_zaman, str):
                raw_zaman = datetime.fromisoformat(raw_zaman)
            if isinstance(raw_zaman, datetime):
                return int(raw_zaman.timestamp() * 1000)
        except (TypeError, ValueError):
            pass

    return int((time.time() - float(fallback_seconds)) * 1000)


def _demo_borsa_kapanisini_kaydet(ctx, eski_key, eski_pnl):
    """Record a DEMO position closed by a server-side Binance algo order."""
    eski_sembol = eski_key.rsplit('_', 1)[0] if '_' in eski_key else eski_key
    detay = (
        ctx['aktif_islemler_detay'].get(eski_key)
        or ctx['aktif_islemler_detay'].get(f"{eski_sembol}_TESTNET")
        or ctx['aktif_islemler_detay'].get(f"{eski_sembol}_DEMO")
        or {}
    )

    since_ms = _fatura_baslangic_ms(detay)
    until_ms = int(time.time() * 1000)

    try:
        fatura = sembol_gelir_net(ctx['borsa'], eski_sembol, since_ms, until_ms)
        gercek_pnl = float(fatura.get('net', eski_pnl)) if fatura.get('kayit_sayisi', 0) else float(eski_pnl)
    except Exception:
        fatura = {}
        gercek_pnl = float(eski_pnl)

    if gercek_pnl >= 0:
        ctx['performans']['kazanc'] += 1
        ctx['DEMO_ARDISIK_ZARAR'] = 0
    else:
        ctx['performans']['kayip'] += 1
        ctx['DEMO_ARDISIK_ZARAR'] += 1
    ctx['SON_ISLEMLER_PNL_DEMO'].append(gercek_pnl)
    if len(ctx['SON_ISLEMLER_PNL_DEMO']) > 10:
        ctx['SON_ISLEMLER_PNL_DEMO'].pop(0)

    if isinstance(detay, dict) and detay:
        giris = float(detay.get('Giris_Fiyati', 0.0) or 0.0)
        miktar = abs(float(detay.get('Miktar', 0.0) or 0.0))
        islem_yonu = str(detay.get('Islem_Yonu', 'LONG'))
        ai_skoru = float(detay.get('AI_Guven_Skoru', 0.0) or 0.0)
        cikis = giris
        if miktar > 0 and islem_yonu == 'LONG':
            cikis = giris + (gercek_pnl / miktar)
        elif miktar > 0 and islem_yonu == 'SHORT':
            cikis = giris - (gercek_pnl / miktar)
        pnl_yuzde = ((cikis - giris) / giris * 100.0) if giris > 0 else 0.0
        if islem_yonu == 'SHORT':
            pnl_yuzde *= -1.0
        detay['Son_Kapanma_Sebebi'] = 'binance_algo_emri'
        detay['Binance_Fatura'] = fatura
        islem_kaydet(
            eski_sembol, 'TESTNET', islem_yonu,
            round(giris, 8), round(cikis, 8), round(gercek_pnl, 2),
            round(pnl_yuzde, 2), round(ai_skoru, 2), ctx['aktif_islemler_detay'],
        )

    try:
        sembol_zararini_isle(ctx, eski_sembol, gercek_pnl, 'Binance algo emri')
    except Exception:
        pass
    try:
        cancel_symbol_orders(ctx['borsa'], eski_sembol)
    except Exception:
        pass
    for detay_key in (eski_key, f"{eski_sembol}_TESTNET", f"{eski_sembol}_DEMO"):
        ctx['aktif_islemler_detay'].pop(detay_key, None)
    _detay_kaydet(ctx['aktif_islemler_detay'])
    print(f"[DEMO SYNC] {eski_sembol} borsa kapanisi kaydedildi: {gercek_pnl:+.2f} USDT")


def pozisyon_takip_paneli(ctx):


    while True:
        try:
            aktifler = []
            mevcut_semboller = set()
            
            api_sorgu_basarili = True
            demo_api_ok = False
            
            # --- LIVE: GERÇEK POZİSYONLARI ÇEK ---
            if ctx['LIVE_MOD_AKTIF']:
                live_api_ok = _hesap_pozisyon_cek(
                    ctx['borsa_live'], "LIVE", mevcut_semboller, aktifler,
                    ctx.get('ALIM_SATIM_TETIGI_ACIK', False),
                )
                if not live_api_ok:
                    api_sorgu_basarili = False
            else:
                live_api_ok = False  # LIVE modu kapalı, API'ye dokunma
            # --- TESTNET (DEMO): CACHE İLE POZİSYONLARİ ÇEK (5dk aralıkla) ---
            simdi_ts = time.time()
            if simdi_ts - ctx['_DEMO_CACHE']['son_guncelleme'] > ctx['_DEMO_CACHE_SURESI']:
                demo_api_ok = _hesap_pozisyon_cek(ctx['borsa'], "DEMO", mevcut_semboller, aktifler)
                if demo_api_ok:
                    # Cache'e kaydet — sadece DEMO pozisyonlarını sakla
                    ctx['_DEMO_CACHE']['pozisyonlar'] = [(p, a) for p, a in aktifler if p.get('Hesap_Tipi') == 'DEMO']
                    ctx['_DEMO_CACHE']['son_guncelleme'] = simdi_ts
                else:
                    api_sorgu_basarili = False
            else:
                # Cache'den oku (API'ye dokunma)
                for cp, ca in ctx['_DEMO_CACHE'].get('pozisyonlar', []):
                    sym = cp.get('symbol', '').replace(':USDT', '')
                    if f"{sym}_DEMO" not in mevcut_semboller:
                        aktifler.append((cp, ca))
                        mevcut_semboller.add(f"{sym}_DEMO")
            
            # --- DETAY DOSYASI SENKRONİZASYONU (10dk'da bir) ---
            if api_sorgu_basarili:
                _detay_senkronize(mevcut_semboller, ctx['aktif_islemler_detay'])

            # Conditional orders use Binance's separate Algo Order API.
            # Keep entries locked until every open demo position has one hard stop.
            sync_state = ctx.setdefault('ORDER_SYNC_STATE', {})
            if demo_api_ok and simdi_ts - float(sync_state.get('last_run_ts', 0) or 0) >= 60:
                demo_positions = [
                    p for p, _ in aktifler if p.get('Hesap_Tipi') == 'DEMO'
                ]
                sync_result = reconcile_protective_orders(
                    ctx['borsa'], demo_positions, ctx['aktif_islemler_detay']
                )
                sync_state.clear()
                sync_state.update(sync_result)
                sync_state['last_run_ts'] = simdi_ts
                sync_state['last_error'] = '; '.join(sync_result.get('errors', [])[:3])
                status_yaz({"emir_senkron": sync_result})
                if sync_result.get('ready'):
                    print(
                        f"[EMIR SYNC] Hazir | pozisyon={sync_result.get('active_positions', 0)} "
                        f"| algo={sync_result.get('algo_after', 0)}"
                    )
                else:
                    print(f"[EMIR SYNC KILIDI] {sync_state['last_error']}")
            
            # --- Kapanan Pozisyon Tespiti (Win/Loss Tracker) ---
            for eski_key, eski_pnl in list(ctx['onceki_pozisyonlar'].items()):
                if eski_key not in mevcut_semboller:
                    eski_sembol = eski_key.split('_')[0]
                    hesap_t = eski_key.split('_')[1] if '_' in eski_key else 'DEMO'
                    if hesap_t == 'DEMO':
                        if not demo_api_ok:
                            mevcut_semboller.add(eski_key)
                            continue
                        _demo_borsa_kapanisini_kaydet(ctx, eski_key, eski_pnl)
                        continue
                    if hesap_t == 'DEMO':
                        continue # Demo Sanal Motor kapanışları kendi Loop'unda halletti.
                        
                    if not live_api_ok:
                        mevcut_semboller.add(eski_key) # Körlük Kalkanı: API çöktü, işlem AÇIK!
                        continue
                        
                    # Gerçekçi Fatura Denetimi (Deterministic Engine)
                    gercek_pnl = borsa_gerceklesen_pnl_getir(ctx['borsa_live'], eski_sembol)
                    if gercek_pnl is None: 
                        gercek_pnl = eski_pnl # Fatura okunamadıysa geçici olarak eski PNL kullan
                        
                    if gercek_pnl >= 0:
                        ctx['performans']['kazanc'] += 1
                        ctx['LIVE_ARDISIK_ZARAR'] = 0
                        print(f"✅ [{hesap_t}] {eski_sembol} KÂRLA KAPANDI! (Gerçekleşen Fatura: +{gercek_pnl:.2f} USDT)")
                    else:
                        ctx['performans']['kayip'] += 1
                        ctx['LIVE_ARDISIK_ZARAR'] += 1
                        print(f"❌ [{hesap_t}] {eski_sembol} ZARARLA KAPANDI! (Gerçekleşen Fatura: {gercek_pnl:.2f} USDT)")
                        
                    if ctx['LIVE_ARDISIK_ZARAR'] >= 3:
                        ctx['ALIM_SATIM_TETIGI_ACIK'] = False
                        ctx['CANLI_DEVRE_KESICI_AKTIF'] = True
                        print("🛑 [DEVRE KESİCİ] 3 Ardışık Canlı Zarar! LIVE işlemler kilitlendi, uyanış için Demo kanıtı bekleniyor...")

                    # --- ANLIK BEKLENTİ (EXPECTANCY) KONTROLÜ ---
                    ctx['SON_ISLEMLER_PNL_LIVE'].append(gercek_pnl)
                    if len(ctx['SON_ISLEMLER_PNL_LIVE']) > 10:
                        ctx['SON_ISLEMLER_PNL_LIVE'].pop(0)

                    if len(ctx['SON_ISLEMLER_PNL_LIVE']) == 10:
                        _karlar = [p for p in ctx['SON_ISLEMLER_PNL_LIVE'] if p > 0]
                        _zararlar = [p for p in ctx['SON_ISLEMLER_PNL_LIVE'] if p <= 0]
                        _win_rate = len(_karlar) / 10.0
                        _loss_rate = len(_zararlar) / 10.0
                        _avg_kar = sum(_karlar) / len(_karlar) if _karlar else 0.0
                        _avg_zarar = abs(sum(_zararlar) / len(_zararlar)) if _zararlar else 0.0
                        _expectancy = (_win_rate * _avg_kar) - (_loss_rate * _avg_zarar)
                        
                        if _expectancy < -0.2 and not ctx['CANLI_DEVRE_KESICI_AKTIF']:
                            ctx['ALIM_SATIM_TETIGI_ACIK'] = False
                            ctx['CANLI_DEVRE_KESICI_AKTIF'] = True
                            print(f"🛑 [DEVRE KESİCİ] Matematiksel Beklenti Çöktü (E: {_expectancy:.2f}) HEDEF: > -0.2! LIVE işlemler kilitlendi...")
                        
                    # --- Trade Logger Kaydı ---
                    detay = ctx['aktif_islemler_detay'].get(eski_key, {})
                    if detay:
                        giris = detay.get('Giris_Fiyati', 0.0)
                        miktar = detay.get('Miktar', 1.0)
                        islem_yonu = detay.get('Islem_Yonu', 'Bilinmiyor')
                        ai_skoru = detay.get('AI_Guven_Skoru', 0.0)
                        
                        cikis = 0.0
                        pnl_yuzde = 0.0
                        if islem_yonu == 'LONG':
                            cikis = giris + (gercek_pnl / miktar) if miktar > 0 else 0
                            pnl_yuzde = ((cikis - giris) / giris) * 100 if giris > 0 else 0
                        elif islem_yonu == 'SHORT':
                            cikis = giris - (gercek_pnl / miktar) if miktar > 0 else 0
                            pnl_yuzde = ((giris - cikis) / giris) * 100 if giris > 0 else 0
                        
                        detay['Son_Kapanma_Sebebi'] = "pozisyon_borsada_kapandi"
                        islem_kaydet(
                            eski_sembol, hesap_t, islem_yonu,
                            round(giris, 6), round(cikis, 6),
                            round(gercek_pnl, 2), round(pnl_yuzde, 2), round(ai_skoru, 2),
                            ctx['aktif_islemler_detay'],
                        )
                        
                        if hesap_t == 'LIVE' and ctx['LIVE_MOD_AKTIF']:
                            try:
                                cancel_symbol_orders(ctx['borsa_live'], eski_sembol)
                                print(f"🧹 [{eski_sembol}] Otonom Temizlik: Arkada kalan şarta bağlı (Stop/TP) emirler iptal edildi.")
                            except: pass
                            
                        try: del ctx['aktif_islemler_detay'][eski_key]
                        except: pass
            
            # Mevcut pozisyonları güncelle
            yeni_pozisyonlar = {}
            
            # --- BAKİYE GÜNCELLEME (CACHE + API) ---
            simdi_ts2 = time.time()
            _demo_bal_raw = {}  # Binance RAW bakiye verisini sakla
            _demo_bakiye_ozeti = ctx['_DEMO_CACHE'].get('bakiye_ozeti', {}) or {}
            bakiye_son_guncelleme = ctx['_DEMO_CACHE'].get('bakiye_son_guncelleme', 0)
            if simdi_ts2 - bakiye_son_guncelleme < ctx['_DEMO_CACHE_SURESI'] and ctx['_DEMO_CACHE']['bakiye'] > 0:
                bakiye_demo = ctx['_DEMO_CACHE']['bakiye']
                _demo_bal_raw = ctx['_DEMO_CACHE'].get('raw', {})
            else:
                try:
                    _demo_bakiye_ozeti = (
                        bakiye_ozeti_getir(ctx['borsa'])
                        if hasattr(ctx['borsa'], 'apiKey') and ctx['borsa'].apiKey
                        else {}
                    )
                    _demo_bal_raw = _demo_bakiye_ozeti.get('raw', {})
                    bakiye_demo = float(_demo_bakiye_ozeti.get('wallet', 0.0) or 0.0)
                    ctx['KASA_DURUM']['DEMO_KASA'] = bakiye_demo
                    ctx['_DEMO_CACHE']['bakiye'] = bakiye_demo
                    ctx['_DEMO_CACHE']['raw'] = _demo_bal_raw
                    ctx['_DEMO_CACHE']['bakiye_ozeti'] = _demo_bakiye_ozeti
                    ctx['_DEMO_CACHE']['bakiye_son_guncelleme'] = simdi_ts2
                except Exception:
                    # API hata verirse son bilinen bakiyeyi koru
                    bakiye_demo = ctx['_DEMO_CACHE']['bakiye'] if ctx['_DEMO_CACHE']['bakiye'] > 0 else 0.0
                    ctx['KASA_DURUM']['DEMO_KASA'] = bakiye_demo


            if ctx['LIVE_MOD_AKTIF']:
                try:
                    bakiye_live = float(ctx['borsa_live'].fetch_balance({'type': 'future'}).get('USDT', {}).get('total', 0.0)) if hasattr(ctx['borsa_live'], 'apiKey') and ctx['borsa_live'].apiKey else 0.0
                    ctx['KASA_DURUM']['LIVE_KASA'] = bakiye_live
                except:
                    bakiye_live = 0.0
            else:
                bakiye_live = 0.0
            
            # --- OTONOM RESET (GECE 00:00) VE DRAWDOWN (KANAMA) KONTROLÜ ---
            bugun = datetime.now().date()
            if bugun != ctx['SON_RESET_TARIHI']:
                ctx['SON_RESET_TARIHI'] = bugun
                ctx['GUN_BASLANGIC_BAKIYESI'] = bakiye_live
                ctx['LIVE_ARDISIK_ZARAR'] = 0
                ctx['DEMO_ARDISIK_KAR'] = 0
                ctx['SON_ISLEMLER_PNL_LIVE'].clear()
                # ⚠️ ctx['ALIM_SATIM_TETIGI_ACIK'] DEĞİŞTİRİLMEZ!
                # Bu değer sadece kullanıcı tarafından kod seviyesinde açılır.
                # Gece yarısı reseti Live tetiği açmamalı.
                ctx['CANLI_DEVRE_KESICI_AKTIF'] = False
                print(f"🌅 [YENİ GÜN] Sistem sayaçları sıfırlandı. Yeni Gün Başlangıç Bakiyesi: {ctx['GUN_BASLANGIC_BAKIYESI']:.2f} USDT")
                
                # --- TELEGRAM GECE RAPORU ---
                gunluk_rapor_gonder(
                    ctx['performans'], ctx['KASA_DURUM'], ctx['_DEMO_CACHE'],
                    ctx.get('KARANTINA_LISTESI', {}),
                )
                
                try:
                    import subprocess
                    import sys
                    print("📊 [GECE YARISI OTOMASYONU] Müfettiş ve Dijital Analist otonom olarak tetikleniyor...")
                    subprocess.Popen([sys.executable, "mufettis.py"])
                except:
                    pass
                
            if ctx['GUN_BASLANGIC_BAKIYESI'] is None and bakiye_live > 0:
                ctx['GUN_BASLANGIC_BAKIYESI'] = bakiye_live
                
            if ctx['GUN_BASLANGIC_BAKIYESI'] is not None and bakiye_live > 0:
                drawdown_yuzde = ((ctx['GUN_BASLANGIC_BAKIYESI'] - bakiye_live) / ctx['GUN_BASLANGIC_BAKIYESI']) * 100
                if drawdown_yuzde >= 10.0 and ctx['ALIM_SATIM_TETIGI_ACIK']:
                    ctx['ALIM_SATIM_TETIGI_ACIK'] = False
                    ctx['CANLI_DEVRE_KESICI_AKTIF'] = True
                    print(f"🚨 [KRİTİK ZARAR EŞİĞİ] Günlük bakiye %{drawdown_yuzde:.2f} eridi (Limit: %10)! Sistem güvenlik için durduruldu.")
                    
            print("\n" + "="*50)
            
            toplam_pnl_demo = 0
            toplam_pnl_live = 0
            
            if not aktifler:
                print(f"⏳ [{datetime.now().strftime('%H:%M:%S')}] Aktif İşlem Yok. Fırsatlar Taranıyor...")
            else:
                print(f"📊 AÇIK POZİSYONLAR | {datetime.now().strftime('%H:%M:%S')}")
                print("-" * 50)
                
                for p, amt in aktifler:
                    sembol = p.get('symbol', 'Bilinmiyor').replace(':USDT', '')
                    hesap_t = p.get('Hesap_Tipi', 'Bilinmiyor')
                    guncel_fiyat = float(p.get('markPrice', p.get('info', {}).get('markPrice', 0)))
                    giris_fiyat = float(p.get('entryPrice', p.get('info', {}).get('entryPrice', 0)))
                    pnl = float(p.get('unrealizedPnl', p.get('info', {}).get('unRealizedProfit', 0)))
                    key = f"{sembol}_{hesap_t}"
                    
                    if hesap_t == 'LIVE':
                        toplam_pnl_live += pnl
                    else:
                        toplam_pnl_demo += pnl
                        
                    yeni_pozisyonlar[key] = pnl
                    
                    # ═══════════════════════════════════════════════════════
                    # 🧠 PRO YAZILIMSAL ÇIKIŞ MOTORU v2.0
                    # Live kalitesinde: ATR bazlı TP/SL, Kısmi Kâr Alım,
                    # Dinamik Trailing Stop, Break-Even Stop, Zaman Aşımı
                    # ═══════════════════════════════════════════════════════
                    if hesap_t == 'DEMO' and giris_fiyat > 0 and guncel_fiyat > 0:
                        # Key uyuşmazlığını çöz: DEMO vs TESTNET
                        # islem_ac "TESTNET" olarak kaydeder, pozisyon_takip "DEMO" olarak okur
                        alt_key = f"{sembol}_TESTNET"
                        detay = ctx['aktif_islemler_detay'].get(key) or ctx['aktif_islemler_detay'].get(alt_key) or {}
                        # Gerçek detay anahtarını belirle (temizlikte kullanılacak)
                        detay_key = key if key in ctx['aktif_islemler_detay'] else (alt_key if alt_key in ctx['aktif_islemler_detay'] else key)
                        # ⚠️ JSON YERİNE DOĞRUDAN BİNANCE MİKTARINA GÜVEN:
                        islem_yonu = 'LONG' if amt > 0 else 'SHORT'
                        ai_skoru = detay.get('AI_Guven_Skoru', 0.0)
                        
                        tp_hedef = detay.get('TP_Fiyat', 0)
                        sl_hedef = detay.get('SL_Fiyat', 0)
                        raw_zaman = detay.get('Acilis_Zamani', None)
                        if isinstance(raw_zaman, str):
                            try: acilis_zamani = datetime.fromisoformat(raw_zaman)
                            except: acilis_zamani = datetime.now()
                        elif isinstance(raw_zaman, datetime):
                            acilis_zamani = raw_zaman
                        else:
                            acilis_zamani = datetime.now()
                        scale_out_yapildi = detay.get('Scale_Out_Yapildi', False)
                        
                        # ═══════════════════════════════════════════
                        # PNL HESABI (Binance PNL'ini kullan!)
                        # ═══════════════════════════════════════════
                        if islem_yonu == 'LONG':
                            pnl_yuzde_ham = ((guncel_fiyat - giris_fiyat) / giris_fiyat) * 100
                        else:
                            pnl_yuzde_ham = ((giris_fiyat - guncel_fiyat) / giris_fiyat) * 100
                        
                        islem_buyuklugu = abs(amt) * giris_fiyat
                        if islem_buyuklugu > 0:
                            pnl_yuzde = (pnl / islem_buyuklugu) * 100
                        else:
                            pnl_yuzde = pnl_yuzde_ham
                        
                        if sl_hedef > 0:
                            atr_mesafe = abs(giris_fiyat - sl_hedef)
                        else:
                            atr_mesafe = giris_fiyat * 0.015  # Fallback %1.5
                        
                        # Trailing Stop Hafızası
                        tsl_key = f"_tsl_max_{key}"
                        tsl_key_alt = f"_tsl_max_{sembol}_TESTNET" if hesap_t == 'DEMO' else tsl_key
                        if tsl_key not in ctx['aktif_islemler_detay'] and tsl_key_alt in ctx['aktif_islemler_detay']:
                            ctx['aktif_islemler_detay'][tsl_key] = ctx['aktif_islemler_detay'][tsl_key_alt]
                        if tsl_key not in ctx['aktif_islemler_detay']:
                            ctx['aktif_islemler_detay'][tsl_key] = pnl_yuzde
                        if pnl_yuzde > ctx['aktif_islemler_detay'][tsl_key]:
                            ctx['aktif_islemler_detay'][tsl_key] = pnl_yuzde
                        zirve_pnl = ctx['aktif_islemler_detay'][tsl_key]
                        
                        atr_yuzde = (atr_mesafe / giris_fiyat) * 100
                        callback = max(1.5, min(4.0, atr_yuzde * 2.0))
                        tsl_activation_yuzde = atr_yuzde
                        
                        demo_kasa_anlik = ctx['KASA_DURUM'].get('DEMO_KASA', 3000)
                        
                        # BTC Flash Dump momentum tespiti
                        btc_1h_ret, btc_15m_ret = 0.0, 0.0
                        try:
                            if 'borsa' in ctx and ctx['borsa']:
                                btc_ohlcv = ctx['borsa'].fetch_ohlcv('BTC/USDT', timeframe='15m', limit=5)
                                if btc_ohlcv and len(btc_ohlcv) >= 4:
                                    son_f = float(btc_ohlcv[-1][4])
                                    f_15m = float(btc_ohlcv[-2][4])
                                    f_1h = float(btc_ohlcv[0][4])
                                    btc_15m_ret = (son_f - f_15m) / f_15m
                                    btc_1h_ret = (son_f - f_1h) / f_1h
                        except Exception:
                            pass

                        kapanma_sebebi, kapanma_miktari = process_demo_exit_rules(
                            islem_yonu=islem_yonu, giris_fiyat=giris_fiyat, guncel_fiyat=guncel_fiyat,
                            pnl=pnl, pnl_yuzde=pnl_yuzde, amt=amt, sl_hedef=sl_hedef, zirve_pnl=zirve_pnl,
                            tsl_activation_yuzde=tsl_activation_yuzde, callback=callback, atr_yuzde=atr_yuzde,
                            acilis_zamani=acilis_zamani, scale_out_yapildi=scale_out_yapildi, demo_kasa_anlik=demo_kasa_anlik,
                            btc_1h_ret=btc_1h_ret, btc_15m_ret=btc_15m_ret
                        )
                        
                        # ━━━━━━━━ ÇIKIŞ EMRİ GÖNDER (v5) ━━━━━━━━
                        if kapanma_sebebi:
                            print(f"\n  ⚡ [ÇIKIŞ MOTORU] {sembol} | {kapanma_sebebi}")
                            fatura_baslangic_ms = _fatura_baslangic_ms(detay)
                            # Tüm olası key varyantları (DEMO + TESTNET)
                            tum_temizlik_keyleri = list(set([tsl_key, key, f"{sembol}_TESTNET", f"_tsl_max_{sembol}_TESTNET", f"_tsl_max_{sembol}_DEMO", detay_key]))
                            kapanma_miktari = abs(amt)  # Güvenli başlangıç değeri
                            try:
                                zit_yon = 'sell' if islem_yonu == 'LONG' else 'buy'
                                
                                # ADIM 2: Binance'ten GERÇEK pozisyon miktarını çek
                                try:
                                    gercek_miktar = _pozisyon_miktari_cek(ctx['borsa'], sembol)
                                except Exception as err:
                                    print(f"  ⚠️ Miktar çekilemedi, pozisyon miktarı doğrulanamadı: {err}")
                                    print("  ℹ️ İşlem şimdilik atlanıyor. Bir sonraki turda tekrar denenecek.")
                                    continue # Döngünün sonraki pozisyonuna geç
                                
                                # Pozisyon zaten kapalıysa (miktar 0), işlemi atla ve hafızayı temizle
                                if gercek_miktar == 0:
                                    print(f"  [EXIT] {sembol} pozisyonu zaten kapali; resmi gelir kaydi sonraki senkron turuna birakildi.")
                                    continue
                                
                                # ADIM 3: Çıkış Miktarı ve Hassasiyet (Precision) Ayarı
                                if 'SCALE-OUT' in kapanma_sebebi:
                                    ham_miktar = gercek_miktar * 0.40
                                else:
                                    ham_miktar = gercek_miktar
                                    
                                try:
                                    # Binance'in kabul edeceği tam hassasiyete (küsurata) yuvarla
                                    kapanma_miktari = float(ctx['borsa'].amount_to_precision(sembol, ham_miktar))
                                except:
                                    kapanma_miktari = ham_miktar
                                # ADIM 3.5: Max Market Qty ve Min Amount Kontrolü
                                max_qty, min_amount = _market_limitleri(ctx['borsa'], sembol)
                                
                                if kapanma_miktari < min_amount:
                                    if 'SCALE-OUT' in kapanma_sebebi:
                                        print(f"  ⚠️ Kısmi kapanış miktarı ({kapanma_miktari}) Binance limitinden ({min_amount}) küçük. Kısmi kapanış atlanıyor.")
                                        if detay_key in ctx['aktif_islemler_detay']:
                                            _detay_kaydet(ctx['aktif_islemler_detay'])
                                        continue # Sonraki pozisyona geç
                                    else:
                                        kapanma_miktari = min_amount # Tam kapanışsa min_amount ile zorla

                                # ADIM 3.8: Miktar geçerliyse açık emirleri temizle.
                                # Scale-out Binance minimumunun altındaysa buraya gelinmez; mevcut stoplar korunur.
                                iptal_sayisi = 0
                                algo_temizlik = cancel_symbol_orders(ctx['borsa'], sembol)
                                if algo_temizlik.get('algo'):
                                    iptal_sayisi += 1
                                try:
                                    acik_emirler = ctx['borsa'].fetch_open_orders(sembol)
                                    for emir in acik_emirler:
                                        try:
                                            ctx['borsa'].cancel_order(emir['id'], sembol)
                                            iptal_sayisi += 1
                                        except Exception as ce:
                                            print(f"  ⚠️ Emir iptal hatası ({emir.get('id','?')}): {ce}")
                                except Exception as fe:
                                    print(f"  ⚠️ Emir listesi alınamadı: {fe}")

                                try:
                                    ctx['borsa'].cancel_all_orders(sembol)
                                    iptal_sayisi += 1
                                except:
                                    pass

                                try:
                                    market_id = ctx['borsa'].market_id(sembol)
                                    ctx['borsa'].fapiPrivateDeleteAllOpenOrders({'symbol': market_id})
                                except Exception as e:
                                    print(f"  ⚠️ Özel iptal uyarısı: {e}")

                                if iptal_sayisi > 0:
                                    print(f"  🧹 Açık emirler temizlendi. 3sn bekleniyor...")
                                    time.sleep(3)

                                
                                # ADIM 4: Market emri gönder (Parçalı Kapanış Desteğiyle)
                                kalan_miktar = kapanma_miktari
                                try:
                                    while kalan_miktar > 0:
                                        suan_kapatilacak = min(kalan_miktar, max_qty)
                                        _kapatma_emri_gonder(
                                            ctx['borsa'], sembol, zit_yon, suan_kapatilacak,
                                            referans_fiyat=guncel_fiyat, reduce_only=True
                                        )
                                        # Kayan noktalı sayı sorunlarını engellemek için round kullanıyoruz
                                        kalan_miktar = round(kalan_miktar - suan_kapatilacak, 6)
                                        if kalan_miktar > 0: time.sleep(0.5)
                                        
                                except Exception as emir_hata:
                                    hata_str = str(emir_hata)
                                    if '-2022' in hata_str:
                                        try:
                                            kontrol_miktari = _pozisyon_miktari_cek(ctx['borsa'], p.get('symbol', sembol))
                                        except Exception as verify_err:
                                            print(f"  [EXIT] {sembol} pozisyon dogrulanamadi; hafiza korunuyor: {verify_err}")
                                            continue
                                        if kontrol_miktari > 0:
                                            try:
                                                _kapatma_emri_gonder(
                                                    ctx['borsa'], sembol, zit_yon, kontrol_miktari,
                                                    referans_fiyat=guncel_fiyat, reduce_only=True
                                                )
                                                time.sleep(0.5)
                                                kontrol_miktari = _pozisyon_miktari_cek(ctx['borsa'], p.get('symbol', sembol))
                                                if kontrol_miktari > 0:
                                                    print(f"  [EXIT] {sembol} reduce-only sonrasi hala acik; hafiza korunuyor.")
                                                    continue
                                            except Exception as retry_err:
                                                print(f"  [EXIT] {sembol} reduce-only tekrar denemesi basarisiz; hafiza korunuyor: {retry_err}")
                                                continue
                                        if kontrol_miktari == 0:
                                            print(f"  ✅ {sembol} pozisyonu kapali olarak API'den dogrulandi.")
                                            for tk in tum_temizlik_keyleri:
                                                if tk in ctx['aktif_islemler_detay']:
                                                    del ctx['aktif_islemler_detay'][tk]
                                            _detay_kaydet(ctx['aktif_islemler_detay'])
                                            ctx['_DEMO_CACHE']['pozisyonlar'] = [
                                                (cp, ca) for cp, ca in ctx['_DEMO_CACHE'].get('pozisyonlar', [])
                                                if cp.get('symbol') != p.get('symbol')
                                            ]
                                            ctx['COOLDOWN_DICT'][sembol] = datetime.now()
                                            break
                                        print(f"  [EXIT] {sembol} -2022 sonrasi pozisyon hala acik; hafiza korunuyor.")
                                        continue
                                    else:
                                        print(f"  ⚠️ {sembol} Market kapatma hatası: {hata_str}")
                                        raise

                                try:
                                    dogrulanan_miktar = _pozisyon_miktari_cek(ctx['borsa'], p.get('symbol', sembol))
                                except Exception as verify_err:
                                    print(f"  [EXIT] {sembol} kapanis sonrasi pozisyon dogrulanamadi; hafiza korunuyor: {verify_err}")
                                    continue
                                if 'SCALE-OUT' in kapanma_sebebi:
                                    if dogrulanan_miktar >= gercek_miktar * 0.999:
                                        print(f"  [EXIT] {sembol} kismi kapanis borsada teyit edilemedi; tekrar denenecek.")
                                        continue
                                elif dogrulanan_miktar > max(min_amount, 1e-12):
                                    print(f"  [EXIT] {sembol} tam kapanis sonrasi {dogrulanan_miktar} pozisyon kaldi; kayit silinmiyor.")
                                    continue
                                
                                # Scale-Out ise sadece işaret koy, pozisyon hâlâ açık
                                if 'SCALE-OUT' in kapanma_sebebi:
                                    kalan_pozisyon_miktari = max(gercek_miktar - kapanma_miktari, 0)
                                    koruma_ok = _koruma_stop_emri_kur(
                                        ctx['borsa'], sembol, islem_yonu, kalan_pozisyon_miktari,
                                        sl_hedef, referans_fiyat=guncel_fiyat
                                    )
                                    if detay_key in ctx['aktif_islemler_detay']:
                                        ctx['aktif_islemler_detay'][detay_key]['Scale_Out_Yapildi'] = True
                                    if not koruma_ok:
                                        print(f"  [EXIT] {sembol} kalan pozisyon icin stop kurulamadi; reduce-only kapanis deneniyor.")
                                        if detay_key in ctx['aktif_islemler_detay']:
                                            ctx['aktif_islemler_detay'][detay_key]['Koruma_Bekliyor'] = True
                                            _detay_kaydet(ctx['aktif_islemler_detay'])
                                        if kalan_pozisyon_miktari > 0:
                                            try:
                                                _kapatma_emri_gonder(
                                                    ctx['borsa'], sembol, zit_yon, kalan_pozisyon_miktari,
                                                    referans_fiyat=guncel_fiyat, reduce_only=True
                                                )
                                            except Exception as kalan_hata:
                                                print(f"  [EXIT] {sembol} kalan reduce-only kapanis basarisiz; pozisyon korunuyor: {kalan_hata}")
                                        continue
                                    print(f"  ✅ {sembol} KISMİ KAPANDI (%40)! Kalan pozisyon sabit stop ile korunuyor.")
                                else:
                                    # Tam kapanış
                                    resmi_fatura = {}
                                    kayit_pnl = pnl
                                    try:
                                        time.sleep(0.8)
                                        fatura_bitis_ms = int(time.time() * 1000)
                                        resmi_fatura = sembol_gelir_net(
                                            ctx['borsa'], sembol, fatura_baslangic_ms, fatura_bitis_ms
                                        )
                                        if resmi_fatura.get('kayit_sayisi', 0) > 0:
                                            kayit_pnl = float(resmi_fatura.get('net', pnl))
                                    except Exception:
                                        resmi_fatura = {}
                                    print(f"  ✅ {sembol} TAMAMEN KAPATILDI! PNL: {kayit_pnl:+.3f}$ (%{pnl_yuzde:.2f})")
                                    if detay_key in ctx['aktif_islemler_detay'] and isinstance(ctx['aktif_islemler_detay'][detay_key], dict):
                                        ctx['aktif_islemler_detay'][detay_key]['Son_Kapanma_Sebebi'] = kapanma_sebebi
                                        ctx['aktif_islemler_detay'][detay_key]['Binance_Fatura'] = resmi_fatura
                                    
                                    islem_kaydet(sembol, 'TESTNET', islem_yonu,
                                        round(giris_fiyat, 6), round(guncel_fiyat, 6),
                                        round(kayit_pnl, 2), round(pnl_yuzde, 2), round(ai_skoru, 2),
                                        ctx['aktif_islemler_detay'])
                                    
                                    ctx['COOLDOWN_DICT'][sembol] = datetime.now()
                                    ctx['SON_ISLEMLER_PNL_DEMO'].append(kayit_pnl)
                                    if len(ctx['SON_ISLEMLER_PNL_DEMO']) > 10:
                                        ctx['SON_ISLEMLER_PNL_DEMO'].pop(0)
                                    if kayit_pnl > 0:
                                        ctx['performans']['kazanc'] += 1
                                        ctx['DEMO_ARDISIK_ZARAR'] = 0
                                    else:
                                        ctx['performans']['kayip'] += 1
                                        ctx['DEMO_ARDISIK_ZARAR'] += 1
                                    try:
                                        sembol_zararini_isle(ctx, sembol, kayit_pnl, kapanma_sebebi)
                                    except Exception as sg_hata:
                                        print(f"  [SYMBOL GUARD] {sembol} zarar isleme atlandi: {sg_hata}")
                                    
                                    # Hafızayı temizle
                                    for tk in tum_temizlik_keyleri:
                                        if tk in ctx['aktif_islemler_detay']:
                                            del ctx['aktif_islemler_detay'][tk]
                                    _detay_kaydet(ctx['aktif_islemler_detay'])  # Temizliği diske yaz
                                    
                            except Exception as e:
                                hata_mesaji = str(e)
                                # -2022 buraya kadar gelirse de yakala (güvenlik katmanı)
                                if '-2022' in hata_mesaji:
                                    try:
                                        kontrol_miktari = _pozisyon_miktari_cek(ctx['borsa'], p.get('symbol', sembol))
                                    except Exception as verify_err:
                                        print(f"  [EXIT] {sembol} dis katman dogrulamasi basarisiz; hafiza korunuyor: {verify_err}")
                                        continue
                                    if kontrol_miktari > 0:
                                        try:
                                            _kapatma_emri_gonder(
                                                ctx['borsa'], sembol, zit_yon, kontrol_miktari,
                                                referans_fiyat=guncel_fiyat, reduce_only=True
                                            )
                                            time.sleep(0.5)
                                            if _pozisyon_miktari_cek(ctx['borsa'], p.get('symbol', sembol)) > 0:
                                                print(f"  [EXIT] {sembol} dis katmanda hala acik; hafiza korunuyor.")
                                                continue
                                        except Exception as retry_err:
                                            print(f"  [EXIT] {sembol} dis katman reduce-only basarisiz; hafiza korunuyor: {retry_err}")
                                            continue
                                    # reduceOnly bypass dene (dış katman)
                                    try:
                                        _kapatma_emri_gonder(
                                            ctx['borsa'], sembol, zit_yon, kapanma_miktari,
                                            referans_fiyat=guncel_fiyat, reduce_only=True
                                        )
                                        print(f"  ✅ {sembol} dış katman bypass ile kapatıldı!")
                                    except:
                                        print(f"  ℹ️ {sembol} zaten kapalı (dış katman).")
                                    for tk in tum_temizlik_keyleri:
                                        if tk in ctx['aktif_islemler_detay']:
                                            del ctx['aktif_islemler_detay'][tk]
                                    _detay_kaydet(ctx['aktif_islemler_detay'])
                                    ctx['_DEMO_CACHE']['pozisyonlar'] = [
                                        (cp, ca) for cp, ca in ctx['_DEMO_CACHE'].get('pozisyonlar', [])
                                        if cp.get('symbol') != p.get('symbol')
                                    ]
                                else:
                                    print(f"  ❌ Çıkış Motoru Hatası ({sembol}): {hata_mesaji}")
                                    print(f"  ⚠️ Lütfen acil müdahale et!")
                                    
                                    # SPAM KORUMASI: Aynı sembol için hatayı 30 dakikada (1800 sn) bir kez yolla
                                    if 'TEL_HATA_CACHE' not in globals(): globals()['TEL_HATA_CACHE'] = {}
                                    simdi = time.time()
                                    if sembol not in globals()['TEL_HATA_CACHE'] or simdi - globals()['TEL_HATA_CACHE'][sembol] > 1800:
                                        globals()['TEL_HATA_CACHE'][sembol] = simdi
                                        telegrama_gonder(f"❌ Çıkış Motoru Hatası ({sembol}):\n{hata_mesaji}\n\n⚠️ Bu hata susturuldu (30dk boyunca tekrar bildirim gelmeyecek).")
                    

                    # Yön tespiti
                    islem_yeri = p.get('positionSide', '').upper()
                    if islem_yeri == 'LONG':
                        yon_str = "🟢 LONG"
                    elif islem_yeri == 'SHORT':
                        yon_str = "🔴 SHORT"
                    else:
                        yon_str = "🟢 LONG" if amt > 0 else "🔴 SHORT"
                        
                    print(f" [{hesap_t}] {sembol:<12} | {yon_str} | K/Z: {pnl:+.2f} USDT")
                
                print("-" * 50)

            # --- KASA DURUMU (Her zaman basılır - Commander Header için) ---
            wallet_demo = float(_demo_bakiye_ozeti.get('wallet', 0.0) or bakiye_demo or 0.0)
            equity_demo = float(_demo_bakiye_ozeti.get('equity', 0.0) or (wallet_demo + toplam_pnl_demo))
            
            # LIVE hesabı için bakiye_live = CCXT total = Margin Balance
            equity_live = bakiye_live
            wallet_live = bakiye_live - toplam_pnl_live
            ctx['KASA_DURUM']['DEMO_KASA'] = wallet_demo
            ctx['KASA_DURUM']['DEMO_EQUITY'] = equity_demo
            ctx['KASA_DURUM']['LIVE_KASA'] = wallet_live
            ctx['KASA_DURUM']['LIVE_EQUITY'] = equity_live
            _gunluk_risk_guncelle("DEMO", wallet_demo, equity_demo)
            if ctx['LIVE_MOD_AKTIF']:
                _gunluk_risk_guncelle("LIVE", wallet_live, equity_live)
            
            # DEMO başlangıç sermayesi henüz ayarlanmadıysa, ilk okunan değeri kullan
            if ctx['BASLANGIC_SERMAYE_DEMO'] == 0.0 and wallet_demo > 0:
                ctx['BASLANGIC_SERMAYE_DEMO'] = wallet_demo
            
            # Gercek net K/Z: Binance income ledger + acik PnL farki.
            gercek_pnl_live = equity_live - ctx['BASLANGIC_SERMAYE_LIVE'] if equity_live > 0 else 0.0
            muhasebe_ozeti = {}
            try:
                muhasebe_ozeti = gelir_ozeti_hesapla(
                    ctx['borsa'],
                    ctx.get('MUHASEBE_BASLANGIC_MS'),
                    baseline_open_pnl=ctx.get('MUHASEBE_BASLANGIC_ACIK_PNL_DEMO', 0.0),
                    current_open_pnl=toplam_pnl_demo,
                    wallet=wallet_demo,
                    baseline_wallet=ctx.get('BASLANGIC_SERMAYE_DEMO', 0.0),
                )
                ctx['_DEMO_CACHE']['muhasebe_ozeti'] = muhasebe_ozeti
            except Exception as muhasebe_hata:
                muhasebe_ozeti = ctx['_DEMO_CACHE'].get('muhasebe_ozeti', {}) or {}
                muhasebe_ozeti = {**muhasebe_ozeti, "son_hata": str(muhasebe_hata)}
            gercek_pnl_demo = float(
                muhasebe_ozeti.get(
                    'net_pnl_mtm',
                    (equity_demo - ctx['BASLANGIC_SERMAYE_DEMO']) if ctx['BASLANGIC_SERMAYE_DEMO'] > 0 else 0.0,
                )
            )
            gerceklesmis_pnl_demo = float(muhasebe_ozeti.get('realized_net', 0.0) or 0.0)
            
            # Not: Commander Interceptor "$" işaretini ve "|" ayırıcıyı arar
            print(f" 🏦 [DEMO] Kasa: ${wallet_demo:.2f} | K/Z: ${gercek_pnl_demo:+.2f} | Realized: ${gerceklesmis_pnl_demo:+.2f} | VARLIK: ${equity_demo:.2f}")
            if ctx['LIVE_MOD_AKTIF']:
                print(f" 🏦 [LIVE] Kasa: ${wallet_live:.2f} | K/Z: ${gercek_pnl_live:+.2f} | VARLIK: ${equity_live:.2f}")
            
            # --- Performans Karnesi ---
            toplam_islem = ctx['performans']['kazanc'] + ctx['performans']['kayip']
            win_rate = (ctx['performans']['kazanc'] / toplam_islem * 100) if toplam_islem > 0 else 0
            print(f"📊 PERFORMANS: Kazanma Oranı: %{win_rate:.0f} | Başarılı: {ctx['performans']['kazanc']} | Başarısız: {ctx['performans']['kayip']}")
            print("="*50 + "\n")
            status_yaz({
                "demo_kasa": round(float(wallet_demo), 2),
                "demo_wallet": round(float(wallet_demo), 2),
                "demo_equity": round(float(equity_demo), 2),
                "demo_pnl": round(float(gercek_pnl_demo), 2),
                "demo_realized_pnl": round(float(gerceklesmis_pnl_demo), 2),
                "demo_unrealized_pnl": round(float(toplam_pnl_demo), 2),
                "demo_muhasebe": muhasebe_ozeti,
                "live_kasa": round(float(wallet_live), 2),
                "live_equity": round(float(equity_live), 2),
                "live_mod": ctx['LIVE_MOD_AKTIF'],
                "live_tetik": ctx['ALIM_SATIM_TETIGI_ACIK'],
                "demo_profil": DEMO_CALISMA_PROFILI,
                "demo_live_shadow": DEMO_LIVE_SHADOW_AKTIF,
                "short_islem_aktif": SHORT_ISLEM_AKTIF,
                "performans": {
                    "win_rate": round(float(win_rate), 2),
                    "kazanc": ctx['performans']['kazanc'],
                    "kayip": ctx['performans']['kayip'],
                    "demo_pnl": round(float(gercek_pnl_demo), 2),
                    "demo_realized_pnl": round(float(gerceklesmis_pnl_demo), 2),
                    "demo_unrealized_pnl": round(float(toplam_pnl_demo), 2),
                    "live_pnl": round(float(gercek_pnl_live), 2),
                },
                "gunluk_risk": _gunluk_risk_ozeti(),
            })
            
            ctx['onceki_pozisyonlar'] = yeni_pozisyonlar
            
        except Exception as e:
            status_yaz({
                "son_hata": {
                    "modul": "pozisyon_takip_paneli",
                    "mesaj": str(e),
                    "zaman": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }
            }, event={"tip": "hata", "mesaj": f"pozisyon_takip_paneli: {e}"})
        
        time.sleep(30)

