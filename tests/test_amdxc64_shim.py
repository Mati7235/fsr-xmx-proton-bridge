"""CPU-only verification of the minimal amdxc64.dll gate shim.

The Windows PE is only statically inspected (exports/imports/strings). The same
C source is built for Linux (-DAMDXC_HOST_TEST) and driven through ctypes to
exercise the exact vtable ABI the FG 4.0.1 module uses: factory ->
IAmdExtD3DDevice8::GetWaveMatrixProperties (count in/out, single FP8
16x16x16 entry) -> IAmdExtD3DShaderIntrinsics::CheckSupport/Enable, and the
IAmdExtFfxApi E_NOINTERFACE answer. No Wine, no game, no prefix, no GPU.

Local inputs fail closed: missing build outputs skip with an explicit message.
"""

import ctypes as ct
import hashlib
import json
import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM_DLL = ROOT / "build/amdxc64-shim/amdxc64.dll"
SHIM_SO = ROOT / "build/amdxc64-shim/test/libamdxc64_shim_test.so"
SHIM_REPORT = ROOT / "build/amdxc64-shim/report.json"
LOG_DIR = ROOT / "build/amdxc64-shim/test/logs"

TOOLCHAIN_BIN = (ROOT / "artifacts/extracted/llvm-mingw-20261020-ucrt" /
                 "llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin")
READOBJ = TOOLCHAIN_BIN / "llvm-readobj"
OBJDUMP = TOOLCHAIN_BIN / "x86_64-w64-mingw32-objdump"

EXPECTED_EXPORTS = {
    "AmdExtD3DCreateInterface",
    "AmdGetDxcModuleHandle",
    "GetSettingsBlobsAll",
    "OpenAdapter12",
    "OpenShimInterface",
}
ALLOWED_IMPORT_DLLS = {"KERNEL32.dll"}

# Same GUIDs as analysis/fg-401-static/amdxc-gate.md.
IID_FACTORY = "014937EC-9288-446F-A9AC-D75A8E3A984F"
IID_DEVICE8 = "F714E11A-B54E-4E0F-ABC5-DF58B18133D1"
IID_INTRINSICS = "BA019D53-CCAB-4CBD-B56A-7230ED4330AD"
IID_FFXAPI = "B58D6601-7401-4234-8180-6FEBFC0E484C"
IID_UNKNOWN = "11223344-5566-7788-99AA-BBCCDDEEFF00"

S_OK = 0
E_NOINTERFACE = 0x80004002
E_POINTER = 0x80004003


def u32(value: int) -> int:
    """HRESULT as the unsigned 32-bit value seen on the wire."""
    return value & 0xFFFFFFFF


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class GUID(ct.Structure):
    _fields_ = [("d1", ct.c_uint32), ("d2", ct.c_uint16),
                ("d3", ct.c_uint16), ("d4", ct.c_ubyte * 8)]


class WmmaProps(ct.Structure):
    _fields_ = [("m", ct.c_uint64), ("n", ct.c_uint64), ("k", ct.c_uint64),
                ("a", ct.c_int32), ("b", ct.c_int32), ("c", ct.c_int32),
                ("r", ct.c_int32), ("sat", ct.c_uint8), ("pad", ct.c_ubyte * 7)]


def guid(text: str) -> GUID:
    a, b, c, d, e = text.split("-")
    return GUID(int(a, 16), int(b, 16), int(c, 16),
                (ct.c_ubyte * 8)(*bytes.fromhex(d + e)))


def vtbl_slot(obj_addr: int, index: int) -> int:
    vtbl = ct.c_void_p.from_address(obj_addr).value
    assert vtbl, "object has no vtable"
    fn = ct.c_void_p.from_address(vtbl + 8 * index).value
    assert fn, f"vtable slot {index} is NULL"
    return fn


SHIM_BUILT = SHIM_DLL.is_file() and SHIM_SO.is_file() and SHIM_REPORT.is_file()


@unittest.skipUnless(SHIM_BUILT, "amdxc64 shim not built: run tools/build_amdxc64_shim.py")
class StaticBinaryTests(unittest.TestCase):
    def readobj_exports(self):
        proc = subprocess.run([str(READOBJ), "--coff-exports", str(SHIM_DLL)],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        names = set()
        for line in proc.stdout.splitlines():
            m = re.match(r"\s*Name:\s*(\S+)", line)
            if m:
                names.add(m.group(1))
        return names

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

    def test_exports_contract(self):
        self.assertEqual(self.readobj_exports(), EXPECTED_EXPORTS)

    def test_only_kernel32_and_no_crt(self):
        imports = self.objdump_imports()
        self.assertTrue(imports, "no imports parsed")
        self.assertEqual(set(imports), ALLOWED_IMPORT_DLLS)
        flat = {sym for syms in imports.values() for sym in syms}
        for sym in ("GetEnvironmentVariableW", "CreateFileW", "WriteFile",
                    "CloseHandle"):
            self.assertIn(sym, flat)
        for sym in flat:
            self.assertNotIn("crt", sym.lower())
            self.assertNotIn("msvc", sym.lower())

    def test_expected_strings_present(self):
        data = SHIM_DLL.read_bytes()
        for text in ("AMDXC_SHIM_LOG", "AMDXC_SHIM",
                     "GetWaveMatrixProperties", "CheckSupport",
                     "AmdExtD3DCreateInterface"):
            ascii_form = text.encode()
            wide_form = b"".join(bytes((c, 0)) for c in ascii_form)
            self.assertTrue(ascii_form in data or wide_form in data,
                            f"missing string {text}")


@unittest.skipUnless(SHIM_BUILT, "amdxc64 shim not built")
class ReportTests(unittest.TestCase):
    def test_report_matches_artifacts(self):
        report = json.loads(SHIM_REPORT.read_text())
        self.assertEqual(set(report["expected_exports"]), EXPECTED_EXPORTS)
        self.assertEqual(report["dll"]["sha256"], sha256_file(SHIM_DLL))
        self.assertEqual(report["dll"]["size"], SHIM_DLL.stat().st_size)
        self.assertEqual(set(report["dll"]["exports"]), EXPECTED_EXPORTS)
        self.assertEqual(set(report["dll"]["imports"]), ALLOWED_IMPORT_DLLS)
        self.assertEqual(report["test_so"]["sha256"], sha256_file(SHIM_SO))


class HostShim:
    """ctypes binding to the host twin (same source as the Windows DLL)."""

    def __init__(self, path: Path):
        self.lib = ct.CDLL(str(path))
        self.lib.AmdExtD3DCreateInterface.argtypes = [
            ct.c_void_p, ct.c_void_p, ct.POINTER(ct.c_void_p)]
        self.lib.AmdExtD3DCreateInterface.restype = ct.c_int32
        self.lib.AmdGetDxcModuleHandle.restype = ct.c_void_p
        self.lib.GetSettingsBlobsAll.restype = ct.c_int32
        self.lib.OpenAdapter12.restype = ct.c_int32
        self.lib.OpenShimInterface.restype = ct.c_int32

    def create_interface(self, iid_text: str):
        out = ct.c_void_p(0xDEAD)
        iid = guid(iid_text)
        hr = self.lib.AmdExtD3DCreateInterface(None, ct.byref(iid),
                                               ct.byref(out))
        return hr, out.value

    def factory_create(self, factory: int, iid_text: str):
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p, ct.c_void_p,
                          ct.POINTER(ct.c_void_p))(vtbl_slot(factory, 3))
        out = ct.c_void_p(0xDEAD)
        iid = guid(iid_text)
        hr = fn(factory, None, ct.byref(iid), ct.byref(out))
        return hr, out.value

    def release(self, obj: int) -> int:
        fn = ct.CFUNCTYPE(ct.c_uint32, ct.c_void_p)(vtbl_slot(obj, 2))
        return fn(obj)

    def addref(self, obj: int) -> int:
        fn = ct.CFUNCTYPE(ct.c_uint32, ct.c_void_p)(vtbl_slot(obj, 1))
        return fn(obj)

    def query_interface(self, obj: int, iid_text: str):
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p,
                          ct.POINTER(ct.c_void_p))(vtbl_slot(obj, 0))
        out = ct.c_void_p(0xDEAD)
        iid = guid(iid_text)
        return fn(obj, ct.byref(iid), ct.byref(out)), out.value

    def get_wmma(self, dev8: int, count_ptr, props_ptr) -> int:
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p,
                          ct.c_void_p)(vtbl_slot(dev8, 16))
        return fn(dev8, ct.cast(count_ptr, ct.c_void_p),
                  ct.cast(props_ptr, ct.c_void_p))

    def check_support(self, intrinsics: int, value: int) -> int:
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_int32)(
            vtbl_slot(intrinsics, 4))
        return fn(intrinsics, value)

    def enable(self, intrinsics: int) -> int:
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p)(vtbl_slot(intrinsics, 5))
        return fn(intrinsics)

    def update_provider(self, ffx: int, data_ptr, size: int) -> int:
        fn = ct.CFUNCTYPE(ct.c_int32, ct.c_void_p, ct.c_void_p, ct.c_uint32)(
            vtbl_slot(ffx, 3))
        return fn(ffx, ct.cast(data_ptr, ct.c_void_p), size)


@unittest.skipUnless(SHIM_BUILT, "amdxc64 shim not built")
class GateBehaviourTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shim = HostShim(SHIM_SO)
        cls._saved = {k: os.environ.get(k)
                      for k in ("AMDXC_SHIM", "AMDXC_SHIM_LOG")}
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        os.environ["AMDXC_SHIM"] = "1"

    @classmethod
    def tearDownClass(cls):
        for k, v in cls._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def setUp(self):
        self.log = LOG_DIR / f"{self._testMethodName}.log"
        if self.log.exists():
            self.log.unlink()
        os.environ["AMDXC_SHIM_LOG"] = str(self.log)

    def test_full_gate_sequence(self):
        shim = self.shim
        hr, factory = shim.create_interface(IID_FACTORY)
        self.assertEqual(hr, S_OK)
        self.assertTrue(factory)

        hr, dev8 = shim.factory_create(factory, IID_DEVICE8)
        self.assertEqual(hr, S_OK)
        self.assertTrue(dev8)

        count = ct.c_uint64(14)
        props = (WmmaProps * 14)()
        hr = shim.get_wmma(dev8, ct.byref(count), props)
        self.assertEqual(hr, S_OK)
        self.assertEqual(count.value, 1)
        self.assertEqual((props[0].m, props[0].n, props[0].k), (16, 16, 16))
        self.assertEqual((props[0].a, props[0].b), (0xB, 0xB))
        self.assertEqual((props[0].c, props[0].r), (1, 1))
        self.assertEqual(props[0].sat, 0)

        hr, intrinsics = shim.factory_create(factory, IID_INTRINSICS)
        self.assertEqual(hr, S_OK)
        self.assertEqual(shim.check_support(intrinsics, 0x1F), S_OK)
        self.assertEqual(shim.check_support(intrinsics, 0x20), S_OK)
        self.assertEqual(shim.enable(intrinsics), S_OK)

        # Releases are no-ops for the static singletons.
        self.assertEqual(shim.release(dev8), 0)
        self.assertEqual(shim.release(intrinsics), 0)
        self.assertEqual(shim.release(factory), 0)

        text = self.log.read_text()
        self.assertIn("AmdExtD3DCreateInterface", text)
        self.assertIn("Factory::CreateInterface", text)
        self.assertIn("count_in=14 count_out=1", text)
        self.assertIn("SI::CheckSupport intrinsic=0x001F result=S_OK", text)
        self.assertIn("SI::CheckSupport intrinsic=0x0020 result=S_OK", text)
        self.assertIn("SI::Enable result=S_OK", text)

    def test_wmma_count_semantics(self):
        shim = self.shim
        _, factory = shim.create_interface(IID_FACTORY)
        _, dev8 = shim.factory_create(factory, IID_DEVICE8)

        # Capacity 0: nothing written, *count = 0.
        props = (WmmaProps * 1)()
        ct.memset(ct.byref(props), 0xAA, ct.sizeof(props))
        count = ct.c_uint64(0)
        self.assertEqual(shim.get_wmma(dev8, ct.byref(count), props), S_OK)
        self.assertEqual(count.value, 0)
        self.assertEqual(bytes(props)[0], 0xAA)

        # Capacity 3: one entry, trailing entries untouched.
        arr = (WmmaProps * 3)()
        ct.memset(ct.byref(arr), 0xAA, ct.sizeof(arr))
        count = ct.c_uint64(3)
        self.assertEqual(shim.get_wmma(dev8, ct.byref(count), arr), S_OK)
        self.assertEqual(count.value, 1)
        self.assertEqual(arr[0].m, 16)
        self.assertEqual(bytes(arr)[ct.sizeof(WmmaProps)], 0xAA)

        # NULL count -> E_POINTER (defensive; the module always passes one).
        self.assertEqual(u32(shim.get_wmma(dev8, None, arr)), E_POINTER)

    def test_ffxapi_returns_e_nointerface(self):
        shim = self.shim
        hr, ffx = shim.create_interface(IID_FFXAPI)
        self.assertEqual(hr, S_OK)
        self.assertTrue(ffx)
        data = (ct.c_uint32 * 20)()
        data[0] = 2  # structVersion
        data[2] = 0x00020000  # descType low half, arbitrary
        self.assertEqual(u32(shim.update_provider(ffx, ct.byref(data), 0x50)),
                         E_NOINTERFACE)
        text = self.log.read_text()
        self.assertIn("FfxApi::UpdateFfxApiProvider", text)
        self.assertIn("E_NOINTERFACE", text)

    def test_unknown_iids_rejected(self):
        shim = self.shim
        hr, obj = shim.create_interface(IID_UNKNOWN)
        self.assertEqual(u32(hr), E_NOINTERFACE)
        self.assertIsNone(obj)

        _, factory = shim.create_interface(IID_FACTORY)
        hr, obj = shim.factory_create(factory, IID_UNKNOWN)
        self.assertEqual(u32(hr), E_NOINTERFACE)
        self.assertIsNone(obj)

        # The module also asks the factory for IAmdExtFlipMeter.
        hr, obj = shim.factory_create(
            factory, "543820DD-06C9-4F7E-A3D0-CA260D794ADD")
        self.assertEqual(u32(hr), E_NOINTERFACE)
        self.assertIsNone(obj)

    def test_queryinterface_and_refcounts(self):
        shim = self.shim
        _, factory = shim.create_interface(IID_FACTORY)
        self.assertEqual(u32(shim.query_interface(factory, IID_FACTORY)[0]),
                         E_NOINTERFACE)
        self.assertEqual(shim.addref(factory), 1)
        self.assertEqual(shim.release(factory), 0)

    def test_other_exports(self):
        self.assertIsNone(self.shim.lib.AmdGetDxcModuleHandle())
        self.assertNotEqual(self.shim.lib.GetSettingsBlobsAll(), 0)
        self.assertNotEqual(self.shim.lib.OpenAdapter12(), 0)
        self.assertNotEqual(self.shim.lib.OpenShimInterface(), 0)

    def test_log_appends_across_calls(self):
        shim = self.shim
        for _ in range(2):
            shim.create_interface(IID_FACTORY)
        lines = [l for l in self.log.read_text().splitlines() if l]
        self.assertEqual(len(lines), 2)
        self.assertTrue(all("AmdExtD3DCreateInterface" in l for l in lines))

    def test_inert_when_env_missing(self):
        shim = self.shim
        os.environ.pop("AMDXC_SHIM", None)
        try:
            hr, obj = shim.create_interface(IID_FACTORY)
            self.assertEqual(u32(hr), E_NOINTERFACE)
            self.assertIsNone(obj)
            self.assertFalse(self.log.exists())
        finally:
            os.environ["AMDXC_SHIM"] = "1"


if __name__ == "__main__":
    unittest.main()
