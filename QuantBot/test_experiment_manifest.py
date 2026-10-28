import io
import json
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

from experiment_manifest import (
    dataframe_parmak_izi,
    manifest_olustur,
    manifest_yaz,
)


class ExperimentManifestTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {"close": [100.0, 101.0], "volume": [10.0, 12.0]},
            index=pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T00:15:00Z"]),
        )

    def test_dataframe_fingerprint_changes_when_data_changes(self):
        original = dataframe_parmak_izi(self.frame)
        changed_frame = self.frame.copy()
        changed_frame.iloc[1, 0] = 101.5
        changed = dataframe_parmak_izi(changed_frame)

        self.assertNotEqual(original["sha256"], changed["sha256"])
        self.assertEqual(2, original["rows"])
        self.assertEqual(["close", "volume"], original["columns"])

    def test_experiment_identity_is_stable_for_same_inputs(self):
        code_path = Path(__file__)
        first = manifest_olustur(
            experiment_type="unit_test",
            parameters={"depth": 5},
            datasets={"BTC/USDT": self.frame},
            code_paths=[code_path],
            features=["close", "volume"],
            random_seed=42,
            root=code_path.parent,
        )
        second = manifest_olustur(
            experiment_type="unit_test",
            parameters={"depth": 5},
            datasets={"BTC/USDT": self.frame.copy()},
            code_paths=[code_path],
            features=["close", "volume"],
            random_seed=42,
            root=code_path.parent,
        )

        self.assertEqual(first["experiment_id"], second["experiment_id"])
        self.assertEqual(64, len(first["experiment_id"]))

    def test_manifest_is_atomic_idempotent_and_immutable(self):
        code_path = Path(__file__)
        target = code_path.parent / "_virtual_test" / "experiment_manifest.json"
        virtual_files = {}
        open_buffers = {}

        class WritableBuffer(io.StringIO):
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def fileno(self):
                return 1

        def fake_exists(path):
            return str(path) in virtual_files

        def fake_open(path, mode="r", *args, **kwargs):
            if mode != "x":
                raise AssertionError(f"Beklenmeyen dosya modu: {mode}")
            buffer = WritableBuffer()
            open_buffers[str(path)] = buffer
            return buffer

        def fake_replace(source, destination):
            virtual_files[str(destination)] = open_buffers[str(source)].getvalue()

        def fake_read_text(path, *args, **kwargs):
            return virtual_files[str(path)]

        manifest_kwargs = {
            "experiment_type": "unit_test",
            "parameters": {"depth": 5},
            "datasets": {"BTC/USDT": self.frame},
            "code_paths": [code_path],
            "root": code_path.parent,
        }
        first = manifest_olustur(**manifest_kwargs)
        with (
            mock.patch.object(Path, "mkdir"),
            mock.patch.object(Path, "exists", fake_exists),
            mock.patch.object(Path, "open", fake_open),
            mock.patch.object(Path, "read_text", fake_read_text),
            mock.patch.object(Path, "unlink"),
            mock.patch("experiment_manifest.os.fsync"),
            mock.patch("experiment_manifest.os.replace", fake_replace),
        ):
            persisted_first = manifest_yaz(target, first)
            second = manifest_yaz(target, persisted_first)

            persisted = json.loads(virtual_files[str(target.resolve())])
            self.assertEqual(first["experiment_id"], second["experiment_id"])
            self.assertEqual(first["experiment_id"], persisted["experiment_id"])

            changed = dict(first)
            changed["experiment_id"] = "different"
            with self.assertRaises(FileExistsError):
                manifest_yaz(target, changed)


if __name__ == "__main__":
    unittest.main()
