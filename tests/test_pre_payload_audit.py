"""CPU-only tests for the restricted static PRE audit, including false-safe traps."""
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from audit_pre_payload import audit_ir, audit_native, build_report

SEED = '(W) send.ugm (1|M0) r2 r127 null:0 0xFF000000 0x6219C500 // wr:1+0, rd:1; load.ugm.d32x8t.a32.ca.cc.bti[255]'
END = '(W) send.gtwy (1|M0) null r127 null:0 0x0 0x02000010 // wr:1+0, rd:0; end of thread'


def native(*lines):
    return audit_native('\n'.join([SEED, *lines, END]), seed_line=1)


def ir_fixture(extra_use='', type_definition='OpTypeBufferSurfaceINTEL ReadWrite'):
    body_params = '\n'.join(f'%b{i} = OpFunctionParameter %surface' for i in range(12))
    entry_params = '\n'.join(f'%e{i} = OpFunctionParameter %surface' for i in range(12))
    args = ' '.join(f'%e{i}' for i in range(12))
    conversions = '\n'.join(f'%c{i} = OpFunctionCall %uint %convert %b{i}' for i in (0, 9, 10))
    return f'''OpEntryPoint Kernel %entry "fsr4_pre_xmx"
OpDecorate %convert LinkageAttributes "llvm.genx.address.convert.i32.p1intel.buffer_rw_t" Import
%surface = {type_definition}
%body = OpFunction %void DontInline %fn
{body_params}
%bodylabel = OpLabel
{conversions}
{extra_use}
OpReturn
OpFunctionEnd
%entry = OpFunction %void DontInline %fn
{entry_params}
%entrylabel = OpLabel
%call = OpFunctionCall %void %body {args}
OpReturn
OpFunctionEnd
'''


class NativePayloadTests(unittest.TestCase):
    def test_direct_read_is_not_safe(self):
        r = native('mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['possible_reads'][0]['offsets'], [0, 1, 2, 3])

    def test_partial_overwrite_does_not_kill_other_bytes(self):
        r = native('mov (1|M0) r2.0<1>:ud 0x0:ud',
                   'mov (1|M0) r3.0<1>:ud r2.1<0;1,0>:ud')
        self.assertEqual(r['possible_reads'][0]['offsets'], [4, 5, 6, 7])

    def test_read_before_same_instruction_write(self):
        r = native('add (1|M0) r2.0<1>:ud r2.0<0;1,0>:ud 0x1:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_complete_overwrite(self):
        r = native('mov (8|M0) r2.0<1>:ud 0x0:ud',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['possible_reads'], [])

    def test_predicated_write_cannot_prove_dead(self):
        r = native('(f0.0) mov (8|M0) r2.0<1>:ud 0x0:ud',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_sel_predicate_selects_value_not_write_enable(self):
        r = native('(f0.0) sel (8|M0) r2.0<1>:ud r4.0<1;1,0>:ud 0x0:ud',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['possible_reads'], [])

    def test_join_preserves_bytes_from_path_without_overwrite(self):
        r = native('(W&f0.0) jmpi L100',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud', 'L100:',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_unconditional_jump_skips_unreachable_read(self):
        r = native('(W) jmpi L100', 'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud', 'L100:')
        self.assertEqual(r['possible_reads'], [])

    def test_loop_reaches_fixed_point(self):
        r = native('L100:', '(f0.0) mov (8|M0) r2.0<1>:ud 0x0:ud',
                   '(W&f0.0) jmpi L100', 'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_transpose_address_uses_one_dword_not_grf_padding(self):
        r = native('mov (1|M0) r2.0<1>:ud 0x0:ud',
                   'send.ugm (1|M0) r4 r2 null:0 0x8000000 0x6210B500 // wr:1+0, rd:1; load.ugm.d32x4t.a32.bti[8]')
        self.assertEqual(r['possible_reads'], [])

    def test_transpose_store_reads_all_data_components(self):
        r = native('mov (2|M0) r2.0<1>:ud 0x0:ud',
                   'send.ugm (1|M0) null r4 r2:1 0x8000000 0x6200B504 // wr:1+1, rd:0; store.ugm.d32x4t.a32.bti[8]')
        self.assertEqual(r['possible_reads'][0]['offsets'], list(range(8, 16)))

    def test_short_load_response_does_not_kill_entire_grf(self):
        r = native('send.ugm (1|M0) r2 r4 null:0 0x8000000 0x6210B500 // wr:1+0, rd:1; load.ugm.d32x4t.a32.bti[8]',
                   'mov (1|M0) r3.0<1>:ud r2.4<0;1,0>:ud')
        self.assertEqual(r['possible_reads'][0]['offsets'], list(range(16, 20)))

    def test_predicated_load_response_does_not_kill(self):
        r = native('(f0.0) send.ugm (1|M0) r2 r4 null:0 0x8000000 0x6210B500 // wr:1+0, rd:1; load.ugm.d32x4t.a32.bti[8]',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_unknown_ternary_footprint_is_conservative(self):
        r = native('mad (1|M0) r3.0<1>:ud r1.0<4;1>:ud 0x0:ud 0x0:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_unsupported_opcode_rejected(self):
        with self.assertRaises(ValueError):
            native('unknown (1|M0) r2.0<1>:ud 0x0:ud')

    def test_indirect_addressing_rejected(self):
        with self.assertRaises(ValueError):
            native('mov (1|M0) r3.0<1>:ud r[a0.0]<0;1,0>:ud')

    def test_unknown_branch_rejected(self):
        with self.assertRaises(ValueError):
            native('(W) jmpi L999')

    def test_live_path_cannot_fall_off_end(self):
        with self.assertRaises(ValueError):
            audit_native(SEED+'\nnop', seed_line=1)

    def test_full_mask_assumption_is_explicit(self):
        self.assertIn('full constant thread execution mask', native()['assumptions'])

    # Fase 3 hardening: predicated stores, diamond joins, backedges with
    # partial kills, and fail-closed send/transpose decoding. All CPU-only.
    def test_predicated_store_response_does_not_kill(self):
        r = native('(f0.0) send.ugm (1|M0) null r4 r2:1 0x8000000 0x6200B504 // wr:1+1, rd:0; store.ugm.d32x4t.a32.bti[8]',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_predicated_partial_overwrite_preserves_all_bytes(self):
        r = native('(f0.0) mov (1|M0) r2.0<1>:ud 0x0:ud',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['possible_reads'][0]['offsets'], [0, 1, 2, 3])

    def test_diamond_join_union_preserves_complementary_halves(self):
        # Each branch kills a complementary half; union must keep both live,
        # so the later read is still a possible read (conservative).
        r = native('(W&f0.0) jmpi L100',
                   'mov (4|M0) r2.0<1>:ud 0x0:ud',
                   '(W) jmpi L200',
                   'L100:',
                   'mov (4|M0) r2.4<1>:ud 0x0:ud',
                   'L200:',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_diamond_join_both_branches_full_kill_is_safe(self):
        r = native('(W&f0.0) jmpi L100',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud',
                   '(W) jmpi L200',
                   'L100:',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud',
                   'L200:',
                   'mov (1|M0) r3.0<1>:ud r2.0<0;1,0>:ud')
        self.assertEqual(r['possible_reads'], [])

    def test_backedge_partial_kill_needs_fixed_point(self):
        r = native('L100:',
                   'mov (4|M0) r2.0<1>:ud 0x0:ud',
                   '(W&f0.0) jmpi L100',
                   'mov (1|M0) r3.0<1>:ud r2.4<0;1,0>:ud')
        # Low half is killed on every iteration, high half survives the loop.
        self.assertEqual(r['possible_reads'][0]['offsets'], list(range(16, 20)))

    def test_illegal_with_live_bytes_rejected(self):
        with self.assertRaisesRegex(ValueError, 'illegal/padding'):
            audit_native('\n'.join([SEED, 'illegal', END]), seed_line=1)

    def test_missing_send_lengths_rejected(self):
        with self.assertRaisesRegex(ValueError, 'decoded message lengths'):
            native('send.ugm (1|M0) r2 r4 null:0 0x0 0x0 // no lengths')

    def test_register_descriptor_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Register-based message descriptor'):
            native('send.ugm (1|M0) r2 r4 null:0 r5 0x0 // wr:1+0, rd:1; load.ugm.d32x4t.a32.bti[8]')

    def test_transpose_wrong_width_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Transpose is only modelled for SIMD1'):
            native('send.ugm (8|M0) r4 r2 null:0 0x8000000 0x6210B500 // wr:1+0, rd:1; load.ugm.d32x4t.a32.bti[8]')

    def test_transpose_load_with_data_input_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected load data input'):
            native('send.ugm (1|M0) r4 r2 r4:1 0x8000000 0x6210B500 // wr:1+1, rd:1; load.ugm.d32x4t.a32.bti[8]')

    def test_transpose_store_with_response_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unexpected store response'):
            native('send.ugm (1|M0) r4 r4 r2:1 0x8000000 0x6200B504 // wr:1+1, rd:1; store.ugm.d32x4t.a32.bti[8]')


class IrSurfaceTests(unittest.TestCase):
    def test_opaque_surface_conversion(self):
        r = audit_ir(ir_fixture())
        self.assertEqual([p['arg_index'] for p in r], [0, 9, 10])

    def test_extra_use_rejected(self):
        with self.assertRaises(ValueError):
            audit_ir(ir_fixture(extra_use='OpStore %sink %b0'))

    def test_pointer_not_opaque_surface_rejected(self):
        with self.assertRaises(ValueError):
            audit_ir(ir_fixture(type_definition='OpTypePointer CrossWorkgroup %uint'))

    def test_wrapper_reordering_rejected(self):
        text = ir_fixture().replace('%body %e0 %e1 ', '%body %e1 %e0 ')
        with self.assertRaises(ValueError):
            audit_ir(text)


REQUIRED = ['analysis/cm-payloads-0001/module-0000.cmspv',
            'analysis/offline-pre/full/pre_bmg.bin',
            'analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm',
            'analysis/pre-payload/embedded.spvasm']


@unittest.skipUnless(all((ROOT/p).exists() for p in REQUIRED), 'Optional compiled/disassembled PRE absent')
class LocalPreAuditTests(unittest.TestCase):
    def test_matches_recorded_static_audit(self):
        report = build_report(*[(ROOT/p).read_bytes() for p in REQUIRED])
        recorded = json.loads((ROOT/'profiles/fsr4-pre-native1080-payload-audit.json').read_text())
        self.assertEqual(report, recorded)
        self.assertEqual(report['native_byte_liveness']['possible_reads'], [])
        self.assertFalse(report['runtime_approved'])
        mapping = json.loads((ROOT/'profiles/fsr4-pre-native1080-bmg.json').read_text())
        self.assertEqual(mapping['code_sha256'], report['code_sha256'])
        self.assertEqual(mapping['payload_review']['status'], 'static-unread-under-full-mask')
        self.assertFalse(mapping['payload_review']['runtime_approved'])
        self.assertEqual(ROOT/mapping['payload_review']['evidence'],
                         ROOT/'profiles/fsr4-pre-native1080-payload-audit.json')

    def test_changed_native_assembly_rejected(self):
        source, zebin, asm, ir = [(ROOT/p).read_bytes() for p in REQUIRED]
        with self.assertRaisesRegex(ValueError, 'native disassembly'):
            build_report(source, zebin, asm+b'\nnop\n', ir)

    def test_changed_ir_assembly_rejected(self):
        source, zebin, asm, ir = [(ROOT/p).read_bytes() for p in REQUIRED]
        with self.assertRaisesRegex(ValueError, 'IR disassembly'):
            build_report(source, zebin, asm, ir+b'\n')

    def test_changed_input_rejected(self):
        source, zebin, asm, ir = [(ROOT/p).read_bytes() for p in REQUIRED]
        with self.assertRaisesRegex(ValueError, 'CM input'):
            build_report(source+b'\0', zebin, asm, ir)


if __name__ == '__main__':
    unittest.main()
