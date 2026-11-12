"""CPU-only census pins for the XMX 4.1.2 PRE Xe2 SPIR-V block.

Static only. No DLL execution, no GPU/Wine, no game or prefix access.
Reads only ``analysis/fsr-xmx-412/pack-40102.raw`` (already decompressed)
and disassembles the extracted PRE IR with ``spirv-dis`` (CPU tool).
All pins are fail-closed: any changed entry, argument order, guard,
operation count, or store surface breaks the tests.
No scene semantics or image formats are assigned here.
"""
import hashlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))

import parse_cm_payloads  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _xmx412 = _load('decompress_xmx412')
except Exception:  # pragma: no cover - pins below remain authoritative
    _xmx412 = None

PACK = ROOT / 'analysis' / 'fsr-xmx-412' / 'pack-40102.raw'

# Pins observed 2026-11-12 via parse_cm_payloads + spirv-dis (SPIRV-Tools 2026.4).
# Pack 40102: 18-variant Xe2 (SIMD16 DPAS), DLL fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732.
RAW_SIZE = 23682325
RAW_SHA256 = 'd88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491'
CM_ENVELOPES = 252
PRE_RECORD_INDICES = [0, 14, 28, 42, 56, 70, 84, 98, 112, 126, 140, 154, 168, 182, 196, 210, 224, 238]
PRE_IR_SIZE = 358776
PRE_TRAILER_SIZE = 97
PRE_STRING_A = "-vc-payload -Xfinalizer '-noDPASMacro'"
PRE_STRING_B = ' -target-features=+ocl_runtime'
FIRST_IR_SHA256 = '49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568'
FIRST_ENVELOPE_SHA256 = 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab'
# Guard cycle observed across the 18 PRE variants (x, y) in record order:
# 120x540, 240x1080, 480x2160 repeating (6 each). Old 4.0.2x pack shows the
# same cycle; xe2-first.spvasm is the 120x540 member.
EXPECTED_GUARD_CYCLE = [(120, 540), (240, 1080), (480, 2160)] * 6

ENTRY_NAME = 'fsr4_pre_xmx'
ENTRY_ID = '%11173'
ENTRY_INTERFACE = '%__spirv_BuiltInWorkgroupId'

# Ordered argument *type* ids for the wrapper entry %11173.
EXPECTED_ARGS = ['%770', '%774', '%778', '%778', '%778', '%778',
                 '%778', '%778', '%778', '%770', '%770', '%782']
EXPECTED_ARG_LABELS = [
    'BufferSurfaceINTEL ReadWrite',
    'Image 2D ReadWrite; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'Image 2D ReadOnly; format Unknown',
    'BufferSurfaceINTEL ReadWrite',
    'BufferSurfaceINTEL ReadWrite',
    'Sampler',
]
EXPECTED_TYPE_DECLS = {
    '%770': ('OpTypeBufferSurfaceINTEL', 'ReadWrite'),
    '%774': ('OpTypeImage', '%void 2D 0 0 0 0 Unknown ReadWrite'),
    '%778': ('OpTypeImage', '%void 2D 0 0 0 0 Unknown ReadOnly'),
    '%782': ('OpTypeSampler', ''),
}
EXPECTED_EXECMODES = {
    'ContractionOff': None,
    'SubgroupSize': '1',
    'SharedLocalMemorySizeINTEL': '0',
    'NamedBarrierCountINTEL': '0',
}
EXPECTED_GUARDS = {120: 1, 540: 1}
EXPECTED_COUNTS = {'3d_load': 78, '3d_sample': 85, 'typed_quad_store': 1}
STORE_FUNC_SUBSTR = 'llvm_genx_lsc_store_quad_typed_bti_v16i1_v16i32_v48f32'
STORE_SURFACE_SSA = '%10694'
STORE_CHANNEL_MASKS = [7]
STORE_ORIGIN_ARG_INDEX = 1
# SSA chain from the typed-store surface operand back to the arg-1 conversion.
# Substring patterns (Aligned suffixes omitted on purpose); order is load/store
# alternating, ending at the address-convert of inner param %789 (arg 1 RW).
SURFACE_FLOW = [
    r'%1920 = OpFunctionCall %uint %llvm_genx_address_convert_i32_p1opencl_image2d_rw_t %789',
    r'OpStore %4058 %1920',
    r'%4151 = OpLoad %uint %4058',
    r'OpStore %3851 %4151',
    r'%10683 = OpLoad %uint %3851',
    r'OpStore %3788 %10683',
    r'%10688 = OpLoad %uint %3788',
    r'OpStore %3782 %10688',
    r'%10694 = OpLoad %uint %3782',
]
INNER_ARG1_DECL = r'%789 = OpFunctionParameter %774'

SPIRV_DIS = shutil.which('spirv-dis')


def disassemble(ir: bytes) -> str:
    if SPIRV_DIS is None:
        raise unittest.SkipTest('spirv-dis is not installed')
    with tempfile.NamedTemporaryFile(suffix='.spv', delete=False) as tmp:
        tmp.write(ir)
        name = tmp.name
    try:
        proc = subprocess.run([SPIRV_DIS, name], capture_output=True, text=True, check=False)
    finally:
        Path(name).unlink(missing_ok=True)
    if proc.returncode != 0:
        raise ValueError(f'spirv-dis failed: {proc.stderr[:500]}')
    return proc.stdout


def extract_census(text: str, expected_guards=None) -> dict:
    """Extract only the pinned PRE census; raise ValueError on any drift.

    ``expected_guards`` is an optional (x, y) pair. When omitted, any two
    distinct single guards are accepted and returned in appearance order
    (first = x, second = y); callers pin the exact values.
    Operation counts are returned as observed; callers pin the exact
    78/85/1 for real modules. Missing classes always fail closed.
    """
    lines = text.splitlines()
    entries = re.findall(r'OpEntryPoint\s+Kernel\s+(%\w+)\s+"([^"]+)"\s+(%\w+)', text)
    if len(entries) != 1:
        raise ValueError(f'Expected exactly one Kernel entry, got {entries}')
    entry_id, entry_name, entry_iface = entries[0]
    if (entry_id, entry_name, entry_iface) != (ENTRY_ID, ENTRY_NAME, ENTRY_INTERFACE):
        raise ValueError(f'PRE entry changed: {entries}')

    # Wrapper parameters in order.
    start = next((i for i, l in enumerate(lines)
                  if re.search(rf'^\s*{re.escape(ENTRY_ID)}\s+=\s+OpFunction\b', l)), None)
    if start is None:
        raise ValueError('Pinned PRE wrapper function not found')
    params = []
    for line in lines[start + 1:]:
        if 'OpLabel' in line:
            break
        m = re.search(r'OpFunctionParameter\s+(%\w+)', line)
        if m:
            params.append(m.group(1))
    if params != EXPECTED_ARGS:
        raise ValueError(f'PRE resource argument order changed: {params}')

    declarations = {}
    for line in lines:
        m = re.search(r'^\s*(%\w+)\s+=\s+(OpType\w+)(?:\s+(.*?))?\s*$', line)
        if m:
            declarations[m.group(1)] = (m.group(2), (m.group(3) or '').strip())
    for type_id, expected in EXPECTED_TYPE_DECLS.items():
        got = declarations.get(type_id)
        if got is None:
            raise ValueError(f'Missing resource type declaration {type_id}')
        if got[0] != expected[0]:
            raise ValueError(f'Resource type opcode changed for {type_id}: {got}')
        if expected[1] and got[1] != expected[1]:
            raise ValueError(f'Resource type operands changed for {type_id}: {got!r}')
        if type_id == '%782' and got[0] != 'OpTypeSampler':
            raise ValueError(f'Sampler declaration changed: {got}')
    resources = [{'arg_index': i, 'type': EXPECTED_ARG_LABELS[i]} for i in range(12)]

    # BuiltIns: only WorkgroupId may appear.
    builtin_names = re.findall(r'BuiltIn\s+(\w+)', text)
    if sorted(set(builtin_names)) != ['WorkgroupId']:
        raise ValueError(f'Unexpected BuiltIns: {sorted(set(builtin_names))}')
    if not re.search(r'OpDecorate\s+%__spirv_BuiltInWorkgroupId\s+BuiltIn\s+WorkgroupId', text):
        raise ValueError('WorkgroupId BuiltIn decoration missing')
    if not re.search(r'%__spirv_BuiltInWorkgroupId\s+=\s+OpVariable\s+%_ptr_Input_v3ulong\s+Input', text):
        raise ValueError('WorkgroupId interface variable changed')

    # ExecutionModes for the pinned entry; LocalSize must stay absent.
    exec_lines = [l.strip() for l in lines if f'OpExecutionMode {ENTRY_ID}' in l]
    if len(exec_lines) != 4:
        raise ValueError(f'Expected 4 ExecutionModes, got {exec_lines}')
    seen = {}
    for line in exec_lines:
        m = re.search(rf'OpExecutionMode\s+{re.escape(ENTRY_ID)}\s+(\w+)(?:\s+(\S+))?', line)
        if not m:
            raise ValueError(f'Unparseable ExecutionMode: {line}')
        seen[m.group(1)] = m.group(2)
    if seen != EXPECTED_EXECMODES:
        raise ValueError(f'ExecutionModes changed: {seen}')
    if re.search(r'OpExecutionMode\s+%\w+\s+LocalSize', text):
        raise ValueError('Unexpected LocalSize ExecutionMode')

    guards = {}
    guard_order = []
    for line in lines:
        m = re.search(r'OpUGreaterThanEqual\s+%bool\s+%\w+\s+%uint_(\d+)\b', line)
        if m:
            bound = int(m.group(1))
            guards[bound] = guards.get(bound, 0) + 1
            if bound not in guard_order:
                guard_order.append(bound)
    if len(guards) != 2 or any(v != 1 for v in guards.values()):
        raise ValueError(f'Expected two single workgroup guards, got {guards}')
    if expected_guards is not None and tuple(guard_order) != tuple(expected_guards):
        raise ValueError(f'Workgroup guards changed: {guard_order} != {list(expected_guards)}')
    x_bound, y_bound = guard_order[0], guard_order[1]

    operations = {'3d_load': 0, '3d_sample': 0, 'typed_quad_store': 0}
    store_channel_masks = []
    store_surface_operands = []
    store_predicates = []
    for line in lines:
        if 'OpFunctionCall' not in line:
            continue
        if '%llvm_genx_3d_load_' in line:
            operations['3d_load'] += 1
        if '%llvm_genx_3d_sample_' in line:
            operations['3d_sample'] += 1
        if '%llvm_genx_lsc_store_quad_typed_bti_' in line:
            if STORE_FUNC_SUBSTR not in line:
                raise ValueError(f'Unexpected typed-store function: {line.strip()}')
            operations['typed_quad_store'] += 1
            m = re.search(rf'{re.escape(STORE_FUNC_SUBSTR)}\w*\s+(.+)$', line)
            operands = m.group(1).split() if m else []
            controls = [re.fullmatch(r'%uchar_(\d+)', o) for o in operands[1:4]] if len(operands) == 10 else []
            if len(operands) != 10 or any(x is None for x in controls):
                raise ValueError('Unsupported typed-store channel mask/surface operands')
            store_predicates.append(operands[0])
            store_channel_masks.append(int(controls[2].group(1)))
            store_surface_operands.append(operands[4])
    if not all(operations.values()):
        raise ValueError(f'Expected image loads, sampler operations and typed stores: {operations}')
    if store_channel_masks != STORE_CHANNEL_MASKS or store_surface_operands != [STORE_SURFACE_SSA]:
        raise ValueError(f'Unexpected store mask/surface: {store_channel_masks} {store_surface_operands}')
    if not re.search(rf'{re.escape(STORE_SURFACE_SSA)}\s+=\s+OpLoad\s+%uint\s+%\w+', text):
        raise ValueError('Store surface SSA definition missing')

    normalized = [' '.join(l.split()) for l in lines]
    if not re.search(INNER_ARG1_DECL, text):
        raise ValueError('Inner arg-1 (Image RW) declaration missing')
    for pattern in SURFACE_FLOW:
        if not any(re.search(pattern, l) for l in normalized):
            raise ValueError(f'Typed-store surface no longer originates from arg 1 RW: missing {pattern}')

    return {
        'entry': entry_name,
        'entry_id': entry_id,
        'entry_argument_resources': resources,
        'builtins': ['WorkgroupId'],
        'execution_modes': dict(EXPECTED_EXECMODES),
        'workgroup_id_guards': {'x_at_least': x_bound, 'y_at_least': y_bound},
        'genx_operation_call_counts': dict(operations),
        'typed_store_function': STORE_FUNC_SUBSTR,
        'typed_store_channel_masks': list(store_channel_masks),
        'typed_store_surface_operands': list(store_surface_operands),
        'typed_store_surface_origin_arg_index': STORE_ORIGIN_ARG_INDEX,
        'image_format': 'Unknown in OpTypeImage; not inferred here',
        'limitations': [
            'Counts are syntactic OpFunctionCall counts, not pixels or access bounds.',
            'Does not identify color/depth/motion semantics or prove output values.',
            'Does not establish runtime local size, dispatch API behavior, or execution mask.',
        ],
    }


def fixture(args=None, guards=(120, 540)):
    args = EXPECTED_ARGS if args is None else args
    declarations = '\n'.join(
        f'{i} = OpFunctionParameter {t}' for i, t in enumerate(args)
    )
    types = '\n'.join([
        '%770 = OpTypeBufferSurfaceINTEL ReadWrite',
        '%774 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadWrite',
        '%778 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly',
        '%782 = OpTypeSampler',
    ])
    guard_lines = '\n'.join(
        f'%g{i} = OpUGreaterThanEqual %bool %x{i} %uint_{b}' for i, b in enumerate(guards)
    )
    return '\n'.join([
        'OpCapability Kernel',
        'OpExtension "SPV_INTEL_vector_compute"',
        'OpMemoryModel Physical64 OpenCL',
        f'OpEntryPoint Kernel {ENTRY_ID} "{ENTRY_NAME}" {ENTRY_INTERFACE}',
        f'OpExecutionMode {ENTRY_ID} ContractionOff',
        f'OpExecutionMode {ENTRY_ID} SubgroupSize 1',
        f'OpExecutionMode {ENTRY_ID} SharedLocalMemorySizeINTEL 0',
        f'OpExecutionMode {ENTRY_ID} NamedBarrierCountINTEL 0',
        'OpDecorate %__spirv_BuiltInWorkgroupId BuiltIn WorkgroupId',
        '%__spirv_BuiltInWorkgroupId = OpVariable %_ptr_Input_v3ulong Input',
        types,
        f'{ENTRY_ID} = OpFunction %void DontInline %786', declarations, '%label = OpLabel',
        guard_lines,
        '%789 = OpFunctionParameter %774',
        '%1920 = OpFunctionCall %uint %llvm_genx_address_convert_i32_p1opencl_image2d_rw_t %789',
        'OpStore %4058 %1920',
        '%4151 = OpLoad %uint %4058',
        'OpStore %3851 %4151',
        '%10683 = OpLoad %uint %3851',
        'OpStore %3788 %10683',
        '%10688 = OpLoad %uint %3788',
        'OpStore %3782 %10688',
        '%10694 = OpLoad %uint %3782',
        '%a = OpFunctionCall %v16float %llvm_genx_3d_load_v16f32',
        '%b = OpFunctionCall %v64float %llvm_genx_3d_sample_v64f32',
        f'%c = OpFunctionCall %void %llvm_genx_lsc_store_quad_typed_bti_v16i1_v16i32_v48f32 '
        f'%pred %uchar_0 %uchar_0 %uchar_7 {STORE_SURFACE_SSA} %u %v %r %lod %data',
    ])


def _read_pack():
    if not PACK.is_file():
        raise unittest.SkipTest(f'Missing pinned pack artifact: {PACK}')
    data = PACK.read_bytes()
    if len(data) != RAW_SIZE:
        raise ValueError(f'Pack size drift: {len(data)} != {RAW_SIZE}')
    if hashlib.sha256(data).hexdigest() != RAW_SHA256:
        raise ValueError('Pack SHA-256 drift: unreviewed 4.1.2 bytes')
    return data


class PackEnvelopeTests(unittest.TestCase):
    def test_raw_size_and_hash_are_pinned(self):
        data = _read_pack()
        self.assertEqual(len(data), RAW_SIZE)
        self.assertEqual(hashlib.sha256(data).hexdigest(), RAW_SHA256)

    def test_envelope_count_and_pre_indices(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        self.assertEqual(len(records), CM_ENVELOPES)
        pre_offsets = [i for i, r in enumerate(records)
                       if b'fsr4_pre_xmx' in data[r['offset']:r['offset'] + r['ir_size']]]
        self.assertEqual(pre_offsets, PRE_RECORD_INDICES)
        self.assertEqual(len(pre_offsets), 18)

    def test_pre_envelope_sizes_and_embedded_strings(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        for i in PRE_RECORD_INDICES:
            rec = records[i]
            self.assertEqual(rec['ir_size'], PRE_IR_SIZE, f'record {i}')
            self.assertEqual(rec['trailer_size'], PRE_TRAILER_SIZE, f'record {i}')
            self.assertEqual(rec['embedded_string_a'], PRE_STRING_A, f'record {i}')
            self.assertEqual(rec['embedded_string_b'], PRE_STRING_B, f'record {i}')

    def test_first_pre_hashes_are_pinned(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        rec = records[PRE_RECORD_INDICES[0]]
        ir = data[rec['offset']:rec['offset'] + rec['ir_size']]
        self.assertEqual(hashlib.sha256(ir).hexdigest(), FIRST_IR_SHA256)
        self.assertEqual(hashlib.sha256(data[rec['offset']:rec['end']]).hexdigest(),
                         FIRST_ENVELOPE_SHA256)
        self.assertEqual(ir[:4], b'\x03\x02\x23\x07')

    def test_all_pre_ir_shas_are_distinct(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        shas = [r['ir_sha256'] for i, r in enumerate(records) if i in PRE_RECORD_INDICES]
        self.assertEqual(len(set(shas)), 18)

    def test_loader_pins_stay_consistent(self):
        if _xmx412 is None:
            self.skipTest('decompress_xmx412 tool not importable')
        meta = _xmx412.EXPECTED.get(40102)
        self.assertIsNotNone(meta)
        self.assertEqual(meta['raw_size'], RAW_SIZE)
        self.assertEqual(meta['raw_sha256'], RAW_SHA256)
        self.assertEqual(meta['cm_envelopes'], CM_ENVELOPES)


@unittest.skipUnless(SPIRV_DIS is not None, 'spirv-dis is not installed')
class FirstPreCensusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        rec = records[PRE_RECORD_INDICES[0]]
        cls.text = disassemble(data[rec['offset']:rec['offset'] + rec['ir_size']])
        cls.census = extract_census(cls.text, expected_guards=(120, 540))

    def test_single_entry_point(self):
        self.assertEqual(self.census['entry'], ENTRY_NAME)
        self.assertEqual(self.census['entry_id'], ENTRY_ID)

    def test_ordered_arguments_and_types(self):
        self.assertEqual(len(self.census['entry_argument_resources']), 12)
        for i, expected in enumerate(EXPECTED_ARG_LABELS):
            self.assertEqual(self.census['entry_argument_resources'][i]['type'], expected,
                             f'arg {i}')

    def test_builtins_only_workgroupid(self):
        self.assertEqual(self.census['builtins'], ['WorkgroupId'])

    def test_execution_modes_exact_and_no_localsize(self):
        self.assertEqual(self.census['execution_modes'], EXPECTED_EXECMODES)
        self.assertNotIn('LocalSize', self.text)

    def test_workgroup_guards(self):
        self.assertEqual(self.census['workgroup_id_guards'], {'x_at_least': 120, 'y_at_least': 540})

    def test_genx_counts(self):
        self.assertEqual(self.census['genx_operation_call_counts'], EXPECTED_COUNTS)

    def test_store_signature_and_origin(self):
        self.assertEqual(self.census['typed_store_function'], STORE_FUNC_SUBSTR)
        self.assertEqual(self.census['typed_store_channel_masks'], [7])
        self.assertEqual(self.census['typed_store_surface_operands'], [STORE_SURFACE_SSA])
        self.assertEqual(self.census['typed_store_surface_origin_arg_index'], 1)
        self.assertEqual(self.census['image_format'], 'Unknown in OpTypeImage; not inferred here')


@unittest.skipUnless(SPIRV_DIS is not None, 'spirv-dis is not installed')
class AllPreBlockStabilityTests(unittest.TestCase):
    def test_all_18_share_coarse_census_with_guard_cycle(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        self.assertEqual(len(EXPECTED_GUARD_CYCLE), 18)
        for idx, rec_idx in enumerate(PRE_RECORD_INDICES):
            rec = records[rec_idx]
            ir = data[rec['offset']:rec['offset'] + rec['ir_size']]
            text = disassemble(ir)
            expected_pair = EXPECTED_GUARD_CYCLE[idx]
            with self.subTest(pre_variant=idx, record=rec_idx):
                census = extract_census(text, expected_guards=expected_pair)
                self.assertEqual(census['entry'], ENTRY_NAME)
                self.assertEqual(census['genx_operation_call_counts'], EXPECTED_COUNTS)
                self.assertEqual(census['workgroup_id_guards'],
                                 {'x_at_least': expected_pair[0], 'y_at_least': expected_pair[1]})
                self.assertEqual(census['typed_store_surface_origin_arg_index'], 1)
                self.assertEqual(census['typed_store_channel_masks'], [7])
                self.assertEqual(census['typed_store_surface_operands'], [STORE_SURFACE_SSA])


class SyntheticFailClosedTests(unittest.TestCase):
    def test_fixture_extracts_new_census(self):
        result = extract_census(fixture())
        self.assertEqual(len(result['entry_argument_resources']), 12)
        self.assertEqual(result['entry_argument_resources'][1]['type'],
                         'Image 2D ReadWrite; format Unknown')
        self.assertEqual(result['genx_operation_call_counts'],
                         {'3d_load': 1, '3d_sample': 1, 'typed_quad_store': 1})
        # Synthetic fixture has one call per class; real pins are asserted above.

    def test_rejects_changed_argument_order(self):
        changed = EXPECTED_ARGS.copy()
        changed[1], changed[2] = changed[2], changed[1]
        with self.assertRaisesRegex(ValueError, 'argument order changed'):
            extract_census(fixture(changed))

    def test_rejects_missing_or_changed_guards(self):
        with self.assertRaisesRegex(ValueError, 'workgroup guard'):
            extract_census(fixture(guards=(120,)))

    def test_rejects_store_surface_rebound(self):
        text = fixture().replace('OpStore %4058 %1920', 'OpStore %4058 %1921')
        with self.assertRaisesRegex(ValueError, 'arg 1|surface'):
            extract_census(text)

    def test_rejects_changed_store_mask(self):
        text = fixture().replace('%uchar_7 %10694', '%uchar_15 %10694')
        with self.assertRaisesRegex(ValueError, 'mask/surface'):
            extract_census(text)

    def test_rejects_missing_operation_classes(self):
        text = fixture().replace('%llvm_genx_3d_load_', '%other_')
        with self.assertRaisesRegex(ValueError, 'Expected image loads'):
            extract_census(text)

    def test_rejects_extra_entry_point(self):
        text = fixture() + '\nOpEntryPoint Kernel %99999 "other" %__spirv_BuiltInWorkgroupId'
        with self.assertRaisesRegex(ValueError, 'exactly one Kernel entry'):
            extract_census(text)


if __name__ == '__main__':
    unittest.main()
