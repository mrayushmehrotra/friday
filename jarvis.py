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
        greeting = "Jarvis is online, How's your day?"
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

        elif 'open github' in query:
            webbrowser.open_new_tab('https://github.com/mrayushmehrotra')
            speak("Opening Github dashboard.")

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
                if 'remove' in command or 'rm' in command:
                    speak(f"Confirm: Do you really want to run {command}?")
                    confirm = takeCommand()
                    if 'yes' in confirm:
                        os.system(confirm if 'rm' in confirm else command) # Just being safe
                        os.system(command)
                        speak("Command executed.")
                    else:
                        speak("Aborted.")
                else:
                    os.system(f"{command} &")
                    speak(f"Executing {command}")

        elif 'copy' in query:
            text_to_copy = query.replace('copy', '', 1).strip()
            if not text_to_copy:
                speak("What text should I copy?")
                text_to_copy = takeCommand()
            
            if text_to_copy != 'none':
                import pyperclip
                pyperclip.copy(text_to_copy)
                speak("Text copied to clipboard.")

        elif 'write' in query or 'right' in query:
            # Fix: Cleanup text by removing both 'write' and 'right'
            text_to_write = query.replace('write', '', 1).replace('right', '', 1).strip()
            if not text_to_write:
                speak("What should I write?")
                text = takeCommand()
                if text != 'none':
                    text_to_write = text
            
            if text_to_write != 'none' and text_to_write.strip():
                import pyperclip
                import time
                speak("Writing in 2 seconds. Focus your field.")
                time.sleep(2)
                
                try:
                    old_clip = pyperclip.paste()
                except:
                    old_clip = ""
                
                pyperclip.copy(text_to_write)
                
                # Check for Wayland vs X11
                is_wayland = os.environ.get('XDG_SESSION_TYPE') == 'wayland'
                
                if is_wayland:
                    if os.system("which wtype > /dev/null 2>&1") == 0:
                        os.system(f"wtype '{text_to_write}'")
                    else:
                        try:
                            # Try hotkey paste but wrap to avoid X11 crash
                            import pyautogui
                            pyautogui.hotkey('ctrl', 'v')
                        except:
                            speak("Ready to paste. Please press Ctrl V.")
                else:
                    try:
                        import pyautogui
                        pyautogui.hotkey('ctrl', 'v')
                    except:
                        speak("Paste failed. Do it manually.")

                time.sleep(0.5)
                try:
                    pyperclip.copy(old_clip)
                except:
                    pass
                speak("Done.")

        elif 'close' in query or 'window close' in query:
            speak("Closing.")
            try:
                import pyautogui
                pyautogui.hotkey('ctrl', 'q')
            except:
                is_wayland = os.environ.get('XDG_SESSION_TYPE') == 'wayland'
                if is_wayland and os.system("which wtype > /dev/null 2>&1") == 0:
                     os.system("wtype -M ctrl -k q -m ctrl")
                else:
                     speak("I can't close this window automatically. Try Ctrl Q.")

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
            # System instruction for brevity as requested by user
            system_instruction = "You are JARVIS, a highly concise local AI. Answer the user in one short sentence only."
            full_prompt = f"{system_instruction}\n\nUser: {query}\nAssistant:"
            
            payload = {"model": self.model, "prompt": full_prompt, "stream": False}
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
            # Increased responsiveness by using a very short timeout
            interrupt = takeCommand(timeout=0.1, phrase_limit=1.0)
            if any(word in interrupt for word in ["stop", "wait", "shut up", "cancel"]):
                self.aborted = True
                speak("Alright, stopping.")
                log_event("AI generation interrupted by user")
                return 

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
