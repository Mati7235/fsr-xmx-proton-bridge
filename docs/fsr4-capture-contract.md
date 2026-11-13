# FSR 4 XMX: contrato de captura para validacion real (RenderDoc + readback)

Solo estatico, CPU-only. DLL del mod leida como datos, sin cargarla ni ejecutarla:
`artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
(SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`,
45.558.272 bytes). Sin GPU, Wine, Proton, RenderDoc sobre proceso real ni
prefijos tocados. Cada afirmacion sale de una fuente leida; lo no determinable
se marca como tal.

Fuentes: `docs/xmx412-model-selection.md`, `docs/xmx412-dispatch.md`,
`docs/xmx412-packs.md`, `docs/xmx412-static-inventory.md`,
`docs/pre-resource-descriptors.md`, `docs/pre-dispatch-dimensions.md`,
`docs/manual-image-test.md`, `docs/first-image-gpu-result.md`,
`docs/spiderman-trace-runbook.md`, `docs/first-runtime-trace-412.md`,
`tools/inspect_dll_412.py`, `tools/inspect_pre_dispatch.py`,
`tools/inspect_pre_inputs.py`, `tools/reconstruct_pre_resources.py`,
`build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/evidence/vkd3d-trace3-20261113.log`
y `.../results/ciudad1-int8-20261113-125925/vkd3d.log`.
Cadenas verificadas por lectura directa del binario (ASCII y UTF-16LE, nota 1).

## 1. Facilidades de debug del mod: que hay y que escribe

No existe dump de imagenes. No hay writer PNG/DDS/BMP/JPG ni `SaveTexture`:
las busquedas solo devuelven fragmentos (`OpngK~`, `ndds`, `abmp`, sin nombre
de API ni ruta de salida). Lo unico que el mod escribe a disco son tensores
`.bin`, un `.csv` de paridad, SPIR-V de fallo y blobs de stage-2. Los canales
de texto son `OutputDebugStringA/W` (importados), `MessageBoxA` (solo aviso de
GPU sin XMX, ver `docs/xmx412-static-inventory.md:57-87`) y el log de Proton.

| Variable / interruptor | Que hace | Que escribe y donde |
|---|---|---|
| `FSR4_XMX_DEV=1` | Desbloquea pestana Developer, Version list, `HiddenEntries`, `Profile` (`docs/xmx412-model-selection.md:191-194`, `0x18006FD90`) | Nada a disco por si solo; habilita UI y vistas |
| `FSR4_XMX_FS_DIAG` (leida con `atoi` en `FUN_180068CF0`; no existe `FS_DIAG` sola; `docs/xmx412-model-selection.md:442-446`) | `0/2/4` = skip rules como colores; bit 8 = stats (`docs/xmx412-model-selection.md:436-440`) | Cadenas `FSR4_XMX_FS_DIAG=`, `=2`, `=4`; `Skip rules as colours`; `[FSR4 XMX] %s This frame shows magenta (logged once)`; `[FSR4 XMX FATAL] %s Stock fallback is disabled; diagnostic magenta will be shown` |
| Oracle por pase `FSR4_XMX_P1/P2/P3/P4/P5/P7/P8/P9/P10/P11/P12_OracleCaptureReadback` (nombres UTF-16LE en DLL) + `FSR4_P10_U1_OracleCaptureReadback`, con dirs `MLSR-XMX-PASS*-ORACLE-DUMP`, `MLSR-P10-U1-ORACLE-DUMP` | Captura one-shot con buffer de readback GPU tras completar: `One-shot capture armed: dir=%s ...`, `Capture copy scheduled; files will be written after GPU completion`, `CAPTURED input=%llu bytes FNV1a64=... output=...` | `%s\p1_input.bin` + `%s\p1_output.bin` (igual P2..P5, P10..P12); P7/P8: `input` + `stage2`; P9: `input`, `skip`, `stage2`, `stage3` (`%s\p9_input.bin`, `%s\p9_skip.bin`, `%s\p9_stage2.bin`, `%s\p9_stage3.bin`); P10U1: `%s\p10_input.bin` + `%s\p10_output.bin`. Fallos: `Failed to create/map readback buffer`, `Dump directory path is ...`, `Failed to write capture files` |
| Paridad PRE `MLSR-XMX-PRE-PARITY`, `-TRIGGER`, `-DIR`, `MLSR-XMX-PRE-HOSTPARITY`, `MLSR-XMX-PRE-POSTSTORE-PARITY` | Compara bytes del tensor PRE XMX contra PRE stock en el mismo equipo; `Trigger observed; multi-frame capture armed` | `%ls\pre_parity_%04u.bin` + `%ls\pre_parity_summary.csv`; logs `frame=%u EXACT: 8294400/8294400 PRE tensor bytes match stock. reset=%u jitter=...`, `BYTE-MISMATCH` / `mismatchGroups=... maxAbs=... sumAbs=... first=(x y c stock xmx) reset jitter mvScale jitterCancel flags`, `HOSTPARITY ... BYTE-EXACT/BYTE-MISMATCH ... stockHash xmxHash`, `Ring full; capture frame skipped`, `TELEMETRY-INVALID: zeroRecords=... Do NOT classify this frame as BYTE-EXACT` |
| Dump de entrada fallida `MLSR-XMX-PRE-DUMP-FAILED-INPUT` | Vuelca el SPIR-V seleccionado cuando falla | `[FSR4 XMX DIAG] PRE failed selected SPIR-V dump file='%s' bytes=%zu write=%s`; `PRE failed-input dump path too long; dump skipped` |
| Dump stage-2 `MLSR-XMX-PRE-DUMP-STAGE2`, `fsr4_pre_xmx_stage2.bin` | Vuelca el blob compilado via `INTC_D3D12_GetCachedBlob` | `[FSR4 XMX] PRE stage-2 GetCachedBlob failed: hr=...`; `PRE stage-2 dump unavailable: ... export missing`; `PRE stage-2 dump path is too long` |
| Perfiles `MLSR-PROFILE*`, `MLSR-XMX-PRE-STAGE-PROFILE`, `PASS7/8/9-STAGE-PROFILE`, `MLSR-PROFILE-WHOLE`, `MLSR-PROFILE-PERIOD/SAMPLES`, `PRE PROFILE` | Tiempos por region con timestamp queries, no pixeles | `[FSR4 XMX PRE PROFILE] n=%u diag=%u mode=%s total=... resources=... params=... constants=... bind=... xmx=... post=...`; `[FSR4 WHOLE PROFILE] ... scope=pre..post`; fallos `Failed to create ... query heap/readback buffer/...; disabled` |
| Overrides de parametros `FSR4_XMX_PRE_Params`, `FSR4_XMX_PRE_ParamsUpload`, `FSR4_XMX_Pass1..12_Params`, `EMBED_PRE/Pass6..9_Params`, `Post_Params`, `Post_Constants`, `Pass6_PackedWeights` (UTF-16LE) | Nombres de entorno para params/pesos por pase | Semantica exacta no determinada estaticamente; solo presencia de nombres. No usar sin leer el call-site |
| `r_debug_visualization`, `rw_debug_visualization`, `debug`, `MLSR-PIX-DLL`, `MLSR-PIX-MARKERS` | Nombres de recursos/marcadores, no salida a archivo | Sin ruta ni writer asociados en las cadenas. `WinPixEventRuntime` solo se menciona para pedir su ruta |

Nota 1: metodo de verificacion de cadenas, solo lectura como datos:

```bash
python3 -c "
import re
data=open('artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll','rb').read()
asc=set(m.decode('ascii') for m in re.findall(rb'[\x20-\x7e]{4,}',data))
u16=set(m.decode('utf-16le') for m in re.findall(rb'(?:[\x20-\x7e]\x00){4,}',data))
s=asc|u16
for k in ['FSR4_XMX_FS_DIAG','ORACLE-DUMP','pre_parity','PRE-DUMP','r_debug_visualization']:
    print(k, sum(1 for x in s if k in x))
"
```

## 2. Contrato de las 8 imagenes + salida del PRE/red

Base: `tools/inspect_pre_inputs.py:13-60` (12 args del entry `fsr4_pre_xmx`,
 Tipos `BufferSurfaceINTEL ReadWrite`, `Image 2D ReadOnly/ReadWrite formato Unknown`,
 `Sampler`) y `docs/pre-resource-descriptors.md:26-40`
(mapa arg/root/heap contratastado con `ze_info.yaml` y SPIR-V).
Retencion en 4.1.2: mismos 10 nombres stock, mismas multiplicidades wide,
misma grilla y mismos slots de vtable salvo un `+0x78` extra
(`docs/xmx412-dispatch.md:113-137,203-243`).
Helper reescrito en 4.1.2: traductor `0x18000bbd0` (198 B) + barrera
`0x180027bc0` (57 B); heap ya no sale de `ctx+0x1b40` sino de
`0x38f0/0xa78/0x4920/0x4910/0x3910` (`docs/xmx412-dispatch.md:180-201`).

| Arg | Root / registro | Slot heap relativo | Clase en firma | Formato y tamano |
|---:|---|---|---|---|
| 0 (scratch mixto) | 1 / u0 | recursos / 7 | UAV `BUFFER`, `R8_UINT` (`0x3E`), `FirstElement=0`, `NumElements = Width` | `GetDesc` exige `Dimension == BUFFER (1)`; cota inferior `Width >= factor^2 * 0x7e9000`; para `native_1080` factor 1: minimo **8.294.400 bytes**. Width exacto es runtime. Ver `docs/pre-resource-descriptors.md:47-76`, `docs/xmx412-dispatch.md:158-170` |
| 1 (destino) | 2 / u1 | recursos / 8 | Image2D ReadWrite | Descriptor copiado con `CopyDescriptorsSimple`; formato y dimensiones fuente no recuperados en esta secuencia |
| 2..8 (t0..t6, 7 entradas) | 3..9 / t0..t6 | recursos / 0..6 | Image2D ReadOnly | Descriptores copiados por helper; indices fuente elegidos en runtime (`[rsp+0x78]`, `[rsp+0x7c]`, `esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx` en la 4.0.2; revalidar call-sites 4.1.2). Formato/dimensiones no fijados |
| 9 | 10 / t7 | recursos / 9 | SRV `BUFFER`, `R8_UINT`, map `0x1688`, first 0, **0x840 = 2.112 bytes** | Recurso de `ctx+0xa80`; vista fija 2.112 B; backing y contenido son runtime |
| 10 (header) | 11 / t8 | recursos / 10 | SRV `BUFFER`, `R8_UINT`, map `0x1688`, first 0, **0x80 = 128 bytes** | Recurso de `ctx+0xa98`; el kernel lee 128 B (DWORDs 8..84, dir/bytes 64..80, flag byte 100, base byte 104; bit `0x400` guard, `0x2000` elige `base` o `base+16` como offset en arg 0). Ver `docs/pre-resource-descriptors.md:78-90` |
| 11 (sampler) | 12 / s0 | heap sampler / 0 | Sampler | MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, ALWAYS, MinLOD 0, MaxLOD FLT_MAX |
| push constants | root 0 | no aplica | `SetComputeRoot32BitConstant(root 0) = 0` (`b0=0`); opcodes `FF 90 08 01 00 00` 1 vez; `FF 90 F8` 3 veces, `Dispatch` 2 veces (`docs/xmx412-dispatch.md:203-243`) | Constantes incompletas (`<0x20` en `0x250e9..0x250f5`) o ABI (`consts+100`, altos `0x5058`, `docs/xmx412-dispatch.md:139-170`) disparan fail-stop, no dispatch parcial |

Reglas para reconocer cada recurso en RenderDoc (no hay nombres de recurso):
formato de vista + tamano visible + orden de binding + push constants.
Para imagenes el formato DXGI/VK, dimensiones y strides **no se pueden fijar
estaticamente**: el SPIR-V declara `Unknown`, los descriptores se copian y la
fuente es runtime (`docs/pre-resource-descriptors.md:172-190`,
`tools/inspect_pre_inputs.py:116-121`). La primera captura debe registrar por
ID de recurso y descriptor: `D3D12_RESOURCE_DESC` completo, cada
`CreateSRV/UAV` y `CopyDescriptors*`, handles GPU de las 11 tablas + sampler,
grid de `Dispatch` y bytes pre y post de args 0/9/10
(`docs/spiderman-trace-runbook.md:151-168`,
`docs/pre-resource-descriptors.md:192-225`).

## 3. Como identificar el dispatch del upscaler en la captura

1. Es un dispatch de compute con grid derivada de la entrada:
   `x = (w+15)>>4; x += x&1; y = h>>1` (`docs/xmx412-dispatch.md:64-90`).
   Para `w=1920,h=1080`: **`(120, 540, 1)`**. Cadenas `baseDispatch=120x540x1`
   (tambien `60x270x1`, `30x135x1/2`) en la DLL lo confirman.
2. Modos (funcion `0x18002bed0`, 145 B; call en `0x25a3e`):
   modo 2,3 = return 1 sin dispatch; 4 = `(1,1,1)`; 5 = `(x,1,1)`;
   6 = `(x,0x44,1)`; resto = `Dispatch(x,y,1)` en `0x26394` y `0x263c9`
   (`docs/xmx412-dispatch.md:91-111`).
3. Firma de binding: 11 tablas efectivas (roots 1..11: u0, u1, t0..t6, t7,
   t8) + sampler en root 12, `root0 = 0`
   (`docs/spiderman-trace-runbook.md:151-168`). El resto de dispatches del
   juego no presenta esa combinacion grid + 12 roots + `b0=0`.
4. Kernel CM: entry `fsr4_pre_xmx`, pack 40102 record 0, `ir_size` 358.776,
   envelope 358.873, `ir_sha256 49e069fd...`, envelope `ce372719...`
   (`docs/xmx412-packs.md:69-90`, `docs/spiderman-trace-runbook.md:9-21`).
   En el log runtime aparece como `dyn_60.spv` (358.873 B) = kernel
   `e8fca351200197b3`, con una diferencia de 3 bytes en offset 59112..59114
   (`OpConstant float 68.45...` offline vs `67.18...` runtime: parche por
   dispatch del mod, no corrupcion) y compilacion ANV posterior
   (`docs/first-runtime-trace-412.md:47-62,73-86`).
5. Lineas ANV que lo delatan en `vkd3d-trace3-20261113.log:1298-1305`:
   `compiling kernel e8fca351200197b3 (dyn_60.spv)`, `placeholder wg 61,1,7`,
   `set 0: type 1 bindings 1 descriptors 2048`,
   `set 1: type 1 bindings 3 descriptors 1000002`,
   `samples but the pipeline layout has 0 static samplers`,
   `sampler descriptor table after the surfaces (sampler heap found)`,
   `heap set 1 binding 2: descriptor offset 128 stride 64`,
   `injected ... (30464 bytes code, 128 GRF, lws 1,1,1)`.
   El `placeholder wg 61,1,7` es selector del packer, no geometria del shader
   (`docs/pre-dispatch-dimensions.md:38-52`).
6. Contexto de juego (no es prueba por si solo): overlay `FFX -> FSR 4.0.2`
   con upscaler 0.8..0.96 ms (vs ~2 ms sin XMX), UI perfecta, mundo 3D con
   ruido magenta/verde; `d3d12_resource_SetName: FSR4 resource detected`
   docenas de veces (`docs/first-runtime-trace-412.md:24-36`,
   `vkd3d-trace3-20261113.log:1285-1297`). El overlay muestra la etiqueta del
   proveedor, no el modelo ejecutado; el log (`INT8/Lite model ...`) manda
   (`docs/xmx412-model-selection.md:270-276,448-484`).
7. La corrida `ciudad1-int8-20261113-125925` inyecto 174 kernels
   (`summary.txt`), con 74 huellas unicas y `sampler-heap-ok: 6`; es evidencia
   de actividad XMX real, no de correccion.

## 4. Que permite cada nivel de evidencia y que no

| Nivel | Que permite afirmar | Que NO permite afirmar |
|---|---|---|
| Readback determinista (mismos bits entre corridas, `FNV1a64`, `pre_parity` EXACT 8294400/8294400) | Reproducibilidad de ese stack (mod + pesos + driver + LWS + sampler). Con `reset`/jitter/mvScale fijados y frames `TELEMETRY-INVALID` descartados, dos corridas identicas descartan no-determinismo accidental | Correccion funcional. La paridad compara XMX contra stock en la misma GPU Intel; ninguno es oracle AMD. Un buffer estable pero equivocado (p. ej. sampler fallback linear/clamp o layout auto 8 vs 4) sigue dando EXACT entre corridas |
| Comparacion contra referencia de upscaling (PSNR/SSIM) | Cercania perceptual con umbral declarado, si la referencia, el alineado (reset, jitter, crop, formato) y el plan de comparacion estan fijados | Bit-exactitud ni causa. Un PSNR alto con un solo frame no prueba otros presets, resoluciones ni determinismo |
| Sin oracle bit-exacto de FSR 4 sin hardware AMD | Honestidad metodologica: los pesos se verifican por contenido (FNV-1a64 de blobs `0x6B00`/`0x20000`, `docs/xmx412-model-selection.md:301-335`), el IR 4.1.2 difiere +8,7 % del viejo (`docs/xmx412-packs.md:84-90`), el runtime parchea una constante float y el driver recompila; no hay salida AMD de referencia en el repo | Cualquier afirmacion del tipo "el PRE es bit-exacto con FSR 4 oficial". `S_OK`, un PSO creado, el overlay o el timing no acreditan modelo ni pixeles (`docs/xmx412-model-selection.md:517-530`) |

Base de este criterio en docs: `docs/pre-resource-descriptors.md:226-231`
(captura de descriptores es evidencia de entrada, no oracle),
`docs/pre-dispatch-dimensions.md:83-103` (sin local size, mascara ni oracle no
se autoriza dispatch), `docs/manual-image-test.md` y
`docs/first-image-gpu-result.md` (el unico readback validado es el del kernel
sintetico 2x2 RGBA32F con error maximo 0.0 y 1.984 words centinela intactos;
no valida PRE ni FSR), `docs/first-runtime-trace-412.md:64-71` (el camino
mod→VKD3D→ANV funciona; bindings y causa del ruido sin confirmar).

## 5. Quedo indeterminado (no afirmable estaticamente)

- Formato DXGI/VK, dimensiones, mip/layer, sample count y strides de las 8
  imagenes (t0..t6 + destino). Requiere RenderDoc.
- Width exacto de arg 0 (solo cota inferior), backing y bytes iniciales de
  args 0/9/10, contenido del header de 128 B. Requiere captura pre/post.
- Local size, threadcount y mascara de ejecucion del dispatch PRE real
  (`docs/pre-dispatch-dimensions.md:38-103`). El `lws 1,1,1` del log ANV y el
  `placeholder wg` son decisiones del puente/packer, no contrato del shader.
- Semantica exacta de cada override `*_Params`/`*_Upload`, de los modos
  `FSR4_XMX_FS_DIAG` mas alla de colores/stats, y de `ASKIP/FRAMESKIP/MIDSKIP/
  LIST_SKIP`. Solo cadenas y un call-site documentado (`atoi` en
  `FUN_180068CF0`).
- Causa del ruido magenta/verde (candidatos: layout base auto 8 vs 4,
  sampler fallback, LWS; `docs/first-runtime-trace-412.md:81-86`). Sin
  captura de frame con formatos reales no se decide.
- Cualquier oracle de salida bit-exacta de FSR 4 (seccion 4).

## 6. Reproducir la base estatica

```bash
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
# fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory tests.test_xmx412_model_strings tests.test_xmx412_dispatch -v
python3 tools/inspect_pre_inputs.py analysis/fsr-resources/xe2-first.spvasm
```
