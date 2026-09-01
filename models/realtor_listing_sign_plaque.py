# model: realtor_listing_sign_plaque
"""Realtor listing plaque: raised QR code plus embossed name band.

90 x 60 x 4 mm sign plate with rounded corners, a raised QR code for
https://blakesherwood.com in the upper field, and BLAKE SHERWOOD embossed
along the bottom edge. Prints flat on the bed, no supports needed.
"""

import cadquery as cq

import segno


def build(
    plate_w=90.0,
    plate_h=60.0,
    plate_t=4.0,
    module_raise=0.8,
    corner_r=5.0,
    text_size=8.0,
    text_raise=0.9,
    hang_hole_d=4.2,
):
    """Build the listing sign plaque.

    plate_w/plate_h/plate_t : outer plate size in mm.
    module_raise            : height of the raised QR modules above the field.
    corner_r                : rounded corner radius of the plate.
    text_size               : cap height of the embossed name.
    text_raise              : emboss height of the name.
    hang_hole_d             : diameter of the two hanging holes (0 disables).
    """
    url = "https://blakesherwood.com"

    # --- name band geometry (bottom strip reserved for the text) ---------
    band_h = text_size + 7.0
    field_h = plate_h - band_h

    # --- QR matrix ------------------------------------------------------
    matrix = [list(row) for row in segno.make(url, error="m").matrix]
    n = len(matrix)
    quiet = 4  # modules of bare plate all around
    total_modules = n + 2 * quiet

    # Largest pitch that fits the free field, then clamp to the 2mm floor
    # a phone camera needs on a printed code.
    field_margin = 5.0
    avail = min(plate_w - 2 * field_margin, field_h - 2 * field_margin)
    pitch = avail / total_modules
    if pitch < 2.0:
        pitch = 2.0

    qr_span = n * pitch
    qr_cx = 0.0
    qr_cy = plate_h / 2.0 - field_h / 2.0  # centre of the upper field

    # --- plate ----------------------------------------------------------
    plate = (
        cq.Workplane("XY")
        .rect(plate_w, plate_h)
        .extrude(plate_t)
        .edges("|Z")
        .fillet(corner_r)
    )

    # Recess the back slightly so the large flat face is not dead flat and
    # the plaque sits on a raised rim.
    rim = 4.0
    plate = (
        plate.faces("<Z")
        .workplane()
        .rect(plate_w - 2 * rim, plate_h - 2 * rim)
        .cutBlind(-0.8)
    )

    # Shallow border groove framing the whole sign face.
    groove_w = 1.2
    border = 2.6
    face = plate.faces(">Z").workplane(centerOption="CenterOfBoundBox")
    plate = (
        face.rect(plate_w - 2 * border, plate_h - 2 * border)
        .rect(plate_w - 2 * border - 2 * groove_w, plate_h - 2 * border - 2 * groove_w)
        .cutBlind(-0.6)
    )

    # --- QR modules -----------------------------------------------------
    # One fused block per dark module, built as a single extruded sketch.
    x0 = qr_cx - qr_span / 2.0 + pitch / 2.0
    y0 = qr_cy + qr_span / 2.0 - pitch / 2.0

    centers = []
    for r, row in enumerate(matrix):
        for c, dark in enumerate(row):
            if dark:
                centers.append((x0 + c * pitch, y0 - r * pitch))

    qr = (
        cq.Workplane("XY", origin=(0, 0, plate_t))
        .pushPoints(centers)
        .rect(pitch, pitch)
        .extrude(module_raise)
    )
    plate = plate.union(qr)

    # --- embossed name --------------------------------------------------
    name_y = -plate_h / 2.0 + band_h / 2.0
    name = (
        cq.Workplane("XY", origin=(0, name_y, plate_t))
        .text(
            "BLAKE SHERWOOD",
            text_size,
            text_raise,
            kind="bold",
            halign="center",
            valign="center",
        )
    )
    plate = plate.union(name)

    # --- hanging holes --------------------------------------------------
    if hang_hole_d > 0:
        hx = plate_w / 2.0 - corner_r - 1.0
        hy = plate_h / 2.0 - corner_r - 1.0
        plate = (
            plate.faces(">Z")
            .workplane(centerOption="CenterOfBoundBox", offset=-module_raise)
            .pushPoints([(-hx, hy), (hx, hy)])
            .hole(hang_hole_d + 0.2)
        )
        # Ease the hole mouths so the countersink reads as finished.
        plate = plate.edges(
            cq.NearestToPointSelector((-hx, hy, plate_t))
        ).chamfer(0.5)
        plate = plate.edges(
            cq.NearestToPointSelector((hx, hy, plate_t))
        ).chamfer(0.5)

    # --- bottom chamfer against elephant's foot -------------------------
    plate = plate.edges("<Z").chamfer(0.5)

    return plate


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "part.stl"
    solid = build()
    cq.exporters.export(solid, out, tolerance=0.01, angularTolerance=0.1)
    bb = solid.val().BoundingBox()
    print(f"Wrote {out}: {bb.xlen:.1f} x {bb.ylen:.1f} x {bb.zlen:.1f} mm")
