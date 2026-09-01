// G-code parse worker: single pass over the raw text, emitting typed arrays.
// Per extrusion segment: 6 floats of position, 1 byte of feature id, and the
// BYTE OFFSET of its source line - the key that makes live print sync exact
// (OctoPrint reports progress as bytes into the streamed file).
//
// Handles: G0/G1 moves, G90/G91 (absolute/relative), M82/M83 (E mode),
// G92 resets, Orca/Prusa feature comments (; FEATURE: / ;TYPE:) and
// ;LAYER_CHANGE markers with Z-cluster fallback. G2/G3 arcs fall back to a
// straight chord (this pipeline slices with arc fitting off).

const FEATURES = [
  'Outer wall', 'Inner wall', 'Overhang wall', 'Sparse infill',
  'Internal solid infill', 'Top surface', 'Bottom surface', 'Bridge',
  'Gap infill', 'Skirt', 'Brim', 'Support', 'Support interface', 'Custom',
  'Travel', 'Other',
];
const FEAT_INDEX = {};
FEATURES.forEach((f, i) => { FEAT_INDEX[f.toLowerCase()] = i; });

self.onmessage = (ev) => {
  const text = ev.data;
  const n = text.length;

  // growable chunked output
  let cap = 1 << 18;
  let pos = new Float32Array(cap * 6);
  let feat = new Uint8Array(cap);
  let offs = new Uint32Array(cap);
  let count = 0;
  const layers = [];          // {z, firstSeg, byteOff}

  function grow() {
    cap *= 2;
    const p2 = new Float32Array(cap * 6); p2.set(pos); pos = p2;
    const f2 = new Uint8Array(cap); f2.set(feat); feat = f2;
    const o2 = new Uint32Array(cap); o2.set(offs); offs = o2;
  }

  let x = 0, y = 0, z = 0, e = 0;
  let absXYZ = true, absE = true;
  let curFeat = FEAT_INDEX['other'];
  let lineStart = 0;
  let lastLayerZ = -1;
  let sawLayerComment = false;

  while (lineStart < n) {
    let lineEnd = text.indexOf('\n', lineStart);
    if (lineEnd === -1) lineEnd = n;
    const line = text.slice(lineStart, lineEnd);
    const byteOff = lineStart;

    if (line.charCodeAt(0) === 59) {           // ';' comment line
      if (line.startsWith(';LAYER_CHANGE')) {
        sawLayerComment = true;
        layers.push({ z, firstSeg: count, byteOff });
      } else if (line.startsWith('; FEATURE:') || line.startsWith(';TYPE:')) {
        const name = line.slice(line.indexOf(':') + 1).trim().toLowerCase();
        curFeat = FEAT_INDEX[name] ?? FEAT_INDEX['other'];
      }
    } else {
      // strip trailing comment, tokenize
      const ci = line.indexOf(';');
      const code = ci === -1 ? line : line.slice(0, ci);
      if (code.length > 1) {
        const parts = code.trim().split(/\s+/);
        const cmd = parts[0];
        if (cmd === 'G0' || cmd === 'G1' || cmd === 'G2' || cmd === 'G3') {
          let nx = x, ny = y, nz = z, ne = null;
          for (let i = 1; i < parts.length; i++) {
            const t = parts[i];
            const v = parseFloat(t.slice(1));
            if (Number.isNaN(v)) continue;
            switch (t[0]) {
              case 'X': nx = absXYZ ? v : x + v; break;
              case 'Y': ny = absXYZ ? v : y + v; break;
              case 'Z': nz = absXYZ ? v : z + v; break;
              case 'E': ne = absE ? v : e + v; break;
            }
          }
          const extruding = ne !== null && ne > e + 1e-6;
          const moved = nx !== x || ny !== y || nz !== z;
          if (moved && extruding) {
            if (count >= cap) grow();
            const b = count * 6;
            pos[b] = x; pos[b+1] = y; pos[b+2] = z;
            pos[b+3] = nx; pos[b+4] = ny; pos[b+5] = nz;
            feat[count] = curFeat;
            offs[count] = byteOff;
            count++;
            // Z-cluster fallback layer detection when no comments exist
            if (!sawLayerComment && nz !== lastLayerZ) {
              layers.push({ z: nz, firstSeg: count - 1, byteOff });
              lastLayerZ = nz;
            }
          }
          x = nx; y = ny; z = nz;
          if (ne !== null) e = ne;
        } else if (cmd === 'G90') { absXYZ = true; absE = true; }
        else if (cmd === 'G91') { absXYZ = false; absE = false; }
        else if (cmd === 'M82') { absE = true; }
        else if (cmd === 'M83') { absE = false; }
        else if (cmd === 'G92') {
          for (let i = 1; i < parts.length; i++) {
            const t = parts[i];
            const v = parseFloat(t.slice(1));
            if (Number.isNaN(v)) continue;
            if (t[0] === 'E') e = v;
            else if (t[0] === 'X') x = v;
            else if (t[0] === 'Y') y = v;
            else if (t[0] === 'Z') z = v;
          }
        }
      }
    }
    lineStart = lineEnd + 1;
  }

  // trim to fit and transfer zero-copy
  const positions = pos.slice(0, count * 6);
  const features = feat.slice(0, count);
  const offsets = offs.slice(0, count);
  self.postMessage({
    count,
    positions: positions.buffer,
    features: features.buffer,
    offsets: offsets.buffer,
    layers,
    featureNames: FEATURES,
  }, [positions.buffer, features.buffer, offsets.buffer]);
};
