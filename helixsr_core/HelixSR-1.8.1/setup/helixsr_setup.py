#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""helixsr_setup.py OUT_DIR [--dlss NVNGX_DLSS_DLL] [--yes] [--dxc DXC] [--keep WORK_DIR] [--wave64 | --no-wave64]

Builds HelixSR's network on the user's machine from NVIDIA's DLSS 310.7.0 DLL, downloaded from NVIDIA's own GitHub
(github.com/NVIDIA/DLSS, after the user agrees) or taken from a local copy (--dlss, e.g. from a game):
  1. weights  -> OUT_DIR/helixsr_weights.bin   (plain fp32 tensors in the DLL, converted as NVIDIA does)
  2. PTX of the network kernels (CUDA fatbins in the DLL; sm_89 when present, else sm_80)
  3. fragment tables of the family kernels (PTX simulator on launches built by HelixSR's host model)
  4. HLSL of every network kernel (translator + HelixSR's scheduling recipes)
  5. DXIL shaders -> OUT_DIR/helixsr_kernels.pak
  (a HelixSR 1.5/1.6 nvngx.dll in OUT_DIR gets them appended instead; HelixSR 1.7 keeps them as two files)
Nothing is downloaded and nothing leaves the machine. Needs Python 3 with numpy, a C++ compiler (g++/clang++) and
DXC (the DirectX shader compiler)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import hashlib, json, os, re, shutil, struct, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
# NVIDIA's DLSS SDK release v310.7.0, the DLL this setup is verified with (checked before use)
DLSS_URL = 'https://raw.githubusercontent.com/NVIDIA/DLSS/v310.7.0/lib/Windows_x86_64/rel/nvngx_dlss.dll'
DLSS_SHA256 = 'be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e'
DLSS_LICENSE = 'https://github.com/NVIDIA/DLSS/blob/v310.7.0/LICENSE.txt'


def download_dlss(work, assume_yes):
    print(f"HelixSR needs NVIDIA's DLSS 310.7.0 DLL to build its network on this PC. It will be downloaded from\n"
          f"NVIDIA's GitHub ({DLSS_URL}), used once and deleted. The DLL is NVIDIA's, under NVIDIA's license:\n"
          f"{DLSS_LICENSE}")
    if not assume_yes and input('Download it now? [Y/n] ').strip().lower() not in ('', 'y', 'yes'):
        raise SystemExit('Nothing was built: HelixSR does not work until the setup has built its network. Run the setup '
                         'again and answer y, or pass a local copy of the DLL with --dlss <path>.')
    import urllib.request
    path = work / 'nvngx_dlss.dll'
    step('downloading nvngx_dlss.dll from NVIDIA')
    with urllib.request.urlopen(DLSS_URL, timeout=120) as r, open(path, 'wb') as f:
        size = int(r.headers.get('Content-Length') or 0)
        got = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            BAR.draw(100.0 * got / size if size else 0, f'download {got >> 20}/{size >> 20} MB', 0)
    BAR.clear()
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != DLSS_SHA256:
        path.unlink()
        raise SystemExit('the downloaded file is not the expected DLSS 310.7.0 DLL; nothing was built')
    path.unlink()
    return data
LIB = HERE / 'lib'
sys.path.insert(0, str(LIB))
PAK_MAGIC = b'HXSRKPAK'
PAK_VERSION = 2
# wave64 kernels whose cross-lane reads go through LDS (verified bit-identical with wave32; not the small reductions)
LDS_READS = {'k5', 'k5f', 'k5n', 'k7', 'k9', 'k10', 'k11'}
DXC_ARGS = ['-T', 'cs_6_6', '-E', 'main', '-O3', '-HV', '2021', '-enable-16bit-types', '-D', 'PX_FAST=1']


def step(msg):
    BAR.clear()
    print(f'[helixsr-setup] {msg}', flush=True)


class Progress:
    """One bar for the whole build. Each stage has a share of the bar (its typical share of the build time) and
    reports how far it is (0..1). On a terminal the bar is redrawn in place; in a log only stage changes are printed."""
    STAGES = [('weights', 2), ('ptx', 5), ('tables', 6), ('sources', 12), ('shaders', 75)]   # measured (16 threads)

    def __init__(self):
        self.tty = True   # lines, not in-place redraws: fine for terminals and logs alike
        self.start = {k: sum(w for _, w in self.STAGES[:i]) for i, (k, _) in enumerate(self.STAGES)}
        self.weight = dict(self.STAGES)
        self.total = sum(self.weight.values())
        self.shown = False
        self.times = {}
        import time, threading
        self.clock = time.monotonic
        self.t0 = None
        self.lock = threading.Lock()
        self.cur = None   # (stage, frac or a function returning it, label): redrawn twice a second while active
        self.ticker = None

    def update(self, stage, frac, label):
        now = self.clock()
        with self.lock:
            if self.t0 is None:
                self.t0 = now
            self.times.setdefault(stage, now)
            self.cur = (stage, frac, label)
            self._redraw(now)
        if self.tty and self.ticker is None:
            import threading
            self.ticker = threading.Thread(target=self._tick, daemon=True)
            self.ticker.start()

    def _redraw(self, now):
        stage, frac, label = self.cur
        f = frac() if callable(frac) else frac
        pct = 100.0 * (self.start[stage] + self.weight[stage] * min(max(f, 0.0), 1.0)) / self.total
        self.draw(pct, label() if callable(label) else label, now - self.t0)

    def _tick(self):
        import time
        while True:
            time.sleep(0.5)
            with self.lock:
                if self.cur is not None:
                    self._redraw(self.clock())

    def draw(self, pct, label, elapsed):
        """A new line whenever the bar moves on by 5% (or every 5 seconds): no in-place redrawing, which some terminals
        (and log views) do not show, so it reads the same everywhere."""
        now = self.clock()
        step5 = int(pct // 5)
        if step5 == getattr(self, '_last5', None) and now - getattr(self, '_lastT', 0) < 5:
            return
        self._last5, self._lastT = step5, now
        n = int(20 * pct / 100)
        el = int(elapsed)
        print(f'[helixsr-setup] [{"#" * n}{"-" * (20 - n)}] {pct:4.0f}%  {el // 60}:{el % 60:02d}  {label}', flush=True)

    def report_times(self):
        """HELIXSR_SETUP_TIMES=1: seconds per stage (to tune STAGES)."""
        if not os.environ.get('HELIXSR_SETUP_TIMES'):
            return
        ks = [k for k, _ in self.STAGES if k in self.times] + ['end']
        self.times['end'] = self.clock()
        print('[helixsr-setup] stage seconds: ' + ', '.join(f'{a} {self.times[b] - self.times[a]:.0f}' for a, b in zip(ks, ks[1:])))

    def clear(self):
        with self.lock:
            self.cur = None   # the ticker stops drawing until the next update
            self._clear()

    def _clear(self):
        if self.shown:
            sys.stdout.write('\n')
            self.shown = False


BAR = Progress()


def run(cmd, env=None, **kw):
    p = subprocess.run([str(c) for c in cmd], env=env, capture_output=True, text=True, **kw)
    if p.returncode:
        raise SystemExit(f'failed: {" ".join(map(str, cmd))}\n{p.stdout[-2000:]}{p.stderr[-2000:]}')
    return p.stdout


def amd_gpus():
    """PCI device ids of this PC's AMD display GPUs (Linux: sysfs, Windows: the registry); empty if none found."""
    ids = set()
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Enum\PCI') as pci:
                for k in range(4096):
                    try:
                        name = winreg.EnumKey(pci, k)
                    except OSError:
                        break
                    if not name.upper().startswith('VEN_1002&DEV_'):
                        continue
                    with winreg.OpenKey(pci, name) as dk:
                        for j in range(64):
                            try:
                                inst = winreg.EnumKey(dk, j)
                            except OSError:
                                break
                            try:
                                with winreg.OpenKey(dk, inst) as ik:
                                    if str(winreg.QueryValueEx(ik, 'Class')[0]).lower() == 'display':
                                        ids.add(int(name[13:17], 16))
                            except OSError:
                                pass
        except OSError:
            pass
    else:
        for d in Path('/sys/class/drm').glob('card[0-9]*/device'):
            try:
                if (d / 'vendor').read_text().strip() == '0x1002' and (d / 'class').read_text().startswith('0x03'):
                    ids.add(int((d / 'device').read_text(), 16))
            except (OSError, ValueError):
                pass
    return ids


def rdna3_or_newer(dev):
    """Same rule as the DLL: these GPUs run the network kernels at 64 lanes."""
    return (0x7440 <= dev <= 0x74ff or 0x7550 <= dev <= 0x75ff or
            dev in (0x15bf, 0x15c8, 0x1900, 0x1901, 0x150e, 0x1586, 0x1114))


EMBED_MAGIC = b'HXSRNET1'
DROP_IN_README = '''HelixSR for FSR 3.1 games, one file (the network is inside the DLL).

Most FSR 3.1 games: go to the folder that holds the game's amd_fidelityfx_upscaler_dx12.dll (or, if there is none,
amd_fidelityfx_dx12.dll), rename the game's file to amd_fidelityfx_upscaler_dx12.original.dll (or
amd_fidelityfx_dx12.original.dll), and copy the file with the same name from this folder there. Start the game and
pick AMD FSR. Keep the .original.dll: FSR frame generation keeps working through it, and renaming it back undoes
everything. helixsr.log next to the DLL shows what HelixSR is doing.

The setup does this for you for the games it finds. These DLLs contain NVIDIA's network: they are for your own PC,
do not share or upload them.
'''


def embed(dll_path, weights, pak):
    """Appends the network to HelixSR's DLL: [DLL][weights][pak][footer: magic, u64 weights size, u64 pak size,
    u64 format 1]. Windows does not map data after a DLL's sections; HelixSR reads it from its own file. An earlier
    payload is replaced."""
    data = dll_path.read_bytes()
    if data[-32:-24] == EMBED_MAGIC:
        nw, np_, _ = struct.unpack('<QQQ', data[-24:])
        data = data[:len(data) - 32 - nw - np_]
    if data[:2] != b'MZ':
        raise SystemExit(f'{dll_path} is not a DLL')
    tmp = dll_path.with_name(dll_path.name + '.tmp')
    want = data + weights + pak + EMBED_MAGIC + struct.pack('<QQQ', len(weights), len(pak), 1)
    tmp.write_bytes(want)
    os.replace(tmp, dll_path)
    # check what is on disk now (security software or sync folders can block or change a fresh DLL)
    got = dll_path.read_bytes()
    if got != want:
        raise SystemExit(f'{dll_path} is not what was written: {len(got)} bytes on disk, {len(want)} written'
                         f'{" (no network at its end)" if got[-32:-24] != EMBED_MAGIC else ""}. Something on this PC changes '
                         'or replaces new DLLs in this folder (antivirus, a synced folder such as OneDrive): extract HelixSR '
                         'into a plain folder such as C:\\HelixSR and run the setup there.')
    return len(got)


def main():
    a = sys.argv[1:]
    opt = lambda k: a[a.index(k) + 1] if k in a else None
    dxc = opt('--dxc') or shutil.which('dxc')
    keep = Path(opt('--keep')) if opt('--keep') else None
    pos = [x for i, x in enumerate(a)
           if not x.startswith('--') and (i == 0 or a[i - 1] not in ('--dxc', '--keep', '--dlss'))]
    if len(pos) != 1 or not dxc:
        raise SystemExit(__doc__)
    out = Path(pos[0])
    out.mkdir(parents=True, exist_ok=True)
    work = keep or Path(tempfile.mkdtemp(prefix='helixsr-setup-'))
    work.mkdir(parents=True, exist_ok=True)
    dll = Path(opt('--dlss')).read_bytes() if opt('--dlss') else download_dlss(work, '--yes' in a)
    dll_sha = hashlib.sha256(dll).hexdigest()

    step('building the network (about a minute)')
    BAR.update('weights', 0, 'weights')
    import extract_weights
    (out / 'helixsr_weights.bin').write_bytes(extract_weights.extract(dll))

    BAR.update('ptx', 0, 'reading the network kernels')
    import extract_ptx
    from kernels import ENTRY
    ptx = work / 'ptx'
    ptx.mkdir(exist_ok=True)
    have = set()
    for entry, sm, text in extract_ptx.modules(dll):
        (ptx / f'{entry}.sm_{sm}.ptx').write_text(text)
        have.add((entry, sm))
    sm = next((s for s in (89, 80) if all((e, s) in have for e in ENTRY.values())), None)
    if sm is None:
        raise SystemExit('this nvngx_dlss.dll does not contain the network kernels HelixSR uses')
    env = dict(os.environ, HELIXSR_PTX_DIR=str(ptx), HELIXSR_PTX_SM=str(sm),
               HELIXSR_FAMILY_TABLES=str(work / 'tables'))
    BAR.update('tables', 0, 'fragment tables')
    m = LIB / 'model'
    synth = m / ('launch_synth.exe' if os.name == 'nt' else 'launch_synth')   # prebuilt, static
    if not synth.exists():
        cxx = os.environ.get('CXX') or shutil.which('g++') or shutil.which('clang++')
        if not cxx:
            raise SystemExit('no prebuilt launch_synth and no C++ compiler found')
        synth = work / synth.name
        run([cxx, '-std=c++17', '-O2', f'-I{m}', m / 'model.cpp', m / 'launch_synth.cpp', '-o', synth])
    families = ['k4', 'k9', 'k10', 'k11', 'k7', 'u5', 'u6', 'u8', 'u9']
    from concurrent.futures import ThreadPoolExecutor, as_completed
    BAR.update('tables', 0, f'fragment tables 0/{len(families)}')
    with ThreadPoolExecutor(max_workers=max(1, min(len(families), os.cpu_count() or 4))) as pool:
        futs = [pool.submit(run, [sys.executable, LIB / 'trace_tables.py', work / 'tables', '--model', synth, k], env=env)
                for k in families]
        for i, fut in enumerate(as_completed(futs), 1):
            fut.result()
            BAR.update('tables', i / len(families), f'fragment tables {i}/{len(families)}')

    BAR.update('sources', 0, 'preparing shaders')
    src = work / 'kernels'
    run([sys.executable, LIB / 'regen_kernels.py', src], env=env)

    import regen_kernels
    rt = HERE / 'kernels/rt'
    shaders = [(f'px_{n}', src / n, f'{n}.hlsl') for n in regen_kernels.RECIPES]
    shaders.append(('px_u5_table', src / 'u5/table', 'u5.hlsl'))
    blobs = []
    # Every shader is also built for 64-lane waves ("<name>_w64"): GPUs without wave32 (GCN/Vega) use those. The text
    # is the same with the wave-size attribute changed; the arithmetic does not depend on the wave size. --no-wave64
    # skips them (about half the build time) for GPUs known to run wave32 (RDNA 1-4).
    # Both sizes are always built (as 1.4.3), whatever this PC's GPU: the DLL picks per GPU at run time; --no-wave64
    # skips the 64-lane copies.
    want64 = '--no-wave64' not in a
    jobs = []   # (blob name, dxc command, output): all prepared first, then compiled in parallel
    for name, d, f in shaders:
        cso = work / f'{name}.cso'
        jobs.append((name, [dxc] + DXC_ARGS + ['-I', d, '-I', rt, '-Fo', cso, d / f], cso))
        if want64:
            text = (d / f).read_text()
            assert '[WaveSize(32)]' in text, (name, 'no wave size attribute')
            tmp64 = d / ('w64_' + f)
            text64 = text.replace('[WaveSize(32)]', '[WaveSize(64)]')
            extra = []
            if name[3:] in LDS_READS or name[3:].startswith('k8_'):
                # cross-lane reads through LDS (kernels/rt/px_hlsl.h, PX_LDS_SHUFFLE): same results, ~25% faster at 64 lanes
                text64, k = re.subn(r'\{ (\w+_body)\(tid, gid\); \}',
                                    r'{ PX_SET_GI(tid.x + tid.y * PX_BLOCK_X + tid.z * PX_BLOCK_X * PX_BLOCK_Y); \1(tid, gid); }', text64)
                assert k == 1, (name, 'entry point')
                extra = ['-D', 'PX_LDS_SHUFFLE=1']
            tmp64.write_text(text64)
            cso64 = work / f'{name}_w64.cso'
            jobs.append((name + '_w64', [dxc] + DXC_ARGS + extra + ['-I', d, '-I', rt, '-Fo', cso64, tmp64], cso64))
    workers = max(1, min(len(jobs), os.cpu_count() or 4))
    # measured compile seconds (16 threads busy): the slow ones start first so they do not trail at the end, and the
    # bar counts each shader by its cost, with the ones still compiling counted in part (scaled to this PC's speed)
    secs = {'px_k8_hdr_colvar_mvhi': 27, 'px_u8': 27, 'px_u9': 26, 'px_k5n': 26, 'px_k10': 17, 'px_u5_table': 15,
            'px_u5': 15, 'px_u6': 14, 'px_k7': 10, 'px_k9': 9, 'px_u4': 6, 'px_k8_rel': 6, 'px_k4': 5, 'px_k5': 4,
            'px_u10': 4, 'px_k5f': 4}
    est = [secs.get(n[:-4] if n.endswith('_w64') else n, 3 if n.startswith('px_k8_') else 1) for n, _, _ in jobs]
    warm = min(range(len(jobs)), key=lambda i: est[i])   # a quick one starts the compiler (and its Wine prefix) alone
    order = sorted((i for i in range(len(jobs)) if i != warm), key=lambda i: -est[i])
    import time as _t
    total = float(sum(est))
    state = {'done': 0.0, 'n': 0, 'running': {}}

    def frac():
        now = _t.monotonic()
        part = sum(min((now - s) / est[i], 0.95) * est[i] for i, s in list(state['running'].items()))
        return (state['done'] + part) / total

    def label():
        return f'shaders {state["n"]}/{len(jobs)}' if state['n'] else 'starting the shader compiler'

    def timed(i):
        state['running'][i] = s = _t.monotonic()
        run(jobs[i][1])
        secs = _t.monotonic() - s
        del state['running'][i]
        state['done'] += est[i]
        state['n'] += 1
        return jobs[i][0], secs

    BAR.update('shaders', frac, label)
    timed(warm)   # alone first: it may have to set up the compiler's Wine prefix
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for fut in as_completed([pool.submit(timed, i) for i in order]):
            jname, secs = fut.result()   # raises (SystemExit with the compiler output) if a compile failed
            if os.environ.get('HELIXSR_SETUP_TIMES'):
                BAR.clear(); print(f'[helixsr-setup] compile {jname} {secs:.1f} s', flush=True)
                BAR.update('shaders', frac, label)
    blobs = [(name, cso.read_bytes()) for name, _, cso in jobs]   # same order as before
    table = b''.join(struct.pack('<32sII', n.encode(), 0, len(b)) for n, b in blobs)
    offs, pos_ = [], 16 + len(table)
    for _, b in blobs:
        offs.append(pos_)
        pos_ += len(b)
    table = b''.join(struct.pack('<32sII', n.encode(), o, len(b)) for (n, b), o in zip(blobs, offs))
    # pak version 2: k7/k11 carry split-K (the DLL splits their K loop only with these shaders)
    (out / 'helixsr_kernels.pak').write_bytes(PAK_MAGIC + struct.pack('<II', PAK_VERSION, len(blobs)) + table +
                                              b''.join(b for _, b in blobs))
    (out / 'helixsr_setup.json').write_text(json.dumps(dict(
        source_sha256=dll_sha, ptx_target=f'sm_{sm}', shaders=len(blobs), wave64=want64,
        weights_sha256=hashlib.sha256((out / 'helixsr_weights.bin').read_bytes()).hexdigest()), indent=1) + '\n')
    BAR.update('shaders', 1, 'done')
    BAR.clear()
    BAR.report_times()
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    # one-file DLL: the network is appended to the package's HelixSR DLL and the two files are removed (the installer
    # copies only the DLL; fsr3-drop-in/ gets copies under FSR 3.1's file names). A 1.5/1.6 nvngx.dll is still filled.
    target = next((p for p in (out / 'amd_fidelityfx_dx12.dll', out / 'nvngx.dll') if p.exists()), out / 'nvngx.dll')
    if '--separate-files' not in a and target.exists():
        size = embed(target, (out / 'helixsr_weights.bin').read_bytes(), (out / 'helixsr_kernels.pak').read_bytes())
        (out / 'helixsr_weights.bin').unlink()
        (out / 'helixsr_kernels.pak').unlink()
        step(f'done: {target} now carries the network ({len(blobs)} shaders, {size / 1e6:.1f} MB, checked on disk)')
        drop = out / 'fsr3-drop-in'
        drop.mkdir(exist_ok=True)
        for n in ('amd_fidelityfx_dx12.dll', 'amd_fidelityfx_upscaler_dx12.dll'):
            shutil.copyfile(target, drop / n)
        (drop / 'README.txt').write_text(DROP_IN_README, newline='\r\n' if os.name != 'nt' else None)
        step(f'drop-in DLLs for FSR 3.1 games: {drop}')
        step('they contain NVIDIA\'s network: they are for your own PC, do not share or upload them')
    else:
        for n in ('helixsr_weights.bin', 'helixsr_kernels.pak'):   # what is on disk now (antivirus, synced folders)
            if not (out / n).exists() or (out / n).stat().st_size == 0:
                raise SystemExit(f'{out / n} is missing after the build: something on this PC removes new files in this folder '
                                 '(antivirus or a synced folder). Extract HelixSR into a plain folder such as C:\\HelixSR.')
        step(f'done: the network is built: {out}/helixsr_weights.bin and helixsr_kernels.pak ({len(blobs)} shaders)')


if __name__ == '__main__':
    main()
