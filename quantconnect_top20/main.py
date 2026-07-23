from AlgorithmImports import *

import math

from factor_core import (
    normalize_factor_weights,
    price_features,
    rank_factor_rows,
    select_top,
    target_weights,
)


class AllInTransactionCostModel(FeeModel):
    """Approximate a 25 bps round trip as 12.5 bps on each traded leg."""

    def __init__(self, one_way_rate):
        self._one_way_rate = one_way_rate

    def get_order_fee(self, parameters):
        notional = abs(float(parameters.order.quantity)) * float(parameters.security.price)
        return OrderFee(CashAmount(notional * self._one_way_rate, "USD"))


class Top20FactorValidationAlgorithm(QCAlgorithm):
    """Independent, survivorship-aware validation of the stock Top20 model."""

    def initialize(self):
        start = self.get_parameter("start_date") or "2021-07-01"
        end = self.get_parameter("end_date") or "2026-06-30"
        start_year, start_month, start_day = [int(value) for value in start.split("-")]
        end_year, end_month, end_day = [int(value) for value in end.split("-")]
        self.set_start_date(start_year, start_month, start_day)
        self.set_end_date(end_year, end_month, end_day)
        self.set_cash(float(self.get_parameter("initial_cash") or 1_000_000))

        self._top_n = int(self.get_parameter("top_n") or 20)
        self._min_positions = int(self.get_parameter("min_positions") or 5)
        self._sector_cap = float(self.get_parameter("sector_cap") or 0.25)
        self._max_position_weight = float(
            self.get_parameter("max_position_weight") or 0.05
        )
        self._min_avg_dollar_volume = float(
            self.get_parameter("min_avg_dollar_volume") or 5_000_000
        )
        self._cash_buffer = float(self.get_parameter("cash_buffer") or 0.005)
        self._factor_weights = normalize_factor_weights({
            "quality": float(self.get_parameter("quality_weight") or 0.35),
            "value": float(self.get_parameter("value_weight") or 0.20),
            "momentum": float(self.get_parameter("momentum_weight") or 0.30),
            "risk": float(self.get_parameter("risk_weight") or 0.15),
        })
        round_trip_cost_bps = float(
            self.get_parameter("round_trip_cost_bps") or 25.0
        )
        self._one_way_cost_rate = round_trip_cost_bps / 2.0 / 10_000.0
        self._fundamental_by_symbol = {}
        self._rebalance_count = 0

        self.settings.minimum_order_margin_portfolio_percentage = 0
        self.settings.seed_initial_prices = True
        self.set_brokerage_model(
            BrokerageName.QUANT_CONNECT_BROKERAGE,
            AccountType.MARGIN,
        )
        self.universe_settings.resolution = Resolution.DAILY
        self.universe_settings.asynchronous = False
        self.universe_settings.data_normalization_mode = DataNormalizationMode.ADJUSTED
        self.universe_settings.schedule.on(self.date_rules.month_start())

        self._spy = self.add_equity(
            "SPY", Resolution.DAILY, data_normalization_mode=DataNormalizationMode.ADJUSTED
        ).symbol
        self.set_benchmark(self._spy)
        self._universe = self.add_universe(
            self.universe.etf(self._spy),
            self._fundamental_selection,
        )
        self.schedule.on(
            self.date_rules.month_start(self._spy),
            self.time_rules.before_market_open(self._spy, 10),
            self._rebalance,
        )
        factor_mix = "/".join(
            f"{factor[:1].upper()}{weight:.3f}"
            for factor, weight in self._factor_weights.items()
        )
        self.set_runtime_statistic("Factor Mix", factor_mix)

    @staticmethod
    def _finite(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None

    def _annual_value(self, field):
        if field is None:
            return None
        for attribute in ("one_year", "value"):
            try:
                value = self._finite(getattr(field, attribute))
            except Exception:
                value = None
            if value is not None:
                return value
        return None

    def _fundamental_row(self, fundamental):
        operation = fundamental.operation_ratios
        valuation = fundamental.valuation_ratios
        return {
            "symbol": fundamental.symbol,
            "sector": str(
                fundamental.asset_classification.morningstar_sector_code
            ),
            "roe": self._annual_value(operation.roe),
            "roa": self._annual_value(operation.roa),
            "profit_margin": self._annual_value(operation.net_margin),
            "gross_margin": self._annual_value(operation.gross_margin),
            "revenue_growth": self._annual_value(operation.revenue_growth),
            "earnings_growth": self._annual_value(operation.net_income_growth),
            "debt_to_equity": self._annual_value(operation.total_debt_equity_ratio),
            "earnings_yield": self._finite(valuation.earning_yield),
            "fcf_yield": self._finite(valuation.fcf_yield),
            "dividend_yield": self._finite(valuation.trailing_dividend_yield),
        }

    def _fundamental_selection(self, fundamentals):
        current = {}
        for fundamental in fundamentals:
            try:
                row = self._fundamental_row(fundamental)
            except Exception:
                continue
            current[fundamental.symbol] = row
        self._fundamental_by_symbol = current
        return list(current)

    @staticmethod
    def _symbol_history(history, symbol):
        try:
            frame = history.loc[symbol]
        except (KeyError, TypeError):
            try:
                frame = history.xs(symbol, level=0)
            except (KeyError, TypeError, ValueError):
                return None
        if frame is None or frame.empty:
            return None
        return frame.sort_index()

    def _rebalance(self):
        symbols = [
            symbol for symbol in self._universe.selected
            if symbol in self._fundamental_by_symbol
        ]
        if not symbols:
            self.debug(f"{self.time.date()} rebalance skipped: empty universe")
            return

        history = self.history(symbols, 253, Resolution.DAILY)
        if history is None or history.empty:
            self.debug(f"{self.time.date()} rebalance skipped: empty history")
            return

        rows = []
        for symbol in symbols:
            frame = self._symbol_history(history, symbol)
            if frame is None or "close" not in frame or "volume" not in frame:
                continue
            features = price_features(
                frame["close"].tolist(),
                frame["volume"].tolist(),
                self._min_avg_dollar_volume,
            )
            if features is None:
                continue
            row = dict(self._fundamental_by_symbol[symbol])
            row.update(features)
            rows.append(row)

        ranked = rank_factor_rows(rows, self._factor_weights)
        selected = select_top(ranked, self._top_n, self._min_positions)
        weights = target_weights(
            selected,
            self._max_position_weight,
            self._sector_cap,
        )
        if not weights:
            self.liquidate(tag="Insufficient eligible factor coverage")
            self.debug(
                f"{self.time.date()} no portfolio: universe={len(symbols)} "
                f"features={len(rows)} eligible={sum(row['eligible'] for row in ranked)}"
            )
            return

        buffered_weights = {
            symbol: weight * (1.0 - self._cash_buffer)
            for symbol, weight in weights.items()
        }
        self._submit_market_on_open_targets(buffered_weights)
        self._rebalance_count += 1
        invested = sum(buffered_weights.values())
        top_symbols = ",".join(str(row["symbol"].value) for row in selected[:5])
        self.set_runtime_statistic("Rebalances", str(self._rebalance_count))
        self.set_runtime_statistic("Eligible", str(sum(row["eligible"] for row in ranked)))
        self.set_runtime_statistic("Invested", f"{invested:.1%}")
        self.plot("Selection", "Feature rows", len(rows))
        self.plot("Selection", "Eligible", sum(row["eligible"] for row in ranked))
        self.debug(
            f"{self.time.date()} universe={len(symbols)} features={len(rows)} "
            f"eligible={sum(row['eligible'] for row in ranked)} selected={len(selected)} "
            f"invested={invested:.1%} top5={top_symbols}"
        )

    def _submit_market_on_open_targets(self, weights):
        """Submit one opening-auction rebalance with sells ordered before buys."""
        current_symbols = {
            holding.symbol
            for holding in self.portfolio.values()
            if holding.invested and holding.symbol != self._spy
        }
        symbols = current_symbols | set(weights)
        orders = []
        for symbol in symbols:
            target = weights.get(symbol, 0.0)
            quantity = self.calculate_order_quantity(symbol, target)
            if quantity:
                orders.append((quantity > 0, symbol, quantity))

        for _, symbol, quantity in sorted(
            orders,
            key=lambda order: (order[0], str(order[1])),
        ):
            self.market_on_open_order(
                symbol,
                quantity,
                tag="Monthly Top20 opening rebalance",
                asynchronous=True,
            )

    def on_securities_changed(self, changes):
        for security in changes.added_securities:
            security.set_fee_model(AllInTransactionCostModel(self._one_way_cost_rate))
