#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""Split-K for the family kernels whose cost is one serial K loop over a small grid (k7, k11).

  splitk_hlsl.py shader KERNEL_DIR NAME   edits <NAME>.hlsl and <NAME>_body.h (after family_hlsl.py; regen rule 'splitk')
  splitk_hlsl.py host KERNEL_DIR NAME     edits <NAME>.host.cpp (once, in the source tree)

The host launches F slices per output tile (grid z x F; F in the constant word after the grid). Slice s runs iterations
[s*I, (s+1)*I) of the K loop (I = total/F): the loop count parameter becomes I - 1 and every pointer the loop advances
starts s*I strides further. Before the epilogue every slice stores its accumulators to a kernel-private scratch buffer
and counts itself in; the last slice to arrive sums all F partials in fp32 in slice order (the result does not depend on
arrival order), resets the tile counter and runs the epilogue; the others end. Nothing waits on another workgroup.
F = 1 is the original kernel (the same arithmetic, no scratch traffic). fp32 accumulators (k11) give the same output as
unsplit in our tests; packed fp16 accumulators (k7) are summed in fp32 and rounded once (differences of a few fp16 ulp)."""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import re, sys

# name -> (loop count parameter, [(pointer parameter, per-iteration stride parameter), ...])
SPECS = {
    'k7': (384, [(0, 104), (8, 104), (16, 112)]),
    'k11': (368, [(0, 88), (8, 96)]),
}
MAX_CTAS = 256   # split launches have at most this many workgroups (scratch size)


def layout(body, hl):
    m = re.search(r'\n    (uint|float) family_acc0\[(\d+)\];', body)
    assert m, 'family accumulator declaration'
    acc, threads = int(m.group(2)), int(re.search(r'\[numthreads\((\d+), 1, 1\)\]', hl).group(1))
    assert acc % 4 == 0
    cnt = MAX_CTAS * acc * threads * 4      # tile counters after the partials
    return m.group(1) == 'float', acc, threads, cnt, cnt + MAX_CTAS * 4


def shader(kdir, name):
    loop, ptrs = SPECS[name]
    hp, bp = '%s/%s.hlsl' % (kdir, name), '%s/%s_body.h' % (kdir, name)
    hl, body = open(hp).read(), open(bp).read()
    assert 'SKBUF' not in hl, 'already split'
    flt, acc, threads, cnt, _ = layout(body, hl)
    hl, n = re.subn(r'cbuffer PxArgs : register\(b0\) \{ uint4 PXP\[(\d+)\]; uint4 PXGRID; \};',
                    r'cbuffer PxArgs : register(b0) { uint4 PXP[\1]; uint4 PXGRID; uint4 PXSK; };', hl, count=1)
    assert n == 1
    uavs = len(re.findall(r'RWByteAddressBuffer PXW\d+ : register\(u\d+\);', hl))
    inc = '#include "%s_body.h"' % name
    assert hl.count(inc) == 1
    hl = hl.replace(inc, 'globallycoherent RWByteAddressBuffer SKBUF : register(u%d);   // split-K partials + tile counters\n'
                    % uavs + inc)
    hl, n = re.subn(r'DescriptorTable\(UAV\(u0, numDescriptors = (\d+)\)\)',
                    lambda m: 'DescriptorTable(UAV(u0, numDescriptors = %d))' % (int(m.group(1)) + 1), hl, count=1)
    assert n == 1

    if flt:   # fp32 accumulators
        sums = '    float sum[%(acc)d];\n    [unroll] for (uint i = 0; i < %(acc)du; ++i) sum[i] = 0.0f;'
        add = 'sum[4 * j + c] += asfloat(v[j][c]);'
        fin = 'acc[i] = sum[i];'
        pack = 'asuint(acc[4 * j]), asuint(acc[4 * j + 1]), asuint(acc[4 * j + 2]), asuint(acc[4 * j + 3])'
    else:     # packed fp16 pairs: halves summed in fp32, rounded once
        sums = ('    float lo[%(acc)d], hi[%(acc)d];\n'
                '    [unroll] for (uint i = 0; i < %(acc)du; ++i) { lo[i] = 0.0f; hi[i] = 0.0f; }')
        add = 'lo[4 * j + c] += f16tof32(v[j][c]); hi[4 * j + c] += f16tof32(v[j][c] >> 16);'
        fin = 'acc[i] = f32tof16(lo[i]) | (f32tof16(hi[i]) << 16);'
        pack = 'acc[4 * j], acc[4 * j + 1], acc[4 * j + 2], acc[4 * j + 3]'
    helper = ('''// split-K (tools/splitk_hlsl.py): F slices of the K loop per tile; the last slice to finish sums the partials
#ifdef __cplusplus
// CPU emulator: unsplit
#define SK_SLICES 1u
template <typename T> bool sk_reduce(T, uint, uint3, uint, uint) { return true; }
#else
#define SK_SLICES max(PXSK.x, 1u)
groupshared uint sk_flag;
bool sk_reduce(inout %(ty)s acc[%(acc)d], uint t, uint3 cta, uint F, uint s)
{
    if (F <= 1u) return true;
    const uint tile = (cta.z * PXGRID.y + cta.y) * PXGRID.x + cta.x;
    const uint me = tile * F + s;
    [unroll] for (uint j = 0; j < %(acc4)du; ++j)
        SKBUF.Store4(((me * %(acc4)du + j) * %(thr)du + t) * 16u, uint4(%(pack)s));
    DeviceMemoryBarrierWithGroupSync();
    if (t == 0u) { uint old; SKBUF.InterlockedAdd(%(cnt)du + tile * 4u, 1u, old); sk_flag = old; }
    GroupMemoryBarrierWithGroupSync();
    if (sk_flag != F - 1u) return false;
    DeviceMemoryBarrier();
''' + sums + '''
    [loop] for (uint o = 0; o < F; ++o)
    {
        const uint src = tile * F + o;
        uint4 v[%(acc4)d];
        [unroll] for (uint j = 0; j < %(acc4)du; ++j) v[j] = SKBUF.Load4(((src * %(acc4)du + j) * %(thr)du + t) * 16u);
        [unroll] for (uint j = 0; j < %(acc4)du; ++j)
            [unroll] for (uint c = 0; c < 4u; ++c) { %(add)s }
    }
    [unroll] for (uint i = 0; i < %(acc)du; ++i) %(fin)s
    if (t == 0u) SKBUF.Store(%(cnt)du + tile * 4u, 0u);
    return true;
}
#endif
''') % dict(ty='float' if flt else 'uint', acc=acc, acc4=acc // 4, thr=threads, cnt=cnt, pack=pack, add=add, fin=fin)
    sig = 'void %s_body(uint3 tid, uint3 ctaid) {' % name
    lp = 'PX_PARAM32(%du)' % loop
    fin0 = 'family_final0(family_acc0, family_out0);'
    assert body.count(sig) == 1 and body.count(lp) == 1 and body.count(fin0) == 1
    body = body.replace(lp, '(sk_iters - 1u)')
    for p, _ in ptrs:
        k = '= PX_PARAM64(%du);' % p
        assert body.count(k) == 1, k
        body = body.replace(k, '= PX_PARAM64(%du) + sk_off%d;' % (p, p))
    body = body.replace(sig, helper + sig + '''
    const uint sk_F = SK_SLICES;
    const uint sk_s = ctaid.z %% sk_F;
    ctaid.z /= sk_F;
    const uint sk_iters = (%s + 1u) / sk_F;
%s''' % (lp, ''.join('    const uint64_t sk_off%d = (uint64_t)(sk_s * sk_iters) * PX_PARAM64(%du);\n' % (p, st)
                     for p, st in ptrs)), 1)
    body = body.replace(fin0, 'if (!sk_reduce(family_acc0, tid.x, ctaid, sk_F, sk_s)) return;\n        ' + fin0)
    open(hp, 'w').write(hl)
    open(bp, 'w').write(body)


HOST_SPLIT = '''// Split-K (tools/splitk_hlsl.py): slices per output tile, F dividing the iteration count. Measured on the BC-250 (2000 MHz):
// 4 slices pay while the split grid stays within 72 workgroups, 2 slices up to %(max)d; larger grids are not latency bound.
// Off (F = 1) when the shaders do not support it (bch::split_k()). HELIXSR_SPLITK=n (tests): the largest F <= n (<= 8)
// that divides the iterations and keeps the grid within %(max)d workgroups.
uint32_t %(n)s_split(const bch::LaunchInfo& L)
{
    if (!bch::split_k() || (int32_t)L.word(%(lp)d) < 0)
        return 1;
    const uint32_t iters = L.word(%(lp)d) + 1, tiles = L.grid[0] * L.grid[1] * L.grid[2];
    if (const char* e = getenv("HELIXSR_SPLITK"))
    {
        for (uint32_t f = (uint32_t)atoi(e); f > 1; --f)
            if (f <= 8 && iters %% f == 0 && tiles * f <= %(max)d)
                return f;
        return 1;
    }
    if (iters %% 4 == 0 && tiles * 4 <= 72)
        return 4;
    if (iters %% 2 == 0 && tiles * 2 <= %(max)d)
        return 2;
    return 1;
}

void %(n)s_dims(const bch::LaunchInfo& L, uint32_t dims[3])
{
    dims[0] = L.grid[0], dims[1] = L.grid[1], dims[2] = L.grid[2] * %(n)s_split(L);
}

'''


def host(kdir, name, hl, body):
    loop, _ = SPECS[name]
    _, _, _, _, scratch = layout(body, hl)
    p = '%s/%s.host.cpp' % (kdir, name)
    t = open(p).read()
    assert '_split(' not in t, 'already split'
    fn = re.search(r'uint32_t %s_constants\(.*?\n\}\n' % name, t, re.S).group(0)
    grid_at = int(re.search(r'memcpy\(out \+ (\d+), g, 16\);', fn).group(1))
    fn2 = re.sub(r'const uint32_t size = \((\d+) \+ 255\) & ~255u;',
                 lambda m: 'const uint32_t size = (%d + 255) & ~255u;' % (int(m.group(1)) + 16), fn)
    fn2 = fn2.replace('    return size;\n}', '    const uint32_t f = %s_split(L);   // split-K slices\n'
                      '    memcpy(out + %d, &f, 4);\n    return size;\n}' % (name, grid_at + 16))
    t = t.replace(fn, HOST_SPLIT % dict(n=name, lp=loop, max=MAX_CTAS) + fn2)
    t = t.replace('#include "kernel_registry.h"', '#include <cstdlib>\n#include "kernel_registry.h"', 1)
    last = re.findall(r'    \{(\d+), bch::View::TableUAVRaw, bch::Src::Arg, \d+\},\n', t)
    lines = re.findall(r'    \{\d+, bch::View::TableUAVRaw, bch::Src::Arg, \d+\},\n', t)
    t = t.replace(lines[-1], lines[-1] + '    {%s, bch::View::TableUAVRaw, bch::Src::Scratch, 0, 0, %d},   // split-K\n'
                  % (last[-1], scratch), 1)
    t, n = re.subn(r'(%s_constants, )nullptr,' % name, r'\1%s_dims,' % name, t)
    assert n == 1
    open(p, 'w').write(t)


if __name__ == '__main__':
    mode, kdir, name = sys.argv[1:4]
    if mode == 'shader':
        shader(kdir, name)
    elif mode == 'host':
        host(kdir, name, open('%s/%s.hlsl' % (kdir, name)).read(), open('%s/%s_body.h' % (kdir, name)).read())
    else:
        raise SystemExit(__doc__)
