"""Live, order-free A/B scoring for active and shadow prediction models."""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from model_contract import OutcomeSpec, timeframe_delta


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_STATE_PATH = BASE_DIR / "live_model_compare_state.json"
DEFAULT_V6_STATE_PATH = BASE_DIR / "live_model_compare_v6_state.json"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").upper().replace(":USDT", "").strip()
    base = text.replace("/USDT", "").replace("USDT", "")
    return f"{base}/USDT" if base else text


def _bar_open_timestamp(value: Any, *, name: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} geçerli timestamp olmalıdır.") from exc
    if pd.isna(result):
        raise ValueError(f"{name} NaT olamaz.")
    if result.tzinfo is not None:
        result = result.tz_convert("UTC").tz_localize(None)
    return result


def _utc_timestamp(epoch_seconds: float) -> pd.Timestamp:
    return pd.Timestamp(float(epoch_seconds), unit="s", tz="UTC").tz_localize(None)


def _empty_metrics() -> dict[str, Any]:
    return {
        "evaluated": 0,
        "correct": 0,
        "brier_sum": 0.0,
        "actual_positives": 0,
        "signals": 0,
        "wins": 0,
        "gross_pnl": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "cost": 0.0,
        "net_pnl": 0.0,
    }


def _score_metrics(
    metrics: dict[str, Any],
    probability: float,
    actual: float,
    market_return: float,
    *,
    threshold: float,
    notional_usdt: float,
    round_trip_cost_rate: float,
) -> tuple[bool, bool, float]:
    correct = (probability >= 0.5) == bool(actual)
    metrics["evaluated"] += 1
    metrics["correct"] += int(correct)
    metrics["brier_sum"] += (probability - actual) ** 2
    metrics["actual_positives"] += int(actual)

    signal = probability >= threshold
    gross_pnl = notional_usdt * market_return if signal else 0.0
    cost = notional_usdt * round_trip_cost_rate if signal else 0.0
    net_pnl = gross_pnl - cost
    if signal:
        metrics["signals"] += 1
        metrics["wins"] += int(net_pnl > 0)
        metrics["gross_pnl"] += gross_pnl
        metrics["gross_profit"] += max(0.0, net_pnl)
        metrics["gross_loss"] += min(0.0, net_pnl)
        metrics["cost"] += cost
        metrics["net_pnl"] += net_pnl
    return bool(correct), bool(signal), net_pnl


class LiveModelComparator:
    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        label_schema_version: int = 5,
        horizon_minutes: int = 60,
        base_timeframe: str = "15m",
        horizon_bars: int = 4,
        threshold: float = 0.60,
        target_min_return: float = 0.0015,
        notional_usdt: float = 100.0,
        round_trip_cost_rate: float = 0.001,
        min_evaluated: int = 500,
        min_signals: int = 50,
        min_profit_factor: float = 1.20,
        min_brier_skill: float = 0.0,
        min_positive_regimes: int = 2,
        min_regime_signals: int = 10,
    ):
        try:
            self.label_schema_version = int(label_schema_version)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Geçersiz label schema version: {label_schema_version!r}"
            ) from exc
        if self.label_schema_version not in (5, 6):
            raise ValueError(
                f"Desteklenmeyen label schema version: "
                f"{self.label_schema_version}"
            )
        if state_path is None:
            state_path = (
                DEFAULT_V6_STATE_PATH
                if self.label_schema_version == 6
                else DEFAULT_STATE_PATH
            )
        self.state_path = Path(state_path)
        self.horizon_seconds = max(60, int(horizon_minutes) * 60)
        self.base_timeframe = str(base_timeframe)
        self.horizon_bars = int(horizon_bars)
        self.threshold = min(0.95, max(0.51, float(threshold)))
        self.target_min_return = max(0.0, float(target_min_return))
        self.notional_usdt = max(1.0, float(notional_usdt))
        self.round_trip_cost_rate = max(0.0, float(round_trip_cost_rate))
        self.min_evaluated = max(100, int(min_evaluated))
        self.min_signals = max(10, int(min_signals))
        self.min_profit_factor = max(1.0, float(min_profit_factor))
        self.min_brier_skill = max(0.0, float(min_brier_skill))
        self.min_positive_regimes = max(1, int(min_positive_regimes))
        self.min_regime_signals = max(1, int(min_regime_signals))
        self.outcome_spec = None
        if self.label_schema_version == 6:
            base_delta = timeframe_delta(self.base_timeframe)
            expected_horizon_seconds = int(
                base_delta.total_seconds() * self.horizon_bars
            )
            if self.horizon_seconds != expected_horizon_seconds:
                raise ValueError(
                    "V6 horizon_minutes, base_timeframe * horizon_bars ile "
                    "eşleşmelidir."
                )
            minimum_edge_rate = (
                self.target_min_return - self.round_trip_cost_rate
            )
            if minimum_edge_rate < 0:
                raise ValueError(
                    "V6 target_min_return işlem maliyetinden küçük olamaz."
                )
            self.outcome_spec = OutcomeSpec(
                schema_version=6,
                horizon_bars=self.horizon_bars,
                round_trip_cost_rate=self.round_trip_cost_rate,
                minimum_edge_rate=minimum_edge_rate,
            )
        self.state = self._load()
        self.state.setdefault("config", {})["acceptance"] = self._acceptance_config()

    def _acceptance_config(self) -> dict[str, Any]:
        return {
            "min_common_observations": self.min_evaluated,
            "min_signals": self.min_signals,
            "min_profit_factor": self.min_profit_factor,
            "min_brier_skill": self.min_brier_skill,
            "min_positive_regimes": self.min_positive_regimes,
            "min_regime_signals": self.min_regime_signals,
            "requires_positive_net_pnl": True,
        }

    def _new_state(self) -> dict[str, Any]:
        now = time.time()
        config = {
            "label_schema_version": self.label_schema_version,
            "horizon_minutes": int(self.horizon_seconds / 60),
            "threshold": self.threshold,
            "target_min_return": self.target_min_return,
            "notional_usdt": self.notional_usdt,
            "round_trip_cost_rate": self.round_trip_cost_rate,
            "trade_mode": "LONG_ONLY",
            "acceptance": self._acceptance_config(),
        }
        if self.label_schema_version == 6:
            config.update(
                {
                    "base_timeframe": self.base_timeframe,
                    "horizon_bars": self.horizon_bars,
                    "entry_policy": self.outcome_spec.entry_policy,
                    "exit_policy": self.outcome_spec.exit_policy,
                    "outcome_contract_id": self.outcome_spec.contract_id,
                    "outcome_spec": self.outcome_spec.to_dict(),
                }
            )
        return {
            "schema": 3 if self.label_schema_version == 6 else 2,
            "started_at": now,
            "updated_at": now,
            "config": config,
            "pending": {},
            "models": {
                "450_8": _empty_metrics(),
                "400_5": _empty_metrics(),
                "200_3": _empty_metrics(),
            },
            "regimes": {},
            "recent": [],
        }

    def _load(self) -> dict[str, Any]:
        expected_schema = 3 if self.label_schema_version == 6 else 2
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema") == expected_schema:
                config = data.setdefault("config", {})
                if self.label_schema_version == 6:
                    if (
                        int(config.get("label_schema_version") or 0) != 6
                        or str(config.get("outcome_contract_id") or "")
                        != self.outcome_spec.contract_id
                    ):
                        raise ValueError(
                            "V6 comparator state outcome sözleşmesi uyumsuz."
                        )
                data.setdefault("pending", {})
                data.setdefault("recent", [])
                data.setdefault("regimes", {})
                models = data.setdefault("models", {})
                for key in ("450_8", "400_5", "200_3"):
                    metric = models.setdefault(key, _empty_metrics())
                    for metric_key, default_value in _empty_metrics().items():
                        metric.setdefault(metric_key, default_value)
                return data
            if isinstance(data, dict):
                raise ValueError(
                    f"Comparator state schema uyumsuz: "
                    f"{data.get('schema')!r} != {expected_schema}"
                )
        except FileNotFoundError:
            return self._new_state()
        except json.JSONDecodeError:
            return self._new_state()
        except ValueError:
            raise
        except Exception:
            if self.label_schema_version == 6:
                raise
            return self._new_state()
        return self._new_state()

    def _save(self) -> None:
        self.state["updated_at"] = time.time()
        temp_path = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with temp_path.open("x", encoding="utf-8") as handle:
                json.dump(
                    self.state,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            for attempt in range(4):
                try:
                    os.replace(temp_path, self.state_path)
                    break
                except PermissionError:
                    if attempt == 3:
                        raise
                    time.sleep(0.025 * (attempt + 1))
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def record_prediction(
        self,
        symbol: str,
        entry_price: float | None,
        active_probability: float,
        shadow_probability: float,
        *,
        v6_1h_probability: float | None = None,
        regime: str = "UNKNOWN",
        now: float | None = None,
        decision_bar_open: Any = None,
        feature_schema_version: int | None = None,
        outcome_contract_id: str | None = None,
        shadow_outcome_contract_id: str | None = None,
        v6_1h_outcome_contract_id: str | None = None,
    ) -> bool:
        now = float(now or time.time())
        symbol = normalize_symbol(symbol)
        entry_price = _float(entry_price)
        active_probability = _float(active_probability, -1.0)
        shadow_probability = _float(shadow_probability, -1.0)
        if not 0.0 <= active_probability <= 1.0 or not 0.0 <= shadow_probability <= 1.0:
            return False
        if symbol in self.state["pending"]:
            return False

        v6_prob = _float(v6_1h_probability, -1.0) if v6_1h_probability is not None else -1.0
        probs = {
            "450_8": active_probability,
            "400_5": shadow_probability,
        }
        if 0.0 <= v6_prob <= 1.0:
            probs["200_3"] = v6_prob
        item = {
            "created_at": now,
            "probabilities": probs,
            "regime": str(regime or "UNKNOWN").upper(),
        }
        if self.label_schema_version == 6:
            try:
                decision_at = _bar_open_timestamp(
                    decision_bar_open,
                    name="decision_bar_open",
                )
                feature_schema_version = int(feature_schema_version)
            except (TypeError, ValueError):
                return False
            if feature_schema_version != 6:
                return False
            if str(outcome_contract_id or "") != self.outcome_spec.contract_id:
                return False
            if (
                str(shadow_outcome_contract_id or "")
                != self.outcome_spec.contract_id
            ):
                return False
            model_contracts = {
                "450_8": self.outcome_spec.contract_id,
                "400_5": self.outcome_spec.contract_id,
            }
            if 0.0 <= v6_prob <= 1.0:
                v6_contract = str(v6_1h_outcome_contract_id or "")
                if v6_contract == self.outcome_spec.contract_id:
                    model_contracts["200_3"] = self.outcome_spec.contract_id
            item.update(
                {
                    "label_schema_version": 6,
                    "feature_schema_version": feature_schema_version,
                    "outcome_contract_id": self.outcome_spec.contract_id,
                    "model_outcome_contracts": model_contracts,
                    "decision_bar_open": decision_at.isoformat(),
                }
            )
        else:
            if entry_price <= 0:
                return False
            item["entry_price"] = entry_price

        self.state["pending"][symbol] = item
        self._save()
        return True

    def _settle_one(self, symbol: str, item: dict[str, Any], exit_price: float, now: float) -> None:
        entry_price = _float(item.get("entry_price"))
        if entry_price <= 0 or exit_price <= 0:
            return
        market_return = (exit_price - entry_price) / entry_price
        actual = 1.0 if market_return >= self.target_min_return else 0.0
        result = {
            "symbol": symbol,
            "created_at": item.get("created_at"),
            "settled_at": now,
            "hold_minutes": round((now - _float(item.get("created_at"), now)) / 60.0, 2),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "market_return_pct": round(market_return * 100.0, 4),
            "regime": str(item.get("regime") or "UNKNOWN").upper(),
            "models": {},
        }
        self._append_scored_result(
            item,
            result,
            actual=actual,
            market_return=market_return,
        )

    def _append_scored_result(
        self,
        item: dict[str, Any],
        result: dict[str, Any],
        *,
        actual: float,
        market_return: float,
    ) -> None:
        regime = result["regime"]

        for model_key in ("450_8", "400_5", "200_3"):
            probability = _float((item.get("probabilities") or {}).get(model_key), -1.0)
            if not 0.0 <= probability <= 1.0:
                continue
            metrics = self.state["models"].setdefault(model_key, _empty_metrics())
            correct, signal, net_pnl = _score_metrics(
                metrics,
                probability,
                actual,
                market_return,
                threshold=self.threshold,
                notional_usdt=self.notional_usdt,
                round_trip_cost_rate=self.round_trip_cost_rate,
            )
            regime_metrics = (
                self.state.setdefault("regimes", {})
                .setdefault(regime, {})
                .setdefault(model_key, _empty_metrics())
            )
            _score_metrics(
                regime_metrics,
                probability,
                actual,
                market_return,
                threshold=self.threshold,
                notional_usdt=self.notional_usdt,
                round_trip_cost_rate=self.round_trip_cost_rate,
            )

            result["models"][model_key] = {
                "probability": round(probability, 6),
                "direction_correct": bool(correct),
                "signal": bool(signal),
                "net_pnl": round(net_pnl, 6),
            }

        self.state["recent"].append(result)
        self.state["recent"] = self.state["recent"][-200:]

    def _v6_frame_hazirla(
        self,
        frame: pd.DataFrame,
        *,
        decision_bar_open: pd.Timestamp,
    ) -> pd.DataFrame | None:
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            return None
        try:
            index = pd.DatetimeIndex(frame.index)
        except (TypeError, ValueError):
            return None
        if index.hasnans or index.has_duplicates or not index.is_monotonic_increasing:
            return None
        if index.tz is not None:
            index = index.tz_convert("UTC").tz_localize(None)

        close_column = (
            "Hedef_Close"
            if "Hedef_Close" in frame.columns
            else ("close" if "close" in frame.columns else None)
        )
        if "open" not in frame.columns or close_column is None:
            return None

        expected_index = pd.date_range(
            decision_bar_open,
            periods=self.horizon_bars + 1,
            freq=timeframe_delta(self.base_timeframe),
        )
        if not expected_index.isin(index).all():
            return None

        normalized = frame.copy()
        normalized.index = index
        selected = normalized.reindex(expected_index)[["open", close_column]].copy()
        selected.rename(columns={close_column: "Hedef_Close"}, inplace=True)
        return selected

    def settle_due_bars(
        self,
        frames: dict[str, pd.DataFrame],
        *,
        now: float | None = None,
    ) -> int:
        if self.label_schema_version != 6:
            raise RuntimeError("Bar settlement yalnızca label schema 6 içindir.")
        now = float(now or time.time())
        now_timestamp = _utc_timestamp(now)
        normalized_frames = {
            normalize_symbol(symbol): frame
            for symbol, frame in frames.items()
        }
        settled = 0
        base_delta = timeframe_delta(self.base_timeframe)

        for symbol, item in list(self.state["pending"].items()):
            if (
                int(item.get("label_schema_version") or 0) != 6
                or str(item.get("outcome_contract_id") or "")
                != self.outcome_spec.contract_id
            ):
                continue
            try:
                decision_bar_open = _bar_open_timestamp(
                    item.get("decision_bar_open"),
                    name="decision_bar_open",
                )
            except ValueError:
                continue

            exit_bar_open = decision_bar_open + (
                self.horizon_bars * base_delta
            )
            outcome_available_at = exit_bar_open + base_delta
            if now_timestamp < outcome_available_at:
                continue

            frame = normalized_frames.get(normalize_symbol(symbol))
            selected = self._v6_frame_hazirla(
                frame,
                decision_bar_open=decision_bar_open,
            )
            if selected is None:
                continue
            outcomes = self.outcome_spec.build_long_outcomes(selected)
            outcome = outcomes.iloc[0]
            if pd.isna(outcome["y_long"]):
                continue

            entry_price = float(outcome["entry_price"])
            exit_price = float(outcome["exit_price"])
            gross_return = float(outcome["gross_return"])
            net_return = float(outcome["net_return"])
            actual = float(outcome["y_long"])
            entry_bar_open = decision_bar_open + base_delta
            result = {
                "schema": 6,
                "outcome_contract_id": self.outcome_spec.contract_id,
                "symbol": symbol,
                "created_at": item.get("created_at"),
                "settled_at": now,
                "decision_bar_open": decision_bar_open.isoformat(),
                "entry_bar_open": entry_bar_open.isoformat(),
                "exit_bar_open": exit_bar_open.isoformat(),
                "outcome_available_at": outcome_available_at.isoformat(),
                "hold_minutes": round(
                    (outcome_available_at - entry_bar_open).total_seconds()
                    / 60.0,
                    2,
                ),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "market_return_pct": round(gross_return * 100.0, 4),
                "net_return_pct": round(net_return * 100.0, 4),
                "actual": int(actual),
                "regime": str(item.get("regime") or "UNKNOWN").upper(),
                "models": {},
            }
            self._append_scored_result(
                item,
                result,
                actual=actual,
                market_return=gross_return,
            )
            del self.state["pending"][symbol]
            settled += 1

        if settled:
            self._save()
        return settled

    def due_bar_requests(
        self,
        *,
        now: float | None = None,
    ) -> dict[str, dict[str, int]]:
        if self.label_schema_version != 6:
            return {}
        now_timestamp = _utc_timestamp(float(now or time.time()))
        base_delta = timeframe_delta(self.base_timeframe)
        due = {}
        for symbol, item in self.state.get("pending", {}).items():
            try:
                decision_bar_open = _bar_open_timestamp(
                    item.get("decision_bar_open"),
                    name="decision_bar_open",
                )
            except ValueError:
                continue
            outcome_available_at = decision_bar_open + (
                (self.horizon_bars + 1) * base_delta
            )
            if now_timestamp >= outcome_available_at:
                decision_utc = decision_bar_open.tz_localize("UTC")
                due[normalize_symbol(symbol)] = {
                    "since_ms": int(decision_utc.timestamp() * 1000),
                    "limit": int(self.horizon_bars + 2),
                }
        return dict(sorted(due.items()))

    def due_symbols(self, *, now: float | None = None) -> list[str]:
        return list(self.due_bar_requests(now=now))

    def settle_due(self, prices: dict[str, float], *, now: float | None = None) -> int:
        if self.label_schema_version == 6:
            raise RuntimeError(
                "V6 ticker fiyatıyla settle edilemez; settle_due_bars kullanılmalı."
            )
        now = float(now or time.time())
        normalized_prices = {
            normalize_symbol(symbol): _float(price)
            for symbol, price in prices.items()
            if _float(price) > 0
        }
        settled = 0
        for symbol, item in list(self.state["pending"].items()):
            created_at = _float(item.get("created_at"))
            if now - created_at < self.horizon_seconds:
                continue
            exit_price = normalized_prices.get(normalize_symbol(symbol), 0.0)
            if exit_price <= 0:
                continue
            self._settle_one(symbol, item, exit_price, now)
            del self.state["pending"][symbol]
            settled += 1
        if settled:
            self._save()
        return settled

    def summary(self) -> dict[str, Any]:
        now = time.time()
        models = {}
        for model_key in ("450_8", "400_5", "200_3"):
            raw = self.state["models"].get(model_key, _empty_metrics())
            evaluated = int(raw.get("evaluated", 0) or 0)
            signals = int(raw.get("signals", 0) or 0)
            brier_score = round(_float(raw.get("brier_sum")) / evaluated, 6) if evaluated else None
            actual_positives = int(raw.get("actual_positives", 0) or 0)
            prevalence = actual_positives / evaluated if evaluated else 0.0
            brier_baseline = prevalence * (1.0 - prevalence) if 0.0 < prevalence < 1.0 else 0.0
            brier_skill = (
                1.0 - (float(brier_score) / brier_baseline)
                if brier_score is not None and brier_baseline > 0 else None
            )
            models[model_key] = {
                "evaluated": evaluated,
                "direction_accuracy": round(100.0 * int(raw.get("correct", 0) or 0) / evaluated, 2) if evaluated else 0.0,
                "brier_score": brier_score,
                "brier_baseline": round(brier_baseline, 6) if evaluated else None,
                "brier_skill_score": round(brier_skill, 6) if brier_skill is not None else None,
                "signals": signals,
                "wins": int(raw.get("wins", 0) or 0),
                "win_rate": round(100.0 * int(raw.get("wins", 0) or 0) / signals, 2) if signals else 0.0,
                "gross_pnl": round(_float(raw.get("gross_pnl")), 4),
                "profit_factor": round(
                    _float(raw.get("gross_profit")) / abs(_float(raw.get("gross_loss"))), 4
                ) if _float(raw.get("gross_loss")) < 0 else (999.0 if _float(raw.get("gross_profit")) > 0 else 0.0),
                "cost": round(_float(raw.get("cost")), 4),
                "net_pnl": round(_float(raw.get("net_pnl")), 4),
            }

        active_evals = [models[key]["evaluated"] for key in models if models[key]["evaluated"] > 0]
        min_samples = min(active_evals) if active_evals else 0
        regime_summary = {}
        positive_regime_counts = {key: 0 for key in models}
        for regime, regime_models in self.state.get("regimes", {}).items():
            regime_summary[regime] = {}
            for model_key in models:
                raw = regime_models.get(model_key, _empty_metrics())
                signals = int(raw.get("signals", 0) or 0)
                gross_loss = _float(raw.get("gross_loss"))
                gross_profit = _float(raw.get("gross_profit"))
                profit_factor = (
                    gross_profit / abs(gross_loss)
                    if gross_loss < 0
                    else (999.0 if gross_profit > 0 else 0.0)
                )
                net_pnl = _float(raw.get("net_pnl"))
                regime_summary[regime][model_key] = {
                    "evaluated": int(raw.get("evaluated", 0) or 0),
                    "signals": signals,
                    "net_pnl": round(net_pnl, 4),
                    "profit_factor": round(profit_factor, 4),
                }
                if (
                    signals >= self.min_regime_signals
                    and net_pnl > 0
                    and profit_factor >= 1.0
                ):
                    positive_regime_counts[model_key] += 1
        leader = "VERI_BIRIKIYOR"
        accepted = []
        if min_samples >= self.min_evaluated:
            for key, metric in models.items():
                if (
                    metric["signals"] >= self.min_signals
                    and metric["net_pnl"] > 0
                    and metric["profit_factor"] >= self.min_profit_factor
                    and float(metric["brier_score"] or 1.0) <= 0.26
                    and metric["brier_skill_score"] is not None
                    and float(metric["brier_skill_score"]) > self.min_brier_skill
                    and positive_regime_counts[key] >= self.min_positive_regimes
                ):
                    accepted.append(key)
            leader = (
                max(accepted, key=lambda key: (models[key]["net_pnl"], -float(models[key]["brier_score"] or 1.0)))
                if accepted else "BASARISIZ"
            )
        return {
            "started_at": self.state.get("started_at"),
            "elapsed_hours": round((now - _float(self.state.get("started_at"), now)) / 3600.0, 2),
            "pending": len(self.state.get("pending", {})),
            "settled": min_samples,
            "leader": leader,
            "accepted_models": accepted,
            "config": self.state.get("config", {}),
            "models": models,
            "regimes": regime_summary,
            "positive_regime_counts": positive_regime_counts,
        }
