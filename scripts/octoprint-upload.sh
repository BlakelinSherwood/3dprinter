#!/usr/bin/env bash
# Upload a G-code file to OctoPrint's local storage. Does NOT select or start the print.
# Usage: scripts/octoprint-upload.sh path/to/file.gcode
set -euo pipefail

OCTO_URL="${OCTO_URL:-http://127.0.0.1:5001}"
GCODE="${1:?usage: octoprint-upload.sh file.gcode}"
: "${OCTOPRINT_API_KEY:?OCTOPRINT_API_KEY must be set}"

curl -sf -X POST "$OCTO_URL/api/files/local" \
  -H "X-Api-Key: $OCTOPRINT_API_KEY" \
  -F "file=@$GCODE" \
  -F "select=false" \
  -F "print=false"
echo
echo "Uploaded $(basename "$GCODE") to OctoPrint local storage (not selected, not printing)."
