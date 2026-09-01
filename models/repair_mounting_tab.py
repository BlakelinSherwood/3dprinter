# model: repair_mounting_tab
"""Replacement mounting tab / ear - the broken-off flat tab with a screw hole
that held something to a wall or frame (a speaker bracket ear, a fan mount tab,
an appliance foot). Prints a new tab with a keyed glue pad that bonds to the
flat where the old one snapped off.

Measure: tab_len/tab_width to match the original, screw_hole for the fastener,
and pad_len for how much flat surface you have to glue onto.
"""
import cadquery as cq


def build(
    tab_len=25.0,         # length of the tab from the glue pad to the hole
    tab_width=16.0,       # width of the tab
    thickness=4.0,        # tab thickness
    screw_hole=4.2,       # fastener clearance hole dia
    hole_inset=7.0,       # hole center distance from the free end
    pad_len=14.0,         # glue-pad length that bonds to the broken face
):
    t = thickness
    total_len = tab_len + pad_len
    # round the free-end corners on the plain box first (filleting after the
    # groove/hole cuts hits tiny edges and fails)
    tab = (
        cq.Workplane("XY")
        .box(total_len, tab_width, t, centered=(False, False, False))
        .edges(">X and |Z")
        .fillet(min(2.0, tab_width / 3.0))
    )
    # screw hole near the free (tab) end
    hx = total_len - hole_inset
    hole = (cq.Workplane("XY").center(hx, tab_width / 2.0)
            .circle(screw_hole / 2.0).extrude(t))
    tab = tab.cut(hole)
    # keyed glue pad: shallow grooves on the underside of the pad end give the
    # adhesive bite and relief instead of a slick butt face
    for i in range(3):
        gx = 2.5 + i * 4.0
        groove = (cq.Workplane("XY").center(gx, tab_width / 2.0)
                  .rect(1.2, tab_width - 3.0).extrude(1.0))
        tab = tab.cut(groove)
    tab = tab.faces("<Z").chamfer(0.4)
    return tab


if __name__ == "__main__":
    from cadquery import exporters
    exporters.export(build(), "repair_mounting_tab.stl")
