import { C, FONT } from "./tokens";

/** Twin of the site's hero df panel rows (site/index.html .df-row): label, GB, a 1 TB meter. */
export function DfRow({ label, gb, color, flash = 0, size = 34 }: { label: string; gb: number; color: string; flash?: number; size?: number }) {
  const full = gb >= 1000;
  const pct = Math.min(100, gb / 10);
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: size }}>
        <span>{label}</span>
        <b style={{ fontWeight: 600, color: full ? C.nuke : C.termFg, fontVariantNumeric: "tabular-nums" }}>{full ? "DISK FULL" : `${Math.round(gb)} GB`}</b>
      </div>
      <div data-target={`meter-${label}`} style={{ height: 30, borderRadius: 7, background: C.term2, boxShadow: `inset 0 0 0 1.5px ${C.termRule}`, overflow: "hidden" }}>
        <i style={{ display: "block", height: "100%", width: `${pct}%`, borderRadius: 6, background: color,
          filter: flash > 0 ? `brightness(${1 + 0.6 * flash})` : undefined }} />
      </div>
    </div>
  );
}

export function DayScrub({ day }: { day: number }) {
  return (
    <div style={{ display: "grid", gap: 14, paddingTop: 26, borderTop: `2px dashed ${C.termRule}`, fontFamily: FONT.mono }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 26, color: C.termMuted }}>
        <span>heavy agent user, simulated</span>
        <b style={{ color: C.termFg, fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>day {Math.max(1, Math.floor(day))}</b>
      </div>
      <div style={{ height: 8, borderRadius: 4, background: C.term2 }}>
        <i style={{ display: "block", height: "100%", width: `${((Math.min(60, day) - 1) / 59) * 100}%`, borderRadius: 4, background: C.accentHi }} />
      </div>
    </div>
  );
}
