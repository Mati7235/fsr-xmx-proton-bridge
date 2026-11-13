import unittest

try:
    import numpy as np
    from tools.bench_quality import luma, psnr, sharpness, ssim
    HAVE_DEPS = True
except ImportError:  # numpy/Pillow are optional analysis dependencies
    HAVE_DEPS = False


@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not available")
class MetricTests(unittest.TestCase):
    def test_psnr_identical_is_infinite(self):
        a = np.zeros((8, 8, 3), dtype=np.uint8)
        self.assertEqual(psnr(a, a), float("inf"))

    def test_psnr_known_value(self):
        a = np.zeros((4, 4, 3), dtype=np.uint8)
        b = np.full((4, 4, 3), 10, dtype=np.uint8)
        # mse = 100, peak = 255
        self.assertAlmostEqual(psnr(a, b), 10 * np.log10(255.0 ** 2 / 100), places=6)

    def test_ssim_identical_is_one(self):
        rng = np.random.default_rng(1)
        a = rng.integers(0, 255, (16, 16, 3), dtype=np.uint8)
        self.assertAlmostEqual(ssim(a, a), 1.0, places=9)

    def test_sharpness_orders_blur_before_detail(self):
        # Vertical stripes survive a horizontal box blur; a uniform image has none.
        stripes = np.zeros((32, 32, 3), dtype=np.uint8)
        stripes[:, ::2] = 255
        flat = np.full((32, 32, 3), 128, dtype=np.uint8)
        self.assertGreater(sharpness(stripes), sharpness(flat))
        self.assertEqual(sharpness(flat), 0.0)

    def test_luma_weights_green_most(self):
        green = np.zeros((1, 1, 3), dtype=np.uint8)
        green[0, 0, 1] = 255
        red = np.zeros((1, 1, 3), dtype=np.uint8)
        red[0, 0, 0] = 255
        self.assertGreater(float(luma(green)[0, 0]), float(luma(red)[0, 0]))


@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not available")
@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not available")
class AlignWindowTests(unittest.TestCase):
    def _frames(self, n, seed=0):
        rng = np.random.default_rng(seed)
        return rng.integers(0, 255, (n, 9, 16), dtype=np.uint8)

    def test_finds_zero_offset_for_identical_windows(self):
        from tools.bench_quality import align_windows
        ref = self._frames(30)
        alt = ref.copy()
        shift, err = align_windows(ref, 5, alt, 5, 20)
        self.assertEqual(shift, 0)
        self.assertAlmostEqual(err, 0.0, places=6)

    def test_finds_a_known_shift(self):
        from tools.bench_quality import align_windows
        ref = self._frames(40, seed=3)
        alt = ref.copy()
        shift, err = align_windows(ref, 10, alt, 13, 20)
        self.assertEqual(shift, -3)
        self.assertAlmostEqual(err, 0.0, places=6)

    def test_common_window_ignores_a_different_prefix(self):
        from tools.bench_quality import best_common_window
        ref = self._frames(100, seed=1)
        alt = np.concatenate([self._frames(20, seed=2), ref[10:60]])
        value, ref_start, offset = best_common_window(ref, alt, 40)
        self.assertEqual(ref_start, 10)
        # alt has 20 frames of menu before the same footage: alt index = ref index + 10
        self.assertEqual(offset, 10)
        self.assertAlmostEqual(value, 0.0, places=6)

    def test_common_window_ignores_a_different_suffix(self):
        from tools.bench_quality import best_common_window
        ref = self._frames(100, seed=4)
        alt = np.concatenate([ref[20:70], self._frames(30, seed=5)])
        value, ref_start, offset = best_common_window(ref, alt, 40)
        self.assertEqual(ref_start, 20)
        self.assertEqual(offset, -20)
        self.assertAlmostEqual(value, 0.0, places=6)

    def test_best_offset_is_zero_when_the_window_centers_on_the_frame(self):
        from tools.bench_quality import best_offset
        seq = (np.arange(21 * 9 * 16, dtype=np.uint8) % 251).reshape(21, 9, 16)
        radius = 10 / 60
        self.assertAlmostEqual(best_offset(seq[10], seq, 60, radius), 0.0, places=6)

    def test_best_offset_reports_a_lagging_alt(self):
        from tools.bench_quality import best_offset
        seq = (np.arange(21 * 9 * 16, dtype=np.uint8) % 251).reshape(21, 9, 16)
        radius = 10 / 60
        # alt window starts 8 frames before the reference frame: best k = 2
        self.assertAlmostEqual(best_offset(seq[10], seq[8:19], 60, radius),
                               2 / 60 - radius, places=6)

    def test_best_offset_is_positive_when_the_match_is_after_the_center(self):
        from tools.bench_quality import best_offset
        seq = (np.arange(21 * 9 * 16, dtype=np.uint8) % 251).reshape(21, 9, 16)
        radius = 5 / 60
        # the match sits at k = 10, after a 5-frame radius: positive offset
        self.assertAlmostEqual(best_offset(seq[10], seq[0:11], 60, radius),
                               10 / 60 - radius, places=6)

    def test_common_window_prefers_the_matching_stretch(self):
        from tools.bench_quality import best_common_window
        ref = self._frames(120, seed=6)
        # same footage, but alt is dark for a while, as the menu is
        alt = (ref[30:110] // 3).astype(np.uint8)
        value, ref_start, offset = best_common_window(ref, alt, 40)
        self.assertEqual(offset, -30)
        self.assertGreaterEqual(ref_start, 30)
        self.assertLessEqual(ref_start + 40, 110)


if __name__ == "__main__":
    unittest.main()
