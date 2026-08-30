#!/usr/bin/env bash
# Build the CAD virtualenv used by models/*.py (CadQuery on OpenCascade).
# Separate from ~/octoprint-venv so CAD dependencies can never disturb OctoPrint.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_DIR/.venv-cad"
PY="${CAD_PYTHON:-$(brew --prefix python@3.13 2>/dev/null)/bin/python3.13}"

[ -x "$PY" ] || { echo "Python 3.13 not found. Run: brew install python@3.13" >&2; exit 1; }

rm -rf "$VENV"
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null

# --no-deps is deliberate. Resolving cadquery's full dependency graph drags in
# numba -> llvmlite, which has no cp313 wheel and fails to build from source.
# None of it is needed at runtime, so every real dependency is pinned here
# instead and installed without resolution.
"$VENV/bin/pip" install --no-deps -r "$REPO_DIR/scripts/requirements-cad.txt"

"$VENV/bin/python" -c "import cadquery; print('cadquery', cadquery.__version__, 'ready')"
