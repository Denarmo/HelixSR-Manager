// HLSL target primitives for px_common.h (DXC: -T cs_6_6 -enable-16bit-types -HV 2021 -denorm ftz).
#ifndef PX_HLSL_H
#define PX_HLSL_H
#define INOUT(T) inout T
#define OUTP(T) out T
#ifdef PX_FAST
#define PRECISE
#else
#define PRECISE precise
#endif
#define PX_LOOP [loop]

#ifndef PX_SMEM_WORDS
#define PX_SMEM_WORDS 1
#endif
// Shared memory is typed as fp16 pairs so that rows read from it stay 2 x 16-bit vectors through DXIL -> SPIR-V -> NIR,
// which is what lets RADV form packed v_pk_fma_f16 (32-bit words read through integer casts do not vectorize).
#ifdef PX_LDS_ROW8
groupshared uint4 SMR[(PX_SMEM_WORDS + 3) / 4];
#elif defined(PX_LDS_ROW4)
groupshared float16_t4 SM4[(PX_SMEM_WORDS + 1) / 2];
#else
groupshared float16_t2 SM[PX_SMEM_WORDS];
#endif
typedef float16_t2 PXH2;
#ifdef PX_HALF_UNPACK
float16_t2 px_v2h(uint w) { return float16_t2((float16_t)f16tof32(w), (float16_t)f16tof32(w >> 16)); }
#else
float16_t2 px_v2h(uint w) { return asfloat16(uint16_t2((uint16_t)(w & 0xffffu), (uint16_t)(w >> 16))); }
#endif
uint px_h2v(float16_t2 v) { return (uint)asuint16(v.x) | ((uint)asuint16(v.y) << 16); }
#ifdef PX_LDS_ROW8
#define LDS32(a) SMR[(a) >> 4][((a) >> 2) & 3u]
void px_sts_word(uint a, uint v) {
    switch ((a >> 2) & 3u) {
    case 0u: SMR[a >> 4].x = v; break;
    case 1u: SMR[a >> 4].y = v; break;
    case 2u: SMR[a >> 4].z = v; break;
    default: SMR[a >> 4].w = v; break;
    }
}
#define PX_STS32(a, v) px_sts_word(a, v)
#define PX_LDSH2(a) px_v2h(LDS32(a))
#elif defined(PX_LDS_ROW4)
PXH2 px_lds_pair(uint a) { float16_t4 v = SM4[a >> 3]; return (a & 4u) ? v.zw : v.xy; }
void px_sts_pair(uint a, uint v) {
    if (a & 4u) SM4[a >> 3].zw = px_v2h(v);
    else SM4[a >> 3].xy = px_v2h(v);
}
#define LDS32(a) px_h2v(px_lds_pair(a))
#define PX_STS32(a, v) px_sts_pair(a, v)
#define PX_LDSH2(a) px_lds_pair(a)
#else
#define LDS32(a) px_h2v(SM[(a) >> 2])
#define PX_STS32(a, v) SM[(a) >> 2] = px_v2h(v)
#define PX_LDSH2(a) SM[(a) >> 2]
#endif

uint px_lane() { return WaveGetLaneIndex() & 31u; }
#if defined(PX_LDS_SHUFFLE) && (PX_SMEM_WORDS * 4 + PX_BLOCK_X * PX_BLOCK_Y * PX_BLOCK_Z * 4 <= 32768)
// wave64 builds: these reads stay inside one 32-lane warp (px_rd) or quad (px_qrd), which the compiler cannot prove for
// WaveReadLaneAt in a 64-lane wave (it emits a slow cross-half sequence). They go through a per-thread LDS slot instead:
// a wave's LDS operations execute in order, so each read sees the value its lane just wrote. Same results.
groupshared uint PX_SHF[PX_BLOCK_X * PX_BLOCK_Y * PX_BLOCK_Z];
static uint px_gi;
uint px_rd(uint v, uint l) { PX_SHF[px_gi] = v; return PX_SHF[(px_gi & ~31u) | l]; }
uint px_qrd(uint v, uint l) { PX_SHF[px_gi] = v; return PX_SHF[(px_gi & ~3u) | l]; }
#define PX_SET_GI(t) px_gi = (t)
#else
uint px_rd(uint v, uint l) { return WaveReadLaneAt(v, (WaveGetLaneIndex() & ~31u) | l); }
uint px_qrd(uint v, uint l) { return QuadReadLaneAt(v, l); }
#define PX_SET_GI(t)
#endif

float px_h2f(uint h) { return (float)asfloat16((uint16_t)(h & 0xffffu)); }
// fp32 -> fp16, round to nearest even. The OR with the host's runtime zero stops ACO from merging a preceding fp32
// add/FMA and this conversion into one rounding (v_fma_mix_lo), which it does even for precise code.
uint px_f2h(float f) { return (uint)asuint16((float16_t)asfloat(asuint(f) | px_rtzero())); }
uint px_fma16(uint a, uint b, uint c) {
    return (uint)asuint16(mad(asfloat16((uint16_t)a), asfloat16((uint16_t)b), asfloat16((uint16_t)c)));
}
uint px_half_boundary(uint w) {
#ifdef PX_HALF_ROUND_BARRIER
    return w | px_rtzero();
#else
    return w;
#endif
}
uint px_half_add_boundary(uint w) {
#ifdef PX_HALF_ADD_NO_BARRIER
    return w;
#else
    return px_half_boundary(w);
#endif
}
uint px_add_f16x2(uint a, uint b) { return px_half_add_boundary(px_h2v(px_v2h(a) + px_v2h(b))); }
uint px_sub_f16x2(uint a, uint b) { return px_half_add_boundary(px_h2v(px_v2h(a) - px_v2h(b))); }
uint px_mul_f16x2(uint a, uint b) { return px_half_boundary(px_h2v(px_v2h(a) * px_v2h(b))); }
uint px_fma_f16x2(uint a, uint b, uint c) {
    uint w = px_h2v(mad(px_v2h(a), px_v2h(b), px_v2h(c)));
#ifdef PX_HALF_FMA_NO_BARRIER
    return w;
#else
    return px_half_boundary(w);
#endif
}
// typed pairs for the MMA rows
PXH2 px_h2fma(PXH2 a, PXH2 b, PXH2 c) { return mad(a, b, c); }
float px_h2lo(PXH2 a) { return (float)a.x; }
float px_h2hi(PXH2 a) { return (float)a.y; }
PXH2 px_u2h2(uint w) { return px_v2h(w); }
// +0 pair that the compiler cannot see as a constant (an FMA with a literal 0 becomes a multiply: wrong sign for -0)
PXH2 px_h2z(PXH2 a) { return asfloat16(asuint16(a) & (uint16_t)px_rtzero()); }
uint px_h22u(PXH2 a) { return px_h2v(a); }
uint px_max_f16x2(uint a, uint b) { return px_h2v(max(px_v2h(a), px_v2h(b))); }
uint px_min_f16x2(uint a, uint b) { return px_h2v(min(px_v2h(a), px_v2h(b))); }
uint px_abs_f16x2(uint a) { return a & 0x7fff7fffu; }
// fp32 math (ACO: v_rcp_f32 / v_exp_f32 / v_log_f32 / v_sqrt_f32)
float px_fmax(float a, float b) { return max(a, b); }
float px_fmin(float a, float b) { return min(a, b); }
float px_div_approx(float a, float b) { return a / b; }
float px_rcp(float a) { return 1.0f / a; }
float px_ex2(float a) { return exp2(a); }
float px_lg2(float a) { return log2(a); }
float px_sqrt(float a) { return sqrt(a); }
float px_sqrt_rn(float a) { return sqrt(a); }
float px_sat(float a) { return saturate(a); }
float px_floor(float a) { return floor(a); }
float px_trunc(float a) { return trunc(a); }
uint px_ballot(bool p) { uint4 mask = WaveActiveBallot(p); return WaveGetLaneIndex() < 32u ? mask.x : mask.y; }
#define PX_BARRIER() GroupMemoryBarrierWithGroupSync()

// sub-word shared memory: a 16-bit store writes one half of the pair (a separate ds_write_b16, so lanes writing the
// two halves of one word do not race). 8-bit stores are read-modify-write of the half (only used for single-value
// flags written identically by every thread).
uint PX_LDS16(uint a) { float16_t2 h = PX_LDSH2(a & ~3u); return (uint)asuint16((a & 2u) != 0u ? h.y : h.x); }
#define PX_LDS8(a) ((LDS32(a) >> (((a) & 3u) * 8u)) & 0xffu)
void PX_STS16(uint a, uint v) {
#ifdef PX_LDS_ROW8
    uint shift = (a & 2u) * 8u;
    uint expected = LDS32(a), observed;
    do {
        uint replacement = (expected & ~(0xffffu << shift)) | ((v & 0xffffu) << shift);
        InterlockedCompareExchange(SMR[a >> 4][(a >> 2) & 3u], expected, replacement, observed);
        if (observed == expected) break;
        expected = observed;
    } while (true);
#elif defined(PX_LDS_ROW4)
    SM4[a >> 3][(a >> 1) & 3u] = asfloat16((uint16_t)(v & 0xffffu));
#else
    if ((a & 2u) != 0u) SM[a >> 2].y = asfloat16((uint16_t)(v & 0xffffu));
    else SM[a >> 2].x = asfloat16((uint16_t)(v & 0xffffu));
#endif
}
void PX_STS8(uint a, uint v) {
    uint h = PX_LDS16(a & ~1u);
    uint sh = (a & 1u) * 8u;
    PX_STS16(a & ~1u, (h & ~(0xffu << sh)) | ((v & 0xffu) << sh));
}

// global memory: one buffer per pointer argument (PXBUF_<slot>, defined by the kernel), byte offset = low 32 bits of
// the 64-bit "address" (the host writes (slot + 1) << 40 | byte offset into each pointer argument)
#define PX_GLD32(S, a) PXBUF_##S.Load((uint)(a))
#define PX_GLD64(S, a) ((uint64_t)PXBUF_##S.Load((uint)(a)) | ((uint64_t)PXBUF_##S.Load((uint)(a) + 4u) << 32))
#define PX_GLD16(S, a) ((uint)PXBUF_##S.Load<uint16_t>((uint)(a)))
#define PX_GLD8(S, a) ((PXBUF_##S.Load((uint)(a) & ~3u) >> (((uint)(a) & 3u) * 8u)) & 0xffu)
#define PX_GLD2(S, a) PXBUF_##S.Load2((uint)(a))
#define PX_GLD4(S, a) PXBUF_##S.Load4((uint)(a))
#define PX_GST32(S, a, v) PXBUF_##S.Store((uint)(a), (v))
#define PX_GST16(S, a, v) PXBUF_##S.Store<uint16_t>((uint)(a), (uint16_t)(v))
#define PX_GST8(S, a, v) px_gst8_##S((uint)(a), (v))
#define PX_GST2(S, a, v) PXBUF_##S.Store2((uint)(a), (v))
#define PX_GST4(S, a, v) PXBUF_##S.Store4((uint)(a), (v))
#ifdef PX_U5_COMPACT
uint u5_load32(uint a);
void u5_store32(uint a, uint v);
PXH2 u5_loadh2(uint a);
#undef LDS32
#undef PX_STS32
#undef PX_LDSH2
#define LDS32(a) u5_load32(a)
#define PX_STS32(a, v) u5_store32(a, v)
#define PX_LDSH2(a) u5_loadh2(a)
#endif
#include "px_common.h"
#endif
