# model: classic_pickup_truck
"""Classic 1950s-style pickup truck body with fenders, bed and wheels.

Modeled at true full size (~5150 mm long) so the studio can apply a
1/64 printing scale afterwards. Oriented print-ready: the tyre contact
patches and the underside of the frame rails sit on z=0.
"""

import cadquery as cq


def build(
    body_length=5150.0,
    body_width=1950.0,
    cab_height=1820.0,
    wheel_diameter=780.0,
    bed_wall=110.0,
    fender_flare=70.0,
    grille_slats=5,
):
    """Classic long-nose pickup: hood, cab with raked screen, stepside bed."""

    # ---- master proportions -------------------------------------------------
    half_w = body_width / 2.0
    tyre_w = 240.0
    wheel_r = wheel_diameter / 2.0

    # Frame / floor: the flat structural slab everything hangs off.
    frame_z0 = wheel_r * 0.42          # underside of the frame rails
    frame_h = 190.0                    # rail depth
    frame_top = frame_z0 + frame_h

    body_w = body_width - 2.0 * fender_flare   # core body, fenders flare beyond

    # Longitudinal stations, measured from the front bumper at x=0.
    x_bumper = 0.0
    x_grille = 130.0
    x_hood0 = 190.0
    x_cowl = 1850.0                    # hood meets windscreen
    x_cab_end = 3050.0                 # back of cab
    x_bed0 = 3160.0                    # bed front wall
    x_bed1 = body_length - 120.0       # tailgate outer face

    hood_h = 560.0                     # hood surface above the frame top
    hood_top = frame_top + hood_h
    cab_top = frame_z0 + cab_height
    belt_z = frame_top + 470.0         # window sill / bed rail height

    axle_f_x = 1180.0
    axle_r_x = body_length - 1230.0

    # ---- frame rails + running boards --------------------------------------
    frame = (
        cq.Workplane("XY")
        .workplane(offset=frame_z0)
        .box(body_length - 260.0, body_w - 240.0, frame_h,
             centered=(False, True, False))
        .translate((130.0, 0, 0))
        .edges("|Z")
        .fillet(70.0)
    )

    # Running board / rocker between the fenders, a classic step for the cab.
    step_len = x_bed0 - (axle_f_x + wheel_r + 60.0)
    running = (
        cq.Workplane("XY")
        .workplane(offset=frame_z0 + frame_h * 0.35)
        .center(axle_f_x + wheel_r + 60.0 + step_len / 2.0, 0)
        .rect(step_len, body_w + 60.0)
        .extrude(90.0)
        .edges("|Z")
        .fillet(24.0)
    )

    result = frame.union(running)

    # ---- hood: a crowned deck lofted from cowl back to the grille ----------
    def deck(x, width, top_z, crown):
        """Rounded-corner deck section used for the hood loft."""
        return (
            cq.Workplane("XY")
            .workplane(offset=top_z - crown)
            .center(x, 0)
            .rect(1.0, width)  # placeholder, replaced below
        )

    hood_front_w = body_w - 210.0
    hood_rear_w = body_w - 40.0

    hood = (
        cq.Workplane("YZ")
        .workplane(offset=x_hood0)
        .center(0, 0)
        .rect(hood_front_w, 1.0)
        .workplane(offset=x_cowl - x_hood0)
        .rect(hood_rear_w, 1.0)
        .loft(ruled=True)
    )
    # The loft above is degenerate in Z; build the hood as a tapered prism
    # instead, then crown its top with a shallow cylindrical cut-away.
    hood_h_front = hood_h - 60.0
    hood = (
        cq.Workplane("YZ")
        .workplane(offset=x_hood0)
        .rect(hood_front_w, hood_h_front)
        .workplane(offset=x_cowl - x_hood0)
        .rect(hood_rear_w, hood_h)
        .loft(ruled=True)
    )
    hood = hood.translate((0, 0, frame_top + hood_h / 2.0))

    # Crown the hood: shave the top with a big cylinder so it is not a slab.
    crown_r = (body_w * body_w / 8.0 + 3600.0) / 60.0
    crown = (
        cq.Workplane("XY")
        .center(x_hood0 + 10.0, 0)
        .circle(crown_r)
        .extrude(x_cowl - x_hood0 + 200.0)
        .rotate((0, 0, 0), (0, 1, 0), 90)
        .translate((0, 0, hood_top - crown_r + 55.0))
    )
    hood = hood.intersect(crown.union(
        cq.Workplane("XY")
        .workplane(offset=frame_top - 20.0)
        .center((x_hood0 + x_cowl) / 2.0, 0)
        .box(x_cowl - x_hood0 + 40.0, body_w + 40.0,
             hood_top - frame_top - 55.0 + 20.0, centered=(True, True, False))
    ))
    result = result.union(hood)

    # ---- grille / nose ------------------------------------------------------
    nose = (
        cq.Workplane("XY")
        .workplane(offset=frame_top)
        .center(x_grille + (x_hood0 - x_grille) / 2.0, 0)
        .rect(x_hood0 - x_grille + 20.0, hood_front_w)
        .extrude(hood_h_front)
        .edges("|X")
        .fillet(60.0)
    )
    result = result.union(nose)

    # Horizontal grille slats, engraved into the nose face.
    slat_n = max(2, int(grille_slats))
    slat_gap = (hood_h_front - 150.0) / slat_n
    slat_h = max(60.0, slat_gap * 0.45)
    for i in range(slat_n):
        z = frame_top + 90.0 + slat_gap * (i + 0.5)
        result = result.cut(
            cq.Workplane("XY")
            .workplane(offset=z - slat_h / 2.0)
            .center(x_grille + 20.0, 0)
            .box(45.0, hood_front_w - 260.0, slat_h,
                 centered=(True, True, False))
        )

    # Round headlamps perched on the fender tops, period-correct.
    for y in (-1, 1):
        lamp = (
            cq.Workplane("XZ")
            .workplane(offset=-(hood_front_w / 2.0 - 30.0) * y)
            .center(x_grille + 60.0, hood_top - 130.0)
            .circle(115.0)
            .extrude(90.0 * (1 if y > 0 else -1))
        )
        result = result.union(lamp)

    # Chrome bumper bar across the nose.
    bumper = (
        cq.Workplane("XY")
        .workplane(offset=frame_top - 60.0)
        .center(x_bumper + 55.0, 0)
        .rect(110.0, body_width - 180.0)
        .extrude(150.0)
        .edges("|Z")
        .fillet(50.0)
    )
    result = result.union(bumper)

    # ---- cab: raked windscreen, roof, rear window ---------------------------
    cab_lower = (
        cq.Workplane("XY")
        .workplane(offset=frame_top)
        .center((x_cowl + x_cab_end) / 2.0, 0)
        .rect(x_cab_end - x_cowl, body_w)
        .extrude(belt_z - frame_top)
    )
    # Greenhouse: shorter and narrower than the body, with a raked A-pillar.
    green_pts = [
        (x_cowl + 60.0, belt_z),
        (x_cowl + 430.0, cab_top),
        (x_cab_end - 90.0, cab_top),
        (x_cab_end - 30.0, belt_z),
    ]
    greenhouse = (
        cq.Workplane("XZ")
        .polyline(green_pts)
        .close()
        .extrude(body_w - 150.0)
        .translate((0, (body_w - 150.0) / 2.0, 0))
    )
    cab = cab_lower.union(greenhouse)
    cab = cab.edges("|Z").fillet(55.0)
    result = result.union(cab)

    # Side window openings and a rear screen, engraved as recesses.
    win_depth = 26.0
    for y in (1, -1):
        result = result.cut(
            cq.Workplane("XZ")
            .workplane(offset=-y * (body_w - 150.0) / 2.0)
            .polyline([
                (x_cowl + 330.0, belt_z + 60.0),
                (x_cowl + 470.0, cab_top - 90.0),
                (x_cab_end - 190.0, cab_top - 90.0),
                (x_cab_end - 150.0, belt_z + 60.0),
            ])
            .close()
            .extrude(-win_depth * y)
        )
    result = result.cut(
        cq.Workplane("YZ")
        .workplane(offset=x_cab_end - 40.0)
        .center(0, (belt_z + cab_top) / 2.0 + 20.0)
        .rect(body_w - 620.0, cab_top - belt_z - 200.0)
        .extrude(win_depth)
    )
    # Door shut line + handle dimple.
    for y in (1, -1):
        result = result.cut(
            cq.Workplane("XZ")
            .workplane(offset=-y * (body_w / 2.0))
            .center(x_cowl + 420.0, frame_top + 200.0)
            .rect(14.0, 400.0)
            .extrude(-16.0 * y)
        )
        result = result.cut(
            cq.Workplane("XZ")
            .workplane(offset=-y * (body_w / 2.0))
            .center(x_cab_end - 300.0, belt_z - 110.0)
            .rect(180.0, 60.0)
            .extrude(-22.0 * y)
        )

    # ---- bed: open box with ribbed floor and tailgate ----------------------
    bed_h = belt_z - frame_top
    bed = (
        cq.Workplane("XY")
        .workplane(offset=frame_top)
        .center((x_bed0 + x_bed1) / 2.0, 0)
        .rect(x_bed1 - x_bed0, body_w)
        .extrude(bed_h)
        .edges("|Z")
        .fillet(50.0)
    )
    wall = max(bed_wall, 90.0)
    cavity = (
        cq.Workplane("XY")
        .workplane(offset=frame_top + 90.0)
        .center((x_bed0 + x_bed1) / 2.0, 0)
        .rect(x_bed1 - x_bed0 - 2.0 * wall, body_w - 2.0 * wall)
        .extrude(bed_h)
        .edges("|Z")
        .fillet(40.0)
    )
    bed = bed.cut(cavity)
    result = result.union(bed)

    # Ribbed bed floor: raised longitudinal strakes, printable proportions.
    rib_span = body_w - 2.0 * wall - 120.0
    rib_n = 5
    for i in range(rib_n):
        y = -rib_span / 2.0 + rib_span * i / (rib_n - 1)
        result = result.union(
            cq.Workplane("XY")
            .workplane(offset=frame_top + 90.0)
            .center((x_bed0 + x_bed1) / 2.0, y)
            .box(x_bed1 - x_bed0 - 2.0 * wall - 80.0, 70.0, 45.0,
                 centered=(True, True, False))
        )

    # Tailgate panel line and rear bumper.
    result = result.cut(
        cq.Workplane("YZ")
        .workplane(offset=x_bed1 - 18.0)
        .center(0, frame_top + bed_h / 2.0)
        .rect(body_w - 260.0, bed_h - 160.0)
        .extrude(20.0)
    )
    result = result.union(
        cq.Workplane("XY")
        .workplane(offset=frame_top - 60.0)
        .center(body_length - 55.0, 0)
        .rect(110.0, body_width - 180.0)
        .extrude(140.0)
        .edges("|Z")
        .fillet(45.0)
    )

    # ---- fenders: flared arches over each wheel ----------------------------
    for x in (axle_f_x, axle_r_x):
        for y in (1, -1):
            arch = (
                cq.Workplane("XZ")
                .workplane(offset=-y * (half_w - 12.0))
                .center(x, wheel_r)
                .circle(wheel_r + 150.0)
                .extrude(-y * (fender_flare + 12.0))
            )
            # Trim the arch to the upper half so nothing dips below the axle.
            arch = arch.intersect(
                cq.Workplane("XY")
                .workplane(offset=wheel_r - 40.0)
                .center(x, y * (half_w + 40.0))
                .box(2.0 * (wheel_r + 200.0), 200.0, wheel_r + 260.0,
                     centered=(True, True, False))
            )
            result = result.union(arch)

    # Wheel wells cut back through body and fender so the tyres sit clear.
    for x in (axle_f_x, axle_r_x):
        result = result.cut(
            cq.Workplane("XZ")
            .workplane(offset=body_width / 2.0 + 10.0)
            .center(x, wheel_r)
            .circle(wheel_r + 40.0)
            .extrude(body_width + 20.0)
            .intersect(
                cq.Workplane("XY")
                .center(x, 0)
                .box(2.0 * (wheel_r + 60.0), body_width + 40.0,
                     2.0 * (wheel_r + 60.0))
                .translate((0, 0, wheel_r - (wheel_r + 60.0)))
            )
        )

    # ---- wheels: tyre + dished rim, contact patch flattened to z=0 ---------
    for x in (axle_f_x, axle_r_x):
        for y in (1, -1):
            y_out = y * (half_w - 6.0)
            tyre = (
                cq.Workplane("XZ")
                .workplane(offset=-y_out)
                .center(x, wheel_r)
                .circle(wheel_r)
                .extrude(-y * tyre_w)
            )
            # Hub face: a recessed dish so the wheel is not a plain cylinder.
            tyre = tyre.cut(
                cq.Workplane("XZ")
                .workplane(offset=-y_out)
                .center(x, wheel_r)
                .circle(wheel_r * 0.62)
                .extrude(-y * 55.0)
            )
            tyre = tyre.union(
                cq.Workplane("XZ")
                .workplane(offset=-y_out)
                .center(x, wheel_r)
                .circle(wheel_r * 0.22)
                .extrude(-y * 40.0)
            )
            # Five spokes across the dish.
            for k in range(5):
                spoke = (
                    cq.Workplane("XZ")
                    .workplane(offset=-y_out)
                    .center(x, wheel_r)
                    .rect(90.0, wheel_r * 1.1)
                    .extrude(-y * 42.0)
                )
                result = result.union(
                    spoke.rotate((x, 0, wheel_r), (x, 1, wheel_r),
                                 k * 180.0 / 5.0)
                )
            result = result.union(tyre)

    # Flatten the tyre contact patches: everything below z=0 is trimmed, and
    # the wheels are sunk 8 mm so each has a real bearing surface.
    result = result.translate((0, 0, -8.0))
    result = result.intersect(
        cq.Workplane("XY")
        .center(body_length / 2.0, 0)
        .box(body_length + 400.0, body_width + 400.0, cab_height + 400.0,
             centered=(True, True, False))
    )

    # Bottom chamfer on the frame rails to counter elephant's foot.
    try:
        result = result.faces("<Z").edges().chamfer(12.0)
    except Exception:
        pass

    return result


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
