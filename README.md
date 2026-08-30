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

OctoPrint does **not** support Python 3.14. With a 3.14 venv, pip silently falls
back to ancient OctoPrint 1.8.7, which then dies building PyYAML 5.4.1 with:

```
'build_ext' object has no attribute 'cython_sources'
```

Build the venv on **Python 3.13** instead:

```bash
brew install python@3.13
rm -rf ~/octoprint-venv                       # discard any 3.14 venv
python3.13 -m venv ~/octoprint-venv
~/octoprint-venv/bin/python -m pip install --upgrade pip wheel setuptools
~/octoprint-venv/bin/pip install "octoprint>=1.10"
~/octoprint-venv/bin/octoprint --version      # expect 1.10 or newer
```

Then start it (port 5001, loopback only):

```bash
~/octoprint-venv/bin/octoprint serve --host 127.0.0.1 --port 5001
```

Leave it running and open http://127.0.0.1:5001 to complete the first-run
wizard, then generate the API key as described below. **Until the wizard is
finished, OctoPrint returns HTTP 403 for privileged API calls such as file
upload**, even with a valid API key — so `setup-mac.sh` cannot pass until you
have created the admin account.

## Quickstart (on the Mac)

```bash
git clone https://github.com/BlakelinSherwood/3dprinter ~/3dprinter
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

## Handing off to a local Claude session

Claude must run **on the Mac** for any of this to work (it needs localhost:5001,
/Applications/OrcaSlicer.app, and the USB port). A ready-to-paste prompt that
brings a fresh local session fully up to speed lives in
[docs/local-claude-prompt.md](docs/local-claude-prompt.md).

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

`.mcp.json` must point the MCP server at **both** the machine and process
profiles (`SLICER_PROFILE`, joined with `;`) plus the filament profile
(`FILAMENT_PROFILE`). Passing only a process profile makes `slice_stl` fail with
a bare "Slicer failed" — OrcaSlicer needs a machine profile to slice at all.

Preferred long-term path: open OrcaSlicer once, add printer **Creality Ender-3
V2** with its bundled system presets, tweak to taste, then point `SLICER_PROFILE`
in `.mcp.json` (and the paths in `scripts/test-slice.sh`) at your saved user
presets in `~/Library/Application Support/OrcaSlicer/user/default/`.

## Modelling parts (CadQuery)

Part models live in `models/` as small parametric CadQuery scripts. Each one
takes an output path and prints its bounding box, so a part can be re-generated
at a different size without editing the file:

```bash
scripts/setup-cad.sh                              # once: builds .venv-cad
scripts/make-part.sh models/cable_clip.py         # default 5mm cable
scripts/make-part.sh models/cable_clip.py 6.5     # 6.5mm cable
```

`make-part.sh` runs the whole chain — model → STL → slice → **safety check** →
upload to OctoPrint — and never selects or starts a print. The safety check
(`scripts/check-gcode.py`) exits non-zero on an out-of-range temperature or
out-of-volume move, and because the script runs under `set -e`, an unsafe slice
can never reach the upload step.

CadQuery lives in its own `.venv-cad`, deliberately separate from
`~/octoprint-venv`. Its dependencies are pinned in `scripts/requirements-cad.txt`
and installed with `--no-deps`: resolving cadquery's full graph pulls in
`numba` → `llvmlite`, which has no Python 3.13 wheel and fails to build from
source. Nothing needs it at runtime.

Design parts to print without supports where possible — flat face on the bed,
overhangs under about 45°.

## Part Studio (visual model editor)

A local web UI over the same pipeline: pick a model, adjust its parameters,
see the part in 3D on a 220×220 build plate, then slice and upload without
leaving the browser.

```bash
scripts/studio.sh          # serves http://127.0.0.1:8434
```

- **Describe it** builds a brand-new model from a sentence ("Build new") or
  rewrites the selected one ("Edit selected"). Generation shells out to the
  `claude` CLI headlessly with `viewer/design_rules.md` — the Ender 3 V2 / PLA
  / 0.4-nozzle design rules — injected into every request, validates that the
  generated file actually builds (one automatic repair round on failure), and
  keeps prior versions in `models/.history/`. Requires a one-time `claude`
  CLI login (`claude`, then `/login`); everything else works without it.
- **Generate** re-runs the CadQuery model with the values in the form.
- **scale ×** applies a display/output scale: decimals (`0.5`, `2`) or hobby
  ratios (`1/64`, `1:55`, `150%`). Parts are auto-dropped onto the bed plane,
  and warnings flag anything too big for 220×220×250, close to the plate
  edge, or too small to print (tiny bounding box, or estimated feature
  thickness under two perimeter widths).
- **Rotate** turns the part in 90° steps about X/Y/Z (imports included) and
  re-drops it onto the bed. Orientation drives strength, supports and finish.
- **Print settings** override the profile per-slice: layer height
  (0.12/0.16/0.2/0.28), infill %, tree supports, and a brim (auto-suggested
  for tall parts with small footprints). Overrides are merged onto
  `profiles/ender3v2/process.json` at slice time; the profile itself never
  changes. Changing a setting re-locks Upload until the part is re-sliced.
- **Slice + check** runs the normal `test-slice.sh` path; the safety report is
  shown verbatim, and **Upload stays disabled unless the check passes**. After
  a successful slice the panel shows the estimated print time and filament
  use (oz/ft or g/m, following the units toggle). Slicer failures now surface
  Orca's real reason (e.g. "floating regions - enable supports") instead of a
  bare error.
- **Upload** independently re-runs `check-gcode.py` on the file before sending
  it, and always uploads with `select=false&print=false`.
- The header shows a **live printer strip** (connection state, nozzle/bed
  temperatures, 5s poll), and an **OctoPrint queue** section lists the G-code
  files on the printer with per-file delete. Both are read-only against the
  printer - delete is the only mutation, and it never touches a selected or
  printing file (OctoPrint refuses, and the refusal is shown).
- **undo edit** swaps the selected model with its most recent saved version
  from `models/.history/` - pressing it again swaps back, so no version is
  ever lost. **&#8595; STL** downloads the currently generated STL.
- There is deliberately **no print button** — the server has no endpoint that
  can start a print.

The UI is stdlib Python + a vendored Three.js (`viewer/`), so it needs no
extra dependencies and works offline. Claude Code sessions can launch it via
the `part-studio` entry in `.claude/launch.json`. It binds to 127.0.0.1 only.

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
