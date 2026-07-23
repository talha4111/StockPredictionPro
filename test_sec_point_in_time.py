import gzip
import json
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

import sec_point_in_time as sec


def _fact(val, end, filed, form="10-K", start=None, accn="1"):
    row = {"val": val, "end": end, "filed": filed, "form": form, "accn": accn}
    if start:
        row["start"] = start
    return row


def _concept(rows, unit="USD"):
    return {"units": {unit: rows}}


class SECPointInTimeTests(unittest.TestCase):
    def test_user_agent_requires_contact_identity(self):
        with self.assertRaises(ValueError):
            sec.validate_user_agent("StockPredictionPro")
        self.assertEqual(
            sec.validate_user_agent("StockPredictionPro research@example.com"),
            "StockPredictionPro research@example.com",
        )

    def test_offline_client_uses_existing_cache_and_fails_closed_when_missing(self):
        cache_dir = Path(__file__).resolve().parent / ".test_sec_offline_cache"
        cache_dir.mkdir(exist_ok=True)
        try:
            ticker_payload = {
                "0": {"ticker": "AAA", "cik_str": 1234},
            }
            with gzip.open(cache_dir / "company_tickers.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(ticker_payload, handle)
            facts_payload = {"cik": 1234, "entityName": "AAA", "facts": {}}
            with gzip.open(cache_dir / "CIK0000001234.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(facts_payload, handle)

            client = sec.SECCompanyFactsClient(
                "StockPredictionPro research@example.com",
                cache_dir=cache_dir,
                offline_cache=True,
            )
            self.assertEqual(client.cik_for_ticker("AAA"), "0000001234")
            self.assertEqual(client.company_facts("1234")["entityName"], "AAA")
            with self.assertRaisesRegex(RuntimeError, "onbellegi eksik"):
                client.company_facts("9999")
        finally:
            for path in cache_dir.glob("*"):
                path.unlink(missing_ok=True)
            cache_dir.rmdir()

    def test_env_loader_falls_back_to_quantbot_env(self):
        original_file = sec.__file__
        project = Path(__file__).resolve().parent / ".test_sec_env"
        env_path = project / "QuantBot" / ".env"
        try:
            (project / "QuantBot").mkdir(parents=True, exist_ok=True)
            env_path.write_text(
                "SEC_USER_AGENT=StockPredictionPro research@example.com\n",
                encoding="utf-8",
            )
            sec.__file__ = str(project / "sec_point_in_time.py")
            value = sec._env_value("SEC_USER_AGENT", project / "missing.env")
        finally:
            sec.__file__ = original_file
            env_path.unlink(missing_ok=True)
            if (project / "QuantBot").exists():
                (project / "QuantBot").rmdir()
            if project.exists():
                project.rmdir()
        self.assertEqual(value, "StockPredictionPro research@example.com")

    def test_same_day_and_future_filings_are_not_visible(self):
        payload = {
            "facts": {"us-gaap": {"Revenues": _concept([
                _fact(100, "2023-12-31", "2024-02-15", start="2023-01-01", accn="old"),
                _fact(200, "2024-12-31", "2025-02-20", start="2024-01-01", accn="new"),
            ])}}
        }

        same_day = sec.ttm_fact(payload, "revenue", "2025-02-20")
        next_day = sec.ttm_fact(payload, "revenue", "2025-02-21")

        self.assertEqual(same_day.value, 100)
        self.assertEqual(next_day.value, 200)

    def test_duplicate_instant_facts_use_accession_as_tie_breaker(self):
        payload = {
            "facts": {"us-gaap": {"Assets": _concept([
                _fact(100, "2024-12-31", "2025-02-20", accn="0001"),
                _fact(110, "2024-12-31", "2025-02-20", accn="0002"),
            ])}}
        }

        selected = sec.latest_instant(payload, "assets", "2025-02-21")

        self.assertEqual(selected.value, 110)
        self.assertEqual(selected.accession, "0002")

    def test_ttm_uses_annual_plus_current_ytd_minus_prior_ytd(self):
        payload = {
            "facts": {"us-gaap": {"Revenues": _concept([
                _fact(100, "2023-12-31", "2024-02-15", start="2023-01-01", accn="annual"),
                _fact(45, "2023-06-30", "2024-08-01", form="10-Q", start="2023-01-01", accn="q2"),
                _fact(70, "2024-06-30", "2024-08-01", form="10-Q", start="2024-01-01", accn="q2"),
                _fact(35, "2024-06-30", "2024-08-01", form="10-Q", start="2024-04-01", accn="q2"),
            ])}}
        }

        result = sec.ttm_fact(payload, "revenue", "2024-08-02")

        self.assertEqual(result.form, "TTM")
        self.assertAlmostEqual(result.value, 125.0)

        indexed_result = sec.ttm_fact(
            sec.IndexedCompanyFacts(payload), "revenue", "2024-08-02"
        )
        self.assertEqual(indexed_result.form, "TTM")
        self.assertAlmostEqual(indexed_result.value, result.value)

    def test_snapshot_uses_raw_price_for_market_cap(self):
        revenue_rows = [
            _fact(800, "2022-12-31", "2023-02-15", start="2022-01-01", accn="r0"),
            _fact(1000, "2023-12-31", "2024-02-15", start="2023-01-01", accn="r1"),
        ]
        net_rows = [
            _fact(80, "2022-12-31", "2023-02-15", start="2022-01-01", accn="n0"),
            _fact(100, "2023-12-31", "2024-02-15", start="2023-01-01", accn="n1"),
        ]
        payload = {
            "facts": {
                "dei": {
                    "EntityCommonStockSharesOutstanding": _concept([
                        _fact(10, "2023-12-31", "2024-02-15")
                    ], unit="shares")
                },
                "us-gaap": {
                    "Revenues": _concept(revenue_rows),
                    "NetIncomeLoss": _concept(net_rows),
                    "GrossProfit": _concept([
                        _fact(400, "2023-12-31", "2024-02-15", start="2023-01-01")
                    ]),
                    "NetCashProvidedByUsedInOperatingActivities": _concept([
                        _fact(160, "2023-12-31", "2024-02-15", start="2023-01-01")
                    ]),
                    "PaymentsToAcquirePropertyPlantAndEquipment": _concept([
                        _fact(60, "2023-12-31", "2024-02-15", start="2023-01-01")
                    ]),
                    "PaymentsOfDividends": _concept([
                        _fact(20, "2023-12-31", "2024-02-15", start="2023-01-01")
                    ]),
                    "Assets": _concept([_fact(2000, "2023-12-31", "2024-02-15")]),
                    "StockholdersEquity": _concept([_fact(500, "2023-12-31", "2024-02-15")]),
                    "LongTermDebtCurrent": _concept([_fact(50, "2023-12-31", "2024-02-15")]),
                    "LongTermDebtNoncurrent": _concept([_fact(150, "2023-12-31", "2024-02-15")]),
                },
            }
        }

        snapshot = sec.build_factor_snapshot(payload, "2024-03-01", raw_close=100.0)

        self.assertEqual(snapshot["sec_market_cap"], 1000.0)
        self.assertAlmostEqual(snapshot["earnings_yield"], 0.10)
        self.assertAlmostEqual(snapshot["fcf_yield"], 0.10)
        self.assertAlmostEqual(snapshot["debt_to_equity"], 40.0)
        self.assertAlmostEqual(snapshot["profit_margin"], 0.10)
        self.assertGreaterEqual(snapshot["sec_metric_count"], 8)

    def test_normalized_prices_keep_raw_close_separate(self):
        from stock_walkforward import normalize_history

        frame = pd.DataFrame(
            {
                "Open": [98.0], "High": [102.0], "Low": [97.0], "Close": [100.0],
                "Adj Close": [10.0], "Volume": [1_000_000.0],
            },
            index=pd.to_datetime(["2024-01-02"]),
        )
        normalized = normalize_history(frame)

        self.assertEqual(normalized["Close"].iloc[0], 10.0)
        self.assertEqual(normalized["Open"].iloc[0], 9.8)
        self.assertEqual(normalized["RawClose"].iloc[0], 100.0)

    def test_compaction_removes_unneeded_tags(self):
        payload = {
            "cik": 1,
            "entityName": "Example",
            "facts": {"us-gaap": {
                "Revenues": _concept([]),
                "UnneededCustomLikeTag": _concept([]),
            }},
        }
        compact = sec.compact_company_facts(payload)

        self.assertIn("Revenues", compact["facts"]["us-gaap"])
        self.assertNotIn("UnneededCustomLikeTag", compact["facts"]["us-gaap"])


if __name__ == "__main__":
    unittest.main()
