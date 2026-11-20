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
        scan_amd_stock,
        scan_universe_vcp,
    )
except ImportError:
    DEFAULT_SWING_UNIVERSE = None
    VCPResult = None
    analyze_vcp_stock = None
    fetch_stock_candles = None
    scan_amd_stock = None
try:
    from daily_support_scanner import (
        analyze_daily_support,
        get_cached_or_scan_support,
        get_chart_series,
    )
except ImportError:
    analyze_daily_support = None
    get_cached_or_scan_support = None
    get_chart_series = None

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
_FNO_CSV_PATH = os.path.join(HERE, "assets", "stocks_with_options.csv")
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


_WATCH_UNIVERSE_CACHE = None
_WATCH_UNIVERSE_LOCK = threading.Lock()


def _load_watch_universe():
    """Return every symbol from the equity and F&O CSV universe (cached)."""
    global _WATCH_UNIVERSE_CACHE
    if _WATCH_UNIVERSE_CACHE is not None:
        return _WATCH_UNIVERSE_CACHE
    with _WATCH_UNIVERSE_LOCK:
        if _WATCH_UNIVERSE_CACHE is not None:
            return _WATCH_UNIVERSE_CACHE
        import csv
        symbols = set()
        for path in (_CSV_PATH, _FNO_CSV_PATH):
            if not os.path.exists(path):
                continue
            try:
                with open(path) as f:
                    for row in csv.DictReader(f):
                        raw = (
                            row.get("SYMBOL")
                            or row.get("symbol")
                            or row.get("cash_trading_symbol")
                            or ""
                        )
                        symbol = str(raw).strip().upper()
                        if symbol:
                            symbols.add(symbol)
            except Exception:
                pass
        if not symbols:
            symbols = set(ALL_EQ_SYMBOLS)
        _WATCH_UNIVERSE_CACHE = sorted(symbols)
        return _WATCH_UNIVERSE_CACHE


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
# 4. AMD Filter (standalone): 4h Accumulation → Manipulation state machine (Pine port, confirmed
#    candles). A liquidity sweep of a tight 4h range that closes back inside (no distribution
#    yet) = the A+ Swing Equity setup at 4h TF.
# 5. Mixed Filter: ALL THREE at once — 4h 9/20 EMA + VCP + active 4h AMD range.
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
    "amd": {
        "running": False,
        "started": 0.0,
        "finished": 0.0,
        "scanned": 0,
        "total": 0,
        "results": None,
        "breakouts": [],
        "quiet_accumulations": [],
        "amd_a_plus": [],
        "amd_accumulations": [],
        "error": None,
    },
    "mixed": {
        "running": False,
        "started": 0.0,
        "finished": 0.0,
        "scanned": 0,
        "total": 0,
        "results": None,
        "breakouts": [],
        "quiet_accumulations": [],
        "amd_a_plus": [],
        "amd_accumulations": [],
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
            amd_a_plus=[],
            amd_accumulations=[],
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
                if item.get("amd_a_plus"):
                    st["amd_a_plus"].append(item)
                    st["amd_a_plus"].sort(key=lambda x: -x["score"])
                elif item.get("amd_status") == "ACCUMULATION":
                    st["amd_accumulations"].append(item)
                    st["amd_accumulations"].sort(key=lambda x: -x["score"])

    try:
        scan_res = scan_universe_vcp(
            tickers=tickers,
            mode=mode,
            api_key=api_key,
            progress_cb=_prog,
            on_match_cb=_on_match,
        )
        amd_ap = scan_res.get("amd_a_plus") or [p for p in scan_res.get("picks", []) if p.get("amd_a_plus")]
        amd_acc = scan_res.get("amd_accumulations") or [p for p in scan_res.get("picks", []) if not p.get("amd_a_plus") and p.get("amd_status") == "ACCUMULATION"]
        with _SWING_LOCK:
            _SWING_STATES[mode].update(
                results=scan_res.get("picks", []),
                breakouts=scan_res.get("breakouts", []),
                quiet_accumulations=scan_res.get("quiet_accumulations", []),
                amd_a_plus=amd_ap,
                amd_accumulations=amd_acc,
                running=False,
                finished=time.time(),
            )
    except Exception as e:
        with _SWING_LOCK:
            _SWING_STATES[mode].update(error=str(e), running=False, finished=time.time())


def _start_swing_scan(check="combined", refresh=False, api_key=None):
    """Start a background universe scan for the requested check mode unless fresh results exist."""
    check = check if check in _SWING_STATES else "combined"
    clean_key = (api_key or "").strip() or None
    with _SWING_LOCK:
        st = _SWING_STATES[check]
        last_key = (st.get("api_key") or "").strip() or None
        key_changed = (clean_key != last_key)
        fresh = (
            st["results"] is not None
            and st["finished"]
            and (time.time() - st["finished"]) < _SWING_TTL
        )
        if not key_changed:
            if (fresh and not refresh) or st["running"]:
                return False

        st.update(running=True, started=time.time(), error=None, api_key=clean_key)
        st["results"] = []
        st["breakouts"] = []
        st["quiet_accumulations"] = []
        st["amd_a_plus"] = []
        st["amd_accumulations"] = []

    if check == "ema_range":
        threading.Thread(target=_run_ema_scan, daemon=True).start()
    else:
        threading.Thread(target=_run_vcp_scan, args=(check, clean_key), daemon=True).start()
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
        "api_key_active": bool((api_key and api_key.strip()) or st.get("api_key")),
        "scanning": st["running"],
        "scanned": st["scanned"],
        "total": st["total"],
        "error": st["error"],
        "picks": st["results"] or [],
        "breakouts": st.get("breakouts", []),
        "quiet_accumulations": st.get("quiet_accumulations", []),
        "amd_a_plus": st.get("amd_a_plus", []),
        "amd_accumulations": st.get("amd_accumulations", []),
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


# ---------------------------------------------------------------------------
# FRIDAY fundamentals — Screener.in + Yahoo Finance
#
# INDstocks does not expose balance sheets, P&L, cash flow or ratios. This layer
# combines the Indian-format tables from Screener.in with Yahoo's statements and
# price history. Both are public read-only sources and are cached briefly.
# ---------------------------------------------------------------------------

_FUNDAMENTALS_CACHE = {}
_FUND_PRICE_CACHE = {}
_FUND_TTL = 600  # 10 minutes


def _fund_clean(node):
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip() if node else ""


def _fund_num(value):
    if value is None:
        return None
    text = str(value).replace(",", "").replace("−", "-").strip()
    if not text or text in ("-", "—", "NA", "N/A"):
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _fund_table(table):
    head = table.find("thead")
    head_cells = head.find_all("th") if head else []
    periods = [_fund_clean(c) for c in head_cells[1:] if _fund_clean(c)]
    body = table.find("tbody") or table
    rows = []
    for tr in body.find_all("tr"):
        cells = tr.find_all(["th", "td"], recursive=False)
        if len(cells) < 2:
            continue
        label = _fund_clean(cells[0])
        values = [_fund_clean(c) for c in cells[1:]]
        if not periods and label:
            periods = values
            continue
        if label or any(v for v in values):
            rows.append({"label": label, "values": values})
    return {"periods": periods, "rows": rows}


def _fund_ranges(table):
    lines = []
    for tr in table.find_all("tr"):
        cells = [_fund_clean(c) for c in tr.find_all(["th", "td"])]
        cells = [c for c in cells if c]
        if cells:
            lines.append(cells)
    if not lines:
        return {"title": "", "metrics": {}}
    title = lines[0][0]
    metrics = {}
    for line in lines[1:]:
        if len(line) >= 2:
            metrics[line[0].rstrip(":")] = line[1]
    return {"title": title, "metrics": metrics}


def _fetch_screener_fundamentals(symbol):
    sym = re.sub(r"\.(NS|BO)$", "", (symbol or "").strip().upper())
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    url = f"https://www.screener.in/company/{sym}/consolidated/"
    response = _requests.get(url, headers=headers, timeout=20)
    if response.status_code != 200:
        response = _requests.get(
            f"https://www.screener.in/company/{sym}/", headers=headers, timeout=20
        )
    if response.status_code != 200:
        raise RuntimeError(f"Screener.in returned HTTP {response.status_code}")
    soup = BeautifulSoup(response.text, "html.parser")
    ratios = {}
    for item in soup.select("#top-ratios li"):
        name = _fund_clean(item.select_one(".name"))
        value = _fund_clean(item.select_one(".value"))
        if name and value:
            ratios[name] = value
    h1 = soup.find("h1")
    about = soup.select_one(".about")
    sector = industry = ""
    peer = soup.find("h2", string=lambda s: s and "Peer comparison" in s)
    if peer:
        links = peer.parent.select("p.sub a[href]")
        by_title = {a.get("title", ""): _fund_clean(a) for a in links}
        sector = by_title.get("Sector") or ""
        industry = by_title.get("Industry") or ""
        if not sector or not industry:
            labels = [_fund_clean(a) for a in links if _fund_clean(a)]
            if len(labels) > 1:
                sector = sector or labels[1]
                industry = industry or labels[-1]
    tables = {}
    ranges = []
    for table in soup.find_all("table"):
        heading = _fund_clean(table.find_previous("h2"))
        css = " ".join(table.get("class") or [])
        if "ranges-table" in css:
            parsed = _fund_ranges(table)
            if parsed["title"]:
                ranges.append(parsed)
            continue
        if "blur" in css or "pointer-events-none" in css:
            continue
        parsed = _fund_table(table)
        if not parsed["periods"] or not parsed["rows"]:
            continue
        if heading.startswith("Quarterly"):
            tables["quarterly"] = parsed
        elif heading.startswith("Profit"):
            tables["annual"] = parsed
        elif heading.startswith("Balance"):
            tables["balance_sheet"] = parsed
        elif heading.startswith("Cash"):
            tables["cash_flow"] = parsed
        elif heading.startswith("Ratios"):
            tables["ratios"] = parsed
        elif heading.startswith("Shareholding"):
            key = "shareholding" if "shareholding" not in tables else "shareholding_annual"
            tables[key] = parsed
    return {
        "profile": {
            "name": _fund_clean(h1) or sym,
            "about": _fund_clean(about),
            "sector": sector,
            "industry": industry,
            "url": url,
        },
        "ratios": ratios,
        "ranges": ranges,
        "tables": tables,
        "source": "Screener.in",
    }


def _fund_df_table(frame, limit=12):
    if frame is None or getattr(frame, "empty", True):
        return {"periods": [], "rows": []}
    frame = frame.iloc[:, :limit]
    periods = []
    for col in frame.columns:
        try:
            periods.append(pd.Timestamp(col).strftime("%b %Y"))
        except Exception:
            periods.append(str(col))
    rows = []
    for label, row in frame.iterrows():
        values = []
        for value in row.tolist():
            try:
                values.append("—" if pd.isna(value) else f"{float(value):,.2f}")
            except (TypeError, ValueError):
                values.append(str(value))
        rows.append({"label": str(label), "values": values})
    return {"periods": periods, "rows": rows}


def _fetch_yahoo_fundamentals(symbol):
    resolved = _resolve_ticker(symbol)
    # Guard invalid / renamed symbols before touching yfinance. Its quoteSummary
    # and history calls print crumbs and "No data found" errors to stderr.
    try:
        quote = get_stock_data(resolved)
    except Exception:
        quote = None
    if not quote:
        raise RuntimeError(f"No Yahoo quote available for {resolved}")
    ticker = yf.Ticker(resolved)
    try:
        info = ticker.info or {}
    except Exception:
        info = {}
    top = {}
    for key, label in [
        ("marketCap", "Market Cap"), ("currentPrice", "Current Price"),
        ("trailingPE", "Stock P/E"), ("priceToBook", "Price/Book"),
        ("dividendYield", "Dividend Yield"), ("returnOnEquity", "ROE"),
        ("returnOnAssets", "ROA"), ("enterpriseValue", "Enterprise Value"),
    ]:
        if info.get(key) is not None:
            top[label] = str(info[key])
    tables = {
        "quarterly": _fund_df_table(ticker.quarterly_financials),
        "annual": _fund_df_table(ticker.financials),
        "balance_sheet": _fund_df_table(ticker.balance_sheet),
        "cash_flow": _fund_df_table(ticker.cashflow),
        "ratios": _fund_df_table(None),
        "shareholding": {"periods": [], "rows": []},
    }
    return {
        "profile": {
            "name": info.get("longName") or quote.get("company") or resolved,
            "about": info.get("longBusinessSummary", ""),
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "url": f"https://finance.yahoo.com/quote/{resolved}/",
        },
        "ratios": top,
        "ranges": [],
        "tables": tables,
        "source": "Yahoo Finance",
    }


def _fund_find_row(table, *keywords, exclude=()):
    for row in (table or {}).get("rows", []):
        label = row.get("label", "").lower()
        if all(k in label for k in keywords) and not any(x in label for x in exclude):
            return row
    return None


def _fund_yoy(tables):
    annual = tables.get("annual") or {}
    quarterly = tables.get("quarterly") or {}
    sales = _fund_find_row(annual, "sales", exclude=("growth",))
    profit = _fund_find_row(annual, "net profit", exclude=("growth",))
    if not profit:
        profit = _fund_find_row(annual, "profit", exclude=("growth", "operating", "before tax"))
    s_growth = _fund_find_row(annual, "sales", "growth")
    p_growth = _fund_find_row(annual, "profit", "growth")
    opm = _fund_find_row(annual, "opm")
    eps = _fund_find_row(annual, "eps")

    def seq(row, index):
        values = (row or {}).get("values", [])
        return _fund_num(values[index]) if 0 <= index < len(values) else None

    def derived(row, index, lag=1):
        cur, prev = seq(row, index), seq(row, index - lag) if index >= lag else None
        if cur is None or prev in (None, 0):
            return None
        return (cur / prev - 1) * 100

    out = []
    for i, period in enumerate(annual.get("periods", [])):
        out.append({
            "period": period,
            "sales": seq(sales, i),
            "profit": seq(profit, i),
            "sales_growth": seq(s_growth, i) if s_growth else derived(sales, i),
            "profit_growth": seq(p_growth, i) if p_growth else derived(profit, i),
            "opm": seq(opm, i),
            "eps": seq(eps, i),
        })

    q_sales = _fund_find_row(quarterly, "sales", exclude=("growth",))
    q_profit = _fund_find_row(quarterly, "net profit", exclude=("growth",))
    q_yoy = []
    for i, period in enumerate(quarterly.get("periods", [])):
        q_yoy.append({
            "period": period,
            "sales": seq(q_sales, i),
            "profit": seq(q_profit, i),
            "sales_growth": derived(q_sales, i, 4),
            "profit_growth": derived(q_profit, i, 4),
        })
    return {"annual": out, "quarterly": q_yoy}


def _fund_price_history(symbol, period):
    period = period if period in ("1y", "3y", "5y", "max") else "1y"
    key = (re.sub(r"\.(NS|BO)$", "", (symbol or "").strip().upper()), period)
    cached = _FUND_PRICE_CACHE.get(key)
    if cached and time.time() - cached[0] < _FUND_TTL:
        return cached[1]
    if not get_stock_data(key[0]):
        return []  # do not poison the 10-minute history cache on a transient 429
    try:
        frame = yf.Ticker(_resolve_ticker(key[0])).history(
            period=period, interval="1d", auto_adjust=False
        )
    except Exception:
        frame = None
    out = []
    if frame is not None and not frame.empty:
        for ts, row in frame.iterrows():
            try:
                out.append({"t": int(ts.timestamp() * 1000), "c": float(row["Close"])})
            except Exception:
                continue
    _FUND_PRICE_CACHE[key] = (time.time(), out)
    return out


def _fetch_fundamentals(symbol, period="1y"):
    sym = re.sub(r"\.(NS|BO)$", "", (symbol or "").strip().upper())
    key = (sym, period if period in ("1y", "3y", "5y", "max") else "1y")
    cached = _FUNDAMENTALS_CACHE.get(key)
    if cached and time.time() - cached[0] < _FUND_TTL:
        return cached[1]

    errors = []
    screener, yahoo = None, None
    try:
        screener = _fetch_screener_fundamentals(sym)
    except Exception as exc:
        errors.append(f"Screener.in: {exc}")
    try:
        yahoo = _fetch_yahoo_fundamentals(sym)
    except Exception as exc:
        errors.append(f"Yahoo Finance: {exc}")
    if not screener and not yahoo:
        raise RuntimeError(" ; ".join(errors) or "No fundamental data available")

    base = screener or yahoo
    tables = dict(base.get("tables") or {})
    if yahoo:
        for name, table in (yahoo.get("tables") or {}).items():
            if not tables.get(name) or not (tables[name] or {}).get("rows"):
                tables[name] = table
    ratios = dict(base.get("ratios") or {})
    if yahoo:
        for name, value in (yahoo.get("ratios") or {}).items():
            ratios.setdefault(name, value)
    result = {
        "status": "success",
        "symbol": sym,
        "resolved": _resolve_ticker(sym),
        "profile": base.get("profile") or {},
        "ratios": ratios,
        "ranges": base.get("ranges") or (yahoo or {}).get("ranges") or [],
        "tables": tables,
        "yoy": _fund_yoy(tables),
        "price_history": _fund_price_history(sym, key[1]),
        "price_range": key[1],
        "sources": [name for name, obj in (("Screener.in", screener), ("Yahoo Finance", yahoo)) if obj],
        "errors": errors,
        "ts": time.time(),
    }
    _FUNDAMENTALS_CACHE[key] = (time.time(), result)
    return result


# ---------------------------------------------------------------------------
# FRIDAY Terminal — INDstocks (INDmoney) proxy
#
# The terminal asks the user to paste an access token on first load. The
# browser keeps it in localStorage and sends it as the `X-IND-Token` header.
# These routes forward it server-side so the browser never has to deal with
# CORS, and so order placement can be audited in one place. Nothing is stored
# on disk here.
# ---------------------------------------------------------------------------

INDSTOCKS_BASE = "https://api.indstocks.com"

_IND_MASTER = None
_IND_SEARCH = None

INDEX_ALIASES = {
    "^NSEI": ("NIDX_40000001", "NIFTY 50"),
    "NIFTY": ("NIDX_40000001", "NIFTY 50"),
    "NIFTY50": ("NIDX_40000001", "NIFTY 50"),
    "BANKNIFTY": ("NIDX_40000003", "BANK NIFTY"),
    "^NSEBANK": ("NIDX_40000003", "BANK NIFTY"),
    "NIFTYBANK": ("NIDX_40000003", "BANK NIFTY"),
    "FINNIFTY": ("NIDX_40000100", "NIFTY FINANCIAL"),
    "MIDCPNIFTY": ("NIDX_40000062", "NIFTY MIDCAP 150"),
    "^BSESN": ("BIDX_40000006", "SENSEX"),
    "SENSEX": ("BIDX_40000006", "SENSEX"),
}


def _load_ind_master():
    """Lazy-load the INDstocks equity master (symbol → scrip code)."""
    global _IND_MASTER, _IND_SEARCH
    if _IND_MASTER is not None:
        return _IND_MASTER
    mapping, search = {}, {}
    path = os.path.join(HERE, "assets", "indstocks_equity_master.csv")
    if os.path.exists(path):
        import csv
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    exch = (row.get("EXCH") or "").strip().upper()
                    segment = (row.get("SEGMENT") or "").strip().upper()
                    sid = (row.get("SECURITY_ID") or "").strip()
                    sym = (row.get("TRADING_SYMBOL") or "").strip().upper()
                    if not sym or not sid or segment not in ("E", "EQ"):
                        continue
                    entry = {
                        "symbol": sym,
                        "name": (row.get("SYMBOL_NAME") or sym).strip(),
                        "exchange": exch,
                        "scrip": f"{exch}_{sid}",
                        "security_id": sid,
                        "lot": (row.get("LOT_UNITS") or "1").strip(),
                        "isin": (row.get("ISIN") or "").strip(),
                    }
                    if exch == "NSE" or sym not in mapping:
                        mapping[sym] = entry
                    if sym not in search:
                        search[sym] = entry
        except Exception as exc:  # pragma: no cover - defensive
            print(f"[terminal] instrument master load failed: {exc}")
    _IND_MASTER, _IND_SEARCH = mapping, list(search.values())
    return _IND_MASTER


def _ind_resolve(symbol):
    """Resolve a terminal symbol (RELIANCE, NIFTY, ^NSEI) to a scrip code."""
    raw = (symbol or "").strip().upper()
    if not raw:
        return None
    if raw in INDEX_ALIASES:
        code, name = INDEX_ALIASES[raw]
        return {
            "symbol": raw.lstrip("^"),
            "name": name,
            "exchange": code.split("_")[0],
            "scrip": code,
            "security_id": code.split("_", 1)[1],
            "lot": "1",
            "index": True,
        }
    resolved = _load_ind_master().get(raw)
    if resolved:
        return resolved
    for suffix in (".NS", ".BO"):
        if raw.endswith(suffix):
            return _ind_resolve(raw[: -len(suffix)])
    return None


def _ind_request(method, path, token, params=None, body=None):
    token = (token or "").strip()
    if not token:
        raise RuntimeError("Missing INDmoney access token")
    response = _requests.request(
        method,
        INDSTOCKS_BASE + path,
        headers={
            "Authorization": token,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        params=params,
        json=body,
        timeout=15,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "error", "message": response.text[:300]}
    if response.status_code >= 400:
        message = (
            payload.get("message")
            or payload.get("error")
            or payload.get("debug_info")
            or f"HTTP {response.status_code}"
        )
        if response.status_code in (401, 403):
            message = "INDmoney token expired or revoked — paste a fresh access token."
        raise RuntimeError(message)
    return payload


# Index history/quotes: the REST scrip-code prefix for indices is not
# documented consistently, so indices are served from the public Yahoo feed
# and cached briefly. Equities always go through INDstocks.
YAHOO_INDEX_MAP = {
    "NIFTY": "^NSEI", "NIFTY50": "^NSEI", "^NSEI": "^NSEI", "NSEI": "^NSEI",
    "BANKNIFTY": "^NSEBANK", "^NSEBANK": "^NSEBANK", "NIFTYBANK": "^NSEBANK",
    "SENSEX": "^BSESN", "^BSESN": "^BSESN",
}
_IND_INDEX_CACHE = {}


def _terminal_yahoo_symbol(symbol):
    return YAHOO_INDEX_MAP.get((symbol or "").strip().upper())


def _terminal_index_quote(symbol):
    ysym = _terminal_yahoo_symbol(symbol)
    if not ysym:
        return None
    cached = _IND_INDEX_CACHE.get(ysym)
    if cached and time.time() - cached[0] < 15:
        return cached[1]
    try:
        data = get_stock_data(ysym)
    except Exception:
        data = None
    if not data:
        return None
    entry = _ind_resolve(symbol) or {}
    quote = {
        "symbol": symbol.lstrip("^"),
        "name": entry.get("name") or data.get("company") or symbol,
        "scrip": entry.get("scrip"),
        "exchange": "NSE" if ysym in ("^NSEI", "^NSEBANK") else "BSE",
        "ltp": data.get("price"),
        "change": data.get("change"),
        "change_pct": data.get("change_pct"),
        "open": data.get("open"),
        "high": data.get("high"),
        "low": data.get("low"),
        "prev_close": data.get("prev_close"),
        "volume": data.get("volume"),
        "w52_high": data.get("fifty_two_week_high"),
        "w52_low": data.get("fifty_two_week_low"),
        "depth": None,
        "source": "Yahoo Finance (index fallback)",
        "ts": time.time(),
    }
    _IND_INDEX_CACHE[ysym] = (time.time(), quote)
    return quote


def _terminal_yahoo_candles(symbol, interval, days):
    ysym = _terminal_yahoo_symbol(symbol)
    if not ysym:
        return []
    yinterval = {
        "1minute": "1m", "2minute": "2m", "5minute": "5m", "15minute": "15m",
        "30minute": "30m", "60minute": "60m", "1day": "1d", "1week": "1wk",
        "1month": "1mo",
    }.get(interval, "1d")
    if yinterval.endswith("m"):
        period = f"{max(1, min(days, 7))}d"
    elif yinterval == "1d":
        period = f"{max(5, min(days, 365))}d"
    elif yinterval == "1mo":
        period = "1y"
    else:
        period = f"{max(1, min(days // 7 or 1, 52))}wk"
    try:
        frame = yf.Ticker(ysym).history(period=period, interval=yinterval, auto_adjust=False)
    except Exception:
        return []
    if frame is None or frame.empty:
        return []
    out = []
    for ts, row in frame.iterrows():
        try:
            out.append({
                "t": int(ts.timestamp() * 1000),
                "o": float(row["Open"]), "h": float(row["High"]),
                "l": float(row["Low"]), "c": float(row["Close"]),
                "v": float(row.get("Volume", 0) or 0),
            })
        except Exception:
            continue
    return out


def _ind_norm_quote(symbol, entry, q):
    return {
        "symbol": symbol,
        "name": entry.get("name") or symbol,
        "scrip": entry.get("scrip"),
        "exchange": entry.get("exchange"),
        "ltp": q.get("live_price"),
        "change": q.get("day_change"),
        "change_pct": q.get("day_change_percentage"),
        "open": q.get("day_open"),
        "high": q.get("day_high"),
        "low": q.get("day_low"),
        "prev_close": q.get("prev_close"),
        "volume": q.get("volume"),
        "w52_high": q.get("52week_high"),
        "w52_low": q.get("52week_low"),
        "upper_circuit": q.get("upper_circuit"),
        "lower_circuit": q.get("lower_circuit"),
        "depth": q.get("market_depth"),
        "ts": time.time(),
    }


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
        elif path in ("/api/corporate-events", "/api/events"):
            self._handle_corporate_events(params)
        elif path == "/api/market-wire":
            self._handle_market_wire(params)
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
        elif path == "/api/top-buying-stocks":
            self._handle_top_buying_stocks()
        elif path == "/api/large-deals":
            self._handle_large_deals()
        elif path == "/api/market-overview":
            self._handle_market_overview()
        elif path == "/api/institutional-deals":
            self._handle_institutional_deals(params)
        elif path == "/api/fno-strategy":
            self._handle_fno_strategy(params)
        elif path == "/api/fno-stocks":
            self._handle_fno_stocks()
        elif path == "/api/gex":
            self._handle_gex(params)
        elif path == "/api/fundamentals":
            self._handle_fundamentals(params)
        elif path == "/api/terminal/health":
            self._handle_terminal_health()
        elif path == "/api/terminal/search":
            self._handle_terminal_search(params)
        elif path == "/api/terminal/watch-universe":
            self._handle_terminal_watch_universe()
        elif path == "/api/terminal/quotes":
            self._handle_terminal_quotes(params)
        elif path == "/api/terminal/depth":
            self._handle_terminal_depth(params)
        elif path == "/api/terminal/candles":
            self._handle_terminal_candles(params)
        elif path == "/api/terminal/funds":
            self._handle_terminal_proxy("/funds")
        elif path == "/api/terminal/holdings":
            self._handle_terminal_proxy("/portfolio/holdings")
        elif path == "/api/terminal/positions":
            self._handle_terminal_positions(params)
        elif path == "/api/terminal/orders":
            self._handle_terminal_proxy("/order-book")
        elif path == "/api/terminal/trades":
            self._handle_terminal_proxy("/trade-book", params)
        elif path == "/api/terminal/option-chain":
            self._handle_terminal_option_chain(params)
        elif path == "/api/daily-support":
            self._handle_daily_support(params)
        elif path == "/api/daily-support/chart":
            self._handle_daily_support_chart(params)
        elif path == "/api/strategy/orb":
            self._handle_strategy_orb(params)
        elif path == "/api/strategy/monte-carlo":
            self._handle_strategy_monte_carlo(params)
        elif path in ("/", "/terminal"):
            self._serve_file("terminal.html")
        elif path == "/legacy":
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

    def _handle_fundamentals(self, params):
        ticker = self._get_param(params, "ticker", "").strip()
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        period = (self._get_param(params, "range", "1y") or "1y").lower()
        try:
            data = _fetch_fundamentals(ticker, period)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)
            return
        self._send_json(data)

    def _handle_quote(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        try:
            data = get_stock_data(resolved)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)
            return
        if not data:
            self._send_json({"error": f"No data for {ticker}"}, 404)
            return
        self._send_json(data)

    def _handle_news(self, params):
        ticker = (self._get_param(params, "ticker", "") or self._get_param(params, "symbol", "")).upper().strip()
        count = int(self._get_param(params, "count", "15") or 15)
        refresh = bool(self._get_param(params, "refresh", "0") in ("1", "true"))
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        clean = ticker.replace(".NS", "").replace(".BO", "")
        resolved_entry = _ind_resolve(clean)
        comp_name = resolved_entry.get("name") if resolved_entry else None
        try:
            import news_events_engine
            res = news_events_engine.fetch_stock_news(clean, company_name=comp_name, count=count, force_refresh=refresh)
            articles = res.get("articles", [])
            # Supply both "news" (legacy array of dicts) and "articles" (modern)
            self._send_json({
                "ticker": clean,
                "symbol": clean,
                "company": comp_name or clean,
                "count": len(articles),
                "articles": articles,
                "news": articles,
                "updated_at": res.get("updated_at"),
            })
        except Exception as exc:
            self._send_json({"ticker": clean, "symbol": clean, "news": [], "articles": [], "error": str(exc)}, 502)

    def _handle_corporate_events(self, params):
        ticker = (self._get_param(params, "ticker", "") or self._get_param(params, "symbol", "")).upper().strip()
        refresh = bool(self._get_param(params, "refresh", "0") in ("1", "true"))
        if not ticker:
            self._send_json({"error": "Missing ticker or symbol parameter"}, 400)
            return
        clean = ticker.replace(".NS", "").replace(".BO", "")
        try:
            import news_events_engine
            data = news_events_engine.fetch_corporate_events(clean, force_refresh=refresh)
            self._send_json(data)
        except Exception as exc:
            self._send_json({"error": str(exc), "symbol": clean, "actions": [], "announcements": []}, 502)

    def _handle_market_wire(self, params):
        limit = int(self._get_param(params, "limit", "60") or 60)
        refresh = bool(self._get_param(params, "refresh", "0") in ("1", "true"))
        try:
            import news_events_engine
            data = news_events_engine.fetch_market_wire(force_refresh=refresh, limit=limit)
            self._send_json(data)
        except Exception as exc:
            self._send_json({"error": str(exc), "articles": []}, 502)

    def _handle_backtest(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        strategy = self._get_param(params, "strategy", "ict_fair_value_gap")
        start = self._get_param(params, "start", "1y")
        interval = self._get_param(params, "interval", "1d")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")
        risk = self._get_float(params, "risk")
        api_key = self._get_param(params, "api_key", "").strip() or self._ind_token(params) or None

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
        api_key = self._get_param(params, "api_key", "").strip() or self._ind_token(params) or None

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
                if check not in ("combined", "vcp", "ema_range", "amd", "mixed"):
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

                    if check == "amd":
                        # Standalone 4h AMD filter — needs no VCP base.
                        if scan_amd_stock is not None:
                            try:
                                pick = scan_amd_stock(f"{ticker_clean}.NS", api_key=api_key)
                                if pick:
                                    self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "pick": pick})
                                else:
                                    self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": f"No active 4h AMD range for {ticker_clean} right now (no tight accumulation base / setup already resolved)."})
                            except Exception as ex:
                                self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": str(ex)})
                        else:
                            self._send_json({"mode": "swing", "check": check, "single": True, "ticker": ticker_clean, "error": "VCP/AMD scanner not loaded."})
                        return

                    if analyze_vcp_stock is not None:
                        res = analyze_vcp_stock(ticker_clean, api_key=api_key)
                        if res is not None:
                            d = asdict(res)
                            if check == "combined" and not (res.ema_bullish_4h and len(res.contractions) >= 2):
                                d["combined_warning"] = "Stock has VCP structure but does not pass 4h 9/20 EMA bullish alignment simultaneously, or has fewer than 2 contractions."
                            if check == "mixed":
                                fails = []
                                if not res.ema_bullish_4h:
                                    fails.append("4h 9/20 EMA is not bullish")
                                if len(res.contractions) < 2:
                                    fails.append("fewer than 2 VCP contractions")
                                if not res.amd_status:
                                    fails.append("no active 4h AMD range")
                                if fails:
                                    d["mixed_warning"] = "Mixed Filter (EMA + VCP + AMD) not fully satisfied: " + "; ".join(fails) + "."
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

    def _get_top_gainers_batch(self):
        gainers = []
        tickers = [t + ".NS" for t in NIFTY_50]
        try:
            df = yf.download(tickers, period="5d", progress=False)
            if not df.empty and "Close" in df:
                close = df["Close"]
                for t in tickers:
                    sym = t.replace(".NS", "")
                    if t in close:
                        c = close[t].dropna()
                        if len(c) >= 2:
                            pct = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
                            if pct > 0:
                                gainers.append((sym, round(pct, 2), round(float(c.iloc[-1]), 2)))
        except Exception:
            pass

        if not gainers:
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
        return gainers

    def _handle_bullish_news(self):
        try:
            gainers = self._get_top_gainers_batch()
            top = gainers[:8]
            top_5_symbols = [t[0] for t in top[:5]]
            all_news = []
            for t, chg, price in top:
                try:
                    news = get_stock_news(t + ".NS", 3)
                    all_news.append({"ticker": t, "change_pct": chg, "price": price, "news": news})
                except Exception:
                    all_news.append({"ticker": t, "change_pct": chg, "price": price, "news": []})
            self._send_json({"gainers": all_news, "top_5": top_5_symbols})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_top_buying_stocks(self):
        try:
            gainers = self._get_top_gainers_batch()
            top_5 = gainers[:5]
            stocks = [{"symbol": t[0], "change_pct": t[1], "price": t[2]} for t in top_5]
            self._send_json({"status": "success", "top_5": [t[0] for t in top_5], "stocks": stocks})
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

    def _handle_fno_strategy(self, params):
        json_path = os.path.join(HERE, "assets", "bullish_stocks_with_cheap_puts.json")
        refresh = self._get_param(params, "refresh", "0").lower() in ("1", "true", "yes")
        days = int(self._get_param(params, "days", "5") or 5)
        max_premium = float(self._get_param(params, "max_premium", "20.0") or 20.0)
        max_lot_cost = float(self._get_param(params, "max_lot_cost", "5000.0") or 5000.0)
        mode = self._get_param(params, "mode", "higher_closes")

        # Return cached JSON if default parameters and no refresh requested
        if (
            not refresh
            and os.path.exists(json_path)
            and days == 5
            and abs(max_premium - 20.0) < 1e-4
            and abs(max_lot_cost - 5000.0) < 1e-4
            and mode == "higher_closes"
        ):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._send_json(data)
                return
            except Exception:
                pass

        try:
            from bullish_put_filter import BullishPutFilter
            scanner = BullishPutFilter(
                consecutive_days=days,
                max_put_premium=max_premium,
                max_lot_investment=max_lot_cost,
                bullish_mode=mode,
            )
            data = scanner.run_screen()
            scanner.save_results(data)
            self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_fno_stocks(self):
        json_path = os.path.join(HERE, "assets", "stocks_with_options.json")
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                self._send_json(json.load(f))
        else:
            self._send_json({"error": "stocks_with_options.json not found"}, 404)

    def _handle_gex(self, params):
        """Gamma exposure / option Greeks for NIFTY 50 and SENSEX."""
        index_key = (params.get("index") or ["NIFTY"])[0].upper()
        expiry = (params.get("expiry") or [None])[0]
        try:
            strike_count = int((params.get("strike_count") or [15])[0])
        except (TypeError, ValueError):
            strike_count = 15
        try:
            import gex
            self._send_json(gex.get_gex(index_key, expiry, strike_count))
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_daily_support(self, params):
        if analyze_daily_support is None:
            self._send_json({"error": "Daily support scanner module not loaded"}, 500)
            return

        ticker = self._get_param(params, "ticker", "").strip()
        api_key = self._get_param(params, "api_key", "").strip() or self._ind_token(params) or None
        max_dist = self._get_float(params, "max_dist", 2.0)

        try:
            if ticker:
                match = analyze_daily_support(ticker, api_key=api_key, max_support_dist_pct=max_dist)
                if match:
                    self._send_json({"single": True, "ticker": ticker, "pick": asdict(match)})
                else:
                    self._send_json({"single": True, "ticker": ticker, "error": f"No data or support analysis available for {ticker}"})
                return

            universe = self._get_param(params, "universe", "nifty50").strip()
            refresh = self._get_param(params, "refresh", "") in ("1", "true", "yes", "on")
            support_type = self._get_param(params, "support_type", "all").strip().lower()

            data = get_cached_or_scan_support(universe=universe, refresh=refresh, api_key=api_key, max_dist=max_dist)

            # Optional filter by support_type
            if support_type != "all" and data.get("picks"):
                picks = data["picks"]
                if support_type == "confluence":
                    data["picks"] = [p for p in picks if p.get("has_confluence")]
                elif support_type == "sma":
                    data["picks"] = [p for p in picks if "SMA" in p.get("primary_support", {}).get("type", "")]
                elif support_type == "horizontal":
                    data["picks"] = [p for p in picks if "HORIZONTAL" in p.get("primary_support", {}).get("type", "")]
                elif support_type == "order_block":
                    data["picks"] = [p for p in picks if "ORDER_BLOCK" in p.get("primary_support", {}).get("type", "")]
                elif support_type == "hammer":
                    data["picks"] = [p for p in picks if p.get("candle_reaction") == "HAMMER_WICK_REJECTION"]

            self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_daily_support_chart(self, params):
        if get_chart_series is None:
            self._send_json({"error": "Daily support chart module not loaded"}, 500)
            return

        ticker = self._get_param(params, "ticker", "").strip()
        api_key = self._get_param(params, "api_key", "").strip() or self._ind_token(params) or None
        bars = int(self._get_param(params, "bars", "90") or 90)

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return

        try:
            chart_data = get_chart_series(ticker, api_key=api_key, bars=bars)
            self._send_json(chart_data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_strategy_orb(self, params):
        symbol = (self._get_param(params, "symbol", "NIFTY") or "NIFTY").strip().upper()
        days = int(self._get_param(params, "days", "60") or 60)
        direction = (self._get_param(params, "direction", "BOTH") or "BOTH").strip().upper()
        mode = (self._get_param(params, "mode", "standard") or "standard").strip().lower()
        cutoff_str = (self._get_param(params, "cutoff", "14:30") or "14:30").strip()
        risk = float(self._get_param(params, "risk", "1000.0") or 1000.0)
        capital = float(self._get_param(params, "capital", "100000.0") or 100000.0)
        token = self._ind_token(params)

        try:
            import datetime as dt_mod
            from opening_range_backtest import run_opening_range_backtest
            from monte_carlo_pinescript import fetch_candles_with_fallback

            cutoff_h, cutoff_m = map(int, cutoff_str.split(":"))
            cutoff_time = dt_mod.time(cutoff_h, cutoff_m)

            df, source = fetch_candles_with_fallback(symbol, token=token, interval="5minute", days=days)
            if df is None or len(df) < 15:
                self._send_json({"error": f"Insufficient 5-minute candle data for {symbol} ({source})"}, 400)
                return

            trades, summary = run_opening_range_backtest(
                df=df,
                symbol=symbol,
                direction=direction,
                displacement_mode=mode,
                risk_per_trade_inr=risk,
                initial_capital=capital,
                max_entry_time=cutoff_time,
            )

            today_status = None
            if not df.empty and isinstance(df.index, pd.DatetimeIndex):
                last_date = df.index[-1].date()
                day_df = df[df.index.date == last_date]
                or_candles = day_df[(day_df.index.time >= dt_mod.time(9, 15)) & (day_df.index.time < dt_mod.time(9, 30))]
                if len(or_candles) >= 3:
                    or_h = float(or_candles["High"].max())
                    or_l = float(or_candles["Low"].min())
                    latest_candle = day_df.iloc[-1]
                    today_status = {
                        "date": str(last_date),
                        "or_high": round(or_h, 2),
                        "or_low": round(or_l, 2),
                        "or_range": round(or_h - or_l, 2),
                        "latest_time": df.index[-1].strftime("%H:%M"),
                        "latest_close": round(float(latest_candle["Close"]), 2),
                        "displaced_bullish": bool(float(latest_candle["Close"]) > or_h),
                        "displaced_bearish": bool(float(latest_candle["Close"]) < or_l),
                    }

            self._send_json({
                "symbol": symbol,
                "data_source": source,
                "summary": asdict(summary),
                "today": today_status,
                "trades": [asdict(t) for t in trades[-100:]],
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)

    def _handle_strategy_monte_carlo(self, params):
        symbol = (self._get_param(params, "symbol", "NIFTY") or "NIFTY").strip().upper()
        days = int(self._get_param(params, "days", "60") or 60)
        interval = (self._get_param(params, "interval", "15minute") or "15minute").strip().lower()
        simulations = int(self._get_param(params, "simulations", "1000") or 1000)
        simulations = min(5000, max(100, simulations))
        trail_mode = (self._get_param(params, "trail_mode", "EMA Trail") or "EMA Trail").strip()
        use_partial = (self._get_param(params, "use_partial", "1") or "1").lower() in ("1", "true", "yes")
        token = self._ind_token(params)

        try:
            from monte_carlo_pinescript import (
                fetch_candles_with_fallback,
                simulate_pinescript_strategy as simulate_strategy,
                run_monte_carlo,
            )

            df, source = fetch_candles_with_fallback(symbol, token=token, interval=interval, days=days)
            if df is None or len(df) < 30:
                self._send_json({"error": f"Insufficient {interval} candle data for {symbol} ({source})"}, 400)
                return

            trades = simulate_strategy(
                df=df,
                symbol=symbol,
                trail_mode=trail_mode,
                use_partial=use_partial,
            )

            if not trades:
                self._send_json({
                    "error": f"No trades generated for {symbol} on {interval} with mode {trail_mode}",
                    "data_source": source,
                }, 400)
                return

            metrics, curves, max_dd = run_monte_carlo(trades, num_simulations=simulations)

            n_steps = curves.shape[1]
            step_indices = np.linspace(0, n_steps - 1, min(50, n_steps), dtype=int)
            p5_band = [round(float(v), 2) for v in np.percentile(curves[:, step_indices], 5, axis=0)]
            p25_band = [round(float(v), 2) for v in np.percentile(curves[:, step_indices], 25, axis=0)]
            p50_band = [round(float(v), 2) for v in np.percentile(curves[:, step_indices], 50, axis=0)]
            p75_band = [round(float(v), 2) for v in np.percentile(curves[:, step_indices], 75, axis=0)]
            p95_band = [round(float(v), 2) for v in np.percentile(curves[:, step_indices], 95, axis=0)]

            self._send_json({
                "symbol": symbol,
                "data_source": source,
                "trail_mode": trail_mode,
                "use_partial": use_partial,
                "metrics": asdict(metrics),
                "percentiles": {
                    "steps": list(range(len(step_indices))),
                    "p5": p5_band,
                    "p25": p25_band,
                    "p50": p50_band,
                    "p75": p75_band,
                    "p95": p95_band,
                },
                "trades": [asdict(t) for t in trades[:50]],
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 500)


    # ------------------------------------------------------------------
    # FRIDAY Terminal endpoints
    # ------------------------------------------------------------------
    def _ind_token(self, params=None):
        token = (
            self.headers.get("X-IND-Token", "")
            or self.headers.get("X-Api-Key", "")
            or ""
        )
        if not token and params:
            token = self._get_param(params, "api_key", "") or ""
        return token.strip()

    def _handle_terminal_health(self):
        token = self._ind_token()
        if not token:
            self._send_json({"ok": False, "error": "Paste an INDmoney access token."}, 401)
            return
        try:
            payload = _ind_request("GET", "/funds", token)
            self._send_json({"ok": True, "funds": payload.get("data", {}), "source": "INDstocks"})
            return
        except Exception as exc:
            funds_error = str(exc)
        # Some tokens are scoped for market data only — fall back to a quote
        # ping so the terminal can still open in read-only trading mode.
        try:
            _ind_request(
                "GET",
                "/market/quotes/ltp",
                token,
                params={"scrip-codes": "NSE_2885"},
            )
            self._send_json({
                "ok": True,
                "funds": {},
                "trading": False,
                "warning": f"Market data OK; account funds unavailable: {funds_error}",
                "source": "INDstocks",
            })
        except Exception:
            self._send_json({"ok": False, "error": funds_error}, 401)

    def _handle_terminal_search(self, params):
        query = (self._get_param(params, "q", "") or "").strip().upper()
        limit = int(self._get_param(params, "limit", "20") or 20)
        _load_ind_master()
        ranked = []
        for alias in INDEX_ALIASES:
            if not alias.startswith("^") and query and query in alias:
                entry = _ind_resolve(alias)
                if entry:
                    ranked.append((0, {**entry, "index": True}))
        if query:
            for entry in _IND_SEARCH or []:
                symbol = entry["symbol"]
                name = entry["name"].upper()
                if symbol == query:
                    score = 0
                elif symbol.startswith(query):
                    score = 1 if entry["exchange"] == "NSE" else 2
                elif name.startswith(query):
                    score = 3
                elif query in symbol:
                    score = 4
                elif query in name:
                    score = 5
                else:
                    continue
                ranked.append((score, entry))
        ranked.sort(key=lambda item: (item[0], len(item[1].get("symbol", ""))))
        results, seen = [], set()
        for _, entry in ranked:
            key = entry.get("symbol")
            if key not in seen:
                seen.add(key)
                results.append(entry)
            if len(results) >= limit:
                break
        self._send_json({"results": results})

    def _handle_terminal_watch_universe(self):
        self._send_json({"symbols": _load_watch_universe()})

    def _handle_terminal_quotes(self, params):
        token = self._ind_token(params)
        if not token:
            self._send_json({"error": "Paste an INDmoney access token."}, 401)
            return
        raw = (self._get_param(params, "symbols", "") or "").split(",")
        symbols = [s.strip().upper() for s in raw if s.strip()][:1000]
        if not symbols:
            self._send_json({"error": "symbols parameter required"}, 400)
            return
        resolved, code_to_symbol, index_symbols, missing = {}, {}, [], []
        for symbol in symbols:
            entry = _ind_resolve(symbol)
            if not entry:
                missing.append(symbol)
                continue
            resolved[symbol] = entry
            if entry.get("index"):
                index_symbols.append(symbol)
            else:
                code_to_symbol[entry["scrip"]] = symbol

        quotes, warning = {}, None
        if code_to_symbol:
            try:
                payload = _ind_request(
                    "GET",
                    "/market/quotes/full",
                    token,
                    params={"scrip-codes": ",".join(code_to_symbol.keys())},
                )
                data = payload.get("data") or {}
                for code, symbol in code_to_symbol.items():
                    if code in data:
                        quotes[symbol] = _ind_norm_quote(symbol, resolved[symbol], data[code] or {})
            except Exception as exc:
                warning = str(exc)

        # Indices come from the public fallback; never let one bad index code
        # poison the equity batch.
        for symbol in index_symbols:
            quote = _terminal_index_quote(symbol)
            if quote:
                quotes[symbol] = quote

        result = {"quotes": quotes, "missing": missing, "ts": time.time()}
        if warning and not quotes:
            self._send_json({"error": warning, **result}, 502)
            return
        if warning:
            result["warning"] = warning
        self._send_json(result)

    def _handle_terminal_depth(self, params):
        token = self._ind_token(params)
        symbol = (self._get_param(params, "symbol", "") or "").upper()
        entry = _ind_resolve(symbol)
        if not entry:
            self._send_json({"error": f"Unknown symbol {symbol}"}, 404)
            return
        try:
            payload = _ind_request(
                "GET",
                "/market/quotes/mkt",
                token,
                params={"scrip-codes": entry["scrip"]},
            )
            block = (payload.get("data") or {}).get(entry["scrip"], {}) or {}
            depth = block.get("market_depth") or {}
            levels = depth.get("depth") or []
            bids, asks = [], []
            for level in levels:
                buy = level.get("buy") or {}
                sell = level.get("sell") or {}
                if buy:
                    bids.append({
                        "price": float(str(buy.get("price", 0)).replace(",", "")),
                        "qty": float(str(buy.get("quantity", 0)).replace(",", "")),
                    })
                if sell:
                    asks.append({
                        "price": float(str(sell.get("price", 0)).replace(",", "")),
                        "qty": float(str(sell.get("quantity", 0)).replace(",", "")),
                    })
            self._send_json({
                "symbol": symbol,
                "bids": bids,
                "asks": asks,
                "aggregate": depth.get("aggregate") or {},
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def _handle_terminal_candles(self, params):
        token = self._ind_token(params)
        symbol = (self._get_param(params, "symbol", "") or "").upper()
        entry = _ind_resolve(symbol)
        if not entry:
            self._send_json({"error": f"Unknown symbol {symbol}"}, 404)
            return
        interval = (self._get_param(params, "interval", "1day") or "1day").strip()
        allowed = {
            "1minute", "2minute", "3minute", "4minute", "5minute", "10minute",
            "15minute", "30minute", "60minute", "120minute", "180minute",
            "240minute", "1day", "1week", "1month",
        }
        if interval not in allowed:
            interval = "1day"
        days = int(self._get_param(params, "days", "260") or 260)
        max_days = 365 if interval in ("1day", "1week", "1month") else (15 if "minute" in interval and interval[:2].isdigit() and int(interval[:2]) >= 60 else 7)
        days = max(1, min(days, max_days))
        if entry.get("index"):
            candles = _terminal_yahoo_candles(symbol, interval, days)
            self._send_json({
                "symbol": symbol,
                "scrip": entry["scrip"],
                "interval": interval,
                "source": "Yahoo Finance (index fallback)",
                "candles": candles,
            })
            return
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - days * 24 * 3600 * 1000
        try:
            payload = _ind_request(
                "GET",
                f"/market/historical/{interval}",
                token,
                params={
                    "scrip-codes": entry["scrip"],
                    "start_time": start_ms,
                    "end_time": now_ms,
                },
            )
            block = (payload.get("data") or {}).get(entry["scrip"], {}) or {}
            candles = [
                {
                    "t": int(c.get("ts", 0)) * 1000,
                    "o": float(c.get("o", 0)),
                    "h": float(c.get("h", 0)),
                    "l": float(c.get("l", 0)),
                    "c": float(c.get("c", 0)),
                    "v": float(c.get("v", 0)),
                }
                for c in (block.get("candles") or [])
                if c.get("c") is not None
            ]
            self._send_json({
                "symbol": symbol,
                "scrip": entry["scrip"],
                "interval": interval,
                "candles": candles,
            })
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def _handle_terminal_proxy(self, path, params=None):
        token = self._ind_token(params)
        if not token:
            self._send_json({"error": "Paste an INDmoney access token."}, 401)
            return
        query = {}
        if params:
            for key, values in params.items():
                if key in ("api_key",):
                    continue
                if values:
                    query[key] = values[0]
        try:
            payload = _ind_request("GET", path, token, params=query or None)
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def _fetch_terminal_positions(self, token):
        """Aggregate the four segment/product position books into one list."""
        combos = [
            ("equity", "intraday"), ("equity", "cnc"),
            ("derivative", "intraday"), ("derivative", "margin"),
        ]
        rows, errors = [], []
        for segment, product in combos:
            try:
                payload = _ind_request(
                    "GET",
                    "/portfolio/positions",
                    token,
                    params={"segment": segment, "product": product},
                )
                data = payload.get("data")
                if isinstance(data, list):
                    rows.extend(data)
                elif isinstance(data, dict):
                    rows.extend(data.get("positions") or [])
            except Exception as exc:
                errors.append(f"{segment}/{product}: {exc}")
        # De-duplicate by position id where available.
        dedup, seen = [], set()
        for row in rows:
            key = row.get("position_id") or (
                row.get("security_id"), row.get("segment"), row.get("product"),
                row.get("drv_expiry_date"), row.get("drv_strike_price"),
                row.get("drv_option_type"),
            )
            if key in seen:
                continue
            seen.add(key)
            dedup.append(row)
        return dedup, errors

    def _handle_terminal_positions(self, params):
        token = self._ind_token(params)
        if not token:
            self._send_json({"error": "Paste an INDmoney access token."}, 401)
            return
        segment = (self._get_param(params, "segment", "") or "").strip()
        product = (self._get_param(params, "product", "") or "").strip()
        if segment and product:
            try:
                payload = _ind_request(
                    "GET",
                    "/portfolio/positions",
                    token,
                    params={"segment": segment, "product": product},
                )
                self._send_json(payload)
            except Exception as exc:
                self._send_json({"error": str(exc)}, 502)
            return
        rows, errors = self._fetch_terminal_positions(token)
        self._send_json({
            "status": "success" if rows or not errors else "error",
            "data": rows,
            "errors": errors,
        })

    def _handle_terminal_flatten(self, body):
        """Emergency exit: market-close every non-zero position."""
        token = self._ind_token()
        dry_run = bool((body or {}).get("dry_run", True))
        if not token:
            self._send_json({"error": "Paste an INDmoney access token."}, 401)
            return
        rows, errors = self._fetch_terminal_positions(token)
        results = []
        for row in rows:
            try:
                net = int(float(row.get("net_qty") or 0))
            except (TypeError, ValueError):
                continue
            if net == 0:
                continue
            security_id = str(row.get("security_id") or "").strip()
            if not security_id:
                errors.append(f"{row.get('symbol')}: missing security_id")
                continue
            payload = {
                "txn_type": "SELL" if net > 0 else "BUY",
                "exchange": (row.get("exchange") or "NSE").upper(),
                "segment": (row.get("segment") or "EQUITY").upper(),
                "product": (row.get("product") or "INTRADAY").upper(),
                "order_type": "MARKET",
                "validity": "DAY",
                "security_id": security_id,
                "qty": abs(net),
                "is_amo": False,
                "algo_id": "99999",
                "remarks": "FRIDAY-FLATTEN",
            }
            if dry_run:
                results.append({
                    "status": "simulated",
                    "symbol": row.get("symbol"),
                    "qty": abs(net),
                    "side": payload["txn_type"],
                    "request": payload,
                })
                continue
            try:
                response = _ind_request("POST", "/order", token, body=payload)
                results.append({
                    "status": "sent",
                    "symbol": row.get("symbol"),
                    "qty": abs(net),
                    "side": payload["txn_type"],
                    "response": response,
                })
            except Exception as exc:
                errors.append(f"{row.get('symbol')}: {exc}")
        self._send_json({
            "status": "success" if not errors else "partial",
            "dry_run": dry_run,
            "orders": results,
            "errors": errors,
        })

    def _handle_terminal_option_chain(self, params):
        token = self._ind_token(params)
        index = (self._get_param(params, "index", "NIFTY") or "NIFTY").upper()
        expiry = self._get_param(params, "expiry", "") or None
        strike_count = int(self._get_param(params, "strike_count", "15") or 15)
        try:
            import gex as gex_mod
            chain = gex_mod.fetch_chain(
                index,
                expiry=expiry,
                strike_count=strike_count,
                request_get=lambda url, **kwargs: _requests.get(
                    url,
                    params=kwargs.get("params"),
                    headers={"Authorization": token},
                    timeout=20,
                ),
            )
            lot = 65 if index == "NIFTY" else 25
            try:
                lot = int(gex_mod.load_index_meta().get(index, {}).get("lot_size", lot) or lot)
            except Exception:
                pass
            analysis = gex_mod.analyze_chain(chain, lot)
            self._send_json({"chain": chain, "analysis": analysis})
        except Exception as exc:
            self._send_json({"error": str(exc)}, 502)

    def _handle_terminal_order(self, body):
        token = self._ind_token()
        if not token:
            body = body or {}
            token = str(body.pop("api_key", "") or "").strip()
        if not token:
            self._send_json({"error": "Paste an INDmoney access token."}, 401)
            return
        body = body or {}
        symbol = str(body.get("symbol", "") or "").upper().strip()
        entry = _ind_resolve(symbol)
        if not entry:
            self._send_json({"error": f"Unknown symbol {symbol}"}, 404)
            return
        try:
            qty = int(body.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        if qty <= 0:
            self._send_json({"error": "qty must be greater than zero"}, 400)
            return
        order_type = str(body.get("order_type", "LIMIT") or "LIMIT").upper()
        try:
            limit_price = float(body.get("limit_price") or 0)
        except (TypeError, ValueError):
            limit_price = 0.0
        if order_type == "LIMIT" and limit_price <= 0:
            self._send_json({"error": "limit_price required for LIMIT orders"}, 400)
            return
        payload = {
            "txn_type": str(body.get("txn_type", "BUY") or "BUY").upper(),
            "exchange": str(body.get("exchange") or entry.get("exchange") or "NSE").upper(),
            "segment": str(body.get("segment") or "EQUITY").upper(),
            "product": str(body.get("product") or "INTRADAY").upper(),
            "order_type": order_type,
            "validity": str(body.get("validity") or "DAY").upper(),
            "security_id": str(entry.get("security_id") or ""),
            "qty": qty,
            "is_amo": bool(body.get("is_amo", False)),
            "algo_id": "99999",
            "remarks": str(body.get("remarks") or "FRIDAY-TERMINAL")[:100],
        }
        if limit_price > 0:
            payload["limit_price"] = round(limit_price, 2)
        if body.get("dry_run"):
            self._send_json({
                "status": "success",
                "dry_run": True,
                "data": {
                    "order_id": f"PAPER-{int(time.time())}",
                    "order_status": "SIMULATED",
                    "request": payload,
                },
            })
            return
        try:
            response = _ind_request("POST", "/order", token, body=payload)
            self._send_json({**response, "request": payload})
        except Exception as exc:
            self._send_json({"status": "error", "error": str(exc)}, 502)

    def _handle_terminal_cancel(self, body):
        token = self._ind_token()
        order_id = str((body or {}).get("order_id", "") or "").strip()
        if not token or not order_id:
            self._send_json({"error": "token and order_id required"}, 400)
            return
        try:
            response = _ind_request("POST", "/order/cancel", token, body={"order_id": order_id})
            self._send_json(response)
        except Exception as exc:
            self._send_json({"status": "error", "error": str(exc)}, 502)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            self._send_json({"error": "invalid JSON body"}, 400)
            return
        if path == "/api/terminal/order":
            self._handle_terminal_order(body)
        elif path == "/api/terminal/flatten":
            self._handle_terminal_flatten(body)
        elif path == "/api/terminal/order/cancel":
            self._handle_terminal_cancel(body)
        else:
            self.send_error(404)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Stock Dashboard Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--no-telegram", action="store_true",
                        help="do not start the institutional-deals Telegram watcher")
    args = parser.parse_args()

    # Institutional deal watcher → Telegram alerts (best effort, daemon thread).
    if not args.no_telegram:
        try:
            from institution_telegram_bot import start_watcher
            if start_watcher():
                print("Telegram institution watcher started (new institution "
                      "buy/sell deals will be messaged)")
            else:
                print("Telegram watcher not configured "
                      "(telegram_config.json) — skipping")
        except Exception as e:
            print(f"Telegram watcher failed to start: {e}")

    server = ThreadingHTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Stock dashboard running at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
