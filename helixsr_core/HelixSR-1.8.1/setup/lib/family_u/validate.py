# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""What the family tracer needs: the PTX simulator, kernel names/PTX paths, and the rounding-site parser."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ptxsim_up as ptxsim
from kernels import K, ENTRY
NAMES = {n.upper(): {'ptx': K[n]['ptx'], 'kernel': ENTRY[n]} for n in K}
R0 = R_UP = None


def sites(spec, n):
    if spec in (None, ''):
        return set()
    if spec == 'all':
        return set(range(n))
    out = set()
    for part in spec.split(','):
        a, _, b = part.partition('-')
        out.update(range(int(a), int(b or a) + 1))
    return out
