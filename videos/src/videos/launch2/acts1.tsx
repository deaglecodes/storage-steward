import { AbsoluteFill } from "remotion";

import { step } from "../../kit/spring";
import { C, FONT } from "../launch/tokens";
import { b, BEAT } from "./cues";
import { ease, lerp, punch, Rgb, seg, slam, Slices, Platter } from "./fx";
import { AgentWindow, FileChip, Gauge, LEFTOVERS } from "./parts";

const G = { x: 1748, y: 168 };                           // the disk gauge, where everything gets sucked in
const WIN = [{ x: 545, y: 300 }, { x: 1295, y: 300 }, { x: 545, y: 700 }, { x: 1295, y: 700 }];
const AGENTS = ["Claude Code", "Codex", "Cursor", "Gemini CLI"];

/* ---------------------------------------------------------------- 1. the pile-up, then everything gets sucked into the gauge */
export function OpenAct({ t }: { t: number }) {
  if (t > b(3) + 0.06) return null;
  const pushIn = 1 + 0.06 * ease.inOut3(seg(t, 0, b(2, 4)));
  const suckRaw = seg(t, b(2, 4), b(3));
  const suck = ease.inExpo(suckRaw);
  const zoom = Math.exp(Math.log(16) * suck);
  const pct = 61 + 35 * ease.inOut3(seg(t, 0.2, b(2, 3)));
  const warn = pct > 93;
  return (
    <AbsoluteFill style={{ transformOrigin: `${G.x}px ${G.y}px`, opacity: 1 - seg(t, b(3) - 0.05, b(3) + 0.05),
      transform: `translate(${(960 - G.x) * suck}px, ${(540 - G.y) * suck}px) scale(${pushIn * zoom})` }}>
      <Platter t={t} opacity={0.35} />
      <div style={{ position: "absolute", left: 95, top: 125, width: 1500, height: 800, perspective: 2200 }}>
        <div style={{ position: "absolute", inset: 0, transformStyle: "preserve-3d",
          transform: `rotateX(15deg) rotateY(${-15 + 5 * seg(t, 0, b(3))}deg) rotateZ(1.5deg)` }}>
          {AGENTS.map((name, i) => (
            <AgentWindow key={name} name={name} t={t + i * 0.37} speed={6 + i * 1.3}
              style={{ position: "absolute", left: (i % 2) * 750, top: Math.floor(i / 2) * 400, width: 710, height: 360,
                opacity: 1 - suck * 0.8 }} />
          ))}
        </div>
      </div>
      {Array.from({ length: 30 }, (_, i) => {
        const s = 0.15 + i * 0.104;
        if (t < s) return null;
        const src = WIN[(i * 3) % 4];
        const row = Math.floor(i / 5);
        const col = i % 5;
        const dst = { x: 262 + col * 334 + (row % 2) * 150, y: 1000 - row * 48 };   // 5 per row, still inside the frame after the push-in
        const u = step(t - s, { stiffness: 150, damping: 15 });
        let x = lerp(src.x, dst.x, u);
        let y = lerp(src.y, dst.y, u) - 170 * Math.sin(Math.PI * Math.min(1, u));
        const pull = ease.in3(suckRaw);
        x = lerp(x, G.x, pull);
        y = lerp(y, G.y, pull);
        return <FileChip key={i} text={LEFTOVERS[i % LEFTOVERS.length]}
          style={{ left: x, top: y, translate: "-50% -50%", fontSize: 18, padding: "6px 12px", scale: `${lerp(0.5, 1, Math.min(1, u)) * (1 - 0.8 * pull)}`, opacity: Math.min(1, u * 3) }} />;
      })}
      <Gauge pct={pct} size={230} x={G.x} y={G.y} label="disk" />
      {warn ? (
        <div style={{ position: "absolute", left: G.x - 120, top: G.y + 140, width: 240, textAlign: "center", fontFamily: FONT.mono, fontSize: 22,
          color: C.nuke, opacity: Math.floor(t / (BEAT / 2)) % 2 ? 1 : 0.35 }}>ALMOST FULL</div>
      ) : null}
    </AbsoluteFill>
  );
}

/* ---------------------------------------------------------------- 2. punchline inside the full disk, then it slices apart */
const P1: Array<Array<{ text: string; at: number; hot?: boolean }>> = [
  [{ text: "Your", at: b(3, 1) }, { text: "agents", at: b(3, 2) }, { text: "leave", at: b(3, 3) }],
  [{ text: "files", at: b(3, 4), hot: true }, { text: "behind.", at: b(4, 1), hot: true }],
];

export function PunchAct({ t }: { t: number }) {
  if (t < b(3) - 0.05 || t > b(5) + 0.02) return null;
  const ring = lerp(5.5, 1, ease.outExpo(seg(t, b(3), b(3) + 0.5)));
  const dim = lerp(0.55, 0.2, seg(t, b(3, 3), b(4, 1)));      // keep the words readable
  const scale = punch(t, b(4, 1), 0.09) * (1 + 0.05 * seg(t, b(4, 1), b(4, 4)));
  const frame = (
    <AbsoluteFill style={{ display: "grid", placeItems: "center" }}>
      <div style={{ position: "absolute", left: 960 - 430, top: 540 - 430, width: 860, height: 860, scale: `${ring}`, rotate: `${t * 12}deg`, opacity: dim }}>
        <Gauge pct={96} size={860} x={430} y={430} stroke={26} showText={false} />
      </div>
      <div style={{ display: "grid", gap: 0, justifyItems: "center", scale: `${scale}` }}>
        {P1.map((line, r) => (
          <div key={r} style={{ display: "flex", gap: "0.24em", fontFamily: FONT.display, fontWeight: 800, fontSize: 176, lineHeight: 1.02, letterSpacing: "-0.04em" }}>
            {line.map((w) => {
              const s = slam(t, w.at);
              return <span key={w.text} style={{ display: "inline-block", color: w.hot ? C.nuke : C.ink, opacity: s.visible ? s.opacity : 0,
                scale: `${s.scale}`, filter: s.blur > 0.3 ? `blur(${s.blur}px)` : undefined }}>{w.text}</span>;
            })}
          </div>
        ))}
      </div>
    </AbsoluteFill>
  );
  return <AbsoluteFill><Slices t={t} at={b(4, 4)} n={9}>{frame}</Slices></AbsoluteFill>;
}

/* ---------------------------------------------------------------- 3. the daily chore: four hard cuts, then a tape stop */
const DAY = ["MON", "TUE", "WED", "THU"];
const WORD = ["Every.", "single.", "day.", "Again."];
const CMD = ["rm -rf ~/.npm/_npx", "rm -rf /private/tmp/claude-501/*", "rm -rf …/local-agent-mode-sessions/*", "df -h /"];
const OUT: Array<[string, string]> = [["freed 2.1 GB · back by tomorrow", C.termMuted], ["freed 21 GB · back by tomorrow", C.termMuted],
  ["✗ also deleted outputs/Q3-report.pdf", C.nuke], ["/dev/disk3s5   97% full", C.nuke]];

export function ChoreAct({ t }: { t: number }) {
  if (t < b(5) - 0.02 || t > b(6) + 0.5) return null;
  const tl = Math.min(t, b(6) - 0.001);
  const k = Math.max(0, Math.min(3, Math.floor((tl - b(5)) / BEAT)));
  const ck = b(5, k + 1);
  const typed = Math.max(0, Math.min(CMD[k].length, Math.floor((tl - ck) / 0.0055) + 1));
  const stop = ease.in3(seg(t, b(6), b(6) + 0.47));
  const rot = (k % 2 ? 1 : -1) * 1.6 * (1 - seg(tl, ck, ck + 0.3));
  const shake = (1 - seg(tl, ck, ck + 0.18)) * 14;
  return (
    <AbsoluteFill style={{ scale: `${(1 - 0.45 * stop) * punch(tl, ck, 0.13, 0.3)}`, rotate: `${rot}deg`,
      translate: `${Math.sin(tl * 97) * shake}px ${150 * stop + Math.cos(tl * 83) * shake}px`,
      filter: stop > 0 ? `saturate(${1 - stop}) blur(${16 * stop}px)` : undefined, opacity: 1 - stop }}>
      <div style={{ position: "absolute", left: 80, top: 120, fontFamily: FONT.display, fontWeight: 800, fontSize: 300, lineHeight: 1,
        color: "transparent", WebkitTextStroke: `3px ${C.ink2}55`, letterSpacing: "-0.03em" }}>{DAY[k]}</div>
      <Rgb t={tl} at={ck} amount={18}>
        <div style={{ position: "absolute", right: 110, top: 215, fontFamily: FONT.display, fontWeight: 800, fontSize: 168,
          color: k === 3 ? C.nuke : C.ink, letterSpacing: "-0.04em" }}>{WORD[k]}</div>
      </Rgb>
      <div style={{ position: "absolute", left: 460, top: 560, width: 1340, background: C.term, borderRadius: 24, boxShadow: `0 0 0 1.5px ${C.termRule}`,
        padding: "30px 44px", fontFamily: FONT.mono, color: C.termFg, display: "grid", gap: 18 }}>
        <div style={{ fontSize: 40, whiteSpace: "nowrap" }}><span style={{ color: C.termMuted }}>$ </span>{CMD[k].slice(0, typed)}</div>
        <div style={{ fontSize: 34, color: OUT[k][1], opacity: seg(tl, ck + 0.22, ck + 0.3) }}>{OUT[k][0]}</div>
      </div>
    </AbsoluteFill>
  );
}
