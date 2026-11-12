# PRE native_1080: spec de captura correlacionada para una futura traza autorizada

## Estado y alcance

Fase 1, CPU-only. Este documento **no autoriza** ningún dispatch PRE ni ninguna
ejecución GPU/Wine. Solo define qué debe registrar una futura traza autorizada
del caller (ruta `native_1080`) en un prefijo descartable, para resolver los
datos de runtime que el análisis estático no puede establecer: tamaños
asignados, formatos de imagen, bytes iniciales y valores efectivos del dispatch.

Contexto estático fijado (verificado localmente por SHA-256 el 2026-11-12):

| Artefacto | SHA-256 |
|---|---|
| DLL `amd_fidelityfx_upscaler_dx12.dll` | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` |
| `analysis/fsr-xmx-disassembly.txt` | `4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0` |
| `d3d12.h` local (LLVM-MinGW) | `23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e` |
| `dxgiformat.h` local | `8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48` |
| envelope CM PRE (`cm-payloads-0001/module-0000.cmspv`) | `76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b` |
| zebin PRE Xe2 (`offline-pre/full/pre_bmg.bin`) | `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2` |
| código nativo (`code_sha256` del perfil) | `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f` |
| `offline-pre/full/ze_info.yaml` | `5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c` |
| desensamblado IGA `.text.fsr4_pre_xmx` | `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660` |
| IR `fsr-resources/xe2-first.spvasm` | `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e` |

Referencias de análisis: dispatch y procedencia en
[`pre-dispatch-ghidra.md`](pre-dispatch-ghidra.md) (función `FUN_1800163c0`,
fórmula de grid, bindings stock por nombre, fail-stops, helper `0x180002df0`,
vtables contra `d3d12.h`); contrato en
[`pre-controlled-test-contract.md`](pre-controlled-test-contract.md); vistas
tipadas en [`pre-resource-descriptors.md`](pre-resource-descriptors.md).

## Objetivo de la traza

Registrar, correlacionado por ID de recurso/descriptor, todo lo que la ruta
normal `0x1800163c0..0x180017b6e` consume justo antes del primer dispatch PRE
`native_1080`, y volcar bytes pre/post sin modificar el estado observado. La
traza es evidencia de entrada, no oracle funcional ni prueba de corrección.

## Mapa de slots que la traza debe resolver

Slots relativos al heap/tabla que usa la ruta normal (no índices absolutos):

| Slot heap recursos | Arg | Root | BTI | Contenido esperado (estático) |
|---|---|---|---|---|
| 0–6 | 2–8 / t0–t6 | 3–9 | 1–7 | imágenes ReadOnly, copiadas por helper `0x180002df0`; source index en runtime |
| 7 | 0 / u0 | 1 | 8 | UAV `R8_UINT BUFFER`, `NumElements = Width` (`GetDesc` exige `Dimension == 1`) |
| 8 | 1 / u1 | 2 | 9 | imagen destino ReadWrite, copiada en `0x18001727e` |
| 9 | 9 / t7 | 10 | 10 | SRV `R8_UINT BUFFER`, `NumElements = 0x840` (2.112 B), recurso en contexto `+0xa80` |
| 10 | 10 / t8 | 11 | 11 | SRV `R8_UINT BUFFER`, `NumElements = 0x80` (128 B), recurso en contexto `+0xa98` |
| heap sampler 0 | 11 / s0 | 12 | — | sampler linear/CLAMP (ver §6) |

Además `SetComputeRoot32BitConstant(rootIndex=0, value=0, destOffset=0)`:
**b0 = 0**; y `SetComputeRootDescriptorTable` 1…11 desde el array RVA
`0x68988` (`0x180017410..0x180017435`), root 12 con handle GPU del heap sampler
(`0x180017543`).

## Bloques de captura (todos correlacionados por ID)

### 1. Creación de recursos

Por cada recurso enlazado a los slots 0–10, registrar el evento de creación
efectivo (`CreateCommittedResource`, placed/reserved o importación):

- `D3D12_RESOURCE_DESC` completo: `Dimension`, `Width`, `Height`,
  `DepthOrArraySize`, `MipLevels`, `Format`, `SampleDesc`,
  `Layout`, `Flags`.
- `D3D12_HEAP_PROPERTIES` + `D3D12_HEAP_FLAGS`, tamaño y offset de asignación
  cuando aplique.
- ID de recurso (puntero de objeto + secuencia de creación) que se usará para
  correlacionar vistas, copias y barriers. Seguir aliases y copias, no solo
  direcciones de handles.

### 2. Vistas y copias de descriptores

- Cada `CreateShaderResourceView` / `CreateUnorderedAccessView`: recurso
  asociado (ID del §1), `D3D12_*_VIEW_DESC` completo (formato, dimensión,
  `FirstElement`, `NumElements`, `StructureByteStride`, `Flags`,
  `Shader4ComponentMapping`), mip/layer/rango, slot destino y heap.
- Cada `CopyDescriptors*` (incluido el helper `0x180002df0` y el sitio
  `0x18001727e`): heap origen, índice origen, incremento de descriptor,
  heap destino, slot destino 0–10, y el ID del recurso que el descriptor
  origen designaba. Para t0–t6 anotar además el registro de selección
  (`[rsp+0x78]`, `[rsp+0x7c]`, `esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx`).
- Valores fijados que deben coincidir: arg 9 SRV `R8_UINT`, `0x1688`,
  `0x840`; arg 10 SRV `R8_UINT`, `0x1688`, `0x80`; arg 0 UAV `R8_UINT`,
  `FirstElement = 0`, `NumElements = Width`. Cualquier desviación se registra
  como hallazgo, no se "corrige" la spec.

### 3. Identidad pre-dispatch (`GetDesc` y resolución de handles)

Justo antes del dispatch, para cada heap slot 0–10:

- `GetDesc` del recurso enlazado (el mismo `+0x50` que la DLL usa para arg 0).
- Resolución handle CPU/GPU → ID de recurso del §1; detectar aliasing
  (dos slots al mismo recurso) y descriptores obsoletos.
- Para arg 0, verificar la guarda estática: `Dimension == 1` y
  `Width >= factor² * 0x7e9000` (native_1080: factor 1, mínimo 8.294.400 B),
  `Width <= 0xffffffff`. Registrar el `Width` efectivo: es el tamaño que
  dimensiona el UAV, no suponer asignación exacta.

### 4. Bytes de buffers: arg 9, arg 10 y regiones de arg 0

- Arg 10: header completo de 128 B tal cual lo carga el kernel, con bytes
  legibles y flags originales. Campos usados por el IR (offsets 8–84 DWORDs,
  dirección/bytes en 64–80, flags byte 100, base en byte 104). La base de
  byte 104 es **desplazamiento relativo al buffer arg 0** condicionado por el
  bit `0x2000` (`base` frente a `base+16`), no una VA.
- Arg 9: los 2.112 B visibles por el SRV.
- Arg 0: como mínimo el registro float4 de 16 B en `base + {0,16}` y el plano
  de escritura OWORD (`índice = wg_y*960 + wg_x*8`, 16 B por OWORD, extremo
  exclusivo 8.294.400 B para grid 120×540). Recomendado: volcado completo
  pre/post del backing resource, ya que contiene regiones de entrada/scratch
  y salida cuyas relaciones exactas dependen del header arg 10. No
  inicializarlo como buffer vacío de readback.
- Volcar pre **y** post dispatch sin modificar el estado observado; preservar
  la captura original íntegra.

### 5. Handles GPU, bases e incrementos

- `GetGPUDescriptorHandleForHeapStart` de ambos heaps (recursos y sampler),
  bases CPU/GPU, `GetDescriptorHandleIncrementSize` por tipo de heap.
- Tabla root efectiva: los 11 handles GPU pasados a
  `SetComputeRootDescriptorTable` + handle del sampler a root 12, con la
  correspondencia slot→arg→BTI de la tabla de arriba.
- Incremento origen usado por el helper (`ctx+0x1b40` + `sourceIndex *
  incremento`).

### 6. Descriptor del sampler

`D3D12_SAMPLER_DESC` completo del slot 0 del heap sampler: valores estáticos
esperados MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, `MaxAnisotropy` 1,
comparación ALWAYS, `MinLOD` 0, `MaxLOD` FLT_MAX. Registrar cualquier
desviación y el heap/tabla reales usados en root 12.

### 7. Secuencia de contexto y blobs

- Frontera pública: `ffxCreateContext` (`0x180001290`), `ffxDispatch`
  (`0x1800013b0`), `ffxQuery` (`0x180001400`); wrapper interno
  `0x1800058a1..0x1800058e6` y sitio llamante `0x1800058be`
  (`rcx=estado, rdx=registro, r8=interfaz D3D12`).
- Registrar si el dispatch PRE **reutiliza** un contexto/dispositivo/cola ya
  creado (limitación conocida del parche de contexto, ver
  [`context-output-fix.md`](context-output-fix.md)) o crea uno nuevo, y con
  qué parámetros (`CreateDeviceExtensionContext` 4.20.0,
  `CheckFeatureSupport` OPTIONS1/XMX y OPTIONS2/SIMD16Required).
- Registrar llamadas a `GetCachedBlob` y su resultado (en el shim de
  referencia es E_NOTIMPL; su carácter obligatorio no está establecido).
- Registrar constantes/modelos observados (`4.0.2x`/`4.0.2xm`, lectura de
  `fsr-original.dll`) solo como procedencia, sin atribuir semántica.
- Registrar cualquier fail-stop emitido (cadenas en
  [`pre-dispatch-ghidra.md`](pre-dispatch-ghidra.md): params no listos,
  binding stock faltante, constantes incompletas, ABI `0x5058`, layout
  ScratchBuffer, geometría no disponible, anillo de paridad lleno).

### 8. Grid del dispatch y transiciones

- Argumentos de `ID3D12GraphicsCommandList::Dispatch`: fórmula estática
  `x = (w+15)>>4`, `x += x&1`, `y = h>>1` con `w = *(ctx+0x840)`,
  `h = *(ctx+0x844)`; para 1920×1080: `(120, 540, 1)`. Modos de
  `FUN_18001c9c0`: 2–3 → sin dispatch PRE; 4 → `(1,1,1)`; 5 → `(x,1,1)`;
  6 → `(x,0x44,1)`. Registrar `w/h` efectivos y el modo observado.
- `ResourceBarrier` con estados (`0x40`/`0x400`/`0x800`) alrededor de las
  copias, `SetDescriptorHeaps`, `SetPipelineState`, y estado/transiciones de
  cada recurso pre/post.
- El tamaño local CM/hardware y la máscara de ejecución **no** son argumentos
  de `Dispatch`: requieren evidencia separada del driver/launcher (ver
  [`pre-dispatch-dimensions.md`](pre-dispatch-dimensions.md)). No sustituirlos
  por `1×1×1`, `SubgroupSize 1` ni el selector Vulkan.

## Correlación por ID y preservación

- Cada fila de evidencia cita `resource_id`, `heap_id:slot`, evento y
  secuencia. Un handle sin ID de recurso correlacionado es captura incompleta.
- Nombres de stock wide observados (10, por procedencia, no por semántica):
  `MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
  `r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`,
  `r_depth`, `r_input_exposure`, `r_auto_exposure_texture`.
- Guardar bytes pre/post, captura original y versiones registradas
  ([checklist](pre-trace-version-checklist.md)) bajo `runs/<id>/evidence/`.
- No renombrar t0…t8 a color/depth/etc.; no reinterpretar el `7` de la
  máscara `.xyz` del store como binding; u1 (arg 1/BTI 9) es el destino del
  store, t6 (arg 8/BTI 7) no se convierte en UAV por ese store.

## Lo que esta captura no establece

Formato/contenido inicial de las 8 imágenes, oracle de salida PRE, corrección
funcional, equivalencia Proton/VKD3D ni validez de reutilizar estos valores
fuera del `native_1080` trazado. El criterio de aprobación sigue siendo el del
[contrato controlado](pre-controlled-test-contract.md).
