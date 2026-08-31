# Roadmap: military models -> printable toys

Goal (Blake, 2026-08-31): drop in a model of a military truck / ship / plane
and get a printable, playable toy with as much detail as possible.

## The honest reframe

Text-to-CAD (the describe button) will never reach museum detail - CSG code
tops out at "stylized". The detail already exists in the world, made by
artists. The pipeline's job is not to GENERATE detail; it is to ACQUIRE a
detailed mesh and CONVERT it into a printable, playable object:

    acquire -> make printable -> make playable -> print

## 1. Acquire (three lanes, best first)

- **Print-ready military STLs.** Specialist marketplaces sell/skip-list
  models designed for FDM: Wargaming3D (historical vehicles at wargame
  scales), Gambody (premium, split into parts already), Cults3D and
  CGTrader military sections, Printables (free). m_bergman's free 1:100/
  1:200 vehicle fleets are legendary. These often need only scale + slice.
  The Studio's finder covers Printables today; a URL import covers the rest.
- **Visual meshes** (Sketchfab CC, game-asset style): gorgeous, NOT print-
  ready (open shells, zero thickness, intersecting parts). These need lane-2
  processing below - that is what Blender is for.
- **AI image-to-3D** (Meshy / Tripo / Rodin APIs, 2026 gen): photo of a toy
  or a vehicle -> textured mesh in minutes. Tripo and Meshy both emit
  watertight STL-ready meshes now. Quality: excellent silhouette + decent
  surface, soft on crisp panel lines. Needs an API key + credits. Good for
  "I have a picture of it and nowhere sells it".

## 2. Make printable (Blender headless - INSTALLED, PROVEN)

Blender 4.5 runs scripted with no UI (`--background --python job.py`);
voxel-remeshing the 246cm3 headphone stand to watertight took 5.5s on this
Mac. Codegen writes bpy scripts the same way it writes CadQuery today.
The standard passes:

1. Voxel remesh -> one watertight solid (kills open shells, self-
   intersections, paper-thin walls). Voxel size ~= printable feature floor.
2. Decimate to a slicing-friendly triangle budget.
3. Scale to toy size FIRST, then enforce minimums: fuse/thicken anything
   under ~1mm at print scale (antennas, gun barrels, railings) or plan
   supports for it.
4. Split into parts along natural seams (hull/turret/wheels/wings) with
   plane booleans; add alignment sockets on cut faces.

## 3. Make playable (the toy layer)

- Rotating turret: peg + socket, 0.4-0.5mm clearance (free spin).
- Wheels on axles: 0.4-0.5mm; snap-fit press studs: 0.2-0.3mm.
  fit_test.py already calibrates THIS printer's real clearances - print it
  once, remember the numbers.
- Ball-and-socket for poseable parts (landing gear, guns).
- Toy-proofing: fill fragile voids with infill-heavy solids, thicken
  grab-points, round sharp tips (children + spiky masts do not mix).
- Scale guidance on a 220x220 bed: vehicles ~1:35-1:48 (hand-filling,
  detail survives a 0.4 nozzle), aircraft 1:48-1:72, ships 1:200-1:350
  split into hull sections. Multi-part beats shrinking.

## 4. Build order in the Studio

1. `bpy` job runner: like _meshlib but for Blender scripts; "make
   printable" one-click on any import (remesh/decimate/scale preset). [next]
2. Split-and-pin: describe-driven ("cut the hull at the turret ring, add a
   20mm rotation peg") -> codegen writes the bpy/trimesh booleans. The
   focus-click already supplies coordinates.
3. Optional: Meshy/Tripo API key -> photo-to-mesh lane in the finder.
4. Fit library: print fit_test once; store the winning clearances in
   design_rules so every joint uses measured numbers.

## Sources

Marketplaces: wargaming3d.com, gambody.com, cults3d.com/en/tags/wargaming,
cgtrader.com/3d-print-models/military-vehicle, printables.com.
AI mesh gen (2026): meshy.ai, tripo3d.ai, hyper3d.ai (Rodin), Hunyuan3D
(open-source, needs a big NVIDIA GPU - not viable on this Intel Mac).
Joinery: snap-fit clearance 0.2-0.3mm friction / 0.4-0.5mm free-spin;
dovetail + dowel patterns for seam joints; metal pins for high-wear joints.
