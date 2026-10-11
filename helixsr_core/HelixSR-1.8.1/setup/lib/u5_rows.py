#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Specialize compact U5 family rows: activation LDS versus immutable SRV weights."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse
from pathlib import Path
import re
p=argparse.ArgumentParser()
p.add_argument('kernel_dir',type=Path)
a=p.parse_args()
f=a.kernel_dir/'u5_body.h'
s=f.read_text()
marker='// Specialized U5 family vector rows.'
if marker in s: raise SystemExit('already specialized')
helper=marker+'''
famu4 fam_act_row(uint a) {
#ifdef __cplusplus
    return px_row(a);
#else
    uint4 v = SMR[a >> 4];
    return px_mkrow(px_u2h2(v.x), px_u2h2(v.y), px_u2h2(v.z), px_u2h2(v.w));
#endif
}
'''
for stage,slot,rp,cp,sp in [(0,2,56,52,100),(1,4,280,276,324)]:
    helper+=f'''
famu4 fam_weight_row{stage}(uint a) {{
    uint b = a - 0x8000u;
    uint row = b >> 7;
    uint col = ((b & 127u) >> 4) ^ (row & 7u);
    if (row >= PX_PARAM32({rp}u) || col * 8u >= PX_PARAM32({cp}u)) return px_row0();
    uint4 v = PX_GLD4({slot}, (row * PX_PARAM32({sp}u) + col * 8u) * 2u);
    return px_mkrow(px_u2h2(v.x), px_u2h2(v.y), px_u2h2(v.z), px_u2h2(v.w));
}}
'''
s=s.replace('famh2 fam_h2(',helper+'\nfamh2 fam_h2(',1)
for stage in [0,1]:
    start=s.index(f'FAM_API void family_seg{stage}(')
    end=s.index('\nvoid u5_body(',start) if stage==1 else s.index('FAM_API void family_seg1(',start)
    part=s[start:end]
    part,nA=re.subn(r'fam_row\((pA[^;]+)\)',r'fam_act_row(\1)',part)
    part,nB=re.subn(r'fam_row\((pB[^;]+)\)',f'fam_weight_row{stage}(\\1)',part)
    if not nA or not nB: raise RuntimeError('missing family rows')
    print(f'stage={stage} activation_rows={nA} weight_rows={nB}')
    s=s[:start]+part+s[end:]
f.write_text(s)
