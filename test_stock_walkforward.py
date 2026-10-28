import unittest

import numpy as np
import pandas as pd

import stock_walkforward as walkforward


class StockWalkForwardTests(unittest.TestCase):
    @staticmethod
    def _history(multiplier=1.0, periods=620):
        dates = pd.bdate_range("2022-01-03", periods=periods)
        trend = np.linspace(80.0, 180.0 * multiplier, periods)
        cycle = np.sin(np.arange(periods) / 9.0) * 5.0
        close = trend + cycle
        return pd.DataFrame(
            {
                "Open": close * 0.999,
                "High": close * 1.01,
                "Low": close * 0.99,
                "Close": close,
                "Volume": np.full(periods, 2_000_000.0),
            },
            index=dates,
        )

    def test_features_never_read_rows_after_signal_date(self):
        history = self._history()
        signal_date = history.index[400]
        original = walkforward.price_features_as_of("AAA", "Tech", history, signal_date)

        changed = history.copy()
        changed.loc[changed.index > signal_date, ["Open", "High", "Low", "Close"]] *= 100
        repeated = walkforward.price_features_as_of("AAA", "Tech", changed, signal_date)

        self.assertIsNotNone(original)
        self.assertEqual(original, repeated)

    def test_point_in_time_contracts_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "temel veri"):
            walkforward.WalkForwardConfig(
                start_date="2024-01-01",
                strategy_mode="full_factor",
                fundamental_mode="point_in_time",
            ).validate(None, None)

        with self.assertRaisesRegex(ValueError, "evren"):
            walkforward.WalkForwardConfig(
                start_date="2024-01-01",
                universe_mode="point_in_time",
            ).validate(None, None)

    def test_turnover_includes_cash_and_replacement(self):
        self.assertAlmostEqual(walkforward._turnover({}, {"AAA": 1.0}), 1.0)
        self.assertAlmostEqual(walkforward._turnover({"AAA": 1.0}, {"AAA": 1.0}), 0.0)
        self.assertAlmostEqual(walkforward._turnover({"AAA": 1.0}, {"BBB": 1.0}), 1.0)

    def test_walk_forward_reports_costs_and_benchmarks(self):
        histories = {
            "AAA": self._history(1.00),
            "BBB": self._history(1.05),
            "CCC": self._history(1.10),
            "DDD": self._history(1.15),
            "EEE": self._history(1.20),
            "FFF": self._history(1.25),
        }
        sectors = {
            "AAA": "Tech", "BBB": "Tech",
            "CCC": "Health", "DDD": "Health",
            "EEE": "Energy", "FFF": "Industry",
        }
        benchmark = self._history(0.95)
        config = walkforward.WalkForwardConfig(
            start_date="2023-06-01",
            end_date="2024-04-30",
            top_n=4,
            min_positions=2,
            sector_cap=0.50,
            max_position_weight=0.30,
            transaction_cost_bps=10,
        )

        result = walkforward.run_walk_forward(histories, sectors, benchmark, config)

        self.assertEqual(result["validity"]["classification"], "DIAGNOSTIC_ONLY")
        self.assertFalse(result["validity"]["production_valid"])
        self.assertGreater(result["data_quality"]["completed_periods"], 3)
        self.assertIn("spy", result["metrics"])
        self.assertIn("equal_weight_universe", result["metrics"])
        self.assertIn("strategy_before_costs", result["metrics"])
        self.assertGreater(len(result["annual_summary"]), 0)
        first = result["periods"][0]
        self.assertGreater(first["turnover"], 0.0)
        self.assertGreater(first["transaction_cost"], 0.0)
        self.assertLessEqual(first["net_return"], first["gross_return"])
        self.assertLess(first["signal_date"], first["entry_date"])

    def test_sector_and_position_caps_leave_excess_as_cash(self):
        selected = [
            {"sembol": "A", "sektor": "Tech"},
            {"sembol": "B", "sektor": "Tech"},
            {"sembol": "C", "sektor": "Tech"},
            {"sembol": "D", "sektor": "Health"},
        ]
        config = walkforward.WalkForwardConfig(
            start_date="2024-01-01",
            top_n=4,
            min_positions=2,
            sector_cap=0.40,
            max_position_weight=0.30,
        )
        weights = walkforward._target_weights(selected, config)

        self.assertLessEqual(sum(weights[symbol] for symbol in ("A", "B", "C")), 0.40)
        self.assertLessEqual(max(weights.values()), 0.30)
        self.assertLess(sum(weights.values()), 1.0)

    def test_factor_weights_and_cash_buffer_are_explicit_research_parameters(self):
        config = walkforward.WalkForwardConfig(
            start_date="2024-01-01",
            min_positions=2,
            cash_buffer=0.005,
            quality_weight=0.35,
            value_weight=0.20,
            momentum_weight=0.0,
            risk_weight=0.05,
        )
        normalized = config.normalized_factor_weights()
        selected = [
            {"sembol": "A", "sektor": "Tech"},
            {"sembol": "B", "sektor": "Health"},
        ]
        weights = walkforward._target_weights(selected, config)

        self.assertAlmostEqual(sum(normalized.values()), 1.0)
        self.assertEqual(normalized["momentum"], 0.0)
        self.assertAlmostEqual(sum(weights.values()), 0.199)
        with self.assertRaises(ValueError):
            walkforward.WalkForwardConfig(
                start_date="2024-01-01", risk_weight=-0.1
            ).validate(None, None)

    def test_full_factor_mode_records_point_in_time_coverage(self):
        histories = {
            symbol: self._history(1.0 + index * 0.05)
            for index, symbol in enumerate(("AAA", "BBB", "CCC", "DDD", "EEE", "FFF"))
        }
        sectors = {
            "AAA": "Tech", "BBB": "Tech", "CCC": "Health",
            "DDD": "Health", "EEE": "Energy", "FFF": "Industry",
        }

        def fundamentals(signal_date, symbols):
            return {
                symbol: {
                    "roe": 0.10 + index * 0.02,
                    "roa": 0.05 + index * 0.01,
                    "profit_margin": 0.08 + index * 0.01,
                    "gross_margin": 0.30 + index * 0.02,
                    "revenue_growth": 0.05 + index * 0.02,
                    "earnings_growth": 0.04 + index * 0.02,
                    "debt_to_equity": 100.0 - index * 5.0,
                    "earnings_yield": 0.03 + index * 0.005,
                    "fcf_yield": 0.02 + index * 0.005,
                    "dividend_yield": 0.005 + index * 0.001,
                    "sec_metric_count": 10,
                    "sec_data_status": "OK",
                }
                for index, symbol in enumerate(symbols)
            }

        config = walkforward.WalkForwardConfig(
            start_date="2023-06-01",
            end_date="2024-04-30",
            top_n=4,
            min_positions=1,
            sector_cap=0.50,
            max_position_weight=0.30,
            strategy_mode="full_factor",
            fundamental_mode="point_in_time",
        )
        result = walkforward.run_walk_forward(
            histories,
            sectors,
            self._history(0.95),
            config,
            fundamental_provider=fundamentals,
        )

        coverage = result["data_quality"]["fundamental_coverage"]
        self.assertGreater(coverage["periods"], 0)
        self.assertEqual(coverage["average_metric_count"], 10.0)
        self.assertTrue(result["validity"]["point_in_time_fundamentals"])
        self.assertFalse(result["validity"]["production_valid"])
        self.assertEqual(result["config"]["resolved_selection_policy"], "factor_rank")
        self.assertIn("average_rank_ic", result["metrics"]["ranking_diagnostics"])
        selected_scores = [row["score"] for row in result["periods"][0]["selected"]]
        self.assertEqual(selected_scores, sorted(selected_scores, reverse=True))

    def test_low_observed_fundamental_coverage_revokes_production_label(self):
        config = walkforward.WalkForwardConfig(
            start_date="2024-01-01",
            strategy_mode="full_factor",
            fundamental_mode="point_in_time",
            universe_mode="point_in_time",
            selection_policy="factor_rank",
        )
        initial = {
            "classification": "PRODUCTION_VALIDATION",
            "production_valid": True,
            "warnings": [],
        }
        result = walkforward._apply_observed_coverage_validity(
            initial,
            config,
            [{"requested": 100, "ok": 84}],
        )

        self.assertFalse(result["production_valid"])
        self.assertEqual(result["classification"], "DIAGNOSTIC_ONLY")
        self.assertEqual(result["observed_fundamental_ok_ratio"], 0.84)


if __name__ == "__main__":
    unittest.main()
