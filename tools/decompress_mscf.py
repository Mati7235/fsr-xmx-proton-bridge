#!/usr/bin/env python3
"""Decode Compression API LZMS buffers using an explicitly supplied local libwim.

Only decompression code from libwim is loaded; the input DLL is never loaded.
Rejects unknown headers, CRC mismatch, truncation, and excessive output sizes.
"""
import argparse
import ctypes as ct
from pathlib import Path
import struct
import zlib


def decode(data: bytes, library: Path, max_output: int = 128*1024*1024) -> bytes:
    if len(data) < 24 or data[:4] != b'\x0a\x51\xe5\xc0':
        raise ValueError('Not a Compression API buffer')
    header_size, checksum, algorithm = struct.unpack_from('<HBB', data, 4)
    total, unknown1, blocksize, unknown2 = struct.unpack_from('<IIII', data, 8)
    if header_size != 24 or algorithm != 5 or unknown1 or unknown2:
        raise ValueError('Unsupported Compression API header')
    if (zlib.crc32(data[7:24], zlib.crc32(data[:6])) & 255) != checksum:
        raise ValueError('Header CRC mismatch')
    if not 0 < total <= max_output or not 0 < blocksize <= 64*1024*1024:
        raise ValueError('Output/block size exceeds limits')
    lib = ct.CDLL(str(library.resolve()))
    create = lib.wimlib_create_decompressor
    create.argtypes = [ct.c_int, ct.c_size_t, ct.POINTER(ct.c_void_p)]
    create.restype = ct.c_int
    decompress = lib.wimlib_decompress
    decompress.argtypes = [ct.c_void_p, ct.c_size_t, ct.c_void_p, ct.c_size_t, ct.c_void_p]
    decompress.restype = ct.c_int
    free = lib.wimlib_free_decompressor
    free.argtypes = [ct.c_void_p]
    free.restype = None
    context = ct.c_void_p()
    # WIMLIB_COMPRESSION_TYPE_LZMS = 3; Compression API LZMS = 5.
    if create(3, blocksize, ct.byref(context)):
        raise ValueError('Cannot create LZMS decompressor')
    result = bytearray()
    pos = 24
    try:
        while len(result) < total:
            if pos+4 > len(data):
                raise ValueError('Missing chunk length')
            size, = struct.unpack_from('<I', data, pos)
            pos += 4
            if not size or pos+size > len(data):
                raise ValueError('Truncated/empty compressed chunk')
            chunk = data[pos:pos+size]
            pos += size
            outsize = min(blocksize, total-len(result))
            if size == outsize:
                result.extend(chunk)
            else:
                output = ct.create_string_buffer(outsize)
                source = ct.create_string_buffer(chunk)
                if decompress(source, size, output, outsize, context):
                    raise ValueError(f'LZMS chunk failed at output offset {len(result)}')
                result.extend(output.raw)
        if pos != len(data):
            raise ValueError('Unexpected trailing compressed bytes')
        return bytes(result)
    finally:
        free(context)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--libwim', type=Path, required=True)
    a = p.parse_args()
    decoded = decode(a.input.read_bytes(), a.libwim)
    with a.output.open('xb') as f:
        f.write(decoded)
    print(f'Decoded {len(decoded)} bytes to {a.output}')


if __name__ == '__main__':
    main()
