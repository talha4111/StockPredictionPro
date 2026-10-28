import unittest

import pandas as pd

from model_contract import (
    FeatureAvailabilitySpec,
    FeatureCoverageSpec,
    OutcomeSpec,
    PurgedWalkForwardSpec,
    timeframe_delta,
)


class FeatureCoverageSpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = FeatureCoverageSpec(
            recent_window_bars=2,
            min_total_coverage_ratio=0.50,
            min_recent_coverage_ratio=1.0,
            min_joint_available_bars=3,
        )

    def test_baseline_zero_is_distinct_from_a_real_zero_observation(self):
        target = pd.date_range("2026-01-01 00:00", periods=4, freq="15min")
        source = pd.Series(
            [0.0, 5.0],
            index=pd.to_datetime(["2026-01-01 00:30", "2026-01-01 00:45"]),
        )

        aligned = self.spec.align_observations(
            source,
            target,
            feature_name="Open_Interest",
            max_staleness_bars=2,
            baseline_value=0.0,
        )

        self.assertEqual(0.0, aligned.iloc[0]["Open_Interest"])
        self.assertEqual(0, aligned.iloc[0]["Open_Interest_Available"])
        self.assertEqual(0.0, aligned.iloc[1]["Open_Interest"])
        self.assertEqual(1, aligned.iloc[1]["Open_Interest_Available"])
        self.assertEqual(1, aligned.iloc[1]["Open_Interest_Observed"])
        self.assertEqual(1, aligned.attrs["quality_report"]["real_zero_count"])

    def test_stale_observation_becomes_unavailable_after_max_age(self):
        target = pd.date_range("2026-01-01 00:00", periods=5, freq="15min")
        source = pd.Series(
            [7.0],
            index=pd.to_datetime(["2026-01-01 00:15"]),
        )

        aligned = self.spec.align_observations(
            source,
            target,
            feature_name="Open_Interest",
            max_staleness_bars=2,
            baseline_value=0.0,
        )

        self.assertEqual([1, 1, 1, 0, 0], aligned["Open_Interest_Available"].tolist())
        self.assertEqual([0.0, 1.0, 2.0, 3.0, 4.0], aligned["Open_Interest_Age_Bars"].tolist())
        with self.assertRaisesRegex(ValueError, "recent coverage"):
            self.spec.validate_report(aligned.attrs["quality_report"])

    def test_report_validation_fails_closed_for_nan_and_low_coverage(self):
        report = {
            "feature": "Funding_Rate",
            "target_rows": 100,
            "coverage_ratio": float("nan"),
            "recent_coverage_ratio": 1.0,
            "latest_available": True,
        }
        with self.assertRaisesRegex(ValueError, "geçersiz"):
            self.spec.validate_report(report)

        report["coverage_ratio"] = 0.49
        with self.assertRaisesRegex(ValueError, "toplam coverage"):
            self.spec.validate_report(report)

    def test_report_must_match_the_actual_availability_mask(self):
        frame = pd.DataFrame(
            {"Open_Interest_Available": [1, 0, 1, 1]},
        )
        report = {
            "feature": "Open_Interest",
            "target_rows": 4,
            "coverage_ratio": 1.0,
            "recent_coverage_ratio": 1.0,
            "latest_available": True,
        }

        with self.assertRaisesRegex(ValueError, "maskesi uyuşmuyor"):
            self.spec.validate_frame_report(
                frame,
                feature_name="Open_Interest",
                report=report,
            )

    def test_contract_identity_is_stable_and_parameter_sensitive(self):
        same = FeatureCoverageSpec(
            recent_window_bars=2,
            min_total_coverage_ratio=0.50,
            min_recent_coverage_ratio=1.0,
            min_joint_available_bars=3,
        )
        changed = FeatureCoverageSpec(recent_window_bars=3)

        self.assertEqual(self.spec.contract_id, same.contract_id)
        self.assertNotEqual(self.spec.contract_id, changed.contract_id)
        self.assertEqual(64, len(self.spec.contract_id))


class FeatureAvailabilitySpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = FeatureAvailabilitySpec(base_timeframe="15m")

    def test_four_hour_value_is_hidden_until_source_bar_closes(self):
        source = pd.Series(
            [73.0, 81.0],
            index=pd.to_datetime(["2026-01-01 08:00", "2026-01-01 12:00"]),
            name="RSI_4H",
        )
        target = pd.date_range("2026-01-01 08:00", periods=32, freq="15min")

        aligned = self.spec.align_completed_feature(
            source,
            target,
            source_timeframe="4h",
        )

        self.assertTrue(aligned.loc["2026-01-01 08:00":"2026-01-01 11:30"].isna().all())
        self.assertEqual(73.0, aligned.loc["2026-01-01 11:45"])
        self.assertEqual(73.0, aligned.loc["2026-01-01 15:30"])
        self.assertEqual(81.0, aligned.loc["2026-01-01 15:45"])

    def test_one_hour_value_is_not_exposed_to_first_three_quarter_hours(self):
        source = pd.Series(
            [55.0],
            index=pd.to_datetime(["2026-01-01 10:00"]),
            name="RSI_1H",
        )
        target = pd.date_range("2026-01-01 10:00", periods=4, freq="15min")

        aligned = self.spec.align_completed_feature(
            source,
            target,
            source_timeframe="1h",
        )

        self.assertTrue(aligned.iloc[:3].isna().all())
        self.assertEqual(55.0, aligned.iloc[3])
        self.assertAlmostEqual(0.25, aligned.attrs["coverage_ratio_before_fill"])

    def test_fill_value_does_not_change_pre_fill_coverage(self):
        source = pd.Series(
            [55.0],
            index=pd.to_datetime(["2026-01-01 10:00"]),
        )
        target = pd.date_range("2026-01-01 10:00", periods=4, freq="15min")

        aligned = self.spec.align_completed_feature(
            source,
            target,
            source_timeframe="1h",
            fill_value=50.0,
        )

        self.assertFalse(aligned.isna().any())
        self.assertAlmostEqual(0.25, aligned.attrs["coverage_ratio_before_fill"])
        self.assertEqual(50.0, aligned.iloc[0])

    def test_invalid_or_unsorted_time_contract_fails_closed(self):
        with self.assertRaises(ValueError):
            timeframe_delta("90x")
        source = pd.Series(
            [1.0, 2.0],
            index=pd.to_datetime(["2026-01-01 11:00", "2026-01-01 10:00"]),
        )
        with self.assertRaises(ValueError):
            self.spec.align_completed_feature(
                source,
                pd.date_range("2026-01-01 10:00", periods=2, freq="15min"),
                source_timeframe="1h",
            )


class OutcomeSpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = OutcomeSpec(
            horizon_bars=4,
            round_trip_cost_rate=0.001,
            minimum_edge_rate=0.0005,
        )

    def test_threshold_matches_cost_plus_minimum_edge(self):
        self.assertAlmostEqual(0.0015, self.spec.positive_gross_return_threshold)
        self.assertEqual(1, self.spec.classify_long(100.0, 100.15))
        self.assertEqual(0, self.spec.classify_long(100.0, 100.149))

    def test_outcome_uses_next_bar_open_and_fixed_horizon_close(self):
        index = pd.date_range("2026-01-01 00:00", periods=7, freq="15min")
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0],
                "Hedef_Close": [100.0, 100.5, 101.0, 102.0, 103.0, 104.0, 105.0],
            },
            index=index,
        )

        outcomes = self.spec.build_long_outcomes(frame)

        self.assertEqual(101.0, outcomes.iloc[0]["entry_price"])
        self.assertEqual(103.0, outcomes.iloc[0]["exit_price"])
        self.assertEqual(1, outcomes.iloc[0]["y_long"])
        self.assertEqual(3, outcomes["y_long"].notna().sum())
        self.assertTrue(outcomes["y_long"].tail(4).isna().all())

    def test_neutral_and_negative_rows_are_preserved_as_zero(self):
        index = pd.date_range("2026-01-01 00:00", periods=6, freq="15min")
        frame = pd.DataFrame(
            {
                "open": [100.0] * 6,
                "Hedef_Close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            },
            index=index,
        )
        spec = OutcomeSpec(horizon_bars=2)

        outcomes = spec.build_long_outcomes(frame)

        self.assertEqual([0, 0, 0, 0], outcomes["y_long"].dropna().astype(int).tolist())
        self.assertEqual(4, outcomes["y_long"].notna().sum())

    def test_contract_identity_is_stable_and_parameter_sensitive(self):
        same = OutcomeSpec(
            horizon_bars=4,
            round_trip_cost_rate=0.001,
            minimum_edge_rate=0.0005,
        )
        changed = OutcomeSpec(
            horizon_bars=8,
            round_trip_cost_rate=0.001,
            minimum_edge_rate=0.0005,
        )

        self.assertEqual(self.spec.contract_id, same.contract_id)
        self.assertNotEqual(self.spec.contract_id, changed.contract_id)
        self.assertEqual(64, len(self.spec.contract_id))


class PurgedWalkForwardSpecTests(unittest.TestCase):
    def setUp(self):
        self.spec = PurgedWalkForwardSpec(
            horizon_bars=4,
            purge_bars=4,
            embargo_bars=1,
            n_splits=3,
            min_train_bars=100,
            min_train_fraction=0.40,
            min_validation_bars=20,
        )
        self.index = pd.date_range(
            "2026-01-01",
            periods=500,
            freq="15min",
        )

    def test_holdout_boundary_purges_every_overlapping_label(self):
        fold = self.spec.holdout_split(self.index, holdout_bars=84)

        self.assertEqual(412, len(fold.train_index))
        self.assertEqual(4, len(fold.purge_index))
        self.assertEqual(84, len(fold.validation_index))
        self.assertEqual(0, len(fold.embargo_index))
        self.assertLess(
            self.spec.label_end_times(fold.train_index[-1:])[0],
            self.spec.decision_times(fold.validation_index[:1])[0],
        )

    def test_walk_forward_folds_expand_and_record_embargo(self):
        holdout = self.spec.holdout_split(self.index, holdout_bars=84)
        folds = self.spec.walk_forward_splits(holdout.train_index)

        self.assertEqual(3, len(folds))
        self.assertEqual([166, 247, 328], [len(f.train_index) for f in folds])
        self.assertEqual([4, 4, 4], [len(f.purge_index) for f in folds])
        self.assertEqual([80, 80, 80], [len(f.validation_index) for f in folds])
        self.assertEqual([1, 1, 0], [len(f.embargo_index) for f in folds])
        for fold in folds:
            self.assertLess(
                self.spec.label_end_times(fold.train_index[-1:])[0],
                self.spec.decision_times(fold.validation_index[:1])[0],
            )

    def test_irregular_timeline_and_short_purge_fail_closed(self):
        irregular = self.index.delete(150)
        with self.assertRaisesRegex(ValueError, "kesintisiz 15m"):
            self.spec.walk_forward_splits(irregular)
        with self.assertRaisesRegex(ValueError, "etiket ufkundan kısa"):
            PurgedWalkForwardSpec(horizon_bars=4, purge_bars=3)

    def test_split_contract_identity_is_stable(self):
        same = PurgedWalkForwardSpec()
        changed = PurgedWalkForwardSpec(embargo_bars=2)
        changed_fraction = PurgedWalkForwardSpec(min_train_fraction=0.50)

        self.assertEqual(self.spec.contract_id, same.contract_id)
        self.assertNotEqual(self.spec.contract_id, changed.contract_id)
        self.assertNotEqual(
            self.spec.contract_id,
            changed_fraction.contract_id,
        )
        self.assertEqual(64, len(self.spec.contract_id))


if __name__ == "__main__":
    unittest.main()
