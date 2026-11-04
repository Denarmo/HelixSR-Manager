#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HelixSR Manager for Decky: bridge between the Decky backend (main.py) and the
HelixSR Manager Linux engine (src/linux/helixsr_swapper_linux.py, copied into
py_modules/ as helixsr_engine.py when the plugin is packaged).

Runs either as a CLI (`python3 helixsr_bridge.py <command> '<json args>'`,
prints one JSON object) or in-process through run(command, args). The CLI form
is preferred: SteamOS's system Python has the full standard library, Decky's
bundled interpreter may not.
"""

import inspect
import json
import os
import re
import shutil
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

_engine = None
_core_note = ""


def _home():
    return os.environ.get("HOME") or os.path.expanduser("~")


def data_dir():
    xdg = os.environ.get("XDG_DATA_HOME") or os.path.join(_home(), ".local", "share")
    return os.path.join(xdg, "HelixSR")


def settings_dir():
    d = os.environ.get("HELIXSR_DECKY_SETTINGS") or os.path.join(data_dir(), "decky")
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".write_probe")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return d
    except Exception:
        d = os.path.join(data_dir(), "decky")
        os.makedirs(d, exist_ok=True)
        return d


def load_settings():
    p = os.path.join(settings_dir(), "settings.json")
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_settings(data):
    p = os.path.join(settings_dir(), "settings.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, p)


def _bundled_core_root():
    return os.environ.get("HELIXSR_DECKY_CORE_BUNDLE") or os.path.join(os.path.dirname(HERE), "helixsr_core")


def _manager_app_dir():
    """Folder of an installed HelixSR Manager (Python edition writes app_dir.txt on every start)."""
    p = os.path.join(data_dir(), "app_dir.txt")
    try:
        with open(p, "r", encoding="utf-8") as f:
            d = f.read().strip()
        return d if d and os.path.isdir(d) else None
    except Exception:
        return None


def _is_writable(d):
    try:
        probe = os.path.join(d, ".helixsr_write_probe")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except Exception:
        return False


def _copy_tree(src, dst):
    tmp = dst + ".partial"
    if os.path.isdir(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    shutil.copytree(src, tmp)
    os.replace(tmp, dst)


def resolve_core(engine):
    """Pick the HelixSR core to use, preferring one whose network is already built.

    Order: settings "corePath", $HELIXSR_CORE, the installed Manager's core, the
    data-folder copy (shared with the Flutter app), then the core bundled in the
    plugin (copied to the data folder so a network build can write into it).
    """
    global _core_note
    folder = f"HelixSR-{engine.CORE_VERSION}"
    settings = load_settings()
    candidates = []
    if settings.get("corePath"):
        candidates.append(("settings", settings["corePath"]))
    if os.environ.get("HELIXSR_CORE"):
        candidates.append(("env", os.environ["HELIXSR_CORE"]))
    app_dir = _manager_app_dir()
    if app_dir:
        candidates.append(("manager", os.path.join(app_dir, "helixsr_core", folder)))
    data_core = os.path.join(data_dir(), "core", folder)
    candidates.append(("data", data_core))
    bundled = os.path.join(_bundled_core_root(), folder)

    existing = [(src, c) for src, c in candidates if os.path.isfile(os.path.join(c, engine.DLL_FSR))]
    for src, c in existing:
        if engine.has_embedded_network(os.path.join(c, engine.DLL_FSR)) or all(
            os.path.isfile(os.path.join(c, n)) and os.path.getsize(os.path.join(c, n)) > 0 for n in engine.NETWORK_FILES
        ):
            _core_note = src
            return c
    for src, c in existing:
        if _is_writable(c):
            _core_note = src
            return c
    if os.path.isfile(os.path.join(bundled, engine.DLL_FSR)):
        # Never build into the plugin's own folder: Decky replaces it on every plugin update, which would
        # throw the user's built network away. The data-folder copy survives updates.
        try:
            os.makedirs(os.path.dirname(data_core), exist_ok=True)
            _copy_tree(bundled, data_core)
            _core_note = "data"
            return data_core
        except Exception:
            _core_note = "bundled (read-only)"
            return bundled
    if existing:
        _core_note = existing[0][0]
        return existing[0][1]
    _core_note = "missing"
    return data_core


def engine():
    """Import the Manager engine and point it at the right core and config."""
    global _engine
    if _engine is not None:
        return _engine
    import helixsr_engine as eng  # noqa: E402  (copied from src/linux at package time)

    eng.CORE_DIR = resolve_core(eng)
    app_dir = _manager_app_dir()
    manager_cfg = os.path.join(app_dir, "config.json") if app_dir else None
    if manager_cfg and os.path.isfile(manager_cfg):
        eng.CONFIG_FILE = manager_cfg  # share the Manager's extra game folders
    else:
        eng.CONFIG_FILE = os.path.join(settings_dir(), "config.json")
    _engine = eng
    return eng


# ---------------------------------------------------------------------------
# Capabilities (feature-detected so the plugin works with older and newer engines)
# ---------------------------------------------------------------------------

def capabilities():
    eng = engine()
    try:
        params = inspect.signature(eng.install_helixsr).parameters
    except Exception:
        params = {}
    variants = getattr(eng, "FSR4_VARIANTS", None)
    fsr4 = bool(variants) and "fsr4_variant" in params
    return {
        "fsr4Variants": list(variants) if fsr4 else [],
        "dlssLoader": bool(getattr(eng, "dlss_loader_available", lambda: False)()),
        "optiDlls": list(getattr(eng, "OPTI_NAMES", ["dxgi.dll"])),
        "fgModes": [
            {"id": "auto", "label": "Game default"},
            {"id": "dlssg_xefg", "label": "DLSS-G to XeFG"},
            {"id": "dlssg_fsrfg", "label": "DLSS-G to FSR-FG"},
            {"id": "dlssg_nukems", "label": "DLSS-G to Nukem's FG"},
            {"id": "optifg_fsrfg", "label": "OptiFG (any game)"},
        ],
    }


# ---------------------------------------------------------------------------
# Games
# ---------------------------------------------------------------------------

GAME_KEYS = (
    "id", "name", "folder", "exeFolder", "exeName", "appId", "launcher", "route", "routeDisplay",
    "optiDllName", "useFakeNvapi", "fgMode", "hasDlssG", "isReEngine", "isInZoi", "isUnity",
    "installReFramework", "installed", "version", "inputs", "hasBackups", "hasLogs", "hasMyFsr",
    "protonLaunchOptions", "fsr4Variant",
)


def _slim(game):
    out = {k: game.get(k) for k in GAME_KEYS if k in game}
    if out.get("appId") is not None:
        out["appId"] = str(out["appId"])
    exe = (game.get("exeName") or "").lower()
    out["native"] = None
    if not exe.endswith(".exe"):
        out["native"] = native_linux_exe(game.get("folder"))
    try:
        import fsr4lite

        out["lite"] = dict(fsr4lite.game_state(game.get("exeFolder")), **fsr4lite.eligibility(game))
    except Exception as e:  # never hide a game because of the Lite check
        out["lite"] = {"installed": False, "eligible": False, "reasons": [str(e)], "inputs": [], "inputsKnown": False}
    if out["native"]:
        out["lite"]["reasons"] = ["Native Linux game: OptiScaler, HelixSR and FSR 4 Lite only work in Windows games running through Proton"]
    return out


def native_linux_exe(folder, max_depth=2):
    """Name of a native Linux game executable (an ELF program, not a library) in the folder, or None."""
    if not folder or not os.path.isdir(folder):
        return None
    base = folder.rstrip("/").count("/")
    for root, dirs, files in os.walk(folder):
        if root.count("/") - base >= max_depth:
            dirs[:] = []
        for f in sorted(files):
            low = f.lower()
            if ".so" in low or low.endswith((".dll", ".txt", ".json", ".py")):
                continue
            p = os.path.join(root, f)
            try:
                if not os.access(p, os.X_OK) or os.path.getsize(p) < 4096:
                    continue
                with open(p, "rb") as fh:
                    head = fh.read(18)
            except Exception:
                continue
            # ELF, e_type 2 = executable, 3 = PIE executable (shared libraries are filtered by name above)
            if head[:4] == b"\x7fELF" and head[16] in (2, 3):
                return os.path.relpath(p, folder)
    return None


# Steam tools and runtimes the engine's folder scan picks up; they are not games.
NOT_GAMES_APPIDS = {
    "228980", "1070560", "1391110", "1628350", "1826330", "4183110", "1493710", "2180100", "2230260",
    "961940", "1054830", "1113280", "1245040", "1420170", "1580130", "1887720", "2348590", "2805730",
    "3658110", "4628710",
}
NOT_GAMES_RE = re.compile(r"^(proton\b|steam linux runtime|steamworks|steamvr)", re.IGNORECASE)


def is_game(g):
    """Drops Steam tools/runtimes and folders without a Windows executable (leftovers of uninstalled games)."""
    if g.get("installed") or (g.get("lite") or {}).get("installed"):
        return True
    if str(g.get("appId") or "") in NOT_GAMES_APPIDS or NOT_GAMES_RE.search(g.get("name") or ""):
        return False
    exe = (g.get("exeName") or "").lower()
    # Native Linux games are listed too (as not supported) so the user sees why nothing applies to them.
    return exe.endswith(".exe") or bool(g.get("native"))


def _cache_path():
    return os.path.join(settings_dir(), "games-cache.json")


def list_games(refresh=False):
    cache = _cache_path()
    if not refresh:
        try:
            with open(cache, "r", encoding="utf-8") as f:
                data = json.load(f)
            games = data.get("games") if isinstance(data, dict) else None
            # A cache from before the FSR 4 Lite check (no "lite" field) is rescanned once.
            if isinstance(games, list) and all(isinstance(g, dict) and "lite" in g and "native" in g for g in games):
                data["games"] = [g for g in games if is_game(g)]
                return data
        except Exception:
            pass
    games = [g for g in (_slim(g) for g in engine().scan_all_games()) if is_game(g)]
    data = {"games": games, "scannedAt": int(time.time())}
    try:
        tmp = cache + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, cache)
    except Exception:
        pass
    return data


def _update_cache(game):
    cache = _cache_path()
    try:
        with open(cache, "r", encoding="utf-8") as f:
            data = json.load(f)
        games = data.get("games") or []
        for i, g in enumerate(games):
            if g.get("folder") == game.get("folder"):
                games[i] = game
                break
        else:
            games.append(game)
            games.sort(key=lambda x: (x.get("name") or "").lower())
        data["games"] = games
        with open(cache + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(cache + ".tmp", cache)
    except Exception:
        pass


def game(folder):
    eng = engine()
    g = _slim(eng.scan_game(folder, None, eng.get_steam_manifests()))
    _update_cache(g)
    return g


def find_app(appid):
    """Folder and scan of a Steam app by its id, or None when it is not a supported game."""
    eng = engine()
    appid = str(appid)
    for m in eng.get_steam_manifests().values():
        if str(m.get("appid")) == appid:
            folder = os.path.join(m["libraryRoot"], "steamapps", "common", m["installdir"])
            if os.path.isdir(folder):
                g = _slim(eng.scan_game(folder, m["installdir"], eng.get_steam_manifests()))
                return g if g.get("route") and is_game(g) else None
    return None


def install(folder, options=None):
    eng = engine()
    o = options or {}
    kwargs = {}
    route = o.get("route")
    if route in ("direct", "optiscaler", "dlss"):
        kwargs["route_override"] = route
    if o.get("optiDll"):
        kwargs["opti_dll"] = o["optiDll"]
    if o.get("useFakeNvapi") is not None:
        kwargs["use_fakenvapi"] = bool(o["useFakeNvapi"])
    if o.get("installReFramework") is not None:
        kwargs["install_ref"] = bool(o["installReFramework"])
    if o.get("fgMode"):
        kwargs["fg_mode"] = o["fgMode"]
    if o.get("fsr4Variant") and capabilities()["fsr4Variants"]:
        kwargs["fsr4_variant"] = o["fsr4Variant"]
    res = eng.install_helixsr(folder, **kwargs)
    g = game(folder)
    return {"success": bool(res.get("success", True)), "message": res.get("message", ""), "game": g}


def uninstall(folder):
    res = engine().uninstall_helixsr(folder)
    g = game(folder)
    return {"success": bool(res.get("success", True)), "message": res.get("message", ""), "game": g}


def clear_cache(folder):
    eng = engine()
    g = eng.scan_game(folder, None, eng.get_steam_manifests())
    res = eng.clear_shader_cache(g)
    if isinstance(res, dict):
        return res
    return {"success": True, "cleared": bool(res)}


def logs(folder):
    res = engine().get_game_logs_and_ini(folder)
    tail = lambda s, n=4000: (s or "")[-n:]
    return {
        "helixsrLog": tail(res.get("helixsrLog")),
        "optiscalerLog": tail(res.get("optiscalerLog")),
        "exeFolder": res.get("exeFolder"),
    }


def status():
    eng = engine()
    st = eng.get_core_status()
    st["coreSource"] = _core_note
    st["managerDir"] = _manager_app_dir()
    st["capabilities"] = capabilities()
    st["building"] = _build_running()
    st["settingsDir"] = settings_dir()
    return st


# ---------------------------------------------------------------------------
# Network build (runs detached; progress goes to build.log, state to build.json)
# ---------------------------------------------------------------------------

def _build_files():
    d = settings_dir()
    return os.path.join(d, "build.log"), os.path.join(d, "build.json")


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _build_running():
    _, state_path = _build_files()
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            st = json.load(f)
        return st.get("state") == "running" and _pid_alive(st.get("pid"))
    except Exception:
        return False


def build_status():
    log_path, state_path = _build_files()
    st = {"state": "idle"}
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        pass
    if st.get("state") == "running" and not _pid_alive(st.get("pid")):
        st["state"] = "failed"
        st["error"] = "The build stopped unexpectedly."
    lines = []
    try:
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.read().splitlines()[-40:]
    except Exception:
        pass
    st["log"] = lines
    return st


def build_run(dlss_path=""):
    """Run the network compiler in the foreground (the backend starts this as its own process)."""
    eng = engine()
    log_path, state_path = _build_files()

    def write_state(**kw):
        with open(state_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(dict(kw, pid=os.getpid(), updatedAt=int(time.time())), f)
        os.replace(state_path + ".tmp", state_path)

    write_state(state="running")
    with open(log_path, "w", encoding="utf-8") as log:
        def listener_line(line):
            log.write(line + "\n")
            log.flush()

        class _Sink(list):
            def append(self, item):
                listener_line(item)

        eng.BUILD_LISTENERS.append(_Sink())
        before = set(threading.enumerate())
        res = eng.start_network_build(dlss_path=dlss_path)
        if not res.get("success"):
            write_state(state="failed", error=res.get("error", "Could not start the build"))
            return res
        for t in set(threading.enumerate()) - before:
            t.join()
    ok = eng.get_core_status()["weightsBuilt"]
    write_state(state="done" if ok else "failed", error=None if ok else "The build did not produce the network. See the log.")
    return {"success": ok}


# ---------------------------------------------------------------------------
# FSR 4 Lite (py_modules/fsr4lite.py)
# ---------------------------------------------------------------------------

def _full_game(folder):
    eng = engine()
    return eng.scan_game(folder, None, eng.get_steam_manifests())


def lite_status():
    import fsr4lite

    return {"runtime": fsr4lite.runtime_status(), "device": fsr4lite.device_info()}


def lite_prepare(payload_path=None):
    import fsr4lite

    return {"success": True, "runtime": fsr4lite.prepare_runtime(payload_path or None)}


def lite_install(folder, proxy=None, mode="lite"):
    import fsr4lite

    st = fsr4lite.install(_full_game(folder), proxy or "dxgi.dll", mode or "lite")
    return {"success": True, "lite": st, "game": game(folder)}


def lite_uninstall(folder):
    import fsr4lite

    res = fsr4lite.uninstall(_full_game(folder)["exeFolder"])
    return {"success": True, "removed": res["removed"], "game": game(folder)}


def lite_mode(folder, mode, reason=None):
    import fsr4lite

    st = fsr4lite.set_mode(_full_game(folder)["exeFolder"], mode, reason)
    return {"success": True, "lite": st, "game": game(folder)}


def lite_verify(folder):
    import fsr4lite

    v = fsr4lite.verify(_full_game(folder)["exeFolder"])
    return {"success": True, "verification": v, "game": game(folder)}


COMMANDS = {
    "lite_status": lambda a: lite_status(),
    "lite_prepare": lambda a: lite_prepare(a.get("payloadPath")),
    "lite_install": lambda a: lite_install(a["folder"], a.get("proxy"), a.get("mode") or "lite"),
    "lite_uninstall": lambda a: lite_uninstall(a["folder"]),
    "lite_mode": lambda a: lite_mode(a["folder"], a["mode"], a.get("reason")),
    "lite_verify": lambda a: lite_verify(a["folder"]),
    "status": lambda a: status(),
    "capabilities": lambda a: capabilities(),
    "list_games": lambda a: list_games(bool(a.get("refresh"))),
    "game": lambda a: game(a["folder"]),
    "find_app": lambda a: {"game": find_app(a["appId"])},
    "install": lambda a: install(a["folder"], a.get("options")),
    "uninstall": lambda a: uninstall(a["folder"]),
    "clear_cache": lambda a: clear_cache(a["folder"]),
    "logs": lambda a: logs(a["folder"]),
    "build_status": lambda a: build_status(),
    "build_run": lambda a: build_run(a.get("dlssPath") or ""),
    "get_settings": lambda a: load_settings(),
    "set_settings": lambda a: (save_settings(dict(load_settings(), **(a.get("settings") or {}))), load_settings())[1],
}


def run(command, args=None):
    fn = COMMANDS.get(command)
    if not fn:
        return {"success": False, "error": f"Unknown command: {command}"}
    try:
        res = fn(args or {})
        return res if isinstance(res, dict) else {"result": res}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main(argv):
    if len(argv) < 2:
        print(json.dumps({"success": False, "error": "usage: helixsr_bridge.py <command> [json]"}))
        return 2
    args = json.loads(argv[2]) if len(argv) > 2 and argv[2] else {}
    res = run(argv[1], args)
    sys.stdout.write("\n@@HELIXSR_JSON@@" + json.dumps(res) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
