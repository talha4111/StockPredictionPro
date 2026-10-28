import json
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

import stock_value_engine as sve


class CompletedBarContractTests(unittest.TestCase):
    def test_daily_bar_is_dropped_before_market_close(self):
        index = pd.DatetimeIndex([
            '2026-07-24 00:00:00-04:00',
            '2026-07-27 00:00:00-04:00',
        ])
        frame = pd.DataFrame({'Close': [100.0, 90.0]}, index=index)

        result = sve._tamamlanmis_barlari_sec(
            frame,
            '1d',
            now='2026-07-27 11:00:00-04:00',
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(sve._bar_tarihi(result), '2026-07-24')

    def test_daily_bar_is_kept_after_settlement_buffer(self):
        index = pd.DatetimeIndex([
            '2026-07-24 00:00:00-04:00',
            '2026-07-27 00:00:00-04:00',
        ])
        frame = pd.DataFrame({'Close': [100.0, 90.0]}, index=index)

        result = sve._tamamlanmis_barlari_sec(
            frame,
            '1d',
            now='2026-07-27 16:20:00-04:00',
        )

        self.assertEqual(len(result), 2)

    def test_current_week_is_dropped_until_friday_close(self):
        index = pd.DatetimeIndex([
            '2026-07-13 00:00:00-04:00',
            '2026-07-20 00:00:00-04:00',
            '2026-07-27 00:00:00-04:00',
        ])
        frame = pd.DataFrame({'Close': [100.0, 105.0, 80.0]}, index=index)

        result = sve._tamamlanmis_barlari_sec(
            frame,
            '1wk',
            now='2026-07-27 11:00:00-04:00',
        )

        self.assertEqual(list(result['Close']), [100.0, 105.0])
        self.assertEqual(sve._bar_tarihi(result), '2026-07-20')

    def test_missing_last_session_is_rebuilt_from_complete_intraday_bars(self):
        daily_index = pd.DatetimeIndex([
            '2026-07-23 00:00:00-04:00',
            '2026-07-27 00:00:00-04:00',
        ])
        daily = pd.DataFrame({
            'Open': [100.0, 80.0],
            'High': [105.0, 85.0],
            'Low': [95.0, 75.0],
            'Close': [102.0, 78.0],
            'Volume': [1_000_000.0, 500_000.0],
        }, index=daily_index)
        minute_index = pd.date_range(
            '2026-07-24 09:30:00-04:00',
            periods=390,
            freq='1min',
        )
        minute_closes = np.linspace(101.0, 94.0, len(minute_index))
        intraday = pd.DataFrame({
            'Open': minute_closes,
            'High': minute_closes + 0.5,
            'Low': minute_closes - 0.5,
            'Close': minute_closes,
            'Volume': np.full(len(minute_index), 10_000.0),
        }, index=minute_index)

        class FakeTicker:
            fast_info = {'last_price': 90.0, 'previous_close': 94.0}

            def history(self, period, interval='1d', prepost=False):
                self.history_call = (period, interval, prepost)
                return intraday.copy()

        result, meta = sve._gunluk_veriyi_hazirla(
            FakeTicker(),
            daily,
            now='2026-07-27 11:00:00-04:00',
        )

        self.assertTrue(meta['ok'])
        self.assertEqual(meta['veri_durumu'], 'dakikalik_veriden_onarildi')
        self.assertEqual(meta['onarilan_gunluk_barlar'], ['2026-07-24'])
        self.assertEqual(sve._bar_tarihi(result), '2026-07-24')
        self.assertAlmostEqual(float(result['Close'].iloc[-1]), 94.0)

    def test_stale_daily_data_fails_closed_when_repair_is_unavailable(self):
        index = pd.DatetimeIndex(['2026-07-23 00:00:00-04:00'])
        daily = pd.DataFrame({
            'Open': [100.0],
            'High': [105.0],
            'Low': [95.0],
            'Close': [100.0],
            'Volume': [1_000_000.0],
        }, index=index)

        class FakeTicker:
            fast_info = {'last_price': 80.0, 'previous_close': 82.0}

            def history(self, period, interval='1d', prepost=False):
                return pd.DataFrame()

        result, meta = sve._gunluk_veriyi_hazirla(
            FakeTicker(),
            daily,
            now='2026-07-27 11:00:00-04:00',
        )

        self.assertFalse(meta['ok'])
        self.assertEqual(meta['veri_durumu'], 'bayat_veya_eksik')
        self.assertEqual(sve._bar_tarihi(result), '2026-07-23')


class SectorPeTests(unittest.TestCase):
    def setUp(self):
        self.cache_path = Path(__file__).with_name(
            f'.test_sector_pe_{uuid.uuid4().hex}.json'
        )

    def tearDown(self):
        if self.cache_path.exists():
            self.cache_path.unlink()

    def test_info_fallback_and_versioned_nonempty_cache(self):
        # Eski/boş cache geçerli kabul edilmemeli.
        self.cache_path.write_text(
            json.dumps({'ts': time.time(), 'data': {}}),
            encoding='utf-8',
        )

        values = {'AAA': 20.0, 'BBB': 40.0, 'BAD': -3.0}

        class FakeTicker:
            def __init__(self, symbol):
                self.fast_info = {}
                self.info = {'trailingPE': values[symbol]}

        with patch.object(sve.yf, 'Ticker', side_effect=FakeTicker):
            result = sve.sektor_pe_ortalamalari(
                havuz={'AAA': 'Technology', 'BBB': 'Technology', 'BAD': 'Energy'},
                cache_dosya=str(self.cache_path),
                sleep_seconds=0,
            )

        self.assertEqual(result, {'Technology': 30.0})
        cache = json.loads(self.cache_path.read_text(encoding='utf-8'))
        self.assertEqual(cache['schema_version'], 2)
        self.assertEqual(cache['sample_counts'], {'Technology': 2})
        self.assertNotIn('Energy', result)


class StockAnalysisContractTests(unittest.TestCase):
    def test_analysis_ignores_intraday_bar_and_reports_all_hard_failures(self):
        index = pd.bdate_range(
            end='2026-07-27',
            periods=260,
            tz='America/New_York',
        )
        closes = np.linspace(100.0, 500.0, len(index))
        closes[-1] = 1.0  # Açık seanstaki geçici fiyat; analize girmemeli.
        daily = pd.DataFrame({
            'Open': closes,
            'High': closes + 2.0,
            'Low': np.maximum(closes - 2.0, 0.1),
            'Close': closes,
            'Volume': np.full(len(index), 1_000_000.0),
        }, index=index)

        class FakeTicker:
            def history(self, period, interval='1d'):
                self.assert_history_call = (period, interval)
                return daily.copy()

        with patch.object(sve.yf, 'Ticker', return_value=FakeTicker()):
            result = sve.hisse_analiz_et(
                'TEST',
                'Technology',
                vix_degeri=20.0,
                spy_getiri=0.10,
                sektor_pe_map={},
                sektor_momentum={},
                now='2026-07-27 11:00:00-04:00',
            )

        self.assertFalse(result['success'])
        self.assertEqual(result['last_completed_daily_bar'], '2026-07-24')
        self.assertGreater(result['fiyat'], 490.0)
        self.assertIsNone(result['kural_skoru'])
        self.assertEqual(result['scoring_mode'], sve.STOCK_SCORING_MODE)
        self.assertTrue(any(reason.startswith('RSI Yüksek') for reason in result['red_sebepleri']))
        self.assertTrue(any(reason.startswith('Aşırı Primlenmiş') for reason in result['red_sebepleri']))

    def test_rule_score_prefers_new_field_and_supports_legacy_records(self):
        self.assertEqual(sve._skor_degeri({'kural_skoru': 81, 'ai_skor': 70}), 81)
        self.assertEqual(sve._skor_degeri({'ai_skor': 70}), 70)


if __name__ == '__main__':
    unittest.main()
