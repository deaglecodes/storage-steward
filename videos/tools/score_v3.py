"""Score v3 for the minimal storage-steward film: 120 BPM, 16 bars = 32.0 s, E minor, synthesized from scratch.

    uv run --exclude-newer 2026-09-30 --with numpy --with scipy python3 tools/score_v3.py

  1-2   leftovers land: ticks that thicken with the flood, a low swell          (the mess)
  3     soft kick and a woody tap on every word                                (Your agents leave files behind.)
  4     the sweep: one breath of noise that pans left to right with the line   (the page clears)
  5     a low thump, a tap per letter, a bell when the dot lands                (Less.)
  6-14  a quiet pulse: kick on 1 and 3, off-beat hats, a sparse pluck line;
        typing ticks on the exact characters, a short sweep at every scene change
  15-16 the pad opens, a last bell, ring out                                    (end card)
Every cue mirrors src/videos/launch3/cues.ts. The whole mix is one file: no separate SFX.
"""
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
N = int(round(16 * BAR * SR))
rng = np.random.default_rng(3)
OUT = Path(__file__).resolve().parents[1] / "public/audio/launch3/music/launch3.wav"

hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
b = lambda bar, beat=1, frac=0.0: (bar - 1) * BAR + (beat - 1 + frac) * BEAT

# cues.ts, mirrored
WIPE = 0.75
TYPED = [(b(7, 2), 0.016, 89), (b(11, 2), 0.03, 28), (b(11, 4), 0.018, 39)]
SESSIONS = [b(9, 2) + k * 0.45 for k in range(6)]
BG_SWEEPS = [SESSIONS[k] + 0.32 + 0.04 for k in (1, 3, 5)]
CHORDS = {1: (52, 55, 59), 5: (52, 55, 59), 7: (48, 52, 55), 9: (55, 59, 62), 11: (50, 54, 57), 13: (48, 52, 55), 15: (52, 55, 59)}


def chord_at(bar):
    return CHORDS[max(k for k in CHORDS if k <= bar)]


def sos(kind, f, order=2):
    return butter(order, f, kind, fs=SR, output="sos")


def lp(x, f):
    return sosfilt(sos("low", min(f, SR / 2 - 200)), x)


def hp(x, f, order=2):
    return sosfilt(sos("high", f, order), x)


def bp(x, lo, hi):
    return sosfilt(sos("band", [lo, hi]), x)


def env(n, decay, attack=0.002):
    t = np.arange(n) / SR
    return np.clip(t / attack, 0, 1) * np.exp(-t * decay)


def place(buf, sig, at, gain=1.0, pan=0.0):
    i = int(round(at * SR))
    if i >= N or i < 0:
        return
    sig = sig[: N - i] * gain
    left, right = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * left * 1.414
    buf[i:i + len(sig), 1] += sig * right * 1.414


# ---------------------------------------------------------------- instruments, all soft
def kick():
    n = int(0.36 * SR)
    t = np.arange(n) / SR
    f = 46 + 90 * np.exp(-t * 30)
    return np.tanh(1.3 * np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 8))


def hat():
    n = int(0.05 * SR)
    return hp(rng.standard_normal(n), 8000, 3) * env(n, 80)


def tick():
    n = int(0.018 * SR)
    return hp(rng.standard_normal(n), 3500) * env(n, 260)


def tap():                                   # woody, for words and letters
    n = int(0.12 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 820 * t) + 0.4 * np.sin(2 * np.pi * 1640 * t)) * env(n, 45)


def pluck(m, length=0.4):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = hz(m)
    x = np.sin(2 * np.pi * f * t) + 0.3 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 12)
    return x * env(n, 7)


def bell(m, length=2.2):
    n = int(length * SR)
    t = np.arange(n) / SR
    f = hz(m)
    parts = [(1, 1.0, 1.6), (2.76, 0.4, 3.2), (5.4, 0.18, 6.0), (2.0, 0.25, 2.2)]
    return sum(a * np.sin(2 * np.pi * f * r * t) * np.exp(-t * d) for r, a, d in parts) * np.clip(t / 0.003, 0, 1)


def pad(chord, length, cutoff):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = sum(np.sin(2 * np.pi * hz(m - 12) * (1 + d) * t + rng.random() * 6.28) for m in chord for d in (-0.002, 0.0, 0.0021))
    return lp(x / 9, cutoff) * np.clip(t / 0.5, 0, 1) * np.clip((length - t) / 0.4, 0, 1)


def thump(length=1.0, f0=62):
    n = int(length * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(f0 * np.exp(-t * 2.2) + 22) / SR) * np.exp(-t * 3.2)


def breath(length):                           # filtered noise whose band rises; the sweep line's sound
    n = int(length * SR)
    x = rng.standard_normal(n)
    out = np.zeros(n)
    steps = 24
    seg = n // steps
    for k in range(steps):
        a, z = k * seg, (k + 1) * seg if k < steps - 1 else n
        lo = 300 + 2400 * k / steps
        out[a:z] = bp(x[a:z], lo, lo * 2.2)
    shape = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    return out * shape


def place_sweep(buf, at, length, gain):
    """A breath panned left to right across `length`, like the line."""
    sig = breath(length) * gain
    i = int(round(at * SR))
    n = min(len(sig), N - i)
    pan = np.linspace(-0.9, 0.9, n)
    buf[i:i + n, 0] += sig[:n] * np.cos((pan + 1) * np.pi / 4) * 1.414
    buf[i:i + n, 1] += sig[:n] * np.sin((pan + 1) * np.pi / 4) * 1.414


def sidechain(kicks, depth=0.35, rel=9):
    g = np.ones(N)
    for k in kicks:
        i = int(k * SR)
        m = min(int(0.3 * SR), N - i)
        if m > 0:
            g[i:i + m] = np.minimum(g[i:i + m], 1 - depth * np.exp(-np.arange(m) / SR * rel))
    return g


# ---------------------------------------------------------------- arrangement
def main():
    drums, bus, fx = np.zeros((N, 2)), np.zeros((N, 2)), np.zeros((N, 2))
    kicks = []

    # 1-2: the flood. Ticks follow the film's landing curve (from + span * u^0.55), so they thicken toward bar 3.
    for u in rng.random(120):
        place(fx, tick(), 0.25 + (b(3) - 0.4) * u ** 0.75, 0.05 + 0.04 * rng.random(), rng.uniform(-0.8, 0.8))
    place(bus, pad(chord_at(1), 2 * BAR + 0.4, 700), 0.0, 0.5)
    place(bus, pad(chord_at(3), BAR * 2 + 0.3, 1200), b(3), 0.45)

    # 3: the words
    for at in (b(3, 1), b(3, 2), b(3, 3), b(3, 4), b(3, 4, 0.5)):
        place(drums, tap(), at, 0.35, 0.1)
    for beat in range(1, 5):
        kicks.append(b(3, beat))

    # 4: the sweep across the whole bar
    place_sweep(fx, b(4), BAR, 0.28)

    # 5: Less.
    place(fx, thump(1.4, 58), b(5), 0.75)
    for i in range(4):
        place(drums, tap(), b(5, 1, i * 0.25), 0.22, -0.2 + 0.13 * i)
    place(fx, bell(88, 2.4), b(5, 3), 0.22, 0.15)
    place(fx, bell(76, 2.4), b(5, 3), 0.12, -0.1)

    # 6-14: the quiet pulse
    motif = [(0.0, 2), (1.5, 1), (2.0, 0), (3.0, 1)]          # (beat offset, chord tone)
    for bar in range(6, 15):
        chord = chord_at(bar)
        kicks += [b(bar, 1), b(bar, 3)]
        for beat in range(1, 5):
            place(drums, hat(), b(bar, beat, 0.5), 0.05, 0.3)
        for off, idx in motif:
            place(bus, pluck(chord[idx] + 12), b(bar, 1, off), 0.16, -0.25 if idx % 2 else 0.25)
        if bar % 2 == 1 or bar == 6:
            place(bus, pad(chord, 2 * BAR + 0.3, 900), b(bar), 0.32)
    for k in kicks:
        place(drums, kick(), k, 0.55)

    # scene changes: a short breath ending on each bar line
    for bar in (7, 9, 11, 13, 15):
        place_sweep(fx, b(bar) - WIPE, WIPE, 0.16)
    # typing: one tick per character, exactly where the film types
    for at, per, count in TYPED:
        for i in range(count):
            place(fx, tick(), at + i * per, 0.035, 0.2)
    # forget: a soft note per session, a small breath per background sweep
    for k, s in enumerate(SESSIONS):
        place(bus, pluck((64, 67, 71, 74, 76, 79)[k], 0.5), s, 0.14, -0.4 + 0.16 * k)
    for at in BG_SWEEPS:
        place_sweep(fx, at, 0.34, 0.09)
    # confirmations and captions
    for at in (b(8, 1), b(12, 2)):
        place(fx, bell(83, 1.2), at, 0.08, 0.2)
    # proof: one low thump and a bell per number
    for at, m in ((b(13, 1), 76), (b(13, 3), 79), (b(14, 1), 83)):
        place(fx, thump(0.8, 66), at, 0.5)
        place(fx, bell(m, 1.6), at, 0.1)

    # 15-16: the end card
    place(bus, pad((52, 55, 59, 66), 2 * BAR + 0.5, 1600), b(15), 0.5)
    place(fx, thump(1.6, 55), b(15), 0.6)
    place(fx, bell(76, 3.0), b(15), 0.18)
    place(fx, bell(83, 3.0), b(16), 0.12, 0.2)

    music = drums + bus * sidechain(kicks)[:, None] + fx
    fade = int(1.6 * SR)
    music[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    music = np.tanh(1.1 * music) / np.tanh(1.1)
    music *= 10 ** (-1.5 / 20) / np.max(np.abs(music))
    write(OUT, music)
    print(f"score v3: {N / SR:.2f} s, 16 bars at {BPM} BPM -> {OUT.relative_to(OUT.parents[3])}")


def write(path, stereo):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main()
