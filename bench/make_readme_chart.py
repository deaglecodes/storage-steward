#!/usr/bin/env python3
"""Render the 60-day storage chart as static SVGs (light + dark) for the README."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = json.loads((ROOT / "bench/results/report_data.json").read_text())["series"]["typical"]
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
POL = [("none", "No cleanup", True), ("daily-nuke", "Manual daily wipe", False),
       ("steward", "storage-steward hooks", False), ("steward+weekly", "Hooks + weekly OK", False)]
THEMES = {
    "light": {"fg": "#0E1A2B", "muted": "#586579", "rule": "#E3E8EF",
              "c": {"none": "#9AA1AB", "daily-nuke": "#EB6834", "steward": "#2A78D6", "steward+weekly": "#1BAF7A"}},
    "dark": {"fg": "#EEF2F7", "muted": "#9AA6B6", "rule": "#283241",
             "c": {"none": "#6B727D", "daily-nuke": "#D95926", "steward": "#3987E5", "steward+weekly": "#199E70"}},
}


def render(theme: str) -> str:
    t = THEMES[theme]
    W, H, L, R, T, B = 880, 340, 64, 200, 20, 40
    n, top = len(DATA["none"]["gb"]), 300
    x = lambda d: L + d / (n - 1) * (W - L - R)
    y = lambda v: T + (1 - v / top) * (H - T - B)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
           f'aria-label="Disk used by agent leftovers over 60 days per cleanup policy">']
    for v in range(0, top + 1, 50):
        out.append(f'<line x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{t["rule"]}"/>')
        out.append(f'<text x="{L - 10}" y="{y(v) + 4:.1f}" text-anchor="end" font-family="{MONO}" font-size="12" fill="{t["muted"]}">{v} GB</text>')
    for d in (1, 15, 30, 45, 60):
        out.append(f'<text x="{x(d - 1):.1f}" y="{H - 14}" text-anchor="middle" font-family="{MONO}" font-size="12" fill="{t["muted"]}">day {d}</text>')
    ends = []
    for k, name, dash in POL:
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(DATA[k]["gb"]))
        extra = ' stroke-dasharray="6 5"' if dash else ""
        out.append(f'<polyline points="{pts}" fill="none" stroke="{t["c"][k]}" stroke-width="2.5" stroke-linejoin="round"{extra}/>')
        ends.append((DATA[k]["gb"][-1], k, name))
    last = -1e9
    for v, k, name in sorted(ends, reverse=True):
        ly = max(y(v) + 4, last + 18)
        last = ly
        out.append(f'<circle cx="{x(n - 1):.1f}" cy="{y(v):.1f}" r="4" fill="{t["c"][k]}"/>')
        out.append(f'<text x="{x(n - 1) + 12:.1f}" y="{ly:.1f}" font-family="{FONT}" font-size="13" font-weight="600" fill="{t["fg"]}">{name} <tspan fill="{t["muted"]}" font-family="{MONO}" font-weight="400">{v:.0f} GB</tspan></text>')
    out.append("</svg>")
    return "\n".join(out)


for th in THEMES:
    (ROOT / f"assets/chart-{th}.svg").write_text(render(th))
print("wrote assets/chart-light.svg, assets/chart-dark.svg")
