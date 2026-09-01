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
HOTEND_RE = re.compile(r"^\s*M10[49](?!\d)[^;\n]*?[SR](\d+(?:\.\d+)?)",
                       re.M | re.I)
BED_RE = re.compile(r"^\s*M1[49]0(?!\d)[^;\n]*?[SR](\d+(?:\.\d+)?)",
                    re.M | re.I)
# Value form covers Orca's leading-dot decimals ("G1 Z.4") and compact
# Marlin words with no separating space ("G1X10Y300").
NUM = r"([+-]?(?:\d+\.?\d*|\.\d+))"
AXIS_RE = {ax: re.compile(ax + NUM) for ax in "XYZ"}
ARC_I_RE = re.compile("I" + NUM)
ARC_J_RE = re.compile("J" + NUM)
ARC_R_RE = re.compile("R" + NUM)
CMD_RE = re.compile(r"([GM]\d+)")

# (nozzle_min, nozzle_max, bed_max) per material.
MATERIALS = {
    "pla": (190.0, 230.0, 70.0),
    "petg": (220.0, 260.0, 90.0),
    "tpu": (195.0, 245.0, 60.0),
}


def motion_extents(lines):
    """Track the PHYSICAL toolhead position across G0/G1/G2/G3 moves.

    Honors G90/G91 (absolute/relative), G28 homing, and G92 datum shifts -
    G92 re-bases the LOGICAL frame, so the physical offset is tracked and a
    file cannot hide travel by moving the datum ("G1 Z200 / G92 Z0 / G1
    Z200" counts as 400mm of Z). Arcs (G2/G3) are bounded conservatively by
    the full circle around their center (R-form arcs by endpoints +- |R|).
    Also reports whether the file disables firmware soft endstops (M211 S0),
    which removes the printer's own last line of defense."""
    phys = {"X": None, "Y": None, "Z": None}    # true machine position
    offset = {"X": 0.0, "Y": 0.0, "Z": 0.0}    # logical = physical - offset
    seen = {"X": [], "Y": [], "Z": []}
    absolute = True
    m211_off = False
    for line in lines:
        code = line.split(";", 1)[0].strip().upper()
        if not code:
            continue
        m = CMD_RE.match(code)
        if not m:
            continue
        cmd = m.group(1)
        if cmd == "G90":
            absolute = True
            continue
        if cmd == "G91":
            absolute = False
            continue
        if cmd == "M211" and re.search(r"S0(?!\d)", code):
            m211_off = True
            continue
        if cmd == "G28":
            axes = [a for a in "XYZ" if a in code[3:]] or list("XYZ")
            for ax in axes:
                phys[ax] = 0.0
                offset[ax] = 0.0
                seen[ax].append(0.0)
            continue
        if cmd == "G92":
            for ax, rx in AXIS_RE.items():
                mm = rx.search(code)
                if mm:
                    offset[ax] = (phys[ax] or 0.0) - float(mm.group(1))
            continue
        if cmd not in ("G0", "G1", "G2", "G3"):
            continue
        start = dict(phys)
        for ax, rx in AXIS_RE.items():
            mm = rx.search(code)
            if mm:
                v = float(mm.group(1))
                if absolute or phys[ax] is None:
                    phys[ax] = v + offset[ax]
                else:
                    phys[ax] += v
        for ax in "XYZ":
            if phys[ax] is not None:
                seen[ax].append(phys[ax])
        if cmd in ("G2", "G3") and start["X"] is not None and start["Y"] is not None:
            mi, mj = ARC_I_RE.search(code), ARC_J_RE.search(code)
            if mi or mj:
                i = float(mi.group(1)) if mi else 0.0
                jv = float(mj.group(1)) if mj else 0.0
                cx, cy = start["X"] + i, start["Y"] + jv
                r = (i * i + jv * jv) ** 0.5
                seen["X"] += [cx - r, cx + r]
                seen["Y"] += [cy - r, cy + r]
            else:
                mr = ARC_R_RE.search(code)
                if mr and phys["X"] is not None:
                    r = abs(float(mr.group(1)))
                    seen["X"] += [start["X"] - r, phys["X"] + r]
                    seen["Y"] += [start["Y"] - r, phys["Y"] + r]
    return seen, m211_off


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

    seen, m211_off = motion_extents(lines)
    if m211_off:
        failures.append("M211 S0 disables the firmware's soft endstops - refused")
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
