# TODO — Live NIFTY 50 GEX / Greeks Report + NSE Events + Market Decision Data

Four workstreams:

1. **Live NIFTY 50 GEX report** from the INDmoney / INDstocks option-chain API (IV, delta, gamma, theta, vega, max pain, PCR, gamma flip).
2. **NSE earnings / corporate-event + news calendar** — scrape all stock names and every upcoming event/announcement from NSE and expose it in the dashboard.
3. **Market decision-support data** — India VIX, FII/DII flows, breadth, delivery volume, OI build-up, global cues, risk gates.
4. **Nifty options edge handbook** — Charm, Vanna, Theta-to-Gamma, OI/PCR positioning, expiry-day mechanics, and pre-market/intraday checklists.

Legend: `[x]` already in the repo, `[ ]` still to do.

---

## 1. Live NIFTY 50 GEX / Greeks report (INDmoney API key)

### Data source
- Endpoint: `GET https://api.indstocks.com/market/option-chain`
- Header: `Authorization: <INDMONEY_API_TOKEN>` (from `.env`, loaded by `bullish_put_filter.get_token()`)
- Params:
  - `exchange=NSE`
  - `segment=INDEX`
  - `underlying-scrip=40000001` (NIFTY 50; SENSEX = `40000006`, `BSE`)
  - `expiry=YYYY-MM-DD` (from `assets/indices_with_options.json` → `upcoming_expiries`)
  - `strike_count=15` (clamped 3–30)
- Greeks come **pre-calculated** in each leg: `greeks.delta`, `greeks.gamma`, `greeks.theta`, `greeks.vega`; plus `iv`, `oi`, `previous_oi`, `volume`, `last_price`.
- No local Black-Scholes calculation needed.

### Already done `[x]`
- [x] `gex.py` — `fetch_chain()`, `_normalise_leg()`, `analyze_chain()`, `pick_expiry()`, `available_expiries()`, `get_gex()`
- [x] Dealer-GEX convention: `(-CE_OI × CE_gamma + PE_OI × PE_gamma) × lot_size × spot × 0.01` (₹ crore)
- [x] Metrics: net/call/put GEX, per-strike delta/gamma/theta/vega/IV, OI change, PCR (OI + volume), max pain, gamma flip + spot-vs-flip, avg IV, buyer/seller verdict
- [x] `GET /api/gex?index=NIFTY|SENSEX&expiry=YYYY-MM-DD&strike_count=15` in `stock_dashboard.py`
- [x] Dashboard **GEX / Greeks** tab in `stock_dashboard.html` (`loadGex()` / `renderGex()`), expiry selector, refresh, verdict banner, metrics, OI bar, strike table
- [x] 60s memory cache + `assets/gex_last_good.json` stale fallback with `[stale]` badge (gitignored)
- [x] `tests/gex_test.py` (8 tests)

### Remaining `[ ]`
- [ ] **Refresh the expired INDmoney token.** Current `.env` token returns `403: access_token expired/revoked`. Update `INDMONEY_API_TOKEN` in `.env` and reconnect the INDmoney bot token, then restart the dashboard (`bash run-stock.sh --no-install`) and verify `curl "http://localhost:9090/api/gex?index=NIFTY"` returns 31 strike rows with no `error`.
- [ ] **Live report view:** add a compact "NIFTY 50 Live GEX Report" card at the top of the GEX tab with spot, expiry, time-to-expiry, net GEX, max pain, gamma flip, PCR, and buyer/seller control — one-glance summary plus the detailed table below.
- [ ] **Auto-refresh** GEX every 60s while the tab is active (respect the 60s cache), plus "last updated" timestamp and a visible stale/token-error banner.
- [ ] **IV surface / term structure:** fetch the next 2–3 expiries and chart avg CE/PE IV + ATM IV by expiry (uses the same endpoint, one call per expiry; cache separately).
- [ ] **Delta / gamma exposure by strike:** stacked bar of CE vs PE gamma exposure and cumulative net delta, with the gamma-flip strike marked on price axis.
- [ ] **Change tracking:** store snapshots in `assets/gex_history.jsonl` (timestamp, expiry, net GEX, max pain, PCR, IV) and show "Change vs previous refresh" arrows.
- [ ] **Alert hooks (optional):** Telegram alert when control flips (buyers ↔ sellers) or spot crosses the gamma flip. Reuse `telegram_notify.py`; must stay send-only, no interactive commands.
- [ ] **Tests:** extend `tests/gex_test.py` for stale-cache fallback, token-403 message, expiry override, and IV-term-structure aggregation.
- [ ] **Docs:** add a short "How to refresh INDmoney token" note to `README`/`todo.md` once the new token is in place.

### Acceptance criteria
- `GET /api/gex?index=NIFTY` returns `{expiry, underlying_ltp, gex_cr, max_pain, pcr_oi, gamma_flip, control, rows[31]}` with no `error` and `stale: false`.
- UI GEX tab renders without manual refresh and clearly shows IV, delta, gamma, theta, vega for each strike.
- On token failure: clear actionable message + last-good snapshot badge, never a blank section.

---

## 2. NSE earnings / corporate events / stock news scraper

Goal: from the NSE website, capture **all stock names** and **every news/event item** a stock is going to give (upcoming earnings/results, board meetings, dividends, bonuses, splits, buybacks, AGM/EGM, investor meets, press releases, etc.), then show it in the dashboard.

### NSE endpoints (public JSON, no key; browser User-Agent required)
All under `https://www.nseindia.com/api/`:

| Purpose | Endpoint | Params |
|---|---|---|
| Announcements / any filing | `corporate-announcements` | `index=equities`, `from_date=DD-MM-YYYY`, `to_date=DD-MM-YYYY`, optional `symbol=` |
| Upcoming corporate actions (dividend/bonus/split/buyback) | `corporates-corporateActions` | same; range filters on **ex-date** |
| Board meetings (often earnings date) | `corporate-board-meetings` | same; range filters on **meeting date** |
| Event calendar | `event-calendar` | same; optional `index=equities`, `fo_sec=true` |
| Financial results (unreliable for ranges) | `corporates-financial-results` | `index=equities`, `period=Quarterly|Annual|Half-Yearly` |
| Equity universe / stock names | `equity-stockIndices?index=NIFTY%2050` and NSE master CSV | no auth |
| Latest bulk/block deals | `snapshot-capital-market-largedeal` | already used in `stock_dashboard.py` |

RSS fallback: `https://nsearchives.nseindia.com/content/RSS/{Announcements,Corporate_action,Board_Meetings,Financial_Results}.xml` (latest items only, ~5 min TTL).

### Scraping rules (important)
- Send a **browser User-Agent** (`Mozilla/5.0 ... Chrome/...`); default `python-requests` UA gets no response.
- Reuse `_get_nse_session()` in `stock_dashboard.py:668` (already warms cookies via `https://www.nseindia.com/`). If API returns 401/403, load `https://www.nseindia.com/companies-listing/corporate-filings-announcements` in the same session and retry.
- Dates **must** be `DD-MM-YYYY`; wrong formats return `200 {"data":[]}` silently.
- `index=equities` is required; omitting it returns plain text `Missing index`.
- No dates ⇒ only the latest 20 rows. `symbol=SYM` with no dates ⇒ **entire history** (multi-MB) — always bound with a date window.
- Dedupe on `seq_id`. Parse `an_dt` / `sort_date` as Asia/Kolkata (UTC+05:30).
- Cache past days once; poll only the current day every ~3–5 min; keep requests sequential and polite. Endpoints are undocumented/unofficial — treat as failure-prone and cache results.

### Fields to capture
- Identity: `symbol`, `sm_name`, `sm_isin`, `smIndustry`, `seq_id`
- Event: `desc` (subject), `attchmntText` (summary), `an_dt`, `sort_date`, `exchdisstime`
- Attachment: `attchmntFile` (PDF on `nsearchives.nseindia.com`), `attFileSize`, `hasXbrl`
- Corporate action: `subject`, `exDate`, `recDate`, `bcStartDate`, `bcEndDate`, `series`, `faceVal`, `comp`, `isin`
- Board meeting: meeting date + purpose text
- Event calendar: `symbol`, `company`, `purpose`, `bm_desc`, `date`, `fo_sec`

### Tasks `[ ]`
- [ ] Create `nse_events.py`:
  - `get_session()` — browser-like headers + cookie warm-up (reuse/extend `stock_dashboard._get_nse_session`)
  - `fetch_announcements(from_date, to_date, symbol=None, index="equities")`
  - `fetch_corporate_actions(...)`, `fetch_board_meetings(...)`, `fetch_event_calendar(...)`
  - `fetch_all_stock_names()` — union of NSE equity indices/master + every symbol seen in calendars; write `assets/nse_stock_names.json`
  - `classify_event(desc)` — tags: `EARNINGS`, `BOARD_MEETING`, `DIVIDEND`, `BONUS`, `SPLIT`, `BUYBACK`, `AGM_EGM`, `INVESTOR_MEET`, `PRESS_RELEASE`, `OTHER`
  - `parse_event_datetime()` — Asia/Kolkata aware
  - `normalise()` → common record schema `{seq_id, symbol, company, event_type, title, summary, event_date, published_at, source_url, pdf_url, raw}`
  - `get_events(days_ahead=30, days_back=7, fo_only=False)` — merged, deduped, cached (`assets/nse_events_cache.json`, gitignored)
- [ ] Add API routes in `stock_dashboard.py`:
  - `GET /api/nse/events?days_ahead=30&days_back=7&type=EARNINGS&symbol=RELIANCE&fo_only=false`
  - `GET /api/nse/stock-names` (full scraped universe, with count)
  - `GET /api/nse/event-summary` (counts by type, next 7 days, top symbols)
- [ ] Add a dashboard tab **“NSE Events / Earnings”** in `stock_dashboard.html`:
  - Upcoming events table (date, symbol, company, type badge, title, summary, PDF link)
  - Filters: symbol search, event type, F&O-only, date range
  - "All stock names" panel with count + search + last-synced time
  - News/event detail drawer using `attchmntText` + PDF link
  - Refresh button with last-updated timestamp and source-status banner
- [ ] Earnings-specific view: board-meeting + announcement rows tagged `EARNINGS`, sorted by date, with "result expected on" date and link to filing.
- [ ] Cross-reference with F&O universe from `assets/stocks_with_options.json` so option traders see which event stocks have derivatives.
- [ ] Optional Telegram digest: send next-day earnings/board meetings for the watchlist only; send-only, no commands (reuse `telegram_notify.py`).
- [ ] Tests `tests/nse_events_test.py`: mocked JSON payloads, date format validation, `seq_id` dedupe, classification, timezone parsing, cache fallback on 403/timeout.
- [ ] Add `assets/nse_events_cache.json`, `assets/nse_stock_names.json` to `.gitignore` if they contain fetched/generated data.

### Acceptance criteria
- `GET /api/nse/stock-names` returns the full scraped NSE equity symbol list (hundreds+) with a last-synced timestamp.
- `GET /api/nse/events?days_ahead=30` returns deduped upcoming events with symbols, dates, event types, summaries and PDF links; earnings/board meetings clearly tagged.
- Dashboard tab lists all stock names and upcoming events without blank rows; failures show a clear "NSE source unavailable — showing cached data" message.
- No auth/CAPTCHA bypass; only public NSE JSON/RSS endpoints with browser-like headers.

---

## 3. Market decision-support data (beyond GEX and earnings)

Goal: give the dashboard a complete "regime + flows + risk" picture so signals are sized and filtered correctly.

| Priority | Data | Why it matters | Where to get it (India) | How to use it |
|---|---|---|---|---|
| 1 | **India VIX + IV rank / IV skew / term structure** | Tells you whether the market is calm, complacent, or panicking. GEX = dealer positioning; VIX/IV = price of risk. | India VIX from NSE `/api/allIndices`; IV from INDmoney option chain; NSE F&O volatility archives | Suppress breakouts when VIX spikes; prefer spreads when IV rank is high; inspect 25-delta skew before directional trades |
| 2 | **FII / DII flows + participant-wise OI** | FIIs drive index trends; DIIs absorb selling. Participant OI shows whether clients, pros, or institutions hold the position. | NSE `fiidiiTradeReact`, FII stats XLS, F&O “Participant wise Open Interest” CSV | Align bias with FII flow; fade client-only moves with no institutional support |
| 3 | **Market breadth + sector rotation** | A NIFTY rally led by 4 heavyweights is fragile; broad participation is durable. | NSE constituents, advances/declines, 52-week high/low lists, `/api/allIndices` sector indices | Size positions down when breadth is negative even if a stock signal is bullish |
| 4 | **Delivery volume + price/volume** | High delivery % = real accumulation; low delivery = intraday churn. Bulk deals are stronger when confirmed by delivery. | NSE full bhavcopy `sec_bhavdata_full` (`DELIV_QTY`, `DELIV_PER`) | Filter watchlist to rising delivery % + price breakouts; avoid volume spikes with poor delivery |
| 5 | **OI change / PCR / long–short build-up** | Complements GEX. Price↑ + OI↑ = long build-up; price↓ + OI↑ = short build-up; PCR extremes flag crowding. | INDmoney `oi` vs `previous_oi`; NSE F&O bhavcopy | Add an “OI build-up” column next to the GEX table; use PCR + max pain + gamma flip together |
| 6 | **F&O ban list, MWPL, ASM/GSM** | Hard risk gates — a perfect setup is useless if the stock is banned or under surveillance. | NSE F&O ban-period report / `fo_secban`, ASM/GSM lists | Block or flag entries in banned/ASM/GSM stocks as a pre-trade check in `indmoney_intraday_bot.py` |
| 7 | **Promoter/insider activity + shareholding pattern** | Promoter buying and FII stake increases are slow but powerful signals. | NSE PIT, shareholding master, corporate announcements | Add an “Ownership” filter to the NSE Events tab; combine with delivery volume |
| 8 | **Global macro / pre-market cues** | Indian gaps are often driven by overnight US, crude, dollar and Asia moves. | Gift/SGX Nifty, USD/INR, Brent, DXY, US 10Y, Fed/CPI/RBI calendar | Show a “Global Cues” strip above the GEX tab; decide aggressive vs defensive sizing at open |
| 9 | **Earnings quality, not just date** | Guidance, concall language and estimate revisions drive post-result drift. | NSE announcement PDFs, concall transcripts, broker reports | In the NSE Events tab, link the PDF and add a “guidance / estimate” note field |
| 10 | **Order book / liquidity** | Spread and depth decide whether the exit is clean, especially in options. | NSE quote/order book, INDmoney depth | Avoid trades where bid-ask is wide relative to the stop; check impact cost before sizing |

### Already in the repo `[x]`
- [x] GEX, Greeks, max pain, PCR, gamma flip — `gex.py` + GEX tab
- [x] Bulk/block/large deals — `stock_dashboard.py`
- [x] News RSS + top-buying stocks — `stock_dashboard.py`, `stock_tools.py`
- [x] Daily support scanner, opening-range backtester, Monte Carlo reports
- [x] VWAP×EMA auto bot with trailing/partial exits — `indmoney_intraday_bot.py`

### Next additions `[ ]`
- [ ] **Market Regime tab** — India VIX, breadth, FII/DII, sector heatmap, global cues. One screen that answers “risk-on or risk-off today?”
- [ ] **Delivery × OI confluence screener** — full bhavcopy delivery % + option OI change + GEX/PCR → rank stocks by conviction.
- [ ] **Risk-gate layer** — F&O ban, ASM/GSM, high IV, and event-risk flags wired into the bot so it refuses bad setups automatically.

---

## 4. Nifty options edge handbook — Greeks, positioning, mechanics

Companion to GEX/IV: focus on **additional Greeks**, **market positioning**, and **Indian market mechanics**.

### 4.1 Additional option Greeks `[ ]`
- [x] **Delta, Gamma, Theta, Vega** — already supplied pre-calculated by INDmoney (`greeks.*`) and shown per strike.
- [ ] **Charm (Delta decay)** — how Delta changes as time passes. On weekly Nifty expiry days Charm accelerates, forcing market makers to unwind hedges and causing sudden late-session moves. Approximate from cached snapshots: `Charm ≈ ΔDelta / ΔT`; store snapshots in `assets/gex_history.jsonl`.
- [ ] **Vanna** — how Delta changes when IV shifts. After an event/IV crush, Vanna flows can push Nifty upward as dealers buy back short hedges. Approximate: `Vanna ≈ ΔDelta / ΔIV` using the IV term-structure snapshots.
- [ ] **Theta-to-Gamma ratio** — Nifty options decay fast in the final two days; this ratio helps choose buying for momentum vs selling for range-bound decay. Add as a per-strike column and a regime flag.
- [ ] Label Charm/Vanna as **finite-difference approximations** from snapshots, not exact analytic greeks (the API does not supply them).

### 4.2 Market positioning & liquidity
- [x] **OI & Change in OI** — highest Call OI = resistance, highest Put OI = support. Keep the existing `oi` / `previous_oi` fields and expose them per strike.
- [ ] **Intraday OI change at psychological levels** — watch fresh addition vs unwinding around every 100 / 500 Nifty point level; add a “fresh position vs unwinding” indicator.
- [x] **PCR** — already computed (OI and volume). Track intraday extremes: `PCR > 1.4` often means put writers are heavily confident; if support breaks, expect a sharp short-covering drop.
- [ ] **India VIX + IV Rank (IVR)** — compare VIX and strike IV to the past year. High IVR favors option selling; low IVR favors buying ahead of a breakout.
- [x] **Max Pain** — already computed. Use as a quiet-session expiry magnet, not a standalone signal.

### 4.3 Indian market mechanics & flows
- [ ] **FII/DII derivatives data** — NSE releases participant-wise OI daily after close. Strong FII net-short futures positioning often caps Nifty rallies. Show net long/short by participant.
- [ ] **Synthetic future & spot–future basis** — infer from ATM call/put OI and futures price vs spot; premium/discount indicates institutional sentiment and cost-of-carry shifts.
- [ ] **Expiry-day dynamics** — weekly expiries mean 0-DTE mechanics dominate. Post **13:30 IST** frequently sees gamma squeezes when a major OI strike breaks; add a time-aware alert/flag.

### 4.4 Checklists to build into the dashboard
**Pre-market**
1. India VIX / IVR regime + global cues (Gift Nifty, USD/INR, crude, DXY, US 10Y).
2. Previous-close FII/DII derivatives positioning.
3. Max pain, gamma flip, highest CE/PE OI strikes for the chosen expiry.
4. Earnings/event calendar for watchlist holdings.

**Intraday**
1. Spot vs gamma flip and max pain; note which OI strikes are being defended.
2. PCR shift and OI change at key 100/500-point strikes.
3. Charm / Vanna / Theta-to-Gamma flag as expiry approaches; raise post-13:30 gamma-squeeze alert.
4. Risk gates: F&O ban, ASM/GSM, wide bid-ask, event risk.
5. Position size from the Market Regime tab, not from a single signal.

### 4.5 Open questions to tailor this
- [ ] Trading style: intraday option buying, expiry-day selling, or positional swings?
- [ ] Current charting/data setup: Sensibull, Opstra, TradingView, or only this dashboard?

---

## Order of work
1. Refresh INDmoney token, verify live GEX endpoint, add the compact live report card + auto-refresh.
2. Build `nse_events.py` + API routes with caching and tests; add the **NSE Events / Earnings** tab and stock-name panel.
3. Add the **Market Regime** tab (India VIX, breadth, FII/DII, sector heatmap, global cues).
4. Add advanced Greeks (Charm/Vanna approximations, Theta-to-Gamma) and OI/PCR/expiry-day flags.
5. Add the **Delivery × OI confluence screener** and the F&O-ban/ASM/GSM risk-gate layer.
6. Optional: IV term structure, Telegram digests, and pre-market/intraday checklist view (only after 1–5 are stable).

## Notes / constraints
- INDmoney token expiry currently blocks live GEX; the code now fails loudly and shows the last-good snapshot instead of an empty section.
- NSE `/api` endpoints are undocumented and can change; keep all fetching behind a single module with timeouts, caching, and graceful degradation.
- Respect NSE Terms of Use; for commercial use, NSE Data & Analytics is the licensed route.
- Do not add interactive Telegram commands; the bot stays send-only.
