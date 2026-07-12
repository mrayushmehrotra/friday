"""
Enhanced features for Jarvis:
  - clipboard_to_llm()  — read clipboard, send to local LLM, speak result
  - daily_briefing()    — weather + news + tasks, returned as formatted text
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from helpers import log_event, speak
from memory import build_context
from memory import store as store_memory

# ---------------------------------------------------------------------------
#  Clipboard → LLM  (local Ollama)
# ---------------------------------------------------------------------------


def clipboard_to_llm() -> str:
    try:
        import pyperclip

        text = pyperclip.paste()
    except ImportError:
        log_event("clipboard_to_llm: pyperclip not installed", "error")
        return ""

    text = text.strip()
    if not text:
        speak("Clipboard is empty, sir.")
        return ""

    speak("Analyzing clipboard contents.")
    result = _query_llm(
        "Summarize the following text concisely in 2-3 sentences:\n\n" + text
    )
    if result:
        speak(result)
    return result


def clipboard_translate(target_lang: str = "English") -> str:
    try:
        import pyperclip

        text = pyperclip.paste()
    except ImportError:
        log_event("clipboard_translate: pyperclip not installed", "error")
        return ""

    text = text.strip()
    if not text:
        speak("Clipboard is empty, sir.")
        return ""

    speak(f"Translating clipboard to {target_lang}.")
    result = _query_llm(
        f"Translate the following text to {target_lang}. "
        f"Output only the translation, no explanations:\n\n{text}"
    )
    if result:
        speak(result)
    return result


def _query_llm(prompt: str, model: str | None = None) -> str:
    if model is None:
        model = os.environ.get("JARVIS_LLM_MODEL", "qwen2.5:0.5b")

    base_url = os.environ.get("JARVIS_LLM_ENDPOINT", "http://localhost:11434")
    base_url = base_url.replace("/api/generate", "").replace("/api/chat", "")

    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.6,
        num_predict=512,
        num_ctx=4096,
    )

    ctx = build_context(prompt)
    messages = []
    if ctx:
        messages.append(("system", ctx))
    messages.append(("human", prompt))

    try:
        result = llm.invoke(messages)
        raw = result.content.strip()
        if raw:
            return raw
        log_event("LLM returned empty response", "error")
    except Exception as e:
        log_event(f"LLM query failed: {e}", "error")
    return ""


# ---------------------------------------------------------------------------
#  Daily Briefing
# ---------------------------------------------------------------------------


def _fetch_market_data() -> str | None:
    try:
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ENSEI?range=1d&interval=1m"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            nifty = json.loads(r.read().decode())
        meta = nifty["chart"]["result"][0]["meta"]
        nifty_price = meta["regularMarketPrice"]
        nifty_prev = meta["chartPreviousClose"]
        nifty_change = nifty_price - nifty_prev
        nifty_pct = (nifty_change / nifty_prev) * 100

        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5EBSESN?range=1d&interval=1m"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            sensex = json.loads(r.read().decode())
        meta = sensex["chart"]["result"][0]["meta"]
        sensex_price = meta["regularMarketPrice"]
        sensex_prev = meta["chartPreviousClose"]
        sensex_change = sensex_price - sensex_prev
        sensex_pct = (sensex_change / sensex_prev) * 100

        nifty_dir = "up" if nifty_change >= 0 else "down"
        sensex_dir = "up" if sensex_change >= 0 else "down"
        return (
            f"Nifty 50 is at {nifty_price:.0f}, {nifty_dir} by {abs(nifty_change):.0f} points "
            f"({nifty_pct:+.2f}%). "
            f"Sensex is at {sensex_price:.0f}, {sensex_dir} by {abs(sensex_change):.0f} points "
            f"({sensex_pct:+.2f}%)."
        )
    except Exception as e:
        log_event(f"Market data fetch failed: {e}", "error")
        return None


def daily_briefing() -> str:
    now = datetime.datetime.now()
    hour = now.hour
    if hour < 12:
        period = "morning"
    elif hour < 17:
        period = "afternoon"
    else:
        period = "evening"

    market = _fetch_market_data()
    headlines = _fetch_headlines(4)
    parts = [f"Good {period}, sir."]
    if market:
        parts.append(market)
    context = f"Today's stock market: {market or 'unavailable'}\n\n" + "\n".join(headlines)
    summary = _query_llm(
        f"{context}\n\nSummarize the market movement and these headlines into 2-3 concise, natural sentences. Read like a news anchor."
    )
    if summary:
        return summary
    return " ".join(parts)


def speak_daily_briefing() -> None:
    briefing = daily_briefing()
    if briefing:
        speak(briefing)
    log_event("Daily briefing delivered")


def _fetch_headlines(max_items: int = 4) -> list[str]:
    try:
        url = (
            "https://news.google.com/rss/search?"
            "q=stock+market+nifty+sensex+india+finance&hl=en-IN&gl=IN&ceid=IN:en"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read().decode())

        items: list[str] = []
        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is not None and title_el.text:
                items.append(title_el.text)
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        log_event(f"Headlines fetch failed: {e}", "error")
        return []


# ---------------------------------------------------------------------------
#  Convenience: run both in sequence
# ---------------------------------------------------------------------------


def enhanced_welcome() -> None:
    speak_daily_briefing()


# ---------------------------------------------------------------------------
#  Direct web / news / todos helpers (no MCP subprocess overhead)
# ---------------------------------------------------------------------------


def _duckduckgo_search(query: str) -> str:
    """Direct DuckDuckGo search — no MCP subprocess needed."""
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        data = json.loads(resp.read().decode())

    results = []
    if data.get("AbstractText"):
        results.append(data["AbstractText"][:500])
    if data.get("Answer"):
        results.append(data["Answer"][:500])
    if data.get("Definition"):
        results.append(data["Definition"][:500])
    if data.get("Results"):
        for r in data["Results"][:3]:
            if r.get("Text"):
                results.append(r["Text"][:500])
    if results:
        return "\n".join(results)

    fallback = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
    req = urllib.request.Request(fallback, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        html = resp.read().decode()
    import re

    snippets = re.findall(
        r'class="result__snippet"[^>]*>(.*?)</(?:a|span|td)>', html, re.DOTALL
    )
    cleaned = []
    for s in snippets[:3]:
        text = re.sub(r"<[^>]+>", "", s).strip()
        if text:
            cleaned.append(text[:500])
    return "\n".join(cleaned) if cleaned else "No results found."


def _fetch_news_rss(topic: str) -> str:
    """Direct Google News RSS fetch — no MCP subprocess needed."""
    url = (
        f"https://news.google.com/rss/search?"
        f"q={urllib.parse.quote(topic)}&hl=en-IN&gl=IN&ceid=IN:en"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=8) as r:
        root = ET.fromstring(r.read().decode())

    import re as _re

    items = []
    for item in root.iter("item"):
        title_el = item.find("title")
        desc_el = item.find("description")
        if title_el is not None and title_el.text:
            title = title_el.text.strip()
            desc = ""
            if desc_el and desc_el.text:
                desc = _re.sub(r"<[^>]+>", "", desc_el.text).strip()[:300]
            items.append(f"• {title}")
            if desc:
                items.append(f"  {desc}")
        if len(items) >= 20:
            break
    return "\n".join(items) if items else "No news found."


def _ollama_chat(query: str) -> str:
    """Synchronous Ollama chat call via ChatOllama. Low temperature for structured output."""
    model = os.environ.get("JARVIS_LLM_MODEL", "qwen2.5:0.5b")
    base_url = os.environ.get("JARVIS_LLM_ENDPOINT", "http://localhost:11434")
    base_url = base_url.replace("/api/generate", "").replace("/api/chat", "")

    from langchain_ollama import ChatOllama

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=0.1,
        num_predict=512,
        num_ctx=4096,
    )

    ctx = build_context(query)
    messages = []
    if ctx:
        messages.append(("system", ctx))
    messages.append(("human", query))

    try:
        result = llm.invoke(messages)
        content = result.content.strip()
        if content:
            return content
    except Exception as e:
        log_event(f"Ollama chat failed: {e}", "error")

    return _query_llm(
        f"Answer in exactly one sentence: {query.split('Search results')[0].strip()}"
    )


def query_with_search(query: str) -> str:
    """Search the web via direct DuckDuckGo API, then summarize with Ollama."""
    try:
        search_text = _duckduckgo_search(query)
        if search_text and search_text != "No results found.":
            return _ollama_chat(
                f"Search results for '{query}':\n{search_text}\n\n"
                f"Answer the original question in one sentence based on these results."
            )
        return _query_llm(f"Answer in exactly one sentence: {query}")
    except Exception as e:
        log_event(f"Search failed, falling back: {e}", "error")
        return _query_llm(f"Answer in exactly one sentence: {query}")


def query_with_news(topic: str) -> str:
    """Fetch latest news via direct Google News RSS, then summarize with Ollama."""
    try:
        news_text = _fetch_news_rss(topic)
        if news_text and not news_text.startswith("No news found"):
            return _ollama_chat(
                f"Today's news for '{topic}':\n{news_text}\n\n"
                f"Summarize the key highlights. Focus on stocks that are in the news "
                f"— mention specific company names and whether they're bullish or bearish. "
                f"Also mention any stocks giving dividends. Keep it concise."
            )
        return f"I couldn't find any news about {topic}, sir."
    except Exception as e:
        log_event(f"News fetch failed: {e}", "error")
        return f"I couldn't fetch news about {topic}, sir."


def query_todos() -> str:
    """Read the user's notes/todos directly and return a one-sentence summary."""
    try:
        notes_path = os.path.expanduser("~/notes.md")
        if not os.path.exists(notes_path):
            return "You have no tasks saved, sir."
        with open(notes_path) as f:
            notes_text = f.read().strip()
        if not notes_text:
            return "You have no tasks saved, sir."
        return _ollama_chat(
            f"The user's notes say:\n{notes_text}\n\nSummarize what they need to do today in one sentence."
        )
    except Exception as e:
        log_event(f"Todos failed: {e}", "error")
        return "I couldn't read your notes, sir."
