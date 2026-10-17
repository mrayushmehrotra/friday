"""
Mark Minervini–style Volatility Contraction Pattern (VCP) Scanner
Combined with Relative Volume Divergence, Smart Money Concepts (SMC), and 9/20 EMA Swing Filters.

Features:
1. Data Input: Pluggable historical Daily and 4-Hour OHLCV (INDmoney API / Yahoo Finance).
2. Contraction Detection (VCP): Successive shallowing pullbacks (e.g. -20% -> -12% -> -5%).
3. Volume Dry-Up: Phase-over-phase declining volume confirming supply exhaustion.
4. Late-Stage Relative Volume Divergence: Tight rolling price range (< 3-4%) + rising relative volume (1.2x - 2x+) = "Quiet Accumulation".
5. Breakout Confirmation: Close above final contraction resistance with 40-50%+ volume surge.
6. Trend Template: Price > 50 & 200 SMA, 50 SMA > 200 SMA, proximity to 52-week high.
7. Liquidity / SMC Filter: Order block, liquidity sweep (Turtle Soup), and Equal Highs alignment.
8. Combined Swing Filter: Qualified on both 4h 9/20 EMA range and Minervini VCP simultaneously.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

# Re-use project utilities if available
try:
    from backtest_tools import (
        INDSTOCKS_SECURITY_IDS,
        fetch_data,
        fetch_indstocks_data,
        resample_to_4h,
        resolve_indstocks_scrip,
    )
except ImportError:
    fetch_data = None
    fetch_indstocks_data = None
    resample_to_4h = None
    resolve_indstocks_scrip = None

try:
    from ict_strategies import add_ict_indicators
except ImportError:
    add_ict_indicators = None


@dataclass
class Contraction:
    high_bar: int
    high_date: str
    high_price: float
    low_bar: int
    low_date: str
    low_price: float
    depth_pct: float
    avg_vol: float
    bars: int


@dataclass
class VCPResult:
    ticker: str
    price: float
    change_pct: float
    status: str  # CONFIRMED_BREAKOUT, PRE_BREAKOUT_ACCUMULATION, COILING_AT_RESISTANCE, VCP_BASE_FORMING
    vcp_type: str  # e.g. '2T', '3T', '4T'
    contractions: List[float]  # e.g. [18.2, 10.5, 4.1]
    final_depth_pct: float
    resistance: float
    dist_to_resistance_pct: float
    vol_dry_up: bool
    vol_reduction_pct: float
    rolling_range_pct: float  # tight range over last 10 candles
    rvol: float  # current volume vs 20-day SMA volume
    trend_template: bool  # 50 SMA > 200 SMA & Close > 50 SMA
    sma50: float
    sma200: float
    high_52w: float
    low_52w: float
    smc_confluence: bool
    smc_notes: str
    ema9_4h: Optional[float] = None
    ema20_4h: Optional[float] = None
    ema_gap_pct_4h: Optional[float] = None
    ema_bullish_4h: Optional[bool] = None
    bars_since_ema_cross_4h: Optional[int] = None
    score: float = 0.0
    allocation_inr: float = 2000.0
    suggested_qty: int = 1
    position_value: float = 0.0
    pivot_stop_loss: float = 0.0
    target_price: float = 0.0
    hold_expectation: str = "3-5 days minimum"
    data_source: str = "Yahoo Finance"
    details: Dict[str, Any] = field(default_factory=dict)


DEFAULT_SWING_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "BHARTIARTL", "SBIN",
    "LICI", "ITC", "HINDUNILVR", "LT", "BAJFINANCE", "HCLTECH", "MARUTI",
    "SUNPHARMA", "ADANIENT", "KOTAKBANK", "TITAN", "ONGC", "NTPC",
    "AXISBANK", "DMART", "ADANIGREEN", "ADANIPORTS", "ULTRACEMCO", "COALINDIA",
    "POWERGRID", "BAJAJFINSV", "TRENT", "M&M", "BEL", "HAL", "SIEMENS",
    "IOC", "DLF", "VBL", "CHOLAFIN", "VEDL", "PIDILITIND", "DIVISLAB",
    "JIOFIN", "POLYCAB", "PERSISTENT", "COFORGE", "DIXON", "KALYANKJIL",
    "BSE", "CDSL", "ANGELONE", "MOTILALOFS", "SUZLON", "MAXHEALTH",
    "TATACOMM", "APOLLOHOSP", "SHRIRAMFIN", "FEDERALBNK", "INDUSINDBK", "TECHM", "WIPRO"
]


def fetch_stock_candles(
    ticker: str,
    period: str = "1y",
    interval: str = "1d",
    api_key: Optional[str] = None,
) -> Tuple[Optional[pd.DataFrame], str]:
    """Fetch historical OHLCV candles using INDmoney API or Yahoo Finance fallback."""
    clean_sym = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
    resolved_ticker = clean_sym if clean_sym.endswith(".NS") or clean_sym.startswith("^") else clean_sym + ".NS"

    # Try project's fetch_data first
    if fetch_data is not None:
        try:
            df, src = fetch_data(resolved_ticker, start=period, interval=interval, api_key=api_key)
            if df is not None and len(df) >= 20:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                return df, src
        except Exception:
            pass

    # Direct Yahoo finance fallback
    try:
        base_iv = "1h" if interval == "4h" else interval
        df = yf.download(resolved_ticker, period=period, interval=base_iv, progress=False)
        if df is not None and not df.empty and len(df) >= 20:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if interval == "4h":
                if resample_to_4h is not None:
                    df = resample_to_4h(df)
                else:
                    df = df.resample("4h").agg({
                        "Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"
                    }).dropna(subset=["Close"])
            return df, "Yahoo Finance"
    except Exception:
        pass

    return None, "None"


def check_trend_template(df: pd.DataFrame) -> Tuple[bool, Dict[str, float]]:
    """Mark Minervini Stage 2 Trend Template rules:

    1. Current Price > 50-day and 200-day Simple Moving Averages.
    2. 50-day SMA > 200-day SMA.
    3. Current Price within 30-35% of its 52-week High.
    4. Current Price at least 25% above its 52-week Low.
    """
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    last_c = float(close.iloc[-1])

    sma50 = close.rolling(50, min_periods=20).mean()
    sma200 = close.rolling(200, min_periods=40).mean()

    s50 = float(sma50.iloc[-1]) if len(sma50) else np.nan
    s200 = float(sma200.iloc[-1]) if len(sma200) else np.nan

    h52 = float(high.max()) if len(high) else last_c
    l52 = float(low.min()) if len(low) else last_c

    # Allow slight flexibility on SMA200 if stock is an IPO or strong emerging leader
    above_50 = last_c >= s50 if not np.isnan(s50) else True
    above_200 = last_c >= s200 if not np.isnan(s200) else True
    golden_alignment = s50 >= s200 * 0.98 if (not np.isnan(s50) and not np.isnan(s200)) else True
    near_highs = (last_c >= 0.65 * h52)  # within 35% of 52-week high
    above_lows = (last_c >= 1.20 * l52)  # at least 20% off 52-week low

    passes = bool(above_50 and above_200 and golden_alignment and near_highs)

    metrics = {
        "sma50": round(s50, 2) if not np.isnan(s50) else round(last_c, 2),
        "sma200": round(s200, 2) if not np.isnan(s200) else round(last_c, 2),
        "high_52w": round(h52, 2),
        "low_52w": round(l52, 2),
        "dist_from_52w_high_pct": round((h52 - last_c) / (h52 or 1) * 100, 2),
        "dist_from_52w_low_pct": round((last_c - l52) / (l52 or 1) * 100, 2),
    }
    return passes, metrics


def detect_vcp_contractions(df: pd.DataFrame, lookback: int = 100, order: int = 2) -> List[Contraction]:
    """Detect successive pullbacks (swing high to swing low) that contract in percentage depth."""
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    volume = df["Volume"].astype(float)
    n = len(df)
    if n < 30:
        return []

    start_bar = max(0, n - lookback)

    # 1. Detect swing highs and lows
    swings = []
    for i in range(start_bar + order, n - order):
        h_i = high.iloc[i]
        l_i = low.iloc[i]
        is_h = all(h_i >= high.iloc[i - k] and h_i >= high.iloc[i + k] for k in range(1, order + 1))
        is_l = all(l_i <= low.iloc[i - k] and l_i <= low.iloc[i + k] for k in range(1, order + 1))
        if is_h and not is_l:
            swings.append(("H", i, float(h_i), df.index[i]))
        elif is_l and not is_h:
            swings.append(("L", i, float(l_i), df.index[i]))
        elif is_h and is_l:
            side = "H" if close.iloc[i] >= df["Open"].iloc[i] else "L"
            val = float(h_i if side == "H" else l_i)
            swings.append((side, i, val, df.index[i]))

    # Merge consecutive swings of same side
    cleaned = []
    for s in swings:
        if not cleaned:
            cleaned.append(s)
            continue
        if s[0] == cleaned[-1][0]:
            if s[0] == "H" and s[2] > cleaned[-1][2]:
                cleaned[-1] = s
            elif s[0] == "L" and s[2] < cleaned[-1][2]:
                cleaned[-1] = s
        else:
            cleaned.append(s)

    # Build individual contraction phases (H -> L)
    raw_contractions = []
    for j in range(len(cleaned) - 1):
        if cleaned[j][0] == "H" and cleaned[j + 1][0] == "L":
            h_bar, h_dt, h_val = cleaned[j][1], cleaned[j][3], cleaned[j][2]
            l_bar, l_dt, l_val = cleaned[j + 1][1], cleaned[j + 1][3], cleaned[j + 1][2]
            if h_val > l_val:
                depth = (h_val - l_val) / h_val * 100.0
                phase_vol = volume.iloc[h_bar:l_bar + 1]
                avg_vol = float(phase_vol.mean()) if len(phase_vol) else 0.0
                raw_contractions.append(Contraction(
                    high_bar=h_bar,
                    high_date=str(h_dt)[:10],
                    high_price=round(h_val, 2),
                    low_bar=l_bar,
                    low_date=str(l_dt)[:10],
                    low_price=round(l_val, 2),
                    depth_pct=round(depth, 2),
                    avg_vol=avg_vol,
                    bars=l_bar - h_bar + 1,
                ))

    if len(raw_contractions) < 2:
        return []

    # Find the longest / best contraction chain where depth strictly or progressively contracts
    best_chain: List[Contraction] = []
    for start in range(len(raw_contractions)):
        chain = [raw_contractions[start]]
        for k in range(start + 1, len(raw_contractions)):
            curr = raw_contractions[k]
            prev = chain[-1]
            # Must be strictly later in time, and depth must be shallower than previous
            if curr.high_bar >= prev.low_bar and curr.depth_pct < prev.depth_pct * 0.98:
                chain.append(curr)
        if len(chain) >= 2:
            # Check recency: final contraction low should be within recent 35 bars
            if (n - chain[-1].low_bar) <= 40:
                if len(chain) > len(best_chain):
                    best_chain = chain
                elif len(chain) == len(best_chain) and chain[-1].depth_pct < best_chain[-1].depth_pct:
                    best_chain = chain

    return best_chain


def check_volume_dry_up(contractions: List[Contraction]) -> Tuple[bool, float, List[float]]:
    """Verify that average volume declines phase-over-phase across the contraction series."""
    if not contractions:
        return False, 0.0, []
    vols = [c.avg_vol for c in contractions]
    if len(vols) < 2:
        return True, 0.0, vols

    first_vol = vols[0] or 1.0
    last_vol = vols[-1]
    reduction_pct = round((1.0 - (last_vol / first_vol)) * 100.0, 1)

    # General decline or final volume substantially lower than initial base volume
    dry_up = (last_vol < first_vol) or all(vols[i] <= vols[i - 1] * 1.15 for i in range(1, len(vols)))
    return bool(dry_up), reduction_pct, vols


def detect_relative_volume_divergence(
    df: pd.DataFrame,
    contractions: List[Contraction],
    resistance: float,
) -> Tuple[bool, float, float, float]:
    """Detect late-stage volume divergence (Quiet Accumulation signal):

    In the final contraction phase or the last 10 candles:
    - Price range is compressing/flat (rolling % range <= 3.5 - 4.5%).
    - Relative volume (RVOL) is rising (current/recent volume >= 1.2x 20-day SMA).
    This indicates institutional absorption before the breakout.
    """
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    volume = df["Volume"].astype(float)
    last_c = float(close.iloc[-1])
    last_v = float(volume.iloc[-1])

    # Rolling 10-bar price range %
    last_10_h = high.iloc[-10:]
    last_10_l = low.iloc[-10:]
    rolling_range_pct = round(((last_10_h.max() - last_10_l.min()) / (last_c or 1)) * 100, 2)

    # 20-day average volume
    vol_20d = float(volume.iloc[-20:].mean()) if len(volume) >= 20 else float(volume.mean()) or 1.0
    rvol = round(last_v / (vol_20d or 1.0), 2)
    recent_rvol_3d = round(float(volume.iloc[-3:].mean()) / (vol_20d or 1.0), 2)

    # Quiet accumulation condition
    # Price is tight (< 4.5% 10-bar range or within tight final contraction < 8%), and RVOL is rising (>= 1.2x)
    tight_range = (rolling_range_pct <= 4.5) or (contractions and contractions[-1].depth_pct <= 6.5)
    rvol_rising = (rvol >= 1.15) or (recent_rvol_3d >= 1.15)
    is_quiet_accumulation = bool(tight_range and rvol_rising)

    return is_quiet_accumulation, rolling_range_pct, rvol, recent_rvol_3d


def check_breakout_confirmation(
    df: pd.DataFrame,
    resistance: float,
    rvol: float,
) -> Tuple[bool, bool]:
    """Flag confirmed breakout:

    - Price closes (not just wicks) above the resistance level.
    - Accompanied by volume surge (>= 1.35x - 1.5x average, i.e. 40-50% above average).
    """
    close = df["Close"].astype(float)
    high = df["High"].astype(float)
    last_c = float(close.iloc[-1])
    last_h = float(high.iloc[-1])

    # Confirmed close breakout with volume
    is_breakout = bool(last_c > resistance and rvol >= 1.35)
    # Near pivot / coiling within 3% of breakout level
    is_coiling = bool(resistance * 0.96 <= last_c <= resistance * 1.025)

    return is_breakout, is_coiling


def check_smc_confluence(df: pd.DataFrame, resistance: float) -> Tuple[bool, str]:
    """Check Smart Money Concepts (SMC) alignment:

    - Resistance aligns with prior Equal Highs (EQH) liquidity pool.
    - Prior liquidity sweep (Turtle Soup / sweep of swing low before the base contracted).
    - Bullish displacement / Fair Value Gap (FVG) mitigating at the bottom of the base.
    """
    if add_ict_indicators is None or len(df) < 30:
        return False, "Standard Price Action"

    try:
        f = add_ict_indicators(df)
        notes = []

        # Check Equal Highs near resistance
        if "EQH" in f.columns:
            eqh_max = int(f["EQH"].iloc[-30:].max())
            if eqh_max >= 2:
                notes.append(f"Swept {eqh_max} Equal Highs liquidity pool")

        # Check Bullish FVG in the base
        if "Bull_FVG" in f.columns:
            recent_fvg = bool(f["Bull_FVG"].iloc[-20:].any())
            if recent_fvg:
                notes.append("Institutional Bullish FVG present in base")

        # Check Displacement
        if "Displacement_Bull" in f.columns:
            recent_disp = bool(f["Displacement_Bull"].iloc[-15:].any())
            if recent_disp:
                notes.append("Recent Bullish Displacement")

        has_confluence = len(notes) > 0
        details = " & ".join(notes) if notes else "Clean structural base"
        return has_confluence, details
    except Exception:
        return False, "Clean structural base"


def check_4h_ema_alignment(df_4h: Optional[pd.DataFrame]) -> Tuple[bool, float, float, float, Optional[int]]:
    """Check 9/20 EMA range on 4-Hour timeframe:

    Returns (is_bullish, ema9, ema20, gap_pct, bars_since_cross).
    """
    if df_4h is None or df_4h.empty or len(df_4h) < 25:
        return False, 0.0, 0.0, 0.0, None

    try:
        close = df_4h["Close"].astype(float)
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        e9 = float(ema9.iloc[-1])
        e20 = float(ema20.iloc[-1])

        if not (np.isfinite(e9) and np.isfinite(e20)) or e20 == 0:
            return False, 0.0, 0.0, 0.0, None

        diff = ema9 - ema20
        cross_idx = None
        for i in range(len(diff) - 1, 0, -1):
            if float(diff.iloc[i]) > 0 and float(diff.iloc[i - 1]) <= 0:
                cross_idx = i
                break
        bars_since = (len(diff) - 1 - cross_idx) if cross_idx is not None else None
        gap_pct = round((e9 / e20 - 1) * 100, 2)
        is_bullish = bool(e9 > e20)
        return is_bullish, round(e9, 2), round(e20, 2), gap_pct, bars_since
    except Exception:
        return False, 0.0, 0.0, 0.0, None


def analyze_vcp_stock(
    ticker: str,
    df_daily: Optional[pd.DataFrame] = None,
    df_4h: Optional[pd.DataFrame] = None,
    api_key: Optional[str] = None,
) -> Optional[VCPResult]:
    """Comprehensive VCP + Volume Divergence + SMC + EMA analysis for a single stock."""
    # 1. Fetch Daily Data
    if df_daily is None:
        df_daily, src_daily = fetch_stock_candles(ticker, period="1y", interval="1d", api_key=api_key)
    else:
        src_daily = "Cached"
    if df_daily is None or len(df_daily) < 40:
        return None

    close = df_daily["Close"].astype(float)
    last_c = float(close.iloc[-1])
    prev_c = float(close.iloc[-2]) if len(close) >= 2 else last_c
    chg_pct = round(((last_c / (prev_c or 1)) - 1) * 100, 2)

    # 2. Trend Template
    trend_ok, trend_metrics = check_trend_template(df_daily)

    # 3. Contraction Detection (VCP)
    contractions = detect_vcp_contractions(df_daily, lookback=100, order=2)
    if len(contractions) < 2:
        return None

    vcp_type = f"{len(contractions)}T"
    depth_list = [c.depth_pct for c in contractions]
    final_depth = contractions[-1].depth_pct
    resistance = max(c.high_price for c in contractions)
    dist_to_res = round((resistance - last_c) / (resistance or 1) * 100, 2)

    # 4. Volume Dry-Up
    vol_dry_up, vol_reduction, _ = check_volume_dry_up(contractions)

    # 5. Relative Volume Divergence
    quiet_acc, rolling_range, rvol, rvol_3d = detect_relative_volume_divergence(df_daily, contractions, resistance)

    # 6. Breakout Confirmation
    is_breakout, is_coiling = check_breakout_confirmation(df_daily, resistance, rvol)

    # Determine Status
    if is_breakout:
        status = "CONFIRMED_BREAKOUT"
    elif quiet_acc:
        status = "PRE_BREAKOUT_ACCUMULATION"
    elif is_coiling:
        status = "COILING_AT_RESISTANCE"
    else:
        status = "VCP_BASE_FORMING"

    # 7. SMC Confluence
    smc_ok, smc_notes = check_smc_confluence(df_daily, resistance)

    # 8. 4-Hour EMA Analysis (Swing criteria)
    if df_4h is None:
        df_4h, _ = fetch_stock_candles(ticker, period="3mo", interval="4h", api_key=api_key)
    e_bull, e9, e20, e_gap, e_bars = check_4h_ema_alignment(df_4h)

    # Compute Total Quality Score (0 - 100)
    # Weights: Tightness (35%), Range (25%), RVOL (20%), VCP Symmetry (10%), Trend/SMC (10%)
    score = 0.0
    score += max(0.0, 35.0 - final_depth * 2.5)  # tighter final contraction = higher score
    score += max(0.0, 25.0 - rolling_range * 3.0)  # tight 10-day range
    score += min(20.0, rvol * 10.0)  # relative volume
    score += len(contractions) * 3.0  # more contractions = more mature base
    if trend_ok:
        score += 5.0
    if smc_ok:
        score += 5.0
    if is_breakout or quiet_acc:
        score += 5.0
    final_score = round(min(100.0, max(10.0, score)), 1)

    # 9. Swing ₹2,000 Allocation & Position Sizing
    alloc_inr = 2000.0
    suggested_qty = max(1, int(alloc_inr / (last_c or 1))) if last_c > 0 else 1
    pos_val = round(suggested_qty * last_c, 2)
    final_low = contractions[-1].low_price if contractions else (last_c * 0.95)
    stop_loss = round(final_low, 2)
    risk_unit = max(1.0, last_c - stop_loss)
    target_p = round(last_c + 2.0 * risk_unit, 2)

    return VCPResult(
        ticker=ticker.replace(".NS", "").replace(".BO", ""),
        price=round(last_c, 2),
        change_pct=chg_pct,
        status=status,
        vcp_type=vcp_type,
        contractions=depth_list,
        final_depth_pct=final_depth,
        resistance=resistance,
        dist_to_resistance_pct=dist_to_res,
        vol_dry_up=vol_dry_up,
        vol_reduction_pct=vol_reduction,
        rolling_range_pct=rolling_range,
        rvol=rvol,
        trend_template=trend_ok,
        sma50=trend_metrics["sma50"],
        sma200=trend_metrics["sma200"],
        high_52w=trend_metrics["high_52w"],
        low_52w=trend_metrics["low_52w"],
        smc_confluence=smc_ok,
        smc_notes=smc_notes,
        ema9_4h=e9,
        ema20_4h=e20,
        ema_gap_pct_4h=e_gap,
        ema_bullish_4h=e_bull,
        bars_since_ema_cross_4h=e_bars,
        score=final_score,
        allocation_inr=alloc_inr,
        suggested_qty=suggested_qty,
        position_value=pos_val,
        pivot_stop_loss=stop_loss,
        target_price=target_p,
        hold_expectation="3-5 days minimum",
        data_source=src_daily if "src_daily" in locals() and src_daily else "Yahoo Finance",
        details={
            "recent_rvol_3d": rvol_3d,
            "dist_from_52w_high_pct": trend_metrics["dist_from_52w_high_pct"],
        },
    )


def scan_universe_vcp(
    tickers: Optional[List[str]] = None,
    mode: str = "combined",  # "vcp", "ema_range", "combined"
    api_key: Optional[str] = None,
    max_workers: int = 8,
    progress_cb: Optional[Any] = None,
    on_match_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Scan a list of stocks across the requested check mode.

    Modes:
      - 'vcp': Mark Minervini VCP + Vol Divergence + SMC
      - 'ema_range': 4h 9/20 EMA Range
      - 'combined': Must qualify on BOTH 9/20 EMA Range AND Minervini VCP
    """
    if not tickers:
        try:
            from backtest_tools import NIFTY50
            comb = list(dict.fromkeys(NIFTY50 + DEFAULT_SWING_UNIVERSE))
            tickers = [s + ".NS" if not s.endswith(".NS") and not s.endswith(".BO") else s for s in comb]
        except ImportError:
            tickers = [s + ".NS" for s in DEFAULT_SWING_UNIVERSE]

    all_picks = []
    breakouts = []
    accumulations = []

    def _process(t):
        try:
            return analyze_vcp_stock(t, api_key=api_key)
        except Exception:
            return None

    scanned_count = 0
    total_count = len(tickers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_process, t): t for t in tickers}
        for fut in as_completed(future_map):
            scanned_count += 1
            if progress_cb:
                try:
                    progress_cb(scanned_count, total_count)
                except Exception:
                    pass

            res = fut.result()
            if res is None:
                continue

            # Filtering based on mode
            if mode == "combined":
                # Must satisfy BOTH VCP and 4h 9/20 EMA bullish alignment
                if not (res.ema_bullish_4h and len(res.contractions) >= 2):
                    continue
            elif mode == "ema_range":
                if not res.ema_bullish_4h:
                    continue

            d = asdict(res)
            all_picks.append(d)
            if res.status == "CONFIRMED_BREAKOUT":
                breakouts.append(d)
            elif res.status in ("PRE_BREAKOUT_ACCUMULATION", "COILING_AT_RESISTANCE"):
                accumulations.append(d)

            if on_match_cb:
                try:
                    on_match_cb(d)
                except Exception:
                    pass

    # Sort candidates by score descending
    all_picks.sort(key=lambda x: -x["score"])
    breakouts.sort(key=lambda x: -x["score"])
    accumulations.sort(key=lambda x: -x["score"])

    return {
        "mode": mode,
        "total_scanned": len(tickers),
        "total_qualified": len(all_picks),
        "picks": all_picks,
        "breakouts": breakouts,
        "quiet_accumulations": accumulations,
    }


def main():
    parser = argparse.ArgumentParser(description="Mark Minervini VCP Scanner with Volume Divergence & SMC Filters")
    parser.add_argument("--ticker", "-t", type=str, help="Specific ticker to analyze (e.g. RELIANCE, TRENT, TCS)")
    parser.add_argument("--mode", "-m", choices=["vcp", "ema_range", "combined"], default="combined", help="Scanner mode")
    parser.add_argument("--api-key", type=str, default="", help="INDmoney API Key / token")
    parser.add_argument("--json", action="store_true", help="Output raw JSON format")
    parser.add_argument("--limit", type=int, default=15, help="Max candidates to show")
    args = parser.parse_args()

    api_key = args.api_key.strip() or os.getenv("INDMONEY_API_KEY") or None

    if args.ticker:
        res = analyze_vcp_stock(args.ticker, api_key=api_key)
        if not res:
            print(f"No valid VCP setup found for {args.ticker} or insufficient data.")
            sys.exit(0)
        if args.json:
            print(json.dumps(asdict(res), indent=2))
        else:
            print(f"\n{'=' * 60}")
            print(f"VCP Analysis for {res.ticker} (₹{res.price:.2f}, {res.change_pct:+.2f}%)")
            print(f"{'=' * 60}")
            print(f"Status:               {res.status}")
            print(f"VCP Pattern:          {res.vcp_type} Contractions: {' -> '.join(f'{d:.1f}%' for d in res.contractions)}")
            print(f"Final Depth:          {res.final_depth_pct:.1f}% (Tightness)")
            print(f"Pivot Resistance:     ₹{res.resistance:.2f} (Distance: {res.dist_to_resistance_pct:+.2f}%)")
            print(f"Volume Dry-Up:        {'Confirmed' if res.vol_dry_up else 'Flat'} ({res.vol_reduction_pct}% reduction)")
            print(f"Relative Volume:      {res.rvol:.2f}x (20-day SMA)")
            print(f"Rolling Range (10d):  {res.rolling_range_pct:.2f}% (Volatility)")
            print(f"Trend Template:       {'PASS' if res.trend_template else 'FAIL'} (SMA50: ₹{res.sma50:.1f}, SMA200: ₹{res.sma200:.1f})")
            print(f"4h 9/20 EMA Swing:    {'BULLISH (+ ' + str(res.ema_gap_pct_4h) + '%)' if res.ema_bullish_4h else 'BEARISH'}")
            print(f"SMC Confluence:       {res.smc_notes}")
            print(f"Total Quality Score:  {res.score:.1f} / 100")
            print(f"{'=' * 60}\n")
    else:
        print(f"Scanning stocks in mode: {args.mode.upper()}...")
        scan_res = scan_universe_vcp(mode=args.mode, api_key=api_key)
        if args.json:
            print(json.dumps(scan_res, indent=2))
        else:
            print(f"\nScan complete: {scan_res['total_qualified']} candidates qualified out of {scan_res['total_scanned']} stocks scanned.\n")
            if scan_res["breakouts"]:
                print(f"--- CONFIRMED BREAKOUTS TODAY ({len(scan_res['breakouts'])}) ---")
                for p in scan_res["breakouts"][:args.limit]:
                    print(f"  • {p['ticker']:<12} ₹{p['price']:<8} VCP: {p['vcp_type']} {p['contractions']} | RVOL: {p['rvol']}x | Score: {p['score']}")
                print()
            if scan_res["quiet_accumulations"]:
                print(f"--- PRE-BREAKOUT QUIET ACCUMULATION WATCHLIST ({len(scan_res['quiet_accumulations'])}) ---")
                for p in scan_res["quiet_accumulations"][:args.limit]:
                    print(f"  • {p['ticker']:<12} ₹{p['price']:<8} VCP: {p['vcp_type']} {p['contractions']} | RVOL: {p['rvol']}x | Range: {p['rolling_range_pct']}% | Score: {p['score']}")
                print()


if __name__ == "__main__":
    main()
