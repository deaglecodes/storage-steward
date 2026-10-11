#!/usr/bin/env python3
"""Aggregate simulator runs into the published benchmark data.

Reads bench/results/sim_typical_s{7,11,23}.json and sim_runaway_s7.json (from bench/simulate.py) and writes
  bench/results/report_data.json   (benchmarks page and README chart)
  docs/assets/sim.json             (the website's interactive chart)
Then run bench/build_site.py and bench/make_readme_chart.py to rebuild the pages and charts.

Usage: python3 bench/build_results.py [--results DIR] [--out-dir DIR]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIB = 1 << 30
SEEDS = (7, 11, 23)
CHART_POLICIES = ("none", "daily-nuke", "steward", "steward+weekly")   # the site chart's lines


def load(results: Path, scenario: str, seed: int) -> dict:
    data = json.loads((results / f"sim_{scenario}_s{seed}.json").read_text())
    return {r["policy"]: r for r in data["results"]}


def gib(n: float) -> float:
    return round(n / GIB, 1)


def series(runs: dict) -> dict:
    return {p: {"gb": [gib(b) for b in r["footprint"]], "misses": r["cache_misses"], "miss_gb": gib(r["miss_bytes"]),
                "lost": r["deliverables_lost"], "deliv": r["deliverables_total"]} for p, r in runs.items()}


def seed_table(runs: dict) -> dict:
    base = runs["none"]["footprint"][-1]
    return {p: {"d60_gb": gib(r["footprint"][-1]), "saved": round(100 * (1 - r["footprint"][-1] / base), 1),
                "misses": r["cache_misses"]} for p, r in runs.items()}


def build(results: Path):
    runs = {"typical": load(results, "typical", 7), "runaway": load(results, "runaway", 7)}
    report = {"series": {k: series(v) for k, v in runs.items()},
              "seeds": {str(s): seed_table(load(results, "typical", s)) for s in SEEDS}}
    site = {"series": {k: {p: v[p]["gb"] for p in CHART_POLICIES} for k, v in report["series"].items()},
            "cost": {k: {p: {f: d[f] for f in ("misses", "miss_gb", "lost", "deliv")} for p, d in v.items()}
                     for k, v in report["series"].items()}}
    return report, site


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--results", type=Path, default=ROOT / "bench/results")
    p.add_argument("--out-dir", type=Path, default=ROOT, help="repo root to write into (default: this repo)")
    a = p.parse_args(argv)
    report, site = build(a.results)
    (a.out_dir / "bench/results").mkdir(parents=True, exist_ok=True)
    (a.out_dir / "docs/assets").mkdir(parents=True, exist_ok=True)
    (a.out_dir / "bench/results/report_data.json").write_text(json.dumps(report))
    (a.out_dir / "docs/assets/sim.json").write_text(json.dumps(site, separators=(",", ":")))
    t = report["seeds"]["7"]
    print("seed 7, day 60: " + ", ".join(f"{k} {v['d60_gb']} GB ({v['saved']}%)" for k, v in t.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
