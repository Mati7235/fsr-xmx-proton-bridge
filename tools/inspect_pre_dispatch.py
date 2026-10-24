#!/usr/bin/env python3
"""Report hash-pinned static dispatch evidence for PRE native_1080.

This deliberately does not infer a required workgroup size from SIMD metadata,
assembly execution widths, or a packer/Vulkan placeholder selector.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


EXPECTED_ZE_INFO_SHA256 = '5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c'
EXPECTED_ASSEMBLY_SHA256 = 'a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660'
EXPECTED_ZEBIN_SHA256 = '3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2'
EXPECTED_IR_SHA256 = '7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e'
KERNEL = 'fsr4_pre_xmx'


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inspect(ze_info, assembly, zebin, spirv_assembly=None):
    """Validate pinned inputs and emit only directly supported observations."""
    ze_hash = sha256(ze_info)
    asm_hash = sha256(assembly)
    zebin_hash = sha256(zebin)
    if ze_hash != EXPECTED_ZE_INFO_SHA256:
        raise ValueError(f'Unreviewed or truncated .ze_info SHA-256: {ze_hash}')
    if asm_hash != EXPECTED_ASSEMBLY_SHA256:
        raise ValueError(f'Unreviewed or truncated IGA assembly SHA-256: {asm_hash}')
    if zebin_hash != EXPECTED_ZEBIN_SHA256:
        raise ValueError(f'Unreviewed or truncated zebin SHA-256: {zebin_hash}')

    try:
        info = ze_info.decode('utf-8')
        asm = assembly.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ValueError('Pinned evidence is not valid UTF-8 text') from exc

    # Validate kernel scope and the small set of metadata facts cited below.
    if len(re.findall(r'^  - name:\s*' + re.escape(KERNEL) + r'\s*$', info, re.M)) != 1:
        raise ValueError('Expected exactly one pinned PRE kernel record')
    kernel_record = re.split(r'^  - name:\s*', info, flags=re.M)[1]
    if not kernel_record.startswith(KERNEL + '\n'):
        raise ValueError('Unexpected first kernel record')
    env = re.search(r'^    execution_env:\s*\n(.*?)(?=^    \w+:|\Z)', kernel_record, re.M | re.S)
    payload = re.search(r'^    per_thread_payload_arguments:\s*\n(.*?)(?=^    \w+:|\Z)', kernel_record, re.M | re.S)
    if not env or not re.search(r'^      simd_size:\s+1\s*$', env.group(1), re.M):
        raise ValueError('Pinned SIMD metadata no longer matches expected simd_size: 1')
    if not payload or not re.search(
            r'^      - arg_type:\s+packed_local_ids\s*\n'
            r'^        offset:\s+0\s*\n^        size:\s+6\s*$',
            payload.group(1), re.M):
        raise ValueError('Pinned packed_local_ids metadata changed')

    # Check the known dimension-attribute spellings in this complete,
    # hash-pinned compiler metadata block; this is not a general YAML parser.
    dimension_attrs = re.findall(
        r'^\s*(?:required_work_group_size|reqd_work_group_size|local_size(?:_[xyz])?)\s*:',
        kernel_record, re.M)
    if dimension_attrs:
        raise ValueError('Unexpected local-size metadata attribute found')

    simd16_count = len(re.findall(r'\bsimd16\b', asm))
    if simd16_count == 0:
        raise ValueError('Expected SIMD16 operations in pinned IGA disassembly')
    result = {
        'status': 'static-evidence-only',
        'kernel': KERNEL,
        'evidence': {
            'ze_info_sha256': ze_hash,
            'iga_assembly_sha256': asm_hash,
            'zebin_sha256': zebin_hash,
        },
        'observed': {
            'compiler_simd_size': 1,
            'per_thread_payload': {'arg_type': 'packed_local_ids', 'offset': 0, 'size_bytes': 6},
            'iga_simd16_instruction_text_occurrences': simd16_count,
        },
        'not_established': {
            'required_workgroup_size': None,
            'runtime_local_size': None,
            'hardware_threadcount': None,
            'vulkan_placeholder_selector': 'not a dispatch geometry source; packer 1,1,1 is provisional',
            'runtime_workgroupcount': None,
            'execution_mask': 'full and constant mask assumed by payload audit; runtime not proven',
        },
    }
    if spirv_assembly is not None:
        ir_hash = sha256(spirv_assembly)
        if ir_hash != EXPECTED_IR_SHA256:
            raise ValueError(f'Unreviewed or truncated SPIR-V assembly SHA-256: {ir_hash}')
        ir = spirv_assembly.decode('utf-8')
        builtins = re.findall(r'^\s*OpDecorate\s+%\w+\s+BuiltIn\s+(\w+)\s*$', ir, re.M)
        modes = re.findall(r'^\s*OpExecutionMode\s+%10259\s+(.+?)\s*$', ir, re.M)
        if builtins != ['WorkgroupId'] or any(mode.startswith('LocalSize') for mode in modes):
            raise ValueError('Pinned PRE builtin declarations or execution modes changed')
        result['evidence']['spirv_assembly_sha256'] = ir_hash
        result['observed']['spirv_builtin_declarations'] = builtins
        result['observed']['spirv_entry_execution_modes'] = modes
        result['observed']['ir_limit'] = (
            'No local invocation builtin is declared in this pinned textual module; '
            'this does not prove native per-thread payload is unused or authorize a local size.')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ze_info', type=Path)
    parser.add_argument('assembly', type=Path)
    parser.add_argument('zebin', type=Path)
    parser.add_argument('--spirv-assembly', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.ze_info.read_bytes(), args.assembly.read_bytes(),
                             args.zebin.read_bytes(),
                             args.spirv_assembly.read_bytes() if args.spirv_assembly else None), indent=2))


if __name__ == '__main__':
    main()
