import argparse
import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stock_tools import get_stock_data, get_stock_news, _resolve_ticker
from backtest_tools import (
    run as run_backtest,
    compare_strategies,
    stock_of_the_day,
    STRATEGY_MAP,
    example_strategies,
    format_result_json,
)

PORT = 9090


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        if path == "/api/quote":
            self._handle_quote(params)
        elif path == "/api/news":
            self._handle_news(params)
        elif path == "/api/backtest":
            self._handle_backtest(params)
        elif path == "/api/compare":
            self._handle_compare(params)
        elif path == "/api/stock-of-day":
            self._handle_stock_of_day(params)
        elif path == "/api/strategies":
            self._send_json(example_strategies())
        elif path == "/":
            self._serve_file("stock_dashboard.html")
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

    def _get_float(self, params, key, default=None):
        v = self._get_param(params, key)
        if v is None:
            return default
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    def _handle_quote(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        data = get_stock_data(resolved)
        if not data:
            self._send_json({"error": f"No data for {ticker}"}, 404)
            return
        self._send_json(data)

    def _handle_news(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        count = int(self._get_param(params, "count", "10"))
        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        resolved = _resolve_ticker(ticker)
        news = get_stock_news(resolved, count)
        self._send_json({"ticker": ticker, "resolved": resolved, "news": news})

    def _handle_backtest(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        strategy = self._get_param(params, "strategy", "ma_crossover")
        start = self._get_param(params, "start", "1y")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return
        if strategy not in STRATEGY_MAP:
            self._send_json(
                {"error": f"Unknown strategy. Choose: {', '.join(STRATEGY_MAP.keys())}"}, 400
            )
            return

        try:
            resolved = _resolve_ticker(ticker)
            result = run_backtest(
                ticker=resolved, strategy=strategy, start=start,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
            )
            data = format_result_json(result)
            data["strategy"] = strategy
            data["ticker"] = ticker
            data["resolved"] = resolved
            self._send_json(data)
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_compare(self, params):
        ticker = self._get_param(params, "ticker", "").upper()
        start = self._get_param(params, "start", "1y")
        stop_loss = self._get_float(params, "stop_loss")
        trailing_stop = self._get_float(params, "trailing_stop")

        if not ticker:
            self._send_json({"error": "Missing ticker parameter"}, 400)
            return

        try:
            resolved = _resolve_ticker(ticker)
            results = compare_strategies(
                ticker=resolved, start=start,
                stop_loss_pct=stop_loss, trailing_stop_pct=trailing_stop,
            )
            self._send_json({"ticker": ticker, "resolved": resolved, "strategies": results})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_stock_of_day(self, params):
        strategy = self._get_param(params, "strategy", "sma_50_trend")
        start = self._get_param(params, "start", "1y")
        movement_min = self._get_float(params, "movement_min", 10)
        movement_max = self._get_float(params, "movement_max", 30)

        try:
            top = stock_of_the_day(
                start=start, strategy=strategy,
                movement_min=movement_min, movement_max=movement_max,
            )
            self._send_json({"strategy": strategy, "movement_filter": f"{movement_min}%-{movement_max}%", "picks": top})
        except Exception as e:
            self._send_json({"error": str(e)}, 500)

    def log_message(self, format, *args):
        pass


def main():
    parser = argparse.ArgumentParser(description="Stock Dashboard Server")
    parser.add_argument("--port", type=int, default=PORT, help=f"Port (default: {PORT})")
    args = parser.parse_args()

    server = HTTPServer(("0.0.0.0", args.port), DashboardHandler)
    print(f"Stock dashboard running at http://localhost:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
