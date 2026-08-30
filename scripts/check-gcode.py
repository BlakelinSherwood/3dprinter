#!/usr/bin/env python3
"""Sanity-check sliced G-code before it is allowed anywhere near the printer.

Enforces the pipeline's safety rules for PLA on an Ender 3 V2:
  * hotend target 190-230 C
  * bed target <= 70 C
  * all motion inside the 220 x 220 x 250 mm build volume

Exits 0 if every check passes, 1 otherwise. Usage:
    scripts/check-gcode.py output/part.gcode
"""
import argparse
import re
import sys

# Heat commands: M104/M109 set the hotend, M140/M190 the bed. S0 is "turn off",
# emitted by the end G-code, so it is not a temperature to range-check.
HOTEND_RE = re.compile(r"^M10[49]\b[^;\n]*?\sS(\d+(?:\.\d+)?)", re.M)
BED_RE = re.compile(r"^M1[49]0\b[^;\n]*?\sS(\d+(?:\.\d+)?)", re.M)
AXIS_RE = {ax: re.compile(rf"\b{ax}(-?\d+(?:\.\d+)?)") for ax in "XYZ"}


def motion_extents(lines):
    """Track the toolhead position across G0/G1 moves, carrying unchanged axes."""
    pos = {"X": None, "Y": None, "Z": None}
    seen = {"X": [], "Y": [], "Z": []}
    for line in lines:
        if not line.startswith(("G0 ", "G1 ")):
            continue
        code = line.split(";", 1)[0]
        for ax, rx in AXIS_RE.items():
            m = rx.search(code)
            if m:
                pos[ax] = float(m.group(1))
        for ax in "XYZ":
            if pos[ax] is not None:
                seen[ax].append(pos[ax])
    return seen


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("gcode")
    ap.add_argument("--nozzle-min", type=float, default=190.0)
    ap.add_argument("--nozzle-max", type=float, default=230.0)
    ap.add_argument("--bed-max", type=float, default=70.0)
    ap.add_argument("--max-x", type=float, default=220.0)
    ap.add_argument("--max-y", type=float, default=220.0)
    ap.add_argument("--max-z", type=float, default=250.0)
    a = ap.parse_args()

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

    print(f"checked: {a.gcode} ({len(lines)} lines)")
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
    print("\nPASS: temperatures and geometry within Ender 3 V2 / PLA limits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
