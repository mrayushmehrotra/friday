#!/usr/bin/env python3
import json
import http.server
import socket
import socketserver
import psutil
import os
import sys
import datetime
import webbrowser
import subprocess
import urllib.request
import re
import sqlite3
import xml.etree.ElementTree as ET

PORT = 8000

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from helpers import init_db, log_event, save_chat_to_db


def fetch_weather():
    try:
        with urllib.request.urlopen(
            "https://wttr.in/Mau?format=%C+%t&m", timeout=5
        ) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def fetch_weather_json():
    try:
        with urllib.request.urlopen(
            "https://wttr.in/Mau?format=j1", timeout=5
        ) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def fetch_india_news():
    try:
        url = "https://news.google.com/rss/search?q=india+technology&hl=en-IN&gl=IN&ceid=IN:en"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            xml_data = r.read().decode()
        root = ET.fromstring(xml_data)
        items = []
        for item in root.iter('item'):
            title = item.find('title').text if item.find('title') is not None else ''
            link = item.find('link').text if item.find('link') is not None else ''
            pub_date = item.find('pubDate').text if item.find('pubDate') is not None else ''
            source = item.find('source').text if item.find('source') is not None else ''
            items.append({
                'title': title,
                'link': link,
                'date': pub_date,
                'source': source,
            })
        return items[:15]
    except Exception as e:
        print(f"News fetch error: {e}")
        return []


def read_notes():
    notes_path = os.path.join(os.path.dirname(__file__), '..', 'notes.txt')
    try:
        with open(notes_path) as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


class JarvisAPI:

    def __init__(self):
        init_db()
        log_event("JARVIS Web UI initialized")

    def get_init_data(self):
        weather = fetch_weather()
        weather_json = fetch_weather_json()
        notes = read_notes()

        return {
            "greeting": "welcome home, sir",
            "notes": notes,
            "weather": weather,
            "weather_json": weather_json,
        }

    def execute_query(self, query):
        query = query.lower().strip()
        response = None

        if "time" in query:
            strTime = datetime.datetime.now().strftime("%H:%M:%S")
            response = f"Sir, the time is {strTime}"
        elif "open google" in query:
            response = "Opening Google."
        elif "open github" in query:
            response = "Opening Github."
        elif "finance" in query or "market" in query:
            response = "Checking market."
        elif "open terminal" in query:
            response = "Opening terminal."
        elif "mute" in query:
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 1 > /dev/null 2>&1")
            response = "Muted."
        elif "unmute" in query:
            os.system("wpctl set-mute @DEFAULT_AUDIO_SINK@ 0 > /dev/null 2>&1")
            response = "Unmuted."
        elif "volume" in query:
            nums = re.findall(r"\d+", query)
            if nums:
                level = min(int(nums[0]), 100)
                os.system(f"wpctl set-volume @DEFAULT_AUDIO_SINK@ {level}% > /dev/null 2>&1")
                response = f"Volume set to {level} percent."
            else:
                response = "What volume level, sir?"
        elif "remember" in query:
            text = query.replace("remember", "", 1).strip()
            if text:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                notes_path = os.path.join(os.path.dirname(__file__), '..', 'notes.txt')
                with open(notes_path, "a") as f:
                    f.write(f"[{timestamp}] {text}\n")
                response = "I'll remember that, sir."
            else:
                response = "What should I remember?"
        elif "let's work" in query or "lets work" in query:
            response = "Let's get to work, sir!"
        elif "evade" in query:
            response = "Shutting down the system, sir."
            os.system("shutdown now")
        elif "sleep" in query or "stop" in query:
            response = "Goodbye SIR"
        elif "notes" in query or "tasks" in query or "task" in query or "what's my plan" in query:
            notes = read_notes()
            if notes:
                response = notes
            else:
                response = "No notes for today, sir."
        elif "news" in query:
            news = fetch_india_news()
            if news:
                headlines = ". ".join([n['title'][:80] for n in news[:5]])
                response = f"Top headlines. {headlines}"
            else:
                response = "Could not fetch news, sir."
        elif "weather" in query:
            w = fetch_weather()
            response = f"weather is {w}" if w else "Could not fetch weather, sir."
        else:
            response = "I don't know how to do that, sir"

        save_chat_to_db("user", query)
        save_chat_to_db("jarvis", response)
        log_event(f"Query: {query} -> Response: {response}")

        return response


def get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        try:
            return urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
        except Exception:
            return "127.0.0.1"


def format_bytes(b):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


api = JarvisAPI()


class ApiHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        if self.path == '/api/system':
            disk = psutil.disk_usage("/")
            net = psutil.net_io_counters()
            cpu_freq = psutil.cpu_freq()
            boot = datetime.datetime.fromtimestamp(psutil.boot_time())
            uptime = str(datetime.datetime.now() - boot).split(".")[0]
            battery = psutil.sensors_battery()
            self.send_json({
                'cpu': psutil.cpu_percent(interval=0.3),
                'cpu_count': psutil.cpu_count(),
                'cpu_freq': cpu_freq.current if cpu_freq else 0,
                'ram': psutil.virtual_memory().percent,
                'ram_used': psutil.virtual_memory().used,
                'ram_total': psutil.virtual_memory().total,
                'disk_total': disk.total,
                'disk_used': disk.used,
                'disk_free': disk.free,
                'disk_percent': disk.percent,
                'net_sent': net.bytes_sent,
                'net_recv': net.bytes_recv,
                'uptime': uptime,
                'ip': get_ip(),
                'battery_percent': battery.percent if battery else None,
                'battery_charging': battery.power_plugged if battery else None,
            })
        elif self.path == '/api/init':
            self.send_json(api.get_init_data())
        elif self.path == '/api/weather':
            self.send_json(api.get_init_data())
        elif self.path == '/api/news':
            self.send_json(fetch_india_news())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == '/api/command':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            data = json.loads(body)
            query = data.get('query', '')
            response = api.execute_query(query)
            self.send_json({'response': response, 'query': query})

    def send_json(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def log_message(self, format, *args):
        pass


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print(f"JARVIS HUD Server running at http://localhost:{PORT}")
    print("Open it in your browser for the JARVIS UI experience.")
    with socketserver.TCPServer(("", PORT), ApiHandler) as httpd:
        httpd.serve_forever()
