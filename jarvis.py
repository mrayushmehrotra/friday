import datetime
import os
import subprocess
import sys
import webbrowser

from helpers import init_db, log_event, speak, takeCommand


class Jarvis:
    def __init__(self) -> None:
        init_db()
        log_event("JARVIS initialized")

    def wishMe(self) -> None:
        music = os.path.expanduser("~/personal/friday/assets/background_music.mp3")
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-af", "volume=0.5", music],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        greeting = "welcome home, sir"
        speak(greeting)
        try:
            webbrowser.open_new_tab("https://app.todoist.com/app/inbox")
            with open("notes.txt") as f:
                notes = f.read().strip()
            if notes:
                speak(notes)
        except FileNotFoundError:
            pass

        music = os.path.expanduser("~/personal/friday/assets/background_music.m4a")
        subprocess.Popen(
            ["ffplay", "-nodisp", "-autoexit", "-af", "volume=0.5", music],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def execute_query(self, query):
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

        elif (
            "what's about the finance" in query
            or "finance" in query
            or "check market" in query
        ):
            webbrowser.open_new_tab(
                "https://www.worldmonitor.app/?lat=20.0000&lon=-36.1535&zoom=1.00&view=global&timeRange=7d&layers=conflicts%2Cbases%2Cpipelines%2Chotspots%2Cnuclear%2Csanctions%2Cweather%2Ceconomic%2Cwaterways%2Coutages%2Cdatacenters%2Cmilitary%2Cnatural%2CiranAttacks"
            )
            speak("checking market")
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
        elif "remember" in query:
            text = query.replace("remember", "", 1).strip()
            if text:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                with open("notes.txt", "a") as f:
                    f.write(f"[{timestamp}] {text}\n")
                speak("I'll remember that, sir.")
            else:
                speak("What should I remember?")
        elif "let's work" in query or "lets work" in query:
            import subprocess

            mp3 = os.path.expanduser("~/personal/friday/assets/lets_work.m4a")
            subprocess.Popen(
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
        elif "evade" in query:
            speak("Shutting down the system, sir.")
            os.system("shutdown now")
        elif "sleep" in query or "stop" in query:
            speak("Goodbye SIR")
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


def main():
    bot = Jarvis()
    bot.wishMe()
    while True:
        query = takeCommand()
        if query != "none":
            bot.execute_query(query)


if __name__ == "__main__":
    main()
