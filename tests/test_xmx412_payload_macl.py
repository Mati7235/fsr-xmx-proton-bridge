"""CPU-only tests for the minimal conservative macl/acc0 model (4.1.2 PRE).

No DLL is executed, no GPU/Wine/driver is touched. All checks are static:
synthetic IGA snippets plus the pinned offline 4.1.2 disassembly when present.
"""
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from audit_pre_payload import audit_native, parse_isa

SEED = '(W) send.ugm (1|M0) r2 r127 null:0 0xFF000000 0x6219C500 // wr:1+0, rd:1; load.ugm.d32x8t.a32.ca.cc.bti[255]'
END = '(W) send.gtwy (1|M0) null r127 null:0 0x0 0x02000010 // wr:1+0, rd:0; end of thread'


def native(*lines):
    return audit_native('\n'.join([SEED, *lines, END]), seed_line=1)


class MaclAccModelTests(unittest.TestCase):
    def test_macl_opcode_is_now_parsed(self):
        ins, _ = parse_isa('macl (1|M0) r1.0<1>:d r2.0<0;1,0>:d r80.1<0;1,0>:d')
        self.assertEqual(ins[0]['op'], 'macl')

    def test_unreviewed_opcodes_still_rejected(self):
        with self.assertRaises(ValueError):
            native('mach (1|M0) r1.0<1>:d r80.0<0;1,0>:d r80.1<0;1,0>:d')
        with self.assertRaises(ValueError):
            native('unknown (1|M0) r2.0<1>:ud 0x0:ud')

    def test_macl_benign_with_clean_acc_is_unread(self):
        r = native('mul (1|M0) acc0.0<1>:d r80.0<0;1,0>:d 1:w',
                   'macl (1|M0) r1.0<1>:d r80.1<0;1,0>:d r80.2<0;1,0>:d',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        self.assertEqual(r['status'], 'unread-before-overwrite-or-end')
        self.assertEqual(r['possible_reads'], [])

    def test_mac_implicit_read_clean_is_unread(self):
        r = native('mul (1|M0) acc0.0<1>:f r80.0<0;1,0>:f 1.0:f',
                   'mac (16|M0) r10.0<1>:f r16.0<1;1,0>:f r9.0<0;1,0>:f',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        self.assertEqual(r['possible_reads'], [])

    def test_r2_to_acc_is_a_possible_read(self):
        r = native('mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        self.assertEqual(r['status'], 'possible-read')
        self.assertEqual(r['possible_reads'][0]['offsets'], [0, 1, 2, 3])

    def test_macl_implicit_acc_read_is_modelled(self):
        r = native('mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   'macl (1|M0) r1.0<1>:d r80.0<0;1,0>:d r80.1<0;1,0>:d')
        self.assertEqual(r['status'], 'possible-read')
        # Both the GRF->acc copy and the implicit acc0 read at macl report.
        self.assertEqual(len(r['possible_reads']), 2)
        self.assertEqual(r['possible_reads'][1]['offsets'], [0, 1, 2, 3])

    def test_macl_with_r2_source_reports_grf_read(self):
        r = native('macl (1|M0) r1.0<1>:d r2.0<0;1,0>:d r80.1<0;1,0>:d',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        self.assertEqual(r['status'], 'possible-read')

    def test_acc_pair_overlap_is_conservative(self):
        # acc0/acc1 share a group: write acc0, read acc1 must still report.
        r = native('mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   'mul (1|M0) r3.0<1>:f acc1.0<1;1,0>:f 1.0:f')
        self.assertEqual(len(r['possible_reads']), 2)

    def test_acc_groups_are_isolated(self):
        # acc2 taint must not pollute the implicit acc0 read of macl.
        r = native('mov (1|M0) acc2.0<1>:ud r2.0<0;1,0>:ud',
                   'macl (1|M0) r1.0<1>:d r80.0<0;1,0>:d r80.1<0;1,0>:d')
        self.assertEqual(len(r['possible_reads']), 1)

    def test_clean_acc_overwrite_clears_taint(self):
        r = native('mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   'mov (1|M0) acc0.0<1>:ud 0x0:ud',
                   'mul (1|M0) r3.0<1>:f acc0.0<1;1,0>:f 1.0:f',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        # Only the first copy reports; the post-clean read must not.
        self.assertEqual(len(r['possible_reads']), 1)

    def test_predicated_acc_write_does_not_kill(self):
        r = native('(f0.0) mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   'mul (1|M0) r3.0<1>:f acc0.0<1;1,0>:f 1.0:f',
                   'mov (8|M0) r2.0<1>:ud 0x0:ud')
        self.assertEqual(len(r['possible_reads']), 2)

    def test_sel_to_acc_kills_like_grf_sel(self):
        r = native('mov (1|M0) acc0.0<1>:ud r2.0<0;1,0>:ud',
                   '(f0.0) sel (1|M0) acc0.0<1>:ud 0x0:ud 0x0:ud',
                   'mul (1|M0) r3.0<1>:f acc0.0<1;1,0>:f 1.0:f')
        self.assertEqual(len(r['possible_reads']), 1)


NEW_ASM = ROOT / 'analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm'


@unittest.skipUnless(NEW_ASM.is_file(), 'Offline 4.1.2 disassembly absent')
class Real412KernelTests(unittest.TestCase):
    def test_412_native_is_unread_with_macl_model(self):
        r = audit_native(NEW_ASM.read_text(encoding='utf-8'), 11)
        self.assertEqual(r['status'], 'unread-before-overwrite-or-end')
        self.assertEqual(r['possible_reads'], [])
        self.assertEqual(r['visited_instructions_with_live_bytes'], 160)
        self.assertEqual([o['line'] for o in r['overwrites']],
                         [20, 23, 143, 179, 379])


if __name__ == '__main__':
    unittest.main()
