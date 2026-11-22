# Inventario estático FSR ML Frame Generation 4.0.1

Fecha: 2026-11-22. Solo inspección estática, CPU-only. No se ejecutó la DLL,
sin GPU/Wine, sin tocar juegos ni prefijos. Detalle completo (local, no
versionado): `analysis/fg-401-static/report.md`, `inventory.json`,
`ags-wmma.json`.

## Artefactos

| DLL | Versión | Tamaño | SHA-256 |
|---|---|---:|---|
| Cyberpunk 2077 `bin/x64/amd_fidelityfx_framegeneration_dx12.dll` | 4.0.1.2740 | 40.085.776 | `02297beedd285e822d3a64f314cf00faf378dcec0edc47ff0c4dd71b3a8c2f18` |
| FidelityFX SDK 2.4.0 `amd_fidelityfx_framegeneration_dx12.dll` | 4.0.2.4555 | 29.679.376 | `e6843252f58b0341a0d80f6a20bc0d840643ee95bc48c22cac08745344577bb6` |
| Cyberpunk 2077 `bin/x64/amd_fidelityfx_loader_dx12.dll` | 2.3.0.2740 | 26.376 | `e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa` |

Copias inmutables en `artifacts/original/cp2077-bin-x64/`.

## Hallazgos (offsets de archivo de la DLL 4.0.1)

- Una sola DLL contiene el FG ML y el FG analítico (FSR 3.1): 487 contenedores
  DXBC, SM 6.6 compute. Efecto `FFX_EFFECT_MLFRAMEGENERATION` en `0x10d238`.
- 382 pases ML `mlfi_4k_pass0..190` y `mlfi_8k_pass0..190`; 105 shaders del
  FG clásico (optical flow, `0x2534ea0`).
- Pesos: bloque sin comprimir en `0x2b074c` (RVA `0x2b1f4c`), 10.657.332 B;
  tabla de 128 registros de 32 B y payload desde `0x2b176c` de 5.324.784
  valores. Estadística compatible con **FP16** (0,74 % representable en E4M3,
  mantisa uniforme); confianza alta pero no probada por rastreo de
  descriptores. Segunda copia idéntica en `0x152a400`. El payload es
  byte-idéntico en la 4.0.2 del SDK 2.4.0 (`0xdd704c`).
- Matrices vía intrinsics AGS ("UAV mágico" `u0`, space `0x7FFF0ADE`): 156 de
  382 pases. Ejemplo: `mlfi_8k_pass59` en `0xd3b380`. Ningún shader no-`mlfi`
  lo usa.
- Census AGS (decodificador según dxil-spirv `34f0ff84`, `dxil_ags.hpp`):
  8.048 `WaveMatrixMulAcc`, todo 16x16x16 con acumulador F32:
  `F16` 6.016 (74,8 %) y `FP8_FP8` 2.032 (25,2 %). FP8 solo en
  `pass158..186` pares (15 por variante), con conversiones `F32→FP8` en el
  shader. 4k y 8k tienen conteos idénticos.
- Requisitos: wave32 (`32x1x{1,2,4}`, `WaveSizeRange {32}` en 32 pases), TGSM
  máximo 4.096 B en `mlfi`.
- Imports: solo `dxgi!CreateDXGIFactory2` relevante; sin AGS/amdxc64/nvapi
  estáticos.

## Implicancias para Xe2/XMX

- FP16 es nativo en XMX (`8x16x16 f16→f32` en ANV). FP8→FP16 es exacto, así
  que los pases FP8 se pueden emular exactamente redondeando a la grilla FP8 y
  multiplicando en FP16 con acumulación F32.
- El bloqueo no es el tipo de dato sino el layout: los shaders asumen wave32 y
  matrices 16x16 con reparto de elementos de RDNA; ANV Xe2 usa subgroup 16 y
  M=8. Un port debe traducir semántica de matriz, no copiar elementos por lane.
- La memoria compartida es baja (≤ 4 KB), a diferencia de `k_attn` en el
  upscaler 4.1.2.

## Mapa de pases 4k (`tools/mlfi_pass_map.py`)

- 4k y 8k tienen el mismo IR normalizado en los 191 pares; solo cambian
  constantes de resolución. Los offsets de pesos son idénticos: basta portar
  la variante 4k.
- Histograma de los 191 pases: `param_store` 88, `matmul_f16` 63,
  `param_load` 16, `matmul_fp8` 15, activación 4, resample 3, pack 2. Solo los
  78 pases con WMMA necesitan reemplazo; el resto no usa AGS.
- 60 cuerpos de kernel distintos (20 plantillas con ≥3 miembros y 38
  singletons, casi todos matmul grandes). Conv KxK y GEMM 1x1 no se distinguen
  estáticamente.
- Un único buffer `u0` lleva pesos y activaciones. Los pesos se direccionan
  con constantes de compilación (659 offsets, invariantes entre 4k y 8k); las
  activaciones escalan con la resolución. La tabla de 128 registros no es un
  directorio de esos offsets.
- Primer candidato a portar: `mlfi_4k_pass26` (`0xf7cde0`, `32x1x4`, 9
  `MulAcc` F16).

## Factibilidad del puerto

- Gate ML: la DLL carga `amdxc64.dll` dinámicamente y consulta
  `AmdExtD3DCreateInterface` (sitios RVA `0x6d7b` y `0xfe250`); no hay checks
  de vendor ID. En Intel cae al FG analítico.
- En vkd3d-proton sin WMMA, los pipelines con AGS fallan en
  `d3d12_device_validate_shader_meta`: nunca llegan a ANV, así que el bridge
  CMK del upscaler no puede interceptarlos. Los kernels XMX del upscaler
  vinieron de nitec; este puerto requiere escribirlos.
- lavapipe solo expone 8x8x8 sin FP8: la referencia tiene que ser un
  intérprete en CPU de DXIL+AGS con el blob FP16.
- Detalle local: `analysis/fg-401-static/port-feasibility.md`.

## Límites

- No se probó qué buffer liga el bloque de pesos a cada pase; REA abrió el PE
  pero devolvió `provider_unavailable` en referencias cruzadas.
- La tabla de 128 registros no cierra con el tamaño del payload.
- 52 shaders no se pudieron desensamblar con `llvm-dis`; ninguno contiene el
  UAV mágico (búsqueda por bytes).

## Reproducción

```sh
python3 -I tools/build_fg_inventory.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/inventory.json
python3 -I tools/ags_wmma_census.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/ags-wmma.json
```

`ags_wmma_census.py` y `mlfi_pass_map.py` re-ejecutados el 2026-11-22: salida
byte-idéntica.

```sh
python3 -I tools/mlfi_pass_map.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/pass-map.json
```
