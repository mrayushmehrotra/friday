"""
Tests for the Telegram sender (telegram_notify.py).
"""

import json
import os
import tempfile
import unittest
from unittest import mock

import telegram_notify


class _Resp:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class TestTelegramNotify(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_path = telegram_notify.CONFIG_PATH
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                  "TELEGRAM_POLL_INTERVAL_MIN", "TELEGRAM_MAX_DEAL_AGE_DAYS"):
            os.environ.pop(k, None)

    def tearDown(self):
        telegram_notify.CONFIG_PATH = self._orig_path
        self._env.stop()

    def _write_config(self, cfg):
        path = os.path.join(self.tmp, "telegram_config.json")
        with open(path, "w") as f:
            json.dump(cfg, f)
        telegram_notify.CONFIG_PATH = path

    def test_load_config_defaults(self):
        telegram_notify.CONFIG_PATH = os.path.join(self.tmp, "missing.json")
        cfg = telegram_notify.load_config()
        self.assertEqual(cfg["poll_interval_min"], 30.0)
        self.assertEqual(cfg["max_deal_age_days"], 10)

    def test_env_overrides_file(self):
        self._write_config({"bot_token": "file-token", "chat_id": "111"})
        os.environ["TELEGRAM_BOT_TOKEN"] = "env-token"
        os.environ["TELEGRAM_CHAT_ID"] = "222"
        cfg = telegram_notify.load_config()
        self.assertEqual(cfg["bot_token"], "env-token")
        self.assertEqual(cfg["chat_id"], "222")

    def test_is_configured(self):
        telegram_notify.CONFIG_PATH = os.path.join(self.tmp, "missing.json")
        self.assertFalse(telegram_notify.is_configured())
        self._write_config({"bot_token": "t", "chat_id": "1"})
        self.assertTrue(telegram_notify.is_configured())

    @mock.patch("telegram_notify.requests.post")
    def test_send_success(self, post):
        self._write_config({"bot_token": "T", "chat_id": "42"})
        post.return_value = _Resp(200, {"ok": True})
        self.assertTrue(telegram_notify.send_telegram_message("hi"))
        args, kwargs = post.call_args
        self.assertIn("/botT/sendMessage", args[0])
        self.assertEqual(kwargs["json"]["chat_id"], "42")
        self.assertEqual(kwargs["json"]["text"], "hi")
        self.assertEqual(kwargs["json"]["parse_mode"], "HTML")

    @mock.patch("telegram_notify.requests.post")
    def test_html_parse_error_retries_plain(self, post):
        self._write_config({"bot_token": "T", "chat_id": "42"})
        post.side_effect = [
            _Resp(400, {"ok": False, "description": "can't parse entities"}),
            _Resp(200, {"ok": True}),
        ]
        self.assertTrue(telegram_notify.send_telegram_message("<b>bad</b>"))
        self.assertEqual(post.call_count, 2)
        second = post.call_args_list[1].kwargs["json"]
        self.assertNotIn("parse_mode", second)

    @mock.patch("telegram_notify.requests.post")
    def test_api_failure_returns_false(self, post):
        self._write_config({"bot_token": "T", "chat_id": "42"})
        post.return_value = _Resp(401, {"ok": False, "description": "Unauthorized"})
        self.assertFalse(telegram_notify.send_telegram_message("hi"))

    @mock.patch("telegram_notify.requests.post")
    def test_network_error_returns_false(self, post):
        self._write_config({"bot_token": "T", "chat_id": "42"})
        post.side_effect = ConnectionError("no network")
        self.assertFalse(telegram_notify.send_telegram_message("hi"))

    @mock.patch("telegram_notify.requests.post")
    def test_unconfigured_never_calls_api(self, post):
        telegram_notify.CONFIG_PATH = os.path.join(self.tmp, "missing.json")
        self.assertFalse(telegram_notify.send_telegram_message("hi"))
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
