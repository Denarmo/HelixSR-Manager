"""HelixSR Manager for Decky: backend.

Every call goes through py_modules/helixsr_bridge.py. It runs under the
system's python3 (full standard library, no Decky/PyInstaller library paths),
and falls back to running in-process when no system python3 exists.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys

import decky

PLUGIN_DIR = os.environ.get("DECKY_PLUGIN_DIR") or os.path.dirname(os.path.abspath(__file__))
PY_MODULES = os.path.join(PLUGIN_DIR, "py_modules")
BRIDGE = os.path.join(PY_MODULES, "helixsr_bridge.py")
MARK = "@@HELIXSR_JSON@@"

if PY_MODULES not in sys.path:
    sys.path.insert(0, PY_MODULES)


def _user_home():
    return getattr(decky, "DECKY_USER_HOME", None) or os.environ.get("DECKY_USER_HOME") or os.path.expanduser("~")


def _system_python():
    for p in ("/usr/bin/python3", "/usr/local/bin/python3"):
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return shutil.which("python3")


def _bridge_env():
    env = dict(os.environ)
    # PyInstaller (Decky's runtime) sets these for its own bundle; they break other programs.
    for k in ("LD_LIBRARY_PATH", "LD_PRELOAD", "PYTHONHOME", "PYTHONPATH", "_MEIPASS2", "_PYI_ARCHIVE_FILE"):
        env.pop(k, None)
    orig = env.get("LD_LIBRARY_PATH_ORIG")
    if orig:
        env["LD_LIBRARY_PATH"] = orig
    env["HOME"] = _user_home()
    env["HELIXSR_DECKY_SETTINGS"] = getattr(decky, "DECKY_PLUGIN_SETTINGS_DIR", "") or os.path.join(
        _user_home(), ".local", "share", "HelixSR", "decky"
    )
    env["HELIXSR_DECKY_CORE_BUNDLE"] = os.path.join(PLUGIN_DIR, "helixsr_core")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _parse(out):
    idx = out.rfind(MARK)
    if idx < 0:
        raise RuntimeError(out.strip()[-500:] or "HelixSR bridge returned nothing")
    return json.loads(out[idx + len(MARK):].strip().splitlines()[0])


class Plugin:
    _build_proc = None

    async def _call(self, command, args=None, timeout=300):
        py = _system_python()
        payload = json.dumps(args or {})
        if py:
            proc = await asyncio.create_subprocess_exec(
                py, "-B", BRIDGE, command, payload,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                stdin=asyncio.subprocess.DEVNULL,
                env=_bridge_env(),
                cwd=PY_MODULES,
            )
            try:
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return {"success": False, "error": f"{command} timed out"}
            text = out.decode("utf-8", errors="ignore")
            try:
                return _parse(text)
            except Exception as e:
                decky.logger.error(f"bridge {command} failed: {text[-2000:]}")
                return {"success": False, "error": str(e)}
        # No system python3: run in this process.
        os.environ.update({k: v for k, v in _bridge_env().items() if k.startswith("HELIXSR_") or k == "HOME"})
        import helixsr_bridge
        return await asyncio.to_thread(helixsr_bridge.run, command, args or {})

    # ----- called from the frontend -----

    async def get_status(self):
        return await self._call("status")

    async def list_games(self, refresh=False):
        return await self._call("list_games", {"refresh": bool(refresh)}, timeout=600)

    async def get_game(self, folder):
        return await self._call("game", {"folder": folder})

    async def find_app(self, app_id):
        return await self._call("find_app", {"appId": str(app_id)})

    async def install(self, folder, options=None):
        decky.logger.info(f"install {folder} {options}")
        return await self._call("install", {"folder": folder, "options": options or {}}, timeout=900)

    async def uninstall(self, folder):
        decky.logger.info(f"uninstall {folder}")
        return await self._call("uninstall", {"folder": folder}, timeout=600)

    async def clear_cache(self, folder):
        return await self._call("clear_cache", {"folder": folder})

    async def get_logs(self, folder):
        return await self._call("logs", {"folder": folder})

    async def get_settings(self):
        return await self._call("get_settings")

    async def set_settings(self, settings):
        return await self._call("set_settings", {"settings": settings or {}})

    async def build_status(self):
        return await self._call("build_status")

    async def start_build(self):
        if self._build_proc and self._build_proc.poll() is None:
            return {"success": False, "error": "A build is already running"}
        st = await self._call("build_status")
        if st.get("state") == "running":
            return {"success": False, "error": "A build is already running"}
        py = _system_python()
        if not py:
            return {"success": False, "error": "Building the network needs python3 (found none on this system)."}
        self._build_proc = subprocess.Popen(
            [py, "-B", BRIDGE, "build_run", "{}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_bridge_env(),
            cwd=PY_MODULES,
            start_new_session=True,
        )
        decky.logger.info(f"network build started (pid {self._build_proc.pid})")
        return {"success": True}

    # ----- lifecycle -----

    async def _main(self):
        decky.logger.info(f"HelixSR Manager plugin loaded from {PLUGIN_DIR}, python3: {_system_python()}")

    async def _unload(self):
        decky.logger.info("HelixSR Manager plugin unloaded")

    async def _uninstall(self):
        pass
