import numpy as np
import sounddevice as sd
import time
import copy

def main():
    sound1 = [sawtooth_tone(frequency= 220 * i, amplitude= 0.7 / i,) for i in range(1, 40, 4)]
    sound2 = [sine_tone(frequency= 220 * i, amplitude= 0.7 / i,) for i in range(1, 40, 4)]
    carier = [sine_tone(frequency= 2 , amplitude= 0.7) for i in range(1, 40, 4)]
    mysound1 = [am_synthesis(sound1[i], carier[i]) for i in range(len(sound1))]
    mysound2 = [am_synthesis(sound2[i], carier[i]) for i in range(len(sound1))]
    mysound1 = sum(mysound1)
    mysound2 = sum(mysound2)
    mysound = (mysound1 + mysound2)/2
    mysound = aply_envelope(mysound, [0.5, 0.2, 0.6, 0.5])

    trainin_element("Pajacyki", 40, mysound, mysound)

    trainin_element("Otwarcie klatki piersiowej lewa strona", 20, mysound, mysound)

    trainin_element("Otwarcie klatki piersiowej prawa strona", 20, mysound, mysound)

    trainin_element("Pąpki zregresowane", 40, mysound, mysound)

    trainin_element("Przysiady", 40, mysound, mysound)

    trainin_element("Pąpki zregresowane", 40, mysound, mysound)

    trainin_element("Przysiady", 40, mysound, mysound)

    trainin_element("Podpór bokiem lewa strona", 20, mysound, mysound)

    trainin_element("Podpór bokiem prawa strona", 20, mysound, mysound)

    trainin_element("Pies", 40, mysound, mysound)

    trainin_element("Podpór tyłem", 40, mysound, mysound)

    trainin_element("Podpór bokiem lewa strona", 20, mysound, mysound)

    trainin_element("Podpór bokiem prawa strona", 20, mysound, mysound)

    trainin_element("Pies", 40, mysound, mysound)

    trainin_element("Podpór tyłem", 40, mysound, mysound)

    trainin_element("Hollow body", 20, mysound, mysound)

    trainin_element("Podnoszenie nóg", 20, mysound, mysound)

    trainin_element("Pozycja Y", 20, mysound, mysound)

    trainin_element("Hollow body", 20, mysound, mysound)

    trainin_element("Podnoszenie nóg", 20, mysound, mysound)

    trainin_element("Pozycja Y", 20, mysound, mysound)

def trainin_element(training_name, training_time, beginning_sound, ending_sound):
    print(training_name)

    input("Naciśnij Enter...")

    print("Przygotuj się")

    time.sleep(2)

    print("Ćwicz")

    sd.play(beginning_sound)
    #sd.wait()

    time.sleep(training_time)

    sd.play(ending_sound)
    sd.wait()

    print("koniec")

def sawtooth_tone(
    frequency: int = 440,
    duration: float = 1.0,
    amplitude: float = 0.5,
    sample_rate: int = 44100
    ) -> np.ndarray:
    n_samples = int(sample_rate * duration)
    time_points = np.linspace(0, duration, n_samples, False)
    phase = frequency * time_points
    sawtooth = 2 * (phase - np.floor(phase + 0.5))
    sawtooth *= amplitude
    return sawtooth

def sine_tone(
    frequency: int = 440,
    duration: float = 1.0,
    amplitude: float = 0.5,
    sample_rate: int = 44100
    ) -> np.ndarray:
    n_samples = int(sample_rate * duration)
    time_points = np.linspace(0, duration, n_samples, False)
    sine = np.sin(2 * np.pi * frequency * time_points)
    sine *= amplitude
    return sine

def am_synthesis(
    carrier_wave: np.ndarray,
    modulator_wave: np.ndarray,
    modulation_index: float = 0.5,
    amplitude: float = 0.5
    ) -> np.ndarray:
    n_samples = min(len(carrier_wave), len(modulator_wave))
    carrier_wave = carrier_wave[:n_samples]
    modulator_wave = modulator_wave[:n_samples]

    am_wave = (1 + modulation_index * modulator_wave) * carrier_wave
    max_amplitude = np.max(np.abs(am_wave))
    am_wave = amplitude * (am_wave / max_amplitude)
    return am_wave

def aply_envelope(sound: np.array, adsr:list, sample_rete: int=44100) -> np.array:
    sound = sound.copy()
    attack_samples = int(adsr[0] * sample_rete)
    decay_samples = int(adsr[1] * sample_rete)
    release_samples = int(adsr[3] * sample_rete)
    sustain_samples = len(sound) - (attack_samples + decay_samples + release_samples)
    sound[:attack_samples] *= np.linspace(0, 1, attack_samples)
    sound[attack_samples:attack_samples + decay_samples] *= np.linspace(1, adsr[2], decay_samples)
    sound[attack_samples + decay_samples:attack_samples + decay_samples + sustain_samples] *= adsr[2]
    sound[attack_samples + decay_samples + sustain_samples:] *= np.linspace(adsr[2], 0, release_samples)
    return sound

if __name__ == "__main__":
    main()