#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HelixSR Manager — Standalone Linux & SteamOS Application Backend & Desktop Launcher
Zero external dependencies (Python 3 standard library only).
"""

import base64
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PUBLIC_DIR = os.path.join(APP_DIR, "public")
if not os.path.isdir(PUBLIC_DIR):
    PUBLIC_DIR = os.path.abspath(os.path.join(APP_DIR, "..", "..", "public"))

APP_VERSION = "1.1.1"   # HelixSR Manager release
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
    if "SYSTEM_LD_LIBRARY_PATH" in env:
        env["LD_LIBRARY_PATH"] = env["SYSTEM_LD_LIBRARY_PATH"]
    elif "LD_LIBRARY_PATH" in env:
        parts = [
            p for p in env["LD_LIBRARY_PATH"].split(":")
            if p and not any(k in p.lower() for k in ("steam", "pressure-vessel", "sniper", "soldier", "scout"))
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
                    # only targets HelixSR owns (game's file kept as *.original.dll or our install record)
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
            # game running / file locked: leave this game as it is, the user can reinstall it from the drawer
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
            # HelixSR 1.8+: both wave sizes are always built (wave64 flag kept only for API compatibility),
            # the network is embedded into amd_fidelityfx_dx12.dll, and setup no longer has a build-only switch.
            if os.name == "nt":
                ps1 = os.path.join(CORE_DIR, "helixsr-setup.ps1")
                cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Yes", "-Rebuild"]
                if dlss_path and os.path.isfile(dlss_path):
                    cmd += ["-Dlss", dlss_path]
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

            env = dict(os.environ)
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
            # Upstream setup continues with its own interactive game installer after the build; the
            # manager handles installs itself, so that part of the output is hidden.
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


class SwapperRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw) if raw else {}

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        pathname = parsed.path
        qs = urllib.parse.parse_qs(parsed.query)

        if pathname == "/api/games":
            return self._send_json(200, {"games": scan_all_games()})

        if pathname == "/api/core/status":
            st = get_core_status()
            games = scan_all_games()
            cands = [{"game": g["name"], "path": g["foundNvngxDlssPath"]} for g in games if g.get("foundNvngxDlssPath")]
            st["dlssCandidates"] = cands
            st["handheld"] = detect_handheld_environment()
            st["isBuilding"] = IS_BUILDING
            return self._send_json(200, st)

        if pathname == "/api/system/info":
            return self._send_json(200, {
                "platform": platform.system(),
                "release": platform.release(),
                "gpus": get_gpu_info(),
                "steamLibraries": get_steam_libraries(),
                "customFolders": load_config().get("customFolders", []),
                "handheld": detect_handheld_environment(),
            })

        if pathname == "/api/games/logs":
            folder = qs.get("folder", [""])[0]
            manifests = get_steam_manifests()
            g = scan_game(folder, None, manifests) if folder else {}
            t = g.get("exeFolder") or folder
            hlog = ""
            olog = ""
            ini = ""
            for p in (os.path.join(t, HELIXSR_FOLDER, "helixsr.log"), os.path.join(t, "helixsr.log")):
                if os.path.isfile(p):
                    with open(p, "r", encoding="utf-8", errors="ignore") as f:
                        hlog = f.read()
                    break
            op = os.path.join(t, "OptiScaler.log")
            if os.path.isfile(op):
                with open(op, "r", encoding="utf-8", errors="ignore") as f:
                    olog = f.read()
            ip = os.path.join(t, "OptiScaler.ini")
            if os.path.isfile(ip):
                with open(ip, "r", encoding="utf-8", errors="ignore") as f:
                    ini = f.read()
            return self._send_json(200, {"helixsrLog": hlog, "optiscalerLog": olog, "optiscalerIni": ini})

        if pathname == "/api/steam-image":
            b64 = qs.get("path", [""])[0]
            try:
                img_path = base64.b64decode(b64).decode("utf-8")
                if os.path.isfile(img_path):
                    with open(img_path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
            except Exception:
                pass
            self.send_response(404)
            self.end_headers()
            return

        if pathname == "/api/core/build-events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = []
            with BUILD_LOCK:
                BUILD_LISTENERS.append(q)
            try:
                while True:
                    while q:
                        line = q.pop(0)
                        self.wfile.write(f"data: {json.dumps({'log': line})}\n\n".encode("utf-8"))
                        self.wfile.flush()
                    if not IS_BUILDING and not q:
                        break
                    time.sleep(0.25)
            except Exception:
                pass
            finally:
                with BUILD_LOCK:
                    if q in BUILD_LISTENERS:
                        BUILD_LISTENERS.remove(q)
            return

        # Serve Static Public UI
        rel = "index.html" if pathname in ("/", "") else pathname.lstrip("/")
        file_path = os.path.abspath(os.path.join(PUBLIC_DIR, rel))
        if not file_path.startswith(os.path.abspath(PUBLIC_DIR)) or not os.path.isfile(file_path):
            file_path = os.path.join(PUBLIC_DIR, "index.html")

        ext = os.path.splitext(file_path)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".ico": "image/x-icon",
        }.get(ext, "application/octet-stream")

        try:
            with open(file_path, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        pathname = parsed.path
        body = self._read_json()

        try:
            if pathname == "/api/shutdown":
                self._send_json(200, {"success": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if pathname == "/api/scan":
                games = scan_all_games()
                return self._send_json(200, {"success": True, "count": len(games), "games": games})

            if pathname == "/api/games/install":
                res = install_helixsr(
                    body.get("gameFolder"),
                    route_override=body.get("route"),
                    opti_dll=body.get("optiDllName"),
                    use_fakenvapi=body.get("useFakeNvapi"),
                    install_ref=body.get("installReFramework"),
                    fg_mode=body.get("fgMode"),
                )
                return self._send_json(200, res)

            if pathname == "/api/games/uninstall":
                res = uninstall_helixsr(body.get("gameFolder"))
                return self._send_json(200, res)

            if pathname == "/api/games/clear-cache":
                manifests = get_steam_manifests()
                g = scan_game(body.get("gameFolder"), None, manifests)
                cleared = clear_shader_cache(g)
                msg = f"Cleared shader & Proton pipeline cache for {g['name']}!" if cleared else f"No cached shader files found for {g['name']}."
                return self._send_json(200, {"success": True, "cleared": cleared, "message": msg})

            if pathname == "/api/games/install-all":
                games = scan_all_games()
                results = []
                for g in games:
                    if not g["installed"] and g["route"]:
                        try:
                            r = install_helixsr(g["folder"])
                            results.append({"name": g["name"], "success": True, "message": r["message"]})
                        except Exception as e:
                            results.append({"name": g["name"], "success": False, "error": str(e)})
                return self._send_json(200, {"success": True, "results": results})

            if pathname == "/api/games/uninstall-all":
                games = scan_all_games()
                results = []
                for g in games:
                    if g["installed"]:
                        try:
                            r = uninstall_helixsr(g["folder"])
                            results.append({"name": g["name"], "success": True, "message": r["message"]})
                        except Exception as e:
                            results.append({"name": g["name"], "success": False, "error": str(e)})
                return self._send_json(200, {"success": True, "results": results})

            if pathname == "/api/games/launch":
                return self._send_json(200, launch_game_native(body.get("gameFolder")))

            if pathname == "/api/games/open-folder":
                return self._send_json(200, open_folder_native(body.get("path")))

            if pathname == "/api/games/save-ini":
                manifests = get_steam_manifests()
                g = scan_game(body.get("gameFolder"), None, manifests)
                t = g.get("exeFolder") or body.get("gameFolder")
                with open(os.path.join(t, "OptiScaler.ini"), "w", encoding="utf-8") as f:
                    f.write(body.get("content", ""))
                return self._send_json(200, {"success": True})

            if pathname == "/api/games/add-custom":
                fp = body.get("folderPath", "").strip()
                if not fp or not os.path.isdir(fp):
                    return self._send_json(400, {"success": False, "error": "Directory does not exist"})
                cfg = load_config()
                if fp not in cfg["customFolders"]:
                    cfg["customFolders"].append(fp)
                    save_config(cfg)
                return self._send_json(200, {"success": True, "games": scan_all_games()})

            if pathname == "/api/core/build":
                return self._send_json(200, start_network_build(body.get("dlssPath", ""), bool(body.get("wave64"))))

        except Exception as e:
            return self._send_json(500, {"success": False, "error": str(e)})

        return self._send_json(404, {"error": "Not found"})


def is_flatpak_app_installed(app_id):
    home = os.path.expanduser("~")
    candidates = [
        f"/var/lib/flatpak/exports/bin/{app_id}",
        os.path.join(home, ".local", "share", "flatpak", "exports", "bin", app_id),
        f"/var/lib/flatpak/app/{app_id}",
        os.path.join(home, ".local", "share", "flatpak", "app", app_id),
    ]
    return any(os.path.exists(c) for c in candidates)


def _try_spawn_browser(cmd, env, wait_sec=0.35):
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        deadline = time.monotonic() + wait_sec
        while time.monotonic() < deadline:
            rc = proc.poll()
            if rc is not None:
                return rc == 0
            time.sleep(0.05)
        return True
    except Exception:
        return False


def open_desktop_window(url):
    env = get_clean_desktop_env()
    search_path = env.get("PATH")

    # 1. Native Chromium-family browsers in chromeless desktop app mode
    native_chromium = [
        "chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
        "brave-browser", "brave", "microsoft-edge", "microsoft-edge-stable",
        "vivaldi", "vivaldi-stable",
    ]
    for b in native_chromium:
        exe = shutil.which(b, path=search_path)
        if exe and _try_spawn_browser([exe, f"--app={url}", "--window-size=1320,850"], env):
            return

    # 2. Flatpak Chromium-family browsers (standard on SteamOS / Bazzite) in chromeless app mode
    flatpak_exe = shutil.which("flatpak", path=search_path)
    flatpak_chromium = [
        "com.google.Chrome",
        "org.chromium.Chromium",
        "com.brave.Browser",
        "com.microsoft.Edge",
        "io.github.ungoogled_software.ungoogled_chromium",
        "com.vivaldi.Vivaldi",
    ]
    if flatpak_exe:
        for app_id in flatpak_chromium:
            if is_flatpak_app_installed(app_id):
                if _try_spawn_browser([flatpak_exe, "run", app_id, f"--app={url}", "--window-size=1320,850"], env):
                    return

    in_gamescope = (
        env.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"
        or env.get("SteamGamepadUI") == "1"
    )

    def try_firefox_fallbacks():
        if flatpak_exe:
            for ff_id in ("org.mozilla.firefox", "app.zen_browser.zen", "io.gitlab.librewolf-community", "net.waterfox.waterfox"):
                if is_flatpak_app_installed(ff_id):
                    if _try_spawn_browser([flatpak_exe, "run", ff_id, url], env):
                        return True
        ff_exe = shutil.which("firefox", path=search_path)
        if ff_exe and _try_spawn_browser([ff_exe, url], env):
            return True
        return False

    def try_xdg_fallbacks():
        for opener in (
            ["xdg-open", url],
            ["kioclient5", "exec", url],
            ["kioclient", "exec", url],
            ["kde-open5", url],
            ["gio", "open", url],
        ):
            exe = shutil.which(opener[0], path=search_path)
            if exe and _try_spawn_browser([exe] + opener[1:], env, wait_sec=0.6):
                return True
        return False

    # 3. In SteamOS Gaming Mode (gamescope), xdg-open often lacks a portal daemon, so try direct browser first
    if in_gamescope:
        if try_firefox_fallbacks() or try_xdg_fallbacks():
            return
    else:
        if try_xdg_fallbacks() or try_firefox_fallbacks():
            return

    try:
        webbrowser.open(url)
    except Exception:
        pass


def _is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _probe_existing_instance(port):
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/core/status")
        with urllib.request.urlopen(req, timeout=0.8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict) and "appVersion" in data:
                return data
    except Exception:
        pass
    return None


def _shutdown_existing_instance(port):
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/shutdown",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=0.8) as _resp:
            pass
        deadline = time.monotonic() + 1.5
        while time.monotonic() < deadline:
            if not _is_port_in_use(port):
                return True
            time.sleep(0.05)
    except Exception:
        pass
    return not _is_port_in_use(port)


def main():
    ensure_linux_environment()

    if "--list" in sys.argv:
        for g in scan_all_games():
            status = f"ACTIVE ({g['routeDisplay']})" if g["installed"] else f"Not Installed ({g['routeDisplay']})"
            print(f"- {g['name']} [{g['launcher']}] -> {status} ({g['folder']})")
        return

    port = 4280
    if _is_port_in_use(port):
        existing = _probe_existing_instance(port)
        if existing is not None:
            if existing.get("isBuilding"):
                url = f"http://127.0.0.1:{port}"
                print(f"[HelixSR Manager] Reconnecting to active instance on {url}")
                if "--no-browser" not in sys.argv:
                    open_desktop_window(url)
                return
            if not _shutdown_existing_instance(port):
                url = f"http://127.0.0.1:{port}"
                print(f"[HelixSR Manager] Opening existing instance on {url}")
                if "--no-browser" not in sys.argv:
                    open_desktop_window(url)
                return

    for p in range(4280, 4310):
        if not _is_port_in_use(p):
            port = p
            break

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("127.0.0.1", port), SwapperRequestHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"[HelixSR Manager] Running on {url} (Press Ctrl+C to quit)")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.4, lambda: open_desktop_window(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[HelixSR Manager] Shutting down cleanly.")
        server.server_close()


if __name__ == "__main__":
    main()
