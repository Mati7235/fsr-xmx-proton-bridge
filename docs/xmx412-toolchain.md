# XMX 4.1.2 toolchain + PRE Xe2: offline compile reference

CPU-only. No DLL is executed, no GPU/Wine/driver/prefix/Steam state is
touched, `artifacts/original` is read-only. Offline compilation with the
local IGC/ocloc below is explicitly allowed (CPU, no dispatch).

## 1. Toolchain intacto (verificado)

Pinned in `profiles/intel-toolchain.json`:

- IGC `2.10.10+18926`, ocloc `25.18.33578.6` (binary `ocloc-25.18.1`).
- Target `0xe20b` (B580/Battlemage G21).

| Deb | SHA-256 |
|---|---|
| `artifacts/original/intel-toolchain/igc-core.deb` | `ec3b8e6bb3d6371d3b9963c32ddb1d5315e6b0c3f4ae1d91a7515b5a8907ffe6` |
| `artifacts/original/intel-toolchain/igc-opencl.deb` | `0c631f25cd8394a2f7640f9e35b593cc98ca3fbe922419c5cb20b2281477ef4c` |
| `artifacts/original/intel-toolchain/ocloc.deb` | `c772db8891539890237d50c357af1480b22cbd859c0b8afb5355f605a818d758` |

Extracted layout (no install, only `data.tar.gz` / `data.tar.zst` extracted):

- `artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1`
- `artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu/libocloc.so`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigc.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libiga64.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigdfcl.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libopencl-clang2.so.15`

Verificación (solo lectura + parseo stdlib, sin ejecutar la DLL):

```bash
sha256sum artifacts/original/intel-toolchain/*.deb
ls artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 \
   artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu/libocloc.so \
   artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigc.so.2.10.10+18926
python -m unittest tests.test_xmx412_toolchain -v
```

`tests/test_xmx412_toolchain.py` fails closed on any hash/layout drift and
skips only when the ignored local artifacts are absent.

## 2. Bloque CM del PRE Xe2 4.1.2 (listo para compilar)

Pack `analysis/fsr-xmx-412/pack-40102.raw` (bucket `18-variant Xe2
(SIMD16 DPAS)`, del commit `7059945`):

- `raw_size 23682325`, `raw_sha256
  d88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491`.
- 252 envelopes CM, todos `trailer 97` con las mismas opciones embebidas.
- 18 PRE (`ir_size 358776`, antes `330108`) + 18 `pass6` (`31824`/`31808`,
  antes `31748`/`31732`); las otras 216 envolventes son bit-idénticas al
  censo viejo (mismo `ir_sha256` por índice).
- Cada IR contiene `fsr4_pre_xmx` / `fsr4_pass6_xmx_runtime` según familia.

PRE `native_1080` = primer envelope del pack (posición heredada del censo
viejo: `pre-reconstruction.json` variant `index 1`, `pack_40102 offset 0`):

| Campo | Valor |
|---|---|
| Pack | `analysis/fsr-xmx-412/pack-40102.raw` |
| `offset` | `0` |
| `ir_size` | `358776` |
| `trailer_size` | `97` |
| `envelope_size` / `end` | `358873` / `358873` |
| `ir_sha256` | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| `envelope_sha256` | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| `embedded_string_a` | `-vc-payload -Xfinalizer '-noDPASMacro'` |
| `embedded_string_b` | ` -target-features=+ocl_runtime` |
| Contenido | magic `03 02 23 07` en offset 0, `fsr4_pre_xmx` en el IR |

Si el parseo (`tools/parse_cm_payloads.py`) no devuelve este bloque exacto,
el PRE **no es identificable**: reportar y parar, no compilar otro índice.

Materializar el input sin ejecutar la DLL (el `.cmspv` incluye IR + pie;
no usar el `.spv` recortado; el control viejo demuestra que el compilador
consume las opciones del pie):

```bash
python3 -c "
from pathlib import Path
data = Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes()
blob = data[0:358873]
out = Path('analysis/xmx412-pre-native1080/module-0000.cmspv')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(blob)
import hashlib
assert hashlib.sha256(blob).hexdigest() == 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab'
print('staged', out, len(blob))
"
```

Comando exacto de compilación (misma receta que
`docs/offline-pre-compilation.md`, solo cambia el input/output):

```bash
mkdir -p analysis/xmx412-pre-native1080/out analysis/compiler-cache
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/xmx412-pre-native1080/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/xmx412-pre-native1080/out" \
  -output pre -options '-vc-codegen'
```

Inspección posterior (CPU, sin GPU):

```bash
python tools/inspect_zebin.py analysis/xmx412-pre-native1080/out/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/xmx412-pre-native1080/summary.json
```

Nota: `tools/build_pre_profile.py` rechaza este input nuevo por diseño
(fija `input 76942f…` / `zebin 3e974d…` viejos). Comparar BTIs/ze_info a
mano contra la §4 hasta una revisión de perfil nueva.

## 3. Matriz mínima de compilación

Orden de variantes asumido del censo viejo (`pre-reconstruction.json`
`native_1080 … drs_4320`, `rec_idx = 14k`). Todos los PRE nuevos comparten
`ir_size 358776`, `envelope 358873`, mismo pie que arriba. Prefijos SHA-12
solo como sanity; el pin completo de `native_1080` está en la §2 y en el
test; recalcular el resto con `tools/parse_cm_payloads.py` antes de compilar.

| # | Variante (asumida) | `rec_idx` | `offset` | `ir_sha12` | `env_sha12` |
|---|---|---:|---:|---|---|
| 1 | `native_1080` | 0 | 0 | `49e069fd7ad1` | `ce3727191553` |
| 2 | `native_2160` | 14 | 1315712 | `20096eefd6ea` | `ee5553e3d31d` |
| 3 | `native_4320` | 28 | 2631424 | `b4eacd686aa9` | `281e11fc87bb` |
| 4 | `quality_1080` | 42 | 3947072 | `4516209c2f75` | `bc2b0cf3eb0f` |
| 5 | `quality_2160` | 56 | 5262784 | `781497a65e8d` | `c7af3e98a45a` |
| 6 | `quality_4320` | 70 | 6578496 | `530315c68368` | `3414bc91df06` |
| 7 | `balanced_1080` | 84 | 7894144 | `58681903c962` | `a6673041f400` |
| 8 | `balanced_2160` | 98 | 9209856 | `fdd506a063ea` | `0dc3e2dd165d` |
| 9 | `balanced_4320` | 112 | 10525568 | `0d02fd9f232b` | `457c98b43110` |
| 10 | `performance_1080` | 126 | 11841216 | `13d797165e10` | `00239bc0fe38` |
| 11 | `performance_2160` | 140 | 13156928 | `44ddd92c95086` | `5ffb99bbc8c9` |
| 12 | `performance_4320` | 154 | 14472640 | `cc0d724ae018` | `4d6437df94cf` |
| 13 | `ultraperf_1080` | 168 | 15788288 | `9fdea8f98f92` | `4f16b9c138a5` |
| 14 | `ultraperf_2160` | 182 | 17103984 | `6f2805c29197` | `50a9da87b25c` |
| 15 | `ultraperf_4320` | 196 | 18419680 | `ae23ffef499a` | `87a6d240ee8e` |
| 16 | `drs_1080` | 210 | 19735312 | `1692bc855b02` | `e1bb7ba59ae5` |
| 17 | `drs_2160` | 224 | 21051008 | `b289069b36ae` | `436e5cb09cd5` |
| 18 | `drs_4320` | 238 | 22366704 | `c674bc372fe5` | `ed03b05e97c5` |

Fases:

1. Solo `native_1080` (fila 1): compilar, inspeccionar, aplicar criterio §5.
2. Resto PRE (filas 2–18): mismo comando por bloque (`data[offset:offset+358873]`),
   sin perfilar ni cachear hasta que la fila 1 cierre.
3. `pass6` (18 bloques en `rec_idx 6,20,…`, `ir 31824/31808`): fuera de esta
   matriz; requiere su propio censo/kernel. Las 12 familias restantes no se
   recompilan (bit-idénticas al build viejo).

Si las tablas de variante de la DLL 4.1.2 (`fadbcb50…`) reordenan los PRE
respecto al censo viejo, la columna `Variante` queda invalidada: no renombrar
a ciegas, reportar la tabla real y parar.

## 4. BTIs / `ze_info` esperados (censo viejo)

Del perfil `profiles/fsr4-pre-native1080-bmg.json` + `ze_info.yaml` viejo
(`zebin 3e974d…`, `code 2e42d33c…`, `input 76942f…`):

| Arg | BTI | Root | Registro | Push |
|---:|---:|---:|---|---:|
| 0 | 8 | 1 | u0 | 4 |
| 1 | 9 | 2 | u1 | 8 |
| 2 | 1 | 3 | t0 | 12 |
| 3 | 2 | 4 | t1 | 16 |
| 4 | 3 | 5 | t2 | 20 |
| 5 | 4 | 6 | t3 | 24 |
| 6 | 5 | 7 | t4 | 28 |
| 7 | 6 | 8 | t5 | 32 |
| 8 | 7 | 9 | t6 | 36 |
| 9 | 10 | 10 | t7 | 40 |
| 10 | 11 | 11 | t8 | 44 |
| 11 | — sampler 0 | 12 | s0 | 48 (heap separado) |

- 11 superficies stateful + 1 sampler; `expected_push_size 52`, `table_pc_base 4`.
- `execution_env`: `grf_count 128`, `simd_size 1`, `has_dpas true`,
  `has_sample true`, `has_fence_for_image_access true`,
  `has_no_stateless_write true`, `offset_to_skip_per_thread_data_load 128`.
- `per_thread`: `packed_local_ids size 6`; cross-thread: `arg0@8`, `arg9@16`,
  `arg10@24` (8 B cada uno) + `private_base_stateless@0` (8 B), en cero según
  packer; auditoría `static-unread-under-full-mask` pendiente de máscara.

## 5. Criterio de éxito (solo offline)

- Build `ocloc` exit 0 (`Build succeeded`; el warning de triples dispares se
  conserva, no se suprime).
- Orden y BTIs **iguales al perfil viejo** (`[8,9,1,2,3,4,5,6,7,10,11]` por
  `arg_index 0…10` + sampler separado, push 52, base 4). Cualquier desvío es
  evidencia nueva: registrar `ze_info.yaml`/hashes reales, no forzar el mapa.
- `code_sha256`/`zebin_sha256` **deben diferir** del pin viejo (el IR cambió de
  `330108` a `358776` B); coincidir sería sospechoso, no éxito.
- `simd_size 1`, `has_dpas`, `has_sample` se re-chquean; `grf_count > 128` u
  otro env divergente no generaliza a otras variantes: reportar por variante.
- No hay gate GPU: sin dispatch, inyección, readback ni aprobación runtime.
  No copiar a cache runtime ni activar helpers con el artefacto nuevo.

## 6. Reproducción mínima

```bash
python -m unittest tests.test_xmx412_toolchain -v
python3 -c "
import sys; sys.path.insert(0,'tools')
import parse_cm_payloads
from pathlib import Path
recs = parse_cm_payloads.parse(Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes())
print(len(recs), sum(1 for r in recs if r['ir_size']==358776))
print(recs[0])
"
```
