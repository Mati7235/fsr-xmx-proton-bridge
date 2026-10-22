#!/usr/bin/env python3
"""Extract PE resource leaves without loading the image (Python standard library)."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def extract(data: bytes) -> list[tuple[list, bytes]]:
    def unpack(fmt, offset):
        size = struct.calcsize(fmt)
        if offset < 0 or offset + size > len(data):
            raise ValueError('Truncated PE structure')
        return struct.unpack_from(fmt, data, offset)

    if data[:2] != b'MZ':
        raise ValueError('Missing DOS signature')
    pe, = unpack('<I', 0x3c)
    if data[pe:pe+4] != b'PE\0\0':
        raise ValueError('Missing PE signature')
    count, = unpack('<H', pe+6)
    optsize, = unpack('<H', pe+20)
    opt = pe+24
    magic, = unpack('<H', opt)
    if magic not in (0x10b, 0x20b):
        raise ValueError('Unsupported optional header')
    directory = opt + (112 if magic == 0x20b else 96)
    if directory + 24 > opt + optsize:
        raise ValueError('Missing resource directory slot')
    resource_rva, resource_size = unpack('<II', directory+16)
    if not resource_rva or not resource_size:
        return []
    sections = []
    for n in range(count):
        off = opt+optsize+40*n
        vsize, va, rawsize, raw = unpack('<IIII', off+8)
        sections.append((va, vsize, rawsize, raw))

    def rva_offset(rva, size):
        for va, vsize, rawsize, raw in sections:
            delta = rva-va
            if 0 <= delta and delta+size <= rawsize:
                pos = raw+delta
                if pos+size <= len(data):
                    return pos
        raise ValueError(f'Unmapped RVA: {rva:#x}, size {size}')

    base = rva_offset(resource_rva, resource_size)

    def resource_offset(relative, size):
        if relative < 0 or relative+size > resource_size:
            raise ValueError('Resource metadata outside directory')
        return base+relative

    leaves = []
    visited = set()

    def walk(relative, path):
        if len(path) > 8 or relative in visited or len(visited) >= 10000:
            raise ValueError('Resource directory cycle or excessive complexity')
        visited.add(relative)
        off = resource_offset(relative, 16)
        named, ids = unpack('<HH', off+12)
        resource_offset(relative+16, (named+ids)*8)
        for i in range(named+ids):
            name, target = unpack('<II', off+16+i*8)
            if name & 0x80000000:
                rel = name & 0x7fffffff
                textoff = resource_offset(rel, 2)
                length, = unpack('<H', textoff)
                textoff = resource_offset(rel+2, length*2)
                label = data[textoff:textoff+length*2].decode('utf-16le')
            else:
                label = name
            newpath = path+[label]
            if target & 0x80000000:
                walk(target & 0x7fffffff, newpath)
            else:
                leaf = resource_offset(target, 16)
                rva, size, codepage, reserved = unpack('<IIII', leaf)
                pos = rva_offset(rva, size)
                leaves.append((newpath, data[pos:pos+size]))
    walk(0, [])
    return leaves


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dll', type=Path)
    parser.add_argument('output', type=Path, help='New output directory; must not exist')
    args = parser.parse_args()
    data = args.dll.read_bytes()
    leaves = extract(data)
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'input_sha256': hashlib.sha256(data).hexdigest(), 'resources': []}
    for i, (path, blob) in enumerate(leaves):
        name = f'resource-{i:04d}.bin'
        (args.output/name).write_bytes(blob)
        report['resources'].append({'path': path, 'file': name, 'size': len(blob),
                                    'sha256': hashlib.sha256(blob).hexdigest(),
                                    'first_32_bytes': blob[:32].hex()})
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Extracted {len(leaves)} resources into {args.output}')


if __name__ == '__main__':
    main()
