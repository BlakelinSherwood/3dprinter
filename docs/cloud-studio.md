# Cloud studio (designing from a phone)

Part Studio can also run on a hosted server, so parts can be designed from a
phone away from home and then brought into the home studio to print.

## What it is

- The same `viewer/server.py`, started with `STUDIO_MODE=cloud` (see the
  `Dockerfile`). It runs on Railway, built from this repo; pushes to `main`
  redeploy it.
- **Design only**: describe / change / refine, sliders, scale, rotation,
  Printables search and imports (STL, OBJ, PLY, OFF, GLB, GLTF, 3MF, STEP,
  IGES, BREP), auto-orient, gang plates.
- **Refused in the cloud** (by the server, not just hidden): slicing, uploads,
  the OctoPrint queue, filament lookup, and the Blender tools (make printable,
  solidify walls, FBX / DAE / USD imports). The cloud never talks to the printer.
- Data lives on a Railway volume at `/data`. The repo's models are copied in on
  every start; a copy that was changed in the cloud is never overwritten.
- The page lays itself out for phones (3D view pinned on top, controls
  scrolling underneath). The home studio uses the same layout on a narrow
  window.

## Security

- One password, `STUDIO_PASSWORD` (12+ characters), set as a Railway variable.
  Without it the studio only shows a setup page.
- Sign-ins are signed tokens: 30 days on the phone, 180 days for the home
  studio's link. Changing the password signs every device out.
- Wrong passwords: 5 per address and 20 overall in 15 minutes, then sign-in is
  locked for the rest of that window (existing sessions keep working).
- The server runs as a non-root user inside the container.

## Railway variables (service → Variables)

| Variable | Purpose |
| --- | --- |
| `STUDIO_PASSWORD` | the sign-in password - required |
| `CLAUDE_CODE_OAUTH_TOKEN` | printed by `claude setup-token` on the Mac; makes *Build it*, *Make the change* and *refine* work in the cloud on the Claude plan. `ANTHROPIC_API_KEY` also works (it wins if both are set). |
| `STUDIO_PUBLIC_HOST` | only needed if a custom domain is added |

## Bringing a design home

1. In the home studio, expand **☁ From your phone**.
2. First time only: enter the cloud address and password, then **Connect**. The
   Mac keeps only a sign-in token, in `~/.config/part-studio/cloud.json` (0600).
3. Parts made or changed on the phone are listed. **bring home** copies the part
   into `models/`, together with any mesh it is built on and its last slider,
   scale and rotation settings. If there's a different local copy, the button
   asks **replace mine?** first, and yours is kept in `models/.history` so
   **undo change** swaps back.
4. Slice, check, upload and print as usual. Printing still goes through Claude
   with an explicit yes.

## Tests

```bash
.venv-cad/bin/python viewer/test_cloud.py
```

Starts a cloud and a home studio on spare ports with throwaway data, then
checks the sign-in gate, the refusals, remembered settings, the round trip
home, and bundle validation.
