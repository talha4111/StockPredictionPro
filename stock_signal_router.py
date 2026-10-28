import sqlite3
import json
import logging
from datetime import datetime, timedelta

# Loglama ayarları
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('SignalRouter')

class StockSignalRouter:
    def __init__(self, db_path='trading_bot.db'):
        self.db_path = db_path
        logger.info(f"StockSignalRouter başlatıldı. Veritabanı: {self.db_path}")

    def _baglanti_al(self):
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn
        except Exception as e:
            logger.error(f"Veritabanı bağlantı hatası: {e}")
            return None

    def son_tarama_tarihi(self) -> str:
        """En son taramanın as_of_date değerini döndürür."""
        conn = self._baglanti_al()
        if not conn:
            return ""
        
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT MAX(as_of_date) as son_tarih FROM hisse_sinyalleri")
            row = cursor.fetchone()
            return row['son_tarih'] if row and row['son_tarih'] else ""
        except Exception as e:
            logger.error(f"Son tarama tarihi alınırken hata: {e}")
            return ""
        finally:
            conn.close()

    def tarama_guncel_mi(self, max_yas_saat=48) -> bool:
        """En son taramanın (max_yas_saat) saatten daha yeni olup olmadığını kontrol eder."""
        son_tarih_str = self.son_tarama_tarihi()
        if not son_tarih_str:
            logger.warning("Veritabanında tarama kaydı bulunamadı.")
            return False
            
        try:
            # as_of_date genellikle 'YYYY-MM-DD' veya 'YYYY-MM-DD HH:MM:SS' formatındadır.
            if len(son_tarih_str) == 10:
                son_tarih = datetime.strptime(son_tarih_str, "%Y-%m-%d")
            else:
                son_tarih = datetime.strptime(son_tarih_str[:19], "%Y-%m-%d %H:%M:%S")
                
            fark = datetime.now() - son_tarih
            guncel = fark.total_seconds() <= (max_yas_saat * 3600)
            logger.info(f"Tarama güncel mi: {guncel} (Son tarama: {son_tarih_str}, Yaş: {fark.total_seconds()/3600:.1f} saat)")
            return guncel
        except Exception as e:
            logger.error(f"Tarih formatı kontrol edilirken hata: {e}")
            return False

    def aday_listesi_getir(self, max_aday=15, min_faktor_skoru=65.0,
                           izin_verilen_setuplar=None,
                           haric_semboller=None,
                           max_sektor_yogunluk=3) -> list:
        """
        Son taramadan işlem adaylarının sıralı listesini getirir.
        """
        son_tarih = self.son_tarama_tarihi()
        if not son_tarih:
            logger.error("Aday listesi oluşturmak için geçerli bir tarama tarihi bulunamadı.")
            return []
            
        haric_semboller = haric_semboller or []
        conn = self._baglanti_al()
        if not conn:
            return []
            
        adaylar = []
        try:
            cursor = conn.cursor()
            query = """
                SELECT * FROM hisse_sinyalleri 
                WHERE as_of_date = ? 
                AND decision IN ('AL_ADAYI', 'BEKLE_GERI_CEKILME')
            """
            cursor.execute(query, (son_tarih,))
            rows = cursor.fetchall()
            
            ham_adaylar = []
            for row in rows:
                sembol = row['sembol']
                if sembol in haric_semboller:
                    continue
                    
                # Faktör skoru: Bilesik agirlikli hesap veya ai_skor fallback
                q_score = row['quality_score']
                v_score = row['value_score'] or 50.0
                m_score = row['momentum_score'] or 50.0
                r_score = row['risk_score'] or 50.0
                
                if q_score is not None and q_score > 0:
                    faktor_skoru = round(q_score * 0.35 + v_score * 0.20 + m_score * 0.30 + r_score * 0.15, 1)
                else:
                    faktor_skoru = row['ai_skor'] or 0.0
                    if faktor_skoru <= 1.0:
                        faktor_skoru *= 100.0
                        
                if faktor_skoru < min_faktor_skoru:
                    continue
                    
                faktor_coverage = row['factor_coverage']
                if faktor_coverage is None:
                    faktor_coverage = 100.0
                elif faktor_coverage <= 1.0:
                    faktor_coverage *= 100.0 # 0.85 -> 85.0
                    
                if faktor_coverage < 50.0: # En az %50 veri kapsama kalitesi
                    continue
                    
                setup = row['setup']
                if izin_verilen_setuplar and setup not in izin_verilen_setuplar:
                    continue
                    
                fiyat = row['fiyat'] or 0.0
                sma200 = row['sma200'] or 0.0
                rsi = row['rsi'] or 0.0
                
                # Yön Belirleme (LONG varsayılan)
                yon = 'LONG'
                if setup == 'ZAYIF_TREND' and rsi > 70 and fiyat < sma200:
                    yon = 'SHORT'
                    
                # Seviye (Tier) / Öncelik Belirleme
                decision = row['decision']
                tier = 4 # Default
                if setup == 'KALITELI_GERI_CEKILME' and faktor_skoru >= 70.0:
                    tier = 1
                elif setup == 'TREND_DEVAMI' and faktor_skoru >= 65.0:
                    tier = 2
                elif decision == 'AL_ADAYI' and faktor_skoru >= 60.0:
                    tier = 3
                
                # Belirli seviyede olmayanları (tier 4) eliyoruz
                if tier == 4:
                    continue
                
                reasons_str = row['reasons_json']
                try:
                    reasons = json.loads(reasons_str) if reasons_str else []
                except:
                    reasons = []
                    
                aday = {
                    'sembol': sembol,
                    'sektor': row['sektor'],
                    'fiyat': fiyat,
                    'yon': yon,
                    'faktor_skoru': faktor_skoru,
                    'kalite_skor': row['quality_score'],
                    'deger_skor': row['value_score'],
                    'momentum_skor': row['momentum_score'],
                    'risk_skor': row['risk_score'],
                    'setup': setup,
                    'karar': decision,
                    'tp': row['tp'],
                    'sl': row['sl'],
                    'rsi': rsi,
                    'golden_cross': row['golden_cross'],
                    'rs_skor': row['rs_skor'],
                    'reasons': reasons,
                    'tier': tier
                }
                ham_adaylar.append(aday)
                
            # Sıralama mantığı: tier (düşük daha iyi), ardından faktor_skoru (yüksek daha iyi)
            ham_adaylar.sort(key=lambda x: (x['tier'], -x['faktor_skoru']))
            
            # Sektör dağılımı kontrolü ile max_aday sınırına ulaşma
            sektor_sayaci = {}
            for aday in ham_adaylar:
                sektor = aday['sektor']
                sayi = sektor_sayaci.get(sektor, 0)
                
                if sayi < max_sektor_yogunluk:
                    adaylar.append(aday)
                    sektor_sayaci[sektor] = sayi + 1
                    
                if len(adaylar) >= max_aday:
                    break
                    
            logger.info(f"Aday belirleme tamamlandı. Toplam {len(adaylar)} nitelikli aday bulundu.")
            return adaylar
            
        except Exception as e:
            logger.error(f"Aday listesi getirilirken hata: {e}")
            return []
        finally:
            conn.close()

    def sektor_dagilimi(self, adaylar: list) -> dict:
        """Aday listesinin sektörel dağılımını hesaplar ve döndürür."""
        dagilim = {}
        for aday in adaylar:
            sektor = aday.get('sektor', 'Bilinmiyor')
            dagilim[sektor] = dagilim.get(sektor, 0) + 1
        return dagilim

    def sembol_detay(self, sembol: str) -> dict:
        """Belirtilen sembolün son tarama verilerindeki detaylarını döndürür."""
        son_tarih = self.son_tarama_tarihi()
        conn = self._baglanti_al()
        if not conn or not son_tarih:
            return {}
            
        try:
            cursor = conn.cursor()
            query = "SELECT * FROM hisse_sinyalleri WHERE as_of_date = ? AND sembol = ?"
            cursor.execute(query, (son_tarih, sembol))
            row = cursor.fetchone()
            
            if row:
                detay = dict(row)
                if detay.get('reasons_json'):
                    try:
                        detay['reasons_json'] = json.loads(detay['reasons_json'])
                    except:
                        pass
                if detay.get('feature_json'):
                    try:
                        detay['feature_json'] = json.loads(detay['feature_json'])
                    except:
                        pass
                return detay
            return {}
        except Exception as e:
            logger.error(f"{sembol} detayı alınırken veritabanı hatası: {e}")
            return {}
        finally:
            conn.close()

    def sektor_odakli_adaylar(self, tema_veya_sektor: str, max_aday=10) -> list:
        """
        Belirtilen temaya (örn: 'ai_enerji', 'yari_iletken') veya sektöre ait
        adayları 'thematic_baskets' ve 'sector_deep_dive' kullanarak getirir.
        """
        logger.info(f"Sektör/Tema odaklı tarama başlatılıyor: {tema_veya_sektor}")
        try:
            from thematic_baskets import tema_getir
            from sector_deep_dive import sektor_derinlik_analizi
            
            havuz = tema_getir(tema_veya_sektor)
            if havuz:
                semboller = havuz.get("semboller", [])
                roller = havuz.get("odak_alanlari", {})
            else:
                # Doğrudan sektör/sembol listesi olarak dene
                semboller = [s.strip().upper() for s in tema_veya_sektor.split(",") if s.strip()]
                roller = {}
                
            if not semboller:
                logger.warning(f"'{tema_veya_sektor}' için sembol bulunamadı.")
                return []
                
            df_sonuc = sektor_derinlik_analizi(semboller, roller)
            if df_sonuc.empty:
                return []
                
            adaylar = []
            for _, row in df_sonuc.head(max_aday).iterrows():
                adaylar.append({
                    "sembol": row["Sembol"],
                    "sektor": tema_veya_sektor,
                    "fiyat": row["Fiyat"],
                    "yon": "LONG",
                    "faktor_skoru": row["Kompozit Skor"],
                    "kalite_skor": row["Kalite"],
                    "buyume_skor": row["Büyüme"],
                    "deger_skor": row["Değer"],
                    "momentum_skor": row["Momentum"],
                    "setup": row["Setup"],
                    "karar": row["Karar"],
                    "potansiyel": row["Analist Potansiyeli (%)"],
                    "rol": row["Rol"]
                })
            return adaylar
        except Exception as e:
            logger.error(f"Sektör odaklı adaylar getirilirken hata: {e}")
            return []

    def tarama_tetikle(self) -> bool:
        """stock_value_engine.tam_tarama_baslat() metodunu çağırarak yeni tarama başlatır."""
        logger.info("Tarama tetikleniyor...")
        try:
            import stock_value_engine
            if hasattr(stock_value_engine, 'tam_tarama_baslat'):
                sonuc = stock_value_engine.tam_tarama_baslat()
                logger.info(f"Tarama başarıyla tamamlandı: {sonuc}")
                return bool(sonuc)
            else:
                logger.error("stock_value_engine modülünde 'tam_tarama_baslat' metodu bulunamadı.")
                return False
        except ImportError:
            logger.error("stock_value_engine modülü içe aktarılamadı. Dosyanın aynı dizinde olduğundan emin olun.")
            return False
        except Exception as e:
            logger.error(f"Tarama tetiklenirken bilinmeyen bir hata oluştu: {e}")
            return False

if __name__ == '__main__':
    router = StockSignalRouter()
    print(f"Son Tarama Tarihi: {router.son_tarama_tarihi()}")
    print(f"Tarama Güncel Mi? {router.tarama_guncel_mi()}")
    
    adaylar = router.aday_listesi_getir(max_aday=10)
    print("\n--- EN İYİ ADAYLAR ---")
    for a in adaylar:
        print(f"{a['sembol']:<5} | {a['sektor']:<25} | {a['yon']:<5} | Tier: {a['tier']} | Skor: {a['faktor_skoru']:.1f} | Kur: {a['fiyat']} | Karar: {a['karar']}")
        
    print("\n--- SEKTÖR DAĞILIMI ---")
    print(router.sektor_dagilimi(adaylar))
