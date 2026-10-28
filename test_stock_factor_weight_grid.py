import unittest

import pandas as pd

import stock_factor_weight_grid as grid


class StockFactorWeightGridTests(unittest.TestCase):
    @staticmethod
    def _result(returns):
        dates = pd.date_range("2021-01-31", periods=len(returns), freq="ME")
        return {
            "periods": [
                {
                    "signal_date": date.date().isoformat(),
                    "net_return": value,
                    "spy_return": 0.005 if index % 3 else -0.004,
                    "equal_weight_return": 0.004,
                    "selected": [],
                }
                for index, (date, value) in enumerate(zip(dates, returns))
            ]
        }

    def test_grid_contains_nine_declared_candidates(self):
        candidates = grid.candidate_specs()

        self.assertEqual(len(candidates), 9)
        self.assertEqual({row["momentum"] for row in candidates}, {0.0, 0.1, 0.2})
        self.assertEqual({row["risk"] for row in candidates}, {0.05, 0.1, 0.15})

    def test_rolling_selection_uses_training_months_not_future_returns(self):
        candidate_a = [0.020, 0.010] * 12 + [-0.020, -0.010] * 3
        candidate_b = [0.010, 0.004] * 12 + [0.080, 0.040] * 3
        baseline = [0.006, 0.003] * 15

        result = grid.rolling_weight_selection(
            {
                "a": self._result(candidate_a),
                "b": self._result(candidate_b),
            },
            self._result(baseline),
            train_months=24,
            test_months=6,
        )

        self.assertEqual(len(result["folds"]), 1)
        self.assertEqual(result["folds"][0]["selected_variant"], "a")
        self.assertLess(
            result["stitched_out_of_sample"]["strategy"]["cumulative_return"],
            0.0,
        )

    def test_risk_adjusted_objective_requires_a_full_year(self):
        short = grid._portfolio_metrics([0.01, -0.005] * 5)
        full = grid._portfolio_metrics([0.01, -0.005] * 6)

        self.assertIsNone(grid.risk_adjusted_objective(short))
        self.assertIsNotNone(grid.risk_adjusted_objective(full))


if __name__ == "__main__":
    unittest.main()
