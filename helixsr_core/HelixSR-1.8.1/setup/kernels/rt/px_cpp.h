// C++ (CPU emulator) target primitives for px_common.h. Every GPU lane is a cooperative fiber (one OS thread per CTA);
// wave reads and barriers are rendezvous points that yield to the other lanes. Compile with -ffp-contract=off; FTZ/DAZ
// are set per OS thread (PTX .ftz semantics, DXC -denorm ftz).
#ifndef PX_CPP_H
#define PX_CPP_H
#include <cstdint>
#include <cstring>
#include <cmath>
#include <vector>
#include <stdexcept>
#include <algorithm>
#include <cstdio>
typedef uint32_t uint;
#define INOUT(T) T&
#define OUTP(T) T&
#define PRECISE
#define PX_LOOP
struct float4 { float x, y, z, w; float4() : x(0), y(0), z(0), w(0) {} float4(float a, float b, float c, float d) : x(a), y(b), z(c), w(d) {} };
struct uint3 { uint x, y, z; };
inline float asfloat(uint u) { float f; std::memcpy(&f, &u, 4); return f; }
inline uint asuint(float f) { uint u; std::memcpy(&u, &f, 4); return u; }
inline uint asuint(int i) { return (uint)i; }
using std::abs;
inline uint countbits(uint v) { return (uint)__builtin_popcount(v); }

void px_yield();   // switch to the next lane fiber of this CTA (emulator)
inline thread_local uint64_t px_events = 0;   // rendezvous arrivals (deadlock detection in the emulator)
struct PxBar {
    int expected = 0, arrived = 0; uint64_t gen = 0;
    void wait() {
        uint64_t g = gen; ++px_events;
        if (++arrived == expected) { arrived = 0; ++gen; return; }
        while (gen == g) px_yield();
    }
    void drop() { --expected; if (expected > 0 && arrived == expected) { arrived = 0; ++gen; } }
};
struct PxWave { uint slot[32]; PxBar bar; };
struct PxCtx {
    uint3 tid, ctaid, ntid; uint lane; PxWave* wave; PxBar* cta; uint* sm; size_t smwords;
    uint mem_phase = 0;
};
extern thread_local PxCtx* px_ctx;
inline uint px_lane() { return px_ctx->lane; }
inline uint px_rd(uint v, uint l) {
    PxWave* w = px_ctx->wave; w->slot[px_ctx->lane] = v; w->bar.wait();
    uint r = w->slot[l & 31u]; w->bar.wait(); return r;
}
inline uint px_qrd(uint v, uint l) { return px_rd(v, (px_ctx->lane & ~3u) | (l & 3u)); }
inline void px_barrier() { px_ctx->cta->wait(); }
inline uint& px_sm(uint a) {
    if ((a >> 2) >= px_ctx->smwords) {
        char message[96];
        snprintf(message, sizeof(message), "LDS out of bounds: byte %u, capacity %zu", a, px_ctx->smwords * 4);
        throw std::runtime_error(message);
    }
    return px_ctx->sm[a >> 2];
}
#define LDS32(a) px_sm(a)
#define PX_STS32(a, v) (px_sm(a) = (v))
struct PXH2 { uint v; };
inline uint px_rtzero() { return 0u; }
#define PX_LDSH2(a) PXH2{px_sm(a)}

inline float px_h2f(uint h) { _Float16 x; uint16_t b = (uint16_t)(h & 0xffffu); std::memcpy(&x, &b, 2); return (float)x; }
inline uint px_d2h(double d) { _Float16 x = (_Float16)d; uint16_t b; std::memcpy(&b, &x, 2); return b; }
inline uint px_f2h(float f) { return px_d2h((double)f); }
inline uint px_fma16(uint a, uint b, uint c) { return px_d2h((double)px_h2f(a) * (double)px_h2f(b) + (double)px_h2f(c)); }
inline uint px_f16x2(uint a, uint b, double (*op)(double, double)) {
    uint lo = px_d2h(op(px_h2f(a & 0xffffu), px_h2f(b & 0xffffu)));
    uint hi = px_d2h(op(px_h2f(a >> 16), px_h2f(b >> 16)));
    return lo | (hi << 16);
}
inline uint px_add_f16x2(uint a, uint b) { return px_f16x2(a, b, [](double x, double y) { return x + y; }); }
inline uint px_sub_f16x2(uint a, uint b) { return px_f16x2(a, b, [](double x, double y) { return x - y; }); }
inline uint px_mul_f16x2(uint a, uint b) { return px_f16x2(a, b, [](double x, double y) { return x * y; }); }
inline uint px_max_f16x2(uint a, uint b) { return px_f16x2(a, b, [](double x, double y) { return std::isnan(x) ? y : std::isnan(y) ? x : std::max(x, y); }); }
inline uint px_min_f16x2(uint a, uint b) { return px_f16x2(a, b, [](double x, double y) { return std::isnan(x) ? y : std::isnan(y) ? x : std::min(x, y); }); }
inline uint px_fma_f16x2(uint a, uint b, uint c) {
    return px_fma16(a & 0xffffu, b & 0xffffu, c & 0xffffu) | (px_fma16(a >> 16, b >> 16, c >> 16) << 16);
}
inline uint px_abs_f16x2(uint a) { return a & 0x7fff7fffu; }
inline PXH2 px_h2fma(PXH2 a, PXH2 b, PXH2 c) { return PXH2{px_fma_f16x2(a.v, b.v, c.v)}; }
inline float px_h2lo(PXH2 a) { return px_h2f(a.v & 0xffffu); }
inline float px_h2hi(PXH2 a) { return px_h2f(a.v >> 16); }
inline PXH2 px_u2h2(uint w) { return PXH2{w}; }
inline uint px_h22u(PXH2 a) { return a.v; }
inline PXH2 px_h2z(PXH2) { return PXH2{0u}; }
inline float px_floor(float f) { return std::floor(f); }
inline float px_trunc(float f) { return std::trunc(f); }
inline float px_fmax(float a, float b) { return std::fmax(a, b); }
inline float px_fmin(float a, float b) { return std::fmin(a, b); }
inline float px_div_approx(float a, float b) { volatile float r = 1.0f / b; return a * r; }
inline float px_rcp(float a) { return 1.0f / a; }
inline float px_ex2(float a) { return std::exp2(a); }
inline float px_lg2(float a) { return std::log2(a); }
inline float px_sqrt(float a) { return std::sqrt(a); }
inline float px_sqrt_rn(float a) { return std::sqrt(a); }
inline float px_sat(float a) { return !(a > 0.0f) ? 0.0f : (a > 1.0f ? 1.0f : a); }
inline int asint(uint u) { return (int)u; }
uint px_ballot(bool p);
#define PX_BARRIER() px_barrier()
inline uint PX_LDS16(uint a) { return (px_sm(a) >> ((a & 2u) * 8u)) & 0xffffu; }
inline uint PX_LDS8(uint a) { return (px_sm(a) >> ((a & 3u) * 8u)) & 0xffu; }
inline void PX_STS16(uint a, uint v) {
    uint sh = (a & 2u) * 8u; uint& w = px_sm(a);
    __atomic_fetch_and(&w, ~(0xffffu << sh), __ATOMIC_SEQ_CST); __atomic_fetch_or(&w, (v & 0xffffu) << sh, __ATOMIC_SEQ_CST);
}
inline void PX_STS8(uint a, uint v) {
    uint sh = (a & 3u) * 8u; uint& w = px_sm(a);
    __atomic_fetch_and(&w, ~(0xffu << sh), __ATOMIC_SEQ_CST); __atomic_fetch_or(&w, (v & 0xffu) << sh, __ATOMIC_SEQ_CST);
}

// global memory: per-slot byte buffers with bounds checks (an out-of-range access is a kernel bug -> abort)
struct uint2 { uint x, y; uint2() : x(0), y(0) {} uint2(uint a, uint b) : x(a), y(b) {} };
struct uint4 { uint x, y, z, w; uint4() : x(0), y(0), z(0), w(0) {} uint4(uint a, uint b, uint c, uint d) : x(a), y(b), z(c), w(d) {} };
struct PxBuf {
    uint8_t* p = nullptr; size_t n = 0; int slot = -1; uint8_t* mask = nullptr;
    uint8_t* at(uint o, uint sz) const {
        if (!p || (size_t)o + sz > n) { char m[96]; snprintf(m, 96, "global OOB slot %d off %u size %u (buf %zu)", slot, o, sz, n); throw std::runtime_error(m); }
        return p + o;
    }
    uint ld32(uint o) const { uint v; std::memcpy(&v, at(o, 4), 4); return v; }
    uint ld16(uint o) const { uint16_t v; std::memcpy(&v, at(o, 2), 2); return v; }
    uint ld8(uint o) const { return *at(o, 1); }
    void mark(uint o, uint sz) const { if (mask) std::memset(mask + o, 1, sz); }
    void st32(uint o, uint v) const { std::memcpy(at(o, 4), &v, 4); mark(o, 4); }
    void st8(uint o, uint v) const { *at(o, 1) = (uint8_t)v; mark(o, 1); }
    void st16(uint o, uint v) const { uint16_t h = (uint16_t)v; std::memcpy(at(o, 2), &h, 2); mark(o, 2); }
    uint2 ld2(uint o) const { return uint2(ld32(o), ld32(o + 4)); }
    uint4 ld4(uint o) const { return uint4(ld32(o), ld32(o + 4), ld32(o + 8), ld32(o + 12)); }
    void st2(uint o, uint2 v) const { st32(o, v.x); st32(o + 4, v.y); }
    void st4(uint o, uint4 v) const { st32(o, v.x); st32(o + 4, v.y); st32(o + 8, v.z); st32(o + 12, v.w); }
};
extern PxBuf px_bufs[16];
#define PX_GLD32(S, a) px_bufs[S].ld32((uint)(a))
#define PX_GLD64(S, a) ((uint64_t)px_bufs[S].ld32((uint)(a)) | ((uint64_t)px_bufs[S].ld32((uint)(a) + 4u) << 32))
#define PX_GLD16(S, a) px_bufs[S].ld16((uint)(a))
#define PX_GLD8(S, a) px_bufs[S].ld8((uint)(a))
#define PX_GST32(S, a, v) px_bufs[S].st32((uint)(a), (v))
#define PX_GST16(S, a, v) px_bufs[S].st16((uint)(a), (v))
#define PX_GST8(S, a, v) px_bufs[S].st8((uint)(a), (v))
float4 px_tex_level(int s, float u, float v, float lod);
float4 px_tex_fetch(int s, int x, int y);
void px_surf_store(int s, int x, int y, float4 v, int n);
#define PX_TEX_LEVEL(S, u, v, l) px_tex_level(S, u, v, l)
#define PX_TEX_FETCH(S, x, y) px_tex_fetch(S, x, y)
#define PX_SURF_STORE4(S, x, y, v) px_surf_store(S, x, y, v, 4)
#define PX_SURF_STORE1(S, x, y, v) px_surf_store(S, x, y, float4(v, 0.0f, 0.0f, 0.0f), 1)
#define PX_GLD2(S, a) px_bufs[S].ld2((uint)(a))
#define PX_GLD4(S, a) px_bufs[S].ld4((uint)(a))
#define PX_GST2(S, a, v) px_bufs[S].st2((uint)(a), (v))
#define PX_GST4(S, a, v) px_bufs[S].st4((uint)(a), (v))
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
