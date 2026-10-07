---
name: storage-steward
description: Keeps disk storage healthy while agents work. Prevents and sweeps agent leftovers (Claude Code task .output files in /tmp/claude-*, desktop-app sandboxes, stale worktrees, old transcripts, Codex sessions, npx/uv/pnpm/pip/Xcode caches) using token-cheap commands and zero-token hooks, without deleting user data or slowing the next build. Use this whenever disk space or storage comes up ("my Mac is full", "System Data is huge", low disk warnings, cleaning caches/temp files/leftovers), when the user wants cleanup to happen automatically instead of by hand, before writing anything big (model downloads, docker builds, datasets, monorepo installs, new worktrees), and when long sessions or many subagents might be filling the disk, even if the user never names this skill.
---

# Storage Steward

Agents leak disk in a few predictable places: background task output that is never deleted (single
sessions have written 278–771 GB to `/private/tmp/claude-<uid>`), per-task sandbox clones, a fresh
`node_modules` per worktree, transcripts, and package caches. People end up cleaning by hand every day.
This skill makes cleanup continuous and cheap. Hooks do the recurring work at zero token cost. You
prevent new leftovers while you work. Anything that might be user data goes to the user.

`S` below means `python3 <this-skill-dir>/scripts/steward.py`. It uses only the standard library, and
every command prints at most ~15 lines. The table below is the complete interface, so there's no need
for `--help`, and no need to read the script source. `install` self-tests its own hooks.

## Keep it token-cheap

Never explore disk usage with raw `du`, `find`, `ls -R`, or `ncdu`. Their output is thousands of lines,
and reading it costs more than the cleanup is worth. The script already knows the agent/dev hotspots and
summarizes them. One `scan` per task is enough, and `sweep` prints its own one-line result, so don't
re-scan just to confirm. Open `references/targets.md` only when someone asks why a path is safe or what
a rule touches.

| Command | Output |
|---|---|
| `S status` | one line: free space, flags LOW |
| `S scan` | dry run grouped by tier (auto / confirm / info) |
| `S sweep` | reclaims the auto tier, prints one line |
| `S sweep --tier confirm --only RULE[,RULE] --yes` | reclaims named confirm-tier rules, only after the user agrees |
| `S report` | total reclaimed so far (for showing value) |
| `S install [--retention 21]` / `S uninstall` | add or remove the hooks |

## Make it automatic (offer this once)

Daily manual cleanup stops when the hooks are installed. Check with `grep -c storage-steward
~/.claude/settings.json`. If they're missing, offer to install them. This is a persistent settings
change, so ask first, and say in one sentence what it does:

- `UserPromptSubmit`: a free-space check that prints a warning into context only when disk is low.
  Otherwise it prints nothing and costs 0 tokens.
- `Stop` and `SessionEnd`: a detached auto-tier sweep, throttled to once every 3 hours (or immediately
  when disk is low). The agent never waits on it.
- `--retention 21`: also sets `cleanupPeriodDays`, Claude Code's built-in transcript retention
  (default 30 days).

`install` backs up `settings.json` and is idempotent. `uninstall` removes only these hooks.

## While you work: don't create the mess

These habits matter more than any sweep, because they stop the big leaks at the source:

1. **Use one scratch place.** Put intermediates in the session scratchpad or a single `mktemp -d`
   directory, not scattered across the repo, `~`, or `/tmp`. Delete them when the task is done, but keep
   the deliverables. A good test: what would be left if this task were run ten times?
2. **Never let a background process stream unbounded output.** Dev servers, watchers, `tail -f`, and
   verbose builds run in the background write into a task output file that nothing caps. That is exactly
   how the 500 GB `.output` files happened. Silence them (`> /dev/null 2>&1`) and probe health separately
   (`curl -sf localhost:3000`), or use the tool's quiet/log-level flag. Stop them when you're done.
3. **Clone dependencies; don't reinstall them per worktree.** On macOS (APFS), `cp -c -R
   ../main/node_modules node_modules` makes a copy-on-write clone that takes almost no extra space.
   pnpm's hardlinked store achieves the same. Remove a worktree when its branch is merged or abandoned
   (`git worktree remove <path>`).
4. **Check before you write more than ~1 GB.** Model pulls, docker builds, datasets, and fresh installs:
   run `S status` first. If it says LOW, run `S sweep`, and tell the user if space is still tight
   instead of letting the disk hit 0 bytes. At 0 bytes, Claude Code itself can corrupt its settings and
   auth.
5. **Stream rather than materialize.** `curl … | tar xz`, `git clone --depth 1`, pipes instead of giant
   intermediate files. Delete downloaded archives after extracting them.

## Safety model: why sweeps never cost the user anything

- **auto**: Things that are regenerable or pure agent junk, where the worst case is a re-download or
  rebuild. Examples: idle task outputs, idle session temp dirs, plugin clones inside idle desktop
  sandboxes, old debug logs, stale npx/uv/pip/Xcode build caches, `$TMPDIR` entries older than 7 days.
  Hooks and plain `sweep` handle these.
- **confirm**: Recoverable only from somewhere else, or part of the user's history. Examples: clean
  agent worktrees, transcripts or Codex sessions older than 30 days, `node_modules`/`.venv` of projects
  idle for 30+ days, old Playwright browsers, Docker build cache. Show the user the rule names and sizes
  from `scan`, then run `--only` with exactly the rules they approve.
- **info**: Local models, the Cowork VM image, Codex DBs, Cowork `outputs/`, Trash. The script never
  deletes these. Tell the user what they are and how to handle them in their app.

The script refuses to touch:
- anything written in the last hour
- the current session (`CLAUDE_CODE_SESSION_ID`) and its desktop sandbox
- worktrees with uncommitted changes
- `Documents`, `Desktop`, and `Downloads`
- credentials, settings, memory, and skills

It also won't empty the Trash, which would be a permanent deletion the user should do themselves.

**Caches that are read but rarely written** (npx, uv fallback) use second-chance eviction: macOS and
Linux relatime update a file's access time only when it is older than its modification time. A stale
entry is first "armed" (atime set just below mtime). If anything reads it, atime moves forward and the
entry is kept. It's deleted only if it stays unread for a further 7 days. That's why `scan` shows some
caches "on probation", and it's how sweeps avoid slowing the next build. In a real disk emergency (under
5 GB free), `S sweep --no-probation` evicts idle caches immediately.

## Telling the user

Keep it to a few lines: what was reclaimed, what needs their decision (confirm-tier rules with sizes),
and at most one recommendation. For example:

> Freed 3.2 GB automatically (npx 2.1 GB, task outputs 0.9 GB); 43 → 46 GB free.
> Needs your OK: 3.3 GB of deps in 10 projects idle 30+ days, 1.1 GB of clean Codex worktrees.
> Biggest item I can't touch: the 10.4 GB Cowork VM image (Claude app settings).
> Want me to install the auto-cleanup hooks so this happens without you asking?

The script is agent-agnostic. Codex, Cursor, or a cron job can call the same commands.
