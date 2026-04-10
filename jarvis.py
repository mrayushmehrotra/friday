import datetime
import sys
import webbrowser
from helpers import speak, takeCommand

class Jarvis:
    def __init__(self) -> None:
        pass

    def wishMe(self) -> None:
        hour = int(datetime.datetime.now().hour)
        if 0 <= hour < 12:
            speak("Good Morning SIR")
        elif 12 <= hour < 18:
            speak("Good Afternoon SIR")
        else:
            speak('Good Evening SIR')
        speak('I am JARVIS. How can I help you?')

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

        elif 'who are you' in query:
            speak('I am JARVIS, your basic voice-controlled assistant.')

        elif 'search' in query:
            speak('What should I search for?')
            search = takeCommand()
            if search != 'none':
                url = 'https://google.com/search?q=' + search
                webbrowser.open_new_tab(url)
                speak(f'Searching for {search}')

        elif 'sleep' in query or 'stop' in query:
            speak('Goodbye SIR')
            sys.exit()

def main():
    bot = Jarvis()
    bot.wishMe()
    while True:
        query = takeCommand()
        if query != 'none':
            bot.execute_query(query)

if __name__ == '__main__':
    main()
