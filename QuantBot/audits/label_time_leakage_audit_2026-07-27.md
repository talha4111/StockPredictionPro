# QuantBot Etiket ve Zaman Sızıntısı Denetimi

Tarih: 2026-07-27
Kapsam: QuantBot v5, 15 dakikalık kripto modeli, 450/8 aktif ve 400/5 gölge karşılaştırması
Denetim tipi: Salt okunur; çalışan sunucuya dağıtım veya davranış değişikliği yapılmadı.

## Yönetici kararı

V5 gölge testi, 450/8 ile 400/5 model karmaşıklığını aynı veri ve puanlama
koşullarında karşılaştırmak için kullanılabilir. Ancak aşağıdaki kritik hedef ve
zaman hizalama sorunları giderilmeden sonuç, gerçek sermaye veya otomatik model
terfisi için yeterli kanıt değildir.

Önerilen karar:

1. V5 gölge testi mevcut kimliğiyle veri toplamaya devam etsin.
2. V5 sonucu yalnızca göreli model karşılaştırması olarak etiketlensin.
3. V5'ten otomatik canlı model terfisi yapılmasın.
4. Düzeltmeler ayrı `model_schema_version=6` altında hazırlanıp temiz ölçüm
   dosyasıyla yeniden başlatılsın.

## Kanonik olay akışı — mevcut durum

| Katman | Mevcut tanım |
|---|---|
| Feature gözlem anı | Son tamamlanmış 15m mumun kapanışı |
| Eğitim etiketi | Sonraki 4 mum içinde kapanış fiyatının önce +%0,15 veya -%0,15 bariyerine ulaşması |
| Eğitimde nötr olay | Veri setinden tamamen siliniyor |
| Holdout etiketi | Yalnızca bariyere ulaşmış satırlardaki `Gelecek_Ret` |
| A/B shadow etiketi | Yaklaşık 60 dakika sonraki ticker fiyatının girişe göre en az +%0,15 olması |
| Gerçek işlem çıkışı | ATR tabanlı stop ve 2,5–3,5R hedef; intrabar high/low ile gerçekleşebilir |

Bu tanımlar aynı ekonomik olayı ölçmüyor.

## Bulgular

### [Kritik] F1 — 1h ve 4h feature'ları tarihsel satırlara erken veriliyor

Kanıt:

- `tarayici.py:48-54`, OHLCV indeksini borsanın mum **açılış zamanıyla**
  oluşturuyor.
- `tarayici.py:305-311`, üst zaman dilimi serisini hiçbir kullanılabilirlik
  gecikmesi uygulamadan 15m indekse `ffill` ediyor.
- `tarayici.py:314-385`, RSI 1h/4h, EMA slope 1h, ADX 4h, volume trend 4h ve
  trend alignment feature'larının tamamı bu yardımcıyı kullanıyor.

Örnek:

- 08:00 indeksli bir 4h mum 08:00–12:00 dönemini içerir ve ancak 12:00'de
  tamamlanır.
- Mevcut hizalama, bu mumdan hesaplanan değeri 08:00, 08:15, ..., 11:45
  satırlarına verir.
- 15m satır indeksi de mum açılış zamanıdır ve karar o mumun kapanışında
  verilir. Bu nedenle 11:45 satırı 12:00 kararında 4h değeri yasal olarak
  kullanabilir; 08:00–11:30 arasındaki 15 satır erkendir.
- 1h feature için aynı sorun mum başına 3 adet 15m kararını etkiler.

Etki:

Model, tarihsel eğitim sırasında o anda henüz kapanmamış üst zaman dilimi
mumunun nihai değerini görebilir. Canlı son satırda yalnızca tamamlanmış mum
çekilse bile tarihsel eğitim matrisi point-in-time değildir.

Gerekli düzeltme:

Üst zaman dilimi feature indeksleri, 15m frame'e hizalanmadan önce kendi mum
süreleri kadar ileri taşınmalı:

- 1h kaynak: `available_at = open_timestamp + 1h`
- 4h kaynak: `available_at = open_timestamp + 4h`

Hizalama yalnızca `available_at <= decision_at` koşuluyla backward/ffill
yapmalıdır.

### [Kritik] F2 — Eğitim etiketi ile A/B shadow etiketi aynı değil

Kanıt:

- `ai_core.py:161-179`, eğitim etiketi sonraki dört **kapanışın** bariyere ilk
  temasına göre belirleniyor.
- `live_model_compare.py:204-209`, shadow etiketi yalnızca giriş ve yaklaşık
  60 dakika sonraki terminal ticker fiyatını karşılaştırıyor.
- `live_model_compare.py:262-277`, settlement tam bir 15m kapanış dizisi değil;
  tarama yeniden geldiğinde bulunan son ticker fiyatıyla yapılıyor.

Örnek:

Bir fiyat ilk 15 dakikada +%0,20'ye çıkıp 60 dakika sonunda +%0,10'da
kapanırsa eğitim etiketi pozitif, shadow etiketi negatiftir. Tersi yol
senaryolarında da uyumsuzluk oluşur.

Etki:

Modelin kalibrasyonu bir olaya göre eğitilip başka bir olaya göre Brier skoru
alıyor. Eski A/B testlerinde iki modelin de negatif Brier skill üretmesinin
olası nedenlerinden biri budur.

Gerekli düzeltme:

Tek bir paylaşılan `OutcomeSpec` tanımlanmalı ve eğitim, holdout, offline
doğrulama ile live shadow aynı fonksiyonu kullanmalıdır.

V6 için önerilen ilk sözleşme:

- `decision_at`: tamamlanmış 15m mum kapanışı
- `entry`: sonraki yürütülebilir fiyat / backtestte sonraki mum açılışı +
  slippage
- `horizon`: tam 4 adet 15m mum
- `y_long=1`: terminal net getiri, tahmini tüm maliyet ve minimum edge'in
  üzerindeyse
- `y_long=0`: diğer bütün sonuçlar
- Nötr satırlar korunmalı
- Short açılacaksa ayrı `y_short` ve ayrı kalibrasyon kullanılmalı

Bu terminal alpha hedefi, ATR stop/target işlem simülatöründen ayrı tutulmalıdır.
İşlem ekonomisi daha sonra OHLC path-aware backtest ile ölçülmelidir.

### [Yüksek] F3 — `drop_neutral` parametresi etkisiz; nötr satırlar her durumda siliniyor

Kanıt:

- `ai_core.py:104`, fonksiyon `drop_neutral=False` kabul ediyor.
- `ai_core.py:178-185`, bariyere değmeyen satırlar `NaN` bırakılıyor ve
  koşulsuz `dropna` ile siliniyor.
- Sentetik kontrolde hem `drop_neutral=False` hem `drop_neutral=True` için
  etiketli satır sayısı sıfır çıktı.

Etki:

- Model olasılığı `P(yukarı bariyer | bariyerlerden biri gerçekleşti)` haline
  geliyor.
- Canlıda görülen sakin/nötr piyasa dağılımı eğitim ve kalibrasyonda yok.
- Satırlar silindiği için fold ve holdout uzunluğu takvim zamanı yerine olay
  yoğunluğuna bağlı oluyor.
- Model düşük olasılığı hem düşüş hem de nötr hareket için doğru biçimde
  yorumlayamıyor.

Gerekli düzeltme:

Etiket üretimi tam kronolojik frame'i korumalıdır. Label kullanılamayan son
`horizon` satırı dışında her gözlem açık bir sınıf almalıdır. Purge/embargo,
silinmiş olay sırasına değil orijinal zaman indeksine göre uygulanmalıdır.

### [Yüksek] F4 — “Triple-barrier” uygulaması intrabar high/low kullanmıyor

Kanıt:

- `ai_core.py:156-176`, yalnızca `Hedef_Close` dizisini okuyor.
- Gerçek işlem/backtest motoru `shadow_backtest.py:374-408` içinde high/low ile
  stop ve hedef temasını kontrol ediyor ve aynı mumda ikisi de olursa
  `stop_first_same_bar` uyguluyor.

Sentetik kontrolde sonraki mumun high değeri +%0,30, low değeri -%0,30 olmasına
rağmen kapanış değişmediğinde eğitim hiçbir etiket üretmedi.

Etki:

Kodda “triple-barrier” olarak adlandırılan hedef ile emir yaşam döngüsü aynı
path olayını temsil etmiyor. Holdout strateji PnL'si gerçek ATR stop/target
ekonomisini ölçmüyor.

Gerekli düzeltme:

İki kavram ayrılmalıdır:

1. Alpha etiketi: sabit ufuk terminal net getiri.
2. Trade simülasyonu/meta-label: high/low kullanan ATR stop/target; aynı mum
   belirsizliğinde muhafazakâr stop-first.

Eğer model etiketi yeniden gerçek triple-barrier yapılacaksa shadow settlement
da ufuk boyunca high/low path toplamalıdır.

### [Yüksek] F5 — OI/funding tarih kapsamı ana frame ile eşit değil

Kanıt:

- Ana 15m frame `tarayici.py:64` içinde 4.000 mum ister.
- Open interest `tarayici.py:133` içinde en fazla 1.000 dönem ister.
- Funding `tarayici.py:143` içinde en fazla 100 funding olayı ister.
- Eksik geçmiş `tarayici.py:152-154` içinde sabit baseline ile doldurulur.

Yaklaşık üst sınır:

- OI: 1.000 / 4.000 bar kapsaması; geçmişin yaklaşık %75'i sıfır baseline.
- Funding: 8 saatlik 100 olay yaklaşık 3.200 adet 15m bara denk gelir;
  geçmişin yaklaşık %20'si baseline olabilir.

Etki:

Model gerçek piyasa rejimi yerine “feature veri kaynağı bu tarihte başladı”
sınırını öğrenebilir. `Funding_Delta` da baseline/gerçek veri geçişinden
etkilenir.

Gerekli düzeltme:

- Her feature için `coverage_ratio`, ilk/son gerçek timestamp ve stale oranı
  kaydedilmeli.
- Minimum kapsama sağlanmıyorsa feature o eğitim koşusundan çıkarılmalı veya
  model eğitimi fail-closed durmalıdır.
- Eksik değer ile gerçek sıfır aynı sayı olarak kodlanmamalı; gerekiyorsa
  ayrıca `feature_available` maskesi kullanılmalı.

### [Orta] F6 — Backtest OI/funding ile canlı OI/funding aynı veri değil

Kanıt:

- `crypto_backtest.py:103-104`, OI için rolling volume, funding için rolling
  return proxy'si kullanıyor.
- `tarayici.py:133-148`, canlı/eğitim akışı borsa OI ve funding geçmişini
  kullanmaya çalışıyor.

Etki:

Offline model seçimi ile çalışan modelin feature anlamı farklı olabilir.
Optuna sonucu aynı feature isimleri altında farklı ekonomik veriyi test eder.

Gerekli düzeltme:

Backtest ve canlı eğitim aynı point-in-time veri snapshot deposundan
beslenmelidir. Proxy kullanılan bir deney ayrı feature/schema adı taşımalıdır.

### [Orta] F7 — Veri kalite kapısı geçmiş feature kalitesini ölçmüyor

Kanıt:

- `risk_manager.py:479-519`, mum sayısını, son mum yaşını, kolon varlığını ve
  yalnızca son satırdaki NaN/inf değerlerini kontrol ediyor.

Kontrol edilmeyenler:

- Tarihsel feature kapsaması
- Sabit/baseline oranı
- Zaman boşluğu ve yinelenen timestamp
- Feature `available_at` zamanı
- Ani baseline-gerçek veri sınırı
- OI/funding stale süresi

Gerekli düzeltme:

Dataset sözleşmesine coverage, monotonic index, expected interval, duplicate,
staleness ve point-in-time kontrolleri eklenmelidir.

### [Orta] F8 — Model kalite metrikleri koşullu holdout üzerinden hesaplanıyor

Kanıt:

- `ai_core.py:243-245`, `df_hazirla` nötrleri zaten sildikten sonra holdout
  oluşturuluyor.
- `ai_core.py:265-328`, holdout son takvim dönemi değil son bariyer olaylarıdır.
- `ai_core.py:452`, `recent_neutral_count` hesaplanıyor; fakat nötr satırlar
  önceden silindiği için yapısal olarak sıfırdır.
- `signal_engine.py:267-305`, bu metrikler model kalite kapısında kullanılır.

Etki:

Kalite kapısı gerçek canlı sınıf dağılımını temsil etmeyen metriklerle modeli
geçirebilir veya engelleyebilir.

Gerekli düzeltme:

Holdout önce tam kronolojik frame üzerinde takvim/zaman sınırıyla ayrılmalı,
purge uygulanmalı ve tüm sınıflar korunmalıdır. Kalite metrikleri aynı canonical
outcome üzerinde hesaplanmalıdır.

## V5 testinin yorum sınırı

V5'in cevaplayabileceği soru:

> Aynı mevcut veri/etiket/settlement boru hattında 450/8 mi, 400/5 mi daha iyi
> davranıyor?

V5'in güvenilir biçimde cevaplayamayacağı sorular:

- Model olasılıkları gerçek 60 dakikalık sonuç için kalibre mi?
- Backtest kârı gerçek işlem kurallarıyla tekrar eder mi?
- Üst zaman dilimi feature'ları sızıntısız mı?
- Model gerçek para için hazır mı?

## V6 düzeltme sırası

1. `OutcomeSpec` ve `FeatureAvailabilitySpec` sözleşmelerini oluştur.
2. MTF indekslerini `available_at` zamanına taşı ve sentetik sızıntı testlerini
   ekle.
3. Etiketi tam kronolojik frame üzerinde üret; nötrleri koru.
4. Train/CV/holdout ayrımını orijinal timestamp üzerinden purge/embargo ile yap.
5. Live comparator'ı aynı outcome fonksiyonuna geçir; tam ufuk kapanışını
   kaydet.
6. OI/funding kapsama raporu ve fail-closed eşiği ekle.
7. Offline doğrulamayı gerçek point-in-time snapshot ve aynı feature koduyla
   çalıştır.
8. Temiz v6 A/B state'i ile 450/8, 400/5 ve basit logistic baseline'ı yeniden
   ölç.

## V6 kabul testleri

- Her feature için `available_at <= decision_at`.
- 1h ve 4h sentetik mumları kapanmadan hiçbir 15m satırında görünmüyor.
- Label sayısı, son horizon satırları hariç kronolojik gözlem sayısına eşit.
- Eğitim, holdout ve live A/B aynı outcome fonksiyonunu çağırıyor.
- OI/funding gerçek veri kapsaması eşik altında ise eğitim başlamıyor.
- Aynı mumda stop ve hedef teması, trade simülatöründe stop-first.
- Entry fiyatı sinyal mumunun kapanışı değil sonraki yürütülebilir fiyat ve
  slippage ile ölçülüyor.
- V6 sonuç dosyası v5 state ve model artefaktlarından fiziksel olarak ayrı.

## Uygulama durumu

2026-07-27 MTF entegrasyon dilimi:

- `FeatureAvailabilitySpec` bağımsız ve kimlikli sözleşme olarak eklendi.
- `tarayici.veri_getir_dortlu`, `feature_schema_version` seçicisi aldı.
- Varsayılan değer 5 olarak bırakıldı; mevcut `signal_engine` çağrısı schema
  belirtmediği için v5 davranışı değişmedi.
- Schema 6 açıkça seçildiğinde RSI 1h/4h, EMA slope 1h, ADX 4h, volume trend
  4h ve trend alignment değerleri kaynak mum kapanış zamanından önce
  gösterilmiyor.
- V5/v6 yan yana sentetik zaman çizelgesi, sözleşme, A/B, promotion ve gerçek
  instance-lock dahil 29 test geçti.
- Sunucuya dağıtım yapılmadı; çalışan v5 gölge testinin kimliği korunuyor.

2026-07-27 etiket entegrasyon dilimi:

- `BeyinMotoru`, varsayılanı 5 olan bağımsız `label_schema_version` seçicisi
  aldı; mevcut çağrılar ve `beyin_*` v5 artefakt adları değişmedi.
- Schema 6 açıkça seçildiğinde `OutcomeSpec`, sinyalden sonraki mum açılışını
  giriş ve dördüncü gelecek mum kapanışını çıkış olarak kullanıyor.
- Son dört bilinmeyen ufuk satırı dışında nötr ve negatif sonuçlar `y_long=0`
  olarak korunuyor; maliyet sonrası minimum edge pozitif sınıf eşiğine dahil.
- V6 artefaktları için ayrı `v6_beyin_*` prefix'i ayrıldı.
- Kronolojik holdout/purge entegrasyonu tamamlanana kadar v6 eğitim ve tahmin
  yolları fail-closed kilitlendi; yanlışlıkla model üretilemiyor veya
  yüklenemiyor.
- Yeni etiket sözleşmesi, eski model kalite, MTF, A/B, manifest, promotion ve
  instance-lock dahil 36 test geçti.
- Sunucuya dağıtım veya süreç restartı yapılmadı; çalışan v5 gölge testi aynı
  ayarlarla devam ediyor.

2026-07-27 kronolojik CV/holdout dilimi:

- `PurgedWalkForwardSpec`, 15 dakikalık orijinal `DatetimeIndex` üzerinde
  kimlikli v6 split sözleşmesi olarak eklendi.
- Split girdisi artan, benzersiz ve kesintisiz 15m zaman çizelgesi değilse
  fail-closed davranıyor.
- Her train/validation sınırında dört mum purge uygulanıyor; son train
  etiketinin bitiş zamanı ilk validation karar zamanından kesin olarak önce
  olmak zorunda.
- Üç expanding-window CV fold'u arasında bir mum embargo kaydediliyor.
- Holdout boyu etiketlenmiş satır sayısından değil orijinal zaman çizelgesinden
  kuruluyor. İstenen 80 değerlendirilebilir gözlem için 80 + 4 bilinmeyen
  outcome kuyruğu ayrılıyor.
- Eksik/elenen bir outcome satırı split sınırlarını öne kaydıramıyor; sınırlar
  önce ham zaman çizelgesinde sabitlenip uygun satırlar daha sonra seçiliyor.
- V6 eğitim planı `BeyinMotoru.v6_egitim_plani_hazirla` ile artefakt üretmeden
  denetlenebiliyor. Model eğitimi ve tahmin kilitleri henüz açılmadı.
- Etiket, MTF, kronolojik split, eski model kalite, A/B, manifest, promotion ve
  instance-lock dahil 43 test geçti.
- Sunucuya dağıtım veya süreç restartı yapılmadı; çalışan v5 gölge testi
  etkilenmedi.

2026-07-27 v6 çevrimdışı eğitim entegrasyon dilimi:

- `tarayici`, ürettiği DataFrame'e feature schema, base timeframe ve
  `FeatureAvailabilitySpec` sözleşme kimliğini provenance olarak ekliyor.
- V6 eğitim bu provenance alanları eksik, schema 6 dışında veya sözleşme
  kimliği uyumsuzsa başlamıyor.
- Üç purged/embargoed expanding-window fold ayrı ayrı eğitiliyor; kalibrasyon
  yalnızca fold dışı OOF olasılıklardan kuruluyor.
- Holdout modeli yalnızca holdout öncesi train bölümünü görüyor. Holdout
  sınıfları doğrudan ortak `OutcomeSpec` tarafından üretilen `Hedef_Yön`
  kolonundan alınıyor.
- V6 strateji metriği `Gelecek_Net_Ret` kullandığı için işlem maliyeti ikinci
  kez düşülmüyor.
- Nihai araştırma modeli tüm uygun geçmişle eğitiliyor ve ayrı
  `v6_beyin_*`/`v6_stock_beyin_*` artefakt alanına yazılıyor.
- Meta dosyası feature, outcome ve split sözleşme kimliklerini; fold zaman
  sınırlarını; OOF, kalibrasyon ve holdout metriklerini içeriyor.
- Artefakt `training_mode=offline_research` ve
  `live_prediction_enabled=false` olarak işaretleniyor. V6 tahmin yolu hâlâ
  fail-closed kilitli.
- Formattan kalan bozuk `venv` değiştirilmeden, git tarafından ignore edilen
  ayrı `.venv` smoke ortamı Python 3.12 ile oluşturuldu.
- Projede sabitlenmiş NumPy 2.2.6, pandas 3.0.0, scikit-learn 1.8.0, joblib
  1.5.3 ve XGBoost 3.2.0 sürümleri kuruldu; `pip check` bağımlılık sorunu
  bulmadı.
- Gerçek XGBoost ve gerçek scikit-learn kalibrasyonuyla 3 CV + 1 holdout + 1
  final fit akışı sentetik v6 verisinde geçti. Kaydetme fonksiyonları mock
  edildiği için `.pkl` veya meta artefaktı üretilmedi.
- Etiket, MTF, provenance, kronolojik split, v6 eğitim, eski model kalite, A/B,
  manifest, promotion, gerçek XGBoost smoke ve instance-lock dahil 46 test
  geçti.
- Sunucuya dağıtım, süreç restartı veya gerçek v6 model üretimi yapılmadı;
  çalışan v5 gölge testi etkilenmedi.

2026-07-27 v6 live comparator outcome entegrasyon dilimi:

- `LiveModelComparator`, varsayılanı 5 olan `label_schema_version` seçicisi
  aldı. Mevcut v5 schema 2 state ve ticker settlement davranışı korundu.
- V6 comparator schema 3 ve ayrı `live_model_compare_v6_state.json` kullanıyor;
  v5/v6 state dosyası veya outcome sözleşmesi uyuşmazlığında fail-closed
  davranıyor.
- V6 pending gözlem karar mumunun bar-open timestamp'ini, feature schema
  sürümünü ve aktif/gölge modellerin iki outcome contract kimliğini kaydediyor.
  Modellerden biri farklı hedef sözleşmesi taşıyorsa gözlem kabul edilmiyor.
- Settlement, ticker snapshot yerine karar mumundan başlayan kesintisiz 15m
  OHLCV dizisini ortak `OutcomeSpec.build_long_outcomes` fonksiyonuna veriyor.
- Giriş sonraki mum açılışı, çıkış dördüncü gelecek mum kapanışı ve outcome
  kullanılabilirlik zamanı çıkış mumunun kapanışı olarak birebir uygulanıyor.
- Erken bariyer teması v6 etiketini değiştirmiyor; terminal net outcome eğitim,
  holdout ve live comparator için aynı tanım.
- Eksik ara mumda settlement yapılmıyor. Restart gecikmiş olsa bile scanner
  OHLCV isteğini pending kaydın gerçek `decision_bar_open` zamanından `since`
  ile başlatıyor.
- V6 ticker settlement açıkça reddediliyor. Scanner yalnızca schema 6 seçilirse
  bar settlement dalına giriyor; mevcut `LiveModelComparator()` çağrısı schema
  belirtmediği için çalışan v5 yolu değişmedi.
- State yazımı OneDrive/Windows geçici kilitlerine karşı UUID geçici dosya,
  `fsync`, atomik replace ve sınırlı retry ile sağlamlaştırıldı.
- Eğitim/etiket/MTF/provenance/split, gerçek XGBoost smoke, v5/v6 comparator,
  promotion ve instance-lock dahil 51 test geçti.
- Sunucuya dağıtım, süreç restartı veya v6 state/model üretimi yapılmadı;
  çalışan v5 gölge testi etkilenmedi.

2026-07-27 v6 OI/funding veri kalitesi dilimi:

- `FeatureCoverageSpec`, dış metrikleri 15 dakikalık karar zamanına point-in-time
  hizalıyor. Her metrik için gerçek gözlem, kullanılabilirlik ve yaş bilgisi
  ayrı kolonlarda tutuluyor; baseline değer ile gerçek sıfır artık birbirine
  karıştırılmıyor.
- Open interest en fazla 2 bar, funding en fazla 36 bar taşınabiliyor. Bu
  sınırların ötesindeki değer feature kolonunda nötr baseline'a dönse bile
  `Available=0` olarak işaretleniyor.
- V6 provenance; coverage sözleşme kimliği, toplam/recent coverage, baseline ve
  stale oranları, ilk/son kullanılabilir zaman ve gerçek sıfır sayısını içeriyor.
- Eğitim kapısı her iki metrikte en az `%60` toplam, son 192 barda `%95` coverage
  ve son mumda kullanılabilirlik istiyor. Ardından yalnızca iki metriğin ortak
  olduğu en son kesintisiz suffix kullanılıyor; bu bölüm en az 1000 bar değilse
  eğitim başlamıyor.
- V6 model meta verisine coverage sözleşmesi, eşikler, kalite raporları ve ortak
  eğitim aralığı ekleniyor. V6 canlı risk kapısı da son mum maskelerini ve aynı
  kalite raporlarını doğruluyor.
- Tek sayfalık borsa cevabının eşiği karşılayacağı varsayılmıyor. Tarihsel veri
  yetersizse sistem baseline ile model eğitmek yerine fail-closed duruyor; çok
  sayfalı toplama/snapshot deposu bir sonraki veri edinim dilimi olarak kaldı.
- Seçilmiş regresyon, gerçek XGBoost smoke ve yeni coverage/risk testlerinden 61
  test; ayrıca iki süreçli instance-lock testleri geçti. Bağımlılık denetimi
  temiz ve değiştirilmiş dosyalar derleniyor.
- Sunucuya dağıtım, süreç restartı, gerçek API çağrısı veya v6 state/model
  üretimi yapılmadı; çalışan v5 gölge testi etkilenmedi.

2026-07-27 v6 OI/funding pagination ve snapshot dilimi:

- V6 dış metrik edinimi tek cevaba bağlı olmaktan çıkarıldı. Open interest
  `since` ile ileri doğru, sayfa başına en fazla 500 kayıt ve toplam en fazla 10
  çağrı; funding sayfa başına en fazla 1000 kayıt ve toplam en fazla 4 çağrı ile
  bounded olarak ilerliyor.
- Her sayfada timestamp sırası temizleniyor, tekrarlar son kayıt lehine
  birleştiriliyor ve cursor ilerlemiyorsa döngü fail-closed kesiliyor.
- Binance open-interest endpointinin yalnızca son bir aylık veriyi sunması
  sözleşmeye işlendi. İstenen 4000 mumun erişilemeyen kısmı sahte değerle
  tamamlanmıyor; mevcut coverage kapısı gerçek kullanılabilir oranı ölçmeye
  devam ediyor.
- `.cache/external_metrics_v6` altında sembol/metrik/timeframe kimlikli atomik
  JSON snapshot deposu eklendi. Dosya adı bileşenleri path traversal'a kapalı;
  kayıt gövdesi SHA-256 checksum, schema ve kimlik doğrulamasından geçiyor.
- Snapshot güncellemesi UUID geçici dosya, exclusive-create, `fsync`, atomik
  replace ve Windows/OneDrive kilitleri için sınırlı retry kullanıyor. Başarısız
  replace önceki sağlam snapshot'ı koruyor.
- Başarılı her sayfa grubu hata sonrasında dahi kaydediliyor. Restart, son
  timestamp + 1 milisaniyeden devam ediyor; tamamlanmış aynı aralık yeniden
  indirilmeden snapshot'tan okunuyor.
- Acquisition çağrı/kayıt sayıları, pagination tamamlanma durumu, API hatası,
  snapshot bütünlük/yazım durumu coverage provenance içine ekleniyor.
- V5 yolu eski tek çağrı imzalarını ve varsayılan schema 5 davranışını koruyor.
- Pagination, cursor non-progress, yarım indirmeden restart, checksum, atomik
  replace, coverage, canlı risk ve gerçek XGBoost dahil 69 test; ayrıca iki
  süreçli instance-lock testi geçti. Derleme ve bağımlılık denetimi temiz.
- Gerçek borsa API'sine çağrı, sunucuya dağıtım, süreç restartı veya v6
  model/state/snapshot üretimi yapılmadı; çalışan v5 gölge testi etkilenmedi.

2026-07-27 gerçek veri doğrulaması ve v6 artifact kalite kapısı dilimi:

- Gerçek BTC/USDT 15m veri edinimi 3931 ham mum üretti. Binance open-interest
  geçmişinin tam 30 günlük sınırında `startTime` reddetmesi üzerine istek
  tabanı 29 günlük güvenli pencereye çekildi; funding kapsamı `%100`, OI toplam
  kapsamı `%70,82` ve son 192 mum OI kapsamı `%100` olarak doğrulandı.
- Gerçek ortak OI/funding suffix'i 2784 mum, değerlendirilebilir eğitim bölümü
  2780 outcome ve holdout 200 outcome üretti. Üç fold'un purge/embargo ve
  kronolojik sınır sözleşmeleri eksiksiz geçti.
- Gerçek BTC dry-run modeli CV ve holdout'ta `0,500` dengeli doğruluk üretti;
  holdout Brier skill `-0,008`, bağımsız sinyal sayısı `0`, net strateji
  getirisi ve profit factor `0` kaldı. Bu sonuç alfa kanıtı değildir.
- V6 eğitimine, canlı kalite eşikleriyle uyumlu bir offline artifact kapısı
  eklendi. CV/holdout dengeli doğruluk, Brier ve Brier skill; en az 8 bağımsız
  holdout sinyali; pozitif net getiri ve en az `1,10` profit factor birlikte
  denetleniyor.
- Kapı başarısızsa nihai model hiç eğitilmiyor, `artifact_saved=false`
  bellekteki rapora yazılıyor ve model/meta kayıt fonksiyonları çağrılmadan
  eğitim fail-closed sonlanıyor. Başarılı artifact meta verisi kapının
  eşiklerini, metriklerini ve geçti bilgisini taşıyor.
- Sabit `0,50` olasılık üreten no-alpha sınıflandırıcısının dört değerlendirme
  fit'inden sonra kesildiğini ve hiçbir artifact yazmadığını doğrulayan regresyon
  testi eklendi.
- Model/outcome/feature/split, dış metrik deposu, comparator, promotion, risk,
  safety ve gerçek XGBoost dahil 73 test; slippage için ayrıca 5 test ve iki
  süreçli instance-lock için 2 test geçti. Derleme ve `pip check` temiz.
- Son gerçek BTC dry-run yeni kapı tarafından altı açık nedenle reddedildi ve
  mocklanan model/meta kayıt çağrıları sıfır kaldı. Sunucu dağıtımı, süreç
  restartı, canlı emir veya v6 model/state artifact üretimi yapılmadı; çalışan
  v5 sistem etkilenmedi.

2026-07-28 v6 olasılık diagnostikleri ve ölçek-duyarlı split dilimi:

- V6 offline meta verisine schema kimlikli tahmin diagnostikleri eklendi.
  Her fold ile toplam CV ve holdout için ham/kalibre dengeli doğruluk, Brier,
  hedef prevalansı, olasılık yüzdelikleri, `0,50` sınıflandırma ve sinyal eşiği
  üzerindeki aday sayıları ayrı kaydediliyor.
- Holdout ham ve kalibre stratejileri; bağımsız sinyal sayısı, net getiri ve
  profit factor ile yan yana raporlanıyor. Böylece model alfası ile
  kalibrasyonun güven daraltma etkisi birbirinden ayrılabiliyor.
- Mevcut `450 ağaç / derinlik 8` Optuna ayarlarıyla gerçek BTC dry-run'da ham
  CV dengeli doğruluk `0,541`, ham holdout `0,537` çıktı. Buna rağmen ham
  holdout stratejisi yalnızca 6 bağımsız sinyal, `-%0,116` net getiri ve
  `0,842` profit factor üretti.
- Platt eğimi `0,132` oldu ve kalibre olasılıklar yaklaşık `%20-%41` aralığına
  sıkıştı. Bu, kalibrasyonun kârlı bir sinyali yok etmesinden çok ham modelin
  aşırı güvenli ve zayıf ayrıştırıcı olduğuna işaret etti.
- İlk walk-forward fold'unun yalnızca minimum 100 mumu kullanması ölçekleme
  kusuru olarak düzeltildi. `PurgedWalkForwardSpec`, artık en az sabit minimum
  ile kullanılabilir CV geçmişinin `%40`'ından büyük olanını ilk eğitim
  penceresi olarak seçiyor; bu oran split sözleşme kimliğinin parçası.
- Gerçek BTC tekrarında fold eğitim boyları `1032 / 1546 / 2060`, validation
  boyları `513 / 513 / 513` oldu. Ham CV dengeli doğruluk `0,534`; holdout
  sonuçları değişmeden zayıf ve maliyet sonrası zararlı kaldı. Model yine kalite
  kapısından geçmedi ve model/meta kayıt çağrıları sıfırdı.
- Eşiği keyfî biçimde düşürme veya başarısız modeli kaydetme yapılmadı. Sonraki
  araştırma, yalnızca CV OOF üzerinde karar/sinyal eşiği diagnostikleri ve
  feature/rejim katkı ayrıştırması olarak sınırlandı; holdout seçim için
  kullanılmayacak.
- Model/outcome/feature/split, dış metrik deposu, comparator, promotion, risk,
  safety ve gerçek XGBoost dahil 73 test; slippage için 5 ve iki süreçli
  instance-lock için 2 test geçti. Derleme ve bağımlılık denetimi temiz.
- Sunucu dağıtımı, süreç restartı, canlı emir veya v6 model/state artifact
  üretimi yapılmadı; çalışan v5 sistem etkilenmedi.

2026-07-28 v6 CV-only eşik ve permutation feature araştırma dilimi:

- V6 diagnostiklerine yalnızca kalibre CV-OOF tahminlerinde çalışan, schema
  kimlikli karar ve sinyal eşiği taraması eklendi. Sınıflandırma için
  `0,10-0,50`, sinyal için `0,10-0,60` aralığı `0,01` adımla taranıyor.
- Sinyal eşiği seçiminde en az 20 veya OOF satırlarının `%1`'i kadar bağımsız
  CV sinyali şartı uygulanıyor. Eşik seçiminde holdout hedefleri veya getirileri
  kullanılmıyor; `selection_scope=cv_oof_only`,
  `holdout_used_for_selection=false` ve `activated=false` meta verisine
  yazılıyor.
- Holdout hedef ve getirileri tamamen değiştirildiğinde seçilen CV eşiklerinin
  değişmediğini doğrulayan izolasyon testi eklendi. Araştırma eşikleri kalite
  kapısına, artifact'a veya canlı sinyal motoruna uygulanmadı.
- Gerçek BTC araştırmasında CV'nin seçtiği sınıf eşiği `0,24` ile CV dengeli
  doğruluk `0,540` olurken temiz holdout doğruluğu `0,492`'ye düştü. Seçilen
  sinyal eşiği `0,32`; CV'de 20 sinyal, `-%2,376` net getiri ve `0,363` profit
  factor; holdout'ta 2 sinyal, `-%0,154` net getiri ve `0,114` profit factor
  üretti. Eşik optimizasyonu genellenebilir alfa göstermedi.
- Her CV fold validation bölümünde her feature'ı deterministik olarak tek tek
  permüte eden dış-örnek katkı analizi eklendi. Ham dengeli doğruluk düşüşü ve
  Brier artışı feature/fold bazında kaydediliyor; sonuç yalnızca diagnostik ve
  `activated=false`.
- Gerçek BTC'de üç fold'un tamamında Brier'ı pozitif etkileyen feature çıkmadı.
  En umut verici ancak yalnızca iki fold'da desteklenen grup
  `EMA_Slope_1H`, `RSI_4H`, `Funding_Rate`, `Vol_Ret`, `BTC_Korelasyon` ve
  `Volatility_20` oldu.
- `RSI_1H`, `RSI`, `EMA_Slope`, `ATR_ZScore`, `Hour_Cos`, `ADX`,
  `Volume_Trend_4H` permutation sonrasında Brier'ı üç fold'un hiçbirinde
  kötüleştirmedi; mevcut modelde olasılık kalitesine istikrarlı katkı
  kanıtlamadılar. Ortak coverage suffix'inde sabit kalan availability/age
  maskelerinin katkısı sıfır ölçüldü.
- Hiçbir feature otomatik silinmedi. Sonraki aday, yalnızca CV katkı kuralıyla
  önceden kilitlenecek azaltılmış feature setinin ayrı shadow modeli olarak
  eğitilip holdout'ta tek sefer karşılaştırılmasıdır.
- İlgili sözleşme, veri, model, comparator, promotion, risk, safety ve gerçek
  XGBoost dahil 74 test; slippage için 5 ve iki süreçli instance-lock için 2
  test geçti. Derleme ve bağımlılık denetimi temiz.
- Model kalite kapısından geçmedi; model/meta kayıt çağrıları sıfır kaldı.
  Sunucu dağıtımı, süreç restartı, canlı emir veya v6 model/state artifact
  üretimi yapılmadı; çalışan v5 sistem etkilenmedi.

2026-07-28 v6 azaltılmış feature shadow aday dilimi:

- Baseline CV permutation sonuçlarından feature seçen sabit araştırma kuralı
  eklendi: ortalama Brier katkısı pozitif, en az iki fold'da Brier katkısı ve en
  az iki fold'da dengeli doğruluk katkısı pozitif olmalı. En fazla 12 feature
  seçiliyor; en az 3 feature bulunmazsa aday fail-closed atlanıyor.
- Seçim yalnızca baseline CV validation permutation sonuçlarını kullanıyor.
  Shadow meta verisi `selection_scope=baseline_cv_permutation_only`,
  `holdout_used_for_selection=false`,
  `holdout_role=research_comparison_not_promotion_evidence`,
  `activated=false` ve `artifact_saved=false` alanlarını taşıyor.
- Azaltılmış aday aynı purged üç fold'da yeniden eğitiliyor, yalnızca kendi OOF
  olasılıklarından ayrı Platt kalibrasyonu kuruyor ve mevcut araştırma
  holdout'unda tam modelle karşılaştırılıyor. Kendi CV-only eşik taraması da
  ayrı raporlanıyor; sonuç kalite kapısına veya canlıya bağlanmıyor.
- Minimum feature sayısı ilk taslakta ihtiyari olarak 4 seçilmişti. Gerçek CV
  kuralı `OBV`, `BTC_Korelasyon`, `RSI_4H` olmak üzere üç farklı bilgi
  ailesinden 3 feature seçince, shadow holdout'u hiç görmeden teorik dayanağı
  olmayan bu alt sınır 3'e indirildi; katkı eşikleri gevşetilmedi.
- Gerçek üç-feature shadow fold ham dengeli doğrulukları
  `0,491 / 0,520 / 0,497` oldu. Kalibre CV dengeli doğruluk `0,500`, Brier
  `0,190125`; holdout dengeli doğruluk `0,500`, Brier `0,182104` çıktı.
- Tam modele göre shadow CV Brier'ı `0,000515` kötüleştirirken holdout Brier'ı
  yalnızca `0,001115` iyileştirdi. Bu küçük olasılık iyileşmesi fold'lar boyunca
  genellenmedi.
- Shadow CV'nin seçtiği `0,26` karar eşiği holdout dengeli doğruluğu `0,525`'e
  çıkardı; fakat aynı `0,26` sinyal eşiği CV'de 103 sinyal ve `-%10,369` net
  getiri / `0,389` profit factor, holdout'ta 16 sinyal ve `-%0,199` net getiri
  / `0,892` profit factor üretti. İşlem alfası kanıtlanmadığı için aday
  reddedildi.
- Skip ve evaluated yolları, yalnızca CV katkısından seçim, holdout izolasyonu
  ve sıfır shadow artifact üretimi regresyon testleriyle doğrulandı.
- İlgili sözleşme, veri, model, comparator, promotion, risk, safety ve gerçek
  XGBoost dahil 76 test; slippage için 5 ve iki süreçli instance-lock için 2
  test geçti. Derleme ve bağımlılık denetimi temiz.
- Tam ve azaltılmış modeller için kayıt çağrıları sıfır kaldı. Sunucu dağıtımı,
  süreç restartı, canlı emir veya v6 model/state artifact üretimi yapılmadı;
  çalışan v5 sistem etkilenmedi.
