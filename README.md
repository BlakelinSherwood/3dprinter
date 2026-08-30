# 3D Printer Pipeline — Ender 3 V2 + OctoPrint + OrcaSlicer + Claude

A pipeline so Claude can take "make me a part," generate an STL, slice it for an
Ender 3 V2 (220×220×250mm, PLA), and queue it on OctoPrint — with printing always
gated on your explicit go-ahead.

```
Claude (local session on the Mac)
  └─ generates STL ──► OrcaSlicer CLI (slice) ──► OctoPrint REST API (upload/queue)
        via mcp-3d-printer-server (MCP), configured in .mcp.json
```

## Installing OctoPrint itself (macOS)

OctoPrint does **not** support Python 3.14. If your `python3` is 3.14, a plain
`python3 -m venv` produces a venv that pip silently downgrades to OctoPrint
1.8.7, which then dies building PyYAML 5.4.1 with:

```
'build_ext' object has no attribute 'cython_sources'
```

Build the venv on **Python 3.13** instead:

```bash
brew install python@3.13
rm -rf ~/octoprint-venv                       # discard any 3.14 venv
$(brew --prefix python@3.13)/bin/python3.13 -m venv ~/octoprint-venv
~/octoprint-venv/bin/python -m pip install --upgrade pip wheel setuptools
~/octoprint-venv/bin/pip install "octoprint>=1.10"
~/octoprint-venv/bin/octoprint --version      # expect 1.10 or newer
```

Then start it (port 5001, loopback only):

```bash
~/octoprint-venv/bin/octoprint serve --host 127.0.0.1 --port 5001
```

Leave it running and open http://127.0.0.1:5001 to complete the first-run
wizard. **Until the wizard is finished, OctoPrint returns HTTP 403 for
privileged API calls such as file upload**, even with a valid API key — so
`setup-mac.sh` cannot pass until you have created the admin account.

## Quickstart (on the Mac)

```bash
git clone <this repo> ~/3dprinter
cd ~/3dprinter
export OCTOPRINT_API_KEY="<your key — see below>"   # also add to ~/.zshrc
chmod +x setup-mac.sh scripts/*.sh
./setup-mac.sh
```

`setup-mac.sh` is idempotent and verifies every link in the chain: OctoPrint
reachable → OrcaSlicer installed (installs via `brew install --cask orcaslicer`
if missing) → Node/npx available → test-slices the bundled 20mm calibration cube
→ uploads the G-code to OctoPrint **without starting a print**. Re-run it until
everything reports `[ok]`.

Then start Claude Code **inside this directory on the Mac** — `.mcp.json` is
picked up automatically and gives Claude these tools against your printer:
`get_printer_status`, `slice_stl`, `upload_gcode`, `start_print`, `cancel_print`,
plus STL utilities (`scale_stl`, `rotate_stl`, `center_model`, `lay_flat`, …).

> **Important:** the MCP server talks to `127.0.0.1:5001`, so it only works when
> Claude runs *on the Mac itself* (Claude Code CLI/desktop, or Claude Desktop).
> A cloud/remote Claude session cannot reach your Mac's localhost.

## Getting an OctoPrint API key

1. Open http://127.0.0.1:5001 and log in.
2. Click the **wrench icon** (Settings) → under **Features**, choose
   **Application Keys** (on older OctoPrint versions: **API** in the left sidebar).
3. Under "Manually generate an application key", enter a name like
   `claude-pipeline` and click **Generate**. Copy the key immediately.
4. If your version still shows a **Global API Key** under Settings → API, that
   works too, but a per-app Application Key is preferred (revocable on its own).
5. Put it in your shell environment so `.mcp.json` can expand it:
   ```bash
   echo 'export OCTOPRINT_API_KEY="paste_key_here"' >> ~/.zshrc && source ~/.zshrc
   ```
   (For Claude Desktop, which doesn't inherit shell env, paste the key directly
   into its `claude_desktop_config.json` instead.)

## Slicer profiles

`profiles/ender3v2/` holds hand-written OrcaSlicer config JSONs (machine =
220×220×250 Marlin with standard Ender prime-line start G-code; process = 0.20mm
layers, 3 walls, 15% grid infill, conservative speeds; filament = generic PLA at
210/60°C). They are a sensible starting point, **but watch the first layer of
your first print closely**.

Preferred long-term path: open OrcaSlicer once, add printer **Creality Ender-3
V2** with its bundled system presets, tweak to taste, then point `SLICER_PROFILE`
in `.mcp.json` (and the paths in `scripts/test-slice.sh`) at your saved user
presets in `~/Library/Application Support/OrcaSlicer/user/default/`.

## Manual pipeline (no MCP, for debugging)

```bash
python3 scripts/generate_test_cube.py 20 test-parts/calibration_cube_20mm.stl
scripts/test-slice.sh                                  # STL -> output/*.gcode
scripts/octoprint-upload.sh output/calibration_cube_20mm.gcode
```

The slice script uses OrcaSlicer's CLI (`--load-settings … --slice 0
--export-3mf`) and extracts `Metadata/plate_1.gcode` from the sliced .3mf —
that's the plain G-code OctoPrint wants.

## Safety rules

- Uploads always use `select=false&print=false` — nothing prints on upload.
- Claude must ask before calling `start_print`, ever.
- `confirm_temperatures` (MCP tool) should be run on generated G-code before any
  print: PLA sanity range is nozzle 190–230°C, bed ≤ 70°C.
- Never print unattended until the profile has proven itself on a few parts.

## Moving to a Raspberry Pi (OctoPi)

See [docs/raspberry-pi-migration.md](docs/raspberry-pi-migration.md) — short
version: only `PRINTER_HOST`/`PRINTER_PORT` and a fresh API key change; slicing
stays on the Mac.
