# model: Headphone_Stand_mod
"""Cut a 20mm cable-routing hole front-to-back through the arm."""

import cadquery as cq
from _meshlib import load_import, cq_solid, difference


def build(hole_diameter=20.0, hole_x=169.07, hole_z=212.61):
    m = load_import("Headphone_Stand")

    # Cylinder tool: built on XY (axis +Z), rotated to lie along Y, then
    # moved to the clicked spot. Length spans the full mesh Y range plus
    # generous margin so the cut passes cleanly through front and back.
    y_start = -20.0
    y_end = 260.0
    length = y_end - y_start

    tool = (
        cq.Workplane("XY")
        .circle(hole_diameter / 2.0)
        .extrude(length)
        .rotate((0, 0, 0), (1, 0, 0), -90)  # +Z axis -> +Y axis
        .translate((hole_x, y_start, hole_z))
    )

    return difference(m, cq_solid(tool))


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    build().export(out)
