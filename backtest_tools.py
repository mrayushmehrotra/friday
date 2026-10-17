import argparse
import json
import re
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from gs_quant.timeseries import technicals, statistics
from ict_strategies import (
    Signal,
    add_ict_indicators,
    example_strategies,
    STRATEGY_MAP,
    NEEDS_SMT_REF,
    ict_fair_value_gap,
    ict_silver_bullet,
    ict_order_block_mss,
    ict_liquidity_sweep_turtle_soup,
    ict_optimal_trade_entry,
    ict_judas_swing,
    super_trend,
)

INDIAN_INDICES = {"^NSEI", "^BSESN", "^NSEBANK"}

NIFTY50 = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN",
    "ITC", "HCLTECH", "WIPRO", "LT", "BAJFINANCE", "MARUTI", "TATAMOTORS",
    "ASIANPAINT", "NESTLEIND", "SUNPHARMA", "KOTAKBANK", "AXISBANK", "TITAN",
    "POWERGRID", "NTPC", "M&M", "ULTRACEMCO", "TECHM", "HINDUNILVR", "COALINDIA",
    "BAJAJ-AUTO", "HEROMOTOCO", "DRREDDY", "CIPLA", "GRASIM", "ADANIENT",
    "ADANIPORTS", "ZOMATO", "TRENT", "BAJAJFINSV", "DIVISLAB", "SBILIFE",
    "HINDALCO", "EICHERMOT", "BPCL", "TATACONSUM", "HDFCLIFE", "BRITANNIA",
    "INDUSINDBK", "HINDZINC", "BEL", "ONGC", "JSWSTEEL",
]

#: history window the data providers actually keep for each intraday interval
#: (Yahoo retains 15-minute bars ~60 days and 1-hour bars ~2 years)
INTRADAY_MAX_START = {"5m": "5d", "15m": "1mo", "1h": "2y", "4h": "2y"}
_PERIOD_ORDER = ["5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"]


def clamp_start(start: str, interval: str) -> Tuple[str, bool]:
    """Cap the history window for intraday intervals.

    Yahoo keeps 15-minute bars for ~60 days; asking for more returns nothing at
    all, which surfaces as "no market data" and hides the real reason.  Returns
    ``(start, clamped)`` so a caller can tell the user the range was trimmed.
    """
    cap = INTRADAY_MAX_START.get(interval)
    if cap is None:
        return start, False
    try:
        clamped = _PERIOD_ORDER.index(start) > _PERIOD_ORDER.index(cap)
    except ValueError:
        clamped = True
    return (cap if clamped else start), clamped


def _resolve_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if t in INDIAN_INDICES or t.endswith(".NS") or t.endswith(".BO"):
        return t
    if re.match(r"^[A-Z0-9&.-]{1,20}$", t):
        return t + ".NS"
    safe = re.sub(r"[^A-Z0-9]", "", t)
    if safe:
        return safe + ".NS"
    return t


@dataclass
class Position:
    """An open trade.

    ``entry_cost`` is the capital actually deployed: cash spent for a long
    (including entry commission) and net proceeds received for a short.  Every
    P&L number in the engine is derived from it, so ``pnl`` and ``pnl_pct``
    can never disagree about the sign of a trade.
    """

    side: str  # "LONG" | "SHORT"
    size: float
    entry_price: float
    entry_date: pd.Timestamp
    entry_cost: float
    stop_price: Optional[float] = None      # structural ICT invalidation level
    target_price: Optional[float] = None    # draw on liquidity
    highest_price: float = 0.0
    lowest_price: float = float("inf")


@dataclass
class Trade:
    entry_date: pd.Timestamp
    exit_date: pd.Timestamp
    entry_price: float
    exit_price: float
    size: float
    pnl_pct: float
    pnl: float
    reason: str = ""
    side: str = "LONG"


@dataclass
class BacktestResult:
    trades: List[Trade]
    equity_curve: pd.Series
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate: float
    num_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    data_source: str = "Yahoo Finance (NSE)"


# Mapping of common Indian tickers to INDstocks / INDmoney security IDs (per assets/indstocks-api-docs.md)
INDSTOCKS_SECURITY_IDS = {
    "RELIANCE": "NSE_2885",
    "TCS": "NSE_11536",
    "HDFCBANK": "NSE_1333",
    "INFY": "NSE_1594",
    "ICICIBANK": "NSE_4963",
    "SBIN": "NSE_3045",
    "BHARTIARTL": "NSE_10604",
    "ITC": "NSE_1660",
    "KOTAKBANK": "NSE_1922",
    "LT": "NSE_11483",
    "AXISBANK": "NSE_5900",
    "BAJFINANCE": "NSE_317",
    "MARUTI": "NSE_10999",
    "TATAMOTORS": "NSE_3456",
    "SUNPHARMA": "NSE_3351",
    "ASIANPAINT": "NSE_236",
    "TITAN": "NSE_3506",
    "ULTRACEMCO": "NSE_11532",
    "NTPC": "NSE_11630",
    "POWERGRID": "NSE_14977",
    "WIPRO": "NSE_3787",
    "HCLTECH": "NSE_7229",
    "M&M": "NSE_2031",
    "ADANIENT": "NSE_25",
    "ADANIPORTS": "NSE_15083",
    "COALINDIA": "NSE_20374",
    "BAJAJ-AUTO": "NSE_16669",
    "HEROMOTOCO": "NSE_1348",
    "DRREDDY": "NSE_881",
    "CIPLA": "NSE_694",
    "GRASIM": "NSE_1232",
    "ZOMATO": "NSE_5097",
    "TRENT": "NSE_1964",
    "BAJAJFINSV": "NSE_16675",
    "DIVISLAB": "NSE_10940",
    "SBILIFE": "NSE_21808",
    "HINDALCO": "NSE_1363",
    "EICHERMOT": "NSE_910",
    "BPCL": "NSE_526",
    "TATACONSUM": "NSE_3432",
    "HDFCLIFE": "NSE_467",
    "BRITANNIA": "NSE_547",
    "INDUSINDBK": "NSE_5258",
    "HINDZINC": "NSE_1424",
    "BEL": "NSE_383",
    "ONGC": "NSE_2475",
    "JSWSTEEL": "NSE_11723",
    "TECHM": "NSE_13538",
    "HINDUNILVR": "NSE_1394",
    "VEDL": "NSE_3067",
    "TATASTEEL": "NSE_3499",
    "NIFTY": "NSE_40000001",
    "^NSEI": "NSE_40000001",
    "BANKNIFTY": "NSE_40000002",
    "^NSEBANK": "NSE_40000002",
}

_INSTRUMENTS_CACHE: Dict[str, str] = {}


def resolve_indstocks_scrip(ticker: str, api_key: Optional[str] = None) -> Optional[str]:
    """Resolve an Indian equity ticker to its INDstocks security ID (e.g. NSE_2885).

    Checks the static map first, then in-memory cache, then locally cached
    equity master CSV, and downloads from INDstocks instruments API if needed.
    """
    clean = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    if clean in INDSTOCKS_SECURITY_IDS:
        return INDSTOCKS_SECURITY_IDS[clean]
    if clean.startswith("NSE_") or clean.startswith("BSE_"):
        return clean
    if clean in _INSTRUMENTS_CACHE:
        return _INSTRUMENTS_CACHE[clean]

    import os
    csv_path = os.path.join(os.path.dirname(__file__), "assets", "indstocks_equity_master.csv")
    if not os.path.exists(csv_path) and api_key and api_key.strip():
        try:
            import requests
            r = requests.get(
                "https://api.indstocks.com/market/instruments?source=equity",
                headers={"Authorization": api_key.strip()},
                timeout=15,
            )
            if r.status_code == 200 and len(r.content) > 1000:
                with open(csv_path, "wb") as f:
                    f.write(r.content)
        except Exception:
            pass

    if os.path.exists(csv_path):
        try:
            import csv
            with open(csv_path, "r", encoding="utf-8", errors="ignore") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    sym = (row.get("TRADING_SYMBOL") or row.get("CUSTOM_SYMBOL") or "").strip().upper()
                    sec_id = (row.get("SECURITY_ID") or "").strip()
                    exch = (row.get("EXCH") or "NSE").strip().upper()
                    if sym and sec_id:
                        _INSTRUMENTS_CACHE[sym] = f"{exch}_{sec_id}"
            if clean in _INSTRUMENTS_CACHE:
                return _INSTRUMENTS_CACHE[clean]
        except Exception:
            pass

    return None


def fetch_indstocks_data(scrip_code: str, api_key: str, interval: str = "15minute", days: int = 365) -> Optional[pd.DataFrame]:
    """Fetch historical candles from INDstocks / INDmoney API per assets/indstocks-api-docs.md.

    Supports 1day (Daily), 240minute (4h), 60minute (1h), and 15minute intervals
    with date-range paging to build continuous price history.
    """
    import requests
    import time

    if interval in ("1d", "1day", "d", "daily"):
        ind_interval = "1day"
        chunk_days = 365
    elif interval in ("4h", "240m", "240minute"):
        ind_interval = "240minute"
        chunk_days = 15
    elif interval in ("1h", "60m", "60minute"):
        ind_interval = "60minute"
        chunk_days = 15
    elif interval in ("15m", "15minute"):
        ind_interval = "15minute"
        chunk_days = 7
    elif interval in ("5m", "5minute"):
        ind_interval = "5minute"
        chunk_days = 7
    else:
        ind_interval = "1day"
        chunk_days = 365

    now_ms = int(time.time() * 1000)
    target_start_ms = now_ms - (days * 24 * 60 * 60 * 1000)
    headers = {
        "Authorization": api_key.strip(),
        "Accept": "application/json",
    }

    all_rows = []
    curr_end_ms = now_ms
    max_pages = min(24, max(1, (days + chunk_days - 1) // chunk_days))

    for _ in range(max_pages):
        if curr_end_ms <= target_start_ms:
            break
        curr_start_ms = max(target_start_ms, curr_end_ms - (chunk_days * 24 * 60 * 60 * 1000))
        url = f"https://api.indstocks.com/market/historical/{ind_interval}?scrip-codes={scrip_code}&start_time={curr_start_ms}&end_time={curr_end_ms}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                res = r.json()
                if res.get("success") and res.get("data"):
                    scrip_data = res["data"].get(scrip_code)
                    if scrip_data and scrip_data.get("candles"):
                        candles = scrip_data["candles"]
                        for c in candles:
                            all_rows.append({
                                "Date": pd.to_datetime(c["ts"], unit="s", utc=True).tz_convert("Asia/Kolkata"),
                                "Open": float(c["o"]),
                                "High": float(c["h"]),
                                "Low": float(c["l"]),
                                "Close": float(c["c"]),
                                "Volume": float(c.get("v", 0)),
                            })
            curr_end_ms = curr_start_ms
        except Exception:
            break

    if all_rows:
        df = pd.DataFrame(all_rows).drop_duplicates(subset=["Date"]).sort_values("Date").set_index("Date")
        if len(df) >= 5:
            return df

    # If 240minute was not returned, fallback try 60minute and aggregate to 4h
    if interval in ("4h", "240minute") and not all_rows:
        df_60m = fetch_indstocks_data(scrip_code, api_key, interval="60minute", days=min(days, 60))
        if df_60m is not None and len(df_60m) >= 5:
            return resample_to_4h(df_60m)

    return None


def fetch_yahoo_chart(ticker: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Fallback direct Yahoo Finance chart API with browser User-Agent to avoid crumb/429 rate limits."""
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={period}&interval={interval}"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            res = r.json()
            result = res.get("chart", {}).get("result")
            if result:
                quote = result[0]["indicators"]["quote"][0]
                ts = result[0]["timestamp"]
                df = pd.DataFrame({
                    "Date": pd.to_datetime(ts, unit="s", utc=True).tz_convert("Asia/Kolkata"),
                    "Open": quote.get("open"),
                    "High": quote.get("high"),
                    "Low": quote.get("low"),
                    "Close": quote.get("close"),
                    "Volume": quote.get("volume"),
                }).dropna().set_index("Date")
                if len(df) >= 2:
                    return df
    except Exception:
        pass
    return None


def resample_to_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate intraday candles into 4-hour bars.

    NSE trades 09:15–15:30 IST, so a session splits into a morning bucket
    (08:00–12:00) and an afternoon one (12:00–16:00); the afternoon bar is the
    shorter closing auction.  Each bucket is aggregated only from the bars
    inside it, so nothing from a later bucket can influence an earlier one —
    the result stays causal bar for bar.
    """
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    if len(df) < 2 or not pd.Index(df.index.normalize()).duplicated().any():
        return df  # already lower frequency than 4h (e.g. daily)
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    if "Volume" in df.columns:
        agg["Volume"] = "sum"
    out = df.groupby(df.index.floor("4h")).agg(agg)
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out[out["High"] >= out["Low"]]


def fetch_data(
    ticker: str,
    start: str = "2y",
    end: Optional[str] = None,
    interval: str = "1d",
    api_key: Optional[str] = None,
) -> Tuple[pd.DataFrame, str]:
    start, _ = clamp_start(start, interval)  # intraday bars only live ~60 days
    clean_sym = ticker.replace(".NS", "").replace(".BO", "").upper()

    # Yahoo has no 4h interval: fetch 1h and aggregate.
    base_interval = "1h" if interval == "4h" else interval

    # 1. Try INDstocks API first if api_key is provided.
    if api_key and api_key.strip() and interval in ("1d", "4h", "15m", "1h", "5m"):
        scrip = resolve_indstocks_scrip(clean_sym, api_key.strip())
        if scrip:
            try:
                days = 730 if start in ("2y", "5y") else (365 if start == "1y" else 90)
                df_ind = fetch_indstocks_data(scrip, api_key.strip(), interval=interval, days=days)
                if df_ind is not None and len(df_ind) >= 5:
                    if interval == "4h":
                        df_ind = resample_to_4h(df_ind)
                        if len(df_ind) >= 5:
                            return df_ind, "INDstocks API (Live Token, 4h bars)"
                    else:
                        return df_ind, "INDstocks API (Live Token)"
            except Exception:
                pass

    # 2. Try standard yfinance download
    try:
        period_patterns = ("d", "mo", "wk", "y")
        if any(start.endswith(suf) for suf in period_patterns) and end is None:
            df = yf.download(ticker, period=start, interval=base_interval, progress=False)
        elif end:
            df = yf.download(ticker, start=start, end=end, interval=base_interval, progress=False)
        else:
            df = yf.download(ticker, start=start, interval=base_interval, progress=False)
        if df is not None and not df.empty and len(df) >= 5:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if interval == "4h":
                df = resample_to_4h(df)
                if len(df) >= 5:
                    return df, "Yahoo Finance (NSE, 4h bars)"
            else:
                return df, "Yahoo Finance (NSE)"
    except Exception:
        pass

    # 3. Direct Yahoo chart API fallback (resilient to 429 crumb rate limit)
    chart_period = start if any(start.endswith(suf) for suf in ("d", "mo", "y")) else "1y"
    df_direct = fetch_yahoo_chart(ticker, period=chart_period, interval=base_interval)
    if df_direct is not None and not df_direct.empty and len(df_direct) >= 5:
        if interval == "4h":
            df_direct = resample_to_4h(df_direct)
            if len(df_direct) >= 5:
                return df_direct, "Yahoo Finance (Direct API, 4h bars)"
        else:
            return df_direct, "Yahoo Finance (Direct API)"

    raise ValueError(f"No market data available for {ticker}")


def add_indicators(df: pd.DataFrame, ref: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """ICT indicator set.  ``ref`` is the index series used for SMT divergence."""
    return add_ict_indicators(df, ref=ref)


#: SMT reference pairs — correlated instruments ICT compares for divergence.
SMT_REF_PAIRS = {
    "^NSEI": "^BSESN",    # NIFTY 50 vs SENSEX
    "^BSESN": "^NSEI",
    "^NSEBANK": "^NSEI",
}
DEFAULT_SMT_REF = "^NSEI"

_SMT_REF_CACHE: Dict[Tuple[str, str, str], pd.DataFrame] = {}
_SMT_REF_TRIED: set = set()


def _load_smt_ref(
    ticker: str,
    start: str,
    interval: str,
    api_key: Optional[str] = None,
) -> Optional[pd.DataFrame]:
    """Fetch (and cache) the reference series an SMT strategy compares against.

    Only the reference's raw ``Close`` is needed — ``_smt_columns`` reindexes it
    onto the symbol's calendar with forward-fill, so no future reference data
    can leak in.  Returns ``None`` when no sensible partner exists (e.g. the
    symbol already *is* the only index we know), which callers must surface as
    an error rather than silently degrade to a non-SMT strategy.
    """
    ref_ticker = SMT_REF_PAIRS.get(ticker, DEFAULT_SMT_REF)
    if ref_ticker == ticker:
        return None

    key = (ref_ticker, start, interval)
    cached = _SMT_REF_CACHE.get(key)
    if cached is not None:
        return cached
    if key in _SMT_REF_TRIED:  # a failed fetch is not retried per ticker
        return None
    _SMT_REF_TRIED.add(key)

    try:
        ref_df, _ = fetch_data(ref_ticker, start=start, interval=interval, api_key=api_key)
    except Exception:
        return None

    ref_df = ref_df[["Close"]].dropna()
    if len(ref_df) < 5:
        return None
    _SMT_REF_CACHE[key] = ref_df
    return ref_df


def _calendar_years(index: pd.Index) -> float:
    """Span of the backtest in years, from the calendar (not bar count)."""
    try:
        days = (index[-1] - index[0]).days
        return days / 365.25
    except Exception:
        return len(index) / 252.0


def compute_performance(equity: pd.Series, trades: List[Trade], data_source: str = "Yahoo Finance (NSE)") -> BacktestResult:
    """Aggregate performance.

    Annualisation is calendar based (``len(bars) / span_years`` periods per
    year), so a 15-minute backtest and a daily one both get the right Sharpe
    and the right annualised return.
    """
    if len(equity) < 2:
        daily_returns = pd.Series(dtype=float)
    else:
        daily_returns = equity.pct_change().dropna()

    n_years = _calendar_years(equity.index)
    if n_years <= 0:
        n_years = max(len(equity) / 252.0, 1e-9)
    periods_per_year = max(len(equity) / n_years, 1.0)

    if len(daily_returns) > 0:
        total_ret = (equity.iloc[-1] / equity.iloc[0]) - 1
        if 1 + total_ret > 0:
            ann_ret = (1 + total_ret) ** (1 / n_years) - 1
        else:
            ann_ret = -1.0
        sharpe = (
            (daily_returns.mean() / daily_returns.std() * np.sqrt(periods_per_year))
            if daily_returns.std() > 0
            else 0.0
        )
    else:
        total_ret = ann_ret = sharpe = 0.0

    cumulative_max = equity.cummax()
    drawdown = (equity - cumulative_max) / cumulative_max
    max_dd = drawdown.min()

    if not trades:
        return BacktestResult(
            trades=[], equity_curve=equity, total_return_pct=round(total_ret * 100, 2),
            annualized_return_pct=round(ann_ret * 100, 2), max_drawdown_pct=round(max_dd * 100, 2),
            sharpe_ratio=round(sharpe, 2), win_rate=0.0, num_trades=0,
            avg_win_pct=0.0, avg_loss_pct=0.0, profit_factor=0.0,
            data_source=data_source,
        )

    # a trade is a win iff it made money — same test as profit factor uses
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    win_rate = len(wins) / len(trades) * 100

    avg_win = np.mean([t.pnl_pct for t in wins]) if wins else 0.0
    avg_loss = np.mean([t.pnl_pct for t in losses]) if losses else 0.0

    gross_profit = sum(t.pnl for t in wins) if wins else 0
    gross_loss = abs(sum(t.pnl for t in losses)) if losses else 1
    profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0.0

    return BacktestResult(
        trades=trades,
        equity_curve=equity,
        total_return_pct=round(total_ret * 100, 2),
        annualized_return_pct=round(ann_ret * 100, 2),
        max_drawdown_pct=round(max_dd * 100, 2),
        sharpe_ratio=round(sharpe, 2),
        win_rate=round(win_rate, 2),
        num_trades=len(trades),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        data_source=data_source,
    )


def run_backtest(
    df: pd.DataFrame,
    signal_fn: Callable[..., Signal],
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    data_source: str = "Yahoo Finance (NSE)",
    risk_pct: Optional[float] = None,
) -> BacktestResult:
    """Walk the indicator frame bar by bar.

    Execution model, per bar:

    1. The strategy sees the *current* position and returns a Signal describing
       the desired end state (``BUY``/``SHORT`` reverse an opposite position,
       ``SELL``/``COVER`` only close that side).
    2. Protective levels run **intrabar**: the structural ICT stop carried from
       the entry signal, tightened by the optional fixed-% and trailing stops —
       whichever sits closest.  Liquidity targets fill intrabar too.  A level
       that price gaps through is filled at the bar's open, which is what
       actually happens live; a close-based stop would miss wick-throughs.
    3. Signal-driven exits and entries execute on the close.  A bar that hit a
       stop or a target never re-enters on that same bar (churn filter:
       stop -> immediate re-entry at the same close).

    Accounting: ``entry_cost`` is the capital deployed *including* the entry
    commission, exits deduct the exit commission from the cashflow, and both
    ``pnl`` and ``pnl_pct`` are derived from those two numbers — so their signs
    always agree and win rate can't contradict profit factor.

    ``risk_pct`` sizes an entry so that a stop-out loses that percentage of
    equity (ICT risk model); without it the full equity is allocated, scaled by
    ``Signal.size``.
    """
    import inspect

    df = df.copy()
    cash = initial_capital
    position: Optional[Position] = None
    trades: List[Trade] = []
    equity = pd.Series(index=df.index, dtype=float)

    try:
        n_params = len(inspect.signature(signal_fn).parameters)
    except (TypeError, ValueError):
        n_params = 3

    def _close_position(price: float, date, reason: str) -> None:
        nonlocal cash, position
        pos = position
        if pos.side == "LONG":
            cashflow = pos.size * price * (1 - commission_pct)
            cash += cashflow
            pnl = cashflow - pos.entry_cost
        else:
            cashflow = pos.size * price * (1 + commission_pct)
            cash -= cashflow
            pnl = pos.entry_cost - cashflow
        pnl_pct = (pnl / pos.entry_cost * 100) if pos.entry_cost else 0.0
        trades.append(Trade(
            entry_date=pos.entry_date, exit_date=date,
            entry_price=pos.entry_price, exit_price=price,
            size=pos.size, pnl_pct=pnl_pct, pnl=pnl,
            reason=reason, side=pos.side,
        ))
        position = None

    def _open_position(side: str, sig: Signal, price: float, date) -> None:
        nonlocal cash, position
        if price <= 0 or cash <= 0:
            return

        stop = sig.stop_price
        if stop is not None:
            if (side == "LONG" and stop >= price) or (side == "SHORT" and stop <= price):
                stop = None  # invalid structural level — fall back to no stop
        target = sig.target_price
        if target is not None:
            if (side == "LONG" and target <= price) or (side == "SHORT" and target >= price):
                target = None

        if risk_pct and stop is not None and abs(price - stop) > 0:
            shares = (cash * risk_pct / 100.0) / abs(price - stop)
        else:
            shares = (cash * sig.size) / price

        max_shares = (
            cash / (price * (1 + commission_pct))
            if side == "LONG"
            else cash / (price * (1 - commission_pct))
        )
        shares = min(shares, max_shares)
        if not np.isfinite(shares) or shares <= 0:
            return

        if side == "LONG":
            entry_cost = shares * price * (1 + commission_pct)
            cash -= entry_cost
        else:
            entry_cost = shares * price * (1 - commission_pct)
            cash += entry_cost

        position = Position(
            side=side, size=shares, entry_price=price, entry_date=date,
            entry_cost=entry_cost, stop_price=stop, target_price=target,
            highest_price=price, lowest_price=price,
        )

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]
        price = float(row["Close"])
        o = float(row["Open"])
        h = float(row["High"])
        l = float(row["Low"])

        sig = signal_fn(df, i, position) if n_params >= 3 else signal_fn(df, i)

        exited_this_bar = False

        if position is not None:
            position.highest_price = max(position.highest_price, h)
            position.lowest_price = min(position.lowest_price, l)

            stop_price, stop_label = position.stop_price, "Structural stop (invalidation)"
            if stop_price is None:
                stop_price, stop_label = None, None

            if stop_loss_pct is not None:
                pct_stop = (
                    position.entry_price * (1 - abs(stop_loss_pct) / 100)
                    if position.side == "LONG"
                    else position.entry_price * (1 + abs(stop_loss_pct) / 100)
                )
                label = f"Stop-loss ({abs(stop_loss_pct):.1f}%)"
                if stop_price is None:
                    stop_price, stop_label = pct_stop, label
                elif position.side == "LONG" and pct_stop > stop_price:
                    stop_price, stop_label = pct_stop, label
                elif position.side == "SHORT" and pct_stop < stop_price:
                    stop_price, stop_label = pct_stop, label

            if trailing_stop_pct is not None:
                ts = abs(trailing_stop_pct)
                if position.side == "LONG":
                    trail = position.highest_price * (1 - ts / 100)
                    label = f"Trailing stop (-{ts:.1f}% from ₹{position.highest_price:.2f})"
                    tighten = stop_price is None or trail > stop_price
                else:
                    trail = position.lowest_price * (1 + ts / 100)
                    label = f"Trailing stop (+{ts:.1f}% from ₹{position.lowest_price:.2f})"
                    tighten = stop_price is None or trail < stop_price
                if tighten:
                    stop_price, stop_label = trail, label

            exit_price = None
            if position.side == "LONG":
                if stop_price is not None and l <= stop_price:
                    exit_price = o if o <= stop_price else stop_price
                elif position.target_price is not None and h >= position.target_price:
                    t = position.target_price
                    exit_price = o if o >= t else t
                    stop_label = f"Liquidity target reached (₹{t:.2f})"
            else:
                if stop_price is not None and h >= stop_price:
                    exit_price = o if o >= stop_price else stop_price
                elif position.target_price is not None and l <= position.target_price:
                    t = position.target_price
                    exit_price = o if o <= t else t
                    stop_label = f"Liquidity target reached (₹{t:.2f})"

            if exit_price is not None:
                _close_position(exit_price, date, stop_label or "stop")
                exited_this_bar = True

        if not exited_this_bar:
            action = sig.action
            if action == "EXIT" and position is not None:
                _close_position(price, date, sig.reason or "exit")
            elif action == "SELL" and position is not None and position.side == "LONG":
                _close_position(price, date, sig.reason or "exit long")
            elif action == "COVER" and position is not None and position.side == "SHORT":
                _close_position(price, date, sig.reason or "exit short")
            elif action == "BUY" and position is not None and position.side == "SHORT":
                _close_position(price, date, f"Reversal: {sig.reason or 'long signal'}")
            elif action == "SHORT" and position is not None and position.side == "LONG":
                _close_position(price, date, f"Reversal: {sig.reason or 'short signal'}")

            if position is None:
                if action == "BUY":
                    _open_position("LONG", sig, price, date)
                elif action == "SHORT":
                    _open_position("SHORT", sig, price, date)

        if position is None:
            equity.iloc[i] = cash
        elif position.side == "LONG":
            equity.iloc[i] = cash + position.size * price
        else:
            equity.iloc[i] = cash - position.size * price

    if position is not None:
        price = float(df["Close"].iloc[-1])
        _close_position(price, df.index[-1], "end of backtest")
        equity.iloc[-1] = cash

    return compute_performance(equity, trades, data_source=data_source)


def format_result(result: BacktestResult, ticker: str) -> str:
    resolved = _resolve_ticker(ticker)
    ccy = "₹" if resolved.endswith(".NS") or resolved.endswith(".BO") or resolved in INDIAN_INDICES else "$"
    lines = [
        f"Backtest Results for {ticker.replace('.NS', '')}",
        f"{'=' * 50}",
        f"Data Source:       {getattr(result, 'data_source', 'Yahoo Finance')}",
        f"Total Return:      {result.total_return_pct:>+8.2f}%",
        f"Annualized Return: {result.annualized_return_pct:>+8.2f}%",
        f"Max Drawdown:      {result.max_drawdown_pct:>8.2f}%",
        f"Sharpe Ratio:      {result.sharpe_ratio:>8.2f}",
        f"Trades:            {result.num_trades:>8d}",
        f"Win Rate:          {result.win_rate:>8.2f}%",
        f"Avg Win:           {result.avg_win_pct:>+8.2f}%",
        f"Avg Loss:          {result.avg_loss_pct:>+8.2f}%",
        f"Profit Factor:     {result.profit_factor:>8.2f}",
    ]

    if result.trades:
        lines.extend(["", f"{'Trades':-^50}", ""])
        for t in result.trades[-10:]:
            sign = "+" if t.pnl >= 0 else ""
            lines.append(
                f"  {_ts_label(t.entry_date)} -> {_ts_label(t.exit_date)} | "
                f"{t.side:<5} | {ccy}{t.entry_price:.2f} -> {ccy}{t.exit_price:.2f} | "
                f"PnL: {sign}{ccy}{t.pnl:.2f} ({sign}{t.pnl_pct:.2f}%) | {t.reason}"
            )

    return "\n".join(lines)


def _ts_label(d) -> str:
    """Date label; includes the time of day for intraday bars."""
    try:
        if getattr(d, "hour", 0) or getattr(d, "minute", 0):
            return d.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return str(getattr(d, "date", lambda: d)())


def _drawdown_curve(equity: pd.Series) -> list:
    cummax = equity.cummax()
    dd = ((equity - cummax) / cummax * 100).fillna(0)
    return [
        {"date": _ts_label(d), "value": round(float(v), 2)}
        for d, v in dd.items()
    ]


def format_result_json(result: BacktestResult) -> dict:
    return {
        "data_source": getattr(result, "data_source", "Yahoo Finance (NSE)"),
        "total_return_pct": result.total_return_pct,
        "annualized_return_pct": result.annualized_return_pct,
        "max_drawdown_pct": result.max_drawdown_pct,
        "sharpe_ratio": result.sharpe_ratio,
        "num_trades": result.num_trades,
        "win_rate": result.win_rate,
        "avg_win_pct": result.avg_win_pct,
        "avg_loss_pct": result.avg_loss_pct,
        "profit_factor": result.profit_factor,
        "equity_curve": [
            {"date": _ts_label(d), "value": round(float(v), 2)}
            for d, v in result.equity_curve.items()
        ],
        "drawdown_curve": _drawdown_curve(result.equity_curve),
        "trades": [
            {
                "entry_date": _ts_label(t.entry_date),
                "exit_date": _ts_label(t.exit_date),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "pnl": t.pnl,
                "side": t.side,
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }


def run(
    ticker: str,
    strategy: str = "ict_fair_value_gap",
    start: str = "2y",
    end: Optional[str] = None,
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    interval: str = "1d",
    bse: bool = False,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    api_key: Optional[str] = None,
    risk_pct: Optional[float] = None,
) -> BacktestResult:
    if strategy not in STRATEGY_MAP:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Choose: {', '.join(STRATEGY_MAP.keys())}"
        )

    ticker = _resolve_ticker(ticker)
    if bse:
        ticker = ticker.replace(".NS", ".BO")

    ref = None
    if strategy in NEEDS_SMT_REF:
        ref = _load_smt_ref(ticker, start=start, interval=interval, api_key=api_key)
        if ref is None:
            raise ValueError(
                f"Strategy '{strategy}' needs an SMT reference index for {ticker}, "
                f"but no reference series could be fetched."
            )

    df, data_source = fetch_data(ticker, start=start, end=end, interval=interval, api_key=api_key)
    df = add_indicators(df, ref=ref)
    signal_fn = STRATEGY_MAP[strategy]
    return run_backtest(
        df, signal_fn, initial_capital, commission_pct,
        stop_loss_pct, trailing_stop_pct,
        data_source=data_source, risk_pct=risk_pct,
    )


def compare_strategies(
    ticker: str,
    start: str = "1y",
    end: Optional[str] = None,
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    interval: str = "1d",
    bse: bool = False,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    api_key: Optional[str] = None,
    risk_pct: Optional[float] = None,
) -> Dict[str, dict]:
    ticker = _resolve_ticker(ticker)
    if bse:
        ticker = ticker.replace(".NS", ".BO")

    # fetch the SMT reference once, shared by every strategy that needs it
    needs_ref = any(name in NEEDS_SMT_REF for name in STRATEGY_MAP)
    ref = _load_smt_ref(ticker, start=start, interval=interval, api_key=api_key) if needs_ref else None

    df, data_source = fetch_data(ticker, start=start, end=end, interval=interval, api_key=api_key)
    df = add_indicators(df, ref=ref)

    results = {}
    for name, fn in STRATEGY_MAP.items():
        if name in NEEDS_SMT_REF and ref is None:
            results[name] = {
                "error": f"no SMT reference series available for {ticker}"
            }
            continue
        try:
            res = run_backtest(
                df.copy(), fn, initial_capital, commission_pct,
                stop_loss_pct, trailing_stop_pct,
                data_source=data_source, risk_pct=risk_pct,
            )
            results[name] = format_result_json(res)
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


def stock_of_the_day(
    start: str = "1y",
    strategy: str = "ict_fair_value_gap",
    top_n: int = 5,
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    tickers: Optional[List[str]] = None,
    movement_min: Optional[float] = None,
    movement_max: Optional[float] = None,
    api_key: Optional[str] = None,
) -> List[Dict]:
    scan_list = tickers or NIFTY50
    results = []

    def _analyse(t):
        try:
            resolved = _resolve_ticker(t)
            df_1m, _ = fetch_data(resolved, start="1mo", api_key=api_key)
            if len(df_1m) < 2:
                return None
            prev = float(df_1m["Close"].iloc[0])
            curr = float(df_1m["Close"].iloc[-1])
            move_pct = (curr / prev - 1) * 100

            if move_pct is None or np.isnan(move_pct):
                return None
            if movement_min is not None and move_pct < movement_min:
                return None
            if movement_max is not None and move_pct > movement_max:
                return None

            res = run(
                ticker=t, strategy=strategy, start=start,
                initial_capital=initial_capital, commission_pct=commission_pct,
                api_key=api_key,
            )
            if res.num_trades > 0:
                score = (
                    res.sharpe_ratio * 0.3
                    + res.total_return_pct * 0.3
                    + res.win_rate * 0.2
                    + res.profit_factor * 0.2
                )
                return {
                    "ticker": t,
                    "score": round(score, 2),
                    "return": res.total_return_pct,
                    "sharpe": res.sharpe_ratio,
                    "win_rate": res.win_rate,
                    "trades": res.num_trades,
                    "profit_factor": res.profit_factor,
                    "movement_1m": round(move_pct, 2),
                }
        except Exception:
            pass
        return None

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_analyse, t): t for t in scan_list}
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_n]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest ICT trading strategies on Indian Equities")
    parser.add_argument("ticker", nargs="?", help="Stock ticker (e.g. RELIANCE, TCS, ^NSEI)")
    parser.add_argument("--strategy", "-s", default="ict_fair_value_gap",
                        choices=list(STRATEGY_MAP.keys()),
                        help="ICT trading strategy to backtest")
    parser.add_argument("--start", default="1y", help="Start date/period")
    parser.add_argument("--end", help="End date")
    parser.add_argument("--interval", default="1d",
                        help="Bar interval (1d, 4h, 15m, ...; 4h is built from 1h bars)")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--commission", type=float, default=0.001, help="Commission per trade")
    parser.add_argument("--risk", type=float, default=None,
                        help="Risk per trade as %% of equity, sized off the ICT stop (e.g. 1)")
    parser.add_argument("--stop-loss", type=float, help="Stop-loss percentage (e.g. 5 for 5 percent)")
    parser.add_argument("--trailing-stop", type=float, help="Trailing stop percentage")
    parser.add_argument("--api-key", help="INDstocks / INDmoney API access token")
    parser.add_argument("--bse", action="store_true", help="Use BSE instead of NSE")
    parser.add_argument("--compare", "-c", action="store_true", help="Compare all strategies")
    parser.add_argument("--stock-of-day", "-d", action="store_true", help="Find stock of the day")
    parser.add_argument("--list-strategies", "-l", action="store_true", help="List strategies")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")

    args = parser.parse_args()

    if args.list_strategies:
        print("Available ICT strategies:")
        for name, desc in example_strategies().items():
            print(f"  {name}: {desc}")
        exit(0)

    if args.stock_of_day:
        top = stock_of_the_day(start=args.start, strategy=args.strategy or "ict_fair_value_gap", api_key=args.api_key)
        if args.json:
            print(json.dumps(top, indent=2))
        else:
            print(f"{'Stock of the Day':=^60}")
            for i, s in enumerate(top, 1):
                print(f"  {i}. {s['ticker']} — Score: {s['score']} | Return: {s['return']:+}% | Sharpe: {s['sharpe']} | Win: {s['win_rate']}%")
        exit(0)

    if not args.ticker:
        parser.print_help()
        exit(1)

    if args.compare:
        results = compare_strategies(
            ticker=args.ticker, start=args.start, end=args.end,
            initial_capital=args.capital, commission_pct=args.commission,
            interval=args.interval,
            bse=args.bse, stop_loss_pct=args.stop_loss, trailing_stop_pct=args.trailing_stop,
            api_key=args.api_key, risk_pct=args.risk,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"{'Strategy Comparison for ' + args.ticker.upper():=^60}")
            print(f"{'Strategy':<32} {'Return':>8} {'Sharpe':>8} {'Win%':>7} {'Trades':>7} {'Pf':>7}")
            print("-" * 75)
            for name, r in results.items():
                if "error" in r:
                    print(f"{name:<32} {'ERROR':>8}")
                else:
                    print(f"{name:<32} {r['total_return_pct']:>+7.2f}% {r['sharpe_ratio']:>7.2f} {r['win_rate']:>6.1f}% {r['num_trades']:>6d} {r['profit_factor']:>6.2f}")
        exit(0)

    result = run(
        ticker=args.ticker,
        strategy=args.strategy,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
        commission_pct=args.commission,
        interval=args.interval,
        bse=args.bse,
        stop_loss_pct=args.stop_loss,
        trailing_stop_pct=args.trailing_stop,
        api_key=args.api_key,
        risk_pct=args.risk,
    )

    if args.json:
        print(json.dumps(format_result_json(result), indent=2))
    else:
        print(format_result(result, args.ticker))
