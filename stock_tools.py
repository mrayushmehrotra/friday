import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

try:
    import yfinance as yf
except ImportError:
    print("yfinance not installed. Run: pip install yfinance")
    sys.exit(1)

INDIAN_INDICES = {"^NSEI", "^BSESN", "^NSEBANK"}
_CHART_CACHE = {}
_CHART_TTL = 12  # Yahoo chart quotes are delayed anyway; avoids 429 on 3s watchlist polls

def _resolve_ticker(ticker: str) -> str:
    t = ticker.upper().strip()
    if t in INDIAN_INDICES or t.endswith(".NS") or t.endswith(".BO"):
        return t
    if re.match(r"^[A-Z0-9&.-]{1,20}$", t):
        return t + ".NS"
    safe = re.sub(r"[^A-Z0-9]", "", t)
    if safe:
        return safe + ".NS"
    return t


def _chart_quote(ticker: str) -> Optional[Dict]:
    """Read quote metadata from Yahoo's public chart endpoint.

    yfinance's quoteSummary calls require a crumb/cookie and now fail with
    `Invalid Crumb` for many sessions. The chart endpoint is open and carries
    everything the terminal header needs except market cap / P/E, which are
    optional here. This is now the only quote path; on errors we return no
    quote rather than falling back to the broken crumb-gated APIs.
    """
    quoted = urllib.parse.quote(ticker, safe="")
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120 Safari/537.36",
        "Accept": "application/json",
    }
    payload = None
    for host in ("query1", "query2"):
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{quoted}?range=5d&interval=1d"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=12) as response:
                payload = json.load(response)
            break
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and host == "query1":
                continue  # try the second chart host
            raise
    if payload is None:
        raise LookupError("No response from Yahoo chart API")

    chart = payload.get("chart") or {}
    error = chart.get("error") or {}
    if error.get("code") == "Not Found" or not chart.get("result"):
        raise LookupError(error.get("description") or "Symbol not found on Yahoo Finance")

    result = chart["result"][0]
    meta = result.get("meta") or {}
    price = meta.get("regularMarketPrice") or meta.get("previousClose")
    if price is None:
        return None
    quote = (result.get("indicators") or {}).get("quote") or [{}]
    raw_closes = quote[0].get("close") or []
    closes = [v for v in raw_closes if v is not None]
    if raw_closes and raw_closes[-1] is None and closes:
        # Today's daily bar is still forming; last non-null close is yesterday.
        prev_close = closes[-1]
    elif len(closes) >= 2:
        prev_close = closes[-2]
    else:
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")

    change = price - prev_close if prev_close is not None else None
    change_pct = (change / prev_close * 100) if change is not None and prev_close else None

    opens = [v for v in (quote[0].get("open") or []) if v is not None]
    return {
        "symbol": ticker.upper(),
        "company": meta.get("longName") or meta.get("shortName") or ticker.upper(),
        "price": price,
        "change": round(change, 2) if change is not None else None,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "prev_close": prev_close,
        "open": opens[-1] if opens else None,
        "high": meta.get("regularMarketDayHigh"),
        "low": meta.get("regularMarketDayLow"),
        "volume": meta.get("regularMarketVolume"),
        "avg_volume": None,
        "market_cap": None,
        "pe_ratio": None,
        "dividend_yield": None,
        "fifty_two_week_high": meta.get("fiftyTwoWeekHigh"),
        "fifty_two_week_low": meta.get("fiftyTwoWeekLow"),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "currency": meta.get("currency"),
    }


def get_stock_data(ticker: str) -> Optional[Dict]:
    ticker = _resolve_ticker(ticker)
    cached = _CHART_CACHE.get(ticker)
    if cached and time.time() - cached[0] < cached[2]:
        return cached[1]

    try:
        quote = _chart_quote(ticker)
        if quote:
            _CHART_CACHE[ticker] = (time.time(), quote, _CHART_TTL)
            return quote
    except LookupError:
        _CHART_CACHE[ticker] = (time.time(), None, 300)
        return None
    except urllib.error.HTTPError as exc:
        # 404 = delisted/renamed, 429 = rate limited, 5xx = upstream issue.
        # Never fall back to yfinance's crumb-gated quoteSummary: it only
        # produces the same symbol errors plus noisy HTTP traces.
        ttl = 300 if exc.code == 404 else 60
        _CHART_CACHE[ticker] = (time.time(), None, ttl)
        return None
    except Exception:
        _CHART_CACHE[ticker] = (time.time(), None, 30)
        return None
    return None


def get_stock_news(ticker: str, max_articles: int = 10) -> List[Dict]:
    if not get_stock_data(ticker):
        return []
    stock = yf.Ticker(ticker)
    news = stock.news or []
    results = []
    for article in news[:max_articles]:
        content = article.get("content", {})
        results.append({
            "title": content.get("title"),
            "publisher": content.get("provider", {}).get("displayName"),
            "link": (
                content.get("clickThroughUrl", {}).get("url")
                or content.get("canonicalUrl", {}).get("url")
            ),
            "summary": content.get("summary"),
            "pub_date": content.get("pubDate"),
            "type": content.get("contentType"),
            "thumbnail": (
                content.get("thumbnail", {}).get("originalUrl")
                if content.get("thumbnail")
                else None
            ),
        })
    return results


def format_data(data: Dict) -> str:
    symbol = data["symbol"].replace(".NS", "")
    company = data["company"]
    price = data["price"]
    change = data["change"]
    change_pct = data["change_pct"]
    sign = "+" if change is not None and change >= 0 else ""
    ccy = "₹" if data.get("currency") == "INR" else (data["currency"] or "")

    lines = [
        f"{symbol} - {company}",
        f"Price: {ccy}{price}",
        f"Change: {sign}{ccy}{change} ({sign}{change_pct}%)" if change is not None else "",
        f"Open: {ccy}{data['open']}  |  High: {ccy}{data['high']}  |  Low: {ccy}{data['low']}",
        f"Volume: {_fmt_num(data['volume'])}" if data["volume"] else "",
        f"Avg Volume: {_fmt_num(data['avg_volume'])}" if data["avg_volume"] else "",
        f"Market Cap: {_fmt_num(data['market_cap'])}" if data["market_cap"] else "",
        f"P/E: {data['pe_ratio']}" if data["pe_ratio"] else "",
        f"52W High: {ccy}{data['fifty_two_week_high']}  |  52W Low: {ccy}{data['fifty_two_week_low']}",
    ]
    return "\n".join(line for line in lines if line)


def _fmt_num(n):
    if n is None:
        return ""
    if n >= 1e12:
        return f"{n/1e12:.2f}T"
    if n >= 1e7:
        return f"{n/1e7:.2f}Cr"
    if n >= 1e5:
        return f"{n/1e5:.2f}L"
    return f"{n:,}"


def format_news(news: List[Dict]) -> str:
    if not news:
        return "No news available."
    lines = []
    for i, article in enumerate(news, 1):
        lines.append(f"{i}. {article['title']}")
        if article.get("publisher"):
            lines.append(f"   Publisher: {article['publisher']}")
        if article.get("pub_date"):
            lines.append(f"   Date: {article['pub_date']}")
        if article.get("summary"):
            import re
            clean = re.sub(r"<[^>]+>", "", article["summary"])
            lines.append(f"   {clean[:200]}{'...' if len(clean) > 200 else ''}")
        if article.get("link"):
            lines.append(f"   {article['link']}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stock data and news via yfinance (Indian market)")
    parser.add_argument("ticker", help="Stock ticker (e.g. RELIANCE, TCS, HDFCBANK, ^NSEI)")
    parser.add_argument("--news", "-n", type=int, nargs="?", const=10, default=0,
                        help="Fetch news (optional: specify article count)")
    parser.add_argument("--json", "-j", action="store_true", help="Output as JSON")
    parser.add_argument("--bse", action="store_true", help="Use BSE suffix (.BO) instead of NSE")

    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    if args.bse and not ticker.endswith(".BO") and ticker not in INDIAN_INDICES:
        ticker = ticker.replace(".NS", "") + ".BO"

    data = get_stock_data(ticker)
    if not data:
        print(f"No data found for {ticker}")
        sys.exit(1)

    news = []
    if args.news:
        news = get_stock_news(ticker, args.news)

    if args.json:
        output = {"data": data, "news": news}
        print(json.dumps(output, indent=2, default=str))
    else:
        print(format_data(data))
        if news:
            print("\n--- News ---")
            print(format_news(news))
