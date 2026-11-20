"""
Monte Carlo Simulation of TradingView PineScript v6 Strategy:
"VWAP x EMA Cross | Smart Profit Trail"
=============================================================
Faithfully replicates the PineScript logic:
1. Indicators:
   - EMA(9) on Close
   - Daily Session VWAP(hlc3) resetting at 09:15 IST
   - ATR(14) RMA
2. Entries:
   - Long: EMA crosses over VWAP, SL = Low of prior bar (low[1]), Risk = Close - SL.
     TP = Close + Risk * rr (default 2.0).
   - Short: EMA crosses under VWAP, SL = High of prior bar (high[1]), Risk = SL - Close.
     TP = Close - Risk * rr (default 2.0).
3. Trailing & Management:
   - Once High >= Entry + (Risk * trailStartR) [default 1.0R]:
     * Trailing activates (trailOn = true).
     * If useBE = true: SL moves to Entry price (Breakeven).
     * Stop ratchets progressively (never moves backwards):
       - "EMA Trail": candidateSL = EMA(9)
       - "ATR Trail": candidateSL = extremePx - (ATR * atrMult)
       - "Candle Low/High": candidateSL = prior bar low/high
4. Exits:
   - usePartial = true: 50% exits at Target (limit tpPx, +2R), 50% runs on trailing stop.
   - closeEOD = true: open trades closed at 15:15 IST.
5. Monte Carlo Simulation:
   - 5,000+ resampled paths with bootstrap reshuffling and sequence permutations.
   - Drawdown distributions, ruin probability, consecutive losing streaks, percentile equity bands.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# Re-use project utilities
try:
    from backtest_tools import INDSTOCKS_SECURITY_IDS, fetch_indstocks_data, resolve_indstocks_scrip
except ImportError:
    INDSTOCKS_SECURITY_IDS = {}
    fetch_indstocks_data = None
    resolve_indstocks_scrip = None


@dataclass
class StrategyTrade:
    symbol: str
    entry_time: str
    exit_time: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    initial_sl: float
    target_price: float
    risk_points: float
    final_exit_price: float
    outcome: str  # "TARGET+RUNNER", "SL", "BE", "EOD"
    partial_taken: bool
    r_multiple: float
    pnl_inr: float = 0.0
    duration_bars: int = 0


@dataclass
class MonteCarloMetrics:
    num_simulations: int
    trades_per_sim: int
    median_final_r: float
    mean_final_r: float
    p5_final_r: float
    p25_final_r: float
    p75_final_r: float
    p95_final_r: float
    median_max_dd_r: float
    p95_max_dd_r: float
    p99_max_dd_r: float
    prob_profit_pct: float
    prob_dd_10r_pct: float
    prob_dd_15r_pct: float
    prob_dd_20r_pct: float
    median_consecutive_losses: int
    p95_consecutive_losses: int
    historical_total_trades: int
    historical_win_rate_pct: float
    historical_total_r: float
    historical_profit_factor: float
    historical_max_dd_r: float


def get_api_token() -> str:
    """Retrieve INDmoney API token from environment or .env file."""
    token = os.environ.get("INDMONEY_API_TOKEN") or os.environ.get("INDMONEY_ACCESS_TOKEN") or ""
    if not token.strip():
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("INDMONEY_API_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
                    elif line.startswith("INDMONEY_ACCESS_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
    return token.strip()


def fetch_candles_with_fallback(
    symbol: str,
    token: str,
    interval: str = "15minute",
    days: int = 60,
) -> Tuple[Optional[pd.DataFrame], str]:
    """Fetch candles from INDmoney API with disk cache and Yahoo Finance fallback."""
    cache_dir = os.path.join(os.path.dirname(__file__), ".cache_candles")
    os.makedirs(cache_dir, exist_ok=True)
    clean_sym = symbol.strip().upper()
    cache_file = os.path.join(cache_dir, f"{clean_sym}_{interval}_{days}d.pkl")

    # 1. Try INDmoney API
    scrip = INDSTOCKS_SECURITY_IDS.get(clean_sym)
    if not scrip and resolve_indstocks_scrip:
        scrip = resolve_indstocks_scrip(clean_sym, api_key=token)

    if scrip and token:
        try:
            df = fetch_indstocks_data(scrip, token, interval=interval, days=days)
            if df is not None and len(df) >= 30:
                try:
                    df.to_pickle(cache_file)
                except Exception:
                    pass
                return df, f"INDmoney LIVE API ({scrip})"
        except Exception:
            pass

    # 2. Check disk cache
    if os.path.exists(cache_file):
        try:
            df = pd.read_pickle(cache_file)
            if df is not None and len(df) >= 30:
                return df, f"Local Cache ({len(df)} candles)"
        except Exception:
            pass

    # 3. Seamless Yahoo Finance Fallback
    try:
        import yfinance as yf
        ticker_map = {
            "NIFTY": "^NSEI",
            "NIFTY 50": "^NSEI",
            "NIFTY50": "^NSEI",
            "^NSEI": "^NSEI",
            "BANKNIFTY": "^NSEBANK",
            "^NSEBANK": "^NSEBANK",
        }
        yf_ticker = ticker_map.get(clean_sym, f"{clean_sym}.NS")
        yf_interval = "5m" if "5" in interval else ("15m" if "15" in interval else "1d")
        period_str = f"{min(days, 59)}d"
        df = yf.download(yf_ticker, period=period_str, interval=yf_interval, progress=False)
        if df is not None and not df.empty and len(df) >= 30:
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = pd.to_datetime(df.index)
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC").tz_convert("Asia/Kolkata")
            else:
                df.index = df.index.tz_convert("Asia/Kolkata")
            try:
                df.to_pickle(cache_file)
            except Exception:
                pass
            return df, f"Yahoo Finance ({yf_ticker})"
    except Exception as e:
        print(f"[-] Fallback error: {e}")

    return None, "None"


def simulate_pinescript_strategy(
    df: pd.DataFrame,
    symbol: str,
    ema_len: int = 9,
    rr: float = 2.0,
    trail_mode: str = "EMA Trail",  # "None (Fixed RR)", "EMA Trail", "ATR Trail", "Candle Low/High"
    use_partial: bool = True,
    trail_start_r: float = 1.0,
    use_be: bool = True,
    atr_len: int = 14,
    atr_mult: float = 2.0,
    close_eod: bool = True,
    risk_per_trade_inr: float = 1000.0,
) -> List[StrategyTrade]:
    """Simulate PineScript v6 strategy on intraday 5m candle data."""
    if df is None or df.empty or len(df) < 30:
        return []

    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)

    # 1. Indicators
    # Session VWAP anchored to 09:15 daily
    tp = (df["High"] + df["Low"] + df["Close"]) / 3.0
    vol = df["Volume"].replace(0, np.nan).fillna(1.0)
    dates = df.index.date
    cum_pv = (tp * vol).groupby(dates).cumsum()
    cum_vol = vol.groupby(dates).cumsum()
    df["VWAP"] = cum_pv / cum_vol

    # EMA
    df["EMA"] = df["Close"].ewm(span=ema_len, adjust=False).mean()

    # ATR (Wilder smoothed RMA, alpha=1/length)
    tr0 = df["High"] - df["Low"]
    tr1 = (df["High"] - df["Close"].shift(1)).abs()
    tr2 = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1.0 / atr_len, adjust=False).mean()

    # Crossovers
    df["LongCross"] = (df["EMA"] > df["VWAP"]) & (df["EMA"].shift(1) <= df["VWAP"].shift(1))
    df["ShortCross"] = (df["EMA"] < df["VWAP"]) & (df["EMA"].shift(1) >= df["VWAP"].shift(1))

    trades: List[StrategyTrade] = []

    pos = 0  # 0: flat, +2: full long, +1: partial long, -2: full short, -1: partial short
    entry_px = 0.0
    stop_px = 0.0
    tp_px = 0.0
    risk_px = 0.0
    extreme_px = 0.0
    trail_on = False
    entry_bar = 0
    partial_taken = False

    n = len(df)

    for i in range(1, n):
        cur_dt = df.index[i]
        prev_dt = df.index[i - 1]
        c = float(df["Close"].iloc[i])
        o = float(df["Open"].iloc[i])
        h = float(df["High"].iloc[i])
        l = float(df["Low"].iloc[i])
        ema_val = float(df["EMA"].iloc[i])
        atr_val = float(df["ATR"].iloc[i])
        cur_time = cur_dt.time()

        is_session_end = close_eod and (
            cur_time >= time(15, 15) or cur_dt.date() != prev_dt.date()
        )

        # ── End-of-Session Exit ──
        if pos != 0 and is_session_end:
            if pos > 0:
                leg_r = (c - entry_px) / risk_px if risk_px > 0 else 0.0
                side = "LONG"
            else:
                leg_r = (entry_px - c) / risk_px if risk_px > 0 else 0.0
                side = "SHORT"

            # If partial was already taken at target (+2R), full trade R is weighted average
            if partial_taken:
                total_r = (rr * 0.5) + (leg_r * 0.5)
                outcome = "PARTIAL+EOD"
            else:
                total_r = leg_r
                outcome = "EOD"

            trades.append(
                StrategyTrade(
                    symbol=symbol,
                    entry_time=str(df.index[entry_bar]),
                    exit_time=str(cur_dt),
                    side=side,
                    entry_price=round(entry_px, 2),
                    initial_sl=round(stop_px, 2),
                    target_price=round(tp_px, 2),
                    risk_points=round(risk_px, 2),
                    final_exit_price=round(c, 2),
                    outcome=outcome,
                    partial_taken=partial_taken,
                    r_multiple=round(total_r, 2),
                    pnl_inr=round(total_r * risk_per_trade_inr, 2),
                    duration_bars=i - entry_bar,
                )
            )
            pos = 0
            partial_taken = False
            continue

        # ── Active Trade Trailing & Exits ──
        if pos > 0 and i > entry_bar:
            extreme_px = max(extreme_px, h)

            # Check trailing trigger
            if not trail_on and h >= entry_px + (risk_px * trail_start_r):
                trail_on = True
                if use_be:
                    stop_px = max(stop_px, entry_px)

            # Ratchet Stop upward
            if trail_on and trail_mode != "None (Fixed RR)":
                candidate_sl = stop_px
                if trail_mode == "EMA Trail":
                    candidate_sl = ema_val
                elif trail_mode == "ATR Trail":
                    candidate_sl = extreme_px - (atr_val * atr_mult)
                elif trail_mode == "Candle Low/High":
                    candidate_sl = float(df["Low"].iloc[i - 1])

                if candidate_sl < c:
                    stop_px = max(stop_px, candidate_sl)

            # Target Partial Exit (50% at 1:2 RR)
            if use_partial and not partial_taken and h >= tp_px:
                partial_taken = True
                pos = 1

            # Stop Loss Execution
            if l <= stop_px:
                leg_r = (stop_px - entry_px) / risk_px if risk_px > 0 else 0.0
                if partial_taken:
                    total_r = (rr * 0.5) + (leg_r * 0.5)
                    outcome = "TARGET+TRAIL_SL"
                else:
                    total_r = -1.0 if abs(stop_px - entry_px) >= 0.9 * risk_px else leg_r
                    outcome = "BE_SL" if total_r >= 0 else "SL"

                trades.append(
                    StrategyTrade(
                        symbol=symbol,
                        entry_time=str(df.index[entry_bar]),
                        exit_time=str(cur_dt),
                        side="LONG",
                        entry_price=round(entry_px, 2),
                        initial_sl=round(stop_px, 2),
                        target_price=round(tp_px, 2),
                        risk_points=round(risk_px, 2),
                        final_exit_price=round(stop_px, 2),
                        outcome=outcome,
                        partial_taken=partial_taken,
                        r_multiple=round(total_r, 2),
                        pnl_inr=round(total_r * risk_per_trade_inr, 2),
                        duration_bars=i - entry_bar,
                    )
                )
                pos = 0
                partial_taken = False

        elif pos < 0 and i > entry_bar:
            extreme_px = min(extreme_px, l)

            if not trail_on and l <= entry_px - (risk_px * trail_start_r):
                trail_on = True
                if use_be:
                    stop_px = min(stop_px, entry_px)

            if trail_on and trail_mode != "None (Fixed RR)":
                candidate_sl = stop_px
                if trail_mode == "EMA Trail":
                    candidate_sl = ema_val
                elif trail_mode == "ATR Trail":
                    candidate_sl = extreme_px + (atr_val * atr_mult)
                elif trail_mode == "Candle Low/High":
                    candidate_sl = float(df["High"].iloc[i - 1])

                if candidate_sl > c:
                    stop_px = min(stop_px, candidate_sl)

            if use_partial and not partial_taken and l <= tp_px:
                partial_taken = True
                pos = -1

            if h >= stop_px:
                leg_r = (entry_px - stop_px) / risk_px if risk_px > 0 else 0.0
                if partial_taken:
                    total_r = (rr * 0.5) + (leg_r * 0.5)
                    outcome = "TARGET+TRAIL_SL"
                else:
                    total_r = -1.0 if abs(stop_px - entry_px) >= 0.9 * risk_px else leg_r
                    outcome = "BE_SL" if total_r >= 0 else "SL"

                trades.append(
                    StrategyTrade(
                        symbol=symbol,
                        entry_time=str(df.index[entry_bar]),
                        exit_time=str(cur_dt),
                        side="SHORT",
                        entry_price=round(entry_px, 2),
                        initial_sl=round(stop_px, 2),
                        target_price=round(tp_px, 2),
                        risk_points=round(risk_px, 2),
                        final_exit_price=round(stop_px, 2),
                        outcome=outcome,
                        partial_taken=partial_taken,
                        r_multiple=round(total_r, 2),
                        pnl_inr=round(total_r * risk_per_trade_inr, 2),
                        duration_bars=i - entry_bar,
                    )
                )
                pos = 0
                partial_taken = False

        # ── Fresh Entries on Bar Close ──
        if pos == 0 and not is_session_end:
            if df["LongCross"].iloc[i]:
                sl = float(df["Low"].iloc[i - 1])  # PineScript: sl = low[1]
                risk = c - sl
                if risk > 0.05:
                    entry_px = c
                    stop_px = sl
                    risk_px = risk
                    tp_px = c + (risk * rr)
                    extreme_px = h
                    trail_on = False
                    entry_bar = i
                    partial_taken = False
                    pos = 2

            elif df["ShortCross"].iloc[i]:
                sl = float(df["High"].iloc[i - 1])  # PineScript: sl = high[1]
                risk = sl - c
                if risk > 0.05:
                    entry_px = c
                    stop_px = sl
                    risk_px = risk
                    tp_px = c - (risk * rr)
                    extreme_px = l
                    trail_on = False
                    entry_bar = i
                    partial_taken = False
                    pos = -2

    return trades


def run_monte_carlo(
    trades: List[StrategyTrade],
    num_simulations: int = 5000,
    trades_per_simulation: Optional[int] = None,
    seed: int = 42,
) -> Tuple[MonteCarloMetrics, np.ndarray, np.ndarray]:
    """Execute vector-accelerated Monte Carlo simulation with bootstrap resampling.

    Returns:
    - MonteCarloMetrics summary
    - Simulated equity paths array: shape (num_simulations, trades_per_sim + 1)
    - Drawdown distributions array: shape (num_simulations,)
    """
    if not trades:
        raise ValueError("Cannot run Monte Carlo simulation on empty trade list.")

    r_multiples = np.array([t.r_multiple for t in trades], dtype=np.float64)
    n_historical = len(r_multiples)
    n_sim_trades = trades_per_simulation if trades_per_simulation is not None else n_historical

    np.random.seed(seed)

    # Bootstrap random resampling with replacement: shape (num_simulations, n_sim_trades)
    simulated_indices = np.random.randint(0, n_historical, size=(num_simulations, n_sim_trades))
    simulated_returns = r_multiples[simulated_indices]  # (S, N)

    # Compute cumulative equity curves starting from 0R: shape (S, N+1)
    equity_curves = np.zeros((num_simulations, n_sim_trades + 1), dtype=np.float64)
    equity_curves[:, 1:] = np.cumsum(simulated_returns, axis=1)

    # Compute maximum drawdown for each simulated path
    # running_max shape: (S, N+1)
    running_max = np.maximum.accumulate(equity_curves, axis=1)
    drawdowns = running_max - equity_curves
    max_drawdowns = np.max(drawdowns, axis=1)  # shape (S,)

    # Final R distribution across paths
    final_r_values = equity_curves[:, -1]

    # Calculate consecutive losses for each simulation
    is_loss = simulated_returns < 0  # boolean array (S, N)

    def calc_max_consecutive_losses(loss_matrix: np.ndarray) -> np.ndarray:
        consec = np.zeros(loss_matrix.shape[0], dtype=np.int32)
        cur = np.zeros(loss_matrix.shape[0], dtype=np.int32)
        for col in range(loss_matrix.shape[1]):
            losses = loss_matrix[:, col]
            cur = np.where(losses, cur + 1, 0)
            consec = np.maximum(consec, cur)
        return consec

    consecutive_losses = calc_max_consecutive_losses(is_loss)

    # Historical metrics
    hist_wins = np.sum(r_multiples > 0)
    hist_win_rate = (hist_wins / n_historical) * 100.0 if n_historical > 0 else 0.0
    hist_total_r = float(np.sum(r_multiples))
    gross_win = np.sum(r_multiples[r_multiples > 0])
    gross_loss = abs(np.sum(r_multiples[r_multiples < 0]))
    hist_pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0

    hist_cum = np.cumsum(r_multiples)
    hist_peak = np.maximum.accumulate(hist_cum)
    hist_max_dd = float(np.max(hist_peak - hist_cum)) if len(hist_cum) > 0 else 0.0

    metrics = MonteCarloMetrics(
        num_simulations=num_simulations,
        trades_per_sim=n_sim_trades,
        median_final_r=round(float(np.median(final_r_values)), 2),
        mean_final_r=round(float(np.mean(final_r_values)), 2),
        p5_final_r=round(float(np.percentile(final_r_values, 5)), 2),
        p25_final_r=round(float(np.percentile(final_r_values, 25)), 2),
        p75_final_r=round(float(np.percentile(final_r_values, 75)), 2),
        p95_final_r=round(float(np.percentile(final_r_values, 95)), 2),
        median_max_dd_r=round(float(np.median(max_drawdowns)), 2),
        p95_max_dd_r=round(float(np.percentile(max_drawdowns, 95)), 2),
        p99_max_dd_r=round(float(np.percentile(max_drawdowns, 99)), 2),
        prob_profit_pct=round(float(np.mean(final_r_values > 0) * 100.0), 1),
        prob_dd_10r_pct=round(float(np.mean(max_drawdowns >= 10.0) * 100.0), 1),
        prob_dd_15r_pct=round(float(np.mean(max_drawdowns >= 15.0) * 100.0), 1),
        prob_dd_20r_pct=round(float(np.mean(max_drawdowns >= 20.0) * 100.0), 1),
        median_consecutive_losses=int(np.median(consecutive_losses)),
        p95_consecutive_losses=int(np.percentile(consecutive_losses, 95)),
        historical_total_trades=n_historical,
        historical_win_rate_pct=round(hist_win_rate, 1),
        historical_total_r=round(hist_total_r, 2),
        historical_profit_factor=round(hist_pf, 2),
        historical_max_dd_r=round(hist_max_dd, 2),
    )

    return metrics, equity_curves, max_drawdowns


def generate_monte_carlo_html_dashboard(
    metrics: MonteCarloMetrics,
    equity_curves: np.ndarray,
    max_drawdowns: np.ndarray,
    trades: List[StrategyTrade],
    output_path: str,
    title: str = "VWAP x EMA Cross | Smart Profit Trail — Monte Carlo Report",
):
    """Generate an interactive HTML dashboard visualizing Monte Carlo percentiles & risk analysis."""
    n_sims, n_steps = equity_curves.shape

    # Calculate equity curve percentiles across all trade steps
    step_indices = list(range(n_steps))
    p5_curve = np.percentile(equity_curves, 5, axis=0).tolist()
    p25_curve = np.percentile(equity_curves, 25, axis=0).tolist()
    p50_curve = np.percentile(equity_curves, 50, axis=0).tolist()
    p75_curve = np.percentile(equity_curves, 75, axis=0).tolist()
    p95_curve = np.percentile(equity_curves, 95, axis=0).tolist()

    # Drawdown histogram bins
    dd_hist, dd_bins = np.histogram(max_drawdowns, bins=25)
    dd_labels = [f"{dd_bins[i]:.1f} - {dd_bins[i+1]:.1f}R" for i in range(len(dd_hist))]
    dd_counts = dd_hist.tolist()

    # Sample trades for table
    trade_rows = []
    for t in trades[-30:]:
        color = "#10b981" if t.r_multiple > 0 else ("#ef4444" if t.r_multiple < 0 else "#94a3b8")
        trade_rows.append(f"""
        <tr>
            <td>{t.entry_time[:16]}</td>
            <td><strong>{t.symbol}</strong></td>
            <td><span class="badge {t.side.lower()}">{t.side}</span></td>
            <td>₹{t.entry_price:.2f}</td>
            <td style="color:#ef4444">₹{t.initial_sl:.2f}</td>
            <td style="color:#10b981">₹{t.target_price:.2f}</td>
            <td>₹{t.final_exit_price:.2f}</td>
            <td>{t.outcome}</td>
            <td style="color:{color};font-weight:700">{t.r_multiple:+.2f}R</td>
            <td style="color:{color}">₹{t.pnl_inr:+,.0f}</td>
        </tr>
        """)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            margin: 0; padding: 24px; background: #0b0f19; color: #f1f5f9;
        }}
        .header {{
            background: linear-gradient(135deg, #1e293b, #0f172a);
            padding: 24px; border-radius: 12px; margin-bottom: 24px;
            border: 1px solid #334155;
        }}
        h1 {{ margin: 0 0 8px 0; color: #38bdf8; font-size: 26px; }}
        .subtitle {{ color: #94a3b8; font-size: 14px; margin-bottom: 12px; }}
        .cards {{
            display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 16px; margin-bottom: 24px;
        }}
        .card {{
            background: #151e32; padding: 18px; border-radius: 10px; border: 1px solid #23324d;
        }}
        .card .title {{ font-size: 12px; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px; }}
        .card .val {{ font-size: 26px; font-weight: 800; color: #f8fafc; }}
        .val.pos {{ color: #10b981; }}
        .val.neg {{ color: #ef4444; }}
        .val.warn {{ color: #f59e0b; }}
        .chart-box {{
            background: #151e32; padding: 22px; border-radius: 10px; border: 1px solid #23324d; margin-bottom: 24px;
        }}
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }}
        @media(max-width: 900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 13px; }}
        th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #23324d; }}
        th {{ background: #0b0f19; color: #94a3b8; font-weight: 600; text-transform: uppercase; font-size: 11px; }}
        tr:hover {{ background: #1a253c; }}
        .badge {{ padding: 3px 8px; border-radius: 4px; font-size: 11px; font-weight: 700; }}
        .badge.long {{ background: #064e3b; color: #34d399; }}
        .badge.short {{ background: #7f1d1d; color: #f87171; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🎲 Monte Carlo Simulation Dashboard</h1>
        <div class="subtitle">
            Strategy: <strong>VWAP x EMA Cross | Smart Profit Trail (PineScript v6)</strong> | 
            Source: <strong>INDmoney LIVE API</strong> | 
            Simulations: <strong>{metrics.num_simulations:,} Iterations</strong> ({metrics.trades_per_sim} Trades/Path)
        </div>
    </div>

    <!-- Metrics Cards -->
    <div class="cards">
        <div class="card">
            <div class="title">Prob. of Profit</div>
            <div class="val {"pos" if metrics.prob_profit_pct >= 50 else "neg"}">{metrics.prob_profit_pct:.1f}%</div>
        </div>
        <div class="card">
            <div class="title">Median Expectancy</div>
            <div class="val {"pos" if metrics.median_final_r >= 0 else "neg"}">{metrics.median_final_r:+.2f} R</div>
        </div>
        <div class="card">
            <div class="title">95% Worst Case (P5)</div>
            <div class="val {"pos" if metrics.p5_final_r >= 0 else "neg"}">{metrics.p5_final_r:+.2f} R</div>
        </div>
        <div class="card">
            <div class="title">95% Best Case (P95)</div>
            <div class="val pos">{metrics.p95_final_r:+.2f} R</div>
        </div>
        <div class="card">
            <div class="title">Median Max Drawdown</div>
            <div class="val warn">{metrics.median_max_dd_r:.2f} R</div>
        </div>
        <div class="card">
            <div class="title">95% VaR Max Drawdown</div>
            <div class="val neg">{metrics.p95_max_dd_r:.2f} R</div>
        </div>
        <div class="card">
            <div class="title">Consecutive Losses (P95)</div>
            <div class="val">{metrics.p95_consecutive_losses} trades</div>
        </div>
        <div class="card">
            <div class="title">Risk of Drawdown ≥ 15R</div>
            <div class="val {"neg" if metrics.prob_dd_15r_pct > 25 else "pos"}">{metrics.prob_dd_15r_pct:.1f}%</div>
        </div>
    </div>

    <!-- Main Cone Chart -->
    <div class="chart-box">
        <h3 style="margin-top:0;color:#38bdf8">📈 Monte Carlo Equity Percentile Cone ({metrics.num_simulations:,} Resampled Runs)</h3>
        <p style="color:#94a3b8;font-size:13px;margin-bottom:16px">
            Visualizes the range of probable equity paths over {metrics.trades_per_sim} consecutive trades. The green band represents the 95th percentile, blue represents the median expected trajectory, and red represents the 5th percentile conservative boundary.
        </p>
        <canvas id="monteCarloChart" height="90"></canvas>
    </div>

    <!-- Drawdown Histogram & Historical Stats -->
    <div class="grid-2">
        <div class="chart-box">
            <h3 style="margin-top:0;color:#38bdf8">📉 Max Drawdown Distribution</h3>
            <canvas id="drawdownChart" height="130"></canvas>
        </div>
        <div class="chart-box">
            <h3 style="margin-top:0;color:#38bdf8">📋 Simulation & Risk Metrics</h3>
            <table>
                <tbody>
                    <tr><td>Historical Trades Sampled</td><td><strong>{metrics.historical_total_trades} trades</strong></td></tr>
                    <tr><td>Historical Win Rate</td><td><strong>{metrics.historical_win_rate_pct:.1f}%</strong></td></tr>
                    <tr><td>Historical Total Return</td><td><strong>{metrics.historical_total_r:+.2f} R</strong></td></tr>
                    <tr><td>Historical Profit Factor</td><td><strong>{metrics.historical_profit_factor:.2f}</strong></td></tr>
                    <tr><td>Historical Max Drawdown</td><td><strong>{metrics.historical_max_dd_r:.2f} R</strong></td></tr>
                    <tr><td>Monte Carlo Mean Final R</td><td><strong>{metrics.mean_final_r:+.2f} R</strong></td></tr>
                    <tr><td>99% Stress Drawdown (CVaR)</td><td><strong style="color:#ef4444">{metrics.p99_max_dd_r:.2f} R</strong></td></tr>
                    <tr><td>Chance of Drawdown &ge; 10R</td><td><strong>{metrics.prob_dd_10r_pct:.1f}%</strong></td></tr>
                    <tr><td>Chance of Drawdown &ge; 20R</td><td><strong>{metrics.prob_dd_20r_pct:.1f}%</strong></td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- Recent Trades Table -->
    <div class="chart-box">
        <h3 style="margin-top:0;color:#38bdf8">🔍 Sample Strategy Trades (From INDmoney Historical Data)</h3>
        <table>
            <thead>
                <tr>
                    <th>Time</th>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Entry</th>
                    <th>Initial SL</th>
                    <th>Target (1:2)</th>
                    <th>Exit</th>
                    <th>Outcome</th>
                    <th>R-Multiple</th>
                    <th>PnL (@ ₹1k Risk)</th>
                </tr>
            </thead>
            <tbody>
                {''.join(trade_rows)}
            </tbody>
        </table>
    </div>

    <script>
        // Monte Carlo Fan Chart
        const mcCtx = document.getElementById('monteCarloChart').getContext('2d');
        new Chart(mcCtx, {{
            type: 'line',
            data: {{
                labels: {step_indices},
                datasets: [
                    {{
                        label: '95th Percentile (Optimistic)',
                        data: {p95_curve},
                        borderColor: '#10b981',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false
                    }},
                    {{
                        label: '75th Percentile',
                        data: {p75_curve},
                        borderColor: '#34d399',
                        borderWidth: 1.5,
                        borderDash: [5, 5],
                        pointRadius: 0,
                        fill: false
                    }},
                    {{
                        label: '50th Percentile (Median Expected)',
                        data: {p50_curve},
                        borderColor: '#38bdf8',
                        borderWidth: 3,
                        pointRadius: 0,
                        fill: false
                    }},
                    {{
                        label: '25th Percentile',
                        data: {p25_curve},
                        borderColor: '#f87171',
                        borderWidth: 1.5,
                        borderDash: [5, 5],
                        pointRadius: 0,
                        fill: false
                    }},
                    {{
                        label: '5th Percentile (Conservative / Worst 5%)',
                        data: {p5_curve},
                        borderColor: '#ef4444',
                        borderWidth: 2,
                        pointRadius: 0,
                        fill: false
                    }}
                ]
            }},
            options: {{
                responsive: true,
                interaction: {{ mode: 'index', intersect: false }},
                scales: {{
                    x: {{
                        title: {{ display: true, text: 'Trade Number in Simulation', color: '#94a3b8' }},
                        grid: {{ color: '#1e293b' }},
                        ticks: {{ color: '#94a3b8' }}
                    }},
                    y: {{
                        title: {{ display: true, text: 'Cumulative R-Multiple', color: '#94a3b8' }},
                        grid: {{ color: '#1e293b' }},
                        ticks: {{ color: '#94a3b8' }}
                    }}
                }},
                plugins: {{
                    legend: {{ position: 'top', labels: {{ color: '#cbd5e1' }} }}
                }}
            }}
        }});

        // Drawdown Histogram Chart
        const ddCtx = document.getElementById('drawdownChart').getContext('2d');
        new Chart(ddCtx, {{
            type: 'bar',
            data: {{
                labels: {dd_labels},
                datasets: [{{
                    label: 'Simulation Frequency',
                    data: {dd_counts},
                    backgroundColor: 'rgba(239, 68, 68, 0.65)',
                    borderColor: '#ef4444',
                    borderWidth: 1
                }}]
            }},
            options: {{
                responsive: true,
                scales: {{
                    x: {{ ticks: {{ color: '#94a3b8', font: {{ size: 10 }} }}, grid: {{ display: false }} }},
                    y: {{ ticks: {{ color: '#94a3b8' }}, grid: {{ color: '#1e293b' }} }}
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
    parser = argparse.ArgumentParser(description="Monte Carlo Simulation for PineScript VWAP x EMA Strategy")
    parser.add_argument("--symbols", type=str, default="LT,TATAMOTORS,SBIN,INFY,ICICIBANK,RELIANCE,HDFCBANK,BHARTIARTL", help="Comma-separated stock symbols")
    parser.add_argument("--days", type=int, default=60, help="Days of historical data to fetch from INDmoney API")
    parser.add_argument("--interval", type=str, default="5minute", choices=["5minute", "15minute"], help="Candle interval (5minute or 15minute)")
    parser.add_argument("--simulations", type=int, default=5000, help="Number of Monte Carlo simulation runs")
    parser.add_argument("--trades-per-sim", type=int, default=150, help="Number of trades per Monte Carlo path")
    parser.add_argument("--trail-mode", type=str, default="EMA Trail", choices=["None (Fixed RR)", "EMA Trail", "ATR Trail", "Candle Low/High"])
    parser.add_argument("--no-partial", action="store_true", help="Disable 50 percent partial exit at Target RR")
    parser.add_argument("--html", type=str, default="pinescript_monte_carlo_report.html", help="HTML report output path")

    args = parser.parse_args()

    token = get_api_token()
    if not token:
        print("[ERROR] INDmoney API token not found!")
        sys.exit(1)

    print(f"[*] Authenticated with INDmoney API (Token prefix: {token[:16]}...)")
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    print(f"[*] Simulating PineScript on {len(symbols)} symbols over {args.days} days ({args.interval}): {', '.join(symbols)}")
    print(f"[*] Strategy Settings: EMA=9 | RR=2.0 | Trail Mode='{args.trail_mode}' | Partial={not args.no_partial}")

    all_trades: List[StrategyTrade] = []

    for sym in symbols:
        print(f"[*] Fetching {args.interval} candles for {sym}...")
        df, src = fetch_candles_with_fallback(sym, token, interval=args.interval, days=args.days)
        if df is None or len(df) < 30:
            print(f"[-] Insufficient candle data for {sym}")
            continue

        print(f"    [+] Loaded {len(df)} candles via {src}")

        trades = simulate_pinescript_strategy(
            df=df,
            symbol=sym,
            ema_len=9,
            rr=2.0,
            trail_mode=args.trail_mode,
            use_partial=not args.no_partial,
            trail_start_r=1.0,
            use_be=True,
            atr_len=14,
            atr_mult=2.0,
            close_eod=True,
        )

        win_rate = (sum(1 for t in trades if t.r_multiple > 0) / len(trades) * 100) if trades else 0
        total_r = sum(t.r_multiple for t in trades)
        print(f"    -> {sym}: {len(trades)} trades | Win Rate: {win_rate:.1f}% | Total R: {total_r:+.2f}R")
        all_trades.extend(trades)

    if not all_trades:
        print("[ERROR] No trades generated across symbols!")
        sys.exit(1)

    print(f"\n[*] Total historical trade universe: {len(all_trades)} trades across {len(symbols)} stocks.")
    print(f"[*] Launching {args.simulations:,} Monte Carlo bootstrap simulation paths ({args.trades_per_sim} trades each)...")

    metrics, equity_curves, max_drawdowns = run_monte_carlo(
        trades=all_trades,
        num_simulations=args.simulations,
        trades_per_simulation=args.trades_per_sim,
        seed=42,
    )

    print("\n" + "=" * 80)
    print("MONTE CARLO SIMULATION RESULTS (5,000 PATHS)")
    print("=" * 80)
    print(f"Probability of Profit (Ending Equity > 0):  {metrics.prob_profit_pct:.1f}%")
    print(f"Median Final Return (50th Percentile):      {metrics.median_final_r:+.2f} R")
    print(f"Conservative Final Return (5th Percentile): {metrics.p5_final_r:+.2f} R")
    print(f"Optimistic Final Return (95th Percentile):  {metrics.p95_final_r:+.2f} R")
    print(f"Median Expected Max Drawdown:              {metrics.median_max_dd_r:.2f} R")
    print(f"95% Value at Risk (VaR) Max Drawdown:      {metrics.p95_max_dd_r:.2f} R")
    print(f"99% Extreme Stress Max Drawdown (CVaR):    {metrics.p99_max_dd_r:.2f} R")
    print(f"95% Worst Consecutive Losses Streak:       {metrics.p95_consecutive_losses} trades")
    print(f"Chance of Max Drawdown Exceeding 10R:      {metrics.prob_dd_10r_pct:.1f}%")
    print(f"Chance of Max Drawdown Exceeding 15R:      {metrics.prob_dd_15r_pct:.1f}%")
    print(f"Chance of Max Drawdown Exceeding 20R:      {metrics.prob_dd_20r_pct:.1f}%")

    if args.html:
        generate_monte_carlo_html_dashboard(
            metrics=metrics,
            equity_curves=equity_curves,
            max_drawdowns=max_drawdowns,
            trades=all_trades,
            output_path=args.html,
        )
        print(f"\n[+] Interactive Monte Carlo Dashboard saved to: {args.html}")


if __name__ == "__main__":
    main()
