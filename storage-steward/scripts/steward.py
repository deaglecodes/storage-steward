#!/usr/bin/env python3
"""storage-steward: keep agent + dev-tool disk usage in check, with tiny output.

  status      one line of free space (--quiet: print only when low)
  scan        dry run: what a sweep would reclaim, by tier (<= ~15 lines)
  sweep       reclaim auto tier; add --tier confirm --yes [--only RULE] after the user agrees
  report      total reclaimed so far (ledger)
  hook EVENT  Claude Code hook entry point: prompt | stop | session-end
  install     add hooks to ~/.claude/settings.json (backup first); uninstall removes them

Sandbox/testing: --home DIR [--tmp DIR] [--user-tmp DIR] --now EPOCH. With --home, nothing
outside those dirs is touched and native prune commands are skipped.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import DAY, GIB, HOUR, RULES, Item  # noqa: E402

LOW_FREE_BYTES = 20 * GIB          # warn below this ...
LOW_FREE_FRACTION = 0.05           # ... or below this fraction free (big disks)
CRITICAL_FREE_BYTES = 5 * GIB      # skip probation when this tight
MIN_IDLE = HOUR                    # never touch anything written in the last hour
PROBATION = 7 * DAY                # second-chance: armed entries must stay unread this long
SWEEP_INTERVAL = 3 * HOUR          # hooks sweep at most this often
WARN_INTERVAL = 6 * HOUR           # low-disk warning at most this often per session
SENTINELS = 64                     # files armed per cache entry
MARK = "storage-steward"           # identifies our hook entries in settings.json
NEVER = ("", "Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Library",
         ".ssh", ".gnupg", ".claude", ".claude/settings.json", ".claude.json", ".claude/memory",
         ".claude/skills", ".claude/plugins", ".codex", ".codex/auth.json", ".codex/config.toml")


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit in ("GB", "TB") else f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class Ctx:
    def __init__(self, a):
        sandbox = a.home is not None
        self.real_home = not sandbox
        self.home = Path(a.home or os.path.expanduser("~")).resolve()
        self.now = float(a.now) if a.now else time.time()
        uid = os.getuid()
        tmp = a.tmp or (None if sandbox else ("/private/tmp" if sys.platform == "darwin" else "/tmp"))
        self.claude_tmp = Path(tmp) / f"claude-{uid}" if tmp else None
        ut = a.user_tmp or (None if sandbox else (os.environ.get("TMPDIR") or tempfile.gettempdir()))
        self.user_tmp = Path(ut).resolve() if ut else None
        self.cwd = Path(a.cwd).resolve() if getattr(a, "cwd", None) else None
        self.session = getattr(a, "session", None) or (None if sandbox else os.environ.get("CLAUDE_CODE_SESSION_ID"))
        protect = list(getattr(a, "protect", None) or [])
        self.protect = [os.path.realpath(p) for p in protect]
        host = None if sandbox else os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")
        self.protect_names = {host} if host else set()
        self.state = self.home / ".cache" / MARK
        self.kept = []          # (rule, bytes, reason) reported but not removable
        self._never = {os.path.realpath(self.home / n) for n in NEVER}

    # one walk: allocated bytes (hardlinks once), newest mtime, early-exit when active
    def stats(self, path, cutoff=None):
        try:
            st = os.lstat(path)
        except OSError:
            return 0, 0.0, False
        size, newest = st.st_blocks * 512, st.st_mtime
        if cutoff is not None and newest > cutoff:
            return size, newest, True
        if not stat.S_ISDIR(st.st_mode):
            return size, newest, False
        seen, stack = set(), [str(path)]
        while stack:
            try:
                it = os.scandir(stack.pop())
            except OSError:
                continue
            with it:
                for e in it:
                    try:
                        s = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if s.st_mtime > newest:
                        newest = s.st_mtime
                        if cutoff is not None and newest > cutoff:
                            return size, newest, True
                    if s.st_nlink > 1 and not stat.S_ISDIR(s.st_mode):
                        if (s.st_dev, s.st_ino) in seen:
                            continue
                        seen.add((s.st_dev, s.st_ino))
                    size += s.st_blocks * 512
                    if stat.S_ISDIR(s.st_mode):
                        stack.append(e.path)
        return size, newest, False

    def allowed(self, item: Item) -> bool:
        if not item.path or not item.root:
            return False
        rp = os.path.join(os.path.realpath(os.path.dirname(item.path)), os.path.basename(item.path))
        root = os.path.realpath(item.root)
        if rp == root or not rp.startswith(root + os.sep):
            return False
        if rp in self._never or any(n.startswith(rp + os.sep) for n in self._never):
            return False
        if self.session and self.session in rp:
            return False
        if any(n in rp for n in self.protect_names):
            return False
        for p in self.protect:
            if rp == p or rp.startswith(p + os.sep) or p.startswith(rp + os.sep):
                return False
        return True


# ---------------------------------------------------------------- second-chance eviction
# macOS APFS (and Linux relatime) update atime only when atime < mtime. Arming an entry sets
# atime just below mtime; any later read bumps it. Entries still unread after PROBATION go.

class SecondChance:
    def __init__(self, ctx):
        self.ctx, self.path = ctx, ctx.state / "armed.json"
        try:
            self.armed = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.armed = {}

    @staticmethod
    def sentinels(entry):
        out, stack = [], [(str(entry), 0)]
        while stack and len(out) < SENTINELS:
            d, depth = stack.pop()
            try:
                ents = sorted(os.scandir(d), key=lambda e: e.name)
            except OSError:
                if os.path.isfile(d):
                    out.append(d)
                continue
            for e in ents:
                if e.is_file(follow_symlinks=False):
                    out.append(e.path)
                elif e.is_dir(follow_symlinks=False) and depth < 2:
                    stack.append((e.path, depth + 1))
        return out[:SENTINELS]

    def was_read(self, entry) -> bool:
        for f in self.sentinels(entry):
            try:
                s = os.lstat(f)
            except OSError:
                continue
            if s.st_atime >= s.st_mtime:
                return True
        return False

    def arm(self, entry):
        for f in self.sentinels(entry):
            try:
                s = os.lstat(f)
                os.utime(f, (s.st_mtime - 1, s.st_mtime), follow_symlinks=False)
            except OSError:
                pass
        self.armed[entry] = self.ctx.now

    def atime_works(self) -> bool:
        if not hasattr(self, "_atime"):
            self.ctx.state.mkdir(parents=True, exist_ok=True)
            probe = self.ctx.state / ".atime-probe"
            try:
                probe.write_text("x")
                s = os.stat(probe)
                os.utime(probe, (s.st_mtime - 10, s.st_mtime))
                probe.read_text()
                self._atime = os.stat(probe).st_atime >= s.st_mtime
            except OSError:
                self._atime = False
        return self._atime

    def filter(self, items, apply: bool, skip_probation: bool):
        """Return items that may be deleted now; arm the rest (only when apply)."""
        ready, pending = [], 0
        if not skip_probation and not self.atime_works():
            return [], sum(i.size for i in items)
        for it in items:
            at = self.armed.get(it.path)
            if skip_probation or (at is not None and self.ctx.now - at >= PROBATION and not self.was_read(it.path)):
                ready.append(it)
            elif at is not None and self.was_read(it.path):
                self.armed.pop(it.path, None)      # in use: rescued, re-armed on a later sweep
                pending += it.size
            else:
                if apply and at is None:
                    self.arm(it.path)
                pending += it.size
        return ready, pending

    def save(self):
        self.armed = {k: v for k, v in self.armed.items() if os.path.lexists(k)}
        self.ctx.state.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.armed))
        os.replace(tmp, self.path)


# ---------------------------------------------------------------- core

def free_space(ctx):
    target = ctx.home if ctx.home.exists() else Path("/")
    u = shutil.disk_usage(target)
    return u.free, u.total


def is_low(free, total):
    return free < LOW_FREE_BYTES or free < total * LOW_FREE_FRACTION


def collect(ctx, tiers, only, apply, skip_probation):
    sc = SecondChance(ctx)
    out = []   # (rule, ready_items, pending_bytes)
    for r in RULES:
        if r.tier not in tiers or (only and r.id not in only):
            continue
        try:
            items = [i for i in r.find(ctx) if i.cmd or r.tier == "info" or ctx.allowed(i)]
        except Exception as e:  # a broken rule must never abort the sweep
            ctx.kept.append((r.id, 0, f"error: {e}"))
            continue
        pending = 0
        if r.second_chance:
            dels = [i for i in items if not i.cmd]
            ready, pending = sc.filter(dels, apply, skip_probation)
            items = ready + [i for i in items if i.cmd]
        if items or pending:
            out.append((r, items, pending))
    if apply:
        sc.save()
    return out


def run_cmd(cmd):
    # native prunes can wait on a lock held by long-running tools (e.g. uv-based MCP servers);
    # give up quickly rather than holding the sweep lock for minutes
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def remove(ctx, item: Item) -> int:
    if not ctx.allowed(item):
        return 0
    before, _, active = ctx.stats(item.path, ctx.now - MIN_IDLE)   # race guard: written meanwhile?
    if active:
        return 0
    try:
        if os.path.isdir(item.path) and not os.path.islink(item.path):
            shutil.rmtree(item.path, ignore_errors=True)
        else:
            os.unlink(item.path)
    except OSError:
        pass
    left = ctx.stats(item.path)[0] if os.path.lexists(item.path) else 0
    return max(0, before - left)


def ledger(ctx, freed, by_rule, source):
    if not freed:
        return
    ctx.state.mkdir(parents=True, exist_ok=True)
    with open(ctx.state / "ledger.jsonl", "a") as f:
        f.write(json.dumps({"t": ctx.now, "freed": freed, "by": by_rule, "src": source}) + "\n")


def sweep(ctx, tiers, only=None, source="manual", skip_probation=None):
    free, total = free_space(ctx)
    if skip_probation is None:
        skip_probation = free < CRITICAL_FREE_BYTES
    freed, by_rule = 0, {}
    for rule, items, _pending in collect(ctx, tiers, only, True, skip_probation):
        if rule.tier == "info":
            continue
        got = 0
        for it in items:
            if it.cmd:
                u0 = shutil.disk_usage(ctx.home).free if ctx.real_home else 0
                run_cmd(it.cmd)
                got += max(0, shutil.disk_usage(ctx.home).free - u0) if ctx.real_home else 0
            else:
                got += remove(ctx, it)
        if got:
            by_rule[rule.id] = got
            freed += got
    ledger(ctx, freed, by_rule, source)
    return freed, by_rule


# ---------------------------------------------------------------- commands

def cmd_status(ctx, a):
    free, total = free_space(ctx)
    low = is_low(free, total)
    if a.quiet and not low:
        return 0
    used = 100 * (1 - free / total)
    flag = "LOW - run storage-steward scan" if low else "ok"
    print(f"disk: {human(free)} free of {human(total)} ({used:.0f}% used) {flag}")
    return 0


def cmd_scan(ctx, a):
    tiers = ("auto", "confirm", "info")
    results = collect(ctx, tiers, set(a.only or []), False, a.no_probation)
    if a.json:
        print(json.dumps([{"rule": r.id, "tier": r.tier, "bytes": sum(i.size for i in its),
                           "pending": p, "items": len(its)} for r, its, p in results]))
        return 0
    free, total = free_space(ctx)
    print(f"disk: {human(free)} free of {human(total)} ({100 * (1 - free / total):.0f}% used)")
    heads = {"auto": "AUTO (sweep; regenerable, no data loss)",
             "confirm": "CONFIRM (ask user, then: sweep --tier confirm --only RULE --yes)",
             "info": "INFO (never auto-deleted)"}
    for tier in tiers:
        rows = []
        for r, its, pending in results:
            if r.tier != tier:
                continue
            size = sum(i.size for i in its)
            if size < 1 << 20 and not pending and not any(i.cmd for i in its):
                continue   # sub-MB rows cost tokens and reclaim nothing meaningful
            notes = [n for n in {i.note for i in its} if n]
            extra = f"{len(its)} item{'s' if len(its) != 1 else ''}"
            if any(i.cmd for i in its):
                extra = "native prune (size known after run)"
            if pending:
                extra += f", {human(pending)} on probation"
            if notes:
                extra += f" [{', '.join(sorted(notes))[:40]}]"
            rows.append((size, f"  {r.id:<24}{human(size):>9}  {extra}"))
        if not rows:
            continue
        rows.sort(key=lambda x: -x[0])
        total_t = sum(s for s, _ in rows)
        print(f"{heads[tier]}  {human(total_t)}")
        for _, line in rows[: a.top]:
            print(line)
        if len(rows) > a.top:
            print(f"  ... {len(rows) - a.top} more rules (--top N)")
    for rule, size, why in ctx.kept[:3]:
        print(f"kept: {rule} {human(size)} ({why})")
    tip = retention_tip(ctx)
    if tip:
        print(tip)
    return 0


def retention_tip(ctx):
    if not ctx.real_home:
        return ""
    try:
        s = json.loads((ctx.home / ".claude/settings.json").read_text())
    except (OSError, ValueError):
        s = {}
    if "cleanupPeriodDays" not in s:
        return 'tip: transcripts are kept 30d by default; install --retention 21 caps them'
    return ""


def cmd_sweep(ctx, a):
    tiers = ("auto", "confirm") if a.tier == "confirm" else ("auto",)
    if a.tier == "confirm" and not a.yes:
        print("refusing: confirm tier needs --yes (only after the user agreed)")
        return 2
    if a.dry_run:
        return cmd_scan(ctx, a)
    freed, by_rule = sweep(ctx, tiers, set(a.only or []), "manual", True if a.no_probation else None)
    free, total = free_space(ctx)
    top = ", ".join(f"{k} {human(v)}" for k, v in sorted(by_rule.items(), key=lambda x: -x[1])[:4])
    print(f"swept {human(freed)}" + (f" ({top})" if top else "") + f" | {human(free)} free")
    return 0


def cmd_report(ctx, a):
    try:
        rows = [json.loads(l) for l in (ctx.state / "ledger.jsonl").read_text().splitlines() if l.strip()]
    except OSError:
        rows = []
    if not rows:
        print("nothing reclaimed yet")
        return 0
    total = sum(r["freed"] for r in rows)
    days = max(1.0, (rows[-1]["t"] - rows[0]["t"]) / DAY)
    by = {}
    for r in rows:
        for k, v in r["by"].items():
            by[k] = by.get(k, 0) + v
    top = ", ".join(f"{k} {human(v)}" for k, v in sorted(by.items(), key=lambda x: -x[1])[:5])
    print(f"reclaimed {human(total)} over {days:.0f}d in {len(rows)} sweeps ({top})")
    return 0


# ---------------------------------------------------------------- hooks

def _stamp_due(path: Path, interval: float, now: float) -> bool:
    try:
        return now - path.stat().st_mtime >= interval
    except OSError:
        return True


def _touch(path: Path, now: float):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    os.utime(path, (now, now))


def cmd_hook(ctx, a):
    try:
        data = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
    except ValueError:
        data = {}
    ctx.session = data.get("session_id") or ctx.session
    if data.get("cwd"):
        ctx.cwd = Path(data["cwd"]).resolve()
    if a.event == "prompt":
        free, total = free_space(ctx)
        stamp = ctx.state / f"warned-{ctx.session or 'x'}"
        if is_low(free, total) and (a.self_test or _stamp_due(stamp, WARN_INTERVAL, ctx.now)):
            if not a.self_test:
                _touch(stamp, ctx.now)
            print(f"[storage-steward] disk low: {human(free)} free "
                  f"({100 * free / total:.0f}%). Before big writes, run the storage-steward skill's scan.")
        return 0
    # stop / session-end: detach so the agent never waits on cleanup
    if a.self_test:
        return 0      # install's self-test: measure the hook path, never start a sweep
    if not a.foreground:
        args = [sys.executable, os.path.abspath(__file__)]
        for flag, val in (("--home", a.home), ("--tmp", a.tmp), ("--user-tmp", a.user_tmp),
                          ("--now", a.now), ("--session", ctx.session), ("--cwd", ctx.cwd)):
            if val:
                args += [flag, str(val)]
        args += ["hook", a.event, "--foreground"]
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    ctx.state.mkdir(parents=True, exist_ok=True)
    with open(ctx.state / "sweep.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another sweep is running
        free, total = free_space(ctx)
        stamp = ctx.state / "last-sweep"
        if _stamp_due(stamp, SWEEP_INTERVAL, ctx.now) or is_low(free, total):
            _touch(stamp, ctx.now)
            sweep(ctx, ("auto",), source=f"hook:{a.event}")
    return 0


def _settings_path(a):
    return Path(a.settings or os.path.expanduser("~/.claude/settings.json"))


def _our_hooks():
    me = f"python3 '{os.path.abspath(__file__)}'"
    return {
        "UserPromptSubmit": {"type": "command", "command": f"{me} hook prompt", "timeout": 10},
        "Stop": {"type": "command", "command": f"{me} hook stop", "timeout": 10},
        "SessionEnd": {"type": "command", "command": f"{me} hook session-end", "timeout": 10},
    }


def _ours(command: str) -> bool:
    return MARK in command or "steward.py' hook " in command


def _strip(settings):
    hooks = settings.get("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            hs = [h for h in g.get("hooks", []) if not _ours(h.get("command", ""))]
            if hs:
                groups.append({**g, "hooks": hs})
        if groups:
            hooks[ev] = groups
        else:
            hooks.pop(ev)
    if not hooks:
        settings.pop("hooks", None)
    return settings


def _write_settings(path: Path, settings):
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".bak-{int(time.time())}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, indent=2) + "\n")
    os.replace(tmp, path)


def cmd_install(ctx, a):
    path = _settings_path(a)
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        print(f"refusing: {path} is not valid JSON")
        return 2
    settings = _strip(settings)
    hooks = settings.setdefault("hooks", {})
    for ev, h in _our_hooks().items():
        hooks.setdefault(ev, []).append({"hooks": [h]})
    if a.retention and "cleanupPeriodDays" not in settings:
        settings["cleanupPeriodDays"] = a.retention
    _write_settings(path, settings)
    extra = f", cleanupPeriodDays={settings.get('cleanupPeriodDays')}" if a.retention else ""
    print(f"installed hooks (UserPromptSubmit, Stop, SessionEnd) in {path}{extra}; backup saved; re-run safe")
    print(_self_test(a))
    return 0


def _self_test(a) -> str:
    """Prove the hooks are cheap so nobody has to read this file or fire them by hand."""
    base = [sys.executable, os.path.abspath(__file__)]
    for flag, val in (("--home", a.home), ("--tmp", a.tmp), ("--user-tmp", a.user_tmp)):
        if val:
            base += [flag, val]
    out = []
    for ev in ("prompt", "stop"):
        t0 = time.perf_counter()
        p = subprocess.run(base + ["hook", ev, "--self-test"], input='{"session_id":"self-test"}',
                           capture_output=True, text=True, timeout=30)
        ms = (time.perf_counter() - t0) * 1000
        note = " (disk is low now, so it warned)" if ev == "prompt" and p.stdout else ""
        out.append(f"{ev} hook {ms:.0f} ms, {len(p.stdout)} bytes output{note}")
    return ("self-test: " + "; ".join(out) +
            " (prompt prints only when disk is low; stop/session-end sweep detached, max every 3h; "
            "self-test starts no sweep)")


def cmd_uninstall(ctx, a):
    path = _settings_path(a)
    if not path.exists():
        print("nothing to uninstall")
        return 0
    _write_settings(path, _strip(json.loads(path.read_text())))
    print(f"removed storage-steward hooks from {path}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="steward.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home"), p.add_argument("--tmp"), p.add_argument("--user-tmp")
    p.add_argument("--now", type=float), p.add_argument("--cwd"), p.add_argument("--session")
    p.add_argument("--protect", action="append")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--quiet", action="store_true")
    for name in ("scan", "sweep"):
        s = sub.add_parser(name)
        s.add_argument("--only", action="append")
        s.add_argument("--top", type=int, default=6)
        s.add_argument("--json", action="store_true")
        s.add_argument("--no-probation", action="store_true", help="evict idle caches now (disk emergency)")
        if name == "sweep":
            s.add_argument("--tier", choices=("auto", "confirm"), default="auto")
            s.add_argument("--yes", action="store_true")
            s.add_argument("--dry-run", action="store_true")
    sub.add_parser("report")
    s = sub.add_parser("hook"); s.add_argument("event", choices=("prompt", "stop", "session-end"))
    s.add_argument("--foreground", action="store_true")
    s.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    for name in ("install", "uninstall"):
        s = sub.add_parser(name); s.add_argument("--settings")
        if name == "install":
            s.add_argument("--retention", type=int, help="also set cleanupPeriodDays if unset")
    a = p.parse_args(argv)
    if getattr(a, "only", None):
        a.only = [x for o in a.only for x in o.split(",")]
    ctx = Ctx(a)
    return {"status": cmd_status, "scan": cmd_scan, "sweep": cmd_sweep, "report": cmd_report,
            "hook": cmd_hook, "install": cmd_install, "uninstall": cmd_uninstall}[a.cmd](ctx, a)


if __name__ == "__main__":
    sys.exit(main())
