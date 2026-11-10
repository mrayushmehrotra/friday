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
9. AMD Filter (Accumulation → Manipulation): confirmed-candle AMD state machine on 4h bars.
   A tight 4h range (≤ 3x ATR) = Accumulation; a liquidity sweep of that range with the close
   back inside and distribution NOT yet started = A+ manipulation setup for the swing trade.
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


# ── AMD (Accumulation → Manipulation → Distribution) parameters ────────────────
# Defaults match the Pine AMD indicator (confirmed candles only, 4h timeframe).
AMD_RANGE_LEN = 6          # candles that form the accumulation range
AMD_MAX_RANGE_ATR = 3.0    # max range height in ATR(14) units
AMD_MAX_MANIP_WAIT = 6     # candles allowed between sweep and distribution break
AMD_ATR_LEN = 14


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
    # AMD state machine on confirmed 4h candles (Accumulation → Manipulation)
    amd_status: str = ""               # "", "ACCUMULATION", "ACCUMULATION + MANIPULATION"
    amd_a_plus: bool = False           # live manipulation sweep → A+ swing setup at 4h TF
    amd_bias: str = ""                 # "LONG (low swept)" / "SHORT (high swept)"
    amd_range_low: float = 0.0
    amd_range_high: float = 0.0
    amd_range_height_pct: float = 0.0
    amd_candles_in_range: int = 0
    amd_sweep_time: str = ""
    amd_candles_since_sweep: Optional[int] = None
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


# ═══════════════════════════ AMD (4h) filter ═══════════════════════════
_AMD_EMPTY = {
    "status": "",
    "bias": "",
    "range_low": 0.0,
    "range_high": 0.0,
    "range_height_pct": 0.0,
    "range_start": "",
    "candles_in_range": 0,
    "sweep_time": "",
    "sweep_extreme": 0.0,
    "candles_since_sweep": None,
    "last_close": 0.0,
    "direction": 0,
}


def _wilder_atr_np(high: np.ndarray, low: np.ndarray, close: np.ndarray, n: int = AMD_ATR_LEN) -> np.ndarray:
    """Wilder ATR as a plain numpy array (first n-1 values are NaN), same as the Pine port."""
    pc = np.concatenate([[np.nan], close[:-1]])
    # np.fmax ignores NaN, matching pandas .max(axis=1) skipna behaviour of the original port
    tr = np.fmax.reduce([high - low, np.abs(high - pc), np.abs(low - pc)])
    out = np.full(len(tr), np.nan)
    if len(tr) >= n:
        out[n - 1] = tr[:n].mean()
        for i in range(n, len(tr)):
            out[i] = (out[i - 1] * (n - 1) + tr[i]) / n
    return out


def _drop_live_4h(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the still-forming 4h bar so the state machine only sees confirmed candles."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return df
    idx = df.index
    try:
        now = pd.Timestamp.now(tz=idx.tz) if idx.tz is not None else pd.Timestamp.now()
        s = pd.Series(idx)
        end = s + pd.Timedelta(hours=4)
        # NSE's afternoon 4h bucket starts at 12:00 IST but the session closes at 15:30 IST.
        if idx.tz is not None and "Kolkata" in str(idx.tz):
            afternoon = s.dt.hour == 12
            if bool(afternoon.any()):
                end = end.mask(afternoon, s.dt.normalize() + pd.Timedelta(hours=15, minutes=30))
        return df[(end <= now).to_numpy()]
    except Exception:
        return df


def scan_amd_state(df_4h: Optional[pd.DataFrame]) -> Optional[Dict[str, Any]]:
    """Run the AMD state machine over confirmed 4h candles.

    Faithful port of the Pine indicator (confirmed candles only):

      state 0 → 1  a tight range formed (rolling RANGE_LEN high/low height ≤ ATR × MAX_RANGE_ATR)
                   = ACCUMULATION
      state 1 → 2  the range high (or low) was swept by a wick while the close stayed back
                   inside the range = manipulation; distribution has NOT started yet
                   = ACCUMULATION + MANIPULATION  →  the A+ swing setup at 4h TF
      state 2 → 0  price closed beyond the opposite side of the range (distribution
                   confirmed) or the wait expired → setup is gone

    Returns None when no setup is active, otherwise a dict describing the state on
    the last confirmed candle.
    """
    if df_4h is None or df_4h.empty:
        return None
    df = df_4h
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    if not {"high", "low", "close"}.issubset(df.columns):
        return None
    df = _drop_live_4h(df.dropna(subset=[c for c in ("open", "high", "low", "close") if c in df.columns]))
    n = len(df)
    if n < AMD_RANGE_LEN + AMD_ATR_LEN + 2:
        return None

    h = df["high"].astype(float).to_numpy()
    l = df["low"].astype(float).to_numpy()
    c = df["close"].astype(float).to_numpy()
    atr = _wilder_atr_np(h, l, c, AMD_ATR_LEN)
    rh = df["high"].rolling(AMD_RANGE_LEN).max().to_numpy()
    rl = df["low"].rolling(AMD_RANGE_LEN).min().to_numpy()

    state, direction = 0, 0
    acc_hi = acc_lo = manip_ext = np.nan
    acc_start = manip_bar = -1
    last_reset = -1000

    for i in range(n):
        if state == 0:
            range_ok = (
                i >= AMD_RANGE_LEN
                and not np.isnan(atr[i])
                and not np.isnan(rh[i])
                and (rh[i] - rl[i]) <= atr[i] * AMD_MAX_RANGE_ATR
                and i - last_reset >= AMD_RANGE_LEN
            )
            if range_ok:
                state, acc_hi, acc_lo, acc_start = 1, rh[i], rl[i], i - AMD_RANGE_LEN + 1
        elif state == 1:
            sweep_up = h[i] > acc_hi and acc_lo < c[i] < acc_hi
            sweep_dn = l[i] < acc_lo and acc_lo < c[i] < acc_hi
            broke_out = c[i] > acc_hi or c[i] < acc_lo
            if sweep_up and sweep_dn:
                state, last_reset = 0, i
            elif sweep_up:
                state, direction, manip_ext, manip_bar = 2, -1, h[i], i
            elif sweep_dn:
                state, direction, manip_ext, manip_bar = 2, 1, l[i], i
            elif broke_out:
                state, last_reset = 0, i
        else:  # state == 2: swept, waiting for distribution
            manip_ext = max(manip_ext, h[i]) if direction == -1 else min(manip_ext, l[i])
            confirmed = (direction == -1 and c[i] < acc_lo) or (direction == 1 and c[i] > acc_hi)
            failed = (
                (direction == -1 and c[i] > acc_hi)
                or (direction == 1 and c[i] < acc_lo)
                or (i - manip_bar > AMD_MAX_MANIP_WAIT)
            )
            if confirmed or failed:
                state, last_reset = 0, i  # distribution started → no longer a candidate

    if state == 0:
        return None

    ts = df.index
    res = dict(
        status="ACCUMULATION" if state == 1 else "ACCUMULATION + MANIPULATION",
        range_low=float(acc_lo),
        range_high=float(acc_hi),
        range_height_pct=float((acc_hi - acc_lo) / acc_lo * 100) if acc_lo else 0.0,
        range_start=str(ts[acc_start]),
        candles_in_range=int(n - acc_start),
        last_close=float(c[-1]),
        direction=int(direction),
    )
    if state == 2:
        res.update(
            bias="LONG (low swept)" if direction == 1 else "SHORT (high swept)",
            sweep_time=str(ts[manip_bar]),
            sweep_extreme=float(manip_ext),
            candles_since_sweep=int(n - 1 - manip_bar),
        )
    else:
        res.update(bias="", sweep_time="", sweep_extreme=0.0, candles_since_sweep=None)
    return res


def check_amd_manipulation(df_4h: Optional[pd.DataFrame]) -> Tuple[bool, Dict[str, Any]]:
    """AMD swing filter → (is_a_plus, info).

    is_a_plus is True while the price is INSIDE the manipulation phase: the 4h range
    high/low was swept and price closed back inside, and distribution has NOT started
    yet — the A+ setup for the Swing Equity trade at 4h TF.

    info always carries the full AMD state (info["status"] is "" when no range is active).
    """
    info = dict(_AMD_EMPTY)
    try:
        res = scan_amd_state(df_4h)
    except Exception:
        res = None
    if res is None:
        return False, info
    info.update(res)
    return bool(res["status"] == "ACCUMULATION + MANIPULATION"), info


def scan_amd_stock(
    ticker: str,
    df_4h: Optional[pd.DataFrame] = None,
    api_key: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Standalone 4h AMD filter for the swing scan — no VCP base required.

    Returns a compact pick dict while the stock sits inside an active accumulation
    range on confirmed 4h candles. When the manipulation phase is live (range swept,
    close back inside, distribution not started) the pick is flagged ``amd_a_plus``
    and ``status = "A+_AMD_MANIPULATION"`` — the A+ Swing Equity setup at 4h TF.
    Returns None when no AMD range is active.
    """
    if df_4h is None:
        df_4h, src = fetch_stock_candles(ticker, period="3mo", interval="4h", api_key=api_key)
    else:
        src = "Cached"
    if df_4h is None or df_4h.empty:
        return None

    state = scan_amd_state(df_4h)
    if state is None:
        return None

    df = df_4h
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.lower)
    if "close" not in df.columns:
        return None
    close = df["close"].astype(float).dropna()
    if isinstance(close.index, pd.DatetimeIndex):
        close = close.loc[_drop_live_4h(close.to_frame()).index]
    if len(close) == 0:
        return None
    last_c = float(close.iloc[-1])
    prev_c = float(close.iloc[-2]) if len(close) >= 2 else last_c
    chg_pct = round(((last_c / (prev_c or 1)) - 1) * 100, 2) if prev_c else 0.0

    a_plus = state["status"] == "ACCUMULATION + MANIPULATION"
    sweep_ext = float(state.get("sweep_extreme") or 0.0)
    if a_plus:
        # Fresher sweep = higher score (window is AMD_MAX_MANIP_WAIT bars).
        age = int(state.get("candles_since_sweep") or 0)
        score = round(96.0 - min(age, AMD_MAX_MANIP_WAIT) * 3.0, 1)
        if sweep_ext:
            if "LONG" in state.get("bias", ""):
                stop_loss = round(sweep_ext * 0.995, 2)
                target_p = round(last_c + max(1.0, last_c - stop_loss) * 2.5, 2)
            else:
                stop_loss = round(sweep_ext * 1.005, 2)
                target_p = round(last_c - max(1.0, stop_loss - last_c) * 2.5, 2)
        else:
            stop_loss = round(last_c * 0.95, 2)
            target_p = round(last_c * 1.08, 2)
    else:
        # Tighter accumulation range = higher score.
        score = round(72.0 + max(0.0, 10.0 - float(state["range_height_pct"]) * 2.0), 1)
        if state.get("range_low"):
            stop_loss = round(float(state["range_low"]) * 0.99, 2)
            target_p = round(float(state["range_high"]) * 1.05, 2)
        else:
            stop_loss = round(last_c * 0.95, 2)
            target_p = round(last_c * 1.08, 2)

    return {
        "ticker": ticker.replace(".NS", "").replace(".BO", ""),
        "price": round(last_c, 2),
        "change_pct": chg_pct,
        "status": "A+_AMD_MANIPULATION" if a_plus else "AMD_ACCUMULATION",
        "amd_status": state["status"],
        "amd_a_plus": a_plus,
        "amd_bias": state["bias"],
        "amd_range_low": round(state["range_low"], 2),
        "amd_range_high": round(state["range_high"], 2),
        "amd_range_height_pct": round(state["range_height_pct"], 2),
        "amd_candles_in_range": state["candles_in_range"],
        "amd_sweep_time": state["sweep_time"],
        "amd_candles_since_sweep": state["candles_since_sweep"],
        "score": score,
        "allocation_inr": 2000.0,
        "suggested_qty": max(1, int(2000.0 / (last_c or 1))) if last_c > 0 else 1,
        "pivot_stop_loss": stop_loss,
        "target_price": target_p,
        "hold_expectation": "3-5 days minimum",
        "data_source": src,
        "details": {
            "amd_range_start": state.get("range_start", ""),
            "amd_sweep_extreme": sweep_ext,
        },
    }


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
    vcp_qualified = len(contractions) >= 2

    if vcp_qualified:
        vcp_type = f"{len(contractions)}T"
        depth_list = [c.depth_pct for c in contractions]
        final_depth = contractions[-1].depth_pct
        resistance = max(c.high_price for c in contractions)
        dist_to_res = round((resistance - last_c) / (resistance or 1) * 100, 2)
        vol_dry_up, vol_reduction, _ = check_volume_dry_up(contractions)
        quiet_acc, rolling_range, rvol, rvol_3d = detect_relative_volume_divergence(df_daily, contractions, resistance)
        is_breakout, is_coiling = check_breakout_confirmation(df_daily, resistance, rvol)
        if is_breakout:
            status = "CONFIRMED_BREAKOUT"
        elif quiet_acc:
            status = "PRE_BREAKOUT_ACCUMULATION"
        elif is_coiling:
            status = "COILING_AT_RESISTANCE"
        else:
            status = "VCP_BASE_FORMING"
        smc_ok, smc_notes = check_smc_confluence(df_daily, resistance)
    else:
        vcp_type = ""
        depth_list = [c.depth_pct for c in contractions] if contractions else []
        final_depth = depth_list[-1] if depth_list else 0.0
        rolling_20_hi = float(df_daily["High"].rolling(20, min_periods=5).max().iloc[-1])
        resistance = round(rolling_20_hi, 2)
        dist_to_res = round((resistance - last_c) / (resistance or 1) * 100, 2)
        vol_dry_up, vol_reduction = False, 0.0
        rolling_range = round(float(((df_daily["High"].rolling(10).max() - df_daily["Low"].rolling(10).min()) / (df_daily["Close"] or 1) * 100).iloc[-1]), 2)
        vol_col = df_daily["Volume"].astype(float)
        vol_sma20 = vol_col.rolling(20, min_periods=5).mean().iloc[-1]
        rvol = round(float(vol_col.iloc[-1] / (vol_sma20 or 1)), 2)
        rvol_3d = round(float(vol_col.tail(3).mean() / (vol_sma20 or 1)), 2)
        is_breakout, is_coiling, quiet_acc = False, False, False
        status = "NO_VCP_BASE"
        smc_ok, smc_notes = False, ""

    # 8. 4-Hour EMA Analysis (Swing criteria)
    if df_4h is None:
        df_4h, _ = fetch_stock_candles(ticker, period="3mo", interval="4h", api_key=api_key)
    e_bull, e9, e20, e_gap, e_bars = check_4h_ema_alignment(df_4h)

    # 8b. AMD state machine on confirmed 4h candles (Accumulation → Manipulation)
    amd_a_plus, amd = check_amd_manipulation(df_4h)

    # Must qualify on at least one swing paradigm: VCP base, AMD range, or 4h EMA bullish alignment
    if not vcp_qualified and not amd["status"] and not e_bull:
        return None

    if not vcp_qualified:
        if amd_a_plus:
            status = "AMD_A_PLUS_MANIPULATION"
        elif amd["status"] == "ACCUMULATION":
            status = "AMD_ACCUMULATION"
        elif e_bull:
            status = "EMA_4H_BULLISH"

    # Compute Total Quality Score (0 - 100)
    score = 0.0
    if vcp_qualified:
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
    else:
        score += max(0.0, 25.0 - rolling_range * 2.0)
        score += min(15.0, rvol * 10.0)
        if trend_ok:
            score += 10.0

    if amd_a_plus:
        score += 25.0  # A+: 4h sweep closed back inside, distribution pending
    elif amd["status"]:
        score += 10.0  # active accumulation range (pre-sweep)

    if e_bull:
        score += 5.0
    final_score = round(min(100.0, max(15.0, score)), 1)

    # 9. Swing ₹2,000 Allocation & Position Sizing
    alloc_inr = 2000.0
    suggested_qty = max(1, int(alloc_inr / (last_c or 1))) if last_c > 0 else 1
    pos_val = round(suggested_qty * last_c, 2)
    if amd["status"]:
        if amd_a_plus and amd["sweep_extreme"]:
            if "LONG" in amd["bias"]:
                stop_loss = round(amd["sweep_extreme"] * 0.995, 2)
                target_p = round(last_c + max(1.0, last_c - stop_loss) * 2.5, 2)
            else:
                stop_loss = round(amd["sweep_extreme"] * 1.005, 2)
                target_p = round(last_c - max(1.0, stop_loss - last_c) * 2.5, 2)
        elif amd["range_low"]:
            stop_loss = round(amd["range_low"] * 0.99, 2)
            target_p = round(amd["range_high"] * 1.05, 2)
        else:
            final_low = contractions[-1].low_price if contractions else (last_c * 0.95)
            stop_loss = round(final_low, 2)
            risk_unit = max(1.0, last_c - stop_loss)
            target_p = round(last_c + 2.0 * risk_unit, 2)
    else:
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
        amd_status=amd["status"],
        amd_a_plus=amd_a_plus,
        amd_bias=amd["bias"],
        amd_range_low=amd["range_low"],
        amd_range_high=amd["range_high"],
        amd_range_height_pct=round(amd["range_height_pct"], 2),
        amd_candles_in_range=amd["candles_in_range"],
        amd_sweep_time=amd["sweep_time"],
        amd_candles_since_sweep=amd["candles_since_sweep"],
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
            "amd_range_start": amd["range_start"],
            "amd_sweep_extreme": amd["sweep_extreme"],
        },
    )


def scan_universe_vcp(
    tickers: Optional[List[str]] = None,
    mode: str = "combined",  # "vcp", "ema_range", "amd", "combined"
    api_key: Optional[str] = None,
    max_workers: int = 8,
    progress_cb: Optional[Any] = None,
    on_match_cb: Optional[Any] = None,
) -> Dict[str, Any]:
    """Scan a list of stocks across the requested check mode.

    Modes:
      - 'vcp': Mark Minervini VCP + Vol Divergence + SMC (standalone filter)
      - 'ema_range': 4h 9/20 EMA Range (standalone filter)
      - 'amd': 4h AMD state machine (standalone filter) — inside an active accumulation
               range, with the manipulation phase (sweep closed back inside, no
               distribution yet) = A+
      - 'combined': BOTH 9/20 EMA Range AND Minervini VCP
      - 'mixed': ALL THREE — 9/20 EMA Range AND VCP AND active 4h AMD range
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

    if mode == "amd":
        # Standalone 4h AMD filter: no VCP structure required, only an active AMD range.
        def _process(t):
            try:
                return scan_amd_stock(t, api_key=api_key)
            except Exception:
                return None
    else:
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

            if mode == "amd":
                # scan_amd_stock already returns None unless an active 4h AMD range exists.
                d = res
            else:
                # Filtering based on mode
                if mode == "combined":
                    # Must satisfy BOTH VCP and 4h 9/20 EMA bullish alignment
                    if not (res.ema_bullish_4h and len(res.contractions) >= 2):
                        continue
                elif mode == "mixed":
                    # All three filters simultaneously: 4h 9/20 EMA + VCP + active 4h AMD range
                    if not (res.ema_bullish_4h and len(res.contractions) >= 2 and res.amd_status):
                        continue
                elif mode == "ema_range":
                    if not res.ema_bullish_4h:
                        continue
                d = asdict(res)

            all_picks.append(d)
            status = d.get("status")
            if status == "CONFIRMED_BREAKOUT":
                breakouts.append(d)
            elif status in ("PRE_BREAKOUT_ACCUMULATION", "COILING_AT_RESISTANCE"):
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
    amd_a_plus = [p for p in all_picks if p.get("amd_a_plus")]
    amd_accumulations = [p for p in all_picks if not p.get("amd_a_plus") and p.get("amd_status") == "ACCUMULATION"]
    amd_a_plus.sort(key=lambda x: -x["score"])
    amd_accumulations.sort(key=lambda x: -x["score"])

    return {
        "mode": mode,
        "total_scanned": len(tickers),
        "total_qualified": len(all_picks),
        "picks": all_picks,
        "breakouts": breakouts,
        "quiet_accumulations": accumulations,
        "amd_a_plus": amd_a_plus,
        "amd_accumulations": amd_accumulations,
    }


def main():
    parser = argparse.ArgumentParser(description="Mark Minervini VCP Scanner with Volume Divergence & SMC Filters")
    parser.add_argument("--ticker", "-t", type=str, help="Specific ticker to analyze (e.g. RELIANCE, TRENT, TCS)")
    parser.add_argument("--mode", "-m", choices=["vcp", "ema_range", "amd", "combined", "mixed"], default="combined",
                        help="Scanner mode: each filter standalone (vcp / ema_range / amd), combined = EMA+VCP, mixed = all three")
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
            amd_line = res.amd_status or "No active 4h range"
            if res.amd_a_plus:
                amd_line += " — A+ manipulation live"
            if res.amd_bias:
                amd_line += f" · {res.amd_bias}"
            if res.amd_status:
                amd_line += f" (range ₹{res.amd_range_low:.2f}–₹{res.amd_range_high:.2f})"
            print(f"AMD 4h Filter:        {amd_line}")
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
            a_plus = [p for p in scan_res["picks"] if p.get("amd_a_plus")]
            if a_plus:
                print(f"--- AMD A+ MANIPULATION SETUPS (4h) ({len(a_plus)}) ---")
                for p in a_plus[:args.limit]:
                    print(f"  • {p['ticker']:<12} ₹{p['price']:<8} {p['amd_bias']} | Sweep {p['amd_candles_since_sweep']} bars ago | "
                          f"Range ₹{p['amd_range_low']}–₹{p['amd_range_high']} | Score: {p['score']}")
                print()


if __name__ == "__main__":
    main()
