# Independent static evidence with REA — pinned DLL

Date: 2026-11-12. Static inspection only, without executing the DLL.

## Artifact

- `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256: `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`
- PE32+, x86_64. REA `open_binary` confirms the format and architecture.

## Imports (REA `inspect_pe_imports`, full coverage)

- 16 DLLs, 167 functions, 0 delay-imports.
- `d3d12.dll`: only `D3D12SerializeRootSignature`.
- `dxgi.dll`: only `CreateDXGIFactory2`.
- No direct imports of `CreateCommittedResource`,
  `CreateShaderResourceView`, `CreateUnorderedAccessView` nor `CopyDescriptors*`.
- This corroborates the local reading with `llvm-objdump -p`: resource/view
  creation happens through D3D12 vtables received from the host, not through imports.

## Exports (REA `inspect_native_exports`, full coverage)

5 exports, no forwarders:

| Name | Ordinal | Address |
|---|---|---|
| `ffxConfigure` | 1 | `0x180001240` |
| `ffxCreateContext` | 2 | `0x180001290` |
| `ffxDestroyContext` | 3 | `0x180001340` |
| `ffxDispatch` | 4 | `0x1800013b0` |
| `ffxQuery` | 5 | `0x180001400` |

They match the local dump `analysis/fsr-xmx-disassembly.txt`.

## Resources (REA `inspect_pe_resources`, full coverage)

5 resources, hashes identical to `analysis/fsr-resources/manifest.json`:

| Type | Name | Bytes | SHA-256 |
|---|---|---:|---|
| 10 | 40101 | 6454442 | `587f138c…34e503a5` |
| 10 | 40102 | 3777348 | `25538200…815a74290` |
| 10 | 40103 | 2229762 | `1847b9af…6a7fe74681` |
| 16 | 1 | 728 | `c974f38e…e99ffdd76` |
| 24 | 2 | 145 | `d2952e57…d68bde04` |

## REA limits in this environment

- No disassembly provider (Ghidra/Hopper/IDA/Kuna not configured).
- `analyze_function` not available; no new pseudocode or CFG.
- objdump symbols: the image is stripped, with no symbol table.
- The above does not invalidate the PE evidence; it only limits its scope.

## Implication

It reinforces `docs/pre-resource-descriptors.md`: views via vtables, copies via
`CopyDescriptorsSimple`, with no direct allocation visible in the imports. It
does not prove the creators of images nor initial contents. It does not
authorize PRE dispatch.
