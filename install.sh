#!/usr/bin/env bash
# Install storage-steward for every coding agent on this machine.
# One real copy goes to ~/.agents/skills (read by Codex, OpenCode and others); Claude Code, Cursor,
# Gemini CLI and Copilot CLI get symlinks. Hooks are added in each agent's own format.
# Usage: ./install.sh [--dry-run] [--agents auto|all|claude,codex,cursor,gemini] [--schedule] [--retention DAYS]
# Re-run it after `git pull` to update; it replaces the old copy.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="$HOME/.agents/skills/storage-steward"

command -v python3 >/dev/null || { echo "storage-steward needs python3 (3.9+)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "python3 is older than 3.9" >&2; exit 1; }

for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then
    echo "dry run: would copy the skill to $dest"
    exec python3 "$here/storage-steward/scripts/steward.py" install "$@"
  fi
done

if [ -e "$dest" ] && [ ! -L "$dest" ] && ! grep -q '^name: storage-steward$' "$dest/SKILL.md" 2>/dev/null; then
  echo "refusing: $dest exists and is not storage-steward; move it aside first" >&2
  exit 1
fi

# Stage a fresh copy, then swap it in, so an update never leaves files from an older version behind.
mkdir -p "$(dirname "$dest")"
staging="$(mktemp -d "$(dirname "$dest")/.storage-steward.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
cp -R "$here/storage-steward/SKILL.md" "$here/storage-steward/scripts" "$here/storage-steward/references" "$staging/"
find "$staging" -name __pycache__ -type d -prune -exec rm -rf {} +
chmod 755 "$staging"
rm -rf "$dest"
mv "$staging" "$dest"
trap - EXIT
echo "$(python3 "$dest/scripts/steward.py" --version) copied to $dest"
python3 "$dest/scripts/steward.py" install "$@"
