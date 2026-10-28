"""
signal_engine.py — Sinyal analiz motoru.
Coin'i analiz eder, XGBoost tahmini yapar, filtreler uygular ve sinyal raporu döndürür.
main.py'den ayrıştırıldı (modülerleştirme sprint'i).
"""
from datetime import datetime
from tarayici import veri_getir_dortlu
from analist import korku_acgozluluk_getir, makro_volatilite_beklentisi
from config import (
    REF, MAX_ATR_FIYAT_YUZDESI, DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF,
    SHORT_ISLEM_AKTIF, MIN_MODEL_WALK_FORWARD_SKORU, MODEL_KALITE_KAPISI_AKTIF,
    MODEL_KALITE_BILINMEYENI_ENGELLE, MODEL_KALITE_SARI_ESIK,
    MODEL_KALITE_SARI_MARGIN_CARPANI, MAX_DEMO_MARGIN_YUZDESI,
    MIN_MODEL_SCHEMA_VERSION,
    MODEL_RECENT_MIN_SIGNAL, MODEL_RECENT_MAX_BRIER,
    MODEL_RECENT_MIN_BRIER_SKILL,
    MODEL_RECENT_MIN_PROFIT_FACTOR,
    DEMO_MIN_MARGIN_YUZDESI, HEDGE_SNIPER_MODU_AKTIF, HEDGE_MIN_RR,
    HEDGE_MIN_GUVEN, HEDGE_MIN_ADX, HEDGE_MAX_CHOP,
    HEDGE_MIN_VOLUME_ZSCORE, HEDGE_ESCAPE_GUVEN, HEDGE_ESCAPE_RR,
    HEDGE_MARGIN_CARPANI,
)
from risk_manager import (
    _ret_raporu, _ret_nedeni_kaydet, _ret_kategorisi, _ret_kategorileri,
    _veri_kalitesi_kontrol, _model_kalite_oku,
)
from rejim import piyasa_rejimi_belirle


def analiz_motoru(
    hedef_coin,
    beyin,
    karantina_listesi,
    coin_zarar_sayaci,
    kara_liste,
    golge_beyin=None,
    model_karsilastirici=None,
    v6_1h_beyin=None,
):
    """
    Coin'i analiz eder ve bir sonuç raporu döndürür.
    success: True ise tüm filtrelerden geçmiş ve işlem açılabilir demektir.

    Args:
        hedef_coin: Analiz edilecek coin sembolü (örn: 'BTC/USDT')
        beyin: BeyinMotoru instance'ı
        karantina_listesi: {sembol: karantina_bitis_datetime} dict'i
        coin_zarar_sayaci: {sembol: ardisik_zarar_sayisi} dict'i
        kara_liste: Kalıcı yasaklı pariteler set'i
    """
    guncel, tahmin_olasilik, yon, dinamik_esik = None, None, None, 0.48
    df = None
    sl, tp, rr = 0, 0, 0
    btc_dom = 50.0

    try:
        if makro_volatilite_beklentisi():
            return _ret_raporu(hedef_coin, "Makro volatilite filtresi")

        try:
            beyin_tf = getattr(beyin, 'base_timeframe', '1h')
            schema_ver = getattr(beyin, 'label_schema_version', 5)
            df = veri_getir_dortlu(hedef_coin, REF, timeframe=beyin_tf, feature_schema_version=schema_ver)
        except Exception as e:
            return _ret_raporu(hedef_coin, f"Veri çekim hatası: {e}")

        if df is None or df.empty:
            return _ret_raporu(hedef_coin, "Veri yok")

        # --- KARANTİNA & KARA LİSTE KONTROLÜ ---
        if hedef_coin in kara_liste:
            return _ret_raporu(hedef_coin, "Kara liste")
        if hedef_coin in karantina_listesi:
            if datetime.now() < karantina_listesi[hedef_coin]:
                return _ret_raporu(hedef_coin, "Karantina aktif")
            else:
                del karantina_listesi[hedef_coin]
                if hedef_coin in coin_zarar_sayaci: del coin_zarar_sayaci[hedef_coin]
                print(f"✅ [KARANTİNA BİTTİ] {hedef_coin} tekrar taranmaya başlandı.")

        # Sprint 3: Order Book Dengesizlik Verisi (XGBoost Feature)
        try:
            from tarayici import emir_defteri_analizi
            df['OB_Imbalance'] = emir_defteri_analizi(hedef_coin)
        except Exception:
            df['OB_Imbalance'] = 0.0

        features = list(getattr(beyin, 'crypto_features', [])) or ['Hedef_Ret', 'Ref_Ret', 'RSI', 'MACD', 'Vol_Ret', 'Korelasyon', 'OBV', 'BB_Width', 'MFI', 'VP_Sapma', 'ADX', 'EMA_Slope']
        kontrol_kolonlari = list(dict.fromkeys(features + ['open', 'Hedef_Close', 'ATR', 'volume']))
        veri_ok, veri_red, veri_kalite = _veri_kalitesi_kontrol(hedef_coin, df, kontrol_kolonlari)
        if not veri_ok:
            print(f"⚠️ Veri Hatası ({hedef_coin}): {veri_red}")
            return _ret_raporu(hedef_coin, veri_red, ekstra={'veri_kalite': veri_kalite})

        try:
            tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None:
                beyin.model_egit(hedef_coin, df, is_crypto=True)
                tahmin_olasilik = beyin.tahmin_et(hedef_coin, df, is_crypto=True)
            if tahmin_olasilik is None:
                return _ret_raporu(hedef_coin, "Model tahmini üretilemedi", ekstra={'veri_kalite': veri_kalite})
        except Exception as e:
            return _ret_raporu(hedef_coin, f"Model hatası: {e}", ekstra={'veri_kalite': veri_kalite})

        model_kalite = _model_kalite_oku(hedef_coin, is_crypto=True)

        guncel = float(df['Hedef_Close'].iloc[-1])
        if golge_beyin is not None and model_karsilastirici is not None:
            try:
                golge_olasilik = golge_beyin.tahmin_et(hedef_coin, df, is_crypto=True)
                # V6 1h model tahmini
                v6_1h_olasilik = None
                if v6_1h_beyin is not None:
                    try:
                        v6_1h_olasilik = v6_1h_beyin.tahmin_et(hedef_coin, df, is_crypto=True)
                    except Exception as v6_err:
                        print(f"[MODEL A/B] {hedef_coin} 200/3 v6_1h tahmini atlandi: {v6_err}")
                if golge_olasilik is not None:
                    model_karsilastirici.record_prediction(
                        hedef_coin,
                        guncel,
                        tahmin_olasilik,
                        golge_olasilik,
                        v6_1h_probability=v6_1h_olasilik,
                        regime=piyasa_rejimi_belirle(df.iloc[-1]),
                        decision_bar_open=df.index[-1],
                        feature_schema_version=df.attrs.get(
                            'feature_schema_version'
                        ),
                        outcome_contract_id=getattr(
                            getattr(beyin, 'outcome_spec', None),
                            'contract_id',
                            None,
                        ),
                        shadow_outcome_contract_id=getattr(
                            getattr(golge_beyin, 'outcome_spec', None),
                            'contract_id',
                            None,
                        ),
                        v6_1h_outcome_contract_id=getattr(
                            getattr(v6_1h_beyin, 'outcome_spec', None),
                            'contract_id',
                            None,
                        ) if v6_1h_beyin else None,
                    )
            except Exception as golge_hata:
                print(f"[MODEL A/B] {hedef_coin} 400/5 golge tahmini atlandi: {golge_hata}")
        atr = float(df['ATR'].iloc[-1])
        volat_kat = (atr / guncel) * 100
        if volat_kat > MAX_ATR_FIYAT_YUZDESI:
            return _ret_raporu(
                hedef_coin,
                f"Volatilite anomalisi ATR/Fiyat(%{volat_kat:.1f}>{MAX_ATR_FIYAT_YUZDESI:.1f})",
                fiyat=guncel,
                ekstra={'veri_kalite': veri_kalite}
            )

        # XGBoost giriş eşiği — %48.0 (Agresif mod: daha fazla sinyal üretilmesi için gevşetildi)
        dinamik_esik = 0.480

        guven_skoru_yuzde = tahmin_olasilik * 100
        if tahmin_olasilik >= dinamik_esik: yon = "YÜKSELİŞ 🚀"
        elif tahmin_olasilik <= (1.0 - dinamik_esik):
            yon = "DÜŞÜŞ 📉"
            guven_skoru_yuzde = 100 - (tahmin_olasilik * 100)
        else:
            yon = "NÖTR ⚖️"
            if tahmin_olasilik < 0.5: guven_skoru_yuzde = (1.0 - tahmin_olasilik) * 100

        # Rapor Hazırla (Base Sözlük)
        rapor = {
            'coin': hedef_coin, 'live_ok': False, 'demo_ok': False,
            'guven_skoru': guven_skoru_yuzde, 'yon': yon, 'fiyat': guncel,
            'margin_override': DEMO_MIN_MARGIN_YUZDESI,
            'dinamik_esik': dinamik_esik * 100,
            'veri_kalite': veri_kalite,
            'model_aciklama': getattr(beyin, 'son_tahmin_aciklama', {}).get(hedef_coin, {}),
            'model_kalite': model_kalite,
            'min_model_walk_forward_skoru': MIN_MODEL_WALK_FORWARD_SKORU,
            'demo_profil': DEMO_CALISMA_PROFILI,
            'demo_live_shadow': DEMO_LIVE_SHADOW_AKTIF,
            'short_islem_aktif': SHORT_ISLEM_AKTIF,
        }

        if yon == "NÖTR ⚖️":
            rapor['success'] = False
            rapor['red_sebebi'] = f"Model nötr bölgede({tahmin_olasilik:.2f})"
            rapor['ret_kategori'] = _ret_kategorisi(rapor['red_sebebi'])
            rapor['ret_kategorileri'] = _ret_kategorileri(rapor['red_sebebi'])
            _ret_nedeni_kaydet(rapor['red_sebebi'])
            return rapor

        # --- TREND KALKANI (Trend Shield) ---
        from tarayici import ana_trend_getir, btc_kalkan_kontrol, ema_mesafe_kontrol
        ana_trend = ana_trend_getir(hedef_coin)

        # --- 🛡️ BTC KORELASYON KALKANI ---
        btc_yon = "NÖTR"
        if hedef_coin != 'BTC/USDT':
            btc_yon = btc_kalkan_kontrol()

        # --- 🎯 MARKET REGIME ADAPTIF ATR ÇARPANI ---
        volat_yuzde = (atr / guncel) * 100
        if volat_yuzde > 1.5:
            atr_carpani = 3.0
            tp_mult = 2.5
        elif volat_yuzde < 0.5:
            atr_carpani = 1.8
            tp_mult = 3.5
        else:
            atr_carpani = 2.5
            tp_mult = 3.0

        min_guvenli_mesafe = guncel * 0.01
        hesaplanan_mesafe = atr * atr_carpani
        final_mesafe = max(hesaplanan_mesafe, min_guvenli_mesafe)
        if "YÜKSELİŞ" in yon:
            sl, tp = guncel - final_mesafe, guncel + (final_mesafe * tp_mult)
            rr = (tp - guncel) / (guncel - sl) if (guncel - sl) != 0 else 0
        else:
            sl, tp = guncel + final_mesafe, guncel - (final_mesafe * tp_mult)
            rr = (guncel - tp) / (sl - guncel) if (sl - guncel) != 0 else 0

        rapor.update({'tp': tp, 'sl': sl, 'rr': rr})

        # Base Filters
        son_bar = df.iloc[-1]
        rejim_etiketi = piyasa_rejimi_belirle(son_bar, btc_kalkan_aktif_mi=(btc_yon == "DOWN"))
        son_adx = son_bar.get('ADX', 25.0)
        son_chop = son_bar.get('CHOP', 50.0)
        fg_skor, _ = korku_acgozluluk_getir()

        if 'volume' in df.columns:
            hacim_sma = df['volume'].rolling(window=20).mean().iloc[-1]
            anlik_hacim = df['volume'].iloc[-1]
            hacim_patlamasi = (anlik_hacim / hacim_sma) - 1.0 if hacim_sma > 0 else 0
        else:
            hacim_patlamasi = 0

        vol_zscore = df['Volume_ZScore'].iloc[-1] if 'Volume_ZScore' in df.columns else 0.0

        # =========================================================
        # BİFURCATION (LIVE vs DEMO ŞARTLARI) — v3.0 AI-Driven
        # =========================================================
        _live_prob = tahmin_olasilik if "YÜKSELİŞ" in yon else (1 - tahmin_olasilik)
        ret_nedenleri = []
        if rr < 1.2:
            ret_nedenleri.append(f"RR({rr:.2f}<1.2)")
        elif rr < 1.5:
            ret_nedenleri.append(f"LIVE_RR({rr:.2f}<1.5)")
        if _live_prob < 0.58:
            ret_nedenleri.append(f"LIVE_Güven({_live_prob*100:.1f}<58)")

        live_ok = (
            rr >= 1.5 and
            _live_prob >= 0.58
        )

        # DEMO Şartları (Hedge Fund Gölge Modu — %53.5+ güven ve RR>=1.3 ile sanal işlem takibi)
        _demo_prob = tahmin_olasilik if "YÜKSELİŞ" in yon else (1 - tahmin_olasilik)
        demo_rr_min = 1.3 if DEMO_LIVE_SHADOW_AKTIF else 1.2
        demo_guven_min = dinamik_esik  # Agresif mod: demo güven eşiği = dinamik_esik (0.48)
        demo_ret_etiket = "DEMO_SHADOW" if DEMO_LIVE_SHADOW_AKTIF else "DEMO_KESIF"
        if rr < demo_rr_min:
            ret_nedenleri.append(f"{demo_ret_etiket}_RR({rr:.2f}<{demo_rr_min:.1f})")
        if _demo_prob < demo_guven_min:
            ret_nedenleri.append(f"{demo_ret_etiket}_Guven({_demo_prob*100:.1f}<{demo_guven_min*100:.0f})")
        demo_ok = (
            rr >= demo_rr_min and
            _demo_prob >= demo_guven_min
        )

        model_kalite_bolgesi = "bilinmiyor"
        model_kalite_sari = False
        if MODEL_KALITE_KAPISI_AKTIF:
            wf_skor_raw = model_kalite.get("walk_forward_skoru")
            wf_skor = None
            try:
                wf_skor = float(wf_skor_raw) if wf_skor_raw is not None else None
            except Exception:
                wf_skor = None

            model_kalite_ret = None
            if wf_skor is None and MODEL_KALITE_BILINMEYENI_ENGELLE:
                model_kalite_ret = "MODEL_KALITE_BILINMIYOR"
                model_kalite_bolgesi = "bilinmiyor"
            elif wf_skor is not None:
                if wf_skor < MIN_MODEL_WALK_FORWARD_SKORU:
                    model_kalite_ret = f"MODEL_KALITE_KIRMIZI({wf_skor:.3f}<{MIN_MODEL_WALK_FORWARD_SKORU:.2f})"
                    model_kalite_bolgesi = "kirmizi"
                elif wf_skor < MODEL_KALITE_SARI_ESIK:
                    model_kalite_sari = True
                    model_kalite_bolgesi = "sari"
                else:
                    model_kalite_bolgesi = "yesil"

            recent_reasons = []
            try:
                model_schema = int(model_kalite.get("model_schema_version") or 0)
                if model_schema < MIN_MODEL_SCHEMA_VERSION:
                    recent_reasons.append(
                        f"schema={model_schema}<{MIN_MODEL_SCHEMA_VERSION}"
                    )
                recent_signal_count = int(model_kalite.get("recent_signal_count") or 0)
                recent_brier = float(model_kalite.get("recent_brier_score"))
                recent_holdout_rows = int(model_kalite.get("recent_holdout_rows") or 0)
                recent_profitable_up = int(model_kalite.get("recent_profitable_up_count") or 0)
                recent_net = float(model_kalite.get("recent_strategy_net_return"))
                recent_profit_factor = float(model_kalite.get("recent_strategy_profit_factor"))
                if recent_signal_count < MODEL_RECENT_MIN_SIGNAL:
                    recent_reasons.append(f"sinyal={recent_signal_count}<{MODEL_RECENT_MIN_SIGNAL}")
                if recent_brier > MODEL_RECENT_MAX_BRIER:
                    recent_reasons.append(f"brier={recent_brier:.3f}>{MODEL_RECENT_MAX_BRIER:.2f}")
                if 0 < recent_profitable_up < recent_holdout_rows:
                    prevalence = recent_profitable_up / recent_holdout_rows
                    brier_baseline = prevalence * (1.0 - prevalence)
                    brier_skill = 1.0 - (recent_brier / brier_baseline)
                    if brier_skill < MODEL_RECENT_MIN_BRIER_SKILL:
                        recent_reasons.append(
                            f"brier_skill={brier_skill:.3f}<{MODEL_RECENT_MIN_BRIER_SKILL:.3f}"
                        )
                else:
                    recent_reasons.append("brier_baseline_eksik")
                if recent_net <= 0:
                    recent_reasons.append(f"net={recent_net*100:+.2f}%")
                if recent_profit_factor < MODEL_RECENT_MIN_PROFIT_FACTOR:
                    recent_reasons.append(
                        f"pf={recent_profit_factor:.2f}<{MODEL_RECENT_MIN_PROFIT_FACTOR:.2f}"
                    )
            except (TypeError, ValueError):
                recent_reasons.append("metrik_eksik")

            if recent_reasons:
                model_kalite_ret = "MODEL_RECENT_BASARISIZ(" + ",".join(recent_reasons) + ")"
                model_kalite_bolgesi = "kirmizi"

            if model_kalite_ret:
                if live_ok:
                    live_ok = False
                    ret_nedenleri.append(f"{model_kalite_ret}(LIVE)")
                if DEMO_LIVE_SHADOW_AKTIF:
                    # Demo modda MODEL_RECENT sinyali engellemez, sadece etiketler (ölüm sarmalı kırıcı)
                    ret_nedenleri.append(f"DEMO_SHADOW_{model_kalite_ret}(BILGI)")
            elif model_kalite_sari:
                if live_ok:
                    live_ok = False
                    ret_nedenleri.append(f"MODEL_KALITE_SARI(LIVE:{wf_skor:.3f}<{MODEL_KALITE_SARI_ESIK:.2f})")
                if DEMO_LIVE_SHADOW_AKTIF:
                    # Agresif mod: sarı bölge demo'yu engellemez, sadece margin küçültür
                    ret_nedenleri.append(f"DEMO_SHADOW_MODEL_KALITE_SARI({wf_skor:.3f}<{MODEL_KALITE_SARI_ESIK:.2f})(BILGI)")
                elif demo_ok:
                    demo_ok = False
                    ret_nedenleri.append(f"DEMO_SHADOW_MODEL_KALITE_SARI({wf_skor:.3f}<{MODEL_KALITE_SARI_ESIK:.2f})")

        rapor['model_kalite_bolgesi'] = model_kalite_bolgesi
        rapor['model_kalite_sari'] = model_kalite_sari

        # Trend Kalkanı
        if live_ok:
            if "YÜKSELİŞ" in yon and ana_trend == "DOWN":
                live_ok = False
                ret_nedenleri.append("LIVE_AnaTrendZıt(DOWN)")
            elif "DÜŞÜŞ" in yon and ana_trend == "UP":
                live_ok = False
                ret_nedenleri.append("LIVE_AnaTrendZıt(UP)")
            if "YÜKSELİŞ" in yon and btc_yon == "DOWN":
                live_ok = False
                ret_nedenleri.append("LIVE_BTCZıt(DOWN)")
            elif "DÜŞÜŞ" in yon and btc_yon == "UP":
                live_ok = False
                ret_nedenleri.append("LIVE_BTCZıt(UP)")
        if demo_ok:
            if "YÜKSELİŞ" in yon and ana_trend == "DOWN":
                demo_ok = False
                ret_nedenleri.append("DEMO_AnaTrendZit(DOWN)")
            elif "DÜŞÜŞ" in yon and ana_trend == "UP":
                demo_ok = False
                ret_nedenleri.append("DEMO_AnaTrendZit(UP)")

        if DEMO_LIVE_SHADOW_AKTIF:
            demo_shadow_nedenleri = []
            if "YÜKSELİŞ" in yon and ana_trend == "DOWN":
                demo_shadow_nedenleri.append("DEMO_SHADOW_AnaTrendZit(DOWN)")
            elif "DÜŞÜŞ" in yon and ana_trend == "UP":
                demo_shadow_nedenleri.append("DEMO_SHADOW_AnaTrendZit(UP)")
            if "YÜKSELİŞ" in yon and btc_yon == "DOWN":
                demo_shadow_nedenleri.append("DEMO_SHADOW_BTCZit(DOWN)")
            elif "DÜŞÜŞ" in yon and btc_yon == "UP":
                demo_shadow_nedenleri.append("DEMO_SHADOW_BTCZit(UP)")
            demo_ok = demo_ok and len(demo_shadow_nedenleri) == 0
            ret_nedenleri.extend(demo_shadow_nedenleri)

        if "DÜŞÜŞ" in yon and not SHORT_ISLEM_AKTIF:
            if live_ok:
                live_ok = False
                ret_nedenleri.append("SHORT_KAPALI(LIVE)")
            if DEMO_LIVE_SHADOW_AKTIF and demo_ok:
                demo_ok = False
                ret_nedenleri.append("DEMO_SHADOW_SHORT_KAPALI")

        # --- FUNDING RATE KALABALIK FİLTRESİ ---
        son_funding = df['Funding_Rate'].iloc[-1] if 'Funding_Rate' in df.columns else 0.0001
        if son_funding > 0.001 and "YÜKSELİŞ" in yon:
            live_ok = False
            demo_ok = False
            ret_nedenleri.append(f"Funding_Long_Kalabalık({son_funding:.4f})")
        elif son_funding < -0.001 and "DÜŞÜŞ" in yon:
            live_ok = False
            demo_ok = False
            ret_nedenleri.append(f"Funding_Short_Kalabalık({son_funding:.4f})")

        hedge_skor = 0
        if HEDGE_SNIPER_MODU_AKTIF:
            hedge_nedenleri = []
            if rr >= HEDGE_MIN_RR:
                hedge_skor += 2
            else:
                hedge_nedenleri.append(f"HEDGE_RR({rr:.2f}<{HEDGE_MIN_RR:.1f})")

            if guven_skoru_yuzde >= HEDGE_MIN_GUVEN:
                hedge_skor += 2
            else:
                hedge_nedenleri.append(f"HEDGE_Guven({guven_skoru_yuzde:.1f}<{HEDGE_MIN_GUVEN:.0f})")

            zayif_piyasa = 0
            if son_adx >= HEDGE_MIN_ADX:
                hedge_skor += 1
            else:
                zayif_piyasa += 1
                hedge_nedenleri.append(f"HEDGE_ADX({son_adx:.1f}<{HEDGE_MIN_ADX:.0f})")

            if son_chop <= HEDGE_MAX_CHOP:
                hedge_skor += 1
            else:
                zayif_piyasa += 1
                hedge_nedenleri.append(f"HEDGE_CHOP({son_chop:.1f}>{HEDGE_MAX_CHOP:.0f})")

            hacim_destegi = vol_zscore >= HEDGE_MIN_VOLUME_ZSCORE or hacim_patlamasi >= 0.05
            if hacim_destegi:
                hedge_skor += 1
            else:
                zayif_piyasa += 1
                hedge_nedenleri.append(f"HEDGE_Hacim(volZ={vol_zscore:.2f},pat={hacim_patlamasi:.2f})")

            guclu_istisna = guven_skoru_yuzde >= HEDGE_ESCAPE_GUVEN and rr >= HEDGE_ESCAPE_RR
            hedge_ret = (
                rr < HEDGE_MIN_RR
                or guven_skoru_yuzde < HEDGE_MIN_GUVEN
                or (zayif_piyasa >= 2 and not guclu_istisna)
            )
            if hedge_ret:
                live_ok = False
                demo_ok = False
                ret_nedenleri.extend(hedge_nedenleri)
            elif zayif_piyasa > 0:
                ret_nedenleri.append(f"HEDGE_Temkin(skor={hedge_skor}/7)")

        if not live_ok and not demo_ok:
            rapor['success'] = False
            rapor['live_ok'] = False
            rapor['demo_ok'] = False
            rapor['red_sebebi'] = " | ".join(ret_nedenleri) if ret_nedenleri else "Filtrelerden geçmedi"
            rapor['ret_kategori'] = _ret_kategorisi(rapor['red_sebebi'])
            rapor['ret_kategorileri'] = _ret_kategorileri(rapor['red_sebebi'])
            rapor['demo_rr_min'] = demo_rr_min
            rapor['demo_guven_min'] = demo_guven_min * 100
            rapor['model_kalite_bolgesi'] = model_kalite_bolgesi
            rapor['model_kalite_sari'] = model_kalite_sari
            rapor['hedge_sniper_modu'] = HEDGE_SNIPER_MODU_AKTIF
            rapor['hedge_skor'] = hedge_skor
            rapor['piyasa_kalite'] = {
                'rejim': rejim_etiketi,
                'adx': float(son_adx),
                'chop': float(son_chop),
                'volume_zscore': float(vol_zscore),
                'hacim_patlamasi': float(hacim_patlamasi),
                'funding': float(son_funding),
            }
            _ret_nedeni_kaydet(rapor['red_sebebi'])
            return rapor

        # =========================================================
        # DİNAMİK BÜTÇE (Güven Skoruna Göre Kademeli Pozisyon)
        # =========================================================
        p_kelly = tahmin_olasilik if "YÜKSELİŞ" in yon else (1.0 - tahmin_olasilik)
        kelly_orani = max(0, (p_kelly * rr - (1-p_kelly)) / rr) if rr > 0 else 0

        frac_kelly_live = max(0.01, min(0.95, kelly_orani))

        half_kelly = kelly_orani * 0.5
        frac_kelly_demo = min(
            MAX_DEMO_MARGIN_YUZDESI,
            max(DEMO_MIN_MARGIN_YUZDESI, half_kelly),
        )

        if model_kalite_sari:
            frac_kelly_demo = max(0.005, frac_kelly_demo * MODEL_KALITE_SARI_MARGIN_CARPANI)
        if HEDGE_SNIPER_MODU_AKTIF:
            frac_kelly_demo = max(DEMO_MIN_MARGIN_YUZDESI * 0.60, frac_kelly_demo * HEDGE_MARGIN_CARPANI)

        red_sebebi = " | ".join(ret_nedenleri)

        rapor.update({
            'success': True,
            'live_ok': live_ok,
            'demo_ok': demo_ok,
            'margin_override_live': frac_kelly_live,
            'margin_override_demo': frac_kelly_demo,
            'fg_skor': fg_skor,
            'dinamik_esik': dinamik_esik * 100,
            'demo_profil': DEMO_CALISMA_PROFILI,
            'demo_live_shadow': DEMO_LIVE_SHADOW_AKTIF,
            'short_islem_aktif': SHORT_ISLEM_AKTIF,
            'model_kalite_bolgesi': model_kalite_bolgesi,
            'model_kalite_sari': model_kalite_sari,
            'model_kalite_sari_margin_carpani': MODEL_KALITE_SARI_MARGIN_CARPANI,
            'demo_rr_min': demo_rr_min,
            'demo_guven_min': demo_guven_min * 100,
            'hedge_sniper_modu': HEDGE_SNIPER_MODU_AKTIF,
            'hedge_skor': hedge_skor,
            'piyasa_kalite': {
                'rejim': rejim_etiketi,
                'adx': float(son_adx),
                'chop': float(son_chop),
                'volume_zscore': float(vol_zscore),
                'hacim_patlamasi': float(hacim_patlamasi),
                'funding': float(son_funding),
            },
            'ret_kategori': _ret_kategorisi(red_sebebi) if red_sebebi else "",
            'ret_kategorileri': _ret_kategorileri(red_sebebi) if red_sebebi else [],
            'red_sebebi': red_sebebi
        })
        return rapor

    except Exception as e:
        print(f"⚠️ Analiz Hatası ({hedef_coin}): {e}")
        guven = 0.0
        try:
            if tahmin_olasilik is not None:
                guven = max(tahmin_olasilik, 1.0 - tahmin_olasilik) * 100
        except Exception:
            guven = 0.0
        return _ret_raporu(hedef_coin, f"Analiz hatası: {e}", guven_skoru=guven)
