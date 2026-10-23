#!/usr/bin/env python3
"""Build our deterministic DPAS/resource-map probe OFFLINE, never dispatch GPU work.

This is NOT the FSR kernel. All shader source here belongs to this lab. Requires
locally extracted pinned IGC/ocloc and installed CPU SPIR-V/GLSL assembler tools.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess

from apply_cmk_mapping import convert
from audit_pre_payload import audit_native, parse_isa
from inspect_zebin import inspect, sections

SLOTS = [7, 8, 0, 1, 2, 3, 4, 5, 6, 9, 10]
CM_LOCAL_SIZE = (1, 1, 1)
EXPECTED_GRF_COUNT = 128


def shader_source():
    lines = ['OpCapability Addresses', 'OpCapability Linkage', 'OpCapability Kernel',
             'OpCapability Vector16', 'OpCapability VectorComputeINTEL', 'OpCapability VectorAnyINTEL',
             'OpExtension "SPV_INTEL_vector_compute"', 'OpMemoryModel Physical64 OpenCL',
             'OpEntryPoint Kernel %probe "bridge_probe"',
             'OpExecutionMode %probe SubgroupSize 1',
             'OpExecutionMode %probe SharedLocalMemorySizeINTEL 0',
             'OpExecutionMode %probe NamedBarrierCountINTEL 0',
             'OpName %probe "bridge_probe"',
             'OpDecorate %probe LinkageAttributes "bridge_probe" Export',
             'OpDecorate %probe VectorComputeFunctionINTEL']
    lines += [f'OpDecorate %arg{i} FuncParamIOKindINTEL 0' for i in range(11)]
    imports = {'convert': 'llvm.genx.address.convert.i32.p1intel.buffer_rw_t',
               'dpas': 'llvm.genx.dpas2.v128f32.v128f32.v128i32.v64i32',
               'store': 'llvm.genx.oword.st.v4f32'}
    for name, symbol in imports.items():
        lines += [f'OpName %{name} "{symbol}"',
                  f'OpDecorate %{name} LinkageAttributes "{symbol}" Import',
                  f'OpDecorate %{name} VectorComputeFunctionINTEL']
    lines += ['%void = OpTypeVoid', '%uint = OpTypeInt 32 0', '%float = OpTypeFloat 32',
              '%surface = OpTypeBufferSurfaceINTEL ReadWrite',
              '%v128f = OpTypeVector %float 128', '%v128u = OpTypeVector %uint 128',
              '%v64u = OpTypeVector %uint 64', '%u0 = OpConstant %uint 0',
               '%u8 = OpConstant %uint 8', '%u10 = OpConstant %uint 10',
               *[f'%off{i} = OpConstant %uint {i}' for i in range(32)],
              f'%packed = OpConstant %uint {0x3c003c00}',  # Two FP16 numeric ones.
              '%zero = OpConstantNull %v128f',
              '%weights = OpConstantComposite %v128u '+' '.join(['%packed']*128),
              '%activations = OpConstantComposite %v64u '+' '.join(['%packed']*64)]
    for i in range(11):
        lines += [f'%f{i} = OpConstant %float {i}.0',
                  f'%tag{i} = OpConstantComposite %v128f '+' '.join([f'%f{i}']*128)]
    lines += ['%v4f = OpTypeVector %float 4',
              '%ft_convert = OpTypeFunction %uint %surface',
              '%ft_store = OpTypeFunction %void %uint %uint %v4f',
              '%ft_dpas = OpTypeFunction %v128f %v128f %v128u %v64u '+' '.join(['%uint']*6),
              '%ft_probe = OpTypeFunction %void '+' '.join(['%surface']*11),
              '%convert = OpFunction %uint Pure %ft_convert',
              '%convarg = OpFunctionParameter %surface', 'OpFunctionEnd',
              '%store = OpFunction %void DontInline %ft_store',
              '%st0 = OpFunctionParameter %uint', '%st1 = OpFunctionParameter %uint',
              '%st2 = OpFunctionParameter %v4f', 'OpFunctionEnd',
              '%dpas = OpFunction %v128f Pure %ft_dpas',
              '%dp0 = OpFunctionParameter %v128f', '%dp1 = OpFunctionParameter %v128u',
              '%dp2 = OpFunctionParameter %v64u']
    lines += [f'%dp{i} = OpFunctionParameter %uint' for i in range(3, 9)]
    lines += ['OpFunctionEnd', '%probe = OpFunction %void DontInline %ft_probe']
    lines += [f'%arg{i} = OpFunctionParameter %surface' for i in range(11)]
    lines += ['%entry = OpLabel',
              '%matrix = OpFunctionCall %v128f %dpas %zero %weights %activations %u10 %u10 %u8 %u8 %u0 %u0']
    for i in range(11):
        lines += [f'%bti{i} = OpFunctionCall %uint %convert %arg{i}',
                  f'%value{i} = OpFAdd %v128f %matrix %tag{i}']
        for chunk in range(32):
            start = chunk*4
            lines += [f'%part{i}_{chunk} = OpVectorShuffle %v4f %value{i} %value{i} '
                      + ' '.join(str(start+lane) for lane in range(4)),
                      f'%write{i}_{chunk} = OpFunctionCall %void %store %bti{i} %off{chunk} %part{i}_{chunk}']
    return '\n'.join(lines+['OpReturn', 'OpFunctionEnd', ''])


def placeholder_source(z):
    return f'''#version 450
layout(local_size_x=1, local_size_y=1, local_size_z={z}) in;
layout(set=0,binding=0,std430) buffer Heap {{ uint words[]; }} heap[16];
void main() {{
    if (gl_LocalInvocationIndex == 0u)
        heap[0].words[0] = 0x584d5843u;
}}
'''


def audit_probe_spirv(text):
    """Narrow audit: entry surface args are only opaque address-convert inputs."""
    ids = r'%[\w.]+'
    entry = re.findall(r'^\s*OpEntryPoint Kernel ('+ids+r') "bridge_probe"', text, re.M)
    if len(entry) != 1:
        raise ValueError('Payload audit requires exact bridge_probe entry point')
    imports = dict(re.findall(r'^\s*OpDecorate\s+('+ids+r') LinkageAttributes "([^"]+)" Import',
                              text, re.M))
    convert = [i for i, name in imports.items()
               if name == 'llvm.genx.address.convert.i32.p1intel.buffer_rw_t']
    dpas = [i for i, name in imports.items() if name.startswith('llvm.genx.dpas2.')]
    if len(convert) != 1 or len(dpas) != 1:
        raise ValueError('Payload audit requires the reviewed address-convert and DPAS imports')

    lines = text.splitlines()
    try:
        start = next(i for i, line in enumerate(lines)
                     if re.match(r'^\s*'+re.escape(entry[0])+r' = OpFunction\b', line))
        end = next(i for i in range(start+1, len(lines)) if 'OpFunctionEnd' in lines[i])
    except StopIteration as exc:
        raise ValueError('Malformed bridge_probe function') from exc
    body = lines[start+1:end]
    params = [re.match(r'^\s*('+ids+r') = OpFunctionParameter\s+('+ids+r')', line)
              for line in body]
    params = [m.groups() for m in params if m]
    if len(params) != 11 or any(typ != params[0][1] for _, typ in params):
        raise ValueError('Payload audit requires exactly eleven opaque surface parameters')
    surface_type = params[0][1]
    if not re.search(r'^\s*'+re.escape(surface_type)+r' = OpTypeBufferSurfaceINTEL ReadWrite\s*$',
                     text, re.M):
        raise ValueError('Entry arguments are not read/write buffer surfaces')

    body = [line for line in body if 'OpFunctionParameter' not in line and 'OpLabel' not in line]
    for parameter, _ in params:
        uses = [line for line in body if re.search(r'(?<![\w.])'+re.escape(parameter)+r'(?![\w.])', line)]
        if len(uses) != 1 or not re.search(
                r'OpFunctionCall\s+%[\w.]+\s+'+re.escape(convert[0])+r'\s+'
                +re.escape(parameter)+r'\s*$', uses[0]):
            raise ValueError('Surface parameter has an unreviewed SPIR-V use')
    if not any(re.search(r'OpFunctionCall\s+%[\w.]+\s+'+re.escape(dpas[0])+r'\b', line)
               for line in body):
        raise ValueError('Payload audit refuses a kernel without a real DPAS call')
    return {'status': 'opaque-surface-args-only', 'surface_arguments': len(params),
            'uses': 'each entry argument is passed once to address.convert; no direct pointer loads'}


def payload_layout_sha256(report):
    layout = [report['payload_arguments'], report['per_thread_payload_arguments']]
    encoded = json.dumps(layout, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_payload_layout(report):
    expected_args = [
        {'arg_type': 'arg_bypointer', 'offset': 8*(i+1), 'size': 8, 'arg_index': i,
         'addrmode': 'stateful', 'addrspace': 'global', 'access_type': 'readwrite'}
        for i in range(11)
    ]
    actual_args = [p for p in report['payload_arguments'] if p.get('size', 0)]
    if actual_args[:11] != expected_args or len(actual_args) != 12 or actual_args[11] != {
            'arg_type': 'private_base_stateless', 'offset': 0, 'size': 8}:
        raise ValueError('Probe cross-thread pointer payload differs from the narrowly audited layout')
    zero_args = [p for p in report['payload_arguments'] if p.get('size', 0) == 0]
    if len(zero_args) != 11 or any(p.get('arg_type') != 'arg_bypointer' or p.get('offset') != 0
                                   or p.get('arg_index') != i
                                   for i, p in enumerate(zero_args)):
        raise ValueError('Unexpected zero-sized argument payload metadata')
    per = report['per_thread_payload_arguments']
    if per != [{'arg_type': 'packed_local_ids', 'offset': 0, 'size': 6}]:
        raise ValueError('Probe per-thread payload differs from the audited packed-local-ID field')


def audit_probe_payload(zebin, native, spirv_disassembly):
    """Audit this exact probe's opaque-arg IR and native cross-thread load liveness.

    This deliberately does not call build_report(): that report is pinned to a
    different PRE binary. Only its restricted native byte-liveness routine is
    reused, with this probe's own input bytes, native disassembly, and seeds.
    """
    r = inspect(zebin, 'bridge_probe')
    validate_payload_layout(r)

    embedded_spv = sections(zebin).get('.spv')
    if embedded_spv is None:
        raise ValueError('Payload audit requires embedded SPIR-V')
    spirv = audit_probe_spirv(spirv_disassembly)

    instructions, _ = parse_isa(native)
    loads = [ins for ins in instructions if ins['op'] == 'send.ugm'
             and 'load.ugm.' in ins['comment'] and 'bti[255]' in ins['comment']]
    if len(loads) != 3:
        raise ValueError('Payload audit requires exactly three recognized cross-thread load responses')
    native_liveness = []
    for ins in loads:
        if len(ins['args']) != 5 or not re.fullmatch(r'r[1-9][0-9]*', ins['args'][0]):
            raise ValueError('Unsupported cross-thread load response register')
        decoded = re.search(r'rd:(\d+);', ins['comment'])
        if not decoded or int(decoded.group(1)) != 1:
            raise ValueError('Unsupported cross-thread load response size')
        reg = int(ins['args'][0][1:])
        result = audit_native(native, ins['line'], reg, 64)
        if result['possible_reads'] or result['status'] != 'unread-before-overwrite-or-end':
            raise ValueError('Cross-thread payload has a possible native read')
        native_liveness.append({'line': ins['line'], 'register': reg,
                                'status': result['status'],
                                'overwrites': result['overwrites']})
    return {'status': 'restricted-static-no-read', 'zebin_sha256': r['zebin_sha256'],
            'code_sha256': r['code_sha256'], 'embedded_spirv_sha256':
            hashlib.sha256(embedded_spv).hexdigest(), 'spirv': spirv,
            'native_asm_sha256': hashlib.sha256(native.encode()).hexdigest(),
            'payload_layout_sha256': payload_layout_sha256(r),
            'native_assumptions': ['full constant thread execution mask', '64-byte GRFs',
                                   'decoded IGA send descriptions agree with native encoding'],
            'native_cross_thread_response_liveness': native_liveness}


def pack_probe(zebin, payload_audit, local_size=CM_LOCAL_SIZE):
    r = inspect(zebin, 'bridge_probe')
    env = r['execution_env']
    if not env.get('has_dpas') or env.get('has_sample') or env.get('simd_size') != 1:
        raise ValueError('Probe must have real DPAS, SIMD1 CM metadata, no sampler')
    if env.get('grf_count') != EXPECTED_GRF_COUNT:
        raise ValueError('Probe GRF count differs from the reviewed 128-GRF reader contract')
    if tuple(local_size) != CM_LOCAL_SIZE:
        raise ValueError('Probe CM local dimensions must be exactly 1,1,1')
    if env.get('slm_size', 0) or env.get('barrier_count', 0):
        raise ValueError('Unexpected shared memory/barrier requirements')
    btis = sorted(r['binding_table_indices'], key=lambda b: b['arg_index'])
    if [b['arg_index'] for b in btis] != list(range(11)):
        raise ValueError('Unexpected probe buffer arguments')
    if [b['bti_value'] for b in btis] != list(range(1, 12)):
        raise ValueError('Probe BTI values must be exactly 1..11 for this reader mapping')
    validate_payload_layout(r)
    if payload_audit.get('status') != 'restricted-static-no-read' \
            or payload_audit.get('zebin_sha256') != r['zebin_sha256'] \
            or payload_audit.get('code_sha256') != r['code_sha256'] \
            or payload_audit.get('payload_layout_sha256') != payload_layout_sha256(r):
        raise ValueError('Cross-thread zeros require a successful audit of this exact zebin')
    cross = 96
    per = r['per_thread_payload_arguments']
    if any(p['arg_type'] != 'packed_local_ids' for p in per):
        raise ValueError('Unreviewed per-thread payload')
    per_size = (max([p['offset']+p['size'] for p in per]+[0])+63)//64*64
    code = sections(zebin)['.text.bridge_probe']
    bti = [b['bti_value'] for b in btis]
    header = (b'CMK2'+struct.pack('<9I', len(code), env['grf_count'], 0, 0,
                                  *local_size, cross, per_size)
              +bytes(128)+struct.pack('<4I', 0, 0, 0, 11)
              +struct.pack('<24I', *(bti+[0]*13))
              +struct.pack('<24I', *(list(range(11))+[0]*13))+bytes(96))
    profile = {'schema_version': 1, 'status': 'experimental-offline-only',
               'code_sha256': r['code_sha256'], 'table_pc_base': 4, 'expected_push_size': 52,
               'surfaces': [{'arg_index': i, 'bti': bti[i], 'table_index': i,
                             'element': 0, 'push_byte_offset': 4+4*i} for i in range(11)]}
    cmk = bytearray(convert(header+code, profile))
    # The general adapter intentionally keeps auto-heap selection for PRE profiles.
    # This synthetic Vulkan harness uses set 0/binding 0, so opt in explicitly here.
    struct.pack_into('<II', cmk, 168, 0, 0)
    return bytes(cmk), r


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--toolchain', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    root, out = a.toolchain.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    compiler = root/'neo/usr/bin/ocloc-25.18.1'
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = f'{root}/igc/usr/local/lib:{root}/neo/usr/lib/x86_64-linux-gnu'
    env['XDG_CACHE_HOME'] = str(out/'cache')
    commands = []

    def run(command, log):
        commands.append(command)
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        with (out/log).open('w') as stream:
            subprocess.run(command, check=True, stdout=stream, stderr=subprocess.STDOUT,
                           env=env, timeout=180)

    (out/'probe.spvasm').write_text(shader_source())
    run(['spirv-as', '--target-env', 'spv1.1', str(out/'probe.spvasm'), '-o', str(out/'probe.spv')], 'assemble.log')
    run([str(compiler), 'compile', '-spirv_input', '-file', str(out/'probe.spv'),
         '-device', '0xe20b', '-out_dir', str(out), '-output', 'probe',
         '-options', "-vc-codegen -Xfinalizer '-noDPASMacro'"], 'compile.log')
    zebin = (out/'probe_bmg.bin').read_bytes()
    run([str(compiler), 'disasm', '-file', str(out/'probe_bmg.bin'),
         '-dump', str(out/'disasm'), '-device', 'bmg-g21'], 'disasm.log')
    native = (out/'disasm/.text.bridge_probe.asm').read_text()
    if 'dpas.' not in native:
        raise ValueError('Native DPAS instruction missing; never accept a constant-folded substitute')
    embedded = sections(zebin).get('.spv')
    if embedded is None or embedded != (out/'probe.spv').read_bytes():
        raise ValueError('Compiler zebin does not preserve the assembled probe SPIR-V')
    (out/'embedded-probe.spv').write_bytes(embedded)
    run(['spirv-dis', str(out/'embedded-probe.spv'), '-o', str(out/'embedded-probe.spvasm')],
        'spirv-dis.log')
    payload_audit = audit_probe_payload(zebin, native, (out/'embedded-probe.spvasm').read_text())
    cmk, summary = pack_probe(zebin, payload_audit)
    (out/'wg1_1_5.cmk').write_bytes(cmk)
    for name, z in [('placeholder', 5), ('canary', 17)]:
        (out/f'{name}.comp').write_text(placeholder_source(z))
        run(['glslangValidator', '-V', '--target-env', 'vulkan1.1', str(out/f'{name}.comp'),
             '-o', str(out/f'{name}.spv')], f'{name}.log')
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    (out/'payload-audit.json').write_text(json.dumps(payload_audit, indent=2)+'\n')
    (out/'probe-spec.json').write_text(json.dumps({
        'kind': 'synthetic-dpas-resource-map-probe-not-fsr', 'schema_version': 1,
        'target_vendor_id': '0x8086', 'target_device_id': '0xe20b', 'resource_heap_slots': SLOTS,
        'surfaces': 11, 'words_per_surface': 128, 'untouched_heap_slots': list(range(11, 16)),
        'expected_float_result': '16 + argument_index (16 FP16 one*one products)',
        'cm_local_size': [1, 1, 1], 'hardware_local_size': [32, 1, 1],
        'expected_right_mask': '0xffffffff', 'push_size': 52, 'table_pc_base': 4,
        'cmk_magic': 'CMK3', 'heap_set': 0, 'heap_binding': 0,
        'payload_audit': payload_audit['status'], 'gpu_validated': False,
        'runtime_approved': False,
         'runtime_block_reason': 'DIRECT descriptor layout gate and probe output require an authorized GPU experiment',
        'code_sha256': summary['code_sha256'],
        'compiler_sha256': hashlib.sha256(compiler.read_bytes()).hexdigest(),
    }, indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
