import { AbsoluteFill, Html5Audio, Sequence, staticFile, useVideoConfig } from "remotion";

import { TargetLog } from "../../kit/debug";
import { move, swapIn, type Rect } from "../../kit/move";
import { Punchlines, type Card } from "../../kit/punchlines";
import { step } from "../../kit/spring";
import { clamp01, progress, useTime } from "../../kit/time";
import { b, scanOut, sweepOut, typing, W } from "./cues";
import { AGENTS, FREE_AFTER, gbAt, KPIS, SCAN, SWEPT_GB, type Line } from "./data";
import { DayScrub, DfRow } from "./Df";
import { Mark } from "./Logo";
import { Panel } from "./Panel";
import { C, FONT } from "./tokens";

export type LaunchProps = { fps: number; debug: boolean };

const inWin = (t: number, [a, z]: readonly [number, number]) => t >= a - 0.05 && t <= z + 0.3;
const rise = { stiffness: 170, damping: 22 };

/* ------------------------------------------------------------------ punchlines */
const CARDS: Card[] = [
  { lines: [[{ text: "Your", at: b(3, 1) }, { text: "agents", at: b(3, 2) }, { text: "leave", at: b(3, 3) }],
    [{ text: "files", at: b(3, 4), accent: true }, { text: "behind.", at: b(3, 4, 0.5), accent: true }]], out: W.punch1[1], y: 540, size: 150 },
  { lines: [[{ text: "This", at: b(7, 1) }, { text: "cleans", at: b(7, 2), accent: true }, { text: "up", at: b(7, 2, 0.5), accent: true }],
    [{ text: "as", at: b(7, 3) }, { text: "they", at: b(7, 3, 0.5) }, { text: "work.", at: b(7, 4) }]], out: W.punch2[1], y: 540, size: 150 },
  { lines: [[{ text: "Zero", at: b(14, 1), accent: true }, { text: "tokens.", at: b(14, 2) }],
    [{ text: "Zero", at: b(14, 3), accent: true }, { text: "files", at: b(14, 4) }, { text: "lost.", at: b(14, 4, 0.5) }]], out: W.punch3[1], y: 540, size: 150 },
];

/* ------------------------------------------------------------------ 1. logo */
function LogoAct({ t }: { t: number }) {
  if (!inWin(t, W.logo)) return null;
  const leave = clamp01((t - (W.logo[1] - 0.25)) / 0.25);
  const word = clamp01((t - b(2, 2)) / 0.3);
  const land = 1 - Math.pow(1 - word, 3);
  return (
    <AbsoluteFill style={{ display: "grid", placeItems: "center", opacity: 1 - leave, filter: leave ? `blur(${leave * 12}px)` : undefined }}>
      <div style={{ display: "flex", alignItems: "center", gap: 44 }}>
        <Mark t={t} draw0={b(1)} pop0={b(2)} size={250} />
        <div style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 132, letterSpacing: "-0.035em", color: C.ink,
          opacity: land, translate: `${(1 - land) * -30}px 0`, filter: land < 1 ? `blur(${(1 - land) * 14}px)` : undefined }}>
          storage-steward
        </div>
      </div>
    </AbsoluteFill>
  );
}

/* ------------------------------------------------------------------ 3. the problem: a 1 TB disk filling */
const DF_RECT: Rect = { x: 340, y: 270, w: 1240, h: 540 };
const PROBLEM_TOP = 368;   // measured: one-row panel is ~344 px tall, centered on 540

function ProblemAct({ t }: { t: number }) {
  if (!inWin(t, W.problem)) return null;
  const s = swapIn(t, W.problem[0], W.problem[1], 0);
  const day = 1 + 59 * progress(t, b(4), b(6) - b(4));
  const gb = gbAt("runaway", "none", day);
  const flash = [b(6, 1), b(6, 2), b(6, 3), b(6, 4)].reduce((m, c) => Math.max(m, clamp01(1 - (t - c) / 0.3) * (t >= c ? 1 : 0)), 0);
  return (
    <div style={{ opacity: s.opacity, filter: s.filter }}>
      <Panel title="df -h  ·  1 TB drive  ·  no cleanup" style={{ left: DF_RECT.x, top: PROBLEM_TOP, width: DF_RECT.w }}>
        <div style={{ display: "grid", gap: 40 }}>
          <DfRow label="agent leftovers" gb={gb} color={gb >= 1000 ? C.nuke : C.none} flash={flash} size={40} />
          <DayScrub day={day} />
        </div>
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ 5. the terminal: scan, then sweep */
const TERM_RECT: Rect = { x: 220, y: 96, w: 1480, h: 888 };
const TIER_COLOR = { AUTO: C.keep, CONFIRM: C.accent, INFO: C.termMuted };

function Typed({ t, text, start, stepS }: { t: number; text: string; start: number; stepS: number }) {
  const n = Math.max(0, Math.min(text.length, Math.floor((t - start) / stepS) + 1));
  const done = t >= start + text.length * stepS;
  const caret = !done || Math.floor(t * 4) % 2 === 0;
  return (
    <div style={{ display: "flex", fontSize: 32, whiteSpace: "pre" }}>
      <span style={{ color: C.termMuted }}>$ </span>
      <span>{t < start ? "" : text.slice(0, n)}</span>
      <span style={{ width: 18, height: 36, marginLeft: 4, background: caret ? C.termFg : "transparent", alignSelf: "center" }} />
    </div>
  );
}

function ScanLine({ line, at, t }: { line: Line; at: number; t: number }) {
  const u = clamp01((t - at) / 0.14);
  if (u <= 0) return <div style={{ height: 44 }} />;
  const style = { opacity: u, filter: u < 1 ? `blur(${(1 - u) * 6}px)` : undefined, height: 44, display: "flex", alignItems: "center", fontSize: 27, whiteSpace: "pre" as const };
  if (line.kind === "tier") {
    const color = TIER_COLOR[line.tier!];
    return (
      <div style={{ ...style, gap: 16, marginTop: 10 }}>
        <span style={{ fontWeight: 600, fontSize: 22, letterSpacing: "0.06em", color, background: `${color}22`, padding: "3px 12px", borderRadius: 99 }}>{line.tier}</span>
        <span style={{ color: C.termMuted, flex: 1 }}>{line.note}</span>
        <b style={{ fontWeight: 600 }}>{line.size}</b>
      </div>
    );
  }
  if (line.kind === "row") {
    return (
      <div style={{ ...style, paddingLeft: 34 }}>
        <span style={{ width: 470 }}>{line.rule}</span>
        <span style={{ width: 150, textAlign: "right", fontWeight: 600 }}>{line.size}</span>
        <span style={{ color: C.termMuted, marginLeft: 26 }}>{line.extra}</span>
      </div>
    );
  }
  return <div style={{ ...style, color: line.kind === "more" ? C.termMuted : C.termFg, paddingLeft: line.kind === "more" ? 34 : 0 }}>{line.text}</div>;
}

function TerminalBody({ t }: { t: number }) {
  const gb = SWEPT_GB * clamp01((t - sweepOut) / 0.45);
  const swept = clamp01((t - sweepOut) / 0.14);
  return (
    <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr)", gap: 2 }}>
      <Typed t={t} text={typing.scan.text} start={typing.scan.start} stepS={typing.scan.step} />
      {SCAN.map((line, i) => <ScanLine key={i} line={line} at={scanOut + i * 0.25} t={t} />)}
      <div style={{ height: 18 }} />
      {t >= typing.sweep.start - 0.01 ? <Typed t={t} text={typing.sweep.text} start={typing.sweep.start} stepS={typing.sweep.step} /> : <div style={{ height: 44 }} />}
      <div style={{ height: 52, display: "flex", alignItems: "center", fontSize: 30, opacity: swept, whiteSpace: "pre" }}>
        <span style={{ color: C.keep, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>swept {gb.toFixed(1)} GB</span>
        <span style={{ color: C.termMuted }}> (desktop-sandbox-plugins 27.4 GB, …) | </span>
        <span style={{ opacity: clamp01((t - b(11, 3)) / 0.15) }}>{FREE_AFTER}</span>
      </div>
    </div>
  );
}

function TerminalAct({ t }: { t: number }) {
  if (!inWin(t, [W.terminal[0], b(12)])) return null;
  const s = swapIn(t, W.terminal[0], b(12) + 0.05, 0, 0.12);
  return (
    <div style={{ opacity: s.opacity, filter: s.filter }}>
      <Panel title="~ — zsh" style={{ left: TERM_RECT.x, top: TERM_RECT.y, width: TERM_RECT.w, height: TERM_RECT.h }}>
        <TerminalBody t={t} />
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ 6. the drop: the terminal becomes the df panel */
function DropAct({ t }: { t: number }) {
  if (!inWin(t, [b(12) - 0.02, W.drop[1]])) return null;
  const r = move(t, b(12), TERM_RECT, DF_RECT, { stiffness: 150, damping: 20 });
  const content = swapIn(t, b(12), W.drop[1], 0.32);
  const leave = clamp01((t - (W.drop[1] - 0.2)) / 0.2);
  const day = 3 + 57 * progress(t, b(12, 2), b(13, 3) - b(12, 2));   // day 1-2 of this seed hold a runaway not yet swept
  const none = gbAt("runaway", "none", day);
  const kept = gbAt("runaway", "steward", day);
  return (
    <div style={{ opacity: 1 - leave, filter: leave ? `blur(${leave * 12}px)` : undefined }}>
      <div style={{ position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, background: C.term, borderRadius: 26, boxShadow: `0 0 0 1.5px ${C.termRule}` }} />
      <div style={{ opacity: content.opacity, filter: content.filter }}>
        <Panel title="df -h  ·  1 TB drive  ·  60 days, simulated" style={{ left: DF_RECT.x, top: DF_RECT.y, width: DF_RECT.w, background: "transparent", boxShadow: "none" }}>
          <div style={{ display: "grid", gap: 34 }}>
            <DfRow label="no cleanup" gb={none} color={none >= 1000 ? C.nuke : C.none} size={36} />
            <DfRow label="storage-steward" gb={kept} color={C.accentHi} size={36} />
            <DayScrub day={day} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ 8. proof */
function ProofAct({ t }: { t: number }) {
  if (!inWin(t, W.proof)) return null;
  const starts = [b(15, 1), b(15, 3), b(16, 1)];
  const leave = clamp01((t - (W.proof[1] - 0.25)) / 0.25);
  const cap = clamp01((t - b(17)) / 0.3);
  return (
    <AbsoluteFill style={{ display: "grid", placeItems: "center", opacity: 1 - leave, filter: leave ? `blur(${leave * 12}px)` : undefined }}>
      <div style={{ display: "grid", gap: 44, justifyItems: "center" }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 470px)", gap: 30 }}>
          {KPIS.map((k, i) => {
            const u = step(t - starts[i], rise);
            const count = Math.round(k.value * clamp01((t - starts[i]) / 0.6));
            return (
              <div key={i} style={{ background: C.surface, borderRadius: 22, boxShadow: `0 0 0 1.5px ${C.rule}`, padding: "40px 40px 36px",
                display: "grid", gap: 14, opacity: clamp01(u * 1.5), translate: `0 ${(1 - u) * 50}px` }}>
                <div style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 128, lineHeight: 1, letterSpacing: "-0.04em", fontVariantNumeric: "tabular-nums" }}>
                  {count}{k.suffix}<span style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 34, color: C.muted, letterSpacing: 0 }}>{k.tail ?? ""}</span>
                </div>
                <div style={{ fontSize: 31, color: C.muted, lineHeight: 1.3 }}>{k.label}</div>
              </div>
            );
          })}
        </div>
        <div style={{ fontFamily: FONT.mono, fontSize: 26, color: C.muted, opacity: cap }}>60-day benchmark · 3 seeds · token evals 2 runs per configuration</div>
      </div>
    </AbsoluteFill>
  );
}

/* ------------------------------------------------------------------ 9. ending */
function EndAct({ t }: { t: number }) {
  if (t < W.end[0] - 0.05) return null;
  const word = 1 - Math.pow(1 - clamp01((t - b(18, 3)) / 0.3), 3);
  const url = clamp01((t - b(20)) / 0.3);
  return (
    <AbsoluteFill style={{ display: "grid", placeItems: "center" }}>
      <div style={{ display: "grid", gap: 56, justifyItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 36 }}>
          <Mark t={t} draw0={b(18)} pop0={b(18, 2)} size={180} />
          <div style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 112, letterSpacing: "-0.035em",
            opacity: word, translate: `${(1 - word) * -30}px 0`, filter: word < 1 ? `blur(${(1 - word) * 14}px)` : undefined }}>storage-steward</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={{ fontFamily: FONT.mono, fontSize: 24, letterSpacing: "0.08em", color: C.muted, marginRight: 8, opacity: clamp01((t - b(19)) / 0.25) }}>WORKS WITH</span>
          {AGENTS.map((name, i) => {
            const u = step(t - b(19, i + 1), rise);
            return (
              <span key={name} style={{ fontSize: 34, fontWeight: 500, color: C.ink2, background: C.surface, boxShadow: `0 0 0 1.5px ${C.rule}`,
                borderRadius: 99, padding: "10px 24px", opacity: clamp01(u * 1.5), translate: `0 ${(1 - u) * 24}px` }}>{name}</span>
            );
          })}
        </div>
        <div style={{ fontFamily: FONT.mono, fontSize: 38, color: C.accent, opacity: url, filter: url < 1 ? `blur(${(1 - url) * 8}px)` : undefined }}>
          github.com/deaglecodes/storage-steward
        </div>
      </div>
    </AbsoluteFill>
  );
}

/* ------------------------------------------------------------------ sound effects on cues */
const SFX: Array<[string, number, number]> = [
  ...Array.from(typing.scan.text, (_, i) => ["tick", typing.scan.start + i * typing.scan.step, 0.22] as [string, number, number]),
  ...Array.from(typing.sweep.text, (_, i) => ["tick", typing.sweep.start + i * typing.sweep.step, 0.16] as [string, number, number]),
  ["whoosh", b(12) - 0.35, 0.45],
  ["ping", b(15, 1), 0.22], ["ping", b(15, 3), 0.22], ["ping", b(16, 1), 0.22],
];

export const Launch = ({ debug }: LaunchProps) => {
  const t = useTime();
  const { fps } = useVideoConfig();
  return (
    <AbsoluteFill style={{ background: C.bg, color: C.ink, fontFamily: FONT.body }}>
      <LogoAct t={t} />
      <ProblemAct t={t} />
      <TerminalAct t={t} />
      <DropAct t={t} />
      <ProofAct t={t} />
      <EndAct t={t} />
      <Punchlines t={t} cards={CARDS} theme={{ font: FONT.display, color: C.ink, accent: C.accent, weight: 800 }} />
      <Html5Audio src={staticFile("audio/launch/music/launch.wav")} />
      {SFX.map(([name, at, volume], i) => (
        <Sequence key={i} from={Math.round(at * fps)} durationInFrames={Math.round(1 * fps)}>
          <Html5Audio src={staticFile(`audio/launch/sfx/${name}.wav`)} volume={volume} />
        </Sequence>
      ))}
      {debug ? <TargetLog /> : null}
    </AbsoluteFill>
  );
};
