#!/usr/bin/env python3
"""Generate a simple binary STL calibration cube (default 20mm) for pipeline testing.

Usage: python3 generate_test_cube.py [size_mm] [output_path]
No dependencies beyond the standard library.
"""
import struct
import sys


def cube_triangles(s):
    # 8 corners of a cube from (0,0,0) to (s,s,s)
    v = [
        (0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0),  # bottom
        (0, 0, s), (s, 0, s), (s, s, s), (0, s, s),  # top
    ]
    # Each face: two triangles, counter-clockwise when viewed from outside
    faces = [
        # (normal, tri1, tri2)
        ((0, 0, -1), (0, 2, 1), (0, 3, 2)),   # bottom (z=0)
        ((0, 0, 1),  (4, 5, 6), (4, 6, 7)),   # top (z=s)
        ((0, -1, 0), (0, 1, 5), (0, 5, 4)),   # front (y=0)
        ((0, 1, 0),  (2, 3, 7), (2, 7, 6)),   # back (y=s)
        ((-1, 0, 0), (0, 4, 7), (0, 7, 3)),   # left (x=0)
        ((1, 0, 0),  (1, 2, 6), (1, 6, 5)),   # right (x=s)
    ]
    tris = []
    for normal, t1, t2 in faces:
        for tri in (t1, t2):
            tris.append((normal, [v[i] for i in tri]))
    return tris


def write_binary_stl(path, tris, name=b"calibration_cube"):
    with open(path, "wb") as f:
        f.write(name.ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for normal, verts in tris:
            f.write(struct.pack("<3f", *normal))
            for vx in verts:
                f.write(struct.pack("<3f", *vx))
            f.write(struct.pack("<H", 0))


if __name__ == "__main__":
    size = float(sys.argv[1]) if len(sys.argv) > 1 else 20.0
    out = sys.argv[2] if len(sys.argv) > 2 else "calibration_cube_20mm.stl"
    write_binary_stl(out, cube_triangles(size))
    print(f"Wrote {out}: {size}mm cube, 12 triangles")
