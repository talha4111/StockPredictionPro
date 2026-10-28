import unittest

import pandas as pd

from regime_horizon_baseline import (
    future_return_next_open,
    non_overlapping_metrics,
)


class RegimeHorizonBaselineTests(unittest.TestCase):
    def test_return_uses_next_open_and_fixed_horizon_close(self):
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 103.0, 104.0],
                "Hedef_Close": [100.0, 100.5, 103.0, 104.0, 105.0],
            }
        )
        returns = future_return_next_open(frame, 2)
        self.assertAlmostEqual((103.0 / 101.0) - 1.0, returns.iloc[0])
        self.assertTrue(pd.isna(returns.iloc[-2]))

    def test_non_overlapping_metrics_charges_cost_once_per_trade(self):
        signals = pd.Series([True, True, True, True, True, True])
        returns = pd.Series([0.02, 0.02, 0.02, 0.02, float("nan"), float("nan")])
        result = non_overlapping_metrics(
            signals,
            returns,
            horizon_bars=2,
            cost_rate=0.001,
        )
        self.assertEqual(2, result["signals"])
        self.assertEqual(2, result["wins"])
        self.assertAlmostEqual((1.019 * 1.019) - 1.0, result["net_return"])
