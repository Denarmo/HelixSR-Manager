#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""helixsr_install.py HELIXSR_FOLDER [list | install N.. | uninstall N.. | install-all | uninstall-all | remove]
                     [--folder GAME_FOLDER]..

The game part of the HelixSR setup (helixsr-setup runs it after building the network). Finds the games in every Steam
library (Linux, Flatpak Steam, Windows; other games: --folder) and installs HelixSR into the ones you pick, one of two ways:
  - games with FSR 3.1 (also when they have DLSS): HelixSR replaces the game's FSR 3.1 DLL (amd_fidelityfx_upscaler_dx12.dll,
    or amd_fidelityfx_dx12.dll in games without it); the game's file is kept as *.original.dll. No OptiScaler.
  - games without FSR 3.1 (DLSS, XeSS or FSR 2 only): OptiScaler (the official 0.9.4, folder "optiscaler") next to the game's .exe, as
    dxgi.dll or under the name of the OptiScaler the game already has, its FSR 3.1 backend pointed at HelixSR
    (Dx12Upscaler = fsr31, FfxDx12Path / FfxDx12SRPath = HelixSR/helixsr.dll / helixsr_upscaler.dll next to it). Select DLSS in the game: its
    DLSS inputs reach HelixSR. Everything replaced goes to HelixSR/backup first.
  - experimental, games with DLSS: the HelixSR DLSS loader (folder "dlss-loader", dxgi.dll) and HelixSR as nvngx.dll next to
    the game's .exe: the game's own DLSS option runs HelixSR, without OptiScaler.
Uninstall puts everything back. Uses only Python's standard library. Close the game first."""
import json, os, re, shutil, sys
from pathlib import Path

DLL = 'amd_fidelityfx_dx12.dll'
DLL_SR = 'amd_fidelityfx_upscaler_dx12.dll'
NAMES = (DLL_SR, DLL)                     # a game's FSR 3.1 DLLs, the upscaler one first
OWN = 'helixsr.dll'                       # HelixSR in the HelixSR folder for OptiScaler's FfxDx12Path, and a second copy
OWN_SR = 'helixsr_upscaler.dll'           # for FfxDx12SRPath: OptiScaler hooks the upscaler module, so the two must be
                                          # different files (one file in both roles hangs the game when the upscaler starts)
NETWORK = ('helixsr_weights.bin', 'helixsr_kernels.pak')
FOLDER = 'HelixSR'
MARKER = 'helixsr-install.json'
BACKUP = 'backup'
OPTI_NAMES = ('dxgi.dll', 'winmm.dll', 'version.dll', 'dbghelp.dll', 'd3d12.dll', 'wininet.dll', 'winhttp.dll',
              'OptiScaler.asi')
OPTI_EXTRA = ('fakenvapi.dll', 'fakenvapi.ini')   # OptiScaler loads fakenvapi.dll on non-NVIDIA GPUs (games that check nvapi)
AMD_FSR = 'amd_fidelityfx_upscaler_dx12.amd.dll'   # AMD's FSR (folder "amd-fsr"): HelixSR lists it after itself
AMD_FG = 'amd_fidelityfx_framegeneration_dx12.dll'   # AMD's frame generation (folder "amd-fsr"): HelixSR has none
MY_FSR = 'my-fsr'                                 # in a game's HelixSR folder: an FSR DLL put there is listed after HelixSR
MY_FSR_README = '''Put an FSR upscaler DLL into this folder (for example FSR 4: amd_fidelityfx_upscaler_dx12.dll, any
file name) and start the game again. Only for this game.

In the game press Insert (OptiScaler's menu), then Upscaling tab > Upscalers > FFX Upscaler, and pick it there:
it is listed by its version, for example "FSR 4.1.1". HelixSR stays the default ("FSR HelixSR (3.1.5)").
FSR 4 is listed only if the DLL supports your GPU.

To go back: delete the DLL from this folder.
'''
LOADER_DIR = 'dlss-loader'                        # the HelixSR DLSS loader (experimental route "dlss")
LOADER = 'dxgi.dll'
CORE = 'nvngx.dll'                                # HelixSR next to the .exe under the DLSS core's name
OLD_FILES = ('nvngx.dll', DLL, DLL_SR)            # left in the HelixSR folder by HelixSR 1.5 / 1.6 / early 1.7
SKIP_EXE = re.compile(r'unins|setup|redist|crash|launcher|vc_?redist|dxsetup|easyanticheat|beservice|dotnet|'
                      r'helper|report|prereq|install|7z|ue4prereq|cefprocess|webhelper', re.I)
INPUTS = {'nvngx_dlss.dll': 'DLSS', 'libxess.dll': 'XeSS', 'ffx_fsr2_api_x64.dll': 'FSR 2',
          'ffx_fsr2_api_dx12_x64.dll': 'FSR 2'}


def say(msg):
    print(f'[helixsr-setup] {msg}', flush=True)


def is_helixsr(path):
    try:
        with open(path, 'rb') as f:
            return re.search(rb'HelixSR \d+\.\d+\.\d+', f.read(4 << 20)) is not None
    except OSError:
        return False


def is_loader(path):
    try:
        with open(path, 'rb') as f:
            return b'HelixSR DLSS loader' in f.read(1 << 20)
    except OSError:
        return False


def is_optiscaler(path):
    try:
        with open(path, 'rb') as f:
            return b'OptiScaler' in f.read(32 << 20)
    except OSError:
        return False


def version_of(dll):
    m = re.search(rb'\x00HelixSR (\d+\.\d+\.\d+)\x00', Path(dll).read_bytes()[:4 << 20])
    return m.group(1).decode() if m else '?'


def copy_checked(src, dst):
    shutil.copyfile(src, dst)
    if Path(dst).read_bytes() != Path(src).read_bytes():
        raise SystemExit(f'{dst} differs from the file just copied: something on this PC changes new files there '
                         '(antivirus or a synced folder). Close the game and try again.')


def sha(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


_fsr_source = {}


def fsr_source(here):
    """The FSR DLL listed next to HelixSR: one the user put into my-fsr, else AMD's that comes with HelixSR."""
    if here not in _fsr_source:
        _fsr_source[here] = find_fsr_source(here)
    return _fsr_source[here]


def find_fsr_source(here):
    mine = sorted(p for p in (here / 'my-fsr').glob('*') if p.suffix.lower() == '.dll') if (here / 'my-fsr').is_dir() else []
    for p in mine:
        if b'ffxCreateContext' in p.read_bytes():
            return p
        say(f'note: {p.name} in my-fsr is not an FSR (FidelityFX) DLL; ignored')
    return here / 'amd-fsr' / DLL_SR


def make_my_fsr(folder):
    (folder / MY_FSR).mkdir(exist_ok=True)
    (folder / MY_FSR / 'README.txt').write_text(MY_FSR_README, newline='\r\n' if os.name != 'nt' else None)


def remove_my_fsr(folder):
    """Removes the game's my-fsr folder unless the user put files there; True if it was kept."""
    d = folder / MY_FSR
    if (d / 'README.txt').exists():
        (d / 'README.txt').unlink()
    try:
        d.rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        return True
    return False


def has_embedded_network(path):
    """True when the DLL carries the network (the setup appends it: one-file DLL)."""
    try:
        with open(path, 'rb') as f:
            f.seek(-32, os.SEEK_END)
            return f.read(8) == b'HXSRNET1'
    except OSError:
        return False


def strip_embedded_network(path):
    """Cuts the appended network off a one-file DLL (back to the DLL as downloaded)."""
    import struct
    with open(path, 'r+b') as f:
        f.seek(-32, os.SEEK_END)
        tail = f.read(32)
        if tail[:8] != b'HXSRNET1':
            return
        nw, np_, _ = struct.unpack('<QQQ', tail[8:])
        f.truncate(f.seek(0, os.SEEK_END) - 32 - nw - np_)


def network_ready(here):
    return is_helixsr(here / DLL) and (has_embedded_network(here / DLL) or all((here / n).exists() for n in NETWORK))


def copy_network(here, folder):
    """Separate network files only when the DLL does not carry the network; otherwise earlier copies are removed (the
    DLL reads its own copy first)."""
    for n in NETWORK:
        if has_embedded_network(here / DLL):
            if (folder / n).exists():
                (folder / n).unlink()
        else:
            copy_checked(here / n, folder / n)


def copy_helixsr(here, folder, names):
    """HelixSR's DLL under the given names (and the network files if it does not carry the network) into folder."""
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        copy_checked(here / DLL, folder / n)
    copy_network(here, folder)


# --- finding games ---------------------------------------------------------------------------------------------------

def steam_roots():
    roots = []
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
                roots.append(Path(winreg.QueryValueEx(k, 'SteamPath')[0]))
        except OSError:
            pass
        roots.append(Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Steam')
    else:
        h = Path.home()
        roots += [h / '.local/share/Steam', h / '.steam/steam', h / '.steam/root',
                  h / '.var/app/com.valvesoftware.Steam/.local/share/Steam']
    return roots


def steam_libraries():
    libs, seen = [], set()
    for root in steam_roots():
        vdf = root / 'steamapps' / 'libraryfolders.vdf'
        paths = [root]
        if vdf.exists():
            text = vdf.read_text(errors='replace')
            paths += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', text)]
        for p in paths:
            common = p / 'steamapps' / 'common'
            try:
                key = common.resolve()
            except OSError:
                continue
            if common.is_dir() and key not in seen:
                seen.add(key)
                libs.append(common)
    return libs


def walk(folder, depth):
    """(directory, file names) pairs under folder, at most depth levels deep, without following links."""
    out, todo = [], [(Path(folder), 0)]
    while todo:
        d, n = todo.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        out.append((d, [e.name for e in entries if e.is_file(follow_symlinks=False) or e.is_symlink()]))
        if n < depth:
            todo += [(Path(e.path), n + 1) for e in entries if e.is_dir(follow_symlinks=False) and e.name != FOLDER]
    return out


def exe_folder(tree):
    """The folder of the game's main .exe: where OptiScaler has to go."""
    for d, names in tree:   # a folder that already has OptiScaler (or HelixSR) wins
        if 'OptiScaler.ini' in names or (d / FOLDER / MARKER).exists():
            return d
    best, size = None, -1
    for d, names in tree:
        for n in names:
            if not n.lower().endswith('.exe') or SKIP_EXE.search(n):
                continue
            s = (d / n).stat().st_size if (d / n).exists() else 0
            if n.lower().endswith('-win64-shipping.exe'):
                s += 1 << 40   # Unreal Engine: always the game itself
            if s > size:
                best, size = d, s
    return best


def original(target):
    return target.with_name(target.stem + '.original.dll')


class Game:
    """route 'optiscaler' (target = folder of the .exe) or 'direct' (targets = the game's FSR 3.1 DLLs)."""

    def __init__(self, name, folder, tree):
        self.name, self.folder = name, folder
        low = {d: {n.lower(): n for n in names} for d, names in tree}
        self.inputs = sorted({INPUTS[n] for d in low for n in low[d] if n in INPUTS}, key=['DLSS', 'XeSS', 'FSR 2'].index)
        fsr = [d / low[d][n] for d in low for n in NAMES if n in low[d]]
        up = [p for p in fsr if p.name.lower() == DLL_SR]
        self.fsr_targets = up or [p for p in fsr if p.name.lower() == DLL]
        direct_installed = any(original(t).exists() and is_helixsr(t) for t in self.fsr_targets)
        self.target = exe_folder(tree)
        # FSR 3.1 games get the drop-in (no OptiScaler), also when they have DLSS, unless OptiScaler was picked for the
        # game (answer o at the setup's question for the game, kept in the install record); OptiScaler for the others
        marker = self.target / FOLDER / MARKER if self.target else None
        try:
            rec = json.loads(marker.read_text()) if marker and marker.exists() else {}
        except (OSError, ValueError):
            rec = {}
        self.dlss_installed = rec.get('route') == 'dlss'
        self.opti_installed = bool(marker and marker.exists()) and not self.dlss_installed
        self.chosen = rec.get('chosen') == 'optiscaler' and self.opti_installed
        self.can_opti = bool(self.fsr_targets and self.inputs and self.target)   # either way works
        self.can_dlss = bool('DLSS' in self.inputs and self.target and (Path(__file__).parent.parent / LOADER_DIR / LOADER).exists())
        if self.dlss_installed:
            self.route = 'dlss'
        elif self.fsr_targets and not self.chosen:
            self.route = 'direct'
        else:
            self.route = 'optiscaler' if self.inputs and self.target else None

    def installed(self):
        if self.route == 'dlss':
            return self.dlss_installed
        if self.route == 'direct':
            return self.opti_installed or any(original(t).exists() and is_helixsr(t) for t in self.fsr_targets)
        return self.route == 'optiscaler' and (self.target / FOLDER / MARKER).exists()

    def label(self):
        if self.route == 'dlss':
            return 'DLSS (HelixSR as the game\'s DLSS, experimental: select DLSS in the game)'
        if self.route == 'direct':
            return 'FSR 3.1 (HelixSR replaces the game\'s FSR DLL: select AMD FSR in the game)'
        return ' / '.join(self.inputs) + ' (through OptiScaler: select DLSS in the game)'


def games(extra):
    out = []
    for common in steam_libraries():
        for d in sorted(common.iterdir(), key=lambda p: p.name.lower()):
            if d.is_dir():
                g = Game(d.name, d, walk(d, 7))
                if g.route:
                    out.append(g)
    return out + games_from(extra, out)


def clean_path(f):
    """A path as typed, pasted or dragged into a terminal: quotes, file:// URLs (%20), backslash-escaped spaces, a file
    inside the game folder (its folder is used)."""
    from urllib.parse import unquote
    f = f.strip().strip('"').strip("'").strip()
    if f.lower().startswith('file://'):
        f = unquote(f[7:])
    if os.name != 'nt':
        f = re.sub(r'\\(.)', r'\1', f)
    p = Path(f).expanduser()
    return str(p.parent if p.is_file() else p)


def overlaps(a, b):
    a, b = Path(a), Path(b)
    return a == b or a in b.parents or b in a.parents


def games_from(folders, listed=()):
    """Games in folders given by hand (dropped onto the setup, passed, or typed at its prompt). A folder of a game that
    is already listed (or inside it) is skipped; a folder inside a game (e.g. Binaries\\Win64) is taken from the
    nearest parent where the game's FSR 3.1 DLL is found (up to four levels)."""
    out = []
    for f in folders:
        d = Path(clean_path(f)).expanduser()
        if not d.is_dir():
            say(f'not a folder: {d}')
            continue
        d = d.resolve()
        same = next((g for g in list(listed) + out if overlaps(g.folder, d)), None)
        if same:
            say(f'{d} is {same.name}, already in the list')
            continue
        g = Game(d.name, d, walk(d, 7))
        if not g.fsr_targets:
            up = d
            for _ in range(4):
                if up.parent == up:
                    break
                up = up.parent
                h = Game(up.name, up, walk(up, 7))
                if h.fsr_targets and h.target and overlaps(h.target, d):
                    g = h
                    break
        if g.route:
            out.append(g)
        else:
            say(f'no DLSS, XeSS or FSR in {d}')
    return out


# --- OptiScaler.ini --------------------------------------------------------------------------------------------------

def key_re(key):
    # one "key = value" line; works with Windows (CRLF) and Linux line endings
    return re.compile(r'(?m)^(?P<key>%s)[ \t]*=[ \t]*(?P<val>[^\r\n]*?)[ \t]*(?=\r?$)' % re.escape(key))


def set_value(text, key, value, section=None):
    """Sets key = value. A missing key is added at the start of [section]."""
    found = list(key_re(key).finditer(text))
    if len(found) > 1:
        raise SystemExit(f'OptiScaler.ini: more than one "{key} =" line')
    if found:
        return key_re(key).sub(lambda m: f'{m.group("key")} = {value}', text, count=1)
    m = re.search(r'(?m)^\[%s\][ \t]*(\r?\n)' % re.escape(section or ''), text) if section else None
    if not m:
        raise SystemExit(f'OptiScaler.ini: no "{key} =" line' + (f' and no [{section}] section' if section else ''))
    return text[:m.end()] + f'{key} = {value}' + m.group(1) + text[m.end():]


def win_path(path):
    """The path as OptiScaler wants it: a Windows path (under Proton the Linux root is Z:)."""
    p = str(path.resolve())
    return p if os.name == 'nt' else 'Z:' + p.replace('/', '\\')


def read_ini(p):
    with open(p, encoding='utf-8', errors='surrogateescape', newline='') as f:
        return f.read()


def write_ini(p, text):
    with open(p, 'w', encoding='utf-8', errors='surrogateescape', newline='') as f:
        f.write(text)


def point_at_helixsr(text, folder):
    text = set_value(text, 'Dx12Upscaler', 'fsr31', 'Upscalers')
    text = set_value(text, 'FfxDx12Path', win_path(folder / OWN), 'Libraries')
    text = set_value(text, 'FfxDx12SRPath', win_path(folder / OWN_SR), 'Libraries')
    return set_value(text, 'FfxDx12FGPath', win_path(folder / AMD_FG), 'Libraries')


# --- route 1: OptiScaler ---------------------------------------------------------------------------------------------

def move_to_backup(t, name, rec):
    src = t / name
    if not (src.exists() or src.is_symlink()) or name in rec['moved']:
        return
    dst = t / FOLDER / BACKUP / name
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(src, dst)
    rec['moved'].append(name)


def install_optiscaler(t, here):
    folder = t / FOLDER
    marker = folder / MARKER
    rec = json.loads(marker.read_text()) if marker.exists() else {'moved': [], 'created': []}
    if 'previous' in rec:   # HelixSR 1.5: it only changed two OptiScaler.ini lines; undo them first
        text = read_ini(t / 'OptiScaler.ini')
        for key, value in rec['previous'].items():
            text = set_value(text, key, value)
        write_ini(t / 'OptiScaler.ini', text)
        rec = {'moved': [], 'created': []}
    rec.setdefault('created', [])
    folder.mkdir(exist_ok=True)
    opti = rec.get('optiscaler') or next((n for n in OPTI_NAMES if (t / n).exists() and is_optiscaler(t / n)), 'dxgi.dll')
    if 'optiscaler' not in rec:   # first install: keep what the game had
        move_to_backup(t, opti, rec)
        if (t / 'OptiScaler.ini').exists():
            (folder / BACKUP).mkdir(parents=True, exist_ok=True)
            shutil.copy2(t / 'OptiScaler.ini', folder / BACKUP / 'OptiScaler.ini')
            rec['ini'] = 'edited'
        else:
            shutil.copyfile(here / 'optiscaler' / 'OptiScaler.ini', t / 'OptiScaler.ini')
            rec['ini'] = 'created'
        rec['optiscaler'] = opti
    for n in OPTI_EXTRA:
        if not (t / n).exists():
            shutil.copyfile(here / 'optiscaler' / n, t / n)
            if n not in rec['created']:
                rec['created'].append(n)
    if (t / opti).is_symlink():
        (t / opti).unlink()
    copy_checked(here / 'optiscaler' / 'OptiScaler.dll', t / opti)
    for n in OLD_FILES:   # only HelixSR's own older copies
        if (folder / n).exists() and is_helixsr(folder / n):
            (folder / n).unlink()
    copy_helixsr(here, folder, (OWN, OWN_SR))
    make_my_fsr(folder)
    src, dst = fsr_source(here), folder / AMD_FSR
    if dst.exists() and rec.get('amd_fsr') and sha(dst) != rec['amd_fsr']:
        say(f'  keeping your {AMD_FSR} in {FOLDER} (replaced by hand)')
    else:
        copy_checked(src, dst)
        rec['amd_fsr'] = sha(dst)
    src, dst = here / 'amd-fsr' / AMD_FG, folder / AMD_FG   # FSR frame generation (OptiScaler's or the game's)
    if dst.exists() and rec.get('amd_fg') and sha(dst) != rec['amd_fg']:
        say(f'  keeping your {AMD_FG} in {FOLDER} (replaced by hand)')
    else:
        copy_checked(src, dst)
        rec['amd_fg'] = sha(dst)
    if not (t / 'OptiScaler.ini').exists():   # deleted or moved by hand since the last install: a fresh one
        shutil.copyfile(here / 'optiscaler' / 'OptiScaler.ini', t / 'OptiScaler.ini')
        say('  OptiScaler.ini was missing next to the game\'s .exe; made a new one')
    write_ini(t / 'OptiScaler.ini', point_at_helixsr(read_ini(t / 'OptiScaler.ini'), folder))
    rec['helixsr'] = version_of(here / DLL)
    rec['route'] = 'optiscaler'
    marker.write_text(json.dumps(rec, indent=1) + '\n')
    say(f'  installed in {t} (OptiScaler as {opti}' + (f'; the previous {opti} is in {FOLDER}/{BACKUP})' if opti in rec['moved'] else ')'))


def uninstall_optiscaler(t):
    folder = t / FOLDER
    marker = folder / MARKER
    if not marker.exists():
        return
    rec = json.loads(marker.read_text())
    opti = rec.get('optiscaler', 'dxgi.dll')
    if (t / opti).exists() or (t / opti).is_symlink():
        (t / opti).unlink()
    if rec.get('ini') == 'created':
        for n in ('OptiScaler.ini', 'OptiScaler.log'):
            if (t / n).exists():
                (t / n).unlink()
    elif (folder / BACKUP / 'OptiScaler.ini').exists():
        os.replace(folder / BACKUP / 'OptiScaler.ini', t / 'OptiScaler.ini')
    for n in rec.get('created', []):
        if (t / n).exists():
            (t / n).unlink()
    for name in rec['moved']:
        src = folder / BACKUP / name
        if src.exists() or src.is_symlink():
            os.replace(src, t / name)
    for n in (OWN, OWN_SR, AMD_FSR, AMD_FG, MARKER, 'helixsr.log') + NETWORK + OLD_FILES:
        if (folder / n).exists() and (n not in OLD_FILES or is_helixsr(folder / n)):
            (folder / n).unlink()
    kept = remove_my_fsr(folder)
    for d in (folder / BACKUP, folder):
        try:
            d.rmdir()
        except OSError:
            pass
    say(f'  removed from {t} (everything put back as it was)')
    if kept:
        say(f'  your files in {folder / MY_FSR} were left there')


# --- route 2: the game's FSR 3.1 DLL ---------------------------------------------------------------------------------

def install_direct(g, here):
    for t in g.fsr_targets:
        orig = original(t)
        if is_helixsr(t):
            if not orig.exists():
                say(f'  {t}: HelixSR without a backup of the game\'s file; left as it is')
                continue
            copy_checked(here / DLL, t)   # update
        else:
            if orig.exists():
                say(f'  {t}: {orig.name} already exists and {t.name} is not HelixSR; left as it is')
                continue
            os.replace(t, orig)
            copy_checked(here / DLL, t)
        copy_network(here, t.parent)
        (t.parent / MARKER).write_text(json.dumps({'helixsr': version_of(here / DLL), 'files': [t.name],
                                                   'route': 'direct'}, indent=1) + '\n')
        say(f'  installed {t} (the game\'s file kept as {orig.name})')


def uninstall_direct(g):
    for t in g.fsr_targets:
        orig = original(t)
        if not orig.exists():
            continue
        if t.exists() and not is_helixsr(t):
            say(f'  {t} is not HelixSR (the game may have been updated); {orig.name} left in place')
            continue
        if t.exists():
            t.unlink()
        os.replace(orig, t)
        for extra in (MARKER, 'helixsr.log') + NETWORK:
            if (t.parent / extra).exists():
                (t.parent / extra).unlink()
        say(f'  restored the game\'s {t}')


# --- route 3 (experimental): the HelixSR DLSS loader ------------------------------------------------------------------

def install_dlss(t, here):
    """dxgi.dll (the loader) and HelixSR as nvngx.dll next to the game's .exe; files of the same names that are not
    HelixSR's go to HelixSR/backup first."""
    folder = t / FOLDER
    marker = folder / MARKER
    rec = json.loads(marker.read_text()) if marker.exists() else {'moved': [], 'created': []}
    rec.setdefault('moved', [])
    folder.mkdir(exist_ok=True)
    for name, ours in ((LOADER, is_loader), (CORE, is_helixsr)):
        if (t / name).exists() and not ours(t / name):
            move_to_backup(t, name, rec)
    copy_checked(here / LOADER_DIR / LOADER, t / LOADER)
    copy_checked(here / DLL, t / CORE)
    rec.update({'helixsr': version_of(here / DLL), 'route': 'dlss', 'files': [LOADER, CORE]})
    marker.write_text(json.dumps(rec, indent=1) + '\n')
    say(f'  installed in {t} (DLSS loader as {LOADER}, HelixSR as {CORE}' +
        (f'; the game\'s previous files are in {FOLDER}/{BACKUP})' if rec['moved'] else ')'))
    if (t / 'OptiScaler.ini').exists():
        say('  NOTE: an OptiScaler that HelixSR did not install is next to the game\'s .exe (OptiScaler.ini); remove it for '
            'this way (its dxgi.dll was moved to the backup if it used that name).')


def uninstall_dlss(t):
    folder = t / FOLDER
    marker = folder / MARKER
    if not marker.exists():
        return
    rec = json.loads(marker.read_text())
    for name, ours in ((LOADER, is_loader), (CORE, is_helixsr)):
        if (t / name).exists() and ours(t / name):
            (t / name).unlink()
    for name in rec.get('moved', []):
        src = folder / BACKUP / name
        if src.exists() or src.is_symlink():
            os.replace(src, t / name)
    for n in (MARKER, 'helixsr.log'):
        if (folder / n).exists():
            (folder / n).unlink()
    for n in ('helixsr.log', 'helixsr_loader.log'):
        if (t / n).exists():
            (t / n).unlink()
    for d in (folder / BACKUP, folder):
        try:
            d.rmdir()
        except OSError:
            pass
    say(f'  removed from {t} (everything put back as it was)')


def install(g, here):
    if g.route != 'dlss' and g.dlss_installed:   # switching away from the DLSS loader
        say('  removing the DLSS loader first')
        uninstall_dlss(g.target)
        g.dlss_installed = False
    if g.route == 'dlss':
        if g.opti_installed:
            say('  removing OptiScaler first (the DLSS loader replaces it)')
            uninstall_optiscaler(g.target)
            g.opti_installed = False
        if any(original(t).exists() and is_helixsr(t) for t in g.fsr_targets):
            say('  removing the FSR drop-in first (the DLSS loader was picked for this game)')
            uninstall_direct(g)
        install_dlss(g.target, here)
        return
    if g.route == 'direct' and g.opti_installed:   # an earlier version used OptiScaler here: the drop-in replaces it
        say('  removing the OptiScaler install of an earlier version (this game has FSR 3.1: HelixSR replaces its FSR DLL)')
        uninstall_optiscaler(g.target)
        g.opti_installed = False
    if g.route == 'optiscaler' and any(original(t).exists() and is_helixsr(t) for t in g.fsr_targets):
        say('  removing the drop-in first (OptiScaler was picked for this game)')
        uninstall_direct(g)
    install_optiscaler(g.target, here) if g.route == 'optiscaler' else install_direct(g, here)
    if g.route == 'optiscaler' and g.chosen:   # remembered: updates keep the OptiScaler way
        m = g.target / FOLDER / MARKER
        rec = json.loads(m.read_text())
        rec['chosen'] = 'optiscaler'
        m.write_text(json.dumps(rec, indent=1) + '\n')
    if g.route == 'direct' and g.target and (g.target / 'OptiScaler.ini').exists():
        say('  NOTE: an OptiScaler that HelixSR did not install is next to the game\'s .exe (OptiScaler.ini); it can take '
            'over the game\'s FSR calls. For the drop-in, remove it (its dxgi.dll / winmm.dll etc. and OptiScaler.ini).')


def uninstall(g):
    if g.dlss_installed:
        uninstall_dlss(g.target)
        g.dlss_installed = False
        return
    if g.route == 'direct' and g.opti_installed:
        uninstall_optiscaler(g.target)
        g.opti_installed = False
    uninstall_optiscaler(g.target) if g.route == 'optiscaler' else uninstall_direct(g)


# --- manual install --------------------------------------------------------------------------------------------------

MANUAL = 'manual-install'
MANUAL_NOTE = """For a game the setup did not find. Easiest: run the setup and drag the game's folder into it when it asks for
another game; it picks the right way by itself. By hand:

1. A game with FSR 3.1 (also when it has DLSS): use the one-file DLLs in ../fsr3-drop-in (the network is inside them,
   see the README.txt there): rename the game's amd_fidelityfx_upscaler_dx12.dll (or, if it has none,
   amd_fidelityfx_dx12.dll) to *.original.dll and copy the file with the same name from fsr3-drop-in next to it.
   Select AMD FSR in the game. To undo: delete HelixSR's file and rename the *.original.dll back.

2. A game without FSR 3.1 (DLSS, XeSS or FSR 2 only): copy dxgi.dll, OptiScaler.ini, fakenvapi.dll and fakenvapi.ini
   from this folder next to the game's .exe (keep a copy of the game's own dxgi.dll first if it has one), start the
   game and select DLSS. This way keeps working only while this HelixSR folder stays where it is; OptiScaler.ini
   points at the HelixSR folder in here:
   {folder}
   To undo: delete the four files and put the game's own dxgi.dll back if it had one.

3. EXPERIMENTAL - a game with DLSS, without OptiScaler (read "Experimental: DLSS without OptiScaler" in HelixSR's
   README first: it may not work or may crash the game, it is not tested on Windows, and it must NOT be used in online
   games or games with anti-cheat: ban risk). Next to the game's .exe (keep a copy of the game's own dxgi.dll first if
   it has one):
     - copy ../dlss-loader/dxgi.dll
     - copy ../amd_fidelityfx_dx12.dll and rename the copy to nvngx.dll (the network is inside it after the setup)
   Start the game and select DLSS. Leave NVIDIA-only options (Reflex, Frame Generation) off.
   To undo: delete dxgi.dll and nvngx.dll and put the game's own dxgi.dll back if it had one.

Switching a game from OptiScaler (way 2) to the drop-in (way 1): undo way 2 first (next to the game's .exe: delete
dxgi.dll, OptiScaler.ini, fakenvapi.dll, fakenvapi.ini and the HelixSR folder, after putting back anything from
HelixSR\\backup), then do way 1. The setup does all of this for you: answer f (FSR 3 DLL) or o (OptiScaler)
at its question for the game.

Your own OptiScaler (any version): copy the two DLLs from ../fsr3-drop-in into a folder next to OptiScaler and set, in
its OptiScaler.ini:
   [Upscalers]  Dx12Upscaler = fsr31
   [Libraries]  FfxDx12Path = <full path of that folder>\\amd_fidelityfx_dx12.dll
                FfxDx12SRPath = <full path of that folder>\\amd_fidelityfx_upscaler_dx12.dll
HelixSR is then OptiScaler's FSR 3.1 upscaler (listed as FSR HelixSR in its menu).
"""


def make_manual(here):
    m = here / MANUAL
    m.mkdir(exist_ok=True)
    shutil.copyfile(here / 'optiscaler' / 'OptiScaler.dll', m / 'dxgi.dll')
    for n in OPTI_EXTRA:
        shutil.copyfile(here / 'optiscaler' / n, m / n)
    copy_helixsr(here, m / FOLDER, (OWN, OWN_SR))
    make_my_fsr(m / FOLDER)
    shutil.copyfile(fsr_source(here), m / FOLDER / AMD_FSR)
    shutil.copyfile(here / 'amd-fsr' / AMD_FG, m / FOLDER / AMD_FG)
    write_ini(m / 'OptiScaler.ini', point_at_helixsr(read_ini(here / 'optiscaler' / 'OptiScaler.ini'), m / FOLDER))
    (m / 'README.txt').write_text(MANUAL_NOTE.format(folder=win_path(m / FOLDER)),
                                  newline='\r\n' if os.name != 'nt' else None)


# --- main ------------------------------------------------------------------------------------------------------------

def show(gl):
    if not gl:
        say('no game with DLSS, XeSS or FSR found in your Steam libraries')
        return
    for i, g in enumerate(gl, 1):
        print(f'  {i:3}. {g.name:45} {"HelixSR installed" if g.installed() else g.label()}')


def pick(gl, words):
    out = []
    for w in words:
        if not w.isdigit() or not 1 <= int(w) <= len(gl):
            raise SystemExit(f'not a game number: {w}')
        out.append(gl[int(w) - 1])
    return out


def way(route):
    return {'optiscaler': 'OptiScaler', 'dlss': 'DLSS, experimental'}.get(route, 'FSR')


def in_game(route):
    return 'DLSS' if route in ('optiscaler', 'dlss') else 'AMD FSR'


def ask(g, todo, remove):
    """One short question per game: f = FSR 3 DLL, o = OptiScaler (where the game can use it), n = skip, r = remove.
    Enter = the first letter shown (the way the game has, else FSR where possible)."""
    now = 'dlss' if g.dlss_installed else 'optiscaler' if g.opti_installed else \
        'direct' if any(original(t).exists() for t in g.fsr_targets) else None
    ways = ['direct', 'optiscaler'] if g.can_opti else ['direct'] if g.fsr_targets else ['optiscaler'] if g.inputs and g.target else []
    if g.can_dlss:
        ways.append('dlss')
    if now in ways:
        ways.remove(now)
        ways.insert(0, now)
    keys = [{'direct': 'f', 'optiscaler': 'o', 'dlss': 'd'}[w] for w in ways] + (['r'] if now else []) + ['n']
    q = (f'{g.name}: installed ({way(now)}). Update? ' if now else f'{g.name}: install? ') + f'[{"/".join(keys)}] '
    while True:
        try:
            r = input(q).strip().lower()[:1] or keys[0]
        except EOFError:
            return False
        if r in keys or r == 'y':
            break
        say(f'  type one of: {", ".join(keys)}' + ('  (f only for games that have an FSR 3.1 DLL)' if r == 'f' else ''))
    if r in ('f', 'o', 'd', 'y'):
        g.route = ways[0] if r == 'y' else {'f': 'direct', 'o': 'optiscaler', 'd': 'dlss'}[r]
        g.chosen = g.route == 'optiscaler' and g.can_opti
        todo.append(g)
        say(f'  -> {way(g.route)} (installed after the last question)')
        if g.route == 'dlss':
            say('     EXPERIMENTAL: may not work or may crash the game; NOT for online games or games with anti-cheat (ban risk).')
            say('     Leave NVIDIA-only options (Reflex, Frame Generation) off. Back to normal: run the setup again, pick f or o.')
    elif r == 'r':
        g.route = now
        remove.append(g)
        say('  -> remove (after the last question)')
    else:
        say('  -> skipped')
    return True


def done_message(todo=()):
    print()
    if todo:
        say('Done. Start the game and pick this in its graphics settings:')
        for g in todo:
            say(f'  {g.name}: {in_game(g.route)}')
    else:
        say('Done. Start the game and pick AMD FSR in its graphics settings (DLSS in games that use OptiScaler).')
    say('helixsr.log (in the game\'s HelixSR folder, or next to the game\'s FSR DLL) shows what HelixSR is doing.')
    say(f'Games that were not listed: see {MANUAL}/README.txt.')


def remove_games(gl, here):
    """helixsr-uninstall: removes HelixSR from the games you pick (everything put back as it was), then optionally the
    network files and the setup's downloads."""
    inst = [g for g in gl if g.installed()]
    if not inst:
        say('HelixSR is not installed in any game the setup can find (other games: drop their folder onto the uninstaller)')
    else:
        print('Close your games first. For each game: Enter = remove, n = keep.\n')
        todo = []
        for g in inst:
            try:
                r = input(f'{g.name}: remove HelixSR? [Y/n] ').strip().lower()
            except EOFError:
                return
            if r in ('', 'y', 'yes'):
                todo.append(g)
        for g in todo:
            say(g.name)
            uninstall(g)
    left = [g.name for g in gl if g.installed()]
    extra = [here / n for n in NETWORK if (here / n).exists()]
    built = [d for d in (here / 'amd_fidelityfx_dx12.dll', here / 'nvngx.dll') if has_embedded_network(d)]
    dropin = here / 'fsr3-drop-in'
    extra += built + ([dropin] if dropin.exists() else [])
    data = Path(os.environ['LOCALAPPDATA']) / 'HelixSR' if os.name == 'nt' else \
        Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'HelixSR'
    if left or not (extra or data.exists()):
        say('done' + (f' (still installed in: {", ".join(left)})' if left else ''))
        return
    try:
        r = input('\nAlso delete the built network (in HelixSR\'s DLL, fsr3-drop-in) and the setup\'s downloads (Python, shader compiler)? [y/N] ')
    except EOFError:
        r = ''
    if r.strip().lower() in ('y', 'yes'):
        for p in extra:
            if p in built:
                strip_embedded_network(p)
            elif p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        say(f'deleted; to use HelixSR again, run helixsr-setup (it builds the network again)')
        if data.exists():
            raise SystemExit(3)   # helixsr-uninstall deletes the downloads folder after Python (it may live there) exits
    say('done')


def main():
    a = sys.argv[1:]
    if not a or a[0] in ('-h', '--help'):
        raise SystemExit(__doc__)
    here = Path(a.pop(0)).resolve()
    extra = []
    while '--folder' in a:
        i = a.index('--folder')
        extra.append(a[i + 1])
        del a[i:i + 2]
    a = [x for x in a if x != '--yes']
    cmd = a[0] if a else ''
    if cmd == 'remove':   # helixsr-uninstall: needs neither the network files nor numpy
        say('looking for games with HelixSR ...')
        remove_games(games(extra), here)
        return
    if not network_ready(here):
        raise SystemExit('the network files are missing: the setup builds them first')
    make_manual(here)
    src = fsr_source(here)
    if src.parent.name == 'my-fsr':
        say(f'using your FSR DLL from my-fsr ({src.name}) next to HelixSR')
    say('looking for games with DLSS, XeSS or FSR ...')
    gl = games(extra)
    if cmd == 'list':
        show(gl)
        return
    if not cmd:
        if not gl:
            show(gl)
        else:
            print('\nClose your games first.\n\n  f = FSR   o = OptiScaler   d = DLSS (experimental)   n = skip   r = remove      '
                  '(just Enter = the first letter)\n')
        todo, remove = [], []
        for g in gl:
            if not ask(g, todo, remove):
                return
        # games the scan did not find (not from Steam, other drives): one folder at a time; FSR 3.1 or OptiScaler is
        # picked the same way as for listed games
        while True:
            try:
                f = input('\nAnother game? Drag its folder here (or just Enter to finish): ').strip()
            except EOFError:
                break
            if not f:
                break
            for g in games_from([f], gl + todo + remove):
                ask(g, todo, remove)
        for g in remove:
            say(g.name)
            uninstall(g)
        if todo:
            say(f'HelixSR {version_of(here / DLL)}')
            for g in todo:
                say(g.name)
                install(g, here)
            done_message(todo)
        return
    if cmd in ('install', 'install-all'):
        targets = gl if cmd == 'install-all' else pick(gl, a[1:])
        say(f'HelixSR {version_of(here / DLL)}')
        for g in targets:
            say(g.name)
            install(g, here)
        done_message()
    elif cmd in ('uninstall', 'uninstall-all'):
        targets = [g for g in gl if g.installed()] if cmd == 'uninstall-all' else pick(gl, a[1:])
        for g in targets:
            say(g.name)
            uninstall(g)
        say('done')
    else:
        raise SystemExit(__doc__)


if __name__ == '__main__':
    main()
