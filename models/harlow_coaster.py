# model: harlow_coaster
"""Round drink coaster, fluted grip rim, "Harlow" engraved underneath.

A 95 mm coaster with a chamfered flat base, vertical flutes around the
rim for grip, a dished top with concentric catch grooves and a shallow
central basin so condensation collects instead of sheeting off, and the
name "Harlow" engraved 0.6 mm into the underside (mirrored so it reads
correctly when the coaster is turned over).
"""

import inspect

import cadquery as cq


def _text_solid(label, size, distance, z_base):
    """Standalone extruded text compound, tolerant of cadquery API drift."""
    params = inspect.signature(cq.Workplane.text).parameters
    kwargs = {"combine": False, "halign": "center", "valign": "center"}
    if "cut" in params:
        kwargs["cut"] = False
    return (
        cq.Workplane("XY")
        .workplane(offset=z_base)
        .text(label, size, distance, **kwargs)
    )


def build(
    diameter=95.0,
    height=10.0,
    dish_depth=2.2,
    ring_count=3,
    flute_count=48,
    text_size=11.0,
):
    R = max(40.0, diameter) / 2.0
    H = max(7.0, height)

    bot_ch = 0.5          # elephant's-foot chamfer
    top_ch = 1.2          # broken top rim edge
    rim_w = 5.0           # flat landing between outer wall and dish
    dish_d = max(1.2, min(dish_depth, H - 4.0))
    floor_z = H - dish_d

    dish_R = R - rim_w
    floor_start = dish_R - 3.0
    inner_limit = 10.0

    groove_w = 2.4
    groove_d = 0.8

    # ---- revolved body: one continuous section, no fillet guesswork -------
    prof = (
        cq.Workplane("XZ")
        .moveTo(0.0, 0.0)
        .lineTo(R - bot_ch, 0.0)
        .lineTo(R, bot_ch)
        .lineTo(R, H - top_ch)
        .lineTo(R - top_ch, H)
        .lineTo(dish_R, H)
        .threePointArc(
            (dish_R - 0.9, floor_z + dish_d * 0.28),
            (floor_start, floor_z),
        )
    )

    n_rings = max(0, min(int(ring_count), 5))
    last_r = floor_start
    if n_rings > 0:
        outer_c = floor_start - 3.0
        if n_rings == 1:
            centers = [(outer_c + inner_limit) / 2.0]
        else:
            step = (outer_c - inner_limit) / (n_rings - 1)
            centers = [outer_c - i * step for i in range(n_rings)]
        for c in centers:
            prof = (
                prof.lineTo(c + groove_w / 2.0, floor_z)
                .lineTo(c + groove_w / 2.0 - 0.5, floor_z - groove_d)
                .lineTo(c - groove_w / 2.0 + 0.5, floor_z - groove_d)
                .lineTo(c - groove_w / 2.0, floor_z)
            )
        last_r = centers[-1] - groove_w / 2.0

    body = (
        prof.spline(
            [(last_r * 0.55, floor_z - 0.45), (0.0, floor_z - 0.5)],
            includeCurrent=True,
        )
        .close()
        .revolve(360, (0, 0), (0, 1))
    )

    # ---- vertical grip flutes around the outer wall ----------------------
    n_flutes = max(0, min(int(flute_count), 96))
    if n_flutes > 0:
        cut_r = 1.6
        bite = 0.7
        ring_r = R + cut_r - bite
        z0 = 1.0
        z1 = H - top_ch - 0.4
        pts = []
        for i in range(n_flutes):
            a = 2.0 * 3.141592653589793 * i / n_flutes
            pts.append((ring_r * cq.Vector(1, 0, 0).x * __import__("math").cos(a),
                        ring_r * __import__("math").sin(a)))
        flutes = (
            cq.Workplane("XY", origin=(0, 0, z0))
            .pushPoints(pts)
            .circle(cut_r)
            .extrude(z1 - z0)
        )
        body = body.cut(flutes)

    # ---- engraved name on the underside ----------------------------------
    depth = 0.6
    letters = _text_solid("Harlow", max(5.0, text_size), depth + 0.1, -0.1)
    body = body.cut(letters.mirror("YZ"))

    return body


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
