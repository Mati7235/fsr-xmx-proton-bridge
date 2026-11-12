# Evidencia estática independiente con REA — DLL fijada

Fecha: 2026-11-12. Solo inspección estática, sin ejecutar la DLL.

## Artefacto

- `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256: `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`
- PE32+, x86_64. REA `open_binary` confirma formato y arquitectura.

## Imports (REA `inspect_pe_imports`, cobertura completa)

- 16 DLLs, 167 funciones, 0 delay-imports.
- `d3d12.dll`: solo `D3D12SerializeRootSignature`.
- `dxgi.dll`: solo `CreateDXGIFactory2`.
- Sin imports directos de `CreateCommittedResource`,
  `CreateShaderResourceView`, `CreateUnorderedAccessView` ni `CopyDescriptors*`.
- Esto corrobora la lectura local con `llvm-objdump -p`: la creación de
  recursos/vistas ocurre por vtables D3D12 recibidas del host, no por imports.

## Exports (REA `inspect_native_exports`, cobertura completa)

5 exports, sin forwarders:

| Nombre | Ordinal | Dirección |
|---|---|---|
| `ffxConfigure` | 1 | `0x180001240` |
| `ffxCreateContext` | 2 | `0x180001290` |
| `ffxDestroyContext` | 3 | `0x180001340` |
| `ffxDispatch` | 4 | `0x1800013b0` |
| `ffxQuery` | 5 | `0x180001400` |

Coinciden con el dump local `analysis/fsr-xmx-disassembly.txt`.

## Recursos (REA `inspect_pe_resources`, cobertura completa)

5 recursos, hashes idénticos a `analysis/fsr-resources/manifest.json`:

| Tipo | Nombre | Bytes | SHA-256 |
|---|---|---:|---|
| 10 | 40101 | 6454442 | `587f138c…34e503a5` |
| 10 | 40102 | 3777348 | `25538200…815a74290` |
| 10 | 40103 | 2229762 | `1847b9af…6a7fe74681` |
| 16 | 1 | 728 | `c974f38e…e99ffdd76` |
| 24 | 2 | 145 | `d2952e57…d68bde04` |

## Límites de REA en este entorno

- Sin proveedor de desensamblado (Ghidra/Hopper/IDA/Kuna no configurados).
- `analyze_function` no disponible; no hay pseudocódigo ni CFG nuevos.
- Símbolos objdump: imagen stripped, sin tabla de símbolos.
- Lo anterior no invalida la evidencia PE; solo limita el alcance.

## Implicancia

Refuerza `docs/pre-resource-descriptors.md`: vistas por vtables, copias por
`CopyDescriptorsSimple`, sin asignación directa visible en imports. No prueba
creadores de imágenes ni contenido inicial. No autoriza dispatch PRE.
