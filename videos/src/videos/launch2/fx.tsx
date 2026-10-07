import type { CSSProperties, ReactNode } from "react";

import { C } from "../launch/tokens";

/** Motion toolkit for the v2 film. Every value is a pure function of time. */
export const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
export const seg = (t: number, a: number, z: number) => (z <= a ? (t >= a ? 1 : 0) : clamp01((t - a) / (z - a)));
export const lerp = (a: number, z: number, u: number) => a + (z - a) * u;
export const ease = {
  out3: (x: number) => 1 - Math.pow(1 - x, 3),
  in3: (x: number) => x * x * x,
  inOut3: (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  outExpo: (x: number) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inExpo: (x: number) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  outBack: (x: number) => 1 + 2.4 * Math.pow(x - 1, 3) + 1.4 * Math.pow(x - 1, 2),
};

/** Deterministic PRNG (mulberry32): the same seed paints the same frame every time. */
export function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

/** A word slamming in: big and blurred, landing hard in `dur`. */
export function slam(t: number, at: number, dur = 0.16, from = 1.8) {
  const u = ease.outExpo(seg(t, at, at + dur));
  return { opacity: clamp01(u * 1.6), scale: lerp(from, 1, u), blur: (1 - u) * 22, visible: t >= at - 0.001 };
}

/** Zoom punch on a cut: a quick overshoot that settles. */
export const punch = (t: number, at: number, amount = 0.14, len = 0.28) =>
  t < at ? 1 : 1 + amount * Math.pow(1 - seg(t, at, at + len), 3);

/** A ring that expands from (x, y) and fades. */
export function Shockwave({ t, at, x, y, color = C.accentHi, max = 1000, len = 0.7, width = 10 }:
  { t: number; at: number; x: number; y: number; color?: string; max?: number; len?: number; width?: number }) {
  const u = seg(t, at, at + len);
  if (t < at || u >= 1) return null;
  const r = 40 + max * ease.out3(u);
  return (
    <svg style={{ position: "absolute", left: 0, top: 0, width: 1920, height: 1080, overflow: "visible" }}>
      <circle cx={x} cy={y} r={r} fill="none" stroke={color} strokeWidth={width * (1 - u) + 0.5} opacity={1 - u} />
    </svg>
  );
}

/** Exit transition: the frame splits into horizontal strips that slide away, alternating. */
export function Slices({ t, at, n = 8, len = 0.42, children }: { t: number; at: number; n?: number; len?: number; children: ReactNode }) {
  if (t < at) return <>{children}</>;
  return (
    <>
      {Array.from({ length: n }, (_, i) => {
        const u = ease.in3(seg(t, at + i * 0.018, at + i * 0.018 + len));
        const top = (i / n) * 100;
        const bottom = 100 - ((i + 1) / n) * 100;
        return (
          <div key={i} style={{ position: "absolute", inset: 0, clipPath: `inset(${top}% 0 ${bottom}% 0)`,
            translate: `${(i % 2 ? 1 : -1) * 2100 * u}px 0` }}>{children}</div>
        );
      })}
    </>
  );
}

/** RGB split for a beat-cut: two tinted copies offset for ~0.12 s. */
export function Rgb({ t, at, children, amount = 14 }: { t: number; at: number; children: ReactNode; amount?: number }) {
  const u = t < at ? 0 : 1 - seg(t, at, at + 0.14);
  const base: CSSProperties = { position: "absolute", inset: 0 };
  return (
    <div style={{ position: "absolute", inset: 0 }}>
      {u > 0.01 ? (
        <>
          <div style={{ ...base, translate: `${-amount * u}px 0`, opacity: 0.7 * u, mixBlendMode: "screen", filter: "sepia(1) saturate(6) hue-rotate(-50deg)" }}>{children}</div>
          <div style={{ ...base, translate: `${amount * u}px 0`, opacity: 0.7 * u, mixBlendMode: "screen", filter: "sepia(1) saturate(6) hue-rotate(160deg)" }}>{children}</div>
        </>
      ) : null}
      <div style={base}>{children}</div>
    </div>
  );
}

/** The disk platter: concentric tracks and sector ticks, the logo's ring as a world. */
export function Platter({ t, x = 960, y = 540, scale = 1, opacity = 0.5, spin = 5 }:
  { t: number; x?: number; y?: number; scale?: number; opacity?: number; spin?: number }) {
  if (opacity <= 0.002) return null;
  const rings = Array.from({ length: 22 }, (_, i) => 70 + i * 62);
  const ticks = Array.from({ length: 120 }, (_, i) => i * 3);
  return (
    <svg width={3000} height={3000} viewBox="-1500 -1500 3000 3000"
      style={{ position: "absolute", left: x - 1500, top: y - 1500, opacity, scale: `${scale}`, rotate: `${t * spin}deg` }}>
      {rings.map((r, i) => <circle key={r} r={r} fill="none" stroke="#ffffff" strokeOpacity={i % 4 === 3 ? 0.07 : 0.035} strokeWidth={i % 4 === 3 ? 2 : 1} />)}
      {ticks.map((a) => (
        <line key={a} x1={0} y1={-560} x2={0} y2={a % 30 === 0 ? -620 : -585} stroke="#ffffff" strokeOpacity={0.08} strokeWidth={2} transform={`rotate(${a})`} />
      ))}
      <path d="M -1300 0 A 1300 1300 0 0 1 0 -1300" fill="none" stroke={C.accentHi} strokeOpacity={0.12} strokeWidth={3} />
    </svg>
  );
}

/** Film grain, re-seeded 24 times a second, plus a soft vignette for depth. */
export function Atmosphere({ t }: { t: number }) {
  const seed = Math.floor(t * 24) % 97;
  return (
    <>
      <svg width={1920} height={1080} style={{ position: "absolute", inset: 0, opacity: 0.06, mixBlendMode: "overlay", pointerEvents: "none" }}>
        <filter id={`g${seed}`}><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves={2} seed={seed} stitchTiles="stitch" /></filter>
        <rect width="1920" height="1080" filter={`url(#g${seed})`} />
      </svg>
      <div style={{ position: "absolute", inset: 0, pointerEvents: "none",
        background: "radial-gradient(ellipse at 50% 50%, transparent 55%, rgba(2,5,9,0.55) 100%)" }} />
    </>
  );
}
