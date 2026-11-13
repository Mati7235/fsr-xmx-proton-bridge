import unittest

try:
    import numpy as np
    from tools.bench_quality import longest_run, luma, psnr, sharpness, ssim
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
class LongestRunTests(unittest.TestCase):
    def test_picks_the_longest_true_stretch(self):
        mask = [True, True, False, True, True, True, False, True]
        self.assertEqual(longest_run(mask), (3, 3))

    def test_all_true(self):
        self.assertEqual(longest_run([True] * 5), (0, 5))

    def test_all_false(self):
        self.assertEqual(longest_run([False] * 4), (0, 0))


@unittest.skipUnless(HAVE_DEPS, "numpy/Pillow not available")
class WindowTests(unittest.TestCase):
    def test_motion_score_is_zero_for_static_frames(self):
        from tools.bench_quality import motion_score
        frames = np.full((5, 9, 16), 128, dtype=np.uint8)
        self.assertTrue(np.allclose(motion_score(frames), 0.0))

    def test_motion_score_grows_with_change(self):
        from tools.bench_quality import motion_score
        frames = np.zeros((5, 9, 16), dtype=np.uint8)
        frames[1:] = 200
        self.assertGreater(float(motion_score(frames).mean()), 0.0)

    def test_best_window_prefers_the_moving_part(self):
        from tools.bench_quality import best_window
        mask = np.ones(20, dtype=bool)
        motion = np.zeros(19, dtype=np.float32)
        motion[10:17] = 5.0  # a moving stretch in the middle
        score, start, length = best_window(mask, motion, 7)
        self.assertEqual(length, 7)
        self.assertEqual(start, 10)
        self.assertAlmostEqual(score, 5.0, places=5)

    def test_best_window_returns_none_when_too_dissimilar(self):
        from tools.bench_quality import best_window
        mask = np.zeros(20, dtype=bool)
        motion = np.zeros(19, dtype=np.float32)
        self.assertIsNone(best_window(mask, motion, 5))


if __name__ == "__main__":
    unittest.main()
