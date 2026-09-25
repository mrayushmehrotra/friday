import json
import os
import socket
import subprocess
import sys

from hermes_agent import execute_hermes_task
from helpers import init_db, log_event, speak, takeCommand


class Ultron:
    """Thin entry-point shell. All intelligence & actions live in Hermes."""

    def __init__(self) -> None:
        init_db()
        log_event("ULTRON initialized")
        self._welcome_proc = None

    def _is_port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _open_welcome(self) -> bool:
        devnull = subprocess.DEVNULL
        base = os.path.dirname(os.path.abspath(__file__))
        if self._is_port_open(9091):
            return True
        try:
            self._welcome_proc = subprocess.Popen(
                [sys.executable, "welcome_dashboard.py", "--port", "9091"],
                cwd=base,
                stdout=devnull,
                stderr=devnull,
            )
            return True
        except Exception as e:
            log_event(f"Welcome dashboard failed: {e}", "error")
            return False

    def _close_welcome(self):
        if self._welcome_proc and self._welcome_proc.poll() is None:
            self._welcome_proc.terminate()
            try:
                self._welcome_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._welcome_proc.kill()
        self._welcome_proc = None

    def wishMe(self) -> None:
        import webbrowser

        from enhanced import speak_daily_briefing

        if self._open_welcome():
            webbrowser.open_new_tab("http://localhost:9091")
        speak_daily_briefing()

    def execute_query(self, query) -> bool:
        from helpers import stop_speech

        stop_speech()
        for prefix in ["ultron ", "ultron", "ultron's ", "hermes ", "hermes"]:
            if query.startswith(prefix):
                query = query.removeprefix(prefix)
                break

        # Everything is handled by the Hermes agent layer.
        execute_hermes_task(query)
        return True

    def _cleanup(self):
        try:
            from tools import automation_tools, linux_tools

            automation_tools.stop_hand_control()
            linux_tools.stop_music()
        except Exception:
            pass
        if self._welcome_proc and self._welcome_proc.poll() is None:
            self._welcome_proc.terminate()
            try:
                self._welcome_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._welcome_proc.kill()


def main():
    print("Starting Ultron...")
    bot = Ultron()
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
