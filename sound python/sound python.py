import numpy as np
import sounddevice as sd

def main():
    #mysound = sine_tone(frequency=300, duration=2)
    #mysound = aply_envelope(mysound, [0.5, 0.2, 0.6, 0.5])
    
    #sines = [sine_tone(frequency= 200 * i, amplitude= 0.7 / i,) for i in range(1, 31, 2)]
    #mysound = sum(sines)

    #mysound = white_noise()

    #mymodulator = square_tone(100, 3)

    #mysound = fm_synthesis(220, mymodulator, modulation_index=6)

    #carrier = sine_tone(frequency=440, duration=2)
    #modulator = sine_tone(frequency=200, duration=2)
    #mysound = fm_synthesis(carrier, modulator)

    sound1 = [sawtooth_tone(frequency= 220 * i, amplitude= 0.7 / i,) for i in range(1, 40, 4)]
    sound2 = [sine_tone(frequency= 220 * i, amplitude= 0.7 / i,) for i in range(1, 40, 4)]
    carier = [sine_tone(frequency= 2 , amplitude= 0.7) for i in range(1, 40, 4)]
    mysound1 = [am_synthesis(sound1[i], carier[i]) for i in range(len(sound1))]
    mysound2 = [am_synthesis(sound2[i], carier[i]) for i in range(len(sound1))]
    mysound1 = sum(mysound1)
    mysound2 = sum(mysound2)
    mysound = (mysound1 + mysound2)/2
    mysound = aply_envelope(mysound, [0.5, 0.2, 0.6, 0.5])

    sd.play(mysound)
    sd.wait()

def fm_synthesis_sine(
    carrier_frequency: float,
    modulator_wave: np.array,
    modulation_index: float=3,
    amplitude: float=0.5,
    sample_rate: int=44100
    )-> np.ndarray:
    total_samples = len(modulator_wave)
    time_points = np.arange(total_samples) / sample_rate
    fm_wave = np.sin(2 * np.pi * carrier_frequency * time_points + modulation_index * modulator_wave)
    max_amplitude = np.max(np.abs(fm_wave))
    fm_wave = amplitude * (fm_wave / max_amplitude)
    return fm_wave


def am_synthesis_sine(
    carrier_frequency: float,
    modulator_wave: np.array,
    modulation_index: float=0.5,
    amplitude: float=0.5,
    sample_rate: int=44100
    )-> np.ndarray:
    total_samples = len(modulator_wave)
    time_points = np.arange(total_samples) / sample_rate
    carrier_wave = np.sin(2 * np.pi * carrier_frequency * time_points)
    am_wave = (1 + modulation_index * modulator_wave) * carrier_wave
    max_amplitude = np.max(np.abs(am_wave))
    am_wave = amplitude * (am_wave / max_amplitude)
    return am_wave

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

def fm_synthesis(
    carrier_frequency: np.ndarray,
    modulator_wave: np.ndarray,
    modulation_index: float = 3,
    amplitude: float = 0.5,
    sample_rate: int = 44100
    ) -> np.ndarray:
    n_samples = min(len(carrier_frequency), len(modulator_wave))
    carrier_frequency = carrier_frequency[:n_samples]
    modulator_wave = modulator_wave[:n_samples]

    # instantaneous phase = integral of instantaneous frequency
    phase = 2 * np.pi * np.cumsum(carrier_frequency) / sample_rate
    fm_wave = np.sin(phase + modulation_index * modulator_wave)

    max_amplitude = np.max(np.abs(fm_wave))
    fm_wave = amplitude * (fm_wave / max_amplitude)
    return fm_wave

def ring_modulation(
    carrier_wave: np.ndarray,
    modulator_wave: np.ndarray,
    amplitude: float = 0.5
    ) -> np.ndarray:
    n_samples = min(len(carrier_wave), len(modulator_wave))
    result = carrier_wave[:n_samples] * modulator_wave[:n_samples]
    max_amplitude = np.max(np.abs(result))
    result = amplitude * (result / max_amplitude)
    return result

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

def square_tone(
    frequency: int = 440,
    duration: float = 1.0,
    amplitude: float = 0.5,
    sample_rate: int = 44100
    ) -> np.ndarray:
    n_samples = int(sample_rate * duration)
    time_points = np.linspace(0, duration, n_samples, False)
    square = np.sign(np.sin(2 * np.pi * frequency * time_points))
    square *= amplitude
    return square

def white_noise(
    duration: float = 1.0,
    amplitude: float = 0.5,
    sample_rate: int = 44100
    ) -> np.ndarray:
    n_samples = int(duration * sample_rate)
    noise = np.random.uniform(-1, 1, n_samples)
    noise *= amplitude
    return noise




if __name__ == "__main__":
    main()