#!/usr/bin/env python
"""Cloud studio checks: the sign-in gate, what the cloud refuses, per-design
settings, and a phone design reaching a home studio intact.

Runs two real servers on spare ports - one STUDIO_MODE=cloud, one home - each
with its own temp data dir and HOME, so nothing touches models/ or ~/.config.

    .venv-cad/bin/python viewer/test_cloud.py
"""
import http.client
import io
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

VIEWER = Path(__file__).resolve().parent
REPO = VIEWER.parent
sys.path.insert(0, str(VIEWER))
import cloudstudio  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def request(port, method, path, body=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
    hdrs = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    conn.request(method, path, body=data, headers=hdrs)
    r = conn.getresponse()
    raw = r.read()
    conn.close()
    return r.status, dict(r.getheaders()), raw


def zipped(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class CloudStudioTest(unittest.TestCase):
    @classmethod
    def serve(cls, root, **env_extra):
        port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("STUDIO_")}
        env.update(HOME=str(root / "home"), STUDIO_DATA=str(root / "data"), **env_extra)
        (root / "home").mkdir(parents=True, exist_ok=True)
        log = open(root / "server.log", "w")
        proc = subprocess.Popen(
            [sys.executable, str(VIEWER / "server.py"), "--port", str(port)],
            env=env, stdout=log, stderr=subprocess.STDOUT)
        cls.addClassCleanup(log.close)
        cls.addClassCleanup(proc.wait, 10)
        cls.addClassCleanup(proc.terminate)
        deadline = time.time() + 60
        while time.time() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("server exited:\n" + (root / "server.log").read_text())
            try:
                if request(port, "GET", "/healthz")[0] == 200:
                    return port
            except OSError:
                time.sleep(0.2)
        raise RuntimeError("server did not come up:\n" + (root / "server.log").read_text())

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="studio-cloudtest-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp, True)
        cls.password = secrets.token_urlsafe(18)     # throwaway, exists only in this run
        cls.cport = cls.serve(cls.tmp / "cloud", STUDIO_MODE="cloud",
                              STUDIO_PASSWORD=cls.password)
        cls.cmodels = cls.tmp / "cloud" / "data" / "models"
        cls.hmodels = cls.tmp / "home" / "data" / "models"
        cls.hmodels.mkdir(parents=True)
        for f in ("cable_clip.py", "_meshlib.py"):
            shutil.copy(REPO / "models" / f, cls.hmodels)
        cls.hport = cls.serve(cls.tmp / "home")
        status, headers, _ = request(cls.cport, "POST", "/api/login",
                                     {"password": cls.password})
        assert status == 200, status
        cls.cookie = headers["Set-Cookie"].split(";")[0]

    def cget(self, path, cookie=True, headers=None):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = self.cookie
        return request(self.cport, "GET", path, headers=h)

    def cpost(self, path, body=None, cookie=True, headers=None):
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = self.cookie
        return request(self.cport, "POST", path, {} if body is None else body, headers=h)

    def hjson(self, method, path, body=None):
        status, _, raw = request(self.hport, method, path, body)
        return status, json.loads(raw)

    def test_01_everything_is_behind_sign_in(self):
        probe = request(self.cport, "GET", "/healthz",
                        headers={"Host": "healthcheck.railway.app"})
        self.assertEqual(probe[0], 200)
        status, headers, _ = self.cget("/", cookie=False)
        self.assertEqual((status, headers.get("Location")), (302, "/login"))
        self.assertEqual(self.cget("/login", cookie=False)[0], 200)
        for path in ("/api/models", "/static/app.js", "/api/sync/list",
                     "/output/cable_clip.stl"):
            self.assertEqual(self.cget(path, cookie=False)[0], 401, path)
        self.assertEqual(self.cpost("/api/generate", {"model": "cable_clip"},
                                    cookie=False)[0], 401)
        forged = self.cookie.rsplit(".", 1)[0] + ".AAAAAAAA"
        self.assertEqual(self.cget("/api/models", cookie=False,
                                   headers={"Cookie": forged})[0], 401)
        self.assertEqual(self.cget("/", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.cget("/api/sync/bundle?name=..%2Fserver")[0], 404)

    def test_02_sign_in(self):
        self.assertEqual(self.cpost("/api/login", {"password": "not it"}, cookie=False)[0], 401)
        status, headers, _ = self.cpost("/api/login", {"password": self.password}, cookie=False)
        self.assertEqual(status, 200)
        for flag in ("HttpOnly", "Secure", "SameSite=Lax"):
            self.assertIn(flag, headers["Set-Cookie"])
        _, _, raw = self.cpost("/api/login", {"password": self.password, "client": "home"},
                              cookie=False)
        self.assertTrue(json.loads(raw)["token"].startswith("v1."))
        self.assertEqual(self.cpost("/api/generate", {"model": "cable_clip"},
                                    headers={"Origin": "https://evil.example"})[0], 403)

    def test_03_cloud_refuses_printer_work(self):
        self.assertEqual(json.loads(self.cget("/api/config")[2])["mode"], "cloud")
        for path in ("/api/slice", "/api/upload", "/api/files/delete",
                     "/api/material_lookup", "/api/make_printable", "/api/solidify"):
            self.assertEqual(self.cpost(path, {"model": "cable_clip"})[0], 403, path)
        self.assertTrue(json.loads(self.cget("/api/printer")[2])["cloud"])
        self.assertEqual(json.loads(self.cget("/api/files")[2]), [])
        _, _, raw = self.cpost("/api/import", {"name": "house.fbx", "data": ""})
        self.assertIn("home studio", json.loads(raw)["error"])

    def test_04_seeded_models_remember_their_settings(self):
        models = json.loads(self.cget("/api/models")[2])
        clip = next(m for m in models if m["name"] == "cable_clip")
        p0 = clip["params"][0]
        status, _, raw = self.cpost("/api/generate", {
            "model": "cable_clip", "params": {p0["name"]: p0["default"] + 1},
            "scale": "1/2", "rot": [90, 0, 0]})
        self.assertEqual(status, 200, raw[:500])
        models = json.loads(self.cget("/api/models")[2])
        state = next(m for m in models if m["name"] == "cable_clip")["state"]
        self.assertEqual(state["scale"], "1/2")
        self.assertEqual(state["rot"], [90.0, 0.0, 0.0])
        self.assertEqual(state["params"][p0["name"]], p0["default"] + 1)
        # an untouched repo model isn't offered to the home studio
        listed = [d["name"] for d in json.loads(self.cget("/api/sync/list")[2])]
        self.assertNotIn("cable_clip", listed)

    def test_05_phone_design_comes_home(self):
        # stands in for a part described on the phone
        src = (REPO / "models" / "cable_clip.py").read_text()
        (self.cmodels / "phone_clip.py").write_text(src.replace('"""', '"""Phone clip. ', 1))
        status, _, raw = self.cpost("/api/generate",
                                    {"model": "phone_clip", "params": {}, "scale": "2"})
        self.assertEqual(status, 200, raw[:500])
        listed = {d["name"]: d for d in json.loads(self.cget("/api/sync/list")[2])}
        self.assertIn("phone_clip", listed)

        status, out = self.hjson("POST", "/api/cloud/connect", {
            "url": f"http://127.0.0.1:{self.cport}", "password": self.password})
        self.assertEqual(status, 200, out)
        cfg = self.tmp / "home" / "home" / ".config" / "part-studio" / "cloud.json"
        self.assertEqual(cfg.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.password, cfg.read_text())

        designs = {d["name"]: d for d in self.hjson("GET", "/api/cloud/designs")[1]}
        self.assertEqual(designs["phone_clip"]["status"], "new")
        status, out = self.hjson("POST", "/api/cloud/pull", {"name": "phone_clip"})
        self.assertEqual(status, 200, out)
        self.assertEqual((self.hmodels / "phone_clip.py").read_bytes(),
                         (self.cmodels / "phone_clip.py").read_bytes())
        home = {m["name"]: m for m in self.hjson("GET", "/api/models")[1]}
        self.assertEqual(home["phone_clip"]["state"]["scale"], "2")   # settings came too
        designs = {d["name"]: d for d in self.hjson("GET", "/api/cloud/designs")[1]}
        self.assertEqual(designs["phone_clip"]["status"], "same")

    def test_06_pull_never_replaces_silently(self):
        local = self.hmodels / "phone_clip.py"
        local.write_text(local.read_text() + "\n# edited at home\n")
        designs = {d["name"]: d for d in self.hjson("GET", "/api/cloud/designs")[1]}
        self.assertEqual(designs["phone_clip"]["status"], "differs")
        status, out = self.hjson("POST", "/api/cloud/pull", {"name": "phone_clip"})
        self.assertTrue(out.get("conflict"), out)
        self.assertIn("# edited at home", local.read_text())
        status, out = self.hjson("POST", "/api/cloud/pull",
                                 {"name": "phone_clip", "overwrite": True})
        self.assertEqual(status, 200, out)
        self.assertNotIn("# edited at home", local.read_text())
        kept = list((self.hmodels / ".history").glob("phone_clip-*.py"))
        self.assertTrue(kept and "# edited at home" in kept[0].read_text())

    def test_07_bundles_are_checked_before_writing(self):
        for bad in ({"models/../evil.py": "x"}, {"/etc/passwd": "x"},
                    {"models/.history/x.py": "x"}, {"models/_meshlib.py": "x"},
                    {"models/imports/x.sh": "x"}, {"models/a/../../b.py": "x"}):
            with self.assertRaises(ValueError, msg=str(bad)):
                cloudstudio.read_bundle(zipped(bad))
        with self.assertRaises(ValueError):
            cloudstudio.read_bundle(b"not a zip")
        ok = cloudstudio.read_bundle(zipped({"models/a.py": "x", "models/.state/a.json": "{}"}))
        self.assertEqual([rel for rel, _ in ok], ["a.py", ".state/a.json"])

    def test_08_seeded_copies_follow_the_repo_until_edited(self):
        repo, vol = self.tmp / "seed_repo", self.tmp / "seed_vol"
        repo.mkdir()
        (repo / "a.py").write_text("v1")
        (repo / "b.py").write_text("v1")
        cloudstudio.seed_models(repo, vol)
        (vol / "b.py").write_text("changed in the cloud")
        time.sleep(0.01)
        (repo / "a.py").write_text("v2")
        (repo / "b.py").write_text("v2")
        cloudstudio.seed_models(repo, vol)
        self.assertEqual((vol / "a.py").read_text(), "v2")
        self.assertEqual((vol / "b.py").read_text(), "changed in the cloud")

    def test_09_wrong_passwords_lock_out(self):
        codes = [self.cpost("/api/login", {"password": f"guess {i}"}, cookie=False)[0]
                 for i in range(6)]
        self.assertEqual(codes, [401] * 5 + [429])
        self.assertEqual(self.cget("/api/models")[0], 200)   # a live session still works


if __name__ == "__main__":
    unittest.main(verbosity=2)
