import { AbsoluteFill } from "remotion";

import { Mark } from "../launch/Logo";
import { ease, lerp, rng, seg } from "../launch2/fx";
import {
  b, BAR, BG_SWEEP_LEN, BG_SWEEPS, CMD, RUN, SAY, SCENE, SESSION_LEN, SESSIONS, TYPE_CMD, TYPE_RUN, TYPE_SAY, W, WIPE, X0,
} from "./cues";
import { arrive, buildMess, Caret, CHAR, Exit, JunkItem, Status, SweepLine, typed, Words } from "./parts";
import { F, L } from "./theme";

const HEAD = { position: "absolute", left: X0, top: 250, fontFamily: F.display, fontWeight: 800, fontSize: 130, lineHeight: 1,
  letterSpacing: "-0.045em", color: L.ink } as const;
const LINE = { position: "absolute", left: X0, margin: 0, fontFamily: F.body, fontSize: 48, color: L.muted } as const;
const live = (t: number, [start, exit]: readonly [number, number]) => t >= start - 0.01 && t <= exit + WIPE;

/* ---------------------------------------------------------------- 1. agents leave files behind, then the sweep (bars 1-4) */
const MESS_TOP = 392;
const MESS = buildMess(23, [{ l: 110, r: 1660, t: MESS_TOP - 40, b: MESS_TOP + 330 }, { l: 0, r: W, t: 945, b: 1080 }], 0.25, b(3) - 0.15);
const SWEEP_AT = b(4);
const messX = (t: number) => (t < SWEEP_AT ? -1e4 : lerp(-40, W + 40, seg(t, SWEEP_AT, SWEEP_AT + BAR)));

export function Mess({ t }: { t: number }) {
  if (t > b(5) + 0.45) return null;
  const x = messX(t);
  const count = MESS.reduce((n, it) => n + (t >= it.at && x < it.x + it.w ? 1 : 0), 0);
  return (
    <AbsoluteFill>
      {MESS.map((it, i) => <JunkItem key={i} t={t} it={it} sweepX={x} />)}
      <AbsoluteFill style={{ clipPath: x > 0 ? `inset(0 0 0 ${x}px)` : undefined }}>
        <div style={{ ...HEAD, top: MESS_TOP, fontSize: 150 }}>
          <Words t={t} words={[{ text: "Your", at: b(3, 1) }, { text: "agents", at: b(3, 2) }, { text: "leave", at: b(3, 3) }]} />
          <Words t={t} words={[{ text: "files", at: b(3, 4), color: L.junk }, { text: "behind.", at: b(3, 4, 0.5), color: L.junk }]} />
        </div>
      </AbsoluteFill>
      {t >= SWEEP_AT && t <= SWEEP_AT + BAR ? <SweepLine x={x} /> : null}
      <Status count={count} ratio={count / MESS.length} opacity={1 - seg(t, b(5), b(5) + 0.4)} />
    </AbsoluteFill>
  );
}

/* ---------------------------------------------------------------- 2. Less. (bars 5-6) */
function dotPop(t: number, at: number) {
  const u = seg(t, at, at + 0.6);
  return u < 0.35 ? lerp(0, 1.55, ease.outExpo(u / 0.35)) : lerp(1.55, 1, ease.out3((u - 0.35) / 0.65));
}

export function Less({ t }: { t: number }) {
  if (!live(t, SCENE.less)) return null;
  return (
    <Exit t={t} at={SCENE.less[1]} dur={WIPE}>
      <div style={{ ...HEAD, left: X0 - 22, top: 236, display: "flex", fontSize: 420, lineHeight: 0.8, letterSpacing: "-0.065em" }}>
        {["L", "e", "s", "s"].map((ch, i) => <span key={i} style={{ display: "inline-block", ...arrive(t, b(5, 1, i * 0.25), 0.26) }}>{ch}</span>)}
        <span style={{ display: "inline-block", color: L.accent, transformOrigin: "50% 85%", transform: `scale(${dotPop(t, b(5, 3))})` }}>.</span>
      </div>
      <p style={{ ...LINE, top: 690 }}>
        <b style={{ display: "inline-block", color: L.ink, fontWeight: 600, ...arrive(t, b(6, 1)) }}>storage-steward</b>{" "}
        <span style={{ display: "inline-block", ...arrive(t, b(6, 2)) }}>cleans up while your agents work.</span>
      </p>
    </Exit>
  );
}

/* ---------------------------------------------------------------- 3. Clone it into your agent. (bars 7-8) */
export function Clone({ t }: { t: number }) {
  if (!live(t, SCENE.clone)) return null;
  const shown = typed(t, TYPE_CMD.at, TYPE_CMD.per, CMD);
  return (
    <Exit t={t} at={SCENE.clone[1]} dur={WIPE}>
      <Words t={t} style={HEAD} words={[{ text: "Clone", at: b(7, 1) }, { text: "it", at: b(7, 1, 0.25) }, { text: "into", at: b(7, 1, 0.5) },
        { text: "your", at: b(7, 1, 0.75) }, { text: "agent.", at: b(7, 2) }]} />
      <div style={{ position: "absolute", left: X0, top: 452, width: W - 2 * X0, boxSizing: "border-box", padding: "26px 32px", background: L.raise,
        border: `1.5px solid ${L.rule}`, borderRadius: 18, fontFamily: F.mono, fontSize: 26, color: L.ink, whiteSpace: "nowrap", ...arrive(t, b(7, 1, 0.5), 0.3) }}>
        <span style={{ color: L.muted }}>$ </span>{t >= TYPE_CMD.at ? shown : ""}<Caret t={t} show={t >= TYPE_CMD.at && shown.length < CMD.length} />
      </div>
      <div style={{ position: "absolute", left: X0 + 2, top: 586, fontFamily: F.mono, fontSize: 26, color: L.accent, ...arrive(t, b(8, 1)) }}>
        ✓ installed for every agent it found
      </div>
      <p style={{ ...LINE, top: 742, ...arrive(t, b(8, 2)) }}>
        Works with any agent that reads <span style={{ fontFamily: F.mono, fontSize: 44, color: L.ink }}>SKILL.md</span>.
      </p>
    </Exit>
  );
}

/* ---------------------------------------------------------------- 4. Then forget it. (bars 9-10) */
const SLOT = (W - 2 * X0) / SESSIONS.length;
const TRACK = 726;
const SHORT = ["tasks/#.output", "tmp.agent#", ".npm/_npx/#", "debug/#.txt", "file-history/#", "rollout-#.jsonl", "worktrees/#"];
const LEFT = SESSIONS.flatMap((s, k) => {
  const r = rng(100 + k);
  return [0, 1, 2].map((j) => {
    const text = SHORT[Math.floor(r() * SHORT.length)].replace("#", Math.floor(r() * 0xffff).toString(16).padStart(4, "0"));
    return { k, x: X0 + k * SLOT + 12, y: TRACK - 70 - j * 38, w: text.length * CHAR, text, at: s + 0.06 + j * 0.07 };
  });
});
const bgX = (t: number, sw: (typeof BG_SWEEPS)[number]) =>
  t < sw.at ? -1e4 : lerp(X0 - 24, X0 + (sw.after + 1) * SLOT, ease.inOut3(seg(t, sw.at, sw.at + BG_SWEEP_LEN)));

export function Forget({ t }: { t: number }) {
  if (!live(t, SCENE.forget)) return null;
  const x = Math.max(...BG_SWEEPS.map((sw) => bgX(t, sw)));
  const count = LEFT.reduce((n, it) => n + (t >= it.at && x < it.x + it.w ? 1 : 0), 0);
  const active = BG_SWEEPS.find((sw) => t >= sw.at && t <= sw.at + BG_SWEEP_LEN);
  return (
    <Exit t={t} at={SCENE.forget[1]} dur={WIPE}>
      <Words t={t} style={HEAD} words={[{ text: "Then", at: b(9, 1) }, { text: "forget", at: b(9, 1, 0.5) }, { text: "it.", at: b(9, 2) }]} />
      <div style={{ position: "absolute", left: X0, right: X0, top: TRACK + 5, height: 1.5, background: L.rule, ...arrive(t, b(9, 1, 0.5)) }} />
      {SESSIONS.map((s, k) => (
        <div key={k}>
          <div style={{ position: "absolute", left: X0 + k * SLOT + 12, top: TRACK, height: 12, borderRadius: 6, background: L.ink,
            width: lerp(0, SLOT - 24, ease.out3(seg(t, s, s + SESSION_LEN))) }} />
          <div style={{ position: "absolute", left: X0 + k * SLOT + 12, top: TRACK + 32, fontFamily: F.mono, fontSize: 20, color: L.muted,
            ...arrive(t, s, 0.2) }}>session {k + 1}</div>
        </div>
      ))}
      {LEFT.map((it, i) => (
        <JunkItem key={i} t={t} it={it} sweepX={x} />
      ))}
      {active ? <SweepLine x={bgX(t, active)} top={TRACK - 200} height={260} /> : null}
      <p style={{ ...LINE, top: 836, ...arrive(t, b(10, 1)) }}>Sweeps in the background. 0 tokens per prompt.</p>
      <Status count={count} ratio={count / 14} opacity={seg(t, b(9, 1, 0.5), b(9, 2))} />
    </Exit>
  );
}

/* ---------------------------------------------------------------- 5. Your rules. (bars 11-12) */
export function Rules({ t }: { t: number }) {
  if (!live(t, SCENE.rules)) return null;
  const say = typed(t, TYPE_SAY.at, TYPE_SAY.per, SAY), run = typed(t, TYPE_RUN.at, TYPE_RUN.per, RUN);
  const sayDone = say.length === SAY.length;
  return (
    <Exit t={t} at={SCENE.rules[1]} dur={WIPE}>
      <Words t={t} style={{ ...HEAD, fontSize: 150 }} words={[{ text: "Your", at: b(11, 1) }, { text: "rules.", at: b(11, 1, 0.5) }]} />
      <p style={{ ...LINE, top: 486, color: L.ink, fontSize: 56, fontWeight: 500, letterSpacing: "-0.012em", opacity: seg(t, TYPE_SAY.at - 0.05, TYPE_SAY.at) }}>
        “{t >= TYPE_SAY.at ? say : ""}{sayDone ? "”" : ""}
      </p>
      <div style={{ position: "absolute", left: X0, top: 590, fontFamily: F.mono, fontSize: 32, color: L.ink, whiteSpace: "nowrap",
        opacity: seg(t, TYPE_RUN.at - 0.05, TYPE_RUN.at) }}>
        <span style={{ color: L.muted }}>$ </span>{t >= TYPE_RUN.at ? run : ""}<Caret t={t} show={t >= TYPE_RUN.at} />
      </div>
      <div style={{ position: "absolute", left: X0 + 2, top: 658, fontFamily: F.mono, fontSize: 28, color: L.accent, ...arrive(t, b(12, 2)) }}>
        ✓ saved · the next sweep uses it
      </div>
    </Exit>
  );
}

/* ---------------------------------------------------------------- 6. the proof (bars 13-14) */
const STATS = [
  { to: [79, 85], suffix: "%", label: "less disk", left: X0, at: b(13, 1) },
  { to: [72], suffix: "%", label: "fewer tokens", left: 1040, at: b(13, 3) },
  { to: [0], suffix: "", label: "files lost", left: 1600, at: b(14, 1) },
];

export function Proof({ t }: { t: number }) {
  if (!live(t, SCENE.proof)) return null;
  return (
    <Exit t={t} at={SCENE.proof[1]} dur={WIPE}>
      {STATS.map((s) => {
        const u = ease.out3(seg(t, s.at, s.at + 0.55));
        return (
          <div key={s.label} style={{ position: "absolute", left: s.left, top: 330, ...arrive(t, s.at) }}>
            <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 196, lineHeight: 1, letterSpacing: "-0.045em", color: L.ink,
              fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{s.to.map((v) => Math.round(v * u)).join("–")}{s.suffix}</div>
            <div style={{ marginTop: 22, fontFamily: F.body, fontSize: 42, color: L.muted }}>{s.label}</div>
          </div>
        );
      })}
      <p style={{ ...LINE, top: 760, fontSize: 34, ...arrive(t, b(14, 2)) }}>From a 60-day simulation and the token evals.</p>
    </Exit>
  );
}

/* ---------------------------------------------------------------- 7. the end card (bars 15-16) */
export function End({ t }: { t: number }) {
  if (t < SCENE.end[0] - 0.01) return null;
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: X0, top: 318 }}><Mark t={t} draw0={b(15, 1)} pop0={b(15, 2)} size={196} /></div>
      <div style={{ ...HEAD, left: X0 + 236, top: 338, fontSize: 150, ...arrive(t, b(15, 1, 0.5), 0.3) }}>storage-steward</div>
      <p style={{ ...LINE, top: 610, ...arrive(t, b(15, 3)) }}>
        Works with any agent that reads <span style={{ fontFamily: F.mono, fontSize: 44, color: L.ink }}>SKILL.md</span>.
      </p>
      <div style={{ position: "absolute", left: X0, top: 702, fontFamily: F.mono, fontSize: 40, color: L.accent, ...arrive(t, b(16, 1)) }}>
        github.com/deaglecodes/storage-steward
      </div>
    </AbsoluteFill>
  );
}
