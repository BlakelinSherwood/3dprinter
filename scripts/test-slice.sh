#!/usr/bin/env bash
# Slice an STL to G-code with OrcaSlicer's CLI using the Ender 3 V2 profiles in this repo.
# Usage: scripts/test-slice.sh [input.stl] [output_basename] [process_json]
# The optional third argument swaps in an alternate process profile (used by
# Part Studio for per-print overrides: layer height, infill, supports, brim).
# Env:
#   MATERIAL=pla|petg|tpu  picks the filament profile and the matching
#                          check-gcode temperature envelope (default pla)
#   REPETITIONS=N          slice N arranged copies of the part (via
#                          --clone-objects; Orca's --repetitions rejects
#                          raw-STL slice-all runs)
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
PROCESS="${3:-$PROF/process.json}"
MATERIAL="${MATERIAL:-pla}"
case "$MATERIAL" in
  pla)  FILAMENT="$PROF/filament_pla.json" ;;
  petg) FILAMENT="$PROF/filament_petg.json" ;;
  tpu)  FILAMENT="$PROF/filament_tpu.json" ;;
  *) echo "unknown MATERIAL '$MATERIAL' (pla|petg|tpu)" >&2; exit 2 ;;
esac

# Log to a file so real failure reasons (e.g. "floating regions, enable
# supports") can be surfaced instead of Orca's bare "run found error".
ORCA_LOG="$OUT_DIR/.orca-$BASE.log"
rm -f "$ORCA_LOG"
rc=0
"$ORCA_BIN" \
  --load-settings "$PROF/machine.json;$PROCESS" \
  --load-filaments "$FILAMENT" \
  ${REPETITIONS:+--clone-objects "$REPETITIONS" --arrange 1} \
  --slice 0 \
  --debug 4 \
  --logfile "$ORCA_LOG" \
  --export-3mf "$OUT_DIR/$BASE.3mf" \
  "$STL" || rc=$?
if [ "$rc" -ne 0 ]; then
  echo "Slicer failed (exit $rc):" >&2
  grep -E "message_type=[12]" "$ORCA_LOG" 2>/dev/null \
    | sed -E 's/.*message=(.*), message_type=[12].*/  \1/' | sort -u | tail -5 >&2
  exit "$rc"
fi

unzip -p "$OUT_DIR/$BASE.3mf" Metadata/plate_1.gcode > "$OUT_DIR/$BASE.gcode"

lines=$(wc -l < "$OUT_DIR/$BASE.gcode")
echo "Sliced OK: $OUT_DIR/$BASE.gcode ($lines lines of G-code)"

# Safety gate: PLA temperature ranges + build-volume containment. Non-zero exit
# here means the G-code must not be printed.
"$REPO_DIR/scripts/check-gcode.py" --material "$MATERIAL" "$OUT_DIR/$BASE.gcode"
