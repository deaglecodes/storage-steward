import { loadFont as loadDisplay } from "@remotion/google-fonts/BricolageGrotesque";
import { loadFont as loadBody } from "@remotion/google-fonts/PublicSans";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";

/** storage-steward's own dark theme (site/index.html :root dark block). Hex only: these animate. */
export const C = {
  bg: "#0a1018",
  surface: "#101926",
  ink: "#edf2f8",
  ink2: "#c9d4e2",
  muted: "#98a5b7",
  rule: "#1f2c3e",
  accent: "#6ea2ff",
  accentHi: "#4d8dff",
  nuke: "#f07a49",
  keep: "#2fbf86",
  none: "#6b7686",
  term: "#060b12",
  term2: "#0c1522",
  termRule: "#1b2a40",
  termFg: "#dce6f3",
  termMuted: "#8796ab",
  logoTile: "#0e1a2b",
  logoTrack: "#21324b",
  logoUsed: "#e9eff8",
} as const;

const display = loadDisplay("normal", { weights: ["600", "800"], subsets: ["latin"] });
const body = loadBody("normal", { weights: ["400", "500", "600"], subsets: ["latin"] });
const mono = loadMono("normal", { weights: ["400", "600"], subsets: ["latin"] });

export const FONT = {
  display: `${display.fontFamily}, "Avenir Next", system-ui, sans-serif`,
  body: `${body.fontFamily}, -apple-system, system-ui, sans-serif`,
  mono: `${mono.fontFamily}, "SF Mono", Menlo, monospace`,
};
