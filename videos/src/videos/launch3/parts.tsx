import type { CSSProperties, ReactNode } from "react";
import { AbsoluteFill } from "remotion";

import { ease, lerp, rng, seg } from "../launch2/fx";
import { H, W, X0 } from "./cues";
import { F, L, mixHex } from "./theme";

/** Something arriving: a short rise and fade. No scale, no blur, and its slot is held before it shows. */
export function arrive(t: number, at: number, dur = 0.24): CSSProperties {
  const u = ease.out3(seg(t, at, at + dur));
  return { opacity: u, transform: `translateY(${(1 - u) * 16}px)` };
}

export type Word = { text: string; at: number; color?: string };

export function Words({ t, words, style }: { t: number; words: Word[]; style?: CSSProperties }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", columnGap: "0.24em", ...style }}>
      {words.map((w) => (
        <span key={`${w.text}-${w.at}`} style={{ display: "inline-block", color: w.color, ...arrive(t, w.at) }}>{w.text}</span>
      ))}
    </div>
  );
}

/** Characters typed at a fixed pitch from `at`. */
export const typed = (t: number, at: number, per: number, text: string) =>
  text.slice(0, Math.max(0, Math.min(text.length, Math.floor((t - at) / per) + 1)));

/** A block caret that blinks twice a second, on the clock. */
export function Caret({ t, show }: { t: number; show: boolean }) {
  if (!show) return null;
  return <span style={{ display: "inline-block", width: "0.55em", height: "1.1em", marginLeft: 3, verticalAlign: "text-bottom",
    background: L.accent, opacity: Math.floor(t * 2) % 2 ? 0 : 1 }} />;
}

/** The product's sweep: one blue line with the site's soft glow. */
export function SweepLine({ x, top = 0, height = H }: { x: number; top?: number; height?: number }) {
  return <div style={{ position: "absolute", left: x - 1.5, top, width: 3, height, background: L.accent,
    boxShadow: `0 0 30px 6px ${L.accent}55` }} />;
}

/** A scene leaves the way the product works: the line crosses it and the page behind is clean. */
export function Exit({ t, at, dur, children }: { t: number; at: number; dur: number; children: ReactNode }) {
  if (t < at) return <AbsoluteFill>{children}</AbsoluteFill>;
  const u = seg(t, at, at + dur);
  if (u >= 1) return null;
  const x = lerp(-40, W + 40, ease.inOut3(u));
  return (
    <>
      <AbsoluteFill style={{ clipPath: `inset(0 0 0 ${Math.max(0, x)}px)` }}>{children}</AbsoluteFill>
      <SweepLine x={x} />
    </>
  );
}

/** The status line from the site's hero: a count of what is on screen and a thin disk meter. */
export function Status({ count, ratio, opacity = 1 }: { count: number; ratio: number; opacity?: number }) {
  const fill = mixHex(L.accent, L.junk, seg(ratio, 0.42, 0.58));
  return (
    <div style={{ position: "absolute", left: X0, right: X0, top: 972, display: "flex", alignItems: "center", gap: 30,
      fontFamily: F.mono, fontSize: 22, color: L.muted, opacity }}>
      <span style={{ minWidth: 230, fontVariantNumeric: "tabular-nums" }}>{count} leftover{count === 1 ? "" : "s"}</span>
      <div style={{ flex: 1, height: 3, background: L.rule, borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", background: fill, transformOrigin: "0 50%", transform: `scaleX(${0.03 + 0.95 * ratio})` }} />
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- agent leftovers */
const NAMES = ["tasks/#.output", ".npm/_npx/#", "worktrees/agent-#", "rollout-#.jsonl", "DerivedData/App-#", "file-history/#",
  "sessions/#.jsonl", ".cache/uv/archive-#", "snapshots/#", "checkpoints/#", "ShipIt/update-#.zip", "debug/#.txt",
  "node_modules", "tmp.agent#", "transcripts/#.jsonl", "pnpm/store/v10/#", "pip/http-v2/#", "shell-snapshots/#.sh",
  "ms-playwright/chromium-#", "agent-logs/#.log", "tmp/agent-#", "Homebrew/downloads/#", ".venv", "sandbox-#/plugins"];
export const JUNK_PX = 22;
export const CHAR = JUNK_PX * 0.64;     // SF Mono's advance at 22 px

export type Rect = { l: number; r: number; t: number; b: number };
export type Junk = { x: number; y: number; w: number; text: string; at: number };

export function junkName(r: () => number): string {
  const hex = Math.floor(r() * 0xffff).toString(16).padStart(4, "0");
  const size = r() < 0.22 ? `${(0.3 + r() * 20).toFixed(1)} GB` : `${Math.round(2 + r() * 900)} MB`;
  return `${NAMES[Math.floor(r() * NAMES.length)].replace("#", hex)}  ${size}`;
}

/** Fill the frame with leftovers row by row, outside the keep-out boxes; each one lands at its own moment. */
export function buildMess(seed: number, keepOut: Rect[], from: number, to: number): Junk[] {
  const r = rng(seed);
  const items: Junk[] = [];
  for (let y = 46; y < 930; y += 34) {
    for (let x = 40 + r() * 70; x < W - 60;) {
      const text = junkName(r), w = text.length * CHAR;
      if (x + w > W - 40) break;
      const hit = keepOut.some((k) => x < k.r && x + w > k.l && y < k.b && y + 30 > k.t);
      if (!hit) items.push({ x, y, w, text, at: from + (to - from) * Math.pow(r(), 0.75) });
      x += w + 26 + r() * 60;
    }
  }
  return items;
}

/** One leftover: it lands, then a sweep line at `sweepX` erases it from the left. */
export function JunkItem({ t, it, sweepX }: { t: number; it: Junk; sweepX: number }) {
  if (t < it.at) return null;
  const cut = Math.min(it.w + 4, Math.max(0, sweepX - it.x));
  if (cut >= it.w + 4) return null;
  return (
    <div style={{ position: "absolute", left: it.x, top: it.y, whiteSpace: "nowrap", fontFamily: F.mono, fontSize: JUNK_PX,
      color: L.faint, clipPath: cut > 0 ? `inset(0 0 0 ${cut}px)` : undefined, ...arrive(t, it.at, 0.2) }}>{it.text}</div>
  );
}
