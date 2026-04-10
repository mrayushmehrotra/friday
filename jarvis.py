import datetime
import os
import sys
import webbrowser
import requests
import threading
import json
from helpers import speak, takeCommand, init_db, save_chat_to_db, log_event

class Jarvis:
    def __init__(self) -> None:
        self.ollama_url = "http://localhost:11434/api/chat" # Switched to chat for tool support
        self.model = "qwen3.5:latest" # Using the better model you have for MCP
        init_db()
        log_event("JARVIS initialized with MCP support")
        
        # Internal MCP-like Tool Registry
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_time",
                    "description": "Get the current system time",
                    "parameters": {"type": "object", "properties": {}}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "open_website",
                    "description": "Open a specific URL in the browser",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The URL to open"}
                        },
                        "required": ["url"]
                    }
                }
            }
        ]

    def wishMe(self) -> None:
        hour = int(datetime.datetime.now().hour)
        greeting = "Jarvis is online, How's your day?"
        speak(greeting)

    def execute_query(self, query):
        # Handle hardcoded voice shortcuts first for speed
        if 'time' in query:
            strTime = datetime.datetime.now().strftime("%H:%M:%S")
            speak(f'Sir, the time is {strTime}')
        elif 'open google' in query:
            webbrowser.open_new_tab('https://google.com')
            speak("Opening Google.")
        elif 'open github' in query:
            webbrowser.open_new_tab('https://github.com/mrayushmehrotra')
            speak("Opening Github.")
        elif 'open terminal' in query:
            if os.system("which ghostty > /dev/null 2>&1") == 0:
                os.system("ghostty &")
                speak("Opening Ghostty.")
        elif 'copy' in query:
            text = query.replace('copy', '', 1).strip()
            import pyperclip
            pyperclip.copy(text)
            speak("Copied.")
        elif 'write' in query or 'right' in query:
            self.handle_write(query)
        elif 'close' in query:
            self.handle_close()
        elif 'sleep' in query or 'stop' in query:
            speak('Goodbye SIR')
            sys.exit()
        else:
            # Fallback to AI (Now with MCP Tool Calling)
            self.ask_ai_mcp(query)

    def handle_write(self, query):
        text_to_write = query.replace('write', '', 1).replace('right', '', 1).strip()
        if not text_to_write:
            speak("What should I write?")
            text_to_write = takeCommand()
        if text_to_write != 'none':
            import pyperclip, time
            speak("Writing in 2 seconds.")
            time.sleep(2)
            old_clip = pyperclip.paste()
            pyperclip.copy(text_to_write)
            if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
                os.system(f"wtype '{text_to_write}'") or os.system("pyautogui hotkey ctrl v") # Simplified fallback
            else:
                os.system("xdotool key ctrl+v")
            time.sleep(0.5)
            pyperclip.copy(old_clip)
            speak("Done.")

    def handle_close(self):
        speak("Closing.")
        if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
            os.system("wtype -M ctrl -k q -m ctrl")
        else:
            os.system("xdotool key ctrl+q")

    def ask_ai_mcp(self, query):
        save_chat_to_db('user', query)
        speak("Thinking...")
        
        self.ai_result = None
        self.ai_completed = False
        self.aborted = False

        def ai_worker():
            messages = [
                {"role": "system", "content": "You are JARVIS. Answer in one sentence. Use tools if needed."},
                {"role": "user", "content": query}
            ]
            
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "tools": self.tools
            }
            
            try:
                response = requests.post(self.ollama_url, json=payload, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    message = data.get('message', {})
                    
                    # Handle Tool Calls (MCP-style)
                    if message.get('tool_calls'):
                        for tool in message['tool_calls']:
                            name = tool['function']['name']
                            args = tool['function']['arguments']
                            log_event(f"MCP Tool Call: {name} with {args}")
                            
                            if name == "get_time":
                                self.ai_result = f"The time is {datetime.datetime.now().strftime('%H:%M')}."
                            elif name == "open_website":
                                webbrowser.open_new_tab(args['url'])
                                self.ai_result = f"I've opened {args['url']} for you."
                    else:
                        self.ai_result = message.get('content', '')
            except Exception as e:
                log_event(f"AI Worker Error: {e}", "error")
            self.ai_completed = True

        thread = threading.Thread(target=ai_worker)
        thread.daemon = True
        thread.start()

        while not self.ai_completed:
            interrupt = takeCommand(timeout=0.1, phrase_limit=1.0)
            if any(word in interrupt for word in ["stop", "cancel"]):
                self.aborted = True
                speak("Stopped.")
                return

        if self.ai_result and not self.aborted:
            save_chat_to_db('assistant', self.ai_result)
            speak(self.ai_result)

def main():
    bot = Jarvis()
    bot.wishMe()
    while True:
        query = takeCommand()
        if query != 'none':
            bot.execute_query(query)

if __name__ == '__main__':
    main()
