import importlib.util
import sys
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd


if importlib.util.find_spec("joblib") is None:
    sys.modules["joblib"] = types.ModuleType("joblib")

from ai_core import BeyinMotoru


def _frame(rows=10):
    index = pd.date_range("2026-01-01", periods=rows, freq="15min")
    return pd.DataFrame(
        {
            "open": [100.0] * rows,
            "Hedef_Close": [100.0] * rows,
        },
        index=index,
    )


class _FakeClassifier:
    def fit(self, features, targets):
        self.n_features_in_ = features.shape[1]
        self.feature_importances_ = np.repeat(
            1.0 / features.shape[1],
            features.shape[1],
        )
        return self

    def predict_proba(self, features):
        positive = np.where(features[:, 0] > 0.0, 0.70, 0.30)
        return np.column_stack([1.0 - positive, positive])


class _NoAlphaClassifier(_FakeClassifier):
    def predict_proba(self, features):
        positive = np.repeat(0.50, len(features))
        return np.column_stack([1.0 - positive, positive])


def _v6_training_frame(motor, rows=500):
    frame = _frame(rows=rows)
    direction = np.where(np.arange(rows) % 2 == 0, 1.0, -1.0)
    frame["Hedef_Close"] = 100.0 + (direction * 0.30)
    for feature in motor.stock_features:
        frame[feature] = direction * 0.01 if feature == "Hedef_Ret" else 0.1
    frame.attrs.update(
        {
            "feature_schema_version": 6,
            "base_timeframe": "15m",
            "feature_contract_id": motor.feature_availability_spec.contract_id,
        }
    )
    return frame


def _v6_crypto_training_frame(motor, rows=1200):
    frame = _frame(rows=rows)
    direction = np.where(np.arange(rows) % 2 == 0, 1.0, -1.0)
    frame["Hedef_Close"] = 100.0 + (direction * 0.30)
    for feature in motor.crypto_features:
        frame[feature] = direction * 0.01 if feature == "Hedef_Ret" else 0.1
    frame["Open_Interest_Available"] = 1
    frame["Open_Interest_Age_Bars"] = 0.0
    frame["Funding_Rate_Available"] = 1
    frame["Funding_Rate_Age_Bars"] = 0.0
    quality = {}
    for feature_name in ("Open_Interest", "Funding_Rate"):
        quality[feature_name] = {
            "feature": feature_name,
            "target_rows": rows,
            "source_observations": rows,
            "observed_rows": rows,
            "available_rows": rows,
            "coverage_ratio": 1.0,
            "recent_window_rows": 192,
            "recent_coverage_ratio": 1.0,
            "baseline_ratio": 0.0,
            "stale_ratio": 0.0,
            "latest_available": True,
            "first_available_at": frame.index[0].isoformat(),
            "last_available_at": frame.index[-1].isoformat(),
            "real_zero_count": 0,
        }
    frame.attrs.update(
        {
            "feature_schema_version": 6,
            "base_timeframe": "15m",
            "feature_contract_id": motor.feature_availability_spec.contract_id,
            "coverage_contract_id": motor.feature_coverage_spec.contract_id,
            "feature_quality": quality,
        }
    )
    return frame


class AiCoreLabelContractTests(unittest.TestCase):
    def test_default_path_remains_v5(self):
        motor = BeyinMotoru()

        self.assertEqual(motor.label_schema_version, 5)
        self.assertEqual(motor.model_schema_version, 5)
        self.assertEqual(motor.model_prefix, "beyin")
        self.assertIsNone(motor.outcome_spec)
        self.assertIsNone(motor.training_split_spec)
        self.assertIsNone(motor.feature_coverage_spec)
        self.assertEqual(
            BeyinMotoru(model_prefix="shadow_400_5").model_prefix,
            "shadow_400_5",
        )
        self.assertEqual(BeyinMotoru(model_prefix="").model_prefix, "")

    def test_v6_uses_isolated_artifact_prefix_and_outcome_contract(self):
        motor = BeyinMotoru(label_schema_version=6)

        self.assertEqual(motor.model_schema_version, 6)
        self.assertEqual(motor.model_prefix, "v6_beyin")
        self.assertEqual(len(motor.outcome_spec.contract_id), 64)
        self.assertEqual(len(motor.training_split_spec.contract_id), 64)
        self.assertEqual(len(motor.feature_coverage_spec.contract_id), 64)
        self.assertIn("Open_Interest_Available", motor.crypto_features)
        self.assertIn("Funding_Rate_Age_Bars", motor.crypto_features)
        self.assertAlmostEqual(
            motor.outcome_spec.positive_gross_return_threshold,
            motor.min_target_return,
        )

    def test_v6_keeps_neutral_rows_as_negative_class(self):
        motor = BeyinMotoru(label_schema_version=6)

        result = motor.df_hazirla(_frame(), drop_neutral=False)

        self.assertEqual(len(result), 6)
        self.assertEqual(result["Hedef_Yön"].tolist(), [0] * 6)
        self.assertEqual(result["Gelecek_Ret"].tolist(), [0.0] * 6)
        self.assertEqual(result["Gelecek_Net_Ret"].tolist(), [-0.001] * 6)

    def test_v6_enters_next_open_and_exits_fixed_horizon_close(self):
        motor = BeyinMotoru(label_schema_version=6)
        frame = _frame(rows=7)
        frame["open"] = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0]
        frame["Hedef_Close"] = [
            100.0,
            101.0,
            102.0,
            103.0,
            104.0,
            105.0,
            106.0,
        ]

        result = motor.df_hazirla(frame, drop_neutral=False)

        self.assertEqual(len(result), 3)
        self.assertEqual(result.iloc[0]["Outcome_Entry"], 101.0)
        self.assertEqual(result.iloc[0]["Outcome_Exit"], 104.0)
        self.assertEqual(result.iloc[0]["Hedef_Yön"], 1)

    def test_v6_rejects_neutral_drop_and_missing_open(self):
        motor = BeyinMotoru(label_schema_version=6)

        with self.assertRaisesRegex(ValueError, "nötr/negatif"):
            motor.df_hazirla(_frame(), drop_neutral=True)
        with self.assertRaisesRegex(ValueError, "open"):
            motor.df_hazirla(_frame().drop(columns=["open"]))

    def test_v6_training_requires_provenance_and_prediction_remains_locked(self):
        motor = BeyinMotoru(label_schema_version=6)

        with self.assertRaisesRegex(ValueError, "feature_schema_version=6"):
            motor.model_egit("BTC/USDT", _frame())
        with self.assertRaisesRegex(RuntimeError, "doğrulanmamış"):
            motor.tahmin_et("BTC/USDT", _frame())

    def test_v6_offline_training_uses_cv_holdout_and_contract_metadata(self):
        motor = BeyinMotoru(
            n_estimators=20,
            max_depth=2,
            label_schema_version=6,
        )
        frame = _v6_training_frame(motor)

        with (
            mock.patch.object(
                motor,
                "_siniflandirici_olustur",
                side_effect=lambda *args, **kwargs: _FakeClassifier(),
            ) as factory,
            mock.patch.object(
                motor,
                "_platt_kalibrasyon_uydur",
                return_value=(1.0, 0.0),
            ),
            mock.patch.object(motor, "_atomik_model_kaydet") as save_model,
            mock.patch.object(motor, "_atomik_json_kaydet") as save_meta,
        ):
            model = motor.model_egit(
                "BTC/USDT",
                frame,
                is_crypto=False,
                algoritma="xgboost",
            )

        self.assertIsInstance(model, _FakeClassifier)
        self.assertEqual(factory.call_count, 5)
        save_model.assert_called_once()
        save_meta.assert_called_once()
        self.assertEqual(
            save_model.call_args.args[1],
            "v6_stock_beyin_BTC-USDT.pkl",
        )
        meta = motor.son_egitim_meta
        self.assertEqual(meta["training_mode"], "offline_research")
        self.assertFalse(meta["live_prediction_enabled"])
        self.assertTrue(meta["artifact_saved"])
        self.assertTrue(meta["offline_artifact_quality_gate"]["passed"])
        self.assertEqual(meta["model_schema_version"], 6)
        self.assertEqual(meta["feature_schema_version"], 6)
        self.assertEqual(meta["recent_holdout_rows"], 124)
        self.assertEqual(meta["cv_oof_rows"], 213)
        self.assertEqual(len(meta["cv_fold_rows"]), 3)
        diagnostics = meta["prediction_diagnostics"]
        self.assertEqual(diagnostics["schema_version"], 1)
        self.assertFalse(
            diagnostics["threshold_research"]["holdout_used_for_selection"]
        )
        self.assertFalse(diagnostics["threshold_research"]["activated"])
        self.assertEqual(
            diagnostics["cv"]["raw_balanced_accuracy"],
            1.0,
        )
        self.assertEqual(
            diagnostics["cv"]["calibrated_balanced_accuracy"],
            1.0,
        )
        self.assertEqual(
            diagnostics["holdout"]["raw_probability_summary"]["min"],
            0.3,
        )
        self.assertEqual(
            diagnostics["holdout"]["raw_probability_summary"]["max"],
            0.7,
        )
        self.assertEqual(meta["cv_fold_rows"][0]["raw_balanced_accuracy"], 1.0)
        contribution = diagnostics["feature_contribution"]
        self.assertEqual(
            contribution["method"],
            "validation_permutation_raw_probability",
        )
        self.assertFalse(contribution["activated"])
        self.assertEqual(
            contribution["ranking"][0]["feature"],
            "Hedef_Ret",
        )
        shadow = diagnostics["feature_subset_shadow"]
        self.assertEqual(shadow["status"], "skipped")
        self.assertFalse(shadow["holdout_used_for_selection"])
        self.assertFalse(shadow["activated"])
        self.assertEqual(
            meta["outcome_contract_id"],
            motor.outcome_spec.contract_id,
        )
        self.assertEqual(
            meta["split_contract_id"],
            motor.training_split_spec.contract_id,
        )

    def test_v6_reduced_feature_shadow_evaluates_without_artifacts(self):
        motor = BeyinMotoru(
            n_estimators=20,
            max_depth=2,
            label_schema_version=6,
        )
        frame = _v6_training_frame(motor)
        selected = set(motor.stock_features[:4])

        def contribution(*, feature_names, **kwargs):
            return [
                {
                    "feature": name,
                    "balanced_accuracy_drop": 0.10 if name in selected else 0.0,
                    "brier_increase": 0.05 if name in selected else 0.0,
                }
                for name in feature_names
            ]

        with (
            mock.patch.object(
                motor,
                "_siniflandirici_olustur",
                side_effect=lambda *args, **kwargs: _FakeClassifier(),
            ) as factory,
            mock.patch.object(
                motor,
                "_platt_kalibrasyon_uydur",
                return_value=(1.0, 0.0),
            ),
            mock.patch.object(
                motor,
                "_v6_permutasyon_katkisi",
                side_effect=contribution,
            ),
            mock.patch.object(motor, "_atomik_model_kaydet") as save_model,
            mock.patch.object(motor, "_atomik_json_kaydet") as save_meta,
        ):
            motor.model_egit(
                "BTC/USDT",
                frame,
                is_crypto=False,
                algoritma="xgboost",
            )

        self.assertEqual(factory.call_count, 9)
        save_model.assert_called_once()
        save_meta.assert_called_once()
        shadow = motor.son_egitim_meta["prediction_diagnostics"][
            "feature_subset_shadow"
        ]
        self.assertEqual(shadow["status"], "evaluated")
        self.assertEqual(set(shadow["selected_features"]), selected)
        self.assertFalse(shadow["activated"])
        self.assertFalse(shadow["artifact_saved"])

    def test_v6_quality_gate_rejects_no_alpha_without_saving_artifacts(self):
        motor = BeyinMotoru(
            n_estimators=20,
            max_depth=2,
            label_schema_version=6,
        )
        frame = _v6_training_frame(motor)

        with (
            mock.patch.object(
                motor,
                "_siniflandirici_olustur",
                side_effect=lambda *args, **kwargs: _NoAlphaClassifier(),
            ) as factory,
            mock.patch.object(
                motor,
                "_platt_kalibrasyon_uydur",
                return_value=(1.0, 0.0),
            ),
            mock.patch.object(motor, "_atomik_model_kaydet") as save_model,
            mock.patch.object(motor, "_atomik_json_kaydet") as save_meta,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "artifact kalite kapısı başarısız",
            ):
                motor.model_egit(
                    "BTC/USDT",
                    frame,
                    is_crypto=False,
                    algoritma="xgboost",
                )

        self.assertEqual(factory.call_count, 4)
        save_model.assert_not_called()
        save_meta.assert_not_called()
        meta = motor.son_egitim_meta
        self.assertFalse(meta["artifact_saved"])
        self.assertFalse(meta["offline_artifact_quality_gate"]["passed"])
        self.assertEqual(
            meta["prediction_diagnostics"]["holdout"][
                "raw_probability_summary"
            ]["std"],
            0.0,
        )
        self.assertIn(
            "recent_signal_count=0<8",
            meta["offline_artifact_quality_gate"]["reasons"],
        )

    def test_v6_crypto_training_rejects_short_joint_available_suffix(self):
        motor = BeyinMotoru(label_schema_version=6)
        frame = _v6_crypto_training_frame(motor)
        frame.iloc[200, frame.columns.get_loc("Open_Interest_Available")] = 0
        report = frame.attrs["feature_quality"]["Open_Interest"]
        report["available_rows"] = len(frame) - 1
        report["coverage_ratio"] = (len(frame) - 1) / len(frame)

        with self.assertRaisesRegex(ValueError, "kesintisiz ortak"):
            motor.model_egit("BTC/USDT", frame, is_crypto=True)

    def test_v6_crypto_training_records_coverage_contract_metadata(self):
        motor = BeyinMotoru(
            n_estimators=20,
            max_depth=2,
            label_schema_version=6,
        )
        frame = _v6_crypto_training_frame(motor)

        with (
            mock.patch.object(
                motor,
                "_siniflandirici_olustur",
                side_effect=lambda *args, **kwargs: _FakeClassifier(),
            ),
            mock.patch.object(
                motor,
                "_platt_kalibrasyon_uydur",
                return_value=(1.0, 0.0),
            ),
            mock.patch.object(motor, "_atomik_model_kaydet"),
            mock.patch.object(motor, "_atomik_json_kaydet"),
        ):
            motor.model_egit("BTC/USDT", frame, is_crypto=True)

        meta = motor.son_egitim_meta
        self.assertEqual(
            meta["coverage_contract_id"],
            motor.feature_coverage_spec.contract_id,
        )
        self.assertEqual(1200, meta["joint_available_rows"])
        self.assertEqual(
            motor.feature_coverage_spec.to_dict(),
            meta["coverage_spec"],
        )

    def test_v6_plan_uses_raw_timeline_and_keeps_requested_holdout_size(self):
        motor = BeyinMotoru(label_schema_version=6)

        plan = motor.v6_egitim_plani_hazirla(
            _frame(rows=500),
            holdout_observations=80,
        )

        self.assertEqual(plan["outcome_contract_id"], motor.outcome_spec.contract_id)
        self.assertEqual(
            plan["split_contract_id"],
            motor.training_split_spec.contract_id,
        )
        self.assertEqual(plan["raw_holdout_bars"], 84)
        self.assertEqual(len(plan["planned_holdout"].validation_index), 84)
        self.assertEqual(len(plan["holdout"].validation_index), 80)
        self.assertEqual(len(plan["cv_folds"]), 3)
        self.assertEqual(
            plan["planned_holdout"].validation_index[0],
            plan["holdout"].validation_index[0],
        )

    def test_missing_eligible_row_does_not_move_planned_boundaries(self):
        motor = BeyinMotoru(label_schema_version=6)
        baseline = _frame(rows=500)
        incomplete = baseline.copy()
        incomplete.iloc[150, incomplete.columns.get_loc("open")] = float("nan")

        baseline_plan = motor.v6_egitim_plani_hazirla(
            baseline,
            holdout_observations=80,
        )
        incomplete_plan = motor.v6_egitim_plani_hazirla(
            incomplete,
            holdout_observations=80,
        )

        self.assertEqual(
            baseline_plan["planned_holdout"].validation_index[0],
            incomplete_plan["planned_holdout"].validation_index[0],
        )
        self.assertEqual(
            baseline_plan["planned_cv_folds"][0].validation_index[0],
            incomplete_plan["planned_cv_folds"][0].validation_index[0],
        )
        self.assertLess(
            len(incomplete_plan["eligible_index"]),
            len(baseline_plan["eligible_index"]),
        )

    def test_v6_plan_rejects_irregular_timeline_and_v5_access(self):
        irregular = _frame(rows=500).drop(_frame(rows=500).index[100])
        with self.assertRaisesRegex(ValueError, "kesintisiz 15m"):
            BeyinMotoru(label_schema_version=6).v6_egitim_plani_hazirla(
                irregular,
                holdout_observations=80,
            )
        with self.assertRaisesRegex(RuntimeError, "yalnızca label schema 6"):
            BeyinMotoru().v6_egitim_plani_hazirla(_frame(rows=500))

    def test_unknown_label_schema_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Desteklenmeyen"):
            BeyinMotoru(label_schema_version=7)


if __name__ == "__main__":
    unittest.main()
