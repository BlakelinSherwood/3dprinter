#!/usr/bin/env python
"""Part Studio: local web UI for the model -> slice -> upload pipeline.

Stdlib only (runs in .venv-cad, which has cadquery but no web framework).
Serves a Three.js viewer and a small JSON API:

  GET  /api/models            models/*.py with their build() parameters
  POST /api/generate          {model, params} -> STL + bbox/volume
  POST /api/slice             {model} -> runs test-slice.sh (safety-gated)
  POST /api/upload            {model} -> re-checks G-code, then uploads

Printing is deliberately absent: uploads are select=false/print=false via the
existing script, and there is no endpoint that can start a print.
"""
import base64
import glob
import os
import urllib.error
import urllib.parse
import urllib.request
import importlib.util
import inspect
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MODELS = REPO / "models"
OUTPUT = REPO / "output"
STATIC = Path(__file__).resolve().parent / "static"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".stl": "model/stl",
    ".json": "application/json",
}

_module_cache = {}   # path -> (mtime, module)
_generate_lock = threading.Lock()   # OCC is not thread-safe
_codegen_lock = threading.Lock()    # one description job at a time
_jobs = {}                          # job id -> {status, result?, error?}


def start_job(fn, *args):
    """Run fn in a worker thread; the client polls /api/job for the outcome.
    Long codegen can't live inside one HTTP request - proxies kill idle
    connections after a couple of minutes."""
    import uuid
    jid = uuid.uuid4().hex[:12]
    _jobs[jid] = {"status": "running", "started": time.time()}
    def run():
        try:
            _jobs[jid]["result"] = fn(*args)
            _jobs[jid]["status"] = "done"
        except Exception:
            _jobs[jid]["error"] = traceback.format_exc()
            _jobs[jid]["status"] = "error"
    threading.Thread(target=run, daemon=True).start()
    return {"job": jid}

PLATE_X, PLATE_Y, PLATE_Z = 220.0, 220.0, 250.0


def find_claude():
    """The Claude Code CLI; PATH first, then the usual install locations."""
    p = shutil.which("claude")
    if p:
        return p
    candidates = glob.glob(str(Path.home() / ".nvm/versions/node/*/bin/claude"))
    candidates += ["/usr/local/bin/claude", "/opt/homebrew/bin/claude"]
    for c in sorted(candidates, reverse=True):
        if Path(c).is_file():
            return c
    raise RuntimeError("claude CLI not found - install Claude Code or add it to PATH")


def design_rules():
    f = Path(__file__).resolve().parent / "design_rules.md"
    return f.read_text() if f.is_file() else ""


MODEL_CONTRACT = """You write parametric 3D models as single-file CadQuery scripts.

The file contract (follow it exactly):
- Very first line: `# model: snake_case_name` naming the part (short, specific).
- Then a module docstring whose FIRST line is a <=70 char summary of the part.
- `import cadquery as cq` (plus Python stdlib only; nothing else).
- Define `build(...)` where every parameter is a keyword with a NUMERIC
  default in millimetres, returning a cq.Workplane solid. 3-6 parameters,
  each one something a user would meaningfully tweak.
- End with the standard runner:

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")

- No file I/O outside that runner, no network, no prints during build().
- Model the part already oriented for printing per the design rules below,
  bottom face on the z=0 plane.
- CONTOURS ARE MANDATORY for anything that is curved in real life (vehicles,
  animals, furniture, consumer products, organic shapes). Box-and-cylinder
  massing is only acceptable for parts that truly are prismatic (brackets,
  plates, hardware). Your primary surfacing tools, with working idioms:
  * Spline side-profile, then extrude or cut with it:
      profile = (cq.Workplane("XZ").spline([(0,0),(l*0.25,h*0.85),
                 (l*0.6,h),(l,h*0.4)]).lineTo(l,0).close().extrude(w))
  * Loft between 2-4 cross-sections for bodies, hulls, handles:
      body = (cq.Workplane("XY").ellipse(a1,b1)
              .workplane(offset=h1).ellipse(a2,b2)
              .workplane(offset=h2).ellipse(a3,b3).loft(ruled=False))
  * revolve() for wheels, domes, vases; sweep() for rails, pipes, rims;
    shell() to hollow; .mirror() to keep symmetric halves consistent.
  * Wheel arches and cutouts: cut with cylinders, then fillet the cut rims.
  * LARGE fillets (several mm at full scale) on body masses are what reads
    as "designed"; select the edges precisely (e.g. "|Y", ">Z") and fillet
    the biggest masses first, before small features are added.

# Real-world size (mandatory)
- Model real-world subjects at their TRUE full size in mm: a pickup truck is
  ~5000mm long, a person ~1750mm tall, a house ~8000mm wide. NEVER pre-scale
  the geometry - the studio applies printing scale afterwards, so a "1/64
  scale car" request still gets modeled at ~5000mm and the studio sets 1/64.
- Functional parts that print at working size (hooks, clips, coasters,
  brackets, organizers) ARE their full size - model them at print dimensions.

# Design quality (mandatory)
- Aim for the detail of a well-designed store-bought product, not a minimal
  primitive. A plain disc or box is only acceptable if the user asks for
  minimal/plain.
- Include the functional micro-detail a good industrial designer would add:
  chamfered or filleted openings, grip ribs or knurl-like patterns where a
  hand touches, drainage/relief where liquid could pool, recessed bottoms so
  large faces do not sit dead flat, gentle crowns or steps instead of large
  featureless planes.
- Decorative patterns (radial grooves, concentric rings, hex or slot grids)
  are welcome where they suit the object - sized to print: >= 0.8mm wide,
  >= 0.6mm deep/tall features only.
- Expose 4-8 meaningful parameters.
"""

OUTPUT_RULE = ("\nReply with ONLY the complete Python source file. "
               "No markdown fences, no commentary before or after.")


def call_claude(prompt, allow_read=False, model="sonnet"):
    scratch = tempfile.mkdtemp(prefix="studio-codegen-")
    cmd = [find_claude(), "-p", prompt, "--model", model, "--output-format", "text"]
    if allow_read:   # let the CLI view an uploaded reference image
        cmd += ["--allowedTools", "Read"]
    p = subprocess.run(
        cmd,
        cwd=scratch, stdin=subprocess.DEVNULL, capture_output=True, text=True,
        timeout=1500,  # a full contoured rewrite can exceed 20 minutes
    )
    if p.returncode != 0:
        out = (p.stderr or "") + (p.stdout or "")
        if "Not logged in" in out or "/login" in out:
            raise RuntimeError(
                "The claude CLI is not logged in, so description-to-model is "
                "unavailable. One-time fix: open Terminal, run `claude`, then "
                "type /login and finish the browser sign-in. Everything else "
                "in Part Studio works without it.")
        raise RuntimeError(f"claude CLI failed: {out[-800:]}")
    return p.stdout.strip()


def extract_code(reply):
    m = re.search(r"```(?:python)?\s*\n(.*?)```", reply, re.S)
    code = (m.group(1) if m else reply).strip()
    if "def build" not in code or "import cadquery" not in code:
        raise ValueError("reply did not contain a valid model file:\n" + reply[:600])
    return code + "\n"


def slugify(text):
    words = re.findall(r"[a-z0-9]+", text.lower())[:4]
    return "_".join(words) or "part"


IMAGE_EXTS = {".png": ".png", ".jpg": ".jpg", ".jpeg": ".jpg",
              ".webp": ".webp", ".gif": ".gif"}

IMPORTS = MODELS / "imports"


def read_stl(path):
    """Load an STL (binary or ASCII) as an (n,3,3) float array of triangles."""
    import numpy as np
    data = Path(path).read_bytes()
    if len(data) >= 84:
        n = int.from_bytes(data[80:84], "little")
        if len(data) == 84 + 50 * n:   # well-formed binary STL
            dt = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)),
                           ("attr", "<u2")])
            rec = np.frombuffer(data, dtype=dt, count=n, offset=84)
            return rec["v"].astype(np.float64).copy()
    text = data.decode("ascii", errors="ignore")
    verts = re.findall(
        r"vertex\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)", text)
    if not verts or len(verts) % 3:
        raise ValueError("not a valid STL file")
    arr = np.array(verts, dtype=np.float64).reshape(-1, 3, 3)
    return arr


def write_stl(path, tris):
    import numpy as np
    n = len(tris)
    dt = np.dtype([("normal", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")])
    rec = np.zeros(n, dtype=dt)
    a = tris[:, 1] - tris[:, 0]
    b = tris[:, 2] - tris[:, 0]
    nrm = np.cross(a, b)
    lens = np.linalg.norm(nrm, axis=1, keepdims=True)
    lens[lens == 0] = 1.0
    rec["normal"] = (nrm / lens).astype(np.float32)
    rec["v"] = tris.astype(np.float32)
    with open(path, "wb") as f:
        f.write(b"part-studio import".ljust(80, b"\0"))
        f.write(n.to_bytes(4, "little"))
        f.write(rec.tobytes())


def mesh_volume(tris):
    import numpy as np
    v0, v1, v2 = tris[:, 0], tris[:, 1], tris[:, 2]
    return abs(np.einsum("ij,ij->i", v0, np.cross(v1, v2)).sum()) / 6.0


MESH_EXTS = {".stl", ".glb", ".gltf", ".obj", ".ply", ".3mf", ".off"}


def save_import(name, data_b64):
    data = base64.b64decode(data_b64)
    if len(data) > 60 * 1024 * 1024:
        raise ValueError("mesh too large (60MB max)")
    ext = Path(name).suffix.lower()
    if ext not in MESH_EXTS:
        raise ValueError(f"unsupported mesh type {ext or '(none)'} - "
                         f"accepted: {', '.join(sorted(MESH_EXTS))}")
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(name).stem).strip("_") or "import"
    IMPORTS.mkdir(parents=True, exist_ok=True)
    path = IMPORTS / f"{stem}.stl"
    if ext == ".stl":
        path.write_bytes(data)
        read_stl(path)   # validate now so a bad file fails at upload time
    else:
        # GLB and friends (Tripo/Meshy web downloads, Sketchfab...) convert
        # through trimesh into one STL.
        import trimesh
        tmp = OUTPUT / f"_convert{ext}"
        OUTPUT.mkdir(exist_ok=True)
        tmp.write_bytes(data)
        scene = trimesh.load(str(tmp), force=None)
        mesh = (scene.to_mesh() if hasattr(scene, "to_mesh")
                else scene.dump(concatenate=True) if isinstance(scene, trimesh.Scene)
                else scene)
        if mesh.is_empty:
            raise ValueError(f"no geometry found in {name}")
        mesh.export(str(path))
        tmp.unlink(missing_ok=True)
    return stem


def rotation_matrix(rot):
    import numpy as np
    rx, ry, rz = [math_radians(a) for a in rot]
    cx, sx = np_cos_sin(rx)
    cy, sy = np_cos_sin(ry)
    cz, sz = np_cos_sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return Rz @ Ry @ Rx


def math_radians(deg):
    import math
    return math.radians(deg)


def np_cos_sin(rad):
    import math
    return math.cos(rad), math.sin(rad)


def norm_rot(rot):
    rot = [float(a) % 360 for a in (rot or [0, 0, 0])]
    return rot if any(rot) else None


def finish_mesh_tris(tris, name, scale, scale_label, rot, warnings):
    """Rotate/scale/bed-drop a triangle soup, write it, and report like a
    parametric generate() would."""
    if rot:
        tris = tris @ rotation_matrix(rot).T
        warnings.append(f"rotated {'/'.join(f'{a:g}' for a in rot)} deg")
    if scale != 1.0:
        tris = tris * scale
        warnings.append(f"scaled {scale_label} = x{scale:g}")
    zmin = tris[:, :, 2].min()
    if abs(zmin) > 1e-4:
        tris[:, :, 2] -= zmin
    lo = tris.reshape(-1, 3).min(axis=0)
    hi = tris.reshape(-1, 3).max(axis=0)
    dims = hi - lo
    if dims[0] > PLATE_X or dims[1] > PLATE_Y:
        warnings.append(f"TOO BIG for the 220x220 plate: {dims[0]:.0f} x {dims[1]:.0f} - will not print")
    if dims[2] > PLATE_Z:
        warnings.append(f"TOO TALL for 250mm height: {dims[2]:.0f} - will not print")
    if min(dims) < 2.0:
        warnings.append(f"very small ({min(dims):.1f}mm min dimension) - unlikely to print")
    if dims[2] > 30 and dims[2] > 2.5 * min(dims[0], dims[1]):
        warnings.append("tall part with a small footprint - consider enabling Brim")
    OUTPUT.mkdir(exist_ok=True)
    write_stl(OUTPUT / f"{name}.stl", tris)
    support = support_analysis(OUTPUT / f"{name}.stl")
    if support["needs_supports"]:
        warnings.append("may need supports (" + "; ".join(support["reasons"]) + ") - the slicer decides and will auto-enable them if required")
    return {
        "stl": f"/output/{name}.stl",
        "bbox": [round(float(d), 2) for d in dims],
        "volume_cm3": round(mesh_volume(tris) / 1000.0, 2),
        "scale": scale,
        "scale_label": scale_label,
        "support": support,
        "warnings": warnings,
    }


def auto_orient(name):
    """Tweaker-3: find the orientation with the least support need and store
    it beside the import; generate_import applies it from then on. Calling
    again clears it (toggle)."""
    src = IMPORTS / f"{name}.stl"
    if not src.is_file():
        raise ValueError("auto-orient works on imported meshes")
    marker = IMPORTS / f"{name}.orient.json"
    if marker.is_file():
        marker.unlink()
        result = generate(name, {})
        result["model"] = name
        result["oriented"] = False
        return result
    import numpy as np
    from tweaker3.MeshTweaker import Tweak
    import trimesh
    m = trimesh.load(str(src), force="mesh")
    tris = m.triangles
    if len(tris) > 300_000:      # tweaker is O(n) but python-slow; subsample
        idx = np.linspace(0, len(tris) - 1, 300_000).astype(int)
        tris = tris[idx]
    tw = Tweak(tris.reshape(-1, 3), extended_mode=True, verbose=False,
               min_volume=True)
    marker.write_text(json.dumps({
        "matrix": np.array(tw.matrix).tolist(),
        "unprintability": float(tw.unprintability),
    }))
    result = generate(name, {})
    result["model"] = name
    result["oriented"] = True
    result["unprintability"] = round(float(tw.unprintability), 2)
    return result


def generate_import(name, scale, scale_label, rot=None):
    import numpy as np
    tris = read_stl(IMPORTS / f"{name}.stl")
    warnings = ["imported mesh - scale and slice only, no parameters"]
    orient_marker = IMPORTS / f"{name}.orient.json"
    if orient_marker.is_file():
        try:
            M = np.array(json.loads(orient_marker.read_text())["matrix"])
            tris = tris @ M.T
            warnings.append("auto-oriented for least support")
        except Exception:
            pass
    return finish_mesh_tris(tris, name, scale, scale_label, rot, warnings)


def save_reference_image(image):
    """Persist an uploaded reference photo for the codegen CLI to Read."""
    data = base64.b64decode(image["data"])
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("image too large (10MB max)")
    ext = IMAGE_EXTS.get(Path(image.get("name", "photo.png")).suffix.lower())
    if not ext:
        raise ValueError("unsupported image type (png/jpg/webp/gif)")
    uploads = REPO / "uploads"
    uploads.mkdir(exist_ok=True)
    path = uploads / f"ref-{int(time.time())}{ext}"
    path.write_bytes(data)
    return path


MESH_MOD_CONTRACT = """You modify existing 3D mesh files (downloaded STLs) with
python. Write a single-file model script with this exact structure:

- First line: `# model: <base>_mod` (keep the _mod suffix).
- Module docstring, first line <=70 chars describing the modification.
- Imports: `import cadquery as cq` and `from _meshlib import load_import,
  cq_solid, difference, union, intersection` (only what you use).
- `def build(...)` with 1-6 NUMERIC keyword parameters in millimetres,
  returning a trimesh mesh:
    * start from `m = load_import("<base>")` - the unmodified downloaded mesh
    * build tool solids with CadQuery (`cq_solid(cq.Workplane("XY")...)`)
    * combine with difference/union/intersection (manifold engine, watertight)
- End with:

if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    build().export(out)

- The mesh's own coordinates are what the user sees; probe nothing, trust the
  stated coordinates. Keep tools generously sized (extend cuts a few mm past
  surfaces) so booleans are robust.
- Splitting and joints, all from _meshlib:
  * split_plane(mesh, point, normal) -> (kept, removed): capped watertight
    halves. Use for turret rings, hull sections, wing joints.
  * peg(diameter, length) -> cylinder tool: union for the peg, and subtract
    peg(d, l, clearance=...) for the socket. MEASURED on this printer:
    0.4 = press fit, 0.5 = moves with drag, 0.6 = free spin (use 0.6 for
    turrets/axles). Below 0.4 will not assemble.
    Position with .apply_translation([x, y, z]).
  * parts(a, b, ...) -> lays the pieces side by side on the plate as ONE
    printable set; return it from build() when the edit splits the model.
- CRITICAL: cq extrude() goes along the workplane NORMAL - "XY" extrudes
  toward +Z, "XZ" toward -Y, "YZ" toward +X. The safest pattern is to build
  every tool on Workplane("XY") at the origin and move it into place with
  .rotate() and .translate(), then sanity-check that the tool's coordinate
  span overlaps the mesh's bounding box in all three axes.
"""


SCALE_MENTION_RE = re.compile(r"\b1\s*[/:]\s*(\d{1,4})\b")


def support_analysis(stl_path):
    """Decide whether a sliced part needs supports, from the geometry itself.

    Two independent signals:
    - floating bodies: connected components whose lowest point never reaches
      the bed (a rotated star's arms, a figurine's outstretched hand)
    - steep overhang area: downward-facing surface steeper than 45 degrees
      that is not the first layer
    Returns a machine-usable verdict plus human-readable reasons.
    """
    try:
        import numpy as np
        import trimesh
        m = trimesh.load(str(stl_path), force="mesh")
        lo_z = float(m.bounds[0][2])
        reasons = []
        # A region only truly floats if there is AIR all the way down: parts
        # resting on other parts (print-in-place wheels on cradles, hinge
        # pins on chassis) are supported by design. Ray-cast straight down
        # from each candidate and measure the drop.
        def drop_to_ground(points):
            pts = np.asarray(points, dtype=float)
            hits = np.full(len(pts), np.inf)
            origins = pts + [0, 0, -0.05]
            locs, ray_idx, _ = m.ray.intersects_location(
                origins, np.tile([0.0, 0.0, -1.0], (len(pts), 1)),
                multiple_hits=False)
            for l, r in zip(locs, ray_idx):
                hits[r] = min(hits[r], origins[r][2] - l[2])
            bed_drop = pts[:, 2] - lo_z
            return np.minimum(hits, bed_drop)

        floating = 0
        for body in m.split(only_watertight=False):
            bz = float(body.bounds[0][2])
            if bz <= lo_z + 0.4:
                continue        # touches the bed
            low_pts = body.vertices[body.vertices[:, 2] < bz + 0.5][:40]
            if len(low_pts) and float(np.min(drop_to_ground(low_pts))) > 1.0:
                floating += 1
        if floating:
            reasons.append(f"{floating} loose region" + ("s" if floating > 1 else ""))
        # Steep unsupported ceiling: downward faces above the first layer
        # with a long empty drop beneath them.
        n = m.face_normals
        tri_z = m.triangles[:, :, 2]
        steep = (n[:, 2] < -0.72) & (tri_z.max(axis=1) > lo_z + 0.35)
        area = 0.0
        idx = np.flatnonzero(steep)
        if len(idx):
            if len(idx) > 300:
                idx = idx[np.linspace(0, len(idx) - 1, 300).astype(int)]
            centers = m.triangles[idx].mean(axis=1)
            drops = drop_to_ground(centers)
            unsupported = drops > 1.0
            # scale the sampled verdict back to the full steep area
            frac = float(unsupported.mean()) if len(drops) else 0.0
            area = float(m.area_faces[steep].sum()) * frac
        if area > 150.0:
            reasons.append(f"~{area/100:.1f}cm2 of overhang with nothing beneath")
        return {"needs_supports": bool(floating or area > 150.0),
                "floating_bodies": floating,
                "overhang_cm2": round(area / 100.0, 1),
                "reasons": reasons}
    except Exception:
        return {"needs_supports": False, "floating_bodies": 0,
                "overhang_cm2": 0.0, "reasons": [],
                "note": "analysis failed - relying on the slicer's own check"}


def blockiness(stl_path):
    """Fraction of surface area lying in flat axis-aligned planes."""
    try:
        import numpy as np
        tris = read_stl(stl_path)
        n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        areas = np.linalg.norm(n, axis=1) / 2.0
        total = areas.sum()
        if total <= 0:
            return None
        unit = n / (2.0 * areas[:, None] + 1e-12)
        aligned = (np.abs(unit) > 0.999).any(axis=1)
        return float(areas[aligned].sum() / total)
    except Exception:
        return None


def render_views(name):
    """Render the model's current STL from three angles so the refiner can
    actually see its own work. Returns PNG paths."""
    import numpy as np
    import trimesh
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    mesh = trimesh.load(str(OUTPUT / f"{name}.stl"), force="mesh")
    v, f = mesh.vertices, mesh.faces
    ext = v.max(axis=0) - v.min(axis=0)
    out = REPO / "uploads"
    out.mkdir(exist_ok=True)
    paths = []
    for label, elev, azim in (("iso", 22, -55), ("front", 4, -90), ("side", 4, 0)):
        fig = plt.figure(figsize=(5.5, 4.2), dpi=100)
        ax = fig.add_subplot(projection="3d")
        ax.plot_trisurf(v[:, 0], v[:, 1], v[:, 2], triangles=f,
                        color=(0.55, 0.66, 0.82), edgecolor="none", shade=True)
        ax.set_box_aspect(tuple(np.maximum(ext, 1e-6)))
        ax.view_init(elev, azim)
        ax.set_axis_off()
        p = out / f"render-{name}-{label}.png"
        fig.savefig(p, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        paths.append(str(p))
    return paths


def refine(name, notes=None):
    """Show the model's renders to the generator and have it rewrite the file
    with more convincing detail. One round per call."""
    path = MODELS / f"{name}.py"
    if not path.is_file():
        raise ValueError("only parametric models can be refined - imports are "
                         "fixed meshes (edit them by description instead)")
    if not (OUTPUT / f"{name}.stl").is_file():
        generate(name, {})
    original = path.read_text()
    views = render_views(name)
    task = (f"You previously wrote the CadQuery model below. Rendered previews "
            f"of exactly what it produces are at these paths - use the Read "
            f"tool to look at ALL of them before anything else:\n"
            + "\n".join(views) +
            f"\n\nCritique your own output honestly: where does it look "
            f"crude, blocky, mis-proportioned or underdetailed for what it is "
            f"meant to be? Then rewrite the COMPLETE file with meaningfully "
            f"richer, more convincing, still-printable detail. Keep the same "
            f"`# model:` name, keep full-size real-world dimensions, keep or "
            f"extend the parameters.")
    if notes:
        task += f"\n\nThe user specifically wants: {notes}"
    task += f"\n\nCurrent file:\n{original}"
    prompt = (MODEL_CONTRACT + "\n# Printer design rules (mandatory)\n"
              + design_rules() + "\n# Task\n" + task + OUTPUT_RULE)
    with _codegen_lock:
        last_err = None
        for attempt in (1, 2):
            try:
                reply = call_claude(prompt, allow_read=True, model="opus")
            except subprocess.TimeoutExpired:
                raise RuntimeError("refine ran past the 25-minute limit - try "
                                   "again with specific notes about what to "
                                   "improve")
            code = extract_code(reply)
            hist = MODELS / ".history"
            hist.mkdir(exist_ok=True)
            (hist / f"{name}-{int(time.time())}.py").write_text(path.read_text())
            path.write_text(code)
            try:
                result = generate(name, {})
                result["model"] = name
                result["attempts"] = attempt
                return result
            except Exception:
                last_err = traceback.format_exc()
                prompt += (f"\n\nYour previous file failed when run:"
                           f"\n{last_err[-1500:]}\nOutput the complete "
                           f"corrected file.{OUTPUT_RULE}")
        path.write_text(original)
        raise RuntimeError(f"refine failed twice; last error:\n{last_err}")


def describe(mode, name, description, image=None, focus=None):
    """Natural-language build/edit. Writes models/<name>.py after validating
    that the generated file actually loads and builds."""
    rules = design_rules()
    image_path = save_reference_image(image) if image else None
    mesh_base = None
    if mode == "edit":
        path = MODELS / f"{name}.py"
        if not path.is_file():
            if (IMPORTS / f"{name}.stl").is_file():
                mesh_base = name
            else:
                raise FileNotFoundError(f"no such model: {name}")
        if mesh_base:
            original = None
            tris = read_stl(IMPORTS / f"{name}.stl")
            lo = tris.reshape(-1, 3).min(axis=0)
            hi = tris.reshape(-1, 3).max(axis=0)
            task = (f"Modify the downloaded mesh '{name}' per this request: "
                    f"{description}\n\nThe mesh's bounding box runs from "
                    f"({lo[0]:.1f}, {lo[1]:.1f}, {lo[2]:.1f}) to "
                    f"({hi[0]:.1f}, {hi[1]:.1f}, {hi[2]:.1f}) mm.")
            if focus and focus.get("point"):
                # The click is reported in bed-dropped coordinates; the raw
                # mesh file the generated code loads keeps its original Z.
                fx, fy, fz = (float(v) for v in focus["point"])
                focus = dict(focus, point=[fx, fy, fz + float(lo[2])])
        else:
            original = path.read_text()
            task = (f"Modify this existing model per the request below. Keep the same "
                    f"`# model:` name and overall structure; change only what the "
                    f"request implies.\n\nRequest: {description}\n\n"
                    f"Current file:\n{original}")
    else:
        original = None
        task = f"Write a new model for this request: {description}"

    if mode == "edit" and focus and focus.get("point"):
        x, y, z = (round(float(v), 2) for v in focus["point"])
        region = focus.get("region") or "that spot"
        task += (f"\n\nThe user clicked a specific spot on the current model: "
                 f"({x}, {y}, {z}) mm in the model's own coordinates - {region}. "
                 f"Apply the requested change to the feature at or nearest this "
                 f"spot, and leave the rest of the geometry unchanged.")
    if image_path:
        task += (f"\n\nReference photo: the user uploaded an image at "
                 f"{image_path}. Use the Read tool to view it FIRST. Design a "
                 f"printable interpretation of the pictured object or shape - "
                 f"match its proportions and character, simplified for FDM "
                 f"printing. Dimensions in the text description take "
                 f"precedence; otherwise pick sensible sizes in mm.")

    task += ("\n\nIf the request gives dimensions in inches or fractions "
             "(1/4\", 2in), convert to millimetres (25.4 mm per inch) - the "
             "code and all parameters stay in mm.")
    contract = MODEL_CONTRACT
    if mesh_base:
        contract = MESH_MOD_CONTRACT.replace("<base>", mesh_base)
    prompt = (contract + "\n# Printer design rules (mandatory)\n" + rules
              + "\n# Task\n" + task + OUTPUT_RULE)

    with _codegen_lock:
        last_err = None
        for attempt in (1, 2):
            try:
                reply = call_claude(prompt, allow_read=image_path is not None,
                                    model="opus")
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    "generation ran past the 25-minute limit. Very high detail "
                    "requests can do this - try describing the shape more "
                    "specifically, or build a simpler base and add detail with "
                    "focused edits.")
            code = extract_code(reply)
            if mode == "edit":
                out_name = f"{name}_mod" if mesh_base else name
            else:
                m = re.match(r"#\s*model:\s*([a-zA-Z0-9_]+)", code)
                out_name = (m.group(1).lower() if m else slugify(description))[:40]
            path = MODELS / f"{out_name}.py"
            if path.is_file():   # keep every overwritten version
                hist = MODELS / ".history"
                hist.mkdir(exist_ok=True)
                (hist / f"{out_name}-{int(time.time())}.py").write_text(path.read_text())
            path.write_text(code)
            try:
                result = generate(out_name, {})
                result["model"] = out_name
                result["attempts"] = attempt
                m = SCALE_MENTION_RE.search(description)
                if m:
                    result["suggested_scale"] = f"1/{m.group(1)}"
                return result
            except Exception:
                last_err = traceback.format_exc()
                prompt += (f"\n\nYour previous file failed when run:\n{last_err[-1500:]}"
                           f"\nOutput the complete corrected file.{OUTPUT_RULE}")
        # both attempts failed - put things back the way they were
        if mode == "edit" and original is not None:
            path.write_text(original)
        elif path.is_file():
            path.unlink()
        raise RuntimeError(f"model generation failed twice; last error:\n{last_err}")


def load_model(path: Path):
    if str(MODELS) not in sys.path:
        sys.path.insert(0, str(MODELS))   # generated mods import _meshlib
    mtime = path.stat().st_mtime
    cached = _module_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    spec = importlib.util.spec_from_file_location(f"model_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _module_cache[str(path)] = (mtime, mod)
    return mod


def model_params(mod):
    """Numeric keyword parameters of build(), with their defaults."""
    sig = inspect.signature(mod.build)
    out = []
    for name, p in sig.parameters.items():
        if isinstance(p.default, (int, float)) and not isinstance(p.default, bool):
            out.append({"name": name, "default": p.default})
    return out


def as_shape(obj):
    return obj.val() if hasattr(obj, "val") else obj


def list_models():
    entries = []   # (mtime, item) - newest first so the default selection is
    for f in (IMPORTS.glob("*.stl") if IMPORTS.is_dir() else []):
        entries.append((f.stat().st_mtime,
                        {"name": f.stem, "summary": "imported mesh",
                         "params": [], "imported": True}))
    for f in MODELS.glob("*.py"):
        if f.stem.startswith("_"):
            continue
        try:
            mod = load_model(f)
            doc = (mod.__doc__ or "").strip().splitlines()
            hist = MODELS / ".history"
            entries.append((f.stat().st_mtime, {
                "name": f.stem,
                "summary": doc[0] if doc else "",
                "params": model_params(mod),
                "has_history": bool(hist.is_dir() and list(hist.glob(f"{f.stem}-*.py"))),
            }))
        except Exception:
            entries.append((f.stat().st_mtime,
                            {"name": f.stem, "summary": "LOAD ERROR",
                             "params": [], "error": traceback.format_exc()}))
    entries.sort(key=lambda e: -e[0])   # the thing worked on most recently
    return [item for _, item in entries]


def parse_scale(value):
    """Accept decimals and hobby-scale ratios: 1, 0.5, 2, "1/64", "1:55", "150%"."""
    if value is None:
        return 1.0, "1"
    text = str(value).strip().lower().rstrip("x").strip() or "1"
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[/:]\s*(\d+(?:\.\d+)?)", text)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        if den == 0:
            raise ValueError("scale denominator is zero")
        return num / den, f"{m.group(1)}/{m.group(2)}"
    if text.endswith("%"):
        return float(text[:-1]) / 100.0, text
    return float(text), text


def generate(name, params, scale=1.0, rot=None):
    import cadquery as cq
    scale_f, scale_label = parse_scale(scale)
    rot = norm_rot(rot)
    path = MODELS / f"{name}.py"
    if not path.is_file():
        if (IMPORTS / f"{name}.stl").is_file():
            if not 0.001 <= scale_f <= 100:
                raise ValueError(f"scale {scale_label} outside 0.001-100")
            with _generate_lock:
                return generate_import(name, scale_f, scale_label, rot)
        raise FileNotFoundError(f"no such model: {name}")
    mod = load_model(path)
    kwargs = {k: float(v) for k, v in (params or {}).items()}
    scale, scale_label = scale_f, scale_label
    if not 0.001 <= scale <= 100:
        raise ValueError(f"scale {scale_label} ({scale:g}) outside 0.001-100")
    warnings = []
    with _generate_lock:
        built = mod.build(**kwargs)
        if type(built).__module__.split(".")[0] == "trimesh":
            import numpy as np
            tris = np.array(built.triangles, dtype=float)   # copy: trimesh caches are read-only
            return finish_mesh_tris(tris, name, scale, scale_label, rot, [])
        shape = as_shape(built)
        if rot:
            axes = ((1, 0, 0), (0, 1, 0), (0, 0, 1))
            for axis, ang in zip(axes, rot):
                if ang:
                    shape = shape.rotate(cq.Vector(0, 0, 0), cq.Vector(*axis), ang)
            warnings.append(f"rotated {'/'.join(f'{a:g}' for a in rot)} deg")
        if scale != 1.0:
            shape = shape.scale(scale)
            warnings.append(f"scaled {scale_label} = x{scale:g} (params stay in real mm)")
        # Output prep: the slicer expects the part resting on the bed plane.
        bb = shape.BoundingBox()
        if abs(bb.zmin) > 1e-4:
            shape = shape.translate(cq.Vector(0, 0, -bb.zmin))
            if scale == 1.0:
                warnings.append(f"model was {bb.zmin:+.2f}mm off the bed - dropped to z=0")
        OUTPUT.mkdir(exist_ok=True)
        stl = OUTPUT / f"{name}.stl"
        cq.exporters.export(shape, str(stl), tolerance=0.01, angularTolerance=0.1)
    bb = shape.BoundingBox()
    # Too big: hard printer limits.
    if bb.xlen > PLATE_X or bb.ylen > PLATE_Y:
        warnings.append(f"TOO BIG for the 220x220 plate: {bb.xlen:.0f} x {bb.ylen:.0f} - will not print")
    elif bb.xlen > 200 or bb.ylen > 200:
        warnings.append("close to the plate edge - prefer <= 200mm in X/Y")
    if bb.zlen > PLATE_Z:
        warnings.append(f"TOO TALL for 250mm height: {bb.zlen:.0f} - will not print")
    if bb.zlen > 30 and bb.zlen > 2.5 * min(bb.xlen, bb.ylen):
        warnings.append("tall part with a small footprint - consider enabling Brim")
    blocky = blockiness(OUTPUT / f"{name}.stl")
    if blocky is not None and blocky > 0.80:
        warnings.append(
            f"{int(blocky*100)}% of the surface is flat axis-aligned planes - "
            f"reads as blocky; use splines/lofts/large fillets for curved "
            f"subjects")
    # Too small: printability heuristics for a 0.4 nozzle.
    vol, area = shape.Volume(), shape.Area()
    if min(bb.xlen, bb.ylen, bb.zlen) < 2.0:
        warnings.append(f"very small ({min(bb.xlen, bb.ylen, bb.zlen):.1f}mm min dimension) - unlikely to print")
    elif area > 0:
        # For shell-like parts the mean wall is ~2*V/A; below two perimeter
        # widths (0.88mm) the slicer starts dropping walls entirely.
        t_est = 2.0 * vol / area
        if t_est < 0.88:
            warnings.append(
                f"features estimated ~{t_est:.2f}mm thick - below the 0.88mm "
                f"two-perimeter minimum, may slice incompletely")
    support = support_analysis(OUTPUT / f"{name}.stl")
    if support["needs_supports"]:
        warnings.append("may need supports (" + "; ".join(support["reasons"]) + ") - the slicer decides and will auto-enable them if required")
    return {
        "stl": f"/output/{name}.stl",
        "bbox": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
        "volume_cm3": round(vol / 1000.0, 2),
        "scale": scale,
        "scale_label": scale_label,
        "support": support,
        "warnings": warnings,
    }


def run_script(args, timeout=600, extra_env=None):
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    p = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                       timeout=timeout, env=env)
    return p.returncode, (p.stdout + p.stderr).strip()


SETTING_KEYS = {
    "layer_height": {"0.12", "0.16", "0.2", "0.28"},
    "infill_pct": None,     # 5-100
    "supports": None,       # bool -> tree(auto)
    "brim": None,           # bool -> outer_only 5mm
}


# Modern-slicer quality keys, all verified against the installed Orca 2.4.2
# CLI (see docs/research: orca-beta). These are unconditional wins with no
# user decision attached, so every slice gets them - that is what makes the
# studio's default output look a generation newer than stock profiles:
#   scarf seams   - the visible seam line all but disappears on curved walls
#   adaptive Z    - variable layer height where the geometry curves (ZAA)
#   polyholes     - vertical holes print round and to size
#   bridge/seam/flow refinements - cleaner overhangs, corners, small areas
QUALITY_BASE = {
    "seam_slope_type": "external", "seam_slope_conditional": "1",
    "scarf_angle_threshold": "155", "seam_slope_start_height": "10%",
    "seam_slope_min_length": "10", "seam_slope_steps": "10",
    "scarf_joint_speed": "10", "scarf_joint_flow_ratio": "0.98",
    "precise_z_height": "1",
    "zaa_enabled": "1", "zaa_minimize_perimeter_height": "35",
    "zaa_min_z": "0.04",
    "hole_to_polyhole": "1", "hole_to_polyhole_threshold": "0.01",
    "slowdown_for_curled_perimeters": "1",
    "extra_perimeters_on_overhangs": "1",
    "enable_extra_bridge_layer": "apply_to_all",
    "internal_bridge_density": "75%",
    "small_area_infill_flow_compensation": "1",
    "gap_fill_target": "everywhere",
    "wall_sequence": "inner-outer-inner wall",
    "staggered_inner_seams": "1",
    "counterbore_hole_bridging": "sacrificiallayer",
}

INFILL_PATTERNS = {
    "grid": ("grid", "standard"),
    "lightning": ("lightning", "lightning - fastest, uses least material"),
    "gyroid": ("gyroid", "gyroid - strong in every direction"),
    "adaptive": ("adaptivecubic", "adaptive cubic - dense near walls"),
}

FUZZY_KEYS = {
    "fuzzy_skin": "external", "fuzzy_skin_mode": "displacement",
    "fuzzy_skin_noise_type": "voronoi", "fuzzy_skin_thickness": "0.3",
    "fuzzy_skin_point_distance": "0.8", "fuzzy_skin_scale": "0.5",
    "fuzzy_skin_octaves": "4", "fuzzy_skin_persistence": "0.5",
    "fuzzy_skin_first_layer": "0",
}


def build_process_override(settings):
    """Merge per-print settings onto the repo process profile. Returns a path
    to a temp process json, or None when everything is at profile defaults."""
    settings = settings or {}
    base = json.loads((REPO / "profiles/ender3v2/process.json").read_text())
    base.update(QUALITY_BASE)
    changed = ["modern seams/Z"]   # the quality base always applies
    lh = str(settings.get("layer_height") or "").strip()
    if lh and lh in SETTING_KEYS["layer_height"] and lh != str(base.get("layer_height")):
        base["layer_height"] = lh
        changed.append(f"layer {lh}mm")
    infill = settings.get("infill_pct")
    if infill is not None:
        infill = max(0, min(100, int(infill)))
        if f"{infill}%" != base.get("sparse_infill_density"):
            base["sparse_infill_density"] = f"{infill}%"
            changed.append(f"infill {infill}%")
    pattern = str(settings.get("infill_pattern") or "").strip().lower()
    if pattern and pattern in INFILL_PATTERNS and pattern != "grid":
        base["sparse_infill_pattern"] = INFILL_PATTERNS[pattern][0]
        changed.append(f"{pattern} infill")
    if str(settings.get("finish") or "").lower() == "textured":
        base.update(FUZZY_KEYS)
        changed.append("textured surface")
    if settings.get("supports"):
        base["enable_support"] = "1"
        base["support_type"] = "tree(auto)"
        base["support_style"] = "organic"
        base["tree_support_tip_diameter"] = "0.8"
        changed.append("tree supports")
    if settings.get("brim"):
        base["brim_type"] = "outer_only"
        base["brim_width"] = "5"
        changed.append("brim")
    base["name"] = base["name"] + " (override)"
    OUTPUT.mkdir(exist_ok=True)
    path = OUTPUT / "_process_override.json"
    path.write_text(json.dumps(base, indent=2))
    return path, changed


EST_TIME_RE = re.compile(r";\s*(?:total\s+)?estimated printing time.*?=\s*(.+)", re.I)
EST_G_RE = re.compile(r";\s*(?:total\s+)?filament used \[g\]\s*=\s*([\d.]+)", re.I)
EST_MM_RE = re.compile(r";\s*(?:total\s+)?filament used \[mm\]\s*=\s*([\d.]+)", re.I)
EST_CM3_RE = re.compile(r";\s*(?:total\s+)?filament used \[cm3\]\s*=\s*([\d.]+)", re.I)


def parse_time_s(text):
    total, m = 0, re.findall(r"(\d+)\s*([dhms])", text)
    for num, unit in m:
        total += int(num) * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]
    return total or None


def gcode_estimates(gcode_path):
    est = {}
    try:
        src = Path(gcode_path).read_text(errors="replace")
        if m := EST_TIME_RE.search(src):
            est["time_text"] = m.group(1).strip()
            est["time_s"] = parse_time_s(m.group(1))
        if m := EST_G_RE.search(src):
            est["filament_g"] = float(m.group(1))
        if m := EST_CM3_RE.search(src):
            est["filament_cm3"] = float(m.group(1))
        # Orca reports 0.00g when the filament profile carries no density;
        # fall back to volume x PLA density (1.24 g/cm3).
        if not est.get("filament_g") and est.get("filament_cm3"):
            est["filament_g"] = round(est["filament_cm3"] * 1.24, 1)
        if m := EST_MM_RE.search(src):
            est["filament_mm"] = float(m.group(1))
    except OSError:
        pass
    return est


MATERIALS = ("pla", "petg", "tpu")

# Mirror of check-gcode.py's envelopes: (nozzle_min, nozzle_max, bed_max).
MATERIAL_ENV = {"pla": (190, 230, 70), "petg": (220, 260, 90), "tpu": (195, 245, 60)}
ORCA_LIB = Path("/Applications/OrcaSlicer.app/Contents/Resources/profiles")
CUSTOM_FILAMENT = OUTPUT / "_filament_custom.json"
CUSTOM_META = OUTPUT / "_filament_custom.meta.json"


def material_class(text):
    t = (text or "").upper()
    if "TPU" in t or "FLEX" in t:
        return "tpu"
    if "PET" in t:
        return "petg"
    if "PLA" in t:
        return "pla"
    return None


def _find_preset(start, name):
    """Resolve an inherited preset: same dir, then up to the vendor's
    filament/ root, then anywhere under it."""
    for d in (start, *start.parents):
        cand = d / f"{name}.json"
        if cand.is_file():
            return cand
        if d.name == "filament":
            hits = list(d.rglob(f"{name}.json"))
            return hits[0] if hits else None
    return None


def _preset_chain(path, depth=0):
    d = json.loads(path.read_text())
    parent_name = d.get("inherits")
    if depth < 8 and parent_name:
        parent = _find_preset(path.parent, parent_name)
        if parent:
            base = _preset_chain(parent, depth + 1)
            base.update(d)
            return base
    return d


def _first(d, key, cast=float):
    v = d.get(key)
    if isinstance(v, list):
        v = v[0] if v else None
    if v in (None, ""):
        return None
    try:
        return cast(v)
    except (TypeError, ValueError):
        return None


def lookup_local(query):
    tokens = [t for t in re.split(r"\W+", query.lower()) if t]
    if not tokens or not ORCA_LIB.is_dir():
        return None
    hits = [f for f in ORCA_LIB.glob("*/filament/**/*.json")
            if all(t in f.stem.lower() for t in tokens)]
    if not hits:
        return None
    hits.sort(key=lambda f: len(f.stem))   # generic "@base" beats printer variants
    d = _preset_chain(hits[0])
    return {
        "name": hits[0].stem,
        "source": "OrcaSlicer filament library",
        "filament_type": str(_first(d, "filament_type", str) or ""),
        "nozzle": _first(d, "nozzle_temperature"),
        "nozzle_first": _first(d, "nozzle_temperature_initial_layer"),
        "bed": _first(d, "hot_plate_temp"),
        "bed_first": _first(d, "hot_plate_temp_initial_layer"),
        "fan_min": _first(d, "fan_min_speed"),
        "fan_max": _first(d, "fan_max_speed"),
        "volumetric": _first(d, "filament_max_volumetric_speed"),
        "density": _first(d, "filament_density"),
        "alternatives": [n for n in dict.fromkeys(f.stem for f in hits[1:6])
                         if n != hits[0].stem][:3],
    }


LOOKUP_PROMPT = """You are a 3D-printing filament database. For the filament named
below, reply with ONLY a JSON object (no fences, no prose):
{"filament_type": "PLA|PETG|TPU|OTHER", "nozzle": <typical nozzle temp C>,
 "nozzle_first": <first layer nozzle C>, "bed": <bed temp C>,
 "bed_first": <first layer bed C>, "fan_min": <percent>, "fan_max": <percent>,
 "volumetric": <max volumetric speed mm3/s for a stock bowden Ender 3 V2>,
 "density": <g/cm3>, "notes": ["short caveats, if any"]}
Use the manufacturer's published ranges when you know them; otherwise typical
values for that material family. filament_type OTHER for anything that is not
PLA-, PETG- or TPU-family (ABS, ASA, PA, PC...).
Filament: """


def lookup_claude(query):
    reply = call_claude(LOOKUP_PROMPT + query)
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        raise ValueError("lookup returned no JSON: " + reply[:300])
    d = json.loads(m.group(0))
    d["name"] = query
    d["source"] = "Claude lookup (not manufacturer-verified)"
    d.setdefault("alternatives", [])
    return d


def material_lookup(query):
    query = (query or "").strip()
    if not query:
        raise ValueError("type a filament name to look up")
    info = lookup_local(query) or lookup_claude(query)
    cls = material_class(info.get("filament_type")) or material_class(info.get("name"))
    notes = list(info.get("notes") or [])
    if not cls:
        raise ValueError(
            f"{info.get('name', query)}: {info.get('filament_type') or 'unknown type'} "
            f"is not printable on this setup (supported families: PLA, PETG, TPU - "
            f"no enclosure for ABS/ASA, no hardened components for exotics)")
    if re.search(r"\b(cf|gf|carbon|glass)\b", (info.get("name", "") + " "
                 + info.get("filament_type", "")).lower()):
        notes.append("fiber-filled filament wears brass nozzles - fit a hardened "
                     "nozzle before printing this")
    n_lo, n_hi, b_max = MATERIAL_ENV[cls]
    base = json.loads((REPO / f"profiles/ender3v2/filament_{cls}.json").read_text())

    def clamp(v, lo, hi, label):
        if v is None:
            return None
        v = float(v)
        if v < lo or v > hi:
            c = max(lo, min(hi, v))
            notes.append(f"{label} {v:g}C clamped to {c:g}C ({cls.upper()} safety envelope)")
            return c
        return v

    nozzle = clamp(info.get("nozzle"), n_lo, n_hi, "nozzle")
    nozzle_first = clamp(info.get("nozzle_first") or nozzle, n_lo, n_hi, "first-layer nozzle")
    bed = clamp(info.get("bed"), 0, b_max, "bed")
    bed_first = clamp(info.get("bed_first") or bed, 0, b_max, "first-layer bed")

    if nozzle:
        base["nozzle_temperature"] = [str(round(nozzle))]
    if nozzle_first:
        base["nozzle_temperature_initial_layer"] = [str(round(nozzle_first))]
    for key in ("hot_plate_temp", "textured_plate_temp", "cool_plate_temp"):
        if bed:
            base[key] = [str(round(bed))]
        if bed_first:
            base[key + "_initial_layer"] = [str(round(bed_first))]
    for key, val in (("fan_min_speed", info.get("fan_min")),
                     ("fan_max_speed", info.get("fan_max")),
                     ("filament_density", info.get("density"))):
        if val is not None:
            base[key] = [str(val)]
    vol = info.get("volumetric")
    cap = float(base.get("filament_max_volumetric_speed", ["12"])[0])
    if vol is not None:
        base["filament_max_volumetric_speed"] = [str(min(float(vol), cap))]
    base["name"] = f"{info['name']} (lookup)"

    OUTPUT.mkdir(exist_ok=True)
    CUSTOM_FILAMENT.write_text(json.dumps(base, indent=2))
    def effective(key):
        v = base.get(key)
        return round(float(v[0])) if isinstance(v, list) and v else None

    applied = {"nozzle": round(nozzle) if nozzle else effective("nozzle_temperature"),
               "nozzle_first": round(nozzle_first) if nozzle_first else effective("nozzle_temperature_initial_layer"),
               "bed": round(bed) if bed else effective("hot_plate_temp"),
               "bed_first": round(bed_first) if bed_first else effective("hot_plate_temp_initial_layer")}
    meta = {"name": info["name"], "class": cls, "applied": applied,
            "source": info["source"]}
    CUSTOM_META.write_text(json.dumps(meta))
    meta["notes"] = notes
    meta["alternatives"] = info.get("alternatives", [])
    return meta


def custom_material_meta():
    if CUSTOM_META.is_file() and CUSTOM_FILAMENT.is_file():
        return json.loads(CUSTOM_META.read_text())
    return None


def do_slice(name, settings=None):
    stl = OUTPUT / f"{name}.stl"
    if not stl.is_file():
        raise FileNotFoundError("generate the STL first")
    settings = settings or {}
    material = str(settings.get("material") or "pla").lower()
    custom = None
    if material == "custom":
        custom = custom_material_meta()
        if not custom:
            raise ValueError("no looked-up filament stored - use the lookup first")
        material = custom["class"]
    elif material not in MATERIALS:
        raise ValueError(f"unknown material {material}")
    copies = max(1, min(25, int(settings.get("copies") or 1)))
    args = [str(REPO / "scripts/test-slice.sh"), str(stl), name]
    override = build_process_override(settings)
    changed = []
    if override:
        args.append(str(override[0]))
        changed = override[1]
    if custom:
        changed.append(f"filament: {custom['name']} ({material.upper()} rules)")
    elif material != "pla":
        changed.append(material.upper())
    if copies > 1:
        changed.append(f"{copies} copies")
    extra_env = {"MATERIAL": material}
    if custom:
        extra_env["FILAMENT_OVERRIDE"] = str(CUSTOM_FILAMENT)
    if copies > 1:
        extra_env["REPETITIONS"] = str(copies)
    code, out = run_script(args, extra_env=extra_env)
    supports_auto = False
    if code != 0 and not settings.get("supports") and re.search(
            r"floating regions|enable support", out, re.I):
        # The slicer itself is the authority on floating geometry. When it
        # refuses and supports were off, retry once with tree supports -
        # that is the plug-and-play path a novice expects.
        retry = dict(settings)
        retry["supports"] = True
        override = build_process_override(retry)
        args = [str(REPO / "scripts/test-slice.sh"), str(stl), name]
        if override:
            args.append(str(override[0]))
            changed = override[1]
        code, out = run_script(args, extra_env=extra_env)
        if code == 0:
            supports_auto = True
            changed = [c for c in changed if c != "tree supports"]
            changed.append("tree supports AUTO-ENABLED (slicer found floating regions)")
    if code == 0:
        # The upload re-check must verify against the envelope this file was
        # sliced for, not assume PLA.
        (OUTPUT / f"{name}.material").write_text(material)
    result = {"ok": code == 0, "report": out, "overrides": changed,
              "supports_auto": supports_auto,
              "gcode": f"output/{name}.gcode" if code == 0 else None}
    if code == 0:
        result["estimates"] = gcode_estimates(OUTPUT / f"{name}.gcode")
    return result


def do_upload(name):
    gcode = OUTPUT / f"{name}.gcode"
    if not gcode.is_file():
        raise FileNotFoundError("slice first")
    # Independent re-check so a stale or unsafe file can never be uploaded,
    # even if the UI is out of sync with what's on disk. The material marker
    # written at slice time selects the temperature envelope.
    marker = OUTPUT / f"{name}.material"
    material = marker.read_text().strip() if marker.is_file() else "pla"
    if material not in MATERIALS:
        material = "pla"
    code, out = run_script([sys.executable, str(REPO / "scripts/check-gcode.py"),
                            "--material", material, str(gcode)])
    if code != 0:
        return {"ok": False, "report": "REFUSED - safety check failed:\n" + out}
    code, out = run_script([str(REPO / "scripts/octoprint-upload.sh"), str(gcode)])
    return {"ok": code == 0, "report": out}


# ---------------------- public model search (Printables) ----------------------
PRINTABLES_API = "https://api.printables.com/graphql/"
PRINTABLES_UA = "PartStudio/1.0 (personal 3D printing tool)"


def printables_gql(query, variables):
    req = urllib.request.Request(
        PRINTABLES_API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "User-Agent": PRINTABLES_UA})
    with urllib.request.urlopen(req, timeout=20) as r:
        out = json.load(r)
    if out.get("errors"):
        raise RuntimeError("Printables API: " + json.dumps(out["errors"])[:300])
    return out["data"]


def search_models(query):
    query = (query or "").strip()
    if not query:
        raise ValueError("type something to search for")
    data = printables_gql(
        """query S($q: String!) { searchPrints2(query: $q, limit: 24) { items {
             id name slug image { filePath } user { publicUsername }
             license { name } likesCount downloadCount } } }""",
        {"q": query})
    items = []
    for it in data["searchPrints2"]["items"]:
        items.append({
            "id": it["id"],
            "name": it["name"],
            "url": f"https://www.printables.com/model/{it['id']}-{it['slug']}",
            "image": ("https://media.printables.com/" + it["image"]["filePath"])
                     if it.get("image") else None,
            "author": (it.get("user") or {}).get("publicUsername"),
            "license": (it.get("license") or {}).get("name"),
            "likes": it.get("likesCount"),
            "downloads": it.get("downloadCount"),
            "source": "Printables",
        })
    return items


def model_files(print_id):
    data = printables_gql(
        """query P($id: ID!) { print(id: $id) { id name
             user { publicUsername } license { name }
             stls { id name fileSize } } }""",
        {"id": str(print_id)})
    p = data["print"]
    files = [f for f in p["stls"] if f["name"].lower().endswith(".stl")]
    return {"id": p["id"], "name": p["name"],
            "author": (p.get("user") or {}).get("publicUsername"),
            "license": (p.get("license") or {}).get("name"),
            "files": files}


def http_download(url, cap=60 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": PRINTABLES_UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(cap + 1)
    if len(data) > cap:
        raise ValueError("file larger than the 60MB import cap")
    return data


def import_remote(print_id, file_id):
    info = model_files(print_id)
    f = next((x for x in info["files"] if str(x["id"]) == str(file_id)), None)
    if not f:
        raise ValueError("that file is not part of this model")
    data = printables_gql(
        """mutation D($id: ID!, $printId: ID!, $fileType: DownloadFileTypeEnum!,
                      $source: DownloadSourceEnum!) {
             getDownloadLink(id: $id, printId: $printId, fileType: $fileType,
                             source: $source) { ok output { link } } }""",
        {"id": str(file_id), "printId": str(print_id),
         "fileType": "stl", "source": "model_detail"})
    link = data["getDownloadLink"]["output"]["link"]
    raw = http_download(link)
    stem = save_import(f["name"], base64.b64encode(raw).decode())
    attribution = {
        "title": info["name"], "file": f["name"], "author": info["author"],
        "license": info["license"], "source": "Printables",
        "url": f"https://www.printables.com/model/{print_id}",
    }
    (IMPORTS / f"{stem}.json").write_text(json.dumps(attribution, indent=2))
    return {"model": stem, "attribution": attribution}


def import_url(url):
    url = (url or "").strip()
    m = re.match(r"https?://(?:www\.)?printables\.com/model/(\d+)", url)
    if m:
        info = model_files(m.group(1))
        if len(info["files"]) == 1:
            return import_remote(info["id"], info["files"][0]["id"])
        return {"choose": info}     # several files - let the user pick
    if re.match(r"https?://\S+\.(stl|glb|gltf|obj|ply|3mf)(\?\S*)?$", url, re.I):
        raw = http_download(url)
        stem = save_import(url.split("?")[0].rsplit("/", 1)[-1],
                           base64.b64encode(raw).decode())
        (IMPORTS / f"{stem}.json").write_text(json.dumps(
            {"title": stem, "source": "direct URL", "url": url}, indent=2))
        return {"model": stem, "attribution": {"title": stem, "url": url}}
    raise ValueError("paste a printables.com model URL or a direct link to an "
                     ".stl file")


BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def make_printable(name, voxel=0.8, target_mm=0.0):
    """Run the headless Blender solidify job on an import; produces a new
    import named <name>_solid with attribution carried over."""
    src = IMPORTS / f"{name}.stl"
    if not src.is_file():
        raise ValueError("make printable runs on imported meshes - select an import")
    if not Path(BLENDER).is_file():
        raise RuntimeError("Blender not found at /Applications/Blender.app - "
                           "install it with: brew install --cask blender")
    out_name = f"{name}_solid"
    dst = IMPORTS / f"{out_name}.stl"
    job = REPO / "scripts/bpy_make_printable.py"
    p = subprocess.run(
        [BLENDER, "--background", "--python", str(job), "--",
         str(src), str(dst), str(voxel), "0.5", str(target_mm or 0)],
        capture_output=True, text=True, timeout=600)
    marker = [l for l in p.stdout.splitlines() if l.startswith("BPY_RESULT")]
    if p.returncode != 0 or not dst.is_file() or not marker:
        raise RuntimeError("Blender job failed:\n" + (p.stdout + p.stderr)[-600:])
    att_src = IMPORTS / f"{name}.json"
    att = json.loads(att_src.read_text()) if att_src.is_file() else {}
    att["processed"] = f"voxel remesh {voxel}mm" + (f", scaled to {target_mm}mm" if target_mm else "")
    (IMPORTS / f"{out_name}.json").write_text(json.dumps(att, indent=2))
    result = generate(out_name, {})
    result["model"] = out_name
    result["bpy"] = marker[0]
    return result


# ---- AI image/text -> 3D (Tripo or Meshy; key arrives via ~/.zshrc) ----
def gen3d_provider():
    if os.environ.get("TRIPO_API_KEY"):
        return "tripo"
    if os.environ.get("MESHY_API_KEY"):
        return "meshy"
    return None


def gen3d_config():
    p = gen3d_provider()
    return {"provider": p,
            "hint": None if p else ("no key configured - add TRIPO_API_KEY or "
                                    "MESHY_API_KEY to ~/.zshrc and restart the studio")}


def _gen3d_poll(url, headers, done_key, status_path, interval=6, budget=900):
    waited = 0
    while waited < budget:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
        node = d
        for k in status_path[:-1]:
            node = node.get(k, {})
        status = node.get(status_path[-1], "")
        if status in ("success", "SUCCEEDED", "completed"):
            return d
        if status in ("failed", "FAILED", "cancelled", "expired"):
            raise RuntimeError(f"generation failed: {json.dumps(d)[:300]}")
        time.sleep(interval)
        waited += interval
    raise RuntimeError("3D generation timed out after 15 minutes")


def gen3d(image_b64=None, image_name=None, prompt=None):
    """Photo (or text) -> mesh via the configured provider -> import."""
    provider = gen3d_provider()
    if not provider:
        raise RuntimeError(gen3d_config()["hint"])
    if provider == "tripo":
        key = os.environ["TRIPO_API_KEY"]
        H = {"Authorization": f"Bearer {key}"}
        JH = {**H, "Content-Type": "application/json"}
        API = "https://openapi.tripo3d.ai/v3"

        def tripo(url, payload=None, headers=None, raw=None):
            req = urllib.request.Request(url, data=raw or (json.dumps(payload).encode() if payload else None),
                                         headers=headers or JH)
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    d = json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:400]
                raise RuntimeError(f"Tripo HTTP {e.code}: {body}")
            if d.get("code") != 0:
                raise RuntimeError(f"Tripo: {d.get('message')} - {d.get('suggestion','')}")
            return d["data"]

        if image_b64:
            # multipart upload -> file token -> image_to_model
            img = base64.b64decode(image_b64)
            fname = Path(image_name or "photo.png").name
            boundary = "----partstudio" + str(int(time.time()))
            body = (f"--{boundary}\r\nContent-Disposition: form-data; "
                    f'name="file"; filename="{fname}"\r\n'
                    f"Content-Type: application/octet-stream\r\n\r\n").encode()                    + img + f"\r\n--{boundary}--\r\n".encode()
            up = tripo(f"{API}/files", raw=body,
                       headers={**H, "Content-Type": f"multipart/form-data; boundary={boundary}"})
            token = up.get("file_token") or up.get("token") or up.get("id")
            task = tripo(f"{API}/generation/image-to-model",
                         {"model": os.environ.get("TRIPO_MODEL", "v3.0-20250812"),
                          "file": {"type": Path(fname).suffix.lstrip(".") or "png",
                                   "file_token": token}})["task_id"]
        else:
            task = tripo(f"{API}/generation/text-to-model",
                         {"model": os.environ.get("TRIPO_MODEL", "v3.0-20250812"),
                          "prompt": prompt or ""})["task_id"]

        waited = 0
        while True:
            d = tripo(f"{API}/tasks/{task}")
            if d.get("status") == "success":
                break
            if d.get("status") in ("failed", "cancelled"):
                raise RuntimeError(f"Tripo task {d.get('status')}: {json.dumps(d)[:300]}")
            time.sleep(6)
            waited += 6
            if waited > 900:
                raise RuntimeError("Tripo generation timed out after 15 minutes")
        out = d.get("output") or {}
        url = (out.get("pbr_model") or out.get("model") or out.get("base_model")
               or next((v for v in out.values()
                        if isinstance(v, str) and v.startswith("http")), None))
    else:   # meshy
        key = os.environ["MESHY_API_KEY"]
        H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        if image_b64:
            body = {"image_url": f"data:image/png;base64,{image_b64}",
                    "should_remesh": True}
            ep = "https://api.meshy.ai/openapi/v1/image-to-3d"
        else:
            body = {"mode": "preview", "prompt": prompt or "", "art_style": "realistic"}
            ep = "https://api.meshy.ai/openapi/v2/text-to-3d"
        req = urllib.request.Request(ep, data=json.dumps(body).encode(), headers=H)
        with urllib.request.urlopen(req, timeout=60) as r:
            task = json.load(r)["result"]
        base = ep.rsplit("/", 1)[0] + ("/image-to-3d" if image_b64 else "/text-to-3d")
        done = _gen3d_poll(f"{base}/{task}", H, "SUCCEEDED", ["status"])
        url = (done.get("model_urls") or {}).get("glb")
    if not url:
        raise RuntimeError("provider returned no model url")
    raw = http_download(url)
    tmp = OUTPUT / "_gen3d_download"
    suffix = ".glb" if ".glb" in url.split("?")[0] else ".stl"
    tmp_file = tmp.with_suffix(suffix)
    tmp_file.write_bytes(raw)
    if suffix == ".glb":   # convert to STL via trimesh
        import trimesh
        scene = trimesh.load(str(tmp_file))
        mesh = scene.dump(concatenate=True) if isinstance(scene, trimesh.Scene) else scene
        stem_src = prompt or Path(image_name or "generated").stem
        stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", stem_src).strip("_")[:30] or "generated"
        out = IMPORTS / f"{stem}.stl"
        IMPORTS.mkdir(parents=True, exist_ok=True)
        mesh.export(str(out))
    else:
        stem = save_import((prompt or image_name or "generated") + ".stl",
                           base64.b64encode(raw).decode())
        out = IMPORTS / f"{stem}.stl"
    (IMPORTS / f"{out.stem}.json").write_text(json.dumps(
        {"title": prompt or image_name, "source": f"AI generated ({provider})",
         "license": "check provider terms"}, indent=2))
    result = generate(out.stem, {})
    result["model"] = out.stem
    return result


OCTO_URL = os.environ.get("OCTO_URL", "http://127.0.0.1:5001")


def octo_request(path, method="GET"):
    key = os.environ.get("OCTOPRINT_API_KEY", "")
    req = urllib.request.Request(OCTO_URL + path, method=method,
                                 headers={"X-Api-Key": key})
    with urllib.request.urlopen(req, timeout=5) as r:
        body = r.read()
        return json.loads(body) if body.strip() else {}


def printer_status():
    """Read-only printer snapshot: connection state + temperatures."""
    try:
        conn = octo_request("/api/connection")
    except (urllib.error.URLError, OSError):
        return {"reachable": False, "state": "OctoPrint unreachable"}
    state = conn.get("current", {}).get("state", "Unknown")
    out = {"reachable": True, "state": state, "temps": None}
    try:
        printer = octo_request("/api/printer?exclude=sd,history")
        out["temps"] = printer.get("temperature")
        out["state"] = printer.get("state", {}).get("text", state)
    except urllib.error.HTTPError:
        pass   # 409: no printer connected - state alone is the answer
    except (urllib.error.URLError, OSError):
        pass
    return out


def octo_files():
    d = octo_request("/api/files/local")
    files = []
    for f in d.get("files", []):
        if f.get("type") == "machinecode" or f.get("name", "").endswith(".gcode"):
            files.append({"name": f["name"], "size": f.get("size"),
                          "date": f.get("date")})
    files.sort(key=lambda x: x.get("date") or 0, reverse=True)
    return files


def octo_delete(name):
    if "/" in name or name.startswith("."):
        raise ValueError("bad filename")
    try:
        octo_request("/api/files/local/" + urllib.parse.quote(name), method="DELETE")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise FileNotFoundError(f"{name} is not on the printer")
        if e.code == 409:
            raise RuntimeError(f"{name} is in use (selected or printing) - not deleted")
        raise
    return {"deleted": name}


def revert_model(name):
    """Swap the model with its most recent saved version. Calling it again
    swaps back, so nothing is ever lost."""
    hist = MODELS / ".history"
    versions = sorted(hist.glob(f"{name}-*.py")) if hist.is_dir() else []
    if not versions:
        raise ValueError(f"no earlier version of {name} recorded")
    latest = versions[-1]
    path = MODELS / f"{name}.py"
    current = path.read_text()
    path.write_text(latest.read_text())
    latest.write_text(current)
    return {"model": name, "note": "previous version restored - revert again to switch back"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _file(self, path: Path):
        if not path.is_file():
            return self._send(404, {"error": "not found"})
        self._send(200, path.read_bytes(), MIME.get(path.suffix, "application/octet-stream"))

    def do_GET(self):
        route = self.path.split("?")[0]
        if route == "/":
            return self._file(STATIC / "index.html")
        if route.startswith("/static/"):
            p = (STATIC / route[len("/static/"):]).resolve()
            if not str(p).startswith(str(STATIC)):
                return self._send(403, {"error": "forbidden"})
            return self._file(p)
        if route.startswith("/output/") and route.endswith((".stl", ".gcode")):
            p = (OUTPUT / Path(route).name).resolve()
            return self._file(p)
        if route == "/api/printjob":
            # live print state for toolpath sync: which file, byte position
            try:
                d = octo_request("/api/job")
                prog = d.get("progress", {})
                return self._send(200, {
                    "state": d.get("state"),
                    "file": (d.get("job", {}).get("file") or {}).get("name"),
                    "filepos": prog.get("filepos"),
                    "filesize": (d.get("job", {}).get("file") or {}).get("size"),
                    "completion": prog.get("completion"),
                    "printTimeLeft": prog.get("printTimeLeft"),
                })
            except Exception:
                return self._send(200, {"state": "unreachable"})
        if route == "/api/models":
            return self._send(200, list_models())
        if route == "/api/busy":
            running = [j for j in _jobs.values() if j["status"] == "running"]
            return self._send(200, {"running": len(running)})
        if route.startswith("/api/job/"):
            jid = route.rsplit("/", 1)[-1]
            job = _jobs.get(jid)
            if not job:
                return self._send(404, {"error": "unknown job"})
            out = dict(job)
            if job["status"] != "running":
                # deliver once, then forget
                _jobs.pop(jid, None)
            return self._send(200, out)
        if route == "/api/gen3d_config":
            return self._send(200, gen3d_config())
        if route == "/api/material_custom":
            return self._send(200, custom_material_meta() or {})
        if route == "/api/printer":
            return self._send(200, printer_status())
        if route == "/api/files":
            try:
                return self._send(200, octo_files())
            except Exception:
                return self._send(500, {"error": traceback.format_exc()})
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/generate":
                return self._send(200, generate(req["model"], req.get("params"),
                                                req.get("scale", 1.0),
                                                req.get("rot")))
            if self.path == "/api/slice":
                return self._send(200, do_slice(req["model"], req.get("settings")))
            if self.path == "/api/upload":
                return self._send(200, do_upload(req["model"]))
            if self.path == "/api/search":
                return self._send(200, search_models(req.get("query")))
            if self.path == "/api/model_files":
                return self._send(200, model_files(req["id"]))
            if self.path == "/api/model_import":
                return self._send(200, import_remote(req["id"], req["file_id"]))
            if self.path == "/api/import_url":
                return self._send(200, import_url(req.get("url")))
            if self.path == "/api/material_lookup":
                return self._send(200, material_lookup(req.get("query")))
            if self.path == "/api/files/delete":
                return self._send(200, octo_delete(req["name"]))
            if self.path == "/api/refine":
                return self._send(200, start_job(
                    refine, req["model"], req.get("notes")))
            if self.path == "/api/auto_orient":
                return self._send(200, start_job(auto_orient, req["model"]))
            if self.path == "/api/make_printable":
                return self._send(200, start_job(
                    make_printable, req["model"],
                    float(req.get("voxel") or 0.8),
                    float(req.get("target_mm") or 0)))
            if self.path == "/api/gen3d":
                return self._send(200, start_job(
                    gen3d, req.get("image"), req.get("image_name"),
                    req.get("prompt")))
            if self.path == "/api/revert":
                return self._send(200, revert_model(req["model"]))
            if self.path == "/api/import":
                stem = save_import(req["name"], req["data"])
                return self._send(200, {"model": stem})
            if self.path == "/api/describe":
                return self._send(200, start_job(
                    describe, req.get("mode", "new"), req.get("model"),
                    req["description"], req.get("image"), req.get("focus")))
            return self._send(404, {"error": "not found"})
        except Exception:
            return self._send(500, {"error": traceback.format_exc()})


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8434
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Part Studio on http://127.0.0.1:{port}  (models: {MODELS})", flush=True)
    srv.serve_forever()
