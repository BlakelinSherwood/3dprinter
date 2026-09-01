# Activation checklist — what each upgrade needs to be fully "on"

A running list of the overnight upgrades and the keys / credits / hardware each one
needs. Claude maintains this; check the **Status** column for anything with your name
on it. Last verified: 2026-09-01.

## Status at a glance

| Feature | Needs | Status | Your move |
|---|---|---|---|
| Core pipeline (slice → safety check → upload → live temps) | `OCTOPRINT_API_KEY`, `OCTO_URL` relay | ✅ Working | none |
| Three-stage UI, auto-orient, toolpath viewer, QR plaques, auto-supports, modern slicing | nothing (all local) | ✅ Working | none |
| Model **search** — Printables **and** Sketchfab | nothing (keyless) | ✅ Working | none |
| Sketchfab **one-click import** | `SKETCHFAB_API_TOKEN` (free) | 🆓 Not set | add free token (2 min, below) |
| Blueprint → 3D (Tripo multiview) | `TRIPO_API_KEY` **+ credits** | 💳 Key set, balance $0 | add credits *or* use free web path |
| Photo → 3D and text → 3D (in-studio) | `TRIPO_API_KEY` + credits (or Meshy) | 💳 Key set, balance $0 | same as above |
| Filament break/runout detection | BTT SFS V1.0 sensor + OctoPrint plugin | 🔌 Sensor ordered (arrives ~Sep 2) | install together on arrival |

---

## 🆓 Free quick win — Sketchfab one-click import

Search already shows Sketchfab models; this just adds the one-click **import** button.

1. Make a free account at **sketchfab.com** (or log in).
2. Go to **Settings → Password & API**.
3. Copy your **API Token**.
4. Add it to `~/.zshrc`:
   ```bash
   echo 'export SKETCHFAB_API_TOKEN="paste_token_here"' >> ~/.zshrc && source ~/.zshrc
   ```
5. Tell Claude — a studio restart picks it up, and the import buttons light up.

Until then: open the model on sketchfab.com, download the **.glb**, and use the
**⊕ mesh** button in the studio. Same result, one extra step.

---

## 💳 Paid decision — Tripo credits (photo→3D, blueprint→3D inside the studio)

- Your `TRIPO_API_KEY` is already configured. The **account balance is $0**, so the
  in-studio "Build 3D" / photo→3D calls stop at Tripo's billing gate.
- To turn these on inside the studio: add credits to the Tripo account tied to that key
  at **tripo3d.ai**, then tell Claude.
- **Free alternative that needs no credits:** use Tripo's **web studio** in a browser to
  generate the model, download the **.glb**, and bring it in with the **⊕ mesh** button.
  You get the same mesh; you just do the generation step in the browser.
- **Meshy** is a second option but its API is paid-only — you said skip it, so
  `MESHY_API_KEY` is intentionally unset. (If you ever change your mind, that's the one
  variable to add.)

---

## 🔌 Hardware in progress — filament sensor

- **BTT SFS V1.0** ordered (Amazon, ~Sep 2 delivery). No API needed.
- Wires to the **Raspberry Pi GPIO**, not the printer board — no firmware flash.
- Full setup guide: [`filament-sensor-install.html`](filament-sensor-install.html).
- On arrival: install the OctoPrint plugin + wire it together, then the next overnight
  run has break/runout protection.

---

## Operational info Claude needs kept intact

These aren't features — they're the plumbing the whole system rides on. Flagged here so
they don't silently break.

- **The relay** `127.0.0.1:5051 → 10.0.0.112:80` must be running for uploads and live
  temps (macOS Local Network privacy blocks the direct route). If uploads/temps go dead,
  the relay needs restarting from a normal Terminal. See
  [`raspberry-pi-migration.md`](raspberry-pi-migration.md) → "As-built".
- **OctoPrint API key** is the Raspberry Pi's Application Key. If you ever regenerate it
  in OctoPrint, paste the new one to Claude so `~/.zshrc` gets updated.
- **Pip dependencies** for the new features (`tweaker3`, `segno`, `pillow`, `trimesh`,
  `manifold3d`) are pinned in `scripts/requirements-cad.txt`, so a CAD-venv rebuild keeps
  auto-orient, QR plaques, and mesh import working.
