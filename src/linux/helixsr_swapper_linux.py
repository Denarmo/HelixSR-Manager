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
            self.launcher_filter = "All"
            self.sort_mode = "Name (A-Z)"
            self.is_grid_view = True
            self.focused_index = -1
            self.is_handheld_mode = False
            self.build_log_queue = []
            self.drawer_tab = "guide"
            self.updating_drawer = False
            self.toast_after_id = None

            with BUILD_LOCK:
                BUILD_LISTENERS.append(self.build_log_queue)

            self.root.title(f"HelixSR Manager v{APP_VERSION} — Neural Upscaler & Game Manager")
            sw = max(1024, self.root.winfo_screenwidth())
            sh = max(680, self.root.winfo_screenheight())
            win_w = min(1320, sw - 40)
            win_h = min(840, sh - 60)
            pos_x = max(0, (sw - win_w) // 2)
            pos_y = max(0, (sh - win_h) // 2)
            self.root.geometry(f"{win_w}x{win_h}+{pos_x}+{pos_y}")
            self.root.minsize(920, 600)

            self._set_app_icon()
            self._apply_palette()
            self._build_layout()
            self._bind_shortcuts()

            handheld_info = detect_handheld_environment()
            in_gamescope = (
                os.environ.get("XDG_CURRENT_DESKTOP", "").lower() == "gamescope"
                or os.environ.get("SteamGamepadUI") == "1"
            )
            if in_gamescope or "--handheld" in sys.argv:
                self._toggle_handheld_mode(force_state=True)
            elif handheld_info.get("isHandheld"):
                self.legend_bar.pack(side="bottom", fill="x")

            self.root.after(80, self._initial_load)
            self.root.after(250, self._periodic_tick)
            if smoke_test_ms > 0:
                self.root.after(smoke_test_ms, self.root.destroy)

        def _set_app_icon(self):
            try:
                icon = tk.PhotoImage(width=32, height=32)
                icon.put("#f59e0b", to=(2, 2, 30, 30))
                icon.put("#fbbf24", to=(4, 4, 28, 16))
                bolt_pts = [
                    (17, 5, 20, 8), (15, 8, 19, 11), (12, 11, 17, 14),
                    (10, 14, 22, 17), (15, 17, 20, 20), (14, 20, 18, 23), (12, 23, 16, 27),
                ]
                for x1, y1, x2, y2 in bolt_pts:
                    icon.put("#0b0e14", to=(x1, y1, x2, y2))
                self._icon_ref = icon
                self.root.iconphoto(True, icon)
            except Exception:
                pass

        def _apply_palette(self):
            if self.is_light:
                self.c_bg = "#eef1f5"
                self.c_sidebar = "#ffffff"
                self.c_card = "#f8fafc"
                self.c_card_hover = "#e2e8f0"
                self.c_surface2 = "#e2e8f0"
                self.c_border = "#cbd5e1"
                self.c_emerald = "#059669"
                self.c_emerald_fg = "#ffffff"
                self.c_blue = "#2563eb"
                self.c_violet = "#7c3aed"
                self.c_amber = "#d97706"
                self.c_red = "#dc2626"
                self.c_text = "#0f172a"
                self.c_muted = "#475569"
                self.c_dim = "#64748b"
            else:
                self.c_bg = "#0b0e14"
                self.c_sidebar = "#0f141c"
                self.c_card = "#151c28"
                self.c_card_hover = "#1e293b"
                self.c_surface2 = "#1a2332"
                self.c_border = "#263246"
                self.c_emerald = "#10b981"
                self.c_emerald_fg = "#06130e"
                self.c_blue = "#3b82f6"
                self.c_violet = "#8b5cf6"
                self.c_amber = "#f59e0b"
                self.c_red = "#ef4444"
                self.c_text = "#f1f5f9"
                self.c_muted = "#94a3b8"
                self.c_dim = "#64748b"
            self.root.configure(bg=self.c_bg)

        def _build_layout(self):
            for child in self.root.winfo_children():
                child.destroy()

            # Bottom Handheld / Controller Legend Bar
            self.legend_bar = tk.Frame(self.root, bg=self.c_sidebar, highlightbackground=self.c_border, highlightthickness=1, height=34)
            legend_lbl = tk.Label(
                self.legend_bar,
                text="GAMEPAD / KEYBOARD:   [Arrows] Navigate Games   [Enter / Space] Configure / Install   [Esc] Close Drawer   [F5] Rescan   [F11] Fullscreen Handheld Mode",
                bg=self.c_sidebar,
                fg=self.c_muted,
                font=("Sans", 9, "bold"),
                padx=14,
                pady=6,
            )
            legend_lbl.pack(side="left")

            # Main Horizontal Container
            self.main_wrap = tk.Frame(self.root, bg=self.c_bg)
            self.main_wrap.pack(side="top", fill="both", expand=True)

            # ---- Left Sidebar ----
            self.sidebar = tk.Frame(self.main_wrap, bg=self.c_sidebar, width=235, highlightbackground=self.c_border, highlightthickness=1)
            self.sidebar.pack(side="left", fill="y")
            self.sidebar.pack_propagate(False)

            # Brand Header
            brand_frame = tk.Frame(self.sidebar, bg=self.c_sidebar, padx=16, pady=18)
            brand_frame.pack( side="top", fill="x")
            logo_lbl = tk.Label(
                brand_frame,
                text="⚡",
                bg=self.c_amber,
                fg="#0b0e14",
                font=("Sans", 15, "bold"),
                width=2,
                padx=4,
                pady=2,
            )
            logo_lbl.pack(side="left", padx=(0, 10))
            title_col = tk.Frame(brand_frame, bg=self.c_sidebar)
            title_col.pack(side="left", fill="x")
            tk.Label(title_col, text="HelixSR", bg=self.c_sidebar, fg=self.c_text, font=("Sans", 14, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                title_col,
                text=f"MANAGER v{APP_VERSION} · CORE v{CORE_VERSION}",
                bg=self.c_sidebar,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x")

            tk.Frame(self.sidebar, bg=self.c_border, height=1).pack(fill="x", padx=14, pady=(0, 10))

            # Navigation Items
            self.nav_buttons = {}
            nav_items = [
                ("games", "🎮  Games Library"),
                ("core", "⚡  Engine & Weights"),
                ("myfsr", "🧩  My-FSR & FrameGen"),
                ("settings", "⚙  Settings & Paths"),
                ("about", "ℹ  About & Guide"),
            ]
            for tab_id, label in nav_items:
                btn = tk.Button(
                    self.sidebar,
                    text=label,
                    anchor="w",
                    padx=16,
                    pady=9,
                    bd=0,
                    relief="flat",
                    cursor="hand2",
                    font=("Sans", 10, "bold"),
                    command=lambda tid=tab_id: self._switch_tab(tid),
                )
                btn.pack(fill="x", padx=10, pady=2)
                self.nav_buttons[tab_id] = btn

            # Sidebar Bottom Engine Status Card
            self.sidebar_card = tk.Frame(self.sidebar, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=12, pady=12)
            self.sidebar_card.pack(side="bottom", fill="x", padx=12, pady=14)
            tk.Label(self.sidebar_card, text="HELIXSR ENGINE STATUS", bg=self.c_card, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(fill="x")
            self.lbl_sidebar_status = tk.Label(self.sidebar_card, text="Checking core...", bg=self.c_card, fg=self.c_text, font=("Sans", 9, "bold"), anchor="w", pady=4)
            self.lbl_sidebar_status.pack(fill="x")
            self.btn_sidebar_compile = tk.Button(
                self.sidebar_card,
                text="Open Engine & Weights",
                bg=self.c_surface2,
                fg=self.c_text,
                activebackground=self.c_emerald,
                activeforeground=self.c_emerald_fg,
                bd=0,
                padx=8,
                pady=5,
                cursor="hand2",
                font=("Sans", 9, "bold"),
                command=lambda: self._switch_tab("core"),
            )
            self.btn_sidebar_compile.pack(fill="x", pady=(4, 0))
            gpus = get_gpu_info()
            gpu_name = gpus[0]["name"] if gpus else "Linux GPU"
            if len(gpu_name) > 30:
                gpu_name = gpu_name[:28] + ".."
            tk.Label(self.sidebar_card, text=gpu_name, bg=self.c_card, fg=self.c_dim, font=("Sans", 8), anchor="w").pack(fill="x", pady=(6, 0))

            # ---- Right Content Area ----
            self.content_area = tk.Frame(self.main_wrap, bg=self.c_bg)
            self.content_area.pack(side="left", fill="both", expand=True)

            # Toast Notification Bar (hidden by default)
            self.toast_frame = tk.Frame(self.content_area, bg=self.c_emerald, padx=16, pady=8)
            self.lbl_toast = tk.Label(self.toast_frame, text="", bg=self.c_emerald, fg=self.c_emerald_fg, font=("Sans", 10, "bold"), anchor="w")
            self.lbl_toast.pack(side="left", fill="x", expand=True)

            # Tab Panes Container
            self.panes_wrap = tk.Frame(self.content_area, bg=self.c_bg)
            self.panes_wrap.pack(fill="both", expand=True)

            self.panes = {}
            for tid in ("games", "core", "myfsr", "settings", "about"):
                f = tk.Frame(self.panes_wrap, bg=self.c_bg)
                self.panes[tid] = f

            self._build_games_pane(self.panes["games"])
            self._build_core_pane(self.panes["core"])
            self._build_myfsr_pane(self.panes["myfsr"])
            self._build_settings_pane(self.panes["settings"])
            self._build_about_pane(self.panes["about"])

            self._switch_tab(self.current_tab)

        def _show_toast(self, message, is_error=False):
            bg = self.c_red if is_error else self.c_emerald
            fg = "#ffffff" if is_error else self.c_emerald_fg
            self.toast_frame.configure(bg=bg)
            self.lbl_toast.configure(text=message, bg=bg, fg=fg)
            self.toast_frame.pack(side="top", fill="x", before=self.panes_wrap)
            if self.toast_after_id:
                try:
                    self.root.after_cancel(self.toast_after_id)
                except Exception:
                    pass
            self.toast_after_id = self.root.after(4200, lambda: self.toast_frame.pack_forget())

        def _switch_tab(self, tab_id):
            self.current_tab = tab_id
            for tid, f in self.panes.items():
                f.pack_forget()
            self.panes[tab_id].pack(fill="both", expand=True)

            for tid, btn in self.nav_buttons.items():
                if tid == tab_id:
                    btn.configure(bg=self.c_emerald, fg=self.c_emerald_fg, activebackground=self.c_emerald, activeforeground=self.c_emerald_fg)
                else:
                    btn.configure(bg=self.c_sidebar, fg=self.c_muted, activebackground=self.c_card_hover, activeforeground=self.c_text)

            if tab_id == "core":
                self._refresh_core_ui()
            elif tab_id == "myfsr":
                self._refresh_myfsr_ui()
            elif tab_id == "settings":
                self._refresh_settings_ui()

        # --------------------------------------------------------------------
        # TAB 1: GAMES LIBRARY
        # --------------------------------------------------------------------
        def _build_games_pane(self, parent):
            # Top Header & Action Bar
            top_bar = tk.Frame(parent, bg=self.c_bg, padx=18, pady=14)
            top_bar.pack(fill="x")

            title_box = tk.Frame(top_bar, bg=self.c_bg)
            title_box.pack(side="left")
            tk.Label(title_box, text="Games Library", bg=self.c_bg, fg=self.c_text, font=("Sans", 16, "bold"), anchor="w").pack(anchor="w")
            self.lbl_games_subtitle = tk.Label(
                title_box,
                text="Auto-detected Steam & Proton games compatible with HelixSR",
                bg=self.c_bg,
                fg=self.c_muted,
                font=("Sans", 9),
                anchor="w",
            )
            self.lbl_games_subtitle.pack(anchor="w")

            actions_box = tk.Frame(top_bar, bg=self.c_bg)
            actions_box.pack(side="right")

            self._make_btn(actions_box, "🔄 Scan Library", self._rescan_games, bg=self.c_surface2, fg=self.c_text).pack(side="left", padx=4)
            self._make_btn(actions_box, "➕ Add Game Folder", self._prompt_add_custom_folder, bg=self.c_surface2, fg=self.c_text).pack(side="left", padx=4)
            self._make_btn(actions_box, "⚡ Install All", self._install_all_games, bg=self.c_emerald, fg=self.c_emerald_fg).pack(side="left", padx=4)
            self._make_btn(actions_box, "↩ Restore All", self._uninstall_all_games, bg=self.c_surface2, fg=self.c_text).pack(side="left", padx=4)
            self.btn_handheld = self._make_btn(actions_box, "🎮 Handheld", self._toggle_handheld_mode, bg=self.c_surface2, fg=self.c_text)
            self.btn_handheld.pack(side="left", padx=4)

            # Stats Summary Row
            stats_row = tk.Frame(parent, bg=self.c_bg, padx=18, pady=2)
            stats_row.pack(fill="x")
            self.lbl_stat_total = self._make_stat_pill(stats_row, "TOTAL GAMES", "0", self.c_text)
            self.lbl_stat_active = self._make_stat_pill(stats_row, "HELIXSR ACTIVE", "0", self.c_emerald)
            self.lbl_stat_direct = self._make_stat_pill(stats_row, "DIRECT FSR 3.1", "0", self.c_blue)
            self.lbl_stat_opti = self._make_stat_pill(stats_row, "OPTISCALER / DLSS", "0", self.c_violet)

            # Filter & Search Toolbar
            filter_bar = tk.Frame(parent, bg=self.c_bg, padx=18, pady=10)
            filter_bar.pack(fill="x")

            search_wrap = tk.Frame(filter_bar, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=8, pady=4)
            search_wrap.pack(side="left", padx=(0, 10))
            tk.Label(search_wrap, text="🔍", bg=self.c_card, fg=self.c_muted, font=("Sans", 9)).pack(side="left")
            self.search_var = tk.StringVar()
            self.search_var.trace_add("write", lambda *_: self._apply_game_filters())
            self.entry_search = tk.Entry(
                search_wrap,
                textvariable=self.search_var,
                bg=self.c_card,
                fg=self.c_text,
                insertbackground=self.c_text,
                bd=0,
                width=24,
                font=("Sans", 10),
            )
            self.entry_search.pack(side="left", padx=6)

            self.filter_pill_btns = {}
            for fid, flabel in (
                ("all", "All"),
                ("installed", "Installed"),
                ("direct", "Direct FSR"),
                ("optiscaler", "OptiScaler"),
                ("dlss", "DLSS Loader"),
            ):
                b = tk.Button(
                    filter_bar,
                    text=flabel,
                    bd=0,
                    padx=10,
                    pady=5,
                    cursor="hand2",
                    font=("Sans", 9, "bold"),
                    command=lambda k=fid: self._set_quick_filter(k),
                )
                b.pack(side="left", padx=2)
                self.filter_pill_btns[fid] = b

            self.btn_view_toggle = self._make_btn(
                filter_bar,
                "☰ List View" if self.is_grid_view else "⊞ Grid View",
                self._toggle_view_mode,
                bg=self.c_surface2,
                fg=self.c_text,
            )
            self.btn_view_toggle.pack(side="right")

            # Main Split Body: Left Games Scroll Area + Right Inspector Drawer
            self.games_body = tk.Frame(parent, bg=self.c_bg, padx=18, pady=4)
            self.games_body.pack(fill="both", expand=True)

            # Left Scrollable Games List/Grid
            self.games_list_wrap = tk.Frame(self.games_body, bg=self.c_bg)
            self.games_list_wrap.pack(side="left", fill="both", expand=True)

            self.games_canvas = tk.Canvas(self.games_list_wrap, bg=self.c_bg, highlightthickness=0, bd=0)
            self.games_scrollbar = tk.Scrollbar(self.games_list_wrap, orient="vertical", command=self.games_canvas.yview)
            self.games_inner = tk.Frame(self.games_canvas, bg=self.c_bg)

            self.games_inner.bind(
                "<Configure>",
                lambda _e: self.games_canvas.configure(scrollregion=self.games_canvas.bbox("all")),
            )
            self.games_canvas_win = self.games_canvas.create_window((0, 0), window=self.games_inner, anchor="nw")
            self.games_canvas.bind("<Configure>", self._on_games_canvas_resize)
            self.games_canvas.configure(yscrollcommand=self.games_scrollbar.set)

            self.games_canvas.pack(side="left", fill="both", expand=True)
            self.games_scrollbar.pack(side="right", fill="y")

            # Mouse wheel scrolling for Linux (<Button-4>/<Button-5>) and Windows/macOS (<MouseWheel>)
            self.games_canvas.bind_all("<MouseWheel>", self._on_mousewheel)
            self.games_canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
            self.games_canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

            # Right Inspector Drawer (hidden until a game is selected)
            self.drawer_frame = tk.Frame(
                self.games_body,
                bg=self.c_card,
                width=420,
                highlightbackground=self.c_border,
                highlightthickness=1,
            )
            self._build_drawer_ui(self.drawer_frame)

            self._update_filter_pill_styles()

        def _make_btn(self, parent, text, cmd, bg=None, fg=None, padx=10, pady=6):
            return tk.Button(
                parent,
                text=text,
                command=cmd,
                bg=bg or self.c_surface2,
                fg=fg or self.c_text,
                activebackground=self.c_emerald,
                activeforeground=self.c_emerald_fg,
                bd=0,
                relief="flat",
                padx=padx,
                pady=pady,
                cursor="hand2",
                font=("Sans", 9, "bold"),
            )

        def _make_stat_pill(self, parent, title, val, color):
            card = tk.Frame(parent, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=14, pady=8)
            card.pack(side="left", fill="x", expand=True, padx=(0, 8))
            tk.Label(card, text=title, bg=self.c_card, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(fill="x")
            val_lbl = tk.Label(card, text=val, bg=self.c_card, fg=color, font=("Sans", 15, "bold"), anchor="w")
            val_lbl.pack(fill="x")
            return val_lbl

        def _on_games_canvas_resize(self, event):
            self.games_canvas.itemconfig(self.games_canvas_win, width=event.width)

        def _on_mousewheel(self, event):
            if self.current_tab == "games":
                self.games_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(self, event):
            if self.current_tab == "games":
                if event.num == 4:
                    self.games_canvas.yview_scroll(-3, "units")
                elif event.num == 5:
                    self.games_canvas.yview_scroll(3, "units")

        def _set_quick_filter(self, fid):
            self.quick_filter = fid
            self._update_filter_pill_styles()
            self._apply_game_filters()

        def _update_filter_pill_styles(self):
            for fid, btn in self.filter_pill_btns.items():
                if fid == self.quick_filter:
                    btn.configure(bg=self.c_emerald, fg=self.c_emerald_fg)
                else:
                    btn.configure(bg=self.c_card, fg=self.c_muted)

        def _toggle_view_mode(self):
            self.is_grid_view = not self.is_grid_view
            self.btn_view_toggle.configure(text="☰ List View" if self.is_grid_view else "⊞ Grid View")
            self._render_games()

        def _apply_game_filters(self):
            q = self.search_var.get().strip().lower() if hasattr(self, "search_var") else ""
            res = []
            for g in self.all_games:
                if q and q not in g["name"].lower() and q not in (g.get("folder") or "").lower():
                    continue
                if self.quick_filter == "installed" and not g.get("installed"):
                    continue
                if self.quick_filter == "direct" and g.get("route") != "direct":
                    continue
                if self.quick_filter == "optiscaler" and g.get("route") != "optiscaler":
                    continue
                if self.quick_filter == "dlss" and g.get("route") != "dlss":
                    continue
                res.append(g)
            self.filtered_games = res
            self._render_games()

        def _render_games(self):
            for child in self.games_inner.winfo_children():
                child.destroy()

            total = len(self.all_games)
            active = sum(1 for g in self.all_games if g.get("installed"))
            direct = sum(1 for g in self.all_games if g.get("route") == "direct")
            opti = sum(1 for g in self.all_games if g.get("route") in ("optiscaler", "dlss"))

            self.lbl_stat_total.configure(text=str(total))
            self.lbl_stat_active.configure(text=str(active))
            self.lbl_stat_direct.configure(text=str(direct))
            self.lbl_stat_opti.configure(text=str(opti))
            self.nav_buttons["games"].configure(text=f"🎮  Games Library ({total})")

            if not self.filtered_games:
                empty = tk.Frame(self.games_inner, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=30, pady=40)
                empty.pack(fill="x", pady=20, padx=10)
                tk.Label(empty, text="No matching games found", bg=self.c_card, fg=self.c_text, font=("Sans", 13, "bold")).pack(pady=(0, 6))
                tk.Label(
                    empty,
                    text="Click '➕ Add Game Folder' to add a game directory manually or '🔄 Scan Library' to refresh Steam libraries.",
                    bg=self.c_card,
                    fg=self.c_muted,
                    font=("Sans", 10),
                ).pack()
                return

            if self.is_grid_view:
                cols = 2 if self.selected_game else 3
                for c in range(cols):
                    self.games_inner.grid_columnconfigure(c, weight=1, uniform="gamecol")
                for idx, g in enumerate(self.filtered_games):
                    r = idx // cols
                    c = idx % cols
                    card = self._create_game_card(self.games_inner, g, idx)
                    card.grid(row=r, column=c, sticky="nsew", padx=5, pady=5)
            else:
                for idx, g in enumerate(self.filtered_games):
                    row = self._create_game_row(self.games_inner, g, idx)
                    row.pack(fill="x", pady=3, padx=2)

        def _create_game_card(self, parent, game, idx):
            is_sel = self.selected_game and canonical_key(self.selected_game["folder"]) == canonical_key(game["folder"])
            is_foc = idx == self.focused_index
            border_col = self.c_emerald if (is_sel or is_foc) else self.c_border
            border_w = 2 if (is_sel or is_foc) else 1

            card = tk.Frame(parent, bg=self.c_card, highlightbackground=border_col, highlightthickness=border_w, padx=12, pady=12, cursor="hand2")

            # Top Row: Launcher badge + Status badge
            top = tk.Frame(card, bg=self.c_card)
            top.pack(fill="x")
            tk.Label(
                top,
                text=(game.get("launcher") or "Game").upper(),
                bg=self.c_surface2,
                fg=self.c_muted,
                font=("Sans", 8, "bold"),
                padx=6,
                pady=2,
            ).pack(side="left")

            if game.get("installed"):
                tk.Label(
                    top,
                    text="● HELIXSR ACTIVE",
                    bg=self.c_emerald,
                    fg=self.c_emerald_fg,
                    font=("Sans", 8, "bold"),
                    padx=7,
                    pady=2,
                ).pack(side="right")
            else:
                tk.Label(
                    top,
                    text="NOT INSTALLED",
                    bg=self.c_surface2,
                    fg=self.c_dim,
                    font=("Sans", 8, "bold"),
                    padx=6,
                    pady=2,
                ).pack(side="right")

            # Game Name
            name_lbl = tk.Label(
                card,
                text=game["name"],
                bg=self.c_card,
                fg=self.c_text,
                font=("Sans", 11, "bold"),
                anchor="w",
                justify="left",
                wraplength=260,
            )
            name_lbl.pack(fill="x", pady=(10, 4))

            # Route Description
            route_col = self.c_blue if game.get("route") == "direct" else (self.c_amber if game.get("route") == "dlss" else self.c_violet)
            route_lbl = tk.Label(
                card,
                text=game.get("routeDisplay") or "OptiScaler",
                bg=self.c_card,
                fg=route_col,
                font=("Sans", 9, "bold"),
                anchor="w",
            )
            route_lbl.pack(fill="x")

            folder_short = game.get("folder") or ""
            if len(folder_short) > 42:
                folder_short = "..." + folder_short[-39:]
            path_lbl = tk.Label(card, text=folder_short, bg=self.c_card, fg=self.c_dim, font=("Sans", 8), anchor="w")
            path_lbl.pack(fill="x", pady=(2, 10))

            # Bottom Action Row
            btn_row = tk.Frame(card, bg=self.c_card)
            btn_row.pack(fill="x", side="bottom")
            action_txt = "⚙ Configure / Update" if game.get("installed") else "⚡ Configure & Install"
            btn = tk.Button(
                btn_row,
                text=action_txt,
                bg=self.c_surface2 if not is_sel else self.c_emerald,
                fg=self.c_text if not is_sel else self.c_emerald_fg,
                bd=0,
                padx=8,
                pady=5,
                cursor="hand2",
                font=("Sans", 9, "bold"),
                command=lambda g=game, i=idx: self._select_game(g, i),
            )
            btn.pack(fill="x")

            for w in (card, top, name_lbl, route_lbl, path_lbl):
                w.bind("<Button-1>", lambda _e, g=game, i=idx: self._select_game(g, i))

            return card

        def _create_game_row(self, parent, game, idx):
            is_sel = self.selected_game and canonical_key(self.selected_game["folder"]) == canonical_key(game["folder"])
            border_col = self.c_emerald if is_sel else self.c_border
            row = tk.Frame(parent, bg=self.c_card, highlightbackground=border_col, highlightthickness=1, padx=12, pady=8, cursor="hand2")

            status_txt = "ACTIVE" if game.get("installed") else "READY"
            status_bg = self.c_emerald if game.get("installed") else self.c_surface2
            status_fg = self.c_emerald_fg if game.get("installed") else self.c_dim
            tk.Label(row, text=status_txt, bg=status_bg, fg=status_fg, font=("Sans", 8, "bold"), width=8, pady=2).pack(side="left", padx=(0, 10))

            tk.Label(row, text=game["name"], bg=self.c_card, fg=self.c_text, font=("Sans", 10, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
            tk.Label(row, text=game.get("routeDisplay") or "", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), padx=10).pack(side="left")

            self._make_btn(
                row,
                "Configure",
                lambda g=game, i=idx: self._select_game(g, i),
                bg=self.c_emerald if is_sel else self.c_surface2,
                fg=self.c_emerald_fg if is_sel else self.c_text,
                padx=10,
                pady=3,
            ).pack(side="right")

            row.bind("<Button-1>", lambda _e, g=game, i=idx: self._select_game(g, i))
            return row

        # --------------------------------------------------------------------
        # RIGHT DRAWER: GAME CONFIGURATION & LOGS
        # --------------------------------------------------------------------
        def _build_drawer_ui(self, parent):
            # Header
            hdr = tk.Frame(parent, bg=self.c_sidebar, padx=14, pady=12)
            hdr.pack(fill="x")
            self.lbl_drawer_title = tk.Label(
                hdr,
                text="Select a Game",
                bg=self.c_sidebar,
                fg=self.c_text,
                font=("Sans", 12, "bold"),
                anchor="w",
                wraplength=330,
                justify="left",
            )
            self.lbl_drawer_title.pack(side="left", fill="x", expand=True)
            tk.Button(
                hdr,
                text="✕",
                bg=self.c_surface2,
                fg=self.c_text,
                bd=0,
                padx=8,
                pady=2,
                cursor="hand2",
                font=("Sans", 10, "bold"),
                command=self._close_drawer,
            ).pack(side="right")

            # Primary Install / Restore / Launch Buttons
            act = tk.Frame(parent, bg=self.c_card, padx=14, pady=10)
            act.pack(fill="x")

            self.btn_drawer_install = tk.Button(
                act,
                text="⚡ Install HelixSR",
                bg=self.c_emerald,
                fg=self.c_emerald_fg,
                bd=0,
                pady=8,
                cursor="hand2",
                font=("Sans", 10, "bold"),
                command=self._drawer_install_clicked,
            )
            self.btn_drawer_install.pack(fill="x", pady=(0, 6))

            sec_row = tk.Frame(act, bg=self.c_card)
            sec_row.pack(fill="x")
            self.btn_drawer_uninstall = self._make_btn(sec_row, "↩ Restore Original", self._drawer_uninstall_clicked, bg=self.c_red, fg="#ffffff")
            self.btn_drawer_uninstall.pack(side="left", fill="x", expand=True, padx=(0, 4))
            self.btn_drawer_launch = self._make_btn(sec_row, "▶ Launch", self._drawer_launch_clicked, bg=self.c_surface2, fg=self.c_text)
            self.btn_drawer_launch.pack(side="left", padx=2)
            self.btn_drawer_folder = self._make_btn(sec_row, "📂 Folder", self._drawer_folder_clicked, bg=self.c_surface2, fg=self.c_text)
            self.btn_drawer_folder.pack(side="left", padx=2)
            self.btn_drawer_cache = self._make_btn(sec_row, "🧹 Cache", self._drawer_cache_clicked, bg=self.c_surface2, fg=self.c_text)
            self.btn_drawer_cache.pack(side="left", padx=(2, 0))

            # Drawer Sub-Tabs
            sub_nav = tk.Frame(parent, bg=self.c_sidebar, padx=14, pady=6)
            sub_nav.pack(fill="x")
            self.drawer_tab_btns = {}
            for dt_id, dt_lbl in (("guide", "Configuration & Proton"), ("ini", "OptiScaler.ini"), ("logs", "Game Logs")):
                b = tk.Button(
                    sub_nav,
                    text=dt_lbl,
                    bd=0,
                    padx=8,
                    pady=4,
                    cursor="hand2",
                    font=("Sans", 9, "bold"),
                    command=lambda d=dt_id: self._switch_drawer_tab(d),
                )
                b.pack(side="left", padx=(0, 4))
                self.drawer_tab_btns[dt_id] = b

            self.drawer_body = tk.Frame(parent, bg=self.c_card, padx=14, pady=10)
            self.drawer_body.pack(fill="both", expand=True)

            # Sub-pane 1: Configuration & Proton Guide
            self.dpane_guide = tk.Frame(self.drawer_body, bg=self.c_card)

            # SteamOS / Linux Proton Launch Option Box
            proton_box = tk.Frame(self.dpane_guide, bg=self.c_surface2, highlightbackground=self.c_border, highlightthickness=1, padx=10, pady=8)
            proton_box.pack(fill="x", pady=(0, 10))
            tk.Label(
                proton_box,
                text="🐧 STEAMOS / PROTON LAUNCH OPTION",
                bg=self.c_surface2,
                fg=self.c_emerald,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x")
            p_row = tk.Frame(proton_box, bg=self.c_surface2)
            p_row.pack(fill="x", pady=(4, 0))
            self.proton_cmd_var = tk.StringVar()
            self.entry_proton_cmd = tk.Entry(
                p_row,
                textvariable=self.proton_cmd_var,
                bg=self.c_card,
                fg=self.c_text,
                readonlybackground=self.c_card,
                bd=0,
                font=("Monospace", 9),
                state="readonly",
            )
            self.entry_proton_cmd.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
            self._make_btn(p_row, "📋 Copy", self._copy_proton_launch_option, bg=self.c_emerald, fg=self.c_emerald_fg, padx=8, pady=3).pack(side="right")

            # Route selection
            tk.Label(self.dpane_guide, text="INSTALLATION METHOD", bg=self.c_card, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(fill="x", pady=(4, 2))
            self.var_route = tk.StringVar(value="optiscaler")
            self.route_options = [
                ("optiscaler", "OptiScaler Proxy (DLSS / XeSS / FSR -> HelixSR)"),
                ("direct", "Direct FSR 3.1 Swap (amd_fidelityfx_dx12.dll)"),
                ("dlss", "DLSS Loader (Experimental dxgi.dll + nvngx.dll)"),
            ]
            for r_val, r_lbl in self.route_options:
                rb = tk.Radiobutton(
                    self.dpane_guide,
                    text=r_lbl,
                    variable=self.var_route,
                    value=r_val,
                    bg=self.c_card,
                    fg=self.c_text,
                    selectcolor=self.c_surface2,
                    activebackground=self.c_card,
                    activeforeground=self.c_emerald,
                    font=("Sans", 9),
                    anchor="w",
                    command=self._on_drawer_option_changed,
                )
                rb.pack(fill="x")

            # OptiScaler Proxy DLL Name + FrameGen
            self.opti_opts_frame = tk.Frame(self.dpane_guide, bg=self.c_card)
            self.opti_opts_frame.pack(fill="x", pady=6)

            dll_row = tk.Frame(self.opti_opts_frame, bg=self.c_card)
            dll_row.pack(fill="x", pady=2)
            tk.Label(dll_row, text="Proxy DLL:", bg=self.c_card, fg=self.c_muted, font=("Sans", 9, "bold"), width=12, anchor="w").pack(side="left")
            self.var_opti_dll = tk.StringVar(value="dxgi.dll")
            self.opt_dll_menu = tk.OptionMenu(dll_row, self.var_opti_dll, *OPTI_NAMES, command=lambda _v: self._on_drawer_option_changed())
            self.opt_dll_menu.configure(bg=self.c_surface2, fg=self.c_text, bd=0, highlightthickness=0, font=("Sans", 9))
            self.opt_dll_menu.pack(side="left", fill="x", expand=True)

            fg_row = tk.Frame(self.opti_opts_frame, bg=self.c_card)
            fg_row.pack(fill="x", pady=4)
            tk.Label(fg_row, text="FrameGen:", bg=self.c_card, fg=self.c_muted, font=("Sans", 9, "bold"), width=12, anchor="w").pack(side="left")
            self.fg_label_to_key = {
                "Auto / Disabled": "auto",
                "OptiFG -> AMD FSR 3.1 FG": "optifg_fsrfg",
                "DLSS-G -> AMD FSR 3.1 FG": "dlssg_fsrfg",
                "DLSS-G -> Intel XeFG": "dlssg_xefg",
                "DLSS-G -> Nukem FG": "dlssg_nukems",
            }
            self.fg_key_to_label = {v: k for k, v in self.fg_label_to_key.items()}
            self.var_fg_label = tk.StringVar(value="Auto / Disabled")
            self.fg_menu = tk.OptionMenu(fg_row, self.var_fg_label, *self.fg_label_to_key.keys())
            self.fg_menu.configure(bg=self.c_surface2, fg=self.c_text, bd=0, highlightthickness=0, font=("Sans", 9))
            self.fg_menu.pack(side="left", fill="x", expand=True)

            self.var_fakenvapi = tk.BooleanVar(value=True)
            tk.Checkbutton(
                self.opti_opts_frame,
                text="Bundle FakeNVAPI (fakenvapi.dll for DLSS exposure)",
                variable=self.var_fakenvapi,
                bg=self.c_card,
                fg=self.c_text,
                selectcolor=self.c_surface2,
                activebackground=self.c_card,
                activeforeground=self.c_emerald,
                font=("Sans", 9),
                anchor="w",
            ).pack(fill="x", pady=2)

            self.var_reframework = tk.BooleanVar(value=False)
            tk.Checkbutton(
                self.dpane_guide,
                text="Install REFramework Nightly (Capcom RE Engine games)",
                variable=self.var_reframework,
                bg=self.c_card,
                fg=self.c_text,
                selectcolor=self.c_surface2,
                activebackground=self.c_card,
                activeforeground=self.c_emerald,
                font=("Sans", 9),
                anchor="w",
                command=self._on_drawer_option_changed,
            ).pack(fill="x", pady=2)

            self.lbl_drawer_info = tk.Label(
                self.dpane_guide,
                text="",
                bg=self.c_surface2,
                fg=self.c_muted,
                font=("Sans", 8),
                justify="left",
                anchor="nw",
                wraplength=380,
                padx=10,
                pady=8,
            )
            self.lbl_drawer_info.pack(fill="x", pady=(8, 0))

            # Sub-pane 2: OptiScaler.ini Editor
            self.dpane_ini = tk.Frame(self.drawer_body, bg=self.c_card)
            ini_btn_row = tk.Frame(self.dpane_ini, bg=self.c_card)
            ini_btn_row.pack(fill="x", pady=(0, 6))
            self._make_btn(ini_btn_row, "💾 Save OptiScaler.ini", self._save_drawer_ini, bg=self.c_emerald, fg=self.c_emerald_fg).pack(side="left", padx=(0, 6))
            self._make_btn(ini_btn_row, "🔄 Reload", self._reload_drawer_logs_and_ini, bg=self.c_surface2, fg=self.c_text).pack(side="left")
            self.txt_ini = tk.Text(self.dpane_ini, bg=self.c_bg, fg=self.c_text, insertbackground=self.c_text, font=("Monospace", 9), bd=0, wrap="none")
            self.txt_ini.pack(fill="both", expand=True)

            # Sub-pane 3: Game Logs
            self.dpane_logs = tk.Frame(self.drawer_body, bg=self.c_card)
            log_btn_row = tk.Frame(self.dpane_logs, bg=self.c_card)
            log_btn_row.pack(fill="x", pady=(0, 6))
            self._make_btn(log_btn_row, "🔄 Refresh Logs", self._reload_drawer_logs_and_ini, bg=self.c_surface2, fg=self.c_text).pack(side="left")
            self.txt_logs = tk.Text(self.dpane_logs, bg=self.c_bg, fg=self.c_text, font=("Monospace", 8), bd=0, wrap="word")
            self.txt_logs.pack(fill="both", expand=True)

            self._switch_drawer_tab("guide")

        def _switch_drawer_tab(self, dt_id):
            self.drawer_tab = dt_id
            for p in (self.dpane_guide, self.dpane_ini, self.dpane_logs):
                p.pack_forget()
            if dt_id == "guide":
                self.dpane_guide.pack(fill="both", expand=True)
            elif dt_id == "ini":
                self.dpane_ini.pack(fill="both", expand=True)
                self._reload_drawer_logs_and_ini()
            elif dt_id == "logs":
                self.dpane_logs.pack(fill="both", expand=True)
                self._reload_drawer_logs_and_ini()

            for k, b in self.drawer_tab_btns.items():
                if k == dt_id:
                    b.configure(bg=self.c_emerald, fg=self.c_emerald_fg)
                else:
                    b.configure(bg=self.c_surface2, fg=self.c_muted)

        def _select_game(self, game, idx=0):
            manifests = get_steam_manifests()
            fresh = scan_game(game["folder"], game["name"], manifests)
            self.selected_game = fresh
            self.focused_index = idx

            self.drawer_frame.pack(side="right", fill="y", padx=(10, 0))
            self.drawer_frame.pack_propagate(False)

            self.updating_drawer = True
            try:
                self.lbl_drawer_title.configure(text=fresh["name"])
                self.var_route.set(fresh.get("route") or "optiscaler")
                self.var_opti_dll.set(fresh.get("optiDllName") or "dxgi.dll")
                fg_key = fresh.get("fgMode") or "auto"
                self.var_fg_label.set(self.fg_key_to_label.get(fg_key, "Auto / Disabled"))
                self.var_fakenvapi.set(bool(fresh.get("useFakeNvapi", True)))
                self.var_reframework.set(bool(fresh.get("installReFramework", False)))

                if fresh.get("installed"):
                    self.btn_drawer_install.configure(text="⚡ Update / Reinstall HelixSR")
                    self.btn_drawer_uninstall.configure(state="normal")
                else:
                    self.btn_drawer_install.configure(text="⚡ Install HelixSR")
                    self.btn_drawer_uninstall.configure(state="disabled")

                self._update_drawer_proton_and_info()
            finally:
                self.updating_drawer = False

            if self.drawer_tab in ("ini", "logs"):
                self._reload_drawer_logs_and_ini()
            self._render_games()

        def _close_drawer(self):
            self.selected_game = None
            self.drawer_frame.pack_forget()
            self._render_games()

        def _on_drawer_option_changed(self):
            if self.updating_drawer or not self.selected_game:
                return
            self._update_drawer_proton_and_info()

        def _update_drawer_proton_and_info(self):
            if not self.selected_game:
                return
            route = self.var_route.get()
            opti_dll = self.var_opti_dll.get()
            install_ref = self.var_reframework.get()

            if route == "optiscaler":
                self.opti_opts_frame.pack(fill="x", pady=6)
            else:
                self.opti_opts_frame.pack_forget()

            proton_cmd = compute_proton_launch_option(route, opti_dll, install_ref)
            self.proton_cmd_var.set(proton_cmd or "(No DLL override needed for Direct FSR 3.1)")

            exe_dir = self.selected_game.get("exeFolder") or self.selected_game.get("folder") or ""
            inputs = []
            if self.selected_game.get("hasDlss"):
                inputs.append("DLSS")
            if self.selected_game.get("hasXess"):
                inputs.append("XeSS")
            if self.selected_game.get("fsrTargets"):
                inputs.append("FSR 3.1")
            inputs_str = ", ".join(inputs) if inputs else "Generic DirectX 12"

            guide = (
                f"Target Folder: {exe_dir}\n"
                f"Detected Upscalers: {inputs_str}\n\n"
                "SteamOS / Proton Setup:\n"
                "1. Click 'Install HelixSR' above.\n"
                "2. Copy the Proton Launch Option above into Steam -> Game Properties -> Launch Options.\n"
                "3. Enable DLSS or FSR in the game's graphics settings (press Insert in-game for OptiScaler menu)."
            )
            self.lbl_drawer_info.configure(text=guide)

        def _copy_proton_launch_option(self):
            cmd = self.proton_cmd_var.get()
            if not cmd or cmd.startswith("("):
                self._show_toast("No special Proton launch option needed for Direct FSR 3.1.")
                return
            try:
                self.root.clipboard_clear()
                self.root.clipboard_append(cmd)
                self.root.update()
            except Exception:
                pass
            if os.name != "nt":
                for clip_cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
                    if shutil.which(clip_cmd[0]):
                        try:
                            p = subprocess.Popen(clip_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=get_clean_desktop_env())
                            p.communicate(input=cmd.encode("utf-8"), timeout=1.5)
                            break
                        except Exception:
                            pass
            self._show_toast(f"Copied to clipboard: {cmd}")

        def _drawer_install_clicked(self):
            if not self.selected_game:
                return
            try:
                fg_mode = self.fg_label_to_key.get(self.var_fg_label.get(), "auto")
                res = install_helixsr(
                    self.selected_game["folder"],
                    route_override=self.var_route.get(),
                    opti_dll=self.var_opti_dll.get(),
                    use_fakenvapi=self.var_fakenvapi.get(),
                    install_ref=self.var_reframework.get(),
                    fg_mode=fg_mode,
                )
                self._show_toast(res["message"])
                self._rescan_games(keep_selection=True)
            except Exception as e:
                self._show_toast(str(e), is_error=True)
                if "not been compiled yet" in str(e):
                    self._switch_tab("core")

        def _drawer_uninstall_clicked(self):
            if not self.selected_game:
                return
            try:
                res = uninstall_helixsr(self.selected_game["folder"])
                self._show_toast(res["message"])
                self._rescan_games(keep_selection=True)
            except Exception as e:
                self._show_toast(str(e), is_error=True)

        def _drawer_launch_clicked(self):
            if not self.selected_game:
                return
            res = launch_game_native(self.selected_game["folder"])
            if res.get("success"):
                self._show_toast(res.get("message", "Launching game..."))
            else:
                self._show_toast(res.get("error", "Could not launch game"), is_error=True)

        def _drawer_folder_clicked(self):
            if not self.selected_game:
                return
            target = self.selected_game.get("exeFolder") or self.selected_game.get("folder")
            res = open_folder_native(target)
            if not res.get("success"):
                self._show_toast(res.get("error", "Could not open folder"), is_error=True)

        def _drawer_cache_clicked(self):
            if not self.selected_game:
                return
            cleared = clear_shader_cache(self.selected_game)
            msg = f"Cleared shader & Proton pipeline cache for {self.selected_game['name']}!" if cleared else "No cached shader files found."
            self._show_toast(msg)

        def _reload_drawer_logs_and_ini(self):
            if not self.selected_game:
                return
            data = get_game_logs_and_ini(self.selected_game["folder"])
            self.txt_ini.delete("1.0", "end")
            self.txt_ini.insert("1.0", data["optiscalerIni"] or "# OptiScaler.ini not created yet. Install HelixSR (OptiScaler route) first.")

            combined_logs = ""
            if data["helixsrLog"]:
                combined_logs += "=== helixsr.log ===\n" + data["helixsrLog"] + "\n\n"
            if data["optiscalerLog"]:
                combined_logs += "=== OptiScaler.log ===\n" + data["optiscalerLog"] + "\n"
            if not combined_logs:
                combined_logs = "No log files found yet. Launch the game after installing HelixSR to generate logs."
            self.txt_logs.delete("1.0", "end")
            self.txt_logs.insert("1.0", combined_logs)

        def _save_drawer_ini(self):
            if not self.selected_game:
                return
            data = get_game_logs_and_ini(self.selected_game["folder"])
            exe_dir = data.get("exeFolder") or self.selected_game["folder"]
            try:
                content = self.txt_ini.get("1.0", "end-1c")
                with open(os.path.join(exe_dir, "OptiScaler.ini"), "w", encoding="utf-8") as f:
                    f.write(content)
                self._show_toast("Saved OptiScaler.ini successfully!")
            except Exception as e:
                self._show_toast(f"Failed to save OptiScaler.ini: {e}", is_error=True)

        # --------------------------------------------------------------------
        # TAB 2: ENGINE & WEIGHTS
        # --------------------------------------------------------------------
        def _build_core_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_bg, padx=22, pady=18)
            wrap.pack(fill="both", expand=True)

            tk.Label(wrap, text="HelixSR Engine & Neural Network Weights", bg=self.c_bg, fg=self.c_text, font=("Sans", 16, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                wrap,
                text="Compile the HelixSR neural network weights & RDNA compute kernels into amd_fidelityfx_dx12.dll (one-time build).",
                bg=self.c_bg,
                fg=self.c_muted,
                font=("Sans", 9),
                anchor="w",
            ).pack(fill="x", pady=(2, 14))

            cards_row = tk.Frame(wrap, bg=self.c_bg)
            cards_row.pack(fill="x", pady=(0, 14))
            self.lbl_core_ver = self._make_stat_pill(cards_row, "CORE VERSION", f"v{CORE_VERSION}", self.c_text)
            self.lbl_core_status = self._make_stat_pill(cards_row, "NETWORK STATUS", "Checking...", self.c_amber)
            self.lbl_core_weights = self._make_stat_pill(cards_row, "WEIGHTS SIZE", "0 KB", self.c_blue)
            self.lbl_core_kernels = self._make_stat_pill(cards_row, "KERNELS SIZE", "0 KB", self.c_violet)

            # Compiler Configuration Card
            cfg_card = tk.Frame(wrap, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=16, pady=14)
            cfg_card.pack(fill="x", pady=(0, 14))

            tk.Label(
                cfg_card,
                text="DLSS 310.7.0 WEIGHTS SOURCE (OPTIONAL LOCAL OVERRIDE)",
                bg=self.c_card,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x")

            src_row = tk.Frame(cfg_card, bg=self.c_card)
            src_row.pack(fill="x", pady=8)
            self.dlss_source_var = tk.StringVar(value="")
            self.entry_dlss_source = tk.Entry(
                src_row,
                textvariable=self.dlss_source_var,
                bg=self.c_bg,
                fg=self.c_text,
                insertbackground=self.c_text,
                bd=0,
                font=("Sans", 10),
            )
            self.entry_dlss_source.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
            self._make_btn(src_row, "📂 Browse nvngx_dlss.dll...", self._browse_dlss_dll, bg=self.c_surface2, fg=self.c_text).pack(side="left", padx=(0, 8))
            self.btn_start_build = self._make_btn(
                src_row,
                "⚡ Build HelixSR Network",
                self._on_start_build_clicked,
                bg=self.c_emerald,
                fg=self.c_emerald_fg,
                padx=16,
                pady=7,
            )
            self.btn_start_build.pack(side="right")

            tk.Label(
                cfg_card,
                text="Leave blank to automatically download NVIDIA's official DLSS 310.7.0 DLL from GitHub during compilation. On SteamOS, Proton/Wine and portable Python are configured automatically.",
                bg=self.c_card,
                fg=self.c_muted,
                font=("Sans", 8),
                anchor="w",
            ).pack(fill="x")

            # Live Compiler Console
            tk.Label(wrap, text="LIVE COMPILER CONSOLE", bg=self.c_bg, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(fill="x", pady=(0, 4))
            self.txt_build_console = tk.Text(
                wrap,
                bg="#070a0e" if not self.is_light else "#1e293b",
                fg="#10b981",
                font=("Monospace", 9),
                bd=0,
                padx=12,
                pady=10,
                wrap="word",
            )
            self.txt_build_console.pack(fill="both", expand=True)
            self.txt_build_console.insert("1.0", "[HelixSR Manager] Ready. Click 'Build HelixSR Network' to compile weights and RDNA shaders.\n")

        def _browse_dlss_dll(self):
            path = filedialog.askopenfilename(
                title="Select nvngx_dlss.dll",
                filetypes=[("DLSS DLL", "nvngx_dlss.dll *.dll"), ("All Files", "*.*")],
            )
            if path:
                self.dlss_source_var.set(path)

        def _on_start_build_clicked(self):
            if IS_BUILDING:
                self._show_toast("A network build is already in progress.", is_error=True)
                return
            self.txt_build_console.delete("1.0", "end")
            dlss_path = self.dlss_source_var.get().strip()
            res = start_network_build(dlss_path=dlss_path)
            if res.get("success"):
                self._show_toast("Started HelixSR Network compilation!")
                self._refresh_core_ui()
            else:
                self._show_toast(res.get("error", "Could not start build"), is_error=True)

        def _refresh_core_ui(self):
            st = get_core_status()
            built = st.get("weightsBuilt", False)
            if built:
                self.lbl_core_status.configure(text="READY (BUILT)", fg=self.c_emerald)
                self.lbl_sidebar_status.configure(text="● Network Ready & Built", fg=self.c_emerald)
            else:
                self.lbl_core_status.configure(text="NOT BUILT", fg=self.c_amber)
                self.lbl_sidebar_status.configure(text="● Setup Required (Click below)", fg=self.c_amber)

            w_kb = int((st.get("weightsSize") or 0) / 1024)
            k_kb = int((st.get("kernelsSize") or 0) / 1024)
            self.lbl_core_weights.configure(text=f"{w_kb:,} KB" if w_kb else "Not Built")
            self.lbl_core_kernels.configure(text=f"{k_kb:,} KB" if k_kb else "Not Built")

            if IS_BUILDING:
                self.btn_start_build.configure(text="⏳ Compiling Network...", state="disabled")
            else:
                self.btn_start_build.configure(
                    text="⚡ Rebuild HelixSR Network" if built else "⚡ Build HelixSR Network",
                    state="normal",
                )

        # --------------------------------------------------------------------
        # TAB 3: MY-FSR & FRAMEGEN
        # --------------------------------------------------------------------
        def _build_myfsr_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_bg, padx=22, pady=18)
            wrap.pack(fill="both", expand=True)

            tk.Label(wrap, text="My-FSR & Custom Frame Generation DLLs", bg=self.c_bg, fg=self.c_text, font=("Sans", 16, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                wrap,
                text="Drop custom FSR upscaler DLLs (such as FSR 4) or Frame Generation DLLs into core/my-fsr to bundle them into OptiScaler games.",
                bg=self.c_bg,
                fg=self.c_muted,
                font=("Sans", 9),
                anchor="w",
            ).pack(fill="x", pady=(2, 14))

            btn_row = tk.Frame(wrap, bg=self.c_bg)
            btn_row.pack(fill="x", pady=(0, 12))
            self._make_btn(btn_row, "➕ Import Custom DLL...", self._import_myfsr_dll, bg=self.c_emerald, fg=self.c_emerald_fg).pack(side="left", padx=(0, 8))
            self._make_btn(btn_row, "📂 Open core/my-fsr Folder", self._open_core_myfsr_folder, bg=self.c_surface2, fg=self.c_text).pack(side="left", padx=(0, 8))
            self._make_btn(btn_row, "🔄 Refresh List", self._refresh_myfsr_ui, bg=self.c_surface2, fg=self.c_text).pack(side="left")

            self.myfsr_list_frame = tk.Frame(wrap, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=16, pady=14)
            self.myfsr_list_frame.pack(fill="both", expand=True)

        def _refresh_myfsr_ui(self):
            for child in self.myfsr_list_frame.winfo_children():
                child.destroy()
            my_fsr_dir = os.path.join(CORE_DIR, MY_FSR_FOLDER)
            os.makedirs(my_fsr_dir, exist_ok=True)
            tk.Label(self.myfsr_list_frame, text=f"Directory: {my_fsr_dir}", bg=self.c_card, fg=self.c_dim, font=("Sans", 9), anchor="w").pack(fill="x", pady=(0, 10))

            dlls = [f for f in os.listdir(my_fsr_dir) if f.lower().endswith(".dll")] if os.path.isdir(my_fsr_dir) else []
            if not dlls:
                tk.Label(
                    self.myfsr_list_frame,
                    text="No custom DLLs currently in core/my-fsr.\n\n" + MY_FSR_README,
                    bg=self.c_card,
                    fg=self.c_muted,
                    font=("Sans", 9),
                    justify="left",
                    anchor="w",
                ).pack(fill="x")
            else:
                for fn in sorted(dlls):
                    fp = os.path.join(my_fsr_dir, fn)
                    sz_kb = int(os.path.getsize(fp) / 1024)
                    r = tk.Frame(self.myfsr_list_frame, bg=self.c_surface2, padx=10, pady=6)
                    r.pack(fill="x", pady=3)
                    tk.Label(r, text=f"🧩 {fn} ({sz_kb:,} KB)", bg=self.c_surface2, fg=self.c_text, font=("Sans", 9, "bold")).pack(side="left")

        def _import_myfsr_dll(self):
            path = filedialog.askopenfilename(title="Select Custom FSR or FrameGen DLL", filetypes=[("DLL Files", "*.dll"), ("All Files", "*.*")])
            if path and os.path.isfile(path):
                my_fsr_dir = os.path.join(CORE_DIR, MY_FSR_FOLDER)
                os.makedirs(my_fsr_dir, exist_ok=True)
                dst = os.path.join(my_fsr_dir, os.path.basename(path))
                shutil.copy2(path, dst)
                self._show_toast(f"Imported {os.path.basename(path)} into core/my-fsr!")
                self._refresh_myfsr_ui()

        def _open_core_myfsr_folder(self):
            my_fsr_dir = os.path.join(CORE_DIR, MY_FSR_FOLDER)
            os.makedirs(my_fsr_dir, exist_ok=True)
            open_folder_native(my_fsr_dir)

        # --------------------------------------------------------------------
        # TAB 4: SETTINGS & PATHS
        # --------------------------------------------------------------------
        def _build_settings_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_bg, padx=22, pady=18)
            wrap.pack(fill="both", expand=True)

            tk.Label(wrap, text="Settings & Library Paths", bg=self.c_bg, fg=self.c_text, font=("Sans", 16, "bold"), anchor="w").pack(fill="x", pady=(0, 14))

            app_card = tk.Frame(wrap, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=16, pady=12)
            app_card.pack(fill="x", pady=(0, 14))
            tk.Label(app_card, text="APPEARANCE & DISPLAY", bg=self.c_card, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(fill="x", pady=(0, 6))
            row = tk.Frame(app_card, bg=self.c_card)
            row.pack(fill="x")
            self._make_btn(
                row,
                "☀ Switch to Light Theme" if not self.is_light else "🌙 Switch to Aurora Dark Theme",
                self._toggle_theme,
                bg=self.c_surface2,
                fg=self.c_text,
            ).pack(side="left", padx=(0, 8))
            self._make_btn(row, "🎮 Toggle Fullscreen Handheld Mode (F11)", self._toggle_handheld_mode, bg=self.c_surface2, fg=self.c_text).pack(side="left")

            self.settings_paths_frame = tk.Frame(wrap, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=16, pady=12)
            self.settings_paths_frame.pack(fill="both", expand=True)

        def _refresh_settings_ui(self):
            for child in self.settings_paths_frame.winfo_children():
                child.destroy()

            tk.Label(
                self.settings_paths_frame,
                text="AUTO-DETECTED STEAM LIBRARIES (INTERNAL & MICROSD)",
                bg=self.c_card,
                fg=self.c_dim,
                font=("Sans", 8, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(0, 4))

            libs = get_steam_libraries()
            if not libs:
                tk.Label(self.settings_paths_frame, text="No Steam library folders detected.", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), anchor="w").pack(fill="x")
            else:
                for lib in libs:
                    tk.Label(self.settings_paths_frame, text=f"• {lib}", bg=self.c_card, fg=self.c_text, font=("Monospace", 9), anchor="w").pack(fill="x", pady=1)

            tk.Frame(self.settings_paths_frame, bg=self.c_border, height=1).pack(fill="x", pady=12)

            hdr = tk.Frame(self.settings_paths_frame, bg=self.c_card)
            hdr.pack(fill="x", pady=(0, 6))
            tk.Label(hdr, text="CUSTOM GAME FOLDERS (HEROIC / LUTRIS / STANDALONE)", bg=self.c_card, fg=self.c_dim, font=("Sans", 8, "bold"), anchor="w").pack(side="left")
            self._make_btn(hdr, "➕ Add Folder", self._prompt_add_custom_folder, bg=self.c_emerald, fg=self.c_emerald_fg, padx=8, pady=3).pack(side="right")

            customs = load_config().get("customFolders", [])
            if not customs:
                tk.Label(self.settings_paths_frame, text="No custom game folders added yet.", bg=self.c_card, fg=self.c_muted, font=("Sans", 9), anchor="w").pack(fill="x")
            else:
                for cf in customs:
                    r = tk.Frame(self.settings_paths_frame, bg=self.c_surface2, padx=10, pady=5)
                    r.pack(fill="x", pady=2)
                    tk.Label(r, text=cf, bg=self.c_surface2, fg=self.c_text, font=("Monospace", 9), anchor="w").pack(side="left", fill="x", expand=True)
                    self._make_btn(r, "Remove", lambda p=cf: self._remove_custom_folder(p), bg=self.c_red, fg="#ffffff", padx=8, pady=2).pack(side="right")

        # --------------------------------------------------------------------
        # TAB 5: ABOUT
        # --------------------------------------------------------------------
        def _build_about_pane(self, parent):
            wrap = tk.Frame(parent, bg=self.c_bg, padx=22, pady=18)
            wrap.pack(fill="both", expand=True)

            card = tk.Frame(wrap, bg=self.c_card, highlightbackground=self.c_border, highlightthickness=1, padx=20, pady=20)
            card.pack(fill="both", expand=True)

            tk.Label(card, text=f"HelixSR Manager v{APP_VERSION}", bg=self.c_card, fg=self.c_text, font=("Sans", 18, "bold"), anchor="w").pack(fill="x")
            tk.Label(
                card,
                text=f"Bundled HelixSR Core v{CORE_VERSION} · Standalone Native Linux & SteamOS Desktop Application",
                bg=self.c_card,
                fg=self.c_emerald,
                font=("Sans", 10, "bold"),
                anchor="w",
            ).pack(fill="x", pady=(2, 14))

            about_text = (
                "HelixSR runs NVIDIA's DLSS Super Resolution (Model E convolutional autoencoder) on AMD RDNA 2 / RDNA 3 / RDNA 4 "
                "and any Vulkan / DirectX 12 GPU through Proton/Wine and native DX12.\n\n"
                "Supported Installation Routes:\n"
                "• OptiScaler Proxy (Recommended): Hooks DLSS / XeSS / FSR inputs via dxgi.dll and routes upscaling to HelixSR.\n"
                "• Direct FSR 3.1 Swap: Replaces amd_fidelityfx_dx12.dll / amd_fidelityfx_upscaler_dx12.dll directly in FSR 3.1 games.\n"
                "• DLSS Loader (Experimental): Uses HelixSR's native DLSS loader (dxgi.dll + nvngx.dll) without OptiScaler.\n\n"
                "SteamOS & Linux Quick Start:\n"
                "1. Open 'Engine & Weights' and click 'Build HelixSR Network' once to compile the neural weights & RDNA shaders.\n"
                "2. Select any game in 'Games Library' and click 'Install HelixSR'.\n"
                "3. Copy the displayed Proton Launch Option into Steam -> Game Properties -> Launch Options."
            )
            tk.Label(card, text=about_text, bg=self.c_card, fg=self.c_muted, font=("Sans", 10), justify="left", anchor="nw", wraplength=780).pack(fill="x")

        # --------------------------------------------------------------------
        # ACTIONS, SHORTCUTS & PERIODIC POLLING
        # --------------------------------------------------------------------
        def _initial_load(self):
            self._rescan_games()
            self._refresh_core_ui()

        def _rescan_games(self, keep_selection=False):
            prev_folder = self.selected_game["folder"] if (keep_selection and self.selected_game) else None
            self.all_games = scan_all_games()
            self._apply_game_filters()
            if prev_folder:
                for i, g in enumerate(self.filtered_games):
                    if canonical_key(g["folder"]) == canonical_key(prev_folder):
                        self._select_game(g, i)
                        break

        def _prompt_add_custom_folder(self):
            folder = filedialog.askdirectory(title="Select Game Installation Folder")
            if folder and os.path.isdir(folder):
                cfg = load_config()
                norm = normalize_path(folder)
                if norm not in cfg["customFolders"]:
                    cfg["customFolders"].append(norm)
                    save_config(cfg)
                self._rescan_games()
                self._refresh_settings_ui()
                self._show_toast(f"Added game folder: {os.path.basename(norm)}")

        def _remove_custom_folder(self, folder_path):
            cfg = load_config()
            if folder_path in cfg.get("customFolders", []):
                cfg["customFolders"].remove(folder_path)
                save_config(cfg)
            self._rescan_games()
            self._refresh_settings_ui()
            self._show_toast("Removed custom game folder.")

        def _install_all_games(self):
            st = get_core_status()
            if not st["weightsBuilt"]:
                self._show_toast("Please build the HelixSR Network first in 'Engine & Weights'!", is_error=True)
                self._switch_tab("core")
                return
            installed_count = 0
            for g in self.all_games:
                if not g.get("installed") and g.get("route"):
                    try:
                        install_helixsr(g["folder"])
                        installed_count += 1
                    except Exception:
                        pass
            self._rescan_games(keep_selection=True)
            self._show_toast(f"Installed HelixSR in {installed_count} game(s)!")

        def _uninstall_all_games(self):
            restored_count = 0
            for g in self.all_games:
                if g.get("installed"):
                    try:
                        uninstall_helixsr(g["folder"])
                        restored_count += 1
                    except Exception:
                        pass
            self._rescan_games(keep_selection=True)
            self._show_toast(f"Restored original files in {restored_count} game(s).")

        def _toggle_theme(self):
            self.is_light = not self.is_light
            cfg = load_config()
            cfg["lightTheme"] = self.is_light
            save_config(cfg)
            self._apply_palette()
            self._build_layout()
            self._render_games()
            self._refresh_core_ui()

        def _toggle_handheld_mode(self, force_state=None):
            if force_state is not None:
                self.is_handheld_mode = bool(force_state)
            else:
                self.is_handheld_mode = not self.is_handheld_mode
            try:
                self.root.attributes("-fullscreen", self.is_handheld_mode)
            except Exception:
                pass
            if self.is_handheld_mode:
                self.legend_bar.pack(side="bottom", fill="x", before=self.main_wrap)
            else:
                self.legend_bar.pack_forget()

        def _bind_shortcuts(self):
            self.root.bind("<F11>", lambda _e: self._toggle_handheld_mode())
            self.root.bind("<F5>", lambda _e: self._rescan_games(keep_selection=True))
            self.root.bind("<Escape>", lambda _e: self._close_drawer() if self.selected_game else None)
            self.root.bind("<Down>", lambda _e: self._move_focus(1))
            self.root.bind("<Right>", lambda _e: self._move_focus(1))
            self.root.bind("<Up>", lambda _e: self._move_focus(-1))
            self.root.bind("<Left>", lambda _e: self._move_focus(-1))
            self.root.bind("<Return>", lambda _e: self._activate_focused())

        def _move_focus(self, delta):
            if self.current_tab != "games" or not self.filtered_games:
                return
            self.focused_index = max(0, min(len(self.filtered_games) - 1, self.focused_index + delta))
            self._render_games()

        def _activate_focused(self):
            if self.current_tab == "games" and 0 <= self.focused_index < len(self.filtered_games):
                self._select_game(self.filtered_games[self.focused_index], self.focused_index)

        def _periodic_tick(self):
            # 1. Check single-instance wakeup flag so clicking .desktop again focuses this window
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

            # 2. Drain live build logs into console
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

