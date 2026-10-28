import json
import sqlite3
import logging
import threading
from datetime import datetime, timedelta
import math
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)

class StockTradeJournal:
    """
    US hisse senedi alım-satım işlemleri için gelişmiş kayıt ve performans takip sistemi (Interactive Brokers uyumlu).
    İşlemleri hem SQLite veritabanına hem de yedeklilik için JSONL dosyasına kaydeder.
    """

    def __init__(self, db_path: str = 'trading_bot.db', jsonl_path: str = 'stock_trade_journal.jsonl'):
        self.db_path = db_path
        self.jsonl_path = jsonl_path
        self.lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        """SQLite veritabanını ve tabloyu oluşturur/günceller."""
        try:
            with self.lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                    CREATE TABLE IF NOT EXISTS stock_trades (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        tip TEXT NOT NULL,
                        zaman TEXT NOT NULL,
                        sembol TEXT NOT NULL,
                        yon TEXT NOT NULL,
                        giris_fiyati REAL,
                        cikis_fiyati REAL,
                        miktar INTEGER,
                        margin REAL,
                        pnl_usd REAL,
                        pnl_yuzde REAL,
                        ai_skoru REAL,
                        faktor_skoru REAL,
                        setup_tipi TEXT,
                        sektor TEXT,
                        atr_giris REAL,
                        tp_fiyat REAL,
                        sl_fiyat REAL,
                        ibkr_order_id TEXT,
                        kapanis_sebebi TEXT,
                        tutma_gun INTEGER,
                        komisyon_toplam REAL,
                        kismi_yuzde REAL
                    )
                    ''')
                    conn.commit()
            logger.info("StockTradeJournal: Veritabanı başlatıldı.")
        except Exception as e:
            logger.error(f"StockTradeJournal DB başlatma hatası: {e}")

    def _log_jsonl(self, record: dict):
        """İşlem kaydını JSONL formatında dosyaya ekler."""
        try:
            with self.lock:
                with open(self.jsonl_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, ensure_ascii=False) + '\n')
        except Exception as e:
            logger.error(f"StockTradeJournal JSONL yazma hatası: {e}")

    def islem_ac(self, sembol: str, yon: str, giris_fiyati: float, miktar: int, **kwargs) -> int:
        """
        Yeni bir pozisyon açılışını kaydeder.
        Dönüş: trade_id (int)
        """
        zaman = datetime.now().isoformat()
        
        margin_used = kwargs.get('margin_used', 0.0)
        ai_score = kwargs.get('ai_score', 0.0)
        factor_score = kwargs.get('factor_score', 0.0)
        setup_type = kwargs.get('setup_type', '')
        sector = kwargs.get('sector', '')
        atr_at_entry = kwargs.get('atr_at_entry', 0.0)
        tp_price = kwargs.get('tp_price', 0.0)
        sl_price = kwargs.get('sl_price', 0.0)
        ibkr_order_id = kwargs.get('ibkr_order_id', '')
        komisyon = kwargs.get('komisyon_toplam', 0.0)

        record = {
            'tip': 'acilis',
            'zaman': zaman,
            'sembol': sembol,
            'yon': yon,
            'giris_fiyati': giris_fiyati,
            'miktar': miktar,
            'margin': margin_used,
            'ai_skoru': ai_score,
            'faktor_skoru': factor_score,
            'setup_tipi': setup_type,
            'sektor': sector,
            'atr_giris': atr_at_entry,
            'tp_fiyat': tp_price,
            'sl_fiyat': sl_price,
            'ibkr_order_id': ibkr_order_id,
            'komisyon_toplam': komisyon
        }

        self._log_jsonl(record)
        trade_id = -1

        try:
            with self.lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO stock_trades (
                            tip, zaman, sembol, yon, giris_fiyati, miktar, margin,
                            ai_skoru, faktor_skoru, setup_tipi, sektor, atr_giris,
                            tp_fiyat, sl_fiyat, ibkr_order_id, komisyon_toplam
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        'acilis', zaman, sembol, yon, giris_fiyati, miktar, margin_used,
                        ai_score, factor_score, setup_type, sector, atr_at_entry,
                        tp_price, sl_price, ibkr_order_id, komisyon
                    ))
                    trade_id = cursor.lastrowid
                    conn.commit()
            logger.info(f"İşlem açıldı: {sembol} {yon} (ID: {trade_id})")
        except Exception as e:
            logger.error(f"İşlem açılışı kaydedilemedi: {e}")

        return trade_id

    def _get_acilis_islemi(self, sembol: str, yon: str = None) -> Optional[tuple]:
        """İlgili sembol için açık olan en son işlemi bulur."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = "SELECT id, zaman, giris_fiyati, miktar, yon FROM stock_trades WHERE sembol = ? AND tip = 'acilis' ORDER BY id DESC LIMIT 1"
                cursor.execute(query, (sembol,))
                return cursor.fetchone()
        except Exception as e:
            logger.error(f"Açılış işlemi bulunurken hata: {e}")
        return None

    def islem_kapat(self, sembol: str, cikis_fiyati: float, kapanis_sebebi: str, **kwargs) -> dict:
        """
        Mevcut bir pozisyonun tamamen kapanışını kaydeder.
        """
        acilis = self._get_acilis_islemi(sembol)
        zaman = datetime.now().isoformat()
        
        giris_fiyati = 0.0
        yon = 'LONG'
        miktar = kwargs.get('miktar', 0)
        tutma_gun = 0
        pnl_usd = kwargs.get('pnl_usd', 0.0)
        pnl_yuzde = kwargs.get('pnl_pct', 0.0)

        if acilis:
            _, acilis_zaman_str, giris_fiyati, acilis_miktar, yon = acilis
            acilis_zamani = datetime.fromisoformat(acilis_zaman_str)
            tutma_gun = (datetime.now() - acilis_zamani).days
            if miktar == 0:
                miktar = acilis_miktar

            if 'pnl_usd' not in kwargs:
                if yon == 'LONG':
                    pnl_usd = (cikis_fiyati - giris_fiyati) * miktar
                else:
                    pnl_usd = (giris_fiyati - cikis_fiyati) * miktar
            
            if 'pnl_pct' not in kwargs and giris_fiyati > 0:
                if yon == 'LONG':
                    pnl_yuzde = ((cikis_fiyati - giris_fiyati) / giris_fiyati) * 100
                else:
                    pnl_yuzde = ((giris_fiyati - cikis_fiyati) / giris_fiyati) * 100

        komisyon = kwargs.get('commission_total', 0.0)
        pnl_usd -= komisyon  # Komisyonu kar/zarardan düş

        record = {
            'tip': 'kapanis',
            'zaman': zaman,
            'sembol': sembol,
            'yon': yon,
            'giris_fiyati': giris_fiyati,
            'cikis_fiyati': cikis_fiyati,
            'miktar': miktar,
            'pnl_usd': pnl_usd,
            'pnl_yuzde': pnl_yuzde,
            'kapanis_sebebi': kapanis_sebebi,
            'tutma_gun': tutma_gun,
            'komisyon_toplam': komisyon
        }

        self._log_jsonl(record)

        try:
            with self.lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO stock_trades (
                            tip, zaman, sembol, yon, giris_fiyati, cikis_fiyati, miktar,
                            pnl_usd, pnl_yuzde, kapanis_sebebi, tutma_gun, komisyon_toplam
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        'kapanis', zaman, sembol, yon, giris_fiyati, cikis_fiyati, miktar,
                        pnl_usd, pnl_yuzde, kapanis_sebebi, tutma_gun, komisyon
                    ))
                    conn.commit()
            logger.info(f"İşlem kapatıldı: {sembol} (PnL: ${pnl_usd:.2f})")
        except Exception as e:
            logger.error(f"İşlem kapanışı kaydedilemedi: {e}")

        return {'pnl_usd': pnl_usd, 'pnl_pct': pnl_yuzde, 'hold_days': tutma_gun}

    def kismi_cikis(self, sembol: str, cikis_fiyati: float, kismi_yuzde: float, kapanis_sebebi: str, **kwargs) -> dict:
        """
        Kısmi çıkış (kar al) işlemlerini kaydeder.
        """
        acilis = self._get_acilis_islemi(sembol)
        zaman = datetime.now().isoformat()
        
        giris_fiyati = 0.0
        yon = 'LONG'
        cikis_miktar = 0
        tutma_gun = 0
        pnl_usd = 0.0
        pnl_yuzde = 0.0

        if acilis:
            _, acilis_zaman_str, giris_fiyati, acilis_miktar, yon = acilis
            acilis_zamani = datetime.fromisoformat(acilis_zaman_str)
            tutma_gun = (datetime.now() - acilis_zamani).days
            cikis_miktar = int(acilis_miktar * (kismi_yuzde / 100.0))

            if yon == 'LONG':
                pnl_usd = (cikis_fiyati - giris_fiyati) * cikis_miktar
                pnl_yuzde = ((cikis_fiyati - giris_fiyati) / giris_fiyati) * 100
            else:
                pnl_usd = (giris_fiyati - cikis_fiyati) * cikis_miktar
                pnl_yuzde = ((giris_fiyati - cikis_fiyati) / giris_fiyati) * 100

        komisyon = kwargs.get('commission_total', 0.0)
        pnl_usd -= komisyon

        record = {
            'tip': 'kismi_cikis',
            'zaman': zaman,
            'sembol': sembol,
            'yon': yon,
            'giris_fiyati': giris_fiyati,
            'cikis_fiyati': cikis_fiyati,
            'miktar': cikis_miktar,
            'pnl_usd': pnl_usd,
            'pnl_yuzde': pnl_yuzde,
            'kapanis_sebebi': kapanis_sebebi,
            'tutma_gun': tutma_gun,
            'komisyon_toplam': komisyon,
            'kismi_yuzde': kismi_yuzde
        }

        self._log_jsonl(record)

        try:
            with self.lock:
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute('''
                        INSERT INTO stock_trades (
                            tip, zaman, sembol, yon, giris_fiyati, cikis_fiyati, miktar,
                            pnl_usd, pnl_yuzde, kapanis_sebebi, tutma_gun, komisyon_toplam, kismi_yuzde
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        'kismi_cikis', zaman, sembol, yon, giris_fiyati, cikis_fiyati, cikis_miktar,
                        pnl_usd, pnl_yuzde, kapanis_sebebi, tutma_gun, komisyon, kismi_yuzde
                    ))
                    conn.commit()
            logger.info(f"Kısmi çıkış yapıldı: {sembol} %{kismi_yuzde} (PnL: ${pnl_usd:.2f})")
        except Exception as e:
            logger.error(f"Kısmi çıkış kaydedilemedi: {e}")

        return {'pnl_usd': pnl_usd, 'pnl_pct': pnl_yuzde, 'miktar': cikis_miktar}

    def acik_islemler(self) -> list:
        """Şu anda açık olan işlemleri (tamamen kapanmamış) döndürür."""
        acik_liste = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Açılışları bul
                cursor.execute("SELECT * FROM stock_trades WHERE tip = 'acilis'")
                acilislar = cursor.fetchall()
                
                for acilis in acilislar:
                    sembol = acilis['sembol']
                    
                    # Bu sembol için kapanış var mı kontrol et (kısmi olmayan)
                    cursor.execute("SELECT id FROM stock_trades WHERE tip = 'kapanis' AND sembol = ? AND zaman > ?", (sembol, acilis['zaman']))
                    kapanis = cursor.fetchone()
                    
                    if not kapanis:
                        acik_liste.append(dict(acilis))
                        
        except Exception as e:
            logger.error(f"Açık işlemler alınırken hata: {e}")
            
        return acik_liste

    def performans_ozeti(self, son_n_gun: int = None) -> dict:
        """Genel veya son N günlük performans istatistiklerini hesaplar."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                query_cond = "WHERE tip IN ('kapanis', 'kismi_cikis')"
                params = []
                if son_n_gun is not None:
                    cutoff_date = (datetime.now() - timedelta(days=son_n_gun)).isoformat()
                    query_cond += " AND zaman >= ?"
                    params.append(cutoff_date)
                    
                cursor.execute(f"SELECT * FROM stock_trades {query_cond}", params)
                trades = cursor.fetchall()
                
                if not trades:
                    return {"hata": "Yeterli kapanmış işlem verisi yok."}

                total_trades = len(trades)
                winners = [t for t in trades if t['pnl_usd'] > 0]
                losers = [t for t in trades if t['pnl_usd'] <= 0]
                
                win_count = len(winners)
                lose_count = len(losers)
                win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
                
                total_pnl = sum(t['pnl_usd'] for t in trades)
                gross_wins = sum(t['pnl_usd'] for t in winners)
                gross_losses = abs(sum(t['pnl_usd'] for t in losers))
                
                avg_winner = gross_wins / win_count if win_count > 0 else 0
                avg_loser = gross_losses / lose_count if lose_count > 0 else 0
                avg_pnl = total_pnl / total_trades if total_trades > 0 else 0
                profit_factor = gross_wins / gross_losses if gross_losses > 0 else float('inf')
                
                # Setup ve Sektör analizi için verileri topla
                sektor_kar = {}
                setup_kar = {}
                
                for t in trades:
                    # acilis bilgisini bul
                    cursor.execute("SELECT sektor, setup_tipi FROM stock_trades WHERE tip = 'acilis' AND sembol = ? AND zaman <= ? ORDER BY zaman DESC LIMIT 1", (t['sembol'], t['zaman']))
                    acilis_info = cursor.fetchone()
                    if acilis_info:
                        sek = acilis_info['sektor'] or 'Bilinmiyor'
                        setup = acilis_info['setup_tipi'] or 'Bilinmiyor'
                        
                        sektor_kar[sek] = sektor_kar.get(sek, 0.0) + t['pnl_usd']
                        setup_kar[setup] = setup_kar.get(setup, 0.0) + t['pnl_usd']

                # Drawdown Hesaplama
                cursor.execute("SELECT zaman, pnl_usd FROM stock_trades WHERE tip IN ('kapanis', 'kismi_cikis') ORDER BY zaman ASC")
                all_pnl = cursor.fetchall()
                
                cum_pnl = 0
                max_cum_pnl = 0
                max_dd_usd = 0
                daily_returns = []
                
                for pnl_row in all_pnl:
                    pnl_val = pnl_row['pnl_usd']
                    cum_pnl += pnl_val
                    if cum_pnl > max_cum_pnl:
                        max_cum_pnl = cum_pnl
                    dd = max_cum_pnl - cum_pnl
                    if dd > max_dd_usd:
                        max_dd_usd = dd
                    daily_returns.append(pnl_val)
                
                # Sharpe Ratio Yaklaşımı
                import statistics
                if len(daily_returns) > 1:
                    stdev = statistics.stdev(daily_returns)
                    mean = statistics.mean(daily_returns)
                    sharpe = (mean / stdev) * math.sqrt(252) if stdev > 0 else 0
                else:
                    sharpe = 0.0

                return {
                    'total_trades': total_trades,
                    'winners': win_count,
                    'losers': lose_count,
                    'win_rate': round(win_rate, 2),
                    'total_pnl': round(total_pnl, 2),
                    'avg_pnl_per_trade': round(avg_pnl, 2),
                    'avg_winner': round(avg_winner, 2),
                    'avg_loser': round(avg_loser, 2),
                    'profit_factor': round(profit_factor, 2),
                    'max_drawdown_usd': round(max_dd_usd, 2),
                    'max_drawdown_pct': 0.0, # Sermaye bilgisi olmadan yüzdesel DD tahmini zordur
                    'avg_hold_days': round(sum(t['tutma_gun'] or 0 for t in trades) / total_trades, 1) if total_trades > 0 else 0,
                    'best_trade': max((t['pnl_usd'] for t in trades), default=0),
                    'worst_trade': min((t['pnl_usd'] for t in trades), default=0),
                    'sharpe_ratio': round(sharpe, 2),
                    'trades_by_sector': {k: round(v, 2) for k, v in sektor_kar.items()},
                    'trades_by_setup': {k: round(v, 2) for k, v in setup_kar.items()}
                }

        except Exception as e:
            logger.error(f"Performans özeti hesaplanırken hata: {e}")
            return {"hata": str(e)}

    def gunluk_rapor(self, tarih: str = None) -> str:
        """Belirtilen gün (veya bugün) için işlem özet raporu üretir."""
        if not tarih:
            tarih = datetime.now().strftime('%Y-%m-%d')
        
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM stock_trades WHERE tip IN ('kapanis', 'kismi_cikis') AND zaman LIKE ?", (f"{tarih}%",))
                trades = cursor.fetchall()
                
                if not trades:
                    return f"[{tarih}] tarihinde kapanmış işlem bulunmamaktadır."
                
                pnl = sum(t['pnl_usd'] for t in trades)
                win = sum(1 for t in trades if t['pnl_usd'] > 0)
                
                rapor = f"--- GÜNLÜK RAPOR ({tarih}) ---\n"
                rapor += f"Toplam İşlem: {len(trades)}\n"
                rapor += f"Kazançlı: {win} | Kayıplı: {len(trades)-win}\n"
                rapor += f"Günlük PnL: ${pnl:.2f}\n"
                rapor += "Detaylar:\n"
                for t in trades:
                    rapor += f" - {t['sembol']} | {t['yon']} | Sebeb: {t['kapanis_sebebi']} | PnL: ${t['pnl_usd']:.2f}\n"
                return rapor
        except Exception as e:
            return f"Rapor oluşturulurken hata: {e}"

    def haftalik_rapor(self) -> str:
        """Son 7 günün performans raporunu üretir."""
        ozet = self.performans_ozeti(son_n_gun=7)
        if "hata" in ozet:
            return "Haftalık rapor verisi yok."
        
        rapor = "--- HAFTALIK RAPOR (Son 7 Gün) ---\n"
        rapor += f"Toplam PnL: ${ozet['total_pnl']:.2f}\n"
        rapor += f"Kazanma Oranı: %{ozet['win_rate']:.1f} ({ozet['winners']}K / {ozet['losers']}Z)\n"
        rapor += f"Profit Factor: {ozet['profit_factor']:.2f}\n"
        return rapor

    def aylik_rapor(self) -> str:
        """Son 30 günün performans raporunu üretir."""
        ozet = self.performans_ozeti(son_n_gun=30)
        if "hata" in ozet:
            return "Aylık rapor verisi yok."
        
        rapor = "--- AYLIK RAPOR (Son 30 Gün) ---\n"
        rapor += f"Toplam PnL: ${ozet['total_pnl']:.2f}\n"
        rapor += f"Kazanma Oranı: %{ozet['win_rate']:.1f} ({ozet['winners']}K / {ozet['losers']}Z)\n"
        rapor += f"Profit Factor: {ozet['profit_factor']:.2f}\n"
        rapor += f"Sharpe Ratio: {ozet['sharpe_ratio']:.2f}\n"
        rapor += f"Maks. Drawdown: ${ozet['max_drawdown_usd']:.2f}\n"
        return rapor

    def equity_curve(self) -> list:
        """
        Grafik çizimi için kümülatif PnL serisi döndürür.
        Format: [(tarih_str, cum_pnl), ...]
        """
        curve = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT zaman, pnl_usd FROM stock_trades WHERE tip IN ('kapanis', 'kismi_cikis') ORDER BY zaman ASC")
                trades = cursor.fetchall()
                
                cum_pnl = 0.0
                for t in trades:
                    cum_pnl += t['pnl_usd']
                    curve.append((t['zaman'], cum_pnl))
        except Exception as e:
            logger.error(f"Equity curve oluşturulamadı: {e}")
        return curve

    def drawdown_series(self) -> list:
        """
        Zaman içindeki düşüş (drawdown) eğrisini döndürür.
        Format: [(tarih_str, drawdown_usd), ...]
        """
        series = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("SELECT zaman, pnl_usd FROM stock_trades WHERE tip IN ('kapanis', 'kismi_cikis') ORDER BY zaman ASC")
                trades = cursor.fetchall()
                
                cum_pnl = 0.0
                max_cum_pnl = 0.0
                for t in trades:
                    cum_pnl += t['pnl_usd']
                    if cum_pnl > max_cum_pnl:
                        max_cum_pnl = cum_pnl
                    dd = max_cum_pnl - cum_pnl
                    series.append((t['zaman'], dd))
        except Exception as e:
            logger.error(f"Drawdown series oluşturulamadı: {e}")
        return series
