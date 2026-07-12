import datetime
import logging
import os
import sqlite3
import subprocess
import sys
import threading
from ctypes import *

# Silence ALSA/JACK errors
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)


def py_error_handler(filename, line, function, err, fmt):
    pass


c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)

try:
    asound = cdll.LoadLibrary("libasound.so.2")
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

# Setup Logging
logging.basicConfig(
    filename="jarvis.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Global models and state
_tts = None
_tts_type = None
_piper_voice = None


def get_piper_voice():
    global _piper_voice
    if _piper_voice is not None:
        return _piper_voice

    try:
        from piper import PiperVoice

        voice_name = os.environ.get("PIPER_VOICE", "en_US-ryan-medium")
        voice_dir = os.path.expanduser("~/.local/share/piper-voices")
        os.makedirs(voice_dir, exist_ok=True)
        model_path = os.path.join(voice_dir, f"{voice_name}.onnx")
        config_file = f"{voice_name}.onnx.json"

        if not os.path.exists(model_path):
            print(f"Downloading Piper voice ({voice_name}) (~60MB)...")
            import requests

            token = os.environ.get("HF_TOKEN")
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            parts = voice_name.split("-")
            lang = parts[0].split("_")[0]
            subpath = f"{lang}/{parts[0]}/{parts[1]}/{parts[2]}"
            base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{subpath}"

            names = [f"{voice_name}.onnx", config_file]
            for fname in names:
                url = f"{base}/{fname}"
                dest = os.path.join(voice_dir, fname)
                if os.path.exists(dest):
                    continue
                resp = requests.get(url, headers=headers, stream=True, timeout=60)
                resp.raise_for_status()
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(dest, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total:
                            pct = downloaded * 100 // total
                            print(
                                f"\r  {fname}: {pct}% ({downloaded//1024**2}MB/{total//1024**2}MB)",
                                end="",
                            )
                print()

        _piper_voice = PiperVoice.load(model_path)
        return _piper_voice
    except Exception as e:
        log_event(f"Piper TTS unavailable: {e}", "error")
        _piper_voice = False
        return None


# SPEED CONFIG
SPEECH_SPEED = 0.8


def get_tts():
    global _tts, _tts_type
    if _tts is None:
        try:
            import pyttsx3

            _tts = pyttsx3.init()
            _tts_type = "pyttsx3"
        except Exception:
            _tts_type = None
            print("WARNING: No TTS engine available. Voice output disabled.")
            log_event("No TTS engine available", "error")
    return _tts


def init_db():
    conn = sqlite3.connect("chat_history.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT,
            message TEXT
        )
    """)
    conn.commit()
    conn.close()


def save_chat_to_db(role, message):
    try:
        conn = sqlite3.connect("chat_history.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO chat (role, message) VALUES (?, ?)", (role, message)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Database error: {e}")


def log_event(message, level="info"):
    if level == "info":
        logging.info(message)
    elif level == "error":
        logging.error(message)


_speech_thread = None
_speech_lock = threading.Lock()


def stop_speech():
    global _speech_thread
    with _speech_lock:
        if _speech_thread and _speech_thread.is_alive():
            subprocess.run(["pkill", "-f", "paplay"], capture_output=True)
            _speech_thread = None
            subprocess.run(
                ["wpctl", "set-mute", "@DEFAULT_SOURCE@", "0"],
                capture_output=True,
            )


def _mute_mic(mute: bool):
    val = "1" if mute else "0"
    subprocess.run(
        ["wpctl", "set-mute", "@DEFAULT_SOURCE@", val],
        capture_output=True,
    )


def speak(audio, wait=False) -> None:
    print(f"JARVIS: {audio}")
    log_event(f"Speak: {audio}")

    def _worker(text):
        _mute_mic(True)
        try:
            try:
                voice = get_piper_voice()
                if voice:
                    import wave

                    output_path = "output.wav"
                    with wave.open(output_path, "wb") as wav_file:
                        voice.synthesize_wav(text, wav_file)

                    subprocess.run(
                        ["paplay", output_path],
                        capture_output=True,
                    )
                    try:
                        os.unlink(output_path)
                    except Exception:
                        pass
                    return
            except Exception as e:
                log_event(f"Piper speech error: {e}", "error")

            engine = get_tts()
            if engine is None or _tts_type is None:
                return
            rate = int(200 * SPEECH_SPEED)
            engine.setProperty("rate", rate)
            engine.say(text)
            engine.runAndWait()
        finally:
            _mute_mic(False)

    global _speech_thread
    with _speech_lock:
        _speech_thread = threading.Thread(target=_worker, args=(audio,), daemon=True)
        _speech_thread.start()
    if wait:
        _speech_thread.join()


try:
    import speech_recognition as sr
except ImportError:
    sr = None


def takeCommand(timeout=None, phrase_limit=None) -> str:
    if sr is None:
        return "none"

    _recognizer = sr.Recognizer()
    _recognizer.energy_threshold = 2000
    _recognizer.dynamic_energy_threshold = True
    _recognizer.dynamic_energy_adjustment_damping = 0.15
    _recognizer.dynamic_energy_ratio = 1.5
    _recognizer.pause_threshold = 1.0
    _recognizer.phrase_threshold = 0.3
    _recognizer.non_speaking_duration = 0.8

    with sr.Microphone() as source:
        if timeout is None:
            print("\n--- Listening ---")

        try:
            if timeout is None:
                _recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_sr = _recognizer.listen(
                source, timeout=timeout, phrase_time_limit=phrase_limit
            )
        except sr.WaitTimeoutError:
            return "none"
        except Exception:
            return "none"

    if timeout is None:
        print("Recognizing...")

    query = _try_recognize(_recognizer, audio_sr, timeout is None)
    return query


def _try_recognize(recognizer, audio_sr, verbose: bool) -> str:
    engines = [
        ("Google Cloud", lambda: recognizer.recognize_google(audio_sr)),
        (
            "Faster Whisper",
            lambda: recognizer.recognize_faster_whisper(
                audio_sr, model="base", language="en"
            ),
        ),
    ]

    for name, fn in engines:
        try:
            query = fn().strip().lower()
            if query:
                if verbose:
                    print(f"User ({name}): {query}")
                return query
        except sr.UnknownValueError:
            continue
        except Exception as e:
            log_event(f"{name} STT error: {e}", "error")
            continue

    return "none"
