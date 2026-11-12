# Recheck puente contra DLL 4.1.2 (estático, CPU-only)

Método: solo inspección estática. No se ejecutó la DLL, sin GPU/Wine/prefijos.
No se tocó `artifacts/original`, `upstream/`, juegos ni prefijos. No se modifica
ningún archivo existente: este doc es la única salida.

## Artefactos comparados

| Pieza | Vieja | Nueva 4.1.2 |
|---|---|---|
| DLL extraída | `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`, 25.779.712 B, SHA-256 `3eb08656…0eba08eba53` | `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`, 45.558.272 B, SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| Packs | 3 packs, 690 envelopes (`analysis/fsr-resources/manifest.json`) | 6 packs, 1.977 envelopes (`analysis/fsr-xmx-412/manifest.json`, doc `docs/xmx412-pack-envelope.md`) |
| Pack Xe2 40102 raw | — | `analysis/fsr-xmx-412/pack-40102.raw`, 23.682.325 B, SHA-256 `d88aa9d6…995e491`, 252 envelopes |

Comandos estáticos usados (lectura, sin ejecución):

```sh
python3 tools/inspect_dll.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
strings -a <dll> | grep -i -E "cachedblob|GetCached|blob|4.20.0|root ?sig|0028ZR|FNV1a64|igdext"
llvm-objdump -p <dll>   # solo tablas Import/Export, no ejecución
python3 -c "from tools.carve_spirv import carve; ..."       # sobre pack-40102.raw
python3 -c "from tools.parse_cm_payloads import parse; ..." # sobre pack-40102.raw
```

## API de extensiones y versión (aplica a 0002/0003)

Evidencia nueva (DLL 4.1.2, `strings -a` + `inspect_dll.py`):

- Mismo set INTC que la vieja, con y sin guion bajo (10 cadenas, idénticas):
  `INTC_D3D12_CheckFeatureSupport`, `INTC_D3D12_CreateComputePipelineState`,
  `INTC_D3D12_CreateDeviceExtensionContext`, `INTC_D3D12_GetCachedBlob`,
  `INTC_DestroyDeviceExtensionContext` (+ variantes `_INTC_*`).
- `requested=4.20.0` presente en DIAG y en 12 cadenas fail-stop
  (`Intel extension context 4.20.0 failed [for passN]`), byte-idénticas a la vieja.
- Resolución igdext idéntica: `Intel DX12 extension igdext64.dll could not be
  resolved with required exports.` + `... with required DX12 exports was not found
  beside DLL, system search, or DriverStore.` (sin cambios).
- Imports troncales sin cambios: `d3d12.dll:D3D12SerializeRootSignature`,
  `dxgi.dll:CreateDXGIFactory2`, `Cabinet.dll` ordinales 40/43/45,
  `bcrypt.dll:BCryptHash`. Solo lectura vía `llvm-objdump -p`.

Diferencias que NO tocan el puente INTC (se registran, no se parchean):

- Exports FSR 5 → 6: se añade `OptiPluginInit` (ordinal 1; `ffx*` se recorren).
  Es entry de plugin OptiScaler, no un export INTC; el shim usa igdext, no `ffx*`.
- Nuevo import `USER32.dll:MessageBoxA` (antes ausente) + altas menores en
  KERNEL32 (`CreateThread`, `GetLocalTime`, `GetTickCount64`,
  `SetEnvironmentVariableA`; baja `FormatMessageW`) y CRT (`ceilf/exp2/logf/sqrtf`,
  `atof/atoi`, `realloc`, `strncmp`, `_putenv_s`, `__stdio_common_vsprintf`).
  Riesgo solo ambiental (diálogos en prefijo headless), sin efecto en los parches.

## GetCachedBlob (pregunta: ¿pasó a obligatorio?)

Evidencia nueva: las 4 cadenas blob son byte-idénticas vieja/nueva:

- `INTC_D3D12_GetCachedBlob` / `_INTC_D3D12_GetCachedBlob` (resolución dinámica).
- `[FSR4 XMX] PRE stage-2 dump unavailable: INTC_D3D12_GetCachedBlob export missing.`
- `[FSR4 XMX] PRE stage-2 GetCachedBlob failed: hr=0x%08X blob=%p.`
- `[FSR4 XMX] PRE stage-2 blob: hr=0x%08X bytes=%zu FNV1a64=0x%016llx file='%s' write=%s.`
- Más `PRE stage-2 dump path is too long; dump skipped.` (idéntica).

Ninguna lleva `fail-stop will trigger` (a diferencia de las 14+14 de
create/serialize root signature y las 12 de contexto). Sigue siendo ruta de
diagnóstico/dump stage-2 con tolerancia a `export missing` y a `hr` fallido.
Veredicto: **mantener** `E_NOTIMPL` del shim (`shim/src/dll/D3D12Api.cpp:120-124`
según `docs/compatibility.md:47`). Sin cambio.

## Root signature b0 + 11 tablas + sampler (pregunta DIAG/FNV)

Evidencia nueva:

- `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB
  physical heap slots retained.` — byte-idéntica vieja/nueva.
- `[FSR4 XMX DIAG] PRE root signature serialized bytes=%zu FNV1a64=0x%016llx
  rootParameters=%u flags=0x%X.` — byte-idéntica vieja/nueva.
- Conteos create/serialize root signature idénticos: 14 `Failed to create ...`,
  14 `Failed to serialize ...`, más `root signature creation/serialization failed`.
- `PRE sampler heap creation failed` y `PRE Intel capabilities ... OPTIONS1/OPTIONS2 ...`
  idénticas; `CheckFeatureSupport` audit-missing idéntica.

Lectura: el supuesto del perfil revisado (b0@0 + 11 superficies en 4..44 +
sampler en 48 en heap separado, `profiles/fsr4-pre-native1080-bmg.json`,
`docs/offline-pre-compilation.md:54-76`) **sigue válido para ese PRE viejo**
porque la DLL nueva no contradice la ABI declarada. Pero la cadena DIAG solo
prueba observabilidad futura (bytes + FNV + `rootParameters` + `flags` logueables),
no la geometría: no fija ningún número en estático.
Veredicto: **mantener** lector/mapa para el hash revisado; para la 4.1.2 exigir
log DIAG real con `rootParameters==13` esperado (1 constante + 12 tablas) antes de
afirmar que la geometría se conserva. Sin cambio de parche.

## Geometría base-4/push-52 (pregunta: ¿sigue válida en 4.1.2?)

Evidencia nueva (estática, packs ya descomprimidos):

- Nuevo 40102: 252 envelopes, 14 familias × 18 variantes, mismos nombres
  (`fsr4_pre_xmx`, `p1/p2_h1_hybrid`, `p3_xmx_n32`, ... `post_xmx`) y mismo trailer
  `-vc-payload -Xfinalizer '-noDPASMacro' -target-features=+ocl_runtime`.
- PERO el contenido PRE cambió: IR `358.776` B × 18 ( SHAs `49e069fd…`,
  `20096eef…`, …) frente a IR vieja `330.108` B (`1d10c34e…`, envelope
  `76942f6c…`). Con `tools/parse_cm_payloads.py`: **0 de 252** envelopes nuevos
  igualan al `envelope_sha256` del registry (`76942f6c…`), y **0** igualan la IR
  vieja. El `code_sha256 2e42d33c…` / `input_sha256 76942f6c…` /
  `zebin_sha256 3e974d57…` de `profiles/registry.json` no aparece en el pack nuevo.
- Conclusión: el pack nuevo trae otra geometría binaria no revisada (tamaño distinto;
  BTI/orden sin auditar para este binario). El lector CMK3 no puede heredar
  `table_pc_base=4` / `expected_push_size=52` / `surface_count=11` a ciegas.

## Tabla supuesto → evidencia-nueva → veredicto por parche

### `patches/0002-shim-context-output.patch` (doc `docs/context-output-fix.md`)

| Supuesto del puente | Evidencia nueva 4.1.2 | Veredicto |
|---|---|---|
| DLL pide `RequestedExtensionVersion 4.20.0` vía `INTCExtensionInfo(192B)→Info1(200B)` | DIAG `requested=4.20.0 … GTGen/EU/gpuMHz/TDP/fillRate` + 12 fail-stop `4.20.0` idénticas; sin nueva versión | **mantener** |
| Helper copia 7 device-info + 3 driver outputs solo en éxito; D3D11/`Context2` fuera de alcance | Mismos strings de fallo de contexto; sin nuevo export de contexto; import `D3D12SerializeRootSignature` único e igual | **mantener**, sin regenerar |
| `InitExtensions` rellena outputs; el stub los modela | Sin cambio observable en estático; los Asserts CPU 192/200 del parche siguen siendo la guarda | **mantener** |

### `patches/0003-shim-context-reuse.patch` (doc `docs/context-reuse-fix.md`)

| Supuesto del puente | Evidencia nueva 4.1.2 | Veredicto |
|---|---|---|
| Reuso early-`S_OK` sin refrescar existe en shim (no en DLL) | Cadenas de reuso/diagnóstico idénticas (`PRE diagnostic fresh CreateDeviceExtensionContext`, `fresh context destroy`, `NEVER DISPATCHED`, `W0 Quarantined…no slot reuse`); sin nueva semántica de reuso en la DLL | **mantener** |
| Contrato: misma device → `S_OK` + refresh; versión mayor → `E_NOINTERFACE`; distinto device → `E_INVALIDARG`; sin rebind | Sin nuevos códigos ni exports de contexto; `DestroyDeviceExtensionContext` igual; fail-stop de contexto igual | **mantener**, apilado 0002→0003 |
| Refresh re-ejecuta `InitExtensions` en el half vivo y restaura `m_SupportedExtVersion` | Sin evidencia en contra en strings/imports; DIAG de contexto loguea el contrato otorgado (`returnedDriverBuild/driverDesc/driverVersion…`) | **mantener** |

### `patches/0001-anv-cmk3-explicit-mapping.patch` + `profiles/registry.json` (docs `docs/profile-selection-cache-identity.md`, `docs/offline-pre-compilation.md`)

| Supuesto del puente | Evidencia nueva 4.1.2 | Veredicto |
|---|---|---|
| `table_pc_base=4`, `expected_push_size=52`, 11 superficies, sampler separado (solo PRE `native_1080` hash `2e42d33c…`) | Nuevo 40102 PRE = 18 IRs de 358.776 B, ninguna iguala IR/envelope registradas; geometría nueva sin compilar/auditar | **cambiar-proceso, no código**: NO extender registry; NO reutilizar base-4/push-52 fuera del hash revisado |
| Lector CMK3 valida: magic `CMK3`, flags==1, `nsurf 1..24`, base alineada, push exacto + cobertura por rangos; CMK2 intacto | Sin cambio en la DLL que invalide esas guardas; packs nuevos (Lite 378, DLSS-K 716, E/F 312, MX 67: `k_gemm/k_linear/e_conv/m_layer…`) nunca hacen hit por hash | **mantener** lector y límites tal cual |
| `registry_gen()=0x912cda6a` invalida cachés al cambiar registry | Registry intacto (1 entrada); digest sin cambio necesario | **mantener**; cualquier alta futura debe pasar por `tools/build_anv_mapping_patch.py` (bump automático) |
| Efecto global nulo: miss → legado CMK2 | Confirmado por diseño hash-gated; la 4.1.2 no añade superficies al perfil revisado | **mantener** `experimental-offline-only`, sin runtime |

## Cambios concretos propuestos (NO aplicados, sin commit)

1. **0002 / 0003: no tocar.** Solo re-verificar determinismo cuando corresponda:
   `python tools/build_context_output_patch.py`,
   `python tools/build_context_reuse_patch.py` + `patch -p1` 0002→0003 en árbol
   aislado + `python -m unittest tests.test_context_output tests.test_context_reuse -v`.
   No hay evidencia nueva que exija reescribir el helper ni el contrato de reuso.
2. **0001 / registry: no tocar.** Mantener 1 entrada (`PRE 4.0.2x native_1080`,
   `code 2e42d3…`, base 4, push 52) y el digest `0x912cda6a`. El lector sigue
   rechazando por magic/flags/nsurf/cobertura; lo desconocido (toda la 4.1.2 y los
   packs DLSS K/E/F/MX) cae a CMK2 por miss.
3. **Para soportar la 4.1.2 (hito separado, CPU-only):** compilar offline el candidato
   `native_1080` del nuevo 40102 con el toolchain fijado
   (`profiles/intel-toolchain.json`: IGC `2.10.10+18926`, ocloc `25.18.33578.6`,
   device `0xe20b`), inspeccionar BTIs con `tools/inspect_zebin.py`, generar un
   **nuevo** fichero de perfil (no editar el viejo) vía `tools/build_pre_profile.py`,
   añadir **nueva** entrada al registry con sus `code/input/zebin_sha256` propios,
   regenerar con `tools/build_anv_mapping_patch.py` (bump de cache identity) y
   extender `tests/test_profile_selection.py` con la nueva fila `(base,push)`;
   prohibido copiar base-4/push-52 al nuevo hash sin esa auditoría.
4. **Antes de cualquier runtime:** capturar los DIAG nuevos
   (`PRE extension context=…`, `PRE root signature serialized … rootParameters …
   flags=…`, `PRE PSO request …`) y exigir `rootParameters==13` y bytes/FNV
   estables más readback GPU determinista; `S_OK`/magenta/falta de fail-stop no
   bastan (criterio `docs/compatibility.md:103-108`). `GetCachedBlob` sigue sin
   ser gate: un `hr` fallido o `export missing` solo debe loguear dump, nunca
   fail-stop.
5. **Nota ambiental (solo docs, sin parche):** registrar `OptiPluginInit`,
   `USER32!MessageBoxA` y las cadenas `nvngx_dlss.dll` / `fsr-original.dll` /
   variantes `Skip/Hybrid/QSkip` + `4.1.2X` como consideraciones de prefijo headless
   y de pesos no verificados; no cambian el puente INTC/CMK3.

## Límites de esta revisión

Strings + imports + docs/packs; sin desensamblado nuevo, sin compilar el PRE nuevo,
sin ejecutar DLL ni driver. La identidad de versión/API es evidencia de compatibilidad
del contrato, no prueba de corrección GPU ni de layout. La geometría de la 4.1.2 queda
expresamente **no validada** hasta el hito 3–4.
