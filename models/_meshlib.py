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


def parts(*meshes, gap=8.0):
    """Lay several bodies side by side on the plate as one printable set.
    Use after splitting a model: return parts(hull, turret, wheels...)."""
    import numpy as np
    import trimesh
    placed = []
    x = 0.0
    for m in meshes:
        m = m.copy()
        lo, hi = m.bounds
        m.apply_translation([x - lo[0], -lo[1], -lo[2]])
        x += (hi[0] - lo[0]) + gap
        placed.append(m)
    return trimesh.util.concatenate(placed)


def split_plane(mesh, point, normal):
    """Cut a mesh into (kept, removed) halves along a plane. Both halves are
    capped watertight. point/normal are in the mesh's own coordinates."""
    import numpy as np
    import trimesh
    n = np.asarray(normal, dtype=float)
    n /= (np.linalg.norm(n) or 1)
    a = mesh.slice_plane(point, n, cap=True)
    b = mesh.slice_plane(point, -n, cap=True)
    return a, b


def peg(diameter=8.0, length=10.0, clearance=0.0):
    """A cylinder tool for rotation pegs / alignment pins. Positive clearance
    makes the SOCKET version (subtract it); zero makes the peg (union it)."""
    import trimesh
    return trimesh.creation.cylinder(radius=(diameter + clearance) / 2.0,
                                     height=length, sections=48)
