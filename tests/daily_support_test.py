"""
Unit and integration tests for Daily Support Level Scanner & Analyzer.
"""

import unittest
import numpy as np
import pandas as pd
from daily_support_scanner import (
    SupportLevel,
    DailySupportMatch,
    detect_swing_pivots,
    cluster_price_levels,
    detect_bullish_order_blocks,
    detect_breakout_retests,
    analyze_daily_support,
    load_universe_symbols,
    get_cached_or_scan_support,
    get_chart_series,
)


class TestDailySupportScanner(unittest.TestCase):
    def setUp(self):
        np.random.seed(42)
        n = 250
        dates = pd.date_range("2026-01-01", periods=n, freq="D")

        # Create an uptrending price series with a pullback landing onto SMA 50
        prices = np.linspace(800, 1200, n)
        # Pullback in the last 6 bars from 1200 down to 1100 (which touches the 50-day average)
        prices[-6:] = [1180, 1150, 1130, 1115, 1105, 1108]

        high = prices * 1.015
        low = prices * 0.985
        # Lower wick rejection on the final bar: low drops to 1095, closes at 1108, open at 1102
        low[-1] = 1095.0
        open_p = prices * 0.998
        open_p[-1] = 1102.0
        volume = np.full(n, 500000.0)

        self.df = pd.DataFrame({
            "Open": open_p,
            "High": high,
            "Low": low,
            "Close": prices,
            "Volume": volume,
        }, index=dates)

    def test_detect_swing_pivots(self):
        lows = self.df["Low"]
        highs = self.df["High"]
        sw_lows, sw_highs = detect_swing_pivots(lows, highs, order=3, lookback_bars=180)
        self.assertIsInstance(sw_lows, list)
        self.assertIsInstance(sw_highs, list)

    def test_cluster_price_levels(self):
        raw_levels = [
            (10, 100.0, "2026-02-01"),
            (25, 101.0, "2026-03-01"),
            (50, 150.0, "2026-04-01"),
        ]
        clusters = cluster_price_levels(raw_levels, tolerance_pct=1.5)
        self.assertEqual(len(clusters), 2)
        # First cluster has 2 touches around 100.5
        self.assertEqual(clusters[0][1], 2)
        self.assertAlmostEqual(clusters[0][0], 100.5, delta=0.5)

    def test_detect_bullish_order_blocks(self):
        # Inject an impulsive displacement bar at bar 100
        df_copy = self.df.copy()
        # Bar 100 is down bar
        df_copy.iloc[100, df_copy.columns.get_loc("Open")] = 950.0
        df_copy.iloc[100, df_copy.columns.get_loc("Close")] = 930.0
        # Bars 101-103 displace aggressively higher
        df_copy.iloc[101:104, df_copy.columns.get_loc("Close")] = 990.0
        df_copy.iloc[101:104, df_copy.columns.get_loc("High")] = 1010.0

        obs = detect_bullish_order_blocks(df_copy, lookback=150)
        self.assertIsInstance(obs, list)

    def test_analyze_daily_support(self):
        match = analyze_daily_support("SYNTHETIC.NS", df_daily=self.df, data_src="Test Synthetic")
        self.assertIsNotNone(match)
        self.assertEqual(match.symbol, "SYNTHETIC")
        self.assertTrue(match.is_good_stock)
        self.assertGreater(match.quality_score, 50)
        self.assertTrue(match.landed_on_support)
        self.assertIsNotNone(match.primary_support)
        self.assertIn("price", match.primary_support)
        self.assertGreater(len(match.all_supports), 0)
        self.assertGreater(match.suggested_entry, 0)
        self.assertGreater(match.stop_loss, 0)
        self.assertGreater(match.target_1, match.suggested_entry)
        self.assertGreater(match.risk_reward_ratio, 0)

    def test_universe_loader(self):
        nifty = load_universe_symbols("nifty50")
        self.assertGreaterEqual(len(nifty), 45)
        self.assertIn("RELIANCE", nifty)
        self.assertIn("TCS", nifty)

        fno = load_universe_symbols("fno")
        self.assertGreater(len(fno), 50)

    def test_chart_series_helper(self):
        # Test with a mock / live stock
        res = get_chart_series("HCLTECH", bars=30)
        if "error" not in res:
            self.assertEqual(res["ticker"], "HCLTECH")
            self.assertGreater(len(res["candles"]), 10)
            self.assertIn("close", res["candles"][0])


if __name__ == "__main__":
    unittest.main()
