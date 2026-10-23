#!/usr/bin/env python3
"""Extract a small, pinned static contract from the PRE SPIR-V disassembly.

This is not a SPIR-V validator, resource-format decoder, or output oracle.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re


EXPECTED_SHA256 = '7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e'
ENTRY_ID = '%10259'
EXPECTED_ARGS = ['%587', '%591', '%595', '%595', '%595', '%595',
                 '%595', '%595', '%595', '%587', '%587', '%599']


def extract(text):
    """Extract only declarations and instruction forms relied on by the contract."""
    lines = text.splitlines()
    entry = re.compile(r'^\s*%10259 = OpFunction %void DontInline %603$')
    start = next((i for i, line in enumerate(lines) if entry.match(line)), None)
    if start is None:
        raise ValueError('Pinned PRE entry function not found')
    params = []
    for line in lines[start + 1:]:
        if 'OpLabel' in line:
            break
        match = re.search(r'OpFunctionParameter\s+(%\w+)', line)
        if match:
            params.append(match.group(1))
    if params != EXPECTED_ARGS:
        raise ValueError('PRE entry resource argument order changed')

    declarations = {}
    for line in lines:
        match = re.search(r'^\s*(%\w+) = (OpType\w+)(?:\s+(.*?))?\s*$', line)
        if match:
            declarations[match.group(1)] = (match.group(2), match.group(3) or '')
    types = {
        '%587': 'BufferSurfaceINTEL ReadWrite',
        '%591': 'Image 2D ReadWrite; format Unknown',
        '%595': 'Image 2D ReadOnly; format Unknown',
        '%599': 'Sampler',
    }
    expected_types = {
        '%587': ('OpTypeBufferSurfaceINTEL', 'ReadWrite'),
        '%591': ('OpTypeImage', '%void 2D 0 0 0 0 Unknown ReadWrite'),
        '%595': ('OpTypeImage', '%void 2D 0 0 0 0 Unknown ReadOnly'),
        '%599': ('OpTypeSampler', ''),
    }
    if any(declarations.get(type_id) != expected
           for type_id, expected in expected_types.items()):
        raise ValueError('PRE resource type declarations changed')
    resources = [
        {'arg_index': i, 'type': types[type_id]}
        for i, type_id in enumerate(params)
    ]

    guards = {}
    for line in lines:
        match = re.search(r'OpUGreaterThanEqual\s+%bool\s+%\w+\s+%uint_(120|540)\b', line)
        if match:
            guards[int(match.group(1))] = guards.get(int(match.group(1)), 0) + 1
    if guards != {120: 1, 540: 1}:
        raise ValueError(f'Expected one workgroup guard for each pinned bound, got {guards}')

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
            operations['typed_quad_store'] += 1
            call = re.search(r'%llvm_genx_lsc_store_quad_typed_bti_\w+\s+(.+)$', line)
            operands = call.group(1).split() if call else []
            controls = [re.fullmatch(r'%uchar_(\d+)', operand) for operand in operands]
            if (len(operands) != 10 or any(m is None for m in controls[1:4])
                    or not re.fullmatch(r'%\w+', operands[4])):
                raise ValueError('Unsupported typed-store channel mask/surface operands')
            store_channel_masks.append(int(controls[3].group(1)))
            store_surface_operands.append(operands[4])
    if not all(operations.values()):
        raise ValueError(f'Expected image loads, sampler operations and typed stores: {operations}')
    if store_channel_masks != [7] or store_surface_operands != ['%9780']:
        raise ValueError('Unexpected typed-store channel mask or surface SSA operand')
    surface_flow = [
        r'%1687 = OpFunctionCall %uint %llvm_genx_address_convert_i32_p1opencl_image2d_rw_t %606',
        r'OpStore %3656 %1687',
        r'%3749 = OpLoad %uint %3656',
        r'OpStore %3460 %3749',
        r'%9769 = OpLoad %uint %3460',
        r'OpStore %3397 %9769',
        r'%9774 = OpLoad %uint %3397',
        r'OpStore %3391 %9774',
        r'%9780 = OpLoad %uint %3391',
    ]
    normalized = [' '.join(line.split()) for line in lines]
    if any(not any(re.search(pattern, line) for line in normalized) for pattern in surface_flow):
        raise ValueError('Typed-store surface SSA no longer originates from arg 1 image RW')

    return {
        'entry': 'fsr4_pre_xmx',
        'entry_argument_resources': resources,
        'workgroup_id_guards': {'x_at_least': 120, 'y_at_least': 540},
        'genx_operation_call_counts': operations,
        'typed_store_channel_masks': store_channel_masks,
        'typed_store_surface_operands': store_surface_operands,
        'typed_store_surface_origin_arg_index': 1,
        'image_format': 'Unknown in OpTypeImage; not inferred here',
        'limitations': [
            'Counts are syntactic call counts, not unique pixels, resource identities, or access bounds.',
            'Does not identify color/depth/motion semantics or prove output values.',
            'Does not establish runtime local size, dispatch API behavior, or execution mask.',
        ],
    }


def inspect(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError(f'Unreviewed SPIR-V disassembly SHA-256: {digest}')
    result = extract(data.decode('utf-8'))
    result['spirv_disassembly_sha256'] = digest
    result['status'] = 'static-extraction-only'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spvasm', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.spvasm.read_bytes()), indent=2))


if __name__ == '__main__':
    main()
