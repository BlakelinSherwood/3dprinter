"""Headless Blender importer -> STL converter.

Blender reads a pile of formats the Python mesh libraries can't (FBX, Collada,
3DS, X3D/VRML, USD, .blend). This loads one of those, keeps the mesh objects,
and writes a single STL the Part Studio can treat like any other import.

Usage:  blender --background --python bpy_convert.py -- <src> <dst.stl>
Prints  BPY_CONVERT_OK <bytes>  on success (parsed by the caller).
"""
import bpy
import sys
import os

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
ext = os.path.splitext(src)[1].lower()

bpy.ops.wm.read_factory_settings(use_empty=True)


def do_import():
    if ext == ".dae":
        bpy.ops.wm.collada_import(filepath=src)
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=src)
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=src)
    elif ext in (".usd", ".usdz", ".usdc", ".usda"):
        bpy.ops.wm.usd_import(filepath=src)
    elif ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=src)
    elif ext == ".blend":
        with bpy.data.libraries.load(src) as (data_from, data_to):
            data_to.objects = list(data_from.objects)
        for obj in data_to.objects:
            if obj is not None:
                bpy.context.collection.objects.link(obj)
    else:
        raise SystemExit(f"BPY_CONVERT_ERR unsupported extension {ext}")


do_import()

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("BPY_CONVERT_ERR no mesh geometry found in the file")

for obj in bpy.context.scene.objects:
    obj.select_set(obj.type == "MESH")

# Blender 4.x uses wm.stl_export; fall back to the legacy operator just in case.
try:
    bpy.ops.wm.stl_export(filepath=dst, export_selected_objects=True,
                          apply_modifiers=True)
except Exception:
    bpy.ops.export_mesh.stl(filepath=dst, use_selection=True)

print("BPY_CONVERT_OK", os.path.getsize(dst))
