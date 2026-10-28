import unittest

import numpy as np
import pandas as pd

import risk_manager


def _quality_frame(schema_version=5):
    index = pd.date_range(
        pd.Timestamp.now(tz="UTC").tz_localize(None)
        - pd.Timedelta(minutes=15 * 349),
        periods=350,
        freq="15min",
    )
    frame = pd.DataFrame(
        {
            "Hedef_Close": np.repeat(100.0, 350),
            "ATR": np.repeat(1.0, 350),
        },
        index=index,
    )
    frame.attrs["feature_schema_version"] = schema_version
    return frame


class RiskManagerFeatureQualityTests(unittest.TestCase):
    def test_v5_path_remains_unchanged(self):
        accepted, reason, _ = risk_manager._veri_kalitesi_kontrol(
            "BTC/USDT",
            _quality_frame(schema_version=5),
            ["Hedef_Close", "ATR"],
        )

        self.assertTrue(accepted, reason)

    def test_v6_rejects_missing_coverage_provenance(self):
        accepted, reason, _ = risk_manager._veri_kalitesi_kontrol(
            "BTC/USDT",
            _quality_frame(schema_version=6),
            ["Hedef_Close", "ATR"],
        )

        self.assertFalse(accepted)
        self.assertIn("coverage sözleşmesi", reason)

    def test_v6_masks_without_schema_provenance_fail_closed(self):
        frame = _quality_frame(schema_version=5)
        frame.attrs.clear()
        frame["Open_Interest_Available"] = 1
        frame["Funding_Rate_Available"] = 1

        accepted, reason, _ = risk_manager._veri_kalitesi_kontrol(
            "BTC/USDT",
            frame,
            ["Hedef_Close", "ATR"],
        )

        self.assertFalse(accepted)
        self.assertIn("schema provenance eksik", reason)

    def test_v6_accepts_fresh_external_features_and_rejects_closed_mask(self):
        frame = _quality_frame(schema_version=6)
        frame["Open_Interest_Available"] = 1
        frame["Funding_Rate_Available"] = 1
        quality = {}
        for feature_name in ("Open_Interest", "Funding_Rate"):
            quality[feature_name] = {
                "feature": feature_name,
                "target_rows": len(frame),
                "coverage_ratio": 1.0,
                "recent_coverage_ratio": 1.0,
                "latest_available": True,
            }
        frame.attrs.update(
            {
                "coverage_contract_id": (
                    risk_manager._V6_FEATURE_COVERAGE.contract_id
                ),
                "feature_quality": quality,
            }
        )

        accepted, reason, details = risk_manager._veri_kalitesi_kontrol(
            "BTC/USDT",
            frame,
            ["Hedef_Close", "ATR"],
        )
        self.assertTrue(accepted, reason)
        self.assertIn("feature_quality", details)

        frame.loc[frame.index[-1], "Funding_Rate_Available"] = 0
        accepted, reason, _ = risk_manager._veri_kalitesi_kontrol(
            "BTC/USDT",
            frame,
            ["Hedef_Close", "ATR"],
        )
        self.assertFalse(accepted)
        self.assertIn("maskesi uyuşmuyor", reason)


if __name__ == "__main__":
    unittest.main()
