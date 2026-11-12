# Inventario estático XMX 4.1.2

Fecha: 2026-11-12. Solo inspección estática, CPU-only. No se ejecutó la DLL,
sin GPU/Wine, sin tocar `artifacts/original`, juegos ni prefijos.

## Artefacto

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256: `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- Tamaño: 45.558.272 bytes
- PE32+, x86_64 (`machine 0x8664`, `bits 64`), 6 secciones.

Vieja inventariada (`docs/rea-static-evidence.md`,
`analysis/fsr-xmx-static.json`): `3eb08656…ea08eba53`, 25.779.712 bytes.

## Método reproducible

- `tools/inspect_dll_412.py` (nuevo, solo stdlib): reutiliza
  `tools/inspect_dll.inspect()` sin modificarlo y añade exports, imports,
  recursos, VERSIONINFO/manifiesto y marcadores de modelo. La DLL nunca se
  carga ni ejecuta.
- Salida: `analysis/xmx412-static.json` (ignorado por git, libre).
- Pins: `tests/test_xmx412_inventory.py` (fail-closed).
- Controles: `llvm-readobj --coff-imports/--coff-exports/--coff-resources`
  y REA MCP (`inspect_native_exports`, `inspect_pe_imports`,
  `inspect_pe_resources`, cobertura completa).

Regenerar:

```sh
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory -v
```

## Exports: no son los mismos 5

REA `inspect_native_exports`, cobertura completa, sin forwarders:

| Nombre | Ordinal | RVA |
|---|---|---|
| `OptiPluginInit` | 1 | `0x18006fc20` |
| `ffxConfigure` | 2 | `0x180001fc0` |
| `ffxCreateContext` | 3 | `0x180002020` |
| `ffxDestroyContext` | 4 | `0x1800020d0` |
| `ffxDispatch` | 5 | `0x180002140` |
| `ffxQuery` | 6 | `0x1800021a0` |

Vieja: 5 exports FFX en ordinales 1–5. Nueva: 6 exports; añade
`OptiPluginInit` en ordinal 1 y desplaza los 5 FFX a ordinales 2–6.
Parse local y `llvm-readobj --coff-exports` coinciden con REA.

## Imports: 17 DLLs, 181 funciones, 0 delay-imports

REA `inspect_pe_imports`, cobertura completa (`examined_dlls 17`,
`imports 181`, `delay_imports 0`, `imphash md5 0c1bdb71ec72f8dcd180853c7323ac13`):

| DLL | Funciones | Detalle |
|---|---:|---|
| `KERNEL32.dll` | 65 | incluye `CreateThread`, `GetTickCount64`, `LoadResource/LockResource/SizeofResource/FindResourceW`, `LoadLibraryW/ExW`, `GetProcAddress` |
| `USER32.dll` | 1 | `MessageBoxA` (nueva vs vieja) |
| `dxgi.dll` | 1 | solo `CreateDXGIFactory2` |
| `d3d12.dll` | 1 | solo `D3D12SerializeRootSignature` |
| `MSVCP140.dll` | 24 | STL/locale/mutex |
| `Cabinet.dll` | 3 | ordinales 40/43/45, sin nombres |
| `bcrypt.dll` | 1 | solo `BCryptHash` |
| `VCRUNTIME140_1.dll` | 1 | `__CxxFrameHandler4` |
| `VCRUNTIME140.dll` | 16 | `memcpy/memmove/memset/memcmp`, excepciones |
| `api-ms-win-crt-*.dll` (8) | 69 | stdio/heap/string/runtime/convert/math/environment/locale |

Sin imports directos de `CreateCommittedResource`,
`CreateShader/Descriptor` ni `CopyDescriptors*`: la creación de
recursos/vistas sigue siendo por vtables D3D12 del host. `igdext64.dll`
no es import estático; se resuelve en runtime (`LoadLibraryW`,
`GetProcAddress`, `%s\%s\igdext64.dll`, `DriverStore`).

- ¿`CreateDeviceExtensionContext2`? No. Cero ocurrencias en bytes y en
  strings ascii/utf-16le. Solo `INTC_D3D12_CreateDeviceExtensionContext`.
- ¿`CachedBlob`? Sí como cadena (`INTC_D3D12_GetCachedBlob`,
  `_INTC_D3D12_GetCachedBlob`, mensajes `PRE stage-2 GetCachedBlob …`),
  sin import estático (es export de igdext, no de esta DLL).
- INTC observadas (10 con/sin `_`): `CheckFeatureSupport`,
  `CreateComputePipelineState`, `CreateDeviceExtensionContext`,
  `GetCachedBlob`, `DestroyDeviceExtensionContext`. Idéntico set a la vieja.

Vieja: 16 DLLs / 167 funciones / 0 delay. Nueva añade `USER32.dll`
(`MessageBoxA`) y ~14 funciones (`CreateThread`, `GetTickCount64`,
`atoi/atof`, `log2f/exp2`, `wcstombs_s`→`wcsstr`, etc.).

## Recursos PE: 8 con hashes

REA `inspect_pe_resources`, cobertura completa (`examined_entries 19`,
`resources 8`). Idénticos al parse local y a `tools/decompress_xmx412.py`
`EXPECTED`:

| Tipo | Nombre | Bytes | SHA-256 |
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
- `24/2` = manifiesto mínimo (145 bytes, solo `assembly`,
  `manifestVersion='1.0'`).
- Vieja: 5 recursos (40101–40103 + 16/1 + 24/2). Nueva añade
  40104–40106 (DLSS K / E-F / MX).

## Versión / modelo (solo presencia, no prueba GPU)

- `4.0.2X` (8): `4.0.2X`, `4.0.2X ASkip/Hybrid/QSkip/Skip` y combinadas.
- `4.1.2X` (2): `4.1.2X`, `4.1.2X Lite`; `FSR 4.1.2 Lite (DG2)`.
- `Lite/INT8`: `FSR4_XMX_LITE`, `FSR4_XMX_INT8`, `Lite/INT8 model requested
  without verified fsr-original.dll weights`, `fsr-original.dll`,
  `embedded Lite XMX resource pack is missing or invalid`.
- `DG2/Xe2`: `18-variant DG2 (SIMD8 DPAS)`, `18-variant Xe2 (SIMD16 DPAS)`,
  `DG2 SIMD8-DPAS`, `Xe2/Xe3 SIMD16-DPAS`, `DLSS K (DG2 + Xe2/Xe3)`,
  `DLSS-MX (DG2)`.
- `DLSS`: ~87 marcadores (`DLSS K/E/F/MX/LX/EX/FX`, `nvngx_dlss.dll`,
  `FFX_DLSSK/M_*_XMX`, perfiles, `DlssLdrTest`). FileDescription ya dice
  `FSR 4 and DLSS on Intel XMX`.
- `OptiPluginInit`: 1 ocurrencia (nuevo export).
- Contexto: `4.20.0` en 27 cadenas (DIAG + `failed` por pase + `enabled`
  por pase + `requested=4.20.0`).
- `12 pases`: PRE + pases 1–12 con mensajes `Failed to load/create/serialize`,
  `hybrid enabled`, `full-fusion enabled`, `fused-all host mode`,
  `baseDispatch 120x540x1 / 60x270x1 / 30x135x2 / 30x135x1`.
  Token suelto `pass13_params.bin` sin mensajes de pase 13.
- `DIAG/ABI`: 32 DIAG (`PRE extension context`, `root signature FNV1a64`,
  `SPIR-V bytes/magic/manifestSHA256`, `2160-vs-1080`, `PRE PROFILE`),
  más `[FSR4 XMX 0028ZR] PRE production ABI: one table per
  SurfaceIndex/sampler; ZB physical heap slots retained`,
  `Stock fallback is disabled; diagnostic magenta`, `DriverStore`.

## Corroboración REA

- Exports `ev_d1cea06b…0906e` (completa, 6/6) = parse local + llvm-readobj.
- Imports `ev_a1f49e0e…93cb13` (completa, 17/181/0) = parse local +
  llvm-readobj; Cabinet 40/43/45, `BCryptHash`, un solo import D3D12/DXGI.
- Recursos `ev_544cdced…4e19432` (completa, 8/8) = parse local +
  `decompress_xmx412.EXPECTED`.
- Límites REA en este entorno: sin desensamblador (Ghidra/Hopper/IDA/Kuna
  no configurados), sin `analyze_function`/pseudocódigo/CFG; no invalida
  el inventario PE.

## Límites

- Presencia de strings/imports no prueba ejecución, requisitos de API,
  compatibilidad Linux ni corrección GPU.
- Sin ejecución, sin red, sin desensamblado nuevo.
- `tools/inspect_dll.py` intacto (6 claves originales);
  el inventario extendido vive en `tools/inspect_dll_412.py`.
