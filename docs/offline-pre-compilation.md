# Compilación offline y primer prototipo del mapa

## Resumen sin jerga

La receta inicial del mod **sí compila para una B580 con la herramienta usada por
xess-xmx-linux**. Ahora conocemos el orden real que espera el código generado.
Además hicimos un prototipo que conserva ese orden y separa el casillero del
sampler, en lugar de adivinar tomando los últimos casilleros.

No ejecutamos ese código en la GPU. El prototipo no se instaló ni se conectó a
Steam. Que compile no demuestra que procese correctamente una imagen.

## Herramientas y alcance

- IGC `2.10.10+18926`, ocloc `25.18.33578.6` (binario ocloc-25.18.1).
- Paquetes oficiales descargados y extraídos **sin instalación** dentro de
  `artifacts/extracted/intel-toolchain/`.
- Se verificaron SHA-256 contra las publicaciones; ver `profiles/intel-toolchain.json`.
- Target explícito `0xe20b`, identificado localmente como B580/Battlemage G21.
- Se usó el compilador offline, sin carga de la DLL, lanzamiento del juego ni dispatch GPU.
- Input: primer PRE del pack Xe2 40102, variante native_1080, con su pie CM completo.
- Upstream shim/ANV de referencia: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- Layout VKD3D de referencia: `ef9a02e873715c9e2da0d6db8a236aca8380b303`.

## 1. Compilación y control de opciones

Con el input completo y `-options '-vc-codegen'`:

- Exit 0, `Build succeeded`; warning de triples LLVM diferentes, conservado en el log.
- Zebin: 365504 bytes, `.text.fsr4_pre_xmx`: 29376 bytes.
- GRF count **128**, SIMD size **1**, `has_dpas=true`, `has_sample=true`.
- Payload cross-thread: el packer legado calcula 32 bytes; per-thread: 64 bytes.
- No `grf_count > 128` en este PRE; eso no permite generalizar a otras variantes.

Se repitió la compilación completa y se hizo un control quitando el pie CM:

| Input | SHA-256 código nativo | Build options registradas |
|---|---|---|
| Completo, dos ejecuciones idénticas | `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` |
| SPIR-V sin pie | `31418b6e18b394a874ea6dcc2ff667e48f5305f623fb66955ee39862c46d7346` | `-vc-codegen` |

**Confirmado para esta combinación:** el compilador consume opciones del pie;
no eran simplemente texto decorativo ni desaparecen por el filtro externo del helper.
Ambos outputs tienen el mismo mapa BTI, pero distinto código: identificar solo por
nombre del kernel o BTIs sería insuficiente. El generador del perfil fija tanto
el SHA-256 del input completo como el del zebin revisado y rechaza el control sin opciones.

SHA-256 input completo:
`76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`

SHA-256 zebin completo, reproducido dos veces:
`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`

## 2. Orden confirmado por el compilador

BTI es el número interno de casillero que usa el código de GPU; no es el número
de root parameter ni el slot relativo dentro del heap.

| Arg | BTI del compilador | Root D3D12 esperado | Registro | Offset push esperado |
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
| 11 | —, sampler index 0 | 12 | s0 | 48, heap separado |

Hay once superficies stateful y un sampler. Los tipos de los argumentos coinciden
con el PRE inspeccionado previamente. El orden del packer por `arg_index` es el
necesario para esta correspondencia; todavía no es una traza de lecturas GPU.

## 3. Desarrollo del prototipo, sin instalación

Nuevas piezas:

- `tools/inspect_zebin.py`: lee ELF y la forma restringida de `.ze_info`; nombres
  de kernel exactos, sin confundir prefijos. No es un parser YAML general.
- `tools/build_pre_profile.py`: genera un perfil para **un input y un output
  revisados**, rechaza cambios de identidad/opciones y verifica BTIs y entorno.
- `profiles/fsr4-pre-native1080-bmg.json`: evidencia y mapa explícito por argumento.
- `tools/apply_cmk_mapping.py`: convierte un CMK2 local revisado a un formato
  **CMK3 experimental de este proyecto**, sin alterar el código nativo.
- `tools/build_anv_mapping_patch.py`: genera un parche para los dos parches ANV
  upstream, manteniendo intacto el checkout.
- `patches/0001-anv-cmk3-explicit-mapping.patch`: candidato generado y revisable.

El nuevo formato no reutiliza silenciosamente CMK2: un lector viejo rechaza
`CMK3` por su magic. Conserva el header legado de 472 bytes y añade antes del
código 8 bytes: flags `1` (base explícita) y tamaño push esperado `52`.
El código nativo comienza en byte **480**.

El lector candidato:

1. Sigue leyendo CMK2 con su comportamiento anterior.
2. Para CMK3 comprueba flags, nsurf, alineación y extensión.
3. Exige tamaño push máximo exacto de 52 bytes según el perfil.
4. Comprueba con aritmética de 64 bits que cada DWORD esté cubierto por un rango.
5. Sigue detectando automáticamente el heap, pero **no reemplaza la base explícita 4**
   por la inferencia de cola que daba 8.

El adaptador comprueba la identidad del código nativo y los BTIs antes de emitir
el nuevo header. El sampler no entra en las once superficies.

**Límites importantes:** el parche del lector no se compiló dentro de Mesa ni se
aplicó a un driver instalado. Se comprobó que aplica al checkout fijado y que los
parches Mesa internos mantienen sintaxis válida. El bloque C de validación insertado
se compiló y ejecutó con estructuras sintéticas en CPU; no es una compilación del
resto del driver. La selección de perfil por hash y el bump de cache identity
son candidatos offline (`profiles/registry.json`, `tools/pre_profile_registry.py`,
`docs/profile-selection-cache-identity.md`); el helper runtime sigue sin leerlos.

## 4. Qué falta antes de una prueba GPU

El compilador revela detalles que no debemos dar por resueltos:

- Args de buffers stateful 0, 9 y 10 tienen también campos de **8 bytes** en offsets
  cross-thread **8, 16 y 24**. El packer upstream los deja en cero.
- `private_base_stateless` ocupa **8 bytes en offset 0**; también queda en cero.
- **Avance posterior:** la [auditoría estática del payload](pre-payload-audit.md)
  no encuentra lecturas de los cuatro campos antes de sobrescribirlos o terminar,
  suponiendo máscara de ejecución completa y constante. No se identificó necesidad
  de inicializarlos con direcciones en este binario; falta validar esa máscara.
- Dimensiones locales 1x1x1 usadas al empaquetar son provisionales; SIMD1 no las prueba.
- El sampler sigue usando el fallback del driver, no el descriptor dinámico real.
- Falta identificar el layout del Proton que se vaya a usar en runtime.
- Falta corregir/cubrir la devolución de información GPU del contexto.
- Los demás kernels y variantes no están cubiertos por este perfil.

 Por eso el perfil y el artefacto CMK3 llevan estado **experimental-offline-only**.
No copiarlos a un cache runtime. No activar el helper con ellos todavía.

## 8. Promoción 4.1.2 (estado actual, sin runtime)

La serie 4.1.2 cerró el hueco que dejaba este documento en §4/§7:

- Perfil nuevo `profiles/fsr4-pre-412-native1080-bmg.json`
  (`experimental-offline-only`): `input ce372719…`, `code 68b962b5…`,
  `zebin b1781bb4…`, `surface_count 11`, `push 52`, `base 4` (misma
  derivación que el viejo: mismo orden/BTIs + mismo `ze_info`).
- Auditoría `profiles/fsr4-pre-412-native1080-payload-audit.json`:
  `static-analysis-only` / `unread-before-overwrite-or-end`
  (160 visitadas, 0 lecturas); ver [macl/acc0](xmx412-macl-acc0.md).
  `runtime_approved=false` se mantiene.
- `profiles/registry.json` ya tiene **2 entradas** (vieja `2e42d33c…` +
  nueva `68b962b5…`). Digest de cache `registry_gen()` pasó de
  `0x912cda6a` (1 entrada) a **`0x3ddd809f`** (2 entradas), embebido en
  `patches/0001-anv-cmk3-explicit-mapping.patch` (ambas variantes
  `anv_cm_toolchain_gen`). Miss → ruta legacy CMK2, sin cambio global.
- Detalle de compilación/auditoría en [offline 4.1.2](xmx412-offline-compile.md);
  recheck/regen del puente en [recheck](xmx412-bridge-recheck.md) y
  [regen](xmx412-bridge-regen.md).

Qué falta (no es runtime): traza Fase 1 autorizada (grid real, tablas,
DIAG `rootParameters==13`, bytes pre/post), oracle de salida, máscara/
local-size, helper nuevo y tabla de variantes 4.1.2. `profiles/xmx412-pins.json`
sigue como staging con `REQUIRED-TBD` (deuda documental, no bloquea el
registry ya promovido). Nada se copia a cachés runtime ni se instala.

## 5. Reproducción

Descargar de las URLs y verificar los hashes de `profiles/intel-toolchain.json`.
Los dos deb de IGC contienen `data.tar.gz`; el de ocloc contiene `data.tar.zst`.
Extraer solo esos archivos, no ejecutar maintainer scripts ni instalar paquetes.

Ejemplo de compilación desde la raíz del proyecto, con las extracciones presentes:

```bash
mkdir -p analysis/offline-pre/full
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/cm-payloads-0001/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre/full" \
  -output pre -options '-vc-codegen'

python tools/inspect_zebin.py analysis/offline-pre/full/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/offline-pre/full/summary.json
python tools/build_pre_profile.py analysis/cm-payloads-0001/module-0000.cmspv \
  analysis/offline-pre/full/pre_bmg.bin > analysis/offline-pre/profile-reproduced.json

# Packer upstream previamente leído; solo escribe este artefacto local.
CMK_GC=1,1,1 CMK_GRF_BYTES=64 python upstream/xess-xmx-linux/tools/cmk_pack.py \
  analysis/offline-pre/full/pre_bmg.bin fsr4_pre_xmx 1 1 1 \
  analysis/offline-pre/full/pre-legacy.cmk --heap auto --surf auto
python tools/apply_cmk_mapping.py analysis/offline-pre/full/pre-legacy.cmk \
  profiles/fsr4-pre-native1080-bmg.json analysis/offline-pre/full/pre-explicit.cmk3

# Solo comprobar el parche, NO aplicarlo ni instalar drivers.
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest discover -s tests -v
```

El adaptador rechaza sobrescribir outputs. Los artefactos de compilación permanecen
ignorados por Git; solo se versionan código, documentación, parche y metadata.
