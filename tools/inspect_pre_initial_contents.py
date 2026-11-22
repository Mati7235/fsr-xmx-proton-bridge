#!/usr/bin/env python3
"""Pin the CPU-only PRE native_1080 initial-contents spec without invented data.

Static-only: never executes GPU, DLL, or game prefixes. Image formats,
dimensions, backing allocations and initial bytes are NOT derivable from the
DLL/IR views and are marked TRACE_FASE1_REQUIRED. This module pins every
integer that *is* statically established and refuses to fill the rest.
"""
import argparse
import hashlib
import json
from pathlib import Path

EXPECTED_IR_SHA256 = '7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e'

TRACE_REQUIRED = 'TRACE_FASE1_REQUIRED'

# Static view facts from docs/xmx412-dispatch.md (R8_UINT = 0x3e).
R8_UINT_ENUM = 0x3E
ARG9_VISIBLE_BYTES = 0x840  # 2112
ARG10_VISIBLE_BYTES = 0x80  # 128
ARG0_MIN_NATIVE1080 = 8294400  # factor 1: 1*1*0x7e9000; SPIR-V :15977-15993
ARG0_MIN_FACTOR_EXPR = 'factor*factor*0x7e9000'
GRID_GUARDS = {'x_at_least': 120, 'y_at_least': 540}


def _need(text, fragment, label):
    if fragment not in text:
        raise ValueError(f'Pinned PRE anchor changed or missing: {label}')
    return True


def extract_static_plan(text):
    """Extract only statically pinned header/flag/plane facts from IR text."""
    _need(text, '%587 = OpTypeBufferSurfaceINTEL ReadWrite', 'buffer surface type')
    _need(text, 'OpTypeImage %void 2D 0 0 0 0 Unknown ReadWrite', 'image RW Unknown')
    _need(text, 'OpTypeImage %void 2D 0 0 0 0 Unknown ReadOnly', 'image RO Unknown')
    _need(text, '%uint_120', 'grid guard 120')
    _need(text, '%uint_540', 'grid guard 540')
    # 128 B header load path (SPIR-V :5213/:5220, both alignment variants).
    _need(text, '%llvm_genx_oword_ld_unaligned_v32i32', 'header oword load unaligned')
    _need(text, '%llvm_genx_oword_ld_v32i32', 'header oword load aligned')
    # Observed flag-bit constants on the header word at byte 100 (:5225,:5574,:5593).
    for const, bit in (('%uint_1024', '0x400'), ('%uint_4096', '0x1000'),
                       ('%uint_8192', '0x2000'), ('%uint_512', '0x200')):
        _need(text, const, f'header flag bit {bit}')
    _need(text, '%ushort_100', 'header flags byte-100 selector')
    _need(text, '%ushort_104', 'header base byte-104 selector')
    # 16 B float4 read from arg0 at base (+0/+16) (:5627/:5634).
    _need(text, '%llvm_genx_oword_ld_unaligned_v4f32', 'arg0 float4 unaligned')
    _need(text, '%llvm_genx_oword_ld_v4f32', 'arg0 float4 aligned')
    # Final 128 B per-group store plane (:15977-15993).
    for const, label in (('%uint_960', 'plane stride 960'), ('%uint_8', 'plane stride 8')):
        _need(text, const, label)
    _need(text, '%llvm_genx_oword_st_v128i8', 'final 128 B store')
    # Typed store destination is arg 1 (channel mask 7, surface %9780).
    _need(text, '%uchar_7 %9780', 'typed-store mask/surface')
    return {
        'header_bytes': 128,
        'header_float_dword_offsets': [8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 56, 60],
        'header_uint_dword_offsets': [64, 68, 72, 76, 80],
        'header_extra_float_offset': [84],
        'header_flags_byte': 100,
        'header_base_byte': 104,
        'flag_bits_observed': {
            '0x400': 'guard: when set, early exit without work (:5225-5230)',
            '0x1000': 'observed branch selector, unnamed (:5574-5583)',
            '0x2000': 'selects base vs base+16 for the arg0 float4 read (:5593-5602)',
            '0x200': 'gates the final 128 B store; when set, early exit (:15970-15973)',
        },
        'flag_field_note': '(flags & 0x18) >> 3 is derived at :5325-5328; unnamed, no semantics assigned',
        'arg0_float4_window': '16 bytes at byte104_base + {0, 16} (flag 0x2000)',
        'arg0_write_plane': '(wg_y * 960 + wg_x * 8) OWORD * 16 B; exclusive end 518400 OWORD = 8294400 B',
        'grid_guards': dict(GRID_GUARDS),
        'store_channel_mask': 7,
    }


def resource_table():
    """Per-resource required-contents table. Unknowns stay TRACE_REQUIRED."""
    t = TRACE_REQUIRED
    return [
        {'arg': 0, 'cm_type': 'BufferSurfaceINTEL ReadWrite', 'd3d_view': 'UAV BUFFER R8_UINT, FirstElement 0, NumElements = resource Width',
         'root': 1, 'bti': 8, 'heap_slot': 7, 'push_offset': 4, 'context': 'GetDesc-guarded BUFFER resource',
         'visible_bytes': 'Width (runtime); minimum 8294400 for native_1080 (factor 1)',
         'backing_bytes': t, 'initial_bytes': t,
         'valid_filler_rule': 'any byte 0x00..0xFF is a valid R8_UINT value; actual scene/scratch bytes come from trace',
         'provenance': 'view shape STATIC; Width and bytes TRACE_FASE1_REQUIRED',
         'constraint': 'float4 window [base, base+32) must lie inside Width and not destructively alias the write plane; trace must locate both'},
        {'arg': 1, 'cm_type': 'Image 2D ReadWrite; format Unknown', 'd3d_view': 'copied image descriptor (CopyDescriptorsSimple at 0x18001727e)',
         'root': 2, 'bti': 9, 'heap_slot': 8, 'push_offset': 8, 'context': 'host image resource',
         'visible_bytes': t, 'backing_bytes': t, 'initial_bytes': t,
         'valid_filler_rule': t + ': no filler is definable before the trace fixes DXGI/Vulkan format, dims, mip/layer, sample count',
         'provenance': 'binding STATIC; format/dims/content TRACE_FASE1_REQUIRED',
         'constraint': 'typed quad store destination (mask 7 = .xyz); descriptor must be writable per signature'},
        *({'arg': i, 'cm_type': 'Image 2D ReadOnly; format Unknown',
           'd3d_view': f'copied image descriptor (helper 0x180002df0, dest slot {i - 2})',
           'root': i + 1, 'bti': i - 1, 'heap_slot': i - 2, 'push_offset': 4 + 4 * (i + 1),
           'context': 'host image resource; slot<-name mapping is runtime',
           'visible_bytes': t, 'backing_bytes': t, 'initial_bytes': t,
           'valid_filler_rule': t + ': filler must be in-range for the traced format once known; no format invented here',
           'provenance': 'binding STATIC; format/dims/content and slot<-stock-name TRACE_FASE1_REQUIRED',
           'constraint': 'stock-name pool fixed (10 names); exact slot assignment + depth/exposure substitution from trace/flags'}
          for i in range(2, 9)),
        {'arg': 9, 'cm_type': 'BufferSurfaceINTEL ReadWrite (D3D view is SRV)', 'd3d_view': 'SRV BUFFER R8_UINT, FirstElement 0, NumElements 0x840',
         'root': 10, 'bti': 10, 'heap_slot': 9, 'push_offset': 40, 'context': 'resource at ctx+0xa80',
         'visible_bytes': 2112, 'backing_bytes': t, 'initial_bytes': t,
         'valid_filler_rule': 'any byte 0x00..0xFF is a valid R8_UINT value; actual bytes come from trace',
         'provenance': 'view extent STATIC (2112 B); backing allocation and bytes TRACE_FASE1_REQUIRED',
         'constraint': 'SRV range limits visibility, not allocation size'},
        {'arg': 10, 'cm_type': 'BufferSurfaceINTEL ReadWrite (D3D view is SRV)', 'd3d_view': 'SRV BUFFER R8_UINT, FirstElement 0, NumElements 0x80',
         'root': 11, 'bti': 11, 'heap_slot': 10, 'push_offset': 44, 'context': 'resource at ctx+0xa98',
         'visible_bytes': 128, 'backing_bytes': t, 'initial_bytes': t,
         'valid_filler_rule': 'header bytes come from trace only; no invented header: flags and base preserved verbatim',
         'provenance': 'view extent STATIC (128 B header fully visible); header contents TRACE_FASE1_REQUIRED',
         'constraint': 'flags byte100 (0x400 guard, 0x2000 base select, 0x200 store gate) + base byte104; base+32 inside arg0 Width'},
        {'arg': 11, 'cm_type': 'Sampler', 'd3d_view': 'MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, comparison ALWAYS, MinLOD 0, MaxLOD FLT_MAX',
         'root': 12, 'bti': 'sampler index 0', 'heap_slot': 'sampler heap 0', 'push_offset': 48, 'context': 'separate sampler heap',
         'visible_bytes': 'n/a', 'backing_bytes': 'n/a', 'initial_bytes': 'n/a (state, not bytes)',
         'valid_filler_rule': 'sampler state pinned statically; ANV fallback is partial, not equivalent',
         'provenance': 'STATIC descriptor; sampling behaviour still needs traced image formats/coords',
         'constraint': 'do not route the sampler index into the resource heap'},
    ]


def oracle_policy():
    """Ordered oracle design. Rank 1 > Rank 2 > Rank 3. No invented epsilons."""
    return {
        'order': [
            {'rank': 1, 'name': 'reference_capture_working',
             'what': 'pre/post capture of the same PRE native_1080 input in an implementation that already works',
             'why_first': 'only a working reference defines correct output; a capture of the still-failing bridge is evidence of inputs, never an oracle'},
            {'rank': 2, 'name': 'cpu_validated_against_reference',
             'what': 'CPU reimplementation validated byte/bit against Rank 1 on at least one pinned input',
             'why_second': 'translating isolated shader ops without that validation is not an oracle'},
            {'rank': 3, 'name': 'l0_ocl_same_zebin_bindings_contrast',
             'what': 'same zebin via Level Zero / OpenCL with identical inputs, byte-compared',
             'why_last': 'same kernel and possibly same NEO compiler core: contrasts bindings/backend only, never proves FSR math (docs/xmx412-dispatch.md)'},
        ],
        'tolerances': {
            'R8_UINT_buffers': {'value': 0, 'justification': 'DXGI_FORMAT_R8_UINT is an 8-bit unsigned integer; typed BUFFER views and oword accesses are bit-exact, no rounding or filtering exists in this path'},
            'images_Unknown_format': TRACE_REQUIRED + ': fixed only after the trace pins DXGI/Vulkan format; then integer formats -> 0, UNORM/SNORM/SRGB -> format quantization step from the format spec, FLOAT -> IEEE-754 rounding of the traced op sequence; no epsilon is pre-picked here',
        },
        'nan_policy': 'FAIL on any NaN in a compared output region (and on reference-finite vs test-NaN mismatch): IEEE-754 NaN != everything including itself; finite scene inputs must not produce NaN',
        'inf_policy': 'FAIL unless the Rank-1 reference provably holds Inf at the same element',
        'capture_checklist': [
            'same DLL / CM input / zebin hashes, w/h = 1920/1080, native_1080, MLSR constants',
            'per-resource D3D12_RESOURCE_DESC + heap properties + allocation size/offset',
            'every CreateSRV/UAV + CopyDescriptors*: resource, view desc, format, mip/layer/range, final heap slot',
            'GetDesc/identity of heap slots 0..10 just before dispatch; full 128 B header of arg10 + arg0 bytes at [base, base+32)',
            'root-table GPU handles, heap bases/increment, sampler desc, Dispatch grid, resource states',
            'pre AND post dumps with canaries; executable/version/hashes recorded; original capture preserved',
        ],
    }


# Stock names observed as UTF-16LE pairs in the pinned DLL (assignment is runtime).
STOCK_NAMES = ['MLSR_Optimized_Constants', 'ScratchBuffer', 'rw_reprojected_color',
               'r_history_color', 'r_velocity', 'r_input_color', 'r_recurrent_0',
               'r_depth', 'r_input_exposure', 'r_auto_exposure_texture']

SUBSTITUTION_RULES = ('No r_depth with flags bit0 set -> early return 0. '
                      'With flags&0x18==0, r_input_exposure is required when bit2 is clear, '
                      'r_auto_exposure_texture when bit2 is set. '
                      'depth/exposure/auto-exposure substitute default sources. '
                      'Exact slot<-name order is runtime (caller tables +0x8efc) and needs a values trace.')


def validate_trace_candidate(trace):
    """Check a Fase-1 trace dict for completeness. Returns missing-field list.

    Rejects invented scene-role assignments: t0..t6 must never carry a
    'scene_role' key in this spec stage.
    """
    missing = []
    for row in resource_table():
        arg = row['arg']
        if arg in (1, 2, 3, 4, 5, 6, 7, 8):
            for key in ('dxgi_format', 'width', 'height', 'view_desc', 'bytes_sha256'):
                if key not in trace.get(f'arg{arg}', {}):
                    missing.append(f'arg{arg}.{key}')
            if 'scene_role' in trace.get(f'arg{arg}', {}):
                raise ValueError(f'arg{arg}: scene_role is invented semantics; not allowed')
        elif arg == 0:
            for key in ('width_bytes', 'base_u32', 'flags_u32', 'bytes_sha256'):
                if key not in trace.get('arg0', {}):
                    missing.append(f'arg0.{key}')
        elif arg == 10:
            for key in ('header_hex128', 'flags_u32', 'base_u32'):
                if key not in trace.get('arg10', {}):
                    missing.append(f'arg10.{key}')
        elif arg == 9:
            if 'bytes_sha256' not in trace.get('arg9', {}):
                missing.append('arg9.bytes_sha256')
    if 'dispatch_grid' not in trace:
        missing.append('dispatch_grid')
    if 'local_size' not in trace:
        missing.append('local_size')
    return missing


def inspect(data):
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_IR_SHA256:
        raise ValueError(f'Unreviewed SPIR-V disassembly SHA-256: {digest}')
    plan = extract_static_plan(data.decode('utf-8'))
    return {'status': 'static-spec-only', 'runtime_approved': False,
            'spirv_disassembly_sha256': digest, 'static_plan': plan,
            'resources': resource_table(), 'oracle': oracle_policy(),
            'stock_names': STOCK_NAMES, 'substitution_rules': SUBSTITUTION_RULES}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('spvasm', type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.spvasm.read_bytes()), indent=2))


if __name__ == '__main__':
    main()
