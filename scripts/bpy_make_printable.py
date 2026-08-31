"""Headless Blender job: turn any mesh into one watertight printable solid.

Usage (via Blender):
  Blender --background --python bpy_make_printable.py -- \
      <src.stl> <dst.stl> [voxel_mm] [decimate_ratio] [target_longest_mm]

voxel_mm          remesh resolution; the printable feature floor (default 0.8)
decimate_ratio    triangle reduction after remesh (default 0.5; 1 = keep all)
target_longest_mm scale the model so its longest side is this, 0 = no scaling
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
voxel = float(argv[2]) if len(argv) > 2 else 0.8
ratio = float(argv[3]) if len(argv) > 3 else 0.5
target = float(argv[4]) if len(argv) > 4 else 0.0

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=src)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

if target > 0:
    longest = max(obj.dimensions)
    if longest > 0:
        s = target / longest
        obj.scale = (s, s, s)
        bpy.ops.object.transform_apply(scale=True)

mod = obj.modifiers.new("remesh", "REMESH")
mod.mode = "VOXEL"
mod.voxel_size = max(voxel, 0.1)
bpy.ops.object.modifier_apply(modifier="remesh")

if 0 < ratio < 1:
    mod = obj.modifiers.new("dec", "DECIMATE")
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier="dec")

bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True)
d = obj.dimensions
print(f"BPY_RESULT tris={len(obj.data.polygons)} dims={d.x:.1f}x{d.y:.1f}x{d.z:.1f}")
