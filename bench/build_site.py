#!/usr/bin/env python3
"""Build the GitHub Pages site: docs/index.html (+ docs/benchmarks.html via build_report)."""
import json
from pathlib import Path

import build_report

ROOT = Path(__file__).resolve().parents[1]
TASKS = {"eval-1-disk-full-cleanup": "Free up space now", "eval-2-automate-cleanup": "Make cleanup automatic"}


def main():
    data = build_report.main()
    it2 = data["evals"]["iteration-2"]
    tok = [{"task": TASKS[ev], "with": c["with_skill"]["task_tokens"], "without": c["without_skill"]["task_tokens"],
            "secs_with": c["with_skill"]["secs"], "secs_without": c["without_skill"]["secs"]}
           for ev, c in it2.items() if ev in TASKS]
    sim = (ROOT / "docs/assets/sim.json").read_text()
    html = (ROOT / "site/index.html").read_text()
    html = html.replace("/*__SIM__*/null", sim).replace("/*__TOK__*/null", json.dumps(tok))
    (ROOT / "docs/index.html").write_text(html)
    (ROOT / "docs/.nojekyll").write_text("")
    print(f"wrote docs/index.html ({len(html) // 1024} KB), tokens: {tok}")


if __name__ == "__main__":
    main()
