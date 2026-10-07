import type { CSSProperties } from "react";

import { C, FONT } from "../launch/tokens";
import { clamp01, lerp, rng } from "./fx";

const LOG: Record<string, string[]> = {
  "Claude Code": ["Read src/app/page.tsx", "Bash npm test --watch", "Task: explore repo (background)", "writing tasks/b19f9ea.output", "Edit components/Hero.tsx", "Bash npx playwright test", "Agent: review changes"],
  Codex: ["exec rg --files", "apply_patch src/api/route.ts", "exec npm install", "worktree add ../app-fix-login", "exec pnpm build", "thread fork 0042 (copy history)"],
  Cursor: ["Indexing workspace…", "Agent: refactor auth flow", "Terminal: npm run dev", "Writing .cursor/logs/agent.log", "Apply edit utils/date.ts", "Run tests (12 files)"],
  "Gemini CLI": ["ReadFile package.json", "Shell uv pip install -r req.txt", "Checkpoint saved (shadow repo)", "WriteFile notebooks/eval.py", "Shell python train.py", "Edit README.md"],
};

/** An agent at work: title bar and a fast scrolling log, all from t. */
export function AgentWindow({ name, t, style, speed = 7 }: { name: string; t: number; style?: CSSProperties; speed?: number }) {
  const lines = LOG[name] ?? LOG["Claude Code"];
  const scroll = t * speed;
  const first = Math.floor(scroll);
  const off = scroll - first;
  return (
    <div style={{ background: C.term, borderRadius: 18, boxShadow: `0 0 0 1.5px ${C.termRule}, 0 30px 60px -20px rgba(0,0,0,0.6)`,
      overflow: "hidden", fontFamily: FONT.mono, color: C.termFg, ...style }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 20px", fontSize: 20, color: C.termMuted, borderBottom: `1.5px solid ${C.termRule}` }}>
        {[0, 1, 2].map((i) => <i key={i} style={{ width: 12, height: 12, borderRadius: 9, background: C.termRule, display: "inline-block" }} />)}
        <b style={{ marginLeft: 8, color: C.termFg, fontWeight: 600 }}>{name}</b>
        <span style={{ marginLeft: "auto", color: C.keep }}>● working</span>
      </div>
      <div style={{ padding: "8px 20px", height: "100%", position: "relative" }}>
        <div style={{ translate: `0 ${-off * 38}px` }}>
          {Array.from({ length: 9 }, (_, i) => {
            const k = first + i;
            const text = lines[k % lines.length];
            const hot = text.includes("output") || text.includes("worktree") || text.includes("install") || text.includes("Checkpoint") || text.includes("fork") || text.includes("logs");
            return (
              <div key={k} style={{ height: 38, display: "flex", alignItems: "center", fontSize: 21, whiteSpace: "nowrap", color: hot ? C.nuke : C.termFg, opacity: 0.55 + 0.45 * ((k * 37) % 7) / 7 }}>
                <span style={{ color: C.termMuted, marginRight: 12 }}>{String(10 + (k % 50)).padStart(2, "0")}:{String((k * 7) % 60).padStart(2, "0")}</span>{text}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

export const LEFTOVERS = [
  "tasks/b19f.output · 21 GB", "local_8c1e/.claude · 300 MB", "node_modules · 612 MB", "rollout-0042.jsonl · 48 MB",
  ".npm/_npx/4f1a · 40 MB", "file-history/9d8e · 12 MB", "DerivedData/App · 1.5 GB", "tmp.agent7 · 30 MB",
  "tasks/7a2c.output · 3.4 GB", "worktrees/fix-login · 640 MB", "debug/9d8e.txt · 8 MB", ".cache/uv/wheels · 1.1 GB",
  "local_31f0/.claude · 300 MB", "snapshot/opencode · 210 MB", "gemini/tmp/chats · 64 MB", "ShipIt/update.zip · 420 MB",
];

export function FileChip({ text, style, hot = true }: { text: string; style?: CSSProperties; hot?: boolean }) {
  return (
    <div style={{ position: "absolute", whiteSpace: "nowrap", fontFamily: FONT.mono, fontSize: 21, padding: "7px 14px", borderRadius: 999,
      background: C.surface, color: C.ink2, boxShadow: `0 0 0 1.5px ${hot ? "#f07a4999" : C.rule}`, ...style }}>{text}</div>
  );
}

/** Ring gauge: track, arc and the percentage, colored by how full it is. */
export function Gauge({ pct, size, x, y, label = "disk", stroke = 18, showText = true }:
  { pct: number; size: number; x: number; y: number; label?: string; stroke?: number; showText?: boolean }) {
  const r = size / 2 - stroke;
  const circ = 2 * Math.PI * r;
  const hot = clamp01((pct - 80) / 12);
  const color = hot > 0.5 ? C.nuke : C.accentHi;
  return (
    <div style={{ position: "absolute", left: x - size / 2, top: y - size / 2, width: size, height: size }}>
      <svg width={size} height={size} style={{ position: "absolute", rotate: "-90deg" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={C.logoTrack} strokeWidth={stroke} />
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          strokeDasharray={`${(circ * pct) / 100} ${circ}`} />
      </svg>
      {showText ? (
        <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", alignContent: "center", gap: 2 }}>
          <b style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: size * 0.27, color: hot > 0.5 ? C.nuke : C.ink, lineHeight: 1, fontVariantNumeric: "tabular-nums" }}>{Math.round(pct)}%</b>
          <span style={{ fontFamily: FONT.mono, fontSize: size * 0.085, color: C.muted, letterSpacing: "0.08em" }}>{label.toUpperCase()}</span>
        </div>
      ) : null}
    </div>
  );
}

/** Small deterministic jitter around a point, for junk chips orbiting a node. */
export function orbit(seed: number, t: number, radius: number) {
  const r = rng(seed);
  const a0 = r() * Math.PI * 2;
  const w = 0.6 + r() * 0.8;
  const rr = radius * (0.75 + r() * 0.5);
  return { dx: Math.cos(a0 + t * w) * rr * 1.6, dy: Math.sin(a0 + t * w) * rr * 0.55 };
}

export const mix = (a: string, z: string, u: number) => {
  const p = (h: string) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [A, Z] = [p(a), p(z)];
  return `rgb(${A.map((v, i) => Math.round(lerp(v, Z[i], u))).join(",")})`;
};
