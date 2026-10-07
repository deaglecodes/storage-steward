"""Score v2 for the storage-steward launch film: 128 BPM, 24 bars = 45.0 s, E minor, synthesized from scratch.

    uv run --exclude-newer 2026-09-30 --with numpy --with scipy python3 tools/score_v2.py

  1-2   intro: sub drone, ticking hats, arp opening, riser + reverse swell      (pile-up, suck-in)
  3-4   groove + chord stabs on every word, big hit on 4.1                     (punchline)
  5     stomp: kick + clap + stab on every beat, glitch roll on 5.4.5           (the chore, 4 cuts)
  6     tape stop on beat 1, silence, reverse swell, bloom on 6.4               (turn, logo)
  7-8   build: kick, hats, snare roll, riser, pre-drop gap                      (install once)
  9-12  main groove, extra percussion on 12, swell into 13                      (it just runs)
  13-16 half-time groove, playful keys, riser + roll + gap                      (your rules)
  17-20 DROP: supersaw chords, sub, crash on 17.1 and 19.1, hits on bar 19     (chart, proof slams)
  21-23 outro, filter closing                                                   (lockup)
  24    final hit, ring out                                                     (end card)
Also writes SFX: tick, whoosh, impact, ping, flip, shimmer.
"""
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, sosfilt

SR = 48000
BPM = 128
BEAT = 60 / BPM
BAR = 4 * BEAT
BARS = 24
N = int(round(BARS * BAR * SR))
rng = np.random.default_rng(11)
OUT = Path(__file__).resolve().parents[1] / "public/audio/launch2"

CHORDS = [(52, 55, 59), (48, 52, 55), (55, 59, 62), (50, 54, 57)]   # Em C G D
ROOTS = [40, 36, 43, 38]
hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
b = lambda bar, beat=1, frac=0.0: (bar - 1) * BAR + (beat - 1 + frac) * BEAT


def sos(kind, f, order=2):
    return butter(order, f, kind, fs=SR, output="sos")


def lp(x, f, order=2):
    return sosfilt(sos("low", min(f, SR / 2 - 200), order), x)


def hp(x, f, order=2):
    return sosfilt(sos("high", f, order), x)


def bp(x, lo, hi):
    return sosfilt(sos("band", [lo, hi]), x)


def env(n, decay, attack=0.002):
    t = np.arange(n) / SR
    return np.clip(t / attack, 0, 1) * np.exp(-t * decay)


def saw(f, n, phase=0.0):
    t = np.arange(n) / SR
    return 2 * ((t * f + phase) % 1.0) - 1


def place(buf, sig, at, gain=1.0, pan=0.0):
    i = int(round(at * SR))
    if i >= N or i < 0:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    buf[i:i + len(sig), 0] += sig * l * 1.414
    buf[i:i + len(sig), 1] += sig * r * 1.414


def place_st(buf, st, at, gain=1.0):
    i = int(round(at * SR))
    if i >= N:
        return
    st = st[: N - i] * gain
    buf[i:i + len(st)] += st


# ---------------------------------------------------------------- instruments
def kick(punch=1.0):
    n = int(0.42 * SR)
    t = np.arange(n) / SR
    f = 44 + 140 * punch * np.exp(-t * 34)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 7)
    click = hp(rng.standard_normal(n), 2500) * env(n, 500) * 0.3
    return np.tanh(1.8 * (body + click))


def clap():
    n = int(0.32 * SR)
    noise = bp(rng.standard_normal(n), 900, 5000)
    e = sum(np.roll(env(n, 75), int(d * SR)) for d in (0, 0.01, 0.021)) + env(n, 13) * 0.7
    return noise * e * 0.5


def snare():
    n = int(0.2 * SR)
    t = np.arange(n) / SR
    tone = np.sin(2 * np.pi * 190 * t) * np.exp(-t * 30)
    return (bp(rng.standard_normal(n), 1200, 7000) * env(n, 26) + 0.5 * tone) * 0.6


def hat(open_=False):
    n = int((0.3 if open_ else 0.06) * SR)
    return hp(rng.standard_normal(n), 7800, 3) * env(n, 10 if open_ else 70)


def rim():
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 1700 * t) + 0.5 * hp(rng.standard_normal(n), 3000)) * env(n, 90) * 0.4


def pluck(m, cutoff, length=0.2):
    n = int(length * SR)
    f = hz(m)
    x = 0.6 * saw(f, n) + 0.4 * np.sign(np.sin(2 * np.pi * f * np.arange(n) / SR))
    return lp(x, cutoff) * env(n, 17)


def keys(m, length=0.35):          # marimba-ish: sine + octave partial, quick decay
    n = int(length * SR)
    t = np.arange(n) / SR
    f = hz(m)
    return (np.sin(2 * np.pi * f * t) + 0.35 * np.sin(2 * np.pi * 4 * f * t) * np.exp(-t * 30)) * env(n, 9) * 0.6


def supersaw(chord, length, cutoff=5200, stab=False):
    n = int(length * SR)
    L, R = np.zeros(n), np.zeros(n)
    for m in chord:
        for k, d in enumerate((-0.22, -0.13, -0.05, 0.0, 0.05, 0.13, 0.22)):
            x = saw(hz(m) * 2 ** (d / 12), n, rng.random())
            (L if k % 2 else R)[:] += x
            if k == 3:
                L[:] += x * 0.5
                R[:] += x * 0.5
    t = np.arange(n) / SR
    shape = (np.exp(-t * 6) if stab else np.clip(t / 0.02, 0, 1) * np.clip((length - t) / 0.06, 0, 1))
    st = np.stack([lp(L, cutoff), lp(R, cutoff)], axis=1) / (len(chord) * 5)
    return st * shape[:, None]


def pad(chord, length, cutoff=1500):
    n = int(length * SR)
    x = np.zeros(n)
    for m in chord:
        for d in (-0.09, 0.0, 0.08):
            x += saw(hz(m - 12) * 2 ** (d / 12), n, rng.random())
    t = np.arange(n) / SR
    return lp(x / 9, cutoff) * np.clip(t / 0.3, 0, 1) * np.clip((length - t) / 0.25, 0, 1)


def sub_hit(length=1.4, f0=70):
    n = int(length * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * np.cumsum(f0 * np.exp(-t * 1.6) + 26) / SR) * np.exp(-t * 2.4)


def crash(length=2.4):
    n = int(length * SR)
    return hp(rng.standard_normal(n), 3500) * env(n, 2.0)


def swell(length):                  # reverse cymbal ending at `length`
    n = int(length * SR)
    t = np.arange(n) / SR
    return hp(rng.standard_normal(n), 2500) * (t / length) ** 3


def riser(length):
    n = int(length * SR)
    t = np.arange(n) / SR
    x = rng.standard_normal(n)
    out = np.zeros(n)
    seg = n // 16
    for k in range(16):                     # stepped highpass sweep
        a, z = k * seg, (k + 1) * seg if k < 15 else n
        out[a:z] = hp(x[a:z], 300 + 400 * k)
    return out * (t / length) ** 2


def sidechain(kicks, depth=0.75, rel=11):
    g = np.ones(N)
    for k in kicks:
        i = int(k * SR)
        m = min(int(0.36 * SR), N - i)
        if m > 0:
            g[i:i + m] = np.minimum(g[i:i + m], 1 - depth * np.exp(-np.arange(m) / SR * rel))
    return g


# ---------------------------------------------------------------- arrangement
def main():
    drums = np.zeros((N, 2))
    bus = np.zeros((N, 2))          # sidechained musical parts
    fx = np.zeros((N, 2))
    kicks = []

    def k_(t, gain=0.95, punch=1.0):
        kicks.append(t)
        place(drums, kick(punch), t, gain)

    for bar in range(1, BARS + 1):
        ci = (bar - 1) % 4
        chord, root = CHORDS[ci], ROOTS[ci]
        # ---- drums
        if bar in (3, 4, 7, 8) or 9 <= bar <= 12 or 17 <= bar <= 22:
            for beat in range(1, 5):
                k_(b(bar, beat))
        if 13 <= bar <= 16:                       # half-time
            for beat in (1, 3):
                k_(b(bar, beat))
            place(drums, clap(), b(bar, 3), 0.45)
        if bar == 5:
            for beat in range(1, 5):
                k_(b(bar, beat), 1.0, 1.2)
                place(drums, clap(), b(bar, beat), 0.5)
        if bar in (3, 4, 7) or 9 <= bar <= 12 or 17 <= bar <= 22:
            for beat in (2, 4):
                place(drums, clap(), b(bar, beat), 0.45, 0.05)
        if bar <= 2:
            for s in range(16):
                place(drums, hat(), b(bar, 1, s / 4), 0.035 + 0.02 * (s % 2), 0.3)
        if bar in (3, 4, 7, 8) or 9 <= bar <= 23:
            step = 4 if (9 <= bar <= 12 or 17 <= bar <= 20) else 2
            for s in range(4 * step):
                place(drums, hat(), b(bar, 1, s / step), 0.05 if s % 2 else 0.035, 0.25)
        if 9 <= bar <= 12 or 17 <= bar <= 20:
            for beat in range(1, 5):
                place(drums, hat(True), b(bar, beat, 0.5), 0.06, -0.3)
        if bar == 12:
            for s in range(16):
                place(drums, rim(), b(bar, 1, s / 4), 0.25 if s % 4 == 2 else 0.12, 0.4)
        # ---- bass: offbeat 8ths (octave jumps in the big sections)
        if bar in (3, 4, 7, 8) or 9 <= bar <= 12 or 17 <= bar <= 22:
            for e in range(8):
                if e % 2 == 0 and bar not in range(17, 21):
                    continue
                n = int(BEAT / 2 * SR * 0.9)
                m = root + (12 if (e in (3, 7) and (9 <= bar <= 12 or 17 <= bar <= 20)) else 0)
                note = lp(saw(hz(m), n) + 0.5 * saw(hz(m) * 1.005, n), 500 if bar < 17 else 800) * env(n, 6, 0.003)
                place(bus, note, b(bar, 1, e / 2), 0.5)
        if 13 <= bar <= 16:
            for e in (0, 3, 4, 6):
                n = int(BEAT * 0.9 * SR)
                place(bus, lp(saw(hz(root), n), 350) * env(n, 5, 0.004), b(bar, 1, e / 2), 0.5)
        if bar <= 2:                               # sub drone swell
            n = int(BAR * SR)
            t = np.arange(n) / SR
            place(bus, lp(saw(hz(28), n), 260 + 300 * (bar - 1)) * (0.4 + 0.3 * t / BAR), b(bar), 0.5)
        # ---- harmony
        if bar not in (5, 6, 24) and not (17 <= bar <= 20):
            place(bus, pad(chord, BAR + 0.3, 1100 if bar <= 2 else 1600), b(bar), 0.45)
        if 17 <= bar <= 20:                        # the drop: offbeat supersaw stabs + sustained chord
            place_st(bus, supersaw(chord, BAR, 6000), b(bar), 0.55)
            for e in range(8):
                if e % 2:
                    place_st(bus, supersaw(chord, BEAT / 2, 7500, stab=True), b(bar, 1, e / 2), 0.7)
        if bar in (3, 4):                          # stabs on the words
            for beat in range(1, 5):
                place_st(bus, supersaw(chord, BEAT * 0.9, 6500, stab=True), b(bar, beat), 0.9 if bar == 3 else 0.6)
        if bar == 5:
            for beat in range(1, 5):
                place_st(bus, supersaw(CHORDS[beat % 4], BEAT * 0.8, 7000, stab=True), b(bar, beat), 1.0)
        # ---- arps / keys
        if bar <= 2 or 7 <= bar <= 12 or 21 <= bar <= 23:
            pattern = [0, 1, 2, 1, 2, 0, 2, 1, 0, 2, 1, 2, 1, 0, 2, 1]
            cutoff = 700 + 2800 * min(1.0, bar / 2.5) if bar <= 2 else (5200 if bar <= 12 else 5200 - 1200 * (bar - 20))
            for s, idx in enumerate(pattern):
                m = chord[idx] + 12 + (12 if s % 8 >= 4 else 0)
                place(bus, pluck(m, cutoff), b(bar, 1, s / 4), 0.13, -0.35 if s % 2 else 0.35)
        if 13 <= bar <= 16:
            melody = [(0, 2), (0.75, 1), (1.5, 2), (2.5, 0), (3, 1), (3.5, 2)]
            for pos, idx in melody:
                place(bus, keys(chord[idx] + 12), b(bar, 1, pos), 0.5, 0.2)

    # ---- transitions and hits
    place(fx, riser(BAR), b(2), 0.25)
    place(fx, swell(BEAT * 1.0), b(3) - BEAT, 0.35)
    place(fx, sub_hit(1.2), b(4), 0.75)
    place(fx, crash(1.8), b(4), 0.12)
    place(fx, riser(BAR), b(8), 0.28)
    for s in range(16):                            # snare roll through bar 8: 8ths, 16ths, 32nds
        place(drums, snare(), b(8, 1, s / 4), 0.12 + 0.02 * s)
    for s in range(8):
        place(drums, snare(), b(8, 4, s / 8), 0.4)
    place(fx, swell(BEAT), b(13) - BEAT, 0.3)
    place(fx, riser(BAR * 2), b(15), 0.3)
    for s in range(8):
        place(drums, snare(), b(16, 3, s / 8), 0.18 + 0.03 * s)
    for t in (b(17), b(19)):
        place(fx, crash(2.6), t, 0.14)
        place(fx, sub_hit(1.6, 80), t, 0.8)
    for beat in range(1, 5):                       # proof slams
        place(fx, sub_hit(0.5, 90), b(19, beat), 0.45)
    place(fx, sub_hit(2.6, 60), b(24), 0.8)
    place(fx, crash(3.0), b(24), 0.12)
    place_st(bus, supersaw(CHORDS[0], 3.0, 3500), b(24), 0.6)

    # pre-drop gaps: silence the last 8th before bars 9 and 17
    for bar in (9, 17):
        a, z = int((b(bar) - BEAT / 2) * SR), int(b(bar) * SR)
        drums[a:z] = 0
        bus[a:z] *= 0.15

    music = drums + bus * sidechain(kicks)[:, None] + fx
    # bar 6: tape stop of the last 8th of bar 5, then silence until the bloom on 6.4
    b6 = int(b(6) * SR)
    music[b6:int(b(6, 4) * SR)] = 0
    T = BEAT * 1.1
    n = int(T * SR)
    src = music[b6 - int(T / 3 * SR): b6].copy()
    tt = np.arange(n) / SR
    speed = (1 - tt / T) ** 2
    pos = np.clip(np.cumsum(speed), 0, len(src) - 2)
    i0 = pos.astype(int)
    frac = (pos - i0)[:, None]
    tape = src[i0] * (1 - frac) + src[i0 + 1] * frac
    tape *= np.linspace(1, 0.2, n)[:, None]
    music[b6:b6 + n] += tape
    place(music, swell(BEAT * 1.6), b(6, 4) - BEAT * 1.6, 0.4)
    place_st(music, supersaw(CHORDS[0], BAR, 3000), b(6, 4), 0.5)
    place(music, sub_hit(1.4, 75), b(6, 4), 0.7)
    # glitch roll at 5.4.5: repeat a 32nd four times
    g0, g = int(b(5, 4, 0.5) * SR), int(BEAT / 8 * SR)
    piece = music[g0:g0 + g].copy()
    for k in range(4):
        music[g0 + k * g: g0 + (k + 1) * g] = piece * (1 - 0.12 * k)

    # simple stereo widening delay on the musical bus already baked; master
    fade = int(1.4 * SR)
    music[-fade:] *= np.linspace(1, 0, fade)[:, None] ** 2
    music = np.tanh(1.2 * music) / np.tanh(1.2)
    music *= 10 ** (-1 / 20) / np.max(np.abs(music))
    write(OUT / "music/launch2.wav", music)

    sfx = {
        "tick": hp(rng.standard_normal(int(0.025 * SR)), 2800) * env(int(0.025 * SR), 200) * 0.5,
        "whoosh": bp(rng.standard_normal(int(0.55 * SR)), 250, 5000) * np.sin(np.linspace(0, np.pi, int(0.55 * SR))) ** 2,
        "impact": np.tanh(1.5 * (sub_hit(0.7, 95) + hp(rng.standard_normal(int(0.7 * SR)), 1500) * env(int(0.7 * SR), 18) * 0.5)),
        "ping": (np.sin(2 * np.pi * 1318.5 * np.arange(int(0.6 * SR)) / SR)
                 + 0.4 * np.sin(2 * np.pi * 1975.5 * np.arange(int(0.6 * SR)) / SR)) * env(int(0.6 * SR), 8),
        "flip": bp(rng.standard_normal(int(0.08 * SR)), 1500, 6000) * env(int(0.08 * SR), 60),
        "shimmer": sum(np.sin(2 * np.pi * hz(m) * np.arange(int(1.2 * SR)) / SR) for m in (76, 79, 83, 88)) * env(int(1.2 * SR), 3, 0.05) * 0.3,
    }
    for name, sig in sfx.items():
        write(OUT / f"sfx/{name}.wav", np.stack([sig, sig], axis=1) * (0.9 / max(1e-9, np.max(np.abs(sig)))))
    print(f"score v2: {N / SR:.2f} s, {BARS} bars at {BPM} BPM; sfx: {', '.join(sfx)}")


def write(path, stereo):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(stereo, -1, 1) * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    main()
