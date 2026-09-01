#!/usr/bin/env python3
"""Sanity-check sliced G-code before it is allowed anywhere near the printer.

Enforces the pipeline's safety rules on an Ender 3 V2:
  * hotend and bed targets inside the selected material's envelope
  * all motion inside the 220 x 220 x 250 mm build volume

Material envelopes (--material, default pla):
    pla   nozzle 190-230  bed <=70
    petg  nozzle 220-260  bed <=90
    tpu   nozzle 195-245  bed <=60

Exits 0 if every check passes, 1 otherwise. Usage:
    scripts/check-gcode.py [--material petg] output/part.gcode
"""
import argparse
import re
import sys

# Heat commands: M104/M109 set the hotend, M140/M190 the bed. S0 is "turn off",
# emitted by the end G-code, so it is not a temperature to range-check.
HOTEND_RE = re.compile(r"^M10[49]\b[^;\n]*?\sS(\d+(?:\.\d+)?)", re.M)
BED_RE = re.compile(r"^M1[49]0\b[^;\n]*?\sS(\d+(?:\.\d+)?)", re.M)
AXIS_RE = {ax: re.compile(rf"\b{ax}(-?\d+(?:\.\d+)?)") for ax in "XYZ"}

# (nozzle_min, nozzle_max, bed_max) per material.
MATERIALS = {
    "pla": (190.0, 230.0, 70.0),
    "petg": (220.0, 260.0, 90.0),
    "tpu": (195.0, 245.0, 60.0),
}


def motion_extents(lines):
    """Track the toolhead across G0/G1/G2/G3 moves, honoring absolute vs
    relative positioning (G90/G91), G92 resets, and G28 homing. Arc moves
    contribute their endpoints (this pipeline slices with arc fitting off).
    Relative moves accumulate onto the current position - an end-gcode
    "G91 / G1 Z10" near the ceiling counts as real travel."""
    pos = {"X": None, "Y": None, "Z": None}
    seen = {"X": [], "Y": [], "Z": []}
    absolute = True
    for line in lines:
        code = line.split(";", 1)[0].strip()
        if not code:
            continue
        cmd = code.split(None, 1)[0].upper()
        if cmd == "G90":
            absolute = True
            continue
        if cmd == "G91":
            absolute = False
            continue
        if cmd == "G28":
            axes = [a for a in "XYZ" if a in code.upper()] or list("XYZ")
            for ax in axes:
                pos[ax] = 0.0
                seen[ax].append(0.0)
            continue
        if cmd == "G92":
            for ax, rx in AXIS_RE.items():
                m = rx.search(code)
                if m:
                    pos[ax] = float(m.group(1))
            continue
        if cmd not in ("G0", "G1", "G2", "G3"):
            continue
        for ax, rx in AXIS_RE.items():
            m = rx.search(code)
            if m:
                v = float(m.group(1))
                pos[ax] = v if (absolute or pos[ax] is None) else pos[ax] + v
        for ax in "XYZ":
            if pos[ax] is not None:
                seen[ax].append(pos[ax])
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gcode")
    ap.add_argument("--material", choices=sorted(MATERIALS), default="pla")
    ap.add_argument("--nozzle-min", type=float, default=None)
    ap.add_argument("--nozzle-max", type=float, default=None)
    ap.add_argument("--bed-max", type=float, default=None)
    ap.add_argument("--max-x", type=float, default=220.0)
    ap.add_argument("--max-y", type=float, default=220.0)
    ap.add_argument("--max-z", type=float, default=250.0)
    a = ap.parse_args()
    mat = MATERIALS[a.material]
    if a.nozzle_min is None:
        a.nozzle_min = mat[0]
    if a.nozzle_max is None:
        a.nozzle_max = mat[1]
    if a.bed_max is None:
        a.bed_max = mat[2]

    src = open(a.gcode, errors="replace").read()
    lines = src.splitlines()
    failures = []

    hotend = [float(t) for t in HOTEND_RE.findall(src)]
    bed = [float(t) for t in BED_RE.findall(src)]

    active_hotend = [t for t in hotend if t > 0]
    if not active_hotend:
        failures.append("no hotend temperature command (M104/M109) found")
    for t in sorted(set(active_hotend)):
        if not a.nozzle_min <= t <= a.nozzle_max:
            failures.append(f"hotend {t}C outside {a.nozzle_min}-{a.nozzle_max}C")
    for t in sorted(set(bed)):
        if t > a.bed_max:
            failures.append(f"bed {t}C above {a.bed_max}C")

    seen = motion_extents(lines)
    limits = {"X": (0.0, a.max_x), "Y": (0.0, a.max_y), "Z": (0.0, a.max_z)}
    extents = {}
    for ax, (lo, hi) in limits.items():
        vals = seen[ax]
        if not vals:
            failures.append(f"no {ax} motion found")
            continue
        extents[ax] = (min(vals), max(vals))
        if min(vals) < lo or max(vals) > hi:
            failures.append(
                f"{ax} travel {min(vals):.2f}..{max(vals):.2f} outside {lo}..{hi}mm"
            )

    print(f"checked: {a.gcode} ({len(lines)} lines, material {a.material})")
    print(f"  hotend: {sorted(set(active_hotend)) or 'none'} C")
    print(f"  bed:    {sorted({t for t in bed if t > 0}) or 'none'} C")
    for ax in "XYZ":
        if ax in extents:
            lo, hi = extents[ax]
            print(f"  {ax}: {lo:.2f} .. {hi:.2f} mm (limit {limits[ax][1]:.0f})")

    if failures:
        print("\nUNSAFE - do not print:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"\nPASS: temperatures and geometry within Ender 3 V2 / {a.material.upper()} limits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
