#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""trace_tables.py OUT_DIR name...: fragment tables (<K>.json) of the family kernels for the PTX that tools/kernels.py
selects (HELIXSR_PTX_DIR), traced by the family tracer (trace_frags.py) on one captured launch of each kernel.
family_hlsl.py reads them with HELIXSR_FAMILY_TABLES=OUT_DIR."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import importlib.util, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kernels import K   # noqa: E402

PERF = HERE


def tracer(name):
    src = PERF / ('family_u' if name.startswith('u') else 'family_k')
    for m in [m for m, v in sys.modules.items() if getattr(v, '__file__', None) and str(PERF) in str(v.__file__)]:
        del sys.modules[m]   # each tracer folder has its own validate/ptxsim modules
    sys.path.insert(0, str(src))
    spec = importlib.util.spec_from_file_location(f'trace_frags_{src.name}', src / 'trace_frags.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.remove(str(src))
    return mod


def synth_run(t, kk, work):
    """A run directory holding only the launch the tracer uses, with every buffer randomised."""
    import subprocess, tempfile
    cap = [r for r in sorted((Path(t.R0) / 'replay').iterdir()) if r.name.endswith(t.V.NAMES[kk]['kernel'])][0]
    run = Path(tempfile.mkdtemp(dir=work))
    subprocess.run([sys.executable, str(HERE / 'synth_capture.py'), str(cap), str(run / 'replay' / cap.name)],
                   check=True)
    return run


def model_run(t, kk, work, synth_tool):
    """A run directory with one launch built from HelixSR's host model alone (no recording): 1920x1080 from 1280x720
    for the main network, 3840x2160 from 1280x720 for the Ultra Performance network, buffers random."""
    import subprocess, tempfile
    kernel = t.V.NAMES[kk]['kernel']
    shape = ['3840', '2160', '1280', '720'] if kernel.startswith('dltss_nhwc') else ['1920', '1080', '1280', '720']
    run = Path(tempfile.mkdtemp(dir=work))
    subprocess.run([synth_tool, str(run / 'replay' / f'replay-000000-{kernel}'), kernel] + shape, check=True,
                   capture_output=True)
    return run


def main():
    import shutil, tempfile
    model = None
    if '--model' in sys.argv:
        model = sys.argv[sys.argv.index('--model') + 1]   # path of the launch_synth tool
    args = [a for i, a in enumerate(sys.argv[1:], 1) if a not in ('--synth', '--model') and sys.argv[i - 1] != '--model']
    synth = '--synth' in sys.argv
    out = Path(args[0])
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp())
    for name in args[1:]:
        t = tracer(name)
        kk = name.upper()
        t.V.NAMES[kk]['ptx'] = K[name]['ptx']
        run = model_run(t, kk, work, model) if model else synth_run(t, kk, work) if synth else t.R0
        tab = t.tables(kk, run)
        (out / f'{kk}.json').write_text(json.dumps(tab, indent=1, default=str) + '\n')
        print(name, 'sites', len(tab['sites']), 'chains', len(tab['chains']),
              'iterations agree', all(s['iterations_agree'] for s in tab['sites']))
    shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()
