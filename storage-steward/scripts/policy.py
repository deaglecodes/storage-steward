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
A broken file never breaks a hook, and it fails closed: if the file or its keep list can't be read,
deletes pause until it is fixed (scan says why); a rule whose override has a typo is switched off.
"""
from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from rules import BUILTIN, RULES, KeepList, Rule, check_custom, custom_rule, positive_days

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
    """'14', '14d', '6h', '0.5' -> days; ValueError unless finite and above zero."""
    t = str(text).strip().lower()
    if t.endswith("h"):
        return positive_days(float(t[:-1]) / 24)
    if t.endswith("d"):
        t = t[:-1]
    return positive_days(t)


class Policy:
    """The effective policy: built-in rules, the user's overrides, keep list and custom rules.

    Never raises. `paused` is set (deletes stop) when the user's intent can't be read safely.
    """

    def __init__(self, home: Path, real_home: bool):
        self.home, self.path = home, path_for(home, real_home)
        self.raw: dict = {}
        self.errors: List[str] = []
        self.paused = ""
        self.overrides: Dict[str, dict] = {}
        self.keep: List[str] = []
        self.custom: List[Rule] = []
        self.numbers = dict(DEFAULTS)
        self.keeper = KeepList(home, [])
        try:
            self._load()
            self.keeper = KeepList(home, self.keep)
            self.errors.extend(self.keeper.problems)
            if self.keeper.broken:
                self._pause("keep: an entry can't be read, so it can't protect anything")
        except Exception as e:      # a config shape nobody anticipated: stop deleting, keep working
            self._pause(f"config not understood ({e.__class__.__name__}: {e})")

    def _pause(self, why: str):
        self.errors.append(why)
        self.paused = self.paused or why

    def _load(self):
        try:
            text = self.path.read_text()
        except (FileNotFoundError, NotADirectoryError):
            return                  # no config: built-in defaults
        except OSError as e:        # it may exist but can't be read (permissions): its keep list would be lost
            return self._pause(f"config can't be read ({e.__class__.__name__}: {e})")
        try:
            data = json.loads(text or "{}")
        except ValueError as e:
            return self._pause(f"config can't be read ({e.__class__.__name__}: {e})")
        if not isinstance(data, dict):
            return self._pause("config root must be a JSON object")
        self.raw = data
        self._load_keep(data.get("keep"))
        rules = data.get("rules") or {}
        if not isinstance(rules, dict):
            self._pause("rules: must be an object of rule-name: settings")
            rules = {}
        customs = self._custom_specs()
        for spec in customs:
            problems = check_custom(self.home, spec)
            if problems:
                self.errors.extend(problems)
                continue
            try:
                self.custom.append(custom_rule(self.home, spec))
            except (TypeError, ValueError) as e:
                self.errors.append(f"custom rule {spec.get('name')!r}: {e}")
        known = set(BUILTIN) | {r.id for r in self.custom}
        for rid, ov in rules.items():
            if rid not in known:
                self.errors.append(f"rules.{rid}: no such rule")
                continue
            self.overrides[rid] = self._override(rid, ov)
        for key, (lo, hi) in NUMBERS.items():
            if key in data:
                try:
                    v = float(data[key])
                    if not (math.isfinite(v) and lo <= v <= hi):
                        raise ValueError
                    self.numbers[key] = v
                except (TypeError, ValueError):
                    self.errors.append(f"{key}: must be a number between {lo} and {hi}")

    def _load_keep(self, keep):
        if keep is None:
            return
        if isinstance(keep, str):
            self.errors.append("keep: should be a list; read as one entry")
            keep = [keep]
        if not isinstance(keep, list) or not all(isinstance(k, str) for k in keep):
            return self._pause("keep: must be a list of paths or patterns")
        self.keep = keep

    def _override(self, rid: str, ov) -> dict:
        """One rule's settings. Anything unreadable switches the rule off rather than back to its default."""
        if not isinstance(ov, dict):
            self.errors.append(f"rules.{rid}: must be an object; rule off until fixed")
            return {"tier": "off"}
        clean = {}
        if "tier" in ov:
            if ov["tier"] in TIERS:
                clean["tier"] = ov["tier"]
            else:
                self.errors.append(f"rules.{rid}.tier: use one of {', '.join(TIERS)}; rule off until fixed")
                return {"tier": "off"}
        if "idle_days" in ov:
            try:
                clean["idle_days"] = positive_days(ov["idle_days"])
            except (TypeError, ValueError):
                self.errors.append(f"rules.{rid}.idle_days: must be a positive number; rule off until fixed")
                return {"tier": "off"}
        return clean

    def _custom_specs(self) -> List[dict]:
        c = self.raw.get("custom") or []
        if not isinstance(c, list):
            self.errors.append("custom: must be a list of rules")
            return []
        bad = [x for x in c if not isinstance(x, dict)]
        if bad:
            self.errors.append("custom: every rule must be an object")
        return [x for x in c if isinstance(x, dict)]

    def effective(self) -> List[Tuple[Rule, str, Optional[float], bool]]:
        """(rule, tier, idle_days, overridden) for every rule, built-in first, then the user's own."""
        out = []
        for r in RULES + self.custom:
            ov = self.overrides.get(r.id, {})
            tier = ov.get("tier", r.tier)
            if r.capped and tier == "auto":
                tier = "confirm"        # rules reaching into Documents/Desktop/... stay ask-first
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
    if not isinstance(data, dict):
        raise SystemExit(f"refusing: {path} must hold a JSON object; fix or move it first")
    return data


def _section(data: dict, key: str, kind: type):
    value = data.setdefault(key, kind())
    if isinstance(value, str) and kind is list:          # "keep": "~/x" -> ["~/x"]
        value = data[key] = [value]
    if not isinstance(value, kind):
        raise SystemExit(f"refusing: '{key}' in the config must be a {'list' if kind is list else 'object'}; "
                         "fix it by hand first (steward.py config show)")
    return value


def _days(text: str) -> float:
    try:
        return round(parse_days(text), 4)
    except ValueError:
        raise SystemExit(f"--idle {text!r}: use a positive number of days or hours, e.g. 14, 14d or 6h")


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
    act = a.action
    if act == "show":
        pol = Policy(home, real_home)
        try:
            body = path.read_text() if path.exists() else "(no config yet: built-in defaults)"
        except OSError as e:
            body = f"(can't read: {e})"
        errs = "".join(f"\nproblem: {e}" for e in pol.errors)
        paused = f"\ndeletes paused until this is fixed: {pol.paused}" if pol.paused else ""
        return f"{path}\n{body.rstrip()}{errs}{paused}"
    data = _load_raw(path)
    customs = _section(data, "custom", list)
    names = set(BUILTIN) | {c.get("name") for c in customs if isinstance(c, dict)}
    if act in ("set", "unset"):
        if a.rule not in names:
            raise SystemExit(f"unknown rule {a.rule!r}; see `steward.py rules`")
        rules = _section(data, "rules", dict)
        if act == "unset":
            rules.pop(a.rule, None)
            msg = f"{a.rule}: back to defaults"
        else:
            if a.tier is None and a.idle is None:
                raise SystemExit("set needs --tier and/or --idle")
            ov = rules.setdefault(a.rule, {})
            if not isinstance(ov, dict):
                ov = rules[a.rule] = {}
            if a.tier is not None:
                if a.tier not in TIERS:
                    raise SystemExit(f"--tier must be one of {', '.join(TIERS)}")
                ov["tier"] = a.tier
            if a.idle is not None:
                ov["idle_days"] = _days(a.idle)
            msg = f"{a.rule}: " + ", ".join(f"{k}={v}" for k, v in ov.items())
    elif act in ("keep", "unkeep"):
        keep = _section(data, "keep", list)
        for p in a.paths:
            if act == "keep" and p not in keep:
                keep.append(p)
            if act == "unkeep" and p in keep:
                keep.remove(p)
        msg = f"keep list: {', '.join(keep) or '(empty)'}"
    elif act == "add":
        spec = {"name": a.name, "paths": a.path, "idle_days": _days(a.idle), "tier": a.tier}
        if a.label:
            spec["label"] = a.label
        problems = check_custom(home, spec)
        if problems:
            raise SystemExit("refusing: " + "; ".join(problems))
        customs[:] = [c for c in customs if not (isinstance(c, dict) and c.get("name") == a.name)] + [spec]
        r = custom_rule(home, spec)
        capped = " (capped to confirm: inside a personal folder)" if r.tier != a.tier else ""
        msg = f"added rule {a.name}: {', '.join(a.path)} idle {spec['idle_days']}d tier {r.tier}{capped}"
    elif act == "drop":
        before = len(customs)
        customs[:] = [c for c in customs if not (isinstance(c, dict) and c.get("name") == a.name)]
        if isinstance(data.get("rules"), dict):
            data["rules"].pop(a.name, None)
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
