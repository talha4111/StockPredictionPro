import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd
from external_metric_store import ExternalMetricSnapshotStore


class _FakeExchange:
    def load_markets(self):
        return {}


fake_ccxt = types.ModuleType("ccxt")
fake_ccxt.binance = lambda *args, **kwargs: _FakeExchange()
fake_pandas_ta = types.ModuleType("pandas_ta")

sys.modules["ccxt"] = fake_ccxt
sys.modules["pandas_ta"] = fake_pandas_ta

import tarayici


class TarayiciFeatureContractTests(unittest.TestCase):
    def setUp(self):
        self.source_4h = pd.DataFrame(
            {"value": [73.0, 81.0]},
            index=pd.to_datetime(["2026-01-01 08:00", "2026-01-01 12:00"]),
        )
        self.target_15m = pd.date_range(
            "2026-01-01 08:00",
            periods=32,
            freq="15min",
        )

    def test_default_schema_preserves_v5_behavior(self):
        default = tarayici._hizali_feature_serisi(
            self.source_4h,
            "value",
            self.target_15m,
            50.0,
        )
        explicit_v5 = tarayici._hizali_feature_serisi(
            self.source_4h,
            "value",
            self.target_15m,
            50.0,
            source_timeframe="4h",
            feature_schema_version=5,
        )

        pd.testing.assert_series_equal(default, explicit_v5)
        self.assertEqual(73.0, default.loc["2026-01-01 08:00"])

    def test_v6_hides_value_until_4h_bar_is_completed(self):
        v6 = tarayici._hizali_feature_serisi(
            self.source_4h,
            "value",
            self.target_15m,
            50.0,
            source_timeframe="4h",
            feature_schema_version=6,
        )

        self.assertTrue((v6.loc["2026-01-01 08:00":"2026-01-01 11:30"] == 50.0).all())
        self.assertEqual(73.0, v6.loc["2026-01-01 11:45"])
        self.assertEqual(81.0, v6.loc["2026-01-01 15:45"])
        self.assertAlmostEqual(
            17 / 32,
            v6.attrs["coverage_ratio_before_fill"],
        )

    def test_v6_delays_each_source_bar_until_its_own_close(self):
        v5 = tarayici._hizali_feature_serisi(
            self.source_4h,
            "value",
            self.target_15m,
            50.0,
            source_timeframe="4h",
            feature_schema_version=5,
        )
        v6 = tarayici._hizali_feature_serisi(
            self.source_4h,
            "value",
            self.target_15m,
            50.0,
            source_timeframe="4h",
            feature_schema_version=6,
        )

        differing = self.target_15m[v5.to_numpy() != v6.to_numpy()]
        matching = self.target_15m[v5.to_numpy() == v6.to_numpy()]

        self.assertEqual(30, len(differing))
        self.assertEqual(
            [
                pd.Timestamp("2026-01-01 11:45"),
                pd.Timestamp("2026-01-01 15:45"),
            ],
            list(matching),
        )
        self.assertTrue((v5.loc[self.target_15m[:15]] == 73.0).all())
        self.assertTrue((v6.loc[self.target_15m[:15]] == 50.0).all())
        self.assertTrue((v5.loc[self.target_15m[16:31]] == 81.0).all())
        self.assertTrue((v6.loc[self.target_15m[16:31]] == 73.0).all())

    def test_rsi_4h_path_passes_schema_to_shared_aligner(self):
        source_frame = pd.DataFrame(
            {"close": [100.0, 101.0]},
            index=self.source_4h.index,
        )
        rsi = pd.Series([73.0, 81.0], index=self.source_4h.index)
        fake_pandas_ta.rsi = mock.Mock(return_value=rsi)

        with mock.patch.object(
            tarayici,
            "_ccxt_veri_getir",
            return_value=source_frame,
        ):
            aligned = tarayici._rsi_4h_serisi_getir(
                "BTC/USDT",
                self.target_15m,
                feature_schema_version=6,
            )

        self.assertEqual(50.0, aligned.loc["2026-01-01 11:30"])
        self.assertEqual(73.0, aligned.loc["2026-01-01 11:45"])

    def test_v6_requires_source_timeframe_and_unknown_schema_fails(self):
        with self.assertRaises(ValueError):
            tarayici._hizali_feature_serisi(
                self.source_4h,
                "value",
                self.target_15m,
                50.0,
                feature_schema_version=6,
            )
        with self.assertRaises(ValueError):
            tarayici._feature_schema_dogrula(7)

    def test_feature_provenance_identifies_v6_contract(self):
        frame = pd.DataFrame(index=self.target_15m)

        result = tarayici._feature_provenance_ekle(
            frame,
            feature_schema_version=6,
            base_timeframe="15m",
        )

        self.assertIs(result, frame)
        self.assertEqual(result.attrs["feature_schema_version"], 6)
        self.assertEqual(result.attrs["base_timeframe"], "15m")
        self.assertEqual(
            result.attrs["feature_contract_id"],
            tarayici._V6_FEATURE_AVAILABILITY.contract_id,
        )
        self.assertEqual(
            result.attrs["coverage_contract_id"],
            tarayici._V6_FEATURE_COVERAGE.contract_id,
        )
        self.assertEqual({}, result.attrs["feature_quality"])

    def test_external_metric_parser_keeps_real_zero_and_last_duplicate(self):
        rows = [
            {"timestamp": 1767226500000, "openInterestValue": "5.0"},
            {"timestamp": 1767225600000, "openInterestValue": "0"},
            {"timestamp": 1767226500000, "openInterestValue": "7.0"},
            {"timestamp": None, "openInterestValue": "9.0"},
        ]

        result = tarayici._dis_metrik_serisi(
            rows,
            value_columns=("openInterestValue",),
            name="Open_Interest",
        )

        self.assertTrue(result.index.is_monotonic_increasing)
        self.assertEqual([0.0, 7.0], result.tolist())
        self.assertEqual("Open_Interest", result.name)

    def test_external_metric_pagination_advances_and_deduplicates(self):
        rows = [
            {"timestamp": 1000, "openInterestValue": "1"},
            {"timestamp": 2000, "openInterestValue": "2"},
            {"timestamp": 3000, "openInterestValue": "3"},
        ]
        cursors = []

        def fetch_page(cursor, limit):
            cursors.append(cursor)
            return [
                row for row in rows if row["timestamp"] >= cursor
            ][:limit]

        result, status = tarayici._sayfali_dis_metrik_getir(
            fetch_page,
            since_ms=1000,
            until_ms=3000,
            page_limit=2,
            max_calls=4,
            value_columns=("openInterestValue",),
            name="Open_Interest",
        )

        self.assertEqual([1000, 2001], cursors)
        self.assertEqual([1.0, 2.0, 3.0], result.tolist())
        self.assertEqual(2, status["calls"])
        self.assertTrue(status["completed"])
        self.assertIsNone(status["last_error"])

    def test_external_metric_pagination_is_bounded_on_non_progress(self):
        def fetch_page(_cursor, _limit):
            return [{"timestamp": 1000, "fundingRate": "0.001"}]

        _, status = tarayici._sayfali_dis_metrik_getir(
            fetch_page,
            since_ms=1000,
            until_ms=5000,
            page_limit=1,
            max_calls=10,
            value_columns=("fundingRate",),
            name="Funding_Rate",
        )

        self.assertEqual(2, status["calls"])
        self.assertFalse(status["completed"])
        self.assertIn("ilerlemedi", status["last_error"])

    def test_open_interest_retention_uses_safe_29_day_floor(self):
        target = pd.date_range(
            "2026-01-01 00:00",
            periods=(40 * 24 * 4),
            freq="15min",
        )

        class Exchange:
            def __init__(self):
                self.since_values = []

            def fetch_open_interest_history(
                self,
                _symbol,
                timeframe,
                since,
                limit,
            ):
                self.since_values.append(since)
                return []

        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        store_root = Path(__file__).parent
        store = ExternalMetricSnapshotStore(store_root)
        snapshot_path = store.path_for(symbol, "open_interest", "15m")
        try:
            exchange = Exchange()
            _, metadata = tarayici._v6_dis_metrik_gecmisi(
                symbol,
                target,
                metric="open_interest",
                timeframe="15m",
                exchange=exchange,
                store=store,
            )
        finally:
            snapshot_path.unlink(missing_ok=True)

        until_ms = int(
            (target[-1] + pd.Timedelta(minutes=15)).value // 1_000_000
        )
        expected_floor = until_ms - (29 * 24 * 60 * 60 * 1000)
        self.assertEqual([expected_floor], exchange.since_values)
        self.assertEqual(expected_floor, metadata["effective_since_ms"])

    def test_v6_metric_history_resumes_from_snapshot_without_refetch(self):
        target = pd.date_range(
            "2026-01-01 00:00",
            periods=4,
            freq="15min",
        )
        records = [
            {
                "timestamp": int(
                    (timestamp + pd.Timedelta(minutes=15)).value
                    // 1_000_000
                ),
                "openInterestValue": str(value),
            }
            for timestamp, value in zip(target, (1.0, 2.0, 3.0, 4.0))
        ]

        class Exchange:
            def __init__(self):
                self.calls = []

            def fetch_open_interest_history(
                self,
                symbol,
                timeframe,
                since,
                limit,
            ):
                self.calls.append((symbol, timeframe, since, limit))
                return [
                    row for row in records if row["timestamp"] >= since
                ][:limit]

        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        store_root = Path(__file__).parent
        snapshot_path = ExternalMetricSnapshotStore(store_root).path_for(
            symbol,
            "open_interest",
            "15m",
        )
        try:
            exchange = Exchange()
            first_store = ExternalMetricSnapshotStore(store_root)
            first, first_meta = tarayici._v6_dis_metrik_gecmisi(
                symbol,
                target,
                metric="open_interest",
                timeframe="15m",
                exchange=exchange,
                store=first_store,
            )
            restarted_store = ExternalMetricSnapshotStore(store_root)
            second, second_meta = tarayici._v6_dis_metrik_gecmisi(
                symbol,
                target,
                metric="open_interest",
                timeframe="15m",
                exchange=exchange,
                store=restarted_store,
            )
        finally:
            snapshot_path.unlink(missing_ok=True)

        self.assertEqual(1, len(exchange.calls))
        pd.testing.assert_series_equal(first, second)
        self.assertTrue(first_meta["snapshot_saved"])
        self.assertTrue(second_meta["snapshot_saved"])
        self.assertEqual(4, second_meta["cached_records"])

    def test_v6_metric_history_persists_partial_page_and_resumes(self):
        target = pd.date_range(
            "2026-01-01 00:00",
            periods=600,
            freq="15min",
        )
        records = [
            {
                "timestamp": int(
                    (timestamp + pd.Timedelta(minutes=15)).value
                    // 1_000_000
                ),
                "openInterestValue": str(position),
            }
            for position, timestamp in enumerate(target, start=1)
        ]

        class FirstExchange:
            def __init__(self):
                self.calls = 0

            def fetch_open_interest_history(
                self,
                _symbol,
                timeframe,
                since,
                limit,
            ):
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("temporary API error")
                return [
                    row for row in records if row["timestamp"] >= since
                ][:limit]

        class RestartedExchange:
            def __init__(self):
                self.since_values = []

            def fetch_open_interest_history(
                self,
                _symbol,
                timeframe,
                since,
                limit,
            ):
                self.since_values.append(since)
                return [
                    row for row in records if row["timestamp"] >= since
                ][:limit]

        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        store_root = Path(__file__).parent
        snapshot_path = ExternalMetricSnapshotStore(store_root).path_for(
            symbol,
            "open_interest",
            "15m",
        )
        try:
            first_exchange = FirstExchange()
            partial, partial_meta = tarayici._v6_dis_metrik_gecmisi(
                symbol,
                target,
                metric="open_interest",
                timeframe="15m",
                exchange=first_exchange,
                store=ExternalMetricSnapshotStore(store_root),
            )
            restarted_exchange = RestartedExchange()
            completed, completed_meta = tarayici._v6_dis_metrik_gecmisi(
                symbol,
                target,
                metric="open_interest",
                timeframe="15m",
                exchange=restarted_exchange,
                store=ExternalMetricSnapshotStore(store_root),
            )
        finally:
            snapshot_path.unlink(missing_ok=True)

        self.assertEqual(500, len(partial))
        self.assertIn("temporary API error", partial_meta["last_error"])
        self.assertTrue(partial_meta["snapshot_saved"])
        self.assertEqual(600, len(completed))
        self.assertEqual(1, len(restarted_exchange.since_values))
        self.assertEqual(
            records[499]["timestamp"] + 1,
            restarted_exchange.since_values[0],
        )
        self.assertTrue(completed_meta["pagination_complete"])


if __name__ == "__main__":
    unittest.main()
