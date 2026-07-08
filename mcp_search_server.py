from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jarvis-tools")


@mcp.tool()
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo and return text snippets."""
    try:
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
        snippets = re.findall(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|span|td)>', html, re.DOTALL
        )
        cleaned = []
        for s in snippets[:3]:
            text = re.sub(r"<[^>]+>", "", s).strip()
            if text:
                cleaned.append(text[:500])
        return "\n".join(cleaned) if cleaned else "No results found."
    except Exception as e:
        return f"Search error: {e}"


@mcp.tool()
def news_search(topic: str) -> str:
    """Search for the latest news on any topic."""
    try:
        url = (
            f"https://news.google.com/rss/search?"
            f"q={urllib.parse.quote(topic)}&hl=en-IN&gl=IN&ceid=IN:en"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            root = ET.fromstring(r.read().decode())

        items: list[str] = []
        for item in root.iter("item"):
            title_el = item.find("title")
            desc_el = item.find("description")
            if title_el is not None and title_el.text:
                title = title_el.text.strip()
                desc = ""
                if desc_el and desc_el.text:
                    desc = re.sub(r"<[^>]+>", "", desc_el.text).strip()[:300]
                items.append(f"{title}")
                if desc:
                    items.append(f"  {desc}")
            if len(items) >= 20:
                break

        return "\n".join(items) if items else f"No news found about '{topic}'."
    except Exception as e:
        return f"News search error: {e}"


@mcp.tool()
def read_notes() -> str:
    """Read the user's notes/todos file."""
    try:
        notes_path = os.path.expanduser("~/notes.md")
        if not os.path.exists(notes_path):
            return "No notes found."
        with open(notes_path) as f:
            content = f.read().strip()
        return content or "No notes found."
    except Exception as e:
        return f"Error reading notes: {e}"


@mcp.tool()
def define_word(word: str) -> str:
    """Look up the definition of a word using a dictionary API."""
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{urllib.parse.quote(word)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        lines = []
        for entry in data[:2]:
            word_name = entry.get("word", word)
            phonetics = entry.get("phonetics", [])
            phonetic_text = ""
            for p in phonetics:
                if p.get("text"):
                    phonetic_text = p["text"]
                    break
            header = word_name.capitalize()
            if phonetic_text:
                header += f" ({phonetic_text})"
            lines.append(header)
            for meaning in entry.get("meanings", [])[:3]:
                part = meaning.get("partOfSpeech", "")
                for definition in meaning.get("definitions", [])[:2]:
                    def_text = definition.get("definition", "")
                    example = definition.get("example")
                    line = f"  [{part}] {def_text}"
                    if example:
                        line += f'\n    e.g. "{example}"'
                    lines.append(line)
        return "\n".join(lines) if lines else f"No definition found for '{word}'."
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"No definition found for '{word}'."
        return f"Dictionary error: {e}"
    except Exception as e:
        return f"Dictionary error: {e}"


@mcp.tool()
def weather(city: str) -> str:
    """Get current weather and forecast for a city."""
    try:
        url = f"https://wttr.in/{urllib.parse.quote(city)}?format=%l:+%t,+%C,+humidity+%h,+wind+%w"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read().decode().strip()
    except Exception as e:
        return f"Weather error: {e}"


@mcp.tool()
def stock_price(symbol: str) -> str:
    """Get the current stock price and change for a ticker symbol (e.g. AAPL, TSLA, RELIANCE.NS)."""
    try:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol.upper())}?interval=1d&range=1d"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        result = data.get("chart", {}).get("result", [])
        if not result:
            return f"No data found for symbol '{symbol}'."

        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose")
        currency = meta.get("currency", "USD")
        short_name = meta.get("shortName", symbol.upper())

        if price is None:
            return f"No price data for '{symbol}'."

        change = price - previous_close if previous_close else 0
        change_pct = (change / previous_close * 100) if previous_close else 0
        direction = "+" if change >= 0 else ""

        return (
            f"{short_name}: {currency} {price:.2f} "
            f"({direction}{change:.2f}, {direction}{change_pct:.2f}%)"
        )
    except Exception as e:
        return f"Stock price error: {e}"


@mcp.tool()
def wikipedia_summary(topic: str) -> str:
    """Get a summary of a topic from Wikipedia."""
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(topic.replace(' ', '_'))}"
        req = urllib.request.Request(url, headers={"User-Agent": "Jarvis/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())

        title = data.get("titles", {}).get("normalized", data.get("title", topic))
        extract = data.get("extract", "")
        page_url = data.get("content_urls", {}).get("desktop", {}).get("page", "")

        if not extract:
            return f"No Wikipedia article found for '{topic}'."

        result = f"{title}\n{extract[:1000]}"
        if page_url:
            result += f"\nSource: {page_url}"
        return result
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return f"No Wikipedia article found for '{topic}'."
        return f"Wikipedia error: {e}"
    except Exception as e:
        return f"Wikipedia error: {e}"


@mcp.tool()
def find_file(name: str) -> str:
    """Search for files by name in the home directory. Returns matching file paths."""
    try:
        home = os.path.expanduser("~")
        result = subprocess.run(
            ["find", home, "-maxdepth", "5", "-iname", f"*{name}*", "-type", "f"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return f"Search error: {result.stderr.strip()}"
        files = [f for f in result.stdout.strip().split("\n") if f.strip()]
        if not files:
            return f"No files found matching '{name}'."
        files = files[:20]
        lines = [f"Found {len(files)} file(s):"]
        for f in files:
            lines.append(f"  {f}")
        return "\n".join(lines)
    except subprocess.TimeoutExpired:
        return f"Search timed out for '{name}'."
    except Exception as e:
        return f"Find file error: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
