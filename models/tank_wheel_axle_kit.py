# model: tank_wheel_axle_kit
"""Snap-in wheel and axle kit for a toy tank track chassis.

Prints as one plate: two road wheels lying flat, one axle rod, and two
snap-in axle blocks whose C-clips click onto the chassis mounting bosses.
Everything is oriented bottom-face-down on z=0 with no supports needed.
"""

import cadquery as cq


def _wheel(dia, width, axle_dia, hub_dia, spoke_count, chamfer):
    """One road wheel: dished rim, spoked web, chamfered tread shoulders."""
    r = dia / 2.0
    tread_depth = max(0.8, width * 0.18)

    w = cq.Workplane("XY").circle(r).extrude(width)

    # Tread groove: a shallow V-band around the rolling surface so the wheel
    # bites the inside of a rubber/printed track instead of a slick cylinder.
    groove = (
        cq.Workplane("XZ")
        .moveTo(r + 0.01, width / 2.0)
        .lineTo(r - tread_depth, width / 2.0 - tread_depth)
        .lineTo(r - tread_depth, width / 2.0 + tread_depth)
        .close()
        .revolve(360, (0, 0, 0), (0, 1, 0))
    )
    w = w.cut(groove)

    # Dish both faces down to the hub: lighter, and it reads like a real
    # road wheel instead of a puck. Depth stays shallow so the web is solid.
    dish_depth = min(width * 0.28, (width - 2.0) / 2.0)
    if dish_depth > 0.5:
        dish = (
            cq.Workplane("XY")
            .workplane(offset=width - dish_depth)
            .circle(r - 2.2)
            .circle(hub_dia / 2.0)
            .extrude(dish_depth + 1.0)
        )
        w = w.cut(dish)
        dish_b = (
            cq.Workplane("XY")
            .workplane(offset=-1.0)
            .circle(r - 2.2)
            .circle(hub_dia / 2.0)
            .extrude(dish_depth + 1.0)
        )
        w = w.cut(dish_b)

    # Spokes across the top dish only (bottom dish spans <25mm, prints as a
    # bridge over the flat plate face; the top one gets ribs for stiffness).
    if spoke_count >= 3 and dish_depth > 0.5:
        spoke_w = max(1.6, width * 0.35)
        spoke_len = r - 2.2
        spokes = (
            cq.Workplane("XY")
            .workplane(offset=width - dish_depth)
            .polarArray(spoke_len / 2.0, 0, 360, spoke_count)
            .rect(spoke_len, spoke_w)
            .extrude(dish_depth)
        )
        # Rotate each spoke to point outward from the hub.
        spokes = cq.Workplane("XY")
        for i in range(spoke_count):
            ang = 360.0 * i / spoke_count
            spokes = spokes.union(
                cq.Workplane("XY")
                .workplane(offset=width - dish_depth)
                .center(0, 0)
                .transformed(rotate=(0, 0, ang))
                .center(spoke_len / 2.0, 0)
                .rect(spoke_len, spoke_w)
                .extrude(dish_depth)
            )
        w = w.union(spokes)

    # Hub bore, sized loose so the axle spins freely.
    w = w.faces(">Z").workplane().hole(axle_dia + 0.3 + 0.2)

    # Chamfer the outer rim edges (both ends) - kills elephant's foot on the
    # bottom and softens the top so the wheel rolls into the track guide.
    try:
        w = w.edges("%CIRCLE").edges(cq.selectors.RadiusNthSelector(-1)).chamfer(chamfer)
    except Exception:
        pass

    return w


def _axle_block(axle_dia, boss_dia, width, height, chamfer):
    """Snap block: C-clip underneath grips a chassis boss, bore carries axle."""
    bore = axle_dia + 0.3 + 0.2
    body_l = boss_dia + 6.0
    body_w = width

    b = (
        cq.Workplane("XY")
        .rect(body_l, body_w)
        .extrude(height)
        .edges("|Z")
        .fillet(min(2.0, body_w / 3.0 - 0.2))
    )

    # Axle bore runs through the block, centred at the upper half so the
    # wheel clears the chassis deck.
    bore_z = height - bore / 2.0 - 1.6
    b = b.cut(
        cq.Workplane("XZ")
        .workplane(offset=body_w / 2.0 + 1.0)
        .center(0, bore_z)
        .circle(bore / 2.0)
        .extrude(body_w + 2.0)
    )

    # C-clip pocket in the bottom face: a circular cavity with a mouth
    # narrower than the boss, so it clicks on and stays put.
    clip_r = (boss_dia + 0.3) / 2.0
    clip_top = clip_r + 0.9
    mouth = boss_dia * 0.72

    clip = (
        cq.Workplane("XZ")
        .workplane(offset=body_w / 2.0 + 1.0)
        .center(0, clip_top)
        .circle(clip_r)
        .extrude(body_w + 2.0)
    )
    throat = (
        cq.Workplane("XZ")
        .workplane(offset=body_w / 2.0 + 1.0)
        .center(0, clip_top / 2.0)
        .rect(mouth, clip_top + 0.02)
        .extrude(body_w + 2.0)
    )
    b = b.cut(clip).cut(throat)

    # Relief slot behind the clip so the two jaws can actually flex.
    b = b.cut(
        cq.Workplane("XZ")
        .workplane(offset=body_w / 2.0 + 1.0)
        .center(0, clip_top + clip_r)
        .rect(0.9, 2.4)
        .extrude(body_w + 2.0)
    )

    # Bottom perimeter chamfer against elephant's foot.
    try:
        b = b.faces("<Z").chamfer(chamfer)
    except Exception:
        pass

    return b


def _axle(axle_dia, length, chamfer):
    """Plain rod, printed lying down is weak - print it standing, short."""
    a = cq.Workplane("XY").circle(axle_dia / 2.0).extrude(length)
    # Lead-in chamfers so it threads through wheels and blocks by hand.
    try:
        a = a.edges("%CIRCLE").chamfer(min(chamfer, axle_dia / 4.0))
    except Exception:
        pass
    return a


def build(
    wheel_dia=26.0,
    wheel_width=9.0,
    axle_dia=4.0,
    axle_length=54.0,
    boss_dia=6.0,
    block_height=14.0,
    spoke_count=6,
    bottom_chamfer=0.5,
):
    """Wheel/axle kit laid out on one print plate, all bottoms at z=0."""
    hub_dia = axle_dia + 6.0
    block_width = wheel_width + 3.0

    wheel = _wheel(wheel_dia, wheel_width, axle_dia, hub_dia, int(spoke_count),
                   bottom_chamfer)
    block = _axle_block(axle_dia, boss_dia, block_width, block_height,
                        bottom_chamfer)
    rod = _axle(axle_dia, axle_length, bottom_chamfer)

    gap = 6.0
    x_w = wheel_dia / 2.0
    x_b = wheel_dia + gap + (boss_dia + 6.0) / 2.0
    y_pitch = wheel_dia / 2.0 + block_width / 2.0 + gap

    plate = cq.Workplane("XY")
    plate = plate.union(wheel.translate((-x_b, y_pitch, 0)))
    plate = plate.union(wheel.translate((-x_b, -y_pitch, 0)))
    plate = plate.union(block.translate((0, y_pitch, 0)))
    plate = plate.union(block.translate((0, -y_pitch, 0)))
    plate = plate.union(rod.translate((x_b, y_pitch, 0)))
    plate = plate.union(rod.translate((x_b, -y_pitch, 0)))

    return plate


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
