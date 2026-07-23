import json
import sqlite3
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import stock_shadow_paper as shadow
import stock_value_engine as engine


class StockShadowPaperTests(unittest.TestCase):
    def setUp(self):
        self.db_file = Path(__file__).resolve().parent / ".test_stock_shadow.db"
        self.db_file.unlink(missing_ok=True)

    def tearDown(self):
        self.db_file.unlink(missing_ok=True)

    @staticmethod
    def _ranked_row(index, score=None):
        return {
            "sembol": f"T{index:02d}",
            "sektor": "Technology" if index < 8 else f"Sector{index // 4}",
            "fiyat": 100.0 + index,
            "sma_200": 90.0,
            "rsi": 55.0,
            "teknik_skor": score if score is not None else 100.0 - index,
            "faktor_skor": score if score is not None else 100.0 - index,
            "faktor_kapsami": 1.0,
            "tp": 120.0,
            "sl": 90.0,
            "golden_cross": True,
            "rs_skor": 60.0,
            "veri_tarihi": "2026-07-21",
            "veri_durumu": "OK",
            "kurulum": "IZLE",
            "karar": "IZLE",
            "kalite_skor": 70.0,
            "deger_skor": 60.0,
            "momentum_skor": 50.0,
            "risk_skor": 65.0,
            "olumlu_nedenler": [],
            "olumsuz_nedenler": [],
        }

    def test_top20_contract_caps_positions_and_sectors(self):
        rows = [self._ranked_row(index) for index in range(24)]

        selected = shadow.select_monthly_top20(
            rows,
            model_id=shadow.CHALLENGER_MODEL_ID,
            cohort_month="2026-07",
        )

        self.assertEqual(len(selected), 20)
        self.assertEqual([row["paper_rank"] for row in selected], list(range(1, 21)))
        self.assertTrue(all(row["motor_surumu"] == shadow.CHALLENGER_VERSION for row in selected))
        self.assertTrue(all(row["kurulum"] == "PAPER_TOP20" for row in selected))
        self.assertTrue(all(row["karar"] == "PAPER_SHADOW" for row in selected))
        self.assertLessEqual(max(row["paper_target_weight"] for row in selected), 0.05)
        technology_weight = sum(
            row["paper_target_weight"]
            for row in selected
            if row["sektor"] == "Technology"
        )
        self.assertLessEqual(technology_weight, 0.25)

    def test_monthly_pair_is_recorded_once(self):
        baseline = [self._ranked_row(index) for index in range(24)]
        challenger = [
            self._ranked_row(index, score=80.0 + (index % 7))
            for index in range(24)
        ]
        now = datetime(2026, 7, 22, 12, 0)

        first = engine.aylik_golge_kohortlarini_kaydet(
            baseline,
            challenger,
            vix_degeri=18.0,
            db_path=str(self.db_file),
            now=now,
        )
        second = engine.aylik_golge_kohortlarini_kaydet(
            baseline,
            challenger,
            vix_degeri=18.0,
            db_path=str(self.db_file),
            now=now,
        )

        self.assertEqual(first["status"], "RECORDED")
        self.assertEqual(first["models"][shadow.BASELINE_MODEL_ID]["inserted"], 20)
        self.assertEqual(first["models"][shadow.CHALLENGER_MODEL_ID]["inserted"], 20)
        self.assertEqual(second["status"], "ALREADY_RECORDED")

        conn = sqlite3.connect(self.db_file)
        try:
            counts = dict(conn.execute(
                """SELECT strategy_version, COUNT(*) FROM hisse_sinyalleri
                   GROUP BY strategy_version"""
            ).fetchall())
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(hisse_sinyalleri)")
            }
        finally:
            conn.close()
        self.assertEqual(counts[shadow.BASELINE_VERSION], 20)
        self.assertEqual(counts[shadow.CHALLENGER_VERSION], 20)
        self.assertTrue({
            "model_role", "cohort_month", "cohort_rank",
            "target_weight", "factor_weights_json",
        }.issubset(columns))

    def test_monthly_pair_rolls_back_if_second_model_fails(self):
        baseline = [self._ranked_row(index) for index in range(24)]
        challenger = [self._ranked_row(index) for index in range(24)]
        real_store = engine.sinyal_kaydet
        calls = {"count": 0}

        def fail_second(*args, **kwargs):
            calls["count"] += 1
            if calls["count"] == 2:
                raise RuntimeError("synthetic second-model failure")
            return real_store(*args, **kwargs)

        with patch.object(engine, "sinyal_kaydet", side_effect=fail_second):
            result = engine.aylik_golge_kohortlarini_kaydet(
                baseline,
                challenger,
                db_path=str(self.db_file),
                now=datetime(2026, 7, 22, 12, 0),
            )

        conn = sqlite3.connect(self.db_file)
        try:
            count = conn.execute("SELECT COUNT(*) FROM hisse_sinyalleri").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(result["status"], "FAILED_CLOSED")
        self.assertEqual(count, 0)

    def test_mixed_market_dates_fail_closed(self):
        rows = [self._ranked_row(index) for index in range(20)]
        rows[0]["veri_tarihi"] = "2026-07-20"

        with self.assertRaisesRegex(ValueError, "mixed market dates"):
            shadow.cohort_month_from_rows(rows)
    def test_three_paired_mature_cohorts_trigger_research_review(self):
        conn = sqlite3.connect(self.db_file)
        try:
            engine._hisse_veritabani_hazirla(conn)
            for month_index, month in enumerate(("2026-07", "2026-08", "2026-09")):
                for version, return_bonus, excess_bonus, mae in (
                    (shadow.BASELINE_VERSION, 0.00, 0.00, -0.05),
                    (shadow.CHALLENGER_VERSION, 0.02, 0.020, -0.055),
                ):
                    for symbol_index in range(20):
                        cursor = conn.execute(
                            """INSERT INTO hisse_sinyalleri
                               (sembol, as_of_date, strategy_version, setup,
                                cohort_month, ai_skor, target_weight)
                               VALUES (?, ?, ?, 'PAPER_TOP20', ?, ?, 0.05)""",
                            (
                                f"T{symbol_index:02d}",
                                f"{month}-01",
                                version,
                                month,
                                80.0 - symbol_index,
                            ),
                        )
                        base_return = 0.01 + month_index * 0.005
                        conn.execute(
                            """INSERT INTO hisse_sinyal_sonuclari
                               (signal_id, getiri_20g, excess_spy_20g, mae_20g)
                               VALUES (?, ?, ?, ?)""",
                            (
                                cursor.lastrowid,
                                base_return + return_bonus,
                                0.005 + excess_bonus,
                                mae,
                            ),
                        )
            conn.commit()
        finally:
            conn.close()

        summary = shadow.shadow_performance_summary(str(self.db_file))

        self.assertEqual(summary["paired_mature_cohorts"], 3)
        self.assertEqual(summary["status"], "PAPER_REVIEW_PASS_RESEARCH_ONLY")
        self.assertTrue(summary["comparison"]["passed"])
        self.assertFalse(summary["production_valid"])

    def test_manifest_matches_frozen_code_contract(self):
        manifest = json.loads(
            Path("data/stock_shadow_paper_manifest.json").read_text(encoding="utf-8")
        )
        by_id = {row["id"]: row for row in manifest["models"]}

        for model_id, spec in shadow.MODEL_SPECS.items():
            self.assertEqual(by_id[model_id]["strategy_version"], spec["strategy_version"])
            self.assertEqual(by_id[model_id]["weights"], spec["weights"])
        self.assertEqual(
            manifest["decision_rule"]["minimum_paired_mature_cohorts"],
            shadow.DECISION_RULE["minimum_paired_mature_cohorts"],
        )


if __name__ == "__main__":
    unittest.main()
