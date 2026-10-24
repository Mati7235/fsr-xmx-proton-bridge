import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from inspect_pre_dispatch import inspect


ZE_INFO = ROOT / 'analysis/offline-pre/full/ze_info.yaml'
ASSEMBLY = ROOT / 'analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm'
ZEBIN = ROOT / 'analysis/offline-pre/full/pre_bmg.bin'


@unittest.skipUnless(ZE_INFO.is_file() and ASSEMBLY.is_file() and ZEBIN.is_file(),
                     'Requires pinned local PRE compiler evidence')
class PreDispatchInspectionTests(unittest.TestCase):
    def test_pinned_evidence_separates_simd_from_workgroup_geometry(self):
        result = inspect(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(), ZEBIN.read_bytes())
        self.assertEqual(result['observed']['compiler_simd_size'], 1)
        self.assertEqual(result['observed']['per_thread_payload']['size_bytes'], 6)
        self.assertIsNone(result['not_established']['required_workgroup_size'])
        self.assertIsNone(result['not_established']['hardware_threadcount'])
        self.assertIsNone(result['not_established']['runtime_workgroupcount'])
        self.assertIn('assumed', result['not_established']['execution_mask'])

    def test_rejects_truncated_metadata(self):
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            inspect(b'version: 1.50\n', ASSEMBLY.read_bytes(), ZEBIN.read_bytes())

    def test_rejects_changed_assembly(self):
        with self.assertRaisesRegex(ValueError, 'assembly SHA-256'):
            inspect(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes() + b'\n', ZEBIN.read_bytes())

    def test_rejects_truncated_zebin(self):
        with self.assertRaisesRegex(ValueError, 'zebin SHA-256'):
            inspect(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(), ZEBIN.read_bytes()[:-1])


class PreDispatchHashGateTests(unittest.TestCase):
    def test_rejects_unreviewed_input_without_local_artifacts(self):
        with self.assertRaisesRegex(ValueError, r'\.ze_info SHA-256'):
            inspect(b'version: 1.50\n', b'', b'')


if __name__ == '__main__':
    unittest.main()
