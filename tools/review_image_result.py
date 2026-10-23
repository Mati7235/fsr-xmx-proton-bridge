#!/usr/bin/env python3
"""Independently check captured synthetic image-probe bytes using CPU only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from image_probe_reference import contract
from prepare_lab_test import verify_manifest


SENTINEL = 0xa5c39e71
WORDS_PER_BUFFER = 128
BUFFER_COUNT = 16


def check_readback(data):
    spec = contract()
    if len(data) != BUFFER_COUNT * WORDS_PER_BUFFER * 4:
        raise ValueError('Readback must contain exactly 16 buffers of 128 uint32 words')
    words = struct.unpack('<2048I', data)
    values = struct.unpack_from('<64f', data, spec['output_heap_slot'] * WORDS_PER_BUFFER * 4)
    maximum_error = 0.
    for lane, (actual, expected) in enumerate(zip(values, spec['expected'])):
        if not math.isfinite(actual) or abs(actual - expected) > spec['absolute_tolerance']:
            raise ValueError(f'Output index {lane}: got {actual}, expected {expected}')
        maximum_error = max(maximum_error, abs(actual - expected))
    for index, word in enumerate(words):
        slot, offset = divmod(index, WORDS_PER_BUFFER)
        if slot == spec['output_heap_slot'] and offset < len(values):
            continue
        if word != SENTINEL:
            raise ValueError(f'Sentinel changed at buffer {slot}, word {offset}')
    return {'checked_float_values': len(values), 'maximum_absolute_error': maximum_error,
            'checked_sentinel_words': len(words) - len(values),
            'raw_readback_sha256': hashlib.sha256(data).hexdigest()}


def review(evidence_dir, manifest_path):
    evidence = Path(evidence_dir)
    manifest = json.loads(Path(manifest_path).read_text())
    if manifest.get('kind') != contract()['kind']:
        raise ValueError('Not a prepared synthetic image/sampler manifest')
    verify_manifest(manifest)
    if 'patched ANV' not in (evidence / 'anv_canary').read_text():
        raise ValueError('Missing patched ANV canary recognition')
    log = (evidence / 'probe-driver.log').read_text()
    if not re.search(r'ANV CM: injected .*wg2_1_5\.cmk\b', log):
        raise ValueError('Missing image kernel injection evidence')
    if not re.search(r'ANV CM: dispatch kernel 2,1,5 idx:\s+3\s+7\s*(?:\n|$)', log):
        raise ValueError('Missing expected image/output descriptor-map dispatch')
    if not re.search(r'heap set 0 binding 0: descriptor offset \d+ stride [1-9]\d* \(set layout type 2\)', log):
        raise ValueError('Missing DIRECT heap evidence')
    result = check_readback((evidence / 'image-readback.bin').read_bytes())
    result.update({'mode': 'CPU-only-review-of-user-captured-evidence',
                   'kind': contract()['kind'], 'evidence_dir': str(evidence.resolve()),
                   'injection_and_descriptor_log_checked': True,
                   'current_artifacts_match_preparation': True,
                   'fsr_validated': False})
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, help='New JSON output, never overwritten')
    args = parser.parse_args(argv)
    try:
        result = review(args.evidence_dir, args.manifest)
        text = json.dumps(result, indent=2) + '\n'
        if args.out:
            with args.out.open('x') as stream:
                stream.write(text)
        print(text, end='')
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'blocked: {exc}\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
