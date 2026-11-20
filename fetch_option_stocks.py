#!/usr/bin/env python3
"""
fetch_option_stocks.py
======================
Generates and maintains the master list of Indian stocks & indices that have
options enabled (Call and Put contracts), powered by the INDstocks (INDmoney) API.

Reference: assets/indstocks-api-docs.md
Endpoints used:
  - GET /market/instruments?source=fno     (F&O instruments: OPTSTK, OPTIDX, FUTSTK, FUTIDX)
  - GET /market/instruments?source=equity  (Cash equity master: NSE/BSE security IDs, ISIN)
  - GET /market/instruments?source=index   (Index master: NIFTY 50, BANK NIFTY, SENSEX, etc.)
  - GET /market/option-chain               (Live option chain verification)
  - GET /market/quotes/ltp                 (Live LTP verification)
"""

import os
import sys
import csv
import io
import json
import argparse
from datetime import datetime
from collections import defaultdict
from typing import Dict, Any, List, Optional
import requests
from dotenv import dotenv_values, load_dotenv

# Base directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

# Output paths
DEFAULT_STOCKS_JSON = os.path.join(ASSETS_DIR, "stocks_with_options.json")
DEFAULT_STOCKS_CSV = os.path.join(ASSETS_DIR, "stocks_with_options.csv")
DEFAULT_INDICES_JSON = os.path.join(ASSETS_DIR, "indices_with_options.json")
DEFAULT_INDICES_CSV = os.path.join(ASSETS_DIR, "indices_with_options.csv")
EQUITY_MASTER_CACHE = os.path.join(ASSETS_DIR, "indstocks_equity_master.csv")
FNO_MASTER_CACHE = os.path.join(ASSETS_DIR, "indstocks_fno_master.csv")
INDEX_MASTER_CACHE = os.path.join(ASSETS_DIR, "indstocks_index_master.csv")

# Known symbol mappings between F&O underlying and Cash Equity symbols
FNO_TO_CASH_SYMBOL_OVERRIDES = {
    "ICICILIFE": "ICICIPRULI",
}


def get_indmoney_token() -> str:
    """Retrieve INDstocks API token from environment or .env."""
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
        raise ValueError(
            "INDstocks API token not found! Please set INDMONEY_API_TOKEN in .env or environment."
        )
    return token


class IndstocksOptionScanner:
    """Scanner for discovering and extracting options-enabled stocks and indices."""

    BASE_URL = "https://api.indstocks.com"

    def __init__(self, token: Optional[str] = None):
        self.token = token or get_indmoney_token()
        self.headers = {
            "Authorization": self.token,
            "Accept": "application/json",
        }

    def fetch_master_csv(self, source: str, cache_path: Optional[str] = None, force_refresh: bool = False) -> str:
        """Download instrument CSV for the given source (equity, fno, index) with local caching."""
        if not force_refresh and cache_path and os.path.exists(cache_path) and os.path.getsize(cache_path) > 1000:
            print(f"[*] Loading cached {source} master from {os.path.basename(cache_path)}...")
            with open(cache_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()

        url = f"{self.BASE_URL}/market/instruments?source={source}"
        print(f"[*] Downloading {source} instrument master from INDstocks API ({url})...")
        r = requests.get(url, headers={"Authorization": self.token}, timeout=60)
        r.raise_for_status()

        csv_text = r.text
        if cache_path and len(csv_text) > 1000:
            with open(cache_path, "w", encoding="utf-8") as f:
                f.write(csv_text)
            print(f"[*] Saved {source} master to {os.path.basename(cache_path)} ({len(csv_text) / (1024*1024):.2f} MB)")

        return csv_text

    def load_equity_mapping(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Build mapping from Cash Trading Symbol -> {
            'nse_security_id': str,
            'bse_security_id': str,
            'company_name': str,
            'isin': str,
            'tick_size': float
        }
        """
        csv_text = self.fetch_master_csv("equity", EQUITY_MASTER_CACHE, force_refresh=force_refresh)
        reader = csv.DictReader(io.StringIO(csv_text))

        equity_map: Dict[str, Dict[str, Any]] = {}
        for row in reader:
            sym = row.get("TRADING_SYMBOL", "").strip().upper()
            if not sym:
                continue

            exch = row.get("EXCH", "").strip().upper()
            sec_id = row.get("SECURITY_ID", "").strip()
            series = row.get("SERIES", "").strip().upper()
            comp = row.get("SYMBOL_NAME", "").strip()
            isin = row.get("ISIN", "").strip()
            try:
                tick = float(row.get("TICK_SIZE", 0.05)) / 100.0  # tick in paise converted to Rs if integer
                if tick <= 0:
                    tick = 0.05
            except Exception:
                tick = 0.05

            if sym not in equity_map:
                equity_map[sym] = {
                    "nse_security_id": None,
                    "bse_security_id": None,
                    "company_name": comp,
                    "isin": isin,
                    "tick_size": tick,
                }

            if exch == "NSE" and (series == "EQ" or not equity_map[sym]["nse_security_id"]):
                equity_map[sym]["nse_security_id"] = sec_id
                if comp:
                    equity_map[sym]["company_name"] = comp
                if isin:
                    equity_map[sym]["isin"] = isin
            elif exch == "BSE" and (series in ("A", "B", "T", "EQ", "") or not equity_map[sym]["bse_security_id"]):
                equity_map[sym]["bse_security_id"] = sec_id
                if not equity_map[sym]["company_name"] and comp:
                    equity_map[sym]["company_name"] = comp
                if not equity_map[sym]["isin"] and isin:
                    equity_map[sym]["isin"] = isin

        return equity_map

    def load_index_mapping(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Build mapping from Index Name / Symbol -> {
            'nse_security_id': str,
            'bse_security_id': str,
            'exchange': str
        }
        """
        csv_text = self.fetch_master_csv("index", INDEX_MASTER_CACHE, force_refresh=force_refresh)
        reader = csv.reader(io.StringIO(csv_text))
        header = next(reader, None)

        index_map: Dict[str, Dict[str, Any]] = {}
        for row in reader:
            if len(row) < 3:
                continue
            exch = row[0].strip().upper()
            idx_name = row[1].strip()
            sec_id = row[2].strip()

            norm_name = idx_name.upper().replace(" ", "").replace("&", "")
            index_map[norm_name] = {
                "name": idx_name,
                "exchange": exch,
                "security_id": sec_id,
            }

        return index_map

    def scan_options_instruments(
        self, force_refresh_fno: bool = False, force_refresh_equity: bool = False
    ) -> Dict[str, Any]:
        """
        Parses all F&O instruments and extracts:
          - stocks: list of stock option metadata dictionaries
          - indices: list of index option metadata dictionaries
        """
        equity_map = self.load_equity_mapping(force_refresh=force_refresh_equity)
        index_map = self.load_index_mapping()

        fno_csv = self.fetch_master_csv("fno", FNO_MASTER_CACHE, force_refresh=force_refresh_fno)
        reader = csv.DictReader(io.StringIO(fno_csv))

        stocks_data = defaultdict(lambda: {
            "company_name": "",
            "lot_size": None,
            "freeze_qty": None,
            "tick_size": 0.05,
            "has_call": False,
            "has_put": False,
            "expiries": set(),
            "strikes": set(),
            "ce_contracts": 0,
            "pe_contracts": 0,
            "total_contracts": 0,
            "exchanges": set(),
        })

        indices_data = defaultdict(lambda: {
            "company_name": "",
            "lot_size": None,
            "freeze_qty": None,
            "tick_size": 0.05,
            "has_call": False,
            "has_put": False,
            "expiries": set(),
            "strikes": set(),
            "ce_contracts": 0,
            "pe_contracts": 0,
            "total_contracts": 0,
            "exchanges": set(),
        })

        total_fno_rows = 0
        total_optstk_rows = 0
        total_optidx_rows = 0

        for row in reader:
            total_fno_rows += 1
            itype = row.get("INSTRUMENT_NAME", "").strip()
            if itype not in ("OPTSTK", "OPTIDX"):
                continue

            ts = row.get("TRADING_SYMBOL", "").strip()
            parts = ts.split("-")
            # Format: SYMBOL-EXPIRY-STRIKE-OPTION_TYPE, where SYMBOL can contain hyphens (e.g., BAJAJ-AUTO, NAM-INDIA)
            if len(parts) < 4:
                continue
            sym = "-".join(parts[:-3]).strip().upper()

            comp = row.get("UNDERLYING_SCRIP_NAME", "").strip()
            opt_type = row.get("OPTION_TYPE", "").strip().upper()
            expiry_raw = row.get("EXPIRY_DATE", "").strip()
            exch = row.get("EXCH", "").strip().upper()
            lot_raw = row.get("LOT_UNITS", "").strip()
            freeze_raw = row.get("FREEZE_QTY", "").strip()
            strike_raw = row.get("STRIKE_PRICE", "").strip()
            tick_raw = row.get("TICK_SIZE", "").strip()

            # Parse expiry date into standard YYYY-MM-DD
            expiry_str = ""
            if expiry_raw:
                try:
                    expiry_str = datetime.strptime(expiry_raw, "%m/%d/%Y %H:%M").strftime("%Y-%m-%d")
                except Exception:
                    try:
                        expiry_str = datetime.strptime(expiry_raw.split()[0], "%Y-%m-%d").strftime("%Y-%m-%d")
                    except Exception:
                        expiry_str = expiry_raw.split()[0]

            # Parse strike price
            strike_val = 0.0
            if strike_raw:
                try:
                    strike_val = float(strike_raw)
                except Exception:
                    pass

            target_dict = stocks_data[sym] if itype == "OPTSTK" else indices_data[sym]

            if itype == "OPTSTK":
                total_optstk_rows += 1
            else:
                total_optidx_rows += 1

            if comp and not target_dict["company_name"]:
                target_dict["company_name"] = comp
            if lot_raw and target_dict["lot_size"] is None:
                try:
                    target_dict["lot_size"] = int(lot_raw)
                except Exception:
                    pass
            if freeze_raw and target_dict["freeze_qty"] is None:
                try:
                    target_dict["freeze_qty"] = int(freeze_raw)
                except Exception:
                    pass
            if tick_raw:
                try:
                    # Tick in paise / integer
                    t = float(tick_raw)
                    target_dict["tick_size"] = t / 100.0 if t >= 1.0 else t
                except Exception:
                    pass

            target_dict["exchanges"].add(exch)
            if opt_type == "CE":
                target_dict["has_call"] = True
                target_dict["ce_contracts"] += 1
            elif opt_type == "PE":
                target_dict["has_put"] = True
                target_dict["pe_contracts"] += 1

            if expiry_str:
                target_dict["expiries"].add(expiry_str)
            if strike_val > 0:
                target_dict["strikes"].add(strike_val)
            target_dict["total_contracts"] += 1

        # Format stock option list
        formatted_stocks = []
        for sym, d in sorted(stocks_data.items()):
            cash_sym = FNO_TO_CASH_SYMBOL_OVERRIDES.get(sym, sym)
            eq_info = equity_map.get(cash_sym, {})

            nse_sec_id = eq_info.get("nse_security_id")
            bse_sec_id = eq_info.get("bse_security_id")
            isin = eq_info.get("isin", "")
            company_name = eq_info.get("company_name") or d["company_name"] or sym

            sorted_expiries = sorted(list(d["expiries"]))
            sorted_strikes = sorted(list(d["strikes"]))
            min_strike = sorted_strikes[0] if sorted_strikes else 0.0
            max_strike = sorted_strikes[-1] if sorted_strikes else 0.0

            formatted_stocks.append({
                "symbol": sym,
                "cash_trading_symbol": cash_sym,
                "company_name": company_name,
                "isin": isin,
                "lot_size": d["lot_size"],
                "freeze_qty": d["freeze_qty"],
                "tick_size": d["tick_size"],
                "options_enabled": True,
                "has_call": d["has_call"],
                "has_put": d["has_put"],
                "total_contracts": d["total_contracts"],
                "ce_contracts": d["ce_contracts"],
                "pe_contracts": d["pe_contracts"],
                "expiries_count": len(sorted_expiries),
                "upcoming_expiries": sorted_expiries,
                "nearest_expiry": sorted_expiries[0] if sorted_expiries else "",
                "strike_count": len(sorted_strikes),
                "min_strike": min_strike,
                "max_strike": max_strike,
                "nse_security_id": nse_sec_id,
                "bse_security_id": bse_sec_id,
                "scrip_code": f"NSE_{nse_sec_id}" if nse_sec_id else "",
                "exchanges": sorted(list(d["exchanges"])),
            })

        # Format index option list
        index_alias = {
            "NIFTY": "NIFTY50",
            "BANKNIFTY": "BANKNIFTY",
            "FINNIFTY": "NIFTYFINANCIAL",
            "MIDCPNIFTY": "NIFTYMIDCAPSEL",
            "NIFTYNXT50": "NIFTYNEXT50",
            "SENSEX": "SENSEX",
            "BANKEX": "BSEBANKEX",
            "FOCIT": "BSEFOCUSEDIT",
        }

        formatted_indices = []
        for sym, d in sorted(indices_data.items()):
            sorted_expiries = sorted(list(d["expiries"]))
            sorted_strikes = sorted(list(d["strikes"]))
            min_strike = sorted_strikes[0] if sorted_strikes else 0.0
            max_strike = sorted_strikes[-1] if sorted_strikes else 0.0

            # Match index security id
            lookup_key = index_alias.get(sym, sym).upper()
            idx_info = index_map.get(lookup_key, {})
            if not idx_info:
                # search partial
                for k, v in index_map.items():
                    if sym in k or k in sym:
                        idx_info = v
                        break

            sec_id = idx_info.get("security_id", "")
            idx_exch = idx_info.get("exchange", "NSE")

            formatted_indices.append({
                "symbol": sym,
                "name": idx_info.get("name") or d["company_name"] or sym,
                "security_id": sec_id,
                "scrip_code": f"{idx_exch}_{sec_id}" if sec_id else "",
                "lot_size": d["lot_size"],
                "freeze_qty": d["freeze_qty"],
                "options_enabled": True,
                "has_call": d["has_call"],
                "has_put": d["has_put"],
                "total_contracts": d["total_contracts"],
                "ce_contracts": d["ce_contracts"],
                "pe_contracts": d["pe_contracts"],
                "expiries_count": len(sorted_expiries),
                "upcoming_expiries": sorted_expiries,
                "nearest_expiry": sorted_expiries[0] if sorted_expiries else "",
                "strike_count": len(sorted_strikes),
                "min_strike": min_strike,
                "max_strike": max_strike,
                "exchanges": sorted(list(d["exchanges"])),
            })

        return {
            "timestamp": datetime.now().isoformat(),
            "total_fno_rows_parsed": total_fno_rows,
            "total_optstk_contracts": total_optstk_rows,
            "total_optidx_contracts": total_optidx_rows,
            "stocks_count": len(formatted_stocks),
            "indices_count": len(formatted_indices),
            "stocks": formatted_stocks,
            "indices": formatted_indices,
        }

    def save_outputs(
        self,
        scan_result: Dict[str, Any],
        stocks_json_path: str = DEFAULT_STOCKS_JSON,
        stocks_csv_path: str = DEFAULT_STOCKS_CSV,
        indices_json_path: str = DEFAULT_INDICES_JSON,
        indices_csv_path: str = DEFAULT_INDICES_CSV,
    ):
        """Save results to JSON and CSV files."""
        # 1. Stocks JSON
        stocks = scan_result["stocks"]
        with open(stocks_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": scan_result["timestamp"],
                "source": "INDstocks API (/market/instruments?source=fno)",
                "total_stocks_with_options": len(stocks),
                "stocks": stocks,
            }, f, indent=2)
        print(f"[+] Saved {len(stocks)} option-enabled stocks to JSON: {stocks_json_path}")

        # 2. Stocks CSV
        csv_headers = [
            "symbol",
            "cash_trading_symbol",
            "company_name",
            "lot_size",
            "has_call",
            "has_put",
            "total_contracts",
            "ce_contracts",
            "pe_contracts",
            "expiries_count",
            "nearest_expiry",
            "upcoming_expiries",
            "strike_count",
            "min_strike",
            "max_strike",
            "tick_size",
            "freeze_qty",
            "nse_security_id",
            "bse_security_id",
            "scrip_code",
            "isin",
        ]
        with open(stocks_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=csv_headers, extrasaction="ignore")
            writer.writeheader()
            for s in stocks:
                row = dict(s)
                row["upcoming_expiries"] = ";".join(s.get("upcoming_expiries", []))
                writer.writerow(row)
        print(f"[+] Saved {len(stocks)} option-enabled stocks to CSV: {stocks_csv_path}")

        # 3. Indices JSON & CSV
        indices = scan_result["indices"]
        with open(indices_json_path, "w", encoding="utf-8") as f:
            json.dump({
                "generated_at": scan_result["timestamp"],
                "total_indices_with_options": len(indices),
                "indices": indices,
            }, f, indent=2)
        print(f"[+] Saved {len(indices)} option-enabled indices to JSON: {indices_json_path}")

        idx_headers = [
            "symbol",
            "name",
            "security_id",
            "scrip_code",
            "lot_size",
            "has_call",
            "has_put",
            "total_contracts",
            "expiries_count",
            "nearest_expiry",
            "upcoming_expiries",
            "strike_count",
            "min_strike",
            "max_strike",
        ]
        with open(indices_csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=idx_headers, extrasaction="ignore")
            writer.writeheader()
            for idx in indices:
                row = dict(idx)
                row["upcoming_expiries"] = ";".join(idx.get("upcoming_expiries", []))
                writer.writerow(row)
        print(f"[+] Saved {len(indices)} option-enabled indices to CSV: {indices_csv_path}")

    def fetch_live_option_chain(
        self, symbol: str, expiry: Optional[str] = None, strike_count: int = 5
    ) -> Dict[str, Any]:
        """Fetch live option chain from INDstocks API for a stock symbol."""
        # Find the stock
        stocks_data = self.get_saved_stocks()
        stock = next((s for s in stocks_data if s["symbol"] == symbol.upper() or s["cash_trading_symbol"] == symbol.upper()), None)
        if not stock:
            return {"status": "error", "message": f"Symbol '{symbol}' not found in optionable stocks."}

        sec_id = stock.get("nse_security_id")
        if not sec_id:
            return {"status": "error", "message": f"No NSE cash security ID found for '{symbol}'"}

        exp = expiry or stock.get("nearest_expiry")
        if not exp:
            return {"status": "error", "message": f"No expiry found for '{symbol}'"}

        url = (
            f"{self.BASE_URL}/market/option-chain"
            f"?exchange=NSE&segment=EQUITY&underlying-scrip={sec_id}&expiry={exp}&strike_count={strike_count}"
        )
        r = requests.get(url, headers=self.headers, timeout=10)
        return r.json()

    @staticmethod
    def get_saved_stocks(json_path: str = DEFAULT_STOCKS_JSON) -> List[Dict[str, Any]]:
        """Load the generated stock list."""
        if os.path.exists(json_path):
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("stocks", [])
        return []


def main():
    parser = argparse.ArgumentParser(description="Fetch and list stocks with options enabled via INDstocks API.")
    parser.add_argument("--refresh-fno", action="store_true", help="Force fresh download of F&O master CSV")
    parser.add_argument("--refresh-equity", action="store_true", help="Force fresh download of Equity master CSV")
    parser.add_argument("--search", type=str, help="Search for a specific stock symbol and display details")
    parser.add_argument("--chain", type=str, help="Fetch live option chain for the specified symbol")
    parser.add_argument("--expiry", type=str, help="Expiry date for --chain (YYYY-MM-DD)")
    parser.add_argument("--strikes", type=int, default=5, help="Number of strikes around ATM for option chain")
    args = parser.parse_args()

    scanner = IndstocksOptionScanner()

    if args.search:
        stocks = scanner.get_saved_stocks()
        if not stocks:
            print("[*] No saved stocks found. Running scan first...")
            result = scanner.scan_options_instruments()
            scanner.save_outputs(result)
            stocks = result["stocks"]

        matches = [s for s in stocks if args.search.upper() in s["symbol"] or args.search.upper() in s["company_name"].upper()]
        if not matches:
            print(f"[-] No stock found matching '{args.search}'")
            return

        print(f"\n🔍 Found {len(matches)} matching stock(s):")
        for s in matches:
            print("-" * 60)
            print(f"Symbol:           {s['symbol']} (Cash: {s['cash_trading_symbol']})")
            print(f"Company:          {s['company_name']}")
            print(f"Lot Size:         {s['lot_size']} shares")
            print(f"Calls / Puts:     CE: {s['has_call']} ({s['ce_contracts']} contracts) | PE: {s['has_put']} ({s['pe_contracts']} contracts)")
            print(f"Total Contracts:  {s['total_contracts']}")
            print(f"Upcoming Expiries: {', '.join(s['upcoming_expiries'])}")
            print(f"Strike Range:     ₹{s['min_strike']} - ₹{s['max_strike']} ({s['strike_count']} strikes)")
            print(f"NSE Security ID:  {s['nse_security_id']} (Scrip Code: {s['scrip_code']})")
            print(f"ISIN:             {s['isin']}")
            print(f"Freeze Limit:     {s['freeze_qty']} qty")
        return

    if args.chain:
        print(f"[*] Fetching live Option Chain for {args.chain.upper()} (strike_count={args.strikes})...")
        res = scanner.fetch_live_option_chain(args.chain, expiry=args.expiry, strike_count=args.strikes)
        if res.get("status") == "success" and "data" in res:
            d = res["data"]
            print(f"\n✅ Underlying LTP: ₹{d.get('underlying_ltp')} | Expiry: {d.get('expiry')}")
            strikes = d.get("strikes", {})
            print(f"{'CE LTP':>10} | {'CE OI':>10} | {'CE IV':>8} | {'Strike':^10} | {'PE IV':>8} | {'PE OI':>10} | {'PE LTP':>10}")
            print("-" * 80)
            for strk, legs in sorted(strikes.items(), key=lambda x: float(x[0])):
                ce = legs.get("ce", {}) or {}
                pe = legs.get("pe", {}) or {}
                ce_ltp = f"₹{ce.get('ltp', 0):.2f}" if ce.get("ltp") is not None else "-"
                ce_oi = f"{ce.get('oi', 0):,}" if ce.get("oi") is not None else "-"
                ce_iv = f"{ce.get('implied_volatility', 0):.1f}%" if ce.get("implied_volatility") is not None else "-"
                pe_ltp = f"₹{pe.get('ltp', 0):.2f}" if pe.get("ltp") is not None else "-"
                pe_oi = f"{pe.get('oi', 0):,}" if pe.get("oi") is not None else "-"
                pe_iv = f"{pe.get('implied_volatility', 0):.1f}%" if pe.get("implied_volatility") is not None else "-"
                print(f"{ce_ltp:>10} | {ce_oi:>10} | {ce_iv:>8} | {strk:^10} | {pe_iv:>8} | {pe_oi:>10} | {pe_ltp:>10}")
        else:
            print("[-] Failed to fetch option chain:", res)
        return

    # Default action: run the complete scan and save files
    print("=" * 70)
    print("INDSTOCKS OPTIONS-ENABLED STOCKS SCANNER")
    print("=" * 70)
    result = scanner.scan_options_instruments(
        force_refresh_fno=args.refresh_fno,
        force_refresh_equity=args.refresh_equity,
    )
    scanner.save_outputs(result)

    print("\n" + "=" * 70)
    print("SCAN SUMMARY:")
    print(f"  • Total F&O Rows Parsed:       {result['total_fno_rows_parsed']:,}")
    print(f"  • Stock Option Contracts:      {result['total_optstk_contracts']:,}")
    print(f"  • Index Option Contracts:      {result['total_optidx_contracts']:,}")
    print(f"  • Stocks with Options Enabled: {result['stocks_count']}")
    print(f"  • Indices with Options Enabled:{result['indices_count']}")
    print("=" * 70)

    # Show top 10 sample stocks
    print("\nTop 10 Stocks with Options Enabled:")
    print(f"{'Symbol':<12} | {'Company Name':<30} | {'Lot':>6} | {'Expiries':>8} | {'Contracts':>9} | {'Strike Range':^22}")
    print("-" * 98)
    for s in result["stocks"][:10]:
        strike_range = f"₹{s['min_strike']:.0f} - ₹{s['max_strike']:.0f}"
        print(f"{s['symbol']:<12} | {s['company_name'][:30]:<30} | {s['lot_size']:>6} | {s['expiries_count']:>8} | {s['total_contracts']:>9} | {strike_range:^22}")
    print("-" * 98)
    print(f"\nAll {result['stocks_count']} stocks saved to:")
    print(f"  • JSON: {DEFAULT_STOCKS_JSON}")
    print(f"  • CSV:  {DEFAULT_STOCKS_CSV}")


if __name__ == "__main__":
    main()
