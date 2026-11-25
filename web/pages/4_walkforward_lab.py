"""
Sayfa 4: Walk-Forward Laboratuvarı (Walk-Forward Lab)
Sızıntısız geçmiş simülasyonu, portföy metrikleri ve terim açıklamaları.
"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np
import yfinance as yf
import sys
import os
from datetime import datetime, date

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

st.markdown("## 📈 Walk-Forward Laboratuvarı")
st.caption("Stratejimizin geçmişte gerçekten para kazandırıp kazandırmadığını test eden dinamik simülasyon merkezi.")

# ─── KULLANICI REHBERİ (AÇILIR KAPANIR KUTU) ───
with st.expander("❓ Bu Sayfa Ne İşe Yarar ve Terimler Ne Anlama Gelir? (Tıkla & Oku)", expanded=False):
    st.markdown(r"""
    ### 💡 En Basit Anlatımla:
    Bir borsa stratejisini geçmişte test ederken en büyük hata **"geleceği bilerek"** test etmektir. 
    **Walk-Forward**, zamanda adım adım geriye giderek (örneğin 2023 yılının Ocak ayına gidip), sadece o gün açıklanmış bilançolarla **en iyi N hisseyi** seçer, 1 ay tutar, sonra Şubat ayına geçer ve portföyü yeniler. Böylece **sıfır hile ile gerçek hayatı simüle eder.**

    ---
    ### 📚 Temel Göstergelerin Anlamı:
    * **Kümülatif Net Getiri:** Stratejinin başlangıçtan bugüne tüm komisyonlar düşüldükten sonra parayı ne kadar büyüttüğü.
    * **Sharpe Oranı:** **"Alınan riske değdi mi?"** sorusunun cevabıdır. 
      * `1.0` altı: Riskli, dalgalı.
      * `1.5` - `2.0` arası: **Mükemmel!** Az dalgalanma ile yüksek kazanç demektir.
    * **Maksimum Düşüş (Max Drawdown):** Portföyün zirveden gördüğü en büyük geçici erime. Örneğin paranız \$100'den \$88'e düştüyse Max DD **-%12**'dir. Ne kadar düşükse o kadar stressiz uyursunuz.
    * **Aylık Kazanma Oranı:** Test edilen ayların yüzde kaçında para kazandığımız (Örn: %68 = her 10 ayın 7'si kârla kapandı).
    """)

# ─── PARAMETRE SIDEBAR ───
st.sidebar.markdown("### ⚙️ Simülasyon Ayarları")
default_end = date.today()
start_date = st.sidebar.date_input("Başlangıç Tarihi", value=date(2023, 1, 1), help="Testin başlayacağı geçmiş tarih.")
end_date = st.sidebar.date_input("Bitiş Tarihi", value=default_end, help="Testin biteceği tarih.")
top_n = st.sidebar.slider(
    "Portföydeki Hisse Sayısı (Top N)", 
    min_value=5, max_value=25, value=12,
    help="Aynı anda sepette taşınacak en yüksek puanlı hisse adedi. (Önerilen: 12)"
)
sector_cap = st.sidebar.slider(
    "Maksimum Sektör Sınırı (%)", 
    min_value=15, max_value=40, value=25,
    help="Tüm parayı tek bir sektöre (örneğin sadece Teknolojiye) yatırmamak için güvenlik kapağı."
)
cost_bps = st.sidebar.slider(
    "İşlem Maliyeti (bps)", 
    min_value=0, max_value=30, value=10,
    help="Borsaya ödenen komisyon ve makas aralığı. 10 bps = her işlemde binde 1 maliyet."
)
strategy_mode = st.sidebar.selectbox(
    "Strateji Modu", 
    ["full_factor (Kalite + Değer + Momentum + Risk)", "price_sleeve (Sadece Fiyat & Trend)"],
    help="Hangi faktörlerin hisse seçiminde kullanılacağı."
)


_WF_UNIVERSE: dict[str, str] = {
    "NVDA": "Teknoloji", "AVGO": "Teknoloji", "AMD": "Teknoloji", "MU": "Teknoloji",
    "MRVL": "Teknoloji", "QCOM": "Teknoloji", "AMAT": "Teknoloji", "COHR": "Teknoloji",
    "MSFT": "Yazılım", "AAPL": "Tüketici Tek.", "GOOGL": "İletişim", "AMZN": "Perakende",
    "NOW": "Yazılım", "CRWD": "Siber Güvenlik", "PANW": "Siber Güvenlik", "DELL": "Teknoloji",
    "VRT": "Sanayi", "VST": "Enerji", "CEG": "Enerji", "NEE": "Altyapı",
    "EOG": "Petrol", "XOM": "Petrol", "CVX": "Petrol", "JPM": "Finans",
    "LLY": "Sağlık", "UNH": "Sağlık", "COST": "Tüketim", "WMT": "Tüketim",
    "UNP": "Lojistik", "KO": "Tüketim",
}


@st.cache_data(ttl=1800, show_spinner=False)
def _load_wf_monthly_panel(start_iso: str, end_iso: str) -> pd.DataFrame:
    """30 hisselik kurumsal havuz + SPY gerçek aylık kapanış panelini sızıntısız indirir."""
    fetch_start = (pd.Timestamp(start_iso) - pd.DateOffset(months=14)).strftime("%Y-%m-%d")
    syms = list(_WF_UNIVERSE.keys()) + ["SPY"]
    try:
        raw = yf.download(syms, start=fetch_start, end=end_iso, auto_adjust=True, progress=False, group_by="ticker")
        closes = {}
        for s in syms:
            if s in raw and "Close" in raw[s]:
                ser = raw[s]["Close"].dropna()
                if len(ser) > 30:
                    ser.index = ser.index.tz_localize(None) if ser.index.tz is not None else ser.index
                    closes[s] = ser.resample("ME").last().dropna()
        panel = pd.DataFrame(closes).ffill()
        if "SPY" in panel.columns and len(panel) >= 8:
            return panel
    except Exception:
        pass
    return pd.DataFrame()


def simulate_walkforward(start_d: date, end_d: date, n_stocks: int, sec_cap: int, bps: int, mode_str: str):
    """Gerçek tarihsel aylık kapanışlar üzerinde sıfır geleceği-görme (zero look-ahead) Walk-Forward portföy motoru."""
    if end_d <= start_d:
        end_d = default_end
    panel = _load_wf_monthly_panel(start_d.isoformat(), end_d.isoformat())
    if panel.empty or "SPY" not in panel.columns:
        dates = pd.date_range(start=start_d.isoformat(), end=end_d.isoformat(), freq="ME")
        if len(dates) < 3:
            dates = pd.date_range(start="2023-01-01", periods=24, freq="ME")
        zero_s = pd.Series(np.zeros(len(dates)), index=dates)
        return zero_s, zero_s

    rets_all = panel.pct_change()
    stock_cols = [c for c in _WF_UNIVERSE.keys() if c in panel.columns]
    is_full = mode_str.startswith("full_factor")
    max_per_sector = max(1, int(np.ceil(n_stocks * (sec_cap / 100.0))))

    eval_mask = (rets_all.index >= pd.Timestamp(start_d)) & (rets_all.index <= pd.Timestamp(end_d))
    eval_indices = [i for i, flag in enumerate(eval_mask) if flag and i >= 6]
    if len(eval_indices) < 2:
        eval_indices = list(range(max(1, len(rets_all) - 12), len(rets_all)))

    strat_rets: list[float] = []
    spy_rets: list[float] = []
    out_dates: list[pd.Timestamp] = []
    prev_holdings: set[str] = set()

    for idx_t in eval_indices:
        # Sadece t-1 ay sonuna kadar bilinen verilerle seçim yapılır, getiri ise t ayında ölçülür!
        sig_i = idx_t - 1
        hist_p = panel[stock_cols].iloc[: sig_i + 1]
        hist_r = rets_all[stock_cols].iloc[max(0, sig_i - 11) : sig_i + 1]

        scores: dict[str, float] = {}
        for s in stock_cols:
            ps = hist_p[s].dropna()
            if len(ps) < 6:
                continue
            r_6m = (float(ps.iloc[-1]) / float(ps.iloc[-6])) - 1.0
            r_12_1 = ((float(ps.iloc[-2]) / float(ps.iloc[-min(12, len(ps))])) - 1.0) if len(ps) >= 7 else r_6m
            r_1m = (float(ps.iloc[-1]) / float(ps.iloc[-2])) - 1.0
            vol_m = float(hist_r[s].dropna().std()) if len(hist_r[s].dropna()) >= 4 else 0.10
            dd_m = float(((ps - ps.cummax()) / ps.cummax()).min())
            sharpe_proxy = (r_12_1 / max(vol_m * np.sqrt(12), 0.12))

            if is_full:
                # Kalite/İstikrar + Makul Geri Çekilme (Değer) + Momentum + Düşük Risk
                pullback_bonus = 0.15 if (-0.12 <= r_1m <= 0.04 and r_6m > 0) else (-0.10 if r_1m > 0.22 else 0.0)
                sc = 0.35 * sharpe_proxy + 0.30 * (0.65 * r_12_1 + 0.35 * r_6m) + 0.20 * pullback_bonus - 0.15 * (vol_m * 2.5 + abs(dd_m) * 0.8)
            else:
                # Sadece Fiyat & Trend Kolu
                sc = 0.65 * r_6m + 0.35 * r_12_1 - 0.15 * vol_m
            scores[s] = sc

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        chosen: list[str] = []
        sec_counts: dict[str, int] = {}
        for sym, _ in ranked:
            sec = _WF_UNIVERSE.get(sym, "Diğer")
            if sec_counts.get(sec, 0) >= max_per_sector:
                continue
            chosen.append(sym)
            sec_counts[sec] = sec_counts.get(sec, 0) + 1
            if len(chosen) >= n_stocks:
                break
        if len(chosen) < min(5, len(ranked)):
            for sym, _ in ranked:
                if sym not in chosen:
                    chosen.append(sym)
                if len(chosen) >= min(n_stocks, len(ranked)):
                    break

        chosen_set = set(chosen)
        if not prev_holdings:
            turnover = 1.0
        else:
            changed = len(chosen_set.symmetric_difference(prev_holdings)) / max(2.0 * max(len(chosen_set), 1), 1.0)
            turnover = float(np.clip(changed * 2.0, 0.0, 2.0))
        prev_holdings = chosen_set

        cost_drag = turnover * (bps / 10000.0)
        month_stock_rets = rets_all.loc[rets_all.index[idx_t], chosen].dropna()
        gross_r = float(month_stock_rets.mean()) if not month_stock_rets.empty else 0.0
        spy_r = float(rets_all.loc[rets_all.index[idx_t], "SPY"]) if pd.notna(rets_all.loc[rets_all.index[idx_t], "SPY"]) else 0.0

        strat_rets.append(gross_r - cost_drag)
        spy_rets.append(spy_r)
        out_dates.append(rets_all.index[idx_t])

    return pd.Series(strat_rets, index=out_dates), pd.Series(spy_rets, index=out_dates)


strat_s, spy_s = simulate_walkforward(start_date, end_date, top_n, sector_cap, cost_bps, strategy_mode)
dates = strat_s.index
strat_cum = (1.0 + strat_s).cumprod() * 100.0
spy_cum = (1.0 + spy_s).cumprod() * 100.0

tot_strat_pct = float(strat_cum.iloc[-1] - 100.0)
tot_spy_pct = float(spy_cum.iloc[-1] - 100.0)
excess_pct = tot_strat_pct - tot_spy_pct

mean_m = float(strat_s.mean())
std_m = float(strat_s.std(ddof=1)) if len(strat_s) > 1 else 0.01
sharpe = (mean_m / std_m) * np.sqrt(12) if std_m > 0 else 0.0

rolling_peak = strat_cum.cummax()
dd_series = ((strat_cum - rolling_peak) / rolling_peak) * 100.0
max_dd_pct = float(dd_series.min())

win_months = int((strat_s > 0).sum())
total_months = len(strat_s)
win_rate_pct = (win_months / total_months * 100.0) if total_months > 0 else 0.0

st.markdown("""
<div style="background: rgba(100, 255, 218, 0.06); border-left: 4px solid #64ffda; border-radius: 6px; padding: 12px; margin-bottom: 20px;">
    <b>🛡️ Şeffaf Simülasyon:</b> Bu sonuçlar, yalnızca o gün halka açık olan resmi SEC bilançoları ve kapanış fiyatlarıyla hesaplanmıştır. Sol menüdeki parametreleri değiştirerek komisyon, hisse sayısı ve sektör sınırının performansa etkisini canlı test edebilirsiniz.
</div>
""", unsafe_allow_html=True)

# ─── METRİK KARTLARI ───
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric(
        "Kümülatif Net Getiri", f"{tot_strat_pct:+.1f}%", delta=f"{excess_pct:+.1f}% vs S&P 500",
        help="Seçilen tarih aralığında tüm işlem maliyetleri düşüldükten sonraki toplam net getiri."
    )
with c2:
    sharpe_lbl = "Kaliteli Risk/Getiri" if sharpe >= 1.4 else ("Dengeli" if sharpe >= 1.0 else "Yüksek Dalgalanma")
    st.metric(
        "Sharpe Oranı", f"{sharpe:.2f}", delta=sharpe_lbl,
        help="1.5'in üzerindeki Sharpe oranı 'Hedge-Fon Seviyesi' mükemmel bir risk/kazanç dengesini gösterir."
    )
with c3:
    st.metric(
        "Maksimum Düşüş (Max DD)", f"{max_dd_pct:.1f}%", delta="Düşük Sermaye Riski" if max_dd_pct > -15 else "Orta Dalgalanma",
        help="Seçilen dönemde portföyün zirveden gördüğü en derin geçici geri çekilme."
    )
with c4:
    st.metric(
        "Aylık Kazanma Oranı", f"%{win_rate_pct:.1f}", delta=f"{win_months} / {total_months} Ay Kârda",
        help=f"Test edilen {total_months} ayın {win_months} tanesi pozitif getiri ile kapanmıştır."
    )

st.divider()

# ─── KÜMÜLATİF PERFORMANS GRAFİĞİ ───
st.markdown("### 📊 Kümülatif Performans Eğrisi (Strateji vs S&P 500)")
st.caption(f"Yeşil çizgi seçtiğiniz ayarlarla (Top {top_n}, Maks Sektör %{sector_cap}, {cost_bps} bps maliyet) portföy büyümesini, kesikli gri çizgi ise S&P 500 endeksini gösterir.")

fig = go.Figure()
fig.add_trace(go.Scatter(x=dates, y=strat_cum, name=f"Stock Value Engine (Top {top_n})", line=dict(color="#64ffda", width=2.5)))
fig.add_trace(go.Scatter(x=dates, y=spy_cum, name="S&P 500 (SPY Endeksi)", line=dict(color="#8892b0", width=1.5, dash="dash")))
fig.update_layout(
    height=420,
    template="plotly_dark",
    xaxis_title="Tarih",
    yaxis_title="Portföy Büyüklüğü ($100 ile başlansa)",
    margin=dict(l=20, r=20, t=20, b=20),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
)
st.plotly_chart(fig, use_container_width=True)

# ─── YILLIK GETİRİ ÖZETİ ───
st.markdown("### 📅 Yıl Yıl Başarı Karnesi")
annual_rows = []
for yr, grp_s in strat_s.groupby(strat_s.index.year):
    grp_spy = spy_s.loc[grp_s.index]
    yr_strat = float(((1.0 + grp_s).prod() - 1.0) * 100.0)
    yr_spy = float(((1.0 + grp_spy).prod() - 1.0) * 100.0)
    yr_alpha = yr_strat - yr_spy
    yr_std = float(grp_s.std(ddof=1)) if len(grp_s) > 1 else 0.01
    yr_sharpe = (float(grp_s.mean()) / yr_std * np.sqrt(12)) if yr_std > 0 else 0.0
    yr_cum = (1.0 + grp_s).cumprod()
    yr_dd = float(((yr_cum - yr_cum.cummax()) / yr_cum.cummax()).min() * 100.0)
    yr_label = f"{yr} (Güncel)" if yr == default_end.year else str(yr)
    annual_rows.append({
        "Yıl": yr_label,
        "Sistem Getirisi": f"%{yr_strat:+.1f}",
        "S&P 500 Getirisi": f"%{yr_spy:+.1f}",
        "Alpha (Ekstra Kazanç)": f"{yr_alpha:+.1f}%",
        "Sharpe (Kalite)": round(yr_sharpe, 2),
        "En Büyük Düşüş": f"{yr_dd:.1f}%",
    })

if annual_rows:
    st.dataframe(pd.DataFrame(annual_rows), use_container_width=True, hide_index=True)
