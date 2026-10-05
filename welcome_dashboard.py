import argparse
import datetime
import json
import os
import socket
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stock_tools import get_stock_data, get_stock_news, _resolve_ticker

PORT = 9091
TODO_PATH = os.path.join(os.path.dirname(__file__), "TODO.txt")
CMD_QUEUE = os.path.join(os.path.dirname(__file__), ".cmd_queue")
PNL_PATH = os.path.join(os.path.dirname(__file__), ".pnl_data.json")


class WelcomeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/news":
            self._handle_news(params)
        elif path == "/api/quote":
            self._handle_quote(params)
        elif path == "/api/pnl":
            self._handle_pnl(params)
        elif path == "/api/todofile":
            self._handle_todofile(params)
        elif path == "/api/server":
            self._handle_server(params)
        elif path == "/api/command":
            self._handle_command(params)
        elif path == "/":
            self._serve_file("welcome.html")
        else:
            super().do_GET()

    def _serve_file(self, filename):
        filepath = os.path.join(HERE, filename)
        if not os.path.exists(filepath):
            self.send_error(404)
            return
        ext = filename.split(".")[-1]
        types = {"html": "text/html", "css": "text/css", "js": "application/javascript"}
        self.send_response(200)
        self.send_header("Content-Type", types.get(ext, "text/plain"))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(filepath, "rb") as f:
            self.wfile.write(f.read())

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, indent=2, default=str).encode())

    def _get_param(self, params, key, default=None):
        vals = params.get(key, [])
        return vals[0] if vals else default

    def _handle_news(self, params):
        raw = self._get_param(params, "ticker", "").upper()
        ticker = _resolve_ticker(raw) if raw else "^NSEI"
        count = int(self._get_param(params, "count", "10"))
        news = []
        try:
            news = get_stock_news(ticker, count) if ticker else []
        except Exception:
            news = []
        if not news:
            try:
                import urllib.request
                import xml.etree.ElementTree as ET
                query = f"{raw}+stock+india" if raw else "indian+stock+market+nifty+sensex"
                url = (
                    f"https://news.google.com/rss/search?"
                    f"q={query}&hl=en-IN&gl=IN&ceid=IN:en"
                )
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=5) as r:
                    root = ET.fromstring(r.read().decode())
                for item in root.iter("item"):
                    title_el = item.find("title")
                    link_el = item.find("link")
                    pub_el = item.find("pubDate")
                    desc_el = item.find("description")
                    if title_el is not None and title_el.text:
                        news.append({
                            "title": title_el.text,
                            "link": link_el.text if link_el is not None else "#",
                            "publisher": "Google News",
                            "pub_date": pub_el.text if pub_el is not None else "",
                            "summary": desc_el.text if desc_el is not None else "",
                        })
                    if len(news) >= count:
                        break
            except Exception:
                pass
        self._send_json({"news": news, "count": len(news)})

    def _handle_quote(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        if not ticker:
            self._send_json({"error": "Missing ticker"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        data = get_stock_data(resolved)
        if not data:
            self._send_json({"error": f"No data for {ticker}"}, 404)
            return
        self._send_json(data)

    def _handle_command(self, params):
        cmd = self._get_param(params, "text", "")
        if not cmd:
            self._send_json({"error": "No command"}, 400)
            return
        try:
            with open(CMD_QUEUE, "w") as f:
                json.dump({"command": cmd, "ts": datetime.datetime.now().isoformat()}, f)
            self._send_json({"status": "received", "command": cmd})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_pnl(self, params):
        reset = self._get_param(params, "reset")
        if reset is not None:
            if os.path.exists(PNL_PATH):
                os.remove(PNL_PATH)
            self._send_json({"entries": []})
            return
        wallet = self._get_param(params, "wallet")
        pl = self._get_param(params, "pl")
        data = []
        if os.path.exists(PNL_PATH):
            try:
                with open(PNL_PATH) as f:
                    data = json.load(f)
            except Exception:
                data = []
        if wallet is not None and pl is not None:
            try:
                entry = {
                    "date": datetime.date.today().isoformat(),
                    "time": datetime.datetime.now().strftime("%H:%M"),
                    "wallet": float(wallet),
                    "pl": float(pl),
                }
                data.append(entry)
                with open(PNL_PATH, "w") as f:
                    json.dump(data, f, indent=2)
            except (ValueError, TypeError):
                self._send_json({"error": "wallet and pl must be numbers"}, 400)
                return
        self._send_json({"entries": data})

    def _handle_todofile(self, params):
        content = self._get_param(params, "content")
        if content is not None:
            try:
                with open(TODO_PATH, "w") as f:
                    f.write(content)
                self._send_json({"status": "saved"})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            return
        try:
            with open(TODO_PATH) as f:
                text = f.read()
            self._send_json({"content": text})
        except FileNotFoundError:
            self._send_json({"content": ""})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_server(self, params):
        action = self._get_param(params, "action", "")
        name = self._get_param(params, "name", "")
        PORT_MAP = {"upload": 3000, "stock": 9090, "welcome": 9091}
        CMD_MAP = {
            "upload": ["sh", "-c", "cd '{}' && bun run dev".format(os.path.join(HERE, "assets", "yt_upload_next"))],
            "stock": [sys.executable, "stock_dashboard.py"],
        }

        if action == "status":
            status = {}
            for n, p in PORT_MAP.items():
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    s.settimeout(1)
                    status[n] = s.connect_ex(("127.0.0.1", p)) == 0
                finally:
                    s.close()
            self._send_json({"servers": status})
            return

        if name not in PORT_MAP:
            self._send_json({"error": f"Unknown server: {name}"}, 400)
            return

        port = PORT_MAP[name]
        if action == "open":
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(1)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    self._send_json({"status": f"{name} already running"})
                    return
            finally:
                s.close()
            if name == "welcome":
                self._send_json({"status": "welcome is this page"})
                return
            logfile = os.path.join(HERE, f"{name}.server.log")
            try:
                handle = open(logfile, "ab")
            except OSError:
                handle = subprocess.DEVNULL
            try:
                subprocess.Popen(
                    CMD_MAP[name], cwd=HERE,
                    stdout=handle, stderr=subprocess.STDOUT,
                )
                self._send_json({"status": f"starting {name}"})
            except Exception as e:
                self._send_json({"error": str(e)}, 500)
            finally:
                if handle is not subprocess.DEVNULL:
                    handle.close()
        elif action == "close":
            import subprocess as sp
            sp.run(["fuser", "-k", "-n", "tcp", str(port)], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            for script in ("stock_dashboard.py", "welcome_dashboard.py"):
                sp.run(["pkill", "-f", script], stdout=sp.DEVNULL, stderr=sp.DEVNULL)
            self._send_json({"status": f"closed {name}"})
        else:
            self._send_json({"error": "action must be open/close/status"}, 400)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Welcome Dashboard")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), WelcomeHandler)
    print(f"Welcome dashboard at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
