#!/usr/bin/env bash
# One-shot setup + verification for the Claude -> OrcaSlicer -> OctoPrint pipeline on macOS.
# Safe to re-run; each step checks before installing. Never starts a physical print.
set -uo pipefail

OCTO_URL="${OCTO_URL:-http://127.0.0.1:5001}"
ORCA_BIN="${ORCA_BIN:-/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer}"
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
PASS=0; FAIL=0
ok()   { echo "  [ok]   $1"; PASS=$((PASS+1)); }
bad()  { echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }
info() { echo "  [..]   $1"; }

echo "== 1. OctoPrint reachability ($OCTO_URL) =="
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$OCTO_URL/api/version" -H "X-Api-Key: ${OCTOPRINT_API_KEY:-}") || code=000
case "$code" in
  200) ok "OctoPrint is up and the API key works" ;;
  403|401) bad "OctoPrint is up but OCTOPRINT_API_KEY is missing/invalid (HTTP $code). See README section 'Getting an API key'." ;;
  000)
    if [ -x "$HOME/octoprint-venv/bin/octoprint" ]; then
      bad "OctoPrint installed but not running. Start it: ~/octoprint-venv/bin/octoprint serve --port 5001"
    else
      bad "OctoPrint is NOT installed in ~/octoprint-venv (no octoprint binary)."
      pyver=$("$HOME/octoprint-venv/bin/python" --version 2>/dev/null | awk '{print $2}')
      case "$pyver" in
        3.14*|3.15*)
          echo "         Cause: venv uses Python $pyver, which OctoPrint does not support."
          echo "         Fix:   brew install python@3.13 && rm -rf ~/octoprint-venv \\"
          echo "                  && python3.13 -m venv ~/octoprint-venv \\"
          echo "                  && ~/octoprint-venv/bin/pip install --upgrade pip wheel \\"
          echo "                  && ~/octoprint-venv/bin/pip install OctoPrint" ;;
        *)
          echo "         Fix:   see README section 'Installing OctoPrint itself (macOS)'" ;;
      esac
    fi ;;
  *) bad "Unexpected HTTP $code from $OCTO_URL/api/version" ;;
esac

echo "== 2. OrcaSlicer =="
if [ -x "$ORCA_BIN" ]; then
  ok "OrcaSlicer found at $ORCA_BIN"
else
  if command -v brew >/dev/null 2>&1; then
    info "Installing OrcaSlicer via Homebrew..."
    brew install --cask orcaslicer && ok "OrcaSlicer installed" || bad "brew install --cask orcaslicer failed"
  else
    bad "OrcaSlicer not found and Homebrew missing. Install from https://github.com/SoftFever/OrcaSlicer/releases"
  fi
fi

echo "== 3. Node.js / MCP server =="
if command -v npx >/dev/null 2>&1; then
  ok "npx available ($(node --version 2>/dev/null))"
  info "Priming mcp-3d-printer-server download (npx cache)..."
  # </dev/null matters: the package ignores --help and starts its stdio server,
  # which blocks forever on an interactive terminal. Closing stdin makes it exit.
  if npx -y mcp-3d-printer-server --help </dev/null >/dev/null 2>&1; then
    ok "mcp-3d-printer-server fetchable via npx"
  else
    bad "npx could not fetch/run mcp-3d-printer-server"
  fi
else
  if command -v brew >/dev/null 2>&1; then
    info "Installing Node.js via Homebrew..."
    brew install node && ok "Node.js installed" || bad "brew install node failed"
  else
    bad "Node.js not found and Homebrew missing. Install from https://nodejs.org"
  fi
fi

echo "== 4. API key in environment =="
if [ -n "${OCTOPRINT_API_KEY:-}" ]; then
  ok "OCTOPRINT_API_KEY is set"
else
  bad "OCTOPRINT_API_KEY not set. Add to ~/.zshrc:  export OCTOPRINT_API_KEY=\"<your key>\""
fi

echo "== 5. Test slice (STL -> G-code) =="
if [ -x "$ORCA_BIN" ]; then
  "$REPO_DIR/scripts/test-slice.sh" && ok "CLI slicing works (output/calibration_cube_20mm.gcode)" || bad "Test slice failed — see output above"
else
  info "Skipped (OrcaSlicer not installed yet — re-run after step 2 succeeds)"
fi

echo "== 6. Test upload to OctoPrint (no print started) =="
if [ -n "${OCTOPRINT_API_KEY:-}" ] && [ -f "$REPO_DIR/output/calibration_cube_20mm.gcode" ]; then
  "$REPO_DIR/scripts/octoprint-upload.sh" "$REPO_DIR/output/calibration_cube_20mm.gcode" \
    && ok "G-code uploaded to OctoPrint (queued, NOT printing)" || bad "Upload failed"
else
  info "Skipped (needs API key + a sliced file from step 5)"
fi

echo
echo "Done: $PASS ok, $FAIL failing. Re-run this script after fixing failures."
[ "$FAIL" -eq 0 ]
