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
import urllib.request
import xml.etree.ElementTree as ET

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
        all_symbols = list({d["symbol"] for k in ("BULK_DEALS_DATA", "BLOCK_DEALS_DATA") for d in data.get(k, [])})
        out["symbols"] = all_symbols
        return out
    except Exception:
        return None


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
