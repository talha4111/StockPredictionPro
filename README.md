<div align="center">
  <h1>📈 StockPredictionPro — Quantitative Factor Engine, Triple-Barrier AI & Multi-Asset FinTech Platform</h1>
  <p><strong>Kurumsal Seviyede 4-Sütunlu Kantitatif Faktör Modeli, QuantConnect Doğrulama Hattı, Triple-Barrier Hibrit Yapay Zeka Tahmincisi ve 10 Sayfalık Siber Güvenlik Zırhlı Streamlit Web Platformu</strong></p>
  
  [![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
  [![Streamlit](https://img.shields.io/badge/Streamlit-10--Page_FinTech_Cloud-FF4B4B?style=for-the-badge&logo=streamlit&logoColor=white)](https://streamlit.io/)
  [![QuantConnect](https://img.shields.io/badge/QuantConnect-LEAN_Validated-F5A623?style=for-the-badge)]()
  [![ML](https://img.shields.io/badge/AI-Triple--Barrier_%26_XGBoost-2EA44F?style=for-the-badge)]()
  [![Security](https://img.shields.io/badge/Security-PBKDF2_%7C_TOTP_2FA_%7C_WAF-0A66C2?style=for-the-badge)]()
</div>

<br>

## 📖 Proje Hakkında
**StockPredictionPro**, hem kurumsal ABD hisse senetleri (S&P 500 / Teknoloji & Yarıiletken Evreni) hem de kripto vadeli işlemler (Binance Futures & Interactive Brokers) için geliştirilmiş uçtan uca bir **Kantitatif Araştırma, Algoritmik Sinyal ve Portföy Yönetim Platformudur**.

Sistem; **Point-in-Time SEC EDGAR** temel verileriyle çalışan **Stock Value Engine v3.1** faktör modelini, **QuantConnect (LEAN)** bulut doğrulama laboratuvarını, **Triple-Barrier ($\pm 1.8\text{ ATR}$)** etiketlemeli hibrit makine öğrenmesi motorunu ve **NIST PBKDF2 + RFC 6238 TOTP 2FA + Uygulama Katmanı WAF** ile korunan **10 sayfalık mobil uyumlu Streamlit Web Platformunu** tek bir çatı altında birleştirir.

---

## 🏗️ Çekirdek Mühendislik Mimarisi

### 1. 📊 Stock Value Engine v3.1 — 4 Sütunlu Kesitsel (Cross-Sectional) Faktör Modeli
100+ kurumsal ABD hissesini sektör içi (sector-neutral) yüzdelik dilim ve winsorize edilmiş z-skorları ile 4 ana sütunda puanlar:
- **Quality (%35 Ağırlık):** ROE, ROIC, Brüt ve Operasyonel Marj istikrarı, Serbest Nakit Akışı (FCF) dönüşümü (`sec_point_in_time.py` üzerinden ileriye dönük veri sızıntısını — *look-ahead bias* — önleyen Point-in-Time SEC EDGAR entegrasyonu).
- **Value (%20 Ağırlık):** Sektöre göre düzeltilmiş F/K (Forward/Trailing P/E), EV/EBITDA, FCF Yield ve PEG rasyoları.
- **Momentum (%30 Ağırlık):** 3, 6 ve 12 aylık (son 1 ay hariç klasik 12-1 momentum) riske göre düzeltilmiş fiyat ivmesi ve sektör ETF'lerine (`SMH`, `XLK`, `SPY`) göre göreceli güç (Relative Strength).
- **Risk & Volatilite (%15 Ağırlık):** Yıllıklandırılmış volatilite, maksimum düşüş (Max Drawdown), Beta ve Borç/Özkaynak (Debt-to-Equity) dengesi.

### 2. 🧪 QuantConnect (LEAN Engine) Bulut Doğrulaması & Gölge (Shadow) Testi
- **Tarihsel Evren & Sağkalım Yanlılığı (Survivorship Bias) Koruması (`quantconnect_top20/`, `stock_historical_universe.py`):** 2021–2026 döneminde S&P 500 tarihsel bileşenleri, Market-On-Open (MOO) emir yürütmesi ve işlem başına **25 bps** komisyon/kayma (slippage) maliyeti ile test edilmiştir.
- **3 Rejim Doğrulaması & Ablasyon (`stock_factor_regime_validation.py`):** 2021–2022 Ayı/Enflasyon Stresi, 2023–2024 Toparlanma ve 2025–2026 Güncel Piyasa rejimlerinde *Leave-One-Factor-Out* ablasyon testleriyle doğrulanmıştır.
- **Canlı Shadow Paper Yarışı (`stock_shadow_paper.py`):** Üretimdeki **Baseline (35/20/30/15)** modeli ile aday **Challenger** modellerini aylık kohortlar halinde canlı piyasada kafa kafaya yarıştırır; istatistiksel terfi kapısını (`Model Promotion Gate`) geçemeyen modelleri üretime almaz.

### 3. 🧠 Triple-Barrier Kalibre Edilmiş Hibrit Yapay Zeka (`ai_core.py`, `stock_ai_predictor.py`)
- **Triple-Barrier Etiketleme (Marcos López de Prado Metodolojisi):** Basit sabit gün getirisi yerine, 15 işlem günü ufkunda **Üst Bariyer ($+1.8\text{ ATR}$ Kâr Al)** ve **Alt Bariyer ($-1.8\text{ ATR}$ Zarar Kes)** seviyelerinden hangisine önce dokunulduğunu sınıflandırır.
- **15 Volatilite-Normalize Öznitelik:** RSI-14, RSI-5, ADX, ATR biriminde SMA-20/50/200 uzaklıkları, Bollinger %B, mum dönüş/fitil hacim oranı, SPY ve SMH göreceli gücü, VIX seviyesi ve değişimi.
- **Hibrit Olasılık Kalibrasyonu:** 2.837 örneklem dışı (out-of-sample) olay üzerinde doğrulanmış **L2 Lojistik Regresyon** ağırlıkları ile tarihsel ikiz (Historical Twin) **Random Forest / XGBoost** sınıflandırıcılarını birleştirerek kalibre edilmiş kazanma olasılığı üretir.

### 4. 🌐 10 Sayfalık Mobil Öncelikli Streamlit FinTech Web Platformu (`web/`)
1. **`0_ana_sayfa.py` (Ana Kumanda Merkezi):** Canlı VIX piyasa rejimi hapı, portföy özet kartları, günün Triple-Barrier AI fırsatları ve haftalık model nabzı.
2. **`1_piyasa_tarayici.py` (100+ Hisse Faktör Tarayıcı):** 4 sütunlu faktör skorlarına göre çoklu filtreleme ve sıralama.
3. **`2_tek_hisse_analiz.py` (Tek Hisse Röntgeni & Yatırım Komitesi):** Radar grafikleri, Faktör Çatışma Dedektörü, Bilanço/Katalizör Laboratuvarı ve ATR tabanlı kademeli giriş / SL / TP seviyeleri.
4. **`3_sektor_radari.py` (Piyasa Rejimi & Sektör Rotasyonu):** Sektör ETF momentum saçılım grafiği ve tematik yatırım sepetleri (AI Altyapı, Yarıiletken, Siber Güvenlik, Temiz Enerji).
5. **`4_walkforward_lab.py` (Walk-Forward Test Laboratuvarı):** Dönem bazlı kümülatif getiri, Sharpe oranı, Alfa ve maksimum düşüş simülasyonu.
6. **`5_faktor_optimizasyonu.py` (Faktör Ağırlık Grid-Search):** Farklı faktör ağırlık kombinasyonlarının tarihsel verimlilik sınaması.
7. **`6_shadow_test.py` (Shadow Test & Model Promotion Gate):** Baseline vs. Challenger canlı kohort performans takibi.
8. **`7_performans.py` (Sinyal Takip Motoru):** Üretilen sinyallerin gerçekleşen isabet oranı (Hit Rate) ve getiri eğrisi.
9. **`8_portfoy_defteri.py` (FIFO Portföy Defteri, Stres Testi & Vergi Motoru):**
   - **Midas Uyumlu FIFO Lot Eşleştirme:** İlk giren ilk çıkar (FIFO) kuralına göre lot bazlı maliyet, anlık USD ve TRY kâr/zarar hesabı.
   - **Yoğunlaşma & Kriz Stres Testi:** Portföyün S&P 500 Betası, hisseler arası korelasyon ısı haritası ve tarihsel kriz şok senaryoları (2022 Fed Faiz Şoku, Resesyon, Yarıiletken Düzeltmesi).
   - **Türkiye Vergi Taslağı:** TCMB kurları ve **Yİ-ÜFE endeksleme (%10+ şartı)** kurallarına göre Yabancı Hisse Değer Artış Kazancı matrah hesaplayıcısı.
10. **`9_alim_avcisi.py` (Dip Avcısı & Kar Koruma Motoru):** Kurumsal kalitesi yüksek hisselerde aşırı satım dönüşlerini ve açık lotlarda bilanço tuzağı / kâr koruma (trailing stop) uyarılarını yakalayıp otomatik **Telegram** bildirimi gönderir.

### 5. 🛡️ Kurumsal Siber Güvenlik & Uygulama Katmanı WAF (`auth.py`, `security_shield.py`)
- **Katman 1 — Kimlik Doğrulama & 2FA:** NIST standardında tuzlanmış **PBKDF2-SHA256** parola özütleme, **RFC 6238 TOTP (Google / Microsoft Authenticator)** dinamik QR kod kurulumu ve Brute-Force kilitleme kalkanı (5 hatalı denemede 300 sn kilit).
- **Katman 2 — Uygulama İçi WAF & Tehdit Kalkanı:** Kayan pencere hız sınırlayıcı (**Sliding-Window Rate Limiter**: 40 istek/dk, 10 istek/3 sn burst), Anti-Scraping bot imzası engelleme (`403 Forbidden`), Anti-SQLi / Anti-XSS parametre sanitizasyonu, güvenlik başlıkları (`X-Frame-Options`, `X-Content-Type-Options`) ve SQLite `security_audit_log` denetim izi.

---

## 🚀 Kurulum ve Çalıştırma

### 1. Repoyu Klonlayın
```bash
git clone https://github.com/talha4111/StockPredictionPro.git
cd StockPredictionPro
```

### 2. Bağımlılıkları Yükleyin
```bash
pip install -r requirements_web.txt
```

### 3. Ortam Değişkenlerini Yapılandırın (`.env`)
```bash
cp .env.example .env
cp ayar.example.json ayar.json
```

### 4. Web Platformunu Başlatın
```bash
streamlit run web/app.py
```

### 5. Birim ve Entegrasyon Testlerini Çalıştırın
```bash
pytest test_quantconnect_factor_core.py test_sec_point_in_time.py test_stock_value_foundation.py test_stock_walkforward.py
```

---

## 📂 Proje Klasör Yapısı
```text
StockPredictionPro/
├── web/
│   ├── app.py                        # Streamlit ana giriş noktası, WAF ve Login Gate
│   ├── pages/                        # 0_ana_sayfa.py .. 9_alim_avcisi.py (10 interaktif modül)
│   └── components/                   # auth.py, security_shield.py, stock_ai_predictor.py, portfolio_tracker.py, stress_test.py
├── quantconnect_top20/               # QuantConnect LEAN bulut algoritması ve doğrulama modülleri
├── stock_value_engine.py             # 4 sütunlu kesitsel (Cross-Sectional) faktör puanlama motoru
├── sec_point_in_time.py              # SEC EDGAR Point-in-Time temel veri çekici (Look-ahead bias korumalı)
├── stock_walkforward.py              # Walk-forward simülasyon ve performans değerlendirme motoru
├── stock_shadow_paper.py             # Baseline vs. Challenger canlı gölge testi ve terfi kapısı
├── ai_core.py                        # Triple-Barrier ve ML öznitelik mühendisliği çekirdeği
├── QuantBot/                         # Kripto vadeli işlemler (Binance / IBKR) ve Optuna alt modülü
└── test_*.py                         # Faktör motoru, PIT muhasebe ve walk-forward birim testleri
```

---

## 👨‍💻 Geliştirici
**Talha Gürler** — [GitHub (@talha4111)](https://github.com/talha4111)

---
*Yasal Uyarı: Bu yazılım tamamen akademik araştırma, finansal mühendislik ve algoritmik sistem tasarımı amacıyla geliştirilmiştir. Hiçbir çıktısı yatırım tavsiyesi niteliği taşımaz.*
