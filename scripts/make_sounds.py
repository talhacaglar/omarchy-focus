#!/usr/bin/env python3
"""Generate the chimes in src/omarchy_focus/sounds/.

They go off while someone is concentrating, so they are built not to startle:
each note fades in over 40 ms instead of striking, holds little above its
fundamental, stays below 700 Hz and peaks around -10 dBFS. Nothing here is
sampled; the notes are a few decaying sine partials.

    python scripts/make_sounds.py        # needs ffmpeg for the Ogg encoding
"""

from __future__ import annotations

import math
import struct
import subprocess
import tempfile
import wave
from pathlib import Path

RATE = 48000
OUT = Path(__file__).resolve().parents[1] / "src" / "omarchy_focus" / "sounds"

# (partial of the fundamental, level, how much faster it dies away)
PARTIALS = ((1.0, 1.0, 1.0), (1.003, 0.35, 1.0), (2.0, 0.22, 2.2), (3.0, 0.06, 3.5))
ATTACK = 0.04

# name -> (peak level, decay in seconds, [(start in seconds, Hz), ...])
CHIMES = {
    # G4, C5, E5: a major chord opening upward. "Done; well done."
    "session-end": (0.32, 0.95, [(0.0, 392.00), (0.30, 523.25), (0.60, 659.26)]),
    # A4, D5: two notes, quieter. "Back when you're ready."
    "break-end": (0.24, 0.80, [(0.0, 440.00), (0.32, 587.33)]),
}


def note(frequency: float, decay: float, length: float) -> list[float]:
    samples = []
    for index in range(int(length * RATE)):
        t = index / RATE
        rise = 0.5 - 0.5 * math.cos(math.pi * min(1.0, t / ATTACK))
        value = sum(
            level * math.exp(-t * speed / decay) * math.sin(2 * math.pi * frequency * ratio * t)
            for ratio, level, speed in PARTIALS
        )
        samples.append(rise * value)
    return samples


def render(peak: float, decay: float, notes: list[tuple[float, float]]) -> list[float]:
    length = max(start for start, _ in notes) + decay * 4.5
    mix = [0.0] * int(length * RATE)
    for start, frequency in notes:
        offset = int(start * RATE)
        for index, value in enumerate(note(frequency, decay, length - start)):
            mix[offset + index] += value
    fade = int(0.25 * RATE)
    for index in range(fade):
        mix[-1 - index] *= index / fade
    loudest = max(abs(value) for value in mix)
    return [value * peak / loudest for value in mix]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (peak, decay, notes) in CHIMES.items():
        frames = b"".join(
            struct.pack("<hh", s, s) for s in (round(v * 32767) for v in render(peak, decay, notes))
        )
        with tempfile.NamedTemporaryFile(suffix=".wav") as raw:
            with wave.open(raw.name, "wb") as handle:
                handle.setnchannels(2)
                handle.setsampwidth(2)
                handle.setframerate(RATE)
                handle.writeframes(frames)
            target = OUT / f"{name}.oga"
            subprocess.run(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    raw.name,
                    "-c:a",
                    "libvorbis",
                    "-q:a",
                    "4",
                    "-map_metadata",
                    "-1",
                    "-fflags",
                    "+bitexact",
                    "-flags:a",
                    "+bitexact",
                    str(target),
                ],
                check=True,
            )
            print(
                f"{target.relative_to(OUT.parents[2])}: {len(frames) / 4 / RATE:.1f} s, {target.stat().st_size} bytes"
            )


if __name__ == "__main__":
    main()
