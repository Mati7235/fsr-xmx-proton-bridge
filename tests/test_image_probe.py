"""CPU-only contract, shader-source, audit-gate and packer checks."""
from pathlib import Path
import hashlib
import struct
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from image_probe_reference import contract
from build_image_probe import (COORDS, audit_probe_spirv, bilinear_reference,
                               pack_image_probe, payload_layout_sha256, shader_source)


class ImageProbeContractTests(unittest.TestCase):
    def test_cpu_oracle_and_shader_use_canonical_coordinates_and_channels(self):
        c = contract()
        self.assertEqual(COORDS, list(zip(c['u'], c['v'])))
        expected = [bilinear_reference()[lane][ch] for ch in range(4) for lane in range(16)]
        self.assertEqual(c['expected'], expected)
        self.assertEqual(c['texels_row_major_rgba'], [[1., 2., 3., 4.], [5., 6., 7., 8.],
                                                       [9., 10., 11., 12.], [13., 14., 15., 16.]])

    def test_shader_uses_real_sample_address_conversion_and_oword_store_imports(self):
        source = shader_source()
        for abi in ('llvm.genx.address.convert.i32.p1opencl.image2d_ro_t',
                    'llvm.genx.address.convert.i32.p1intel.buffer_rw_t',
                    'llvm.genx.address.convert.i32.p2opencl.sampler_t',
                    'llvm.genx.3d.sample.v64f32.', 'llvm.genx.oword.st.v4f32'):
            self.assertIn(abi, source)
        self.assertIn('OpEntryPoint Kernel %probe "bridge_image_probe"', source)
        self.assertIn('%sampler_bti = OpFunctionCall %uint %sampler_convert %arg2', source)
        self.assertIn('%sample_lz_opcode = OpConstant %uint 24', source)
        self.assertIn('%channelmask = OpConstant %uint 15', source)
        self.assertIn('%sampled = OpFunctionCall %v64f %sample %sample_lz_opcode %mask '
                      '%channelmask %s0 %sampler_bti %image_bti', source)
        self.assertEqual(source.count('%write'), 16)
        first_function = source.index('%image_convert = OpFunction')
        self.assertLess(source.index('OpExtInstImport'), source.index('OpMemoryModel'))
        self.assertLess(source.index('%true = OpConstantTrue'), source.index('%mask = OpConstantComposite'))
        for line in source.splitlines():
            if ' = OpConstant' in line:
                self.assertLess(source.index(line), first_function, line)
        for channel in range(4):
            self.assertIn(f'%offset{channel}_0 = OpConstant %uint {channel*4}', source)
            self.assertIn(f'%part{channel}_0 = OpVectorShuffle %v4f %sampled %sampled '
                          + ' '.join(str(channel*16+i) for i in range(4)), source)

    def test_spirv_audit_requires_imports_and_entry_point(self):
        source = shader_source()
        audit_probe_spirv(source)
        with self.assertRaisesRegex(ValueError, 'real compiler import'):
            audit_probe_spirv(source.replace('llvm.genx.3d.sample.v64f32.', 'fake.sample.'))

    def test_packer_derives_only_surface_btis_and_explicit_heap_mapping(self):
        code, zebin = b'own sample kernel', b'zebin fixture'
        report = {'execution_env': {'has_sample': True, 'has_dpas': False, 'grf_count': 128,
                                    'simd_size': 1},
                  'binding_table_indices': [{'arg_index': 0, 'bti_value': 4},
                                            {'arg_index': 1, 'bti_value': 9}],
                  'payload_arguments': [
                      {'arg_type': 'arg_bypointer', 'offset': 8, 'size': 8, 'arg_index': 1,
                       'addrmode': 'stateful', 'addrspace': 'global', 'access_type': 'readwrite'},
                      {'arg_type': 'arg_bypointer', 'offset': 0, 'size': 0, 'arg_index': 0,
                       'addrspace': 'image', 'image_type': 'image_2d', 'access_type': 'readonly'},
                      {'arg_type': 'arg_bypointer', 'offset': 0, 'size': 0, 'arg_index': 1,
                       'addrspace': 'global', 'access_type': 'readwrite'},
                      {'arg_type': 'arg_bypointer', 'offset': 0, 'size': 0, 'arg_index': 2,
                       'addrspace': 'sampler', 'sampler_index': 0},
                      {'arg_type': 'private_base_stateless', 'offset': 0, 'size': 8}],
                  'per_thread_payload_arguments': [{'arg_type': 'packed_local_ids',
                                                    'offset': 0, 'size': 6}],
                  'code_sha256': hashlib.sha256(code).hexdigest(),
                  'zebin_sha256': hashlib.sha256(zebin).hexdigest()}
        payload = {'status': 'restricted-static-no-read', 'zebin_sha256': report['zebin_sha256'],
                   'code_sha256': report['code_sha256'],
                   'payload_layout_sha256': payload_layout_sha256(report),
                   'native_asm_sha256': 'native-hash', 'loads': [{'line': 1}]}
        with mock.patch('build_image_probe.inspect', return_value=report), \
             mock.patch('build_image_probe.sections', return_value={'.text.bridge_image_probe': code}):
            cmk, emitted_report = pack_image_probe(zebin, payload)
        self.assertEqual(cmk[:4], b'CMK3')
        self.assertEqual(struct.unpack_from('<III', cmk, 168), (0, 0, 4))
        self.assertEqual(struct.unpack_from('<II', cmk, 472), (1, 52))
        self.assertEqual(struct.unpack_from('<3I', cmk, 20), (1, 1, 1))
        self.assertEqual(struct.unpack_from('<I', cmk, 16), (0x80000000,))
        self.assertEqual(struct.unpack_from('<2I', cmk, 280), (0, 1))
        self.assertEqual(struct.unpack_from('<2I', cmk, 376), (0, 0))
        self.assertEqual(emitted_report, report)
        report['execution_env']['simd_size'] = 16
        with mock.patch('build_image_probe.inspect', return_value=report):
            with self.assertRaisesRegex(ValueError, 'SIMD1'):
                pack_image_probe(zebin, payload)


if __name__ == '__main__':
    unittest.main()
