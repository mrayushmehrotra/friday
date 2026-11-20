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
- BlackRock has no standalone Trendlyne portfolio page, so its deals are
  matched by client name in Trendlyne's all-deals feed instead.
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
# Format: (display label, Trendlyne URL, expected-name keywords)
# Trendlyne portfolio IDs are normally stable, but they HAVE been silently
# re-pointed to other entities before (the old LIC/Vanguard/BlackRock URLs
# recently started serving unrelated portfolios), so the scraped page title
# is verified against `keywords` before any alert is sent.
INSTITUTIONS = [
    ("Government of Singapore", "https://trendlyne.com/portfolio/bulk-block-deals/53902/government-of-singapore/", ("singapore",)),
    ("ICICI Group", "https://trendlyne.com/portfolio/bulk-block-deals/597533/icici-group/", ("icici",)),
    ("SBI Group", "https://trendlyne.com/portfolio/bulk-block-deals/597531/sbi-group/", ("sbi",)),
    ("HDFC Group", "https://trendlyne.com/portfolio/bulk-block-deals/597532/hdfc-group/", ("hdfc",)),
    ("LIC of India", "https://trendlyne.com/portfolio/bulk-block-deals/53950/life-insurance-corporation-of-india/", ("life insurance", "lic of india")),
    ("Vanguard", "https://trendlyne.com/portfolio/bulk-block-deals/54044/vanguard-fund", ("vanguard",)),
]

# Trendlyne currently has no standalone institution portfolio page for
# BlackRock (the old URL now serves a different entity), so BlackRock deals
# are caught by scanning the all-deals feed for matching client names
# (e.g. "BLACKROCK INTL LTD", "BLACKROCK GLOBAL FUNDS").
CLIENT_WATCHES = [
    ("BlackRock", ("blackrock",)),
]
ALL_DEALS_URL = "https://trendlyne.com/portfolio/bulk-block-deals/all/all"

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
    lines.append('🔗 <a href="https://trendlyne.com/portfolio/bulk-block-deals/all/all">'
                 'Trendlyne bulk/block deals</a>')
    return "\n".join(lines)


_MISMATCH_WARNED = set()


def _matches_keywords(scraped_name: str, keywords: tuple) -> bool:
    low = (scraped_name or "").lower()
    return any(k in low for k in keywords)


def _warn_mismatch(label: str, scraped_name: str) -> None:
    """Trendlyne re-pointed a preset URL to a different entity — warn once."""
    _log(f"WARNING: {label} URL now resolves to '{scraped_name}' — "
         "skipping alerts for it. Update INSTITUTIONS in institution_telegram_bot.py")
    if label in _MISMATCH_WARNED:
        return
    _MISMATCH_WARNED.add(label)
    send_telegram_message(
        f"⚠️ <b>Institution watcher config issue</b>\n\n"
        f"The Trendlyne page for <b>{html.escape(label)}</b> now shows "
        f"<i>{html.escape(scraped_name)}</i>.\n"
        f"Skipping it — its preset URL needs updating in "
        f"<code>institution_telegram_bot.py</code>."
    )


def _collect_new_deals(label, deals, state, max_age, initialized, pending):
    """Dedup-mark deals and append fresh unseen ones to `pending`."""
    for d in deals:
        key = _deal_key(label, d)
        if key in state["keys"]:
            continue
        state["keys"][key] = time.time()
        if initialized and _deal_is_fresh(d, max_age):
            pending.append((label, d))


def poll_once(max_age_days: Optional[int] = None, quiet: bool = False) -> int:
    """Run one polling cycle across all institutions. Returns alert count."""
    cfg = telegram_notify.load_config()
    max_age = max_age_days if max_age_days is not None else cfg["max_deal_age_days"]
    state = _load_state()
    pending = []

    # 1. Institutions with a dedicated Trendlyne portfolio page.
    for label, url, keywords in INSTITUTIONS:
        try:
            data = _scrape_trendlyne_deals(url)
        except Exception as e:
            _log(f"scrape failed for {label}: {e}")
            continue

        if not data or data.get("error"):
            _log(f"scrape error for {label}: {(data or {}).get('error', 'no data')}")
            continue

        scraped_name = data.get("institution") or ""
        if scraped_name and not _matches_keywords(scraped_name, keywords):
            _warn_mismatch(label, scraped_name)
            continue

        deals = data.get("deals") or []
        initialized = state["inits"].get(label)
        _collect_new_deals(label, deals, state, max_age, initialized, pending)
        if not initialized:
            state["inits"][label] = True
            _log(f"initialized {label}: {len(deals)} existing deals marked as seen")
        _save_state(state)

    # 2. Institutions without a page — match client names in the all-deals feed.
    if CLIENT_WATCHES:
        try:
            feed = _scrape_trendlyne_deals(ALL_DEALS_URL)
        except Exception as e:
            feed = {"error": str(e)}
        if not feed or feed.get("error"):
            _log(f"all-deals feed error: {(feed or {}).get('error', 'no data')}")
        else:
            all_deals = feed.get("deals") or []
            for label, needles in CLIENT_WATCHES:
                matched = [
                    d for d in all_deals
                    if any(n in (d.get("client") or d.get("clientName") or "").lower()
                           for n in needles)
                ]
                initialized = state["inits"].get(label)
                _collect_new_deals(label, matched, state, max_age, initialized, pending)
                if not initialized:
                    state["inits"][label] = True
                    _log(f"initialized {label}: {len(matched)} existing deal(s) marked as seen")
            _save_state(state)

    # 3. Send alerts.
    alerts_sent = 0
    for label, d in pending:
        _log(f"new deal — {label}: {d.get('buySell')} {d.get('symbol')} "
             f"({d.get('qty')} @ {d.get('watp')})")
        if send_telegram_message(_deal_message(label, d)):
            alerts_sent += 1
        time.sleep(SEND_SPACING_SEC)

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

    watched = [n for n, _, _ in INSTITUTIONS] + [n for n, _ in CLIENT_WATCHES]
    send_telegram_message(
        "🤖 <b>Institution Deal Watcher started</b>\n\n"
        "Watching for new BUY/SELL bulk &amp; block deals from:\n"
        + "\n".join("• " + html.escape(n) for n in watched)
        + f"\n\n⏱ Polling every {interval / 60:.0f} min"
    )
    _log(f"watcher running — {len(watched)} institutions, "
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
    parser.add_argument("--status", action="store_true", help="show config/state summary and exit")
    parser.add_argument("--interval", type=float, default=None,
                        help="poll interval in minutes (overrides config)")
    parser.add_argument("--max-age-days", type=int, default=None,
                        help="only alert deals newer than this many days")
    args = parser.parse_args()

    if args.status:
        cfg = telegram_notify.load_config()
        state = _load_state()
        print(f"configured:        {telegram_notify.is_configured()}")
        print(f"poll interval:     {cfg['poll_interval_min']:g} min")
        print(f"max deal age:      {cfg['max_deal_age_days']} day(s)")
        print(f"institutions:      {', '.join(n for n, _, _ in INSTITUTIONS)}")
        print(f"client watches:    {', '.join(n for n, _ in CLIENT_WATCHES) or '-'}")
        print(f"initialized:       {', '.join(sorted(state['inits'])) or '-'}")
        print(f"seen deal keys:    {len(state['keys'])}")
        print(f"state file:        {STATE_PATH}")
        sys.exit(0)

    if args.test:
        ok = send_telegram_message("✅ <b>Test message</b> — institution deal watcher is configured correctly.")
        print("test message sent" if ok else "test message FAILED — check config/logs above")
        sys.exit(0 if ok else 1)

    if not telegram_notify.is_configured():
        print("Telegram not configured. Create telegram_config.json with bot_token "
              "and chat_id (or set TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID env vars).")
        sys.exit(1)

    if args.once:
        poll_once(max_age_days=args.max_age_days)
        sys.exit(0)

    if args.interval is not None:
        run_forever(interval_min=args.interval)
    else:
        run_forever()


if __name__ == "__main__":
    main()
