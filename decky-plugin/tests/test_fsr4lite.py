"""Tests for py_modules/fsr4lite.py (FSR 4 Lite through OptiScaler 10).

Run from the repo root: python3 -m unittest discover -s decky-plugin/tests
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "py_modules"))

import fsr4lite  # noqa: E402

INI = """; -------------------------------------------------------
[Upscalers]
; Select Upscaler for Dx12 games
Dx12Upscaler=auto

VulkanUpscaler=auto

[FSR]
; 0 = No override | 1 = FP8 | 2 = INT8 | 3 = INT8-2 | 4 = INT8 Lite
Fsr4GpuSupport=auto
Fsr4Model=auto
UpscalerIndex=auto

[Log]
LogLevel=auto
"""

# Lines in the shape OptiScaler 10.0.0-pre1 writes them (see fsr4/*.cpp and upscalers/IFeature.cpp).
LOG_LITE = """[2026-11-04 01:40:01.100] [info] amdxcffx64.dll loaded from game folder
[2026-11-04 01:40:01.200] [info] Hooked the support check of ffxProvider_FSR4Lite_Int8 in amdxcffx64.dll
[2026-11-04 01:40:01.210] [info] amdxcffx64.dll provider for 10000: FSR 4.1.2, id: 80001234, struct version: 2
[2026-11-04 01:40:02.000] [info] Creating FSR upscaler feature
[2026-11-04 01:40:02.001] [info] Render Resolution: 1280x720, Display Resolution 2560x1440, Quality: 1
[2026-11-04 01:40:02.100] [debug] FP8: false
[2026-11-04 01:40:02.101] [debug] INT8: false
[2026-11-04 01:40:02.102] [debug] INT8 RDNA2: false
[2026-11-04 01:40:02.103] [debug] INT8 Lite: true
[2026-11-04 01:40:02.200] [info] Created driver upscaler context, result: OK
[2026-11-04 01:40:02.300] [debug] Input Resolution: 1280x720
[2026-11-04 01:40:02.301] [debug] Dispatch!!
[2026-11-04 01:40:02.320] [debug] Input Resolution: 1280x720
[2026-11-04 01:40:02.321] [debug] Dispatch!!
"""


class IniTest(unittest.TestCase):
    def test_set_keeps_comments_and_adds_missing(self):
        out = fsr4lite.set_ini_values(INI, {
            ("FSR", "Fsr4GpuSupport"): "4", ("FSR", "Fsr4Model"): "3", ("Upscalers", "Dx12Upscaler"): "ffx",
            ("Menu", "DisableSplash"): "true", ("Log", "LogToFile"): "true",
        })
        self.assertIn("; 0 = No override | 1 = FP8 | 2 = INT8 | 3 = INT8-2 | 4 = INT8 Lite", out)
        self.assertEqual(fsr4lite.get_ini_value(out, "FSR", "Fsr4GpuSupport"), "4")
        self.assertEqual(fsr4lite.get_ini_value(out, "FSR", "Fsr4Model"), "3")
        self.assertEqual(fsr4lite.get_ini_value(out, "Upscalers", "Dx12Upscaler"), "ffx")
        self.assertEqual(fsr4lite.get_ini_value(out, "Upscalers", "VulkanUpscaler"), "auto")
        self.assertEqual(fsr4lite.get_ini_value(out, "Log", "LogToFile"), "true")
        self.assertEqual(fsr4lite.get_ini_value(out, "Menu", "DisableSplash"), "true")
        self.assertEqual(out.count("Fsr4GpuSupport="), 1)

    def test_lite_values_are_the_int8_lite_enums(self):
        # OptiTypes.h @ b686ef4: FSR4Support::INT8Lite = 4, FSR4Model::INT8Lite = 3
        self.assertEqual(fsr4lite.LITE_INI[("FSR", "Fsr4GpuSupport")], "4")
        self.assertEqual(fsr4lite.LITE_INI[("FSR", "Fsr4Model")], "3")


class LogTest(unittest.TestCase):
    def test_lite_run_is_active(self):
        v = fsr4lite.judge(fsr4lite.parse_log(LOG_LITE))
        self.assertTrue(v["active"], v)
        self.assertEqual(v["model"], "INT8 Lite")
        self.assertEqual(v["input"], "1280x720")
        self.assertEqual(v["output"], "2560x1440")
        self.assertIn("4.1.2", v["provider"]["name"])
        self.assertEqual(v["dispatches"], 2)

    def test_config_alone_is_not_active(self):
        v = fsr4lite.judge(fsr4lite.parse_log(LOG_LITE.split("[2026-11-04 01:40:02.000]")[0]))
        self.assertFalse(v["active"])
        self.assertIn("dispatched", v["missing"])
        self.assertIn("liteModel", v["missing"])

    def test_other_model_or_version_is_not_active(self):
        v = fsr4lite.judge(fsr4lite.parse_log(LOG_LITE.replace("INT8 Lite: true", "INT8 Lite: false")
                                              .replace("INT8: false", "INT8: true")))
        self.assertFalse(v["active"])
        v = fsr4lite.judge(fsr4lite.parse_log(LOG_LITE.replace("FSR 4.1.2", "FSR 4.0.2")))
        self.assertFalse(v["active"])
        self.assertIn("provider412", v["missing"])

    def test_dispatch_error_is_not_active(self):
        v = fsr4lite.judge(fsr4lite.parse_log(LOG_LITE + "[x] [error] _dispatch error: FFX_API_RETURN_ERROR\n"))
        self.assertFalse(v["active"])

    def test_real_handheld_log_lines(self):
        # Copied from over the hill (Unity 6, DX11 via dx11on12, Proton 11) on the Legion Go S, 2026-11-04.
        log = (
            "[07:49:45.450645] [I] NVSDK_NGX_D3D11_CreateFeature Creating new FSR 3.X w/Dx12 feature\n"
            "[07:49:45.450795] [I] IFeature::SetInitParameters Render Resolution: 1920x1200, "
            "Display Resolution 1920x1200, Quality: 2\n"
            "                          Upscaler support - fsr4: int8 lite (forced), dlss: false\n"
            "[07:49:46.012126] [I] FSR4Models::Hook Hooked the support check of ffxProvider_FSR4Lite_Int8 in amdxcffx64.dll\n"
            "[07:49:46.126927] [I] FSR4DriverDll::QueryProvider amdxcffx64.dll provider for 10000: 4.1.2 *, "
            "id: F5A5CA1E81001002, struct version: 2\n"
            "[07:49:46.134554] [D] `anonymous-namespace'::hkIsSupported INT8 Lite: true\n"
            "[07:49:46.177370] [I] FSR4DriverProviderDx12::CreateContext Created driver upscaler context, "
            "result: The operation was successful.\n"
            "[07:49:46.681971] [D] FFXFeatureDx12::EvaluateInternal Input Resolution: 1920x1200\n"
            "[07:49:46.682000] [D] FFXFeatureDx12::EvaluateInternal Dispatch!!\n"
        )
        p = fsr4lite.parse_log(log)
        self.assertEqual(p["driverContext"], "The operation was successful.")
        self.assertEqual(p["fsr4Gpu"], "int8 lite (forced)")
        v = fsr4lite.judge(p)
        self.assertTrue(v["active"], v)
        self.assertEqual((v["input"], v["output"]), ("1920x1200", "1920x1200"))
        failed = fsr4lite.judge(fsr4lite.parse_log(log.replace("The operation was successful.", "FFX_API_RETURN_ERROR")))
        self.assertFalse(failed["active"])
        self.assertIn("dispatched", failed["missing"])

    def test_vulkan_lines(self):
        log = ("[i] Using driver provided FSR 4.1.2\n"
               "[i] Render Resolution: 960x540, Display Resolution 1920x1080, Quality: 2\n"
               "[i] FSR 4 inputs, preExposure: 1, model: INT8 Lite, flags: 0, dispatch flags: 0\n"
               "[d] Dispatch!!\n")
        v = fsr4lite.judge(fsr4lite.parse_log(log))
        self.assertTrue(v["active"], v)
        self.assertEqual(v["provider"]["dll"], "amdvkffx64.dll")


class GameTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fsr4lite-")
        self.old_home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp
        os.environ.pop("XDG_DATA_HOME", None)
        # Fake runtime with the real layout (hashes are recorded at install, not compared to the pins here).
        rt = fsr4lite.runtime_dir()
        for rel in fsr4lite.RUNTIME_FILES:
            p = os.path.join(rt, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(INI if rel == "OptiScaler.ini" else ("OptiScaler build" if rel == "OptiScaler.dll" else rel))
        with open(os.path.join(rt, "runtime.json"), "w") as f:
            json.dump({"version": fsr4lite.OPTISCALER_VERSION, "verified": True}, f)
        self.game_dir = os.path.join(self.tmp, "Game")
        os.makedirs(os.path.join(self.game_dir, "Binaries"))
        self.exe_dir = os.path.join(self.game_dir, "Binaries")
        with open(os.path.join(self.exe_dir, "Game.exe"), "wb") as f:
            f.write(b"MZ")
        with open(os.path.join(self.exe_dir, "nvngx_dlss.dll"), "wb") as f:
            f.write(b"MZ")
        self.game = {"folder": self.game_dir, "exeFolder": self.exe_dir, "exeName": "Game.exe",
                     "inputs": ["DLSS"], "installed": False}

    def tearDown(self):
        if self.old_home is not None:
            os.environ["HOME"] = self.old_home
        shutil.rmtree(self.tmp, ignore_errors=True)

    def listing(self):
        out = []
        for root, _, files in os.walk(self.game_dir):
            out += [os.path.relpath(os.path.join(root, f), self.game_dir) for f in files]
        return sorted(out)

    def test_unity_game_without_exe_name_is_eligible_and_gets_dxgi_spoofing(self):
        # over the hill: the engine left exeName empty (UnityCrashHandler64.exe sits next to the game exe).
        for n in ("UnityCrashHandler64.exe", "over the hill.exe"):
            with open(os.path.join(self.exe_dir, n), "wb") as f:
                f.write(b"MZ")
        os.remove(os.path.join(self.exe_dir, "Game.exe"))
        game = dict(self.game, exeName=None, isUnity=True)
        self.assertEqual(fsr4lite.find_game_exe(self.exe_dir), "over the hill.exe")
        self.assertTrue(fsr4lite.eligibility(game)["eligible"])
        self.assertEqual(fsr4lite.game_extra_ini(game), [["Spoofing", "Dxgi", "true"]])
        self.assertEqual(fsr4lite.game_extra_ini(dict(game, isUnity=False)), [])
        fsr4lite.install(game, "dxgi.dll")
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), encoding="utf-8") as f:
            ini = f.read()
        self.assertEqual(fsr4lite.get_ini_value(ini, "Spoofing", "Dxgi"), "true")
        fsr4lite.set_mode(self.exe_dir, "fallback")
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), encoding="utf-8") as f:
            self.assertEqual(fsr4lite.get_ini_value(f.read(), "Spoofing", "Dxgi"), "true")

    def test_install_and_uninstall_restore_the_folder(self):
        before = self.listing()
        st = fsr4lite.install(self.game, "dxgi.dll")
        self.assertTrue(st["installed"])
        self.assertEqual(st["proxy"], "dxgi.dll")
        self.assertEqual(st["label"], "Enabled, not verified yet")
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), encoding="utf-8") as f:
            ini = f.read()
        self.assertEqual(fsr4lite.get_ini_value(ini, "FSR", "Fsr4GpuSupport"), "4")
        self.assertEqual(fsr4lite.get_ini_value(ini, "FSR", "Fsr4Model"), "3")
        self.assertEqual(fsr4lite.get_ini_value(ini, "Upscalers", "Dx12Upscaler"), "ffx")
        self.assertEqual(fsr4lite.get_ini_value(ini, "Log", "LogLevel"), fsr4lite.LOG_VERBOSE)
        self.assertTrue(os.path.isfile(os.path.join(self.exe_dir, "OptiScaler", "amdxcffx64.dll")))
        self.assertTrue(os.path.isfile(os.path.join(self.exe_dir, "OptiScaler", "amdvkffx64.dll")))
        with open(os.path.join(self.exe_dir, "OptiScaler.log"), "w") as f:
            f.write(LOG_LITE)
        fsr4lite.uninstall(self.exe_dir)
        self.assertEqual(self.listing(), before)

    def test_other_mods_are_never_overwritten(self):
        reshade = os.path.join(self.exe_dir, "dxgi.dll")
        with open(reshade, "wb") as f:
            f.write(b"ReShade")
        st = fsr4lite.install(self.game, "dxgi.dll")
        self.assertEqual(st["proxy"], "winmm.dll")
        fsr4lite.uninstall(self.exe_dir)
        with open(reshade, "rb") as f:
            self.assertEqual(f.read(), b"ReShade")
        self.assertFalse(os.path.exists(os.path.join(self.exe_dir, "winmm.dll")))

    def test_refuses_other_optiscaler_and_anticheat_and_helixsr(self):
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), "w") as f:
            f.write("[FSR]\n")
        with self.assertRaisesRegex(RuntimeError, "Another OptiScaler"):
            fsr4lite.install(self.game)
        os.remove(os.path.join(self.exe_dir, "OptiScaler.ini"))
        os.makedirs(os.path.join(self.game_dir, "EasyAntiCheat"))
        self.assertFalse(fsr4lite.eligibility(self.game)["eligible"])
        with self.assertRaisesRegex(RuntimeError, "Anti-cheat"):
            fsr4lite.install(self.game)
        shutil.rmtree(os.path.join(self.game_dir, "EasyAntiCheat"))
        with self.assertRaisesRegex(RuntimeError, "HelixSR is installed"):
            fsr4lite.install(dict(self.game, installed=True))

    def test_fallback_and_verify(self):
        fsr4lite.install(self.game)
        st = fsr4lite.set_mode(self.exe_dir, "fallback", "test")
        self.assertEqual(st["mode"], "fallback")
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), encoding="utf-8") as f:
            self.assertEqual(fsr4lite.get_ini_value(f.read(), "Upscalers", "Dx12Upscaler"), "fsr22")
        fsr4lite.set_mode(self.exe_dir, "lite")
        self.assertEqual(fsr4lite.verify(self.exe_dir)["state"], "not-run")
        with open(os.path.join(self.exe_dir, "OptiScaler.log"), "w") as f:
            f.write(LOG_LITE)
        v = fsr4lite.verify(self.exe_dir)
        self.assertTrue(v["active"], v)
        self.assertEqual(fsr4lite.game_state(self.exe_dir)["label"], "Active")
        with open(os.path.join(self.exe_dir, "OptiScaler.ini"), encoding="utf-8") as f:
            self.assertEqual(fsr4lite.get_ini_value(f.read(), "Log", "LogLevel"), fsr4lite.LOG_NORMAL)

    def test_provider_check_on_fake_runtime_fails(self):
        p = fsr4lite.check_providers()
        self.assertFalse(p["dx12"]["ok"])
        self.assertFalse(p["dx12"]["has412"])


if __name__ == "__main__":
    unittest.main()
