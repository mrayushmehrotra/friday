"""
VWAP x EMA Cross | Smart Profit Trail — Python mirror of the TradingView
PineScript strategy used by the INDmoney auto bot.

The TradingView source is kept verbatim in PINESCRIPT so the dashboard can
show it in a copyable box. The functions below implement the same entry,
trailing-stop and partial-exit logic for the Python execution engine.
"""

from typing import Any, Dict, Optional

DEFAULT_CONFIG: Dict[str, Any] = {
    "ema_len": 9,
    "target_rr": 2.0,
    "trail_mode": "EMA Trail",       # None (Fixed RR) | EMA Trail | ATR Trail | Candle Low/High
    "use_partial": True,             # book 50% at target, trail the runner
    "trail_start_r": 1.0,            # activate trailing after this R multiple
    "use_be": True,                  # move SL to breakeven at trail trigger
    "atr_len": 14,
    "atr_mult": 2.0,
    "use_session": False,
    "trade_session": "0915-1500",
    "tz": "Asia/Kolkata",
    "close_eod": True,
    "one_at_a_time": True,
    "show_sl": True,
}

FIXED_MODE = "None (Fixed RR)"


def in_session(bar_time: Optional[str], start: str = "0915", end: str = "1500") -> bool:
    """True when a 'HH:MM' bar timestamp is inside the session window."""
    if not bar_time:
        return True
    try:
        hhmm = bar_time[-5:]
        return start <= hhmm <= end
    except (TypeError, ValueError):
        return True


def apply_trailing(position: Dict[str, Any], bar: Dict[str, float],
                   cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ratchet the stop exactly like the PineScript 'Dynamic Profit Trailing'.

    `bar` needs: high, low, close, ema, atr (and optionally prev_low/prev_high).
    Mutates and returns `position`. Never loosens an existing stop.
    """
    mode = cfg.get("trail_mode", DEFAULT_CONFIG["trail_mode"])
    if mode == FIXED_MODE:
        return position

    long_side = position.get("side", "BUY").upper() == "BUY"
    entry = float(position["entry_price"])
    risk = float(position.get("risk_per_share") or abs(entry - float(position["stop_loss"])))
    if risk <= 0:
        return position

    stop = float(position["stop_loss"])
    extreme = float(position.get("extreme_price", bar["high"] if long_side else bar["low"]))
    trail_on = bool(position.get("trail_on", False))

    if long_side:
        extreme = max(extreme, float(bar["high"]))
        triggered = float(bar["high"]) >= entry + risk * float(cfg.get("trail_start_r", 1.0))
        if triggered and not trail_on:
            trail_on = True
            if cfg.get("use_be", True):
                stop = max(stop, entry)
        if trail_on:
            if mode == "EMA Trail":
                candidate = float(bar.get("ema", stop))
            elif mode == "ATR Trail":
                candidate = extreme - float(bar.get("atr", 0.0)) * float(cfg.get("atr_mult", 2.0))
            else:  # Candle Low/High
                candidate = float(bar.get("prev_low", bar["low"]))
            if candidate < float(bar["close"]):
                stop = max(stop, candidate)
    else:
        extreme = min(extreme, float(bar["low"]))
        triggered = float(bar["low"]) <= entry - risk * float(cfg.get("trail_start_r", 1.0))
        if triggered and not trail_on:
            trail_on = True
            if cfg.get("use_be", True):
                stop = min(stop, entry)
        if trail_on:
            if mode == "EMA Trail":
                candidate = float(bar.get("ema", stop))
            elif mode == "ATR Trail":
                candidate = extreme + float(bar.get("atr", 0.0)) * float(cfg.get("atr_mult", 2.0))
            else:  # Candle Low/High
                candidate = float(bar.get("prev_high", bar["high"]))
            if candidate > float(bar["close"]):
                stop = min(stop, candidate)

    position["stop_loss"] = round(stop, 2)
    position["extreme_price"] = round(extreme, 2)
    position["trail_on"] = trail_on
    position["is_trailing"] = trail_on
    position["is_breakeven"] = bool(position.get("is_breakeven")) or (trail_on and cfg.get("use_be", True))
    return position


def exit_signal(position: Dict[str, Any], ltp: float,
                cfg: Dict[str, Any]) -> Optional[str]:
    """Return 'TARGET', 'PARTIAL_TARGET', 'STOP' or None for the current tick."""
    long_side = position.get("side", "BUY").upper() == "BUY"
    target = float(position["target_price"])
    stop = float(position["stop_loss"])
    mode = cfg.get("trail_mode", DEFAULT_CONFIG["trail_mode"])

    if long_side:
        if ltp >= target:
            if mode != FIXED_MODE and cfg.get("use_partial", True) and not position.get("partial_done"):
                return "PARTIAL_TARGET"
            return "TARGET"
        if ltp <= stop:
            return "STOP"
    else:
        if ltp <= target:
            if mode != FIXED_MODE and cfg.get("use_partial", True) and not position.get("partial_done"):
                return "PARTIAL_TARGET"
            return "TARGET"
        if ltp >= stop:
            return "STOP"
    return None


PINESCRIPT = r'''//@version=6
strategy("VWAP x EMA Cross | Smart Profit Trail", overlay=true,
         process_orders_on_close=true,
         default_qty_type=strategy.fixed, default_qty_value=2, // Set to 2+ if using 50% partial exit
         initial_capital=1000000)

// ───────── Inputs ─────────
emaLen     = input.int(9, "EMA length", minval=1, group="Strategy")
rr         = input.float(2.0, "Target Risk : Reward", minval=0.5, step=0.25, group="Strategy")

// Trailing & Management
trailMode  = input.string("EMA Trail", "Trailing Method", 
             options=["None (Fixed RR)", "EMA Trail", "ATR Trail", "Candle Low/High"], group="Profit Trailing")
usePartial = input.bool(true, "Book 50% profit at Target RR & trail runner", group="Profit Trailing")
trailStartR = input.float(1.0, "Activate trailing after (R multiple)", minval=0.0, step=0.25, group="Profit Trailing")
useBE      = input.bool(true, "Move SL to Breakeven at trigger R", group="Profit Trailing")
atrLen     = input.int(14, "ATR Length (for ATR Trail)", minval=1, group="Profit Trailing")
atrMult    = input.float(2.0, "ATR Multiplier", minval=0.5, step=0.25, group="Profit Trailing")

// Session & Filters
useSess    = input.bool(false, "Limit trading to a session", group="Session")
tradeSess  = input.session("0915-1500", "Trading session", group="Session")
tz         = input.string("Asia/Kolkata", "Timezone", group="Session")
closeEOD   = input.bool(true, "Close open trade when session ends", group="Session")
oneAtATime = input.bool(true, "Only one trade at a time", group="Trade")
showSL     = input.bool(true, "Show stop / target lines", group="Display")

// ───────── Indicators ─────────
ema    = ta.ema(close, emaLen)
vwap   = ta.vwap(hlc3)
atrVal = ta.atr(atrLen)

// ───────── Cross detection ─────────
longCross  = ta.crossover(ema, vwap)
shortCross = ta.crossunder(ema, vwap)

inSess  = not useSess or not na(time(timeframe.period, tradeSess, tz))
flat    = strategy.position_size == 0
canTake = inSess and (not oneAtATime or flat)

// ───────── State Variables ─────────
var float entryPx   = na
var float stopPx    = na
var float tpPx      = na
var float riskPx    = na
var float extremePx = na
var bool  trailOn   = false
var int   entryBar  = na

// ───────── Entries ─────────
if longCross and canTake
    sl   = low[1]
    risk = close - sl
    if risk > 0
        entryPx   := close
        stopPx    := sl
        riskPx    := risk
        tpPx      := close + risk * rr
        extremePx := high
        trailOn   := false
        entryBar  := bar_index
        strategy.entry("Long", strategy.long)

if shortCross and canTake
    sl   = high[1]
    risk = sl - close
    if risk > 0
        entryPx   := close
        stopPx    := sl
        riskPx    := risk
        tpPx      := close - risk * rr
        extremePx := low
        trailOn   := false
        entryBar  := bar_index
        strategy.entry("Short", strategy.short)

// ───────── Dynamic Profit Trailing Logic ─────────
if strategy.position_size > 0 and bar_index > entryBar
    extremePx := math.max(extremePx, high)
    
    // Check if price hit the R-multiple trigger to start trailing
    if not trailOn and high >= entryPx + (riskPx * trailStartR)
        trailOn := true
        if useBE
            stopPx := math.max(stopPx, entryPx)

    // Ratchet stop-loss upward (never moves down)
    if trailOn and trailMode != "None (Fixed RR)"
        float candidateSL = stopPx
        if trailMode == "EMA Trail"
            candidateSL := ema
        else if trailMode == "ATR Trail"
            candidateSL := extremePx - (atrVal * atrMult)
        else if trailMode == "Candle Low/High"
            candidateSL := low[1]
            
        // Only update if candidateSL is below current price and higher than old SL
        if candidateSL < close
            stopPx := math.max(stopPx, candidateSL)

if strategy.position_size < 0 and bar_index > entryBar
    extremePx := math.min(extremePx, low)
    
    if not trailOn and low <= entryPx - (riskPx * trailStartR)
        trailOn := true
        if useBE
            stopPx := math.min(stopPx, entryPx)

    if trailOn and trailMode != "None (Fixed RR)"
        float candidateSL = stopPx
        if trailMode == "EMA Trail"
            candidateSL := ema
        else if trailMode == "ATR Trail"
            candidateSL := extremePx + (atrVal * atrMult)
        else if trailMode == "Candle Low/High"
            candidateSL := high[1]
            
        if candidateSL > close
            stopPx := math.min(stopPx, candidateSL)

// ───────── Exit Execution ─────────
if strategy.position_size > 0
    if trailMode == "None (Fixed RR)"
        strategy.exit("Long Exit", "Long", stop=stopPx, limit=tpPx)
    else if usePartial
        // Close 50% at 1:2 RR, let remaining 50% run on the trailing stop
        strategy.exit("Long Partial", "Long", qty_percent=50, stop=stopPx, limit=tpPx)
        strategy.exit("Long Runner",  "Long", stop=stopPx)
    else
        // 100% runner on trailing stop (no upper limit cap)
        strategy.exit("Long Trail", "Long", stop=stopPx)

if strategy.position_size < 0
    if trailMode == "None (Fixed RR)"
        strategy.exit("Short Exit", "Short", stop=stopPx, limit=tpPx)
    else if usePartial
        strategy.exit("Short Partial", "Short", qty_percent=50, stop=stopPx, limit=tpPx)
        strategy.exit("Short Runner",  "Short", stop=stopPx)
    else
        strategy.exit("Short Trail", "Short", stop=stopPx)

// ───────── End-of-Session Exit ─────────
if closeEOD and useSess and not inSess and strategy.position_size != 0
    strategy.close_all("EOD")

// ───────── Plots ─────────
plot(ema,  "EMA",  color.new(color.yellow, 0), 2)
plot(vwap, "VWAP", color.new(color.blue, 0),   2)
plot(showSL and strategy.position_size != 0 ? stopPx : na, "Trailing Stop", color.new(color.red, 0), 2, plot.style_linebr)
plot(showSL and strategy.position_size != 0 and (trailMode == "None (Fixed RR)" or usePartial) ? tpPx : na, "Target", color.new(color.lime, 0), 2, plot.style_linebr)
plotshape(longCross,  "Long",  shape.triangleup,   location.belowbar, color.green, size=size.small)
plotshape(shortCross, "Short", shape.triangledown, location.abovebar, color.red,   size=size.small)
'''
