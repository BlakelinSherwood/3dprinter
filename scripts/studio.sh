#!/usr/bin/env bash
# Launch Part Studio (local model/slice/upload web UI) on 127.0.0.1:8434.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

[ -x "$REPO_DIR/.venv-cad/bin/python" ] || {
  echo "CAD venv missing - run scripts/setup-cad.sh first" >&2; exit 1; }

# The upload step needs the OctoPrint key; pull it from ~/.zshrc when the
# launching environment doesn't have it (e.g. started from a GUI process).
# ~/.zshrc is the source of truth for the OctoPrint target - launcher
# environments carry stale copies of these across config changes.
if [ -f "$HOME/.zshrc" ]; then
  eval "$(grep '^export OCTOPRINT_API_KEY=' "$HOME/.zshrc" || true)"
  eval "$(grep '^export OCTO_URL=' "$HOME/.zshrc" || true)"
  export OCTOPRINT_API_KEY OCTO_URL
fi

exec "$REPO_DIR/.venv-cad/bin/python" "$REPO_DIR/viewer/server.py" --port "${PORT:-8434}"
