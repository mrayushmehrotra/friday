#!/usr/bin/env python3
"""
news_events_engine.py - High-speed multi-pipeline news and corporate events aggregator.

Pipelines:
1. Official Exchange Events:
   - Corporate Actions (Dividends, Splits, Bonus, Rights) via NSE API
   - Corporate Filings & Announcements with official PDF URLs via NSE API
2. Stock-Specific Real-Time News:
   - Dynamic Google News RSS (aggregated across Moneycontrol, ET, LiveMint, CNBC, Reuters)
   - Yahoo Finance News (tagged ticker news)
   - Deduplicated, sorted, and formatted
3. Market-Wide Breaking Wire:
   - Aggregated RSS from Economic Times Markets, LiveMint Markets, Google News India
   - Automated stock keyword and ticker tagging
"""

import datetime
import email.utils
import html
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional, Tuple

import requests

# In-memory TTL caches
_EVENTS_CACHE: Dict[str, Tuple[float, dict]] = {}
_NEWS_CACHE: Dict[str, Tuple[float, dict]] = {}
_MARKET_WIRE_CACHE: Dict[str, Tuple[float, list]] = {}

CACHE_TTL_EVENTS = 900       # 15 minutes
CACHE_TTL_NEWS = 600         # 10 minutes
CACHE_TTL_WIRE = 300         # 5 minutes

_NSE_SESSION = threading.local()

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Ticker tagging dictionary for breaking market news
TICKER_TAGS = {
    "RELIANCE": [r"\breliance\b", r"\bril\b", r"\bmukesh ambani\b"],
    "TCS": [r"\btcs\b", r"\btata consultancy\b"],
    "INFY": [r"\binfosys\b", r"\binfy\b"],
    "HDFCBANK": [r"\bhdfc bank\b", r"\bhdfc\b"],
    "ICICIBANK": [r"\bicici bank\b", r"\bicici\b"],
    "SBIN": [r"\bstate bank of india\b", r"\bsbi\b"],
    "BHARTIARTL": [r"\bbharti airtel\b", r"\bairtel\b"],
    "ITC": [r"\bitc\b"],
    "LT": [r"\blarsen & toubro\b", r"\bl&t\b", r"\blarsen\b"],
    "BAJFINANCE": [r"\bbajaj finance\b"],
    "MARUTI": [r"\bmaruti suzuki\b", r"\bmaruti\b"],
    "TATAMOTORS": [r"\btata motors\b", r"\btamo\b"],
    "SUNPHARMA": [r"\bsun pharma\b", r"\bsun pharmaceutical\b"],
    "TITAN": [r"\btitan company\b", r"\btitan\b"],
    "ADANIENT": [r"\badani enterprises\b", r"\badani\b"],
    "ADANIPORTS": [r"\badani ports\b"],
    "ASIANPAINT": [r"\basian paints\b"],
    "AXISBANK": [r"\baxis bank\b"],
    "BAJAJFINSV": [r"\bbajaj finserv\b"],
    "BPCL": [r"\bbpcl\b", r"\bbharat petroleum\b"],
    "CIPLA": [r"\bcipla\b"],
    "COALINDIA": [r"\bcoal india\b"],
    "DRREDDY": [r"\bdr\.? reddy\b"],
    "EICHERMOT": [r"\beicher motors\b", r"\broyal enfield\b"],
    "GRASIM": [r"\bgrasim\b"],
    "HCLTECH": [r"\bhcl tech\b", r"\bhcl\b"],
    "HDFCLIFE": [r"\bhdfc life\b"],
    "HEROMOTOCO": [r"\bhero motocorp\b", r"\bhero moto\b"],
    "HINDALCO": [r"\bhindalco\b"],
    "HINDUNILVR": [r"\bhindustan unilever\b", r"\bhul\b"],
    "INDUSINDBK": [r"\bindusind bank\b"],
    "JSWSTEEL": [r"\bjsw steel\b", r"\bjsw\b"],
    "KOTAKBANK": [r"\bkotak mahindra\b", r"\bkotak bank\b"],
    "M&M": [r"\bmahindra & mahindra\b", r"\bm&m\b"],
    "NESTLEIND": [r"\bnestle india\b", r"\bnestle\b"],
    "NTPC": [r"\bntpc\b"],
    "ONGC": [r"\bongc\b"],
    "POWERGRID": [r"\bpower grid\b"],
    "SBILIFE": [r"\bsbi life\b"],
    "TATASTEEL": [r"\btata steel\b"],
    "TECHM": [r"\btech mahindra\b"],
    "ULTRACEMCO": [r"\bultratech cement\b"],
    "WIPRO": [r"\bwipro\b"],
    "ZOMATO": [r"\bzomato\b"],
    "PAYTM": [r"\bpaytm\b", r"\bone97\b"],
    "JIOFIN": [r"\bjio financial\b", r"\bjio finance\b"],
    "HAL": [r"\bhindustan aeronautics\b", r"\bhal\b"],
    "BEL": [r"\bbharat electronics\b", r"\bbel\b"],
    "VEDL": [r"\bvedanta\b"],
    "TRENT": [r"\btrent\b"],
    "NIFTY": [r"\bnifty 50\b", r"\bnifty\b"],
    "SENSEX": [r"\bsensex\b"],
}

_COMPILED_TAGS = {
    sym: [re.compile(pat, re.IGNORECASE) for pat in patterns]
    for sym, patterns in TICKER_TAGS.items()
}


def _get_nse_session() -> requests.Session:
    """Return a thread-local requests session authenticated with NSE cookies."""
    if not hasattr(_NSE_SESSION, "session") or _NSE_SESSION.session is None:
        s = requests.Session()
        s.headers.update(BROWSER_HEADERS)
        try:
            s.get("https://www.nseindia.com", timeout=12)
        except Exception:
            pass
        _NSE_SESSION.session = s
    return _NSE_SESSION.session


def _clean_str(val: Optional[str]) -> str:
    if not val:
        return ""
    text = html.unescape(str(val).strip())
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _format_time_ago(dt_str: Optional[str]) -> str:
    """Convert RFC 822 / ISO date strings to human relative time (e.g. 2h ago, 1d ago)."""
    if not dt_str:
        return ""
    try:
        dt = email.utils.parsedate_to_datetime(dt_str)
        now = datetime.datetime.now(datetime.timezone.utc)
        diff = max(0, (now - dt).total_seconds())
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        days = int(diff // 86400)
        return f"{days}d ago" if days < 30 else dt.strftime("%d %b")
    except Exception:
        # Try custom NSE format: 19-Nov-2026 18:35:25
        try:
            m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", dt_str)
            if m:
                return f"{m.group(1)} {m.group(2)}"
        except Exception:
            pass
        return dt_str


def tag_text(text: str) -> List[str]:
    """Find all matching stock tickers mentioned in a title or text."""
    if not text:
        return []
    tags = []
    for sym, regexes in _COMPILED_TAGS.items():
        if any(rgx.search(text) for rgx in regexes):
            tags.append(sym)
    return tags


# ----------------------------------------------------------------------
# Pipeline 1: Official Exchange Corporate Events (NSE Actions & Filings)
# ----------------------------------------------------------------------
def fetch_corporate_events(symbol: str, force_refresh: bool = False) -> dict:
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    if clean_sym in ("NIFTY", "BANKNIFTY", "SENSEX", "^NSEI", "^NSEBANK"):
        return {
            "symbol": clean_sym,
            "is_index": True,
            "actions": [],
            "announcements": [],
            "note": "Broad-market indices do not have direct corporate actions or board meetings.",
        }

    now = time.time()
    if not force_refresh and clean_sym in _EVENTS_CACHE:
        cached_ts, data = _EVENTS_CACHE[clean_sym]
        if now - cached_ts < CACHE_TTL_EVENTS:
            return data

    s = _get_nse_session()
    actions_raw = []
    announcements_raw = []

    # 1. Fetch Corporate Actions (Dividends, Splits, Bonus, Rights)
    try:
        url_actions = f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&symbol={urllib.parse.quote(clean_sym)}"
        r = s.get(
            url_actions,
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"},
            timeout=12,
        )
        if r.status_code == 200:
            actions_raw = r.json()
    except Exception as exc:
        print(f"[events] NSE actions error for {clean_sym}: {exc}")

    # 2. Fetch Corporate Announcements & Filings (Results, Order Wins, PDF attachments)
    try:
        url_ann = f"https://www.nseindia.com/api/corporate-announcements?index=equities&symbol={urllib.parse.quote(clean_sym)}"
        r = s.get(
            url_ann,
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
            timeout=12,
        )
        if r.status_code == 200:
            announcements_raw = r.json()
    except Exception as exc:
        print(f"[events] NSE announcements error for {clean_sym}: {exc}")

    # Parse and structure Corporate Actions
    parsed_actions = []
    for a in (actions_raw or [])[:25]:
        subj = _clean_str(a.get("subject", ""))
        subj_l = subj.lower()
        kind = "ACTION"
        if "dividend" in subj_l:
            kind = "DIVIDEND"
        elif "split" in subj_l:
            kind = "SPLIT"
        elif "bonus" in subj_l:
            kind = "BONUS"
        elif "rights" in subj_l:
            kind = "RIGHTS"
        elif "agm" in subj_l or "egm" in subj_l:
            kind = "AGM"

        # Extract amount if present
        amount_match = re.search(r"(?:rs\.?|re\.?|inr|₹)\s*([\d\.]+)", subj_l)
        ratio_match = re.search(r"(\d+:\d+)", subj_l)
        details = (
            f"₹{amount_match.group(1)}/share"
            if amount_match
            else (f"Ratio {ratio_match.group(1)}" if ratio_match else "")
        )

        parsed_actions.append({
            "kind": kind,
            "subject": subj,
            "details": details,
            "ex_date": a.get("exDate") or "—",
            "record_date": a.get("recDate") or "—",
            "bc_start": a.get("bcStartDate") or "—",
            "bc_end": a.get("bcEndDate") or "—",
            "company": a.get("comp") or clean_sym,
        })

    # Parse and structure Corporate Filings & Announcements
    parsed_announcements = []
    for m in (announcements_raw or [])[:30]:
        pdf = m.get("attchmntFile")
        pdf_url = None
        if pdf and isinstance(pdf, str) and pdf.strip() and pdf.strip() != "-":
            pdf = pdf.strip()
            if pdf.startswith("http://") or pdf.startswith("https://"):
                pdf_url = pdf
            else:
                pdf_url = f"https://nsearchives.nseindia.com/corporate/{pdf}"

        date_str = m.get("an_dt") or m.get("sort_date") or ""
        desc_str = _clean_str(m.get("desc") or "Corporate Filing")
        text_str = _clean_str(m.get("attchmntText") or "")
        summary_str = _clean_str(m.get("voiceSummary") or "")

        # Categorize
        cat = "FILING"
        if "result" in desc_str.lower() or "financial" in desc_str.lower():
            cat = "RESULTS"
        elif "meeting" in desc_str.lower() or "board" in desc_str.lower():
            cat = "BOARD"
        elif "dividend" in desc_str.lower():
            cat = "DIVIDEND"
        elif "press" in desc_str.lower() or "media" in desc_str.lower():
            cat = "PRESS"

        parsed_announcements.append({
            "category": cat,
            "date": date_str,
            "time_ago": _format_time_ago(date_str),
            "desc": desc_str,
            "text": text_str[:280] + ("…" if len(text_str) > 280 else ""),
            "summary": summary_str,
            "pdf_url": pdf_url,
            "company": m.get("sm_name") or clean_sym,
        })

    result = {
        "symbol": clean_sym,
        "actions_count": len(parsed_actions),
        "actions": parsed_actions,
        "announcements_count": len(parsed_announcements),
        "announcements": parsed_announcements,
        "source": "NSE Official Corporate Filings",
        "cached_at": datetime.datetime.now().strftime("%H:%M:%S IST"),
    }
    _EVENTS_CACHE[clean_sym] = (now, result)
    return result


# ----------------------------------------------------------------------
# Pipeline 2: Real-Time Multi-Source Stock News (Google News + Yahoo)
# ----------------------------------------------------------------------
def fetch_stock_news(
    symbol: str, company_name: Optional[str] = None, count: int = 15, force_refresh: bool = False
) -> dict:
    clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
    now = time.time()
    if not force_refresh and clean_sym in _NEWS_CACHE:
        cached_ts, data = _NEWS_CACHE[clean_sym]
        if now - cached_ts < CACHE_TTL_NEWS:
            return data

    articles = []
    seen_titles = set()

    def _normalize_title(t: str) -> str:
        return re.sub(r"\W+", "", (t or "").lower())[:50]

    # Method A: Dynamic Google News RSS across Moneycontrol, ET, LiveMint, CNBC, etc.
    try:
        is_index = clean_sym in ("NIFTY", "BANKNIFTY", "SENSEX", "^NSEI", "^NSEBANK")
        if is_index:
            query = f"{clean_sym} 50 stock market India"
        else:
            q_comp = company_name or clean_sym
            # Strip legal suffixes like Ltd, Limited for better query recall
            q_clean = re.sub(r"\b(ltd|limited|corp|corporation|inc)\b", "", q_comp, flags=re.I).strip()
            query = f"{q_clean} {clean_sym} NSE stock"

        url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=8) as resp:
            root = ET.fromstring(resp.read())
            for it in root.findall(".//item"):
                raw_title = it.findtext("title") or ""
                # Google News titles are usually "Title - Publisher"
                src = it.findtext("source") or ""
                title = raw_title
                if not src and " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title, src = parts[0], parts[1]

                title = _clean_str(title)
                norm = _normalize_title(title)
                if not norm or norm in seen_titles:
                    continue
                seen_titles.add(norm)

                link = it.findtext("link") or ""
                pub_date = it.findtext("pubDate") or ""
                time_ago = _format_time_ago(pub_date)

                # Parse epoch timestamp for sorting
                ts = 0
                try:
                    dt = email.utils.parsedate_to_datetime(pub_date)
                    ts = dt.timestamp()
                except Exception:
                    pass

                articles.append({
                    "title": title,
                    "link": link,
                    "source": src or "Google News",
                    "pub_date": pub_date,
                    "time_ago": time_ago,
                    "timestamp": ts,
                    "origin": "Google News",
                })
    except Exception as exc:
        print(f"[news] Google News RSS error for {clean_sym}: {exc}")

    # Method B: Yahoo Finance News Endpoint (yfinance)
    try:
        import yfinance as yf
        yf_sym = f"{clean_sym}.NS" if not clean_sym.startswith("^") else clean_sym
        yf_ticker = yf.Ticker(yf_sym)
        y_news = getattr(yf_ticker, "news", []) or []
        for art in y_news[:10]:
            content = art.get("content", {}) if isinstance(art, dict) else {}
            title = _clean_str(content.get("title") or art.get("title") or "")
            norm = _normalize_title(title)
            if not norm or norm in seen_titles:
                continue
            seen_titles.add(norm)

            link = (
                content.get("clickThroughUrl", {}).get("url")
                or content.get("canonicalUrl", {}).get("url")
                or art.get("link")
                or ""
            )
            src = (
                content.get("provider", {}).get("displayName")
                or art.get("publisher")
                or "Yahoo Finance"
            )
            pub_date = content.get("pubDate") or ""
            ts = 0
            if pub_date:
                try:
                    dt = datetime.datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                    ts = dt.timestamp()
                except Exception:
                    pass

            articles.append({
                "title": title,
                "link": link,
                "source": src,
                "pub_date": pub_date,
                "time_ago": _format_time_ago(pub_date),
                "timestamp": ts,
                "origin": "Yahoo Finance",
            })
    except Exception as exc:
        if os.getenv("FRIDAY_DEBUG"):
            print(f"[news] Yahoo news error for {clean_sym}: {exc}")

    # Sort newest first
    articles.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    top_articles = articles[:count]

    result = {
        "symbol": clean_sym,
        "company": company_name or clean_sym,
        "count": len(top_articles),
        "articles": top_articles,
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S IST"),
    }
    _NEWS_CACHE[clean_sym] = (now, result)
    return result


# ----------------------------------------------------------------------
# Pipeline 3: Market-Wide Breaking Wire (ET, LiveMint, MC, Tagged)
# ----------------------------------------------------------------------
def fetch_market_wire(force_refresh: bool = False, limit: int = 50) -> dict:
    now = time.time()
    if not force_refresh and "wire" in _MARKET_WIRE_CACHE:
        cached_ts, data = _MARKET_WIRE_CACHE["wire"]
        if now - cached_ts < CACHE_TTL_WIRE:
            return data

    feeds = [
        ("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
        ("LiveMint Markets", "https://www.livemint.com/rss/markets"),
        ("Moneycontrol", "https://news.google.com/rss/search?q=site:moneycontrol.com+market+stocks&hl=en-IN&gl=IN&ceid=IN:en"),
        ("Business Standard", "https://news.google.com/rss/search?q=site:business-standard.com+markets+stocks&hl=en-IN&gl=IN&ceid=IN:en"),
    ]

    all_articles = []
    seen = set()

    for provider, feed_url in feeds:
        try:
            req = urllib.request.Request(feed_url, headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                root = ET.fromstring(resp.read())
                for item in root.findall(".//item"):
                    raw_title = item.findtext("title") or ""
                    title = _clean_str(raw_title)
                    norm = re.sub(r"\W+", "", title.lower())[:45]
                    if not norm or norm in seen:
                        continue
                    seen.add(norm)

                    link = item.findtext("link") or ""
                    pub_date = item.findtext("pubDate") or ""
                    time_ago = _format_time_ago(pub_date)
                    ts = 0
                    try:
                        dt = email.utils.parsedate_to_datetime(pub_date)
                        ts = dt.timestamp()
                    except Exception:
                        pass

                    desc = _clean_str(item.findtext("description") or "")
                    tags = tag_text(f"{title} {desc}")

                    all_articles.append({
                        "title": title,
                        "link": link,
                        "source": provider,
                        "pub_date": pub_date,
                        "time_ago": time_ago,
                        "timestamp": ts,
                        "tagged_symbols": tags,
                    })
        except Exception as exc:
            print(f"[wire] Error fetching {provider}: {exc}")

    # Sort descending by timestamp
    all_articles.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
    trimmed = all_articles[:limit]

    result = {
        "count": len(trimmed),
        "articles": trimmed,
        "sources": [f[0] for f in feeds],
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S IST"),
    }
    _MARKET_WIRE_CACHE["wire"] = (now, result)
    return result


_MARKET_FILINGS_CACHE: Dict[str, Tuple[float, dict]] = {}
_MARKET_ACTIONS_CACHE: Dict[str, Tuple[float, dict]] = {}


# ----------------------------------------------------------------------
# Pipeline 4: Market-Wide Corporate Filings & Announcements (NSE Live)
# ----------------------------------------------------------------------
def fetch_market_filings(force_refresh: bool = False, limit: int = 100) -> dict:
    now = time.time()
    if not force_refresh and "filings" in _MARKET_FILINGS_CACHE:
        cached_ts, data = _MARKET_FILINGS_CACHE["filings"]
        if now - cached_ts < CACHE_TTL_WIRE:
            return data

    s = _get_nse_session()
    raw_ann = []
    try:
        now_dt = datetime.datetime.now()
        from_d = (now_dt - datetime.timedelta(days=4)).strftime("%d-%m-%Y")
        to_d = now_dt.strftime("%d-%m-%Y")
        url = f"https://www.nseindia.com/api/corporate-announcements?index=equities&from_date={from_d}&to_date={to_d}"
        r = s.get(
            url,
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"},
            timeout=12,
        )
        if r.status_code == 200:
            raw_ann = r.json()
        elif r.status_code != 200:
            r_fb = s.get("https://www.nseindia.com/api/corporate-announcements?index=equities", timeout=12)
            if r_fb.status_code == 200:
                raw_ann = r_fb.json()
    except Exception as exc:
        print(f"[filings] Error fetching market filings: {exc}")

    parsed = []
    for m in (raw_ann or [])[:limit]:
        pdf = m.get("attchmntFile")
        pdf_url = None
        if pdf and isinstance(pdf, str) and pdf.strip() and pdf.strip() != "-":
            pdf = pdf.strip()
            if pdf.startswith("http://") or pdf.startswith("https://"):
                pdf_url = pdf
            else:
                pdf_url = f"https://nsearchives.nseindia.com/corporate/{pdf}"

        date_str = m.get("an_dt") or m.get("sort_date") or ""
        desc_str = _clean_str(m.get("desc") or "Filing")
        text_str = _clean_str(m.get("attchmntText") or "")
        summary_str = _clean_str(m.get("voiceSummary") or "")
        sym = (m.get("symbol") or "").strip().upper()

        cat = "FILING"
        desc_l = desc_str.lower()
        if "result" in desc_l or "financial" in desc_l:
            cat = "RESULTS"
        elif "meeting" in desc_l or "board" in desc_l:
            cat = "BOARD"
        elif "dividend" in desc_l:
            cat = "DIVIDEND"
        elif "allotment" in desc_l or "qip" in desc_l:
            cat = "ALLOTMENT"
        elif "order" in desc_l or "contract" in desc_l:
            cat = "ORDER"

        parsed.append({
            "symbol": sym,
            "company": m.get("sm_name") or sym,
            "category": cat,
            "desc": desc_str,
            "text": text_str[:280] + ("…" if len(text_str) > 280 else ""),
            "summary": summary_str,
            "date": date_str,
            "time_ago": _format_time_ago(date_str),
            "pdf_url": pdf_url,
            "industry": m.get("smIndustry") or "",
        })

    result = {
        "count": len(parsed),
        "filings": parsed,
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S IST"),
    }
    _MARKET_FILINGS_CACHE["filings"] = (now, result)
    return result


# ----------------------------------------------------------------------
# Pipeline 5: Market-Wide Corporate Actions (Dividends, Splits, Bonus)
# ----------------------------------------------------------------------
def fetch_market_actions(force_refresh: bool = False, limit: int = 150) -> dict:
    now = time.time()
    if not force_refresh and "actions" in _MARKET_ACTIONS_CACHE:
        cached_ts, data = _MARKET_ACTIONS_CACHE["actions"]
        if now - cached_ts < CACHE_TTL_EVENTS:
            return data

    s = _get_nse_session()
    raw_actions = []
    try:
        now_dt = datetime.datetime.now()
        from_d = (now_dt - datetime.timedelta(days=14)).strftime("%d-%m-%Y")
        to_d = (now_dt + datetime.timedelta(days=45)).strftime("%d-%m-%Y")
        url = f"https://www.nseindia.com/api/corporates-corporateActions?index=equities&from_date={from_d}&to_date={to_d}"
        r = s.get(
            url,
            headers={"Referer": "https://www.nseindia.com/companies-listing/corporate-filings-actions"},
            timeout=12,
        )
        if r.status_code == 200:
            raw_actions = r.json()
        elif r.status_code != 200:
            r_fb = s.get("https://www.nseindia.com/api/corporates-corporateActions?index=equities", timeout=12)
            if r_fb.status_code == 200:
                raw_actions = r_fb.json()
    except Exception as exc:
        print(f"[actions] Error fetching market corporate actions: {exc}")

    parsed = []
    for a in (raw_actions or [])[:limit]:
        subj = _clean_str(a.get("subject", ""))
        subj_l = subj.lower()
        kind = "ACTION"
        if "dividend" in subj_l:
            kind = "DIVIDEND"
        elif "split" in subj_l:
            kind = "SPLIT"
        elif "bonus" in subj_l:
            kind = "BONUS"
        elif "rights" in subj_l:
            kind = "RIGHTS"
        elif "agm" in subj_l or "egm" in subj_l:
            kind = "AGM"

        amount_match = re.search(r"(?:rs\.?|re\.?|inr|₹)\s*([\d\.]+)", subj_l)
        ratio_match = re.search(r"(\d+:\d+)", subj_l)
        details = (
            f"₹{amount_match.group(1)}/sh"
            if amount_match
            else (f"Ratio {ratio_match.group(1)}" if ratio_match else "")
        )

        sym = (a.get("symbol") or "").strip().upper()
        parsed.append({
            "symbol": sym,
            "company": a.get("comp") or sym,
            "kind": kind,
            "subject": subj,
            "details": details,
            "ex_date": a.get("exDate") or "—",
            "record_date": a.get("recDate") or "—",
            "series": a.get("series") or "EQ",
        })

    result = {
        "count": len(parsed),
        "actions": parsed,
        "updated_at": datetime.datetime.now().strftime("%H:%M:%S IST"),
    }
    _MARKET_ACTIONS_CACHE["actions"] = (now, result)
    return result


if __name__ == "__main__":
    print("Testing News & Corporate Events Engine...")
    e = fetch_corporate_events("RELIANCE")
    print(f"RELIANCE Events: {len(e['actions'])} actions, {len(e['announcements'])} filings")
    n = fetch_stock_news("RELIANCE", "Reliance Industries Limited", count=5)
    print(f"RELIANCE News: {len(n['articles'])} articles")
    w = fetch_market_wire(limit=10)
    print(f"Market Wire: {len(w['articles'])} articles")
    mf = fetch_market_filings(limit=5)
    print(f"Market Filings: {len(mf['filings'])} filings")
    ma = fetch_market_actions(limit=5)
    print(f"Market Actions: {len(ma['actions'])} actions")
