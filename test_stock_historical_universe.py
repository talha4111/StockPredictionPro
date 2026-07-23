import json
import unittest
from unittest.mock import patch

import stock_walkforward as walkforward
from stock_historical_universe import (
    HistoricalUniverseProvider,
    UniverseChange,
    UniverseDataError,
)


SOURCE = "https://press.spglobal.com/example"


class HistoricalUniverseProviderTests(unittest.TestCase):
    @staticmethod
    def _provider(complete=True):
        return HistoricalUniverseProvider(
            anchor_date="2024-06-30",
            anchor_constituents={"AAA": "Tech", "CCC": "Health"},
            changes=[
                UniverseChange.from_mapping(
                    {
                        "effective_date": "2024-03-18",
                        "action": "ADD",
                        "symbol": "AAA",
                        "sector": "Tech",
                        "source_url": SOURCE,
                    }
                ),
                UniverseChange.from_mapping(
                    {
                        "effective_date": "2024-05-01",
                        "action": "REMOVE",
                        "symbol": "BBB",
                        "sector": "Energy",
                        "source_url": SOURCE,
                    }
                ),
                UniverseChange.from_mapping(
                    {
                        "effective_date": "2024-09-23",
                        "action": "ADD",
                        "symbol": "DDD",
                        "sector": "Industry",
                        "source_url": SOURCE,
                    }
                ),
            ],
            coverage_start="2024-01-01",
            coverage_end="2024-12-31",
            source="S&P DJI official change releases",
            complete=complete,
        )

    def test_reconstructs_backward_and_forward_with_effective_date_semantics(self):
        provider = self._provider()

        self.assertEqual(provider("2024-03-17"), {"BBB": "Energy", "CCC": "Health"})
        self.assertEqual(
            provider("2024-03-18"),
            {"AAA": "Tech", "BBB": "Energy", "CCC": "Health"},
        )
        self.assertEqual(provider("2024-05-01"), {"AAA": "Tech", "CCC": "Health"})
        self.assertIn("DDD", provider("2024-09-23"))

    def test_fails_closed_outside_declared_coverage(self):
        provider = self._provider()
        with self.assertRaisesRegex(UniverseDataError, "kapsaminin disinda"):
            provider("2023-12-31")

    def test_complete_data_requires_a_source_for_every_change(self):
        with self.assertRaisesRegex(UniverseDataError, "HTTPS kaynak"):
            HistoricalUniverseProvider(
                anchor_date="2024-06-30",
                anchor_constituents={"AAA": "Tech"},
                changes=[
                    UniverseChange.from_mapping(
                        {
                            "effective_date": "2024-03-18",
                            "action": "ADD",
                            "symbol": "AAA",
                            "sector": "Tech",
                        }
                    )
                ],
                coverage_start="2024-01-01",
                coverage_end="2024-12-31",
                source="test",
                complete=True,
            )

    def test_json_loader_and_audit_metadata(self):
        payload = {
            "schema_version": 1,
            "source": "S&P DJI official change releases",
            "coverage": {
                "start": "2024-01-01",
                "end": "2024-12-31",
                "complete": True,
            },
            "anchor": {
                "date": "2024-06-30",
                "constituents": [
                    {"symbol": "AAA", "sector": "Tech"},
                    {"symbol": "CCC", "sector": "Health"},
                ],
            },
            "changes": [
                {
                    "effective_date": "2024-03-18",
                    "action": "ADD",
                    "symbol": "AAA",
                    "sector": "Tech",
                    "source_url": SOURCE,
                }
            ],
        }
        with patch(
            "stock_historical_universe.Path.read_text",
            return_value=json.dumps(payload),
        ):
            provider = HistoricalUniverseProvider.from_json("universe.json")

        self.assertTrue(provider.metadata["point_in_time_eligible"])
        self.assertEqual(provider.metadata["cited_change_count"], 1)
        self.assertEqual(provider.symbols, ["AAA", "CCC"])

    def test_walkforward_validity_requires_audited_provider_metadata(self):
        class AuditedFundamentals:
            metadata = {"point_in_time_eligible": True}

        config = walkforward.WalkForwardConfig(
            start_date="2024-01-01",
            strategy_mode="full_factor",
            fundamental_mode="point_in_time",
            universe_mode="point_in_time",
            event_risk_mode="point_in_time",
        )
        unaudited = walkforward._validity(
            config,
            fundamental_provider=lambda *_: {},
            universe_provider=lambda _: {"AAA": "Tech"},
        )
        audited = walkforward._validity(
            config,
            fundamental_provider=AuditedFundamentals(),
            universe_provider=self._provider(),
        )

        self.assertFalse(unaudited["production_valid"])
        self.assertFalse(unaudited["point_in_time_fundamentals_audited"])
        self.assertFalse(unaudited["point_in_time_universe_audited"])
        self.assertTrue(audited["production_valid"])
        self.assertTrue(audited["point_in_time_fundamentals_audited"])
        self.assertTrue(audited["point_in_time_universe_audited"])
        self.assertFalse(audited["event_calendar_required"])


if __name__ == "__main__":
    unittest.main()
