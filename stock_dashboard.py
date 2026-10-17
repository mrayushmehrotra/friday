import argparse
import json
import os
import sys
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional
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

from dataclasses import asdict
from stock_tools import get_stock_data, get_stock_news, _resolve_ticker
from concurrent.futures import ThreadPoolExecutor, as_completed, wait

try:
    from vcp_scanner import (
        DEFAULT_SWING_UNIVERSE,
        VCPResult,
        analyze_vcp_stock,
        fetch_stock_candles,
        scan_universe_vcp,
    )
except ImportError:
    DEFAULT_SWING_UNIVERSE = None
    VCPResult = None
    analyze_vcp_stock = None
    fetch_stock_candles = None
    scan_universe_vcp = None

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
    clamp_start,
    STRATEGY_MAP,
    example_strategies,
    format_result_json,
)

PORT = 9090

INDIAN_INDICES = {"^NSEI", "^BSESN", "^NSEBANK"}


def _movement_label(movement_min: Optional[float], movement_max: Optional[float]) -> str:
    """Human-readable 1-month movement filter, for the UI header."""
    if movement_min is not None and movement_max is not None:
        return f"{movement_min:g}% to {movement_max:g}%"
    if movement_min is not None:
        return f"≥ {movement_min:g}%"
    if movement_max is not None:
        return f"≤ {movement_max:g}%"
    return "any"


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


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Swing trading scan — Supports:
# 1. Check 1: 9/20 EMA bullish cross on 4h timeframe (all NSE EQ symbols).
# 2. Check 2: Mark Minervini VCP + Relative Volume Divergence + SMC filters.
# 3. Combined Filter: Simultaneous qualification on BOTH 4h 9/20 EMA & VCP (₹2,000 allocation rule).
#
# Background thread caching ensures fast dashboard responses and live progress.
# Single stocks can also be analyzed immediately via ticker=... parameter.
# ---------------------------------------------------------------------------

_SWING_TTL = 900  # seconds a completed scan is served before a refresh starts
_SWING_LOCK = threading.Lock()
_SWING_STATES: Dict[str, Dict[str, Any]] = {
    "combined": {
        "running": False,
        "started": 0.0,
        "finished": 0.0,
        "scanned": 0,
        "total": 0,
        "results": None,
        "breakouts": [],
        "quiet_accumulations": [],
        "error": None,
    },
    "vcp": {
        "running": False,
        "started": 0.0,
        "finished": 0.0,
        "scanned": 0,
        "total": 0,
        "results": None,
        "breakouts": [],
        "quiet_accumulations": [],
        "error": None,
    },
    "ema_range": {
        "running": False,
        "started": 0.0,
        "finished": 0.0,
        "scanned": 0,
        "total": 0,
        "results": None,
        "breakouts": [],
        "quiet_accumulations": [],
        "error": None,
    },
}
_SWING_STATE = _SWING_STATES["ema_range"]  # legacy fallback alias


def _flatten_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _resample_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse 1h OHLCV bars into 4h bars."""
    df = _flatten_ohlcv(df)
    agg = {k: v for k, v in {
        "Open": "first", "High": "max", "Low": "min",
        "Close": "last", "Volume": "sum",
    }.items() if k in df.columns}
    if "Close" not in agg or df.empty:
        return pd.DataFrame()
    return df.resample("4h").agg(agg).dropna(subset=["Close"])


def _swing_signal_from_4h(df4h: pd.DataFrame, ticker: str):
    """Return a pick when EMA9 > EMA20 on the latest 4h bar ("crossed and still above")."""
    try:
        if df4h is None or df4h.empty or len(df4h) < 25:
            return None
        close = df4h["Close"].astype(float)
        last = float(close.iloc[-1])
        if not np.isfinite(last):
            return None

        ema9 = close.ewm(span=9, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        e9 = float(ema9.iloc[-1])
        e20 = float(ema20.iloc[-1])
        if not (np.isfinite(e9) and np.isfinite(e20)) or e20 == 0:
            return None
        if not (e9 > e20):  # bullish alignment required
            return None

        diff = ema9 - ema20
        cross_idx = None
        for i in range(len(diff) - 1, 0, -1):
            if float(diff.iloc[i]) > 0 and float(diff.iloc[i - 1]) <= 0:
                cross_idx = i
                break
        bars_since = (len(diff) - 1 - cross_idx) if cross_idx is not None else None
        cross_date = ""
        if cross_idx is not None:
            try:
                cross_date = df4h.index[cross_idx].strftime("%Y-%m-%d")
            except Exception:
                cross_date = ""

        gap_pct = (e9 / e20 - 1) * 100
        prev = float(close.iloc[-2]) if len(close) >= 2 else last
        change_pct = ((last / prev - 1) * 100) if prev else 0.0

        recency = 20.0 if bars_since is None else max(0.0, 60.0 - bars_since * 2.0)
        sep_score = min(abs(gap_pct) * 20.0, 40.0)
        score = round(recency + sep_score, 1)

        return {
            "ticker": ticker.replace(".NS", "").replace(".BO", ""),
            "price": round(last, 2),
            "ema9": round(e9, 2),
            "ema20": round(e20, 2),
            "ema_gap_pct": round(gap_pct, 2),
            "bars_since_cross": bars_since,
            "cross_date": cross_date,
            "change_pct": round(change_pct, 2),
            "score": score,
        }
    except Exception:
        return None


def _run_ema_scan():
    tickers = [s + ".NS" for s in ALL_EQ_SYMBOLS]
    total = len(tickers)
    chunk_size = 80
    results = []
    with _SWING_LOCK:
        _SWING_STATES["ema_range"].update(
            total=total,
            scanned=0,
            results=[],
            breakouts=[],
            quiet_accumulations=[],
            error=None,
            running=True,
        )
    try:
        for i in range(0, total, chunk_size):
            chunk = tickers[i:i + chunk_size]
            try:
                data = yf.download(
                    chunk, period="6mo", interval="1h",
                    group_by="ticker", threads=True, progress=False,
                )
            except Exception:
                data = None
            if data is not None and not data.empty:
                for t in chunk:
                    try:
                        if isinstance(data.columns, pd.MultiIndex):
                            if t not in data.columns.get_level_values(0):
                                continue
                            sub = data[t]
                        else:
                            sub = data
                        pick = _swing_signal_from_4h(_resample_4h(sub), t)
                        if pick:
                            results.append(pick)
                    except Exception:
                        continue
            with _SWING_LOCK:
                _SWING_STATES["ema_range"]["scanned"] = min(i + chunk_size, total)
                _SWING_STATES["ema_range"]["results"] = sorted(
                    list(results),
                    key=lambda p: (
                        p["bars_since_cross"] if p["bars_since_cross"] is not None else 10 ** 6,
                        -p["ema_gap_pct"],
                    ),
                )
        with _SWING_LOCK:
            _SWING_STATES["ema_range"].update(running=False, finished=time.time())
    except Exception as e:
        with _SWING_LOCK:
            _SWING_STATES["ema_range"].update(error=str(e), running=False, finished=time.time())


def _run_vcp_scan(mode="combined", api_key=None):
    if scan_universe_vcp is None:
        with _SWING_LOCK:
            _SWING_STATES[mode].update(error="VCP scanner module not loaded", running=False, finished=time.time())
        return

    try:
        from backtest_tools import NIFTY50
        base_u = list(dict.fromkeys(NIFTY50 + (DEFAULT_SWING_UNIVERSE or [])))
    except Exception:
        base_u = DEFAULT_SWING_UNIVERSE or NIFTY_50[:50]
    tickers = [s + ".NS" if not s.endswith(".NS") and not s.endswith(".BO") else s for s in base_u]
    total = len(tickers)

    # Initialize with empty list so partial results stream immediately to user
    with _SWING_LOCK:
        _SWING_STATES[mode].update(
            total=total,
            scanned=0,
            results=[],
            breakouts=[],
            quiet_accumulations=[],
            error=None,
            running=True,
        )

    def _prog(scanned, tot):
        with _SWING_LOCK:
            _SWING_STATES[mode]["scanned"] = scanned

    def _on_match(item):
        with _SWING_LOCK:
            st = _SWING_STATES[mode]
            if st["results"] is None:
                st["results"] = []
            if not any(x.get("ticker") == item.get("ticker") for x in st["results"]):
                st["results"].append(item)
                st["results"].sort(key=lambda x: -x["score"])
                if item.get("status") == "CONFIRMED_BREAKOUT":
                    st["breakouts"].append(item)
                    st["breakouts"].sort(key=lambda x: -x["score"])
                elif item.get("status") in ("PRE_BREAKOUT_ACCUMULATION", "COILING_AT_RESISTANCE"):
                    st["quiet_accumulations"].append(item)
                    st["quiet_accumulations"].sort(key=lambda x: -x["score"])

    try:
        scan_res = scan_universe_vcp(
            tickers=tickers,
            mode=mode,
            api_key=api_key,
            progress_cb=_prog,
            on_match_cb=_on_match,
        )
        with _SWING_LOCK:
            _SWING_STATES[mode].update(
                results=scan_res.get("picks", []),
                breakouts=scan_res.get("breakouts", []),
                quiet_accumulations=scan_res.get("quiet_accumulations", []),
                running=False,
                finished=time.time(),
            )
    except Exception as e:
        with _SWING_LOCK:
            _SWING_STATES[mode].update(error=str(e), running=False, finished=time.time())


def _start_swing_scan(check="combined", refresh=False, api_key=None):
    """Start a background universe scan for the requested check mode unless fresh results exist."""
    check = check if check in _SWING_STATES else "combined"
    with _SWING_LOCK:
        st = _SWING_STATES[check]
        last_key = st.get("api_key")
        key_changed = (api_key is not None and api_key.strip() != (last_key or "").strip())
        fresh = (
            st["results"] is not None
            and st["finished"]
            and (time.time() - st["finished"]) < _SWING_TTL
            and not key_changed
        )
        if (fresh and not refresh) or st["running"]:
            return False
        st.update(running=True, started=time.time(), error=None, api_key=api_key)
        if refresh or key_changed:
            st["results"] = []
            st["breakouts"] = []
            st["quiet_accumulations"] = []

    if check == "ema_range":
        threading.Thread(target=_run_ema_scan, daemon=True).start()
    else:
        threading.Thread(target=_run_vcp_scan, args=(check, api_key), daemon=True).start()
    return True


def _swing_picks(check="combined", refresh=False, api_key=None):
    """Return the current swing state: cached picks, or live scan progress."""
    check = check if check in _SWING_STATES else "combined"
    _start_swing_scan(check=check, refresh=refresh, api_key=api_key)
    with _SWING_LOCK:
        st = dict(_SWING_STATES[check])
    age = (time.time() - st["finished"]) if st["finished"] else None
    return {
        "check": check,
        "api_key_active": bool(st.get("api_key")),
        "scanning": st["running"],
        "scanned": st["scanned"],
        "total": st["total"],
        "error": st["error"],
        "picks": st["results"] or [],
        "breakouts": st.get("breakouts", []),
        "quiet_accumulations": st.get("quiet_accumulations", []),
        "cache_age_sec": round(age) if age is not None else None,
    }


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
        strategy = self._get_param(params, "strategy", "ict_fair_value_gap")
        start = self._get_param(params, "start", "1y")
        interval = self._get_param(params, "interval", "1d")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")
        risk = self._get_float(params, "risk")
        api_key = self._get_param(params, "api_key", "").strip() or None

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        if strategy not in STRATEGY_MAP:
            self._send_json(
                {"error": f"Unknown strategy. Choose: {', '.join(STRATEGY_MAP.keys())}"}, 400
            )
            return
        start, interval, clamped = self._clamp_range(start, interval)

        try:
            resolved = _resolve_ticker(ticker)
            result = run_backtest(
                ticker=resolved, strategy=strategy, start=start,
                interval=interval,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
                api_key=api_key, risk_pct=risk,
            )
            data = format_result_json(result)
            data["strategy"] = strategy
            data["ticker"] = ticker
            data["resolved"] = resolved
            data["interval"] = interval
            data["risk_pct"] = risk
            if clamped:
                data["range_note"] = (
                    f"Range capped to {start} — {interval} bars are only "
                    "retained for a short window by the data provider."
                )
            self._send_json(data)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_compare(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        start = self._get_param(params, "start", "1y")
        interval = self._get_param(params, "interval", "1d")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")
        risk = self._get_float(params, "risk")
        api_key = self._get_param(params, "api_key", "").strip() or None

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        start, interval, clamped = self._clamp_range(start, interval)

        try:
            resolved = _resolve_ticker(ticker)
            results = compare_strategies(
                ticker=resolved, start=start, interval=interval,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
                api_key=api_key, risk_pct=risk,
            )
            payload = {"ticker": ticker, "resolved": resolved, "strategies": results}
            if clamped:
                payload["range_note"] = f"Range capped to {start} for {interval} bars."
            self._send_json(payload)
        except ValueError as e:
            self._send_json({"error": str(e)}, 400)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    @classmethod
    def _clamp_range(cls, start: str, interval: str):
        """Cap the history window for intraday intervals.

        Returns ``(start, interval, clamped)`` — the flag drives a note in the
        response so the user knows why the range is shorter than they asked.
        """
        start, clamped = clamp_start(start, interval)
        return start, interval, clamped

    def _handle_stock_of_day(self, params):
        mode = self._get_param(params, "mode", "midterm")

        try:
            if mode == "intraday":
                picks = _intraday_picks()
                self._send_json({"mode": "intraday", "picks": picks})
            elif mode == "swing":
                check = self._get_param(params, "check", "combined").strip().lower()
                if check not in ("combined", "vcp", "ema_range"):
                    check = "combined"
                refresh = self._get_param(params, "refresh", "") in ("1", "true", "yes", "on")
                api_key = self._get_param(params, "api_key", "").strip() or None
                ticker = self._get_param(params, "ticker", "").strip()

                if ticker:
                    ticker_clean = ticker.upper().replace(".NS", "").replace(".BO", "")
                    if check == "ema_range":
                        try:
                            df_4h = None
                            src = "Yahoo Finance"
                            if api_key and fetch_stock_candles is not None:
                                df_4h, src = fetch_stock_candles(f"{ticker_clean}.NS", period="6mo", interval="4h", api_key=api_key)
                            if df_4h is None:
                                df_1h = yf.download(f"{ticker_clean}.NS", period="6mo", interval="1h", progress=False)
                                df_4h = _resample_4h(df_1h)
                                src = "Yahoo Finance"
                            pick = _swing_signal_from_4h(df_4h, ticker_clean)
                            if pick:
                                pick["data_source"] = src
                                self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "pick": pick})
                            else:
                                self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": f"{ticker_clean} is not currently in a bullish 4h 9/20 EMA alignment (EMA9 <= EMA20)."})
                        except Exception as ex:
                            self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": str(ex)})
                        return

                    if analyze_vcp_stock is not None:
                        res = analyze_vcp_stock(ticker_clean, api_key=api_key)
                        if res is not None:
                            d = asdict(res)
                            if check == "combined" and not (res.ema_bullish_4h and len(res.contractions) >= 2):
                                d["combined_warning"] = "Stock has VCP structure but does not pass 4h 9/20 EMA bullish alignment simultaneously, or has fewer than 2 contractions."
                            self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "pick": d})
                            return
                        else:
                            self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": f"No valid VCP contraction setup detected for {ticker_clean} (requires >= 2 pullbacks with contracting depth & Stage 2 trend)."})
                            return
                    else:
                        self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": "VCP scanner not loaded."})
                        return

                state = _swing_picks(check=check, refresh=refresh, api_key=api_key)
                self._send_json({"mode": "swing", **state})
            elif mode == "options":
                self._send_json({"mode": "options", "picks": [], "info": "Deprecated — use swing mode instead"})
            else:
                strategy = self._get_param(params, "strategy", "ict_fair_value_gap")
                start = self._get_param(params, "start", "1y")
                movement_min = self._get_float(params, "movement_min")
                movement_max = self._get_float(params, "movement_max")
                api_key = self._get_param(params, "api_key", "").strip() or None
                top = stock_of_the_day(
                    start=start, strategy=strategy,
                    movement_min=movement_min, movement_max=movement_max,
                    api_key=api_key,
                )
                self._send_json({
                    "mode": "midterm",
                    "strategy": strategy,
                    "movement_filter": _movement_label(movement_min, movement_max),
                    "picks": top,
                })
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
