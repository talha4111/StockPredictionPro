"""
Leakage-aware walk-forward diagnostics for the US stock research engine.

The default mode intentionally tests only the price-derived momentum/risk
sleeve. A full Factor v3.1 run is allowed only when callers provide
point-in-time fundamentals. Results based on the current static universe are
always labelled diagnostic because they contain survivorship bias.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Optional

import numpy as np
import pandas as pd
import yfinance as yf


WALK_FORWARD_VERSION = "stock-walk-forward-v1.0"
YFINANCE_CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "yfinance"
try:
    YFINANCE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(YFINANCE_CACHE_DIR))
except OSError:
    pass

FundamentalProvider = Callable[[pd.Timestamp, list[str]], Mapping[str, Mapping[str, object]]]
UniverseProvider = Callable[[pd.Timestamp], Mapping[str, str]]


@dataclass(frozen=True)
class WalkForwardConfig:
    start_date: str
    end_date: Optional[str] = None
    top_n: int = 12
    min_positions: int = 5
    sector_cap: float = 0.25
    max_position_weight: float = 0.10
    transaction_cost_bps: float = 10.0
    cash_buffer: float = 0.0
    min_avg_dollar_volume: float = 5_000_000.0
    min_history_days: int = 252
    benchmark_symbol: str = "SPY"
    strategy_mode: str = "price_sleeve"
    fundamental_mode: str = "price_only"
    universe_mode: str = "current_static"
    event_risk_mode: str = "not_modeled"
    selection_policy: str = "auto"
    quality_weight: float = 0.35
    value_weight: float = 0.20
    momentum_weight: float = 0.30
    risk_weight: float = 0.15

    def resolved_selection_policy(self) -> str:
        if self.selection_policy == "auto":
            return "factor_rank" if self.strategy_mode == "full_factor" else "price_trend"
        return self.selection_policy

    def normalized_factor_weights(self) -> dict[str, float]:
        from quantconnect_top20.factor_core import normalize_factor_weights

        return normalize_factor_weights({
            "quality": self.quality_weight,
            "value": self.value_weight,
            "momentum": self.momentum_weight,
            "risk": self.risk_weight,
        })

    def validate(
        self,
        fundamental_provider: Optional[FundamentalProvider],
        universe_provider: Optional[UniverseProvider],
    ) -> None:
        if self.strategy_mode not in {"price_sleeve", "full_factor"}:
            raise ValueError("strategy_mode price_sleeve veya full_factor olmali")
        if self.fundamental_mode not in {"price_only", "point_in_time"}:
            raise ValueError("fundamental_mode price_only veya point_in_time olmali")
        if self.universe_mode not in {"current_static", "point_in_time"}:
            raise ValueError("universe_mode current_static veya point_in_time olmali")
        if self.event_risk_mode not in {"not_modeled", "point_in_time"}:
            raise ValueError("event_risk_mode not_modeled veya point_in_time olmali")
        policy = self.resolved_selection_policy()
        if policy not in {"price_trend", "live_setups", "factor_rank"}:
            raise ValueError("selection_policy gecersiz")
        if self.strategy_mode == "price_sleeve" and policy != "price_trend":
            raise ValueError("price_sleeve yalniz price_trend secim politikasini destekler")
        if self.strategy_mode == "full_factor" and policy == "price_trend":
            raise ValueError("full_factor icin live_setups veya factor_rank kullanilmali")
        if self.strategy_mode == "full_factor" and self.fundamental_mode != "point_in_time":
            raise ValueError("full_factor icin point-in-time temel veri zorunlu")
        if self.fundamental_mode == "point_in_time" and fundamental_provider is None:
            raise ValueError("point-in-time temel veri saglayicisi eksik")
        if self.universe_mode == "point_in_time" and universe_provider is None:
            raise ValueError("point-in-time evren saglayicisi eksik")
        if self.top_n < 1 or self.min_positions < 1 or self.min_positions > self.top_n:
            raise ValueError("pozisyon sayisi ayarlari gecersiz")
        if not 0 < self.sector_cap <= 1:
            raise ValueError("sector_cap 0 ile 1 arasinda olmali")
        if not 0 < self.max_position_weight <= 1:
            raise ValueError("max_position_weight 0 ile 1 arasinda olmali")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps negatif olamaz")
        if not 0 <= self.cash_buffer < 1:
            raise ValueError("cash_buffer 0 dahil ve 1 haric aralikta olmali")
        self.normalized_factor_weights()


def normalize_history(frame: pd.DataFrame) -> pd.DataFrame:
    """Return sorted, timezone-naive adjusted OHLCV data."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    if frame.attrs.get("stock_walkforward_normalized"):
        return frame

    result = frame.copy()
    if isinstance(result.columns, pd.MultiIndex):
        if len(result.columns.levels) == 2 and len(result.columns.get_level_values(0).unique()) == 1:
            result.columns = result.columns.get_level_values(1)
        else:
            raise ValueError("Tek sembolluk fiyat tablosu bekleniyordu")

    rename = {str(column).strip().lower(): column for column in result.columns}
    raw_source = rename.get("rawclose") or rename.get("raw close") or rename.get("unadjusted close")
    raw_close = (
        pd.to_numeric(result[raw_source], errors="coerce").copy()
        if raw_source is not None else None
    )
    if "close" in rename and "adj close" in rename:
        if raw_close is None:
            raw_close = pd.to_numeric(result[rename["close"]], errors="coerce").copy()
        adjusted_close = pd.to_numeric(result[rename["adj close"]], errors="coerce")
        adjustment = adjusted_close / raw_close.replace(0.0, np.nan)
        for wanted in ("open", "high", "low", "close"):
            source = rename.get(wanted)
            if source is not None:
                result[source] = pd.to_numeric(result[source], errors="coerce") * adjustment
    elif "close" not in rename and "adj close" in rename:
        result["Close"] = result[rename["adj close"]]
        rename["close"] = "Close"

    standard = {}
    for wanted in ("open", "high", "low", "close", "volume"):
        source = rename.get(wanted)
        if source is not None:
            standard[source] = wanted.title()
    result = result.rename(columns=standard)
    required = ["Open", "High", "Low", "Close", "Volume"]
    if not set(required).issubset(result.columns):
        return pd.DataFrame()
    result["RawClose"] = raw_close.to_numpy() if raw_close is not None else result["Close"]

    index = pd.to_datetime(result.index, errors="coerce")
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    result.index = index.normalize()
    result = result.loc[~result.index.isna(), required + ["RawClose"]].copy()
    for column in required:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    result["RawClose"] = pd.to_numeric(result["RawClose"], errors="coerce")
    result = result[~result.index.duplicated(keep="last")].sort_index()
    result = result.dropna(subset=["Close"])
    result.attrs["stock_walkforward_normalized"] = True
    return result


def _rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False, min_periods=length).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    result = 100.0 - 100.0 / (1.0 + rs)
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    return result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous_close = frame["Close"].shift(1)
    ranges = pd.concat(
        [
            frame["High"] - frame["Low"],
            (frame["High"] - previous_close).abs(),
            (frame["Low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1).ewm(
        alpha=1 / length,
        adjust=False,
        min_periods=length,
    ).mean()


def price_features_as_of(
    symbol: str,
    sector: str,
    history: pd.DataFrame,
    signal_date: pd.Timestamp,
    min_history_days: int = 252,
    min_avg_dollar_volume: float = 5_000_000.0,
) -> Optional[dict]:
    """Calculate features using rows available on or before signal_date only."""
    frame = normalize_history(history)
    as_of = pd.Timestamp(signal_date).normalize()
    frame = frame.loc[frame.index <= as_of]
    if len(frame) < min_history_days or len(frame) < 252:
        return None

    close = frame["Close"].astype(float)
    volume = frame["Volume"].astype(float)
    price = float(close.iloc[-1])
    if not np.isfinite(price) or price <= 0:
        return None

    sma_50 = close.rolling(50, min_periods=50).mean()
    sma_200 = close.rolling(200, min_periods=200).mean()
    rsi = _rsi(close)
    atr = _atr(frame)
    indicator_values = (sma_50.iloc[-1], sma_200.iloc[-1], rsi.iloc[-1], atr.iloc[-1])
    if any(pd.isna(value) for value in indicator_values):
        return None

    raw_close = frame["RawClose"].astype(float) if "RawClose" in frame else close
    avg_dollar_volume = float((raw_close * volume).iloc[-20:].mean())
    if not np.isfinite(avg_dollar_volume) or avg_dollar_volume < min_avg_dollar_volume:
        return None

    returns = close.pct_change().dropna()
    recent_returns = returns.iloc[-63:]
    downside = recent_returns.loc[recent_returns < 0]
    realized_vol = float(recent_returns.std(ddof=0) * np.sqrt(252))
    downside_vol = (
        float(downside.std(ddof=0) * np.sqrt(252))
        if len(downside) >= 2 else 0.0
    )
    trailing = close.iloc[-252:]
    rolling_peak = trailing.cummax()
    max_drawdown = float((trailing / rolling_peak - 1.0).min())
    high_52w = float(trailing.max())
    atr_value = float(atr.iloc[-1])
    sma_50_value = float(sma_50.iloc[-1])
    sma_200_value = float(sma_200.iloc[-1])

    return {
        "sembol": symbol,
        "sektor": sector,
        "fiyat": price,
        "sma_50": sma_50_value,
        "sma_200": sma_200_value,
        "rsi": float(rsi.iloc[-1]),
        "atr": atr_value,
        "sma50_atr_uzaklik": (
            (price - sma_50_value) / atr_value if atr_value > 0 else None
        ),
        "golden_cross": sma_50_value > sma_200_value,
        "momentum_12_1": float(close.iloc[-22] / close.iloc[-252] - 1.0),
        "momentum_6_1": float(close.iloc[-22] / close.iloc[-126] - 1.0),
        "distance_52w_high": float(price / high_52w - 1.0),
        "realized_vol_63d": realized_vol,
        "downside_vol_63d": downside_vol,
        "max_drawdown_1y": max_drawdown,
        "avg_dollar_volume": avg_dollar_volume,
        "bilanco_riski": False,
        "veri_tarihi": frame.index[-1].date().isoformat(),
        "success": True,
    }


def _percentile_scores(rows: list[dict], metric: str, higher_is_better: bool) -> dict[int, float]:
    values = {
        index: row.get(metric)
        for index, row in enumerate(rows)
        if row.get(metric) is not None and np.isfinite(float(row[metric]))
    }
    if not values:
        return {}
    if len(values) == 1:
        return {next(iter(values)): 50.0}
    series = pd.Series(values, dtype=float)
    ranks = series.rank(method="average", ascending=higher_is_better)
    return {
        index: float((rank - 1.0) / (len(series) - 1.0) * 100.0)
        for index, rank in ranks.items()
    }


def rank_price_sleeve(rows: list[dict]) -> list[dict]:
    """Rank the historical momentum/risk sleeve without fundamental claims."""
    metrics = {
        "momentum": (
            ("momentum_12_1", True),
            ("momentum_6_1", True),
            ("distance_52w_high", True),
        ),
        "risk": (
            ("realized_vol_63d", False),
            ("downside_vol_63d", False),
            ("max_drawdown_1y", True),
        ),
    }
    score_maps = {
        metric: _percentile_scores(rows, metric, higher)
        for factor_metrics in metrics.values()
        for metric, higher in factor_metrics
    }

    ranked = []
    for index, source in enumerate(rows):
        row = dict(source)
        momentum_scores = [score_maps[name].get(index) for name, _ in metrics["momentum"]]
        risk_scores = [score_maps[name].get(index) for name, _ in metrics["risk"]]
        momentum_scores = [score for score in momentum_scores if score is not None]
        risk_scores = [score for score in risk_scores if score is not None]
        if len(momentum_scores) < 2 or len(risk_scores) < 2:
            continue
        momentum_score = float(np.mean(momentum_scores))
        risk_score = float(np.mean(risk_scores))
        row["momentum_skor"] = round(momentum_score, 2)
        row["risk_skor"] = round(risk_score, 2)
        row["price_sleeve_skor"] = round(momentum_score * (2 / 3) + risk_score * (1 / 3), 2)
        atr_distance = row.get("sma50_atr_uzaklik")
        row["eligible"] = bool(
            row["fiyat"] > row["sma_200"]
            and row["sma_50"] > row["sma_200"]
            and row["momentum_12_1"] > 0
            and row["rsi"] <= 72
            and atr_distance is not None
            and atr_distance <= 3.0
        )
        ranked.append(row)
    return sorted(ranked, key=lambda row: row["price_sleeve_skor"], reverse=True)


def _rank_full_factor(
    rows: list[dict],
    snapshots: Mapping[str, Mapping[str, object]],
    selection_policy: str,
    factor_weights: Optional[Mapping[str, float]] = None,
) -> list[dict]:
    from stock_value_engine import faktor_siralama_uygula

    enriched = []
    for source in rows:
        row = dict(source)
        snapshot = snapshots.get(row["sembol"])
        if snapshot:
            row.update(dict(snapshot))
        enriched.append(row)
    ranked = faktor_siralama_uygula(enriched, faktor_agirliklari=factor_weights)
    for row in ranked:
        if selection_policy == "live_setups":
            row["eligible"] = row.get("karar") == "AL_ADAYI"
        else:
            row["eligible"] = bool(
                row.get("faktor_skor") is not None
                and row.get("faktor_kapsami", 0.0) >= 0.75
            )
    if selection_policy == "factor_rank":
        ranked = sorted(
            ranked,
            key=lambda row: (
                not row.get("eligible", False),
                -(row.get("faktor_skor") or -1.0),
            ),
        )
    return ranked


def _ranking_diagnostics(
    ranked: list[dict],
    score_key: str,
    forward_returns: Mapping[str, float],
) -> dict:
    pairs = [
        (float(row[score_key]), float(forward_returns[row["sembol"]]))
        for row in ranked
        if row.get(score_key) is not None and row["sembol"] in forward_returns
        and np.isfinite(float(row[score_key]))
        and np.isfinite(float(forward_returns[row["sembol"]]))
    ]
    if len(pairs) < 8:
        return {
            "sample": len(pairs),
            "rank_ic": None,
            "top_quartile_return": None,
            "bottom_quartile_return": None,
            "quartile_spread": None,
        }
    frame = pd.DataFrame(pairs, columns=["score", "forward_return"])
    score_rank = frame["score"].rank(method="average")
    return_rank = frame["forward_return"].rank(method="average")
    rank_ic = score_rank.corr(return_rank)
    ordered = frame.sort_values("score")
    quartile_size = max(1, len(ordered) // 4)
    bottom_return = float(ordered.head(quartile_size)["forward_return"].mean())
    top_return = float(ordered.tail(quartile_size)["forward_return"].mean())
    return {
        "sample": len(pairs),
        "rank_ic": float(rank_ic) if pd.notna(rank_ic) else None,
        "top_quartile_return": top_return,
        "bottom_quartile_return": bottom_return,
        "quartile_spread": top_return - bottom_return,
    }


def _monthly_signal_dates(
    benchmark: pd.DataFrame,
    start_date: str,
    end_date: Optional[str],
) -> list[pd.Timestamp]:
    frame = normalize_history(benchmark)
    if frame.empty:
        return []
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize() if end_date else frame.index[-1]
    available = frame.loc[(frame.index >= start) & (frame.index <= end)]
    if available.empty:
        return []
    dates = pd.Series(available.index, index=available.index)
    return list(dates.groupby(available.index.to_period("M")).max())


def _next_session(index: pd.DatetimeIndex, date: pd.Timestamp) -> Optional[pd.Timestamp]:
    position = index.searchsorted(pd.Timestamp(date).normalize(), side="right")
    if position >= len(index):
        return None
    return pd.Timestamp(index[position]).normalize()


def _price_at(frame: pd.DataFrame, date: pd.Timestamp, column: str) -> Optional[float]:
    history = normalize_history(frame)
    if date not in history.index or column not in history.columns:
        return None
    value = history.at[date, column]
    if pd.isna(value) or not np.isfinite(float(value)) or float(value) <= 0:
        return None
    return float(value)


def _security_return(
    frame: pd.DataFrame,
    entry_date: pd.Timestamp,
    exit_date: pd.Timestamp,
) -> tuple[Optional[float], Optional[str]]:
    entry = _price_at(frame, entry_date, "Open")
    if entry is None:
        return None, "entry_missing"
    exit_price = _price_at(frame, exit_date, "Open")
    if exit_price is not None:
        return float(exit_price / entry - 1.0), None

    history = normalize_history(frame)
    fallback = history.loc[(history.index > entry_date) & (history.index <= exit_date), "Close"].dropna()
    if fallback.empty:
        return -1.0, "exit_missing_total_loss"
    return float(fallback.iloc[-1] / entry - 1.0), "exit_last_close"


def _select_symbols(ranked: list[dict], top_n: int) -> list[dict]:
    selected = []
    for row in ranked:
        if not row.get("eligible"):
            continue
        selected.append(row)
        if len(selected) >= top_n:
            break
    return selected


def _target_weights(
    selected: list[dict],
    config: WalkForwardConfig,
) -> dict[str, float]:
    if len(selected) < config.min_positions:
        return {}
    base_weight = min(1.0 / len(selected), config.max_position_weight)
    by_sector: dict[str, list[str]] = {}
    for row in selected:
        by_sector.setdefault(str(row.get("sektor", "Unknown")), []).append(row["sembol"])

    weights = {}
    for symbols in by_sector.values():
        per_symbol = min(base_weight, config.sector_cap / len(symbols))
        for symbol in symbols:
            weights[symbol] = per_symbol * (1.0 - config.cash_buffer)
    return weights


def _turnover(previous: Mapping[str, float], target: Mapping[str, float]) -> float:
    symbols = set(previous) | set(target)
    security_change = sum(abs(target.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols)
    previous_cash = max(0.0, 1.0 - sum(previous.values()))
    target_cash = max(0.0, 1.0 - sum(target.values()))
    return float(0.5 * (security_change + abs(target_cash - previous_cash)))


def _drift_weights(weights: Mapping[str, float], returns: Mapping[str, float]) -> dict[str, float]:
    cash = max(0.0, 1.0 - sum(weights.values()))
    values = {
        symbol: weight * (1.0 + returns.get(symbol, 0.0))
        for symbol, weight in weights.items()
    }
    total = cash + sum(values.values())
    if total <= 0:
        return {}
    return {symbol: max(0.0, value / total) for symbol, value in values.items() if value > 0}


def _portfolio_metrics(returns: list[float]) -> dict:
    if not returns:
        return {
            "periods": 0,
            "cumulative_return": None,
            "annualized_return": None,
            "annualized_volatility": None,
            "sharpe_zero_rf": None,
            "max_drawdown": None,
            "positive_period_rate": None,
        }
    values = np.asarray(returns, dtype=float)
    equity = np.cumprod(1.0 + values)
    cumulative = float(equity[-1] - 1.0)
    annualized = float(equity[-1] ** (12.0 / len(values)) - 1.0) if equity[-1] > 0 else -1.0
    volatility = float(np.std(values, ddof=1) * np.sqrt(12)) if len(values) > 1 else 0.0
    sharpe = float(np.mean(values) * 12 / volatility) if volatility > 0 else None
    running_peak = np.maximum.accumulate(np.insert(equity, 0, 1.0))[1:]
    max_drawdown = float(np.min(equity / running_peak - 1.0))
    return {
        "periods": int(len(values)),
        "cumulative_return": cumulative,
        "annualized_return": annualized,
        "annualized_volatility": volatility,
        "sharpe_zero_rf": sharpe,
        "max_drawdown": max_drawdown,
        "positive_period_rate": float(np.mean(values > 0)),
    }


def _annual_summary(records: list[dict]) -> list[dict]:
    by_year: dict[str, list[dict]] = {}
    for record in records:
        by_year.setdefault(record["signal_date"][:4], []).append(record)

    summary = []
    for year, rows in sorted(by_year.items()):
        net = np.asarray([row["net_return"] for row in rows], dtype=float)
        spy = np.asarray([row["spy_return"] for row in rows], dtype=float)
        equal_weight = np.asarray([row["equal_weight_return"] for row in rows], dtype=float)
        summary.append(
            {
                "year": year,
                "periods": len(rows),
                "strategy_return": float(np.prod(1.0 + net) - 1.0),
                "spy_return": float(np.prod(1.0 + spy) - 1.0),
                "equal_weight_return": float(np.prod(1.0 + equal_weight) - 1.0),
                "average_invested_weight": float(np.mean([row["invested_weight"] for row in rows])),
                "average_positions": float(np.mean([row["position_count"] for row in rows])),
                "win_rate_vs_spy": float(np.mean(net > spy)),
            }
        )
    return summary


def _provider_metadata(provider: object) -> dict[str, object]:
    if provider is None:
        return {}
    metadata = getattr(provider, "metadata", {})
    if callable(metadata):
        metadata = metadata()
    return dict(metadata) if isinstance(metadata, Mapping) else {}


def _validity(
    config: WalkForwardConfig,
    fundamental_provider: Optional[FundamentalProvider] = None,
    universe_provider: Optional[UniverseProvider] = None,
) -> dict:
    point_fundamentals = config.fundamental_mode == "point_in_time"
    fundamental_metadata = _provider_metadata(fundamental_provider)
    audited_fundamentals = bool(
        point_fundamentals and fundamental_metadata.get("point_in_time_eligible")
    )
    point_universe = config.universe_mode == "point_in_time"
    universe_metadata = _provider_metadata(universe_provider)
    audited_universe = bool(
        point_universe and universe_metadata.get("point_in_time_eligible")
    )
    event_calendar_required = config.resolved_selection_policy() == "live_setups"
    point_events = config.event_risk_mode == "point_in_time"
    # There is no historical event-calendar provider contract yet. A mode flag
    # alone must not certify production validity.
    audited_events = False
    event_requirement_met = not event_calendar_required or audited_events
    production_valid = bool(
        config.strategy_mode == "full_factor"
        and audited_fundamentals
        and audited_universe
        and event_requirement_met
    )
    warnings = []
    if config.strategy_mode == "price_sleeve":
        warnings.append("Bu test yalnizca momentum/risk ve trend kurulumunu olcer; tam Faktor v3.1 degildir.")
    if not point_fundamentals:
        warnings.append("Tarihsel temel veriler kullanilmadi; kalite ve deger faktorleri test edilmedi.")
    elif not audited_fundamentals:
        warnings.append(
            "Tarihsel temel veri saglayicisinin nokta-zaman sozlesmesi dogrulanamadi."
        )
    if not point_universe:
        warnings.append("Bugunku sabit hisse havuzu survivorship bias icerir.")
    elif not audited_universe:
        warnings.append(
            "Tarihsel evren saglayicisinin eksiksiz ve kaynakli oldugu dogrulanamadi."
        )
    if event_calendar_required and not audited_events:
        warnings.append("Tarihsel olarak bilinen bilanco takvimi modellenmedi.")
    return {
        "classification": "PRODUCTION_VALIDATION" if production_valid else "DIAGNOSTIC_ONLY",
        "production_valid": production_valid,
        "point_in_time_fundamentals": point_fundamentals,
        "point_in_time_fundamentals_audited": audited_fundamentals,
        "fundamental_metadata": fundamental_metadata,
        "point_in_time_universe": point_universe,
        "point_in_time_universe_audited": audited_universe,
        "universe_metadata": universe_metadata,
        "point_in_time_event_calendar": point_events,
        "point_in_time_event_calendar_audited": audited_events,
        "event_calendar_required": event_calendar_required,
        "warnings": warnings,
    }


def _apply_observed_coverage_validity(
    validity: dict,
    config: WalkForwardConfig,
    coverage_records: list[dict],
    minimum_ok_ratio: float = 0.90,
) -> dict:
    result = dict(validity)
    requested = sum(int(row.get("requested", 0)) for row in coverage_records)
    ok = sum(int(row.get("ok", 0)) for row in coverage_records)
    ratio = float(ok / requested) if requested else None
    result["observed_fundamental_ok_ratio"] = ratio
    result["minimum_fundamental_ok_ratio"] = minimum_ok_ratio
    if config.strategy_mode != "full_factor":
        return result
    if ratio is None or ratio < minimum_ok_ratio:
        result["classification"] = "DIAGNOSTIC_ONLY"
        result["production_valid"] = False
        warning = (
            "Gozlenen nokta-zaman temel veri kapsami uretim esiginin altinda: "
            f"{ratio:.1%} < {minimum_ok_ratio:.1%}"
            if ratio is not None
            else "Gozlenen nokta-zaman temel veri kapsami hesaplanamadi."
        )
        result["warnings"] = list(result.get("warnings", [])) + [warning]
    return result


def run_walk_forward(
    histories: Mapping[str, pd.DataFrame],
    sectors: Mapping[str, str],
    benchmark: pd.DataFrame,
    config: WalkForwardConfig,
    fundamental_provider: Optional[FundamentalProvider] = None,
    universe_provider: Optional[UniverseProvider] = None,
) -> dict:
    """Run a monthly signal/next-open walk-forward simulation."""
    config.validate(fundamental_provider, universe_provider)
    normalized_histories = {
        symbol: frame
        for symbol, source in histories.items()
        if not (frame := normalize_history(source)).empty
    }
    benchmark_frame = normalize_history(benchmark)
    signal_dates = _monthly_signal_dates(benchmark_frame, config.start_date, config.end_date)
    entries = [(date, _next_session(benchmark_frame.index, date)) for date in signal_dates]
    entries = [(date, entry) for date, entry in entries if entry is not None]

    records = []
    previous_end_weights: dict[str, float] = {}
    missing_data_events: dict[str, int] = {}
    fundamental_coverage_records = []

    for period_index in range(len(entries) - 1):
        signal_date, entry_date = entries[period_index]
        _, exit_date = entries[period_index + 1]
        if config.end_date and exit_date > pd.Timestamp(config.end_date).normalize():
            continue

        active_sectors = (
            dict(universe_provider(signal_date))
            if config.universe_mode == "point_in_time" and universe_provider
            else dict(sectors)
        )
        rows = []
        for symbol, sector in active_sectors.items():
            history = normalized_histories.get(symbol)
            if history is None:
                continue
            row = price_features_as_of(
                symbol,
                sector,
                history,
                signal_date,
                min_history_days=config.min_history_days,
                min_avg_dollar_volume=config.min_avg_dollar_volume,
            )
            if row is not None:
                rows.append(row)

        if config.strategy_mode == "full_factor":
            snapshots = fundamental_provider(signal_date, [row["sembol"] for row in rows])
            metric_counts = [
                int(snapshot.get("sec_metric_count", 0))
                for snapshot in snapshots.values()
            ]
            fundamental_coverage_records.append(
                {
                    "signal_date": signal_date.date().isoformat(),
                    "requested": len(rows),
                    "returned": len(snapshots),
                    "ok": sum(
                        snapshot.get("sec_data_status") == "OK"
                        for snapshot in snapshots.values()
                    ),
                    "average_metric_count": (
                        float(np.mean(metric_counts)) if metric_counts else 0.0
                    ),
                }
            )
            ranked = _rank_full_factor(
                rows,
                snapshots,
                config.resolved_selection_policy(),
                config.normalized_factor_weights(),
            )
            score_key = "faktor_skor"
        else:
            ranked = rank_price_sleeve(rows)
            score_key = "price_sleeve_skor"

        universe_returns_by_symbol = {}
        for symbol in active_sectors:
            history = normalized_histories.get(symbol)
            if history is None:
                continue
            security_return, issue = _security_return(history, entry_date, exit_date)
            if issue:
                missing_data_events[issue] = missing_data_events.get(issue, 0) + 1
            if security_return is not None:
                universe_returns_by_symbol[symbol] = security_return

        rank_diagnostics = _ranking_diagnostics(
            ranked,
            score_key,
            universe_returns_by_symbol,
        )
        selected_rows = _select_symbols(ranked, config.top_n)
        tradable_rows = [
            row for row in selected_rows if row["sembol"] in universe_returns_by_symbol
        ]
        selected_returns = {
            row["sembol"]: universe_returns_by_symbol[row["sembol"]]
            for row in tradable_rows
        }

        target_weights = _target_weights(tradable_rows, config)
        turnover = _turnover(previous_end_weights, target_weights)
        gross_return = float(
            sum(target_weights[symbol] * selected_returns[symbol] for symbol in target_weights)
        )
        cost = float(turnover * config.transaction_cost_bps / 10_000.0)
        net_return = gross_return - cost

        benchmark_return, benchmark_issue = _security_return(
            benchmark_frame, entry_date, exit_date
        )
        if benchmark_return is None:
            continue
        if benchmark_issue:
            missing_data_events[f"benchmark_{benchmark_issue}"] = (
                missing_data_events.get(f"benchmark_{benchmark_issue}", 0) + 1
            )

        universe_returns = list(universe_returns_by_symbol.values())
        equal_weight_return = float(np.mean(universe_returns)) if universe_returns else 0.0

        selected_summary = [
            {
                "symbol": row["sembol"],
                "sector": row.get("sektor"),
                "score": row.get(score_key),
                "weight": target_weights.get(row["sembol"], 0.0),
                "return": selected_returns.get(row["sembol"]),
            }
            for row in tradable_rows
        ]
        records.append(
            {
                "signal_date": signal_date.date().isoformat(),
                "entry_date": entry_date.date().isoformat(),
                "exit_date": exit_date.date().isoformat(),
                "universe_size": len(rows),
                "eligible_count": sum(bool(row.get("eligible")) for row in ranked),
                "position_count": len(target_weights),
                "invested_weight": float(sum(target_weights.values())),
                "turnover": turnover,
                "transaction_cost": cost,
                "gross_return": gross_return,
                "net_return": net_return,
                "spy_return": float(benchmark_return),
                "equal_weight_return": equal_weight_return,
                "rank_ic": rank_diagnostics["rank_ic"],
                "rank_sample": rank_diagnostics["sample"],
                "top_quartile_return": rank_diagnostics["top_quartile_return"],
                "bottom_quartile_return": rank_diagnostics["bottom_quartile_return"],
                "quartile_spread": rank_diagnostics["quartile_spread"],
                "selected": selected_summary,
            }
        )
        previous_end_weights = _drift_weights(target_weights, selected_returns)

    strategy_returns = [record["net_return"] for record in records]
    gross_returns = [record["gross_return"] for record in records]
    spy_returns = [record["spy_return"] for record in records]
    equal_weight_returns = [record["equal_weight_return"] for record in records]
    strategy_metrics = _portfolio_metrics(strategy_returns)
    gross_strategy_metrics = _portfolio_metrics(gross_returns)
    spy_metrics = _portfolio_metrics(spy_returns)
    equal_weight_metrics = _portfolio_metrics(equal_weight_returns)
    rank_ics = [record["rank_ic"] for record in records if record["rank_ic"] is not None]
    quartile_spreads = [
        record["quartile_spread"]
        for record in records
        if record["quartile_spread"] is not None
    ]
    ranking_summary = {
        "periods": len(rank_ics),
        "average_rank_ic": float(np.mean(rank_ics)) if rank_ics else None,
        "median_rank_ic": float(np.median(rank_ics)) if rank_ics else None,
        "positive_rank_ic_rate": float(np.mean(np.asarray(rank_ics) > 0)) if rank_ics else None,
        "average_quartile_spread": (
            float(np.mean(quartile_spreads)) if quartile_spreads else None
        ),
    }

    comparison = {
        "cumulative_excess_vs_spy": None,
        "cumulative_excess_vs_equal_weight": None,
        "period_win_rate_vs_spy": None,
        "period_win_rate_vs_equal_weight": None,
        "average_monthly_turnover": None,
        "average_invested_weight": None,
        "empty_portfolio_periods": None,
        "total_transaction_cost_drag": None,
        "compounded_cost_drag": None,
    }
    if records:
        strategy_equity = 1.0 + strategy_metrics["cumulative_return"]
        spy_equity = 1.0 + spy_metrics["cumulative_return"]
        ew_equity = 1.0 + equal_weight_metrics["cumulative_return"]
        comparison = {
            "cumulative_excess_vs_spy": float(strategy_equity / spy_equity - 1.0) if spy_equity > 0 else None,
            "cumulative_excess_vs_equal_weight": float(strategy_equity / ew_equity - 1.0) if ew_equity > 0 else None,
            "period_win_rate_vs_spy": float(np.mean(np.asarray(strategy_returns) > np.asarray(spy_returns))),
            "period_win_rate_vs_equal_weight": float(
                np.mean(np.asarray(strategy_returns) > np.asarray(equal_weight_returns))
            ),
            "average_monthly_turnover": float(np.mean([record["turnover"] for record in records])),
            "average_invested_weight": float(
                np.mean([record["invested_weight"] for record in records])
            ),
            "empty_portfolio_periods": int(
                sum(record["position_count"] == 0 for record in records)
            ),
            "total_transaction_cost_drag": float(sum(record["transaction_cost"] for record in records)),
            "compounded_cost_drag": float(
                gross_strategy_metrics["cumulative_return"] - strategy_metrics["cumulative_return"]
            ),
        }

    config_payload = asdict(config)
    config_payload["resolved_selection_policy"] = config.resolved_selection_policy()
    config_payload["normalized_factor_weights"] = config.normalized_factor_weights()
    validity = _apply_observed_coverage_validity(
        _validity(config, fundamental_provider, universe_provider),
        config,
        fundamental_coverage_records,
    )
    return {
        "engine_version": WALK_FORWARD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": config_payload,
        "validity": validity,
        "data_quality": {
            "histories_supplied": len(histories),
            "histories_usable": len(normalized_histories),
            "signal_months": len(signal_dates),
            "completed_periods": len(records),
            "missing_data_events": missing_data_events,
            "fundamental_coverage": {
                "periods": len(fundamental_coverage_records),
                "average_returned": (
                    float(np.mean([row["returned"] for row in fundamental_coverage_records]))
                    if fundamental_coverage_records else None
                ),
                "average_ok": (
                    float(np.mean([row["ok"] for row in fundamental_coverage_records]))
                    if fundamental_coverage_records else None
                ),
                "average_metric_count": (
                    float(np.mean([
                        row["average_metric_count"] for row in fundamental_coverage_records
                    ]))
                    if fundamental_coverage_records else None
                ),
                "by_period": fundamental_coverage_records,
            },
        },
        "metrics": {
            "strategy": strategy_metrics,
            "strategy_before_costs": gross_strategy_metrics,
            "spy": spy_metrics,
            "equal_weight_universe": equal_weight_metrics,
            "comparison": comparison,
            "ranking_diagnostics": ranking_summary,
        },
        "annual_summary": _annual_summary(records),
        "periods": records,
    }


def _extract_downloaded_symbol(raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if raw is None or raw.empty:
        return pd.DataFrame()
    if not isinstance(raw.columns, pd.MultiIndex):
        return normalize_history(raw)
    level_zero = raw.columns.get_level_values(0)
    level_one = raw.columns.get_level_values(1)
    if symbol in level_zero:
        return normalize_history(raw[symbol])
    if symbol in level_one:
        return normalize_history(raw.xs(symbol, axis=1, level=1))
    return pd.DataFrame()


def download_price_histories(
    symbols: list[str],
    start_date: str,
    end_date: str,
    cache_dir: str | Path = ".cache/stock_walkforward",
    chunk_size: int = 25,
) -> dict[str, pd.DataFrame]:
    """Download split-adjusted daily bars in bounded batches and cache them."""
    unique_symbols = sorted(set(symbols))
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256("|".join(unique_symbols).encode("ascii")).hexdigest()[:12]
    cache_file = cache_path / f"prices_v2_raw_{start_date}_{end_date}_{digest}.pkl"
    histories: dict[str, pd.DataFrame] = {}
    if cache_file.exists():
        cached = pd.read_pickle(cache_file)
        minimum_cache_size = max(1, math.ceil(len(unique_symbols) * 0.80))
        if isinstance(cached, dict) and len(cached) >= minimum_cache_size:
            for symbol, source in cached.items():
                if symbol not in unique_symbols:
                    continue
                frame = normalize_history(source)
                if not frame.empty:
                    histories[symbol] = frame
            if len(histories) == len(unique_symbols):
                return histories

    exclusive_end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).date().isoformat()
    symbols_to_download = [symbol for symbol in unique_symbols if symbol not in histories]
    for offset in range(0, len(symbols_to_download), chunk_size):
        chunk = symbols_to_download[offset:offset + chunk_size]
        try:
            raw = yf.download(
                chunk,
                start=start_date,
                end=exclusive_end,
                auto_adjust=False,
                group_by="ticker",
                progress=False,
                threads=True,
                timeout=30,
            )
        except Exception:
            continue
        for symbol in chunk:
            frame = _extract_downloaded_symbol(raw, symbol)
            if not frame.empty:
                histories[symbol] = frame

    missing = [symbol for symbol in unique_symbols if symbol not in histories]
    if histories and len(missing) <= max(10, math.ceil(len(unique_symbols) * 0.25)):
        for symbol in missing:
            try:
                frame = yf.Ticker(symbol).history(
                    start=start_date,
                    end=exclusive_end,
                    auto_adjust=False,
                    timeout=20,
                )
            except Exception:
                continue
            frame = normalize_history(frame)
            if not frame.empty:
                histories[symbol] = frame

    minimum_cache_size = max(1, math.ceil(len(unique_symbols) * 0.80))
    if len(histories) >= minimum_cache_size:
        pd.to_pickle(histories, cache_file)
    return histories


def _json_default(value):
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    raise TypeError(f"JSON'a cevrilemeyen tip: {type(value).__name__}")


def main() -> int:
    parser = argparse.ArgumentParser(description="US stock price-sleeve walk-forward diagnostic")
    parser.add_argument("--years", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=12)
    parser.add_argument("--cost-bps", type=float, default=10.0)
    parser.add_argument("--mode", choices=("price_sleeve", "full_factor"), default="price_sleeve")
    parser.add_argument(
        "--selection-policy",
        choices=("auto", "price_trend", "live_setups", "factor_rank"),
        default="auto",
    )
    parser.add_argument(
        "--universe-history",
        default=None,
        help="Denetlenmis nokta-zaman evren JSON dosyasi",
    )
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    from stock_value_engine import KURUMSAL_HAVUZ

    sec_client = None
    if args.mode == "full_factor":
        from sec_point_in_time import SECCompanyFactsClient

        sec_client = SECCompanyFactsClient.from_env()

    universe_provider = None
    universe_mode = "current_static"
    stock_symbols = list(KURUMSAL_HAVUZ)
    if args.universe_history:
        from stock_historical_universe import HistoricalUniverseProvider

        universe_provider = HistoricalUniverseProvider.from_json(args.universe_history)
        universe_mode = "point_in_time"
        stock_symbols = universe_provider.symbols

    end = pd.Timestamp.now(tz="America/New_York").tz_localize(None).normalize()
    start = end - pd.DateOffset(years=args.years)
    fetch_start = start - pd.DateOffset(days=420)
    symbols = stock_symbols + ["SPY"]
    print(f"Fiyat verisi indiriliyor: {len(symbols)} sembol...")
    histories = download_price_histories(
        symbols,
        fetch_start.date().isoformat(),
        end.date().isoformat(),
    )
    minimum_coverage = math.ceil(len(symbols) * 0.80)
    if len(histories) < minimum_coverage:
        raise RuntimeError(
            f"Fiyat kapsami yetersiz: {len(histories)}/{len(symbols)} "
            f"(minimum {minimum_coverage})"
        )
    benchmark = histories.pop("SPY", pd.DataFrame())
    if benchmark.empty:
        raise RuntimeError("SPY fiyat verisi indirilemedi")

    fundamental_provider = None
    fundamental_mode = "price_only"
    if args.mode == "full_factor":
        from sec_point_in_time import SECPointInTimeProvider

        fundamental_provider = SECPointInTimeProvider(sec_client, histories, progress=True)
        fundamental_mode = "point_in_time"

    config = WalkForwardConfig(
        start_date=start.date().isoformat(),
        end_date=end.date().isoformat(),
        top_n=args.top_n,
        min_positions=min(5, args.top_n),
        transaction_cost_bps=args.cost_bps,
        strategy_mode=args.mode,
        fundamental_mode=fundamental_mode,
        universe_mode=universe_mode,
        selection_policy=args.selection_policy,
    )
    result = run_walk_forward(
        histories,
        KURUMSAL_HAVUZ,
        benchmark,
        config,
        fundamental_provider=fundamental_provider,
        universe_provider=universe_provider,
    )
    default_output = (
        "data/stock_walkforward_full_factor.json"
        if args.mode == "full_factor"
        else "data/stock_walkforward_diagnostic.json"
    )
    output = Path(args.output or default_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, ensure_ascii=True, allow_nan=False, default=_json_default),
        encoding="utf-8",
    )

    metrics = result["metrics"]
    strategy = metrics["strategy"]
    comparison = metrics["comparison"]
    print("\nSTOCK WALK-FORWARD DIAGNOSTIC")
    print(f"Mod: {args.mode}")
    print(f"Secim politikasi: {config.resolved_selection_policy()}")
    print(f"Sinif: {result['validity']['classification']}")
    print(f"Tamamlanan ay: {strategy['periods']}")
    if strategy["cumulative_return"] is not None:
        print(f"Strateji toplam getiri: %{strategy['cumulative_return'] * 100:.2f}")
        print(f"SPY toplam getiri: %{metrics['spy']['cumulative_return'] * 100:.2f}")
        print(f"Esit agirlik toplam getiri: %{metrics['equal_weight_universe']['cumulative_return'] * 100:.2f}")
        print(f"SPY goreli sonuc: %{comparison['cumulative_excess_vs_spy'] * 100:.2f}")
        print(f"Maksimum dusus: %{strategy['max_drawdown'] * 100:.2f}")
    fundamental_coverage = result["data_quality"]["fundamental_coverage"]
    if fundamental_coverage["periods"]:
        print(
            "Ortalama SEC kapsami: "
            f"{fundamental_coverage['average_ok']:.1f} hisse, "
            f"{fundamental_coverage['average_metric_count']:.1f}/10 metrik"
        )
    ranking = metrics["ranking_diagnostics"]
    if ranking["average_rank_ic"] is not None:
        print(f"Ortalama aylik rank-IC: {ranking['average_rank_ic']:.3f}")
    print(f"Rapor: {output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
