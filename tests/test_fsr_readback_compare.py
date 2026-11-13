"""Fail-closed tests for tools/fsr_readback_compare.py (CPU only, no GPU)."""
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parents[1] / "tools" / "fsr_readback_compare.py"

PURE_ENV = dict(os.environ, FSR_READBACK_NO_NUMPY="1")


def run_tool(*argv, env=None):
    proc = subprocess.run(
        [sys.executable, str(TOOL), *argv],
        capture_output=True, text=True, env=env, timeout=300)
    return proc.returncode, proc.stdout, proc.stderr


def both_modes(test):
    """Run the same CLI scenario with numpy fast path and pure fallback."""

    def wrapper(self):
        for env in (None, PURE_ENV):
            with self.subTest(numpy="off" if env else "on"):
                test(self, env)

    return wrapper


def write_tmp(directory, name, payload):
    path = Path(directory) / name
    path.write_bytes(payload)
    return path


def pack_f32(values):
    return struct.pack("<%df" % len(values), *values)


class DiffTests(unittest.TestCase):
    @both_modes
    def test_self_diff_is_identical(self, env):
        with tempfile.TemporaryDirectory() as directory:
            blob = pack_f32([0.1 * i for i in range(64)])
            path = write_tmp(directory, "a.bin", blob)
            code, out, _ = run_tool("diff", str(path), str(path), env=env)
            self.assertEqual(code, 0)
            self.assertIn("identical", out.lower().replace("true", "true"))
            self.assertIn("True", out)

    @both_modes
    def test_single_change_reports_index_and_coord(self, env):
        with tempfile.TemporaryDirectory() as directory:
            # 4x2 rgba32f: 8 pixels, 32 floats; change float index 9
            # (pixel 2 -> x=2 y=0, channel 1).
            width, height = 4, 2
            base = [float(i) for i in range(width * height * 4)]
            changed = list(base)
            changed[9] = 123.5
            pa = write_tmp(directory, "a.bin", pack_f32(base))
            pb = write_tmp(directory, "b.bin", pack_f32(changed))
            args = ["diff", str(pa), str(pb), "--format", "rgba32f",
                    "--width", str(width), "--height", str(height)]
            code, out, _ = run_tool(*args, env=env)
            self.assertEqual(code, 1)
            self.assertIn("identical: False", out)
            self.assertIn("different_values: 1 of 32", out)
            self.assertIn("diff 9:", out)
            self.assertIn("x=2 y=0 c=1", out)
            self.assertIn("b=123.5", out)

    @both_modes
    def test_tolerance_accepts_small_change(self, env):
        with tempfile.TemporaryDirectory() as directory:
            base = [1.0] * 16
            changed = list(base)
            changed[5] = 1.0 + 1e-4
            pa = write_tmp(directory, "a.bin", pack_f32(base))
            pb = write_tmp(directory, "b.bin", pack_f32(changed))
            code, _, _ = run_tool("diff", str(pa), str(pb), env=env)
            self.assertEqual(code, 1)  # bits differ, no tolerance
            code, out, _ = run_tool(
                "diff", str(pa), str(pb), "--tolerance", "0.01", env=env)
            self.assertEqual(code, 0)
            self.assertIn("within_tolerance: True", out)
            code, _, _ = run_tool(
                "diff", str(pa), str(pb), "--tolerance", "1e-9", env=env)
            self.assertEqual(code, 1)

    def test_size_mismatch_is_error_exit_2(self):
        with tempfile.TemporaryDirectory() as directory:
            pa = write_tmp(directory, "a.bin", pack_f32([0.0] * 8))
            pb = write_tmp(directory, "b.bin", pack_f32([0.0] * 4))
            code, _, err = run_tool("diff", str(pa), str(pb))
            self.assertEqual(code, 2)
            self.assertIn("size mismatch", err)


class InspectTests(unittest.TestCase):
    @both_modes
    def test_nan_inf_counts(self, env):
        with tempfile.TemporaryDirectory() as directory:
            # 2x2 r32f: [1.0, nan, +inf, -inf]
            blob = struct.pack("<4f", 1.0, math.nan, math.inf, -math.inf)
            path = write_tmp(directory, "d.bin", blob)
            code, out, _ = run_tool(
                "inspect", str(path), "--format", "r32f",
                "--width", "2", "--height", "2", env=env)
            self.assertEqual(code, 0)
            self.assertIn("nan: 1", out)
            self.assertIn("posinf: 1", out)
            self.assertIn("neginf: 1", out)
            self.assertIn("finite: 1", out)
            self.assertIn("min: 1.0", out)
            self.assertIn("max: 1.0", out)

    def test_wrong_size_exits_2(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_tmp(directory, "d.bin", b"\x00" * 15)
            code, _, err = run_tool(
                "inspect", str(path), "--format", "r32f",
                "--width", "2", "--height", "2")
            self.assertEqual(code, 2)
            self.assertIn("size mismatch", err)

    def test_bad_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_tmp(directory, "d.bin", b"\x00" * 16)
            code, _, err = run_tool(
                "inspect", str(path), "--format", "bogus",
                "--width", "2", "--height", "2")
            self.assertEqual(code, 2)
            self.assertIn("unsupported format", err)

    @both_modes
    def test_per_channel_means(self, env):
        with tempfile.TemporaryDirectory() as directory:
            # 2x1 rg32f: R=[1,3] G=[2,4]
            blob = pack_f32([1.0, 2.0, 3.0, 4.0])
            path = write_tmp(directory, "d.bin", blob)
            code, out, _ = run_tool(
                "inspect", str(path), "--format", "rg32f",
                "--width", "2", "--height", "1", env=env)
            self.assertEqual(code, 0)
            self.assertIn("mean_R: 2.0", out)
            self.assertIn("mean_G: 3.0", out)

    @both_modes
    def test_stride_padding(self, env):
        with tempfile.TemporaryDirectory() as directory:
            # 2x2 r32f with 4 pad bytes per row: stride 12.
            blob = (pack_f32([1.0, 2.0]) + b"\x00" * 4
                    + pack_f32([3.0, 4.0]) + b"\x00" * 4)
            path = write_tmp(directory, "d.bin", blob)
            code, out, _ = run_tool(
                "inspect", str(path), "--format", "r32f",
                "--width", "2", "--height", "2", "--stride", "12", env=env)
            self.assertEqual(code, 0)
            self.assertIn("mean: 2.5", out)


class MetricsTests(unittest.TestCase):
    @both_modes
    def test_identical_gives_inf_psnr_and_unit_ssim(self, env):
        with tempfile.TemporaryDirectory() as directory:
            vals = [0.05 * (i % 17) for i in range(16 * 16 * 3)]
            blob = pack_f32(vals)
            pc = write_tmp(directory, "c.bin", blob)
            pr = write_tmp(directory, "r.bin", blob)
            code, out, _ = run_tool(
                "metrics", str(pc), str(pr), "--format", "rgb32f",
                "--width", "16", "--height", "16", env=env)
            self.assertEqual(code, 0)
            self.assertIn("psnr_db: inf", out)
            self.assertIn("ssim: 1.0", out)
            self.assertNotIn("nan", out.lower().split("ssim_window")[1])

    @both_modes
    def test_noise_gives_finite_lower_scores(self, env):
        with tempfile.TemporaryDirectory() as directory:
            ref = [0.5 + 0.01 * ((i * 7919) % 23) for i in range(16 * 16)]
            cand = [v + (0.02 if i % 2 else -0.02) for i, v in enumerate(ref)]
            pr = write_tmp(directory, "r.bin", pack_f32(ref))
            pc = write_tmp(directory, "c.bin", pack_f32(cand))
            code, out, _ = run_tool(
                "metrics", str(pc), str(pr), "--format", "r32f",
                "--width", "16", "--height", "16", env=env)
            self.assertEqual(code, 0)
            psnrs = [float(line.split(":")[1])
                     for line in out.splitlines() if "psnr_db" in line]
            ssims = [float(line.split(":")[1])
                     for line in out.splitlines() if "ssim:" in line]
            self.assertTrue(psnrs, out)
            self.assertTrue(ssims, out)
            for p in psnrs:
                self.assertTrue(math.isfinite(p), out)
                self.assertLess(p, 60.0, out)
            for s in ssims:
                self.assertLess(s, 1.0, out)
                self.assertGreater(s, 0.5, out)

    def test_nan_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ref = pack_f32([0.5] * 16)
            cand = pack_f32([0.5] * 15 + [math.nan])
            pr = write_tmp(directory, "r.bin", ref)
            pc = write_tmp(directory, "c.bin", cand)
            code, _, err = run_tool(
                "metrics", str(pc), str(pr), "--format", "r32f",
                "--width", "4", "--height", "4")
            self.assertEqual(code, 2)
            self.assertIn("NaN", err)

    def test_inf_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            ref = pack_f32([0.5] * 15 + [math.inf])
            cand = pack_f32([0.5] * 16)
            pr = write_tmp(directory, "r.bin", ref)
            pc = write_tmp(directory, "c.bin", cand)
            code, _, err = run_tool(
                "metrics", str(pc), str(pr), "--format", "r32f",
                "--width", "4", "--height", "4")
            self.assertEqual(code, 2)
            self.assertIn("Inf", err)


class ConsistencyTests(unittest.TestCase):
    def test_numpy_and_pure_modes_agree(self):
        import random
        random.seed(1234)
        width, height = 32, 24
        ref = [random.random() for _ in range(width * height * 3)]
        cand = [v + random.gauss(0, 0.01) for v in ref]
        with tempfile.TemporaryDirectory() as directory:
            pr = write_tmp(directory, "r.bin", pack_f32(ref))
            pc = write_tmp(directory, "c.bin", pack_f32(cand))
            outs = []
            for env in (None, PURE_ENV):
                code, out, _ = run_tool(
                    "metrics", str(pc), str(pr), "--format", "rgb32f",
                    "--width", str(width), "--height", str(height), env=env)
                self.assertEqual(code, 0)
                outs.append(out)
        nums = []
        for out in outs:
            row = {}
            for line in out.splitlines():
                if ": " in line and line.split(":")[0].endswith(
                        ("mse", "psnr_db", "ssim")):
                    key, val = line.split(":", 1)
                    row[key.strip()] = float(val)
            nums.append(row)
        self.assertEqual(set(nums[0]), set(nums[1]))
        for key in nums[0]:
            self.assertAlmostEqual(nums[0][key], nums[1][key], places=9,
                                   msg=key)


class PerfTests(unittest.TestCase):
    def test_1080p_r32f_inspect_and_diff_stay_fast(self):
        # 1920x1080 r32f is ~8 MB; must not blow memory or take minutes.
        width, height = 1920, 1080
        n = width * height
        with tempfile.TemporaryDirectory() as directory:
            blob = pack_f32([0.25] * n)
            pa = write_tmp(directory, "a.bin", blob)
            start = time.monotonic()
            code, out, _ = run_tool(
                "inspect", str(pa), "--format", "r32f",
                "--width", str(width), "--height", str(height))
            inspect_secs = time.monotonic() - start
            self.assertEqual(code, 0)
            self.assertIn("mean: 0.25", out)
            start = time.monotonic()
            code, out, _ = run_tool("diff", str(pa), str(pa))
            diff_secs = time.monotonic() - start
            self.assertEqual(code, 0)
            self.assertIn("identical: True", out)
            self.assertLess(inspect_secs, 90.0)
            self.assertLess(diff_secs, 90.0)


if __name__ == "__main__":
    unittest.main()
