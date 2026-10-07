# Audio

- `music/launch.wav`: original score, synthesized by `tools/synth.py` (numpy + scipy). 120 BPM, 20 bars, 40.0 s.
  Written for this film; no samples or third-party recordings. Released with the repo under MIT.
- `sfx/*.wav`: tick, whoosh, ping, impact, synthesized by the same script.

Regenerate with:

    uv run --exclude-newer 2026-09-30 --with numpy --with scipy python3 tools/synth.py
