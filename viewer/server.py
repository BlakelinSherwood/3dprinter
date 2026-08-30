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
- Prefer simple robust CadQuery: boxes, cylinders, extrudes, cuts, unions,
  fillet/chamfer with conservative radii. Selectors can be brittle - when
  filleting, select edges precisely (e.g. "|Z", ">Z") and keep radii small
  relative to the faces they touch, or skip the fillet.
"""

OUTPUT_RULE = ("\nReply with ONLY the complete Python source file. "
               "No markdown fences, no commentary before or after.")


def call_claude(prompt, allow_read=False):
    scratch = tempfile.mkdtemp(prefix="studio-codegen-")
    cmd = [find_claude(), "-p", prompt, "--model", "sonnet", "--output-format", "text"]
    if allow_read:   # let the CLI view an uploaded reference image
        cmd += ["--allowedTools", "Read"]
    p = subprocess.run(
        cmd,
        cwd=scratch, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=420,
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


def save_import(name, data_b64):
    data = base64.b64decode(data_b64)
    if len(data) > 60 * 1024 * 1024:
        raise ValueError("mesh too large (60MB max)")
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", Path(name).stem).strip("_") or "import"
    IMPORTS.mkdir(parents=True, exist_ok=True)
    path = IMPORTS / f"{stem}.stl"
    path.write_bytes(data)
    read_stl(path)   # validate now so a bad file fails at upload time
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


def generate_import(name, scale, scale_label, rot=None):
    import numpy as np
    tris = read_stl(IMPORTS / f"{name}.stl")
    warnings = [f"imported mesh - scale and slice only, no parameters"]
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
    return {
        "stl": f"/output/{name}.stl",
        "bbox": [round(float(d), 2) for d in dims],
        "volume_cm3": round(mesh_volume(tris) / 1000.0, 2),
        "scale": scale,
        "scale_label": scale_label,
        "warnings": warnings,
    }


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


def describe(mode, name, description, image=None):
    """Natural-language build/edit. Writes models/<name>.py after validating
    that the generated file actually loads and builds."""
    rules = design_rules()
    image_path = save_reference_image(image) if image else None
    if mode == "edit":
        path = MODELS / f"{name}.py"
        if not path.is_file():
            if (IMPORTS / f"{name}.stl").is_file():
                raise ValueError(
                    "imported meshes have no editable source - use scale, or "
                    "describe a new part instead")
            raise FileNotFoundError(f"no such model: {name}")
        original = path.read_text()
        task = (f"Modify this existing model per the request below. Keep the same "
                f"`# model:` name and overall structure; change only what the "
                f"request implies.\n\nRequest: {description}\n\n"
                f"Current file:\n{original}")
    else:
        original = None
        task = f"Write a new model for this request: {description}"

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
    prompt = (MODEL_CONTRACT + "\n# Printer design rules (mandatory)\n" + rules
              + "\n# Task\n" + task + OUTPUT_RULE)

    with _codegen_lock:
        last_err = None
        for attempt in (1, 2):
            reply = call_claude(prompt, allow_read=image_path is not None)
            code = extract_code(reply)
            if mode == "edit":
                out_name = name
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
    items = []
    for f in sorted(IMPORTS.glob("*.stl")) if IMPORTS.is_dir() else []:
        items.append({"name": f.stem, "summary": "imported mesh",
                      "params": [], "imported": True})
    for f in sorted(MODELS.glob("*.py")):
        try:
            mod = load_model(f)
            doc = (mod.__doc__ or "").strip().splitlines()
            hist = MODELS / ".history"
            items.append({
                "name": f.stem,
                "summary": doc[0] if doc else "",
                "params": model_params(mod),
                "has_history": bool(hist.is_dir() and list(hist.glob(f"{f.stem}-*.py"))),
            })
        except Exception:
            items.append({"name": f.stem, "summary": "LOAD ERROR",
                          "params": [], "error": traceback.format_exc()})
    return items


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
        shape = as_shape(mod.build(**kwargs))
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
    return {
        "stl": f"/output/{name}.stl",
        "bbox": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
        "volume_cm3": round(vol / 1000.0, 2),
        "scale": scale,
        "scale_label": scale_label,
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


def build_process_override(settings):
    """Merge per-print settings onto the repo process profile. Returns a path
    to a temp process json, or None when everything is at profile defaults."""
    if not settings:
        return None
    base = json.loads((REPO / "profiles/ender3v2/process.json").read_text())
    changed = []
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
    if settings.get("supports"):
        base["enable_support"] = "1"
        base["support_type"] = "tree(auto)"
        changed.append("tree supports")
    if settings.get("brim"):
        base["brim_type"] = "outer_only"
        base["brim_width"] = "5"
        changed.append("brim")
    if not changed:
        return None
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


def do_slice(name, settings=None):
    stl = OUTPUT / f"{name}.stl"
    if not stl.is_file():
        raise FileNotFoundError("generate the STL first")
    settings = settings or {}
    material = str(settings.get("material") or "pla").lower()
    if material not in MATERIALS:
        raise ValueError(f"unknown material {material}")
    copies = max(1, min(25, int(settings.get("copies") or 1)))
    args = [str(REPO / "scripts/test-slice.sh"), str(stl), name]
    override = build_process_override(settings)
    changed = []
    if override:
        args.append(str(override[0]))
        changed = override[1]
    if material != "pla":
        changed.append(material.upper())
    if copies > 1:
        changed.append(f"{copies} copies")
    extra_env = {"MATERIAL": material}
    if copies > 1:
        extra_env["REPETITIONS"] = str(copies)
    code, out = run_script(args, extra_env=extra_env)
    if code == 0:
        # The upload re-check must verify against the envelope this file was
        # sliced for, not assume PLA.
        (OUTPUT / f"{name}.material").write_text(material)
    result = {"ok": code == 0, "report": out, "overrides": changed,
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


OCTO_URL = "http://127.0.0.1:5001"


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
        if route.startswith("/output/") and route.endswith(".stl"):
            p = (OUTPUT / Path(route).name).resolve()
            return self._file(p)
        if route == "/api/models":
            return self._send(200, list_models())
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
            if self.path == "/api/files/delete":
                return self._send(200, octo_delete(req["name"]))
            if self.path == "/api/revert":
                return self._send(200, revert_model(req["model"]))
            if self.path == "/api/import":
                stem = save_import(req["name"], req["data"])
                return self._send(200, {"model": stem})
            if self.path == "/api/describe":
                return self._send(200, describe(
                    req.get("mode", "new"), req.get("model"), req["description"],
                    req.get("image")))
            return self._send(404, {"error": "not found"})
        except Exception:
            return self._send(500, {"error": traceback.format_exc()})


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8434
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Part Studio on http://127.0.0.1:{port}  (models: {MODELS})", flush=True)
    srv.serve_forever()
