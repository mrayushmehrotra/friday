"""
Unit tests for Options-Enabled Stocks discovery and INDstocks API integration.
"""

import os
import sys
import json
import csv
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fetch_option_stocks import (
    IndstocksOptionScanner,
    DEFAULT_STOCKS_JSON,
    DEFAULT_STOCKS_CSV,
    DEFAULT_INDICES_JSON,
    DEFAULT_INDICES_CSV,
)


class TestOptionStocks(unittest.TestCase):

    def test_stocks_files_exist(self):
        self.assertTrue(os.path.exists(DEFAULT_STOCKS_JSON), "stocks_with_options.json must exist")
        self.assertTrue(os.path.exists(DEFAULT_STOCKS_CSV), "stocks_with_options.csv must exist")
        self.assertTrue(os.path.exists(DEFAULT_INDICES_JSON), "indices_with_options.json must exist")
        self.assertTrue(os.path.exists(DEFAULT_INDICES_CSV), "indices_with_options.csv must exist")

    def test_stocks_json_structure(self):
        with open(DEFAULT_STOCKS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertIn("total_stocks_with_options", data)
        self.assertGreaterEqual(data["total_stocks_with_options"], 200)
        stocks = data.get("stocks", [])
        self.assertEqual(len(stocks), data["total_stocks_with_options"])

        for s in stocks:
            self.assertTrue(bool(s["symbol"]), "Stock must have a symbol")
            self.assertIsNotNone(s["lot_size"], f"Stock {s['symbol']} must have valid lot size")
            self.assertGreater(s["lot_size"], 0)
            self.assertTrue(s["has_call"], f"Stock {s['symbol']} must have Call options")
            self.assertTrue(s["has_put"], f"Stock {s['symbol']} must have Put options")
            self.assertTrue(s["options_enabled"])
            self.assertGreater(len(s["upcoming_expiries"]), 0, f"Stock {s['symbol']} must have expiries")
            self.assertGreater(s["strike_count"], 0, f"Stock {s['symbol']} must have strike prices")
            self.assertLessEqual(s["min_strike"], s["max_strike"])

    def test_major_bluechips_present(self):
        with open(DEFAULT_STOCKS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        stock_map = {s["symbol"]: s for s in data["stocks"]}

        key_symbols = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "SBIN", "TATASTEEL", "LT"]
        for sym in key_symbols:
            self.assertIn(sym, stock_map, f"Major stock {sym} should be in optionable list")
            stk = stock_map[sym]
            self.assertTrue(stk["has_call"])
            self.assertTrue(stk["has_put"])
            self.assertGreater(stk["lot_size"], 0)
            self.assertIsNotNone(stk["nse_security_id"])
            self.assertTrue(stk["scrip_code"].startswith("NSE_"))

    def test_indices_options(self):
        with open(DEFAULT_INDICES_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)

        idx_map = {idx["symbol"]: idx for idx in data["indices"]}
        self.assertIn("NIFTY", idx_map)
        self.assertIn("BANKNIFTY", idx_map)
        self.assertIn("SENSEX", idx_map)

        for sym, idx in idx_map.items():
            self.assertTrue(idx["has_call"])
            self.assertTrue(idx["has_put"])
            self.assertTrue(bool(idx["security_id"]), f"Index {sym} must have security_id")
            self.assertTrue(bool(idx["scrip_code"]), f"Index {sym} must have scrip_code")

    def test_csv_matches_json(self):
        with open(DEFAULT_STOCKS_JSON, "r", encoding="utf-8") as f:
            json_stocks = json.load(f)["stocks"]

        with open(DEFAULT_STOCKS_CSV, "r", encoding="utf-8") as f:
            reader = list(csv.DictReader(f))

        self.assertEqual(len(json_stocks), len(reader))
        json_symbols = [s["symbol"] for s in json_stocks]
        csv_symbols = [r["symbol"] for r in reader]
        self.assertEqual(json_symbols, csv_symbols)


if __name__ == "__main__":
    unittest.main()
