#!/usr/bin/env python3
"""PTX -> HLSL (and the same body as C++ for the CPU emulator) for the DLSS Model E kernels.

Design (see kernels/README.md):
- One structured function body, valid in both HLSL (with rt/px_hlsl.h) and C++ (with rt/px_cpp.h).
- Control flow: PTX's forward branches become per-block reach flags (if (rb_N) { ... }); natural loops (one backward
  branch at the end of a contiguous block range) become do { ... } while (lc).
- Registers: 32-bit regs (b32/f32/u32/s32) are uint, 16-bit regs are uint holding the low 16 bits, 64-bit regs are
  uint64_t, predicates are bool. Floats are reinterpreted with asfloat/asuint per instruction.
- Memory: kernel parameters come from the PX_PARAM32 cbuffer view of the CUDA argument block (pointer arguments hold
  arena byte offsets on the GPU, device addresses in the emulator); global memory is PX_GLD/PX_GST on the arena;
  shared memory is the SM[] word array; textures/surfaces are per-argument-slot resources.
- Warp collectives (ldmatrix, mma.sync, shfl.sync, vote.ballot) map to px_common.h helpers built on wave reads.
- mma numerics per site: 'orig' (the original kernels', with per-site direct/two rounding), or chain modes 'f32' / 'pk'.

Usage: ptx2hlsl.py <ptx> <out_dir> --name NAME --block X,Y,Z [--smem-dyn BYTES] [--mma orig|f32|pk]
       [--two all|none|A-B,C,...]"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import argparse, json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ptxsim as S   # parser only


def parse_regs(text):
    regs = {}
    for t, pfx, n in re.findall(r'\.reg\s+\.(\w+)\s+%(\w+)<(\d+)>\s*;', text):
        for i in range(int(n)):
            regs['%' + pfx + str(i)] = t
    for t, name in re.findall(r'\.reg\s+\.(\w+)\s+%(\w+)\s*;', text):
        regs['%' + name] = t
    return regs


def regclass(t):
    if t == 'pred':
        return 'pred'
    if t in ('b64', 'u64', 's64', 'f64'):
        return 64
    if t in ('b16', 'u16', 's16', 'f16'):
        return 16
    return 32


class Tx:
    def __init__(self, ptx, name, block, smem_dyn=0, mma=lambda s: 'orig', two=(), fast=False, null_params=()):
        self.text = open(ptx).read()
        self.k = S.Kernel(ptx)
        self.name = name
        self.block = block
        self.regs = parse_regs(self.text)
        # kernel parameters (CUDA ABI: each at a multiple of its alignment) and shared variables
        self.params = {}
        off = 0
        for al, ty, nm, n in re.findall(r'\.param\s+(?:\.align\s+(\d+)\s+)?\.(\w+)\s+(\w+)(?:\[(\d+)\])?', self.text):
            esz = max(1, int(re.sub(r'\D', '', ty) or 8) // 8)
            a = int(al) if al else esz
            off = (off + a - 1) // a * a
            self.params[nm] = off
            off += esz * (int(n) if n else 1)
        self.param_bytes = off
        self.shared = {}
        so = 0
        for al, ty, nm, n in re.findall(r'\.shared\s+(?:\.align\s+(\d+)\s+)?\.(\w+)\s+(\w+)(?:\[(\d+)\])?\s*;', self.text):
            esz = max(1, int(re.sub(r'\D', '', ty) or 8) // 8)
            a = max(4, int(al) if al else esz)
            so = (so + a - 1) // a * a
            self.shared[nm] = so
            so += esz * (int(n) if n else 1)
        self.smem = (so + 15) // 16 * 16 + smem_dyn
        self.mma_mode = mma
        self.two = set(two)
        self.ins = self.k.ins
        self.labels = self.k.labels
        self.defs = {}
        for i, x in enumerate(self.ins):
            for d in self.dests(x):
                self.defs.setdefault(d, []).append(i)
        self.tex_slots = {}    # param offset -> slot index
        self.surf_slots = {}
        self.surf_single = {}
        self.uses_ctaid = set()
        self.chains = {}
        self.chain_regs = {}
        self.out = []
        self.ptr_slots = {}     # param offset -> buffer slot
        self.ptr_written = set()
        self.prov = self.provenance()
        self.null_params = set(null_params)
        self.tex_level = {}     # texture slot -> sampled (needs a sampler) or only fetched
        self.samplers = {}      # param offset -> (filter, addressU, addressV) of NGX's CUDA texture object
        self.fast = fast
        self.rows = {}      # register -> {'A' | 'B': set of 'plain' / 'rot'} (fast MMA path)
        if fast:
            self.plan_rows()
        for site, i in enumerate(self.k.mma_sites):
            mode = self.mma_mode(site)
            if mode in ('f32', 'pk'):
                D = re.findall(r'%\w+', self.ins[i]['ops'][0])
                key = 'sh_' + '_'.join(r[1:] for r in D)
                for r in D:
                    self.chain_regs[r] = key

    def provenance(self):
        """register -> set of pointer-argument param offsets it is derived from (64-bit address arithmetic only)"""
        # pointer arguments: u64 params that reach a cvta.to.global (or are used directly as a global address)
        loaded = {}
        for x in self.ins:
            if x['op'] in ('ld.param.u64', 'ld.param.b64'):
                b, off = self.addr(x['ops'][1])
                loaded[x['ops'][0].strip()] = self.param_off(b, off)
        ptrs = set()
        for x in self.ins:
            op, o = x['op'], x['ops']
            if op.startswith('cvta.to.global') and o[1].strip() in loaded:
                ptrs.add(loaded[o[1].strip()])
            if op.startswith(('ld.global', 'st.global')):
                b, _ = self.addr(o[1] if op.startswith('ld') else o[0])
                if b.strip() in loaded:
                    ptrs.add(loaded[b.strip()])
        self.ptr_params = ptrs
        prov = {}
        changed = True
        while changed:
            changed = False
            for x in self.ins:
                op, o = x['op'], x['ops']
                new = None
                if op == 'ld.param.u64' or op == 'ld.param.b64':
                    b, off = self.addr(o[1])
                    po = self.param_off(b, off)
                    new = {po} if po in ptrs else None
                elif op.startswith(('mov.b64', 'mov.u64', 'cvta')) and o[1].strip().startswith('%'):
                    new = set(prov.get(o[1].strip(), ()))
                elif op.split('.')[0] in ('add', 'sub') and op.split('.')[-1] in ('s64', 'u64', 'b64'):
                    new = set(prov.get(o[1].strip(), ())) | set(prov.get(o[2].strip(), ()))
                if new:
                    d = o[0].strip()
                    if not new <= prov.get(d, set()):
                        prov[d] = prov.get(d, set()) | new
                        changed = True
        return prov

    def plan_rows(self):
        """MMA operands whose every definition is an ldmatrix get full rows read from LDS at the ldmatrix."""
        need = {}
        bad = set()
        for site, i in enumerate(self.k.mma_sites):
            D, A, B, C = (re.findall(r'%\w+', x) for x in self.ins[i]['ops'])
            kind = 'plain' if self.mma_mode(site) in ('f32', 'pk') else 'rot'
            for role, regs in (('A', A), ('B', B)):
                for r in regs:
                    need.setdefault(r, {}).setdefault(role, set()).add(kind)
        for r, roles in need.items():
            if len(roles) != 1 or not all(self.ins[d]['op'].startswith('ldmatrix') for d in self.defs.get(r, [])) \
                    or not self.defs.get(r):
                bad.add(r)
        self.rows = {r: v for r, v in need.items() if r not in bad}

    def rowvar(self, r, role, kind, o=0):
        n = r[1:]
        return {('A', 'plain'): 'ra_%s', ('A', 'rot'): 'qa_%s', ('B', 'plain'): 'rb%d_%%s' % o,
                ('B', 'rot'): 'qb%d_%%s' % o}[(role, kind)] % n

    def operand_rows(self, regs, role, kind, k16):
        """uint4 expressions: A -> [a00, a10, a01, a11] (row r, chunk c); B -> [b00, b10, b01, b11] (column o, chunk c)"""
        out = {}
        if role == 'A':
            for idx, r in enumerate(regs):
                rr, c = idx & 1, idx >> 1
                if r in self.rows:
                    e = self.rowvar(r, 'A', kind)
                else:
                    e = 'px_arow(%s)' % self.u32(r)
                    if kind == 'rot':
                        e = 'px_rot4(%s)' % e
                out[(rr, c)] = e
            return [out.get((0, 0)), out.get((1, 0)), out.get((0, 1), 'px_row0()'), out.get((1, 1), 'px_row0()')]
        for c, r in enumerate(regs):
            for o in range(2):
                if r in self.rows:
                    e = self.rowvar(r, 'B', kind, o)
                else:
                    e = 'px_bcol(%s, %du)' % (self.u32(r), o)
                    if kind == 'rot':
                        e = 'px_rot4(%s)' % e
                out[(o, c)] = e
        return [out.get((0, 0)), out.get((1, 0)), out.get((0, 1), 'px_row0()'), out.get((1, 1), 'px_row0()')]

    def gslot(self, base, write):
        ps = self.prov.get(base.strip())
        assert ps and len(ps) == 1, ('global access without a unique pointer argument', base, ps)
        off = next(iter(ps))
        sl = self.slot(self.ptr_slots, off)
        if write:
            self.ptr_written.add(sl)
        return sl

    # ---- helpers --------------------------------------------------------------------------------------------------
    @staticmethod
    def dests(x):
        op = x['op']
        if not x['ops'] or op.startswith(('st.', 'bra', 'bar', 'sust', 'ret', 'trap')):
            return []
        d = x['ops'][0]
        return re.findall(r'%\w+', d)

    def vname(self, r):
        return 'x_' + r[1:]

    def regtype(self, r):
        return self.regs.get(r)

    def special(self, s):
        sp = {'%tid.x': 'tid.x', '%tid.y': 'tid.y', '%tid.z': 'tid.z',
              '%ctaid.x': 'ctaid.x', '%ctaid.y': 'ctaid.y', '%ctaid.z': 'ctaid.z',
              '%ntid.x': '%du' % self.block[0], '%ntid.y': '%du' % self.block[1], '%ntid.z': '%du' % self.block[2],
              '%laneid': 'px_lane()'}
        if s in sp:
            return sp[s]
        if s.startswith('%nctaid'):
            return 'px_nctaid().' + s[-1]
        return None

    def u32(self, s):
        """operand as a uint expression"""
        s = s.strip()
        sp = self.special(s)
        if sp is not None:
            return sp
        if s.startswith('%'):
            rc = regclass(self.regtype(s))
            if rc == 64:
                return '((uint)%s)' % self.vname(s)
            if rc == 'pred':
                return '(%s ? 1u : 0u)' % self.vname(s)
            return self.vname(s)
        if re.match(r'^0[fF][0-9a-fA-F]{8}$', s):
            return '0x%sU' % s[2:].upper()
        if s in self.shared:
            return '%du' % self.shared[s]
        if s in self.params:
            return '%du' % self.params[s]
        if s == 'WARP_SZ':
            return '32u'
        v = int(s, 0)
        return '0x%xU' % (v & 0xffffffff)

    def u64(self, s):
        s = s.strip()
        if s.startswith('%') and regclass(self.regtype(s)) == 64:
            return self.vname(s)
        if s in self.params:
            return '((uint64_t)%d)' % self.params[s]
        if re.match(r'^-?(0[xX][0-9a-fA-F]+|\d+)$', s):
            return '((uint64_t)0x%xULL)' % (int(s, 0) & ((1 << 64) - 1))
        return '((uint64_t)%s)' % self.u32(s)

    def s64(self, s):
        return '((int64_t)%s)' % self.u64(s)

    def s32(self, s):
        s2 = s.strip()
        if re.match(r'^-?\d+$', s2):
            return '(%d)' % int(s2)
        return 'asint(%s)' % self.u32(s)

    def f32(self, s):
        s = s.strip()
        if re.match(r'^0[fF][0-9a-fA-F]{8}$', s):
            return 'asfloat(0x%sU)' % s[2:].upper()
        if re.match(r'^-?\d+(\.\d*)?$', s):
            return '(%sf)' % (s if '.' in s else s + '.0')
        return 'asfloat(%s)' % self.u32(s)

    def pred(self, s):
        s = s.strip()
        if s.startswith('!'):
            return '(!%s)' % self.pred(s[1:])
        if s.startswith('%'):
            return self.vname(s)
        return 'true' if int(s, 0) else 'false'

    def assign(self, d, expr, kind):
        """kind: 'u32' uint expression, 'f32' float expression, 'u64', 'pred', 'u16' (uint, masked)"""
        rc = regclass(self.regtype(d))
        v = self.vname(d)
        if rc == 'pred':
            return '%s = %s;' % (v, expr)
        if kind == 'f32':
            e = 'asuint(%s)' % expr
        else:
            e = expr
        if rc == 64:
            if kind in ('u64',):
                return '%s = %s;' % (v, e)
            return '%s = (uint64_t)(%s);' % (v, e)
        if rc == 16:
            return '%s = (%s) & 0xffffU;' % (v, e) if kind != 'u64' else '%s = ((uint)(%s)) & 0xffffU;' % (v, e)
        if kind == 'u64':
            return '%s = (uint)(%s);' % (v, e)
        return '%s = %s;' % (v, e)

    def addr(self, s):
        """[base+off] -> (base_operand, offset_int)"""
        m = re.match(r'^\[\s*([^\]+]+?)\s*(?:\+\s*(-?\w+))?\s*\]$', s.strip())
        assert m, s
        return m.group(1), int(m.group(2), 0) if m.group(2) else 0

    def param_off(self, reg_or_sym, off):
        """static offset into the param block for a param-space address (base reg or param symbol)."""
        if reg_or_sym in self.params:
            return self.params[reg_or_sym] + off
        return self.const_param_base(reg_or_sym) + off

    def const_param_base(self, r):
        ds = self.defs.get(r, [])
        assert len(ds) == 1, ('param base not SSA', r, ds)
        x = self.ins[ds[0]]
        op, o = x['op'], x['ops']
        if op.startswith('mov') and o[1].strip() in self.params:
            return self.params[o[1].strip()]
        if op.startswith('mov') and o[1].strip().startswith('%'):
            return self.const_param_base(o[1].strip())
        if op.startswith('add.s64') or op.startswith('add.u64'):
            a, b = o[1].strip(), o[2].strip()
            if re.match(r'^-?\d+$', b):
                return self.const_param_base(a) + int(b)
        if op.startswith('cvta'):
            return self.const_param_base(o[1].strip())
        raise AssertionError(('cannot resolve param base', r, x['text']))

    def handle_param(self, r):
        """param offset the texture/surface handle register r was loaded from"""
        ds = self.defs.get(r, [])
        assert len(ds) == 1, ('handle not SSA', r, ds)
        x = self.ins[ds[0]]
        if x['op'].startswith('mov') and x['ops'][1].strip().startswith('%'):
            return self.handle_param(x['ops'][1].strip())
        assert x['op'] == 'ld.param.u64', x['text']
        b, off = self.addr(x['ops'][1])
        return self.param_off(b, off)

    def slot(self, table, off):
        if off not in table:
            table[off] = len(table)
        return table[off]

    # ---- instruction translation ----------------------------------------------------------------------------------
    def tr(self, i, x):
        op, o = x['op'], x['ops']
        p = op.split('.')
        base = p[0]
        L = []
        if base in ('bra', 'ret'):
            return []
        if base == 'trap':
            return ['/* trap */']
        if base == 'bar':
            return ['PX_BARRIER();']
        if base == 'mov':
            return self.tr_mov(op, o)
        if base == 'cvta':
            return [self.assign(o[0], self.u64(o[1]), 'u64')]
        if base == 'ld':
            return self.tr_ld(op, o)
        if base == 'st':
            return self.tr_st(op, o)
        if base == 'setp':
            return [self.tr_setp(op, o)]
        if base == 'tex':
            return self.tr_tex(op, o)
        if base == 'sust':
            return self.tr_sust(op, o)
        if base == 'selp':
            t = p[1]
            if t == 'f32':
                return [self.assign(o[0], '(%s ? %s : %s)' % (self.pred(o[3]), self.u32(o[1]), self.u32(o[2])), 'u32')]
            if t in ('b64', 'u64', 's64'):
                return [self.assign(o[0], '(%s ? %s : %s)' % (self.pred(o[3]), self.u64(o[1]), self.u64(o[2])), 'u64')]
            return [self.assign(o[0], '(%s ? %s : %s)' % (self.pred(o[3]), self.u32(o[1]), self.u32(o[2])), 'u32')]
        if 'f16x2' in op.split('.') and base != 'cvt':
            return self.tr_f16x2(op, o)
        if op.split('.')[-1] == 'f16' and base in ('add', 'sub', 'mul', 'fma', 'max', 'min', 'abs', 'neg', 'ex2'):
            # scalar f16: the f16x2 helper on the low halves (each half is computed independently)
            return [self.assign(o[0], '(%s & 0xffffU)' % self.tr_f16x2_expr(op, o), 'u32')]
        if op.endswith('.f32') or '.f32.' in op + '.':
            r = self.tr_f32(op, o)
            if r is not None:
                return r
        if base == 'cvt':
            return [self.tr_cvt(op, o)]
        if base in ('add', 'sub', 'mul', 'mad', 'min', 'max', 'and', 'or', 'xor', 'not', 'shl', 'shr', 'neg', 'div',
                    'rem', 'popc', 'bfi', 'prmt', 'abs'):
            return self.tr_int(op, o)
        if base == 'movmatrix':
            assert op == 'movmatrix.sync.trans.aligned.m8n8.b16', op
            return [self.assign(o[0], 'px_movmatrix_t(%s)' % self.u32(o[1]), 'u32')]
        if base == 'mma':
            return self.tr_mma(i, op, o)
        if base == 'ldmatrix':
            regs = re.findall(r'%\w+', o[0])
            n = len(regs)
            tmp = ['_lm%d' % j for j in range(n)]
            a = self.addr(o[1])
            ad = '(%s + %du)' % (self.u32(a[0]), a[1]) if a[1] else self.u32(a[0])
            L = ['{ uint %s;' % ', '.join(tmp), 'px_ldmatrix_x%d(%s, %s);' % (n, ', '.join(tmp), ad)]
            L += [self.assign(r, t, 'u32') for r, t in zip(regs, tmp)]
            if any(r in self.rows for r in regs):
                L.append('uint _la = %s;' % ad)
                for j, r in enumerate(regs):
                    for role, kinds in self.rows.get(r, {}).items():
                        for kind in sorted(kinds):
                            fn = 'px_row' if kind == 'plain' else 'px_row_rot'
                            if role == 'A':
                                L.append('%s = %s(px_rd(_la, %du + (px_lane() >> 2)));' % (self.rowvar(r, 'A', kind), fn, 8 * j))
                            else:
                                for o in range(2):
                                    L.append('%s = %s(px_rd(_la, %du + ((px_lane() & 3u) << 1) + %du));'
                                             % (self.rowvar(r, 'B', kind, o), fn, 8 * j, o))
            L.append('}')
            return L
        if base == 'shfl':
            mode = p[2]
            d = o[0]
            dp = None
            if '|' in d:
                d, dp = d.split('|')
            fn = {'idx': 'px_shfl_idx', 'down': 'px_shfl_down', 'bfly': 'px_shfl_bfly'}[mode]
            L = ['{ bool _ok; uint _v = %s(%s, %s, %s, _ok);' % (fn, self.u32(o[1]), self.u32(o[2]), self.u32(o[3])),
                 self.assign(d, '_v', 'u32')]
            if dp:
                L.append(self.assign(dp, '_ok', 'pred'))
            L.append('}')
            return L
        if base == 'vote':
            assert op == 'vote.sync.ballot.b32', op
            return [self.assign(o[0], 'px_ballot(%s)' % self.pred(o[1]), 'u32')]
        if base == 'tex':
            return self.tr_tex(op, o)
        if base == 'sust':
            return self.tr_sust(op, o)
        raise NotImplementedError(x['text'])

    def tr_mov(self, op, o):
        d, s = o[0].strip(), o[1].strip()
        t = op.split('.')[1]
        if t == 'pred':
            return [self.assign(d, self.pred(s), 'pred')]
        if d.startswith('{'):                    # unpack
            regs = re.findall(r'%\w+', d)
            if len(regs) == 2 and regclass(self.regtype(s)) == 64:
                return [self.assign(regs[0], '(uint)(%s)' % self.u64(s), 'u32'),
                        self.assign(regs[1], '(uint)(%s >> 32)' % self.u64(s), 'u32')]
            if len(regs) == 2:                   # b32 -> two b16
                return [self.assign(regs[0], '(%s & 0xffffU)' % self.u32(s), 'u32'),
                        self.assign(regs[1], '(%s >> 16)' % self.u32(s), 'u32')]
            raise NotImplementedError(op + ' ' + str(o))
        if s.startswith('{'):                    # pack
            regs = re.findall(r'%\w+|\b\d+\b', s)
            if regclass(self.regtype(d)) == 64:
                return [self.assign(d, '((uint64_t)%s | ((uint64_t)%s << 32))' % (self.u32(regs[0]), self.u32(regs[1])), 'u64')]
            return [self.assign(d, '((%s & 0xffffU) | (%s << 16))' % (self.u32(regs[0]), self.u32(regs[1])), 'u32')]
        if regclass(self.regtype(d)) == 64:
            return [self.assign(d, self.u64(s), 'u64')]
        return [self.assign(d, self.u32(s), 'u32')]

    def tr_setp(self, op, o):
        p = op.split('.')
        cmp, t = p[1], p[-1]
        d = o[0]
        assert '|' not in d and len(o) == 3, op
        if t == 'f32':
            a, b = self.f32(o[1]), self.f32(o[2])
            e = {'lt': '(%s < %s)', 'le': '(%s <= %s)', 'gt': '(%s > %s)', 'ge': '(%s >= %s)', 'eq': '(%s == %s)',
                 'ne': '((%s < %s) || (%s > %s))',
                 'ltu': '(!(%s >= %s))', 'leu': '(!(%s > %s))', 'gtu': '(!(%s <= %s))', 'geu': '(!(%s < %s))',
                 'equ': '(!((%s < %s) || (%s > %s)))', 'neu': '(!(%s == %s))'}[cmp]
            args = (a, b, a, b) if e.count('%s') == 4 else (a, b)
            return self.assign(d, e % args, 'pred')
        if t in ('s32',):
            a, b = self.s32(o[1]), self.s32(o[2])
        elif t in ('u32', 'b32'):
            a, b = self.u32(o[1]), self.u32(o[2])
        elif t in ('s64',):
            a, b = self.s64(o[1]), self.s64(o[2])
        elif t in ('u64', 'b64'):
            a, b = self.u64(o[1]), self.u64(o[2])
        elif t in ('s16', 'u16', 'b16'):
            a, b = '(%s & 0xffffU)' % self.u32(o[1]), '(%s & 0xffffU)' % self.u32(o[2])
            if t == 's16' and cmp not in ('eq', 'ne'):
                a, b = '((int)(%s << 16) >> 16)' % self.u32(o[1]), '((int)(%s << 16) >> 16)' % self.u32(o[2])
        else:
            raise NotImplementedError(op)
        c = {'lt': '<', 'le': '<=', 'gt': '>', 'ge': '>=', 'eq': '==', 'ne': '!='}[cmp]
        return self.assign(d, '(%s %s %s)' % (a, c, b), 'pred')

    def tr_f32(self, op, o):
        p = op.split('.')
        base = p[0]
        f = self.f32
        d = o[0]
        if base == 'cvt':
            return None
        if base == 'add':
            if '.rz' in op:
                return [self.assign(d, 'px_add_rz(%s, %s)' % (f(o[1]), f(o[2])), 'f32')]
            return [self.assign(d, '(%s + %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'sub':
            return [self.assign(d, '(%s - %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'mul':
            return [self.assign(d, '(%s * %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'fma':
            return [self.assign(d, 'px_fma32(%s, %s, %s)' % (f(o[1]), f(o[2]), f(o[3])), 'f32')]
        if base == 'max':
            return [self.assign(d, 'px_fmax(%s, %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'min':
            return [self.assign(d, 'px_fmin(%s, %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'abs':
            return [self.assign(d, '(%s & 0x7fffffffU)' % self.u32(o[1]), 'u32')]
        if base == 'neg':
            return [self.assign(d, '(%s ^ 0x80000000U)' % self.u32(o[1]), 'u32')]
        if base == 'div':
            return [self.assign(d, 'px_div_approx(%s, %s)' % (f(o[1]), f(o[2])), 'f32')]
        if base == 'rcp':
            return [self.assign(d, 'px_rcp(%s)' % f(o[1]), 'f32')]
        if base == 'rsqrt':
            return [self.assign(d, 'px_rsqrt(%s)' % f(o[1]), 'f32')]
        if base == 'ex2':
            return [self.assign(d, 'px_ex2(%s)' % f(o[1]), 'f32')]
        if base == 'lg2':
            return [self.assign(d, 'px_lg2(%s)' % f(o[1]), 'f32')]
        if base == 'sqrt':
            return [self.assign(d, ('px_sqrt_rn(%s)' if '.rn' in op else 'px_sqrt(%s)') % f(o[1]), 'f32')]
        if base == 'ld' or base == 'st' or base == 'mov' or base == 'selp' or base == 'setp':
            return None
        raise NotImplementedError(op)

    def tr_cvt(self, op, o):
        d, s = o[0], o[1]
        if op == 'cvt.f32.f16':
            return self.assign(d, 'px_h2f(%s)' % self.u32(s), 'f32')
        if op == 'cvt.ftz.sat.f32.f32':
            return self.assign(d, 'px_sat(%s)' % self.f32(s), 'f32')
        if op == 'cvt.rmi.ftz.f32.f32':
            return self.assign(d, 'px_floor(%s)' % self.f32(s), 'f32')
        if op == 'cvt.rzi.f32.f32' or op == 'cvt.rzi.ftz.f32.f32':
            return self.assign(d, 'px_trunc(%s)' % self.f32(s), 'f32')
        if op == 'cvt.rn.f16x2.f32':
            return self.assign(d, '(px_f2h(%s) | (px_f2h(%s) << 16))' % (self.f32(o[2]), self.f32(o[1])), 'u32')
        if op == 'cvt.rn.f16.f32':
            return self.assign(d, 'px_f2h(%s)' % self.f32(s), 'u32')
        if op == 'cvt.rn.f16.s32':   # exact through f32 for |x| < 2^24 (DLSS converts small counts and 0)
            return self.assign(d, 'px_f2h((float)%s)' % self.s32(s), 'u32')
        if op == 'cvt.rn.f32.s32':
            return self.assign(d, '((float)%s)' % self.s32(s), 'f32')
        if op == 'cvt.rn.f32.u32':
            return self.assign(d, '((float)%s)' % self.u32(s), 'f32')
        if op == 'cvt.rzi.ftz.s32.f32':
            return self.assign(d, 'asuint(px_f2s32_rzi(%s))' % self.f32(s), 'u32')
        if op == 'cvt.rzi.ftz.u32.f32':
            return self.assign(d, 'px_f2u32_rzi(%s)' % self.f32(s), 'u32')
        if op == 'cvt.s64.s32':
            return self.assign(d, '((uint64_t)(int64_t)%s)' % self.s32(s), 'u64')
        if op == 'cvt.u64.u32':
            return self.assign(d, '((uint64_t)%s)' % self.u32(s), 'u64')
        if op in ('cvt.u16.u32', 'cvt.u32.u16'):
            return self.assign(d, '(%s & 0xffffU)' % self.u32(s), 'u32')
        if op == 'cvt.u32.u64':
            return self.assign(d, '((uint)%s)' % self.u64(s), 'u32')
        raise NotImplementedError(op)

    def tr_int(self, op, o):
        p = op.split('.')
        base = p[0]
        t = p[-1]
        d = o[0]
        if t == 'pred':
            ops = {'and': '&&', 'or': '||', 'xor': '!='}
            if base == 'not':
                return [self.assign(d, '(!%s)' % self.pred(o[1]), 'pred')]
            return [self.assign(d, '(%s %s %s)' % (self.pred(o[1]), ops[base], self.pred(o[2])), 'pred')]
        if t in ('s64', 'u64', 'b64'):
            a = self.u64(o[1])
            if base == 'add':
                return [self.assign(d, '(%s + %s)' % (a, self.u64(o[2])), 'u64')]
            if base == 'sub':
                return [self.assign(d, '(%s - %s)' % (a, self.u64(o[2])), 'u64')]
            if base == 'shl':
                return [self.assign(d, 'px_shl64(%s, %s)' % (a, self.u32(o[2])), 'u64')]
            if base == 'mul' and 'lo' in p:
                return [self.assign(d, '(%s * %s)' % (a, self.u64(o[2])), 'u64')]
            if base in ('and', 'or', 'xor'):
                return [self.assign(d, '(%s %s %s)' % (a, {'and': '&', 'or': '|', 'xor': '^'}[base], self.u64(o[2])), 'u64')]
            if base == 'shr' and t == 'u64':
                return [self.assign(d, 'px_shr64(%s, %s)' % (a, self.u32(o[2])), 'u64')]
            raise NotImplementedError(op)
        u, s = self.u32, self.s32
        if base == 'add':
            return [self.assign(d, '(%s + %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'sub':
            return [self.assign(d, '(%s - %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'neg':
            return [self.assign(d, '(0U - %s)' % u(o[1]), 'u32')]
        if base == 'mul':
            if 'wide' in p:
                if t == 's32':
                    return [self.assign(d, '((uint64_t)((int64_t)%s * (int64_t)%s))' % (s(o[1]), s(o[2])), 'u64')]
                return [self.assign(d, '((uint64_t)%s * (uint64_t)%s)' % (u(o[1]), u(o[2])), 'u64')]
            if 'hi' in p:
                if t == 's32':
                    return [self.assign(d, 'asuint(px_mulhi_s32(%s, %s))' % (s(o[1]), s(o[2])), 'u32')]
                return [self.assign(d, 'px_mulhi_u32(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
            return [self.assign(d, '(%s * %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'mad':
            assert 'lo' in p, op
            return [self.assign(d, '(%s * %s + %s)' % (u(o[1]), u(o[2]), u(o[3])), 'u32')]
        if base in ('min', 'max'):
            if t == 's32':
                return [self.assign(d, 'asuint(%s(%s, %s))' % (base, s(o[1]), s(o[2])), 'u32')]
            return [self.assign(d, '%s(%s, %s)' % (base, u(o[1]), u(o[2])), 'u32')]
        if base in ('and', 'or', 'xor'):
            c = {'and': '&', 'or': '|', 'xor': '^'}[base]
            e = '(%s %s %s)' % (u(o[1]), c, u(o[2]))
            if t in ('b16',):
                e = '(%s & 0xffffU)' % e
            return [self.assign(d, e, 'u32')]
        if base == 'not':
            e = '(~%s)' % u(o[1])
            if t == 'b16':
                e = '(%s & 0xffffU)' % e
            return [self.assign(d, e, 'u32')]
        if base == 'shl':
            return [self.assign(d, 'px_shl32(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'shr':
            if t == 's32':
                return [self.assign(d, 'px_sar32(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
            return [self.assign(d, 'px_shr32(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'div':
            if t == 'u16':
                return [self.assign(d, '((%s & 0xffffU) / (%s & 0xffffU))' % (u(o[1]), u(o[2])), 'u32')]
            if t == 'u32':
                return [self.assign(d, '(%s / %s)' % (u(o[1]), u(o[2])), 'u32')]
            if t == 's32':
                return [self.assign(d, 'asuint(%s / %s)' % (s(o[1]), s(o[2])), 'u32')]
        if base == 'rem':
            if t == 'u32':
                return [self.assign(d, '(%s %% %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'abs' and t == 's32':
            return [self.assign(d, 'asuint(abs(%s))' % s(o[1]), 'u32')]
        if base == 'popc':
            return [self.assign(d, 'countbits(%s)' % u(o[1]), 'u32')]
        if base == 'bfi':
            return [self.assign(d, 'px_bfi(%s, %s, %s, %s)' % (u(o[1]), u(o[2]), u(o[3]), u(o[4])), 'u32')]
        if base == 'prmt':
            assert op == 'prmt.b32', op
            return [self.assign(d, 'px_prmt(%s, %s, %s)' % (u(o[1]), u(o[2]), u(o[3])), 'u32')]
        raise NotImplementedError(op)

    def tr_f16x2_expr(self, op, o):
        p = op.split('.')
        base = p[0]
        u = self.u32
        if base == 'neg':
            return '(%s ^ 0x80008000U)' % u(o[1])
        if base == 'ex2':
            return 'px_ex2_f16x2(%s)' % u(o[1])
        if base == 'abs':
            return 'px_abs_f16x2(%s)' % u(o[1])
        if base == 'fma':
            e = 'px_fma_f16x2(%s, %s, %s)' % (u(o[1]), u(o[2]), u(o[3]))
            return 'px_relu_f16x2(%s)' % e if 'relu' in p else e
        assert base in ('add', 'sub', 'mul', 'max', 'min') and not ('ftz' in p or 'sat' in p or 'rz' in p), op
        return 'px_%s_f16x2(%s, %s)' % (base, u(o[1]), u(o[2]))

    def tr_f16x2(self, op, o):
        p = op.split('.')
        if p[0] in ('neg', 'ex2'):
            return [self.assign(o[0], self.tr_f16x2_expr(op, o), 'u32')]
        base = p[0]
        u = self.u32
        d = o[0]
        if base == 'add':
            return [self.assign(d, 'px_add_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'sub':
            return [self.assign(d, 'px_sub_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'mul':
            return [self.assign(d, 'px_mul_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'fma':
            e = 'px_fma_f16x2(%s, %s, %s)' % (u(o[1]), u(o[2]), u(o[3]))
            if 'relu' in p:
                e = 'px_relu_f16x2(%s)' % e
            return [self.assign(d, e, 'u32')]
        if base == 'max':
            return [self.assign(d, 'px_max_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'min':
            return [self.assign(d, 'px_min_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        if base == 'abs':
            return [self.assign(d, 'px_abs_f16x2(%s)' % u(o[1]), 'u32')]
        if base == 'set':
            assert op == 'set.equ.u32.f16x2', op
            return [self.assign(d, 'px_set_equ_f16x2(%s, %s)' % (u(o[1]), u(o[2])), 'u32')]
        raise NotImplementedError(op)

    def ldst_parts(self, op):
        # cache / memory-order qualifiers do not change a single thread's result
        p = [x for x in op.split('.') if x not in ('weak', 'ca', 'cg', 'cs', 'lu', 'cv', 'nc', 'relaxed', 'gpu', 'cta')]
        space = p[1]
        vec = 1
        rest = p[2:]
        if rest[0].startswith('v'):
            vec = int(rest[0][1:])
            rest = rest[1:]
        t = rest[-1]
        sz = int(re.sub(r'\D', '', t)) // 8
        return space, vec, t, sz

    def tr_ld(self, op, o):
        space, vec, t, sz = self.ldst_parts(op)
        regs = re.findall(r'%\w+', o[0]) if vec > 1 else [o[0].strip()]
        b, off = self.addr(o[1])
        L = []
        if space == 'param':
            po = self.param_off(b, off)
            for j, r in enumerate(regs):
                o_ = po + sz * j
                if sz == 8:
                    L.append(self.assign(r, 'PX_PARAM64(%du)' % o_, 'u64'))
                elif sz == 4:
                    L.append(self.assign(r, 'PX_PARAM32(%du)' % o_, 'u32'))
                else:
                    L.append(self.assign(r, '((PX_PARAM32(%du) >> %du) & 0x%xU)' % (o_ & ~3, (o_ & 3) * 8, (1 << (8 * sz)) - 1), 'u32'))
            return L
        if space == 'global':
            sl = self.gslot(b, False)
            a = '(%s + %d)' % (self.u64(b), off) if off else self.u64(b)
            L.append('{ uint64_t _a = %s;' % a)
            if sz == 4 and vec in (2, 4):
                L.append('uint%d _v = PX_GLD%d(%d, _a);' % (vec, vec, sl))
                for r, c in zip(regs, 'xyzw'):
                    L.append(self.assign(r, '_v.' + c, 'u32'))
            else:
                for j, r in enumerate(regs):
                    aj = '_a + %d' % (sz * j) if j else '_a'
                    fn = {4: 'PX_GLD32', 2: 'PX_GLD16', 1: 'PX_GLD8', 8: 'PX_GLD64'}[sz]
                    L.append(self.assign(r, '%s(%d, %s)' % (fn, sl, aj), 'u64' if sz == 8 else 'u32'))
            L.append('}')
            return L
        if space == 'shared':
            a = '(%s + %du)' % (self.u32(b), off & 0xffffffff) if off else self.u32(b)
            L.append('{ uint _a = %s;' % a)
            for j, r in enumerate(regs):
                aj = '_a + %du' % (sz * j) if j else '_a'
                if sz == 4:
                    L.append(self.assign(r, 'LDS32(%s)' % aj, 'u32'))
                elif sz == 2:
                    L.append(self.assign(r, 'PX_LDS16(%s)' % aj, 'u32'))
                elif sz == 1:
                    L.append(self.assign(r, 'PX_LDS8(%s)' % aj, 'u32'))
                else:
                    raise NotImplementedError(op)
            L.append('}')
            return L
        raise NotImplementedError(op)

    def tr_st(self, op, o):
        space, vec, t, sz = self.ldst_parts(op)
        b, off = self.addr(o[0])
        vals = re.findall(r'%\w+|\b0[fF][0-9a-fA-F]{8}\b|\b\d+\b', o[1]) if vec > 1 else [o[1].strip()]
        L = []
        if space == 'global':
            sl = self.gslot(b, True)
            a = '(%s + %d)' % (self.u64(b), off) if off else self.u64(b)
            L.append('{ uint64_t _a = %s;' % a)
            if sz == 4 and vec in (2, 4):
                L.append('PX_GST%d(%d, _a, uint%d(%s));' % (vec, sl, vec, ', '.join(self.u32(v) for v in vals)))
            else:
                for j, v in enumerate(vals):
                    aj = '_a + %d' % (sz * j) if j else '_a'
                    fn = {4: 'PX_GST32', 2: 'PX_GST16', 1: 'PX_GST8'}[sz]
                    L.append('%s(%d, %s, %s);' % (fn, sl, aj, self.u32(v)))
            L.append('}')
            return L
        if space == 'shared':
            a = '(%s + %du)' % (self.u32(b), off & 0xffffffff) if off else self.u32(b)
            L.append('{ uint _a = %s;' % a)
            for j, v in enumerate(vals):
                aj = '_a + %du' % (sz * j) if j else '_a'
                if sz == 4:
                    L.append('PX_STS32(%s, %s);' % (aj, self.u32(v)))
                elif sz == 2:
                    L.append('PX_STS16(%s, %s);' % (aj, self.u32(v)))
                elif sz == 1:
                    L.append('PX_STS8(%s, %s);' % (aj, self.u32(v)))
                else:
                    raise NotImplementedError(op)
            L.append('}')
            return L
        raise NotImplementedError(op)

    def tr_mma(self, i, op, o):
        site = self.k.mma_sites.index(i)
        D, A, B, C = (re.findall(r'%\w+', x) for x in o)
        k16 = 'k16' in op
        if not k16:
            A = A + A[:0]
        Ae = [self.u32(r) for r in A] + ['0u'] * (4 - len(A))
        Be = [self.u32(r) for r in B] + ['0u'] * (2 - len(B))
        Ce = [self.u32(r) for r in C]
        mode = self.mma_mode(site)
        L = ['{ uint _d0, _d1;']
        if self.fast:
            kind = 'plain' if mode in ('f32', 'pk') else 'rot'
            Ar = self.operand_rows(A, 'A', kind, k16)
            Br = self.operand_rows(B, 'B', kind, k16)
            rows = ', '.join(Ar + Br)
            if mode in ('f32', 'pk'):
                assert D == C, ('chain with D != C', site)
                key = 'sh_' + '_'.join(r[1:] for r in D)
                self.chains[key] = True
                L.append('if (!v%s) { %s = float4(px_lo(%s), px_hi(%s), px_lo(%s), px_hi(%s)); v%s = true; }'
                         % (key, key, Ce[0], Ce[0], Ce[1], Ce[1], key))
                L.append('px_mmar_chain(_d0, _d1, %s, %s, %du, %s);' % (rows, 'true' if k16 else 'false',
                                                                      {'f32': 1, 'pk': 2}[mode], key))
            elif mode == 'pk2':
                L.append('px_mmar_pk2(_d0, _d1, %s, %s, %s);' % (rows, ', '.join(Ce), 'true' if site in self.two else 'false'))
            else:
                L.append('px_mmar_orig(_d0, _d1, %s, %s, %s, %s);' % (rows, ', '.join(Ce), 'true' if k16 else 'false',
                                                                    'true' if site in self.two else 'false'))
            L.append(self.assign(D[0], '_d0', 'u32'))
            L.append(self.assign(D[1], '_d1', 'u32'))
            L.append('}')
            return L
        if mode == 'pk2':
            assert k16
            L.append('px_mma_pk2(_d0, _d1, %s, %s, %s, %s);' % (', '.join(Ae), ', '.join(Be), ', '.join(Ce),
                                                               'true' if site in self.two else 'false'))
        elif mode == 'orig':
            L.append('px_mma_orig(_d0, _d1, %s, %s, %s, %s, %s);' % (', '.join(Ae), ', '.join(Be), ', '.join(Ce),
                                                                    'true' if k16 else 'false',
                                                                    'true' if site in self.two else 'false'))
        else:
            assert D == C, ('chain with D != C', site)
            key = 'sh_' + '_'.join(r[1:] for r in D)
            self.chains[key] = True
            for r in D:
                self.chain_regs[r] = key
            L.append('if (!v%s) { %s = float4(px_lo(%s), px_hi(%s), px_lo(%s), px_hi(%s)); v%s = true; }'
                     % (key, key, Ce[0], Ce[0], Ce[1], Ce[1], key))
            L.append('px_mma_chain(_d0, _d1, %s, %s, %s, %du, %s);' % (', '.join(Ae), ', '.join(Be),
                                                                     'true' if k16 else 'false',
                                                                     {'f32': 1, 'pk': 2}[mode], key))
        L.append(self.assign(D[0], '_d0', 'u32'))
        L.append(self.assign(D[1], '_d1', 'u32'))
        L.append('}')
        return L

    def tr_tex(self, op, o):
        regs = re.findall(r'%\w+', o[0])
        m = re.match(r'^\[\s*(%\w+)\s*,\s*\{([^}]*)\}\s*\]$', o[1].strip())
        h, coords = m.group(1), [c.strip() for c in m.group(2).split(',')]
        hp = self.handle_param(h)
        regs_ = regs
        if hp in self.null_params:   # null texture object: reads 0 (CUDA texture object 0; a null descriptor)
            return [self.assign(r, '0.0f', 'f32') for r in regs_]
        sl = self.slot(self.tex_slots, hp)
        self.tex_level.setdefault(sl, False)
        if op == 'tex.level.2d.v4.f32.f32':
            self.tex_level[sl] = True
        L = ['{ float4 _t;']
        if op == 'tex.level.2d.v4.f32.f32':
            L.append('_t = PX_TEX_LEVEL(%d, %s, %s, %s);' % (sl, self.f32(coords[0]), self.f32(coords[1]), self.f32(o[2])))
        elif op == 'tex.base.2d.v4.f32.s32':
            L.append('_t = PX_TEX_FETCH(%d, %s, %s);' % (sl, self.s32(coords[0]), self.s32(coords[1])))
        else:
            raise NotImplementedError(op)
        for r, c in zip(regs, 'xyzw'):
            L.append(self.assign(r, '_t.' + c, 'f32'))
        L.append('}')
        return L

    def tr_sust(self, op, o):
        m = re.match(r'^\[\s*(%\w+)\s*,\s*\{([^}]*)\}\s*\]$', o[0].strip())
        h, coords = m.group(1), [c.strip() for c in m.group(2).split(',')]
        off = self.handle_param(h)
        sl = self.slot(self.surf_slots, off)
        vals = re.findall(r'%\w+|\b0[fF][0-9a-fA-F]{8}\b', o[1])
        if op == 'sust.p.2d.v4.b32.zero':
            self.surf_single.setdefault(sl, False)
            return ['PX_SURF_STORE4(%d, %s, %s, float4(%s));' % (sl, self.s32(coords[0]), self.s32(coords[1]),
                                                                 ', '.join(self.f32(v) for v in vals))]
        if op == 'sust.p.2d.b32.zero':
            self.surf_single[sl] = self.surf_single.get(sl, True)
            return ['PX_SURF_STORE1(%d, %s, %s, %s);' % (sl, self.s32(coords[0]), self.s32(coords[1]), self.f32(vals[0]))]
        raise NotImplementedError(op)

    # ---- control flow ----------------------------------------------------------------------------------------------
    def blocks(self):
        n = len(self.ins)
        starts = {0}
        for lab, at in self.labels.items():
            if at < n:
                starts.add(at)
        for i, x in enumerate(self.ins):
            if x['op'].startswith(('bra', 'ret')) and i + 1 < n:
                starts.add(i + 1)
        starts = sorted(starts)
        bl = []
        for j, s in enumerate(starts):
            e = starts[j + 1] if j + 1 < len(starts) else n
            bl.append((s, e))
        self.bstart = {s: k for k, (s, e) in enumerate(bl)}
        return bl

    def block_of_label(self, lab):
        return self.bstart[self.labels[lab]]

    def emit_body(self):
        bl = self.blocks()
        nb = len(bl)
        succ = {}
        loops = []
        for k, (s, e) in enumerate(bl):
            last = self.ins[e - 1]
            op = last['op']
            sc = []
            if op.startswith('bra'):
                tgt = self.block_of_label(last['ops'][0])
                if tgt <= k:
                    loops.append((tgt, k))
                sc.append(('br', tgt, last['pred']))
                if last['pred'] is not None and k + 1 < nb:
                    sc.append(('ft', k + 1, last['pred']))
            elif op.startswith('ret'):
                if last['pred'] is not None and k + 1 < nb:
                    sc.append(('ft', k + 1, last['pred']))
            elif k + 1 < nb:
                sc.append(('ft', k + 1, None))
            succ[k] = sc
        # validate loops: well nested, entered only at the header
        loops.sort(key=lambda l: (l[0], -l[1]))
        for h, t in loops:
            for k in range(nb):
                for kind, tgt, pr in succ[k]:
                    if h < tgt <= t and not (h <= k <= t):
                        raise AssertionError(('branch into loop body', k, tgt, h, t))
        self.loops = loops
        out = []
        out.append('bool ' + ', '.join('rb%d = %s' % (k, 'true' if k == 0 else 'false') for k in range(nb)) + ';')

        def cond_of(pr, kind):
            if pr is None:
                return None
            neg, pv = pr
            c = self.vname(pv)
            take = ('!' + c) if neg else c
            return take if kind == 'br' else ('(!%s)' % take)

        def emit_range(lo, hi, depth, loop_tail):
            k = lo
            ind = '    ' * depth
            while k <= hi:
                inner = [l for l in self.loops if l[0] == k and l != loop_tail and l[1] <= hi]
                if inner:
                    h, t = max(inner, key=lambda l: l[1])
                    out.append(ind + 'if (rb%d) {' % h)
                    out.append(ind + '    bool lc%d = true;' % h)
                    out.append(ind + '    PX_LOOP do {')
                    resets = ', '.join('rb%d = false' % j for j in range(h + 1, t + 1))
                    if resets:
                        out.append(ind + '        ' + ';'.join(('rb%d = false' % j) for j in range(h + 1, t + 1)) + ';')
                    out.append(ind + '        lc%d = false;' % h)
                    emit_range(h, t, depth + 2, (h, t))
                    out.append(ind + '    } while (lc%d);' % h)
                    out.append(ind + '}')
                    k = t + 1
                    continue
                s, e = bl[k]
                out.append(ind + 'if (rb%d) {' % k)
                body = []
                for i in range(s, e):
                    x = self.ins[i]
                    if x['op'].startswith(('bra', 'ret')):
                        continue
                    lines = self.tr(i, x)
                    if not x['op'].startswith('mma'):
                        inv = sorted({self.chain_regs[d] for d in self.dests(x) if d in self.chain_regs})
                        lines = lines + ['v%s = false;' % key for key in inv]
                    if x['pred'] is not None:
                        c = self.pred(('!' if x['pred'][0] else '') + x['pred'][1])
                        body.append('if (%s) {' % c)
                        body += ['    ' + l for l in lines]
                        body.append('}')
                    else:
                        body += lines
                for l in body:
                    out.append(ind + '    ' + l)
                for kind, tgt, pr in succ[k]:
                    c = cond_of(pr, kind)
                    if loop_tail is not None and tgt == loop_tail[0] and k == loop_tail[1] and kind == 'br':
                        stmt = 'lc%d = true;' % tgt
                    else:
                        stmt = 'rb%d = true;' % tgt
                    if c is None:
                        out.append(ind + '    ' + stmt)
                    else:
                        out.append(ind + '    if (%s) %s' % (c, stmt))
                out.append(ind + '}')
                k += 1

        emit_range(0, nb - 1, 0, None)
        return out

    def generate(self):
        body = self.emit_body()
        decl = {}
        for r, t in self.regs.items():
            rc = regclass(t)
            decl.setdefault(rc, []).append(self.vname(r))
        L = []
        for rc, names in decl.items():
            ty = {'pred': 'bool', 64: 'uint64_t', 32: 'uint', 16: 'uint'}[rc]
            init = 'false' if rc == 'pred' else '0'
            for j in range(0, len(names), 16):
                L.append('%s %s;' % (ty, ', '.join('%s = %s' % (n, init) for n in names[j:j + 16])))
        rv = []
        for r, roles in sorted(self.rows.items()):
            for role, kinds in roles.items():
                for kind in sorted(kinds):
                    rv += [self.rowvar(r, role, kind)] if role == 'A' else [self.rowvar(r, role, kind, o) for o in range(2)]
        for j in range(0, len(rv), 8):
            L.append('PxRow %s;' % ', '.join('%s = px_row0()' % v for v in rv[j:j + 8]))
        for key in self.chains:
            L.append('float4 %s = float4(0.0f, 0.0f, 0.0f, 0.0f);' % key)
            L.append('bool v%s = false;' % key)
        return L + body


def write(tx, outdir, wave=32):
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    lines = tx.generate()
    name = tx.name
    smw = max(1, (tx.smem + 3) // 4)
    gen = '// Generated by ptx2hlsl.py from NVIDIA PTX (%s). Do not edit.' % tx.k.name
    # bindings: SRV table = read-only buffers, then textures; UAV table = written buffers, then surfaces
    bufs = sorted(tx.ptr_slots.items(), key=lambda kv: kv[1])
    srv, uav = [], []
    for off, sl in bufs:
        (uav if sl in tx.ptr_written else srv).append(('buf', sl, off))
    for off, sl in sorted(tx.tex_slots.items(), key=lambda kv: kv[1]):
        srv.append(('tex', sl, off))
    for off, sl in sorted(tx.surf_slots.items(), key=lambda kv: kv[1]):
        uav.append(('surf', sl, off))
    hdr = [gen, '#define PX_SMEM_WORDS %d' % smw, '#define PX_PARAM_BYTES %d' % tx.param_bytes,
           '#define PX_BLOCK_X %d' % tx.block[0], '#define PX_BLOCK_Y %d' % tx.block[1], '#define PX_BLOCK_Z %d' % tx.block[2],
           '#define PX_NBUF %d' % len(bufs), '#define PX_NTEX %d' % len(tx.tex_slots), '#define PX_NSURF %d' % len(tx.surf_slots)]
    for off, sl in bufs:
        hdr.append('#define PX_BUF%d_PARAM %d' % (sl, off))
    for off, sl in sorted(tx.tex_slots.items(), key=lambda kv: kv[1]):
        hdr.append('#define PX_TEX%d_PARAM %d' % (sl, off))
    for off, sl in sorted(tx.surf_slots.items(), key=lambda kv: kv[1]):
        hdr.append('#define PX_SURF%d_PARAM %d' % (sl, off))
    hdr.append('#define PX_TEX_PARAMS {%s}' % ', '.join(str(off) for off, sl in sorted(tx.tex_slots.items(), key=lambda kv: kv[1])))
    hdr.append('#define PX_SURF_PARAMS {%s}' % ', '.join(str(off) for off, sl in sorted(tx.surf_slots.items(), key=lambda kv: kv[1])))
    hdr.append('#define PX_BUF_PARAMS {%s}' % ', '.join(str(off) for off, sl in bufs))
    (out / (name + '_cfg.h')).write_text('\n'.join(hdr) + '\n')
    body = [gen, 'void %s_body(uint3 tid, uint3 ctaid) {' % name] + ['    ' + l for l in lines] + ['}']
    (out / (name + '_body.h')).write_text('\n'.join(body) + '\n')
    # HLSL entry point
    nparam4 = max(1, (tx.param_bytes + 15) // 16)
    H = [gen, '// Bindings: b0 = CUDA argument block (pointer arguments hold (slot + 1) << 40 | byte offset) + grid size;',
         '// SRV table t0.. and UAV table u0.. in the order listed below.',
         '#include "%s_cfg.h"' % name,
         'cbuffer PxArgs : register(b0) { uint4 PXP[%d]; uint4 PXGRID; };' % nparam4,
         '#define PX_PARAM32(o) PXP[(o) >> 4][((o) >> 2) & 3]',
         '#define PX_PARAM64(o) ((uint64_t)PX_PARAM32(o) | ((uint64_t)PX_PARAM32((o) + 4) << 32))',
         'uint3 px_nctaid() { return PXGRID.xyz; }',
         'uint px_rtzero() { return PXGRID.w; }   // the host writes 0 (an opaque zero for the compiler)',
         '#include "px_hlsl.h"   // kernels/rt']
    for j, (kind, sl, off) in enumerate(srv):
        if kind == 'buf':
            H.append('ByteAddressBuffer PXR%d : register(t%d);   // param +%d' % (sl, j, off))
            H.append('#define PXBUF_%d PXR%d' % (sl, sl))
        else:
            H.append('Texture2D<float4> PXT%d : register(t%d);   // param +%d' % (sl, j, off))
            if tx.tex_level.get(sl):
                H.append('SamplerState PXS%d : register(s%d);' % (sl, sl))
    for j, (kind, sl, off) in enumerate(uav):
        if kind == 'buf':
            H.append('RWByteAddressBuffer PXW%d : register(u%d);   // param +%d' % (sl, j, off))
            H.append('#define PXBUF_%d PXW%d' % (sl, sl))
            H.append('void px_gst8_%d(uint a, uint v) { uint sh = (a & 3u) * 8u; PXW%d.InterlockedAnd(a & ~3u, ~(0xffu << sh)); '
                     'PXW%d.InterlockedOr(a & ~3u, (v & 0xffu) << sh); }' % (sl, sl, sl))
        else:
            H.append('RWTexture2D<%s> PXU%d : register(u%d);   // param +%d' % ('float' if tx.surf_single.get(sl) else 'float4', sl, j, off))
    H += ['#define PX_TEX_LEVEL(S, u, v, l) PXT##S.SampleLevel(PXS##S, float2(u, v), l)',
          '#define PX_TEX_FETCH(S, x, y) PXT##S.Load(int3(x, y, 0))',
          '#define PX_SURF_STORE4(S, x, y, v) PXU##S[int2(x, y)] = (v)',
          '#define PX_SURF_STORE1(S, x, y, v) PXU##S[int2(x, y)] = (v)',
          '#include "%s_body.h"' % name]
    rs = ['CBV(b0)']
    if srv:
        rs.append('DescriptorTable(SRV(t0, numDescriptors = %d))' % len(srv))
    if uav:
        rs.append('DescriptorTable(UAV(u0, numDescriptors = %d))' % len(uav))
    for off, sl in sorted(tx.tex_slots.items(), key=lambda kv: kv[1]):
        if not tx.tex_level.get(sl):
            continue
        assert off in tx.samplers, ('no sampler settings for sampled texture parameter', off)
        f, au, av = tx.samplers[off]
        am = {0: 'TEXTURE_ADDRESS_WRAP', 1: 'TEXTURE_ADDRESS_CLAMP', 2: 'TEXTURE_ADDRESS_MIRROR', 3: 'TEXTURE_ADDRESS_BORDER'}
        rs.append('StaticSampler(s%d, filter = %s, addressU = %s, addressV = %s, addressW = TEXTURE_ADDRESS_CLAMP)'
                  % (sl, 'FILTER_MIN_MAG_MIP_LINEAR' if f else 'FILTER_MIN_MAG_MIP_POINT', am[au], am[av]))
    H += ['[RootSignature("%s")]' % ', '.join(rs),
          '[WaveSize(%d)]' % wave, '[numthreads(%d, %d, %d)]' % tuple(tx.block),
          'void main(uint3 tid : SV_GroupThreadID, uint3 gid : SV_GroupID) { %s_body(tid, gid); }' % name]
    (out / (name + '.hlsl')).write_text('\n'.join(H) + '\n')
    meta = dict(kernel=tx.k.name, name=name, block=tx.block, smem=tx.smem, param_bytes=tx.param_bytes,
                buffers={str(off): dict(slot=sl, write=sl in tx.ptr_written) for off, sl in bufs},
                srv=[dict(kind=k, slot=sl, param=off) for k, sl, off in srv],
                uav=[dict(kind=k, slot=sl, param=off) for k, sl, off in uav],
                surf_single={str(k): v for k, v in tx.surf_single.items()}, loops=tx.loops, mma_mode=[tx.mma_mode(i) for i in range(len(tx.k.mma_sites))],
                two=sorted(tx.two), mma_sites=len(tx.k.mma_sites))
    (out / (name + '.json')).write_text(json.dumps(meta, indent=1) + '\n')
    return meta


def parse_mma(spec):
    """'pk' | 'orig' | 'pk2' | '0-63:pk,64-127:orig' -> site -> mode"""
    if ':' not in spec:
        return lambda site: spec
    rng = []
    for part in spec.split(','):
        r, m = part.split(':')
        a, _, b = r.partition('-')
        rng.append((int(a), int(b or a), m))

    def f(site):
        for a, b, m in rng:
            if a <= site <= b:
                return m
        return 'orig'
    return f


def parse_two(s, nsites):
    if s in ('all',):
        return set(range(nsites))
    if not s or s == 'none':
        return set()
    r = set()
    for part in s.split(','):
        if '-' in part:
            a, b = part.split('-')
            r |= set(range(int(a), int(b) + 1))
        else:
            r.add(int(part))
    return r


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('ptx')
    ap.add_argument('out')
    ap.add_argument('--name', required=True)
    ap.add_argument('--block', required=True)
    ap.add_argument('--smem-dyn', type=int, default=0)
    ap.add_argument('--mma', default='orig')
    ap.add_argument('--two', default='')
    ap.add_argument('--fast', action='store_true', help='row-based MMA path (rows from LDS at ldmatrix)')
    ap.add_argument('--null', default='', help='texture parameters that are always null (read 0)')
    ap.add_argument('--wave', type=int, default=32)
    ap.add_argument('--samplers', default='', help='param:filter:addrU:addrV,... (CUDA filter/address modes)')
    a = ap.parse_args()
    k = S.Kernel(a.ptx)
    tx = Tx(a.ptx, a.name, tuple(int(x) for x in a.block.split(',')), a.smem_dyn, parse_mma(a.mma),
            parse_two(a.two, len(k.mma_sites)), a.fast, [int(x) for x in a.null.split(',') if x])
    for sp in [x for x in a.samplers.split(',') if x]:
        o_, f_, u_, v_ = (int(y) for y in sp.split(':'))
        tx.samplers[o_] = (f_, u_, v_)
    m = write(tx, a.out, a.wave)
    print(json.dumps(m))
