import argparse
import json
import os
import subprocess
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stock_tools import get_stock_data, get_stock_news, _resolve_ticker

PORT = 9091
NOTES_PATH = os.path.expanduser("~/notes.md")


class WelcomeHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/todos":
            self._handle_todos()
        elif path == "/api/news":
            self._handle_news(params)
        elif path == "/api/quote":
            self._handle_quote(params)
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

    def _handle_todos(self):
        todos = []
        if os.path.exists(NOTES_PATH):
            with open(NOTES_PATH) as f:
                text = f.read()
            for line in text.splitlines():
                stripped = line.strip()
                if stripped.startswith("- [ ]"):
                    todos.append({"text": stripped[5:].strip(), "done": False})
                elif stripped.startswith("- [x]"):
                    todos.append({"text": stripped[5:].strip(), "done": True})
        self._send_json({"todos": todos})

    def _handle_news(self, params):
        raw = self._get_param(params, "ticker", "").upper()
        ticker = _resolve_ticker(raw) if raw else "^NSEI"
        count = int(self._get_param(params, "count", "10"))
        news = get_stock_news(ticker, count) if ticker else []
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
        self._send_json({"status": "received", "command": cmd})

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Welcome Dashboard")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), WelcomeHandler)
    print(f"Welcome dashboard at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
