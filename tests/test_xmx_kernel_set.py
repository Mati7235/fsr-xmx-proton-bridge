#!/usr/bin/env python3
"""Fail-closed tests for tools/xmx_kernel_set.py (synthetic logs only)."""
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOL = [sys.executable, str(Path(__file__).resolve().parent.parent
                            / "tools" / "xmx_kernel_set.py")]
HEADER = 472


def make_cmk(code: bytes) -> bytes:
    hdr = bytearray(HEADER)
    hdr[:4] = b"CMK2"
    struct.pack_into("<I", hdr, 4, len(code))
    return bytes(hdr) + code


def inj_line(name, nbytes=64, grf=128):
    return ("ANV CM: injected /home/matias/.cache/xess-xmx/kernels/%s "
            "(%d bytes code, %d GRF, lws 1,1,1)\n" % (name, nbytes, grf))


class XmxKernelSetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.kdir = Path(self.tmp.name) / "kernels"
        self.kdir.mkdir()
        self.codes = {
            "aaaa1111bbbb2222_e20b_142835e7.cmk": bytes(range(64)),
            "cccc3333dddd4444_e20b_142835e7.cmk": bytes([9]) * 64,
        }
        for name, code in self.codes.items():
            (self.kdir / name).write_bytes(make_cmk(code))

    def run_tool(self, *argv):
        return subprocess.run(TOOL + list(argv), capture_output=True,
                              text=True, timeout=60)

    def write_log(self, name, lines):
        p = Path(self.tmp.name) / name
        p.write_text("".join(lines), encoding="utf-8")
        return str(p)

    def fp(self, log, kdir=None):
        r = self.run_tool("fingerprint", log, kdir or str(self.kdir))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_fingerprint_deterministic(self):
        log = self.write_log("a.log", [
            "noise line\n",
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
            "ANV CM: placeholder wg 1,1,7 -> x (sets 2)\n",
            inj_line("cccc3333dddd4444_e20b_142835e7.cmk", grf=96),
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),  # dup
        ])
        fp1 = self.fp(log)
        fp2 = self.fp(log)
        self.assertEqual(fp1, fp2)
        lines = fp1.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines, sorted(lines))
        for entry in lines:
            parts = entry.split(":")
            self.assertEqual(len(parts), 3)
            self.assertEqual(len(parts[0]), 64)  # sha256 hex
            self.assertEqual(parts[1], "64")

    def test_diff_identical_exit_0(self):
        log = self.write_log("a.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
        ])
        fp = self.fp(log)
        fa = Path(self.tmp.name) / "fa.txt"
        fb = Path(self.tmp.name) / "fb.txt"
        fa.write_text(fp)
        fb.write_text(fp)
        r = self.run_tool("diff", str(fa), str(fb))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("COMUNES 1", r.stdout)
        self.assertIn("SOLO_A 0", r.stdout)
        self.assertIn("SOLO_B 0", r.stdout)

    def test_diff_one_kernel_differs_exit_1(self):
        log_a = self.write_log("a.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
            inj_line("cccc3333dddd4444_e20b_142835e7.cmk"),
        ])
        (self.kdir / "eeee5555ffff6666_e20b_0913d3f4.cmk").write_bytes(
            make_cmk(bytes([7]) * 64))
        log_b = self.write_log("b.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
            inj_line("eeee5555ffff6666_e20b_0913d3f4.cmk"),
        ])
        fa = Path(self.tmp.name) / "fa.txt"
        fb = Path(self.tmp.name) / "fb.txt"
        fa.write_text(self.fp(log_a))
        fb.write_text(self.fp(log_b))
        r = self.run_tool("diff", str(fa), str(fb))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("COMUNES 1", r.stdout)
        self.assertIn("SOLO_A 1", r.stdout)
        self.assertIn("SOLO_B 1", r.stdout)
        # The differing entries themselves must be listed.
        import hashlib
        gone = hashlib.sha256(self.codes[
            "cccc3333dddd4444_e20b_142835e7.cmk"]).hexdigest()
        new = hashlib.sha256(bytes([7]) * 64).hexdigest()
        self.assertIn(gone, r.stdout)
        self.assertIn(new, r.stdout)

    def test_missing_cmk_marked_no_crash(self):
        log = self.write_log("a.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
            inj_line("ffff9999ffff9999_e20b_142835e7.cmk"),
        ])
        r = self.run_tool("fingerprint", log, str(self.kdir))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("MISSING:ffff9999ffff9999", r.stdout)

    def test_diff_logs_mode(self):
        log_a = self.write_log("a.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
        ])
        log_b = self.write_log("b.log", [
            inj_line("aaaa1111bbbb2222_e20b_142835e7.cmk"),
        ])
        r = self.run_tool("diff", "--logs", log_a, log_b,
                          "--kernels-dir", str(self.kdir))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_usage_error_exit_2(self):
        r = self.run_tool("fingerprint", "/nonexistent.log", str(self.kdir))
        self.assertEqual(r.returncode, 2)
        r = self.run_tool("diff", "/nonexistent-a.txt", "/nonexistent-b.txt")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
