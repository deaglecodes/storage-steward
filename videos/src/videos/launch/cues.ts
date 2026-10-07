import { at, type Grid } from "../../kit/time";

/** The score is synthesized on an exact grid: 120 BPM, downbeat at 0 (beats.py measured 119.985, spread 5.9 ms). */
export const grid: Grid = { bpm: 120, firstBeat: 0, pickupBeats: 0, beatsPerBar: 4 };
export const b = (bar: number, beat = 1, fraction = 0) => at(grid, bar, beat, fraction);
export const BARS = 20;
export const DURATION = b(BARS + 1); // 40.0 s

/** Scene windows, in grid time. Scene code reads these; it never holds a literal frame. */
export const W = {
  logo: [b(1), b(3) - 0.05],
  punch1: [b(3), b(4) - 0.12],
  problem: [b(4), b(7) - 0.05],
  punch2: [b(7), b(8) - 0.12],
  terminal: [b(8), b(12) + 0.35],
  drop: [b(12), b(14) - 0.05],
  punch3: [b(14), b(15) - 0.12],
  proof: [b(15), b(18) - 0.05],
  end: [b(18), DURATION + 1],
} as const;

/** Typed commands: one character per 16th (scan) and per 32nd (sweep). */
export const typing = {
  scan: { text: "steward.py scan", start: b(8, 1, 0.5), step: 0.125 },
  sweep: { text: "steward.py sweep", start: b(10, 3), step: 0.0625 },
};
export const scanOut = b(9);           // first output line; one line per eighth
export const sweepOut = b(11, 2);      // "swept …" line
