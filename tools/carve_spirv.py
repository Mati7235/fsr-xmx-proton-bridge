#!/usr/bin/env python3
"""Heuristic SPIR-V carving from decompressed packs, not a container parser.

Candidates must start at a magic signature, have a bounded instruction stream,
contain an entry point and end on OpFunctionEnd. A manifest records offsets and
unparsed gaps; extracted modules still need external validation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

MAGIC = b'\x03\x02\x23\x07'


def carve(data: bytes) -> list[dict]:
    offsets = [m.start() for m in re.finditer(re.escape(MAGIC), data)]
    found = []
    for index, start in enumerate(offsets):
        limit = offsets[index+1] if index+1 < len(offsets) else len(data)
        if start+20 > limit:
            continue
        magic, version, generator, bound, schema = struct.unpack_from('<5I', data, start)
        if schema != 0 or not bound or not 0x10000 <= version <= 0x10600:
            continue
        pos = start+20
        last_op = None
        entries = []
        modes = []
        while pos+4 <= limit:
            word, = struct.unpack_from('<I', data, pos)
            count, opcode = word >> 16, word & 0xffff
            if count == 0 or pos+count*4 > limit:
                break
            if opcode == 15 and count >= 4:
                model, entry_id = struct.unpack_from('<II', data, pos+4)
                rawname = data[pos+12:pos+count*4].split(b'\0', 1)[0]
                entries.append({'model': model, 'id': entry_id,
                                'name': rawname.decode('utf-8', errors='replace')})
            if opcode == 16 and count >= 3:
                args = struct.unpack_from(f'<{count-1}I', data, pos+4)
                modes.append({'entry_id': args[0], 'mode': args[1], 'operands': list(args[2:])})
            last_op = opcode
            pos += count*4
        if last_op != 56 or not entries:
            continue
        blob = data[start:pos]
        gap = data[pos:limit]
        found.append({'offset': start, 'size': len(blob),
                      'sha256': hashlib.sha256(blob).hexdigest(),
                      'version_word': version, 'entries': entries, 'execution_modes': modes,
                      'gap_size': len(gap),
                      'gap_ascii_strings': [s.decode() for s in re.findall(rb'[\x20-\x7e]{5,}', gap)],
                      'blob': blob})
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pack', type=Path)
    parser.add_argument('output', type=Path, help='New directory; must not exist')
    args = parser.parse_args()
    data = args.pack.read_bytes()
    candidates = carve(data)
    args.output.mkdir(parents=True, exist_ok=False)
    manifest = {'input_sha256': hashlib.sha256(data).hexdigest(),
                'method': 'heuristic instruction walk, not verified container offsets',
                'modules': []}
    for i, candidate in enumerate(candidates):
        blob = candidate.pop('blob')
        filename = f'module-{i:04d}.spv'
        (args.output/filename).write_bytes(blob)
        candidate['file'] = filename
        manifest['modules'].append(candidate)
    (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(f'Carved {len(candidates)} candidate modules into {args.output}')


if __name__ == '__main__':
    main()
