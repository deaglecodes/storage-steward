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
import math
import os
import re
import shutil
import stat
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

DAY = 86400.0
HOUR = 3600.0
GIB = 1 << 30
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
DEP_DIRS = {"node_modules", ".venv", "venv", ".next", ".turbo", ".nuxt", ".svelte-kit", ".parcel-cache"}
PROJECT_MARKERS = ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", ".git")
SKIP_HOME_DIRS = {"Library", "Applications", "Pictures", "Movies", "Music", "Downloads", "Public"}
PERSONAL_DIRS = ("Documents", "Desktop", "Downloads", "Pictures", "Movies", "Music")   # auto never reaches in
# ignored files that are safe to lose with a worktree: they rebuild from the checkout itself
REGENERABLE = DEP_DIRS | {"target", "dist", "build", "out", ".cache", "__pycache__", ".pytest_cache",
                          ".mypy_cache", ".ruff_cache", ".gradle", ".tox", "coverage", ".nyc_output", ".DS_Store",
                          ".eslintcache"}
KEEP_GLOB_MAX = 2000   # keep globs matching more than this are checked by name only (no identity lookups)
Node = Tuple[int, int]


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
    capped: bool = False             # reaches into a personal folder: never auto, whatever the config says


# ---------------------------------------------------------------- helpers

def kids(d: Path) -> List[Path]:
    try:
        return sorted(Path(d).iterdir())
    except OSError:
        return []


def node(path) -> Optional[Node]:
    """(device, inode) of path, following symlinks: the file's identity, whatever its spelling."""
    try:
        st = os.stat(path)
    except (OSError, ValueError):      # ValueError: a NUL or lone surrogate in a hand-written path
        return None
    return st.st_dev, st.st_ino


LineageCache = Dict[str, Tuple[str, List[Node]]]


def real_parent(path, cache: Optional[LineageCache] = None) -> Tuple[str, List[Node]]:
    """(real path of path's folder, identities of that folder and every folder above it)."""
    d = os.path.dirname(os.path.abspath(path))
    hit = cache.get(d) if cache is not None else None
    if hit is None:
        parent = os.path.realpath(d)
        up, p = [], parent
        while True:
            n = node(p)
            if n:
                up.append(n)
            nxt = os.path.dirname(p)
            if nxt == p:
                break
            p = nxt
        hit = (parent, up)
        if cache is not None:
            cache[d] = hit
    return hit


def lineage(path, cache: Optional[LineageCache] = None) -> List[Node]:
    """Identity of `path` itself (not followed if it is a symlink), then of every real ancestor.

    Comparing identities instead of strings is what makes the guards hold on case-insensitive APFS
    (~/documents is ~/Documents), through `..`, `//` and symlinked parents. `cache` (one per run) saves
    re-resolving the same folders for every item in them.
    """
    try:
        parent, up = real_parent(path, cache)
        st = os.lstat(os.path.join(parent, os.path.basename(path)))
    except (OSError, ValueError):
        return []
    return [(st.st_dev, st.st_ino)] + up


def inside(path: str, root: str) -> bool:
    """True when path's real location is root's real location or below it."""
    try:
        rp, rr = os.path.realpath(path), os.path.realpath(root)
    except ValueError:
        return False
    return rp == rr or rp.startswith(rr.rstrip(os.sep) + os.sep)


def fold(text: str) -> str:
    """Comparison form for names: APFS treats NFC/NFD and (by default) case as the same name."""
    return unicodedata.normalize("NFC", text).casefold()


def in_personal_folder(home: Path, path: str) -> bool:
    """Inside Documents, Desktop, Downloads, Pictures, Movies or Music (any case, through symlinks)."""
    rp, h = os.path.realpath(path).casefold(), os.path.realpath(home).casefold()
    return any(rp == f"{h}/{d.casefold()}" or rp.startswith(f"{h}/{d.casefold()}/") for d in PERSONAL_DIRS)


def idle_items(ctx, root: Path, idle_s: float, depth: int = 1, match=None, note: str = "",
               ctime: bool = False) -> Iterable[Item]:
    """Entries `depth` levels under root whose whole subtree is untouched for idle_s.

    ctime=True also counts inode changes, so files restored or extracted with old mtimes look fresh.
    """
    level = [Path(root)]
    for _ in range(depth):
        level = [k for d in level for k in kids(d) if d.is_dir() and not d.is_symlink()]
    cutoff = ctx.now - idle_s
    for p in level:
        if match and not match(p):
            continue
        size, _newest, aborted = ctx.stats(p, cutoff, ctime and ctx.use_ctime)
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


def _has_socket(d: Path, depth: int = 2) -> bool:
    """A socket means a live server (tmux, ssh-agent, an IDE) whose files don't change while it runs."""
    try:
        entries = list(os.scandir(d))
    except OSError:
        return True             # can't look inside: assume it's in use
    for e in entries:
        try:
            mode = e.stat(follow_symlinks=False).st_mode
        except OSError:
            continue
        if stat.S_ISSOCK(mode):
            return True
        if stat.S_ISDIR(mode) and depth > 1 and _has_socket(Path(e.path), depth - 1):
            return True
    return False


def user_tmp(ctx, days):
    if not ctx.user_tmp:
        return
    root, home = os.path.realpath(ctx.user_tmp), os.path.realpath(ctx.home)
    if root == os.sep or inside(home, root):
        ctx.kept.append(("user-tmp", 0, f"TMPDIR {root} contains your home folder; rule skipped"))
        return

    def ok(p: Path) -> bool:
        if p.name.startswith(("com.apple", ".", "tmux-", "ssh-")) or p.is_symlink():
            return False
        if p.is_dir():
            return not _has_socket(p)
        return p.is_file()
    yield from idle_items(ctx, ctx.user_tmp, days * DAY, match=ok, ctime=True)


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

def _checkouts(d: Path, depth: int = 2) -> Optional[List[Path]]:
    """The git checkouts that make up d (d itself, or nested as in Codex's worktrees/<id>/<repo>).

    None when d holds anything outside a checkout, which git can't vouch for.
    """
    if (d / ".git").exists():
        return [d]
    try:
        entries = sorted(os.scandir(d), key=lambda e: e.name)
    except OSError:
        return None
    found: List[Path] = []
    for e in entries:
        if e.name == ".DS_Store":
            continue
        if depth == 0 or not e.is_dir(follow_symlinks=False):
            return None
        sub = _checkouts(Path(e.path), depth - 1)
        if sub is None:
            return None
        found += sub
    return found


def _git(repo: Path, *args) -> subprocess.CompletedProcess:
    # fsmonitor off: a scan must not leave a file-watcher daemon running in every worktree it checks
    return subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(repo), *args],
                          capture_output=True, text=True, timeout=20)


def worktree_risk(wt: Path) -> Optional[str]:
    """Why deleting this worktree could lose work, or None when git proves it can't."""
    repos = _checkouts(wt)
    if repos is None:
        return "files outside a git checkout"
    for repo in repos:
        try:
            st = _git(repo, "status", "--porcelain", "--ignored=matching", "--untracked-files=all")
            if st.returncode:
                return "git status failed"
            for line in st.stdout.splitlines():
                if not line.startswith("!! "):
                    return "uncommitted changes"
                parts = line[3:].strip('"').rstrip("/").split("/")
                if not (set(parts) & REGENERABLE or parts[-1].endswith(".pyc")):
                    return f"ignored file {parts[-1]}"
            risk = _unshared_commits(repo)
            if risk:
                return risk
        except (OSError, subprocess.TimeoutExpired):
            return "git unavailable"
    return None


def _unshared_commits(repo: Path) -> Optional[str]:
    """Commits or stashes that exist only inside this checkout and would go with it."""
    if _git(repo, "rev-parse", "--verify", "-q", "HEAD").returncode:
        return None if not _git(repo, "for-each-ref", "--count=1").stdout.strip() else "refs git can't resolve"
    if (repo / ".git").is_dir():
        # a standalone repo: its branches and stashes are deleted with it, so only pushed or tagged work is safe
        rl = _git(repo, "rev-list", "-n", "1", "--all", "--not", "--remotes", "--tags")
        if rl.returncode or rl.stdout.strip():
            return "commits not pushed anywhere"
        st = _git(repo, "stash", "list")
        if st.returncode or st.stdout.strip():
            return "stashed changes"
        return None
    # a linked worktree: branches live in the main repo; only commits reachable from no ref would be lost
    rl = _git(repo, "rev-list", "-n", "1", "HEAD", "--not", "--branches", "--remotes", "--tags")
    if rl.returncode or rl.stdout.strip():
        return "commits on no branch"
    return None


def agent_worktrees(ctx, days):
    roots = [ctx.home / ".claude/worktrees", ctx.home / ".codex/worktrees", ctx.home / ".cursor/worktrees"]
    if ctx.cwd:
        roots += [ctx.cwd / ".claude/worktrees", ctx.cwd / ".worktrees"]
    for root in roots:
        for it in idle_items(ctx, root, days * DAY):
            risk = worktree_risk(Path(it.path))
            if risk:
                ctx.kept.append(("agent-worktrees", it.size, risk))
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


def _git_dir(proj: Path) -> Path:
    """Where a checkout's git data lives (a worktree or submodule has a .git file pointing there)."""
    g = proj / ".git"
    if g.is_file():
        try:
            line = g.read_text(errors="replace").strip()
        except OSError:
            return g
        if line.startswith("gitdir:"):
            target = Path(line[len("gitdir:"):].strip())
            return target if target.is_absolute() else proj / target
    return g


def _project_activity(proj: Path) -> Optional[float]:
    """Newest git or manifest change, or None when nothing tells us (then the project counts as active)."""
    gd, ts = _git_dir(proj), []
    for path in [gd / "index", gd / "HEAD", gd / "FETCH_HEAD"] + [proj / m for m in PROJECT_MARKERS[:-1]]:
        try:
            ts.append(os.stat(path).st_mtime)
        except OSError:
            pass
    return max(ts) if ts else None


def _edited_since(proj: Path, cutoff: float, skip: Set[str], budget: int = 50000) -> bool:
    """Any file in the project (outside dependency and git dirs) changed after cutoff?"""
    stack = [str(proj)]
    while stack:
        try:
            it = os.scandir(stack.pop())
        except OSError:
            continue
        with it:
            for e in it:
                budget -= 1
                if budget <= 0:
                    return True         # too big to prove idle: leave it alone
                if e.name in skip or e.name == ".git":
                    continue
                try:
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    continue
                if st.st_mtime > cutoff:
                    return True
                if stat.S_ISDIR(st.st_mode):
                    stack.append(e.path)
    return False


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
            cutoff = ctx.now - days * DAY
            last = _project_activity(d)
            deps = {e.name for e in entries if e.name in DEP_DIRS or (e.name == "target" and "Cargo.toml" in names)}
            if last is None or last > cutoff or not deps or _edited_since(d, cutoff, deps):
                return
            for e in entries:
                if e.name in deps and e.is_dir() and not e.is_symlink():
                    size, _, active = ctx.stats(e, cutoff)
                    if not active:
                        yield Item(str(e), size, str(d), d.name)
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


def _has_entries(d: Path) -> bool:
    """Unreadable counts as non-empty: we only call a folder empty when we can see it is."""
    try:
        with os.scandir(d) as it:
            return any(True for _ in it)
    except FileNotFoundError:
        return False
    except OSError:
        return True


def desktop_sandboxes_empty(ctx, days):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    for sb in root.glob("*/*/local_*"):
        if _has_entries(sb / "outputs") or _has_entries(sb / "uploads"):
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
USER_DIRS = PERSONAL_DIRS            # custom rules here: ask first
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


def expand(home: Path, pattern: str) -> str:
    """'~' and '$HOME' mean the steward's home (so --home sandboxes work); `//`, `.` and trailing `/` go.

    Relative patterns stay relative; callers refuse or interpret them.
    """
    s = pattern.strip()
    for var in ("${HOME}", "$HOME"):
        if s == var or s.startswith(var + "/"):
            s = "~" + s[len(var):]
    if s == "~" or s.startswith("~/"):
        s = str(home) + s[1:]
    return os.path.normpath(s) if os.path.isabs(s) else s


def fixed_prefix(pattern: str) -> str:
    parts = []
    for part in pattern.split(os.sep):
        if GLOB_CHARS & set(part):
            break
        parts.append(part)
    return os.sep.join(parts) or os.sep


def positive_days(value) -> float:
    """A finite threshold above zero, or ValueError."""
    d = float(value)
    if not math.isfinite(d) or d <= 0:
        raise ValueError(f"{value!r} is not a positive number of days")
    return d


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
    home_real = os.path.realpath(home)
    for raw in paths:
        if ".." in raw.split("/"):
            errs.append(f"custom rule {name!r}: {raw!r} uses '..'; name the folder directly")
            continue
        p = expand(home, raw)
        if not os.path.isabs(p):
            errs.append(f"custom rule {name!r}: {raw!r} must start with ~/ or /")
            continue
        prefix = fixed_prefix(p) if GLOB_CHARS & set(p) else os.path.dirname(p)
        if not inside(prefix, home_real):
            errs.append(f"custom rule {name!r}: {raw!r} is outside your home folder")
        elif os.path.realpath(prefix) == home_real and GLOB_CHARS & set(p):
            errs.append(f"custom rule {name!r}: {raw!r} is too broad; name a folder below ~ first")
    try:
        positive_days(spec.get("idle_days", 30))
    except (TypeError, ValueError):
        errs.append(f"custom rule {name!r}: idle_days must be a positive number")
    if spec.get("tier", "confirm") not in ("auto", "confirm", "info", "off"):
        errs.append(f"custom rule {name!r}: tier must be auto, confirm, info or off")
    if "label" in spec and not isinstance(spec["label"], str):
        errs.append(f"custom rule {name!r}: label must be text")
    return errs


def custom_rule(home: Path, spec: dict) -> Rule:
    """Build a validated custom rule (call check_custom first)."""
    patterns = [expand(home, raw) for raw in spec["paths"]]
    capped = any(in_personal_folder(home, fixed_prefix(p)) for p in patterns)
    tier = spec.get("tier", "confirm")
    if capped and tier == "auto":
        tier = "confirm"        # automatic sweeps never reach into your own folders
    home_real = os.path.realpath(home)

    def find(ctx, days):
        for p in patterns:
            has_glob = bool(GLOB_CHARS & set(p))
            root = fixed_prefix(p) if has_glob else os.path.dirname(p)
            for m in (sorted(glob.glob(p)) if has_glob else ([p] if os.path.lexists(p) else [])):
                if not inside(m, home_real):          # the tree changed under a symlink since it was added
                    continue
                size, _newest, active = ctx.stats(m, ctx.now - days * DAY, ctx.use_ctime)
                if not active:
                    yield Item(m, size, root, spec["name"])

    label = spec.get("label") or "your rule: " + ", ".join(spec["paths"])
    return Rule(spec["name"], tier, label, find, positive_days(spec.get("idle_days", 30)),
                custom=True, capped=capped)


class KeepList:
    """The user's keep entries; protects() is true for anything they cover, however it is spelled.

    Entries: a path ("~/models", "$HOME/x", "/abs"; a relative path is taken from ~) protects itself,
    everything under it and every folder above it; a glob ("~/code/client-*") protects what it matches;
    a bare name pattern ("*.mov", ".env*", "*.sparsebundle") protects matching files, anything inside a
    matching folder, and any folder that contains a match. Paths compare by file identity; names and
    globs compare NFC-normalized and case-folded, so no APFS spelling slips past.
    Building never raises: an entry it can't read is reported and sets `broken` (the policy then pauses).
    """

    def __init__(self, home: Path, entries: List[str]):
        self.home, self.names, self.patterns = home, [], []
        self.problems: List[str] = []
        self.broken = False
        self._built = False
        self.nodes: Set[Node] = set()       # kept paths themselves
        self.above: Set[Node] = set()       # kept paths and every folder that contains one
        for raw in entries:
            try:
                self._add(raw)
            except (ValueError, re.error) as e:
                self.problems.append(f"keep {raw!r}: can't be read ({e})")
                self.broken = True

    def _add(self, raw: str):
        entry = raw.strip()
        if not entry:
            return
        if "\0" in entry:
            raise ValueError("contains a NUL character")
        if "/" not in entry.rstrip("/") and not entry.startswith(("~", "$")):
            pat = fold(entry.rstrip("/"))
            re.compile(fnmatch.translate(pat))          # surface a bad pattern now, not mid-sweep
            self.names.append(pat)
            return
        p = expand(home=self.home, pattern=entry)
        if not os.path.isabs(p):
            self.problems.append(f"keep {raw!r}: read as ~/{entry} (start it with ~/ to be explicit)")
            p = os.path.normpath(str(self.home / entry))
        re.compile(fnmatch.translate(fold(p)))
        p.encode()                                      # lone surrogates can't name a file
        self.patterns.append(p)
        if not GLOB_CHARS & set(p) and not os.path.lexists(p):
            self.problems.append(f"keep {raw!r}: nothing there yet (a typo?)")

    def _build(self, cache: Optional[LineageCache]):
        """Resolve path entries to identities, once, on the first check (hooks that never delete skip it)."""
        self._built = True
        for p in self.patterns:
            try:
                matches = [p]
                if GLOB_CHARS & set(p):
                    matches = []
                    for m in glob.iglob(p):
                        matches.append(m)
                        if len(matches) > KEEP_GLOB_MAX:
                            matches = []                # too many: the name/string match covers them
                            break
                for m in matches:
                    n = node(m)
                    if n:
                        self.nodes.add(n)
                        self.above.add(n)
                        self.above.update(lineage(m, cache))
            except (OSError, ValueError, re.error):
                continue

    def protects(self, path: str, cache: Optional[LineageCache] = None) -> bool:
        if not self._built:
            self._build(cache)
        lin = lineage(path, cache)
        if lin and (lin[0] in self.above or any(n in self.nodes for n in lin)):
            return True
        try:
            real = os.path.join(real_parent(path, cache)[0], os.path.basename(path))
        except (OSError, ValueError):
            return True                                 # can't tell where it is: keep it
        if self._by_string(path) or self._by_string(real):
            return True
        return bool(self.names) and self._by_name(real)

    def _by_string(self, path: str) -> bool:
        """Fallback for entries that match nothing on disk yet, kept symlinks, and huge globs."""
        path = fold(os.path.normpath(path))
        for raw in self.patterns:
            p = fold(raw)
            if GLOB_CHARS & set(p):
                if fnmatch.fnmatchcase(path, p) or fnmatch.fnmatchcase(path, p.rstrip("*").rstrip(os.sep) + os.sep + "*") \
                        or fixed_prefix(p).startswith(path + os.sep):
                    return True
            elif path == p or path.startswith(p + os.sep) or p.startswith(path + os.sep):
                return True
        return False

    def _name_hit(self, name: str) -> bool:
        n = fold(name)
        return any(fnmatch.fnmatchcase(n, pat) for pat in self.names)

    def _by_name(self, path: str) -> bool:
        home = os.path.realpath(self.home)
        below = path[len(home) + 1:] if path.startswith(home + os.sep) else path
        if any(self._name_hit(part) for part in below.split(os.sep) if part):
            return True                                 # it, or a folder it sits in, matches
        if not os.path.isdir(path) or os.path.islink(path):
            return False
        for _root, dirs, files in os.walk(path):        # a folder holding a kept file is kept whole
            if any(self._name_hit(n) for n in files) or any(self._name_hit(n) for n in dirs):
                return True
        return False


def kept(home: Path, keep: List[str], path: str) -> bool:
    """True when a keep entry protects `path` (see KeepList)."""
    return KeepList(home, keep).protects(path)
