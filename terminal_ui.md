# Bloomberg Institutional Financial Terminal — Architecture, Data Engine & Trade Execution Blueprint (`terminal_ui.md`)

An institutional-grade financial workstation built specifically for **Indian Equities & Derivatives (NSE/BSE)**. It integrates the **INDmoney (INDstocks) Developer API** for real-time market data, pre-calculated Option Greeks, and sub-second trade execution, backed by **100% free verified public feeds** (NSE public JSON, Yahoo Finance, Screener.in, FRED, and Google News RSS).

This document unifies all repository capabilities, strategies, and architectural designs across [`terminal_features.md`](file:///home/ayush/personal/friday/terminal_features.md), [`todo.md`](file:///home/ayush/personal/friday/todo.md), [`assets/indstocks-api-docs.md`](file:///home/ayush/personal/friday/assets/indstocks-api-docs.md), [`indmoney_intraday_bot.py`](file:///home/ayush/personal/friday/indmoney_intraday_bot.py), [`gex.py`](file:///home/ayush/personal/friday/gex.py), [`daily_support_scanner.py`](file:///home/ayush/personal/friday/daily_support_scanner.py), [`bullish_put_filter.py`](file:///home/ayush/personal/friday/bullish_put_filter.py), [`opening_range_backtest.py`](file:///home/ayush/personal/friday/opening_range_backtest.py), and [`monte_carlo_pinescript.py`](file:///home/ayush/personal/friday/monte_carlo_pinescript.py).

---

## 1. Top-Level Architectural Hierarchy

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                        BLOOMBERG-STYLE COMMAND BAR & INDMONEY API VAULT                                │
│ [API TOKEN: eyJhbGci... ● CONNECTED] [FUNDS: ₹1,924.12 | SOD: ₹2,563.42 | PnL: +₹840.00] [CLI: RELIANCE GP] │
├────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Ticker Tape: NIFTY 25,514.30 (+124.50) │ BANKNIFTY 54,230.15 (+310.20) │ INDIA VIX 13.82 (-0.45)      │
├───────────────────────────────┬───────────────────────────────────────┬────────────────────────────────┤
│ 1. WATCHLIST & SCANNER        │ 2. ADVANCED INTERACTIVE CHARTING      │ 3. ORDER DESK & EXECUTION      │
│ • Custom Stock/Index Universe │ • TradingView Lightweight Charts      │ • Instant L1/L2 Market Depth   │
│ • 15m OR Displacement Alerts  │ • 9 EMA, Session VWAP, 18 SMMA        │ • 1-Click Buy/Sell Ticket      │
│ • VCP & Daily Support Levels  │ • ICT PD-Arrays, FVG & Order Blocks   │ • Bracket / Smart GTT Orders   │
│ • Daily Delivery & Volume     │ • Intraday 1m/5m/15m + 10Y EOD        │ • Live Position Blotter & PnL  │
├───────────────────────────────┴───────────────────────────────────────┴────────────────────────────────┤
│ 4. INSTITUTIONAL DERIVATIVES, GEX & GREEKS WORKBENCH (OMON / OVOL)                                     │
│ • Live Strike-by-Strike Option Chain (NIFTY, BANKNIFTY, SENSEX, F&O Equities)                           │
│ • Real-time Greeks (Delta, Gamma, Theta, Vega) + IV Skew + Max Pain + Gamma Flip Strike                 │
│ • Net Dealer Gamma Exposure (₹ Cr) + Buyer vs. Seller Control Verdict                                  │
├───────────────────────────────────────┬────────────────────────────────────────────────────────────────┤
│ 5. INSTITUTIONAL FLOWS & CORPORATE    │ 6. MACRO REGIME & MARKET WIRE                                  │
│ • Daily FII / DII Net Cash & F&O Flow │ • RBI Repo, CPI Inflation, India 10Y G-Sec Yield               │
│ • NSE Large Bulk & Block Deals (LTP)  │ • Breaking Market Headlines (Moneycontrol, ET, LiveMint RSS)   │
│ • Board Meetings & Earnings Calendar  │ • Market Breadth (Adv/Dec Ratio, 52W Highs/Lows)               │
└───────────────────────────────────────┴────────────────────────────────────────────────────────────────┘
```

---

## 2. Repository Markdown Manifest & Knowledge Base Integration

This terminal directly materializes the specifications, schemas, endpoints, and strategy rulebooks established across all markdown documentation files in this workspace:

### 1. [`terminal_features.md`](file:///home/ayush/personal/friday/terminal_features.md) — 9 Pillars & Zero-Cost Data Map
- **Pillars Integrated**:
  * Pillar 1: Live Market Data & L2 Depth (`INDmoney WebSockets` + `Historical REST`).
  * Pillar 2: Trade & Order Execution (`INDmoney REST /order`, `bracket GTT`).
  * Pillar 3: Derivatives, Greeks & Directional Engine (`GET /market/option-chain` + Black-Scholes local engine).
  * Pillar 4: Fundamental Analytics (`Yahoo Finance` 10Y Income, Balance Sheet, Cash Flow + `Screener.in` ratios).
  * Pillar 5: Shareholding & Institutional Flows (FII/DII Net Flow, Bulk/Block Deals, Insider Trading PIT).
  * Pillar 6: Corporate Events & Filings (Board meetings, Result announcements, Dividends, Splits, Bonus).
  * Pillar 7: Breaking News & AI Sentiment (Google News, Moneycontrol, ET RSS feeds with LLM sentiment scoring).
  * Pillar 8: Indian Macro Dashboard (RBI Repo, CPI, GDP, India 10Y G-Sec Yield via FRED API).
  * Pillar 9: Command-Line Workspace (Bloomberg mnemonics: `GP`, `OMON`, `FA`, `HDS`, `FIIDII`, `ECO`, `ORB`).
- **Anti-Blocking Best Practices**: Integrated request timeouts, local parquet caching, and browser User-Agent headers.

### 2. [`todo.md`](file:///home/ayush/personal/friday/todo.md) — Live GEX / Greeks, NSE Scraper & Options Handbook
- **Live GEX Report**: Integrates Net GEX, Call/Put GEX, per-strike Delta/Gamma/Theta/Vega, Max Pain strike, and the **Gamma Flip Strike** (where dealer hedging switches from volatility dampening to volatility amplifying).
- **NSE Events & Corporate Calendar**: Automated tracking of earnings announcement dates, board meetings, dividend ex-dates, and filings.
- **Market Decision-Support Matrix**: Real-time integration of India VIX, FII/DII participant-wise OI, Market Breadth (Adv/Dec), Delivery %, and F&O Ban list risk gates.
- **Options Edge Handbook**: Second-order Greeks approximation (**Charm** $\approx \Delta \text{Delta}/\Delta T$, **Vanna** $\approx \Delta \text{Delta}/\Delta \text{IV}$) and Theta-to-Gamma ratios to time momentum breakouts vs. premium decay.

### 3. [`assets/indstocks-api-docs.md`](file:///home/ayush/personal/friday/assets/indstocks-api-docs.md) — INDstocks Trading API Reference
- **Canonical API Endpoints**:
  * `GET /funds`: Live SOD balance, available margin, withdrawal balance, realized/unrealized PnL.
  * `POST /order` & `POST /smart/order`: Regular LIMIT/MARKET and Smart GTT bracket orders with Stop Loss and Target legs.
  * `GET /order-book`, `GET /trade-book`, `GET /position-book`: Order blotter, execution receipts, and active positions.
  * `GET /market/option-chain`: Full strike ladder with native exchange-calculated Greeks (`delta`, `gamma`, `theta`, `vega`, `iv`, `oi`).
  * `GET /market/historical/{interval}`: 1m, 5m, 15m, 60m, 1day OHLCV candles (anchored to 09:15 session open).
  * `NIDX_` Prefix Convention: Seamless index quoting for **NIFTY 50** (`NIDX_40000001`) and **BANKNIFTY** (`NIDX_40000002`).

### 4. [`assets/yt_upload_next/DESIGN.md`](file:///home/ayush/personal/friday/assets/yt_upload_next/DESIGN.md), [`TODO.md`](file:///home/ayush/personal/friday/assets/yt_upload_next/TODO.md), [`README.md`](file:///home/ayush/personal/friday/assets/yt_upload_next/README.md) — Automated Market Video & Chart Snapshot Pipeline
- Automated screen capture engine rendering institutional daily market recap cards, GEX heatmap summaries, and chart setups for reporting and social broadcast.

---

## 3. Frontend INDmoney API Key Authentication Vault

To eliminate manual `.env` file editing and enable instant browser-based plug-and-play access, the terminal features a **persistent authentication vault** anchored to the top command bar.

### A. Frontend Token Input Workflow
1. **Interactive Entry Field**:
   - Placed at the top-left of the terminal header in high-contrast Bloomberg amber (`#ff9900`).
   - Placeholder: `Paste INDMONEY_API_TOKEN (JWT)...`
   - Obfuscated display: `eyJhbGciOiJIUzUxMi... [Show/Hide Toggle]`.
2. **Instant Live Validation**:
   - On paste or clicking **[CONNECT / REFRESH]**, the frontend immediately initiates a handshake to `GET /funds` via `https://api.indstocks.com/funds` (or backend proxy `POST /api/auth/token`).
   - **Handshake Response 200 OK**:
     - Status Badge transitions from `DISCONNECTED` 🔴 to `LIVE CONNECTED` 🟢.
     - Live Sod Balance, Available Margin, and Realized/Unrealized P&L populate the header HUD.
     - Token is cached to browser `localStorage.setItem('indmoney_token', token)` with an expiration countdown timer derived from the JWT payload (`exp` timestamp).
   - **Handshake Response 401/403 (Expired or Invalid Token)**:
     - Badge displays `TOKEN EXPIRED / INVALID` 🔴.
     - The terminal displays a high-visibility amber prompt with instructions to refresh the token via [indstocks.com/app/api-trading/access-tokens](https://www.indstocks.com/app/api-trading/access-tokens).
     - Read-only features automatically fail over to the local candle cache and Yahoo Finance fallback.

### B. Header Account HUD Elements

| Element | Description | Source Endpoint |
| :--- | :--- | :--- |
| **Connection Status** | Live WebSocket & REST handshake beacon (`CONNECTED` / `OFFLINE`) | `GET /funds` / WS Ping |
| **Available Margin** | Live intraday buying power (MIS equity / options margin) | `res.data.detailed_avl_balance.eq_mis` |
| **SOD Balance** | Start of Day balance (capital baseline) | `res.data.sod_balance` |
| **Realized P&L** | Booked daily profit/loss | `res.data.realized_pnl` |
| **Unrealized P&L** | Mark-to-market open position profit/loss | `res.data.unrealized_pnl` |
| **Token Expiry Countdown** | Remaining hours/minutes until 24-hour token revocation | Decoded JWT `exp` field |

---

## 3. Core Functional Modules & Data Engine

### Module 1: Live Market Data, Index Watch & Depth (`GP` / `L2`)
- **Supported Tickers**:
  - Major Indices: **NIFTY 50** (`NIDX_40000001`), **BANKNIFTY** (`NIDX_40000002`), **FINNIFTY**, **MIDCPNIFTY**, **SENSEX** (`40000006`).
  - Equity Universe: Full NSE & BSE equities mapped via `INDSTOCKS_SECURITY_IDS` and `assets/indstocks_equity_master.csv`.
- **Streaming & Candles**:
  - Live tick streaming via INDmoney WebSockets (`wss://api.indstocks.com/ws`).
  - Historical intraday intervals: `1minute`, `5minute`, `15minute`, `60minute`, and `1day`.
  - Intraday anchor: Session open at 09:15 IST with half-open intervals $[ts, ts + interval)$.

### Module 2: Institutional Trade Execution & Order Desk (`BLOTTER`)
Direct API integration with INDmoney order routing per [`assets/indstocks-api-docs.md`](file:///home/ayush/personal/friday/assets/indstocks-api-docs.md):

#### Order Types Supported:
1. **Regular Limit / Market Orders**:
   - `POST https://api.indstocks.com/order`
   - Parameters:
     ```json
     {
       "txn_type": "BUY",
       "exchange": "NSE",
       "segment": "EQUITY",
       "product": "INTRADAY",
       "order_type": "LIMIT",
       "limit_price": 25500.0,
       "validity": "DAY",
       "security_id": "40000001",
       "qty": 50,
       "remarks": "bloomberg-terminal"
     }
     ```
2. **Smart GTT (Good-Till-Triggered) OCO Orders**:
   - Multi-leg entry with stop-loss and target legs executed directly on broker server.
   - `POST https://api.indstocks.com/smart/order`
   - Enables the exact rules from the user's backtested strategies:
     * **15m Opening Range Displacement**: Enter on displacement close, Stop Loss at candle low, Target at 1:2 RR.
     * **PineScript VWAP x EMA Cross**: Enter on crossover, Stop Loss at prior candle extreme, Target at 1:2 RR with 50% partial exit.
3. **Execution Blotter Features**:
   - **Open Orders Window**: Live order status tracking (`OPEN`, `COMPLETE`, `CANCELLED`, `REJECTED`).
   - **Trade Book**: Detailed fill prices, timestamps, and exchange execution IDs.
   - **Position Book**: Open quantities, average prices, live LTP, trailing stops, and single-click **[FLATTEN ALL]** emergency exit button (`Alt + X`).

### Module 3: Derivatives, GEX & Institutional Greeks Suite (`OMON` / `OVOL`)
Driven by `gex.py` and INDmoney Option Chain API (`GET /market/option-chain`):
- **Live Greeks Calculated by Exchange**:
  - **Delta ($\Delta$)**: Directional probability and net hedge ratio.
  - **Gamma ($\Gamma$)**: Curvature of delta; highlights gamma squeezes and dealer hedging acceleration near ATM.
  - **Theta ($\Theta$)**: Daily decay in ₹/lot; isolates high-decay selling opportunities.
  - **Vega ($\nu$)**: Sensitivity to 1% IV shift; flags pre-earnings/RBI policy expansion and post-event IV crush.
- **Dealer Gamma Exposure (GEX) Calculation**:
  $$\text{GEX}_{\text{Net}} = \sum \left( -\text{OI}_{CE} \times \Gamma_{CE} + \text{OI}_{PE} \times \Gamma_{PE} \right) \times \text{Lot Size} \times \text{Spot} \times 0.01 \quad (\text{₹ Crore})$$
- **Gamma Flip Strike**: The pivot price where dealer delta hedging flips from dampening market volatility (positive gamma) to amplifying market volatility (negative gamma).
- **Max Pain & Put-Call Ratio (PCR)**: Expiry magnet strike and volume/OI sentiment ratio.

### Module 4: Integrated Quantitative Strategy Scanners

#### A. 15-Minute Opening Range Displacement Scanner
- Established between **09:15 and 09:30 IST** across the first three 5-minute bars.
- Scans for candles that displace and close outside the range ($Close > OR_{High}$ or $Close < OR_{Low}$).
- Automatically calculates Stop Loss (Displacement Candle Low for Long, High for Short) and 1:2 Risk-Reward Target.
- Validated performance on NIFTY 50: **47.5% win rate**, **+18.29 R profit**, **1.94 profit factor**.

#### B. VWAP x EMA(9) Smart Profit Trail Engine
- Ported from PineScript v6 to Python in [`monte_carlo_pinescript.py`](file:///home/ayush/personal/friday/monte_carlo_pinescript.py).
- Monitors session-anchored VWAP and EMA(9) crossovers.
- Dynamic Profit Trailing Modes:
  * `None (Fixed RR)`: Classical 1:2 bracket exit.
  * `EMA Trail`: Ratchets SL along EMA(9) after 1.0R activation.
  * `ATR Trail`: Ratchets SL along Extreme Price $\pm (2.0 \times \text{ATR}_{14})$.
  * `Candle Low/High`: Trailing stop behind prior candle extremes.
- Partial Booking: 50% booked at 1:2 RR, 50% runner trails for maximum trend capture.

#### C. Daily Support & Minervini VCP Pattern Engine
- Integrated from [`daily_support_scanner.py`](file:///home/ayush/personal/friday/daily_support_scanner.py) and [`vcp_scanner.py`](file:///home/ayush/personal/friday/vcp_scanner.py).
- Multi-timeframe confluence: 4-Hour 9/20 EMA swing regime, Stage 2 Trend Template, and Volatility Contraction Pattern (VCP) volume dry-up.

### Module 5: Institutional Flows & Corporate Intelligence
- **FII / DII Daily Activity**:
  - End-of-day net buy/sell cash flow and index futures long-short ratio from NSE public API (`https://www.nseindia.com/api/fiidiiTradeReact`).
- **Bulk & Block Deals**:
  - Live feed of large institutional block transactions with client name, quantity, and average trade price from `https://www.nseindia.com/api/snapshot-capital-market-largedeal`.
- **Corporate Filings & Earnings Calendar**:
  - Scrapes upcoming board meetings, quarterly result announcements, dividend ex-dates, bonus issues, and AGM/EGM dates from NSE.

### Module 6: Macro Regime & Real-Time Financial Wire
- **Macro Economic Indicators**:
  - RBI Repo Rate, CPI Inflation, GDP Growth, and 10-Year G-Sec Yield (from FRED API & RBI DBIE).
- **Financial Wire Feed**:
  - Filtered RSS stream from Moneycontrol, Economic Times, and LiveMint.
  - Automatically tags headlines with stock tickers and sentiment scores (`BULLISH`, `BEARISH`, `NEUTRAL`).

---

## 4. Complete API & Data Mapping Specification

| Data Component | Provider / Protocol | Endpoint / Source | Refresh Interval |
| :--- | :--- | :--- | :--- |
| **API Authentication & Funds** | INDmoney REST | `GET /funds` | On load / 30s |
| **Order Placement / Modification** | INDmoney REST | `POST /order`, `POST /smart/order` | Sub-second on action |
| **Open Positions & Order Book** | INDmoney REST | `GET /order-book`, `GET /position-book` | 3s / On execution |
| **Historical Candles (Intraday)** | INDmoney REST | `GET /market/historical/{interval}` | On symbol switch |
| **Option Chain & Greeks** | INDmoney REST | `GET /market/option-chain` | 15s - 60s |
| **Market Quotes & L1/L2 Depth** | INDmoney WebSockets | `wss://api.indstocks.com/ws` | Real-time tick stream |
| **FII / DII Cash & F&O Flows** | NSE Public JSON | `https://www.nseindia.com/api/fiidiiTradeReact` | Daily at 18:30 IST |
| **Bulk & Block Institutional Deals**| NSE Public JSON | `https://www.nseindia.com/api/snapshot-capital-market-largedeal` | 5 minutes |
| **Earnings & Corporate Filings** | NSE Public JSON | `https://www.nseindia.com/api/corporate-announcements` | 5 minutes |
| **Indian Macroeconomic Indicators**| FRED API | Series `INDCPIALLMINMEI`, `INDIRLTLT01STM` | Daily |
| **Market Breaking News** | Financial RSS | Moneycontrol, LiveMint, Economic Times | 3 minutes |

---

## 5. Keyboard Navigation & Command-Line Architecture

The terminal implements an authentic Bloomberg-style command parser at the top of the workspace:

```
[ COMMAND INPUT: _______________________________ <GO> ]
```

### Supported Syntax & Mnemonics:
- `<TICKER> GP <GO>`: Open interactive candlestick chart with volume profile and ICT levels.
- `<TICKER> OMON <GO>`: Open live Option Chain with Delta, Gamma, Theta, Vega, and GEX.
- `<TICKER> FA <GO>`: Open Financial Analysis (P&L, Balance Sheet, Ratios).
- `<TICKER> HDS <GO>`: Open Shareholding Pattern (Promoter, FII, DII holdings).
- `<TICKER> DVD <GO>`: Open Corporate Actions (Dividends, Splits, Results).
- `NIFTY 50 <GO>` / `BANKNIFTY <GO>`: Switch terminal focus to major index.
- `FIIDII <GO>`: Display daily institutional cash and derivatives activity.
- `BLOCK <GO>`: Display live bulk and block deals.
- `ORB <GO>`: Launch 15-Minute Opening Range Displacement Scanner.
- `MC <GO>`: Run Monte Carlo simulation for selected asset.
- `BUY <QTY> <TICKER> [LMT <PX>] <GO>`: Pre-fill order execution ticket.
- `FLATTEN <GO>` / `Alt + X`: Emergency close for all open positions.
