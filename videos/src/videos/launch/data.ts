import sim from "./sim.json";

/** Demo data = the site's benchmark data (docs/assets/sim.json), so the film and the site agree. */
type Series = Record<"none" | "daily-nuke" | "steward" | "steward+weekly", number[]>;
const S = sim.series as unknown as Record<"typical" | "runaway", Series>;

/** GB on a fractional day (1..60), interpolated between the simulated days. */
export function gbAt(scenario: "typical" | "runaway", policy: keyof Series, day: number) {
  const arr = S[scenario][policy];
  const x = Math.min(arr.length - 1, Math.max(0, day - 1));
  const i = Math.floor(x);
  const f = x - i;
  return arr[i] + (arr[Math.min(arr.length - 1, i + 1)] - arr[i]) * f;
}

/** `steward.py scan` / `sweep` as the tool prints them; sizes from the 60-day model at day 14 (no cleanup). */
export type Line = { kind: "plain" | "tier" | "row" | "more"; text?: string; tier?: "AUTO" | "CONFIRM" | "INFO"; note?: string; size?: string; rule?: string; extra?: string };
export const SCAN: Line[] = [
  { kind: "plain", text: "disk: 18.4 GB free of 460 GB (96% used)" },
  { kind: "tier", tier: "AUTO", note: "sweep; regenerable, no data loss", size: "53.7 GB" },
  { kind: "row", rule: "desktop-sandbox-plugins", size: "27.4 GB", extra: "plugin clones" },
  { kind: "row", rule: "claude-task-output", size: "19.6 GB", extra: "runaway" },
  { kind: "row", rule: "xcode-derived-data", size: "2.9 GB", extra: "14 items" },
  { kind: "row", rule: "claude-tmp-sessions", size: "1.4 GB", extra: "idle >3d" },
  { kind: "more", text: "… 5 more rules" },
  { kind: "tier", tier: "CONFIRM", note: "ask user, then: sweep --tier confirm --only RULE --yes", size: "8.5 GB" },
  { kind: "row", rule: "agent-worktrees", size: "4.8 GB", extra: "clean" },
  { kind: "row", rule: "stale-project-deps", size: "1.5 GB", extra: "idle 30+ days" },
  { kind: "row", rule: "claude-transcripts", size: "1.2 GB", extra: ">30d" },
  { kind: "tier", tier: "INFO", note: "never auto-deleted", size: "12.8 GB" },
];
export const SWEPT_GB = 53.7;
export const FREE_AFTER = "72.1 GB free";

export const KPIS = [
  { value: 85, suffix: "%", label: "less disk used by day 60" },
  { value: 0, suffix: "", tail: " vs 104", label: "files lost, vs a daily manual wipe" },
  { value: 72, suffix: "%", label: "fewer tokens when an agent cleans up" },
];
export const AGENTS = ["Claude Code", "Codex", "Cursor", "Gemini CLI"];
