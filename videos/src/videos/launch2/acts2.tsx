import { AbsoluteFill } from "remotion";

import { step } from "../../kit/spring";
import { Mark } from "../launch/Logo";
import { C, FONT } from "../launch/tokens";
import { b, BEAT, HUB, NODES, PULSE, SWEEPS } from "./cues";
import { ease, lerp, Platter, seg, Shockwave, slam } from "./fx";
import { FileChip, Gauge, mix, orbit } from "./parts";

const DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const JUNK = ["tasks/*.output", "node_modules", "local_*/.claude", "rollout.jsonl", ".npm/_npx", "DerivedData", "file-history", "tmp.agent3"];

type W = { text: string; at: number; hot?: boolean };
export function Headline({ t, words, out, y = 118, size = 96 }: { t: number; words: W[]; out: number; y?: number; size?: number }) {
  if (t < words[0].at - 0.02 || t > out + 0.2) return null;
  const leave = seg(t, out, out + 0.16);
  return (
    <div style={{ position: "absolute", left: 0, right: 0, top: y, translate: "0 -50%", display: "flex", justifyContent: "center", gap: "0.24em",
      fontFamily: FONT.display, fontWeight: 800, fontSize: size, letterSpacing: "-0.035em", opacity: 1 - leave, filter: leave ? `blur(${leave * 14}px)` : undefined }}>
      {words.map((w) => {
        const s = slam(t, w.at, 0.14, 1.5);
        return <span key={w.text + w.at} style={{ display: "inline-block", color: w.hot ? C.accent : C.ink, opacity: s.visible ? s.opacity : 0,
          scale: `${s.scale}`, filter: s.blur > 0.3 ? `blur(${s.blur}px)` : undefined }}>{w.text}</span>;
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- 4-6. turn, install once, then it just runs */
export function HubAct({ t }: { t: number }) {
  if (t < b(6, 2) - 0.05 || t > b(13) + 0.05) return null;
  const whip = ease.in3(seg(t, b(12, 4), b(13)));
  const pull = 1 - 0.06 * ease.inOut3(seg(t, b(9), b(9, 3)));
  const pump = t >= b(9) && t < b(12, 4) ? 1 + 0.012 * Math.exp(-((t - b(9)) % BEAT) * 14) : 1;   // the scene breathes on every kick
  const auto = seg(t, b(9) - 0.25, b(9) + 0.1);
  const arrivals = SWEEPS.map(([e]) => e + PULSE);
  const bump = arrivals.reduce((m, a) => Math.max(m, t >= a ? Math.pow(1 - seg(t, a, a + 0.25), 2) : 0), 0);
  const logo = lerp(300, 200, ease.out3(seg(t, b(7, 1), b(7, 2)))) * (1 + 0.12 * bump);
  // disk ring: creeps up as agents work, snaps back at every sweep
  const done = arrivals.filter((a) => a <= t);
  const last = done.length ? done[done.length - 1] : b(9) - 1.5;
  const next = arrivals.find((a) => a > t) ?? b(13);
  const pct = 41 + 9 * seg(t, last, next);
  const freedBefore = SWEEPS.slice(0, Math.max(0, done.length - 1)).reduce((s, [, , g]) => s + g, 0);
  const lastGb = done.length ? SWEEPS[done.length - 1][2] : 0;
  const freed = freedBefore + lastGb * ease.out3(seg(t, last, last + 0.35));
  const hours = 9 + 158 * seg(t, b(9), b(13));
  const clock = `${DAYS[Math.min(6, Math.floor(hours / 24))]} ${String(Math.floor(hours % 24)).padStart(2, "0")}:${String(Math.floor((hours * 60) % 60)).padStart(2, "0")}`;

  return (
    <AbsoluteFill style={{ translate: `${-2600 * whip}px 0`, scale: `${pull * pump}` }}>
      <Platter t={t} opacity={0.5 * seg(t, b(6, 4), b(7))} spin={4} />
      {/* connectors */}
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0 }}>
        {NODES.map((n, k) => {
          const na = b(7, 3) + k * 0.117;
          return <line key={k} x1={HUB.x} y1={HUB.y} x2={n.x} y2={n.y} stroke={C.termRule} strokeWidth={4} pathLength={1}
            strokeDasharray="1 1" strokeDashoffset={1 - ease.out3(seg(t, na, na + 0.35))} />;
        })}
        {SWEEPS.map(([e, k], i) => {
          if (t < e || t > e + PULSE) return null;
          const p = ease.in3(seg(t, e, e + PULSE));
          const n = NODES[k];
          const x = lerp(n.x, HUB.x, p), y = lerp(n.y, HUB.y, p);
          const tx = lerp(n.x, HUB.x, Math.max(0, p - 0.25)), ty = lerp(n.y, HUB.y, Math.max(0, p - 0.25));
          return (
            <g key={i}>
              <line x1={tx} y1={ty} x2={x} y2={y} stroke={C.keep} strokeWidth={8} strokeLinecap="round" opacity={0.6} />
              <circle cx={x} cy={y} r={11} fill={C.keep} />
            </g>
          );
        })}
      </svg>
      {/* disk ring around the hub during the time-lapse */}
      <div style={{ opacity: auto }}>
        <Gauge pct={pct} size={500} x={HUB.x} y={HUB.y} stroke={16} showText={false} />
        <div style={{ position: "absolute", left: HUB.x - 150, width: 300, top: HUB.y + 262, textAlign: "center", fontFamily: FONT.mono, fontSize: 24, color: C.muted }}>
          disk {Math.round(pct)}% · steady
        </div>
      </div>
      {/* hub */}
      <div style={{ position: "absolute", left: HUB.x - logo / 2, top: HUB.y - logo / 2 }}>
        <Mark t={t} draw0={b(6, 2)} pop0={b(6, 4)} size={logo} />
      </div>
      <Shockwave t={t} at={b(6, 4)} x={HUB.x} y={HUB.y} max={1150} len={0.8} />
      <Shockwave t={t} at={b(7, 3)} x={HUB.x} y={HUB.y} max={900} len={0.6} color={C.keep} />
      {arrivals.map((a, i) => <Shockwave key={i} t={t} at={a} x={HUB.x} y={HUB.y} max={230} len={0.45} width={5} color={C.keep} />)}
      {/* agent nodes */}
      {NODES.map((n, k) => {
        const na = b(7, 3) + k * 0.117;
        if (t < na) return null;
        const u = step(t - na, { stiffness: 210, damping: 16 });
        const hk = b(8, k + 1);
        const hooked = seg(t, hk, hk + 0.15);
        const flash = SWEEPS.reduce((m, [e, kk]) => (kk === k && t >= e ? Math.max(m, 1 - seg(t, e, e + 0.45)) : m), 0);
        return (
          <div key={n.name} style={{ position: "absolute", left: n.x - 200, top: n.y - 66, width: 400, height: 132, borderRadius: 22,
            background: C.surface, boxShadow: `0 0 0 ${1.5 + 3 * flash}px ${mix(C.rule, C.keep, Math.max(hooked * 0.35, flash))}, 0 24px 50px -20px rgba(0,0,0,0.7)`,
            scale: `${lerp(0.5, 1, u)}`, opacity: Math.min(1, u * 1.6), padding: "22px 26px", display: "grid", gap: 8, alignContent: "center" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <b style={{ fontFamily: FONT.body, fontWeight: 600, fontSize: 34, color: C.ink }}>{n.name}</b>
              <span style={{ width: 34, height: 34, borderRadius: 99, background: C.keep, color: C.bg, display: "grid", placeItems: "center",
                fontSize: 22, fontWeight: 800, scale: `${step(t - hk, { stiffness: 260, damping: 14 })}` }}>✓</span>
            </div>
            <span style={{ fontFamily: FONT.mono, fontSize: 20, color: C.muted, opacity: hooked }}>hooks: {n.hooks}</span>
          </div>
        );
      })}
      {/* junk orbiting each agent, pulled in and dissolved by every sweep */}
      {SWEEPS.map(([e, k], i) => {
        const prev = SWEEPS.slice(0, i).reverse().find(([, kk]) => kk === k);
        const start = prev ? prev[0] + PULSE : b(9) - 0.3;
        const arrive = e + PULSE;
        if (t < start || t > arrive + 0.25) return null;
        const n = NODES[k];
        return [0, 1, 2].map((j) => {
          const s = start + (e - start) * (j + 1) / 4;
          if (t < s) return null;
          const o = orbit(i * 10 + j, t, 150);
          const grow = ease.out3(seg(t, s, s + 0.2));
          const d = seg(t, e, arrive + 0.15);
          const dir = n.y < HUB.y ? 1 : -1;                                     // junk floats in the gap between the card rows
          const xb = n.x + [-125, 125, 0][j] + o.dx * 0.08;                      // staggered slots: chips never touch each other
          const yb = n.y + dir * (104 + 40 * j) + o.dy * 0.04;
          return <FileChip key={`${i}-${j}`} text={JUNK[(i + j) % JUNK.length]}
            style={{ left: lerp(xb, n.x, d), top: lerp(yb, n.y, d), translate: "-50% -50%", fontSize: 17, padding: "5px 11px",
              scale: `${grow * (1 - d)}`, opacity: grow * (1 - d), filter: d > 0 ? `blur(${10 * d}px)` : undefined }} />;
        });
      })}
      {SWEEPS.map(([e, k, gb], i) => {
        const nextSame = SWEEPS.slice(i + 1).find(([, kk]) => kk === k)?.[0] ?? Infinity;
        const end = Math.min(e + 0.9, nextSame);
        if (t < e || t > end) return null;
        const n = NODES[k];
        const dir = n.y < HUB.y ? -1 : 1;                                       // outside the card rows: above the top cards, below the bottom ones
        const pop = ease.outBack(seg(t, e, e + 0.22));
        return (
          <div key={i} style={{ position: "absolute", left: n.x - 260, width: 520, height: 48, top: n.y + dir * 108 - 24 + dir * 8 * seg(t, e, end),
            display: "flex", alignItems: "center", justifyContent: "center", gap: 16, color: C.keep,
            scale: `${lerp(0.7, 1, pop)}`, opacity: Math.min(1, pop * 2) * (1 - seg(t, end - 0.2, end)) }}>
            <span style={{ fontFamily: FONT.mono, fontSize: 20 }}>session ended → swept</span>
            <b style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 40 }}>+{gb.toFixed(1)} GB</b>
          </div>
        );
      })}
      {/* install command */}
      {t >= b(7) - 0.05 && t < b(9) + 0.3 ? (
        <div style={{ position: "absolute", left: HUB.x - 360, top: 860, width: 720, background: C.term, borderRadius: 20, boxShadow: `0 0 0 1.5px ${C.termRule}`,
          padding: "20px 30px", fontFamily: FONT.mono, display: "grid", gap: 8, opacity: (1 - seg(t, b(9), b(9) + 0.3)) * seg(t, b(7) - 0.05, b(7) + 0.1) }}>
          <div style={{ fontSize: 34, color: C.termFg }}><span style={{ color: C.termMuted }}>$ </span>{"./install.sh".slice(0, Math.max(0, Math.floor((t - b(7) - 0.05) / 0.05) + 1))}</div>
          <div style={{ fontSize: 24, color: C.keep, opacity: seg(t, b(7, 3) + 0.08, b(7, 3) + 0.2) }}>✓ 4 agents found · hooks added and tested</div>
        </div>
      ) : null}
      {/* headlines */}
      <Headline t={t} words={[{ text: "Install", at: b(7, 3) }, { text: "once.", at: b(7, 4), hot: true }]} out={b(9) - 0.18} />
      <Headline t={t} words={[{ text: "It", at: b(9, 1) }, { text: "cleans", at: b(9, 1, 0.5) }, { text: "up", at: b(9, 2) },
        { text: "by", at: b(9, 2, 0.5) }, { text: "itself.", at: b(9, 3), hot: true }]} out={b(11) - 0.16} />
      {t >= b(11) - 0.05 && t < b(12) ? (
        <div style={{ position: "absolute", left: 0, right: 0, top: 118, translate: "0 -50%", display: "flex", justifyContent: "center", gap: 22,
          opacity: 1 - seg(t, b(12) - 0.16, b(12)) }}>
          {["0 commands typed", "0 tokens per prompt", "61 ms hook"].map((label, i) => {
            const s = slam(t, b(11, i + 1), 0.14, 1.4);
            return <span key={label} style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 54, color: C.ink, background: C.surface, borderRadius: 999,
              padding: "12px 30px", boxShadow: `0 0 0 1.5px ${C.rule}`, opacity: s.visible ? s.opacity : 0, scale: `${s.scale}` }}>
              <span style={{ color: C.keep }}>{label.split(" ")[0]}</span> {label.split(" ").slice(1).join(" ")}</span>;
          })}
        </div>
      ) : null}
      <Headline t={t} words={[{ text: "Every", at: b(12, 1) }, { text: "session.", at: b(12, 1, 0.5) }, { text: "Every", at: b(12, 2) },
        { text: "agent.", at: b(12, 2, 0.5), hot: true }]} out={b(13) + 1} />
      {/* HUD */}
      <div style={{ opacity: auto }}>
        <div style={{ position: "absolute", left: 70, top: 980, fontFamily: FONT.mono }}>
          <div style={{ fontSize: 18, color: C.muted, letterSpacing: "0.1em" }}>TIME-LAPSE</div>
          <div style={{ fontSize: 44, color: C.ink, fontVariantNumeric: "tabular-nums" }}>{clock}</div>
        </div>
        <div style={{ position: "absolute", right: 70, top: 975, textAlign: "right" }}>
          <div style={{ fontFamily: FONT.mono, fontSize: 18, color: C.muted, letterSpacing: "0.1em" }}>RECLAIMED, NOBODY ASKED</div>
          <div style={{ fontFamily: FONT.display, fontWeight: 800, fontSize: 56, color: C.keep, fontVariantNumeric: "tabular-nums", lineHeight: 1.05 }}>{freed.toFixed(1)} GB</div>
        </div>
      </div>
    </AbsoluteFill>
  );
}
