import sounddevice as sd
import numpy as np

# Play a 1-second tone
fs = 44100
t = np.linspace(0, 1, fs)
tone = 0.3 * np.sin(2 * np.pi * 440 * t)
sd.play(tone, samplerate=fs)
sd.wait()
print("done playing")