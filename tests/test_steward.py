"""Safety + behavior tests for storage-steward. Run: python3 -m unittest discover tests -v"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "storage-steward" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import steward  # noqa: E402
from rules import DAY, GIB, Item  # noqa: E402

NOW = time.time()


def mk(path: Path, size: int = 1024, age_days: float = 0.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"x" * size)
    t = NOW - age_days * DAY
    os.utime(path, (t, t))
    return path


def age_tree(path: Path, age_days: float):
    t = NOW - age_days * DAY
    for root, dirs, files in os.walk(path):
        for n in files + dirs:
            os.utime(os.path.join(root, n), (t, t), follow_symlinks=False)
    os.utime(path, (t, t))


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        base = Path(self.td.name).resolve()
        self.home, self.tmp, self.utmp = base / "home", base / "tmp", base / "utmp"
        for d in (self.home, self.tmp, self.utmp):
            d.mkdir()
        self.ctmp = self.tmp / f"claude-{os.getuid()}"

    def tearDown(self):
        self.td.cleanup()

    def run_cli(self, *args, session=None):
        argv = ["--home", str(self.home), "--tmp", str(self.tmp), "--user-tmp", str(self.utmp), "--now", str(NOW)]
        if session:
            argv += ["--session", session]
        buf, stdin = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO("{}")
        try:
            with redirect_stdout(buf):
                code = steward.main(argv + list(args))
        finally:
            sys.stdin = stdin
        return code, buf.getvalue()

    def ctx(self, session=None):
        ns = steward.argparse.Namespace(home=str(self.home), tmp=str(self.tmp), user_tmp=str(self.utmp),
                                        now=NOW, cwd=None, session=session, protect=None)
        return steward.Ctx(ns)


class GuardTests(Sandbox):
    def test_refuses_root_outside_and_never_paths(self):
        c = self.ctx()
        root = self.home / ".npm/_npx"
        (root / "a").mkdir(parents=True)
        self.assertTrue(c.allowed(Item(str(root / "a"), 0, str(root))))
        self.assertFalse(c.allowed(Item(str(root), 0, str(root))), "root itself")
        self.assertFalse(c.allowed(Item(str(self.home / "Documents"), 0, str(self.home))), "never path")
        self.assertFalse(c.allowed(Item(str(self.home / ".claude"), 0, str(self.home))), "ancestor of settings")
        self.assertFalse(c.allowed(Item(str(self.tmp / "x"), 0, str(root))), "outside root")

    def test_symlink_escape_is_not_followed(self):
        victim = mk(self.home / "Documents" / "thesis.docx", age_days=60)
        root = self.home / ".npm/_npx"
        root.mkdir(parents=True)
        os.symlink(self.home / "Documents", root / "evil")
        age_tree(root, 60)
        self.run_cli("sweep", "--no-probation")
        self.assertTrue(victim.exists(), "symlink target must survive")

    def test_session_and_recent_writes_protected(self):
        sess = "11111111-2222-3333-4444-555555555555"
        out = mk(self.ctmp / "-proj" / sess / "tasks" / "a.output", 2048, age_days=5)
        recent = mk(self.ctmp / "-proj" / "99999999-2222-3333-4444-555555555555" / "tasks" / "b.output", 2048, age_days=0)
        self.run_cli("sweep", session=sess)
        self.assertTrue(out.exists(), "current session kept")
        self.assertTrue(recent.exists(), "recent output kept")


class RuleTests(Sandbox):
    def test_task_output_idle_and_runaway(self):
        s = "99999999-2222-3333-4444-555555555555"
        old = mk(self.ctmp / "-p" / s / "tasks" / "old.output", 4096, age_days=2)
        fresh = mk(self.ctmp / "-p" / s / "tasks" / "fresh.output", 4096, age_days=0.5)
        self.run_cli("sweep")
        self.assertFalse(old.exists())
        self.assertTrue(fresh.exists(), "small + <24h idle stays")

    def test_sandbox_only_plugins_trimmed_outputs_kept(self):
        sb = self.home / "Library/Application Support/Claude/local-agent-mode-sessions/acct/org/local_abc"
        plug = mk(sb / ".claude/plugins/p/big.bin", 1 << 20)
        deliverable = mk(sb / "outputs" / "report.pdf", 4096)
        transcript = mk(sb / ".claude/projects/x/s.jsonl", 4096)
        age_tree(sb, 5)
        self.run_cli("sweep")
        self.assertFalse(plug.exists(), "plugin clone trimmed")
        self.assertTrue(deliverable.exists(), "outputs kept")
        self.assertTrue(transcript.exists(), "sandbox transcript kept")

    def test_confirm_tier_requires_yes(self):
        mk(self.home / ".codex/sessions/2026/01/01/r.jsonl", 4096, age_days=90)
        code, out = self.run_cli("sweep", "--tier", "confirm")
        self.assertEqual(code, 2)
        self.assertIn("refusing", out)
        self.assertTrue((self.home / ".codex/sessions/2026/01/01/r.jsonl").exists())
        self.run_cli("sweep", "--tier", "confirm", "--only", "codex-sessions", "--yes")
        self.assertFalse((self.home / ".codex/sessions/2026/01/01/r.jsonl").exists())

    def test_dirty_worktree_kept_clean_removed(self):
        main = repo(self.home / "code/main")
        clean = worktree(main, self.home / ".codex/worktrees/clean")
        dirty = worktree(main, self.home / ".codex/worktrees/dirty")
        (dirty / "a.txt").write_text("changed")
        for d in (clean, dirty):
            age_tree(d, 30)
        self.run_cli("sweep", "--tier", "confirm", "--only", "agent-worktrees", "--yes")
        self.assertFalse(clean.exists())
        self.assertTrue(dirty.exists(), "uncommitted work must survive")

    def test_stale_project_deps_skip_active_project(self):
        old = self.home / "code" / "oldproj"
        mk(old / "package.json")
        mk(old / "node_modules/x/index.js", 8192)
        age_tree(old, 60)
        active = self.home / "code" / "newproj"
        mk(active / "package.json")
        mk(active / "node_modules/x/index.js", 8192, age_days=60)
        self.run_cli("sweep", "--tier", "confirm", "--only", "stale-project-deps", "--yes")
        self.assertFalse((old / "node_modules").exists())
        self.assertTrue((active / "node_modules").exists(), "recent package.json => active project")


class SecondChanceTests(Sandbox):
    def _entry(self):
        e = self.home / ".npm/_npx/abc123"
        mk(e / "package.json", 512)
        mk(e / "node_modules/.package-lock.json", 512)
        age_tree(e, 20)
        return e

    def test_unread_entry_evicted_after_probation(self):
        e = self._entry()
        self.run_cli("sweep")                      # arms
        self.assertTrue(e.exists(), "first sweep only arms")
        later = NOW + 8 * DAY
        argv = ["--home", str(self.home), "--now", str(later), "sweep"]
        with redirect_stdout(io.StringIO()):
            steward.main(argv)
        self.assertFalse(e.exists(), "unread after probation => evicted")

    def test_read_entry_is_rescued(self):
        e = self._entry()
        self.run_cli("sweep")                      # arms (atime < mtime)
        (e / "package.json").read_bytes()          # real read => APFS/relatime bumps atime
        later = NOW + 8 * DAY
        with redirect_stdout(io.StringIO()):
            steward.main(["--home", str(self.home), "--now", str(later), "sweep"])
        self.assertTrue(e.exists(), "a cache entry in use must survive")


class InstallTests(Sandbox):
    def test_install_idempotent_preserves_other_hooks(self):
        sp = self.home / "settings.json"
        sp.write_text(json.dumps({"model": "x", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
        for _ in range(2):
            self.run_cli("install", "--settings", str(sp), "--retention", "21")
        s = json.loads(sp.read_text())
        stops = [h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]]
        self.assertEqual(sum("steward.py" in c for c in stops), 1, "no duplicates")
        self.assertIn("echo mine", stops)
        self.assertEqual(s["cleanupPeriodDays"], 21)
        self.assertTrue(list(self.home.glob("settings.json.bak-*")), "backup written")
        self.run_cli("uninstall", "--settings", str(sp))
        s = json.loads(sp.read_text())
        self.assertEqual([h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]], ["echo mine"])
        self.assertNotIn("UserPromptSubmit", s["hooks"])

    def test_install_self_test_starts_no_sweep(self):
        s = "99999999-2222-3333-4444-555555555555"
        junk = mk(self.ctmp / "-p" / s / "tasks" / "old.output", 4096, age_days=5)
        sp = self.home / ".claude" / "settings.json"
        sp.parent.mkdir(parents=True)
        sp.write_text("{}")
        _, out = self.run_cli("install", "--settings", str(sp))
        self.assertIn("self-test", out)
        time.sleep(1.5)                       # a detached sweep would have run by now
        self.assertTrue(junk.exists(), "install must not sweep as a side effect")

    def test_prompt_hook_silent_unless_low(self):
        old, old_f = steward.LOW_FREE_BYTES, steward.LOW_FREE_FRACTION
        steward.LOW_FREE_BYTES, steward.LOW_FREE_FRACTION = 0, 0.0
        try:
            code, out = self.run_cli("hook", "prompt")
        finally:
            steward.LOW_FREE_FRACTION = old_f
        self.assertEqual(out, "", "zero tokens when disk is fine")
        steward.LOW_FREE_BYTES = 1 << 60
        try:
            _, out = self.run_cli("hook", "prompt", session="s1")
            self.assertIn("disk low", out)
            _, again = self.run_cli("hook", "prompt", session="s1")
            self.assertEqual(again, "", "warning throttled per session")
        finally:
            steward.LOW_FREE_BYTES = old



class MultiAgentTests(Sandbox):
    def _seed(self):
        (self.home / ".codex").mkdir()
        (self.home / ".claude").mkdir()
        (self.home / ".cursor").mkdir()
        (self.home / ".cursor/hooks.json").write_text(json.dumps(
            {"version": 1, "hooks": {"stop": [{"command": "notify-me"}]}}))
        (self.home / ".gemini").mkdir()
        (self.home / ".gemini/settings.json").write_text(json.dumps(
            {"theme": "x", "hooks": {"SessionStart": [{"type": "command", "command": "hello"}]}}))

    def test_install_all_agents_merges_and_uninstalls_cleanly(self):
        self._seed()
        for _ in range(2):
            code, out = self.run_cli("install", "--agents", "auto")
        self.assertEqual(code, 0)
        self.assertIn("output format ok", out)
        codex = json.loads((self.home / ".codex/hooks.json").read_text())
        self.assertEqual(sorted(codex["hooks"]), ["Stop", "UserPromptSubmit"])
        self.assertEqual(len(codex["hooks"]["Stop"]), 1, "idempotent")
        cursor = json.loads((self.home / ".cursor/hooks.json").read_text())
        self.assertEqual(cursor["version"], 1)
        self.assertEqual([h["command"] for h in cursor["hooks"]["stop"]][0], "notify-me", "user hook kept")
        self.assertIn("sessionEnd", cursor["hooks"])
        self.assertNotIn("beforeSubmitPrompt", cursor["hooks"], "Cursor prompt hooks can't add context")
        gem = json.loads((self.home / ".gemini/settings.json").read_text())
        self.assertEqual(gem["theme"], "x")
        self.assertIn("BeforeAgent", gem["hooks"])
        self.assertEqual(gem["hooks"]["SessionStart"][0]["command"], "hello")
        # skill visible to every agent from one real copy
        self.assertTrue((self.home / ".agents/skills/storage-steward").is_symlink())
        self.assertTrue((self.home / ".claude/skills/storage-steward/SKILL.md").exists())
        self.run_cli("uninstall")
        self.assertEqual(json.loads((self.home / ".cursor/hooks.json").read_text())["hooks"],
                         {"stop": [{"command": "notify-me"}]})
        self.assertFalse((self.home / ".codex/hooks.json").exists(), "held only our hooks, so removed")
        gem = json.loads((self.home / ".gemini/settings.json").read_text())
        self.assertEqual(list(gem["hooks"]), ["SessionStart"])

    def test_hook_output_matches_each_agent_protocol(self):
        expect = {("codex", "stop"): {}, ("cursor", "stop"): {}, ("cursor", "session-end"): {},
                  ("gemini", "stop"): {}, ("gemini", "prompt"): {}}
        for (agent, ev), want in expect.items():
            _, out = self.run_cli("hook", ev, "--agent", agent, "--self-test")
            self.assertEqual(json.loads(out), want, f"{agent} {ev}")
        _, out = self.run_cli("hook", "stop", "--agent", "claude", "--self-test")
        self.assertEqual(out, "", "Claude stop hook stays silent")
        old = steward.LOW_FREE_BYTES
        steward.LOW_FREE_BYTES = 1 << 60
        try:
            _, out = self.run_cli("hook", "prompt", "--agent", "gemini", "--self-test")
            self.assertIn("disk low", json.loads(out)["hookSpecificOutput"]["additionalContext"])
            _, out = self.run_cli("hook", "prompt", "--agent", "codex", "--self-test")
            self.assertTrue(out.startswith("[storage-steward] disk low"), "Codex takes plain-text context")
        finally:
            steward.LOW_FREE_BYTES = old

    def test_existing_foreign_skill_dir_is_not_replaced(self):
        (self.home / ".claude/skills/storage-steward").mkdir(parents=True)
        (self.home / ".claude/skills/storage-steward/SKILL.md").write_text("---\nname: something-else\n---\n")
        _, out = self.run_cli("install", "--agents", "claude")
        self.assertIn("skipped", out)
        self.assertIn("something-else", (self.home / ".claude/skills/storage-steward/SKILL.md").read_text())

    def test_schedule_dry_run_writes_nothing(self):
        _, out = self.run_cli("schedule", "install", "--dry-run")
        self.assertTrue("StartInterval" in out or "OnUnitActiveSec" in out)
        self.assertFalse((self.home / "Library/LaunchAgents").exists())
        self.assertFalse((self.home / ".config/systemd").exists())


class PolicyTests(Sandbox):
    """config.json lets people decide what goes and what stays; these prove each knob takes effect."""

    def cfg(self, *args):
        return self.run_cli("config", *args)

    def test_tier_off_disables_a_rule(self):
        s = "99999999-2222-3333-4444-555555555555"
        out = mk(self.ctmp / "-p" / s / "tasks" / "old.output", 4096, age_days=3)
        self.cfg("set", "claude-task-output", "--tier", "off")
        self.run_cli("sweep")
        self.assertTrue(out.exists(), "rule switched off: nothing deleted")

    def test_promote_confirm_rule_to_auto(self):
        f = mk(self.home / ".codex/sessions/2026/01/02/r.jsonl", 4096, age_days=50)
        self.run_cli("sweep")
        self.assertTrue(f.exists(), "confirm tier by default")
        self.cfg("set", "codex-sessions", "--tier", "auto", "--idle", "45d")
        self.run_cli("sweep")
        self.assertFalse(f.exists(), "now swept automatically")

    def test_idle_override_changes_threshold(self):
        f = mk(self.home / ".claude/debug/x.txt", 4096, age_days=10)
        self.cfg("set", "claude-debug", "--idle", "14")
        self.run_cli("sweep")
        self.assertTrue(f.exists(), "10 days < 14-day threshold")
        self.cfg("set", "claude-debug", "--idle", "6h")
        self.run_cli("sweep")
        self.assertFalse(f.exists())

    def test_keep_protects_paths_and_globs(self):
        a = self.home / ".npm/_npx/keepme1"
        b = self.home / ".npm/_npx/other22"
        for e in (a, b):
            mk(e / "package.json", 512)
            age_tree(e, 40)
        self.cfg("keep", "~/.npm/_npx/keep*")
        self.run_cli("sweep", "--no-probation")
        self.assertTrue(a.exists(), "kept by glob")
        self.assertFalse(b.exists())
        n = mk(self.home / ".claude/debug/movie.mov", 4096, age_days=30)
        self.cfg("keep", "*.mov")
        self.run_cli("sweep")
        self.assertTrue(n.exists(), "kept by name pattern")

    def test_custom_rule_and_personal_folder_cap(self):
        build = self.home / "work/app/build"
        mk(build / "bundle.js", 8192)
        age_tree(build, 20)
        rec = mk(self.home / "Desktop/Screen Recording 1.mov", 8192, age_days=60)
        self.cfg("add", "work-builds", "--path", "~/work/*/build", "--idle", "7", "--tier", "auto")
        _, out = self.cfg("add", "recordings", "--path", "~/Desktop/Screen Recording*.mov", "--idle", "30", "--tier", "auto")
        self.assertIn("capped to confirm", out)
        self.run_cli("sweep")
        self.assertFalse(build.exists(), "your own auto rule ran")
        self.assertTrue(rec.exists(), "personal folders are never swept automatically")
        self.run_cli("sweep", "--tier", "confirm", "--only", "recordings", "--yes")
        self.assertFalse(rec.exists(), "removed once you said yes")

    def test_broad_or_outside_patterns_refused(self):
        for bad in ("~/*", "/etc/*", "relative/*"):
            with self.assertRaises(SystemExit):
                self.cfg("add", "nope", "--path", bad, "--tier", "auto")
        self.assertFalse((self.home / ".config/storage-steward/config.json").exists())

    def test_broken_config_never_breaks_hooks(self):
        p = self.home / ".config/storage-steward/config.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json")
        code, out = self.run_cli("hook", "prompt")
        self.assertEqual((code, out), (0, ""))
        _, out = self.run_cli("scan")
        self.assertIn("config problem", out)

    def test_rules_listing_shows_changes(self):
        self.cfg("set", "claude-transcripts", "--tier", "off")
        _, out = self.run_cli("rules")
        self.assertIn("OFF", out)
        self.assertIn("*claude-transcripts", out)


# ---------------------------------------------------------------- v0.2 safety regressions
# Each test below reproduces a defect found in review, where a sweep could delete something the docs
# promise is protected. They must fail on v0.1.x-era guards and pass now.

def case_insensitive(path: Path) -> bool:
    probe = path / "CaseProbe"
    probe.write_text("x")
    try:
        return (path / "caseprobe").exists()
    finally:
        probe.unlink()


GIT_ISOLATED = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "maintenance.auto=false", "-c", "gc.auto=0",
                "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "-c", "init.defaultBranch=main"]


def git(d: Path, *args):
    subprocess.run(["git", "-C", str(d), *GIT_ISOLATED, *args], check=True, capture_output=True)


def repo(d: Path) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", *GIT_ISOLATED, "init", "-q", str(d)], check=True)
    mk(d / "a.txt")
    git(d, "add", ".")
    git(d, "commit", "-qm", "x")
    return d


def worktree(main: Path, path: Path, detach: bool = False) -> Path:
    """A linked worktree, the way agents make them: its branch lives on in the main repo."""
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"wt-{path.parent.name}-{path.name}"
    git(main, "worktree", "add", "-q", *(["--detach"] if detach else ["-b", branch]), str(path))
    return path


def npx_entry(home: Path, name: str) -> Path:
    e = home / ".npm/_npx" / name
    mk(e / "package.json", 512)
    age_tree(e, 40)
    return e


class SafetySandbox(Sandbox):
    def cfg(self, *args):
        return self.run_cli("config", *args)

    def write_config(self, data):
        p = self.home / ".config/storage-steward/config.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data if isinstance(data, str) else json.dumps(data))
        return p


class PathGuardTests(SafetySandbox):
    def test_case_variant_paths_cannot_auto_sweep_documents(self):
        if not case_insensitive(self.home):
            self.skipTest("case-sensitive file system")
        thesis = mk(self.home / "Documents/thesis.docx", age_days=60)
        notes = mk(self.home / "Documents/old/notes.txt", age_days=60)
        age_tree(self.home / "Documents", 60)
        _, out = self.cfg("add", "docs", "--path", "~/documents/*", "--tier", "auto")
        self.assertIn("capped to confirm", out)
        self.write_config({"custom": [
            {"name": "whole", "paths": ["~/documents"], "tier": "auto", "idle_days": 1},
            {"name": "inside", "paths": ["~/DOCUMENTS/*"], "tier": "auto", "idle_days": 1}]})
        self.run_cli("sweep")
        self.assertTrue(thesis.exists() and notes.exists(), "~/documents is ~/Documents on APFS")
        c = self.ctx()
        self.assertFalse(c.allowed(Item(str(self.home / "documents"), 0, str(self.home)), "confirm"))

    def test_dotdot_cannot_escape_home_or_reach_desktop(self):
        (self.home / "Library").mkdir()
        outside = mk(self.home.parent / "outside" / "a" / "f.bin", age_days=60)
        age_tree(self.home.parent / "outside", 60)
        rec = mk(self.home / "Desktop/clip.mov", age_days=60)
        for bad in ("~/Library/../../outside/*", "~/Library/../Desktop/*.mov"):
            with self.assertRaises(SystemExit):
                self.cfg("add", "esc", "--path", bad, "--tier", "auto")
        self.write_config({"custom": [
            {"name": "esc1", "paths": ["~/Library/../../outside/*"], "tier": "auto", "idle_days": 1},
            {"name": "esc2", "paths": ["~/Library/../Desktop/*.mov"], "tier": "auto", "idle_days": 1}]})
        self.run_cli("sweep")
        self.assertTrue(outside.exists(), "custom rules stay inside home")
        self.assertTrue(rec.exists(), "and out of personal folders")
        _, out = self.run_cli("scan")
        self.assertIn("config problem", out)

    def test_tier_override_cannot_lift_the_personal_folder_cap(self):
        rec = mk(self.home / "Desktop/Screen Recording 1.mov", 8192, age_days=60)
        self.cfg("add", "recs", "--path", "~/Desktop/Screen Recording*.mov", "--tier", "off")
        self.cfg("set", "recs", "--tier", "auto")
        self.run_cli("sweep")
        self.assertTrue(rec.exists())
        _, out = self.run_cli("rules", "--json")
        tier = next(r["tier"] for r in json.loads(out) if r.get("rule") == "recs")
        self.assertEqual(tier, "confirm")

    def test_auto_sweeps_never_reach_personal_folders(self):
        def project(d):
            mk(d / "package.json")
            mk(d / "node_modules/x/index.js", 8192)
            age_tree(d, 60)
            return d / "node_modules"
        in_docs, in_code = project(self.home / "Documents/proj"), project(self.home / "code/proj")
        self.cfg("set", "stale-project-deps", "--tier", "auto")
        self.run_cli("sweep")
        self.assertTrue(in_docs.exists(), "auto never deletes inside Documents, whatever the rule")
        self.assertFalse(in_code.exists())


class KeepTests(SafetySandbox):
    def test_name_glob_protects_folder_contents(self):
        a, b, c = (self.home / f"work/{n}/build" for n in "abc")
        mk(a / "demo-recording.mov", age_days=30)
        mk(c / "CLIP.MOV", age_days=30)
        for d in (a, b, c):
            mk(d / "bundle.js", age_days=30)
            age_tree(d, 30)
        self.cfg("keep", "~/models", "*.mov")
        self.cfg("add", "work-builds", "--path", "~/work/*/build", "--idle", "7", "--tier", "auto")
        self.run_cli("sweep")
        self.assertTrue((a / "demo-recording.mov").exists(), "README example: keep *.mov beats the rule")
        self.assertTrue((c / "CLIP.MOV").exists(), "name patterns ignore case")
        self.assertFalse(b.exists())

    def test_keep_entries_are_normalized(self):
        entries = {"t1": "~/.npm/_npx/t1/", "t2": "~//.npm/_npx/t2", "t3": "~/.npm/../.npm/_npx/t3",
                   "t4": "$HOME/.npm/_npx/t4", "t5": str(self.home) + "/.npm/_npx/t5", "t6": "~/.npm/_npx/t6*/",
                   "t7": ".npm/_npx/t7"}
        if case_insensitive(self.home):
            entries["t8"] = "~/.NPM/_npx/t8"
        for name in list(entries) + ["loose"]:
            npx_entry(self.home, name)
        self.write_config({"keep": list(entries.values())})
        self.run_cli("sweep", "--no-probation")
        for name in entries:
            self.assertTrue((self.home / ".npm/_npx" / name).exists(), f"{entries[name]} protects {name}")
        self.assertFalse((self.home / ".npm/_npx/loose").exists())

    def test_keep_as_a_string_still_protects_and_is_reported(self):
        e = npx_entry(self.home, "k1")
        self.write_config({"keep": "~/.npm/_npx/k1"})
        self.run_cli("sweep", "--no-probation")
        self.assertTrue(e.exists())
        _, out = self.run_cli("scan")
        self.assertIn("config problem", out)

    def test_broken_config_pauses_deletes(self):
        e = npx_entry(self.home, "k1")
        log = mk(self.home / ".claude/debug/old.txt", age_days=30)
        self.write_config('{"keep": ["~/.npm/_npx/k1"],}')        # trailing comma: invalid JSON
        code, out = self.run_cli("sweep", "--no-probation")
        self.assertEqual(code, 0)
        self.assertIn("paused", out)
        self.run_cli("hook", "stop", "--foreground")
        self.assertTrue(e.exists(), "the keep list can't be read, so nothing is deleted")
        self.assertTrue(log.exists())
        _, out = self.run_cli("scan")
        self.assertIn("paused", out)

    def test_malformed_types_never_crash_and_config_stays_repairable(self):
        self.write_config({"rules": [], "keep": [5],
                           "custom": [{"name": "wk", "paths": ["~/w/*"], "idle_days": "soon"}]})
        for args in (("hook", "prompt"), ("scan",), ("rules",), ("config", "show"), ("sweep",)):
            code, _ = self.run_cli(*args)
            self.assertEqual(code, 0, args)
        _, out = self.run_cli("scan")
        self.assertIn("paused", out, "rules/keep of the wrong shape: intent unknown, so nothing is deleted")
        code, out = self.cfg("drop", "wk")
        self.assertEqual(code, 0)
        self.assertIn("dropped", out)

    def test_invalid_override_turns_the_rule_off(self):
        f = mk(self.home / ".claude/debug/x.txt", age_days=30)
        g = mk(self.home / ".claude/shell-snapshots/s.sh", age_days=30)
        self.write_config({"rules": {"claude-debug": {"tier": "of"},
                                     "claude-shell-snapshots": {"idle_days": "soon"}}})
        self.run_cli("sweep")
        self.assertTrue(f.exists() and g.exists(), "a typo must not fall back to deleting")
        _, out = self.run_cli("scan")
        self.assertIn("config problem", out)

    def test_thresholds_must_be_finite_and_positive(self):
        for v in ("nan", "inf", "0", "-5", "-1h", "soon"):
            with self.assertRaises(SystemExit, msg=v):
                self.cfg("set", "claude-debug", "--idle", v)
            with self.assertRaises(SystemExit, msg=v):
                self.cfg("add", "wk", "--path", "~/w/*", "--idle", v)
        f = mk(self.home / "w/x/a.txt", age_days=2)
        self.write_config('{"custom": [{"name": "wk", "paths": ["~/w/*"], "tier": "auto", "idle_days": NaN}]}')
        self.run_cli("sweep")
        self.assertTrue(f.exists())


class RuleSafetyTests(SafetySandbox):
    def test_nested_worktree_layout_is_checked(self):
        main = repo(self.home / "code/main")
        base = self.home / ".codex/worktrees"
        dirty = worktree(main, base / "abc1/app")
        (dirty / "a.txt").write_text("changed")
        worktree(main, base / "abc2/app")
        mk(base / "abc3/notes.txt")
        for d in ("abc1", "abc2", "abc3"):
            age_tree(base / d, 30)
        self.run_cli("sweep", "--tier", "confirm", "--only", "agent-worktrees", "--yes")
        self.assertTrue((base / "abc1").exists(), "uncommitted work one level down")
        self.assertFalse((base / "abc2").exists(), "clean nested worktree removed")
        self.assertTrue((base / "abc3").exists(), "no git checkout: can't prove it's clean")

    def test_detached_commits_and_ignored_secrets_keep_a_worktree(self):
        main = repo(self.home / "code/main")
        (main / ".gitignore").write_text(".env\nnode_modules/\n")
        git(main, "add", ".")
        git(main, "commit", "-qm", "ignore")
        base = self.home / ".claude/worktrees"
        det = worktree(main, base / "det", detach=True)
        mk(det / "b.txt")
        git(det, "add", ".")
        git(det, "commit", "-qm", "only here")
        sec = worktree(main, base / "sec")
        mk(sec / ".env")
        deps = worktree(main, base / "deps")
        mk(deps / "node_modules/x/index.js")
        for d in (det, sec, deps):
            age_tree(d, 30)
        self.run_cli("sweep", "--tier", "confirm", "--only", "agent-worktrees", "--yes")
        self.assertTrue(det.exists(), "commits on no branch would be lost")
        self.assertTrue(sec.exists(), "an ignored .env is user data")
        self.assertFalse(deps.exists(), "ignored node_modules is regenerable")

    def test_standalone_repos_keep_unpushed_work(self):
        origin = repo(self.home / "code/origin")
        base = self.home / ".claude/worktrees"
        local = repo(base / "local")                     # commits that exist nowhere else
        stashed = base / "stashed"
        subprocess.run(["git", *GIT_ISOLATED, "clone", "-q", str(origin), str(stashed)], check=True)
        (stashed / "a.txt").write_text("wip")
        git(stashed, "stash", "-q")
        pushed = base / "pushed"
        subprocess.run(["git", *GIT_ISOLATED, "clone", "-q", str(origin), str(pushed)], check=True)
        for d in (local, stashed, pushed):
            age_tree(d, 30)
        self.run_cli("sweep", "--tier", "confirm", "--only", "agent-worktrees", "--yes")
        self.assertTrue(local.exists(), "a repo's own branches go with it")
        self.assertTrue(stashed.exists(), "so do its stashes")
        self.assertFalse(pushed.exists(), "everything is on the remote: safe")

    def test_stale_deps_need_a_provably_idle_project(self):
        sub = self.home / "code/sub"
        sub.mkdir(parents=True)
        (sub / ".git").write_text("gitdir: /nonexistent/x\n")
        mk(sub / ".venv/bin/python", 1024)
        age_tree(sub, 60)
        busy = self.home / "code/busy"
        mk(busy / "package.json")
        mk(busy / "node_modules/x/index.js", 8192)
        age_tree(busy, 60)
        mk(busy / "src/app.js", age_days=1)
        self.run_cli("sweep", "--tier", "confirm", "--only", "stale-project-deps", "--yes")
        self.assertTrue((sub / ".venv").exists(), "activity unknown => treated as active")
        self.assertTrue((busy / "node_modules").exists(), "source edited yesterday => active")

    def test_scan_paths_names_what_confirm_would_delete(self):
        p = self.home / "Documents/oldproj"
        mk(p / "package.json")
        mk(p / "node_modules/x/index.js", 2 << 20)
        age_tree(p, 60)
        _, out = self.run_cli("scan", "--only", "stale-project-deps", "--paths")
        self.assertIn("~/Documents/oldproj/node_modules", out)

    def test_user_tmp_keeps_socket_dirs(self):
        import socket
        named = self.utmp / "tmux-501"                  # skipped by name even without a socket
        mk(named / "default.lock")
        age_tree(named, 30)
        d = self.utmp / "srv"
        d.mkdir()
        cwd = os.getcwd()
        os.chdir(d)
        try:
            s = socket.socket(socket.AF_UNIX)
            s.bind("default")
        finally:
            os.chdir(cwd)
        self.addCleanup(s.close)
        age_tree(d, 30)
        junk = self.utmp / "junk"
        mk(junk / "x.bin")
        age_tree(junk, 30)
        self.run_cli("sweep")
        self.assertTrue(d.exists(), "a live server's socket dir looks idle but isn't")
        self.assertTrue(named.exists())
        self.assertFalse(junk.exists())

    def test_user_tmp_root_containing_home_is_refused(self):
        proj = mk(self.home / "projects/app/main.py", age_days=30)
        age_tree(self.home / "projects", 30)
        for root in (self.home, self.home.parent):
            with redirect_stdout(io.StringIO()):
                steward.main(["--home", str(self.home), "--tmp", str(self.tmp), "--user-tmp", str(root),
                              "--now", str(NOW), "sweep"])
            self.assertTrue(proj.exists(), f"TMPDIR={root} must not sweep home")

    def test_sandbox_with_unreadable_outputs_is_kept(self):
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        sb = self.home / "Library/Application Support/Claude/local-agent-mode-sessions/a/o/local_x"
        mk(sb / "outputs/report.pdf")
        age_tree(sb, 30)
        os.chmod(sb / "outputs", 0)
        try:
            _, out = self.run_cli("scan", "--only", "desktop-sandboxes-empty", "--paths")
            self.assertNotIn("local_x", out, "not a candidate at all")
            self.run_cli("sweep", "--tier", "confirm", "--only", "desktop-sandboxes-empty", "--yes")
        finally:
            os.chmod(sb / "outputs", 0o755) if os.path.lexists(sb / "outputs") else None
        self.assertTrue((sb / "outputs/report.pdf").exists(), "can't see inside outputs/, so it isn't empty")

    def test_recently_restored_files_survive_the_race_check(self):
        f = mk(self.home / ".claude/debug/restored.txt", age_days=30)   # old mtime, ctime is now
        c = self.ctx()
        c.use_ctime = True
        item = Item(str(f), 0, str(self.home / ".claude/debug"))
        self.assertEqual(steward.remove(c, item), 0)
        self.assertTrue(f.exists(), "extracted/restored minutes ago")
        c.use_ctime = False
        steward.remove(c, item)
        self.assertFalse(f.exists())


class ReviewRegressionTests(SafetySandbox):
    """Second review pass: protected trees, aliases, unicode, unreadable config, and other escapes."""

    def test_credentials_and_agent_config_are_protected_whole(self):
        key = mk(self.home / ".ssh/old_id_rsa", age_days=400)
        md = mk(self.home / ".claude/CLAUDE.md", age_days=400)
        agent = mk(self.home / ".claude/agents/reviewer.md", age_days=400)
        os.symlink(self.home / ".ssh", self.home / "keys")          # an alias, so this holds on Linux too
        self.write_config({"custom": [
            {"name": "old-keys", "paths": ["~/.ssh/old_*"], "tier": "auto", "idle_days": 1},
            {"name": "alias", "paths": ["~/keys/*"], "tier": "auto", "idle_days": 1},
            {"name": "claude-all", "paths": ["~/.claude/*"], "tier": "auto", "idle_days": 1}]})
        self.run_cli("sweep")
        self.assertTrue(key.exists() and md.exists() and agent.exists())

    def test_keep_matches_unicode_and_case_variants(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "café-clip.mov")
        clip = mk(self.home / "w/one" / nfd, age_days=30)
        client = mk(self.home / "w/Client-A/report.txt", age_days=30)
        other = mk(self.home / "w/other/x.txt", age_days=30)
        age_tree(self.home / "w", 30)
        self.write_config({"keep": ["*café*.mov", "~/w/client-*"],
                           "custom": [{"name": "wk", "paths": ["~/w/*"], "tier": "auto", "idle_days": 7}]})
        self.run_cli("sweep")
        self.assertTrue(clip.exists(), "NFC pattern, NFD name")
        self.assertTrue(client.exists(), "glob literal case")
        self.assertFalse(other.exists())

    def test_name_pattern_protects_inside_a_matching_folder(self):
        band = mk(self.home / "w/backup.sparsebundle/bands/0", age_days=30)
        age_tree(self.home / "w", 30)
        self.write_config({"keep": ["*.sparsebundle"],
                           "custom": [{"name": "wk", "paths": ["~/w/*/*"], "tier": "auto", "idle_days": 7}]})
        self.run_cli("sweep")
        self.assertTrue(band.exists())

    def test_keep_through_an_alias_protects_the_parent(self):
        keepme = mk(self.home / "w/a/keepme.txt", age_days=30)
        mk(self.home / "w/b/x.txt", age_days=30)
        age_tree(self.home / "w", 30)
        os.symlink(self.home / "w", self.home / "alias")
        self.write_config({"keep": ["~/alias/a/keepme.txt"],
                           "custom": [{"name": "wk", "paths": ["~/w/*"], "tier": "auto", "idle_days": 7}]})
        self.run_cli("sweep")
        self.assertTrue(keepme.exists(), "~/w/a holds a kept file, under another spelling")
        self.assertFalse((self.home / "w/b").exists())

    def test_protect_flag_matches_by_identity(self):
        e = npx_entry(self.home, "foo")
        os.symlink(self.home / ".npm/_npx", self.home / "npx-alias")
        with redirect_stdout(io.StringIO()):
            steward.main(["--home", str(self.home), "--tmp", str(self.tmp), "--user-tmp", str(self.utmp),
                          "--now", str(NOW), "--protect", str(self.home / "npx-alias/foo"), "sweep", "--no-probation"])
        self.assertTrue(e.exists())

    def test_unreadable_keep_entries_pause_without_crashing(self):
        e = npx_entry(self.home, "k1")
        for bad in ("~/a\u0000b", "~/x/[z-a]"):
            self.write_config('{"keep": ["~/.npm/_npx/k1", "' + bad + '"]}')
            for args in (("hook", "prompt"), ("scan",), ("config", "show"), ("sweep", "--no-probation")):
                code, _ = self.run_cli(*args)
                self.assertEqual(code, 0, (bad, args))
            self.assertTrue(e.exists())

    def test_unreadable_config_pauses_deletes(self):
        if os.geteuid() == 0:
            self.skipTest("root reads everything")
        e = npx_entry(self.home, "k1")
        cfg = self.write_config({"keep": ["~/.npm/_npx/k1"]})
        os.chmod(cfg.parent, 0)
        try:
            self.run_cli("sweep", "--no-probation")
            _, out = self.run_cli("scan")
        finally:
            os.chmod(cfg.parent, 0o755)
        self.assertTrue(e.exists(), "a keep list we can't read can't protect anything: pause")
        self.assertIn("paused", out)

    def test_custom_rule_stays_home_when_its_folder_becomes_a_symlink(self):
        mk(self.home / "w/a.txt", age_days=30)
        self.cfg("add", "wk", "--path", "~/w/*", "--tier", "auto", "--idle", "7")
        outside = mk(self.home.parent / "elsewhere/data.bin", age_days=30)
        (self.home / "w/a.txt").unlink()
        (self.home / "w").rmdir()
        os.symlink(self.home.parent / "elsewhere", self.home / "w")
        self.run_cli("sweep")
        self.assertTrue(outside.exists())

    def test_recent_install_keeps_deps_of_an_idle_project(self):
        proj = self.home / "code/p"
        mk(proj / "package.json")
        mk(proj / "src/app.js")
        age_tree(proj, 60)
        mk(proj / "node_modules/x/index.js", age_days=1)
        os.utime(proj / "node_modules", (NOW - 60 * DAY,) * 2)
        os.utime(proj / "node_modules/x", (NOW - 60 * DAY,) * 2)
        self.run_cli("sweep", "--tier", "confirm", "--only", "stale-project-deps", "--yes")
        self.assertTrue((proj / "node_modules").exists(), "installed yesterday")

    def test_paused_policy_stops_sweep_itself(self):
        f = mk(self.home / ".claude/debug/x.txt", age_days=30)
        self.write_config("{oops")
        self.assertEqual(steward.sweep(self.ctx(), ("auto",)), (0, {}))
        self.assertTrue(f.exists())

    def test_odd_state_files_and_paths_are_handled(self):
        (self.home / ".cache/storage-steward").mkdir(parents=True)
        (self.home / ".cache/storage-steward/armed.json").write_text("[]")
        f = mk(self.home / ".claude/debug/a\nb.txt", age_days=30)
        code, _ = self.run_cli("sweep")
        self.assertEqual(code, 0)
        self.assertFalse(f.exists())
        log = (self.home / ".cache/storage-steward/removed.log").read_text()
        self.assertIn("a\\nb.txt", log)
        self.assertFalse(any(line.startswith("b.txt") for line in log.splitlines()), "no forged lines")


class HookRobustnessTests(SafetySandbox):
    def hook(self, stdin, *args):
        argv = ["--home", str(self.home), "--tmp", str(self.tmp), "--user-tmp", str(self.utmp), "--now", str(NOW)]
        buf, old = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO(stdin)
        try:
            with redirect_stdout(buf):
                code = steward.main(argv + ["hook", *args])
        finally:
            sys.stdin = old
        return code, buf.getvalue()

    def test_odd_stdin_never_crashes_a_hook(self):
        for raw in ("[]", "null", '{"cwd": 5}', '{"session_id": 7, "workspace_roots": "x"}', "\x00junk"):
            code, _ = self.hook(raw, "prompt")
            self.assertEqual(code, 0, raw)
            code, out = self.hook(raw, "stop", "--agent", "codex", "--self-test")
            self.assertEqual((code, json.loads(out)), (0, {}), raw)

    def test_low_disk_warning_survives_an_unwritable_state_dir(self):
        self.write_config({"warn_below_gb": 10000})
        (self.home / ".cache").mkdir()
        (self.home / ".cache/storage-steward").write_text("a file where the state dir should be")
        code, out = self.hook("{}", "prompt")
        self.assertEqual(code, 0)
        self.assertIn("disk low", out)
        f = mk(self.home / ".claude/debug/x.txt", age_days=30)
        code, _ = self.run_cli("sweep")
        self.assertEqual(code, 0)
        self.assertFalse(f.exists(), "sweeping still works without state")


class CliTests(SafetySandbox):
    def test_every_removed_path_is_logged(self):
        f = mk(self.home / ".claude/debug/old-log.txt", 4096, age_days=30)
        self.run_cli("sweep")
        self.assertFalse(f.exists())
        log = (self.home / ".cache/storage-steward/removed.log").read_text()
        self.assertIn(f"claude-debug\t", log)
        self.assertIn(str(f), log)
        _, out = self.run_cli("report")
        self.assertIn("removed.log", out)

    def test_confirm_sweep_needs_named_rules(self):
        f = mk(self.home / ".codex/sessions/2026/01/01/r.jsonl", 4096, age_days=90)
        code, out = self.run_cli("sweep", "--tier", "confirm", "--yes")
        self.assertEqual(code, 2)
        self.assertIn("--only", out)
        self.assertTrue(f.exists())

    def test_version_is_consistent(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit):
            steward.main(["--version"])
        self.assertEqual(buf.getvalue().strip(), f"storage-steward {steward.__version__}")
        root = SCRIPTS.parents[1]
        skill = (SCRIPTS.parent / "SKILL.md").read_text()
        self.assertIn(f'version: "{steward.__version__}"', skill.split("---")[1], "SKILL.md metadata")
        self.assertIn(f"## [{steward.__version__}]", (root / "CHANGELOG.md").read_text())


if __name__ == "__main__":
    unittest.main()
