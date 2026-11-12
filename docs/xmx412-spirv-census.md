# Censo SPIR-V PRE Xe2: viejo (4.0.2x) vs nuevo (4.1.2)

CPU-only, estático. PROHIBIDO ejecutar DLLs, GPU/Wine, tocar
`artifacts/original`, juegos o prefijos. No se asigna semántica de escena
(color/profundidad/movimiento) y no se infieren formatos de imagen.

## Fuentes y método

- Viejo: pack Xe2 `analysis/fsr-resources/resource-0001.raw`
  (23 164 789 B, SHA-256 `8b520078…9ecec39d24`), 252 envelopes CM.
  PRE documentado `analysis/fsr-resources/xe2-first.spvasm`
  (16 014 líneas, SHA-256 `7ed1d81b…7968db6a9e`), IR 330 108 B,
  `ir_sha256 1d10c34e…2bd44a2`. Ver
  `docs/pre-controlled-test-contract.md:20-119` y `docs/pre-resource-map.md`.
- Nuevo: build XMX 4.1.2 DLL `fadbcb50…b37f44732` (8 recursos: 6 packs
  + VERSIONINFO + manifest, ver `docs/xmx412-pins.md`),
  pack Xe2 `analysis/fsr-xmx-412/pack-40102.raw`
  (23 682 325 B, SHA-256 `d88aa9d6…995e491`), 252 envelopes CM.
  Primer PRE (record 0): IR 358 776 B,
  `ir_sha256 49e069fd…21f9f568`,
  `envelope_sha256 ce372719…faac8f34bf0b34aa5b85ab`,
  desensamblado transitorio en `/tmp/opencode` (17 444 líneas,
  SHA-256 `7ac12fd2…19dd9d46a2`). No se incorpora el `.spvasm` al repo.
- Parser: `tools/parse_cm_payloads.py` (pies verificados, trailer 97 B,
  `"-vc-payload -Xfinalizer '-noDPASMacro'"` +
  `" -target-features=+ocl_runtime"` en ambos builds).
  Pins de loader: `tools/decompress_xmx412.py:EXPECTED[40102]`
  (verificado en `tests/test_xmx412_spirv.py`).
- Dis: `spirv-dis` SPIRV-Tools 2026.4 (solo CPU). Reproducción sin escribir
  en el repo:

```bash
python3 -c "import sys; sys.path.insert(0,'tools'); import parse_cm_payloads, pathlib; \
data=pathlib.Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes(); \
recs=parse_cm_payloads.parse(data); \
open('/tmp/opencode/new-pre.spv','wb').write(data[recs[0]['offset']:recs[0]['offset']+recs[0]['ir_size']])"
spirv-dis /tmp/opencode/new-pre.spv -o /tmp/opencode/new-pre.spvasm
python3 -m unittest discover -s tests -p test_xmx412_spirv.py -v
```

El bloque PRE son 18 variantes por pack en ambos builds
(indices `[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`,
paso 14). Todos los IR PRE del mismo pack comparten `ir_size`
(viejo 330 108, nuevo 358 776) pero tienen `ir_sha256` distintos (18/18).
El censo fino se hizo sobre la variante 120×540 (record 0, la documentada
como `xe2-first`); la estabilidad del bloque (entry/args/tipos/BuiltIns/
ExecutionModes/conteos/store) se verificó en las 18 nuevas por
desensamblado.

## Tabla lado a lado (record 0 vs record 0)

| Aspecto | Viejo 4.0.2x (`xe2-first`) | Nuevo 4.1.2 (pack 40102 record 0) | ¿Igual? |
|---|---|---|---|
| Entry points | 1× `Kernel %10259 "fsr4_pre_xmx" %__spirv_BuiltInWorkgroupId` | 1× `Kernel %11173 "fsr4_pre_xmx" %__spirv_BuiltInWorkgroupId` | Sí (nombre/iface; solo cambia el SSA id) |
| Args ordenados | 12: `%587,%591,%595×7,%587,%587,%599` (wrapper `%10259`, inner `%fsr4_pre_xmx` `%605…%616` mismo orden) | 12: `%770,%774,%778×7,%770,%770,%782` (wrapper `%11173`, inner `%fsr4_pre_xmx` `%788…%799` mismo orden) | Sí (patrón; solo renumeración de ids de tipo) |
| Tipos (`OpType*`) | `%587=BufferSurfaceINTEL ReadWrite`; `%591=Image 2D Unknown ReadWrite`; `%595=Image 2D Unknown ReadOnly`; `%599=Sampler`. Firma `%603=Function %void %587 %591 %595×7 %587 %587 %599` | `%770=BufferSurfaceINTEL ReadWrite`; `%774=Image 2D Unknown ReadWrite`; `%778=Image 2D Unknown ReadOnly`; `%782=Sampler`. Firma `%786=Function %void %770 %774 %778×7 %770 %770 %782` | Sí (permisos/dims/formato `Unknown` idénticos) |
| Detalle args | 0 Buffer RW, 1 Image RW, 2–8 Image RO ×7, 9–10 Buffer RW, 11 sampler | 0 Buffer RW, 1 Image RW, 2–8 Image RO ×7, 9–10 Buffer RW, 11 sampler | Sí |
| `OpTypeImage` | `%void 2D 0 0 0 0 Unknown` + `ReadWrite`/`ReadOnly`; 2D, sin formato inferido | Idéntico: `%void 2D 0 0 0 0 Unknown` + `ReadWrite`/`ReadOnly` | Sí (no inventar formatos) |
| BuiltIns | Solo `WorkgroupId` (`OpDecorate … BuiltIn WorkgroupId`, `OpVariable %_ptr_Input_v3ulong Input`, 2× `OpLoad v3ulong`) | Solo `WorkgroupId`, misma decoración/variable/cargas (`%4100/%4104` vs `%3698/%3702`) | Sí |
| ExecutionModes | `%10259 ContractionOff`, `SubgroupSize 1`, `SharedLocalMemorySizeINTEL 0`, `NamedBarrierCountINTEL 0` | `%11173 ContractionOff`, `SubgroupSize 1`, `SharedLocalMemorySizeINTEL 0`, `NamedBarrierCountINTEL 0` | Sí |
| `LocalSize` | Ausente | Ausente (no inferir local size de `SubgroupSize 1`) | Sí (ausente en ambos) |
| Guards WorkgroupId (record 0) | `OpUGreaterThanEqual %bool … %uint_120` + `… %uint_540`, `BranchConditional` a retorno temprano (líneas 5177/5183; contrato 5166–5185). Solo X/Y; Z no se usa | `OpUGreaterThanEqual %bool … %uint_120` + `… %uint_540`, mismo patrón `BranchConditional` (líneas 5838/5844 del transitorio). Solo X/Y; Z no se usa | Sí para record 0 |
| Guards del bloque | 18 variantes ciclan `120×540,240×1080,480×2160` (6 cada una, orden repetido) | 18 variantes ciclan `120×540,240×1080,480×2160` (6 cada una, mismo orden) | Sí (NO es “mismo 120×540” para todo el bloque; el primero sí coincide) |
| Conteos `OpFunctionCall` | `3d_load 78`, `3d_sample 85`, `typed_quad_store 1` (misma en las 18 viejas muestreadas) | `3d_load 78`, `3d_sample 85`, `typed_quad_store 1` (misma en las 18 nuevas, verificado por dis) | Sí |
| Firma store | `llvm.genx.lsc.store.quad.typed.bti.v16i1.v16i32.v48f32`, 10 operandos `(pred,i8,i8,i8,i32 surface,u,v,r,lod,data)`, `(%uchar_0,%uchar_0,%uchar_7,…)` | Misma función y aridad 10, mismos `(0,0,7,…)` | Sí |
| Máscara/canales | `7` = `.xyz` channel-enable, no BTI/superficie | `7` = `.xyz`, no BTI/superficie | Sí |
| Superficie store | `%9780` (`:15312` viejo), cadena `%9780←%3391←%9774←%3397←%9769←%3460←%3749←%3656←%1687`, `%1687=address_convert … %606` | `%10694` (call `%10703`), cadena `%10694←%3782←%10688←%3788←%10683←%3851←%4151←%4058←%1920`, `%1920=address_convert … %789` | Patrón sí; SSA ids cambian |
| Origen store | arg 1 Image2D RW (`%606` es 2.º param inner `%605…%616`; outer pasa args en orden; zebin BTI 9, IGA `store_quad…bti[9]`) | arg 1 Image2D RW (`%789` es 2.º param inner `%788…%799`; outer `%11174…%11185` en orden). No se reclama BTI/zebin nuevo | Sí (arg 1; t6/BTI 7 no es destino) |
| IR / módulo | 330 108 B, `Bound 10274`, 16 014 líneas, SPIR-V 1.1, `Khronos LLVM/SPIR-V Translator;14`, caps 13, ext `SPV_INTEL_vector_compute`+`SPV_KHR_no_integer_wrap_decoration`, `Physical64 OpenCL` | 358 776 B (+28 668), `Bound 11188`, 17 444 líneas, misma versión/generador/caps/ext/memoria | Crece; resto idéntico |
| Trailer CM | 97 B, mismas 2 cadenas | 97 B, mismas 2 cadenas | Sí |

## Diferencias sintácticas adicionales (informativas, sin semántica)

- `OpFunctionCall` totales: 1 403 (viejo record 0) vs 1 509 (nuevo record 0).
- `oword_st_*` calls: 2 (`v4f32`, `v128i8`) vs 4
  (`v4f32`, `v8i32`, `v4i32`, `v128i8`). No se asigna significado ni se
  cuenta como parte del censo pedido.
- Patrón header 128 B preservado sintácticamente (`%uint_128`,
  `Aligned 128`, `oword_ld_unaligned_v32i32`/`oword_ld_v32i32` + ramas
  `%uint_3/7/9`) en ambos records 0; no se infieren layouts ni contenidos.

## Límites

- Conteos = llamadas sintácticas `OpFunctionCall`, no píxeles ni accesos.
- `Unknown` en `OpTypeImage` = no inferir formato Vulkan/canales/espacio.
- No establece local size, comportamiento del dispatch runtime, máscara de
  ejecución, ni oracle funcional. `S_OK`/PSO no acreditan nada.
- El censo no sustituye compilación offline/zebin ni auditoría de payload
  del nuevo build (ver `docs/xmx412-pins.md` REQUIRED-TBD).

## Evidencia y pins CPU

`tests/test_xmx412_spirv.py` (21 tests, fail-closed): tamaño/SHA del pack,
252 envelopes, 18 PRE en índices fijos, `ir_size` 358 776 + strings,
`ir/envelope SHA` del record 0, 18 SHAs distintos, consistencia con
`decompress_xmx412.EXPECTED[40102]`, entry único, 12 args ordenados,
`WorkgroupId` único, 4 ExecutionModes exactos sin `LocalSize`, ciclo de
guards `[(120,540),(240,1080),(480,2160)]×6`, conteos 78/85/1 en las 18,
firma store `(pred,0,0,7,surface,u,v,r,lod,data)` con superficie `%10694`
desde arg 1 (`%789`), más fixtures sintéticos que rechazan cambio de orden,
guards, rebinding de superficie, máscara y clases de ops.
