import unittest

from order_engine import _borsa_sembol_destekli_mi, _stop_on_kontrol


class BrokenExchange:
    markets = {}
    symbols = []

    def load_markets(self):
        raise RuntimeError("market metadata unavailable")


class SafetyGuardTests(unittest.TestCase):
    def test_market_metadata_failure_blocks_entry(self):
        self.assertFalse(_borsa_sembol_destekli_mi(BrokenExchange(), "AAA/USDT:USDT"))

    def test_invalid_stop_inputs_block_entry(self):
        self.assertFalse(_stop_on_kontrol("LONG", "AAA/USDT:USDT", None, 100.0))
        self.assertFalse(_stop_on_kontrol("LONG", "AAA/USDT:USDT", 95.0, 0.0))

if __name__ == "__main__":
    unittest.main()
