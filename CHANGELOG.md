# Changelog

All notable changes to storage-steward. Versions follow [Semantic Versioning](https://semver.org); the
release workflow publishes each version's section below as its GitHub release notes.

## [0.2.0] - 2026-10-11

The first release since the original Claude Code version. It works with any coding agent, lets you set
your own policy, and closes a set of safety gaps found in a full review. **Upgrading is recommended:**
several of the fixes below stop a sweep from deleting something the docs promised it would keep.

### Safety fixes

- **Protected folders hold on case-insensitive disks.** On a stock Mac (case-insensitive APFS) a custom
  rule written as `~/documents` reached `~/Documents`. Guards now compare files by identity (device and
  inode), so no spelling, `..`, `//` or symlinked parent slips past them.
- **Automatic sweeps never reach inside Documents, Desktop, Downloads, Pictures, Movies or Music**, now
  enforced at delete time for every rule. Before, a tier override or a `..` in a custom rule could lift the
  cap, and a built-in rule promoted to `auto` could reach in.
- **Credentials, agent settings and memory are protected whole.** Nothing inside `~/.ssh`, `~/.gnupg`,
  `~/.aws`, the Keychain, your agents' settings, instructions (`CLAUDE.md`, `AGENTS.md`, rules, agents,
  commands, hooks), memory or skills is ever deleted, even by a rule you or an agent wrote. Before, only
  those folders themselves were protected, not what's inside them.
- **Custom rules stay inside your home folder.** Paths with `..`, or that resolve outside home through a
  symlink, are refused.
- **The keep list covers what it says.** `keep '*.mov'` now protects a folder that contains a `.mov`
  (the README's own example used to delete it), and so is anything inside a matching folder. Names and
  globs ignore case and Unicode normalization (`café` typed or pasted), and path entries work with a
  trailing `/`, `//`, `..`, `$HOME`, a symlinked alias, or another case spelling.
- **A broken or unreadable config pauses deletes** instead of falling back to defaults that ignore your
  keep list.
  A typo in one rule's override switches that rule off. Thresholds must be finite and above zero (`nan`
  was accepted). Hooks and `config` commands keep working with any config, so you can always repair it.
- **Agent worktrees are only removed when git proves nothing is lost.** Codex's nested
  `worktrees/<id>/<repo>` layout was treated as clean even with uncommitted work. Now worktrees with
  uncommitted or untracked files, ignored files that aren't build output (like `.env`), commits on no
  branch, or files outside a checkout are kept. A standalone repo (a real `.git` folder) is removed only
  when every commit is pushed or tagged and nothing is stashed, since its branches go with it.
- **`stale-project-deps` needs a provably idle project.** A project whose activity can't be read (a
  `.git` file, no manifest) counts as active, and so does one whose source files changed recently.
- **`$TMPDIR` sweeps skip live servers' socket folders** (tmux, ssh-agent, IDEs) and refuse a `TMPDIR`
  that contains your home folder.
- An unreadable `outputs/` folder no longer makes a desktop sandbox look empty.
- Files restored or extracted with old timestamps aren't deleted within the hour (on real homes the race
  check also looks at the inode change time).
- Hooks never crash or block the agent on unexpected input or an unwritable state folder, and the
  low-disk warning still appears when the disk is too full to record it.
- `sweep --tier confirm` now requires `--only RULE`, so one approval can't sweep every confirm rule.

### Added

- Works with Codex, Cursor, Gemini CLI / Antigravity, OpenCode and Copilot CLI as well as Claude Code:
  one copy of the skill in `~/.agents/skills`, symlinks for the others, and hooks in each agent's own
  format. `--schedule` adds a launchd / systemd / cron timer for agents without hooks.
- Your own policy in `~/.config/storage-steward/config.json`: `steward.py rules` and `steward.py config`
  change a rule's tier or age, keep paths and patterns, or add your own folders to clean.
- `scan --paths` lists every path a sweep would remove, so you can see exactly what you're approving.
- `steward.py --version`, and a version in `SKILL.md` metadata.
- New rules for OpenCode, Cursor, Gemini CLI and Copilot CLI leftovers.

### Changed

- `install.sh --dry-run` writes nothing. It used to copy the skill into `~/.agents/skills` first. The dry
  run now lists each agent's hook events and the backups it would make.
- `--retention` is opt-in and visible: the README no longer adds it to the install command, install says
  when it sets `cleanupPeriodDays`, and uninstall reverts it if you haven't changed it since.
- `uninstall` removes everything it installed: hooks in every agent, the skill copy and its links, the OS
  timer, the retention setting, and a hooks file left empty. `uninstall --purge` also removes your policy
  and the removal log. It prints what was removed and what stays.
- Re-running `install.sh` (to update) replaces the old copy instead of copying over it, so files removed
  upstream don't linger. It refuses to replace a different skill with the same folder name.

### Installer fixes

- Editing an agent's config keeps its permissions (a `0600` settings file stayed `0600`), writes through a
  symlinked config instead of replacing the link, leaves a file untouched when nothing changes, and keeps
  only the two newest backups per file.
- One unreadable agent config (say, a `hooks.json` with comments) skips that agent with a clear message
  instead of aborting the whole install or uninstall halfway.
- An unreadable `crontab -l` can no longer cause `--schedule` to overwrite your crontab.
- With `--home` (tests, sandboxes) the scheduler never calls `launchctl`, `systemctl` or `crontab`, and on a
  real home, uninstall only calls them when a timer is actually installed. Paths with spaces or quotes
  work in hook commands, the cron line, the systemd unit and the launchd plist.
- `--retention` must be a whole number of days, 1 or more.

### Project

- CI runs on Python 3.9 (the macOS system Python) and 3.14, on macOS and Linux. It also checks that
  the packaged skill runs on its own, that `install.sh --dry-run` leaves `$HOME` untouched, and that
  the website matches its sources.
- Releases are built by CI from the tagged commit, after the full test suite passes.
- The simulator builds agent worktrees as linked worktrees (`git worktree add`), as agents do. With
  standalone repos, the safer worktree check would rightly keep them (their only commit exists nowhere
  else). It no longer counts the steward's own `removed.log` as disk used. The published figures were
  regenerated: day-60 disk use is about 3 GB lower for every policy (no cleanup 294 GB, hooks 61 GB,
  hooks + weekly OK 44 GB), and every percentage saved is unchanged. `bench/build_results.py` now
  rebuilds the published data from the simulator runs.

## [0.1.0] - 2026-10-07

First release: the `storage-steward` skill for Claude Code, with zero-token hooks, auto / confirm /
info tiers, second-chance cache eviction and the 60-day benchmark.

[0.2.0]: https://github.com/deaglecodes/storage-steward/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/deaglecodes/storage-steward/releases/tag/v0.1.0
