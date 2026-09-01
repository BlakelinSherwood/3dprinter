# model: repair_sleeve_coupler
"""Sleeve coupler - rejoins a cleanly snapped round rod or dowel. Both broken
ends slide into a tube with a center stop, then get glued. A chamfered mouth
makes insertion easy; the center ridge sets equal insertion depth on each side.

Measure with calipers: rod_diameter (OD of the broken rod). fit_clearance 0.5
lets the ends slide in for gluing; 0.4 is a tighter press if you're not gluing.
"""
import cadquery as cq


def build(
    rod_diameter=8.0,     # measured OD of the rod, mm
    fit_clearance=0.5,    # +0.5 slide-in for glue (measured), +0.4 press
    wall=2.5,             # sleeve wall thickness
    insert_depth=12.0,    # how far each end goes in (>= 1.5x rod dia for strength)
    stop_thick=2.0,       # center stop ridge thickness
):
    bore = rod_diameter + fit_clearance
    outer = bore + 2.0 * wall
    total = 2.0 * insert_depth + stop_thick
    sleeve = (
        cq.Workplane("XY")
        .circle(outer / 2.0)
        .extrude(total)
    )
    # bore from the bottom up to the stop
    lower = (
        cq.Workplane("XY")
        .circle(bore / 2.0)
        .extrude(insert_depth)
    )
    # bore from the top down to the stop
    upper = (
        cq.Workplane("XY")
        .workplane(offset=insert_depth + stop_thick)
        .circle(bore / 2.0)
        .extrude(insert_depth)
    )
    sleeve = sleeve.cut(lower).cut(upper)
    # chamfer both mouths so the rod ends start easily
    sleeve = sleeve.faces("<Z").chamfer(0.8).faces(">Z").chamfer(0.8)
    return sleeve


if __name__ == "__main__":
    from cadquery import exporters
    exporters.export(build(), "repair_sleeve_coupler.stl")
