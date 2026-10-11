#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Regenerate HelixSR's network kernel sources from PTX and compare them with a reference kernel tree.

  regen_kernels.py OUT [--ref KERNELS_DIR] [--only a,b,...]

Every kernel is a recipe: the PTX translator (tools/ptx2hlsl.py) or the family scheduler (tools/family_hlsl.py)
with recorded options, then the post-generation rules the shipped kernels carry (fast-numerics switch, numerics
flags, shared-memory size, split-K). With --ref, each generated .hlsl/_body.h/_cfg.h is compared byte for byte.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from kernels import K   # noqa: E402  (PTX path, launch block, numerics per kernel)
import samplers   # noqa: E402

FAST_SWITCH = '#ifdef PX_FAST\nuint px_rtzero() { return 0u; }   // fast numerics: no rounding/sign barriers\n#else\n'
FMA32 = ['PX_FMA32_RELAXED', 'PX_FMA32_UNFUSED']
HALF_NB = ['PX_HALF_ADD_NO_BARRIER', 'PX_HALF_FMA_NO_BARRIER']
COMPACT = HALF_NB + ['PX_FMA32_RELAXED']
# k5f output ReLU: packed max (same finite values; NaN -> 0 in the CPU emulator)
OUTPUT_RELU = '''// Packed max has the same finite ReLU values; NaNs are mapped to zero.
uint output_relu(uint v) {
#ifdef __cplusplus
    uint l=v&0xffffu,h=v>>16;
    l=((l&0x7fffu)>0x7c00u)?0u:px_relu_h(l);
    h=((h&0x7fffu)>0x7c00u)?0u:px_relu_h(h);
    return l|(h<<16);
#else
    return px_max_f16x2(v,0u);
#endif
}
'''
# k7 fast numerics: each 8-product chain as 4 packed fp16 FMAs, added once to the fp32 chain value
FAM_FAST = '''#ifdef PX_FAST
// fast numerics: each 8-product chain as 4 packed fp16 FMAs, added once to the fp32 chain value
#define FAM_S0 float16_t2 fs = float16_t2(0, 0);
#define FAM_P(x, y) fs = mad(x, y, fs);
#define FAM_S1 d += (float)fs.x + (float)fs.y;
#else
#define FAM_S0
#define FAM_P(x, y) d = (px_h2lo(x) * px_h2lo(y) + d); d = (px_h2hi(x) * px_h2hi(y) + d);
#define FAM_S1
#endif
'''


def fam_fast(text):
    text = re.sub(r'^(\s*\{ float d = px_h2f\(acc\[\d+\] >> \d+u\);)$', r'\1 FAM_S0', text, flags=re.M)
    text = text.replace('d = (px_h2lo(x) * px_h2lo(y) + d); d = (px_h2hi(x) * px_h2hi(y) + d); }', 'FAM_P(x, y) }')
    text = re.sub(r'^(\s*)(acc\[\d+\] = \(acc\[\d+\] & 0xffff(?:0000)?u\) \| \(px_f2h\(d\) << \d+u\); \})$',
                  r'\1FAM_S1 \2', text, flags=re.M)
    return FAM_FAST + text


# name -> (generator, generator options, cfg flags prepended, extra rules)
RECIPES = {
    'auto_exposure': ('ptx', [], [], {}),
    'auto_exposure_copy': ('ptx', [], [], {}),
    'clear_buffer': ('ptx', [], [], {}),
    'copy_exposure': ('ptx', [], [], {}),
    'luma_convert': ('ptx', [], ['PX_FMA32_UNFUSED', 'PX_FMA32_RELAXED'], {}),
    'reduce_sum': ('ptx', [], [], {}),
    'u10': ('ptx', [], [], {}),
    **{n: ('ptx', ['--null', '296,336'], FMA32, {}) for n in (
        'k8_rel', 'k8_hdr_colvar_mvhi', 'k8_hdr_colvar_mvlo', 'k8_hdr_mvdiff_mvhi', 'k8_hdr_mvdiff_mvlo',
        'k8_ldr_colvar_mvhi', 'k8_ldr_colvar_mvlo', 'k8_ldr_mvdiff_mvhi', 'k8_ldr_mvdiff_mvlo')},
    'k4': ('family', ['--roll', '--half-unpack', '--lds-row8', '--no-sts4'], HALF_NB, {}),
    'k9': ('family', ['--roll', '--half-unpack', '--lds-row8'], HALF_NB, {}),
    'k10': ('family', ['--roll', '--half-unpack', '--lds-row8', '--opaque-loop'], HALF_NB, {'smem_words': 4096}),
    # k11, k7: split-K (tools/splitk_hlsl.py): extra K slices on small grids, the last slice sums the partials
    'k11': ('family', ['--roll', '--half-unpack', '--lds-row8'], HALF_NB, {'splitk': True}),
    'u6': ('family', ['--roll', '--half-unpack', '--lds-row8', '--round-half', '--precise-orig'], HALF_NB, {}),
    'k7': ('family', ['--roll', '--half-unpack', '--lds-row8', '--round-half', '--opaque-loop', '--math', 'orig',
                      '--pack-orig', '--rotate-orig'], HALF_NB, {'fam_fast': True, 'splitk': True}),
    # u9: activation-major family, rolled blocks (tools/u5_roll.py), fixed shape arguments folded to constants,
    # just-in-time B-row loads (tools/load_fence.py)
    'u9': ('family', ['--roll', '--half-unpack', '--lds-row8', '--round-half', '--opaque-loop', '--a-major'],
           HALF_NB + ['PX_FP32_ROUND_BARRIER'], {'roll': 'u9', 'fold': {384: 7, 72: 256, 76: 1, 48: 256, 60: 256, 88: 256}, 'load_fence': True}),
    # u5: compact 32 KiB activation LDS (tools/compact_u5.py), vector rows (tools/u5_rows.py), rolled blocks
    # (tools/u5_roll.py), weight rows read from the prepared tables; table/ = the same body with the plain .hlsl
    'u5': ('family', ['--roll', '--half-unpack', '--lds-row8', '--round-half', '--opaque-loop'],
           ['PX_HALF_FMA_NO_BARRIER', 'PX_HALF_ADD_NO_BARRIER'], {'u5': True}),
    'u8': ('family', ['--roll', '--half-unpack', '--lds-row8', '--round-half', '--opaque-loop', '--precise-orig'],
           HALF_NB, {}),
    # joint-fragment kernels (tools/compact_hlsl.py) + PX_FAST direct row reads (tools/fast_tiles.py)
    'k5': ('compact', [], COMPACT, {'fast_tiles': True}),
    'k5f': ('compact', [], COMPACT, {'fast_tiles': True, 'output_relu': True}),
    'k5n': ('compact', [], COMPACT, {'fast_tiles': True}),
    'u4': ('compact', [], COMPACT, {'fast_tiles': True}),
}


def generate(name, out):
    gen, opts, flags, rules = RECIPES[name]
    k = K[name]
    if gen == 'ptx':
        args = [sys.executable, str(HERE / 'ptx2hlsl.py'), k['ptx'], str(out), '--name', name,
                '--block', ','.join(map(str, k['block'])), '--two', k.get('two', '') or 'none',
                '--mma', k.get('installed', 'orig')] + opts
        if 'mma' in open(k['ptx']).read():   # row-based MMA path (as package.py)
            args.append('--fast')
        s = samplers.spec(name)
        if s:
            args += ['--samplers', s]
    else:
        args = [sys.executable, str(HERE / f'{gen}_hlsl.py'), name, str(out)] + opts
    subprocess.run(args, check=True, capture_output=True, text=True)
    body = out / f'{name}_body.h'
    if rules.get('fast_tiles'):
        import fast_tiles
        body.write_text(fast_tiles.transform(body.read_text()))
    if rules.get('u5'):
        for tool, extra in (('compact_u5.py', ['--kernel-dir']), ('u5_rows.py', []), ('u5_roll.py', [])):
            subprocess.run([sys.executable, str(HERE / tool)] + extra + [str(out)], check=True, capture_output=True,
                           text=True)
        t = body.read_text()
        for slot, rp, cp, sp in ((2, 56, 52, 100), (4, 280, 276, 324)):
            old = (f'    uint b = a - 0x8000u;\n    uint row = b >> 7;\n    uint col = ((b & 127u) >> 4) ^ (row & 7u);\n'
                   f'    if (row >= PX_PARAM32({rp}u) || col * 8u >= PX_PARAM32({cp}u)) return px_row0();\n'
                   f'    uint4 v = PX_GLD4({slot}, (row * PX_PARAM32({sp}u) + col * 8u) * 2u);\n')
            assert t.count(old) == 1, slot
            t = t.replace(old, f'    uint4 v = PX_GLD4({slot}, a - 0x8000u);\n')
        inc = '#include "u5_memory.h"\n'
        t = t.replace(inc, inc + '#ifndef __cplusplus\n#undef PX_STS4\n#define PX_STS4(a, v0, v1, v2, v3) do { if ((a) '
                      '< 0x8000u) SMR[(a) >> 4] = uint4(v0, v1, v2, v3); } while (false)\n#endif\n', 1)
        body.write_text(t)
    if rules.get('roll'):
        subprocess.run([sys.executable, str(HERE / 'u5_roll.py'), str(out), '--name', rules['roll']], check=True,
                       capture_output=True, text=True)
    if rules.get('fold'):
        t = body.read_text()
        for off, v in rules['fold'].items():
            t = t.replace(f'PX_PARAM32({off}u);', f'{v}u;')
        body.write_text(t)
    if rules.get('load_fence'):
        import load_fence
        body.write_text(load_fence.transform(body.read_text(), name))
    if rules.get('fam_fast'):
        body.write_text(fam_fast(body.read_text()))
    if rules.get('output_relu'):
        body.write_text(OUTPUT_RELU + body.read_text().replace('px_relu_f16x2(', 'output_relu('))
    cfg = out / f'{name}_cfg.h'
    text = cfg.read_text()
    if rules.get('smem_words'):
        import re
        text = re.sub(r'#define PX_SMEM_WORDS \d+', f'#define PX_SMEM_WORDS {rules["smem_words"]}', text)
    cfg.write_text(''.join(f'#define {f} 1\n' for f in flags) + text)
    h = out / f'{name}.hlsl'
    plain = h.read_text()
    lines = plain.split('\n')
    for i, l in enumerate(lines):
        if l.startswith('uint px_rtzero()'):
            lines[i] = FAST_SWITCH + l + '\n#endif'
            break
    h.write_text('\n'.join(lines))
    if rules.get('splitk'):
        import splitk_hlsl
        splitk_hlsl.shader(str(out), name)
    if rules.get('u5'):
        # u5_memory.h is HelixSR's own source (kernels/u5); table/ = the same kernel with the plain .hlsl
        mem = (HERE.parent / 'kernels/u5/u5_memory.h').read_text()
        (out / 'u5_memory.h').write_text(mem)
        t = out / 'table'
        t.mkdir(exist_ok=True)
        for f in ('u5_body.h', 'u5_cfg.h', 'u5_memory.h'):
            (t / f).write_text((out / f).read_text())
        (t / 'u5.hlsl').write_text(plain)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out', type=Path)
    ap.add_argument('--ref', type=Path)
    ap.add_argument('--only', default='')
    a = ap.parse_args()
    names = a.only.split(',') if a.only else list(RECIPES)
    bad = 0
    for n in names:
        d = a.out / n
        d.mkdir(parents=True, exist_ok=True)
        try:
            generate(n, d)
        except subprocess.CalledProcessError as e:
            print(f'{n:22} FAILED {e.stderr.strip().splitlines()[-1] if e.stderr else ""}')
            bad += 1
            continue
        if a.ref:
            res = []
            for suf in ('.hlsl', '_body.h', '_cfg.h'):
                same = (d / f'{n}{suf}').read_bytes() == (a.ref / n / f'{n}{suf}').read_bytes()
                bad += not same
                res.append(f'{suf}:{"same" if same else "DIFF"}')
            print(f'{n:22}', ' '.join(res))
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
