from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


_TIMEFRAME_PATTERN = re.compile(r"^(?P<count>[1-9]\d*)(?P<unit>[mhd])$")
_TIMEFRAME_UNITS = {
    "m": "minutes",
    "h": "hours",
    "d": "days",
}


def timeframe_delta(timeframe: str) -> pd.Timedelta:
    text = str(timeframe or "").strip().lower()
    match = _TIMEFRAME_PATTERN.fullmatch(text)
    if not match:
        raise ValueError(f"Desteklenmeyen timeframe: {timeframe!r}")
    count = int(match.group("count"))
    return pd.Timedelta(**{_TIMEFRAME_UNITS[match.group("unit")]: count})


def _datetime_index(index: Any, *, name: str) -> pd.DatetimeIndex:
    try:
        result = pd.DatetimeIndex(index)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} DatetimeIndex olmalıdır.") from exc
    if result.hasnans:
        raise ValueError(f"{name} NaT içeremez.")
    if not result.is_monotonic_increasing:
        raise ValueError(f"{name} artan zaman sırasına sahip olmalıdır.")
    if result.has_duplicates:
        raise ValueError(f"{name} yinelenen timestamp içeremez.")
    return result


@dataclass(frozen=True)
class FeatureAvailabilitySpec:
    """Bar-open timestamp'lerini gerçek karar/kullanılabilirlik zamanına çevirir."""

    schema_version: int = 6
    base_timeframe: str = "15m"
    source_timestamp_semantics: str = "bar_open"
    decision_timestamp_semantics: str = "bar_close"

    def __post_init__(self) -> None:
        timeframe_delta(self.base_timeframe)
        if self.source_timestamp_semantics != "bar_open":
            raise ValueError("V6 yalnızca bar_open kaynak timestamp semantiğini destekler.")
        if self.decision_timestamp_semantics != "bar_close":
            raise ValueError("V6 kararı tamamlanmış base mum kapanışında verir.")

    @property
    def base_delta(self) -> pd.Timedelta:
        return timeframe_delta(self.base_timeframe)

    def decision_times(self, target_bar_open_index: Any) -> pd.DatetimeIndex:
        target_index = _datetime_index(target_bar_open_index, name="target_index")
        return target_index + self.base_delta

    def source_available_times(
        self,
        source_bar_open_index: Any,
        *,
        source_timeframe: str,
    ) -> pd.DatetimeIndex:
        source_index = _datetime_index(source_bar_open_index, name="source_index")
        return source_index + timeframe_delta(source_timeframe)

    def align_completed_feature(
        self,
        source: pd.Series,
        target_bar_open_index: Any,
        *,
        source_timeframe: str,
        fill_value: float | None = None,
    ) -> pd.Series:
        if not isinstance(source, pd.Series):
            raise TypeError("source pandas Series olmalıdır.")

        source_index = _datetime_index(source.index, name="source.index")
        target_index = _datetime_index(target_bar_open_index, name="target_index")
        if (source_index.tz is None) != (target_index.tz is None):
            raise ValueError("source ve target timezone farkındalığı aynı olmalıdır.")

        numeric = pd.to_numeric(source, errors="coerce").replace([np.inf, -np.inf], np.nan)
        available = pd.Series(
            numeric.to_numpy(),
            index=self.source_available_times(
                source_index,
                source_timeframe=source_timeframe,
            ),
            name=source.name,
            dtype=float,
        )
        decision_index = self.decision_times(target_index)
        aligned = available.reindex(decision_index, method="ffill")
        aligned.index = target_index

        coverage_ratio = float(aligned.notna().mean()) if len(aligned) else 0.0
        aligned.attrs.update(
            {
                "schema_version": self.schema_version,
                "source_timeframe": source_timeframe,
                "base_timeframe": self.base_timeframe,
                "coverage_ratio_before_fill": coverage_ratio,
                "source_available_start": (
                    available.index[0].isoformat() if len(available) else None
                ),
                "source_available_end": (
                    available.index[-1].isoformat() if len(available) else None
                ),
            }
        )
        if fill_value is not None:
            aligned = aligned.fillna(float(fill_value))
            aligned.attrs["fill_value"] = float(fill_value)
        return aligned

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def contract_id(self) -> str:
        return _contract_id(self.to_dict())


@dataclass(frozen=True)
class FeatureCoverageSpec:
    """Seyrek dış veriyi point-in-time hizalar ve gerçek veri kapsamını ölçer."""

    schema_version: int = 6
    base_timeframe: str = "15m"
    recent_window_bars: int = 192
    min_total_coverage_ratio: float = 0.60
    min_recent_coverage_ratio: float = 0.95
    min_joint_available_bars: int = 1000

    def __post_init__(self) -> None:
        timeframe_delta(self.base_timeframe)
        if int(self.schema_version) != 6:
            raise ValueError("FeatureCoverageSpec yalnızca schema 6 içindir.")
        if int(self.recent_window_bars) < 1:
            raise ValueError("recent_window_bars en az 1 olmalıdır.")
        for name, value in (
            ("min_total_coverage_ratio", self.min_total_coverage_ratio),
            ("min_recent_coverage_ratio", self.min_recent_coverage_ratio),
        ):
            if not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} [0, 1] aralığında olmalıdır.")
        if int(self.min_joint_available_bars) < 1:
            raise ValueError("min_joint_available_bars en az 1 olmalıdır.")

    @property
    def base_delta(self) -> pd.Timedelta:
        return timeframe_delta(self.base_timeframe)

    def align_observations(
        self,
        source: pd.Series,
        target_bar_open_index: Any,
        *,
        feature_name: str,
        max_staleness_bars: int,
        baseline_value: float,
    ) -> pd.DataFrame:
        if not isinstance(source, pd.Series):
            raise TypeError("source pandas Series olmalıdır.")
        if int(max_staleness_bars) < 0:
            raise ValueError("max_staleness_bars negatif olamaz.")

        source_index = _datetime_index(source.index, name="source.index")
        target_index = _datetime_index(
            target_bar_open_index,
            name="target_index",
        )
        if (source_index.tz is None) != (target_index.tz is None):
            raise ValueError("source ve target timezone farkındalığı aynı olmalıdır.")

        numeric = pd.to_numeric(source, errors="coerce").replace(
            [np.inf, -np.inf],
            np.nan,
        )
        valid_source = numeric.dropna()
        valid_source = valid_source[~valid_source.index.duplicated(keep="last")]
        decision_index = target_index + self.base_delta

        value_at_decision = valid_source.reindex(decision_index, method="ffill")
        source_times = pd.Series(
            pd.DatetimeIndex(valid_source.index),
            index=valid_source.index,
        ).reindex(decision_index, method="ffill")
        age_bars = (
            pd.Series(decision_index, index=decision_index) - source_times
        ) / self.base_delta
        available = (
            value_at_decision.notna()
            & age_bars.notna()
            & (age_bars >= 0)
            & (age_bars <= int(max_staleness_bars))
        )
        observed = source_times.eq(pd.Series(decision_index, index=decision_index))

        result = pd.DataFrame(
            {
                feature_name: value_at_decision.where(
                    available,
                    float(baseline_value),
                ),
                f"{feature_name}_Available": available.astype("int8"),
                f"{feature_name}_Observed": observed.fillna(False).astype("int8"),
                f"{feature_name}_Age_Bars": age_bars.where(
                    age_bars.notna(),
                    float(max_staleness_bars + 1),
                ).astype(float),
            },
            index=decision_index,
        )
        result.index = target_index
        result.attrs["quality_report"] = self.quality_report(
            result,
            feature_name=feature_name,
            max_staleness_bars=max_staleness_bars,
            source_observations=len(valid_source),
        )
        result.attrs["coverage_contract_id"] = self.contract_id
        return result

    def quality_report(
        self,
        aligned: pd.DataFrame,
        *,
        feature_name: str,
        max_staleness_bars: int,
        source_observations: int | None = None,
    ) -> dict[str, Any]:
        available_column = f"{feature_name}_Available"
        observed_column = f"{feature_name}_Observed"
        age_column = f"{feature_name}_Age_Bars"
        missing = [
            column
            for column in (feature_name, available_column, observed_column, age_column)
            if column not in aligned.columns
        ]
        if missing:
            raise ValueError(f"Eksik coverage kolonları: {missing}")

        available = pd.to_numeric(
            aligned[available_column],
            errors="coerce",
        ).fillna(0).astype(bool)
        observed = pd.to_numeric(
            aligned[observed_column],
            errors="coerce",
        ).fillna(0).astype(bool)
        age = pd.to_numeric(aligned[age_column], errors="coerce")
        recent = available.tail(int(self.recent_window_bars))
        available_values = pd.to_numeric(
            aligned.loc[available, feature_name],
            errors="coerce",
        )
        available_index = aligned.index[available]
        stale = age > int(max_staleness_bars)
        total_rows = int(len(aligned))
        available_rows = int(available.sum())
        return {
            "feature": feature_name,
            "target_rows": total_rows,
            "source_observations": int(
                observed.sum()
                if source_observations is None
                else source_observations
            ),
            "observed_rows": int(observed.sum()),
            "available_rows": available_rows,
            "coverage_ratio": (
                float(available_rows / total_rows) if total_rows else 0.0
            ),
            "recent_window_rows": int(len(recent)),
            "recent_coverage_ratio": (
                float(recent.mean()) if len(recent) else 0.0
            ),
            "baseline_ratio": (
                float(1.0 - (available_rows / total_rows))
                if total_rows
                else 1.0
            ),
            "stale_ratio": (
                float(stale.fillna(False).mean()) if total_rows else 0.0
            ),
            "latest_available": bool(available.iloc[-1]) if total_rows else False,
            "first_available_at": (
                available_index[0].isoformat() if len(available_index) else None
            ),
            "last_available_at": (
                available_index[-1].isoformat() if len(available_index) else None
            ),
            "real_zero_count": int((available_values == 0.0).sum()),
            "max_staleness_bars": int(max_staleness_bars),
        }

    def validate_report(self, report: dict[str, Any]) -> None:
        if not isinstance(report, dict):
            raise ValueError("Feature coverage raporu sözlük olmalıdır.")
        feature_name = str(report.get("feature") or "UNKNOWN")
        try:
            target_rows = int(report.get("target_rows"))
            coverage_ratio = float(report.get("coverage_ratio"))
            recent_coverage_ratio = float(report.get("recent_coverage_ratio"))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{feature_name} coverage raporu sayısal olarak geçersiz."
            ) from exc
        if target_rows < 1:
            raise ValueError(f"{feature_name} coverage raporu boş.")
        for name, value in (
            ("coverage_ratio", coverage_ratio),
            ("recent_coverage_ratio", recent_coverage_ratio),
        ):
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(
                    f"{feature_name} {name} değeri geçersiz."
                )
        if coverage_ratio < float(
            self.min_total_coverage_ratio
        ):
            raise ValueError(f"{feature_name} toplam coverage eşiğinin altında.")
        if recent_coverage_ratio < float(
            self.min_recent_coverage_ratio
        ):
            raise ValueError(f"{feature_name} recent coverage eşiğinin altında.")
        if not bool(report.get("latest_available")):
            raise ValueError(f"{feature_name} son mumda kullanılabilir değil.")

    def validate_frame_report(
        self,
        frame: pd.DataFrame,
        *,
        feature_name: str,
        report: dict[str, Any],
    ) -> None:
        self.validate_report(report)
        available_column = f"{feature_name}_Available"
        if available_column not in frame.columns:
            raise ValueError(f"{available_column} eksik.")
        available_numeric = pd.to_numeric(
            frame[available_column],
            errors="coerce",
        )
        if available_numeric.isna().any():
            raise ValueError(f"{available_column} geçersiz değer içeriyor.")
        if not available_numeric.isin((0, 1)).all():
            raise ValueError(f"{available_column} yalnızca 0/1 içerebilir.")

        available = available_numeric.astype(bool)
        target_rows = int(len(frame))
        recent = available.tail(int(self.recent_window_bars))
        actual_coverage = (
            float(available.mean()) if target_rows else 0.0
        )
        actual_recent_coverage = (
            float(recent.mean()) if len(recent) else 0.0
        )
        expected = {
            "target_rows": target_rows,
            "coverage_ratio": actual_coverage,
            "recent_coverage_ratio": actual_recent_coverage,
            "latest_available": (
                bool(available.iloc[-1]) if target_rows else False
            ),
        }
        for key, actual in expected.items():
            reported = report.get(key)
            if isinstance(actual, float):
                try:
                    matches = math.isclose(
                        float(reported),
                        actual,
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                except (TypeError, ValueError):
                    matches = False
            else:
                matches = reported == actual
            if not matches:
                raise ValueError(
                    f"{feature_name} coverage raporu {key} ile "
                    "DataFrame maskesi uyuşmuyor."
                )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def contract_id(self) -> str:
        return _contract_id(self.to_dict())


@dataclass(frozen=True)
class OutcomeSpec:
    """V6 long alpha hedefi: sonraki yürütülebilir girişten sabit ufuk net sonuç."""

    schema_version: int = 6
    horizon_bars: int = 4
    round_trip_cost_rate: float = 0.001
    minimum_edge_rate: float = 0.0005
    entry_policy: str = "next_bar_open"
    exit_policy: str = "fixed_horizon_close"
    label_mode: str = "long_terminal_net_return"

    def __post_init__(self) -> None:
        if int(self.horizon_bars) < 1:
            raise ValueError("horizon_bars en az 1 olmalıdır.")
        if not 0.0 <= float(self.round_trip_cost_rate) < 1.0:
            raise ValueError("round_trip_cost_rate [0, 1) aralığında olmalıdır.")
        if not 0.0 <= float(self.minimum_edge_rate) < 1.0:
            raise ValueError("minimum_edge_rate [0, 1) aralığında olmalıdır.")
        if self.entry_policy != "next_bar_open":
            raise ValueError("V6 yalnızca next_bar_open giriş politikasını destekler.")
        if self.exit_policy != "fixed_horizon_close":
            raise ValueError("V6 yalnızca fixed_horizon_close çıkış politikasını destekler.")
        if self.label_mode != "long_terminal_net_return":
            raise ValueError("V6 yalnızca long_terminal_net_return etiketini destekler.")

    @property
    def positive_gross_return_threshold(self) -> float:
        return float(self.round_trip_cost_rate + self.minimum_edge_rate)

    def returns(self, entry_price: float, exit_price: float) -> tuple[float, float]:
        entry = float(entry_price)
        exit_ = float(exit_price)
        if not np.isfinite(entry) or not np.isfinite(exit_) or entry <= 0 or exit_ <= 0:
            raise ValueError("entry_price ve exit_price pozitif sonlu sayı olmalıdır.")
        gross_return = (exit_ - entry) / entry
        net_return = gross_return - float(self.round_trip_cost_rate)
        return float(gross_return), float(net_return)

    def classify_long(self, entry_price: float, exit_price: float) -> int:
        _, net_return = self.returns(entry_price, exit_price)
        return int(net_return + 1e-12 >= float(self.minimum_edge_rate))

    def build_long_outcomes(
        self,
        frame: pd.DataFrame,
        *,
        open_column: str = "open",
        close_column: str = "Hedef_Close",
    ) -> pd.DataFrame:
        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame pandas DataFrame olmalıdır.")
        missing = [
            column
            for column in (open_column, close_column)
            if column not in frame.columns
        ]
        if missing:
            raise ValueError(f"Eksik outcome kolonları: {missing}")

        entry = pd.to_numeric(frame[open_column], errors="coerce").shift(-1)
        exit_ = pd.to_numeric(frame[close_column], errors="coerce").shift(
            -int(self.horizon_bars)
        )
        valid = (
            entry.notna()
            & exit_.notna()
            & np.isfinite(entry)
            & np.isfinite(exit_)
            & (entry > 0)
            & (exit_ > 0)
        )
        gross_return = (exit_ - entry) / entry
        net_return = gross_return - float(self.round_trip_cost_rate)

        label = pd.Series(pd.NA, index=frame.index, dtype="Int8")
        label.loc[valid] = (
            net_return.loc[valid] + 1e-12 >= float(self.minimum_edge_rate)
        ).astype("int8")

        return pd.DataFrame(
            {
                "entry_price": entry.where(valid),
                "exit_price": exit_.where(valid),
                "gross_return": gross_return.where(valid),
                "net_return": net_return.where(valid),
                "y_long": label,
            },
            index=frame.index,
        )

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["positive_gross_return_threshold"] = (
            self.positive_gross_return_threshold
        )
        return result

    @property
    def contract_id(self) -> str:
        return _contract_id(self.to_dict())


@dataclass(frozen=True)
class TemporalFold:
    """Orijinal zaman çizelgesinden türetilmiş tek bir walk-forward bölümü."""

    train_index: pd.DatetimeIndex
    purge_index: pd.DatetimeIndex
    validation_index: pd.DatetimeIndex
    embargo_index: pd.DatetimeIndex

    def select_eligible(self, eligible_index: Any) -> "TemporalFold":
        eligible = _datetime_index(eligible_index, name="eligible_index")
        return TemporalFold(
            train_index=self.train_index.intersection(eligible, sort=False),
            purge_index=self.purge_index,
            validation_index=self.validation_index.intersection(
                eligible,
                sort=False,
            ),
            embargo_index=self.embargo_index,
        )


@dataclass(frozen=True)
class PurgedWalkForwardSpec:
    """V6 için bar zamanına bağlı expanding-window CV ve holdout sözleşmesi."""

    schema_version: int = 6
    base_timeframe: str = "15m"
    horizon_bars: int = 4
    purge_bars: int = 4
    embargo_bars: int = 1
    n_splits: int = 3
    min_train_bars: int = 100
    min_train_fraction: float = 0.40
    min_validation_bars: int = 20

    def __post_init__(self) -> None:
        timeframe_delta(self.base_timeframe)
        if int(self.schema_version) != 6:
            raise ValueError("PurgedWalkForwardSpec yalnızca schema 6 içindir.")
        if int(self.horizon_bars) < 1:
            raise ValueError("horizon_bars en az 1 olmalıdır.")
        if int(self.purge_bars) < int(self.horizon_bars):
            raise ValueError("purge_bars etiket ufkundan kısa olamaz.")
        if int(self.embargo_bars) < 0:
            raise ValueError("embargo_bars negatif olamaz.")
        if int(self.n_splits) < 2:
            raise ValueError("n_splits en az 2 olmalıdır.")
        if int(self.min_train_bars) < 1:
            raise ValueError("min_train_bars en az 1 olmalıdır.")
        if not 0.0 < float(self.min_train_fraction) < 1.0:
            raise ValueError("min_train_fraction (0, 1) aralığında olmalıdır.")
        if int(self.min_validation_bars) < 1:
            raise ValueError("min_validation_bars en az 1 olmalıdır.")

    @property
    def base_delta(self) -> pd.Timedelta:
        return timeframe_delta(self.base_timeframe)

    def validate_index(self, index: Any) -> pd.DatetimeIndex:
        result = _datetime_index(index, name="split_index")
        if len(result) > 1:
            deltas = result[1:] - result[:-1]
            if not bool(np.all(deltas == self.base_delta)):
                raise ValueError(
                    f"split_index kesintisiz {self.base_timeframe} aralığında "
                    "olmalıdır."
                )
        return result

    def decision_times(self, index: Any) -> pd.DatetimeIndex:
        return self.validate_index(index) + self.base_delta

    def label_end_times(self, index: Any) -> pd.DatetimeIndex:
        return self.validate_index(index) + (
            (int(self.horizon_bars) + 1) * self.base_delta
        )

    def _fold(
        self,
        index: pd.DatetimeIndex,
        *,
        train_stop: int,
        validation_start: int,
        validation_stop: int,
        embargo_stop: int,
    ) -> TemporalFold:
        fold = TemporalFold(
            train_index=index[:train_stop],
            purge_index=index[train_stop:validation_start],
            validation_index=index[validation_start:validation_stop],
            embargo_index=index[validation_stop:embargo_stop],
        )
        if len(fold.train_index) < int(self.min_train_bars):
            raise ValueError("Walk-forward eğitim bölümü minimumdan kısa.")
        if len(fold.validation_index) < int(self.min_validation_bars):
            raise ValueError("Walk-forward doğrulama bölümü minimumdan kısa.")
        if len(fold.purge_index) < int(self.purge_bars):
            raise ValueError("Walk-forward purge bölümü sözleşmeden kısa.")

        last_train_label_end = self.label_end_times(fold.train_index[-1:])[0]
        first_validation_decision = self.decision_times(
            fold.validation_index[:1]
        )[0]
        if last_train_label_end >= first_validation_decision:
            raise ValueError("Train etiketi doğrulama karar zamanına taşıyor.")
        return fold

    def holdout_split(
        self,
        index: Any,
        *,
        holdout_bars: int,
    ) -> TemporalFold:
        timeline = self.validate_index(index)
        holdout_size = int(holdout_bars)
        if holdout_size < int(self.min_validation_bars):
            raise ValueError("Holdout bölümü minimumdan kısa.")

        validation_start = len(timeline) - holdout_size
        train_stop = validation_start - int(self.purge_bars)
        if train_stop < int(self.min_train_bars):
            raise ValueError("Holdout öncesi eğitim bölümü minimumdan kısa.")
        return self._fold(
            timeline,
            train_stop=train_stop,
            validation_start=validation_start,
            validation_stop=len(timeline),
            embargo_stop=len(timeline),
        )

    def walk_forward_splits(self, index: Any) -> tuple[TemporalFold, ...]:
        timeline = self.validate_index(index)
        split_count = int(self.n_splits)
        embargo = int(self.embargo_bars)
        initial_train_bars = max(
            int(self.min_train_bars),
            int(math.ceil(len(timeline) * float(self.min_train_fraction))),
        )
        available = (
            len(timeline)
            - initial_train_bars
            - int(self.purge_bars)
            - ((split_count - 1) * embargo)
        )
        validation_size = available // split_count
        if validation_size < int(self.min_validation_bars):
            raise ValueError("Walk-forward doğrulama bölümleri için veri yetersiz.")

        validation_total = (
            (split_count * validation_size)
            + ((split_count - 1) * embargo)
        )
        first_validation_start = len(timeline) - validation_total
        folds = []
        for split_number in range(split_count):
            validation_start = first_validation_start + (
                split_number * (validation_size + embargo)
            )
            validation_stop = validation_start + validation_size
            embargo_stop = min(
                len(timeline),
                validation_stop + (embargo if split_number < split_count - 1 else 0),
            )
            folds.append(
                self._fold(
                    timeline,
                    train_stop=validation_start - int(self.purge_bars),
                    validation_start=validation_start,
                    validation_stop=validation_stop,
                    embargo_stop=embargo_stop,
                )
            )
        return tuple(folds)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def contract_id(self) -> str:
        return _contract_id(self.to_dict())


def _contract_id(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
