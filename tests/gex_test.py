"""Tests for GEX / option-Greeks analytics (INDstocks option chain)."""

import unittest
from datetime import date
from unittest import mock

import gex


def _leg(oi=1_000_000, gamma=0.001, delta=0.5, theta=-1.0, vega=2.0,
         iv=12.0, prev_oi=None, volume=100):
    return {
        "security_id": "1", "symbol": "TEST", "ltp": 100.0,
        "oi": oi, "prev_oi": oi if prev_oi is None else prev_oi,
        "volume": volume, "iv": iv,
        "delta": delta, "gamma": gamma, "theta": theta, "vega": vega,
    }


def _chain(rows, ltp=25000.0):
    return {
        "index": "NIFTY", "name": "NIFTY 50", "expiry": "2026-11-23",
        "underlying_ltp": ltp, "expiries": ["2026-11-23"], "strikes": rows,
    }


def _row(strike, ce=None, pe=None):
    return {"strike": strike, "ce": ce or _leg(), "pe": pe or _leg()}


class AnalyzeChainTests(unittest.TestCase):
    def test_greeks_and_gex_are_propagated(self):
        chain = _chain([
            _row(24900, ce=_leg(oi=2_000_000, gamma=0.002, delta=0.3,
                                theta=-2, vega=3),
                 pe=_leg(oi=1_000_000, gamma=0.001, delta=-0.2)),
            _row(25000),
            _row(25100),
        ])
        d = gex.analyze_chain(chain, lot_size=65)
        row = d["rows"][0]
        self.assertEqual(row["ce"]["gamma"], 0.002)
        self.assertEqual(row["pe"]["vega"], 2.0)
        self.assertEqual(row["ce"]["theta"], -2)
        per_pct = 65 * 25000 * 0.01
        self.assertAlmostEqual(row["call_gex_cr"],
                               round(-2_000_000 * 0.002 * per_pct / 1e7, 2))
        self.assertAlmostEqual(row["put_gex_cr"],
                               round(1_000_000 * 0.001 * per_pct / 1e7, 2))

    def test_verdict_sellers_when_put_gex_dominates(self):
        chain = _chain([
            _row(24900, ce=_leg(oi=10, gamma=0.001), pe=_leg(oi=5_000_000)),
            _row(25000, ce=_leg(oi=10, gamma=0.001), pe=_leg(oi=5_000_000)),
        ])
        d = gex.analyze_chain(chain, 65)
        self.assertGreater(d["gex_cr"], 0)
        self.assertEqual(d["control_tone"], "sellers")

    def test_verdict_buyers_when_call_gex_dominates(self):
        chain = _chain([
            _row(24900, ce=_leg(oi=5_000_000), pe=_leg(oi=10, gamma=0.001)),
            _row(25000, ce=_leg(oi=5_000_000), pe=_leg(oi=10, gamma=0.001)),
        ])
        d = gex.analyze_chain(chain, 65)
        self.assertLess(d["gex_cr"], 0)
        self.assertEqual(d["control_tone"], "buyers")

    def test_pcr_max_pain_and_oi_change(self):
        chain = _chain([
            _row(100, ce=_leg(oi=1_000_000, prev_oi=800_000),
                 pe=_leg(oi=2_000_000, prev_oi=1_500_000)),
            _row(110, ce=_leg(oi=3_000_000, prev_oi=3_000_000),
                 pe=_leg(oi=1_000, prev_oi=1_000)),
        ])
        d = gex.analyze_chain(chain, 65)
        self.assertAlmostEqual(d["pcr_oi"], 0.5)
        self.assertEqual(d["ce_oi_change"], 200_000)
        self.assertEqual(d["pe_oi_change"], 500_000)
        self.assertEqual(d["max_pain"], 100.0)

    def test_gamma_flip_interpolated_when_cumulative_crosses_zero(self):
        chain = _chain([
            _row(100, ce=_leg(oi=5_000_000, gamma=0.001), pe=_leg(oi=0)),
            _row(110, ce=_leg(oi=0), pe=_leg(oi=20_000_000, gamma=0.001)),
            _row(120, ce=_leg(oi=0), pe=_leg(oi=0)),
        ])
        d = gex.analyze_chain(chain, 65)
        self.assertIsNotNone(d["gamma_flip"])
        self.assertTrue(110 < d["gamma_flip"] < 120)


class FetchChainTests(unittest.TestCase):
    def test_normalises_api_payload(self):
        payload = {"status": "success", "data": {
            "underlying_ltp": 25000, "expiry": "2026-11-23",
            "strikes": {
                "25100": {"ce": {"last_price": 100, "oi": 10, "previous_oi": 8,
                                 "greeks": {"delta": 0.5, "gamma": 0.001}},
                          "pe": {"last_price": 50, "oi": 20,
                                 "greeks": {"delta": -0.4, "gamma": 0.0012}}},
                "25000": {"ce": {}, "pe": {}},
            },
        }}

        class Resp:
            def raise_for_status(self):
                pass

            def json(self):
                return payload

        calls = {}

        def fake_get(url, **kw):
            calls.update(url=url, **kw)
            return Resp()

        with mock.patch.object(gex, "get_token", return_value="TOKEN"):
            result = gex.fetch_chain("nifty", "2026-11-23", 3, fake_get)
        self.assertEqual(calls["params"]["underlying-scrip"], "40000001")
        self.assertEqual(calls["params"]["exchange"], "NSE")
        self.assertEqual(calls["headers"]["Authorization"], "TOKEN")
        self.assertEqual([r["strike"] for r in result["strikes"]], [25000, 25100])
        self.assertEqual(result["strikes"][1]["ce"]["oi"], 10)
        self.assertEqual(result["strikes"][1]["pe"]["gamma"], 0.0012)

    def test_rejects_unknown_index(self):
        with self.assertRaises(ValueError):
            gex.fetch_chain("BANKNIFTY", "2026-11-23")


class ExpiryTests(unittest.TestCase):
    def test_only_upcoming_expiries(self):
        meta = {"NIFTY": {"upcoming_expiries": ["2026-01-01", "2026-12-01"],
                          "nearest_expiry": "2026-01-01"}}
        with mock.patch.object(gex, "load_index_meta", return_value=meta):
            self.assertEqual(gex.available_expiries("NIFTY", date(2026, 11, 19)),
                             ["2026-12-01"])
            self.assertEqual(gex.pick_expiry("NIFTY", date(2026, 11, 19)),
                             "2026-12-01")


if __name__ == "__main__":
    unittest.main()
