"""
Institutional deal watcher → Telegram alerts.

Polls the same Trendlyne bulk/block-deal portfolios that the dashboard's
"Institutions" tab shows (Government of Singapore, ICICI Group, SBI Group,
HDFC Group, LIC of India, Vanguard, BlackRock) and sends a Telegram
message whenever one of those institutions shows a NEW buy or sell deal.

How it works
------------
- Each poll scrapes every institution page via stock_dashboard's
  `_scrape_trendlyne_deals` (same code path as the dashboard UI).
- Deals already seen are stored in ``telegram_seen_deals.json`` so
  restarts never re-alert history.
- On the FIRST successful scrape per institution, all existing rows are
  marked as seen silently (no alert flood from history).
- A deal is only alerted if its trade date is within ``max_deal_age_days``
  (default 10) — protects against Trendlyne backfilling old rows.

Configuration: see telegram_notify.py (telegram_config.json or env vars).

Usage
-----
    python institution_telegram_bot.py            # poll forever (30 min default)
    python institution_telegram_bot.py --once     # single poll cycle
    python institution_telegram_bot.py --test     # send a test Telegram message
    python institution_telegram_bot.py --interval 15

It also auto-starts as a background thread when the stock dashboard server
runs (see stock_dashboard.main), so no separate process is needed.
"""

import argparse
import html
import json
import os
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import telegram_notify
from telegram_notify import send_telegram_message
from stock_dashboard import _scrape_trendlyne_deals

# The 7 preset institutions shown in the dashboard's Institutions tab.
INSTITUTIONS = [
    ("Government of Singapore", "https://trendlyne.com/portfolio/bulk-block-deals/53902/government-of-singapore/"),
    ("ICICI Group", "https://trendlyne.com/portfolio/bulk-block-deals/597533/icici-group/"),
    ("SBI Group", "https://trendlyne.com/portfolio/bulk-block-deals/597531/sbi-group/"),
    ("HDFC Group", "https://trendlyne.com/portfolio/superstar-shareholders/597532/latest/hdfc-group/"),
    ("LIC of India", "https://trendlyne.com/portfolio/bulk-block-deals/53860/life-insurance-corporation-of-india/"),
    ("Vanguard", "https://trendlyne.com/portfolio/bulk-block-deals/53874/vanguard/"),
    ("BlackRock", "https://trendlyne.com/portfolio/bulk-block-deals/53896/blackrock/"),
]

STATE_PATH = os.path.join(HERE, "telegram_seen_deals.json")
SEEN_PRUNE_DAYS = 120  # drop keys older than this to bound state file growth
SEND_SPACING_SEC = 1.0


def _log(msg: str) -> None:
    print(f"[inst-telegram {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def _load_state() -> dict:
    state = {"keys": {}, "inits": {}}
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH) as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                state["keys"] = loaded.get("keys") or {}
                state["inits"] = loaded.get("inits") or {}
        except (ValueError, OSError):
            pass
    return state


def _save_state(state: dict) -> None:
    cutoff = time.time() - SEEN_PRUNE_DAYS * 86400
    state["keys"] = {k: ts for k, ts in state["keys"].items() if ts >= cutoff}
    tmp = STATE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE_PATH)
    except OSError as e:
        _log(f"could not save state: {e}")


def _deal_key(institution: str, deal: dict) -> str:
    return "|".join(str(x) for x in [
        institution,
        (deal.get("symbol") or "").upper(),
        deal.get("iso_date") or deal.get("date") or "",
        (deal.get("buySell") or "").upper(),
        deal.get("qty"),
        deal.get("watp"),
        (deal.get("client") or deal.get("clientName") or "").upper(),
    ])


def _deal_is_fresh(deal: dict, max_age_days: int) -> bool:
    """Alert only recent deals so Trendlyne backfills of old rows don't spam."""
    iso = deal.get("iso_date") or ""
    if not iso:
        return True  # unknown date → trust the dedup key
    try:
        dt = datetime.strptime(iso, "%Y-%m-%d")
    except ValueError:
        return True
    return dt >= datetime.now() - timedelta(days=max_age_days)


def _fmt_inr(val: float) -> str:
    if not val or val != val:  # None / NaN guard
        return "₹0"
    if abs(val) >= 1e7:
        return f"₹{val / 1e7:,.2f} Cr"
    if abs(val) >= 1e5:
        return f"₹{val / 1e5:,.2f} L"
    return f"₹{val:,.0f}"


def _deal_message(institution: str, deal: dict) -> str:
    side = (deal.get("buySell") or "").upper()
    emoji = "🟢 BUY" if side == "BUY" else "🔴 SELL"
    symbol = html.escape((deal.get("symbol") or "").upper())
    name = html.escape(deal.get("name") or "")
    client = html.escape((deal.get("client") or deal.get("clientName") or "").strip())
    qty = deal.get("qty") or 0
    price = deal.get("watp") or 0
    val = deal.get("val") if deal.get("val") else (qty or 0) * (price or 0)

    lines = [
        f"{emoji} — <b>{html.escape(institution)}</b>",
        "",
        f"📈 <b>{symbol}</b>" + (f" ({name})" if name else ""),
        f"💰 Qty: {qty:,.0f} @ ₹{price:,.2f}" if price else f"💰 Qty: {qty:,.0f}",
        f"💵 Value: {_fmt_inr(val)}",
    ]
    if deal.get("deal_type"):
        lines.append(f"🏷 {html.escape(str(deal['deal_type']))} Deal")
    if client and client.upper() != institution.upper():
        lines.append(f"🏦 Client: {client}")
    if deal.get("date"):
        lines.append(f"📅 {html.escape(str(deal['date']))}")
    lines.append(f"🔗 trendlyne.com · {symbol}")
    return "\n".join(lines)


def poll_once(max_age_days: Optional[int] = None, quiet: bool = False) -> int:
    """Run one polling cycle across all institutions. Returns alert count."""
    cfg = telegram_notify.load_config()
    max_age = max_age_days if max_age_days is not None else cfg["max_deal_age_days"]
    state = _load_state()
    alerts_sent = 0

    for preset_name, url in INSTITUTIONS:
        try:
            data = _scrape_trendlyne_deals(url)
        except Exception as e:
            _log(f"scrape failed for {preset_name}: {e}")
            continue

        if not data or data.get("error"):
            _log(f"scrape error for {preset_name}: {(data or {}).get('error', 'no data')}")
            continue

        institution = data.get("institution") or preset_name
        deals = data.get("deals") or []
        initialized = state["inits"].get(preset_name)

        new_deals = []
        for d in deals:
            key = _deal_key(institution, d)
            if key in state["keys"]:
                continue
            state["keys"][key] = time.time()
            if initialized and _deal_is_fresh(d, max_age):
                new_deals.append(d)

        if not initialized:
            state["inits"][preset_name] = True
            _log(f"initialized {institution}: {len(deals)} existing deals marked as seen")
        elif new_deals:
            _log(f"{len(new_deals)} new deal(s) for {institution}")
            for d in new_deals:
                if send_telegram_message(_deal_message(institution, d)):
                    alerts_sent += 1
                time.sleep(SEND_SPACING_SEC)
        _save_state(state)

    if not quiet:
        _log(f"poll done — {alerts_sent} alert(s) sent")
    return alerts_sent


def run_forever(interval_min: Optional[float] = None) -> None:
    """Poll forever. Called either standalone or as a dashboard daemon thread."""
    cfg = telegram_notify.load_config()
    interval = (interval_min if interval_min is not None else cfg["poll_interval_min"]) * 60

    if not telegram_notify.is_configured():
        _log("Telegram not configured — watcher disabled "
             "(set bot_token/chat_id in telegram_config.json)")
        return

    send_telegram_message(
        "🤖 <b>Institution Deal Watcher started</b>\n\n"
        "Watching for new BUY/SELL bulk &amp; block deals from:\n"
        + "\n".join("• " + html.escape(n) for n, _ in INSTITUTIONS)
        + f"\n\n⏱ Polling every {interval / 60:.0f} min"
    )
    _log(f"watcher running — {len(INSTITUTIONS)} institutions, "
         f"every {interval / 60:.0f} min")

    while True:
        try:
            poll_once()
        except Exception as e:
            _log(f"poll cycle error: {e}")
        time.sleep(interval)


def start_watcher() -> bool:
    """Start the watcher as a daemon thread. Returns True if it launched."""
    if not telegram_notify.is_configured():
        return False
    threading.Thread(target=run_forever, daemon=True, name="telegram-inst-watcher").start()
    return True


def main():
    parser = argparse.ArgumentParser(description="Institution deals → Telegram bot")
    parser.add_argument("--once", action="store_true", help="run a single poll cycle and exit")
    parser.add_argument("--test", action="store_true", help="send a test Telegram message and exit")
    parser.add_argument("--interval", type=float, default=None,
                        help="poll interval in minutes (overrides config)")
    parser.add_argument("--max-age-days", type=int, default=None,
                        help="only alert deals newer than this many days")
    args = parser.parse_args()

    if args.test:
        ok = send_telegram_message("✅ <b>Test message</b> — institution deal watcher is configured correctly.")
        print("test message sent" if ok else "test message FAILED — check config/logs above")
        sys.exit(0 if ok else 1)

    if not telegram_notify.is_configured():
        print("Telegram not configured. Create telegram_config.json with bot_token "
              "and chat_id (or set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars).")
        sys.exit(1)

    if args.once:
        sys.exit(0 if poll_once(max_age_days=args.max_age_days) >= 0 else 1)

    if args.interval is not None:
        run_forever(interval_min=args.interval)
    else:
        run_forever()


if __name__ == "__main__":
    main()
