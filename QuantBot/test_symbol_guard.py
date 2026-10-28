import unittest

from symbol_guard import _negatif_realized_gruplari


class SymbolGuardGroupingTests(unittest.TestCase):
    def test_split_fills_from_one_close_are_one_loss_event(self):
        grouped = _negatif_realized_gruplari(
            [(1_000, -0.4), (1_500, -0.5), (2_000, -0.6), (30_000, -2.0)]
        )

        self.assertEqual(2, len(grouped))
        self.assertAlmostEqual(-1.5, grouped[0])
        self.assertAlmostEqual(-2.0, grouped[1])

    def test_input_order_does_not_change_grouping(self):
        grouped = _negatif_realized_gruplari([(20_000, -1.0), (1_000, -0.5), (2_000, -0.5)])

        self.assertEqual([-1.0, -1.0], grouped)


if __name__ == "__main__":
    unittest.main()
