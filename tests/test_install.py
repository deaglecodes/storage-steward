"""Installer tests: config edits, uninstall, retention and the OS scheduler.

Run: python3 -m unittest discover tests -v. Every test runs against a sandbox --home; a guard fails the
test if anything would reach launchctl, systemctl or crontab.
"""
import io
import json
import os
import plistlib
import shlex
import shutil
import stat
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_steward import SCRIPTS, Sandbox  # noqa: E402

import agents  # noqa: E402  (test_steward put the scripts dir on sys.path)

SKILL_SRC = SCRIPTS.parent
LINKS = (".claude/skills", ".cursor/skills", ".gemini/skills", ".copilot/skills", ".agents/skills")
RETENTION_LINE = "Claude Code cleanupPeriodDays -> 21 (Claude Code deletes transcripts older than this)"


def _no_scheduler(*args, **kwargs):
    raise AssertionError(f"a sandbox run reached the real OS scheduler: {args}")


class InstallSandbox(Sandbox):
    def setUp(self):
        super().setUp()
        for target, value in (("_run", mock.Mock(side_effect=_no_scheduler)),
                              ("subprocess", mock.Mock(run=_no_scheduler))):
            patcher = mock.patch.object(agents, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def settings(self, data=None, rel=".claude/settings.json") -> Path:
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if data is not None:
            p.write_text(json.dumps(data))
        return p

    def seed_all(self):
        for d in (".claude", ".codex", ".cursor", ".gemini", ".copilot", ".config/opencode"):
            (self.home / d).mkdir(parents=True, exist_ok=True)
        self.settings({"version": 1, "hooks": {"stop": [{"command": "notify-me"}]}}, ".cursor/hooks.json")

    def copy_skill(self, dest: Path):
        dest.mkdir(parents=True)
        shutil.copy2(SKILL_SRC / "SKILL.md", dest / "SKILL.md")
        for d in ("scripts", "references"):
            shutil.copytree(SKILL_SRC / d, dest / d, ignore=shutil.ignore_patterns("__pycache__"))


class ConfigWriteTests(InstallSandbox):
    def test_file_mode_is_kept(self):
        sp = self.settings({"model": "x"})
        os.chmod(sp, 0o600)
        self.run_cli("install", "--agents", "claude")
        self.assertIn("hooks", json.loads(sp.read_text()))
        self.assertEqual(stat.S_IMODE(sp.stat().st_mode), 0o600)
        self.run_cli("uninstall")
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"})
        self.assertEqual(stat.S_IMODE(sp.stat().st_mode), 0o600)

    def test_symlinked_config_is_written_through(self):
        real = self.settings({"theme": "x"}, "dotfiles/gemini.json")
        link = self.home / ".gemini/settings.json"
        link.parent.mkdir()
        os.symlink(real, link)
        self.run_cli("install", "--agents", "gemini")
        self.assertTrue(link.is_symlink(), "the symlink stays a symlink")
        self.assertIn("BeforeAgent", json.loads(real.read_text())["hooks"])
        self.run_cli("uninstall")
        self.assertTrue(link.is_symlink())
        self.assertEqual(json.loads(real.read_text()), {"theme": "x"})
        self.assertEqual(os.listdir(real.parent), ["gemini.json"], "no temp or backup files in the dotfiles dir")

    def test_file_without_our_hooks_is_never_rewritten(self):
        raw = '{"theme":"x","hooks":{"SessionStart":[{"type":"command","command":"hello"}],"Stop":[]}}'
        p = self.settings(None, ".gemini/settings.json")
        p.write_text(raw)
        os.utime(p, (1_000_000, 1_000_000))
        self.run_cli("uninstall")
        self.assertEqual(p.read_text(), raw, "same bytes, same formatting")
        self.assertEqual(p.stat().st_mtime, 1_000_000)
        self.assertEqual(list(p.parent.glob("settings.json.bak-*")), [], "no backup either")

    def test_reinstall_without_changes_writes_nothing(self):
        (self.home / ".codex").mkdir()
        self.run_cli("install", "--agents", "codex")
        p = self.home / ".codex/hooks.json"
        os.utime(p, (1_000_000, 1_000_000))
        _, out = self.run_cli("install", "--agents", "codex")
        self.assertEqual(p.stat().st_mtime, 1_000_000)
        self.assertEqual(list(p.parent.glob("hooks.json.bak-*")), [])
        self.assertIn("unchanged", out)

    def test_backups_capped_at_two_per_file(self):
        sp = self.settings({"model": "x"})
        for t in (100, 200, 300):
            (sp.parent / f"settings.json.bak-{t}").write_text("{}")
        mine = [sp.parent / "settings.json.bak-manual", sp.parent / "other.json.bak-100"]
        for p in mine:
            p.write_text("mine")
        self.run_cli("install", "--agents", "claude")
        self.run_cli("uninstall")
        ours = [p.name for p in agents.backups(sp)]
        self.assertEqual(len(ours), 2, ours)
        self.assertNotIn("settings.json.bak-300", ours, "oldest pruned")
        self.assertTrue(all(p.exists() for p in mine), "other files are never pruned")

    def test_newest_backup_survives_a_clock_that_went_backwards(self):
        sp = self.settings({"model": "x"})
        (sp.parent / "settings.json.bak-9999999999").write_text("from the future")
        self.run_cli("install", "--agents", "claude")
        self.assertEqual(json.loads(agents.backups(sp)[-1].read_text()), {"model": "x"})


class MalformedConfigTests(InstallSandbox):
    def test_bad_json_skips_that_agent_and_finishes_the_rest(self):
        (self.home / ".codex").mkdir()
        cur = self.settings(None, ".cursor/hooks.json")
        raw = '// my hooks\n{"version": 1, "hooks": {}}\n'
        cur.write_text(raw)
        code, out = self.run_cli("install", "--agents", "auto")
        self.assertEqual(code, 1)
        self.assertIn(f"Cursor: skipped: {cur} is not valid JSON; fix it and re-run", out)
        self.assertIn("Stop", json.loads((self.home / ".codex/hooks.json").read_text())["hooks"])
        self.assertEqual(cur.read_text(), raw)
        with mock.patch.object(agents, "PLATFORM", "darwin", create=True):
            self.run_cli("schedule", "install")
            code, out = self.run_cli("uninstall")
        self.assertEqual(code, 1)
        self.assertIn("Cursor: skipped:", out)
        self.assertFalse((self.home / ".codex/hooks.json").exists(), "other agents still uninstalled")
        self.assertEqual(list((self.home / "Library/LaunchAgents").glob("*.plist")), [], "timer still removed")
        self.assertEqual(cur.read_text(), raw)

    @unittest.skipIf(os.geteuid() == 0, "root ignores directory permissions")
    def test_unwritable_config_dir_skips_that_agent(self):
        (self.home / ".claude").mkdir()
        codex = self.settings({"model": "x"}, ".codex/hooks.json")
        os.chmod(codex.parent, 0o500)
        try:
            code, out = self.run_cli("install", "--agents", "auto")
        finally:
            os.chmod(codex.parent, 0o700)
        self.assertEqual(code, 1)
        self.assertIn(f"Codex: skipped: {codex} could not be written", out)
        self.assertIn("hooks", json.loads((self.home / ".claude/settings.json").read_text()))


class HookCommandTests(InstallSandbox):
    def test_command_survives_any_path(self):
        script = Path("/Users/o'neil/my skills/steward.py")
        cmd = agents.command(script, "stop", "claude")
        self.assertEqual(shlex.split(cmd), ["python3", str(script), "hook", "stop", "--agent", "claude"])
        self.assertTrue(agents._ours({"command": cmd}))
        self.assertTrue(agents._ours({"command": agents.command(Path("/a/steward.py"), "prompt", "codex")}))
        self.assertTrue(agents._ours({"command": "python3 '/x/steward.py' hook session-end"}), "0.1 format")
        self.assertFalse(agents._ours({"command": "python3 /x/steward.py scan"}))
        self.assertFalse(agents._ours({"command": "echo steward.py hooks"}))
        self.assertFalse(agents._ours({"command": "python3 /x/my-steward.py hook stop"}), "someone else's script")

    def test_non_list_hook_event_skips_that_agent(self):
        (self.home / ".claude").mkdir()
        codex = self.settings({"hooks": {"Stop": {"oops": 1}}}, ".codex/hooks.json")
        code, out = self.run_cli("install", "--agents", "auto")
        self.assertEqual(code, 1)
        self.assertIn(f"Codex: skipped: {codex}", out)
        self.assertIn("hooks", json.loads((self.home / ".claude/settings.json").read_text()))

    def test_old_format_hook_is_upgraded_in_place_then_removed(self):
        old = "python3 '/old place/storage-steward/scripts/steward.py' hook stop --agent claude"
        sp = self.settings({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": old}]},
                                               {"hooks": [{"type": "command", "command": "echo mine"}]}]}})
        self.run_cli("install", "--agents", "claude")
        stops = [h["command"] for g in json.loads(sp.read_text())["hooks"]["Stop"] for h in g["hooks"]]
        ours = [c for c in stops if "steward.py" in c]
        self.assertEqual(len(ours), 1, "no duplicate")
        self.assertNotIn("/old place/", ours[0])
        self.assertIn("echo mine", stops)
        self.run_cli("uninstall")
        s = json.loads(sp.read_text())
        self.assertEqual([h["command"] for g in s["hooks"]["Stop"] for h in g["hooks"]], ["echo mine"])


class SchedulerTests(InstallSandbox):
    UNITS = {"darwin": "Library/LaunchAgents/dev.storage-steward.sweep.plist",
             "linux": ".config/systemd/user/storage-steward.timer"}

    def test_sandbox_only_writes_and_removes_files(self):
        for plat, unit in self.UNITS.items():
            with self.subTest(plat), mock.patch.object(agents, "PLATFORM", plat, create=True):
                _, out = self.run_cli("schedule", "install")
                self.assertIn("(sandbox: not loaded)", out)
                self.assertTrue((self.home / unit).exists())
                _, out = self.run_cli("schedule", "uninstall")
                self.assertIn("(sandbox: not loaded)", out)
                self.assertFalse((self.home / unit).exists())
                self.run_cli("install", "--agents", "claude", "--schedule")
                self.assertTrue((self.home / unit).exists())
                self.run_cli("uninstall")
                self.assertFalse((self.home / unit).exists())

    def test_multi_agent_install_and_uninstall_stay_in_the_sandbox(self):
        # the flow of test_steward.MultiAgentTests.test_install_all_agents_merges_and_uninstalls_cleanly,
        # with the guard from setUp failing the test on any launchctl/systemctl/crontab call
        self.seed_all()
        for _ in range(2):
            code, _ = self.run_cli("install", "--agents", "auto")
            self.assertEqual(code, 0)
        code, _ = self.run_cli("uninstall")
        self.assertEqual(code, 0)
        agents._run.assert_not_called()

    def _recorder(self, crontab="", readable=True):
        calls = []

        def run(cmd, stdin=None):
            calls.append((cmd, stdin))
            if cmd[:2] == ["crontab", "-l"]:
                return (True, crontab) if readable else (False, "crontab: permission denied")
            return True, ""
        return calls, run

    def test_real_home_cron_never_rewrites_a_crontab_it_could_not_read(self):
        script = SCRIPTS / "steward.py"
        calls, run = self._recorder(readable=False)
        with mock.patch.object(agents, "_run", side_effect=run), \
                mock.patch.object(agents, "PLATFORM", "linux", create=True), \
                mock.patch("agents.shutil.which", lambda name: "/usr/bin/crontab" if name == "crontab" else None):
            msg = agents.schedule(self.home, script, "install", real_home=True)
            agents.schedule(self.home, script, "uninstall", real_home=True)
        self.assertIn("could not read", msg)
        self.assertNotIn(["crontab", "-"], [c[0] for c in calls], "the user's crontab is never overwritten")

    def test_real_home_uninstall_unloads_only_an_installed_timer(self):
        script = SCRIPTS / "steward.py"
        calls, run = self._recorder()
        with mock.patch.object(agents, "_run", side_effect=run), \
                mock.patch.object(agents, "PLATFORM", "darwin", create=True):
            self.assertIn("no OS timer", agents.schedule(self.home, script, "uninstall", real_home=True))
            self.assertEqual(calls, [], "nothing installed: launchctl is not called")
            plist = self.home / self.UNITS["darwin"]
            plist.parent.mkdir(parents=True)
            plist.write_text("x")
            agents.schedule(self.home, script, "uninstall", real_home=True)
            self.assertEqual([c[0][:2] for c in calls], [["launchctl", "bootout"]])
            self.assertFalse(plist.exists())

    def test_real_home_linux_uninstall_touches_only_our_entries(self):
        script = SCRIPTS / "steward.py"
        mine = "0 1 * * * backup.sh  # storage-steward is great\n0 2 * * * my-own.sh # storage-steward\n"
        calls, run = self._recorder(mine)
        with mock.patch.object(agents, "_run", side_effect=run), \
                mock.patch.object(agents, "PLATFORM", "linux", create=True), \
                mock.patch("agents.shutil.which", lambda name: f"/usr/bin/{name}"):
            self.assertIn("no OS timer", agents.schedule(self.home, script, "uninstall", real_home=True))
            self.assertEqual([c[0] for c in calls], [["crontab", "-l"]], "read-only probe, no edits")
        ours = mine + agents._cron_line(script) + "\n"
        calls, run = self._recorder(ours)
        timer = self.home / self.UNITS["linux"]
        timer.parent.mkdir(parents=True)
        timer.write_text("x")
        with mock.patch.object(agents, "_run", side_effect=run), \
                mock.patch.object(agents, "PLATFORM", "linux", create=True), \
                mock.patch("agents.shutil.which", lambda name: f"/usr/bin/{name}"):
            agents.schedule(self.home, script, "uninstall", real_home=True)
        cmds = [c[0] for c in calls]
        self.assertIn(["systemctl", "--user", "disable", "--now", "storage-steward.timer"], cmds)
        self.assertFalse(timer.exists())
        self.assertEqual([c[1] for c in calls if c[0] == ["crontab", "-"]], [mine], "user's cron line kept")

    def test_paths_are_quoted_for_launchd_systemd_and_cron(self):
        script = Path("/Users/a b/it's & <x>/steward.py")
        py = "/opt/my python/bin/python3"
        with mock.patch.object(agents.sys, "executable", py):
            plist = plistlib.loads(agents._plist(script).encode())
            self.assertEqual(plist["ProgramArguments"][:2], [py, str(script)])
            service = agents._systemd(script)["storage-steward.service"]
            exec_start = next(x for x in service.splitlines() if x.startswith("ExecStart="))
            self.assertEqual(shlex.split(exec_start[len("ExecStart="):])[:2], [py, str(script)])
            cron = agents._cron_line(script)
            self.assertTrue(cron.startswith("17 */3 * * * ") and cron.endswith(" # storage-steward"))
            self.assertEqual(shlex.split(cron[len("17 */3 * * * "):-len("# storage-steward")])[:2], [py, str(script)])
        self.assertNotRegex(agents._cron_line(Path("/a%b/steward.py")), r"(?<!\\)%", "cron turns bare % into newlines")


class RetentionTests(InstallSandbox):
    def test_retention_must_be_a_whole_number_of_days(self):
        for bad in ("-5", "0", "abc", "1.5"):
            with self.subTest(bad), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                self.run_cli("install", "--agents", "claude", "--retention", bad)
        self.assertFalse((self.home / ".claude/settings.json").exists())

    def test_retention_is_announced_recorded_and_reverted(self):
        sp = self.settings({"model": "x"})
        _, out = self.run_cli("install", "--agents", "claude", "--retention", "21", "--dry-run")
        self.assertIn(RETENTION_LINE, out)
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"}, "dry run writes nothing")
        _, out = self.run_cli("install", "--agents", "claude", "--retention", "21")
        self.assertIn(RETENTION_LINE, out)
        self.assertEqual(json.loads(sp.read_text())["cleanupPeriodDays"], 21)
        rec = json.loads((self.home / ".cache/storage-steward/install.json").read_text())
        self.assertEqual(list(rec["cleanupPeriodDays"].values()), [21])
        _, out = self.run_cli("uninstall")
        self.assertIn("cleanupPeriodDays 21 removed", out)
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"})

    def test_every_file_we_set_is_reverted(self):
        sp = self.settings({"model": "x"})
        other = self.settings({"model": "y"}, "custom/settings.json")
        self.run_cli("install", "--agents", "claude", "--retention", "21")
        self.run_cli("install", "--settings", str(other), "--retention", "30")
        self.run_cli("uninstall")
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"})
        self.assertEqual(json.loads(other.read_text()), {"model": "y"})

    def test_purge_waits_while_a_config_is_skipped(self):
        sp = self.settings({"model": "x"})
        self.run_cli("install", "--agents", "claude", "--retention", "21")
        good = sp.read_text()
        sp.write_text("{broken")
        code, out = self.run_cli("uninstall", "--purge")
        self.assertEqual(code, 1)
        self.assertIn("--purge", out)
        self.assertTrue((self.home / ".cache/storage-steward/install.json").exists(), "record kept for the re-run")
        sp.write_text(good)
        self.run_cli("uninstall", "--purge")
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"})
        self.assertFalse((self.home / ".cache/storage-steward").exists())

    def test_a_value_the_user_chose_is_never_touched(self):
        sp = self.settings({"model": "x"})
        self.run_cli("install", "--agents", "claude", "--retention", "21")
        s = json.loads(sp.read_text())
        s["cleanupPeriodDays"] = 14                       # the user changes it afterwards
        sp.write_text(json.dumps(s))
        _, out = self.run_cli("uninstall")
        self.assertIn("left at 14", out)
        self.assertEqual(json.loads(sp.read_text())["cleanupPeriodDays"], 14)
        sp.write_text(json.dumps({"cleanupPeriodDays": 45}))   # set before we ever ran
        _, out = self.run_cli("install", "--agents", "claude", "--retention", "21")
        self.assertNotIn(RETENTION_LINE, out)
        self.assertEqual(json.loads(sp.read_text())["cleanupPeriodDays"], 45)
        self.run_cli("uninstall")
        self.assertEqual(json.loads(sp.read_text()), {"cleanupPeriodDays": 45})


class UninstallTests(InstallSandbox):
    def test_removes_everything_it_added_and_nothing_else(self):
        self.seed_all()
        foreign_skill = self.settings({}, ".claude/skills/other-skill/conf.json")
        foreign_file = self.settings({}, ".agents/skills/notes.json")
        self.run_cli("install", "--agents", "auto")
        links = [self.home / d / "storage-steward" for d in LINKS]
        self.assertTrue(all(p.is_symlink() for p in links))
        code, out = self.run_cli("uninstall")
        self.assertEqual(code, 0)
        self.assertEqual([p for p in links if os.path.lexists(p)], [], "every skill link removed")
        self.assertTrue(foreign_skill.exists() and foreign_file.exists(), "other skills and files stay")
        self.assertTrue((SKILL_SRC / "scripts/steward.py").exists(), "the source copy is never touched")
        for rel in (".codex/hooks.json", ".gemini/settings.json", ".claude/settings.json"):
            self.assertFalse((self.home / rel).exists(), f"{rel} held only our hooks")
        self.assertEqual(json.loads((self.home / ".cursor/hooks.json").read_text()),
                         {"version": 1, "hooks": {"stop": [{"command": "notify-me"}]}})
        self.assertLessEqual(len(out.strip().splitlines()), 8, out)
        self.assertIn("backups", out)

    def test_cursor_file_with_only_version_left_is_removed(self):
        (self.home / ".cursor").mkdir()
        self.run_cli("install", "--agents", "cursor")
        self.assertTrue((self.home / ".cursor/hooks.json").exists())
        self.run_cli("uninstall")
        self.assertFalse((self.home / ".cursor/hooks.json").exists())

    def test_real_copies_removed_unless_they_hold_other_files(self):
        canon = self.home / ".agents/skills/storage-steward"
        self.copy_skill(canon)
        old = self.home / ".claude/skills/storage-steward"      # a 0.1-era copy the user added notes to
        self.copy_skill(old)
        (old / "NOTES.md").write_text("mine")
        _, out = self.run_cli("uninstall")
        self.assertFalse(canon.exists())
        self.assertTrue((old / "NOTES.md").exists() and (old / "SKILL.md").exists())
        self.assertIn(f"kept {old}", out)

    def test_copy_with_a_nested_file_of_yours_is_kept(self):
        copy = self.home / ".gemini/skills/storage-steward"
        self.copy_skill(copy)
        custom = copy / "scripts/my_custom.py"
        custom.write_text("print('mine')\n")
        _, out = self.run_cli("uninstall")
        self.assertTrue(custom.exists())
        self.assertIn(f"kept {copy}", out)

    def test_similarly_named_skill_is_not_ours(self):
        other = self.home / ".claude/skills/storage-steward"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: storage-steward-pro\n---\n")
        self.assertFalse(agents._is_ours(other))
        self.run_cli("uninstall")
        self.assertTrue((other / "SKILL.md").exists())

    def test_plain_file_where_the_skill_link_goes_is_left_alone(self):
        (self.home / ".claude").mkdir()
        blocker = self.settings({}, ".claude/skills/storage-steward")
        code, out = self.run_cli("install", "--agents", "claude")
        self.assertEqual(code, 0)
        self.assertIn("skipped", out)
        self.assertTrue(blocker.is_file())

    def test_purge_also_removes_policy_and_state(self):
        self.run_cli("config", "keep", "~/models")
        cfg = self.home / ".config/storage-steward/config.json"
        state = self.home / ".cache/storage-steward"
        state.mkdir(parents=True)
        (state / "ledger.jsonl").write_text("x\n")
        other = self.settings({}, ".config/other/x.json")
        self.assertTrue(cfg.exists())
        _, out = self.run_cli("uninstall")
        self.assertTrue(cfg.exists() and state.exists(), "kept without --purge")
        self.assertIn(str(cfg), out)
        self.assertIn("--purge", out)
        self.run_cli("uninstall", "--purge")
        self.assertFalse(cfg.parent.exists())
        self.assertFalse(state.exists())
        self.assertTrue(other.exists())

    def test_purge_keeps_a_policy_dir_holding_other_files(self):
        self.run_cli("config", "keep", "~/models")
        cfg = self.home / ".config/storage-steward/config.json"
        notes = self.settings({}, ".config/storage-steward/my-notes.json")
        _, out = self.run_cli("uninstall", "--purge")
        self.assertFalse(cfg.exists(), "our policy file goes")
        self.assertTrue(notes.exists(), "a file storage-steward did not write stays")
        self.assertIn(f"kept {cfg.parent}", out)

    def test_settings_mode_only_touches_that_file(self):
        self.seed_all()
        self.run_cli("install", "--agents", "claude")
        sp = self.settings({"model": "x"}, "custom/settings.json")
        self.run_cli("install", "--settings", str(sp))
        self.run_cli("uninstall", "--settings", str(sp))
        self.assertEqual(json.loads(sp.read_text()), {"model": "x"})
        self.assertTrue((self.home / ".claude/skills/storage-steward").is_symlink(), "skill links stay")
        self.assertIn("hooks", json.loads((self.home / ".claude/settings.json").read_text()))


class DryRunTests(InstallSandbox):
    def test_dry_run_lists_events_per_agent_and_backups(self):
        self.seed_all()
        before = sorted(str(p) for p in self.home.rglob("*"))
        _, out = self.run_cli("install", "--agents", "auto", "--dry-run")
        self.assertEqual(sorted(str(p) for p in self.home.rglob("*")), before, "nothing written")
        lines = out.splitlines()
        for name, events in (("Claude Code", "UserPromptSubmit, Stop, SessionEnd"),
                             ("Codex", "UserPromptSubmit, Stop"), ("Cursor", "stop, sessionEnd"),
                             ("Gemini CLI / Antigravity", "BeforeAgent, AfterAgent, SessionEnd")):
            line = next(x for x in lines if x.strip().startswith(name + ":"))
            self.assertIn(events, line)
        self.assertIn("backup", out)
        self.assertLessEqual(len(lines), 6 * 2 + 2)


if __name__ == "__main__":
    unittest.main()
