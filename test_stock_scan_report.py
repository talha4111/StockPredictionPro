import unittest
from datetime import datetime
from pathlib import Path

from stock_scan_report import build_report_rows, generate_stock_scan_report


class StockScanReportTests(unittest.TestCase):
    def setUp(self):
        self.output_dir = Path(__file__).resolve().parent / ".test_stock_report"
        self.output_dir.mkdir(exist_ok=True)

    def tearDown(self):
        for path in self.output_dir.glob("*"):
            path.unlink()
        self.output_dir.rmdir()

    @staticmethod
    def _row(symbol, score, price=110.0, sma50=105.0, sma200=100.0, rsi=55.0):
        return {
            "sembol": symbol,
            "sektor": "Technology",
            "karar": "AL_ADAYI",
            "kurulum": "TREND_DEVAMI",
            "faktor_skor": score,
            "kalite_skor": 80.0,
            "deger_skor": 60.0,
            "momentum_skor": 70.0,
            "risk_skor": 65.0,
            "fiyat": price,
            "sma_50": sma50,
            "sma_200": sma200,
            "rsi": rsi,
            "hacim_teyit": True,
            "veri_durumu": "OK",
            "veri_tarihi": "2026-07-22",
            "olumlu_nedenler": ["Kalite %80"],
            "olumsuz_nedenler": [],
        }

    def test_rows_use_pure_factor_rank_and_m00_comparison(self):
        baseline = [self._row("BBB", 70), self._row("AAA", 90)]
        challenger = [self._row("BBB", 95), self._row("AAA", 60)]

        rows = build_report_rows(baseline, challenger)

        self.assertEqual([row["symbol"] for row in rows], ["AAA", "BBB"])
        self.assertEqual(rows[0]["m00_rank"], 2)
        self.assertEqual(rows[0]["rank_delta"], -1)
        self.assertEqual(rows[0]["trend_status"], "UYGUN")
        self.assertEqual(rows[0]["rsi_status"], "UYGUN")

    def test_report_is_self_contained_and_escapes_payload(self):
        baseline = [self._row("A<script>", 90)]
        challenger = [self._row("A<script>", 91)]

        output = generate_stock_scan_report(
            baseline,
            challenger,
            16.6,
            output_dir=self.output_dir,
            generated_at=datetime(2026, 7, 23, 1, 0),
        )
        content = output.read_text(encoding="utf-8")

        self.assertEqual(output.name, "stock_scan_latest.html")
        self.assertIn("Hisse Tarama Raporu", content)
        self.assertIn("CSV indir", content)
        self.assertIn(r"join('\r\n')", content)
        self.assertNotIn("A<script>", content)
        self.assertIn("A\\u003cscript\\u003e", content)


if __name__ == "__main__":
    unittest.main()