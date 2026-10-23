import math
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from image_probe_reference import contract
from review_image_result import SENTINEL, check_readback
import review_image_result


def fixture():
    data = bytearray(struct.pack('<2048I', *([SENTINEL] * 2048)))
    spec = contract()
    struct.pack_into('<64f', data, spec['output_heap_slot'] * 512, *spec['expected'])
    return data


class ImageReadbackTests(unittest.TestCase):
    def test_review_requires_injection_logs_even_when_raw_bytes_are_correct(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            manifest = path / 'manifest.json'
            manifest.write_text(json.dumps({'kind': contract()['kind']}))
            (path / 'anv_canary').write_text('patched ANV')
            (path / 'canary-evidence.txt').write_text(
                'buffer 0 word 0 is 0x584d5843; every other word in all 16 buffers remains sentinel')
            (path / 'image-readback.bin').write_bytes(fixture())
            (path / 'probe-driver.log').write_text('no injection')
            with mock.patch('review_image_result.verify_manifest'):
                with self.assertRaisesRegex(ValueError, 'injection evidence'):
                    review_image_result.review(path, manifest)
                (path / 'probe-driver.log').write_text(
                    'ANV CM: injected /local/wg2_1_5.cmk (code)\n'
                    'ANV CM: dispatch kernel 2,1,5 idx: 3 7\n'
                    'ANV CM: heap set 0 binding 0: descriptor offset 0 stride 64 (set layout type 2)\n')
                result = review_image_result.review(path, manifest)
                self.assertEqual(result['checked_float_values'], 64)
                self.assertFalse(result['fsr_validated'])

    def test_exact_oracle_and_guards(self):
        result = check_readback(fixture())
        self.assertEqual(result['checked_float_values'], 64)
        self.assertEqual(result['checked_sentinel_words'], 1984)
        self.assertEqual(result['maximum_absolute_error'], 0.)

    def test_wrong_size_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'exactly'):
            check_readback(fixture()[:-1])

    def test_noop_and_wrong_output_are_rejected(self):
        data = fixture()
        struct.pack_into('<f', data, 7 * 512, 0.)
        with self.assertRaisesRegex(ValueError, 'Output index'):
            check_readback(data)

    def test_nan_does_not_silently_pass_tolerance(self):
        data = fixture()
        struct.pack_into('<f', data, 7 * 512, math.nan)
        with self.assertRaises(ValueError):
            check_readback(data)

    def test_output_tail_and_other_slots_are_checked_bitwise(self):
        for index in (7 * 128 + 64, 3 * 128, 15 * 128 + 127):
            data = fixture()
            struct.pack_into('<I', data, index * 4, 0)
            with self.assertRaisesRegex(ValueError, 'Sentinel changed'):
                check_readback(data)


if __name__ == '__main__':
    unittest.main()
