import importlib.util
import sys
import types
import unittest
from unittest import mock

import numpy as np
import pandas as pd


_REAL_ML_AVAILABLE = all(
    importlib.util.find_spec(package) is not None
    for package in ("joblib", "sklearn", "xgboost")
)
if importlib.util.find_spec("joblib") is None:
    sys.modules["joblib"] = types.ModuleType("joblib")

from ai_core import BeyinMotoru


def _training_frame(motor, rows=500):
    index = pd.date_range("2026-01-01", periods=rows, freq="15min")
    direction = np.where(np.arange(rows) % 2 == 0, 1.0, -1.0)
    frame = pd.DataFrame(
        {
            "open": np.repeat(100.0, rows),
            "Hedef_Close": 100.0 + (direction * 0.30),
        },
        index=index,
    )
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


@unittest.skipUnless(
    _REAL_ML_AVAILABLE,
    "Gerçek smoke testi joblib, scikit-learn ve xgboost gerektirir.",
)
class V6XGBoostSmokeTests(unittest.TestCase):
    def test_real_xgboost_fit_calibration_and_holdout_without_artifacts(self):
        motor = BeyinMotoru(
            n_estimators=8,
            max_depth=2,
            label_schema_version=6,
        )
        frame = _training_frame(motor)
        real_factory = motor._siniflandirici_olustur

        def limited_factory(algoritma, targets, *, n_estimators):
            return real_factory(
                algoritma,
                targets,
                n_estimators=min(int(n_estimators), 8),
            )

        with (
            mock.patch.object(
                motor,
                "_siniflandirici_olustur",
                side_effect=limited_factory,
            ) as factory,
            mock.patch.object(motor, "_atomik_model_kaydet") as save_model,
            mock.patch.object(motor, "_atomik_json_kaydet") as save_meta,
        ):
            model = motor.model_egit(
                "BTC/USDT",
                frame,
                is_crypto=False,
                algoritma="xgboost",
            )

        self.assertEqual(factory.call_count, 5)
        self.assertEqual(model.__class__.__module__.split(".")[0], "xgboost")
        save_model.assert_called_once()
        save_meta.assert_called_once()

        meta = motor.son_egitim_meta
        self.assertEqual(meta["training_mode"], "offline_research")
        self.assertFalse(meta["live_prediction_enabled"])
        self.assertTrue(meta["artifact_saved"])
        self.assertTrue(meta["offline_artifact_quality_gate"]["passed"])
        self.assertEqual(meta["model_schema_version"], 6)
        self.assertEqual(meta["recent_holdout_rows"], 124)
        self.assertEqual(meta["cv_oof_rows"], 213)
        self.assertTrue(np.isfinite(meta["cv_brier_score"]))
        self.assertTrue(np.isfinite(meta["recent_brier_score"]))
        self.assertTrue(np.isfinite(meta["calibration_a"]))
        self.assertTrue(np.isfinite(meta["calibration_b"]))
        diagnostics = meta["prediction_diagnostics"]
        self.assertTrue(
            np.isfinite(diagnostics["cv"]["raw_balanced_accuracy"])
        )
        self.assertTrue(
            np.isfinite(diagnostics["holdout"]["raw_brier_score"])
        )
        self.assertEqual(
            diagnostics["holdout"]["raw_probability_summary"]["count"],
            124,
        )


if __name__ == "__main__":
    unittest.main()
