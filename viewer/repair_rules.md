# Repair-part design rules (appended to design_rules.md for repair jobs)

This is a REPAIR part. It must interface with an EXISTING object whose mating
dimensions the user has MEASURED (with calipers). Those measured numbers are
ground truth: apply the measured clearances to them, and DO NOT invent or guess
any dimension the user did not give. If a needed mating dimension is missing,
expose it as a prominent `build()` parameter with a safe default and say so in
the docstring — never silently assume a fit dimension.

A repair is a MATING problem, not an invention problem. Build only what is
needed to (a) grip/locate on the surviving part and (b) restore the function.

## Measured clearances (from the printed fit_test — trust these over any table)
- Firm press grip (stays put): hole/socket = shaft + **0.4**
- Slide/pull by hand (drag): + **0.5**
- Spins/moves freely: + **0.6**
- Small holes also print ~0.15mm undersized — add **0.2** to the nominal hole.
- Put precision on the SHAFT/peg (externals print truer and can be sanded); give
  the hole the clearance.
- M3 screw clearance hole **3.6**; M3 self-tap into plastic **2.9**; heat-set M3
  insert pilot **~4.0**.

## Capture the survivor — never a butt joint
A repair must physically capture what remains:
- A clamp/collar that wraps **> 180°** of a rod, or
- A socket the broken stub inserts into (stub dia **+0.4** press / **+0.5** glue), or
- A keyed glue lap with generous overlap and small adhesive-relief grooves.
Never join two pieces on a flat butt face alone — it will pop off.

## Strength & orientation
- Structural clamps/collars/splints: min wall **3mm**.
- Snap/cantilever features: beam **4–6mm wide × 1.5–2mm thick**, hook depth
  **~1.5mm**, engagement clearance **0.3–0.5mm**. Orient so layer lines run
  ALONG the beam (across the beam = it cracks at the root).
- Screw bosses: wall **≥ 2 perimeters**, keep **1.5–2mm** from thin outer walls,
  add ribs on tall or side-loaded bosses.
- Chamfer the bottom perimeter **0.4–0.6** (counters elephant's foot).

## Material logic
- Anything that FLEXES repeatedly (a snap clip, a living hinge, a spring tab):
  recommend **PETG** — PLA is brittle and snaps once.
- Clamps, collars, brackets, gussets that only grip/hold: **PLA is fine**.

## Ready-made repair models already in the library (prefer these to fresh codegen)
- `repair_split_collar` — clamp/reinforce or rejoin a broken round rod
- `repair_sleeve_coupler` — rejoin a cleanly snapped rod/dowel (glue both ends in)
- `repair_corner_gusset` — reinforce a broken right-angle joint, screws
- `repair_mounting_tab` — replace a snapped-off mounting ear/tab with a glue pad
When a break matches one of these, use it with the user's measured numbers rather
than generating new geometry — it's more reliable and instant.
