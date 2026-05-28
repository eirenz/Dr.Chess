"""
Programmatic sound generation for Chess Overlay alerts.
Generates simple sine-wave WAV tones at startup — no external audio files needed.
"""

import wave
import struct
import math
import os
import tempfile

_SAMPLE_RATE = 44100
_sounds_dir = None
_blunder_path = None
_brilliant_path = None


def _get_sounds_dir():
    global _sounds_dir
    if _sounds_dir is None:
        _sounds_dir = os.path.join(tempfile.gettempdir(), "chess_overlay_sounds")
        os.makedirs(_sounds_dir, exist_ok=True)
    return _sounds_dir


def generate_tone_wav(filepath: str, frequencies: list[tuple[float, float]], volume: float = 0.5):
    """
    Generate a WAV file with one or more frequency segments.
    
    Args:
        filepath: Output WAV path.
        frequencies: List of (frequency_hz, duration_seconds) tuples.
        volume: 0.0 to 1.0.
    """
    samples = []
    for freq, duration in frequencies:
        n_samples = int(_SAMPLE_RATE * duration)
        for i in range(n_samples):
            t = i / _SAMPLE_RATE
            # Apply envelope (fade in/out) to avoid clicks
            env = 1.0
            fade_samples = int(_SAMPLE_RATE * 0.01)  # 10ms fade
            if i < fade_samples:
                env = i / fade_samples
            elif i > n_samples - fade_samples:
                env = (n_samples - i) / fade_samples
            
            val = volume * env * math.sin(2.0 * math.pi * freq * t)
            samples.append(val)
    
    # Normalize to 16-bit
    max_val = max(abs(s) for s in samples) if samples else 1.0
    if max_val == 0:
        max_val = 1.0
    
    with wave.open(filepath, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_SAMPLE_RATE)
        for s in samples:
            normalized = int((s / max_val) * 32767 * volume)
            wf.writeframes(struct.pack('<h', max(-32768, min(32767, normalized))))


def init_sounds():
    """Generate alert WAV files. Call once at startup."""
    global _blunder_path, _brilliant_path
    
    sounds_dir = _get_sounds_dir()
    
    # Blunder: descending two-tone alert (E5 → C4)
    _blunder_path = os.path.join(sounds_dir, "blunder.wav")
    if not os.path.exists(_blunder_path):
        generate_tone_wav(_blunder_path, [
            (659.25, 0.12),   # E5
            (523.25, 0.12),   # C5
            (261.63, 0.18),   # C4 (lower, ominous)
        ], volume=0.4)
    
    # Brilliant: ascending two-tone chime (C5 → E5 → G5)
    _brilliant_path = os.path.join(sounds_dir, "brilliant.wav")
    if not os.path.exists(_brilliant_path):
        generate_tone_wav(_brilliant_path, [
            (523.25, 0.10),   # C5
            (659.25, 0.10),   # E5
            (783.99, 0.15),   # G5 (bright, triumphant)
        ], volume=0.35)
    
    print(f"Sound alerts initialized in {sounds_dir}")


def get_blunder_path() -> str | None:
    return _blunder_path


def get_brilliant_path() -> str | None:
    return _brilliant_path
