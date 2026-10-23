import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from image_probe_reference import TEXELS, contract, sample_linear_clamp


class ImageReferenceTests(unittest.TestCase):
    def test_texel_centers_return_exact_texels(self):
        for i, (u, v) in enumerate(((.25, .25), (.75, .25), (.25, .75), (.75, .75))):
            self.assertEqual(sample_linear_clamp(TEXELS, 2, 2, u, v), TEXELS[i])

    def test_middle_is_mean_of_all_four_texels(self):
        self.assertEqual(sample_linear_clamp(TEXELS, 2, 2, .5, .5), (7., 8., 9., 10.))

    def test_clamp_outside_all_edges(self):
        self.assertEqual(sample_linear_clamp(TEXELS, 2, 2, -1., -1.), TEXELS[0])
        self.assertEqual(sample_linear_clamp(TEXELS, 2, 2, 2., 2.), TEXELS[3])
        self.assertEqual(sample_linear_clamp(TEXELS, 2, 2, -1., .5), (5., 6., 7., 8.))

    def test_channel_major_contract(self):
        spec = contract()
        self.assertEqual(len(spec['expected']), 64)
        self.assertEqual(spec['expected'][:5], [1., 5., 9., 13., 7.])
        self.assertEqual(spec['expected'][16:21], [2., 6., 10., 14., 8.])
        self.assertFalse(spec['gpu_validated'])

    def test_invalid_image_or_coordinates_rejected(self):
        for width, height in ((0, 2), (2, -1), (2.0, 2)):
            with self.assertRaises(ValueError):
                sample_linear_clamp(TEXELS, width, height, 0., 0.)
        for u, v in ((math.nan, 0.), (0., math.inf)):
            with self.assertRaises(ValueError):
                sample_linear_clamp(TEXELS, 2, 2, u, v)
        with self.assertRaises(ValueError):
            sample_linear_clamp(TEXELS[:2], 2, 2, 0., 0.)


if __name__ == '__main__':
    unittest.main()
