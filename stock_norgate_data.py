"""Norgate Data adapter for survivorship-aware S&P 500 research.

Norgate's Python package talks to the locally running Norgate Data Updater.
The adapter is optional: importing this module does not require the proprietary
package, which keeps the rest of the project and its tests portable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Mapping, Optional

import pandas as pd

from stock_walkforward import normalize_history


NORGATE_SOURCE_URL = "https://norgatedata.com/data-content-tables.php"
DEFAULT_WATCHLIST = "S&P 500 Current & Past"
VALID_SECTOR_MODES = {"global", "current_gics"}


class NorgateDataError(RuntimeError):
    """Raised when Norgate is missing, unavailable, or incomplete."""


def _as_timestamp(value: object) -> pd.Timestamp:
    if isinstance(value, (date, datetime, pd.Timestamp)):
        result = pd.Timestamp(value)
    else:
        result = pd.Timestamp(str(value))
    if result.tz is not None:
        result = result.tz_localize(None)
    return result.normalize()


def _date_indexed(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    result = frame.copy()
    date_column = next(
        (column for column in result.columns if str(column).strip().lower() == "date"),
        None,
    )
    if date_column is not None:
        result = result.set_index(date_column)
    result.index = pd.to_datetime(result.index, errors="coerce")
    if getattr(result.index, "tz", None) is not None:
        result.index = result.index.tz_localize(None)
    result.index = result.index.normalize()
    return result.loc[~result.index.isna()].sort_index()


def _membership_series(
    annotated: pd.DataFrame,
    original_columns: set[object],
) -> pd.Series:
    frame = _date_indexed(annotated)
    if frame.empty:
        return pd.Series(dtype=bool)
    added = [column for column in frame.columns if column not in original_columns]
    preferred = [
        column
        for column in frame.columns
        if "constituent" in str(column).strip().lower()
        or "membership" in str(column).strip().lower()
    ]
    candidates = preferred or added
    if len(candidates) != 1:
        raise NorgateDataError(
            "Norgate endeks uyelik sutunu tekil olarak belirlenemedi: "
            f"{[str(column) for column in candidates]}"
        )
    values = pd.to_numeric(frame[candidates[0]], errors="coerce").fillna(0.0)
    result = values.ne(0.0)
    result = result.loc[~result.index.duplicated(keep="last")]
    return result.astype(bool)


class NorgateUniverseProvider:
    """Return the index members that were active on a requested date."""

    def __init__(
        self,
        memberships: Mapping[str, pd.Series],
        sectors: Mapping[str, str],
        *,
        coverage_start: object,
        coverage_end: object,
        sector_mode: str,
        index_name: str = "S&P 500",
        source_symbol_count: Optional[int] = None,
    ) -> None:
        if sector_mode not in VALID_SECTOR_MODES:
            raise ValueError(f"Gecersiz sector_mode: {sector_mode}")
        self.coverage_start = _as_timestamp(coverage_start)
        self.coverage_end = _as_timestamp(coverage_end)
        if self.coverage_start > self.coverage_end:
            raise ValueError("Norgate coverage tarihleri gecersiz")
        self.sector_mode = sector_mode
        self.index_name = str(index_name)
        self.source_symbol_count = int(source_symbol_count or len(memberships))
        self._memberships = {
            str(symbol): series.sort_index().astype(bool)
            for symbol, series in memberships.items()
            if series is not None and not series.empty
        }
        self._sectors = {
            str(symbol): str(sectors.get(symbol) or "Unknown")
            for symbol in self._memberships
        }
        if not self._memberships:
            raise NorgateDataError("Norgate uyelik serileri bos")

    @property
    def symbols(self) -> list[str]:
        return sorted(self._memberships)

    @property
    def metadata(self) -> dict[str, object]:
        global_factor_mode = self.sector_mode == "global"
        coverage_ratio = len(self._memberships) / self.source_symbol_count
        return {
            "provider": "NorgateData",
            "source": NORGATE_SOURCE_URL,
            "index_name": self.index_name,
            "coverage_start": self.coverage_start.date().isoformat(),
            "coverage_end": self.coverage_end.date().isoformat(),
            "candidate_symbols": len(self._memberships),
            "source_symbol_count": self.source_symbol_count,
            "symbol_coverage_ratio": coverage_ratio,
            "historical_membership": True,
            "delisted_securities_included": True,
            "sector_mode": self.sector_mode,
            "historical_sector_classification": False,
            "point_in_time_eligible": global_factor_mode and coverage_ratio >= 0.98,
        }

    def __call__(self, signal_date: object) -> dict[str, str]:
        requested = _as_timestamp(signal_date)
        if requested < self.coverage_start or requested > self.coverage_end:
            raise NorgateDataError(
                "Istenen tarih Norgate kapsaminin disinda: "
                f"{requested.date().isoformat()}"
            )
        active: dict[str, str] = {}
        for symbol, membership in self._memberships.items():
            available = membership.loc[membership.index <= requested]
            if not available.empty and bool(available.iloc[-1]):
                active[symbol] = self._sectors[symbol]
        return active


@dataclass(frozen=True)
class NorgateDataBundle:
    histories: dict[str, pd.DataFrame]
    benchmark: pd.DataFrame
    universe_provider: NorgateUniverseProvider
    diagnostics: dict[str, object]


class NorgateDataAdapter:
    def __init__(
        self,
        backend: Optional[object] = None,
        *,
        watchlist_name: str = DEFAULT_WATCHLIST,
        index_name: str = "S&P 500",
    ) -> None:
        self.backend = backend if backend is not None else self._import_backend()
        self.watchlist_name = watchlist_name
        self.index_name = index_name

    @staticmethod
    def _import_backend():
        client_root = Path(__file__).resolve().parent / ".cache" / "norgatedata-client"
        client_root.mkdir(parents=True, exist_ok=True)
        os.environ.setdefault("NORGATEDATA_ROOT", str(client_root))
        try:
            import norgatedata
        except ImportError as exc:
            raise NorgateDataError(
                "norgatedata Python paketi kurulu degil. "
                "Norgate Data Updater ve Python paketi gerekli."
            ) from exc
        return norgatedata

    def readiness(self) -> dict[str, object]:
        running = bool(self.backend.status())
        databases = list(self.backend.databases()) if running else []
        watchlists = list(self.backend.watchlists()) if running else []
        required_databases = {"US Equities", "US Equities Delisted"}
        missing_databases = sorted(required_databases - set(databases))
        ready = bool(
            running
            and not missing_databases
            and self.watchlist_name in watchlists
        )
        return {
            "ready": ready,
            "updater_running": running,
            "watchlist": self.watchlist_name,
            "watchlist_available": self.watchlist_name in watchlists,
            "missing_databases": missing_databases,
            "databases": databases,
        }

    def require_ready(self) -> dict[str, object]:
        status = self.readiness()
        if not status["ready"]:
            raise NorgateDataError(f"Norgate hazir degil: {status}")
        return status

    def _price_frame(self, symbol: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        raw = self.backend.price_timeseries(
            symbol,
            stock_price_adjustment_setting=self.backend.StockPriceAdjustmentType.TOTALRETURN,
            padding_setting=self.backend.PaddingType.NONE,
            start_date=start,
            end_date=end,
            timeseriesformat="pandas-dataframe",
        )
        raw = _date_indexed(raw)
        if raw.empty:
            return pd.DataFrame(), pd.DataFrame()
        history = normalize_history(raw)
        return raw, history

    def load_bundle(
        self,
        start_date: object,
        end_date: object,
        *,
        sector_mode: str = "global",
        benchmark_symbol: str = "SPY",
        minimum_coverage_ratio: float = 0.80,
    ) -> NorgateDataBundle:
        if sector_mode not in VALID_SECTOR_MODES:
            raise ValueError(f"Gecersiz sector_mode: {sector_mode}")
        self.require_ready()
        start = _as_timestamp(start_date).date().isoformat()
        end = _as_timestamp(end_date).date().isoformat()
        symbols = sorted(set(self.backend.watchlist_symbols(self.watchlist_name)))
        if not symbols:
            raise NorgateDataError(f"Norgate watchlist bos: {self.watchlist_name}")

        histories: dict[str, pd.DataFrame] = {}
        memberships: dict[str, pd.Series] = {}
        sectors: dict[str, str] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            try:
                raw, history = self._price_frame(symbol, start, end)
                if raw.empty or history.empty:
                    errors[symbol] = "price_missing"
                    continue
                annotated = self.backend.index_constituent_timeseries(
                    symbol,
                    self.index_name,
                    padding_setting=self.backend.PaddingType.NONE,
                    start_date=start,
                    end_date=end,
                    pandas_dataframe=raw,
                    timeseriesformat="pandas-dataframe",
                )
                membership = _membership_series(annotated, set(raw.columns))
                if membership.empty or not membership.any():
                    errors[symbol] = "membership_missing"
                    continue
                histories[symbol] = history
                memberships[symbol] = membership
                if sector_mode == "current_gics":
                    sector = self.backend.classification_at_level(
                        symbol, "GICS", "Name", 1
                    )
                    sectors[symbol] = str(sector or "Unknown")
                else:
                    sectors[symbol] = "Universe"
            except Exception as exc:
                errors[symbol] = f"{type(exc).__name__}: {str(exc)[:160]}"

        coverage_ratio = len(histories) / len(symbols)
        if coverage_ratio < minimum_coverage_ratio:
            raise NorgateDataError(
                f"Norgate fiyat/uyelik kapsami yetersiz: {len(histories)}/{len(symbols)} "
                f"(%{coverage_ratio * 100:.1f})"
            )

        _, benchmark = self._price_frame(benchmark_symbol, start, end)
        if benchmark.empty:
            raise NorgateDataError(f"Norgate benchmark verisi eksik: {benchmark_symbol}")
        provider = NorgateUniverseProvider(
            memberships,
            sectors,
            coverage_start=start,
            coverage_end=end,
            sector_mode=sector_mode,
            index_name=self.index_name,
            source_symbol_count=len(symbols),
        )
        diagnostics = {
            "source": "NorgateData",
            "watchlist": self.watchlist_name,
            "requested_symbols": len(symbols),
            "usable_symbols": len(histories),
            "coverage_ratio": coverage_ratio,
            "errors": errors,
            "sector_mode": sector_mode,
        }
        return NorgateDataBundle(histories, benchmark, provider, diagnostics)
