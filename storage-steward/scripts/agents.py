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
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

MARK = "steward.py' hook "            # identifies our hook commands in any agent's config
SKILL = "storage-steward"
PLIST_LABEL = "dev.storage-steward.sweep"
INTERVAL_S = 3 * 3600


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


# ---------------------------------------------------------------- json config editing

def _load(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text() or "{}")
    except ValueError:
        raise SystemExit(f"refusing: {path} is not valid JSON; fix it first")


def _save(path: Path, data: dict):
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".bak-{int(time.time())}"))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _ours(entry: dict) -> bool:
    return MARK in entry.get("command", "")


def _strip(hooks: dict) -> dict:
    """Remove our entries from nested ({hooks:[...]}) and flat ([{command}]) layouts alike."""
    out = {}
    for ev, items in hooks.items():
        kept = []
        for it in items:
            if "hooks" in it and isinstance(it["hooks"], list):
                inner = [h for h in it["hooks"] if not _ours(h)]
                if inner:
                    kept.append({**it, "hooks": inner})
            elif not _ours(it):
                kept.append(it)
        if kept:
            out[ev] = kept
    return out


def command(script: Path, event: str, agent: str) -> str:
    return f"python3 '{script}' hook {event} --agent {agent}"


def write_hooks(agent: Agent, home: Path, script: Path, retention: Optional[int] = None,
                settings_path: Optional[Path] = None) -> Path:
    path = settings_path or home / agent.config
    data = _load(path)
    hooks = _strip(data.get("hooks", {}))
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
    if agent.key == "claude" and retention and "cleanupPeriodDays" not in data:
        data["cleanupPeriodDays"] = retention
    _save(path, data)
    return path


def remove_hooks(agent: Agent, home: Path, settings_path: Optional[Path] = None) -> Optional[Path]:
    path = settings_path or home / agent.config
    if not path.exists():
        return None
    data = _load(path)
    hooks = _strip(data.get("hooks", {}))
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
    _save(path, data)
    return path


# ---------------------------------------------------------------- skill links

def _is_ours(p: Path) -> bool:
    try:
        return f"name: {SKILL}" in (p / "SKILL.md").read_text()[:400]
    except OSError:
        return False


def link_skill(agent: Agent, home: Path, canonical: Path) -> str:
    """Make the skill visible to one agent without a second copy on disk."""
    dest = home / (agent.skills or ".agents/skills") / SKILL
    if dest.resolve() == canonical.resolve():
        return "linked"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_symlink():
        dest.unlink()
    elif dest.is_dir():
        if not _is_ours(dest):
            return f"skipped: {dest} exists and is not storage-steward"
        for item in ("SKILL.md", "scripts", "references"):      # refresh an older real copy in place
            src, dst = canonical / item, dest / item
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif src.exists():
                shutil.copy2(src, dst)
        return "updated copy"
    os.symlink(canonical, dest)
    return "linked"


# ---------------------------------------------------------------- OS scheduler (any agent)

def _plist(script: Path) -> str:
    args = "".join(f"<string>{a}</string>" for a in
                   (sys.executable, str(script), "hook", "stop", "--agent", "scheduler", "--foreground"))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{PLIST_LABEL}</string>
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


def _systemd(script: Path) -> Dict[str, str]:
    run = f"{sys.executable} {script} hook stop --agent scheduler --foreground"
    return {
        "storage-steward.service": f"[Unit]\nDescription=storage-steward sweep\n\n[Service]\nType=oneshot\n"
                                   f"Nice=10\nIOSchedulingClass=idle\nExecStart={run}\n",
        "storage-steward.timer": "[Unit]\nDescription=storage-steward sweep every 3 hours\n\n[Timer]\n"
                                 "OnBootSec=10min\nOnUnitActiveSec=3h\nPersistent=true\n\n"
                                 "[Install]\nWantedBy=timers.target\n",
    }


def _run(cmd: List[str]) -> bool:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def schedule(home: Path, script: Path, action: str, dry_run: bool = False) -> str:
    """install | uninstall | status for the OS-level sweep timer."""
    if sys.platform == "darwin":
        plist = home / "Library/LaunchAgents" / f"{PLIST_LABEL}.plist"
        domain = f"gui/{os.getuid()}"
        if action == "status":
            return f"launchd: {'installed' if plist.exists() else 'not installed'} ({plist})"
        if action == "install":
            if dry_run:
                return _plist(script)
            plist.parent.mkdir(parents=True, exist_ok=True)
            plist.write_text(_plist(script))
            _run(["launchctl", "bootout", domain, str(plist)])
            ok = _run(["launchctl", "bootstrap", domain, str(plist)])
            return f"launchd agent {'loaded' if ok else 'written (load failed; log out and in)'}: every 3h"
        if not dry_run:
            _run(["launchctl", "bootout", domain, str(plist)])
            plist.unlink(missing_ok=True)
        return "launchd agent removed"
    unit_dir = home / ".config/systemd/user"
    units = _systemd(script)
    has_systemd = shutil.which("systemctl") is not None
    if action == "status":
        return f"systemd timer: {'installed' if (unit_dir / 'storage-steward.timer').exists() else 'not installed'}"
    if action == "install":
        if dry_run:
            return "\n".join(f"# {k}\n{v}" for k, v in units.items())
        if has_systemd:
            unit_dir.mkdir(parents=True, exist_ok=True)
            for name, body in units.items():
                (unit_dir / name).write_text(body)
            _run(["systemctl", "--user", "daemon-reload"])
            if _run(["systemctl", "--user", "enable", "--now", "storage-steward.timer"]):
                return "systemd user timer enabled: every 3h"
        line = f"17 */3 * * * {sys.executable} {script} hook stop --agent scheduler --foreground # {SKILL}"
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout if shutil.which("crontab") else ""
        lines = [l for l in cur.splitlines() if SKILL not in l] + [line]
        p = subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, capture_output=True)
        return "crontab entry added: every 3h" if p.returncode == 0 else "could not install a scheduler"
    if not dry_run:
        if has_systemd:
            _run(["systemctl", "--user", "disable", "--now", "storage-steward.timer"])
            for name in units:
                (unit_dir / name).unlink(missing_ok=True)
        if shutil.which("crontab"):
            cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
            if SKILL in cur:
                kept = "\n".join(l for l in cur.splitlines() if SKILL not in l)
                subprocess.run(["crontab", "-"], input=kept + "\n", text=True, capture_output=True)
    return "scheduler removed"
