"""HelixSR 3 through the Decky bridge: capabilities, game fields and the install route.

Uses a fake HelixSR 3 release (with a stand-in for upstream's app bridge), never upstream's code.
Run from the repo root: python3 -m unittest discover -s decky-plugin/tests
"""

import json
import os
import unittest

import test_bridge

FAKE_UPSTREAM_BRIDGE = r'''
import json, os, sys
release, cmd, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
with open(os.path.join(release, "calls.jsonl"), "a") as f:
    f.write(json.dumps([cmd] + rest) + "\n")
print(json.dumps({"protocol": 1, "ok": True, "messages": []}))
'''


class HelixSR3BridgeTest(unittest.TestCase):
    # the fake Steam library and the bridge call of test_bridge (without running its tests again)
    setUp = test_bridge.BridgeTest.setUp
    tearDown = test_bridge.BridgeTest.tearDown
    call = test_bridge.BridgeTest.call

    def make_release(self):
        rel = os.path.join(self.home, ".local", "share", "HelixSR", "core", "HelixSR-3.2.0")
        files = {
            os.path.join("setup", "helixsr_bridge.py"): FAKE_UPSTREAM_BRIDGE.encode(),
            os.path.join("HelixSR", "helixsr.dll"): b"MZ\0HelixSR 3.2.0\0" + b"HXSRNET1" + b"\0" * 24,
            os.path.join("HLX-FSR4", "amd_fidelityfx_upscaler_dx12.dll"): b"MZ" + b"HLXFSR4D" + b"\0" * 16,
            os.path.join("helixsr-scaler", "OptiScaler.dll"): b"MZ",
        }
        for rel_path, data in files.items():
            p = os.path.join(rel, rel_path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data)
        return rel

    def test_capabilities_and_status(self):
        st = self.call("status")
        h3 = st["capabilities"]["helixsr3"]
        self.assertEqual(h3["routes"], ["scaler", "hlxfsr"])
        self.assertIn("dxgi.dll", h3["scalerDlls"])
        self.assertNotIn("OptiScaler.asi", h3["scalerDlls"])
        self.assertFalse(st["helixsr3"]["downloaded"])
        self.make_release()
        st = self.call("status")
        self.assertTrue(st["helixsr3"]["scalerReady"])
        self.assertTrue(st["helixsr3"]["dropinReady"])

    def test_games_say_whether_they_have_fsr31(self):
        games = {g["name"]: g for g in self.call("list_games", {"refresh": True})["games"]}
        self.assertTrue(games["Fake FSR Game"]["hasFsr31"])
        self.assertFalse(games["Fake DLSS Game"]["hasFsr31"])

    def test_install_scaler_route_reaches_upstream_bridge(self):
        rel = self.make_release()
        folder = os.path.join(self.common, "FakeDLSS")
        res = self.call("install", {"folder": folder, "options": {"route": "scaler", "optiDll": "version.dll"}})
        self.assertTrue(res.get("success"), res)
        with open(os.path.join(rel, "calls.jsonl")) as f:
            call = json.loads(f.read().splitlines()[-1])
        self.assertEqual(call[0], "install")
        self.assertIn("scaler", call)
        self.assertIn("version.dll", call)


if __name__ == "__main__":
    unittest.main()
