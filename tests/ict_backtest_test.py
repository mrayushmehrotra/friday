"""Self-contained verification of the ICT backtesting stack.

Run from the repo root:

    .venv/bin/python tests/ict_backtest_test.py

No pytest required — every check raises AssertionError with a useful message
and the script exits non-zero on the first failure (or reports the total when
run with ``--keep-going``).

What is verified
----------------
1.  **Indicator causality** — the indicator frame computed on a *prefix* of the
    data equals the full frame's rows for that prefix.  Any back-fill, any
    centered window, any future-dependent state machine fails this.
2.  **Signal causality** — every strategy's signal at bar ``i`` is identical
    whether computed on the full frame or on a frame truncated at ``i + 1``.
3.  **Accounting** — ``pnl`` and ``pnl_pct`` always share a sign, and ``pnl``
    is exactly reproducible from prices, size and commission.
4.  **Trade sanity** — no exit before entry, no non-positive size, equity
    curve length matches the bar count, all values finite.
5.  **Coverage** — all ten strategies run, and the short side is actually
    traded (the audit's biggest gap).
6.  **Hygiene** — no ``bfill`` anywhere in the strategy/engine sources.
7.  **18 SMMA setup** — the mean, the cut-candle state and the trigger are
    re-derived independently, and the exact setup you described (breakout →
    trigger clear of the line → stop on the cut candle) is reproduced on
    scripted candles, with the negative cases (trigger touching the line,
    consolidation in between) asserted to stay flat.
8.  **4h bars** — 1h candles aggregate to 4h bars with the right OHLC and no
    cross-bucket leakage.
"""

from __future__ import annotations

import sys
import os
from typing import List

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_tools import (  # noqa: E402
    STRATEGY_MAP,
    fetch_data,
    run_backtest,
    add_indicators,
    format_result_json,
    resample_to_4h,
)
import ict_strategies  # noqa: E402


FAILURES: List[str] = []
CHECKS = 0
KEEP_GOING = "--keep-going" in sys.argv


def check(name: str, cond: bool, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    if cond:
        print(f"  ok   {name}")
        return
    msg = f"{name}: {detail}" if detail else name
    print(f"  FAIL {msg}")
    FAILURES.append(msg)
    if not KEEP_GOING:
        raise AssertionError(msg)


def _synthetic(n: int = 700, seed: int = 7) -> pd.DataFrame:
    """Deterministic random walk — used only if the network fetch fails."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0004, 0.012, n)
    close = 2500 * np.cumprod(1 + rets)
    open_ = np.roll(close, 1)
    open_[0] = close[0]
    hi = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lo = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": hi, "Low": lo, "Close": close,
         "Volume": rng.integers(1e5, 5e6, n)},
        index=idx,
    )


def _load():
    try:
        df, source = fetch_data("RELIANCE.NS", start="2y", interval="1d")
        ref, _ = fetch_data("^NSEI", start="2y", interval="1d")
        print(f"  data: {source} ({len(df)} bars, ref {len(ref)} bars)")
        return df, ref
    except Exception as e:  # network unavailable — still exercise everything
        print(f"  WARNING: live fetch failed ({e}); using synthetic data")
        return _synthetic(), _synthetic(seed=11)


# ---------------------------------------------------------------- causality --

def test_indicator_causality(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[1] indicator causality (prefix == full-frame rows)")
    full = add_indicators(df.copy(), ref=ref)
    ref_full = add_indicators(ref.copy())

    for cut in (40, 97, 211, len(df) // 2, len(df) - 1):
        # keep every reference bar up to the last timestamp in the prefix, so
        # forward-fill of the reference has exactly the data it had before
        ref_prefix = ref[ref.index <= df.index[cut - 1]]
        trunc = add_indicators(df.iloc[:cut].copy(), ref=ref_prefix)
        a, b = full.iloc[:cut], trunc
        bad = []
        if len(a) != len(b):
            bad.append(f"length {len(a)} != {len(b)}")
        else:
            for col in a.columns:
                sa, sb = a[col], b[col]
                if pd.api.types.is_bool_dtype(sa) or pd.api.types.is_bool_dtype(sb):
                    same = (sa.fillna(False).astype(bool)
                            == sb.fillna(False).astype(bool)).all()
                elif pd.api.types.is_numeric_dtype(sa):
                    same = np.allclose(
                        sa.to_numpy(dtype=float), sb.to_numpy(dtype=float),
                        equal_nan=True, rtol=0, atol=1e-9,
                    )
                else:
                    same = sa.equals(sb)
                if not same:
                    bad.append(col)
        check(
            f"prefix of {cut} bars matches full frame",
            not bad,
            "look-ahead in: " + ", ".join(bad),
        )

    # SMT reference itself must be causal
    rt = add_indicators(ref.iloc[:150].copy())
    check(
        "SMT ref prefix",
        np.allclose(
            ref_full.iloc[:150]["ATR"].to_numpy(dtype=float),
            rt["ATR"].to_numpy(dtype=float),
            equal_nan=True,
        ),
        "reference indicators changed under truncation",
    )


def test_signal_causality(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[2] signal causality (strategy sees no future)")
    frame = add_indicators(df.copy(), ref=ref)
    n = len(frame)
    sample = sorted({int(n * f) for f in (0.2, 0.4, 0.6, 0.8, 0.99)} | {60, 120})

    for name, fn in STRATEGY_MAP.items():
        for cut in sample:
            if cut >= n:
                continue
            full_sig = fn(frame, cut, None)
            trunc = frame.iloc[: cut + 1]
            trunc_sig = fn(trunc, len(trunc) - 1, None)
            same = (
                full_sig.action == trunc_sig.action
                and full_sig.reason == trunc_sig.reason
                and _close(full_sig.stop_price, trunc_sig.stop_price)
                and _close(full_sig.target_price, trunc_sig.target_price)
            )
            check(
                f"{name} @bar {cut}",
                same,
                f"signal changed under truncation: {full_sig} vs {trunc_sig}",
            )


def _close(a, b) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return bool(np.isclose(a, b, rtol=0, atol=1e-9, equal_nan=True))


# ------------------------------------------------------------------ engine --

def test_backtest_invariants(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[3] engine invariants")
    frame = add_indicators(df.copy(), ref=ref)
    commission = 0.001

    trade_counts = {}
    short_total = 0

    for name, fn in STRATEGY_MAP.items():
        res = run_backtest(
            frame.copy(), fn,
            initial_capital=100_000, commission_pct=commission,
            risk_pct=1.0,  # exercise the ICT risk-based position sizer
            data_source="test",
        )
        trade_counts[name] = res.num_trades
        check(f"{name}: ran without error", True)
        check(
            f"{name}: equity length == bars",
            len(res.equity_curve) == len(frame),
            f"{len(res.equity_curve)} != {len(frame)}",
        )
        check(
            f"{name}: equity finite",
            bool(np.isfinite(res.equity_curve.to_numpy()).all()),
            "NaN/inf in equity curve",
        )

        bad = []
        for k, t in enumerate(res.trades):
            tag = f"trade#{k + 1} ({t.side})"
            if t.exit_date < t.entry_date:
                bad.append(f"{tag} exits before entry")
            if not t.size > 0:
                bad.append(f"{tag} non-positive size {t.size}")
            if (t.pnl >= 0) != (t.pnl_pct >= 0):
                bad.append(f"{tag} pnl/pnl_pct sign disagree "
                           f"({t.pnl} vs {t.pnl_pct})")
            if t.side == "LONG":
                entry_cost = t.size * t.entry_price * (1 + commission)
                expected = t.size * t.exit_price * (1 - commission) - entry_cost
            else:
                entry_cost = t.size * t.entry_price * (1 - commission)
                expected = entry_cost - t.size * t.exit_price * (1 + commission)
            if not np.isclose(t.pnl, expected, rtol=0, atol=1e-6):
                bad.append(f"{tag} pnl {t.pnl} != commission-aware {expected}")
            if t.side == "SHORT":
                short_total += 1
        check(
            f"{name}: {len(res.trades)} trades pass accounting checks",
            not bad,
            "; ".join(bad[:4]),
        )

        # win rate and profit factor must use the same definition of "win"
        if res.num_trades:
            wins = [t for t in res.trades if t.pnl > 0]
            losses = [t for t in res.trades if t.pnl <= 0]
            expected_wr = round(len(wins) / len(res.trades) * 100, 2)
            check(
                f"{name}: win rate consistent",
                abs(res.win_rate - expected_wr) < 0.02,
                f"{res.win_rate} != {expected_wr}",
            )
            gp = sum(t.pnl for t in wins)
            gl = abs(sum(t.pnl for t in losses)) or 1
            expected_pf = round(gp / gl, 2) if gl else 0.0
            check(
                f"{name}: profit factor consistent",
                abs(res.profit_factor - expected_pf) < 0.02,
                f"{res.profit_factor} != {expected_pf}",
            )

    print("      trade counts: " + ", ".join(
        f"{k.replace('ict_', '')}={v}" for k, v in trade_counts.items()
    ))
    check(
        "every strategy produced at least one trade",
        all(v > 0 for v in trade_counts.values()),
        "no trades: " + ", ".join(k for k, v in trade_counts.items() if v == 0),
    )
    check(
        "short side is traded",
        short_total > 0,
        "no SHORT trades across the whole strategy set",
    )


def test_json_shape(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[4] API payload shape")
    frame = add_indicators(df.copy(), ref=ref)
    res = run_backtest(frame.copy(), STRATEGY_MAP["ict_fair_value_gap"], data_source="test")
    payload = format_result_json(res)
    for key in ("equity_curve", "drawdown_curve", "trades", "win_rate",
                "profit_factor", "sharpe_ratio"):
        check(f"payload has {key}", key in payload)
    if payload["trades"]:
        t = payload["trades"][0]
        check("trade has side", "side" in t and t["side"] in ("LONG", "SHORT"))
        check("trade has reason", "reason" in t)


def test_no_bfill() -> None:
    print("\n[5] hygiene: no back-fill, all ten strategies registered")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for path in ("ict_strategies.py", "backtest_tools.py"):
        src = open(os.path.join(root, path)).read()
        # call sites only — the docstring legitimately says "bfill is never
        # used", and prose must not trip the check.  ``method="ffill"`` on the
        # SMT reference is causal (past reference bars only) and is allowed.
        check(f"{path} has no .bfill() call", ".bfill(" not in src,
              "back-fill is look-ahead on missing data")
        check(f"{path} has no bfill via fillna(method=)",
              'fillna(method="bfill"' not in src
              and "fillna(method='bfill'" not in src,
              "legacy back-fill call found")

    check("eleven strategies registered", len(STRATEGY_MAP) == 11,
          f"got {len(STRATEGY_MAP)}")
    check("SMT strategy flagged as needing a reference",
          "ict_smt_divergence" in ict_strategies.NEEDS_SMT_REF)
    check("all strategy fns accept a position argument",
          all(
              __import__("inspect").signature(fn).parameters.keys()
              >= {"df", "i", "position"}
              for fn in STRATEGY_MAP.values()
          ))


def test_pd_array_semantics(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    """Independent re-derivation of PDH/PDL/PWH/PWL (no groupby.shift tricks)."""
    print("\n[1b] PD arrays mean what they say")
    f = add_indicators(df.copy(), ref=ref)

    def prev_period_values(periods, values, how):
        keys = list(pd.unique(periods))
        prev = {keys[j]: keys[j - 1] for j in range(1, len(keys))}
        out = []
        for w in periods:
            p = prev.get(w)
            if p is None:
                out.append(np.nan)
            else:
                out.append(how(values[periods == p]))
        return np.asarray(out, dtype=float)

    days = pd.Index(df.index.normalize())
    weeks = pd.Index(df.index.to_period("W"))

    for label, periods, col, values, how in (
        ("PDL", days, "PDL", df["Low"], np.min),
        ("PDH", days, "PDH", df["High"], np.max),
        ("PWL", weeks, "PWL", df["Low"], np.min),
        ("PWH", weeks, "PWH", df["High"], np.max),
    ):
        expected = prev_period_values(periods, values, how)
        got = f[col].to_numpy(dtype=float)
        check(
            f"{label} == previous period's extreme",
            np.allclose(got, expected, equal_nan=True, rtol=0, atol=1e-9),
            f"{int(np.sum(~np.isclose(got, expected, equal_nan=True)))} bars wrong",
        )

    # the old implementation handed each bar its *own* week's high from the
    # second bar onwards, and NaN at every week's first bar
    week_max = df["High"].groupby(weeks).transform("max").to_numpy(dtype=float)
    dup = np.asarray(pd.Index(weeks).duplicated(), dtype=bool)
    first_of_week = ~dup
    interior = dup
    check(
        "PWH is never the current week's own high (look-ahead)",
        not np.any(np.isclose(f["PWH"].to_numpy(dtype=float)[interior],
                              week_max[interior])),
        "PWH leaked the in-progress week's high",
    )
    check(
        "PWH is defined from the second week onwards",
        not np.isnan(f["PWH"].to_numpy(dtype=float)[first_of_week][1:]).any(),
        "PWH is NaN at week boundaries",
    )


# ------------------------------------------------------------ 18 SMMA setup --

def _scripted(rows) -> pd.DataFrame:
    """Candles at a fixed 4h rhythm: (open, high, low, close) per row."""
    idx = pd.date_range("2026-01-05", periods=len(rows), freq="4h")
    return pd.DataFrame(
        {"Open": [r[0] for r in rows],
         "High": [r[1] for r in rows],
         "Low": [r[2] for r in rows],
         "Close": [r[3] for r in rows],
         "Volume": [1_000_000] * len(rows)},
        index=idx,
    )


def _smma_long_rows():
    """The setup exactly as specified: a gentle uptrend, a candle that cuts
    down through the 18 SMMA, a displacement break out of the prior candle's
    high, and a trigger candle whose low never reaches the line."""
    rows = []
    for j in range(20):
        o = 100.0 + 0.25 * j
        c = o + 0.2
        rows.append((o, c + 0.15, o - 0.15, c))
    rows.append((105.0, 105.3, 100.0, 104.6))   # cut candle: low through the line
    rows.append((104.7, 110.5, 104.6, 110.2))   # breakout: over the prior high
    rows.append((110.3, 112.0, 109.0, 111.6))   # trigger: low clear of the line
    return rows


def _smma_short_rows():
    """The mirror: a downtrend, a rally through the line, a breakdown under
    the prior low, a trigger whose high stays clear of the line."""
    rows = []
    for j in range(20):
        o = 110.0 - 0.25 * j
        c = o - 0.2
        rows.append((o, o + 0.15, c - 0.15, c))
    rows.append((105.0, 109.5, 104.8, 105.4))   # cut candle: high through the line
    rows.append((105.3, 105.4, 99.5, 99.8))     # breakdown: under the prior low
    rows.append((99.7, 100.5, 98.0, 98.5))      # trigger: high clear of the line
    return rows


def _smma_entries(rows):
    f = add_indicators(_scripted(rows))
    out = []
    for i in range(len(f)):
        s = ict_strategies.smma_18_breakout(f, i, None)
        if s.action in ("BUY", "SHORT"):
            out.append((i, s.action, s.stop_price))
    return f, out


def test_smma_semantics(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[1c] 18 SMMA setup: mean, cut candle, trigger, stop")
    n = ict_strategies.SMMA_LEN
    look = ict_strategies.SMMA_CUT_LOOKBACK

    # 1. SMMA_18 is exactly the Wilder recursion (independent re-derivation)
    f = add_indicators(df.copy(), ref=ref)
    closes = f["Close"].to_numpy(dtype=float)
    manual = np.empty(len(closes))
    manual[0] = closes[0]
    for k in range(1, len(closes)):
        manual[k] = (manual[k - 1] * (n - 1) + closes[k]) / n
    check(
        "SMMA_18 == Wilder recursion",
        np.allclose(manual, f["SMMA_18"].to_numpy(dtype=float),
                    rtol=0, atol=1e-9, equal_nan=True),
        "smoothed mean diverged from smma[i-1]*(n-1)/n + close[i]/n",
    )

    # 2. the cut-candle state, re-derived bar by bar: most recent prior bar
    #    that traded through the line, per side, never outside the window
    lo = f["Low"].to_numpy(dtype=float)
    hi = f["High"].to_numpy(dtype=float)
    smma = f["SMMA_18"].to_numpy(dtype=float)
    got_lo = f["SMMA_Cut_Age"].to_numpy(dtype=float)
    got_hi = f["SMMA_HiCut_Age"].to_numpy(dtype=float)
    cut_lo = f["SMMA_Cut_Low"].to_numpy(dtype=float)
    cut_hi = f["SMMA_Cut_High"].to_numpy(dtype=float)
    mism = 0
    for i in range(1, len(f)):
        exp_lo = exp_hi = -1
        for j in range(i - 1, max(-1, i - look) - 1, -1):
            if smma[j] != smma[j]:
                continue
            if exp_lo < 0 and lo[j] <= smma[j]:
                exp_lo = i - j
            if exp_hi < 0 and hi[j] >= smma[j]:
                exp_hi = i - j
            if exp_lo > 0 and exp_hi > 0:
                break
        for exp, got, level, col in (
            (exp_lo, got_lo[i], cut_lo[i], lo),
            (exp_hi, got_hi[i], cut_hi[i], hi),
        ):
            g = int(got) if got == got else -1
            if exp != g:
                mism += 1
            elif exp > 0 and not np.isclose(level, col[i - exp],
                                            rtol=0, atol=1e-9):
                mism += 1
    check(
        "cut-candle age/level == most recent bar through the line (per side)",
        mism == 0, f"{mism} bars wrong",
    )
    check(
        "cut age never exceeds the lookback window",
        bool((got_lo[got_lo == got_lo] <= look).all()
             and (got_hi[got_hi == got_hi] <= look).all()),
        "an age outside 1..lookback leaked in",
    )

    # 3. the described long setup -> BUY, stop on the cut candle's low
    f_long, sig = _smma_entries(_smma_long_rows())
    check(
        "long setup fires exactly once, on the trigger candle",
        len(sig) == 1 and sig[0][0] == 22 and sig[0][1] == "BUY",
        f"got {sig}",
    )
    if sig:
        check(
            "long stop == low of the candle that cut the 18 SMMA",
            bool(np.isclose(sig[0][2], 100.0, rtol=0, atol=1e-9)),
            f"stop {sig[0][2]} != 100.0",
        )

    # 4. negative case: the trigger candle trades back into the line
    rows = _smma_long_rows()
    smma_trig = float(f_long["SMMA_18"].iloc[22])
    o, h, _l, c = rows[22]
    rows[22] = (o, h, smma_trig - 0.5, c)
    _, sig_touch = _smma_entries(rows)
    check(
        "no entry when the candle after the break touches the 18 SMMA",
        not sig_touch, f"signalled {sig_touch}",
    )

    # 5. negative case: consolidation between the cut and the breakout
    base = _smma_long_rows()
    _, sig_con = _smma_entries(
        base[:21] + [(104.6, 105.1, 104.2, 104.7)] + base[21:])
    check(
        "no entry when the leg chops sideways first (consolidation)",
        not sig_con, f"signalled {sig_con}",
    )

    # 6. the mirror setup shorts with the cut candle's high as the stop
    _, sig_short = _smma_entries(_smma_short_rows())
    check(
        "mirror setup fires SHORT once, on the trigger candle",
        len(sig_short) == 1 and sig_short[0][0] == 22
        and sig_short[0][1] == "SHORT",
        f"got {sig_short}",
    )
    if sig_short:
        check(
            "short stop == high of the candle that cut the 18 SMMA",
            bool(np.isclose(sig_short[0][2], 109.5, rtol=0, atol=1e-9)),
            f"stop {sig_short[0][2]} != 109.5",
        )


def test_resample_4h() -> None:
    print("\n[1d] 4h bar aggregation")
    # two sessions of 1h candles: 09:15/10:15/11:15 land in the 08:00 bucket,
    # 12:15/13:15/14:15/15:15 in the 12:00 one
    rows = []
    for day, base in ((pd.Timestamp("2026-01-05"), 100.0),
                      (pd.Timestamp("2026-01-06"), 101.0)):
        for k, hh in enumerate((9, 10, 11, 12, 13, 14, 15)):
            o = base + 0.5 * k
            rows.append((day + pd.Timedelta(hours=hh, minutes=15),
                         o, o + 0.6, o - 0.3, o + 0.4, 1000.0 * (k + 1)))
    hourly = pd.DataFrame(
        {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows],
         "Volume": [r[5] for r in rows]},
        index=pd.DatetimeIndex([r[0] for r in rows], name="Datetime"),
    )
    out = resample_to_4h(hourly)

    check("1h candles fold into two 4h bars per session", len(out) == 4,
          f"got {len(out)} bars")
    check("bucket labels are the session's 08:00/12:00 boundaries",
          list(out.index.strftime("%H:%M")) == ["08:00", "12:00", "08:00", "12:00"],
          str(list(out.index)))

    first = out.iloc[0]
    exp = {"Open": 100.0, "High": 100.6 + 1.0, "Low": 99.7, "Close": 101.4,
           "Volume": 6000.0}
    for col, want in exp.items():
        check(f"morning bucket {col} aggregates correctly",
              bool(np.isclose(first[col], want, rtol=0, atol=1e-9)),
              f"{first[col]} != {want}")

    second = out.iloc[1]
    check("afternoon bucket opens on its own first bar (101.5)",
          bool(np.isclose(second["Open"], 101.5, rtol=0, atol=1e-9)),
          f"{second['Open']}")
    check("afternoon bucket close/low come from the last bar of the session",
          bool(np.isclose(second["Close"], 103.4, rtol=0, atol=1e-9)
               and np.isclose(second["Low"], 101.2, rtol=0, atol=1e-9)),
          f"close {second['Close']} low {second['Low']}")

    check("aggregated bars keep OHLC invariants",
          bool((out["High"] >= out[["Open", "Close"]].max(axis=1) - 1e-12).all()
               and (out["Low"] <= out[["Open", "Close"]].min(axis=1) + 1e-12).all()),
          "OHLC invariants broken by aggregation")

    # a truncated session must not change any *completed* earlier bucket
    day1 = hourly[hourly.index < pd.Timestamp("2026-01-06")]
    part = resample_to_4h(day1)
    check("completed buckets are identical under truncation",
          part.equals(out.iloc[: len(part)]),
          "an earlier 4h bar changed when later bars were removed")

    # daily data passes straight through
    daily = _synthetic(120)
    check("daily frames are left alone", resample_to_4h(daily).equals(daily))


def test_supertrend_semantics(df: pd.DataFrame, ref: pd.DataFrame) -> None:
    print("\n[1e] Super Trend: positive flip buy, negative flip sell, long-only in equity stocks")
    f = add_indicators(df.copy(), ref=ref)
    st = f["SuperTrend"].to_numpy(dtype=float)
    d = f["SuperTrend_Direction"].to_numpy(dtype=int)

    # 1. SuperTrend is defined and finite past the warmup window
    valid_mask = ~np.isnan(st[20:])
    check("SuperTrend is defined on history", bool(valid_mask.all()), "NaN found in SuperTrend")
    check("direction values are strictly +1 or -1", set(np.unique(d[20:])).issubset({-1, 1}))

    # 2. Check signal logic on positive and negative transitions
    fn = STRATEGY_MAP["super_trend"]
    long_entries = 0
    sells = 0
    short_entries = 0
    for i in range(21, len(f)):
        sig_flat = fn(f, i, None)
        if sig_flat.action == "SHORT":
            short_entries += 1
        if d[i] == 1 and d[i - 1] == -1:
            check(f"bar {i}: positive flip generates BUY", sig_flat.action == "BUY", f"action was {sig_flat.action}")
            long_entries += 1

        class DummyPos:
            side = "LONG"
        sig_pos = fn(f, i, DummyPos())
        if d[i] == -1:
            check(f"bar {i}: negative SuperTrend closes open LONG via SELL", sig_pos.action == "SELL", f"action was {sig_pos.action}")
            sells += 1

    check("never opens SHORT in equity stocks", short_entries == 0)
    check("positive flip produces BUY signals", long_entries > 0)
    check("negative flip produces SELL signals", sells > 0)

    # 3. Test on 4h timeframe
    df_4h = resample_to_4h(df.copy())
    f_4h = add_indicators(df_4h)
    res_4h = run_backtest(f_4h.copy(), fn, initial_capital=100_000, data_source="test_4h")
    check("4h SuperTrend runs without error", len(res_4h.equity_curve) == len(f_4h))
    check("4h SuperTrend produces trades", res_4h.num_trades > 0)
    check("4h SuperTrend is 100% long-only", all(t.side == "LONG" for t in res_4h.trades))

    # 4. Test daily timeframe backtest
    res_daily = run_backtest(f.copy(), fn, initial_capital=100_000, data_source="test_daily")
    check("Daily SuperTrend runs without error", len(res_daily.equity_curve) == len(f))
    check("Daily SuperTrend produces trades", res_daily.num_trades > 0)
    check("Daily SuperTrend is 100% long-only", all(t.side == "LONG" for t in res_daily.trades))


def main() -> int:
    df, ref = _load()
    test_no_bfill()
    test_indicator_causality(df, ref)
    test_pd_array_semantics(df, ref)
    test_smma_semantics(df, ref)
    test_supertrend_semantics(df, ref)
    test_resample_4h()
    test_signal_causality(df, ref)
    test_backtest_invariants(df, ref)
    test_json_shape(df, ref)
    print(f"\n{CHECKS} checks passed, {len(FAILURES)} failed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError:
        sys.exit(1)
