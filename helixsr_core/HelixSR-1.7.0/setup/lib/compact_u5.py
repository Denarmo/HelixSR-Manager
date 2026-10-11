#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Apply the repeatable 32 KiB U5 LDS transformation after PTX generation."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
from pathlib import Path
import argparse

p = argparse.ArgumentParser()
p.add_argument('--kernel-dir', type=Path, default=Path(__file__).resolve().parents[1] / 'kernels/u5')
a = p.parse_args()
kd = a.kernel_dir
body = kd / 'u5_body.h'
s = body.read_text()
if '#include "u5_memory.h"' not in s:
    s = '#include "u5_memory.h"\n' + s
    s = s.replace('void u5_body(uint3 tid, uint3 ctaid) {', 'void u5_body(uint3 tid, uint3 ctaid) {\n    U5_PHASE = 0u;')
    # Compact two 16 KiB activation slabs. The old stride has 16 B padding
    # per row and a 64 B gap between slabs. All activation addresses are
    # calculated from these bases; the second stage already uses dense LDS.
    import re
    # (register names differ between PTX builds: match the statements by shape)
    rows = re.findall(r'(x_r\d+) = \((x_r\d+) \* 0x810U\);', s)
    assert len(rows) == 2, rows
    for d, x in rows:
        s = s.replace(f'{d} = ({x} * 0x810U);', f'{d} = ({x} * 0x800U);')
    for before, after in (('0x40c0U', '0x4000U'), ('0x4140U', '0x4080U'), ('0x8140U', '0x8000U')):
        assert before in s, before
        s = s.replace(before, after)
    # phase 1 starts at the barrier before the second stage's loop counter (= 0x1f)
    m = re.search(r'        PX_BARRIER\(\);\n(        x_r\d+ = 0x1fU;)', s)
    assert m, 'phase barrier'
    s = s[:m.start(1)] + '        U5_PHASE = 1u;\n' + s[m.start(1):]
    body.write_text(s)
cfg = kd / 'u5_cfg.h'
s = cfg.read_text().replace('#define PX_SMEM_WORDS 12288', '#define PX_SMEM_WORDS 8192')
if '#define PX_U5_COMPACT' not in s:
    s += '#define PX_U5_COMPACT 1\n'
cfg.write_text(s)
# The first-stage matrix loads include two/four/six padded row strides.
# Keep this separate so rerunning also updates an already compacted body.
s = body.read_text()
import re
base = re.search(r'\((x_r\d+) \+ 0x1020U\)', s) or re.search(r'\((x_r\d+) \+ 0x1000U\)', s)
assert base, 'first-stage matrix base'
for old, new in [(0x1020, 0x1000), (0x2040, 0x2000), (0x3060, 0x3000)]:
    for extra in (0, 0x200, 0x400, 0x600):
        before = f'({base[1]} + 0x{old + extra:x}U)'
        after = f'({base[1]} + 0x{new + extra:x}U)'
        s = s.replace(before, after)
body.write_text(s)
# Family helpers use decimal stage-relative row offsets, with the same padding.
s = body.read_text()
import re
if '// U5 family activation padding compacted.' not in s and 'family_seg' in s:
    s = re.sub(r'fam_row\((pA0_\d+) \+ (\d+)u\)',
               lambda m: 'fam_row(' + m[1] + ' + ' + str(int(m[2]) - (int(m[2]) // 0x810) * 16) + 'u)', s)
    s = '// U5 family activation padding compacted.\n' + s
if '// U5 family second-stage weight bases rebased.' not in s and 'family_seg1(' in s:
    # Phase 2 reuses the phase-1 B base addresses in the trace table, with
    # -0x140 relative offsets because its original weight tile starts at
    # 0x8000 rather than 0x8140. Compaction moved only the first tile's base.
    s = re.sub(r'family_seg1\(family_acc1,[^;]+;',
               lambda m: re.sub(r'\bfamily_baseB(\d+)\b', r'(family_baseB\1 + 0x140u)', m[0]), s)
    s = '// U5 family second-stage weight bases rebased.\n' + s
body.write_text(s)
