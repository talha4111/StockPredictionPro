import json
import unittest
import uuid
from pathlib import Path
from unittest import mock

import pandas as pd

from external_metric_store import (
    ExternalMetricSnapshotStore,
    SnapshotIntegrityError,
)


class ExternalMetricSnapshotStoreTests(unittest.TestCase):
    def test_filename_components_cannot_escape_store_root(self):
        store = ExternalMetricSnapshotStore(Path(__file__).parent)

        path = store.path_for(
            "../../BTC/USDT",
            "../../open_interest",
            "../15m",
        )

        self.assertEqual(Path(__file__).parent.resolve(), path.parent)

    def test_update_is_restart_safe_deduplicated_and_retention_bounded(self):
        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        first_store = ExternalMetricSnapshotStore(Path(__file__).parent)
        path = first_store.path_for(symbol, "open_interest", "15m")
        try:
            first = pd.Series(
                [1.0, 0.0],
                index=pd.to_datetime(
                    ["2026-01-01 00:00", "2026-01-01 00:15"]
                ),
            )
            first_store.update(
                symbol,
                "open_interest",
                "15m",
                first,
                metadata={"pagination_complete": False},
            )

            restarted_store = ExternalMetricSnapshotStore(Path(__file__).parent)
            second = pd.Series(
                [2.0, 3.0],
                index=pd.to_datetime(
                    ["2026-01-01 00:15", "2026-01-01 00:30"]
                ),
            )
            result = restarted_store.update(
                symbol,
                "open_interest",
                "15m",
                second,
                metadata={"pagination_complete": True},
                retain_since_ms=int(
                    pd.Timestamp("2026-01-01 00:15").value // 1_000_000
                ),
            )

            self.assertEqual([2.0, 3.0], result.series.tolist())
            self.assertEqual(2, len(result.series))
            self.assertTrue(result.metadata["pagination_complete"])
            self.assertTrue(result.path.exists())
        finally:
            path.unlink(missing_ok=True)

    def test_checksum_corruption_fails_closed(self):
        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        store = ExternalMetricSnapshotStore(Path(__file__).parent)
        path = store.path_for(symbol, "funding_rate", "events")
        try:
            result = store.update(
                symbol,
                "funding_rate",
                "events",
                pd.Series(
                    [0.001],
                    index=pd.to_datetime(["2026-01-01 00:00"]),
                ),
            )
            payload = json.loads(result.path.read_text(encoding="utf-8"))
            payload["records"][0][1] = 999.0
            result.path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                SnapshotIntegrityError,
                "checksum",
            ):
                store.load(symbol, "funding_rate", "events")
        finally:
            path.unlink(missing_ok=True)

    def test_failed_atomic_replace_preserves_previous_snapshot(self):
        symbol = f"TEST-{uuid.uuid4().hex}/USDT"
        store = ExternalMetricSnapshotStore(Path(__file__).parent)
        path = store.path_for(symbol, "open_interest", "15m")
        try:
            original = store.update(
                symbol,
                "open_interest",
                "15m",
                pd.Series(
                    [1.0],
                    index=pd.to_datetime(["2026-01-01 00:00"]),
                ),
            )
            original_bytes = Path(original.path).read_bytes()

            with mock.patch(
                "external_metric_store.os.replace",
                side_effect=PermissionError("locked"),
            ):
                with self.assertRaises(PermissionError):
                    store.update(
                        symbol,
                        "open_interest",
                        "15m",
                        pd.Series(
                            [2.0],
                            index=pd.to_datetime(["2026-01-01 00:15"]),
                        ),
                    )

            self.assertEqual(original_bytes, Path(original.path).read_bytes())
            leftovers = list(Path(__file__).parent.glob(f".{path.name}.*.tmp"))
            self.assertEqual([], leftovers)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
