"""
Unit and integration tests for Mark Minervini VCP Scanner and Swing Trading Filters.
"""

import unittest
import pandas as pd
import numpy as np
from vcp_scanner import (
    check_trend_template,
    detect_vcp_contractions,
    check_volume_dry_up,
    detect_relative_volume_divergence,
    check_breakout_confirmation,
    check_smc_confluence,
    check_4h_ema_alignment,
    analyze_vcp_stock,
    scan_universe_vcp,
    VCPResult,
)
import stock_dashboard


class TestVCPScanner(unittest.TestCase):
    def setUp(self):
        # Generate synthetic VCP candle series:
        # High at 100 -> pullback to 80 (-20%) -> rally to 98 -> pullback to 86 (-12%) -> rally to 97 -> pullback to 92 (-5%)
        np.random.seed(42)
        n_bars = 250
        dates = pd.date_range("2025-01-01", periods=n_bars, freq="D")
        
        # Base prices trending up
        close_prices = np.linspace(60, 100, n_bars)
        
        # Inject 3 contracting pullbacks at the end:
        # T1: bar 190 to 210: 100 -> 80
        # T2: bar 210 to 230: 98 -> 86
        # T3: bar 230 to 248: 97 -> 92
        close_prices[190:200] = np.linspace(100, 80, 10)
        close_prices[200:210] = np.linspace(80, 98, 10)
        close_prices[210:220] = np.linspace(98, 86, 10)
        close_prices[220:230] = np.linspace(86, 97, 10)
        close_prices[230:240] = np.linspace(97, 92, 10)
        close_prices[240:250] = np.linspace(92, 97.5, 10) # coiling near pivot
        
        high_prices = close_prices * 1.01
        low_prices = close_prices * 0.99
        open_prices = close_prices * 0.995
        
        # Declining volume in contractions
        volumes = np.full(n_bars, 1000000.0)
        volumes[190:210] = 900000.0
        volumes[210:230] = 600000.0
        volumes[230:248] = 400000.0
        volumes[248:250] = 1800000.0 # rising relative volume in final breakout / accumulation
        
        self.df_synthetic = pd.DataFrame({
            "Open": open_prices,
            "High": high_prices,
            "Low": low_prices,
            "Close": close_prices,
            "Volume": volumes,
        }, index=dates)

    def test_trend_template(self):
        trend_ok, metrics = check_trend_template(self.df_synthetic)
        self.assertTrue(trend_ok)
        self.assertGreater(metrics["sma50"], metrics["sma200"])
        self.assertGreater(self.df_synthetic["Close"].iloc[-1], metrics["sma50"])

    def test_vcp_contraction_detection(self):
        contractions = detect_vcp_contractions(self.df_synthetic, lookback=80, order=2)
        self.assertGreaterEqual(len(contractions), 2)
        # Check successively smaller depths
        depths = [c.depth_pct for c in contractions]
        for i in range(len(depths) - 1):
            self.assertGreater(depths[i], depths[i + 1])

    def test_volume_dry_up(self):
        contractions = detect_vcp_contractions(self.df_synthetic, lookback=80, order=2)
        dry_up, red_pct, phases = check_volume_dry_up(contractions)
        self.assertTrue(dry_up)
        self.assertGreater(red_pct, 0)

    def test_relative_volume_divergence(self):
        contractions = detect_vcp_contractions(self.df_synthetic, lookback=80, order=2)
        res = max(c.high_price for c in contractions)
        quiet_acc, rolling_rng, rvol, rvol_3d = detect_relative_volume_divergence(
            self.df_synthetic, contractions, res
        )
        self.assertGreater(rvol, 1.0)
        self.assertLess(rolling_rng, 10.0)

    def test_smc_confluence(self):
        contractions = detect_vcp_contractions(self.df_synthetic, lookback=80, order=2)
        res = max(c.high_price for c in contractions)
        smc_ok, smc_notes = check_smc_confluence(self.df_synthetic, res)
        self.assertIsInstance(smc_ok, bool)
        self.assertIsInstance(smc_notes, str)

    def test_4h_ema_alignment(self):
        # Synthetic 4h data
        df4h = pd.DataFrame({
            "Close": [100.0 + i for i in range(40)]
        })
        bullish, e9, e20, gap, bars = check_4h_ema_alignment(df4h)
        self.assertTrue(bullish)
        self.assertGreater(e9, e20)
        self.assertGreater(gap, 0)

    def test_allocation_and_sizing(self):
        # Test ₹2,000 allocation calculation
        res = analyze_vcp_stock("TEST", df_daily=self.df_synthetic, df_4h=self.df_synthetic)
        self.assertIsNotNone(res)
        self.assertEqual(res.allocation_inr, 2000.0)
        self.assertGreaterEqual(res.suggested_qty, 1)
        self.assertGreater(res.position_value, 0)
        self.assertGreater(res.target_price, res.price)
        self.assertLess(res.pivot_stop_loss, res.price)
        self.assertEqual(res.hold_expectation, "3-5 days minimum")

    def test_dashboard_swing_states(self):
        # Test dashboard swing picks state structure
        self.assertIn("combined", stock_dashboard._SWING_STATES)
        self.assertIn("vcp", stock_dashboard._SWING_STATES)
        self.assertIn("ema_range", stock_dashboard._SWING_STATES)

        picks_res = stock_dashboard._swing_picks(check="combined")
        self.assertEqual(picks_res["check"], "combined")
        self.assertIn("picks", picks_res)
        self.assertIn("breakouts", picks_res)
        self.assertIn("quiet_accumulations", picks_res)


if __name__ == "__main__":
    unittest.main()
