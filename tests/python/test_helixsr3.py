"""HelixSR 3 support in the Linux engine (src/linux/helixsr_swapper_linux.py), against a fake release.

The fake release has its own stand-in for upstream's setup/helixsr_bridge.py that records its arguments, so these
tests never run upstream's code. Run from the repo root: python3 -m unittest discover -s tests/python -v
"""

import hashlib
import importlib.util
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENGINE = os.path.join(REPO, "src", "linux", "helixsr_swapper_linux.py")

FAKE_BRIDGE = r'''
import json, os, sys
release, cmd, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
with open(os.path.join(release, "calls.jsonl"), "a") as f:
    f.write(json.dumps([cmd] + rest) + "\n")
if os.environ.get("FAKE_BRIDGE_FAIL"):
    print(json.dumps({"protocol": 1, "ok": False, "error": os.environ["FAKE_BRIDGE_FAIL"], "messages": []}))
    sys.exit(1)
print("noise before the answer")
print(json.dumps({"protocol": 1, "ok": True, "game": {"folder": rest[1] if len(rest) > 1 else None},
                  "messages": ["installed HelixSR Scaler"]}))
'''


def load_engine():
    spec = importlib.util.spec_from_file_location("helixsr_engine_under_test", ENGINE)
    eng = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eng)
    return eng


def write(path, data=b"MZ" + b"\0" * 64):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data if isinstance(data, bytes) else data.encode())


class HelixSR3Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helixsr3-")
        self.old_env = dict(os.environ)
        os.environ["HOME"] = os.path.join(self.tmp, "home")
        os.environ["XDG_DATA_HOME"] = os.path.join(self.tmp, "data")
        os.environ.pop("HELIXSR3_RELEASE", None)
        os.environ.pop("FAKE_BRIDGE_FAIL", None)
        self.eng = load_engine()
        self.eng.CONFIG_FILE = os.path.join(self.tmp, "config.json")
        self.release = self.eng.helixsr3_default_dir()

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.old_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- fixtures ---------------------------------------------------------------------------------------------------

    def make_release(self, network=True, hlx=True):
        r = self.release
        write(os.path.join(r, "setup", "helixsr_bridge.py"), FAKE_BRIDGE)
        dll = b"MZ\0HelixSR 3.2.0\0" + b"\0" * 128
        if network:
            dll += b"HXSRNET1" + b"\0" * 24
        write(os.path.join(r, "HelixSR", "helixsr.dll"), dll)
        hlx_dll = b"MZ HLX FSR 4 (4.1.2)" + b"\0" * 64
        if hlx:
            hlx_dll += b"HLXFSR4D" + b"\0" * 16
        write(os.path.join(r, "HLX-FSR4", "amd_fidelityfx_upscaler_dx12.dll"), hlx_dll)
        write(os.path.join(r, "helixsr-scaler", "OptiScaler.dll"))
        return r

    def calls(self):
        p = os.path.join(self.release, "calls.jsonl")
        if not os.path.isfile(p):
            return []
        with open(p) as f:
            return [json.loads(l) for l in f if l.strip()]

    def make_game(self, name="Game"):
        g = os.path.join(self.tmp, "games", name)
        write(os.path.join(g, name + ".exe"), b"MZ" + b"\0" * 4096)
        return g

    # --- status -----------------------------------------------------------------------------------------------------

    def test_status_not_downloaded(self):
        st = self.eng.helixsr3_status()
        self.assertFalse(st["downloaded"])
        self.assertFalse(st["scalerReady"])
        self.assertEqual(st["version"], self.eng.HELIXSR3_VERSION)
        self.assertIn("helixsr3", self.eng.get_core_status())

    def test_status_reads_trailers(self):
        self.make_release(network=False, hlx=True)
        st = self.eng.helixsr3_status()
        self.assertTrue(st["downloaded"])
        self.assertFalse(st["networkReady"])
        self.assertFalse(st["scalerReady"])
        self.assertTrue(st["dropinReady"])
        self.make_release(network=True, hlx=False)
        st = self.eng.helixsr3_status()
        self.assertTrue(st["scalerReady"])
        self.assertFalse(st["dropinReady"])
        self.assertEqual(st["version"], "3.2.0")

    def test_release_dir_from_config(self):
        other = os.path.join(self.tmp, "mine", "HelixSR-3.2.0")
        self.release = other
        self.make_release()
        with open(self.eng.CONFIG_FILE, "w") as f:
            json.dump({"helixsr3Release": other}, f)
        self.assertEqual(self.eng.helixsr3_release_dir(), self.eng.normalize_path(other))

    # --- scan -------------------------------------------------------------------------------------------------------

    def test_scan_recognises_helixsr_scaler(self):
        g = self.make_game()
        write(os.path.join(g, "nvngx_dlss.dll"))
        write(os.path.join(g, "OptiScaler.ini"), "[HelixSR]\nWaveSize=auto\n")
        write(os.path.join(g, "dxgi.dll"))
        write(os.path.join(g, "HelixSR", "helixsr.dll"), b"MZ\0HelixSR 3.2.0\0")
        write(os.path.join(g, "OptiScaler", "amd_fidelityfx_upscaler_dx12.dll"))
        write(os.path.join(g, "HelixSR-Scaler-backup", "amd_fidelityfx_upscaler_dx12.dll"))
        write(os.path.join(g, "HelixSR-Scaler.files"),
              "# version=2.1.0\nname=dxgi.dll\ndxgi.dll\nOptiScaler.ini\nHelixSR/helixsr.dll\n")
        s = self.eng.scan_game(g)
        self.assertEqual(s["route"], "scaler")
        self.assertTrue(s["installed"])
        self.assertTrue(s["helixsr3"])
        self.assertEqual(s["version"], "3.2.0")
        self.assertEqual(s["scalerVersion"], "2.1.0")
        self.assertEqual(s["fsrTargets"], [])  # HelixSR Scaler's own FSR DLLs are not the game's
        self.assertEqual(s["protonLaunchOptions"], "")  # dxgi.dll: Proton loads it by itself
        self.assertIn("HelixSR Scaler", s["routeDisplay"])

    def test_scan_scaler_other_name_needs_override(self):
        self.assertEqual(self.eng.compute_proton_launch_option("scaler", "winmm.dll", False),
                         'WINEDLLOVERRIDES="winmm=n,b" %command%')

    def test_scan_recognises_hlx_dropin(self):
        g = self.make_game()
        write(os.path.join(g, "amd_fidelityfx_upscaler_dx12.dll"), b"MZ HLX FSR 4 (4.1.2)")
        write(os.path.join(g, "amd_fidelityfx_upscaler_dx12.original.dll"))
        write(os.path.join(g, "helixsr-install.json"),
              json.dumps({"helixsr": "3.2.0", "upscaler": "HLX FSR 4", "route": "direct"}))
        s = self.eng.scan_game(g)
        self.assertEqual(s["route"], "hlxfsr")
        self.assertTrue(s["installed"])

    def test_scan_keeps_legacy_direct(self):
        g = self.make_game()
        write(os.path.join(g, "amd_fidelityfx_dx12.dll"))
        write(os.path.join(g, "amd_fidelityfx_dx12.original.dll"))
        write(os.path.join(g, "helixsr-install.json"), json.dumps({"helixsr": "1.8.1", "route": "direct"}))
        self.assertEqual(self.eng.scan_game(g)["route"], "direct")

    # --- install / remove through the bridge -----------------------------------------------------------------------

    def test_install_scaler_goes_through_bridge(self):
        self.make_release()
        g = self.make_game()
        write(os.path.join(g, "nvngx_dlss.dll"))
        res = self.eng.install_helixsr(g, route_override="scaler", opti_dll="winmm.dll")
        self.assertTrue(res["success"])
        self.assertIn("HelixSR Scaler", res["message"])
        call = self.calls()[-1]
        self.assertEqual(call[0], "install")
        args = dict(zip(call[1::2], call[2::2]))
        self.assertEqual(args["--game"], self.eng.normalize_path(g))
        self.assertEqual(args["--way"], "scaler")
        self.assertEqual(args["--scaler"], os.path.join(self.release, "helixsr-scaler"))
        self.assertEqual(args["--scaler-name"], "winmm.dll")

    def test_install_scaler_ignores_asi_name(self):
        self.make_release()
        g = self.make_game()
        self.eng.install_helixsr(g, route_override="scaler", opti_dll="OptiScaler.asi")
        self.assertNotIn("--scaler-name", self.calls()[-1])

    def test_install_dropin_uses_fsr_way(self):
        self.make_release()
        g = self.make_game()
        write(os.path.join(g, "amd_fidelityfx_upscaler_dx12.dll"))
        self.eng.install_helixsr(g, route_override="hlxfsr")
        call = self.calls()[-1]
        self.assertEqual(call[:5], ["install", "--game", self.eng.normalize_path(g), "--way", "fsr"])

    def test_install_refuses_unbuilt(self):
        self.make_release(network=False, hlx=False)
        g = self.make_game()
        with self.assertRaises(RuntimeError):
            self.eng.install_helixsr(g, route_override="scaler")
        with self.assertRaises(RuntimeError):
            self.eng.install_helixsr(g, route_override="hlxfsr")
        self.assertEqual(self.calls(), [])

    def test_bridge_error_is_raised(self):
        self.make_release()
        os.environ["FAKE_BRIDGE_FAIL"] = "no game (.exe) found"
        with self.assertRaises(RuntimeError) as cm:
            self.eng.helixsr3_bridge("status")
        self.assertIn("no game", str(cm.exception))

    def test_uninstall_scaler_goes_through_bridge(self):
        self.make_release()
        g = self.make_game()
        write(os.path.join(g, "OptiScaler.ini"))
        write(os.path.join(g, "HelixSR-Scaler.files"), "name=dxgi.dll\ndxgi.dll\n")
        self.eng.uninstall_helixsr(g)
        self.assertEqual(self.calls()[-1], ["remove", "--game", self.eng.normalize_path(g)])

    def test_legacy_install_keeps_helixsr3_when_legacy_not_built(self):
        self.make_release()
        g = self.make_game()
        write(os.path.join(g, "OptiScaler.ini"))
        write(os.path.join(g, "HelixSR-Scaler.files"), "name=dxgi.dll\ndxgi.dll\n")
        self.eng.get_core_status = lambda: {"weightsBuilt": False}
        with self.assertRaises(RuntimeError):
            self.eng.install_helixsr(g, route_override="direct")
        self.assertEqual(self.calls(), [])  # nothing removed when the 1.8.1 install cannot go ahead

    def test_legacy_install_removes_helixsr3_first(self):
        self.make_release()
        g = self.make_game()
        write(os.path.join(g, "OptiScaler.ini"))
        write(os.path.join(g, "HelixSR-Scaler.files"), "name=dxgi.dll\ndxgi.dll\n")
        self.eng.get_core_status = lambda: {"weightsBuilt": True}

        class Stop(Exception):
            pass

        removed = []

        def fake_remove(game):
            removed.append(game["route"])
            raise Stop()

        self.eng.helixsr3_remove = fake_remove
        with self.assertRaises(Stop):
            self.eng.install_helixsr(g, route_override="direct")
        self.assertEqual(removed, ["scaler"])

    # --- download ---------------------------------------------------------------------------------------------------

    def make_zip(self, entries):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            for name, data, mode in entries:
                info = zipfile.ZipInfo(name)
                info.external_attr = (mode & 0xFFFF) << 16
                z.writestr(info, data)
        path = os.path.join(self.tmp, "release.zip")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        return path, hashlib.sha256(buf.getvalue()).hexdigest()

    def test_download_verifies_and_extracts(self):
        v = self.eng.HELIXSR3_VERSION
        path, sha = self.make_zip([
            (f"HelixSR-{v}/setup/helixsr_bridge.py", FAKE_BRIDGE, 0o644),
            (f"HelixSR-{v}/HelixSR/helixsr.dll", b"MZ HelixSR 3.2.0", 0o644),
            (f"HelixSR-{v}/helixsr-setup.sh", "#!/bin/sh\n", 0o644),
        ])
        url = "file://" + path
        with self.assertRaises(RuntimeError):
            self.eng.helixsr3_download(log=lambda m: None, url=url, sha256="0" * 64)
        self.assertFalse(self.eng.helixsr3_status()["downloaded"])
        dest = self.eng.helixsr3_download(log=lambda m: None, url=url, sha256=sha)
        self.assertEqual(dest, self.release)
        self.assertTrue(self.eng.helixsr3_status()["downloaded"])
        self.assertTrue(os.stat(os.path.join(dest, "helixsr-setup.sh")).st_mode & stat.S_IXUSR)
        self.assertFalse(os.path.exists(os.path.join(os.path.dirname(dest), f"HelixSR-{v}.zip.partial")))

    def test_download_rejects_path_traversal(self):
        path, sha = self.make_zip([("../evil.txt", "x", 0o644)])
        with self.assertRaises(RuntimeError):
            self.eng.helixsr3_download(log=lambda m: None, url="file://" + path, sha256=sha)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "HelixSR", "evil.txt")))

    # --- build ------------------------------------------------------------------------------------------------------

    @unittest.skipIf(os.name == "nt", "the fake setup is a shell script")
    def test_build_stops_before_the_setup_game_list(self):
        self.make_release(network=True)
        marker = os.path.join(self.tmp, "games-touched")
        write(os.path.join(self.release, "helixsr-setup.sh"),
              "#!/usr/bin/env bash\necho '[helixsr-setup] building'\necho \"args: $*\"\n"
              "echo '[helixsr-setup] looking for your games ...'\nsleep 20\ntouch " + marker + "\n")
        lines = []
        t0 = time.time()
        ok = self.eng.helixsr3_build(log=lines.append)
        self.assertLess(time.time() - t0, 10)
        self.assertTrue(ok)
        self.assertIn("args: --yes", lines)
        self.assertFalse(any("looking for your games" in l for l in lines))
        time.sleep(0.2)
        self.assertFalse(os.path.exists(marker))


if __name__ == "__main__":
    unittest.main()
