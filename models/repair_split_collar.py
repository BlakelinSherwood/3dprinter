# model: repair_split_collar
"""Split clamp collar - wraps and grips a broken or weak round rod/tube to
reinforce it, or to rejoin a snapped rod when printed as a pair. A slit lets it
open over the rod; an M3 pinch bolt through the two ears clamps it tight.

Measure with calipers: rod_diameter (the OD of the rod it grips). Pick the fit:
grip_clearance 0.4 = firm press grip (default), 0.5 = slides on then tightens.
"""
import cadquery as cq


def build(
    rod_diameter=8.0,     # measured OD of the rod, mm
    grip_clearance=0.4,   # +0.4 firm grip (measured), +0.5 for slip-then-clamp
    wall=3.0,             # collar wall thickness (>=3 for a structural clamp)
    length=16.0,          # how much of the rod it wraps along its axis
    slit_width=1.6,       # the opening gap that lets it flex closed
    bolt_hole=3.6,        # M3 clearance (measured 3.4 nominal + shrink)
):
    bore = rod_diameter + grip_clearance
    outer = bore + 2.0 * wall
    # main collar body
    collar = (
        cq.Workplane("XY")
        .circle(outer / 2.0)
        .circle(bore / 2.0)
        .extrude(length)
    )
    # the clamping ears straddle the slit on the +X side
    ear_w = bolt_hole + 4.0
    ear_out = outer / 2.0 + ear_w
    ears = (
        cq.Workplane("XY")
        .center((outer / 2.0 + ear_w / 2.0) / 1.0, 0)
        .rect(ear_w, slit_width + 2.0 * (bolt_hole + 2.0))
        .extrude(length)
    )
    collar = collar.union(ears)
    # cut the slit through the wall and the ears (radial gap on +X)
    slit = (
        cq.Workplane("XY")
        .center(outer / 2.0, 0)
        .rect(ear_w * 2.2, slit_width)
        .extrude(length)
    )
    collar = collar.cut(slit)
    # pinch bolt: through-hole across the slit (bolt + nut clamps it)
    bolt = (
        cq.Workplane("XZ")
        .workplane(offset=-(slit_width / 2.0 + bolt_hole / 2.0 + 2.0))
        .center(outer / 2.0 + ear_w / 2.0, length / 2.0)
        .circle(bolt_hole / 2.0)
        .extrude(slit_width + bolt_hole + 4.0)
    )
    collar = collar.cut(bolt)
    # chamfer the bottom (elephant-foot) and ease the top bore edge
    collar = collar.edges("<Z").chamfer(0.5)
    return collar


if __name__ == "__main__":
    from cadquery import exporters
    exporters.export(build(), "repair_split_collar.stl")
