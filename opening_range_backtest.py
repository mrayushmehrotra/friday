"""
15-Minute Opening Range Displacement Strategy Backtester
=========================================================
Strategy Rules:
1. Timeframe: 5-minute intraday candles fetched from INDmoney / INDstocks API.
2. Opening Range (OR):
   - Formed during the first 15 minutes of the trading session (09:15 to 09:30 IST).
   - Calculated from the first three 5-minute candles (09:15, 09:20, 09:25).
   - OR_High = max(High of 09:15 - 09:30 candles)
   - OR_Low  = min(Low of 09:15 - 09:30 candles)
3. Displacement & Entry:
   - Starting from 09:30 IST, inspect each 5-minute candle.
   - Bullish Displacement (LONG):
     * Candle closes above OR_High (Close > OR_High) and Close > Open (green candle).
     * Entry Price = Close of the displacement candle.
     * Stop Loss (SL) = Low of the displacement candle ("That candle's low will be our SL").
     * Target = Entry + 2 * (Entry - SL) ("1:2 risk reward").
   - Bearish Displacement (SHORT):
     * Candle closes below OR_Low (Close < OR_Low) and Close < Open (red candle).
     * Entry Price = Close of the displacement candle.
     * Stop Loss (SL) = High of the displacement candle.
     * Target = Entry - 2 * (SL - Entry) (1:2 risk reward).
4. Trade Management & Exits:
   - Check subsequent candles during the same trading day:
     * For Long: Hit Target if High >= Target; Hit SL if Low <= SL.
     * For Short: Hit Target if Low <= Target; Hit SL if High >= SL.
     * Intraday Cutoff: If neither SL nor Target is hit by 15:15 IST, square off at 15:15 Close.
   - 1 trade per day per stock.
   - No new entries allowed after 14:30 IST.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Re-use existing project utilities
try:
    from backtest_tools import INDSTOCKS_SECURITY_IDS, fetch_indstocks_data, resolve_indstocks_scrip
except ImportError:
    INDSTOCKS_SECURITY_IDS = {}
    fetch_indstocks_data = None
    resolve_indstocks_scrip = None


@dataclass
class TradeRecord:
    symbol: str
    date: str
    entry_time: str
    side: str  # "LONG" or "SHORT"
    or_high: float
    or_low: float
    entry_price: float
    sl_price: float
    target_price: float
    risk_points: float
    exit_time: str
    exit_price: float
    outcome: str  # "TARGET", "SL", "SQUAREOFF"
    r_multiple: float
    shares: int = 1
    pnl_inr: float = 0.0
    displacement_body_pct: float = 0.0
    notes: str = ""


@dataclass
class BacktestSummary:
    symbol: str
    total_trades: int
    wins: int
    losses: int
    squareoffs: int
    win_rate_pct: float
    total_r: float
    avg_r: float
    profit_factor: float
    max_drawdown_r: float
    total_pnl_inr: float
    initial_capital: float
    final_capital: float
    return_pct: float
    long_trades: int = 0
    long_wins: int = 0
    short_trades: int = 0
    short_wins: int = 0


def get_api_token() -> str:
    """Retrieve INDmoney API token from environment or .env file."""
    token = os.environ.get("INDMONEY_API_TOKEN") or os.environ.get("INDMONEY_ACCESS_TOKEN") or ""
    if not token.strip():
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("INDMONEY_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
                    elif line.startswith("INDMONEY_ACCESS_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
    return token.strip()


def run_opening_range_backtest(
    df: pd.DataFrame,
    symbol: str,
    direction: str = "BOTH",  # "LONG", "SHORT", or "BOTH"
    displacement_mode: str = "standard",  # "standard" (close beyond OR) or "momentum" (body >= 50% range)
    risk_per_trade_inr: float = 1000.0,
    initial_capital: float = 100000.0,
    max_entry_time: time = time(14, 30),
    squareoff_time: time = time(15, 15),
) -> Tuple[List[TradeRecord], BacktestSummary]:
    """Execute Opening Range Displacement strategy backtest on 5m OHLCV data."""
    if df is None or df.empty or len(df) < 15:
        return [], BacktestSummary(
            symbol=symbol,
            total_trades=0,
            wins=0,
            losses=0,
            squareoffs=0,
            win_rate_pct=0.0,
            total_r=0.0,
            avg_r=0.0,
            profit_factor=0.0,
            max_drawdown_r=0.0,
            total_pnl_inr=0.0,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            return_pct=0.0,
        )

    # Ensure timestamp indexing and localized to Asia/Kolkata
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    df["TradingDate"] = df.index.date
    dates = df["TradingDate"].unique()

    trades: List[TradeRecord] = []
    current_capital = initial_capital

    for d in dates:
        day_df = df[df["TradingDate"] == d]

        # 1. First 15 minutes opening range: 09:15, 09:20, 09:25 candles
        or_candles = day_df[
            (day_df.index.time >= time(9, 15)) & (day_df.index.time < time(9, 30))
        ]
        if len(or_candles) < 3:
            # Need complete 15-minute opening range
            continue

        or_high = float(or_candles["High"].max())
        or_low = float(or_candles["Low"].min())

        # Session trading candles starting from 09:30 onwards
        session_candles = day_df[day_df.index.time >= time(9, 30)]
        if session_candles.empty:
            continue

        trade_taken_today = False

        for idx, (t, row) in enumerate(session_candles.iterrows()):
            if trade_taken_today:
                break

            current_time = t.time()
            if current_time > max_entry_time:
                break

            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            candle_range = max(0.01, h - l)
            candle_body = abs(c - o)
            body_ratio = candle_body / candle_range

            is_long_displacement = False
            is_short_displacement = False

            # Check Bullish Displacement (LONG)
            if direction in ("LONG", "BOTH"):
                # Candle closes above Opening Range High
                if c > or_high and c > o:
                    if displacement_mode == "momentum":
                        # Strong displacement: body must be >= 50% of the candle range
                        if body_ratio >= 0.50:
                            is_long_displacement = True
                    else:
                        is_long_displacement = True

            # Check Bearish Displacement (SHORT)
            if direction in ("SHORT", "BOTH") and not is_long_displacement:
                # Candle closes below Opening Range Low
                if c < or_low and c < o:
                    if displacement_mode == "momentum":
                        if body_ratio >= 0.50:
                            is_short_displacement = True
                    else:
                        is_short_displacement = True

            # Process Trade Entry
            if is_long_displacement:
                entry_price = c
                sl_price = l  # User Rule: That candle's low will be our SL
                risk_points = entry_price - sl_price

                if risk_points < 0.05:
                    continue  # Invalid flat candle

                target_price = entry_price + (2.0 * risk_points)  # 1:2 Risk to Reward
                shares = max(1, int(risk_per_trade_inr / risk_points))

                # Simulate position management over remaining candles of the day
                rem_candles = session_candles.iloc[idx + 1 :]
                exit_time_str = "15:25"
                exit_price = entry_price
                outcome = "SQUAREOFF"
                r_mult = 0.0

                for rt, rrow in rem_candles.iterrows():
                    r_time = rt.time()
                    ro = float(rrow["Open"])
                    rh = float(rrow["High"])
                    rl = float(rrow["Low"])
                    rc = float(rrow["Close"])

                    # 1. Square-off at 15:15 IST
                    if r_time >= squareoff_time:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = rc
                        if exit_price >= target_price:
                            outcome = "TARGET"
                            r_mult = 2.0
                            exit_price = target_price
                        elif exit_price <= sl_price:
                            outcome = "SL"
                            r_mult = -1.0
                            exit_price = sl_price
                        else:
                            outcome = "SQUAREOFF"
                            r_mult = (exit_price - entry_price) / risk_points
                        break

                    # 2. Check Intraday SL Hit
                    if rl <= sl_price:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = sl_price
                        outcome = "SL"
                        r_mult = -1.0
                        break

                    # 3. Check Intraday Target Hit
                    if rh >= target_price:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = target_price
                        outcome = "TARGET"
                        r_mult = 2.0
                        break

                if outcome == "SQUAREOFF" and len(rem_candles) > 0 and exit_time_str == "15:25":
                    exit_time_str = rem_candles.index[-1].strftime("%H:%M")
                    exit_price = float(rem_candles.iloc[-1]["Close"])
                    r_mult = (exit_price - entry_price) / risk_points

                pnl = r_mult * risk_per_trade_inr
                current_capital += pnl

                trades.append(
                    TradeRecord(
                        symbol=symbol,
                        date=str(d),
                        entry_time=t.strftime("%H:%M"),
                        side="LONG",
                        or_high=round(or_high, 2),
                        or_low=round(or_low, 2),
                        entry_price=round(entry_price, 2),
                        sl_price=round(sl_price, 2),
                        target_price=round(target_price, 2),
                        risk_points=round(risk_points, 2),
                        exit_time=exit_time_str,
                        exit_price=round(exit_price, 2),
                        outcome=outcome,
                        r_multiple=round(r_mult, 2),
                        shares=shares,
                        pnl_inr=round(pnl, 2),
                        displacement_body_pct=round(body_ratio * 100, 1),
                        notes="Bullish OR displacement",
                    )
                )
                trade_taken_today = True

            elif is_short_displacement:
                entry_price = c
                sl_price = h  # Mirror: That candle's high will be our SL
                risk_points = sl_price - entry_price

                if risk_points < 0.05:
                    continue

                target_price = entry_price - (2.0 * risk_points)  # 1:2 Risk to Reward
                shares = max(1, int(risk_per_trade_inr / risk_points))

                rem_candles = session_candles.iloc[idx + 1 :]
                exit_time_str = "15:25"
                exit_price = entry_price
                outcome = "SQUAREOFF"
                r_mult = 0.0

                for rt, rrow in rem_candles.iterrows():
                    r_time = rt.time()
                    ro = float(rrow["Open"])
                    rh = float(rrow["High"])
                    rl = float(rrow["Low"])
                    rc = float(rrow["Close"])

                    # 1. Square-off at 15:15 IST
                    if r_time >= squareoff_time:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = rc
                        if exit_price <= target_price:
                            outcome = "TARGET"
                            r_mult = 2.0
                            exit_price = target_price
                        elif exit_price >= sl_price:
                            outcome = "SL"
                            r_mult = -1.0
                            exit_price = sl_price
                        else:
                            outcome = "SQUAREOFF"
                            r_mult = (entry_price - exit_price) / risk_points
                        break

                    # 2. Check Intraday SL Hit
                    if rh >= sl_price:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = sl_price
                        outcome = "SL"
                        r_mult = -1.0
                        break

                    # 3. Check Intraday Target Hit
                    if rl <= target_price:
                        exit_time_str = rt.strftime("%H:%M")
                        exit_price = target_price
                        outcome = "TARGET"
                        r_mult = 2.0
                        break

                if outcome == "SQUAREOFF" and len(rem_candles) > 0 and exit_time_str == "15:25":
                    exit_time_str = rem_candles.index[-1].strftime("%H:%M")
                    exit_price = float(rem_candles.iloc[-1]["Close"])
                    r_mult = (entry_price - exit_price) / risk_points

                pnl = r_mult * risk_per_trade_inr
                current_capital += pnl

                trades.append(
                    TradeRecord(
                        symbol=symbol,
                        date=str(d),
                        entry_time=t.strftime("%H:%M"),
                        side="SHORT",
                        or_high=round(or_high, 2),
                        or_low=round(or_low, 2),
                        entry_price=round(entry_price, 2),
                        sl_price=round(sl_price, 2),
                        target_price=round(target_price, 2),
                        risk_points=round(risk_points, 2),
                        exit_time=exit_time_str,
                        exit_price=round(exit_price, 2),
                        outcome=outcome,
                        r_multiple=round(r_mult, 2),
                        shares=shares,
                        pnl_inr=round(pnl, 2),
                        displacement_body_pct=round(body_ratio * 100, 1),
                        notes="Bearish OR displacement",
                    )
                )
                trade_taken_today = True

    # Compute aggregate performance summary
    total_trades = len(trades)
    if total_trades == 0:
        return trades, BacktestSummary(
            symbol=symbol,
            total_trades=0,
            wins=0,
            losses=0,
            squareoffs=0,
            win_rate_pct=0.0,
            total_r=0.0,
            avg_r=0.0,
            profit_factor=0.0,
            max_drawdown_r=0.0,
            total_pnl_inr=0.0,
            initial_capital=initial_capital,
            final_capital=initial_capital,
            return_pct=0.0,
        )

    wins = sum(1 for tr in trades if tr.outcome == "TARGET" or tr.r_multiple > 0)
    losses = sum(1 for tr in trades if tr.outcome == "SL" or tr.r_multiple < 0)
    squareoffs = sum(1 for tr in trades if tr.outcome == "SQUAREOFF")

    long_trades = sum(1 for tr in trades if tr.side == "LONG")
    long_wins = sum(1 for tr in trades if tr.side == "LONG" and tr.r_multiple > 0)
    short_trades = sum(1 for tr in trades if tr.side == "SHORT")
    short_wins = sum(1 for tr in trades if tr.side == "SHORT" and tr.r_multiple > 0)

    total_r = sum(tr.r_multiple for tr in trades)
    avg_r = total_r / total_trades if total_trades > 0 else 0.0
    win_rate = (wins / total_trades) * 100.0 if total_trades > 0 else 0.0

    gross_profit_r = sum(tr.r_multiple for tr in trades if tr.r_multiple > 0)
    gross_loss_r = abs(sum(tr.r_multiple for tr in trades if tr.r_multiple < 0))
    profit_factor = (gross_profit_r / gross_loss_r) if gross_loss_r > 0 else (99.0 if gross_profit_r > 0 else 0.0)

    # Max Drawdown calculation in R
    r_series = pd.Series([tr.r_multiple for tr in trades])
    cum_r = r_series.cumsum()
    running_max = cum_r.cummax()
    drawdown_r = running_max - cum_r
    max_dd_r = float(drawdown_r.max()) if len(drawdown_r) > 0 else 0.0

    total_pnl_inr = sum(tr.pnl_inr for tr in trades)
    final_capital = initial_capital + total_pnl_inr
    return_pct = (total_pnl_inr / initial_capital) * 100.0

    summary = BacktestSummary(
        symbol=symbol,
        total_trades=total_trades,
        wins=wins,
        losses=losses,
        squareoffs=squareoffs,
        win_rate_pct=round(win_rate, 2),
        total_r=round(total_r, 2),
        avg_r=round(avg_r, 2),
        profit_factor=round(profit_factor, 2),
        max_drawdown_r=round(max_dd_r, 2),
        total_pnl_inr=round(total_pnl_inr, 2),
        initial_capital=initial_capital,
        final_capital=round(final_capital, 2),
        return_pct=round(return_pct, 2),
        long_trades=long_trades,
        long_wins=long_wins,
        short_trades=short_trades,
        short_wins=short_wins,
    )

    return trades, summary


def print_summary_table(summaries: List[BacktestSummary]) -> str:
    """Format a clean markdown table of backtest summaries."""
    lines = []
    lines.append("| Symbol | Trades | Win Rate | Total R | Profit Factor | Max DD (R) | PnL (₹) | Return % |")
    lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

    tot_trades = sum(s.total_trades for s in summaries)
    tot_wins = sum(s.wins for s in summaries)
    tot_r = sum(s.total_r for s in summaries)
    tot_pnl = sum(s.total_pnl_inr for s in summaries)

    for s in summaries:
        r_sign = "+" if s.total_r > 0 else ""
        pnl_sign = "+" if s.total_pnl_inr > 0 else ""
        lines.append(
            f"| **{s.symbol}** | {s.total_trades} | {s.win_rate_pct:.1f}% | {r_sign}{s.total_r:.2f}R | {s.profit_factor:.2f} | {s.max_drawdown_r:.2f}R | {pnl_sign}₹{s.total_pnl_inr:,.0f} | {s.return_pct:+.1f}% |"
        )

    if len(summaries) > 1:
        overall_wr = (tot_wins / tot_trades * 100) if tot_trades > 0 else 0
        tot_r_sign = "+" if tot_r > 0 else ""
        tot_pnl_sign = "+" if tot_pnl > 0 else ""
        lines.append("|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")
        lines.append(
            f"| **TOTAL / AVG** | **{tot_trades}** | **{overall_wr:.1f}%** | **{tot_r_sign}{tot_r:.2f}R** | — | — | **{tot_pnl_sign}₹{tot_pnl:,.0f}** | — |"
        )

    return "\n".join(lines)


def print_trade_log_table(trades: List[TradeRecord], max_rows: int = 25) -> str:
    """Format trade-by-trade log table."""
    lines = []
    lines.append("| Date | Time | Symbol | Side | OR High | OR Low | Entry | SL | Target | Exit | Outcome | R-Mult | PnL (₹) |")
    lines.append("|:---|:---:|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|")

    display_trades = trades[-max_rows:] if len(trades) > max_rows else trades
    for t in display_trades:
        r_str = f"{t.r_multiple:+.2f}R"
        pnl_str = f"{t.pnl_inr:+,.0f}"
        outcome_badge = f"**{t.outcome}**" if t.outcome == "TARGET" else t.outcome
        lines.append(
            f"| {t.date} | {t.entry_time} | {t.symbol} | {t.side} | {t.or_high} | {t.or_low} | {t.entry_price} | {t.sl_price} | {t.target_price} | {t.exit_time} ({t.exit_price}) | {outcome_badge} | {r_str} | ₹{pnl_str} |"
        )

    return "\n".join(lines)


def generate_html_report(
    all_trades: List[TradeRecord],
    summaries: List[BacktestSummary],
    output_path: str,
    direction: str,
    mode: str,
    cutoff_str: str,
    days: int,
):
    """Generate an interactive HTML report of the backtest."""
    tot_trades = sum(s.total_trades for s in summaries)
    tot_wins = sum(s.wins for s in summaries)
    tot_losses = sum(s.losses for s in summaries)
    tot_r = sum(s.total_r for s in summaries)
    tot_pnl = sum(s.total_pnl_inr for s in summaries)
    overall_wr = (tot_wins / tot_trades * 100) if tot_trades > 0 else 0

    # Trade table rows
    trade_rows = []
    cum_r = 0.0
    r_curve_data = []
    r_curve_labels = []

    for idx, t in enumerate(all_trades):
        cum_r += t.r_multiple
        r_curve_data.append(round(cum_r, 2))
        r_curve_labels.append(f"{t.date} {t.entry_time} ({t.symbol})")
        outcome_color = "#10b981" if t.outcome == "TARGET" else ("#ef4444" if t.outcome == "SL" else "#f59e0b")
        trade_rows.append(f"""
        <tr>
            <td>{t.date}</td>
            <td>{t.entry_time}</td>
            <td><strong>{t.symbol}</strong></td>
            <td><span class="badge {t.side.lower()}">{t.side}</span></td>
            <td>₹{t.or_high:.2f}</td>
            <td>₹{t.or_low:.2f}</td>
            <td>₹{t.entry_price:.2f}</td>
            <td style="color:#ef4444">₹{t.sl_price:.2f}</td>
            <td style="color:#10b981">₹{t.target_price:.2f}</td>
            <td>{t.exit_time} (₹{t.exit_price:.2f})</td>
            <td><span style="color:{outcome_color};font-weight:600">{t.outcome}</span></td>
            <td style="font-weight:600;color:{outcome_color}">{t.r_multiple:+.2f}R</td>
            <td style="color:{outcome_color}">₹{t.pnl_inr:+,.0f}</td>
        </tr>
        """)

    # Summary table rows
    summary_rows = []
    for s in summaries:
        r_color = "#10b981" if s.total_r >= 0 else "#ef4444"
        summary_rows.append(f"""
        <tr>
            <td><strong>{s.symbol}</strong></td>
            <td>{s.total_trades}</td>
            <td>{s.wins}</td>
            <td>{s.losses}</td>
            <td>{s.win_rate_pct:.1f}%</td>
            <td style="color:{r_color};font-weight:600">{s.total_r:+.2f}R</td>
            <td>{s.profit_factor:.2f}</td>
            <td>{s.max_drawdown_r:.2f}R</td>
            <td style="color:{r_color};font-weight:600">₹{s.total_pnl_inr:+,.0f}</td>
            <td style="color:{r_color}">{s.return_pct:+.1f}%</td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>15m Opening Range Displacement Strategy - Backtest Report</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0; padding: 24px; background: #0f172a; color: #f8fafc;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #0f172a);
            padding: 24px; border-radius: 12px; margin-bottom: 24px;
            border: 1px solid #334155;
        }}
        h1 {{ margin: 0 0 8px 0; color: #38bdf8; font-size: 26px; }}
        .meta {{ color: #94a3b8; font-size: 14px; margin-bottom: 16px; }}
        .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
        .card {{
            background: #1e293b; padding: 18px; border-radius: 10px; border: 1px solid #334155;
        }}
        .card .title {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; }}
        .card .val {{ font-size: 24px; font-weight: bold; color: #f8fafc; }}
        .val.pos {{ color: #10b981; }}
        .val.neg {{ color: #ef4444; }}
        .chart-box {{
            background: #1e293b; padding: 20px; border-radius: 10px; border: 1px solid #334155; margin-bottom: 24px;
        }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
        tr:hover {{ background: #243247; }}
        .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; }}
        .badge.long {{ background: #065f46; color: #34d399; }}
        .badge.short {{ background: #7f1d1d; color: #f87171; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>📊 15-Minute Opening Range Displacement Backtest</h1>
        <div class="meta">
            <strong>Timeframe:</strong> 5-minute candles |
            <strong>Data Source:</strong> INDmoney LIVE API |
            <strong>Lookback:</strong> {days} Days |
            <strong>Direction:</strong> {direction} |
            <strong>Displacement Mode:</strong> {mode} |
            <strong>Entry Cutoff:</strong> {cutoff_str} IST |
            <strong>Risk/Reward:</strong> 1:2 RR (SL at candle low for long)
        </div>
    </div>

    <div class="cards">
        <div class="card">
            <div class="title">Total Trades</div>
            <div class="val">{tot_trades}</div>
        </div>
        <div class="card">
            <div class="title">Win Rate</div>
            <div class="val {"pos" if overall_wr >= 40 else "neg"}">{overall_wr:.1f}%</div>
        </div>
        <div class="card">
            <div class="title">Total Return (R-Multiples)</div>
            <div class="val {"pos" if tot_r >= 0 else "neg"}">{tot_r:+.2f} R</div>
        </div>
        <div class="card">
            <div class="title">Total PnL (@ ₹1k Risk)</div>
            <div class="val {"pos" if tot_pnl >= 0 else "neg"}">₹{tot_pnl:+,.0f}</div>
        </div>
    </div>

    <div class="chart-box">
        <h3 style="margin-top:0;color:#38bdf8">Cumulative R-Multiple Curve</h3>
        <canvas id="equityChart" height="90"></canvas>
    </div>

    <div class="chart-box">
        <h3 style="margin-top:0;color:#38bdf8">Per-Stock Performance Breakdown</h3>
        <table>
            <thead>
                <tr>
                    <th>Symbol</th>
                    <th>Trades</th>
                    <th>Wins</th>
                    <th>Losses</th>
                    <th>Win Rate</th>
                    <th>Total R</th>
                    <th>Profit Factor</th>
                    <th>Max DD (R)</th>
                    <th>PnL (₹)</th>
                    <th>Return %</th>
                </tr>
            </thead>
            <tbody>
                {''.join(summary_rows)}
            </tbody>
        </table>
    </div>

    <div class="chart-box">
        <h3 style="margin-top:0;color:#38bdf8">Trade History Log (All Trades)</h3>
        <table>
            <thead>
                <tr>
                    <th>Date</th>
                    <th>Time</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>OR High</th>
                    <th>OR Low</th>
                    <th>Entry</th>
                    <th>SL</th>
                    <th>Target</th>
                    <th>Exit</th>
                    <th>Outcome</th>
                    <th>R</th>
                    <th>PnL (₹)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(trade_rows)}
            </tbody>
        </table>
    </div>

    <script>
        const ctx = document.getElementById('equityChart').getContext('2d');
        new Chart(ctx, {{
            type: 'line',
            data: {{
                labels: {r_curve_labels},
                datasets: [{{
                    label: 'Cumulative R',
                    data: {r_curve_data},
                    borderColor: '{'#10b981' if tot_r >= 0 else '#ef4444'}',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.1,
                    pointRadius: 2
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ display: false }},
                    y: {{ grid: {{ color: '#334155' }}, ticks: {{ color: '#94a3b8' }} }}
                }},
                plugins: {{ legend: {{ display: false }} }}
            }}
        }});
    </script>
</body>
</html>
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    parser = argparse.ArgumentParser(description="15m Opening Range Displacement Strategy Backtester")
    parser.add_argument("--symbols", type=str, default="RELIANCE,SBIN,INFY,ICICIBANK,HDFCBANK,TCS,TATAMOTORS,AXISBANK,BHARTIARTL,LT", help="Comma-separated stock symbols")
    parser.add_argument("--days", type=int, default=60, help="Days of 5m historical data to fetch from INDmoney API")
    parser.add_argument("--direction", type=str, default="BOTH", choices=["LONG", "SHORT", "BOTH"], help="Trade direction")
    parser.add_argument("--mode", type=str, default="standard", choices=["standard", "momentum"], help="Displacement filter mode")
    parser.add_argument("--cutoff", type=str, default="14:30", help="Latest entry time (HH:MM IST, e.g. 11:30 or 14:30)")
    parser.add_argument("--risk", type=float, default=1000.0, help="Risk per trade in INR")
    parser.add_argument("--capital", type=float, default=100000.0, help="Initial capital in INR")
    parser.add_argument("--html", type=str, default="opening_range_backtest_report.html", help="HTML report output file")

    args = parser.parse_args()

    token = get_api_token()
    if not token:
        print("[ERROR] INDMONEY_API_TOKEN not found in environment or .env file!")
        sys.exit(1)

    print(f"[*] Authenticated with INDmoney API (Token prefix: {token[:16]}...)")

    cutoff_h, cutoff_m = map(int, args.cutoff.split(":"))
    cutoff_time = time(cutoff_h, cutoff_m)

    symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(f"[*] Backtesting {len(symbol_list)} symbols: {', '.join(symbol_list)}")
    print(f"[*] Timeframe: 5-minute | Direction: {args.direction} | Mode: {args.mode} | Cutoff: {args.cutoff} | Days: {args.days}")

    all_trades: List[TradeRecord] = []
    summaries: List[BacktestSummary] = []

    for sym in symbol_list:
        scrip = INDSTOCKS_SECURITY_IDS.get(sym)
        if not scrip and resolve_indstocks_scrip:
            scrip = resolve_indstocks_scrip(sym, api_key=token)
        if not scrip:
            print(f"[-] Could not resolve INDstocks scrip for {sym}, skipping.")
            continue

        print(f"[*] Fetching 5m candles for {sym} ({scrip}) from INDmoney API...")
        df = fetch_indstocks_data(scrip, token, interval="5minute", days=args.days)
        if df is None or len(df) < 20:
            print(f"[-] Insufficient candle data returned for {sym}")
            continue

        trades, summary = run_opening_range_backtest(
            df=df,
            symbol=sym,
            direction=args.direction,
            displacement_mode=args.mode,
            risk_per_trade_inr=args.risk,
            initial_capital=args.capital,
            max_entry_time=cutoff_time,
        )

        summaries.append(summary)
        all_trades.extend(trades)
        print(f"    -> {sym}: {summary.total_trades} trades | Win Rate: {summary.win_rate_pct}% | Return: {summary.total_r:+.2f}R | PnL: ₹{summary.total_pnl_inr:+,.0f}")

    print("\n" + "=" * 80)
    print("BACKTEST SUMMARY TABLE")
    print("=" * 80)
    print(print_summary_table(summaries))

    print("\n" + "=" * 80)
    print("RECENT TRADE LOG")
    print("=" * 80)
    all_trades.sort(key=lambda x: (x.date, x.entry_time))
    print(print_trade_log_table(all_trades, max_rows=20))

    if args.html:
        generate_html_report(
            all_trades=all_trades,
            summaries=summaries,
            output_path=args.html,
            direction=args.direction,
            mode=args.mode,
            cutoff_str=args.cutoff,
            days=args.days,
        )
        print(f"\n[+] Interactive HTML report saved to: {args.html}")


if __name__ == "__main__":
    main()
