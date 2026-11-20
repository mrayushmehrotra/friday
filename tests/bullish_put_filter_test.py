"""
Unit tests for bullish_put_filter.py
"""

import os
import sys
import json
import csv
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bullish_put_filter import (
    BullishPutFilter,
    OUTPUT_JSON,
    OUTPUT_CSV,
)


class TestBullishPutFilter(unittest.TestCase):

    def test_output_files_exist(self):
        self.assertTrue(os.path.exists(OUTPUT_JSON), "bullish_stocks_with_cheap_puts.json must exist")
        self.assertTrue(os.path.exists(OUTPUT_CSV), "bullish_stocks_with_cheap_puts.csv must exist")

    def test_json_structure_and_criteria(self):
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("criteria", data)
        self.assertIn("results", data)
        self.assertGreaterEqual(len(data["results"]), 1)

        for r in data["results"]:
            self.assertTrue(bool(r["symbol"]))
            self.assertGreater(r["spot_ltp"], 0)
            self.assertGreater(r["lot_size"], 0)
            self.assertGreater(r["bullish_gain_pct"], 0)
            self.assertEqual(r["bullish_streak_days"], 5)

            # Check Put filter requirements:
            # 1. Premium < 20
            self.assertLess(r["best_put_premium"], 20.0, f"{r['symbol']} PE premium must be < 20")
            self.assertGreater(r["best_put_premium"], 0.0)

            # 2. Total 1 lot investment <= 5000 INR
            self.assertLessEqual(r["best_put_lot_cost"], 5000.0, f"{r['symbol']} 1-lot cost must be <= 5000")
            expected_cost = round(r["best_put_premium"] * r["lot_size"], 2)
            self.assertAlmostEqual(r["best_put_lot_cost"], expected_cost, places=1)

    def test_is_bullish_logic(self):
        scanner = BullishPutFilter(consecutive_days=5, bullish_mode="higher_closes")

        # 6 candles with 5 consecutive higher closes
        bullish_candles = [
            {"ts": 100, "o": 100, "h": 105, "l": 99, "c": 102},
            {"ts": 200, "o": 102, "h": 106, "l": 101, "c": 104},
            {"ts": 300, "o": 104, "h": 108, "l": 103, "c": 107},
            {"ts": 400, "o": 107, "h": 110, "l": 106, "c": 109},
            {"ts": 500, "o": 109, "h": 112, "l": 108, "c": 111},
            {"ts": 600, "o": 111, "h": 115, "l": 110, "c": 114},
        ]
        is_bull, details = scanner.is_bullish(bullish_candles)
        self.assertTrue(is_bull)
        self.assertTrue(details["is_higher_closes"])
        self.assertGreater(details["net_gain_pct"], 0)

        # Non-bullish series (day 4 drops)
        bearish_candles = [
            {"ts": 100, "o": 100, "h": 105, "l": 99, "c": 102},
            {"ts": 200, "o": 102, "h": 106, "l": 101, "c": 104},
            {"ts": 300, "o": 104, "h": 108, "l": 103, "c": 107},
            {"ts": 400, "o": 107, "h": 107, "l": 101, "c": 103},  # drop
            {"ts": 500, "o": 103, "h": 108, "l": 102, "c": 106},
            {"ts": 600, "o": 106, "h": 110, "l": 105, "c": 108},
        ]
        is_bull2, _ = scanner.is_bullish(bearish_candles)
        self.assertFalse(is_bull2)

    def test_csv_matches_json_results(self):
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            json_results = json.load(f)["results"]

        with open(OUTPUT_CSV, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        self.assertEqual(len(json_results), len(reader))
        for j, c in zip(json_results, reader):
            self.assertEqual(j["symbol"], c["symbol"])
            self.assertAlmostEqual(float(j["best_put_premium"]), float(c["best_put_premium"]))
            self.assertAlmostEqual(float(j["best_put_lot_cost"]), float(c["best_put_lot_cost"]))


if __name__ == "__main__":
    unittest.main()
