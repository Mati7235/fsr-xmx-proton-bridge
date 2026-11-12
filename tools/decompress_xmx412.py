#!/usr/bin/env python3
"""Batch-decode the six XMX 4.1.2 LZMS resource packs without executing the DLL.

Each pack 40101-40106 is a raw MS Compression API LZMS buffer (24-byte
header, algorithm 5, 64 KiB blocks) stored as RCDATA. The DLL loader
(FUN_180029640) resolves the pack by index, reads it with FindResourceW /
LoadResource / LockResource, decompresses it with Cabinet.dll
CreateDecompressor/Decompress/DestroyDecompressor, requires the output size
to equal the expected size exactly, and verifies a one-shot BCryptHash
SHA-256 (pseudo-handle 0x41) against a compiled-in 64-char hex digest.

This driver reuses decompress_mscf.decode (local libwim decompressor only;
the input DLL is never loaded) and fail-closes on any size/hash mismatch,
truncation, or trailing bytes. Standard library only besides libwim.
"""
import argparse
import hashlib
import json
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import decompress_mscf  # noqa: E402
import extract_resources  # noqa: E402
import parse_cm_payloads  # noqa: E402

SPIRV_MAGIC = b'\x03\x02\x23\x07'

# Pinned from the shipped 4.1.2 DLL (SHA-256
# fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732):
# loader immediates (resource ids, expected sizes) plus recomputed digests of
# the decoded packs, cross-checked against the ASCII hex digests compiled into
# the DLL and the MS Compression API header totals.
EXPECTED = {
    40101: {'index': 0, 'bucket': '18-variant DG2 (SIMD8 DPAS)',
            'res_size': 6107632,
            'res_sha256': '8e260219b64694f1d5aa6020632b0d107abff759f200a728b788aed454e9b9b5',
            'raw_size': 35346326,
            'raw_sha256': '4c63d10c83ed371b30a15ed563e560d0c977d473c7237b7f296e6d78aa88ab8d',
            'cm_envelopes': 252},
    40102: {'index': 1, 'bucket': '18-variant Xe2 (SIMD16 DPAS)',
            'res_size': 3856836,
            'res_sha256': '58557640463eeec42c0b9ea923d6b7462af2c38e97976be55c9e3501134d7651',
            'raw_size': 23682325,
            'raw_sha256': 'd88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491',
            'cm_envelopes': 252},
    40103: {'index': 2, 'bucket': 'FSR 4.1.2 Lite (DG2)',
            'res_size': 6960934,
            'res_sha256': '48963849d7b456256fb4e238353be436d6bb17b8385e8cb7857bb901f929f458',
            'raw_size': 42034337,
            'raw_sha256': 'a3731f5b65fb077e34a605e46931abb8988b9924989a1476fe29586ab70eb7d5',
            'cm_envelopes': 378},
    40104: {'index': 3, 'bucket': 'DLSS K (DG2 + Xe2/Xe3)',
            'res_size': 8031050,
            'res_sha256': '2c93c489f21415d4e8505b466669d529f1e397a4d0c9e6790acef326d9d25fa1',
            'raw_size': 42477193,
            'raw_sha256': 'a9ea6724ebe4079a29c819564baeb15815cbd2df15cf7d9752be80ac4e7054ea',
            'cm_envelopes': 716},
    40105: {'index': 4, 'bucket': 'DLSS E / F',
            'res_size': 3421152,
            'res_sha256': '4cff7b12f864d69abf851ae8e88883475116fe80f1ad7841b955d6f9e90acb2f',
            'raw_size': 19590261,
            'raw_sha256': '7ac547ee7bc0fce49b55036cad6993d41a42b1077aa911e6acff91b357d246fa',
            'cm_envelopes': 312},
    40106: {'index': 5, 'bucket': 'DLSS-MX (DG2)',
            'res_size': 1001522,
            'res_sha256': '579f610f8dba82752bdc130ed1de27b1abc4ff432f9963d419d038862d20b0de',
            'raw_size': 5443681,
            'raw_sha256': '03c188585417648a051d2b32258a0a6d554d58ab8969bdcc9c0919435a331ac3',
            'cm_envelopes': 67},
}


def check_header(data: bytes) -> tuple[int, int]:
    """Validate the 24-byte Compression API envelope header (stdlib only)."""
    if len(data) < 24 or data[:4] != b'\x0a\x51\xe5\xc0':
        raise ValueError('Not a Compression API buffer')
    header_size, checksum, algorithm = struct.unpack_from('<HBB', data, 4)
    total, unknown1, blocksize, unknown2 = struct.unpack_from('<IIII', data, 8)
    if header_size != 24 or algorithm != 5 or unknown1 or unknown2:
        raise ValueError('Unsupported Compression API header')
    if (zlib.crc32(data[7:24], zlib.crc32(data[:6])) & 255) != checksum:
        raise ValueError('Header CRC mismatch')
    if not 0 < total <= 128*1024*1024 or not 0 < blocksize <= 64*1024*1024:
        raise ValueError('Output/block size exceeds limits')
    return total, blocksize


def decode_and_verify(blob: bytes, meta: dict, libwim: Path) -> bytes:
    """Decompress one pack and fail closed on any size or digest mismatch."""
    if len(blob) != meta['res_size']:
        raise ValueError('Compressed size mismatch')
    if hashlib.sha256(blob).hexdigest() != meta['res_sha256']:
        raise ValueError('Compressed SHA-256 mismatch')
    total, _ = check_header(blob)
    if total != meta['raw_size']:
        raise ValueError('Header total differs from expected size')
    raw = decompress_mscf.decode(blob, libwim)
    if len(raw) != meta['raw_size']:
        raise ValueError('Decompressed size mismatch')
    if hashlib.sha256(raw).hexdigest() != meta['raw_sha256']:
        raise ValueError('Decompressed SHA-256 mismatch')
    records = parse_cm_payloads.parse(raw)
    if len(records) != meta['cm_envelopes']:
        raise ValueError(
            f"CM envelope count {len(records)} != expected {meta['cm_envelopes']}")
    return raw


def packs_from_dll(dll: bytes) -> dict[int, bytes]:
    """Select the six RCDATA packs from DLL bytes without loading the image."""
    found: dict[int, bytes] = {}
    for path, blob in extract_resources.extract(dll):
        if len(path) == 3 and path[0] == 10 and path[1] in EXPECTED and path[2] == 1033:
            if path[1] in found:
                raise ValueError(f'Duplicate resource {path[1]}')
            found[path[1]] = blob
    missing = sorted(set(EXPECTED) - set(found))
    if missing:
        raise ValueError(f'Missing RCDATA packs: {missing}')
    return found


def packs_from_resdir(resdir: Path) -> dict[int, bytes]:
    """Read packs via an extract_resources manifest (DLL itself untouched)."""
    manifest = json.loads((resdir/'manifest.json').read_bytes())
    found: dict[int, bytes] = {}
    for entry in manifest['resources']:
        rid = entry['path'][1] if len(entry['path']) == 3 else None
        if entry['path'][0] == 10 and rid in EXPECTED:
            blob = (resdir/entry['file']).read_bytes()
            if len(blob) != entry['size']:
                raise ValueError(f"Size drift in {entry['file']}")
            found[rid] = blob
    missing = sorted(set(EXPECTED) - set(found))
    if missing:
        raise ValueError(f'Missing RCDATA packs: {missing}')
    return found


def run(source: Path, outdir: Path, libwim: Path) -> dict:
    """Decode and verify every pack; write outputs only after each verifies."""
    if source.is_dir():
        packs = packs_from_resdir(source)
        origin = {'kind': 'resource-dir', 'path': str(source)}
    else:
        packs = packs_from_dll(source.read_bytes())
        origin = {'kind': 'dll', 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
    outdir.mkdir(parents=True, exist_ok=False)
    report_packs = []
    for rid in sorted(packs):
        meta = EXPECTED[rid]
        raw = decode_and_verify(packs[rid], meta, libwim)
        name = f'pack-{rid}.raw'
        (outdir/name).write_bytes(raw)
        report_packs.append({'resource_id': rid, 'index': meta['index'],
                             'bucket': meta['bucket'], 'file': name,
                             'res_size': len(packs[rid]),
                             'res_sha256': hashlib.sha256(packs[rid]).hexdigest(),
                             'raw_size': len(raw),
                             'raw_sha256': hashlib.sha256(raw).hexdigest(),
                             'spirv_magics': raw.count(SPIRV_MAGIC),
                             'cm_envelopes': len(parse_cm_payloads.parse(raw))})
    report = {'origin': origin, 'packs': report_packs,
              'method': ('MS Compression API LZMS via local libwim; sizes and '
                         'SHA-256 verified against loader pins; CM counts via '
                         'verified length footers. Input image never loaded.')}
    (outdir/'manifest.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path,
                        help='DLL file or resource dir with manifest.json')
    parser.add_argument('output', type=Path, help='New output directory')
    parser.add_argument('--libwim', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.source, args.output, args.libwim)
    for pack in report['packs']:
        print(f"{pack['resource_id']} {pack['bucket']}: "
              f"{pack['res_size']} -> {pack['raw_size']} bytes, "
              f"{pack['cm_envelopes']} CM envelopes")


if __name__ == '__main__':
    main()
