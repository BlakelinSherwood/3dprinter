import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { STLLoader } from 'three/addons/loaders/STLLoader.js';

const $ = (id) => document.getElementById(id);

// Units are a display layer only - models, STL and G-code are always mm.
const MM_IN = 25.4;
let units = 'in';
try { units = localStorage.getItem('studio.units') || 'in'; } catch {}
const toDisplay = (mm) => units === 'in' ? +(mm / MM_IN).toFixed(3) : mm;
const toMM = (val) => units === 'in' ? val * MM_IN : val;
const fmtLen = (mm) => units === 'in' ? `${(mm / MM_IN).toFixed(3)}"` : `${mm} mm`;
const fmtVol = (cm3) => units === 'in'
  ? `${(cm3 / 16.387).toFixed(2)} in³` : `${cm3} cm³`;

// The log is the full history; errors are ALSO mirrored into the active
// stage's message line so they can't hide in a collapsed log.
const log = (msg, cls) => {
  const el = document.createElement('div');
  if (cls) el.className = cls;   // ok | bad | dim | warn
  el.textContent = msg;
  $('log').appendChild(el);
  $('log').scrollTop = $('log').scrollHeight;
  if (cls === 'bad') stageMsg(activeStage(), msg, 'bad');
};

function stageMsg(n, text, cls) {
  const el = $('msg' + n);
  if (!el) return;
  el.textContent = text || '';
  el.className = 'stagemsg' + (cls ? ' ' + cls : '');
}

// ---------- three.js scene (printer coordinates: Z up, plate on XY) ----------
const view = $('view');
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14161a);

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 4000);
camera.up.set(0, 0, 1);
camera.position.set(190, -190, 150);

const renderer = new THREE.WebGLRenderer({ antialias: true });
view.appendChild(renderer.domElement);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const key = new THREE.DirectionalLight(0xffffff, 1.4);
key.position.set(160, -120, 260);
scene.add(key);
const fill = new THREE.DirectionalLight(0x8899ff, 0.35);
fill.position.set(-140, 160, 120);
scene.add(fill);

// Build plate: 220x220 grid centered on origin, plate surface at z=0.
const PLATE = 220;
const grid = new THREE.GridHelper(PLATE, 22, 0x3a4150, 0x242a33);
grid.rotation.x = Math.PI / 2;
scene.add(grid);
const border = new THREE.LineLoop(
  new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(-PLATE/2, -PLATE/2, 0), new THREE.Vector3(PLATE/2, -PLATE/2, 0),
    new THREE.Vector3(PLATE/2, PLATE/2, 0), new THREE.Vector3(-PLATE/2, PLATE/2, 0),
  ]),
  new THREE.LineBasicMaterial({ color: 0x3b6ea5 })
);
scene.add(border);

let mesh = null;
const material = new THREE.MeshStandardMaterial({
  color: 0x7aa3cc, metalness: 0.05, roughness: 0.55,
});

function resize() {
  const w = view.clientWidth, h = view.clientHeight;
  renderer.setSize(w, h);
  renderer.setPixelRatio(window.devicePixelRatio);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener('resize', resize);
resize();

(function animate() {
  requestAnimationFrame(animate);
  controls.update();
  renderer.render(scene, camera);
})();

function showSTL(url) {
  new STLLoader().load(url + '?t=' + Date.now(), (geom) => {
    if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
    geom.computeVertexNormals();
    geom.computeBoundingBox();
    const bb = geom.boundingBox;
    const c = new THREE.Vector3(); bb.getCenter(c);
    // Sit on the plate, centered: xy center -> origin, zmin -> 0.
    geom.translate(-c.x, -c.y, -bb.min.z);
    meshOffset = { x: c.x, y: c.y, z: bb.min.z };
    mesh = new THREE.Mesh(geom, material);
    scene.add(mesh);
    const size = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y, bb.max.z - bb.min.z);
    const d = Math.max(size * 2.6, 60);
    camera.position.set(d, -d, d * 0.75);
    controls.target.set(0, 0, (bb.max.z - bb.min.z) / 2);
    buildRulers();
    updateBadge();
  });
}

// ---------------------------- pipeline state ----------------------------
let models = [];
const state = { generated: false, sliced: false, uploaded: false };
let meshOffset = { x: 0, y: 0, z: 0 };
let rot = [0, 0, 0];
let lastResult = null;
let lastEst = null;
let sliceMeta = null;     // what the queued G-code actually contains
let userOpen = null;      // stage manually toggled open by the user
let describeMode = 'new';

// ---------------------------- measuring rulers ----------------------------
let rulerOn = false;
try { rulerOn = localStorage.getItem('studio.ruler') === '1'; } catch {}
let rulerGroup = null;

function textSprite(text, sizeMM) {
  const cv = document.createElement('canvas');
  const ctx = cv.getContext('2d');
  ctx.font = '28px -apple-system, sans-serif';
  cv.width = Math.ceil(ctx.measureText(text).width) + 12;
  cv.height = 38;
  const c2 = cv.getContext('2d');
  c2.font = '28px -apple-system, sans-serif';
  c2.fillStyle = '#9fb6cc';
  c2.textBaseline = 'middle';
  c2.fillText(text, 6, 19);
  const tex = new THREE.CanvasTexture(cv);
  tex.minFilter = THREE.LinearFilter;
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
  const h = sizeMM;
  sp.scale.set(h * cv.width / cv.height, h, 1);
  return sp;
}

function fmtTick(mm) {
  return units === 'in' ? `${+(mm / MM_IN).toFixed(2)}"` : `${+mm.toFixed(0)}`;
}

function tickStep(lengthMM) {
  const steps = units === 'in'
    ? [3.175, 6.35, 12.7, 25.4, 50.8, 152.4, 304.8]   // 1/8" .. 12"
    : [1, 2, 5, 10, 20, 50, 100, 200];
  for (const s of steps) if (lengthMM / s <= 10) return s;
  return steps[steps.length - 1];
}

function removeRulers() {
  if (rulerGroup) { scene.remove(rulerGroup); rulerGroup = null; }
}

function buildRulers() {
  removeRulers();
  if (!rulerOn || !mesh || !lastResult) return;
  const [X, Y, Z] = lastResult.bbox;
  const g = new THREE.Group();
  const lineMat = new THREE.LineBasicMaterial({ color: 0x8aa8c8 });
  const off = Math.max(6, Math.max(X, Y) * 0.06);
  const tick = Math.max(2, Math.max(X, Y, Z) * 0.02);
  const labelH = Math.max(3.5, Math.max(X, Y, Z) * 0.045);

  function axisRuler(len, place, tickDir) {
    const step = tickStep(len);
    const pts = [place(0), place(len)];
    for (let v = 0; v <= len + 1e-6; v += step) {
      const p = place(Math.min(v, len));
      pts.push(p, p.clone().add(tickDir.clone().multiplyScalar(tick)));
      const lab = textSprite(fmtTick(v), labelH);
      lab.position.copy(p.clone().add(tickDir.clone().multiplyScalar(tick + labelH * 0.8)));
      g.add(lab);
    }
    const end = place(len);
    pts.push(end, end.clone().add(tickDir.clone().multiplyScalar(tick * 1.6)));
    const total = textSprite(fmtLen(+len.toFixed(2)), labelH * 1.25);
    total.position.copy(end.clone().add(tickDir.clone().multiplyScalar(tick + labelH * 2.2)));
    g.add(total);
    const geo = new THREE.BufferGeometry().setFromPoints(pts);
    g.add(new THREE.LineSegments(geo, lineMat));
  }

  axisRuler(X, v => new THREE.Vector3(-X / 2 + v, -Y / 2 - off, 0),
            new THREE.Vector3(0, -1, 0));
  axisRuler(Y, v => new THREE.Vector3(-X / 2 - off, -Y / 2 + v, 0),
            new THREE.Vector3(-1, 0, 0));
  axisRuler(Z, v => new THREE.Vector3(-X / 2 - off, -Y / 2 - off, v),
            new THREE.Vector3(-0.7, -0.7, 0));
  rulerGroup = g;
  scene.add(g);
}

// ------------------- click a spot on the model to focus edits -------------------
let focus = null;        // {point:[x,y,z] model mm, region: "words"}
let focusMarker = null;

function updateBadge() {
  if (focus) $('badge').textContent = `◎ edits aim at: ${focus.region || 'that spot'}`;
  else if (mesh) $('badge').textContent =
    'drag to orbit · scroll to zoom · click a spot to aim a change';
  else $('badge').textContent = 'drag to orbit · scroll to zoom';
}

function clearFocus() {
  focus = null;
  if (focusMarker) { scene.remove(focusMarker); focusMarker = null; }
  $('focusrow').hidden = true;
  updateBadge();
}

function regionWords(p) {
  if (!lastResult) return '';
  const [X, Y, Z] = lastResult.bbox;
  const parts = [];
  if (p.z > Z * 0.8) parts.push('on the top');
  else if (p.z < Z * 0.2) parts.push('near the bottom');
  else parts.push('on the side');
  if (p.x > X * 0.25) parts.push('right (+X) area');
  else if (p.x < -X * 0.25) parts.push('left (-X) area');
  if (p.y > Y * 0.25) parts.push('back (+Y) area');
  else if (p.y < -Y * 0.25) parts.push('front (-Y) area');
  return parts.join(', ');
}

function setFocusFromHit(hit) {
  if (focusMarker) { scene.remove(focusMarker); focusMarker = null; }
  const p = hit.point;
  const model = [
    +(p.x + meshOffset.x).toFixed(2),
    +(p.y + meshOffset.y).toFixed(2),
    +(p.z + meshOffset.z).toFixed(2),
  ];
  const region = regionWords(p);
  focus = { point: model, region };
  const size = lastResult ? Math.max(...lastResult.bbox) : 40;
  focusMarker = new THREE.Mesh(
    new THREE.SphereGeometry(Math.max(size * 0.022, 0.8), 20, 14),
    new THREE.MeshBasicMaterial({ color: 0xffb224 }));
  focusMarker.position.copy(p);
  scene.add(focusMarker);
  $('focustext').textContent =
    `${region || 'spot'} (${model.join(', ')}) — edits target this`;
  $('focusrow').hidden = false;
  setMode('edit');
  updateBadge();
}

function focusAtScreen(cssX, cssY) {
  if (!mesh) return 'no mesh';
  const rc = new THREE.Raycaster();
  const r = renderer.domElement.getBoundingClientRect();
  rc.setFromCamera(new THREE.Vector2(
    ((cssX - r.left) / r.width) * 2 - 1,
    -((cssY - r.top) / r.height) * 2 + 1), camera);
  const hits = rc.intersectObject(mesh);
  if (hits.length) { setFocusFromHit(hits[0]); return 'hit'; }
  return 'miss';   // a miss no longer clears an existing focus
}
window.studioFocusAt = focusAtScreen;

{
  let downAt = null;
  renderer.domElement.addEventListener('pointerdown', (e) => {
    downAt = [e.clientX, e.clientY];
  });
  renderer.domElement.addEventListener('pointerup', (e) => {
    if (!downAt) return;
    const moved = Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]);
    downAt = null;
    if (moved > 6 || !mesh) return;
    focusAtScreen(e.clientX, e.clientY);
  });
}

// ---------------------------- stage controller ----------------------------
function currentModel() {
  return models.find(m => m.name === $('model').value);
}

function activeStage() {
  if (!$('st1')) return 1;
  if ($('st1').classList.contains('active') || $('st1').classList.contains('error')) return 1;
  if ($('st2').classList.contains('active') || $('st2').classList.contains('error')) return 2;
  return 3;
}

function fatalWarning() {
  return lastResult?.warnings?.some(w => /TOO BIG|TOO TALL|will not print/i.test(w));
}

function setStage(el, status, summary) {
  el.classList.remove('active', 'done', 'error', 'locked', 'working');
  if (status) el.classList.add(status);
  el.classList.toggle('open', userOpen === el.id);
  const chip = el.querySelector('.chip');
  const n = el.id.slice(-1);
  chip.textContent = status === 'done' ? '✓' : status === 'error' ? '!' : n;
  el.querySelector('.stagesum').textContent = summary || '';
}

function updateStages() {
  const hasModel = models.length > 0 && !!$('model').value;
  const fatal = fatalWarning();
  const m = currentModel();

  // Stage 1 - Create
  let s1 = 'active', sum1 = '';
  if (busy && /describe|import|gen3d|bpy|refine/.test(progOp || '')) s1 = 'working';
  else if (hasModel) { s1 = 'done'; sum1 = m ? m.name : ''; }
  setStage($('st1'), s1, sum1);

  // Stage 2 - Shape
  let s2, sum2 = '';
  if (!hasModel) { s2 = 'locked'; sum2 = 'build a part first'; }
  else if (busy && progOp === 'generate') s2 = 'working';
  else if (fatal) { s2 = 'error'; sum2 = 'too big to print'; }
  else if (state.generated) {
    s2 = 'done';
    if (lastResult) sum2 = lastResult.bbox.map(v => fmtLen(v)).join(' × ');
  } else s2 = 'active';
  setStage($('st2'), s2, sum2);

  // Stage 3 - Print
  let s3, sum3 = '';
  if (!hasModel || !state.generated || fatal) {
    s3 = 'locked';
    sum3 = fatal ? 'fix the size problem first' : 'make a shape first';
  } else if (busy && /slice|upload/.test(progOp || '')) s3 = 'working';
  else if (state.uploaded) { s3 = 'done'; sum3 = 'on the printer ✓'; }
  else if (state.sliced && sliceMeta) {
    s3 = 'active';
    sum3 = `sliced · ${sliceMeta.material} · ${sliceMeta.lh}mm · ${sliceMeta.time || ''}`;
  } else s3 = 'active';
  setStage($('st3'), s3, sum3);

  // Exactly one expanded stage unless the user has toggled one open.
  const act = s1 === 'active' || s1 === 'working' ? $('st1')
            : (s2 === 'active' || s2 === 'working' || s2 === 'error') ? $('st2') : $('st3');
  for (const el of [$('st1'), $('st2'), $('st3')])
    if (el !== act && userOpen !== el.id) el.classList.remove('active');
  if (!act.classList.contains('done')) act.classList.add(
    act.classList.contains('working') ? 'working' : act.classList.contains('error') ? 'error' : 'active');

  // Buttons
  $('slice').disabled = !state.generated || busy || fatal;
  $('slice').hidden = state.sliced && !state.uploaded;
  $('upload').hidden = !(state.sliced && !state.uploaded);
  $('upload').disabled = busy;
  $('reslice').hidden = !state.sliced || state.uploaded;
  $('revert').disabled = busy || !(m && m.has_history);
  $('makeprint').hidden = !(m && m.imported);
  $('makeprint').disabled = busy;
  $('refine').disabled = busy || (m && m.imported);
  $('refine').parentElement.style.display = (m && m.imported) ? 'none' : '';
  $('importnote').hidden = !(m && m.imported);
  if (m && m.imported)
    $('importnote').textContent =
      'imported mesh — attribution kept · use ⚙ make printable if slicing complains';
  const dl = $('dl');
  if (state.generated && m) {
    dl.href = `/output/${m.name}.stl`;
    dl.setAttribute('download', `${m.name}.stl`);
    dl.classList.remove('off');
  } else dl.classList.add('off');
  for (const id of ['rotx', 'roty', 'rotz', 'rotreset', 'generate'])
    $(id).disabled = busy;
  renderPrintsum();
}

// stage headers toggle open/closed by hand
for (const el of [$('st1'), $('st2'), $('st3')]) {
  el.querySelector('.stagehead').onclick = () => {
    if (el.classList.contains('locked')) return;
    userOpen = (userOpen === el.id) ? null :
      (el.classList.contains('active') || el.classList.contains('error')) ? null : el.id;
    updateStages();
  };
}

function invalidateSlice(why) {
  if (state.sliced || state.uploaded) stageMsg(3, why + ' — slice again', 'dim');
  state.sliced = false;
  state.uploaded = false;
  sliceMeta = null;
  $('est').classList.add('stale');
  updateStages();
}

// ---------------------------- describe mode segment ----------------------------
function setMode(mode) {
  describeMode = mode;
  for (const b of $('mode').querySelectorAll('button'))
    b.classList.toggle('on', b.dataset.m === mode);
  $('buildnew').hidden = mode !== 'new';
  $('editsel').hidden = mode !== 'edit';
  $('desc').placeholder = mode === 'new'
    ? 'Type what you want to make, or attach a photo.'
    : 'Describe the change — click a spot on the part to aim it.';
  $('deschint').textContent = mode === 'new'
    ? 'Enter builds · Shift+Enter for a new line'
    : 'Enter applies the change · Shift+Enter for a new line';
}
for (const b of $('mode').querySelectorAll('button'))
  b.onclick = () => setMode(b.dataset.m);

// ---------------------------- params ----------------------------
const pretty = (name) =>
  name.replace(/_/g, ' ').replace(/^./, c => c.toUpperCase());

let genDebounce = null;
function renderParams(model) {
  const box = $('params');
  box.innerHTML = '';
  if (!model) return;
  for (const p of model.params) {
    const field = document.createElement('div');
    field.className = 'field';
    const unitless = /(ratio|angle|count|teeth|sides|segments|_num$|^num_)/.test(p.name);
    const label = document.createElement('label');
    label.textContent = unitless ? pretty(p.name) : `${pretty(p.name)} (${units})`;
    label.title = p.name;
    label.htmlFor = 'p_' + p.name;
    const input = document.createElement('input');
    input.type = 'number';
    input.step = unitless ? '0.01' : (units === 'in' ? '0.01' : '0.1');
    input.id = 'p_' + p.name;
    input.value = unitless ? p.default : toDisplay(p.default);
    input.dataset.param = p.name;
    if (unitless) input.dataset.unitless = '1';
    input.addEventListener('input', () => {
      clearTimeout(genDebounce);
      genDebounce = setTimeout(() => { if (!busy) doGenerate(); }, 600);
    });
    field.append(label, input);
    box.appendChild(field);
  }
}

function currentParams() {
  const out = {};
  for (const el of $('params').querySelectorAll('input[data-param]'))
    out[el.dataset.param] = el.dataset.unitless
      ? parseFloat(el.value) : toMM(parseFloat(el.value));
  return out;
}

// ---------------------------- print settings ----------------------------
function printSettings() {
  return {
    layer_height: $('ps_lh').value,
    infill_pct: parseInt($('ps_infill').value) || 15,
    supports: $('ps_supports').checked,
    brim: $('ps_brim').checked,
    material: $('ps_material').value,
    copies: parseInt($('ps_copies').value) || 1,
  };
}

function materialLabel() {
  const sel = $('ps_material');
  const opt = sel.options[sel.selectedIndex];
  return opt ? opt.textContent.replace(/^custom — /, '') : sel.value.toUpperCase();
}

function renderPrintsum() {
  const s = printSettings();
  const extras = [];
  if (s.supports) extras.push('supports');
  if (s.brim) extras.push('brim');
  if (s.infill_pct !== 15) extras.push(`${s.infill_pct}% infill`);
  $('printsum').innerHTML =
    `Loaded: <b>${materialLabel()}</b>` + (extras.length ? ` · ${extras.join(' · ')}` : '');
}
$('printsum').onclick = () => { $('printadv').open = !$('printadv').open; };

// quality select writes through to the exact layer height (and back)
$('ps_quality').onchange = () => {
  if ($('ps_quality').value !== 'custom') {
    $('ps_lh').value = $('ps_quality').value;
    $('ps_lh').dispatchEvent(new Event('change'));
  }
};
function syncQuality() {
  const lh = $('ps_lh').value;
  const match = [...$('ps_quality').options].find(o => o.value === lh);
  $('ps_quality').value = match && !match.hidden ? lh : 'custom';
}

try {
  const ps = JSON.parse(localStorage.getItem('studio.printset'));
  if (ps) {
    $('ps_lh').value = ps.layer_height ?? '0.2';
    $('ps_infill').value = ps.infill_pct ?? 15;
    $('ps_supports').checked = !!ps.supports;
    $('ps_brim').checked = !!ps.brim;
    $('ps_material').value = ps.material ?? 'pla';
    if (!$('ps_material').value) $('ps_material').value = 'pla';
    $('ps_copies').value = ps.copies ?? 1;
  }
} catch {}
syncQuality();

for (const id of ['ps_lh', 'ps_infill', 'ps_supports', 'ps_brim', 'ps_material', 'ps_copies']) {
  $(id).onchange = () => {
    try { localStorage.setItem('studio.printset', JSON.stringify(printSettings())); } catch {}
    if (id === 'ps_lh') syncQuality();
    invalidateSlice('settings changed');
  };
}

// ---------------------------- filament lookup ----------------------------
function setCustomOption(name, select) {
  let opt = [...$('ps_material').options].find(o => o.value === 'custom');
  if (!opt) {
    opt = document.createElement('option');
    opt.value = 'custom';
    $('ps_material').appendChild(opt);
  }
  opt.textContent = `custom — ${name}`;
  if (select) {
    $('ps_material').value = 'custom';
    $('ps_material').dispatchEvent(new Event('change'));
  }
}

$('matlookup_btn').onclick = async () => {
  const query = $('matlookup').value.trim();
  if (!query) { log('type a filament name to look up', 'bad'); return; }
  setBusy(true);
  log(`looking up filament: ${query}…`, 'dim');
  try {
    const res = await api('/api/material_lookup', { query });
    setCustomOption(res.name, true);
    const a = res.applied;
    log(`${res.name} → ${res.class.toUpperCase()} rules · nozzle ${a.nozzle}°` +
        (a.nozzle_first !== a.nozzle ? ` (first ${a.nozzle_first}°)` : '') +
        ` · bed ${a.bed}°` + (a.bed_first !== a.bed ? ` (first ${a.bed_first}°)` : '') +
        ` · ${res.source}`, 'ok');
    stageMsg(3, `${res.name} applied — nozzle ${a.nozzle}°, bed ${a.bed}°`, 'ok');
    for (const n of res.notes || []) log('⚠ ' + n, 'warn');
    if (res.alternatives?.length)
      log('also matched: ' + res.alternatives.join(', '), 'dim');
  } catch (e) { log(e.message, 'bad'); }
  setBusy(false);
};

// restore a stored lookup so "custom" survives restarts
(async () => {
  try {
    const meta = await (await fetch('/api/material_custom')).json();
    if (meta.name) setCustomOption(meta.name, false);
    if ($('ps_material').value === 'custom' && !meta.name)
      $('ps_material').value = 'pla';
    renderPrintsum();
  } catch {}
})();

// ---------------------------- header controls ----------------------------
$('ruler').classList.toggle('on', rulerOn);
$('ruler').onclick = () => {
  rulerOn = !rulerOn;
  try { localStorage.setItem('studio.ruler', rulerOn ? '1' : '0'); } catch {}
  $('ruler').classList.toggle('on', rulerOn);
  buildRulers();
};

function renderUnits() {
  for (const b of $('units').querySelectorAll('button'))
    b.classList.toggle('on', b.dataset.u === units);
}
renderUnits();
for (const b of $('units').querySelectorAll('button')) {
  b.onclick = () => {
    if (units === b.dataset.u) return;
    const mmVals = currentParams();
    units = b.dataset.u;
    try { localStorage.setItem('studio.units', units); } catch {}
    renderUnits();
    for (const el of $('params').querySelectorAll('input[data-param]')) {
      if (el.dataset.unitless) continue;
      el.value = toDisplay(mmVals[el.dataset.param]);
      el.step = units === 'in' ? '0.01' : '0.1';
    }
    for (const lab of $('params').querySelectorAll('label'))
      lab.textContent = lab.textContent.replace(/\((in|mm)\)$/, `(${units})`);
    if (lastResult) showResult(lastResult, { keepFocus: true });
    if (lastEst) $('est').innerHTML = fmtEst(lastEst);
    buildRulers();
    updateStages();
  };
}

// ---------------------------- API + jobs ----------------------------
async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (data.error) throw new Error(data.error);
  return data;
}

function rememberJob(id, kind) {
  try { localStorage.setItem('studio.lastjob', JSON.stringify({ id, kind, t: Date.now() })); }
  catch {}
}
function forgetJob() {
  try { localStorage.removeItem('studio.lastjob'); } catch {}
}

async function pollJob(id) {
  for (;;) {
    await new Promise(r => setTimeout(r, 3000));
    const res = await fetch(`/api/job/${id}`);
    if (res.status === 404) throw new Error('the running job was lost (server restarted)');
    const j = await res.json();
    if (j.status === 'done') return j.result;
    if (j.status === 'error') {
      const tail = (j.error || 'failed').trim().split('\n');
      throw new Error(tail.slice(-3).join(' '));
    }
  }
}

async function apiJob(path, body, kind) {
  // long-running codegen: submit, then poll - a single held request gets
  // killed by proxies after a couple of minutes
  const start = await api(path, body);
  if (!start.job) return start;
  rememberJob(start.job, kind || path);
  try {
    const out = await pollJob(start.job);
    forgetJob();
    return out;
  } catch (e) { forgetJob(); throw e; }
}

function showResult(res, opts = {}) {
  lastResult = res;
  if (!opts.keepFocus) clearFocus();
  let html = `<b>${fmtLen(res.bbox[0])} × ${fmtLen(res.bbox[1])} × ${fmtLen(res.bbox[2])}</b> · ${fmtVol(res.volume_cm3)}`;
  for (const w of res.warnings || []) html += `<div class="warn">⚠ ${w}</div>`;
  $('stats').innerHTML = html;
  showSTL(res.stl);
  for (const w of res.warnings || []) log('⚠ ' + w, 'warn');
  // auto-decide brim for tall-thin parts; note the decision where it's seen
  const tall = (res.warnings || []).find(w => /consider enabling Brim/i.test(w));
  if (tall && !$('ps_brim').checked) {
    $('ps_brim').checked = true;
    try { localStorage.setItem('studio.printset', JSON.stringify(printSettings())); } catch {}
    stageMsg(3, 'brim added automatically — tall part with a small footprint', 'dim');
  }
  if (res.support?.needs_supports)
    stageMsg(3, 'this shape may need supports — the slicer will add them if required', 'dim');
  updateStages();
}

// ---- progress bar with self-calibrating time estimates ----
let progTimer = null, progStart = 0, progOp = null;
function pastDurations() {
  try { return JSON.parse(localStorage.getItem('studio.durations')) || {}; }
  catch { return {}; }
}
function estimateFor(op, fallback) {
  const a = pastDurations()[op];
  if (!a || !a.length) return fallback;
  const s = [...a].sort((x, y) => x - y);
  return Math.round(s[Math.floor(s.length / 2)]);
}
function startProgress(op, label, fallback) {
  clearInterval(progTimer);
  progOp = op; progStart = Date.now();
  const est = estimateFor(op, fallback);
  $('prog').hidden = false;
  $('progfill').style.background = 'var(--accent)';
  $('progfill').style.width = '2%';
  const tick = () => {
    const el = Math.round((Date.now() - progStart) / 1000);
    $('progfill').style.width =
      Math.min(96, Math.round(100 * el / Math.max(est, 1))) + '%';
    $('progtext').textContent = el <= est
      ? `${label} · ${el}s of ~${est}s`
      : `${label} · ${el}s (usually ~${est}s — still working)`;
  };
  tick();
  progTimer = setInterval(tick, 1000);
  updateStages();
}
function endProgress(ok) {
  clearInterval(progTimer);
  if (progOp && ok) {
    const secs = (Date.now() - progStart) / 1000;
    const d = pastDurations();
    (d[progOp] = d[progOp] || []).push(secs);
    d[progOp] = d[progOp].slice(-5);
    try { localStorage.setItem('studio.durations', JSON.stringify(d)); } catch {}
  }
  $('progfill').style.width = '100%';
  $('progfill').style.background = ok ? 'var(--ok)' : 'var(--bad)';
  $('progtext').textContent = ok
    ? `done in ${Math.round((Date.now() - progStart) / 1000)}s`
    : 'failed — see the log below';
  progOp = null;
  setTimeout(() => { if (!progOp) $('prog').hidden = true; }, ok ? 1800 : 5000);
}

let busy = false;
function setBusy(b) {
  busy = b;
  for (const id of ['buildnew', 'editsel', 'generate', 'refine', 'makeprint'])
    $(id).disabled = b;
  updateStages();
}

async function refreshModels(selectName) {
  models = await (await fetch('/api/models')).json();
  const sel = $('model');
  sel.innerHTML = '';
  for (const m of models) {
    const o = document.createElement('option');
    o.value = m.name; o.textContent = m.name;
    o.title = m.summary || '';
    sel.appendChild(o);
  }
  if (selectName) sel.value = selectName;
  const cur = currentModel();
  sel.title = cur?.summary || '';
  if (cur) renderParams(cur);
  updateStages();
}

// ---------------------------- attach photo ----------------------------
let photo = null;
$('photobtn').onclick = () => $('photo').click();
$('photo').onchange = () => {
  const f = $('photo').files[0];
  if (!f) return;
  if (f.size > 10 * 1024 * 1024) { log('photo too large (10MB max)', 'bad'); return; }
  const rd = new FileReader();
  rd.onload = () => {
    photo = { name: f.name, data: rd.result.split(',')[1] };
    $('photoname').textContent = f.name;
    $('clearphoto').hidden = false;
    stageMsg(1, 'photo attached — it will guide this build', 'dim');
  };
  rd.readAsDataURL(f);
};
$('clearphoto').onclick = () => {
  photo = null; $('photo').value = '';
  $('photoname').textContent = 'no photo';
  $('clearphoto').hidden = true;
  stageMsg(1, '');
};

// ---------------------------- mesh import ----------------------------
$('importbtn').onclick = () => $('importfile').click();
$('importfile').onchange = () => {
  const f = $('importfile').files[0];
  if (!f) return;
  if (f.size > 60 * 1024 * 1024) { log('mesh too large (60MB max)', 'bad'); return; }
  const rd = new FileReader();
  rd.onload = async () => {
    setBusy(true);
    log(`importing ${f.name}…`, 'dim');
    startProgress('import', `importing ${f.name}`, 12);
    let ok = false;
    try {
      const res = await api('/api/import',
        { name: f.name, data: rd.result.split(',')[1] });
      ok = true;
      await refreshModels(res.model);
      $('scale').value = 1;
      await doGenerate();
      log(`${res.model} imported`, 'ok');
      stageMsg(1, `${res.model} imported`, 'ok');
    } catch (e) { log(e.message, 'bad'); }
    endProgress(ok);
    $('importfile').value = '';
    setBusy(false);
  };
  rd.readAsDataURL(f);
};

// ---------------------------- model finder ----------------------------
$('findbtn').onclick = () => { $('finder').hidden = false; $('fq').focus(); };
$('finderclose').onclick = () => { $('finder').hidden = true; };

async function finderImport(printId, fileId, btn) {
  if (btn) { btn.disabled = true; btn.textContent = 'importing…'; }
  try {
    const res = await api('/api/model_import', { id: printId, file_id: fileId });
    await afterFinderImport(res);
  } catch (e) {
    log(e.message, 'bad');
    if (btn) { btn.disabled = false; btn.textContent = 'import'; }
  }
}

async function afterFinderImport(res) {
  $('finder').hidden = true;
  const a = res.attribution || {};
  log(`imported "${a.title || res.model}"` +
      (a.author ? ` by ${a.author}` : '') +
      (a.license ? ` · ${a.license}` : ''), 'ok');
  if (a.url) log(`source: ${a.url}`, 'dim');
  $('scale').value = 1;
  await refreshModels(res.model);
  await doGenerate();
  stageMsg(1, `imported "${a.title || res.model}"`, 'ok');
}

function renderResults(items) {
  const box = $('fresults');
  box.innerHTML = '';
  if (!items.length) {
    box.innerHTML = '<div class="fsub" style="padding:10px 0">no results</div>';
    return;
  }
  for (const it of items) {
    const card = document.createElement('div');
    card.className = 'fcard';
    const img = document.createElement('img');
    if (it.image) img.src = it.image;
    img.loading = 'lazy'; img.alt = '';
    const meta = document.createElement('div');
    meta.className = 'fmeta';
    const nm = document.createElement('div');
    nm.className = 'fname'; nm.textContent = it.name; nm.title = it.name;
    const sub = document.createElement('div');
    sub.className = 'fsub';
    sub.textContent = `${it.author || '?'} · ${it.license || 'license unknown'}` +
      (it.downloads ? ` · ${it.downloads.toLocaleString()} downloads` : '');
    meta.append(nm, sub);
    card.append(img, meta);
    let open = false, filesBox = null;
    card.onclick = async () => {
      if (open) { filesBox?.remove(); open = false; return; }
      open = true;
      filesBox = document.createElement('div');
      filesBox.className = 'ffiles';
      filesBox.innerHTML = '<div class="frow"><span class="qname">loading files…</span></div>';
      card.after(filesBox);
      try {
        const info = await api('/api/model_files', { id: it.id });
        filesBox.innerHTML = '';
        if (!info.files.length) {
          filesBox.innerHTML = '<div class="frow"><span class="qname">no STL files in this model</span></div>';
        }
        for (const f of info.files) {
          const row = document.createElement('div');
          row.className = 'frow';
          const n = document.createElement('span');
          n.className = 'qname'; n.textContent = f.name; n.title = f.name;
          const sz = document.createElement('span');
          sz.className = 'fsub'; sz.textContent = fmtSize(f.fileSize);
          const go = document.createElement('button');
          go.textContent = 'import';
          go.onclick = (ev) => { ev.stopPropagation(); finderImport(it.id, f.id, go); };
          row.append(n, sz, go);
          filesBox.appendChild(row);
        }
      } catch (e) {
        filesBox.innerHTML = `<div class="frow"><span class="qname">${e.message}</span></div>`;
      }
    };
    box.appendChild(card);
  }
}

async function doSearch() {
  const query = $('fq').value.trim();
  if (!query) return;
  $('fgo').disabled = true;
  $('fresults').innerHTML = '<div class="fsub" style="padding:10px 0">searching…</div>';
  try { renderResults(await api('/api/search', { query })); }
  catch (e) { $('fresults').innerHTML = `<div class="fsub" style="padding:10px 0">${e.message}</div>`; }
  $('fgo').disabled = false;
}
$('fgo').onclick = doSearch;
$('fq').addEventListener('keydown', (e) => { if (e.key === 'Enter') doSearch(); });

$('furlgo').onclick = async () => {
  const url = $('furl').value.trim();
  if (!url) return;
  $('furlgo').disabled = true; $('furlgo').textContent = '…';
  try {
    const res = await api('/api/import_url', { url });
    if (res.choose) {
      renderResults([{ id: res.choose.id, name: res.choose.name,
        author: res.choose.author, license: res.choose.license, image: null }]);
      log('several files in that model - pick one from the list', 'dim');
    } else {
      $('furl').value = '';
      await afterFinderImport(res);
    }
  } catch (e) { log(e.message, 'bad'); }
  $('furlgo').disabled = false; $('furlgo').textContent = 'Import';
};

// ---------------------------- AI generation lane ----------------------------
(async () => {
  try {
    const cfg = await (await fetch('/api/gen3d_config')).json();
    if (cfg.provider) {
      $('finderai').hidden = false;
      $('aiprompt').placeholder = `AI ${cfg.provider}: describe it, or use the photo button…`;
    }
  } catch {}
})();

let aiphotoData = null;
$('aiphoto').onclick = () => $('aifile').click();
$('aifile').onchange = () => {
  const f = $('aifile').files[0];
  if (!f) return;
  const rd = new FileReader();
  rd.onload = () => {
    aiphotoData = { data: rd.result.split(',')[1], name: f.name };
    $('aiphoto').textContent = '📷 ' + f.name.slice(0, 12);
  };
  rd.readAsDataURL(f);
};
$('aigo').onclick = async () => {
  const prompt = $('aiprompt').value.trim();
  if (!aiphotoData && !prompt) { log('pick a photo or type a description for AI 3D', 'bad'); return; }
  setBusy(true);
  log(`AI 3D generation: ${aiphotoData ? aiphotoData.name : prompt}…`, 'dim');
  startProgress('gen3d', 'generating 3D model (provider side)', 240);
  let ok = false;
  try {
    const res = await apiJob('/api/gen3d', {
      image: aiphotoData?.data, image_name: aiphotoData?.name, prompt: prompt || null }, 'gen3d');
    ok = true;
    $('finder').hidden = true;
    await refreshModels(res.model);
    showResult(res);
    state.generated = true;
    invalidateSlice('new model');
    log(`${res.model} imported from AI generation — try ⚙ make printable next`, 'ok');
    aiphotoData = null; $('aiphoto').textContent = '📷→3D';
  } catch (e) { log(e.message, 'bad'); }
  endProgress(ok);
  setBusy(false);
};

// ---------------------------- core actions ----------------------------
async function doDescribe(mode) {
  const description = $('desc').value.trim();
  if (!description) { log('describe the part first', 'bad'); return; }
  const model = $('model').value;
  if (mode === 'edit' && !model) { log('no model selected to edit', 'bad'); return; }
  setBusy(true);
  log(mode === 'edit' ? `editing ${model}: ${description}` : `building: ${description}`, 'dim');
  if (photo) log(`with reference photo: ${photo.name}`, 'dim');
  startProgress(mode === 'edit' ? 'describe_edit' : 'describe_new',
                mode === 'edit' ? `editing ${model}` : 'building your part',
                photo ? 130 : (mode === 'edit' ? 85 : 100));
  let describeOk = false;
  try {
    const res = await apiJob('/api/describe', { mode, model, description, image: photo,
      focus: mode === 'edit' ? focus : null }, 'describe');
    describeOk = true;
    rot = [0, 0, 0]; $('rotval').textContent = '0/0/0';
    await refreshModels(res.model);
    if (res.suggested_scale) {
      $('scale').value = res.suggested_scale;
      log(`modeled at full size — scale set to ${res.suggested_scale}`, 'dim');
      await doGenerate();
    } else {
      $('scale').value = 1;
      showResult(res);
    }
    state.generated = true;
    invalidateSlice('shape changed');
    $('desc').value = '';
    if (photo) $('clearphoto').onclick();
    log(`${res.model} ready` + (res.attempts > 1 ? ` (self-repaired after an error)` : ''), 'ok');
    stageMsg(1, `${res.model} ready`, 'ok');
    setMode('edit');
  } catch (e) { log(e.message, 'bad'); }
  endProgress(describeOk);
  setBusy(false);
}

async function doGenerate() {
  const name = $('model').value;
  if (!name) return;
  const prevOp = progOp; progOp = 'generate';
  log(`generate ${name} ` + JSON.stringify(currentParams()), 'dim');
  updateStages();
  try {
    const res = await api('/api/generate', { model: name, params: currentParams(), scale: $('scale').value || '1', rot });
    showResult(res);
    state.generated = true;
    invalidateSlice('shape changed');
    stageMsg(2, '');
  } catch (e) { log(e.message, 'bad'); }
  progOp = prevOp;
  updateStages();
}

function fmtEst(est) {
  if (!est || (!est.time_text && !est.filament_g)) return '';
  const parts = [];
  if (est.time_text) parts.push(`<b>~${est.time_text}</b>`);
  if (est.time_s) {
    const done = new Date(Date.now() + est.time_s * 1000);
    parts.push(`done ~${done.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`);
  }
  if (est.filament_g != null) {
    parts.push(units === 'in'
      ? `${(est.filament_g / 28.3495).toFixed(2)} oz`
      : `${est.filament_g.toFixed(1)} g`);
  }
  if (est.filament_mm != null) {
    parts.push(units === 'in'
      ? `${(est.filament_mm / 304.8).toFixed(1)} ft filament`
      : `${(est.filament_mm / 1000).toFixed(2)} m filament`);
  }
  return parts.join(' · ');
}

async function doSlice() {
  const settings = printSettings();
  log('slicing…', 'dim');
  startProgress('slice', `slicing ${$('model').value}`, 35);
  setBusy(true);
  let sliceOk = false;
  try {
    const res = await api('/api/slice', { model: $('model').value, settings });
    sliceOk = res.ok;
    if (res.overrides?.length) log('overrides: ' + res.overrides.join(', '), 'dim');
    log(res.report, res.ok ? 'ok' : 'bad');
    state.sliced = res.ok;
    state.uploaded = false;
    lastEst = res.estimates || null;
    $('est').classList.remove('stale');
    $('est').innerHTML = fmtEst(lastEst);
    if (res.ok) {
      if (res.supports_auto) {
        $('ps_supports').checked = true;
        try { localStorage.setItem('studio.printset', JSON.stringify(printSettings())); } catch {}
        stageMsg(3, 'tree supports were added automatically — the shape had floating parts', 'warn');
      } else stageMsg(3, 'checked and safe — ready to send', 'ok');
      sliceMeta = {
        material: materialLabel(),
        lh: settings.layer_height,
        infill: settings.infill_pct,
        copies: settings.copies,
        time: lastEst?.time_text || '',
      };
    } else {
      stageMsg(3, 'the safety check failed — see the activity log', 'bad');
    }
  } catch (e) { log(e.message, 'bad'); state.sliced = false; }
  endProgress(sliceOk);
  setBusy(false);
}

async function doUpload() {
  setBusy(true);
  log('uploading (select=false, print=false)…', 'dim');
  try {
    const res = await api('/api/upload', { model: $('model').value });
    log(res.report, res.ok ? 'ok' : 'bad');
    if (res.ok) {
      state.uploaded = true;
      stageMsg(3, 'on the printer — ask Claude to print it', 'ok');
      loadQueue();
    }
  } catch (e) { log(e.message, 'bad'); }
  setBusy(false);
}

function setRot(axis, delta) {
  if (axis < 0) rot = [0, 0, 0];
  else rot[axis] = (rot[axis] + delta) % 360;
  $('rotval').textContent = rot.join('/');
  if (!busy) doGenerate();
}

$('generate').onclick = () => { if (!busy) doGenerate(); };
$('rotx').onclick = () => setRot(0, 90);
$('roty').onclick = () => setRot(1, 90);
$('rotz').onclick = () => setRot(2, 90);
$('rotreset').onclick = () => setRot(-1, 0);
$('buildnew').onclick = () => doDescribe('new');
$('editsel').onclick = () => doDescribe('edit');
$('focusclear').onclick = clearFocus;
$('desc').addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' || e.shiftKey) return;
  e.preventDefault();
  if (busy) return;
  if (e.metaKey || e.ctrlKey) doDescribe(describeMode === 'new' ? 'edit' : 'new');
  else doDescribe(describeMode);
});
$('slice').onclick = doSlice;
$('reslice').onclick = () => { state.sliced = false; updateStages(); doSlice(); };
$('upload').onclick = doUpload;
$('scale').onchange = () => {
  const v = $('scale').value.trim();
  const okVal = /^\d+(\.\d+)?$/.test(v) || /^\d+(\.\d+)?\s*[/:]\s*\d+(\.\d+)?$/.test(v)
    || /^\d+(\.\d+)?%$/.test(v) || v === '';
  $('scale').classList.toggle('badval', !okVal);
  if (!okVal) { stageMsg(2, `"${v}" is not a scale — use 1, 0.5, 1/64 or 150%`, 'bad'); return; }
  stageMsg(2, '');
  if (!busy) doGenerate();
};
$('model').onchange = () => {
  $('scale').value = 1;
  rot = [0, 0, 0]; $('rotval').textContent = '0/0/0';
  const m = currentModel();
  $('model').title = m?.summary || '';
  renderParams(m);
  state.generated = false;
  invalidateSlice('different part');
  setMode(models.length ? 'edit' : 'new');
  doGenerate();
};

// ---------------------------- model tools ----------------------------
$('refine').onclick = async () => {
  const model = $('model').value;
  if (!model) return;
  const m = currentModel();
  if (m && m.imported) { log('imports are fixed meshes — use Change it to modify them', 'bad'); return; }
  const notes = $('desc').value.trim() || null;
  setBusy(true);
  log(`refining ${model}${notes ? ' — focus: ' + notes : ''}…`, 'dim');
  startProgress('refine', `refining ${model} (looking at its own renders)`, 160);
  let ok = false;
  try {
    const res = await apiJob('/api/refine', { model, notes }, 'refine');
    ok = true;
    $('desc').value = '';
    await refreshModels(model);
    showResult(res);
    state.generated = true;
    invalidateSlice('shape changed');
    log(`${model} refined` + (res.attempts > 1 ? ' (self-repaired)' : ''), 'ok');
  } catch (e) { log(e.message, 'bad'); }
  endProgress(ok);
  setBusy(false);
};

$('makeprint').onclick = async () => {
  const model = $('model').value;
  setBusy(true);
  log(`making ${model} printable (Blender voxel remesh)…`, 'dim');
  startProgress('bpy', `solidifying ${model}`, 60);
  let ok = false;
  try {
    const res = await apiJob('/api/make_printable', { model }, 'bpy');
    ok = true;
    await refreshModels(res.model);
    showResult(res);
    state.generated = true;
    invalidateSlice('new model');
    log(`${res.model} ready — watertight and printable`, 'ok');
  } catch (e) { log(e.message, 'bad'); }
  endProgress(ok);
  setBusy(false);
};

$('revert').onclick = async () => {
  const model = $('model').value;
  if (!model) return;
  setBusy(true);
  try {
    const res = await api('/api/revert', { model });
    log(res.note, 'ok');
    stageMsg(2, 'previous version restored — press again to switch back', 'ok');
    await refreshModels(model);
    await doGenerate();
  } catch (e) { log(e.message, 'bad'); }
  setBusy(false);
};

// ---------------------------- floating panel ----------------------------
const side = document.getElementById('side');
const grab = document.getElementById('grab');
const popBtn = document.getElementById('popout');

function panelState() {
  try { return JSON.parse(localStorage.getItem('studio.panel')) || {}; }
  catch { return {}; }
}
function savePanel(st) {
  try { localStorage.setItem('studio.panel', JSON.stringify(st)); } catch {}
}
function clampPos(x, y) {
  const w = side.offsetWidth || 340, h = Math.min(side.offsetHeight || 400, 200);
  x = Math.min(Math.max(0, x), innerWidth - w);
  y = Math.min(Math.max(0, y), innerHeight - h);
  side.style.maxHeight = Math.max(220, innerHeight - y - 12) + 'px';
  return [x, y];
}
function setFloat(on, x = 24, y = 24) {
  side.classList.toggle('float', on);
  if (on) {
    [x, y] = clampPos(x, y);
    side.style.left = x + 'px';
    side.style.top = y + 'px';
  } else {
    side.style.left = side.style.top = '';
    side.style.maxHeight = '';
  }
  popBtn.textContent = on ? '⇲' : '⇱';
  popBtn.title = on ? 'Dock the panel back to the side'
                    : 'Pop the panel out so it can be dragged around';
  resize();
  savePanel({ float: on, x, y });
}
popBtn.onclick = () => {
  const st = panelState();
  setFloat(!side.classList.contains('float'), st.x ?? 24, st.y ?? 24);
};
grab.addEventListener('pointerdown', (e) => {
  if (!side.classList.contains('float') || e.target.closest('button')) return;
  const startX = e.clientX - side.offsetLeft;
  const startY = e.clientY - side.offsetTop;
  grab.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const [x, y] = clampPos(ev.clientX - startX, ev.clientY - startY);
    side.style.left = x + 'px';
    side.style.top = y + 'px';
  };
  const up = () => {
    grab.removeEventListener('pointermove', move);
    grab.removeEventListener('pointerup', up);
    savePanel({ float: true, x: side.offsetLeft, y: side.offsetTop });
  };
  grab.addEventListener('pointermove', move);
  grab.addEventListener('pointerup', up);
});
window.addEventListener('resize', () => {
  if (side.classList.contains('float'))
    [side.style.left, side.style.top] =
      clampPos(side.offsetLeft, side.offsetTop).map(v => v + 'px');
});
{
  const st = panelState();
  if (st.float) setFloat(true, st.x, st.y);
}

// ---------------------------- printer status ----------------------------
function tempPair(t) {
  return t ? `${Math.round(t.actual)}/${Math.round(t.target)}°` : '–';
}
async function pollPrinter() {
  if (document.hidden) return;
  try {
    const p = await (await fetch('/api/printer')).json();
    const dot = $('pdot');
    let text;
    dot.className = 'dot';
    if (!p.reachable) text = 'OctoPrint unreachable';
    else if (!p.temps) text = `printer ${(p.state || 'off').toLowerCase()} — check power/USB`;
    else {
      text = p.state;
      if (/print/i.test(p.state)) dot.classList.add('busy');
      else dot.classList.add('ok');
      text += ` · nozzle ${tempPair(p.temps.tool0)} · bed ${tempPair(p.temps.bed)}`;
    }
    $('ptext').textContent = text;
  } catch {
    $('pdot').className = 'dot';
    $('ptext').textContent = 'studio server unreachable';
  }
}
pollPrinter();
setInterval(pollPrinter, 5000);

// ---------------------------- OctoPrint queue ----------------------------
function fmtSize(b) {
  if (b == null) return '';
  return b > 1048576 ? (b / 1048576).toFixed(1) + ' MB'
                     : Math.round(b / 1024) + ' KB';
}
async function loadQueue() {
  try {
    const files = await (await fetch('/api/files')).json();
    if (files.error) throw new Error('queue unavailable');
    $('qcount').textContent = files.length;
    const list = $('qlist');
    list.innerHTML = '';
    for (const f of files) {
      const row = document.createElement('div');
      row.className = 'qrow';
      const name = document.createElement('span');
      name.className = 'qname'; name.textContent = f.name; name.title = f.name;
      const size = document.createElement('span');
      size.className = 'qsize'; size.textContent = fmtSize(f.size);
      const del = document.createElement('button');
      del.textContent = '×'; del.title = `Delete ${f.name} from OctoPrint`;
      // Two-step inline confirm: native confirm() dialogs are suppressed in
      // some embedded browsers (they return false without ever showing).
      let armTimer = null;
      del.onclick = async () => {
        if (!del.classList.contains('armed')) {
          del.classList.add('armed');
          del.textContent = 'delete?';
          armTimer = setTimeout(() => {
            del.classList.remove('armed');
            del.textContent = '×';
          }, 4000);
          return;
        }
        clearTimeout(armTimer);
        del.disabled = true;
        try {
          await api('/api/files/delete', { name: f.name });
          log(`deleted ${f.name} from OctoPrint`, 'ok');
          loadQueue();
        } catch (e) {
          log(e.message, 'bad');
          del.disabled = false;
          del.classList.remove('armed');
          del.textContent = '×';
        }
      };
      row.append(name, size, del);
      list.appendChild(row);
    }
  } catch (e) { $('qcount').textContent = '?'; }
}
$('queue').addEventListener('toggle', () => { if ($('queue').open) loadQueue(); });
loadQueue();

// ---------------------------- init ----------------------------
(async function init() {
  setMode('new');
  await refreshModels();
  if (models.length) {
    $('model').value = models[0].name;
    $('model').title = models[0].summary || '';
    renderParams(models[0]);
    setMode('edit');
    doGenerate();
  } else {
    stageMsg(1, 'nothing here yet — describe your first part below', 'dim');
  }
  for (const m of models) if (m.error) log(`${m.name}: ${m.error}`, 'bad');

  // Rescue a job that was running when the page was last closed - job
  // results are delivered once, so without this a reload orphans them.
  let last = null;
  try { last = JSON.parse(localStorage.getItem('studio.lastjob')); } catch {}
  if (last && Date.now() - last.t < 30 * 60 * 1000) {
    stageMsg(1, 'a build from before is still running — reattaching…', 'dim');
    startProgress(last.kind || 'describe', 'reattaching to the running build', 120);
    try {
      const res = await pollJob(last.id);
      forgetJob();
      endProgress(true);
      if (res && res.model) {
        await refreshModels(res.model);
        showResult(res);
        state.generated = true;
        stageMsg(1, `${res.model} ready (finished while you were away)`, 'ok');
      }
    } catch (e) {
      forgetJob();
      endProgress(false);
      stageMsg(1, e.message, 'bad');
    }
  }
  updateStages();
})();
