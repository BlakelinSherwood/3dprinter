# model: star_tag
"""Flat five-pointed star tag with a hanging hole in the top point."""
import math
import cadquery as cq


def build(
    width: float = 50.0,
    thickness: float = 3.0,
    hole_diameter: float = 5.2,
    hole_inset: float = 14.0,
    point_ratio: float = 0.382,
    bottom_chamfer: float = 0.4,
):
    outer_r = width / (2.0 * math.cos(math.radians(18.0)))
    inner_r = outer_r * point_ratio

    pts = []
    for i in range(10):
        angle = math.radians(90.0 + i * 36.0)
        r = outer_r if i % 2 == 0 else inner_r
        pts.append((r * math.cos(angle), r * math.sin(angle)))

    star = (
        cq.Workplane("XY")
        .polyline(pts)
        .close()
        .extrude(thickness)
    )

    hole_y = outer_r - hole_inset
    star = (
        star.faces(">Z")
        .workplane()
        .pushPoints([(0, hole_y)])
        .hole(hole_diameter)
    )

    star = star.edges("<Z").chamfer(bottom_chamfer)

    return star


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
