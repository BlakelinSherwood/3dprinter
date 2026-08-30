# Design rules: Ender 3 V2, PLA, 0.4mm nozzle, 0.2mm layers

Geometry (units are mm, Z is up):
- Build volume 220 x 220 x 250. The part MUST fit; prefer <= 200 in X/Y.
- Model print-ready: the largest flat face is the bottom, sitting exactly on
  the z=0 plane. No rafts, no supports - keep overhangs at 45 degrees or less.
- Bridges (flat spans in the air between two supported ends): 25mm max.

Feature sizes (line width 0.44):
- Walls at least 1.32 (three perimeters). Never less than 0.88.
- Embossed text/logos: at least 0.8 wide, 0.6 tall. Engraved: 0.6 deep.
- Free-standing pins at least 3.0 diameter; prefer ribs over pins.
- Small holes print undersized: add 0.2 to any nominal hole diameter.

Fits and clearances (between this print and another part):
- Press fit: +0.1 on the hole. Snug sliding fit: +0.2. Loose/drop-in: +0.3.
- M3 screw clearance hole: 3.4. M3 self-tap into plastic: 2.8.

Detailing:
- Chamfer the bottom perimeter 0.4-0.6 at 45 degrees (counters elephant's foot).
- Fillet vertical edges >= 0.5 where the shape allows; avoid tiny fillets on
  top edges (they slice into fragile sliver perimeters).
- Avoid large flat tops directly over sparse infill deeper than 6mm.
