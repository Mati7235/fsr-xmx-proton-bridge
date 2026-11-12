"""Pinned static anchors for the XMX 4.1.2 PRE dispatch equivalent.

CPU-only. Never loads or executes the DLL, no GPU/Wine, no prefixes.
Mirrors the style of tests/test_pre_resources.py: hash pins + string
anchors + address anchors, fail-closed on any mismatch.
"""
import hashlib
import struct
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DLL = ROOT / 'artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll'
TOOLCHAIN_INCLUDE = ROOT / ('artifacts/extracted/llvm-mingw-20261020-ucrt/'
                            'llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/'
                            'generic-w64-mingw32/include')
COMPILER = TOOLCHAIN_INCLUDE.parent.parent / 'bin/x86_64-w64-mingw32-clang++'

DLL_SHA256 = 'fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732'
DLL_SIZE = 45558272
IMAGE_BASE = 0x180000000

# Exact ASCII anchors, each must occur exactly once.
EXPECTED_ASCII = {
    '[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; '
    'ZB physical heap slots retained.': (1, 0x30f660, 0x310a60),
    '[FSR4 XMX] Failed to load PRE CM-SPIRV; XMX fail-stop will trigger.': (1, 0x30f400, 0x310800),
    '[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.': (1, 0x3101a0, 0x3115a0),
    '[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.': (1, 0x3102f0, 0x3116f0),
    '[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.': (1, 0x310340, 0x311740),
    '[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.': (1, 0x310390, 0x311790),
    '[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.': (1, 0x310440, 0x311840),
    'PRE runtime geometry is unavailable.': (1, 0x310490, 0x311890),
    '[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.': (1, 0x30f280, 0x310680),
}

# Wide (UTF-16LE) stock table: same 10 names as the old DLL.
# Value is (wide_count, first_file_offset). ScratchBuffer has 3 wides.
EXPECTED_WIDE = {
    'MLSR_Optimized_Constants': (2, 0x3101e8),
    'ScratchBuffer': (3, 0x310220),
    'rw_reprojected_color': (2, 0x310240),
    'r_history_color': (2, 0x310270),
    'r_velocity': (2, 0x310290),
    'r_input_color': (2, 0x3102a8),
    'r_recurrent_0': (2, 0x3102c8),
    'r_depth': (2, 0x3103d8),
    'r_input_exposure': (2, 0x3103e8),
    'r_auto_exposure_texture': (2, 0x310410),
}

# ASCII extras that disambiguate the wide table (kept for change detection).
EXPECTED_ASCII_EXTRA = {
    'r_velocity': 1,
    'r_input_color': 1,
    'r_input_exposure': 2,
    'r_auto_exposure_texture': 2,
    'MLSR_Optimized_Constants': 2,
    'ScratchBuffer': 51,
}

# PRE dispatch equivalent (logical function, pdata-split).
PRE_ENTRY_RVA = 0x24e00
PRE_END_RVA = 0x2666a
PRE_CALLER_SITE_RVA = 0x8e3a
PRE_CALLER_FUNC = (0x8a1c, 0x99b7)
MODE_FUN_RVA = 0x2bed0
MODE_FUN_SIZE = 145
HELPER_BARRIER_RVA = 0x27bc0
HELPER_BARRIER_SIZE = 57
HELPER_DESC_RVA = 0xbbd0
HELPER_DESC_SIZE = 198

# (lea_site_rva -> target_string_rva) for RIP-relative LEAs in .text.
LEA_ANCHORS = {
    0x25110: 0x311790,  # ABI mismatch fail-stop
    0x26635: 0x311890,  # geometry fail-stop (via FUN_18002d710 path)
    0x26646: 0x311840,  # ScratchBuffer layout
    0x26652: 0x311740,  # constants incomplete
    0x2665e: 0x3116f0,  # stock binding missing
    0x2666a: 0x3115a0,  # params not ready
    0x24ea9: 0x3115e8,  # MLSR_Optimized_Constants (first table ref)
    0x24ef2: 0x311620,  # ScratchBuffer (first table ref)
}

# Expected raw vtable-call opcode counts inside PRE file range
# 0x24e00..0x2666a (covers the logical dispatch).
EXPECTED_VTABLE_OPCODE_COUNTS = {
    'FF5048': 2,          # GetCPUDescriptorHandleForHeapStart (+0x48)
    'FF5050': 4,          # GetDesc (+0x50)
    'FF5058': 1,          # GetGPUDescriptorHandleForHeapStart path (+0x58)
    'FF5070': 2,          # Dispatch (+0x70)
    'FF5078': 9,          # +0x78 (copy/barrier helper path)
    'FF9090000000': 2,    # CreateShaderResourceView (+0x90)
    'FF90C0000000': 1,    # CopyDescriptorsSimple (+0xC0)
    'FF90C8000000': 1,    # SetPipelineState (+0xC8)
    'FF90D0000000': 12,   # ResourceBarrier (+0xD0)
    'FF90E0000000': 1,    # SetDescriptorHeaps (+0xE0)
    'FF90E8000000': 1,    # +0xE8
    'FF90F8000000': 3,    # SetComputeRootDescriptorTable (+0xF8)
    'FF9008010000': 1,    # SetComputeRoot32BitConstant (+0x108)
    'FF90A8010000': 7,    # +0x1A8 (per-slot dispatch helper)
}

D3D12_HEADER_SHA256 = '23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e'
DXGI_FORMAT_HEADER_SHA256 = '8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48'


def verify_hash(data, expected, label):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f'Unreviewed {label} SHA-256: {actual}')
    return actual


def parse_pe(data):
    if data[:2] != b'MZ':
        raise ValueError('Not an MZ/PE candidate')
    e_lfanew, = struct.unpack_from('<I', data, 0x3c)
    if data[e_lfanew:e_lfanew + 4] != b'PE\x00\x00':
        raise ValueError('Missing PE signature')
    nsec, = struct.unpack_from('<H', data, e_lfanew + 4 + 2)
    szopt, = struct.unpack_from('<H', data, e_lfanew + 4 + 16)
    opt = e_lfanew + 4 + 20
    magic, = struct.unpack_from('<H', data, opt)
    if magic != 0x20b:
        raise ValueError('Expected PE32+ (x86-64)')
    imagebase, = struct.unpack_from('<Q', data, opt + 24)
    sec_off = e_lfanew + 4 + 20 + szopt
    sections = {}
    for i in range(nsec):
        base = sec_off + i * 40
        name = data[base:base + 8].rstrip(b'\x00').decode()
        vsize, vaddr, rawsz, rawptr = struct.unpack_from('<IIII', data, base + 8)
        sections[name] = (vsize, vaddr, rawsz, rawptr)
    pdata = sections.get('.pdata')
    funcs = []
    if pdata is not None:
        _, _, prawsz, prawptr = pdata
        raw = data[prawptr:prawptr + prawsz]
        for i in range(len(raw) // 12):
            b, e, u = struct.unpack_from('<III', raw, i * 12)
            if b or e:
                funcs.append((b, e, u))
    return imagebase, sections, funcs


def rva_to_offset(rva, sections):
    for _, (vsize, vaddr, rawsz, rawptr) in sections.items():
        span = max(vsize, rawsz)
        if vaddr <= rva < vaddr + span:
            return rawptr + (rva - vaddr)
    raise ValueError(f'Unmapped RVA {rva:#x}')


def read_pinned_dll():
    data = DLL.read_bytes()
    if len(data) != DLL_SIZE:
        raise ValueError(f'Unreviewed DLL size: {len(data)}')
    verify_hash(data, DLL_SHA256, 'XMX 4.1.2 DLL')
    return data


class Xmx412DispatchAnchorTests(unittest.TestCase):
    def test_dll_hash_size_and_pe_layout(self):
        data = read_pinned_dll()
        imagebase, sections, _ = parse_pe(data)
        self.assertEqual(imagebase, IMAGE_BASE)
        # Pinned section geometry (image base 0x180000000).
        self.assertEqual(sections['.text'][1], 0x1000)
        self.assertEqual(sections['.text'][0], 0x7762f)
        self.assertEqual(sections['.rdata'][1], 0x79000)
        # .text must cover the whole logical PRE range.
        _, text_vaddr, text_rawsz, _ = sections['.text']
        for rva in (PRE_ENTRY_RVA, PRE_END_RVA - 1, PRE_CALLER_SITE_RVA,
                    MODE_FUN_RVA, HELPER_DESC_RVA, HELPER_BARRIER_RVA):
            self.assertTrue(text_vaddr <= rva < text_vaddr + text_rawsz, hex(rva))

    def test_ascii_failstop_anchors_exact(self):
        data = read_pinned_dll()
        _, sections, _ = parse_pe(data)
        for text, (count, file_off, rva) in EXPECTED_ASCII.items():
            blob = text.encode('ascii')
            self.assertEqual(data.count(blob), count, text[:50])
            # Pin first file offset and its RVA mapping.
            self.assertEqual(data.find(blob), file_off, text[:50])
            self.assertEqual(rva_to_offset(rva, sections), file_off, text[:50])
            # C strings here are LF-terminated (fail-stops) or NUL-terminated
            # (geometry); both end with a 0x00 within the next two bytes.
            tail = data[file_off + len(blob):file_off + len(blob) + 2]
            self.assertIn(tail[:1], (b'\n', b'\x00'), text[:50])
            self.assertIn(b'\x00', tail, text[:50])

    def test_wide_stock_table_same_ten_names(self):
        data = read_pinned_dll()
        self.assertEqual(sorted(EXPECTED_WIDE), sorted([
            'MLSR_Optimized_Constants', 'ScratchBuffer', 'rw_reprojected_color',
            'r_history_color', 'r_velocity', 'r_input_color', 'r_recurrent_0',
            'r_depth', 'r_input_exposure', 'r_auto_exposure_texture']))
        for name, (count, first_off) in EXPECTED_WIDE.items():
            blob = name.encode('utf-16le')
            self.assertEqual(data.count(blob), count, name)
            self.assertEqual(data.find(blob), first_off, name)
        for name, count in EXPECTED_ASCII_EXTRA.items():
            self.assertEqual(data.count(name.encode('ascii')), count, name)

    def test_pre_entry_caller_and_pdata_split(self):
        data = read_pinned_dll()
        _, sections, funcs = parse_pe(data)

        def covering(rva):
            for b, e, u in funcs:
                if b <= rva < e:
                    return (b, e, u)
            raise ValueError(f'RVA {rva:#x} has no pdata entry')

        # Entry 0x24e00 falls through to 0x24e5a; pdata splits the logical
        # dispatch into [0x24e00,0x24e5a) + [0x24e5a,0x25147) + [0x25163,0x2666a).
        b0, e0, _ = covering(PRE_ENTRY_RVA)
        self.assertEqual((b0, e0), (0x24e00, 0x24e5a))
        b1, e1, _ = covering(0x24e5a)
        self.assertEqual((b1, e1), (0x24e5a, 0x25147))
        b2, e2, _ = covering(0x25163)
        self.assertEqual((b2, e2), (0x25163, 0x2666a))
        self.assertEqual((e1 - b1) + (e2 - b2), 749 + 5383)
        # Helpers and mode function sizes are pinned.
        self.assertEqual(covering(MODE_FUN_RVA)[:2], (MODE_FUN_RVA, MODE_FUN_RVA + MODE_FUN_SIZE))
        self.assertEqual(covering(HELPER_DESC_RVA)[:2],
                         (HELPER_DESC_RVA, HELPER_DESC_RVA + HELPER_DESC_SIZE))
        self.assertEqual(covering(HELPER_BARRIER_RVA)[:2],
                         (HELPER_BARRIER_RVA, HELPER_BARRIER_RVA + HELPER_BARRIER_SIZE))
        # Single direct caller: E8 at 0x8e3a targets 0x24e00.
        call_off = rva_to_offset(PRE_CALLER_SITE_RVA, sections)
        self.assertEqual(data[call_off], 0xE8)
        rel, = struct.unpack_from('<i', data, call_off + 1)
        self.assertEqual(PRE_CALLER_SITE_RVA + 5 + rel, PRE_ENTRY_RVA)
        # Caller site lives in the single caller function.
        for b, e, _ in funcs:
            if b <= PRE_CALLER_SITE_RVA < e:
                self.assertEqual((b, e), PRE_CALLER_FUNC)
                break
        else:
            self.fail('caller site has no pdata entry')
        # No second direct E8 to the entry (unique caller).
        text_vsize, text_vaddr, text_rawsz, text_rawptr = sections['.text']
        text = data[text_rawptr:text_rawptr + text_rawsz]
        hits = 0
        for i in range(len(text) - 5):
            if text[i] == 0xE8:
                r = struct.unpack_from('<i', text, i + 1)[0]
                if text_vaddr + i + 5 + r == PRE_ENTRY_RVA:
                    hits += 1
        self.assertEqual(hits, 1)

    def test_lea_anchors_point_at_strings(self):
        data = read_pinned_dll()
        _, sections, _ = parse_pe(data)
        for site, target in LEA_ANCHORS.items():
            off = rva_to_offset(site, sections)
            # 48 8D disp32 with ModRM rip-relative (0x05/0x0D/0x15/0x1D...).
            self.assertIn(data[off], (0x48, 0x4C, 0x4D))
            self.assertEqual(data[off + 1], 0x8D)
            self.assertEqual(data[off + 2] & 0xC7, 0x05)
            disp, = struct.unpack_from('<i', data, off + 3)
            self.assertEqual(site + 7 + disp, target, hex(site))

    def test_grid_formula_and_mode_branches(self):
        data = read_pinned_dll()
        _, sections, _ = parse_pe(data)

        def raw(rva, n=10):
            return data[rva_to_offset(rva, sections):rva_to_offset(rva, sections) + n]

        # w = [ctx+0x840]; h = [ctx+0x844]; x = (w+15)>>4; x += x&1 (r13d=1); y = h>>1.
        self.assertEqual(raw(0x26094, 3), bytes.fromhex('83C00F'))  # add $15, %eax
        self.assertEqual(raw(0x26099, 3), bytes.fromhex('C1E804'))  # shr $4, %eax
        # r13d pinned to 1 before the grid (mov $1, %r13d).
        self.assertEqual(raw(0x25d55, 6), bytes.fromhex('41BD01000000'))
        # and %r13d, %r15d / add %eax, %r15d  (x += x&1).
        grid_tail = raw(0x2609c, 9).hex().upper()
        self.assertIn('4523FD', grid_tail)  # and r13d, r15d
        self.assertIn('4403F8', grid_tail)  # add eax, r15d
        # Mode branches: 2..6 (mode = return of 0x2bed0).
        self.assertEqual(raw(0x25e82, 3), bytes.fromhex('83FE02'))  # cmp $2, %esi
        self.assertEqual(raw(0x26055, 3), bytes.fromhex('83FE03'))  # cmp $3, %esi
        self.assertEqual(raw(0x260a5, 3), bytes.fromhex('83FE04'))  # cmp $4, %esi
        self.assertEqual(raw(0x260b2, 3), bytes.fromhex('83FE05'))  # cmp $5, %esi
        self.assertEqual(raw(0x260bc, 3), bytes.fromhex('83FE06'))  # cmp $6, %esi
        # Mode 6 loads 0x44 for y.
        self.assertIn('B844000000', raw(0x260bc, 12).hex().upper())
        # Modes 2,3 share the return-1 target (mov $1, %al at 0x2662e).
        self.assertEqual(raw(0x2662e, 2), bytes.fromhex('B001'))
        # ABI gate 0x50580000 and ScratchBuffer bound factor 0x7E9000.
        blob = data[rva_to_offset(PRE_ENTRY_RVA, sections):rva_to_offset(PRE_END_RVA, sections)]
        self.assertIn(struct.pack('<I', 0x50580000), blob)
        self.assertIn(struct.pack('<I', 0x7E9000), blob)
        # Mode call site: E8 at 0x25a3e targets 0x2bed0.
        call_off = rva_to_offset(0x25a3e, sections)
        self.assertEqual(data[call_off], 0xE8)
        rel, = struct.unpack_from('<i', data, call_off + 1)
        self.assertEqual(0x25a3e + 5 + rel, MODE_FUN_RVA)
        # Dispatch slots: both paths end in call *0x70(%rax).
        for rva in (0x26394, 0x263c9):
            self.assertEqual(raw(rva, 3), bytes.fromhex('FF5070'))

    def test_vtable_opcode_counts_in_pre_range(self):
        data = read_pinned_dll()
        _, sections, _ = parse_pe(data)
        blob = data[rva_to_offset(PRE_ENTRY_RVA, sections):rva_to_offset(PRE_END_RVA, sections)]
        for hexpat, count in EXPECTED_VTABLE_OPCODE_COUNTS.items():
            self.assertEqual(blob.count(bytes.fromhex(hexpat)), count, hexpat)

    def test_rejects_unpinned_hash(self):
        with self.assertRaisesRegex(ValueError, 'Unreviewed test input SHA-256'):
            verify_hash(b'modified', '0' * 64, 'test input')

    def test_rejects_changed_ascii_anchor(self):
        data = bytearray(read_pinned_dll())
        needle = b'PRE runtime-flag ABI mismatch'
        i = bytes(data).find(needle)
        self.assertGreaterEqual(i, 0)
        data[i] ^= 0x01
        self.assertNotEqual(bytes(data).count(needle), 1)

    def test_rejects_changed_lea_target(self):
        data = read_pinned_dll()
        _, sections, _ = parse_pe(data)
        off = rva_to_offset(0x25110, sections)
        disp, = struct.unpack_from('<i', data, off + 3)
        self.assertEqual(0x25110 + 7 + disp, 0x311790)
        self.assertNotEqual(0x25110 + 7 + (disp + 1), 0x311790)


@unittest.skipUnless(DLL.is_file() and (TOOLCHAIN_INCLUDE / 'd3d12.h').is_file() and
                     (TOOLCHAIN_INCLUDE / 'dxgiformat.h').is_file(),
                     'Requires pinned DLL and local LLVM-MinGW headers')
class LocalHeaderAbiTests(unittest.TestCase):
    def test_pinned_headers_match_hashes(self):
        verify_hash((TOOLCHAIN_INCLUDE / 'd3d12.h').read_bytes(),
                    D3D12_HEADER_SHA256, 'D3D12 header')
        verify_hash((TOOLCHAIN_INCLUDE / 'dxgiformat.h').read_bytes(),
                    DXGI_FORMAT_HEADER_SHA256, 'DXGI format header')

    @unittest.skipUnless(COMPILER.is_file(), 'Requires local LLVM-MinGW compiler for ABI assertions')
    def test_real_windows_headers_confirm_vtable_and_descriptor_offsets(self):
        source = r'''
#define CINTERFACE
#include <d3d12.h>
static_assert(DXGI_FORMAT_R8_UINT == 0x3e);
static_assert(D3D12_RESOURCE_DIMENSION_BUFFER == 1);
static_assert(D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING == 0x1688);
static_assert(__builtin_offsetof(ID3D12DeviceVtbl, CreateShaderResourceView) == 0x90);
static_assert(__builtin_offsetof(ID3D12DeviceVtbl, CreateUnorderedAccessView) == 0x98);
static_assert(__builtin_offsetof(ID3D12DeviceVtbl, CopyDescriptorsSimple) == 0xc0);
static_assert(__builtin_offsetof(ID3D12DescriptorHeapVtbl, GetCPUDescriptorHandleForHeapStart) == 0x48);
static_assert(__builtin_offsetof(ID3D12ResourceVtbl, GetDesc) == 0x50);
static_assert(__builtin_offsetof(D3D12_RESOURCE_DESC, Width) == 16);
static_assert(__builtin_offsetof(D3D12_SHADER_RESOURCE_VIEW_DESC, Buffer) == 16);
static_assert(__builtin_offsetof(D3D12_BUFFER_SRV, NumElements) == 8);
static_assert(__builtin_offsetof(D3D12_UNORDERED_ACCESS_VIEW_DESC, Buffer) == 8);
static_assert(__builtin_offsetof(D3D12_BUFFER_UAV, NumElements) == 8);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, Dispatch) == 0x70);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, ResourceBarrier) == 0xd0);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, SetDescriptorHeaps) == 0xe0);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, SetPipelineState) == 0xc8);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, SetComputeRootDescriptorTable) == 0xf8);
static_assert(__builtin_offsetof(ID3D12GraphicsCommandListVtbl, SetComputeRoot32BitConstant) == 0x108);
static_assert(__builtin_offsetof(ID3D12DescriptorHeapVtbl, GetGPUDescriptorHandleForHeapStart) == 0x50);
'''
        result = subprocess.run([str(COMPILER), '-std=c++17', '-fms-extensions',
                                 '-x', 'c++', '-fsyntax-only', '-'], input=source,
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
