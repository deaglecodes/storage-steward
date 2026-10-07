"""User policy for storage-steward: what goes, what stays, and when.

File: $XDG_CONFIG_HOME/storage-steward/config.json (default ~/.config/storage-steward/config.json),
or $STORAGE_STEWARD_CONFIG. Every key is optional:

  {
    "rules": {"claude-transcripts": {"tier": "off"},           # never touch them
              "claude-task-output": {"idle_days": 0.25},        # sweep after 6 hours instead of 1 day
              "codex-sessions": {"tier": "auto", "idle_days": 45}},
    "keep": ["~/models", "~/code/client-x/**", "*.mov"],       # never delete these, whatever the rule
    "custom": [{"name": "work-builds", "paths": ["~/work/*/build"], "idle_days": 7, "tier": "auto"}],
    "sweep_every_hours": 3, "warn_below_gb": 20, "warn_below_percent": 5, "probation_days": 7
  }

Tiers: auto (hooks sweep it), confirm (ask first), info (report only), off (ignore the rule).
A broken file never breaks a hook: the steward falls back to defaults and reports the problem.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rules import BUILTIN, RULES, Rule, check_custom, custom_rule

TIERS = ("auto", "confirm", "info", "off")
NUMBERS = {"sweep_every_hours": (0.25, 24 * 30), "warn_below_gb": (0, 10000),
           "warn_below_percent": (0, 50), "probation_days": (1, 90)}
DEFAULTS = {"sweep_every_hours": 3.0, "warn_below_gb": 20.0, "warn_below_percent": 5.0, "probation_days": 7.0}


def path_for(home: Path, real_home: bool) -> Path:
    if real_home and os.environ.get("STORAGE_STEWARD_CONFIG"):
        return Path(os.environ["STORAGE_STEWARD_CONFIG"]).expanduser()
    base = Path(os.environ["XDG_CONFIG_HOME"]) if real_home and os.environ.get("XDG_CONFIG_HOME") else home / ".config"
    return base / "storage-steward" / "config.json"


def parse_days(text: str) -> float:
    """'14', '14d', '6h', '0.5' -> days."""
    t = str(text).strip().lower()
    if t.endswith("h"):
        return float(t[:-1]) / 24
    if t.endswith("d"):
        t = t[:-1]
    return float(t)


class Policy:
    """The effective policy: built-in rules, the user's overrides, keep list and custom rules."""

    def __init__(self, home: Path, real_home: bool):
        self.home, self.path = home, path_for(home, real_home)
        self.raw: dict = {}
        self.errors: List[str] = []
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text() or "{}")
                self.raw = data if isinstance(data, dict) else {}
                if not isinstance(data, dict):
                    self.errors.append("config root must be a JSON object")
            except (OSError, ValueError) as e:
                self.errors.append(f"config ignored ({e.__class__.__name__}: {e})")
        self.overrides: Dict[str, dict] = {}
        for rid, ov in (self.raw.get("rules") or {}).items():
            if not isinstance(ov, dict):
                self.errors.append(f"rules.{rid}: must be an object")
                continue
            if rid not in BUILTIN and not any(c.get("name") == rid for c in self._custom_specs()):
                self.errors.append(f"rules.{rid}: no such rule")
                continue
            clean = {}
            if "tier" in ov:
                if ov["tier"] in TIERS:
                    clean["tier"] = ov["tier"]
                else:
                    self.errors.append(f"rules.{rid}.tier: use one of {', '.join(TIERS)}")
            if "idle_days" in ov:
                try:
                    d = float(ov["idle_days"])
                    if d <= 0:
                        raise ValueError
                    clean["idle_days"] = d
                except (TypeError, ValueError):
                    self.errors.append(f"rules.{rid}.idle_days: must be a positive number")
            self.overrides[rid] = clean
        keep = self.raw.get("keep") or []
        self.keep: List[str] = [k for k in keep if isinstance(k, str)] if isinstance(keep, list) else []
        self.custom: List[Rule] = []
        for spec in self._custom_specs():
            problems = check_custom(home, spec)
            if problems:
                self.errors.extend(problems)
            else:
                self.custom.append(custom_rule(home, spec))
        self.numbers = dict(DEFAULTS)
        for key, (lo, hi) in NUMBERS.items():
            if key in self.raw:
                try:
                    v = float(self.raw[key])
                    if not lo <= v <= hi:
                        raise ValueError
                    self.numbers[key] = v
                except (TypeError, ValueError):
                    self.errors.append(f"{key}: must be a number between {lo} and {hi}")

    def _custom_specs(self) -> List[dict]:
        c = self.raw.get("custom") or []
        return [x for x in c if isinstance(x, dict)] if isinstance(c, list) else []

    def effective(self) -> List[Tuple[Rule, str, Optional[float], bool]]:
        """(rule, tier, idle_days, overridden) for every rule, built-in first, then the user's own."""
        out = []
        for r in RULES + self.custom:
            ov = self.overrides.get(r.id, {})
            tier = ov.get("tier", r.tier)
            if r.custom and tier == "auto" and r.tier == "confirm":
                tier = "confirm"        # custom rules inside Documents/Desktop/... stay ask-first
            days = ov.get("idle_days", r.days) if r.days is not None else None
            out.append((r, tier, days, bool(ov)))
        return out


# ---------------------------------------------------------------- editing (CLI)

def _load_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except ValueError:
        raise SystemExit(f"refusing: {path} is not valid JSON; fix or move it first")
    return data if isinstance(data, dict) else {}


def _save_raw(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def edit(home: Path, real_home: bool, a) -> str:
    """Apply one `config` action and return a one-line summary."""
    path = path_for(home, real_home)
    data = _load_raw(path)
    customs = data.setdefault("custom", [])
    names = set(BUILTIN) | {c.get("name") for c in customs if isinstance(c, dict)}
    act = a.action
    if act == "show":
        pol = Policy(home, real_home)
        body = json.dumps(pol.raw, indent=1) if pol.raw else "(no config yet: built-in defaults)"
        errs = "".join(f"\nproblem: {e}" for e in pol.errors)
        return f"{path}\n{body}{errs}"
    if act in ("set", "unset"):
        if a.rule not in names:
            raise SystemExit(f"unknown rule {a.rule!r}; see `steward.py rules`")
        rules = data.setdefault("rules", {})
        if act == "unset":
            rules.pop(a.rule, None)
            msg = f"{a.rule}: back to defaults"
        else:
            if a.tier is None and a.idle is None:
                raise SystemExit("set needs --tier and/or --idle")
            ov = rules.setdefault(a.rule, {})
            if a.tier is not None:
                if a.tier not in TIERS:
                    raise SystemExit(f"--tier must be one of {', '.join(TIERS)}")
                ov["tier"] = a.tier
            if a.idle is not None:
                d = parse_days(a.idle)
                if d <= 0:
                    raise SystemExit("--idle must be positive (e.g. 14, 14d, 6h)")
                ov["idle_days"] = round(d, 4)
            msg = f"{a.rule}: " + ", ".join(f"{k}={v}" for k, v in ov.items())
    elif act in ("keep", "unkeep"):
        keep = data.setdefault("keep", [])
        for p in a.paths:
            if act == "keep" and p not in keep:
                keep.append(p)
            if act == "unkeep" and p in keep:
                keep.remove(p)
        msg = f"keep list: {', '.join(keep) or '(empty)'}"
    elif act == "add":
        spec = {"name": a.name, "paths": a.path, "idle_days": round(parse_days(a.idle), 4), "tier": a.tier}
        if a.label:
            spec["label"] = a.label
        problems = check_custom(home, spec)
        if problems:
            raise SystemExit("refusing: " + "; ".join(problems))
        customs[:] = [c for c in customs if c.get("name") != a.name] + [spec]
        r = custom_rule(home, spec)
        capped = " (capped to confirm: inside a personal folder)" if r.tier != a.tier else ""
        msg = f"added rule {a.name}: {', '.join(a.path)} idle {spec['idle_days']}d tier {r.tier}{capped}"
    elif act == "drop":
        before = len(customs)
        customs[:] = [c for c in customs if c.get("name") != a.name]
        (data.get("rules") or {}).pop(a.name, None)
        if len(customs) == before:
            raise SystemExit(f"no custom rule named {a.name!r}")
        msg = f"dropped rule {a.name}"
    else:
        raise SystemExit(f"unknown config action {act}")
    if not customs:
        data.pop("custom", None)
    if not data.get("rules"):
        data.pop("rules", None)
    if not data.get("keep"):
        data.pop("keep", None)
    _save_raw(path, data)
    return f"{msg} | saved {path}"
