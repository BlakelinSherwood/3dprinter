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
import importlib.util
import inspect
import json
import subprocess
import sys
import threading
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
    for f in sorted(MODELS.glob("*.py")):
        try:
            mod = load_model(f)
            doc = (mod.__doc__ or "").strip().splitlines()
            items.append({
                "name": f.stem,
                "summary": doc[0] if doc else "",
                "params": model_params(mod),
            })
        except Exception:
            items.append({"name": f.stem, "summary": "LOAD ERROR",
                          "params": [], "error": traceback.format_exc()})
    return items


def generate(name, params):
    import cadquery as cq
    path = MODELS / f"{name}.py"
    if not path.is_file():
        raise FileNotFoundError(f"no such model: {name}")
    mod = load_model(path)
    kwargs = {k: float(v) for k, v in (params or {}).items()}
    with _generate_lock:
        solid = mod.build(**kwargs)
        OUTPUT.mkdir(exist_ok=True)
        stl = OUTPUT / f"{name}.stl"
        cq.exporters.export(solid, str(stl), tolerance=0.01, angularTolerance=0.1)
    shape = as_shape(solid)
    bb = shape.BoundingBox()
    return {
        "stl": f"/output/{name}.stl",
        "bbox": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
        "volume_cm3": round(shape.Volume() / 1000.0, 2),
    }


def run_script(args, timeout=600):
    p = subprocess.run(args, cwd=REPO, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr).strip()


def do_slice(name):
    stl = OUTPUT / f"{name}.stl"
    if not stl.is_file():
        raise FileNotFoundError("generate the STL first")
    code, out = run_script([str(REPO / "scripts/test-slice.sh"), str(stl), name])
    return {"ok": code == 0, "report": out,
            "gcode": f"output/{name}.gcode" if code == 0 else None}


def do_upload(name):
    gcode = OUTPUT / f"{name}.gcode"
    if not gcode.is_file():
        raise FileNotFoundError("slice first")
    # Independent re-check so a stale or unsafe file can never be uploaded,
    # even if the UI is out of sync with what's on disk.
    code, out = run_script([sys.executable, str(REPO / "scripts/check-gcode.py"), str(gcode)])
    if code != 0:
        return {"ok": False, "report": "REFUSED - safety check failed:\n" + out}
    code, out = run_script([str(REPO / "scripts/octoprint-upload.sh"), str(gcode)])
    return {"ok": code == 0, "report": out}


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
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/api/generate":
                return self._send(200, generate(req["model"], req.get("params")))
            if self.path == "/api/slice":
                return self._send(200, do_slice(req["model"]))
            if self.path == "/api/upload":
                return self._send(200, do_upload(req["model"]))
            return self._send(404, {"error": "not found"})
        except Exception:
            return self._send(500, {"error": traceback.format_exc()})


if __name__ == "__main__":
    port = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8434
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Part Studio on http://127.0.0.1:{port}  (models: {MODELS})", flush=True)
    srv.serve_forever()
