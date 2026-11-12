import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import inspect_pre_dispatch as inspector
from inspect_pre_dispatch import inspect


ZE_INFO = ROOT / 'analysis/offline-pre/full/ze_info.yaml'
ASSEMBLY = ROOT / 'analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm'
ZEBIN = ROOT / 'analysis/offline-pre/full/pre_bmg.bin'
IR = ROOT / 'analysis/fsr-resources/xe2-first.spvasm'


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

    @unittest.skipUnless(IR.is_file(), 'Requires pinned local PRE SPIR-V assembly')
    def test_ir_builtin_evidence_does_not_authorize_local_size(self):
        result = inspect(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(), ZEBIN.read_bytes(), IR.read_bytes())
        self.assertEqual(result['observed']['spirv_builtin_declarations'], ['WorkgroupId'])
        self.assertIsNone(result['not_established']['required_workgroup_size'])
        with self.assertRaisesRegex(ValueError, 'SPIR-V assembly SHA-256'):
            inspect(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(), ZEBIN.read_bytes(), IR.read_bytes() + b'\n')


class PreDispatchHashGateTests(unittest.TestCase):
    def test_rejects_unreviewed_input_without_local_artifacts(self):
        with self.assertRaisesRegex(ValueError, r'\.ze_info SHA-256'):
            inspect(b'version: 1.50\n', b'', b'')


class PreDispatchContentGateTests(unittest.TestCase):
    """Defense-in-depth behind the SHA-256 pins: mutate content in memory and
    bypass only the hash gate to prove the semantic checks still fail closed.

    No artifact on disk is modified; all mutations are CPU-only byte copies.
    """

    def _bypass_hash(self, ze=None, asm=None, zebin=None, ir=None):
        import hashlib
        patches = {}
        if ze is not None:
            patches['EXPECTED_ZE_INFO_SHA256'] = hashlib.sha256(ze).hexdigest()
        if asm is not None:
            patches['EXPECTED_ASSEMBLY_SHA256'] = hashlib.sha256(asm).hexdigest()
        if zebin is not None:
            patches['EXPECTED_ZEBIN_SHA256'] = hashlib.sha256(zebin).hexdigest()
        if ir is not None:
            patches['EXPECTED_IR_SHA256'] = hashlib.sha256(ir).hexdigest()
        return patches

    def _assert_content_reject(self, ze, asm, zebin, pattern, ir=None):
        patches = self._bypass_hash(ze=ze, asm=asm, zebin=zebin, ir=ir)
        saved = {k: getattr(inspector, k) for k in patches}
        for k, v in patches.items():
            setattr(inspector, k, v)
        try:
            with self.assertRaisesRegex(ValueError, pattern):
                inspect(ze, asm, zebin, ir)
        finally:
            for k, v in saved.items():
                setattr(inspector, k, v)

    def test_rejects_injected_local_size_attribute(self):
        ze = ZE_INFO.read_bytes() + b'      required_work_group_size: [32, 1, 1]\n'
        self._assert_content_reject(ze, ASSEMBLY.read_bytes(), ZEBIN.read_bytes(),
                                    'local-size metadata attribute')

    def test_rejects_changed_simd_size(self):
        ze = ZE_INFO.read_bytes().replace(b'simd_size:       1', b'simd_size:       32', 1)
        self.assertIn(b'simd_size:       32', ze)
        self._assert_content_reject(ze, ASSEMBLY.read_bytes(), ZEBIN.read_bytes(),
                                    'SIMD metadata no longer matches')

    def test_rejects_changed_packed_local_ids(self):
        ze = ZE_INFO.read_bytes().replace(b'size:            6', b'size:            8', 1)
        self._assert_content_reject(ze, ASSEMBLY.read_bytes(), ZEBIN.read_bytes(),
                                    'packed_local_ids metadata changed')

    def test_rejects_assembly_without_simd16(self):
        asm = ASSEMBLY.read_bytes().replace(b'simd16', b'simdXX')
        self.assertNotIn(b'simd16', asm)
        self._assert_content_reject(ZE_INFO.read_bytes(), asm, ZEBIN.read_bytes(),
                                    'SIMD16 operations')

    @unittest.skipUnless(IR.is_file(), 'Requires pinned local PRE SPIR-V assembly')
    def test_rejects_added_local_size_execution_mode(self):
        ir = IR.read_bytes().replace(
            b'OpExecutionMode %10259 SubgroupSize 1',
            b'OpExecutionMode %10259 LocalSize 32 1 1', 1)
        self.assertIn(b'LocalSize 32 1 1', ir)
        self._assert_content_reject(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(),
                                    ZEBIN.read_bytes(),
                                    'builtin declarations or execution modes changed',
                                    ir=ir)

    @unittest.skipUnless(IR.is_file(), 'Requires pinned local PRE SPIR-V assembly')
    def test_rejects_added_local_invocation_builtin(self):
        ir = IR.read_bytes().replace(b'BuiltIn WorkgroupId', b'BuiltIn LocalInvocationId', 1)
        self._assert_content_reject(ZE_INFO.read_bytes(), ASSEMBLY.read_bytes(),
                                    ZEBIN.read_bytes(),
                                    'builtin declarations or execution modes changed',
                                    ir=ir)


if __name__ == '__main__':
    unittest.main()
