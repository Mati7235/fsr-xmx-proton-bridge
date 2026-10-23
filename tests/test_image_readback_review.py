import math
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from image_probe_reference import contract
from review_image_result import SENTINEL, check_readback


def fixture():
    data = bytearray(struct.pack('<2048I', *([SENTINEL] * 2048)))
    spec = contract()
    struct.pack_into('<64f', data, spec['output_heap_slot'] * 512, *spec['expected'])
    return data


class ImageReadbackTests(unittest.TestCase):
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
