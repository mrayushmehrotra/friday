import speech_recognition as sr
from gtts import gTTS
import subprocess
import webbrowser
import time
from datetime import datetime
import os
import sys
import tempfile
import wave

# faster-whisper: free, offline, runs locally (no API key needed)
from faster_whisper import WhisperModel


class Jarvis:
    def __init__(self, voice_mode=False, whisper_model="base"):
        self.recognizer = sr.Recognizer()
        self.voice_mode = voice_mode
        self.listening = False
        self._whisper = None          # lazy-loaded on first voice use
        self._whisper_model = whisper_model  # tiny/base/small/medium/large

    def _get_whisper(self):
        """Load Whisper model on first use (downloads ~150 MB for 'base' once)."""
        if self._whisper is None:
            print(f"[Jarvis] Loading Whisper '{self._whisper_model}' model "
                  "(first run downloads it automatically)...")
            # device="cpu" works on any machine; int8 keeps it fast & light
            self._whisper = WhisperModel(
                self._whisper_model, device="cpu", compute_type="int8"
            )
            print("[Jarvis] Whisper model ready.")
        return self._whisper

    def speak(self, text):
        print(f"Jarvis: {text}")
        if not self.voice_mode:
            return
        tts = gTTS(text=text, lang="en")
        tts.save("/tmp/jarvis_speak.mp3")
        subprocess.run(["mpg123", "-q", "/tmp/jarvis_speak.mp3"], capture_output=True)

    def listen(self):
        if not self.voice_mode:
            try:
                return input("You: ").lower()
            except EOFError:
                self.listening = False
                return ""

        with sr.Microphone() as source:
            print("Listening...")
            self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=10)
            except sr.WaitTimeoutError:
                return ""

        # Save audio to a temp WAV file and transcribe with Whisper (offline)
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
                wav_data = audio.get_wav_data()
                tmp.write(wav_data)

            model = self._get_whisper()
            segments, _ = model.transcribe(
                tmp_path,
                language="en",          # set to None for auto-detect
                beam_size=5,
                vad_filter=True,        # skip silent parts automatically
                vad_parameters=dict(min_silence_duration_ms=500),
            )
            command = " ".join(seg.text.strip() for seg in segments).lower().strip()
            print(f"You: {command}")
            return command

        except Exception as e:
            print(f"[Whisper error] {e}")
            return ""

        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def execute_command(self, command):
        if not command:
            return

        if "hello" in command or "hi" in command:
            self.speak("Hello! How can I help you?")

        elif "time" in command:
            current_time = datetime.now().strftime("%H:%M")
            self.speak(f"The time is {current_time}")

        elif "date" in command:
            current_date = datetime.now().strftime("%B %d, %Y")
            self.speak(f"Today's date is {current_date}")

        elif "open" in command and "browser" in command:
            self.speak("Opening browser")
            webbrowser.open("https://google.com")

        elif command.startswith("open "):
            app = command.replace("open", "").strip()
            self.speak(f"Opening {app}")
            try:
                subprocess.Popen(app, shell=True)
            except:
                self.speak(f"Could not open {app}")

        elif command.startswith("search "):
            query = command.replace("search", "").strip()
            self.speak(f"Searching for {query}")
            webbrowser.open(f"https://google.com/search?q={query}")

        elif "play music" in command or "play song" in command:
            self.speak("Opening music")
            webbrowser.open("https://music.youtube.com")

        elif "screenshot" in command:
            import pyautogui

            filename = f"screenshot_{int(time.time())}.png"
            pyautogui.screenshot(filename)
            self.speak(f"Screenshot saved as {filename}")

        elif command.startswith("type "):
            text = command.replace("type", "").strip()
            import pyperclip

            pyperclip.copy(text)
            self.speak(f"Copied to clipboard: {text}")

        elif "volume up" in command:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "+10%"], capture_output=True)
            self.speak("Volume increased")

        elif "volume down" in command:
            subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@", "-10%"], capture_output=True)
            self.speak("Volume decreased")

        elif "mute" in command:
            subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"], capture_output=True)
            self.speak("Toggled mute")

        elif command == "help":
            self.help()

        elif "stop" in command or "exit" in command or "goodbye" in command:
            self.speak("Goodbye!")
            self.listening = False

        else:
            self.speak(
                f"I didn't understand that command. Try saying help to see available commands."
            )

    def help(self):
        help_text = """Available commands:
  hello - Greet Jarvis
  time - Tell current time
  date - Tell today's date
  open <app> - Open an application
  browser - Open browser
  search <query> - Search on Google
  play music - Open YouTube Music
  screenshot - Take a screenshot
  type <text> - Copy text to clipboard
  volume up/down - Adjust volume
  mute - Mute/unmute
  help - Show this message
  stop/exit - Exit Jarvis"""
        print(help_text)
        self.speak("Here are my commands. Check terminal for full list.")

    def run(self):
        mode = "voice" if self.voice_mode else "terminal"
        self.speak(
            f"Jarvis is online in {mode} mode. Say or type help for commands, stop to exit."
        )
        self.listening = True

        while self.listening:
            command = self.listen()
            if self.voice_mode and "jarvis" in command:
                command = command.replace("jarvis", "").strip()

            self.execute_command(command)


if __name__ == "__main__":
    voice = "--voice" in sys.argv

    # Pick Whisper model size via --model <name>  (default: base)
    # Sizes: tiny (~39M) | base (~74M) | small (~244M) | medium (~769M) | large (~1.5G)
    # Bigger = more accurate but slower first load. 'base' is a great default.
    model_size = "base"
    if "--model" in sys.argv:
        idx = sys.argv.index("--model")
        if idx + 1 < len(sys.argv):
            model_size = sys.argv[idx + 1]

    jarvis = Jarvis(voice_mode=voice, whisper_model=model_size)
    jarvis.run()
