# TODO — Live NIFTY 50 GEX / Greeks Report + NSE Earnings & Event News

Two workstreams:

1. **Live NIFTY 50 GEX report** from the INDmoney / INDstocks option-chain API (IV, delta, gamma, theta, vega, max pain, PCR, gamma flip).
2. **NSE earnings / corporate-event + news calendar** — scrape all stock names and every upcoming event/announcement from NSE and expose it in the dashboard.

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

## Order of work
1. Refresh INDmoney token, verify live GEX endpoint, add the compact live report card + auto-refresh.
2. Build `nse_events.py` + API routes with caching and tests.
3. Add the **NSE Events / Earnings** dashboard tab and stock-name panel.
4. Optional: IV term structure and Telegram digests (only after 1–3 are stable).

## Notes / constraints
- INDmoney token expiry currently blocks live GEX; the code now fails loudly and shows the last-good snapshot instead of an empty section.
- NSE `/api` endpoints are undocumented and can change; keep all fetching behind a single module with timeouts, caching, and graceful degradation.
- Respect NSE Terms of Use; for commercial use, NSE Data & Analytics is the licensed route.
- Do not add interactive Telegram commands; the bot stays send-only.
