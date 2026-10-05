import datetime
import json
import os
import random
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import webbrowser

from enhanced import (
    _query_llm,
    clipboard_to_llm,
    clipboard_translate,
    query_todos,
    query_with_news,
    query_with_search,
    speak_daily_briefing,
)
import autonomous
from helpers import init_db, log_event, speak, stop_speech, takeCommand
from memory import store as store_memory


class Jarvis:
    def __init__(self) -> None:
        init_db()
        log_event("JARVIS initialized")
        self._music_proc = None
        self._welcome_proc = None
        self._stock_proc = None

    def _kill_music(self):
        if self._music_proc and self._music_proc.poll() is None:
            self._music_proc.terminate()
            try:
                self._music_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._music_proc.kill()
        self._music_proc = None

    def _play_background_music(self):
        self._kill_music()
        music_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "assets", "background_music.mp3"
        )
        if os.path.exists(music_path):
            self._music_proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", "-volume", "20", music_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _play_motivation(self):
        self._kill_music()
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
        videos = ["motivation_1.mp4", "motivation_2.mp4"]
        chosen = os.path.join(assets_dir, random.choice(videos))
        if os.path.exists(chosen):
            subprocess.Popen(
                ["ffplay", "-autoexit", "-fs", chosen],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def _open_welcome(self):
        return self._start_dashboard("welcome_dashboard.py", 9091)

    def _close_welcome(self):
        if self._welcome_proc and self._welcome_proc.poll() is None:
            self._welcome_proc.terminate()
            try:
                self._welcome_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._welcome_proc.kill()
        self._welcome_proc = None
        self._free_port(9091)

    def wishMe(self) -> None:
        if self._open_welcome():
            webbrowser.open_new_tab("http://localhost:9091")

        speak_daily_briefing()

    def _is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _dashboard_ready(self, port: int, path: str = "/", timeout: float = 2.0) -> bool:
        """True only when the port actually serves HTTP, not just accepts TCP.

        A crashed/zombie listener still satisfies _is_port_open, which used to make
        Jarvis report "already running" and open the browser onto a dead page.
        """
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
                return r.status == 200
        except Exception:
            return False

    def _free_port(self, port: int) -> bool:
        """Release a port without lsof (not installed on this machine).

        Uses fuser, falling back to pkill on the dashboard script name so a stale
        process can actually be cleared by voice. Returns True if the port is free.
        """
        subprocess.run(
            ["fuser", "-k", "-n", "tcp", str(port)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        script = {9090: "stock_dashboard.py", 9091: "welcome_dashboard.py"}.get(port)
        if script:
            subprocess.run(
                ["pkill", "-f", script],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        for _ in range(30):
            if not self._is_port_open(port):
                return True
            time.sleep(0.1)
        log_event(f"Port {port} still busy after kill attempts", "error")
        return False

    def _start_dashboard(self, script: str, port: int, wait: float = 60.0) -> bool:
        """Start a dashboard server, log its output, and wait until it really serves.

        stdout/stderr go to a log file instead of DEVNULL so crashes such as
        "Address already in use" are visible instead of silently discarded.
        """
        base = os.path.dirname(os.path.abspath(__file__))
        if self._dashboard_ready(port):
            return True
        self._free_port(port)
        logfile = os.path.join(base, script.replace(".py", "") + ".server.log")
        try:
            handle = open(logfile, "ab")
        except OSError as e:
            log_event(f"Cannot open {logfile}: {e}", "error")
            return False
        try:
            proc = subprocess.Popen(
                [sys.executable, "-u", script, "--port", str(port)],
                cwd=base, stdout=handle, stderr=subprocess.STDOUT,
            )
            if script == "welcome_dashboard.py":
                self._welcome_proc = proc
            else:
                self._stock_proc = proc
        except Exception as e:
            log_event(f"Failed to launch {script}: {e}", "error")
            return False
        finally:
            handle.close()

        deadline = time.time() + wait
        while time.time() < deadline:
            if self._dashboard_ready(port, timeout=1.0):
                return True
            time.sleep(0.4)
        log_event(
            f"{script} did not become ready on :{port} within {wait:.0f}s (see {logfile})",
            "error",
        )
        return False

    def _open_stock_dashboard(self) -> bool:
        """Launch the stock dashboard and only then open the browser."""
        if self._start_dashboard("stock_dashboard.py", 9090):
            webbrowser.open_new_tab("http://localhost:9090")
            return True
        log_event("Stock dashboard failed to start", "error")
        speak("Could not start the stock dashboard, sir. Check stock_dashboard.server.log.")
        return False

    def execute_query(self, query):
        stop_speech()
        for prefix in ["jarvis ", "jarvis", "jarvis's "]:
            if query.startswith(prefix):
                query = query.removeprefix(prefix)
                break
        # Close commands must be handled before the topic branches below, since
        # "close stock dashboard" also contains "stock" and "dashboard" and would
        # otherwise be swallowed by the stock branch and reopen the dashboard.
        if "close" in query or "shut" in query or "kill" in query or "stop" in query:
            wants_welcome = "welcome" in query or "9091" in query
            wants_stock = "stock" in query or "9090" in query or (
                "dashboard" in query and not wants_welcome
            )
            if wants_stock:
                speak("Shutting down the stock dashboard, sir.")
                self._free_port(9090)
                if wants_welcome:
                    self._close_welcome()
                return
            if wants_welcome:
                speak("Shutting down welcome dashboard, sir.")
                self._close_welcome()
                return

        # Handle hardcoded voice shortcuts first for speed
        if "time" in query:
            strTime = datetime.datetime.now().strftime("%H:%M:%S")
            speak(f"Sir, the time is {strTime}")
        elif "open google" in query:
            webbrowser.open_new_tab("https://google.com")
            speak("Opening Google.")
        elif "open github" in query:
            webbrowser.open_new_tab("https://github.com/mrayushmehrotra")
            speak("Opening Github.")

        elif "stock" in query or "nse" in query or "share" in query:
            from stock_tools import get_stock_data, get_stock_news as get_news
            import re
            tickers = re.findall(r"(?:price|of|for|news)\s+([A-Z]{1,5})(?:\s|$)", query, re.IGNORECASE)
            if "price" in query or "quote" in query or "rate" in query:
                ticker = tickers[0].upper() if tickers else ""
                if not ticker:
                    speak("Which stock, sir?")
                else:
                    data = get_stock_data(ticker)
                    if data:
                        sign = "+" if data["change"] and data["change"] >= 0 else ""
                        speak(f"{data['company']} is at {data['price']}. {sign}{data['change']} ({sign}{data['change_pct']}%).")
                    else:
                        speak(f"Could not find data for {ticker}.")
            elif "news" in query:
                ticker = tickers[0].upper() if tickers else ""
                if ticker:
                    news = get_news(ticker, 3)
                    if news:
                        headlines = ". ".join(a["title"] for a in news if a["title"])
                        speak(f"Top news for {ticker}: {headlines[:300]}")
                    else:
                        speak(f"No news found for {ticker}.")
                else:
                    answer = query_with_news("stock market nifty sensex stocks")
                    speak(answer or "No market news available, sir.")
            elif "dashboard" in query or "open" in query or "launch" in query:
                if self._dashboard_ready(9090):
                    speak("Stock dashboard is already running, sir.")
                    webbrowser.open_new_tab("http://localhost:9090")
                elif self._open_stock_dashboard():
                    speak("Opening stock dashboard.")
            elif "backtest" in query or "strategy" in query:
                ticker = tickers[0].upper() if tickers else "AAPL"
                from backtest_tools import run as backtest, format_result
                result = backtest(ticker=ticker, strategy="ma_crossover", start="6mo")
                speak(f"Backtest for {ticker}: {result.total_return_pct}% return, {result.num_trades} trades, {result.win_rate}% win rate.")
            else:
                if self._dashboard_ready(9090):
                    speak("Stock dashboard is already running, sir.")
                    webbrowser.open_new_tab("http://localhost:9090")
                elif self._open_stock_dashboard():
                    speak("Opening stock dashboard.")
        elif ("news" in query or "finance" in query) and "dashboard" not in query:
            topic = query
            for kw in [
                "news",
                "finance",
                "about",
                "tell me about",
                "what's",
                "what is",
            ]:
                topic = topic.replace(kw, "", 1).strip()
            if not topic:
                topic = "stock market nifty sensex stocks"
            answer = query_with_news(topic)
            speak(answer or f"Could not fetch news about {topic}, sir.")
            if answer:
                store_memory(query, answer)
        elif "cheatsheet" in query or "help" in query:
            path = os.path.join(os.path.dirname(__file__), "assets", "cheatsheet.html")
            webbrowser.open_new_tab("file://" + path)
            speak("Opening cheatsheet.")
        elif "open terminal" in query:
            if os.system("which kitty > /dev/null 2>&1") == 0:
                os.system("kitty &")
            speak("Opening terminal.")
        elif "open your logs" in query:
            os.system("kitty nvim ./jarvis.log")
            speak("Muted.")
        elif "mute" in query:
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1 > /dev/null 2>&1")
            speak("Muted.")
        elif "unmute" in query:
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 > /dev/null 2>&1")
            speak("Unmuted.")
        elif "volume" in query:
            import re

            nums = re.findall(r"\d+", query)
            if nums:
                level = min(int(nums[0]), 100)
                os.system(
                    f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {level}% > /dev/null 2>&1"
                )
                speak(f"Volume set to {level} percent.")
            else:
                speak("What volume level, sir?")
        elif "remember" in query:
            text = query.replace("remember", "", 1).strip()
            if text:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                todo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "TODO.txt")
                with open(todo_path, "a") as f:
                    f.write(f"[{timestamp}] {text}\n")
                speak("I'll remember that, sir.")
            else:
                speak("What should I remember?")
        elif "tired" in query or "i'm tired" in query or "i am tired" in query:
            speak("Time to lock in, sir!")
            self._play_motivation()
        elif (
            "daddy's home" in query or "daddy is home" in query or "daddy home" in query
        ):
            speak("Welcome home, sir!")
            self._play_background_music()
            self.wishMe()
            news = query_with_news("current news")
            speak(news)
        elif "copy" in query:
            text = query.replace("copy", "", 1).strip()
            import pyperclip

            pyperclip.copy(text)
            speak("Copied.")
        elif "write" in query or "right" in query:
            self.handle_write(query)
        elif "close" in query:
            self.handle_close()
        elif "stop" in query or "pause" in query:
            self._kill_music()
            if autonomous.auto_active:
                autonomous.stop_requested = True
                speak("Autonomous mode stopping, sir.")
            else:
                speak("Music stopped, sir.")
        elif "evade" in query:
            speak("Shutting down the system, sir.")
            os.system("shutdown now")
        elif "sleep" in query or "goodbye" in query or "good bye" in query:
            speak("Goodbye SIR", wait=True)
            self._cleanup()
            sys.exit()
        elif "briefing" in query or "what's new" in query or "daily briefing" in query:
            speak_daily_briefing()
        elif "clipboard" in query and (
            "summar" in query
            or "analyse" in query
            or "analyze" in query
            or "explain" in query
        ):
            clipboard_to_llm()
        elif "translate clipboard" in query or "clipboard translate" in query:
            import re

            langs = re.findall(
                r"(?:to\s+)?(\w+(?:\s+\w+)?)(?:\s*$)",
                query.replace("translate clipboard", "")
                .replace("clipboard translate", "")
                .strip(),
            )
            target = (
                langs[0].strip().title() if langs and langs[0].strip() else "English"
            )
            clipboard_translate(target)
        elif (
            "todo" in query
            or "to do" in query
            or "task" in query
            or "what i've to do" in query
            or "what's my" in query
            or "what are my" in query
        ):
            answer = query_todos()
            speak(answer)
            store_memory(query, answer)
        elif "on youtube" in query or "youtube" in query:
            search_terms = query
            for kw in ["search for", "search", "on youtube", "youtube"]:
                search_terms = search_terms.replace(kw, "", 1).strip()
            if search_terms:
                url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(search_terms)}"
                webbrowser.open_new_tab(url)
                speak(f"Searching YouTube for {search_terms}.")
            else:
                webbrowser.open_new_tab("https://www.youtube.com")
                speak("Opening YouTube.")
        elif (
            "search" in query
            or "weather" in query
            or "what's" in query
            or "what is" in query
            or "who is" in query
            or "tell me about" in query
        ):
            search_terms = query
            for kw in [
                "search for",
                "search",
                "tell me about",
                "what's",
                "what is",
                "who is",
            ]:
                search_terms = search_terms.replace(kw, "", 1).strip()
            if search_terms:
                answer = query_with_search(search_terms)
                speak(answer or "I couldn't find an answer for that, sir.")
                if answer:
                    store_memory(query, answer)
            else:
                speak("What should I search for, sir?")
        elif "open" in query and ("app" in query or "all" in query or "everything" in query):
            devnull = subprocess.DEVNULL
            next_app = os.path.join(os.path.dirname(__file__), "assets", "yt_upload_next")
            opened = []

            if self._is_port_open(3000):
                speak("YouTube upload server is already running.")
            else:
                subprocess.Popen(
                    ["bun", "run", "dev"],
                    cwd=next_app, stdout=devnull, stderr=devnull,
                )
                opened.append("YouTube upload")

            if self._dashboard_ready(9090):
                speak("Stock dashboard is already running.")
                opened.append("stock dashboard")
            elif self._start_dashboard("stock_dashboard.py", 9090):
                opened.append("stock dashboard")

            if self._open_welcome():
                opened.append("welcome dashboard")

            if opened:
                speak("Starting " + " and ".join(opened) + ".")
                if any("YouTube" in o for o in opened):
                    webbrowser.open_new_tab("http://localhost:3000")
                if any("stock" in o for o in opened):
                    webbrowser.open_new_tab("http://localhost:9090")
                if any("welcome" in o for o in opened):
                    webbrowser.open_new_tab("http://localhost:9091")
            if not opened:
                speak("All servers are already running, sir.")
        elif "upload" in query and ("youtube" in query or "video" in query):
            next_app = os.path.join(os.path.dirname(__file__), "assets", "yt_upload_next")
            speak("Starting the upload dashboard, sir.")
            devnull = subprocess.DEVNULL
            subprocess.Popen(
                ["bun", "run", "dev"],
                cwd=next_app,
                stdout=devnull,
                stderr=devnull,
            )
            webbrowser.open_new_tab("http://localhost:3000")
        elif "open" in query and "welcome" in query:
            if self._open_welcome():
                webbrowser.open_new_tab("http://localhost:9091")
                speak("Opening the welcome dashboard, sir.")
            else:
                speak("Failed to start the welcome dashboard, sir.")
        elif "close" in query and "welcome" in query:
            speak("Shutting down welcome dashboard, sir.")
            self._close_welcome()
        elif "close" in query and ("upload" in query or "server" in query or "youtube" in query):
            speak("Shutting down the upload server, sir.")
            subprocess.run(
                ["fuser", "-k", "-n", "tcp", "3000"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif "close" in query and ("all" in query or "everything" in query or "app" in query):
            speak("Closing all servers, sir.")
            for port in (3000, 9090, 9091):
                subprocess.run(
                    ["fuser", "-k", "-n", "tcp", str(port)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            self._free_port(9090)
            self._free_port(9091)
        elif any(
            kw in query
            for kw in [
                "work for",
                "take control",
                "autonomous",
                "auto pilot",
                "act on its own",
                "do my work",
                "do everything",
            ]
        ):
            import re

            nums = re.findall(r"(\d+)\s*(?:min|minute)", query)
            duration = int(nums[0]) if nums else 30

            goal = query
            for kw in [
                "work for",
                "take control",
                "autonomous",
                "auto pilot",
                "act on its own",
                "do my work",
                "do everything",
                f"{duration} minutes",
                "for",
            ]:
                goal = goal.replace(kw, "", 1).strip()
            if not goal:
                goal = "general productivity work"

            speak(
                f"Entering autonomous mode for {duration} minutes. Goal: {goal}"
            )
            import threading
            threading.Thread(
                target=autonomous.run_autonomous,
                args=(goal, duration),
                daemon=True,
            ).start()
        else:
            if "quick" in query:
                fast_model = os.environ.get(
                    "JARVIS_FAST_LLM_MODEL", "qwen2.5:0.5b"
                )
                answer = _query_llm(
                    f"Answer concisely in one sentence: {query}",
                    model=fast_model,
                )
            else:
                answer = _query_llm(f"Answer concisely in one sentence: {query}")

            if not answer or len(answer) < 5:
                answer = _query_llm(
                    f"Answer in exactly one short sentence: {query}"
                )

            speak(answer or "I don't know how to do that, sir")
            if answer:
                store_memory(query, answer)

    def handle_write(self, query):
        text_to_write = query.replace("write", "", 1).replace("right", "", 1).strip()
        if not text_to_write:
            speak("What should I write?")
            text_to_write = takeCommand()
        if text_to_write != "none":
            import time

            import pyperclip

            speak("Writing in 2 seconds.")
            time.sleep(2)
            old_clip = pyperclip.paste()
            pyperclip.copy(text_to_write)
            if os.environ.get("XDG_SESSION_TYPE") == "wayland":
                os.system(f"wtype '{text_to_write}'") or os.system(
                    "pyautogui hotkey ctrl v"
                )  # Simplified fallback
            else:
                os.system("xdotool key ctrl+v")
            time.sleep(0.5)
            pyperclip.copy(old_clip)
            speak("Done.")

    def handle_close(self):
        speak("Closing.")
        if os.environ.get("XDG_SESSION_TYPE") == "wayland":
            os.system("wtype -M ctrl -k q -m ctrl")
        else:
            os.system("xdotool key ctrl+q")

    def _search_web(self, query: str) -> str:
        try:
            url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1&skip_disambig=1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())

            if data.get("AbstractText"):
                return data["AbstractText"][:300]
            if data.get("Answer"):
                return data["Answer"][:300]
            if data.get("Definition"):
                return data["Definition"][:300]
            if data.get("Results"):
                first = data["Results"][0]
                if first.get("Text"):
                    return first["Text"][:300]

            fallback_url = (
                f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            )
            req = urllib.request.Request(
                fallback_url, headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=8) as r:
                html = r.read().decode()
                import re

                match = re.search(
                    r'class="result__snippet"[^>]*>(.*?)</(?:a|span|td)>',
                    html,
                    re.DOTALL,
                )
                if match:
                    snippet = re.sub(r"<[^>]+>", "", match.group(1)).strip()
                    return snippet[:300]

            return f"I couldn't find an answer for that, sir."
        except Exception as e:
            log_event(f"Search error: {e}", "error")
            return "Search failed, sir."

    def _cleanup(self):
        for attr in ("_stock_proc", "_welcome_proc"):
            proc = getattr(self, attr, None)
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()


def main():
    print("Starting Jarvis...")
    bot = Jarvis()
    cmd_queue = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cmd_queue")
    try:
        import threading
        import time

        threading.Thread(target=bot.wishMe, daemon=True).start()
        last_cmd_ts = ""
        while True:
            query = takeCommand()
            if query != "none":
                bot.execute_query(query)
            # Check typed commands from the welcome dashboard
            try:
                if os.path.exists(cmd_queue):
                    with open(cmd_queue) as f:
                        data = json.load(f)
                    ts = data.get("ts", "")
                    if ts and ts != last_cmd_ts:
                        last_cmd_ts = ts
                        cmd = data.get("command", "").strip()
                        if cmd:
                            print(f"Dashboard command: {cmd}")
                            bot.execute_query(cmd)
                            os.remove(cmd_queue)
            except Exception:
                pass
            time.sleep(0.2)
    finally:
        bot._cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
