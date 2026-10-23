"""CPU-only source invariants for the synthetic offline DPAS probe."""
from pathlib import Path
import hashlib
import struct
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from build_lab_probe import (audit_probe_spirv, pack_probe, payload_layout_sha256,
                             placeholder_source, shader_source)


def pack_fixture():
    code = b'native code identity'
    zebin = b'synthetic test zebin'
    payload = []
    for i in range(11):
        payload.append({'arg_type': 'arg_bypointer', 'offset': 8*(i+1), 'size': 8,
                        'arg_index': i, 'addrmode': 'stateful', 'addrspace': 'global',
                        'access_type': 'readwrite'})
        payload.append({'arg_type': 'arg_bypointer', 'offset': 0, 'size': 0,
                        'arg_index': i, 'addrmode': 'stateful', 'addrspace': 'global',
                        'access_type': 'readwrite'})
    payload.append({'arg_type': 'private_base_stateless', 'offset': 0, 'size': 8})
    report = {
        'execution_env': {'has_dpas': True, 'has_sample': False, 'simd_size': 1,
                          'grf_count': 128, 'slm_size': 0, 'barrier_count': 0},
        'payload_arguments': payload,
        'per_thread_payload_arguments': [{'arg_type': 'packed_local_ids', 'offset': 0, 'size': 6}],
        'binding_table_indices': [{'arg_index': i, 'bti_value': i+1} for i in range(11)],
        'code_sha256': hashlib.sha256(code).hexdigest(),
        'zebin_sha256': hashlib.sha256(zebin).hexdigest(),
    }
    audit = {'status': 'restricted-static-no-read', 'code_sha256': report['code_sha256'],
             'zebin_sha256': report['zebin_sha256'],
             'payload_layout_sha256': payload_layout_sha256(report)}
    return zebin, code, report, audit


def run_pack(zebin, report, audit, **kwargs):
    with mock.patch('build_lab_probe.inspect', return_value=report), \
         mock.patch('build_lab_probe.sections', return_value={'.text.bridge_probe': b'native code identity'}):
        return pack_probe(zebin, audit, **kwargs)


class LabProbeShaderTests(unittest.TestCase):
    def test_marker_has_only_one_writer_per_workgroup(self):
        for size in (5, 17):
            source = placeholder_source(size)
            self.assertIn('if (gl_LocalInvocationIndex == 0u)', source)
            self.assertEqual(source.count('heap[0].words[0] ='), 1)

    def test_uses_dpas_signature_from_compiled_pre(self):
        source = shader_source()
        self.assertIn('llvm.genx.dpas2.v128f32.v128f32.v128i32.v64i32', source)
        self.assertIn('%ft_dpas = OpTypeFunction %v128f %v128f %v128u %v64u '
                      '%uint %uint %uint %uint %uint %uint', source)
        self.assertIn('%matrix = OpFunctionCall %v128f %dpas %zero %weights '
                      '%activations %u10 %u10 %u8 %u8 %u0 %u0', source)

    def test_stores_in_supported_four_float_oword_chunks(self):
        source = shader_source()
        self.assertIn('llvm.genx.oword.st.v4f32', source)
        self.assertIn('%ft_store = OpTypeFunction %void %uint %uint %v4f', source)
        self.assertNotIn('llvm.genx.oword.st.v128f32', source)
        for surface in range(11):
            for chunk in range(32):
                self.assertIn(f'%write{surface}_{chunk} = OpFunctionCall %void '
                              f'%store %bti{surface} %off{chunk} %part{surface}_{chunk}',
                              source)
        self.assertIn('%off31 = OpConstant %uint 31', source)

    def test_spirv_audit_rejects_pointer_use_outside_address_convert(self):
        params = '\n'.join(f'%arg{i} = OpFunctionParameter %surface' for i in range(11))
        calls = '\n'.join(f'%bti{i} = OpFunctionCall %uint %convert %arg{i}' for i in range(11))
        text = ('OpEntryPoint Kernel %kernel "bridge_probe"\n'
                'OpDecorate %convert LinkageAttributes "llvm.genx.address.convert.i32.p1intel.buffer_rw_t" Import\n'
                'OpDecorate %dpas LinkageAttributes "llvm.genx.dpas2.test" Import\n'
                '%surface = OpTypeBufferSurfaceINTEL ReadWrite\n'
                '%kernel = OpFunction %void DontInline %function_type\n'+params+'\n'
                '%label = OpLabel\n'+calls+'\n'
                '%matrix = OpFunctionCall %v128 %dpas %a %b %c\n'
                'OpReturn\nOpFunctionEnd\n')
        audit_probe_spirv(text)
        self.assertRaisesRegex(ValueError, 'unreviewed SPIR-V use',
                               audit_probe_spirv, text.replace('OpReturn', 'OpLoad %uint %arg0\nOpReturn'))


class LabProbePackerTests(unittest.TestCase):
    def setUp(self):
        self.zebin, self.code, self.report, self.audit = pack_fixture()

    def test_emits_explicit_cmk3_heap_mapping_for_harness(self):
        cmk, _ = run_pack(self.zebin, self.report, self.audit)
        self.assertEqual(cmk[:4], b'CMK3')
        self.assertEqual(struct.unpack_from('<III', cmk, 168), (0, 0, 4))
        self.assertEqual(struct.unpack_from('<II', cmk, 472), (1, 52))

    def test_nonzero_payload_without_matching_audit_is_rejected(self):
        audit = dict(self.audit, zebin_sha256='0'*64)
        with self.assertRaisesRegex(ValueError, 'exact zebin'):
            run_pack(self.zebin, self.report, audit)

    def test_unreviewed_payload_layout_is_rejected(self):
        self.report['payload_arguments'][0]['addrmode'] = 'stateless'
        with mock.patch('build_lab_probe.inspect', return_value=self.report):
            with self.assertRaisesRegex(ValueError, 'payload differs'):
                pack_probe(self.zebin, self.audit)

    def test_changed_private_base_payload_is_rejected(self):
        self.report['payload_arguments'][-1]['size'] = 16
        with mock.patch('build_lab_probe.inspect', return_value=self.report):
            with self.assertRaisesRegex(ValueError, 'payload differs'):
                pack_probe(self.zebin, self.audit)

    def test_wrong_bti_values_are_rejected(self):
        self.report['binding_table_indices'][0]['bti_value'] = 12
        with mock.patch('build_lab_probe.inspect', return_value=self.report):
            with self.assertRaisesRegex(ValueError, 'BTI values'):
                pack_probe(self.zebin, self.audit)

    def test_unexpected_bti_argument_count_is_rejected(self):
        self.report['binding_table_indices'].pop()
        with mock.patch('build_lab_probe.inspect', return_value=self.report):
            with self.assertRaisesRegex(ValueError, 'buffer arguments'):
                pack_probe(self.zebin, self.audit)

    def test_unsupported_grf_count_is_rejected(self):
        self.report['execution_env']['grf_count'] = 256
        with mock.patch('build_lab_probe.inspect', return_value=self.report):
            with self.assertRaisesRegex(ValueError, '128-GRF'):
                pack_probe(self.zebin, self.audit)

    def test_unsupported_cm_dimensions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'dimensions'):
            run_pack(self.zebin, self.report, self.audit, local_size=(2, 1, 1))


if __name__ == '__main__':
    unittest.main()
