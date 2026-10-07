"""Original score for the storage-steward launch film, synthesized from scratch (royalty-free).

    uv run --exclude-newer 2026-09-30 --with numpy --with scipy python3 tools/synth.py

120 BPM, 4/4, 20 bars = 40.0 s, downbeat at 0, so the film's grid is exact:
  1-2   intro: pad + filtered pluck arp opening up        (logo draws)
  3-6   kick + bass + clap groove                          (punchline 1, disk filling)
  7     breakdown: pad + plucks only                       (punchline 2)
  8-11  groove returns, riser through bar 11               (terminal: scan, sweep)
  12-17 drop: full groove, open hats, impact on bar 12     (flat line, punchline 3, proof)
  18-19 thinning out                                       (logo lockup)
  20    ring-out                                           (end card)
Also writes short SFX (tick, whoosh, ping, impact) for cue-placed effects.
"""
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT
BARS = 20
N = int(BARS * BAR * SR)
rng = np.random.default_rng(7)
OUT = Path(__file__).resolve().parents[1] / "public/audio/launch"

# A minor: Am - F - C - G, one chord per bar
CHORDS = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]
ROOTS = [45, 41, 48, 43]
hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)


def lp(x, f, order=2):
    return sosfilt(butter(order, min(f, SR / 2 - 100), "low", fs=SR, output="sos"), x)


def hp(x, f, order=2):
    return sosfilt(butter(order, f, "high", fs=SR, output="sos"), x)


def bp(x, lo, hi):
    return sosfilt(butter(2, [lo, hi], "band", fs=SR, output="sos"), x)


def env(n, decay, attack=0.002):
    t = np.arange(n) / SR
    a = np.clip(t / attack, 0, 1)
    return a * np.exp(-t * decay)


def saw(f, n, phase=0.0):
    t = np.arange(n) / SR
    return 2 * ((t * f + phase) % 1.0) - 1


def place(buf, sig, at, gain=1.0, pan=0.0):
    i = int(round(at * SR))
    if i >= N:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * l * 1.414
    buf[i:i + len(sig), 1] += sig * r * 1.414


def kick():
    n = int(0.45 * SR)
    t = np.arange(n) / SR
    f = 46 + 120 * np.exp(-t * 30)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7.5)
    click = hp(rng.standard_normal(n), 2000) * env(n, 400) * 0.25
    return np.tanh(1.6 * (body + click))


def clap():
    n = int(0.3 * SR)
    noise = bp(rng.standard_normal(n), 900, 4200)
    e = sum(np.roll(env(n, 70), int(d * SR)) for d in (0, 0.011, 0.022)) + env(n, 14) * 0.6
    return noise * e * 0.5


def hat(open_=False):
    n = int((0.28 if open_ else 0.07) * SR)
    return hp(rng.standard_normal(n), 7500, 3) * env(n, 11 if open_ else 65)


def pluck(m, cutoff, length=0.22):
    n = int(length * SR)
    f = hz(m)
    x = 0.6 * saw(f, n) + 0.4 * np.sign(np.sin(2 * np.pi * f * np.arange(n) / SR))
    return lp(x, cutoff) * env(n, 16)


def pad(chord, length):
    n = int(length * SR)
    x = np.zeros(n)
    for m in chord:
        for d in (-0.09, 0.0, 0.08):
            x += saw(hz(m - 12) * 2 ** (d / 12), n, rng.random())
    t = np.arange(n) / SR
    shape = np.clip(t / 0.35, 0, 1) * np.clip((length - t) / 0.25, 0, 1)
    return lp(x / 9, 1400) * shape


def sidechain(n_total, kicks):
    g = np.ones(n_total)
    for k in kicks:
        i = int(k * SR)
        m = min(int(0.35 * SR), n_total - i)
        if m > 0:
            g[i:i + m] = np.minimum(g[i:i + m], 1 - 0.75 * np.exp(-np.arange(m) / SR * 11))
    return g


def main():
    mix = np.zeros((N, 2))
    music_bus = np.zeros((N, 2))      # sidechained elements
    b = lambda bar, beat=1, frac=0.0: (bar - 1) * BAR + (beat - 1 + frac) * BEAT

    groove = set(range(3, 7)) | set(range(8, 12)) | set(range(12, 18)) | {18}
    clap_bars = set(range(4, 7)) | set(range(9, 12)) | set(range(12, 18))
    kicks = []
    for bar in range(1, BARS + 1):
        chord, root = CHORDS[(bar - 1) % 4], ROOTS[(bar - 1) % 4]
        if bar in groove:
            for beat in range(1, 5):
                kicks.append(b(bar, beat))
                place(mix, kick(), b(bar, beat), 0.95)
        if bar in clap_bars:
            for beat in (2, 4):
                place(mix, clap(), b(bar, beat), 0.42, 0.05)
        if bar >= 2 and bar not in (7, 19, 20):
            for e in range(8):
                place(mix, hat(), b(bar, 1, e / 2), 0.10 if e % 2 else 0.06, 0.25)
        if 12 <= bar <= 17:
            for beat in range(1, 5):
                place(mix, hat(True), b(bar, beat, 0.5), 0.07, -0.25)
        # bass: offbeat 8ths in the groove, octave lift on the drop
        if bar in groove or bar == 7:
            for e in range(8):
                if bar == 7 and e % 2 == 0:
                    continue
                n = int(BEAT / 2 * SR * 0.92)
                m = root + (12 if bar >= 12 and e in (3, 7) else 0)
                note = lp(saw(hz(m), n), 420 if bar < 12 else 650) * env(n, 6, 0.004)
                place(music_bus, note, b(bar, 1, e / 2), 0.55)
        # pad every bar, swelling in on the intro and ringing out at the end
        length = BAR + (1.6 if bar == BARS else 0.3)
        place(music_bus, pad(chord, length), b(bar), 0.55 if bar not in (1, 2) else 0.4 + 0.1 * bar)
        # 16th pluck arp, filter opens over the intro
        if bar <= 19:
            pattern = [0, 1, 2, 1, 2, 0, 2, 1, 0, 2, 1, 2, 1, 0, 2, 1]
            cutoff = 900 + 3200 * min(1.0, (bar - 1 + 0.5) / 3) + (1500 if 12 <= bar <= 17 else 0)
            for s, idx in enumerate(pattern):
                if bar == 7 and s % 2:
                    continue
                m = chord[idx] + (12 if s % 8 >= 4 else 0)
                place(music_bus, pluck(m, cutoff), b(bar, 1, s / 4), 0.16, -0.35 if s % 2 else 0.35)
    # riser through bar 11 into the drop, impact + crash on bar 12
    n = int(BAR * SR)
    t = np.arange(n) / SR
    riser = hp(rng.standard_normal(n), 800) * (t / BAR) ** 2.2
    place(mix, riser, b(11), 0.22)
    m = int(1.6 * SR)
    tt = np.arange(m) / SR
    sub = np.sin(2 * np.pi * np.cumsum(60 * np.exp(-tt * 1.4) + 28) / SR) * np.exp(-tt * 2.2)
    place(mix, sub, b(12), 0.7)
    place(mix, hp(rng.standard_normal(int(2.5 * SR)), 3000) * env(int(2.5 * SR), 2.2), b(12), 0.16)
    # simple stereo delay on the music bus (dotted eighth), then sidechain it to the kicks
    d = int(0.75 * BEAT * SR)
    wet = np.zeros_like(music_bus)
    wet[d:, 0] = music_bus[:-d, 1] * 0.28
    wet[d:, 1] = music_bus[:-d, 0] * 0.28
    music_bus = (music_bus + wet) * sidechain(N, kicks)[:, None]
    mix += music_bus
    # end: fade the last 1.2 s, master soft clip, -1 dBFS
    fade = int(1.2 * SR)
    mix[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    mix = np.tanh(1.15 * mix) / np.tanh(1.15)
    mix *= 10 ** (-1 / 20) / np.max(np.abs(mix))
    write(OUT / "music/launch.wav", mix)

    sfx = {
        "tick": hp(rng.standard_normal(int(0.03 * SR)), 2500) * env(int(0.03 * SR), 180) * 0.5,
        "whoosh": bp(rng.standard_normal(int(0.7 * SR)), 300, 4000)
        * np.sin(np.linspace(0, np.pi, int(0.7 * SR))) ** 2 * 0.6,
        "ping": (np.sin(2 * np.pi * 1318.5 * np.arange(int(0.8 * SR)) / SR)
                 + 0.4 * np.sin(2 * np.pi * 1975.5 * np.arange(int(0.8 * SR)) / SR)) * env(int(0.8 * SR), 6) * 0.4,
        "impact": sub * 0.9,
    }
    for name, sig in sfx.items():
        write(OUT / f"sfx/{name}.wav", np.stack([sig, sig], axis=1) * (0.9 / max(1e-9, np.max(np.abs(sig)))))
    print(f"music: {N / SR:.1f} s, {BARS} bars at {BPM} BPM; sfx: {', '.join(sfx)}")


def write(path, stereo):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main()
