# QuantBot Sistem Ogrenme Rehberi

Bu rehberin amaci sistemi "yapay zekaya yaptirmak" yerine, parca parca sahiplenmeni saglamak. Her bolumde once sistemde hangi dosyaya baktigini, sonra hangi kavrami ogrendigini, en sonda da kendin yapacagin mini egzersizi goreceksin.

## 1. Buyuk Resim

QuantBot su boru hattiyla calisir:

```text
Piyasa verisi
  -> indikatör / feature üretimi
  -> ana beyin modeli
  -> sinyal ve filtreler
  -> risk kapilari
  -> emir acma
  -> pozisyon takip / cikis
  -> muhasebe ve performans
  -> backtest / optimizasyon
```

Sistemin ana fikri sudur: model tek basina para basmaz. Model bir aday fikir uretir; para kazandirip kazandirmadigini risk filtreleri, pozisyon boyutu, sembol secimi, stop/kar-al davranisi ve muhasebe dogrulugu belirler.

## 2. Bizim Dosya Haritasi

### Baslatma ve ayarlar

- `main.py`: Botun ana giris noktasi. Borsa baglantilari, thread'ler, global durumlar ve servis akisi burada baslar.
- `config.py`: Tum ana esikler burada. Hedge/Sniper, Symbol Guard, margin, short acik/kapali, gunluk risk limiti gibi ayarlari buradan okuruz.
- `runtime_status.py`: Botun anlik durumunu panel/status dosyasina yazar.

Mini egzersiz:

- `config.py` icinde `HEDGE_MIN_RR`, `HEDGE_MIN_GUVEN`, `SYMBOL_GUARD_*` degerlerini bul.
- Her degerin "botu daha cok mu isleme sokar, daha az mi?" sorusuna kendi cevabini yaz.

### Veri ve feature uretimi

- `tarayici.py`: Binance/CCXT uzerinden OHLCV verisi ceker ve teknik gostergeleri uretir.
- Uretilen bazi feature'lar: `RSI`, `MACD`, `ATR`, `ADX`, `CHOP`, `Volume_ZScore`, `Open_Interest`, `Funding_Rate`, `EMA_Slope`.

Mini egzersiz:

- `tarayici.py` icinde `veri_getir_dortlu` fonksiyonunu oku.
- Hangi kolonlar ham veri, hangileri sonradan hesaplanan feature ayir.

### Ana beyin

- `ai_core.py`: Sistemin ana makine ogrenmesi katmani.
- `BeyinMotoru` sinifi burada.
- Su an aktif model: XGBoost classifier.
- Su anki ana parametreler: `n_estimators=500`, `max_depth=4`.
- Hedef degisken: 15 dakikalik mumda yaklasik 4 mum sonrasi, yani 1 saatlik yon.
- Model dosyalari `beyin_SYMBOL-USDT.pkl` olarak, kalite dosyalari `beyin_SYMBOL-USDT_meta.json` olarak kaydedilir.

Mini egzersiz:

- `df_hazirla` fonksiyonunda `Gelecek_Ret` ve `Hedef_Yon` nasil uretiliyor incele.
- `model_egit` fonksiyonunda train ve walk-forward validation ayrimini bul.

### Sinyal motoru

- `signal_engine.py`: Model tahminini gercek trade sinyaline cevirir.
- Model olasiligi burada `guven_skoru` olur.
- Long/short karari, RR hesabi, ATR bazli stop/target, trend kalkanlari, funding filtresi, Hedge/Sniper filtreleri burada devrededir.

Mini egzersiz:

- `analiz_motoru` fonksiyonunda bir sinyalin neden reddedilebilecegini 10 madde halinde yaz.
- `rr`, `guven_skoru`, `ADX`, `CHOP`, `Volume_ZScore` hangi sirayla etkiliyor not al.

### Tarama ve siralama

- `scanner_loop.py`: Piyasayi tarar, aday coinleri secer, sinyalleri siralar ve uygun olanlari emir motoruna gonderir.
- Ayni turda kac islem acilabilecegi ve ayni anda kac pozisyon tutulacagi burada kontrol edilir.

Mini egzersiz:

- `_hedge_dispatch_kontrol` fonksiyonunu oku.
- "Hangi durumda sinyal iyi olsa bile acilmaz?" sorusunu cevapla.

### Risk ve koruma

- `risk_manager.py`: Gunluk zarar limiti, risk kapilari, model kalite okuma, sinyal ret istatistikleri.
- `symbol_guard.py`: Son 24 saatte zarar yazan sembolleri gecici karantinaya alir.
- `exit_rules.py`: Cikis kurallarinin bir kismi.

Mini egzersiz:

- `symbol_guard.py` icinde bir coinin ne zaman karantinaya girdigini yaz.
- `risk_manager.py` icinde `MODEL_KALITE` mantigini incele.

### Emir ve pozisyon

- `order_engine.py`: Emir acar, miktar/precision/notional ayarlar, stop/TP korumalarini kurar.
- `position_tracker.py`: Acik pozisyonlari takip eder, stop/TP/cikis kurallarini uygular.
- `account_sync.py`: Binance income ledger'dan resmi realized PnL, komisyon ve funding verilerini ceker.

Mini egzersiz:

- `order_engine.py` icinde "emir acmadan once hangi guvenlik kontrolleri var?" listesini cikar.
- `account_sync.py` icinde `REALIZED_PNL`, `COMMISSION`, `FUNDING_FEE` nasil toplanir bak.

### Backtest ve optimizasyon

- `shadow_backtest.py`: Canli bota dokunmadan filtre varyasyonlarini karsilastiran golge backtest.
- `optuna_backtest.py`: XGBoost `n_estimators` ve `max_depth` gibi parametreleri Optuna ile arayan test.
- `optimizer.py`: RSI/MACD/ATR/eşik gibi strateji parametreleri icin eski golge optimizasyon hatti.
- `performance_metrics.py`: Win rate, profit factor, expectancy, max drawdown gibi metrikler.

Mini egzersiz:

- Backtest sonucunda sadece `net_pnl` degil, `max_drawdown`, `profit_factor`, `islem_sayisi`, `expectancy` degerlerini birlikte oku.
- En yuksek PnL veren parametre ile en stabil parametre ayni mi kontrol et.

## 3. Ogrenme Sirasi

### Hafta 1: Sistemi okuma ve veri mantigi

Hedef: "Bot ne yapiyor?" sorusuna kendi cumlelerinle cevap vermek.

Calisilacak dosyalar:

- `config.py`
- `main.py`
- `tarayici.py`
- `runtime_status.json`

Ogrenilecek konular:

- OHLCV nedir?
- Mum verisi nedir?
- RSI, MACD, ATR, ADX, CHOP neyi olcer?
- Binance futures sembol yapisi nedir?

Kendi gorevin:

- `BTC/USDT` icin bir veri frame'i nasil olusuyor, kagida akis olarak ciz.

### Hafta 2: Ana beyin ve makine ogrenmesi

Hedef: XGBoost modelinin neyi tahmin ettigini ve neden yanilabilecegini anlamak.

Calisilacak dosyalar:

- `ai_core.py`
- `signal_engine.py`
- `beyin_*-USDT_meta.json`

Ogrenilecek konular:

- Feature / label ayrimi
- Train / validation / forward test
- Overfitting
- XGBoost'ta `max_depth`, `n_estimators`, `learning_rate`, `subsample`
- Walk-forward validation

Kendi gorevin:

- 5 farkli coinin meta dosyasina bak.
- Walk-forward skoru 0.50 altinda olan bir modelin neden riskli oldugunu yaz.

### Hafta 3: Risk, emir ve muhasebe

Hedef: Model dogru bilse bile nasil zarar edilebilecegini anlamak.

Calisilacak dosyalar:

- `risk_manager.py`
- `symbol_guard.py`
- `order_engine.py`
- `position_tracker.py`
- `account_sync.py`

Ogrenilecek konular:

- Pozisyon boyutu
- Komisyon ve funding etkisi
- Stop-loss ve take-profit
- Realized PnL vs open PnL
- Symbol-level quarantine

Kendi gorevin:

- Bir zararli trade sec ve zararin modelden mi, stop mesafesinden mi, sembol seciminden mi, komisyondan mi geldigini ayir.

### Hafta 4: Backtest, Optuna ve karar alma

Hedef: "Bu ayari canliya alalim mi?" sorusuna veriyle cevap vermek.

Calisilacak dosyalar:

- `shadow_backtest.py`
- `optuna_backtest.py`
- `optimizer.py`
- `performance_metrics.py`

Ogrenilecek konular:

- In-sample / out-of-sample
- Walk-forward test
- Backtest overfitting
- Hyperparameter optimization
- Profit factor, expectancy, max drawdown

Kendi gorevin:

- Optuna bitince en iyi 10 denemeyi PnL'e gore degil, `PnL + drawdown + islem sayisi + stabilite` ile sirala.

## 4. Yapay Zeka Bagimliligini Azaltma Kurallari

Bu sistemde AI'yi tamamen birakmana gerek yok. Ama kullanma seklini degistirmen lazim.

1. AI'dan once kendin tahmin et.
   - "Bu fonksiyon ne yapar?" diye 3 cumle yaz.
   - Sonra AI'ya kontrol ettir.

2. AI'ya kod yazdirmadan once karar notu yaz.
   - "Neyi degistiriyoruz?"
   - "Neyi bozabilir?"
   - "Basari kriteri ne?"

3. Her degisiklikten sonra tek metrik degil, 4 metrik oku.
   - Net PnL
   - Max drawdown
   - Islem sayisi
   - Komisyon/funding

4. "Bilmiyorum" defteri tut.
   - Bilmedigin kelimeyi yaz.
   - O gun sadece 1 tanesini ogren.

5. AI'ya final cevabi sorma, once kontrol listesi sor.
   - Kotu soru: "Bunu yap."
   - Iyi soru: "Bu degisikligi yapmadan once hangi 5 riski kontrol etmeliyim?"

## 5. Mevcut Sistemi Daha Iyi Seviyeye Getirme Yol Haritasi

### 1. Backtest kalitesini yukselterek basla

Mevcut en buyuk risk, guzel gorunen ayarin gecmisi ezberlemesi. Bunu azaltmak icin:

- Her Optuna sonucunu forward/out-of-sample testten gecir.
- Ayni parametreyi farkli sembol gruplarinda test et.
- Sonucu sadece PnL'e gore secme.
- Islem sayisi cok az olan "sahte sampiyonlari" ele.

### 2. Model kalite kapisini daha bilincli kullan

Walk-forward skoru 0.50 altindaki modeller rastgeleye yakin veya daha kotu davranabilir. Sistem zaten bunu okuyor; bir sonraki seviye:

- Kirmizi model: isleme hic girme.
- Sari model: margin dusur.
- Yesil model: normal risk.
- Son 24 saat zararli sembol: Symbol Guard.

### 3. Sembol secimini iyilestir

Butun coinlere esit davranmak pahali. Bazi semboller komisyon ve whipsaw uretir.

Yapilacaklar:

- Son 7/14/30 gun sembol bazli PnL tablosu.
- Kotu sembollere daha yuksek guven/RR esigi.
- Iyi sembollere normal esik ama sadece model kalitesi yeterliyse.

### 4. Rejim filtresi ekle

Ayni strateji trend piyasasinda ve yatay piyasada ayni calismaz.

Yapilacaklar:

- BTC trend rejimi: yukari / yatay / dusus.
- Volatilite rejimi: dusuk / normal / asiri.
- CHOP yuksekse daha az islem.
- Funding kalabaliksa long tarafinda daha temkin.

### 5. Emir ve cikis tarafini ayri optimize et

Model sadece giris fikri uretir. Para genelde cikis kalitesinden gelir.

Yapilacaklar:

- ATR stop carpanini Optuna'ya dahil et.
- TP/SL ayni mumda calisirsa konservatif varsay.
- Trailing stop ve break-even kuralini ayri test et.

## 6. Guvenilir Kaynak Listesi

### Sistemimizin kullandigi teknik altyapi

- XGBoost resmi dokumani: https://xgboost.readthedocs.io/en/stable/parameter.html
- Optuna resmi tutorial: https://optuna.readthedocs.io/en/stable/tutorial/index.html
- Optuna sampling/pruning: https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/003_efficient_optimization_algorithms.html
- scikit-learn TimeSeriesSplit: https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- CCXT resmi dokuman: https://docs.ccxt.com/
- Binance USD-M Futures API: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account#get-income-history

### Backtest ve finansal ML kalitesi

- Optuna paper: https://arxiv.org/abs/1907.10902
- Hyperparameter Optimization best practices: https://arxiv.org/abs/2107.05847
- Backtest overfitting uyarisi: https://arxiv.org/abs/1408.1159
- Backtest PnL'i neden indirmeli/iskonto etmeli: https://arxiv.org/abs/1902.01802

### Backtesting araclari

- vectorbt: https://vectorbt.dev/
- Backtrader: https://www.backtrader.com/docu/

## 7. Gunluk 30 Dakikalik Calisma Plani

Her gun sadece 30 dakika:

1. 10 dakika: Bir dosyadan 30-50 satir oku.
2. 10 dakika: Okudugunu kendi cumlenle yaz.
3. 5 dakika: "Bu kisim bozulursa ne olur?" sorusunu cevapla.
4. 5 dakika: AI'ya cevabini kontrol ettir.

Bir ay sonunda sistemi "ben yazdim" seviyesinde bilmesen bile "ne nerede, neden var, neyi bozabilir" seviyesine gelirsin. Trading botta gercek sahiplik budur.

