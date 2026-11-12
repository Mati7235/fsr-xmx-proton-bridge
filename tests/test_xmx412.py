"""Synthetic and pinned tests for the XMX 4.1.2 LZMS pack decoder.

No proprietary DLL is required except for the gated local-artifact case.
No GPU, Wine, or image execution is involved.
"""
import hashlib
import importlib.util
import struct
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xmx = load('decompress_xmx412')
mscf = load('decompress_mscf')

LIBWIM = ROOT/'upstream/wimlib/.libs/libwim.so'
RESDIR = Path('/tmp/opencode/xmx-new/res412')


def stored_buffer(payload: bytes, blocksize: int = 65536) -> bytes:
    """Minimal valid Compression API LZMS buffer using one stored chunk."""
    header = bytearray(24)
    header[:4] = b'\x0a\x51\xe5\xc0'
    struct.pack_into('<H', header, 4, 24)
    struct.pack_into('<B', header, 7, 5)
    struct.pack_into('<IIII', header, 8, len(payload), 0, blocksize, 0)
    header[6] = zlib.crc32(bytes(header[7:24]), zlib.crc32(bytes(header[:6]))) & 255
    return bytes(header)+struct.pack('<I', len(payload))+payload


class HeaderTests(unittest.TestCase):
    def test_valid_header_reports_total(self):
        total, block = xmx.check_header(stored_buffer(b'ABCDEFGH'))
        self.assertEqual((total, block), (8, 65536))

    def test_reject_magic(self):
        with self.assertRaises(ValueError):
            xmx.check_header(b'\x00'*24)

    def test_reject_algorithm(self):
        buf = bytearray(stored_buffer(b'ABCDEFGH'))
        buf[7] = 4
        buf[6] = zlib.crc32(bytes(buf[7:24]), zlib.crc32(bytes(buf[:6]))) & 255
        with self.assertRaises(ValueError):
            xmx.check_header(bytes(buf))

    def test_reject_crc(self):
        buf = bytearray(stored_buffer(b'ABCDEFGH'))
        buf[6] ^= 0xff
        with self.assertRaises(ValueError):
            xmx.check_header(bytes(buf))

    def test_reject_truncated(self):
        with self.assertRaises(ValueError):
            xmx.check_header(stored_buffer(b'ABCDEFGH')[:20])


class PinTableTests(unittest.TestCase):
    def test_six_packs_cover_40101_40106(self):
        self.assertEqual(sorted(xmx.EXPECTED), [40101, 40102, 40103, 40104, 40105, 40106])

    def test_pins_are_wellformed(self):
        buckets = set()
        for rid, meta in xmx.EXPECTED.items():
            self.assertEqual(meta['index'], rid-40101)
            self.assertTrue(meta['bucket'] and meta['bucket'] not in buckets)
            buckets.add(meta['bucket'])
            self.assertGreater(meta['res_size'], 0)
            self.assertGreater(meta['raw_size'], 0)
            for key in ('res_sha256', 'raw_sha256'):
                self.assertRegex(meta[key], r'^[0-9a-f]{64}$')
            self.assertGreater(meta['cm_envelopes'], 0)

    def test_expected_totals_match_cm_survey(self):
        self.assertEqual(sum(m['cm_envelopes'] for m in xmx.EXPECTED.values()),
                         252+252+378+716+312+67)

    def test_compressed_size_mismatch_is_fail_closed(self):
        meta = dict(xmx.EXPECTED[40101])
        with self.assertRaises(ValueError):
            xmx.decode_and_verify(b'short', meta, LIBWIM)

    def test_compressed_hash_mismatch_is_fail_closed(self):
        meta = dict(xmx.EXPECTED[40101])
        meta['res_size'] = 5
        with self.assertRaises(ValueError):
            xmx.decode_and_verify(b'wrong', meta, LIBWIM)


@unittest.skipUnless(LIBWIM.exists(), 'Local libwim build is not present')
class StoredRoundTripTests(unittest.TestCase):
    def test_stored_chunk_decodes_without_proprietary_data(self):
        payload = b'ABCDEFGH'
        self.assertEqual(mscf.decode(stored_buffer(payload), LIBWIM), payload)

    def test_trailing_bytes_rejected(self):
        with self.assertRaises(ValueError):
            mscf.decode(stored_buffer(b'ABCDEFGH')+b'\x00', LIBWIM)

    def test_truncated_chunk_rejected(self):
        with self.assertRaises(ValueError):
            mscf.decode(stored_buffer(b'ABCDEFGH')[:-1], LIBWIM)

    def test_mutated_payload_changes_digest(self):
        raw = mscf.decode(stored_buffer(b'ABCDEFGH'), LIBWIM)
        self.assertNotEqual(hashlib.sha256(raw).hexdigest(),
                            hashlib.sha256(b'ABCDEFGg').hexdigest())


@unittest.skipUnless(RESDIR.is_dir() and LIBWIM.exists(),
                     'Optional local 4.1.2 resources are not present')
class LocalArtifactTests(unittest.TestCase):
    def test_pinned_sizes_hashes_and_counts(self):
        packs = xmx.packs_from_resdir(RESDIR)
        self.assertEqual(sorted(packs), [40101, 40102, 40103, 40104, 40105, 40106])
        for rid, blob in packs.items():
            meta = xmx.EXPECTED[rid]
            raw = xmx.decode_and_verify(blob, meta, LIBWIM)
            self.assertEqual(len(raw), meta['raw_size'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), meta['raw_sha256'])
            self.assertGreater(raw.count(xmx.SPIRV_MAGIC), 0)


if __name__ == '__main__':
    unittest.main()
