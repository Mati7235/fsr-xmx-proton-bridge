import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from inspect_pre_inputs import EXPECTED_ARGS, extract, inspect


def fixture(args=None, guards=None):
    args = EXPECTED_ARGS if args is None else args
    guards = ('%a = OpUGreaterThanEqual %bool %x %uint_120',
              '%b = OpUGreaterThanEqual %bool %y %uint_540') if guards is None else guards
    declarations = '\n'.join(
        f'%{i} = OpFunctionParameter {type_id}' for i, type_id in enumerate(args)
    )
    types = '\n'.join([
        '%587 = OpTypeBufferSurfaceINTEL ReadWrite',
        '%591 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadWrite',
        '%595 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly',
        '%599 = OpTypeSampler',
    ])
    return '\n'.join([
        types,
        '%10259 = OpFunction %void DontInline %603', declarations, '%label = OpLabel',
        *guards,
        '%1687 = OpFunctionCall %uint %llvm_genx_address_convert_i32_p1opencl_image2d_rw_t %606',
        'OpStore %3656 %1687',
        '%3749 = OpLoad %uint %3656',
        'OpStore %3460 %3749',
        '%9769 = OpLoad %uint %3460',
        'OpStore %3397 %9769',
        '%9774 = OpLoad %uint %3397',
        'OpStore %3391 %9774',
        '%9780 = OpLoad %uint %3391',
        '%a = OpFunctionCall %v16float %llvm_genx_3d_load_v16f32',
        '%b = OpFunctionCall %v64float %llvm_genx_3d_sample_v64f32',
        '%c = OpFunctionCall %void %llvm_genx_lsc_store_quad_typed_bti_v16i1 %predicate %uchar_0 %uchar_0 %uchar_7 %9780 %u %v %r %lod %data',
    ])


class PreInputContractTests(unittest.TestCase):
    def test_rejects_unreviewed_input_hash(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            inspect(fixture().encode())

    def test_extracts_resource_types_and_bounds_without_semantic_labels(self):
        result = extract(fixture())
        self.assertEqual(len(result['entry_argument_resources']), 12)
        self.assertEqual(result['entry_argument_resources'][0]['type'],
                         'BufferSurfaceINTEL ReadWrite')
        self.assertEqual(result['entry_argument_resources'][1]['type'],
                         'Image 2D ReadWrite; format Unknown')
        self.assertEqual(result['entry_argument_resources'][2]['type'],
                         'Image 2D ReadOnly; format Unknown')
        self.assertEqual(result['workgroup_id_guards'], {'x_at_least': 120, 'y_at_least': 540})
        self.assertEqual(result['typed_store_channel_masks'], [7])
        self.assertEqual(result['typed_store_surface_operands'], ['%9780'])
        self.assertEqual(result['typed_store_surface_origin_arg_index'], 1)
        self.assertEqual(result['image_format'], 'Unknown in OpTypeImage; not inferred here')

    def test_rejects_typed_store_surface_rebound_to_other_image(self):
        text = fixture().replace('OpStore %3656 %1687', 'OpStore %3656 %1688')
        with self.assertRaisesRegex(ValueError, 'surface SSA'):
            extract(text)

    def test_rejects_changed_resource_order(self):
        changed = EXPECTED_ARGS.copy()
        changed[1], changed[2] = changed[2], changed[1]
        with self.assertRaisesRegex(ValueError, 'argument order changed'):
            extract(fixture(changed))

    def test_rejects_missing_or_changed_guards(self):
        with self.assertRaisesRegex(ValueError, 'workgroup guard'):
            extract(fixture(guards=('%a = OpUGreaterThanEqual %bool %x %uint_120',)))

    def test_rejects_missing_operation_classes(self):
        text = fixture().replace('%llvm_genx_lsc_store_quad_typed_bti_v16i1', '%other')
        with self.assertRaisesRegex(ValueError, 'Expected image loads'):
            extract(text)


class LocalPreInputTests(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1] /
                         'analysis/fsr-resources/xe2-first.spvasm').is_file(),
                        'Requires the pinned local PRE disassembly')
    def test_pinned_real_module_matches_recorded_contract(self):
        path = Path(__file__).resolve().parents[1] / 'analysis/fsr-resources/xe2-first.spvasm'
        result = inspect(path.read_bytes())
        self.assertEqual(result['genx_operation_call_counts'],
                         {'3d_load': 78, '3d_sample': 85, 'typed_quad_store': 1})
        self.assertEqual(result['typed_store_surface_origin_arg_index'], 1)


if __name__ == '__main__':
    unittest.main()
