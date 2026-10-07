"""Rule catalog for storage-steward.

Each rule finds candidates and declares a tier:
  auto    - regenerable or agent junk; at worst costs a re-download/rebuild. Hooks sweep these.
  confirm - recoverable only from elsewhere (git, re-install) or user history; ask first.
  info    - reported for awareness; the tool never deletes these.

Paths and thresholds come from the GitHub issues cited in references/targets.md.
"""
from __future__ import annotations

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
    find: Callable[["object"], Iterable[Item]]
    second_chance: bool = False   # read-mostly cache: arm, then evict only if unread


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

def claude_task_output(ctx):
    base = ctx.claude_tmp
    if not base or not base.is_dir():
        return
    for f in list(base.glob("*/*/tasks/*.output")) + list(base.glob("*/tasks/*.output")):
        size, newest, _ = ctx.stats(f)
        idle = ctx.now - newest
        if idle > DAY or (size >= GIB and idle > HOUR):
            yield Item(str(f), size, str(base), "runaway" if size >= GIB else "")


def claude_tmp_sessions(ctx):
    base = ctx.claude_tmp
    if not base or not base.is_dir():
        return
    yield from idle_items(ctx, base, 3 * DAY, depth=2, match=lambda p: bool(UUID_RE.match(p.name)))
    yield from idle_items(ctx, base, 3 * DAY, match=lambda p: p.name.startswith("cache-break-state-"))


def desktop_sandbox_plugins(ctx):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    for sb in root.glob("*/*/local_*"):
        plug = sb / ".claude" / "plugins"
        if not plug.is_dir():
            continue
        _, _, active = ctx.stats(sb, ctx.now - 3 * DAY)
        if not active:
            yield Item(str(plug), ctx.stats(plug)[0], str(root), "plugin clone")


def claude_debug(ctx):
    yield from idle_items(ctx, ctx.home / ".claude/debug", 7 * DAY)


def claude_file_history(ctx):
    yield from idle_items(ctx, ctx.home / ".claude/file-history", 30 * DAY)


def claude_shell_snapshots(ctx):
    yield from idle_items(ctx, ctx.home / ".claude/shell-snapshots", 7 * DAY)


def npx_cache(ctx):
    yield from idle_items(ctx, ctx.home / ".npm/_npx", 14 * DAY)


def xcode_derived(ctx):
    yield from idle_items(ctx, ctx.home / "Library/Developer/Xcode/DerivedData", 14 * DAY)


def updater_caches(ctx):
    for d in (ctx.home / "Library/Caches").glob("*ShipIt*"):
        yield from idle_items(ctx, d, 3 * DAY)


def user_tmp(ctx):
    if not ctx.user_tmp:
        return
    def ok(p: Path) -> bool:
        if p.name.startswith(("com.apple", ".")) or p.is_symlink():
            return False
        return p.is_dir() or p.is_file()
    yield from idle_items(ctx, ctx.user_tmp, 7 * DAY, match=ok)


def pip_cache(ctx):
    for d in (ctx.home / "Library/Caches/pip", ctx.home / ".cache/pip"):
        yield from idle_items(ctx, d, 30 * DAY, depth=2)


def uv_cache(ctx):
    d = ctx.home / ".cache/uv"
    if which(ctx, "uv"):
        yield from native(ctx, "uv", ["cache", "prune", "--quiet"], d, "native prune")
    else:  # sandbox / no uv: age-based fallback on cache buckets
        yield from idle_items(ctx, d, 30 * DAY, depth=2)


def pnpm_store(ctx):
    d = ctx.home / "Library/pnpm/store"
    if d.exists() and ctx.stats(d)[0] > 200 * (1 << 20):
        yield from native(ctx, "pnpm", ["store", "prune"], d, "native prune")


def brew(ctx):
    yield from native(ctx, "brew", ["cleanup", "--prune=14", "-q"], None, "native cleanup")


def codex_tmp(ctx):
    yield from idle_items(ctx, ctx.home / ".codex", 3 * DAY,
                          match=lambda p: p.name.startswith("..codex-") and ".tmp-" in p.name)
    yield from idle_items(ctx, ctx.home / ".codex/.tmp", 3 * DAY)


def opencode_snapshots(ctx):
    for base in (ctx.home / ".local/share/opencode", ctx.home / "Library/Application Support/opencode"):
        yield from idle_items(ctx, base / "snapshot", 30 * DAY)
        yield from idle_items(ctx, base / "log", 7 * DAY)


def cursor_hooks_logs(ctx):
    yield from idle_items(ctx, ctx.home / ".cursor/logs", 14 * DAY)


# ---------------------------------------------------------------- confirm tier

def _git_clean(wt: Path) -> bool:
    try:
        out = subprocess.run(["git", "--no-optional-locks", "-C", str(wt), "status", "--porcelain"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and not out.stdout.strip()


def agent_worktrees(ctx):
    roots = [ctx.home / ".claude/worktrees", ctx.home / ".codex/worktrees", ctx.home / ".cursor/worktrees"]
    if ctx.cwd:
        roots += [ctx.cwd / ".claude/worktrees", ctx.cwd / ".worktrees"]
    for root in roots:
        for it in idle_items(ctx, root, 7 * DAY):
            if (Path(it.path) / ".git").exists() and not _git_clean(Path(it.path)):
                ctx.kept.append(("agent-worktrees", it.size, "uncommitted changes"))
                continue
            it.note = "clean"
            yield it


def claude_transcripts(ctx):
    root = ctx.home / ".claude/projects"
    for proj in kids(root):
        for f in proj.glob("*.jsonl"):
            size, newest, _ = ctx.stats(f)
            if ctx.now - newest > 30 * DAY:
                yield Item(str(f), size, str(root))
                side = f.with_suffix("")
                if side.is_dir():
                    yield Item(str(side), ctx.stats(side)[0], str(root))


def codex_sessions(ctx):
    root = ctx.home / ".codex/sessions"
    for f in root.glob("*/*/*/*.jsonl"):
        size, newest, _ = ctx.stats(f)
        if ctx.now - newest > 30 * DAY:
            yield Item(str(f), size, str(root))
    yield from idle_items(ctx, ctx.home / ".codex/archived_sessions", 30 * DAY)


def gemini_history(ctx):
    yield from idle_items(ctx, ctx.home / ".gemini/tmp", 30 * DAY)
    yield from idle_items(ctx, ctx.home / ".gemini/history", 30 * DAY)


def copilot_sessions(ctx):
    yield from idle_items(ctx, ctx.home / ".copilot/session-state", 30 * DAY)


def cursor_workspaces(ctx):
    for base in (ctx.home / "Library/Application Support/Cursor/User/workspaceStorage",
                 ctx.home / ".config/Cursor/User/workspaceStorage"):
        yield from idle_items(ctx, base, 60 * DAY)


def _project_activity(proj: Path) -> float:
    ts = []
    for name in (".git/index", ".git/HEAD", ".git/FETCH_HEAD") + PROJECT_MARKERS[:-1]:
        try:
            ts.append(os.stat(proj / name).st_mtime)
        except OSError:
            pass
    return max(ts) if ts else 0.0


def stale_project_deps(ctx):
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
            if ctx.now - _project_activity(d) > 30 * DAY:
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


def playwright_old(ctx):
    root = ctx.home / "Library/Caches/ms-playwright"
    newest = {}
    for d in kids(root):
        name, _, rev = d.name.rpartition("-")
        if rev.isdigit():
            newest[name] = max(newest.get(name, 0), int(rev))
    for d in kids(root):
        name, _, rev = d.name.rpartition("-")
        if rev.isdigit() and int(rev) < newest[name]:
            size, _, active = ctx.stats(d, ctx.now - 30 * DAY)
            if not active:
                yield Item(str(d), size, str(root), "older revision")


def desktop_sandboxes_empty(ctx):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    for sb in root.glob("*/*/local_*"):
        if any(kids(sb / "outputs")) or any(kids(sb / "uploads")):
            continue
        size, _, active = ctx.stats(sb, ctx.now - 7 * DAY)
        if not active:
            yield Item(str(sb), size, str(root), "no outputs/uploads")


def docker_cache(ctx):
    yield from native(ctx, "docker", ["builder", "prune", "-f", "--filter", "until=168h"], None, "native prune")


def simulators(ctx):
    cs = ctx.home / "Library/Developer/CoreSimulator"
    if cs.exists() and ctx.stats(cs)[0] > GIB:
        yield from native(ctx, "xcrun", ["simctl", "delete", "unavailable"], cs, "unavailable sims")


# ---------------------------------------------------------------- info tier

def _sized(ctx, paths, note):
    for p in paths:
        if p.exists():
            yield Item(str(p), ctx.stats(p)[0], "", note)


def local_models(ctx):
    h = ctx.home
    yield from _sized(ctx, [h / ".ollama/models", h / ".lmstudio/models", h / ".cache/huggingface"],
                      "models: delete unused ones in their app")


def claude_vm(ctx):
    yield from _sized(ctx, [ctx.home / "Library/Application Support/Claude/vm_bundles"],
                      "Cowork VM image; re-downloads if removed")


def codex_db(ctx):
    yield from _sized(ctx, sorted((ctx.home / ".codex").glob("*.sqlite")), "Codex history DB")


def sandbox_outputs(ctx):
    root = ctx.home / "Library/Application Support/Claude/local-agent-mode-sessions"
    yield from _sized(ctx, sorted(root.glob("*/*/local_*/outputs")), "Cowork deliverables")


def trash(ctx):
    yield from _sized(ctx, [ctx.home / ".Trash"], "empty Trash yourself")


RULES: List[Rule] = [
    Rule("claude-task-output", "auto", "Claude Code task .output files", claude_task_output),
    Rule("claude-tmp-sessions", "auto", "idle Claude Code session temp dirs", claude_tmp_sessions),
    Rule("desktop-sandbox-plugins", "auto", "plugin clones in idle desktop sandboxes", desktop_sandbox_plugins),
    Rule("claude-debug", "auto", "~/.claude/debug logs >7d", claude_debug),
    Rule("claude-file-history", "auto", "rewind snapshots >30d", claude_file_history),
    Rule("claude-shell-snapshots", "auto", "shell snapshots >7d", claude_shell_snapshots),
    Rule("codex-tmp", "auto", "Codex temp leftovers", codex_tmp),
    Rule("opencode-snapshots", "auto", "OpenCode undo snapshots >30d, logs >7d", opencode_snapshots),
    Rule("cursor-logs", "auto", "Cursor agent logs >14d", cursor_hooks_logs),
    Rule("npx-cache", "auto", "npx packages unused >14d", npx_cache, second_chance=True),
    Rule("uv-cache", "auto", "uv cache", uv_cache, second_chance=True),
    Rule("pnpm-store", "auto", "pnpm store", pnpm_store),
    Rule("pip-cache", "auto", "pip cache >30d", pip_cache),
    Rule("brew", "auto", "Homebrew old versions", brew),
    Rule("xcode-derived-data", "auto", "Xcode DerivedData >14d", xcode_derived),
    Rule("updater-caches", "auto", "app updater leftovers", updater_caches),
    Rule("user-tmp", "auto", "$TMPDIR entries >7d", user_tmp),
    Rule("agent-worktrees", "confirm", "clean agent worktrees idle >7d", agent_worktrees),
    Rule("claude-transcripts", "confirm", "Claude transcripts >30d", claude_transcripts),
    Rule("codex-sessions", "confirm", "Codex sessions >30d", codex_sessions),
    Rule("gemini-history", "confirm", "Gemini CLI chats/checkpoints >30d", gemini_history),
    Rule("copilot-sessions", "confirm", "Copilot CLI sessions >30d", copilot_sessions),
    Rule("cursor-workspaces", "confirm", "Cursor workspace storage >60d", cursor_workspaces),
    Rule("stale-project-deps", "confirm", "deps of projects idle >30d", stale_project_deps),
    Rule("playwright-old", "confirm", "old Playwright browsers", playwright_old),
    Rule("desktop-sandboxes-empty", "confirm", "empty desktop sandboxes >7d", desktop_sandboxes_empty),
    Rule("docker-cache", "confirm", "Docker build cache >7d", docker_cache),
    Rule("simulators", "confirm", "unavailable iOS simulators", simulators),
    Rule("local-models", "info", "local AI models", local_models),
    Rule("claude-vm", "info", "Claude Cowork VM bundle", claude_vm),
    Rule("codex-db", "info", "Codex sqlite DBs", codex_db),
    Rule("sandbox-outputs", "info", "Cowork sandbox outputs", sandbox_outputs),
    Rule("trash", "info", "Trash", trash),
]
