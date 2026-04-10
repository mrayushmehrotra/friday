import os
import sys
import datetime
import logging
import sqlite3
import speech_recognition as sr
from ctypes import *

# Silence ALSA/JACK errors
ERROR_HANDLER_FUNC = CFUNCTYPE(None, c_char_p, c_int, c_char_p, c_int, c_char_p)
def py_error_handler(filename, line, function, err, fmt):
    pass
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)

try:
    asound = cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

# Polyfill to fix Coqui TTS compatibility with newer transformers versions
try:
    import transformers
    if not hasattr(transformers.pytorch_utils, 'isin_mps_friendly'):
        transformers.pytorch_utils.isin_mps_friendly = lambda a, b: a.isin(b)
except (ImportError, AttributeError):
    pass

# Setup Logging
logging.basicConfig(
    filename='jarvis.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Global models and state
_tts = None
_tts_type = None 
_recognizer = sr.Recognizer()

# SPEED CONFIG (Adjust here)
SPEECH_SPEED = 1.3 

def get_tts():
    global _tts, _tts_type
    if _tts is None:
        try:
            from TTS.api import TTS
            print("Loading Coqui TTS male voice model (vctk)...")
            # Switching to a multi-speaker model for a male voice
            _tts = TTS(model_name="tts_models/en/vctk/vits", progress_bar=False, gpu=False)
            _tts_type = 'coqui'
        except Exception as e:
            print(f"Coqui TTS failed to load: {e}. Falling back to pyttsx3.")
            import pyttsx3
            _tts = pyttsx3.init()
            _tts_type = 'pyttsx3'
    return _tts

def init_db():
    conn = sqlite3.connect('chat_history.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            role TEXT,
            message TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_chat_to_db(role, message):
    try:
        conn = sqlite3.connect('chat_history.db')
        cursor = conn.cursor()
        cursor.execute('INSERT INTO chat (role, message) VALUES (?, ?)', (role, message))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Database error: {e}")

def log_event(message, level='info'):
    if level == 'info':
        logging.info(message)
    elif level == 'error':
        logging.error(message)

def speak(audio) -> None:
    print(f"JARVIS: {audio}")
    log_event(f"Speak: {audio}")
    engine = get_tts()
    
    if _tts_type == 'coqui':
        try:
            output_path = "output.wav"
            # Using speaker 'p232' for a soft male voice in VCTK
            try:
                engine.tts_to_file(text=audio, speaker="p232", file_path=output_path, speed=SPEECH_SPEED)
            except (TypeError, Exception):
                # Fallback if specific speaker or speed is not accepted
                engine.tts_to_file(text=audio, speaker="p232", file_path=output_path)
                fast_path = "output_fast.wav"
                os.system(f"ffmpeg -i {output_path} -filter:a 'atempo={SPEECH_SPEED}' {fast_path} -y > /dev/null 2>&1")
                output_path = fast_path
            os.system(f"aplay {output_path} > /dev/null 2>&1")
        except Exception as e:
            log_event(f"Coqui speech error: {e}", 'error')
    else:
        # pyttsx3 fallback
        rate = int(200 * SPEECH_SPEED)
        engine.setProperty('rate', rate)
        engine.say(audio)
        engine.runAndWait()

def takeCommand(timeout=None, phrase_limit=None) -> str:
    global _recognizer
    _recognizer.energy_threshold = 400 
    _recognizer.dynamic_energy_threshold = True
    
    with sr.Microphone() as source:
        if timeout is None:
            print('\n--- Listening ---')
        _recognizer.pause_threshold = 1.0
        
        if timeout is None:
            _recognizer.adjust_for_ambient_noise(source, duration=0.8)
        
        try:
            audio = _recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_limit)
            print("Recognizing...")
            query = _recognizer.recognize_google(audio, language='en-in')
            query = query.strip().lower()
            
            if query:
                if timeout is None:
                    print(f'User: {query}')
                return query
        except Exception:
            return 'none'
    return 'none'
