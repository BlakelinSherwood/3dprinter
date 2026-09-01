# From a name to a faithful model

Goal (Blake, 2026-08-31): type "manufacturer, model, year, trim" - or give
one photo - and get a DETAILED, accurate model of that specific vehicle.

## The resolution ladder (try in order; each step down loses fidelity)

### 1. It already exists - find it (most detail, zero generation)
- **Sketchfab**: keyless search by exact identity works today and the hits
  are extraordinary - "1967 Ford Mustang Fastback" returns CC-licensed
  meshes at 500k-800k faces. Downloads need a free account's API token
  (SKETCHFAB_API_TOKEN slot, same pattern as Tripo). These are visual
  meshes: run make-printable, then toy-ify.
- **Printables search** (wired in the finder) and the military marketplaces
  from the toy roadmap (Wargaming3D, Gambody - often pre-split for print).
- Rule: search before generating. An artist who spent 80 hours on the exact
  subject beats any generator.

### 2. Blueprint-driven multiview generation (identity-accurate shape)
The unlock for subjects nobody has modeled:
- Blueprint libraries index orthographic sheets (front/side/top/rear) BY
  YEAR AND TRIM: the-blueprints.com (37k+ sheets - cars, tanks, ships,
  planes), carblueprints.info (free, no signup), drawingdatabase.com,
  getoutlines.com.
- Tripo's **multiview-to-model** (v3 endpoint in our integration's API;
  also in the FREE web studio) takes 4 views and produces dramatically
  better geometry than single-image - reviewers call the difference
  "professional-grade, 360-degree consistent" vs "warped far side".
- Workflow: name -> blueprint sheet -> crop the 4 views -> multiview
  generate (web studio free tier) -> GLB -> import -> make printable.

### 3. Single photo (today's wired lane) - good silhouette, soft detail.

### Always finish with the toy layer
make printable (Blender) -> scale -> split/pegs at the MEASURED clearances
(0.4 press / 0.5 drag / 0.6 spin) -> slice -> gate -> ask Blake -> print.

## Build queue — ALL BUILT (overnight, Aug 31 2026)
1. ✅ Sketchfab in the finder: searches merge with Printables (source
   badges, license, face counts); one-click import lights up when
   SKETCHFAB_API_TOKEN (free account) lands in ~/.zshrc, and cards
   explain the manual .glb route until then. Sketchfab page URLs also
   work in the import-by-URL box.
2. ✅ Blueprint helper: the ⌗ blueprint button splits an uploaded sheet
   into its views (gutter detection, dark-on-light and white-on-blue),
   each with an editable front/left/right/back/top label.
3. ✅ Multiview call (POST /v3/generation/multiview-to-model): Build 3D
   sends the labeled views; verified to the billing gate — lights up if
   credits appear; until then the Tripo web studio does it free with a
   manual GLB download into the ⊕ mesh button.

Sources: scenario.com Tripo 3.x multiview guides; the-blueprints.com;
carblueprints.info; drawingdatabase.com; api.sketchfab.com/v3/search.
