#!/usr/bin/env python
"""End-to-end check for per-piece gang-plate support: combine two real poses
(one that needs support, one that doesn't) with an explicit support map,
slice the result, and verify support material only shows up under the piece
that asked for it - not spread across the whole plate, and not silently
skipped on the piece that has it on.

Uses real Studio state (models/, output/) since it exercises the same code
path the UI does. combine_models() always writes to the fixed name
"combined_plate" - there's no way to point it elsewhere - so this quarantines
whatever already exists under that name before each test and puts it back
after, rather than deleting it outright. (An earlier version of this test
did exactly that and briefly destroyed a real gang plate on 2026-09-17.)

    .venv-cad/bin/python viewer/test_multipart.py
"""
import json
import re
import shutil
import sys
import unittest
from pathlib import Path

VIEWER = Path(__file__).resolve().parent
sys.path.insert(0, str(VIEWER))
import server  # noqa: E402

STEM = "combined_plate"   # combine_models' fixed output stem - never parameterized
ARTIFACTS = [
    ("file", lambda base: server.IMPORTS / f"{STEM}.stl"),
    ("file", lambda base: server.IMPORTS / f"{STEM}.json"),
    ("file", lambda base: server.IMPORTS / f"{STEM}.parts.json"),
    ("file", lambda base: server.IMPORTS / f"{STEM}.orient.json"),
    ("dir", lambda base: server.IMPORTS / f"{STEM}.parts"),
    ("file", lambda base: server.OUTPUT / f"{STEM}.stl"),
    ("file", lambda base: server.OUTPUT / f"{STEM}.gcode"),
    ("file", lambda base: server.OUTPUT / f"{STEM}.material"),
]


def support_extrusion_bbox(gcode_path):
    """(xmin,ymin,xmax,ymax) of every Support-type extrusion move, or None."""
    cur = None
    box = None
    with open(gcode_path, errors="replace") as f:
        for line in f:
            if line.startswith(";TYPE:"):
                cur = line.strip().split(":", 1)[1]
                continue
            if cur != "Support" or line[:2] not in ("G0", "G1"):
                continue
            mx, my, me = (re.search(p + r"([\-\d.]+)", line) for p in "XYE")
            if mx and my and me and float(me.group(1)) > 0:
                x, y = float(mx.group(1)), float(my.group(1))
                box = [x, y, x, y] if box is None else [
                    min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
    return box


def object_footprint(stl_path):
    import trimesh
    m = trimesh.load(str(stl_path), force="mesh")
    lo, hi = m.bounds
    return [lo[0], lo[1], hi[0], hi[1]]


def overlaps(a, b, margin=2.0):
    return not (a[2] + margin < b[0] or b[2] + margin < a[0]
               or a[3] + margin < b[1] or b[3] + margin < a[1])


class MultipartSupportTest(unittest.TestCase):
    NAME = STEM

    @classmethod
    def setUpClass(cls):
        for m in ("buzz_laser", "buzz_sword"):
            if not (server.MODELS / f"{m}.py").is_file():
                raise unittest.SkipTest(f"{m}.py not present in this models/ dir")

    def setUp(self):
        # Quarantine whatever already lives under the "combined_plate" name -
        # a real gang plate the user made - so the test can freely overwrite
        # it and this gets moved back exactly as it was in tearDown.
        self._backup = {}
        for kind, path_fn in ARTIFACTS:
            p = path_fn(self)
            if kind == "file" and p.is_file():
                dest = p.with_suffix(p.suffix + ".testbak")
                p.replace(dest)
                self._backup[p] = dest
            elif kind == "dir" and p.is_dir():
                dest = p.with_name(p.name + ".testbak")
                if dest.exists():
                    shutil.rmtree(dest)
                p.replace(dest)
                self._backup[p] = dest

    def tearDown(self):
        for kind, path_fn in ARTIFACTS:
            p = path_fn(self)
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        for original, backup in self._backup.items():
            backup.replace(original)

    def test_only_the_marked_piece_gets_support(self):
        result = server.combine_models(["buzz_laser", "buzz_sword"],
                                       supports={"buzz_laser": True, "buzz_sword": False})
        self.assertEqual(result["model"], self.NAME)

        sidecar_path = server.IMPORTS / f"{self.NAME}.parts.json"
        self.assertTrue(sidecar_path.is_file(), "combine_models should write a parts sidecar")
        parts = {p["name"]: p for p in json.loads(sidecar_path.read_text())["parts"]}
        self.assertEqual(parts["buzz_laser"]["support"], True)
        self.assertEqual(parts["buzz_sword"]["support"], False)
        self.assertTrue(parts["buzz_laser"]["needs_support_hint"],
                        "sanity: buzz_laser's own geometry should flag as needing support")

        slice_result = server.do_slice(self.NAME, {})
        self.assertTrue(slice_result["ok"], slice_result.get("report"))
        self.assertIn("supports: buzz_laser", " ".join(slice_result["overrides"]))

        gcode = server.OUTPUT / f"{self.NAME}.gcode"
        self.assertTrue(gcode.is_file())
        sbox = support_extrusion_bbox(gcode)
        self.assertIsNotNone(sbox, "expected some support material for buzz_laser")

        laser_box = object_footprint(server.IMPORTS / f"{self.NAME}.parts" / "buzz_laser.stl")
        sword_box = object_footprint(server.IMPORTS / f"{self.NAME}.parts" / "buzz_sword.stl")
        self.assertTrue(overlaps(sbox, laser_box),
                        f"support {sbox} should sit under buzz_laser {laser_box}")
        self.assertFalse(overlaps(sbox, sword_box),
                         f"support {sbox} should NOT extend under buzz_sword {sword_box}")

        # the safety gate still applies to a multipart slice
        marker = server.OUTPUT / f"{self.NAME}.material"
        self.assertEqual(marker.read_text().strip(), "pla")

    def test_plate_without_a_supports_arg_is_unaffected(self):
        """Old call shape (no supports=) must keep behaving exactly as before -
        no sidecar, normal single-mesh slice path."""
        server.combine_models(["buzz_laser", "buzz_sword"])
        self.assertFalse((server.IMPORTS / f"{self.NAME}.parts.json").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
