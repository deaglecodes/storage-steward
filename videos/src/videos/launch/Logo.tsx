import { step } from "../../kit/spring";
import { clamp01 } from "../../kit/time";
import { C } from "./tokens";

/** The logo mark driven by time: the ring draws, the reclaimed piece pops out, the spindle lands. (assets/logo.svg) */
const pop = { stiffness: 210, damping: 16 };

export function Mark({ t, draw0, pop0, size }: { t: number; draw0: number; pop0: number; size: number }) {
  const ring = clamp01((t - draw0) / 0.35);
  const draw = clamp01((t - draw0 - 0.15) / 1.1);
  const eased = 1 - Math.pow(1 - draw, 3);
  const out = step(t - pop0, pop);
  const dot = step(t - pop0 - 0.08, pop);
  // reclaimed piece: rests inside the ring, pops out along its bisector (215deg) by 3.2 units
  const off = 3.2 * out;
  const dx = Math.cos((215 * Math.PI) / 180) * off;
  const dy = Math.sin((215 * Math.PI) / 180) * off;
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" style={{ display: "block", overflow: "visible" }}>
      <rect x="2.5" y="2.5" width="59" height="59" rx="14.5" fill={C.logoTile} stroke="#ffffff" strokeOpacity={0.12 * ring} opacity={ring} />
      <circle cx="32" cy="32" r="17" fill="none" stroke={C.logoTrack} strokeWidth="7" opacity={ring} />
      <path d="M32 15 A17 17 0 1 1 16.025 37.814" fill="none" stroke={C.logoUsed} strokeWidth="7" pathLength={1}
        strokeDasharray="1 1" strokeDashoffset={1 - eased} />
      <path d="M15.01 32.593 A17 17 0 0 1 26.747 15.832" fill="none" stroke={C.accentHi} strokeWidth="7" strokeLinecap="round"
        style={{ translate: `${dx}px ${dy}px` }} opacity={clamp01(out * 1.4)} />
      <circle cx="32" cy="32" r={3.6 * Math.max(0, dot)} fill={C.accentHi} />
    </svg>
  );
}
