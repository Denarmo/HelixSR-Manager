// Shared PTX-semantics helpers, compiled both as HLSL (px_hlsl.h) and as C++ (px_cpp.h).
// Only portable syntax here: uint/int/float/uint64_t/int64_t/bool/float4, INOUT/OUTP parameter macros,
// and the target primitives declared by the including prelude:
//   px_lane(), px_rd(v, lane) (wave read), px_qrd(v, quadlane) (quad read), LDS32(byteaddr), f16 helpers.
#ifndef PX_COMMON_H
#define PX_COMMON_H

// Optional explicit FP32 boundaries avoid propagating HLSL precise backwards
// into packed FP16 FMAs in a different branch of the kernel.
#ifdef PX_FP32_ROUND_BARRIER
#define PX_PFLOAT float
float px_round32(float v) {
#ifdef __cplusplus
    return v;
#else
    return asfloat(asuint(v) | px_rtzero());
#endif
}
#else
#define PX_PFLOAT PRECISE float
float px_round32(float v) { return v; }
#endif

// ---- fp32 ---------------------------------------------------------------------------------------------------------
// add.rz: exact sum by TwoSum, then step the round-to-nearest result one ulp toward zero if it rounded away from zero.
float px_add_rz(float a, float b) {
    PX_PFLOAT s = px_round32(a + b);
    PX_PFLOAT bb = px_round32(s - a);
    PX_PFLOAT e = px_round32(px_round32(a - px_round32(s - bb)) + px_round32(b - bb));
    if (e != 0.0f && s != 0.0f && ((s > 0.0f) != (e > 0.0f))) {
        uint u = asuint(s);
        s = asfloat(u - 1u);   // magnitude one ulp smaller, same sign
    }
    return s;
}

// Round (p + d) to fp16 exactly once (p, d fp32; the exact sum may not be fp32-representable).
uint px_f16_of_sum(float p, float d) {
    PX_PFLOAT s = px_round32(p + d);
    PX_PFLOAT bb = px_round32(s - p);
    PX_PFLOAT e = px_round32(px_round32(p - px_round32(s - bb)) + px_round32(d - bb));
    uint h = px_f2h(s);
    float hs = px_h2f(h);
    float diff = s - hs;
    if (diff == 0.0f || e == 0.0f) return h;
    // s lies strictly between fp16 values: only a tie (s exactly on an fp16 midpoint) can round differently.
    uint mag = h & 0x7fffu;
    bool neg = (h & 0x8000u) != 0u;
    bool up = (diff > 0.0f) != neg;          // does s lie at larger magnitude than h?
    uint nbits;
    if (mag == 0u) nbits = (diff > 0.0f) ? 0x0001u : 0x8001u;
    else nbits = up ? (h + 1u) : (h - 1u);
    float nf = px_h2f(nbits);
    float half_gap = abs(nf - hs) * 0.5f;
    if (abs(diff) != half_gap) return h;      // not a tie: RNE(s) is RNE(exact)
    // tie at s: the exact value is past the midpoint in the direction of e
    bool e_toward_n = (e > 0.0f) == (nf > hs);
    return e_toward_n ? nbits : h;
}

// ---- warp shuffle (shfl.sync) --------------------------------------------------------------------------------------
uint px_shfl_core(uint a, uint j, uint lane, uint maxl, OUTP(bool) ok) {
    ok = j <= maxl;
    uint src = ok ? j : lane;
    return px_rd(a, src);
}
uint px_shfl_idx(uint a, uint b, uint c, OUTP(bool) ok) {
    uint lane = px_lane();
    uint segmask = (c >> 8) & 0x1fu;
    uint minl = lane & segmask;
    uint maxl = minl | ((c & 0x1fu) & ~segmask);
    uint j = minl | (b & ~segmask & 0x1fu);
    return px_shfl_core(a, j, lane, maxl, ok);
}
uint px_shfl_down(uint a, uint b, uint c, OUTP(bool) ok) {
    uint lane = px_lane();
    uint segmask = (c >> 8) & 0x1fu;
    uint minl = lane & segmask;
    uint maxl = minl | ((c & 0x1fu) & ~segmask);
    uint j = lane + b;
    return px_shfl_core(a, j, lane, maxl, ok);
}

// ---- ldmatrix (m8n8, b16, non-transposed) --------------------------------------------------------------------------
void px_ldmatrix_x4(OUTP(uint) d0, OUTP(uint) d1, OUTP(uint) d2, OUTP(uint) d3, uint addr) {
    uint lane = px_lane();
    uint off = (lane & 3u) * 4u;
    d0 = LDS32(px_rd(addr, 0u + (lane >> 2)) + off);
    d1 = LDS32(px_rd(addr, 8u + (lane >> 2)) + off);
    d2 = LDS32(px_rd(addr, 16u + (lane >> 2)) + off);
    d3 = LDS32(px_rd(addr, 24u + (lane >> 2)) + off);
}
#if defined(PX_FAST) && !defined(__cplusplus) && !defined(PX_LDS_ROW8) && !defined(PX_LDS_ROW4)
// Fast numerics, row-based m16n8k16 (output kernels' compact MMAs): every lane reads the A rows it needs (rows g and
// g+8, k 0..15) and the B rows of its two output columns (n = 2t, 2t+1) as typed fp16 pairs from shared memory (the
// ldmatrix sources), so the products are packed v_pk_fma_f16 instead of cross-lane fragment exchanges.
// ldmatrix_x4 layout: row r of matrix j sits at the address held by lane 8j + r; A: m0 rows 0-7 k 0-7, m1 rows 8-15
// k 0-7, m2 rows 0-7 k 8-15, m3 rows 8-15 k 8-15; B tile: matrix m = k 0-7, m + 1 = k 8-15 (rows = n).
void pxr_arows_lds(uint addr, out PXH2 u[8], out PXH2 l[8]) {
    uint g = px_lane() >> 2;
    uint r0 = px_rd(addr, g) >> 2, r1 = px_rd(addr, 8u + g) >> 2, r2 = px_rd(addr, 16u + g) >> 2, r3 = px_rd(addr, 24u + g) >> 2;
    [unroll] for (uint w = 0u; w < 4u; ++w) {
        u[w] = SM[r0 + w]; l[w] = SM[r1 + w]; u[4u + w] = SM[r2 + w]; l[4u + w] = SM[r3 + w];
    }
}
// A from fragment registers (a0 = A[g][2t..], a1 = A[g+8][2t..], a2 / a3 the k 8-15 halves): quad reads
void pxr_arows_reg(uint a0, uint a1, uint a2, uint a3, out PXH2 u[8], out PXH2 l[8]) {
    [unroll] for (uint w = 0u; w < 4u; ++w) {
        u[w] = px_u2h2(px_qrd(a0, w)); l[w] = px_u2h2(px_qrd(a1, w));
        u[4u + w] = px_u2h2(px_qrd(a2, w)); l[4u + w] = px_u2h2(px_qrd(a3, w));
    }
}
// one n-tile: dU = (D[g][2t], D[g][2t+1]), dL = (D[g+8][2t], D[g+8][2t+1]); C in, D out (fp16 pairs)
void pxr_tile(INOUT(uint) dU, INOUT(uint) dL, PXH2 u[8], PXH2 l[8], uint addrB, uint m) {
    uint t = px_lane() & 3u;
    uint b0l = px_rd(addrB, 8u * m + 2u * t) >> 2, b0h = px_rd(addrB, 8u * (m + 1u) + 2u * t) >> 2;
    uint b1l = px_rd(addrB, 8u * m + 2u * t + 1u) >> 2, b1h = px_rd(addrB, 8u * (m + 1u) + 2u * t + 1u) >> 2;
    PXH2 su0 = PXH2(0, 0), su1 = PXH2(0, 0), sl0 = PXH2(0, 0), sl1 = PXH2(0, 0);
    [unroll] for (uint w = 0u; w < 4u; ++w) {
        PXH2 x0 = SM[b0l + w], x1 = SM[b1l + w], y0 = SM[b0h + w], y1 = SM[b1h + w];
        su0 = mad(u[w], x0, su0); su1 = mad(u[w], x1, su1); sl0 = mad(l[w], x0, sl0); sl1 = mad(l[w], x1, sl1);
        su0 = mad(u[4u + w], y0, su0); su1 = mad(u[4u + w], y1, su1); sl0 = mad(l[4u + w], y0, sl0); sl1 = mad(l[4u + w], y1, sl1);
    }
    float vu0 = px_h2f(dU) + ((float)su0.x + (float)su0.y), vu1 = px_h2f(dU >> 16) + ((float)su1.x + (float)su1.y);
    float vl0 = px_h2f(dL) + ((float)sl0.x + (float)sl0.y), vl1 = px_h2f(dL >> 16) + ((float)sl1.x + (float)sl1.y);
    dU = px_f2h(vu0) | (px_f2h(vu1) << 16);
    dL = px_f2h(vl0) | (px_f2h(vl1) << 16);
}
#endif
void px_ldmatrix_x2(OUTP(uint) d0, OUTP(uint) d1, uint addr) {
    uint lane = px_lane();
    uint off = (lane & 3u) * 4u;
    d0 = LDS32(px_rd(addr, 0u + (lane >> 2)) + off);
    d1 = LDS32(px_rd(addr, 8u + (lane >> 2)) + off);
}
void px_ldmatrix_x1(OUTP(uint) d0, uint addr) {
    uint lane = px_lane();
    d0 = LDS32(px_rd(addr, lane >> 2) + (lane & 3u) * 4u);
}

// ---- mma.sync.m16n8k16 / m16n8k8, f16 inputs and accumulator ------------------------------------------------------
// Original numerics ("orig"): per output, C to fp32, k-pairs in lane-rotated order (t+k)&3, two fp32 FMAs per pair
// (fp16 products are exact in fp32, so fused == unfused); the last FMA of the MMA either rounds once to fp16
// ("direct", two=false) or goes fp32 -> fp16 ("two").
float px_lo(uint w) { return px_h2f(w & 0xffffu); }
float px_hi(uint w) { return px_h2f(w >> 16); }

void px_mma_orig(OUTP(uint) d0, OUTP(uint) d1, uint a0, uint a1, uint a2, uint a3, uint b0, uint b1,
                 uint c0, uint c1, bool k16, bool two) {
    uint lane = px_lane();
    uint t = lane & 3u;
    // A words from my quad (lanes (g<<2)|tp): A[areg][tp]
    uint A0[4]; uint A1[4]; uint A2[4]; uint A3[4];
    uint B0[2][4]; uint B1[2][4];
    for (uint tp = 0u; tp < 4u; ++tp) {
        A0[tp] = px_qrd(a0, tp); A1[tp] = px_qrd(a1, tp);
        A2[tp] = px_qrd(a2, tp); A3[tp] = px_qrd(a3, tp);
        for (uint oo = 0u; oo < 2u; ++oo) {
            uint src = ((2u * t + oo) << 2) | tp;
            B0[oo][tp] = px_rd(b0, src);
            B1[oo][tp] = px_rd(b1, src);
        }
    }
    uint res0 = 0u; uint res1 = 0u;
    uint npair = k16 ? 8u : 4u;
    for (uint r = 0u; r < 2u; ++r) {
        uint cr = (r == 0u) ? c0 : c1;
        uint halves = 0u;
        for (uint oo = 0u; oo < 2u; ++oo) {
            float d = (oo == 0u) ? px_lo(cr) : px_hi(cr);
            uint hres = 0u;
            for (uint k = 0u; k < npair; ++k) {
                uint tp = (t + k) & 3u;
                uint chunk = k16 ? (k >> 2) : 0u;
                uint aw = (chunk == 0u) ? ((r == 0u) ? A0[tp] : A1[tp]) : ((r == 0u) ? A2[tp] : A3[tp]);
                uint bw = (chunk == 0u) ? B0[oo][tp] : B1[oo][tp];
                d = px_lo(aw) * px_lo(bw) + d;
                if (k == npair - 1u && !two) {
                    hres = px_f16_of_sum(px_hi(aw) * px_hi(bw), d);
                } else {
                    d = px_hi(aw) * px_hi(bw) + d;
                    hres = px_f2h(d);
                }
            }
            halves |= hres << (16u * oo);
        }
        if (r == 0u) res0 = halves; else res1 = halves;
    }
    d0 = res0; d1 = res1;
}

// Chain modes (fp32 accumulation across the MMA chain, rounded per MMA only for the visible D registers).
// mode 1 = 'f32' (one fp32 FMA per product, ascending k); mode 2 = 'pk' (two fp16 partial sums per MMA, even/odd k,
// fused fp16 FMA per product, then each added into the fp32 accumulator). sh = (r0o0, r0o1, r1o0, r1o1) is the chain's
// fp32 accumulator; the caller (re)initializes it from C whenever the chain registers were written by anything else.
void px_mma_chain(OUTP(uint) d0, OUTP(uint) d1, uint a0, uint a1, uint a2, uint a3, uint b0, uint b1,
                  bool k16, uint mode, INOUT(float4) sh) {
    uint lane = px_lane();
    uint t = lane & 3u;
    uint A0[4]; uint A1[4]; uint A2[4]; uint A3[4];
    uint B0[2][4]; uint B1[2][4];
    for (uint tp = 0u; tp < 4u; ++tp) {
        A0[tp] = px_qrd(a0, tp); A1[tp] = px_qrd(a1, tp);
        A2[tp] = px_qrd(a2, tp); A3[tp] = px_qrd(a3, tp);
        for (uint oo = 0u; oo < 2u; ++oo) {
            uint src = ((2u * t + oo) << 2) | tp;
            B0[oo][tp] = px_rd(b0, src);
            B1[oo][tp] = px_rd(b1, src);
        }
    }
    uint nk = k16 ? 16u : 8u;
    float acc[4] = { sh.x, sh.y, sh.z, sh.w };
    for (uint r = 0u; r < 2u; ++r) {
        for (uint oo = 0u; oo < 2u; ++oo) {
            float a = acc[r * 2u + oo];
            uint p0 = 0u; uint p1 = 0u;
            for (uint k = 0u; k < nk; ++k) {
                uint chunk = k >> 3;
                uint tp = (k & 7u) >> 1;
                uint aw = (chunk == 0u) ? ((r == 0u) ? A0[tp] : A1[tp]) : ((r == 0u) ? A2[tp] : A3[tp]);
                uint bw = (chunk == 0u) ? B0[oo][tp] : B1[oo][tp];
                uint ah = (k & 1u) ? (aw >> 16) : (aw & 0xffffu);
                uint bh = (k & 1u) ? (bw >> 16) : (bw & 0xffffu);
                if (mode == 1u) {
                    a = px_h2f(ah) * px_h2f(bh) + a;
                } else {
                    if (k & 1u) p1 = px_fma16(ah, bh, p1); else p0 = px_fma16(ah, bh, p0);
                }
            }
            if (mode != 1u) {
                a = px_h2f(p0) + a;
                a = px_h2f(p1) + a;
            }
            acc[r * 2u + oo] = a;
        }
    }
    sh = float4(acc[0], acc[1], acc[2], acc[3]);
    d0 = px_f2h(acc[0]) | (px_f2h(acc[1]) << 16);
    d1 = px_f2h(acc[2]) | (px_f2h(acc[3]) << 16);
}

// Output-kernel packed model ('pk2', installed K5 / K5F): per output, the products of k-pairs 0..6 (lane-rotated
// order) as two fp16 partial sums (lo halves / hi halves, fused fp16 FMA), folded into fp32 C as (c + p.lo) + p.hi, then
// the last pair exactly as the original (two: fp32 FMA then fp16; direct: one rounding to fp16).
void px_mma_pk2(OUTP(uint) d0, OUTP(uint) d1, uint a0, uint a1, uint a2, uint a3, uint b0, uint b1,
                uint c0, uint c1, bool two) {
    uint lane = px_lane();
    uint t = lane & 3u;
    uint A0[4]; uint A1[4]; uint A2[4]; uint A3[4];
    uint B0[2][4]; uint B1[2][4];
    for (uint tp = 0u; tp < 4u; ++tp) {
        A0[tp] = px_qrd(a0, tp); A1[tp] = px_qrd(a1, tp);
        A2[tp] = px_qrd(a2, tp); A3[tp] = px_qrd(a3, tp);
        for (uint oo = 0u; oo < 2u; ++oo) {
            uint src = ((2u * t + oo) << 2) | tp;
            B0[oo][tp] = px_rd(b0, src);
            B1[oo][tp] = px_rd(b1, src);
        }
    }
    uint res0 = 0u; uint res1 = 0u;
    for (uint r = 0u; r < 2u; ++r) {
        uint cr = (r == 0u) ? c0 : c1;
        uint halves = 0u;
        for (uint oo = 0u; oo < 2u; ++oo) {
            uint p0 = 0u; uint p1 = 0u;
            uint hres = 0u;
            for (uint k = 0u; k < 8u; ++k) {
                uint tp = (t + k) & 3u;
                uint chunk = k >> 2;
                uint aw = (chunk == 0u) ? ((r == 0u) ? A0[tp] : A1[tp]) : ((r == 0u) ? A2[tp] : A3[tp]);
                uint bw = (chunk == 0u) ? B0[oo][tp] : B1[oo][tp];
                if (k < 7u) {
                    p0 = px_fma16(aw & 0xffffu, bw & 0xffffu, p0);
                    p1 = px_fma16(aw >> 16, bw >> 16, p1);
                } else {
                    float d = ((oo == 0u) ? px_lo(cr) : px_hi(cr)) + px_h2f(p0);
                    d = d + px_h2f(p1);
                    d = px_lo(aw) * px_lo(bw) + d;
                    if (two) {
                        d = px_hi(aw) * px_hi(bw) + d;
                        hres = px_f2h(d);
                    } else {
                        hres = px_f16_of_sum(px_hi(aw) * px_hi(bw), d);
                    }
                }
            }
            halves |= hres << (16u * oo);
        }
        if (r == 0u) res0 = halves; else res1 = halves;
    }
    d0 = res0; d1 = res1;
}

// ---- fast MMA path: full rows instead of fragment shuffles ---------------------------------------------------------
// Lane (g, t) = (lane >> 2, lane & 3) owns D rows g and g+8, columns 2t and 2t+1. It needs A rows g and g+8 and B
// columns 2t and 2t+1 for all k. When an MMA operand comes from ldmatrix, those rows are read straight from LDS at the
// ldmatrix (row address of matrix j row i = address operand of lane 8j+i); otherwise they are gathered from the
// fragment registers (A: quad lanes, B: lanes (2t+o)*4+tp). Row word w holds k = 2w (lo half) and 2w+1 (hi half).
// Rotated rows (orig / pk2 numerics) hold word (t + w) & 3 at position w: the lane-rotated k-pair order.
struct PxRow { PXH2 w0; PXH2 w1; PXH2 w2; PXH2 w3; };
#if defined(PX_LDS_ROW8) && !defined(__cplusplus) && !defined(PX_U5_COMPACT)
#define PX_STS4(a, v0, v1, v2, v3) SMR[(a) >> 4] = uint4(v0, v1, v2, v3)
#else
#define PX_STS4(a, v0, v1, v2, v3) do { PX_STS32(a, v0); PX_STS32((a) + 4u, v1); PX_STS32((a) + 8u, v2); PX_STS32((a) + 12u, v3); } while (false)
#endif
PxRow px_mkrow(PXH2 a, PXH2 b, PXH2 c, PXH2 d) { PxRow r; r.w0 = a; r.w1 = b; r.w2 = c; r.w3 = d; return r; }
PxRow px_row0() { return px_mkrow(px_u2h2(0u), px_u2h2(0u), px_u2h2(0u), px_u2h2(0u)); }
PxRow px_row(uint a) {
    uint i = (a >> 4) << 4;   // ldmatrix row addresses are 16-byte aligned
#if defined(PX_LDS_ROW8) && !defined(__cplusplus) && !defined(PX_U5_COMPACT)
    uint4 words = SMR[i >> 4];
    return px_mkrow(px_u2h2(words.x), px_u2h2(words.y), px_u2h2(words.z), px_u2h2(words.w));
#elif defined(PX_LDS_ROW4) && !defined(__cplusplus) && !defined(PX_U5_COMPACT)
    float16_t4 lo = SM4[i >> 3], hi = SM4[(i >> 3) + 1u];
    return px_mkrow(lo.xy, lo.zw, hi.xy, hi.zw);
#else
    return px_mkrow(PX_LDSH2(i), PX_LDSH2(i + 4u), PX_LDSH2(i + 8u), PX_LDSH2(i + 12u));
#endif
}
PxRow px_row_rot(uint a) {
    uint t = px_lane() & 3u;
    return px_mkrow(PX_LDSH2(a + ((t & 3u) << 2)), PX_LDSH2(a + (((t + 1u) & 3u) << 2)),
                    PX_LDSH2(a + (((t + 2u) & 3u) << 2)), PX_LDSH2(a + (((t + 3u) & 3u) << 2)));
}
PxRow px_rot4(PxRow v) {
    uint t = px_lane() & 3u;
    PxRow r = v;
    if ((t & 1u) != 0u) r = px_mkrow(v.w1, v.w2, v.w3, v.w0);
    PxRow q = r;
    if ((t & 2u) != 0u) q = px_mkrow(r.w2, r.w3, r.w0, r.w1);
    return q;
}
PXH2 px_rw(PxRow v, uint i) { return i == 0u ? v.w0 : (i == 1u ? v.w1 : (i == 2u ? v.w2 : v.w3)); }
// gathers from fragment registers
PxRow px_arow(uint a) {
    return px_mkrow(px_u2h2(px_qrd(a, 0u)), px_u2h2(px_qrd(a, 1u)), px_u2h2(px_qrd(a, 2u)), px_u2h2(px_qrd(a, 3u)));
}
PxRow px_bcol(uint b, uint o) {
    uint s = (((px_lane() & 3u) * 2u + o) << 2);
    return px_mkrow(px_u2h2(px_rd(b, s)), px_u2h2(px_rd(b, s | 1u)), px_u2h2(px_rd(b, s | 2u)), px_u2h2(px_rd(b, s | 3u)));
}

// chain numerics (mode 1 = f32, 2 = pk) on plain rows; a0/b0 = chunk 0 (k 0..7), a1/b1 = chunk 1 (k 8..15)
float px_dot_chain(PxRow a0, PxRow b0, PxRow a1, PxRow b1, bool k16, uint mode, float acc) {
    if (mode == 1u) {
        for (uint w = 0u; w < 4u; ++w) {
            acc = px_h2lo(px_rw(a0, w)) * px_h2lo(px_rw(b0, w)) + acc;
            acc = px_h2hi(px_rw(a0, w)) * px_h2hi(px_rw(b0, w)) + acc;
        }
        if (k16) {
            for (uint w = 0u; w < 4u; ++w) {
                acc = px_h2lo(px_rw(a1, w)) * px_h2lo(px_rw(b1, w)) + acc;
                acc = px_h2hi(px_rw(a1, w)) * px_h2hi(px_rw(b1, w)) + acc;
            }
        }
        return acc;
    }
    // first product as an FMA with a runtime +0 (as the model: fma(a, b, +0)); a constant 0 would become a multiply,
    // which keeps the sign of a -0 product
    PXH2 p = px_h2fma(a0.w0, b0.w0, px_h2z(a0.w0));
    p = px_h2fma(a0.w1, b0.w1, p); p = px_h2fma(a0.w2, b0.w2, p); p = px_h2fma(a0.w3, b0.w3, p);
    if (k16) {
        p = px_h2fma(a1.w0, b1.w0, p); p = px_h2fma(a1.w1, b1.w1, p);
        p = px_h2fma(a1.w2, b1.w2, p); p = px_h2fma(a1.w3, b1.w3, p);
    }
    // no 'precise' here: HLSL precise is transitive and would turn the packed fp16 FMAs into mul+add
    float r = acc + px_h2lo(p);
    r = r + px_h2hi(p);
    return r;
}
void px_mmar_chain(OUTP(uint) d0, OUTP(uint) d1, PxRow a00, PxRow a10, PxRow a01, PxRow a11,
                   PxRow b00, PxRow b10, PxRow b01, PxRow b11, bool k16, uint mode, INOUT(float4) sh) {
    sh.x = px_dot_chain(a00, b00, a01, b01, k16, mode, sh.x);
    sh.y = px_dot_chain(a00, b10, a01, b11, k16, mode, sh.y);
    sh.z = px_dot_chain(a10, b00, a11, b01, k16, mode, sh.z);
    sh.w = px_dot_chain(a10, b10, a11, b11, k16, mode, sh.w);
    d0 = px_f2h(sh.x) | (px_f2h(sh.y) << 16);
    d1 = px_f2h(sh.z) | (px_f2h(sh.w) << 16);
}

// orig numerics on rotated rows: word w of a rotated row is k-pair (t + w) & 3 of its chunk
uint px_dot_orig(PxRow a0, PxRow b0, PxRow a1, PxRow b1, bool k16, bool two, uint c) {
#ifdef PX_ORIG_PRECISE
    PRECISE float d = px_h2f(c);
#else
    float d = px_h2f(c);
#endif
    uint npair = k16 ? 8u : 4u;
    uint h = 0u;
    for (uint k = 0u; k < npair; ++k) {
        PXH2 aw = k < 4u ? px_rw(a0, k & 3u) : px_rw(a1, k & 3u);
        PXH2 bw = k < 4u ? px_rw(b0, k & 3u) : px_rw(b1, k & 3u);
        d = px_h2lo(aw) * px_h2lo(bw) + d;
        if (k == npair - 1u && !two) {
            h = px_f16_of_sum(px_h2hi(aw) * px_h2hi(bw), d);
        } else {
            d = px_h2hi(aw) * px_h2hi(bw) + d;
            h = px_f2h(d);
        }
    }
    return h;
}
void px_mmar_orig(OUTP(uint) d0, OUTP(uint) d1, PxRow a00, PxRow a10, PxRow a01, PxRow a11,
                  PxRow b00, PxRow b10, PxRow b01, PxRow b11, uint c0, uint c1, bool k16, bool two) {
    d0 = px_dot_orig(a00, b00, a01, b01, k16, two, c0 & 0xffffu) | (px_dot_orig(a00, b10, a01, b11, k16, two, c0 >> 16) << 16);
    d1 = px_dot_orig(a10, b00, a11, b01, k16, two, c1 & 0xffffu) | (px_dot_orig(a10, b10, a11, b11, k16, two, c1 >> 16) << 16);
}
// pk2 numerics on rotated rows (m16n8k16)
uint px_dot_pk2(PxRow a0, PxRow b0, PxRow a1, PxRow b1, bool two, uint c) {
    PXH2 p = px_h2fma(a0.w0, b0.w0, px_h2z(a0.w0));
    p = px_h2fma(a0.w1, b0.w1, p); p = px_h2fma(a0.w2, b0.w2, p); p = px_h2fma(a0.w3, b0.w3, p);
    p = px_h2fma(a1.w0, b1.w0, p); p = px_h2fma(a1.w1, b1.w1, p); p = px_h2fma(a1.w2, b1.w2, p);
    float d = px_h2f(c) + px_h2lo(p);   // not 'precise' (transitive: it would unfuse the packed fp16 FMAs)
    d = d + px_h2hi(p);
    d = px_h2lo(a1.w3) * px_h2lo(b1.w3) + d;
    if (two) {
        d = px_h2hi(a1.w3) * px_h2hi(b1.w3) + d;
        return px_f2h(d);
    }
    return px_f16_of_sum(px_h2hi(a1.w3) * px_h2hi(b1.w3), d);
}
void px_mmar_pk2(OUTP(uint) d0, OUTP(uint) d1, PxRow a00, PxRow a10, PxRow a01, PxRow a11,
                 PxRow b00, PxRow b10, PxRow b01, PxRow b11, uint c0, uint c1, bool two) {
    d0 = px_dot_pk2(a00, b00, a01, b01, two, c0 & 0xffffu) | (px_dot_pk2(a00, b10, a01, b11, two, c0 >> 16) << 16);
    d1 = px_dot_pk2(a10, b00, a11, b01, two, c1 & 0xffffu) | (px_dot_pk2(a10, b10, a11, b11, two, c1 >> 16) << 16);
}

// ---- integer helpers -----------------------------------------------------------------------------------------------
uint px_prmt(uint a, uint b, uint c) {
    uint r = 0u;
    for (uint i = 0u; i < 4u; ++i) {
        uint sel = (c >> (4u * i)) & 0xfu;
        uint idx = sel & 7u;
        uint v = (idx < 4u) ? ((a >> (8u * idx)) & 0xffu) : ((b >> (8u * (idx - 4u))) & 0xffu);
        if (sel & 8u) v = ((v >> 7) & 1u) * 0xffu;
        r |= v << (8u * i);
    }
    return r;
}
uint px_bfi(uint a, uint b, uint pos, uint len) {
    pos &= 0xffu; len &= 0xffu;
    if (len == 0u || pos >= 32u) return b;
    uint mask = (len >= 32u) ? 0xffffffffu : ((1u << len) - 1u);
    mask = mask << pos;
    return (b & ~mask) | ((a << pos) & mask);
}
uint px_shl32(uint a, uint b) { return b >= 32u ? 0u : (a << b); }
uint px_shr32(uint a, uint b) { return b >= 32u ? 0u : (a >> b); }
uint px_sar32(uint a, uint b) { return asuint(int(a) >> (b >= 31u ? 31u : b)); }
uint64_t px_shl64(uint64_t a, uint b) { return b >= 64u ? (uint64_t)0 : (a << b); }
int px_mulhi_s32(int a, int b) { return int(((int64_t)a * (int64_t)b) >> 32); }
uint px_mulhi_u32(uint a, uint b) { return uint(((uint64_t)a * (uint64_t)b) >> 32); }

// fp32 -> integer conversions with PTX saturation (NaN -> 0)
int px_f2s32_rzi(float f) {
    if (!(f == f)) return 0;
    if (f >= 2147483648.0f) return 2147483647;
    if (f <= -2147483648.0f) return int(0x80000000u);
    return int(f);
}
uint px_f2u32_rzi(float f) {
    if (!(f == f) || f <= 0.0f) return 0u;
    if (f >= 4294967296.0f) return 0xffffffffu;
    return uint(f);
}

// f16x2 compare -> per-half 0xffff / 0 (set.cmp.u32.f16x2)
uint px_set_equ_f16x2(uint a, uint b) {
    float al = px_lo(a), ah = px_hi(a), bl = px_lo(b), bh = px_hi(b);
    bool l = !(al < bl) && !(al > bl);   // equal or unordered
    bool h = !(ah < bh) && !(ah > bh);
    return (l ? 0xffffu : 0u) | (h ? 0xffff0000u : 0u);
}

// ---- misc fp helpers ------------------------------------------------------------------------------------------------
// fma.rn.f32 (fused): stock RADV lowers 32-bit FMA to mul+add on gfx1013, so the shader computes
// it in fp64 (the fp32 product is exact in fp64; one fp64 add, then one rounding to fp32). PX_FMA32_UNFUSED selects the
// cheaper unfused form for kernels where the gate allows it.
#ifdef PX_FMA32_UNFUSED
#ifdef PX_FMA32_RELAXED
// gfx1013 RADV lowers FP32 FMA to separate multiply/add instructions. Avoid
// transitive HLSL precise here so upstream packed FP16 FMAs remain fused.
// FP32-to-FP16 boundaries still use px_f2h's runtime-zero barrier.
float px_fma32(float a, float b, float c) { float p = a * b; return p + c; }
#else
float px_fma32(float a, float b, float c) { PX_PFLOAT p = px_round32(a * b); PX_PFLOAT r = px_round32(p + c); return r; }
#endif
#else
float px_fma32(float a, float b, float c) { return (float)((double)a * (double)b + (double)c); }
#endif
// relu of an f16x2 FMA result: NaN -> canonical 0x7fff, negative (and -0) -> +0
uint px_relu_h(uint h) {
    if ((h & 0x7fffu) > 0x7c00u) return 0x7fffu;
    return (h & 0x8000u) != 0u ? 0u : h;
}
uint px_relu_f16x2(uint v) { return px_relu_h(v & 0xffffu) | (px_relu_h(v >> 16) << 16); }

#endif
