#!/usr/bin/env python3
"""Reproduce static PRE table evidence for one pinned DLL and model its root layout.

Does not execute code. Root-signature semantics come from manual disassembly,
not automated decompilation. The push layout models the recorded vkd3d reference,
not the user's installed Proton. This is not a general D3D12 layout parser.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

DLL_SHA256 = '3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53'


def pre_layout(slots):
    if len(slots) != 11:
        raise ValueError('PRE requires eleven resource slots')
    tables = []
    for i, slot in enumerate(slots):
        tables.append({'root_index': i+1, 'register': f'u{i}' if i < 2 else f't{i-2}',
                       'heap': 'resource', 'relative_heap_slot': slot,
                       'push_byte_offset': 4*(i+1)})
    tables.append({'root_index': 12, 'register': 's0', 'heap': 'sampler',
                   'relative_heap_slot': 0, 'push_byte_offset': 48})
    size = 4+4*len(tables)
    auto_base = size-4*11
    return {'assumptions': ['One root constant DWORD before twelve descriptor tables.',
                            'Reference vkd3d classic descriptor-table push layout.',
                            'No raw-VA root descriptors; actual runtime not inspected.'],
            'root_constant': {'root_index': 0, 'register': 'b0', 'count_dwords': 1},
            'tables': tables, 'push_range_size': size,
            'expected_surface_push_offsets': [t['push_byte_offset'] for t in tables[:11]],
            'upstream_auto_base': auto_base,
            'upstream_auto_push_offsets': [auto_base+4*i for i in range(11)],
            'upstream_auto_selected_roots': [t['root_index'] for t in tables
                                              if t['push_byte_offset'] >= auto_base]}


def reconstruct(data):
    if hashlib.sha256(data).hexdigest() != DLL_SHA256:
        raise ValueError('Unreviewed DLL hash: addresses/layout may have changed')
    pe, = struct.unpack_from('<I', data, 0x3c)
    opt = pe+24
    base, = struct.unpack_from('<Q', data, opt+24)
    count, = struct.unpack_from('<H', data, pe+6)
    optsize, = struct.unpack_from('<H', data, pe+20)
    sections = []
    for i in range(count):
        vsize, va, rawsize, raw = struct.unpack_from('<IIII', data, opt+optsize+40*i+8)
        sections.append((va, rawsize, raw))

    def at(rva, size):
        for va, rawsize, raw in sections:
            if va <= rva and rva+size <= va+rawsize:
                return data[raw+rva-va:raw+rva-va+size]
        raise ValueError(f'Unmapped data RVA {rva:#x}')

    def cstring(va):
        return at(va-base, 100).split(b'\0', 1)[0].decode('ascii')

    slots = struct.unpack('<11I', at(0x68988, 44))
    sampler = struct.unpack('<4I', at(0x72a20, 16))
    variants = []
    for i in range(18):
        rva = 0x56160+0x4f0*i
        nameptr, = struct.unpack('<Q', at(rva, 8))
        offset0, length0 = struct.unpack('<QI', at(rva+0xd8+8, 12))
        offset1, length1 = struct.unpack('<QI', at(0x613b0+0xf0*i, 12))
        width_factor, = struct.unpack('<I', at(rva+0x24, 4))
        variants.append({'variant': cstring(nameptr), 'index': i+1,
                         'arg0_width_bound_factor': width_factor,
                         'pack_40101': {'offset': offset0, 'submitted_size': length0},
                         'pack_40102': {'offset': offset1, 'submitted_size': length1}})
    return {'dll_sha256': DLL_SHA256, 'manual_evidence': {
                'pre_init': '0x18002bb60', 'pso_call': '0x18002cb00',
                'root_signature_construction': '0x18002c13f..0x18002c4bd',
                'normal_dispatch_tables': '0x180017400..0x180017543',
                'compile_options_pointer': None, 'internal_options_pointer': None},
            'layout': pre_layout(slots),
            'sampler_template': {'filter': sampler[0], 'address_u': sampler[1],
                                 'address_v': sampler[2], 'address_w': sampler[3]},
            'pre_variant_payloads': variants}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('dll', type=Path)
    a = p.parse_args()
    print(json.dumps(reconstruct(a.dll.read_bytes()), indent=2)+'\n', end='')


if __name__ == '__main__':
    main()
