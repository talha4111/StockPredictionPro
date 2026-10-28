import sqlite3
import logging
from datetime import datetime, timedelta
import math
from typing import Any, Optional, Dict, List

import asyncio
try:
    asyncio.get_event_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

try:
    from ib_insync import IB
except Exception:
    class IB:
        pass

try:
    from ibkr_bridge import (
        ibkr_baglan,
        bakiye_getir,
        piyasa_verisi_cek,
        sozlesme_dogrula,
        hesap_bilgisi_oku,
    )
except ImportError:
    # Mock bridge functions
    def piyasa_verisi_cek(ib, contract):
        return {'last': 100.0, 'bid': 99.9, 'ask': 100.1, 'mid': 100.0, 'spread_bps': 20.0}

try:
    from stock_trade_journal import StockTradeJournal
except ImportError:
    class StockTradeJournal:
        def islem_ac(self, *args, **kwargs): pass
        def islem_kapat(self, *args, **kwargs): pass
        def kismi_cikis(self, *args, **kwargs): pass
        def acik_islemler(self): return []

logger = logging.getLogger(__name__)

class StockPositionTracker:
    """
    Profesyonel US Hisse Senedi Pozisyon Takip ve Çıkış Sistemi.
    Interactive Brokers (IBKR) entegrasyonu ile açık pozisyonların yönetimini sağlar.
    """

    def __init__(self, ib: Any = None, journal: Any = None, db_path='trading_bot.db'):
        """
        ib: Aktif IBKR bağlantı nesnesi (Opsiyonel)
        journal: İşlem günlüğü örneği (Opsiyonel)
        db_path: SQLite veritabanı dosya yolu
        """
        self.ib = ib
        self.journal = journal
        self.db_path = db_path
        self._veritabani_kur()

    def _baglanti_al(self):
        """Thread-safe SQLite bağlantısı döndürür."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _veritabani_kur(self):
        """Tabloları oluşturur."""
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_open_positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sembol TEXT UNIQUE NOT NULL,
                    yon TEXT NOT NULL,
                    giris_fiyati REAL NOT NULL,
                    miktar_baslangic INTEGER NOT NULL,
                    miktar_kalan INTEGER NOT NULL,
                    tp_fiyat REAL,
                    sl_fiyat REAL,
                    mevcut_stop REAL,
                    atr_giris REAL,
                    ai_skoru REAL,
                    faktor_skoru REAL,
                    setup_tipi TEXT,
                    sektor TEXT,
                    giris_zamani TEXT NOT NULL,
                    peak_fiyat REAL,
                    peak_pnl_yuzde REAL,
                    scale_out_yapildi INTEGER DEFAULT 0,
                    break_even_aktif INTEGER DEFAULT 0,
                    trailing_aktif INTEGER DEFAULT 0,
                    ibkr_order_id TEXT,
                    son_guncelleme TEXT
                )
                ''')
                cursor.execute('''
                CREATE TABLE IF NOT EXISTS stock_cooldowns (
                    sembol TEXT PRIMARY KEY,
                    cikis_zamani TEXT NOT NULL,
                    cooldown_bitis TEXT NOT NULL
                )
                ''')
                conn.commit()
            logger.info("Pozisyon takip veritabanı başarıyla kuruldu.")
        except Exception as e:
            logger.error(f"Veritabanı kurulum hatası: {e}")

    def pozisyon_ekle(self, sembol, yon, giris_fiyati, miktar, tp_fiyat, sl_fiyat,
                      atr_giris, ai_skoru, faktor_skoru, setup_tipi, sektor) -> None:
        """Yeni bir pozisyonu veritabanına kaydeder."""
        try:
            simdi = datetime.now().isoformat()
            
            # İlk stop-loss kuralı kontrolü
            if not sl_fiyat:
                if yon == 'LONG':
                    sl_fiyat = giris_fiyati - (atr_giris * 1.5)
                else:
                    sl_fiyat = giris_fiyati + (atr_giris * 1.5)
            
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute('''
                INSERT INTO stock_open_positions (
                    sembol, yon, giris_fiyati, miktar_baslangic, miktar_kalan,
                    tp_fiyat, sl_fiyat, mevcut_stop, atr_giris, ai_skoru, faktor_skoru,
                    setup_tipi, sektor, giris_zamani, peak_fiyat, peak_pnl_yuzde, son_guncelleme
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    sembol, yon, giris_fiyati, miktar, miktar,
                    tp_fiyat, sl_fiyat, sl_fiyat, atr_giris, ai_skoru, faktor_skoru,
                    setup_tipi, sektor, simdi, giris_fiyati, 0.0, simdi
                ))
                conn.commit()
            logger.info(f"Yeni pozisyon eklendi: {sembol} | {yon} | Giriş: {giris_fiyati} | Miktar: {miktar}")
        except Exception as e:
            logger.error(f"{sembol} için pozisyon eklenirken hata: {e}")

    def pozisyonlari_senkronize_et(self) -> list:
        """IBKR'dan mevcut açık pozisyonları okur ve yerel durum ile senkronize eder."""
        logger.info("Pozisyonlar IBKR ile senkronize ediliyor...")
        # Gerçekte hesap_bilgisi_oku vb. ile çekilir.
        return []

    def pozisyon_guncelle(self, sembol: str, guncel_fiyat: float, 
                          guncel_high: float = None, guncel_low: float = None) -> dict:
        """
        Pozisyon durumunu günceller ve çıkış kurallarını kontrol eder.
        Dönüş: {eylem: 'BEKLE'|'KISMI_CIKIS'|'TAM_CIKIS', sebep: str, miktar: int}
        """
        eylem = {'eylem': 'BEKLE', 'sebep': '', 'miktar': 0, 'fiyat': guncel_fiyat}
        
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM stock_open_positions WHERE sembol = ?", (sembol,))
                row = cursor.fetchone()
                
                if not row:
                    logger.warning(f"Pozisyon bulunamadı: {sembol}")
                    return eylem
                
                yon = row['yon']
                giris_fiyati = row['giris_fiyati']
                miktar_kalan = row['miktar_kalan']
                miktar_baslangic = row['miktar_baslangic']
                mevcut_stop = row['mevcut_stop']
                tp_fiyat = row['tp_fiyat']
                peak_fiyat = row['peak_fiyat']
                peak_pnl_yuzde = row['peak_pnl_yuzde']
                atr_giris = row['atr_giris']
                giris_zamani_str = row['giris_zamani']
                scale_out_yapildi = row['scale_out_yapildi']
                break_even_aktif = row['break_even_aktif']
                
                # PnL Hesaplama
                if yon == 'LONG':
                    anlik_pnl = ((guncel_fiyat - giris_fiyati) / giris_fiyati) * 100
                else:
                    anlik_pnl = ((giris_fiyati - guncel_fiyat) / giris_fiyati) * 100
                
                # Peak Fiyat ve Peak PnL Güncelleme
                yeni_peak_fiyat = peak_fiyat
                if yon == 'LONG' and guncel_fiyat > peak_fiyat:
                    yeni_peak_fiyat = guncel_fiyat
                elif yon == 'SHORT' and guncel_fiyat < peak_fiyat:
                    yeni_peak_fiyat = guncel_fiyat
                    
                yeni_peak_pnl = max(peak_pnl_yuzde, anlik_pnl)
                
                # Kural 1: Stop-Loss Kontrolü
                if yon == 'LONG' and guncel_fiyat <= mevcut_stop:
                    eylem = {'eylem': 'TAM_CIKIS', 'sebep': 'STOP_LOSS', 'miktar': miktar_kalan, 'fiyat': guncel_fiyat}
                    self._pozisyon_kapat(sembol, eylem['sebep'])
                    return eylem
                elif yon == 'SHORT' and guncel_fiyat >= mevcut_stop:
                    eylem = {'eylem': 'TAM_CIKIS', 'sebep': 'STOP_LOSS', 'miktar': miktar_kalan, 'fiyat': guncel_fiyat}
                    self._pozisyon_kapat(sembol, eylem['sebep'])
                    return eylem
                
                # Kural 5: Take Profit Kontrolü
                if tp_fiyat:
                    if (yon == 'LONG' and guncel_fiyat >= tp_fiyat) or \
                       (yon == 'SHORT' and guncel_fiyat <= tp_fiyat) or anlik_pnl >= 15.0:
                        eylem = {'eylem': 'TAM_CIKIS', 'sebep': 'TP_HIT', 'miktar': miktar_kalan, 'fiyat': guncel_fiyat}
                        self._pozisyon_kapat(sembol, eylem['sebep'])
                        return eylem

                # Kural 2: Scale-Out (Kısmi Çıkış) %8 Kar
                if not scale_out_yapildi and anlik_pnl >= 8.0:
                    cikis_miktari = max(1, miktar_kalan // 2)
                    eylem = {'eylem': 'KISMI_CIKIS', 'sebep': 'SCALE_OUT_8PCT', 'miktar': cikis_miktari, 'fiyat': guncel_fiyat}
                    scale_out_yapildi = 1
                    miktar_kalan -= cikis_miktari
                    
                # Kural 3: Break-Even Stop
                if not break_even_aktif and (scale_out_yapildi or yeni_peak_pnl >= 5.0):
                    if yon == 'LONG':
                        mevcut_stop = giris_fiyati * 1.001
                    else:
                        mevcut_stop = giris_fiyati * 0.999
                    break_even_aktif = 1
                    logger.info(f"{sembol} için Break-Even Stop aktifleştirildi: {mevcut_stop}")

                # Kural 4: Trailing Stop
                if break_even_aktif:
                    if yon == 'LONG':
                        yeni_trailing = yeni_peak_fiyat - (atr_giris * 2.0)
                        if yeni_trailing > mevcut_stop:
                            mevcut_stop = yeni_trailing
                    else:
                        yeni_trailing = yeni_peak_fiyat + (atr_giris * 2.0)
                        if yeni_trailing < mevcut_stop:
                            mevcut_stop = yeni_trailing

                # Kural 6: Zaman Bazlı Çıkış
                giris_zamani = datetime.fromisoformat(giris_zamani_str)
                gecen_gun = (datetime.now() - giris_zamani).days
                if gecen_gun >= 28: # Yaklaşık 20 işlem günü = 28 takvim günü
                    if -2.0 <= anlik_pnl <= 3.0:
                        eylem = {'eylem': 'TAM_CIKIS', 'sebep': 'TIME_EXIT', 'miktar': miktar_kalan, 'fiyat': guncel_fiyat}
                        self._pozisyon_kapat(sembol, eylem['sebep'])
                        return eylem
                
                # Güncellemeleri veritabanına yaz
                cursor.execute('''
                UPDATE stock_open_positions SET 
                    miktar_kalan = ?, mevcut_stop = ?, peak_fiyat = ?, peak_pnl_yuzde = ?,
                    scale_out_yapildi = ?, break_even_aktif = ?, son_guncelleme = ?
                WHERE sembol = ?
                ''', (miktar_kalan, mevcut_stop, yeni_peak_fiyat, yeni_peak_pnl, 
                      scale_out_yapildi, break_even_aktif, datetime.now().isoformat(), sembol))
                conn.commit()
                
        except Exception as e:
            logger.error(f"{sembol} için pozisyon güncellenirken hata: {e}")
            
        return eylem

    def _pozisyon_kapat(self, sembol: str, sebep: str):
        """Pozisyonu veritabanından siler ve cooldown ekler."""
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM stock_open_positions WHERE sembol = ?", (sembol,))
                
                # 5 işlem günü (yaklaşık 7 takvim günü) cooldown
                simdi = datetime.now()
                cooldown_bitis = simdi + timedelta(days=7)
                
                cursor.execute('''
                INSERT OR REPLACE INTO stock_cooldowns (sembol, cikis_zamani, cooldown_bitis)
                VALUES (?, ?, ?)
                ''', (sembol, simdi.isoformat(), cooldown_bitis.isoformat()))
                conn.commit()
            logger.info(f"{sembol} pozisyonu kapatıldı. Sebep: {sebep}. Cooldown süresi eklendi.")
        except Exception as e:
            logger.error(f"{sembol} pozisyonu kapatılırken hata: {e}")

    def tum_pozisyonlari_kontrol_et(self) -> list:
        """
        Tüm açık pozisyonları döner, IBKR üzerinden anlık fiyatları alır,
        çıkış kurallarını kontrol eder ve alınacak aksiyonların listesini döner.
        """
        aksiyonlar = []
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT sembol FROM stock_open_positions")
                semboller = [row['sembol'] for row in cursor.fetchall()]
                
            for sembol in semboller:
                # Gerçek sistemde piyasa_verisi_cek(self.ib, Contract) kullanılır.
                # Burada örnek olması amacıyla dummy bir çağrı.
                try:
                    fiyat_verisi = piyasa_verisi_cek(self.ib, None)
                    guncel_fiyat = fiyat_verisi['last']
                    eylem = self.pozisyon_guncelle(sembol, guncel_fiyat)
                    
                    if eylem['eylem'] != 'BEKLE':
                        eylem['sembol'] = sembol
                        aksiyonlar.append(eylem)
                        
                        # Günlüğe yazma işlemleri
                        if eylem['eylem'] == 'TAM_CIKIS':
                            self.journal.islem_kapat(sembol, eylem['fiyat'], eylem['sebep'])
                        elif eylem['eylem'] == 'KISMI_CIKIS':
                            # %50'si çıkıldı varsayılıyor, journal_kismi_cikis için uygun oran gönderilir
                            self.journal.kismi_cikis(sembol, eylem['fiyat'], 50.0, eylem['sebep'])
                            
                except Exception as ex:
                    logger.error(f"{sembol} için piyasa verisi çekilirken/kontrol edilirken hata: {ex}")
                    continue
                    
        except Exception as e:
            logger.error(f"Tüm pozisyonlar kontrol edilirken hata: {e}")
            
        return aksiyonlar

    def cooldown_kontrol(self, sembol: str) -> bool:
        """Sembolün cooldown süresinde olup olmadığını kontrol eder."""
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT cooldown_bitis FROM stock_cooldowns WHERE sembol = ?", (sembol,))
                row = cursor.fetchone()
                
                if row:
                    bitis_zamani = datetime.fromisoformat(row['cooldown_bitis'])
                    if datetime.now() < bitis_zamani:
                        return True
                    else:
                        cursor.execute("DELETE FROM stock_cooldowns WHERE sembol = ?", (sembol,))
                        conn.commit()
                        return False
        except Exception as e:
            logger.error(f"Cooldown kontrolü hatası ({sembol}): {e}")
        return False

    def acik_pozisyon_sayisi(self) -> int:
        """Güncel açık pozisyon sayısını döner."""
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as sayi FROM stock_open_positions")
                return cursor.fetchone()['sayi']
        except Exception as e:
            logger.error(f"Açık pozisyon sayısı sorgulanırken hata: {e}")
            return 0

    def sektor_yogunlugu(self, sektor: str) -> int:
        """Belirtilen sektördeki açık pozisyon sayısını döner."""
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as sayi FROM stock_open_positions WHERE sektor = ?", (sektor,))
                return cursor.fetchone()['sayi']
        except Exception as e:
            logger.error(f"Sektör yoğunluğu sorgulanırken hata: {e}")
            return 0

    def portfoy_ozeti(self) -> dict:
        """Portföyün genel özetini döner."""
        ozet = {
            'pozisyon_sayisi': 0,
            'toplam_pnl_yuzde': 0.0,
            'sektor_dagilimi': {},
            'pozisyonlar': []
        }
        try:
            with self._baglanti_al() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM stock_open_positions")
                rows = cursor.fetchall()
                
                ozet['pozisyon_sayisi'] = len(rows)
                toplam_pnl = 0.0
                
                for row in rows:
                    poz_bilgi = dict(row)
                    ozet['pozisyonlar'].append(poz_bilgi)
                    
                    # Sektör dağılımı hesaplama
                    sektor = poz_bilgi['sektor']
                    ozet['sektor_dagilimi'][sektor] = ozet['sektor_dagilimi'].get(sektor, 0) + 1
                    
                    # PnL toplam
                    toplam_pnl += poz_bilgi['peak_pnl_yuzde']
                    
                if ozet['pozisyon_sayisi'] > 0:
                    ozet['toplam_pnl_yuzde'] = toplam_pnl / ozet['pozisyon_sayisi']
                    
        except Exception as e:
            logger.error(f"Portföy özeti oluşturulurken hata: {e}")
            
        return ozet

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    
    # Mock sistem başlat
    tracker = StockPositionTracker(ib=IB(), journal=StockTradeJournal(), db_path='test_trading_bot.db')
    
    # Test 1: Pozisyon Ekle
    logger.info("TEST: Pozisyon ekleniyor (AAPL, LONG)")
    tracker.pozisyon_ekle(
        sembol='AAPL', yon='LONG', giris_fiyati=150.0, miktar=100, 
        tp_fiyat=180.0, sl_fiyat=140.0, atr_giris=3.0, 
        ai_skoru=0.85, faktor_skoru=0.9, setup_tipi='BREAKOUT', sektor='Technology'
    )
    
    # Test 2: Pozisyon Güncelle (Fiyat Artışı, Trailing / Peak güncellemesi)
    logger.info("TEST: Fiyat 155.0'a çıkıyor...")
    aksiyon = tracker.pozisyon_guncelle('AAPL', guncel_fiyat=155.0)
    logger.info(f"Aksiyon: {aksiyon}")
    
    # Test 3: Kısmi Çıkış (%8 kar kontrolü) - 150 -> 162.0 = %8 kar
    logger.info("TEST: Fiyat 162.0'a çıkıyor... (Scale-Out bekleniyor)")
    aksiyon = tracker.pozisyon_guncelle('AAPL', guncel_fiyat=162.0)
    logger.info(f"Aksiyon: {aksiyon}")
    
    # Test 4: Açık Pozisyon Sayısı ve Özet
    logger.info(f"Açık Pozisyon Sayısı: {tracker.acik_pozisyon_sayisi()}")
    logger.info(f"Sektör Yoğunluğu (Technology): {tracker.sektor_yogunlugu('Technology')}")
    logger.info(f"Portföy Özeti: {tracker.portfoy_ozeti()}")
    
    # Test 5: Zaman Bazlı Çıkış (Eski pozisyon testi için veritabanında tarihi değiştirelim)
    with tracker._baglanti_al() as conn:
        eski_zaman = (datetime.now() - timedelta(days=30)).isoformat()
        conn.execute("UPDATE stock_open_positions SET giris_zamani = ? WHERE sembol = 'AAPL'", (eski_zaman,))
        conn.commit()
        
    logger.info("TEST: 30 gün geçmiş pozisyonda fiyat 151.0'e dönüyor (Time-based exit bekleniyor)")
    aksiyon = tracker.pozisyon_guncelle('AAPL', guncel_fiyat=151.0)
    logger.info(f"Aksiyon: {aksiyon}")
    
    # Test 6: Cooldown Kontrolü
    logger.info(f"Cooldown aktif mi? {tracker.cooldown_kontrol('AAPL')}")
