#!/usr/bin/env python
"""Parametric adhesive-backed cable clip.

A C-shaped clip that snaps over a cable, on a flat backing plate for mounting
tape. Printed lying on its back plate, every overhang is self-supporting, so it
needs no supports.

Usage: cable_clip.py [out.stl] [cable_diameter_mm]
"""
import sys
import cadquery as cq

CABLE_D = 5.0     # cable diameter the clip grips
WALL = 2.0        # clip wall thickness
WIDTH = 8.0       # width along the cable axis
BACK = 2.0        # backing plate thickness
GAP_FRAC = 0.72   # snap opening, as a fraction of cable diameter


def build(cable_d=CABLE_D, wall=WALL, width=WIDTH, back=BACK):
    r_in = cable_d / 2.0
    r_out = r_in + wall
    gap = cable_d * GAP_FRAC

    # Ring forming the cable channel, extruded along Y (the cable axis).
    ring = (
        cq.Workplane("XZ")
        .center(0, back + r_out)
        .circle(r_out)
        .circle(r_in)
        .extrude(width)
    )
    # Flat backing plate the part is printed on.
    backing = (
        cq.Workplane("XZ")
        .center(0, back / 2.0)
        .rect(2 * r_out, back)
        .extrude(width)
    )
    part = ring.union(backing)

    # Snap opening cut through the top of the ring.
    opening = (
        cq.Workplane("XZ")
        .center(0, back + r_out + r_out * 0.75)
        .rect(gap, r_out * 1.5)
        .extrude(width)
    )
    part = part.cut(opening)

    # Round the vertical corners of the backing plate.
    part = part.edges("|Y and >Z").fillet(0.5)
    return part


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "cable_clip.stl"
    d = float(sys.argv[2]) if len(sys.argv) > 2 else CABLE_D
    solid = build(cable_d=d)
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}")
    print(f"  bbox: {bb.xlen:.2f} x {bb.ylen:.2f} x {bb.zlen:.2f} mm")
    print(f"  volume: {solid.val().Volume()/1000:.2f} cm^3")
