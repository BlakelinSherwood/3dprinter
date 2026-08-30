# model: round_drink_coaster
"""Round coaster with coin-edge rim, cork recess and drip channel.

90mm disc: recessed drink well with radial drainage ribs, raised lip
milled with reeded coin-edge flutes, and a recessed underside.
"""
import cadquery as cq
import math


def build(
    diameter: float = 90.0,
    base_thickness: float = 4.0,
    lip_height: float = 2.5,
    lip_width: float = 3.2,
    reed_count: int = 72,
    reed_depth: float = 0.9,
    well_depth: float = 1.2,
    bottom_chamfer: float = 0.5,
):
    outer_radius = diameter / 2.0
    inner_radius = outer_radius - lip_width
    total_height = base_thickness + lip_height

    # --- main body: base disc plus raised outer lip -----------------------
    coaster = cq.Workplane("XY").circle(outer_radius).extrude(base_thickness)

    lip = (
        cq.Workplane("XY")
        .workplane(offset=base_thickness)
        .circle(outer_radius)
        .circle(inner_radius)
        .extrude(lip_height)
    )
    coaster = coaster.union(lip)

    # --- coin-edge reeding milled into the outer rim ----------------------
    # Cut a ring of vertical cylindrical flutes around the full perimeter so
    # the rim reads like the milled edge of a coin and gives the fingers grip.
    n = max(12, int(reed_count))
    depth = max(0.6, reed_depth)
    # Flute radius chosen so neighbouring cuts nearly touch: land ~= 0.5 * pitch.
    pitch = 2.0 * math.pi * outer_radius / n
    flute_r = min(max(0.45, pitch * 0.42), depth * 1.6)
    # Centre the cutter so it bites `depth` into the rim.
    cut_c = outer_radius + flute_r - depth

    reed_pts = []
    for i in range(n):
        a = 2.0 * math.pi * i / n
        reed_pts.append((cut_c * math.cos(a), cut_c * math.sin(a)))

    # Leave a small unfluted band top and bottom so the reeds do not break
    # the bottom chamfer or the top edge into razor-thin slivers.
    band = 0.6
    reeds = (
        cq.Workplane("XY")
        .workplane(offset=band)
        .pushPoints(reed_pts)
        .circle(flute_r)
        .extrude(total_height - 2.0 * band)
    )
    coaster = coaster.cut(reeds)

    # --- recessed drink well with a chamfered mouth ------------------------
    well_r = inner_radius
    well = (
        cq.Workplane("XZ")
        .moveTo(0.0, base_thickness)
        .lineTo(well_r - 0.8, base_thickness)
        .lineTo(well_r - 0.8 - well_depth, base_thickness - well_depth)
        .lineTo(0.0, base_thickness - well_depth)
        .close()
        .revolve(360.0, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
    )
    coaster = coaster.cut(well)

    # --- radial drainage ribs across the well floor -----------------------
    # Ribs keep the glass off any pooled condensation and let it run outward.
    rib_w = 1.6
    rib_h = 0.7
    rib_len = well_r - 3.0
    ribs = (
        cq.Workplane("XY")
        .workplane(offset=base_thickness - well_depth)
        .center(rib_len / 2.0 + 1.0, 0.0)
        .rect(rib_len, rib_w)
        .extrude(rib_h)
    )
    ribs = ribs.faces(">Z").edges("|X").fillet(rib_h * 0.45)
    ribs = ribs.translate((0, 0, 0))
    rib_solid = ribs.val()
    for k in range(1, 8):
        coaster = coaster.union(
            cq.Workplane("XY").add(rib_solid).rotate((0, 0, 0), (0, 0, 1), 45.0 * k)
        )
    coaster = coaster.union(cq.Workplane("XY").add(rib_solid))

    # central pip so a glass rests on a defined ring, not on rib ends
    coaster = coaster.union(
        cq.Workplane("XY")
        .workplane(offset=base_thickness - well_depth)
        .circle(3.0)
        .extrude(rib_h)
    )

    # --- underside relief: recessed foot ring so it never rocks ------------
    foot_w = 4.0
    relief = (
        cq.Workplane("XY")
        .circle(outer_radius - foot_w)
        .extrude(0.8)
    )
    coaster = coaster.cut(relief)

    # --- finishing edges ---------------------------------------------------
    coaster = coaster.edges("<Z").chamfer(bottom_chamfer)

    return coaster


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
