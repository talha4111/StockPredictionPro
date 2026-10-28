import math
import unittest

import stock_value_engine
from quantconnect_top20.factor_core import (
    FACTOR_WEIGHTS,
    metric_percentiles,
    normalize_factor_weights,
    price_features,
    rank_factor_rows,
    select_top,
    target_weights,
)


class QuantConnectFactorCoreTests(unittest.TestCase):
    @staticmethod
    def _row(index, sector="Technology"):
        return {
            "symbol": f"T{index}",
            "sector": sector,
            "roe": 0.05 + index * 0.02,
            "roa": 0.02 + index * 0.01,
            "profit_margin": 0.04 + index * 0.015,
            "gross_margin": 0.20 + index * 0.02,
            "revenue_growth": 0.02 + index * 0.02,
            "earnings_growth": 0.01 + index * 0.025,
            "debt_to_equity": 1.8 - index * 0.15,
            "earnings_yield": 0.02 + index * 0.004,
            "fcf_yield": 0.01 + index * 0.005,
            "dividend_yield": 0.002 + index * 0.001,
            "momentum_12_1": 0.02 + index * 0.04,
            "momentum_6_1": 0.01 + index * 0.025,
            "distance_52w_high": -0.25 + index * 0.025,
            "realized_vol_63d": 0.45 - index * 0.025,
            "downside_vol_63d": 0.35 - index * 0.02,
            "max_drawdown_1y": -0.40 + index * 0.025,
        }

    def test_ranking_matches_factor_direction_and_does_not_mutate_input(self):
        rows = [
            self._row(index, "Technology" if index < 4 else "Energy")
            for index in range(8)
        ]
        original_keys = set(rows[0])
        ranked = rank_factor_rows(rows)

        self.assertEqual(ranked[0]["symbol"], "T7")
        self.assertEqual(set(rows[0]), original_keys)
        self.assertTrue(all(0 <= row["factor_score"] <= 100 for row in ranked))
        self.assertTrue(all(row["factor_coverage"] == 1.0 for row in ranked))

    def test_sector_neutral_percentiles_compare_peers(self):
        rows = [
            {"sector": "Technology", "roe": value} for value in (10, 20, 30, 40)
        ] + [
            {"sector": "Energy", "roe": value} for value in (100, 200, 300, 400)
        ]
        scores = metric_percentiles(rows, "roe", True, True)

        self.assertEqual(scores[0], scores[4])
        self.assertEqual(scores[3], scores[7])
        self.assertEqual(scores[0], 0.0)
        self.assertEqual(scores[3], 100.0)

    def test_cloud_core_scores_match_local_factor_engine(self):
        cloud_rows = [
            self._row(index, "Technology" if index < 4 else "Energy")
            for index in range(8)
        ]
        local_rows = []
        for row in cloud_rows:
            local = dict(row)
            local["sembol"] = local.pop("symbol")
            local["sektor"] = local.pop("sector")
            local_rows.append(local)

        cloud = {row["symbol"]: row for row in rank_factor_rows(cloud_rows)}
        local = {
            row["sembol"]: row
            for row in stock_value_engine.faktor_siralama_uygula(local_rows)
        }
        score_names = {
            "quality_score": "kalite_skor",
            "value_score": "deger_skor",
            "momentum_score": "momentum_skor",
            "risk_score": "risk_skor",
            "factor_score": "faktor_skor",
            "factor_coverage": "faktor_kapsami",
        }
        for symbol in cloud:
            for cloud_name, local_name in score_names.items():
                self.assertEqual(cloud[symbol][cloud_name], local[symbol][local_name])

    def test_missing_factor_coverage_is_ineligible(self):
        rows = [self._row(index) for index in range(5)]
        for metric in (
            "roe", "roa", "profit_margin", "gross_margin", "revenue_growth",
            "earnings_growth", "debt_to_equity", "earnings_yield",
        ):
            rows[0][metric] = None

        ranked = rank_factor_rows(rows)
        damaged = next(row for row in ranked if row["symbol"] == "T0")
        self.assertFalse(damaged["eligible"])
        self.assertLess(damaged["factor_coverage"], 0.75)

    def test_explicit_default_weights_preserve_production_ranking(self):
        rows = [
            self._row(index, "Technology" if index < 4 else "Energy")
            for index in range(8)
        ]

        implicit = rank_factor_rows(rows)
        explicit = rank_factor_rows(rows, FACTOR_WEIGHTS)

        self.assertEqual(implicit, explicit)

    def test_ablation_weights_are_normalized_and_safe(self):
        weights = normalize_factor_weights({
            "quality": 0.35,
            "value": 0.0,
            "momentum": 0.30,
            "risk": 0.15,
        })

        self.assertEqual(weights["value"], 0.0)
        self.assertAlmostEqual(sum(weights.values()), 1.0)
        with self.assertRaises(ValueError):
            normalize_factor_weights({"quality": 0.0})
        with self.assertRaises(ValueError):
            normalize_factor_weights({"quality": -0.1, "momentum": 1.0})
        with self.assertRaises(ValueError):
            normalize_factor_weights({"unknown": 1.0})

    def test_single_factor_research_score_matches_factor_score(self):
        rows = [self._row(index, f"Sector{index}") for index in range(6)]
        ranked = rank_factor_rows(rows, {"quality": 1.0})

        for row in ranked:
            self.assertEqual(row["factor_score"], round(row["quality_score"], 1))

    def test_price_features_use_completed_252_bar_window(self):
        closes = [100.0 + index * 0.2 + math.sin(index / 7.0) for index in range(300)]
        volumes = [1_000_000.0] * 300
        result = price_features(closes, volumes)

        self.assertIsNotNone(result)
        self.assertGreater(result["momentum_12_1"], 0)
        self.assertLessEqual(result["distance_52w_high"], 0)
        self.assertGreater(result["avg_dollar_volume"], 5_000_000)
        self.assertLessEqual(result["max_drawdown_1y"], 0)

    def test_price_features_fail_closed_on_bad_history_or_liquidity(self):
        self.assertIsNone(price_features([100.0] * 251, [1_000_000.0] * 251))
        self.assertIsNone(price_features([1.0] * 252, [100.0] * 252))

    def test_top20_position_and_sector_caps_leave_excess_in_cash(self):
        ranked = []
        for index in range(24):
            row = self._row(index, "Technology" if index < 8 else f"Sector{index // 4}")
            row.update({"eligible": True, "factor_score": 100 - index})
            ranked.append(row)

        selected = select_top(ranked, top_n=20, min_positions=5)
        weights = target_weights(selected, max_position_weight=0.05, sector_cap=0.25)
        technology_weight = sum(
            weights[row["symbol"]] for row in selected if row["sector"] == "Technology"
        )

        self.assertEqual(len(selected), 20)
        self.assertLessEqual(max(weights.values()), 0.05)
        self.assertLessEqual(technology_weight, 0.25)
        self.assertLess(sum(weights.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
