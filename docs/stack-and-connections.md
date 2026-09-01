# Stack & connections — the whole map

Every connection in the system: what runs where, what talks to what, how it authenticates,
and what breaks if a link goes down. Companion to [`activation-checklist.md`](activation-checklist.md)
(that one is "how to turn features on"; this one is "how the pieces connect"). Claude keeps
this current. Last verified: 2026-09-01.

## Where everything runs (three zones)

```
YOUR MAC (Intel MBP)                    YOUR PI (3B+, 10.0.0.112)         CLOUD
─────────────────────                   ─────────────────────────        ─────
Part Studio server  :8434               OctoPi 1.1.0 / OctoPrint 1.11.8  Printables
localhost relay     :5051  ───────────► (haproxy :80)                    Sketchfab
Claude Code + MCP server                     │ USB                       Tripo
OrcaSlicer CLI, Blender                       ▼                          (Meshy - unused)
CAD venv (.venv-cad, py3.13)            Ender 3 V2 printer
claude CLI (headless codegen)
fallback OctoPrint :5001 (idle)
```

## MCP servers (`.mcp.json`)

| Server | What it is | Talks to | Auth | Notes |
|---|---|---|---|---|
| `3dprint` | `mcp-3d-printer-server` (via `npx`) | Pi OctoPrint at **10.0.0.112:80 (direct)** + OrcaSlicer | `${OCTOPRINT_API_KEY}` | Tools: `get_printer_status`, `slice_stl`, `upload_gcode`, `start_print`, `cancel_print`, STL utils. **Points straight at the Pi, not the relay** — works when Claude Code runs from a Terminal that has Local-Network access. |

This is the *secondary* interface (for a Claude session working in the repo). The **Part
Studio is the primary interface** and takes the relay path instead (next section).

## External APIs the Part Studio calls

| Service | Endpoint | Auth | Used for | Status |
|---|---|---|---|---|
| **OctoPrint** (your Pi) | via `OCTO_URL` = `127.0.0.1:5051` → `10.0.0.112:80` | `OCTOPRINT_API_KEY` (Pi app key) | live temps, upload, job status, file list, live toolpath sync | ✅ keyed, working |
| **Printables** | `api.printables.com/graphql` | none (keyless, UA header) | model search + STL import | ✅ working |
| **Sketchfab** | `api.sketchfab.com/v3` | search: none · download: `SKETCHFAB_API_TOKEN` | search + one-click import | ⚠️ search works; import needs free token |
| **Tripo** | `api.tripo3d.ai` / `openapi.tripo3d.ai/v3` | `TRIPO_API_KEY` (Bearer) | photo→3D, text→3D, blueprint multiview | 💳 key set, **balance $0** |
| **Meshy** | `api.meshy.ai` | `MESHY_API_KEY` | alternate AI-gen provider | ⬜ unused by choice (paid) |

## Local tools & runtimes (on the Mac)

| Tool | Path / name | Used for | Depends on |
|---|---|---|---|
| **OrcaSlicer 2.4.2** | `/Applications/OrcaSlicer.app` (CLI) | slicing STL → G-code | the `profiles/ender3v2/*.json` |
| **Blender 4.5** | headless | "make printable" voxel remesh | `scripts/bpy_make_printable.py` |
| **`claude` CLI** | headless, `opus` | describe-to-build/edit, refine (codegen) | a one-time `claude` → `/login` |
| **CAD venv** | `.venv-cad` (Python 3.13) | runs the studio + all mesh work | `cadquery, trimesh, manifold3d, tweaker3, segno, pillow` (pinned) |
| **Tweaker-3** | in CAD venv | auto-orient | (local, no network) |
| **fallback OctoPrint** | `~/octoprint-venv` :5001 | backup only; idle now | (default `OCTO_URL` if the env var is ever unset) |

## The plumbing (easy to forget, load-bearing)

- **The relay** `127.0.0.1:5051 → 10.0.0.112:80` exists because macOS Local Network privacy
  (TCC) blocks the studio's process tree from reaching the Pi directly (errno 65). The
  studio path *needs* it; the MCP server path does not (it goes direct). If temps/uploads
  die in the studio, the relay is the first thing to check. Details:
  [`raspberry-pi-migration.md`](raspberry-pi-migration.md) → "As-built".
- **`OCTO_URL`** env var chooses the studio's target. Set = relay (normal). Unset = the
  Mac's own :5001 fallback.
- **`~/.zshrc`** holds `OCTOPRINT_API_KEY`, `OCTO_URL`, `TRIPO_API_KEY`, and (when you add
  them) `SKETCHFAB_API_TOKEN` / `MESHY_API_KEY`. `scripts/studio.sh` force-sources these so
  the studio has them no matter how it's launched.

## If X breaks, Y stops (dependency chain)

- **Relay down** → studio loses printer temps, upload, and live toolpath sync. (MCP server
  unaffected — it goes direct.)
- **`OCTOPRINT_API_KEY` wrong / regenerated** → *both* the studio and the MCP server lose
  all printer access. Re-paste the new key to Claude.
- **`claude` CLI logged out** → describe-to-build/edit and refine fail; everything else
  (import, parametric models, slice, upload) keeps working.
- **OrcaSlicer moved or missing** → slicing fails on both paths; nothing can reach the
  printer as G-code.
- **CAD venv broken** (e.g. a bad rebuild without the pinned deps) → the studio won't start
  at all; auto-orient / QR / mesh import break first.
- **Printer's USB is on the Pi**, not the Mac — so the Mac can be asleep for slicing/design
  work, but a *print* needs the Pi (and the relay) up.

## The happy-path data flow (a normal print)

```
describe / photo / import / find
      ↓  (claude CLI, or Printables/Sketchfab/Tripo)
   STL in the studio
      ↓  OrcaSlicer CLI
   G-code  →  check-gcode.py (safety gate: temps + volume)
      ↓  OCTO_URL relay
   OctoPrint on the Pi (upload only, never auto-print)
      ↓  USB
   Ender 3 V2  —  (Claude starts the print only with your yes, you present)
```
