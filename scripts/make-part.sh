#!/usr/bin/env bash
# Model -> STL -> G-code -> safety check -> OctoPrint upload.
# Never selects a file and never starts a print.
#
# Usage: scripts/make-part.sh models/cable_clip.py [args passed to the model...]
#   e.g. scripts/make-part.sh models/cable_clip.py 6.5   # 6.5mm cable
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MODEL="${1:?usage: make-part.sh models/part.py [model args...]}"
shift || true

NAME="$(basename "${MODEL%.py}")"
OUT_DIR="$REPO_DIR/output"
mkdir -p "$OUT_DIR"
STL="$OUT_DIR/$NAME.stl"

echo "== 1. Model -> STL =="
"$REPO_DIR/.venv-cad/bin/python" "$MODEL" "$STL" "$@"

echo
echo "== 2. Slice + safety check =="
# test-slice.sh runs scripts/check-gcode.py and exits non-zero if the G-code
# violates the temperature or build-volume limits. With `set -e`, that means an
# unsafe slice can never reach the upload step below.
"$REPO_DIR/scripts/test-slice.sh" "$STL" "$NAME"

echo
echo "== 3. Upload to OctoPrint (queued, NOT printing) =="
"$REPO_DIR/scripts/octoprint-upload.sh" "$OUT_DIR/$NAME.gcode"
