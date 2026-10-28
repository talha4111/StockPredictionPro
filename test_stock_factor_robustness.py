import unittest

import stock_factor_robustness as robustness


class StockFactorRobustnessTests(unittest.TestCase):
    @staticmethod
    def _period(date, strategy_return, spy_return, equal_weight_return, symbols):
        return {
            "signal_date": date,
            "net_return": strategy_return,
            "spy_return": spy_return,
            "equal_weight_return": equal_weight_return,
            "selected": [{"symbol": symbol} for symbol in symbols],
        }

    def test_period_slices_do_not_mix_development_and_validation(self):
        periods = [
            self._period("2023-12-29", 0.10, 0.02, 0.03, ["A", "B"]),
            self._period("2024-01-31", -0.05, 0.01, 0.00, ["A", "C"]),
        ]

        development = robustness.period_slice_metrics(
            periods, "2021-01-01", "2023-12-31"
        )
        validation = robustness.period_slice_metrics(
            periods, "2024-01-01", "2026-12-31"
        )

        self.assertEqual(development["periods"], 1)
        self.assertAlmostEqual(development["strategy"]["cumulative_return"], 0.10)
        self.assertEqual(validation["periods"], 1)
        self.assertAlmostEqual(validation["strategy"]["cumulative_return"], -0.05)

    def test_concentration_counts_repeated_selections(self):
        periods = [
            self._period("2024-01-31", 0, 0, 0, ["A", "B"]),
            self._period("2024-02-29", 0, 0, 0, ["A", "C"]),
        ]

        result = robustness.selection_concentration(periods)

        self.assertEqual(result["unique_symbols"], 3)
        self.assertEqual(result["most_selected"][0], {"symbol": "A", "months": 2})
        self.assertAlmostEqual(result["top_5_selection_share"], 1.0)


if __name__ == "__main__":
    unittest.main()
