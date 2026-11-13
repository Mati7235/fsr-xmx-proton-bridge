"""CPU-only static pins for the XMX 4.1.2 model-selection contract.

Read-only.  The DLL is never loaded or executed, no GPU/Wine/driver/prefix
state is touched, and ``artifacts/original`` is not written.  The tests pin:

* the exact local artifact (SHA-256) and its model-selection strings;
* the ``CreateModel`` environment branches (INT8 -> 4.1.2X, LITE ->
  4.1.2X Lite, PRE41 -> 4.0.2X Hybrid) including the order in which the
  branches fall through;
* the 32-entry FFX provider-version table (vtable, state flags and the
  base/hybrid/Lite/INT8/3.1.5 labels);
* the ``fsr-original.dll`` weight-scanner contract (four FNV-1a64
  constants, 0x6b00/0x20000 weight blobs, 0xf5a5ca1e version marker,
  ``%u.%u.%uX`` label generation).

These are static facts only.  They do not prove that a runtime injection,
GPU dispatch, or image readback succeeds.
"""

import hashlib
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / 'artifacts' / 'extracted' / 'fsr-xmx-412' / 'amd_fidelityfx_upscaler_dx12.dll'

DLL_SHA256 = 'fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732'


class PeImage:
    """Minimal read-only PE32+ VA -> file-offset mapper (stdlib only)."""

    def __init__(self, path):
        self.path = path
        self.data = path.read_bytes()
        e_lfanew = struct.unpack_from('<I', self.data, 0x3C)[0]
        if self.data[e_lfanew:e_lfanew + 4] != b'PE\0\0':
            raise ValueError('not a PE image')
        self.sections = []
        number = struct.unpack_from('<H', self.data, e_lfanew + 6)[0]
        opt_size = struct.unpack_from('<H', self.data, e_lfanew + 20)[0]
        opt = e_lfanew + 24
        magic = struct.unpack_from('<H', self.data, opt)[0]
        if magic == 0x20B:
            self.image_base = struct.unpack_from('<Q', self.data, opt + 0x18)[0]
        elif magic == 0x10B:
            self.image_base = struct.unpack_from('<I', self.data, opt + 0x1C)[0]
        else:
            raise ValueError('unsupported optional-header magic 0x%x' % magic)
        table = opt + opt_size
        for i in range(number):
            off = table + i * 40
            name = self.data[off:off + 8].rstrip(b'\0').decode('ascii', 'replace')
            vsize, vaddr, rawsize, rawptr = struct.unpack_from('<IIII', self.data, off + 8)
            self.sections.append((name, vsize, vaddr, rawsize, rawptr))

    def va_to_off(self, va):
        rva = va - self.image_base
        for _name, vsize, vaddr, rawsize, rawptr in self.sections:
            if vaddr <= rva < vaddr + max(vsize, rawsize):
                return rawptr + (rva - vaddr)
        raise KeyError('VA 0x%x is not mapped' % va)

    def read(self, va, size):
        off = self.va_to_off(va)
        return self.data[off:off + size]

    def cstr(self, va, limit=512):
        raw = self.read(va, limit)
        return raw.split(b'\0', 1)[0].decode('ascii')

    def wstr(self, va, limit=1024):
        raw = self.read(va, limit)
        return raw.decode('utf-16le').split('\0', 1)[0]

    def u32(self, va):
        return struct.unpack('<I', self.read(va, 4))[0]

    def u64(self, va):
        return struct.unpack('<Q', self.read(va, 8))[0]

    def lea_target(self, va):
        """Decode a RIP-relative ``lea r64, [rip+disp32]`` at ``va``."""
        raw = self.read(va, 7)
        if raw[0] not in (0x48, 0x4C) or raw[1] != 0x8D:
            raise AssertionError('expected REX.W lea at 0x%x, got %s' % (va, raw.hex()))
        if raw[2] & 0xC7 != 0x05:
            raise AssertionError('expected RIP-relative lea at 0x%x, got %s' % (va, raw.hex()))
        disp = struct.unpack_from('<i', raw, 3)[0]
        return va + 7 + disp


def fsr4_label(state8, state10):
    """Mirror the FSR4 subset of FUN_180065920 (0x180065920).

    Returns ``None`` for non-FSR4 provider entries (DLSS / 3.1.5).
    The generated 4.1.2 strings are represented by their fixed prefixes;
    the real text is built from fsr-original.dll at runtime.
    """
    state = struct.pack('<QQ', state8, state10)
    b8, b9, b10, b11, b12, b13, b14, b15, b16, b17 = state[:10]
    if b17:
        return '3.1.5'
    if b16 or b15 or b13:
        return None  # DLSS-MX/LX, DLSS-E/F/EFX, DLSS-KX
    if b14:
        return 'ASkip'
    if b12:
        return 'QSkip'
    if b11:
        return 'Skip'
    if b10:
        return '4.1.2X'
    if b9:
        return '4.1.2X Lite'
    if b8:
        return '4.0.2X Hybrid'
    return '4.0.2X'


@unittest.skipUnless(DLL.exists(), 'local XMX 4.1.2 DLL is not present')
class Xmx412ModelStringsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.img = PeImage(DLL)

    def test_artifact_sha256(self):
        digest = hashlib.sha256(self.img.data).hexdigest()
        self.assertEqual(digest, DLL_SHA256)

    def test_key_strings_are_at_pinned_addresses(self):
        strings = {
            0x180322370: b'FSR4_XMX_INT8',
            0x180322380: b'FSR4_XMX_LITE',
            0x180322390: b'FSR4_XMX_PRE41',
            0x1803223A0: b'4.1.2X',
            0x1803223A8: b'4.1.2X Lite',
            0x180321E60: b'4.0.2X Hybrid',
            0x180321E70: b'4.0.2X',
            0x180323290: b'FSR4_XMX_PRE41=1',
            0x1803232A8: b'FSR4_XMX_INT8=1',
            0x1803232B8: b'FSR4_XMX_LITE=1',
            0x18030E2A8: b'%s weights are unavailable (fsr-original.dll).',
            0x18030E2E0: b'Lite/INT8 model requested without verified fsr-original.dll weights.',
            0x18030E328: b'embedded Lite XMX resource pack is missing or invalid.',
            0x18030E370: b'[FSR4 XMX] %s model: %s weights from %ls, bucket %u, %s kernels%s.\n',
            0x18031AE50: b'[FSR4 XMX] %s network kernels ready (bucket %u, %s weights).\n',
            0x18030E0C0: b'FSR 4.1.2 Lite (DG2)',
            0x180089FA8: b'%u.%u.%uX',
            0x180089F80: b'%u.%u.%uX Lite',
            0x180323C30: b'FSR4_XMX_DEV',
            0x180F2DA90: b'FSR4_XMX_PROVIDER_INDEX',
            0x18031B0D0: b'FSR4_XMX_FS_DIAG',
            0x18030DDE8: b'FSR4_XMX_DPAS',
            0x180323358: b'FSR4_XMX_SHARPNESS',
            0x1803223E0: b'FSR4_XMX_FRAMESKIP',
            0x180321C70: b'FSR4_XMX_LIST_SKIP',
            0x180321C88: b'FSR4_XMX_ASKIP',
            0x180323778: b'fsr-original.dll',
            0x180323790: b'Missing? Place next to this DLL, restart.',
        }
        for va, expected in strings.items():
            with self.subTest(va=hex(va)):
                self.assertEqual(self.img.cstr(va, len(expected) + 1), expected.decode())

        self.assertEqual(self.img.wstr(0x18008A018), 'fsr-original.dll')
        self.assertEqual(self.img.wstr(0x180089FF0), 'FSR4_XMX_LITE_DLL')

    def test_create_model_env_branches(self):
        # CreateModel = 0x1800617c0.  Each lea loads the env name that is
        # tested by the following GetEnvironmentVariableA call.
        branches = {
            0x180061985: 0x180322370,  # FSR4_XMX_INT8 -> label 4.1.2X
            0x1800619A7: 0x180322380,  # FSR4_XMX_LITE -> label 4.1.2X Lite
            0x1800619D4: 0x180322390,  # FSR4_XMX_PRE41 -> label 4.0.2X Hybrid
            0x180061AF7: 0x1803223A0,  # 4.1.2X
            0x180061B1B: 0x1803223A8,  # 4.1.2X Lite
            0x180061B3C: 0x180321E60,  # 4.0.2X Hybrid
        }
        for va, target in branches.items():
            with self.subTest(va=hex(va)):
                self.assertEqual(self.img.lea_target(va), target)

        # INT8 branch requires FUN_180027c00()->[0x68] != 0.
        self.assertEqual(self.img.read(0x180061AEF, 4), bytes.fromhex('80 78 68 00'))
        self.assertEqual(self.img.read(0x180061AF3, 2), bytes.fromhex('74 13'))
        # LITE branch requires FUN_180027c00()->[0] != 0.
        self.assertEqual(self.img.read(0x180061B14, 3), bytes.fromhex('80 38 00'))
        self.assertEqual(self.img.read(0x180061B17, 2), bytes.fromhex('74 16'))
        # PRE41 is only reached after both weight checks fail.
        self.assertEqual(self.img.read(0x180061B2F, 7), bytes.fromhex('80 bd f0 03 00 00 31'))
        self.assertEqual(self.img.read(0x180061B36, 6), bytes.fromhex('0f 85 bf 00 00 00'))
        self.assertEqual(self.img.read(0x1800619FB, 6), bytes.fromhex('89 95 f0 03 00 00'))

        # Selected branch flags are passed to FUN_180061020 at 0x180061b66:
        # PRE41 in edx, LITE in r8b, INT8 in r9b.
        self.assertEqual(self.img.read(0x180061B00, 4), bytes.fromhex('44 0f b6 ce'))
        self.assertEqual(self.img.read(0x180061B29, 4), bytes.fromhex('44 0f b6 c6'))
        self.assertEqual(self.img.read(0x180061B43, 4), bytes.fromhex('40 0f b6 d6'))
        self.assertEqual(self.img.read(0x180061B66, 5), bytes.fromhex('e8 b5 f4 ff ff'))
        self.assertEqual(0x180061B66 + 5 + struct.unpack('<i', self.img.read(0x180061B67, 4))[0],
                         0x180061020)

    def test_version_labels_are_static_or_weights_derived(self):
        # FUN_180065920 returns the literal base/hybrid labels...
        self.assertEqual(self.img.lea_target(0x180065AD8), 0x180321E60)
        self.assertEqual(self.img.lea_target(0x180065ADF), 0x180321E70)
        # ...and returns generated strings from fsr-original.dll for INT8
        # (+0x69) and Lite (+1).
        self.assertEqual(self.img.read(0x180065AB8, 4), bytes.fromhex('48 83 c0 69'))
        self.assertEqual(self.img.read(0x180065ACC, 3), bytes.fromhex('48 ff c0'))
        # The base provider label is literally "4.0.2X"; the PE VERSIONINFO
        # (4.0.2.1) is fixed independently of FSR4_XMX_*.
        self.assertEqual(self.img.cstr(0x180321E70), '4.0.2X')

    def test_provider_table_state_mapping(self):
        # PTR_PTR_180f2d970 has 32 entries (FUN_180074600 loops to 0x100).
        table = [self.img.u64(0x180F2D970 + i * 8) for i in range(32)]
        self.assertEqual(len(set(table)), 32)
        for i, ptr in enumerate(table):
            with self.subTest(index=i):
                self.assertEqual(self.img.u64(ptr), 0x18031F088)  # FSR4 provider vtable

        expected = {
            0: (0x0000000000000000, 0x0000000000000000, '4.0.2X'),
            4: (0x0000000000000001, 0x0000000000000000, '4.0.2X Hybrid'),
            8: (0x0000000000010101, 0x0000000000000000, '4.1.2X'),
            12: (0x0000000000000101, 0x0000000000000000, '4.1.2X Lite'),
            31: (0x0000000000000000, 0x0000000000000100, '3.1.5'),
        }
        for index, (state8, state10, label) in expected.items():
            ptr = table[index]
            self.assertEqual(self.img.u64(ptr + 8), state8)
            self.assertEqual(self.img.u64(ptr + 16), state10)
            self.assertEqual(fsr4_label(state8, state10), label)

        # 4.1.2X must be the entry with hybrid+lite+INT8 flags; 4.1.2X Lite
        # is the entry with only hybrid+lite.
        self.assertEqual(fsr4_label(self.img.u64(table[8] + 8),
                                    self.img.u64(table[8] + 16)), '4.1.2X')
        self.assertEqual(fsr4_label(self.img.u64(table[12] + 8),
                                    self.img.u64(table[12] + 16)), '4.1.2X Lite')

    def test_fsr_original_weight_scanner_contract(self):
        # FUN_180049950: four fixed FNV-1a64 weight blobs.
        fnv = {
            0x180049C1F: 0x0CA02A3581DE817F,  # Lite preset, copied to +0x38
            0x180049C51: 0x29CE14ECDF23D42B,  # INT8 preset, copied to +0xd8
            0x180049C7C: 0x2DD74EE29ECB9705,  # Lite ultraperf, copied to +0x50
            0x180049CA6: 0x0DFCFD62036F9E391,  # INT8 ultraperf, copied to +0xf0
        }
        for va, value in fnv.items():
            with self.subTest(va=hex(va)):
                self.assertEqual(self.img.read(va, 2), b'\x48\xb8')
                self.assertEqual(struct.unpack('<Q', self.img.read(va + 2, 8))[0], value)

        destinations = {
            0x180049C38: bytes.fromhex('49 8d 4f 38'),              # +0x38 Lite preset
            0x180049C95: bytes.fromhex('49 8d 4f 50'),              # +0x50 Lite ultra
            0x180049C60: bytes.fromhex('49 8d 8f d8 00 00 00'),     # +0xd8 INT8 preset
            0x180049CB5: bytes.fromhex('49 8d 8f f0 00 00 00'),     # +0xf0 INT8 ultra
        }
        for va, expected in destinations.items():
            with self.subTest(va=hex(va)):
                self.assertEqual(self.img.read(va, len(expected)), expected)

        # Version marker and major/minor/patch extraction.
        self.assertEqual(self.img.read(0x180049D60, 7), bytes.fromhex('81 79 04 1e ca a5 f5'))
        self.assertEqual(self.img.read(0x180049EAA, 3), bytes.fromhex('c1 eb 0c'))
        self.assertEqual(self.img.read(0x180049EAD, 6), bytes.fromhex('81 e3 ff 03 00 00'))
        self.assertEqual(self.img.read(0x180049EB3, 3), bytes.fromhex('c1 ef 16'))
        self.assertEqual(self.img.read(0x180049EB6, 6), bytes.fromhex('81 e6 ff 0f 00 00'))

        # Availability flags: struct+0 = Lite, struct+0x68 = INT8.
        self.assertEqual(self.img.read(0x180049E07, 3), bytes.fromhex('41 88 07'))
        self.assertEqual(self.img.read(0x180049E26, 4), bytes.fromhex('41 88 4f 68'))

    def test_only_the_fidelityfx_dll_is_named(self):
        # The mod never references amdxcffx64.dll; the only amdxc* string is
        # the unrelated provider name amdxc64.dll.
        self.assertNotIn(b'amdxcffx64.dll', self.img.data)
        self.assertEqual(self.img.cstr(0x180F2DA80), 'amdxc64.dll')
        self.assertIn(b'amd_fidelityfx_upscaler_dx12.pdb', self.img.data)


if __name__ == '__main__':
    unittest.main()
