<div align="center">
  <h1>🚀 StockPredictionPro (AI-Driven Quant Trading Engine)</h1>
  <p><strong>Gelişmiş Yapay Zeka Tabanlı Kripto ve Hisse Senedi Alım-Satım Botu</strong></p>
  
  [![Python Version](https://img.shields.io/badge/Python-3.9+-blue.svg)](https://www.python.org/downloads/)
  [![License](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
  [![Status](https://img.shields.io/badge/Status-Active-success.svg)]()
</div>

<br>

## 📖 Proje Hakkında
**StockPredictionPro**, makine öğrenmesi (Machine Learning) ve derin öğrenme (Deep Learning) modellerini kullanarak piyasa analizi yapan, Interactive Brokers ve Binance gibi borsalarla entegre çalışan **tam otonom** bir algoritmik ticaret (algorithmic trading) sistemidir. Sistem piyasa trendlerini analiz eder, LLM (Büyük Dil Modeli) destekli kararlar alır ve otomatik alım/satım işlemlerini yürütür.

## ✨ Temel Özellikler
- 🧠 **Yapay Zeka Destekli Karar Mekanizması:** Özel eğitilmiş `Keras` ve `Pickle` (Scikit-Learn/XGBoost) modelleri ile yön tahmini.
- 📊 **Çift Pazar Desteği:** Hem kripto paralar (Binance) hem de geleneksel hisse senetleri (BİST & Global) için analiz ve işlem yapabilme.
- ⚡ **Canlı Trade ve Backtest Motoru:** Gelişmiş `backtest_pro.py` ile strateji simülasyonu ve `commander.py` ile gerçek zamanlı emir yönetimi.
- 🤖 **LLM Analist Entegrasyonu:** `llm_analist.py` üzerinden doğal dil işleme destekli temel ve duygu (sentiment) analizi.
- 📱 **Telegram Bildirimleri:** `test_tele.py` üzerinden gerçek zamanlı kar/zarar ve emir bildirimleri.
- 🛡️ **Risk Yönetimi (Müfettiş Modülü):** Bakiyeyi korumak ve maksimum kayıpları engellemek için geliştirilen akıllı kasa yönetim sistemi.

## 📁 Proje Yapısı
```text
StockPredictionPro/
├── QuantBot/                # Kuantitatif analiz ve işlem sinyali üreten modüller
├── commander.py             # Ana yönetim ve komuta dosyası (Emir iletimi)
├── stock_engine.py          # Hisse senedi verilerini analiz eden motor
├── crypto_backtest.py       # Kripto paralar için geçmişe dönük test aracı
├── ibkr_bridge.py           # Interactive Brokers TWS API bağlantı köprüsü
├── llm_analist.py           # Dil modelleri destekli gelişmiş analiz modülü
├── makro_radar.py           # Makroekonomik indikatör tarayıcı
├── backtest_pro.py          # Profesyonel seviye backtest framework'ü
└── requirements.txt         # Proje bağımlılıkları
```

## 🚀 Kurulum

1. **Repoyu Klonlayın:**
   ```bash
   git clone https://github.com/talha4111/StockPredictionPro.git
   cd StockPredictionPro
   ```

2. **Gerekli Kütüphaneleri Yükleyin:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Ortam Değişkenlerini (API Key) Ayarlayın:**
   Projeyi çalıştırmak için `.env` dosyası oluşturun ve Borsa/Telegram API bilgilerinizi girin:
   ```env
   BINANCE_API_KEY=your_binance_api_key
   BINANCE_SECRET_KEY=your_binance_secret_key
   TELEGRAM_BOT_TOKEN=your_telegram_token
   TELEGRAM_CHAT_ID=your_chat_id
   ```

## ⚙️ Kullanım
Sistemi canlı modda çalıştırmak için ana komuta dosyasını başlatabilirsiniz:
```bash
python commander.py
```
Geçmişe dönük test (Backtest) çalıştırmak için:
```bash
python crypto_backtest.py
```

## 🔐 Güvenlik
Bu proje canlı para ile işlem yapma kapasitesine sahiptir. `.env`, `.pem` dosyaları ve model `.pkl` dosyaları güvenlik ile dosya boyutu optimizasyonu için `gitignore` içerisine eklenmiştir. Lütfen stratejileri canlı hesapta denemeden önce **mutlaka** backtest veya sanal kasa ortamında (Demo) test edin.

## 👨‍💻 Geliştirici
**Talha Gürler** - [@talha4111](https://github.com/talha4111)

---
*Not: Bu sistem tamamen eğitim ve kişisel araştırma amaçlı geliştirilmiştir. Kesinlikle yatırım tavsiyesi içermez.*
