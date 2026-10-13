import { FONT as BRAND } from "../launch/tokens";

/** The site's light theme (site/index.html :root). Hex only: colors that animate are mixed in code. */
export const L = {
  paper: "#f6f6f3",
  ink: "#0c1117",
  muted: "#5d6570",
  faint: "#bfc4ca",
  rule: "#e2e3de",
  raise: "#ffffff",
  accent: "#2a62cc",
  junk: "#e05a26",
} as const;

/** The site's type: Bricolage Grotesque for display, the system UI and mono faces for everything else. */
export const F = {
  display: BRAND.display,
  body: 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
  mono: 'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Consolas, monospace',
};

/** Mix two #rrggbb colors; u = 0 gives a, 1 gives b. */
export function mixHex(a: string, b: string, u: number): string {
  const k = Math.min(1, Math.max(0, u));
  const ch = (hex: string, i: number) => parseInt(hex.slice(1 + i * 2, 3 + i * 2), 16);
  const out = [0, 1, 2].map((i) => Math.round(ch(a, i) + (ch(b, i) - ch(a, i)) * k).toString(16).padStart(2, "0"));
  return `#${out.join("")}`;
}
