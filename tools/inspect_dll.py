#!/usr/bin/env python3
"""Static string/hash triage only. Does not load or execute the supplied DLL."""
import argparse
import hashlib
import json
from pathlib import Path
import re


def inspect(path: Path) -> dict:
    data = path.read_bytes()
    if data[:2] != b'MZ':
        raise ValueError(f'Not an MZ/PE candidate: {path}')
    strings = set()
    for encoding, pattern in (
        ('ascii', rb'[\x20-\x7e]{6,}'),
        ('utf-16le', rb'(?:[\x20-\x7e]\x00){6,}'),
    ):
        strings.update(s.decode(encoding) for s in re.findall(pattern, data))
    functions = sorted({m.group(0) for s in strings for m in
                        re.finditer(r'_?INTC_(?:D3D12_)?[A-Za-z0-9_]+', s)})
    needles = ('igdext', 'fsr-original', '4.20.0', 'CM-SPIRV', 'CM-SPIR-V',
               'Stock fallback', 'diagnostic magenta', '4.0.2x', 'FSR 4.1.2',
               'OPTIONS1', 'OPTIONS2', 'root signature', 'production ABI')
    evidence = sorted(s for s in strings if any(n.lower() in s.lower() for n in needles))
    return {
        'path': str(path.resolve()),
        'size_bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
        'intel_api_strings': functions,
        'evidence_strings': evidence,
        'limitations': [
            'String presence does not prove execution or API requirements.',
            'This report does not prove Linux compatibility or GPU correctness.',
            'No code was loaded or executed from the input DLL.',
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dll', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.dll), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
