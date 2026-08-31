# model: army_tank
"""Simple tracked army tank with hull, turret, and gun barrel.

Two rounded tracks support a boxy hull with a sloped front glacis
plate, topped by a cylindrical turret and a forward-facing barrel.
"""
import cadquery as cq


def build(
    hull_length=120.0,
    hull_width=60.0,
    hull_height=25.0,
    track_height=15.0,
    turret_diameter=35.0,
    barrel_length=50.0,
):
    track_width = 14.0
    track_length = hull_length + 6.0
    track_offset_y = hull_width / 2.0 + track_width / 2.0 - 3.0

    track = (
        cq.Workplane("XY")
        .slot2D(track_length, track_width, angle=0)
        .extrude(track_height)
    )
    track_left = track.translate((0, track_offset_y, 0))
    track_right = track.translate((0, -track_offset_y, 0))

    hull = (
        cq.Workplane("XY")
        .workplane(offset=track_height)
        .box(hull_length, hull_width, hull_height, centered=(True, True, False))
    )
    # sloped front glacis plate, kept at 45 deg or shallower for printability
    hull = hull.edges(">X and >Z").chamfer(hull_height * 0.5)

    turret_height = 16.0
    turret_x = -hull_length * 0.05
    turret = (
        cq.Workplane("XY")
        .workplane(offset=track_height + hull_height)
        .center(turret_x, 0)
        .circle(turret_diameter / 2.0)
        .extrude(turret_height)
    )

    barrel_diameter = 8.0
    barrel_start_x = turret_x + turret_diameter / 2.0 - 2.0
    barrel_z = track_height + hull_height + turret_height * 0.55
    barrel = (
        cq.Workplane("XY")
        .circle(barrel_diameter / 2.0)
        .extrude(barrel_length)
        .rotate((0, 0, 0), (0, 1, 0), 90)
        .translate((barrel_start_x, 0, barrel_z))
    )

    tank = track_left.union(track_right).union(hull).union(turret).union(barrel)
    tank = tank.edges("<Z").chamfer(0.5)

    return tank


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
