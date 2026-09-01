# Repair helper — fixing broken toys & parts

Design and honest reality-check for the "scan a broken thing → print the fix"
idea. Written 2026-09-01 from a research pass. The reliable core (a fitting
library) is built today; the guided wizard is the roadmap.

## The honest truth first

The dream — *photograph any broken object, AI figures out the missing piece and
prints it to fit* — **can't be made reliable today, and the blocker isn't going
away soon.** The missing chunk of a unique break is, by definition, information
that isn't in the photo. Tools that look like they "complete" a shape are
pattern-matching against a catalog of whole objects (chairs, mugs); off-catalog
they guess, and the guess is never trustworthy at *the one surface that has to
mate* — which is the only surface that matters for a repair. Tripo (the app's
photo→3D) invents the unseen back of an object and has no real-world scale — great
for a decorative shape, unsafe for a part that must fit.

**The reframe that makes this real: a repair is a _mating_ problem, not an
_invention_ problem.** The fix has to grip the *surviving* part, whose dimensions
you can **measure**. So we measure the interface with calipers, and only *infer*
the missing form where a reliable, deterministic method applies (symmetry, a
catalog match, or a simple shape). AI's honest job is to **suggest the strategy**;
your calipers and deterministic geometry do the load-bearing work.

## The five repair strategies (most reliable first)

1. **Find the original** — for a mass-market item (LEGO, a named toy, an IKEA cam
   lock, a common appliance part), search for a model someone already made
   (Printables/MakerWorld + Toy-Rescue.com). No modeling. First thing to try; a
   coin-flip on coverage, but free and instant when it hits.
2. **Bridge / bracket / splint / coupler** — *the most broadly useful.* Don't
   recreate the part; print a reinforcement that mechanically bridges the break
   (a split clamp collar over a snapped rod, a corner gusset on a cracked joint, a
   sleeve that rejoins a dowel). Invents zero geometry, forgiving of small errors,
   works from a few caliper numbers. **This is where the ready-made models below
   live.**
3. **Mate-to-interface** — the original is gone but *what it plugged into* survives
   (a lost knob on an existing post, a missing battery-door catch). Measure only
   the surviving interface; the cosmetic part can be described.
4. **Mirror** — a genuinely symmetric part with one side intact (eyeglass arm,
   paired clip). Copy the good half, mirror it, add alignment pins. Deterministic —
   no AI. The "wow" case, but only when the part is *truly* symmetric.
5. **Replace whole** — a decorative/organic part where exact fit doesn't matter
   (a chess piece, a figurine limb). Tripo photo→3D + make-printable. Labeled
   "approximate — not a precision fit."

## Ready to use today: the fitting library

Four parametric repair models are in the studio now (Strategy 2). Pick one, type
your measured numbers into the sliders, and print — deterministic and reliable:

| Model | Fixes | Key measurements |
|---|---|---|
| `repair_split_collar` | reinforce / rejoin a broken **round rod** (clamps >180°) | rod diameter, wall, length |
| `repair_sleeve_coupler` | rejoin a **cleanly snapped rod/dowel** (glue both ends in) | rod diameter, insert depth |
| `repair_corner_gusset` | reinforce a **broken right-angle joint**, with screws | flange size, screw size |
| `repair_mounting_tab` | replace a **snapped-off mounting ear/tab** (keyed glue pad) | tab size, screw hole |

They build at real mm and apply the measured fit clearances (0.4 press / 0.5 drag /
0.6 free-spin) from your printed fit test. For a custom repair shape, the
describe-to-build path now has [`repair_rules.md`](../viewer/repair_rules.md)
injected — the rules that stop it inventing a fit ("capture the survivor, never a
butt joint, measured numbers are ground truth").

## The make-or-break step: measuring so it fits

Fit is a **dimensions** problem, and no software step replaces the one tool that
matters: **a $20 digital caliper (150mm, 0.01mm).** It's the single biggest
reliability multiplier — buy one before anything else.

- **Scan/photo owns the SHAPE; the caliper owns every mating NUMBER.** Never let a
  scan-derived value set a dimension that has to fit — photogrammetry has no
  absolute scale and ~0.3–0.5mm noise, fine for looks, not for a 12mm peg.
- Measure each mating feature **3 times, use the average**; measure holes with the
  inner jaws, shafts with the outer jaws.
- Say the fit in plain words — *stay firmly put / slide by hand / spin freely* —
  and the clearance is applied for you.
- **Print a 10-minute test coupon** of just the critical hole/peg before the full
  part. "10 minutes now saves a 3-hour misprint."

## If you want to scan (Strategy 4/5)

For a complex *organic* shape (not a fit-critical part): phone **photo mode** in
Polycam or KIRI Engine (not LiDAR — too coarse for small objects). Dust shiny/clear
parts with matte spray, put a ruler or coin in frame for scale, shoot 40–70 photos
all around. Then **rescale to a caliper-measured dimension** before printing — this
step is mandatory or the print comes out the wrong size. A ~$350 structured-light
scanner (Creality CR-Scan) is the upgrade if phone scans keep missing the fit.

## Roadmap (build order)

- **Phase 1 (core, mostly done):** the fitting library ✓ + `repair_rules.md` ✓;
  next, a guided **Repair wizard** — pick strategy → measure-it caliper prompts →
  generate → preview → approve.
- **Phase 2:** the deterministic **Mirror** flow (reuse the click-a-spot
  interaction + `split_plane`/mirror/`peg`), and interface-first templates.
- **Phase 3:** whole-part replace (Tripo), a bigger parametric fitting library, and
  a per-repair fit-history log that learns your printer's exact tolerances.

## Three repairs you'd actually do

1. **Snapped closet-rod bracket while staging a listing** → Bridge. Measure the rod
   and screw spacing → `repair_split_collar` / gusset → print. PLA is fine.
2. **Missing dresser knob on a surviving post** → Mate-to-interface. Measure the
   post → socket at post + 0.5 (drag) → add a described knob face.
3. **Snapped arm off a kid's toy** → Mirror if symmetric (copy the good arm), else
   a small splint/sleeve bridging the break, printed in PETG so it flexes without
   snapping again.
