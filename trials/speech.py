import speech_recognition as sr

def get_voice_input(prompt="🎤 Please speak your query: ") -> str:
  recognizer = sr.Recognizer()
  mic = sr.Microphone()
  print(prompt)
  with mic as source:
    recognizer.adjust_for_ambient_noise(source)
    audio = recognizer.listen(source)
  try:
    query = recognizer.recognize_google(audio)
    print(f"You said: {query}")
    return query
  except sr.UnknownValueError:
    print("Could not understand audio")
    return ""
  except sr.RequestError as e:
    print(f"Could not request results; {e}")
    return ""
  
def main():
  get_voice_input()

if __name__ == '__main__':
  main()