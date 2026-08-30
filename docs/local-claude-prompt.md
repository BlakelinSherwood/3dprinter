# Handoff prompt for a local Claude Code session

Run `claude` inside `~/3dprinter` on the Mac, then paste the prompt below.
(Approve the project's `.mcp.json` MCP server when it asks; `/mcp` verifies it.)

---

I'm setting up a pipeline so you can generate 3D-printable parts, slice them,
and queue them on my printer. Work on my Mac, in this repo (~/3dprinter), which
already contains the setup kit: setup-mac.sh, Ender 3 V2 OrcaSlicer profiles in
profiles/ender3v2/, a test cube in test-parts/, helper scripts in scripts/, and
.mcp.json wiring the mcp-3d-printer-server MCP server to OctoPrint.

Hardware/software state:
- Ender 3 V2, connected to this Mac over USB. Bed 220x220x250mm, PLA, 0.4 nozzle.
- OrcaSlicer 2.4.2 installed at /Applications/OrcaSlicer.app.
- Node/npx available.
- OctoPrint is intended to run from ~/octoprint-venv on port 5001, but the
  install FAILED: the venv was created with Python 3.14, which OctoPrint doesn't
  support, so pip fell back to OctoPrint 1.8.7 and died building PyYAML 5.4.1
  ("'build_ext' object has no attribute 'cython_sources'"). The venv has no
  octoprint binary. README's "Installing OctoPrint itself (macOS)" section has
  the Python 3.13 fix.

Please:
1. Rebuild the OctoPrint venv on Python 3.13 and install OctoPrint (should get
   1.10+, not 1.8.7). Start it on port 5001 in the background and confirm it
   responds. Tell me when to do the first-run wizard in the browser and when to
   generate an Application Key (Settings > Application Keys) — I'll paste the key
   back to you and add it to ~/.zshrc as OCTOPRINT_API_KEY.
2. Run ./setup-mac.sh and drive every step to [ok], fixing what fails. This
   test-slices test-parts/calibration_cube_20mm.stl and uploads the G-code to
   OctoPrint.
3. Verify the MCP server works end-to-end: get_printer_status, then slice and
   upload the cube through the MCP tools rather than the shell scripts, so we
   know the path I'll actually use in future conversations is real.
4. Help me connect the printer in OctoPrint's Connection panel (serial port,
   baud) and confirm you can read live temperatures.
5. Commit and push any fixes you make to the repo, so the setup stays
   reproducible.

Safety rules, permanent:
- NEVER start a physical print without asking me first and getting a yes.
- Uploads must use select=false / print=false.
- Sanity-check generated G-code before any print: PLA nozzle 190-230C, bed <=70C,
  and geometry within the 220x220x250mm build volume.
- I need to be physically present for a first-layer check before anything prints.

Once this works, the workflow I want in future sessions is: I describe a part,
you generate the STL, slice it with the Ender 3 V2 profiles, upload it, and ask
me before printing.
