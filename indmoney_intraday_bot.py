"""
INDmoney Intraday Equity Bot Server & Execution Engine
======================================================
Strategy: 1-Minute EMA & VWAP Crossover Strategy
  - User-provided stock watchlist scanned continuously on 1m intraday candles.
  - Session-anchored VWAP calculated from today's open (09:15 IST).
  - Fast EMA (default 9-period) calculated on 1m Close.
  - Bearish Cross (Short / SELL): EMA crosses BELOW VWAP.
    * The 1m candle confirming the cross: that candle's HIGH is the Stop Loss (SL).
    * Minimum 1:2 Risk to Reward Target downward (Entry - 2 * Risk).
  - Bullish Cross (Long / BUY): EMA crosses ABOVE VWAP.
    * The 1m candle confirming the cross: that candle's LOW is the Stop Loss (SL).
    * Minimum 1:2 Risk to Reward Target upward (Entry + 2 * Risk).
  - Single intraday trade at a time (Max 1 active position).
  - Fixed ₹3,000 capital allocation with 5x MIS leverage (₹15,000 exposure).
  - Intraday 3:15 PM auto square-off.
"""

import argparse
import datetime
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import numpy as np
import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import vwap_ema_strategy as vwap_strategy

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from stock_tools import get_stock_data, _resolve_ticker
except ImportError:
    get_stock_data = None
    _resolve_ticker = lambda t: t + ".NS" if not (t.endswith(".NS") or t.endswith(".BO")) else t

try:
    from backtest_tools import INDSTOCKS_SECURITY_IDS, resolve_indstocks_scrip
except ImportError:
    INDSTOCKS_SECURITY_IDS = {
        "RELIANCE": "NSE_2885", "TCS": "NSE_11536", "HDFCBANK": "NSE_1333",
        "INFY": "NSE_1594", "ICICIBANK": "NSE_4963", "SBIN": "NSE_3045",
        "BHARTIARTL": "NSE_10604", "TATAMOTORS": "NSE_3456", "LT": "NSE_11483",
        "BAJFINANCE": "NSE_317", "MARUTI": "NSE_10999", "TITAN": "NSE_3506",
        "AXISBANK": "NSE_5900", "SUNPHARMA": "NSE_3351", "WIPRO": "NSE_3787",
        "HCLTECH": "NSE_7229", "ADANIENT": "NSE_25", "TRENT": "NSE_1964",
    }
    def resolve_indstocks_scrip(ticker: str, api_key: Optional[str] = None) -> Optional[str]:
        c = ticker.replace(".NS", "").replace(".BO", "").strip().upper()
        return INDSTOCKS_SECURITY_IDS.get(c)

PORT = 9092
STATE_FILE = os.path.join(HERE, ".indmoney_bot_state.json")


class IndmoneyClient:
    """INDmoney / INDstocks REST API Client per assets/indstocks-api-docs.md."""

    BASE_URL = "https://api.indstocks.com"

    def __init__(self, token: Optional[str] = None):
        self.token = (token or os.environ.get("INDMONEY_ACCESS_TOKEN", "") or os.environ.get("INDSTOCKS_TOKEN", "")).strip()

    def set_token(self, token: str):
        self.token = token.strip()

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": self.token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def get_funds(self) -> Dict[str, Any]:
        """Call GET /funds to retrieve live account data balance & margin."""
        if not self.token:
            return {"status": "error", "message": "No INDmoney access token configured"}
        try:
            url = f"{self.BASE_URL}/funds"
            r = requests.get(url, headers=self._headers(), timeout=8)
            if r.status_code == 200:
                res = r.json()
                if res.get("status") == "success" and "data" in res:
                    d = res["data"]
                    detailed = d.get("detailed_avl_balance", {})
                    avl = detailed.get("eq_mis", detailed.get("eq_cnc", d.get("withdrawal_balance", 0.0)))
                    sod = float(d.get("sod_balance", 0.0))
                    return {
                        "status": "success",
                        "connected": True,
                        "source": "INDmoney Live API",
                        "sod_balance": sod,
                        "available_balance": float(avl),
                        "utilized_margin": max(0.0, sod - float(avl)),
                        "realized_pnl": float(d.get("realized_pnl", 0.0)),
                        "unrealized_pnl": float(d.get("unrealized_pnl", 0.0)),
                        "withdrawal_balance": float(d.get("withdrawal_balance", 0.0)),
                    }
                return {"status": "error", "message": res.get("message", "API response error")}
            return {"status": "error", "message": f"HTTP {r.status_code}: {r.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def place_order(
        self,
        symbol: str,
        txn_type: str,
        qty: int,
        limit_price: float,
        product: str = "INTRADAY",
    ) -> Dict[str, Any]:
        """Place an Intraday Equity order via POST /order."""
        if not self.token:
            return {"status": "error", "message": "No INDmoney access token configured"}
        sec_code = resolve_indstocks_scrip(symbol, api_key=self.token)
        if not sec_code:
            sec_code = INDSTOCKS_SECURITY_IDS.get(symbol.upper(), "2885")
        sec_id = sec_code.split("_")[-1] if "_" in sec_code else sec_code

        payload = {
            "txn_type": txn_type.upper(),
            "exchange": "NSE",
            "segment": "EQUITY",
            "product": product.upper(),
            "order_type": "LIMIT",
            "limit_price": round(float(limit_price), 2),
            "validity": "DAY",
            "security_id": str(sec_id),
            "qty": int(qty),
            "is_amo": False,
            "algo_id": "99999",
            "remarks": "friday-atr-bot",
        }
        try:
            url = f"{self.BASE_URL}/order"
            r = requests.post(url, headers=self._headers(), json=payload, timeout=8)
            res = r.json()
            if r.status_code in (200, 201) and res.get("status") == "success":
                return {"status": "success", "data": res.get("data", {})}
            return {"status": "error", "message": res.get("message", f"HTTP {r.status_code}"), "details": res}
        except Exception as e:
            return {"status": "error", "message": str(e)}


class BotEngine:
    """Intraday 1-Minute EMA & VWAP Crossover Engine — Single Trade (₹3,000 Capital, 5x MIS)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.client = IndmoneyClient()
        self.state: Dict[str, Any] = {}
        self._load_state()
        self.running_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_scan_results: Dict[str, Dict[str, Any]] = {}

    def _default_state(self) -> Dict[str, Any]:
        today_str = datetime.date.today().isoformat()
        return {
            "date": today_str,
            "token": "",
            "mode": "paper",  # "paper" or "live"
            "is_running": True,
            "strategy": "VWAP x EMA Cross | Smart Profit Trail",
            "sod_balance": 10000.0,
            "available_balance": 10000.0,
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "trade_capital": 3000.0,  # Exactly ₹3,000 capital
            "use_mis_leverage": True,  # 5x MIS leverage (₹15,000 position)
            "leverage": 5,
            "max_open_trades": 1,     # Single intraday trade strictly
            "ema_period": 9,          # 9-period Fast EMA
            "target_rr": 2.0,         # Minimum 1:2 Risk to Reward
            "trade_direction": "both", # "both", "short_only", "long_only"
            "trail_breakeven_pct": 1.0, # Move SL to Breakeven when profit reaches 1.0%
            # PineScript "VWAP x EMA Cross | Smart Profit Trail" settings
            "trail_mode": "EMA Trail",
            "use_partial": True,
            "trail_start_r": 1.0,
            "use_be": True,
            "atr_len": 14,
            "atr_mult": 2.0,
            "use_session": False,
            "trade_session": "0915-1500",
            "close_eod": True,
            "one_at_a_time": True,
            "auto_square_off_time": "15:15",
            "watchlist": [],          # Dynamic user-provided stocks
            "active_positions": [],   # Max 1 active trade
            "completed_trades": [],   # Trades closed today
            "traded_bars_today": [],  # Avoid duplicate re-entries on same bar
            "logs": [],
            "last_scan_time": None,
        }

    def fetch_top_buying_stocks(self) -> List[str]:
        """Fetch the top 5 buying stocks from Stock Dashboard News section or NIFTY 50 gainers."""
        try:
            r = requests.get("http://localhost:9090/api/top-buying-stocks", timeout=3)
            if r.status_code == 200:
                res = r.json()
                top_5 = res.get("top_5", [])
                if top_5 and len(top_5) >= 3:
                    return [s.upper().strip() for s in top_5[:5]]
        except Exception:
            pass

        try:
            tickers = [
                "DRREDDY.NS", "JSWSTEEL.NS", "HEROMOTOCO.NS", "BPCL.NS", "ADANIPORTS.NS",
                "KOTAKBANK.NS", "GRASIM.NS", "COALINDIA.NS", "RELIANCE.NS", "TCS.NS"
            ]
            df = yf.download(tickers, period="5d", progress=False)
            if not df.empty and "Close" in df:
                close = df["Close"]
                changes = []
                for t in tickers:
                    sym = t.replace(".NS", "")
                    if t in close:
                        c = close[t].dropna()
                        if len(c) >= 2:
                            pct = (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100
                            changes.append((sym, pct))
                changes.sort(key=lambda x: x[1], reverse=True)
                return [c[0] for c in changes[:5]]
        except Exception:
            pass

        return ["DRREDDY", "JSWSTEEL", "HEROMOTOCO", "BPCL", "ADANIPORTS"]

    def _load_state(self):
        today_str = datetime.date.today().isoformat()
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, "r") as f:
                    data = json.load(f)
                if data.get("date") != today_str:
                    data["date"] = today_str
                    data["realized_pnl"] = 0.0
                    data["unrealized_pnl"] = 0.0
                    data["utilized_margin"] = 0.0
                    data["active_positions"] = []
                    data["completed_trades"] = []
                    data["logs"] = [f"[SYSTEM] Rolled over to trading session: {today_str}"]
                self.state = data
            except Exception:
                self.state = self._default_state()
        else:
            self.state = self._default_state()

        # Enforce user constraints
        self.state["max_open_trades"] = 1
        self.state["trade_capital"] = 3000.0
        self.state["strategy"] = "VWAP x EMA Cross | Smart Profit Trail"
        self.state.setdefault("ema_period", 9)
        self.state.setdefault("target_rr", 2.0)
        self.state.setdefault("trade_direction", "both")
        self.state.setdefault("traded_bars_today", [])
        for key, value in vwap_strategy.DEFAULT_CONFIG.items():
            self.state.setdefault(key, value)
        if "watchlist" not in self.state:
            self.state["watchlist"] = []

        # Ensure Top 5 Buying Stocks from News section are present in the continuous scanner
        top_5 = self.fetch_top_buying_stocks()
        wl = self.state.setdefault("watchlist", [])
        added_any = False
        for s in top_5:
            if s not in wl:
                wl.append(s)
                added_any = True
        if added_any:
            self.log(f"[WATCHLIST SYNC] Added Top 5 Buying Stocks from Stock News: {', '.join(top_5)}")

        if self.state.get("token"):
            self.client.set_token(self.state["token"])

        self._save_state()

    def _save_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
        except Exception as e:
            print(f"Error saving bot state: {e}")

    def log(self, msg: str):
        ts = datetime.datetime.now().strftime("%H:%M:%S")
        entry = f"[{ts}] {msg}"
        with self.lock:
            self.state.setdefault("logs", []).append(entry)
            if len(self.state["logs"]) > 250:
                self.state["logs"] = self.state["logs"][-250:]
            self._save_state()
        print(entry)

    def get_market_status(self) -> Dict[str, Any]:
        """Check NSE market session (09:15 - 15:30 IST)."""
        now = datetime.datetime.now()
        weekday = now.weekday()
        is_weekday = weekday < 5

        current_mins = now.hour * 60 + now.minute
        open_mins = 9 * 60 + 15
        sq_mins = 15 * 60 + 15
        close_mins = 15 * 60 + 30

        if not is_weekday:
            status = "WEEKEND_CLOSED"
            mins_to_sq = 0
        elif current_mins < open_mins:
            status = "PRE_MARKET"
            mins_to_sq = sq_mins - current_mins
        elif current_mins >= close_mins:
            status = "POST_MARKET_CLOSED"
            mins_to_sq = 0
        elif current_mins >= sq_mins:
            status = "SQUARE_OFF_ZONE"
            mins_to_sq = 0
        else:
            status = "MARKET_OPEN"
            mins_to_sq = sq_mins - current_mins

        return {
            "status": status,
            "is_open": status in ("MARKET_OPEN", "SQUARE_OFF_ZONE"),
            "current_time": now.strftime("%H:%M:%S"),
            "current_date": now.strftime("%Y-%m-%d"),
            "minutes_to_square_off": max(0, mins_to_sq),
            "auto_square_off_time": self.state.get("auto_square_off_time", "15:15"),
        }

    def sync_balance(self) -> Dict[str, Any]:
        """Fetch balance from INDmoney live API or calculate paper wallet."""
        with self.lock:
            token = self.state.get("token")
            mode = self.state.get("mode", "paper")

        if mode == "live" and token:
            funds_res = self.client.get_funds()
            if funds_res.get("status") == "success":
                with self.lock:
                    self.state["sod_balance"] = funds_res["sod_balance"]
                    self.state["available_balance"] = funds_res["available_balance"]
                    self.state["utilized_margin"] = funds_res["utilized_margin"]
                    self.state["realized_pnl"] = funds_res["realized_pnl"]
                    self.state["unrealized_pnl"] = funds_res["unrealized_pnl"]
                    self._save_state()
                return funds_res

        # Paper ledger
        with self.lock:
            utilized = sum(pos.get("capital", 3000.0) for pos in self.state.get("active_positions", []))
            unrealized = sum(pos.get("floating_pnl", 0.0) for pos in self.state.get("active_positions", []))
            realized = self.state.get("realized_pnl", 0.0)
            sod = self.state.get("sod_balance", 10000.0)
            avail = max(0.0, sod + realized - utilized)

            self.state["utilized_margin"] = round(utilized, 2)
            self.state["unrealized_pnl"] = round(unrealized, 2)
            self.state["available_balance"] = round(avail, 2)
            self._save_state()

            return {
                "status": "success",
                "connected": bool(token),
                "source": "INDmoney Paper Ledger" if mode == "paper" else "INDmoney Account (Live Token Pending)",
                "sod_balance": sod,
                "available_balance": avail,
                "utilized_margin": utilized,
                "realized_pnl": realized,
                "unrealized_pnl": unrealized,
                "token_configured": bool(token),
            }

    def add_to_watchlist(self, raw_symbol: str) -> List[str]:
        """Add stock(s) to the continuous scanning watchlist."""
        symbols = [s.strip().upper().replace(".NS", "").replace(".BO", "") for s in raw_symbol.replace(",", " ").split() if s.strip()]
        with self.lock:
            current = self.state.setdefault("watchlist", [])
            added = []
            for s in symbols:
                if s and s not in current:
                    current.append(s)
                    added.append(s)
            self._save_state()
        if added:
            self.log(f"Added to continuous scan watchlist: {', '.join(added)}")
        return self.state.get("watchlist", [])

    def remove_from_watchlist(self, raw_symbol: str) -> List[str]:
        sym = raw_symbol.strip().upper().replace(".NS", "").replace(".BO", "")
        removed = False
        with self.lock:
            current = self.state.setdefault("watchlist", [])
            if sym in current:
                current.remove(sym)
                self._save_state()
                removed = True
        if removed:
            self.log(f"Removed {sym} from watchlist.")
        return self.state.get("watchlist", [])

    def clear_watchlist(self) -> List[str]:
        with self.lock:
            self.state["watchlist"] = []
            self._save_state()
        self.log("Watchlist cleared.")
        return []

    def check_ema_vwap_cross(self, symbol: str) -> Dict[str, Any]:
        """Analyze a stock on 1m candles for EMA & VWAP Crossover Strategy.
        
        Rules:
          1. Timeframe: 1-minute intraday candles from today's open (09:15 IST).
          2. VWAP: Anchored from session open (09:15 IST) using Typical Price (H+L+C)/3 * Vol.
          3. Fast EMA: 9-period EMA calculated on Close (configurable).
          4. Bearish Cross (Short / SELL):
             - Fast EMA crosses BELOW VWAP (prev_EMA >= prev_VWAP and curr_EMA < curr_VWAP).
             - The 1m candle that confirms the cross:
               * High of that confirming candle = Stop Loss (SL).
               * Close = Entry price.
               * Risk = High - Close.
               * Target = Close - (Risk * target_rr) (Minimum 1:2 R:R downward).
          5. Bullish Cross (Long / BUY):
             - Fast EMA crosses ABOVE VWAP (prev_EMA <= prev_VWAP and curr_EMA > curr_VWAP).
             - The 1m candle that confirms the cross:
               * Low of that confirming candle = Stop Loss (SL).
               * Close = Entry price.
               * Risk = Close - Low.
               * Target = Close + (Risk * target_rr) (Minimum 1:2 R:R upward).
        """
        resolved = _resolve_ticker(symbol)
        try:
            df = yf.download(resolved, period="2d", interval="1m", progress=False)
            if df is None or df.empty or len(df) < 10:
                return {"symbol": symbol, "status": "NO_DATA", "error": "Insufficient 1m candles"}

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            ema_period = int(self.state.get("ema_period", 9))
            target_rr = float(self.state.get("target_rr", 2.0))
            trade_dir = self.state.get("trade_direction", "both").lower()

            # Calculate continuous EMA and Wilder ATR across the full sequence
            df["EMA"] = df["Close"].ewm(span=ema_period, adjust=False).mean()
            atr_len = int(self.state.get("atr_len", 14))
            prev_close = df["Close"].shift(1)
            true_range = pd.concat([
                df["High"] - df["Low"],
                (df["High"] - prev_close).abs(),
                (df["Low"] - prev_close).abs(),
            ], axis=1).max(axis=1)
            df["ATR"] = true_range.ewm(alpha=1.0 / max(1, atr_len), adjust=False).mean()

            # Filter for today's intraday bars (starting at 09:15)
            dates = sorted(list(set(df.index.date)))
            today_date = dates[-1]
            today_bars = df[df.index.date == today_date].copy()
            if len(today_bars) < 3:
                return {"symbol": symbol, "status": "EARLY_SESSION", "error": "Fewer than 3 candles today"}

            # Calculate today's session anchored VWAP
            tp = (today_bars["High"] + today_bars["Low"] + today_bars["Close"]) / 3.0
            vol = today_bars["Volume"].clip(lower=1)
            today_bars["VWAP"] = (tp * vol).cumsum() / vol.cumsum()

            # Separate fully closed candles from current forming candle
            if len(today_bars) >= 2 and today_bars["Volume"].iloc[-1] == 0:
                closed_bars = today_bars.iloc[:-1]
                forming_bar = today_bars.iloc[-1]
            else:
                closed_bars = today_bars
                forming_bar = today_bars.iloc[-1]

            confirm_bar = closed_bars.iloc[-1]
            prior_bar = closed_bars.iloc[-2]

            curr_ema = float(confirm_bar["EMA"])
            curr_vwap = float(confirm_bar["VWAP"])
            prev_ema = float(prior_bar["EMA"])
            prev_vwap = float(prior_bar["VWAP"])

            ltp = float(forming_bar["Close"])
            c_time_str = confirm_bar.name.strftime("%H:%M")
            bar_date_str = confirm_bar.name.strftime("%Y-%m-%d %H:%M")

            # Check fresh crossover on the last completed bar
            is_bear_cross_now = (prev_ema >= prev_vwap) and (curr_ema < curr_vwap)
            is_bull_cross_now = (prev_ema <= prev_vwap) and (curr_ema > curr_vwap)

            # Also inspect last 3 bars for recent cross
            recent_cross_type = None
            recent_confirm_bar = None
            recent_bars = closed_bars.iloc[-4:]
            for i in range(1, len(recent_bars)):
                p = recent_bars.iloc[i-1]
                c = recent_bars.iloc[i]
                if (p["EMA"] >= p["VWAP"]) and (c["EMA"] < c["VWAP"]):
                    recent_cross_type = "BEARISH_CROSS"
                    recent_confirm_bar = c
                elif (p["EMA"] <= p["VWAP"]) and (c["EMA"] > c["VWAP"]):
                    recent_cross_type = "BULLISH_CROSS"
                    recent_confirm_bar = c

            if is_bear_cross_now:
                cross_type = "BEARISH_CROSS"
                active_confirm_bar = confirm_bar
                is_fresh = True
            elif is_bull_cross_now:
                cross_type = "BULLISH_CROSS"
                active_confirm_bar = confirm_bar
                is_fresh = True
            elif recent_cross_type:
                cross_type = recent_cross_type
                active_confirm_bar = recent_confirm_bar
                is_fresh = (active_confirm_bar.name == confirm_bar.name)
            else:
                cross_type = "NONE"
                active_confirm_bar = confirm_bar
                is_fresh = False

            conf_high = round(float(active_confirm_bar["High"]), 2)
            conf_low = round(float(active_confirm_bar["Low"]), 2)
            conf_close = round(float(active_confirm_bar["Close"]), 2)
            conf_open = round(float(active_confirm_bar["Open"]), 2)
            conf_time = active_confirm_bar.name.strftime("%H:%M")

            # Calculations based on cross type
            if cross_type == "BEARISH_CROSS":
                suggested_side = "SELL"
                suggested_sl = conf_high  # That candle's High will be our SL
                risk = round(suggested_sl - conf_close, 2)
                if risk <= 0.05:
                    risk = max(0.10, round(conf_close * 0.0008, 2))
                    suggested_sl = round(conf_close + risk, 2)
                suggested_target = round(conf_close - (risk * target_rr), 2)
                status_label = f"🔻 BEARISH CROSS CONFIRMED ({conf_time})"
            elif cross_type == "BULLISH_CROSS":
                suggested_side = "BUY"
                suggested_sl = conf_low  # That candle's Low will be our SL
                risk = round(conf_close - suggested_sl, 2)
                if risk <= 0.05:
                    risk = max(0.10, round(conf_close * 0.0008, 2))
                    suggested_sl = round(conf_close - risk, 2)
                suggested_target = round(conf_close + (risk * target_rr), 2)
                status_label = f"🟢 BULLISH CROSS CONFIRMED ({conf_time})"
            else:
                suggested_side = None
                risk = 0.0
                suggested_sl = conf_high if curr_ema < curr_vwap else conf_low
                suggested_target = 0.0
                if curr_ema > curr_vwap:
                    status_label = f"Bullish (9 EMA > VWAP by +₹{round(curr_ema - curr_vwap, 2)})"
                else:
                    status_label = f"Bearish (9 EMA < VWAP by -₹{round(curr_vwap - curr_ema, 2)})"

            # Check direction eligibility
            dir_allowed = True
            if suggested_side == "SELL" and trade_dir == "long_only":
                dir_allowed = False
            elif suggested_side == "BUY" and trade_dir == "short_only":
                dir_allowed = False

            is_trigger_eligible = (
                is_fresh
                and cross_type in ("BEARISH_CROSS", "BULLISH_CROSS")
                and dir_allowed
            )

            return {
                "symbol": symbol,
                "current_price": ltp,
                "candle_time": c_time_str,
                "bar_date_str": bar_date_str,
                "ema": round(curr_ema, 2),
                "vwap": round(curr_vwap, 2),
                "ema_period": ema_period,
                "spread": round(curr_ema - curr_vwap, 2),
                "confirm_candle_high": conf_high,
                "confirm_candle_low": conf_low,
                "confirm_candle_open": conf_open,
                "confirm_candle_close": conf_close,
                "confirm_candle_time": conf_time,
                "cross_type": cross_type,
                "is_fresh_cross": is_fresh,
                "is_trigger_eligible": is_trigger_eligible,
                "suggested_side": suggested_side,
                "suggested_sl": suggested_sl,
                "suggested_target": suggested_target,
                "risk": risk,
                "target_rr": target_rr,
                "status": status_label,
                # Live bar used by the PineScript-equivalent trailing engine
                "bar": {
                    "high": float(forming_bar["High"]),
                    "low": float(forming_bar["Low"]),
                    "close": ltp,
                    "ema": curr_ema,
                    "atr": float(confirm_bar.get("ATR") or 0.0),
                    "prev_low": float(prior_bar["Low"]),
                    "prev_high": float(prior_bar["High"]),
                },
            }
        except Exception as e:
            return {"symbol": symbol, "status": "ERROR", "error": str(e)}

    # Backwards compatibility alias
    check_atr_breakout = check_ema_vwap_cross

    def execute_trade(
        self,
        symbol: str,
        side: str,  # "BUY" or "SELL"
        entry_price: float,
        stop_loss: float,
        target: float,
        confirm_high: float,
        confirm_low: float,
        cross_time: str,
    ) -> Dict[str, Any]:
        """Execute single intraday trade (₹3,000 capital, 5x MIS leverage) for EMA-VWAP Crossover."""
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "")
        side = side.upper()
        with self.lock:
            active_count = len(self.state.get("active_positions", []))
            if active_count >= 1:
                return {"status": "error", "message": "A single intraday trade is already active. Max 1 trade allowed."}

            cap = float(self.state.get("trade_capital", 3000.0))
            use_mis = self.state.get("use_mis_leverage", True)
            leverage = int(self.state.get("leverage", 5)) if use_mis else 1
            mode = self.state.get("mode", "paper")
            token = self.state.get("token")
            target_rr = float(self.state.get("target_rr", 2.0))

        # Position sizing: ₹3,000 capital deployed with 5x MIS leverage (₹15,000 total exposure)
        total_exposure = cap * leverage
        qty = max(1, int(total_exposure / entry_price))
        actual_margin_blocked = round((qty * entry_price) / leverage, 2)

        risk_per_share = round(abs(stop_loss - entry_price), 2)
        total_risk_inr = round(risk_per_share * qty, 2)
        reward_per_share = round(abs(target - entry_price), 2)
        total_reward_inr = round(reward_per_share * qty, 2)

        trade_id = f"TRD-{side}-{symbol}-{int(time.time() * 1000) % 100000}"

        if mode == "live" and token:
            self.log(f"[LIVE] Transmitting order to INDmoney API: {side} {qty}x {symbol} @ ₹{entry_price:.2f} (Margin: ₹{actual_margin_blocked})...")
            order_res = self.client.place_order(
                symbol=symbol,
                txn_type=side,
                qty=qty,
                limit_price=entry_price,
                product="INTRADAY",
            )
            if order_res.get("status") != "success":
                self.log(f"[REJECTED] INDmoney order rejected: {order_res.get('message')}")
                return {"status": "error", "message": f"INDmoney rejected: {order_res.get('message')}"}
            broker_order_id = order_res.get("data", {}).get("order_id", trade_id)
        else:
            broker_order_id = f"PAPER-{trade_id}"

        sl_desc = f"Confirming Candle High (₹{confirm_high:.2f})" if side == "SELL" else f"Confirming Candle Low (₹{confirm_low:.2f})"

        position = {
            "id": trade_id,
            "broker_id": broker_order_id,
            "symbol": symbol,
            "side": side,  # "SELL" (Short) or "BUY" (Long)
            "qty": qty,
            "entry_price": float(entry_price),
            "current_price": float(entry_price),
            "highest_price": float(entry_price),
            "lowest_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "initial_stop_loss": float(stop_loss),
            "target_price": float(target),
            "target_rr": target_rr,
            "confirm_candle_high": float(confirm_high),
            "confirm_candle_low": float(confirm_low),
            "cross_time": cross_time,
            "risk_per_share": risk_per_share,
            "total_risk_inr": total_risk_inr,
            "total_reward_inr": total_reward_inr,
            "sl_description": sl_desc,
            "capital": actual_margin_blocked,
            "total_value": round(qty * entry_price, 2),
            "entry_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "floating_pnl": 0.0,
            "floating_pnl_pct": 0.0,
            "strategy": "VWAP x EMA Cross | Smart Profit Trail",
            "status": "OPEN",
            "is_breakeven": False,
            "is_trailing": False,
            "extreme_price": float(entry_price),
            "trail_on": False,
            "partial_done": False,
        }

        with self.lock:
            self.state["active_positions"] = [position]  # Strictly single trade
            self._save_state()

        self.log(f"[TRADE OPENED] {side} {qty}x {symbol} @ ₹{entry_price:.2f} | SL ({sl_desc}): ₹{stop_loss:.2f} | 1:{target_rr} TGT: ₹{target:.2f} (+₹{total_reward_inr:,.0f}) | Margin: ₹{actual_margin_blocked:.2f}")
        self.sync_balance()
        return {"status": "success", "position": position}

    def execute_single_bullish_trade(self, symbol: str, entry_price: float, stop_loss: float, target: float) -> Dict[str, Any]:
        """Backward compatibility helper."""
        return self.execute_trade(
            symbol=symbol,
            side="BUY",
            entry_price=entry_price,
            stop_loss=stop_loss,
            target=target,
            confirm_high=entry_price,
            confirm_low=stop_loss,
            cross_time=datetime.datetime.now().strftime("%H:%M"),
        )

    def partial_exit_position(self, reason: str = "50% booked at target") -> Dict[str, Any]:
        """Book 50% at the 1:2 target, keep the remaining runner on a trailing SL."""
        with self.lock:
            if not self.state.get("active_positions"):
                return {"status": "error", "message": "No active trade to book partial profit on."}
            pos = self.state["active_positions"][0]
            if pos.get("partial_done"):
                return {"status": "error", "message": "Partial profit already booked on this trade."}
            old_qty = int(pos["qty"])
            exit_qty = old_qty // 2
            if exit_qty < 1:
                return self.square_off_position(reason=reason)
            sym = pos["symbol"]
            side = pos.get("side", "BUY")
            entry_p = float(pos["entry_price"])
            stop_p = float(pos.get("stop_loss", entry_p))

        live_data = get_stock_data(sym) if get_stock_data else None
        exit_p = float(live_data["price"]) if live_data and live_data.get("price") else float(pos.get("current_price", entry_p))
        exit_txn = "SELL" if side == "BUY" else "BUY"
        pnl = round(((exit_p - entry_p) if side == "BUY" else (entry_p - exit_p)) * exit_qty, 2)

        if self.state.get("mode") == "live" and self.state.get("token"):
            self.log(f"[LIVE] Partial exit order: {exit_txn} {exit_qty}x {sym} @ ₹{exit_p:.2f}")
            self.client.place_order(symbol=sym, txn_type=exit_txn, qty=exit_qty,
                                    limit_price=exit_p, product="INTRADAY")

        remaining = old_qty - exit_qty
        with self.lock:
            if not self.state.get("active_positions"):
                return {"status": "error", "message": "Trade disappeared before partial exit."}
            live_pos = self.state["active_positions"][0]
            live_pos["qty"] = remaining
            live_pos["partial_done"] = True
            live_pos["capital"] = round(float(live_pos.get("capital", 0.0)) * remaining / old_qty, 2)
            live_pos["total_value"] = round(remaining * exit_p, 2)
            live_pos["current_price"] = exit_p
            risk = float(live_pos.get("risk_per_share") or max(0.05, entry_p * 0.001))
            # Runner has no fixed limit in PineScript — park the target far away.
            live_pos["target_price"] = round(entry_p + (1000 * risk if side == "BUY" else -1000 * risk), 2)
            self.state["realized_pnl"] = round(self.state.get("realized_pnl", 0.0) + pnl, 2)
            self.state.setdefault("completed_trades", []).append({
                "id": pos.get("id"), "symbol": sym, "side": side, "qty": exit_qty,
                "entry_price": entry_p, "exit_price": exit_p,
                "stop_loss": stop_p, "target_price": pos.get("target_price", 0.0),
                "entry_time": pos.get("entry_time"),
                "exit_time": datetime.datetime.now().strftime("%H:%M:%S"),
                "pnl": pnl, "pnl_pct": round(((exit_p - entry_p) / entry_p) * 100, 2)
                             if side == "BUY" else round(((entry_p - exit_p) / entry_p) * 100, 2),
                "reason": reason, "strategy": live_pos.get("strategy", "VWAP x EMA Cross | Smart Profit Trail"),
            })
            self._save_state()

        self.log(f"[PARTIAL EXIT] {sym}: booked {exit_qty}/{old_qty} @ ₹{exit_p:.2f} | P&L ₹{pnl:+,.2f} | runner {remaining}x on trailing SL ₹{stop_p:.2f}")
        self.sync_balance()
        return {"status": "success", "exited_qty": exit_qty, "remaining_qty": remaining, "pnl": pnl}

    def square_off_position(self, reason: str = "Manual Exit") -> Dict[str, Any]:
        """Square off the active single trade (Short or Long)."""
        with self.lock:
            if not self.state.get("active_positions"):
                return {"status": "error", "message": "No active trade to square off."}
            pos = self.state["active_positions"][0]

        sym = pos["symbol"]
        qty = pos["qty"]
        side = pos.get("side", "BUY")
        entry_p = pos["entry_price"]

        live_data = get_stock_data(sym) if get_stock_data else None
        exit_p = float(live_data["price"]) if live_data and live_data.get("price") else pos["current_price"]

        # If side is BUY, exit txn is SELL. If side is SELL (short), exit txn is BUY!
        exit_txn = "SELL" if side == "BUY" else "BUY"

        # Calculate P&L
        if side == "BUY":
            pnl = round((exit_p - entry_p) * qty, 2)
            pnl_pct = round(((exit_p - entry_p) / entry_p) * 100.0, 2)
        else:  # Short (SELL)
            pnl = round((entry_p - exit_p) * qty, 2)
            pnl_pct = round(((entry_p - exit_p) / entry_p) * 100.0, 2)

        # If live broker mode, place exit order
        if self.state.get("mode") == "live" and self.state.get("token"):
            self.log(f"[LIVE] Placing exit order: {exit_txn} {qty}x {sym} @ ₹{exit_p:.2f}...")
            self.client.place_order(
                symbol=sym,
                txn_type=exit_txn,
                qty=qty,
                limit_price=exit_p,
                product="INTRADAY",
            )

        closed_record = {
            "id": pos["id"],
            "symbol": sym,
            "side": side,
            "qty": qty,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "stop_loss": pos.get("stop_loss", 0.0),
            "target_price": pos.get("target_price", 0.0),
            "entry_time": pos["entry_time"],
            "exit_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
            "strategy": pos.get("strategy", "VWAP x EMA Cross | Smart Profit Trail"),
        }

        with self.lock:
            self.state["active_positions"] = []
            self.state.setdefault("completed_trades", []).append(closed_record)
            self.state["realized_pnl"] = round(self.state.get("realized_pnl", 0.0) + pnl, 2)
            self._save_state()

        self.log(f"[CLOSED] {reason} on {sym} ({side}): Exit @ ₹{exit_p:.2f} | Net P&L: ₹{pnl:+,.2f} ({pnl_pct:+,.2f}%)")
        self.sync_balance()
        return {"status": "success", "closed": closed_record}
    def _monitor_loop(self):
        """Continuous scanning loop over user's watchlist for 1m EMA & VWAP Crossover & active trade monitor."""
        self.log("Continuous 1m EMA & VWAP Crossover scanner daemon active.")
        while not self._stop_event.is_set():
            try:
                mkt = self.get_market_status()

                # 1. Check 3:15 PM EOD Auto Square-Off
                if mkt["status"] in ("SQUARE_OFF_ZONE", "POST_MARKET_CLOSED"):
                    with self.lock:
                        has_open = len(self.state.get("active_positions", [])) > 0
                    if has_open:
                        self.log("[EOD] 3:15 PM Auto Square-Off triggered for active intraday trade.")
                        self.square_off_position(reason="EOD Auto Square-Off (15:15 IST)")

                # 2. Monitor Active Trade (LTP, SL at confirming candle, 1:2 Target, Trailing/Breakeven)
                with self.lock:
                    active = list(self.state.get("active_positions", []))
                    bot_active = self.state.get("is_running", True)
                    watchlist = list(self.state.get("watchlist", []))

                if active:
                    pos = active[0]
                    sym = pos["symbol"]
                    side = pos.get("side", "BUY")
                    live_data = get_stock_data(sym) if get_stock_data else None
                    if live_data and live_data.get("price"):
                        ltp = float(live_data["price"])
                        entry_p = pos["entry_price"]
                        qty = pos["qty"]
                        tgt = pos["target_price"]
                        sl = pos["stop_loss"]
                        target_rr = pos.get("target_rr", 2.0)

                        # ── PineScript-equivalent profit trailing + exits ──
                        long_side = side == "BUY"
                        fpnl = round(((ltp - entry_p) if long_side else (entry_p - ltp)) * qty, 2)
                        fpnl_pct = round(((ltp - entry_p) if long_side else (entry_p - ltp)) / entry_p * 100.0, 2)
                        if long_side:
                            pos["highest_price"] = max(pos.get("highest_price", entry_p), ltp)
                        else:
                            pos["lowest_price"] = min(pos.get("lowest_price", entry_p), ltp)

                        cfg = {k: self.state.get(k, v) for k, v in vwap_strategy.DEFAULT_CONFIG.items()}
                        analysis = self.check_ema_vwap_cross(sym)
                        bar = analysis.get("bar") if analysis.get("status") not in ("ERROR", "NO_DATA") else None
                        if bar and bar.get("atr", 0) > 0:
                            old_sl = float(pos["stop_loss"])
                            vwap_strategy.apply_trailing(pos, bar, cfg)
                            sl = float(pos["stop_loss"])
                            if abs(sl - old_sl) > 0.001:
                                self.log(f"[TRAIL] {sym} {side} SL ₹{old_sl:.2f} → ₹{sl:.2f} ({cfg.get('trail_mode')})")
                        elif cfg.get("use_be", True) and not pos.get("is_breakeven"):
                            be_trigger = entry_p + pos.get("risk_per_share", 0) * float(cfg.get("trail_start_r", 1.0))
                            if (long_side and ltp >= be_trigger) or (not long_side and ltp <= be_trigger):
                                be_sl = round(entry_p, 2)
                                if (long_side and be_sl > sl) or (not long_side and be_sl < sl):
                                    pos["stop_loss"] = sl = be_sl
                                    pos["is_breakeven"] = True
                                    self.log(f"[BREAKEVEN LOCKED] {sym} SL moved to entry ₹{be_sl:.2f}")

                        signal = vwap_strategy.exit_signal(pos, ltp, cfg)
                        if signal == "PARTIAL_TARGET":
                            self.log(f"[PARTIAL TARGET] {sym} hit 1:{target_rr} ₹{tgt:.2f} — booking 50%, trailing the runner.")
                            self.partial_exit_position(reason=f"50% booked at 1:{target_rr} target")
                        elif signal == "TARGET":
                            self.log(f"[TARGET HIT - 1:{target_rr}] {sym} @ ₹{ltp:.2f} | P&L ₹{fpnl:+,.2f}")
                            self.square_off_position(reason=f"Target Hit 1:{target_rr} (+₹{fpnl:.2f} / {fpnl_pct:+.2f}%)")
                        elif signal == "STOP":
                            sl_type = "Trailing/Breakeven SL" if pos.get("trail_on") else "Confirming Candle SL"
                            self.log(f"[STOP LOSS HIT] {sym} hit {sl_type} ₹{sl:.2f} (LTP ₹{ltp:.2f}, P&L ₹{fpnl:+.2f})")
                            self.square_off_position(reason=f"{sl_type} Hit (₹{sl:.2f})")

                        with self.lock:
                            if self.state.get("active_positions"):
                                self.state["active_positions"][0]["current_price"] = ltp
                                self.state["active_positions"][0]["highest_price"] = pos.get("highest_price", ltp)
                                self.state["active_positions"][0]["lowest_price"] = pos.get("lowest_price", ltp)
                                self.state["active_positions"][0]["stop_loss"] = pos["stop_loss"]
                                self.state["active_positions"][0]["is_breakeven"] = pos.get("is_breakeven", False)
                                self.state["active_positions"][0]["floating_pnl"] = fpnl
                                self.state["active_positions"][0]["floating_pnl_pct"] = fpnl_pct
                                self._save_state()

                # 3. Continuous Scanning for 1m EMA & VWAP Crossover (Only if no active trade)
                elif bot_active and watchlist:
                    for sym in watchlist:
                        analysis = self.check_ema_vwap_cross(sym)
                        self._last_scan_results[sym] = analysis

                        # If fresh cross detected & trade eligible & no active position, take trade!
                        if analysis.get("is_trigger_eligible") and not self.state.get("active_positions"):
                            bar_key = f"{sym}:{analysis.get('bar_date_str')}:{analysis.get('cross_type')}"
                            traded_bars = self.state.setdefault("traded_bars_today", [])
                            if bar_key not in traded_bars:
                                sess_parts = str(self.state.get("trade_session", "0915-1500")).split("-")
                                sess_start, sess_end = sess_parts[0].strip(), sess_parts[-1].strip()
                                session_ok = (not self.state.get("use_session", False)
                                              or vwap_strategy.in_session(mkt.get("current_time"), sess_start, sess_end))
                                if mkt.get("status") == "MARKET_OPEN" and session_ok:
                                    side = analysis["suggested_side"]
                                    sl_ref = f"High ₹{analysis['confirm_candle_high']}" if side == "SELL" else f"Low ₹{analysis['confirm_candle_low']}"
                                    self.log(f"[1m EMA-VWAP CROSSOVER DETECTED] {sym}: {side} Signal confirmed on 1m candle ({analysis['confirm_candle_time']})! 9 EMA (₹{analysis['ema']}) crossed VWAP (₹{analysis['vwap']}). SL at Candle {sl_ref}, 1:{analysis['target_rr']} Target ₹{analysis['suggested_target']}. Taking trade!")
                                    traded_bars.append(bar_key)
                                    self.execute_trade(
                                        symbol=sym,
                                        side=side,
                                        entry_price=analysis["current_price"],
                                        stop_loss=analysis["suggested_sl"],
                                        target=analysis["suggested_target"],
                                        confirm_high=analysis["confirm_candle_high"],
                                        confirm_low=analysis["confirm_candle_low"],
                                        cross_time=analysis["confirm_candle_time"],
                                    )
                                    break
                                else:
                                    self.log(f"[PRE/POST MARKET] 1m EMA-VWAP cross detected on {sym} ({analysis.get('cross_type')}), awaiting 09:15 AM market open...")

                with self.lock:
                    self.state["last_scan_time"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                self.sync_balance()
            except Exception as e:
                print(f"Exception in continuous monitor loop: {e}")

            time.sleep(6)

    def start(self):
        if self.running_thread and self.running_thread.is_alive():
            return
        self._stop_event.clear()
        self.running_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.running_thread.start()

    def stop(self):
        self._stop_event.set()
        if self.running_thread:
            self.running_thread.join(timeout=2)


bot_engine = BotEngine()


class IntradayBotHandler(SimpleHTTPRequestHandler):
    """HTTP Request Handler for Bot Dashboard & API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def _send_json(self, data: Any, status: int = 200):
        body = json.dumps(data, indent=2, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_HEAD(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in ("/", "/dashboard"):
            filepath = os.path.join(HERE, "indmoney_intraday_dashboard.html")
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(os.path.getsize(filepath)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return
        super().do_HEAD()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path in ("/", "/dashboard"):
            self._serve_file("indmoney_intraday_dashboard.html")
        elif path == "/api/status":
            mkt = bot_engine.get_market_status()
            with bot_engine.lock:
                st = {
                    "is_running": bot_engine.state.get("is_running", True),
                    "mode": bot_engine.state.get("mode", "paper"),
                    "strategy": bot_engine.state.get("strategy", "VWAP x EMA Cross | Smart Profit Trail"),
                    "market": mkt,
                    "token_configured": bool(bot_engine.state.get("token")),
                    "trade_capital": bot_engine.state.get("trade_capital", 3000.0),
                    "has_active_trade": len(bot_engine.state.get("active_positions", [])) > 0,
                    "watchlist_count": len(bot_engine.state.get("watchlist", [])),
                    "completed_count": len(bot_engine.state.get("completed_trades", [])),
                    "ema_period": bot_engine.state.get("ema_period", 9),
                    "target_rr": bot_engine.state.get("target_rr", 2.0),
                    "trade_direction": bot_engine.state.get("trade_direction", "both"),
                    "trail_breakeven_pct": bot_engine.state.get("trail_breakeven_pct", 1.0),
                    # Smart Profit Trail settings (mirror of the PineScript inputs)
                    "trail_mode": bot_engine.state.get("trail_mode", "EMA Trail"),
                    "use_partial": bot_engine.state.get("use_partial", True),
                    "trail_start_r": bot_engine.state.get("trail_start_r", 1.0),
                    "use_be": bot_engine.state.get("use_be", True),
                    "atr_len": bot_engine.state.get("atr_len", 14),
                    "atr_mult": bot_engine.state.get("atr_mult", 2.0),
                    "use_session": bot_engine.state.get("use_session", False),
                    "trade_session": bot_engine.state.get("trade_session", "0915-1500"),
                    "close_eod": bot_engine.state.get("close_eod", True),
                    "one_at_a_time": bot_engine.state.get("one_at_a_time", True),
                }
            self._send_json(st)
        elif path == "/api/pinescript":
            self._send_json({
                "status": "success",
                "filename": "vwap_ema_strategy.pine",
                "pinescript": vwap_strategy.PINESCRIPT,
            })
        elif path == "/api/balance":
            bal = bot_engine.sync_balance()
            self._send_json(bal)
        elif path == "/api/trades":
            with bot_engine.lock:
                trades_data = {
                    "active": bot_engine.state.get("active_positions", []),
                    "completed": bot_engine.state.get("completed_trades", []),
                    "realized_pnl": bot_engine.state.get("realized_pnl", 0.0),
                    "unrealized_pnl": bot_engine.state.get("unrealized_pnl", 0.0),
                }
            self._send_json(trades_data)
        elif path == "/api/watchlist":
            with bot_engine.lock:
                watchlist = list(bot_engine.state.get("watchlist", []))
            items = []
            for sym in watchlist:
                data = bot_engine._last_scan_results.get(sym)
                if not data:
                    data = bot_engine.check_ema_vwap_cross(sym)
                    bot_engine._last_scan_results[sym] = data
                items.append(data)
            self._send_json({"watchlist": items})
        elif path == "/api/logs":
            with bot_engine.lock:
                logs = list(bot_engine.state.get("logs", []))
            self._send_json({"logs": logs})
        elif path == "/api/top_buying":
            top_5 = bot_engine.fetch_top_buying_stocks()
            self._send_json({"status": "success", "top_5": top_5})
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        raw_len = self.headers.get("Content-Length")
        try:
            content_length = int(raw_len) if raw_len else 0
        except (ValueError, TypeError):
            content_length = 0
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if path == "/api/watchlist/add":
            sym = payload.get("symbol") or payload.get("symbols") or ""
            updated = bot_engine.add_to_watchlist(str(sym))
            self._send_json({"status": "success", "watchlist": updated})
        elif path == "/api/watchlist/sync_top_buying":
            top_5 = bot_engine.fetch_top_buying_stocks()
            updated = bot_engine.add_to_watchlist(", ".join(top_5))
            self._send_json({"status": "success", "top_5": top_5, "watchlist": updated})
        elif path == "/api/watchlist/remove":
            sym = payload.get("symbol", "")
            updated = bot_engine.remove_from_watchlist(sym)
            self._send_json({"status": "success", "watchlist": updated})
        elif path == "/api/watchlist/clear":
            bot_engine.clear_watchlist()
            self._send_json({"status": "success", "watchlist": []})
        elif path == "/api/bot/toggle":
            with bot_engine.lock:
                curr = bot_engine.state.get("is_running", True)
                bot_engine.state["is_running"] = not curr
                bot_engine._save_state()
                new_state = bot_engine.state["is_running"]
            bot_engine.log(f"Bot auto-scanner switched to: {'ACTIVE' if new_state else 'PAUSED'}")
            self._send_json({"status": "success", "is_running": new_state})
        elif path == "/api/square_off":
            res = bot_engine.square_off_position(reason="Manual User Square-Off")
            self._send_json(res)
        elif path == "/api/partial_exit":
            res = bot_engine.partial_exit_position(reason="Manual 50% partial exit")
            self._send_json(res)
        elif path == "/api/config":
            token = payload.get("token")
            cap = payload.get("trade_capital")
            ema_period = payload.get("ema_period")
            target_rr = payload.get("target_rr")
            trade_dir = payload.get("trade_direction")
            trail_be = payload.get("trail_breakeven_pct")
            leverage = payload.get("leverage")
            mode = payload.get("mode")
            with bot_engine.lock:
                if token is not None:
                    bot_engine.state["token"] = token.strip()
                    bot_engine.client.set_token(token.strip())
                if cap is not None:
                    bot_engine.state["trade_capital"] = float(cap)
                if ema_period is not None:
                    bot_engine.state["ema_period"] = int(ema_period)
                if target_rr is not None:
                    bot_engine.state["target_rr"] = float(target_rr)
                if trade_dir is not None:
                    bot_engine.state["trade_direction"] = str(trade_dir).lower()
                if trail_be is not None:
                    bot_engine.state["trail_breakeven_pct"] = float(trail_be)
                if leverage is not None:
                    bot_engine.state["leverage"] = int(leverage)
                if mode in ("paper", "live"):
                    bot_engine.state["mode"] = mode
                for key in ("use_partial", "use_be", "use_session", "close_eod", "one_at_a_time"):
                    if key in payload:
                        bot_engine.state[key] = str(payload[key]).lower() in ("true", "1", "yes", "on")
                for key in ("trail_start_r", "atr_mult"):
                    if key in payload:
                        bot_engine.state[key] = float(payload[key])
                if "atr_len" in payload:
                    bot_engine.state["atr_len"] = max(1, int(payload["atr_len"]))
                if "trail_mode" in payload:
                    trail_mode = str(payload["trail_mode"])
                    if trail_mode in ("None (Fixed RR)", "EMA Trail", "ATR Trail", "Candle Low/High"):
                        bot_engine.state["trail_mode"] = trail_mode
                if "trade_session" in payload:
                    bot_engine.state["trade_session"] = str(payload["trade_session"])
                bot_engine._save_state()
            bot_engine.log(f"Bot configuration updated: EMA={bot_engine.state.get('ema_period', 9)}, Target R:R=1:{bot_engine.state.get('target_rr', 2.0)}, Direction={bot_engine.state.get('trade_direction', 'both')}, Trail={bot_engine.state.get('trail_mode')}")
            self._send_json({"status": "success", "config": bot_engine.state})
        elif path == "/api/token":
            token = (payload.get("token") or payload.get("api_key") or "").strip()
            if not token:
                self._send_json({"status": "error", "message": "API key / Access Token cannot be empty"}, 400)
                return
            temp_client = IndmoneyClient(token=token)
            funds = temp_client.get_funds()
            if funds.get("status") == "success":
                with bot_engine.lock:
                    bot_engine.state["token"] = token
                    bot_engine.state["mode"] = "live"
                    bot_engine.client.set_token(token)
                    bot_engine.state["sod_balance"] = funds["sod_balance"]
                    bot_engine.state["available_balance"] = funds["available_balance"]
                    bot_engine.state["utilized_margin"] = funds["utilized_margin"]
                    bot_engine.state["realized_pnl"] = funds["realized_pnl"]
                    bot_engine.state["unrealized_pnl"] = funds["unrealized_pnl"]
                    bot_engine._save_state()
                bot_engine.log(f"INDmoney API connected successfully. Live Balance: ₹{funds['available_balance']:,.2f}")
                self._send_json({"status": "success", "message": "INDmoney API key connected successfully", "funds": funds})
            else:
                self._send_json({"status": "error", "message": f"INDmoney validation failed: {funds.get('message', 'Invalid Token')}", "funds": funds}, 400)
        elif path == "/api/token/clear":
            with bot_engine.lock:
                bot_engine.state["token"] = ""
                bot_engine.state["mode"] = "paper"
                bot_engine.client.set_token("")
                bot_engine._save_state()
            bot_engine.log("INDmoney API key disconnected. Switched to Paper mode.")
            self._send_json({"status": "success", "message": "INDmoney token removed"})
        elif path == "/api/balance/sync":
            funds = bot_engine.sync_balance()
            self._send_json(funds)
        elif path == "/api/test_token":
            token = payload.get("token", "").strip()
            temp_client = IndmoneyClient(token=token)
            funds = temp_client.get_funds()
            self._send_json(funds)
        else:
            self._send_json({"status": "error", "message": "Not found"}, 404)

    def _serve_file(self, filename: str):
        filepath = os.path.join(HERE, filename)
        if not os.path.exists(filepath):
            self.send_error(404, f"File {filename} not found")
            return
        ext = filename.split(".")[-1]
        types = {"html": "text/html", "css": "text/css", "js": "application/javascript", "json": "application/json"}
        with open(filepath, "rb") as f:
            content = f.read()
        self.send_response(200)
        self.send_header("Content-Type", types.get(ext, "text/plain"))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="INDmoney Intraday ATR Breakout Bot")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    parser.add_argument("--token", type=str, default="", help="INDmoney Access Token")
    parser.add_argument("--stocks", type=str, default="", help="Comma-separated stock symbols to scan")
    parser.add_argument("--paper", action="store_true", help="Force paper trading mode")
    args = parser.parse_args()

    if args.token:
        bot_engine.state["token"] = args.token
        bot_engine.client.set_token(args.token)

    if args.paper:
        bot_engine.state["mode"] = "paper"

    if args.stocks:
        bot_engine.add_to_watchlist(args.stocks)

    # Start background continuous scanning thread
    bot_engine.start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), IntradayBotHandler)
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print(f"  INDmoney Intraday ATR Breakout Bot Online")
    print(f"  Single Bullish Trade | Capital: ₹3,000 | Port: {args.port}")
    print(f"  Dashboard: http://localhost:{args.port}")
    print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        bot_engine.stop()
        server.shutdown()


if __name__ == "__main__":
    main()
