"""
Sayfa 2: Tek Hisse Derinlemesine Analiz (Stock Deep-Dive)
Canlı fiyat, kurumsal 4-sütun faktör modeli, teknik göstergeler ve profesyonel Uzman Yorumu.
"""
import streamlit as st
import plotly.graph_objects as go
import yfinance as yf
import pandas as pd
import numpy as np
import sqlite3
import sys
import os
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from stock_value_engine import (
        hisse_faktorlerini_hesapla,
        vix_verisi_oku,
        spy_12ay_verisi_oku,
        sektor_rotasyonu_radar,
        kurulum_karari_belirle,
        bilanco_yakin_mi,
        KURUMSAL_HAVUZ,
    )
    ENGINE_AVAILABLE = True
except ImportError as e:
    ENGINE_AVAILABLE = False
    st.error(f"Motor import hatası: {e}")

DB_PATH = os.path.join(PROJECT_ROOT, "trading_bot.db")

def karar_badge(karar):
    badge_map = {
        "AL_ADAYI": ("🟢 AL ADAYI", "badge-al"),
        "KALITELI_GERI_CEKILME": ("🟢 KALİTELİ GERİ ÇEKİLME", "badge-al"),
        "TREND_DEVAMI": ("🟢 TREND DEVAMI", "badge-al"),
        "PAPER_TOP20": ("🟢 PAPER TOP 20", "badge-al"),
        "PAPER_SHADOW": ("🟢 PAPER ADAYI", "badge-al"),
        "BEKLE_GERI_CEKILME": ("🟡 GERİ ÇEKİLME BEKLE", "badge-bekle"),
        "UZAMIS_TREND": ("🟡 UZAMIŞ TREND", "badge-bekle"),
        "IZLE": ("🔵 İZLE", "badge-izle"),
        "REDDET_TREND": ("🔴 REDDET", "badge-reddet"),
        "DUSUS_TRENDI": ("🔴 DÜŞÜŞ TRENDİ", "badge-reddet"),
        "OLAY_RISKI": ("🟣 OLAY RİSKİ", "badge-olay"),
        "VERI_YETERSIZ": ("⚪ İZLEMEDE", "badge-izle"),
    }
    label, css_class = badge_map.get(karar, (karar, "badge-izle"))
    return f'<span class="{css_class}">{label}</span>'

def get_live_quote(sembol):
    """En güncel anlık fiyatı ve günlük değişimi çeker."""
    try:
        t = yf.Ticker(sembol)
        fast = getattr(t, 'fast_info', {})
        last_price = fast.get('lastPrice')
        prev_close = fast.get('previousClose')
        
        if not last_price:
            info = t.info or {}
            last_price = info.get('currentPrice') or info.get('regularMarketPrice')
            prev_close = info.get('regularMarketPreviousClose') or prev_close

        if not last_price:
            hist = t.history(period='2d')
            if not hist.empty:
                last_price = float(hist['Close'].iloc[-1])
                if len(hist) > 1:
                    prev_close = float(hist['Close'].iloc[-2])

        change = (last_price - prev_close) if (last_price and prev_close) else 0.0
        change_pct = (change / prev_close * 100) if (prev_close and prev_close > 0) else 0.0
        return {
            'price': last_price or 0.0,
            'change': change,
            'change_pct': change_pct,
            'prev_close': prev_close or last_price or 0.0,
            'timestamp': datetime.now().strftime('%H:%M:%S TSİ')
        }
    except Exception:
        return {'price': 0.0, 'change': 0.0, 'change_pct': 0.0, 'prev_close': 0.0, 'timestamp': 'N/A'}

def get_stored_scores(sembol):
    """Veritabanından en son hesaplanmış çapraz-faktör skorlarını çeker."""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            SELECT ai_skor, quality_score, value_score, momentum_score, risk_score, decision, setup, as_of_date
            FROM hisse_sinyalleri
            WHERE sembol = ?
            ORDER BY id DESC LIMIT 1
        """, (sembol,))
        row = c.fetchone()
        conn.close()
        if row:
            return {
                'faktor_skor': row[0],
                'kalite_skor': row[1],
                'deger_skor': row[2],
                'momentum_skor': row[3],
                'risk_skor': row[4],
                'karar': row[5],
                'kurulum': row[6],
                'as_of_date': row[7]
            }
    except Exception:
        pass
    return None

def estimate_standalone_scores(raw_data):
    """Veritabanında olmayan hisseler için temel ve teknik verilere dayalı yaklaşık faktör skorları üretir."""
    roe = raw_data.get('roe') or 0.15
    pm = raw_data.get('profit_margin') or 0.10
    de = raw_data.get('debt_to_equity') or 1.0
    kalite = 50.0 + min(25.0, max(-25.0, (roe - 0.15) * 100)) + min(15.0, max(-15.0, (pm - 0.10) * 100))
    if de < 1.0: kalite += 10.0
    elif de > 2.5: kalite -= 15.0
    kalite = max(10.0, min(95.0, kalite))

    pe = raw_data.get('pe_orani') or 25.0
    fcf = (raw_data.get('fcf_getiri') or 3.0) / 100.0
    deger = 50.0
    if pe < 18.0: deger += 25.0
    elif pe > 40.0: deger -= 25.0
    if fcf > 0.05: deger += 15.0
    deger = max(10.0, min(95.0, deger))

    m12 = raw_data.get('momentum_12_1') or 0.0
    m6 = raw_data.get('momentum_6_1') or 0.0
    momentum = 50.0 + min(35.0, max(-35.0, m12 * 70)) + min(15.0, max(-15.0, m6 * 30))
    momentum = max(10.0, min(95.0, momentum))

    vol = raw_data.get('realized_vol_63d') or 0.30
    dd = abs(raw_data.get('max_drawdown_1y') or 0.20)
    risk = 60.0 - min(30.0, (vol - 0.20) * 100) - min(20.0, (dd - 0.15) * 50)
    risk = max(10.0, min(95.0, risk))

    faktor_skor = round(kalite * 0.35 + deger * 0.20 + momentum * 0.30 + risk * 0.15, 1)

    return {
        'kalite_skor': round(kalite, 1),
        'deger_skor': round(deger, 1),
        'momentum_skor': round(momentum, 1),
        'risk_skor': round(risk, 1),
        'faktor_skor': faktor_skor
    }

def evaluate_decision_standalone(sonuc):
    """Skorlar ve teknik göstergelere göre eyleme dönük karar üretir."""
    skor = sonuc.get('faktor_skor') or 50.0
    kalite = sonuc.get('kalite_skor') or 50.0
    fiyat = sonuc.get('fiyat')
    sma_50 = sonuc.get('sma_50')
    sma_200 = sonuc.get('sma_200')
    rsi = sonuc.get('rsi') or 50.0
    momentum = sonuc.get('momentum_12_1') or 0.0
    atr_uzaklik = sonuc.get('sma50_atr_uzaklik') or 0.0

    if sonuc.get('bilanco_riski'):
        return 'OLAY_RISKI', 'Yedi gün içinde bilanço riski var'

    trend_up = (fiyat and sma_200 and sma_50 and fiyat > sma_200 and sma_50 > sma_200 and momentum > 0)
    uzamis = (atr_uzaklik > 3.0) or (rsi > 72.0)

    if uzamis:
        return 'BEKLE_GERI_CEKILME', 'Fiyat SMA50 üzerinde fazla uzamış veya RSI aşırı alımda'

    if kalite >= 60 and fiyat and sma_200 and fiyat >= sma_200 * 0.95 and -1.5 <= atr_uzaklik <= 1.5 and 35 <= rsi <= 60 and skor >= 60:
        return 'AL_ADAYI', 'Kaliteli hissede SMA50 desteğine sağlıklı geri çekilme'

    if trend_up and not uzamis and 0.0 <= atr_uzaklik <= 2.5 and 45 <= rsi <= 70 and skor >= 65:
        return 'AL_ADAYI', 'Güçlü yükseliş trendi devam ediyor'

    if fiyat and sma_200 and sma_50 and fiyat < sma_200 and sma_50 < sma_200 and skor < 45:
        return 'REDDET_TREND', 'Fiyat ve SMA50 200 günlük ortalamanın altında, düşüş trendi'

    return 'IZLE', 'Faktör skorları nötr, takip ediliyor'

def generate_expert_commentary(sembol, price, sma50, sma200, rsi, kalite, deger, momentum, risk, f_skor, karar, bilanco_riski):
    """
    Kullanıcının istediği profesyonel, göstergelere dayalı ve yönlendirici Uzman Raporunu üretir.
    """
    price_val = price or 100.0
    sma50_val = sma50 if (sma50 and not pd.isna(sma50)) else price_val * 0.96
    sma200_val = sma200 if (sma200 and not pd.isna(sma200)) else price_val * 0.90
    rsi_val = rsi or 50.0

    # 1. Durum Tespiti
    if price_val >= sma200_val and price_val >= sma50_val:
        trend_metni = f"hisse hem 50 günlük (${sma50_val:.2f}) hem de 200 günlük (${sma200_val:.2f}) hareketli ortalamalarının üzerinde **güçlü bir boğa (yükseliş) trendini** koruyor."
    elif price_val >= sma200_val and price_val < sma50_val:
        trend_metni = f"hisse 200 günlük ana trend desteğinin (${sma200_val:.2f}) üzerinde kalmayı sürdürüyor ancak kısa vadede 50 günlük ortalamasının (${sma50_val:.2f}) altına sarkarak **düzeltme/soluklanma evresine** geçmiş durumda."
    else:
        trend_metni = f"hisse hem 50 günlük (${sma50_val:.2f}) hem de 200 günlük (${sma200_val:.2f}) ortalamalarının altında seyrederek **ayı/düşüş baskısı** altında işlem görüyor."

    # 2. Göstergelere Dayalı Neden & Uzman Tavsiyesi
    if bilanco_riski:
        teshis = f"⚠️ **Bilanço Riski Mevcut:** {sembol} önümüzdeki 7 gün içerisinde resmi çeyreklik bilançosunu açıklayacak."
        neden = f"Yapay zeka ve çip sektörü gibi yüksek beklentili alanlarda bilançolar çok sert fiyat boşluklarına (gap-down) sebep olabilir. Kalite puanı (%{kalite:.0f}) yüksek olsa bile bilanço belirsizliği en büyük risk faktörüdür."
        tavsiye = f"**Uzman Önerisi:** Şu an bu seviyeden (${price_val:.2f}) yeni pozisyon açılmasını **önermiyorum**. Bilançoyu nakitte izleyip, piyasanın rakamlara vereceği tepkiyi ve yön teyidini gördükten sonra oyuna girmek çok daha güvenli ve rasyonel bir adımdır."
        hedef_giris = f"${sma50_val * 0.97:.2f} - ${sma50_val:.2f} (Bilanço sonrası teyitli)"
        stop_level = f"${sma200_val * 0.95:.2f}"
        tp_level = f"${price_val * 1.15:.2f}"

    elif karar in ['BEKLE_GERI_CEKILME', 'UZAMIS_TREND'] or rsi_val >= 68.0:
        teshis = f"✋ **Acele Etmeyin — Fiyat Fazla Isınmış (Aşırı Alım):**"
        neden = f"RSI göstergesi **{rsi_val:.1f}** seviyesine tırmanarak aşırı alım sınırına dayanmış durumda. Ayrıca fiyat (${price_val:.2f}), 50 günlük ana desteğinden (${sma50_val:.2f}) yukarı doğru fazla uzaklaşmış (uzamış trend)."
        tavsiye = f"**Uzman Önerisi:** Göstergeler hissenin kısa vadede bir kâr satışı veya soluklanma yaşama olasılığının yüksek olduğunu gösteriyor. Treni kaçırma korkusuyla (FOMO) buradan tek seferde alım yapmanızı **tavsiye etmiyorum**. Fiyatın **${sma50_val:.2f} (SMA 50)** desteğine doğru geri çekilmesini ve RSI'ın 50 seviyesine gevşemesini bekleyin. Alım için bu düzeltmeyi kollayın."
        hedef_giris = f"${sma50_val * 0.98:.2f} - ${sma50_val * 1.02:.2f} (Destek Teması)"
        stop_level = f"${sma50_val * 0.94:.2f}"
        tp_level = f"${price_val * 1.18:.2f}"

    elif karar in ['AL_ADAYI', 'KALITELI_GERI_CEKILME', 'TREND_DEVAMI', 'PAPER_TOP20']:
        teshis = f"🎯 **Fırsat Masada — İdeal Alım Pencerelerinden Biri:**"
        neden = f"Şirketin kurumsal Kalite puanı (%{kalite:.0f}) çok yüksek ve hisse hareketli ortalama desteğine (${sma50_val:.2f}) sağlıklı bir şekilde oturmuş. RSI ({rsi_val:.1f}) aşırı şişkinliğini atmış, risk/kazanç (RR) oranı yatırımcı lehine dönmüş durumda."
        tavsiye = f"**Uzman Önerisi:** Sistemimiz hisseyi alım için uygun buluyor. Ancak tek kurşun atmak yerine profesyonelce **2 Kademeli Alım** öneriyorum: Bütçenizin %40'ı ile buralardan (${price_val:.2f}) 1. Kademeyi açabilir, olası piyasa sarkmalarında kalan %60'ı ${sma200_val:.2f} (SMA 200) seviyesine saklayabilirsiniz."
        hedef_giris = f"${price_val:.2f} (Anlık 1. Kademe)"
        stop_level = f"${sma50_val * 0.93:.2f} (%7 Zarar Kes)"
        tp_level = f"${price_val * 1.20:.2f} (+%20 Kâr Al)"

    elif price_val < sma200_val:
        if kalite >= 65.0:
            teshis = f"💎 **Nadir İndirim Fırsatı — Kaliteli Dip Avcılığı:**"
            neden = f"Hisse 200 günlük ortalamasının (${sma200_val:.2f}) altına inerek teknik olarak düzeltme bölgesine girmiş. Ancak şirketin kurumsal **Kalite puanı (%{kalite:.0f}) ve temel rasyoları mükemmel** seviyede. Büyük fonlar bu çapta şirketler 200 SMA altına indiğinde bunu 'panik indirimi' olarak değerlendirir."
            tavsiye = f"**Uzman Önerisi:** İlla 50 günlüğün üzerine (${sma50_val:.2f}) çıkmasını beklemek kâr marjınızı düşürebilir. Çöp hisselerden uzak durulur ancak {sembol} gibi devlerde bu seviyeler (${price_val:.2f}) **Kademeli Dip Alımı** için çok caziptir. Bütçenizin %35-%40'ı ile buralardan 1. Kademeyi açabilir, olası piyasa sarkmalarında kalan %60'ı dip desteğine saklayabilirsiniz."
            hedef_giris = f"${price_val:.2f} (1. Kademe Alım)"
            stop_level = f"${sma200_val * 0.88:.2f} (Geniş Bant / Uzun Vade)"
            tp_level = f"${sma200_val * 1.15:.2f} (+%15 Tepki Yükselişi)"
        else:
            teshis = f"⛔ **Uzak Durun — Düşüş Trendi Aktif:**"
            neden = f"Fiyat hem 50 günlük (${sma50_val:.2f}) hem de 200 günlük (${sma200_val:.2f}) uzun vadeli trend çizgisinin altında ve hissenin kalite puanı (%{kalite:.0f}) riskli. 'Hisse çok düştü, ucuz' algısı yanıltıcı olabilir; düşen bıçak tutulmaz."
            tavsiye = f"**Uzman Önerisi:** Kurumsal alıcıların devreye girdiğine dair yeşil bir teyit mumu görmeden ve fiyat en azından 50 günlük ortalamanın üzerine çıkmadan **alım yapmanızı kesinlikle önermiyorum**. Şu aşamada nakitte beklemek en doğru karardır."
            hedef_giris = f"Giriş önerilmiyor (Düşüş bitene kadar izle)"
            stop_level = "N/A"
            tp_level = "N/A"

    else: # IZLE
        teshis = f"⏳ **İzle ve Pusuya Yat — Karar / Konsolidasyon Aşaması:**"
        neden = f"Hisse şu an ne net bir alım sinyali ne de acil bir satış baskısı üretiyor. RSI ({rsi_val:.1f}) tamamen nötr bantta. Fiyat ${sma50_val:.2f} ile ${sma200_val:.2f} arasında sıkışmış durumda ve piyasanın genel yönünü bekliyor."
        tavsiye = f"**Uzman Önerisi:** Sistem şu göstergelere göre henüz kesin alım noktasında değil: Fiyat henüz net bir destek teması yapmadı veya yukarı yönlü hacimli bir kırılım gerçekleştirmedi. Bu yüzden acele etmeyip **biraz izlemenizi ve sabırla beklemenizi tavsiye ediyorum**. Fiyat ${sma50_val:.2f} seviyesini hacimle yukarı kırarsa trene binilebilir veya ${sma200_val:.2f} desteğine değerse dipten toplanabilir."
        hedef_giris = f"${sma200_val * 1.01:.2f} (Dipten temas) VEYA ${sma50_val * 1.02:.2f} (Yukarı kırılım)"
        stop_level = f"${sma200_val * 0.95:.2f}"
        tp_level = f"${price_val * 1.15:.2f}"

    return {
        'trend_metni': trend_metni,
        'teshis': teshis,
        'neden': neden,
        'tavsiye': tavsiye,
        'hedef_giris': hedef_giris,
        'stop_level': stop_level,
        'tp_level': tp_level
    }

def radar_chart(kalite, deger, momentum, risk):
    categories = ['Kalite', 'Değer', 'Momentum', 'Risk Dayanımı']
    values = [kalite, deger, momentum, risk]
    values_closed = values + [values[0]]
    categories_closed = categories + [categories[0]]

    fig = go.Figure()
    fig.add_trace(go.Scatterpolar(
        r=values_closed,
        theta=categories_closed,
        fill='toself',
        name='Faktör Skoru',
        line=dict(color='#64ffda', width=2),
        fillcolor='rgba(100, 255, 218, 0.18)',
    ))
    fig.update_layout(
        polar=dict(
            bgcolor='rgba(0,0,0,0)',
            radialaxis=dict(visible=True, range=[0, 100], tickfont=dict(size=10, color='#8892b0')),
            angularaxis=dict(tickfont=dict(size=12, color='#ccd6f6')),
        ),
        showlegend=False,
        height=350,
        margin=dict(l=50, r=50, t=20, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
    )
    return fig

def fiyat_grafigi(sembol):
    try:
        t = yf.Ticker(sembol)
        data = t.history(period="1y")
        if data.empty:
            return None

        data['SMA20'] = data['Close'].rolling(20).mean()
        data['SMA50'] = data['Close'].rolling(50).mean()
        data['SMA200'] = data['Close'].rolling(200).mean()

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=data.index, open=data['Open'], high=data['High'],
            low=data['Low'], close=data['Close'], name='Fiyat',
            increasing_line_color='#00c853', decreasing_line_color='#f44336',
        ))
        fig.add_trace(go.Scatter(x=data.index, y=data['SMA20'], name='SMA 20', line=dict(color='#ff9800', width=1, dash='dot')))
        fig.add_trace(go.Scatter(x=data.index, y=data['SMA50'], name='SMA 50', line=dict(color='#2196f3', width=1.5)))
        fig.add_trace(go.Scatter(x=data.index, y=data['SMA200'], name='SMA 200', line=dict(color='#9c27b0', width=2)))
        fig.update_layout(
            height=450,
            xaxis_rangeslider_visible=False,
            template='plotly_dark',
            margin=dict(l=10, r=10, t=10, b=10),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        )
        return fig
    except Exception:
        return None

# ─── UI BAŞLANGICI ───
st.markdown("## 🔍 Tek Hisse Derinlemesine Analiz")
st.caption("Herhangi bir ABD hisse senedinin anlık canlı fiyatı, 4-Sütunlu faktör modeli, teknik göstergeleri ve yapay zeka uzman yorumu.")

with st.expander("❓ 4 Faktör Sütunu (Kalite, Değer, Momentum, Risk) Ne Anlama Gelir? (Tıkla & Oku)", expanded=False):
    st.markdown("""
    * **Kalite (Quality - %35 Ağırlık):** Şirketin kârlılığı, özkaynak kârlılığı (ROE), borç durumu ve gelir büyümesi. Yüksek puan = Kaya gibi sağlam bilanço.
    * **Değer (Value - %20 Ağırlık):** Hissenin ucuzluğu (F/K oranı, Serbest Nakit Akımı verimi). Yüksek puan = İskontolu / Fırsat fiyatı.
    * **Momentum (%30 Ağırlık):** Hissenin son 6 ve 12 aydaki yükseliş gücü ve trend yönü. Yüksek puan = Kurumsal para hisseyi yukarı itiyor.
    * **Risk Dayanımı (%15 Ağırlık):** Hissenin dalgalanması (volatilitesi) ve geçmiş düşüş derinliği. Yüksek puan = Sert düşüşlere karşı korunaklı, az sarsan hisse.
    """)

col_input, col_btn = st.columns([3, 1])
with col_input:
    sembol_input = st.text_input(
        "Hisse Sembolü",
        placeholder="Örn: AVGO, MU, AAPL, BE, NVDA, TSLA, EOG",
        label_visibility="collapsed",
    )
with col_btn:
    analiz_btn = st.button("🚀 Canlı Analiz Et", type="primary", use_container_width=True)

if analiz_btn and sembol_input:
    sembol = sembol_input.upper().strip()

    with st.spinner(f"🔄 {sembol} için canlı piyasa ve faktör verileri çekiliyor..."):
        quote = get_live_quote(sembol)
        
        vix_degeri = 18.5
        spy_getiri = 0.15
        sektor_perf = {}
        try:
            v_res = vix_verisi_oku()
            if v_res.uygun: vix_degeri = v_res.value
            s_res = spy_12ay_verisi_oku()
            if s_res.uygun: spy_getiri = s_res.value
            sektor_perf = sektor_rotasyonu_radar() or {}
        except Exception:
            pass

        sektor = KURUMSAL_HAVUZ.get(sembol, 'Teknoloji')
        raw_result = hisse_faktorlerini_hesapla(sembol, sektor, vix_degeri, spy_getiri, sektor_perf)

        if quote['price'] > 0:
            raw_result['fiyat'] = quote['price']

        stored = get_stored_scores(sembol)
        if stored and stored.get('faktor_skor') is not None:
            kalite = stored.get('kalite_skor') or 50.0
            deger = stored.get('deger_skor') or 50.0
            momentum = stored.get('momentum_skor') or 50.0
            risk = stored.get('risk_skor') or 50.0
            f_skor = stored.get('faktor_skor') or 50.0
            score_source = f"Kurumsal Havuz Taraması ({stored.get('as_of_date', 'Güncel')})"
        else:
            standalone = estimate_standalone_scores(raw_result)
            kalite = standalone['kalite_skor']
            deger = standalone['deger_skor']
            momentum = standalone['momentum_skor']
            risk = standalone['risk_skor']
            f_skor = standalone['faktor_skor']
            score_source = "Dinamik Temel & Teknik Faktör Modellemesi"

        # Gerçek SMA 20'yi hesapla
        sma20_val = "N/A"
        try:
            h_data = yf.Ticker(sembol).history(period="2mo")
            if not h_data.empty and len(h_data) >= 20:
                sma20_val = f"${h_data['Close'].rolling(20).mean().iloc[-1]:.2f}"
            else:
                sma20_val = f"${quote['price']:.2f}"
        except Exception:
            sma20_val = f"${quote['price']:.2f}"

        karar, karar_nedeni = evaluate_decision_standalone(raw_result)
        bilanco_var_mi = False
        try:
            bilanco_var_mi = bilanco_yakin_mi(sembol)
        except Exception:
            pass

        # Uzman Yorumu ve Detaylı Tavsiyeyi Üret
        commentary = generate_expert_commentary(
            sembol=sembol,
            price=quote['price'],
            sma50=raw_result.get('sma_50'),
            sma200=raw_result.get('sma_200'),
            rsi=raw_result.get('rsi'),
            kalite=kalite,
            deger=deger,
            momentum=momentum,
            risk=risk,
            f_skor=f_skor,
            karar=karar,
            bilanco_riski=bilanco_var_mi
        )

    # ─── METRİK KARTLARI ───
    st.divider()
    chg_sign = "+" if quote['change'] >= 0 else ""
    
    h1, h2, h3, h4, h5 = st.columns(5)
    with h1:
        st.markdown(f"""<div class="metric-card">
            <h3>Canlı Fiyat ({quote['timestamp']})</h3>
            <h1>${quote['price']:.2f}</h1>
            <span style="color: {'#00c853' if quote['change']>=0 else '#f44336'}; font-weight: bold;">
                {chg_sign}{quote['change']:.2f} ({chg_sign}{quote['change_pct']:.2f}%)
            </span>
        </div>""", unsafe_allow_html=True)
    with h2:
        sma200 = raw_result.get('sma_200', 0)
        trend_status = "Üstünde 🟢" if quote['price'] >= sma200 else "Altında 🔴"
        st.markdown(f"""<div class="metric-card">
            <h3>SMA 200 ({trend_status})</h3>
            <h1>${sma200:.2f}</h1>
            <span style="color: #8892b0;">Uzun Vade Trend</span>
        </div>""", unsafe_allow_html=True)
    with h3:
        rsi_val = raw_result.get('rsi', 50.0)
        rsi_state = "Aşırı Satım 🔥" if rsi_val < 35 else ("Aşırı Alım ⚠️" if rsi_val > 70 else "Nötr ⚖️")
        st.markdown(f"""<div class="metric-card">
            <h3>RSI (14)</h3>
            <h1>{rsi_val:.1f}</h1>
            <span style="color: #8892b0;">{rsi_state}</span>
        </div>""", unsafe_allow_html=True)
    with h4:
        st.markdown(f"""<div class="metric-card">
            <h3>Faktör Skoru</h3>
            <h1>%{f_skor:.1f}</h1>
            <span style="color: #64ffda;">{score_source}</span>
        </div>""", unsafe_allow_html=True)
    with h5:
        st.markdown(f"""<div class="metric-card">
            <h3>Sistem Kararı</h3>
            <h1>{karar_badge(karar)}</h1>
            <span style="color: #ccd6f6; font-size: 0.8rem;">{karar_nedeni}</span>
        </div>""", unsafe_allow_html=True)

    if bilanco_var_mi:
        st.warning("⚠️ **OLAY RİSKİ:** Bu hissenin çeyreklik bilançosu 7 takvim günü içinde açıklanacak!")

    # ─── YENİ: UZMAN DEĞERLENDİRMESİ & AKSİYON REHBERİ KARTI ───
    st.markdown("""
    <style>
        .expert-box {
            background: linear-gradient(135deg, #0d1f3c 0%, #112240 100%);
            border: 1px solid #64ffda;
            border-radius: 12px;
            padding: 1.5rem;
            margin-top: 1rem;
            margin-bottom: 1rem;
        }
        .expert-box h3 { color: #64ffda; margin-top: 0; font-size: 1.25rem; }
        .target-pill {
            background: rgba(100, 255, 218, 0.1);
            border: 1px solid #64ffda;
            border-radius: 8px;
            padding: 8px 14px;
            display: inline-block;
            margin-right: 10px;
            font-size: 0.9rem;
        }
    </style>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="expert-box">
        <h3>🧠 Quant & Uzman Değerlendirmesi: {sembol}</h3>
        <p style="font-size: 1rem; color: #ccd6f6; line-height: 1.6;">
            <b>Mevcut Trend:</b> {sembol}, {commentary['trend_metni']}
        </p>
        <p style="font-size: 1rem; color: #ccd6f6; line-height: 1.6;">
            {commentary['teshis']}<br>
            {commentary['neden']}
        </p>
        <div style="background: rgba(0, 0, 0, 0.25); border-radius: 8px; padding: 12px; margin: 12px 0;">
            <p style="color: #64ffda; margin: 0; font-size: 1.05rem; line-height: 1.5;">
                {commentary['tavsiye']}
            </p>
        </div>
        <div style="margin-top: 15px;">
            <span class="target-pill">🎯 <b>İdeal Giriş Bölgesi:</b> {commentary['hedef_giris']}</span>
            <span class="target-pill" style="border-color: #f44336; color: #ff8a80;">🛡️ <b>Zarar Durdur (SL):</b> {commentary['stop_level']}</span>
            <span class="target-pill" style="border-color: #00c853; color: #b9f6ca;">💰 <b>Hedef Kâr (TP):</b> {commentary['tp_level']}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ─── 4 SÜTUNLU RADAR & DETAYLAR ───
    st.divider()
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("### 📡 4-Sütun Faktör Radarı")
        fig_radar = radar_chart(kalite, deger, momentum, risk)
        st.plotly_chart(fig_radar, use_container_width=True)

        st.markdown("### 📋 Faktör Puan Dağılımı")
        faktor_df = pd.DataFrame({
            "Sütun": ["Kalite (%35)", "Değer (%20)", "Momentum (%30)", "Risk Dayanımı (%15)"],
            "Puan (0-100)": [f"{kalite:.1f}", f"{deger:.1f}", f"{momentum:.1f}", f"{risk:.1f}"],
            "Durum": [
                "Çok Güçlü 🟢" if kalite >= 70 else ("Orta 🟡" if kalite >= 45 else "Zayıf 🔴"),
                "İskontolu 🟢" if deger >= 60 else ("Makul 🟡" if deger >= 40 else "Pahalı 🔴"),
                "Güçlü Trend 🟢" if momentum >= 60 else ("Yatay 🟡" if momentum >= 40 else "Zayıf 🔴"),
                "Düşük Risk 🟢" if risk >= 60 else ("Orta Risk 🟡" if risk >= 40 else "Yüksek Risk 🔴"),
            ]
        })
        st.dataframe(faktor_df, use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("### 📊 Teknik ve Temel Göstergeler")
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.markdown("**Teknik Seviyeler**")
            teknik_data = {
                "SMA 20": sma20_val,
                "SMA 50": f"${raw_result.get('sma_50', 'N/A')}",
                "SMA 200": f"${raw_result.get('sma_200', 'N/A')}",
                "SMA50 Uzaklık": f"{raw_result.get('sma50_atr_uzaklik', 'N/A')} ATR",
                "12-1 Momentum": f"%{(raw_result.get('momentum_12_1', 0) or 0)*100:.1f}",
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
            }
            st.dataframe(pd.DataFrame(list(temel_data.items()), columns=["Metrik", "Değer"]), use_container_width=True, hide_index=True)

    st.markdown("### 📈 1 Yıllık Canlı Fiyat Grafiği (SMA 20 / 50 / 200)")
    fig_price = fiyat_grafigi(sembol)
    if fig_price:
        st.plotly_chart(fig_price, use_container_width=True)
    else:
        st.info("Fiyat grafiği çizilemedi.")

elif not sembol_input and analiz_btn:
    st.warning("Lütfen analiz etmek istediğiniz hisse sembolünü girin (Örn: AVGO, MU, AAPL, BE, NVDA, TSLA, EOG).")
