"""CPU-only verification of the minimal game-local cabinet.dll substitute.

No DLL is executed under Wine, no GPU/Steam/prefix/driver state is
touched. The shipped mod DLL is only read as bytes (never loaded). The
host test library (same wrapper + same wimlib decoder sources as the
Windows DLL, compiled for Linux) is called via ctypes as a test library.
The Windows PE itself is only statically inspected (exports/imports).

Local inputs fail closed: missing build outputs, mod DLL, or reference
packs skip with an explicit message instead of passing silently.
"""

import ctypes as ct
import hashlib
import re
import shutil
import struct
import subprocess
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import decompress_xmx412 as xmx  # noqa: E402  (read-only pack pins)

DLL412 = ROOT / "artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll"
DLL412_SHA256 = "fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732"
RAWDIR = ROOT / "analysis/fsr-xmx-412"

SHIM_DLL = ROOT / "build/cabinet-shim/cabinet.dll"
SHIM_SO = ROOT / "build/cabinet-shim/test/libcabinet_shim_test.so"
SHIM_REPORT = ROOT / "build/cabinet-shim/report.json"

TOOLCHAIN_BIN = (ROOT / "artifacts/extracted/llvm-mingw-20261020-ucrt" /
                 "llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin")
READOBJ = TOOLCHAIN_BIN / "llvm-readobj"
OBJDUMP = TOOLCHAIN_BIN / "x86_64-w64-mingw32-objdump"

# Ordinal contract shared with tools/build_cabinet_shim.py and the loader
# evidence (FUN_180029640 imports exactly these three ordinals).
EXPECTED_EXPORTS = {40: "CreateDecompressor",
                    43: "Decompress",
                    45: "CloseDecompressor"}
ALLOWED_IMPORT_DLLS = {"KERNEL32.dll",
                       "api-ms-win-crt-runtime-l1-1-0.dll",
                       "api-ms-win-crt-stdio-l1-1-0.dll"}
COMPRESS_RAW = 0x20000000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


SHIM_BUILT = SHIM_DLL.is_file() and SHIM_SO.is_file() and SHIM_REPORT.is_file()
PACK_INPUTS = (
    DLL412.is_file()
    and all((RAWDIR / f"pack-{rid}.raw").is_file() for rid in xmx.EXPECTED)
)


def bind(lib):
    lib.CreateDecompressor.argtypes = [ct.c_uint32, ct.c_void_p,
                                       ct.POINTER(ct.c_void_p)]
    lib.CreateDecompressor.restype = ct.c_int
    lib.Decompress.argtypes = [ct.c_void_p, ct.c_void_p, ct.c_size_t,
                               ct.c_void_p, ct.c_size_t,
                               ct.POINTER(ct.c_size_t)]
    lib.Decompress.restype = ct.c_int
    lib.CloseDecompressor.argtypes = [ct.c_void_p]
    lib.CloseDecompressor.restype = None
    return lib


def load_shim():
    return bind(ct.CDLL(str(SHIM_SO)))


def decode_blob(lib, blob: bytes, out_size: int, algorithm: int = 5):
    handle = ct.c_void_p()
    if lib.CreateDecompressor(algorithm, None, ct.byref(handle)) != 1:
        raise AssertionError(f"CreateDecompressor({algorithm}) failed")
    try:
        inc = ct.create_string_buffer(blob)
        out = ct.create_string_buffer(max(out_size, 1))
        produced = ct.c_size_t(0)
        rc = lib.Decompress(handle, inc, len(blob), out, out_size,
                            ct.byref(produced))
        return rc, produced.value, bytes(out.raw[:out_size])
    finally:
        lib.CloseDecompressor(handle)


@unittest.skipUnless(SHIM_BUILT, "cabinet shim not built: run tools/build_cabinet_shim.py")
class StaticBinaryTests(unittest.TestCase):
    def readobj_exports(self):
        proc = subprocess.run([str(READOBJ), "--coff-exports", str(SHIM_DLL)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        exports = {}
        cur_ord = cur_name = None
        for line in proc.stdout.splitlines():
            line = line.strip()
            m = re.match(r"Ordinal:\s*(\d+)", line)
            if m:
                cur_ord = int(m.group(1))
                continue
            m = re.match(r"Name:\s*(.*)", line)
            if m:
                cur_name = m.group(1).strip()
                continue
            m = re.match(r"RVA:\s*(0x[0-9a-fA-F]+|\d+)", line)
            if m and cur_ord is not None:
                if cur_name:
                    exports[cur_ord] = cur_name
                cur_ord = cur_name = None
        return exports

    def objdump_imports(self):
        proc = subprocess.run([str(OBJDUMP), "-p", str(SHIM_DLL)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        text = proc.stdout.split("Export Table:")[0]
        imports = {}
        cur = None
        for line in text.splitlines():
            m = re.match(r"\s*DLL Name:\s*(\S+)", line)
            if m:
                cur = m.group(1)
                imports[cur] = []
                continue
            m = re.match(r"\s*\d+\s+(?:0x[0-9a-fA-F]+\s+)?(\S+)", line)
            if m and cur is not None and "Hint/Ord" not in line:
                imports[cur].append(m.group(1))
        return imports

    def test_is_pe32plus_x86_64(self):
        proc = subprocess.run([str(OBJDUMP), "-f", str(SHIM_DLL)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("pe-x86-64", proc.stdout)

    def test_ordinal_contract(self):
        self.assertEqual(self.readobj_exports(), EXPECTED_EXPORTS)

    def test_no_unexpected_load_time_deps(self):
        imports = self.objdump_imports()
        self.assertTrue(imports, "no imports parsed")
        self.assertEqual(set(imports) - ALLOWED_IMPORT_DLLS, set())
        flat = [sym for syms in imports.values() for sym in syms]
        self.assertIn("HeapAlloc", flat)
        self.assertIn("SetLastError", flat)

    def test_old_build_needs_same_ordinals(self):
        # Both mod builds (4.0.2x and 4.1.2) import exactly Cabinet 40/43/45.
        self.assertEqual(self.readobj_exports(), EXPECTED_EXPORTS)


@unittest.skipUnless(SHIM_BUILT and PACK_INPUTS,
                     "shim build outputs and/or local 4.1.2 inputs missing")
class SixPackDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_shim()
        dll_bytes = DLL412.read_bytes()
        assert hashlib.sha256(dll_bytes).hexdigest() == DLL412_SHA256
        cls.packs = xmx.packs_from_dll(dll_bytes)
        assert sorted(cls.packs) == [40101, 40102, 40103, 40104, 40105, 40106]

    def decode_and_check(self, rid: int):
        meta = xmx.EXPECTED[rid]
        blob = self.packs[rid]
        self.assertEqual(len(blob), meta["res_size"])
        rc, produced, raw = decode_blob(self.lib, blob, meta["raw_size"])
        self.assertEqual(rc, 1, f"pack {rid}: Decompress failed")
        self.assertEqual(produced, meta["raw_size"], f"pack {rid}")
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         meta["raw_sha256"], f"pack {rid}")
        stored = (RAWDIR / f"pack-{rid}.raw").read_bytes()
        self.assertEqual(len(stored), meta["raw_size"])
        self.assertEqual(raw, stored, f"pack {rid}: not byte-identical")

    def test_pack_40101(self):
        self.decode_and_check(40101)

    def test_pack_40102(self):
        # Focus pack of docs/xmx412-pack-envelope.md and the loader trace.
        self.decode_and_check(40102)

    def test_pack_40103(self):
        self.decode_and_check(40103)

    def test_pack_40104(self):
        self.decode_and_check(40104)

    def test_pack_40105(self):
        self.decode_and_check(40105)

    def test_pack_40106(self):
        self.decode_and_check(40106)


@unittest.skipUnless(SHIM_BUILT and PACK_INPUTS,
                     "shim build outputs and/or local 4.1.2 inputs missing")
class RejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_shim()
        dll_bytes = DLL412.read_bytes()
        cls.packs = xmx.packs_from_dll(dll_bytes)
        cls.blob = cls.packs[40102]
        cls.meta = xmx.EXPECTED[40102]

    def raw_call(self, algorithm, blob, out_size, handle="fresh"):
        lib = self.lib
        if handle == "fresh":
            h = ct.c_void_p()
            created = lib.CreateDecompressor(algorithm, None, ct.byref(h))
            if created != 1:
                return ("create-fail", None, None)
        elif handle is None:
            h = None
        else:
            h = handle
        inc = ct.create_string_buffer(blob)
        out = ct.create_string_buffer(max(out_size, 1))
        produced = ct.c_size_t(0)
        rc = lib.Decompress(h, inc, len(blob), out, out_size,
                            ct.byref(produced))
        if handle == "fresh":
            lib.CloseDecompressor(h)
        return (rc, produced.value, bytes(out.raw[:out_size]))

    def test_unsupported_algorithms_rejected_at_create(self):
        h = ct.c_void_p()
        for alg in (0, 1, 2, 3, 4, 6, 99):
            self.assertNotEqual(
                self.lib.CreateDecompressor(alg, None, ct.byref(h)), 1,
                f"algorithm {alg}")
            self.assertEqual(h.value, None)

    def test_short_buffer_rejected_exact_size_required(self):
        # The loader demands the exact expected size; a short buffer must
        # fail instead of truncating.
        rc, produced, _ = self.raw_call(5, self.blob, self.meta["raw_size"] - 1)
        self.assertEqual(rc, 0)
        self.assertEqual(produced, 0)

    def test_oversize_buffer_reports_exact_produced(self):
        rc, produced, raw = self.raw_call(5, self.blob, self.meta["raw_size"] + 4096)
        self.assertEqual(rc, 1)
        self.assertEqual(produced, self.meta["raw_size"])
        self.assertEqual(hashlib.sha256(raw[:produced]).hexdigest(),
                         self.meta["raw_sha256"])

    def test_truncated_input_rejected(self):
        rc, _, _ = self.raw_call(5, self.blob[:-8], self.meta["raw_size"])
        self.assertEqual(rc, 0)

    def test_trailing_bytes_rejected(self):
        rc, _, _ = self.raw_call(5, self.blob + b"\x00", self.meta["raw_size"])
        self.assertEqual(rc, 0)

    def test_bad_magic_rejected(self):
        bad = bytearray(self.blob)
        bad[0] ^= 0xFF
        rc, _, _ = self.raw_call(5, bytes(bad), self.meta["raw_size"])
        self.assertEqual(rc, 0)

    def test_bad_header_crc_rejected(self):
        bad = bytearray(self.blob)
        bad[6] ^= 0xFF
        rc, _, _ = self.raw_call(5, bytes(bad), self.meta["raw_size"])
        self.assertEqual(rc, 0)

    def test_bad_header_fields_rejected(self):
        # Single-byte corruptions, each guaranteed to differ from the pinned
        # header (24/5/0/65536/0): size, algorithm, reserved, blocksize.
        for off, val in ((4, 32), (7, 3), (12, 1), (16, 1), (20, 7)):
            bad = bytearray(self.blob)
            assert bad[off] != val, f"mutation is a no-op at {off}"
            bad[off] = val
            rc, _, _ = self.raw_call(5, bytes(bad), self.meta["raw_size"])
            self.assertEqual(rc, 0, f"offset {off}")

    def test_null_and_zero_params_rejected(self):
        lib = self.lib
        h = ct.c_void_p()
        self.assertEqual(lib.CreateDecompressor(5, None, ct.byref(h)), 1)
        inc = ct.create_string_buffer(self.blob)
        out = ct.create_string_buffer(self.meta["raw_size"])
        produced = ct.c_size_t(0)
        try:
            self.assertEqual(lib.Decompress(None, inc, len(self.blob), out,
                                           self.meta["raw_size"],
                                           ct.byref(produced)), 0)
            self.assertEqual(lib.Decompress(h, None, len(self.blob), out,
                                           self.meta["raw_size"],
                                           ct.byref(produced)), 0)
            self.assertEqual(lib.Decompress(h, inc, len(self.blob), None,
                                           self.meta["raw_size"],
                                           ct.byref(produced)), 0)
            self.assertEqual(lib.Decompress(h, inc, 0, out,
                                           self.meta["raw_size"],
                                           ct.byref(produced)), 0)
            self.assertEqual(lib.Decompress(h, inc, len(self.blob), out, 0,
                                           ct.byref(produced)), 0)
        finally:
            lib.CloseDecompressor(h)

    def test_null_and_double_close_safe(self):
        lib = self.lib
        lib.CloseDecompressor(None)  # must not crash
        h = ct.c_void_p()
        self.assertEqual(lib.CreateDecompressor(5, None, ct.byref(h)), 1)
        lib.CloseDecompressor(h)
        lib.CloseDecompressor(h)  # stale handle: rejected, no crash

    def test_verbatim_chunk_accepted(self):
        payload = b"hello-verbatim-" * 100
        hdr = struct.pack("<4sHBBIIII", b"\x0a\x51\xe5\xc0", 24, 0, 5,
                          len(payload), 0, 65536, 0)
        crc = zlib.crc32(hdr[7:24], zlib.crc32(hdr[:6])) & 0xFF
        blob = hdr[:6] + bytes([crc]) + hdr[7:] + struct.pack(
            "<I", len(payload)) + payload
        rc, produced, raw = self.raw_call(5, blob, len(payload))
        self.assertEqual(rc, 1)
        self.assertEqual(produced, len(payload))
        self.assertEqual(raw, payload)

    def test_raw_mode_single_block(self):
        # First compressed chunk of pack-40102 decoded as one RAW block.
        lib = self.lib
        total, blocksize = xmx.check_header(self.blob)
        pos = 24
        (chunk_len,) = struct.unpack_from("<I", self.blob, pos)
        chunk = self.blob[pos + 4:pos + 4 + chunk_len]
        want = min(blocksize, total)
        expected = (RAWDIR / "pack-40102.raw").read_bytes()[:want]
        h = ct.c_void_p()
        self.assertEqual(lib.CreateDecompressor(5 | COMPRESS_RAW, None,
                                                ct.byref(h)), 1)
        try:
            inc = ct.create_string_buffer(chunk)
            out = ct.create_string_buffer(want)
            produced = ct.c_size_t(0)
            rc = lib.Decompress(h, inc, len(chunk), out, want,
                                ct.byref(produced))
            self.assertEqual(rc, 1)
            self.assertEqual(produced.value, want)
            self.assertEqual(bytes(out.raw), expected)
        finally:
            lib.CloseDecompressor(h)

    def test_custom_allocation_routines(self):
        # Caller-supplied Allocate/Free must be honored (TLS-routed stubs).
        libc = ct.CDLL(None)
        libc.malloc.argtypes = [ct.c_size_t]
        libc.malloc.restype = ct.c_void_p
        libc.free.argtypes = [ct.c_void_p]
        libc.free.restype = None
        ALLOC = ct.CFUNCTYPE(ct.c_void_p, ct.c_void_p, ct.c_size_t)
        FREE = ct.CFUNCTYPE(None, ct.c_void_p, ct.c_void_p)

        class Routines(ct.Structure):
            _fields_ = [("Allocate", ALLOC), ("Free", FREE),
                        ("UserContext", ct.c_void_p)]

        routines = Routines(ALLOC(lambda ctx, n: libc.malloc(n)),
                            FREE(lambda ctx, p: libc.free(p)), None)
        lib = self.lib
        h = ct.c_void_p()
        self.assertEqual(lib.CreateDecompressor(5, ct.byref(routines),
                                                ct.byref(h)), 1)
        try:
            inc = ct.create_string_buffer(self.blob)
            out = ct.create_string_buffer(self.meta["raw_size"])
            produced = ct.c_size_t(0)
            rc = lib.Decompress(h, inc, len(self.blob), out,
                                self.meta["raw_size"], ct.byref(produced))
            self.assertEqual(rc, 1)
            self.assertEqual(produced.value, self.meta["raw_size"])
            self.assertEqual(
                hashlib.sha256(bytes(out.raw)).hexdigest(),
                self.meta["raw_sha256"])
        finally:
            lib.CloseDecompressor(h)


@unittest.skipUnless(SHIM_BUILT, "cabinet shim not built")
class ReportTests(unittest.TestCase):
    def test_report_matches_artifacts(self):
        import json
        report = json.loads(SHIM_REPORT.read_text())
        self.assertEqual(report["expected_exports"],
                         {str(o): n for o, n in EXPECTED_EXPORTS.items()})
        dll_info = report["dll"]
        self.assertEqual(dll_info["sha256"], sha256_file(SHIM_DLL))
        self.assertEqual(dll_info["size"], SHIM_DLL.stat().st_size)
        self.assertEqual(
            {int(o): v["name"] for o, v in dll_info["exports"].items()},
            EXPECTED_EXPORTS)
        self.assertEqual(set(dll_info["imports"]) - ALLOWED_IMPORT_DLLS, set())
        so_info = report["test_so"]
        self.assertEqual(so_info["sha256"], sha256_file(SHIM_SO))
        self.assertTrue(re.fullmatch(r"[0-9a-f]{40}", report["wimlib"]["rev"]))


if __name__ == "__main__":
    unittest.main()
