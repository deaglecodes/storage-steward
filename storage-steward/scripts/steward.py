#!/usr/bin/env python3
"""storage-steward: keep coding-agent + dev-tool disk usage in check, with tiny output.

  status      one line of free space (--quiet: print only when low)
  scan        dry run: what a sweep would reclaim, by tier (<= ~15 lines)
  sweep       reclaim auto tier; add --tier confirm --yes [--only RULE] after the user agrees
  report      total reclaimed so far (ledger)
  hook EVENT  hook entry point for any agent: prompt | stop | session-end  [--agent NAME]
  install     link the skill + add hooks for detected agents (Claude Code, Codex, Cursor, Gemini CLI)
              [--agents LIST] [--schedule]; uninstall removes them
  schedule    install | uninstall | status of an OS timer (launchd/systemd/cron) for any agent
  rules       the effective policy: every rule, its tier and age threshold, your keep list
  config      change it: set RULE --tier auto|confirm|info|off --idle 14d | keep PATH | add NAME --path GLOB

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
import agents  # noqa: E402
import policy  # noqa: E402
import rules  # noqa: E402
from rules import DAY, GIB, HOUR, Item  # noqa: E402

__version__ = "0.2.0"

LOW_FREE_BYTES = 20 * GIB          # default: warn below this ... (config: warn_below_gb)
LOW_FREE_FRACTION = 0.05           # ... or below this fraction free (config: warn_below_percent)
CRITICAL_FREE_BYTES = 5 * GIB      # skip probation when this tight
MIN_IDLE = HOUR                    # never touch anything written in the last hour
PROBATION = 7 * DAY                # default second-chance probation (config: probation_days)
SWEEP_INTERVAL = 3 * HOUR          # default hook sweep interval (config: sweep_every_hours)
WARN_INTERVAL = 6 * HOUR           # low-disk warning at most this often per session
SENTINELS = 64                     # files armed per cache entry
REMOVED_LOG_MAX = 1 << 20          # removed.log keeps roughly the newest 1 MB of entries
MARK = "storage-steward"           # state dir name (~/.cache/storage-steward)
NEVER = ("", "Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music", "Library",
         ".ssh", ".gnupg", ".claude", ".claude/settings.json", ".claude.json", ".claude/memory",
         ".claude/skills", ".claude/plugins", ".codex", ".codex/auth.json", ".codex/config.toml")
# never deleted, and nothing inside them either, whatever a rule (even one the user wrote) says:
# credentials, agent settings and instructions, memory, skills, and this tool's own policy
NEVER_TREE = (".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker/config.json", ".netrc", ".password-store",
              ".config/gh", ".config/gcloud", "Library/Keychains", ".config/storage-steward", ".agents/skills",
              ".claude.json", ".claude/settings.json", ".claude/settings.local.json", ".claude/CLAUDE.md",
              ".claude/memory", ".claude/skills", ".claude/plugins", ".claude/agents", ".claude/commands",
              ".claude/hooks", ".claude/rules", ".codex/auth.json", ".codex/config.toml", ".codex/AGENTS.md",
              ".codex/rules", ".gemini/settings.json", ".gemini/GEMINI.md", ".cursor/rules", ".cursor/mcp.json")


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
        self.session = getattr(a, "session", None) or (None if sandbox else (
            os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("GEMINI_SESSION_ID")))
        protect = [os.path.abspath(p) for p in (getattr(a, "protect", None) or [])]
        self.protect = rules.KeepList(self.home, protect)     # --protect: same identity matching as keep
        host = None if sandbox else os.environ.get("CLAUDE_CODE_HOST_SESSION_ID")
        self.protect_names = {host} if host else set()
        self.state = self.home / ".cache" / MARK
        self.policy = policy.Policy(self.home, self.real_home)
        n = self.policy.numbers
        self.sweep_interval = n["sweep_every_hours"] * HOUR
        self.probation = n["probation_days"] * DAY
        raw = self.policy.raw          # only an explicit setting replaces the module default
        self.warn_bytes = n["warn_below_gb"] * GIB if "warn_below_gb" in raw else LOW_FREE_BYTES
        self.warn_fraction = n["warn_below_percent"] / 100 if "warn_below_percent" in raw else LOW_FREE_FRACTION
        self.kept = []          # (rule, bytes, reason) reported but not removable
        self.use_ctime = self.real_home   # sandboxes and the simulator fake time with mtimes only
        self._never = {os.path.realpath(self.home / n) for n in NEVER}
        # identities, so no spelling (APFS case, `..`, `//`, symlinked parents) slips past the guards
        self._lineage = {}                               # per-run cache: folder -> (real path, identities)
        self._never_above = set()
        for n in NEVER + NEVER_TREE:
            target = rules.node(self.home / n)           # where a symlinked one (iCloud Documents) points
            self._never_above.update(rules.lineage(self.home / n) + ([target] if target else []))
        self._never_tree = {x for x in (rules.node(self.home / n) for n in NEVER_TREE) if x}
        self._personal = {x for x in (rules.node(self.home / d) for d in rules.PERSONAL_DIRS) if x}

    # one walk: allocated bytes (hardlinks once), newest mtime, early-exit when active
    def stats(self, path, cutoff=None, use_ctime=False):
        try:
            st = os.lstat(path)
        except OSError:
            return 0, 0.0, False
        size, newest = st.st_blocks * 512, max(st.st_mtime, st.st_ctime) if use_ctime else st.st_mtime
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
                    t = max(s.st_mtime, s.st_ctime) if use_ctime else s.st_mtime
                    if t > newest:
                        newest = t
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

    def allowed(self, item: Item, tier: str = "auto") -> bool:
        """May `item` be deleted by a rule of this tier? Every guard here holds whatever the rule says."""
        if not item.path or not item.root:
            return False
        try:
            rp = os.path.join(rules.real_parent(item.path, self._lineage)[0], os.path.basename(item.path))
            root = os.path.realpath(item.root)
        except (OSError, ValueError):
            return False
        if rp == root or not rp.startswith(root + os.sep):
            return False
        if rp in self._never or any(n.startswith(rp + os.sep) for n in self._never):
            return False
        lin = rules.lineage(item.path, self._lineage)
        if not lin or lin[0] in self._never_above:       # gone, or a protected path or one of its parents
            return False
        if any(n in self._never_tree for n in lin):      # inside credentials, agent config, memory, skills
            return False
        if tier == "auto" and any(n in self._personal for n in lin):
            return False                                 # automatic sweeps never reach into personal folders
        if self.session and self.session in rp:
            return False
        if any(n in rp for n in self.protect_names):
            return False
        if self.policy.keeper.protects(item.path, self._lineage):
            return False
        if self.protect.patterns and self.protect.protects(item.path, self._lineage):
            return False
        return True


# ---------------------------------------------------------------- second-chance eviction
# macOS APFS (and Linux relatime) update atime only when atime < mtime. Arming an entry sets
# atime just below mtime; any later read bumps it. Entries still unread after PROBATION go.

class SecondChance:
    def __init__(self, ctx):
        self.ctx, self.path = ctx, ctx.state / "armed.json"
        try:
            armed = json.loads(self.path.read_text())
        except (OSError, ValueError):
            armed = {}
        self.armed = {k: v for k, v in armed.items() if isinstance(v, (int, float))} if isinstance(armed, dict) else {}

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
            probe = self.ctx.state / ".atime-probe"
            try:
                self.ctx.state.mkdir(parents=True, exist_ok=True)
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
            if skip_probation or (at is not None and self.ctx.now - at >= self.ctx.probation and not self.was_read(it.path)):
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


def is_low(free, total, ctx=None):
    warn_b = ctx.warn_bytes if ctx else LOW_FREE_BYTES
    warn_f = ctx.warn_fraction if ctx else LOW_FREE_FRACTION
    return free < warn_b or free < total * warn_f


def collect(ctx, tiers, only, apply, skip_probation):
    sc = SecondChance(ctx)
    out = []   # (rule, effective tier, ready_items, pending_bytes)
    for r, tier, days, _ov in ctx.policy.effective():
        if tier == "off" or tier not in tiers or (only and r.id not in only):
            continue
        try:
            items = [i for i in r.find(ctx, days if days is not None else 0)
                     if i.cmd or tier == "info" or ctx.allowed(i, tier)]
        except Exception as e:  # a broken rule must never abort the sweep
            ctx.kept.append((r.id, 0, f"error: {e}"))
            continue
        pending = 0
        if r.second_chance:
            dels = [i for i in items if not i.cmd]
            ready, pending = sc.filter(dels, apply, skip_probation)
            items = ready + [i for i in items if i.cmd]
        if items or pending:
            out.append((r, tier, items, pending))
    if apply:
        try:
            sc.save()
        except OSError:
            pass            # can't record armed entries (disk full, odd state dir): they re-arm next time
    return out


def run_cmd(cmd):
    # native prunes can wait on a lock held by long-running tools (e.g. uv-based MCP servers);
    # give up quickly rather than holding the sweep lock for minutes
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def remove(ctx, item: Item, tier: str = "auto") -> int:
    if not ctx.allowed(item, tier):
        return 0
    # race guard: written (or restored, extracted, moved in) meanwhile?
    before, _, active = ctx.stats(item.path, ctx.now - MIN_IDLE, ctx.use_ctime)
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
    try:
        ctx.state.mkdir(parents=True, exist_ok=True)
        with open(ctx.state / "ledger.jsonl", "a") as f:
            f.write(json.dumps({"t": ctx.now, "freed": freed, "by": by_rule, "src": source}) + "\n")
    except OSError:
        pass                # the space is freed either way; only the report misses it


def log_removed(ctx, lines):
    """Append what was deleted to removed.log (one line per path), trimming it to the newest ~1 MB."""
    if not lines:
        return
    path = ctx.state / "removed.log"
    try:
        ctx.state.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write("".join(lines))
        if path.stat().st_size > REMOVED_LOG_MAX:
            tail = path.read_bytes()[-REMOVED_LOG_MAX // 2:]
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(tail[tail.find(b"\n") + 1:])
            os.replace(tmp, path)
    except OSError:
        pass


def sweep(ctx, tiers, only=None, source="manual", skip_probation=None):
    if ctx.policy.paused:   # the user's keep list or rules can't be read: deleting now could ignore them
        return 0, {}
    free, total = free_space(ctx)
    if skip_probation is None:
        skip_probation = free < CRITICAL_FREE_BYTES
    freed, by_rule = 0, {}
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ctx.now))

    def logged(rule_id, n, what):          # written as each delete happens, so a killed sweep is still on record
        what = what.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        log_removed(ctx, [f"{stamp}\t{rule_id}\t{n}\t{what}\n"])
    for rule, tier, items, _pending in collect(ctx, tiers, only, True, skip_probation):
        if tier == "info":
            continue
        got = 0
        for it in items:
            if it.cmd:
                u0 = shutil.disk_usage(ctx.home).free if ctx.real_home else 0
                ok = run_cmd(it.cmd)
                n = max(0, shutil.disk_usage(ctx.home).free - u0) if ctx.real_home else 0
                got += n
                if ok:
                    logged(rule.id, n, "$ " + " ".join(it.cmd))
            else:
                n = remove(ctx, it, tier)
                got += n
                if n or not os.path.lexists(it.path):
                    logged(rule.id, n, it.path)
        if got:
            by_rule[rule.id] = got
            freed += got
    ledger(ctx, freed, by_rule, source)
    return freed, by_rule


# ---------------------------------------------------------------- commands

def cmd_status(ctx, a):
    free, total = free_space(ctx)
    low = is_low(free, total, ctx)
    if a.quiet and not low:
        return 0
    used = 100 * (1 - free / total)
    flag = "LOW - run storage-steward scan" if low else "ok"
    print(f"disk: {human(free)} free of {human(total)} ({used:.0f}% used) {flag}")
    return 0


def tilde(ctx, path: str) -> str:
    h = str(ctx.home)
    return "~" + path[len(h):] if path == h or path.startswith(h + os.sep) else path


PATHS_MAX = 40


def cmd_scan(ctx, a):
    tiers = ("auto", "confirm", "info")
    results = collect(ctx, tiers, set(a.only or []), False, a.no_probation)
    if getattr(a, "paths", False):
        rows = [(r.id, tier, i) for r, tier, its, _p in results for i in sorted(its, key=lambda i: -i.size)]
        for rid, tier, i in rows[:PATHS_MAX]:
            what = " ".join(i.cmd) if i.cmd else tilde(ctx, i.path)
            print(f"{rid:<22} {tier:<7} {human(i.size):>9}  {what}")
        if len(rows) > PATHS_MAX:
            print(f"... {len(rows) - PATHS_MAX} more (narrow with --only RULE)")
        if not rows:
            print("nothing to list")
        return 0
    if a.json:
        print(json.dumps([{"rule": r.id, "tier": tier, "bytes": sum(i.size for i in its),
                           "pending": p, "items": len(its)} for r, tier, its, p in results]))
        return 0
    free, total = free_space(ctx)
    print(f"disk: {human(free)} free of {human(total)} ({100 * (1 - free / total):.0f}% used)")
    heads = {"auto": "AUTO (sweep; regenerable, no data loss)",
             "confirm": "CONFIRM (ask user, then: sweep --tier confirm --only RULE --yes)",
             "info": "INFO (never auto-deleted)"}
    for tier in tiers:
        rows = []
        for r, rtier, its, pending in results:
            if rtier != tier:
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
    for err in ctx.policy.errors[:3]:
        print(f"config problem: {err} (steward.py config show)")
    if ctx.policy.paused:
        print("deletes paused until the config is fixed; nothing will be removed")
    tip = retention_tip(ctx)
    if tip:
        print(tip)
    return 0


def cmd_rules(ctx, a):
    """The effective policy: every rule with its tier and threshold, then the keep list."""
    rows = ctx.policy.effective()
    if a.json:
        print(json.dumps([{"rule": r.id, "tier": t, "idle_days": d, "label": r.label, "custom": r.custom,
                           "overridden": ov} for r, t, d, ov in rows] + [{"keep": ctx.policy.keep}]))
        return 0
    src = ctx.policy.path if ctx.policy.path.exists() else "built-in defaults (no config file yet)"
    print(f"policy: {src}")
    for tier in ("auto", "confirm", "info", "off"):
        sel = [(r, d, ov) for r, t, d, ov in rows if t == tier]
        if not sel:
            continue
        print(tier.upper())
        for r, d, ov in sel:
            when = "—" if d is None else (f"{d * 24:g}h" if d < 1 else f"{d:g}d")
            mark = "+" if r.custom else ("*" if ov else " ")
            print(f" {mark}{r.id:<24}{when:>6}  {r.label}")
    print(f"keep: {', '.join(ctx.policy.keep) or '(nothing extra)'}   (* changed by you, + your own rule)")
    for err in ctx.policy.errors:
        print(f"config problem: {err}")
    return 0


def cmd_config(ctx, a):
    print(policy.edit(ctx.home, ctx.real_home, a))
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
    if a.tier == "confirm" and not a.only:
        print("refusing: name the rules the user approved with --only RULE[,RULE]")
        return 2
    if a.dry_run:
        return cmd_scan(ctx, a)
    if ctx.policy.paused:
        print(f"paused: {ctx.policy.paused}; nothing removed. Fix it, then check with `steward.py config show`")
        return 0
    freed, by_rule = sweep(ctx, tiers, set(a.only or []), "manual", True if a.no_probation else None)
    free, total = free_space(ctx)
    top = ", ".join(f"{k} {human(v)}" for k, v in sorted(by_rule.items(), key=lambda x: -x[1])[:4])
    print(f"swept {human(freed)}" + (f" ({top})" if top else "") + f" | {human(free)} free")
    return 0


def cmd_report(ctx, a):
    rows = []
    try:
        for line in (ctx.state / "ledger.jsonl").read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("by"), dict) and "freed" in row and "t" in row:
                rows.append(row)
    except OSError:
        pass
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
    print(f"every removed path: {tilde(ctx, str(ctx.state / 'removed.log'))}")
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


# agents whose hooks must print JSON for these events (Claude/Codex prompt hooks take plain text)
JSON_OUT = {"codex": {"stop"}, "cursor": {"stop", "session-end"}, "gemini": {"prompt", "stop", "session-end"}}


def _emit(agent: str, event: str, warning: str = ""):
    if agent == "gemini":
        out = {"hookSpecificOutput": {"hookEventName": "BeforeAgent", "additionalContext": warning}} if warning else {}
        print(json.dumps(out))
    elif warning:
        print(warning)
    elif event in JSON_OUT.get(agent, ()):
        print("{}")


def _hook_input() -> dict:
    """The agent's JSON on stdin; anything else (no stdin, garbage, a list) reads as {}."""
    try:
        data = json.loads(sys.stdin.read() or "{}") if not sys.stdin.isatty() else {}
    except (ValueError, OSError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def cmd_hook(ctx, a):
    """Never fails and never makes the agent wait: any error ends quietly in the agent's own format."""
    said = []
    try:
        return _hook(ctx, a, said)
    except Exception:
        if not said and not a.foreground:
            _emit(a.agent, a.event)
        return 0


def _hook(ctx, a, said):
    data = _hook_input()
    sid = data.get("session_id") or data.get("conversation_id")
    if isinstance(sid, str) and sid:
        ctx.session = sid
    roots = data.get("workspace_roots")
    cwd = data.get("cwd") or (roots[0] if isinstance(roots, list) and roots else None)
    if isinstance(cwd, str) and cwd:
        ctx.cwd = Path(cwd).resolve()
    if a.event == "prompt":
        free, total = free_space(ctx)
        stamp = ctx.state / f"warned-{ctx.session or 'x'}"
        warning = ""
        if is_low(free, total, ctx) and (a.self_test or _stamp_due(stamp, WARN_INTERVAL, ctx.now)):
            if not a.self_test:
                try:
                    _touch(stamp, ctx.now)
                except OSError:
                    pass        # disk full or odd state dir: warn anyway, just not throttled
            warning = (f"[storage-steward] disk low: {human(free)} free ({100 * free / total:.0f}%). "
                       "Before big writes, run the storage-steward skill's scan.")
        said.append(1)
        _emit(a.agent, a.event, warning)
        return 0
    # stop / session-end: answer the agent at once, sweep in a detached process
    if not a.foreground:
        said.append(1)
        _emit(a.agent, a.event)
    if a.self_test:
        return 0      # install's self-test: measure the hook path, never start a sweep
    if not a.foreground:
        args = [sys.executable, os.path.abspath(__file__)]
        for flag, val in (("--home", a.home), ("--tmp", a.tmp), ("--user-tmp", a.user_tmp),
                          ("--now", a.now), ("--session", ctx.session), ("--cwd", ctx.cwd)):
            if val:
                args += [flag, str(val)]
        args += ["hook", a.event, "--agent", a.agent, "--foreground"]
        subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return 0
    if ctx.policy.paused:
        return 0
    try:
        ctx.state.mkdir(parents=True, exist_ok=True)
        lock = open(ctx.state / "sweep.lock", "w")
    except OSError:
        return 0      # no state dir means no lock and no throttle: skip rather than risk overlapping sweeps
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 0  # another sweep is running
        free, total = free_space(ctx)
        stamp = ctx.state / "last-sweep"
        if _stamp_due(stamp, ctx.sweep_interval, ctx.now) or is_low(free, total, ctx):
            _touch(stamp, ctx.now)
            sweep(ctx, ("auto",), source=f"hook:{a.agent}:{a.event}")
    return 0


def _self_test(a, keys) -> str:
    """Prove each installed hook is fast, silent and speaks its agent's format, without sweeping."""
    base = [sys.executable, os.path.abspath(__file__)]
    for flag, val in (("--home", a.home), ("--tmp", a.tmp), ("--user-tmp", a.user_tmp)):
        if val:
            base += [flag, val]
    worst, bad, n, warned = 0.0, [], 0, False
    for key in keys:
        for ev in sorted(set(agents.BY_KEY[key].events.values()) & {"prompt", "stop"}):
            t0 = time.perf_counter()
            p = subprocess.run(base + ["hook", ev, "--agent", key, "--self-test"],
                               input='{"session_id":"self-test"}', capture_output=True, text=True, timeout=30)
            worst, n = max(worst, (time.perf_counter() - t0) * 1000), n + 1
            if ev in JSON_OUT.get(key, ()):
                try:
                    json.loads(p.stdout)
                except ValueError:
                    bad.append(f"{key}:{ev}")
            warned |= ev == "prompt" and "disk low" in p.stdout
    fmt = f"bad output: {', '.join(bad)}" if bad else "output format ok"
    low = "; disk is low now, so the prompt check warned" if warned else ""
    return f"self-test: {n} hooks, slowest {worst:.0f} ms, {fmt}{low}; no sweep started"


def cmd_install(ctx, a):
    script = Path(os.path.abspath(__file__))
    canonical = script.parent.parent
    settings = Path(a.settings) if a.settings else None    # explicit Claude settings file (custom setups, tests)
    targets = [agents.BY_KEY["claude"]] if settings else agents.pick(ctx.home, a.agents)
    if not targets:
        print("no supported agent found; use --agents NAME or --schedule")
    record = agents.read_record(ctx.state)
    owned = agents.owned_retention(record, settings or ctx.home / agents.BY_KEY["claude"].config)
    if a.dry_run:
        print(f"dry run for home {ctx.home}: nothing written")
        print("\n".join(agents.plan(targets, ctx.home, settings, a.retention, owned)))
        if a.schedule:
            print("  scheduler: would add an OS timer (every 3h)")
        return 0
    lines, notes, hooked, skipped = [], [], [], 0
    for ag in targets:
        try:                             # hooks first: a config we can't parse skips the whole agent
            edit = agents.write_hooks(ag, ctx.home, script, a.retention, settings, owned) if ag.config else None
        except agents.ConfigError as e:
            lines.append(f"  {ag.name}: skipped: {e}")
            skipped += 1
            continue
        parts = [] if settings else [agents.link_skill(ag, ctx.home, canonical)]
        if edit:
            hooked.append(ag.key)
            parts.append(f"hooks in {edit.path}" + ("" if edit.changed else " (unchanged)"))
            notes += [f"  {edit.note}"] if edit.note else []
            if edit.retention is not None:
                agents.remember_retention(ctx.state, record, edit.path, edit.retention)
        else:
            parts.append("no hook API, covered by --schedule")
        lines.append(f"  {ag.name}: " + "; ".join(parts))
    if a.schedule:
        lines.append("  scheduler: " + agents.schedule(ctx.home, script, "install", real_home=ctx.real_home))
    print(f"installed for {len(targets) - skipped} of {len(targets)} agent(s); "
          "each edited file backed up next to it; re-run safe")
    print("\n".join(lines + notes))
    if hooked:
        print(_self_test(a, hooked))
    return 1 if skipped else 0


def cmd_uninstall(ctx, a):
    script = Path(os.path.abspath(__file__))
    if a.settings:                       # narrow: only our hooks in that one file
        if a.purge:
            print("--purge is ignored with --settings")
        try:
            edit = agents.remove_hooks(agents.BY_KEY["claude"], ctx.home, Path(a.settings))
        except agents.ConfigError as e:
            print(f"  Claude Code: skipped: {e}")
            return 1
        print(f"removed storage-steward hooks from {a.settings}" if edit and edit.hooks
              else f"no storage-steward hooks in {a.settings}")
        return 0
    lines, code = agents.uninstall(ctx.home, ctx.state, policy.path_for(ctx.home, ctx.real_home), script,
                                   ctx.real_home, a.purge)
    print("\n".join(lines))
    return code


def cmd_schedule(ctx, a):
    print(agents.schedule(ctx.home, Path(os.path.abspath(__file__)), a.action, a.dry_run, real_home=ctx.real_home))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="steward.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--home"), p.add_argument("--tmp"), p.add_argument("--user-tmp")
    p.add_argument("--now", type=float), p.add_argument("--cwd"), p.add_argument("--session")
    p.add_argument("--protect", action="append")
    p.add_argument("--version", action="version", version=f"storage-steward {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status"); s.add_argument("--quiet", action="store_true")
    for name in ("scan", "sweep"):
        s = sub.add_parser(name)
        s.add_argument("--only", action="append")
        s.add_argument("--top", type=int, default=6)
        s.add_argument("--json", action="store_true")
        s.add_argument("--no-probation", action="store_true", help="evict idle caches now (disk emergency)")
        if name == "scan":
            s.add_argument("--paths", action="store_true", help="list every path a sweep would remove")
        if name == "sweep":
            s.add_argument("--tier", choices=("auto", "confirm"), default="auto")
            s.add_argument("--yes", action="store_true")
            s.add_argument("--dry-run", action="store_true")
    sub.add_parser("report")
    s = sub.add_parser("hook"); s.add_argument("event", choices=("prompt", "stop", "session-end"))
    s.add_argument("--agent", default="claude", choices=[x.key for x in agents.AGENTS] + ["scheduler"])
    s.add_argument("--foreground", action="store_true")
    s.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    for name in ("install", "uninstall"):
        s = sub.add_parser(name)
        s.add_argument("--settings", help="explicit Claude Code settings.json (Claude only)")
        if name == "install":
            s.add_argument("--agents", default="auto", help="auto (detected), all, or e.g. claude,codex,cursor,gemini")
            s.add_argument("--schedule", action="store_true", help="also add an OS timer (covers any agent)")
            s.add_argument("--retention", type=agents.retention_days, metavar="DAYS",
                           help="also set Claude Code cleanupPeriodDays if unset (uninstall reverts it)")
            s.add_argument("--dry-run", action="store_true", help="list what would change; write nothing")
        else:
            s.add_argument("--purge", action="store_true", help="also remove your policy file and the state dir")
    s = sub.add_parser("schedule"); s.add_argument("action", choices=("install", "uninstall", "status"))
    s.add_argument("--dry-run", action="store_true")
    s = sub.add_parser("rules", help="show the effective policy"); s.add_argument("--json", action="store_true")
    c = sub.add_parser("config", help="change what goes and what stays").add_subparsers(dest="action", required=True)
    c.add_parser("show")
    s = c.add_parser("set"); s.add_argument("rule"); s.add_argument("--tier", choices=policy.TIERS); s.add_argument("--idle")
    s = c.add_parser("unset"); s.add_argument("rule")
    for name in ("keep", "unkeep"):
        s = c.add_parser(name); s.add_argument("paths", nargs="+")
    s = c.add_parser("add"); s.add_argument("name"); s.add_argument("--path", action="append", required=True)
    s.add_argument("--idle", default="30"); s.add_argument("--tier", default="confirm", choices=policy.TIERS)
    s.add_argument("--label")
    s = c.add_parser("drop"); s.add_argument("name")
    a = p.parse_args(argv)
    if getattr(a, "only", None):
        a.only = [x for o in a.only for x in o.split(",")]
    ctx = Ctx(a)
    return {"status": cmd_status, "scan": cmd_scan, "sweep": cmd_sweep, "report": cmd_report, "hook": cmd_hook,
            "install": cmd_install, "uninstall": cmd_uninstall, "schedule": cmd_schedule,
            "rules": cmd_rules, "config": cmd_config}[a.cmd](ctx, a)


if __name__ == "__main__":
    sys.exit(main())
