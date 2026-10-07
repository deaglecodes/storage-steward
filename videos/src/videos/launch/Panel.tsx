import type { CSSProperties, ReactNode } from "react";
import { C, FONT } from "./tokens";

/** The site's terminal surface (.panel / .cmd): dark in both themes, three dots, a mono title. */
export function Panel({ title, style, children }: { title: string; style?: CSSProperties; children: ReactNode }) {
  return (
    <div style={{ position: "absolute", background: C.term, borderRadius: 26, boxShadow: `0 0 0 1.5px ${C.termRule}`,
      color: C.termFg, fontFamily: FONT.mono, padding: "26px 40px 36px", overflow: "hidden", ...style }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 24, color: C.termMuted, marginBottom: 28 }}>
        {[0, 1, 2].map((i) => <i key={i} style={{ width: 15, height: 15, borderRadius: 99, background: C.termRule, display: "inline-block" }} />)}
        <span style={{ marginLeft: 12, whiteSpace: "nowrap" }}>{title}</span>
      </div>
      {children}
    </div>
  );
}
