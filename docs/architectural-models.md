# Architectural & CAD models — deep dive and workflow

How to bring building plans and CAD models into the Part Studio and print them.
Written 2026-09-01 from a research pass; the import + prep pieces below are built
and tested. Companion strategy doc; see also [`repair-helper.md`](repair-helper.md).

## What now works (built today)

The importer used to take only meshes. It now accepts three groups, each read a
different way, all normalized to one printable STL:

| Group | Formats | How |
|---|---|---|
| Meshes | STL, OBJ, PLY, OFF, GLB, GLTF, **3MF** | trimesh (3MF needed `lxml`, now installed) |
| **CAD solids** | **STEP, STP, IGES, IGS, BREP** | OpenCASCADE → tessellate. Watertight, exact size. |
| Via Blender | **FBX, DAE/Collada, USD**, .blend | headless Blender converter |

- **STEP is the headline.** SolidWorks, Fusion, DataCAD, Onshape, and nearly every
  CAD program export STEP, and it comes in as a true watertight solid. So "someday
  I get SolidWorks/DataCAD" is already handled — you'd just **File → Export → STEP**.
- **Chief Architect** exports **STL** (native, works) and **DAE/Collada** (via
  Blender, works). Its 3DS export is *not* supported — Blender 4.5 dropped the 3DS
  importer — but STL/DAE are the recommended exports anyway.
- Note on honesty: 3DS, X3D, and VRML are **not** accepted (no installed tool reads
  them reliably); the picker won't offer them rather than crash. If you ever need
  one, we add the `assimp` converter.

## The Chief Architect → printed house workflow

Research was blunt about this: a Chief Architect model is **not** a one-click print.
CA exports walls as **single-sided surfaces with no thickness**, often non-manifold,
and at **full real-world size** (a whole house in feet). Three fixes are needed, and
two of them are now one button each in the studio:

1. **In Chief Architect, before exporting** (this part is on you, in CA): make a
   *copy* of the plan, then use a Layer Set to turn **off** framing, furniture,
   fixtures, plants, terrain, and millwork — leave just the shell (walls, roof,
   floors, openings). This removes most of the non-manifold errors and cuts the
   polygon count dramatically. Then export **STL** (or DAE) from a 3D camera view.
2. **Import it** into the studio (the ⊕ model button).
3. **Press 🏠 solidify walls.** This one step (a headless Blender pass) does the two
   hard fixes at once: it **scales** the model down to fit the bed (default: 200mm
   longest side — pick a display scale) and gives every surface **real wall
   thickness** (default 1.6mm), then closes it into a **watertight** solid.
   *Verified: an 8m single-sided house shell → a watertight 200mm desk model with
   1.6mm walls.*
4. **Slice and print** as normal — the safety gate still checks temps and the
   220×220×250 volume.

If a particular export is especially broken, **⚙ make printable** (voxel remesh) is
the heavier rescue — it welds everything into one solid at the cost of fine detail.

## Picking a scale for the bed

Buildings are modeled at real size; the bed is 220×220×250mm. Common architectural
model scales and what fits:

| Scale | A 12m-wide house becomes | Fits the bed? |
|---|---|---|
| 1:100 | 120mm | yes, roomy |
| 1:150 | 80mm | yes |
| 1:200 | 60mm | yes, small |
| 1:87 (HO) | 138mm | yes |
| 1:50 | 240mm | no — too wide, split it |

The 🏠 solidify step auto-scales to ~200mm; for a specific scale, use the **scale ×**
field (it understands `1:100`, `1/150`, etc.). A house bigger than the bed at your
chosen scale needs **splitting** into sections with alignment pins — a planned
feature (the `split_plane`/`peg` helpers already exist for it).

## Realtor use cases, ranked by practicality

1. **A physical model of a listing** — from the client's/builder's Chief Architect
   or CAD plan (highest fidelity). The workflow above. Great for a listing
   presentation or a **closing gift** (a model of the home they bought).
2. **Lot / terrain models** — high value for land, waterfront, and hillside
   listings. Path: pull free USGS 3DEP elevation data for the parcel, run it
   through TouchTerrain (free, web) to an STL, import and print. A future in-studio
   feature; usable today via the TouchTerrain website.
3. **Neighborhood / site tiles** — OpenStreetMap building footprints + heights
   turned into a printable tile (tools like Map2Model / OSM2World output STL/3MF,
   both importable). Future integration.
4. **From photos** — the existing 📷→3D (Tripo) and blueprint→3D paths already give
   a rough massing model when there's no CAD file, good for a decorative piece (not
   a dimensioned model).

## What's next (not yet built)

- **Split-to-fit**: auto-cut a model bigger than the bed into aligned tiles/floors
  with locating pins.
- **A base/foundation plate** option under a solidified building.
- **A "Print a Property" guided flow** with the three entry points (have a plan /
  terrain from address / neighborhood tile).
- Optional: `rhino3dm` for Rhino `.3dm`, `assimp` for 3DS/X3D if ever needed.
