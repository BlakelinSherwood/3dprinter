"""Headless Blender job: prepare an architectural model for printing.

Buildings from Chief Architect / SketchUp / CAD viz come out as single-sided
SURFACES with no wall thickness, often non-manifold, and at full real-world
size. This job:
  1. scales the whole model to a target longest-side (fit the print bed / pick
     a display scale like 1:100),
  2. gives every zero-thickness surface a real wall thickness (Solidify),
  3. runs a manifold cleanup pass so the slicer accepts it.

Usage (via Blender):
  Blender --background --python bpy_solidify_scale.py -- \
      <src.stl> <dst.stl> [wall_mm] [target_longest_mm] [close_holes]

wall_mm            wall thickness to give surfaces, mm (default 1.6; >= 3x nozzle)
target_longest_mm  scale so the longest side becomes this, 0 = leave size as-is
close_holes        1 = attempt to close the model into a watertight solid
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
wall = float(argv[2]) if len(argv) > 2 else 1.6
target = float(argv[3]) if len(argv) > 3 else 0.0
close_holes = (len(argv) > 4 and argv[4] == "1")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=src)
obj = bpy.context.selected_objects[0]
bpy.context.view_layer.objects.active = obj

# 1) scale to a target longest side (a whole house is meters; the bed is 220mm)
if target > 0:
    longest = max(obj.dimensions)
    if longest > 0:
        s = target / longest
        obj.scale = (s, s, s)
        bpy.ops.object.transform_apply(scale=True)

# merge coincident verts first so Solidify behaves
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.0005)
bpy.ops.mesh.normals_make_consistent(inside=False)
bpy.ops.object.mode_set(mode="OBJECT")

# 2) give surfaces real thickness
mod = obj.modifiers.new("solidify", "SOLIDIFY")
mod.thickness = max(wall, 0.4)
mod.offset = 0.0               # grow both ways from the surface
mod.use_even_offset = True
bpy.ops.object.modifier_apply(modifier="solidify")

# 3) manifold cleanup so the slicer accepts it
if close_holes:
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.0005)
    try:
        bpy.ops.mesh.fill_holes(sides=0)     # 0 = all hole sizes
    except Exception:
        pass
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")

bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True,
                      apply_modifiers=True)
d = obj.dimensions
print(f"BPY_RESULT tris={len(obj.data.polygons)} "
      f"dims={d.x:.1f}x{d.y:.1f}x{d.z:.1f} wall={wall}")
