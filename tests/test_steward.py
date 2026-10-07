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
        def wt(name, dirty):
            d = self.home / ".codex/worktrees" / name
            d.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(d)], check=True)
            mk(d / "a.txt")
            subprocess.run(["git", "-C", str(d), "add", "."], check=True)
            subprocess.run(["git", "-C", str(d), "-c", "user.email=t@t", "-c", "user.name=t",
                            "commit", "-qm", "x"], check=True)
            if dirty:
                (d / "a.txt").write_text("changed")
            age_tree(d, 30)
            return d
        clean, dirty = wt("clean", False), wt("dirty", True)
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


if __name__ == "__main__":
    unittest.main()
