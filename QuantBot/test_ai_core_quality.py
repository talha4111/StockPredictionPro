import unittest

import numpy as np
import pandas as pd

from ai_core import BeyinMotoru


class BeyinMotoruQualityTests(unittest.TestCase):
    def test_neutral_future_moves_share_the_no_trade_class(self):
        motor = BeyinMotoru(n_estimators=10, max_depth=2)
        close = pd.Series(
            [100.0, 100.02, 100.04, 100.03, 100.02, 100.8, 99.2, 101.0, 98.8, 101.5, 98.5, 102.0]
        )
        frame = pd.DataFrame({"Close": close})
        prepared = motor.df_hazirla(frame.copy())

        self.assertGreater(len(prepared), 0)
        self.assertFalse(prepared["Hedef_Yön"].isna().any())
        self.assertTrue(
            ((prepared["Gelecek_Ret"] >= motor.min_target_return).astype(int) == prepared["Hedef_Yön"]).all()
        )

    def test_calibration_is_bounded_and_can_shrink_extreme_probabilities(self):
        calibrated = BeyinMotoru._kalibrasyon_uygula([0.01, 0.5, 0.99], 0.5, 0.0)

        self.assertTrue(np.all(calibrated > 0.0))
        self.assertTrue(np.all(calibrated < 1.0))
        self.assertGreater(calibrated[0], 0.01)
        self.assertLess(calibrated[2], 0.99)
        self.assertAlmostEqual(0.5, calibrated[1], places=7)

    def test_strategy_metrics_include_cost_and_skip_overlapping_signals(self):
        motor = BeyinMotoru(n_estimators=10, max_depth=2)
        metrics = motor._strateji_metrikleri(
            probabilities=[0.70] * 8,
            future_returns=[0.01] * 8,
        )

        self.assertEqual(2, metrics["signal_count"])
        self.assertEqual(2, metrics["wins"])
        self.assertAlmostEqual(0.018, metrics["net_return"], places=8)

        already_net = motor._strateji_metrikleri(
            probabilities=[0.70] * 8,
            future_returns=[0.009] * 8,
            returns_are_net=True,
        )
        self.assertAlmostEqual(0.018, already_net["net_return"], places=8)

        stricter = motor._strateji_metrikleri(
            probabilities=[0.70] * 8,
            future_returns=[0.009] * 8,
            returns_are_net=True,
            signal_threshold=0.71,
        )
        self.assertEqual(0, stricter["signal_count"])

    def test_v6_threshold_selection_uses_cv_only(self):
        motor = BeyinMotoru(label_schema_version=6)
        cv_probability = np.array([0.20, 0.25, 0.70, 0.75] * 10)
        cv_targets = np.array([0, 0, 1, 1] * 10)
        cv_returns = np.array([-0.002, -0.001, 0.003, 0.004] * 10)
        holdout_probability = np.array([0.20, 0.70] * 20)
        first = motor._v6_esik_arastirmasi(
            cv_probabilities=cv_probability,
            cv_targets=cv_targets,
            cv_net_returns=cv_returns,
            holdout_probabilities=holdout_probability,
            holdout_targets=np.array([0, 1] * 20),
            holdout_net_returns=np.array([-0.001, 0.003] * 20),
        )
        changed_holdout = motor._v6_esik_arastirmasi(
            cv_probabilities=cv_probability,
            cv_targets=cv_targets,
            cv_net_returns=cv_returns,
            holdout_probabilities=holdout_probability,
            holdout_targets=np.array([1, 0] * 20),
            holdout_net_returns=np.array([0.010, -0.010] * 20),
        )

        self.assertEqual(first["selection_scope"], "cv_oof_only")
        self.assertFalse(first["holdout_used_for_selection"])
        self.assertFalse(first["activated"])
        self.assertEqual(
            first["classification"]["selected_threshold"],
            changed_holdout["classification"]["selected_threshold"],
        )
        self.assertEqual(
            first["signal"]["selected_threshold"],
            changed_holdout["signal"]["selected_threshold"],
        )

    def test_v6_shadow_feature_rule_is_cv_contribution_only(self):
        ranking = [
            {
                "feature": "good_a",
                "mean_brier_increase": 0.01,
                "positive_brier_folds": 2,
                "positive_accuracy_folds": 2,
            },
            {
                "feature": "bad_brier",
                "mean_brier_increase": -0.01,
                "positive_brier_folds": 3,
                "positive_accuracy_folds": 3,
            },
            {
                "feature": "unstable",
                "mean_brier_increase": 0.02,
                "positive_brier_folds": 1,
                "positive_accuracy_folds": 3,
            },
            {
                "feature": "good_b",
                "mean_brier_increase": 0.005,
                "positive_brier_folds": 3,
                "positive_accuracy_folds": 2,
            },
        ]

        selected = BeyinMotoru._v6_shadow_featureleri_sec(ranking)

        self.assertEqual(["good_a", "good_b"], selected)


if __name__ == "__main__":
    unittest.main()
