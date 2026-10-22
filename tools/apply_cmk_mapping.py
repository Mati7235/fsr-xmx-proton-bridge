#!/usr/bin/env python3
"""Experimental offline CMK2 -> CMK3 mapping adapter; never installs or runs kernels.

CMK3 is a LOCAL prototype format requiring the matching ANV reader patch. An old
reader rejects its magic instead of silently applying the legacy tail heuristic.
Unreviewed cross-thread payload contents are preserved, not fixed by this tool.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

CMK2_SIZE = 472
CMK3_EXPLICIT_TABLE_BASE = 1


def convert(data, profile):
    if len(data) < CMK2_SIZE or data[:4] != b'CMK2':
        raise ValueError('Expected legacy CMK2')
    code_size, = struct.unpack_from('<I', data, 4)
    if not 0 < code_size <= 16*1024*1024 or len(data) != CMK2_SIZE+code_size:
        raise ValueError('Invalid CMK2 code length')
    if profile.get('schema_version') != 1 or profile.get('status') != 'experimental-offline-only':
        raise ValueError('Unsupported experimental profile')
    if hashlib.sha256(data[CMK2_SIZE:]).hexdigest() != profile.get('code_sha256'):
        raise ValueError('Native code identity does not match reviewed mapping')
    surfaces = profile['surfaces']
    count, = struct.unpack_from('<I', data, 180)
    if not 0 < count <= 24 or count != len(surfaces):
        raise ValueError('Surface count mismatch')
    btis = list(struct.unpack_from(f'<{count}I', data, 184))
    if btis != [s['bti'] for s in surfaces] or len(set(btis)) != count:
        raise ValueError('BTI mapping mismatch or duplicates')
    base, expected = profile['table_pc_base'], profile['expected_push_size']
    if type(base) is not int or type(expected) is not int or not 0 <= base < expected <= 256 or base % 4 or expected % 4:
        raise ValueError('Invalid reviewed push layout')
    table, elem = [], []
    for i, s in enumerate(surfaces):
        t, e = s['table_index'], s['element']
        if s['arg_index'] != i or type(t) is not int or type(e) is not int or not 0 <= t <= 0xffffffff or not 0 <= e <= 0xffffffff:
            raise ValueError('Invalid surface metadata')
        offset = base+4*t
        if offset+4 > expected or offset != s['push_byte_offset']:
            raise ValueError('Surface outside expected push layout')
        table.append(t)
        elem.append(e)
    header = bytearray(data[:CMK2_SIZE])
    header[:4] = b'CMK3'
    struct.pack_into('<III', header, 168, 0xffffffff, 0, base)
    struct.pack_into('<24I', header, 280, *(table+[0]*(24-count)))
    struct.pack_into('<24I', header, 376, *(elem+[0]*(24-count)))
    extension = struct.pack('<II', CMK3_EXPLICIT_TABLE_BASE, expected)
    return bytes(header)+extension+data[CMK2_SIZE:]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cmk2', type=Path)
    p.add_argument('profile', type=Path)
    p.add_argument('output', type=Path, help='New local artifact, never a runtime cache path')
    a = p.parse_args()
    result = convert(a.cmk2.read_bytes(), json.loads(a.profile.read_text()))
    with a.output.open('xb') as f:
        f.write(result)
    print(f'Wrote {len(result)} bytes; offline prototype, not GPU-validated')


if __name__ == '__main__':
    main()
