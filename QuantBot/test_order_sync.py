import unittest

from order_sync import reconcile_protective_orders


class FakeExchange:
    def __init__(self):
        self.algos = [
            {"algoId": "1", "symbol": "AAAUSDT", "orderType": "TAKE_PROFIT_MARKET", "side": "SELL", "quantity": "3", "triggerPrice": "110", "reduceOnly": True},
            {"algoId": "2", "symbol": "AAAUSDT", "orderType": "STOP_MARKET", "side": "SELL", "quantity": "8", "triggerPrice": "90", "reduceOnly": True},
            {"algoId": "3", "symbol": "OLDUSDT", "orderType": "STOP_MARKET", "side": "SELL", "quantity": "2", "triggerPrice": "8", "reduceOnly": True},
        ]

    def market_id(self, symbol):
        return symbol.replace("/", "")

    def amount_to_precision(self, symbol, amount):
        return str(amount)

    def price_to_precision(self, symbol, price):
        return str(price)

    def cancel_all_orders(self, symbol):
        return []

    def fapiPrivateGetOpenAlgoOrders(self, params):
        return list(self.algos)

    def fapiPrivateDeleteAlgoOpenOrders(self, params):
        self.algos = [item for item in self.algos if item["symbol"] != params["symbol"]]
        return {"code": 200}

    def create_order(self, symbol, type, side, amount, params):
        order = {
            "algoId": str(len(self.algos) + 10),
            "symbol": self.market_id(symbol),
            "orderType": type,
            "side": side.upper(),
            "quantity": str(amount),
            "triggerPrice": str(params["stopPrice"]),
            "reduceOnly": params["reduceOnly"],
        }
        self.algos.append(order)
        return order


class OrderSyncTests(unittest.TestCase):
    def test_orphans_and_duplicates_are_replaced_by_one_hard_stop(self):
        exchange = FakeExchange()
        positions = [{
            "symbol": "AAA/USDT:USDT",
            "contracts": 5,
            "side": "long",
            "entryPrice": 100,
            "markPrice": 101,
            "info": {"positionAmt": "5", "entryPrice": "100", "markPrice": "101"},
        }]
        details = {"AAA/USDT_TESTNET": {"SL_Fiyat": 95}}

        result = reconcile_protective_orders(exchange, positions, details)

        self.assertTrue(result["ready"], result)
        self.assertEqual(["OLDUSDT"], result["cleaned_symbols"])
        self.assertEqual(["AAA/USDT"], result["rebuilt_symbols"])
        self.assertEqual(1, len(exchange.algos))
        self.assertEqual("STOP_MARKET", exchange.algos[0]["orderType"])
        self.assertEqual("5.0", exchange.algos[0]["quantity"])

    def test_missing_sl_blocks_entry_readiness(self):
        exchange = FakeExchange()
        exchange.algos = []
        positions = [{
            "symbol": "AAA/USDT:USDT",
            "contracts": 5,
            "side": "long",
            "entryPrice": 100,
            "markPrice": 101,
            "info": {"positionAmt": "5"},
        }]

        result = reconcile_protective_orders(exchange, positions, {})

        self.assertFalse(result["ready"])
        self.assertTrue(any("missing SL" in error for error in result["errors"]))


if __name__ == "__main__":
    unittest.main()
