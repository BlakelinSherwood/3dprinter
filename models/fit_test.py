# model: fit_test
"""Clearance fit test: five 5mm holes at +0.1..+0.5 plus a matching 5mm peg."""
import cadquery as cq


def build(
    nominal_d=5.0,
    thickness=4.0,
    plate_width=64.0,
    plate_depth=14.0,
    peg_height=10.0,
):
    clearances = [0.1, 0.2, 0.3, 0.4, 0.5]
    pitch = plate_width / (len(clearances) + 1)
    plate = (
        cq.Workplane("XY")
        .rect(plate_width, plate_depth)
        .extrude(thickness)
        .edges("|Z")
        .fillet(2.0)
        .edges("<Z")
        .chamfer(0.4)
    )
    for i, c in enumerate(clearances):
        x = -plate_width / 2.0 + pitch * (i + 1)
        cutter = (
            cq.Workplane("XY")
            .center(x, 0)
            .circle((nominal_d + c) / 2.0)
            .extrude(thickness)
        )
        plate = plate.cut(cutter)
    # The peg to test in each hole, printed alongside the plate.
    peg = (
        cq.Workplane("XY")
        .center(0, plate_depth / 2.0 + 8.0)
        .circle(nominal_d / 2.0)
        .extrude(peg_height)
        .edges(">Z")
        .chamfer(0.5)
    )
    return plate.union(peg)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
