# Changelog

All notable changes to storage-steward. Versions follow [Semantic Versioning](https://semver.org); the
release workflow publishes each version's section below as its GitHub release notes.

## [Unreleased]

What two weeks of real use showed: the steward's hooks ran in over a thousand Claude Code sessions
across several projects on a disk that stayed 2–5% free, and agents did the biggest cleanups by hand.

### Added

- `where` lists the biggest folders in your home, two levels deep, from one `du` pass (about a minute on
  a full disk, 10 lines). It reports only. When `scan` found little on a full disk, agents explored with
  raw `du` themselves; in every large cleanup the space was in the user's own folders (footage, build
  output, big repos). `scan` now points to `where` when the disk is low.

### Fixed

- **`report` overstated what native prunes freed.** `uv cache prune`, `pnpm store prune` and the others
  were credited with every byte of free space the disk gained while they ran, including other
  processes' deletes and APFS freeing space in the background, and even when the prune failed. One
  machine's report said uv freed 77.1 GB in 17 days from a cache that is 6.9 GB. A prune now counts
  only space that both left the folder it prunes and came back as free disk, and only when it succeeds.
  `docker builder prune`, which frees space inside Docker's VM disk, is counted as 0. Existing ledger
  lines keep their old numbers.
- **`uv cache prune` no longer stalls the sweep for a minute.** uvx-launched MCP servers hold uv's cache
  lock while they run, and uv waits up to 5 minutes for it, so every sweep spent 60 seconds blocked
  before giving up. The prune now waits 5 seconds (`UV_LOCK_TIMEOUT`) and tries again on a later sweep.
- **A disk that stays low no longer triggers a sweep after every agent turn.** Low disk used to skip the
  3-hour throttle entirely, so for days a full sweep (native prunes and git checks included) followed
  every turn of every session and subagent. While disk is low, sweeps now run at most every 15 minutes.
- **Agent worktrees are found in every project.** The Claude desktop app makes a worktree per session in
  `<repo>/.claude/worktrees`, and `agent-worktrees` only looked there for the folder it ran from. Those
  worktrees were the single largest leak on the test machine (72 GB across 21 worktrees in one repo),
  and agents removed them by hand, some with `git worktree remove --force`. The rule now checks every
  project under home that Claude Code lists in `~/.claude.json`, with the same git-proven-clean test.
- **Agent worktrees with submodules are kept.** A submodule's own commits, branches and stashes live in
  the worktree's git data (`.git/worktrees/<name>/modules`, or the repo's own `.git/modules`), and git's
  checks on the enclosing checkout don't see them, so a sweep could delete the only copy of a submodule
  commit. These worktrees are now reported as kept, as `git worktree remove` refuses them too.
- After removing a linked worktree, the sweep drops that worktree's entry in its main repo (what
  `git worktree prune` does, for this worktree only), so its branch can be checked out again. The docs
  used to tell you to run `git worktree prune`, which also forgets every other worktree whose folder is
  missing at that moment, say on an unplugged drive, and orphans its index and detached commits.
- The low-disk warning stamps (one file per session) are cleared once they're older than the 6-hour
  warning interval. They used to pile up in `~/.cache/storage-steward` forever.
- `scan --only RULE --paths` lists every path those rules would remove. It used to stop after 40 and
  suggest `--only RULE` even when one was given, so a confirm sweep could remove paths you were never
  shown. Without `--only`, the listing still stops at 40 and names the rules it left out.
- `config set` no longer reports "saved" for a setting that changes nothing. `--idle` on a rule that
  isn't age-based (`pnpm-store`, `simulators`, the report-only rules) and `--tier auto` or `confirm` on a
  report-only rule (`trash`, `local-models`, `claude-vm`, `codex-db`, `sandbox-outputs`) are refused.
  Such settings already in the config are ignored and listed by `rules` and `scan`; before, promoting
  `trash` made it vanish from the report. `config set` on your own rule now says when it stays at confirm
  because it reaches into a personal folder.
- `report` no longer crashes on a damaged `ledger.jsonl`. A line whose numbers aren't numbers, or a stray
  invalid byte (a write cut short by a full disk), used to stop the whole report; now those lines are
  skipped, the rest is totalled, and `report` says how many it skipped.

### Changed

- SKILL.md tells agents to write the command out or define `S` as a shell function. Its old shorthand
  invited `S="python3 …"; $S scan`, which fails in zsh, the macOS default shell; agents hit that error
  in 2 of the 6 sessions that loaded the skill.
- SKILL.md tells agents never to `git worktree remove --force` an agent worktree: if git refuses, the
  worktree holds work, so they ask the user.
- The low-disk warning says "before writing over 1 GB" instead of "before big writes". Agents ran a full
  scan before a 170 MB render.
- Hooks start about 10 ms sooner (70 ms instead of 80): the XML module only the installer needs is no
  longer imported on every hook.

### Project

- The test suite gives the same result whatever the free space on the machine running it. On a nearly
  full disk (the machines this tool is for) four tests failed, while CI, whose runners always have room,
  passed. A guard test keeps it that way.

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
