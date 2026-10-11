#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Port the native packed family segments into the shared HLSL/CPU body.

Uses the native trace's placement/lifetime proof and rolled k-block scheduling,
rather than retaining every original ldmatrix fragment in registers.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse
import importlib.util
import json
from pathlib import Path
import re
import sys

from kernels import K
import ptx2hlsl as PX

ap = argparse.ArgumentParser()
ap.add_argument('name')
ap.add_argument('out', type=Path)
ap.add_argument('--roll', action='store_true')
ap.add_argument('--pair-barrier', action='store_true', help='preserve packed partial sums before FP32 reduction')
ap.add_argument('--half-unpack', action='store_true', help='use DXIL half unpack for register rows')
ap.add_argument('--lds-row8', action='store_true', help='store LDS rows as four packed words')
ap.add_argument('--round-half', action='store_true', help='enforce FP16 instruction rounding boundaries')
ap.add_argument('--precise-orig', action='store_true', help='make original MMA sums precise (can affect upstream packed FMAs)')
ap.add_argument('--opaque-loop', action='store_true', help='keep short family loops rolled through RADV')
ap.add_argument('--wave', type=int, choices=(32, 64), default=32)
ap.add_argument('--math', choices=('pk', 'orig'), default='pk', help='orig preserves lane-rotated products and rounds every MMA')
ap.add_argument('--pack-orig', action='store_true', help='keep original MMA accumulators as packed fp16 words')
ap.add_argument('--rotate-orig', action='store_true', help='rotate each loaded row once instead of indexing each product')
ap.add_argument('--a-major', action='store_true', help='stream activation rows to reduce register pressure')
ap.add_argument('--no-sts4', action='store_true', help='keep four scalar LDS stores (as kernels generated before the vector-store merge)')
a = ap.parse_args()
perf = Path(__file__).resolve().parent
source = perf / ('family_u' if a.name.startswith('u') else 'family_k')
spec = importlib.util.spec_from_file_location('native_family_generator', source / 'gen_helper.py')
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
if a.a_major:
    generator_source = (source / 'gen_helper.py').read_text()
    assert generator_source.count('if len(adesc) < len(bdesc):') == 1
    generator_source = generator_source.replace('if len(adesc) < len(bdesc):', 'if False:')
    exec(compile(generator_source, str(source / 'gen_helper.py'), 'exec'), gen.__dict__)
if a.math == 'orig' and a.name != 'k7':
    ap.error('orig currently supports the all-two-round K7 family only')
hip, meta = gen.gen(a.name.upper(), 'pk' if a.math == 'pk' else 'f32', a.roll)
import os
tables_dir = Path(os.environ['HELIXSR_FAMILY_TABLES']) if os.environ.get('HELIXSR_FAMILY_TABLES') else source / 'tables'
table = json.loads((tables_dir / (a.name.upper() + '.json')).read_text())

prefix = '''// Native family row scheduling, shared by HLSL and the CPU emulator.
#ifdef __cplusplus
#define FAM_ACC(v, n) float* v
#define FAM_OUT(v, n) uint* v
#define FAM_UNROLL
#else
#define FAM_ACC(v, n) inout float v[n]
#define FAM_OUT(v, n) out uint v[n]
#define FAM_UNROLL [unroll]
#endif
#define FAM_API
typedef PxRow famu4;
typedef PXH2 famh2;
famu4 fam_row(uint a) { return px_row(a); }
famh2 fam_h2(famu4 v, uint i) { return px_rw(v, i); }
famh2 fam_w2(uint v) { return px_u2h2(v); }
uint fam_perm(uint v, uint l) { return px_rd(v, l); }
uint fam_quad(uint v, uint l) { return px_qrd(v, l); }
void fam_addmix(INOUT(float) d, famh2 p) { float r = d + px_h2lo(p); d = r + px_h2hi(p); }
'''
helper = hip[hip.index('// kernel '):]
helper = helper.replace('unsigned', 'uint')
helper = helper.replace('__builtin_amdgcn_mbcnt_lo(~0u, 0u)', 'px_lane()')
helper = helper.replace('__builtin_elementwise_fma', 'px_h2fma')
if a.math == 'orig':
    # All K7 sites use FP32 accumulation followed by a separate FP16 rounding.
    # The native MMA consumes k-pairs in the lane's rotated order.
    if a.rotate_orig:
        prefix = prefix.replace('return px_row(a);', 'return px_rot4(px_row(a));')
    else:
        helper = re.sub(r'fam_h2\(([^,]+), (\d+)u\)',
                        r'fam_h2(\1, (t + \2u) & 3u)', helper)
    helper = helper.replace('float(x[0])', 'px_h2lo(x)').replace('float(x[1])', 'px_h2hi(x)')
    helper = helper.replace('float(y[0])', 'px_h2lo(y)').replace('float(y[1])', 'px_h2hi(y)')
    helper = re.sub(r'__builtin_fmaf\((px_h2(?:lo|hi)\(x\)), (px_h2(?:lo|hi)\(y\)), d\)',
                    r'(\1 * \2 + d)', helper)
    helper = re.sub(r'(acc\[\d+\]) = d;', r'\1 = px_h2f(px_f2h(d));', helper)
    meta['mode'] = 'orig'
helper = helper.replace('famh2 p = {(_Float16)0.0f, (_Float16)0.0f};', 'famh2 p = px_h2z(px_u2h2(0u));')
helper = re.sub(r'asm volatile\("" : "\+v"\(d\)\); ', '', helper)
helper = helper.replace('  __builtin_amdgcn_sched_barrier(0);', '')
helper = re.sub(r'#pragma unroll\n  for \(int i = 0; i < \d+; \+\+i\) asm volatile\("" : "\+v"\(acc\[i\]\)\);', '', helper)
helper = helper.replace('#pragma unroll 1', 'PX_LOOP').replace('#pragma unroll', 'FAM_UNROLL')
helper = re.sub(r'famh2 v = \{\(_Float16\)acc\[c \* 4 \+ r \* 2\], \(_Float16\)acc\[c \* 4 \+ r \* 2 \+ 1\]\};\s*'
                r'out\[2 \* c \+ r\] = __builtin_bit_cast\(uint, v\);',
                'out[2 * c + r] = px_f2h(acc[c * 4 + r * 2]) | (px_f2h(acc[c * 4 + r * 2 + 1]) << 16);', helper)
for p, n in enumerate(meta['nacc']):
    helper = helper.replace(f'__hx_fam_zero{p}(float *acc)', f'family_zero{p}(FAM_ACC(acc, {n}))')
    helper = helper.replace(f'__hx_fam_final{p}(const float *acc, uint *out)',
                            f'family_final{p}(FAM_ACC(acc, {n}), FAM_OUT(out, {n // 2}))')
for seg in meta['segments']:
    i = seg['index']
    helper = helper.replace(f'__hx_fam_seg{i}(float *acc', f'family_seg{i}(FAM_ACC(acc, {meta["nacc"][seg["phase"]]})')
assert 'asm' not in helper and '_Float16' not in helper and '__builtin_' not in helper
helper = re.sub(r'\bout\b', 'result', helper)
if a.pack_orig:
    if a.math != 'orig': ap.error('--pack-orig requires --math orig')
    prefix = prefix.replace('float* v', 'uint* v').replace('inout float v[n]', 'inout uint v[n / 2]')
    for phase, count in enumerate(meta['nacc']):
        if not count: continue
        helper = helper.replace(f'i < {count};', f'i < {count // 2};')
        begin = helper.index(f'FAM_API void family_final{phase}(')
        end = helper.index('FAM_API void family_seg', begin)
        helper = helper[:begin] + f'''FAM_API void family_final{phase}(FAM_ACC(acc, {count}), FAM_OUT(result, {count // 2})) {{
FAM_UNROLL
    for (uint i = 0; i < {count // 2}u; ++i) result[i] = acc[i];
}}
''' + helper[end:]
    helper = re.sub(r'float d = acc\[(\d+)\];',
                    lambda m: f'float d = px_h2f(acc[{int(m[1]) // 2}] >> {(int(m[1]) & 1) * 16}u);', helper)
    def pack_acc(m):
        index = int(m[1]); pair = index // 2; shift = (index & 1) * 16
        mask = '0xffffu' if shift else '0xffff0000u'
        return f'acc[{pair}] = (acc[{pair}] & {mask}) | (px_f2h(d) << {shift}u);'
    helper = re.sub(r'acc\[(\d+)\] = px_h2f\(px_f2h\(d\)\);', pack_acc, helper)
if a.opaque_loop:
    helper = re.sub(r'q < (\d+u)', r'q < (\1 + px_rtzero())', helper)
if a.pair_barrier:
    prefix = prefix.replace('float r = d + px_h2lo(p);',
                            'p = px_u2h2(px_h22u(p) | px_rtzero()); float r = d + px_h2lo(p);')
if a.half_unpack:
    prefix = prefix.replace('famh2 fam_w2(uint v) { return px_u2h2(v); }', '''famh2 fam_w2(uint v) {
#ifdef __cplusplus
return px_u2h2(v);
#else
return float16_t2((float16_t)f16tof32(v), (float16_t)f16tof32(v >> 16));
#endif
}''')


class FamilyTx(PX.Tx):
    def __init__(self):
        k = K[a.name]
        super().__init__(k['ptx'], a.name, k['block'], mma=PX.parse_mma(k.get('installed', 'orig')),
                         two=PX.parse_two(k.get('two', ''), 99999), fast=False)
        self.covered = {s['site'] for s in table['sites']}
        # Covered chains are owned by the family helper, not the generic MMA
        # shadow accumulators. Uncovered MMA sites register their own chains.
        self.chain_regs = {}
        self.after = {}
        self.before = {}
        for kind, key in [('A', 'basesA'), ('B', 'basesB')]:
            for gi, base in enumerate(table[key]):
                x = self.ins[base['pc']]
                assert x['op'].startswith('ldmatrix')
                b, off = self.addr(x['ops'][1])
                value = f'({self.u32(b)} + {off}u)' if off else self.u32(b)
                self.after.setdefault(base['pc'], []).append(f'family_base{kind}{gi} = {value};')
        last = {seg['phase']: seg['index'] for seg in meta['segments']}
        for seg in meta['segments']:
            p = seg['phase']
            params = [f'family_acc{p}'] + [f'family_baseA{g}' for g in seg['basesA']] + \
                     [f'family_baseB{g}' for g in seg['basesB']] + [self.u32(r) for r in seg['aregs']]
            lines = [f'family_seg{seg["index"]}(' + ', '.join(params) + ');']
            if seg['kind'] == 'line':
                if last[p] == seg['index']:
                    lines += self.final(p)
                self.after.setdefault(seg['after_ldm_pc'], []).extend(lines)
            else:
                if seg.get('after_ldm_pc') is not None:
                    self.after.setdefault(seg['after_ldm_pc'], []).extend(lines)
                else:
                    self.before.setdefault(table['loop'][0], []).extend(lines)
                # The native loop's fallthrough is also its zero-iteration skip target.
                latch = table['loop'][1]
                assert self.ins[latch]['op'] == 'bra'
                self.before.setdefault(latch + 1, []).extend(self.final(p))

    def final(self, p):
        lines = [f'family_final{p}(family_acc{p}, family_out{p});']
        for ci, regs in enumerate(meta['chains'][str(p)]):
            for r, reg in enumerate(regs):
                lines.append(f'{self.vname(reg)} = family_out{p}[{2 * ci + r}];')
        return lines

    def tr(self, i, x):
        if x['op'].startswith('mma') and self.k.mma_sites.index(i) in self.covered:
            lines = []
        else:
            lines = super().tr(i, x)
        return self.before.get(i, []) + lines + self.after.get(i, [])

    def generate(self):
        declarations = []
        for p, n in enumerate(meta['nacc']):
            if n:
                acc_decl = f'uint family_acc{p}[{n // 2}];' if a.pack_orig else f'float family_acc{p}[{n}];'
                declarations += [acc_decl, f'uint family_out{p}[{n // 2}];',
                                 f'family_zero{p}(family_acc{p});']
        for kind, key in [('A', 'basesA'), ('B', 'basesB')]:
            declarations += [f'uint family_base{kind}{i} = 0u;' for i in range(len(table[key]))]
        return declarations + super().generate()


a.out.mkdir(parents=True, exist_ok=True)
tx = FamilyTx()
info = PX.write(tx, a.out, wave=a.wave)
cfg = a.out / (a.name + '_cfg.h')
defines = []
if a.lds_row8:
    defines += ['#define PX_LDS_ROW8 1', '#define PX_HALF_UNPACK 1']
if a.round_half:
    defines += ['#define PX_HALF_ROUND_BARRIER 1']
if a.precise_orig:
    defines += ['#define PX_ORIG_PRECISE 1']
cfg.write_text('\n'.join(defines) + '\n' + cfg.read_text())
body = a.out / (a.name + '_body.h')
body_text = body.read_text()
# PTX st.shared.v4.b32 guarantees 16-byte alignment. Preserve the vector
# store so DXC does not create a separate lane-dependent component switch.
if not a.no_sts4:
    body_text = re.sub(r'PX_STS32\(_a, ([^;]+)\);\s*PX_STS32\(_a \+ 4u, ([^;]+)\);\s*'
                       r'PX_STS32\(_a \+ 8u, ([^;]+)\);\s*PX_STS32\(_a \+ 12u, ([^;]+)\);',
                       r'PX_STS4(_a, \1, \2, \3, \4);', body_text)
body.write_text(prefix + helper + '\n' + body_text)
meta['hlsl_options'] = dict(roll=a.roll, pair_barrier=a.pair_barrier, half_unpack=a.half_unpack,
                            lds_row8=a.lds_row8, round_half=a.round_half, precise_orig=a.precise_orig,
                            opaque_loop=a.opaque_loop, wave=a.wave, math=a.math,
                            pack_orig=a.pack_orig, rotate_orig=a.rotate_orig, a_major=a.a_major)
(a.out / (a.name + '_family.json')).write_text(json.dumps(meta, indent=1) + '\n')
print(json.dumps(dict(kernel=a.name, roll=a.roll, nacc=meta['nacc'], segments=len(meta['segments']))))
