<div align="center">
  <h1>🚀 StockPredictionPro — AI Quant & Risk Guardrail Platform (+ MCP Server)</h1>
  <p><strong>Institutional-Grade Equity Intelligence, Triple-Barrier ML, Live News Shock Veto, FIFO Tax-Aware Sizing & Model Context Protocol (MCP) Server</strong></p>

  [![Live App](https://img.shields.io/badge/Streamlit_Cloud-Live_Platform-FF4B4B?logo=streamlit&logoColor=white)](https://stockpredictionpro-fejhzqeqvphuetsafqnun.streamlit.app)
  [![Python Version](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
  [![MCP Compatible](https://img.shields.io/badge/MCP-Stdio_Server_Ready-7C3AED)](#🔌-mcp-server-integration-workbuddy--claude--cursor)
  [![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
</div>

---

## 🌍 Overview (English)

**StockPredictionPro** is an end-to-end quantitative equity research, risk-guarded decision engine, and **Model Context Protocol (`stdio` MCP) server** built for US equities (`NVDA`, `MU`, `COHR`, `MRVL`, `RKLB`, `AVGO`, etc.) and BIST (`.IS`).

Unlike naive technical trading bots that blindly buy falling knives during macro panics or company-specific crises, **StockPredictionPro** enforces a **6-Layer Unified Verdict Architecture** before authorizing any entry:

### 🛡️ The 6-Layer Unified Verdict Architecture (`unified_verdict.py`)
1. **🗞️ Live News Shock & Event Veto (`news_intelligence.py`):**
   - Scans real-time Google News RSS feeds and analyst rating/price-target revisions (`yfinance`).
   - Categorizes drawdowns into **Company-Specific Damage (`SIRKET_HASARI`)**, **Macro/Sector Selloff (`MAKRO_SEKTOR`)**, **Idiosyncratic Weakness (`AYRISAN_ZAYIFLIK`)**, or **Healthy Technical Pullback (`SAGLIKLI_DUZELTME`)**.
   - Triggers an automatic **Hard Veto (`HABER_VETOSU`)** on operational halts, launch/product delays, SEC/legal probes, equity dilution, or downgrades.
   - **Auto-Unveto (Absorption Rule):** Automatically lifts the veto once price holds above the post-shock low for 3–5 consecutive sessions (`≥ +3%` cushion) without printing a new low.
2. **🌍 Macro Regime Filter (`investment_committee.py`):**
   - Tracks `SPY`, `SMH` (Semiconductor ETF), `^VIX`, and `^TNX` (US 10Y Yield).
   - Locks Tier-1 dip buying when `VIX ≥ 25` (`KRIZ_YUKSEK_RISK`), restricting entries strictly to deep-discount Tier-2 structural supports with half-size risk.
3. **🤖 Triple-Barrier Calibrated AI (`stock_ai_predictor.py`):**
   - Predicts the 15-trading-day probability of hitting the profit target (`target1`) before the structural stop-loss (`stop_level`), validated out-of-sample across **2,837 historical dip events** plus 25 nearest **Historical Twin Analogs**.
   - Enforces a strict `≥ 58%` win-probability gate.
4. **📉 8-Gate Structural Dip & Exit Hunter (`dip_hunter.py`):**
   - Fixed structural support boxes (non-sliding Fibonacci `0.618` + 20-day swing lows + ATR bands).
   - Requires daily reversal confirmation, no new 3-day low (falling-knife protection), and Reward/Risk `≥ 1.5R`.
5. **📅 Earnings Catalyst & "Sell-the-News" Guardrail:**
   - Audits the last 8 quarters of post-earnings 1-day/5-day drift and historical "beat-and-drop" frequency. Blocks new full-size entries within `≤ 14 days` of an earnings report.
6. **💼 Per-Lot FIFO Tax & Concentration Brake (`portfolio_tracker.py`, `portfolio_risk.py`):**
   - Tracks individual FIFO lots in both **USD and local currency (TRY)** to prevent accidentally realizing heavy FX-driven taxable gains on oldest low-cost lots when trimming.
   - Enforces averaging-down discipline (`≥ 15%` below last buy price + clean news + `VIX < 25`) and flags single-stock (`> 40%`) or single-sector (`> 60%`) concentration.

---

## 🔌 MCP Server Integration (WorkBuddy / Claude / Cursor)

`StockPredictionPro` ships with a zero-dependency local `stdio` JSON-RPC 2.0 **MCP Server** ([`mcp_server.py`](mcp_server.py)) that exposes 4 quantitative tools to any MCP client (tested live with **Tencent WorkBuddy + Hy4**, **Claude Desktop**, and **Cursor**):

| MCP Tool Name | Description |
| :--- | :--- |
| `get_stock_quant_snapshot` | Returns live price, technicals (`SMA20/50/200`, `RSI14`, Fib levels), 8-gate Dip Hunter zones, 15-day Triple-Barrier AI win/stop odds, active security gates, news shock status, and drawdown diagnosis. |
| `check_earnings_catalyst` | Pre-trade earnings guardrail (`SAFE_WINDOW` / `CAUTION_HALF_SIZE` / `BLOCK_NEW_FULL_SIZE`), days-to-earnings, and historical 8-quarter sell-the-news rate. |
| `inspect_fifo_lots` | Per-lot FIFO cost basis, USD vs. local-currency unrealized PnL, and tax/trimming awareness. |
| `get_market_regime` | Real-time macro regime classification (`SPY`, `SMH`, `VIX`, `10Y Yield`) and position-sizing posture. |

### Add to `~/.workbuddy-ai/mcp.json` or `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "stockpredictionpro": {
      "command": "python",
      "args": [
        "/absolute/path/to/StockPredictionPro/mcp_server.py"
      ]
    }
  }
}
```

---

## 🇹🇷 Türkçe Özet & Mimari

**StockPredictionPro**, ABD borsaları (`MU`, `COHR`, `MRVL`, `NVDA`, `RKLB`, `AVGO` vb.) ve BIST (`.IS`) hisseleri için geliştirilmiş; **Canlı Haber Şoku Radarı**, **Üçlü Bariyer Yapay Zekası**, **8 Şartlı Dip/Satış Avcısı**, **Midas FIFO Vergi/Maliyet Freni** ve **Kalıcı Hafızalı AI Uzman Analist** modüllerini tek bir kararda birleştiren kurumsal yatırım analizi platformudur.

### Öne Çıkan Modüller
- 🎯 **Tek Birleşik Nihai Karar Motoru (`web/components/unified_verdict.py`):** 6 alt-motorun (`Haber`, `Piyasa/VIX`, `AI 15G`, `Teknik`, `Bilanço`, `Portföy Freni`) oylarını hiyerarşik olarak birleştirip çelişkisiz tek bir hüküm ve *"Ne Beklenmeli?"* tetikleyicisi üretir.
- 🗞️ **Canlı Haber & "Neden Düştü?" Teşhis Motoru (`web/components/news_intelligence.py`):** Şirket hasarı ile makro/sektörel satışı birbirinden ayırır; kötü haberde alımı kilitler (`HABER_VETOSU`), haber dibi üzerinde 3–5 gün tutunma sağlandığında vetoyu otomatik kaldırır.
- 📒 **Canlı Sinyal Karnesi (`web/components/signal_journal.py`):** Yeni kuralların verdiği `AL` sinyalleri ile güvenlik kilitlerinin durdurduğu eski tip sinyalleri (`ENGELLENDI`) kaydeder; 5, 10 ve 15 işlem günü sonraki gerçek Hedef / Stop performansını otomatik puanlar.
- 🧠 **Kalıcı Hafızalı AI Uzman Analist (`web/pages/10_ai_analist.py`):** Önceki konuşmaları, portföy kurallarını ve Midas FIFO lotlarını hatırlayan hibrit (Google Gemini / Groq / OpenAI + Yerleşik Quant Motoru) analist masası.

---

## 📁 Project Structure (`Proje Yapısı`)

```text
StockPredictionPro/
├── mcp_server.py                        # Local stdio MCP Server (WorkBuddy / Claude / Cursor)
├── web/
│   ├── app.py                           # Streamlit multi-page application entry
│   ├── components/
│   │   ├── unified_verdict.py           # 6-engine hierarchical single verdict synthesizer
│   │   ├── news_intelligence.py         # Google News RSS + analyst revisions + shock veto & absorption
│   │   ├── dip_hunter.py                # 8-gate Dip Hunter, Exit Hunter & Telegram alerts
│   │   ├── stock_ai_predictor.py        # 15-day Triple-Barrier calibrated ML + historical twins
│   │   ├── portfolio_risk.py            # Averaging-down brake & sector/stock concentration guard
│   │   ├── signal_journal.py            # Automated 5d/10d/15d out-of-sample signal scorecard
│   │   ├── investment_committee.py      # Macro regime (SPY/SMH/VIX/TNX) & earnings catalyst lab
│   │   ├── portfolio_tracker.py         # Midas FIFO lot matcher (USD & TRY tax/cost engine)
│   │   └── ai_analyst.py                # Persistent-memory hybrid LLM + quant analyst engine
│   ├── pages/
│   │   ├── 0_ana_sayfa.py               # Executive dashboard
│   │   ├── 2_tek_hisse_analiz.py        # Unified Single-Stock Analysis & Evidence Tabs
│   │   ├── 7_performans.py              # Walk-forward & signal performance tracker
│   │   ├── 8_portfoy_defteri.py         # Midas FIFO portfolio & tax ledger
│   │   ├── 9_alim_avcisi.py             # Dip Hunter, Profit Shield & Live Signal Scorecard
│   │   └── 10_ai_analist.py             # Persistent-Memory AI Quant Strategist
│   └── scripts/
│       └── alim_avcisi_tarayici.py      # Automated market-hours scanner & journal evaluator
└── requirements.txt
```

---

## 🚀 Quick Start (`Kurulum & Çalıştırma`)

```bash
git clone https://github.com/talha4111/StockPredictionPro.git
cd StockPredictionPro
pip install -r requirements.txt

# Launch the Streamlit Web Platform
streamlit run web/app.py
```

---

## 👨‍💻 Developer (`Geliştirici`)
**Talha Gürler** — [@talha4111](https://github.com/talha4111)

*Disclaimer: This software is built strictly for quantitative research and educational purposes. Nothing herein constitutes financial or investment advice.*
