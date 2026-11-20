# FRIDAY Institutional Terminal — Frontend Design System & Build Spec

> Bloomberg-style workstation for the Indian market (NSE/BSE/NFO/BFO), wired to the
> **INDstocks (INDmoney) API** for quotes, depth, option Greeks, positions, funds and
> order execution.
>
> This document is the visual + interaction contract for the terminal. It folds in the
> API-vault/HUD, mnemonic, GEX workbench, order blotter, smart-GTT, scanner, flow and macro
> wire ideas from [`terminal_ui.md`](./terminal_ui.md). The reference implementation lives
> in [`terminal.html`](./terminal.html) and is served at **`http://localhost:9090/`**
> (legacy dashboard remains at `/legacy`).

## 0. Quick Start

```bash
# from the repo root
bash run-stock.sh --no-install

# open the terminal (root now serves the terminal, not the old dashboard)
open http://localhost:9090/
```

1. Paste the INDmoney access token into the gate and press **CONNECT TERMINAL**.
2. The token is validated against INDstocks before the workspace opens.
3. Quotes, depth, candles, option Greeks, funds, positions and orders load immediately.
4. The header `AUTH` cell counts down to JWT expiry; `AVL` and `P&L` mirror the funds API.
5. Use `FA` for fundamentals, `BLOCK` for bulk/block flows and `FLATTEN` for emergency exit.
6. The session starts in **PAPER**. Arm **LIVE** only when you intend to send real orders.
7. The old dashboard stays available at `http://localhost:9090/legacy`.

Backend endpoints used by the page are documented in §7.2. The token is never stored
server-side; it lives in `localStorage` in the browser and travels as `X-IND-Token`.

---

## 1. Design Intent

The terminal should feel like an operator console, not a website.

| Principle | What it means in practice |
| --- | --- |
| **Density over decoration** | 12px base type, 26–30px toolbars, 1px rules, no cards with shadows or 16px radii. Every pixel carries data. |
| **Keyboard first** | A command line is always focused or one keystroke away. Mouse is optional. |
| **Speed is visible** | Live latency readout, update timestamps, flashing ticks, a hard 3s quote poll. |
| **State is unmistakable** | PAPER vs LIVE, LINKED vs OFFLINE, OPEN vs CLOSED — colour + text + LED, never colour alone. |
| **One glance, one decision** | Security header gives price/OHLC/52W; right rail gives the order ticket; the centre is the evidence. |
| **No dead ends** | Every panel has an explicit empty state, loading state and error state with the next action. |
| **Write-once tokens** | All colour/type/spacing comes from CSS custom properties. No hard-coded colours in components. |

### Reference aesthetic

- **Black-glass chassis** — near-black panels, thin cool-grey borders, one amber accent.
- **Amber is the brand and the "active" colour** (`#ffa028`), used sparingly: command prefix,
  active tab, active rail row, focus ring, the FRIDAY wordmark.
- **Cyan is information** (`#3fd6e8`): metadata, timestamps, secondary links.
- **Green/red are only directional truth** (`#25d07c` / `#ff4d5e`), never decoration.
- **Monospace everywhere.** Numeric alignment matters more than typographic variety.
- **Motion is functional**: 120–160ms state transitions, a 46s ticker scroll. Nothing bounces.

---

## 2. Design Tokens

These are the exact tokens used by `terminal.html`. Copy them verbatim into any new view.

```css
:root {
  /* Chassis */
  --bg:        #040506;   /* page / chart background */
  --bg-elev:   #080a0d;
  --panel:     #0b0e11;   /* rail + panel background */
  --panel-2:   #101419;   /* toolbar / header background */
  --panel-3:   #151a21;   /* hover surface */
  --line:      #1b2129;   /* primary rule */
  --line-2:    #2a333d;   /* emphasised rule / input border */

  /* Accent */
  --amber:      #ffa028;
  --amber-dim:  #7a4a12;
  --amber-soft: rgba(255, 160, 40, .12);
  --cyan:       #3fd6e8;
  --cyan-soft:  rgba(63, 214, 232, .10);

  /* Text */
  --text:   #dfe4ea;
  --muted:  #7e8a98;
  --dim:    #4b5560;

  /* Semantics */
  --up:        #25d07c;
  --up-soft:   rgba(37, 208, 124, .12);
  --down:      #ff4d5e;
  --down-soft: rgba(255, 77, 94, .12);
  --warn:      #ffc93c;
  --violet:    #a78bfa;

  /* Type */
  --font: "IBM Plex Mono", "JetBrains Mono", "SF Mono",
          ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  /* Shell */
  --h: 30px; /* top bar height */
}
```

### Type scale

| Role | Size | Weight | Treatment |
| --- | --- | --- | --- |
| Wordmark | 14px | 700 | Amber, tight tracking |
| Symbol title | 19px | 600 | Uppercase, `-0.01em` |
| Last price | 27px | 600 | Uppercase tabular numerals |
| Body / table | 10–12px | 400–500 | Tabular numerals |
| Panel title | 9px | 500 | Uppercase, `letter-spacing: .2em`, `--muted` |
| Micro label | 8px | 400 | Uppercase, `letter-spacing: .12–.16em`, `--dim` |
| Boot headline | 19px | 600 | Sentence case |

**Rules**

- Always `font-variant-numeric: tabular-nums` on the body.
- Prices are right-aligned; symbols are left-aligned; percentages are right-aligned and
  always signed (`+1.24%`, `-0.38%`). Never show an unsigned change.
- Use `—` (em dash), not `–` or `N/A`, for missing data.
- Currency is prefixed `₹` and uses Indian digit grouping (`12,34,567.80`).

### Spacing & sizing

| Token | Value | Use |
| --- | --- | --- |
| Rail width | `236px` | Watchlist / positions / orders |
| Right rail | `312px` | Ticket + funds + positions |
| Top bar | `30px` | Brand, command line, clock, mode |
| Ticker tape | `24px` | Indices + watchlist scroll |
| Status bar | `22px` | Session + shortcut hints |
| Panel head | `26px` | Title + actions |
| Control height | `23–26px` | Buttons, selects, inputs |
| Table row | `22–26px` | Dense data |
| Border radius | `0` | No rounded panels. Only status LEDs are circular. |

Responsive cuts:

- `< 1180px`: rail `200px`, right rail `286px`, hide the OHLC stat strip.
- `< 900px`: single column stack; rails become scrollable shelves; boot screen becomes one column.
  The terminal is desktop-first; mobile is a degraded read-only layout.

---

## 3. Shell Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ FRIDAY TERM │ > command line …                        │ ●LINK 42ms │ OPEN │  ⏱  │ PAPER/LIVE │
├──────────────────────────────────────────────────────────────────────────────┤
│ NIFTY 24,312.40 ▲0.42% │ BANKNIFTY … │ RELIANCE …   ← continuous ticker tape  │
├───────────────┬──────────────────────────────────────────────┬───────────────┤
│ MONITOR       │ RELIANCE  NSE   ●                            │ ORDER TICKET  │
│ WATCH POS ORD │ 2,945.60   +18.35  +0.63%                    │ BUY │ SELL    │
│ ┌───────────┐ │ O 2,930  H 2,958  L 2,921  V 8.4M  52W …    │ qty  price    │
│ │ RELIANCE  │ ├──────────────────────────────────────────────┤ type product  │
│ │ 2,945.60  │ │ GP  OMON  TOP  POSITIONS  ORDERS             │ value margin  │
│ │ +0.63% ▁▂▃│ ├──────────────────────────────────────────────┤ [ PLACE ]     │
│ ├───────────┤ │                                              ├───────────────┤
│ │ TCS       │ │            CANDLE CHART + VOLUME             │ FUNDS         │
│ │ …         │ │                                              │ avail/util    │
│ ├───────────┤ ├──────────────────────┬───────────────────────┤───────────────┤
│ │ + add     │ │ DEPTH L5             │ HEADLINES             │ POSITIONS     │
│ └───────────┘ │ bid qty │ bid │ ask  │ source / title        │ …             │
│               │ …       │     │      │ …                     │               │
├───────────────┴──────────────────────┴───────────────────────┴───────────────┤
│ ●PAPER  SESSION T-20261120  WATCH RELIANCE  UPDATED 14:32:08  F3 GP F4 OMON … │
└──────────────────────────────────────────────────────────────────────────────┘
```

CSS skeleton:

```css
#app {
  height: 100vh;
  display: grid;
  grid-template-rows: 30px 24px 1fr 22px;
}
#workspace {
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr) 312px;
  min-height: 0;
}
#center { display: grid; grid-template-rows: auto 1fr; min-height: 0; }
#view-GP.active { display: grid; grid-template-rows: 1fr 150px; }
```

**Non-negotiable:** `min-height: 0` and `min-width: 0` on every grid/flex child that scrolls.
Without them the chart grows the page instead of filling the viewport.

---

## 4. Startup — The API-Key Gate

The first screen is a full-viewport gate, not a modal on top of the dashboard. The user
cannot see stale/empty market data before connecting.

### Flow

1. **Read saved token** from `localStorage.friday_term_token`.
2. If present, silently `GET /api/terminal/health` with `X-IND-Token`.
3. On success → enter terminal; on failure → show gate with "Saved token expired".
4. **Paste** → `navigator.clipboard.readText()`; fall back to manual Ctrl+V.
5. **Connect** → validate → decode JWT `exp` for the countdown → persist → enter.
6. **Read-only mode** → enter without a token; public news/market wire still loads;
   quote panels show `TOKEN REQUIRED`.

### Health contract

```
GET /api/terminal/health
Header: X-IND-Token: <access token>

200 { ok: true, funds: {...}, trading: true }
200 { ok: true, funds: {}, trading: false, warning: "Market data OK; funds unavailable" }
401 { ok: false, error: "INDmoney token expired or revoked — paste a fresh access token." }
```

The backend falls back to a one-symbol LTP ping when `/funds` is blocked, so a
market-data-only token can still run the terminal in read-only mode.

### Gate copy

- Kicker: `STEP 01 / SECURE LINK`
- Headline: **Connect your INDmoney account**
- Body: token is stored only in this browser and forwarded through the local dashboard
  server; never written to disk by the terminal.
- Buttons: `CONNECT TERMINAL` (amber), `READ-ONLY MODE` (outline).
- Footnote: trading stays in **PAPER** until the operator arms **LIVE**.

**Never** show the token in full by default. `type="password"` + a `SHOW` toggle.
**Never** log it, put it in a URL, or render it in the DOM.

### API vault & header HUD

The gate is the only place the raw token exists in the UI. After connection it lives in
`localStorage.friday_term_token` and is sent as `X-IND-Token` on every `/api/terminal/*`
request. Only the decoded expiry is surfaced in the top bar — never the JWT itself.

| HUD cell | Value | Refresh |
| --- | --- | --- |
| `AVL` | Compact available balance (`₹4.52L`) from `/funds`; `—` in read-only | On connect, funds load, after orders |
| `P&L` | Realised + unrealised, signed and semantically coloured | Same as `AVL` |
| `AUTH` | JWT countdown (`5h42m`, `38m`), `DATA` for market-data-only tokens, `RO`, `EXPIRED`, or `OFFLINE` | 30s |

Colour rule: `up` above 60 minutes, neutral 15–60 minutes, `down` below 15 minutes or
expired. The countdown title attribute carries the local IST expiry timestamp. If the JWT
has no `exp`, show `VALID` (or `DATA` when `trading: false`) and keep the terminal usable.

---

## 5. Command Line & Keyboard System

Bloomberg's speed comes from mnemonics. The command line is the primary navigation.
A trailing `<GO>` is optional decoration: the parser strips it case-insensitively so
`RELIANCE GP` and `RELIANCE GP <GO>` behave identically.

### Grammar

| Input | Result |
| --- | --- |
| `RELIANCE` | Load symbol into the chart |
| `NIFTY 50 <GO>` | Alias for `NIFTY` |
| `RELIANCE GP <GO>` | Chart view for RELIANCE |
| `NIFTY OMON <GO>` | Option chain for NIFTY |
| `RELIANCE FA <GO>` | Fundamentals snapshot for RELIANCE |
| `BLOCK <GO>` | NSE bulk & block deal flows |
| `TOP <GO>` | Market headlines |
| `POS <GO>` | Positions rail + table |
| `ORD <GO>` | Order book rail + table |
| `BUY 10 RELIANCE <GO>` | Pre-fill ticket: BUY, 10 qty, RELIANCE |
| `BUY RELIANCE 10 LMT 2945 <GO>` | Pre-fill ticket with a limit price |
| `SELL 25 INFY <GO>` | Pre-fill ticket: SELL, 25 qty, INFY |
| `FLATTEN <GO>` / `FLATTEN ALL <GO>` | Confirm and market-close every open position |
| `SYNC <GO>` | Refresh quotes, candles, depth, funds, positions, orders |
| `HELP` | Shortcut reference |

`BUY`/`SELL` accept both `SIDE QTY SYMBOL` and `SIDE SYMBOL QTY`. Neither form transmits
an order — both only pre-fill the ticket, which still requires the order confirmation.

### Palette

- `Ctrl+K` or `/` opens the fuzzy palette.
- Shows at most 10 results: symbol mnemonics, commands, and `OPEN <SYMBOL>` fallback.
- `↑/↓` move, `Enter` runs, `Esc` closes.
- The palette and command line share one parser — never two divergent command dialects.

### Global keys

| Key | Action |
| --- | --- |
| `Ctrl+K` / `/` | Command palette |
| `F1` | Help |
| `F3` | Chart (`GP`) |
| `F4` | Option chain (`OMON`) |
| `F5` | Headlines (`TOP`) |
| `F6` | Positions |
| `F7` | Orders |
| `F8` | Sync all |
| `F9` | Fundamentals (`FA`) |
| `F10` | Bulk & block flows (`BLOCK`) |
| `Alt+X` | Flatten all (works even while an input is focused) |
| `Esc` | Close overlay / blur input |
| `Enter` in ticket | Submit after confirmation |

Never hijack keys while an `<input>`, `<select>` or `<textarea>` has focus (except
`Escape`), or typing a ticker will trigger view changes.

---

## 6. Component Specs

### 6.1 Top bar

Left → right: wordmark, command line, link LED, latency, market pill, IST clock,
`AVL`, `P&L`, `AUTH`, PAPER/LIVE switch, `F1 HELP`.

- **Account HUD**: three compact `label + value` cells after the clock. Values are
  right-aligned, monospace and never wider than 96px. See *API vault & header HUD*.
- **Link LED**: green = linked, red = offline, amber = degraded. Pair with text
  (`LINKED` / `OFFLINE`) — never rely on colour alone.
- **Latency**: last round-trip in ms (`42ms`), updated on every `api()` call. Cap the
  display at `999ms` with `>1s` styling if exceeded.
- **Market pill**: computed in IST, not browser local time.
  - `OPEN` 09:15–15:30 Mon–Fri → green border
  - `PRE-OPEN` 09:00–09:15 → amber
  - `POST` 15:30–16:00 → amber
  - `CLOSED` / `WEEKEND` → dim
- **Mode switch**: PAPER amber, LIVE red. Live requires a confirmation dialog every
  session. Persist the choice, but never auto-arm live on page load without the dialog
  when the saved state changes.

```css
.mode-switch { display:flex; border:1px solid var(--line-2); height:20px; }
.mode-switch button.active { background:var(--amber-soft); color:var(--amber); }
.mode-switch button.live.active { background:var(--down-soft); color:var(--down); }
```

### 6.2 Ticker tape

- Height 24px, continuous leftward scroll, 46s loop, pause on hover.
- Duplicate the item list exactly once so `translateX(-50%)` loops seamlessly.
- Item: `SYMBOL  price  ▲0.42%  |`
- Build from the first 16 watchlist names; indices first.
- Colour only the change, never the symbol or price.

### 6.3 Watchlist rail

- Tabs: `WATCH · POS · ORD`.
- Add field at the top; `Enter` or `+` adds, de-dupes, persists to localStorage.
- Row grid: symbol (left) / LTP (right) / change + 44×12 sparkline (second line).
- Active row: `background: var(--amber-soft); box-shadow: inset 2px 0 0 var(--amber)`.
- Remove `×` appears only on hover, top-right; click must `stopPropagation`.
- Keep a rolling 40-tick price history per symbol for the sparkline.
- Footer: `N symbols` and `HH:MM:SS` last refresh.

### 6.4 Security header

- Symbol + exchange badge + connection LED; company name below.
- Last price 27px; change and change % together, signed.
- Stat strip: Open, High, Low, Prev, Volume (compacted `8.4M`), 52W High, 52W Low.
- Action row: view tabs left, `BUY` / `SELL` quick buttons, `REFRESH` right.
- `BUY`/`SELL` quick buttons only pre-fill the ticket and focus quantity — they must not
  submit anything.

```css
.stat label { font-size:8px; letter-spacing:.14em; color:var(--dim); text-transform:uppercase; }
.stat b     { font-size:10px; font-weight:500; }
.sec-price .last { font-size:27px; font-weight:600; letter-spacing:-.02em; }
```

### 6.5 Chart (`GP`)

- Canvas 2D, device-pixel-ratio aware (`canvas.width = clientWidth * dpr`).
- Layout: price pane on top, volume pane at the bottom (16% of height, min 24px).
- Grid: 4 horizontal price levels, ~6 vertical time ticks. Labels `8px` `--dim`.
- Candles: green `#25d07c` / red `#ff4d5e`; body width `min(9px, step*0.66)`.
- Last price: dashed horizontal line + right-edge price tag on a filled background.
- Crosshair hover updates the legend with `O H L C V` for the hovered bar.
- Timeframes: `5M 15M 1H 1D 1W`. The API caps ranges per interval:
  - minute intervals: 7 days (hourly: 15 days)
  - `1day` / `1week` / `1month`: 1 year per call
- Loading/error states are centred uppercase micro-copy, never a blank canvas.

```css
.chart-tools button { background:rgba(6,8,9,.85); border:1px solid var(--line); }
.chart-tools button.active { color:var(--amber); border-color:var(--amber-dim); }
```

### 6.6 Depth ladder (`L5`)

- Two paired columns: bid qty / bid price / ask price / ask qty.
- Background bars grow from the outer edges (`bid` from right, `ask` from left) at 16%
  opacity. Never colour the numbers themselves beyond green/red.
- Header row `8px` uppercase dim.
- If depth is unavailable, show `Depth unavailable.` — do not collapse the panel.

### 6.7 Market Intelligence & Top News (`TOP`)

The institutional `TOP` view provides a five-section market intelligence and future events calendar suite:
1. **📰 Breaking News & Wire (`#top-sec-news`)**:
   - Multi-source RSS aggregation from Economic Times, LiveMint, Business Standard, and Moneycontrol.
   - Provider subtabs (`ALL WIRE`, `ET`, `LIVEMINT`, `BS`, `MC`) and live ticker/topic search.
   - Automatic entity tagging to NSE stock symbols with clickable badges that immediately pivot to `GP` chart.
   - External source link (↗) opens the full article in a new tab with `rel="noopener"`.
2. **⚡ Corporate Actions & Upcoming Dividends (`#top-sec-actions`)**:
   - Exchange-wide dividends, stock splits, bonus issues, and rights offerings from `/api/corporates-corporateActions?index=equities`.
   - **Future Date Prioritization:** Automatically parses ex-dates and record dates, computes countdowns (`TODAY`, `TOMORROW`, `IN X DAYS`), and sorts upcoming future events at the very top of the table.
   - Filter pills: `ALL ACTIONS`, `UPCOMING ONLY 🔥 (count)`, `DIVIDENDS 💰`, `STOCK SPLITS ✂️`, `BONUS ISSUES 🎁`, `RIGHTS & AGMS`.
   - Financial data table with Countdown Badge, Symbol, Company, Action Type, Calculated Benefit/Details (e.g. `₹24.00/sh`, `Ratio 10:1`), Purpose, Ex-Date (accented in green for upcoming), Record Date, and a 1-click `TRADE` action button that selects the stock and pre-fills the order ticket.
3. **📅 Upcoming Events & Board Meetings Calendar (`#top-sec-calendar`)**:
   - Live exchange forward-looking event pipeline aggregating `/api/corporate-board-meetings` and `/api/event-calendar` across 0–60 days ahead.
   - Captures future board meeting dates, quarterly financial results discussions, interim/final dividend agendas, and fund-raising intimations.
   - Filter pills: `ALL UPCOMING`, `FINANCIAL RESULTS 📊`, `DIVIDEND AGENDAS 💰`, `FUND RAISING 📈`, `THIS WEEK ⚡`, `NEXT WEEK 🗓️`.
   - Direct link to official prior intimation regulatory notice PDFs on `nsearchives.nseindia.in`.
4. **📄 Exchange Filings & Results (`#top-sec-filings`)**:
   - Live corporate board filings and quarterly results directly from official NSE JSON endpoints (`/api/corporate-announcements?index=equities`).
   - **Pinned Nearest Earnings Banner (`#filings-earnings-banner`):** High-visibility pinned alert ticker at the very top of the filings section showing immediate upcoming results dates (e.g. `BCSSL (23-Nov · IN 2D)`, `HDBFS (23-Nov)`), with 1-click ticker jump and a `VIEW ALL EARNINGS →` shortcut.
   - Category filter pills: `ALL FILINGS`, `RESULTS & EARNINGS`, `BOARD MEETINGS`, `ORDER WINS & CONTRACTS`, `QIP / ALLOTMENTS`, `DIVIDENDS`.
   - Card layout with stock badge (1-click chart switch), category tag, filing timestamp, official description, executive text excerpt, AI voice summary, and a direct link to the official exchange PDF document (`nsearchives.nseindia.in`).
5. **🚨 Nearest Earnings Alerts (`#top-sec-earnings`)**:
   - Dedicated forward-looking earnings release hub aggregating official NSE SEBI LODR Regulation 29 prior intimations and institutional consensus reporting calendars.
   - **KPI Strip:** Real-time metrics for `UPCOMING RELEASES`, `TODAY / TOMORROW`, `THIS WEEK (≤ 7 DAYS)`, and `DIVIDEND PROPOSALS`.
   - Filter pills: `ALL EARNINGS`, `TODAY / TOMORROW ⚡`, `THIS WEEK (≤ 7D) 🔥`, `WITH DIVIDEND 💰`.
   - Financial results table with Countdown Badge (`⚡ TODAY`, `🔔 TOMORROW`, `IN X DAYS`), Symbol tag, Company Name, Release/Board Date, Period Ended (e.g. `September 2026`), Agenda & Highlights (with prominent `DIVIDEND PROPOSAL 💰` badge when dividend is considered), official SEBI LODR notice PDF link, and 1-click `TRADE` button.

In the individual stock feed panel (`#feed-panel` below `GP` chart):
- **🚨 Stock-Specific Nearest Earnings Alert Box:** Pinned at the top of the feed whenever an upcoming results date is tracked for the active stock (e.g., `BCSSL releasing financial results (September 2026) IN 2 DAYS` with prior intimation PDF, or `INDUSINDBK · Consensus EPS Est: ₹13.69`).
- **`UPCOMING 📅` Tab:** Displays upcoming board meetings (with purpose, date, countdown `IN X DAYS`, intimation attachment) AND upcoming dividend ex-dates/split dates specifically for the active ticker.
- **`ACTIONS` Tab:** Automatically sorts upcoming corporate actions at the top with `🔔 IN X DAYS` status pill.

### 6.8 Option chain (`OMON`)

- Metric strip: Spot, Expiry, Net GEX (₹ Cr), Max Pain, Gamma Flip, PCR OI, Avg IV, Control.
- Toolbar: index select (`NIFTY` / `SENSEX`), expiry select, `LOAD CHAIN`, refresh, status.
- 13-column table: Calls (LTP, OI, Prev OI, ΔOI, IV, Delta) · Strike · Puts (Delta, IV, ΔOI,
  Prev OI, OI, LTP).
- ATM row: amber-tinted background, amber bold strike.
- OI mini-bars: 2–34px wide, green for calls, red for puts, 50% opacity.
- Auto-refresh every 60s **only while the view is active**; the backend already caches 60s.
- If the token is expired, show the actionable token message in the status area and keep
  the last good chain on screen (stale badge) rather than clearing it.

### 6.8a Fundamentals (`FA`)

- Loads `/api/fundamentals?ticker=<SYMBOL>&range=1y|3y|5y` on view entry, symbol change and
  range change. Backend merges **Screener.in** (Indian-format standalone/consolidated
  statements, ratios, shareholding) with **Yahoo Finance** (fallback statements + price
  history); both are cached for 10 minutes. The INDmoney token is never required for `FA`.
- Header KPI strip: company, sector, industry and the first 12 Screener top ratios
  (market cap, price, P/E, book value, dividend yield, ROCE, ROE, face value, etc.).
- Dense sub-tabs inside the view:
  - `YOY + PRICE` — last six annual periods as REV/PAT cards with YoY growth, a canvas
    price-history chart with 1Y/3Y/5Y selector, plus the full annual P&L table.
  - `QUARTERLY` — last six quarters with computed 4-quarter YoY sales/PAT growth and the
    quarterly results table.
  - `P&L` — 10–13 year annual profit & loss table plus compounded growth cards.
  - `BALANCE SHEET` — annual equity, reserves, borrowings, assets and liabilities.
  - `CASH FLOW` — operating/investing/financing cash flows.
  - `RATIOS` — OPM, ROE, ROCE, debtor/inventory days, leverage and valuation ratios.
  - `SHAREHOLDING` — promoter/FII/DIO/MF/retail quarterly and annual patterns.
  - `CAGR` — compounded sales/profit/price/ROE growth cards and annual P&L.
- Tables use the shared sticky-header `table.data`; values with an explicit `+`/`-` sign are
  green/red. Empty tables render a tab-specific empty state, never a blank panel.
- Source footer links back to the upstream page and shows `DEGRADED` plus the underlying
  error text if only one feed responded. Timestamp: `SCREENER.IN+YAHOO FINANCE · HH:MM:SS`.

### 6.8b Block flows (`BLOCK`)

- Loads `/api/large-deals`; reads `GROUPED_BULK_DEALS_DATA` and
  `GROUPED_BLOCK_DEALS_DATA`, merges and sorts by total value, caps at 40 rows.
- Columns: Symbol, Type, Buy Qty, Sell Qty, Net Qty, Buy Val, Sell Val, Net Val, Clients.
- Filter pills: `ALL DEALS`, `BULK ONLY`, `BLOCK ONLY`, `BUY ONLY` (buy_qty > 0 and
  sell_qty = 0), `SELL ONLY` (sell_qty > 0 and buy_qty = 0) and `NET BUYERS`. These are
  grouped-stock filters, so `BUY ONLY` / `SELL ONLY` mean the stock had deals only on that
  side during the session.
- Net qty/value are semantically coloured; client count appears on hover with up to four
  client names. Footer: `NSE · <as_on_date> · HH:MM:SS`.
- Loading / empty / error states are mandatory; stale NSE snapshots are labelled by date.

### 6.9 Positions / Orders

- Full views use a sticky-header table; micro rows in the right rail show symbol, qty,
  product and P&L only.
- Order side is a pill: `BUY` green outline, `SELL` red outline.
- Always show order ID, status, qty, price. Status text is uppercase and never truncated.
- Empty states: "No open positions." / "No orders today." — not a zeroed table.
- `[FLATTEN ALL]` sits in the positions header and is also bound to `FLATTEN <GO>` /
  `Alt+X`. It refreshes positions, ignores zero rows, previews up to six closing orders,
  then requires a mode-aware confirm (red **live** vs amber **paper**). PAPER sends
  `dry_run: true`; LIVE sends real `MARKET` closes via `POST /api/terminal/flatten`.
  Success toast reports the order count; partial failures show the first broker error.

### 6.10 Order ticket (right rail)

```
┌ ORDER TICKET ───────────── PAPER ┐
│ [ BUY ] [ SELL ]                │
│ Symbol  [ RELIANCE           ]  │
│ Qty [−][ 1 ][+]  Price [2945.60] │
│ Type [LIMIT ▾]   Product [MIS ▾]│
│ Est. value ₹2,945  Margin ₹589   │
│ [ PLACE BUY · PAPER ]           │
│ LIVE ARMED — real money.        │
└─────────────────────────────────┘
```

- `BUY`/`SELL` segmented control: 8px vertical padding, active fill green/red, black text.
- Quantity stepper: `−` / numeric / `+`, min 1, integer only.
- Price pre-fills LTP on symbol change unless the price field is focused.
- `MARKET` disables the price input visually but keeps the last value for the estimate.
- Margin estimate: `INTRADAY = 20%` of notional, `CNC = 100%`. Label it **estimate**.
- Submit always opens a confirmation dialog summarising side, qty, symbol, type, product,
  price, value and mode.
- PAPER submit sends `dry_run: true`; the backend returns `PAPER-<epoch>` and
  `SIMULATED`. LIVE submit hits `POST /order`.
- When `/health` reports `trading: false` (market-data-only token), or no token is linked,
  the place button, LIVE arming and `FLATTEN` are disabled with an explanatory tooltip.
- Disable the place button while a request is in flight; re-enable in `finally`.

### 6.11 Funds / positions micro-panels

- 2×2 grid: Available, Utilised, Realised, Unrealised. Values right-aligned in `11px`.
- Realised/unrealised get semantic colour; Available/Utilised stay neutral.
- Micro position row: symbol + `QTY n · PRODUCT` on the second line, P&L right-aligned.

### 6.12 Status bar

Left: mode LED + `PAPER`/`LIVE`, session id (`T-YYYYMMDD`), active symbol, last update.
Right: keyboard hints (`F3 GP  F4 OMON  F5 TOP  F6 POS  F7 ORD  F8 SYNC`).
Keep it 22px and never wrap.

### 6.13 Toasts

- Bottom-right, 240–380px, 1px border, 2px semantic left border.
- 4.2s auto-dismiss. Kinds: default (amber), `ok` (green), `err` (red).
- Header is `8px` uppercase dim; message is `10px` text.
- Use for order accepted/rejected and feed failures. Never use `alert()`.

### 6.14 Confirm dialog

- Reuses the overlay scrim (`rgba(2,3,4,.72)` + 3px blur).
- Danger confirm button is red (`Arm live`, `SEND LIVE ORDER`); normal is amber.
- Body must repeat the full order parameters — no "Are you sure?" without numbers.

---

## 7. Data Layer

### 7.1 Token transport

```
Browser  ── X-IND-Token header ──▶  local dashboard server  ── Authorization ──▶ api.indstocks.com
```

The browser never calls `api.indstocks.com` directly. Reasons:

1. No CORS dependency.
2. One place to normalise errors and redact tokens from logs.
3. One place to enforce paper/live and order validation.
4. The instrument master stays server-side (23k rows, 3.2 MB CSV).

Token precedence: `X-IND-Token` header → `api_key` query (legacy routes only).
The server must never write the token to disk or include it in error payloads.

### 7.2 Endpoint map (implemented in `stock_dashboard.py`)

| Method | Path | Upstream | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/terminal/health` | `/funds` → `/market/quotes/ltp` fallback | Validate token |
| `GET` | `/api/terminal/search?q=&limit=` | local master | Symbol autocomplete |
| `GET` | `/api/terminal/watch-universe` | local CSVs | Full watchlist symbol universe |
| `GET` | `/api/terminal/quotes?symbols=A,B` | `/market/quotes/full` | Batch quotes (max 1000) |
| `GET` | `/api/terminal/depth?symbol=` | `/market/quotes/mkt` | 5-level book |
| `GET` | `/api/terminal/candles?symbol=&interval=&days=` | `/market/historical/{interval}` | OHLCV |
| `GET` | `/api/terminal/funds` | `/funds` | Balances |
| `GET` | `/api/terminal/positions` | 4 × `/portfolio/positions` | Aggregated open positions |
| `GET` | `/api/terminal/holdings` | `/portfolio/holdings` | Demat holdings |
| `GET` | `/api/terminal/orders` | `/order-book` | Today's orders |
| `GET` | `/api/terminal/trades` | `/trade-book` | Executed trades |
| `GET` | `/api/terminal/option-chain?index=&expiry=&strike_count=` | `/market/option-chain` | Greeks + GEX |
| `GET` | `/api/fundamentals?ticker=&range=` | Screener.in + Yahoo | Statements, ratios, shareholding, YoY and price history (`FA`) |
| `GET` | `/api/quote?ticker=` | Yahoo chart API → yfinance | Security header / chart fallback |
| `GET` | `/api/large-deals` | NSE | Bulk & block flows (`BLOCK`) |
| `POST` | `/api/terminal/order` | `/order` | Place / simulate order |
| `POST` | `/api/terminal/flatten` | `/order` × n | Emergency close-all (dry-run default) |
| `POST` | `/api/terminal/order/cancel` | `/order/cancel` | Cancel order |

`/api/terminal/positions` fans out to `equity/intraday`, `equity/cnc`,
`derivative/intraday` and `derivative/margin`, then deduplicates by security + product +
position type. The returned rows carry normalised `symbol`, `net_qty`, `avg_price`, `ltp`,
`pnl`, `security_id`, `exchange`, `segment` and `product`, which the flatten handler uses
to build opposite-side market orders. Errors from individual segments are returned in
`errors` without hiding successful segments.

Quote reads use Yahoo's public `/v8/finance/chart` endpoint exclusively because `yfinance`
quote-summary calls now fail with `Invalid Crumb` and only add noisy traces. `query1` is
tried first, then `query2` on HTTP 429. Successful quotes are cached for 12s; 404s are
cached for 5 minutes and 429/5xx for 60s, so delisted/renamed symbols and rate limits do
not spam the log. Renamed symbols must be updated in the watchlist (for example
`ZOMATO` → `ETERNAL`, `TATAMOTORS` → `TMPV` / `TMCV` after the demerger).

### 7.3 Normalised quote contract

```json
{
  "quotes": {
    "RELIANCE": {
      "symbol": "RELIANCE", "name": "Reliance Industries Ltd",
      "scrip": "NSE_2885", "exchange": "NSE",
      "ltp": 2945.6, "change": 18.35, "change_pct": 0.63,
      "open": 2930.0, "high": 2958.0, "low": 2921.0, "prev_close": 2927.25,
      "volume": 8431221, "w52_high": 3217.9, "w52_low": 2180.0,
      "upper_circuit": 3220.0, "lower_circuit": 2634.5,
      "depth": { "aggregate": {}, "depth": [] },
      "ts": 1732080728.12
    }
  },
  "missing": ["NOSUCH"],
  "ts": 1732080728.12
}
```

### 7.4 Order contract

Request:

```json
{
  "symbol": "RELIANCE",
  "txn_type": "BUY",
  "qty": 10,
  "order_type": "LIMIT",
  "limit_price": 2945.6,
  "product": "INTRADAY",
  "exchange": "NSE",
  "segment": "EQUITY",
  "validity": "DAY",
  "dry_run": true
}
```

Backend fills `security_id`, `algo_id: "99999"` and `remarks: "FRIDAY-TERMINAL"`.
`dry_run` returns `order_id: "PAPER-<epoch>"` and `order_status: "SIMULATED"` without
calling the exchange.

Response:

```json
{ "status": "success", "data": { "order_id": "EQ-93586788", "order_status": "INITIATED" },
  "request": { "...": "echoed for audit" } }
```

### 7.4a Flatten contract

```
POST /api/terminal/flatten
{ "dry_run": true }   // default true; frontend sends false only in armed LIVE mode
```

```json
{
  "status": "partial",
  "dry_run": true,
  "orders": [
    { "status": "simulated", "symbol": "RELIANCE", "qty": 10, "side": "SELL",
      "request": { "txn_type": "SELL", "order_type": "MARKET", "remarks": "FRIDAY-FLATTEN", "...": "..." } }
  ],
  "errors": ["derivative/intraday: INDmoney token expired or revoked"]
}
```

`dry_run` is the default so a stray API call can never flatten a real account. The
frontend still adds its own modal confirm; the backend never derives live intent from a
saved preference.

### 7.5 Polling & caching cadence

| Stream | Cadence | Notes |
| --- | --- | --- |
| Watchlist + active quotes | 3s | Batch all symbols in one call (API allows up to 1000) |
| Depth | On symbol load + manual refresh | 5-level book is heavier |
| Candles | On symbol / timeframe change | Never poll historical data |
| Option chain | 60s while `OMON` is visible | Backend caches 60s |
| Funds / positions / orders | On load, after an order, manual refresh | Never on a 3s timer |
| Headlines | On symbol change / `TOP` view | RSS is slow; cache server-side |
| Fundamentals (`FA`) | On view entry / symbol change / range change / `SYNC` | 10-minute server cache; no polling |
| Block flows (`BLOCK`) | On view entry / `SYNC` | NSE daily snapshot; no polling |
| AUTH countdown | 30s from decoded JWT `exp` | Local only; no network call |
| Clock | 1s, IST only | Never use browser local time |

### 7.6 Upgrade path: WebSockets

Polling is the v1 transport. Move to the INDstocks price feed when quote freshness
becomes the bottleneck:

```
wss://ws-prices.indstocks.com/api/v1/ws/prices
Authorization: <token>
{ "action": "subscribe", "mode": "quote", "instruments": ["NSE:2885", "NIDX:40000001"] }
```

Design constraints for the upgrade:

- Keep the same normalised quote shape so the UI does not change.
- Backend maintains one socket, fans out to browser clients via SSE/WebSocket.
- Reconnect with exponential backoff (1s → 30s), and fall back to 3s REST polling while
  disconnected.
- Order updates: `wss://ws-order-updates.indstocks.com/api/v1/ws/trades`, subscription
  `{ "action": "subscribe", "mode": "order_update" }`; append to the order book live.
- Never put the token in the browser WebSocket URL.

---

## 8. Visual Rules Cheat-Sheet

| Do | Don't |
| --- | --- |
| Use 1px rules to separate data | Use drop shadows or rounded cards |
| Use amber only for active/brand | Use amber for prices or P&L |
| Show green/red only for direction | Colour whole rows green/red |
| Right-align numbers, left-align text | Centre numeric columns (except strike) |
| `—` for missing values | `0`, `null`, `N/A`, or blank |
| Uppercase 8–10px labels with tracking | Sentence-case micro labels |
| Pair every colour with text/icon | Rely on colour alone |
| Keep rows 22–26px | Use 40px "comfortable" rows |
| Animate 120–160ms opacity/transform | Animate layout properties |
| Reserve space for loading states | Let panels jump when data arrives |

### Semantic colour usage

```css
.up   { color: var(--up); }
.down { color: var(--down); }
.flat { color: var(--muted); }
.dim  { color: var(--dim); }
.amber{ color: var(--amber); }
.cyan { color: var(--cyan); }
```

### Focus ring

Inputs and selects get `border-color: var(--amber)` on `:focus`. Never remove the focus
indicator without replacing it — keyboard operation is the primary path.

### Empty / error / stale states

| State | Presentation |
| --- | --- |
| Loading | Centred `LOADING…` in 10px uppercase `--dim` |
| Empty | One actionable sentence + the next command (`Add a symbol above`) |
| Token error | Amber/red banner with **"paste a fresh access token"** |
| Network error | Toast + keep last data, timestamp marked `STALE` |
| Market closed | `CLOSED` pill; prices remain the last session's values |

---

## 9. Performance Budget

| Metric | Budget |
| --- | --- |
| First paint of the gate | < 150ms (single HTML file, no external assets) |
| Time to interactive after token | < 600ms |
| Quote batch round-trip (local server → INDstocks → browser) | < 500ms typical |
| Chart redraw (500 candles) | < 16ms |
| JS heap | < 40MB for a 20-symbol watchlist |
| Layout thrash | Zero on quote refresh — update text nodes, not `innerHTML` for the whole tree |

Implementation notes:

- One HTML file. No React, no build step, no CDN. Font stack falls back to system
  monospace so the terminal works offline.
- `requestAnimationFrame` for chart sizing; resize observer / `window.resize` only.
- Batch quote requests; never one request per symbol.
- `AbortController` + 15s timeout on every fetch.
- Cap sparkline history at 40 points per symbol.
- Avoid `Date` parsing in render loops; precompute tick labels.

---

## 10. Safety & Compliance

- **Default PAPER.** Live requires an explicit dialog each session and turns the top-bar
  mode red.
- **Confirm every order** with full parameters, including estimated value and mode.
- **No accidental market orders.** `MARKET` is clearly labelled; the API converts it to a
  limit at the live price. The only real market orders come from `FLATTEN`, which requires
  armed LIVE mode plus a separate confirm; the backend still defaults to `dry_run: true`.
- **Token hygiene.** `localStorage` only; no token in URLs, logs, screenshots, or the
  `/api/terminal/*` error payloads. Provide "Forget saved token". Decode JWT `exp` locally
  for the HUD only; never display or send the token payload anywhere.
- **Expiry awareness.** `AUTH` turns amber under 60 minutes and red under 15 minutes.
  On `/funds` 401, keep the last good balances stale and surface the actionable re-paste
  message rather than silently showing zero.
- **Static IP.** INDstocks order APIs require a whitelisted static IP. If orders return
  `403`, surface the broker message verbatim — do not retry silently.
- **Personal use.** NSE/BSE data redistribution requires exchange licensing. Keep this a
  single-operator workstation.
- **Not investment advice.** GEX/PCR/signals are estimates from OI; label them as such in
  any exported report.

---

## 11. Implementation Map

| File | Role |
| --- | --- |
| `terminal.html` | The terminal UI (tokens, shell, views, chart, ticket, command engine) |
| `stock_dashboard.py` | HTTP server + `/api/terminal/*` INDstocks proxy + order validation |
| `assets/indstocks_equity_master.csv` | Symbol → `SECURITY_ID` resolution (23k rows) |
| `assets/indices_with_options.json` | Index expiries, lot sizes, strike ranges |
| `gex.py` | Option-chain normalisation, GEX, max pain, gamma flip, control |
| `stock_dashboard.html` | Legacy dashboard, still served at `/legacy` |
| `terminal_features.md` | Product/feature blueprint (what the terminal can do) |
| `terminal_frontend.md` | This document (how it looks and behaves) |

### Routing

```
GET  /           → terminal.html      (main page)
GET  /terminal   → terminal.html
GET  /legacy     → stock_dashboard.html
GET  /api/...    → existing dashboard APIs
GET  /api/terminal/... → INDstocks proxy
POST /api/terminal/order → place / simulate
POST /api/terminal/flatten → close-all (dry-run default)
```

---

## 12. Build Checklist

### P0 — must ship

- [x] Full-viewport token gate with validation, paste, show/hide, forget, read-only.
- [x] Token persisted in `localStorage`; sent as `X-IND-Token`; never logged.
- [x] Dense three-column shell + ticker tape + status bar.
- [x] Watchlist with add/remove, batch quotes, sparklines, 3s refresh.
- [x] Security header with OHLC/52W/volume.
- [x] Canvas candlestick chart + volume + crosshair + timeframes.
- [x] 5-level depth ladder.
- [x] Option chain with Greeks, OI bars, ATM highlight, metrics.
- [x] Header HUD with compact available balance, realised+unrealised P&L and JWT countdown.
- [x] `FA` fundamentals workbench: annual/quarterly P&L, balance sheet, cash flow,
  ratios, shareholding, compounded-growth cards, YoY earnings and 1Y/3Y/5Y price graph.
- [x] `BLOCK` bulk/block-flows view.
- [x] Order ticket with PAPER/LIVE, confirmation, dry-run.
- [x] Aggregated positions, orders, funds panels.
- [x] `FLATTEN ALL` with modal confirm, PAPER simulation and backend dry-run default.
- [x] Command line + palette + F-key navigation, optional `<GO>` suffix, `BUY <QTY> <TICKER>`.
- [x] Toasts and error states.

### P1 — next

- [ ] WebSocket price feed with REST fallback and reconnect/backoff.
- [ ] Live order-update feed wired into the order book.
- [ ] Holdings view and Demat P&L.
- [ ] **Smart GTT**: OCO trigger + trailing stop + target ladder, stored as templates and
  reconciled against `/order-book` instead of fire-and-forget brokerside GTT.
- [ ] **ORB scanner**: 15-minute opening-range displacement, persisted scan results and
  click-through into `GP`.
- [ ] **FIIDII / flows view**: daily institutional cash + derivatives activity beside the
  existing `BLOCK` table.
- [ ] **Macro wire**: compact `ECO` / rates / USD-INR / crude / global index strip driven by
  the existing headline pipeline.
- [ ] Multi-window layouts (2×2 quadrants, saved workspaces).
- [ ] Chart indicators (VWAP, EMA, opening range) toggled from the chart toolbar.
- [ ] GEX history sparkline and change-vs-previous arrows.
- [ ] Symbol-level news + corporate actions tabs.
- [ ] Sound/visual alert when an order fills or a price alert triggers.

### P2 — polish

- [ ] Column reordering and persisted widths per table.
- [ ] Export current view to CSV / PNG.
- [ ] Light "print" theme for reports (black-on-white, same density).
- [ ] Mobile read-only layout with a compact tape + watchlist.
- [ ] Session replay / audit log of every order attempt (paper and live).

---

## 13. Acceptance Criteria

The terminal is "done" for v1 when:

1. Opening `http://localhost:9090/` shows the token gate, never the dashboard.
2. A valid token reaches the terminal in under 1s; an invalid token stays on the gate with
   an actionable error.
3. Quotes for at least 20 symbols refresh every 3s and the latency badge stays visible.
4. `RELIANCE GP <GO>` loads a chart; `NIFTY OMON <GO>` loads Greeks; `RELIANCE FA <GO>`
   loads fundamentals with YoY cards, a price graph and the P&L / balance-sheet /
   cash-flow / ratios / shareholding tabs; `BLOCK <GO>` and `TOP <GO>` load flows and news.
5. `F3`–`F10`, `Alt+X` and `Ctrl+K` work from anywhere without stealing keystrokes from
   inputs; `BUY 10 RELIANCE <GO>` only pre-fills the ticket.
6. PAPER order returns a `PAPER-*` id; LIVE order opens a red confirmation and only then
   calls `/order`.
7. `FLATTEN ALL` previews open positions, defaults to simulation in PAPER, and sends real
   market closes only after an armed-LIVE confirm.
8. `AVL`, `P&L` and `AUTH` populate from funds/JWT metadata, and `AUTH` counts down locally
   without making extra network calls.
9. Every panel has a loading, empty and error state — no blank rectangles.
10. The layout holds at 1280×720 and 1920×1080 with no page scroll; only inner panels scroll.
11. No console errors on load, refresh, symbol switch, or order submit.
12. The token never appears in the DOM, URL, network log body, or server log.

---

*FRIDAY TERM 1.0 — design system locked. Keep the palette, the density and the keyboard
grammar; extend the panels, not the chrome.*
