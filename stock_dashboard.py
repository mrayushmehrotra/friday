import argparse
import json
import os
import sys
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import datetime
import re
import urllib.request
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup

def _fetch_headlines(max_items: int = 8) -> list[str]:
    try:
        url = (
            "https://news.google.com/rss/search?"
            "q=stock+market+nifty+sensex+india+finance&hl=en-IN&gl=IN&ceid=IN:en"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read().decode())
        items: list[str] = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                items.append(title_el.text)
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []

from stock_tools import get_stock_data, get_stock_news, _resolve_ticker
from concurrent.futures import ThreadPoolExecutor, as_completed, wait

import requests as _requests

NIFTY_50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
    "BHARTIARTL", "SBIN", "ITC", "LT", "KOTAKBANK", "BAJFINANCE",
    "WIPRO", "AXISBANK", "ADANIENT", "MARUTI", "TITAN", "ASIANPAINT",
    "HCLTECH", "ULTRACEMCO", "NTPC", "ONGC", "POWERGRID", "SUNPHARMA",
    "BAJAJFINSV",     "JSWSTEEL", "HINDALCO", "TATASTEEL",
    "ADANIPORTS", "GRASIM", "BRITANNIA", "DIVISLAB", "DRREDDY",
    "CIPLA", "APOLLOHOSP", "NESTLEIND", "COALINDIA", "BPCL",
    "SBILIFE", "EICHERMOT", "M&M", "HDFCLIFE", "TATACONSUM",
    "BAJAJ-AUTO", "INDUSINDBK", "HEROMOTOCO", "TRENT", "BEL",
]

_CSV_PATH = os.path.join(HERE, "assets", "equity_stocks.csv")
ALL_EQ_SYMBOLS = []
if os.path.exists(_CSV_PATH):
    try:
        import csv
        with open(_CSV_PATH) as f:
            for row in csv.DictReader(f):
                s = row.get("SYMBOL", "").strip()
                series = row.get("SERIES", row.get(" SERIES", "")).strip()
                if s and series == "EQ":
                    ALL_EQ_SYMBOLS.append(s)
    except Exception:
        pass
if not ALL_EQ_SYMBOLS:
    ALL_EQ_SYMBOLS = NIFTY_50[:]
from backtest_tools import (
    run as run_backtest,
    compare_strategies,
    stock_of_the_day,
    STRATEGY_MAP,
    example_strategies,
    format_result_json,
)

PORT = 9090

INDIAN_INDICES = {"^NSEI", "^BSESN", "^NSEBANK"}


def _safe(val, default=0.0):
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return default
    return val


from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
_SENTIMENT = SentimentIntensityAnalyzer()

_POS_WORDS = {"surge", "jump", "rise", "gain", "bull", "bullish", "profit", "growth",
             "buy", "upgrade", "positive", "outperform", "beat", "strong", "record"}
_NEG_WORDS = {"fall", "drop", "decline", "bear", "bearish", "loss", "sell", "downgrade",
             "negative", "underperform", "miss", "weak", "cut", "slump", "crash"}


def _keyword_sentiment(text: str) -> float:
    text_lower = text.lower()
    pos = sum(1 for w in _POS_WORDS if w in text_lower)
    neg = sum(1 for w in _NEG_WORDS if w in text_lower)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


def _sentiment_score(ticker: str) -> float:
    try:
        news = get_stock_news(ticker + ".NS", 5)
        if not news:
            return 0.0
        scores = []
        for article in news:
            title = article.get("title", "")
            try:
                vs = _SENTIMENT.polarity_scores(title)
                scores.append(vs["compound"])
            except Exception:
                scores.append(_keyword_sentiment(title))
        return float(np.mean(scores)) if scores else 0.0
    except Exception:
        return 0.0


def _ema_score(close: pd.Series) -> float:
    ema9 = close.ewm(span=9).mean().iloc[-1]
    ema21 = close.ewm(span=21).mean().iloc[-1]
    ema50 = close.ewm(span=50).mean().iloc[-1]
    if pd.isna(ema9) or pd.isna(ema21) or pd.isna(ema50):
        return 0.5
    if ema9 > ema21 > ema50:
        return 1.0
    if ema9 > ema21 and ema21 > ema50 * 0.98:
        return 0.8
    if ema9 < ema21 < ema50:
        return 0.0
    if ema9 < ema21 and ema21 < ema50 * 1.02:
        return 0.2
    return 0.5


def _vwap_distance(close: pd.Series, high: pd.Series, low: pd.Series, volume: pd.Series) -> tuple:
    typical = (high + low + close) / 3
    vwap_series = (typical * volume).cumsum() / volume.cumsum()
    vwap_today = float(_safe(vwap_series.iloc[-1], typical.iloc[-1]))
    price = float(close.iloc[-1])
    dist = (price / vwap_today - 1) * 100
    return dist, vwap_today


def _run_scan(scan_fn, top_n, timeout_sec=60, tickers=None):
    picks = []
    if tickers is None:
        tickers = NIFTY_50
    workers = min(30, len(tickers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(scan_fn, t): t for t in tickers}
        done, _ = wait(futures, timeout=timeout_sec)
        for f in done:
            r = f.result()
            if r:
                picks.append(r)
    picks.sort(key=lambda x: x.get("score", 0) or 0, reverse=True)
    return picks[:top_n]


_NIFTY_DATA = None


def _get_nifty_ret_5d() -> float:
    global _NIFTY_DATA
    if _NIFTY_DATA is None:
        _NIFTY_DATA = yf.download("^NSEI", period="1mo", progress=False)
    if _NIFTY_DATA.empty or len(_NIFTY_DATA) < 6:
        return 0.0
    if isinstance(_NIFTY_DATA.columns, pd.MultiIndex):
        _NIFTY_DATA.columns = _NIFTY_DATA.columns.get_level_values(0)
    nc = _NIFTY_DATA["Close"]
    return (float(nc.iloc[-1]) / float(nc.iloc[-6]) - 1) * 100


def _scan_intraday(t):
    try:
        sd = get_stock_data(t + ".NS")
        if not sd or sd.get("price") is None:
            return None
        price = sd["price"]
        gap_pct = ((sd.get("open") or price) / sd["prev_close"] - 1) * 100

        df = yf.download(t + ".NS", period="3mo", progress=False)
        if df.empty or len(df) < 20:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        vol_14 = volume.rolling(14).mean().iloc[-1]
        rvol = float(volume.iloc[-1] / vol_14) if vol_14 > 0 else 1.0

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50

        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(_safe(tr.rolling(14).mean().iloc[-1]))
        atr_pct = (atr / float(close.iloc[-1])) * 100 if float(close.iloc[-1]) > 0 else 0

        ema_align = _ema_score(close)
        vwap_dist, vwap = _vwap_distance(close, high, low, volume)

        nifty_ret = _get_nifty_ret_5d()
        stock_5d_ret = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0
        rel_strength = stock_5d_ret - nifty_ret

        sent = _sentiment_score(t)

        rvol_score = _safe(min(rvol / 3, 1))
        atr_score = _safe(min(atr_pct / 4, 1))
        gap_score = _safe(min(abs(gap_pct) / 3, 1))
        vwap_near = _safe(1 - min(abs(vwap_dist) / 2, 1))
        rsi_score = _safe(1 - abs(current_rsi - 50) / 50)
        rs_score = _safe(min(max((rel_strength + 5) / 10, 0), 1))
        sent_score = _safe((sent + 1) / 2)

        score = round(
            rvol_score * 10 +
            atr_score * 10 +
            gap_score * 15 +
            ema_align * 20 +
            vwap_near * 15 +
            rsi_score * 10 +
            rs_score * 10 +
            sent_score * 10,
            1,
        )

        return {
            "ticker": t,
            "price": round(price, 2),
            "gap_pct": round(gap_pct, 2),
            "rvol": round(rvol, 2),
            "atr_pct": round(atr_pct, 2),
            "rsi": round(_safe(current_rsi, 50), 1),
            "ema": round(ema_align, 2),
            "vwap_dist": round(vwap_dist, 2),
            "rel_str": round(rel_strength, 2),
            "sent": round(sent, 2),
            "score": score if not (isinstance(score, float) and np.isnan(score)) else 0,
            "change_pct": _safe(sd.get("change_pct")),
        }
    except Exception:
        return None


def _intraday_picks(top_n=15):
    _get_nifty_ret_5d()
    tickers = ALL_EQ_SYMBOLS[:500]
    return _run_scan(_scan_intraday, top_n, timeout_sec=120, tickers=tickers)


def _midterm_picks(strategy, start, movement_min, movement_max, top_n=10):
    return stock_of_the_day(
        start=start, strategy=strategy,
        movement_min=movement_min, movement_max=movement_max,
    )


def _scan_swing(t):
    try:
        sd = get_stock_data(t + ".NS")
        if not sd or sd.get("price") is None or sd["price"] < 20:
            return None
        price = sd["price"]
        df = yf.download(t + ".NS", period="6mo", progress=False)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        avg_6mo = float(close.mean())
        gain_pct = (price / avg_6mo - 1) * 100

        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(_safe(tr.rolling(14).mean().iloc[-1]))
        atr_pct = (atr / float(close.iloc[-1])) * 100 if float(close.iloc[-1]) > 0 else 0

        vol_ratio = float(volume.iloc[-1]) / float(_safe(volume.tail(20).mean(), 1))

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        current_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else 50

        dist_from_ideal = abs(gain_pct - 35)
        swing_score = max(0, 100 - dist_from_ideal * 2.5)
        vol_score = _safe(min(vol_ratio / 2, 1)) * 10
        atr_bonus = _safe(min(atr_pct / 3, 1)) * 10
        rsi_ok = 10 if 30 <= current_rsi <= 80 else 0

        score = round(swing_score + vol_score + atr_bonus + rsi_ok, 1)

        return {
            "ticker": t,
            "price": round(price, 2),
            "avg_6mo": round(avg_6mo, 2),
            "gain_pct": round(gain_pct, 2),
            "atr_pct": round(atr_pct, 2),
            "rsi": round(current_rsi, 1),
            "vol_ratio": round(vol_ratio, 2),
            "score": score if not (isinstance(score, float) and np.isnan(score)) else 0,
            "change_pct": _safe(sd.get("change_pct")),
        }
    except Exception:
        return None


def _swing_picks(top_n=15):
    return _run_scan(_scan_swing, top_n, timeout_sec=120, tickers=NIFTY_50)


_NSE_SESSION = threading.local()


def _get_nse_session():
    if not hasattr(_NSE_SESSION, "session") or _NSE_SESSION.session is None:
        s = _requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        })
        s.get("https://www.nseindia.com/", timeout=15)
        _NSE_SESSION.session = s
    return _NSE_SESSION.session


def _aggregate_deals(deals):
    by_sym = {}
    for d in deals:
        sym = (d.get("symbol") or "").strip().upper()
        if not sym:
            continue
        if sym not in by_sym:
            by_sym[sym] = {
                "symbol": sym,
                "name": d.get("name", ""),
                "category": d.get("category", ""),
                "buy_count": 0,
                "sell_count": 0,
                "buy_qty": 0.0,
                "sell_qty": 0.0,
                "buy_val": 0.0,
                "sell_val": 0.0,
                "clients": {},
                "deals": [],
            }
        bs = (d.get("buySell") or "").strip().upper()
        try:
            qty = float(d.get("qty", 0))
        except (ValueError, TypeError):
            qty = 0.0
        try:
            watp = float(d.get("watp", 0))
        except (ValueError, TypeError):
            watp = 0.0
        val = qty * watp

        if bs == "BUY":
            by_sym[sym]["buy_count"] += 1
            by_sym[sym]["buy_qty"] += qty
            by_sym[sym]["buy_val"] += val
        elif bs == "SELL":
            by_sym[sym]["sell_count"] += 1
            by_sym[sym]["sell_qty"] += qty
            by_sym[sym]["sell_val"] += val

        client = (d.get("clientName") or "Unknown").strip()
        if client not in by_sym[sym]["clients"]:
            by_sym[sym]["clients"][client] = {"client": client, "buys": [], "sells": []}

        deal_entry = {
            "client": client,
            "buySell": bs,
            "qty": qty,
            "watp": watp,
            "val": val,
            "remarks": d.get("remarks", ""),
            "date": d.get("date", ""),
        }
        if bs == "BUY":
            by_sym[sym]["clients"][client]["buys"].append(deal_entry)
        elif bs == "SELL":
            by_sym[sym]["clients"][client]["sells"].append(deal_entry)

        by_sym[sym]["deals"].append(deal_entry)

    out = []
    for sym, item in by_sym.items():
        item["net_val"] = item["buy_val"] - item["sell_val"]
        item["net_qty"] = item["buy_qty"] - item["sell_qty"]
        item["total_val"] = item["buy_val"] + item["sell_val"]
        item["total_qty"] = item["buy_qty"] + item["sell_qty"]
        item["client_list"] = list(item["clients"].values())
        out.append(item)
    out.sort(key=lambda x: x["total_val"], reverse=True)
    return out


def _fetch_large_deals():
    try:
        ses = _get_nse_session()
        r = ses.get(
            "https://www.nseindia.com/api/snapshot-capital-market-largedeal",
            timeout=15,
            headers={"Referer": "https://www.nseindia.com/market-data/large-deals"},
        )
        if r.status_code != 200:
            return None
        data = r.json()
        out = {"as_on_date": data.get("as_on_date", "")}
        for key, label in [("BULK_DEALS_DATA", "Bulk Deals"), ("BLOCK_DEALS_DATA", "Block Deals")]:
            deals = data.get(key, [])
            for d in deals:
                d["category"] = label
            out[key] = deals
            out["GROUPED_" + key] = _aggregate_deals(deals)
        all_symbols = list({d["symbol"] for k in ("BULK_DEALS_DATA", "BLOCK_DEALS_DATA") for d in data.get(k, [])})
        out["symbols"] = all_symbols
        return out
    except Exception:
        return None


def _scrape_trendlyne_deals(url: str = None):
    if not url or not url.strip():
        url = "https://trendlyne.com/portfolio/bulk-block-deals/53902/government-of-singapore/"
    url = url.strip()
    original_url = url

    # Normalize superstar-shareholders URL to bulk-block-deals URL if provided
    if "/portfolio/superstar-shareholders/" in url:
        m = re.search(r"/portfolio/superstar-shareholders/(\d+)/(?:latest/)?([^/]+)/?", url)
        if m:
            inst_id, slug = m.group(1), m.group(2)
            url = f"https://trendlyne.com/portfolio/bulk-block-deals/{inst_id}/{slug}/"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        r = _requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return {"error": f"Trendlyne returned HTTP status {r.status_code}"}

        soup = BeautifulSoup(r.text, "html.parser")
        table = soup.find("table", id="bbdealTable")
        if not table:
            # Check if there is a link to the bulk & block deals table on this page
            bb_link = soup.find("a", href=re.compile(r"/portfolio/bulk-block-deals/\d+/"))
            if bb_link and bb_link.get("href"):
                next_url = bb_link["href"]
                if not next_url.startswith("http"):
                    next_url = "https://trendlyne.com" + next_url
                res = _scrape_trendlyne_deals(next_url)
                if isinstance(res, dict) and not res.get("error"):
                    res["original_url"] = original_url
                return res
            return {"error": "Could not find bulk/block deals table on the provided Trendlyne page"}

        h1 = soup.find("h1")
        raw_name = h1.text.strip() if h1 else ""
        title_text = soup.title.text.strip() if soup.title else ""
        if not raw_name or "Latest Bulk and Block Deals" in raw_name:
            if "Bulk and Block Deals" in title_text:
                raw_name = title_text
        inst_name = re.sub(r"['’]s Bulk and Block Deals.*", "", raw_name, flags=re.IGNORECASE).strip()
        if not inst_name or inst_name == raw_name or "Latest Bulk and Block Deals" in inst_name:
            slug_match = re.search(r"/bulk-block-deals/\d+/([^/]+)/?", url)
            if slug_match:
                inst_name = slug_match.group(1).replace("-", " ").title()
            else:
                inst_name = "Institution"

        tbody = table.find("tbody")
        if not tbody:
            return {"error": "Deals table is empty"}

        now = datetime.datetime.now()
        cur_month_str = now.strftime("%b %Y")

        deals = []
        for row in tbody.find_all("tr"):
            tds = row.find_all("td")
            if len(tds) < 8:
                continue
            stock_a = tds[0].find("a")
            stock_name = stock_a.text.strip() if stock_a else ""
            stock_href = stock_a.get("href", "") if stock_a else ""
            ticker_match = re.search(r"/equity/bulk-block-deals/([^/]+)/", stock_href)
            ticker = ticker_match.group(1).upper() if ticker_match else stock_name.upper()

            client = tds[1].text.strip()
            exchange = tds[2].text.strip()
            deal_type = tds[3].text.strip()
            action_raw = tds[4].text.strip()
            action = "BUY" if "purchase" in action_raw.lower() or "buy" in action_raw.lower() else "SELL"

            date_str = tds[5].text.strip()
            iso_date = ""
            month_year = ""
            try:
                dt = datetime.datetime.strptime(date_str, "%d %b %Y")
                iso_date = dt.strftime("%Y-%m-%d")
                month_year = dt.strftime("%b %Y")
            except Exception:
                month_year = " ".join(date_str.split()[1:]) if len(date_str.split()) >= 3 else ""

            price_str = tds[6].text.replace(",", "").replace("₹", "").strip()
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                price = 0.0

            qty_str = tds[7].text.replace(",", "").strip()
            try:
                qty = float(qty_str)
            except (ValueError, TypeError):
                qty = 0.0

            pct_str = tds[8].text.strip() if len(tds) > 8 else ""
            val = qty * price

            deals.append({
                "symbol": ticker,
                "name": stock_name,
                "client": client,
                "clientName": client,
                "exchange": exchange,
                "deal_type": deal_type,
                "buySell": action,
                "date": date_str,
                "iso_date": iso_date,
                "month_year": month_year,
                "watp": price,
                "qty": qty,
                "val": val,
                "pct": pct_str,
            })

        seen_months = []
        for d in deals:
            m = d.get("month_year")
            if m and m not in seen_months:
                seen_months.append(m)

        latest_month = seen_months[0] if seen_months else ""

        block_deals = [d for d in deals if (d.get("deal_type") or "").strip().lower() == "block"]
        bulk_deals = [d for d in deals if (d.get("deal_type") or "").strip().lower() == "bulk"]

        seen_block_months = []
        for d in block_deals:
            m = d.get("month_year")
            if m and m not in seen_block_months:
                seen_block_months.append(m)
        latest_block_month = seen_block_months[0] if seen_block_months else latest_month

        cur_month_block = [d for d in block_deals if d.get("month_year") == cur_month_str]
        latest_month_block = [d for d in block_deals if d.get("month_year") == latest_block_month]

        return {
            "institution": inst_name,
            "url": url,
            "original_url": original_url,
            "current_month": cur_month_str,
            "latest_deal_month": latest_month,
            "latest_block_month": latest_block_month,
            "available_months": seen_months,
            "total_deals_count": len(deals),
            "total_block_count": len(block_deals),
            "total_bulk_count": len(bulk_deals),
            "deals": deals,
            "block_deals": block_deals,
            "bulk_deals": bulk_deals,
            "current_month_block_deals": cur_month_block,
            "grouped_current_month_block": _aggregate_deals(cur_month_block),
            "grouped_latest_month_block": _aggregate_deals(latest_month_block),
            "grouped_block": _aggregate_deals(block_deals),
            "grouped_bulk": _aggregate_deals(bulk_deals),
            "grouped_all": _aggregate_deals(deals),
        }
    except Exception as e:
        return {"error": f"Scraping failed: {str(e)}"}


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/quote":
            self._handle_quote(params)
        elif path == "/api/news":
            self._handle_news(params)
        elif path == "/api/backtest":
            self._handle_backtest(params)
        elif path == "/api/compare":
            self._handle_compare(params)
        elif path == "/api/stock-of-day":
            self._handle_stock_of_day(params)
        elif path == "/api/strategies":
            self._send_json(example_strategies())
        elif path == "/api/bullish-news":
            self._handle_bullish_news()
        elif path == "/api/large-deals":
            self._handle_large_deals()
        elif path == "/api/market-overview":
            self._handle_market_overview()
        elif path == "/api/institutional-deals":
            self._handle_institutional_deals(params)
        elif path == "/":
            self._serve_file("stock_dashboard.html")
        else:
            super().do_GET()

    def _serve_file(self, filename):
        filepath = os.path.join(HERE, filename)
        if not os.path.exists(filepath):
            self.send_error(404)
            return
        ext = filename.split(".")[-1]
        types = {"html": "text/html", "css": "text/css", "js": "application/javascript"}
        self.send_response(200)
        self.send_header("Content-Type", types.get(ext, "text/plain"))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())

    def _get_param(self, params, key, default=None):
        vals = params.get(key, [])
        return vals[0] if vals else default

    def _get_float(self, params, key, default=None):
        v = self._get_param(params, key)
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def _handle_quote(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        data = get_stock_data(resolved)
        if not data:
            self._send_json({"error": f"No data for {ticker}"}, 404)
            return
        self._send_json(data)

    def _handle_news(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        count = int(self._get_param(params, "count", "10"))
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        news = get_stock_news(resolved, count)
        self._send_json({"ticker": ticker, "resolved": resolved, "news": news})

    def _handle_backtest(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        strategy = self._get_param(params, "strategy", "ma_crossover")
        start = self._get_param(params, "start", "1y")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        if strategy not in STRATEGY_MAP:
            self._send_json(
                {"error": f"Unknown strategy. Choose: {', '.join(STRATEGY_MAP.keys())}"}, 400
            )
            return

        try:
            resolved = _resolve_ticker(ticker)
            result = run_backtest(
                ticker=resolved, strategy=strategy, start=start,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
            )
            data = format_result_json(result)
            data["strategy"] = strategy
            data["ticker"] = ticker
            data["resolved"] = resolved
            self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_compare(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        start = self._get_param(params, "start", "1y")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return

        try:
            resolved = _resolve_ticker(ticker)
            results = compare_strategies(
                ticker=resolved, start=start,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
            )
            self._send_json({"ticker": ticker, "resolved": resolved, "strategies": results})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_stock_of_day(self, params):
        mode = self._get_param(params, "mode", "midterm")

        try:
            if mode == "intraday":
                picks = _intraday_picks()
                self._send_json({"mode": "intraday", "picks": picks})
            elif mode == "swing":
                picks = _swing_picks()
                self._send_json({"mode": "swing", "picks": picks})
            elif mode == "options":
                self._send_json({"mode": "options", "picks": [], "info": "Deprecated — use swing mode instead"})
            else:
                strategy = self._get_param(params, "strategy", "sma_50_trend")
                start = self._get_param(params, "start", "1y")
                movement_min = self._get_float(params, "movement_min", 10)
                movement_max = self._get_float(params, "movement_max", 30)
                top = stock_of_the_day(
                    start=start, strategy=strategy,
                    movement_min=movement_min, movement_max=movement_max,
                )
                self._send_json({"mode": "midterm", "strategy": strategy, "movement_filter": f"{movement_min}%-{movement_max}%", "picks": top})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_bullish_news(self):
        try:
            gainers = []
            with ThreadPoolExecutor(max_workers=10) as pool:
                futures = {pool.submit(get_stock_data, t + ".NS"): t for t in NIFTY_50}
                for fut in as_completed(futures):
                    t = futures[fut]
                    try:
                        d = fut.result()
                        if d and d.get("change_pct") is not None and d["change_pct"] > 0:
                            gainers.append((t, d["change_pct"], d["price"]))
                    except Exception:
                        pass
            gainers.sort(key=lambda x: x[1], reverse=True)
            top = gainers[:8]
            all_news = []
            for t, chg, price in top:
                try:
                    news = get_stock_news(t + ".NS", 3)
                    all_news.append({"ticker": t, "change_pct": chg, "price": price, "news": news})
                except Exception:
                    pass
            self._send_json({"gainers": all_news})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_large_deals(self):
        try:
            data = _fetch_large_deals()
            if not data:
                self._send_json({"error": "Could not fetch large deals data"}, 502)
                return
            news_map = {}
            if data.get("symbols"):
                with ThreadPoolExecutor(max_workers=10) as pool:
                    futures = {pool.submit(get_stock_news, s + ".NS", 3): s for s in data["symbols"]}
                    for fut in as_completed(futures):
                        s = futures[fut]
                        try:
                            news = fut.result()
                            if news:
                                news_map[s] = news
                        except Exception:
                            pass
            data["news"] = news_map
            self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_market_overview(self):
        try:
            indices = {}
            for sym, label in [("^NSEI", "NIFTY 50"), ("^BSESN", "SENSEX")]:
                data = get_stock_data(sym)
                if data:
                    indices[label] = {
                        "price": data["price"], "change": data["change"],
                        "change_pct": data["change_pct"], "prev_close": data["prev_close"],
                    }
            headlines = _fetch_headlines(8)
            self._send_json({"indices": indices, "headlines": headlines})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_institutional_deals(self, params):
        url = self._get_param(params, "url", "https://trendlyne.com/portfolio/bulk-block-deals/53902/government-of-singapore/")
        try:
            data = _scrape_trendlyne_deals(url)
            if "error" in data:
                self._send_json(data, 502)
            else:
                self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Stock Dashboard Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Stock dashboard running at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
