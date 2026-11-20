#!/usr/bin/env python3
"""
bullish_put_filter.py
=====================
Screens F&O-enabled Indian stocks for:
  1. Bullish momentum for 5 consecutive trading days (higher closes or green bars).
  2. Opposite side (Put option) premium < ₹20.
  3. Total investment for 1 lot of that Put option <= ₹5,000 (i.e. Put LTP * Lot Size <= ₹5,000).

API Documentation Reference: assets/indstocks-api-docs.md
Endpoints used:
  - GET /market/instruments?source=fno
  - GET /market/historical/1day
  - GET /market/option-chain
"""

import os
import sys
import csv
import json
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
import requests
from dotenv import dotenv_values, load_dotenv

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
STOCKS_JSON = os.path.join(ASSETS_DIR, "stocks_with_options.json")
OUTPUT_JSON = os.path.join(ASSETS_DIR, "bullish_stocks_with_cheap_puts.json")
OUTPUT_CSV = os.path.join(ASSETS_DIR, "bullish_stocks_with_cheap_puts.csv")


def get_token() -> str:
    """Load INDstocks API token."""
    load_dotenv(os.path.join(BASE_DIR, ".env"))
    env_vars = dotenv_values(os.path.join(BASE_DIR, ".env"))
    token = (
        os.environ.get("INDMONEY_API_TOKEN")
        or os.environ.get("INDSTOCKS_TOKEN")
        or os.environ.get("INDMONEY_ACCESS_TOKEN")
        or env_vars.get("INDMONEY_API_TOKEN")
        or env_vars.get("INDSTOCKS_TOKEN")
        or env_vars.get("INDMONEY_ACCESS_TOKEN")
        or ""
    ).strip()
    if not token:
        raise ValueError("INDMONEY_API_TOKEN not found in .env or environment")
    return token


class BullishPutFilter:
    """Scanner that detects 5-day bullish stocks with Put options under ₹20 and <= ₹5,000 per lot."""

    BASE_URL = "https://api.indstocks.com"

    def __init__(
        self,
        token: Optional[str] = None,
        consecutive_days: int = 5,
        max_put_premium: float = 20.0,
        max_lot_investment: float = 5000.0,
        bullish_mode: str = "higher_closes",  # "higher_closes", "green_candles", "either"
    ):
        self.token = token or get_token()
        self.headers = {
            "Authorization": self.token,
            "Accept": "application/json",
        }
        self.consecutive_days = consecutive_days
        self.max_put_premium = max_put_premium
        self.max_lot_investment = max_lot_investment
        self.bullish_mode = bullish_mode

    def load_stocks(self) -> List[Dict[str, Any]]:
        """Load option-enabled stocks from assets/stocks_with_options.json or scan if missing."""
        if not os.path.exists(STOCKS_JSON):
            print("[*] stocks_with_options.json not found. Running fetch_option_stocks...")
            from fetch_option_stocks import IndstocksOptionScanner
            scanner = IndstocksOptionScanner(self.token)
            scan_res = scanner.scan_options_instruments()
            scanner.save_outputs(scan_res)

        with open(STOCKS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("stocks", [])

    def fetch_historical_daily_candles(
        self, scrip_codes: List[str], days_lookback: int = 25
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Fetch 1day candles for up to 5 scrip codes in a single API call.
        Query parameters per docs:
          - scrip-codes: comma-separated list of max 5 instrument identifiers
          - start_time: epoch milliseconds
          - end_time: epoch milliseconds
        """
        now = datetime.now()
        end_ms = int(now.timestamp() * 1000)
        start_ms = int((now - timedelta(days=days_lookback)).timestamp() * 1000)

        codes_str = ",".join(scrip_codes)
        url = f"{self.BASE_URL}/market/historical/1day?scrip-codes={codes_str}&start_time={start_ms}&end_time={end_ms}"

        r = requests.get(url, headers=self.headers, timeout=12)
        if r.status_code == 200:
            res = r.json()
            if res.get("success") and "data" in res:
                candles_by_scrip = {}
                for code, cdata in res["data"].items():
                    candles_by_scrip[code] = cdata.get("candles", [])
                return candles_by_scrip
        elif r.status_code == 429:
            print("[!] Rate limit encountered in historical data. Sleeping 2 seconds...")
            time.sleep(2)
        else:
            print(f"[!] Warning: HTTP {r.status_code} fetching historical candles for {codes_str}: {r.text[:120]}")
        return {}

    def is_bullish(self, candles: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, Any]]:
        """
        Check if the last N candles meet the bullish condition:
          - higher_closes: Close[t] > Close[t-1] for N consecutive days
          - green_candles: Close[t] > Open[t] for N consecutive days
          - either: satisfies higher_closes OR green_candles
        """
        n = self.consecutive_days
        # We need at least n + 1 candles to compute n daily close changes
        if len(candles) < (n + 1):
            return False, {}

        relevant_candles = candles[-(n + 1):]
        closes = [c["c"] for c in relevant_candles]
        opens = [c["o"] for c in relevant_candles[1:]]
        highs = [c["h"] for c in relevant_candles[1:]]
        lows = [c["l"] for c in relevant_candles[1:]]
        dates = [datetime.fromtimestamp(c["ts"]).strftime("%Y-%m-%d") for c in relevant_candles[1:]]

        # 1. Higher closes: Close[i] > Close[i-1] for each of the last N days
        daily_close_changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        daily_close_pcts = [(daily_close_changes[i] / closes[i]) * 100 for i in range(len(daily_close_changes))]
        is_higher_closes = all(ch > 0 for ch in daily_close_changes)

        # 2. Green candles: Close[i] > Open[i] for each of the last N days
        is_green_candles = all(closes[i + 1] > opens[i] for i in range(n))

        if self.bullish_mode == "higher_closes":
            bullish = is_higher_closes
        elif self.bullish_mode == "green_candles":
            bullish = is_green_candles
        elif self.bullish_mode == "either":
            bullish = is_higher_closes or is_green_candles
        elif self.bullish_mode == "both":
            bullish = is_higher_closes and is_green_candles
        else:
            bullish = is_higher_closes

        start_price = closes[0]
        end_price = closes[-1]
        net_return_pct = ((end_price - start_price) / start_price) * 100.0

        details = {
            "dates": dates,
            "start_close": start_price,
            "latest_close": end_price,
            "net_gain_pct": round(net_return_pct, 2),
            "daily_closes": closes[1:],
            "daily_changes_pct": [round(p, 2) for p in daily_close_pcts],
            "is_higher_closes": is_higher_closes,
            "is_green_candles": is_green_candles,
            "streak_days": n,
        }
        return bullish, details

    def fetch_option_chain_puts(
        self, nse_security_id: str, expiry: str, lot_size: int, strike_count: int = 15
    ) -> Tuple[Optional[float], List[Dict[str, Any]], Dict[str, Any]]:
        """
        Fetch option chain and extract Put options meeting:
          - put_price < max_put_premium (e.g. < 20.0)
          - put_price * lot_size <= max_lot_investment (e.g. <= 5000.0)
        Returns: (underlying_ltp, eligible_puts, atm_put_info)
        """
        url = (
            f"{self.BASE_URL}/market/option-chain"
            f"?exchange=NSE&segment=EQUITY&underlying-scrip={nse_security_id}&expiry={expiry}&strike_count={strike_count}"
        )
        r = requests.get(url, headers=self.headers, timeout=10)
        if r.status_code != 200:
            return None, [], {}

        res = r.json()
        if res.get("status") != "success" or "data" not in res:
            return None, [], {}

        data = res["data"]
        spot_ltp = float(data.get("underlying_ltp") or 0.0)
        strikes = data.get("strikes", {})
        if not strikes or spot_ltp <= 0:
            return spot_ltp, [], {}

        # Identify ATM strike
        sorted_strike_nums = sorted([float(k) for k in strikes.keys()])
        atm_strike_num = min(sorted_strike_nums, key=lambda x: abs(x - spot_ltp))

        atm_key = str(int(atm_strike_num)) if atm_strike_num.is_integer() else str(atm_strike_num)
        atm_pe = strikes.get(atm_key, {}).get("pe", {}) or {}
        atm_pe_price = float(atm_pe.get("last_price") or 0.0)
        atm_lot_cost = round(atm_pe_price * lot_size, 2)
        atm_info = {
            "strike": atm_strike_num,
            "put_price": atm_pe_price,
            "lot_cost": atm_lot_cost,
            "oi": atm_pe.get("oi", 0),
            "volume": atm_pe.get("volume", 0),
            "iv": atm_pe.get("iv"),
            "trading_symbol": atm_pe.get("trading_symbol", ""),
            "meets_criteria": (0 < atm_pe_price < self.max_put_premium and atm_lot_cost <= self.max_lot_investment),
        }

        eligible_puts = []
        for strk_str, legs in strikes.items():
            pe = legs.get("pe", {})
            if not pe:
                continue
            last_price = float(pe.get("last_price") or 0.0)
            if last_price <= 0:
                continue

            lot_cost = round(last_price * lot_size, 2)
            strike_val = float(strk_str)
            dist_pct = round(((strike_val - spot_ltp) / spot_ltp) * 100.0, 2)

            if last_price < self.max_put_premium and lot_cost <= self.max_lot_investment:
                greeks = pe.get("greeks") or {}
                eligible_puts.append({
                    "strike": strike_val,
                    "put_price": last_price,
                    "lot_cost": lot_cost,
                    "distance_from_spot_pct": dist_pct,
                    "is_otm": strike_val < spot_ltp,
                    "is_atm": abs(strike_val - atm_strike_num) < 1e-4,
                    "trading_symbol": pe.get("trading_symbol", ""),
                    "security_id": pe.get("security_id", ""),
                    "oi": pe.get("oi", 0),
                    "volume": pe.get("volume", 0),
                    "iv": pe.get("iv"),
                    "delta": greeks.get("delta"),
                    "theta": greeks.get("theta"),
                    "top_bid": pe.get("top_bid_price"),
                    "top_ask": pe.get("top_ask_price"),
                    "breakeven_price": round(strike_val - last_price, 2),
                })

        # Sort eligible puts descending by strike (nearest to spot / highest strike first)
        eligible_puts.sort(key=lambda x: x["strike"], reverse=True)
        return spot_ltp, eligible_puts, atm_info

    def run_screen(self, progress_callback=None) -> Dict[str, Any]:
        """
        Execute full screening across all optionable stocks:
          Step 1: Fetch historical candles & find 5-day bullish stocks.
          Step 2: Check Put option chains for premium < 20 and 1-lot cost <= 5000.
        """
        stocks = self.load_stocks()
        total_stocks = len(stocks)
        print(f"[*] Starting Bullish + Cheap Put Screen on {total_stocks} F&O stocks...")
        print(f"[*] Criteria: Bullish for {self.consecutive_days} days straight ({self.bullish_mode})")
        print(f"[*] Opposite Put Filter: Premium < ₹{self.max_put_premium} & 1-Lot Investment <= ₹{self.max_lot_investment:,.2f}")

        # Batch 5 scrips per historical call
        batches = []
        curr = []
        for s in stocks:
            if s.get("scrip_code") and s.get("nse_security_id"):
                curr.append(s)
                if len(curr) == 5:
                    batches.append(curr)
                    curr = []
        if curr:
            batches.append(curr)

        print(f"[*] Analyzing 5-day daily candles across {len(batches)} batches (~44 API requests)...")

        bullish_stocks = []
        for b_idx, b in enumerate(batches):
            scrip_codes = [s["scrip_code"] for s in b]
            sym_map = {s["scrip_code"]: s for s in b}
            candles_map = self.fetch_historical_daily_candles(scrip_codes)

            for code, candles in candles_map.items():
                stk = sym_map.get(code)
                if not stk:
                    continue
                bullish, details = self.is_bullish(candles)
                if bullish:
                    bullish_stocks.append({
                        "stock_meta": stk,
                        "bullish_details": details,
                    })

            if progress_callback:
                progress_callback(b_idx + 1, len(batches))
            time.sleep(0.15)  # Respect rate limit (5 req/sec limit)

        print(f"[+] Found {len(bullish_stocks)} stocks that are bullish for {self.consecutive_days} days straight!")
        print(f"[*] Fetching live Put option chains for the {len(bullish_stocks)} candidate stocks...")

        final_screened_results = []
        for item in bullish_stocks:
            stk = item["stock_meta"]
            b_details = item["bullish_details"]
            sym = stk["symbol"]
            sec_id = stk["nse_security_id"]
            exp = stk.get("nearest_expiry")
            lot = stk.get("lot_size", 1)

            spot_ltp, eligible_puts, atm_info = self.fetch_option_chain_puts(sec_id, exp, lot, strike_count=15)
            time.sleep(0.2)  # rate limit compliance

            if eligible_puts:
                # The closest eligible put is the one with the highest strike (closest to ATM/spot)
                nearest_put = eligible_puts[0]
                final_screened_results.append({
                    "symbol": sym,
                    "company_name": stk["company_name"],
                    "spot_ltp": spot_ltp,
                    "lot_size": lot,
                    "expiry": exp,
                    "bullish_gain_pct": b_details["net_gain_pct"],
                    "bullish_streak_days": b_details["streak_days"],
                    "daily_closes": b_details["daily_closes"],
                    "daily_changes_pct": b_details["daily_changes_pct"],
                    "atm_strike": atm_info.get("strike"),
                    "atm_put_price": atm_info.get("put_price"),
                    "atm_lot_cost": atm_info.get("lot_cost"),
                    "atm_meets_filter": atm_info.get("meets_criteria", False),
                    "best_put_strike": nearest_put["strike"],
                    "best_put_premium": nearest_put["put_price"],
                    "best_put_lot_cost": nearest_put["lot_cost"],
                    "best_put_otm_pct": nearest_put["distance_from_spot_pct"],
                    "best_put_trading_symbol": nearest_put["trading_symbol"],
                    "best_put_oi": nearest_put["oi"],
                    "best_put_volume": nearest_put["volume"],
                    "best_put_iv": nearest_put["iv"],
                    "best_put_delta": nearest_put["delta"],
                    "best_put_breakeven": nearest_put["breakeven_price"],
                    "total_eligible_put_strikes": len(eligible_puts),
                    "all_eligible_puts": eligible_puts,
                })

        # Sort results by bullish gain descending
        final_screened_results.sort(key=lambda x: x["bullish_gain_pct"], reverse=True)

        return {
            "screen_timestamp": datetime.now().isoformat(),
            "criteria": {
                "consecutive_bullish_days": self.consecutive_days,
                "bullish_mode": self.bullish_mode,
                "max_put_premium_inr": self.max_put_premium,
                "max_lot_investment_inr": self.max_lot_investment,
            },
            "total_fno_stocks_scanned": total_stocks,
            "total_bullish_stocks_found": len(bullish_stocks),
            "qualifying_stocks_count": len(final_screened_results),
            "results": final_screened_results,
        }

    def save_results(
        self,
        screen_data: Dict[str, Any],
        json_path: str = OUTPUT_JSON,
        csv_path: str = OUTPUT_CSV,
    ):
        """Save screened results to JSON and CSV."""
        # 1. JSON
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(screen_data, f, indent=2)
        print(f"[+] Saved screened results to JSON: {json_path}")

        # 2. CSV
        results = screen_data.get("results", [])
        fieldnames = [
            "symbol",
            "company_name",
            "spot_ltp",
            "lot_size",
            "expiry",
            "bullish_gain_pct",
            "bullish_streak_days",
            "best_put_strike",
            "best_put_premium",
            "best_put_lot_cost",
            "best_put_otm_pct",
            "best_put_trading_symbol",
            "best_put_oi",
            "best_put_volume",
            "best_put_iv",
            "best_put_delta",
            "best_put_breakeven",
            "atm_strike",
            "atm_put_price",
            "atm_lot_cost",
            "atm_meets_filter",
            "total_eligible_put_strikes",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"[+] Saved screened results to CSV: {csv_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Filter F&O stocks that are bullish for 5 days straight with Put premium < 20 and 1-lot cost <= 5000 INR."
    )
    parser.add_argument("--days", type=int, default=5, help="Consecutive bullish days (default: 5)")
    parser.add_argument("--max-premium", type=float, default=20.0, help="Maximum Put option price (default: 20.0)")
    parser.add_argument("--max-lot-cost", type=float, default=5000.0, help="Maximum 1 lot investment cost (default: 5000.0)")
    parser.add_argument(
        "--mode",
        choices=["higher_closes", "green_candles", "either", "both"],
        default="higher_closes",
        help="Bullish definition (default: higher_closes)",
    )
    args = parser.parse_args()

    scanner = BullishPutFilter(
        consecutive_days=args.days,
        max_put_premium=args.max_premium,
        max_lot_investment=args.max_lot_cost,
        bullish_mode=args.mode,
    )

    data = scanner.run_screen()
    scanner.save_results(data)

    results = data["results"]
    print("\n" + "=" * 115)
    print(f"🎯 SCREEN RESULTS: 5-Day Bullish Stocks with Cheap Put Options (Premium < ₹{args.max_premium}, 1 Lot <= ₹{args.max_lot_cost:,.0f})")
    print("=" * 115)
    print(
        f"{'Symbol':<12} | {'Spot LTP':>9} | {'Lot':>5} | {'5D Gain %':>9} | "
        f"{'Best PE Strike':>14} | {'PE Premium':>10} | {'1-Lot Cost':>11} | {'OTM %':>7} | {'PE OI':>10}"
    )
    print("-" * 115)

    for r in results:
        sym = r["symbol"]
        spot = f"₹{r['spot_ltp']:,.1f}"
        lot = r["lot_size"]
        gain = f"+{r['bullish_gain_pct']:.2f}%"
        pe_strk = f"{r['best_put_strike']} PE"
        pe_prem = f"₹{r['best_put_premium']:.2f}"
        lot_cost = f"₹{r['best_put_lot_cost']:,.2f}"
        otm = f"{r['best_put_otm_pct']:.1f}%"
        oi = f"{r['best_put_oi']:,}"
        print(f"{sym:<12} | {spot:>9} | {lot:>5} | {gain:>9} | {pe_strk:>14} | {pe_prem:>10} | {lot_cost:>11} | {otm:>7} | {oi:>10}")

    print("-" * 115)
    print(f"Total Qualifying Stocks: {len(results)} out of {data['total_bullish_stocks_found']} bullish candidates ({data['total_fno_stocks_scanned']} total F&O universe)")
    print(f"Full details written to:\n  • {OUTPUT_JSON}\n  • {OUTPUT_CSV}\n")


if __name__ == "__main__":
    main()
