"""Inspect or apply one-shot Binance demo protective-order reconciliation."""
from __future__ import annotations

import argparse
import json

import ccxt

from config import TESTNET_API_KEY, TESTNET_SECRET
from db_logger import _detay_yukle
from order_sync import fetch_open_algo_orders, market_id, normalize_symbol, reconcile_protective_orders


def build_exchange():
    exchange = ccxt.binanceusdm({
        "apiKey": TESTNET_API_KEY,
        "secret": TESTNET_SECRET,
        "enableRateLimit": True,
        "options": {
            "defaultType": "future",
            "adjustForTimeDifference": True,
            "recvWindow": 60000,
        },
    })
    exchange.enable_demo_trading(True)
    exchange.load_markets()
    return exchange


def active_positions(exchange):
    result = []
    for position in exchange.fetch_positions():
        info = position.get("info") or {}
        amount = float(info.get("positionAmt") or 0)
        if amount:
            result.append(position)
    return result


def inspect(exchange, positions, details):
    active_ids = {}
    for position in positions:
        info = position.get("info") or {}
        symbol = normalize_symbol(position.get("symbol") or info.get("symbol"))
        symbol_id = market_id(exchange, symbol).upper()
        amount = abs(float(info.get("positionAmt") or 0))
        side = "LONG" if float(info.get("positionAmt") or 0) > 0 else "SHORT"
        detail = details.get(f"{symbol}_TESTNET") or details.get(f"{symbol}_DEMO") or {}
        active_ids[symbol_id] = {
            "symbol": symbol,
            "side": side,
            "amount": amount,
            "sl": detail.get("SL_Fiyat"),
        }

    orders = fetch_open_algo_orders(exchange)
    counts = {}
    for order in orders:
        symbol_id = str(order.get("symbol") or "").upper()
        key = f"{symbol_id}:{str(order.get('orderType') or '').upper()}"
        counts[key] = counts.get(key, 0) + 1

    return {
        "active_positions": list(active_ids.values()),
        "active_count": len(active_ids),
        "algo_order_count": len(orders),
        "orphan_symbols": sorted({
            str(order.get("symbol") or "").upper()
            for order in orders
            if str(order.get("symbol") or "").upper() not in active_ids
        }),
        "order_counts": dict(sorted(counts.items())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Apply cleanup and stop reconciliation")
    args = parser.parse_args()

    exchange = build_exchange()
    positions = active_positions(exchange)
    details = _detay_yukle()
    before = inspect(exchange, positions, details)
    output = {"mode": "apply" if args.apply else "dry-run", "before": before}
    if args.apply:
        output["result"] = reconcile_protective_orders(exchange, positions, details)
        output["after"] = inspect(exchange, active_positions(exchange), details)
    print(json.dumps(output, ensure_ascii=True, indent=2, default=str))


if __name__ == "__main__":
    main()
