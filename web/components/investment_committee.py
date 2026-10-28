"""
StockPredictionPro — Yatırım Komitesi, Bilanço & Katalizör Lab ve Piyasa Rejimi Motoru
- Mod #1: Yatırım Komitesi (Boğa / Baz / Ayı senaryoları, Tezi bozan koşul, Karar özeti)
- Mod #2 & Bölüm 3: 4 Faktörlü Çatışma Analizi (Momentum vs Değer, Kalite vs Risk)
- Mod #4: Katalizör & Bilanço Karnesi (Son bilançolarda ertesi gün ne yaptı? Beklenti fiyatlandı mı?)
- Mod #7: Piyasa Rejimi Motoru (SPY, SMH/QQQ, VIX ve Tahvil faizi ile piyasa havası)
- Mod #11: Alternatif Fırsat Kıyası (Aynı dönemde SPY veya Çip ETF'i SMH alsaydın ne olurdu?)
"""
from __future__ import annotations

from datetime import datetime
import numpy as np
import pandas as pd
import yfinance as yf

try:
    import streamlit as st
    _cache_data = st.cache_data
except Exception:
    def _cache_data(**_kwargs):
        def _wrap(fn):
            return fn
        return _wrap


@_cache_data(ttl=600, show_spinner=False)
def get_market_regime_summary() -> dict:
    """
    Piyasanın genel rejimini (Boğa, Seçici/Dalgalı, Düzeltme/Riskten Kaçış, Kriz)
    S&P 500 (SPY), Yarı İletkenler (SMH), Korku Endeksi (^VIX) ve ABD 10Y Faizi (^TNX)
    üzerinden sade Türkçe ile belirler.
    """
    try:
        tickers = ["SPY", "SMH", "^VIX", "^TNX"]
        raw = yf.download(tickers, period="1y", interval="1d", progress=False, group_by="ticker")

        def _get_close(sym: str) -> pd.Series:
            if sym in raw and "Close" in raw[sym]:
                return raw[sym]["Close"].dropna()
            return pd.Series(dtype=float)

        spy = _get_close("SPY")
        smh = _get_close("SMH")
        vix = _get_close("^VIX")
        tnx = _get_close("^TNX")

        spy_price = float(spy.iloc[-1]) if len(spy) else 0.0
        spy_sma50 = float(spy.rolling(50).mean().iloc[-1]) if len(spy) >= 50 else spy_price
        spy_sma200 = float(spy.rolling(200).mean().iloc[-1]) if len(spy) >= 200 else spy_price * 0.92
        spy_2w_ret = ((spy_price / float(spy.iloc[-11])) - 1.0) * 100.0 if len(spy) >= 11 else 0.0

        smh_price = float(smh.iloc[-1]) if len(smh) else 0.0
        smh_2w_ret = ((smh_price / float(smh.iloc[-11])) - 1.0) * 100.0 if len(smh) >= 11 else 0.0

        vix_val = float(vix.iloc[-1]) if len(vix) else 18.5
        vix_5d_chg = ((vix_val / float(vix.iloc[-6])) - 1.0) * 100.0 if len(vix) >= 6 else 0.0

        tnx_val = float(tnx.iloc[-1]) if len(tnx) else 4.2
        tnx_2w_chg = (tnx_val - float(tnx.iloc[-11])) if len(tnx) >= 11 else 0.0

        # Rejim Karar Mantığı
        if vix_val >= 28.0 or (spy_price < spy_sma200 and vix_val >= 23.0):
            regime_code = "KRIZ_YUKSEK_RISK"
            regime_badge = "🔴 YÜKSEK KORKU / SAVUNMA REJİMİ"
            regime_color = "#ef5350"
            summary = (
                f"Piyasada genel korku yüksek (VIX: {vix_val:.1f}). Büyük fonlar riskli hisselerden çıkıp nakde geçiyor. "
                f"Bu havada ucuz görünen hisseler bile daha da düşebilir."
            )
            hunter_rule = "Alım Avcısı'nda 1. kademede acele etme; sadece 2. kademe (derin iskonto) bölgesinde ve güçlü dönüş mumunda küçük parçayla gir."
        elif spy_price < spy_sma50 or smh_2w_ret <= -6.0 or vix_val >= 21.5:
            regime_code = "DUZELTME_BASKISI"
            regime_badge = "🟠 SEKTÖREL DÜZELTME / RİSKTEN KAÇIŞ"
            regime_color = "#ff9100"
            summary = (
                f"Genel borsa veya çip sektörü son 2 haftada kâr satışı baskısında "
                f"(S&P 500 2H: %{spy_2w_ret:+.1f}, Çip ETF SMH 2H: %{smh_2w_ret:+.1f}, VIX: {vix_val:.1f}). "
                f"Tekil hisselerin düşmesi kendi suçları değil, sektör genelinde para çıkışı var."
            )
            hunter_rule = "Tepeden kırılım kovalama! Sadece destek bölgesine inmiş ve gün içi satışları durmuş kaliteli hisselerde kademeli alım yap."
        elif spy_price >= spy_sma50 and spy_price >= spy_sma200 and vix_val < 18.5 and smh_2w_ret >= 0:
            regime_code = "GUCLU_BOGA"
            regime_badge = "🟢 GÜÇLÜ YÜKSELİŞ / RİSK İŞTAHI AÇIK"
            regime_color = "#00c853"
            summary = (
                f"Borsa hem 50 hem 200 günlük ortalamasının üzerinde, korku endeksi düşük ({vix_val:.1f}) ve "
                f"çip/teknoloji sektörüne para girişi var (SMH 2H: %{smh_2w_ret:+.1f})."
            )
            hunter_rule = "Yükseliş trendindeki hisselerde geri çekilmeler alım fırsatıdır, kârda olan hisseleri erken satma ve Kâr Koruma Çizgisi ile sür."
        else:
            regime_code = "SECICI_YATAY"
            regime_badge = "🟡 SEÇİCİ / DALGALI PİYASA REJİMİ"
            regime_color = "#29b6f6"
            summary = (
                f"Endeksler genel olarak dengeli (VIX: {vix_val:.1f}, S&P 500 2H: %{spy_2w_ret:+.1f}) ancak tüm hisseler aynı anda yükselmiyor. "
                f"Kaliteli ve bilançosu güçlü hisselerin ayrıştığı dönem."
            )
            hunter_rule = "Faktör skoru yüksek olan hisselerde 1. alım bölgesini takip et, aşırı şişmiş hisselerde ise kâr almayı ihmal etme."

        return {
            "regime_code": regime_code,
            "regime_badge": regime_badge,
            "regime_color": regime_color,
            "summary": summary,
            "hunter_rule": hunter_rule,
            "spy_price": round(spy_price, 2),
            "spy_2w_ret": round(spy_2w_ret, 2),
            "smh_2w_ret": round(smh_2w_ret, 2),
            "vix_val": round(vix_val, 2),
            "vix_5d_chg": round(vix_5d_chg, 1),
            "tnx_val": round(tnx_val, 2),
            "tnx_2w_chg": round(tnx_2w_chg, 2),
            "updated_at": datetime.now().strftime("%H:%M"),
        }
    except Exception:
        return {
            "regime_code": "SECICI_YATAY",
            "regime_badge": "🟡 SEÇİCİ / DALGALI PİYASA REJİMİ",
            "regime_color": "#29b6f6",
            "summary": "Piyasa dengeli seyrediyor, hisse bazlı seçici hareketler ön planda.",
            "hunter_rule": "Kademeli alım ve kâr koruma kurallarına sadık kal.",
            "spy_price": 0.0,
            "spy_2w_ret": 0.0,
            "smh_2w_ret": 0.0,
            "vix_val": 18.5,
            "vix_5d_chg": 0.0,
            "tnx_val": 4.2,
            "tnx_2w_chg": 0.0,
            "updated_at": datetime.now().strftime("%H:%M"),
        }


def detect_factor_conflicts(
    symbol: str,
    kalite: float,
    deger: float,
    momentum: float,
    risk: float,
) -> dict:
    """
    Bölüm 3 & Mod #2: Dört faktör arasındaki çelişkileri (çatışmaları) yakalar.
    Tek bir ortalama puanın gizlediği tehlikeleri sade Türkçe ile açıklar.
    """
    conflicts = []
    strengths = []

    if momentum >= 68 and deger <= 45:
        conflicts.append(
            f"⚠️ **Momentum – Değer Çatışması (Momentum: {momentum:.0f}/100 vs Değer: {deger:.0f}/100):** "
            f"{symbol} güçlü bir yükseliş/ilgi rüzgarına sahip ancak fiyatı çarpanlarına göre **pahalılaşmış**. "
            f"Bu durum 'beklentiler zaten fiyata girdi' riskini artırır; tepeden kovalamak yerine geri çekilmelerde alınmalıdır."
        )
    if kalite >= 65 and deger >= 55 and momentum <= 42:
        conflicts.append(
            f"⏳ **Kalite – Momentum Çatışması (Kalite: {kalite:.0f}/100 vs Momentum: {momentum:.0f}/100):** "
            f"Şirket temel olarak sağlam ve fiyatı makul/ucuz, fakat piyasa şu an bu hisseyi yukarı taşımıyor (trend zayıf). "
            f"Erken girersen paran yatayda bekleyebilir; dipten dönüş onayı görmeden büyük alım yapma."
        )
    if (momentum >= 65 or kalite >= 65) and risk <= 42:
        conflicts.append(
            f"🎢 **Getiri – Oynaklık Çatışması (Risk Dayanımı: {risk:.0f}/100):** "
            f"Hissenin büyüme/momentum hikayesi güçlü ama **fiyat dalgalanması (beta/volatilite) çok sert**. "
            f"Piyasa %1 düşerken bu hisse %2.5-%3 düşebilir. Pozisyon büyüklüğünü normalin yarısı kadar tutmalısın."
        )
    if deger >= 65 and kalite <= 42:
        conflicts.append(
            f"🪤 **Ucuzluk Tuzağı Uyarısı (Değer: {deger:.0f}/100 vs Kalite: {kalite:.0f}/100):** "
            f"Hisse çarpan olarak ucuz görünüyor ancak şirketin kârlılık/bilanço kalitesi zayıf. "
            f"Sırf ucuz diye kalitesiz hisse almak 'değer tuzağı' olabilir."
        )

    if kalite >= 65 and momentum >= 60:
        strengths.append(
            f"✅ **Kalite + Momentum Uyumu:** Hem şirketin bilançosu sağlam ({kalite:.0f}/100) hem de piyasa trendi destekliyor ({momentum:.0f}/100)."
        )
    if kalite >= 65 and deger >= 55:
        strengths.append(
            f"✅ **Kalite + Makul Fiyat:** Sağlam bir şirketi aşırı şişmemiş değerlemeyle ({deger:.0f}/100) yakalama avantajı var."
        )

    if not conflicts:
        if kalite >= 60 and deger >= 50 and momentum >= 55:
            headline = "🟢 Dört faktör birbiriyle uyumlu; belirgin bir sinyal çatışması yok."
        else:
            headline = "⚖️ Faktörler dengeli/nötr bölgede; keskin bir uçurum bulunmuyor."
    else:
        headline = f"⚠️ Dikkat: Tek puana bakıp aldanma! Bu hissede {len(conflicts)} önemli faktör çatışması tespit edildi."

    return {
        "has_conflict": bool(conflicts),
        "headline": headline,
        "conflicts": conflicts,
        "strengths": strengths,
    }


@_cache_data(ttl=900, show_spinner=False)
def analyze_earnings_catalyst(symbol: str) -> dict:
    """
    Mod #4: Katalizör & Bilanço Laboratuvarı.
    Hissenin geçmiş bilançolarında (son 6-8 çeyrek) beklentiyi aşıp aşmadığını ve
    ertesi işlem günü + 5 işlem günü sonunda fiyatın gerçekte ne yaptığını hesaplar.
    Böylece "İyi bilanço geldi ama neden düştü?" (Sell the news) tuzağını istatistikle gösterir.
    """
    symbol = symbol.strip().upper()
    out = {
        "symbol": symbol,
        "next_earnings_date": None,
        "days_to_earnings": None,
        "pre_earnings_runup_15d_pct": 0.0,
        "priced_in_warning": False,
        "history_rows": [],
        "avg_abs_1d_move_pct": 0.0,
        "drop_count_1d": 0,
        "total_count": 0,
        "sell_the_news_count": 0,
        "summary_text": "Bu hisse için geçmiş bilanço tepki verisi bulunamadı.",
    }
    try:
        tk = yf.Ticker(symbol)
        hist = tk.history(period="2y", interval="1d")
        if hist is None or len(hist) < 40:
            return out

        close_s = hist["Close"]
        cur_p = float(close_s.iloc[-1])
        if len(close_s) >= 16:
            p_15d = float(close_s.iloc[-16])
            out["pre_earnings_runup_15d_pct"] = round(((cur_p / p_15d) - 1.0) * 100.0, 1)

        # Gelecek bilanço tarihi
        try:
            cal = tk.calendar
            edates = None
            if isinstance(cal, dict):
                edates = cal.get("Earnings Date") or cal.get("Earnings High")
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                edates = cal.loc["Earnings Date"].values
            if edates:
                first_dt = edates[0] if isinstance(edates, (list, tuple, np.ndarray)) else edates
                target_d = first_dt.date() if hasattr(first_dt, "date") else pd.to_datetime(str(first_dt)).date()
                diff = (target_d - datetime.now().date()).days
                if -1 <= diff <= 120:
                    out["days_to_earnings"] = int(diff)
                    out["next_earnings_date"] = target_d.strftime("%d.%m.%Y")
        except Exception:
            pass

        # Eğer bilançoya 14 günden az kaldıysa ve hisse son 15 günde +%10'dan fazla yükseldiyse
        if (
            out["days_to_earnings"] is not None
            and 0 <= out["days_to_earnings"] <= 14
            and out["pre_earnings_runup_15d_pct"] >= 10.0
        ):
            out["priced_in_warning"] = True

        # Geçmiş bilanço tarihleri ve EPS sürprizleri
        ed_df = getattr(tk, "earnings_dates", None)
        if ed_df is None or ed_df.empty:
            return out

        # Sadece geçmişteki bilançoları al
        idx_dates = pd.to_datetime(ed_df.index).tz_localize(None)
        ed_clean = ed_df.copy()
        ed_clean.index = idx_dates
        today_ts = pd.Timestamp(datetime.now().date())
        past_ed = ed_clean[ed_clean.index < today_ts].sort_index(ascending=False).head(8)

        hist_idx = pd.to_datetime(hist.index).tz_localize(None)
        closes = hist["Close"].values

        rows = []
        abs_moves = []
        drop_cnt = 0
        sell_news_cnt = 0

        for dt_idx, erow in past_ed.iterrows():
            # Bilanço gününe en yakın işlem gününü bul
            pos_arr = np.searchsorted(hist_idx, dt_idx)
            if pos_arr <= 0 or pos_arr >= len(closes) - 2:
                continue

            # Bilanço öncesi kapanış ve ertesi gün kapanışı (1 günlük net tepki)
            # Bazı bilançolar seans kapandıktan sonra açıklanır, bu yüzden [pos-1 -> pos+1] en büyük hareketi yakalar
            r_same = (closes[pos_arr] / closes[pos_arr - 1] - 1.0) * 100.0
            r_next = (closes[pos_arr + 1] / closes[pos_arr] - 1.0) * 100.0
            move_1d = r_next if abs(r_next) > abs(r_same) else r_same

            end_5d = min(pos_arr + 5, len(closes) - 1)
            move_5d = (closes[end_5d] / closes[pos_arr - 1] - 1.0) * 100.0

            est_eps = erow.get("EPS Estimate")
            rep_eps = erow.get("Reported EPS")
            surp_pct = erow.get("Surprise(%)")

            beat_est = bool(pd.notna(surp_pct) and float(surp_pct) > 0)
            if move_1d < 0:
                drop_cnt += 1
                if beat_est:
                    sell_news_cnt += 1

            abs_moves.append(abs(move_1d))

            rows.append({
                "Bilanço Tarihi": dt_idx.strftime("%d.%m.%Y"),
                "EPS Beklenti": f"${float(est_eps):.2f}" if pd.notna(est_eps) else "—",
                "Açıklanan EPS": f"${float(rep_eps):.2f}" if pd.notna(rep_eps) else "—",
                "Sürpriz (%)": f"%{float(surp_pct):+.1f}" if pd.notna(surp_pct) else "—",
                "Ertesi Gün Tepkisi": f"%{move_1d:+.1f} {'🟢' if move_1d >= 0 else '🔴'}",
                "5 Günlük Sonuç": f"%{move_5d:+.1f}",
                "_move_1d": move_1d,
            })

        if rows:
            total = len(rows)
            avg_abs = float(np.mean(abs_moves))
            out["history_rows"] = rows
            out["avg_abs_1d_move_pct"] = round(avg_abs, 1)
            out["drop_count_1d"] = drop_cnt
            out["total_count"] = total
            out["sell_the_news_count"] = sell_news_cnt

            out["summary_text"] = (
                f"{symbol} son **{total} bilançosunda** bilanço ertesi gün ortalama **±%{avg_abs:.1f}** sertliğinde dalgalandı ve "
                f"bunların **{drop_cnt} tanesinde ertesi gün düştü**. "
                + (
                    f"Üstelik **{sell_news_cnt} kez beklentiden iyi kâr açıklamasına rağmen** 'beklenti bitti' satışıyla (Sell the news) eksi kapattı!"
                    if sell_news_cnt > 0
                    else "Bilanço sonuçları fiyat yönü üzerinde doğrudan belirleyici oldu."
                )
            )
    except Exception:
        pass
    return out


@_cache_data(ttl=600, show_spinner=False)
def compare_opportunity_cost(symbol: str) -> dict:
    """
    Mod #11: Alternatif Fırsat Analizi.
    Bu hisseyi almak yerine aynı dönemde S&P 500 (SPY) veya Yarı İletken ETF'i (SMH)
    tutulsaydı ne kadar getiri ve ne kadar sarsıntı (maksimum düşüş) yaşanırdı?
    """
    symbol = symbol.strip().upper()
    try:
        syms = [symbol, "SPY", "SMH"]
        raw = yf.download(syms, period="6mo", interval="1d", progress=False, group_by="ticker")

        stats = {}
        for s in syms:
            if s not in raw or "Close" not in raw[s]:
                continue
            c = raw[s]["Close"].dropna()
            if len(c) < 20:
                continue
            ret_3m = ((float(c.iloc[-1]) / float(c.iloc[-63])) - 1.0) * 100.0 if len(c) >= 63 else ((float(c.iloc[-1]) / float(c.iloc[0])) - 1.0) * 100.0
            ret_1m = ((float(c.iloc[-1]) / float(c.iloc[-21])) - 1.0) * 100.0 if len(c) >= 21 else 0.0
            peak = c.cummax()
            max_dd = float(((c - peak) / peak).min()) * 100.0
            vol_ann = float(c.pct_change().dropna().std() * np.sqrt(252)) * 100.0
            stats[s] = {
                "ret_1m": round(ret_1m, 1),
                "ret_3m": round(ret_3m, 1),
                "max_dd": round(max_dd, 1),
                "vol": round(vol_ann, 1),
            }

        if symbol not in stats:
            return {}

        st_sym = stats[symbol]
        st_spy = stats.get("SPY", {"ret_3m": 0.0, "max_dd": -5.0, "vol": 15.0})
        st_smh = stats.get("SMH", {"ret_3m": 0.0, "max_dd": -12.0, "vol": 28.0})

        diff_spy = round(st_sym["ret_3m"] - st_spy["ret_3m"], 1)
        diff_smh = round(st_sym["ret_3m"] - st_smh["ret_3m"], 1)

        if diff_spy > 3.0 and diff_smh > 0:
            verdict = (
                f"✅ **Alternatiflerine Göre Üstün:** {symbol} son 3 ayda hem S&P 500'ü (%{diff_spy:+.1f} fark) "
                f"hem de Çip ETF'i SMH'yi (%{diff_smh:+.1f} fark) yenerek aldığı riskin hakkını vermiş."
            )
        elif diff_spy < -5.0:
            verdict = (
                f"⚠️ **Alternatif Fırsat Uyarısı:** {symbol} son 3 ayda S&P 500 endeksinin **%{abs(diff_spy):.1f} gerisinde** kalmış "
                f"ve en tepeden **%{st_sym['max_dd']:.1f}** düşüş yaşamış (SPY düşüşü: %{st_spy['max_dd']:.1f}). "
                f"Tek hisse riski almak için dipten dönüş onayının tam olması şart."
            )
        else:
            verdict = (
                f"⚖️ **Endeksle Paralel:** {symbol} son 3 ayda sektör ETF'i ve piyasayla benzer bir getiri/risk profili sergiliyor."
            )

        return {
            "stats": stats,
            "diff_spy_3m": diff_spy,
            "diff_smh_3m": diff_smh,
            "verdict": verdict,
        }
    except Exception:
        return {}


def build_investment_committee_card(
    symbol: str,
    current_price: float,
    kalite: float,
    deger: float,
    momentum: float,
    risk: float,
    dip_res: dict | None,
    exit_res: dict | None,
    earnings_info: dict | None,
    regime_info: dict | None,
) -> dict:
    """
    Mod #1: Yatırım Komitesi (Investment Committee) Tek Ekran Karar Özeti.
    Tüm analizleri birleştirerek:
    - Komite Kararı (AL / KADEMELİ TOPLA / TUT / KÂR AL / UZAK DUR)
    - Boğa, Baz ve Ayı senaryoları
    - Tezi Geçersiz Kılacak Koşul (Invalidation Level)
    üretir.
    """
    zone1_low = dip_res["zone1_low"] if dip_res else round(current_price * 0.94, 2)
    zone1_high = dip_res["zone1_high"] if dip_res else round(current_price * 0.97, 2)
    stop_level = dip_res["stop_level"] if dip_res else round(current_price * 0.89, 2)
    target1 = dip_res["target1"] if dip_res else round(current_price * 1.10, 2)
    target2 = dip_res["target2"] if dip_res else round(current_price * 1.18, 2)

    bull_upside = round(((target2 / current_price) - 1.0) * 100.0, 1) if current_price > 0 else 15.0
    base_upside = round(((target1 / current_price) - 1.0) * 100.0, 1) if current_price > 0 else 8.0
    bear_downside = round(((stop_level / current_price) - 1.0) * 100.0, 1) if current_price > 0 else -10.0

    # Komite Kararını Belirle
    days_e = earnings_info.get("days_to_earnings") if earnings_info else None
    dip_code = dip_res.get("state_code") if dip_res else "BEKLEMEDE"
    exit_code = exit_res.get("exit_code") if exit_res else "KARI_KORU_TUT"

    if days_e is not None and 0 <= days_e <= 5:
        verdict_badge = f"🟣 BİLANÇO ÖNCESİ RİSK AZALT ({days_e} Gün Kaldı)"
        verdict_color = "#ff9100"
        verdict_summary = (
            "Bilanço açıklamasına çok az kaldı. Yeni alım yapmak yazı-tura atmaktır; "
            "elde yüksek kârlı lot varsa bir kısmını nakde çevirip bilançoyu görmek en güvenli komite kararıdır."
        )
    elif dip_code == "TEHLIKE" or (kalite < 45 and momentum < 45):
        verdict_badge = "🔴 KAÇIN / NAKİTTE BEKLE"
        verdict_color = "#ef5350"
        verdict_summary = (
            "Hisse güvenlik desteğini aşağı kırmış veya temel/teknik gücü zayıf. "
            "Düşüşün durduğuna dair net bir taban oluşmadan alım yapılması komite tarafından onaylanmıyor."
        )
    elif exit_code == "SIMDI_KAR_AL":
        verdict_badge = "💰 AZALT / KADEMELİ KÂR AL"
        verdict_color = "#00e676"
        verdict_summary = (
            "Fiyat kısa vadede güçlü yükseldi ve yorulma bölgesine girdi. "
            "Buradan yeni alım yapılmaz; elinde olanlar için lotların bir kısmını satıp kârı cebine koyma yeridir."
        )
    elif dip_code == "ALIM_FIRSATI" and kalite >= 50:
        verdict_badge = "🟢 KADEMELİ AL (DÖNÜŞ ONAYLI)"
        verdict_color = "#00c853"
        verdict_summary = (
            "Hisse hedeflediğimiz ucuzluk bölgesine indi ve dipten alıcı tepkisi geldi. "
            "Paranın tamamıyla değil, 1. kademe bütçesiyle giriş yapılabilir."
        )
    elif dip_code == "PUSUDA_IZLE":
        verdict_badge = "🟡 İZLE / DÖNÜŞ MUMUNU BEKLE"
        verdict_color = "#ffa726"
        verdict_summary = (
            "Fiyat ucuzluk bölgesinde ve cazip ancak satış baskısı henüz tam kesilmedi. "
            "Elinde varsa dipten panikle satma; yeni alım içinse gün içi yeşil dönüş onayını bekle."
        )
    else:
        verdict_badge = "🔵 TUT / GERİ ÇEKİLME BEKLE"
        verdict_color = "#29b6f6"
        verdict_summary = (
            f"Şirket sağlam ancak anlık fiyat (${current_price:.2f}) ideal alım bölgemizin (${zone1_low:.2f}–${zone1_high:.2f}) üzerinde. "
            f"Elinde tutanlar kâr koruma çizgisiyle devam etmeli, yeni alacaklar geri çekilmeyi beklemeli."
        )

    bull_case = (
        f"Piyasa rejimi destekler ve alıcılar güçlenirse hissenin önce **${target1:.2f}**, ardından ana zirve olan "
        f"**${target2:.2f}** (**+%{bull_upside}**) seviyesine yürümesi beklenir."
    )
    base_case = (
        f"Kısa vadede **${zone1_low:.2f} – ${target1:.2f}** bandında dengelenme ve ilk tepki hedefi olan "
        f"**${target1:.2f}** (**+%{base_upside}**) bölgesine doğru kademeli toparlanma."
    )
    bear_case = (
        f"Sektörel satış dalgası derinleşirse fiyatın 2. kademe destek olan **${dip_res['zone2_low'] if dip_res else current_price*0.91:.2f}** "
        f"ve kaçış sınırı **${stop_level:.2f}** (**%{bear_downside}**) seviyesine sarkma riski."
    )
    invalidation_rule = (
        f"🛑 **Tezi Geçersiz Kılan Koşul:** Fiyat **${stop_level:.2f}** altında günlük kapanış yaparsa "
        f"veya şirket bilançosunda büyüme beklentisini aşağı çekerse yükseliş tezi iptal olur; ısrar edilmez."
    )

    return {
        "verdict_badge": verdict_badge,
        "verdict_color": verdict_color,
        "verdict_summary": verdict_summary,
        "bull_case": bull_case,
        "base_case": base_case,
        "bear_case": bear_case,
        "invalidation_rule": invalidation_rule,
        "target1": target1,
        "target2": target2,
        "stop_level": stop_level,
    }
