# model: round_drink_coaster
"""Round drink coaster with a raised rim to catch condensation/spills.

90mm diameter disc with a flat recessed center and a raised outer lip.
"""
import cadquery as cq


def build(
    diameter: float = 90.0,
    base_thickness: float = 4.0,
    lip_height: float = 2.0,
    lip_width: float = 3.0,
    bottom_chamfer: float = 0.5,
):
    outer_radius = diameter / 2.0
    inner_radius = outer_radius - lip_width

    base = cq.Workplane("XY").circle(outer_radius).extrude(base_thickness)

    lip = (
        cq.Workplane("XY")
        .workplane(offset=base_thickness)
        .circle(outer_radius)
        .circle(inner_radius)
        .extrude(lip_height)
    )

    coaster = base.union(lip)

    coaster = coaster.edges("<Z").chamfer(bottom_chamfer)

    return coaster


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
