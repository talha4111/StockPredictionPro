"""Platform-independent Top20 factor ranking and portfolio construction.

This module deliberately has no QuantConnect imports. Keeping the factor math
separate lets us test the strategy contract locally before cloud data enters
the picture.
"""

from __future__ import annotations

import math
from statistics import fmean, pstdev
from typing import Hashable, Mapping, Optional, Sequence


FACTOR_DEFINITIONS = {
    "quality": (
        ("roe", True, True),
        ("roa", True, True),
        ("profit_margin", True, True),
        ("gross_margin", True, True),
        ("revenue_growth", True, True),
        ("earnings_growth", True, True),
        ("debt_to_equity", False, True),
    ),
    "value": (
        ("earnings_yield", True, True),
        ("fcf_yield", True, True),
        ("dividend_yield", True, True),
    ),
    "momentum": (
        ("momentum_12_1", True, False),
        ("momentum_6_1", True, False),
        ("distance_52w_high", True, False),
    ),
    "risk": (
        ("realized_vol_63d", False, False),
        ("downside_vol_63d", False, False),
        ("max_drawdown_1y", True, False),
    ),
}

FACTOR_WEIGHTS = {
    "quality": 0.35,
    "value": 0.20,
    "momentum": 0.30,
    "risk": 0.15,
}

FACTOR_MINIMUM_METRICS = {
    "quality": 2,
    "value": 1,
    "momentum": 2,
    "risk": 2,
}

TOTAL_METRICS = sum(len(metrics) for metrics in FACTOR_DEFINITIONS.values())


def finite_float(value: object) -> Optional[float]:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percentile(values: Mapping[int, float], higher_is_better: bool) -> dict[int, float]:
    """Return tie-aware 0-100 percentile scores without external libraries."""
    if not values:
        return {}
    if len(values) == 1:
        return {next(iter(values)): 50.0}

    result = {}
    observations = list(values.values())
    denominator = len(observations) - 1
    for index, value in values.items():
        if higher_is_better:
            better_direction = sum(other < value for other in observations)
        else:
            better_direction = sum(other > value for other in observations)
        ties = sum(other == value for other in observations) - 1
        rank_from_worst = better_direction + ties / 2.0
        result[index] = round(rank_from_worst / denominator * 100.0, 2)
    return result


def metric_percentiles(
    rows: Sequence[Mapping[str, object]],
    metric: str,
    higher_is_better: bool,
    sector_neutral: bool,
) -> dict[int, float]:
    values = {
        index: value
        for index, row in enumerate(rows)
        if (value := finite_float(row.get(metric))) is not None
    }
    global_scores = _percentile(values, higher_is_better)
    if not sector_neutral:
        return global_scores

    scores = dict(global_scores)
    by_sector: dict[str, dict[int, float]] = {}
    for index, value in values.items():
        sector = str(rows[index].get("sector", "Unknown"))
        by_sector.setdefault(sector, {})[index] = value
    for sector_values in by_sector.values():
        if len(sector_values) >= 4:
            scores.update(_percentile(sector_values, higher_is_better))
    return scores


def normalize_factor_weights(
    factor_weights: Optional[Mapping[str, object]] = None,
) -> dict[str, float]:
    """Validate and normalize a research factor mix to a unit sum."""
    source = FACTOR_WEIGHTS if factor_weights is None else factor_weights
    unknown = set(source) - set(FACTOR_DEFINITIONS)
    if unknown:
        raise ValueError(f"Unknown factors: {sorted(unknown)}")

    result = {}
    for factor in FACTOR_DEFINITIONS:
        raw_value = source.get(factor, 0.0)
        value = finite_float(raw_value)
        if value is None or value < 0:
            raise ValueError(f"Invalid weight for {factor}: {raw_value!r}")
        result[factor] = value

    total = sum(result.values())
    if total <= 0:
        raise ValueError("At least one factor weight must be positive")
    return {factor: value / total for factor, value in result.items()}


def rank_factor_rows(
    rows: Sequence[Mapping[str, object]],
    factor_weights: Optional[Mapping[str, object]] = None,
) -> list[dict]:
    """Apply the production Factor v3.1 ranking contract to raw observations."""
    if not rows:
        return []

    weights = normalize_factor_weights(factor_weights)

    score_maps = {}
    for metrics in FACTOR_DEFINITIONS.values():
        for metric, higher_is_better, sector_neutral in metrics:
            score_maps[metric] = metric_percentiles(
                rows,
                metric,
                higher_is_better,
                sector_neutral,
            )

    ranked = []
    for index, source in enumerate(rows):
        row = dict(source)
        available_metrics = 0
        for factor, metrics in FACTOR_DEFINITIONS.items():
            scores = []
            for metric, _, _ in metrics:
                score = score_maps[metric].get(index)
                if score is not None:
                    scores.append(score)
                    available_metrics += 1
            row[f"{factor}_score"] = (
                round(fmean(scores), 2)
                if len(scores) >= FACTOR_MINIMUM_METRICS[factor]
                else None
            )

        weighted_total = 0.0
        used_weight = 0.0
        for factor, weight in weights.items():
            factor_score = row.get(f"{factor}_score")
            if factor_score is not None:
                weighted_total += float(factor_score) * weight
                used_weight += weight

        row["factor_coverage"] = round(available_metrics / TOTAL_METRICS, 3)
        row["factor_score"] = (
            round(weighted_total / used_weight, 1) if used_weight else None
        )
        row["eligible"] = bool(
            row["factor_score"] is not None and row["factor_coverage"] >= 0.75
        )
        ranked.append(row)

    return sorted(
        ranked,
        key=lambda row: (
            not row["eligible"],
            -(row["factor_score"] if row["factor_score"] is not None else -1.0),
            str(row.get("symbol", "")),
        ),
    )


def price_features(
    closes: Sequence[object],
    volumes: Sequence[object],
    min_avg_dollar_volume: float = 5_000_000.0,
) -> Optional[dict[str, float]]:
    """Calculate the six momentum/risk metrics from completed daily bars."""
    if len(closes) < 252 or len(volumes) < 252 or len(closes) != len(volumes):
        return None

    clean_closes = [finite_float(value) for value in closes]
    clean_volumes = [finite_float(value) for value in volumes]
    if any(value is None or value <= 0 for value in clean_closes[-252:]):
        return None
    if any(value is None or value < 0 for value in clean_volumes[-20:]):
        return None

    prices = [float(value) for value in clean_closes]
    volume_values = [float(value) for value in clean_volumes]
    avg_dollar_volume = fmean(
        price * volume for price, volume in zip(prices[-20:], volume_values[-20:])
    )
    if avg_dollar_volume < min_avg_dollar_volume:
        return None

    returns = [
        prices[index] / prices[index - 1] - 1.0
        for index in range(len(prices) - 63, len(prices))
    ]
    downside = [value for value in returns if value < 0]
    annualizer = math.sqrt(252.0)
    realized_vol = pstdev(returns) * annualizer
    downside_vol = pstdev(downside) * annualizer if len(downside) >= 2 else 0.0

    trailing = prices[-252:]
    peak = trailing[0]
    max_drawdown = 0.0
    for price in trailing:
        peak = max(peak, price)
        max_drawdown = min(max_drawdown, price / peak - 1.0)

    return {
        "momentum_12_1": prices[-22] / prices[-252] - 1.0,
        "momentum_6_1": prices[-22] / prices[-126] - 1.0,
        "distance_52w_high": prices[-1] / max(trailing) - 1.0,
        "realized_vol_63d": realized_vol,
        "downside_vol_63d": downside_vol,
        "max_drawdown_1y": max_drawdown,
        "avg_dollar_volume": avg_dollar_volume,
    }


def select_top(
    ranked: Sequence[Mapping[str, object]],
    top_n: int = 20,
    min_positions: int = 5,
) -> list[dict]:
    selected = [dict(row) for row in ranked if row.get("eligible")][:top_n]
    return selected if len(selected) >= min_positions else []


def target_weights(
    selected: Sequence[Mapping[str, object]],
    max_position_weight: float = 0.05,
    sector_cap: float = 0.25,
) -> dict[Hashable, float]:
    """Equal weight selected names, leaving cap excess in cash."""
    if not selected:
        return {}
    base_weight = min(1.0 / len(selected), max_position_weight)
    by_sector: dict[str, list[Hashable]] = {}
    for row in selected:
        symbol = row.get("symbol")
        if symbol is None:
            continue
        sector = str(row.get("sector", "Unknown"))
        by_sector.setdefault(sector, []).append(symbol)

    weights = {}
    for symbols in by_sector.values():
        per_symbol = min(base_weight, sector_cap / len(symbols))
        for symbol in symbols:
            weights[symbol] = per_symbol
    return weights
