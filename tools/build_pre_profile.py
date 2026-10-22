#!/usr/bin/env python3
"""Generate a narrowly pinned experimental PRE mapping from offline compiler evidence."""
import argparse
import hashlib
import json
from pathlib import Path

from inspect_zebin import inspect
from reconstruct_pre import DLL_SHA256, pre_layout

EXPECTED_BTIS = [8, 9, 1, 2, 3, 4, 5, 6, 7, 10, 11]
# First Xe2 PRE envelope, including its embedded compiler-options footer.
EXPECTED_INPUT = '76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b'
# Pin the reviewed compiler output too: matching BTIs do not establish that the
# compiler consumed this envelope/options, as the stripped-input control proves.
EXPECTED_ZEBIN = '3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2'


def build(source, zebin):
    sha = hashlib.sha256(source).hexdigest()
    if sha != EXPECTED_INPUT:
        raise ValueError('Unreviewed CM input; this profile covers one PRE envelope only')
    if hashlib.sha256(zebin).hexdigest() != EXPECTED_ZEBIN:
        raise ValueError('Unreviewed compiler output/options; native identity must be re-reviewed')
    report = inspect(zebin, 'fsr4_pre_xmx')
    btis = sorted(report['binding_table_indices'], key=lambda b: b['arg_index'])
    if [b['arg_index'] for b in btis] != list(range(11)) or [b['bti_value'] for b in btis] != EXPECTED_BTIS:
        raise ValueError('Compiler changed the reviewed PRE argument/BTI layout')
    env = report['execution_env']
    if env.get('simd_size') != 1 or not env.get('has_dpas') or not env.get('has_sample'):
        raise ValueError('Unexpected PRE execution environment')
    layout = pre_layout([7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10])
    return {'schema_version': 1, 'status': 'experimental-offline-only',
            'source_dll_sha256': DLL_SHA256, 'input_sha256': sha,
            'zebin_sha256': report['zebin_sha256'], 'code_sha256': report['code_sha256'],
            'kernel': 'fsr4_pre_xmx', 'target_pci_id': '0xe20b',
            'vkd3d_reference': 'ef9a02e873715c9e2da0d6db8a236aca8380b303',
            'expected_push_size': layout['push_range_size'], 'table_pc_base': 4,
            'surfaces': [{'arg_index': i, 'bti': bti, 'table_index': i, 'element': 0,
                          'root_index': i+1, 'push_byte_offset': 4+4*i}
                         for i, bti in enumerate(EXPECTED_BTIS)],
            'remaining_reviews': [
                'Nonzero stateful pointer arguments and private_base_stateless payload.',
                'Actual runtime Vulkan layout and descriptor bindings.',
                'Dynamic sampler vs fallback behavior.',
                'Local workgroup dimensions and correctness of GPU readback.',
                'Other PRE variants and all other FSR stages.',
            ]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('cmspv', type=Path)
    p.add_argument('zebin', type=Path)
    a = p.parse_args()
    print(json.dumps(build(a.cmspv.read_bytes(), a.zebin.read_bytes()), indent=2))


if __name__ == '__main__':
    main()
