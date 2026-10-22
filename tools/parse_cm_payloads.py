#!/usr/bin/env python3
"""Recover CM compiler payload envelopes using their verified length footers.

This is not a full pack parser: raw weights, DXBC and padding are reported as gaps.
No input code is executed. The two embedded strings are not INTC API arguments.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

MARKER = b'-vc-payload'
SPIRV = b'\x03\x02\x23\x07'


def parse(data: bytes) -> list[dict]:
    results = []
    for match in re.finditer(re.escape(MARKER), data):
        marker = match.start()
        if marker < 16:
            continue
        ir_size, trailer_size = struct.unpack_from('<QQ', data, marker-16)
        end = match.end()
        start = end-trailer_size-ir_size
        if not 27 <= trailer_size <= 4096 or ir_size < 20 or start < 0:
            continue
        ir_end = start+ir_size
        if ir_end > marker-16 or data[start:start+4] != SPIRV:
            continue
        raw_options = data[ir_end:marker-16]
        if raw_options.count(b'\0') != 2 or not raw_options.endswith(b'\0'):
            continue
        try:
            options = [s.decode('ascii') for s in raw_options[:-1].split(b'\0')]
        except UnicodeDecodeError:
            continue
        if any(ord(c) < 32 or ord(c) > 126 for s in options for c in s):
            continue
        if results and start < results[-1]['end']:
            raise ValueError('Overlapping CM payload envelopes')
        results.append({'offset': start, 'ir_size': ir_size, 'trailer_size': trailer_size,
                        'envelope_size': end-start, 'end': end,
                        'embedded_string_a': options[0], 'embedded_string_b': options[1],
                        'ir_sha256': hashlib.sha256(data[start:ir_end]).hexdigest(),
                        'envelope_sha256': hashlib.sha256(data[start:end]).hexdigest()})
    return results


def gaps(data: bytes, records: list[dict]) -> list[dict]:
    result = []
    pos = 0
    for record in records+[{'offset': len(data), 'end': len(data)}]:
        if record['offset'] > pos:
            blob = data[pos:record['offset']]
            dxbc = []
            for m in re.finditer(b'DXBC', blob):
                at = m.start()
                if at+32 <= len(blob):
                    size, chunks = struct.unpack_from('<II', blob, at+24)
                    if 32+4*chunks <= size <= len(blob)-at:
                        dxbc.append({'offset': pos+at, 'declared_size': size, 'chunks': chunks})
            result.append({'offset': pos, 'size': len(blob), 'all_zero': not any(blob),
                           'sha256': hashlib.sha256(blob).hexdigest(), 'dxbc_candidates': dxbc})
        pos = record['end']
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pack', type=Path)
    p.add_argument('output', type=Path, help='New output directory')
    args = p.parse_args()
    data = args.pack.read_bytes()
    records = parse(data)
    args.output.mkdir(parents=True, exist_ok=False)
    for i, record in enumerate(records):
        start, end = record['offset'], record['end']
        ir = data[start:start+record['ir_size']]
        name = f'module-{i:04d}'
        (args.output/f'{name}.spv').write_bytes(ir)
        (args.output/f'{name}.cmspv').write_bytes(data[start:end])
        record['ir_file'] = f'{name}.spv'
        record['envelope_file'] = f'{name}.cmspv'
    report = {'input_sha256': hashlib.sha256(data).hexdigest(),
              'records': records, 'gaps': gaps(data, records),
              'limitations': ['Embedded strings are not proof of non-NULL INTC API option pointers.',
                              'Non-CM records and gap contents are not fully parsed.']}
    (args.output/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f'Recovered {len(records)} CM payloads into {args.output}')


if __name__ == '__main__':
    main()
