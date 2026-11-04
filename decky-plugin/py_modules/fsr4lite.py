#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMD FSR 4.1.2 INT8 Lite for Proton games, through OptiScaler.

OptiScaler intercepts the game's own temporal upscaler (DLSS, XeSS or FSR 2/3), which hands it the
colour, depth, motion vectors and jitter of every frame, and runs AMD's driver FSR 4 provider on them.
FSR 4 needs those per-frame inputs: a finished frame (a Gamescope screenshot) cannot feed it.

What is pinned, and why
-----------------------
* OptiScaler 10.0.0-pre1, the build Decky OptiScaler v0.0.9 (n1ckmp3/decky-optiscaler) ships. It is the
  first OptiScaler with 4.1.2 model selection, and it reports itself as "10.0.0-dev (10911bcb)".
  Source: optiscaler/OptiScaler@b686ef4bc1e755185685b47a2da2d8095f5467ce ("Add FSR4 upscaling and FSR4FG
  support for Vulkan + 4.1.2 model selection"), the commit the v0.0.9 release names for its headers.
  In that source (OptiScaler/OptiTypes.h):
      enum class FSR4Support : uint8_t { None = 0, FP8 = 1, INT8 = 2, INT8_2 = 3, INT8Lite = 4 }
      enum class FSR4Model   : uint8_t { FP8 = 0, INT8 = 1, INT8_2 = 2, INT8Lite = 3 }
  so [FSR] Fsr4GpuSupport=4 and Fsr4Model=3 both mean "INT8 Lite". Config.cpp reads them with
  readEnum<FSR4Support>("FSR", "Fsr4GpuSupport") and readEnum<FSR4Model>("FSR", "Fsr4Model").
  fsr4/FSR4Models.cpp selects the model by hooking ffxProvider::IsSupported (vtable slot 2) of the
  classes it finds by RTTI name (ffxProvider_FSR4Lite_Int8 for Lite), so it adapts to the binary instead
  of using fixed offsets.
* AMD's driver FidelityFX libraries from the same payload, both AMD-signed, file version 2.4.0.4370:
  amdxcffx64.dll (DX12, used for DX12 and DX11 games through vkd3d-proton's amdxc64) and amdvkffx64.dll
  (Vulkan, used for Vulkan games). Both contain the provider version string "4.1.2" next to 4.0.0 and
  4.0.2, and the ffxProvider_FSR4Lite_Int8 class. check_providers() re-checks that on the device.

Nothing in here patches a DLL or uses fixed offsets. The Eglantine (Lichii) emulator reached the same
INT8 Lite model by patching four vtable slots at offsets that are only valid for one SDK 2.4.0
amd_fidelityfx_upscaler_vk.dll; OptiScaler finds the same IsSupported slots by RTTI in whatever provider
DLL it loads, which is the approach reused here.

A config value alone does not prove anything ran, so a game is only reported "active" after its
OptiScaler.log shows, from a launch after the install: the 4.1.2 driver provider, INT8 Lite reporting as
the supported model, and successful upscaler dispatches (with the render and display resolution).
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request
import zipfile

# ---------------------------------------------------------------------------
# Pinned runtime
# ---------------------------------------------------------------------------

OPTISCALER_VERSION = "10.0.0-pre1"
OPTISCALER_BUILD = "10.0.0-dev (10911bcb)"
OPTISCALER_SOURCE = "https://github.com/optiscaler/OptiScaler/tree/b686ef4bc1e755185685b47a2da2d8095f5467ce"

PAYLOAD_URL = "https://github.com/n1ckmp3/decky-optiscaler/releases/download/v0.0.9/Decky-OptiScaler-v0.0.9.zip"
PAYLOAD_SHA256 = "e10ceea1813919efe3693420c5025c91c58b4cd0f523e812d489edd40dc7cbac"
PAYLOAD_SIZE = 108050767
PAYLOAD_INNER = "Decky OptiScaler/bin/OptiScaler-10.0.0-pre1.7z"
PAYLOAD_INNER_SHA256 = "f75ece86c1235cbbec65093262ca998dc107dda8efccfef1270ebe6f44c22e6e"

# Files taken from the 7z (path inside it -> sha256). Everything is checked before it is used.
RUNTIME_FILES = {
    "OptiScaler.dll": "119c1f15f6e5945c2d33c52b750235ab1ccd0ee999fc4998f712bfc02902a7a9",
    "OptiScaler.ini": "585b917a8e4859c9eec8d3bd990183d0f8938a310d414ebe60f3ae2fcb6a1d00",
    "OptiScaler/amdxcffx64.dll": "c33a287f3048bf02311cae430b6a977500b94ca7b315cd7bff751e6b03e483e3",
    "OptiScaler/amdvkffx64.dll": "80e761f7c8c0ec8ead7b321df01911baaf917defae51388d29eaecb1d6bc58bd",
    "OptiScaler/amd_fidelityfx_loader_dx12.dll": "e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa",
    "OptiScaler/amd_fidelityfx_upscaler_dx12.dll": "d0dcccc74a43c44ba435b7a369b456e0970d8a4464e4bd683119b374f2c9fb46",
    "OptiScaler/amd_fidelityfx_vk.dll": "a1624cc4238fef046f30c4d80ce3f47be63fc5f5373f49e3ee9edb9960f54c78",
    "Licenses/FidelityFX_v2_LICENSE.md": "f0da09d71ad5c82759a179e774535d4a829e5c96c49294167c1152402b2cb400",
}
PROVIDERS = {"dx12": "OptiScaler/amdxcffx64.dll", "vulkan": "OptiScaler/amdvkffx64.dll"}
PROVIDER_VERSION = "4.1.2"
LITE_CLASS = b"ffxProvider_FSR4Lite_Int8"

# What gets copied into a game (runtime path -> path in the game's exe folder; the proxy is added at install).
GAME_FILES = [p for p in RUNTIME_FILES if p.startswith("OptiScaler/")] + ["Licenses/FidelityFX_v2_LICENSE.md"]
GAME_LICENSE_DEST = "OptiScaler/FidelityFX_v2_LICENSE.md"

PROXY_NAMES = ["dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "wininet.dll", "winhttp.dll"]
MANIFEST = "OptiScaler/helixsr-fsr4lite.json"
LOG_NAME = "OptiScaler.log"

# [section] key = value written into OptiScaler.ini
LITE_INI = {
    ("Upscalers", "Dx12Upscaler"): "ffx",
    ("Upscalers", "Dx11Upscaler"): "ffx_12",
    ("Upscalers", "VulkanUpscaler"): "ffx",
    ("FSR", "Fsr4GpuSupport"): "4",  # FSR4Support::INT8Lite
    ("FSR", "Fsr4Model"): "3",  # FSR4Model::INT8Lite
    ("FSR", "UpscalerIndex"): "0",
    ("FSR", "Fsr4EnableWatermark"): "false",
}
# Fallback: OptiScaler's built-in FSR 2.2 temporal upscaler. It needs no AMD DLL and no FSR 4 support,
# runs on any GPU and takes the same game inputs, so it works when the driver FSR 4 path does not.
FALLBACK_INI = {
    ("Upscalers", "Dx12Upscaler"): "fsr22",
    ("Upscalers", "Dx11Upscaler"): "fsr22",
    ("Upscalers", "VulkanUpscaler"): "fsr22",
    ("FSR", "Fsr4GpuSupport"): "auto",
    ("FSR", "Fsr4Model"): "auto",
    ("FSR", "UpscalerIndex"): "auto",
    ("FSR", "Fsr4EnableWatermark"): "false",
}
COMMON_INI = {
    ("Log", "LogToFile"): "true",
    ("Menu", "DisableSplash"): "true",
    ("Hotfix", "CheckForUpdate"): "false",
}
LOG_VERBOSE = "1"  # Debug: per-model support results and every dispatch, until a run is verified
LOG_NORMAL = "2"  # Info

ANTICHEAT_MARKERS = ("easyanticheat", "easyanticheat_eos", "battleye", "beservice", "eaclaunch.exe",
                     "start_protected_game.exe", "eaanticheat", "vgk.sys", "xigncode", "nprotect")

# ---------------------------------------------------------------------------
# Paths and small helpers
# ---------------------------------------------------------------------------


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def data_dir():
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(_home(), ".local", "share")
    return os.path.join(xdg, "HelixSR", "fsr4lite")


def runtime_dir():
    return os.path.join(data_dir(), f"OptiScaler-{OPTISCALER_VERSION}")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------


def device_info():
    """GPU vendor/device ids and CPU name. Lite is preferred on AMD GPUs (Steam Deck, Legion Go S, Ally...)."""
    gpus = []
    drm = "/sys/class/drm"
    try:
        for card in sorted(os.listdir(drm)):
            if not re.fullmatch(r"card\d+", card):
                continue
            dev = os.path.join(drm, card, "device")
            try:
                vendor = open(os.path.join(dev, "vendor")).read().strip().lower()
                device = open(os.path.join(dev, "device")).read().strip().lower()
            except Exception:
                continue
            gpus.append({"card": card, "vendor": vendor, "device": device})
    except Exception:
        pass
    cpu = ""
    try:
        for line in open("/proc/cpuinfo", encoding="utf-8", errors="ignore"):
            if line.lower().startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except Exception:
        pass
    amd = any(g["vendor"] == "0x1002" for g in gpus)
    return {"gpus": gpus, "cpu": cpu, "amdGpu": amd, "preferLite": amd}


# ---------------------------------------------------------------------------
# Runtime: download, verify, provider check
# ---------------------------------------------------------------------------


def _pe_version(data):
    """FileVersion from a PE's VS_FIXEDFILEINFO (signature 0xFEEF04BD)."""
    i = data.find(b"\xbd\x04\xef\xfe")
    if i < 0 or i + 16 > len(data):
        return None
    ms = int.from_bytes(data[i + 8:i + 12], "little")
    ls = int.from_bytes(data[i + 12:i + 16], "little")
    return f"{ms >> 16}.{ms & 0xFFFF}.{ls >> 16}.{ls & 0xFFFF}"


def check_providers(root=None):
    """Static check of the AMD driver providers: the 4.1.2 version string and the INT8 Lite provider class."""
    root = root or runtime_dir()
    out = {}
    for api, rel in PROVIDERS.items():
        path = os.path.join(root, rel)
        info = {"file": os.path.basename(rel), "present": os.path.isfile(path)}
        if info["present"]:
            with open(path, "rb") as f:
                data = f.read()
            versions = sorted(set(m.decode() for m in re.findall(rb"(?<![0-9.])4\.[0-9]\.[0-9](?=\x00)", data)))
            info.update({
                "fileVersion": _pe_version(data),
                "providerVersions": versions,
                "has412": PROVIDER_VERSION in versions,
                "hasLiteModel": LITE_CLASS in data,
                "sha256": hashlib.sha256(data).hexdigest(),
            })
            info["ok"] = info["has412"] and info["hasLiteModel"] and info["sha256"] == RUNTIME_FILES[rel]
        else:
            info["ok"] = False
        out[api] = info
    return out


def runtime_status():
    root = runtime_dir()
    state = _read_json(os.path.join(root, "runtime.json")) or {}
    missing = [p for p in RUNTIME_FILES if not os.path.isfile(os.path.join(root, p))]
    ready = not missing and state.get("verified") is True and state.get("version") == OPTISCALER_VERSION
    return {
        "ready": ready,
        "dir": root,
        "optiscaler": OPTISCALER_VERSION,
        "optiscalerBuild": OPTISCALER_BUILD,
        "source": OPTISCALER_SOURCE,
        "payloadUrl": PAYLOAD_URL,
        "payloadSize": PAYLOAD_SIZE,
        "providers": state.get("providers") or {},
        "verifiedAt": state.get("verifiedAt"),
        "missing": missing,
    }


def _download(url, dest, expected_sha, progress=None):
    h = hashlib.sha256()
    req = urllib.request.Request(url, headers={"User-Agent": "HelixSR-Manager-Decky"})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if h.hexdigest() != expected_sha:
        raise RuntimeError(f"Download checksum mismatch ({h.hexdigest()[:16]}...), not using it")


def _extract_7z(archive, dest):
    for tool in (["7z", "x", "-y", f"-o{dest}", archive], ["7za", "x", "-y", f"-o{dest}", archive],
                 ["bsdtar", "-xf", archive, "-C", dest]):
        exe = shutil.which(tool[0])
        if not exe:
            continue
        r = subprocess.run([exe] + tool[1:], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=600)
        if r.returncode == 0:
            return
    raise RuntimeError("Could not unpack the OptiScaler archive (needs 7z or bsdtar, both ship with SteamOS)")


def prepare_runtime(payload_path=None, progress=None):
    """Fetch the pinned payload (or use a local copy), verify every file and the providers, install it."""
    st = runtime_status()
    if st["ready"]:
        return st
    os.makedirs(data_dir(), exist_ok=True)
    work = tempfile.mkdtemp(prefix="fsr4lite-", dir=data_dir())
    try:
        zpath = payload_path
        if not zpath:
            zpath = os.path.join(work, "payload.zip")
            _download(PAYLOAD_URL, zpath, PAYLOAD_SHA256, progress)
        elif sha256_file(zpath) != PAYLOAD_SHA256:
            raise RuntimeError("The local payload does not match the pinned Decky OptiScaler v0.0.9 release")
        inner = os.path.join(work, "optiscaler.7z")
        with zipfile.ZipFile(zpath) as z, z.open(PAYLOAD_INNER) as src, open(inner, "wb") as dst:
            shutil.copyfileobj(src, dst, 1 << 20)
        if sha256_file(inner) != PAYLOAD_INNER_SHA256:
            raise RuntimeError("The OptiScaler archive inside the payload does not match the pinned build")
        unpacked = os.path.join(work, "x")
        os.makedirs(unpacked)
        _extract_7z(inner, unpacked)
        stage = os.path.join(work, "runtime")
        for rel, sha in RUNTIME_FILES.items():
            src = os.path.join(unpacked, rel)
            if not os.path.isfile(src) or sha256_file(src) != sha:
                raise RuntimeError(f"{rel} is missing or does not match the pinned build")
            dst = os.path.join(stage, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        providers = check_providers(stage)
        bad = [p["file"] for p in providers.values() if not p.get("ok")]
        if bad:
            raise RuntimeError(f"Provider check failed for {', '.join(bad)}: no 4.1.2 INT8 Lite provider found")
        _write_json(os.path.join(stage, "runtime.json"), {
            "version": OPTISCALER_VERSION,
            "build": OPTISCALER_BUILD,
            "source": OPTISCALER_SOURCE,
            "payload": PAYLOAD_URL,
            "payloadSha256": PAYLOAD_SHA256,
            "files": RUNTIME_FILES,
            "providers": providers,
            "verified": True,
            "verifiedAt": int(time.time()),
        })
        final = runtime_dir()
        if os.path.isdir(final):
            shutil.rmtree(final)
        os.replace(stage, final)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return runtime_status()


# ---------------------------------------------------------------------------
# INI editing (keeps comments, order and every other setting)
# ---------------------------------------------------------------------------


def set_ini_values(text, values):
    lines = text.splitlines()
    pending = dict(values)
    section = None
    out = []
    for line in lines:
        s = line.strip()
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            # Append keys this section is missing before leaving it.
            for (sec, key), val in list(pending.items()):
                if sec == section:
                    out.append(f"{key}={val}")
                    del pending[(sec, key)]
            section = m.group(1)
            out.append(line)
            continue
        if section and not s.startswith(";") and "=" in s:
            key = s.split("=", 1)[0].strip()
            if (section, key) in pending:
                out.append(f"{key}={pending.pop((section, key))}")
                continue
        out.append(line)
    for (sec, key), val in list(pending.items()):
        if sec == section:
            out.append(f"{key}={val}")
            del pending[(sec, key)]
    by_sec = {}
    for (sec, key), val in pending.items():
        by_sec.setdefault(sec, []).append(f"{key}={val}")
    for sec, kv in by_sec.items():
        out += ["", f"[{sec}]"] + kv
    return "\n".join(out) + "\n"


def get_ini_value(text, section, key):
    cur = None
    for line in text.splitlines():
        s = line.strip()
        m = re.fullmatch(r"\[([^\]]+)\]", s)
        if m:
            cur = m.group(1)
        elif cur == section and not s.startswith(";") and "=" in s and s.split("=", 1)[0].strip() == key:
            return s.split("=", 1)[1].split(";", 1)[0].strip()
    return None


# ---------------------------------------------------------------------------
# Per game
# ---------------------------------------------------------------------------


def _manifest(exe_folder):
    return _read_json(os.path.join(exe_folder, MANIFEST))


def find_anticheat(game_folder):
    hits = []
    for root, dirs, files in os.walk(game_folder):
        depth = root[len(game_folder):].count(os.sep)
        for n in dirs + files:
            if n.lower() in ANTICHEAT_MARKERS or n.lower().startswith("easyanticheat"):
                hits.append(os.path.relpath(os.path.join(root, n), game_folder))
        if depth >= 3:
            dirs[:] = []
        if len(hits) >= 3:
            break
    return hits


def _is_optiscaler_binary(path):
    try:
        with open(path, "rb") as f:
            data = f.read(64 << 20)
        return b"OptiScaler" in data
    except Exception:
        return False


def eligibility(game):
    """Can FSR 4 Lite go into this game? game is a scan result from the HelixSR engine."""
    reasons = []
    exe = game.get("exeName") or ""
    if not exe.lower().endswith(".exe"):
        reasons.append("No Windows game executable found (FSR 4 Lite is for Proton games)")
    ac = find_anticheat(game.get("folder") or game.get("exeFolder") or "")
    if ac:
        reasons.append(f"Anti-cheat found ({ac[0]}); injecting OptiScaler could get you banned")
    inputs = list(game.get("inputs") or [])
    if game.get("fsrTargets"):
        inputs.append("FSR 3")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "inputs": sorted(set(inputs)),
        # Without a DLSS/XeSS/FSR DLL in the folder the game may still have an upscaler (built in, or
        # Unreal's DLSS plugin elsewhere), so this is a hint, not a blocker.
        "inputsKnown": bool(inputs),
    }


def _pick_proxy(exe_folder, wanted):
    order = ([wanted] if wanted in PROXY_NAMES else []) + [p for p in PROXY_NAMES if p != wanted]
    for name in order:
        path = os.path.join(exe_folder, name)
        if not os.path.exists(path):
            return name
    return None


def _apply_ini(exe_folder, mode, verbose):
    ini_path = os.path.join(exe_folder, "OptiScaler.ini")
    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
        txt = f.read()
    values = dict(COMMON_INI)
    values.update(LITE_INI if mode == "lite" else FALLBACK_INI)
    values[("Log", "LogLevel")] = LOG_VERBOSE if verbose else LOG_NORMAL
    with open(ini_path + ".tmp", "w", encoding="utf-8", newline="\r\n") as f:
        f.write(set_ini_values(txt, values))
    os.replace(ini_path + ".tmp", ini_path)


def game_state(exe_folder):
    m = _manifest(exe_folder) if exe_folder else None
    if not m:
        return {"installed": False}
    st = {
        "installed": True,
        "mode": m.get("mode", "lite"),
        "proxy": m.get("proxy"),
        "installedAt": m.get("installedAt"),
        "optiscaler": m.get("optiscaler"),
        "verification": m.get("verification"),
        "fallbackReason": m.get("fallbackReason"),
        "launchOverride": (m.get("proxy") or "dxgi.dll").rsplit(".", 1)[0],
        "launchOptions": f'WINEDLLOVERRIDES="{(m.get("proxy") or "dxgi.dll").rsplit(".", 1)[0]}=n,b" %command%',
    }
    v = m.get("verification") or {}
    if st["mode"] == "fallback":
        st["label"] = "Fallback (FSR 2.2 built-in)"
    elif v.get("active"):
        st["label"] = "Active"
    else:
        st["label"] = "Enabled, not verified yet"
    return st


def install(game, proxy="dxgi.dll", mode="lite"):
    """Put OptiScaler + the driver providers into the game. Never overwrites a file it did not place."""
    if mode not in ("lite", "fallback"):
        raise ValueError("mode must be lite or fallback")
    rt = runtime_status()
    if not rt["ready"]:
        raise RuntimeError("Download the FSR 4 Lite runtime first")
    exe_folder = game.get("exeFolder")
    if not exe_folder or not os.path.isdir(exe_folder):
        raise RuntimeError("Game folder not found")
    el = eligibility(game)
    if not el["eligible"]:
        raise RuntimeError("; ".join(el["reasons"]))
    if game.get("installed"):
        raise RuntimeError("HelixSR is installed in this game. Uninstall it first (both use OptiScaler).")

    existing = _manifest(exe_folder)
    if existing:
        # Already ours: just switch the mode (and keep the proxy).
        set_mode(exe_folder, mode)
        return game_state(exe_folder)

    foreign = [n for n in ("OptiScaler.ini", "OptiScaler") if os.path.exists(os.path.join(exe_folder, n))]
    foreign += [n for n in PROXY_NAMES + ["OptiScaler.asi", "d3d12.dll"]
                if os.path.isfile(os.path.join(exe_folder, n)) and _is_optiscaler_binary(os.path.join(exe_folder, n))]
    if foreign:
        raise RuntimeError(
            f"Another OptiScaler install is in this game ({', '.join(sorted(set(foreign)))}). "
            "Remove it with the tool that installed it first; HelixSR will not overwrite it."
        )
    chosen = _pick_proxy(exe_folder, proxy)
    if not chosen:
        raise RuntimeError("Every OptiScaler proxy name is already taken by another mod in this game")

    root = rt["dir"]
    placed = []
    try:
        for rel in GAME_FILES:
            dest_rel = GAME_LICENSE_DEST if rel.startswith("Licenses/") else rel
            dst = os.path.join(exe_folder, dest_rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(root, rel), dst)
            placed.append(dest_rel)
        shutil.copy2(os.path.join(root, "OptiScaler.dll"), os.path.join(exe_folder, chosen))
        placed.append(chosen)
        shutil.copy2(os.path.join(root, "OptiScaler.ini"), os.path.join(exe_folder, "OptiScaler.ini"))
        placed.append("OptiScaler.ini")
        _apply_ini(exe_folder, mode, verbose=True)
        _write_json(os.path.join(exe_folder, MANIFEST), {
            "tool": "HelixSR Manager (Decky) FSR 4 Lite",
            "optiscaler": OPTISCALER_VERSION,
            "build": OPTISCALER_BUILD,
            "mode": mode,
            "proxy": chosen,
            "files": placed + [MANIFEST],
            "dirs": ["OptiScaler"],
            "hashes": {p: sha256_file(os.path.join(exe_folder, p)) for p in placed if p != "OptiScaler.ini"},
            "installedAt": int(time.time()),
            "verification": None,
        })
    except Exception:
        _remove_placed(exe_folder, placed + [MANIFEST], ["OptiScaler"])
        raise
    return game_state(exe_folder)


def _remove_placed(exe_folder, files, dirs):
    for rel in files + [LOG_NAME]:
        p = os.path.join(exe_folder, rel)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p)
        except Exception:
            pass
    for rel in dirs:
        p = os.path.join(exe_folder, rel)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)


def uninstall(exe_folder):
    """Remove everything install() placed. Files it did not place are left alone (none were overwritten)."""
    m = _manifest(exe_folder)
    if not m:
        return {"installed": False, "removed": []}
    files = [f for f in m.get("files", []) if f and not os.path.isabs(f) and ".." not in f.split("/")]
    dirs = [d for d in m.get("dirs", []) if d == "OptiScaler"]
    proxy = m.get("proxy")
    # The proxy is only removed if it is still the OptiScaler binary we put there.
    if proxy and proxy in files:
        p = os.path.join(exe_folder, proxy)
        if os.path.isfile(p) and m.get("hashes", {}).get(proxy) not in (None, sha256_file(p)):
            files.remove(proxy)
    _remove_placed(exe_folder, files, dirs)
    return {"installed": False, "removed": files + dirs}


def set_mode(exe_folder, mode, reason=None):
    m = _manifest(exe_folder)
    if not m:
        raise RuntimeError("FSR 4 Lite is not installed in this game")
    if mode not in ("lite", "fallback"):
        raise ValueError("mode must be lite or fallback")
    _apply_ini(exe_folder, mode, verbose=True)
    m["mode"] = mode
    m["fallbackReason"] = reason if mode == "fallback" else None
    m["verification"] = None
    m["modeChangedAt"] = int(time.time())
    _write_json(os.path.join(exe_folder, MANIFEST), m)
    return game_state(exe_folder)


# ---------------------------------------------------------------------------
# Verification from OptiScaler.log
# ---------------------------------------------------------------------------

RE_PROVIDER = re.compile(r"(amdxcffx64|amdvkffx64)\.dll provider for ([0-9A-Fa-f]+): ([^,]*?), id: ([0-9A-Fa-fx]+)")
RE_VK_DRIVER = re.compile(r"Using driver provided FSR ([0-9.]+)")
RE_MODEL_SUPPORT = re.compile(r"\b(FP8|INT8 RDNA2|INT8 Lite|INT8): (true|false)\b")
RE_VK_MODEL = re.compile(r"model: (FP8|INT8 RDNA2|INT8 Lite|INT8|None)")
RE_RES = re.compile(r"Render Resolution: (\d+)x(\d+), Display Resolution (\d+)x(\d+)")
RE_INPUT_RES = re.compile(r"Input Resolution: (\d+)x(\d+)")
RE_HOOKED_LITE = re.compile(r"Hooked the support check of ffxProvider_FSR4Lite_Int8 in (\S+)")
RE_DRIVER_CTX = re.compile(r"Created driver upscaler context, result: (\S+)")
RE_DISPATCH_ERR = re.compile(r"_dispatch error|Dispatch error|dispatch failed", re.IGNORECASE)
RE_GPU = re.compile(r"Upscaler support - fsr4: ([^,\n]+)")
RE_FEATURE = re.compile(r"(?:Creating (?:new )?(\S+(?: \S+)?) upscaler(?: feature)?|init successful for (.+?), upscaler changed)")


def parse_log(text):
    """Pulls what ran out of an OptiScaler log. Pure function, unit tested."""
    res = {"providers": [], "models": {}, "activeModel": None, "resolutions": [], "inputResolutions": [],
           "dispatches": 0, "dispatchErrors": 0, "liteHookedIn": None, "driverContext": None, "fsr4Gpu": None,
           "features": []}
    for line in text.splitlines():
        m = RE_PROVIDER.search(line)
        if m:
            res["providers"].append({"dll": m.group(1) + ".dll", "desc": m.group(2), "name": m.group(3).strip(),
                                     "id": m.group(4)})
            continue
        m = RE_VK_DRIVER.search(line)
        if m:
            res["providers"].append({"dll": "amdvkffx64.dll", "desc": "vk", "name": m.group(1), "id": None})
        m = RE_HOOKED_LITE.search(line)
        if m:
            res["liteHookedIn"] = m.group(1)
        m = RE_MODEL_SUPPORT.search(line)
        if m and ("ffxProvider" not in line):
            res["models"][m.group(1)] = m.group(2) == "true"
            if m.group(2) == "true":
                res["activeModel"] = m.group(1)
        m = RE_VK_MODEL.search(line)
        if m:
            res["activeModel"] = m.group(1)
        m = RE_RES.search(line)
        if m:
            r = [int(x) for x in m.groups()]
            if r not in res["resolutions"]:
                res["resolutions"].append(r)
        m = RE_INPUT_RES.search(line)
        if m:
            r = [int(x) for x in m.groups()]
            if r not in res["inputResolutions"]:
                res["inputResolutions"].append(r)
        m = RE_DRIVER_CTX.search(line)
        if m:
            res["driverContext"] = m.group(1)
        m = RE_GPU.search(line)
        if m and res["fsr4Gpu"] is None:
            res["fsr4Gpu"] = m.group(1).strip()
        m = RE_FEATURE.search(line)
        if m:
            res["features"].append((m.group(1) or m.group(2)).strip())
        if "Dispatch!!" in line:
            res["dispatches"] += 1
        elif RE_DISPATCH_ERR.search(line):
            res["dispatchErrors"] += 1
    return res


def judge(parsed, mode="lite"):
    """Decide what the log proves. Lite is 'active' only with provider 4.1.2 + INT8 Lite + real dispatches."""
    prov412 = [p for p in parsed["providers"] if PROVIDER_VERSION in p["name"]]
    checks = {
        "provider412": bool(prov412),
        "liteModel": parsed["activeModel"] == "INT8 Lite"
        and not any(v for k, v in parsed["models"].items() if k != "INT8 Lite"),
        "dispatched": parsed["dispatches"] > 0
        and (parsed["driverContext"] is None or "OK" in parsed["driverContext"].upper()),
        "noDispatchErrors": parsed["dispatchErrors"] == 0,
        "resolution": bool(parsed["resolutions"]),
    }
    res = parsed["resolutions"][-1] if parsed["resolutions"] else None
    verdict = {
        "checks": checks,
        "provider": prov412[0] if prov412 else (parsed["providers"][0] if parsed["providers"] else None),
        "model": parsed["activeModel"],
        "dispatches": parsed["dispatches"],
        "dispatchErrors": parsed["dispatchErrors"],
        "input": f"{res[0]}x{res[1]}" if res else None,
        "output": f"{res[2]}x{res[3]}" if res else None,
        "fsr4Gpu": parsed["fsr4Gpu"],
    }
    if mode == "lite":
        verdict["active"] = all(checks.values())
    else:
        verdict["active"] = False
        verdict["fallbackRunning"] = checks["dispatched"] and checks["noDispatchErrors"]
    missing = [k for k, v in checks.items() if not v]
    verdict["missing"] = missing
    return verdict


def verify(exe_folder):
    """Read the game's OptiScaler.log from a launch after install/mode change and record the result."""
    m = _manifest(exe_folder)
    if not m:
        raise RuntimeError("FSR 4 Lite is not installed in this game")
    log = os.path.join(exe_folder, LOG_NAME)
    since = max(m.get("installedAt") or 0, m.get("modeChangedAt") or 0)
    if not os.path.isfile(log):
        return {"state": "not-run", "message": "No OptiScaler log yet: start the game and use its upscaler (DLSS, XeSS or FSR)."}
    mtime = os.path.getmtime(log)
    if mtime < since:
        return {"state": "not-run", "message": "The log is older than the install: start the game once."}
    with open(log, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    parsed = parse_log(text)
    v = judge(parsed, m.get("mode", "lite"))
    prev = m.get("verification") or {}
    if (not v["active"] and prev.get("active") and m.get("mode", "lite") == "lite"
            and v["checks"]["provider412"] and v["checks"]["resolution"] and v["checks"]["noDispatchErrors"]):
        # After a verified run the log drops to Info level, which has no per-frame model/dispatch lines.
        # Keep the earlier proof as long as the new run still loads the 4.1.2 provider and creates the upscaler.
        v = dict(prev, recheckedAt=int(time.time()), recheck="info-level log: provider 4.1.2 and upscaler still created")
        v["input"], v["output"] = judge(parsed)["input"], judge(parsed)["output"]
    v["checkedAt"] = int(time.time())
    v["logTime"] = int(mtime)
    v["state"] = "active" if v["active"] else ("fallback" if m.get("mode") == "fallback" else "not-active")
    m["verification"] = v
    if v["active"]:
        # Verified once: stop the per-frame debug logging.
        _apply_ini(exe_folder, m.get("mode", "lite"), verbose=False)
    _write_json(os.path.join(exe_folder, MANIFEST), m)
    return v
