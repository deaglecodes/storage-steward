"""Per-agent setup for storage-steward: skill links, hooks, and an OS scheduler fallback.

One real copy of the skill lives in ~/.agents/skills (the cross-agent location Codex reads); every
other agent gets a symlink. Hooks are written in each agent's own format:

  agent      file                       prompt check         sweep triggers
  claude     ~/.claude/settings.json    UserPromptSubmit     Stop, SessionEnd
  codex      ~/.codex/hooks.json        UserPromptSubmit     Stop (must print JSON)
  cursor     ~/.cursor/hooks.json       (none: can't add     stop (JSON), sessionEnd
                                         context)
  gemini     ~/.gemini/settings.json    BeforeAgent (JSON)   AfterAgent, SessionEnd (JSON)

Agents without hooks (OpenCode, Copilot CLI, Aider, ...) are covered by `schedule`: a launchd agent
on macOS, a systemd user timer or crontab line on Linux, running the same throttled sweep.

Config edits are conservative: a file is rewritten only when its parsed content changes, through a
symlink onto its target, with the original mode and a `<file>.bak-<epoch>` backup (newest 2 kept). A
config that is not valid JSON raises ConfigError so the caller can skip that one agent. Uninstall
removes only what install added: our hooks, files left empty by that, our skill links and copies,
the OS timer, and the cleanupPeriodDays value we set if the user has not changed it since.
"""
from __future__ import annotations

import argparse
import copy
import glob
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import escape as xml_escape

# Recognizes our hook commands in any agent's config: the quoted form older installs wrote
# (python3 '/p/steward.py' hook stop) and the shlex form written now (python3 /p/steward.py hook stop).
HOOK_RE = re.compile(r"(?:^|[\\/\s'\"])steward\.py'?\s+hook\s+(prompt|stop|session-end)\b")
SKILL = "storage-steward"
SKILL_NAME_RE = re.compile(r"(?m)^name:\s*[\"']?storage-steward[\"']?\s*$")   # in our SKILL.md frontmatter
PLIST_LABEL = "dev.storage-steward.sweep"
INTERVAL_S = 3 * 3600
CRON_TAG = f"# {SKILL}"                 # ends our crontab line; nothing else is ever edited
RETENTION_KEY = "cleanupPeriodDays"     # Claude Code's own transcript retention setting
BACKUPS_KEPT = 2
INSTALLED = ("SKILL.md", "scripts", "references")   # what an install puts in a skill dir
RECORD = "install.json"                 # in the state dir: what install changed that uninstall reverts
SANDBOX = " (sandbox: not loaded)"
PLATFORM = sys.platform


@dataclass
class Agent:
    key: str
    name: str
    home: str                          # relative to $HOME; presence means "installed"
    skills: Optional[str]              # where this agent reads skills (None: reads ~/.agents/skills)
    config: Optional[str] = None       # hooks file, relative to $HOME
    events: Dict[str, str] = field(default_factory=dict)   # agent event -> our hook event


AGENTS: List[Agent] = [
    Agent("claude", "Claude Code", ".claude", ".claude/skills", ".claude/settings.json",
          {"UserPromptSubmit": "prompt", "Stop": "stop", "SessionEnd": "session-end"}),
    Agent("codex", "Codex", ".codex", None, ".codex/hooks.json",
          {"UserPromptSubmit": "prompt", "Stop": "stop"}),
    Agent("cursor", "Cursor", ".cursor", ".cursor/skills", ".cursor/hooks.json",
          {"stop": "stop", "sessionEnd": "session-end"}),
    Agent("gemini", "Gemini CLI / Antigravity", ".gemini", ".gemini/skills", ".gemini/settings.json",
          {"BeforeAgent": "prompt", "AfterAgent": "stop", "SessionEnd": "session-end"}),
    Agent("opencode", "OpenCode", ".config/opencode", None),        # reads ~/.agents/skills
    Agent("copilot", "GitHub Copilot CLI", ".copilot", ".copilot/skills"),
]
BY_KEY = {a.key: a for a in AGENTS}


def detect(home: Path) -> List[Agent]:
    return [a for a in AGENTS if (home / a.home).is_dir()]


def pick(home: Path, spec: str) -> List[Agent]:
    if spec in ("auto", ""):
        return detect(home)
    if spec == "all":
        return list(AGENTS)
    keys = [k.strip() for k in spec.split(",") if k.strip()]
    unknown = [k for k in keys if k not in BY_KEY]
    if unknown:
        raise SystemExit(f"unknown agent(s): {', '.join(unknown)} (known: {', '.join(BY_KEY)})")
    return [BY_KEY[k] for k in keys]


def retention_days(text: str) -> int:
    """argparse type for --retention: a whole number of days, at least 1."""
    try:
        days = int(text)
    except ValueError:
        days = 0
    if days < 1:
        raise argparse.ArgumentTypeError(f"needs a whole number of days >= 1, not {text!r}")
    return days


def _same(a: Optional[object], b: Path) -> bool:
    return bool(a) and os.path.realpath(str(a)) == os.path.realpath(b)


def _tilde(p: Path, home: Path) -> str:
    try:
        return "~/" + str(Path(p).relative_to(home))
    except ValueError:
        return str(p)


# ---------------------------------------------------------------- json config editing

class ConfigError(Exception):
    """An agent config we must not rewrite. The caller skips that agent and carries on."""


@dataclass
class Edit:
    path: Path
    changed: bool = False             # rewritten (after a backup) or removed
    removed: bool = False             # deleted: nothing but our hooks was left in it
    hooks: bool = False               # our hooks are in place (install) / were taken out (uninstall)
    retention: Optional[int] = None   # install: the cleanupPeriodDays value now set by us
    note: str = ""                    # one line about cleanupPeriodDays, if anything happened to it


def _load(path: Path) -> dict:
    try:
        if path.is_symlink() and not path.exists():
            raise ConfigError(f"{path} is a broken symlink; fix it and re-run")
        if not path.exists():
            return {}
        data = json.loads(path.read_text() or "{}")
    except ValueError:
        raise ConfigError(f"{path} is not valid JSON; fix it and re-run") from None
    except OSError as e:
        raise ConfigError(f"{path} could not be read ({e.strerror or e}); fix it and re-run") from None
    if not isinstance(data, dict) or not isinstance(data.get("hooks") or {}, dict):
        raise ConfigError(f"{path} is not a JSON object with a hooks object; fix it and re-run")
    return data


def _backup_keys(path: Path) -> List[Tuple[Tuple[int, int], Path]]:
    pat = re.compile(re.escape(path.name) + r"\.bak-(\d+)(?:-(\d+))?")
    found = []
    for p in path.parent.glob(glob.escape(path.name) + ".bak-*"):
        m = pat.fullmatch(p.name)
        if m and p.is_file() and not p.is_symlink():
            found.append(((int(m.group(1)), int(m.group(2) or 0)), p))
    return sorted(found)


def backups(path: Path) -> List[Path]:
    """Our backups of path (<name>.bak-<epoch>[-n]), oldest first. Other files never match."""
    return [p for _, p in _backup_keys(path)]


def _backup(path: Path, src: Path):
    # never older than an existing backup, so a clock that went backwards can't get the new one pruned
    stamp = max([int(time.time())] + [key[0] for key, _ in _backup_keys(path)])
    bak, n = path.with_name(f"{path.name}.bak-{stamp}"), 0
    while os.path.lexists(bak):
        n += 1
        bak = path.with_name(f"{path.name}.bak-{stamp}-{n}")
    shutil.copy2(src, bak)                   # keeps the mode: a 0600 config gets a 0600 backup
    for old in backups(path)[:-BACKUPS_KEPT]:
        old.unlink()


def _save(path: Path, data: dict, before: dict) -> bool:
    """Write data if it differs from what was read: onto the symlink's target, keeping its mode."""
    if data == before:
        return False
    target = Path(os.path.realpath(path))
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        mode = None
        if target.exists():
            mode = stat.S_IMODE(target.stat().st_mode)
            _backup(path, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp.unlink(missing_ok=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600 if mode is not None else 0o666)
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(data, indent=2) + "\n")
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, target)
    except OSError as e:
        _discard(tmp)
        raise ConfigError(f"{path} could not be written ({e.strerror or e}); fix it and re-run") from None
    except BaseException:
        _discard(tmp)
        raise
    return True


def _discard(p: Path):
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass


def _ours(entry) -> bool:
    cmd = entry.get("command") if isinstance(entry, dict) else None
    return isinstance(cmd, str) and HOOK_RE.search(cmd) is not None


def _strip(hooks: dict) -> dict:
    """Remove our entries from nested ({hooks:[...]}) and flat ([{command}]) layouts alike.
    Anything that held none of ours comes back exactly as it was, empty lists included."""
    out = {}
    for ev, items in hooks.items():
        if not isinstance(items, list):
            out[ev] = items
            continue
        kept = []
        for it in items:
            if isinstance(it, dict) and isinstance(it.get("hooks"), list):
                inner = [h for h in it["hooks"] if not _ours(h)]
                if len(inner) == len(it["hooks"]):
                    kept.append(it)
                elif inner:
                    kept.append({**it, "hooks": inner})
            elif not _ours(it):
                kept.append(it)
        if kept or not items:
            out[ev] = kept
    return out


def command(script: Path, event: str, agent: str) -> str:
    return f"python3 {shlex.quote(str(script))} hook {event} --agent {agent}"


def retention_line(days: int) -> str:
    return f"Claude Code {RETENTION_KEY} -> {days} (Claude Code deletes transcripts older than this)"


def _retention(data: dict, retention: Optional[int], owned: Optional[int]) -> Tuple[Optional[int], str]:
    """(value install sets, line to print): set it when unset, or when it is still the value we set."""
    if not retention:
        return None, ""
    if RETENTION_KEY not in data or (owned is not None and data[RETENTION_KEY] == owned):
        return retention, retention_line(retention)
    return None, f"Claude Code {RETENTION_KEY} stays {data[RETENTION_KEY]} (yours; --retention not applied)"


def _owned(record: dict) -> Dict[str, int]:
    """Install record: {real path of a settings file: the cleanupPeriodDays value we set there}."""
    rec = record.get(RETENTION_KEY)
    return {p: v for p, v in rec.items() if isinstance(v, int)} if isinstance(rec, dict) else {}


def owned_retention(record: dict, path: Path) -> Optional[int]:
    """The cleanupPeriodDays value a previous install set in this file, if any."""
    return _owned(record).get(os.path.realpath(path))


def remember_retention(state: Path, record: dict, path: Path, days: int):
    record[RETENTION_KEY] = {**_owned(record), os.path.realpath(path): days}
    write_record(state, record)


def write_hooks(agent: Agent, home: Path, script: Path, retention: Optional[int] = None,
                settings_path: Optional[Path] = None, owned: Optional[int] = None) -> Edit:
    path = settings_path or home / agent.config
    data = _load(path)
    before = copy.deepcopy(data)
    hooks = _strip(data.get("hooks") or {})
    bad = [ev for ev in agent.events if not isinstance(hooks.get(ev, []), list)]
    if bad:
        raise ConfigError(f"{path} has hooks.{bad[0]} that is not a list; fix it and re-run")
    for ev, ours in agent.events.items():
        cmd = command(script, ours, agent.key)
        if agent.key == "cursor":
            entry = {"command": cmd, "timeout": 10}
        elif agent.key == "gemini":
            entry = {"hooks": [{"name": SKILL, "type": "command", "command": cmd, "timeout": 10000}]}
        else:   # claude, codex
            entry = {"hooks": [{"type": "command", "command": cmd, "timeout": 10}]}
        hooks.setdefault(ev, []).append(entry)
    data["hooks"] = hooks
    if agent.key == "cursor":
        data.setdefault("version", 1)
    days, note = _retention(data, retention, owned) if agent.key == "claude" else (None, "")
    if days is not None:
        data[RETENTION_KEY] = days
    return Edit(path, _save(path, data, before), hooks=True, retention=days, note=note)


def remove_hooks(agent: Agent, home: Path, settings_path: Optional[Path] = None,
                 retention: Optional[int] = None) -> Optional[Edit]:
    """Take our hooks out, plus cleanupPeriodDays if it still equals `retention` (the value we set).
    A file left with nothing else in it is deleted; a file holding none of ours is not touched."""
    path = settings_path or home / agent.config
    if not os.path.lexists(path):
        return None
    data = _load(path)
    before = copy.deepcopy(data)
    old = data.get("hooks") or {}
    hooks = _strip(old)
    if hooks != old:
        if hooks:
            data["hooks"] = hooks
        else:
            data.pop("hooks", None)
    note = ""
    if retention is not None and RETENTION_KEY in data:
        if data[RETENTION_KEY] == retention:
            del data[RETENTION_KEY]
            note = f"Claude Code {RETENTION_KEY} {retention} removed (back to Claude Code's default)"
        else:
            note = f"Claude Code {RETENTION_KEY} left at {data[RETENTION_KEY]} (changed since install)"
    edit = Edit(path, hooks=hooks != old, note=note)
    if data == before:
        return edit
    edit.changed = True
    empty = data == {} or (agent.key == "cursor" and data == {"version": 1})
    if empty and not path.is_symlink():
        try:
            path.unlink()
        except OSError as e:
            raise ConfigError(f"{path} could not be removed ({e.strerror or e}); fix it and re-run") from None
        edit.removed = True
    else:
        _save(path, data, before)
    return edit


# ---------------------------------------------------------------- install record

def read_record(state: Path) -> dict:
    try:
        data = json.loads((state / RECORD).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_record(state: Path, record: dict):
    path = state / RECORD
    if not record:
        path.unlink(missing_ok=True)
        return
    state.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------- skill links

def _is_ours(p: Path) -> bool:
    try:
        return SKILL_NAME_RE.search((p / "SKILL.md").read_text()[:400]) is not None
    except (OSError, ValueError):
        return False


def skill_dest(agent: Agent, home: Path) -> Path:
    return home / (agent.skills or ".agents/skills") / SKILL


def link_skill(agent: Agent, home: Path, canonical: Path) -> str:
    """Make the skill visible to one agent without a second copy on disk."""
    dest = skill_dest(agent, home)
    try:
        if dest.resolve() == canonical.resolve():
            return "linked"
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_symlink():
            dest.unlink()
        elif dest.is_dir():
            if not _is_ours(dest):
                return f"skipped: {dest} exists and is not storage-steward"
            for item in INSTALLED:      # refresh an older real copy in place
                src, dst = canonical / item, dest / item
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif src.exists():
                    shutil.copy2(src, dst)
            return "updated copy"
        elif dest.exists():
            return f"skipped: {dest} exists and is not storage-steward"
        os.symlink(canonical, dest)
    except OSError as e:
        return f"skipped: could not link {dest} ({e.strerror or e})"
    return "linked"


def _foreign(d: Path, source: Path) -> List[str]:
    """Paths in our skill dir d that an install from `source` would not have put there."""
    extra = sorted(set(os.listdir(d)) - set(INSTALLED) - {".DS_Store"})
    if extra:
        return extra
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x != "__pycache__"]
        for name in files + [x for x in dirs if os.path.islink(os.path.join(root, x))]:
            rel = os.path.relpath(os.path.join(root, name), d)
            if name != ".DS_Store" and not (source / rel).is_file():
                extra.append(rel)
    return extra


def unlink_skill(home: Path, source: Path, keep: Sequence[Path] = ()) -> Tuple[List[Path], List[str]]:
    """Remove our skill links and real copies of this skill: never through a link, never a copy that
    holds a file an install from `source` (the running skill dir) would not have put there.
    Returns (removed, notes about what was kept)."""
    canonical = home / ".agents/skills" / SKILL
    dests = []
    for agent in AGENTS:
        d = skill_dest(agent, home)
        if d != canonical and d not in dests:
            dests.append(d)
    dests.append(canonical)              # last: the other links may point at it
    removed, notes = [], []
    for d in dests:
        if d in keep:
            continue
        try:
            if d.is_symlink():
                dangling_ours = not d.exists() and Path(os.readlink(d)).name == SKILL
                if _is_ours(d) or dangling_ours:
                    d.unlink()
                    removed.append(d)
            elif d.is_dir() and _is_ours(d):
                extra = _foreign(d, source)
                if extra:
                    notes.append(f"kept {d}: it holds files install did not put there ({', '.join(extra[:3])})")
                else:
                    shutil.rmtree(d)
                    removed.append(d)
        except OSError as e:
            notes.append(f"could not remove {d} ({e.strerror or e})")
    return removed, notes


# ---------------------------------------------------------------- uninstall

def _purge(p: Path) -> bool:
    """Remove a dir of ours (or just the symlink, if it is one). False if there was nothing there."""
    if p.is_symlink():
        p.unlink()
        return True
    if p.is_dir():
        shutil.rmtree(p)
        return True
    return False


def uninstall(home: Path, state: Path, policy_file: Path, script: Path, real_home: bool,
              purge: bool = False) -> Tuple[List[str], int]:
    """Undo install for every agent: hooks, emptied configs, the OS timer, skill links and copies,
    and the cleanupPeriodDays we set. --purge also drops the policy dir and the state dir.
    Returns (summary lines, exit code); a config we cannot parse is skipped and makes it 1."""
    show = (lambda p: _tilde(p, home)) if real_home else str
    record = read_record(state)
    owned = _owned(record)
    files = [(a, home / a.config) for a in AGENTS if a.config]
    files += [(BY_KEY["claude"], Path(p)) for p in owned               # installed with --settings
              if not any(_same(p, f) for _, f in files)]
    hooked, emptied, notes, skipped, keep = [], [], [], [], []
    for agent, path in files:
        revert = owned.get(os.path.realpath(path)) if agent.key == "claude" else None
        try:
            edit = remove_hooks(agent, home, path, retention=revert)
        except ConfigError as e:
            skipped.append(f"  {agent.name}: skipped: {e}")
            keep.append(skill_dest(agent, home))
            continue
        owned.pop(os.path.realpath(path), None)
        if edit and edit.hooks and agent.name not in hooked:
            hooked.append(agent.name)
        if edit and edit.removed:
            emptied.append(show(path))
        if edit and edit.note:
            notes.append("  " + edit.note)
    timer = schedule(home, script, "uninstall", real_home=real_home)
    if skipped:      # hooks left in a skipped file still run the script: keep the shared copy for them
        keep.append(home / ".agents/skills" / SKILL)
        if purge:    # the re-run still needs the install record to revert cleanupPeriodDays
            purge = False
            notes.append("  --purge postponed: run it again once the skipped file is fixed")
    removed, kept = unlink_skill(home, script.parent.parent, keep)
    head = "storage-steward uninstalled" if not skipped else \
        "storage-steward partly uninstalled: fix the skipped file and run uninstall again"
    lines = [head, "  hooks removed from: " + (", ".join(hooked) or "none found")
             + (f"; deleted emptied {', '.join(emptied)}" if emptied else "")]
    lines += skipped
    lines.append("  skill removed from: " + (", ".join(show(p.parent) for p in removed) or "none found"))
    lines += [f"  {n}" for n in kept]
    lines.append(f"  OS timer: {timer}")
    lines += notes
    if not purge:
        if owned:
            record[RETENTION_KEY] = owned
        else:
            record.pop(RETENTION_KEY, None)
        write_record(state, record)
        try:
            state.rmdir()                 # only if install.json was all that was in it
        except OSError:
            pass
    lines += _leftovers(policy_file, state, purge, show)
    baks = [show(path) + ".bak-*" for _, path in files if backups(path)]
    if baks:
        lines.append("  backups kept: " + ", ".join(baks))
    return lines, 1 if skipped else 0


def _purge_policy(policy_file: Path, show) -> Tuple[List[str], List[str]]:
    """The policy dir goes only if it is named storage-steward and holds nothing but what policy.py
    writes there (config, its .bak, its .tmp); otherwise just those files go. Returns (gone, notes)."""
    d = policy_file.parent
    if d.name != SKILL:
        return [], ([f"  kept {show(policy_file)}: not in a {SKILL} dir"] if policy_file.exists() else [])
    mine = {policy_file.name, policy_file.name + ".bak", policy_file.with_suffix(".tmp").name}
    real_dir = d.is_dir() and not d.is_symlink()
    if not real_dir or not set(os.listdir(d)) - mine - {".DS_Store"}:
        return ([show(d)] if _purge(d) else []), []
    gone = []
    for name in sorted(mine):
        if (d / name).is_file():
            (d / name).unlink()
            gone.append(show(d / name))
    return gone, [f"  kept {show(d)}: it holds files storage-steward did not write"]


def _leftovers(policy_file: Path, state: Path, purge: bool, show) -> List[str]:
    """--purge: remove the policy dir (see _purge_policy) and the state dir. Otherwise say where they are."""
    if not purge:
        left = [show(p) for p in (policy_file, state) if p.exists()]
        return [f"  kept: {', '.join(left)} (uninstall --purge removes them)"] if left else []
    gone, lines = [], []
    for step in (lambda: _purge_policy(policy_file, show), lambda: ([show(state)] if _purge(state) else [], [])):
        try:
            done, notes = step()
        except OSError as e:
            done, notes = [], [f"  could not purge: {e}"]
        gone += done
        lines += notes
    return ([f"  purged: {', '.join(gone)}"] if gone else []) + lines


def plan(targets: Sequence[Agent], home: Path, settings: Optional[Path], retention: Optional[int],
         owned: Optional[int]) -> List[str]:
    """Dry-run lines: one per agent (skill link, hook events, file), then retention and backups."""
    lines, note = [], ""
    for agent in targets:
        parts = [] if settings else [f"link {skill_dest(agent, home)}"]
        if agent.config:
            path = settings or home / agent.config
            try:
                data = _load(path)
            except ConfigError as e:
                lines.append(f"  {agent.name}: would skip: {e}")
                continue
            parts.append(f"add {', '.join(agent.events)} hooks to {path}")
            if agent.key == "claude":
                note = _retention(data, retention, owned)[1]
        else:
            parts.append("no hook API (covered by --schedule)")
        lines.append(f"  {agent.name}: would " + "; ".join(parts))
    if note:
        lines.append("  " + note)
    lines.append(f"  every config file it edits gets a backup next to it (<file>.bak-<time>, newest "
                 f"{BACKUPS_KEPT} kept)")
    return lines


# ---------------------------------------------------------------- OS scheduler (any agent)

def _args(script: Path) -> List[str]:
    return [sys.executable, str(script), "hook", "stop", "--agent", "scheduler", "--foreground"]


def _plist(script: Path) -> str:
    args = "".join(f"<string>{xml_escape(a)}</string>" for a in _args(script))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{xml_escape(PLIST_LABEL)}</string>
  <key>ProgramArguments</key><array>{args}</array>
  <key>StartInterval</key><integer>{INTERVAL_S}</integer>
  <key>RunAtLoad</key><false/>
  <key>ProcessType</key><string>Background</string>
  <key>LowPriorityIO</key><true/>
  <key>Nice</key><integer>10</integer>
  <key>StandardOutPath</key><string>/dev/null</string>
  <key>StandardErrorPath</key><string>/dev/null</string>
</dict></plist>
"""


def _sd_quote(word: str) -> str:
    """One ExecStart word for systemd: double-quoted, with % specifiers and $ variables made literal."""
    esc = word.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%").replace("$", "$$")
    return f'"{esc}"'


def _systemd(script: Path) -> Dict[str, str]:
    run = " ".join(_sd_quote(a) for a in _args(script))
    return {
        "storage-steward.service": f"[Unit]\nDescription=storage-steward sweep\n\n[Service]\nType=oneshot\n"
                                   f"Nice=10\nIOSchedulingClass=idle\nExecStart={run}\n",
        "storage-steward.timer": "[Unit]\nDescription=storage-steward sweep every 3 hours\n\n[Timer]\n"
                                 "OnBootSec=10min\nOnUnitActiveSec=3h\nPersistent=true\n\n"
                                 "[Install]\nWantedBy=timers.target\n",
    }


def _cron_line(script: Path) -> str:
    run = " ".join(shlex.quote(a) for a in _args(script)).replace("%", "\\%")   # cron: bare % is a newline
    return f"17 */3 * * * {run} {CRON_TAG}"


def _cron_ours(line: str) -> bool:
    return line.rstrip().endswith(CRON_TAG) and "--agent scheduler" in line


def _run(cmd: List[str], stdin: Optional[str] = None) -> Tuple[bool, str]:
    """Run launchctl, systemctl or crontab; (True, stdout) or (False, stderr). Real home only."""
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    return (True, p.stdout) if p.returncode == 0 else (False, p.stderr or p.stdout)


def _crontab() -> Optional[List[str]]:
    """The user's crontab lines ([] when there is none), or None when it could not be read:
    then it must never be rewritten, or every line in it would be lost."""
    if not shutil.which("crontab"):
        return []
    ok, out = _run(["crontab", "-l"])
    if not ok:
        return [] if "no crontab" in out.lower() else None
    text = out.rstrip("\n")
    return text.split("\n") if text else []      # \n only: splitlines() would also split on \f, U+2028


def schedule(home: Path, script: Path, action: str, dry_run: bool = False, real_home: bool = False) -> str:
    """install | uninstall | status for the OS-level sweep timer. For a sandbox home (real_home=False)
    only the plist/unit files under it are written or removed; launchctl, systemctl and crontab are
    never run. On the real home, uninstall calls them only for a timer that is actually installed."""
    if PLATFORM == "darwin":
        return _launchd(home, script, action, dry_run, real_home)
    return _linux(home, script, action, dry_run, real_home)


def _launchd(home: Path, script: Path, action: str, dry_run: bool, real_home: bool) -> str:
    plist = home / "Library/LaunchAgents" / f"{PLIST_LABEL}.plist"
    domain = f"gui/{os.getuid()}"
    if action == "status":
        return f"launchd: {'installed' if plist.exists() else 'not installed'} ({plist})"
    if action == "install":
        if dry_run:
            return _plist(script)
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_text(_plist(script))
        if not real_home:
            return f"launchd agent written: {plist}{SANDBOX}"
        _run(["launchctl", "bootout", domain, str(plist)])
        ok, _ = _run(["launchctl", "bootstrap", domain, str(plist)])
        return f"launchd agent {'loaded' if ok else 'written (load failed; log out and in)'}: every 3h"
    if not plist.exists():
        return "no OS timer installed"
    if dry_run:
        return f"would remove launchd agent {plist}"
    if real_home:
        _run(["launchctl", "bootout", domain, str(plist)])
    plist.unlink()
    return "launchd agent removed" + ("" if real_home else SANDBOX)


def _linux(home: Path, script: Path, action: str, dry_run: bool, real_home: bool) -> str:
    unit_dir = home / ".config/systemd/user"
    units = _systemd(script)
    if action == "status":
        cron = "; crontab entry installed" if real_home and any(map(_cron_ours, _crontab() or [])) else ""
        installed = (unit_dir / "storage-steward.timer").exists()
        return f"systemd timer: {'installed' if installed else 'not installed'}{cron}"
    if action == "install":
        if dry_run:
            return "\n".join(f"# {k}\n{v}" for k, v in units.items())
        if not real_home:
            _write_units(unit_dir, units)
            return f"systemd user timer written: {unit_dir}{SANDBOX}"
        if shutil.which("systemctl"):
            _write_units(unit_dir, units)
            _run(["systemctl", "--user", "daemon-reload"])
            if _run(["systemctl", "--user", "enable", "--now", "storage-steward.timer"])[0]:
                return "systemd user timer enabled: every 3h"
        if not shutil.which("crontab"):
            return "could not install a scheduler (no systemd user session, no crontab)"
        cur = _crontab()
        if cur is None:
            return "could not read your crontab, so it was left alone; no scheduler installed"
        lines = [x for x in cur if not _cron_ours(x)] + [_cron_line(script)]
        ok, _ = _run(["crontab", "-"], "\n".join(lines) + "\n")
        return "crontab entry added: every 3h" if ok else "could not install a scheduler"
    have_units = [unit_dir / n for n in units if (unit_dir / n).exists()]
    cron = (_crontab() or []) if real_home else []     # unreadable: never rewritten
    if not have_units and not any(map(_cron_ours, cron)):
        return "no OS timer installed"
    if dry_run:
        return "would remove the systemd timer / crontab entry"
    done = []
    if have_units:
        if real_home and shutil.which("systemctl"):
            _run(["systemctl", "--user", "disable", "--now", "storage-steward.timer"])
        for p in have_units:
            p.unlink()
        if real_home and shutil.which("systemctl"):
            _run(["systemctl", "--user", "daemon-reload"])
        done.append("systemd timer")
    if any(map(_cron_ours, cron)):
        kept = [x for x in cron if not _cron_ours(x)]
        _run(["crontab", "-"], "".join(x + "\n" for x in kept))
        done.append("crontab entry")
    return " and ".join(done) + " removed" + ("" if real_home else SANDBOX)


def _write_units(unit_dir: Path, units: Dict[str, str]):
    unit_dir.mkdir(parents=True, exist_ok=True)
    for name, body in units.items():
        (unit_dir / name).write_text(body)
