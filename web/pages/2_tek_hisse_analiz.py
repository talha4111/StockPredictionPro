"""
Sayfa 2: Tek Hisse Derinlemesine Analiz (Stock Deep-Dive)
Canlı fiyat, kurumsal 4-sütun faktör modeli, teknik göstergeler, Yatırım Komitesi ve Yapay Zeka Uzman Yorumu.
"""
import os
import sqlite3
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from web.components.ui import (
    esc_dollars,
    ACCENT,
    AMBER,
    BLUE,
    BORDER,
    CARD,
    CARD_2,
    GREEN,
    MUTED,
    RED,
    TEXT,
    badge,
    decision_card,
    esc,
    page_header,
    price_chart_with_levels,
    prob_bar_html,
    section,
    stat_grid,
)
from web.components.mobile import COMPANY_NAMES

try:
    from stock_value_engine import (
        KURUMSAL_HAVUZ,
        bilanco_yakin_mi,
        hisse_faktorlerini_hesapla,
        kurulum_karari_belirle,
        sektor_rotasyonu_radar,
        spy_12ay_verisi_oku,
        vix_verisi_oku,
    )
    ENGINE_AVAILABLE = True
except ImportError as e:
    ENGINE_AVAILABLE = False
    st.error(f"Motor import hatası: {e}")

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")


def karar_badge_info(karar: str) -> tuple[str, str]:
    badge_map = {
        "AL_ADAYI": ("🟢 AL ADAYI", GREEN),
        "KALITELI_GERI_CEKILME": ("🟢 KALİTELİ GERİ ÇEKİLME", GREEN),
        "TREND_DEVAMI": ("🟢 TREND DEVAMI", GREEN),
        "PAPER_TOP20": ("🟢 PAPER TOP 20", GREEN),
        "PAPER_SHADOW": ("🟢 PAPER ADAYI", GREEN),
        "BEKLE_GERI_CEKILME": ("🟡 GERİ ÇEKİLME BEKLE", AMBER),
        "UZAMIS_TREND": ("🟡 UZAMIŞ TREND", AMBER),
        "IZLE": ("🔵 İZLE", BLUE),
        "REDDET_TREND": ("🔴 REDDET", RED),
        "DUSUS_TRENDI": ("🔴 DÜŞÜŞ TRENDİ", RED),
        "OLAY_RISKI": ("🟣 OLAY RİSKİ", AMBER),
        "VERI_YETERSIZ": ("⚪ İZLEMEDE", MUTED),
    }
    return badge_map.get(karar, (karar, BLUE))


def karar_badge(karar: str) -> str:
    label, col = karar_badge_info(karar)
    return badge(label, col)


@st.cache_data(ttl=60)
def get_live_quote(sembol):
    """En güncel anlık fiyatı ve günlük değişimi çeker (60 sn önbellekli)."""
    try:
        t = yf.Ticker(sembol)
        fast = getattr(t, "fast_info", {})
        last_price = fast.get("lastPrice")
        prev_close = fast.get("previousClose")

        if not last_price:
            info = t.info or {}
            last_price = info.get("currentPrice") or info.get("regularMarketPrice")
            prev_close = info.get("regularMarketPreviousClose") or prev_close

        if not last_price:
            hist = t.history(period="2d")
            if not hist.empty:
                last_price = float(hist["Close"].iloc[-1])
                if len(hist) > 1:
                    prev_close = float(hist["Close"].iloc[-2])

        change = (last_price - prev_close) if (last_price and prev_close) else 0.0
        change_pct = (change / prev_close * 100) if (prev_close and prev_close > 0) else 0.0
        return {
            "price": last_price or 0.0,
            "change": change,
            "change_pct": change_pct,
            "prev_close": prev_close or last_price or 0.0,
            "timestamp": datetime.now().strftime("%H:%M:%S TSİ"),
        }
    except Exception:
        return {"price": 0.0, "change": 0.0, "change_pct": 0.0, "prev_close": 0.0, "timestamp": "N/A"}


def get_stored_scores(sembol):
    """Veritabanından en son hesaplanmış çapraz-faktör skorlarını çeker."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            """
            SELECT ai_skor, quality_score, value_score, momentum_score, risk_score, decision, setup, as_of_date
            FROM hisse_sinyalleri
            WHERE sembol = ?
            ORDER BY id DESC LIMIT 1
        """,
            (sembol,),
        )
        row = c.fetchone()
        conn.close()
        if row:
            return {
                "faktor_skor": row[0],
                "kalite_skor": row[1],
                "deger_skor": row[2],
                "momentum_skor": row[3],
                "risk_skor": row[4],
                "karar": row[5],
                "kurulum": row[6],
                "as_of_date": row[7],
            }
    except Exception:
        pass
    return None


def estimate_standalone_scores(raw_data):
    """Canlı temel ve teknik verilere dayalı güncel faktör skorları üretir."""
    roe = raw_data.get("roe") if raw_data.get("roe") is not None else 0.15
    pm = raw_data.get("profit_margin") if raw_data.get("profit_margin") is not None else 0.10
    raw_de = raw_data.get("borc_ozkaynak") if raw_data.get("borc_ozkaynak") is not None else raw_data.get("debt_to_equity")
    if raw_de is None:
        de = 0.8
    else:
        de = (raw_de / 100.0) if raw_de > 4.0 else float(raw_de)
    rev_g = raw_data.get("gelir_buyume") or 0.0

    kalite = (
        52.0
        + min(22.0, max(-20.0, (roe - 0.12) * 110))
        + min(18.0, max(-15.0, (pm - 0.08) * 110))
        + min(10.0, max(-5.0, rev_g * 0.25))
    )
    if de < 0.8:
        kalite += 10.0
    elif de > 2.5:
        kalite -= 12.0
    kalite = max(15.0, min(95.0, kalite))

    pe = raw_data.get("pe_orani") or 25.0
    fcf = (raw_data.get("fcf_getiri") or 2.5) / 100.0
    rsi_now = raw_data.get("rsi") or 50.0
    deger = 50.0
    if 0 < pe < 22.0:
        deger += 20.0
    elif pe > 55.0:
        deger -= 15.0
    if fcf > 0.03:
        deger += 12.0
    if rsi_now <= 35.0:
        deger += 18.0
    elif rsi_now <= 43.0:
        deger += 10.0
    deger = max(15.0, min(95.0, deger))

    m12 = raw_data.get("momentum_12_1") or 0.0
    m6 = raw_data.get("momentum_6_1") or 0.0
    momentum = 50.0 + min(35.0, max(-35.0, m12 * 70)) + min(15.0, max(-15.0, m6 * 30))
    momentum = max(15.0, min(95.0, momentum))

    vol = raw_data.get("realized_vol_63d") or 0.30
    dd = abs(raw_data.get("max_drawdown_1y") or 0.20)
    risk = 65.0 - min(28.0, max(0.0, (vol - 0.25) * 55)) - min(18.0, max(0.0, (dd - 0.15) * 40))
    risk = max(15.0, min(95.0, risk))

    faktor_skor = round(kalite * 0.35 + deger * 0.20 + momentum * 0.30 + risk * 0.15, 1)

    return {
        "kalite_skor": round(kalite, 1),
        "deger_skor": round(deger, 1),
        "momentum_skor": round(momentum, 1),
        "risk_skor": round(risk, 1),
        "faktor_skor": faktor_skor,
    }


def evaluate_decision_standalone(sonuc):
    """Skorlar ve teknik göstergelere göre eyleme dönük karar üretir."""
    skor = sonuc.get("faktor_skor") or 50.0
    kalite = sonuc.get("kalite_skor") or 50.0
    fiyat = sonuc.get("fiyat")
    sma_50 = sonuc.get("sma_50")
    sma_200 = sonuc.get("sma_200")
    rsi = sonuc.get("rsi") or 50.0
    momentum = sonuc.get("momentum_12_1") or 0.0
    atr_uzaklik = sonuc.get("sma50_atr_uzaklik") or 0.0

    if sonuc.get("bilanco_riski"):
        return "OLAY_RISKI", "Yedi gün içinde bilanço riski var"

    trend_up = fiyat and sma_200 and sma_50 and fiyat > sma_200 and sma_50 > sma_200 and momentum > 0
    uzamis = (atr_uzaklik > 3.0) or (rsi > 72.0)

    if uzamis:
        return "BEKLE_GERI_CEKILME", "Fiyat SMA50 üzerinde fazla uzamış veya RSI aşırı alımda"

    if kalite >= 58 and (rsi <= 42 or (-3.5 <= atr_uzaklik <= 1.2)):
        return "KALITELI_GERI_CEKILME", "Kaliteli hissede cazip indirim / dipten kademeli alım fırsatı"

    if kalite >= 60 and fiyat and sma_200 and fiyat >= sma_200 * 0.90 and -2.5 <= atr_uzaklik <= 1.5 and 30 <= rsi <= 60 and skor >= 55:
        return "AL_ADAYI", "Kaliteli hissede destek bölgesine sağlıklı geri çekilme"

    if trend_up and not uzamis and 0.0 <= atr_uzaklik <= 2.5 and 45 <= rsi <= 70 and skor >= 62:
        return "AL_ADAYI", "Güçlü yükseliş trendi devam ediyor"

    if fiyat and sma_200 and sma_50 and fiyat < sma_200 * 0.90 and sma_50 < sma_200 and kalite < 45 and skor < 42:
        return "REDDET_TREND", "Temel kalitesi zayıf ve uzun vadeli düşüş trendinde"

    return "IZLE", "İndirim bölgesinde dönüş teyidi takip ediliyor"


def generate_expert_commentary(sembol, price, sma50, sma200, rsi, kalite, deger, momentum, risk, f_skor, karar, bilanco_riski):
    """Kullanıcının istediği profesyonel, göstergelere dayalı ve yönlendirici Uzman Raporunu üretir."""
    price_val = price or 100.0
    sma50_val = sma50 if (sma50 and not pd.isna(sma50)) else price_val * 0.96
    sma200_val = sma200 if (sma200 and not pd.isna(sma200)) else price_val * 0.90
    rsi_val = rsi or 50.0

    if price_val >= sma200_val and price_val >= sma50_val:
        trend_metni = f"hisse hem 50 günlük (${sma50_val:.2f}) hem de 200 günlük (${sma200_val:.2f}) hareketli ortalamalarının üzerinde **güçlü bir boğa (yükseliş) trendini** koruyor."
    elif price_val >= sma200_val and price_val < sma50_val:
        trend_metni = f"hisse 200 günlük ana trend desteğinin (${sma200_val:.2f}) üzerinde kalmayı sürdürüyor ancak kısa vadede 50 günlük ortalamasının (${sma50_val:.2f}) altına sarkarak **düzeltme/soluklanma evresine** geçmiş durumda."
    else:
        trend_metni = f"hisse hem 50 günlük (${sma50_val:.2f}) hem de 200 günlük (${sma200_val:.2f}) ortalamalarının altında seyrederek **ayı/düşüş baskısı** altında işlem görüyor."

    if bilanco_riski:
        teshis = f"⚠️ **Bilanço Riski Mevcut:** {sembol} önümüzdeki 7 gün içerisinde resmi çeyreklik bilançosunu açıklayacak."
        neden = f"Yapay zeka ve çip sektörü gibi yüksek beklentili alanlarda bilançolar çok sert fiyat boşluklarına (gap-down) sebep olabilir. Kalite puanı (%{kalite:.0f}) yüksek olsa bile bilanço belirsizliği en büyük risk faktörüdür."
        tavsiye = f"**Uzman Önerisi:** Şu an bu seviyeden (${price_val:.2f}) yeni pozisyon açılmasını **önermiyorum**. Bilançoyu nakitte izleyip, piyasanın rakamlara vereceği tepkiyi ve yön teyidini gördükten sonra oyuna girmek çok daha güvenli ve rasyonel bir adımdır."
        hedef_giris = f"${sma50_val * 0.97:.2f} - ${sma50_val:.2f} (Bilanço sonrası teyitli)"
        stop_level = f"${sma200_val * 0.95:.2f}"
        tp_level = f"${price_val * 1.15:.2f}"

    elif karar in ["BEKLE_GERI_CEKILME", "UZAMIS_TREND"] or rsi_val >= 68.0:
        teshis = "✋ **Acele Etmeyin — Fiyat Fazla Isınmış (Aşırı Alım):**"
        neden = f"RSI göstergesi **{rsi_val:.1f}** seviyesine tırmanarak aşırı alım sınırına dayanmış durumda. Ayrıca fiyat (${price_val:.2f}), 50 günlük ana desteğinden (${sma50_val:.2f}) yukarı doğru fazla uzaklaşmış (uzamış trend)."
        tavsiye = f"**Uzman Önerisi:** Göstergeler hissenin kısa vadede bir kâr satışı veya soluklanma yaşama olasılığının yüksek olduğunu gösteriyor. Treni kaçırma korkusuyla (FOMO) buradan tek seferde alım yapmanızı **tavsiye etmiyorum**. Fiyatın **${sma50_val:.2f} (SMA 50)** desteğine doğru geri çekilmesini ve RSI'ın 50 seviyesine gevşemesini bekleyin. Alım için bu düzeltmeyi kollayın."
        hedef_giris = f"${sma50_val * 0.98:.2f} - ${sma50_val * 1.02:.2f} (Destek Teması)"
        stop_level = f"${sma50_val * 0.94:.2f}"
        tp_level = f"${price_val * 1.18:.2f}"

    elif karar in ["AL_ADAYI", "KALITELI_GERI_CEKILME", "TREND_DEVAMI", "PAPER_TOP20"]:
        teshis = "🎯 **Fırsat Masada — İdeal Alım Pencerelerinden Biri:**"
        neden = f"Şirketin kurumsal Kalite puanı (%{kalite:.0f}) çok yüksek ve hisse hareketli ortalama desteğine (${sma50_val:.2f}) sağlıklı bir şekilde oturmuş. RSI ({rsi_val:.1f}) aşırı şişkinliğini atmış, risk/kazanç (RR) oranı yatırımcı lehine dönmüş durumda."
        tavsiye = f"**Uzman Önerisi:** Sistemimiz hisseyi alım için uygun buluyor. Ancak tek kurşun atmak yerine profesyonelce **2 Kademeli Alım** öneriyorum: Bütçenizin %40'ı ile buralardan (${price_val:.2f}) 1. Kademeyi açabilir, olası piyasa sarkmalarında kalan %60'ı ${sma200_val:.2f} (SMA 200) seviyesine saklayabilirsiniz."
        hedef_giris = f"${price_val:.2f} (Anlık 1. Kademe)"
        stop_level = f"${sma50_val * 0.93:.2f} (%7 Zarar Kes)"
        tp_level = f"${price_val * 1.20:.2f} (+%20 Kâr Al)"

    elif price_val < sma200_val:
        if kalite >= 55.0 or rsi_val <= 36.0:
            teshis = "💎 **Nadir İndirim Fırsatı — Kaliteli Dip Avcılığı:**"
            neden = (
                f"Hisse son düşüş dalgasıyla 200 günlük ortalamasının (${sma200_val:.2f}) altına sarkarak teknik olarak aşırı satım / ucuzluk bölgesine (RSI: {rsi_val:.1f}) girmiş durumda. "
                f"Şirketin kurumsal Kalite puanı (%{kalite:.0f}) sağlam olduğu için bu çapta geri çekilmeler uzun vadeli 'panik indirimi' fırsatı sunar."
            )
            tavsiye = (
                f"**Uzman Önerisi:** Fiyat bu kadar ucuzlamışken tekrar 50 günlük ortalamanın (${sma50_val:.2f}) üzerine çıkmasını beklemek, dipteki en büyük kâr marjını kaçırmanıza neden olur! "
                f"Bunun yerine {sembol} için bu seviyeler (${price_val:.2f}) **Kademeli Dip Alımı** bölgesidir: Bütçenizin %35-%40'ı ile buralardan 1. Kademeyi açabilir, "
                f"olası ek sarkmalarda kalan %60'ı bir alt destek kademesine saklayarak ilk etapta ${sma200_val:.2f} (SMA 200) ve ardından ${sma50_val:.2f} tepki yükselişini hedefleyebilirsiniz."
            )
            hedef_giris = f"${price_val * 0.97:.2f} – ${price_val * 1.02:.2f} (1. Kademe Dip Alımı)"
            stop_level = f"${price_val * 0.88:.2f} (Kademeli Zarar Kes)"
            tp_level = f"${max(sma200_val * 1.05, price_val * 1.16):.2f} (Tepki Hedefi)"
        else:
            teshis = "⚠️ **Zayıf Bilanço + Düşüş Trendi — Dipte Dönüş Mumu Bekleyin:**"
            neden = (
                f"Fiyat 200 günlük (${sma200_val:.2f}) ortalamasının altında ve şirketin temel kalite puanı (%{kalite:.0f}) nispeten düşük. "
                f"Temel bilançosu zayıf hisselerde düşüşler daha uzun sürebilir."
            )
            tavsiye = (
                "**Uzman Önerisi:** Bilanço kalitesi düşük olduğu için düşüş durmadan körlemesine alım yapmak yerine, "
                "mevcut dip desteğinde satışların kesildiğini ve **Alım Avcısı'nda yeşil dönüş mumunun yandığını** gördükten sonra küçük kademeyle tepki yükselişi kovalamak daha güvenlidir."
            )
            hedef_giris = f"${price_val * 0.95:.2f} civarı (Yeşil dönüş mumu teyidiyle)"
            stop_level = f"${price_val * 0.90:.2f}"
            tp_level = f"${sma200_val:.2f}"

    else:
        teshis = "⏳ **İzle ve Pusuya Yat — Karar / Konsolidasyon Aşaması:**"
        neden = f"Hisse şu an ne net bir alım sinyali ne de acil bir satış baskısı üretiyor. RSI ({rsi_val:.1f}) tamamen nötr bantta. Fiyat ${sma50_val:.2f} ile ${sma200_val:.2f} arasında sıkışmış durumda ve piyasanın genel yönünü bekliyor."
        tavsiye = f"**Uzman Önerisi:** Sistem şu göstergelere göre henüz kesin alım noktasında değil: Fiyat henüz net bir destek teması yapmadı veya yukarı yönlü hacimli bir kırılım gerçekleştirmedi. Bu yüzden acele etmeyip **biraz izlemenizi ve sabırla beklemenizi tavsiye ediyorum**. Fiyat ${sma50_val:.2f} seviyesini hacimle yukarı kırarsa trene binilebilir veya ${sma200_val:.2f} desteğine değerse dipten toplanabilir."
        hedef_giris = f"${sma200_val * 1.01:.2f} (Dipten temas) VEYA ${sma50_val * 1.02:.2f} (Yukarı kırılım)"
        stop_level = f"${sma200_val * 0.95:.2f}"
        tp_level = f"${price_val * 1.15:.2f}"

    return {
        "trend_metni": esc_dollars(trend_metni),
        "teshis": esc_dollars(teshis),
        "neden": esc_dollars(neden),
        "tavsiye": esc_dollars(tavsiye),
        "hedef_giris": hedef_giris,
        "stop_level": stop_level,
        "tp_level": tp_level,
    }


def radar_chart(kalite, deger, momentum, risk):
    categories = ["Kalite", "Değer", "Momentum", "Risk Dayanımı"]
    values = [kalite, deger, momentum, risk]
    values_closed = values + [values[0]]
    categories_closed = categories + [categories[0]]

    fig = go.Figure()
    fig.add_trace(
        go.Scatterpolar(
            r=values_closed,
            theta=categories_closed,
            fill="toself",
            name="Faktör Skoru",
            line=dict(color=ACCENT, width=2),
            fillcolor="rgba(45, 212, 191, 0.18)",
        )
    )
    fig.update_layout(
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=10, color=MUTED)),
            angularaxis=dict(tickfont=dict(size=12, color=TEXT)),
        ),
        showlegend=False,
        height=330,
        margin=dict(l=45, r=45, t=20, b=20),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


@st.cache_data(ttl=300)
def get_price_history_1y(sembol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(sembol).history(period="1y")
    except Exception:
        return pd.DataFrame()


# ─── SAYFA BAŞLIĞI & HIZLI ARAMA ───
page_header(
    "🔍 Hisse Analizi",
    "Canlı fiyat, alım/stop/hedef seviyeleri, Yatırım Komitesi senaryoları ve Yapay Zeka (Üçlü Bariyer) 15 günlük hedef olasılığı.",
)

incoming_symbol = st.session_state.get("selected_symbol", "MU")
auto_analyze = st.session_state.pop("auto_analyze", False)

col_input, col_btn = st.columns([3.2, 1])
with col_input:
    sembol_input = st.text_input(
        "Hisse Sembolü",
        value=incoming_symbol,
        placeholder="Örn: MU, MRVL, COHR, BE, RKLB, VST, AVGO, NVDA",
        label_visibility="collapsed",
    )
with col_btn:
    analiz_btn = st.button("🚀 Canlı Analiz Et", type="primary", use_container_width=True)

# Hızlı seçim butonları
quick_syms = ["MU", "MRVL", "COHR", "BE", "RKLB", "VST", "AVGO", "NVDA"]
q_cols = st.columns(len(quick_syms))
clicked_quick = None
for idx, qs in enumerate(quick_syms):
    with q_cols[idx]:
        if st.button(qs, key=f"quick_an_{qs}", use_container_width=True):
            clicked_quick = qs

active_symbol = (clicked_quick or sembol_input or incoming_symbol or "MU").upper().strip()
st.session_state["selected_symbol"] = active_symbol

if active_symbol:
    sembol = active_symbol
    comp_name = COMPANY_NAMES.get(sembol, "")

    with st.spinner(f"🔄 {sembol} için canlı piyasa, faktör, Yatırım Komitesi ve AI verileri hazırlanıyor..."):
        quote = get_live_quote(sembol)

        vix_degeri = 18.5
        spy_getiri = 0.15
        sektor_perf = {}
        try:
            v_res = vix_verisi_oku()
            if v_res.uygun:
                vix_degeri = v_res.value
            s_res = spy_12ay_verisi_oku()
            if s_res.uygun:
                spy_getiri = s_res.value
            sektor_perf = sektor_rotasyonu_radar() or {}
        except Exception:
            pass

        sektor = KURUMSAL_HAVUZ.get(sembol, "Teknoloji")
        raw_result = hisse_faktorlerini_hesapla(sembol, sektor, vix_degeri, spy_getiri, sektor_perf)

        if quote["price"] > 0:
            raw_result["fiyat"] = quote["price"]

        stored = get_stored_scores(sembol)
        standalone = estimate_standalone_scores(raw_result)
        if stored and stored.get("faktor_skor") is not None:
            kalite = round(max(float(stored.get("kalite_skor") or 50.0), standalone["kalite_skor"]), 1)
            deger = round(max(float(stored.get("deger_skor") or 50.0), standalone["deger_skor"]), 1)
            momentum = round(0.5 * float(stored.get("momentum_skor") or 50.0) + 0.5 * standalone["momentum_skor"], 1)
            risk = round(0.5 * float(stored.get("risk_skor") or 50.0) + 0.5 * standalone["risk_skor"], 1)
            f_skor = round(kalite * 0.35 + deger * 0.20 + momentum * 0.30 + risk * 0.15, 1)
            score_source = "Canlı Bilanço & Kurumsal Havuz Hibrit Modeli"
        else:
            kalite = standalone["kalite_skor"]
            deger = standalone["deger_skor"]
            momentum = standalone["momentum_skor"]
            risk = standalone["risk_skor"]
            f_skor = standalone["faktor_skor"]
            score_source = "Dinamik Temel & Teknik Faktör Modellemesi"

        raw_result["kalite_skor"] = kalite
        raw_result["deger_skor"] = deger
        raw_result["momentum_skor"] = momentum
        raw_result["risk_skor"] = risk
        raw_result["faktor_skor"] = f_skor

        hist_1y = get_price_history_1y(sembol)
        sma20_val = f"${hist_1y['Close'].rolling(20).mean().iloc[-1]:.2f}" if (not hist_1y.empty and len(hist_1y) >= 20) else f"${quote['price']:.2f}"

        karar, karar_nedeni = evaluate_decision_standalone(raw_result)
        bilanco_var_mi = False
        try:
            bilanco_var_mi = bilanco_yakin_mi(sembol)
        except Exception:
            pass

        commentary = generate_expert_commentary(
            sembol=sembol,
            price=quote["price"],
            sma50=raw_result.get("sma_50"),
            sma200=raw_result.get("sma_200"),
            rsi=raw_result.get("rsi"),
            kalite=kalite,
            deger=deger,
            momentum=momentum,
            risk=risk,
            f_skor=f_skor,
            karar=karar,
            bilanco_riski=bilanco_var_mi,
        )

        from web.components.dip_hunter import analyze_stock_dip, analyze_stock_exit
        from web.components.investment_committee import (
            analyze_earnings_catalyst,
            build_investment_committee_card,
            compare_opportunity_cost,
            detect_factor_conflicts,
            get_market_regime_summary,
        )

        regime_info = get_market_regime_summary()
        dip_res = analyze_stock_dip(sembol, vix_value=float(regime_info.get("vix_val", 18.5)))
        exit_res = analyze_stock_exit(sembol)
        earnings_info = analyze_earnings_catalyst(sembol)
        conflict_info = detect_factor_conflicts(sembol, kalite, deger, momentum, risk)
        opp_info = compare_opportunity_cost(sembol)
        ic_card = build_investment_committee_card(
            symbol=sembol,
            current_price=quote.get("price") or 0.0,
            kalite=kalite,
            deger=deger,
            momentum=momentum,
            risk=risk,
            dip_res=dip_res,
            exit_res=exit_res,
            earnings_info=earnings_info,
            regime_info=regime_info,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # KATMAN 1: TEK BİRLEŞİK KARAR KARTI (Fiyat + Komite Hükmü + 4 Kritik Sayı + AI Çubuğu)
    # ═══════════════════════════════════════════════════════════════════════
    q_price = quote.get("price") or (dip_res or {}).get("current_price") or 0.0
    q_pct = quote.get("change_pct") or (dip_res or {}).get("daily_change_pct") or 0.0
    ai_pred = (dip_res or {}).get("ai_pred") or {}

    extra_badges = []
    sys_lbl, sys_col = karar_badge_info(karar)
    extra_badges.append((sys_lbl, sys_col))
    if ai_pred.get("available"):
        extra_badges.append((ai_pred.get("ai_badge", "AI"), ai_pred.get("ai_color", BLUE)))

    if dip_res:
        z1_str = f"${dip_res['zone1_low']:.2f} – ${dip_res['zone1_high']:.2f}"
        z2_sub = f"2. Kademe: ${dip_res['zone2_low']:.2f} – ${dip_res['zone2_high']:.2f}"
        stop_str = f"${dip_res['stop_level']:.2f}"
        tp_str = f"${dip_res['target1']:.2f} – ${dip_res['target2']:.2f}"
        tp_sub = f"+%{dip_res['upside_pct']} kazanç potansiyeli"
    else:
        z1_str = commentary["hedef_giris"]
        z2_sub = "Kademeli giriş"
        stop_str = commentary["stop_level"]
        tp_str = commentary["tp_level"]
        tp_sub = "Hedef bölge"

    raw_rsi = raw_result.get("rsi")
    rsi_val = float(raw_rsi) if (raw_rsi is not None and not pd.isna(raw_rsi)) else 50.0
    raw_sma200 = raw_result.get("sma_200")
    sma200 = float(raw_sma200) if (raw_sma200 is not None and not pd.isna(raw_sma200)) else 0.0
    sma200_str = f"${sma200:.2f}" if sma200 > 0 else "N/A"

    if ai_pred.get("available"):
        wp = int(ai_pred.get("win_prob_pct", 50))
        sp = int(ai_pred.get("stop_prob_pct", 50))
        stat_4 = (
            "🤖 AI 15G Hedef Başarısı",
            f"%{wp}",
            f"Stop riski: %{sp} · Faktör: %{f_skor:.0f}",
            GREEN if wp >= 58 else (AMBER if wp >= 48 else RED),
        )
        footer_bar = (
            "<div style='margin-top:12px;'>"
            + prob_bar_html(
                wp,
                f"🎯 15 Günde Kâr Hedefine Ulaşma İhtimali: %{wp}",
                f"⛔ Kaçış Sınırına Değme Riski: %{sp}",
            )
            + f"<div class='spp-muted' style='margin-top:4px;'>"
            f"📊 <b>Tarihsel İkizler:</b> {esc(sembol)} geçmişte benzer duruma <b>{ai_pred['analog_count']} kez</b> geldi; "
            f"<b>%{ai_pred['analog_win_rate_pct']:.0f}</b> kazanma oranı (15G ort. getiri: <b>{ai_pred['analog_avg_ret_pct']:+.1f}%</b>) · "
            f"RSI(14): <b>{rsi_val:.1f}</b> · SMA200: <b>{sma200_str}</b>"
            f"</div></div>"
        )
    else:
        stat_4 = ("📊 Faktör & RSI", f"%{f_skor:.1f}", f"RSI(14): {rsi_val:.1f} · SMA200: {sma200_str}", ACCENT)
        footer_bar = ""

    top_stats = [
        ("🟢 1. Alım Bölgesi", z1_str, z2_sub, GREEN),
        ("⛔ Kaçış / Stop Sınırı", stop_str, "Altında kapanışta tez iptal", RED),
        ("🎯 Kâr Alma Hedefi", tp_str, tp_sub, BLUE),
        stat_4,
    ]

    decision_card(
        symbol=sembol,
        price=q_price,
        chg_pct=q_pct,
        status_text=ic_card["verdict_badge"],
        status_color=ic_card["verdict_color"],
        headline=ic_card["verdict_summary"],
        stats=top_stats,
        extra_badges=extra_badges,
        name=f"{comp_name} · {sektor}" if comp_name else sektor,
        footer_html=footer_bar,
    )

    if bilanco_var_mi:
        st.warning("⚠️ **OLAY RİSKİ:** Bu hissenin çeyreklik bilançosu 7 takvim günü içinde açıklanacak!")

    # ═══════════════════════════════════════════════════════════════════════
    # KATMAN 2: FİYAT GRAFİĞİ (ALIM BÖLGESİ, STOP VE HEDEFLER GRAFİK ÜZERİNDE)
    # ═══════════════════════════════════════════════════════════════════════
    section(f"📈 {sembol} Fiyat Grafiği & Seviye Haritası (1. Alım · 2. Alım · Stop · Hedef)")
    if not hist_1y.empty:
        fig_levels = price_chart_with_levels(
            hist_1y,
            zone1=(dip_res["zone1_low"], dip_res["zone1_high"]) if dip_res else None,
            zone2=(dip_res["zone2_low"], dip_res["zone2_high"]) if dip_res else None,
            stop=dip_res["stop_level"] if dip_res else None,
            target1=dip_res["target1"] if dip_res else None,
            target2=dip_res["target2"] if dip_res else None,
            height=380,
        )
        if fig_levels:
            st.plotly_chart(fig_levels, use_container_width=True)
    else:
        st.info("Fiyat grafiği verisi alınamadı.")

    # ═══════════════════════════════════════════════════════════════════════
    # KATMAN 3: DÜZENLİ DETAY SEKMELERİ (Hiçbir açıklama veya grafik eksilmeden!)
    # ═══════════════════════════════════════════════════════════════════════
    tab_uzman, tab_komite, tab_faktor, tab_bilanco = st.tabs([
        "🧠 Uzman Yorumu & AI Analizi",
        "🏛️ Yatırım Komitesi & 3 Senaryo",
        "📡 4-Faktör Radarı & Temel/Teknik Veriler",
        "📅 Bilanço Karnesi & Alternatif Kıyas",
    ])

    # ─── SEKME 1: UZMAN YORUMU & AI ANALİZİ ───
    with tab_uzman:
        st.markdown(
            f"""
            <div class="spp-card accent" style="--c:{ACCENT};">
                <div style="font-size:1.1rem; font-weight:800; color:{ACCENT}; margin-bottom:8px;">
                    🧠 Quant & Uzman Değerlendirmesi: {esc(sembol)}
                </div>
                <p style="font-size:0.95rem; color:{TEXT}; line-height:1.6; margin:0 0 10px 0;">
                    <b>Mevcut Trend:</b> {esc(sembol)}, {commentary['trend_metni']}
                </p>
                <p style="font-size:0.95rem; color:{TEXT}; line-height:1.6; margin:0 0 10px 0;">
                    {commentary['teshis']}<br>{commentary['neden']}
                </p>
                <div style="background:{CARD_2}; border:1px solid {BORDER}; border-radius:10px; padding:12px 14px; margin:10px 0;">
                    <div style="color:{ACCENT}; font-size:0.95rem; line-height:1.55;">
                        {commentary['tavsiye']}
                    </div>
                </div>
                <div style="display:flex; gap:10px; flex-wrap:wrap; margin-top:10px;">
                    {badge(f"🎯 İdeal Giriş: {commentary['hedef_giris']}", GREEN)}
                    {badge(f"🛡️ Zarar Durdur (SL): {commentary['stop_level']}", RED)}
                    {badge(f"💰 Hedef Kâr (TP): {commentary['tp_level']}", BLUE)}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if dip_res and dip_res.get("action_advice"):
            st.info(esc_dollars(dip_res["action_advice"]))

        if ai_pred.get("available"):
            section("🤖 Yapay Zeka (Üçlü Bariyer) 15 Günlük Hedef vs Stop Analizi")
            st.caption(
                "QuantBot yapay zeka motorunun 20 ABD hissesi ve bu hissenin kendi geçmişindeki benzer günleri (Tarihsel İkizler) "
                "tarayarak hesapladığı 15 işlem günlük Hedef / Stop olasılığı:"
            )
            st.markdown(esc_dollars(ai_pred.get("ai_summary_tr", "")))
            ai_c1, ai_c2 = st.columns(2)
            with ai_c1:
                st.markdown("**➕ Yapay Zekaya Göre Güçlü Yanlar**")
                for p_txt in ai_pred.get("positives", []):
                    st.success(f"🟢 {p_txt}")
            with ai_c2:
                st.markdown("**➖ Yapay Zekaya Göre Dikkat Edilecek Riskler**")
                for n_txt in ai_pred.get("negatives", []):
                    st.warning(f"🟠 {n_txt}")

        if dip_res and dip_res.get("checklist"):
            total_chk = dip_res.get("total_checks", len(dip_res["checklist"]))
            section(f"📋 {sembol} Alım Avcısı Güven Kontrol Listesi ({dip_res['passed_count']}/{total_chk} Şart Hazır)")
            for item in dip_res["checklist"]:
                icon = "✅" if item["ok"] else "⏳"
                st.markdown(f"{icon} **{item['kriter']}** — *{item['detay']}*")

    # ─── SEKME 2: YATIRIM KOMİTESİ & 3 SENARYO ───
    with tab_komite:
        vc = ic_card["verdict_color"]
        st.markdown(
            f"""
            <div class="spp-card accent" style="--c:{vc};">
                <div class="spp-row">
                    <span style="font-size:1.1rem; font-weight:800; color:{TEXT};">📋 Komite Ortak Hükmü ({esc(sembol)})</span>
                    {badge(ic_card['verdict_badge'], vc)}
                </div>
                <p style="color:{TEXT}; font-size:0.95rem; margin:10px 0 4px 0; line-height:1.55;">
                    {esc_dollars(ic_card['verdict_summary'])}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            st.markdown(
                f"""
                <div class="spp-card accent" style="--c:{GREEN}; height:100%;">
                    <div style="color:{GREEN}; font-weight:700; font-size:0.92rem; margin-bottom:6px;">🟢 Boğa (İyi) Senaryosu</div>
                    <div style="color:{TEXT}; font-size:0.86rem; line-height:1.5;">{esc_dollars(ic_card['bull_case'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sc2:
            st.markdown(
                f"""
                <div class="spp-card accent" style="--c:{BLUE}; height:100%;">
                    <div style="color:{BLUE}; font-weight:700; font-size:0.92rem; margin-bottom:6px;">🟡 Baz (Normal) Senaryo</div>
                    <div style="color:{TEXT}; font-size:0.86rem; line-height:1.5;">{esc_dollars(ic_card['base_case'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with sc3:
            st.markdown(
                f"""
                <div class="spp-card accent" style="--c:{RED}; height:100%;">
                    <div style="color:{RED}; font-weight:700; font-size:0.92rem; margin-bottom:6px;">🔴 Ayı (Kötü) Senaryosu</div>
                    <div style="color:{TEXT}; font-size:0.86rem; line-height:1.5;">{esc_dollars(ic_card['bear_case'])}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.write("")
        st.error(esc_dollars(ic_card["invalidation_rule"]))

    # ─── SEKME 3: 4-FAKTÖR RADARI & TEMEL/TEKNİK VERİLER ───
    with tab_faktor:
        col_left, col_right = st.columns([1, 1])

        with col_left:
            section("📡 4-Sütun Faktör Radarı")
            fig_radar = radar_chart(kalite, deger, momentum, risk)
            st.plotly_chart(fig_radar, use_container_width=True)

            section(f"📋 Faktör Puan Dağılımı ({score_source})")
            faktor_df = pd.DataFrame({
                "Sütun": ["Kalite (%35)", "Değer (%20)", "Momentum (%30)", "Risk Dayanımı (%15)"],
                "Puan (0-100)": [f"{kalite:.1f}", f"{deger:.1f}", f"{momentum:.1f}", f"{risk:.1f}"],
                "Durum": [
                    "Çok Güçlü 🟢" if kalite >= 70 else ("Orta 🟡" if kalite >= 45 else "Zayıf 🔴"),
                    "İskontolu 🟢" if deger >= 60 else ("Makul 🟡" if deger >= 40 else "Pahalı 🔴"),
                    "Güçlü Trend 🟢" if momentum >= 60 else ("Yatay 🟡" if momentum >= 40 else "Zayıf 🔴"),
                    "Düşük Risk 🟢" if risk >= 60 else ("Orta Risk 🟡" if risk >= 40 else "Yüksek Risk 🔴"),
                ],
            })
            st.dataframe(faktor_df, use_container_width=True, hide_index=True)

        with col_right:
            section("📊 Teknik ve Temel Göstergeler")
            t_col1, t_col2 = st.columns(2)
            with t_col1:
                st.markdown("**Teknik Seviyeler**")
                teknik_data = {
                    "SMA 20": sma20_val,
                    "SMA 50": f"${raw_result.get('sma_50', 'N/A')}",
                    "SMA 200": f"${raw_result.get('sma_200', 'N/A')}",
                    "RSI (14)": f"{rsi_val:.1f}",
                    "SMA50 Uzaklık": f"{raw_result.get('sma50_atr_uzaklik', 'N/A')} ATR",
                    "12-1 Momentum": f"%{(raw_result.get('momentum_12_1', 0) or 0) * 100:.1f}",
                }
                st.dataframe(pd.DataFrame(list(teknik_data.items()), columns=["Metrik", "Değer"]), use_container_width=True, hide_index=True)
            with t_col2:
                st.markdown("**Temel Rasyolar**")
                temel_data = {
                    "F/K Oranı": f"{raw_result.get('pe_orani', 'N/A')}",
                    "Borç/Özkaynak": f"{raw_result.get('borc_ozkaynak', 'N/A')}",
                    "FCF Getirisi": f"%{raw_result.get('fcf_getiri', 'N/A')}",
                    "Gelir Büyümesi": f"%{raw_result.get('gelir_buyume', 'N/A')}",
                    "Temettü Verimi": f"%{raw_result.get('temettu_verimi', 0.0):.2f}",
                    "Toplam Faktör Skoru": f"%{f_skor:.1f}",
                }
                st.dataframe(pd.DataFrame(list(temel_data.items()), columns=["Metrik", "Değer"]), use_container_width=True, hide_index=True)

            section("⚖️ 4-Faktör Çatışma & Uyum Analizi")
            if conflict_info["has_conflict"]:
                for c_txt in conflict_info["conflicts"]:
                    st.warning(c_txt)
            else:
                st.success(conflict_info["headline"])
            for s_txt in conflict_info["strengths"]:
                st.info(s_txt)

        with st.expander("❓ 4 Faktör Sütunu (Kalite, Değer, Momentum, Risk) Ne Anlama Gelir?", expanded=False):
            st.markdown(
                """
                * **Kalite (Quality - %35 Ağırlık):** Şirketin kârlılığı, özkaynak kârlılığı (ROE), borç durumu ve gelir büyümesi. Yüksek puan = Kaya gibi sağlam bilanço.
                * **Değer (Value - %20 Ağırlık):** Hissenin ucuzluğu (F/K oranı, Serbest Nakit Akımı verimi ve teknik iskonto). Yüksek puan = İskontolu / Fırsat fiyatı.
                * **Momentum (%30 Ağırlık):** Hissenin son 6 ve 12 aydaki yükseliş gücü ve trend yönü. Yüksek puan = Kurumsal para hisseyi yukarı itiyor.
                * **Risk Dayanımı (%15 Ağırlık):** Hissenin dalgalanması (volatilitesi) ve geçmiş düşüş derinliği. Yüksek puan = Sert düşüşlere karşı korunaklı, az sarsan hisse.
                """
            )

    # ─── SEKME 4: BİLANÇO KARNESİ & ALTERNATİF KIYAS ───
    with tab_bilanco:
        section("📅 Katalizör & Bilanço Geçmişi Karnesi (Bilanço Kumarı Röntgeni)")
        st.caption("Bir şirketin iyi bilanço açıklaması her zaman yükseliş getirmez. Son bilançolarda ertesi gün ne yaptığını buradan kontrol et.")

        if earnings_info.get("next_earnings_date"):
            st.markdown(
                f"📌 **Bir Sonraki Bilanço Tarihi:** `{earnings_info['next_earnings_date']}` "
                f"(**{earnings_info['days_to_earnings']} gün** kaldı) | "
                f"**Son 15 Günlük Fiyat Değişimi:** `%{earnings_info['pre_earnings_runup_15d_pct']:+.1f}`"
            )
        if earnings_info.get("priced_in_warning"):
            st.warning(
                f"⚠️ **Beklenti Önceden Fiyatlanmış Olabilir!** {sembol} bilançoya günler kala son 15 günde "
                f"**+%{earnings_info['pre_earnings_runup_15d_pct']:.1f}** yükselmiş. İyi bilanço gelse bile 'beklenti bitti' satışı (Sell the news) yaşanabilir!"
            )

        st.info(f"📊 **Bilanço İstatistiği:** {earnings_info['summary_text']}")

        if earnings_info.get("history_rows"):
            clean_e_rows = [{k: v for k, v in r.items() if not k.startswith("_")} for r in earnings_info["history_rows"]]
            st.dataframe(pd.DataFrame(clean_e_rows), use_container_width=True, hide_index=True)

        if opp_info and opp_info.get("stats"):
            section("🔄 Alternatif Fırsat Kıyası (Endeks veya Çip ETF'i Alsaydın Ne Olurdu?)")
            st.caption(f"{sembol} hissesinde tekil şirket riski almak yerine S&P 500 (SPY) veya Yarı İletken ETF'i (SMH) tutmanın 3 aylık karşılaştırması:")
            st.markdown(opp_info["verdict"])
            opp_rows = []
            for k_sym, k_val in opp_info["stats"].items():
                label_name = (
                    f"🎯 {k_sym} (İncelenen Hisse)"
                    if k_sym == sembol
                    else ("🇺🇸 SPY (S&P 500 Endeksi)" if k_sym == "SPY" else "🔌 SMH (Yarı İletken / Çip ETF)")
                )
                opp_rows.append({
                    "Varlık": label_name,
                    "1 Aylık Getiri": f"%{k_val['ret_1m']:+.1f}",
                    "3 Aylık Getiri": f"%{k_val['ret_3m']:+.1f}",
                    "Zirveden En Derin Düşüş (6 Ay)": f"%{k_val['max_dd']:.1f}",
                    "Yıllık Oynaklık (Volatilite)": f"%{k_val['vol']:.1f}",
                })
            st.dataframe(pd.DataFrame(opp_rows), use_container_width=True, hide_index=True)
