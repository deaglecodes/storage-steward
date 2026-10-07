import { AbsoluteFill } from "remotion";

import { move, type Rect } from "../../kit/move";
import { step } from "../../kit/spring";
import { gbAt } from "../launch/data";
import { Mark } from "../launch/Logo";
import { C, FONT } from "../launch/tokens";
import { Headline } from "./acts2";
import { ASKS, b } from "./cues";
import { clamp01, ease, lerp, punch, Rgb, seg, Shockwave, slam } from "./fx";

/* ---------------------------------------------------------------- 7. your rules: plain English in, policy flips live */
const askAt = (k: number) => b(13 + k, 1, 0.5);
const runAt = (k: number) => b(13 + k, 3);
const savedAt = (k: number) => b(13 + k, 3, 0.6);
const ROW_Y = (i: number) => 316 + i * 88;
export const CHIP0 = { x: 1722, y: ROW_Y(0) + 40 };

type Row = { name: string; sub: string; when: string; tier: "AUTO" | "ASK" | "INFO" | "KEEP" | "OFF"; from?: number };
const TIER_COLOR: Record<Row["tier"], string> = { AUTO: C.keep, ASK: C.accent, INFO: C.muted, KEEP: C.ink, OFF: C.muted };

function Chip({ t, tier, from, at }: { t: number; tier: Row["tier"]; from?: Row["tier"]; at?: number }) {
  const flipping = from && at !== undefined;
  const u = flipping ? seg(t, at!, at! + 0.26) : 1;
  const show = flipping && u < 0.5 ? from! : tier;
  const col = TIER_COLOR[show];
  return (
    <span style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 21, letterSpacing: "0.06em", color: col, background: `${col}24`,
      padding: "6px 14px", borderRadius: 99, minWidth: 104, textAlign: "center", display: "inline-block",
      textDecoration: show === "OFF" ? "line-through" : undefined, scale: `1 ${Math.abs(Math.cos(Math.PI * u))}` }}>{show}</span>
  );
}

export function RulesAct({ t }: { t: number }) {
  if (t < b(12, 4) || t > b(17) + 0.05) return null;
  const enter = 2600 * (1 - ease.out3(seg(t, b(12, 4) + 0.06, b(13) + 0.12)));
  const zt = ease.inExpo(seg(t, b(16, 4), b(17)));
  const zoom = Math.exp(Math.log(36) * zt);
  const rows: Array<Row & { at?: number; was?: Row["tier"]; whenWas?: string }> = [
    { name: "Background task output", sub: "claude-task-output", when: t >= savedAt(3) ? "6h" : "1d", whenWas: "1d", tier: "AUTO", at: savedAt(3) },
    { name: "Desktop-app sandbox copies", sub: "desktop-sandbox-plugins", when: "3d", tier: "AUTO" },
    { name: "Claude transcripts", sub: "claude-transcripts", when: "30d", tier: t >= savedAt(0) + 0.13 ? "OFF" : "ASK", was: "ASK", at: savedAt(0) },
    { name: "node_modules of idle projects", sub: "stale-project-deps", when: "30d", tier: "ASK" },
    { name: "Local AI models", sub: "local-models", when: "—", tier: "INFO" },
    { name: "~/models · *.mov", sub: "keep list", when: "∞", tier: "KEEP", from: savedAt(1) },
    { name: "~/work/*/build", sub: "your rule: work-builds", when: "7d", tier: "AUTO", from: savedAt(2) },
  ];
  return (
    <AbsoluteFill style={{ translate: `${enter + (960 - CHIP0.x) * zt}px ${(540 - CHIP0.y) * zt}px`, transformOrigin: `${CHIP0.x}px ${CHIP0.y}px`, scale: `${zoom}` }}>
      <Headline t={t} words={[{ text: "Your", at: b(13, 1) }, { text: "rules.", at: b(13, 1, 0.5), hot: true },
        { text: "Your", at: b(13, 2) }, { text: "files.", at: b(13, 2, 0.5), hot: true }]} out={b(17) + 2} />
      {/* the agent: plain English in, one command out */}
      <div style={{ position: "absolute", left: 110, top: 232, width: 860, height: 690, background: C.term, borderRadius: 26, boxShadow: `0 0 0 1.5px ${C.termRule}`,
        padding: "24px 36px", fontFamily: FONT.mono, color: C.termFg, display: "grid", alignContent: "start", gap: 22 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 20, color: C.termMuted }}>
          {[0, 1, 2].map((i) => <i key={i} style={{ width: 12, height: 12, borderRadius: 9, background: C.termRule, display: "inline-block" }} />)}
          <span style={{ marginLeft: 8 }}>your agent · Claude Code, Codex, Cursor, Gemini…</span>
        </div>
        {ASKS.map((ask, k) => {
          if (t < askAt(k) - 0.01) return null;
          const typed = Math.max(0, Math.min(ask.say.length, Math.floor((t - askAt(k)) / 0.028) + 1));
          const ran = seg(t, runAt(k), runAt(k) + 0.14);
          const ok = seg(t, savedAt(k), savedAt(k) + 0.12);
          return (
            <div key={k} style={{ display: "grid", gap: 8 }}>
              <div style={{ fontSize: 31, fontFamily: FONT.body, fontWeight: 500 }}><span style={{ color: C.accent }}>› </span>{ask.say.slice(0, typed)}</div>
              <div style={{ fontSize: 18.5, color: C.termMuted, opacity: ran, filter: ran < 1 ? `blur(${(1 - ran) * 8}px)` : undefined, whiteSpace: "nowrap" }}>$ {ask.run}</div>
              <div style={{ fontSize: 20, color: C.keep, opacity: ok }}>✓ saved · the next sweep uses it</div>
            </div>
          );
        })}
      </div>
      {/* the policy, updating live */}
      <div style={{ position: "absolute", left: 1010, top: 232, width: 800, height: 690, background: C.surface, borderRadius: 26, boxShadow: `0 0 0 1.5px ${C.rule}` }}>
        <div style={{ position: "absolute", left: 30, top: 26, fontFamily: FONT.mono, fontSize: 20, color: C.muted }}>~/.config/storage-steward/config.json</div>
      </div>
      {rows.map((r, i) => {
        if (r.from !== undefined && t < r.from) return null;
        const inU = r.from !== undefined ? step(t - r.from, { stiffness: 190, damping: 18 }) : 1;
        const hi = r.at !== undefined && t >= r.at ? 1 - seg(t, r.at, r.at + 0.7) : r.from !== undefined ? 1 - seg(t, r.from, r.from + 0.8) : 0;
        const roll = r.whenWas && r.at !== undefined ? seg(t, r.at, r.at + 0.24) : 1;
        return (
          <div key={r.sub} style={{ position: "absolute", left: 1030, top: ROW_Y(i), width: 760, height: 80, borderRadius: 16, padding: "0 20px",
            display: "grid", gridTemplateColumns: "minmax(0,1fr) 84px auto", alignItems: "center", gap: 14,
            background: `rgba(110,162,255,${0.16 * hi})`, opacity: Math.min(1, inU * 1.5), translate: `${(1 - inU) * 140}px 0` }}>
            <div style={{ display: "grid", gap: 2 }}>
              <span style={{ fontFamily: FONT.body, fontWeight: 600, fontSize: 27, color: C.ink, whiteSpace: "nowrap" }}>{r.name}</span>
              <span style={{ fontFamily: FONT.mono, fontSize: 18, color: C.muted }}>{r.sub}</span>
            </div>
            <span style={{ fontFamily: FONT.mono, fontWeight: 600, fontSize: 24, color: C.ink2, textAlign: "right", height: 30, overflow: "hidden", position: "relative" }}>
              {r.whenWas && roll < 1 ? (
                <>
                  <span style={{ position: "absolute", right: 0, translate: `0 ${-30 * roll}px`, opacity: 1 - roll }}>{r.whenWas}</span>
                  <span style={{ position: "absolute", right: 0, translate: `0 ${30 * (1 - roll)}px`, opacity: roll, color: C.keep }}>{r.when}</span>
                </>
              ) : <span style={{ color: r.whenWas && t >= (r.at ?? 0) ? C.keep : undefined }}>{r.when}</span>}
            </span>
            <Chip t={t} tier={r.tier} from={r.was} at={r.was ? r.at : undefined} />
          </div>
        );
      })}
    </AbsoluteFill>
  );
}

/* ---------------------------------------------------------------- 8. the drop: the 60-day chart, then the proof slams */
const X0 = 190, X1 = 1720, Y0 = 200, Y1 = 900;
const px = (day: number) => X0 + ((day - 1) / 59) * (X1 - X0);
export const FULL_HIT = b(18, 3);   // day 60 lands here; the no-cleanup line is at 1 TB by then
const py = (gb: number) => Y1 - (Math.min(gb, 1000) / 1000) * (Y1 - Y0);
const PROOF = [
  { n: "85%", l: "less disk used", c: C.accent }, { n: "0", l: "files lost", c: C.keep },
  { n: "72%", l: "fewer tokens", c: C.accent }, { n: "0", l: "commands to type", c: C.ink },
];
const TILE = (k: number): Rect => ({ x: 230 + (k % 2) * 760, y: 170 + Math.floor(k / 2) * 390, w: 700, h: 340 });
const FULL: Rect = { x: 0, y: 0, w: 1920, h: 1080 };
const FROM: Rect[] = [{ x: -1400, y: -600, w: 1920, h: 1080 }, { x: 1400, y: -900, w: 1920, h: 1080 }, { x: -1600, y: 900, w: 1920, h: 1080 }, FULL];

function ProofTile({ k, r, bg }: { k: number; r: Rect; bg: number }) {
  const s = r.w / 700;
  const p = PROOF[k];
  return (
    <div style={{ position: "absolute", left: r.x, top: r.y, width: r.w, height: r.h, borderRadius: 28 * s, background: `rgba(16,25,38,${bg})`,
      boxShadow: bg > 0.05 ? `0 0 0 ${1.5 * s}px rgba(31,44,62,${bg})` : undefined }}>
      <div style={{ position: "absolute", left: 0, top: 0, width: 700, height: 340, scale: `${s}`, transformOrigin: "0 0", display: "grid", placeItems: "center", alignContent: "center", gap: 6 }}>
        <b style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 168, lineHeight: 0.95, letterSpacing: "-0.05em", color: p.c }}>{p.n}</b>
        <span style={{ fontFamily: FONT.display, fontWeight: 600, fontSize: 36, color: C.ink2 }}>{p.l}</span>
      </div>
    </div>
  );
}

export function ProofAct({ t }: { t: number }) {
  if (t < b(17) - 0.02 || t > b(21) + 0.4) return null;
  const chart = 1 - seg(t, b(19) - 0.06, b(19));
  const d = 1 + 59 * ease.inOut3(seg(t, b(17), b(18, 3)));
  const scale = lerp(1.2, 1, ease.out3(seg(t, b(17), b(18, 4))));
  const line = (policy: "none" | "steward") => {
    const pts: string[] = [];
    for (let day = 1; day <= Math.floor(d); day++) pts.push(`${px(day)},${py(gbAt("runaway", policy, day))}`);
    pts.push(`${px(d)},${py(gbAt("runaway", policy, d))}`);
    return pts.join(" ");
  };
  const none = gbAt("runaway", "none", d), kept = gbAt("runaway", "steward", d);
  const full = none >= 1000;
  const stamp = slam(t, FULL_HIT, 0.18, 2.4);
  // the steward label rides above the stretch of its own line it covers (spikes included), easing in so it never jumps
  const labelX = Math.min(px(d) + 26, 1470);
  let labelTop = py(kept) - 64;
  for (let day = 1; day <= 60; day++) {
    const x = px(day);
    const covered = clamp01(Math.min((x - (labelX - 30)) / 40, (labelX + 440 - x) / 40)) * clamp01(d - (day - 1));
    labelTop = Math.min(labelTop, py(gbAt("runaway", "steward", day)) - 60 + (1 - covered) * 800);
  }
  return (
    <AbsoluteFill>
      {chart > 0 ? (
        <AbsoluteFill style={{ opacity: chart, scale: `${scale}` }}>
          <div style={{ position: "absolute", left: X0, top: 70, fontFamily: FONT.display, fontWeight: 800, fontSize: 60, letterSpacing: "-0.03em" }}>
            60 days of heavy agent use<span style={{ fontFamily: FONT.mono, fontWeight: 400, fontSize: 24, color: C.muted, marginLeft: 20, letterSpacing: 0 }}>simulated · 1 TB drive</span></div>
          <div style={{ position: "absolute", right: 200, top: 64, fontFamily: FONT.mono, fontSize: 52, color: C.ink, fontVariantNumeric: "tabular-nums" }}>day {Math.floor(d)}</div>
          {/* axis labels are HTML, not SVG <text>: Chrome keeps SVG text laid out at a stale scale while an ancestor's CSS scale animates */}
          {[0, 250, 500, 750, 1000].map((g) => (
            <div key={g} style={{ position: "absolute", right: 1920 - (X0 - 18), top: py(g) - 13, lineHeight: "26px", fontFamily: FONT.mono, fontSize: 20,
              color: C.muted, whiteSpace: "nowrap" }}>{g === 1000 ? "1 TB" : `${g} GB`}</div>
          ))}
          <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, overflow: "visible" }}>
            {[0, 250, 500, 750, 1000].map((g) => <line key={g} x1={X0} x2={X1} y1={py(g)} y2={py(g)} stroke={C.rule} strokeWidth={2} />)}
            <polyline points={line("none")} fill="none" stroke={C.nuke} strokeWidth={7} strokeLinejoin="round" />
            <polyline points={line("steward")} fill="none" stroke={C.accentHi} strokeWidth={7} strokeLinejoin="round" />
            <circle cx={px(d)} cy={py(none)} r={12} fill={C.nuke} />
            <circle cx={px(d)} cy={py(kept)} r={12} fill={C.accentHi} />
          </svg>
          {!full ? (
            <div style={{ position: "absolute", left: Math.min(px(d) + 26, 1540), top: py(none) - 34, fontFamily: FONT.display, fontWeight: 800,
              fontSize: 34, color: C.nuke, whiteSpace: "nowrap", opacity: 1 - seg(d, 53, 55) }}>no cleanup · {Math.round(none)} GB</div>
          ) : null}
          <div style={{ position: "absolute", left: labelX, top: labelTop, fontFamily: FONT.display, fontWeight: 800, fontSize: 34, color: C.accent, whiteSpace: "nowrap" }}>
            storage-steward · {Math.round(kept)} GB</div>
          {/* the no-cleanup line hits 1 TB: stamp it into the empty corner of the chart, on the beat */}
          <Shockwave t={t} at={FULL_HIT} x={px(60)} y={py(1000)} color={C.nuke} max={320} len={0.5} width={8} />
          {stamp.visible ? (
            <div style={{ position: "absolute", left: 360, width: 800, top: 282, textAlign: "center", fontFamily: FONT.display, fontWeight: 800, fontSize: 132,
              letterSpacing: "-0.04em", color: C.nuke, rotate: "-5deg", opacity: stamp.opacity, scale: `${stamp.scale}`,
              filter: stamp.blur > 0.3 ? `blur(${stamp.blur}px)` : undefined }}>DISK FULL</div>
          ) : null}
        </AbsoluteFill>
      ) : null}
      {t < b(17) + 0.32 ? <AbsoluteFill style={{ background: C.keep, opacity: 1 - seg(t, b(17), b(17) + 0.3) }} /> : null}
      {/* bar 19: one number per beat, full screen */}
      {[0, 1, 2, 3].map((k) => {
        const at = b(19, k + 1);
        if (t < at || (k < 3 && t >= b(19, k + 2))) return null;
        if (t >= b(20)) return null;
        return (
          <AbsoluteFill key={k} style={{ scale: `${punch(t, at, 0.24, 0.32)}`,
            translate: `${Math.sin(t * 101) * 16 * (1 - seg(t, at, at + 0.2))}px ${Math.cos(t * 89) * 16 * (1 - seg(t, at, at + 0.2))}px` }}>
            <Rgb t={t} at={at} amount={22}><ProofTile k={k} r={FULL} bg={0} /></Rgb>
          </AbsoluteFill>
        );
      })}
      {/* bar 20: the four assemble into a grid, then collapse into the logo */}
      {t >= b(20) ? [0, 1, 2, 3].map((k) => {
        const r0 = move(t, b(20) + k * 0.05, FROM[k], TILE(k), { stiffness: 160, damping: 20 });
        const c = ease.in3(seg(t, b(20, 4) + k * 0.03, b(21) + 0.18 + k * 0.03));
        const tile = TILE(k);
        const r = c > 0 ? { x: lerp(r0.x, 960 - tile.w * 0.05, c), y: lerp(r0.y, 540 - tile.h * 0.05, c), w: lerp(r0.w, tile.w * 0.1, c), h: lerp(r0.h, tile.h * 0.1, c) } : r0;
        return <div key={k} style={{ opacity: 1 - c, rotate: `${c * (k % 2 ? 30 : -30)}deg`, position: "absolute", inset: 0 }}><ProofTile k={k} r={r} bg={seg(t, b(20) + 0.1, b(20) + 0.4)} /></div>;
      }) : null}
    </AbsoluteFill>
  );
}

/* ---------------------------------------------------------------- 9. the end: lockup, the promise, every agent, the URL */
const AGENT_CHIPS = ["Claude Code", "Codex", "Cursor", "Gemini CLI", "+ any SKILL.md agent"];

export function EndAct({ t }: { t: number }) {
  if (t < b(20, 4) + 0.1) return null;
  const word = slam(t, b(21, 3), 0.18, 1.35);
  const url = seg(t, b(23, 3), b(23, 3) + 0.25);
  return (
    <AbsoluteFill>
      <Shockwave t={t} at={b(21, 2)} x={370} y={420} max={1300} len={0.9} />
      <Shockwave t={t} at={b(24)} x={370} y={420} max={1700} len={1.1} color={C.keep} width={8} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 420, translate: "0 -50%", display: "flex", justifyContent: "center", alignItems: "center", gap: 44 }}>
        <Mark t={t} draw0={b(21, 1)} pop0={b(21, 2)} size={230} />
        <div style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 150, letterSpacing: "-0.045em", color: C.ink,
          opacity: word.visible ? word.opacity : 0, scale: `${word.scale}`, filter: word.blur > 0.3 ? `blur(${word.blur}px)` : undefined }}>storage-steward</div>
      </div>
      <Headline t={t} y={620} size={84} out={99} words={[{ text: "Set", at: b(21, 4) }, { text: "it", at: b(21, 4, 0.5) }, { text: "once.", at: b(22, 1) },
        { text: "Never", at: b(22, 2) }, { text: "clean", at: b(22, 2, 0.5) }, { text: "again.", at: b(22, 3), hot: true }]} />
      <div style={{ position: "absolute", left: 0, right: 0, top: 770, display: "flex", justifyContent: "center", gap: 16 }}>
        {AGENT_CHIPS.map((name, i) => {
          const u = step(t - b(22, 4, i * 0.5), { stiffness: 230, damping: 17 });
          return <span key={name} style={{ fontFamily: FONT.body, fontWeight: 600, fontSize: 32, color: i === 4 ? C.accent : C.ink2, background: C.surface,
            boxShadow: `0 0 0 1.5px ${C.rule}`, borderRadius: 999, padding: "12px 28px", opacity: Math.min(1, u * 1.5), translate: `0 ${(1 - u) * 40}px` }}>{name}</span>;
        })}
      </div>
      <div style={{ position: "absolute", left: 0, right: 0, top: 900, textAlign: "center", fontFamily: FONT.mono, fontSize: 44, color: C.accent,
        opacity: url, filter: url < 1 ? `blur(${(1 - url) * 10}px)` : undefined }}>github.com/deaglecodes/storage-steward</div>
    </AbsoluteFill>
  );
}
