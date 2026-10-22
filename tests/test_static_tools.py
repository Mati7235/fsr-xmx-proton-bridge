"""Synthetic fixtures only: no proprietary DLLs or GPU execution required."""
import importlib.util
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tools'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


resources = load('extract_resources')
spirv = load('carve_spirv')
mscf = load('decompress_mscf')
payloads = load('parse_cm_payloads')
pre = load('reconstruct_pre')


def pe_fixture():
    data = bytearray(0x400)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 0x3c, 0x80)
    data[0x80:0x84] = b'PE\0\0'
    struct.pack_into('<H', data, 0x86, 1)
    struct.pack_into('<H', data, 0x94, 240)
    struct.pack_into('<H', data, 0x98, 0x20b)
    struct.pack_into('<II', data, 0x98+112+16, 0x1000, 0x100)
    section = 0x98+240
    struct.pack_into('<IIII', data, section+8, 0x200, 0x1000, 0x200, 0x200)
    # One root leaf is sufficient to test RVA translation; no path-depth assumption.
    struct.pack_into('<HH', data, 0x200+12, 0, 1)
    struct.pack_into('<II', data, 0x210, 40101, 0x20)
    struct.pack_into('<IIII', data, 0x220, 0x1080, 4, 0, 0)
    data[0x280:0x284] = b'test'
    return data


def module_fixture():
    header = struct.pack('<5I', 0x07230203, 0x10100, 0, 2, 0)
    entry = struct.pack('<4I', (4 << 16) | 15, 6, 1, 0x0000006b)
    return header+entry+struct.pack('<I', (1 << 16) | 56)


class ResourceTests(unittest.TestCase):
    def test_leaf(self):
        self.assertEqual(resources.extract(pe_fixture()), [([40101], b'test')])

    def test_truncated(self):
        with self.assertRaises(ValueError):
            resources.extract(bytes(pe_fixture()[:0x100]))

    def test_signature(self):
        with self.assertRaises(ValueError):
            resources.extract(b'no')

    def test_bad_rva(self):
        data = pe_fixture()
        struct.pack_into('<I', data, 0x220, 0x99999)
        with self.assertRaises(ValueError):
            resources.extract(data)

    def test_cycle(self):
        data = pe_fixture()
        struct.pack_into('<I', data, 0x214, 0x80000000)
        with self.assertRaises(ValueError):
            resources.extract(data)


class SpirvTests(unittest.TestCase):
    def test_entry_and_gap(self):
        result = spirv.carve(module_fixture()+b'-vc-payload\0')
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['entries'][0]['name'], 'k')
        self.assertEqual(result[0]['gap_ascii_strings'], ['-vc-payload'])
        self.assertEqual(result[0]['blob'], module_fixture())

    def test_two_modules(self):
        result = spirv.carve(module_fixture()+b'padding'+module_fixture())
        self.assertEqual(len(result), 2)

    def test_truncated_instruction(self):
        self.assertEqual(spirv.carve(module_fixture()[:-1]), [])

    def test_bad_schema(self):
        data = bytearray(module_fixture())
        struct.pack_into('<I', data, 16, 1)
        self.assertEqual(spirv.carve(data), [])

    def test_no_signature(self):
        self.assertEqual(spirv.carve(b'not SPIR-V'), [])


def envelope_fixture(ir=None, option_a=b'-vc-payload'):
    if ir is None:
        ir = module_fixture()
    options = option_a+b'\0'+b' -target-features=+ocl_runtime\0'
    trailer_size = len(options)+16+len(payloads.MARKER)
    return ir+options+struct.pack('<QQ', len(ir), trailer_size)+payloads.MARKER


class PayloadTests(unittest.TestCase):
    def test_exact_lengths(self):
        blob = envelope_fixture()
        records = payloads.parse(blob)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['ir_size'], len(module_fixture()))
        self.assertEqual(records[0]['envelope_size'], len(blob))
        self.assertEqual(records[0]['embedded_string_b'], ' -target-features=+ocl_runtime')

    def test_internal_magic_is_not_a_boundary(self):
        blob = envelope_fixture(module_fixture()+payloads.SPIRV)
        self.assertEqual(len(payloads.parse(blob)), 1)

    def test_large_non_ir_gap_does_not_extend_module(self):
        blob = envelope_fixture()+b'x'*140000+envelope_fixture()
        records = payloads.parse(blob)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['ir_size'], len(module_fixture()))
        self.assertFalse(payloads.gaps(blob, records)[0]['all_zero'])

    def test_padding(self):
        blob = envelope_fixture()+b'\0'*16+envelope_fixture()
        records = payloads.parse(blob)
        self.assertEqual(len(records), 2)
        self.assertTrue(payloads.gaps(blob, records)[0]['all_zero'])

    def test_quoted_options_preserved(self):
        option = b"-vc-payload -Xfinalizer '-noDPASMacro'"
        self.assertEqual(payloads.parse(envelope_fixture(option_a=option))[0]['embedded_string_a'], option.decode())

    def test_missing_marker(self):
        self.assertEqual(payloads.parse(envelope_fixture()[:-1]), [])

    def test_invalid_footer(self):
        blob = bytearray(envelope_fixture())
        struct.pack_into('<Q', blob, len(blob)-27, 2**63)
        self.assertEqual(payloads.parse(blob), [])


class PreLayoutTests(unittest.TestCase):
    def test_sampler_table_shift(self):
        report = pre.pre_layout([7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10])
        self.assertEqual(report['push_range_size'], 52)
        self.assertEqual(report['expected_surface_push_offsets'], list(range(4, 48, 4)))
        self.assertEqual(report['upstream_auto_push_offsets'], list(range(8, 52, 4)))
        self.assertEqual(report['upstream_auto_selected_roots'], list(range(2, 13)))
        self.assertEqual(report['tables'][-1]['heap'], 'sampler')

    def test_wrong_surface_count(self):
        with self.assertRaises(ValueError):
            pre.pre_layout([0])

    def test_dll_hash_guard(self):
        with self.assertRaises(ValueError):
            pre.reconstruct(b'unreviewed DLL')


@unittest.skipUnless(
    (ROOT/'artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll').exists()
    and all((ROOT/f'analysis/fsr-resources/resource-{n}.raw').exists() for n in ('0000', '0001', '0002')),
    'Optional local artifacts are not present',
)
class LocalArtifactTests(unittest.TestCase):
    def test_complete_pack_counts(self):
        for n, count in [('0000', 252), ('0001', 252), ('0002', 186)]:
            data = (ROOT/f'analysis/fsr-resources/resource-{n}.raw').read_bytes()
            self.assertEqual(len(payloads.parse(data)), count)

    def test_all_pre_table_lengths_include_footer(self):
        dll = (ROOT/'artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll').read_bytes()
        report = pre.reconstruct(dll)
        for key, n in [('pack_40101', '0000'), ('pack_40102', '0001')]:
            records = {r['offset']: r for r in payloads.parse(
                (ROOT/f'analysis/fsr-resources/resource-{n}.raw').read_bytes())}
            for variant in report['pre_variant_payloads']:
                table = variant[key]
                record = records[table['offset']]
                self.assertEqual(table['submitted_size'], record['envelope_size'])
                self.assertGreater(table['submitted_size'], record['ir_size'])


class CompressionTests(unittest.TestCase):
    def test_reject_header_before_loading_library(self):
        with self.assertRaises(ValueError):
            mscf.decode(b'bad', Path('/does/not/exist'))

    def test_reject_unknown_algorithm(self):
        data = b'\x0a\x51\xe5\xc0'+struct.pack('<HBBIIII', 24, 0, 4, 10, 0, 65536, 0)
        with self.assertRaises(ValueError):
            mscf.decode(data, Path('/does/not/exist'))


if __name__ == '__main__':
    unittest.main()
