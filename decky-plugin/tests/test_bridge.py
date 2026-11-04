"""Tests for the Decky bridge against a fake Steam library.

Run from the repo root: python3 -m unittest discover -s decky-plugin/tests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PLUGIN = os.path.dirname(HERE)
REPO = os.path.dirname(PLUGIN)
ENGINE_SRC = os.path.join(REPO, "src", "linux", "helixsr_swapper_linux.py")
CORE_SRC = os.path.join(REPO, "helixsr_core")


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helixsr-decky-")
        self.home = os.path.join(self.tmp, "home")
        self.mods = os.path.join(self.tmp, "plugin", "py_modules")
        os.makedirs(self.mods)
        shutil.copy2(os.path.join(PLUGIN, "py_modules", "helixsr_bridge.py"), self.mods)
        shutil.copy2(ENGINE_SRC, os.path.join(self.mods, "helixsr_engine.py"))
        # Plugin-bundled core (only the DLLs the tests need, to keep it fast).
        core_ver = next(d for d in sorted(os.listdir(CORE_SRC)) if os.path.isfile(os.path.join(CORE_SRC, d, "amd_fidelityfx_dx12.dll")))
        self.bundle = os.path.join(self.tmp, "plugin", "helixsr_core")
        shutil.copytree(os.path.join(CORE_SRC, core_ver), os.path.join(self.bundle, core_ver),
                        ignore=shutil.ignore_patterns("amd-fsr", "setup"))
        self.core_ver = core_ver
        # Fake Steam library with one FSR 3.1 game and one DLSS game.
        steamapps = os.path.join(self.home, ".local", "share", "Steam", "steamapps")
        for appid, name, inst, dll in (
            ("1001", "Fake FSR Game", "FakeFSR", "amd_fidelityfx_dx12.dll"),
            ("1002", "Fake DLSS Game", "FakeDLSS", "nvngx_dlss.dll"),
        ):
            gdir = os.path.join(steamapps, "common", inst)
            os.makedirs(gdir)
            with open(os.path.join(gdir, inst + ".exe"), "wb") as f:
                f.write(b"MZ" + b"\0" * 4096)
            with open(os.path.join(gdir, dll), "wb") as f:
                f.write(b"MZ" + b"\0" * 1024)
            with open(os.path.join(steamapps, f"appmanifest_{appid}.acf"), "w") as f:
                f.write(f'"AppState"\n{{\n\t"appid"\t\t"{appid}"\n\t"name"\t\t"{name}"\n\t"installdir"\t\t"{inst}"\n}}\n')
        self.common = os.path.join(steamapps, "common")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def call(self, cmd, args=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith("XDG_")}
        env.update({
            "HOME": self.home,
            "HELIXSR_DECKY_SETTINGS": os.path.join(self.tmp, "settings"),
            "HELIXSR_DECKY_CORE_BUNDLE": self.bundle,
        })
        out = subprocess.run(
            [sys.executable, "-B", os.path.join(self.mods, "helixsr_bridge.py"), cmd, json.dumps(args or {})],
            capture_output=True, text=True, env=env, timeout=120,
        ).stdout
        mark = "@@HELIXSR_JSON@@"
        self.assertIn(mark, out, out)
        return json.loads(out[out.rfind(mark) + len(mark):].strip().splitlines()[0])

    def fake_network(self):
        core = self.call("status")["coreDir"]
        for n in ("helixsr_weights.bin", "helixsr_kernels.pak"):
            with open(os.path.join(core, n), "wb") as f:
                f.write(b"x" * 16)

    def test_status_uses_data_copy_of_bundled_core(self):
        # The bundled core is copied out of the plugin folder (Decky replaces that folder on every update,
        # which used to throw the built network away).
        st = self.call("status")
        self.assertTrue(st["coreExists"], st)
        self.assertEqual(st["coreSource"], "data")
        self.assertTrue(st["coreDir"].startswith(os.path.join(self.home, ".local", "share", "HelixSR", "core")))
        self.assertFalse(st["weightsBuilt"])
        caps = st["capabilities"]
        self.assertIn("dxgi.dll", caps["optiDlls"])
        self.assertIsInstance(caps["fsr4Variants"], list)

    def test_read_only_bundle_is_copied_to_data_folder(self):
        os.chmod(os.path.join(self.bundle, self.core_ver), 0o555)
        try:
            if os.access(os.path.join(self.bundle, self.core_ver), os.W_OK):
                self.skipTest("running as root, cannot make the bundle read-only")
            st = self.call("status")
            self.assertEqual(st["coreSource"], "data")
            self.assertTrue(st["coreDir"].startswith(os.path.join(self.home, ".local", "share", "HelixSR", "core")))
        finally:
            os.chmod(os.path.join(self.bundle, self.core_ver), 0o755)

    def test_list_and_find_games(self):
        data = self.call("list_games", {"refresh": True})
        names = [g["name"] for g in data["games"]]
        self.assertIn("Fake FSR Game", names)
        self.assertIn("Fake DLSS Game", names)
        for g in data["games"]:
            self.assertFalse(g["installed"])
        found = self.call("find_app", {"appId": "1002"})["game"]
        self.assertEqual(found["name"], "Fake DLSS Game")
        self.assertEqual(found["appId"], "1002")
        self.assertIsNone(self.call("find_app", {"appId": "999"})["game"])

    def write_manifest(self, appid, name, inst):
        steamapps = os.path.dirname(self.common)
        lines = ['"AppState"', "{", f'\t"appid"\t\t"{appid}"', f'\t"name"\t\t"{name}"', f'\t"installdir"\t\t"{inst}"', "}"]
        os.makedirs(os.path.join(self.common, inst), exist_ok=True)
        with open(os.path.join(steamapps, f"appmanifest_{appid}.acf"), "w") as f:
            f.write("\n".join(lines) + "\n")

    def test_native_linux_game_listed_as_unsupported_and_leftovers_hidden(self):
        elf = bytes([0x7F]) + b"ELF"
        native = os.path.join(self.common, "NativeGame")
        os.makedirs(native)
        exe = os.path.join(native, "NativeGame.x86_64")
        with open(exe, "wb") as f:
            # e_ident (16 bytes) then e_type = 2 (executable)
            f.write(elf + bytes([2, 1, 1]) + bytes(9) + bytes([2, 0]) + bytes(8192))
        os.chmod(exe, 0o755)
        with open(os.path.join(native, "UnityPlayer.so"), "wb") as f:
            f.write(elf + bytes(8192))
        os.makedirs(os.path.join(self.common, "Leftover", "DS"))
        self.write_manifest("1003", "Native Game", "NativeGame")
        self.write_manifest("1004", "Leftover", "Leftover")
        self.write_manifest("228980", "Steamworks Common Redistributables", "Steamworks Shared")
        games = {g["name"]: g for g in self.call("list_games", {"refresh": True})["games"]}
        self.assertIn("Native Game", games)
        self.assertEqual(games["Native Game"]["native"], "NativeGame.x86_64")
        self.assertFalse(games["Native Game"]["lite"]["eligible"])
        self.assertIn("Native Linux", games["Native Game"]["lite"]["reasons"][0])
        self.assertNotIn("Leftover", games)
        self.assertNotIn("Steamworks Common Redistributables", games)
        self.assertIsNone(games["Fake DLSS Game"]["native"])
        self.assertEqual(self.call("find_app", {"appId": "1003"})["game"]["name"], "Native Game")

    def test_install_needs_built_network(self):
        res = self.call("install", {"folder": os.path.join(self.common, "FakeDLSS"), "options": {"route": "optiscaler"}})
        self.assertFalse(res["success"])
        self.assertIn("compiled", res["error"])

    def test_install_and_uninstall_with_fake_network(self):
        self.fake_network()
        folder = os.path.join(self.common, "FakeDLSS")
        res = self.call("install", {"folder": folder, "options": {"route": "optiscaler", "optiDll": "winmm.dll"}})
        self.assertTrue(res.get("success"), res)
        g = res["game"]
        self.assertTrue(g["installed"])
        self.assertEqual(g["optiDllName"], "winmm.dll")
        self.assertIn("winmm=n,b", g["protonLaunchOptions"])
        self.assertTrue(os.path.isfile(os.path.join(folder, "winmm.dll")))
        cached = [x for x in self.call("list_games")["games"] if x["folder"] == g["folder"]][0]
        self.assertTrue(cached["installed"])
        res = self.call("uninstall", {"folder": folder})
        self.assertTrue(res.get("success"), res)
        self.assertFalse(res["game"]["installed"])
        self.assertFalse(os.path.isfile(os.path.join(folder, "winmm.dll")))

    def test_fsr4_lite_variant(self):
        caps = self.call("capabilities")
        ids = [v["id"] for v in caps["fsr4Variants"]]
        if "lite" not in ids:
            self.skipTest("engine has no FSR 4 variants")
        self.fake_network()
        folder = os.path.join(self.common, "FakeDLSS")
        res = self.call("install", {"folder": folder, "options": {"route": "optiscaler", "fsr4Variant": "lite"}})
        self.assertTrue(res.get("success"), res)
        self.assertEqual(res["game"]["fsr4Variant"], "lite")
        with open(os.path.join(folder, "OptiScaler.ini"), encoding="utf-8", errors="ignore") as f:
            self.assertRegex(f.read(), r"(?m)^Fsr4ForceEnableInt8\s*=\s*true")
        res = self.call("install", {"folder": folder, "options": {"route": "optiscaler", "fsr4Variant": "full"}})
        self.assertEqual(res["game"]["fsr4Variant"], "full")

    def test_settings_roundtrip_and_unknown_command(self):
        self.assertEqual(self.call("set_settings", {"settings": {"autoLaunchOptions": False}})["autoLaunchOptions"], False)
        self.assertEqual(self.call("get_settings")["autoLaunchOptions"], False)
        self.assertFalse(self.call("nope")["success"])

    def test_build_status_idle(self):
        st = self.call("build_status")
        self.assertEqual(st["state"], "idle")
        self.assertEqual(st["log"], [])


if __name__ == "__main__":
    unittest.main()
