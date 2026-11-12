"""CPU-only tests for the PRE initial-contents/oracle spec. No GPU, no invented data."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from inspect_pre_initial_contents import (
    TRACE_REQUIRED, extract_static_plan, inspect, oracle_policy,
    resource_table, validate_trace_candidate,
)

IR = ROOT / 'analysis/fsr-resources/xe2-first.spvasm'


def fixture():
    return '\n'.join([
        '%587 = OpTypeBufferSurfaceINTEL ReadWrite',
        '%591 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadWrite',
        '%595 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly',
        '%uint_120 = OpConstant %uint 120',
        '%uint_540 = OpConstant %uint 540',
        '%uint_1024 = OpConstant %uint 1024',
        '%uint_4096 = OpConstant %uint 4096',
        '%uint_8192 = OpConstant %uint 8192',
        '%uint_512 = OpConstant %uint 512',
        '%uint_960 = OpConstant %uint 960',
        '%uint_8 = OpConstant %uint 8',
        '%ushort_100 = OpConstant %ushort 100',
        '%ushort_104 = OpConstant %ushort 104',
        '%a = OpFunctionCall %v32uint %llvm_genx_oword_ld_unaligned_v32i32 %x %y',
        '%b = OpFunctionCall %v32uint %llvm_genx_oword_ld_v32i32 %x %y',
        '%c = OpFunctionCall %v4float %llvm_genx_oword_ld_unaligned_v4f32 %x %y',
        '%d = OpFunctionCall %v4float %llvm_genx_oword_ld_v4f32 %x %y',
        '%e = OpFunctionCall %void %llvm_genx_oword_st_v128i8 %x %y %z',
        '%f = OpFunctionCall %void %llvm_genx_lsc_store_quad_typed_bti_v16i1 %p %uchar_0 %uchar_0 %uchar_7 %9780 %u %v %r %lod %data',
    ])


def complete_trace():
    trace = {'dispatch_grid': (120, 540, 1), 'local_size': 'TRACE_PINNED',
             'arg0': {'width_bytes': 8294400, 'base_u32': 64, 'flags_u32': 0, 'bytes_sha256': 'a' * 64},
             'arg9': {'bytes_sha256': 'b' * 64},
             'arg10': {'header_hex128': '00' * 128, 'flags_u32': 0, 'base_u32': 64}}
    for i in (1, 2, 3, 4, 5, 6, 7, 8):
        trace[f'arg{i}'] = {'dxgi_format': 'FROM_TRACE', 'width': 1920, 'height': 1080,
                            'view_desc': 'FROM_TRACE', 'bytes_sha256': 'c' * 64}
    return trace


class StaticPlanTests(unittest.TestCase):
    def test_extracts_header_flags_and_plane(self):
        plan = extract_static_plan(fixture())
        self.assertEqual(plan['header_bytes'], 128)
        self.assertEqual(plan['header_flags_byte'], 100)
        self.assertEqual(plan['header_base_byte'], 104)
        self.assertEqual(set(plan['flag_bits_observed']),
                         {'0x400', '0x1000', '0x2000', '0x200'})
        self.assertEqual(plan['grid_guards'], {'x_at_least': 120, 'y_at_least': 540})
        self.assertEqual(plan['store_channel_mask'], 7)

    def test_rejects_missing_anchor(self):
        with self.assertRaisesRegex(ValueError, 'anchor'):
            extract_static_plan(fixture().replace('%ushort_104', '%ushort_105'))

    def test_rejects_unreviewed_hash(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed'):
            inspect(b'modified')


class ResourceTableTests(unittest.TestCase):
    def test_twelve_args_no_invented_formats(self):
        table = resource_table()
        self.assertEqual([r['arg'] for r in table], list(range(12)))
        images = [r for r in table if r['arg'] in (1, 2, 3, 4, 5, 6, 7, 8)]
        for row in images:
            self.assertIn('Unknown', row['cm_type'])
            self.assertEqual(row['visible_bytes'], TRACE_REQUIRED)
            self.assertEqual(row['initial_bytes'], TRACE_REQUIRED)

    def test_buffer_views_pinned(self):
        by_arg = {r['arg']: r for r in resource_table()}
        self.assertEqual(by_arg[9]['visible_bytes'], 2112)
        self.assertEqual(by_arg[10]['visible_bytes'], 128)
        self.assertIn('8294400', by_arg[0]['visible_bytes'])
        for arg in (0, 9, 10):
            self.assertIn('R8_UINT', by_arg[arg]['d3d_view'])

    def test_no_scene_semantics_assigned(self):
        text = ' '.join(f"{r['arg']}:{r['provenance']}:{r['constraint']}" for r in resource_table()).lower()
        for word in ('color', 'motion', 'depth map', 'albedo', 'normal map'):
            self.assertNotIn(word, text)

    def test_slot_name_assignment_stays_trace(self):
        for row in resource_table():
            if row['arg'] in (2, 3, 4, 5, 6, 7, 8):
                self.assertIn(TRACE_REQUIRED, row['provenance'])


class OraclePolicyTests(unittest.TestCase):
    def test_order_is_reference_then_cpu_then_bindings(self):
        order = oracle_policy()['order']
        self.assertEqual([o['rank'] for o in order], [1, 2, 3])
        self.assertIn('working', order[0]['what'] + order[0]['why_first'])
        self.assertIn('bindings', order[2]['name'] + order[2]['why_last'])

    def test_r8_exact_and_images_tbd(self):
        tol = oracle_policy()['tolerances']
        self.assertEqual(tol['R8_UINT_buffers']['value'], 0)
        self.assertIn(TRACE_REQUIRED, tol['images_Unknown_format'])

    def test_nan_is_fail(self):
        policy = oracle_policy()
        self.assertIn('FAIL', policy['nan_policy'])
        self.assertIn('NaN', policy['nan_policy'])

    def test_synthetic_probes_are_not_oracles(self):
        names = ' '.join(o['name'] + o['what'] for o in oracle_policy()['order'])
        self.assertNotIn('synthetic', names)
        self.assertNotIn('probe', names)


class TraceValidatorTests(unittest.TestCase):
    def test_complete_trace_passes(self):
        self.assertEqual(validate_trace_candidate(complete_trace()), [])

    def test_incomplete_trace_lists_missing(self):
        missing = validate_trace_candidate({'arg0': {}})
        self.assertIn('arg0.width_bytes', missing)
        self.assertIn('dispatch_grid', missing)
        self.assertIn('local_size', missing)

    def test_rejects_invented_scene_role(self):
        trace = complete_trace()
        trace['arg2']['scene_role'] = 'depth'
        with self.assertRaisesRegex(ValueError, 'invented'):
            validate_trace_candidate(trace)


@unittest.skipUnless(IR.is_file(), 'Requires the pinned local PRE disassembly')
class LocalPreContentsTests(unittest.TestCase):
    def test_pinned_module_matches_static_plan(self):
        result = inspect(IR.read_bytes())
        self.assertEqual(result['status'], 'static-spec-only')
        self.assertFalse(result['runtime_approved'])
        self.assertEqual(result['static_plan']['header_base_byte'], 104)
        self.assertEqual(len(result['resources']), 12)


if __name__ == '__main__':
    unittest.main()
