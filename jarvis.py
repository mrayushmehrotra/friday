import datetime
import os
import sys
import webbrowser
import requests
import threading
from helpers import speak, takeCommand, init_db, save_chat_to_db, log_event

class Jarvis:
    def __init__(self) -> None:
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "phi3:mini"
        init_db()
        log_event("JARVIS initialized")

    def wishMe(self) -> None:
        hour = int(datetime.datetime.now().hour)
        greeting = "Jarvis is online, How's your day?" if 0 <= hour < 12 else "How's your afternoon going?" if 12 <= hour < 18 else "How's your evening going?"
        speak(greeting)

    def execute_query(self, query):
        if 'time' in query:
            strTime = datetime.datetime.now().strftime("%H:%M:%S")
            speak(f'Sir, the time is {strTime}')

        elif 'open google' in query:
            webbrowser.open_new_tab('https://google.com')
            speak("Opening Google.")

        elif 'open youtube' in query:
            webbrowser.open_new_tab('https://youtube.com')
            speak("Opening Youtube.")

        elif 'open vercel' in query:
            webbrowser.open_new_tab('https://vercel.com/dashboard')
            speak("Opening Vercel dashboard.")

        elif 'open training' in query:
            webbrowser.open_new_tab('https://neurobro.vercel.app/')
            speak("Opening your brain training application.")

        elif 'open terminal' in query:
            if os.system("which ghostty > /dev/null 2>&1") == 0:
                os.system("ghostty &")
                speak("Opening Ghostty.")
            else:
                speak("I couldn't find Ghostty on your system.")

        elif 'run command' in query or 'terminal' in query:
            speak("What terminal command should I execute?")
            command = takeCommand()
            if command != 'none':
                # Special handling for 'remove' or 'rm' as requested
                if 'remove' in command or 'rm' in command:
                    speak(f"Confirm: Do you really want to run {command}?")
                    confirm = takeCommand()
                    if 'yes' in confirm:
                        os.system(command)
                        speak("Command executed.")
                    else:
                        speak("Aborted.")
                else:
                    os.system(f"{command} &")
                    speak(f"Executing {command}")

        elif 'who are you' in query:
            speak('I am JARVIS, your local AI assistant.')

        elif 'search' in query:
            speak('What should I search for?')
            search = takeCommand()
            if search != 'none':
                save_chat_to_db('user', f'SEARCH: {search}')
                webbrowser.open_new_tab('https://google.com/search?q=' + search)
                speak(f'Searching for {search}')

        elif 'sleep' in query or 'stop' in query:
            speak('Goodbye SIR')
            sys.exit()

        else:
            self.ask_ai(query)

    def ask_ai(self, query):
        save_chat_to_db('user', query)
        speak("Thinking...")
        
        self.ai_result = None
        self.ai_completed = False
        self.aborted = False

        def ai_worker():
            payload = {"model": self.model, "prompt": query, "stream": False}
            try:
                response = requests.post(self.ollama_url, json=payload, timeout=30)
                if response.status_code == 200:
                    self.ai_result = response.json().get('response', '')
            except Exception as e:
                log_event(f"AI Worker Error: {e}", "error")
            self.ai_completed = True

        thread = threading.Thread(target=ai_worker)
        thread.daemon = True
        thread.start()

        # Check for "stop" while AI is processing
        while not self.ai_completed:
            # We use a short timeout and phrase limit to check for interruptions
            # This will loop until the AI is done or "stop" is heard
            interrupt = takeCommand(timeout=0.5, phrase_limit=1.5)
            if "stop" in interrupt:
                self.aborted = True
                speak("Alright, stopping.")
                log_event("AI generation interrupted by user")
                return # Go back to main loop

        if self.ai_result and not self.aborted:
            save_chat_to_db('assistant', self.ai_result)
            speak(self.ai_result)
        elif not self.ai_result and self.ai_completed and not self.aborted:
            speak("couldn't find one, sorry.")

def main():
    bot = Jarvis()
    bot.wishMe()
    while True:
        query = takeCommand()
        if query != 'none':
            if 'stop' == query.strip():
                speak("I am already listening, SIR.")
            else:
                bot.execute_query(query)

if __name__ == '__main__':
    main()
