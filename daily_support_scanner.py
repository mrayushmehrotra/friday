"""
Daily Support Level Scanner & Analyzer
Identifies high-quality stocks in healthy broader trends that have just pulled back
and landed right onto key daily support levels using INDmoney API (or Yahoo Finance fallback).

Key Support Levels Detected:
1. Institutional Dynamic Moving Averages (50-Day SMA, 200-Day SMA, 100-Day SMA, 20-Day EMA)
2. Horizontal Multi-Touch Structural Support Pivots (Swing Lows over 3-12 months)
3. Breakout Retest / Prior Resistance Turned Support (S/R Polarity Flip)
4. Smart Money Concepts (SMC): Daily Bullish Order Blocks (Demand Zones) & Bullish Fair Value Gaps (FVG)
5. Golden Confluence Zones (alignment of multiple support types within 1-1.5%)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

try:
    from stock_tools import normalize_symbol
except ImportError:  # pragma: no cover - standalone fallback
    _LEGACY_SYMBOLS = {"ZOMATO": "ETERNAL", "TATAMOTORS": "TMPV"}

    def normalize_symbol(ticker: str) -> str:
        return _LEGACY_SYMBOLS.get((ticker or "").strip().upper(), (ticker or "").strip().upper())


try:
    from backtest_tools import (
        INDSTOCKS_SECURITY_IDS,
        NIFTY50,
        fetch_data,
        fetch_indstocks_data,
        resolve_indstocks_scrip,
    )
except ImportError:
    NIFTY50 = [
        "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR",
        "BHARTIARTL", "SBIN", "ITC", "LT", "KOTAKBANK", "BAJFINANCE",
        "WIPRO", "AXISBANK", "ADANIENT", "MARUTI", "TITAN", "ASIANPAINT",
        "HCLTECH", "ULTRACEMCO", "NTPC", "ONGC", "POWERGRID", "SUNPHARMA",
        "BAJAJFINSV", "JSWSTEEL", "HINDALCO", "TATASTEEL", "ADANIPORTS",
        "GRASIM", "BRITANNIA", "DIVISLAB", "DRREDDY", "CIPLA", "APOLLOHOSP",
        "NESTLEIND", "COALINDIA", "BPCL", "SBILIFE", "EICHERMOT", "M&M",
        "HDFCLIFE", "TATACONSUM", "BAJAJ-AUTO", "INDUSINDBK", "HEROMOTOCO",
        "TRENT", "BEL",
    ]
    fetch_data = None
    fetch_indstocks_data = None
    resolve_indstocks_scrip = None

try:
    from vcp_scanner import DEFAULT_SWING_UNIVERSE
except ImportError:
    DEFAULT_SWING_UNIVERSE = [
        "TRENT", "DIXON", "POLYCAB", "KAYNES", "PERSISTENT", "COFORGE",
        "BSE", "CDSL", "ANGELONE", "MOTILALOFS", "SUZLON", "MAXHEALTH",
        "TATACOMM", "APOLLOHOSP", "SHRIRAMFIN", "FEDERALBNK", "INDUSINDBK",
        "TECHM", "WIPRO",
    ]


@dataclass
class SupportLevel:
    type: str               # "SMA_50", "SMA_200", "SMA_100", "EMA_20", "HORIZONTAL_SWING", "BREAKOUT_RETEST", "ORDER_BLOCK", "FVG"
    label: str              # e.g. "50-Day SMA", "Horizontal Pivot (3 touches)"
    price: float            # support price level
    dist_pct: float         # percentage distance from current LTP: ((LTP - price) / price) * 100
    touches: int = 1        # historical test touches
    date_formed: str = ""   # date formed or last tested
    strength: int = 3       # 1 to 5 rating
    zone_low: float = 0.0   # zone bottom (for ranges/order blocks)
    zone_high: float = 0.0  # zone top


@dataclass
class DailySupportMatch:
    ticker: str
    symbol: str
    company_name: str
    ltp: float
    change_pct: float
    high_today: float
    low_today: float
    volume: float
    volume_ratio: float     # today's volume / 20-day avg volume
    data_source: str

    # Quality & Trend
    is_good_stock: bool
    quality_score: int      # 0 to 100
    quality_rating: str     # "⭐⭐⭐⭐⭐ Elite", "⭐⭐⭐⭐ Strong", etc.
    stage2_trend: bool
    dist_from_52w_high: float
    dist_from_52w_low: float
    sma50: float
    sma200: float

    # Pullback context
    pullback_3d_pct: float  # 3-day change %
    pullback_from_peak: float # drop % from highest high of last 10 bars

    # Support Analysis
    landed_on_support: bool
    primary_support: Dict[str, Any]
    all_supports: List[Dict[str, Any]]
    has_confluence: bool
    confluence_count: int
    confluence_notes: str

    # Candle reaction at support
    candle_reaction: str    # "HAMMER_WICK_REJECTION", "GREEN_REBOUND", "DOJI_BASING", "TESTING_SUPPORT"
    candle_reaction_label: str
    lower_wick_pct: float   # lower wick as % of candle range

    # Trade Planning
    suggested_entry: float
    stop_loss: float
    stop_loss_pct: float
    target_1: float
    target_1_pct: float
    target_2: float
    target_2_pct: float
    risk_reward_ratio: float


def load_universe_symbols(universe: str = "nifty50") -> List[str]:
    """Return cleaned symbol list for requested universe."""
    u = universe.lower().strip()
    if u in ("nifty50", "nifty_50", "bluechip"):
        return list(dict.fromkeys(NIFTY50))

    if u in ("fno", "options"):
        fno_json = os.path.join(HERE, "assets", "stocks_with_options.json")
        if os.path.exists(fno_json):
            try:
                with open(fno_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    stocks = data.get("stocks", [])
                    syms = [s["symbol"] for s in stocks if s.get("symbol")]
                    if syms:
                        return list(dict.fromkeys(syms))
            except Exception:
                pass

    if u in ("swing", "growth"):
        syms = list(dict.fromkeys(NIFTY50[:25] + (DEFAULT_SWING_UNIVERSE or [])))
        return syms

    if u in ("nifty100", "nifty_100", "all"):
        # Combine NIFTY50 and swing universe + additional prominent symbols
        extra = [
            "ABB", "ADANIENSOL", "AMBUJACEM", "BANKBARODA", "BOSCHLTD", "CANBK",
            "CHOLAFIN", "DLF", "GAIL", "HAVELLS", "ICICIGI", "ICICIPRULI",
            "INDIGO", "IOC", "IRCTC", "JINDALSTEL", "LICI", "LTIM", "MOTHERSON",
            "NAUKRI", "PIDILITIND", "PNB", "RECLTD", "SHRIRAMFIN", "SIEMENS",
            "TATACOMM", "TATAMTRDVR", "TATAPOWER", "TVSMOTOR", "UNITDSPR",
            "VEDL", "ETERNAL"
        ]
        return list(dict.fromkeys(NIFTY50 + extra))

    return list(dict.fromkeys(NIFTY50))


def fetch_daily_chart(
    ticker: str,
    api_key: Optional[str] = None,
    period: str = "1y",
) -> Tuple[Optional[pd.DataFrame], str]:
    """Fetch daily candles from INDstocks API or fallback to Yahoo Finance."""
    clean_sym = normalize_symbol(ticker.replace(".NS", "").replace(".BO", "").strip().upper())
    resolved = clean_sym if clean_sym.endswith(".NS") or clean_sym.startswith("^") else f"{clean_sym}.NS"

    # 1. Try project's fetch_data (which queries INDstocks API if token is provided)
    if fetch_data is not None:
        try:
            df, src = fetch_data(resolved, start=period, interval="1d", api_key=api_key)
            if df is not None and len(df) >= 20:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df, src
        except Exception:
            pass

    # 2. Try direct fetch_indstocks_data if scrip can be resolved
    if api_key and api_key.strip() and fetch_indstocks_data is not None and resolve_indstocks_scrip is not None:
        try:
            scrip = resolve_indstocks_scrip(clean_sym, api_key.strip())
            if scrip:
                df = fetch_indstocks_data(scrip, api_key.strip(), interval="1day", days=365)
                if df is not None and len(df) >= 20:
                    return df, "INDstocks API (Direct Token)"
        except Exception:
            pass

    # 3. Direct Yahoo finance fallback
    try:
        df = yf.download(resolved, period=period, interval="1d", progress=False)
        if df is not None and not df.empty and len(df) >= 20:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df, "Yahoo Finance"
    except Exception:
        pass

    return None, "None"


def detect_swing_pivots(
    lows: pd.Series,
    highs: pd.Series,
    order: int = 3,
    lookback_bars: int = 200,
) -> Tuple[List[Tuple[int, float, str]], List[Tuple[int, float, str]]]:
    """Find local swing lows and swing highs over the specified lookback window."""
    n = len(lows)
    start_i = max(0, n - lookback_bars)
    swing_lows: List[Tuple[int, float, str]] = []
    swing_highs: List[Tuple[int, float, str]] = []

    # Exclude the very last bar (so support is proven prior history)
    for i in range(start_i + order, n - 1):
        l_i = float(lows.iloc[i])
        h_i = float(highs.iloc[i])
        dt_str = str(lows.index[i]).split(" ")[0]

        is_l = all(l_i <= float(lows.iloc[i - k]) and l_i <= float(lows.iloc[i + k])
                   for k in range(1, min(order + 1, n - i)))
        is_h = all(h_i >= float(highs.iloc[i - k]) and h_i >= float(highs.iloc[i + k])
                   for k in range(1, min(order + 1, n - i)))

        if is_l:
            swing_lows.append((i, l_i, dt_str))
        if is_h:
            swing_highs.append((i, h_i, dt_str))

    return swing_lows, swing_highs


def cluster_price_levels(
    levels: List[Tuple[int, float, str]],
    tolerance_pct: float = 1.3,
) -> List[Tuple[float, int, str]]:
    """Cluster raw price points within tolerance into support clusters (price, touches, last_date)."""
    if not levels:
        return []

    # Sort ascending by price
    sorted_lvls = sorted(levels, key=lambda x: x[1])
    clusters: List[List[Tuple[int, float, str]]] = []

    for item in sorted_lvls:
        if not clusters:
            clusters.append([item])
            continue
        # Check against average of current cluster
        curr_cluster = clusters[-1]
        cluster_avg = sum(x[1] for x in curr_cluster) / len(curr_cluster)
        if abs(item[1] - cluster_avg) / cluster_avg * 100 <= tolerance_pct:
            curr_cluster.append(item)
        else:
            clusters.append([item])

    result = []
    for c in clusters:
        avg_price = sum(x[1] for x in c) / len(c)
        touches = len(c)
        last_dt = max(c, key=lambda x: x[0])[2]
        result.append((round(avg_price, 2), touches, last_dt))

    return result


def detect_bullish_order_blocks(
    df: pd.DataFrame,
    lookback: int = 120,
) -> List[Tuple[float, float, str, float]]:
    """Detect SMC Daily Bullish Order Blocks.

    A bullish order block is the last down candle before an impulsive rally
    that broke market structure (made a higher high over previous 5-10 bars).
    Returns list of (zone_low, zone_high, date, displacement_pct).
    """
    n = len(df)
    if n < 20:
        return []

    c = df["Close"].astype(float)
    o = df["Open"].astype(float)
    h = df["High"].astype(float)
    l = df["Low"].astype(float)
    current_ltp = float(c.iloc[-1])

    order_blocks = []
    start_bar = max(10, n - lookback)

    for i in range(start_bar, n - 2):
        # Down candle followed by aggressive displacement upward
        is_down = c.iloc[i] < o.iloc[i]
        if not is_down:
            continue

        # Look at subsequent 1-3 bars for impulsive upside breakout
        next_high = h.iloc[i+1 : min(n, i+4)].max()
        prior_high = h.iloc[max(0, i-6) : i].max()

        if next_high > prior_high * 1.01:
            displacement = (next_high / prior_high - 1) * 100
            ob_low = float(l.iloc[i])
            ob_high = float(o.iloc[i])  # or high
            dt = str(df.index[i]).split(" ")[0]

            # If current price hasn't violated below the OB low
            if current_ltp >= ob_low * 0.985:
                order_blocks.append((ob_low, ob_high, dt, displacement))

    return order_blocks[-5:]  # most recent 5


def detect_breakout_retests(
    df: pd.DataFrame,
    swing_highs: List[Tuple[int, float, str]],
    current_price: float,
) -> List[Tuple[float, str]]:
    """Detect prior swing highs (resistances) that were broken out and now being retested."""
    c = df["Close"].astype(float)
    h = df["High"].astype(float)
    retests = []

    for idx, sh_val, dt in swing_highs:
        # Check if subsequent price broke decisively above this resistance
        subsequent_closes = c.iloc[idx + 1 :]
        if len(subsequent_closes) >= 3 and subsequent_closes.max() > sh_val * 1.025:
            # Broke out! Now check if current price is pulling back right to this level
            dist = (current_price - sh_val) / sh_val * 100
            if -1.0 <= dist <= 2.5:
                retests.append((sh_val, dt))

    return retests


def analyze_daily_support(
    ticker: str,
    api_key: Optional[str] = None,
    max_support_dist_pct: float = 2.0,
    df_daily: Optional[pd.DataFrame] = None,
    data_src: Optional[str] = None,
) -> Optional[DailySupportMatch]:
    """Perform full daily support analysis on a single stock using daily candles.

    Returns DailySupportMatch if analyzed, or None if insufficient data.
    """
    clean_sym = normalize_symbol(ticker.replace(".NS", "").replace(".BO", "").strip().upper())

    if df_daily is None:
        df, src = fetch_daily_chart(clean_sym, api_key=api_key)
    else:
        df = df_daily
        src = data_src or "Cached"

    if df is None or len(df) < 40:
        return None

    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    open_p = df["Open"].astype(float)
    volume = df["Volume"].astype(float) if "Volume" in df.columns else pd.Series(0, index=df.index)

    n = len(df)
    ltp = float(close.iloc[-1])
    low_today = float(low.iloc[-1])
    high_today = float(high.iloc[-1])
    open_today = float(open_p.iloc[-1])
    prev_close = float(close.iloc[-2]) if n >= 2 else ltp

    change_pct = round(((ltp - prev_close) / prev_close) * 100, 2)
    today_vol = float(volume.iloc[-1]) if len(volume) else 0.0
    avg_vol_20 = float(volume.iloc[-21:-1].mean()) if len(volume) >= 22 else (today_vol or 1.0)
    vol_ratio = round(today_vol / (avg_vol_20 or 1.0), 2)

    # ── 1. Moving Averages ──
    sma50_s = close.rolling(50, min_periods=25).mean()
    sma200_s = close.rolling(200, min_periods=50).mean()
    sma100_s = close.rolling(100, min_periods=35).mean()
    ema20_s = close.ewm(span=20, adjust=False).mean()

    sma50 = float(sma50_s.iloc[-1]) if len(sma50_s) else np.nan
    sma200 = float(sma200_s.iloc[-1]) if len(sma200_s) else np.nan
    sma100 = float(sma100_s.iloc[-1]) if len(sma100_s) else np.nan
    ema20 = float(ema20_s.iloc[-1]) if len(ema20_s) else np.nan

    # ── 2. Quality & Trend Template (Is it a "Good Stock"?) ──
    h52 = float(high.max()) if len(high) else ltp
    l52 = float(low.min()) if len(low) else ltp
    dist_52w_high = round(((h52 - ltp) / (h52 or 1)) * 100, 2)
    dist_52w_low = round(((ltp - l52) / (l52 or 1)) * 100, 2)

    above_200 = ltp >= sma200 * 0.96 if not np.isnan(sma200) else True
    golden_structure = (sma50 >= sma200 * 0.97) if (not np.isnan(sma50) and not np.isnan(sma200)) else True
    not_penny_crash = dist_52w_low >= 15.0
    near_highs = dist_52w_high <= 38.0

    stage2_trend = bool(above_200 and golden_structure and not_penny_crash and near_highs)

    # Calculate Quality Score (0 to 100)
    q_score = 40  # base
    if stage2_trend:
        q_score += 25
    if not np.isnan(sma200) and ltp >= sma200:
        q_score += 15
    if dist_52w_high <= 20.0:
        q_score += 10
    if vol_ratio >= 0.8:
        q_score += 10

    q_score = min(100, max(10, q_score))
    if q_score >= 80:
        q_rating = "⭐⭐⭐⭐⭐ Elite Bluechip"
    elif q_score >= 65:
        q_rating = "⭐⭐⭐⭐ Strong Leader"
    elif q_score >= 50:
        q_rating = "⭐⭐⭐ Sound Quality"
    else:
        q_rating = "⭐⭐ Speculative"

    is_good_stock = (q_score >= 45)

    # ── 3. Pullback Context ──
    pullback_3d = round(((ltp / close.iloc[-4] - 1) * 100), 2) if n >= 4 else change_pct
    recent_10_high = float(high.iloc[-10:].max()) if n >= 10 else high_today
    pullback_from_peak = round(((recent_10_high - ltp) / recent_10_high) * 100, 2)

    # ── 4. Collect Daily Support Levels ──
    supports: List[SupportLevel] = []

    # A. 50-day SMA
    if not np.isnan(sma50):
        dist_s50 = ((ltp - sma50) / sma50) * 100
        supports.append(SupportLevel(
            type="SMA_50",
            label="50-Day SMA",
            price=round(sma50, 2),
            dist_pct=round(dist_s50, 2),
            strength=4,
        ))

    # B. 200-day SMA
    if not np.isnan(sma200):
        dist_s200 = ((ltp - sma200) / sma200) * 100
        supports.append(SupportLevel(
            type="SMA_200",
            label="200-Day SMA",
            price=round(sma200, 2),
            dist_pct=round(dist_s200, 2),
            strength=5,
        ))

    # C. 100-day SMA
    if not np.isnan(sma100):
        dist_s100 = ((ltp - sma100) / sma100) * 100
        supports.append(SupportLevel(
            type="SMA_100",
            label="100-Day SMA",
            price=round(sma100, 2),
            dist_pct=round(dist_s100, 2),
            strength=3,
        ))

    # D. 20-day EMA
    if not np.isnan(ema20):
        dist_e20 = ((ltp - ema20) / ema20) * 100
        supports.append(SupportLevel(
            type="EMA_20",
            label="20-Day EMA",
            price=round(ema20, 2),
            dist_pct=round(dist_e20, 2),
            strength=3,
        ))

    # E. Horizontal Swing Low Pivots
    raw_swing_lows, raw_swing_highs = detect_swing_pivots(low, high, order=3, lookback_bars=180)
    clusters = cluster_price_levels(raw_swing_lows, tolerance_pct=1.4)
    for c_price, touches, last_dt in clusters:
        dist_sw = ((ltp - c_price) / c_price) * 100
        # Only interested if support is below or within reach
        if -2.0 <= dist_sw <= 12.0:
            lbl = f"Horizontal Pivot ({touches} touch{'es' if touches > 1 else ''})"
            strength = min(5, 2 + touches)
            supports.append(SupportLevel(
                type="HORIZONTAL_SWING",
                label=lbl,
                price=round(c_price, 2),
                dist_pct=round(dist_sw, 2),
                touches=touches,
                date_formed=last_dt,
                strength=strength,
            ))

    # F. Breakout Retest (S/R Polarity Flip)
    retests = detect_breakout_retests(df, raw_swing_highs, ltp)
    for r_price, dt in retests:
        dist_r = ((ltp - r_price) / r_price) * 100
        supports.append(SupportLevel(
            type="BREAKOUT_RETEST",
            label=f"Breakout Retest (Prior Peak {dt})",
            price=round(r_price, 2),
            dist_pct=round(dist_r, 2),
            touches=1,
            date_formed=dt,
            strength=4,
        ))

    # G. SMC Bullish Order Blocks (Demand Zones)
    order_blocks = detect_bullish_order_blocks(df, lookback=100)
    for ob_low, ob_high, ob_dt, disp in order_blocks:
        dist_ob = ((ltp - ob_high) / ob_high) * 100
        # If price is near or within zone
        if -1.5 <= dist_ob <= 3.5:
            supports.append(SupportLevel(
                type="ORDER_BLOCK",
                label=f"SMC Bullish Order Block ({ob_dt})",
                price=round(ob_high, 2),
                dist_pct=round(dist_ob, 2),
                strength=4,
                zone_low=round(ob_low, 2),
                zone_high=round(ob_high, 2),
                date_formed=ob_dt,
            ))

    # ── 5. Landing on Support Detection ──
    # Has the stock landed on / tested any of these support levels?
    # Criteria: dist_pct is between -0.8% and +1.8% (or low_today tested within 0.8% of support)
    landing_supports: List[SupportLevel] = []
    for s in supports:
        # Check current price proximity
        in_ltp_range = (-0.85 <= s.dist_pct <= max_support_dist_pct)
        # Check if today's low touched support and bounced
        low_dist = ((low_today - s.price) / s.price) * 100
        in_low_touch = (-1.2 <= low_dist <= 0.6 and ltp >= s.price * 0.99)

        if in_ltp_range or in_low_touch:
            landing_supports.append(s)

    landed = len(landing_supports) > 0

    # Pick the best primary support (closest or highest strength)
    landing_supports.sort(key=lambda x: (abs(x.dist_pct), -x.strength))
    primary_s = landing_supports[0] if landing_supports else (
        sorted(supports, key=lambda x: abs(x.dist_pct))[0] if supports else None
    )

    if not primary_s:
        return None

    # Check for Golden Confluence (multiple supports within 1.2% of primary support)
    confluence_list = [
        s for s in supports
        if abs(s.price - primary_s.price) / primary_s.price * 100 <= 1.3 and s.type != primary_s.type
    ]
    has_confluence = len(confluence_list) >= 1
    conf_notes = ""
    if has_confluence:
        types_str = " + ".join([primary_s.label] + [c.label for c in confluence_list[:2]])
        conf_notes = f"Golden Confluence: {types_str} all aligned at ₹{primary_s.price:,.2f}"

    # ── 6. Candle Reaction at Support ──
    candle_range = high_today - low_today or 0.01
    body = abs(ltp - open_today)
    lower_wick = (min(ltp, open_today) - low_today)
    lower_wick_ratio = round((lower_wick / candle_range) * 100, 1)

    is_green = (ltp >= open_today)
    is_hammer = (lower_wick >= 1.5 * body) and (lower_wick_ratio >= 45.0)

    if is_hammer:
        reaction = "HAMMER_WICK_REJECTION"
        reaction_label = "🔨 Bullish Hammer / Lower Wick Absorption"
    elif is_green and change_pct >= 0.4:
        reaction = "GREEN_REBOUND"
        reaction_label = "🟢 Green Rebound off Support"
    elif body / candle_range <= 0.25:
        reaction = "DOJI_BASING"
        reaction_label = "⚪ Doji / Seller Exhaustion at Support"
    elif abs(primary_s.dist_pct) <= 0.7:
        reaction = "TESTING_SUPPORT"
        reaction_label = "🎯 Direct Test of Daily Support"
    else:
        reaction = "APPROACHING_SUPPORT"
        reaction_label = "📉 Pulling Back towards Support"

    # ── 7. Trade Planning & Risk-Reward ──
    support_val = primary_s.price
    sl_buffer = 0.018  # 1.8% below support
    suggested_sl = round(min(low_today * 0.995, support_val * (1.0 - sl_buffer)), 2)
    sl_dist_pct = round(((ltp - suggested_sl) / ltp) * 100, 2)

    # Target 1: Recent 10-day high or 20 EMA
    t1 = round(max(recent_10_high, ltp * 1.045), 2)
    t1_pct = round(((t1 - ltp) / ltp) * 100, 2)

    # Target 2: 52-week high or 2.5x risk
    t2 = round(max(h52 * 0.98, ltp + (ltp - suggested_sl) * 2.8), 2)
    t2_pct = round(((t2 - ltp) / ltp) * 100, 2)

    rr = round(t1_pct / (sl_dist_pct or 0.1), 1)

    return DailySupportMatch(
        ticker=f"{clean_sym}.NS",
        symbol=clean_sym,
        company_name=clean_sym,
        ltp=round(ltp, 2),
        change_pct=change_pct,
        high_today=round(high_today, 2),
        low_today=round(low_today, 2),
        volume=today_vol,
        volume_ratio=vol_ratio,
        data_source=src,
        is_good_stock=is_good_stock,
        quality_score=q_score,
        quality_rating=q_rating,
        stage2_trend=stage2_trend,
        dist_from_52w_high=dist_52w_high,
        dist_from_52w_low=dist_52w_low,
        sma50=round(sma50, 2) if not np.isnan(sma50) else 0.0,
        sma200=round(sma200, 2) if not np.isnan(sma200) else 0.0,
        pullback_3d_pct=pullback_3d,
        pullback_from_peak=pullback_from_peak,
        landed_on_support=landed,
        primary_support=asdict(primary_s),
        all_supports=[asdict(s) for s in supports],
        has_confluence=has_confluence,
        confluence_count=len(confluence_list) + 1 if has_confluence else 1,
        confluence_notes=conf_notes,
        candle_reaction=reaction,
        candle_reaction_label=reaction_label,
        lower_wick_pct=lower_wick_ratio,
        suggested_entry=round(ltp, 2),
        stop_loss=suggested_sl,
        stop_loss_pct=sl_dist_pct,
        target_1=t1,
        target_1_pct=t1_pct,
        target_2=t2,
        target_2_pct=t2_pct,
        risk_reward_ratio=rr,
    )


def scan_daily_support_universe(
    universe: str = "nifty50",
    api_key: Optional[str] = None,
    max_support_dist_pct: float = 2.0,
    only_good_stocks: bool = True,
    max_workers: int = 12,
    progress_cb=None,
    on_match_cb=None,
) -> Dict[str, Any]:
    """Scan a universe of stocks and return those that landed on daily support."""
    symbols = load_universe_symbols(universe)
    total = len(symbols)
    results: List[Dict[str, Any]] = []
    confluence_picks: List[Dict[str, Any]] = []
    hammer_picks: List[Dict[str, Any]] = []
    scanned = 0

    clean_key = (api_key or "").strip() or os.getenv("INDMONEY_API_TOKEN") or None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                analyze_daily_support,
                sym,
                api_key=clean_key,
                max_support_dist_pct=max_support_dist_pct,
            ): sym
            for sym in symbols
        }

        for fut in as_completed(futures):
            sym = futures[fut]
            scanned += 1
            if progress_cb:
                progress_cb(scanned, total)

            try:
                res = fut.result()
                if not res:
                    continue

                # Filter: must have landed on support, and optionally be a good stock
                if res.landed_on_support and (not only_good_stocks or res.is_good_stock):
                    d = asdict(res)
                    results.append(d)
                    if res.has_confluence:
                        confluence_picks.append(d)
                    if res.candle_reaction == "HAMMER_WICK_REJECTION":
                        hammer_picks.append(d)

                    if on_match_cb:
                        on_match_cb(d)
            except Exception:
                pass

    # Sort results by confluence, quality score, and tightness to support
    results.sort(
        key=lambda x: (
            not x["has_confluence"],
            -x["quality_score"],
            abs(x["primary_support"]["dist_pct"]),
        )
    )
    confluence_picks.sort(key=lambda x: (-x["quality_score"], abs(x["primary_support"]["dist_pct"])))
    hammer_picks.sort(key=lambda x: (-x["quality_score"], abs(x["primary_support"]["dist_pct"])))

    return {
        "universe": universe,
        "total_scanned": scanned,
        "matches_count": len(results),
        "confluence_count": len(confluence_picks),
        "hammer_count": len(hammer_picks),
        "picks": results,
        "confluence_picks": confluence_picks,
        "hammer_picks": hammer_picks,
    }


def get_chart_series(
    ticker: str,
    api_key: Optional[str] = None,
    bars: int = 90,
) -> Dict[str, Any]:
    """Return historical daily OHLCV series for lightweight canvas chart rendering."""
    df, src = fetch_daily_chart(ticker, api_key=api_key)
    if df is None or len(df) < 10:
        return {"error": f"No chart data available for {ticker}"}

    df_slice = df.iloc[-bars:]
    candles = []
    for dt, row in df_slice.iterrows():
        candles.append({
            "date": str(dt).split(" ")[0],
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": float(row.get("Volume", 0)),
        })

    # Run support analysis to get overlay lines
    analysis = analyze_daily_support(ticker, api_key=api_key, df_daily=df, data_src=src)
    analysis_dict = asdict(analysis) if analysis else None

    return {
        "ticker": ticker.upper(),
        "source": src,
        "candles": candles,
        "analysis": analysis_dict,
    }


# ── Global Cache & Background Scan State for Web Server ──────────────────────
_SUPPORT_LOCK = __import__("threading").Lock()
_SUPPORT_STATES: Dict[str, Dict[str, Any]] = {}
_SUPPORT_TTL = 300  # 5 minutes cache


def get_cached_or_scan_support(
    universe: str = "nifty50",
    refresh: bool = False,
    api_key: Optional[str] = None,
    max_dist: float = 2.0,
) -> Dict[str, Any]:
    """Retrieve cached scan results or start background universe scanner."""
    clean_key = (api_key or "").strip() or os.getenv("INDMONEY_API_TOKEN") or None
    state_key = f"{universe}_{clean_key or 'default'}_{max_dist}"

    with _SUPPORT_LOCK:
        if state_key not in _SUPPORT_STATES:
            _SUPPORT_STATES[state_key] = {
                "running": False,
                "scanned": 0,
                "total": 0,
                "started": 0,
                "finished": 0,
                "error": None,
                "results": None,
                "confluence": [],
                "hammers": [],
            }

        st = _SUPPORT_STATES[state_key]
        now = time.time()
        fresh = (st["results"] is not None and st["finished"] and (now - st["finished"] < _SUPPORT_TTL))

        if not fresh or refresh:
            if not st["running"]:
                st.update(
                    running=True,
                    scanned=0,
                    total=len(load_universe_symbols(universe)),
                    started=now,
                    error=None,
                    results=[],
                    confluence=[],
                    hammers=[],
                )

                def _bg_scan():
                    try:
                        def _prog(sc, tot):
                            with _SUPPORT_LOCK:
                                _SUPPORT_STATES[state_key]["scanned"] = sc
                                _SUPPORT_STATES[state_key]["total"] = tot

                        def _on_match(item):
                            with _SUPPORT_LOCK:
                                current_res = _SUPPORT_STATES[state_key]["results"]
                                if current_res is None:
                                    current_res = []
                                    _SUPPORT_STATES[state_key]["results"] = current_res
                                if not any(x["symbol"] == item["symbol"] for x in current_res):
                                    current_res.append(item)
                                    current_res.sort(
                                        key=lambda x: (
                                            not x["has_confluence"],
                                            -x["quality_score"],
                                            abs(x["primary_support"]["dist_pct"]),
                                        )
                                    )
                                    if item.get("has_confluence"):
                                        _SUPPORT_STATES[state_key]["confluence"].append(item)
                                    if item.get("candle_reaction") == "HAMMER_WICK_REJECTION":
                                        _SUPPORT_STATES[state_key]["hammers"].append(item)

                        res = scan_daily_support_universe(
                            universe=universe,
                            api_key=clean_key,
                            max_support_dist_pct=max_dist,
                            progress_cb=_prog,
                            on_match_cb=_on_match,
                        )
                        with _SUPPORT_LOCK:
                            _SUPPORT_STATES[state_key].update(
                                running=False,
                                finished=time.time(),
                                results=res["picks"],
                                confluence=res["confluence_picks"],
                                hammers=res["hammer_picks"],
                            )
                    except Exception as ex:
                        with _SUPPORT_LOCK:
                            _SUPPORT_STATES[state_key].update(
                                running=False,
                                finished=time.time(),
                                error=str(ex),
                            )

                __import__("threading").Thread(target=_bg_scan, daemon=True).start()

    with _SUPPORT_LOCK:
        st_copy = dict(_SUPPORT_STATES[state_key])

    age = (time.time() - st_copy["finished"]) if st_copy["finished"] else None
    return {
        "universe": universe,
        "api_key_active": bool(clean_key),
        "scanning": st_copy["running"],
        "scanned": st_copy["scanned"],
        "total": st_copy["total"],
        "error": st_copy["error"],
        "picks": st_copy["results"] or [],
        "confluence_picks": st_copy.get("confluence", []),
        "hammer_picks": st_copy.get("hammers", []),
        "cache_age_sec": round(age) if age is not None else None,
    }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()

    parser = argparse.ArgumentParser(description="Daily Support Level Scanner")
    parser.add_argument("--ticker", type=str, default="", help="Single ticker to analyze (e.g. HCLTECH)")
    parser.add_argument("--universe", type=str, default="nifty50", help="Universe to scan (nifty50, nifty100, fno, swing)")
    parser.add_argument("--api-key", type=str, default="", help="INDmoney API Token")
    parser.add_argument("--max-dist", type=float, default=2.0, help="Max distance percent to support")
    args = parser.parse_args()

    token = args.api_key.strip() or os.getenv("INDMONEY_API_TOKEN")

    if args.ticker:
        print(f"Analyzing {args.ticker} on Daily Chart...")
        match = analyze_daily_support(args.ticker, api_key=token, max_support_dist_pct=args.max_dist)
        if match:
            print(json.dumps(asdict(match), indent=2))
        else:
            print(f"Could not analyze {args.ticker} or no data.")
    else:
        print(f"Scanning {args.universe} universe for stocks on daily support...")
        t0 = time.time()
        res = scan_daily_support_universe(args.universe, api_key=token, max_support_dist_pct=args.max_dist)
        print(f"Done in {time.time()-t0:.2f}s! Found {res['matches_count']} stocks on daily support.")
        for p in res["picks"][:10]:
            print(f"- {p['symbol']:10s} LTP: {p['ltp']:7.1f} | Support: {p['primary_support']['label']} @ {p['primary_support']['price']:.1f} ({p['primary_support']['dist_pct']:+.2f}%) | {p['quality_rating']} | {p['candle_reaction_label']}")
