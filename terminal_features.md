# Indian Equities & Derivatives Terminal (NSE/BSE) — Architecture & Feature Blueprint

A Bloomberg-inspired financial workstation built exclusively for the **Indian Stock Market (NSE & BSE)**, powered by the **INDmoney (INDstocks) API** for real-time market data and trade execution, combined with **100% free public data sources** for fundamentals, corporate filings, macro indicators, and breaking news.

---

## 1. Core Terminal Pillars & Feature Matrix

| Pillar                                        | Terminal Capabilities                                                                                                                                                                                   | Primary Data Source                                                                                       | Cost                       |
| :-------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | :-------------------------------------------------------------------------------------------------------- | :------------------------- |
| **1. Live Market Data & Depth**               | Tick-by-tick LTP, L1/L2 order book depth, volume, intraday & 10+ year EOD OHLCV charts, index tracking (Nifty, BankNifty, Sensex).                                                                      | **INDmoney (INDstocks) API** (WebSockets + Historical REST)                                               | Free (with broker account) |
| **2. Trade & Order Execution**                | Market, Limit, Stop-Loss, GTT, and OCO orders; margin calculators; live positions; Demat holdings & P&L tracking.                                                                                       | **INDmoney (INDstocks) API** (Requires whitelisted Static IP)                                             | Free                       |
| **3. Derivatives, Greeks & Market Direction** | Live option chains (Indices & Stocks), real-time Greeks (**Delta, Gamma, Theta, Vega**), IV Rank/Percentile, Max Pain, PCR, OI buildup, and automated **Bullish/Bearish/Sideways** directional signals. | **INDmoney Option Chain/Greeks API** + **NSE Option Chain Endpoint** + Black-Scholes Engine (`py_vollib`) | Free                       |
| **4. Fundamental Analytics**                  | 10-year Annual & Quarterly Income Statements (P&L), Balance Sheets, Cash Flow Statements, ROE, ROCE, P/E, EV/EBITDA, Debt-to-Equity.                                                                    | **Yahoo Finance** (`yfinance` / `yahoo-finance2`) + **Screener.in**                                       | Free                       |
| **5. Shareholding & Institutional Flows**     | Quarterly Promoter, FII, DII, and Public shareholding patterns; daily FII/DII net cash/F&O activity; Bulk & Block deals; Insider trading (SAST).                                                        | **NSE & BSE Public JSON Endpoints** + **Screener.in**                                                     | Free                       |
| **6. Corporate Events & Filings**             | Real-time board meeting outcomes, quarterly result PDFs, dividends, stock splits, bonus issues, rights issues, and investor presentations.                                                              | **NSE & BSE Public JSON Endpoints**                                                                       | Free                       |
| **7. Breaking News & AI Summaries**           | Live market-moving headlines, stock-specific news feeds, automated sentiment tagging (`Bullish/Bearish/Neutral`), and earnings summaries.                                                               | **Google News / ET / Moneycontrol / LiveMint RSS** + Free LLM API                                         | Free                       |
| **8. Indian Macro Dashboard**                 | RBI Repo Rate, CPI Inflation, GDP growth, 10-Year G-Sec Bond Yield, India VIX, and Forex Reserves.                                                                                                      | **FRED API** (`stlouisfed.org`) + **RBI DBIE**                                                            | Free                       |
| **9. Command-Line Workspace**                 | Fast keyboard-driven navigation using Bloomberg-style mnemonics (e.g., `RELIANCE FA`, `NIFTY OMON`, `TOP`, `FIIDII`, `ECO`) and multi-panel views.                                                      | **Custom Frontend Engine**                                                                                | Free                       |

---

## 2. Detailed Feature Breakdown by Module

### A. Command-Line Navigation & Workspace (Bloomberg UX)

- **Mnemonic Shortcut Bar:** Instant keyboard navigation without nested menus:
  - `<TICKER> GP` — Interactive Price & Volume Chart (Intraday to 10Y)
  - `<TICKER> FA` — Financial Analysis (10Y P&L, Balance Sheet, Cash Flow, Ratios)
  - `<TICKER> HDS` — Holders & Shareholding Pattern (Promoter, FII, DII, Insider Trades)
  - `<TICKER> DVD` — Corporate Actions (Dividends, Splits, Bonus, Board Meetings)
  - `<TICKER> CN` — Company-Specific News & Exchange Filings
  - `<TICKER> OMON` — Live Option Chain, Full Greeks (Delta, Gamma, Theta, Vega), OI Buildup & Market Direction Engine
  - `<TICKER> OVOL` — Implied Volatility (IV) Skew, IV Percentile & Volatility Surface
  - `TOP` — Top Breaking Indian Market News
  - `FIIDII` — Daily FII/DII Activity & Bulk/Block Deals
  - `EQS` — Equity Screener (Filter NSE/BSE stocks by ROE, P/E, Market Cap, Sales Growth)
  - `ECO` — Indian Macroeconomic Calendar & RBI Indicators
- **Multi-Panel Grid:** Split-screen layout supporting simultaneous watchlist, chart, order book, and live news ticker panels.

---

### B. Institutional Options Analytics, Greeks & Market Direction Engine (`OMON` / `OVOL`)

Built specifically for Nifty, BankNifty, FinNifty, MidcapNifty, and NSE F&O stocks using **INDmoney's live Option Chain & Greeks feed** supplemented by **NSE's Option Chain JSON** and a local Black-Scholes calculator (`py_vollib` / `black-scholes`).

#### 1. Real-Time Option Greeks Suite (Per Strike & Portfolio-Wide)

- **Delta ($\Delta$):** Measures directional exposure and probability of expiring In-The-Money (ITM). Tracks net Call Delta vs. Put Delta flow across strikes.
- **Gamma ($\Gamma$):** Tracks rate of change in Delta; identifies **Gamma Blast / Expiry Squeeze zones** where market makers must aggressively hedge near ATM strikes.
- **Theta ($\Theta$):** Measures daily time decay in ₹ per day; highlights optimal option-selling windows when Theta decay accelerates against stagnant spot prices.
- **Vega ($\nu$):** Measures sensitivity to a $1\%$ change in Implied Volatility (IV). Alerts traders to **IV Crush** risk before/after earnings or RBI policy announcements, and **Vega Expansion** during breakouts.
- **Portfolio Net Greeks:** Aggregates total $\Delta$, $\Gamma$, $\Theta$, and $\nu$ across all open INDmoney positions to show net directional and volatility risk in real time.

#### 2. Volatility & Strike Intelligence

- **Implied Volatility (IV), IV Rank (IVR) & IV Percentile (IVP):** Compares current strike IV against its 52-week range to decide whether to **buy options** (low IVP) or **sell credit spreads/straddles** (high IVP).
- **India VIX Correlation:** Tracks live India VIX (`https://www.nseindia.com/api/allIndices`) alongside Nifty/BankNifty spot to detect fear spikes or complacency.
- **Max Pain & Straddle Pricing:** Calculates exact expiry Max Pain strike and live ATM Straddle premium (expected intraday/weekly move range).
- **Support & Resistance Walls:** Automatically highlights the highest Call OI strike (strongest resistance) and highest Put OI strike (strongest support) with real-time OI unwinding alerts.

#### 3. Automated Market Direction & Sentiment Signal Engine

Combines price action, OI changes, PCR, and Greeks into a unified directional regime indicator (**Strong Bullish**, **Mild Bullish**, **Rangebound / Theta Decay**, **Mild Bearish**, **Strong Bearish**, or **High Volatility Breakout**):

| Signal Metric                 | Bullish Condition                                                                                                                                         | Bearish Condition                                                                                                                                             | Sideways / Neutral Condition                                                  |
| :---------------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------ | :---------------------------------------------------------------------------- |
| **Price + OI Buildup**        | **Long Buildup** (Price $\uparrow$ + Futures/Call OI $\uparrow$) or **Short Covering** (Price $\uparrow$ + Put Writing $\uparrow$ / Call OI $\downarrow$) | **Short Buildup** (Price $\downarrow$ + Futures/Put OI $\uparrow$) or **Long Unwinding** (Price $\downarrow$ + Call Writing $\uparrow$ / Put OI $\downarrow$) | Both ATM Call & Put OI rising heavily (**Short Straddle / Strangle buildup**) |
| **Put-Call Ratio (PCR)**      | PCR rising from oversold ($> 1.15$ to $1.40$) showing heavy Put writing support                                                                           | PCR dropping below $0.75$ showing aggressive Call writing resistance                                                                                          | PCR steady between $0.85$ and $1.10$                                          |
| **Net Delta & Vega Flow**     | Positive Net Delta flow + rising Call IV/Vega                                                                                                             | Negative Net Delta flow + rising Put IV/Vega                                                                                                                  | Net Delta near zero + falling Vega (IV crush)                                 |
| **FII Index F&O Positioning** | FII Long-Short Ratio rising + net Index Futures buying                                                                                                    | FII Long-Short Ratio falling + net Index Futures selling                                                                                                      | Balanced FII hedging with flat cash flows                                     |

---

### C. INDmoney (INDstocks) Core Engine

- **Capabilities Included:**
  - Real-time WebSocket tick streaming across NSE, BSE, NFO, and BFO.
  - Historical candle data (1-min, 5-min, 15-min, 1-hour, Daily) for charting and backtesting.
  - Option chain snapshots, expiry calendars, and pre-computed Option Greeks.
  - Direct order placement, modification, cancellation, GTT orders, strategy builder (multi-leg spreads), and live portfolio sync.
- **Limitations (Handled by External Free Sources):**
  - Does **not** expose stock news, corporate announcements, balance sheets, P&L statements, shareholding patterns, or FII/DII data via the developer API key.

---

### D. Zero-Cost Data Sources & Endpoints Map

#### 1. Master Symbol List (NSE & BSE)

- **NSE Listed Equities CSV:** `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv`
- **NSE SME Equities CSV:** `https://nsearchives.nseindia.com/content/equities/SME_EQUITY_L.csv`

#### 2. Fundamentals (Balance Sheet, P&L, Cash Flow, Ratios)

- **Yahoo Finance (`yfinance` in Python / `yahoo-finance2` in Node.js):**
  - Append `.NS` for NSE tickers (`TCS.NS`) or `.BO` for BSE tickers (`TCS.BO`).
  - Fetches standardized Annual & Quarterly Income Statements, Balance Sheets, Cash Flows, Key Ratios, and Analyst Price Targets.
- **Screener.in (`https://www.screener.in/company/{SYMBOL}/consolidated/`):**
  - HTML table parsing (`BeautifulSoup` / `cheerio`) for 10-year Indian financial ratios (ROCE, ROE, OPM%), quarterly results, and quarterly FII/DII/Promoter shareholding trends.

#### 3. Corporate Filings, Events, FII/DII & Option Chain (NSE/BSE Public APIs)

- **Corporate Announcements & Result PDFs:**
  `https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={SYMBOL}`
- **Dividends, Splits, Bonus & Board Meetings:**
  `https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={SYMBOL}`
- **Shareholding Pattern:**
  `https://www.nseindia.com/api/corporate-share-holdings-master?index=equities&symbol={SYMBOL}`
- **Insider Trading (SAST):**
  `https://www.nseindia.com/api/corporates-pit?index=equities&symbol={SYMBOL}`
- **Daily FII / DII Activity:**
  `https://www.nseindia.com/api/fiidiiTradeReact`
- **Bulk & Block Deals:**
  `https://www.nseindia.com/api/snapshot-capital-market-largedeal`
- **Live Option Chain (Indices & Stocks):**
  - `https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY`
  - `https://www.nseindia.com/api/option-chain-equities?symbol={SYMBOL}`
- **India VIX & All Indices:**
  `https://www.nseindia.com/api/allIndices`

#### 4. Breaking Financial News & AI Summarization

- **Stock-Specific Google News RSS:**
  `https://news.google.com/rss/search?q={COMPANY_NAME}+NSE+stock&hl=en-IN&gl=IN&ceid=IN:en`
- **Market-Wide RSS Feeds:**
  - Moneycontrol: `https://www.moneycontrol.com/rss/latestnews.xml`
  - Economic Times Markets: `https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms`
  - LiveMint Markets: `https://www.livemint.com/rss/markets`
- **AI Layer (Free Tier):** Pass RSS headlines and NSE quarterly filing summaries through a free LLM API (e.g., Gemini Flash / Groq) to auto-tag ticker symbols, score sentiment, and generate bullet-point earnings takeaways.

#### 5. Indian Macroeconomic Data

- **FRED API (Free API Key at `stlouisfed.org`):**
  - India CPI Inflation: `INDCPIALLMINMEI`
  - India GDP: `MKTGDPINA646NWDB`
  - India 10-Year Bond Yield: `INDIRLTLT01STM`
- **RBI DBIE (`dbie.rbi.org.in`):** Free CSV/Excel exports for Repo Rate, CRR/SLR, and Forex Reserves.

---

## 3. Architecture & Anti-Blocking Best Practices

1. **Database Caching Layer (Never Scrape on User Page Load):**
   - Store all fetched data in PostgreSQL / SQLite / Redis and serve your UI exclusively from your own database.
2. **Background Cron Schedule:**
   - **Real-Time Ticks, Option Greeks & Order Book:** Streamed live via **INDmoney WebSockets & Option Greeks API** (zero scraping).
   - **Breaking News RSS & NSE Corporate Announcements:** Poll every **5–10 minutes**.
   - **FII/DII & Bulk Deals:** Fetch once daily after **6:30 PM IST**.
   - **Fundamentals (Balance Sheet, P&L, Ratios):** Fetch once per week or upon new quarterly result announcements.
3. **NSE Session Cookie Handling:**
   - Initialize an HTTP session by hitting `https://www.nseindia.com` first to acquire `nsit` and `nseappid` cookies, include browser `User-Agent` and `Referer` headers, and add a `1–2 second` delay between requests.
   - Run NSE scrapers from a residential/local IP rather than AWS/GCP/DigitalOcean datacenter IPs to avoid Akamai 403 blocks.
4. **Compliance Note:**
   - Keep scraped NSE/BSE feeds strictly for personal trading and internal terminal usage; commercial redistribution of raw exchange data requires official exchange licensing.
