<div align="center">
  <h1>📈 StockPredictionPro & QuantBot — Dual-Engine AI Trading, Equity Research & FinTech Platform</h1>
  <p><strong>1) Binance Futures Entegreli XGBoost & Optuna Kripto Otonom Trading Motoru (QuantBot)<br/>2) Tekil Hisse Analizi, 4-Sütunlu Faktör Modeli, Triple-Barrier AI & 10 Sayfalık Siber Güvenlik Zırhlı Borsa Platformu</strong></p>
  
  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
  [![Binance](https://img.shields.io/badge/Binance_Futures-CCXT_&_OrderBook-F0B90B?style=for-the-badge&logo=binance&logoColor=black)]()
  [![XGBoost](https://img.shields.io/badge/AI-XGBoost_%7C_Optuna_%7C_Triple--Barrier-2EA44F?style=for-the-badge)]()
  [![Streamlit](https://img.shields.io/badge/Streamlit-10--Page_FinTech_Cloud-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
  [![QuantConnect](https://img.shields.io/badge/QuantConnect-LEAN_Validated-F5A623?style=for-the-badge)]()
  [![Security](https://img.shields.io/badge/Security-PBKDF2_%7C_TOTP_2FA_%7C_WAF-0A66C2?style=for-the-badge)]()
</div>

<br>

## 📖 Proje Hakkında
**StockPredictionPro**, iki ana mühendislik omurgasından oluşan çift motorlu (Dual-Engine) bir **Algoritmik Finans, Yapay Zeka ve Portföy Yönetim Ekosistemidir**:

1. **⚡ Kripto Vadeli İşlemler Otonom Trading Motoru (`QuantBot/` & `commander.py`):** **Binance Futures (CCXT)** ve **Interactive Brokers (TWS)** ile entegre çalışan; emir defteri dengesizliği (`OB_Imbalance`), fonlama oranı (`Funding_Rate`), açık pozisyon (`Open_Interest`) ve teknik indikatörler üzerinde her parite için özel **XGBoost** modelleri eğiten, **Optuna** ile hiperparametre optimize eden ve çok katmanlı risk/karantina kapılarıyla 7/24 otonom emir yürüten sistem.
2. **🏛️ Borsa & Hisse Senedi Araştırma, Tekli Analiz ve Portföy Platformu (`web/` & `stock_value_engine.py`):** Tekil hisseler için derinlemesine teknik/temel röntgen (**Tek Hisse Analizi & Yatırım Komitesi**), **Point-in-Time SEC EDGAR** verileriyle 100+ hisseyi puanlayan **4-Sütunlu Kesitsel Faktör Motoru (v3.1)**, **QuantConnect** doğrulama hattı, **Triple-Barrier ($\pm 1.8\text{ ATR}$) Hibrit AI Tahmincisi**, **Dip Avcısı** ve **FIFO Portföy/Stres Testi** sunan 10 sayfalık **Streamlit** web uygulaması.

---

## ⚡ BÖLÜM 1: Kripto Vadeli İşlemler & Binance XGBoost Motoru (`QuantBot/`)

### 1. 🧠 Sembol Bazlı XGBoost Sınıflandırıcı & Piyasa Mikroyapısı (`ai_core.py`, `tarayici.py`)
- **Özel XGBoost Modelleri (`BeyinMotoru`):** Her kripto paritesi (`BTC/USDT`, `ETH/USDT`, `SOL/USDT` vb.) için çoklu zaman dilimi (15m / 1h) verileriyle eğitilen (`n_estimators=500`, `max_depth=4`), Walk-Forward Validation ve **Brier Skill Score** ile kalitesi denetlenen özel yön tahmin modelleri.
- **Zengin Öznitelik Mühendisliği (Feature Engineering):**
  - **Piyasa Mikroyapısı & Türev Verileri:** Canlı **Emir Defteri Dengesizliği (`OB_Imbalance` — Order Book Imbalance)**, **Fonlama Oranı (`Funding_Rate`)** ve **Açık Pozisyon (`Open_Interest`)** değişimleri.
  - **Momentum, Volatilite & Hacim:** `RSI`, `MACD`, `ATR`, `ADX` (Trend Gücü), `CHOP` (Choppiness Index — yatay piyasa tespiti), `Volume_ZScore`, `OBV`, `MFI`, `BB_Width`, `VP_Sapma` (Volume Profile sapması), `EMA_Slope` ve `BTC` referans korelasyonu (`Ref_Ret`, `Korelasyon`).
- **Canlı Gölge Model A/B Karşılaştırması (`live_model_compare.py`):** Üretimdeki ana XGBoost beyni ile aday modelleri (`golge_beyin`, `v6_1h_beyin`) gerçek zamanlı piyasa akışında kafa kafaya test eder.

### 2. 🛡️ Çok Katmanlı Sinyal, Rejim ve Risk Kapıları (`signal_engine.py`, `risk_manager.py`, `symbol_guard.py`)
- **Hedge / Sniper Modu & Rejim Filtresi (`rejim.py`):** Yatay ve testere piyasalarını `CHOP` ve `ADX` eşikleriyle filtreler; yalnızca yüksek Risk/Ödül (`RR`), yüksek model güven skoru ve hacim patlaması (`Volume_ZScore`) olan işlemleri geçirir.
- **Model Kalite Kapısı (`MODEL_KALITE_KAPISI`):** Walk-forward doğruluk skoru, Brier olasılık kalibrasyonu ve yakın dönem Profit Factor eşiğini geçemeyen modellerin işlem açmasını otomatik engeller.
- **Dinamik Savunma Marjin Çarpanı & Günlük Zarar Kesici:** Ardışık zarar sayısına göre pozisyon büyüklüğünü kademeli olarak küçültür (`1.00x ➔ 0.70x ➔ 0.50x ➔ 0.30x`) ve günlük özsermaye (equity) zarar limitine ulaşıldığında tüm yeni emirleri kilitler.
- **Sembol Karantina Kalkanı (`symbol_guard.py`):** Son 24 saat içinde ardışık stop olan pariteleri otomatik olarak geçici karantinaya alır.
- **Sistem Müfettişi (`mufettis.py`) & LLM Haber Analisti (`llm_analist.py`):** API/çalışma zamanı hatalarını denetleyen otonom sağlık müfettişi ve Korku/Açgözlülük Endeksi (`Fear & Greed`) + RSS haber duyarlılığını analiz eden doğal dil modülü.

### 3. ⚙️ Deterministik Emir İletimi, Optuna & Borsa Muhasebe Uzlaştırması (`order_engine.py`, `account_sync.py`, `optuna_backtest.py`)
- **Binance Futures & IBKR Emir Motoru:** Sembol lot/fiyat hassasiyeti (`precision`), minimum notional kontrolü, ATR tabanlı dinamik Stop-Loss / Take-Profit ön doğrulaması (`_stop_on_kontrol`) ve borsada tekil Hard-Stop garantisi (`ensure_single_hard_stop`).
- **Borsa Defteri Mutabakatı (`account_sync.py`, `reconcile_orders_once.py`):** Binance Income Ledger üzerinden resmi `REALIZED_PNL`, `COMMISSION` ve `FUNDING_FEE` kayıtlarını çekerek yerel SQLite veritabanı ile kuruşu kuruşuna uzlaştırır.
- **Optuna Hiperparametre Optimizasyonu (`optuna_backtest.py`, `shadow_backtest.py`):** Komisyon ve kayma (slippage) maliyetleri altında Win Rate, Profit Factor, Expectancy ve Max Drawdown metriklerini optimize eder.

---

## 🏛️ BÖLÜM 2: Borsa & Hisse Senedi Tekli Analiz, Faktör Motoru ve Web Platformu (`web/`)

### 1. 🔍 Tek Hisse Derinlemesine Analiz & Yatırım Komitesi (`2_tek_hisse_analiz.py`, `investment_committee.py`)
Herhangi bir ABD veya BIST hissesi seçildiğinde anlık olarak çalışan kapsamlı karar destek modülü:
- **4 Sütunlu Faktör Radar Röntgeni:** Hisseyi sektörel rakiplerine göre *Kalite (%35)*, *Değer (%20)*, *Momentum (%30)* ve *Risk (%15)* eksenlerinde puanlar.
- **Yatırım Komitesi & Faktör Çatışma Dedektörü (`Factor Conflict Detector`):** Temel değerleme ile teknik momentum arasındaki çelişkileri (örn. *"Değer Tuzakları"* veya *"Aşırı Isınmış Momentum"*) otomatik tespit eder.
- **Bilanço & Katalizör Laboratuvarı (`Catalyst & Earnings Lab`):** Yaklaşan bilanço tarihlerini, tarihsel bilanço sürprizlerini ve analist beklentilerini değerlendirir.
- **ATR Tabanlı Aksiyon Kutusu:** Canlı fiyat, SMA 20/50/200, RSI ve volatiliteye göre **kademeli alım (giriş) bölgeleri, Stop-Loss ve Take-Profit** hedeflerini hesaplar.

### 2. 🎯 Triple-Barrier Hibrit AI Tahmincisi & Dip Avcısı (`stock_ai_predictor.py`, `9_alim_avcisi.py`)
- **Triple-Barrier Etiketleme ($\pm 1.8\text{ ATR}$, 15 İşlem Günü):** 15 volatilite-normalize öznitelik (RSI-14/5, ADX, ATR biriminde SMA-20/50/200 uzaklıkları, Bollinger %B, mum dönüş/fitil hacmi, SPY/SMH göreceli gücü, VIX) üzerinde **2.837 örneklem dışı (out-of-sample)** olayla doğrulanmış L2 Lojistik Regresyon ve Random Forest / XGBoost hibrit olasılık modeli.
- **Dip Avcısı & Kâr Koruma Motoru (`dip_hunter.py`):** Kurumsal kalitesi yüksek hisselerde aşırı satım dönüşlerini yakalar; açık portföy lotlarında bilanço tuzağı ve kâr koruma (trailing stop) uyarılarını otomatik **Telegram** bildirimi olarak gönderir.

### 3. 📊 Kesitsel Faktör Motoru (v3.1), SEC EDGAR PIT & QuantConnect Doğrulaması
- **Point-in-Time SEC EDGAR (`sec_point_in_time.py`):** İleriye dönük veri sızıntısını (*look-ahead bias*) önlemek için bilanço verilerini şirketin SEC'e resmi bildirim tarihi (`filed date`) itibarıyla işler.
- **QuantConnect (LEAN) & Shadow Paper Test (`quantconnect_top20/`, `stock_shadow_paper.py`):** 2021–2026 döneminde 25 bps işlem maliyetiyle 3 piyasa rejiminde (*2021–22 Stres, 2023–24 Toparlanma, 2025–26 Güncel*) doğrulanmış; canlı **Baseline vs. Challenger** gölge testi ve terfi kapısı (`Model Promotion Gate`) ile desteklenmiştir.

### 4. 🌐 10 Sayfalık Mobil Öncelikli Streamlit FinTech Platformu & Siber Güvenlik Zırhı
- **10 İnteraktif Modül (`web/pages/0..9`):**
  - `0_ana_sayfa.py` (VIX Rejim Hapı, Portföy Kartları, Günün AI Fırsatları) · `1_piyasa_tarayici.py` (100+ Hisse Faktör Tarayıcı) · `2_tek_hisse_analiz.py` (Tek Hisse Röntgeni & Yatırım Komitesi) · `3_sektor_radari.py` (Sektör Rotasyonu & Tematik Sepetler) · `4_walkforward_lab.py` (Walk-Forward Lab) · `5_faktor_optimizasyonu.py` (Faktör Grid-Search) · `6_shadow_test.py` (Canlı Gölge Yarışı) · `7_performans.py` (Sinyal Takip Motoru) · `8_portfoy_defteri.py` (FIFO Lot Defteri, S&P 500 Beta, Korelasyon Isı Haritası, Kriz Stres Testi & TCMB/Yİ-ÜFE Vergi Motoru) · `9_alim_avcisi.py` (Dip & Kâr Koruma Avcısı).
- **Siber Güvenlik & WAF (`auth.py`, `security_shield.py`):** **NIST PBKDF2-SHA256** tuzlanmış parola hashleme, **RFC 6238 TOTP 2FA** (Google/Microsoft Authenticator QR kurulumu), Brute-Force kilidi, kayan pencereli **Rate Limiter (40 istek/dk)**, Anti-Scraping bot filtresi, SQLi/XSS girdi sanitizasyonu ve SQLite `security_audit_log`.

---

## 🚀 Kurulum ve Çalıştırma

```bash
git clone https://github.com/talha4111/StockPredictionPro.git
cd StockPredictionPro
pip install -r requirements_web.txt
cp .env.example .env
cp ayar.example.json ayar.json

# 1. Borsa & Hisse Senedi 10 Sayfalık Web Platformunu Başlatma:
streamlit run web/app.py

# 2. Kripto Vadeli İşlemler (QuantBot) Otonom Motorunu Başlatma:
python QuantBot/main.py
```

---

## 📂 Proje Klasör Yapısı
```text
StockPredictionPro/
├── QuantBot/                         # BÖLÜM 1: Kripto Vadeli İşlemler (Binance Futures & IBKR) Otonom Motoru
│   ├── main.py & scanner_loop.py     # Çoklu iş parçacıklı piyasa tarayıcı ve sinyal sıralayıcı
│   ├── ai_core.py                    # Sembol bazlı XGBoost sınıflandırıcı ve Walk-Forward eğitim çekirdeği
│   ├── signal_engine.py              # OB_Imbalance, CHOP, ADX, Funding Rate ve Hedge/Sniper filtre motoru
│   ├── risk_manager.py & symbol_guard.py # Model kalite kapısı, savunma marjini, günlük zarar kesici ve karantina
│   ├── order_engine.py & order_sync.py   # CCXT Binance Futures emir iletimi ve tekil Hard-Stop garantisi
│   ├── account_sync.py               # Binance Income Ledger (Realized PnL, Commission, Funding) mutabakatı
│   └── optuna_backtest.py & shadow_backtest.py # Optuna hiperparametre optimizasyonu ve gölge backtest
├── web/                              # BÖLÜM 2: Borsa & Hisse Senedi 10 Sayfalık Streamlit FinTech Platformu
│   ├── app.py                        # Uygulama giriş noktası, WAF ve 2FA Login Gate
│   ├── pages/                        # 0_ana_sayfa.py .. 9_alim_avcisi.py (Tek Hisse Analizi, Tarayıcı, FIFO Portföy vb.)
│   └── components/                   # investment_committee.py, stock_ai_predictor.py, dip_hunter.py, stress_test.py, auth.py
├── stock_value_engine.py             # 4 sütunlu kesitsel (Cross-Sectional) hisse faktör motoru (v3.1)
├── sec_point_in_time.py              # SEC EDGAR Point-in-Time temel veri çekici (Look-ahead bias korumalı)
├── quantconnect_top20/               # QuantConnect LEAN bulut doğrulama algoritmaları
└── test_*.py                         # 30+ birim ve entegrasyon test paketi
```

---

## 👨‍💻 Geliştirici
**Talha Gürler** — [GitHub (@talha4111)](https://github.com/talha4111)

---
*Yasal Uyarı: Bu yazılım tamamen akademik araştırma, finansal mühendislik ve algoritmik sistem tasarımı amacıyla geliştirilmiştir. Hiçbir çıktısı yatırım tavsiyesi niteliği taşımaz.*
