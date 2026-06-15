import datetime
import json
import os
import subprocess
import sys
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET

from helpers import init_db, log_event, speak, takeCommand


class Jarvis:
    def __init__(self) -> None:
        init_db()
        log_event("JARVIS initialized")
        self._music_proc = None
        self._start_web_ui()

    def _start_web_ui(self):
        server_path = os.path.join(os.path.dirname(__file__), "jarvis-ui", "server.py")
        self._server_proc = subprocess.Popen(
            [sys.executable, server_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log_event("JARVIS Web UI started")

    def _kill_music(self):
        if self._music_proc and self._music_proc.poll() is None:
            self._music_proc.terminate()
            try:
                self._music_proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._music_proc.kill()
        self._music_proc = None

    def wishMe(self) -> None:
        music = os.path.expanduser("~/personal/friday/assets/background_music.mp3")
        self._music_proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-af", "volume=0.1", music],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        greeting = "welcome home, sir"
        speak(greeting)
        try:
            webbrowser.open_new_tab("https://app.todoist.com/app/inbox")
            webbrowser.open_new_tab("http://localhost:8000")
            with open("notes.txt") as f:
                notes = f.read().strip()
            if notes:
                speak(notes)
        except FileNotFoundError:
            pass

        try:
            import urllib.request

            with urllib.request.urlopen(
                "https://wttr.in/Mau?format=%C+%t", timeout=5
            ) as r:
                weather = r.read().decode().strip()
            if weather:
                speak(f"weather is {weather}")
        except Exception:
            pass

        music = os.path.expanduser("~/personal/friday/assets/background_music.m4a")
        self._music_proc = subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-af", "volume=0.5", music],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def execute_query(self, query):
        for prefix in ["jarvis ", "jarvis", "jarvis's "]:
            if query.startswith(prefix):
                query = query.removeprefix(prefix)
                break
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

        elif "news" in query or "finance" in query or "market" in query:
            try:
                url = "https://news.google.com/rss/search?q=india+technology&hl=en-IN&gl=IN&ceid=IN:en"
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    xml_data = r.read().decode()
                root = ET.fromstring(xml_data)
                items = []
                for item in root.iter('item'):
                    title = item.find('title').text if item.find('title') is not None else ''
                    if title:
                        items.append(title)
                if items:
                    headlines = ". ".join(items[:4])
                    speak(f"News. {headlines}")
                else:
                    speak("No news found, sir.")
            except Exception:
                speak("Could not fetch news, sir.")
        elif "open terminal" in query:
            if os.system("which kitty > /dev/null 2>&1") == 0:
                os.system("kitty &")
            speak("Opening terminal.")
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
                with open("notes.txt", "a") as f:
                    f.write(f"[{timestamp}] {text}\n")
                speak("I'll remember that, sir.")
            else:
                speak("What should I remember?")
        elif "daddy's home" in query or "daddy is home" in query or "daddy home" in query:
            speak("Welcome home, sir!")
            self.wishMe()
        elif "let's work" in query or "lets work" in query:
            import subprocess

            mp3 = os.path.expanduser("~/personal/friday/assets/lets_work.m4a")
            self._kill_music()
            self._music_proc = subprocess.Popen(
                ["ffplay", "-nodisp", "-autoexit", mp3],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            speak("Let's get to work, sir!")
        elif "copy" in query:
            text = query.replace("copy", "", 1).strip()
            import pyperclip

            pyperclip.copy(text)
            speak("Copied.")
        elif "write" in query or "right" in query:
            self.handle_write(query)
        elif "close" in query:
            self.handle_close()
        elif "stop the song" in query or "stop music" in query or "stop song" in query:
            self._kill_music()
            speak("Music stopped, sir.")
        elif "evade" in query:
            speak("Shutting down the system, sir.")
            os.system("shutdown now")
        elif "sleep" in query or "stop" in query or "goodbye" in query:
            speak("Goodbye SIR")
            self._cleanup()
            sys.exit()
        else:
            speak("I don't know how to do that, sir")

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

    def _cleanup(self):
        if hasattr(self, "_server_proc") and self._server_proc.poll() is None:
            self._server_proc.terminate()
            try:
                self._server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._server_proc.kill()


def main():
    bot = Jarvis()
    try:
        bot.wishMe()
        while True:
            query = takeCommand()
            if query != "none":
                bot.execute_query(query)
    finally:
        bot._cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
