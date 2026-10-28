import unittest

from promotion_gate import candidate_failure_reasons, evaluate_promotion


class PromotionGateTests(unittest.TestCase):
    def test_blocks_while_observations_are_accumulating(self):
        result = evaluate_promotion({
            "settled": 12,
            "leader": "VERI_BIRIKIYOR",
            "accepted_models": [],
            "positive_regime_counts": {},
            "config": {
                "acceptance": {
                    "min_common_observations": 500,
                    "min_positive_regimes": 2,
                }
            },
        })
        self.assertFalse(result["promotion_ready"])

    def test_allows_only_accepted_leader_with_regime_evidence(self):
        result = evaluate_promotion({
            "settled": 500,
            "leader": "450_8",
            "accepted_models": ["450_8"],
            "positive_regime_counts": {"450_8": 2},
            "config": {
                "acceptance": {
                    "min_common_observations": 500,
                    "min_positive_regimes": 2,
                }
            },
        })
        self.assertTrue(result["promotion_ready"])

    def test_reports_each_failed_absolute_gate_per_candidate(self):
        summary = {
            "positive_regime_counts": {"450_8": 1, "400_5": 2},
            "config": {
                "acceptance": {
                    "min_signals": 50,
                    "min_profit_factor": 1.20,
                    "min_brier_skill": 0.0,
                    "max_brier_score": 0.26,
                    "min_positive_regimes": 2,
                }
            },
            "models": {
                "450_8": {
                    "signals": 20,
                    "net_pnl": -1.25,
                    "profit_factor": 0.70,
                    "brier_score": 0.30,
                    "brier_skill_score": -0.05,
                },
                "400_5": {
                    "signals": 55,
                    "net_pnl": 2.00,
                    "profit_factor": 1.30,
                    "brier_score": 0.20,
                    "brier_skill_score": 0.02,
                },
            },
        }

        failures = candidate_failure_reasons(summary)
        self.assertEqual([], failures["400_5"])
        self.assertIn("sinyal=20<50", failures["450_8"])
        self.assertIn("net_pnl=-1.2500<=0", failures["450_8"])
        self.assertIn("profit_factor=0.7000<1.2000", failures["450_8"])
        self.assertIn("brier_score=0.3000>0.2600", failures["450_8"])
        self.assertIn("brier_skill=-0.0500<=0.0000", failures["450_8"])
        self.assertIn("pozitif_rejim=1<2", failures["450_8"])
