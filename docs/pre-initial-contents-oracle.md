# PRE native_1080: contenidos iniciales requeridos y oracle independiente (Fase 2, CPU-only)

Estado: spec cerrada en CPU. No se ejecutó GPU, DLL, juego ni prefijo.
No autoriza dispatch PRE. Todo lo marcado `TRACE_FASE1_REQUIRED` solo puede
venir de la traza Fase 1 (prefijo desechable, misma ruta `native_1080`).

Fijado por `tools/inspect_pre_initial_contents.py` + `tests/test_pre_initial_contents.py`:

```bash
python tools/inspect_pre_initial_contents.py analysis/fsr-resources/xe2-first.spvasm
python -m unittest discover -s tests -p test_pre_initial_contents.py -v
```

Hashes fijados: DLL `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`,
SPIR-V textual `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`,
zebin `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`.

## (a) Tabla de contenido requerido por recurso

Leyenda: ESTÁTICO = demostrado sin ejecutar nada; `TRACE_FASE1_REQUIRED` =
solo la traza del llamador puede fijarlo. No se inventan formatos ni semántica
de escena: t0…t6 nunca se nombran color/depth/motion.

| Recurso | Formato / permisos | Tamaño | Bytes iniciales | Valores deterministas válidos | Procedencia |
|---|---|---|---|---|---|
| arg0 u0 (root 1, BTI 8, heap slot 7, push 4) | `BufferSurfaceINTEL ReadWrite`; vista UAV `BUFFER R8_UINT`, `FirstElement 0`, `NumElements = Width`. Guard DLL: `Dimension == BUFFER (1)`, `factor²·0x7e9000 <= Width <= 0xffffffff`; native_1080 factor 1 → **mínimo 8.294.400 B** | Width runtime (≥ 8.294.400 B) | Traza: regiones de entrada/scratch + plano de escritura. No inicializar como readback vacío | Cualquier byte `0x00…0xFF` es válido para `R8_UINT`; los bytes reales de escena los da la traza | Vista ESTÁTICA; Width y bytes `TRACE_FASE1_REQUIRED` |
| arg1 u1 (root 2, BTI 9, heap slot 8, push 8) | `Image 2D ReadWrite`, `OpTypeImage … Unknown`. Descriptor copiado (`CopyDescriptorsSimple` en `0x18001727e`); destino del typed quad store (máscara `7` = canales `.xyz`, superficie `%9780` desde arg 1) | `TRACE_FASE1_REQUIRED` (`D3D12_RESOURCE_DESC` completa + `UAV desc`) | Traza pre-dispatch | Ningún filler definible antes de conocer formato/dims/mip/sample | Binding ESTÁTICO; formato/dims/contenido `TRACE_FASE1_REQUIRED` |
| arg2…8 t0…t6 (roots 3…9, BTI 1…7, heap slots 0…6, push 12…36) | `Image 2D ReadOnly`, `Unknown`. Siete copias vía helper `0x180002df0` con índices fuente runtime | `TRACE_FASE1_REQUIRED` por imagen | Traza pre-dispatch | Deben estar en rango del formato trazado; formato aún desconocido → sin filler fijado aquí | Pool de 10 nombres stock ESTÁTICO (lista abajo); asignación slot←nombre y formato/dims/contenido `TRACE_FASE1_REQUIRED` |
| arg9 t7 (root 10, BTI 10, heap slot 9, push 40; recurso `ctx+0xa80`) | CM `BufferSurface ReadWrite`; vista D3D SRV `BUFFER R8_UINT`, `FirstElement 0`, `NumElements 0x840`, mapping `0x1688` | Ventana visible **2.112 B**; backing allocation traza | Traza | Cualquier byte válido `R8_UINT`; bytes reales de traza | Extensión ESTÁTICA; backing y bytes `TRACE_FASE1_REQUIRED` |
| arg10 t8 (root 11, BTI 11, heap slot 10, push 44; recurso `ctx+0xa98`) | CM `BufferSurface ReadWrite`; vista D3D SRV `BUFFER R8_UINT`, `NumElements 0x80`, mapping `0x1688` | **128 B** de header, totalmente visibles | Traza: 128 B íntegros, flags y base preservados verbatim | Sin header inventado; ver reglas de flags/base abajo | Extensión ESTÁTICA; contenido `TRACE_FASE1_REQUIRED` |
| arg11 s0 (root 12, sampler heap 0, push 48) | Sampler MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, `ALWAYS`, `MinLOD 0`, `MaxLOD FLT_MAX` | n/a (estado) | n/a | Estado fijado; el fallback ANV coincide parcialmente y no es equivalente | ESTÁTICO; comportamiento de muestreo pendiente de formatos/coords trazados |
| b0 (root 0) | Constante de 1 DWORD, espacio 0 | 4 B | `0` (`SetComputeRoot32BitConstant(0,0,0)` en `0x1800173e0`) | Fijo a cero; no es campo de dimensiones | ESTÁTICO |

Grid y constantes: `w=1920,h=1080 → (120,540,1)` es candidato derivado de
guards (`WorkgroupId.x < 120`, `y < 540`); tamaño local y máscara runtime
siguen abiertos (ver `docs/pre-dispatch-dimensions.md`). `b0 = 0` siempre.

### Relación byte-104 vs plano OWORD de arg0 y header de 128 B (arg10)

IR fijado (`analysis/fsr-resources/xe2-first.spvasm`):

- El header de 128 B se carga desde arg10 (`:5213`/`5220`, variantes
  alineada/no-alineada según rama `3/7/9`, sin semántica asignada a esa rama).
- Campos usados observados, sin nombres semánticos: floats en DWORD-offsets
  8–44, 56, 60, 84; enteros/direcciones en 64–80; flags en byte 100; **base
  (u32) en byte 104** (`:5190-5325`).
- Bit `0x400` de flags (`:5225-5227`): si está set, salida temprana por
  `:1685` sin trabajo. Un dispatch productivo lo requiere limpio, pero el
  valor manda la traza: si viene set, lo esperado es salida temprana.
- Bit `0x2000` (`:5593-5602`): selecciona entre `base` y `base+16` para una
  lectura float4 de 16 B desde arg0 (`:5606-5612`, variantes `:5627`/:5634).
  En este camino `base` es **desplazamiento en bytes relativo a arg0**, no VA.
- Bit `0x200` (`:15970-15973`): si está set, salida temprana sin el store
  final. Bit `0x1000` (`:5574-5583`) y campo `(flags & 0x18) >> 3`
  (`:5325-5328`) son selectores observados sin semántica asignada.
- Plano de escritura: índice OWORD `wg_y·960 + wg_x·8` (`:15977-15993`),
  extremo exclusivo `518400 OWORD = 8.294.400 B` con grid completa 120×540.

Reglas de aceptación (sin inventar valores):

1. Traza conserva los 128 B de arg10 verbatim; flags y base son los trazados.
2. `[base, base+32)` (cubre ambas selecciones `base`/`base+16` + 16 B de
   lectura) debe caber en el `Width` trazado de arg0.
3. La traza debe localizar ventana de lectura `[base, base+32)` y plano de
   escritura por OWORD y demostrar que no hay alias destructivo
   (lectura-antes-de-escritura o regiones disjuntas documentadas).
4. Si `0x400` o `0x200` vienen set en la traza, el resultado esperado es la
   salida temprana correspondiente, no una imagen.

### Reglas de sustitución depth/exposure (sin expandirlas)

De `docs/pre-dispatch-ghidra.md:38-44`, verbatim y sin asignar t_i a escena:
sin `r_depth` y con bit0 de flags, retorno 0. Con `flags&0x18==0`, se exige
`r_input_exposure` (bit2 limpio) o `r_auto_exposure_texture` (bit2 set).
`depth/exposure/auto-exposure` sustituyen fuentes por defecto. El orden exacto
slot←nombre sale de tablas runtime (`+0x8efc`) e índices del caller: mecanismo
establecido, tabla fija pendiente de traza de valores.

Pool stock fijado (pares UTF-16LE en la DLL, asignación runtime):
`MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
`r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`, `r_depth`,
`r_input_exposure`, `r_auto_exposure_texture`.

## (b) Oracle independiente, por orden

Los probes sintéticos (DPAS y de imagen/sampler,
`docs/first-synthetic-gpu-result.md`, `docs/first-image-gpu-result.md`) solo
validan sus propios kernels: 1.408 valores y 64 muestras + centinelas. **No
validan el PRE** ni sus vistas tipadas, y no son oracle.

1. **Rango 1 — captura en referencia que funcione.** Mismo DLL/input/zebin,
   `native_1080`, 1920×1080, constantes `MLSR_Optimized_Constants`, resolución
   de los 10 nombres stock, en una implementación ya validada como correcta
   (no basta `S_OK`/overlay/magenta). Debe registrar, correlacionado por
   ID/descriptor con roots/slots: `D3D12_RESOURCE_DESC` + heap + tamaño/offset
   por recurso; cada `CreateSRV/UAV` y `CopyDescriptors*` con formato,
   mip/layer/rango y slot final; identidad de slots 0–10 justo antes del
   dispatch; header de 128 B de arg10 + bytes de arg0 en `[base, base+32)`;
   handles de root-tables, bases/incremento de heaps, sampler, grid de
   `Dispatch`, estados/transiciones; dumps pre **y** post con canarios;
   ejecutable/versiones/hashes; captura original preservada. Una captura del
   puente que aún falla es evidencia de entradas, nunca oracle
   (`docs/pre-reference-options.md:8-17`).
2. **Rango 2 — CPU validada contra el Rango 1.** Reimplementación CPU que
   reproduzca el Rango 1 byte/bit dentro de tolerancias justificadas en al
   menos un input fijado, antes de usarse. Traducir operaciones aisladas del
   shader sin esa validación no es oracle (`docs/pre-reference-options.md:10-12`).
3. **Rango 3 — contraste L0/OCL solo como bindings.** Mismo zebin vía Level
   Zero u OpenCL, entradas idénticas, comparación de bytes. Comparte kernel y
   posiblemente núcleo del compilador (NEO), así que solo contrasta ABI de
   bindings/backend, nunca demuestra corrección de FSR
   (`docs/pre-reference-options.md:19-33,42-51`).

Tolerancias (justificadas por formato, ninguna inventada):

- Buffers `R8_UINT` (arg0/9/10 como vistos): **tolerancia 0, bit-exacto**.
  `DXGI_FORMAT_R8_UINT` es entero sin signo de 8 bits; vistas tipadas y
  accesos OWORD son bit-exactos, sin redondeo ni filtrado en este camino.
  Un byte distinto = fallo.
- Imágenes (`Unknown`): **sin tolerancia fijada hasta la traza.** Tras fijar
  formato DXGI/Vulkan: enteros → 0; UNORM/SNORM/SRGB → paso de cuantización
  de la spec del formato; FLOAT → redondeo IEEE-754 de la secuencia trazada.
  Ningún épsilon se pre-elige aquí.
- **NaN = fallo.** Cualquier NaN en una región comparada (o
  referencia-finita vs prueba-NaN) es fallo funcional: `NaN != todo`,
  incluso sí mismo; entradas finitas de escena no deben producir NaN.
  Inf = fallo salvo que la referencia Rango 1 lo contenga en el mismo elemento.

## (c) Tests CPU y gates de aceptación

`tools/inspect_pre_initial_contents.py` fija el plan estático (offsets del
header, bits de flags, plano OWORD, guards, máscara 7) con hash del IR, expone
`resource_table()` (12 filas, desconocidos como `TRACE_FASE1_REQUIRED`),
`oracle_policy()` (orden 1>2>3, R8=0, imágenes TBD, NaN=fallo) y
`validate_trace_candidate()` (enumera faltantes de Fase 1 y rechaza claves
`scene_role` inventadas). `tests/test_pre_initial_contents.py` (15 tests)
fija todo eso con fixtures más el módulo fijado; no contiene datos de escena.

Gates de aceptación Fase 2 (todos deben pasar; ninguno autoriza GPU por sí solo):

- G0 Hashes fijados (DLL, IR, zebin) y suite CPU en verde.
- G1 Traza Fase 1 completa: `validate_trace_candidate()` vacío (formatos,
  dims, vistas, `Width` arg0, header 128 B + `[base, base+32)`, grid, local
  size/máscara con evidencia del launcher).
- G2 Contenidos iniciales fijados según tabla; header/flags/base verbatim;
  no-alias lectura/escritura en arg0 demostrado; `b0=0`; sampler fijado.
- G3 Local size, threadcount/modo dispatch y máscara efectiva probados con
  evidencia runtime (nunca `1×1×1`, `simd_size` ni anchos SIMD16 como sustituto).
- G4 Oracle Rango 1 capturado con checklist completa; Rango 2 validado antes
  de usarse; Rango 3 etiquetado solo como contraste de bindings.
- G5 Comparación con tolerancias de formato (R8 bit-exacto, imágenes según
  formato trazado), NaN=fallo, canarios/guard-regions intactos, sin
  lecturas/escrituras fuera de rango.
- G6 Sin GPU en Fase 2; Fase 1 y siguientes en prefijo desechable, sin tocar
  Steam/prefijo real, drivers ni servicios (AGENTS.md).
