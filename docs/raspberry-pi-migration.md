# Migrating from Mac-hosted OctoPrint to a Raspberry Pi (OctoPi)

The architecture barely changes: OctoPrint moves to the Pi (with the printer's
USB cable), while STL generation and slicing stay on the Mac. The MCP server
just points at a different host.

## What changes

1. **PRINTER_HOST / PRINTER_PORT** in `.mcp.json`:
   - OctoPi serves OctoPrint behind haproxy on port **80**, so:
     `"PRINTER_HOST": "octopi.local"` (or the Pi's static IP — prefer a DHCP
     reservation so it never moves), `"PRINTER_PORT": "80"`.
   - `octopi.local` relies on mDNS/Bonjour; if it's flaky, use the IP.

2. **API key**: the Pi's OctoPrint is a fresh install with its own users and
   keys. Generate a new Application Key there (same steps as the README) and
   update `OCTOPRINT_API_KEY` in your shell env.

3. **Same-LAN requirement**: `octopi.local` is only reachable from your home
   network. The Mac running Claude must be on the same LAN — or use Tailscale
   (install on both Mac and Pi) and point `PRINTER_HOST` at the Pi's Tailscale
   name/IP, which also works away from home. **Do not** port-forward OctoPrint
   to the open internet; exposed OctoPrint instances get abused.

4. **Restore settings**: OctoPrint's built-in Backup & Restore plugin moves your
   printer profile, plugins, and uploaded files from the Mac instance to the Pi
   (Settings → Backup & Restore → download backup on Mac, restore on Pi).

## What does NOT change

- OrcaSlicer, the profiles in this repo, and all of `scripts/` (they honor
  `OCTO_URL`, e.g. `OCTO_URL=http://octopi.local ./setup-mac.sh`).
- The MCP server install and every tool name — only its env vars.
- The safety rules: upload-only by default, explicit confirmation before
  `start_print`.

## Nice-to-haves once on the Pi

- A camera + OctoPrint's webcam support gives you (and Claude, via snapshot
  URLs) visual print monitoring.
- OctoPrint plugins worth adding: Bed Level Visualizer, PrintTimeGenius,
  Obico or OctoEverywhere if you ever want sanctioned remote access.

## As-built (August 2026) — what the live system actually does

The migration happened; this is the part the sections above don't tell you:

- OctoPrint runs on a Pi 3B+ (OctoPi 1.10) at **10.0.0.112:80** (DHCP
  reservation recommended). The printer's USB goes to the Pi.
- **The Mac does not talk to the Pi directly.** macOS Local Network privacy
  (TCC) silently blocks LAN requests (errno 65) from process trees that were
  never granted Local Network permission — including preview-launched dev
  servers, and raw-IP requests are blocked the same as .local names. Python
  also prefers an IPv6 route the Pi doesn't serve.
- The fix is a tiny localhost relay: `OCTO_URL="http://127.0.0.1:5051"`,
  forwarded to `10.0.0.112:80` by a socat-style forwarder started from a
  context that HAS Local Network permission (a normal Terminal shell works):

  ```bash
  # keep-alive relay loop, run from an allowed context:
  while true; do
    /usr/bin/nc -l 127.0.0.1 5051 -c "/usr/bin/nc 10.0.0.112 80" 2>/dev/null || true
  done
  # (the actual relay in use is a python stream forwarder started the same way)
  ```

- `scripts/studio.sh` force-sources `OCTOPRINT_API_KEY`, `OCTO_URL`,
  `TRIPO_API_KEY`, and `SKETCHFAB_API_TOKEN` from ~/.zshrc so the studio
  works no matter how it was launched.
- The old Mac OctoPrint on 127.0.0.1:5001 still exists as a fallback and is
  the default `OCTO_URL` when the env var is unset — with the env var set
  (normal state), everything targets the Pi through the relay.
