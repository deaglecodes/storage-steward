#!/usr/bin/env bash
# Install storage-steward for every coding agent on this machine.
# One real copy goes to ~/.agents/skills (read by Codex, OpenCode and others); Claude Code, Cursor,
# Gemini CLI and Copilot CLI get symlinks. Hooks are added in each agent's own format.
# Usage: ./install.sh [--dry-run] [--agents auto|all|claude,codex,cursor,gemini] [--schedule] [--retention DAYS]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$HOME/.agents/skills/storage-steward"

command -v python3 >/dev/null || { echo "storage-steward needs python3 (3.9+)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "python3 is older than 3.9" >&2; exit 1; }

mkdir -p "$dest"
cp -R "$here/storage-steward/SKILL.md" "$here/storage-steward/scripts" "$here/storage-steward/references" "$dest/"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "skill copied to $dest"
python3 "$dest/scripts/steward.py" install "$@"
