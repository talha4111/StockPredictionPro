import copy
import json
import unittest
from pathlib import Path

import stock_factor_regime_validation as regime


class StockFactorRegimeValidationTests(unittest.TestCase):
    def setUp(self):
        path = Path("data/stock_factor_regime_manifest.json")
        self.manifest = json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _result(variant_id, regime_id, total_return, drawdown, sharpe):
        return {
            "variant_id": variant_id,
            "regime_id": regime_id,
            "total_return_pct": total_return,
            "max_drawdown_pct": drawdown,
            "sharpe_ratio": sharpe,
        }

    def test_manifest_preregisters_nine_runs(self):
        self.assertEqual(len(regime.expected_run_keys(self.manifest)), 9)
        self.manifest["results"] = []
        decision = regime.evaluate_results(self.manifest)
        self.assertEqual(decision["status"], "AWAITING_CLOUD_RESULTS")
        self.assertEqual(decision["required_runs"], 9)

    def test_candidate_passes_only_when_all_registered_guards_pass(self):
        rows = []
        for index, window in enumerate(self.manifest["regimes"]):
            regime_id = window["id"]
            rows.extend([
                self._result("baseline", regime_id, 10 + index, 12, 0.3),
                self._result("m00_r15", regime_id, 12 + index, 13, 0.4),
                self._result("m10_r15", regime_id, 9 + index, 11, 0.2),
            ])
        self.manifest["results"] = rows

        decision = regime.evaluate_results(self.manifest)

        self.assertEqual(
            decision["status"], "REGIME_ROBUSTNESS_PASS_RESEARCH_ONLY"
        )
        self.assertEqual(decision["recommended_candidate"], "m00_r15")
        self.assertFalse(decision["production_valid"])

    def test_drawdown_guard_blocks_otherwise_winning_candidate(self):
        manifest = copy.deepcopy(self.manifest)
        rows = []
        for window in manifest["regimes"]:
            regime_id = window["id"]
            rows.extend([
                self._result("baseline", regime_id, 10, 10, 0.3),
                self._result("m00_r15", regime_id, 12, 12.1, 0.4),
                self._result("m10_r15", regime_id, 9, 10, 0.2),
            ])
        manifest["results"] = rows

        decision = regime.evaluate_results(manifest)

        self.assertEqual(decision["status"], "MODEL_REVIEW_REQUIRED")
        self.assertIsNone(decision["recommended_candidate"])

    def test_duplicate_result_fails_closed(self):
        row = self._result("baseline", "inflation_rate_stress", 1, 2, 0.1)
        self.manifest["results"] = [row, dict(row)]

        with self.assertRaisesRegex(ValueError, "Duplicate cloud result"):
            regime.evaluate_results(self.manifest)


if __name__ == "__main__":
    unittest.main()
