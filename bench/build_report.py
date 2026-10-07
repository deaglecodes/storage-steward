#!/usr/bin/env python3
"""Build the benchmark report page from results JSON -> storage-steward-benchmark.html"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WS = ROOT / "storage-steward-workspace"          # local eval runs (not published)
EVALS = ROOT / "bench/results/evals.json"         # sanitized aggregate, published
OVERHEAD = 102834                                  # measured: no-op general-purpose subagent


def runs(iteration: str):
    out = {}
    for ev in sorted((WS / iteration).glob("eval-*")):
        for cfg in ("with_skill", "without_skill"):
            rows = []
            for run in sorted((ev / cfg).glob("run-*")):
                t, g = run / "timing.json", run / "grading.json"
                if not (t.exists() and g.exists()):
                    continue
                tj, gj = json.loads(t.read_text()), json.loads(g.read_text())
                rows.append({"tokens": tj["total_tokens"], "secs": tj["total_duration_seconds"],
                             "tools": tj.get("tool_uses", 0), "pass": gj["summary"]["pass_rate"],
                             "metrics": gj.get("metrics", {}), "notes": gj.get("notes", [])})
            if rows:
                out.setdefault(ev.name, {})[cfg] = rows
    return out


def summarize(rs):
    def m(k):
        return round(statistics.mean(r[k] for r in rs), 1)
    return {"n": len(rs), "tokens": round(statistics.mean(r["tokens"] for r in rs)),
            "task_tokens": round(statistics.mean(r["tokens"] - OVERHEAD for r in rs)),
            "secs": m("secs"), "tools": m("tools"), "pass": round(100 * statistics.mean(r["pass"] for r in rs)),
            "freed_mb": [r["metrics"].get("freed_mb") for r in rs if "freed_mb" in r["metrics"]],
            "contaminated": any(r["notes"] for r in rs)}


def load_evals():
    if WS.exists():
        evals = {it: {ev: {cfg: summarize(rs) for cfg, rs in cfgs.items()} for ev, cfgs in runs(it).items()}
                 for it in ("iteration-1", "iteration-2")}
        EVALS.write_text(json.dumps(evals, indent=1))
    return json.loads(EVALS.read_text())


DOC_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<link rel="icon" href="assets/logo.svg" type="image/svg+xml">
<style>body{margin:0}.back{display:inline-flex;gap:8px;align-items:center;font:600 14px/1 system-ui;color:inherit;opacity:.75;text-decoration:none}</style>
</head><body>
"""


def main():
    sim = json.loads((ROOT / "bench/results/report_data.json").read_text())
    hooks = json.loads((ROOT / "bench/results/hook_latency.json").read_text())
    data = {"sim": sim, "hooks": hooks, "evals": load_evals(), "overhead": OVERHEAD,
            "mac": json.loads((ROOT / "bench/results/mac_scan.json").read_text())}
    page = (ROOT / "bench/report_template.html").read_text().replace("/*__DATA__*/null", json.dumps(data))
    art = ROOT / "storage-steward-benchmark.html"           # artifact version (no skeleton)
    art.write_text(page)
    back = '<a class="back" href="./"><img src="assets/logo.svg" width="22" height="22" alt="">storage-steward home</a>'
    docs = page.replace('<div class="wrap">\n  <header>', '<div class="wrap">\n  ' + back + '\n  <header>', 1)
    (ROOT / "docs/benchmarks.html").write_text(DOC_HEAD + docs + "\n</body></html>\n")
    print(f"wrote {art.name} and docs/benchmarks.html")
    return data


if __name__ == "__main__":
    main()
