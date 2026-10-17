"""
ICT (Inner Circle Trader) Strategy Library for Indian Equities
==============================================================

Concepts implemented (all long **and** short):

  ict_fair_value_gap           — 3-candle imbalance, entered on mitigation of a pending gap
  ict_silver_bullet            — liquidity raid + displacement/FVG in a time window, drawn to opposing liquidity
  ict_order_block_mss          — market structure shift, retest of the institutional candle (with invalidation checks)
  ict_liquidity_sweep_turtle_soup — purge of a swing/PD-liquidity pool with rejection reclaim
  ict_optimal_trade_entry      — 61.8–78.6% discount/premium retracement of a confirmed impulse leg
  ict_judas_swing              — session-open liquidity raid + institutional engulfing reversal
  ict_breaker_block            — failed order block retested from the other side (NEW)
  ict_premium_discount         — equilibrium (50%) dealing-range model with PD-array targets (NEW)
  ict_smt_divergence           — SMT divergence against the index reference series (NEW)

Supporting ICT concepts:

  * Displacement, ATR, FVG state machine (pending / tapped / filled / invalidated)
  * Fractal swing points (confirmed with a 2-bar delay) → structure + liquidity pools
  * Equal highs / equal lows clustering (EQH / EQL)
  * Premium / discount (equilibrium) of the dealing range
  * PD arrays: PDH / PDL, PWH / PWL, weekly open, session open
  * Higher-time-frame bias (completed weekly bars only)
  * Session / killzone classification (NSE, IST) for intraday candles
  * SMT divergence against a reference instrument (index)
  * Structural (ICT) stop-loss + liquidity target carried on every entry signal

Look-ahead policy
-----------------
No indicator or signal may use data from a bar later than the bar it is
evaluated on.  Specifically:

  * ``bfill`` is never used (it leaks future values into the warm-up rows).
  * Fractal pivots are only visible ``PIVOT`` bars after they occur, because a
    2-bar fractal needs 2 right-hand bars to confirm.
  * Pending-FVG / liquidity-pool state is snapshotted at the *start* of a bar
    and only updated with that bar's data afterwards, so a signal evaluated on
    bar ``i`` sees the pools as they were before bar ``i`` traded.
  * Everything else is strictly causal (rolling/expanding operations that only
    look backwards).

``tests/ict_backtest_test.py`` re-computes the indicator frame on truncated
prefixes and asserts every value at bar ``i`` is identical — that is the
regression guard for this contract.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# --------------------------------------------------------------------------- #
# Tunables
# --------------------------------------------------------------------------- #

MIN_BARS = 20            # every strategy refuses to signal before this bar
PIVOT = 2                # fractal swing = PIVOT bars either side
DEALING_RANGE = 20       # premium/discount dealing range (bars)
OB_RETEST_BARS = 12      # max bars after an MSS in which the OB may be retested
BREAKER_LOOKBACK = 25    # how far back a breaker's origin candle may be
SMT_WINDOW = 10          # bars used for SMT new-high/new-low comparison
SWEEP_LOOKBACK = 4       # bars in which a liquidity raid must have happened

# 18 smoothed-Moving-Average breakout (see smma_18_breakout).  "Smoothed MA" is
# the Wilder/RMA smoothing: smma[i] = (smma[i-1] * n + close[i]) / (n + 1).
SMMA_LEN = 18            # lookback of the smoothed moving average
SMMA_CUT_LOOKBACK = 6    # how recent the 18-SMMA cut candle may be
SMMA_BREAK_BODY = 0.5    # breakout candle body as a fraction of ATR
SMMA_CLEAN_BODY = 0.3    # a bar smaller than this is "consolidation" chop

# Super Trend tunables (standard: period=10, multiplier=3.0)
SUPERTREND_PERIOD = 10
SUPERTREND_MULTIPLIER = 3.0

# ICT killzones are defined in New York time; NSE trades 19:45–01:00 ET, so the
# NY windows never overlap the Indian session.  These are the structural
# equivalents expressed in IST and used for intraday candles only.
SESSION_WINDOWS_IST = [
    ("OPEN",    9.25, 10.25),   # opening drive / Judas window
    ("MORNING", 10.25, 11.50),
    ("MIDDAY",  11.50, 13.50),
    ("PM",      13.50, 14.50),  # afternoon continuation / Silver Bullet window
    ("CLOSE",   14.50, 15.50),  # closing auction
]
OPEN_KZ_IST = (9.25, 10.25)
SILVER_BULLET_IST = (13.50, 14.50)
CLOSE_KZ_IST = (14.50, 15.50)

#: strategies that need the index reference series for SMT
NEEDS_SMT_REF = {"ict_smt_divergence"}


# --------------------------------------------------------------------------- #
# Signal
# --------------------------------------------------------------------------- #

@dataclass
class Signal:
    """Desired end state for the current bar.

    action
        BUY     — be long (covers a short first, then opens the long)
        SHORT   — be short (closes a long first, then opens the short)
        SELL    — close a long, do not open anything
        COVER   — close a short, do not open anything
        EXIT    — close whatever is open
        HOLD    — do nothing

    stop_price / target_price
        Structural ICT levels for the *entry* the signal opens: the invalidation
        level (order block low, sweep low, swing low …) and the draw on
        liquidity (opposing pool).  The engine executes them intrabar.
    """

    action: str = "HOLD"
    size: float = 1.0
    reason: str = ""
    stop_price: Optional[float] = None
    target_price: Optional[float] = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _s(df: pd.DataFrame, i: int, col: str) -> float:
    """Scalar read (float) of ``col`` at bar ``i``."""
    return float(df[col].iloc[i])


def _b(df: pd.DataFrame, i: int, col: str) -> bool:
    """Boolean read of ``col`` at bar ``i`` (NaN → False)."""
    v = df[col].iloc[i]
    return bool(v) if v == v else False


def _session(hour: float) -> Tuple[str, bool, bool]:
    """Return ``(label, opening_killzone, silver_bullet_window)`` for an IST hour."""
    for label, lo, hi in SESSION_WINDOWS_IST:
        if lo <= hour < hi:
            in_open = OPEN_KZ_IST[0] <= hour < OPEN_KZ_IST[1]
            in_sb = SILVER_BULLET_IST[0] <= hour < SILVER_BULLET_IST[1]
            return label, in_open, in_sb
    return "OFF", False, False


def _ist_hours(idx: pd.Index) -> List[float]:
    """IST decimal hours for a (possibly tz-aware) datetime index."""
    ts = idx
    try:
        if getattr(ts, "tz", None) is None:
            ts = ts.tz_localize("Asia/Kolkata")
        else:
            ts = ts.tz_convert("Asia/Kolkata")
    except Exception:
        pass
    return list(ts.hour + ts.minute / 60.0)


def _is_intraday_index(idx: pd.Index) -> bool:
    """True when more than one bar shares a calendar date (i.e. intraday)."""
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 2:
        return False
    return bool(pd.Index(idx.normalize()).duplicated().any())


def _covers(hour: float, end: float, window: Tuple[float, float]) -> bool:
    """True when bar ``[hour, end)`` touches ``window``.

    Start-in-window (the usual case) or the bar's span reaches into it.  A
    4-hour bar opens at 08:00 or 12:00 on NSE and therefore never *opens*
    inside a killzone, yet it contains the whole morning/afternoon window —
    its price action happened during the killzone, so the gate has to see it.
    The ``hour < window_end`` guard keeps a late bar from reaching forward
    into tomorrow's window.
    """
    w0, w1 = window
    return (w0 <= hour < w1) or (hour < w1 and end > w0)


def _classify_sessions(
    idx: pd.Index,
) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
    """Session label / killzone flags for every bar (IST).

    Returns ``(is_intraday, session, opening_kz, silver_bullet_kz,
    closing_kz)``.  On daily candles every flag is False — the time-gated
    strategies simply skip their gate instead of pretending a daily bar has a
    session.

    The ``session`` label is the window the bar *opened* in; the three
    killzone flags are span-based (see :func:`_covers`) so that wide bars
    count.  A bar's span comes from the gap that produced it — timestamps
    already seen — so the flags stay causal under truncation.
    """
    false = pd.Series([False] * len(idx), index=idx, dtype=bool)

    if not _is_intraday_index(idx):
        return (
            false,
            pd.Series(["DAILY"] * len(idx), index=idx, dtype=object),
            false,
            false,
            false,
        )

    hours = _ist_hours(idx)
    labels, open_kz, sb_kz, close_kz = [], [], [], []
    # Bar duration: the gap that produced this bar when it is an intraday gap;
    # the last one seen when the gap spans the overnight break (the grid did
    # not change, only the clock).  Derived purely from timestamps already
    # seen, so truncating the frame can never change an earlier bar's flags.
    dur = 0.0
    prev = None
    for k, h in enumerate(hours):
        lab, _o, _s = _session(float(h))
        t = idx[k]
        if prev is not None:
            gap = (t - prev) / pd.Timedelta(hours=1)
            if t.normalize() == prev.normalize():
                dur = gap
        labels.append(lab)
        open_kz.append(_covers(h, h + dur, OPEN_KZ_IST))
        sb_kz.append(_covers(h, h + dur, SILVER_BULLET_IST))
        close_kz.append(_covers(h, h + dur, CLOSE_KZ_IST))
        prev = t
    true = pd.Series([True] * len(idx), index=idx, dtype=bool)
    return (
        true,
        pd.Series(labels, index=idx, dtype=object),
        pd.Series(open_kz, index=idx, dtype=bool),
        pd.Series(sb_kz, index=idx, dtype=bool),
        pd.Series(close_kz, index=idx, dtype=bool),
    )


def _fractal_masks(high: pd.Series, low: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """2-left / 2-right fractal swing highs and lows.

    The mask at bar ``s`` looks at ``s-2 .. s+2`` — it is *not* valid at bar
    ``s``.  Consumers must only read it at ``s + PIVOT`` (see the state loop).
    """
    win = 2 * PIVOT + 1
    ph = high == high.rolling(win, center=True, min_periods=win).max()
    pl = low == low.rolling(win, center=True, min_periods=win).min()
    return ph.fillna(False), pl.fillna(False)


def _previous_day_levels(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """PDH / PDL: high/low of the *previous completed* session for each bar.

    The per-session aggregates are shifted by one session and then mapped back
    to the bars.  Shifting a per-bar ``transform`` result would instead hand
    every bar after the first of a session the *current* session's high —
    data the bar has not seen yet.
    """
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        nan = pd.Series(np.nan, index=idx)
        return nan, nan
    day = pd.Index(idx.normalize())
    prev_high = df["High"].groupby(day).max().shift(1)
    prev_low = df["Low"].groupby(day).min().shift(1)
    return (
        pd.Series(prev_high.reindex(day).to_numpy(), index=idx),
        pd.Series(prev_low.reindex(day).to_numpy(), index=idx),
    )


def _previous_week_levels(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """PWH / PWL (previous completed week) and the current weekly open.

    Same construction as :func:`_previous_day_levels`: aggregate per week,
    shift the aggregates, map back.  The weekly *open* is the first bar of the
    current week, which is in the past for every bar of that week.
    """
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        nan = pd.Series(np.nan, index=idx)
        return nan, nan, nan
    week = pd.Index(idx.to_period("W"))
    pwh = df["High"].groupby(week).max().shift(1)
    pwl = df["Low"].groupby(week).min().shift(1)
    wk_open = df["Open"].groupby(week).transform("first")
    return (
        pd.Series(pwh.reindex(week).to_numpy(), index=idx),
        pd.Series(pwl.reindex(week).to_numpy(), index=idx),
        wk_open,
    )


def _smma(close: pd.Series, n: int = SMMA_LEN) -> pd.Series:
    """Wilder's smoothed moving average (a.k.a. RMA / SMMA).

    ``smma[i] = (smma[i-1] * (n - 1) + close[i]) / n`` — the "18 smoothed MA"
    of the setup.  Causal: it is an exponential recursion, so bar ``i`` only
    ever sees closes up to and including ``i``.  (Seeded at the first close
    rather than TradingView's SMA seed — the two agree to well under a tick
    after a few multiples of ``n`` bars.)
    """
    return close.ewm(alpha=1.0 / n, adjust=False).mean()


def _supertrend(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    period: int = SUPERTREND_PERIOD,
    multiplier: float = SUPERTREND_MULTIPLIER,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """SuperTrend indicator calculation (Wilder ATR). Strictly causal.

    Returns (supertrend, direction, final_upper_band, final_lower_band)
    where direction is +1 for Bullish/Positive and -1 for Bearish/Negative.
    """
    n = len(close)
    if n == 0:
        return np.array([]), np.array([]), np.array([]), np.array([])

    tr = np.zeros(n, dtype=float)
    tr[0] = high[0] - low[0]
    for i in range(1, n):
        tr[i] = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))

    atr = np.full(n, np.nan, dtype=float)
    if n >= period:
        atr[period - 1] = float(np.mean(tr[:period]))
        for i in range(period, n):
            atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period

    hl2 = (high + low) / 2.0
    basic_upper = hl2 + multiplier * atr
    basic_lower = hl2 - multiplier * atr

    final_upper = np.full(n, np.nan, dtype=float)
    final_lower = np.full(n, np.nan, dtype=float)
    st = np.full(n, np.nan, dtype=float)
    direction = np.zeros(n, dtype=int)

    if n >= period:
        k = period - 1
        final_upper[k] = basic_upper[k]
        final_lower[k] = basic_lower[k]
        if close[k] <= final_upper[k]:
            st[k] = final_upper[k]
            direction[k] = -1
        else:
            st[k] = final_lower[k]
            direction[k] = 1

        for i in range(period, n):
            # Final Upper Band
            if basic_upper[i] < final_upper[i - 1] or close[i - 1] > final_upper[i - 1]:
                final_upper[i] = basic_upper[i]
            else:
                final_upper[i] = final_upper[i - 1]

            # Final Lower Band
            if basic_lower[i] > final_lower[i - 1] or close[i - 1] < final_lower[i - 1]:
                final_lower[i] = basic_lower[i]
            else:
                final_lower[i] = final_lower[i - 1]

            # Direction & Supertrend
            if st[i - 1] == final_upper[i - 1]:
                if close[i] > final_upper[i]:
                    direction[i] = 1
                    st[i] = final_lower[i]
                else:
                    direction[i] = -1
                    st[i] = final_upper[i]
            else:
                if close[i] < final_lower[i]:
                    direction[i] = -1
                    st[i] = final_upper[i]
                else:
                    direction[i] = 1
                    st[i] = final_lower[i]

    return st, direction, final_upper, final_lower


def _htf_bias(df: pd.DataFrame) -> pd.Series:
    """Higher-time-frame bias from *completed* weekly bars.

    +1 when the last completed weekly close is above its 8-week EMA, -1 below,
    0 when there is not enough weekly history.  Mapped back onto the bar's own
    week, so a bar inside week W only ever sees weeks < W.
    """
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex) or len(idx) < 10:
        return pd.Series(0, index=df.index, dtype="int8")
    week = pd.Index(idx.to_period("W"))
    wk_close = df["Close"].groupby(week).last()
    wk_ema = wk_close.ewm(span=8, adjust=False).mean()
    bias = np.sign((wk_close.shift(1) - wk_ema.shift(1)).fillna(0)).astype("int8")
    # ``bias`` is indexed by week, ``week`` has one entry per bar — reindex
    # positionally rather than groupby, which would need matching lengths.
    mapped = bias.reindex(pd.Index(week)).to_numpy()
    return pd.Series(mapped, index=df.index, dtype="int8")


def _smt_columns(df: pd.DataFrame, ref: Optional[pd.DataFrame]) -> Tuple[pd.Series, pd.Series]:
    """SMT divergence vs. the reference instrument (normally the index).

    Bearish SMT: reference prints a new ``SMT_WINDOW``-bar high while the
    symbol does not.  Bullish SMT is the mirror on the lows.  The reference is
    reindexed with forward-fill only, so no future reference data is used.
    """
    if ref is None or len(ref) == 0:
        false = pd.Series(False, index=df.index, dtype=bool)
        return false, false
    ref_close = ref["Close"].astype(float).reindex(df.index, method="ffill")
    sym_close = df["Close"].astype(float)

    ref_h = ref_close.rolling(SMT_WINDOW).max().shift(1)
    ref_l = ref_close.rolling(SMT_WINDOW).min().shift(1)
    sym_h = sym_close.rolling(SMT_WINDOW).max().shift(1)
    sym_l = sym_close.rolling(SMT_WINDOW).min().shift(1)

    smt_bear = ((ref_close > ref_h) & ~(sym_close > sym_h)).fillna(False)
    smt_bull = ((ref_close < ref_l) & ~(sym_close < sym_l)).fillna(False)
    return smt_bull.astype(bool), smt_bear.astype(bool)


# --------------------------------------------------------------------------- #
# Indicators
# --------------------------------------------------------------------------- #

def add_ict_indicators(df: pd.DataFrame, ref: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Compute the ICT indicator set.  Strictly causal — see module docstring.

    Parameters
    ----------
    df : OHLCV frame.
    ref : optional reference instrument (index) used for SMT divergence.
    """
    df = df.copy()
    open_p = df["Open"].astype(float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    n = len(df)
    idx = df.index

    # --- 1. ATR (Wilder), no back-fill -------------------------------------
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    if n:
        tr.iloc[0] = high.iloc[0] - low.iloc[0]
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["ATR"] = atr

    # --- 2. Displacement (body > 0.8 ATR) ----------------------------------
    body = (close - open_p).abs()
    df["Displacement_Bull"] = ((close > open_p) & (body > 0.8 * atr)).astype(bool)
    df["Displacement_Bear"] = ((close < open_p) & (body > 0.8 * atr)).astype(bool)

    # --- 3. FVG formation (3-candle imbalance) -----------------------------
    df["Bull_FVG"] = (low > high.shift(2)).astype(bool)
    df["Bear_FVG"] = (high < low.shift(2)).astype(bool)
    df["FVG_Top"] = np.where(
        df["Bull_FVG"], low, np.where(df["Bear_FVG"], low.shift(2), np.nan)
    )
    df["FVG_Bottom"] = np.where(
        df["Bull_FVG"], high.shift(2), np.where(df["Bear_FVG"], high, np.nan)
    )

    # --- 4. Fractal pivots (confirmation delay) ----------------------------
    ph_mask, pl_mask = _fractal_masks(high, low)
    high_lag2 = high.shift(2).to_numpy()
    low_lag2 = low.shift(2).to_numpy()

    # --- 5. Session / killzone --------------------------------------------
    is_intraday, session, open_kz, sb_kz, close_kz = _classify_sessions(idx)

    # --- 6. PD arrays & HTF bias (grouped, causal) -------------------------
    pdh, pdl = _previous_day_levels(df)
    pwh, pwl, wk_open = _previous_week_levels(df)

    # --- 7. State machine: pending FVG, liquidity pools, impulse legs ------
    fvg_dir = np.zeros(n, dtype=np.int8)
    fvg_top = np.full(n, np.nan)
    fvg_bot = np.full(n, np.nan)
    fvg_tap = np.zeros(n, dtype=bool)
    fvg_fill = np.zeros(n, dtype=bool)
    fvg_invalid = np.zeros(n, dtype=bool)

    liq_high = np.full(n, np.nan)
    liq_low = np.full(n, np.nan)
    swing_high = np.full(n, np.nan)
    swing_low = np.full(n, np.nan)
    eqh = np.zeros(n, dtype=np.int16)
    eql = np.zeros(n, dtype=np.int16)

    up_lo = np.full(n, np.nan)
    up_hi = np.full(n, np.nan)
    dn_lo = np.full(n, np.nan)
    dn_hi = np.full(n, np.nan)

    active_gap: Optional[Tuple[int, float, float]] = None  # (dir, bottom, top)
    pools_hi: List[Tuple[int, float]] = []                 # (source bar, price)
    pools_lo: List[Tuple[int, float]] = []
    last_ph: Optional[Tuple[int, float]] = None
    last_pl: Optional[Tuple[int, float]] = None
    up_leg: Optional[Tuple[float, float]] = None
    dn_leg: Optional[Tuple[float, float]] = None

    hi_arr = high.to_numpy()
    lo_arr = low.to_numpy()
    cl_arr = close.to_numpy()

    for i in range(n):
        a_t = atr.iat[i] if i < len(atr) else np.nan
        tol = 0.1 * a_t if a_t == a_t else 0.001 * cl_arr[i]

        # -- snapshot: state as of the START of bar i ----------------------
        if active_gap is not None:
            fvg_dir[i] = active_gap[0]
            fvg_bot[i] = active_gap[1]
            fvg_top[i] = active_gap[2]

        if pools_hi:
            liq_high[i] = pools_hi[-1][1]
            eqh[i] = sum(1 for _, p in pools_hi if abs(p - pools_hi[-1][1]) <= tol)
        if pools_lo:
            liq_low[i] = pools_lo[-1][1]
            eql[i] = sum(1 for _, p in pools_lo if abs(p - pools_lo[-1][1]) <= tol)
        if last_ph is not None:
            swing_high[i] = last_ph[1]
        if last_pl is not None:
            swing_low[i] = last_pl[1]
        if up_leg is not None:
            up_lo[i], up_hi[i] = up_leg
        if dn_leg is not None:
            dn_lo[i], dn_hi[i] = dn_leg

        # -- update with bar i's data --------------------------------------
        # pending FVG: tap / invalidation / full fill
        if active_gap is not None:
            d, bot, top = active_gap
            if d == 1:  # bullish gap zone [bot, top]
                if lo_arr[i] <= top and hi_arr[i] >= bot:
                    fvg_tap[i] = True
                if lo_arr[i] <= bot:
                    fvg_fill[i] = True
                if cl_arr[i] < bot:
                    fvg_invalid[i] = True
            else:  # bearish gap zone [bot, top]
                if hi_arr[i] >= bot and lo_arr[i] <= top:
                    fvg_tap[i] = True
                if hi_arr[i] >= top:
                    fvg_fill[i] = True
                if cl_arr[i] > top:
                    fvg_invalid[i] = True
            if fvg_tap[i] or fvg_invalid[i]:
                active_gap = None

        # a gap *formed* on bar i becomes tradeable from the next bar
        if df["Bull_FVG"].iat[i]:
            active_gap = (1, float(high_lag2[i]), float(lo_arr[i]))
        elif df["Bear_FVG"].iat[i]:
            active_gap = (-1, float(hi_arr[i]), float(low_lag2[i]))

        # fractal confirmation: the pivot that occurred at s = i - PIVOT
        s = i - PIVOT
        if s >= 0:
            if bool(ph_mask.iat[s]):
                last_ph = (s, float(hi_arr[s]))
                pools_hi.append((s, float(hi_arr[s])))
                if last_pl is not None and last_pl[0] < s:
                    up_leg = (last_pl[1], float(hi_arr[s]))
            if bool(pl_mask.iat[s]):
                last_pl = (s, float(lo_arr[s]))
                pools_lo.append((s, float(lo_arr[s])))
                if last_ph is not None and last_ph[0] < s:
                    dn_leg = (float(lo_arr[s]), last_ph[1])

        # liquidity pool is consumed the moment price trades back to it
        pools_hi = [(b, p) for (b, p) in pools_hi if not (hi_arr[i] >= p)]
        pools_lo = [(b, p) for (b, p) in pools_lo if not (lo_arr[i] <= p)]
        pools_hi = pools_hi[-20:]
        pools_lo = pools_lo[-20:]

        # structural invalidation of the impulse legs
        if up_leg is not None and cl_arr[i] < up_leg[0]:
            up_leg = None
        if dn_leg is not None and cl_arr[i] > dn_leg[1]:
            dn_leg = None

    df["FVG_Pending_Dir"] = fvg_dir
    df["FVG_Pending_Top"] = fvg_top
    df["FVG_Pending_Bottom"] = fvg_bot
    df["FVG_Tap"] = fvg_tap
    df["FVG_Fill"] = fvg_fill
    df["FVG_Invalid"] = fvg_invalid

    df["Liq_High"] = liq_high
    df["Liq_Low"] = liq_low
    df["Swing_High"] = swing_high
    df["Swing_Low"] = swing_low
    df["EQH"] = eqh
    df["EQL"] = eql

    df["UpLeg_Low"] = up_lo
    df["UpLeg_High"] = up_hi
    df["DnLeg_High"] = dn_hi
    df["DnLeg_Low"] = dn_lo

    # --- 8. Trailing extremes (kept: cheap liquidity-run reference) --------
    df["Swing_High_10"] = high.shift(1).rolling(10).max()
    df["Swing_Low_10"] = low.shift(1).rolling(10).min()
    df["Swing_High_5"] = high.shift(1).rolling(5).max()
    df["Swing_Low_5"] = low.shift(1).rolling(5).min()

    # --- 9. Trend anchor ---------------------------------------------------
    df["EMA_50"] = close.ewm(span=50, adjust=False).mean()

    # --- 10. RSI / MACD (never used for entries, kept for the UI) ----------
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14, min_periods=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI"] = 100 - (100 / (1 + rs))
    df["MACD"] = close.ewm(span=12, adjust=False).mean() - close.ewm(
        span=26, adjust=False
    ).mean()

    # --- 11. Premium / discount (equilibrium of the dealing range) ---------
    rng_high = high.rolling(DEALING_RANGE, min_periods=DEALING_RANGE // 2).max()
    rng_low = low.rolling(DEALING_RANGE, min_periods=DEALING_RANGE // 2).min()
    df["Range_High"] = rng_high
    df["Range_Low"] = rng_low
    df["Equilibrium"] = (rng_high + rng_low) / 2
    df["In_Premium"] = (close > df["Equilibrium"]).astype(bool)
    df["In_Discount"] = (close < df["Equilibrium"]).astype(bool)

    # --- 12. PD arrays & higher time frame --------------------------------
    df["PDH"] = pdh
    df["PDL"] = pdl
    df["PWH"] = pwh
    df["PWL"] = pwl
    df["Weekly_Open"] = wk_open
    df["HTF_Bias"] = _htf_bias(df)
    df["Session_Open"] = (
        open_p.groupby(pd.Index(idx.normalize())).transform("first")
        if isinstance(idx, pd.DatetimeIndex)
        else open_p
    )

    # --- 13. Session / killzone flags --------------------------------------
    df["Is_Intraday"] = is_intraday
    df["Session"] = session
    df["Opening_KZ"] = open_kz
    df["Silver_Bullet_KZ"] = sb_kz
    df["Closing_KZ"] = close_kz

    # --- 14. SMT divergence -------------------------------------------------
    smt_bull, smt_bear = _smt_columns(df, ref)
    df["SMT_Bull"] = smt_bull
    df["SMT_Bear"] = smt_bear

    # --- 15. 18 smoothed MA + the candle that last cut it ------------------
    # State as of the START of bar i: the most recent bar j < i whose low
    # traded down into/below the 18 SMMA (the "cut candle" for longs) and the
    # mirror for shorts (its high traded up through the line).  Each side
    # carries its own age, because in a trend one side's cut happens on almost
    # every bar while the other side's is rare — sharing an age would starve
    # the rare side of its setup.  Bar i's own test is deliberately *not*
    # included: the trigger candle must be judged against the line itself by
    # the strategy, not counted as its own pullback.
    smma = _smma(close, SMMA_LEN).to_numpy(dtype=float)
    cut_lo = np.full(n, np.nan)
    cut_hi = np.full(n, np.nan)
    cut_age = np.full(n, -1.0)
    cut_age_hi = np.full(n, -1.0)
    for i in range(1, n):
        for j in range(i - 1, max(-1, i - SMMA_CUT_LOOKBACK) - 1, -1):
            s_j = smma[j]
            if s_j != s_j:
                continue
            if cut_lo[i] != cut_lo[i] and lo_arr[j] <= s_j:
                cut_lo[i] = lo_arr[j]
                cut_age[i] = i - j
            if cut_hi[i] != cut_hi[i] and hi_arr[j] >= s_j:
                cut_hi[i] = hi_arr[j]
                cut_age_hi[i] = i - j
            if cut_lo[i] == cut_lo[i] and cut_hi[i] == cut_hi[i]:
                break

    df["SMMA_18"] = smma
    df["SMMA_Cut_Low"] = cut_lo       # long invalidation: low of the cut candle
    df["SMMA_Cut_High"] = cut_hi      # short invalidation: high of the cut candle
    df["SMMA_Cut_Age"] = cut_age      # bars since the long cut (-1 = none)
    df["SMMA_HiCut_Age"] = cut_age_hi  # bars since the short cut (-1 = none)

    # --- 16. SuperTrend indicator (period=10, multiplier=3.0) --------------
    st_val, st_dir, st_up, st_dn = _supertrend(
        hi_arr, lo_arr, cl_arr, SUPERTREND_PERIOD, SUPERTREND_MULTIPLIER
    )
    df["SuperTrend"] = st_val
    df["SuperTrend_Direction"] = st_dir
    df["SuperTrend_Upper"] = st_up
    df["SuperTrend_Lower"] = st_dn

    return df


# --------------------------------------------------------------------------- #
# Strategy catalogue
# --------------------------------------------------------------------------- #

def example_strategies() -> Dict[str, str]:
    return {
        "ict_fair_value_gap": "ICT Fair Value Gap (FVG) — enter when price mitigates a pending 3-candle imbalance, in the direction of the higher-time-frame draw",
        "ict_silver_bullet": "ICT Silver Bullet — liquidity raid + displacement/FVG inside the killzone window, drawn to opposing liquidity",
        "ict_order_block_mss": "ICT Order Block & MSS — structure shift with displacement, retest of the institutional candle (invalidation-aware)",
        "ict_liquidity_sweep_turtle_soup": "ICT Liquidity Sweep (Turtle Soup) — purge of a swing/PD liquidity pool with a rejection reclaim",
        "ict_optimal_trade_entry": "ICT Optimal Trade Entry (OTE) — 61.8%–78.6% retracement of a confirmed impulse leg, stop behind the leg",
        "ict_judas_swing": "ICT Judas Swing — session-open liquidity raid + institutional engulfing reversal",
        "ict_breaker_block": "ICT Breaker Block — failed order block retested from the opposite side",
        "ict_premium_discount": "ICT Premium/Discount — buy in discount, sell in premium around equilibrium, targets on liquidity",
        "ict_smt_divergence": "ICT SMT Divergence — index vs. symbol new-high/new-low divergence at premium/discount extremes",
        "smma_18_breakout": "18 Smoothed MA Breakout (4h) — clean expansion off a candle that cut the 18 SMMA; trigger candle must stay clear of the line, stop = cut candle low",
        "super_trend": "Super Trend (Daily / 4h) — buy on positive flip, sell on negative flip in equity stocks",
    }


# --------------------------------------------------------------------------- #
# Shared setup helpers
# --------------------------------------------------------------------------- #

def _draw(df: pd.DataFrame, i: int, side: str) -> Optional[float]:
    """Nearest liquidity pool the trade is drawn to, or None."""
    if side == "LONG":
        level = _s(df, i, "Liq_High")
        return level if level == level else None
    level = _s(df, i, "Liq_Low")
    return level if level == level else None


def _time_gate(df: pd.DataFrame, i: int, window: str) -> bool:
    """True when entries are allowed at this bar.

    Daily candles have no session, so the gate is open (a daily bar *is* the
    whole session).  Intraday candles must have their *span* touch ``window``
    ("open" or "silver_bullet") — span-based, so a 4h bar that opens at 08:00
    and contains the 09:25–10:25 window still passes.
    """
    if not _b(df, i, "Is_Intraday"):
        return True
    if window == "open":
        return _b(df, i, "Opening_KZ")
    if window == "silver_bullet":
        return _b(df, i, "Silver_Bullet_KZ")
    if window == "close":
        return _b(df, i, "Closing_KZ")
    return True


def _raid_low(df: pd.DataFrame, i: int) -> float:
    """Sell-side level the bar actually raided, or NaN if it raided none.

    The candidates are the resting pools below (liquidity pool, prior-day low,
    swing low).  The bar reports the *shallowest* one it traded through, so a
    caller that requires the close back above this level has proven a reclaim
    of every pool the bar took.  Asking for the minimum of all pools instead
    would demand the bar undercut every pool at once — a raid almost never does.
    """
    low = _s(df, i, "Low")
    cands = []
    liq = _s(df, i, "Liq_Low")
    if liq == liq:
        cands.append(liq)
    pdl = _s(df, i, "PDL")
    if pdl == pdl:
        cands.append(pdl)
    sw = _s(df, i, "Swing_Low")
    if sw == sw:
        cands.append(sw)
    breached = [x for x in cands if low < x]
    return max(breached) if breached else np.nan


def _raid_high(df: pd.DataFrame, i: int) -> float:
    """Buy-side level the bar actually raided, or NaN if it raided none.

    Mirror of :func:`_raid_low`: the *deepest* of the breached pools, so
    closing back below it proves every taken pool was rejected.
    """
    high = _s(df, i, "High")
    cands = []
    liq = _s(df, i, "Liq_High")
    if liq == liq:
        cands.append(liq)
    pdh = _s(df, i, "PDH")
    if pdh == pdh:
        cands.append(pdh)
    sw = _s(df, i, "Swing_High")
    if sw == sw:
        cands.append(sw)
    breached = [x for x in cands if high > x]
    return min(breached) if breached else np.nan


def _bias_ok(df: pd.DataFrame, i: int, side: str) -> bool:
    """Higher-time-frame alignment filter (0 = neutral, allowed both ways)."""
    bias = int(_s(df, i, "HTF_Bias"))
    if side == "LONG":
        return bias >= 0
    return bias <= 0


# --------------------------------------------------------------------------- #
# 1. Fair Value Gap
# --------------------------------------------------------------------------- #

def ict_fair_value_gap(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Fair Value Gap mitigation.

    A gap is only actionable while it is still *pending* (never traded into,
    never invalidated by a close through it).  Entry happens on the bar that
    taps it, provided the close is back inside the gap — that tap is the
    mitigation ICT traders wait for.  Stop sits behind the gap, target is the
    opposing liquidity pool.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)

    # ---- exits ----------------------------------------------------------
    struct_long = _s(df, i, "Swing_Low")
    struct_short = _s(df, i, "Swing_High")
    if side == "LONG":
        if struct_long == struct_long and close < struct_long:
            return Signal("SELL", reason="Structure break below last swing low")
        if _b(df, i, "FVG_Tap") and _s(df, i, "FVG_Pending_Dir") == -1:
            return Signal("SELL", reason="Opposing (bearish) FVG mitigated — de-risk")
        return Signal()
    if side == "SHORT":
        if struct_short == struct_short and close > struct_short:
            return Signal("COVER", reason="Structure break above last swing high")
        if _b(df, i, "FVG_Tap") and _s(df, i, "FVG_Pending_Dir") == 1:
            return Signal("COVER", reason="Opposing (bullish) FVG mitigated — de-risk")
        return Signal()

    # ---- entries --------------------------------------------------------
    pending = int(_s(df, i, "FVG_Pending_Dir"))
    if not _b(df, i, "FVG_Tap") or _b(df, i, "FVG_Invalid"):
        return Signal()

    if pending == 1 and close >= _s(df, i, "FVG_Pending_Bottom") and close >= open_p:
        if close >= _s(df, i, "EMA_50") and _bias_ok(df, i, "LONG"):
            bot = _s(df, i, "FVG_Pending_Bottom")
            top = _s(df, i, "FVG_Pending_Top")
            stop = bot - 0.2 * atr
            return Signal(
                "BUY",
                reason=f"Bullish FVG mitigation [₹{bot:.2f} – ₹{top:.2f}]",
                stop_price=stop,
                target_price=_draw(df, i, "LONG"),
            )
    if pending == -1 and close <= _s(df, i, "FVG_Pending_Top") and close <= open_p:
        if close <= _s(df, i, "EMA_50") and _bias_ok(df, i, "SHORT"):
            bot = _s(df, i, "FVG_Pending_Bottom")
            top = _s(df, i, "FVG_Pending_Top")
            stop = top + 0.2 * atr
            return Signal(
                "SHORT",
                reason=f"Bearish FVG mitigation [₹{bot:.2f} – ₹{top:.2f}]",
                stop_price=stop,
                target_price=_draw(df, i, "SHORT"),
            )
    return Signal()


# --------------------------------------------------------------------------- #
# 2. Silver Bullet
# --------------------------------------------------------------------------- #

def ict_silver_bullet(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Silver Bullet.

    1. Liquidity run — price raids a sell-side pool (swing / prior-day low)
       within the last few bars.
    2. Displacement — the reversal is confirmed by a displacement candle or a
       fresh bullish FVG.
    3. Draw — buy-side liquidity at the opposing pool.

    On intraday candles the entry is gated to the Silver Bullet window; on
    daily candles the whole bar is the window.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    struct_long = _s(df, i, "Swing_Low")
    struct_short = _s(df, i, "Swing_High")

    if side == "LONG":
        if struct_long == struct_long and close < struct_long:
            return Signal("SELL", reason="Silver Bullet thesis broken (structure)")
        return Signal()
    if side == "SHORT":
        if struct_short == struct_short and close > struct_short:
            return Signal("COVER", reason="Silver Bullet thesis broken (structure)")
        return Signal()

    sb_window = _time_gate(df, i, "silver_bullet")
    open_window = _time_gate(df, i, "open")
    if not (sb_window or open_window):
        return Signal()

    # raid of sell-side liquidity in the last SWEEP_LOOKBACK bars
    start = max(1, i - SWEEP_LOOKBACK)
    swept_low = False
    sweep_low = np.nan
    for j in range(start, i + 1):
        level = _raid_low(df, j)
        if level == level and _s(df, j, "Low") < level:
            swept_low = True
            sweep_low = min(sweep_low, level) if sweep_low == sweep_low else level
    swept_high = False
    sweep_high = np.nan
    for j in range(start, i + 1):
        level = _raid_high(df, j)
        if level == level and _s(df, j, "High") > level:
            swept_high = True
            sweep_high = max(sweep_high, level) if sweep_high == sweep_high else level

    disp_up = _b(df, i, "Displacement_Bull") or (
        int(_s(df, i, "FVG_Pending_Dir")) == 1 and _b(df, i, "FVG_Tap")
    )
    disp_dn = _b(df, i, "Displacement_Bear") or (
        int(_s(df, i, "FVG_Pending_Dir")) == -1 and _b(df, i, "FVG_Tap")
    )

    if swept_low and disp_up and close > open_p and close >= sweep_low:
        if _bias_ok(df, i, "LONG"):
            stop = min(sweep_low, _s(df, i, "Low")) - 0.15 * atr
            return Signal(
                "BUY",
                reason="Silver Bullet: SSL raid + bullish displacement → BSL draw",
                stop_price=stop,
                target_price=_draw(df, i, "LONG"),
            )
    if swept_high and disp_dn and close < open_p and close <= sweep_high:
        if _bias_ok(df, i, "SHORT"):
            stop = max(sweep_high, _s(df, i, "High")) + 0.15 * atr
            return Signal(
                "SHORT",
                reason="Silver Bullet: BSL raid + bearish displacement → SSL draw",
                stop_price=stop,
                target_price=_draw(df, i, "SHORT"),
            )
    return Signal()


# --------------------------------------------------------------------------- #
# 3. Order block + market structure shift
# --------------------------------------------------------------------------- #

def ict_order_block_mss(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Order Block after a Market Structure Shift.

    MSS      — a displacement candle closes through the last untested swing
               point (structure shift).
    OB       — the last opposing candle before that displacement.
    retest   — price returns to the OB within ``OB_RETEST_BARS`` bars, *and*
               the OB was never violated (closed through) in between.
    stop     — behind the OB, target — the opposing pool.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    low = _s(df, i, "Low")
    high = _s(df, i, "High")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    struct_long = _s(df, i, "Swing_Low")
    struct_short = _s(df, i, "Swing_High")

    if side == "LONG":
        if struct_long == struct_long and close < struct_long:
            return Signal("SELL", reason="Structure failed below swing low")
        return Signal()
    if side == "SHORT":
        if struct_short == struct_short and close > struct_short:
            return Signal("COVER", reason="Structure failed above swing high")
        return Signal()

    # --- bullish MSS → long retest ---------------------------------------
    for off in range(2, OB_RETEST_BARS + 1):
        s = i - off
        if s < 4:
            continue
        pool = _s(df, s, "Liq_High")
        if (
            pool == pool
            and _s(df, s, "Close") > pool
            and _b(df, s, "Displacement_Bull")
        ):
            for ob_off in range(1, 4):
                o = s - ob_off
                if o < 0:
                    break
                if _s(df, o, "Close") < _s(df, o, "Open"):  # last down candle
                    ob_lo = _s(df, o, "Low")
                    ob_hi = _s(df, o, "High")
                    violated = any(
                        _s(df, k, "Close") < ob_lo for k in range(s + 1, i + 1)
                    )
                    if violated:
                        break  # OB is no longer valid — skip this MSS
                    if low <= ob_hi and close >= ob_lo and close >= open_p:
                        return Signal(
                            "BUY",
                            reason=f"Bullish OB retest after MSS [₹{ob_lo:.2f} – ₹{ob_hi:.2f}]",
                            stop_price=ob_lo - 0.15 * atr,
                            target_price=_draw(df, i, "LONG"),
                        )
                    break

    # --- bearish MSS → short retest --------------------------------------
    for off in range(2, OB_RETEST_BARS + 1):
        s = i - off
        if s < 4:
            continue
        pool = _s(df, s, "Liq_Low")
        if (
            pool == pool
            and _s(df, s, "Close") < pool
            and _b(df, s, "Displacement_Bear")
        ):
            for ob_off in range(1, 4):
                o = s - ob_off
                if o < 0:
                    break
                if _s(df, o, "Close") > _s(df, o, "Open"):  # last up candle
                    ob_lo = _s(df, o, "Low")
                    ob_hi = _s(df, o, "High")
                    violated = any(
                        _s(df, k, "Close") > ob_hi for k in range(s + 1, i + 1)
                    )
                    if violated:
                        break
                    if high >= ob_lo and close <= ob_hi and close <= open_p:
                        return Signal(
                            "SHORT",
                            reason=f"Bearish OB retest after MSS [₹{ob_lo:.2f} – ₹{ob_hi:.2f}]",
                            stop_price=ob_hi + 0.15 * atr,
                            target_price=_draw(df, i, "SHORT"),
                        )
                    break
    return Signal()


# --------------------------------------------------------------------------- #
# 4. Liquidity sweep / Turtle Soup
# --------------------------------------------------------------------------- #

def ict_liquidity_sweep_turtle_soup(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Liquidity Sweep / Turtle Soup reversal.

    Price purges a resting pool (fractal swing or prior-day low/high), then
    rejects it: the close is back inside the range and the wick shows
    absorption.  Stop sits behind the sweep, target is the opposing pool.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    high = _s(df, i, "High")
    low = _s(df, i, "Low")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if struct == struct and close < struct:
            return Signal("SELL", reason="Sweep thesis failed (close below structure)")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if struct == struct and close > struct:
            return Signal("COVER", reason="Sweep thesis failed (close above structure)")
        return Signal()

    bar_range = high - low

    # --- same-bar purge + reclaim ----------------------------------------
    lvl_low = _raid_low(df, i)
    if lvl_low == lvl_low and low < lvl_low and close > lvl_low:
        lower_wick = min(open_p, close) - low
        absorption = (lower_wick / (bar_range + 1e-6)) >= 0.35 or close > open_p
        if absorption and _bias_ok(df, i, "LONG"):
            return Signal(
                "BUY",
                reason=f"Turtle Soup: SSL purged (₹{low:.2f} < ₹{lvl_low:.2f}), reclaimed",
                stop_price=low - 0.15 * atr,
                target_price=_draw(df, i, "LONG"),
            )

    lvl_high = _raid_high(df, i)
    if lvl_high == lvl_high and high > lvl_high and close < lvl_high:
        upper_wick = high - max(open_p, close)
        absorption = (upper_wick / (bar_range + 1e-6)) >= 0.35 or close < open_p
        if absorption and _bias_ok(df, i, "SHORT"):
            return Signal(
                "SHORT",
                reason=f"Turtle Soup: BSL purged (₹{high:.2f} > ₹{lvl_high:.2f}), rejected",
                stop_price=high + 0.15 * atr,
                target_price=_draw(df, i, "SHORT"),
            )

    # --- purge on the previous bar, confirmation now ----------------------
    if i >= 1:
        prev_lvl = _raid_low(df, i - 1)
        if prev_lvl == prev_lvl and _s(df, i - 1, "Low") < prev_lvl:
            if close > prev_lvl and close > open_p and _bias_ok(df, i, "LONG"):
                return Signal(
                    "BUY",
                    reason="Turtle Soup: confirmation reclaim of swept SSL",
                    stop_price=min(low, _s(df, i - 1, "Low")) - 0.15 * atr,
                    target_price=_draw(df, i, "LONG"),
                )
        prev_lvl_h = _raid_high(df, i - 1)
        if prev_lvl_h == prev_lvl_h and _s(df, i - 1, "High") > prev_lvl_h:
            if close < prev_lvl_h and close < open_p and _bias_ok(df, i, "SHORT"):
                return Signal(
                    "SHORT",
                    reason="Turtle Soup: confirmation rejection of swept BSL",
                    stop_price=max(high, _s(df, i - 1, "High")) + 0.15 * atr,
                    target_price=_draw(df, i, "SHORT"),
                )
    return Signal()


# --------------------------------------------------------------------------- #
# 5. Optimal Trade Entry
# --------------------------------------------------------------------------- #

def ict_optimal_trade_entry(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Optimal Trade Entry.

    The dealing range is a *confirmed impulse leg* (pivot low → pivot high for
    longs).  Entry is the 61.8–78.6% retracement of that leg, taken only while
    the structure that defines the leg is still intact and the higher time
    frame agrees.  Stop sits behind the leg origin, target is the leg high
    (external range liquidity).
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    low = _s(df, i, "Low")
    high = _s(df, i, "High")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)

    up_lo, up_hi = _s(df, i, "UpLeg_Low"), _s(df, i, "UpLeg_High")
    dn_hi, dn_lo = _s(df, i, "DnLeg_High"), _s(df, i, "DnLeg_Low")

    # ---- exits ----------------------------------------------------------
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if struct == struct and close < struct:
            return Signal("SELL", reason="Structure break — OTE long invalidated")
        if up_lo == up_lo and close < up_lo:
            return Signal("SELL", reason="Impulse leg origin lost")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if struct == struct and close > struct:
            return Signal("COVER", reason="Structure break — OTE short invalidated")
        if dn_hi == dn_hi and close > dn_hi:
            return Signal("COVER", reason="Impulse leg origin lost")
        return Signal()

    # ---- long OTE -------------------------------------------------------
    if up_lo == up_lo and up_hi == up_hi and _bias_ok(df, i, "LONG"):
        rng = up_hi - up_lo
        if rng >= 1.5 * atr:
            zone_top = up_lo + 0.382 * rng     # 61.8% retracement
            zone_bot = up_lo + 0.214 * rng     # 78.6% retracement
            if low <= zone_top and close >= zone_bot and close >= open_p:
                return Signal(
                    "BUY",
                    reason=f"OTE long: 61.8–78.6% discount of leg [₹{zone_bot:.2f} – ₹{zone_top:.2f}]",
                    stop_price=up_lo - 0.15 * atr,
                    target_price=up_hi,
                )

    # ---- short OTE ------------------------------------------------------
    if dn_hi == dn_hi and dn_lo == dn_lo and _bias_ok(df, i, "SHORT"):
        rng = dn_hi - dn_lo
        if rng >= 1.5 * atr:
            zone_bot = dn_hi - 0.382 * rng     # 61.8% retracement of the down leg
            zone_top = dn_hi - 0.214 * rng
            if high >= zone_bot and close <= zone_top and close <= open_p:
                return Signal(
                    "SHORT",
                    reason=f"OTE short: 61.8–78.6% premium of leg [₹{zone_bot:.2f} – ₹{zone_top:.2f}]",
                    stop_price=dn_hi + 0.15 * atr,
                    target_price=dn_lo,
                )
    return Signal()


# --------------------------------------------------------------------------- #
# 6. Judas Swing
# --------------------------------------------------------------------------- #

def ict_judas_swing(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Judas Swing — opening manipulation / bear trap.

    Requirements (all of them):

      * time    — inside the opening killzone (intraday candles only);
      * raid    — the bar trades *through* a key sell-side level (prior-day low
                  or the last swing low): the Judas move engineers liquidity;
      * reclaim — price closes back above the level;
      * engulf  — the close is above the previous candle's open (institutional
                  engulfing, the tell that the raid was manipulation);
      * trend   — higher time frame not against the trade.

    The Judas low itself is the invalidation, so the stop is mechanical.
    """
    if i < MIN_BARS or i < 2:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    high = _s(df, i, "High")
    low = _s(df, i, "Low")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if struct == struct and close < struct:
            return Signal("SELL", reason="Judas long invalidated (structure)")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if struct == struct and close > struct:
            return Signal("COVER", reason="Judas short invalidated (structure)")
        return Signal()

    if not _time_gate(df, i, "open"):
        return Signal()

    prev_open = _s(df, i - 1, "Open")
    prev_close = _s(df, i - 1, "Close")
    bias = int(_s(df, i, "HTF_Bias"))
    ema = _s(df, i, "EMA_50")

    total_range = high - low

    # --- bullish Judas: raid below a key low, engulf back up --------------
    raid = _raid_low(df, i)
    if raid == raid and low < raid and close > raid and close >= ema and bias >= 0:
        if (
            total_range > 0.5 * atr
            and close > open_p
            and close > prev_open
            and close > prev_close
            and ((close - low) / (total_range + 1e-6)) >= 0.55
        ):
            return Signal(
                "BUY",
                reason=f"Judas Swing: raid of ₹{raid:.2f} + institutional engulfing",
                stop_price=low - 0.15 * atr,
                target_price=_draw(df, i, "LONG"),
            )

    # --- bearish Judas: raid above a key high, engulf down ----------------
    raid_h = _raid_high(df, i)
    if raid_h == raid_h and high > raid_h and close < raid_h and close <= ema and bias <= 0:
        if (
            total_range > 0.5 * atr
            and close < open_p
            and close < prev_open
            and close < prev_close
            and ((high - close) / (total_range + 1e-6)) >= 0.55
        ):
            return Signal(
                "SHORT",
                reason=f"Judas Swing: raid of ₹{raid_h:.2f} + institutional engulfing",
                stop_price=high + 0.15 * atr,
                target_price=_draw(df, i, "SHORT"),
            )
    return Signal()


# --------------------------------------------------------------------------- #
# 7. Breaker block
# --------------------------------------------------------------------------- #

def ict_breaker_block(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Breaker Block — a failed order block, traded from the other side.

    Long : an *up-close* candle (a former bearish order block) is violated to
           the upside with displacement, then retested from above.  What used
           to be supply is now demand.
    Short: the mirror — a down-close candle violated to the downside and
           retested from below.

    The breaker is only valid while no bar has closed back through the origin
    candle's far side.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    low = _s(df, i, "Low")
    high = _s(df, i, "High")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if struct == struct and close < struct:
            return Signal("SELL", reason="Breaker long lost (structure)")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if struct == struct and close > struct:
            return Signal("COVER", reason="Breaker short lost (structure)")
        return Signal()

    # --- bullish breaker: up-close candle, violated up, retested from above
    for j in range(i - 3, max(2, i - BREAKER_LOOKBACK), -1):
        if _s(df, j, "Close") <= _s(df, j, "Open"):
            continue  # must be an up-close candle (former bearish OB)
        ob_lo = _s(df, j, "Low")
        ob_hi = _s(df, j, "High")
        violation = None
        for k in range(j + 1, i):
            if _s(df, k, "Close") > ob_hi and _b(df, k, "Displacement_Bull"):
                violation = k
                break
        if violation is None:
            continue
        if any(_s(df, k, "Close") < ob_lo for k in range(violation + 1, i + 1)):
            continue  # breaker failed — closed back through it
        if low <= ob_hi and close >= ob_lo and close >= open_p:
            return Signal(
                "BUY",
                reason=f"Bullish breaker retest [₹{ob_lo:.2f} – ₹{ob_hi:.2f}]",
                stop_price=ob_lo - 0.15 * atr,
                target_price=_draw(df, i, "LONG"),
            )
        break  # only the most recent origin candle qualifies

    # --- bearish breaker ---------------------------------------------------
    for j in range(i - 3, max(2, i - BREAKER_LOOKBACK), -1):
        if _s(df, j, "Close") >= _s(df, j, "Open"):
            continue  # must be a down-close candle (former bullish OB)
        ob_lo = _s(df, j, "Low")
        ob_hi = _s(df, j, "High")
        violation = None
        for k in range(j + 1, i):
            if _s(df, k, "Close") < ob_lo and _b(df, k, "Displacement_Bear"):
                violation = k
                break
        if violation is None:
            continue
        if any(_s(df, k, "Close") > ob_hi for k in range(violation + 1, i + 1)):
            continue
        if high >= ob_lo and close <= ob_hi and close <= open_p:
            return Signal(
                "SHORT",
                reason=f"Bearish breaker retest [₹{ob_lo:.2f} – ₹{ob_hi:.2f}]",
                stop_price=ob_hi + 0.15 * atr,
                target_price=_draw(df, i, "SHORT"),
            )
        break
    return Signal()


# --------------------------------------------------------------------------- #
# 8. Premium / discount
# --------------------------------------------------------------------------- #

def ict_premium_discount(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT Premium/Discount equilibrium.

    The dealing range's 50% level is equilibrium: in an uptrend discount is
    bought (target: the premium side / buy-side pool), in a downtrend premium
    is sold.  Position is only taken while structure is intact, and the stop
    sits behind the range — invalidation, not a percentage.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    atr = _s(df, i, "ATR")
    eq = _s(df, i, "Equilibrium")
    rng_hi = _s(df, i, "Range_High")
    rng_lo = _s(df, i, "Range_Low")
    if atr != atr or eq != eq:
        return Signal()

    side = getattr(position, "side", None)
    struct_long = _s(df, i, "Swing_Low")
    struct_short = _s(df, i, "Swing_High")

    if side == "LONG":
        if struct_long == struct_long and close < struct_long:
            return Signal("SELL", reason="Discount buy: structure broken")
        return Signal()
    if side == "SHORT":
        if struct_short == struct_short and close > struct_short:
            return Signal("COVER", reason="Premium sell: structure broken")
        return Signal()

    ema = _s(df, i, "EMA_50")
    bias = int(_s(df, i, "HTF_Bias"))

    if bias >= 0 and close < eq and close >= ema and close > open_p:
        if struct_long == struct_long and close > struct_long:
            return Signal(
                "BUY",
                reason=f"Discount buy below equilibrium ₹{eq:.2f} (uptrend)",
                stop_price=rng_lo - 0.15 * atr,
                target_price=_draw(df, i, "LONG") or rng_hi,
            )
    if bias <= 0 and close > eq and close <= ema and close < open_p:
        if struct_short == struct_short and close < struct_short:
            return Signal(
                "SHORT",
                reason=f"Premium sell above equilibrium ₹{eq:.2f} (downtrend)",
                stop_price=rng_hi + 0.15 * atr,
                target_price=_draw(df, i, "SHORT") or rng_lo,
            )
    return Signal()


# --------------------------------------------------------------------------- #
# 9. SMT divergence
# --------------------------------------------------------------------------- #

def ict_smt_divergence(df: pd.DataFrame, i: int, position=None) -> Signal:
    """ICT SMT divergence (index vs. symbol).

    Bearish SMT — the index prints a new 10-bar high while the symbol does not:
    the rally is no longer being confirmed.  Taken only in premium and only
    with a rejecting candle; the stop sits above the symbol's own high.
    """
    if i < MIN_BARS:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    high = _s(df, i, "High")
    low = _s(df, i, "Low")
    atr = _s(df, i, "ATR")
    if atr != atr:
        return Signal()

    side = getattr(position, "side", None)
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if struct == struct and close < struct:
            return Signal("SELL", reason="SMT long invalidated (structure)")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if struct == struct and close > struct:
            return Signal("COVER", reason="SMT short invalidated (structure)")
        return Signal()

    if _b(df, i, "SMT_Bear") and _b(df, i, "In_Premium") and close < open_p:
        stop_hi = max(high, _s(df, i, "Swing_High")) if _s(df, i, "Swing_High") == _s(df, i, "Swing_High") else high
        return Signal(
            "SHORT",
            reason="Bearish SMT at highs (index leads down, symbol lags)",
            stop_price=stop_hi + 0.15 * atr,
            target_price=_draw(df, i, "SHORT"),
        )
    if _b(df, i, "SMT_Bull") and _b(df, i, "In_Discount") and close > open_p:
        stop_lo = min(low, _s(df, i, "Swing_Low")) if _s(df, i, "Swing_Low") == _s(df, i, "Swing_Low") else low
        return Signal(
            "BUY",
            reason="Bullish SMT at lows (index leads down, symbol holds)",
            stop_price=stop_lo - 0.15 * atr,
            target_price=_draw(df, i, "LONG"),
        )
    return Signal()


# --------------------------------------------------------------------------- #
# 10. 18 smoothed-MA breakout
# --------------------------------------------------------------------------- #

def _is_consolidation_bar(df: pd.DataFrame, j: int) -> bool:
    """An overlapping, indecisive candle — the chop this setup must avoid."""
    o, c = _s(df, j, "Open"), _s(df, j, "Close")
    h, l = _s(df, j, "High"), _s(df, j, "Low")
    atr_j = _s(df, j, "ATR")
    if atr_j != atr_j:
        return False
    small = abs(c - o) < SMMA_CLEAN_BODY * atr_j
    if j == 0:
        return bool(small)
    hp, lp = _s(df, j - 1, "High"), _s(df, j - 1, "Low")
    return bool(small and l <= hp and h >= lp)


def _clean_expansion(df: pd.DataFrame, start: int, end: int, up: bool) -> bool:
    """Bars ``start+1 … end`` form one clean leg: no consolidation candle and
    no pullback — i.e. the move happened *without* chopping sideways."""
    for j in range(max(start, 0) + 1, end + 1):
        if _is_consolidation_bar(df, j):
            return False
        if up and _s(df, j, "Close") < _s(df, j - 1, "Close"):
            return False
        if not up and _s(df, j, "Close") > _s(df, j - 1, "Close"):
            return False
    return True


def smma_18_breakout(df: pd.DataFrame, i: int, position=None) -> Signal:
    """18 smoothed-MA breakout (designed for 4-hour candles).

    The setup, in the order the market prints it:

      1. **cut candle** — a candle trades down into/below the 18 smoothed MA
         (Wilder smoothing).  Its low is the invalidation of the whole idea;
      2. **breakout** — the next-but-one candle breaks *up* out of the
         previous candle's high with a displacement body, and the whole run
         from the cut candle to the breakout is one clean leg: no overlapping
         indecisive candles, no pullback closes (``_clean_expansion``);
      3. **trigger** — the candle *after* the breakout never trades down to
         the 18 MA (its low stays clear of the line): momentum is holding
         away from the mean → go long on that candle's close.

    Stop = the low of the cut candle (the candle that cut the 18 MA).
    Target = the nearest draw on liquidity above; the position is also closed
    if price closes back under the 18 MA or breaks the last swing low.

    The mirror setup (break below the prior low, trigger high clear of the
    line, stop above the cut candle's high) shorts.
    """
    if i < max(MIN_BARS, SMMA_LEN) or i < 3:
        return Signal()

    close = _s(df, i, "Close")
    open_p = _s(df, i, "Open")
    high = _s(df, i, "High")
    low = _s(df, i, "Low")
    atr = _s(df, i, "ATR")
    smma = _s(df, i, "SMMA_18")
    if atr != atr or smma != smma:
        return Signal()

    # ---- exits ------------------------------------------------------------
    side = getattr(position, "side", None)
    if side == "LONG":
        struct = _s(df, i, "Swing_Low")
        if close < smma:
            return Signal("SELL", reason="18 SMMA lost (close back under the mean)")
        if struct == struct and close < struct:
            return Signal("SELL", reason="18 SMMA: structure break below swing low")
        return Signal()
    if side == "SHORT":
        struct = _s(df, i, "Swing_High")
        if close > smma:
            return Signal("COVER", reason="18 SMMA regained (close back over the mean)")
        if struct == struct and close > struct:
            return Signal("COVER", reason="18 SMMA: structure break above swing high")
        return Signal()

    # ---- setup ------------------------------------------------------------
    b, bb = i - 1, i - 2        # breakout candle, the candle it broke out of
    cb, ob = _s(df, b, "Close"), _s(df, b, "Open")
    atr_b = _s(df, b, "ATR")
    if atr_b != atr_b:
        return Signal()

    # long: break up out of the prior candle, displacement body, clean run,
    # and the trigger candle's low never reaches the 18 MA
    age_lo = _s(df, i, "SMMA_Cut_Age")
    cut_lo = _s(df, i, "SMMA_Cut_Low")
    broke_up = (
        cb > _s(df, bb, "High")
        and cb > ob
        and (cb - ob) > SMMA_BREAK_BODY * atr_b
    )
    if (
        age_lo == age_lo
        and 2 <= age_lo <= SMMA_CUT_LOOKBACK   # cut strictly before the break
        and cut_lo == cut_lo
        and broke_up
        and _clean_expansion(df, i - int(age_lo), b, up=True)
        and low > smma
    ):
        return Signal(
            "BUY",
            reason=f"18 SMMA breakout: clean expansion, trigger low clear of the line "
                   f"(cut candle low ₹{cut_lo:.2f})",
            stop_price=cut_lo,
            target_price=_draw(df, i, "LONG"),
        )

    # short: the mirror
    age_hi = _s(df, i, "SMMA_HiCut_Age")
    cut_hi = _s(df, i, "SMMA_Cut_High")
    broke_dn = (
        cb < _s(df, bb, "Low")
        and cb < ob
        and (ob - cb) > SMMA_BREAK_BODY * atr_b
    )
    if (
        age_hi == age_hi
        and 2 <= age_hi <= SMMA_CUT_LOOKBACK
        and cut_hi == cut_hi
        and broke_dn
        and _clean_expansion(df, i - int(age_hi), b, up=False)
        and high < smma
    ):
        return Signal(
            "SHORT",
            reason=f"18 SMMA breakout: clean expansion down, trigger high clear of the line "
                   f"(cut candle high ₹{cut_hi:.2f})",
            stop_price=cut_hi,
            target_price=_draw(df, i, "SHORT"),
        )
    return Signal()


def super_trend(df: pd.DataFrame, i: int, position=None) -> Signal:
    """Super Trend Strategy (Daily / 4-Hour timeframe).

    Designed for Indian equity cash/delivery stocks:
      - Buy (LONG) when SuperTrend turns positive (bullish flip above upper band).
      - Sell (EXIT LONG) when SuperTrend turns negative (bearish flip below lower band).
      - Long-only: never shorts equity stocks.
      - Structural stop-loss set to the SuperTrend line value at entry.
    """
    if i < max(MIN_BARS, SUPERTREND_PERIOD) or i < 1:
        return Signal()

    st = _s(df, i, "SuperTrend")
    trend = _s(df, i, "SuperTrend_Direction")
    if st != st or trend != trend:
        return Signal()

    prev_trend = _s(df, i - 1, "SuperTrend_Direction")
    side = getattr(position, "side", None)

    # 1. Exit open long if SuperTrend becomes negative
    if side == "LONG":
        if trend == -1:
            return Signal(
                "SELL",
                reason=f"Super Trend turned negative (bearish flip below ₹{st:.2f})",
            )
        return Signal()

    # 2. Buy if SuperTrend becomes positive (bullish crossover / flip)
    if trend == 1 and prev_trend <= 0:
        return Signal(
            "BUY",
            reason=f"Super Trend turned positive (bullish flip above ₹{st:.2f})",
            stop_price=st,
        )

    return Signal()


STRATEGY_MAP = {
    "ict_fair_value_gap": ict_fair_value_gap,
    "ict_silver_bullet": ict_silver_bullet,
    "ict_order_block_mss": ict_order_block_mss,
    "ict_liquidity_sweep_turtle_soup": ict_liquidity_sweep_turtle_soup,
    "ict_optimal_trade_entry": ict_optimal_trade_entry,
    "ict_judas_swing": ict_judas_swing,
    "ict_breaker_block": ict_breaker_block,
    "ict_premium_discount": ict_premium_discount,
    "ict_smt_divergence": ict_smt_divergence,
    "smma_18_breakout": smma_18_breakout,
    "super_trend": super_trend,
}
