"""Helpers for editing imported meshes (models/imports/*.stl) by description.

Generated <name>_mod.py models use these to combine a downloaded mesh with
CadQuery-built tool solids via manifold boolean operations.
"""
from pathlib import Path
import tempfile

import trimesh

IMPORTS = Path(__file__).resolve().parent / "imports"


def load_import(name):
    """Load an imported STL by its model name (no extension)."""
    path = IMPORTS / f"{name}.stl"
    if not path.is_file():
        raise FileNotFoundError(f"no imported mesh named {name}")
    mesh = trimesh.load(str(path), force="mesh")
    mesh.remove_unreferenced_vertices()
    return mesh


def cq_solid(workplane):
    """Convert a CadQuery Workplane/solid to a trimesh mesh."""
    import cadquery as cq
    with tempfile.NamedTemporaryFile(suffix=".stl", delete=False) as f:
        tmp = f.name
    cq.exporters.export(workplane, tmp, tolerance=0.01, angularTolerance=0.1)
    mesh = trimesh.load(tmp, force="mesh")
    Path(tmp).unlink(missing_ok=True)
    return mesh


def _boolean(op, a, *tools):
    meshes = [a, *tools]
    out = getattr(trimesh.boolean, op)(meshes, engine="manifold")
    if isinstance(out, trimesh.Scene):
        out = out.dump(concatenate=True)
    # A boolean that changes nothing means the tool never touched the mesh -
    # by far the most common generated-code mistake (wrong extrude direction
    # or coordinate frame). Fail loudly so it can be fixed, not shipped.
    if op == "difference" and abs(out.volume - a.volume) < max(1.0, a.volume * 1e-6):
        raise ValueError(
            "difference() removed no material - the tool solid does not "
            "intersect the mesh. Check the tool's position and extrude "
            "direction (extrude goes along the workplane normal: XY->+Z, "
            "XZ->-Y, YZ->+X).")
    if op == "union":
        total = a.volume + sum(t.volume for t in tools)
        if abs(out.volume - total) < max(1.0, total * 1e-6):
            raise ValueError(
                "union() merged nothing - the added solid does not touch the "
                "mesh. Check its position and extrude direction (extrude goes "
                "along the workplane normal: XY->+Z, XZ->-Y, YZ->+X).")
    return out


def difference(mesh, *tools):
    """mesh minus every tool solid."""
    return _boolean("difference", mesh, *tools)


def union(mesh, *tools):
    return _boolean("union", mesh, *tools)


def intersection(mesh, *tools):
    return _boolean("intersection", mesh, *tools)
