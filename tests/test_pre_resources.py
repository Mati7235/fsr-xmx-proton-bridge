import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.reconstruct_pre_resources import extract, verify_hash, reconstruct, ROOT, TOOLCHAIN_INCLUDE

DLL = ROOT / 'artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll'
DUMP = ROOT / 'analysis/fsr-xmx-disassembly.txt'
COMPILER = TOOLCHAIN_INCLUDE.parent.parent / 'bin/x86_64-w64-mingw32-clang++'


FIXTURE = """\
1800058be:      call 0x1800163c0
180016976:      lea rdx, [rbp + 0x100]
18001697d:      call qword ptr [rax + 0x50]
180016984:      mov edx, 0x1
1800169b2:      mov eax, dword ptr [rcx + 0x24]
1800169df:      cmp dword ptr [rbp + 0x100], edx
1800169eb:      mov rcx, qword ptr [rbp + 0x110]
1800169f6:      imul rax, rax, 0x7e9000
1800171a0:      mov dword ptr [rbp + 0x7c], eax
1800171a6:      mov eax, dword ptr [rbp + 0x110]
1800171ac:      mov dword ptr [rbp + 0x88], eax
1800171b7:      mov qword ptr [rbp + 0x98], r15
1800171c2:      mov dword ptr [rbp + 0x78], 0x3e
1800171cc:      mov qword ptr [rbp + 0x80], r15
1800171d3:      mov dword ptr [rbp + 0x8c], r15d
1800171f3:      mov r10, qword ptr [rdx + 0x98]
1800171ff:      call r10
18001711b:      call 0x180002df0
180017120:      mov r8d, dword ptr [rsp + 0x7c]
18001712d:      call 0x180002df0
180017136:      mov r8d, esi
18001713d:      call 0x180002df0
180017146:      lea edx, [r15 + 0x3]
18001714e:      call 0x180002df0
180017153:      mov r8d, dword ptr [rbp - 0x7c]
18001715f:      call 0x180002df0
180017168:      mov r8d, edi
18001716f:      call 0x180002df0
180017178:      mov r8d, ebx
18001717f:      call 0x180002df0
18001727e:      call qword ptr [rax + 0xc0]
1800172f1:      mov qword ptr [rbp + 0x58], 0x1688
1800172fd:      mov dword ptr [rbp + 0x50], 0x3e
180017304:      mov dword ptr [rbp + 0x54], r13d
180017308:      mov qword ptr [rbp + 0x60], r15
18001730c:      mov qword ptr [rbp + 0x68], 0x840
18001731a:      mov rdx, qword ptr [rdx + 0xa80]
18001732f:      call qword ptr [rax + 0x90]
180017345:      mov dword ptr [rbp + 0x68], 0x80
180017352:      mov rdx, qword ptr [rdx + 0xa98]
180017367:      call qword ptr [rax + 0x90]
180002e21:      mov rcx, qword ptr [r8 + 0x1b40]
180002e2b:      call qword ptr [rax + 0x48]
180002e71:      call qword ptr [rax + 0xc0]
"""


class PreResourceEvidenceTests(unittest.TestCase):
    def test_extracts_pinned_srv_view_formats_extents_and_context_provenance(self):
        findings = extract(FIXTURE)["d3d12_descriptor_findings"]
        self.assertEqual(findings["heap9_arg9_srv"]["format_name"], "DXGI_FORMAT_R8_UINT")
        self.assertEqual(findings["heap9_arg9_srv"]["num_elements"], 0x840)
        self.assertEqual(findings["heap9_arg9_srv"]["resource_context_offset"], "0xa80")
        self.assertEqual(findings["heap10_arg10_srv"]["visible_typed_bytes"], 128)
        self.assertEqual(findings["heap10_arg10_srv"]["resource_context_offset"], "0xa98")
        self.assertEqual(findings["heap7_arg0_uav"]["resource_width_lower_bound_if_factor_is_1"], 0x7E9000)
        self.assertIn('BUFFER (1)', findings['heap7_arg0_uav']['resource_dimension_guard'])

    def test_extracts_direct_caller_and_reviewed_copy_helper_window(self):
        result = extract(FIXTURE)
        self.assertEqual(result["caller_xrefs_to_0x1800163c0"][0]["address"], "0x1800058be")
        self.assertEqual(result["d3d12_descriptor_findings"]["device_vtable_offsets"]["+0xc0"],
                         "ID3D12Device::CopyDescriptorsSimple")

    def test_rejects_unpinned_hashes(self):
        with self.assertRaisesRegex(ValueError, "Unreviewed test input SHA-256"):
            verify_hash(b"modified", "0" * 64, "test input")

    def test_rejects_missing_or_changed_instruction_anchor(self):
        with self.assertRaisesRegex(ValueError, "Pinned instruction mismatch"):
            extract(FIXTURE.replace("0x840", "0x841"))


@unittest.skipUnless(DLL.is_file() and DUMP.is_file() and
                     (TOOLCHAIN_INCLUDE / 'd3d12.h').is_file() and
                     (TOOLCHAIN_INCLUDE / 'dxgiformat.h').is_file(),
                     'Requires pinned DLL, disassembly and local LLVM-MinGW headers')
class LocalPreResourceTests(unittest.TestCase):
    def test_pinned_native1080_view_bounds_and_variant_table(self):
        result = reconstruct(DLL, DUMP, TOOLCHAIN_INCLUDE / 'd3d12.h',
                             TOOLCHAIN_INCLUDE / 'dxgiformat.h')
        self.assertFalse(result['runtime_approved'])
        variants = result['variant_arg0_width_bounds']
        self.assertEqual(len(variants), 18)
        self.assertEqual([v['table_dword_at_0x24'] for v in variants], [1, 2, 4] * 6)
        native = next(v for v in variants if v['variant'] == 'native_1080')
        self.assertEqual(native['context_selector'], 1)
        self.assertEqual(native['minimum_resource_width_bytes'], 8294400)
        self.assertEqual(result['d3d12_descriptor_findings']['heap10_arg10_srv']['visible_typed_bytes'], 128)

    @unittest.skipUnless(COMPILER.is_file(), 'Requires local LLVM-MinGW compiler for compile-only ABI assertions')
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

    @unittest.skipUnless(DLL.is_file(), 'Requires pinned local DLL')
    def test_pinned_dll_carries_ghidra_stock_names_and_failstops(self):
        data = DLL.read_bytes()
        for name in ("MLSR_Optimized_Constants", "ScratchBuffer",
                     "rw_reprojected_color", "r_history_color", "r_velocity",
                     "r_input_color", "r_recurrent_0", "r_depth",
                     "r_input_exposure", "r_auto_exposure_texture"):
            self.assertGreaterEqual(data.count(name.encode('utf-16le')), 2, name)
        for message in ("PRE runtime geometry is unavailable.",
                        "[FSR4 XMX] PRE params are not ready",
                        "[FSR4 XMX] PRE required stock binding missing",
                        "[FSR4 XMX] PRE constants are incomplete",
                        "[FSR4 XMX] PRE runtime-flag ABI mismatch",
                        "[FSR4 XMX] PRE ScratchBuffer layout mismatch",
                        "[FSR4 XMX PARITY] Ring full"):
            self.assertEqual(data.count(message.encode('ascii')), 1, message)


if __name__ == "__main__":
    unittest.main()
