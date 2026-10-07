#!/usr/bin/env python3
"""Storage-over-time benchmark for storage-steward.

Replays N simulated days of an agent-heavy workload on real (scaled) files in a sandbox and
compares cleanup policies:
  none           - no cleanup (status quo)
  daily-nuke     - what people do by hand each day: rm -rf temp/caches/sandboxes
  steward        - storage-steward hooks only (auto tier at session end, 3h throttle)
  steward+weekly - hooks + user approves the confirm tier once a week

Measured per policy: footprint per day (modeled bytes), cache misses (re-downloads = the
performance cost), deliverables or uncommitted work destroyed (data loss).

Rates come from GitHub reports (anthropics/claude-code #26911 #41737 #92158, openai/codex #42648)
and this Mac's measured dirs. Scale: 1 real byte = SCALE modeled bytes.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import sys
import time
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "storage-steward" / "scripts"))
import steward  # noqa: E402

SCALE = 4096
MB = 1 << 20
GB = 1 << 30
DAY = 86400.0
HOUR = 3600.0
SESSION_HOURS = (9, 11, 13, 15, 17, 21)

PERSONA = {                              # modeled sizes, per event
    "task_outputs_per_session": 10, "task_output_mb": 15,
    "scratch_mb": 20, "transcript_mb": 15, "file_history_mb": 5, "debug_mb": 2,
    "sandboxes_per_day": 8, "sandbox_plugin_mb": 290, "sandbox_output_mb": 6, "sandbox_output_p": 0.2,
    "codex_mb_per_day": 70,
    "worktree_every_days": 2, "worktree_mb": 600, "worktree_dirty_p": 0.2,
    "npx_new_per_day": 2, "npx_mb": 40, "npx_hot": 5,
    "uv_new_per_day": 10, "uv_mb": 15, "uv_hot": 20, "uv_hot_use_p": 0.5,
    "xcode_every_days": 3, "xcode_mb": 1500,
    "pip_mb_per_day": 20, "tmpdir_mb_per_day": 50,
    "updater_every_days": 7, "updater_mb": 400,
    "project_every_days": 5, "project_deps_mb": 500, "project_active_days": 10,
    "runaway_p_per_session": 0.0, "runaway_gb": (20, 150),
}


class World:
    def __init__(self, base: Path, policy: str, seed: int, persona: dict, t0: float):
        self.base, self.policy, self.p, self.t0 = base, policy, persona, t0
        self.rng = random.Random(seed)
        self.home, self.tmp, self.utmp = base / "home", base / "tmp", base / "utmp"
        for d in (self.home, self.tmp, self.utmp):
            d.mkdir(parents=True, exist_ok=True)
        self.ctmp = self.tmp / f"claude-{os.getuid()}"
        self.misses = 0
        self.miss_bytes = 0
        self.deliverables, self.dirty_wts = [], []
        self.projects = []          # (path, created_day)
        self.seen = set()
        self.n = 0

    # ---- file helpers (modeled sizes, real sizes scaled down)
    def put(self, path: Path, modeled: int, t: float):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            f.truncate(max(1, modeled // SCALE))
        os.utime(path, (t, t))
        for parent in path.parents:
            if parent == self.base:
                break
            try:
                os.utime(parent, (t, t))
            except OSError:
                pass

    def mkdir(self, d: Path, t: float):
        d.mkdir(parents=True, exist_ok=True)
        for x in [d] + list(d.parents):
            if x == self.base:
                break
            os.utime(x, (t, t))

    def entry(self, d: Path, modeled: int, t: float, files: int = 2):
        for i in range(files):
            self.put(d / f"f{i}.bin", modeled // files, t)

    def use(self, d: Path, modeled: int, t: float, write: bool = False):
        """A tool reuses a cache entry. Missing => cache miss (re-download)."""
        if not d.exists():
            if str(d) in self.seen:           # existed before and was deleted => re-download
                self.misses += 1
                self.miss_bytes += modeled
            self.seen.add(str(d))
            self.entry(d, modeled, t)
            return
        for f in d.rglob("*"):
            if f.is_file():
                st = f.stat()
                if write:
                    os.utime(f, (t, t))
                elif st.st_atime < st.st_mtime:      # APFS/relatime semantics
                    os.utime(f, (t, st.st_mtime))

    def uid(self) -> str:
        self.n += 1
        r = self.rng.getrandbits(128)
        h = f"{r:032x}"
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    # ---- one simulated day
    def day(self, d: int):
        p, rng = self.p, self.rng
        day0 = self.t0 + d * DAY
        self.daily_tools(d, day0)
        for k, hr in enumerate(SESSION_HOURS):
            ts = day0 + hr * HOUR
            sid = self.uid()
            sdir = self.ctmp / "-Users-me-proj" / sid
            self.put(sdir / "scratchpad" / "work.bin", p["scratch_mb"] * MB, ts)
            for i in range(p["task_outputs_per_session"]):
                mb = rng.lognormvariate(0, 1) * p["task_output_mb"]
                self.put(sdir / "tasks" / f"t{i}.output", int(mb * MB), ts + 0.5 * HOUR)
            if rng.random() < p["runaway_p_per_session"]:
                gb = rng.uniform(*p["runaway_gb"])
                self.put(sdir / "tasks" / "runaway.output", int(gb * GB), ts + HOUR)
            pr = self.home / ".claude/projects/-Users-me-proj"
            self.put(pr / f"{sid}.jsonl", p["transcript_mb"] * MB, ts + 1.5 * HOUR)
            self.put(self.home / ".claude/file-history" / sid / "a.bak", p["file_history_mb"] * MB, ts + HOUR)
            self.put(self.home / ".claude/debug" / f"{sid}.txt", p["debug_mb"] * MB, ts + HOUR)
            self.session_end(ts + 1.5 * HOUR, sid)
        if self.policy == "daily-nuke":
            self.nuke(day0 + 23 * HOUR)
        if self.policy == "steward+weekly" and d % 7 == 6:
            self.steward(day0 + 22 * HOUR, None, "sweep", "--tier", "confirm", "--yes")

    def daily_tools(self, d: int, day0: float):
        p, rng = self.p, self.rng
        t = day0 + 8 * HOUR
        sbroot = self.home / "Library/Application Support/Claude/local-agent-mode-sessions/acct/org"
        for _ in range(p["sandboxes_per_day"]):
            sb = sbroot / f"local_{self.uid()}"
            self.entry(sb / ".claude/plugins", p["sandbox_plugin_mb"] * MB, t, files=3)
            self.put(sb / ".claude/projects/x/s.jsonl", 1 * MB, t)
            self.mkdir(sb / "uploads", t)
            if rng.random() < p["sandbox_output_p"]:
                f = sb / "outputs" / "deliverable.pdf"
                self.put(f, p["sandbox_output_mb"] * MB, t + HOUR)
                self.deliverables.append(f)
            else:
                self.mkdir(sb / "outputs", t)
        dd = time.gmtime(day0)
        self.put(self.home / ".codex/sessions" / f"{dd.tm_year}/{dd.tm_mon:02d}/{dd.tm_mday:02d}" / f"r{d}.jsonl",
                 p["codex_mb_per_day"] * MB, t)
        if d % p["worktree_every_days"] == 0:
            wt = self.home / ".codex/worktrees" / f"wt{d}"
            self.make_worktree(wt, rng.random() < p["worktree_dirty_p"], t)
        npx = self.home / ".npm/_npx"
        for i in range(p["npx_hot"]):
            self.use(npx / f"hot{i}", p["npx_mb"] * MB, t)
        for _ in range(p["npx_new_per_day"]):
            self.entry(npx / f"n{self.uid()[:12]}", p["npx_mb"] * MB, t)
        uv = self.home / ".cache/uv/wheels-v5"
        for i in range(p["uv_hot"]):
            if rng.random() < p["uv_hot_use_p"]:
                self.use(uv / f"hot{i}", p["uv_mb"] * MB, t)
        for _ in range(p["uv_new_per_day"]):
            self.entry(uv / f"w{self.uid()[:12]}", p["uv_mb"] * MB, t, files=1)
        if d % p["xcode_every_days"] == 0:
            proj = d // (p["xcode_every_days"] * 4)       # same app rebuilt for ~12 days, then a new one
            self.use(self.home / f"Library/Developer/Xcode/DerivedData/App{proj}", p["xcode_mb"] * MB, t, write=True)
        self.put(self.home / f"Library/Caches/pip/http-v2/{d % 16:x}/{d}.bin", p["pip_mb_per_day"] * MB, t)
        self.put(self.utmp / f"tmp{d}" / "junk.bin", p["tmpdir_mb_per_day"] * MB, t)
        if d % p["updater_every_days"] == 0:
            self.put(self.home / "Library/Caches/com.app.ShipIt" / f"update.{d}" / "payload.zip", p["updater_mb"] * MB, t)
        if d % p["project_every_days"] == 0:
            pj = self.home / "code" / f"proj{d}"
            self.put(pj / "package.json", 2048, t)
            self.entry(pj / "node_modules", p["project_deps_mb"] * MB, t, files=3)
            self.seen.add(str(pj / "node_modules"))
            self.projects.append((pj, d))
        old = [pj for pj, born in self.projects if d - born >= p["project_active_days"]]
        if old and rng.random() < 0.05:
            pj = rng.choice(old)
            self.put(pj / "package.json", 2048, t)
            self.use(pj / "node_modules", p["project_deps_mb"] * MB, t)
        for pj, born in self.projects:
            if d - born < p["project_active_days"]:
                self.put(pj / "package.json", 2048, t)        # active: manifests touched
                self.use(pj / "node_modules", p["project_deps_mb"] * MB, t)

    def make_worktree(self, wt: Path, dirty: bool, t: float):
        import subprocess
        self.put(wt / "README.md", 4096, t)
        (wt / ".gitignore").write_text("node_modules/\n")
        git = ["git", "-C", str(wt), "-c", "user.email=s@s", "-c", "user.name=s",
               "-c", "maintenance.auto=false", "-c", "gc.auto=0"]      # no detached writers
        subprocess.run(["git", "init", "-q", str(wt)], check=True)
        subprocess.run(git + ["add", "."], check=True)
        subprocess.run(git + ["commit", "-qm", "wt"], check=True)
        self.entry(wt / "node_modules", self.p["worktree_mb"] * MB, t, files=3)
        if dirty:
            (wt / "README.md").write_text("uncommitted work")
            self.dirty_wts.append(wt)
        for root, dirs, files in os.walk(wt):
            for n in dirs + files:
                try:
                    os.utime(os.path.join(root, n), (t, t), follow_symlinks=False)
                except FileNotFoundError:
                    pass
        os.utime(wt, (t, t))

    # ---- policies
    def steward(self, t: float, sid, *cmd):
        argv = ["--home", str(self.home), "--tmp", str(self.tmp), "--user-tmp", str(self.utmp), "--now", str(t)]
        if sid:
            argv += ["--session", sid]
        stdin = sys.stdin
        sys.stdin = io.StringIO("{}")
        try:
            with redirect_stdout(io.StringIO()):
                steward.main(argv + list(cmd))
        finally:
            sys.stdin = stdin

    def session_end(self, t: float, sid: str):
        if self.policy.startswith("steward"):
            self.steward(t, sid, "hook", "session-end", "--foreground")

    def nuke(self, t: float):
        """The manual daily routine people post about: wipe temp + caches + sandboxes."""
        h = self.home
        for d in (self.ctmp, h / ".npm/_npx", h / ".cache/uv", h / "Library/Caches/pip",
                  h / "Library/Developer/Xcode/DerivedData", h / ".claude/debug", h / ".claude/file-history",
                  h / "Library/Caches/com.app.ShipIt"):
            shutil.rmtree(d, ignore_errors=True)
        for sb in h.glob("Library/Application Support/Claude/local-agent-mode-sessions/*/*/local_*"):
            shutil.rmtree(sb, ignore_errors=True)    # the #92158 workaround: rm -rf local_*
        for e in self.utmp.iterdir():
            shutil.rmtree(e, ignore_errors=True)

    # ---- measurement
    def footprint(self) -> int:
        total = 0
        for root, _dirs, files in os.walk(self.base):
            for f in files:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
        return total * SCALE

    def data_loss(self):
        lost = sum(1 for f in self.deliverables if not f.exists())
        dirty = sum(1 for w in self.dirty_wts if not w.exists())
        return lost, dirty


def run(policy: str, days: int, seed: int, persona: dict, workdir: Path):
    saved = [(r, r.second_chance) for r in steward.RULES]
    if policy == "steward-age-only":           # ablation: same rules, no second-chance eviction
        for r, _ in saved:
            r.second_chance = False
    try:
        return _run(policy, days, seed, persona, workdir)
    finally:
        for r, v in saved:
            r.second_chance = v


def _run(policy: str, days: int, seed: int, persona: dict, workdir: Path):
    base = workdir / policy
    shutil.rmtree(base, ignore_errors=True)
    t0 = time.time() - (days + 2) * DAY
    w = World(base, policy, seed, persona, t0)
    series = []
    t_start = time.time()
    for d in range(days):
        w.day(d)
        series.append(w.footprint())
    lost, dirty = w.data_loss()
    out = {"policy": policy, "footprint": series, "cache_misses": w.misses, "miss_bytes": w.miss_bytes,
           "deliverables_lost": lost, "deliverables_total": len(w.deliverables),
           "dirty_worktrees_lost": dirty, "wall_s": round(time.time() - t_start, 1)}
    shutil.rmtree(base, ignore_errors=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--runaway", action="store_true", help="include runaway task outputs (3.3%%/session)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    persona = dict(PERSONA)
    if a.runaway:
        persona["runaway_p_per_session"] = 0.033
    results = [run(pol, a.days, a.seed, persona, Path(a.workdir))
               for pol in ("none", "daily-nuke", "steward", "steward+weekly", "steward-age-only")]
    Path(a.out).write_text(json.dumps({"days": a.days, "seed": a.seed, "runaway": a.runaway,
                                       "scale": SCALE, "persona": persona, "results": results}, indent=1))
    base = results[0]["footprint"]
    for r in results:
        f = r["footprint"]
        cells = [f"d{d}: {f[d-1] / GB:6.1f}GB ({100 * (1 - f[d-1] / base[d-1]):4.0f}%)" for d in (7, 14, 30, a.days) if d <= a.days]
        print(f"{r['policy']:<15} " + "  ".join(cells) +
              f" | misses {r['cache_misses']:3d} ({r['miss_bytes'] / GB:5.1f}GB) | lost deliverables "
              f"{r['deliverables_lost']}/{r['deliverables_total']} | {r['wall_s']}s")


if __name__ == "__main__":
    main()
