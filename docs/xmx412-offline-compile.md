# Compilación offline del PRE 4.1.2 (Xe2, native_1080)

CPU-only. No se ejecutó ninguna DLL, no se usó GPU/Wine/driver/prefijo/Steam.
`artifacts/original` solo se leyó. La compilación offline con el toolchain
local está explícitamente permitida (mismo precedente que
`docs/offline-pre-compilation.md`). Sin gate runtime: sin dispatch,
inyección, readback ni copia a caches runtime.

## 1. Input fijado

Pack `analysis/fsr-xmx-412/pack-40102.raw`, envelope índice 0
(`tools/parse_cm_payloads.py`):

| Campo | Valor |
|---|---|
| `offset` / `end` | `0` / `358873` |
| `ir_size` / `trailer_size` | `358776` / `97` |
| `ir_sha256` | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| `envelope_sha256` | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| pie embebido | `-vc-payload -Xfinalizer '-noDPASMacro'` + ` -target-features=+ocl_runtime` |
| contenido | magic `03 02 23 07`, `fsr4_pre_xmx` en el IR |

Slice exacto `data[0:358873]` a `analysis/offline-pre-412/module-0000.cmspv`
(verificado contra `envelope_sha256`). Variante `native_1080` por posición
heredada del censo viejo; **no** confirmada contra la tabla de variantes de
la DLL 4.1.2 (`fadbcb50…`).

Toolchain fijado (`profiles/intel-toolchain.json`): IGC `2.10.10+18926`,
ocloc `25.18.33578.6`, target `0xe20b`. Comando (misma receta que
`docs/xmx412-toolchain.md` §2):

```bash
mkdir -p analysis/offline-pre-412/out analysis/compiler-cache
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/offline-pre-412/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412/out" \
  -output pre -options '-vc-codegen'
```

Exit 0, `Build succeeded`; warning de triples LLVM dispares conservado.

## 2. IGC consume las opciones embebidas (igual que el control viejo)

| Input | zebin SHA-256 | código nativo SHA-256 | `.misc.buildOptions` |
|---|---|---|---|
| Completo, dos ejecuciones | `b1781bb45a675005a81fb6679ad5f0b02d1252987a0d1f49af38cd4cf13751c2` (idéntico) | `68b962b5a01984d02b0bbe15bda0c8e3d04dd49ad8a58d93e5c16dbb28f8792c` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` (byte-idéntico al viejo) |
| SPIR-V recortado (`data[0:358776]`) | `ff889fb8a294588e6de85816dfe52c60a3f3bd701ed17ff82ebd39b39f7c2978` | `e941cd977c6ea1b26de76a8460a07bf9c7167f0120a988438210cc3884d57e78` | `-vc-codegen` |

Mismos BTIs en ambos outputs; distinto código. Identificar solo por
kernel/BTIs sería insuficiente, igual que en el control viejo.

## 3. `ze_info` / BTIs: contrato de compilador idéntico al viejo

- `ze_info` byte-idéntico al viejo (`sha256
  5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c`).
- `execution_env`: `grf_count 128`, `simd_size 1`, `has_dpas true`,
  `has_sample true` (más `has_fence_for_image_access`,
  `has_no_stateless_write`, `offset_to_skip_per_thread_data_load 128`).
- BTIs por `arg_index 0…10`: `[8,9,1,2,3,4,5,6,7,10,11]`; sampler aparte
  (`arg 11`, `sampler_index 0`).
- Payload cross-thread distinto de cero: `arg0@8`, `arg9@16`, `arg10@24`
  (8 B) + `private_base_stateless@0` (8 B); per-thread `packed_local_ids`
  (6 B). Idéntico al viejo.
- IR embebido (`49e069fd…`, 358776 B): entry de 12 parámetros en orden,
  superficies opacas 0/9/10 con uso único
  `llvm.genx.address.convert.i32.p1intel.buffer_rw_t`, guards
  `WorkgroupId.x >= 120`, `WorkgroupId.y >= 540` (mismo patrón que el viejo).

Lo que cambió (esperado, el IR pasó de 330108 a 358776 B):
`code 68b962…` (antes `2e42d33c…`, 30464 B vs 29376 B),
`zebin b1781b…` (antes `3e974d57…`, 395256 B vs 365504 B),
IGA `7773a88b…` (antes `a9c82bbb…`, 2390 líneas vs 2310),
`spvasm 7ac12fd2…` (antes `7ed1d81b…`).
Coincidir con los hashes viejos habría sido sospechoso, no éxito.

## 4. Auditoría de payload: bloqueada (fail-closed), no segura

`tools/audit_pre_payload.py` (sin modificar) rechaza el nuevo IGA:

- `build_report`: `Unreviewed CM input` (sus pins viejos intactos; correcto).
- `parse_isa`: `Unsupported native opcode macl` (línea 444 del ASM:
  `macl (1|M0) r1.0<1>:d r82.14<0;1,0>:d r80.1<0;1,0>:d`,
  precedida por `mul ... acc0...`).

Delta exacto vs el IGA viejo: una sola instrucción `macl` nueva; el resto
parsea. Los flujos `acc0` (252 ocurrencias) ya existían en el IGA viejo con
patrón idéntico, y el auditor los trata igual (no-GRF) en ambos binarios.

El perfil `profiles/fsr4-pre-412-native1080-payload-audit.json` registra
este bloqueo (`status static-analysis-blocked`,
`native_byte_liveness.status blocked-unsupported-opcode`,
`possible_reads unknown`), más la evidencia IR que sí se verificó
(superficies, orden, guards, offsets). `runtime_approved false`.
Nota experimental no reclamada: tratando `macl` como aritmética ternaria
genérica se obtienen 160 visitadas / cero lecturas / overwrites en las
líneas 20/23/143/179/379 (igual forma que el viejo), pero la semántica
implícita de `acc0` en `macl` sigue sin revisar: **ningún veredicto
`unread` para 4.1.2**.

Por eso no se tocó `tools/audit_pre_payload.py`: la extensión requeriría
modificar un archivo existente y reclamar semántica ISA sin revisar.

## 5. Perfil nuevo

`profiles/fsr4-pre-412-native1080-bmg.json`
(`experimental-offline-only`): fija `input ce372719…`, `code 68b962…`,
`zebin b1781b…`, `surface_count 11`,
`expected_push_size 52`, `table_pc_base 4`.
Push/base se portan porque la evidencia 4.1.2 los confirma mecánicamente:
mismo orden/BTIs + mismo `ze_info` → misma derivación `pre_layout`
(11 superficies stateful, sampler separado, offsets 4…44, base explícita 4
en vez del auto 8). `payload_review` apunta a la auditoría bloqueada, no a
un `unread`.

## 6. Reproducción y tests

```bash
python -m unittest tests.test_xmx412_compile -v
python -m unittest tests.test_xmx412_toolchain -v
```

`tests/test_xmx412_compile.py` (13 tests, solo CPU): pins de slice,
zebin/código, determinismo (re-ejecución idéntica), control recortado,
`ze_info`/BTIs/payload/sampler, guards del IR, igualdad de perfiles con el
staging, y rechazo fail-closed del auditor legado (`Unreviewed CM input`,
`macl`). Salta (no pasa en falso) si pack/toolchain/staging están ausentes.

Staging en `analysis/offline-pre-412/` (ignorado por git):
`module-0000.cmspv/.spv`, `out/`, `out-repro/`, `out-stripped/`,
`disasm/`, `embedded.spv/.spvasm`, `metadata/ze_info.yaml`,
`summary.json`.

## 7. Límites

- Sin dispatch, inyección, readback ni aprobación runtime. No copiar el
  artefacto a caches runtime ni activar helpers con él.
- `macl`/`acc0` sin revisar; auditoría de payload bloqueada.
- Variante `native_1080` posicional, sin tabla 4.1.2; resto de PREs
  (filas 2–18 de la matriz) y `pass6` fuera de alcance.
- `grf_count 128` / `simd_size 1` no generalizan a otras variantes.
