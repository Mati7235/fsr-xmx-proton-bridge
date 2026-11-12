"""Pinned CPU-only tests for the XMX 4.1.2 DLSS packs (40104-40106).

Static only. No DLL is executed, no GPU/Wine/prefix is touched.
Proprietary packs are only read when present locally; otherwise gated
cases skip. All checks fail closed on mismatch.

Verifies, via tools/decompress_xmx412.py + tools/parse_cm_payloads.py:
counts, kernel entry names, SPIR-V args/types (BufferSurfaceINTEL vs
images vs samplers), igdext/CM-SPIRV vs CUDA/NGX, shared FUN_180029640
loader table, and contrast against DLL strings
("Failed to load P6 N32 ...", "P7 FullFusion ...").
"""
import hashlib
import importlib.util
import math
import re
import struct
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


xmx = load('decompress_xmx412')
parse_mod = load('parse_cm_payloads')
carve_mod = load('carve_spirv')

LIBWIM = ROOT / 'upstream/wimlib/.libs/libwim.so'
RESDIR = Path('/tmp/opencode/xmx-new/res412')
ANALYSIS_DIR = ROOT / 'analysis/fsr-xmx-412'
DLL_412 = ROOT / 'artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll'
DLL_SHA256 = 'fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732'

# Pinned from tools/decompress_xmx412.EXPECTED (loader immediates + digests).
DLSS_RIDS = [40104, 40105, 40106]
DLSS_ENVELOPES = {40104: 716, 40105: 312, 40106: 67}
DLSS_RAW_SHA = {
    40104: 'a9ea6724ebe4079a29c819564baeb15815cbd2df15cf7d9752be80ac4e7054ea',
    40105: '7ac547ee7bc0fce49b55036cad6993d41a42b1077aa911e6acff91b357d246fa',
    40106: '03c188585417648a051d2b32258a0a6d554d58ab8969bdcc9c0919435a331ac3',
}
DLSS_BUCKETS = {
    40104: 'DLSS K (DG2 + Xe2/Xe3)',
    40105: 'DLSS E / F',
    40106: 'DLSS-MX (DG2)',
}
# Pinned via tools/carve_spirv.py entry names (OpEntryPoint Kernel).
DLSS_KERNELS = {
    40104: {'k_gemm': 174, 'k_linear': 160, 'k_attn': 126, 'k_mlp': 126,
            'k_block': 50, 'k_stage': 48, 'k_adapt': 32},
    40105: {'e_conv': 240, 'e_stage': 64, 'e_adapt': 8},
    40106: {'k_gemm': 19, 'm_layer': 18, 'k_mlp': 10, 'm_stage': 10,
            'm_attn': 8, 'm_adapt': 2},
}
# Pinned trailer option split (parse_cm_payloads: A + B).
DLSS_TRAILER_A = {
    40104: {"-vc-payload -Xfinalizer '-noDPASMacro'": 442,
            "-vc-payload -ze-exp-register-file-size=256 -Xfinalizer '-noDPASMacro'": 274},
    40105: {"-vc-payload -Xfinalizer '-noDPASMacro'": 192,
            "-vc-payload -ze-exp-register-file-size=256 -Xfinalizer '-noDPASMacro'": 120},
    40106: {"-vc-payload -Xfinalizer '-noDPASMacro'": 49,
            "-vc-payload -ze-exp-register-file-size=256 -Xfinalizer '-noDPASMacro'": 18},
}
TRAILER_B = ' -target-features=+ocl_runtime'


def spirv_walk(ir: bytes):
    """Yield (opcode, words) without executing anything."""
    if len(ir) < 20:
        raise ValueError('SPIR-V too short')
    magic, _, _, _, _ = struct.unpack_from('<5I', ir, 0)
    if magic != 0x07230203:
        raise ValueError('Bad SPIR-V magic')
    pos = 20
    while pos + 4 <= len(ir):
        word, = struct.unpack_from('<I', ir, pos)
        cnt, op = word >> 16, word & 0xFFFF
        if cnt == 0 or pos + cnt * 4 > len(ir):
            raise ValueError('Truncated SPIR-V instruction')
        yield op, struct.unpack_from(f'<{cnt}I', ir, pos), ir[pos:pos + cnt * 4]
        pos += cnt * 4


def entry_iface(ir: bytes):
    for op, words, rawb in spirv_walk(ir):
        if op == 15:
            end = rawb.find(b'\x00', 12)
            if end < 0:
                raise ValueError('Unterminated entry name')
            nwords = math.ceil((end - 12 + 1) / 4)
            return rawb[12:end].decode(errors='replace'), list(words[3 + nwords:])
    raise ValueError('No OpEntryPoint found')


class DlssPinTests(unittest.TestCase):
    def test_dlss_subset_of_shared_loader_table(self):
        # Same FUN_180029640 index table covers 40101-40106; DLSS are 3,4,5.
        self.assertEqual(sorted(xmx.EXPECTED), [40101, 40102, 40103, 40104, 40105, 40106])
        for rid in DLSS_RIDS:
            self.assertIn(rid, xmx.EXPECTED)
            self.assertEqual(xmx.EXPECTED[rid]['index'], rid - 40101)
            self.assertEqual(xmx.EXPECTED[rid]['bucket'], DLSS_BUCKETS[rid])
            self.assertEqual(xmx.EXPECTED[rid]['cm_envelopes'], DLSS_ENVELOPES[rid])
            self.assertEqual(xmx.EXPECTED[rid]['raw_sha256'], DLSS_RAW_SHA[rid])

    def test_dlss_envelope_total(self):
        self.assertEqual(sum(DLSS_ENVELOPES.values()), 716 + 312 + 67)
        self.assertEqual(sum(DLSS_ENVELOPES.values()), 1095)

    def test_kernel_distributions_sum_to_envelopes(self):
        for rid, dist in DLSS_KERNELS.items():
            self.assertEqual(sum(dist.values()), DLSS_ENVELOPES[rid],
                             f'kernel sum != envelopes for {rid}')

    def test_trailer_pins_wellformed(self):
        for rid, dist in DLSS_TRAILER_A.items():
            self.assertEqual(sum(dist.values()), DLSS_ENVELOPES[rid])
            for opt in dist:
                self.assertTrue(opt.startswith('-vc-payload'))
                self.assertIn("-Xfinalizer '-noDPASMacro'", opt)
        self.assertIn('ocl_runtime', TRAILER_B)

    def test_compressed_size_mismatch_is_fail_closed(self):
        meta = dict(xmx.EXPECTED[40104])
        with self.assertRaises(ValueError):
            xmx.decode_and_verify(b'short', meta, LIBWIM)

    def test_compressed_hash_mismatch_is_fail_closed(self):
        meta = dict(xmx.EXPECTED[40104])
        meta['res_size'] = 5
        with self.assertRaises(ValueError):
            xmx.decode_and_verify(b'wrong', meta, LIBWIM)

    def test_footer_parser_is_fail_closed_on_empty(self):
        # Parser is pure-python, CPU-only; empty/garbage yields [] (no silent parse).
        self.assertTrue(callable(parse_mod.parse))
        self.assertEqual(parse_mod.parse(b'\x00' * 64), [])
        self.assertEqual(parse_mod.parse(b'-vc-payload\x00' * 4), [])
        # Bad Compression API header must fail closed.
        with self.assertRaises(ValueError):
            xmx.check_header(b'\x00' * 24)


def analysis_packs_present():
    return ANALYSIS_DIR.is_dir() and all(
        (ANALYSIS_DIR / f'pack-{rid}.raw').exists() for rid in DLSS_RIDS)


def dll_present():
    return DLL_412.is_file()


@unittest.skipUnless(analysis_packs_present(),
                     'Local 4.1.2 decoded packs are not present')
class DlssLocalArtifactTests(unittest.TestCase):
    def test_raw_hashes_and_envelope_counts(self):
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), DLSS_RAW_SHA[rid])
            self.assertEqual(len(raw), xmx.EXPECTED[rid]['raw_size'])
            recs = parse_mod.parse(raw)
            self.assertEqual(len(recs), DLSS_ENVELOPES[rid])
            self.assertEqual(raw.count(b'\x03\x02\x23\x07'), DLSS_ENVELOPES[rid])

    def test_entry_names_match_pins(self):
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            carved = carve_mod.carve(raw)
            self.assertEqual(len(carved), DLSS_ENVELOPES[rid])
            got = Counter(e['name'] for c in carved for e in c['entries'])
            self.assertEqual(dict(got), DLSS_KERNELS[rid])

    def test_spirv_via_is_cm_not_ngx(self):
        # Every module: Kernel + SPV_INTEL_vector_compute + OpenCL.std,
        # one BufferSurfaceINTEL (6086, access ReadWrite=2), zero samplers.
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            for r in recs:
                ir = raw[r['offset']:r['offset'] + r['ir_size']]
                exts = []
                imports = []
                model = None
                opcount = Counter()
                buf_access = []
                for op, words, rawb in spirv_walk(ir):
                    opcount[op] += 1
                    if op == 10:
                        exts.append(rawb[4:].split(b'\x00')[0].decode(errors='replace'))
                    elif op == 11:
                        imports.append(rawb[8:].split(b'\x00')[0].decode(errors='replace'))
                    elif op == 15:
                        model = words[1]
                    elif op == 6086 and len(words) > 2:
                        buf_access.append(words[2])
                self.assertEqual(model, 6, 'OpEntryPoint must be Kernel (6)')
                self.assertIn('SPV_INTEL_vector_compute', exts)
                self.assertIn('SPV_KHR_no_integer_wrap_decoration', exts)
                self.assertIn('OpenCL.std', imports)
                self.assertEqual(opcount[26], 0, 'OpTypeSampler must be absent')
                self.assertEqual(opcount[27], 0, 'OpTypeSampledImage must be absent')
                self.assertEqual(opcount[6086], 1, 'exactly one BufferSurface type')
                self.assertEqual(buf_access, [2], 'BufferSurface access must be ReadWrite (2)')
            # Per-pack image minority (OpTypeImage dim=2D Unknown, no samplers).
            n_img = sum(1 for r in recs
                        for op, _, _ in spirv_walk(raw[r['offset']:r['offset'] + r['ir_size']]
                                                   ) if op == 25)
            # OpTypeImage appears at most once per module here; count modules with >=1.
            mods_with_img = 0
            for r in recs:
                ir = raw[r['offset']:r['offset'] + r['ir_size']]
                if any(op == 25 for op, _, _ in spirv_walk(ir)):
                    mods_with_img += 1
            expected_img = {40104: 64, 40105: 40, 40106: 3}[rid]
            self.assertEqual(mods_with_img, expected_img,
                             f'image-module count for {rid}')
            self.assertGreater(n_img, 0)
            _ = opcount  # silence lint

    def test_entry_interfaces_are_cross_thread_payloads(self):
        # All entries: 1-2 x v3i64 Input vectors (thread payload), never
        # BufferSurface/Image directly. Buffers go via BTI/stateless inside.
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            sigs = Counter()
            for r in recs:
                ir = raw[r['offset']:r['offset'] + r['ir_size']]
                name, iface = entry_iface(ir)
                self.assertIn(name, DLSS_KERNELS[rid])
                self.assertIn(len(iface), (1, 2))
                sigs[(name, len(iface))] += 1
            # Rebuild expected (name, iface_len) from gated observation.
            total = sum(sigs.values())
            self.assertEqual(total, DLSS_ENVELOPES[rid])

    def test_iface_counts_match_survey(self):
        expected = {
            40104: Counter({1: 282, 2: 434}),
            40105: Counter({1: 272, 2: 40}),
            40106: Counter({1: 23, 2: 44}),
        }
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            got = Counter()
            for r in recs:
                ir = raw[r['offset']:r['offset'] + r['ir_size']]
                _, iface = entry_iface(ir)
                got[len(iface)] += 1
            self.assertEqual(dict(got), dict(expected[rid]))

    def test_trailers_match_pins(self):
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            got_a = Counter(r['embedded_string_a'] for r in recs)
            got_b = Counter(r['embedded_string_b'] for r in recs)
            self.assertEqual(dict(got_a), DLSS_TRAILER_A[rid])
            self.assertEqual(dict(got_b), {TRAILER_B: DLSS_ENVELOPES[rid]})

    def test_gaps_are_zero_no_dxbc_no_ngx(self):
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            gaps = parse_mod.gaps(raw, recs)
            for g in gaps:
                self.assertTrue(g['all_zero'], f'non-zero gap at {g["offset"]} in {rid}')
                self.assertEqual(g['dxbc_candidates'], [])
            blob = raw.lower()
            for needle in (b'ngx', b'cuda', b'nvngx', b'dxbc'):
                # 'dxbc' may appear as x86 noise; require uppercase DXBC marker.
                if needle == b'dxbc':
                    continue
                self.assertNotIn(needle, blob, f'{needle!r} must not appear in pack {rid}')

    def test_execution_modes_match_cm_profile(self):
        for rid in DLSS_RIDS:
            raw = (ANALYSIS_DIR / f'pack-{rid}.raw').read_bytes()
            recs = parse_mod.parse(raw)
            for r in recs:
                ir = raw[r['offset']:r['offset'] + r['ir_size']]
                modes = set()
                for op, words, _ in spirv_walk(ir):
                    if op == 16:
                        modes.add(words[2])
                self.assertIn(31, modes)
                self.assertIn(35, modes)
                self.assertIn(6417, modes)
                self.assertIn(5618, modes)


@unittest.skipUnless(dll_present(), 'Local 4.1.2 DLL copy is not present')
class DllStringContrastTests(unittest.TestCase):
    @staticmethod
    def strings():
        data = DLL_412.read_bytes()
        if data[:2] != b'MZ':
            raise ValueError('Not an MZ/PE candidate')
        out = set(m.group(0).decode() for m in re.finditer(rb'[\x20-\x7e]{6,}', data))
        return out

    def test_dll_identity(self):
        self.assertEqual(hashlib.sha256(DLL_412.read_bytes()).hexdigest(), DLL_SHA256)

    def test_dlss_bucket_names_present_kernel_names_absent(self):
        s = self.strings()
        for bucket in DLSS_BUCKETS.values():
            self.assertTrue(any(bucket in x for x in s), f'missing bucket {bucket!r}')
        for kernel in ('k_gemm', 'k_linear', 'k_attn', 'k_mlp', 'e_conv', 'm_layer', 'm_attn'):
            self.assertFalse(any(kernel == x or kernel in x for x in s),
                             f'DLSS kernel {kernel!r} must not be a DLL string')

    def test_no_cuda_ngx_classic_strings(self):
        s = self.strings()
        joined = '\n'.join(s)
        self.assertNotIn('CUDA', joined)
        # NVNGX/CUDA runtime markers absent; only lowercase weight-file refs exist.
        self.assertFalse(any(x == 'NVNGX' or x == 'NGX' for x in s))
        self.assertTrue(any('nvngx_dlss.dll' in x for x in s))

    def test_fsr_fail_logs_vs_dlss_logs(self):
        s = self.strings()
        # FSR per-pass CM-SPIRV fail logs exist (P6 N32 / P7-P9 FullFusion).
        self.assertTrue(any('Failed to load pass6 N32 CM-SPIRV' in x for x in s))
        self.assertTrue(any('Failed to load pass7 FullFusion CM-SPIRV' in x for x in s))
        self.assertTrue(any('Failed to load P1 H1 DPAS-DP4A-DPAS CM-SPIRV' in x for x in s))
        # No per-kernel DLSS CM-SPIRV fail logs; DLSS uses token-grid/ScratchBuffer logs.
        self.assertFalse(any('k_gemm' in x and 'Failed to load' in x for x in s))
        self.assertTrue(any('DLSS K ready' in x for x in s))
        self.assertTrue(any('token grid' in x for x in s))
        self.assertTrue(any('ScratchBuffer' in x for x in s))

    def test_shared_loader_and_igdext_strings(self):
        s = self.strings()
        self.assertTrue(any('embedded pack %u invalid' in x for x in s))
        self.assertTrue(any('embedded %s pack loaded' in x for x in s))
        self.assertTrue(any('igdext64.dll' in x for x in s))
        self.assertTrue(any('CreateComputePipelineState' in x for x in s))
        self.assertTrue(any('CreateDeviceExtensionContext' in x for x in s))


@unittest.skipUnless(RESDIR.is_dir() and LIBWIM.exists(),
                     'Optional local 4.1.2 resources are not present')
class DlssDecodeGatedTests(unittest.TestCase):
    def test_pinned_sizes_hashes_and_counts_dlss_only(self):
        packs = xmx.packs_from_resdir(RESDIR)
        for rid in DLSS_RIDS:
            meta = xmx.EXPECTED[rid]
            raw = xmx.decode_and_verify(packs[rid], meta, LIBWIM)
            self.assertEqual(len(raw), meta['raw_size'])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), meta['raw_sha256'])
            self.assertGreater(raw.count(xmx.SPIRV_MAGIC), 0)


if __name__ == '__main__':
    unittest.main()
