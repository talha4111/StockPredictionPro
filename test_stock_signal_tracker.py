import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import stock_signal_tracker as tracker
import stock_value_engine as engine


class StockSignalTrackerTests(unittest.TestCase):
    def setUp(self):
        self.db_file = Path(__file__).resolve().parent / '.test_stock_tracker.db'
        self.db_file.unlink(missing_ok=True)
        self.dates = pd.bdate_range('2025-01-02', periods=135)
        self.histories = {
            'TEST': self._history(100.0, 1.0),
            'RECENT': self._history(80.0, 0.4),
            'SPY': self._history(200.0, 0.5),
            'XLK': self._history(50.0, 0.2),
        }
        self._create_legacy_database()

    def tearDown(self):
        self.db_file.unlink(missing_ok=True)

    def _history(self, start, daily_step):
        close = start + np.arange(len(self.dates)) * daily_step
        return pd.DataFrame(
            {
                'Close': close,
                'High': close * 1.01,
                'Low': close * 0.99,
            },
            index=self.dates,
        )

    def _create_legacy_database(self):
        conn = sqlite3.connect(self.db_file)
        try:
            conn.execute('''CREATE TABLE hisse_sinyalleri (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tarih TEXT, sembol TEXT, sektor TEXT, fiyat REAL,
                sma200 REAL, rsi REAL, ai_skor REAL, tp REAL, sl REAL,
                golden_cross INTEGER, vix REAL, rs_skor REAL
            )''')
            old_date = self.dates[5].date().isoformat()
            recent_date = self.dates[128].date().isoformat()
            rows = [
                (old_date + ' 18:00', 'TEST', 'Technology', 105.0, 90.0, 50.0, 75.0),
                (old_date + ' 20:00', 'TEST', 'Technology', 105.0, 90.0, 50.0, 80.0),
                (recent_date + ' 18:00', 'RECENT', 'Technology', 131.2, 120.0, 55.0, 70.0),
            ]
            conn.executemany('''INSERT INTO hisse_sinyalleri
                (tarih, sembol, sektor, fiyat, sma200, rsi, ai_skor)
                VALUES (?, ?, ?, ?, ?, ?, ?)''', rows)
            conn.commit()
        finally:
            conn.close()

    def _loader(self, symbol, start_date, end_date):
        return self.histories[symbol].copy()

    def test_updates_all_mature_horizons_and_benchmarks(self):
        summary = tracker.sinyal_sonuclarini_guncelle(
            str(self.db_file),
            {'Technology': 'XLK'},
            price_loader=self._loader,
            now=datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(summary['signals_found'], 3)
        self.assertEqual(summary['signals_updated'], 3)
        self.assertEqual(summary['horizons'], {'5g': 3, '20g': 2, '60g': 2, '120g': 2})
        self.assertEqual(summary['errors'], {})

        conn = sqlite3.connect(self.db_file)
        try:
            result = conn.execute('''SELECT
                    entry_price, getiri_5g, spy_getiri_5g,
                    excess_spy_5g, excess_sektor_5g,
                    mfe_20g, mae_20g, getiri_120g
                FROM hisse_sinyal_sonuclari
                WHERE signal_id = 2''').fetchone()
            recent = conn.execute('''SELECT getiri_5g, getiri_20g
                FROM hisse_sinyal_sonuclari WHERE signal_id = 3''').fetchone()
        finally:
            conn.close()

        expected_stock_5g = 110.0 / 105.0 - 1.0
        expected_spy_5g = 205.0 / 202.5 - 1.0
        expected_sector_5g = 52.0 / 51.0 - 1.0
        self.assertAlmostEqual(result[0], 105.0)
        self.assertAlmostEqual(result[1], expected_stock_5g)
        self.assertAlmostEqual(result[2], expected_spy_5g)
        self.assertAlmostEqual(result[3], expected_stock_5g - expected_spy_5g)
        self.assertAlmostEqual(result[4], expected_stock_5g - expected_sector_5g)
        self.assertAlmostEqual(result[5], (125.0 * 1.01) / 105.0 - 1.0)
        self.assertAlmostEqual(result[6], (106.0 * 0.99) / 105.0 - 1.0)
        self.assertAlmostEqual(result[7], 225.0 / 105.0 - 1.0)
        self.assertIsNotNone(recent[0])
        self.assertIsNone(recent[1])

    def test_performance_report_deduplicates_same_symbol_and_date(self):
        tracker.sinyal_sonuclarini_guncelle(
            str(self.db_file),
            {'Technology': 'XLK'},
            price_loader=self._loader,
            now=datetime(2026, 1, 2, 22, 0, tzinfo=timezone.utc),
        )
        report = tracker.performans_ozeti(str(self.db_file))

        self.assertEqual(report['independent_signals'], 2)
        self.assertEqual(report['duplicates_excluded'], 1)
        self.assertEqual(report['horizons']['5g']['sample'], 2)
        self.assertEqual(report['horizons']['20g']['sample'], 1)
        self.assertEqual(report['horizons']['20g']['sector_sample'], 1)
        self.assertIsNotNone(report['horizons']['20g']['median_excess_sector'])
        self.assertIn('LEGACY_SIGNAL', report['by_decision_20g'])

    def test_incomplete_us_daily_bar_is_not_used(self):
        current_day = pd.Timestamp('2026-07-16')
        frame = pd.DataFrame({'Close': [100.0]}, index=[current_day])
        before_close = datetime(2026, 7, 16, 18, 0, tzinfo=timezone.utc)
        after_close = datetime(2026, 7, 16, 21, 0, tzinfo=timezone.utc)

        self.assertTrue(tracker.tamamlanmamis_gunluk_mumu_cikar(frame, before_close).empty)
        self.assertEqual(len(tracker.tamamlanmamis_gunluk_mumu_cikar(frame, after_close)), 1)
        self.assertTrue(engine.tamamlanmis_gunluk_veri(frame, before_close).empty)
        self.assertEqual(len(engine.tamamlanmis_gunluk_veri(frame, after_close)), 1)


if __name__ == '__main__':
    unittest.main()
