#!/usr/bin/env python3
"""extract_weights.py NVNGX_DLSS_DLL OUT: rebuild HelixSR's weight file from the user's own nvngx_dlss.dll.

The network's weights are stored in the DLL as plain fp32 tensors; NGX converts them to fp16 with round-toward-zero.
This tool reads those tensors at the offsets known for a DLL version, converts them the same way and writes them in
HelixSR's canonical layout (per layer: fp16 weights O,H,W,I then fp16 bias, each tensor 256-byte aligned). The
result is checked against the expected sha256; nothing is written for an unknown DLL or a mismatch.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import hashlib, sys
import numpy as np

CANON_BYTES = 1903872
CANON_SHA256 = '762adfde720035f7ac43910846e0ce6826c239bcd41f863196f77c547ae57153'

# (canonical byte offset, O, I, k, stored layout) in canonical order. Stored layouts: 'OIHW' (3x3 convs), 'OI'
# (1x1 convs and biases: identical in every layout), 'OI_SHUF' (last 1x1 conv and its bias: output channel
# o = 8g + 2p + b stored at position 10p + 2g + b).
TENSORS = [
    (0, 32, 16, 3, 'OIHW'), (9216, 32, 1, 1, 'OI'), (9472, 64, 32, 1, 'OI'), (13568, 64, 1, 1, 'OI'),
    (13824, 128, 64, 3, 'OIHW'), (161280, 128, 1, 1, 'OI'), (161536, 128, 128, 3, 'OIHW'), (456448, 128, 1, 1, 'OI'),
    (456704, 256, 128, 3, 'OIHW'), (1046528, 256, 1, 1, 'OI'), (1047040, 512, 256, 1, 'OI'),
    (1309184, 512, 1, 1, 'OI'), (1310208, 256, 512, 1, 'OI'), (1572352, 256, 1, 1, 'OI'),
    (1572864, 256, 256, 1, 'OI'), (1703936, 256, 1, 1, 'OI'), (1704448, 128, 256, 1, 'OI'),
    (1769984, 128, 1, 1, 'OI'), (1770240, 128, 128, 1, 'OI'), (1803008, 128, 1, 1, 'OI'),
    (1803264, 128, 128, 1, 'OI'), (1836032, 128, 1, 1, 'OI'), (1836288, 128, 128, 1, 'OI'),
    (1869056, 128, 1, 1, 'OI'), (1869312, 64, 128, 1, 'OI'), (1885696, 64, 1, 1, 'OI'),
    (1885952, 64, 64, 1, 'OI'), (1894144, 64, 1, 1, 'OI'), (1894400, 32, 64, 1, 'OI'),
    (1898496, 32, 1, 1, 'OI'), (1898752, 32, 32, 1, 'OI'), (1900800, 32, 1, 1, 'OI'),
    (1901056, 40, 32, 1, 'OI_SHUF'), (1903616, 40, 1, 1, 'OI_SHUF'),
]

# Where each tensor starts differs between DLL versions (padding between tensors changes), so each one is found by
# a fingerprint: blake2b-64 of its first 64 stored bytes (same order as TENSORS). Tensors start 16-byte aligned.
FINGERPRINTS = [
    '6f822bc69a42c9e6', 'bda98eddf8432e87', '5ec423eb972835fc', 'be952a492f8e4e14', 'c64e2deafe12d773',
    '477ec1abc195cb9b', '504160e8f9a2ffca', '3c4c6d9e72ab05af', '5852075c7228ce7b', 'c31276deed4a5e6c',
    '2c36387f8111066e', '9444016509e60d35', 'f185e54fafff9c42', '04f04d2a6abebb27', 'fd082b43bedc9d3a',
    'c3f28e8bdd61528a', 'c91bcc2966858f68', 'aea1aff74ab27647', '091713613a21b032', '67a28b5af0cee014',
    '3298669751244b14', '1aa8c956351e0072', '6198ca9a3f7eb976', '3f9ca88ad36f345e', 'b2e055d37fb605dd',
    'dd7dca110d429050', '25cb49b05a296021', '8a99e08ede8387e8', '7bb3bdcf16b209ae', '3ef66cceab2d575c',
    'e232ecc987cc39b3', 'fb378f79b42d01ac', '36e739563aab99b0', '61ae1d24628d155d',
]


def locate(dll, align=16):
    """File offset of every tensor, found by fingerprint; None if one is missing."""
    want = {fp: i for i, fp in enumerate(FINGERPRINTS)}
    found = [None] * len(FINGERPRINTS)
    view = memoryview(dll)
    for p in range(0, len(dll) - 64, align):
        i = want.get(hashlib.blake2b(view[p:p + 64], digest_size=8).hexdigest())
        if i is not None and found[i] is None:
            found[i] = p
            if all(f is not None for f in found):
                break
    return None if any(f is None for f in found) else found


def rtz_fp16(x):
    """fp32 -> fp16, rounding toward zero (as NGX converts the weights)."""
    h = x.astype(np.float16)
    over = np.abs(h.astype(np.float32)) > np.abs(x)
    h[over] = np.nextafter(h[over], np.float16(0))
    return h


def extract(dll):
    offsets = locate(dll) or locate(dll, 4)
    if offsets is None:
        raise SystemExit('this nvngx_dlss.dll does not contain the network HelixSR uses; nothing written')
    out = bytearray(CANON_BYTES)
    for (coff, O, I, k, lay), foff in zip(TENSORS, offsets):
        n = O * I * k * k
        src = np.frombuffer(dll, np.float32, n, foff)
        if lay == 'OIHW':
            t = src.reshape(O, I, k, k).transpose(0, 2, 3, 1)   # -> O,H,W,I
        elif lay == 'OI_SHUF':
            rows = src.reshape(O, -1)
            t = rows[[10 * ((o % 8) // 2) + 2 * (o // 8) + (o % 2) for o in range(O)]]
        else:
            t = src
        with np.errstate(over='ignore'):
            out[coff:coff + 2 * n] = rtz_fp16(np.ascontiguousarray(t, np.float32).ravel()).tobytes()
    if hashlib.sha256(out).hexdigest() != CANON_SHA256:
        raise SystemExit('extracted weights do not match the expected checksum; nothing written')
    return bytes(out)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    data = extract(open(sys.argv[1], 'rb').read())
    open(sys.argv[2], 'wb').write(data)
    print(f'wrote {sys.argv[2]} ({len(data)} bytes, sha256 {CANON_SHA256[:16]}...)')
