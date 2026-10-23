#!/usr/bin/env python3
"""Build an image2D/sampler CM probe offline; never dispatch GPU work."""
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
from image_probe_reference import contract

CM_LOCAL_SIZE = (1, 1, 1)
CMK_HAS_SAMPLER = 0x80000000
IMAGE_SLOT, OUTPUT_SLOT, SAMPLER_INDEX = 3, 7, 0
CONTRACT = contract()
COORDS = list(zip(CONTRACT['u'], CONTRACT['v']))
IMAGE_VALUES = CONTRACT['texels_row_major_rgba']


def bilinear_reference():
    """CPU reference for normalized linear filtering and clamp-to-edge."""
    rows = []
    for u, v in COORDS:
        x = min(1.0, max(0.0, u)) * 2.0 - 0.5
        y = min(1.0, max(0.0, v)) * 2.0 - 0.5
        x0, y0 = int(x // 1), int(y // 1)
        fx, fy = x - x0, y - y0
        samples = []
        for dy in (0, 1):
            for dx in (0, 1):
                ix, iy = min(1, max(0, x0+dx)), min(1, max(0, y0+dy))
                samples.append(IMAGE_VALUES[iy*2+ix])
        rows.append([
            (samples[0][c]*(1-fx)+samples[1][c]*fx)*(1-fy)
            + (samples[2][c]*(1-fx)+samples[3][c]*fx)*fy
            for c in range(4)
        ])
    return rows


def shader_source():
    lines = ['OpCapability Addresses', 'OpCapability Linkage', 'OpCapability Kernel',
             'OpCapability ImageBasic', 'OpCapability ImageReadWrite',
             'OpCapability SubgroupDispatch', 'OpCapability Vector16',
             'OpCapability Float16Buffer', 'OpCapability Int64', 'OpCapability Int16',
             'OpCapability Int8', 'OpCapability VectorComputeINTEL',
             'OpCapability VectorAnyINTEL', 'OpExtension "SPV_INTEL_vector_compute"',
             '%extinst = OpExtInstImport "OpenCL.std"',
             'OpMemoryModel Physical64 OpenCL',
             'OpEntryPoint Kernel %probe "bridge_image_probe"',
             'OpExecutionMode %probe SubgroupSize 1',
             'OpExecutionMode %probe SharedLocalMemorySizeINTEL 0',
             'OpExecutionMode %probe NamedBarrierCountINTEL 0']
    imp = {
        'image_convert': 'llvm.genx.address.convert.i32.p1opencl.image2d_ro_t',
        'buffer_convert': 'llvm.genx.address.convert.i32.p1intel.buffer_rw_t',
        'sampler_convert': 'llvm.genx.address.convert.i32.p2opencl.sampler_t',
        'sample': 'llvm.genx.3d.sample.v64f32.v16i1.' + '.'.join(['v16f32']*15),
        'store': 'llvm.genx.oword.st.v4f32',
    }
    lines.append('OpName %probe "bridge_image_probe"')
    lines += [f'OpName %{name} "{symbol}"' for name, symbol in imp.items()]
    lines += ['OpDecorate %probe LinkageAttributes "bridge_image_probe" Export',
              'OpDecorate %probe VectorComputeFunctionINTEL']
    lines += [f'OpDecorate %arg{i} FuncParamIOKindINTEL 0' for i in range(3)]
    for name, symbol in imp.items():
        lines += [f'OpDecorate %{name} LinkageAttributes "{symbol}" Import',
                  f'OpDecorate %{name} VectorComputeFunctionINTEL']
    lines += ['%void = OpTypeVoid', '%uint = OpTypeInt 32 0', '%ushort = OpTypeInt 16 0',
              '%float = OpTypeFloat 32', '%bool = OpTypeBool',
              '%image = OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly',
              '%buffer = OpTypeBufferSurfaceINTEL ReadWrite', '%sampler_t = OpTypeSampler',
              '%v16f = OpTypeVector %float 16', '%v16b = OpTypeVector %bool 16',
              '%v64f = OpTypeVector %float 64', '%v4f = OpTypeVector %float 4',
              '%ft_image_convert = OpTypeFunction %uint %image',
              '%ft_buffer_convert = OpTypeFunction %uint %buffer',
              '%ft_sampler_convert = OpTypeFunction %uint %sampler_t',
              '%ft_sample = OpTypeFunction %v64f %uint %v16b %uint %ushort %uint %uint '
               + ' '.join(['%v16f']*15),
              '%ft_store = OpTypeFunction %void %uint %uint %v4f',
              '%ft_probe = OpTypeFunction %void %image %buffer %sampler_t']
    # SPIR-V logical layout requires every constant before the first function.
    lines += ['%u0 = OpConstant %uint 0', '%u1 = OpConstant %uint 1',
              '%sample_lz_opcode = OpConstant %uint 24',
              '%channelmask = OpConstant %uint 15', '%s0 = OpConstant %ushort 0',
              '%true = OpConstantTrue %bool',
              '%mask = OpConstantComposite %v16b '+' '.join(['%true']*16)]
    lines += [f'%lane_x_{i} = OpConstant %float {u}'
              for i, (u, _) in enumerate(COORDS)]
    lines += [f'%lane_y_{i} = OpConstant %float {v}'
              for i, (_, v) in enumerate(COORDS)]
    lines += ['%coords_x = OpConstantComposite %v16f '+' '.join(
                  f'%lane_x_{i}' for i in range(16)),
              '%coords_y = OpConstantComposite %v16f '+' '.join(
                  f'%lane_y_{i}' for i in range(16)),
              '%zero = OpConstantNull %v16f']
    lines += [f'%offset{ch}_{q} = OpConstant %uint {ch*4+q}'
              for ch in range(4) for q in range(4)]
    lines += ['%image_convert = OpFunction %uint Pure %ft_image_convert',
              '%ic_arg = OpFunctionParameter %image', 'OpFunctionEnd',
              '%buffer_convert = OpFunction %uint Pure %ft_buffer_convert',
              '%bc_arg = OpFunctionParameter %buffer', 'OpFunctionEnd',
              '%sampler_convert = OpFunction %uint Pure %ft_sampler_convert',
              '%sc_arg = OpFunctionParameter %sampler_t', 'OpFunctionEnd',
              '%sample = OpFunction %v64f Const %ft_sample']
    lines += [f'%sp{i} = OpFunctionParameter {typ}' for i, typ in enumerate(
        ['%uint', '%v16b', '%uint', '%ushort', '%uint', '%uint']+['%v16f']*15)]
    lines += ['OpFunctionEnd', '%store = OpFunction %void DontInline %ft_store',
              '%st_bti = OpFunctionParameter %uint', '%st_idx = OpFunctionParameter %uint',
              '%st_data = OpFunctionParameter %v4f', 'OpFunctionEnd',
              '%probe = OpFunction %void DontInline %ft_probe',
              '%arg0 = OpFunctionParameter %image', '%arg1 = OpFunctionParameter %buffer',
              '%arg2 = OpFunctionParameter %sampler_t', '%entry = OpLabel',
              '%image_bti = OpFunctionCall %uint %image_convert %arg0',
              '%output_bti = OpFunctionCall %uint %buffer_convert %arg1',
              '%sampler_bti = OpFunctionCall %uint %sampler_convert %arg2']
    # Intrinsic ABI: opcode, execution mask, channel mask, aoffimmi, sampler,
    # surface, then U/V/R/Ai and trailing operation-specific vector operands.
    lines += ['%sampled = OpFunctionCall %v64f %sample %sample_lz_opcode %mask %channelmask %s0 '
              '%sampler_bti %image_bti %coords_x %coords_y %zero %zero %zero %zero '
              '%zero %zero %zero %zero %zero %zero %zero %zero %zero']
    # IGC's vISA 3D_SAMPLE contract returns channel-major data: each enabled
    # channel's SIMD16 lanes are contiguous (next GRF per channel), no AoS swizzle.
    for ch in range(4):
        for q in range(4):
            start = ch*16+q*4
            lines += [f'%part{ch}_{q} = OpVectorShuffle %v4f %sampled %sampled '
                      + ' '.join(str(start+j) for j in range(4)),
                      f'%write{ch}_{q} = OpFunctionCall %void %store %output_bti '
                      f'%offset{ch}_{q} %part{ch}_{q}']
    return '\n'.join(lines+['OpReturn', 'OpFunctionEnd', ''])


def audit_probe_spirv(text):
    required = ['llvm.genx.address.convert.i32.p1opencl.image2d_ro_t',
                'llvm.genx.address.convert.i32.p1intel.buffer_rw_t',
                'llvm.genx.address.convert.i32.p2opencl.sampler_t',
                'llvm.genx.3d.sample.v64f32.', 'llvm.genx.oword.st.v4f32']
    for symbol in required:
        if text.count(f'LinkageAttributes "{symbol}') != 1:
            raise ValueError(f'Expected exact real compiler import: {symbol}')
    import_ids = {symbol: ident for ident, symbol in re.findall(
        r'^\s*OpDecorate\s+(%[\w.]+)\s+LinkageAttributes "([^"]+)" Import', text, re.M)}
    entry_ids = re.findall(r'^\s*OpEntryPoint Kernel (%[\w.]+) "bridge_image_probe"',
                           text, re.M)
    if len(entry_ids) != 1:
        raise ValueError('Unexpected probe entry point')
    entry_id = re.escape(entry_ids[0])
    functions = re.findall(r'^\s*'+entry_id+r' = OpFunction\b(.*?)^\s*OpFunctionEnd',
                           text, re.M | re.S)
    if len(functions) != 1:
        raise ValueError('Missing/ambiguous exact bridge_image_probe function')
    body = functions[0]
    sample_symbol = next((symbol for symbol in import_ids if symbol.startswith(required[3])), None)
    if sample_symbol is None:
        raise ValueError('Missing exact GenX sample import')
    sample_calls = re.findall(r'OpFunctionCall\s+%[\w.]+\s+'
                              +re.escape(import_ids[sample_symbol])+r'\b', body)
    store_calls = re.findall(r'OpFunctionCall\s+%[\w.]+\s+'
                             +re.escape(import_ids[required[4]])+r'\b', body)
    if len(sample_calls) != 1 or len(store_calls) != 16:
        raise ValueError('Probe requires exactly one real sample and sixteen buffer stores')
    params = re.findall(r'^\s*(%[\w.]+) = OpFunctionParameter (%[\w.]+)', body, re.M)
    if len(params) != 3:
        raise ValueError('Entry must have exactly image, buffer, sampler parameters')
    body_without_params = '\n'.join(line for line in body.splitlines()
                                     if 'OpFunctionParameter' not in line)
    expected_converters = ('llvm.genx.address.convert.i32.p1opencl.image2d_ro_t',
                           'llvm.genx.address.convert.i32.p1intel.buffer_rw_t',
                           'llvm.genx.address.convert.i32.p2opencl.sampler_t')
    for (arg, _), converter in zip(params, expected_converters):
        converter_id = re.escape(import_ids[converter])
        uses = re.findall(r'OpFunctionCall\s+%[\w.]+\s+'+converter_id+r'\s+'
                          +re.escape(arg)+r'\b', body_without_params)
        total_uses = re.findall(r'(?<![\w.])'+re.escape(arg)+r'(?![\w.])', body_without_params)
        if len(uses) != 1 or len(total_uses) != 1:
            raise ValueError('Entry arguments must each be converted exactly once in order')
    return {'status': 'restricted-image-sample-store', 'entry_arguments':
            ['image2d_ro', 'buffer_rw', 'sampler'], 'sample_calls': 1,
            'stores': len(store_calls), 'btis_not_assumed': True,
            'channelmask': 15, 'sample_opcode': 'sample_lz'}


def validate_payload(r):
    args = [x for x in r['binding_table_indices']]
    if [x.get('arg_index') for x in args] != [0, 1]:
        raise ValueError('Expected only compiler-derived image/output surface BTIs')
    btis = [x.get('bti_value') for x in args]
    if any(type(x) is not int or not 0 < x < 255 for x in btis) or len(set(btis)) != 2:
        raise ValueError('Compiler-derived image/output BTIs must be distinct valid surface indices')
    env = r['execution_env']
    if not env.get('has_sample') or env.get('has_dpas'):
        raise ValueError('Expected sampled-image kernel without required DPAS')
    if env.get('simd_size') != 1 or env.get('slm_size', 0) or env.get('barrier_count', 0):
        raise ValueError('Image probe requires SIMD1 CM metadata with no SLM or barriers')
    fields = r['payload_arguments']
    sized = [x for x in fields if x.get('size', 0)]
    expected_sized = [
        {'arg_type': 'arg_bypointer', 'offset': 8, 'size': 8, 'arg_index': 1,
         'addrmode': 'stateful', 'addrspace': 'global', 'access_type': 'readwrite'},
        {'arg_type': 'private_base_stateless', 'offset': 0, 'size': 8},
    ]
    if sized != expected_sized:
        raise ValueError('Compiler cross-thread payload differs from reviewed image/output shape')
    zero_sized = [x for x in fields if not x.get('size', 0)]
    by_index = {x.get('arg_index'): x for x in zero_sized}
    if len(zero_sized) != 3 or set(by_index) != {0, 1, 2}:
        raise ValueError('Expected zero-sized descriptors for image, output and sampler arguments')
    if (by_index[0].get('addrspace'), by_index[0].get('image_type'), by_index[0].get('access_type')) != (
            'image', 'image_2d', 'readonly'):
        raise ValueError('Image argument metadata is not read-only image2d')
    if (by_index[1].get('addrspace'), by_index[1].get('access_type')) != ('global', 'readwrite'):
        raise ValueError('Output argument metadata is not writable global buffer')
    if (by_index[2].get('addrspace'), by_index[2].get('sampler_index')) != ('sampler', SAMPLER_INDEX):
        raise ValueError('Sampler argument metadata does not select sampler index 0')
    if r['per_thread_payload_arguments'] != [
            {'arg_type': 'packed_local_ids', 'offset': 0, 'size': 6}]:
        raise ValueError('Unexpected per-thread payload metadata')
    return args


def payload_layout_sha256(r):
    payload = [r['payload_arguments'], r['per_thread_payload_arguments']]
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def pack_image_probe(zebin, audit):
    r = inspect(zebin, 'bridge_image_probe')
    args = validate_payload(r)
    if (audit.get('status') != 'restricted-static-no-read'
            or audit.get('zebin_sha256') != r['zebin_sha256']
            or audit.get('code_sha256') != r['code_sha256']
            or audit.get('payload_layout_sha256') != payload_layout_sha256(r)
            or not audit.get('native_asm_sha256') or not audit.get('loads')):
        raise ValueError('Payload zeroing requires an audit of this exact image-probe zebin')
    if tuple(CM_LOCAL_SIZE) != (1, 1, 1):
        raise ValueError('Unexpected image probe local dimensions')
    if r['execution_env'].get('grf_count') != 128:
        raise ValueError('Image probe requires the reviewed 128-GRF local reader contract')
    surfaces = [{'arg_index': 0, 'bti': args[0]['bti_value'], 'table_index': 0,
                 'element': 0, 'push_byte_offset': 4},
                {'arg_index': 1, 'bti': args[1]['bti_value'], 'table_index': 1,
                 'element': 0, 'push_byte_offset': 8}]
    code = sections(zebin)['.text.bridge_image_probe']
    cross_thread_size = max(p['offset']+p['size'] for p in r['payload_arguments']
                            if p.get('size'))
    per_thread_size = 64
    # CMK2/3 barriers bit 31 tells the reader to prepare sampler state. This is
    # independent of the native instruction and must not be omitted for images.
    header = (b'CMK2'+struct.pack('<9I', len(code), 128, 0, CMK_HAS_SAMPLER, *CM_LOCAL_SIZE,
                                  cross_thread_size, per_thread_size)+bytes(128)+struct.pack('<4I', 0, 0, 0, 2)
              +struct.pack('<24I', args[0]['bti_value'], args[1]['bti_value'], *([0]*22))
              +struct.pack('<24I', 0, 0, *([0]*22))+bytes(96))
    profile = {'schema_version': 1, 'status': 'experimental-offline-only',
               'code_sha256': r['code_sha256'], 'table_pc_base': 4,
               'expected_push_size': 52, 'surfaces': surfaces}
    cmk = bytearray(convert(header+code, profile))
    struct.pack_into('<II', cmk, 168, 0, 0)
    return bytes(cmk), r


def audit_image_payload(zebin, native, spvasm):
    r = inspect(zebin, 'bridge_image_probe')
    validate_payload(r)
    audit_probe_spirv(spvasm)
    ins, _ = parse_isa(native)
    if not any(x['op'] == 'send.smpl' for x in ins):
        raise ValueError('Compiled native kernel has no real sampler send')
    if not any(x['op'] == 'send.ugm' and 'store.ugm.' in x['comment'] for x in ins):
        raise ValueError('Compiled native kernel has no output buffer store')
    loads = [x for x in ins if x['op'] == 'send.ugm' and 'load.ugm.' in x['comment']
             and 'bti[255]' in x['comment']]
    evidence = []
    for item in loads:
        if len(item['args']) != 5 or not re.fullmatch(r'r[1-9][0-9]*', item['args'][0]):
            raise ValueError('Unrecognized cross-thread payload load shape')
        decoded = re.search(r'rd:(\d+);', item['comment'])
        if not decoded:
            raise ValueError('Missing decoded payload response size')
        result = audit_native(native, item['line'], int(item['args'][0][1:]),
                              int(decoded.group(1))*64)
        if result['possible_reads'] or result['status'] != 'unread-before-overwrite-or-end':
            raise ValueError('Probe cross-thread zeros are not safe under restricted audit')
        evidence.append({'line': item['line'], 'register': item['args'][0],
                         'response_grfs': int(decoded.group(1)), 'audit': result})
    if not evidence:
        raise ValueError('No recognized payload loads; refusing to zero cross-thread bytes')
    return {'status': 'restricted-static-no-read', 'zebin_sha256': r['zebin_sha256'],
            'code_sha256': r['code_sha256'], 'payload_layout_sha256': payload_layout_sha256(r),
            'cross_thread_payload_size': max(p['offset']+p['size'] for p in r['payload_arguments']
                                             if p.get('size')),
            'native_asm_sha256': hashlib.sha256(
                native.encode()).hexdigest(), 'ir_sha256': hashlib.sha256(spvasm.encode()).hexdigest(),
            'assumptions': ['full constant execution mask', '64-byte GRFs',
                            'IGA-decoded sends match native encoding'], 'loads': evidence}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    a = parser.parse_args()
    root, out = a.toolchain.resolve(), a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    compiler = root/'neo/usr/bin/ocloc-25.18.1'
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = f'{root}/igc/usr/local/lib:{root}/neo/usr/lib/x86_64-linux-gnu'
    env['XDG_CACHE_HOME'] = str(out/'cache')
    version_result = subprocess.run([str(compiler), '--version'], text=True,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env=os.environ.copy(), timeout=30)
    (out/'toolchain.json').write_text(json.dumps({
        'ocloc_version_output': version_result.stdout.strip(),
        'ocloc_version_exit_code': version_result.returncode,
        'compiler_path': str(compiler),
        'compiler_sha256': hashlib.sha256(compiler.read_bytes()).hexdigest(),
        'target_device': '0xe20b',
    }, indent=2)+'\n')
    commands = []

    def run(cmd, log):
        commands.append(cmd)
        (out/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        with (out/log).open('w') as stream:
            subprocess.run(cmd, check=True, stdout=stream, stderr=subprocess.STDOUT,
                           env=env, timeout=180)

    source = shader_source()
    (out/'probe.spvasm').write_text(source)
    run(['spirv-as', '--target-env', 'spv1.1', str(out/'probe.spvasm'), '-o',
         str(out/'probe.spv')], 'assemble.log')
    run([str(compiler), 'compile', '-spirv_input', '-file', str(out/'probe.spv'),
         '-device', '0xe20b', '-out_dir', str(out), '-output', 'probe',
         '-options', '-vc-codegen'], 'compile.log')
    zebin = (out/'probe_bmg.bin').read_bytes()
    run([str(compiler), 'disasm', '-file', str(out/'probe_bmg.bin'), '-dump',
         str(out/'disasm'), '-device', 'bmg-g21'], 'disasm.log')
    native = (out/'disasm/.text.bridge_image_probe.asm').read_text()
    embedded = sections(zebin).get('.spv')
    if embedded != (out/'probe.spv').read_bytes():
        raise ValueError('Zebin does not preserve exact assembled SPIR-V')
    (out/'embedded.spv').write_bytes(embedded)
    run(['spirv-dis', str(out/'embedded.spv'), '-o', str(out/'embedded-probe.spvasm')], 'spirv-dis.log')
    ir = (out/'embedded-probe.spvasm').read_text()
    payload = audit_image_payload(zebin, native, ir)
    (out/'payload-audit.json').write_text(json.dumps(payload, indent=2)+'\n')
    cmk, summary = pack_image_probe(zebin, payload)
    (out/'wg2_1_5.cmk').write_bytes(cmk)
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    for name, workgroup in [('placeholder', (2, 1, 5)), ('canary', (1, 1, 17))]:
        (out/f'{name}.comp').write_text(
            '#version 450\n'
            f'layout(local_size_x={workgroup[0]}, local_size_y={workgroup[1]}, '
            f'local_size_z={workgroup[2]}) in;\n'
            'layout(set=0,binding=0,std430) buffer Heap { uint words[]; } heap[16];\n'
            'void main(){ if(gl_LocalInvocationIndex==0u) heap[0].words[0]=0x584d5843u; }\n')
        run(['glslangValidator', '-V', '--target-env', 'vulkan1.1', str(out/f'{name}.comp'),
             '-o', str(out/f'{name}.spv')], f'{name}.log')
    spec = dict(CONTRACT)
    spec.update({'entry_point': 'bridge_image_probe',
            'sampler_index': SAMPLER_INDEX,
            'cm_local_size': list(CM_LOCAL_SIZE),
            'hardware_local_size': [32, 1, 1],
            'placeholder_workgroup': [2, 1, 5],
            'cmk_artifact_selector': 'wg2_1_5.cmk',
            'output_floats': 64, 'compiler_derived_btis_by_arg': [
                x['bti_value'] for x in summary['binding_table_indices']],
            'payload_audit': payload, 'toolchain': json.loads((out/'toolchain.json').read_text()),
            'gpu_validated': False,
            'runtime_approved': False, 'artifacts': {}})
    for p in sorted(x for x in out.rglob('*') if x.is_file() and x.name != 'probe-spec.json'):
        spec['artifacts'][str(p.relative_to(out))] = {'size': p.stat().st_size,
                                                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    (out/'probe-spec.json').write_text(json.dumps(spec, indent=2)+'\n')
    print(out)


if __name__ == '__main__':
    main()
