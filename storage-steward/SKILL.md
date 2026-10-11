---
name: storage-steward
description: Keeps disk storage healthy while coding agents work, in Claude Code, Codex, Cursor, Gemini CLI, OpenCode, Copilot CLI or any agent that reads SKILL.md. Prevents and sweeps agent leftovers (background task output, desktop-app sandboxes, stale worktrees, old transcripts and sessions, npx/uv/pnpm/pip/Xcode caches) using token-cheap commands and zero-token hooks, without deleting user data or slowing the next build. Use this whenever disk space or storage comes up ("my Mac is full", "System Data is huge", low disk warnings, cleaning caches/temp files/leftovers), when the user wants cleanup to happen automatically instead of by hand, before writing anything big (model downloads, docker builds, datasets, monorepo installs, new worktrees), and when long sessions or many subagents might be filling the disk, even if the user never names this skill.
license: MIT
metadata:
  version: "0.2.0"
---

# Storage Steward

Coding agents leak disk in a few predictable places: background task output that is never deleted
(single Claude Code sessions have written 278–771 GB to `/private/tmp/claude-<uid>`), per-task sandbox
clones, a fresh `node_modules` per worktree, transcripts and session history, and package caches.
People end up cleaning by hand every day. This skill makes cleanup continuous and cheap, whichever agent
you are. Hooks or an OS timer do the recurring work at zero token cost. You prevent new leftovers while
you work. Anything that might be user data goes to the user.

`S` below means `python3 <this-skill-dir>/scripts/steward.py`. It uses only the Python standard library
(3.9+), and its output is short (`scan` is about 15 lines). The table below is the complete interface, so
there's no need for `--help` or to read the script source. `install` self-tests its own hooks.

## Keep it token-cheap

Never explore disk usage with raw `du`, `find`, `ls -R` or `ncdu`. Their output is thousands of lines,
and reading it costs more than the cleanup is worth. The script already knows the agent and dev-tool
hotspots and summarizes them. One `scan` per task is enough, and `sweep` prints its own one-line result.
Open `references/targets.md` only when someone asks why a path is safe or what a rule touches.

| Command | Output |
|---|---|
| `S status` | one line: free space, flags LOW |
| `S scan` | dry run grouped by tier (auto / confirm / info) |
| `S scan --only RULE --paths` | every path that rule would remove (show these before asking for approval) |
| `S sweep` | reclaims the auto tier, prints one line |
| `S sweep --tier confirm --only RULE[,RULE] --yes` | reclaims named confirm-tier rules, only after the user agrees |
| `S report` | total reclaimed so far, and where the per-path removal log is |
| `S install [--agents auto] [--schedule]` / `S uninstall [--purge]` | turn automation on or off |
| `S schedule install` | an OS timer only (launchd, systemd or cron), for agents without hooks |
| `S rules` | the effective policy: every rule, its tier and age threshold, the keep list |
| `S config set RULE --tier auto\|confirm\|info\|off --idle 14d` | change one rule (`--idle` takes `14`, `14d` or `6h`) |
| `S config keep PATH_OR_GLOB…` / `S config unkeep …` | never delete these, whatever the rule |
| `S config add NAME --path GLOB [--idle 7] [--tier auto]` / `S config drop NAME` | the user's own folders to clean |

Once installed, cleanup is automatic: hooks sweep after sessions, and nobody types `scan` or `sweep`. Those
two are for when the user asks what's taking space, or approves confirm-tier items.

## Make it automatic (offer this once)

Daily manual cleanup stops when automation is on. It's a persistent settings change, so ask first, and
say in one sentence what it does. `S install` finds the agents on this machine. It puts the skill where
each one reads skills: one real copy in `~/.agents/skills`, and symlinks for the others. It also adds
hooks in each agent's own format:

| Agent | Hooks file | Free-space check | Background sweep |
|---|---|---|---|
| Claude Code | `~/.claude/settings.json` | `UserPromptSubmit` | `Stop`, `SessionEnd` |
| Codex | `~/.codex/hooks.json` | `UserPromptSubmit` | `Stop` |
| Cursor | `~/.cursor/hooks.json` | — | `stop`, `sessionEnd` |
| Gemini CLI / Antigravity | `~/.gemini/settings.json` | `BeforeAgent` | `AfterAgent`, `SessionEnd` |
| OpenCode, Copilot CLI, anything else | — | — | `--schedule` (OS timer every 3 h) |

- **Free-space check:** it adds a warning to context only when disk is low. Otherwise it prints nothing
  (or `{}` where the agent requires JSON), so it costs 0 tokens.
- **Background sweep:** it runs detached, throttled to once every 3 hours (immediately when disk is low).
  The agent never waits for it.
- **Safe to repeat:** every edited file is backed up, and existing hooks from other tools are kept.
  `install` is idempotent. `uninstall` removes these hooks, the skill links and copy, and the timer;
  `--purge` also removes the user's policy and the removal log.
- **`--retention 21`:** also sets Claude Code's built-in transcript retention, so Claude Code itself deletes
  transcripts older than 21 days. Add it only if the user asks for shorter retention.

## Tweak what goes and what stays (when the user asks)

The user's policy lives in `~/.config/storage-steward/config.json`. Change it with `S config`, never by
hand-editing, so it stays valid. Translate the request into the narrowest change, then confirm it in one
line. Run `S rules` first only if you need rule names.

| They say | You run |
|---|---|
| "never delete my Claude transcripts" | `S config set claude-transcripts --tier off` |
| "clear task output after 6 hours, not a day" | `S config set claude-task-output --idle 6h` |
| "just delete old Codex sessions, don't ask" | `S config set codex-sessions --tier auto --idle 45d` |
| "don't touch ~/models or any .mov file" | `S config keep ~/models '*.mov'` |
| "also clean my ~/work/*/build folders weekly" | `S config add work-builds --path '~/work/*/build' --idle 7 --tier auto` |
| "undo that" | `S config unset RULE` / `S config unkeep PATH` / `S config drop NAME` |

Guard rails you can rely on (and should mention when relevant):
- `keep` beats every rule. A name pattern like `'*.mov'` also keeps any folder that contains a match.
- Custom rules must name a folder below `~`; `~/*`, `..` and paths outside home are refused.
- Nothing inside Documents, Desktop, Downloads, Pictures, Movies or Music is ever swept automatically,
  whatever the tier; rules there are capped at confirm.
- A broken config file never breaks a hook, but it pauses all deletes until it's fixed (`scan` says why).
  If the user wants cleanup to resume, run `S config show` and fix the reported problem with them.

## While you work: don't create the mess

These habits matter more than any sweep, because they stop the big leaks at the source:

1. **Use one scratch place.** Put intermediates in your session's scratch or temp directory, or in a
   single `mktemp -d`, not scattered across the repo, `~` or `/tmp`. Delete them when the task is done,
   but keep the deliverables. Ask yourself what would be left if this task ran ten times.
2. **Never let a background process stream unbounded output.** Dev servers, watchers, `tail -f` and
   verbose builds left running in the background write to log or task-output files that nothing caps.
   That is how the 500 GB `.output` files happened. Silence them (`> /dev/null 2>&1`) and probe health
   separately (`curl -sf localhost:3000`), or use the tool's quiet or log-level flag. Stop them when
   you're done.
3. **Clone dependencies; don't reinstall them per worktree.** On macOS (APFS),
   `cp -c -R ../main/node_modules node_modules` makes a copy-on-write clone that takes almost no extra
   space. pnpm's hardlinked store does the same. Remove a worktree when its branch is merged or abandoned
   (`git worktree remove <path>`).
4. **Check before you write more than ~1 GB.** Model pulls, docker builds, datasets and fresh installs:
   run `S status` first. If it says LOW, run `S sweep`, and tell the user if space is still tight instead
   of letting the disk hit 0 bytes. Agents and editors can corrupt their own settings at 0 bytes free.
5. **Stream rather than materialize.** `curl … | tar xz`, `git clone --depth 1`, pipes instead of giant
   intermediate files. Delete downloaded archives after extracting them.

## Safety model: why sweeps never cost the user anything

- **auto:** regenerable items or pure agent junk, where the worst case is a re-download or rebuild.
  Examples: idle task output, idle session temp dirs, plugin clones inside idle desktop sandboxes, old
  debug logs, OpenCode undo snapshots older than 30 days, stale npx/uv/pip/Xcode build caches, `$TMPDIR`
  entries older than 7 days. Hooks, the timer and plain `sweep` handle these.
- **confirm:** recoverable only from somewhere else, or part of the user's history. Examples: clean
  agent worktrees, transcripts and Codex/Gemini/Copilot sessions older than 30 days, Cursor workspace
  storage, `node_modules`/`.venv` of projects idle for 30+ days, old Playwright browsers, Docker build
  cache. Show the user the rule names and sizes from `scan`. For rules that touch their own folders
  (`stale-project-deps`, `agent-worktrees`, their custom rules), also show `S scan --only RULE --paths`.
  Then run `--only` with exactly the rules they approve; `sweep --tier confirm` refuses without it.
- **info:** local models, the Cowork VM image, Codex DBs, Cowork `outputs/`, Trash. The script never
  deletes these. Tell the user what they are and how to handle them in their app.

The script refuses to touch:
- anything written in the last hour
- the current session (the session id from the hook, or `CLAUDE_CODE_SESSION_ID`/`GEMINI_SESSION_ID`)
  and its desktop sandbox
- worktrees unless git shows nothing would be lost (no uncommitted, untracked or non-build ignored files,
  no commits on no branch)
- anything inside Documents, Desktop, Downloads, Pictures, Movies or Music during an automatic sweep
- credentials, settings, memory and skills
- anything at all while the user's config file can't be read

Every removed path is logged to `~/.cache/storage-steward/removed.log`.

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
> Want me to turn on automatic cleanup for your agents so this happens without you asking?
