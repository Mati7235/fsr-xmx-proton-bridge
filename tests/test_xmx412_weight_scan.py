"""CPU-only pins for the XMX 4.1.2 fsr-original.dll weight scanner.

Read-only.  The DLLs are never loaded or executed; they are opened as data
by a small C scanner (``tools/xmx412_weight_scan.c``) that reimplements the
``FUN_180049950`` contract from ``docs/xmx412-model-selection.md`` section
4.2. No game, prefix, driver, or ``artifacts/original`` state is touched.

Fail-closed pins:

* the official 4.1.2 DLL
  (``artifacts/extracted/fsr-sdk-2.4.0/amd_fidelityfx_upscaler_dx12.dll``)
  reproduces the 4.1.2 version marker at file offset ``0x4b0``
  (``0x01001002`` -> 4.1.2) and satisfies both the Lite and the INT8
  verdicts (all four FNV-1a64 constants match);
* the 4.1.2 mod DLL (``artifacts/extracted/fsr-xmx-412/...``) yields zero
  version pairs and zero weight blobs, so it can never satisfy the loader
  as ``fsr-original.dll``;
* a synthetic undersized input is rejected (size gate), proving the
  verdict path is not hardcoded to OK.

These are static facts only.  They do not prove that a runtime injection,
GPU dispatch, or image readback succeeds.
"""

import hashlib
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER_SRC = ROOT / 'tools' / 'xmx412_weight_scan.c'
OFFICIAL = (ROOT / 'artifacts' / 'extracted' / 'fsr-sdk-2.4.0'
            / 'amd_fidelityfx_upscaler_dx12.dll')
MOD = (ROOT / 'artifacts' / 'extracted' / 'fsr-xmx-412'
       / 'amd_fidelityfx_upscaler_dx12.dll')

OFFICIAL_SHA256 = ('aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace')
MOD_SHA256 = ('fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732')

EXPECTED_FNV_ROLES = {
    'lite-preset': '0x0ca02a3581de817f',
    'lite-ultraperf': '0x2dd74ee29ecb9705',
    'int8-preset': '0x29ce14ecdf23d42b',
    'int8-ultraperf': '0xdfcfd62036f9e391',
}

VERSION_RE = re.compile(
    r'^version off=0x([0-9a-f]+) v=0x([0-9a-f]{8}) '
    r'major=(\d+) minor=(\d+) patch=(\d+)$')
PREFILTER_RE = re.compile(r'^prefilter off=0x([0-9a-f]+) nonzero_words=(\d+)$')
FNV_RE = re.compile(
    r'^fnv_match off=0x([0-9a-f]+) len=0x([0-9a-f]+) '
    r'const=0x([0-9a-f]{16}) role=(\S+) dest=\+0x(\S+)$')


def _sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _parse(output):
    """Parse scanner stdout into a dict; raise on any malformed line."""
    report = {
        'versions': [], 'prefilters': [], 'fnv': [],
        'version_pairs': None, 'max_version': None,
        'prefilter_hits': None, 'fnv_matches': None,
        'verdict_lite': None, 'verdict_int8': None, 'overall': None,
    }
    for line in output.splitlines():
        line = line.strip()
        m = VERSION_RE.match(line)
        if m:
            report['versions'].append({
                'off': int(m.group(1), 16), 'v': int(m.group(2), 16),
                'major': int(m.group(3)), 'minor': int(m.group(4)),
                'patch': int(m.group(5)),
            })
            continue
        m = PREFILTER_RE.match(line)
        if m:
            report['prefilters'].append(
                {'off': int(m.group(1), 16), 'nonzero': int(m.group(2))})
            continue
        m = FNV_RE.match(line)
        if m:
            report['fnv'].append({
                'off': int(m.group(1), 16), 'len': int(m.group(2), 16),
                'const': '0x' + m.group(3), 'role': m.group(4),
                'dest': m.group(5),
            })
            continue
        if line.startswith('version_pairs:'):
            report['version_pairs'] = int(line.split(':')[1])
        elif line.startswith('max_version:'):
            report['max_version'] = line.split(':', 1)[1].strip()
        elif line.startswith('prefilter_hits:'):
            report['prefilter_hits'] = int(line.split(':')[1].split()[0])
        elif line.startswith('fnv_matches:'):
            report['fnv_matches'] = int(line.split(':')[1])
        elif line.startswith('verdict_lite:'):
            report['verdict_lite'] = line.split(':')[1].strip()
        elif line.startswith('verdict_int8:'):
            report['verdict_int8'] = line.split(':')[1].strip()
        elif line.startswith('overall:'):
            report['overall'] = line.split(':')[1].strip()
        # Other lines (file/size/echo/offsets) carry no verdict weight.
    for key in ('version_pairs', 'prefilter_hits', 'fnv_matches',
                'verdict_lite', 'verdict_int8', 'overall'):
        if report[key] is None:
            raise ValueError('scanner output missing %s' % key)
    if len(report['versions']) != report['version_pairs']:
        raise ValueError('version line count does not match version_pairs')
    if len({m['role'] for m in report['fnv']}) != report['fnv_matches']:
        raise ValueError('distinct fnv roles do not match fnv_matches')
    return report


@unittest.skipUnless(shutil.which('cc'), 'C compiler absent')
@unittest.skipUnless(SCANNER_SRC.is_file(), 'weight scanner source absent')
class Xmx412WeightScanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory(prefix='xmx412-scan-')
        cls.binary = Path(cls._tmp.name) / 'xmx412_weight_scan'
        result = subprocess.run(
            ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
             str(SCANNER_SRC), '-o', str(cls.binary)],
            capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(
                'scanner did not compile: %s' % result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _scan(self, path):
        result = subprocess.run(
            [str(self.binary), str(path)],
            capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return _parse(result.stdout)

    @unittest.skipUnless(OFFICIAL.is_file(), 'official 4.1.2 DLL absent')
    def test_official_dll_reproduces_412_marker_and_both_verdicts(self):
        self.assertEqual(_sha256(OFFICIAL), OFFICIAL_SHA256)
        report = self._scan(OFFICIAL)
        # The packed 4.1.2 marker must sit at file offset 0x4b0.
        markers = [v for v in report['versions'] if v['off'] == 0x4b0]
        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]['v'], 0x01001002)
        self.assertEqual(
            (markers[0]['major'], markers[0]['minor'], markers[0]['patch']),
            (4, 1, 2))
        self.assertIn('4.1.2', report['max_version'])
        # All four weight constants must match, each with its role/length.
        roles = {m['role']: m for m in report['fnv']}
        for role, const in EXPECTED_FNV_ROLES.items():
            with self.subTest(role=role):
                self.assertIn(role, roles)
                self.assertEqual(roles[role]['const'], const)
        self.assertEqual(roles['lite-preset']['len'], 0x6B00)
        self.assertEqual(roles['lite-ultraperf']['len'], 0x6B00)
        self.assertEqual(roles['int8-preset']['len'], 0x20000)
        self.assertEqual(roles['int8-ultraperf']['len'], 0x20000)
        # Both availability verdicts must hold.
        self.assertEqual(report['verdict_lite'], 'OK')
        self.assertEqual(report['verdict_int8'], 'OK')
        self.assertEqual(report['overall'], 'LITE+INT8')

    @unittest.skipUnless(MOD.is_file(), 'XMX 4.1.2 mod DLL absent')
    def test_mod_dll_yields_zero_blobs(self):
        self.assertEqual(_sha256(MOD), MOD_SHA256)
        report = self._scan(MOD)
        self.assertEqual(report['version_pairs'], 0)
        self.assertEqual(report['max_version'], 'none')
        self.assertEqual(report['prefilter_hits'], 0)
        self.assertEqual(report['fnv_matches'], 0)
        self.assertEqual(report['verdict_lite'], 'FAIL')
        self.assertEqual(report['verdict_int8'], 'FAIL')
        self.assertEqual(report['overall'], 'NONE')

    def test_undersized_input_is_rejected(self):
        tiny = Path(self._tmp.name) / 'tiny.bin'
        tiny.write_bytes(b'\x00' * 0x100)
        report = self._scan(tiny)
        self.assertEqual(report['verdict_lite'], 'FAIL')
        self.assertEqual(report['verdict_int8'], 'FAIL')
        self.assertEqual(report['overall'], 'NONE')


if __name__ == '__main__':
    unittest.main()
