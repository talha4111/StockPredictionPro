import unittest
from pathlib import Path

import pandas as pd

from live_model_compare import LiveModelComparator


class LiveModelComparatorTests(unittest.TestCase):
    def setUp(self):
        self.state_path = Path.cwd() / "test_live_model_compare_state_tmp.json"
        self.temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        self.state_path.unlink(missing_ok=True)
        self.temp_path.unlink(missing_ok=True)

    def tearDown(self):
        self.state_path.unlink(missing_ok=True)
        self.temp_path.unlink(missing_ok=True)

    def _v6_comparator(self):
        return LiveModelComparator(
            self.state_path,
            label_schema_version=6,
            horizon_minutes=60,
            base_timeframe="15m",
            horizon_bars=4,
            notional_usdt=100,
            round_trip_cost_rate=0.001,
            target_min_return=0.0015,
        )

    @staticmethod
    def _epoch(timestamp):
        value = pd.Timestamp(timestamp)
        if value.tzinfo is None:
            value = value.tz_localize("UTC")
        return value.timestamp()

    def test_scores_both_models_on_the_same_price_move(self):
        comparator = LiveModelComparator(
            self.state_path,
            horizon_minutes=1,
            notional_usdt=100,
            round_trip_cost_rate=0.001,
        )
        self.assertTrue(comparator.record_prediction(
            "AAA/USDT", 100, 0.70, 0.45, regime="BULL", now=1000
        ))
        self.assertEqual(1, comparator.settle_due({"AAA/USDT:USDT": 102}, now=1061))

        summary = comparator.summary()
        self.assertEqual(1, summary["models"]["450_8"]["evaluated"])
        self.assertEqual(1.9, summary["models"]["450_8"]["net_pnl"])
        self.assertEqual(0, summary["models"]["400_5"]["signals"])
        self.assertEqual(1, summary["regimes"]["BULL"]["450_8"]["evaluated"])
        self.assertEqual("VERI_BIRIKIYOR", summary["leader"])

    def test_target_threshold_matches_training_label(self):
        comparator = LiveModelComparator(
            self.state_path,
            horizon_minutes=1,
            target_min_return=0.0015,
        )
        self.assertTrue(comparator.record_prediction("AAA/USDT", 100, 0.70, 0.45, now=1000))
        self.assertEqual(1, comparator.settle_due({"AAA/USDT": 100.10}, now=1061))
        self.assertEqual(0, comparator.state["models"]["450_8"]["actual_positives"])

    def test_does_not_overlap_observations_for_the_same_symbol(self):
        comparator = LiveModelComparator(self.state_path, horizon_minutes=1)
        self.assertTrue(comparator.record_prediction("AAAUSDT", 100, 0.60, 0.61, now=1000))
        self.assertFalse(comparator.record_prediction("AAA/USDT", 101, 0.62, 0.63, now=1020))

    def test_no_losing_model_is_declared_the_winner(self):
        comparator = LiveModelComparator(self.state_path, horizon_minutes=1)
        for key in ("450_8", "400_5"):
            comparator.state["models"][key].update({
                "evaluated": 500,
                "actual_positives": 150,
                "signals": 40,
                "brier_sum": 60.0,
                "gross_profit": 4.0,
                "gross_loss": -8.0,
                "net_pnl": -4.0,
            })

        summary = comparator.summary()
        self.assertEqual("BASARISIZ", summary["leader"])
        self.assertEqual([], summary["accepted_models"])

    def test_only_model_passing_absolute_gates_can_lead(self):
        comparator = LiveModelComparator(self.state_path, horizon_minutes=1)
        comparator.state["models"]["450_8"].update({
            "evaluated": 500,
            "actual_positives": 150,
            "signals": 60,
            "wins": 24,
            "brier_sum": 60.0,
            "gross_profit": 10.0,
            "gross_loss": -5.0,
            "net_pnl": 5.0,
        })
        comparator.state["models"]["400_5"].update({
            "evaluated": 500,
            "actual_positives": 150,
            "signals": 60,
            "brier_sum": 90.0,
            "gross_profit": 3.0,
            "gross_loss": -7.0,
            "net_pnl": -4.0,
        })
        comparator.state["regimes"] = {
            regime: {
                "450_8": {
                    "evaluated": 50,
                    "correct": 30,
                    "brier_sum": 10.0,
                    "actual_positives": 25,
                    "signals": 10,
                    "wins": 6,
                    "gross_pnl": 3.0,
                    "gross_profit": 5.0,
                    "gross_loss": -2.0,
                    "cost": 1.0,
                    "net_pnl": 2.0,
                }
            }
            for regime in ("BULL", "YATAY")
        }

        summary = comparator.summary()
        self.assertEqual("450_8", summary["leader"])
        self.assertEqual(["450_8"], summary["accepted_models"])

    def test_positive_pnl_does_not_override_negative_brier_skill(self):
        comparator = LiveModelComparator(self.state_path, horizon_minutes=1)
        for key in ("450_8", "400_5"):
            comparator.state["models"][key].update({
                "evaluated": 500,
                "actual_positives": 150,
                "signals": 60,
                "wins": 24,
                "brier_sum": 130.0,
                "gross_profit": 10.0,
                "gross_loss": -5.0,
                "net_pnl": 5.0,
            })

        summary = comparator.summary()
        self.assertLess(summary["models"]["450_8"]["brier_skill_score"], 0.0)
        self.assertEqual("BASARISIZ", summary["leader"])

    def test_v6_settles_exact_next_open_and_fourth_future_close(self):
        comparator = self._v6_comparator()
        decision = pd.Timestamp("2026-01-01 00:00:00")
        contract_id = comparator.outcome_spec.contract_id
        self.assertTrue(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                regime="BULL",
                now=self._epoch(decision + pd.Timedelta(minutes=15)),
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id=contract_id,
                shadow_outcome_contract_id=contract_id,
            )
        )
        index = pd.date_range(decision, periods=5, freq="15min")
        frame = pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0, 102.0, 103.0],
                "Hedef_Close": [100.0, 101.0, 102.0, 102.5, 103.0],
            },
            index=index,
        )

        self.assertEqual(
            [],
            comparator.due_symbols(
                now=self._epoch(decision + pd.Timedelta(minutes=74))
            ),
        )
        self.assertEqual(
            ["AAA/USDT"],
            comparator.due_symbols(
                now=self._epoch(decision + pd.Timedelta(minutes=75))
            ),
        )
        request = comparator.due_bar_requests(
            now=self._epoch(decision + pd.Timedelta(days=2))
        )["AAA/USDT"]
        self.assertEqual(int(self._epoch(decision) * 1000), request["since_ms"])
        self.assertEqual(6, request["limit"])
        self.assertEqual(
            0,
            comparator.settle_due_bars(
                {"AAA/USDT": frame},
                now=self._epoch(decision + pd.Timedelta(minutes=74)),
            ),
        )
        self.assertEqual(
            1,
            comparator.settle_due_bars(
                {"AAA/USDT": frame},
                now=self._epoch(decision + pd.Timedelta(minutes=75)),
            ),
        )

        result = comparator.state["recent"][-1]
        self.assertEqual(101.0, result["entry_price"])
        self.assertEqual(103.0, result["exit_price"])
        self.assertEqual(1, result["actual"])
        self.assertEqual(60.0, result["hold_minutes"])
        self.assertEqual(contract_id, result["outcome_contract_id"])
        self.assertAlmostEqual(
            1.880198,
            comparator.state["models"]["450_8"]["net_pnl"],
            places=6,
        )

    def test_v6_uses_terminal_outcome_not_early_barrier_touch(self):
        comparator = self._v6_comparator()
        decision = pd.Timestamp("2026-01-01 00:00:00")
        self.assertTrue(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id=comparator.outcome_spec.contract_id,
                shadow_outcome_contract_id=comparator.outcome_spec.contract_id,
            )
        )
        index = pd.date_range(decision, periods=5, freq="15min")
        frame = pd.DataFrame(
            {
                "open": [100.0] * 5,
                "high": [100.0, 100.5, 100.0, 100.0, 100.1],
                "low": [100.0, 99.5, 100.0, 100.0, 99.9],
                "Hedef_Close": [100.0, 100.4, 100.0, 100.0, 100.1],
            },
            index=index,
        )

        self.assertEqual(
            1,
            comparator.settle_due_bars(
                {"AAA/USDT": frame},
                now=self._epoch(decision + pd.Timedelta(minutes=75)),
            ),
        )
        self.assertEqual(0, comparator.state["recent"][-1]["actual"])
        self.assertEqual(
            0,
            comparator.state["models"]["450_8"]["actual_positives"],
        )

    def test_v6_missing_bar_waits_and_ticker_settlement_is_rejected(self):
        comparator = self._v6_comparator()
        decision = pd.Timestamp("2026-01-01 00:00:00")
        self.assertTrue(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id=comparator.outcome_spec.contract_id,
                shadow_outcome_contract_id=comparator.outcome_spec.contract_id,
            )
        )
        index = pd.date_range(decision, periods=5, freq="15min").delete(2)
        frame = pd.DataFrame(
            {
                "open": [100.0] * 4,
                "Hedef_Close": [100.0, 100.2, 100.2, 100.3],
            },
            index=index,
        )

        self.assertEqual(
            0,
            comparator.settle_due_bars(
                {"AAA/USDT": frame},
                now=self._epoch(decision + pd.Timedelta(minutes=90)),
            ),
        )
        self.assertEqual(1, len(comparator.state["pending"]))
        with self.assertRaisesRegex(RuntimeError, "ticker"):
            comparator.settle_due({"AAA/USDT": 100.3})

    def test_v6_pending_survives_restart_and_contract_mismatch_fails(self):
        comparator = self._v6_comparator()
        decision = pd.Timestamp("2026-01-01 00:00:00")
        self.assertFalse(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id="wrong",
                shadow_outcome_contract_id=comparator.outcome_spec.contract_id,
            )
        )
        self.assertFalse(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id=comparator.outcome_spec.contract_id,
                shadow_outcome_contract_id="wrong",
            )
        )
        self.assertTrue(
            comparator.record_prediction(
                "AAA/USDT",
                None,
                0.70,
                0.45,
                decision_bar_open=decision,
                feature_schema_version=6,
                outcome_contract_id=comparator.outcome_spec.contract_id,
                shadow_outcome_contract_id=comparator.outcome_spec.contract_id,
            )
        )

        restarted = self._v6_comparator()
        self.assertEqual(1, len(restarted.state["pending"]))
        self.assertEqual(
            comparator.outcome_spec.contract_id,
            restarted.state["config"]["outcome_contract_id"],
        )

    def test_v6_refuses_to_open_v5_state_file(self):
        v5 = LiveModelComparator(self.state_path, horizon_minutes=1)
        self.assertTrue(
            v5.record_prediction(
                "AAA/USDT",
                100.0,
                0.70,
                0.45,
                now=1000,
            )
        )

        with self.assertRaisesRegex(ValueError, "schema uyumsuz"):
            self._v6_comparator()


if __name__ == "__main__":
    unittest.main()
