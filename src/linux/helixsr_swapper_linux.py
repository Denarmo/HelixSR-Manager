#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HelixSR Manager — Standalone Linux & SteamOS Native Desktop Application
"""

import base64
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import zipfile

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_DIR, "public")
if not os.path.isdir(PUBLIC_DIR):
    PUBLIC_DIR = os.path.abspath(os.path.join(APP_DIR, "..", "..", "public"))

APP_VERSION = "2.0.0"   # HelixSR Manager release
CORE_VERSION = "1.8.1"  # bundled upstream HelixSR core (helixsr_core/HelixSR-x.y.z)

CORE_DIR = os.path.join(APP_DIR, "helixsr_core", f"HelixSR-{CORE_VERSION}")
if not os.path.isdir(CORE_DIR):
    CORE_DIR = os.path.abspath(os.path.join(APP_DIR, "..", "..", "helixsr_core", f"HelixSR-{CORE_VERSION}"))

CONFIG_FILE = os.path.join(APP_DIR, "config.json")

DLL_FSR = "amd_fidelityfx_dx12.dll"
DLL_SR = "amd_fidelityfx_upscaler_dx12.dll"
OWN_DLL = "helixsr.dll"
OWN_SR_DLL = "helixsr_upscaler.dll"
NETWORK_FILES = ["helixsr_weights.bin", "helixsr_kernels.pak"]
HELIXSR_FOLDER = "HelixSR"
MARKER_FILE = "helixsr-install.json"
BACKUP_FOLDER = "backup"
OPTI_NAMES = ["dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "d3d12.dll", "wininet.dll", "winhttp.dll", "OptiScaler.asi"]
AMD_FSR_FILE = "amd_fidelityfx_upscaler_dx12.amd.dll"
AMD_FG_FILE = "amd_fidelityfx_framegeneration_dx12.dll"  # bundled in core/amd-fsr since HelixSR 1.8.0
MY_FSR_FOLDER = "my-fsr"
# Experimental route (HelixSR 1.8.1): HelixSR DLSS loader (dxgi.dll) + HelixSR as nvngx.dll next to the game's .exe
LOADER_FOLDER = "dlss-loader"
LOADER_DLL = "dxgi.dll"
NVNGX_CORE_DLL = "nvngx.dll"
EMBED_MAGIC = b"HXSRNET1"  # HelixSR 1.8+ appends the network to amd_fidelityfx_dx12.dll (one-file DLL)

MY_FSR_README = """Put an FSR upscaler DLL into this folder (for example FSR 4: amd_fidelityfx_upscaler_dx12.dll, any
file name) and start the game again. Only for this game.

In the game press Insert (OptiScaler's menu), then Upscaling tab > Upscalers > FFX Upscaler, and pick it there:
it is listed by its version, for example "FSR 4.1.1". HelixSR stays the default ("FSR HelixSR (3.1.5)").
FSR 4 is listed only if the DLL supports your GPU.

To go back: delete the DLL from this folder.
"""

SKIP_EXE_RE = re.compile(
    r"unins|setup|redist|crash|launcher|vc_?redist|dxsetup|easyanticheat|beservice|dotnet|helper|report|prereq|install|7z|ue4prereq|cefprocess|webhelper",
    re.IGNORECASE,
)

RE_TITLES = [
    "pragmata", "dragon's dogma 2", "dragons dogma 2", "dd2",
    "monster hunter wilds", "monster hunter rise", "mhwilds", "mhrise",
    "resident evil", "biohazard", "devil may cry 5", "dmc5", "street fighter 6", "sf6",
    "kunitsu-gami", "dead rising deluxe", "onimusha", "mega man star force"
]

BUILD_LOGS = []
IS_BUILDING = False
BUILD_LISTENERS = []
BUILD_LOCK = threading.Lock()


def read_embedded_network(dll_path):
    """HelixSR 1.8+: returns (weights_size, kernels_size) if the network is appended to the DLL, else None.
    Trailer (last 32 bytes): b"HXSRNET1" + u64 weights + u64 kernels + u64 reserved."""
    try:
        size = os.path.getsize(dll_path)
        if size < 32:
            return None
        with open(dll_path, "rb") as f:
            f.seek(size - 32)
            tail = f.read(32)
        if tail[:8] != EMBED_MAGIC:
            return None
        nw = int.from_bytes(tail[8:16], "little")
        nk = int.from_bytes(tail[16:24], "little")
        if nw <= 0 or nk <= 0 or nw + nk + 32 > size:
            return None
        return nw, nk
    except Exception:
        return None


def has_embedded_network(dll_path=None):
    return read_embedded_network(dll_path or os.path.join(CORE_DIR, DLL_FSR)) is not None


def core_has_separate_network_files():
    return all(os.path.isfile(os.path.join(CORE_DIR, f)) for f in NETWORK_FILES)


def sync_network_files(dest_dir):
    """Copy the legacy network files only when the core DLL does not carry the network itself;
    otherwise remove stale copies from older builds."""
    embedded = has_embedded_network()
    for f in NETWORK_FILES:
        src = os.path.join(CORE_DIR, f)
        dst = os.path.join(dest_dir, f)
        try:
            if not embedded and os.path.isfile(src):
                shutil.copy2(src, dst)
            elif embedded and os.path.isfile(dst):
                os.remove(dst)
        except Exception:
            pass


def file_contains_ascii(path, pattern, limit):
    try:
        with open(path, "rb") as f:
            data = f.read(limit)
        if isinstance(pattern, re.Pattern):
            return pattern.search(data) is not None
        return pattern.encode("ascii") in data
    except Exception:
        return False


HELIXSR_VERSION_RE = re.compile(rb"HelixSR \d+\.\d+\.\d+")


def is_helixsr_binary(path):
    return os.path.isfile(path) and file_contains_ascii(path, HELIXSR_VERSION_RE, 4 * 1024 * 1024)


def is_dlss_loader_binary(path):
    return os.path.isfile(path) and file_contains_ascii(path, "HelixSR DLSS loader", 1024 * 1024)


def dlss_loader_available():
    return os.path.isfile(os.path.join(CORE_DIR, LOADER_FOLDER, LOADER_DLL))


def update_marker_version(marker_path):
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["helixsr"] = CORE_VERSION
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def get_data_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "HelixSR")
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(xdg, "HelixSR")


def load_config():
    if os.path.isfile(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    data.setdefault("customFolders", [])
                    data.setdefault("lightTheme", False)
                    return data
        except Exception:
            pass
    return {"customFolders": [], "lightTheme": False}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def normalize_path(p):
    if not p:
        return ""
    sep = "\\" if os.name == "nt" else "/"
    cleaned = p.replace("/", sep).replace("\\", sep)
    try:
        return os.path.normpath(os.path.abspath(cleaned)).rstrip("/\\")
    except Exception:
        return os.path.normpath(cleaned).rstrip("/\\")


def canonical_key(p):
    norm = normalize_path(p)
    if not norm:
        return ""
    try:
        return os.path.normcase(os.path.realpath(norm)).rstrip("/\\")
    except Exception:
        return os.path.normcase(norm).rstrip("/\\")


def get_steam_roots():
    roots = []
    seen = set()
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
        "/run/media/mmcblk0p1",
        "C:\\Program Files (x86)\\Steam",
    ]
    # Check /run/media/<user>/* for SteamOS SD cards & external drives
    media_root = "/run/media"
    if os.path.isdir(media_root):
        try:
            for entry in os.listdir(media_root):
                p1 = os.path.join(media_root, entry)
                if os.path.isdir(p1):
                    candidates.append(p1)
                    try:
                        for sub in os.listdir(p1):
                            p2 = os.path.join(p1, sub)
                            if os.path.isdir(p2):
                                candidates.append(p2)
                    except Exception:
                        pass
        except Exception:
            pass

    for c in candidates:
        if os.path.isdir(c):
            real = normalize_path(os.path.realpath(c))
            key = canonical_key(real)
            if key and key not in seen:
                seen.add(key)
                roots.append(real)
    return roots



VDF_PATH_REGEX = re.compile(r'"path"\s+"([^"]+)"')

def get_steam_libraries():
    libs = []
    seen = set()
    for root in get_steam_roots():
        direct_common = normalize_path(os.path.join(root, "steamapps", "common"))
        if os.path.isdir(direct_common):
            key = canonical_key(direct_common)
            if key and key not in seen:
                seen.add(key)
                libs.append(direct_common)

        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        if os.path.isfile(vdf):
            try:
                with open(vdf, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                for m in VDF_PATH_REGEX.finditer(text):
                    p = normalize_path(m.group(1).replace("\\\\", "\\"))
                    common = normalize_path(os.path.join(p, "steamapps", "common"))
                    if os.path.isdir(common):
                        key = canonical_key(common)
                        if key and key not in seen:
                            seen.add(key)
                            libs.append(common)
            except Exception:
                pass
    return libs


def get_steam_manifests():
    manifests = {}
    for common in get_steam_libraries():
        steamapps = os.path.dirname(common)
        if not os.path.isdir(steamapps):
            continue
        try:
            for fname in os.listdir(steamapps):
                if fname.startswith("appmanifest_") and fname.endswith(".acf"):
                    fpath = os.path.join(steamapps, fname)
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        m_id = re.search(r'"appid"\s+"(\d+)"', content)
                        m_name = re.search(r'"name"\s+"([^"]+)"', content)
                        m_dir = re.search(r'"installdir"\s+"([^"]+)"', content)
                        if m_id and m_name and m_dir:
                            appid = m_id.group(1)
                            name = m_name.group(1)
                            inst_dir = m_dir.group(1)
                            manifests[inst_dir.lower()] = {
                                "appid": appid,
                                "name": name,
                                "installdir": inst_dir,
                                "libraryRoot": os.path.dirname(steamapps),
                            }
                    except Exception:
                        pass
        except Exception:
            pass
    return manifests


def find_steam_artwork(appid, kind="cover"):
    if not appid:
        return None
    for sroot in get_steam_roots():
        cache_dir = os.path.join(sroot, "appcache", "librarycache", str(appid))
        if kind == "cover":
            cands = [
                os.path.join(cache_dir, "library_600x900.jpg"),
                os.path.join(sroot, "appcache", "librarycache", f"{appid}_library_600x900.jpg"),
                os.path.join(cache_dir, "library_header.jpg"),
            ]
        else:
            cands = [
                os.path.join(cache_dir, "library_hero.jpg"),
                os.path.join(sroot, "appcache", "librarycache", f"{appid}_library_hero.jpg"),
            ]
        for c in cands:
            if os.path.isfile(c):
                return {"type": "local", "path": c}

    url = (
        f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg"
        if kind == "cover"
        else f"https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/{appid}/library_hero.jpg"
    )
    return {"type": "remote", "url": url}


def detect_re_engine(game_folder, game_name):
    if not game_folder or not os.path.isdir(game_folder):
        return False
    if os.path.isdir(os.path.join(game_folder, "_storage_")):
        return True
    try:
        for f in os.listdir(game_folder):
            if f.lower().startswith("re_chunk_") and f.lower().endswith(".pak"):
                return True
    except Exception:
        pass
    cfg = os.path.join(game_folder, "config.ini")
    if os.path.isfile(cfg):
        try:
            with open(cfg, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            if "[Render]" in txt and "Capability=DirectX12" in txt:
                return True
        except Exception:
            pass
    low_name = (game_name or os.path.basename(game_folder)).lower()
    for kw in RE_TITLES:
        if kw in low_name:
            return True
    return False


# inZOI (KRAFTON, Unreal Engine 5): project name "BlueClient", Steam AppId 2456740
INZOI_APPID = "2456740"
INZOI_SETTINGS_SECTION = "/Script/BlueClient.B1GameUserSettings"
INZOI_BACKUP_FILE = "GameUserSettings.helixsr-backup.json"
INZOI_SETTING_KEYS = ("DLSSValue", "DLSSG", "FSR3Value", "FSR3FI")


def detect_inzoi(game_folder, game_name, appid=None, exe_name=None):
    if appid and str(appid) == INZOI_APPID:
        return True
    if not game_folder or not os.path.isdir(game_folder):
        return False
    # 1. Unreal project folder "BlueClient" with its Win64 binaries
    if os.path.isdir(os.path.join(game_folder, "BlueClient", "Binaries", "Win64")):
        return True
    # 2. Shipping executable name
    low_exe = (exe_name or "").lower()
    if low_exe.startswith("blueclient") or low_exe.startswith("inzoi"):
        return True
    # 3. Title / folder name
    low_name = (game_name or os.path.basename(game_folder)).lower().replace(" ", "")
    return "inzoi" in low_name


# Unity engine profile: the player ships UnityPlayer.dll (Unity 2017.2+) and/or a "<exe>_Data" folder holding
# globalgamemanagers / data.unity3d next to the game's .exe.
UNITY_VERSION_RE = re.compile(r"(?<![\d.])((?:20\d\d|6\d{3}|5)\.\d{1,2}\.\d{1,3}[abfpx]\d{1,3})")
UNITY_DATA_MARKERS = ("globalgamemanagers", "data.unity3d", "mainData")


def _is_unity_data_folder(path):
    return os.path.isdir(path) and any(os.path.isfile(os.path.join(path, m)) for m in UNITY_DATA_MARKERS)


def _find_unity_data_folder(exe_dir, exe_name):
    if exe_name:
        named = os.path.join(exe_dir, os.path.splitext(exe_name)[0] + "_Data")
        if _is_unity_data_folder(named):
            return named
    try:
        for e in sorted(os.listdir(exe_dir)):
            full = os.path.join(exe_dir, e)
            if e.lower().endswith("_data") and _is_unity_data_folder(full):
                return full
    except Exception:
        pass
    return None


def read_unity_version(data_dir):
    """Engine version string from the header of the player's first serialized file / bundle
    (for example "2022.3.10f1" or "6000.0.23f1")."""
    for name in UNITY_DATA_MARKERS:
        path = os.path.join(data_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                head = f.read(4096)
            m = UNITY_VERSION_RE.search(head.decode("ascii", "replace"))
            if m:
                return m.group(1)
        except Exception:
            pass
    return None


def detect_unity_pipeline(data_dir, backend):
    """Render pipeline from the scripting assemblies the build lists (ScriptingAssemblies.json, Unity 2020.2+) or ships
    (Mono: Managed folder). None when it cannot be told (older IL2CPP builds)."""
    assemblies = None
    try:
        list_path = os.path.join(data_dir, "ScriptingAssemblies.json")
        if os.path.isfile(list_path):
            with open(list_path, "r", encoding="utf-8", errors="replace") as f:
                assemblies = f.read()
    except Exception:
        pass
    if assemblies is None and backend == "Mono":
        try:
            managed = os.path.join(data_dir, "Managed")
            if os.path.isdir(managed):
                assemblies = "\n".join(e for e in os.listdir(managed) if e.lower().endswith(".dll"))
        except Exception:
            pass
    if assemblies is None:
        return None
    low = assemblies.lower()
    if "unity.renderpipelines.highdefinition.runtime" in low:
        return "HDRP"
    if "unity.renderpipelines.universal.runtime" in low:
        return "URP"
    return "Built-in"


def format_unity_version(version):
    """"6000.0.23f1" -> "Unity 6", "6000.1.2f1" -> "Unity 6.1", "2022.3.10f1" -> "Unity 2022.3"."""
    if not version:
        return "Unity"
    parts = version.split(".")
    if len(parts) < 2 or not parts[0].isdigit():
        return "Unity " + version
    major = int(parts[0])
    if major >= 6000:
        unity = major // 1000
        return f"Unity {unity}" if parts[1] == "0" else f"Unity {unity}.{parts[1]}"
    return f"Unity {parts[0]}.{parts[1]}"


def detect_unity(exe_dir, exe_name):
    """Unity profile of a game folder, or None when the game is not a Unity game."""
    if not exe_dir or not os.path.isdir(exe_dir):
        return None
    data_dir = _find_unity_data_folder(exe_dir, exe_name)
    has_player = os.path.isfile(os.path.join(exe_dir, "UnityPlayer.dll"))
    if not has_player and data_dir is None:
        return None

    # Scripting backend: IL2CPP builds ship GameAssembly.dll, Mono builds ship <exe>_Data/Managed
    backend = None
    if os.path.isfile(os.path.join(exe_dir, "GameAssembly.dll")) or (data_dir and os.path.isdir(os.path.join(data_dir, "il2cpp_data"))):
        backend = "IL2CPP"
    elif data_dir and os.path.isfile(os.path.join(data_dir, "Managed", "Assembly-CSharp.dll")):
        backend = "Mono"

    version = read_unity_version(data_dir) if data_dir else None
    pipeline = detect_unity_pipeline(data_dir, backend) if data_dir else None
    # Unity's D3D12 player loads the Agility SDK from a "D3D12" folder next to the .exe
    has_d3d12 = os.path.isfile(os.path.join(exe_dir, "D3D12", "D3D12Core.dll"))
    has_bepinex = os.path.isdir(os.path.join(exe_dir, "BepInEx", "core"))

    parts = [format_unity_version(version)]
    if backend:
        parts.append(backend)
    if pipeline:
        parts.append(pipeline)
    if has_d3d12:
        parts.append("D3D12")
    return {
        "version": version,
        "backend": backend,
        "pipeline": pipeline,
        "hasD3D12": has_d3d12,
        "hasBepInEx": has_bepinex,
        "summary": " · ".join(parts),
    }


def get_inzoi_user_settings_path(game):
    """inZOI keeps its graphics options in %LOCALAPPDATA%\\BlueClient\\Saved\\Config\\Windows\\GameUserSettings.ini,
    which under Proton lives in the game's compatdata prefix."""
    rel = os.path.join("pfx", "drive_c", "users", "steamuser", "AppData", "Local",
                       "BlueClient", "Saved", "Config", "Windows", "GameUserSettings.ini")
    appid = str(game.get("appId") or INZOI_APPID)
    commons = []
    folder = game.get("folder")
    if folder:
        commons.append(os.path.dirname(folder.rstrip("/\\")))  # <library>/steamapps/common
    commons.extend(get_steam_libraries())
    for common in commons:
        cand = os.path.join(os.path.dirname(common), "compatdata", appid, rel)
        if os.path.isfile(cand):
            return cand
    if os.name == "nt":
        cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BlueClient", "Saved", "Config", "Windows", "GameUserSettings.ini")
        if os.path.isfile(cand):
            return cand
    return None


def apply_inzoi_optiscaler_ini(txt):
    """OptiScaler's documented Unreal Engine on AMD fixes (resource barriers against rainbow colors, forced auto
    exposure against crushed dark areas)."""
    txt = set_ini_value(txt, "AutoExposure", "true", "InitFlags")
    txt = set_ini_value(txt, "ColorResourceBarrier", "4", "Hotfix")
    txt = set_ini_value(txt, "MotionVectorResourceBarrier", "8", "Hotfix")
    return txt


def _find_ue_ini_section(text, section):
    # Section body runs from its header to the next header (or end of file)
    return re.search(rf"(?ms)^\[{re.escape(section)}\][ \t]*\r?\n(.*?)(?=^\[|\Z)", text)


def get_ue_ini_value(text, section, key):
    sec = _find_ue_ini_section(text, section)
    if not sec:
        return None
    m = re.search(rf"(?m)^{re.escape(key)}[ \t]*=[ \t]*([^\r\n]*?)[ \t]*\r?$", sec.group(1))
    return m.group(1) if m else None


def set_ue_ini_value(text, section, key, value):
    """Section-scoped "Key=Value" setter for Unreal Engine config files (no spaces around '=', unlike set_ini_value)."""
    line = f"{key}={value}"
    sec = _find_ue_ini_section(text, section)
    if not sec:
        sep = "" if not text or text.endswith("\n") else "\r\n"
        return text + sep + f"[{section}]\r\n{line}\r\n"
    body = sec.group(1)
    key_re = re.compile(rf"(?m)^{re.escape(key)}[ \t]*=[^\r\n]*")
    if key_re.search(body):
        new_body = key_re.sub(lambda _m: line, body, count=1)
    else:
        # Append after the section's last non-empty line
        trimmed = body.rstrip("\r\n")
        tail = body[len(trimmed):]
        new_body = (trimmed + "\r\n" if trimmed else "") + line + (tail or "\r\n")
    return text[:sec.start(1)] + new_body + text[sec.end(1):]


def remove_ue_ini_value(text, section, key):
    sec = _find_ue_ini_section(text, section)
    if not sec:
        return text
    new_body = re.sub(rf"(?m)^{re.escape(key)}[ \t]*=[^\r\n]*\r?\n?", "", sec.group(1))
    return text[:sec.start(1)] + new_body + text[sec.end(1):]


def apply_inzoi_user_settings(game):
    """Selects the in-game upscaler that feeds HelixSR: DLSS for the OptiScaler and DLSS loader routes, FSR 3 for the
    direct route. The game's own values are saved next to the file and put back by restore_inzoi_user_settings."""
    cfg_path = get_inzoi_user_settings_path(game)
    if not cfg_path:
        return  # the game writes it on first launch; install again afterwards to apply
    try:
        with open(cfg_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            text = f.read()
        backup_path = os.path.join(os.path.dirname(cfg_path), INZOI_BACKUP_FILE)
        if not os.path.isfile(backup_path):
            original = {k: get_ue_ini_value(text, INZOI_SETTINGS_SECTION, k) for k in INZOI_SETTING_KEYS}
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(original, f, indent=2)

        def current_int(key):
            try:
                return int(get_ue_ini_value(text, INZOI_SETTINGS_SECTION, key) or "0")
            except ValueError:
                return 0

        if game.get("route") == "direct":
            if current_int("FSR3Value") <= 0:
                text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "FSR3Value", "4")  # Quality
            text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "DLSSValue", "0")
            text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "DLSSG", "False")
        else:
            if current_int("DLSSValue") <= 0:
                text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "DLSSValue", "4")  # Quality
            text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "FSR3Value", "0")
            text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "FSR3FI", "False")
            # DLSS-G only when OptiScaler translates it (DLSS-G input modes); it does not work with the DLSS loader
            dlssg = game.get("route") == "optiscaler" and (game.get("fgMode") or "").startswith("dlssg_")
            text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, "DLSSG", "True" if dlssg else "False")

        with open(cfg_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
    except Exception:
        pass


def restore_inzoi_user_settings(game):
    cfg_path = get_inzoi_user_settings_path(game)
    if not cfg_path:
        return
    backup_path = os.path.join(os.path.dirname(cfg_path), INZOI_BACKUP_FILE)
    if not os.path.isfile(backup_path):
        return
    try:
        with open(backup_path, "r", encoding="utf-8") as f:
            original = json.load(f) or {}
        with open(cfg_path, "r", encoding="utf-8", errors="ignore", newline="") as f:
            text = f.read()
        for key in INZOI_SETTING_KEYS:
            val = original.get(key)
            if val is None:
                text = remove_ue_ini_value(text, INZOI_SETTINGS_SECTION, key)
            else:
                text = set_ue_ini_value(text, INZOI_SETTINGS_SECTION, key, str(val))
        with open(cfg_path, "w", encoding="utf-8", newline="") as f:
            f.write(text)
        os.remove(backup_path)
    except Exception:
        pass


def compute_proton_launch_option(route, opti_dll, install_reframework):
    dlls = []
    if route == "optiscaler":
        opti = opti_dll or "dxgi.dll"
        if opti.lower().endswith(".dll"):
            dlls.append(opti[:-4])
    elif route == "dlss":
        dlls.append(LOADER_DLL[:-4])
    if install_reframework:
        if "dinput8" not in dlls:
            dlls.append("dinput8")
    if not dlls:
        return ""
    joined = ",".join(dlls)
    return f'WINEDLLOVERRIDES="{joined}=n,b" %command%'


def scan_game(game_folder, fallback_name=None, manifests=None):
    game_folder = normalize_path(game_folder)
    folder_name = os.path.basename(game_folder.rstrip("/\\"))
    manifest = manifests.get(folder_name.lower()) if manifests else None
    name = manifest["name"] if manifest else (fallback_name or folder_name)
    appid = manifest["appid"] if manifest else None
    launcher = "Steam" if manifest else "Custom"

    detected_inputs = set()
    fsr_targets = []
    best_exe_dir = None
    best_exe_size = -1
    best_exe_name = None
    found_dlss_path = None
    found_ffx_fg_path = None
    found_xe_fg_path = None
    found_xe_ll_path = None
    has_dlss_g = False

    def walk_dir(curr_dir, depth):
        nonlocal best_exe_dir, best_exe_size, best_exe_name, found_dlss_path
        nonlocal found_ffx_fg_path, found_xe_fg_path, found_xe_ll_path, has_dlss_g
        if depth > 6 or not os.path.isdir(curr_dir):
            return
        try:
            entries = os.listdir(curr_dir)
        except Exception:
            return

        files = []
        subdirs = []
        for e in entries:
            full = os.path.join(curr_dir, e)
            if os.path.isfile(full):
                files.append(e)
            elif os.path.isdir(full) and e.lower() != HELIXSR_FOLDER.lower():
                subdirs.append(full)

        has_opti_marker = any(f.lower() == "optiscaler.ini" for f in files) or os.path.isfile(
            os.path.join(curr_dir, HELIXSR_FOLDER, MARKER_FILE)
        )
        if has_opti_marker:
            best_exe_dir = curr_dir
            best_exe_size = 10**15

        for fname in files:
            low = fname.lower()
            full = os.path.join(curr_dir, fname)
            if low == "nvngx_dlss.dll":
                detected_inputs.add("DLSS")
                found_dlss_path = full
            elif low in ("nvngx_dlssg.dll", "sl.dlss_g.dll"):
                detected_inputs.add("DLSS-G")
                has_dlss_g = True
            elif low == "libxess.dll":
                detected_inputs.add("XeSS")
            elif low == "libxess_fg.dll":
                found_xe_fg_path = full
            elif low == "libxell.dll":
                found_xe_ll_path = full
            elif low == "amd_fidelityfx_framegeneration_dx12.dll":
                found_ffx_fg_path = full
            elif low in ("ffx_fsr2_api_x64.dll", "ffx_fsr2_api_dx12_x64.dll"):
                detected_inputs.add("FSR 2")
            elif low in (DLL_SR.lower(), DLL_FSR.lower()):
                fsr_targets.append(full)

            if low.endswith(".exe") and not SKIP_EXE_RE.search(fname):
                try:
                    sz = os.path.getsize(full)
                    if low.endswith("-win64-shipping.exe"):
                        sz += 10**12
                    if not has_opti_marker and sz > best_exe_size:
                        best_exe_size = sz
                        best_exe_dir = curr_dir
                        best_exe_name = fname
                except Exception:
                    pass

        for d in subdirs:
            walk_dir(d, depth + 1)

    walk_dir(game_folder, 0)

    if best_exe_dir is None and found_dlss_path:
        best_exe_dir = os.path.dirname(found_dlss_path)
    if best_exe_dir and os.path.basename(best_exe_dir).lower() == "_storage_":
        best_exe_dir = game_folder

    exe_folder = best_exe_dir or game_folder
    is_re = detect_re_engine(game_folder, name)
    is_inzoi = detect_inzoi(game_folder, name, appid, best_exe_name)
    unity = detect_unity(exe_folder, best_exe_name)
    has_ref_file = os.path.isfile(os.path.join(exe_folder, "reframework_revision.txt")) or os.path.isfile(os.path.join(exe_folder, "dinput8.dll"))
    install_ref = is_re or has_ref_file

    opti_installed = False
    version = None
    opti_dll_name = "dxgi.dll"
    use_fakenvapi = True
    fg_mode = "auto"
    has_backups = False
    has_logs = False
    has_myfsr = False

    dlss_installed = False
    helix_dir = os.path.join(exe_folder, HELIXSR_FOLDER)
    marker_path = os.path.join(helix_dir, MARKER_FILE)
    if os.path.isfile(marker_path):
        opti_installed = True
        try:
            with open(marker_path, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            version = mdata.get("helixsr", CORE_VERSION)
            if mdata.get("optiscaler"):
                opti_dll_name = mdata["optiscaler"]
            if "fakenvapi" in mdata:
                use_fakenvapi = bool(mdata["fakenvapi"])
            if mdata.get("fg_mode"):
                fg_mode = mdata["fg_mode"]
            if mdata.get("route") == "dlss":
                dlss_installed = True
                opti_installed = False
        except Exception:
            version = CORE_VERSION

    backup_dir = os.path.join(helix_dir, BACKUP_FOLDER)
    if os.path.isdir(backup_dir) and len(os.listdir(backup_dir)) > 0:
        has_backups = True
    if any(os.path.isfile(p) for p in (
        os.path.join(helix_dir, "helixsr.log"),
        os.path.join(exe_folder, "OptiScaler.log"),
        os.path.join(exe_folder, "helixsr.log"),
        os.path.join(exe_folder, "helixsr_loader.log"),
    )):
        has_logs = True
    if os.path.isdir(os.path.join(helix_dir, MY_FSR_FOLDER)):
        has_myfsr = True

    direct_installed = False
    for target in fsr_targets:
        orig = os.path.splitext(target)[0] + ".original.dll"
        t_marker = os.path.join(os.path.dirname(target), MARKER_FILE)
        if os.path.isfile(orig) or os.path.isfile(t_marker):
            direct_installed = True
            has_backups = has_backups or os.path.isfile(orig)
            if os.path.isfile(t_marker):
                try:
                    with open(t_marker, "r", encoding="utf-8") as f:
                        mdata = json.load(f)
                    version = mdata.get("helixsr", CORE_VERSION)
                except Exception:
                    version = CORE_VERSION
            if os.path.isfile(os.path.join(os.path.dirname(target), "helixsr.log")):
                has_logs = True

    exe_marker = os.path.join(exe_folder, MARKER_FILE)
    if not direct_installed and os.path.isfile(exe_marker):
        direct_installed = True
        try:
            with open(exe_marker, "r", encoding="utf-8") as f:
                mdata = json.load(f)
            version = mdata.get("helixsr", CORE_VERSION)
        except Exception:
            version = CORE_VERSION

    if dlss_installed:
        route = "dlss"
        installed = True
    elif opti_installed:
        route = "optiscaler"
        installed = True
    elif direct_installed:
        route = "direct"
        installed = True
    else:
        # Default option is OptiScaler (dxgi.dll) instead of direct FSR replacement
        route = "optiscaler"
        opti_dll_name = "dxgi.dll"
        installed = False

    fg_tag = ""
    if route == "optiscaler" and fg_mode != "auto":
        fg_map = {
            "dlssg_xefg": " + XeFG",
            "dlssg_fsrfg": " + FSR-FG",
            "dlssg_nukems": " + NukemFG",
            "optifg_fsrfg": " + OptiFG",
        }
        fg_tag = fg_map.get(fg_mode, "")

    if route == "optiscaler":
        route_display = f"OptiScaler ({opti_dll_name}{fg_tag})"
    elif route == "direct":
        route_display = "Direct (FSR 3.1)"
    elif route == "dlss":
        route_display = "DLSS Loader (Experimental)"
    else:
        route_display = "Unsupported"

    return {
        "id": base64.b64encode(game_folder.encode("utf-8")).decode("ascii").rstrip("="),
        "name": name,
        "folder": game_folder,
        "exeFolder": exe_folder,
        "exeName": best_exe_name,
        "appId": appid,
        "launcher": launcher,
        "route": route,
        "routeDisplay": route_display,
        "optiDllName": opti_dll_name,
        "useFakeNvapi": use_fakenvapi,
        "fgMode": fg_mode,
        "hasDlssG": has_dlss_g,
        "foundFfxFgPath": found_ffx_fg_path,
        "foundXeFgPath": found_xe_fg_path,
        "foundXeLlPath": found_xe_ll_path,
        "isReEngine": is_re,
        "isInZoi": is_inzoi,
        "isUnity": unity is not None,
        "unity": unity,
        "installReFramework": install_ref,
        "installed": installed,
        "version": version,
        "inputs": sorted(list(detected_inputs)),
        "fsrTargets": fsr_targets,
        "hasBackups": has_backups,
        "hasLogs": has_logs,
        "hasMyFsr": has_myfsr,
        "foundNvngxDlssPath": found_dlss_path,
        "cover": find_steam_artwork(appid, "cover"),
        "hero": find_steam_artwork(appid, "hero"),
        "protonLaunchOptions": compute_proton_launch_option(route, opti_dll_name, install_ref),
    }


def scan_all_games():
    cfg = load_config()
    manifests = get_steam_manifests()
    libs = get_steam_libraries()
    results = []
    scanned = set()

    for lib in libs:
        norm_lib = normalize_path(lib)
        if not norm_lib or not os.path.isdir(norm_lib):
            continue
        try:
            for entry in os.listdir(norm_lib):
                full = normalize_path(os.path.join(norm_lib, entry))
                if os.path.isdir(full):
                    key = canonical_key(full)
                    if key and key not in scanned:
                        scanned.add(key)
                        g = scan_game(full, entry, manifests)
                        if g.get("exeFolder"):
                            scanned.add(canonical_key(g["exeFolder"]))
                        if g["route"]:
                            results.append(g)
        except Exception:
            pass

    for cfolder in cfg.get("customFolders", []):
        norm_cf = normalize_path(cfolder)
        if norm_cf and os.path.isdir(norm_cf):
            key = canonical_key(norm_cf)
            if key and key not in scanned:
                scanned.add(key)
                g = scan_game(norm_cf, os.path.basename(norm_cf.rstrip("/\\")), manifests)
                exe_key = canonical_key(g.get("exeFolder") or "")
                if exe_key and exe_key != key:
                    if exe_key in scanned:
                        continue
                    scanned.add(exe_key)
                if g["route"]:
                    results.append(g)

    results.sort(key=lambda x: x["name"].lower())
    return results


def get_core_status():
    core_exists = os.path.isdir(CORE_DIR)
    w_path = os.path.join(CORE_DIR, "helixsr_weights.bin")
    k_path = os.path.join(CORE_DIR, "helixsr_kernels.pak")
    dll_path = os.path.join(CORE_DIR, DLL_FSR)
    w_built = os.path.isfile(w_path) and os.path.getsize(w_path) > 0
    k_built = os.path.isfile(k_path) and os.path.getsize(k_path) > 0
    embedded = read_embedded_network(dll_path)
    w_size = embedded[0] if embedded else (os.path.getsize(w_path) if w_built else 0)
    k_size = embedded[1] if embedded else (os.path.getsize(k_path) if k_built else 0)

    data_dir = get_data_dir()
    if os.name == "nt":
        has_py = os.path.isfile(os.path.join(data_dir, "python", "python.exe"))
        has_dxc = os.path.isfile(os.path.join(data_dir, "dxc", "dxc.exe"))
    else:
        has_py = shutil.which("python3") is not None or os.path.isfile(os.path.join(data_dir, "python", "bin", "python3"))
        has_dxc = os.path.isfile(os.path.join(data_dir, "dxc-win", "bin", "x64", "dxc.exe"))

    return {
        "version": CORE_VERSION,
        "appVersion": APP_VERSION,
        "platform": platform.system(),
        "coreDir": CORE_DIR,
        "coreExists": core_exists,
        "weightsBuilt": embedded is not None or (w_built and k_built),
        "networkEmbedded": embedded is not None,
        "weightsSize": w_size,
        "kernelsSize": k_size,
        "dllSize": os.path.getsize(dll_path) if os.path.isfile(dll_path) else 0,
        "dlssLoaderAvailable": dlss_loader_available(),
        "hasPython": has_py,
        "hasDxc": has_dxc,
    }


def set_ini_value(text, key, value, section):
    pattern = re.compile(rf"(?m)^({re.escape(key)})[ \t]*=[ \t]*([^\r\n]*?)[ \t]*(?=\r?$)")
    if pattern.search(text):
        return pattern.sub(lambda _m: f"{key} = {value}", text, count=1)
    if section:
        sec_re = re.compile(rf"(?m)^\[{re.escape(section)}\][ \t]*(\r?\n)")
        m = sec_re.search(text)
        if m:
            idx = m.end()
            return text[:idx] + f"{key} = {value}\n" + text[idx:]
        return text + f"\n[{section}]\n{key} = {value}\n"
    return text + f"\n{key} = {value}\n"


def clear_shader_cache(game):
    cleared = False
    folders = set()
    if game.get("folder") and os.path.isdir(game["folder"]):
        folders.add(game["folder"])
    if game.get("exeFolder") and os.path.isdir(game["exeFolder"]):
        folders.add(game["exeFolder"])

    for d in list(folders):
        sub_storage = os.path.join(d, "_storage_")
        if os.path.isdir(sub_storage):
            folders.add(sub_storage)

    for d in folders:
        for cname in ("shader.cache2", "piplinelist.bin"):
            p = os.path.join(d, cname)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                    cleared = True
                except Exception:
                    pass
        try:
            for f in os.listdir(d):
                low = f.lower()
                if (low.endswith(".bin") or low.endswith(".cache2")) and ("shader" in low or "pipeline" in low):
                    try:
                        os.remove(os.path.join(d, f))
                        cleared = True
                    except Exception:
                        pass
        except Exception:
            pass

    # Also clear SteamOS / Linux Proton shadercache/<appid> if present
    appid = game.get("appId")
    if appid:
        for sroot in get_steam_roots():
            sc_dir = os.path.join(sroot, "steamapps", "shadercache", str(appid))
            if os.path.isdir(sc_dir):
                for sub in ("DXVK_state_cache", "fozpipelinesv6", "nvidiacache"):
                    sp = os.path.join(sc_dir, sub)
                    if os.path.isdir(sp):
                        try:
                            shutil.rmtree(sp, ignore_errors=True)
                            cleared = True
                        except Exception:
                            pass
    return cleared


def sanitize_game_config(game):
    root = game.get("folder")
    if not root or not os.path.isdir(root):
        return
    cfg_path = os.path.join(root, "config.ini")
    if os.path.isfile(cfg_path):
        try:
            with open(cfg_path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
            text = re.sub(r"(?m)^\[Render/Adapter\][\r\n]+(?:[A-Za-z0-9_]+=[^\r\n]*[\r\n]+)*", "", text)
            text = re.sub(r"(?m)^DLSSReflexLowLatency=[^\r\n]*", "DLSSReflexLowLatency=OFF", text)
            text = re.sub(r"(?m)^FrameGeneration=[^\r\n]*", "FrameGeneration=OFF", text)
            if re.search(r"(?m)^UpscalingAlgorithm=", text):
                text = re.sub(r"(?m)^UpscalingAlgorithm=[^\r\n]*", "UpscalingAlgorithm=FSR3", text)
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass


def install_reframework_nightly(game):
    root = game.get("exeFolder") or game.get("folder")
    if not root or not os.path.isdir(root):
        return

    cache_dir = os.path.join(get_data_dir(), "cache", "reframework")
    os.makedirs(cache_dir, exist_ok=True)
    cached_dll = os.path.join(cache_dir, "dinput8.dll")
    cached_rev = os.path.join(cache_dir, "reframework_revision.txt")
    zip_path = os.path.join(cache_dir, "REFramework.zip")

    downloaded = False
    try:
        url = "https://github.com/praydog/REFramework-nightly/releases/latest/download/REFramework.zip"
        req = urllib.request.Request(url, headers={"User-Agent": f"HelixSR-Manager/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=20) as resp, open(zip_path, "wb") as out:
            shutil.copyfileobj(resp, out)

        if os.path.isfile(zip_path) and os.path.getsize(zip_path) > 100000:
            with zipfile.ZipFile(zip_path, "r") as zf:
                for member in zf.namelist():
                    bname = os.path.basename(member)
                    if bname.lower() == "dinput8.dll":
                        with open(cached_dll, "wb") as f:
                            f.write(zf.read(member))
                        downloaded = True
                    elif bname.lower() == "reframework_revision.txt":
                        with open(cached_rev, "wb") as f:
                            f.write(zf.read(member))
    except Exception:
        pass
    finally:
        if os.path.isfile(zip_path):
            try:
                os.remove(zip_path)
            except Exception:
                pass

    if not downloaded and not os.path.isfile(cached_dll):
        return

    targets = [root]
    sub_storage = os.path.join(root, "_storage_")
    if os.path.isdir(sub_storage):
        targets.append(sub_storage)

    for d in targets:
        shutil.copy2(cached_dll, os.path.join(d, "dinput8.dll"))
        if os.path.isfile(cached_rev):
            try:
                shutil.copy2(cached_rev, os.path.join(d, "reframework_revision.txt"))
            except Exception:
                pass


def uninstall_reframework(game):
    dirs = set()
    for k in ("folder", "exeFolder"):
        if game.get(k) and os.path.isdir(game[k]):
            dirs.add(game[k])
    sub_storage = os.path.join(game.get("exeFolder") or game.get("folder", ""), "_storage_")
    if os.path.isdir(sub_storage):
        dirs.add(sub_storage)

    ref_files = [
        "dinput8.dll", "reframework_revision.txt", "re2_framework_log.txt",
        "re2_fw_config.txt", "reframework_crash.dmp", "reframework_accessed_files.txt",
        "reframework_faulty_files.txt", "reframework_loose_files.txt", "ref_ui.ini"
    ]
    for d in dirs:
        for fname in ref_files:
            p = os.path.join(d, fname)
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except Exception:
                    pass
        ref_sub = os.path.join(d, "reframework")
        if os.path.isdir(ref_sub):
            shutil.rmtree(ref_sub, ignore_errors=True)


def cleanup_helixsr_files(game):
    # inZOI: put back the game's own upscaler settings (install applies them again)
    if game.get("isInZoi"):
        restore_inzoi_user_settings(game)

    exe_dir = game.get("exeFolder") or game.get("folder")
    if exe_dir and os.path.isdir(exe_dir):
        helix_dir = os.path.join(exe_dir, HELIXSR_FOLDER)
        marker_path = os.path.join(helix_dir, MARKER_FILE)
        backup_dir = os.path.join(helix_dir, BACKUP_FOLDER)

        if os.path.isfile(marker_path) or os.path.isdir(helix_dir):
            opti = "dxgi.dll"
            route = ""
            moved = []
            created = []
            ini_mode = ""
            if os.path.isfile(marker_path):
                try:
                    with open(marker_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    opti = data.get("optiscaler", "dxgi.dll")
                    route = data.get("route", "") or ""
                    ini_mode = data.get("ini", "")
                    moved = data.get("moved", [])
                    created = data.get("created", [])
                except Exception:
                    pass

            if route == "dlss":
                # Experimental DLSS loader route: dxgi.dll (loader) + nvngx.dll (HelixSR) next to the .exe
                opti = LOADER_DLL
                core_copy = os.path.join(exe_dir, NVNGX_CORE_DLL)
                if is_helixsr_binary(core_copy):
                    try:
                        os.remove(core_copy)
                    except Exception:
                        pass
                for extra in ["helixsr.log", "helixsr_loader.log"] + NETWORK_FILES:
                    ep = os.path.join(exe_dir, extra)
                    if os.path.isfile(ep):
                        try:
                            os.remove(ep)
                        except Exception:
                            pass

            opti_file = os.path.join(exe_dir, opti)
            if os.path.isfile(opti_file) and (route != "dlss" or is_dlss_loader_binary(opti_file)):
                try:
                    os.remove(opti_file)
                except Exception:
                    pass

            game_ini = os.path.join(exe_dir, "OptiScaler.ini")
            b_ini = os.path.join(backup_dir, "OptiScaler.ini")
            if ini_mode == "created":
                for f in (game_ini, os.path.join(exe_dir, "OptiScaler.log")):
                    if os.path.isfile(f):
                        try:
                            os.remove(f)
                        except Exception:
                            pass
            elif os.path.isfile(b_ini):
                try:
                    shutil.copy2(b_ini, game_ini)
                except Exception:
                    pass

            for c in created:
                cp = os.path.join(exe_dir, c)
                if os.path.isfile(cp):
                    try:
                        os.remove(cp)
                    except Exception:
                        pass

            for m in moved:
                bp = os.path.join(backup_dir, m)
                orig = os.path.join(exe_dir, m)
                if os.path.isfile(bp):
                    try:
                        shutil.copy2(bp, orig)
                    except Exception:
                        pass

            if os.path.isdir(helix_dir):
                shutil.rmtree(helix_dir, ignore_errors=True)

            sub_storage = os.path.join(exe_dir, "_storage_", HELIXSR_FOLDER)
            if os.path.isdir(sub_storage):
                shutil.rmtree(sub_storage, ignore_errors=True)

    for target in game.get("fsrTargets", []):
        orig = os.path.splitext(target)[0] + ".original.dll"
        if os.path.isfile(orig):
            if os.path.isfile(target):
                try:
                    os.remove(target)
                except Exception:
                    pass
            try:
                os.replace(orig, target)
            except Exception:
                pass
        tdir = os.path.dirname(target)
        for net in NETWORK_FILES + [MARKER_FILE, "helixsr.log"]:
            np = os.path.join(tdir, net)
            if os.path.isfile(np):
                try:
                    os.remove(np)
                except Exception:
                    pass

    if exe_dir and os.path.isdir(exe_dir):
        exe_marker = os.path.join(exe_dir, MARKER_FILE)
        if os.path.isfile(exe_marker):
            try:
                with open(exe_marker, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for c in data.get("created_dlls", []):
                    cp = os.path.join(exe_dir, c)
                    if os.path.isfile(cp):
                        os.remove(cp)
            except Exception:
                pass
            for dll_name in (DLL_SR, DLL_FSR):
                dst = os.path.join(exe_dir, dll_name)
                orig = os.path.splitext(dst)[0] + ".original.dll"
                if os.path.isfile(orig):
                    try:
                        os.replace(orig, dst)
                    except Exception:
                        pass
            for net in NETWORK_FILES + [MARKER_FILE, "helixsr.log"]:
                np = os.path.join(exe_dir, net)
                if os.path.isfile(np):
                    try:
                        os.remove(np)
                    except Exception:
                        pass


def install_helixsr(game_folder, route_override=None, opti_dll=None, use_fakenvapi=None, install_ref=None, fg_mode=None):
    st = get_core_status()
    if not st["weightsBuilt"]:
        raise RuntimeError(
            "HelixSR network weights & kernels have not been compiled yet. Please go to 'Engine & Weights' and click 'Build HelixSR Network'."
        )

    manifests = get_steam_manifests()
    game = scan_game(game_folder, None, manifests)

    if route_override in ("direct", "optiscaler", "dlss"):
        game["route"] = route_override
    if opti_dll:
        game["optiDllName"] = opti_dll
    if use_fakenvapi is not None:
        game["useFakeNvapi"] = bool(use_fakenvapi)
    if install_ref is not None:
        game["installReFramework"] = bool(install_ref)
    if fg_mode:
        game["fgMode"] = fg_mode

    active_fg_mode = game.get("fgMode") or "auto"
    if active_fg_mode.startswith("dlssg_"):
        game["useFakeNvapi"] = True

    cleanup_helixsr_files(game)

    t = game["exeFolder"] or game["folder"]
    src_ffx_dll = os.path.join(CORE_DIR, DLL_FSR)

    if game["route"] == "optiscaler":
        helix_dir = os.path.join(t, HELIXSR_FOLDER)
        backup_dir = os.path.join(helix_dir, BACKUP_FOLDER)
        marker_path = os.path.join(helix_dir, MARKER_FILE)
        os.makedirs(backup_dir, exist_ok=True)

        opti_name = game.get("optiDllName") or "dxgi.dll"
        moved_list = []
        created_list = []
        rec = {
            "optiscaler": opti_name,
            "fakenvapi": bool(game.get("useFakeNvapi", True)),
            "fg_mode": active_fg_mode,
            "helixsr": CORE_VERSION,
            "route": "optiscaler",
        }

        curr_target = os.path.join(t, opti_name)
        if os.path.isfile(curr_target):
            b_target = os.path.join(backup_dir, opti_name)
            if not os.path.isfile(b_target):
                shutil.copy2(curr_target, b_target)
                moved_list.append(opti_name)

        game_ini = os.path.join(t, "OptiScaler.ini")
        src_ini = os.path.join(CORE_DIR, "optiscaler", "OptiScaler.ini")
        if os.path.isfile(game_ini):
            b_ini = os.path.join(backup_dir, "OptiScaler.ini")
            if not os.path.isfile(b_ini):
                shutil.copy2(game_ini, b_ini)
            rec["ini"] = "edited"
        elif os.path.isfile(src_ini):
            shutil.copy2(src_ini, game_ini)
            rec["ini"] = "created"

        dst_fnv = os.path.join(t, "fakenvapi.dll")
        dst_fnv_ini = os.path.join(t, "fakenvapi.ini")
        if game.get("useFakeNvapi", True):
            for fn in ("fakenvapi.dll", "fakenvapi.ini"):
                s = os.path.join(CORE_DIR, "optiscaler", fn)
                d = os.path.join(t, fn)
                if os.path.isfile(s):
                    if not os.path.isfile(d):
                        created_list.append(fn)
                    shutil.copy2(s, d)
        else:
            for d in (dst_fnv, dst_fnv_ini):
                if os.path.isfile(d):
                    try:
                        os.remove(d)
                    except Exception:
                        pass

        src_opti = os.path.join(CORE_DIR, "optiscaler", "OptiScaler.dll")
        if os.path.isfile(src_opti):
            shutil.copy2(src_opti, curr_target)

        if os.path.isfile(src_ffx_dll):
            shutil.copy2(src_ffx_dll, os.path.join(helix_dir, OWN_DLL))
            shutil.copy2(src_ffx_dll, os.path.join(helix_dir, OWN_SR_DLL))

        sync_network_files(helix_dir)

        my_fsr_dir = os.path.join(helix_dir, MY_FSR_FOLDER)
        os.makedirs(my_fsr_dir, exist_ok=True)
        with open(os.path.join(my_fsr_dir, "README.txt"), "w", encoding="utf-8") as f:
            f.write(MY_FSR_README)

        src_amd_fsr = os.path.join(CORE_DIR, "amd-fsr", DLL_SR)
        if os.path.isfile(src_amd_fsr):
            shutil.copy2(src_amd_fsr, os.path.join(helix_dir, AMD_FSR_FILE))

        core_my_fsr = os.path.join(CORE_DIR, MY_FSR_FOLDER)
        optional_fg_dlls = (
            "libxess_fg.dll",
            "libxell.dll",
            "amd_fidelityfx_framegeneration_dx12.dll",
            "dlssg_to_fsr3_amd_is_better.dll",
        )
        for fg_dll in optional_fg_dlls:
            src_fg = os.path.join(core_my_fsr, fg_dll) if os.path.isfile(os.path.join(core_my_fsr, fg_dll)) else (
                os.path.join(my_fsr_dir, fg_dll) if os.path.isfile(os.path.join(my_fsr_dir, fg_dll)) else (
                    os.path.join(CORE_DIR, "optiscaler", fg_dll) if os.path.isfile(os.path.join(CORE_DIR, "optiscaler", fg_dll)) else None
                )
            )
            if src_fg:
                shutil.copy2(src_fg, os.path.join(helix_dir, fg_dll))
                if fg_dll.lower() == "dlssg_to_fsr3_amd_is_better.dll":
                    dst_nukem = os.path.join(t, fg_dll)
                    if not os.path.isfile(dst_nukem):
                        created_list.append(fg_dll)
                    shutil.copy2(src_fg, dst_nukem)

        # HelixSR 1.8+ ships AMD's FSR frame generation DLL; use it when no custom one was provided
        bundled_fg = os.path.join(CORE_DIR, "amd-fsr", AMD_FG_FILE)
        dst_fg = os.path.join(helix_dir, AMD_FG_FILE)
        if not os.path.isfile(dst_fg) and os.path.isfile(bundled_fg):
            shutil.copy2(bundled_fg, dst_fg)

        if os.path.isfile(game_ini):
            with open(game_ini, "r", encoding="utf-8", errors="ignore") as f:
                txt = f.read()
            txt = set_ini_value(txt, "Dx12Upscaler", "fsr31", "Upscalers")
            txt = set_ini_value(txt, "FfxDx12Path", f"HelixSR\\{OWN_DLL}", "Libraries")
            txt = set_ini_value(txt, "FfxDx12SRPath", f"HelixSR\\{OWN_SR_DLL}", "Libraries")

            ffx_fg_lib = os.path.join(helix_dir, "amd_fidelityfx_framegeneration_dx12.dll")
            if os.path.isfile(ffx_fg_lib):
                txt = set_ini_value(txt, "FfxDx12FGPath", "HelixSR\\amd_fidelityfx_framegeneration_dx12.dll", "Libraries")
            elif game.get("foundFfxFgPath") and os.path.isfile(game["foundFfxFgPath"]):
                txt = set_ini_value(txt, "FfxDx12FGPath", game["foundFfxFgPath"], "Libraries")

            xe_fg_lib = os.path.join(helix_dir, "libxess_fg.dll")
            if os.path.isfile(xe_fg_lib):
                txt = set_ini_value(txt, "XeFGPath", "HelixSR\\libxess_fg.dll", "Libraries")
            elif game.get("foundXeFgPath") and os.path.isfile(game["foundXeFgPath"]):
                txt = set_ini_value(txt, "XeFGPath", game["foundXeFgPath"], "Libraries")

            xe_ll_lib = os.path.join(helix_dir, "libxell.dll")
            if os.path.isfile(xe_ll_lib):
                txt = set_ini_value(txt, "XeLLPath", "HelixSR\\libxell.dll", "Libraries")
            elif game.get("foundXeLlPath") and os.path.isfile(game["foundXeLlPath"]):
                txt = set_ini_value(txt, "XeLLPath", game["foundXeLlPath"], "Libraries")

            if active_fg_mode == "dlssg_xefg":
                txt = set_ini_value(txt, "Enabled", "true", "FrameGen")
                txt = set_ini_value(txt, "FGInput", "dlssg", "FrameGen")
                txt = set_ini_value(txt, "FGOutput", "xefg", "FrameGen")
            elif active_fg_mode == "dlssg_fsrfg":
                txt = set_ini_value(txt, "Enabled", "true", "FrameGen")
                txt = set_ini_value(txt, "FGInput", "dlssg", "FrameGen")
                txt = set_ini_value(txt, "FGOutput", "fsrfg", "FrameGen")
            elif active_fg_mode == "dlssg_nukems":
                txt = set_ini_value(txt, "Enabled", "true", "FrameGen")
                txt = set_ini_value(txt, "FGInput", "dlssg", "FrameGen")
                txt = set_ini_value(txt, "FGOutput", "nukems", "FrameGen")
            elif active_fg_mode == "optifg_fsrfg":
                txt = set_ini_value(txt, "Enabled", "true", "FrameGen")
                txt = set_ini_value(txt, "FGInput", "upscaler", "FrameGen")
                txt = set_ini_value(txt, "FGOutput", "fsrfg", "FrameGen")
                txt = set_ini_value(txt, "HUDFix", "true", "OptiFG")
            else:
                txt = set_ini_value(txt, "Enabled", "auto", "FrameGen")
                txt = set_ini_value(txt, "FGInput", "auto", "FrameGen")
                txt = set_ini_value(txt, "FGOutput", "nofg", "FrameGen")

            # Everything above is preconfigured, so keep OptiScaler quiet in-game: no startup splash and no
            # "Update available" popup (the bundled OptiScaler is never the newest). Insert still opens the menu.
            txt = set_ini_value(txt, "DisableSplash", "true", "Menu")
            txt = set_ini_value(txt, "CheckForUpdate", "false", "Hotfix")

            if game.get("isInZoi"):
                txt = apply_inzoi_optiscaler_ini(txt)

            with open(game_ini, "w", encoding="utf-8") as f:
                f.write(txt)

        rec["moved"] = moved_list
        rec["created"] = created_list
        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=2)

        clear_shader_cache(game)

    elif game["route"] == "direct":
        targets = game.get("fsrTargets", [])
        if targets:
            for target in targets:
                orig = os.path.splitext(target)[0] + ".original.dll"
                if os.path.isfile(target) and not os.path.isfile(orig):
                    os.replace(target, orig)
                shutil.copy2(src_ffx_dll, target)
                tdir = os.path.dirname(target)
                sync_network_files(tdir)
                with open(os.path.join(tdir, MARKER_FILE), "w", encoding="utf-8") as f:
                    json.dump({"helixsr": CORE_VERSION, "route": "direct"}, f, indent=2)
        else:
            created_dlls = []
            for dll_name in (DLL_SR, DLL_FSR):
                dst = os.path.join(t, dll_name)
                orig = os.path.splitext(dst)[0] + ".original.dll"
                if os.path.isfile(dst) and not os.path.isfile(orig):
                    os.replace(dst, orig)
                elif not os.path.isfile(dst):
                    created_dlls.append(dll_name)
                shutil.copy2(src_ffx_dll, dst)
            sync_network_files(t)
            with open(os.path.join(t, MARKER_FILE), "w", encoding="utf-8") as f:
                json.dump({"helixsr": CORE_VERSION, "route": "direct", "created_dlls": created_dlls}, f, indent=2)

        clear_shader_cache(game)
        sanitize_game_config(game)

    elif game["route"] == "dlss":
        # EXPERIMENTAL (HelixSR 1.8.1): HelixSR's DLSS loader as dxgi.dll + HelixSR (one-file DLL) as nvngx.dll
        # next to the game's .exe; the game's own DLSS option then runs HelixSR, without OptiScaler.
        if not os.path.isdir(t):
            raise RuntimeError("Game executable directory not found.")
        src_loader = os.path.join(CORE_DIR, LOADER_FOLDER, LOADER_DLL)
        if not os.path.isfile(src_loader):
            raise RuntimeError(f"HelixSR DLSS loader missing at: {src_loader}")

        helix_dir = os.path.join(t, HELIXSR_FOLDER)
        backup_dir = os.path.join(helix_dir, BACKUP_FOLDER)
        marker_path = os.path.join(helix_dir, MARKER_FILE)
        os.makedirs(backup_dir, exist_ok=True)

        moved_list = []
        for name in (LOADER_DLL, NVNGX_CORE_DLL):
            cur = os.path.join(t, name)
            ours = is_dlss_loader_binary(cur) if name == LOADER_DLL else is_helixsr_binary(cur)
            if os.path.isfile(cur) and not ours:
                bak = os.path.join(backup_dir, name)
                if os.path.isfile(bak):
                    os.remove(bak)
                shutil.move(cur, bak)
                moved_list.append(name)

        shutil.copy2(src_loader, os.path.join(t, LOADER_DLL))
        shutil.copy2(src_ffx_dll, os.path.join(t, NVNGX_CORE_DLL))
        sync_network_files(t)

        with open(marker_path, "w", encoding="utf-8") as f:
            json.dump({
                "helixsr": CORE_VERSION,
                "route": "dlss",
                "files": [LOADER_DLL, NVNGX_CORE_DLL],
                "moved": moved_list,
                "created": [],
            }, f, indent=2)

        clear_shader_cache(game)

    if game.get("isInZoi"):
        apply_inzoi_user_settings(game)

    if game.get("installReFramework"):
        install_reframework_nightly(game)
    elif os.path.isfile(os.path.join(t, "reframework_revision.txt")):
        uninstall_reframework(game)

    fg_tag = ""
    if game["route"] == "optiscaler" and active_fg_mode != "auto":
        fg_map = {
            "dlssg_xefg": " + XeFG",
            "dlssg_fsrfg": " + FSR-FG",
            "dlssg_nukems": " + NukemFG",
            "optifg_fsrfg": " + OptiFG",
        }
        fg_tag = fg_map.get(active_fg_mode, "")

    if game["route"] == "optiscaler":
        method_label = f"OptiScaler ({game.get('optiDllName', 'dxgi.dll')}{fg_tag})"
    elif game["route"] == "dlss":
        method_label = "DLSS Loader (Experimental)"
    else:
        method_label = "Direct FSR 3.1"
    if game.get("installReFramework"):
        method_label += " + REFramework Nightly"
    return {"success": True, "message": f"Installed HelixSR [{method_label}] for {game['name']}!"}


def uninstall_helixsr(game_folder):
    manifests = get_steam_manifests()
    game = scan_game(game_folder, None, manifests)
    cleanup_helixsr_files(game)
    if game.get("isReEngine") or game.get("installReFramework") or os.path.isfile(os.path.join(game.get("exeFolder") or game_folder, "reframework_revision.txt")):
        uninstall_reframework(game)
    return {"success": True, "message": f"Restored original files for {game['name']}."}


def get_gpu_info():
    gpus = []
    if os.name != "nt":
        try:
            out = subprocess.check_output(["lspci"], text=True, stderr=subprocess.DEVNULL)
            for line in out.splitlines():
                if any(k in line for k in ("VGA compatible controller:", "3D controller:", "Display controller:")):
                    parts = line.split(":", 2)
                    name = parts[-1].strip() if len(parts) >= 3 else line.strip()
                    gpus.append({"name": name, "ramMB": 0, "driver": "Linux / Mesa RADV"})
        except Exception:
            pass
    if not gpus:
        gpus.append({"name": "AMD RDNA Direct3D 12 / Vulkan GPU", "ramMB": 0, "driver": platform.release()})
    return gpus


def detect_handheld_environment():
    """
    Detects if a gamepad / game controller is connected or handheld CLI flag is passed.
    Returns dict: { isHandheld, isControllerDetected, isSteamOS, isBazzite, isXboxMode, reason, device }
    """
    info = {
        "isHandheld": False,
        "isControllerDetected": False,
        "isSteamOS": False,
        "isBazzite": False,
        "isXboxMode": False,
        "reason": "",
        "device": "",
    }

    # 1. CLI flag or explicit environment variable
    if "--handheld" in sys.argv or os.environ.get("HELIXSR_HANDHELD") == "1":
        info["isHandheld"] = True
        info["isControllerDetected"] = True
        info["reason"] = "Command-line flag or environment variable active"
        info["device"] = "Handheld Mode"
        return info

    # 2. Check for connected gamepad / joystick on Linux (/dev/input/js* or event devices)
    if os.name != "nt":
        try:
            import glob
            js_devices = glob.glob("/dev/input/js*")
            if js_devices:
                info["isHandheld"] = True
                info["isControllerDetected"] = True
                info["reason"] = f"Gamepad controller detected ({os.path.basename(js_devices[0])})"
                info["device"] = "Controller"
                return info
            by_id = glob.glob("/dev/input/by-id/*joystick*") + glob.glob("/dev/input/by-id/*gamepad*")
            if by_id:
                info["isHandheld"] = True
                info["isControllerDetected"] = True
                info["reason"] = "Gamepad controller detected in /dev/input/by-id"
                info["device"] = "Controller"
                return info
        except Exception:
            pass
    else:
        # Check Windows XInput if running under Python on Windows
        try:
            import ctypes
            for dll_name in ("xinput1_4.dll", "xinput9_1_0.dll", "xinput1_3.dll"):
                try:
                    xi = ctypes.windll.LoadLibrary(dll_name)
                    if hasattr(xi, "XInputGetState"):
                        class XINPUT_STATE(ctypes.Structure):
                            _fields_ = [("dwPacketNumber", ctypes.c_uint32), ("Gamepad", ctypes.c_byte * 12)]
                        st = XINPUT_STATE()
                        for i in range(4):
                            if xi.XInputGetState(i, ctypes.byref(st)) == 0:
                                info["isHandheld"] = True
                                info["isControllerDetected"] = True
                                info["reason"] = "Gamepad controller detected via XInput"
                                info["device"] = "Controller"
                                return info
                        break
                except Exception:
                    pass
        except Exception:
            pass

    return info


def get_clean_desktop_env():
    env = dict(os.environ)
    if os.name == "nt":
        return env
    env.pop("LD_PRELOAD", None)
    env.pop("TCL_LIBRARY", None)
    env.pop("TK_LIBRARY", None)
    if "SYSTEM_LD_LIBRARY_PATH" in env:
        env["LD_LIBRARY_PATH"] = env["SYSTEM_LD_LIBRARY_PATH"]
    elif "LD_LIBRARY_PATH" in env:
        parts = [
            p for p in env["LD_LIBRARY_PATH"].split(":")
            if p and not any(k in p.lower() for k in ("steam", "pressure-vessel", "sniper", "soldier", "scout", "helixsr/python"))
        ]
        if parts:
            env["LD_LIBRARY_PATH"] = ":".join(parts)
        else:
            env.pop("LD_LIBRARY_PATH", None)
    base_path = env.get("SYSTEM_PATH") or env.get("PATH", "")
    extra_paths = [
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        os.path.expanduser("~/.local/bin"),
        "/var/lib/flatpak/exports/bin",
        os.path.expanduser("~/.local/share/flatpak/exports/bin"),
    ]
    path_parts = [p for p in base_path.split(":") if p]
    for ep in extra_paths:
        if ep not in path_parts:
            path_parts.append(ep)
    env["PATH"] = ":".join(path_parts)
    return env


def ensure_linux_environment():
    if os.name == "nt":
        return
    try:
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "app_dir.txt"), "w", encoding="utf-8") as f:
            f.write(APP_DIR + "\n")
    except Exception:
        pass

    lf_targets = [
        os.path.join(APP_DIR, "HelixSR-Manager.sh"),
        os.path.join(APP_DIR, "HelixSR-Manager.desktop"),
        os.path.join(CORE_DIR, "helixsr-setup.sh"),
        os.path.join(CORE_DIR, "helixsr-uninstall.sh"),
    ]
    for p in lf_targets:
        if os.path.isfile(p):
            try:
                raw = open(p, "rb").read()
                if b"\r\n" in raw:
                    open(p, "wb").write(raw.replace(b"\r\n", b"\n"))
            except Exception:
                pass

    exec_targets = lf_targets + [
        os.path.join(APP_DIR, "helixsr_swapper_linux.py"),
        os.path.join(CORE_DIR, "setup", "lib", "model", "launch_synth"),
    ]
    for p in exec_targets:
        if os.path.isfile(p):
            try:
                os.chmod(p, 0o755)
            except Exception:
                pass


def open_folder_native(path_str):
    if not path_str or not os.path.exists(path_str):
        return {"success": False, "error": "Folder does not exist"}
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", os.path.normpath(path_str)])
        else:
            subprocess.Popen(["xdg-open", path_str], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=get_clean_desktop_env())
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def launch_game_native(game_folder):
    manifests = get_steam_manifests()
    game = scan_game(game_folder, None, manifests)
    try:
        if game.get("appId"):
            url = f"steam://run/{game['appId']}"
            if os.name == "nt":
                os.startfile(url)
            else:
                subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=get_clean_desktop_env())
            return {"success": True, "message": f"Launching {game['name']} via Steam..."}
    except Exception as e:
        return {"success": False, "error": str(e)}
    return {"success": False, "error": "Could not launch game"}


def broadcast_build_log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg.rstrip()}"
    with BUILD_LOCK:
        BUILD_LOGS.append(line)
        if len(BUILD_LOGS) > 500:
            BUILD_LOGS.pop(0)
        for q in list(BUILD_LISTENERS):
            q.append(line)


def sync_helixsr_to_installed_games():
    """After a rebuild: copy the new HelixSR DLL (network embedded since 1.8) into every game HelixSR is installed in."""
    if not get_core_status()["weightsBuilt"]:
        return 0
    src_dll = os.path.join(CORE_DIR, DLL_FSR)
    if not os.path.isfile(src_dll):
        return 0
    count = 0
    for g in scan_all_games():
        if not g.get("installed"):
            continue
        try:
            updated = False
            t = g.get("exeFolder") or g.get("folder")
            if g["route"] == "optiscaler" and t:
                for d in (os.path.join(t, HELIXSR_FOLDER), os.path.join(t, "_storage_", HELIXSR_FOLDER)):
                    if not os.path.isdir(d):
                        continue
                    shutil.copy2(src_dll, os.path.join(d, OWN_DLL))
                    shutil.copy2(src_dll, os.path.join(d, OWN_SR_DLL))
                    sync_network_files(d)
                    updated = True
                update_marker_version(os.path.join(t, HELIXSR_FOLDER, MARKER_FILE))
            elif g["route"] == "dlss" and t:
                core = os.path.join(t, NVNGX_CORE_DLL)
                if is_helixsr_binary(core):
                    shutil.copy2(src_dll, core)
                    sync_network_files(t)
                    update_marker_version(os.path.join(t, HELIXSR_FOLDER, MARKER_FILE))
                    updated = True
            elif g["route"] == "direct":
                any_target = False
                for target in g.get("fsrTargets") or []:
                    tdir = os.path.dirname(target)
                    marker = os.path.join(tdir, MARKER_FILE)
                    if not os.path.isfile(os.path.splitext(target)[0] + ".original.dll") and not os.path.isfile(marker):
                        continue
                    any_target = True
                    shutil.copy2(src_dll, target)
                    sync_network_files(tdir)
                    update_marker_version(marker)
                    updated = True
                exe_marker = os.path.join(t, MARKER_FILE) if t else None
                if not any_target and exe_marker and os.path.isfile(exe_marker):
                    for dll_name in (DLL_SR, DLL_FSR):
                        dst = os.path.join(t, dll_name)
                        if is_helixsr_binary(dst):
                            shutil.copy2(src_dll, dst)
                    sync_network_files(t)
                    update_marker_version(exe_marker)
                    updated = True
            if updated:
                count += 1
        except Exception:
            pass
    return count


def start_network_build(dlss_path="", wave64=False):
    global IS_BUILDING
    if IS_BUILDING:
        return {"success": False, "error": "Build already in progress"}

    def worker():
        global IS_BUILDING
        IS_BUILDING = True
        try:
            if os.name == "nt":
                ps1 = os.path.join(CORE_DIR, "helixsr-setup.ps1")
                cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Yes", "-Rebuild"]
                if dlss_path and os.path.isfile(dlss_path):
                    cmd += ["-Dlss", dlss_path]
                env = dict(os.environ)
            else:
                sh_script = os.path.join(CORE_DIR, "helixsr-setup.sh")
                synth_bin = os.path.join(CORE_DIR, "setup", "lib", "model", "launch_synth")
                for p in (sh_script, synth_bin):
                    if os.path.isfile(p):
                        try:
                            os.chmod(p, 0o755)
                        except Exception:
                            pass
                cmd = ["bash", sh_script, "--yes", "--rebuild"]
                if dlss_path and os.path.isfile(dlss_path):
                    cmd += ["--dlss", dlss_path]
                env = get_clean_desktop_env()

            env["PYTHONUNBUFFERED"] = "1"
            broadcast_build_log("Starting HelixSR Network Compiler: " + " ".join(cmd))
            proc = subprocess.Popen(
                cmd,
                cwd=CORE_DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
            suppress = False
            for line in proc.stdout:
                if suppress:
                    continue
                if "looking for games" in line.lower():
                    suppress = True
                    broadcast_build_log("(HelixSR Manager installs games itself - skipping the setup's game installer)")
                    continue
                broadcast_build_log(line)
            proc.wait()
            if get_core_status()["weightsBuilt"]:
                broadcast_build_log("Build finished successfully!")
                n = sync_helixsr_to_installed_games()
                if n:
                    broadcast_build_log(f"Updated HelixSR in {n} installed game(s).")
            else:
                broadcast_build_log(f"Build exited with code {proc.returncode}")
        except Exception as e:
            broadcast_build_log(f"Error during build: {e}")
        finally:
            IS_BUILDING = False

    threading.Thread(target=worker, daemon=True).start()
    return {"success": True}


def get_game_logs_and_ini(folder):
    manifests = get_steam_manifests()
    g = scan_game(folder, None, manifests) if folder else {}
    t = g.get("exeFolder") or folder
    hlog = ""
    olog = ""
    ini = ""
    if t and os.path.isdir(t):
        for p in (os.path.join(t, HELIXSR_FOLDER, "helixsr.log"), os.path.join(t, "helixsr.log")):
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        hlog = f.read()
                except Exception:
                    pass
                break
        op = os.path.join(t, "OptiScaler.log")
        if os.path.isfile(op):
            try:
                with open(op, "r", encoding="utf-8", errors="ignore") as f:
                    olog = f.read()
            except Exception:
                pass
        ip = os.path.join(t, "OptiScaler.ini")
        if os.path.isfile(ip):
            try:
                with open(ip, "r", encoding="utf-8", errors="ignore") as f:
                    ini = f.read()
            except Exception:
                pass
    return {"helixsrLog": hlog, "optiscalerLog": olog, "optiscalerIni": ini, "exeFolder": t}


# ============================================================================
# Standalone Native Desktop GUI (Tkinter / Tcl-Tk 9.0)
# ============================================================================

def _prepare_tk_env():
    for ver in ("9.0", "8.6"):
        tcl_dir = os.path.join(sys.prefix, "lib", f"tcl{ver}")
        tk_dir = os.path.join(sys.prefix, "lib", f"tk{ver}")
        if os.path.isdir(tcl_dir) and os.path.isdir(tk_dir):
            os.environ.setdefault("TCL_LIBRARY", tcl_dir)
            os.environ.setdefault("TK_LIBRARY", tk_dir)
            break


def _acquire_single_instance_lock():
    """Returns lock file object if primary instance, or None if another instance is already running."""
    if os.name == "nt":
        return True
    try:
        import fcntl
        data_dir = get_data_dir()
        os.makedirs(data_dir, exist_ok=True)
        lock_path = os.path.join(data_dir, "instance.lock")
        wakeup_path = os.path.join(data_dir, "wakeup.flag")
        fp = open(lock_path, "w")
        try:
            fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fp.write(str(os.getpid()) + "\n")
            fp.flush()
            return fp
        except (BlockingIOError, IOError):
            try:
                with open(wakeup_path, "w", encoding="utf-8") as wf:
                    wf.write(str(time.time()))
            except Exception:
                pass
            fp.close()
            return None
    except Exception:
        return True


def run_standalone_gui(smoke_test_ms=0):
    _prepare_tk_env()
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, messagebox
    except ImportError:
        if os.name != "nt" and os.environ.get("HELIXSR_SH_DELEGATED") != "1":
            sh_path = os.path.join(APP_DIR, "HelixSR-Manager.sh")
            if os.path.isfile(sh_path):
                env = dict(os.environ)
                env["HELIXSR_SH_DELEGATED"] = "1"
                os.execvpe("bash", ["bash", sh_path] + sys.argv[1:], env)
        raise

    lock_handle = _acquire_single_instance_lock()
    if lock_handle is None:
        print("[HelixSR Manager] Another instance is already running; focusing existing window.")
        return

    class HelixSRStandaloneApp:
        def __init__(self, root):
            self.root = root
            self.cfg = load_config()
            self.is_light = bool(self.cfg.get("lightTheme", False))
            self.all_games = []
            self.filtered_games = []
            self.selected_game = None
            self.current_tab = "games"
            self.quick_filter = "all"
            self.is_grid_view = True
            self.focused_index = -1
            self.is_handheld_mode = False
            self.user_disabled_handheld = False
            self.build_log_queue = []
            self.drawer_tab = "guide"
            self.updating_drawer = False
            self.toast_after_id = None
            self._image_cache = {}
            self._image_refs = []
            self._card_frames = []
            self._dlss_candidate_map = {}

            with BUILD_LOCK:
                BUILD_LISTENERS.append(self.build_log_queue)

            self.root.title(f"HelixSR Manager v{APP_VERSION} — Neural Upscaler & Game Manager")
            sw = max(1024, self.root.winfo_screenwidth())
            sh = max(680, self.root.winfo_screenheight())
            win_w = min(1320, sw - 40)
            win_h = min(850, sh - 60)
            pos_x = max(0, (sw - win_w) // 2)
            pos_y = max(0, (sh - win_h) // 2)
            self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
            self.root.minsize(1020, 660)

            self._set_app_icon()
            self._apply_palette()
            self._configure_ttk_styles()
            self._build_layout()
            self._bind_shortcuts()

            handheld_info = detect_handheld_environment()
            in_gamescope = (
                os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"
                or os.environ.get("SteamGamepadUI") == "1"
            )
            if in_gamescope or "--handheld" in sys.argv or handheld_info.get("isHandheld"):
                self._toggle_handheld_mode(force_state=True)

            self.root.after(80, self._initial_load)
            self.root.after(250, self._periodic_tick)
            if smoke_test_ms > 0:
                self.root.after(smoke_test_ms, self.root.destroy)

        def _set_app_icon(self):
            try:
                icon = tk.PhotoImage(width=32, height=32)
                icon.put("#f1c40f", to=(2, 2, 30, 30))
                icon.put("#f39c12", to=(2, 16, 30, 30))
                bolt_pts = [
                    (17, 5, 20, 8), (15, 8, 19, 11), (12, 11, 17, 14),
                    (10, 14, 22, 17), (15, 17, 20, 20), (14, 20, 18, 23), (12, 23, 16, 27),
                ]
                for x1, y1, x2, y2 in bolt_pts:
                    icon.put("#0a0c10", to=(x1, y1, x2, y2))
                self._icon_ref = icon
                self.root.iconphoto(True, icon)
            except Exception:
                pass

        def _apply_palette(self):
            if self.is_light:
                # Exact Clean Light Palette from src/MainWindow.cs
                self.c_bg = "#eef1f5"
                self.c_main_shell = "#ffffff"
                self.c_sidebar = "#ffffff"
                self.c_card = "#f7f9fc"
                self.c_card_hover = "#eaeff6"
                self.c_surface2 = "#f1f5f9"
                self.c_border = "#d0d7e2"
                self.c_border_strong = "#d4ac0d"
                self.c_emerald = "#d4ac0d"          # AccentEmerald (Dark Gold in Light theme)
                self.c_emerald_strong = "#f1c40f"   # AccentEmeraldStrong
                self.c_emerald_bg = "#f9f1d0"       # AccentEmeraldBg tint
                self.c_hero_bg = "#f9f4df"
                self.c_on_accent = "#0a0c10"        # TextOnAccent
                self.c_blue = "#0284c7"             # AccentBlue
                self.c_sky = "#0ea5e9"              # AccentSky
                self.c_violet = "#7c3aed"           # AccentViolet
                self.c_amber = "#d97706"            # AccentAmber
                self.c_red = "#dc2626"              # AccentRed
                self.c_text = "#181f29"             # TextMain
                self.c_muted = "#586577"            # TextMuted
                self.c_dim = "#8592a4"              # TextDim
            else:
                # Exact HelixSR Manager Signature Dark Gold Palette from src/MainWindow.cs
                self.c_bg = "#06080d"               # BgApp (rgb 6, 8, 13)
                self.c_main_shell = "#0e1219"       # mainBorder (rgb 14, 18, 25)
                self.c_sidebar = "#11161e"          # BgSidebar (rgb 17, 22, 30)
                self.c_card = "#161c26"             # BgCard (rgb 22, 28, 38)
                self.c_card_hover = "#1e2735"       # BgCardHover (rgb 30, 39, 53)
                self.c_surface2 = "#0d1118"         # BgSurface2 (rgb 13, 17, 24)
                self.c_border = "#222c3c"           # BorderColor
                self.c_border_strong = "#91780f"    # BorderStrong (gold border)
                self.c_emerald = "#f1c40f"          # AccentEmerald (Gold #f1c40f)
                self.c_emerald_strong = "#f1c40f"   # AccentEmeraldStrong (Gold #f1c40f)
                self.c_emerald_bg = "#282414"       # AccentEmeraldBg (gold-tinted surface)
                self.c_hero_bg = "#1b1d1c"          # Hero banner gold/cyan tinted surface
                self.c_on_accent = "#0a0c10"        # TextOnAccent (rgb 10, 12, 16)
                self.c_blue = "#39d5ff"             # AccentBlue (rgb 57, 213, 255)
                self.c_sky = "#38bdf8"              # AccentSky (rgb 56, 189, 248)
                self.c_violet = "#9b6bff"           # AccentViolet (rgb 155, 107, 255)
                self.c_amber = "#f59e0b"            # AccentAmber (rgb 245, 158, 11)
                self.c_red = "#ef4444"              # AccentRed (rgb 239, 68, 68)
                self.c_text = "#f3f6fb"             # TextMain (rgb 243, 246, 251)
                self.c_muted = "#9aa6b8"            # TextMuted (rgb 154, 166, 184)
                self.c_dim = "#687488"              # TextDim (rgb 104, 116, 136)
            self.root.configure(bg=self.c_bg)

        def _configure_ttk_styles(self):
            try:
                style = ttk.Style(self.root)
                try:
                    style.theme_use("clam")
                except Exception:
                    pass
                style.configure(
                    "Helix.TCombobox",
                    fieldbackground=self.c_card,
                    background=self.c_card_hover,
                    foreground=self.c_text,
                    arrowcolor=self.c_muted,
                    bordercolor=self.c_border,
                    lightcolor=self.c_border,
                    darkcolor=self.c_border,
                    selectbackground=self.c_emerald_bg,
                    selectforeground=self.c_emerald,
                    padding=5,
                )
                style.map(
                    "Helix.TCombobox",
                    fieldbackground=[("readonly", self.c_card), ("!disabled", self.c_card)],
                    foreground=[("readonly", self.c_text), ("!disabled", self.c_text)],
                    selectbackground=[("readonly", self.c_card)],
                    selectforeground=[("readonly", self.c_text)],
                    background=[("active", self.c_card_hover)],
                    bordercolor=[("focus", self.c_emerald), ("active", self.c_emerald)],
                )
                self.root.option_add("*TCombobox*Listbox.background", self.c_sidebar)
                self.root.option_add("*TCombobox*Listbox.foreground", self.c_text)
                self.root.option_add("*TCombobox*Listbox.selectBackground", self.c_emerald_bg)
                self.root.option_add("*TCombobox*Listbox.selectForeground", self.c_emerald)
                self.root.option_add("*TCombobox*Listbox.font", ("Sans", 10))

                style.configure(
                    "Helix.Treeview",
                    background=self.c_card,
                    fieldbackground=self.c_card,
                    foreground=self.c_text,
                    bordercolor=self.c_border,
                    rowheight=30,
                    font=("Sans", 10),
                )
                style.configure(
                    "Helix.Treeview.Heading",
                    background=self.c_sidebar,
                    foreground=self.c_muted,
                    bordercolor=self.c_border,
                    font=("Sans", 9, "bold"),
                    padding=(8, 6),
                )
                style.map(
                    "Helix.Treeview",
                    background=[("selected", self.c_emerald_bg)],
                    foreground=[("selected", self.c_emerald)],
                )
            except Exception:
                pass

        def _make_btn(self, parent, text, cmd, bg=None, fg=None, border=None, padx=11, pady=5, font_size=9):
            btn_bg = bg if bg is not None else self.c_card_hover
            btn_fg = fg if fg is not None else self.c_text
            btn_bd = border if border is not None else self.c_border
            btn = tk.Button(
                parent,
                text=text,
                command=cmd,
                bg=btn_bg,
                fg=btn_fg,
                activebackground=self.c_emerald_strong,
                activeforeground=self.c_on_accent,
                highlightbackground=btn_bd,
                highlightcolor=self.c_emerald,
                highlightthickness=1,
                bd=0,
                relief="flat",
                padx=padx,
                pady=pady,
                cursor="hand2",
                font=("Sans", font_size, "bold"),
            )
            return btn

        # --------------------------------------------------------------------
        # SHELL LAYOUT (Matches MainWindow.cs BuildUi / BuildSidebar / BuildTopBar)
        # --------------------------------------------------------------------
        def _build_layout(self):
            for child in self.root.winfo_children():
                child.destroy()

            # 5. Bottom Handheld Controller Legend Bar (Matches BuildHandheldLegendBar)
            self.legend_bar = tk.Frame(
                self.root,
                bg="#0c1017" if not self.is_light else self.c_sidebar,
                highlightbackground=self.c_border_strong,
                highlightthickness=1,
                height=44,
            )
            self.legend_bar.pack_propagate(False)
            self.legend_stack = tk.Frame(self.legend_bar, bg=self.legend_bar.cget("bg"))
            self.legend_stack.pack(expand=True, pady=8)

            # Shell Grid with 14px outer margin, 248px Floating Sidebar + 14px Gap + Main Container
            self.root_grid = tk.Frame(self.root, bg=self.c_bg, padx=14, pady=14)
            self.root_grid.pack(side="top", fill="both", expand=True)

            # 1. Floating Sidebar (248px wide)
            self.sidebar = tk.Frame(
                self.root_grid,
                bg=self.c_sidebar,
                width=248,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            self.sidebar.pack(side="left", fill="y", padx=(0, 14))
            self.sidebar.pack_propagate(False)
            self._build_sidebar_contents()

            # 2. Main Container (Floating Rounded Card Shell #0e1219 with TopBar + Content Panes)
            self.main_border = tk.Frame(
                self.root_grid,
                bg=self.c_main_shell,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            self.main_border.pack(side="left", fill="both", expand=True)

            # TopBar inside Main Container (Row 0)
            self._build_topbar(self.main_border)

            # Content Panes inside Main Container (Row 1)
            self.panes_wrap = tk.Frame(self.main_border, bg=self.c_main_shell)
            self.panes_wrap.pack(side="top", fill="both", expand=True)

            self.panes = {}
            for tid in ("games", "core", "myfsr", "settings", "about"):
                f = tk.Frame(self.panes_wrap, bg=self.c_main_shell)
                self.panes[tid] = f

            self._build_games_pane(self.panes["games"])
            self._build_core_pane(self.panes["core"])
            self._build_myfsr_pane(self.panes["myfsr"])
            self._build_settings_pane(self.panes["settings"])
            self._build_about_pane(self.panes["about"])

            # 4. Floating Reactive Toast Notification (bottom-right overlay matching _toastBanner)
            self.toast_banner = tk.Frame(
                self.root,
                bg="#121923" if not self.is_light else "#ffffff",
                highlightbackground=self.c_emerald,
                highlightthickness=1,
                padx=16,
                pady=10,
            )
            self.lbl_toast = tk.Label(
                self.toast_banner,
                text="",
                bg=self.toast_banner.cget("bg"),
                fg="#ffffff" if not self.is_light else self.c_text,
                font=("Sans", 10, "bold"),
            )
            self.lbl_toast.pack()

            self._switch_tab(self.current_tab)
            self._update_handheld_legend()

        def _build_sidebar_contents(self):
            # Brand Header (88px height)
            logo_panel = tk.Frame(self.sidebar, bg=self.c_sidebar, height=88, padx=18, pady=18)
            logo_panel.pack(side="top", fill="x")
            logo_panel.pack_propagate(False)

            logo_box = tk.Frame(
                logo_panel,
                bg=self.c_emerald_strong,
                width=42,
                height=42,
                highlightbackground=self.c_border_strong,
                highlightthickness=1,
            )
            logo_box.pack(side="left", padx=(0, 12))
            logo_box.pack_propagate(False)
            tk.Label(
                logo_box,
                text="⚡",
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                font=("Sans", 16, "bold"),
            ).pack(expand=True)

            title_panel = tk.Frame(logo_panel, bg=self.c_sidebar)
            title_panel.pack(side="left", fill="x", expand=True)

            title_row = tk.Frame(title_panel, bg=self.c_sidebar)
            title_row.pack(fill="x", anchor="w")
            tk.Label(
                title_row,
                text="HelixSR",
                bg=self.c_sidebar,
                fg=self.c_text,
                font=("Sans", 14, "bold"),
            ).pack(side="left")

            ver_pill = tk.Frame(
                title_row,
                bg=self.c_emerald_bg,
                highlightbackground=self.c_border_strong,
                highlightthickness=1,
                padx=5,
                pady=1,
            )
            ver_pill.pack(side="left", padx=(7, 0))
            tk.Label(
                ver_pill,
                text=f"v{APP_VERSION}",
                bg=self.c_emerald_bg,
                fg=self.c_emerald,
                font=("Sans", 8, "bold"),
            ).pack()

            tk.Label(
                title_panel,
                text="HELIXSR MANAGER",
                bg=self.c_sidebar,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

            # Nav List (WORKSPACE & SYSTEM sections)
            nav_stack = tk.Frame(self.sidebar, bg=self.c_sidebar, padx=12, pady=4)
            nav_stack.pack(side="top", fill="both", expand=True)

            tk.Label(
                nav_stack,
                text="WORKSPACE",
                bg=self.c_sidebar,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
                padx=10,
            ).pack(fill="x", pady=(0, 6))

            self.nav_items_ui = {}
            self._create_nav_item(nav_stack, "games", "🎮", "Games Library", badge_type="count")
            self._create_nav_item(nav_stack, "core", "⚡", "Engine & Weights", badge_type="dot")
            self._create_nav_item(nav_stack, "myfsr", "📦", "Custom FSR (my-fsr)", badge_type=None)

            tk.Label(
                nav_stack,
                text="SYSTEM",
                bg=self.c_sidebar,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
                padx=10,
            ).pack(fill="x", pady=(18, 6))

            self._create_nav_item(nav_stack, "settings", "⚙️", "Scan & Settings", badge_type=None)
            self._create_nav_item(nav_stack, "about", "🩺", "Hardware & About", badge_type=None)

            # Bottom Live Status Card (Matches statusCard in BuildSidebar)
            self.sidebar_status_card = tk.Frame(
                self.sidebar,
                bg=self.c_surface2,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=14,
                pady=12,
                cursor="hand2",
            )
            self.sidebar_status_card.pack(side="bottom", fill="x", padx=12, pady=12)

            status_top = tk.Frame(self.sidebar_status_card, bg=self.c_surface2)
            status_top.pack(fill="x", pady=(0, 6))
            self.dot_sidebar_status = tk.Label(
                status_top,
                text="●",
                bg=self.c_surface2,
                fg=self.c_emerald,
                font=("Sans", 10, "bold"),
            )
            self.dot_sidebar_status.pack(side="left", padx=(0, 6))
            self.lbl_sidebar_status = tk.Label(
                status_top,
                text="Engine Ready",
                bg=self.c_surface2,
                fg=self.c_text,
                font=("Sans", 9, "bold"),
                anchor="w",
            )
            self.lbl_sidebar_status.pack(side="left", fill="x", expand=True)

            # Progress bar track (5px high)
            self.sidebar_prog_track = tk.Frame(
                self.sidebar_status_card,
                bg="#222c3c" if not self.is_light else "#cbd5e1",
                height=5,
            )
            self.sidebar_prog_track.pack(fill="x", pady=(2, 8))
            self.sidebar_prog_track.pack_propagate(False)
            self.sidebar_prog_bar = tk.Frame(self.sidebar_prog_track, bg=self.c_emerald_strong, height=5, width=190)
            self.sidebar_prog_bar.pack(side="left", fill="y")

            gpus = get_gpu_info()
            gpu_name = gpus[0]["name"] if gpus else "Detecting GPU..."
            if len(gpu_name) > 28:
                gpu_name = gpu_name[:26] + "..."
            self.lbl_gpu_footer = tk.Label(
                self.sidebar_status_card,
                text=gpu_name,
                bg=self.c_surface2,
                fg=self.c_muted,
                font=("Sans", 9, "bold"),
                anchor="w",
            )
            self.lbl_gpu_footer.pack(fill="x", pady=(0, 2))

            self.lbl_sidebar_ver_tag = tk.Label(
                self.sidebar_status_card,
                text="D3D12 Compute • Standalone",
                bg=self.c_surface2,
                fg=self.c_dim,
                font=("Sans", 8),
                anchor="w",
            )
            self.lbl_sidebar_ver_tag.pack(fill="x")

            for w in (
                self.sidebar_status_card,
                status_top,
                self.dot_sidebar_status,
                self.lbl_sidebar_status,
                self.sidebar_prog_track,
                self.sidebar_prog_bar,
                self.lbl_gpu_footer,
                self.lbl_sidebar_ver_tag,
            ):
                w.bind("<Button-1>", lambda _e: self._switch_tab("core"))

        def _create_nav_item(self, parent, tab_key, icon, label, badge_type=None):
            frame = tk.Frame(
                parent,
                bg=self.c_sidebar,
                highlightbackground=self.c_sidebar,
                highlightthickness=1,
                padx=10,
                pady=8,
                cursor="hand2",
            )
            frame.pack(fill="x", pady=2)

            dot_lbl = tk.Label(
                frame,
                text="●",
                bg=self.c_sidebar,
                fg=self.c_emerald,
                font=("Sans", 8, "bold"),
            )
            dot_lbl.pack(side="left", padx=(0, 6))

            icon_lbl = tk.Label(frame, text=icon, bg=self.c_sidebar, fg=self.c_muted, font=("Sans", 11))
            icon_lbl.pack(side="left", padx=(0, 8))

            text_lbl = tk.Label(
                frame,
                text=label,
                bg=self.c_sidebar,
                fg=self.c_muted,
                font=("Sans", 10, "bold"),
                anchor="w",
            )
            text_lbl.pack(side="left", fill="x", expand=True)

            badge_widget = None
            badge_inner = None
            if badge_type == "count":
                badge_widget = tk.Frame(frame, bg=self.c_emerald_bg, padx=6, pady=1)
                badge_widget.pack(side="right")
                badge_inner = tk.Label(
                    badge_widget,
                    text="0",
                    bg=self.c_emerald_bg,
                    fg=self.c_emerald,
                    font=("Sans", 9, "bold"),
                )
                badge_inner.pack()
                self.lbl_game_count_badge = badge_inner
            elif badge_type == "dot":
                badge_inner = tk.Label(
                    frame,
                    text="●",
                    bg=self.c_sidebar,
                    fg=self.c_amber,
                    font=("Sans", 9, "bold"),
                )
                badge_inner.pack(side="right")
                self.dot_core_nav = badge_inner

            self.nav_items_ui[tab_key] = {
                "frame": frame,
                "dot": dot_lbl,
                "icon": icon_lbl,
                "text": text_lbl,
                "badge_wrap": badge_widget,
                "badge_inner": badge_inner,
                "badge_type": badge_type,
            }

            click_targets = [frame, dot_lbl, icon_lbl, text_lbl]
            if badge_widget:
                click_targets.append(badge_widget)
            if badge_inner:
                click_targets.append(badge_inner)
            for w in click_targets:
                w.bind("<Button-1>", lambda _e, k=tab_key: self._switch_tab(k))

        def _update_nav_visuals(self):
            for key, item in self.nav_items_ui.items():
                active = key == self.current_tab
                bg = self.c_emerald_bg if active else self.c_sidebar
                bd = self.c_border_strong if active else self.c_sidebar
                fg = self.c_text if active else self.c_muted
                item["frame"].configure(bg=bg, highlightbackground=bd)
                item["dot"].configure(bg=bg, fg=self.c_emerald if active else bg)
                item["icon"].configure(bg=bg, fg=fg)
                item["text"].configure(bg=bg, fg=fg)
                if item["badge_type"] == "dot" and item["badge_inner"]:
                    item["badge_inner"].configure(bg=bg)

        # --------------------------------------------------------------------
        # TOPBAR UI (Matches BuildTopBar in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_topbar(self, parent):
            bar = tk.Frame(
                parent,
                bg=self.c_sidebar,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=18,
                pady=10,
            )
            bar.pack(side="top", fill="x")

            # Right Action Buttons: ＋ Add Game | ↻ Rescan | ⚡ Install All | ↩ Restore All | ☰ List | ☀️ Light | 🎮 Handheld
            right_wrap = tk.Frame(bar, bg=self.c_sidebar)
            right_wrap.pack(side="right")

            self._make_btn(right_wrap, "＋ Add Game", self._prompt_add_custom_folder, bg=self.c_card_hover, fg=self.c_text).pack(side="left", padx=(0, 6))
            self._make_btn(right_wrap, "↻ Rescan", lambda: (self._rescan_games(keep_selection=True), self._show_toast("Game library rescanned")), bg=self.c_card_hover, fg=self.c_text).pack(side="left", padx=(0, 6))
            self._make_btn(
                right_wrap,
                "⚡ Install All",
                self._install_all_games,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
            ).pack(side="left", padx=(0, 6))
            self._make_btn(right_wrap, "↩ Restore All", self._uninstall_all_games, bg=self.c_card_hover, fg=self.c_text).pack(side="left", padx=(0, 6))

            self.btn_toggle_view = self._make_btn(
                right_wrap,
                "☰ List" if self.is_grid_view else "🔲 Grid",
                self._toggle_view_mode,
                bg=self.c_card_hover,
                fg=self.c_text,
            )
            self.btn_toggle_view.pack(side="left", padx=(0, 6))

            self.btn_theme = self._make_btn(
                right_wrap,
                "🌙 Dark" if self.is_light else "☀️ Light",
                self._toggle_theme,
                bg=self.c_card_hover,
                fg=self.c_text,
            )
            self.btn_theme.pack(side="left", padx=(0, 6))

            self.btn_handheld_toggle = self._make_btn(
                right_wrap,
                "🎮 Handheld: ON" if self.is_handheld_mode else "🎮 Handheld",
                self._toggle_handheld_mode,
                bg=self.c_emerald_bg if self.is_handheld_mode else self.c_card_hover,
                fg=self.c_text,
                border=self.c_emerald if self.is_handheld_mode else self.c_border,
            )
            self.btn_handheld_toggle.pack(side="left")

            # Left Search & Dropdown Filters
            left_wrap = tk.Frame(bar, bg=self.c_sidebar)
            left_wrap.pack(side="left", fill="x", expand=True)

            # Search Box with Placeholder & Clear Button
            search_border = tk.Frame(
                left_wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=8,
                pady=4,
            )
            search_border.pack(side="left", padx=(0, 8))
            tk.Label(search_border, text="🔍", bg=self.c_card, fg=self.c_dim, font=("Sans", 10)).pack(side="left", padx=(0, 4))

            self.search_var = tk.StringVar()
            self.entry_search = tk.Entry(
                search_border,
                textvariable=self.search_var,
                bg=self.c_card,
                fg=self.c_text,
                insertbackground=self.c_emerald,
                bd=0,
                width=14,
                font=("Sans", 9),
            )
            self.entry_search.pack(side="left")

            self.btn_clear_search = tk.Button(
                search_border,
                text="✕",
                bg=self.c_card,
                fg=self.c_dim,
                bd=0,
                padx=4,
                pady=0,
                cursor="hand2",
                font=("Sans", 9, "bold"),
                command=self._clear_search,
            )
            self.search_var.trace_add("write", lambda *_: self._on_search_changed())

            # Dropdown Filters: Launcher | Status | Sort
            self.var_cmb_launcher = tk.StringVar(value="All Launchers")
            self.cmb_launcher = ttk.Combobox(
                left_wrap,
                textvariable=self.var_cmb_launcher,
                values=["All Launchers", "Steam", "Custom"],
                state="readonly",
                width=10,
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_launcher.pack(side="left", padx=(0, 5))
            self.cmb_launcher.bind("<<ComboboxSelected>>", lambda _e: self._apply_game_filters())

            self.var_cmb_status = tk.StringVar(value="All Status")
            self.cmb_status = ttk.Combobox(
                left_wrap,
                textvariable=self.var_cmb_status,
                values=["All Status", "HelixSR Active", "Not Installed"],
                state="readonly",
                width=10,
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_status.pack(side="left", padx=(0, 5))
            self.cmb_status.bind("<<ComboboxSelected>>", lambda _e: self._apply_game_filters())

            self.var_cmb_sort = tk.StringVar(value="Name (A-Z)")
            self.cmb_sort = ttk.Combobox(
                left_wrap,
                textvariable=self.var_cmb_sort,
                values=["Name (A-Z)", "Name (Z-A)", "Installed First"],
                state="readonly",
                width=9,
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_sort.pack(side="left")
            self.cmb_sort.bind("<<ComboboxSelected>>", lambda _e: self._apply_game_filters())

        def _clear_search(self):
            self.search_var.set("")
            self.entry_search.focus_set()

        def _on_search_changed(self):
            if self.search_var.get():
                self.btn_clear_search.pack(side="left")
            else:
                self.btn_clear_search.pack_forget()
            self._apply_game_filters()

        # --------------------------------------------------------------------
        # TAB 1: GAMES LIBRARY (Matches BuildGamesPane in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_games_pane(self, parent):
            # Split container: Left Area (Hero + Filter Pills + Grid/List) and Right Drawer
            self.games_left_area = tk.Frame(parent, bg=self.c_main_shell)
            self.games_left_area.pack(side="left", fill="both", expand=True)

            # Right-hand Slide-Over Drawer (450px wide, hidden until game clicked)
            self.drawer_frame = tk.Frame(
                parent,
                bg=self.c_sidebar,
                width=450,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            self._build_drawer_ui(self.drawer_frame)

            # 1. Hero Header + Live Stat Counter Chips
            hero_banner = tk.Frame(
                self.games_left_area,
                bg=self.c_hero_bg,
                highlightbackground=self.c_border_strong,
                highlightthickness=1,
                padx=18,
                pady=14,
            )
            hero_banner.pack(side="top", fill="x", padx=20, pady=(16, 10))

            # Right Live Stat Counter Chips
            stat_row = tk.Frame(hero_banner, bg=self.c_hero_bg)
            stat_row.pack(side="right", padx=(12, 0))
            self.lbl_stat_total = self._build_stat_chip(stat_row, "TOTAL GAMES", self.c_text)
            self.lbl_stat_active = self._build_stat_chip(stat_row, "HELIXSR ACTIVE", self.c_emerald)
            self.lbl_stat_direct = self._build_stat_chip(stat_row, "DIRECT FSR 3.1", self.c_sky)
            self.lbl_stat_opti = self._build_stat_chip(stat_row, "OPTISCALER", self.c_violet)

            # Left Hero Title + Badge + Subtitle
            banner_stack = tk.Frame(hero_banner, bg=self.c_hero_bg)
            banner_stack.pack(side="left", fill="x", expand=True)

            title_badge_row = tk.Frame(banner_stack, bg=self.c_hero_bg)
            title_badge_row.pack(fill="x", anchor="w")
            self.lbl_hero_title = tk.Label(
                title_badge_row,
                text="Neural Super Resolution Library",
                bg=self.c_hero_bg,
                fg=self.c_text,
                font=("Sans", 13, "bold"),
                anchor="w",
            )
            self.lbl_hero_title.pack(side="left")

            self.hero_drop_badge = tk.Frame(
                title_badge_row,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=8,
                pady=2,
            )
            self.hero_drop_badge.pack(side="left", padx=(10, 0))
            tk.Label(
                self.hero_drop_badge,
                text="📥 Drag & Drop Folders Supported",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 8, "bold"),
            ).pack()

            self.lbl_hero_subtitle = tk.Label(
                banner_stack,
                text="Swap native FSR 3.1 DLLs or inject OptiScaler hooks with DLSS Model E compute shaders & automatic REFramework nightly support.",
                bg=self.c_hero_bg,
                fg=self.c_muted,
                font=("Sans", 9),
                anchor="w",
                justify="left",
                wraplength=520,
            )
            self.lbl_hero_subtitle.pack(fill="x", pady=(4, 0))

            # 2. Interactive Quick-Filter Pill Bar (Matches 6 pills in MainWindow.cs)
            filter_pill_bar = tk.Frame(self.games_left_area, bg=self.c_main_shell, padx=20)
            filter_pill_bar.pack(side="top", fill="x", pady=(0, 10))

            self.filter_pill_btns = {}
            self.filter_pill_base_labels = [
                ("all", "All Games"),
                ("installed", "⚡ HelixSR Active"),
                ("uninstalled", "○ Not Installed"),
                ("direct", "🎯 Direct FSR 3.1"),
                ("optiscaler", "🔌 OptiScaler Hook"),
                ("reengine", "🧬 Capcom RE Engine"),
                ("unity", "🧩 Unity"),
            ]
            for fkey, flabel in self.filter_pill_base_labels:
                btn = tk.Button(
                    filter_pill_bar,
                    text=f"{flabel} (0)",
                    bd=0,
                    relief="flat",
                    padx=12,
                    pady=5,
                    cursor="hand2",
                    highlightthickness=1,
                    font=("Sans", 9, "bold"),
                    command=lambda k=fkey: self._set_quick_filter(k),
                )
                btn.pack(side="left", padx=(0, 8))
                self.filter_pill_btns[fkey] = btn
            self._update_filter_pill_visuals()

            # 3. Viewport Container for Empty State / Poster Grid View / List View
            self.games_viewport = tk.Frame(self.games_left_area, bg=self.c_main_shell)
            self.games_viewport.pack(side="top", fill="both", expand=True)

            # Empty State Panel
            self.empty_state_panel = tk.Frame(
                self.games_viewport,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=36,
                pady=36,
            )
            tk.Label(self.empty_state_panel, text="🎮", bg=self.c_card, fg=self.c_text, font=("Sans", 28)).pack(pady=(0, 8))
            tk.Label(
                self.empty_state_panel,
                text="No matching games in current view",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 12, "bold"),
            ).pack()
            tk.Label(
                self.empty_state_panel,
                text="Clear your active filters, click '＋ Add Game', or drag & drop any game folder here.",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 9),
            ).pack(pady=(4, 14))
            self._make_btn(
                self.empty_state_panel,
                "Reset Filters",
                self._reset_all_filters,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
            ).pack()

            # 4. Grid View (Scrollable Poster Grid)
            self.grid_scroll_wrap = tk.Frame(self.games_viewport, bg=self.c_main_shell, padx=14)
            self.games_canvas = tk.Canvas(self.grid_scroll_wrap, bg=self.c_main_shell, highlightthickness=0, bd=0)
            self.games_scrollbar = tk.Scrollbar(self.grid_scroll_wrap, orient="vertical", command=self.games_canvas.yview)
            self.games_inner = tk.Frame(self.games_canvas, bg=self.c_main_shell)

            self.games_inner.bind(
                "<Configure>",
                lambda _e: self.games_canvas.configure(scrollregion=self.games_canvas.bbox("all")),
            )
            self.games_canvas_win = self.games_canvas.create_window((0, 0), window=self.games_inner, anchor="nw")
            self.games_canvas.bind("<Configure>", self._on_games_canvas_resize)
            self.games_canvas.configure(yscrollcommand=self.games_scrollbar.set)

            self.games_canvas.pack(side="left", fill="both", expand=True)
            self.games_scrollbar.pack(side="right", fill="y")

            self.games_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.games_canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
            self.games_canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

            # 5. List View (Matches _listGamesView columns: Game Title, Launcher, Method, HelixSR Status, Directory)
            self.list_view_wrap = tk.Frame(
                self.games_viewport,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            cols = ("name", "launcher", "method", "status", "folder")
            self.tree_games = ttk.Treeview(
                self.list_view_wrap,
                columns=cols,
                show="headings",
                style="Helix.Treeview",
                selectmode="browse",
            )
            self.tree_games.heading("name", text="Game Title", anchor="w")
            self.tree_games.heading("launcher", text="Launcher", anchor="w")
            self.tree_games.heading("method", text="Method", anchor="w")
            self.tree_games.heading("status", text="HelixSR Status", anchor="w")
            self.tree_games.heading("folder", text="Directory", anchor="w")

            self.tree_games.column("name", width=260, anchor="w")
            self.tree_games.column("launcher", width=85, anchor="w")
            self.tree_games.column("method", width=165, anchor="w")
            self.tree_games.column("status", width=130, anchor="w")
            self.tree_games.column("folder", width=320, anchor="w")

            tree_scroll = tk.Scrollbar(self.list_view_wrap, orient="vertical", command=self.tree_games.yview)
            self.tree_games.configure(yscrollcommand=tree_scroll.set)
            self.tree_games.pack(side="left", fill="both", expand=True)
            tree_scroll.pack(side="right", fill="y")

            self.tree_games.bind("<<TreeviewSelect>>", self._on_tree_select)
            self.tree_games.bind("<Double-1>", self._on_tree_activate)
            self.tree_games.bind("<Return>", self._on_tree_activate)
            self.tree_games.bind("<space>", self._on_tree_activate)

        def _build_stat_chip(self, parent, label, val_color):
            chip = tk.Frame(
                parent,
                bg=self.c_sidebar,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=12,
                pady=6,
            )
            chip.pack(side="left", padx=(8, 0))
            val_lbl = tk.Label(
                chip,
                text="0",
                bg=self.c_sidebar,
                fg=val_color,
                font=("Sans", 12, "bold"),
            )
            val_lbl.pack()
            tk.Label(
                chip,
                text=label,
                bg=self.c_sidebar,
                fg=self.c_dim,
                font=("Sans", 7, "bold"),
            ).pack()
            return val_lbl

        def _reset_all_filters(self):
            self.quick_filter = "all"
            self.search_var.set("")
            self.var_cmb_launcher.set("All Launchers")
            self.var_cmb_status.set("All Status")
            self._update_filter_pill_visuals()
            self._apply_game_filters()

        def _set_quick_filter(self, fkey):
            self.quick_filter = fkey
            self._update_filter_pill_visuals()
            self._apply_game_filters()

        def _update_filter_pill_visuals(self):
            for fkey, btn in self.filter_pill_btns.items():
                active = fkey == self.quick_filter
                btn.configure(
                    bg=self.c_emerald_bg if active else self.c_card,
                    fg=self.c_emerald if active else self.c_muted,
                    highlightbackground=self.c_border_strong if active else self.c_border,
                    activebackground=self.c_emerald_bg,
                    activeforeground=self.c_emerald,
                )

        def _on_games_canvas_resize(self, event):
            self.games_canvas.itemconfig(self.games_canvas_win, width=event.width)
            prev_cols = getattr(self, "_last_grid_cols", 0)
            new_cols = max(1, event.width // 222)
            if new_cols != prev_cols and self.is_grid_view and self.filtered_games:
                self._last_grid_cols = new_cols
                self._render_games_grid_only()

        def _on_mousewheel(self, event):
            if self.current_tab == "games" and self.is_grid_view:
                self.games_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(self, event):
            if self.current_tab == "games" and self.is_grid_view:
                if event.num == 4:
                    self.games_canvas.yview_scroll(-3, "units")
                elif event.num == 5:
                    self.games_canvas.yview_scroll(3, "units")

        # --------------------------------------------------------------------
        # ARTWORK & COVER DECODER (Supports Steam .jpg/.png -> PPM PhotoImage)
        # --------------------------------------------------------------------
        def _load_photo_image(self, img_path, target_w, target_h):
            if not img_path or not os.path.isfile(img_path):
                return None
            cache_key = (img_path, target_w, target_h)
            if cache_key in self._image_cache:
                return self._image_cache[cache_key]

            cache_dir = os.path.join(get_data_dir(), "cache", "ppm")
            os.makedirs(cache_dir, exist_ok=True)
            key_hash = base64.urlsafe_b64encode(f"{img_path}:{target_w}x{target_h}".encode("utf-8")).decode("ascii").rstrip("=")
            if len(key_hash) > 90:
                key_hash = key_hash[-90:]
            ppm_path = os.path.join(cache_dir, f"{key_hash}.ppm")

            if not os.path.isfile(ppm_path):
                # Convert JPEG/PNG cover to scaled PPM using PIL, ffmpeg, magick/convert, or djpeg+pnmscale
                converted = False
                try:
                    from PIL import Image
                    with Image.open(img_path) as im:
                        im = im.convert("RGB")
                        src_w, src_h = im.size
                        scale = max(target_w / max(1, src_w), target_h / max(1, src_h))
                        nw, nh = max(1, int(src_w * scale)), max(1, int(src_h * scale))
                        im = im.resize((nw, nh))
                        left = max(0, (nw - target_w) // 2)
                        top = max(0, (nh - target_h) // 2)
                        im = im.crop((left, top, left + target_w, top + target_h))
                        im.save(ppm_path, format="PPM")
                        converted = True
                except Exception:
                    pass

                if not converted and shutil.which("ffmpeg"):
                    try:
                        vf = f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase,crop={target_w}:{target_h}"
                        subprocess.run(
                            ["ffmpeg", "-y", "-loglevel", "quiet", "-i", img_path, "-vf", vf, "-frames:v", "1", ppm_path],
                            timeout=3,
                            check=False,
                            env=get_clean_desktop_env(),
                        )
                        converted = os.path.isfile(ppm_path) and os.path.getsize(ppm_path) > 100
                    except Exception:
                        pass

                if not converted:
                    for magick_bin in ("magick", "convert"):
                        if shutil.which(magick_bin):
                            try:
                                subprocess.run(
                                    [magick_bin, img_path, "-resize", f"{target_w}x{target_h}^", "-gravity", "center", "-extent", f"{target_w}x{target_h}", ppm_path],
                                    timeout=3,
                                    check=False,
                                    env=get_clean_desktop_env(),
                                )
                                converted = os.path.isfile(ppm_path) and os.path.getsize(ppm_path) > 100
                                if converted:
                                    break
                            except Exception:
                                pass

            target_file = ppm_path if (os.path.isfile(ppm_path) and os.path.getsize(ppm_path) > 100) else img_path
            try:
                photo = tk.PhotoImage(file=target_file)
                self._image_cache[cache_key] = photo
                return photo
            except Exception:
                self._image_cache[cache_key] = None
                return None

        def _ensure_remote_artwork_async(self, game, kind="cover"):
            appid = game.get("appId")
            art = game.get(kind)
            if not appid or not art:
                return None
            if art.get("type") == "local" and os.path.isfile(art.get("path", "")):
                return art["path"]

            cache_dir = os.path.join(get_data_dir(), "cache", "covers")
            os.makedirs(cache_dir, exist_ok=True)
            cache_file = os.path.join(cache_dir, f"{appid}_{kind}.jpg")
            if os.path.isfile(cache_file) and os.path.getsize(cache_file) > 1000:
                return cache_file

            downloading_set = getattr(self, "_downloading_art", set())
            self._downloading_art = downloading_set
            dl_key = f"{appid}_{kind}"
            if dl_key in downloading_set:
                return None
            downloading_set.add(dl_key)

            def bg_dl():
                urls = [
                    art.get("url", ""),
                    f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_600x900.jpg"
                    if kind == "cover"
                    else f"https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/library_hero.jpg",
                    f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_600x900.jpg"
                    if kind == "cover"
                    else f"https://steamcdn-a.akamaihd.net/steam/apps/{appid}/library_hero.jpg",
                ]
                for u in urls:
                    if not u:
                        continue
                    try:
                        req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
                        with urllib.request.urlopen(req, timeout=8) as resp:
                            data = resp.read()
                        if data and len(data) > 1000:
                            with open(cache_file, "wb") as f:
                                f.write(data)
                            try:
                                self.root.after(50, self._render_games_grid_only)
                            except Exception:
                                pass
                            break
                    except Exception:
                        pass

            threading.Thread(target=bg_dl, daemon=True).start()
            return None

        # --------------------------------------------------------------------
        # POSTER GAME CARDS & LIST VIEW (Matches BuildGameCard in MainWindow.cs)
        # --------------------------------------------------------------------
        def _update_filter_counts(self):
            total = len(self.all_games)
            active = sum(1 for g in self.all_games if g.get("installed"))
            uninstalled = total - active
            direct = sum(1 for g in self.all_games if g.get("route") == "direct")
            opti = total - direct
            re_engine = sum(1 for g in self.all_games if g.get("isReEngine"))
            unity = sum(1 for g in self.all_games if g.get("isUnity"))

            if hasattr(self, "lbl_game_count_badge"):
                self.lbl_game_count_badge.configure(text=str(total))
            self.lbl_stat_total.configure(text=str(total))
            self.lbl_stat_active.configure(text=str(active))
            self.lbl_stat_direct.configure(text=str(direct))
            self.lbl_stat_opti.configure(text=str(opti))

            counts_map = {
                "all": total,
                "installed": active,
                "uninstalled": uninstalled,
                "direct": direct,
                "optiscaler": opti,
                "reengine": re_engine,
                "unity": unity,
            }
            for fkey, flabel in self.filter_pill_base_labels:
                if fkey in self.filter_pill_btns:
                    self.filter_pill_btns[fkey].configure(text=f"{flabel} ({counts_map.get(fkey, 0)})")

        def _apply_game_filters(self):
            q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
            l_val = self.var_cmb_launcher.get() if hasattr(self, "var_cmb_launcher") else "All Launchers"
            s_val = self.var_cmb_status.get() if hasattr(self, "var_cmb_status") else "All Status"
            sort_val = self.var_cmb_sort.get() if hasattr(self, "var_cmb_sort") else "Name (A-Z)"

            res = []
            for g in self.all_games:
                if q:
                    m_name = q in (g.get("name") or "").lower()
                    m_folder = q in (g.get("folder") or "").lower()
                    m_route = q in (g.get("routeDisplay") or "").lower()
                    if not (m_name or m_folder or m_route):
                        continue
                if l_val == "Steam" and g.get("launcher") != "Steam":
                    continue
                if l_val == "Custom" and g.get("launcher") != "Custom":
                    continue
                if s_val == "HelixSR Active" and not g.get("installed"):
                    continue
                if s_val == "Not Installed" and g.get("installed"):
                    continue

                if self.quick_filter == "installed" and not g.get("installed"):
                    continue
                if self.quick_filter == "uninstalled" and g.get("installed"):
                    continue
                if self.quick_filter == "direct" and g.get("route") != "direct":
                    continue
                if self.quick_filter == "optiscaler" and g.get("route") != "optiscaler":
                    continue
                if self.quick_filter == "reengine" and not g.get("isReEngine"):
                    continue
                if self.quick_filter == "unity" and not g.get("isUnity"):
                    continue

                res.append(g)

            if sort_val == "Name (A-Z)":
                res.sort(key=lambda x: (x.get("name") or "").lower())
            elif sort_val == "Name (Z-A)":
                res.sort(key=lambda x: (x.get("name") or "").lower(), reverse=True)
            elif sort_val == "Installed First":
                res.sort(key=lambda x: (not bool(x.get("installed")), (x.get("name") or "").lower()))

            self.filtered_games = res
            self._render_games()

        def _render_games(self):
            self._update_filter_counts()

            # Populate List View
            for item in self.tree_games.get_children():
                self.tree_games.delete(item)
            for idx, g in enumerate(self.filtered_games):
                status_disp = f"✔ Installed ({g.get('version') or CORE_VERSION})" if g.get("installed") else "Not Installed"
                self.tree_games.insert(
                    "",
                    "end",
                    iid=str(idx),
                    values=(
                        g.get("name") or "",
                        g.get("launcher") or "Custom",
                        g.get("routeDisplay") or "OptiScaler",
                        status_disp,
                        g.get("folder") or "",
                    ),
                )

            self.empty_state_panel.pack_forget()
            self.grid_scroll_wrap.pack_forget()
            self.list_view_wrap.pack_forget()

            if not self.filtered_games:
                self.empty_state_panel.pack(expand=True, pady=40)
                return

            if self.is_grid_view:
                self.grid_scroll_wrap.pack(fill="both", expand=True, pady=(0, 14))
                self._render_games_grid_only()
            else:
                self.list_view_wrap.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        def _render_games_grid_only(self):
            if not hasattr(self, "games_inner") or not self.games_inner.winfo_exists():
                return
            for child in self.games_inner.winfo_children():
                child.destroy()
            self._card_frames = []
            self._image_refs = []

            avail_w = self.games_canvas.winfo_width()
            if avail_w <= 100:
                avail_w = 960 if not self.selected_game else 520
            cols = max(1, avail_w // 222)
            self._last_grid_cols = cols

            for idx, g in enumerate(self.filtered_games):
                r = idx // cols
                c = idx % cols
                card = self._build_game_poster_card(self.games_inner, g, idx)
                card.grid(row=r, column=c, padx=9, pady=9, sticky="nw")
                self._card_frames.append(card)

        def _build_game_poster_card(self, parent, game, idx):
            is_installed = bool(game.get("installed"))
            is_focused = self.is_handheld_mode and idx == self.focused_index
            is_selected = self.selected_game and canonical_key(self.selected_game.get("folder")) == canonical_key(game.get("folder"))

            border_col = self.c_emerald_strong if (is_focused or is_selected or is_installed) else self.c_border
            border_thick = 3 if is_focused else (2 if (is_installed or is_selected) else 1)

            card = tk.Frame(
                parent,
                width=204,
                height=304,
                bg=self.c_card,
                highlightbackground=border_col,
                highlightthickness=border_thick,
                cursor="hand2",
            )
            card.pack_propagate(False)

            cv = tk.Canvas(card, width=200, height=300, bg="#141a24", highlightthickness=0, bd=0, cursor="hand2")
            cv.pack(fill="both", expand=True)

            # 1. Stylized Gradient Poster Backdrop or Steam Cover Image
            cover_path = self._ensure_remote_artwork_async(game, "cover")
            photo = self._load_photo_image(cover_path, 204, 304) if cover_path else None
            if photo:
                self._image_refs.append(photo)
                cv.create_image(102, 152, image=photo, anchor="center")
            else:
                # Stylized dark gradient fallback matching MainWindow.cs fallback container
                bands = ("#1a212e", "#181f2b", "#161c27", "#131923", "#10151e", "#0e121a")
                bh = 304 // len(bands) + 1
                for bi, bcol in enumerate(bands):
                    cv.create_rectangle(0, bi * bh, 204, (bi + 1) * bh, fill=bcol, outline="")
                cv.create_text(
                    102,
                    138,
                    text=game.get("name") or "Game",
                    fill="#ffffff",
                    font=("Sans", 11, "bold"),
                    width=172,
                    justify="center",
                )

            # 2. Top Badges (Launcher + DLSS/DLSS-G/XeSS/FSR 2 + RE badge)
            bx, by = 9, 9
            badges = [(game.get("launcher") or "Steam", "#080c12", "#ffffff")]
            for inp in game.get("inputs") or []:
                if inp == "DLSS":
                    badges.append(("DLSS", self.c_emerald_strong, self.c_on_accent))
                elif inp == "DLSS-G":
                    badges.append(("DLSS-G", self.c_amber, self.c_on_accent))
                elif inp == "XeSS":
                    badges.append(("XeSS", self.c_sky, "#ffffff"))
                else:
                    badges.append((inp, self.c_violet, "#ffffff"))
            if game.get("isReEngine"):
                badges.append(("RE", "#b42828", "#ffffff"))
            if game.get("isInZoi"):
                badges.append(("inZOI", "#7c3aed", "#ffffff"))
            if game.get("isUnity"):
                badges.append(("Unity", "#374151", "#ffffff"))

            for b_txt, b_bg, b_fg in badges:
                tw = max(28, len(b_txt) * 7 + 12)
                if bx + tw > 195:
                    bx = 9
                    by += 22
                cv.create_rectangle(bx, by, bx + tw, by + 18, fill=b_bg, outline="#2e3a4e", width=1)
                cv.create_text(bx + tw // 2, by + 9, text=b_txt, fill=b_fg, font=("Sans", 8, "bold"))
                bx += tw + 4

            # 3. Hover Quick-Action Pill Overlay (hidden until hover)
            hover_txt = "⚙️ Configure HelixSR" if is_installed else "⚡ Setup & Install"
            hover_rect = cv.create_rectangle(
                32, 134, 172, 164,
                fill="#0c1018",
                outline=self.c_emerald,
                width=1,
                state="hidden",
            )
            hover_lbl = cv.create_text(
                102, 149,
                text=hover_txt,
                fill=self.c_emerald,
                font=("Sans", 9, "bold"),
                state="hidden",
            )

            # 4. Bottom Scrim & Metadata (Title, Status Dot + Active/Not Installed, RouteDisplay)
            cv.create_rectangle(0, 232, 204, 304, fill="#080b10", outline="")
            cv.create_line(0, 232, 204, 232, fill="#1e2735", width=1)

            title_str = game.get("name") or "Game"
            if len(title_str) > 24:
                title_str = title_str[:22] + "…"
            cv.create_text(
                12, 252,
                text=title_str,
                fill="#ffffff",
                font=("Sans", 10, "bold"),
                anchor="w",
            )

            dot_col = self.c_emerald if is_installed else "#64748b"
            status_str = "Active" if is_installed else "Not Installed"
            status_col = self.c_emerald if is_installed else "#94a3b8"
            cv.create_oval(12, 276, 18, 282, fill=dot_col, outline="")
            cv.create_text(23, 279, text=status_str, fill=status_col, font=("Sans", 8, "bold"), anchor="w")

            route_str = game.get("routeDisplay") or "OptiScaler"
            if len(route_str) > 18:
                route_str = route_str[:16] + "…"
            cv.create_text(
                192, 279,
                text=route_str,
                fill="#94a3b8",
                font=("Sans", 8),
                anchor="e",
            )

            def on_enter(_e):
                card.configure(highlightbackground=self.c_emerald)
                cv.itemconfigure(hover_rect, state="normal")
                cv.itemconfigure(hover_lbl, state="normal")

            def on_leave(_e):
                card.configure(highlightbackground=border_col)
                cv.itemconfigure(hover_rect, state="hidden")
                cv.itemconfigure(hover_lbl, state="hidden")

            cv.bind("<Enter>", on_enter)
            cv.bind("<Leave>", on_leave)
            cv.bind("<Button-1>", lambda _e, g=game, i=idx: self._open_drawer(g, i))
            cv.bind("<Button-3>", lambda e, g=game, i=idx: self._show_card_context_menu(e, g, i))
            return card

        def _show_card_context_menu(self, event, game, idx):
            menu = tk.Menu(
                self.root,
                tearoff=0,
                bg=self.c_sidebar,
                fg=self.c_text,
                activebackground=self.c_card_hover,
                activeforeground=self.c_emerald,
                font=("Sans", 9),
            )
            menu.add_command(label="⚙️  Configure & Choose Method...", command=lambda: self._open_drawer(game, idx))
            inst_lbl = "⚡  Update / Reinstall HelixSR" if game.get("installed") else "⚡  Quick Install HelixSR"
            menu.add_command(label=inst_lbl, command=lambda: (self._open_drawer(game, idx), self._on_install_clicked()))
            if game.get("installed"):
                menu.add_command(
                    label="↩  Restore Original Files (Uninstall)",
                    command=lambda: (self._open_drawer(game, idx), self._on_uninstall_clicked()),
                )
            menu.add_command(label="🧹  Clear Shader Cache", command=lambda: (self._open_drawer(game, idx), self._on_clear_shader_cache_clicked()))
            menu.add_command(label="▶  Launch Game", command=lambda: (self._open_drawer(game, idx), self._on_launch_clicked()))
            menu.add_command(label="📁  Open Game Folder", command=lambda: open_folder_native(game.get("exeFolder") or game.get("folder")))
            menu.add_command(
                label="📋  Copy Folder Path",
                command=lambda: self._copy_to_clipboard(game.get("exeFolder") or game.get("folder"), "Copied path"),
            )
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        def _on_tree_select(self, _event):
            sel = self.tree_games.selection()
            if sel:
                try:
                    idx = int(sel[0])
                    if 0 <= idx < len(self.filtered_games):
                        self.focused_index = idx
                except Exception:
                    pass

        def _on_tree_activate(self, _event):
            sel = self.tree_games.selection()
            if sel:
                try:
                    idx = int(sel[0])
                    if 0 <= idx < len(self.filtered_games):
                        self._open_drawer(self.filtered_games[idx], idx)
                except Exception:
                    pass

        def _toggle_view_mode(self):
            self.is_grid_view = not self.is_grid_view
            self.btn_toggle_view.configure(text="☰ List" if self.is_grid_view else "🔲 Grid")
            self._render_games()
            self._show_toast("🔲 Grid View" if self.is_grid_view else "☰ List View")

        # --------------------------------------------------------------------
        # RIGHT-HAND GAME DRAWER (Matches BuildDrawer in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_drawer_ui(self, parent):
            # 1. Top Hero Banner (160px high with thumbnail, title, badges, and close button)
            self.drawer_hero = tk.Frame(parent, bg=self.c_card, height=156)
            self.drawer_hero.pack(side="top", fill="x")
            self.drawer_hero.pack_propagate(False)

            hero_top_row = tk.Frame(self.drawer_hero, bg=self.c_card, padx=12, pady=8)
            hero_top_row.pack(side="top", fill="x")
            tk.Button(
                hero_top_row,
                text="✕",
                bg="#0a0e14",
                fg="#ffffff",
                activebackground=self.c_emerald_strong,
                activeforeground=self.c_on_accent,
                highlightbackground=self.c_border,
                highlightthickness=1,
                bd=0,
                padx=8,
                pady=2,
                cursor="hand2",
                font=("Sans", 9, "bold"),
                command=self._close_drawer,
            ).pack(side="right")

            hero_overlay = tk.Frame(self.drawer_hero, bg=self.c_card, padx=18, pady=6)
            hero_overlay.pack(side="bottom", fill="x")

            self.drawer_thumb_box = tk.Frame(
                hero_overlay,
                bg=self.c_surface2,
                width=54,
                height=78,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            self.drawer_thumb_box.pack(side="left", padx=(0, 14))
            self.drawer_thumb_box.pack_propagate(False)
            self.lbl_drawer_thumb = tk.Label(self.drawer_thumb_box, text="🎮", bg=self.c_surface2, fg=self.c_emerald, font=("Sans", 18))
            self.lbl_drawer_thumb.pack(expand=True, fill="both")

            meta_stack = tk.Frame(hero_overlay, bg=self.c_card)
            meta_stack.pack(side="left", fill="x", expand=True)

            self.lbl_drawer_title = tk.Label(
                meta_stack,
                text="Game Title",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 13, "bold"),
                anchor="w",
                justify="left",
                wraplength=330,
            )
            self.lbl_drawer_title.pack(fill="x")

            badge_stack = tk.Frame(meta_stack, bg=self.c_card)
            badge_stack.pack(fill="x", pady=(6, 0))

            pill_plat = tk.Frame(badge_stack, bg=self.c_sidebar, highlightbackground=self.c_border, highlightthickness=1, padx=7, pady=2)
            pill_plat.pack(side="left", padx=(0, 6))
            self.lbl_drawer_platform = tk.Label(pill_plat, text="Steam", bg=self.c_sidebar, fg=self.c_blue, font=("Sans", 8, "bold"))
            self.lbl_drawer_platform.pack()

            pill_route = tk.Frame(badge_stack, bg=self.c_sidebar, highlightbackground=self.c_border, highlightthickness=1, padx=7, pady=2)
            pill_route.pack(side="left", padx=(0, 6))
            self.lbl_drawer_route = tk.Label(pill_route, text="OptiScaler", bg=self.c_sidebar, fg=self.c_sky, font=("Sans", 8, "bold"))
            self.lbl_drawer_route.pack()

            self.pill_drawer_status = tk.Frame(badge_stack, bg=self.c_emerald_bg, highlightbackground=self.c_border_strong, highlightthickness=1, padx=7, pady=2)
            self.pill_drawer_status.pack(side="left")
            self.lbl_drawer_status = tk.Label(self.pill_drawer_status, text="Installed", bg=self.c_emerald_bg, fg=self.c_emerald, font=("Sans", 8, "bold"))
            self.lbl_drawer_status.pack()

            tk.Frame(parent, bg=self.c_border, height=1).pack(side="top", fill="x")

            # Scrollable Drawer Body
            content_stack = tk.Frame(parent, bg=self.c_sidebar, padx=18, pady=12)
            content_stack.pack(side="top", fill="both", expand=True)

            # 2. Installation Method & Hooks Box (Matches methodBox in BuildDrawer)
            method_box = tk.Frame(
                content_stack,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=14,
                pady=12,
            )
            method_box.pack(fill="x", pady=(0, 10))

            tk.Label(
                method_box,
                text="INSTALLATION METHOD & HOOKS",
                bg=self.c_card,
                fg=self.c_emerald,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))

            self.var_drawer_method = tk.StringVar()
            self.cmb_drawer_method = ttk.Combobox(
                method_box,
                textvariable=self.var_drawer_method,
                state="readonly",
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_drawer_method.pack(fill="x", pady=(0, 6))
            self.cmb_drawer_method.bind("<<ComboboxSelected>>", lambda _e: self._on_drawer_method_changed())

            self.lbl_drawer_method_hint = tk.Label(
                method_box,
                text="",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 8),
                justify="left",
                anchor="w",
                wraplength=380,
            )
            self.lbl_drawer_method_hint.pack(fill="x", pady=(0, 8))

            self.panel_drawer_fg = tk.Frame(method_box, bg=self.c_card)
            self.panel_drawer_fg.pack(fill="x", pady=(0, 6))
            tk.Label(
                self.panel_drawer_fg,
                text="FRAME GENERATION (DLSS-G HOOK / OPTIFG)",
                bg=self.c_card,
                fg=self.c_emerald,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 4))

            self.var_drawer_fg = tk.StringVar()
            self.cmb_drawer_fg = ttk.Combobox(
                self.panel_drawer_fg,
                textvariable=self.var_drawer_fg,
                state="readonly",
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_drawer_fg.pack(fill="x")
            self.cmb_drawer_fg.bind("<<ComboboxSelected>>", lambda _e: self._on_drawer_fg_changed())

            self.var_chk_fakenvapi = tk.BooleanVar(value=True)
            self.chk_drawer_fakenvapi = tk.Checkbutton(
                method_box,
                text="Deploy FakeNVAPI (fakenvapi.dll) to unlock DLSS & DLSS-G on AMD/Intel GPUs",
                variable=self.var_chk_fakenvapi,
                bg=self.c_card,
                fg=self.c_text,
                selectcolor=self.c_surface2,
                activebackground=self.c_card,
                activeforeground=self.c_emerald,
                font=("Sans", 8),
                anchor="w",
                command=self._on_drawer_check_changed,
            )
            self.chk_drawer_fakenvapi.pack(fill="x", pady=(2, 2))

            self.var_chk_reframework = tk.BooleanVar(value=False)
            self.chk_drawer_reframework = tk.Checkbutton(
                method_box,
                text="Install REFramework Nightly (dinput8.dll) for Capcom RE Engine",
                variable=self.var_chk_reframework,
                bg=self.c_card,
                fg=self.c_text,
                selectcolor=self.c_surface2,
                activebackground=self.c_card,
                activeforeground=self.c_emerald,
                font=("Sans", 8),
                anchor="w",
                command=self._on_drawer_check_changed,
            )
            self.chk_drawer_reframework.pack(fill="x")

            # 3. Primary Actions Bar (3 columns: ⚡ Install HelixSR | ↩ Restore | ▶ Launch Game)
            actions_bar = tk.Frame(content_stack, bg=self.c_sidebar)
            actions_bar.pack(fill="x", pady=(0, 8))
            for col in range(3):
                actions_bar.grid_columnconfigure(col, weight=1, uniform="actcol")

            self.btn_drawer_install = self._make_btn(
                actions_bar,
                "⚡ Install HelixSR",
                self._on_install_clicked,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
            )
            self.btn_drawer_install.grid(row=0, column=0, sticky="ew", padx=(0, 4))

            self.btn_drawer_uninstall = self._make_btn(
                actions_bar,
                "↩ Restore",
                self._on_uninstall_clicked,
                bg=self.c_red,
                fg="#ffffff",
                border=self.c_red,
            )
            self.btn_drawer_uninstall.grid(row=0, column=1, sticky="ew", padx=2)

            self.btn_drawer_launch = self._make_btn(
                actions_bar,
                "▶ Launch Game",
                self._on_launch_clicked,
                bg=self.c_card_hover,
                fg=self.c_text,
            )
            self.btn_drawer_launch.grid(row=0, column=2, sticky="ew", padx=(4, 0))

            # 4. Folder Shortcuts & Maintenance (4 columns: 📁 Folder | 📂 Backups | 📦 my-fsr | 🧹 Cache)
            shortcuts_bar = tk.Frame(content_stack, bg=self.c_sidebar)
            shortcuts_bar.pack(fill="x", pady=(0, 10))
            for col in range(4):
                shortcuts_bar.grid_columnconfigure(col, weight=1, uniform="sccol")

            self._make_btn(
                shortcuts_bar,
                "📁 Folder",
                lambda: self._open_selected_subfolder(""),
                bg=self.c_card,
                fg=self.c_text,
                padx=6,
            ).grid(row=0, column=0, sticky="ew", padx=(0, 3))
            self._make_btn(
                shortcuts_bar,
                "📂 Backups",
                lambda: self._open_selected_subfolder(os.path.join("HelixSR", "backup")),
                bg=self.c_card,
                fg=self.c_text,
                padx=6,
            ).grid(row=0, column=1, sticky="ew", padx=2)
            self._make_btn(
                shortcuts_bar,
                "📦 my-fsr",
                lambda: self._open_selected_subfolder(os.path.join("HelixSR", "my-fsr")),
                bg=self.c_card,
                fg=self.c_text,
                padx=6,
            ).grid(row=0, column=2, sticky="ew", padx=2)
            self._make_btn(
                shortcuts_bar,
                "🧹 Cache",
                self._on_clear_shader_cache_clicked,
                bg=self.c_card,
                fg=self.c_text,
                padx=6,
            ).grid(row=0, column=3, sticky="ew", padx=(3, 0))

            # 5. Target Game Telemetry Card (Executable, Location, Detected APIs, Active Route)
            prop_box = tk.Frame(
                content_stack,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=12,
                pady=8,
            )
            prop_box.pack(fill="x", pady=(0, 10))
            self.lbl_prop_exe = self._add_prop_row(prop_box, "Executable:", "-")
            self.lbl_prop_folder = self._add_prop_row(prop_box, "Location:", "-")
            self.lbl_prop_inputs = self._add_prop_row(prop_box, "Detected APIs:", "-")
            self.lbl_prop_method = self._add_prop_row(prop_box, "Active Route:", "-")

            # 6. Segmented Pill Tab Bar (📘 Setup Guide | ⚙️ OptiScaler.ini | 📋 Logs)
            seg_bar = tk.Frame(
                content_stack,
                bg=self.c_surface2,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=4,
                pady=4,
            )
            seg_bar.pack(fill="x", pady=(0, 8))
            for col in range(3):
                seg_bar.grid_columnconfigure(col, weight=1, uniform="segcol")

            self.drawer_seg_btns = {}
            for col, (tid, tlabel) in enumerate(
                (("guide", "📘 Setup Guide"), ("ini", "⚙️ OptiScaler.ini"), ("logs", "📋 Logs"))
            ):
                b = tk.Button(
                    seg_bar,
                    text=tlabel,
                    bd=0,
                    relief="flat",
                    pady=4,
                    cursor="hand2",
                    highlightthickness=1,
                    font=("Sans", 8, "bold"),
                    command=lambda k=tid: self._switch_drawer_tab(k),
                )
                b.grid(row=0, column=col, sticky="ew", padx=2)
                self.drawer_seg_btns[tid] = b

            # Tab Panes Container
            self.drawer_tabs_host = tk.Frame(content_stack, bg=self.c_sidebar)
            self.drawer_tabs_host.pack(fill="both", expand=True)

            # Tab 1: Setup Guide (+ Proton Launch Option copy bar on Linux/SteamOS)
            self.dpane_guide = tk.Frame(
                self.drawer_tabs_host,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=12,
                pady=10,
            )
            self.lbl_drawer_guide = tk.Label(
                self.dpane_guide,
                text="",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 9),
                justify="left",
                anchor="nw",
                wraplength=380,
            )
            self.lbl_drawer_guide.pack(fill="x")

            self.proton_bar = tk.Frame(self.dpane_guide, bg=self.c_surface2, padx=8, pady=6)
            self.proton_bar.pack(fill="x", pady=(8, 0))
            tk.Label(
                self.proton_bar,
                text="STEAM LAUNCH OPTION:",
                bg=self.c_surface2,
                fg=self.c_emerald,
                font=("Sans", 7, "bold"),
                anchor="w",
            ).pack(fill="x")
            p_row = tk.Frame(self.proton_bar, bg=self.c_surface2)
            p_row.pack(fill="x", pady=(2, 0))
            self.proton_cmd_var = tk.StringVar()
            tk.Entry(
                p_row,
                textvariable=self.proton_cmd_var,
                bg=self.c_card,
                fg=self.c_text,
                readonlybackground=self.c_card,
                bd=0,
                font=("Monospace", 8),
                state="readonly",
            ).pack(side="left", fill="x", expand=True, ipady=3, padx=(0, 6))
            self._make_btn(
                p_row,
                "📋 Copy",
                lambda: self._copy_to_clipboard(self.proton_cmd_var.get(), "Copied Steam Launch Option"),
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                padx=8,
                pady=2,
                font_size=8,
            ).pack(side="right")

            # Tab 2: OptiScaler.ini Editor
            self.dpane_ini = tk.Frame(
                self.drawer_tabs_host,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=12,
                pady=10,
            )
            ini_top = tk.Frame(self.dpane_ini, bg=self.c_card)
            ini_top.pack(fill="x", pady=(0, 6))
            tk.Label(
                ini_top,
                text="OptiScaler Configuration",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 9, "bold"),
            ).pack(side="left")
            self._make_btn(
                ini_top,
                "💾 Save INI Changes",
                self._on_save_ini_clicked,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
                padx=10,
                pady=3,
                font_size=8,
            ).pack(side="right")
            self.txt_ini_editor = tk.Text(
                self.dpane_ini,
                height=8,
                bg="#0a0d12",
                fg=self.c_emerald_strong,
                insertbackground="#ffffff",
                font=("Monospace", 9),
                bd=0,
                padx=8,
                pady=6,
                wrap="none",
            )
            self.txt_ini_editor.pack(fill="both", expand=True)

            # Tab 3: Logs & Diagnostics
            self.dpane_logs = tk.Frame(
                self.drawer_tabs_host,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=12,
                pady=10,
            )
            log_top = tk.Frame(self.dpane_logs, bg=self.c_card)
            log_top.pack(fill="x", pady=(0, 6))
            tk.Label(
                log_top,
                text="Runtime Telemetry",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 9, "bold"),
            ).pack(side="left")
            self._make_btn(
                log_top,
                "↻ Refresh",
                lambda: (self._refresh_drawer_logs(), self._show_toast("Logs refreshed")),
                bg=self.c_card_hover,
                fg=self.c_text,
                padx=8,
                pady=2,
                font_size=8,
            ).pack(side="right")
            self._make_btn(
                log_top,
                "📋 Copy",
                lambda: self._copy_to_clipboard(self.txt_log_output.get("1.0", "end-1c"), "Diagnostic logs copied to clipboard"),
                bg=self.c_card_hover,
                fg=self.c_text,
                padx=8,
                pady=2,
                font_size=8,
            ).pack(side="right", padx=(0, 6))
            self.txt_log_output = tk.Text(
                self.dpane_logs,
                height=8,
                bg="#0a0d12",
                fg="#cbd5e1",
                font=("Monospace", 8),
                bd=0,
                padx=8,
                pady=6,
                wrap="word",
            )
            self.txt_log_output.pack(fill="both", expand=True)

            self._switch_drawer_tab(self.drawer_tab)

        def _add_prop_row(self, parent, label, def_val):
            row = tk.Frame(parent, bg=self.c_card)
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=label,
                bg=self.c_card,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                width=14,
                anchor="w",
            ).pack(side="left")
            val_lbl = tk.Label(
                row,
                text=def_val,
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 8),
                anchor="w",
            )
            val_lbl.pack(side="left", fill="x", expand=True)
            return val_lbl

        def _switch_drawer_tab(self, tab):
            self.drawer_tab = tab
            for p in (self.dpane_guide, self.dpane_ini, self.dpane_logs):
                p.pack_forget()
            if tab == "guide":
                self.dpane_guide.pack(fill="both", expand=True)
            elif tab == "ini":
                self.dpane_ini.pack(fill="both", expand=True)
            elif tab == "logs":
                self.dpane_logs.pack(fill="both", expand=True)

            for tid, btn in self.drawer_seg_btns.items():
                active = tid == tab
                btn.configure(
                    bg=self.c_emerald_bg if active else self.c_surface2,
                    fg=self.c_emerald if active else self.c_muted,
                    highlightbackground=self.c_border_strong if active else self.c_surface2,
                )

        def _populate_drawer_method_options(self, game):
            self.updating_drawer = True
            try:
                has_native_fsr = bool(game.get("fsrTargets"))
                direct_label = (
                    "Direct FSR 3.1 Replacement (Native FSR 3.1 DLLs)"
                    if has_native_fsr
                    else "Direct FSR 3.1 Replacement (Standalone FidelityFX DLLs)"
                )
                opti_options = [
                    ("dxgi.dll", "OptiScaler Proxy — dxgi.dll (Recommended DLSS/XeSS/FSR2 Hook)"),
                    ("winmm.dll", "OptiScaler Proxy — winmm.dll (Compatibility Hook)"),
                    ("version.dll", "OptiScaler Proxy — version.dll (Alternative Hook)"),
                    ("dbghelp.dll", "OptiScaler Proxy — dbghelp.dll (Alternative Hook)"),
                    ("d3d12.dll", "OptiScaler Proxy — d3d12.dll (Direct3D 12 Hook)"),
                    ("wininet.dll", "OptiScaler Proxy — wininet.dll (Alternative Hook)"),
                    ("winhttp.dll", "OptiScaler Proxy — winhttp.dll (Alternative Hook)"),
                    ("OptiScaler.asi", "OptiScaler ASI Plugin — OptiScaler.asi (ASI Loader)"),
                ]
                self.method_items = [("optiscaler:" + opti_options[0][0], opti_options[0][1])]
                self.method_items.append(("direct", direct_label))
                for dll_n, lbl in opti_options[1:]:
                    self.method_items.append(("optiscaler:" + dll_n, lbl))

                has_dlss = "DLSS" in (game.get("inputs") or [])
                if (has_dlss and dlss_loader_available()) or game.get("route") == "dlss":
                    self.method_items.append(
                        ("dlss", "⚠ EXPERIMENTAL — DLSS Loader (HelixSR as the game's own DLSS, no OptiScaler)")
                    )

                self.cmb_drawer_method["values"] = [lbl for _tag, lbl in self.method_items]
                target_tag = (
                    game["route"]
                    if game.get("route") in ("direct", "dlss")
                    else "optiscaler:" + (game.get("optiDllName") or "dxgi.dll")
                )
                sel_idx = 0
                for idx, (tag, _lbl) in enumerate(self.method_items):
                    if tag.lower() == target_tag.lower():
                        sel_idx = idx
                        break
                self.cmb_drawer_method.current(sel_idx)

                self.fg_items = [
                    ("auto", "Frame Gen: Game Default / Pass-Through"),
                    ("dlssg_xefg", "DLSS-G Hook → Intel XeFG (AI Neural Frame Gen on AMD)"),
                    ("dlssg_fsrfg", "DLSS-G Hook → AMD FidelityFX FG (FSR 3.1 / 4.0 FG)"),
                    ("dlssg_nukems", "DLSS-G Hook → Nukem's dlssg-to-fsr3 (Streamline Swapchain)"),
                    ("optifg_fsrfg", "Universal OptiFG (Upscaler Hook + HUDFix → FSR-FG)"),
                ]
                self.cmb_drawer_fg["values"] = [lbl for _tag, lbl in self.fg_items]
                target_fg = game.get("fgMode") or "auto"
                fg_idx = 0
                for idx, (tag, _lbl) in enumerate(self.fg_items):
                    if tag.lower() == target_fg.lower():
                        fg_idx = idx
                        break
                self.cmb_drawer_fg.current(fg_idx)

                self.var_chk_fakenvapi.set(bool(game.get("useFakeNvapi", True)))
                self.var_chk_reframework.set(bool(game.get("installReFramework", False)))
            finally:
                self.updating_drawer = False
            self._update_drawer_method_summary()

        def _on_drawer_method_changed(self):
            if self.updating_drawer or not self.selected_game:
                return
            idx = self.cmb_drawer_method.current()
            if 0 <= idx < len(self.method_items):
                tag = self.method_items[idx][0]
                if tag in ("direct", "dlss"):
                    self.selected_game["route"] = tag
                elif tag.startswith("optiscaler:"):
                    self.selected_game["route"] = "optiscaler"
                    self.selected_game["optiDllName"] = tag.split(":", 1)[1]
            self._update_drawer_method_summary()

        def _on_drawer_fg_changed(self):
            if self.updating_drawer or not self.selected_game:
                return
            idx = self.cmb_drawer_fg.current()
            if 0 <= idx < len(self.fg_items):
                fg_tag = self.fg_items[idx][0]
                self.selected_game["fgMode"] = fg_tag
                if fg_tag.startswith("dlssg_"):
                    self.selected_game["useFakeNvapi"] = True
                    self.var_chk_fakenvapi.set(True)
            self._update_drawer_method_summary()

        def _on_drawer_check_changed(self):
            if self.updating_drawer or not self.selected_game:
                return
            self.selected_game["useFakeNvapi"] = bool(self.var_chk_fakenvapi.get())
            self.selected_game["installReFramework"] = bool(self.var_chk_reframework.get())
            self._update_drawer_method_summary()

        def _update_drawer_method_summary(self):
            if not self.selected_game:
                return
            route = self.selected_game.get("route") or "optiscaler"
            opti_dll = self.selected_game.get("optiDllName") or "dxgi.dll"
            fg_mode = self.selected_game.get("fgMode") or "auto"
            install_ref = bool(self.selected_game.get("installReFramework"))
            installed = bool(self.selected_game.get("installed"))

            fg_map = {
                "dlssg_xefg": " + XeFG",
                "dlssg_fsrfg": " + FSR-FG",
                "dlssg_nukems": " + NukemFG",
                "optifg_fsrfg": " + OptiFG",
            }
            fg_tag = fg_map.get(fg_mode, "") if route == "optiscaler" else ""
            if route == "optiscaler":
                r_disp = f"OptiScaler ({opti_dll}{fg_tag})"
            elif route == "direct":
                r_disp = "Direct (FSR 3.1)"
            else:
                r_disp = "DLSS Loader (Experimental)"
            self.selected_game["routeDisplay"] = r_disp

            self.lbl_drawer_route.configure(text=r_disp + (" + REFramework" if install_ref else ""))
            btn_verb = "Update / Reinstall" if installed else "Install HelixSR"

            if route == "optiscaler":
                self.panel_drawer_fg.pack(fill="x", pady=(0, 6), before=self.chk_drawer_fakenvapi)
                self.chk_drawer_fakenvapi.pack(fill="x", pady=(2, 2), before=self.chk_drawer_reframework)
                fg_note = ""
                if fg_mode == "dlssg_xefg":
                    fg_note = " Routes in-game DLSS Frame Generation to Intel XeSS-FG (AI optical flow on AMD/Intel)."
                elif fg_mode == "dlssg_fsrfg":
                    fg_note = " Routes in-game DLSS Frame Generation to AMD FidelityFX Frame Generation."
                elif fg_mode == "dlssg_nukems":
                    fg_note = " Routes in-game DLSS Frame Generation via Nukem's dlssg-to-fsr3 swapchain."
                elif fg_mode == "optifg_fsrfg":
                    fg_note = " Enables Universal OptiFG + HUDFix using upscaler motion vectors & depth."

                self.lbl_drawer_method_hint.configure(
                    text=f"Injects OptiScaler via {opti_dll} and routes DLSS/XeSS/FSR 2 inputs to HelixSR.{fg_note} Press Insert in-game to open the OptiScaler menu."
                )
                self.lbl_prop_method.configure(
                    text=f"{r_disp} + REFramework Nightly (dinput8.dll)" if install_ref else f"{r_disp} (Select DLSS in game)"
                )
                self.lbl_drawer_guide.configure(
                    text=(
                        f"1. Choose your preferred OptiScaler hook ({opti_dll}) and Frame Generation mode, then click '{btn_verb}'.\n"
                        "2. Start the game and open Graphics / Display settings.\n"
                        "3. Select NVIDIA DLSS as your upscaler (and enable DLSS Frame Generation if using a DLSS-G hook).\n"
                        "4. Press the Insert key in-game to open OptiScaler's HUD and customize HelixSR & Frame Generation."
                    )
                )
            elif route == "dlss":
                self.panel_drawer_fg.pack_forget()
                self.chk_drawer_fakenvapi.pack_forget()
                self.lbl_drawer_method_hint.configure(
                    text="EXPERIMENTAL (HelixSR 1.8.1): puts HelixSR's DLSS loader (dxgi.dll) and HelixSR as nvngx.dll next to the game's .exe, so the game's own DLSS option runs HelixSR without OptiScaler."
                )
                self.lbl_prop_method.configure(
                    text="DLSS Loader (Experimental) + REFramework Nightly (dinput8.dll)"
                    if install_ref
                    else "DLSS Loader (Experimental — select DLSS in game)"
                )
                self.lbl_drawer_guide.configure(
                    text=(
                        f"1. Click '{btn_verb}' above (you will be asked to confirm the experimental warning).\n"
                        "2. Start the game and open Graphics / Display settings.\n"
                        "3. Select NVIDIA DLSS. Leave NVIDIA-only options (Reflex, Frame Generation) off.\n"
                        "4. If it misbehaves, switch back to Direct FSR 3.1 or OptiScaler and reinstall."
                    )
                )
            else:
                self.panel_drawer_fg.pack_forget()
                self.chk_drawer_fakenvapi.pack_forget()
                fsr_count = len(self.selected_game.get("fsrTargets") or [])
                self.lbl_drawer_method_hint.configure(
                    text=(
                        f"Replaces {fsr_count} native FidelityFX DX12 DLL(s) directly (*.original.dll backed up). Best stability for RE Engine & AMD GPUs."
                        if fsr_count > 0
                        else "Deploys standalone amd_fidelityfx_upscaler_dx12.dll & amd_fidelityfx_dx12.dll directly next to the game executable."
                    )
                )
                self.lbl_prop_method.configure(
                    text="Direct FSR 3.1 Replacement + REFramework Nightly (dinput8.dll)"
                    if install_ref
                    else "Direct FSR 3.1 DLL Replacement (*.original.dll kept)"
                )
                self.lbl_drawer_guide.configure(
                    text=(
                        f"1. Click '{btn_verb}' above to replace the FidelityFX upscaler DLL with HelixSR.\n"
                        "2. Start the game and open Graphics / Display settings.\n"
                        "3. Enable AMD FSR 3 / FSR 3.1 in the game's options menu.\n"
                        "4. HelixSR will run automatically in place of FSR 3.1 with zero proxy hook overhead."
                    )
                )

            proton_opt = compute_proton_launch_option(route, opti_dll, install_ref)
            self.proton_cmd_var.set(proton_opt or "(No Proton override needed for Direct FSR 3.1)")

        def _open_drawer(self, game, idx=0):
            manifests = get_steam_manifests()
            fresh = scan_game(game["folder"], game.get("name"), manifests) if os.path.isdir(game.get("folder", "")) else dict(game)
            self.selected_game = fresh
            self.focused_index = idx

            self.lbl_drawer_title.configure(text=fresh.get("name") or "Game")
            self.lbl_drawer_platform.configure(text=fresh.get("launcher") or "Custom")
            if fresh.get("installed"):
                self.lbl_drawer_status.configure(text=f"✔ Installed ({fresh.get('version') or CORE_VERSION})", fg=self.c_emerald)
                self.btn_drawer_install.configure(text="⚡ Update / Reinstall")
                self.btn_drawer_uninstall.grid(row=0, column=1, sticky="ew", padx=2)
            else:
                self.lbl_drawer_status.configure(text="Not Installed", fg=self.c_dim)
                self.btn_drawer_install.configure(text="⚡ Install HelixSR")
                self.btn_drawer_uninstall.grid_remove()

            # Load thumbnail artwork if available
            cover_path = self._ensure_remote_artwork_async(fresh, "cover")
            thumb_photo = self._load_photo_image(cover_path, 54, 78) if cover_path else None
            if thumb_photo:
                self._drawer_thumb_ref = thumb_photo
                self.lbl_drawer_thumb.configure(image=thumb_photo, text="")
            else:
                self.lbl_drawer_thumb.configure(image="", text="🎮")

            exe_folder = fresh.get("exeFolder") or fresh.get("folder") or ""
            folder_disp = exe_folder if len(exe_folder) <= 44 else ("..." + exe_folder[-41:])
            self.lbl_prop_exe.configure(text=fresh.get("exeName") or "N/A")
            self.lbl_prop_folder.configure(text=folder_disp)

            apis = list(fresh.get("inputs") or [])
            if fresh.get("fsrTargets") and "FSR 3.1" not in apis:
                apis.append("FSR 3.1")
            self.lbl_prop_inputs.configure(text=", ".join(apis) if apis else "DirectX 12")

            self._populate_drawer_method_options(fresh)
            self._refresh_drawer_logs()

            if hasattr(self, "hero_drop_badge"):
                self.hero_drop_badge.pack_forget()
            if hasattr(self, "lbl_hero_title"):
                self.lbl_hero_title.configure(text="Neural Super Resolution")
            if hasattr(self, "lbl_hero_subtitle"):
                self.lbl_hero_subtitle.configure(text="Swap native FSR 3.1 DLLs or inject OptiScaler hooks with DLSS Model E.")

            self.drawer_frame.pack(side="right", fill="y", before=self.games_left_area)
            self.drawer_frame.pack_propagate(False)
            self._update_handheld_legend()
            self._render_games_grid_only()

        def _close_drawer(self):
            self.selected_game = None
            self.drawer_frame.pack_forget()
            if hasattr(self, "lbl_hero_title"):
                self.lbl_hero_title.configure(text="Neural Super Resolution Library")
            if hasattr(self, "hero_drop_badge"):
                self.hero_drop_badge.pack(side="left", padx=(10, 0))
            if hasattr(self, "lbl_hero_subtitle"):
                self.lbl_hero_subtitle.configure(
                    text="Swap native FSR 3.1 DLLs or inject OptiScaler hooks with DLSS Model E compute shaders & automatic REFramework nightly support."
                )
            self._update_handheld_legend()
            self._render_games_grid_only()

        def _open_selected_subfolder(self, rel_sub):
            if not self.selected_game:
                return
            base = self.selected_game.get("exeFolder") or self.selected_game.get("folder")
            target = os.path.join(base, rel_sub) if rel_sub else base
            if rel_sub and not os.path.isdir(target):
                os.makedirs(target, exist_ok=True)
            open_folder_native(target)

        def _refresh_drawer_logs(self):
            if not self.selected_game:
                return
            data = get_game_logs_and_ini(self.selected_game["folder"])
            self.txt_ini_editor.delete("1.0", "end")
            self.txt_ini_editor.insert(
                "1.0",
                data.get("optiscalerIni") or "; OptiScaler.ini not found yet. Install HelixSR (OptiScaler route) first.\n",
            )
            l1 = data.get("helixsrLog") or "(No helixsr.log found)"
            l2 = data.get("optiscalerLog") or "(No OptiScaler.log found)"
            self.txt_log_output.delete("1.0", "end")
            self.txt_log_output.insert("1.0", f"=== helixsr.log ===\n{l1}\n\n=== OptiScaler.log ===\n{l2}")

        def _on_save_ini_clicked(self):
            if not self.selected_game:
                return
            target = self.selected_game.get("exeFolder") or self.selected_game.get("folder")
            try:
                content = self.txt_ini_editor.get("1.0", "end-1c")
                with open(os.path.join(target, "OptiScaler.ini"), "w", encoding="utf-8") as f:
                    f.write(content)
                self._show_toast(f"Saved OptiScaler.ini for {self.selected_game.get('name')}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to save: {e}", parent=self.root)

        def _on_install_clicked(self):
            if not self.selected_game:
                return
            st = get_core_status()
            if not st.get("weightsBuilt"):
                ask = messagebox.askyesno(
                    "Network Not Built",
                    "The HelixSR network has not been built yet (HelixSR 1.8+ builds it into amd_fidelityfx_dx12.dll).\n\n"
                    "Without the network, HelixSR cannot upscale and the game may fail to start.\n\n"
                    "Would you like to switch to the 'Engine & Weights' tab to build it now?",
                    parent=self.root,
                )
                if ask:
                    self._switch_tab("core")
                return

            if self.selected_game.get("route") == "dlss":
                confirm = messagebox.askyesno(
                    "Experimental DLSS Loader",
                    "EXPERIMENTAL: DLSS without OptiScaler (HelixSR 1.8.1)\n\n"
                    "• Tested in very few games, on Linux (Proton) only — NOT tested on Windows.\n"
                    "• It may not work or may crash the game.\n"
                    "• Do NOT use it in online games or games with anti-cheat (ban risk).\n"
                    "• Leave NVIDIA-only options (Reflex, Frame Generation) off.\n\n"
                    f"Install the DLSS loader for {self.selected_game.get('name')} anyway?",
                    parent=self.root,
                )
                if not confirm:
                    return

            try:
                res = install_helixsr(
                    self.selected_game["folder"],
                    route_override=self.selected_game.get("route"),
                    opti_dll=self.selected_game.get("optiDllName"),
                    use_fakenvapi=self.selected_game.get("useFakeNvapi"),
                    install_ref=self.selected_game.get("installReFramework"),
                    fg_mode=self.selected_game.get("fgMode"),
                )
                chosen = self.selected_game.get("routeDisplay") or "OptiScaler"
                self._show_toast(f"Installed HelixSR [{chosen}] on {self.selected_game.get('name')}")
                messagebox.showinfo("Install Success", res["message"], parent=self.root)
                self._rescan_games(keep_selection=True)
            except Exception as e:
                messagebox.showerror("Error", f"Install failed: {e}", parent=self.root)

        def _on_uninstall_clicked(self):
            if not self.selected_game:
                return
            has_ref = bool(self.selected_game.get("isReEngine") or self.selected_game.get("installReFramework"))
            q_msg = (
                f"Restore original files and uninstall HelixSR & REFramework from {self.selected_game.get('name')}?"
                if has_ref
                else f"Restore original files and uninstall HelixSR from {self.selected_game.get('name')}?"
            )
            if not messagebox.askyesno("Confirm Uninstall", q_msg, parent=self.root):
                return
            try:
                res = uninstall_helixsr(self.selected_game["folder"])
                self._show_toast(f"Restored original files for {self.selected_game.get('name')}")
                messagebox.showinfo("Success", res["message"], parent=self.root)
                self._rescan_games(keep_selection=True)
            except Exception as e:
                messagebox.showerror("Error", f"Uninstall failed: {e}", parent=self.root)

        def _on_launch_clicked(self):
            if not self.selected_game:
                return
            res = launch_game_native(self.selected_game["folder"])
            if res.get("success"):
                self._show_toast(res.get("message", "Launching game..."))
            else:
                messagebox.showwarning("Error", res.get("error", "Could not launch game"), parent=self.root)

        def _on_clear_shader_cache_clicked(self):
            if not self.selected_game:
                return
            cleared = clear_shader_cache(self.selected_game)
            if cleared:
                self._show_toast(f"Cleared shader cache for {self.selected_game.get('name')}")
                messagebox.showinfo(
                    "Cache Cleared",
                    f"Shader cache files successfully cleared for {self.selected_game.get('name')}!\n\n"
                    "Broken or corrupted pipeline states (such as shader.cache2) were removed. The game will perform a clean shader compilation on next startup.",
                    parent=self.root,
                )
            else:
                messagebox.showinfo(
                    "Cache Empty",
                    f"No cached shader or pipeline binary files were found for {self.selected_game.get('name')}.",
                    parent=self.root,
                )

        # --------------------------------------------------------------------
        # TAB 2: ENGINE & WEIGHTS (Matches BuildCorePane in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_core_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_main_shell, padx=24, pady=24)
            wrap.pack(fill="both", expand=True)

            tk.Label(
                wrap,
                text="HelixSR Core & Neural Network Compiler",
                bg=self.c_main_shell,
                fg=self.c_text,
                font=("Sans", 16, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
            tk.Label(
                wrap,
                text=f"HelixSR runs NVIDIA DLSS Model E neural networks as pure Direct3D 12 compute shaders. Since Core {CORE_VERSION} the network is built locally once and embedded into HelixSR's DLL (one file per game).",
                bg=self.c_main_shell,
                fg=self.c_muted,
                font=("Sans", 10),
                anchor="w",
                justify="left",
                wraplength=880,
            ).pack(fill="x", pady=(0, 18))

            # Card 1: Network Artifacts Telemetry
            card_status = tk.Frame(
                wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=20,
                pady=18,
            )
            card_status.pack(fill="x", pady=(0, 18))
            tk.Label(
                card_status,
                text="Network Artifacts Telemetry",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 12, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 10))

            self.lbl_weights_status = tk.Label(
                card_status,
                text="Checking...",
                bg=self.c_card,
                fg=self.c_emerald,
                font=("Sans", 10, "bold"),
                anchor="w",
            )
            self.lbl_weights_status.pack(fill="x", pady=(0, 6))
            self.lbl_weights_size = tk.Label(card_status, text="Weights: -", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), anchor="w")
            self.lbl_weights_size.pack(fill="x", pady=(0, 3))
            self.lbl_kernels_size = tk.Label(card_status, text="Kernels: -", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), anchor="w")
            self.lbl_kernels_size.pack(fill="x", pady=(0, 3))
            self.lbl_toolchain_status = tk.Label(card_status, text="Local Toolchain: -", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), anchor="w")
            self.lbl_toolchain_status.pack(fill="x")

            # Card 2: Network Compiler Wizard
            card_builder = tk.Frame(
                wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=20,
                pady=18,
            )
            card_builder.pack(fill="both", expand=True)
            tk.Label(
                card_builder,
                text="Network Compiler Wizard",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 12, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
            tk.Label(
                card_builder,
                text="Select an existing local copy of nvngx_dlss.dll (DLSS 310.7.0 found in your games) or download automatically from NVIDIA GitHub.",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 9),
                anchor="w",
            ).pack(fill="x", pady=(0, 12))

            self.var_dlss_source = tk.StringVar(value="Download automatically from NVIDIA GitHub (Recommended)")
            self.cmb_dlss_source = ttk.Combobox(
                card_builder,
                textvariable=self.var_dlss_source,
                values=["Download automatically from NVIDIA GitHub (Recommended)"],
                state="readonly",
                style="Helix.TCombobox",
                font=("Sans", 9),
            )
            self.cmb_dlss_source.pack(fill="x", pady=(0, 14))

            btn_row = tk.Frame(card_builder, bg=self.c_card)
            btn_row.pack(fill="x", pady=(0, 14))
            self.btn_start_build = self._make_btn(
                btn_row,
                "⚡ Compile HelixSR Network & Auto-Sync",
                self._on_start_build_clicked,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
                padx=20,
                pady=8,
                font_size=10,
            )
            self.btn_start_build.pack(side="left")

            self.txt_build_console = tk.Text(
                card_builder,
                height=10,
                bg="#080a0f",
                fg=self.c_emerald_strong,
                font=("Monospace", 9),
                bd=0,
                padx=10,
                pady=10,
                wrap="word",
            )
            self.txt_build_console.pack(fill="both", expand=True)
            self.txt_build_console.insert(
                "1.0",
                "Ready to compile. Press 'Compile HelixSR Network & Auto-Sync' to build the network into HelixSR's DLL.\n",
            )

        def _update_dlss_candidates(self):
            if not hasattr(self, "cmb_dlss_source"):
                return
            items = ["Download automatically from NVIDIA GitHub (Recommended)"]
            self._dlss_candidate_map = {}
            for g in self.all_games:
                p = g.get("foundNvngxDlssPath")
                if p and os.path.isfile(p):
                    try:
                        if os.path.getsize(p) >= 40 * 1024 * 1024:
                            lbl = f"Use from {g.get('name')} ({p})"
                            items.append(lbl)
                            self._dlss_candidate_map[lbl] = p
                    except Exception:
                        pass
            self.cmb_dlss_source["values"] = items
            self.cmb_dlss_source.current(0)

        def _on_start_build_clicked(self):
            if IS_BUILDING:
                self._show_toast("Compilation already in progress...")
                return
            self.txt_build_console.delete("1.0", "end")
            self.txt_build_console.insert("1.0", "Starting HelixSR Network compiler...\n")
            sel = self.var_dlss_source.get()
            dlss_path = self._dlss_candidate_map.get(sel, "")
            start_network_build(dlss_path=dlss_path)
            self._refresh_core_ui()

        def _refresh_core_ui(self):
            st = get_core_status()
            built = bool(st.get("weightsBuilt"))
            if built:
                if hasattr(self, "dot_core_nav") and self.dot_core_nav:
                    self.dot_core_nav.configure(fg=self.c_emerald)
                self.dot_sidebar_status.configure(fg=self.c_emerald)
                self.lbl_sidebar_status.configure(text="Ready • Network Built")
                self.sidebar_prog_bar.configure(width=195, bg=self.c_emerald_strong)

                self.lbl_weights_status.configure(fg=self.c_emerald)
                if st.get("networkEmbedded"):
                    dll_mb = (st.get("dllSize") or 0) / (1024.0 * 1024.0)
                    w_mb = (st.get("weightsSize") or 0) / (1024.0 * 1024.0)
                    k_mb = (st.get("kernelsSize") or 0) / (1024.0 * 1024.0)
                    self.lbl_weights_status.configure(text=f"✔ Network: READY (embedded in amd_fidelityfx_dx12.dll, {dll_mb:.2f} MB)")
                    self.lbl_weights_size.configure(text=f"Weights (embedded): {w_mb:.2f} MB")
                    self.lbl_kernels_size.configure(text=f"DXIL kernels (embedded): {k_mb:.2f} MB")
                else:
                    w_mb = (st.get("weightsSize") or 0) / (1024.0 * 1024.0)
                    k_mb = (st.get("kernelsSize") or 0) / (1024.0 * 1024.0)
                    self.lbl_weights_status.configure(text="✔ Network: READY (separate files from an older setup — rebuild to embed it)")
                    self.lbl_weights_size.configure(text=f"helixsr_weights.bin: {w_mb:.2f} MB")
                    self.lbl_kernels_size.configure(text=f"helixsr_kernels.pak: {k_mb:.2f} MB")
            else:
                if hasattr(self, "dot_core_nav") and self.dot_core_nav:
                    self.dot_core_nav.configure(fg=self.c_amber)
                self.dot_sidebar_status.configure(fg=self.c_amber)
                self.lbl_sidebar_status.configure(text="Action Needed • Build Network")
                self.sidebar_prog_bar.configure(width=65, bg=self.c_amber)

                self.lbl_weights_status.configure(text="⚠ Network: NOT BUILT (Run Compiler below)", fg=self.c_amber)
                self.lbl_weights_size.configure(text="Weights: Missing")
                self.lbl_kernels_size.configure(text="DXIL kernels: Missing")

            self.lbl_toolchain_status.configure(
                text="Toolchain: Installed in LocalAppData / ~/.local/share/HelixSR"
                if (st.get("hasPython") and st.get("hasDxc"))
                else "Toolchain: Will download automatically on first compile"
            )
            self.btn_start_build.configure(state="disabled" if IS_BUILDING else "normal")

        # --------------------------------------------------------------------
        # TAB 3: CUSTOM FSR (my-fsr) (Matches BuildMyFsrPane in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_myfsr_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_main_shell, padx=24, pady=24)
            wrap.pack(fill="both", expand=True)

            tk.Label(
                wrap,
                text="Custom FSR & Frame Generation Manager (my-fsr)",
                bg=self.c_main_shell,
                fg=self.c_text,
                font=("Sans", 16, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 6))
            tk.Label(
                wrap,
                text="OptiScaler allows dropping custom AMD FidelityFX and Intel XeSS Frame Generation DLLs into 'my-fsr' to expose them in-game alongside HelixSR!",
                bg=self.c_main_shell,
                fg=self.c_muted,
                font=("Sans", 10),
                anchor="w",
            ).pack(fill="x", pady=(0, 20))

            card = tk.Frame(
                wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=22,
                pady=22,
            )
            card.pack(fill="x")

            guide_text = (
                "How to use custom FSR & Frame Generation DLLs in your games:\n\n"
                "1. Click 'Open Core my-fsr Folder' below (or open a game's 'my-fsr' folder from the Game Drawer).\n"
                "2. Drop any of these optional DLLs into the folder:\n"
                "   • amd_fidelityfx_upscaler_dx12.dll — Custom FSR 3.1 / FSR 4 upscaler for real-time A/B comparisons\n"
                "   • libxess_fg.dll & libxell.dll — Intel XeSS Frame Generation & XeLL Low Latency (for DLSS-G → XeFG)\n"
                "   • amd_fidelityfx_framegeneration_dx12.dll — AMD FidelityFX Frame Generation (for DLSS-G → FSR-FG / OptiFG)\n"
                "   • dlssg_to_fsr3_amd_is_better.dll — Nukem's DLSS-G to FSR 3.1 Streamline swapchain translator\n"
                "3. Select your desired Frame Generation mode in the Game Drawer and install HelixSR.\n"
                "4. Launch the game and press the Insert key to open OptiScaler's HUD to switch upscalers or tune Frame Gen!"
            )
            tk.Label(
                card,
                text=guide_text,
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 10),
                justify="left",
                anchor="w",
                wraplength=840,
            ).pack(fill="x")

            btn_row = tk.Frame(card, bg=self.c_card)
            btn_row.pack(fill="x", pady=(20, 0))
            self._make_btn(
                btn_row,
                "📂 Open Core my-fsr Folder",
                self._open_core_myfsr_folder,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
                padx=16,
                pady=7,
            ).pack(side="left")

        def _open_core_myfsr_folder(self):
            p = os.path.join(CORE_DIR, MY_FSR_FOLDER)
            os.makedirs(p, exist_ok=True)
            open_folder_native(p)

        # --------------------------------------------------------------------
        # TAB 4: SCAN & SETTINGS (Matches BuildSettingsPane in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_settings_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_main_shell, padx=24, pady=24)
            wrap.pack(fill="both", expand=True)

            tk.Label(
                wrap,
                text="Settings & Library Scan Paths",
                bg=self.c_main_shell,
                fg=self.c_text,
                font=("Sans", 16, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 20))

            self.settings_card = tk.Frame(
                wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=22,
                pady=22,
            )
            self.settings_card.pack(fill="x")
            self._refresh_settings_ui()

        def _refresh_settings_ui(self):
            if not hasattr(self, "settings_card") or not self.settings_card.winfo_exists():
                return
            for child in self.settings_card.winfo_children():
                child.destroy()

            tk.Label(
                self.settings_card,
                text="Detected Steam Library Roots:",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 11, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 8))

            for lib in get_steam_libraries():
                tk.Label(
                    self.settings_card,
                    text=f"• {lib}",
                    bg=self.c_card,
                    fg=self.c_muted,
                    font=("Sans", 10),
                    anchor="w",
                ).pack(fill="x", pady=2)

            tk.Label(
                self.settings_card,
                text="Custom Scan Folders:",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 11, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(18, 8))

            customs = load_config().get("customFolders", [])
            if not customs:
                tk.Label(
                    self.settings_card,
                    text="(No custom folders added yet. Click '＋ Add Game' or drag & drop any game folder onto the window).",
                    bg=self.c_card,
                    fg=self.c_dim,
                    font=("Sans", 10),
                    anchor="w",
                ).pack(fill="x")
            else:
                for cf in customs:
                    tk.Label(
                        self.settings_card,
                        text=f"• {cf}",
                        bg=self.c_card,
                        fg=self.c_muted,
                        font=("Sans", 10),
                        anchor="w",
                    ).pack(fill="x", pady=2)

            btn_row = tk.Frame(self.settings_card, bg=self.c_card)
            btn_row.pack(fill="x", pady=(18, 0))
            self._make_btn(
                btn_row,
                "＋ Add Custom Folder",
                self._prompt_add_custom_folder,
                bg=self.c_emerald_strong,
                fg=self.c_on_accent,
                border=self.c_border_strong,
                padx=16,
                pady=7,
            ).pack(side="left")

        # --------------------------------------------------------------------
        # TAB 5: HARDWARE & ABOUT (Matches BuildAboutPane in MainWindow.cs)
        # --------------------------------------------------------------------
        def _build_about_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_main_shell, padx=24, pady=24)
            wrap.pack(fill="both", expand=True)

            tk.Label(
                wrap,
                text="Diagnostics & Hardware Telemetry",
                bg=self.c_main_shell,
                fg=self.c_text,
                font=("Sans", 16, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 20))

            card = tk.Frame(
                wrap,
                bg=self.c_card,
                highlightbackground=self.c_border,
                highlightthickness=1,
                padx=22,
                pady=22,
            )
            card.pack(fill="x")

            tk.Label(
                card,
                text="Detected Display Adapters:",
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 11, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 10))

            for g in get_gpu_info():
                r = tk.Frame(card, bg=self.c_card)
                r.pack(fill="x", pady=3)
                tk.Label(
                    r,
                    text="⚡ " + g.get("name", "GPU"),
                    bg=self.c_card,
                    fg=self.c_text,
                    font=("Sans", 10, "bold"),
                    width=42,
                    anchor="w",
                ).pack(side="left")
                ram_txt = f"{g['ramMB']} MB VRAM" if g.get("ramMB", 0) > 0 else "Shared / Unified APU Memory"
                tk.Label(
                    r,
                    text=ram_txt,
                    bg=self.c_card,
                    fg=self.c_emerald,
                    font=("Sans", 10),
                    width=24,
                    anchor="w",
                ).pack(side="left")
                tk.Label(
                    r,
                    text=f"Driver: {g.get('driver', 'Mesa RADV')}",
                    bg=self.c_card,
                    fg=self.c_dim,
                    font=("Sans", 9),
                    anchor="w",
                ).pack(side="left")

            about_text = (
                "\nAbout HelixSR Manager:\n"
                "HelixSR runs NVIDIA's DLSS Model E neural network using pure Direct3D 12 compute shaders on AMD RDNA GPUs without Tensor Cores or NVIDIA drivers.\n\n"
                "HelixSR Manager is a 100% standalone native desktop application supporting Direct FSR 3.1 replacement, OptiScaler proxy hooks, DLSS-G Frame Generation translation (XeFG / FSR-FG / NukemFG / OptiFG), FakeNVAPI, and automatic Capcom REFramework nightly deployment.\n\n"
                "Open Source / Fork Notice:\n"
                "Denarmo is not the original owner of the underlying forked codebase. Modifications and contributions in this fork are provided under the MIT License and may be used by others."
            )
            tk.Label(
                card,
                text=about_text,
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 10),
                justify="left",
                anchor="w",
                wraplength=840,
            ).pack(fill="x")

        # --------------------------------------------------------------------
        # NAVIGATION, TOAST, HANDHELD LEGEND & SHORTCUTS
        # --------------------------------------------------------------------
        def _switch_tab(self, tab_id):
            self.current_tab = tab_id
            for tid, f in self.panes.items():
                f.pack_forget()
            self.panes[tab_id].pack(fill="both", expand=True)
            self._update_nav_visuals()
            if tab_id == "core":
                self._refresh_core_ui()
            elif tab_id == "settings":
                self._refresh_settings_ui()
            self._update_handheld_legend()

        def _show_toast(self, message):
            self.lbl_toast.configure(text="✦  " + message)
            self.toast_banner.place(relx=1.0, rely=1.0, x=-28, y=-26, anchor="se")
            self.toast_banner.lift()
            if self.toast_after_id:
                try:
                    self.root.after_cancel(self.toast_after_id)
                except Exception:
                    pass
            self.toast_after_id = self.root.after(3200, lambda: self.toast_banner.place_forget())

        def _copy_to_clipboard(self, text, toast_prefix="Copied"):
            if not text:
                return
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(text)
                self.root.update()
            except Exception:
                pass
            if os.name != "nt":
                for clip_cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                    if shutil.which(clip_cmd[0]):
                        try:
                            p = subprocess.Popen(
                                clip_cmd,
                                stdin=subprocess.PIPE,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                env=get_clean_desktop_env(),
                            )
                            p.communicate(input=text.encode("utf-8"), timeout=1.5)
                            break
                        except Exception:
                            pass
            self._show_toast(f"{toast_prefix}: {text}")

        def _update_handheld_legend(self):
            if not hasattr(self, "legend_stack") or not self.legend_stack.winfo_exists():
                return
            for child in self.legend_stack.winfo_children():
                child.destroy()

            is_drawer = self.selected_game is not None
            if is_drawer:
                items = [
                    ("D-Pad / Stick", "#3498db", "Navigate / Change"),
                    ("A", "#2ecc71", "Select / Toggle"),
                    ("B", "#e74c3c", "Close Drawer"),
                    ("LB/RB", "#95a5a6", "Tabs (Guide/INI/Logs)"),
                    ("View", "#9b59b6", "Exit Handheld (F11)"),
                ]
            elif self.current_tab == "core":
                items = [
                    ("A", "#2ecc71", "Compile Network"),
                    ("LB/RB", "#95a5a6", "Tabs"),
                    ("B", "#e74c3c", "Library"),
                    ("View", "#9b59b6", "Exit Handheld (F11)"),
                ]
            else:
                items = [
                    ("A", "#2ecc71", "Manage"),
                    ("X", "#3498db", "Launch Game"),
                    ("Y", "#f1c40f", "Toggle View"),
                    ("LB/RB", "#95a5a6", "Tabs"),
                    ("LT/RT", "#95a5a6", "Filters"),
                    ("View", "#9b59b6", "Exit Handheld (F11)"),
                ]

            bar_bg = self.legend_stack.cget("bg")
            for btn_txt, badge_col, act_txt in items:
                p = tk.Frame(self.legend_stack, bg=bar_bg, padx=10)
                p.pack(side="left")
                tk.Label(
                    p,
                    text=btn_txt,
                    bg=badge_col,
                    fg="#000000",
                    font=("Sans", 8, "bold"),
                    padx=6,
                    pady=1,
                ).pack(side="left", padx=(0, 6))
                tk.Label(p, text=act_txt, bg=bar_bg, fg=self.c_muted, font=("Sans", 9)).pack(side="left")

        def _toggle_handheld_mode(self, force_state=None):
            target = bool(force_state) if force_state is not None else (not self.is_handheld_mode)
            self.is_handheld_mode = target
            try:
                self.root.attributes("-fullscreen", self.is_handheld_mode)
            except Exception:
                pass

            if self.is_handheld_mode:
                self.legend_bar.pack(side="bottom", fill="x", before=self.root_grid)
                self.root_grid.configure(padx=8, pady=8)
                self.btn_handheld_toggle.configure(
                    text="🎮 Handheld: ON",
                    bg=self.c_emerald_bg,
                    highlightbackground=self.c_emerald,
                )
                if self.focused_index < 0 and self.filtered_games:
                    self.focused_index = 0
                self._update_handheld_legend()
                self._show_toast("🎮 Handheld Mode: ON (Fullscreen & Controller Navigation Active)")
            else:
                self.legend_bar.pack_forget()
                self.root_grid.configure(padx=14, pady=14)
                self.btn_handheld_toggle.configure(
                    text="🎮 Handheld",
                    bg=self.c_card_hover,
                    highlightbackground=self.c_border,
                )
                self._show_toast("🎮 Handheld Mode: OFF (Standard Desktop Window)")
            self._render_games_grid_only()

        def _toggle_theme(self):
            self.is_light = not self.is_light
            cfg = load_config()
            cfg["lightTheme"] = self.is_light
            save_config(cfg)
            prev_game = self.selected_game
            prev_tab = self.current_tab
            prev_search = self.search_var.get() if hasattr(self, "search_var") else ""

            self._apply_palette()
            self._configure_ttk_styles()
            self._build_layout()
            if prev_search:
                self.search_var.set(prev_search)
            self._refresh_core_ui()
            self._apply_game_filters()
            self._update_dlss_candidates()
            self._switch_tab(prev_tab)
            if prev_game:
                self._open_drawer(prev_game, max(0, self.focused_index))
            self._show_toast("Switched to Clean Light Theme" if self.is_light else "Switched to HelixSR Manager Dark Gold Theme")

        def _initial_load(self):
            self._rescan_games()
            self._refresh_core_ui()

        def _rescan_games(self, keep_selection=False):
            prev_folder = self.selected_game["folder"] if (keep_selection and self.selected_game) else None
            self.all_games = scan_all_games()
            self._apply_game_filters()
            self._update_dlss_candidates()
            if prev_folder:
                for i, g in enumerate(self.filtered_games):
                    if canonical_key(g["folder"]) == canonical_key(prev_folder):
                        self._open_drawer(g, i)
                        break

        def _prompt_add_custom_folder(self):
            folder = filedialog.askdirectory(title="Select a Game installation folder:", parent=self.root)
            if folder and os.path.isdir(folder):
                cfg = load_config()
                norm = normalize_path(folder)
                if norm not in cfg["customFolders"]:
                    cfg["customFolders"].append(norm)
                    save_config(cfg)
                self._rescan_games()
                self._refresh_settings_ui()
                self._show_toast(f"Added folder: {os.path.basename(norm)}")

        def _install_all_games(self):
            if not messagebox.askyesno("Batch Action", "Are you sure you want to Install HelixSR on all uninstalled games?", parent=self.root):
                return
            count = 0
            for g in self.all_games:
                if not g.get("installed") and g.get("route"):
                    try:
                        install_helixsr(g["folder"])
                        count += 1
                    except Exception:
                        pass
            self._show_toast(f"Batch operation completed on {count} game(s)")
            messagebox.showinfo("Done", f"Operation complete on {count} games.", parent=self.root)
            self._rescan_games(keep_selection=True)

        def _uninstall_all_games(self):
            if not messagebox.askyesno("Batch Action", "Are you sure you want to Restore original files on all installed games?", parent=self.root):
                return
            count = 0
            for g in self.all_games:
                if g.get("installed"):
                    try:
                        uninstall_helixsr(g["folder"])
                        count += 1
                    except Exception:
                        pass
            self._show_toast(f"Batch operation completed on {count} game(s)")
            messagebox.showinfo("Done", f"Operation complete on {count} games.", parent=self.root)
            self._rescan_games(keep_selection=True)

        def _bind_shortcuts(self):
            self.root.bind("<F11>", lambda _e: self._toggle_handheld_mode())
            self.root.bind("<F5>", lambda _e: (self._rescan_games(keep_selection=True), self._show_toast("Library rescanned")))
            self.root.bind("<Control-k>", lambda _e: (self._switch_tab("games"), self.entry_search.focus_set(), self.entry_search.select_range(0, "end")))
            self.root.bind("<Control-f>", lambda _e: (self._switch_tab("games"), self.entry_search.focus_set(), self.entry_search.select_range(0, "end")))
            self.root.bind("<Escape>", self._on_escape_pressed)
            self.root.bind("<Down>", lambda _e: self._move_focus(1))
            self.root.bind("<Right>", lambda _e: self._move_focus(1))
            self.root.bind("<Up>", lambda _e: self._move_focus(-1))
            self.root.bind("<Left>", lambda _e: self._move_focus(-1))
            self.root.bind("<Return>", lambda _e: self._activate_focused())

        def _on_escape_pressed(self, _event):
            if self.selected_game is not None:
                self._close_drawer()
            elif self.search_var.get():
                self.search_var.set("")

        def _move_focus(self, delta):
            if self.current_tab != "games" or not self.filtered_games:
                return
            self.focused_index = max(0, min(len(self.filtered_games) - 1, self.focused_index + delta))
            self._render_games_grid_only()

        def _activate_focused(self):
            if self.current_tab == "games" and 0 <= self.focused_index < len(self.filtered_games):
                self._open_drawer(self.filtered_games[self.focused_index], self.focused_index)

        def _periodic_tick(self):
            if os.name != "nt":
                wakeup_path = os.path.join(get_data_dir(), "wakeup.flag")
                if os.path.isfile(wakeup_path):
                    try:
                        os.remove(wakeup_path)
                    except Exception:
                        pass
                    try:
                        self.root.deiconify()
                        self.root.lift()
                        self.root.focus_force()
                    except Exception:
                        pass

            updated_logs = False
            while self.build_log_queue:
                line = self.build_log_queue.pop(0)
                if hasattr(self, "txt_build_console") and self.txt_build_console.winfo_exists():
                    self.txt_build_console.insert("end", line + "\n")
                    self.txt_build_console.see("end")
                updated_logs = True

            if updated_logs or IS_BUILDING:
                self._refresh_core_ui()
                if not IS_BUILDING and updated_logs:
                    self._rescan_games(keep_selection=True)
                    self._show_toast("Network compilation finished")

            self.root.after(250, self._periodic_tick)

    root = tk.Tk()
    HelixSRStandaloneApp(root)
    root.mainloop()


def main():
    ensure_linux_environment()

    if "--list" in sys.argv:
        for g in scan_all_games():
            status = f"ACTIVE ({g['routeDisplay']})" if g["installed"] else f"Not Installed ({g['routeDisplay']})"
            print(f"- {g['name']} [{g['launcher']}] -> {status} ({g['folder']})")
        return

    smoke_ms = 0
    for arg in sys.argv[1:]:
        if arg.startswith("--smoke-test="):
            try:
                smoke_ms = int(arg.split("=", 1)[1])
            except Exception:
                smoke_ms = 500

    run_standalone_gui(smoke_test_ms=smoke_ms)


if __name__ == "__main__":
    main()
