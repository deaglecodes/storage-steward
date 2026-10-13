/** Launch v3, the minimal cut: 120 BPM, 16 bars = 32 s, bar 1 opens at 0.
 *  Every scene leaves the same way the product works: a sweep line crosses it and leaves a clean page,
 *  landing on the next bar. tools/score_v3.py mirrors these numbers. */
export const BPM = 120;
export const BEAT = 60 / BPM;
export const BAR = 4 * BEAT;
export const b = (bar: number, beat = 1, frac = 0) => (bar - 1) * BAR + (beat - 1 + frac) * BEAT;
export const DURATION = b(17);

export const W = 1920;
export const H = 1080;
export const X0 = 160;            // left margin, and the right one
export const WIPE = 0.75;         // a scene's exit sweep, ending on the bar line

/** [first frame, start of the exit sweep] per scene. The mess is erased by its own two-bar sweep in bar 4. */
export const SCENE = {
  mess: [0, b(4)],
  less: [b(5), b(7) - WIPE],
  clone: [b(7), b(9) - WIPE],
  forget: [b(9), b(11) - WIPE],
  rules: [b(11), b(13) - WIPE],
  proof: [b(13), b(15) - WIPE],
  end: [b(15), b(17)],
} as const;

/** Typed lines: start time and seconds per character (the score ticks on the same characters). */
export const CMD = "git clone https://github.com/deaglecodes/storage-steward && cd storage-steward && ./install.sh";
export const TYPE_CMD = { at: b(7, 2), per: 0.016 };
export const SAY = "keep ~/models and every .mov";
export const TYPE_SAY = { at: b(11, 2), per: 0.03 };
export const RUN = "steward.py config keep ~/models '*.mov'";
export const TYPE_RUN = { at: b(11, 4), per: 0.018 };

/** Then forget it: sessions run along a track; the background sweep clears what they leave, every few sessions. */
export const SESSIONS = Array.from({ length: 6 }, (_, k) => b(9, 2) + k * 0.45);
export const SESSION_LEN = 0.32;
export const BG_SWEEPS = [1, 3, 5].map((k) => ({ after: k, at: SESSIONS[k] + SESSION_LEN + 0.04 }));
export const BG_SWEEP_LEN = 0.34;
