# 🧠 StockPredictionPro — Proje Hafızası & Devir Teslim Belgesi
*Son Güncelleme: 04 Ekim 2026*  
*Bu dosya, yeni bir yapay zeka sohbeti açıldığında ajanın projenin tüm geçmişini, mimarisini, kullanıcı tercihlerini ve portföy durumunu 1 saniyede eksiksiz anlaması için hazırlanmıştır.*

---

## 👤 1. Kullanıcı Profili & Yatırım Stratejisi
* **Kullanıcı:** Talha (@talha4111)
* **İşlem Platformu:** Midas (ABD Borsaları, komisyon işlem başına $1.50, FIFO lot satışı).
* **Yatırım Tarzı:** Büyüme + Yapay Zeka / Yarıiletken odaklı hisseler, kurumsal değer & momentum swing işlemleri.
* **Aktif Takip Listesi (`watchlist.json`):**  
  `MU` (Micron), `MRVL` (Marvell), `AVGO` (Broadcom), `BE` (Bloom Energy), `EOG` (EOG Resources), `COHR` (Coherent).  
  *(Ayrıca izlenen AI altyapı hisseleri: VRT, CEG, GEV, NVDA).*
* **Talha'nın Güncel Micron (MU) Giriş Lotları (Midas FIFO):**
  1. **Lot 1:** 2026-03-15 · 1 Adet · **$450.00** (Giriş kuru: 38.50 ₺)
  2. **Lot 2:** 2026-05-10 · 1 Adet · **$780.00** (Giriş kuru: 42.10 ₺)
  3. **Lot 3:** 2026-07-20 · 1 Adet · **$956.00** (Giriş kuru: 45.20 ₺)
  4. **Lot 4:** 2026-08-25 · 1 Adet · **$1,014.00** (Giriş kuru: 47.80 ₺)
  5. **Lot 5:** 2026-09-18 · 1 Adet · **$1,080.00** (Giriş kuru: 48.90 ₺)
  > ⚠️ **Kritik Kural:** Midas FIFO (First-In, First-Out) çalışır. Satış yapıldığında en eski lot ($450) ilk satılır; kullanıcı spesifik olarak 1080'i satamaz.

---

## 🏗️ 2. Sistem Mimarisi & Web Paneli
Proje, kurumsal seviyede bir **Factor Research & Equity Engine (v3.1)** ve bunun üzerine kurulu bir **Streamlit Multipage Web Dashboard**'udur.

### 🌐 Canlı Yayın (Streamlit Community Cloud):
* **GitHub Deposu:** `talha4111/StockPredictionPro` (Branch: `main`)
* **Canlı Link:** Streamlit Cloud üzerinde 7/24 aktif çalışır.
* **Git Yönetimi:** Bilgisayarda **GitHub Desktop** kullanılıyor.
* **Uyku Önleyici Bot:** `.github/workflows/keep_awake.yml` ile her 6 saatte bir GitHub Action sessiz HTTP ping göndererek Streamlit Cloud'un uykuya geçmesini engeller.
* **Bağımlılıklar:** `requirements.txt` sadeleştirildi (TensorFlow/Torch kaldırıldı, hafif veri bilimi paketleri ve `st-gsheets-connection` tutuldu).

### 📑 Mevcut 9 Dashboard Modülü (`web/pages/`):
1. **`0_ana_sayfa.py` (Varsayılan Mobil Ana Sayfa):**  
   VIX hapı, hızlı arama kutusu + hap butonlar, Midas portföy kartları (canlı fiyat, günlük % değişim, karar rozeti), Bugünün Fırsatları (AL Adayları), Haftalık Model Nabzı özeti.
2. **`1_piyasa_tarayici.py`:**  
   100+ kurumsal ABD hissesini 4-sütun faktör skoruna göre filtreler ve tarar.
3. **`2_tek_hisse_analiz.py`:**  
   Tek hisse derinlemesine analiz. Canlı fiyat, SMA 20/50/200, RSI, 4 Sütun Radar (Kalite %35, Değer %20, Momentum %30, Risk %15), Uzman Değerlendirme & Aksiyon Kutusu (kademeli giriş, SL, TP seviyeleri). `0_ana_sayfa.py`'den gelen tıklamaları otomatik analiz eder.
4. **`3_sektor_radari.py`:**  
   Sektör rotasyon scatter grafiği, ETF performans tablosu, tematik yatırım sepetleri (Çip, AI Altyapı, Temiz Enerji vb.).
5. **`4_walkforward_lab.py`:**  
   Tarihsel getiri, Sharpe oranı ve walk-forward test laboratuvarı.
6. **`5_faktor_optimizasyonu.py`:**  
   Grid-search ile faktör ağırlıklarını optimize eden simülasyon.
7. **`6_shadow_test.py`:**  
   Canlı üretim modeli (**v3.1 Baseline**) ile yeni meydan okuyan (**Challenger m00**) modelinin kafa kafaya gölge yarışı.
8. **`7_performans.py`:**  
   Sinyal takip motoru ve kümülatif getiri eğrisi.
9. **`8_portfoy_defteri.py` (Yeni Eklenen Portföy & Stres Testi Merkezi):**  
   * **Açık Pozisyonlar & FIFO Lot Röntgeni:** Midas alımlarını lot bazında gösterir, ilk satılacak lotu vurgular.
   * **Yoğunlaşma & Stres Testi:** Portföyün S&P 500'e göre betası, hisseler arası korelasyon ısı haritası, 4 tarihsel kriz şok senaryosu (2022 Fed faiz şoku, resesyon, AI düzeltmesi vb.).
   * **Dolar & TL Kâr/Zarar:** Anlık USD/TRY kuru ile hem $ hem ₺ bazlı canlı kâr.
   * **Türkiye Vergi Taslağı:** TCMB kuru üzerinden Değer Artış Kazancı ve Yİ-ÜFE endeksleme matrah taslağı.
   * **Depolama:** Hem yerel `portfolio_transactions.json` hem de `st-gsheets-connection` üzerinden Google Sheets senkronizasyon altyapısı.

---

## 🗄️ 3. Kritik Veri Dosyaları & Konumları
* `trading_bot.db`: SQLite ana veritabanı (hisse sinyalleri, model tahminleri, geçmiş taramalar).
* `web/data/watchlist.json`: Kullanıcının takip listesi sembolleri.
* `web/data/portfolio_transactions.json`: Kullanıcının Midas alış/satış lot kayıtları.
* `web/data/last_update.json`: Shadow test son güncelleme özeti (Pazar geceleri yenilenir).
* `web/components/mobile.py`: Mobil önbellekli veri çekici (`get_cached_quotes`, `badge_info`, `get_top_opportunities`, `get_vix_status`).
* `web/components/portfolio_tracker.py`: FIFO lot eşleştirme ve vergi motoru.
* `web/components/stress_test.py`: Beta, korelasyon matrisi ve kriz şok simülasyon motoru.
* `web/components/auth.py`: Siber güvenlik ve kimlik doğrulama katmanı (NIST PBKDF2-SHA256, RFC 6238 TOTP 2FA, brute-force kalkanı, login gate).
* `web/components/security_shield.py`: Uygulama katmanı WAF & Siber Savunma Kalkanı (Rate limiter, anti-scraping bot filtresi, query sanitization, audit log).
* `web/scripts/haftalik_guncelle.py`: Windows Görev Zamanlayıcısı (Pazar 21:00) tarafından çalıştırılan model yarış betiği.

---

## 🕒 4. En Son Yapılan İşlemler (04-05 Ekim 2026)
1. **Mobil Uygulama Arayüzü:** Streamlit chrome'u gizlendi (`toolbarMode = "minimal"`), dokunmatik butonlar ve fintech tarzı kartlar entegre edildi.
2. **Çökme & Hata Kalkanları:** Yahoo Finance'ın bulut IP'lerinde boş veri döndürmesi durumunda oluşan çökmeler (`KeyError: '1 Ay (%)'`, `None` format hataları) tamamen giderildi. Önbellekleme (`st.cache_data`) yapıldı.
3. **Gerçek Portföy & FIFO Defteri Kuruldu:** Talha'nın Midas MU girişleri yüklendi, lot eritme ve TL kâr hesabı eklendi.
4. **Yoğunlaşma & Stres Testi Eklendi:** Portföy betası ve tarihsel şok testleri tamamlandı.
5. **Haftalık Model Nabzı:** Pazar gecesi 22:12'de otomatik çalıştı. Sonuç: **Baseline (v3.1) Lider**, VIX 15.31, Olgunlaşan Kohort 2/3.
6. **Siber Güvenlik Katmanı 1 (Kimlik & İki Adımlı Doğrulama - 2FA):**
   * NIST standardında tuzlanmış PBKDF2-SHA256 parola hashleme.
   * RFC 6238 TOTP standardında Google Authenticator / Microsoft Authenticator entegrasyonu (`pyotp` ve `qrcode`).
   * Dinamik QR kod üretimi ve gizli anahtar doğrulama.
   * İki aşamalı giriş kapısı (`render_login_gate`) ve Brute-Force kalkanı (5 hatalı denemede 5 dakika kilit).
   * Kullanıcı ve yönetici profilinden 2FA açma/kapama yönetimi.
7. **Siber Güvenlik Katmanı 3 (Uygulama İçi WAF & Tehdit Kalkanı):**
   * **Kayan Pencere Hız Sınırlayıcı (Rate Limiter):** Dakika başına 40 istek, 3 saniyede 10 istek (Burst koruması) ile Yahoo Finance kota tüketimini ve DoS saldırılarını engelleme.
   * **Anti-Scraping & Bot Savunması:** Kötü niyetli otomatik güvenlik tarayıcısı ve kazıyıcı (Scraper) imzalarını yakalayıp 403 Forbidden ile engelleme.
   * **Girdi Sanitizasyonu (Anti-SQLi & Anti-XSS):** URL parametrelerindeki enjeksiyon girişimlerini temizleme ve güvenliğe alma.
   * **Güvenlik Başlıkları:** X-Content-Type-Options, X-Frame-Options (Clickjacking önleme), Referrer-Policy enjeksiyonu.
   * **Güvenlik Denetim Günlüğü (Audit Log):** SQLite `security_audit_log` tablosunda tüm olayların kaydı ve Yönetici (Admin) canlı izleme widget'ı.
8. **Git Senkronizasyonu:** Kodlar hazırlandı.

---

## 🚀 5. Gelecek Yol Haritası & Masadaki Fikirler
1. **Siber Güvenlik Katmanı 2 (Sırada / Beklemede):** Model & Fikri Mülkiyet Koruması (FastAPI backend ile faktör formüllerini kapalı kutu yapma).
2. **Resmi Veri Sağlayıcı (İleride):** Yahoo Finance yerine Polygon.io / FMP API geçişi (Site yayına alınıp domain bağlandığında).
3. **Özel Domain & Cloudflare DNS WAF (İleride):** Özel domain satın alındığında tam kapsamlı Cloudflare Edge WAF ve SSL aktivasyonu.
4. **Telegram / Webhook Anlık Alarm Botu:** Ekrana bakmaya gerek kalmadan kritik destek temaslarında (örn: MU 50 SMA teması) cep telefonuna anlık bildirim düşmesi.
5. **Volatilite Bazlı Lot/Risk Boyutlandırma Hesaplayıcısı (Risk Parity Sizing):** Midas bütçesine ve stop-loss mesafesine göre tam kaç lot alınması gerektiğini söyleyen hesaplayıcı.
3. **Analist Revizyon Trendi (Earnings Revision Momentum):** Büyük bankaların son 30-90 gündeki EPS tahmin revizyonlarının takibi.
4. **Bilanço & Opsiyon Beklenti Merkezi:** Bilanço geri sayımı ve opsiyon piyasasının fiyatladığı beklenen oynaklık.

---

## 📌 6. Yeni Sohbetteki Ajana Notlar
* **İletişim:** Talha ile samimi, doğrudan konuya giren, net ve profesyonel Türkçe ile iletişim kur.
* **Terminal & Git:** Windows PowerShell kullanılıyor. Asla `cd` komutu önerme. GitHub Desktop açık olduğu için push/pull adımlarında kullanıcıyı GitHub Desktop üzerinden yönlendir.
* **Streamlit Cloud:** Yapılan web değişikliklerinde hafif kütüphaneler kullan, ağır paketlerden kaçın, `st.cache_data` ile kota/hız optimizasyonunu koru.
