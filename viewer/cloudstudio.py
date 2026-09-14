"""Cloud studio: Part Studio on a hosted server, so parts can be designed from
a phone away from home and brought into the home studio for printing.

Stdlib only, like server.py. Two halves:

Cloud side (server.py with STUDIO_MODE=cloud)
  - one password (STUDIO_PASSWORD) guards every route; sessions are signed
    tokens, so a restart or a sleeping container signs nobody out, and
    changing the password signs everyone out
  - the repo's models are seeded onto the data volume; /api/sync/* hands the
    designs made or changed there to the home studio as zip bundles

Home side (server.py next to the printer)
  - connect once with the cloud address + password; only a sign-in token is
    kept, in ~/.config/part-studio/cloud.json (0600)
  - list cloud designs and pull one into models/ - never silently over a
    local file that differs
"""
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

MIN_PASSWORD = 12
SESSION_COOKIE = "ps_session"
BROWSER_DAYS = 30
HOME_DAYS = 180
NAME_RE = r"[A-Za-z0-9][A-Za-z0-9._ -]{0,99}"


def valid_name(name):
    name = str(name or "")
    return bool(re.fullmatch(NAME_RE, name)) and ".." not in name


# ------------------------------ file hashing ------------------------------
_sha_cache = {}          # path -> (size, mtime_ns, sha256)
_sha_lock = threading.Lock()


def sha_cached(path):
    """sha256 of a file, recomputed only when its size or mtime moves - the
    model list asks for every design's signature on each refresh."""
    path = Path(path)
    st = path.stat()
    with _sha_lock:
        hit = _sha_cache.get(str(path))
    if hit and hit[0] == st.st_size and hit[1] == st.st_mtime_ns:
        return hit[2]
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    with _sha_lock:
        _sha_cache[str(path)] = (st.st_size, st.st_mtime_ns, h.hexdigest())
    return h.hexdigest()


# ----------------------- per-design settings (both sides) -----------------------
def design_file(models, name):
    py = models / f"{name}.py"
    return py if py.is_file() else models / "imports" / f"{name}.stl"


def save_state(models, name, params, scale, rot):
    """Remember the sliders, scale and rotation a design was last built with,
    so it comes back - and comes home - the way it was left."""
    f = design_file(models, name)
    if not f.is_file():
        return
    d = models / ".state"
    d.mkdir(exist_ok=True)
    (d / f"{name}.json").write_text(json.dumps({
        "sig": sha_cached(f),
        "params": {k: float(v) for k, v in (params or {}).items()},
        "scale": str(scale if scale not in (None, "") else 1),
        "rot": [float(a) % 360 for a in (rot or [0, 0, 0])][:3],
    }))


def design_state(models, name):
    """Last-used settings - but only while the design file is still the one
    they were set on, since an edit can change what the sliders mean."""
    try:
        st = json.loads((models / ".state" / f"{name}.json").read_text())
        f = design_file(models, name)
        if f.is_file() and st.get("sig") == sha_cached(f):
            return {"params": st.get("params") or {},
                    "scale": st.get("scale", "1"),
                    "rot": st.get("rot") or [0, 0, 0]}
    except (OSError, ValueError, AttributeError):
        pass
    return None


# ------------------------------ cloud: seeding ------------------------------
SEED_MANIFEST = ".seeded.json"


def read_manifest(models):
    try:
        return json.loads((models / SEED_MANIFEST).read_text())
    except (OSError, ValueError):
        return {}


def seed_models(repo_models, models):
    """Copy the repo's model scripts onto the data volume. A copy nobody has
    changed in the cloud follows the repo on later deploys; a changed one is
    left alone. Nothing is deleted."""
    models.mkdir(parents=True, exist_ok=True)
    manifest = read_manifest(models)
    for src in sorted(repo_models.glob("*.py")):
        dst = models / src.name
        want = sha_cached(src)
        if dst.is_file():
            have = sha_cached(dst)
            if have != want and manifest.get(src.name) != have:
                continue                    # changed in the cloud - keep it
            if have != want:
                shutil.copyfile(src, dst)
        else:
            shutil.copyfile(src, dst)
        manifest[src.name] = want
    (models / SEED_MANIFEST).write_text(json.dumps(manifest, indent=1, sort_keys=True))


# ------------------------------ cloud: sign-in ------------------------------
class Auth:
    """One shared password. Session tokens are HMAC-signed with a key derived
    from the password and a random per-volume salt: they survive restarts,
    can't be forged or brute-forced offline from a stolen cookie, and all
    stop working together when the password changes."""

    def __init__(self, data_dir, password):
        self.password = password or ""
        self.configured = len(self.password) >= MIN_PASSWORD
        self._digest = hashlib.sha256(self.password.encode()).digest()
        self._key = None
        if self.configured:
            data_dir.mkdir(parents=True, exist_ok=True)
            salt_file = data_dir / ".session_salt"
            try:
                fd = os.open(salt_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as f:
                    f.write(secrets.token_bytes(32))
            except FileExistsError:
                pass
            self._key = hashlib.pbkdf2_hmac(
                "sha256", self.password.encode(), salt_file.read_bytes(), 200_000)

    def check(self, candidate):
        if not self.configured or not isinstance(candidate, str):
            return False
        return hmac.compare_digest(
            hashlib.sha256(candidate.encode()).digest(), self._digest)

    def mint(self, days):
        body = f"v1.{int(time.time() + days * 86400)}.{secrets.token_urlsafe(9)}"
        return f"{body}.{self._sign(body)}"

    def verify(self, token):
        if not self.configured or not token:
            return False
        parts = str(token).split(".")
        if len(parts) != 4 or parts[0] != "v1" or not parts[1].isdigit():
            return False
        body = ".".join(parts[:3])
        if not hmac.compare_digest(parts[3].encode(), self._sign(body).encode()):
            return False
        return int(parts[1]) > time.time()

    def _sign(self, body):
        mac = hmac.new(self._key, body.encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(mac).decode().rstrip("=")


class LoginLimiter:
    """Wrong passwords: 5 per address and 20 overall per 15 minutes. The
    overall cap is what really bounds guessing - forwarded addresses can be
    faked."""
    PER_ADDR, OVERALL, WINDOW = 5, 20, 900

    def __init__(self):
        self._lock = threading.Lock()
        self._fails = {}        # addr -> [timestamps]
        self._all = []

    def _prune(self, now):
        cut = now - self.WINDOW
        self._all = [t for t in self._all if t > cut]
        for addr in list(self._fails):
            kept = [t for t in self._fails[addr] if t > cut]
            if kept:
                self._fails[addr] = kept
            else:
                del self._fails[addr]

    def blocked(self, addr):
        with self._lock:
            self._prune(time.time())
            return (len(self._fails.get(addr, ())) >= self.PER_ADDR
                    or len(self._all) >= self.OVERALL)

    def failed(self, addr):
        with self._lock:
            now = time.time()
            self._fails.setdefault(addr, []).append(now)
            self._all.append(now)

    def succeeded(self, addr):
        with self._lock:
            self._fails.pop(addr, None)


def session_cookie(token):
    return (f"{SESSION_COOKIE}={token}; Path=/; Max-Age={BROWSER_DAYS * 86400}; "
            "HttpOnly; Secure; SameSite=Lax")


CLEAR_COOKIE = f"{SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax"


def token_from_headers(headers):
    auth = headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    for part in (headers.get("Cookie") or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == SESSION_COOKIE:
            return value
    return None


_PAGE_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Part Studio</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#14161a">
<style>
  :root { --bg: #14161a; --panel: #1c1f26; --edge: #2a2e37; --text: #e6e8ec;
          --dim: #9aa1ad; --accent: #3b6ea5; --bad: #ff6369; }
  * { box-sizing: border-box; margin: 0; }
  body { min-height: 100vh; min-height: 100dvh; display: flex; align-items: center;
         justify-content: center; padding: 16px; background: var(--bg);
         color: var(--text); font: 16px/1.45 system-ui, -apple-system, sans-serif; }
  .card { width: 100%; max-width: 360px; background: var(--panel);
          border: 1px solid var(--edge); border-radius: 12px; padding: 22px; }
  h1 { font-size: 19px; }
  .sub { color: var(--dim); font-size: 13px; margin: 4px 0 14px; }
  p { color: var(--dim); font-size: 14px; margin-top: 10px; }
  code { color: var(--text); }
  label { display: block; color: var(--dim); font-size: 13px; margin: 12px 0 5px; }
  input { width: 100%; padding: 10px 12px; background: var(--bg); color: var(--text);
          border: 1px solid var(--edge); border-radius: 8px; font: inherit; }
  input:focus { outline: 1px solid var(--accent); }
  input[readonly] { color: var(--dim); }
  button { width: 100%; margin-top: 18px; padding: 11px 0; border: 0; border-radius: 8px;
           background: var(--accent); color: #eaf1f8; font: inherit; font-weight: 600; }
  button:disabled { opacity: .5; }
  #err { color: var(--bad); font-size: 13px; min-height: 18px; margin-top: 10px; }
</style></head><body>
"""

LOGIN_PAGE = _PAGE_HEAD + """<form class="card" id="f">
  <h1>Part Studio</h1>
  <div class="sub">Cloud studio &middot; sign in to design</div>
  <label for="u">Account</label>
  <input id="u" name="username" autocomplete="username" value="studio" readonly>
  <label for="p">Password</label>
  <input id="p" name="password" type="password" autocomplete="current-password" required autofocus>
  <button id="b">Sign in</button>
  <div id="err" role="alert"></div>
</form>
<script>
document.getElementById('f').onsubmit = async (e) => {
  e.preventDefault();
  const b = document.getElementById('b'), err = document.getElementById('err');
  b.disabled = true; err.textContent = '';
  try {
    const r = await fetch('/api/login', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: document.getElementById('p').value }) });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) { location.href = '/'; return; }
    err.textContent = d.error || 'sign-in failed';
  } catch { err.textContent = 'could not reach the studio - try again'; }
  b.disabled = false;
};
</script></body></html>
"""

SETUP_PAGE = _PAGE_HEAD + """<div class="card">
  <h1>Part Studio</h1>
  <div class="sub">Cloud studio &middot; not set up yet</div>
  <p>This studio stays locked until it has a password. In Railway, open this
  service's <b>Variables</b> tab and add <code>STUDIO_PASSWORD</code> with a
  password of at least 12 characters. The studio restarts by itself.</p>
</div></body></html>
"""


# --------------------------- cloud: design export ---------------------------
def doc_summary(text):
    m = re.search(r'("""|\'\'\')', text)
    if not m:
        return ""
    first = text[m.end():].lstrip().split("\n", 1)[0]
    return first.replace(m.group(1), "").strip()[:90]


def import_files(models, stem):
    imp = models / "imports"
    return [p for p in (imp / f"{stem}.stl", imp / f"{stem}.json",
                        imp / f"{stem}.orient.json") if p.is_file()]


def list_designs(models):
    """Designs made or changed in the cloud: parametric parts that differ from
    what the repo seeded, and every imported mesh."""
    manifest = read_manifest(models)
    out = []
    for f in models.glob("*.py"):
        if f.stem.startswith("_") or not valid_name(f.stem):
            continue
        sha = sha_cached(f)
        if manifest.get(f.name) == sha:
            continue                        # the repo's own, untouched
        out.append({"name": f.stem, "kind": "part", "sha": sha,
                    "modified": f.stat().st_mtime,
                    "summary": doc_summary(f.read_text(errors="replace")),
                    "state": design_state(models, f.stem)})
    imp = models / "imports"
    for f in (imp.glob("*.stl") if imp.is_dir() else []):
        if not valid_name(f.stem):
            continue
        try:
            title = json.loads((imp / f"{f.stem}.json").read_text()).get("title")
        except (OSError, ValueError, AttributeError):
            title = None
        out.append({"name": f.stem, "kind": "import", "sha": sha_cached(f),
                    "modified": f.stat().st_mtime,
                    "summary": title or "imported mesh",
                    "state": design_state(models, f.stem)})
    out.sort(key=lambda d: -d["modified"])
    return out


def bundle(models, name):
    """One design as a zip: its file, any mesh it is built on, attribution,
    orientation, and last-used settings."""
    if not valid_name(name):
        raise ValueError(f"bad name {name!r}")
    py = models / f"{name}.py"
    if py.is_file():
        files = [py]
        m = re.search(r"load_import\(\s*['\"](" + NAME_RE + r")['\"]",
                      py.read_text(errors="replace"))
        if m and valid_name(m.group(1)):
            files += import_files(models, m.group(1))
    else:
        files = import_files(models, name)
        if not files or files[0].suffix != ".stl":
            raise FileNotFoundError(f"no such design: {name}")
    state = models / ".state" / f"{name}.json"
    if state.is_file():
        files.append(state)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, "models/" + f.relative_to(models).as_posix())
    return buf.getvalue()


# ------------------------------ home: pulling ------------------------------
CLIENT_FILE = Path.home() / ".config" / "part-studio" / "cloud.json"
BUNDLE_PATH = re.compile(r"models/(?:" + NAME_RE + r"\.py|imports/" + NAME_RE
                         + r"\.(?:stl|json)|\.state/" + NAME_RE + r"\.json)")
MAX_ENTRY = 80 * 1024 * 1024


def client_config():
    try:
        cfg = json.loads(CLIENT_FILE.read_text())
        return cfg if cfg.get("url") and cfg.get("token") else None
    except (OSError, ValueError, AttributeError):
        return None


def status():
    cfg = client_config()
    return {"connected": bool(cfg), "url": cfg["url"] if cfg else None}


def cloud_base(url):
    raw = str(url or "").strip().rstrip("/")
    if "://" not in raw:
        raw = "https://" + raw
    u = urllib.parse.urlparse(raw)
    local = u.hostname in ("127.0.0.1", "localhost")
    if not u.hostname or (u.scheme != "https" and not (u.scheme == "http" and local)):
        raise ValueError("use the https:// address of your cloud studio")
    return f"{u.scheme}://{u.netloc}"


def _call(url, token=None, body=None, timeout=90):
    headers = {"User-Agent": "PartStudio-home/1.0"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error")
        except (ValueError, AttributeError):
            msg = None
        if e.code == 401 and token:
            raise PermissionError(
                "the cloud studio no longer accepts this Mac's sign-in (was the "
                "password changed?) - disconnect, then connect again")
        raise RuntimeError(msg or f"the cloud studio answered HTTP {e.code}")
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(
            f"could not reach the cloud studio ({getattr(e, 'reason', e)})")


def connect(url, password):
    base = cloud_base(url)
    out = json.loads(_call(base + "/api/login",
                           body={"password": password or "", "client": "home"}))
    if not out.get("token"):
        raise RuntimeError("the cloud studio did not hand back a sign-in token")
    CLIENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(CLIENT_FILE.parent, 0o700)
    fd = os.open(CLIENT_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": base, "token": out["token"],
                   "connected": int(time.time())}, f)
    os.chmod(CLIENT_FILE, 0o600)     # O_CREAT's mode skips an existing file
    return status()


def disconnect():
    CLIENT_FILE.unlink(missing_ok=True)
    return status()


def _require():
    cfg = client_config()
    if not cfg:
        raise PermissionError("not connected to a cloud studio yet")
    return cfg


def remote_designs(models):
    """The cloud's designs, each marked against this studio: new, differs
    (a local file with other content), settings (same file, other sliders),
    or same."""
    cfg = _require()
    items = json.loads(_call(cfg["url"] + "/api/sync/list", token=cfg["token"]))
    out = []
    for it in items:
        name = it.get("name")
        if not valid_name(name):
            continue
        local = (models / f"{name}.py" if it.get("kind") == "part"
                 else models / "imports" / f"{name}.stl")
        if not local.is_file():
            it["status"] = "new"
        elif sha_cached(local) != it.get("sha"):
            it["status"] = "differs"
        elif it.get("state") and it["state"] != design_state(models, name):
            it["status"] = "settings"
        else:
            it["status"] = "same"
        out.append(it)
    return out


def read_bundle(data):
    """Check a bundle before anything touches disk: only known design paths,
    plain names, bounded sizes."""
    entries, total = [], 0
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError("the cloud studio sent something that isn't a design bundle")
    with z:
        infos = [i for i in z.infolist() if not i.is_dir()]
        if len(infos) > 12:
            raise ValueError("bundle has too many files")
        for info in infos:
            arc = info.filename
            if ".." in arc or not BUNDLE_PATH.fullmatch(arc):
                raise ValueError(f"unexpected file in bundle: {arc!r}")
            with z.open(info) as f:
                content = f.read(MAX_ENTRY + 1)
            total += len(content)
            if len(content) > MAX_ENTRY or total > 3 * MAX_ENTRY:
                raise ValueError(f"bundle file too large: {arc}")
            entries.append((arc[len("models/"):], content))
    if not any(rel.endswith((".py", ".stl")) for rel, _ in entries):
        raise ValueError("bundle has no design file")
    return entries


def pull(models, name, overwrite=False):
    """Bring one cloud design into models/. A local design file with other
    content is only replaced with overwrite=True, and even then it is kept:
    parts go to .history (so "undo change" swaps back), meshes to a .bak."""
    if not valid_name(name):
        raise ValueError(f"bad name {name!r}")
    cfg = _require()
    entries = read_bundle(_call(
        cfg["url"] + "/api/sync/bundle?name=" + urllib.parse.quote(name),
        token=cfg["token"], timeout=180))
    conflicts = [rel for rel, content in entries
                 if rel.endswith((".py", ".stl")) and (models / rel).is_file()
                 and (models / rel).read_bytes() != content]
    if conflicts and not overwrite:
        return {"conflict": True, "files": conflicts}
    stamp = int(time.time())
    kept = []
    for rel, content in entries:
        target = models / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel in conflicts:
            if rel.endswith(".py"):
                (models / ".history").mkdir(exist_ok=True)
                backup = models / ".history" / f"{target.stem}-{stamp}.py"
            else:
                backup = target.with_name(f"{target.stem}-{stamp}.stl.bak")
            shutil.copyfile(target, backup)
            kept.append(backup.relative_to(models).as_posix())
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(content)
        os.replace(tmp, target)
    return {"model": name, "files": [rel for rel, _ in entries], "kept": kept}
