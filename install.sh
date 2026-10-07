#!/usr/bin/env bash
# Install storage-steward: copy the skill into ~/.claude/skills and add its hooks.
# Usage: ./install.sh [--retention DAYS]
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
dest="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/storage-steward"

command -v python3 >/dev/null || { echo "storage-steward needs python3 (3.9+)" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || { echo "python3 is older than 3.9" >&2; exit 1; }

mkdir -p "$dest"
cp -R "$here/storage-steward/SKILL.md" "$here/storage-steward/scripts" "$here/storage-steward/references" "$dest/"
find "$dest" -name __pycache__ -type d -prune -exec rm -rf {} +
echo "skill copied to $dest"
python3 "$dest/scripts/steward.py" install "$@"
