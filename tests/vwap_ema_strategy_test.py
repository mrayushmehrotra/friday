"""Tests for the PineScript-equivalent VWAP x EMA trade-management rules."""

import unittest

import vwap_ema_strategy as s


def _pos(side="BUY", entry=100.0, sl=98.0, target=104.0, **extra):
    p = {
        "side": side, "entry_price": entry, "stop_loss": sl,
        "initial_stop_loss": sl, "target_price": target,
        "risk_per_share": abs(entry - sl), "extreme_price": entry,
        "trail_on": False, "is_breakeven": False,
    }
    p.update(extra)
    return p


class TrailingTests(unittest.TestCase):
    def test_long_ema_trail_ratchets_and_never_loosens(self):
        p = _pos()
        s.apply_trailing(p, {"high": 103, "low": 101, "close": 102, "ema": 101.5, "atr": 1.0},
                         {"trail_mode": "EMA Trail", "trail_start_r": 1.0, "use_be": True})
        self.assertTrue(p["trail_on"])
        self.assertGreaterEqual(p["stop_loss"], 100.0)  # breakeven locked
        before = p["stop_loss"]
        s.apply_trailing(p, {"high": 104, "low": 102, "close": 103, "ema": 100.0, "atr": 1.0},
                         {"trail_mode": "EMA Trail", "trail_start_r": 1.0, "use_be": True})
        self.assertEqual(p["stop_loss"], before)  # candidate below old SL ignored

    def test_atr_trail_uses_extreme_minus_atr(self):
        p = _pos()
        cfg = {"trail_mode": "ATR Trail", "trail_start_r": 0.0, "atr_mult": 2.0, "use_be": False}
        s.apply_trailing(p, {"high": 104, "low": 102, "close": 103, "ema": 101, "atr": 1.0}, cfg)
        self.assertAlmostEqual(p["stop_loss"], 102.0)

    def test_short_trail_moves_stop_down(self):
        p = _pos(side="SELL", entry=100.0, sl=102.0, target=96.0)
        s.apply_trailing(p, {"high": 99, "low": 97, "close": 98, "ema": 98.5, "atr": 1.0},
                         {"trail_mode": "EMA Trail", "trail_start_r": 0.0, "use_be": True})
        self.assertLessEqual(p["stop_loss"], 100.0)

    def test_fixed_mode_leaves_stop_untouched(self):
        p = _pos()
        s.apply_trailing(p, {"high": 103, "low": 101, "close": 102, "ema": 101.5, "atr": 1.0},
                         {"trail_mode": s.FIXED_MODE})
        self.assertEqual(p["stop_loss"], 98.0)
        self.assertFalse(p["trail_on"])


class ExitTests(unittest.TestCase):
    def test_partial_then_full_target(self):
        p = _pos()
        cfg = {"trail_mode": "EMA Trail", "use_partial": True}
        self.assertEqual(s.exit_signal(p, 104.0, cfg), "PARTIAL_TARGET")
        p["partial_done"] = True
        self.assertEqual(s.exit_signal(p, 104.0, cfg), "TARGET")
        self.assertEqual(s.exit_signal(p, 99.0, cfg), None)

    def test_fixed_mode_goes_straight_to_full_target(self):
        cfg = {"trail_mode": s.FIXED_MODE, "use_partial": True}
        self.assertEqual(s.exit_signal(_pos(), 104.0, cfg), "TARGET")
        self.assertEqual(s.exit_signal(_pos(), 97.5, cfg), "STOP")

    def test_short_target_and_stop(self):
        p = _pos(side="SELL", entry=100.0, sl=102.0, target=96.0)
        cfg = {"trail_mode": "EMA Trail", "use_partial": False}
        self.assertEqual(s.exit_signal(p, 95.5, cfg), "TARGET")
        self.assertEqual(s.exit_signal(p, 102.5, cfg), "STOP")


class PineScriptTests(unittest.TestCase):
    def test_pinescript_is_complete(self):
        self.assertIn("//@version=6", s.PINESCRIPT)
        self.assertIn("strategy(\"VWAP x EMA Cross | Smart Profit Trail\"", s.PINESCRIPT)
        for token in ("ta.vwap", "ta.ema", "ta.atr", "qty_percent=50",
                      "color.new(color.lime", "strategy.close_all(\"EOD\")"):
            self.assertIn(token, s.PINESCRIPT)


if __name__ == "__main__":
    unittest.main()
