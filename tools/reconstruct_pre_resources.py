#!/usr/bin/env python3
"""Extract hash-pinned PRE D3D12 descriptor/copy evidence; never loads the DLL."""
import argparse
import hashlib
import json
from pathlib import Path
import re

if __package__:
    from .reconstruct_pre import reconstruct as reconstruct_pre_tables
else:
    from reconstruct_pre import reconstruct as reconstruct_pre_tables


DLL_SHA256 = "3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53"
DISASSEMBLY_SHA256 = "4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0"
D3D12_HEADER_SHA256 = "23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e"
DXGI_FORMAT_HEADER_SHA256 = "8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48"

ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN_INCLUDE = ROOT / "artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include"
LINE_RE = re.compile(r"^\s*(?:0x)?([0-9a-fA-F]{8,16}):\s+(.*)$")
CALL_RE = re.compile(r"\bcall\s+(?:0x)?([0-9a-fA-F]{8,16})\b", re.IGNORECASE)
WINDOWS = {
    "exported_ffx_boundary": (0x180001290, 0x180001400),
    "dispatch_wrapper_caller": (0x1800058A1, 0x1800058E6),
    "resource_width_guard_and_arg0_uav": (0x1800169DD, 0x180016A0E),
    "arg0_resource_getdesc": (0x180016973, 0x1800169E5),
    "pre_descriptor_creation_and_binding": (0x18001711B, 0x180017543),
    "descriptor_copy_helper": (0x180002DF0, 0x180002E83),
}


def verify_hash(data, expected, label):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(f"Unreviewed {label} SHA-256: {actual}")
    return actual


def parse_lines(text):
    result = {}
    for line in text.splitlines():
        match = LINE_RE.match(line)
        if match:
            result[int(match.group(1), 16)] = re.sub(r"\s+", " ", line.strip())
    return result


def extract(text):
    lines = parse_lines(text)
    callers = []
    for address, line in lines.items():
        match = CALL_RE.search(line)
        if match and int(match.group(1), 16) == 0x1800163C0:
            callers.append({"address": f"0x{address:x}", "instruction": line})

    # These are instruction facts, cross-checked with the pinned D3D12 headers.
    required = {
        0x180016976: "lea rdx, [rbp + 0x100]",
        0x18001697D: "call qword ptr [rax + 0x50]",
        0x180016984: "mov edx, 0x1",
        0x1800169B2: "mov eax, dword ptr [rcx + 0x24]",
        0x1800169DF: "cmp dword ptr [rbp + 0x100], edx",
        0x1800169EB: "mov rcx, qword ptr [rbp + 0x110]",
        0x1800169F6: "imul rax, rax, 0x7e9000",
        0x1800171A0: "mov dword ptr [rbp + 0x7c], eax",
        0x1800171A6: "mov eax, dword ptr [rbp + 0x110]",
        0x1800171AC: "mov dword ptr [rbp + 0x88], eax",
        0x1800171B7: "mov qword ptr [rbp + 0x98], r15",
        0x1800171C2: "mov dword ptr [rbp + 0x78], 0x3e",
        0x1800171CC: "mov qword ptr [rbp + 0x80], r15",
        0x1800171D3: "mov dword ptr [rbp + 0x8c], r15d",
        0x1800171F3: "mov r10, qword ptr [rdx + 0x98]",
        0x1800171FF: "call r10",
        0x18001711B: "call 0x180002df0",
        0x180017120: "mov r8d, dword ptr [rsp + 0x7c]",
        0x18001712D: "call 0x180002df0",
        0x180017136: "mov r8d, esi",
        0x18001713D: "call 0x180002df0",
        0x180017146: "lea edx, [r15 + 0x3]",
        0x18001714E: "call 0x180002df0",
        0x180017153: "mov r8d, dword ptr [rbp - 0x7c]",
        0x18001715F: "call 0x180002df0",
        0x180017168: "mov r8d, edi",
        0x18001716F: "call 0x180002df0",
        0x180017178: "mov r8d, ebx",
        0x18001717F: "call 0x180002df0",
        0x18001727E: "call qword ptr [rax + 0xc0]",
        0x1800172F1: "mov qword ptr [rbp + 0x58], 0x1688",
        0x1800172FD: "mov dword ptr [rbp + 0x50], 0x3e",
        0x180017304: "mov dword ptr [rbp + 0x54], r13d",
        0x180017308: "mov qword ptr [rbp + 0x60], r15",
        0x18001730C: "mov qword ptr [rbp + 0x68], 0x840",
        0x18001731A: "mov rdx, qword ptr [rdx + 0xa80]",
        0x18001732F: "call qword ptr [rax + 0x90]",
        0x180017345: "mov dword ptr [rbp + 0x68], 0x80",
        0x180017352: "mov rdx, qword ptr [rdx + 0xa98]",
        0x180017367: "call qword ptr [rax + 0x90]",
        0x180002E2B: "call qword ptr [rax + 0x48]",
        0x180002E21: "mov rcx, qword ptr [r8 + 0x1b40]",
        0x180002E71: "call qword ptr [rax + 0xc0]",
    }
    for address, fragment in required.items():
        if address not in lines or fragment not in lines[address]:
            raise ValueError(f"Pinned instruction mismatch at 0x{address:x}")

    windows = {
        name: [line for address, line in sorted(lines.items()) if start <= address <= end]
        for name, (start, end) in WINDOWS.items()
    }
    return {
        "caller_xrefs_to_0x1800163c0": callers,
        "reviewed_instruction_windows": windows,
        "d3d12_descriptor_findings": {
            "device_vtable_offsets": {
                "+0x48": "ID3D12DescriptorHeap::GetCPUDescriptorHandleForHeapStart",
                "+0x50 (resource)": "ID3D12Resource::GetDesc",
                "+0x90": "ID3D12Device::CreateShaderResourceView",
                "+0x98": "ID3D12Device::CreateUnorderedAccessView",
                "+0xc0": "ID3D12Device::CopyDescriptorsSimple",
            },
            "heap7_arg0_uav": {
                "format_enum": 0x3E,
                "format_name": "DXGI_FORMAT_R8_UINT",
                "view_dimension": "D3D12_UAV_DIMENSION_BUFFER (1)",
                "first_element": 0,
                "num_elements": "resource D3D12_RESOURCE_DESC.Width, loaded from [rbp+0x110]",
                "structure_byte_stride": 0,
                "counter_offset": 0,
                "flags": 0,
                "resource_dimension_guard": "GetDesc.Dimension == D3D12_RESOURCE_DIMENSION_BUFFER (1), held in edx",
                "resource_width_lower_bound_expression": "variantTableDwordAt0x24 * variantTableDwordAt0x24 * 0x7e9000; fallback factor 1",
                "resource_width_lower_bound_if_factor_is_1": 0x7E9000,
                "resource_width_upper_bound_bytes": 0xFFFFFFFF,
                "evidence": ["0x180016973..0x1800169e5 GetDesc + Dimension check", "0x1800169eb..0x180016a0e Width bounds", "0x180017184..0x1800171ff UAV desc + ID3D12Device::CreateUnorderedAccessView"],
                "caveat": "Dimension is fixed BUFFER; the width factor is a separate value in eax. Width/active variant remain runtime-dependent, and a lower bound is not an exact allocation size.",
            },
            "heap9_arg9_srv": {
                "resource_context_offset": "0xa80",
                "format_enum": 0x3E,
                "format_name": "DXGI_FORMAT_R8_UINT",
                "view_dimension": "D3D12_SRV_DIMENSION_BUFFER (1)",
                "component_mapping": 0x1688,
                "first_element": 0,
                "num_elements": 0x840,
                "num_elements_decimal": 2112,
                "visible_typed_bytes": 2112,
                "evidence": ["0x1800172e1..0x18001732f D3D12_SHADER_RESOURCE_VIEW_DESC + CreateShaderResourceView"],
                "structure_byte_stride": 0,
                "flags": 0,
                "caveat": "View extent is fixed; backing resource allocation and initial bytes are not.",
            },
            "heap10_arg10_srv": {
                "resource_context_offset": "0xa98",
                "format_enum": 0x3E,
                "format_name": "DXGI_FORMAT_R8_UINT",
                "view_dimension": "D3D12_SRV_DIMENSION_BUFFER (1)",
                "component_mapping": 0x1688,
                "first_element": 0,
                "num_elements": 0x80,
                "num_elements_decimal": 128,
                "visible_typed_bytes": 128,
                "evidence": ["0x180017335..0x180017367 descriptor reuses R8_UINT BUFFER layout with NumElements=0x80"],
                "structure_byte_stride": 0,
                "flags": 0,
                "caveat": "The 128-byte header is viewable/read by the kernel; backing allocation and header contents are runtime inputs.",
            },
            "read_only_images": {
                "arguments": "t0..t6 (PRE args 2..8), destination descriptor heap indices 0..6",
                "operation": "CopyDescriptorsSimple via helper 0x180002df0; source indices passed in r8d from dispatch-selected values",
                "source_handle": "CPU handle start of heap at context+0x1b40 + source index * descriptor increment",
                "source_index_registers_by_destination_slot": [
                    "slot0 <- [rsp+0x78]", "slot1 <- [rsp+0x7c]", "slot2 <- esi",
                    "slot3 <- [rbp-0x80]", "slot4 <- [rbp-0x7c]", "slot5 <- edi", "slot6 <- ebx",
                ],
                "destination_slots": [0, 1, 2, 3, 4, 5, 6],
                "evidence": ["calls at 0x18001711b..0x18001717f", "helper obtains heap CPU start at +0x48 and copies via device +0xc0 at 0x180002df0..0x180002e83"],
                "limitation": "Source descriptors are copied; their texture formats/dimensions are not reconstructed by this sequence.",
            },
            "arg1_u1_image": {
                "heap_index": 8,
                "operation": "CopyDescriptorsSimple path at 0x18001727e; source image descriptor contents are copied, not defined by the local descriptor constructor analyzed here.",
                "limitation": "Source descriptor/resource identity and its dimensions/format still require tracing the source handle.",
            },
        },
    }


def reconstruct(dll_path, disassembly_path, d3d12_header_path, dxgi_header_path):
    dll_bytes = dll_path.read_bytes()
    dll_hash = verify_hash(dll_bytes, DLL_SHA256, "DLL")
    disasm_bytes = disassembly_path.read_bytes()
    disasm_hash = verify_hash(disasm_bytes, DISASSEMBLY_SHA256, "disassembly")
    d3d_hash = verify_hash(d3d12_header_path.read_bytes(), D3D12_HEADER_SHA256, "D3D12 header")
    dxgi_hash = verify_hash(dxgi_header_path.read_bytes(), DXGI_FORMAT_HEADER_SHA256, "DXGI format header")
    evidence = extract(disasm_bytes.decode("utf-8"))
    if len(evidence["caller_xrefs_to_0x1800163c0"]) != 1:
        raise ValueError("Expected exactly one direct caller in the pinned disassembly")
    evidence['variant_arg0_width_bounds'] = [
        {'variant': item['variant'], 'context_selector': item['index'],
         'table_dword_at_0x24': item['arg0_width_bound_factor'],
         'minimum_resource_width_bytes': item['arg0_width_bound_factor'] ** 2 * 0x7e9000}
        for item in reconstruct_pre_tables(dll_bytes)['pre_variant_payloads']
    ]
    return {
        "status": "static-descriptor-evidence-only",
        "runtime_approved": False,
        "input_sha256": {
            "dll": dll_hash,
            "disassembly": disasm_hash,
            "d3d12_header": d3d_hash,
            "dxgi_format_header": dxgi_hash,
        },
        **evidence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dll", type=Path)
    parser.add_argument("disassembly", type=Path)
    parser.add_argument("--d3d12-header", type=Path, default=TOOLCHAIN_INCLUDE / "d3d12.h")
    parser.add_argument("--dxgi-format-header", type=Path, default=TOOLCHAIN_INCLUDE / "dxgiformat.h")
    args = parser.parse_args()
    result = reconstruct(args.dll, args.disassembly, args.d3d12_header, args.dxgi_format_header)
    print(json.dumps(result, indent=2) + "\n", end="")


if __name__ == "__main__":
    main()
