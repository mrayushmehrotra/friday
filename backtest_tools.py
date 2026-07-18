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
class Signal:
    action: str
    size: float = 1.0
    reason: str = ""


@dataclass
class Position:
    size: float
    entry_price: float
    entry_date: pd.Timestamp
    current_price: float = 0.0
    highest_price: float = 0.0


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


def fetch_data(
    ticker: str,
    start: str = "2y",
    end: Optional[str] = None,
    interval: str = "1d",
) -> pd.DataFrame:
    period_patterns = ("d", "mo", "wk", "y")
    if any(start.endswith(suf) for suf in period_patterns) and end is None:
        df = yf.download(ticker, period=start, interval=interval, progress=False)
    elif end:
        df = yf.download(ticker, start=start, end=end, interval=interval, progress=False)
    else:
        df = yf.download(ticker, start=start, interval=interval, progress=False)
    if df.empty:
        raise ValueError(f"No data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    close = df["Close"]

    rsi = technicals.relative_strength_index(close, 14)
    df["RSI"] = rsi

    macd = technicals.macd(close)
    df["MACD"] = macd

    bb = technicals.bollinger_bands(close, 20, 2)
    df["BB_upper"] = bb.iloc[:, 0]
    df["BB_lower"] = bb.iloc[:, 1]
    df["BB_mid"] = technicals.moving_average(close, 20)

    df["SMA_20"] = technicals.moving_average(close, 20)
    df["SMA_50"] = technicals.moving_average(close, 50)
    df["EMA_12"] = technicals.exponential_moving_average(close, beta=0.75)
    df["Volatility"] = technicals.exponential_volatility(close, beta=0.75)

    volume_ma = technicals.moving_average(df["Volume"], 20)
    df["Volume_ratio"] = df["Volume"] / volume_ma

    df["Returns"] = technicals.returns(close)
    df["ZScore"] = statistics.zscores(close, 20)
    df.dropna(inplace=True)
    return df


def compute_performance(equity: pd.Series, trades: List[Trade]) -> BacktestResult:
    if len(equity) < 2:
        daily_returns = pd.Series(dtype=float)
    else:
        daily_returns = equity.pct_change().dropna()

    if len(daily_returns) > 0:
        total_ret = (equity.iloc[-1] / equity.iloc[0]) - 1
        n_years = len(equity) / 252
        ann_ret = (1 + total_ret) ** (1 / n_years) - 1 if n_years > 0 else 0.0
        sharpe = (
            (daily_returns.mean() / daily_returns.std() * np.sqrt(252))
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
        )

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
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
    )


def run_backtest(
    df: pd.DataFrame,
    signal_fn: Callable[[pd.DataFrame, int], Signal],
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
) -> BacktestResult:
    df = df.copy()
    cash = initial_capital
    position: Optional[Position] = None
    trades: List[Trade] = []
    equity = pd.Series(index=df.index, dtype=float)

    for i in range(len(df)):
        row = df.iloc[i]
        date = df.index[i]
        price = float(row["Close"])

        sig = signal_fn(df, i)

        # Check stop-loss and trailing stop
        if position is not None:
            position.current_price = price
            if price > position.highest_price:
                position.highest_price = price

            exit_reason = None
            if stop_loss_pct is not None:
                loss_pct = (price / position.entry_price - 1) * 100
                if loss_pct <= -abs(stop_loss_pct):
                    exit_reason = f"Stop-loss ({loss_pct:.1f}%)"
            if exit_reason is None and trailing_stop_pct is not None:
                from_peak = (price / position.highest_price - 1) * 100
                if from_peak <= -abs(trailing_stop_pct):
                    exit_reason = f"Trailing stop (-{abs(trailing_stop_pct):.1f}% from ₹{position.highest_price:.2f})"

            if exit_reason:
                proceeds = position.size * price * (1 - commission_pct)
                pnl = proceeds - (position.size * position.entry_price)
                pnl_pct = (price / position.entry_price - 1) * 100
                trades.append(Trade(
                    entry_date=position.entry_date, exit_date=date,
                    entry_price=position.entry_price, exit_price=price,
                    size=position.size, pnl_pct=pnl_pct, pnl=pnl, reason=exit_reason,
                ))
                cash += proceeds
                position = None

        if sig.action == "BUY" and position is None:
            allocated = cash * sig.size
            shares = (allocated / price) * (1 - commission_pct)
            cost = shares * price
            position = Position(size=shares, entry_price=price, entry_date=date, highest_price=price)
            cash -= cost

        elif sig.action == "SELL" and position is not None:
            proceeds = position.size * price * (1 - commission_pct)
            pnl = proceeds - (position.size * position.entry_price)
            pnl_pct = (price / position.entry_price - 1) * 100
            trades.append(Trade(
                entry_date=position.entry_date, exit_date=date,
                entry_price=position.entry_price, exit_price=price,
                size=position.size, pnl_pct=pnl_pct, pnl=pnl, reason=sig.reason,
            ))
            cash += proceeds
            position = None

        elif sig.action == "EXIT" and position is not None:
            proceeds = position.size * price * (1 - commission_pct)
            pnl = proceeds - (position.size * position.entry_price)
            pnl_pct = (price / position.entry_price - 1) * 100
            trades.append(Trade(
                entry_date=position.entry_date, exit_date=date,
                entry_price=position.entry_price, exit_price=price,
                size=position.size, pnl_pct=pnl_pct, pnl=pnl, reason=sig.reason or "exit",
            ))
            cash += proceeds
            position = None

        holdings = (position.size * price) if position is not None else 0.0
        equity.iloc[i] = cash + holdings

    if position is not None:
        price = float(df["Close"].iloc[-1])
        proceeds = position.size * price * (1 - commission_pct)
        pnl = proceeds - (position.size * position.entry_price)
        pnl_pct = (price / position.entry_price - 1) * 100
        trades.append(Trade(
            entry_date=position.entry_date, exit_date=df.index[-1],
            entry_price=position.entry_price, exit_price=price,
            size=position.size, pnl_pct=pnl_pct, pnl=pnl, reason="end of backtest",
        ))
        cash += proceeds
        position = None
        equity.iloc[-1] = cash

    return compute_performance(equity, trades)


def format_result(result: BacktestResult, ticker: str) -> str:
    ccy = "₹" if ticker.endswith(".NS") or ticker in INDIAN_INDICES else "$"
    lines = [
        f"Backtest Results for {ticker.replace('.NS', '')}",
        f"{'=' * 50}",
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
                f"  {t.entry_date.date()} -> {t.exit_date.date()} | "
                f"LONG | {ccy}{t.entry_price:.2f} -> {ccy}{t.exit_price:.2f} | "
                f"PnL: {sign}{ccy}{t.pnl:.2f} ({sign}{t.pnl_pct:.2f}%) | {t.reason}"
            )

    return "\n".join(lines)


def format_result_json(result: BacktestResult) -> dict:
    return {
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
            {"date": str(d.date()), "value": round(float(v), 2)}
            for d, v in result.equity_curve.items()
        ],
        "drawdown_curve": _drawdown_curve(result.equity_curve),
        "trades": [
            {
                "entry_date": str(t.entry_date.date()),
                "exit_date": str(t.exit_date.date()),
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "pnl_pct": t.pnl_pct,
                "pnl": t.pnl,
                "reason": t.reason,
            }
            for t in result.trades
        ],
    }


def _drawdown_curve(equity: pd.Series) -> list:
    cummax = equity.cummax()
    dd = ((equity - cummax) / cummax * 100).fillna(0)
    return [
        {"date": str(d.date()), "value": round(float(v), 2)}
        for d, v in dd.items()
    ]


def example_strategies() -> Dict[str, str]:
    return {
        "rsi_mean_reversion": "RSI < 30 → BUY, RSI > 70 → SELL",
        "ma_crossover": "SMA_20 crosses above SMA_50 → BUY, crosses below → SELL",
        "bollinger_bounce": "Price touches BB_lower → BUY, touches BB_upper → SELL",
        "macd_signal": "MACD crosses above 0 → BUY, crosses below 0 → SELL",
        "sma_50_trend": "Price above SMA_50 and RSI > 50 → BUY, price below SMA_50 and RSI < 50 → SELL",
    }


def rsi_mean_reversion(df: pd.DataFrame, i: int) -> Signal:
    row = df.iloc[i]
    rsi = row.get("RSI", 50)
    if rsi < 30 and not pd.isna(rsi):
        return Signal("BUY", 1.0, f"RSI oversold ({rsi:.1f})")
    elif rsi > 70 and not pd.isna(rsi):
        return Signal("SELL", 1.0, f"RSI overbought ({rsi:.1f})")
    return Signal("HOLD")


def ma_crossover(df: pd.DataFrame, i: int) -> Signal:
    if i < 1:
        return Signal("HOLD")
    sma20_prev = df["SMA_20"].iloc[i - 1]
    sma50_prev = df["SMA_50"].iloc[i - 1]
    sma20_curr = df["SMA_20"].iloc[i]
    sma50_curr = df["SMA_50"].iloc[i]
    if pd.isna(sma20_prev) or pd.isna(sma50_prev) or pd.isna(sma20_curr) or pd.isna(sma50_curr):
        return Signal("HOLD")
    if sma20_prev <= sma50_prev and sma20_curr > sma50_curr:
        return Signal("BUY", 1.0, "Golden cross (SMA20 > SMA50)")
    elif sma20_prev >= sma50_prev and sma20_curr < sma50_curr:
        return Signal("SELL", 1.0, "Death cross (SMA20 < SMA50)")
    return Signal("HOLD")


def bollinger_bounce(df: pd.DataFrame, i: int) -> Signal:
    row = df.iloc[i]
    price = row["Close"]
    bb_lower = row.get("BB_lower")
    bb_upper = row.get("BB_upper")
    if pd.isna(bb_lower) or pd.isna(bb_upper):
        return Signal("HOLD")
    if price <= bb_lower:
        return Signal("BUY", 1.0, f"Price at lower BB ({price:.2f} <= {bb_lower:.2f})")
    elif price >= bb_upper:
        return Signal("SELL", 1.0, f"Price at upper BB ({price:.2f} >= {bb_upper:.2f})")
    return Signal("HOLD")


def macd_signal(df: pd.DataFrame, i: int) -> Signal:
    if i < 1:
        return Signal("HOLD")
    macd_curr = df["MACD"].iloc[i]
    macd_prev = df["MACD"].iloc[i - 1]
    if pd.isna(macd_curr) or pd.isna(macd_prev):
        return Signal("HOLD")
    if macd_prev <= 0 and macd_curr > 0:
        return Signal("BUY", 1.0, f"MACD crossed above 0 ({macd_curr:.2f})")
    elif macd_prev >= 0 and macd_curr < 0:
        return Signal("SELL", 1.0, f"MACD crossed below 0 ({macd_curr:.2f})")
    return Signal("HOLD")


def sma_50_trend(df: pd.DataFrame, i: int) -> Signal:
    row = df.iloc[i]
    price = row["Close"]
    sma50 = row.get("SMA_50")
    rsi = row.get("RSI", 50)
    if pd.isna(sma50):
        return Signal("HOLD")
    if price > sma50 and rsi > 50:
        return Signal("BUY", 1.0, f"Uptrend (price {price:.2f} > SMA50 {sma50:.2f}, RSI {rsi:.1f})")
    elif price < sma50 and rsi < 50:
        return Signal("SELL", 1.0, f"Downtrend (price {price:.2f} < SMA50 {sma50:.2f}, RSI {rsi:.1f})")
    return Signal("HOLD")


STRATEGY_MAP = {
    "rsi_mean_reversion": rsi_mean_reversion,
    "ma_crossover": ma_crossover,
    "bollinger_bounce": bollinger_bounce,
    "macd_signal": macd_signal,
    "sma_50_trend": sma_50_trend,
}


def run(
    ticker: str,
    strategy: str = "ma_crossover",
    start: str = "2y",
    end: Optional[str] = None,
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    interval: str = "1d",
    bse: bool = False,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
) -> BacktestResult:
    if strategy not in STRATEGY_MAP:
        raise ValueError(
            f"Unknown strategy '{strategy}'. Choose: {', '.join(STRATEGY_MAP.keys())}"
        )

    ticker = _resolve_ticker(ticker)
    if bse:
        ticker = ticker.replace(".NS", ".BO")

    df = fetch_data(ticker, start=start, end=end, interval=interval)
    df = add_indicators(df)
    signal_fn = STRATEGY_MAP[strategy]
    return run_backtest(df, signal_fn, initial_capital, commission_pct, stop_loss_pct, trailing_stop_pct)


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
) -> Dict[str, dict]:
    ticker = _resolve_ticker(ticker)
    if bse:
        ticker = ticker.replace(".NS", ".BO")

    df = fetch_data(ticker, start=start, end=end, interval=interval)
    df = add_indicators(df)

    results = {}
    for name, fn in STRATEGY_MAP.items():
        try:
            res = run_backtest(df.copy(), fn, initial_capital, commission_pct, stop_loss_pct, trailing_stop_pct)
            results[name] = format_result_json(res)
        except Exception as e:
            results[name] = {"error": str(e)}
    return results


def stock_of_the_day(
    start: str = "1y",
    strategy: str = "sma_50_trend",
    top_n: int = 5,
    initial_capital: float = 100_000,
    commission_pct: float = 0.001,
    tickers: Optional[List[str]] = None,
    movement_min: Optional[float] = 10,
    movement_max: Optional[float] = 30,
) -> List[Dict]:
    scan_list = tickers or NIFTY50
    results = []

    def _analyse(t):
        try:
            resolved = _resolve_ticker(t)
            df_1m = fetch_data(resolved, start="1mo")
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
    parser = argparse.ArgumentParser(description="Backtest trading strategies with yfinance + GS Quant")
    parser.add_argument("ticker", nargs="?", help="Stock ticker (e.g. RELIANCE, TCS, ^NSEI)")
    parser.add_argument("--strategy", "-s", default="ma_crossover",
                        choices=list(STRATEGY_MAP.keys()),
                        help="Trading strategy to backtest")
    parser.add_argument("--start", default="1y", help="Start date/period")
    parser.add_argument("--end", help="End date")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--commission", type=float, default=0.001, help="Commission per trade")
    parser.add_argument("--stop-loss", type=float, help="Stop-loss percentage (e.g. 5 for 5%)")
    parser.add_argument("--trailing-stop", type=float, help="Trailing stop percentage")
    parser.add_argument("--bse", action="store_true", help="Use BSE instead of NSE")
    parser.add_argument("--compare", "-c", action="store_true", help="Compare all strategies")
    parser.add_argument("--stock-of-day", "-d", action="store_true", help="Find stock of the day")
    parser.add_argument("--list-strategies", "-l", action="store_true", help="List strategies")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")

    args = parser.parse_args()

    if args.list_strategies:
        print("Available strategies:")
        for name, desc in example_strategies().items():
            print(f"  {name}: {desc}")
        exit(0)

    if args.stock_of_day:
        top = stock_of_the_day(start=args.start, strategy=args.strategy or "sma_50_trend")
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
            bse=args.bse, stop_loss_pct=args.stop_loss, trailing_stop_pct=args.trailing_stop,
        )
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            print(f"{'Strategy Comparison for ' + args.ticker.upper():=^60}")
            print(f"{'Strategy':<22} {'Return':>8} {'Sharpe':>8} {'Win%':>7} {'Trades':>7} {'Pf':>7}")
            print("-" * 60)
            for name, r in results.items():
                if "error" in r:
                    print(f"{name:<22} {'ERROR':>8}")
                else:
                    print(f"{name:<22} {r['total_return_pct']:>+7.2f}% {r['sharpe_ratio']:>7.2f} {r['win_rate']:>6.1f}% {r['num_trades']:>6d} {r['profit_factor']:>6.2f}")
        exit(0)

    result = run(
        ticker=args.ticker,
        strategy=args.strategy,
        start=args.start,
        end=args.end,
        initial_capital=args.capital,
        commission_pct=args.commission,
        bse=args.bse,
        stop_loss_pct=args.stop_loss,
        trailing_stop_pct=args.trailing_stop,
    )

    if args.json:
        print(json.dumps(format_result_json(result), indent=2))
    else:
        print(format_result(result, args.ticker))
