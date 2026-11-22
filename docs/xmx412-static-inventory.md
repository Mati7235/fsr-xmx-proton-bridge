# XMX 4.1.2 static inventory

Date: 2026-11-12. Static inspection only, CPU-only. The DLL was not executed,
no GPU/Wine, `artifacts/original`, games or prefixes were touched.

## Artifact

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256: `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- Size: 45,558,272 bytes
- PE32+, x86_64 (`machine 0x8664`, `bits 64`), 6 sections.

Old one inventoried (`docs/rea-static-evidence.md`,
`analysis/fsr-xmx-static.json`): `3eb08656…ea08eba53`, 25,779,712 bytes.

## Reproducible method

- `tools/inspect_dll_412.py` (new, stdlib only): reuses
  `tools/inspect_dll.inspect()` without modifying it and adds exports, imports,
  resources, VERSIONINFO/manifest and model markers. The DLL is never
  loaded or executed.
- Output: `analysis/xmx412-static.json` (ignored by git, free).
- Pins: `tests/test_xmx412_inventory.py` (fail-closed).
- Controls: `llvm-readobj --coff-imports/--coff-exports/--coff-resources`
  and REA MCP (`inspect_native_exports`, `inspect_pe_imports`,
  `inspect_pe_resources`, full coverage).

Regenerate:

```sh
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory -v
```

## Exports: not the same 5

REA `inspect_native_exports`, full coverage, no forwarders:

| Name | Ordinal | RVA |
|---|---|---|
| `OptiPluginInit` | 1 | `0x18006fc20` |
| `ffxConfigure` | 2 | `0x180001fc0` |
| `ffxCreateContext` | 3 | `0x180002020` |
| `ffxDestroyContext` | 4 | `0x1800020d0` |
| `ffxDispatch` | 5 | `0x180002140` |
| `ffxQuery` | 6 | `0x1800021a0` |

Old: 5 FFX exports at ordinals 1–5. New: 6 exports; adds
`OptiPluginInit` at ordinal 1 and shifts the 5 FFX exports to ordinals 2–6.
The local parse and `llvm-readobj --coff-exports` match REA.

## Imports: 17 DLLs, 181 functions, 0 delay-imports

REA `inspect_pe_imports`, full coverage (`examined_dlls 17`,
`imports 181`, `delay_imports 0`, `imphash md5 0c1bdb71ec72f8dcd180853c7323ac13`):

| DLL | Functions | Detail |
|---|---:|---|
| `KERNEL32.dll` | 65 | includes `CreateThread`, `GetTickCount64`, `LoadResource/LockResource/SizeofResource/FindResourceW`, `LoadLibraryW/ExW`, `GetProcAddress` |
| `USER32.dll` | 1 | `MessageBoxA` (new vs. old) |
| `dxgi.dll` | 1 | only `CreateDXGIFactory2` |
| `d3d12.dll` | 1 | only `D3D12SerializeRootSignature` |
| `MSVCP140.dll` | 24 | STL/locale/mutex |
| `Cabinet.dll` | 3 | ordinals 40/43/45, no names |
| `bcrypt.dll` | 1 | only `BCryptHash` |
| `VCRUNTIME140_1.dll` | 1 | `__CxxFrameHandler4` |
| `VCRUNTIME140.dll` | 16 | `memcpy/memmove/memset/memcmp`, exceptions |
| `api-ms-win-crt-*.dll` (8) | 69 | stdio/heap/string/runtime/convert/math/environment/locale |

No direct imports of `CreateCommittedResource`,
`CreateShader/Descriptor` or `CopyDescriptors*`: resource and view creation
is still done through the host's D3D12 vtables. `igdext64.dll`
is not a static import; it is resolved at runtime (`LoadLibraryW`,
`GetProcAddress`, `%s\%s\igdext64.dll`, `DriverStore`).

- `CreateDeviceExtensionContext2`? No. Zero occurrences in bytes and in
  ASCII/utf-16le strings. Only `INTC_D3D12_CreateDeviceExtensionContext`.
- `CachedBlob`? Yes as a string (`INTC_D3D12_GetCachedBlob`,
  `_INTC_D3D12_GetCachedBlob`, messages `PRE stage-2 GetCachedBlob …`),
  with no static import (it is an igdext export, not of this DLL).
- INTC observed (10 with/without `_`): `CheckFeatureSupport`,
  `CreateComputePipelineState`, `CreateDeviceExtensionContext`,
  `GetCachedBlob`, `DestroyDeviceExtensionContext`. Identical set to the old one.

Old: 16 DLLs / 167 functions / 0 delay. New adds `USER32.dll`
(`MessageBoxA`) and ~14 functions (`CreateThread`, `GetTickCount64`,
`atoi/atof`, `log2f/exp2`, `wcstombs_s`→`wcsstr`, etc.).

## PE resources: 8 with hashes

REA `inspect_pe_resources`, full coverage (`examined_entries 19`,
`resources 8`). Identical to the local parse and to `tools/decompress_xmx412.py`
`EXPECTED`:

| Type | Name | Bytes | SHA-256 |
|---:|---:|---:|---|
| 10 | 40101 | 6107632 | `8e260219…454e9b9b5` |
| 10 | 40102 | 3856836 | `58557640…3501134d7651` |
| 10 | 40103 | 6960934 | `48963849…901f929f458` |
| 10 | 40104 | 8031050 | `2c93c489…326d9d25fa1` |
| 10 | 40105 | 3421152 | `4cff7b12…6f9e90acb2f` |
| 10 | 40106 | 1001522 | `579f610f…038862d20b0de` |
| 16 | 1 | 776 | `20ba4d46…5e78bd072` |
| 24 | 2 | 145 | `d2952e57…dfd68bde04` |

- `16/1` = VERSIONINFO: `CompanyName Advanced Micro Devices, Inc.`,
  `FileDescription AMD FidelityFX Upscaler Library (FSR 4 and DLSS on Intel XMX)`,
  `FileVersion 4.0.2.1`, `ProductName AMD FidelityFX Upscaler (Intel XMX build)`,
  `ProductVersion 4.0.2.1`, `LegalCopyright Copyright (C) 2025-2026`.
- `24/2` = minimal manifest (145 bytes, only `assembly`,
  `manifestVersion='1.0'`).
- Old: 5 resources (40101–40103 + 16/1 + 24/2). New adds
  40104–40106 (DLSS K / E-F / MX).

## Version / model (presence only, not GPU proof)

- `4.0.2X` (8): `4.0.2X`, `4.0.2X ASkip/Hybrid/QSkip/Skip` and combined.
- `4.1.2X` (2): `4.1.2X`, `4.1.2X Lite`; `FSR 4.1.2 Lite (DG2)`.
- `Lite/INT8`: `FSR4_XMX_LITE`, `FSR4_XMX_INT8`, `Lite/INT8 model requested
  without verified fsr-original.dll weights`, `fsr-original.dll`,
  `embedded Lite XMX resource pack is missing or invalid`.
- `DG2/Xe2`: `18-variant DG2 (SIMD8 DPAS)`, `18-variant Xe2 (SIMD16 DPAS)`,
  `DG2 SIMD8-DPAS`, `Xe2/Xe3 SIMD16-DPAS`, `DLSS K (DG2 + Xe2/Xe3)`,
  `DLSS-MX (DG2)`.
- `DLSS`: ~87 markers (`DLSS K/E/F/MX/LX/EX/FX`, `nvngx_dlss.dll`,
  `FFX_DLSSK/M_*_XMX`, profiles, `DlssLdrTest`). FileDescription already says
  `FSR 4 and DLSS on Intel XMX`.
- `OptiPluginInit`: 1 occurrence (new export).
- Context: `4.20.0` in 27 strings (DIAG + `failed` per pass + `enabled`
  per pass + `requested=4.20.0`).
- `12 pases`: PRE + passes 1–12 with messages `Failed to load/create/serialize`,
  `hybrid enabled`, `full-fusion enabled`, `fused-all host mode`,
  `baseDispatch 120x540x1 / 60x270x1 / 30x135x2 / 30x135x1`.
  Loose token `pass13_params.bin` with no pass 13 messages.
- `DIAG/ABI`: 32 DIAG (`PRE extension context`, `root signature FNV1a64`,
  `SPIR-V bytes/magic/manifestSHA256`, `2160-vs-1080`, `PRE PROFILE`),
  plus `[FSR4 XMX 0028ZR] PRE production ABI: one table per
  SurfaceIndex/sampler; ZB physical heap slots retained`,
  `Stock fallback is disabled; diagnostic magenta`, `DriverStore`.

## REA corroboration

- Exports `ev_d1cea06b…0906e` (complete, 6/6) = local parse + llvm-readobj.
- Imports `ev_a1f49e0e…93cb13` (complete, 17/181/0) = local parse +
  llvm-readobj; Cabinet 40/43/45, `BCryptHash`, a single D3D12/DXGI import.
- Resources `ev_544cdced…4e19432` (complete, 8/8) = local parse +
  `decompress_xmx412.EXPECTED`.
- REA limits in this environment: no disassembler (Ghidra/Hopper/IDA/Kuna
  not configured), no `analyze_function`/pseudocode/CFG; does not invalidate
  the PE inventory.

## Limits

- Presence of strings/imports does not prove execution, API requirements,
  Linux compatibility or GPU correctness.
- No execution, no network, no new disassembly.
- `tools/inspect_dll.py` intact (6 original keys);
  the extended inventory lives in `tools/inspect_dll_412.py`.
