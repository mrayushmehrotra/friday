"""
Tests for the institutional deal watcher → Telegram alerts.
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

import institution_telegram_bot as bot
import telegram_notify


def _deal(**overrides):
    base = {
        "symbol": "RELIANCE",
        "name": "Reliance Industries",
        "client": "GOF",
        "clientName": "GOF",
        "exchange": "NSE",
        "deal_type": "Block",
        "buySell": "BUY",
        "date": "10 Nov 2026",
        "iso_date": datetime.now().strftime("%Y-%m-%d"),
        "watp": 2500.5,
        "qty": 1234567.0,
        "val": 1234567.0 * 2500.5,
    }
    base.update(overrides)
    return base


def _inst_data(institution="Government of Singapore", deals=None, error=None):
    if error:
        return {"error": error}
    return {"institution": institution, "deals": deals or []}


class TestDealKeyAndFormatting(unittest.TestCase):
    def test_deal_key_distinguishes_sides(self):
        buy = self._deal_key_of(_deal(buySell="BUY"))
        sell = self._deal_key_of(_deal(buySell="SELL"))
        self.assertNotEqual(buy, sell)

    def test_deal_key_same_deal_stable(self):
        self.assertEqual(self._deal_key_of(_deal()), self._deal_key_of(_deal()))

    def test_fmt_inr_scales(self):
        self.assertEqual(bot._fmt_inr(1.5e7), "₹1.50 Cr")
        self.assertEqual(bot._fmt_inr(2.5e5), "₹2.50 L")
        self.assertEqual(bot._fmt_inr(1500.0), "₹1,500")

    def test_message_contains_deal_fields(self):
        msg = bot._deal_message("Government of Singapore", _deal())
        self.assertIn("BUY", msg)
        self.assertIn("RELIANCE", msg)
        self.assertIn("Government of Singapore", msg)
        self.assertIn("₹308.70 Cr", msg)  # 1,234,567 * 2500.5 = ₹308.70 Cr
        self.assertIn("Block", msg)

    def test_message_escapes_html(self):
        msg = bot._deal_message("A & B <Fund>", _deal(name="X <&> Y"))
        self.assertNotIn("<Fund>", msg)
        self.assertIn("&lt;Fund&gt;", msg)

    def test_deal_is_fresh(self):
        fresh = _deal(iso_date=datetime.now().strftime("%Y-%m-%d"))
        old = _deal(iso_date=(datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
        self.assertTrue(bot._deal_is_fresh(fresh, 10))
        self.assertFalse(bot._deal_is_fresh(old, 10))
        self.assertTrue(bot._deal_is_fresh(_deal(iso_date=""), 10))

    def _deal_key_of(self, deal):
        return bot._deal_key("Government of Singapore", deal)


class TestPollOnce(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_state_path = bot.STATE_PATH
        bot.STATE_PATH = os.path.join(self.tmp, "state.json")
        self._orig_config = telegram_notify.load_config
        telegram_notify.load_config = lambda: {
            "bot_token": "t", "chat_id": "c",
            "poll_interval_min": 30, "max_deal_age_days": 10,
        }
        self.sent = []
        self._orig_send = bot.send_telegram_message
        bot.send_telegram_message = lambda text, **kw: (self.sent.append(text), True)[1]

    def tearDown(self):
        bot.STATE_PATH = self._orig_state_path
        telegram_notify.load_config = self._orig_config
        bot.send_telegram_message = self._orig_send

    def _scrape_factory(self, deals_by_url):
        def fake_scrape(url):
            for name, u in bot.INSTITUTIONS:
                if u == url:
                    return _inst_data(deals=deals_by_url.get(name, []))
            return {"error": "unknown url"}
        return fake_scrape

    def test_first_poll_marks_seen_without_alert(self):
        deals = {"Government of Singapore": [_deal()]}
        with mock.patch.object(bot, "_scrape_trendlyne_deals", self._scrape_factory(deals)):
            sent = bot.poll_once()
        self.assertEqual(sent, 0)
        self.assertEqual(self.sent, [])

    def test_new_deal_alerts_once(self):
        deals = {"Government of Singapore": [_deal()]}
        with mock.patch.object(bot, "_scrape_trendlyne_deals", self._scrape_factory(deals)):
            bot.poll_once()
            self.assertEqual(self.sent, [])
            deals["Government of Singapore"].append(_deal(buySell="SELL", symbol="TCS", qty=100.0))
            sent = bot.poll_once()
        self.assertEqual(sent, 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("SELL", self.sent[0])
        self.assertIn("TCS", self.sent[0])
        # Third poll — nothing new, no duplicate alert
        with mock.patch.object(bot, "_scrape_trendlyne_deals", self._scrape_factory(deals)):
            self.assertEqual(bot.poll_once(), 0)
        self.assertEqual(len(self.sent), 1)

    def test_old_backfilled_deal_not_alerted(self):
        deals = {"Government of Singapore": [_deal()]}
        with mock.patch.object(bot, "_scrape_trendlyne_deals", self._scrape_factory(deals)):
            bot.poll_once()
            deals["Government of Singapore"].append(
                _deal(symbol="WIPRO", iso_date=(datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")))
            sent = bot.poll_once()
        self.assertEqual(sent, 0)

    def test_state_survives_restart(self):
        deals = {"Government of Singapore": [_deal()]}
        with mock.patch.object(bot, "_scrape_trendlyne_deals", self._scrape_factory(deals)):
            bot.poll_once()
            bot.poll_once()
            deals["Government of Singapore"].append(_deal(symbol="INFY", qty=50.0))
            sent = bot.poll_once()
        self.assertEqual(sent, 1)


if __name__ == "__main__":
    unittest.main()
