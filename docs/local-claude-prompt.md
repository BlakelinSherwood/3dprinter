# Handoff prompt for a local Claude Code session

Run `claude` inside `~/3dprinter` on the Mac, then paste the prompt below.
(Approve the project's `.mcp.json` MCP server if it asks; `/mcp` verifies it.)

---

You're picking up a working 3D-printing pipeline. Read the repo README first —
it describes the system as-built. The short version:

Hardware/software state (as of Sep 2026):
- Ender 3 V2 (BLTouch, Creality 4.2.2 board), 220x220x250mm, 0.4 nozzle.
- OctoPrint runs on a Raspberry Pi 3B+ (OctoPi) at 10.0.0.112, port 80.
  The printer's USB goes to the Pi, NOT the Mac.
- The Mac reaches the Pi through a localhost relay: `OCTO_URL` is
  `http://127.0.0.1:5051`, forwarded to `10.0.0.112:80`. This exists because
  macOS Local Network privacy (TCC) blocks direct LAN requests from some
  process trees (errno 65). If port 5051 is dead, restart the relay:
  see docs/raspberry-pi-migration.md "As-built".
- `OCTOPRINT_API_KEY` (the Pi's Application Key), `OCTO_URL`, and optional
  `TRIPO_API_KEY` / `SKETCHFAB_API_TOKEN` live in ~/.zshrc.
- OrcaSlicer 2.4.2 at /Applications/OrcaSlicer.app; profiles in
  profiles/ender3v2/ (machine + process + PLA/PETG/TPU filaments).
- Part Studio (the visual editor, primary UI): `scripts/studio.sh` serves
  http://127.0.0.1:8434 from the CAD venv (.venv-cad, Python 3.13).

SAFETY RULES (non-negotiable, from Blake):
- NEVER start a physical print without asking Blake first and getting a yes.
- Uploads must use select=false / print=false.
- Sanity-check G-code before any print: scripts/check-gcode.py enforces
  temperature envelopes (PLA 190-230/70, PETG 220-260/90, TPU 195-245/60)
  and the 220x220x250 volume. Slicing through the studio or
  scripts/test-slice.sh runs it automatically; uploads re-check.
- Blake must be physically present for a first-layer check before anything
  prints.

Useful entry points:
- Slice + safety-check an STL: `scripts/test-slice.sh <stl> <name>`
  (MATERIAL=pla|petg|tpu, REPETITIONS=N for copies).
- Upload checked G-code (never prints): `scripts/octoprint-upload.sh <gcode>`.
- Printer status: `curl -s -H "X-Api-Key: $OCTOPRINT_API_KEY" $OCTO_URL/api/printer`.
- CadQuery models live in models/ (see models/_meshlib.py for mesh-mod
  helpers and the measured clearances: 0.4 press / 0.5 drag / 0.6 free).
