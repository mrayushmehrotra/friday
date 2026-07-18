# Quant Trading Bot — Implementation Checklist

## Phase 1: Data Pipeline
- [ ] Download all Nifty 500 stocks (yfinance / nsepython)
- [ ] Store daily OHLCV data locally (SQLite / parquet)
- [ ] Schedule pre-market data fetch (e.g., 8:00 AM IST)

## Phase 2: Indicators & Scoring
- [x] Relative Volume (RVOL) — ratio of current volume to avg(14d)
- [x] Average True Range (ATR — 14 period)
- [x] Gap % — (open - prev close) / prev close
- [x] EMA alignment — 9/21/50 EMA sorted check
- [x] VWAP distance — % distance from VWAP
- [x] RSI — 14 period
- [x] Relative strength vs Nifty — stock return / Nifty return (5d)

## Phase 3: Sentiment
- [x] Fetch news headlines per stock (yfinance / Google News)
- [x] Score sentiment via lightweight model (VADER)
- [x] Incorporate sentiment score into ranking

## Phase 4: Sector Analysis
- [ ] Map each Nifty 500 stock to sector
- [ ] Compute sector relative strength (avg sector return vs Nifty)
- [ ] Add sector score to ranking

## Phase 5: Ranking Engine
- [x] Weighted score: RVOL (10%), ATR (10%), gap (15%), EMA (20%), VWAP (15%), RSI (10%), relative strength (10%), sentiment (10%)
- [x] Rank all stocks → top 10–20
- [ ] Output ranked list before market open (9:15 AM IST)

## Phase 6: Intraday Execution
- [ ] 5-min bar polling during market hours
- [ ] Opening Range Breakout (ORB) — break of first 15-min high/low
- [ ] VWAP breakout — price > VWAP + threshold for long, < for short
- [ ] Entry only if stock is in pre-market ranked list
- [ ] SL / trailing stop per trade

## Phase 7: Dashboard & Alerts
- [x] Web dashboard — today's ranked list
- [ ] Telegram / desktop notification on trade entry/exit
- [ ] Daily summary report (win rate, P&L, Sharpe)

## Phase 8: Backtesting
- [ ] Walk-forward backtest on historical data (6+ months)
- [ ] Compare ORB vs VWAP vs combined strategy
- [ ] Output equity curve, drawdown, trade log
