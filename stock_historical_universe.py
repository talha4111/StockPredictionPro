"""Auditable point-in-time stock universe reconstruction.

The provider starts from a dated constituent snapshot and applies sourced
add/remove events in either direction. It fails closed outside its declared
coverage so a backtest cannot silently fall back to today's constituents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping


SCHEMA_VERSION = 1
VALID_ACTIONS = {"ADD", "REMOVE"}


class UniverseDataError(ValueError):
    """Raised when historical universe data is incomplete or inconsistent."""


def _as_date(value: object, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise UniverseDataError(f"{field_name} ISO tarih olmali: {value!r}") from exc


def _clean_symbol(value: object) -> str:
    symbol = str(value or "").strip().upper()
    if not symbol:
        raise UniverseDataError("Sembol bos olamaz")
    return symbol


@dataclass(frozen=True)
class UniverseChange:
    effective_date: date
    action: str
    symbol: str
    sector: str
    company: str = ""
    source_url: str = ""

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object]) -> "UniverseChange":
        action = str(payload.get("action", "")).strip().upper()
        if action not in VALID_ACTIONS:
            raise UniverseDataError(f"Gecersiz evren islemi: {action!r}")
        sector = str(payload.get("sector", "")).strip()
        if not sector:
            raise UniverseDataError("Her evren degisikliginde sektor zorunlu")
        return cls(
            effective_date=_as_date(payload.get("effective_date"), "effective_date"),
            action=action,
            symbol=_clean_symbol(payload.get("symbol")),
            sector=sector,
            company=str(payload.get("company", "")).strip(),
            source_url=str(payload.get("source_url", "")).strip(),
        )


class HistoricalUniverseProvider:
    """Reconstruct membership as known on each requested signal date."""

    def __init__(
        self,
        *,
        anchor_date: object,
        anchor_constituents: Mapping[str, str],
        changes: list[UniverseChange],
        coverage_start: object,
        coverage_end: object,
        source: str,
        complete: bool = False,
    ) -> None:
        self.anchor_date = _as_date(anchor_date, "anchor_date")
        self.coverage_start = _as_date(coverage_start, "coverage_start")
        self.coverage_end = _as_date(coverage_end, "coverage_end")
        self.source = str(source).strip()
        self.complete = bool(complete)
        self._anchor = {
            _clean_symbol(symbol): str(sector).strip()
            for symbol, sector in anchor_constituents.items()
        }
        self._changes = sorted(changes, key=lambda item: (item.effective_date, item.symbol))

        self._validate_contract()
        # Exercise both reconstruction directions now, not halfway through a run.
        self._state_as_of(self.coverage_start)
        self._state_as_of(self.coverage_end)

    @classmethod
    def from_json(cls, path: str | Path) -> "HistoricalUniverseProvider":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise UniverseDataError(
                f"Desteklenmeyen evren semasi: {payload.get('schema_version')!r}"
            )
        anchor = payload.get("anchor")
        coverage = payload.get("coverage")
        if not isinstance(anchor, Mapping) or not isinstance(coverage, Mapping):
            raise UniverseDataError("anchor ve coverage nesneleri zorunlu")

        rows = anchor.get("constituents")
        if not isinstance(rows, list):
            raise UniverseDataError("anchor.constituents liste olmali")
        constituents: dict[str, str] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                raise UniverseDataError("Her constituent bir nesne olmali")
            symbol = _clean_symbol(row.get("symbol"))
            sector = str(row.get("sector", "")).strip()
            if not sector:
                raise UniverseDataError(f"{symbol} icin sektor eksik")
            if symbol in constituents:
                raise UniverseDataError(f"Anchor listesinde tekrar eden sembol: {symbol}")
            constituents[symbol] = sector

        raw_changes = payload.get("changes", [])
        if not isinstance(raw_changes, list):
            raise UniverseDataError("changes liste olmali")
        changes = [UniverseChange.from_mapping(row) for row in raw_changes]
        return cls(
            anchor_date=anchor.get("date"),
            anchor_constituents=constituents,
            changes=changes,
            coverage_start=coverage.get("start"),
            coverage_end=coverage.get("end"),
            source=str(payload.get("source", "")),
            complete=bool(coverage.get("complete", False)),
        )

    @property
    def metadata(self) -> dict[str, object]:
        cited_changes = sum(change.source_url.startswith("https://") for change in self._changes)
        all_changes_cited = cited_changes == len(self._changes)
        return {
            "schema_version": SCHEMA_VERSION,
            "source": self.source,
            "anchor_date": self.anchor_date.isoformat(),
            "coverage_start": self.coverage_start.isoformat(),
            "coverage_end": self.coverage_end.isoformat(),
            "complete": self.complete,
            "change_count": len(self._changes),
            "cited_change_count": cited_changes,
            "all_changes_cited": all_changes_cited,
            "point_in_time_eligible": self.complete and all_changes_cited,
        }

    @property
    def symbols(self) -> list[str]:
        """Return every symbol needed to cover the declared history."""
        return sorted(set(self._anchor) | {change.symbol for change in self._changes})

    def __call__(self, signal_date: object) -> dict[str, str]:
        requested = _as_date(signal_date, "signal_date")
        if requested < self.coverage_start or requested > self.coverage_end:
            raise UniverseDataError(
                "Istenen tarih evren kapsaminin disinda: "
                f"{requested.isoformat()} not in "
                f"[{self.coverage_start.isoformat()}, {self.coverage_end.isoformat()}]"
            )
        return dict(sorted(self._state_as_of(requested).items()))

    def _validate_contract(self) -> None:
        if not self.source:
            raise UniverseDataError("Evren veri kaynagi zorunlu")
        if not self._anchor:
            raise UniverseDataError("Anchor constituent listesi bos olamaz")
        if any(not sector for sector in self._anchor.values()):
            raise UniverseDataError("Anchor listesindeki her sembolun sektoru olmali")
        if not self.coverage_start <= self.anchor_date <= self.coverage_end:
            raise UniverseDataError("Anchor tarihi coverage araliginda olmali")

        seen: set[tuple[date, str]] = set()
        for change in self._changes:
            key = (change.effective_date, change.symbol)
            if key in seen:
                raise UniverseDataError(
                    f"Ayni tarih ve sembol icin birden fazla islem var: {key}"
                )
            seen.add(key)
            if not self.coverage_start <= change.effective_date <= self.coverage_end:
                raise UniverseDataError(
                    f"Evren degisikligi coverage disinda: {change.effective_date}"
                )
        if self.complete and any(
            not change.source_url.startswith("https://") for change in self._changes
        ):
            raise UniverseDataError(
                "Tam (complete) evren kaydinda her degisiklik icin HTTPS kaynak zorunlu"
            )

    def _state_as_of(self, requested: date) -> dict[str, str]:
        state = dict(self._anchor)
        if requested < self.anchor_date:
            changes = [
                change
                for change in self._changes
                if requested < change.effective_date <= self.anchor_date
            ]
            for change in reversed(changes):
                self._apply(state, change, forward=False)
        elif requested > self.anchor_date:
            changes = [
                change
                for change in self._changes
                if self.anchor_date < change.effective_date <= requested
            ]
            for change in changes:
                self._apply(state, change, forward=True)
        return state

    @staticmethod
    def _apply(
        state: dict[str, str],
        change: UniverseChange,
        *,
        forward: bool,
    ) -> None:
        add_symbol = (change.action == "ADD") == forward
        if add_symbol:
            if change.symbol in state:
                direction = "ileri" if forward else "geri"
                raise UniverseDataError(
                    f"{direction} evren zinciri tutarsiz; sembol zaten var: {change.symbol}"
                )
            state[change.symbol] = change.sector
            return

        if change.symbol not in state:
            direction = "ileri" if forward else "geri"
            raise UniverseDataError(
                f"{direction} evren zinciri tutarsiz; sembol bulunamadi: {change.symbol}"
            )
        del state[change.symbol]
