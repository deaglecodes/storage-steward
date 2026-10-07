"""Rule catalog for storage-steward.

Each rule finds candidates and declares a tier:
  auto    - regenerable or agent junk; at worst costs a re-download/rebuild. Hooks sweep these.
  confirm - recoverable only from elsewhere (git, re-install) or user history; ask first.
  info    - reported for awareness; the tool never deletes these.

Paths and thresholds come from the GitHub issues cited in references/targets.md.
"""
from __future__ import annotations

import fnmatch
import glob
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional

DAY = 86400.0
HOUR = 3600.0
GIB = 1 << 30
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DEP_DIRS = {"node_modules", ".venv", "venv", ".next", ".turbo", ".nuxt", ".svelte-kit", ".parcel-cache"}
PROJECT_MARKERS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", ".git")
SKIP_HOME_DIRS = {"Library", "Applications", "Pictures", "Movies", "Music", "Downloads", "Public"}


@dataclass
class Item:
    path: str               # file or dir to remove ("" for a native command)
    size: int               # bytes (0 when unknown, e.g. native prune)
    root: str               # deletion guard: path must sit strictly inside root
    note: str = ""
    cmd: Optional[List[str]] = None


@dataclass
class Rule:
    id: str
    tier: str
    label: str
    find: Callable[["object", float], Iterable[Item]]
    days: Optional[float] = None     # default idle threshold in days (None: not age-based)
    second_chance: bool = False      # read-mostly cache: arm, then evict only if unread
    custom: bool = False             # defined by the user in config.json


# ---------------------------------------------------------------- helpers

def kids(d: Path) -> List[Path]:
    try:
        return sorted(Path(d).iterdir())
    except OSError:
        return []


def idle_items(ctx, root: Path, idle_s: float, depth: int = 1, match=None, note: str = "") -> Iterable[Item]:
    """Entries `depth` levels under root whose whole subtree is untouched for idle_s."""
    level = [Path(root)]
    for _ in range(depth):
        level = [k for d in level for k in kids(d) if d.is_dir() and not d.is_symlink()]
    cutoff = ctx.now - idle_s
    for p in level:
        if match and not match(p):
            continue
        size, _newest, aborted = ctx.stats(p, cutoff)
        if not aborted:
            yield Item(str(p), size, str(root), note)


def which(ctx, tool: str) -> Optional[str]:
    return shutil.which(tool) if ctx.real_home else None


def native(ctx, tool: str, args: List[str], measure: Optional[Path], note: str) -> Iterable[Item]:
    exe = which(ctx, tool)
    if exe and (measure is None or measure.exists()):
        yield Item("", 0, "", note, cmd=[exe] + args)


# ---------------------------------------------------------------- auto tier

def claude_task_output(ctx, days):
    base = ctx.claude_tmp
    if not base or not base.is_dir():
        return
    for f in list(base.glob("*/*/tasks/*.output")) + list(base.glob("*/tasks/*.output")):
        size, newest, _ = ctx.stats(f)
        idle = ctx.now - newest
        if idle > days * DAY or (size >= GIB and idle > HOUR):
            yield Item(str(f), size, str(base), "runaway" if size >= GIB else "")


def claude_tmp_sessions(ctx, days):
    base = ctx.claude_tmp
    if not base or not base.is_dir():
        return
    yield from idle_items(ctx, base, days * DAY, depth=2, match=lambda p: bool(UUID_RE.match(p.name)))
    yield from idle_items(ctx, base, days * DAY, match=lambda p: p.name.startswith("cache-break-state-"))


def desktop_sandbox_plugins(ctx, days):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    for sb in root.glob("*/*/local_*"):
        plug = sb / ".claude" / "plugins"
        if not plug.is_dir():
            continue
        _, _, active = ctx.stats(sb, ctx.now - days * DAY)
        if not active:
            yield Item(str(plug), ctx.stats(plug)[0], str(root), "plugin clone")


def claude_debug(ctx, days):
    yield from idle_items(ctx, ctx.home / ".claude/debug", days * DAY)


def claude_file_history(ctx, days):
    yield from idle_items(ctx, ctx.home / ".claude/file-history", days * DAY)


def claude_shell_snapshots(ctx, days):
    yield from idle_items(ctx, ctx.home / ".claude/shell-snapshots", days * DAY)


def npx_cache(ctx, days):
    yield from idle_items(ctx, ctx.home / ".npm/_npx", days * DAY)


def xcode_derived(ctx, days):
    yield from idle_items(ctx, ctx.home / "Library/Developer/Xcode/DerivedData", days * DAY)


def updater_caches(ctx, days):
    for d in (ctx.home / "Library/Caches").glob("*ShipIt*"):
        yield from idle_items(ctx, d, days * DAY)


def user_tmp(ctx, days):
    if not ctx.user_tmp:
        return
    def ok(p: Path) -> bool:
        if p.name.startswith(("com.apple", ".")) or p.is_symlink():
            return False
        return p.is_dir() or p.is_file()
    yield from idle_items(ctx, ctx.user_tmp, days * DAY, match=ok)


def pip_cache(ctx, days):
    for d in (ctx.home / "Library/Caches/pip", ctx.home / ".cache/pip"):
        yield from idle_items(ctx, d, days * DAY, depth=2)


def uv_cache(ctx, days):
    d = ctx.home / ".cache/uv"
    if which(ctx, "uv"):
        yield from native(ctx, "uv", ["cache", "prune", "--quiet"], d, "native prune")
    else:  # sandbox / no uv: age-based fallback on cache buckets
        yield from idle_items(ctx, d, days * DAY, depth=2)


def pnpm_store(ctx, days):
    d = ctx.home / "Library/pnpm/store"
    if d.exists() and ctx.stats(d)[0] > 200 * (1 << 20):
        yield from native(ctx, "pnpm", ["store", "prune"], d, "native prune")


def brew(ctx, days):
    yield from native(ctx, "brew", ["cleanup", f"--prune={max(1, int(days))}", "-q"], None, "native cleanup")


def codex_tmp(ctx, days):
    yield from idle_items(ctx, ctx.home / ".codex", days * DAY,
                          match=lambda p: p.name.startswith("..codex-") and ".tmp-" in p.name)
    yield from idle_items(ctx, ctx.home / ".codex/.tmp", days * DAY)


def opencode_snapshots(ctx, days):
    for base in (ctx.home / ".local/share/opencode", ctx.home / "Library/Application Support/opencode"):
        yield from idle_items(ctx, base / "snapshot", days * DAY)
        yield from idle_items(ctx, base / "log", min(days, 7) * DAY)


def cursor_hooks_logs(ctx, days):
    yield from idle_items(ctx, ctx.home / ".cursor/logs", days * DAY)


# ---------------------------------------------------------------- confirm tier

def _git_clean(wt: Path) -> bool:
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", str(wt), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and not out.stdout.strip()


def agent_worktrees(ctx, days):
    roots = [ctx.home / ".claude/worktrees", ctx.home / ".codex/worktrees", ctx.home / ".cursor/worktrees"]
    if ctx.cwd:
        roots += [ctx.cwd / ".claude/worktrees", ctx.cwd / ".worktrees"]
    for root in roots:
        for it in idle_items(ctx, root, days * DAY):
            if (Path(it.path) / ".git").exists() and not _git_clean(Path(it.path)):
                ctx.kept.append(("agent-worktrees", it.size, "uncommitted changes"))
                continue
            it.note = "clean"
            yield it


def claude_transcripts(ctx, days):
    root = ctx.home / ".claude/projects"
    for proj in kids(root):
        for f in proj.glob("*.jsonl"):
            size, newest, _ = ctx.stats(f)
            if ctx.now - newest > days * DAY:
                yield Item(str(f), size, str(root))
                side = f.with_suffix("")
                if side.is_dir():
                    yield Item(str(side), ctx.stats(side)[0], str(root))


def codex_sessions(ctx, days):
    root = ctx.home / ".codex/sessions"
    for f in root.glob("*/*/*/*.jsonl"):
        size, newest, _ = ctx.stats(f)
        if ctx.now - newest > days * DAY:
            yield Item(str(f), size, str(root))
    yield from idle_items(ctx, ctx.home / ".codex/archived_sessions", days * DAY)


def gemini_history(ctx, days):
    yield from idle_items(ctx, ctx.home / ".gemini/tmp", days * DAY)
    yield from idle_items(ctx, ctx.home / ".gemini/history", days * DAY)


def copilot_sessions(ctx, days):
    yield from idle_items(ctx, ctx.home / ".copilot/session-state", days * DAY)


def cursor_workspaces(ctx, days):
    for base in (ctx.home / "Library/Application Support/Cursor/User/workspaceStorage",
                 ctx.home / ".config/Cursor/User/workspaceStorage"):
        yield from idle_items(ctx, base, days * DAY)


def _project_activity(proj: Path) -> float:
    ts = []
    for name in (".git/index", ".git/HEAD", ".git/FETCH_HEAD") + PROJECT_MARKERS[:-1]:
        try:
            ts.append(os.stat(proj / name).st_mtime)
        except OSError:
            pass
    return max(ts) if ts else 0.0


def stale_project_deps(ctx, days):
    """node_modules/.venv/... in projects with no git or manifest activity for 30 days."""
    budget = [20000]

    def walk(d: Path, depth: int):
        if depth > 4 or budget[0] <= 0:
            return
        entries = kids(d)
        budget[0] -= len(entries)
        names = {e.name for e in entries}
        if any(m in names for m in PROJECT_MARKERS) and d != ctx.home:
            if ctx.cwd and (d == ctx.cwd or d in ctx.cwd.parents):
                return
            if ctx.now - _project_activity(d) > days * DAY:
                for e in entries:
                    if e.name in DEP_DIRS or (e.name == "target" and "Cargo.toml" in names):
                        if e.is_dir() and not e.is_symlink():
                            yield Item(str(e), ctx.stats(e)[0], str(d), d.name)
            return
        for e in entries:
            if e.is_dir() and not e.is_symlink() and not e.name.startswith(".") \
                    and not (d == ctx.home and e.name in SKIP_HOME_DIRS) and e.name not in DEP_DIRS:
                yield from walk(e, depth + 1)

    yield from walk(ctx.home, 0)


def playwright_old(ctx, days):
    root = ctx.home / "Library/Caches/ms-playwright"
    newest = {}
    for d in kids(root):
        name, _, rev = d.name.rpartition("-")
        if rev.isdigit():
            newest[name] = max(newest.get(name, 0), int(rev))
    for d in kids(root):
        name, _, rev = d.name.rpartition("-")
        if rev.isdigit() and int(rev) < newest[name]:
            size, _, active = ctx.stats(d, ctx.now - days * DAY)
            if not active:
                yield Item(str(d), size, str(root), "older revision")


def desktop_sandboxes_empty(ctx, days):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    for sb in root.glob("*/*/local_*"):
        if any(kids(sb / "outputs")) or any(kids(sb / "uploads")):
            continue
        size, _, active = ctx.stats(sb, ctx.now - days * DAY)
        if not active:
            yield Item(str(sb), size, str(root), "no outputs/uploads")


def docker_cache(ctx, days):
    yield from native(ctx, "docker", ["builder", "prune", "-f", "--filter", f"until={max(1, int(days * 24))}h"], None, "native prune")


def simulators(ctx, days):
    cs = ctx.home / "Library/Developer/CoreSimulator"
    if cs.exists() and ctx.stats(cs)[0] > GIB:
        yield from native(ctx, "xcrun", ["simctl", "delete", "unavailable"], cs, "unavailable sims")


# ---------------------------------------------------------------- info tier

def _sized(ctx, paths, note):
    for p in paths:
        if p.exists():
            yield Item(str(p), ctx.stats(p)[0], "", note)


def local_models(ctx, days):
    h = ctx.home
    yield from _sized(ctx, [h / ".ollama/models", h / ".lmstudio/models", h / ".cache/huggingface"],
                      "models: delete unused ones in their app")


def claude_vm(ctx, days):
    yield from _sized(ctx, [ctx.home / "Library/Application Support/Claude/vm_bundles"],
                      "Cowork VM image; re-downloads if removed")


def codex_db(ctx, days):
    yield from _sized(ctx, sorted((ctx.home / ".codex").glob("*.sqlite")), "Codex history DB")


def sandbox_outputs(ctx, days):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    yield from _sized(ctx, sorted(root.glob("*/*/local_*/outputs")), "Cowork deliverables")


def trash(ctx, days):
    yield from _sized(ctx, [ctx.home / ".Trash"], "empty Trash yourself")


RULES: List[Rule] = [
    Rule("claude-task-output", "auto", "Claude Code background task output", claude_task_output, 1),
    Rule("claude-tmp-sessions", "auto", "idle Claude Code session temp dirs", claude_tmp_sessions, 3),
    Rule("desktop-sandbox-plugins", "auto", "plugin clones in idle Claude desktop sandboxes", desktop_sandbox_plugins, 3),
    Rule("claude-debug", "auto", "Claude Code debug logs", claude_debug, 7),
    Rule("claude-file-history", "auto", "Claude Code rewind snapshots", claude_file_history, 30),
    Rule("claude-shell-snapshots", "auto", "Claude Code shell snapshots", claude_shell_snapshots, 7),
    Rule("codex-tmp", "auto", "Codex temp leftovers", codex_tmp, 3),
    Rule("opencode-snapshots", "auto", "OpenCode undo snapshots and logs", opencode_snapshots, 30),
    Rule("cursor-logs", "auto", "Cursor agent logs", cursor_hooks_logs, 14),
    Rule("npx-cache", "auto", "npx packages (second chance)", npx_cache, 14, second_chance=True),
    Rule("uv-cache", "auto", "uv cache (native prune)", uv_cache, 30, second_chance=True),
    Rule("pnpm-store", "auto", "pnpm store (native prune)", pnpm_store),
    Rule("pip-cache", "auto", "pip cache", pip_cache, 30),
    Rule("brew", "auto", "Homebrew old versions", brew, 14),
    Rule("xcode-derived-data", "auto", "Xcode DerivedData", xcode_derived, 14),
    Rule("updater-caches", "auto", "app updater leftovers", updater_caches, 3),
    Rule("user-tmp", "auto", "$TMPDIR entries", user_tmp, 7),
    Rule("agent-worktrees", "confirm", "clean agent worktrees", agent_worktrees, 7),
    Rule("claude-transcripts", "confirm", "Claude Code transcripts", claude_transcripts, 30),
    Rule("codex-sessions", "confirm", "Codex sessions", codex_sessions, 30),
    Rule("gemini-history", "confirm", "Gemini CLI chats and checkpoints", gemini_history, 30),
    Rule("copilot-sessions", "confirm", "Copilot CLI sessions", copilot_sessions, 30),
    Rule("cursor-workspaces", "confirm", "Cursor workspace storage", cursor_workspaces, 60),
    Rule("stale-project-deps", "confirm", "node_modules/.venv of idle projects", stale_project_deps, 30),
    Rule("playwright-old", "confirm", "old Playwright browsers", playwright_old, 30),
    Rule("desktop-sandboxes-empty", "confirm", "empty Claude desktop sandboxes", desktop_sandboxes_empty, 7),
    Rule("docker-cache", "confirm", "Docker build cache", docker_cache, 7),
    Rule("simulators", "confirm", "unavailable iOS simulators", simulators),
    Rule("local-models", "info", "local AI models", local_models),
    Rule("claude-vm", "info", "Claude Cowork VM bundle", claude_vm),
    Rule("codex-db", "info", "Codex sqlite DBs", codex_db),
    Rule("sandbox-outputs", "info", "Cowork sandbox outputs", sandbox_outputs),
    Rule("trash", "info", "Trash", trash),
]
BUILTIN = {r.id: r for r in RULES}


# ---------------------------------------------------------------- user rules and keep patterns (config.json)

GLOB_CHARS = set("*?[")
USER_DIRS = ("Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music")   # custom rules here: ask first
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def expand(home: Path, pattern: str) -> str:
    """'~' means the steward's home (so --home sandboxes work); relative patterns are refused by callers."""
    if pattern == "~" or pattern.startswith("~/"):
        pattern = str(home) + pattern[1:]
    return os.path.normpath(pattern) if not GLOB_CHARS & set(pattern) else pattern


def fixed_prefix(pattern: str) -> str:
    parts = []
    for part in pattern.split(os.sep):
        if GLOB_CHARS & set(part):
            break
        parts.append(part)
    return os.sep.join(parts) or os.sep


def check_custom(home: Path, spec: dict) -> List[str]:
    """Problems with a custom rule spec (empty list = valid)."""
    errs = []
    name = spec.get("name", "")
    if not NAME_RE.match(str(name)):
        errs.append(f"custom rule name {name!r}: use lowercase letters, digits and dashes")
    elif name in BUILTIN:
        errs.append(f"custom rule {name!r} clashes with a built-in rule")
    paths = spec.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(x, str) for x in paths):
        errs.append(f"custom rule {name!r}: 'paths' must be a non-empty list of globs")
        return errs
    home_s = str(home)
    for raw in paths:
        p = expand(home, raw)
        if not os.path.isabs(p):
            errs.append(f"custom rule {name!r}: {raw!r} must start with ~/ or /")
            continue
        prefix = fixed_prefix(p) if GLOB_CHARS & set(p) else os.path.dirname(p)
        if not (prefix + os.sep).startswith(home_s + os.sep):
            errs.append(f"custom rule {name!r}: {raw!r} is outside your home folder")
        elif os.path.normpath(prefix) == home_s and GLOB_CHARS & set(p):
            errs.append(f"custom rule {name!r}: {raw!r} is too broad; name a folder below ~ first")
    if spec.get("tier", "confirm") not in ("auto", "confirm", "info", "off"):
        errs.append(f"custom rule {name!r}: tier must be auto, confirm, info or off")
    return errs


def custom_rule(home: Path, spec: dict) -> Rule:
    patterns = [expand(home, raw) for raw in spec["paths"]]
    tier = spec.get("tier", "confirm")
    in_user_dirs = any(fixed_prefix(p).startswith(str(home / d)) for p in patterns for d in USER_DIRS)
    if in_user_dirs and tier == "auto":
        tier = "confirm"        # automatic sweeps never reach into your own folders

    def find(ctx, days):
        for p in patterns:
            has_glob = bool(GLOB_CHARS & set(p))
            root = fixed_prefix(p) if has_glob else os.path.dirname(p)
            for m in (sorted(glob.glob(p)) if has_glob else ([p] if os.path.lexists(p) else [])):
                size, _newest, active = ctx.stats(m, ctx.now - days * DAY)
                if not active:
                    yield Item(m, size, root, spec["name"])

    label = spec.get("label") or "your rule: " + ", ".join(spec["paths"])
    return Rule(spec["name"], tier, label, find, float(spec.get("idle_days", 30)), custom=True)


def kept(home: Path, keep: List[str], path: str) -> bool:
    """True when a keep entry protects `path`: a path (and everything under it), a glob, or a name glob."""
    base = os.path.basename(path)
    for raw in keep:
        if "/" not in raw and not raw.startswith("~"):
            if fnmatch.fnmatch(base, raw):          # "*.mov", ".env*": match the item's name
                return True
            continue
        p = expand(home, raw)
        if GLOB_CHARS & set(p):
            if fnmatch.fnmatch(path, p) or fnmatch.fnmatch(path, p.rstrip("*").rstrip(os.sep) + os.sep + "*") \
                    or fixed_prefix(p).startswith(path + os.sep):
                return True
        elif path == p or path.startswith(p + os.sep) or p.startswith(path + os.sep):
            return True
    return False
