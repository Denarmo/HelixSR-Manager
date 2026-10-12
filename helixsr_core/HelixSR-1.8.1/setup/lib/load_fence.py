#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""load_fence.py BODY: just-in-time B-row loads for a rolled family body (tools/u5_roll.py --name u9).

Each B-row group (const famu4 rowN_* = fam_row(pBq_...), N >= 1) moves to just before the first block that reads it,
every other group (1st, 3rd, ... in order) behind a fam_load_fence() (a workgroup barrier on the GPU, nothing in
the CPU emulator), so that only the rows in use are live. Empty lines inside the family segment are dropped, except
before the last group and at the end of the segment.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import re, sys
from pathlib import Path

HELPER = '#ifdef __cplusplus\nvoid fam_load_fence() {}\n#else\nvoid fam_load_fence() { GroupMemoryBarrierWithGroupSync(); }\n#endif\n'
ROW = re.compile(r'^\s*const famu4 (row(\d+)_\d+_\d+ = fam_row\(pBq_.*)$')


def transform(text, name='u9'):
    start = text.index('FAM_API void family_seg0(')
    end = text.index(f'\nvoid {name}_body', start)
    seg = text[start:end].split('\n')
    groups, rest = {}, []
    for l in seg:
        m = ROW.match(l)
        if m and int(m.group(2)) >= 1:
            groups.setdefault(int(m.group(2)), []).append('const famu4 ' + m.group(1))
        elif l.strip():
            rest.append(l)
    order = sorted(groups)
    for seq, n in enumerate(order):
        use = next(i for i, l in enumerate(rest) if f'fam_h2(row{n}_' in l)
        block = max(i for i in range(use) if rest[i] == '  {')
        # the last group already sits before its block: it keeps its separating empty line
        rest[block:block] = (['fam_load_fence();'] if seq % 2 == 0 else []) + ([''] if n == order[-1] else []) + groups[n]
    text = text[:start] + '\n'.join(rest) + '\n' + text[end:]
    anchor = '#define FAM_API\n'
    assert text.count(anchor) == 1
    return text.replace(anchor, anchor + HELPER)


if __name__ == '__main__':
    p = Path(sys.argv[1])
    p.write_text(transform(p.read_text()))
