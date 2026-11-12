"""CPU-only pins for the 18 PRE Xe2 variants in XMX 4.1.2 pack 40102.

Static only. No DLL is executed, no GPU/Wine/driver/prefix/Steam state is
touched, ``artifacts/original`` is never written. Reads only
``analysis/fsr-xmx-412/pack-40102.raw`` (already decompressed) and
disassembles exact IR slices with ``spirv-dis`` (CPU tool). Offline
``ocloc`` outputs under ``analysis/offline-pre-412-variants/`` are read-only
when present and never required for the core SPIR-V pins.

All pins are fail-closed: any changed offset, size, option string, entry,
argument order, guard, operation count, store surface, BTI order, or
execution environment breaks the tests. Variant names
(``native_1080`` ... ``drs_4320``) are the assumed order inherited from the
old census (``analysis/pre-reconstruction.json`` index 1..18,
``rec_idx = 14*k``); the new 4.1.2 DLL variant table is not re-parsed here.
The assumption is checked structurally: every ``_1080`` variant must guard
``120x540`` with factor 1, every ``_2160`` must guard ``240x1080`` with
factor 2, every ``_4320`` must guard ``480x2160`` with factor 4. Any
reordering invalidates the ``Variante`` column (report, do not rename blindly).

No scene semantics, image formats, or functional correctness are assigned.
"""

import hashlib
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

PACK = ROOT / 'analysis' / 'fsr-xmx-412' / 'pack-40102.raw'
VARIANTS_DIR = ROOT / 'analysis' / 'offline-pre-412-variants'

RAW_SIZE = 23682325
RAW_SHA256 = 'd88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491'
CM_ENVELOPES = 252
PRE_RECORD_INDICES = [0, 14, 28, 42, 56, 70, 84, 98, 112, 126, 140, 154, 168, 182, 196, 210, 224, 238]
PRE_IR_SIZE = 358776
PRE_TRAILER_SIZE = 97
PRE_ENVELOPE_SIZE = 358873
PRE_STRING_A = "-vc-payload -Xfinalizer '-noDPASMacro'"
PRE_STRING_B = ' -target-features=+ocl_runtime'

ENTRY_NAME = 'fsr4_pre_xmx'
ENTRY_ID = '%11173'
ENTRY_INTERFACE = '%__spirv_BuiltInWorkgroupId'
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
EXPECTED_COUNTS = {'3d_load': 78, '3d_sample': 85, 'typed_quad_store': 1}
STORE_FUNC_SUBSTR = 'llvm_genx_lsc_store_quad_typed_bti_v16i1_v16i32_v48f32'
STORE_SURFACE_SSA = '%10694'
STORE_CHANNEL_MASKS = [7]
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

# Variant order assumed from the old census (pre-reconstruction.json 1..18).
# Guards and factors below are the cycle under test, not free text:
# _1080 -> 120x540 factor 1, _2160 -> 240x1080 factor 2, _4320 -> 480x2160 factor 4.
VARIANTS = [
    {'variant': 'native_1080', 'variant_index': 1, 'rec_idx': 0, 'offset': 0, 'ir_sha256': '49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568', 'envelope_sha256': 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'native_2160', 'variant_index': 2, 'rec_idx': 14, 'offset': 1315712, 'ir_sha256': '20096eefd6ea90a84581f846c221d2185c573bd4ad0831adbf7d77c83d7ebb29', 'envelope_sha256': 'ee5553e3d31dca00ec5112724dd62134fa4b808052016435a9883cd0da027597', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'native_4320', 'variant_index': 3, 'rec_idx': 28, 'offset': 2631424, 'ir_sha256': 'b4eacd686aa953bc6bb48365cd69a61f730b01c9c425aecd1b5f65d3010efc5e', 'envelope_sha256': '281e11fc87bb558a1207631f64a24ccd300173f5d9cbce3ef51295da0aefe616', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
    {'variant': 'quality_1080', 'variant_index': 4, 'rec_idx': 42, 'offset': 3947072, 'ir_sha256': '4516209c2f751b2f67ab808ab034027dec984542e492e08668f9479ae9779722', 'envelope_sha256': 'bc2b0cf3eb0f84e06933dbff0390a519c0db26d7c17adce0145b48a4e413a558', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'quality_2160', 'variant_index': 5, 'rec_idx': 56, 'offset': 5262784, 'ir_sha256': '781497a65e8dc4a7e6dca7fcfd1987e9bbe64d6e751b131de7e5857da83a7e35', 'envelope_sha256': 'c7af3e98a45a31ed2be8ef3e95ee6bf14b17c4600f89da73f846aaadabc4fa66', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'quality_4320', 'variant_index': 6, 'rec_idx': 70, 'offset': 6578496, 'ir_sha256': '530315c6836883e34ff3c54a62a40ab5ab7ab317c012fd90c243a1702b940950', 'envelope_sha256': '3414bc91df06b019010aa64570539279ce9ed8d9ec810ca9dab6345c341233d4', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
    {'variant': 'balanced_1080', 'variant_index': 7, 'rec_idx': 84, 'offset': 7894144, 'ir_sha256': '58681903c962a845f13e524a9786e931e53ddb6b886bc89d58046166a394a1f3', 'envelope_sha256': 'a6673041f400ae4ba949b431310c099af6ba6bc02cf5a92832dd3a9c016a84a1', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'balanced_2160', 'variant_index': 8, 'rec_idx': 98, 'offset': 9209856, 'ir_sha256': 'fdd506a063ea332a680dd81719fd901ac962f6eeb7fe2d0590956bc36ccffe9f', 'envelope_sha256': '0dc3e2dd165d0b33821477a6ceffa5c54f700109190c0b075db486955fc1f12d', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'balanced_4320', 'variant_index': 9, 'rec_idx': 112, 'offset': 10525568, 'ir_sha256': '0d02fd9f232ba5b30300964cb570293462446939711a0d34538ec5d9036be9c8', 'envelope_sha256': '457c98b4311009c021ff7fc586f5a952b1794b054f265b24211daa8908b508da', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
    {'variant': 'performance_1080', 'variant_index': 10, 'rec_idx': 126, 'offset': 11841216, 'ir_sha256': '13d797165e10ec9634b38a4add15a32c9b1ccd859bd6e73b4f74e265db21b7d2', 'envelope_sha256': '00239bc0fe38baffb1cdc6571b4f180e95f77c8f5310ceb85e481d86b11a954e', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'performance_2160', 'variant_index': 11, 'rec_idx': 140, 'offset': 13156928, 'ir_sha256': '44ddd92c950861b00be23243d28c79598a7c3f58dedef374c356dc7d84937aa4', 'envelope_sha256': '5ffb99bbc8c961f2a2cfecb7729dd6b48ec4383b165319fe013da773b9a10ddf', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'performance_4320', 'variant_index': 12, 'rec_idx': 154, 'offset': 14472640, 'ir_sha256': 'cc0d724ae01864958158cf1ff2aff6e334cd68d2f4c2df088e0bcaa7bb64d313', 'envelope_sha256': '4d6437df94cfaab0efb2bcc2f2dba9eb606f7fb317b736e204d2c852f2862414', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
    {'variant': 'ultraperf_1080', 'variant_index': 13, 'rec_idx': 168, 'offset': 15788288, 'ir_sha256': '9fdea8f98f924b3f997bda4a692932a46239e915d106acfa8a3fe9652ba4386f', 'envelope_sha256': '4f16b9c138a580bbdb5c50b31c47dcfede40de5aef2a93bf251853c0d5839c1b', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'ultraperf_2160', 'variant_index': 14, 'rec_idx': 182, 'offset': 17103984, 'ir_sha256': '6f2805c2919749db2a6bb5bfbf3a3adee9b1d2435a0d7ff2a05fb88b37d81ad4', 'envelope_sha256': '50a9da87b25c8c36646957c03583369c5c4fc1c7b734caa4c39003b0e778aaa3', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'ultraperf_4320', 'variant_index': 15, 'rec_idx': 196, 'offset': 18419680, 'ir_sha256': 'ae23ffef499a3bde96270d9da87241a874447c611833c45cb3bbd4ce50ebf3f8', 'envelope_sha256': '87a6d240ee8eafdd101af89df9833a777e3433c670b78f4c772d7e75f8a3634e', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
    {'variant': 'drs_1080', 'variant_index': 16, 'rec_idx': 210, 'offset': 19735312, 'ir_sha256': '1692bc855b0276526381ee54fe5b6d0a889aa2d97591a82f2bb415a329964f64', 'envelope_sha256': 'e1bb7ba59ae5c8ac982434082ce47f7cca74f8ee170f85a9eb3cdd64171c63c6', 'guard_x': 120, 'guard_y': 540, 'factor': 1},
    {'variant': 'drs_2160', 'variant_index': 17, 'rec_idx': 224, 'offset': 21051008, 'ir_sha256': 'b289069b36aee74280b8a83e7d03683bf97f08ebcb6b742c8d038a1fd96694cd', 'envelope_sha256': '436e5cb09cd56e1fff3895e43b6ab15b1eebf2e11cb418723a40124dc3cb3440', 'guard_x': 240, 'guard_y': 1080, 'factor': 2},
    {'variant': 'drs_4320', 'variant_index': 18, 'rec_idx': 238, 'offset': 22366704, 'ir_sha256': 'c674bc372fe51df67a337f98828d821645a11625a3bfe0c27f07b47ebd20eb27', 'envelope_sha256': 'ed03b05e97c56a0a2ca1adeae9643dcb2bbfc4bf6b79790bc3fa2ea6f8d6d05e', 'guard_x': 480, 'guard_y': 2160, 'factor': 4},
]

EXPECTED_GUARD_CYCLE = [(120, 540), (240, 1080), (480, 2160)] * 6
EXPECTED_FACTORS = [1, 2, 4] * 6

# Offline toolchain pins (IGC 2.10.10+18926, ocloc 25.18.33578.6, device 0xe20b).
# Compiled 2026-11-12 into analysis/offline-pre-412-variants/ with
# `-options '-vc-codegen'`; all 18 exit 0 ("Build succeeded" + triple warning).
IGC_VERSION = '2.10.10+18926'
OCLOC_RELEASE = '25.18.33578.6'
OCL_DEVICE = '0xe20b'
EXPECTED_BTIS = [8, 9, 1, 2, 3, 4, 5, 6, 7, 10, 11]
EXPECTED_ENV = {'grf_count': 128, 'simd_size': 1, 'has_dpas': True, 'has_sample': True}
EXPECTED_CODE_SIZE = 30464
OFFLINE_BUILDS = [
    {'variant': 'native_1080', 'zebin_sha256': 'b1781bb45a675005a81fb6679ad5f0b02d1252987a0d1f49af38cd4cf13751c2', 'code_sha256': '68b962b5a01984d02b0bbe15bda0c8e3d04dd49ad8a58d93e5c16dbb28f8792c', 'code_size': 30464},
    {'variant': 'native_2160', 'zebin_sha256': '6a8f0fe60135cb50a7140cb1b53400eb974075b077533dbdd82a30fec4bca2e6', 'code_sha256': 'ba7f966a695c7c9603c8f5d4a84dca6307768167da1c4a014f8b8513ec697b87', 'code_size': 30464},
    {'variant': 'native_4320', 'zebin_sha256': 'dede3aed811782d7d155d91b14b6b16f9fec7adf471b566eb0d4abcbbe7a62fa', 'code_sha256': '0ad9975575163bad2436c51ff1134283a80d531b4d24e0559f55d24421930f09', 'code_size': 30464},
    {'variant': 'quality_1080', 'zebin_sha256': '35fe9a6e112866ded0b81b30d263ec2483bb0415157fc1bf932f31fc7e2699f4', 'code_sha256': '88ccb2ffc6cb5ada59ee1d7e9bfb7c183636ffe4354b9ea7b74b7120ea05426a', 'code_size': 30464},
    {'variant': 'quality_2160', 'zebin_sha256': '05e99861c4969bcef18a2b5d5c773b9c39719dfd946c41b133294b10fd0ceeed', 'code_sha256': 'cce6dbabfa00dbf17d200650e3c5f8576d32842fd2915b09dcd483a4a3f7fadb', 'code_size': 30464},
    {'variant': 'quality_4320', 'zebin_sha256': '1d747d5026a146fbd76b384373ae208743ae31bf0abd6dd7c68b451971a043d8', 'code_sha256': 'a5ba59b01559ee04bc5c18841f5f313bc0595d926278de390ba48ef152cc8d55', 'code_size': 30464},
    {'variant': 'balanced_1080', 'zebin_sha256': '4fe17d55dd1a0d117765a4196a7ccb0c8b680b9012a78046d7d7445abf1e4275', 'code_sha256': '46c43ce56aa34fe408a396f4d656c90e0e3a61b4f276ac88a36f5878fb032638', 'code_size': 30464},
    {'variant': 'balanced_2160', 'zebin_sha256': '096a231fcc7480a6d206e1a82312b811868dd3f29bfa4e3c43291d5f404fac5c', 'code_sha256': '83e1bc5ce6f6054d1b4a6deda4a933d183f8365765a27b61a63dca81b0daaf29', 'code_size': 30464},
    {'variant': 'balanced_4320', 'zebin_sha256': '5921d2688e9d4e69c094af9e15e42766b2846a1afc9626a8f0397f9ebe317718', 'code_sha256': 'ec826861c578a9977f592be79bf9ecc5437edff7b1449226e278077e44fe1630', 'code_size': 30464},
    {'variant': 'performance_1080', 'zebin_sha256': '2580f6614a9cfe1e68662fceacf398402bff696701c5b23f527b52fad065cd89', 'code_sha256': '5daf0d65a41c3fa6ad48c987b28a9ee2fd66d933f09cd88dd6083db9b34c4b65', 'code_size': 30464},
    {'variant': 'performance_2160', 'zebin_sha256': 'f4d93730900ac5c6620044a461f6f66a8fd71fb33a3288b1673a640a0924632a', 'code_sha256': '0bb8b07db58e657a8a1a5879a45e2460517b6b87f29155c8e7addd8057803599', 'code_size': 30464},
    {'variant': 'performance_4320', 'zebin_sha256': '250ddd1aaf9fc0f353cd41fc8e38494c38bcb1c08990585fd91b84e2e62f832d', 'code_sha256': '1437b71591982435720b8bec6b2e24548e463936882705dfa2ca9a96f3da60d6', 'code_size': 30464},
    {'variant': 'ultraperf_1080', 'zebin_sha256': 'e7640611abeab58d18f0ca71a33600b5df28bf52514ea8dec581dbb664bb3176', 'code_sha256': '67ad389945c3399409e0aa88b762b3280896b80845abba753988e8ddd6c48d81', 'code_size': 30464},
    {'variant': 'ultraperf_2160', 'zebin_sha256': 'cb80102b21e884cefbbaa0722d9eaa1275ac12d89596a0c7837dc950194830b6', 'code_sha256': '679b9162d3d9b6bc6f16e947b29c1ff1d28e3ac1f2fa108031e604144eead584', 'code_size': 30464},
    {'variant': 'ultraperf_4320', 'zebin_sha256': '503f1269b911f5e7bcd31573bcb06ad34e7b6fa9c146f0ac945b85a6dcb426f7', 'code_sha256': '46c84cb9ac0824f33c1ab54a8f20c060d4da77fd87f15686169de99414e7af65', 'code_size': 30464},
    {'variant': 'drs_1080', 'zebin_sha256': 'e481a5f8f71e861c59dc01375b7e079efd0c87e42d65ea47625edf57a8e4c2e5', 'code_sha256': '04268212e33d83ff881237c39d5e558e52bf159c94441c91294420a7a9631c68', 'code_size': 30464},
    {'variant': 'drs_2160', 'zebin_sha256': '243f845f98c730677b82138ca52506c4a3147b36b961dc7e50fc945332a5b535', 'code_sha256': '5a589d020720939d8c682b787e2073c8077586cae626c011d38431ba4558680a', 'code_size': 30464},
    {'variant': 'drs_4320', 'zebin_sha256': '4c7b279639a0a45cb09cc432824c320b604b8875d653c27232fb6f3fe85483cd', 'code_sha256': 'b3c63d8f27441e12bb2a3878570f20976a71fb8814593b4eb4d037c75c3152c1', 'code_size': 30464},
]

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
    lines = text.splitlines()
    entries = re.findall(r'OpEntryPoint\s+Kernel\s+(%\w+)\s+"([^"]+)"\s+(%\w+)', text)
    if len(entries) != 1:
        raise ValueError(f'Expected exactly one Kernel entry, got {entries}')
    entry_id, entry_name, entry_iface = entries[0]
    if (entry_id, entry_name, entry_iface) != (ENTRY_ID, ENTRY_NAME, ENTRY_INTERFACE):
        raise ValueError(f'PRE entry changed: {entries}')
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
    builtin_names = re.findall(r'BuiltIn\s+(\w+)', text)
    if sorted(set(builtin_names)) != ['WorkgroupId']:
        raise ValueError(f'Unexpected BuiltIns: {sorted(set(builtin_names))}')
    if not re.search(r'OpDecorate\s+%__spirv_BuiltInWorkgroupId\s+BuiltIn\s+WorkgroupId', text):
        raise ValueError('WorkgroupId BuiltIn decoration missing')
    if not re.search(r'%__spirv_BuiltInWorkgroupId\s+=\s+OpVariable\s+%_ptr_Input_v3ulong\s+Input', text):
        raise ValueError('WorkgroupId interface variable changed')
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
        'workgroup_id_guards': {'x_at_least': x_bound, 'y_at_least': y_bound},
        'genx_operation_call_counts': dict(operations),
        'typed_store_surface_operands': list(store_surface_operands),
    }


def _read_pack() -> bytes:
    if not PACK.is_file():
        raise unittest.SkipTest(f'Missing pinned pack artifact: {PACK}')
    data = PACK.read_bytes()
    if len(data) != RAW_SIZE:
        raise ValueError(f'Pack size drift: {len(data)} != {RAW_SIZE}')
    if hashlib.sha256(data).hexdigest() != RAW_SHA256:
        raise ValueError('Pack SHA-256 drift: unreviewed 4.1.2 bytes')
    return data


def _inspect_zebin():
    import importlib.util
    spec = importlib.util.spec_from_file_location('inspect_zebin', str(ROOT / 'tools' / 'inspect_zebin.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackVariantTableTests(unittest.TestCase):
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
        self.assertEqual([v['rec_idx'] for v in VARIANTS], PRE_RECORD_INDICES)

    def test_all_18_envelope_pins(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        self.assertEqual(len(VARIANTS), 18)
        seen_ir = set()
        for v in VARIANTS:
            with self.subTest(variant=v['variant']):
                rec = records[v['rec_idx']]
                self.assertEqual(rec['offset'], v['offset'], 'pack offset')
                self.assertEqual(rec['ir_size'], PRE_IR_SIZE, 'ir_size')
                self.assertEqual(rec['trailer_size'], PRE_TRAILER_SIZE, 'trailer_size')
                self.assertEqual(rec['envelope_size'], PRE_ENVELOPE_SIZE, 'envelope_size')
                self.assertEqual(rec['end'], v['offset'] + PRE_ENVELOPE_SIZE, 'end')
                self.assertEqual(rec['embedded_string_a'], PRE_STRING_A)
                self.assertEqual(rec['embedded_string_b'], PRE_STRING_B)
                self.assertEqual(rec['ir_sha256'], v['ir_sha256'])
                self.assertEqual(rec['envelope_sha256'], v['envelope_sha256'])
                ir = data[rec['offset']:rec['offset'] + rec['ir_size']]
                self.assertEqual(hashlib.sha256(ir).hexdigest(), v['ir_sha256'])
                self.assertEqual(hashlib.sha256(data[rec['offset']:rec['end']]).hexdigest(),
                                 v['envelope_sha256'])
                self.assertEqual(ir[:4], b'\x03\x02\x23\x07')
                self.assertIn(b'fsr4_pre_xmx', ir)
                seen_ir.add(v['ir_sha256'])
        self.assertEqual(len(seen_ir), 18, '18 distinct IR SHAs required')

    def test_guard_and_factor_cycles(self):
        self.assertEqual([(v['guard_x'], v['guard_y']) for v in VARIANTS], EXPECTED_GUARD_CYCLE)
        self.assertEqual([v['factor'] for v in VARIANTS], EXPECTED_FACTORS)
        for v in VARIANTS:
            with self.subTest(variant=v['variant']):
                if v['variant'].endswith('_1080'):
                    self.assertEqual((v['guard_x'], v['guard_y']), (120, 540))
                    self.assertEqual(v['factor'], 1)
                elif v['variant'].endswith('_2160'):
                    self.assertEqual((v['guard_x'], v['guard_y']), (240, 1080))
                    self.assertEqual(v['factor'], 2)
                elif v['variant'].endswith('_4320'):
                    self.assertEqual((v['guard_x'], v['guard_y']), (480, 2160))
                    self.assertEqual(v['factor'], 4)
                else:
                    self.fail(f"Unexpected variant suffix: {v['variant']}")
                self.assertEqual(v['factor'] * v['factor'] * 0x7e9000,
                                 {1: 8294400, 2: 33177600, 4: 132710400}[v['factor']])

    def test_variant_order_assumption_is_explicit(self):
        names = [v['variant'] for v in VARIANTS]
        self.assertEqual(names, [
            'native_1080', 'native_2160', 'native_4320',
            'quality_1080', 'quality_2160', 'quality_4320',
            'balanced_1080', 'balanced_2160', 'balanced_4320',
            'performance_1080', 'performance_2160', 'performance_4320',
            'ultraperf_1080', 'ultraperf_2160', 'ultraperf_4320',
            'drs_1080', 'drs_2160', 'drs_4320',
        ])
        self.assertEqual([v['variant_index'] for v in VARIANTS], list(range(1, 19)))
        for k, v in enumerate(VARIANTS):
            self.assertEqual(v['rec_idx'], 14 * k)


@unittest.skipUnless(SPIRV_DIS is not None, 'spirv-dis is not installed')
class AllVariantsDisassemblyTests(unittest.TestCase):
    def test_all_18_share_entry_args_guards_counts_store(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        for v in VARIANTS:
            with self.subTest(variant=v['variant'], record=v['rec_idx']):
                rec = records[v['rec_idx']]
                ir = data[rec['offset']:rec['offset'] + rec['ir_size']]
                text = disassemble(ir)
                census = extract_census(text, expected_guards=(v['guard_x'], v['guard_y']))
                self.assertEqual(census['entry'], ENTRY_NAME)
                self.assertEqual(census['entry_id'], ENTRY_ID)
                self.assertEqual(census['workgroup_id_guards'],
                                 {'x_at_least': v['guard_x'], 'y_at_least': v['guard_y']})
                self.assertEqual(census['genx_operation_call_counts'], EXPECTED_COUNTS)
                self.assertEqual(census['typed_store_surface_operands'], [STORE_SURFACE_SSA])

    def test_native1080_matches_index_zero_reference(self):
        data = _read_pack()
        records = parse_cm_payloads.parse(data)
        ref = disassemble(data[records[0]['offset']:records[0]['offset'] + PRE_IR_SIZE])
        ref_census = extract_census(ref, expected_guards=(120, 540))
        self.assertEqual(ref_census['entry'], ENTRY_NAME)
        for v in VARIANTS:
            with self.subTest(variant=v['variant']):
                rec = records[v['rec_idx']]
                text = disassemble(data[rec['offset']:rec['offset'] + PRE_IR_SIZE])
                census = extract_census(text, expected_guards=(v['guard_x'], v['guard_y']))
                self.assertEqual(census['entry'], ref_census['entry'])
                self.assertEqual(census['genx_operation_call_counts'],
                                 ref_census['genx_operation_call_counts'])
                self.assertEqual(census['typed_store_surface_operands'],
                                 ref_census['typed_store_surface_operands'])


class OfflineCompileStabilityTests(unittest.TestCase):
    def test_toolchain_pins_are_documented(self):
        self.assertEqual(IGC_VERSION, '2.10.10+18926')
        self.assertEqual(OCLOC_RELEASE, '25.18.33578.6')
        self.assertEqual(OCL_DEVICE, '0xe20b')
        self.assertEqual(EXPECTED_BTIS, [8, 9, 1, 2, 3, 4, 5, 6, 7, 10, 11])
        self.assertEqual(EXPECTED_ENV['grf_count'], 128)
        self.assertEqual(EXPECTED_ENV['simd_size'], 1)
        self.assertTrue(EXPECTED_ENV['has_dpas'])
        self.assertTrue(EXPECTED_ENV['has_sample'])
        self.assertEqual(EXPECTED_CODE_SIZE, 30464)

    def test_all_18_offline_builds_verify_when_present(self):
        missing = []
        for idx, v in enumerate(VARIANTS):
            cands = sorted(VARIANTS_DIR.glob(f"out-{idx:02d}-rec{v['rec_idx']:04d}/pre_bmg.bin"))
            if not cands:
                cands = sorted(VARIANTS_DIR.glob(f"out-{idx:02d}-rec*/pre_bmg.bin"))
            if not cands:
                missing.append(v['variant'])
        if missing:
            raise unittest.SkipTest(f"Missing offline zebins for: {', '.join(missing)}")
        inspect_zebin = _inspect_zebin()
        for idx, v in enumerate(VARIANTS):
            with self.subTest(variant=v['variant']):
                cands = sorted(VARIANTS_DIR.glob(f"out-{idx:02d}-rec{v['rec_idx']:04d}/pre_bmg.bin"))
                if not cands:
                    cands = sorted(VARIANTS_DIR.glob(f"out-{idx:02d}-rec*/pre_bmg.bin"))
                data = cands[0].read_bytes()
                rep = inspect_zebin.inspect(data, ENTRY_NAME)
                btis = [(r['arg_index'], r['bti_value']) for r in rep['binding_table_indices']]
                self.assertEqual([a for a, _ in btis], list(range(11)), 'arg_index order')
                self.assertEqual([b for _, b in btis], EXPECTED_BTIS, 'BTI order')
                self.assertEqual(rep['code_size'], EXPECTED_CODE_SIZE)
                env = rep['execution_env']
                for key, expected in EXPECTED_ENV.items():
                    self.assertEqual(env[key], expected, key)
                pinned = next(b for b in OFFLINE_BUILDS if b['variant'] == v['variant'])
                self.assertEqual(rep['zebin_sha256'], pinned['zebin_sha256'], 'zebin sha')
                self.assertEqual(rep['code_sha256'], pinned['code_sha256'], 'code sha')


class SyntheticFailClosedTests(unittest.TestCase):
    def _fixture(self, args=None, guards=(120, 540)):
        args = EXPECTED_ARGS if args is None else args
        declarations = '\n'.join(f'{i} = OpFunctionParameter {t}' for i, t in enumerate(args))
        types = '\n'.join([
            '%770 = OpTypeBufferSurfaceINTEL ReadWrite',
            '%774 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadWrite',
            '%778 = OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly',
            '%782 = OpTypeSampler',
        ])
        guard_lines = '\n'.join(f'%g{i} = OpUGreaterThanEqual %bool %x{i} %uint_{b}'
                                for i, b in enumerate(guards))
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

    def test_fixture_extracts(self):
        result = extract_census(self._fixture())
        self.assertEqual(result['genx_operation_call_counts'],
                         {'3d_load': 1, '3d_sample': 1, 'typed_quad_store': 1})

    def test_rejects_changed_argument_order(self):
        changed = EXPECTED_ARGS.copy()
        changed[1], changed[2] = changed[2], changed[1]
        with self.assertRaisesRegex(ValueError, 'argument order changed'):
            extract_census(self._fixture(changed))

    def test_rejects_missing_or_changed_guards(self):
        with self.assertRaisesRegex(ValueError, 'workgroup guard'):
            extract_census(self._fixture(guards=(120,)))

    def test_rejects_store_surface_rebound(self):
        text = self._fixture().replace('OpStore %4058 %1920', 'OpStore %4058 %1921')
        with self.assertRaisesRegex(ValueError, 'arg 1|surface'):
            extract_census(text)

    def test_rejects_changed_store_mask(self):
        text = self._fixture().replace('%uchar_7 %10694', '%uchar_15 %10694')
        with self.assertRaisesRegex(ValueError, 'mask/surface'):
            extract_census(text)

    def test_rejects_missing_operation_classes(self):
        text = self._fixture().replace('%llvm_genx_3d_load_', '%other_')
        with self.assertRaisesRegex(ValueError, 'Expected image loads'):
            extract_census(text)

    def test_rejects_extra_entry_point(self):
        text = self._fixture() + '\nOpEntryPoint Kernel %99999 "other" %__spirv_BuiltInWorkgroupId'
        with self.assertRaisesRegex(ValueError, 'exactly one Kernel entry'):
            extract_census(text)


if __name__ == '__main__':
    unittest.main()
