import pyttsx3
import speech_recognition as sr

engine = pyttsx3.init()
voices = engine.getProperty('voices')
# Set the voice (usually 0 is male, 1 is female; depends on OS)
engine.setProperty('voice', voices[0].id)

def speak(audio) -> None:
    print(f"JARVIS: {audio}")
    engine.say(audio)
    engine.runAndWait()

def takeCommand() -> str:
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print('Listening...')
        r.pause_threshold = 1
        r.adjust_for_ambient_noise(source, duration=1.5)
        audio = r.listen(source)

    try:
        print('Recognizing...')
        query = r.recognize_google(audio, language='en-in')
        print(f'User said: {query}\n')
    except Exception as e:
        print('Say that again please...')
        return 'none'
    return query.lower()
