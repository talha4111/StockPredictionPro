"""
STOCK ENGINE V9 — Otonom İnfaz ve Karar Motoru (Tam IBKR Entegrasyonu)
========================================================================
Görev: ibkr_bridge.py, stock_signal_router.py, stock_position_tracker.py, 
stock_trade_journal.py ve ai_core.py bileşenlerini orkestre ederek tam otonom işlem yapmak.
Market hours farkındalığı, risk parity pozisyon boyutlandırma, VIX filtresi ve AI+Faktör kombinasyonu içerir.
"""

import sys
import io
import asyncio
import logging
import time
from datetime import datetime, timedelta
import pytz
import pandas as pd
try:
    import pandas_ta as ta
except ImportError:
    class ta:
        @staticmethod
        def atr(high, low, close, length=14):
            tr = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low - close.shift()).abs()
            ], axis=1).max(axis=1)
            return tr.rolling(length).mean()
import yfinance as yf

# Windows CMD Unicode Hatası Önleyici
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

# Loglama ayarları
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
logger = logging.getLogger(__name__)

# Gerekli importlar (Mevcut yapıdan)
from ibkr_bridge import (
    ibkr_baglan, bakiye_getir, toplu_veri_cek,
    gecmis_veri_cek, bracket_emri_gonder, sozlesme_dogrula,
    piyasa_verisi_cek, hesap_bilgisi_oku, net_rr_filtresi,
    islem_maliyeti_hesapla
)
from stock_signal_router import StockSignalRouter
from stock_position_tracker import StockPositionTracker
from stock_trade_journal import StockTradeJournal
from ai_core import BeyinMotoru

# ============================================================
#  SİSTEM KONFİGÜRASYONU
# ============================================================
MAX_ESANLI_POZISYON = 5          # Maksimum eşzamanlı açık pozisyon
MAX_SEKTOR_YOGUNLUK = 2          # Tek sektörde max pozisyon
RISK_PER_TRADE_PCT = 0.015       # Trade başına risk: portföyün %1.5'i
MIN_POZISYON_DEGERI = 500        # Minimum pozisyon büyüklüğü ($)
MAX_POZISYON_ORANI = 0.20        # Tek pozisyon max portföy oranı
PORTFOY_ISI_SINIRI = 0.80        # Portföy ısısı üst sınır
GUNLUK_KAYIP_SINIRI = 0.03       # Günlük max kayıp: %3
AI_GUVEN_ESIGI = 0.58            # XGBoost minimum güven skoru
FAKTOR_SKOR_ESIGI = 65.0         # Minimum faktör skoru
VIX_DIKKAT_ESIGI = 30            # VIX uyarı seviyesi
VIX_DURDUR_ESIGI = 35            # VIX durma seviyesi  
TARAMA_ARALIK_DAKIKA = 5         # Tarama döngü aralığı
IBKR_HOST = '127.0.0.1'
IBKR_PORT = 7497                 # Paper Trading
IBKR_CLIENT_ID = 1


# ============================================================
#  YARDIMCI FONKSİYONLAR
# ============================================================

def piyasa_durumu_al():
    """
    US Eastern Time'a (New York) göre mevcut piyasa durumunu döner.
    NYSE: 09:30 - 16:00 arası açık.
    09:15 - 09:30 arası pre-market.
    Hafta sonu kapalı.
    """
    et_tz = pytz.timezone('US/Eastern')
    now = datetime.now(et_tz)
    
    if now.weekday() >= 5:  # 5=Cumartesi, 6=Pazar
        return False, "HAFTA SONU"
        
    market_open = now.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now.replace(hour=16, minute=0, second=0, microsecond=0)
    pre_market = now.replace(hour=9, minute=15, second=0, microsecond=0)
    
    if now < pre_market:
        return False, "KAPALI (Pre-market bekleniyor)"
    elif pre_market <= now < market_open:
        return False, "PRE-MARKET (Hazırlık, Pozisyonlar senkronize edilecek)"
    elif market_open <= now < market_close:
        return True, "AÇIK"
    else:
        return False, "KAPALI (Piyasa kapandı)"

def guncel_vix_al():
    """VIX endeks değerini yfinance üzerinden alır."""
    try:
        vix = yf.Ticker('^VIX').history(period='1d')
        if not vix.empty:
            return float(vix['Close'].iloc[-1])
    except Exception as e:
        logger.warning(f"VIX çekilemedi: {e}")
    return 20.0 # Hata durumunda nötr bir değer dön


# ============================================================
#  ANA MOTOR DÖNGÜSÜ
# ============================================================

def motor_baslat():
    logger.info("============================================")
    logger.info("   STOCK ENGINE V9 | OTONOM İNFAZ MOTORU")
    logger.info("============================================")

    # Bileşenleri başlat
    ib = ibkr_baglan(host=IBKR_HOST, port=IBKR_PORT, client_id=IBKR_CLIENT_ID)
    if not ib:
        logger.critical("🚨 IBKR TWS Bağlantısı kurulamadı. Sistem kapatılıyor.")
        return

    beyin = BeyinMotoru()
    journal = StockTradeJournal()
    router = StockSignalRouter()
    tracker = StockPositionTracker(ib=ib, journal=journal)
    
    # Döngü istatistikleri
    son_tarama_zamani = None
    gunluk_baslangic_bakiyesi = None

    try:
        while True:
            # 1. Market saatleri kontrolü
            piyasa_acik, durum = piyasa_durumu_al()
            logger.info(f"🕒 Piyasa Durumu: {durum}")
            
            if "HAFTA SONU" in durum or "KAPALI" in durum:
                logger.info("💤 Piyasa kapalı, 15 dakika uyutuluyor...")
                ib.sleep(60 * 15)
                continue
                
            # Pre-market veya açık durumda IBKR verilerini senkronize et
            bakiye = bakiye_getir(ib)
            if bakiye <= 0:
                logger.error("🚨 Kasa bilgisi okunamadı. 1 Dakika bekleniyor...")
                ib.sleep(60)
                continue
                
            if gunluk_baslangic_bakiyesi is None:
                gunluk_baslangic_bakiyesi = bakiye

            # Pozisyonları IBKR ile Senkronize Et ve Çıkış Kurallarını İşlet
            try:
                # 2. Açık pozisyonların çıkış kurallarını (Trailing, Scale-Out, BE, SL/TP) denetle
                tracker.tum_pozisyonlari_kontrol_et()
            except Exception as e:
                logger.error(f"Tracker güncellenirken hata oluştu: {e}")

            # Pozisyonları IBKR'den oku ve ısıyı güncelle
            hesap_ozeti = hesap_bilgisi_oku(ib)
            acik_pozisyonlar = hesap_ozeti.get('pozisyonlar', []) if hesap_ozeti else []
            
            kullanilan_margin = sum(abs(p.position * p.avgCost) for p in acik_pozisyonlar)
            toplam_kasa = bakiye + kullanilan_margin
            isi_yuzdesi = kullanilan_margin / toplam_kasa if toplam_kasa > 0 else 0
            
            logger.info(f"💰 Kasa: ${bakiye:,.2f} | 📊 Margin: ${kullanilan_margin:,.2f} | 🔥 Isı: %{isi_yuzdesi*100:.1f}")
            
            # Günlük Kayıp Sınırı Kontrolü
            gunluk_pnl = toplam_kasa - gunluk_baslangic_bakiyesi
            gunluk_kayip_yuzdesi = abs(min(0, gunluk_pnl)) / gunluk_baslangic_bakiyesi if gunluk_baslangic_bakiyesi else 0
            
            if gunluk_kayip_yuzdesi > GUNLUK_KAYIP_SINIRI:
                logger.warning(f"🛑 GÜNLÜK KAYIP SINIRI AŞILDI! (Kayıp: %{gunluk_kayip_yuzdesi*100:.2f}). Yeni işlem açılmayacak.")
                ib.sleep(60 * 15)
                continue

            # Sadece piyasa açıksa işlem araması ve çıkış kuralları çalışır
            if not piyasa_acik:
                ib.sleep(60 * 5)
                continue
                
            logger.info("\n--- [V9] YENİ OTONOM TARAMA DÖNGÜSÜ ---")
            
            # 2. VIX Kontrolü
            vix_seviyesi = guncel_vix_al()
            logger.info(f"📈 VIX Seviyesi: {vix_seviyesi:.2f}")
            
            if vix_seviyesi > VIX_DURDUR_ESIGI:
                logger.warning("🚨 VIX ÇOK YÜKSEK! Piyasa aşırı volatil. Yeni işlem açılmayacak.")
                ib.sleep(60 * TARAMA_ARALIK_DAKIKA)
                continue
                
            vix_carpani = 0.5 if vix_seviyesi > VIX_DIKKAT_ESIGI else 1.0
            if vix_carpani < 1.0:
                logger.warning("⚠️ VIX UYARI SEVİYESİNDE. Pozisyon büyüklükleri yarıya düşürüldü.")
                
            # 3. Portföy Isısı Kontrolü
            if isi_yuzdesi >= PORTFOY_ISI_SINIRI:
                logger.warning("🔥 PORTFÖY ISISI LİMİTTE! Yeni işlem açılmayacak.")
                ib.sleep(60 * TARAMA_ARALIK_DAKIKA)
                continue
                
            # 4. Açık pozisyon sayısını ve sektör yoğunluğunu hesapla
            aktif_semboller = [p.contract.symbol for p in acik_pozisyonlar if p.position != 0]
            aktif_pozisyon_sayisi = len(aktif_semboller)
            
            if aktif_pozisyon_sayisi >= MAX_ESANLI_POZISYON:
                logger.info("🔒 Maksimum açık pozisyon sınırına ulaşıldı. Bekleniyor...")
                ib.sleep(60 * TARAMA_ARALIK_DAKIKA)
                continue
                
            # 5. Sinyal Yönlendirici'den Adayları Al
            try:
                adaylar = router.aday_listesi_getir()
            except AttributeError:
                logger.warning("StockSignalRouter.aday_listesi_getir() metodu bulunamadı.")
                adaylar = []
                
            if not adaylar:
                logger.info("📭 Uygun işlem adayı bulunamadı.")
                ib.sleep(60 * TARAMA_ARALIK_DAKIKA)
                continue
                
            logger.info(f"🎯 Sinyal Yönlendirici'den {len(adaylar)} aday alındı.")
            
            sektor_haritasi = {}
            taranacak_adaylar = [a for a in adaylar if a['sembol'] not in aktif_semboller][:15]
            sembol_listesi = [a['sembol'] for a in taranacak_adaylar]
            
            if not sembol_listesi:
                logger.info("Tüm adaylarda zaten pozisyonumuz var.")
                ib.sleep(60 * TARAMA_ARALIK_DAKIKA)
                continue

            logger.info(f"⚡ Canlı veri çekiliyor: {sembol_listesi}")
            anlik_veriler = toplu_veri_cek(ib, sembol_listesi, bekleme_sn=3)
            
            # 6. Adayları Değerlendir ve İnfaz Et
            for aday in taranacak_adaylar:
                sembol = aday['sembol']
                sektor = aday.get('sektor', 'Genel')
                faktor_skoru = aday.get('faktor_skoru', 0.0)
                sinyal_yonu = aday.get('yon', 'BUY').upper()
                
                # Cooldown kontrolü
                if tracker.cooldown_kontrol(sembol):
                    logger.info(f"[{sembol}] ⏳ Cooldown süresinde. Pas geçiliyor.")
                    continue
                    
                # Sektör kontrolü
                if sektor_haritasi.get(sektor, 0) >= MAX_SEKTOR_YOGUNLUK:
                    logger.info(f"[{sembol}] {sektor} sektörü dolu. Pas geçiliyor.")
                    continue
                    
                # Faktör Skoru Kontrolü
                if faktor_skoru < FAKTOR_SKOR_ESIGI:
                    logger.info(f"[{sembol}] Faktör skoru yetersiz ({faktor_skoru} < {FAKTOR_SKOR_ESIGI}).")
                    continue
                
                veri = anlik_veriler.get(sembol)
                anlik_fiyat = None
                if veri:
                    anlik_fiyat = veri.get('mid') or veri.get('last')
                    if not anlik_fiyat and veri.get('ask') and veri.get('bid'):
                        anlik_fiyat = (veri['ask'] + veri['bid']) / 2.0
                        
                if not anlik_fiyat or anlik_fiyat <= 0:
                    try:
                        ticker_yf = yf.Ticker(sembol).history(period='1d')
                        if not ticker_yf.empty:
                            anlik_fiyat = float(ticker_yf['Close'].iloc[-1])
                    except:
                        pass
                        
                if not anlik_fiyat or anlik_fiyat <= 0:
                    logger.warning(f"[{sembol}] Canlı fiyat okunamadı.")
                    continue
                    
                bid_fiyat = (veri.get('bid') if veri else None) or round(anlik_fiyat * 0.9995, 2)
                ask_fiyat = (veri.get('ask') if veri else None) or round(anlik_fiyat * 1.0005, 2)
                
                # Geçmiş veriyi çek ve XGBoost (AI) ile skorla
                contract = sozlesme_dogrula(ib, sembol)
                if not contract:
                    continue
                    
                df = gecmis_veri_cek(ib, contract, bar_boyutu='15 mins', sure='5 D', pipeline_uygula=True)
                if df is None or df.empty:
                    logger.warning(f"[{sembol}] AI için yeterli geçmiş veri alınamadı.")
                    continue
                    
                ai_skoru = beyin.tahmin_et(sembol, df, is_crypto=False)
                logger.info(f"[{sembol}] 🧠 AI Skoru: {ai_skoru:.3f} | 🔬 Faktör Skoru: {faktor_skoru:.1f}")
                
                # AI + Faktör Çatışma Kontrolü
                ai_yon = 'BUY' if ai_skoru > 0.52 else ('SELL' if ai_skoru < 0.48 else 'NEUTRAL')
                
                if ai_yon == 'NEUTRAL':
                    logger.info(f"[{sembol}] AI skoru nötr bölgede. Pas geçiliyor.")
                    continue
                    
                if ai_yon != sinyal_yonu and sinyal_yonu != 'NEUTRAL':
                    logger.info(f"[{sembol}] ❌ Çatışma: AI {ai_yon} diyor, Sinyal {sinyal_yonu} diyor. Pas geçiliyor.")
                    continue
                
                # AI Güven Eşiği Kontrolü
                ai_guven_uygun = (ai_yon == 'BUY' and ai_skoru >= AI_GUVEN_ESIGI) or \
                                 (ai_yon == 'SELL' and (1 - ai_skoru) >= AI_GUVEN_ESIGI)
                                 
                if not ai_guven_uygun:
                    logger.info(f"[{sembol}] AI güven eşiğini geçemedi.")
                    continue
                    
                # 7. Risk Parity Pozisyon Boyutlandırma
                atr_df = ta.atr(df['High'], df['Low'], df['Close'], length=14)
                atr = float(atr_df.iloc[-1]) if (atr_df is not None and not atr_df.empty and not pd.isna(atr_df.iloc[-1])) else (anlik_fiyat * 0.02)
                
                risk_miktari = toplam_kasa * RISK_PER_TRADE_PCT * vix_carpani
                sl_mesafesi = atr * 1.5
                miktar = int(risk_miktari / sl_mesafesi)
                islem_butcesi = miktar * anlik_fiyat
                
                if islem_butcesi < MIN_POZISYON_DEGERI:
                    logger.warning(f"[{sembol}] İşlem bütçesi (${islem_butcesi:.2f}) minimumun (${MIN_POZISYON_DEGERI}) altında.")
                    continue
                    
                if islem_butcesi > (toplam_kasa * MAX_POZISYON_ORANI):
                    miktar = int((toplam_kasa * MAX_POZISYON_ORANI) / anlik_fiyat)
                    
                if miktar < 1:
                    continue
                    
                # 8. TP ve SL Belirleme
                if ai_yon == 'BUY':
                    giris_fiyati = ask_fiyat
                    tp_fiyat = round(giris_fiyati + (atr * 2.5), 2)
                    sl_fiyat = round(giris_fiyati - (atr * 1.5), 2)
                else:
                    giris_fiyati = bid_fiyat
                    tp_fiyat = round(giris_fiyati - (atr * 2.5), 2)
                    sl_fiyat = round(giris_fiyati + (atr * 1.5), 2)
                    
                # 9. Net RR Filtresi
                rr_kontrol = net_rr_filtresi(
                    fiyat=giris_fiyati, tp_fiyat=tp_fiyat, sl_fiyat=sl_fiyat, 
                    miktar=miktar, spread_bps=veri.get('spread_bps'), yon=ai_yon
                )
                
                if rr_kontrol.get('karar') == 'RED':
                    logger.info(f"[{sembol}] ❌ Net RR Filtresine Takıldı: {rr_kontrol.get('red_sebebi')}")
                    continue
                    
                logger.info(f"[{sembol}] ✅ İNFAZ ONAYI: {ai_yon} | Miktar: {miktar} | Fiyat: ~${giris_fiyati:.2f}")
                logger.info(f"         TP: ${tp_fiyat:.2f} | SL: ${sl_fiyat:.2f} | Risk: ${risk_miktari:.2f}")
                
                # İnfaz (Bracket Order)
                basarili = bracket_emri_gonder(ib, sembol, ai_yon, miktar, tp_fiyat, sl_fiyat)
                
                if basarili:
                    logger.info(f"🚀 [{sembol}] İşlem Başarıyla Borsaya İletildi!")
                    aktif_semboller.append(sembol)
                    aktif_pozisyon_sayisi += 1
                    sektor_haritasi[sektor] = sektor_haritasi.get(sektor, 0) + 1
                    
                    journal.islem_ac(
                        sembol=sembol, yon=ai_yon, giris_fiyati=giris_fiyati, miktar=miktar,
                        margin_used=(miktar * giris_fiyati), ai_score=ai_skoru, factor_score=faktor_skoru,
                        setup_type="AI+Factor Trend", sector=sektor, atr_at_entry=atr,
                        tp_price=tp_fiyat, sl_price=sl_fiyat
                    )
                    
                    tracker.pozisyon_ekle(
                        sembol=sembol, yon=ai_yon, giris_fiyati=giris_fiyati, miktar=miktar,
                        tp_fiyat=tp_fiyat, sl_fiyat=sl_fiyat, atr_giris=atr,
                        ai_skoru=ai_skoru, faktor_skoru=faktor_skoru,
                        setup_tipi="AI+Factor Trend", sektor=sektor
                    )
                    
                    if aktif_pozisyon_sayisi >= MAX_ESANLI_POZISYON:
                        logger.info("🔒 Maksimum açık pozisyona ulaşıldı, tarama durduruluyor.")
                        break

            # Döngü sonu raporlama
            logger.info("\n--- [V9] PORTFÖY ÖZETİ ---")
            logger.info(f"Kasa: ${bakiye:,.2f} | Kullanılan Margin: ${kullanilan_margin:,.2f} | Toplam Kasa: ${toplam_kasa:,.2f}")
            logger.info(f"Portföy Isısı: %{isi_yuzdesi*100:.1f} | Günlük PnL: ${gunluk_pnl:,.2f} (%{gunluk_kayip_yuzdesi*-100:.2f})")
            logger.info(f"Açık Pozisyon Sayısı: {aktif_pozisyon_sayisi} / {MAX_ESANLI_POZISYON}")
            
            simdiki_zaman = time.time()
            if son_tarama_zamani is None or (simdiki_zaman - son_tarama_zamani) >= 3600:
                logger.info("\n--- [V9] SAATLİK PERFORMANS METRİKLERİ ---")
                try:
                    saatlik_ozet = journal.performans_ozeti(son_n_gun=7)
                    if "hata" not in saatlik_ozet:
                        logger.info(f"Son 7 Gün PnL: ${saatlik_ozet.get('total_pnl', 0):.2f} | Win Rate: %{saatlik_ozet.get('win_rate', 0):.1f}")
                        logger.info(f"Profit Factor: {saatlik_ozet.get('profit_factor', 0):.2f} | Kazançlı İşlemler: {saatlik_ozet.get('winners', 0)}")
                except Exception as e:
                    logger.warning(f"Performans özeti alınamadı: {e}")
                son_tarama_zamani = simdiki_zaman

            logger.info(f"⏱️ {TARAMA_ARALIK_DAKIKA} Dakika Bekleniyor...\n")
            ib.sleep(60 * TARAMA_ARALIK_DAKIKA)

    except KeyboardInterrupt:
        logger.info("Kaptan tarafından manuel olarak kapatıldı. (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Beklenmeyen MOTOR HATASI: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib and ib.isConnected():
            ib.disconnect()
            logger.info("🔌 IBKR bağlantısı güvenle sonlandırıldı.")

if __name__ == "__main__":
    motor_baslat()
