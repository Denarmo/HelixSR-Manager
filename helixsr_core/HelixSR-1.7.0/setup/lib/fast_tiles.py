#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""fast_tiles.py BODY: give every compact_N(...) call of a joint-fragment body (tools/compact_hlsl.py) a PX_FAST
alternative that reads its operand rows directly: A rows from LDS (pxr_arows_lds at the A ldmatrix address) or from
registers (pxr_arows_reg), then one pxr_tile per output tile with the B ldmatrix address and half (0u / 2u).

compact_N(d0..d(2N-1), a0..a3, b0_0, b0_1, ..., b(N-1)_0, b(N-1)_1): tile i accumulates into d(2i), d(2i+1); each
px_ldmatrix_x4 of B operands feeds two consecutive tiles (its first two words: half 0u, its last two: half 2u).
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import re, sys
from pathlib import Path

LDM = re.compile(r'\{ uint _lm0, _lm1, _lm2, _lm3;\s*px_ldmatrix_x4\(_lm0, _lm1, _lm2, _lm3, (x_\w+)\);\s*'
                 r'(x_\w+) = _lm0;\s*(x_\w+) = _lm1;\s*(x_\w+) = _lm2;\s*(x_\w+) = _lm3;\s*\}')
CALL = re.compile(r'^(\s*)compact_(\d+)\(([^;]*)\);$', re.M)


def transform(text):
    src = {}   # register -> (ldmatrix address, word index)
    for m in LDM.finditer(text):
        for i in range(4):
            src[m.group(2 + i)] = (m.group(1), i)

    def fast(m):
        ind, n, args = m.group(1), int(m.group(2)), [x.strip() for x in m.group(3).split(',')]
        d, a, b = args[:2 * n], args[2 * n:2 * n + 4], args[2 * n + 4:]
        assert len(b) == 2 * n, m.group(0)
        if all(x in src for x in a) and len({src[x][0] for x in a}) == 1 and [src[x][1] for x in a] == [0, 1, 2, 3]:
            rows = f'pxr_arows_lds({src[a[0]][0]}, _pu, _pl);'
        else:
            rows = f'pxr_arows_reg({", ".join(a)}, _pu, _pl);'
        tiles = []
        for t in range(n):
            addr, word = src[b[2 * t]]
            assert src[b[2 * t + 1]] == (addr, word + 1) and word in (0, 2), (b[2 * t], b[2 * t + 1])
            tiles.append(f'pxr_tile({d[2 * t]}, {d[2 * t + 1]}, _pu, _pl, {addr}, {word}u);')
        return (f'#ifdef PX_FAST\n{ind}{{ PXH2 _pu[8], _pl[8]; {rows} {" ".join(tiles)} }}\n#else\n'
                f'{m.group(0)}\n#endif')

    return CALL.sub(fast, text)


if __name__ == '__main__':
    p = Path(sys.argv[1])
    p.write_text(transform(p.read_text()))
