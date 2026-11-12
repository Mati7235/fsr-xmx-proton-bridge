# XMX 4.1.2: 18 variantes PRE Xe2 (pack 40102)

CPU-only, estático. PROHIBIDO ejecutar DLLs, GPU/Wine, tocar
`artifacts/original`, juegos o prefijos. No se asigna semántica de escena
(color/profundidad/movimiento) ni se infieren formatos de imagen.

## Fuentes y método

- Pack Xe2 `analysis/fsr-xmx-412/pack-40102.raw` (23 682 325 B, SHA-256
  `d88aa9d6…995e491`), 252 envelopes CM, parser `tools/parse_cm_payloads.py`
  (pies verificados, trailer 97 B, `"-vc-payload -Xfinalizer '-noDPASMacro'"` +
  `" -target-features=+ocl_runtime"`).
- Los 18 PRE son los envelopes con `fsr4_pre_xmx` en el IR, en índices CM
  `[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`
  (paso 14). Todos comparten `ir_size 358776`, `trailer 97`,
  `envelope 358873`, mismas dos cadenas, `entry %11173 "fsr4_pre_xmx"`,
  12 args ordenados, `WorkgroupId` único, 4 ExecutionModes sin `LocalSize`,
  conteos `78/85/1` y store `typed_quad_bti (0,0,7)` con superficie `%10694`
  desde arg 1. Ver `tests/test_xmx412_variants.py` (16 tests, fail-closed)
  y `docs/xmx412-spirv-census.md` para el censo fino del record 0.
- Desensamblado: `spirv-dis` SPIRV-Tools 2026.4 (solo CPU) sobre cada slice
  exacto `data[offset:offset+358776]`.
- Compilación offline: toolchain fijado `profiles/intel-toolchain.json`
  (IGC `2.10.10+18926`, ocloc `25.18.33578.6`), target `0xe20b` (B580),
  `-options '-vc-codegen'`, en `analysis/offline-pre-412-variants/`
  (ignorado; no usar `analysis/offline-pre-412/`, de otro agente en paralelo).
  Los 18 compilan con exit 0 (`Build succeeded` + warning de triples dispares
  conservado, no suprimido).
- Orden de variantes asumido del censo viejo
  (`analysis/pre-reconstruction.json` `native_1080 … drs_4320`,
  `rec_idx = 14*k`, `index = k+1`). La tabla de variantes de la DLL nueva
  (`fadbcb50…`) no se re-parsea aquí: la columna `Variante` queda invalidada
  si esa DLL reordena los PRE respecto al censo viejo (reportar, no renombrar
  a ciegas). La hipótesis se sostiene estructuralmente (ver § Confirmación).

## Tabla completa (confirmada)

`grid` = guards `WorkgroupId.x/y` (`OpUGreaterThanEqual %uint_X/Y`, una sola
ocurrencia c/u, solo X/Y; Z no se usa). `factor` = ciclo `[1,2,4]×6` heredado
del censo viejo (`test_pre_resources.py:96`, `table_dword_at_0x24`) y
correlacionado con sufijo/grid; `min Width = factor²·0x7e9000` (DLL vieja;
fórmula retenida, no re-derivada de la DLL nueva). `IR` siempre 358 776 B.

| # | Variante (asumida) | `rec_idx` | `offset` | grid guards | factor / min Width | `ir_sha256` | `envelope_sha256` | zebin / code (offline `0xe20b`) |
|---:|---|---|---:|---|---|---|---|---|
| 1 | `native_1080` | 0 | 0 | 120×540 | 1 / 8 294 400 | `49e069fd…21f9f568` | `ce372719…b85ab` | `b1781bb4…13751c2` / `68b962b5…28f8792c` |
| 2 | `native_2160` | 14 | 1315712 | 240×1080 | 2 / 33 177 600 | `20096eef…83d7ebb29` | `ee5553e3…027597` | `6a8f0fe6…bca2e6` / `ba7f966a…697b87` |
| 3 | `native_4320` | 28 | 2631424 | 480×2160 | 4 / 132 710 400 | `b4eacd68…0efc5e` | `281e11fc…efe616` | `dede3aed…7a62fa` / `0ad99755…1930f09` |
| 4 | `quality_1080` | 42 | 3947072 | 120×540 | 1 / 8 294 400 | `4516209c…7979722` | `bc2b0cf3…13a558` | `35fe9a6e…6999f4` / `88ccb2ff…05426a` |
| 5 | `quality_2160` | 56 | 5262784 | 240×1080 | 2 / 33 177 600 | `781497a6…83a7e35` | `c7af3e98…fa66` | `05e99861…0eeed` / `cce6dbab…7fadb` |
| 6 | `quality_4320` | 70 | 6578496 | 480×2160 | 4 / 132 710 400 | `530315c6…0940950` | `3414bc91…2333d4` | `1d747d50…a043d8` / `a5ba59b0…8d55` |
| 7 | `balanced_1080` | 84 | 7894144 | 120×540 | 1 / 8 294 400 | `58681903…a394a1f3` | `a6673041…a84a1` | `4fe17d55…e4275` / `46c43ce5…323638` |
| 8 | `balanced_2160` | 98 | 9209856 | 240×1080 | 2 / 33 177 600 | `fdd506a0…cffe9f` | `0dc3e2dd…f12d` | `096a231f…fac5c` / `83e1bc5c…aaf29` |
| 9 | `balanced_4320` | 112 | 10525568 | 480×2160 | 4 / 132 710 400 | `0d02fd9f…6be9c8` | `457c98b4…08da` | `5921d268…17718` / `ec826861…e1630` |
| 10 | `performance_1080` | 126 | 11841216 | 120×540 | 1 / 8 294 400 | `13d79716…21b7d2` | `00239bc0…a954e` | `2580f661…5cd89` / `5daf0d65…34c4b65` |
| 11 | `performance_2160` | 140 | 13156928 | 240×1080 | 2 / 33 177 600 | `44ddd92c…937aa4` | `5ffb99bb…10ddf` | `f4d93730…4632a` / `0bb8b07d…03599` |
| 12 | `performance_4320` | 154 | 14472640 | 480×2160 | 4 / 132 710 400 | `cc0d724a…64d313` | `4d6437df…2414` | `250ddd1a…832d` / `1437b715…60d6` |
| 13 | `ultraperf_1080` | 168 | 15788288 | 120×540 | 1 / 8 294 400 | `9fdea8f9…4386f` | `4f16b9c1…9c1b` | `e7640611…3176` / `67ad3899…48d81` |
| 14 | `ultraperf_2160` | 182 | 17103984 | 240×1080 | 2 / 33 177 600 | `6f2805c2…81ad4` | `50a9da87…8aaa3` | `cb80102b…30b6` / `679b9162…ad584` |
| 15 | `ultraperf_4320` | 196 | 18419680 | 480×2160 | 4 / 132 710 400 | `ae23ffef…ebf3f8` | `87a6d240…3634e` | `503f1269…26f7` / `46c84cb9…e7af65` |
| 16 | `drs_1080` | 210 | 19735312 | 120×540 | 1 / 8 294 400 | `1692bc85…964f64` | `e1bb7ba5…63c6` | `e481a5f8…4c2e5` / `04268212…1c68` |
| 17 | `drs_2160` | 224 | 21051008 | 240×1080 | 2 / 33 177 600 | `b289069b…694cd` | `436e5cb0…3440` | `243f845f…b535` / `5a589d02…680a` |
| 18 | `drs_4320` | 238 | 22366704 | 480×2160 | 4 / 132 710 400 | `c674bc37…eb27` | `ed03b05e…d05e` | `4c7b2796…83cd` / `b3c63d8f…52c1` |

Hashes completos (64 hex) en `tests/test_xmx412_variants.py: VARIANTS` y
`OFFLINE_BUILDS`. SHAs de IR/envelope verificados por slice exacto + footer;
SHAs de zebin/code por `tools/inspect_zebin.py` (`fsr4_pre_xmx`).

## Confirmación del ciclo y factores

- Ciclo de guards **confirmado** por desensamblado de los 18:
  `[(120,540),(240,1080),(480,2160)]×6` en orden de `rec_idx` (6 de cada uno,
  intercalados, no agrupados). Cada `_1080` guarda `120×540`, cada `_2160`
  guarda `240×1080`, cada `_4320` guarda `480×2160`. Coincide con el censo
  (`docs/xmx412-spirv-census.md:63`) y con la fórmula de dispatch derivada
  (`x=(w+15)>>4; x+=x&1; y=h>>1` → `1920×1080→120×540×1`,
  `docs/xmx412-dispatch.md:64-89`).
- Factores **confirmados como ciclo** `[1,2,4]×6` en el mismo orden (heredado
  del censo viejo; `pre-reconstruction.json` + `test_pre_resources.py:96`).
  Correlación sufijo→factor→grid: `_1080→1→120×540`,
  `_2160→2→240×1080`, `_4320→4→480×2160`. No se re-parseó la tabla de la DLL
  4.1.2; si esa tabla reordena, la columna `Variante` cae (ver límites).
- Resto bit-idéntico al censo viejo salvo PRE+pass6 (ya fijado en
  `docs/xmx412-toolchain.md:42-54`): los 18 PRE nuevos comparten `ir_size`
  358 776 (viejo 330 108) con 18 `ir_sha256` distintos; las otras 216
  envolventes son bit-idénticas por índice al build viejo.

## Compilación offline (los 18)

Comando por variante (input `.cmspv` = IR+pie, nunca `.spv` recortado):

```bash
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/offline-pre-412-variants/module-00-rec0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412-variants/out-00-rec0000" \
  -output pre -options '-vc-codegen'
python tools/inspect_zebin.py analysis/offline-pre-412-variants/out-00-rec0000/pre_bmg.bin \
  --kernel fsr4_pre_xmx
```

Resultados (todos):

- Exit 0, `Build succeeded` en los 18 (warning de triples LLVM dispares
  conservado, igual que `docs/offline-pre-compilation.md:29`).
- Mismo `execution_env` en los 18: `grf_count 128`, `simd_size 1`,
  `has_dpas true`, `has_sample true` (+ `has_fence_for_image_access true`,
  `has_no_stateless_write true`, `offset_to_skip_per_thread_data_load 128`).
- Mismo orden BTI en los 18: `[8,9,1,2,3,4,5,6,7,10,11]` por
  `arg_index 0…10` + sampler separado (igual al censo viejo,
  `docs/xmx412-toolchain.md:158-184`). Cualquier desvío habría sido evidencia
  nueva; no lo hubo.
- Mismo `code_size 30464` en los 18 (viejo `native_1080`: 29 376).
- `zebin_sha256`/`code_sha256` **difieren** en los 18 (esperado: los IR
  difieren en guards) y difieren del pin viejo (`zebin 3e974d…`, `code
  2e42d33c…`); coincidir habría sido sospechoso.
- `per_thread`: `packed_local_ids size 6`; cross-thread `arg0@8`, `arg9@16`,
  `arg10@24` (8 B c/u) + `private_base_stateless@0` (8 B), igual al viejo.

## Límites

- Nombres de variante = hipótesis heredada, no prueba de la tabla 4.1.2.
  No renombrar a ciegas; no usar para perfilar/cachear sin revisión.
- `Unknown` en `OpTypeImage` = no inferir formato Vulkan/canales/espacio.
- Conteos = llamadas sintácticas `OpFunctionCall`, no píxeles ni accesos.
- No establece local size, comportamiento del dispatch runtime, máscara de
  ejecución, ni oracle funcional. `S_OK`/PSO no acreditan nada.
- Compilación offline ≠ corrección GPU. Sin dispatch, inyección, readback ni
  aprobación runtime. No copiar a cache runtime ni activar helpers.
- `analysis/offline-pre-412-variants/` y `analysis/compiler-cache/` están
  ignorados por git; solo se versionan código, tests y docs.

## Evidencia y reproducción

- `tests/test_xmx412_variants.py` (16 tests): tamaño/SHA del pack, 252
  envelopes, 18 PRE en índices fijos, tabla completa offsets/IR/envelope SHAs/
  opciones, ciclos de guards/factores + correlación por sufijo, entry único,
  12 args ordenados, `WorkgroupId` único, 4 ExecutionModes sin `LocalSize`,
  conteos 78/85/1 y store `%10694`/máscara 7/origen arg 1 en los 18, BTIs
  `[8,9,1,2,3,4,5,6,7,10,11]` + env + `code_size` + zebin/code SHAs cuando los
  artefactos offline están presentes, más fixtures sintéticos que rechazan
  cambio de orden, guards, rebinding, máscara, clases de ops y entry extra.
- `python -m unittest tests.test_xmx412_variants -v`
- `python -m unittest tests.test_xmx412_spirv -v` (censo fino, ya verde)
