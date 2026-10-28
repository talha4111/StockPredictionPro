from __future__ import annotations

import hashlib
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


SNAPSHOT_SCHEMA_VERSION = 1
_MAX_SNAPSHOT_RECORDS = 20_000
_MAX_SNAPSHOT_BYTES = 5_000_000
_STORE_LOCK = threading.RLock()


class SnapshotIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class MetricSnapshot:
    series: pd.Series
    metadata: dict[str, Any]
    path: Path


def _empty_series(name: str) -> pd.Series:
    return pd.Series(
        dtype=float,
        index=pd.DatetimeIndex([], dtype="datetime64[ns]"),
        name=name,
    )


def _canonical_records(series: pd.Series) -> list[list[int | float]]:
    if not isinstance(series, pd.Series):
        raise TypeError("snapshot verisi pandas Series olmalıdır.")
    index = pd.DatetimeIndex(series.index)
    if index.tz is not None:
        index = index.tz_convert("UTC").tz_localize(None)
    numeric = pd.to_numeric(series, errors="coerce")
    clean = pd.Series(numeric.to_numpy(), index=index, dtype=float)
    clean = clean[
        ~clean.index.isna()
        & clean.map(math.isfinite)
    ]
    clean = clean[~clean.index.duplicated(keep="last")].sort_index()
    if len(clean) > _MAX_SNAPSHOT_RECORDS:
        clean = clean.iloc[-_MAX_SNAPSHOT_RECORDS:]
    return [
        [int(timestamp.value // 1_000_000), float(value)]
        for timestamp, value in clean.items()
    ]


def _records_digest(records: list[list[int | float]]) -> str:
    canonical = json.dumps(
        records,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class ExternalMetricSnapshotStore:
    def __init__(self, root: str | os.PathLike[str] | None = None):
        configured = os.environ.get("QUANTBOT_EXTERNAL_METRIC_CACHE_DIR")
        self.root = Path(
            root
            or configured
            or Path(__file__).resolve().parent
            / ".cache"
            / "external_metrics_v6"
        ).resolve()

    @staticmethod
    def _identity(symbol: str, metric: str, timeframe: str) -> str:
        return f"{str(symbol).strip().upper()}|{metric}|{timeframe}"

    def path_for(self, symbol: str, metric: str, timeframe: str) -> Path:
        identity = self._identity(symbol, metric, timeframe)
        slug = re.sub(r"[^A-Z0-9]+", "-", str(symbol).upper()).strip("-")
        slug = (slug or "UNKNOWN")[:40]
        metric_slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            str(metric).lower(),
        ).strip("-") or "metric"
        timeframe_slug = re.sub(
            r"[^a-z0-9]+",
            "-",
            str(timeframe).lower(),
        ).strip("-") or "timeframe"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        return (
            self.root
            / f"{slug}-{metric_slug[:32]}-{timeframe_slug[:16]}-{digest}.json"
        )

    def load(self, symbol: str, metric: str, timeframe: str) -> MetricSnapshot:
        path = self.path_for(symbol, metric, timeframe)
        if not path.exists():
            return MetricSnapshot(_empty_series(metric), {}, path)
        try:
            if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
                raise SnapshotIntegrityError("Snapshot dosyası beklenenden büyük.")
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotIntegrityError(
                f"Snapshot okunamadı: {path.name}"
            ) from exc

        if not isinstance(payload, dict):
            raise SnapshotIntegrityError("Snapshot kök nesnesi geçersiz.")
        expected_identity = self._identity(symbol, metric, timeframe)
        if int(payload.get("schema_version") or 0) != SNAPSHOT_SCHEMA_VERSION:
            raise SnapshotIntegrityError("Snapshot schema sürümü uyumsuz.")
        if str(payload.get("identity") or "") != expected_identity:
            raise SnapshotIntegrityError("Snapshot kimliği uyumsuz.")
        records = payload.get("records")
        if not isinstance(records, list) or len(records) > _MAX_SNAPSHOT_RECORDS:
            raise SnapshotIntegrityError("Snapshot kayıt listesi geçersiz.")
        if str(payload.get("records_sha256") or "") != _records_digest(records):
            raise SnapshotIntegrityError("Snapshot checksum doğrulaması başarısız.")

        try:
            timestamps = [int(record[0]) for record in records]
            values = [float(record[1]) for record in records]
        except (IndexError, TypeError, ValueError) as exc:
            raise SnapshotIntegrityError("Snapshot kaydı çözümlenemedi.") from exc
        if any(timestamp < 0 for timestamp in timestamps):
            raise SnapshotIntegrityError("Snapshot negatif timestamp içeriyor.")
        if any(not math.isfinite(value) for value in values):
            raise SnapshotIntegrityError("Snapshot sonlu olmayan değer içeriyor.")
        index = pd.to_datetime(timestamps, unit="ms")
        series = pd.Series(values, index=index, name=metric, dtype=float)
        if series.index.has_duplicates or not series.index.is_monotonic_increasing:
            raise SnapshotIntegrityError(
                "Snapshot timestamp sırası benzersiz ve artan değil."
            )
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            raise SnapshotIntegrityError("Snapshot metadata alanı geçersiz.")
        return MetricSnapshot(series, dict(metadata), path)

    def update(
        self,
        symbol: str,
        metric: str,
        timeframe: str,
        new_series: pd.Series,
        *,
        metadata: dict[str, Any] | None = None,
        retain_since_ms: int | None = None,
    ) -> MetricSnapshot:
        with _STORE_LOCK:
            current = self.load(symbol, metric, timeframe)
            incoming = new_series.rename(metric)
            combined = pd.concat([current.series, incoming])
            combined = combined[~combined.index.duplicated(keep="last")].sort_index()
            if retain_since_ms is not None:
                retain_from = pd.to_datetime(int(retain_since_ms), unit="ms")
                combined = combined.loc[combined.index >= retain_from]

            records = _canonical_records(combined)
            merged_metadata = dict(current.metadata)
            merged_metadata.update(dict(metadata or {}))
            payload = {
                "schema_version": SNAPSHOT_SCHEMA_VERSION,
                "identity": self._identity(symbol, metric, timeframe),
                "symbol": str(symbol),
                "metric": str(metric),
                "timeframe": str(timeframe),
                "updated_at_ms": int(time.time() * 1000),
                "records_sha256": _records_digest(records),
                "metadata": merged_metadata,
                "records": records,
            }
            path = current.path
            path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = path.with_name(
                f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
            )
            try:
                with temp_path.open("x", encoding="utf-8") as handle:
                    json.dump(
                        payload,
                        handle,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        allow_nan=False,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                for attempt in range(4):
                    try:
                        os.replace(temp_path, path)
                        break
                    except PermissionError:
                        if attempt == 3:
                            raise
                        time.sleep(0.025 * (attempt + 1))
            finally:
                if temp_path.exists():
                    temp_path.unlink()
            return self.load(symbol, metric, timeframe)
