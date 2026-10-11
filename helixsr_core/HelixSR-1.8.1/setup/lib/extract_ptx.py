#!/usr/bin/env python3
# Copyright 2026 lonewolf0622. Licensed under the Apache License, Version 2.0.
"""extract_ptx.py NVNGX_DLSS_DLL OUTDIR: write every PTX module of the DLL's CUDA fatbins as
OUTDIR/<entry>.sm_<NN>.ptx (one per kernel and target architecture).

CUDA fatbins (magic 0xBA55ED50) hold one file per target; PTX files (kind 1) are stored plain or LZ4-compressed
(flag 0x2000, standard LZ4 block format). Each module is named after its kernel (.entry), so callers find kernels by
name whatever the DLL's layout.
"""
import os as _o, sys as _s; _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))  # helixsr-setup
import re, struct, sys
from pathlib import Path

FATBIN_MAGIC = 0xBA55ED50
KIND_PTX = 1
FLAG_LZ4 = 0x2000
FLAG_ZSTD = 0x8000


def lz4_block(src, size_hint):
    """Decompress one LZ4 block (no frame header)."""
    out = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(out) - off
        if off <= 0 or start < 0:
            raise ValueError('bad LZ4 offset')
        for k in range(ml):   # overlapping copy
            out.append(out[start + k])
    return bytes(out)


def modules(dll):
    """Yield (entry name, SM version, PTX text) for every PTX file in the DLL's fatbins."""
    magic = struct.pack('<I', FATBIN_MAGIC)
    p = dll.find(magic)
    while p >= 0:
        _, hsize, fsize = struct.unpack_from('<HHQ', dll, p + 4)
        q, end = p + hsize, p + hsize + fsize
        while q + 64 <= end:
            kind, _, fh, payload, _, csize = struct.unpack_from('<HHIIII', dll, q)
            sm = struct.unpack_from('<I', dll, q + 28)[0]
            flags, _, raw = struct.unpack_from('<QQQ', dll, q + 40)
            body = dll[q + fh:q + fh + max(payload, csize)]
            if kind == KIND_PTX:
                if flags & FLAG_ZSTD:
                    raise SystemExit('zstd-compressed PTX is not supported')
                data = lz4_block(body[:csize], raw) if flags & FLAG_LZ4 else body[:payload]
                text = data.rstrip(b'\0').decode('utf-8', 'replace')
                for e in re.findall(r'\.entry\s+(\w+)', text):
                    yield e, sm, text
            if fh == 0:
                break
            q += fh + max(payload, csize)
        p = dll.find(magic, end)


if __name__ == '__main__':
    dll = open(sys.argv[1], 'rb').read()
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for entry, sm, text in modules(dll):
        (out / f'{entry}.sm_{sm}.ptx').write_text(text)
        n += 1
    print(f'{n} PTX kernels written to {out}')
