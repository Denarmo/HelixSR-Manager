// C++ side of the portable kernel sources: the CPU emulators compile the same kernel bodies as the HLSL shaders.
// Build with -ffp-contract=off (no FMA contraction) so every fp32 operation rounds like the GPU's unfused add/mul.
// One CTA runs as NT real threads with a real barrier (std::barrier); groupshared arrays are statics.
#pragma once
#include <barrier>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
typedef uint32_t uint;
static inline uint port_asu(float f) { uint u; memcpy(&u, &f, 4); return u; }
static inline float port_asf(uint u) { float f; memcpy(&f, &u, 4); return f; }
#define ASUINT port_asu
#define ASFLOAT port_asf
#define PRECISE
#define GS static
#define UNROLL
#define LOOP
struct float4 { float x, y, z, w; };
struct uint2 { uint x, y; };
struct uint4 { uint x, y, z, w; };
static inline float4 F4(float a, float b, float c, float d) { float4 r = {a, b, c, d}; return r; }
static inline uint2 U2(uint a, uint b) { uint2 r = {a, b}; return r; }
static inline uint4 U4(uint a, uint b, uint c, uint d) { uint4 r = {a, b, c, d}; return r; }
static inline uint MAXU(uint a, uint b) { return a > b ? a : b; }
extern std::barrier<> *g_port_bar;
#define BARRIER() g_port_bar->arrive_and_wait()
// MAD: the stock-RADV (gfx1013) lowering of a shader fma is an unfused multiply then add; EMU_FUSED=1 models a fused FMA.
#if defined(EMU_FUSED) && EMU_FUSED
#define MAD(a, b, c) std::fma((float)(a), (float)(b), (float)(c))
#else
static inline float port_mad(float a, float b, float c) { volatile float p = a * b; return p + c; }
#define MAD(a, b, c) port_mad((float)(a), (float)(b), (float)(c))
#endif
// Wave-uniform broadcast: the kernels only pass values that are already uniform in their wave.
#define WAVE_FIRST(x) (x)
// Lane exchange inside a wave32: XOR of the lane index (all lanes of the wave participate at the call site).
extern uint g_port_xbuf[1024];
static inline uint port_xchg(uint tid, uint v, uint m)
{
    g_port_xbuf[tid] = v; g_port_bar->arrive_and_wait();
    uint r = g_port_xbuf[(tid & ~31u) | ((tid & 31u) ^ m)]; g_port_bar->arrive_and_wait();
    return r;
}
#define LANE_XOR(tid, v, m) port_xchg(tid, v, m)
#include "fp16.h"

// Shader-level fp16 primitives (HLSL: hardware conversions, see port_hlsl.hlsli); here the exact integer models.
//   H2F(h): fp16 bits -> float; CVT16(f): float -> fp16 bits, RNE; FMIX(a, b, c): fp32 a*b + c of fp16 bits (exact
//   product, so fused == unfused); MIXLO(a, b, c): fp16(a*b + c) rounded once (v_fma_mixlo_f16).
#define H2F(h) fp_h2f(h)
#define CVT16(f) fp_rne16(f)
#define CVT16_SUM16(f) fp_rne16(f)
#define FMIX(a, b, c) fp_fmix(a, b, c)
#define MIXLO(a, b, c) fp_mixlo(a, b, c)
#define OPAQUE_F(x) (x)
