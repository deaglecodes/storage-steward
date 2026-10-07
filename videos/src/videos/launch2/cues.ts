import { at, type Grid } from "../../kit/time";

/** Score v2 is synthesized on an exact grid: 128 BPM, downbeat at 0 (beats.py: spread 2.7 ms). */
export const grid: Grid = { bpm: 128, firstBeat: 0, pickupBeats: 0, beatsPerBar: 4 };
export const b = (bar: number, beat = 1, fraction = 0) => at(grid, bar, beat, fraction);
export const BEAT = 60 / 128;
export const BARS = 24;
export const DURATION = b(BARS + 1); // 45.0 s

/** Hub layout shared by install, automation and the sweep pulses (measured in px at 1080p). */
export const HUB = { x: 960, y: 540 };
export const NODES = [
  { name: "Claude Code", hooks: "Stop · SessionEnd", x: 400, y: 330 },
  { name: "Codex", hooks: "Stop", x: 1520, y: 330 },
  { name: "Cursor", hooks: "stop · sessionEnd", x: 400, y: 770 },
  { name: "Gemini CLI", hooks: "AfterAgent · SessionEnd", x: 1520, y: 770 },
];

/** Automatic sweeps during the time-lapse: [time, node, GB freed]. One per beat-ish, then 8ths on bar 12. */
export const SWEEPS: Array<[number, number, number]> = [
  [b(9, 2), 0, 4.2], [b(9, 4), 2, 1.1], [b(10, 1), 1, 7.8], [b(10, 3), 3, 0.9], [b(10, 4), 0, 12.4],
  [b(11, 2), 1, 3.3], [b(11, 3, 0.5), 3, 2.0], [b(11, 4, 0.5), 2, 5.6],
  [b(12, 1), 0, 0.7], [b(12, 1, 0.5), 1, 2.9], [b(12, 2), 2, 1.8], [b(12, 2, 0.5), 3, 6.1], [b(12, 3), 0, 3.4], [b(12, 3, 0.5), 1, 9.2],
];
export const PULSE = 0.24;   // node -> hub travel time

/** Your-rules exchanges, one bar each from bar 13. */
export const ASKS = [
  { say: "never delete my transcripts", run: "steward.py config set claude-transcripts --tier off" },
  { say: "keep ~/models and every .mov", run: "steward.py config keep ~/models '*.mov'" },
  { say: "clean ~/work/*/build every week", run: "steward.py config add work-builds --path '~/work/*/build' --idle 7" },
  { say: "sweep task output after 6 hours", run: "steward.py config set claude-task-output --idle 6h" },
];
