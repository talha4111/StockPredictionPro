<div align="center">
  <h1>🚀 StockPredictionPro & QuantBot — Dual-Engine AI Quant Platform (+ MCP Server)</h1>
  <p><strong>Engine 1: Crypto Futures Microstructure XGBoost Execution · Engine 2: Institutional Equity Factor (v3.1), 6-Layer Unified Verdict, Live News Shock Veto, Triple-Barrier ML & Model Context Protocol (MCP) Server</strong></p>

  [![Live App](https://img.shields.io/badge/Streamlit_Cloud-Live_Platform-FF4B4B?logo=streamlit&logoColor=white)](https://stockpredictionpro-fejhzqeqvphuetsafqnun.streamlit.app)
  [![Python Version](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/downloads/)
  [![MCP Compatible](https://img.shields.io/badge/MCP-Stdio_Server_Ready-7C3AED)](#🔌-mcp-server-integration-workbuddy--mcp-clients)
  [![Security](https://img.shields.io/badge/Security-PBKDF2_%2B_TOTP_2FA_%2B_WAF-0D9488)](#🔐-enterprise-security--architecture)
  [![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
</div>

---

## 🤖 Featured MCP Workflow: Tencent WorkBuddy + Hy4 Preview

**StockPredictionPro** integrates directly with **Tencent WorkBuddy** (tested live using the **Hy4 preview** model) via a local `stdio` JSON-RPC 2.0 **Model Context Protocol (MCP) Server** ([`mcp_server.py`](mcp_server.py), configured via `~/.workbuddy-ai/mcp.json`).

In our verified live workflow (**Hy4 preview** orchestrating the local MCP tools over `COHR`, `MRVL`, and `MU`), **WorkBuddy** executed and synthesized 4 custom quantitative tools:

| Tool Actually Invoked | Model & Transport | Verified Quantitative Output Used by WorkBuddy |
| :--- | :--- | :--- |
| `get_market_regime` | **Hy4 preview** via `stdio` MCP | Detected defensive macro regime (`KRIZ_YUKSEK_RISK`, `VIX 29.91`, rising US 10Y yields) and locked aggressive Tier-1 entries. |
| `get_stock_quant_snapshot` | **Hy4 preview** via `stdio` MCP | Pulled technicals (`SMA20/50/200`, `RSI14`), Dip-Hunter staged Zone-1 / Zone-2 / Stop / Target levels, 15-day Triple-Barrier AI probabilities (`67/33` win/stop), factor scores, and active risk gates. |
| `check_earnings_catalyst` | **Hy4 preview** via `stdio` MCP | Caught `MRVL`'s upcoming earnings (`12 days away`) and historical `±13.3%` post-earnings gap risk, deferring entry until after the print. |
| `inspect_fifo_lots` | **Hy4 preview** via `stdio` MCP | Audited existing `MU` FIFO tax lots (`Midas` USD vs. TRY cost basis) to prevent unnecessary concentration and premature selling/tax events. |

*(See the [MCP Server Integration](#🔌-mcp-server-integration-workbuddy--mcp-clients) section below for full `mcp.json` setup.)*

---

## 🌍 Flagship Dual-Engine Overview (English)

**StockPredictionPro** is a dual-engine quantitative trading, equity research, and **Model Context Protocol (`stdio` MCP)** ecosystem combining:

### ⚡ ENGINE 1: Crypto Futures & Microstructure XGBoost Engine (`QuantBot/`)
- **Per-Symbol Walk-Forward XGBoost Classifiers:** Integrated with **Binance Futures (`CCXT`)** and **Interactive Brokers (`TWS`)** (`n_estimators=500`, `max_depth=4`), gated by out-of-sample Walk-Forward validation and **Brier Skill Score**.
- **Order-Book & Microstructure Features:** Real-time Order Book Imbalance (`OB_Imbalance`), `Funding_Rate`, `Open_Interest`, Choppiness Index (`CHOP`), `ADX`, and `Volume_ZScore`.
- **Multi-Layer Execution Guardrails & Optuna Tuning:** Dynamic drawdown margin scaling (`1.0x ➔ 0.30x`), daily equity circuit breaker, 24-hour **Symbol Guard** quarantine for losing pairs, single Hard-Stop synchronization, **Binance Income Ledger** (`REALIZED_PNL`, `COMMISSION`, `FUNDING_FEE`) reconciliation, and **Optuna** hyperparameter optimization.

### 📈 ENGINE 2: Global Equity Factor Platform (v3.1) & 6-Layer Unified Verdict Engine (`web/`)
An **11-page Streamlit FinTech & Quant Platform** for US equities (`NVDA`, `MU`, `COHR`, `MRVL`, `RKLB`, `AVGO`, etc.) and BIST (`.IS`), featuring a **Point-in-Time 4-Pillar Cross-Sectional Factor Engine** (*Quality 35%, Value 20%, Momentum 30%, Risk 15%* — validated on **QuantConnect 2021–2026** & live **Shadow Paper Testing**) and a conflict-free **6-Layer Unified Verdict Engine (`unified_verdict.py`)**:

1. **🗞️ Live News Shock & Event Veto (`news_intelligence.py`):**
   - Scans real-time Google News RSS feeds and analyst rating/price-target revisions (`yfinance`).
   - Classifies drawdowns into **Company-Specific Damage (`SIRKET_HASARI`)**, **Macro/Sector Selloff (`MAKRO_SEKTOR`)**, **Idiosyncratic Weakness (`AYRISAN_ZAYIFLIK`)**, or **Healthy Technical Pullback (`SAGLIKLI_DUZELTME`)**.
   - Enforces a **Hard Veto (`HABER_VETOSU`)** on operational halts, launch delays, legal/SEC probes, equity dilution, or downgrades — and **automatically lifts the veto** once price holds above the post-shock low for 3–5 sessions (`≥ +3%` cushion).
2. **🌍 Macro Regime Filter (`investment_committee.py`):**
   - Monitors `SPY`, `SMH`, `^VIX`, and `^TNX` (US 10Y Yield). Locks Tier-1 buying during high-fear regimes (`VIX ≥ 25`, `KRIZ_YUKSEK_RISK`), restricting entries to deep-discount Tier-2 supports with half-size risk.
3. **🤖 Triple-Barrier Calibrated AI (`stock_ai_predictor.py`):**
   - Predicts 15-trading-day Target vs. Stop-Loss hit probability (`±1.8 ATR`), calibrated out-of-sample across **2,837 historical dip events** and 25 **Historical Twin Analogs** (`≥ 58%` win-probability gate).
4. **📉 8-Gate Structural Dip & Exit Hunter (`dip_hunter.py`):**
   - Non-sliding structural support boxes (Fibonacci `0.618`, 20-day swing lows, ATR bands), daily reversal confirmation, 3-day no-new-low falling-knife protection, and Reward/Risk `≥ 1.5R`.
5. **📅 Earnings Catalyst & "Sell-the-News" Lab:**
   - Audits 8 quarters of post-earnings 1-day/5-day drift and "beat-and-drop" frequency; blocks new full-size entries within `≤ 14 days` of earnings.
6. **💼 Per-Lot FIFO Tax & Concentration Brake (`portfolio_tracker.py`, `portfolio_risk.py`):**
   - Dual-currency (**USD & TRY**) Midas FIFO lot accounting with CBRT/PPI tax drafting; blocks premature averaging-down (`< 15%` from last buy or `VIX ≥ 25`) and flags single-stock (`> 40%`) or single-sector (`> 60%`) concentration.
7. **📒 Live Out-of-Sample Signal Scorecard (`signal_journal.py`) & 🧠 Persistent-Memory AI Analyst (`ai_analyst.py`):**
   - Automatically logs `AL` signals alongside legacy signals blocked by the new risk gates (`ENGELLENDI`), evaluating 5d/10d/15d outcomes; paired with a persistent-memory hybrid LLM (`Gemini 2.5` / `Groq` / `OpenAI` + local quant engine) strategist desk.

---

## 🔌 MCP Server Integration (WorkBuddy & MCP Clients)

`StockPredictionPro` includes a local `stdio` JSON-RPC 2.0 **MCP Server** ([`mcp_server.py`](mcp_server.py)) exposing 4 live quantitative tools. It has been tested live with **Tencent WorkBuddy (Hy4 preview)** and follows the standard `stdio` MCP schema compatible with other MCP clients such as Claude Desktop and Cursor:

| MCP Tool Name | Description |
| :--- | :--- |
| `get_stock_quant_snapshot` | Live quote, technicals (`SMA20/50/200`, `RSI14`, Fib levels), 8-gate Dip Hunter zones, 15-day Triple-Barrier AI win/stop odds, active security gates, news shock status, and drawdown diagnosis. |
| `check_earnings_catalyst` | Pre-trade earnings guardrail (`SAFE_WINDOW` / `CAUTION_HALF_SIZE` / `BLOCK_NEW_FULL_SIZE`), days-to-earnings, and historical 8-quarter sell-the-news rate. |
| `inspect_fifo_lots` | Per-lot FIFO cost basis, USD vs. TRY unrealized PnL, and tax/trimming awareness. |
| `get_market_regime` | Real-time macro regime classification (`SPY`, `SMH`, `VIX`, `10Y Yield`) and position-sizing posture. |

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

## 🇹🇷 Türkçe Özet & Çift Motorlu Mimari

**StockPredictionPro & QuantBot**, iki ana motordan oluşan kurumsal bir algoritmik ticaret ve finansal yapay zeka platformudur:

- ⚡ **Motor 1 — Kripto Vadeli İşlemler & Mikroyapı XGBoost Motoru (`QuantBot/`):** Binance Futures (`CCXT`) ve Interactive Brokers (`TWS`) entegreli, Walk-Forward ve Brier Skill Score denetimli `XGBoost` modelleri; Emir Defteri Dengesizliği (`OB_Imbalance`), Fonlama Oranı, Açık Pozisyon, `CHOP` filtresi, 24 saatlik **Symbol Guard** karantinası, Binance Income Ledger mutabakatı ve **Optuna** optimizasyonu.
- 📈 **Motor 2 — Küresel Borsa 4-Sütunlu Faktör Platformu (v3.1), 6 Katmanlı Tek Karar Motoru & MCP Sunucusu (`web/`):**
  - **Tek Birleşik Nihai Karar Motoru (`unified_verdict.py`):** `Haber Şoku`, `Piyasa/VIX`, `AI 15G`, `Teknik/Dip`, `Bilanço` ve `Portföy Freni` oylarını tek bir çelişkisiz hükümde birleştirir.
  - **Canlı Haber & "Neden Düştü?" Teşhis Radarı (`news_intelligence.py`):** Şirket hasarını (`HABER_VETOSU`) makro/sektör satışından ayırır; haber dibi üzerinde 3–5 gün tutunma sağlandığında vetoyu otomatik kaldırır.
  - **Canlı Sinyal Karnesi (`signal_journal.py`):** Verilen `AL` sinyallerini ve yeni kilitlerin durdurduğu eski tip sinyalleri (`ENGELLENDI`) kaydedip 5/10/15 iş günü sonra otomatik puanlar.
  - **Kalıcı Hafızalı AI Uzman Analist (`10_ai_analist.py`) & Yerel MCP Sunucusu (`mcp_server.py`).**

---

## 🔐 Enterprise Security & Architecture
- **Authentication & Access Control:** NIST-compliant `PBKDF2-HMAC-SHA256` password hashing, **RFC 6238 TOTP 2FA** (Google Authenticator), and multi-tenant user portfolio isolation.
- **Application-Layer WAF:** Sliding-window rate limiter (`40 req/min`), payload sanitization, and secret isolation.

---

## 📁 Project Structure (`Proje Yapısı`)

```text
StockPredictionPro/
├── QuantBot/                            # Engine 1: Crypto Futures XGBoost, OB_Imbalance, Symbol Guard & Optuna
├── mcp_server.py                        # Local stdio MCP Server (WorkBuddy / Claude / Cursor)
├── web/                                 # Engine 2: 11-Page Streamlit Equity Quant & FinTech Platform
│   ├── app.py                           # Multi-page application entry + WAF & TOTP 2FA auth
│   ├── components/
│   │   ├── unified_verdict.py           # 6-engine hierarchical single verdict synthesizer
│   │   ├── news_intelligence.py         # Google News RSS + analyst revisions + shock veto & absorption
│   │   ├── dip_hunter.py                # 8-gate Dip Hunter, Exit Hunter & Telegram alerts
│   │   ├── stock_ai_predictor.py        # 15-day Triple-Barrier calibrated ML (2,837 OOS events)
│   │   ├── portfolio_risk.py            # Averaging-down brake & sector/stock concentration guard
│   │   ├── signal_journal.py            # Automated 5d/10d/15d out-of-sample signal scorecard
│   │   ├── investment_committee.py      # Macro regime (SPY/SMH/VIX/TNX) & earnings catalyst lab
│   │   ├── portfolio_tracker.py         # Midas FIFO lot matcher (USD & TRY tax/cost engine)
│   │   ├── ai_analyst.py                # Persistent-memory hybrid LLM + quant analyst engine
│   │   └── security_shield.py           # PBKDF2, RFC 6238 TOTP 2FA & application-layer WAF
│   └── pages/                           # 11 interactive pages (Screener, Single-Stock, Dip Hunter, AI Analyst...)
├── quantconnect_top20/                  # QuantConnect Walk-Forward validation & research pipeline
└── requirements.txt
```

---

## 👨‍💻 Developer (`Geliştirici`)
**Talha Gürler** — [@talha4111](https://github.com/talha4111)

*Disclaimer: This software is built strictly for quantitative research and educational purposes. Nothing herein constitutes financial or investment advice.*
