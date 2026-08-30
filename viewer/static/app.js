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
const log = (msg, cls) => {
  const el = document.createElement('div');
  if (cls) el.className = cls;   // ok | bad | dim | warn
  el.textContent = msg;
  $('log').appendChild(el);
  $('log').scrollTop = $('log').scrollHeight;
};

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
  new THREE.LineBasicMaterial({ color: 0xff7a45 })
);
scene.add(border);

let mesh = null;
const material = new THREE.MeshStandardMaterial({
  color: 0xff9a62, metalness: 0.05, roughness: 0.55,
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
    mesh = new THREE.Mesh(geom, material);
    scene.add(mesh);
    const size = Math.max(bb.max.x - bb.min.x, bb.max.y - bb.min.y, bb.max.z - bb.min.z);
    const d = Math.max(size * 2.6, 60);
    camera.position.set(d, -d, d * 0.75);
    controls.target.set(0, 0, (bb.max.z - bb.min.z) / 2);
  });
}

// ---------------------------- pipeline controls ----------------------------
let models = [];
const state = { generated: false, sliced: false };

function setButtons() {
  $('slice').disabled = !state.generated;
  $('upload').disabled = !state.sliced;
}

function renderParams(model) {
  const box = $('params');
  box.innerHTML = '';
  for (const p of model.params) {
    const field = document.createElement('div');
    field.className = 'field';
    const label = document.createElement('label');
    label.textContent = `${p.name} (${units})`;
    label.htmlFor = 'p_' + p.name;
    const input = document.createElement('input');
    input.type = 'number'; input.step = units === 'in' ? '0.01' : '0.1';
    input.id = 'p_' + p.name;
    input.value = toDisplay(p.default);
    input.dataset.param = p.name; input.dataset.mm = p.default;
    field.append(label, input);
    box.appendChild(field);
  }
}

function currentParams() {
  const out = {};
  for (const el of $('params').querySelectorAll('input[data-param]'))
    out[el.dataset.param] = toMM(parseFloat(el.value));
  return out;
}

$('units').textContent = units;
$('units').onclick = () => {
  // convert visible inputs in place, then re-label
  const mmVals = currentParams();
  units = units === 'in' ? 'mm' : 'in';
  try { localStorage.setItem('studio.units', units); } catch {}
  $('units').textContent = units;
  for (const el of $('params').querySelectorAll('input[data-param]')) {
    el.value = toDisplay(mmVals[el.dataset.param]);
    el.step = units === 'in' ? '0.01' : '0.1';
  }
  for (const lab of $('params').querySelectorAll('label'))
    lab.textContent = lab.textContent.replace(/\((in|mm)\)$/, `(${units})`);
  if (lastResult) showResult(lastResult);
};

async function api(path, body) {
  const r = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await r.json();
  if (data.error) throw new Error(data.error);
  return data;
}

let lastResult = null;
function showResult(res) {
  lastResult = res;
  let html = `<b>${fmtLen(res.bbox[0])} × ${fmtLen(res.bbox[1])} × ${fmtLen(res.bbox[2])}</b> · ${fmtVol(res.volume_cm3)}`;
  for (const w of res.warnings || []) html += `<div class="warn">⚠ ${w}</div>`;
  $('stats').innerHTML = html;
  showSTL(res.stl);
  for (const w of res.warnings || []) log('⚠ ' + w, 'warn');
}

let busy = false;
function setBusy(b) {
  busy = b;
  for (const id of ['buildnew', 'editsel', 'generate']) $(id).disabled = b;
  if (b) { $('slice').disabled = true; $('upload').disabled = true; }
  else setButtons();
}

async function refreshModels(selectName) {
  models = await (await fetch('/api/models')).json();
  const sel = $('model');
  sel.innerHTML = '';
  for (const m of models) {
    const o = document.createElement('option');
    o.value = m.name; o.textContent = m.name + (m.summary ? ' — ' + m.summary : '');
    sel.appendChild(o);
  }
  if (selectName) sel.value = selectName;
  const cur = models.find(x => x.name === sel.value);
  if (cur) renderParams(cur);
}

let photo = null;   // {name, data} base64 payload for /api/describe
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
  };
  rd.readAsDataURL(f);
};
$('clearphoto').onclick = () => {
  photo = null; $('photo').value = '';
  $('photoname').textContent = 'no photo';
  $('clearphoto').hidden = true;
};

$('importbtn').onclick = () => $('importfile').click();
$('importfile').onchange = () => {
  const f = $('importfile').files[0];
  if (!f) return;
  if (f.size > 60 * 1024 * 1024) { log('mesh too large (60MB max)', 'bad'); return; }
  const rd = new FileReader();
  rd.onload = async () => {
    setBusy(true);
    log(`importing ${f.name}…`, 'dim');
    try {
      const res = await api('/api/import',
        { name: f.name, data: rd.result.split(',')[1] });
      await refreshModels(res.model);
      $('scale').value = 1;
      await doGenerate();
      log(`${res.model} imported`, 'ok');
    } catch (e) { log(e.message, 'bad'); }
    $('importfile').value = '';
    setBusy(false);
  };
  rd.readAsDataURL(f);
};

async function doDescribe(mode) {
  const description = $('desc').value.trim();
  if (!description) { log('describe the part first', 'bad'); return; }
  const model = $('model').value;
  if (mode === 'edit' && !model) { log('no model selected to edit', 'bad'); return; }
  setBusy(true);
  log(mode === 'edit' ? `editing ${model}: ${description}` : `building: ${description}`, 'dim');
  if (photo) log(`with reference photo: ${photo.name}`, 'dim');
  log('asking Claude — this can take a minute…', 'dim');
  try {
    const res = await api('/api/describe', { mode, model, description, image: photo });
    $('scale').value = 1;
    await refreshModels(res.model);
    showResult(res);
    state.generated = true; state.sliced = false;
    $('desc').value = '';
    $('clearphoto').onclick && photo && $('clearphoto').onclick();
    log(`${res.model} ready` + (res.attempts > 1 ? ` (self-repaired after an error)` : ''), 'ok');
  } catch (e) { log(e.message, 'bad'); }
  setBusy(false);
}

async function doGenerate() {
  const name = $('model').value;
  $('generate').disabled = true;
  log(`generate ${name} ` + JSON.stringify(currentParams()), 'dim');
  try {
    const res = await api('/api/generate', { model: name, params: currentParams(), scale: $('scale').value || '1' });
    showResult(res);
    state.generated = true; state.sliced = false;
    log('STL ready', 'ok');
  } catch (e) { log(e.message, 'bad'); }
  $('generate').disabled = false;
  setButtons();
}

async function doSlice() {
  $('slice').disabled = true;
  log('slicing…', 'dim');
  try {
    const res = await api('/api/slice', { model: $('model').value });
    log(res.report, res.ok ? 'ok' : 'bad');
    state.sliced = res.ok;
  } catch (e) { log(e.message, 'bad'); state.sliced = false; }
  setButtons();
}

async function doUpload() {
  $('upload').disabled = true;
  log('uploading (select=false, print=false)…', 'dim');
  try {
    const res = await api('/api/upload', { model: $('model').value });
    log(res.report, res.ok ? 'ok' : 'bad');
  } catch (e) { log(e.message, 'bad'); }
  $('upload').disabled = false;
}

$('generate').onclick = doGenerate;
$('buildnew').onclick = () => doDescribe('new');
$('editsel').onclick = () => doDescribe('edit');
$('slice').onclick = doSlice;
$('upload').onclick = doUpload;
$('scale').onchange = () => { if (!busy) doGenerate(); };
$('model').onchange = () => {
  $('scale').value = 1;
  const m = models.find(x => x.name === $('model').value);
  renderParams(m);
  state.generated = state.sliced = false;
  setButtons();
  doGenerate();
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
  // Keep the card inside the window: shrink it as it nears the bottom edge.
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

(async function init() {
  models = await (await fetch('/api/models')).json();
  for (const m of models) {
    const o = document.createElement('option');
    o.value = m.name; o.textContent = m.name + (m.summary ? ' — ' + m.summary : '');
    $('model').appendChild(o);
    if (m.error) log(`${m.name}: ${m.error}`, 'bad');
  }
  if (models.length) {
    $('model').value = models[0].name;
    renderParams(models[0]);
    doGenerate();
  } else {
    log('no models found in models/', 'bad');
  }
})();
