import speech_recognition as sr
import pyttsx3
import openai
import os
import time

openai.api_key = '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'

engine = pyttsx3.init()

def trancribe_audio_to_text(filname):
    recogniser=sr.Recognizer()
    with sr.AudioFile(filname) as source:
        audio=recogniser.record(source)
        try:
            return recogniser.recognize_google(audio)
        except:
            print('Skipping unknown error')

def generate_response(prompt):
    responce=openai.Completion.create(
        engine='text-davinci-003',
        prompt=prompt,
        max_tokens=4000,
        n=1,
        stop=None,
        tempreture=0.5,
    )
    return responce['choices'][0]['text']

def speak_text(text):
    engine.say(text)
    engine.runAndWait()

def main():
    while True:
        print('say "chat" to start secording your question...')
        with sr.Microphone() as source:
            recogniser=sr.Recognizer()
            audio=recogniser.listen(source)
            try:
                transcription=recogniser.recognize_google()
                if transcription.lower() == 'chat':
                    filename='input.wav'
                    recogniser=sr.Recognizer()
                    source.pause_threshold=1
                    audio=recogniser.listen(source, phrase_time_limit=None, timeout=None)
                    with open(filename, 'wb') as f:
                        f.write(audio.get_wav_data())
                    text=trancribe_audio_to_text(filename)
                    if text:
                        print(f'you said: {text}')
                        response = generate_response(text)
                        print(f'GPT-3 says: {response}')
                        speak_text(response)
            except Exception as e:
                print('an error ocured: {}'.format(e))

if __name__=="__main__":
    main()