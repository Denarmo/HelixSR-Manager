// Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
// U5's immutable weights/bias stay in their SRVs; only activations occupy LDS.
#ifdef __cplusplus
inline uint PX_PARAM32(uint o);
#define U5_PHASE px_ctx->mem_phase
#else
static uint u5_phase = 0;
#define U5_PHASE u5_phase
#endif

uint u5_load32(uint a) {
    if (a < 0x8000u) {
#ifdef __cplusplus
        return px_sm(a);
#else
#ifdef PX_LDS_ROW8
        return SMR[a >> 4][(a >> 2) & 3u];
#elif defined(PX_LDS_ROW4)
        return px_h2v(px_lds_pair(a));
#else
        return px_h2v(SM[a >> 2]);
#endif
#endif
    }
    if (U5_PHASE == 0u && a >= 0xa140u)
        return PX_GLD32(3, a - 0xa140u);
    // Invert NVIDIA's weight-tile XOR swizzle: 8 channel vectors per row.
    uint b = a - 0x8000u;
    uint row = b >> 7;
    uint col = ((b & 127u) >> 4) ^ (row & 7u);
    uint off = b & 15u;
    if (U5_PHASE == 0u) {
        if (row >= PX_PARAM32(56u) || col * 8u >= PX_PARAM32(52u)) return 0u;
        return PX_GLD32(2, (row * PX_PARAM32(100u) + col * 8u) * 2u + off);
    }
    if (row >= PX_PARAM32(280u) || col * 8u >= PX_PARAM32(276u)) return 0u;
    return PX_GLD32(4, (row * PX_PARAM32(324u) + col * 8u) * 2u + off);
}

void u5_store32(uint a, uint v) {
#if defined(__cplusplus) && defined(U5_VALIDATE_WEIGHTS)
    if (a >= 0x8000u && u5_load32(a) != v) {
        char msg[128];
        snprintf(msg, sizeof msg, "weight mapping phase %u addr %x got %x expected %x", U5_PHASE, a, u5_load32(a), v);
        throw std::runtime_error(msg);
    }
#endif
    if (a >= 0x8000u) return; // Original cooperative weight/bias copies are redundant.
#ifdef __cplusplus
    px_sm(a) = v;
#else
#ifdef PX_LDS_ROW8
    px_sts_word(a, v);
#elif defined(PX_LDS_ROW4)
    px_sts_pair(a, v);
#else
    SM[a >> 2] = px_v2h(v);
#endif
#endif
}
PXH2 u5_loadh2(uint a) { return px_u2h2(u5_load32(a)); }
