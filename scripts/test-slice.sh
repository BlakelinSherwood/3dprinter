#!/usr/bin/env bash
# Slice an STL to G-code with OrcaSlicer's CLI using the Ender 3 V2 profiles in this repo.
# Usage: scripts/test-slice.sh [input.stl] [output_basename]
# OrcaSlicer's CLI exports a sliced .3mf; the plate G-code lives inside it at
# Metadata/plate_1.gcode, so we unzip it out to get a plain .gcode for OctoPrint.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ORCA_BIN="${ORCA_BIN:-/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer}"
STL="${1:-$REPO_DIR/test-parts/calibration_cube_20mm.stl}"
BASE="${2:-$(basename "${STL%.stl}")}"
OUT_DIR="$REPO_DIR/output"
mkdir -p "$OUT_DIR"

PROF="$REPO_DIR/profiles/ender3v2"

"$ORCA_BIN" \
  --load-settings "$PROF/machine.json;$PROF/process.json" \
  --load-filament "$PROF/filament_pla.json" \
  --slice 0 \
  --debug 1 \
  --export-3mf "$OUT_DIR/$BASE.3mf" \
  "$STL"

unzip -p "$OUT_DIR/$BASE.3mf" Metadata/plate_1.gcode > "$OUT_DIR/$BASE.gcode"

lines=$(wc -l < "$OUT_DIR/$BASE.gcode")
echo "Sliced OK: $OUT_DIR/$BASE.gcode ($lines lines of G-code)"
grep -m1 -E "^M104|^M109" "$OUT_DIR/$BASE.gcode" >/dev/null || {
  echo "WARNING: no hotend temperature command found in G-code — inspect before printing" >&2
  exit 1
}
