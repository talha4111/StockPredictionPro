import unittest

import numpy as np
import pandas as pd

from stock_norgate_data import (
    NorgateDataAdapter,
    NorgateDataError,
)


class _Adjustment:
    TOTALRETURN = "total_return"


class _Padding:
    NONE = "none"


class FakeNorgate:
    StockPriceAdjustmentType = _Adjustment
    PaddingType = _Padding

    def __init__(self, running=True):
        self.running = running
        self.dates = pd.bdate_range("2024-01-02", periods=8)

    def status(self):
        return self.running

    def databases(self):
        return ["US Equities", "US Equities Delisted"]

    def watchlists(self):
        return ["S&P 500 Current & Past"]

    def watchlist_symbols(self, _):
        return ["AAA", "DEAD"]

    def price_timeseries(self, symbol, **_):
        base = 20.0 if symbol == "AAA" else 10.0
        close = base + np.arange(len(self.dates), dtype=float)
        return pd.DataFrame(
            {
                "Open": close - 0.2,
                "High": close + 0.5,
                "Low": close - 0.5,
                "Close": close,
                "Volume": np.full(len(close), 1_000_000.0),
                "Unadjusted Close": close / 2.0,
            },
            index=self.dates,
        )

    def index_constituent_timeseries(self, symbol, index_name=None, **kwargs):
        result = kwargs["pandas_dataframe"].copy()
        values = np.ones(len(result), dtype=int)
        if symbol == "DEAD":
            values[-3:] = 0
        result["Index Constituent"] = values
        return result

    def classification_at_level(self, symbol, *_):
        return "Technology" if symbol == "AAA" else "Industrials"


class NorgateDataTests(unittest.TestCase):
    def test_readiness_fails_closed_when_updater_is_not_running(self):
        adapter = NorgateDataAdapter(FakeNorgate(running=False))
        self.assertFalse(adapter.readiness()["ready"])
        with self.assertRaisesRegex(NorgateDataError, "hazir degil"):
            adapter.require_ready()

    def test_bundle_keeps_delisted_history_and_point_in_time_membership(self):
        adapter = NorgateDataAdapter(FakeNorgate())
        bundle = adapter.load_bundle("2024-01-02", "2024-01-11")

        self.assertIn("DEAD", bundle.histories)
        self.assertIn("DEAD", bundle.universe_provider("2024-01-05"))
        self.assertNotIn("DEAD", bundle.universe_provider("2024-01-11"))
        self.assertEqual(bundle.histories["AAA"]["RawClose"].iloc[0], 10.0)
        self.assertTrue(bundle.universe_provider.metadata["point_in_time_eligible"])

    def test_current_gics_mode_is_explicitly_diagnostic(self):
        adapter = NorgateDataAdapter(FakeNorgate())
        bundle = adapter.load_bundle(
            "2024-01-02",
            "2024-01-11",
            sector_mode="current_gics",
        )

        self.assertEqual(
            bundle.universe_provider("2024-01-05")["AAA"],
            "Technology",
        )
        self.assertFalse(bundle.universe_provider.metadata["point_in_time_eligible"])


if __name__ == "__main__":
    unittest.main()
