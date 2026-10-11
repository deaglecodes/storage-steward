#!/usr/bin/env python3
"""Build the GitHub Pages site: docs/index.html (+ docs/benchmarks.html via build_report).

The page is meant to weigh almost nothing, so the build does the work instead of the browser:
the chart is pre-rendered from the 60-day simulation, the stats are computed from the benchmark
results, the one display font is subset to the glyphs the page uses, and the inline scripts are
pinned in a Content-Security-Policy by hash.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import build_report

ROOT = Path(__file__).resolve().parents[1]
TASKS = {"eval-1-disk-full-cleanup": "Free up space now", "eval-2-automate-cleanup": "Make cleanup automatic"}
TOP_GB = 320          # chart y-scale; the no-cleanup line peaks just under 300 GB
GRID_GB = 300         # the one labelled gridline
FONT = "Bricolage+Grotesque:opsz,wght@96,800"
EXTRA_GLYPHS = "0123456789.,–%KB "   # text the scripts write in the display face (counters, page weight)
BROWSER = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129 Safari/537.36"


def token_saving(data: dict) -> int:
    """Average task-token reduction across the iteration-2 evals, as a whole percent."""
    runs = [c for ev, c in data["evals"]["iteration-2"].items() if ev in TASKS]
    cuts = [1 - c["with_skill"]["task_tokens"] / c["without_skill"]["task_tokens"] for c in runs]
    return round(100 * sum(cuts) / len(cuts))


def disk_saving(series: dict[str, list[float]]) -> tuple[int, int]:
    """Day-60 saving of the default policy and of the default plus the weekly confirm review."""
    none = series["none"][-1]
    return round(100 * (1 - series["steward"][-1] / none)), round(100 * (1 - series["steward+weekly"][-1] / none))


def chart(none: list[float], steward: list[float]) -> str:
    """Static SVG lines plus HTML labels, so the chart shows without JavaScript."""
    last = len(none) - 1

    def y(gb: float) -> float:
        return 400 - gb / TOP_GB * 400

    def points(values: list[float]) -> str:
        return " ".join(f"{i / last * 1000:.1f},{y(v):.1f}" for i, v in enumerate(values))

    def top(gb: float) -> str:
        return f"{100 - gb / TOP_GB * 100:.2f}%"

    return "\n".join([
        '<svg viewBox="0 0 1000 400" preserveAspectRatio="none" aria-hidden="true">',
        f'<line class="g" x1="0" x2="1000" y1="{y(GRID_GB):.1f}" y2="{y(GRID_GB):.1f}"/><line class="g" x1="0" x2="1000" y1="400" y2="400"/>',
        f'<polyline class="l l-none" points="{points(none)}"/>',
        f'<polyline class="l l-st" points="{points(steward)}"/>',
        "</svg>",
        f'<span class="y" style="top:{top(GRID_GB)}" aria-hidden="true">{GRID_GB} GB</span><span class="y" style="top:100%" aria-hidden="true">0</span>',
        f'<span class="dotm l-none" style="top:{top(none[-1])}"></span><span class="dotm l-st" style="top:{top(steward[-1])}"></span>',
        f'<span class="end" style="top:calc({top(none[-1])} + 14px)" aria-hidden="true">no cleanup <b>{round(none[-1])} GB</b></span>',
        f'<span class="end" style="top:calc({top(steward[-1])} - 38px)" aria-hidden="true">storage-steward <b>{round(steward[-1])} GB</b></span>',
    ])


class DisplayText(HTMLParser):
    """Collects the text set in the display face (class "d"), skipping screen-reader-only text."""

    VOID = {"meta", "link", "br", "img", "input", "hr", "source", "wbr"}

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[list[str]] = []
        self.chars: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.VOID:
            self.stack.append((dict(attrs).get("class") or "").split())

    def handle_endtag(self, tag: str) -> None:
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, data: str) -> None:
        classes = {c for level in self.stack for c in level}
        if "d" in classes and "sr" not in classes:
            self.chars.update(re.sub(r"__[A-Z_]+__", "", data))   # build placeholders are not page text


def font_url(html: str) -> str:
    parser = DisplayText()
    parser.feed(html)
    glyphs = "".join(sorted((parser.chars | set(EXTRA_GLYPHS)) - {"\n", "\t"}))
    query = urllib.parse.quote(glyphs, safe="")
    return f"https://fonts.googleapis.com/css2?family={FONT}&amp;text={query}&amp;display=swap"


def fetch(url: str) -> bytes:
    """Bytes as they arrive on the wire (gzip left compressed), the way a browser would download them."""
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=15) as res:
        return res.read()


def font_bytes(url: str) -> int:
    """What the subset font costs a first visit: its stylesheet plus every font file the stylesheet points at."""
    try:
        sheet = fetch(url.replace("&amp;", "&"))
        css = gzip.decompress(sheet).decode() if sheet[:2] == b"\x1f\x8b" else sheet.decode()
        return len(sheet) + sum(len(fetch(src)) for src in re.findall(r"url\((https://fonts\.gstatic\.com[^)]+)\)", css))
    except OSError as err:
        print(f"font size unavailable offline ({err}); assuming 5 KB")
        return 5000


def page_weight(html: str, fonts: str) -> float:
    """KB a first visit downloads: the gzipped HTML GitHub Pages serves plus the subset font.

    Measured once per page version and recorded, so CI rebuilds the exact same page without
    touching the network or depending on its zlib build.
    """
    record = ROOT / "bench/results/site_weight.json"
    key = hashlib.sha256((html + fonts).encode()).hexdigest()
    try:
        saved = json.loads(record.read_text())
    except (OSError, ValueError):
        saved = {}
    if saved.get("key") == key:
        return saved["kb"]
    html_gz, font = len(gzip.compress(html.encode(), 6)), font_bytes(fonts)
    kb = round((html_gz + font) / 1000, 1)
    record.write_text(json.dumps({"key": key, "kb": kb, "html_gzip_bytes": html_gz, "font_bytes": font}, indent=1) + "\n")
    return kb


def csp(html: str) -> str:
    hashes = " ".join(
        f"'sha256-{base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()}'"
        for body in re.findall(r"<script>(.*?)</script>", html, re.S))
    return ("default-src 'self'; script-src " + hashes + "; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data:; media-src 'self'; connect-src 'none'; "
            "object-src 'none'; base-uri 'none'; form-action 'none'")


def main() -> None:
    data = build_report.main()
    series = json.loads((ROOT / "docs/assets/sim.json").read_text())["series"]["typical"]
    none, steward = series["none"], series["steward"]
    lo, hi = disk_saving(series)
    tok = token_saving(data)
    label = (f"60-day simulation of heavy agent use: with no cleanup, agent leftovers grow to {round(none[-1])} GB; "
             f"with storage-steward they stay near {round(steward[-1])} GB.")
    compact = {"none": [round(v, 1) for v in none], "steward": [round(v, 1) for v in steward]}

    html = (ROOT / "site/index.html").read_text()
    html = (html.replace("<!--__CHART__-->", chart(none, steward)).replace("__CHART_LABEL__", label)
            .replace("/*__DATA__*/null", json.dumps(compact, separators=(",", ":")))
            .replace("__DISK_LO__", str(lo)).replace("__DISK_HI__", str(hi)).replace("__TOK_PCT__", str(tok))
            .replace("__NONE_GB__", str(round(none[-1]))).replace("__ST_GB__", str(round(steward[-1]))))
    fonts = font_url(html)
    html = html.replace("__FONTS__", fonts)
    weight = page_weight(html, fonts)
    html = html.replace("__WEIGHT__", f"{weight:.1f}")
    html = html.replace("__CSP__", csp(html))
    leftover = re.findall(r"__[A-Z_]+__", html)
    if leftover:
        raise SystemExit(f"unfilled placeholders: {sorted(set(leftover))}")

    (ROOT / "docs/index.html").write_text(html)
    (ROOT / "docs/.nojekyll").write_text("")
    raw, packed = len(html.encode()), len(gzip.compress(html.encode(), 9))
    print(f"wrote docs/index.html ({raw / 1000:.1f} KB, {packed / 1000:.1f} KB gzipped, page weight {weight:.1f} KB) · disk {lo}–{hi}% · tokens {tok}%")


if __name__ == "__main__":
    main()
