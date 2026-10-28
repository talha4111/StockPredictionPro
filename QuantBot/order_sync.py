"""Binance Futures position/protective-order reconciliation.

Binance stores conditional futures orders in the Algo Order API. CCXT's
``fetch_open_orders`` and ``cancel_all_orders`` do not include that channel,
so conditional orders must be reconciled explicitly.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import time
from typing import Any


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def normalize_symbol(symbol: Any) -> str:
    text = str(symbol or "").upper().replace(":USDT", "")
    if "/" not in text and text.endswith("USDT"):
        text = f"{text[:-4]}/USDT"
    return text


def market_id(exchange, symbol: Any) -> str:
    normalized = normalize_symbol(symbol)
    try:
        return str(exchange.market_id(normalized))
    except Exception:
        return normalized.replace("/", "")


def fetch_open_algo_orders(exchange) -> list[dict[str, Any]]:
    method = getattr(exchange, "fapiPrivateGetOpenAlgoOrders", None)
    if not callable(method):
        raise RuntimeError("Binance Algo Order API is not available")
    response = method({}) or []
    if isinstance(response, dict):
        response = response.get("orders") or response.get("data") or []
    if not isinstance(response, list):
        raise RuntimeError("Binance Algo Order API returned an invalid response")
    return [item for item in response if isinstance(item, dict)]


def cancel_all_algo_orders(exchange, symbol: Any) -> int:
    symbol_id = market_id(exchange, symbol)
    method = getattr(exchange, "fapiPrivateDeleteAlgoOpenOrders", None)
    if not callable(method):
        raise RuntimeError("Binance Algo Order cancel API is not available")
    method({"symbol": symbol_id})
    return 1


def cancel_symbol_orders(exchange, symbol: Any) -> dict[str, Any]:
    """Cancel both classic and conditional/algo orders for one symbol."""
    result = {"classic": False, "algo": False, "errors": []}
    try:
        exchange.cancel_all_orders(normalize_symbol(symbol))
        result["classic"] = True
    except Exception as exc:
        result["errors"].append(f"classic: {exc}")

    try:
        cancel_all_algo_orders(exchange, symbol)
        result["algo"] = True
    except Exception as exc:
        result["errors"].append(f"algo: {exc}")
    return result


def _position_snapshot(exchange, position: dict[str, Any]) -> dict[str, Any] | None:
    info = position.get("info") or {}
    raw_amount = info.get("positionAmt")
    if raw_amount in (None, ""):
        contracts = _float(position.get("contracts"))
        side = str(position.get("side") or "").lower()
        raw_amount = -contracts if side == "short" else contracts
    amount = _float(raw_amount)
    if amount == 0:
        return None

    symbol = normalize_symbol(position.get("symbol") or info.get("symbol"))
    return {
        "symbol": symbol,
        "market_id": market_id(exchange, symbol),
        "amount": abs(amount),
        "side": "LONG" if amount > 0 else "SHORT",
        "entry": _float(position.get("entryPrice") or info.get("entryPrice")),
        "mark": _float(position.get("markPrice") or info.get("markPrice")),
    }


def _detail_for(details: dict[str, Any], symbol: str) -> dict[str, Any]:
    for suffix in ("TESTNET", "DEMO", "LIVE"):
        detail = details.get(f"{symbol}_{suffix}")
        if isinstance(detail, dict):
            return detail
    return {}


def _order_matches_stop(order: dict[str, Any], position: dict[str, Any], expected_sl: float) -> bool:
    if str(order.get("orderType") or order.get("type") or "").upper() != "STOP_MARKET":
        return False
    expected_side = "SELL" if position["side"] == "LONG" else "BUY"
    if str(order.get("side") or "").upper() != expected_side:
        return False
    if not _bool(order.get("reduceOnly")):
        return False

    quantity = _float(order.get("quantity") or order.get("origQty"))
    tolerance = max(position["amount"] * 0.001, 1e-10)
    if abs(quantity - position["amount"]) > tolerance:
        return False

    trigger = _float(order.get("triggerPrice") or order.get("stopPrice"))
    reference = position["mark"] or position["entry"]
    if trigger <= 0 or reference <= 0:
        return False
    if position["side"] == "LONG" and trigger >= reference:
        return False
    if position["side"] == "SHORT" and trigger <= reference:
        return False
    if expected_sl > 0 and abs(trigger - expected_sl) > max(abs(expected_sl) * 0.002, 1e-10):
        return False
    return True


def create_hard_stop(exchange, symbol: str, side: str, amount: float, stop_price: float) -> dict[str, Any]:
    order_side = "sell" if side == "LONG" else "buy"
    precise_amount = float(exchange.amount_to_precision(symbol, amount))
    precise_price = float(exchange.price_to_precision(symbol, stop_price))
    return exchange.create_order(
        symbol=symbol,
        type="STOP_MARKET",
        side=order_side,
        amount=precise_amount,
        params={"stopPrice": precise_price, "reduceOnly": True},
    )


def ensure_single_hard_stop(
    exchange,
    symbol: str,
    side: str,
    amount: float,
    stop_price: float,
) -> tuple[bool, dict[str, Any]]:
    """Replace every classic/algo order with one full-size emergency stop."""
    cancel_result = cancel_symbol_orders(exchange, symbol)
    try:
        created = create_hard_stop(exchange, symbol, side, amount, stop_price)
    except Exception as exc:
        return False, {"cancel": cancel_result, "error": str(exc)}

    symbol_id = market_id(exchange, symbol)
    last_error = "created stop was not visible"
    matching = []
    for attempt in range(3):
        try:
            orders = fetch_open_algo_orders(exchange)
            matching = [
                order for order in orders
                if str(order.get("symbol") or "").upper() == symbol_id.upper()
            ]
            verified = (
                len(matching) == 1
                and str(matching[0].get("orderType") or "").upper() == "STOP_MARKET"
            )
            if verified:
                return True, {"cancel": cancel_result, "created": created, "orders": matching}
            last_error = f"expected one STOP_MARKET, found {len(matching)} orders"
        except Exception as exc:
            last_error = f"verify: {exc}"
        if attempt < 2:
            time.sleep(0.4)
    return False, {"cancel": cancel_result, "created": created, "orders": matching, "error": last_error}


def reconcile_protective_orders(
    exchange,
    positions: list[dict[str, Any]],
    details: dict[str, Any],
) -> dict[str, Any]:
    """Remove orphan/duplicate algo orders and leave one stop per position."""
    result = {
        "ready": False,
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "active_positions": 0,
        "algo_before": 0,
        "algo_after": 0,
        "cleaned_symbols": [],
        "rebuilt_symbols": [],
        "protected_symbols": [],
        "errors": [],
    }

    active: dict[str, dict[str, Any]] = {}
    for raw_position in positions:
        snapshot = _position_snapshot(exchange, raw_position)
        if snapshot:
            active[snapshot["market_id"].upper()] = snapshot
    result["active_positions"] = len(active)

    try:
        before = fetch_open_algo_orders(exchange)
    except Exception as exc:
        result["errors"].append(f"algo list: {exc}")
        return result
    result["algo_before"] = len(before)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in before:
        grouped[str(order.get("symbol") or "").upper()].append(order)

    for symbol_id, orders in grouped.items():
        if symbol_id in active:
            continue
        try:
            cancel_all_algo_orders(exchange, symbol_id)
            result["cleaned_symbols"].append(symbol_id)
        except Exception as exc:
            result["errors"].append(f"orphan {symbol_id}: {exc}")

    for symbol_id, position in active.items():
        detail = _detail_for(details, position["symbol"])
        expected_sl = _float(detail.get("SL_Fiyat"))
        current_orders = grouped.get(symbol_id, [])
        valid = [
            order for order in current_orders
            if _order_matches_stop(order, position, expected_sl)
        ]
        if len(current_orders) == 1 and len(valid) == 1:
            result["protected_symbols"].append(position["symbol"])
            continue
        if expected_sl <= 0:
            result["errors"].append(f"{position['symbol']}: missing SL detail")
            continue

        reference = position["mark"] or position["entry"]
        if reference <= 0:
            result["errors"].append(f"{position['symbol']}: missing market reference")
            continue
        if position["side"] == "LONG" and expected_sl >= reference:
            result["errors"].append(f"{position['symbol']}: LONG stop is not below market")
            continue
        if position["side"] == "SHORT" and expected_sl <= reference:
            result["errors"].append(f"{position['symbol']}: SHORT stop is not above market")
            continue

        ok, detail_result = ensure_single_hard_stop(
            exchange,
            position["symbol"],
            position["side"],
            position["amount"],
            expected_sl,
        )
        if ok:
            result["rebuilt_symbols"].append(position["symbol"])
        else:
            result["errors"].append(f"{position['symbol']}: {detail_result.get('error', 'stop verify failed')}")

    try:
        after = fetch_open_algo_orders(exchange)
    except Exception as exc:
        result["errors"].append(f"final algo list: {exc}")
        return result
    result["algo_after"] = len(after)

    final_grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in after:
        final_grouped[str(order.get("symbol") or "").upper()].append(order)

    protected = []
    for symbol_id, position in active.items():
        detail = _detail_for(details, position["symbol"])
        expected_sl = _float(detail.get("SL_Fiyat"))
        orders = final_grouped.get(symbol_id, [])
        if len(orders) == 1 and _order_matches_stop(orders[0], position, expected_sl):
            protected.append(position["symbol"])
        else:
            result["errors"].append(f"{position['symbol']}: final protection mismatch")

    orphan_ids = sorted(symbol_id for symbol_id in final_grouped if symbol_id not in active)
    if orphan_ids:
        result["errors"].append(f"orphan algo orders remain: {','.join(orphan_ids)}")

    result["protected_symbols"] = sorted(set(protected))
    result["ready"] = not result["errors"] and len(protected) == len(active)
    return result
