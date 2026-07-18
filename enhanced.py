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

from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage

_JARVIS_THREAD = "jarvis_main"
_checkpointer = MemorySaver()
_llm_graphs: dict[str, any] = {}


def _build_llm_graph(model: str, temperature: float):
    base_url = os.environ.get("JARVIS_LLM_ENDPOINT", "http://localhost:11434")
    base_url = base_url.replace("/api/generate", "").replace("/api/chat", "").rstrip("/")

    llm = ChatOllama(
        model=model,
        base_url=base_url,
        temperature=temperature,
        num_predict=512,
        num_ctx=4096,
    )

    def call_model(state: MessagesState):
        response = llm.invoke(state["messages"])
        return {"messages": [response]}

    builder = StateGraph(MessagesState)
    builder.add_node("llm", call_model)
    builder.add_edge(START, "llm")
    builder.add_edge("llm", END)

    return builder.compile(checkpointer=_checkpointer)


def _get_llm_graph(model: str | None = None, temperature: float = 0.6):
    model_name = model or os.environ.get("JARVIS_LLM_MODEL", "qwen2.5:0.5b")
    key = f"{model_name}_{temperature}"
    if key not in _llm_graphs:
        _llm_graphs[key] = _build_llm_graph(model_name, temperature)
    return _llm_graphs[key]

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

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


def _query_llm(prompt: str, model: str | None = None, temperature: float = 0.6) -> str:
    try:
        graph = _get_llm_graph(model, temperature)
        config = {"configurable": {"thread_id": _JARVIS_THREAD}}

        ctx = build_context(prompt)
        messages = []
        if ctx:
            messages.append(SystemMessage(content=ctx))
        messages.append(HumanMessage(content=prompt))

        result = graph.invoke({"messages": messages}, config=config)
        content = result["messages"][-1].content.strip()
        if content:
            return content
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


def _fetch_moneycontrol_stocks() -> list[dict[str, str]]:
    try:
        import requests
        from lxml import html

        url = "https://www.moneycontrol.com/news/business/stocks/"
        headers = {"User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=10)
        tree = html.fromstring(resp.content)

        articles: list[dict[str, str]] = []
        for li in tree.xpath("//li[.//h2]"):
            a = li.find(".//a")
            href = a.get("href", "") if a is not None else ""
            h2 = li.findtext(".//h2", "")
            full = li.text_content().strip()
            if h2:
                articles.append({"title": h2.strip(), "url": href, "text": full[:500]})
        return articles
    except Exception as e:
        log_event(f"Moneycontrol scrape failed: {e}", "error")
        return []


def _groq_stock_recommendations(articles: list[dict[str, str]]) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return ""
    if not articles:
        return ""

    headlines = "\n\n".join(
        f"{i+1}. {a['title']}"
        for i, a in enumerate(articles[:15])
    )

    try:
        from groq import Groq

        client = Groq(api_key=api_key)
        completion = client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a stock market analyst. Given today's Indian stock market news headlines "
                        "from Moneycontrol, identify the top recommended stocks for today. "
                        "Answer in 2-3 concise sentences. Mention specific stock names and whether "
                        "they are a buy, sell, or hold. Be brief and natural."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Here are today's stock market headlines:\n\n{headlines}\n\nWhat are the top recommended stocks today?",
                },
            ],
            temperature=0.3,
            max_tokens=200,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        log_event(f"Groq stock analysis failed: {e}", "error")
        return ""


def _strip_markdown(text: str) -> str:
    text = text.replace("**", "")
    text = text.replace("*", "")
    text = text.replace("__", "")
    text = text.replace("`", "")
    text = text.replace("###", "").replace("##", "").replace("#", "")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") or stripped.startswith("* "):
            stripped = stripped[2:]
        if stripped:
            lines.append(stripped)
    return " ".join(lines)


_YOUTUBE_CHANNEL_HANDLE = "@shortscaster-o9t"
_YOUTUBE_CHANNEL_ID = "UCgHiG-4239dZcxdpkQ9OX9w"
_YOUTUBE_TRACK_PATH = os.path.join(os.path.dirname(__file__), ".youtube_track.json")


def _youtube_channel_stats() -> str | None:
    try:
        import requests
        import json
        import re

        headers = {"User-Agent": "Mozilla/5.0"}
        channel_url = f"https://www.youtube.com/{_YOUTUBE_CHANNEL_HANDLE}"
        resp = requests.get(channel_url, headers=headers, timeout=10)

        sub_match = re.search(r'(\d+[\d,.]*)\s*subscriber', resp.text, re.IGNORECASE)
        prev = {}
        if os.path.exists(_YOUTUBE_TRACK_PATH):
            try:
                prev = json.load(open(_YOUTUBE_TRACK_PATH))
            except Exception:
                prev = {}

        sub_count = 0
        sub_text = "0"
        if sub_match:
            sub_text = sub_match.group(1).replace(",", "")
            sub_count = int(float(sub_text.replace("K", "000").replace("M", "000000").split(".")[0]) if "K" in sub_text.upper() or "M" in sub_text.upper() else float(sub_text))
            if "K" in sub_text.upper():
                sub_count = int(float(sub_text.replace("K", "")) * 1000)
            elif "M" in sub_text.upper():
                sub_count = int(float(sub_text.replace("M", "")) * 1000000)

        # Latest video via RSS + InnerTube
        rss = requests.get(
            f"https://www.youtube.com/feeds/videos.xml?channel_id={_YOUTUBE_CHANNEL_ID}",
            headers=headers, timeout=10
        )
        root = ET.fromstring(rss.content)
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        entries = root.findall("atom:entry", ns)
        video_title = ""
        video_views = 0
        if entries:
            video_id = entries[0].find("yt:videoId", ns).text
            video_title = entries[0].find("atom:title", ns).text or ""
            # Clean title for speech
            video_title = re.sub(r'[^\w\s.,!?-]', '', video_title).strip()

            payload = {
                "videoId": video_id,
                "context": {
                    "client": {"clientName": "WEB", "clientVersion": "2.20231001.00.00"}
                }
            }
            innertube = requests.post(
                f"https://www.youtube.com/youtubei/v1/player?key=AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
                json=payload, headers={"Content-Type": "application/json"}, timeout=10
            )
            if innertube.status_code == 200:
                video_views = int(innertube.json().get("videoDetails", {}).get("viewCount", 0))

        parts = []
        parts.append(f"Your channel {_YOUTUBE_CHANNEL_HANDLE} has {sub_text} subscribers")
        if video_title and video_views > 0:
            parts.append(f"your latest video has {video_views} views")
        elif video_title:
            parts.append(f"your latest video is titled {video_title[:60]}")

        sub_change = sub_count - prev.get("subs", sub_count)
        if sub_change > 0:
            parts.append(f"you gained {sub_change} new subscriber since last check")
        elif sub_change > 0:
            parts.append(f"you lost {abs(sub_change)} subscribers since last check")

        # Save current state
        json.dump({"subs": sub_count, "views": video_views, "video_title": video_title}, open(_YOUTUBE_TRACK_PATH, "w"))

        return ". ".join(parts)
    except Exception as e:
        log_event(f"YouTube stats failed: {e}", "error")
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
    parts = [f"Good {period}, sir."]
    if market:
        parts.append(market)

    stocks = _fetch_moneycontrol_stocks()
    groq_take = _groq_stock_recommendations(stocks)
    if groq_take:
        parts.append(_strip_markdown(groq_take))

    yt = _youtube_channel_stats()
    if yt:
        parts.append(yt)

    return ". ".join(parts)


def speak_daily_briefing() -> None:
    briefing = daily_briefing()
    if briefing:
        speak(briefing)
    log_event("Daily briefing delivered")


_NOTES_PATH = os.path.expanduser("~/.notes.md")
_WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]


def _read_notes_plan() -> str:
    try:
        with open(_NOTES_PATH) as f:
            text = f.read()
    except FileNotFoundError:
        return ""

    today = datetime.datetime.now().strftime("%A").lower()
    lines = text.splitlines()

    today_section: list[str] = []
    in_today = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("### ") and stripped[4:].strip().lower().startswith(today):
            in_today = True
            continue
        if in_today:
            if stripped.startswith("### ") or stripped.startswith("---"):
                break
            if stripped:
                today_section.append(stripped)

    todo_done: list[str] = []
    todo_pending: list[str] = []
    in_todo = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Immediate Jarvis TODO (This Week)":
            in_todo = True
            continue
        if in_todo:
            if stripped.startswith("## ") or stripped.startswith("---"):
                break
            if stripped.startswith("- [x]"):
                todo_done.append(stripped[5:].strip())
            elif stripped.startswith("- [ ]"):
                todo_pending.append(stripped[5:].strip())

    parts: list[str] = []

    if today_section:
        today_name = datetime.datetime.now().strftime("%A")
        items = []
        for item in today_section:
            clean = item.lstrip("-* ").strip().replace("**", "")
            if clean and not clean.startswith("|"):
                items.append(clean)
        if items:
            parts.append(f"Today is {today_name}. Plan: " + ". ".join(items))

    if todo_done:
        done = [t.replace("**", "").strip() for t in todo_done]
        parts.append("Done: " + ". ".join(done))
    if todo_pending:
        count = len(todo_pending)
        parts.append(f"You have {count} pending tasks in your notes")

    return ". ".join(parts) if parts else ""


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
    """Synchronous Ollama chat via LangGraph. Low temperature for structured output."""
    result = _query_llm(query, temperature=0.1)
    if result:
        return result
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
    """Read the user's TODO.txt directly and return a one-sentence summary."""
    try:
        todo_path = os.path.join(os.path.dirname(__file__), "TODO.txt")
        if not os.path.exists(todo_path):
            return "You have no tasks saved, sir."
        with open(todo_path) as f:
            text = f.read().strip()
        if not text:
            return "You have no tasks saved, sir."
        return _ollama_chat(
            f"The user's TODO says:\n{text}\n\nSummarize what they need to do today in one sentence."
        )
    except Exception as e:
        log_event(f"Todos failed: {e}", "error")
        return "I couldn't read your notes, sir."
