"""
INDmoney Intraday Equity Bot Server & Execution Engine
======================================================
Strategy:
  - User-provided stock watchlist scanned continuously.
  - Abnormal ATR breakout detection (Candle Range >= Multiplier * Normal ATR).
  - Gap openings strictly filtered out (no gap trades; intraday price action only).
  - Single intraday trade at a time (Max 1 active position).
  - Fixed ₹3,000 capital allocation.
  - Bullish only (BUY side strictly).
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
    """Intraday ATR Breakout Engine — Bullish Only, Single Trade, 3k Capital."""

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
            "sod_balance": 10000.0,
            "available_balance": 10000.0,
            "utilized_margin": 0.0,
            "realized_pnl": 0.0,
            "unrealized_pnl": 0.0,
            "trade_capital": 3000.0,  # Exactly ₹3,000 capital
            "max_loss_inr": 150.0,    # Strictly ₹150 Stop Loss per trade
            "use_mis_leverage": True,  # 5x MIS leverage (₹15,000 position)
            "leverage": 5,
            "max_open_trades": 1,     # Single intraday trade strictly
            "atr_multiplier": 1.3,    # Abnormal candle range threshold (1.3x normal ATR)
            "volume_multiplier": 1.3, # Breakout volume threshold (1.3x average volume)
            "trail_activation_pct": 1.5, # Activate trailing SL when profit reaches +1.5%
            "trail_breakeven_pct": 1.0,  # Move SL to Breakeven when profit reaches +1.0%
            "trail_distance_pct": 0.8,   # Trail peak price with 0.8% buffer
            "target_rr": 2.0,         # 1:2 Risk to Reward
            "auto_square_off_time": "15:15",
            "watchlist": [],          # Dynamic user-provided stocks
            "active_positions": [],   # Max 1 active trade
            "completed_trades": [],   # Trades closed today
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
        self.state["max_loss_inr"] = 150.0  # Strictly ₹150 Stop Loss per trade
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

    def check_atr_breakout(self, symbol: str) -> Dict[str, Any]:
        """Analyze a stock for Morning Baseline Reclaim & Momentum Ignition Breakout.
        
        Setup characteristics (matching INDmoney Intraday chart):
          1. Baseline = Previous Day Close / Day Open equilibrium.
          2. Coiling/Consolidation base established near baseline in early session.
          3. Momentum Ignition Trigger:
             - Decisive bounce/reclaim holding above baseline.
             - Breakout above morning consolidation resistance (High of opening base).
             - Volume surge >= volume_multiplier * rolling average volume.
             - Candle range expansion >= atr_multiplier * normal ATR.
             - Strong bullish closing candle (top 35% of range).
             - Clean intraday move (excludes massive >3.5% pre-market gap exhaustions).
        """
        resolved = _resolve_ticker(symbol)
        try:
            df = yf.download(resolved, period="5d", interval="5m", progress=False)
            if df is None or df.empty or len(df) < 15:
                return {"symbol": symbol, "status": "NO_DATA", "error": "Insufficient 5m candles"}

            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            high = df["High"]
            low = df["Low"]
            close = df["Close"]
            open_p = df["Open"]
            volume = df["Volume"]
            prev_close = close.shift(1)

            # True Range and 14-period Normal ATR (shifted so it's baseline before current bar)
            tr = np.maximum(high - low, np.maximum(abs(high - prev_close), abs(low - prev_close)))
            atr14 = tr.rolling(14).mean().shift(1)
            vol_ma10 = volume.rolling(10).mean().shift(1)

            # Identify trading days
            dates = sorted(list(set(df.index.date)))
            if len(dates) < 2:
                # Single day data fallback
                today_date = dates[-1]
                prev_day_close = float(df["Open"].iloc[0])
            else:
                today_date = dates[-1]
                prev_date = dates[-2]
                prev_day_close = float(df[df.index.date == prev_date]["Close"].iloc[-1])

            today_bars = df[df.index.date == today_date]
            if len(today_bars) == 0:
                today_bars = df.iloc[-10:]

            c_time = today_bars.index[-1]
            c_close = float(today_bars["Close"].iloc[-1])
            c_open = float(today_bars["Open"].iloc[-1])
            c_high = float(today_bars["High"].iloc[-1])
            c_low = float(today_bars["Low"].iloc[-1])
            c_vol = float(today_bars["Volume"].iloc[-1])
            c_range = round(c_high - c_low, 2)

            day_open = float(today_bars["Open"].iloc[0])
            baseline = prev_day_close if prev_day_close > 0 else day_open

            normal_atr = float(atr14.loc[c_time]) if c_time in atr14.index else float(atr14.iloc[-1])
            if pd.isna(normal_atr) or normal_atr <= 0:
                normal_atr = float(tr.iloc[-15:-1].mean()) if len(tr) >= 15 else (c_range or 0.5)
            normal_atr = round(max(0.05, normal_atr), 2)
            atr_ratio = round(c_range / normal_atr, 2) if normal_atr > 0 else 1.0

            avg_vol = float(vol_ma10.loc[c_time]) if c_time in vol_ma10.index else float(vol_ma10.iloc[-1])
            if pd.isna(avg_vol) or avg_vol <= 0:
                avg_vol = float(volume.iloc[-11:-1].mean()) if len(volume) >= 11 else (c_vol or 1000)
            avg_vol = max(1.0, avg_vol)
            vol_ratio = round(c_vol / avg_vol, 2)

            # --- GAP FILTER ---
            gap_pct = round(((day_open - prev_day_close) / prev_day_close) * 100.0, 2) if prev_day_close > 0 else 0.0
            max_gap = float(self.state.get("max_gap_pct", 1.5))
            has_gap = abs(gap_pct) >= max_gap
            is_opening_candle = (c_time.hour == 9 and c_time.minute <= 15)

            # --- MORNING CONSOLIDATION BASE ---
            if len(today_bars) > 1:
                prior_bars = today_bars.iloc[:-1]
                base_high = float(prior_bars["High"].max())
                base_low = float(prior_bars["Low"].min())
            else:
                base_high = c_open
                base_low = c_open

            base_high = round(base_high, 2)
            base_low = round(base_low, 2)

            # --- MOMENTUM IGNITION CRITERIA ---
            atr_mult = float(self.state.get("atr_multiplier", 1.3))
            vol_mult = float(self.state.get("volume_multiplier", 1.3))

            dist_from_baseline_pct = round(((c_close - baseline) / baseline) * 100.0, 2)
            above_baseline = c_close >= baseline
            breaks_base_res = c_close > base_high
            is_green = c_close > c_open
            strong_body = (c_close - c_open) >= (0.35 * c_range) if c_range > 0 else True
            strong_close = (c_high - c_close) <= (0.35 * c_range) if c_range > 0 else True
            vol_surging = vol_ratio >= vol_mult
            atr_expanded = atr_ratio >= atr_mult

            # Momentum ignition confirmed (Upside-only breakout):
            is_breakout = (
                not is_opening_candle
                and not has_gap
                and above_baseline
                and breaks_base_res
                and is_green
                and strong_close
                and (vol_surging or atr_expanded)
            )

            # Suggested tight Stop Loss strictly capped at ₹150 risk per trade
            est_qty = max(1, int(15000.0 / c_close)) if c_close > 0 else 1
            max_loss_inr = float(self.state.get("max_loss_inr", 150.0))
            per_share_risk = max(0.05, round(max_loss_inr / est_qty, 2))
            suggested_sl = round(c_close - per_share_risk, 2)
            target_rr = float(self.state.get("target_rr", 2.0))
            suggested_target = round(c_close + (per_share_risk * target_rr), 2)

            if is_breakout:
                status = "IGNITION_BREAKOUT"
            elif has_gap:
                status = f"GAP_IGNORED ({'+' if gap_pct > 0 else ''}{gap_pct}%)"
            elif not above_baseline:
                status = "BELOW_BASELINE"
            elif (base_high - c_close) <= (0.5 * normal_atr):
                status = "TESTING_RESISTANCE"
            else:
                status = "COILING_ABOVE_BASE"

            return {
                "symbol": symbol,
                "current_price": c_close,
                "candle_open": c_open,
                "candle_high": c_high,
                "candle_low": c_low,
                "candle_range": c_range,
                "baseline": round(baseline, 2),
                "baseline_dist_pct": dist_from_baseline_pct,
                "consolidation_high": base_high,
                "consolidation_low": base_low,
                "normal_atr": normal_atr,
                "atr_ratio": atr_ratio,
                "atr_threshold": atr_mult,
                "volume": int(c_vol),
                "avg_volume": int(avg_vol),
                "vol_ratio": vol_ratio,
                "vol_threshold": vol_mult,
                "is_breakout": is_breakout,
                "is_opening_candle": is_opening_candle,
                "gap_pct": gap_pct,
                "above_baseline": above_baseline,
                "breaks_resistance": breaks_base_res,
                "suggested_sl": suggested_sl,
                "suggested_target": suggested_target,
                "time": c_time.strftime("%H:%M"),
                "status": status,
            }
        except Exception as e:
            return {"symbol": symbol, "status": "ERROR", "error": str(e)}

    def execute_single_bullish_trade(self, symbol: str, entry_price: float, stop_loss: float, target: float) -> Dict[str, Any]:
        """Execute the single intraday bullish trade with fixed ₹3,000 capital and trailing profit setup."""
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "")
        with self.lock:
            active_count = len(self.state.get("active_positions", []))
            if active_count >= 1:
                return {"status": "error", "message": "A single intraday trade is already active. Only 1 trade allowed."}

            cap = float(self.state.get("trade_capital", 3000.0))
            use_mis = self.state.get("use_mis_leverage", True)
            leverage = int(self.state.get("leverage", 5)) if use_mis else 1
            mode = self.state.get("mode", "paper")
            token = self.state.get("token")
            trail_act = float(self.state.get("trail_activation_pct", 1.5))
            trail_be = float(self.state.get("trail_breakeven_pct", 1.0))
            trail_dist = float(self.state.get("trail_distance_pct", 0.8))

        # Position sizing: ₹3,000 capital deployed with 5x MIS leverage (₹15,000 total exposure)
        total_exposure = cap * leverage
        qty = max(1, int(total_exposure / entry_price))
        actual_margin_blocked = round((qty * entry_price) / leverage, 2)

        # Strictly ₹150 Stop Loss cap per trade
        max_loss_inr = float(self.state.get("max_loss_inr", 150.0))
        per_share_risk = max(0.05, round(max_loss_inr / qty, 2))
        stop_loss = round(entry_price - per_share_risk, 2)
        target_rr = float(self.state.get("target_rr", 2.0))
        target = round(entry_price + (per_share_risk * target_rr), 2)

        trade_id = f"TRD-{symbol}-{int(time.time() * 1000) % 100000}"

        if mode == "live" and token:
            self.log(f"[LIVE] Transmitting order to INDmoney API: BUY {qty}x {symbol} @ ₹{entry_price:.2f} (Margin: ₹{actual_margin_blocked})...")
            order_res = self.client.place_order(
                symbol=symbol,
                txn_type="BUY",
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

        position = {
            "id": trade_id,
            "broker_id": broker_order_id,
            "symbol": symbol,
            "side": "BUY",  # Bullish only
            "qty": qty,
            "entry_price": float(entry_price),
            "current_price": float(entry_price),
            "highest_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "initial_stop_loss": float(stop_loss),
            "target_price": float(target),
            "max_loss_inr": max_loss_inr,
            "is_breakeven": False,
            "is_trailing": False,
            "trail_activation_pct": trail_act,
            "trail_breakeven_pct": trail_be,
            "trail_distance_pct": trail_dist,
            "capital": actual_margin_blocked,
            "total_value": round(qty * entry_price, 2),
            "entry_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "floating_pnl": 0.0,
            "floating_pnl_pct": 0.0,
            "strategy": "Morning Baseline Reclaim & Momentum Ignition",
            "status": "OPEN",
        }

        with self.lock:
            self.state["active_positions"] = [position]  # Strictly single trade
            self._save_state()

        self.log(f"[MOMENTUM IGNITION BUY] BUY {qty}x {symbol} @ ₹{entry_price:.2f} | Exact ₹{max_loss_inr:.0f} SL: ₹{stop_loss:.2f} | TGT: ₹{target:.2f} (+₹{max_loss_inr*target_rr:.0f}) | Margin: ₹{actual_margin_blocked:.2f}")
        self.sync_balance()
        return {"status": "success", "position": position}
        """Execute the single intraday bullish trade with fixed ₹3,000 capital."""
        symbol = symbol.upper().replace(".NS", "").replace(".BO", "")
        with self.lock:
            active_count = len(self.state.get("active_positions", []))
            if active_count >= 1:
                return {"status": "error", "message": "A single intraday trade is already active. Only 1 trade allowed."}

            cap = float(self.state.get("trade_capital", 3000.0))
            use_mis = self.state.get("use_mis_leverage", True)
            leverage = int(self.state.get("leverage", 5)) if use_mis else 1
            mode = self.state.get("mode", "paper")
            token = self.state.get("token")

        # Position sizing: ₹3,000 capital deployed
        # With 5x MIS leverage, total trade exposure = ₹3,000 * 5 = ₹15,000
        total_exposure = cap * leverage
        qty = max(1, int(total_exposure / entry_price))
        actual_margin_blocked = round((qty * entry_price) / leverage, 2)

        trade_id = f"TRD-{symbol}-{int(time.time() * 1000) % 100000}"

        if mode == "live" and token:
            self.log(f"[LIVE] Transmitting order to INDmoney API: BUY {qty}x {symbol} @ ₹{entry_price:.2f} (Margin: ₹{actual_margin_blocked})...")
            order_res = self.client.place_order(
                symbol=symbol,
                txn_type="BUY",
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

        position = {
            "id": trade_id,
            "broker_id": broker_order_id,
            "symbol": symbol,
            "side": "BUY",  # Bullish only
            "qty": qty,
            "entry_price": float(entry_price),
            "current_price": float(entry_price),
            "stop_loss": float(stop_loss),
            "target_price": float(target),
            "capital": actual_margin_blocked,
            "total_value": round(qty * entry_price, 2),
            "entry_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "floating_pnl": 0.0,
            "floating_pnl_pct": 0.0,
            "strategy": "Intraday Abnormal ATR Breakout",
            "status": "OPEN",
        }

        with self.lock:
            self.state["active_positions"] = [position]  # Strictly single trade
            self._save_state()

        self.log(f"[TRADE TRIGGERED] Opened Bullish Intraday Trade: BUY {qty}x {symbol} @ ₹{entry_price:.2f} | SL: ₹{stop_loss:.2f} | TGT: ₹{target:.2f} | Margin: ₹{actual_margin_blocked:.2f}")
        self.sync_balance()
        return {"status": "success", "position": position}

    def square_off_position(self, reason: str = "Manual Exit") -> Dict[str, Any]:
        """Square off the active single trade."""
        with self.lock:
            if not self.state.get("active_positions"):
                return {"status": "error", "message": "No active trade to square off."}
            pos = self.state["active_positions"][0]

        sym = pos["symbol"]
        qty = pos["qty"]
        entry_p = pos["entry_price"]

        live_data = get_stock_data(sym) if get_stock_data else None
        exit_p = float(live_data["price"]) if live_data and live_data.get("price") else pos["current_price"]

        # If live broker mode, place SELL order
        if self.state.get("mode") == "live" and self.state.get("token"):
            self.client.place_order(
                symbol=sym,
                txn_type="SELL",
                qty=qty,
                limit_price=exit_p,
                product="INTRADAY",
            )

        pnl = round((exit_p - entry_p) * qty, 2)
        pnl_pct = round(((exit_p - entry_p) / entry_p) * 100.0, 2)

        closed_record = {
            "id": pos["id"],
            "symbol": sym,
            "side": "BUY",
            "qty": qty,
            "entry_price": entry_p,
            "exit_price": exit_p,
            "entry_time": pos["entry_time"],
            "exit_time": datetime.datetime.now().strftime("%H:%M:%S"),
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "reason": reason,
        }

        with self.lock:
            self.state["active_positions"] = []
            self.state.setdefault("completed_trades", []).append(closed_record)
            self.state["realized_pnl"] = round(self.state.get("realized_pnl", 0.0) + pnl, 2)
            self._save_state()

        self.log(f"[CLOSED] {reason} on {sym}: Exit @ ₹{exit_p:.2f} | Net P&L: ₹{pnl:+,.2f} ({pnl_pct:+,.2f}%)")
        self.sync_balance()
        return {"status": "success", "closed": closed_record}

    def _monitor_loop(self):
        """Continuous scanning loop over user's watchlist & active trade monitor."""
        self.log("Continuous intraday scanner daemon active.")
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

                # 2. Monitor Active Trade (LTP, Dynamic Trailing SL, Breakeven, Target)
                with self.lock:
                    active = list(self.state.get("active_positions", []))
                    bot_active = self.state.get("is_running", True)
                    watchlist = list(self.state.get("watchlist", []))

                if active:
                    pos = active[0]
                    sym = pos["symbol"]
                    live_data = get_stock_data(sym) if get_stock_data else None
                    if live_data and live_data.get("price"):
                        ltp = float(live_data["price"])
                        entry_p = pos["entry_price"]
                        qty = pos["qty"]
                        tgt = pos["target_price"]

                        # Track peak high price
                        highest = max(pos.get("highest_price", entry_p), ltp)
                        pos["highest_price"] = highest

                        fpnl = round((ltp - entry_p) * qty, 2)
                        fpnl_pct = round(((ltp - entry_p) / entry_p) * 100.0, 2)

                        # Breakeven Lock-in (at +1.0% gain)
                        be_pct = float(pos.get("trail_breakeven_pct", 1.0))
                        if fpnl_pct >= be_pct and not pos.get("is_breakeven", False):
                            be_sl = round(entry_p * 1.001, 2)
                            if be_sl > pos["stop_loss"]:
                                pos["stop_loss"] = be_sl
                                pos["is_breakeven"] = True
                                self.log(f"[BREAKEVEN LOCKED] {sym} up +{fpnl_pct:.2f}%: SL raised to Breakeven (₹{be_sl:.2f})")

                        # Dynamic Trailing Stop Loss (at +1.5% gain)
                        act_pct = float(pos.get("trail_activation_pct", 1.5))
                        dist_pct = float(pos.get("trail_distance_pct", 0.8))
                        if fpnl_pct >= act_pct:
                            trail_floor = round(highest * (1.0 - (dist_pct / 100.0)), 2)
                            if trail_floor > pos["stop_loss"]:
                                pos["stop_loss"] = trail_floor
                                pos["is_trailing"] = True

                        with self.lock:
                            if self.state.get("active_positions"):
                                self.state["active_positions"][0]["current_price"] = ltp
                                self.state["active_positions"][0]["highest_price"] = highest
                                self.state["active_positions"][0]["stop_loss"] = pos["stop_loss"]
                                self.state["active_positions"][0]["is_breakeven"] = pos.get("is_breakeven", False)
                                self.state["active_positions"][0]["is_trailing"] = pos.get("is_trailing", False)
                                self.state["active_positions"][0]["floating_pnl"] = fpnl
                                self.state["active_positions"][0]["floating_pnl_pct"] = fpnl_pct
                                self._save_state()

                        sl = pos["stop_loss"]
                        max_loss = float(pos.get("max_loss_inr", 150.0))
                        if ltp >= tgt:
                            self.log(f"[TARGET HIT] {sym} reached target ₹{tgt:.2f} (LTP: ₹{ltp:.2f})!")
                            self.square_off_position(reason=f"Target Hit (Peak: ₹{highest:.2f})")
                        elif ltp <= sl or fpnl <= -max_loss:
                            if pos.get("is_trailing"):
                                self.log(f"[TRAILING SL LOCKED] {sym} closed at trailing stop ₹{sl:.2f} (Peak was ₹{highest:.2f})!")
                                self.square_off_position(reason=f"Trailing Stop Locked (+₹{fpnl:.2f} / {fpnl_pct:+.2f}%)")
                            elif pos.get("is_breakeven"):
                                self.log(f"[BREAKEVEN SL HIT] {sym} exited at breakeven ₹{sl:.2f}")
                                self.square_off_position(reason="Breakeven Stop Hit")
                            else:
                                self.log(f"[STOP LOSS HIT] {sym} hit ₹{max_loss:.0f} risk cap (LTP: ₹{ltp:.2f}, Loss: ₹{fpnl:.2f})!")
                                self.square_off_position(reason=f"₹{max_loss:.0f} Stop Loss Hit (-₹{abs(fpnl):.2f})")

                # 3. Continuous Scanning for Momentum Ignition Breakout (Only if no active trade)
                elif bot_active and watchlist:
                    for sym in watchlist:
                        analysis = self.check_atr_breakout(sym)
                        self._last_scan_results[sym] = analysis

                        # If momentum ignition detected & no trade active, execute immediately when market is open!
                        if analysis.get("is_breakout") and not self.state.get("active_positions"):
                            if mkt.get("status") == "MARKET_OPEN":
                                self.log(f"[IGNITION BREAKOUT DETECTED] {sym}: Reclaimed Baseline ₹{analysis['baseline']}, broke resistance ₹{analysis['consolidation_high']} with {analysis['vol_ratio']}x Volume and {analysis['atr_ratio']}x ATR! Taking trade!")
                                self.execute_single_bullish_trade(
                                    symbol=sym,
                                    entry_price=analysis["current_price"],
                                    stop_loss=analysis["suggested_sl"],
                                    target=analysis["suggested_target"],
                                )
                                break  # Single trade taken, stop scanning loop
                            else:
                                self.log(f"[PRE/POST MARKET] Breakout signal detected on {sym}, awaiting 09:15 AM market open...")

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
                    "market": mkt,
                    "token_configured": bool(bot_engine.state.get("token")),
                    "trade_capital": bot_engine.state.get("trade_capital", 3000.0),
                    "has_active_trade": len(bot_engine.state.get("active_positions", [])) > 0,
                    "watchlist_count": len(bot_engine.state.get("watchlist", [])),
                    "completed_count": len(bot_engine.state.get("completed_trades", [])),
                    "atr_multiplier": bot_engine.state.get("atr_multiplier", 1.3),
                    "volume_multiplier": bot_engine.state.get("volume_multiplier", 1.3),
                    "trail_activation_pct": bot_engine.state.get("trail_activation_pct", 1.5),
                    "trail_distance_pct": bot_engine.state.get("trail_distance_pct", 0.8),
                    "target_rr": bot_engine.state.get("target_rr", 2.0),
                }
            self._send_json(st)
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
                    data = bot_engine.check_atr_breakout(sym)
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
        elif path == "/api/config":
            token = payload.get("token")
            cap = payload.get("trade_capital")
            mult = payload.get("atr_multiplier")
            vol_mult = payload.get("volume_multiplier")
            trail_act = payload.get("trail_activation_pct")
            trail_be = payload.get("trail_breakeven_pct")
            trail_dist = payload.get("trail_distance_pct")
            target_rr = payload.get("target_rr")
            leverage = payload.get("leverage")
            mode = payload.get("mode")
            with bot_engine.lock:
                if token is not None:
                    bot_engine.state["token"] = token.strip()
                    bot_engine.client.set_token(token.strip())
                if cap is not None:
                    bot_engine.state["trade_capital"] = float(cap)
                if mult is not None:
                    bot_engine.state["atr_multiplier"] = float(mult)
                if vol_mult is not None:
                    bot_engine.state["volume_multiplier"] = float(vol_mult)
                if trail_act is not None:
                    bot_engine.state["trail_activation_pct"] = float(trail_act)
                if trail_be is not None:
                    bot_engine.state["trail_breakeven_pct"] = float(trail_be)
                if trail_dist is not None:
                    bot_engine.state["trail_distance_pct"] = float(trail_dist)
                if target_rr is not None:
                    bot_engine.state["target_rr"] = float(target_rr)
                if leverage is not None:
                    bot_engine.state["leverage"] = int(leverage)
                if mode in ("paper", "live"):
                    bot_engine.state["mode"] = mode
                bot_engine._save_state()
            bot_engine.log("Bot configuration updated.")
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
