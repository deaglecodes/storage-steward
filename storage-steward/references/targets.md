# What each rule touches, and why it's safe

Every threshold and tier below is a default. Users can change any of them with `steward.py config set`,
protect paths with `config keep`, or add their own rules with `config add` (stored in
`~/.config/storage-steward/config.json`). Rules are agent-agnostic. They cover Claude Code, the Claude desktop app, Codex, Cursor, Gemini CLI,
OpenCode and Copilot CLI, plus the dev-tool caches every agent fills.

Read this only when the user asks why something is or isn't deleted. The thresholds are deliberately
conservative: "idle" means nothing in the subtree was modified for that long.

## auto: regenerable or agent junk (hooks sweep these)

| Rule | Path(s) | Condition | Why it's safe / source |
|---|---|---|---|
| claude-task-output | `/private/tmp/claude-<uid>/<proj>/<session>/tasks/*.output` | idle >24h, or >1 GiB and idle >1h | Background-task stdout capture. Nothing caps or deletes it; reported at 278 GB, 537 GB and 771 GB (anthropics/claude-code #41737, #26911, #46479). The current session is always skipped. |
| claude-tmp-sessions | `/private/tmp/claude-<uid>/<proj>/<session-uuid>/` | idle >3d | Per-session scratch and task dirs. Claude Code recreates them; only UUID-named dirs match. |
| desktop-sandbox-plugins | `~/Library/Application Support/Claude/local-agent-mode-sessions/*/*/local_*/.claude/plugins` | sandbox idle >3d | Each task sandbox clones `~/.claude`, mostly plugins, ~300 MB each, never cleaned up (#92158). Only the plugin clone is removed. The sandbox's `outputs/`, `uploads/` and its own transcripts (`.claude/projects`, `sessions`) are kept. |
| claude-debug | `~/.claude/debug/*` | idle >7d | Debug logs; not covered by `cleanupPeriodDays`. |
| claude-file-history | `~/.claude/file-history/<session>` | idle >30d | `/rewind` snapshots; reported up to 300 GB. A month-old session is past any realistic rewind. |
| claude-shell-snapshots | `~/.claude/shell-snapshots/*` | idle >7d | Shell env captures, recreated per session. |
| codex-tmp | `~/.codex/..codex-*.tmp-*`, `~/.codex/.tmp/*` | idle >3d | Leftovers from atomic writes. |
| opencode-snapshots | `~/.local/share/opencode/snapshot/*`, `…/log/*` | idle >30d (logs >7d) | OpenCode undo snapshots, the equivalent of Claude's file-history. |
| cursor-logs | `~/.cursor/logs/*` | idle >14d | Agent logs. |
| npx-cache | `~/.npm/_npx/<hash>` | idle >14d, then second chance | Re-fetched by the next `npx`. Second chance keeps anything still being read. |
| uv-cache | `~/.cache/uv` | `uv cache prune` (native) | Removes only unreachable objects. |
| pnpm-store | `~/Library/pnpm/store` | `pnpm store prune` (native) | Removes only unreferenced packages. |
| pip-cache | `~/Library/Caches/pip`, `~/.cache/pip` | idle >30d | HTTP/wheel cache. |
| brew | Homebrew cache | `brew cleanup --prune=14` | Old versions and downloads. Homebrew does this itself periodically. |
| xcode-derived-data | `~/Library/Developer/Xcode/DerivedData/*` | idle >14d | Build products. Xcode writes here on every build, so idle means not built recently. |
| updater-caches | `~/Library/Caches/*ShipIt*/*` | idle >3d | Squirrel/ShipIt update payloads left after the app updates. |
| user-tmp | `$TMPDIR/*` (not `com.apple*`, not dotfiles) | idle >7d | macOS already clears this at boot after 3 days; 7 days is stricter than the OS. |

## confirm: ask the user, then `sweep --tier confirm --only RULE --yes`

| Rule | Path(s) | Condition | Notes |
|---|---|---|---|
| agent-worktrees | `~/.claude/worktrees`, `~/.codex/worktrees`, `~/.cursor/worktrees`, `<cwd>/.claude/worktrees`, `<cwd>/.worktrees` | idle >7d and `git status --porcelain` empty | Commits live in the main repo, so removing a clean worktree loses nothing committed. Dirty ones are reported as "kept". Afterwards run `git worktree prune` in the main repo. |
| claude-transcripts | `~/.claude/projects/*/*.jsonl` (+ sibling dir) | idle >30d | Session history used by `--resume`. Better long-term fix: `install --retention N` sets `cleanupPeriodDays`. |
| codex-sessions | `~/.codex/sessions/YYYY/MM/DD/*.jsonl`, `~/.codex/archived_sessions` | idle >30d | Codex keeps these forever (openai/codex #42648, #40371). |
| gemini-history | `~/.gemini/tmp/*`, `~/.gemini/history/*` | idle >30d | Gemini CLI chats and checkpoint shadow repos. |
| copilot-sessions | `~/.copilot/session-state/*` | idle >30d | Copilot CLI session state. |
| cursor-workspaces | `Cursor/User/workspaceStorage/*` | idle >60d | Per-workspace state, including chat history. |
| stale-project-deps | `node_modules`, `.venv`, `venv`, `.next`, `.turbo`, `.nuxt`, `.svelte-kit`, `.parcel-cache`, Rust `target` | project idle >30d (git index/HEAD + manifests) | Reinstallable, but costs a reinstall. Never the current project. |
| playwright-old | `~/Library/Caches/ms-playwright/<browser>-<rev>` | older revision, idle >30d | The newest revision of each browser is always kept. |
| desktop-sandboxes-empty | whole `local_*` sandbox | idle >7d, `outputs/` and `uploads/` empty | Removes that Cowork task's transcript too, so ask first. |
| docker-cache | Docker builder cache | `docker builder prune --filter until=168h` | Next build is slower. |
| simulators | CoreSimulator | `xcrun simctl delete unavailable` | Only simulators for runtimes that are no longer installed. |

## info: never deleted by the tool

local-models (Ollama, LM Studio, Hugging Face), claude-vm (the Cowork VM bundle, roughly 10 GB, which
re-downloads), codex-db (`~/.codex/*.sqlite`), sandbox-outputs (Cowork deliverables), trash.

## Hard refusals (in code, not just policy)

- **Protected paths:** `~`, `Documents`, `Desktop`, `Downloads`, `Pictures`, `Movies`, `Music`,
  `Library`, `.ssh`, `.gnupg`, `~/.claude` itself, `settings.json`, `~/.claude.json`, `memory`, `skills`,
  `plugins`, `~/.codex/auth.json`, and `config.toml`. Neither these paths nor anything containing them
  can be deleted.
- **Contained:** each candidate must sit strictly inside its rule's root (realpath checked, symlinks
  are not followed).
- **Recent writes:** anything written in the last hour is skipped. This is re-checked at delete time.
- **The running session:** the current session id and the desktop host sandbox id are skipped.
- **Sandbox mode:** with `--home`, nothing outside the sandbox is touched and native commands are
  skipped.

## Other tools people use (for comparison)

- **Mole** (`tw93/Mole`, `mo clean`/`mo purge`): a one-shot interactive macOS cleaner.
- **Void** (`eladbash/void`): a scan → plan → apply desktop app with an MCP server.
- **npkill**, **kondo**: `node_modules` and build-artifact finders.

All of these are on-demand. storage-steward runs continuously through hooks, costs zero tokens unless
disk is low, and uses second-chance eviction so it doesn't evict caches that are still in use.
