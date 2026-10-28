from __future__ import annotations

import sys
import unittest
from pathlib import Path

from ab_test_status import build_report


ROOT = Path(__file__).resolve().parent
QUANTBOT_DIR = ROOT / "QuantBot"
if str(QUANTBOT_DIR) not in sys.path:
    sys.path.insert(0, str(QUANTBOT_DIR))

from offline_ab_compare import aggregate, parse_symbols  # noqa: E402


class AbStatusTests(unittest.TestCase):
    def test_report_requires_observation_and_signal_thresholds(self):
        model = {
            "evaluated": 300,
            "signals": 30,
            "wins": 18,
            "gross_profit": 4.0,
            "gross_loss": -2.0,
            "net_pnl": 1.5,
            "cost": 3.0,
            "brier_sum": 60.0,
        }
        state = {
            "schema": 2,
            "started_at": 1000.0,
            "pending": {"BTC/USDT": {}},
            "models": {"450_8": dict(model), "400_5": dict(model)},
        }
        report = build_report(state, {}, service="active", now=8200.0)
        self.assertTrue(report["ready_for_decision"])
        self.assertEqual(report["settled"], 300)
        self.assertEqual(report["pending"], 1)
        self.assertEqual(report["models"]["450_8"]["brier_score"], 0.2)
        self.assertEqual(report["models"]["450_8"]["profit_factor"], 2.0)

    def test_report_uses_lower_common_evaluated_count(self):
        state = {
            "started_at": 0.0,
            "pending": {},
            "models": {
                "450_8": {"evaluated": 320, "signals": 35},
                "400_5": {"evaluated": 299, "signals": 35},
            },
        }
        report = build_report(state, {}, service="active", now=3600.0)
        self.assertEqual(report["settled"], 299)
        self.assertFalse(report["ready_for_decision"])


class OfflineAbTests(unittest.TestCase):
    def test_symbol_parser_normalizes_and_deduplicates(self):
        self.assertEqual(
            parse_symbols("btcusdt, ETH/USDT;BTC/USDT:USDT"),
            ["BTC/USDT", "ETH/USDT"],
        )

    def test_aggregate_ranks_net_result_first(self):
        base = {
            "holdout_rows": 200,
            "signals": 10,
            "wins": 5,
            "brier_score": 0.22,
            "balanced_accuracy": 0.55,
            "max_drawdown": 0.02,
            "walk_forward_score": 0.53,
        }
        rows = [
            {**base, "candidate": "450_8", "net_pnl_usdt": 1.0},
            {**base, "candidate": "400_5", "net_pnl_usdt": 2.0},
        ]
        summary = aggregate(rows)
        self.assertEqual(summary[0]["candidate"], "400_5")
        self.assertEqual(summary[0]["rank"], 1)
        self.assertEqual(summary[0]["signals"], 10)


if __name__ == "__main__":
    unittest.main()
