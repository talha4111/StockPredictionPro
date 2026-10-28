import sqlite3
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import stock_value_engine as engine


class StockValueFoundationTests(unittest.TestCase):
    @staticmethod
    def _factor_row(index, sector='Technology'):
        return {
            'sembol': f'T{index}',
            'sektor': sector,
            'fiyat': 120.0,
            'sma_50': 110.0,
            'sma_200': 100.0,
            'rsi': 58.0,
            'sma50_atr_uzaklik': 2.0,
            'golden_cross': True,
            'bilanco_riski': False,
            'roe': 0.05 + index * 0.02,
            'roa': 0.02 + index * 0.01,
            'profit_margin': 0.04 + index * 0.015,
            'gross_margin': 0.20 + index * 0.02,
            'revenue_growth': 0.02 + index * 0.02,
            'earnings_growth': 0.01 + index * 0.025,
            'debt_to_equity': 180.0 - index * 15.0,
            'earnings_yield': 0.02 + index * 0.004,
            'fcf_yield': 0.01 + index * 0.005,
            'dividend_yield': 0.002 + index * 0.001,
            'momentum_12_1': 0.02 + index * 0.04,
            'momentum_6_1': 0.01 + index * 0.025,
            'distance_52w_high': -0.25 + index * 0.025,
            'realized_vol_63d': 0.45 - index * 0.025,
            'downside_vol_63d': 0.35 - index * 0.02,
            'max_drawdown_1y': -0.40 + index * 0.025,
            'teknik_skor': None,
            'tp': 130.0,
            'sl': 110.0,
            'atr': 5.0,
            'veri_tarihi': '2026-07-15',
            'veri_durumu': 'OK',
            'motor_surumu': engine.ENGINE_VERSION,
            'success': True,
        }

    def test_factor_ranking_is_discriminative_and_bounded(self):
        ranked = engine.faktor_siralama_uygula([
            self._factor_row(index, 'Technology' if index < 4 else 'Energy')
            for index in range(8)
        ])
        scores = [row['faktor_skor'] for row in ranked]

        self.assertTrue(all(0.0 <= score <= 100.0 for score in scores))
        self.assertGreater(len(set(scores)), 4)
        self.assertLess(sum(score == 100.0 for score in scores), len(scores))

    def test_research_factor_weights_are_normalized_without_changing_defaults(self):
        rows = [
            self._factor_row(index, 'Technology' if index < 4 else 'Energy')
            for index in range(8)
        ]
        default_rank = engine.faktor_siralama_uygula([dict(row) for row in rows])
        explicit_rank = engine.faktor_siralama_uygula(
            [dict(row) for row in rows],
            faktor_agirliklari={
                'quality': 0.35,
                'value': 0.20,
                'momentum': 0.30,
                'risk': 0.15,
            },
        )
        quality_only = engine.faktor_siralama_uygula(
            [dict(row) for row in rows],
            faktor_agirliklari={'quality': 1.0},
        )

        self.assertEqual(
            [(row['sembol'], row['faktor_skor']) for row in default_rank],
            [(row['sembol'], row['faktor_skor']) for row in explicit_rank],
        )
        for row in quality_only:
            self.assertEqual(row['faktor_skor'], round(row['kalite_skor'], 1))
        with self.assertRaises(ValueError):
            engine.faktor_agirliklarini_normalize_et({'quality': -0.1})
        with self.assertRaises(ValueError):
            engine.faktor_agirliklarini_normalize_et({'quality': 0.0})

    def test_sector_neutral_percentiles_compare_peers(self):
        analyses = [
            {'sektor': 'Technology', 'roe': value} for value in (10, 20, 30, 40)
        ] + [
            {'sektor': 'Energy', 'roe': value} for value in (100, 200, 300, 400)
        ]
        scores = engine._metrik_yuzdelikleri(analyses, 'roe', True, True)

        self.assertEqual(scores[0], scores[4])
        self.assertEqual(scores[3], scores[7])
        self.assertEqual(scores[0], 0.0)
        self.assertEqual(scores[3], 100.0)

    def test_factor_bulletin_renders_new_decision_contract(self):
        ranked = engine.faktor_siralama_uygula([
            self._factor_row(index) for index in range(4)
        ])
        output = StringIO()
        with redirect_stdout(output):
            bulletin = engine.sinyal_bulteni_olustur(ranked[:1], 18.0, {})

        self.assertIn('HİSSE FAKTÖR BÜLTENİ', bulletin)
        self.assertIn(ranked[0]['kurulum'], output.getvalue())

    def test_setup_decisions_are_separate_and_sma200_is_not_global_veto(self):
        trend = self._factor_row(7)
        trend.update({'faktor_skor': 80.0, 'kalite_skor': 75.0, 'faktor_kapsami': 0.9})
        self.assertEqual(engine.kurulum_karari_belirle(trend), ('TREND_DEVAMI', 'AL_ADAYI'))

        extended = dict(trend, sma50_atr_uzaklik=4.0)
        self.assertEqual(
            engine.kurulum_karari_belirle(extended),
            ('UZAMIS_TREND', 'BEKLE_GERI_CEKILME'),
        )

        pullback = dict(
            trend,
            fiyat=101.0,
            sma_50=100.0,
            sma_200=95.0,
            sma50_atr_uzaklik=0.5,
            rsi=50.0,
        )
        self.assertEqual(
            engine.kurulum_karari_belirle(pullback),
            ('KALITELI_GERI_CEKILME', 'AL_ADAYI'),
        )

        below_sma200 = dict(
            trend,
            fiyat=90.0,
            sma_50=95.0,
            sma_200=100.0,
            momentum_12_1=-0.05,
            faktor_skor=70.0,
        )
        self.assertEqual(engine.kurulum_karari_belirle(below_sma200), ('IZLE', 'IZLE'))

    def test_local_indicators_are_deterministic(self):
        prices = pd.Series([float(value) for value in range(1, 61)])
        volume = pd.Series([100.0] * len(prices))

        self.assertEqual(engine.ta.sma(prices, length=5).iloc[-1], 58.0)
        self.assertEqual(engine.ta.rsi(prices, length=14).iloc[-1], 100.0)
        self.assertGreater(engine.ta.obv(prices, volume).iloc[-1], 0.0)

        macd = engine.ta.macd(prices)
        self.assertEqual(list(macd.columns), ['MACD', 'MACD_SIGNAL', 'MACD_HIST'])
        self.assertFalse(macd.iloc[-1].isna().any())

    def test_daily_data_freshness_uses_business_days(self):
        fresh = pd.DataFrame({'Close': [100.0]}, index=pd.to_datetime(['2026-07-13']))
        stale = pd.DataFrame({'Close': [100.0]}, index=pd.to_datetime(['2026-07-10']))
        now = datetime(2026, 7, 16, 12, 0)

        self.assertEqual(engine.gunluk_veri_taze_mi(fresh, now=now), (True, '2026-07-13'))
        self.assertEqual(engine.gunluk_veri_taze_mi(stale, now=now), (False, '2026-07-10'))

    def test_macro_failure_does_not_create_neutral_fallback(self):
        with patch.object(engine.yf, 'Ticker', side_effect=RuntimeError('offline')):
            self.assertIsNone(engine.vix_oku())
            self.assertIsNone(engine.spy_12ay_getiri())

    def test_dividend_yield_uses_decimal_ratio(self):
        info = {
            'dividendYield': 0.34,
            'trailingAnnualDividendYield': 0.0033,
            'dividendRate': 1.08,
            'currentPrice': 327.5,
        }
        self.assertAlmostEqual(engine.temettu_verimi_normalize(info), 0.0033)

    def test_sector_failure_is_missing_not_zero(self):
        with patch.object(engine.yf, 'Ticker', side_effect=RuntimeError('offline')):
            with patch.object(engine.time, 'sleep'):
                self.assertEqual(engine.sektor_rotasyonu_radar(), {})

    def test_scan_stops_when_required_macro_data_is_missing(self):
        missing = engine.VeriSonucu(error='offline')
        with patch.object(engine, 'vix_verisi_oku', return_value=missing):
            self.assertEqual(engine.tam_tarama_baslat(), [])

        status = engine.son_tarama_durumu_oku()
        self.assertEqual(status['status'], 'DATA_INCOMPLETE')
        self.assertIn('VIX', status['message'])

    def test_signal_storage_is_versioned_and_deduplicated(self):
        signal = {
            'sembol': 'TEST',
            'sektor': 'Technology',
            'fiyat': 100.0,
            'sma_200': 90.0,
            'rsi': 55.0,
            'teknik_skor': 80.0,
            'tp': 110.0,
            'sl': 95.0,
            'golden_cross': True,
            'rs_skor': 70.0,
            'veri_tarihi': '2026-07-15',
            'veri_durumu': 'OK',
            'motor_surumu': engine.ENGINE_VERSION,
            'kurulum': 'LEGACY_COMBINED',
            'karar': 'AL_ADAYI',
            'kalite_skor': 75.0,
            'deger_skor': 65.0,
            'momentum_skor': 80.0,
            'risk_skor': 70.0,
            'faktor_kapsami': 0.9,
            'olumlu_nedenler': ['Kalite %75'],
            'olumsuz_nedenler': [],
        }

        db_file = Path(__file__).resolve().parent / '.test_stock_signals.db'
        db_file.unlink(missing_ok=True)
        try:
            db_path = str(db_file)
            now = datetime(2026, 7, 16, 9, 30)
            first = engine.sinyal_kaydet([signal], vix_degeri=18.5, db_path=db_path, now=now)
            second = engine.sinyal_kaydet([signal], vix_degeri=18.5, db_path=db_path, now=now)

            self.assertEqual(first, 1)
            self.assertEqual(second, 0)

            conn = sqlite3.connect(db_path)
            try:
                count = conn.execute('SELECT COUNT(*) FROM hisse_sinyalleri').fetchone()[0]
                columns = {
                    row[1] for row in conn.execute('PRAGMA table_info(hisse_sinyal_sonuclari)')
                }
                signal_columns = {
                    row[1] for row in conn.execute('PRAGMA table_info(hisse_sinyalleri)')
                }
                stored_factor = conn.execute(
                    'SELECT quality_score, factor_coverage FROM hisse_sinyalleri'
                ).fetchone()
            finally:
                conn.close()

            self.assertEqual(count, 1)
            self.assertTrue({'getiri_5g', 'getiri_20g', 'getiri_60g', 'getiri_120g'}.issubset(columns))
            self.assertTrue({'quality_score', 'factor_coverage', 'feature_json'}.issubset(signal_columns))
            self.assertEqual(stored_factor, (75.0, 0.9))
        finally:
            db_file.unlink(missing_ok=True)


if __name__ == '__main__':
    unittest.main()
