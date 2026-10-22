"""CPU-only metadata/adapter tests; optional local compiler artifacts stay ignored."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from apply_cmk_mapping import convert
from build_anv_mapping_patch import adapt
from inspect_zebin import metadata, sections


def fixture():
    code = b'not executable GPU fixture'
    header = bytearray(472)
    header[:4] = b'CMK2'
    struct.pack_into('<I', header, 4, len(code))
    struct.pack_into('<I', header, 180, 2)
    struct.pack_into('<2I', header, 184, 8, 9)
    profile = {'schema_version': 1, 'status': 'experimental-offline-only',
               'code_sha256': hashlib.sha256(code).hexdigest(),
               'table_pc_base': 4, 'expected_push_size': 16,
               'surfaces': [{'arg_index': i, 'bti': bti, 'table_index': i,
                             'element': 0, 'push_byte_offset': 4+4*i}
                            for i, bti in enumerate([8, 9])]}
    return bytes(header)+code, profile


class MappingAdapterTests(unittest.TestCase):
    def test_cmk3_preserves_code_and_inserts_extension(self):
        legacy, profile = fixture()
        result = convert(legacy, profile)
        self.assertEqual(result[:4], b'CMK3')
        self.assertEqual(result[480:], legacy[472:])
        self.assertEqual(result[4:168], legacy[4:168])
        self.assertEqual(struct.unpack_from('<II', result, 472), (1, 16))
        self.assertEqual(struct.unpack_from('<III', result, 168), (0xffffffff, 0, 4))

    def test_native_code_hash_mismatch(self):
        legacy, profile = fixture()
        with self.assertRaises(ValueError):
            convert(legacy+b'changed', profile)
        profile['code_sha256'] = '0'*64
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_wrong_magic(self):
        legacy, profile = fixture()
        with self.assertRaises(ValueError):
            convert(b'CMK3'+legacy[4:], profile)

    def test_wrong_surface_count(self):
        legacy, profile = fixture()
        profile['surfaces'].pop()
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_bti_mismatch(self):
        legacy, profile = fixture()
        profile['surfaces'][0]['bti'] = 1
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_out_of_range_mapping(self):
        legacy, profile = fixture()
        profile['surfaces'][0].update(table_index=10, push_byte_offset=44)
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_unaligned_base(self):
        legacy, profile = fixture()
        profile['table_pc_base'] = 3
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_negative_element(self):
        legacy, profile = fixture()
        profile['surfaces'][0]['element'] = -1
        with self.assertRaises(ValueError):
            convert(legacy, profile)

    def test_nonexperimental_profile_rejected(self):
        legacy, profile = fixture()
        profile['status'] = 'runtime-approved'
        with self.assertRaises(ValueError):
            convert(legacy, profile)


class ZebinMetadataTests(unittest.TestCase):
    def test_exact_kernel_name_not_prefix(self):
        info = '''kernels:
  - name: fsr4_pre_xmx_extra
    execution_env:
      grf_count: 64
  - name: fsr4_pre_xmx
    execution_env:
      grf_count: 128
      has_dpas: true
    binding_table_indices:
      - bti_value: 8
        arg_index: 0
'''
        r = metadata(info, 'fsr4_pre_xmx')
        self.assertEqual(r['execution_env']['grf_count'], 128)
        self.assertIs(r['execution_env']['has_dpas'], True)
        self.assertEqual(r['binding_table_indices'], [{'bti_value': 8, 'arg_index': 0}])

    def test_truncated_elf(self):
        with self.assertRaises(ValueError):
            sections(b'\x7fELF\x02\x01')

    def test_missing_kernel(self):
        with self.assertRaises(ValueError):
            metadata('kernels:\n  - name: other\n', 'expected')


@unittest.skipUnless((ROOT/'upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch').exists(),
                     'Optional upstream checkout absent')
class ReaderPatchTests(unittest.TestCase):
    def test_both_patch_variants_preserve_legacy_and_guard_explicit_base(self):
        for relative in ['patches/0001-anv-cm-kernel-injection.patch',
                         'patches/mesa-26.3/0001-anv-cm-kernel-injection.patch']:
            original = (ROOT/'upstream/xess-xmx-linux'/relative).read_text()
            updated = adapt(original)
            self.assertIn('memcmp(h.magic, "CMK2", 4) != 0 && memcmp(h.magic, "CMK3", 4) != 0', updated)
            self.assertIn('if (auto_heap && !explicit_table_base)', updated)
            self.assertIn('push_size == mapping[1]', updated)
            self.assertIn('off + 4 <= push_size', updated)

    @unittest.skipUnless(shutil.which('cc'), 'C compiler absent')
    def test_actual_inserted_c_validation_with_synthetic_layouts(self):
        original = (ROOT/'upstream/xess-xmx-linux/patches/0001-anv-cm-kernel-injection.patch').read_text()
        added = '\n'.join(l[1:] for l in adapt(original).splitlines() if l.startswith('+') and not l.startswith('+++'))
        begin = added.index('   if (explicit_table_base) {\n      uint64_t push_size')
        end = added.index('   if (cs->cm_has_sampler)', begin)
        block = added[begin:end]
        harness = '''#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <assert.h>
#define ANV_CM_FAILED -1
struct range { uint32_t offset, size; };
struct info { uint32_t push_constant_range_count; struct range *push_constant_ranges; };
struct header { uint32_t table_pc_base, nsurf, table_idx[24]; };
static int validate(struct header h, uint32_t expected, struct info *ci) {
 const bool explicit_table_base = true;
 uint32_t mapping[2] = {1, expected};
 int state = 7, saved = 7, *cs = &state;
 const char *path = "synthetic-test";
'''+block+'''
 return 0;
}
int main(void) {
 struct range ranges[] = {{0,52}};
 struct info ci = {1, ranges};
 struct header h = {.table_pc_base=4, .nsurf=11};
 for (unsigned i=0; i<11; i++) h.table_idx[i]=i;
 assert(validate(h,52,&ci)==0);
 assert(validate(h,56,&ci)==-1);
 h.table_idx[10]=12;
 assert(validate(h,52,&ci)==-1);
 h.table_idx[10]=0xffffffffu;
 assert(validate(h,52,&ci)==-1);
 h.table_idx[10]=10;
 ranges[0].offset=8; ranges[0].size=44;
 assert(validate(h,52,&ci)==-1);
 ci.push_constant_range_count=0;
 assert(validate(h,52,&ci)==-1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix='cmk-reader-test-') as temp:
            source = Path(temp)/'test.c'
            binary = Path(temp)/'test'
            source.write_text(harness)
            result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless((ROOT/'analysis/offline-pre/full/pre_bmg.bin').exists(),
                     'Optional offline compiler outputs absent')
class LocalCompiledArtifactTests(unittest.TestCase):
    def test_stripped_options_output_cannot_be_registered_as_full(self):
        from build_pre_profile import build
        source = (ROOT/'analysis/cm-payloads-0001/module-0000.cmspv').read_bytes()
        control = ROOT/'analysis/offline-pre/stripped/pre_bmg.bin'
        if not control.exists():
            self.skipTest('Optional stripped-input control absent')
        with self.assertRaisesRegex(ValueError, 'compiler output/options'):
            build(source, control.read_bytes())

    def test_unreviewed_input_rejected(self):
        from build_pre_profile import build
        with self.assertRaises(ValueError):
            build(b'unreviewed input', b'unreviewed zebin')

    def test_profile_and_cmk_match_compiled_code(self):
        from build_pre_profile import build
        from inspect_zebin import inspect
        source = (ROOT/'analysis/cm-payloads-0001/module-0000.cmspv').read_bytes()
        zebin = (ROOT/'analysis/offline-pre/full/pre_bmg.bin').read_bytes()
        profile = build(source, zebin)
        recorded = json.loads((ROOT/'profiles/fsr4-pre-native1080-bmg.json').read_text())
        self.assertEqual(profile, recorded)
        legacy = (ROOT/'analysis/offline-pre/full/pre-legacy.cmk').read_bytes()
        result = convert(legacy, profile)
        self.assertEqual(result, (ROOT/'analysis/offline-pre/full/pre-explicit.cmk3').read_bytes())
        self.assertEqual(inspect(zebin, 'fsr4_pre_xmx')['execution_env']['grf_count'], 128)


if __name__ == '__main__':
    unittest.main()
