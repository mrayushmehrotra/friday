#!/usr/bin/env python3
"""
gex.py — Gamma Exposure (GEX) analytics for NIFTY 50 and SENSEX.

Data source: INDstocks (INDmoney) `/market/option-chain` — one call per
index/expiry returns the full strike ladder *with pre-calculated Greeks*
(delta, gamma, theta, vega) and IV for both CE and PE, so no local
Black-Scholes model is needed.

Reference: assets/indstocks-api-docs.md (see "Option Chain").

Sign convention (dealer positioning, the one used by most GEX dashboards):
customers are assumed to be net call buyers / net put writers, so dealers are
short calls (negative gamma) and long puts (positive gamma):

    net GEX(strike) = (-CE_OI * CE_gamma + PE_OI * PE_gamma)
                      * lot_size * spot * 0.01     # ₹ per 1% move

Positive net GEX  -> dealers long gamma, they sell rallies / buy dips:
                     volatility is suppressed, WRITERS (sellers) in control.
Negative net GEX  -> dealers short gamma, they chase the move:
                     trends accelerate, BUYERS in control.

All this is an estimate from end-of-day OI; it is not investment advice.
"""

import json
import os
import time
from datetime import date, datetime

import requests

from bullish_put_filter import get_token

HERE = os.path.dirname(os.path.abspath(__file__))
INDEX_META_PATH = os.path.join(HERE, "assets", "indices_with_options.json")
DISK_CACHE_PATH = os.path.join(HERE, "assets", "gex_last_good.json")
API_URL = "https://api.indstocks.com/market/option-chain"

# Key -> (display name, exchange, underlying security id, lot size).
# Lot sizes come from assets/indstocks_index_master.csv via the generated
# indices_with_options.json; kept here as a fallback default.
INDICES = {
    "NIFTY": ("NIFTY 50", "NSE", "40000001", 65),
    "SENSEX": ("SENSEX", "BSE", "40000006", 25),
}

_CACHE_TTL_SEC = 60  # live quotes; refresh at most once a minute per key
_CACHE = {}


# ---------------------------------------------------------------------------
# Expiry discovery
# ---------------------------------------------------------------------------

def load_index_meta() -> dict:
    """Load the generated INDstocks index master (expiries + lot sizes)."""
    try:
        with open(INDEX_META_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return {i["symbol"].upper(): i for i in data.get("indices", [])}
    except (OSError, ValueError, TypeError):
        return {}


def available_expiries(index_key: str, today: date | None = None) -> list[str]:
    """Upcoming expiries for an index, newest master first; never in the past."""
    today = today or date.today()
    meta = load_index_meta().get(index_key.upper(), {})
    dates = meta.get("upcoming_expiries") or []
    if meta.get("nearest_expiry"):
        dates = [meta["nearest_expiry"]] + dates
    return sorted({d for d in dates if _parse_date(d) >= today})


def pick_expiry(index_key: str, today: date | None = None) -> str | None:
    """Nearest upcoming expiry for an index."""
    expiries = available_expiries(index_key, today)
    return expiries[0] if expiries else None


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


# ---------------------------------------------------------------------------
# INDstocks API
# ---------------------------------------------------------------------------

def fetch_chain(index_key: str, expiry: str | None = None,
                strike_count: int = 15, request_get=None) -> dict:
    """Fetch + normalise the option chain for one index and expiry."""
    key = index_key.upper()
    if key not in INDICES:
        raise ValueError(f"unsupported index {index_key!r}; use NIFTY or SENSEX")
    _, exchange, security_id, _ = INDICES[key]
    expiry = expiry or pick_expiry(key)
    if not expiry:
        raise ValueError(f"no upcoming expiry found for {key} — refresh "
                         "assets/indices_with_options.json via fetch_option_stocks.py")

    resp = (request_get or requests.get)(
        API_URL,
        params={
            "exchange": exchange,
            "segment": "INDEX",
            "underlying-scrip": security_id,
            "expiry": expiry,
            "strike_count": max(3, min(int(strike_count), 30)),
        },
        headers={"Authorization": get_token()},
        timeout=20,
    )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code in (401, 403):
            raise RuntimeError(
                "INDmoney option-chain access token expired or revoked. "
                "Refresh INDMONEY_API_TOKEN in .env (or reconnect the INDmoney bot) "
                "to restore live Greeks."
            ) from exc
        raise
    payload = resp.json()
    if payload.get("status") != "success" or not isinstance(payload.get("data"), dict):
        raise ValueError(str(payload.get("message") or payload.get("error")
                             or "unexpected option-chain response"))

    data = payload["data"]
    raw = data.get("strikes") or {}
    strikes = []
    for strike_key, legs in raw.items():
        ce, pe = legs.get("ce") or {}, legs.get("pe") or {}
        strikes.append({
            "strike": float(strike_key),
            "ce": _normalise_leg(ce),
            "pe": _normalise_leg(pe),
        })
    strikes.sort(key=lambda r: r["strike"])
    if not strikes:
        raise ValueError("option chain returned no strikes")

    return {
        "index": key,
        "name": INDICES[key][0],
        "expiry": data.get("expiry") or expiry,
        "underlying_ltp": float(data.get("underlying_ltp") or 0),
        "expiries": available_expiries(key),
        "strikes": strikes,
    }


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalise_leg(leg: dict) -> dict:
    greeks = leg.get("greeks") or {}
    return {
        "security_id": leg.get("security_id"),
        "symbol": leg.get("trading_symbol"),
        "ltp": _num(leg.get("last_price")),
        "oi": _num(leg.get("oi")),
        "prev_oi": _num(leg.get("previous_oi")),
        "volume": _num(leg.get("volume")),
        "iv": _num(leg.get("iv")),
        "delta": _num(greeks.get("delta")),
        "gamma": _num(greeks.get("gamma")),
        "theta": _num(greeks.get("theta")),
        "vega": _num(greeks.get("vega")),
    }


# ---------------------------------------------------------------------------
# GEX maths
# ---------------------------------------------------------------------------

def _interpolate(x1: float, y1: float, x2: float, y2: float) -> float:
    if abs(y2 - y1) < 1e-12:
        return x1
    return x1 + (0.0 - y1) * (x2 - x1) / (y2 - y1)


def max_pain(strikes: list[dict]) -> float | None:
    """Strike with the least total intrinsic value for option writers."""
    if not strikes:
        return None
    best_strike, best_cost = None, float("inf")
    for candidate in strikes:
        k = candidate["strike"]
        cost = 0.0
        for row in strikes:
            s = row["strike"]
            cost += row["ce"]["oi"] * max(0.0, k - s)
            cost += row["pe"]["oi"] * max(0.0, s - k)
        if cost < best_cost:
            best_strike, best_cost = k, cost
    return best_strike


def analyze_chain(chain: dict, lot_size: int) -> dict:
    """Turn a normalised chain into GEX levels, Greeks table and the verdict."""
    strikes = chain["strikes"]
    spot = chain["underlying_ltp"] or strikes[len(strikes) // 2]["strike"]
    per_pct = lot_size * spot * 0.01  # ₹ of underlying per 1% move, per lot

    rows = []
    cumulative = 0.0
    flip = None
    prev = None
    for r in strikes:
        ce, pe = r["ce"], r["pe"]
        call_gex = -ce["oi"] * ce["gamma"] * per_pct
        put_gex = pe["oi"] * pe["gamma"] * per_pct
        net_gex = call_gex + put_gex
        # Spot crossing this strike flips the sign of cumulative dealer gamma.
        if prev and prev["cumulative"] * cumulative < 0 and flip is None:
            flip = round(_interpolate(prev["strike"], prev["cumulative"],
                                      r["strike"], cumulative), 2)
        prev = {"strike": r["strike"], "cumulative": cumulative}
        rows.append({
            "strike": r["strike"],
            "ce": ce, "pe": pe,
            "ce_oi_change": ce["oi"] - ce["prev_oi"],
            "pe_oi_change": pe["oi"] - pe["prev_oi"],
            "call_gex_cr": round(call_gex / 1e7, 2),
            "put_gex_cr": round(put_gex / 1e7, 2),
            "net_gex_cr": round(net_gex / 1e7, 2),
            "net_delta": ce["oi"] * ce["delta"] + pe["oi"] * pe["delta"],
        })
        cumulative += net_gex

    total_ce_oi = sum(r["ce"]["oi"] for r in strikes)
    total_pe_oi = sum(r["pe"]["oi"] for r in strikes)
    total_ce_vol = sum(r["ce"]["volume"] for r in strikes)
    total_pe_vol = sum(r["pe"]["volume"] for r in strikes)
    total_ce_change = sum(r["ce"]["oi"] - r["ce"]["prev_oi"] for r in strikes)
    total_pe_change = sum(r["pe"]["oi"] - r["pe"]["prev_oi"] for r in strikes)
    avg_iv = (sum(r["ce"]["iv"] + r["pe"]["iv"] for r in strikes)
              / (2 * len(strikes)))

    pcr_oi = total_pe_oi / total_ce_oi if total_ce_oi else None
    pcr_vol = total_pe_vol / total_ce_vol if total_ce_vol else None
    net_gex_cr = cumulative / 1e7

    # Verdict: sign of net dealer gamma decides who is in control of the next
    # move. OI change and PCR are shown alongside as corroborating flow.
    if net_gex_cr > 0:
        control, tone, reason = (
            "SELLERS IN CONTROL", "sellers",
            "Dealers are long gamma (positive GEX) — they sell rallies and "
            "buy dips, dampening volatility. Range-bound / mean-reverting.")
    elif net_gex_cr < 0:
        control, tone, reason = (
            "BUYERS IN CONTROL", "buyers",
            "Dealers are short gamma (negative GEX) — they must chase price "
            "moves, amplifying trends. Breakouts can accelerate.")
    else:
        control, tone, reason = (
            "NEUTRAL", "neutral",
            "Dealer gamma is balanced — no clear hedging bias.")

    if flip is not None:
        if spot > flip:
            zone = "Above gamma flip — hedging supports the uptrend"
        else:
            zone = "Below gamma flip — hedging pressures the downside"
    else:
        zone = "No gamma flip inside the fetched strike range"

    strongest = max(rows, key=lambda r: abs(r["net_gex_cr"])) if rows else None

    return {
        **chain,
        "lot_size": lot_size,
        "gex_cr": round(net_gex_cr, 2),
        "call_gex_cr": round(sum(r["call_gex_cr"] for r in rows), 2),
        "put_gex_cr": round(sum(r["put_gex_cr"] for r in rows), 2),
        "gamma_flip": flip,
        "spot_vs_flip": zone,
        "max_pain": max_pain(strikes),
        "pcr_oi": round(pcr_oi, 3) if pcr_oi is not None else None,
        "pcr_volume": round(pcr_vol, 3) if pcr_vol is not None else None,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "ce_oi_change": total_ce_change,
        "pe_oi_change": total_pe_change,
        "avg_iv": round(avg_iv, 2),
        "control": control,
        "control_tone": tone,
        "control_reason": reason,
        "strongest_gamma_strike": strongest["strike"] if strongest else None,
        "rows": rows,
        "source": "INDstocks (INDmoney) option chain — Greeks supplied by the API",
    }


def _load_disk_cache() -> dict:
    try:
        with open(DISK_CACHE_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _save_disk_cache(cache_key: str, result: dict):
    try:
        cache = _load_disk_cache()
        cache[cache_key] = result
        os.makedirs(os.path.dirname(DISK_CACHE_PATH), exist_ok=True)
        with open(DISK_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(cache, f, default=str)
    except (OSError, TypeError, ValueError):
        pass  # caching is best-effort; live fetch errors are still reported


def get_gex(index_key: str, expiry: str | None = None,
            strike_count: int = 15) -> dict:
    """Cached wrapper used by the dashboard endpoint.

    Falls back to the last successful snapshot if the live option-chain call
    fails (e.g. token expiry), marking the payload ``stale``.
    """
    key = (index_key.upper(), expiry, int(strike_count))
    cache_key = "|".join(str(k) for k in key)
    hit = _CACHE.get(key)
    now = time.time()
    if hit and now - hit[0] < _CACHE_TTL_SEC:
        return hit[1]
    try:
        chain = fetch_chain(index_key, expiry, strike_count)
    except Exception as exc:
        cached = _load_disk_cache().get(cache_key)
        if cached:
            stale = dict(cached)
            stale["stale"] = True
            stale["stale_reason"] = str(exc)
            stale["source"] = str(cached.get("source", "")) + " (last good cached snapshot)"
            return stale
        raise
    lot = load_index_meta().get(key[0], {}).get("lot_size") or INDICES[key[0]][3]
    result = analyze_chain(chain, int(lot))
    result["stale"] = False
    _CACHE[key] = (now, result)
    _save_disk_cache(cache_key, result)
    return result
