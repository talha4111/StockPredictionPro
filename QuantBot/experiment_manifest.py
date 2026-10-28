from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


MANIFEST_SCHEMA_VERSION = 1


def _json_uyumlu(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {
            str(key): _json_uyumlu(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple, set)):
        return [_json_uyumlu(item) for item in value]
    if hasattr(value, "item"):
        try:
            return _json_uyumlu(value.item())
        except (TypeError, ValueError):
            pass
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except (TypeError, ValueError):
            pass
    return repr(value)


def _kanonik_json(value: Any) -> bytes:
    return json.dumps(
        _json_uyumlu(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def dosya_parmak_izi(path: str | os.PathLike[str], *, root: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    dosya = Path(path).resolve()
    digest = hashlib.sha256()
    with dosya.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    gorunen_yol = str(dosya)
    if root is not None:
        try:
            gorunen_yol = dosya.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            pass

    return {
        "path": gorunen_yol,
        "sha256": digest.hexdigest(),
        "bytes": dosya.stat().st_size,
    }


def dataframe_parmak_izi(frame: pd.DataFrame) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Veri parmak izi yalnızca pandas DataFrame için üretilebilir.")

    schema = {
        "columns": [str(column) for column in frame.columns],
        "dtypes": [str(dtype) for dtype in frame.dtypes],
        "index_type": type(frame.index).__name__,
        "index_dtype": str(getattr(frame.index, "dtype", "")),
    }
    digest = hashlib.sha256(_kanonik_json(schema))
    try:
        row_hashes = pd.util.hash_pandas_object(frame, index=True, categorize=True)
    except TypeError:
        row_hashes = pd.util.hash_pandas_object(frame.astype(str), index=True, categorize=True)
    digest.update(row_hashes.to_numpy().tobytes())

    return {
        "sha256": digest.hexdigest(),
        "rows": int(len(frame)),
        "columns": schema["columns"],
        "dtypes": schema["dtypes"],
        "index_start": _json_uyumlu(frame.index[0]) if len(frame) else None,
        "index_end": _json_uyumlu(frame.index[-1]) if len(frame) else None,
    }


def manifest_olustur(
    *,
    experiment_type: str,
    parameters: Mapping[str, Any],
    datasets: Mapping[str, pd.DataFrame],
    code_paths: Iterable[str | os.PathLike[str]],
    features: Iterable[str] = (),
    validation: Mapping[str, Any] | None = None,
    cost_assumptions: Mapping[str, Any] | None = None,
    random_seed: int | None = None,
    trial_count: int | None = None,
    root: str | os.PathLike[str] | None = None,
    notes: Iterable[str] = (),
) -> dict[str, Any]:
    if not str(experiment_type).strip():
        raise ValueError("experiment_type boş olamaz.")
    if not datasets:
        raise ValueError("Manifest için en az bir veri seti gerekir.")

    dataset_fingerprints = {
        str(name): dataframe_parmak_izi(frame)
        for name, frame in sorted(datasets.items(), key=lambda pair: str(pair[0]))
    }
    code_fingerprints = [
        dosya_parmak_izi(path, root=root)
        for path in sorted({str(Path(path).resolve()) for path in code_paths})
    ]

    identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "experiment_type": str(experiment_type),
        "parameters": _json_uyumlu(parameters),
        "features": [str(feature) for feature in features],
        "validation": _json_uyumlu(validation or {}),
        "cost_assumptions": _json_uyumlu(cost_assumptions or {}),
        "random_seed": random_seed,
        "trial_count": trial_count,
        "datasets": dataset_fingerprints,
        "code": code_fingerprints,
    }
    experiment_id = hashlib.sha256(_kanonik_json(identity)).hexdigest()
    return {
        **identity,
        "experiment_id": experiment_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "pandas": pd.__version__,
        },
        "notes": [str(note) for note in notes],
    }


def manifest_yaz(path: str | os.PathLike[str], manifest: Mapping[str, Any]) -> dict[str, Any]:
    hedef = Path(path).resolve()
    hedef.parent.mkdir(parents=True, exist_ok=True)
    yeni = _json_uyumlu(dict(manifest))

    if hedef.exists():
        mevcut = json.loads(hedef.read_text(encoding="utf-8"))
        if mevcut.get("experiment_id") == yeni.get("experiment_id"):
            return mevcut
        raise FileExistsError(
            f"Mevcut deney manifesti farklı bir deney kimliğine sahip: {hedef}"
        )

    temp_path = hedef.with_name(
        f".{hedef.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        # tempfile.mkstemp, bazı Windows sandbox'larında PermissionError sonrası
        # yeni adları sonsuza dek deneyebilir. UUID + exclusive create aynı
        # çakışma korumasını tek denemede ve fail-fast biçimde sağlar.
        with temp_path.open("x", encoding="utf-8") as handle:
            json.dump(yeni, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, hedef)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return yeni


def deney_manifesti_yaz(path: str | os.PathLike[str], **kwargs: Any) -> dict[str, Any]:
    return manifest_yaz(path, manifest_olustur(**kwargs))
