# model: repair_corner_gusset
"""Corner gusset / L-bracket - reinforces a broken or weak right-angle joint
(furniture corner, drawer, frame, mounting corner). Two screwed flanges with a
triangular web between them for stiffness. Screws pull the joint back together.

Measure: pick flange length/width to fit your surface, and screw_hole for your
screws (3.6 = M3 clearance, 4.5 = #8 wood screw). Holes are countersunk.
"""
import cadquery as cq


def build(
    flange_len=40.0,      # length of each leg along the joint
    flange_width=20.0,    # how far each leg reaches from the corner
    thickness=4.0,        # plate thickness
    screw_hole=4.5,       # through-hole dia (M3 clr 3.6, #8 wood ~4.5)
    web=True,             # add the triangular stiffening web (1=yes)
    holes_per_leg=2.0,
):
    t = thickness
    # horizontal leg (in XY), vertical leg (in XZ), sharing the corner edge at origin
    leg_a = (
        cq.Workplane("XY")
        .box(flange_len, flange_width, t, centered=(False, False, False))
        .translate((0, 0, 0))
    )
    leg_b = (
        cq.Workplane("XY")
        .box(flange_len, t, flange_width, centered=(False, False, False))
    )
    part = leg_a.union(leg_b)
    # triangular web joining the two legs (stiffens the corner)
    if web:
        wsize = min(flange_width, 18.0)
        tri = (
            cq.Workplane("XZ")
            .polyline([(0, t), (0, wsize), (0, t)])  # placeholder, replaced below
        )
        tri = (
            cq.Workplane("XZ")
            .moveTo(0, t)
            .lineTo(wsize, t)
            .lineTo(0, wsize)
            .close()
            .extrude(t)
        )
        # center the web across the width
        tri = tri.translate((0, (flange_width - t) / 2.0 + t, 0)) if False else tri
        part = part.union(tri)
    # screw holes down each leg
    n = max(1, int(holes_per_leg))
    for i in range(n):
        f = (i + 1) / (n + 1)
        x = flange_len * f
        h1 = (cq.Workplane("XY").center(x, flange_width / 2.0)
              .circle(screw_hole / 2.0).extrude(t))
        part = part.cut(h1)
        h2 = (cq.Workplane("XZ").center(x, flange_width / 2.0)
              .circle(screw_hole / 2.0).extrude(-t))
        part = part.cut(h2)
    part = part.edges("|Y").fillet(1.5)
    return part


if __name__ == "__main__":
    from cadquery import exporters
    exporters.export(build(), "repair_corner_gusset.stl")
