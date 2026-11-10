"""
Telegram notification helper.

Sends messages through the Telegram Bot API. Credentials come from
``telegram_config.json`` (repo root) with environment-variable overrides:

    TELEGRAM_BOT_TOKEN   — bot token from @BotFather
    TELEGRAM_CHAT_ID     — your chat id (get it via the bot's getUpdates)

Example telegram_config.json:

    {
        "bot_token": "123456789:AA...",
        "chat_id": "123456789",
        "poll_interval_min": 30,
        "max_deal_age_days": 10
    }
"""

import json
import os
from typing import Optional

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "telegram_config.json")

API_BASE = "https://api.telegram.org/bot{token}/{method}"
SEND_TIMEOUT = 15


class TelegramConfigError(RuntimeError):
    """Raised when Telegram credentials are missing or malformed."""


def load_config() -> dict:
    """Load Telegram config: file first, then environment overrides."""
    cfg = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f) or {}
        except (ValueError, OSError):
            cfg = {}

    cfg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", cfg.get("bot_token") or "").strip()
    cfg["chat_id"] = str(os.environ.get("TELEGRAM_CHAT_ID", cfg.get("chat_id") or "")).strip()
    try:
        cfg["poll_interval_min"] = float(os.environ.get(
            "TELEGRAM_POLL_INTERVAL_MIN", cfg.get("poll_interval_min", 30)))
    except (ValueError, TypeError):
        cfg["poll_interval_min"] = 30.0
    try:
        cfg["max_deal_age_days"] = int(os.environ.get(
            "TELEGRAM_MAX_DEAL_AGE_DAYS", cfg.get("max_deal_age_days", 10)))
    except (ValueError, TypeError):
        cfg["max_deal_age_days"] = 10
    return cfg


def is_configured() -> bool:
    """True when a bot token + chat id are available."""
    cfg = load_config()
    return bool(cfg.get("bot_token") and cfg.get("chat_id"))


def send_telegram_message(text: str, parse_mode: str = "HTML",
                          chat_id: Optional[str] = None) -> bool:
    """Send one message via the Bot API. Returns True on success.

    Never raises — failures are logged to stderr so a bad alert can
    never take down the poller or the dashboard.
    """
    cfg = load_config()
    token = cfg.get("bot_token")
    target = (chat_id or cfg.get("chat_id") or "").strip()
    if not token or not target:
        print("[telegram] not configured — set bot_token/chat_id in "
              f"{CONFIG_PATH} or TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env",
              flush=True)
        return False

    url = API_BASE.format(token=token, method="sendMessage")
    payload = {
        "chat_id": target,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    try:
        r = requests.post(url, json=payload, timeout=SEND_TIMEOUT)
        if r.status_code == 200 and r.json().get("ok"):
            return True
        # 400 with parse error → retry as plain text so the alert still lands.
        if r.status_code == 400 and parse_mode:
            return send_telegram_message(text, parse_mode=None, chat_id=chat_id)
        print(f"[telegram] sendMessage failed: HTTP {r.status_code} "
              f"{(r.text or '')[:200]}", flush=True)
        return False
    except Exception as e:
        print(f"[telegram] sendMessage error: {e}", flush=True)
        return False
