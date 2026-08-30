# model: first_layer_test
"""First-layer and bed-level test: five thin pads at the corners and center."""
import cadquery as cq


def build(
    pad_size=25.0,
    pad_height=0.2,
    spread=140.0,
):
    half = spread / 2.0
    points = [(0, 0), (-half, -half), (half, -half), (-half, half), (half, half)]
    return (
        cq.Workplane("XY")
        .pushPoints(points)
        .rect(pad_size, pad_size)
        .extrude(pad_height)
    )


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
