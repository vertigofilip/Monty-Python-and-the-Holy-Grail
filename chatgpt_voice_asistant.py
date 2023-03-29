import openai
import pyttsx3
import speech_recognition as sr
import time
import env

# Set your OpenAI API key
openai.api_key = env.OPEN_AI_KEY

# Initialize the text-to-speach engine
engine = pyttsx3.init()

def trancribe_audio_to_text(filname):
    recognizer=sr.Recognizer()
    with sr.AudioFile(filname) as source:
        audio=recognizer.record(source)
    try:
        return recognizer.recognize_google(audio)
    except:
        print('Skipping unknown error')

def generate_response(prompt):
    responce=openai.Completion.create(
        engine='text-davinci-003',
        prompt=prompt,
        max_tokens=4000,
        n=1,
        stop=None,
        temperature=0.5
    )
    return responce['choices'][0]['text']

def speak_text(text):
    engine.say(text)
    engine.runAndWait()

def main():
    while True:
        # Wait for user to say "chat"
        print('say "chat" to start secording your question...')
        with sr.Microphone() as source:
            recognizer=sr.Recognizer()
            audio=recognizer.listen(source)
            try:
                transcription=recognizer.recognize_google(audio)
                if transcription.lower() == 'chat':
                    # Record audio
                    filename='input.wav'
                    print('Ask a question...')
                    with sr.Microphone() as source:
                        recognizer=sr.Recognizer()
                        source.pause_threshold=1
                        audio=recognizer.listen(source, phrase_time_limit=None, timeout=None)
                        with open(filename, 'wb') as f:
                            f.write(audio.get_wav_data())
                
                    # Transcribe audio to text
                    text=trancribe_audio_to_text(filename)
                    if text:
                        print(f'you said: {text}')

                        # Generate response using GPT-3
                        response = generate_response(text)
                        print(f'GPT-3 says: {response}')

                        # Readresponse using text-to-speach
                        speak_text(response)
            except Exception as e:
                print('an error ocured: {}'.format(e))

if __name__=="__main__":
    main()