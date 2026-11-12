# Regeneración del puente XMX 4.1.2 (CPU-only, sin commit)

Alcance: re-correr los 3 builders y confirmar determinismo + `apply --check`
contra upstream `ef39559`, cross-compilar el shim con el stack 0002→0003,
probar que el registry aceptará una segunda entrada sin cambios de código,
y fijar la secuencia exacta para regenerar 0001 cuando exista el perfil 4.1.2.

Límites respetados: sin ejecutar DLLs, sin GPU/Wine, sin instalar nada, sin
tocar `artifacts/original`, `upstream/`, juegos ni prefijos. Compilación
offline del shim con LLVM-MinGW permitida (precedente
`docs/shim-cross-build.md`). Parches regenerados solo a `/tmp`; no se
sobrescribió ningún archivo versionado. Sin commit.

Verdictos de `docs/xmx412-bridge-recheck.md` vigentes: mantener
0002/0003/0001, registry con 1 entrada, `registry_gen=0x912cda6a`,
`GetCachedBlob` en `E_NOTIMPL`, `rootParameters==13` esperado por DIAG.

## (a) Determinismo de builders + `apply --check` (sin deriva)

Comandos (solo lectura/escritura a `/tmp`, sin modificar el repo):

```sh
python3 tools/build_context_output_patch.py > /tmp/opencode/regen0002.patch
diff -q patches/0002-shim-context-output.patch /tmp/opencode/regen0002.patch
python3 tools/build_context_reuse_patch.py > /tmp/opencode/regen0003.patch
diff -q patches/0003-shim-context-reuse.patch /tmp/opencode/regen0003.patch
python3 tools/build_anv_mapping_patch.py upstream/xess-xmx-linux > /tmp/opencode/regen0001.patch
diff -q patches/0001-anv-cmk3-explicit-mapping.patch /tmp/opencode/regen0001.patch
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0002-shim-context-output.patch"
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0003-shim-context-reuse.patch"
```

Resultado 2026-11-12:

| Pieza | Determinismo | `apply --check` | SHA-256 checked-in |
|---|---|---|---|
| 0002 | idéntico (`diff -q` limpio) | OK | `fa9c302b…7f8508` |
| 0003 | idéntico | OK solo; el orden válido es 0002→0003 (ver stack) | `ef8112d4…554f0c` |
| 0001 | idéntico | OK | `26383938…c38d70` |

Fijado adicional:

- Fuente shim `upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp`
  SHA-256 `aed09d4f…80ca96`, revisión `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- `build_full == build∘build_output` (0003 apilado sobre 0002) verificado en CPU.
- Stack `patch -p1` 0002→0003 en árbol aislado: OK, con
  `CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1)` y 3×
  `liveHalf` presentes.
- Los builders rechazan fuente modificada (`refusing unpinned source`).
- Cubierto por `tests/test_xmx412_bridge_regen.py`
  (`BuilderDeterminismTests`, `PatchApplyTests`): 17/17 OK.

Sin deriva: ninguna regeneración difiere del parche versionado.

## (b) Cross-compilación del shim, stack 0002→0003 (14/14, sin errores)

Secuencia exacta ejecutada (copia aislada en `/tmp`, sin tocar upstream):

```sh
rm -rf /tmp/opencode/xmx412-shim-stack-v01 && mkdir -p /tmp/opencode/xmx412-shim-stack-v01
cp -a upstream/xess-xmx-linux/shim /tmp/opencode/xmx412-shim-stack-v01/source
patch -p2 --batch --forward -d /tmp/opencode/xmx412-shim-stack-v01/source \
  -i "$PWD/patches/0002-shim-context-output.patch"
patch -p2 --batch --forward -d /tmp/opencode/xmx412-shim-stack-v01/source \
  -i "$PWD/patches/0003-shim-context-reuse.patch"
TC="$PWD/artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin"
cmake -S /tmp/opencode/xmx412-shim-stack-v01/source \
  -B /tmp/opencode/xmx412-shim-stack-v01/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/opencode/xmx412-shim-stack-v01/obj -j 4
```

Resultado:

- Configure: `Clang 23.1.4`, `Generating done`, exit 0.
- Build: **[14/14], 0 errores, 0 warnings** en el log
  (`/tmp/opencode/xmx412-shim-stack-v01-build.log`).
- DLL: `obj/igdext64.dll`, 1.616.896 B,
  SHA-256 `3aff7abf…3054d1`, PE32+ AMD64.
- `x86_64-w64-mingw32-objdump -p`: **75 exports con nombre** (misma forma que
  el baseline documentado), imports `KERNEL32.dll`, `ADVAPI32.dll` + familia
  UCRT (`api-ms-win-crt-*`), sin `MSVCP` dinámico inesperado.
- Fuentes de `/tmp/opencode/xmx412-shim-stack-v01/source` idénticas a
  `/tmp/opencode/shim-cross-reuse-v01/source` (`diff -r` limpio).

Nota sobre hashes: la DLL no se declara bit-reproducible. El build previo
documentado (`8afc4973…`, mismo tamaño y 75 exports) difiere solo por
timestamp/rutas embebidas; lo que se afirma es 14/14 + misma forma de
exports/imports, no igualdad de hash. La variante MSVC/Windows-SDK no se
compiló; UCRT sigue pendiente de validación runtime como ya se sabía.

## (c) El registry aceptará una segunda entrada sin cambios de código

`tools/pre_profile_registry.py` + `tools/build_anv_mapping_patch.py` son
genéricos respecto al número de entradas: validan cada fila (claves,
`code_sha256` único 64-hex, `0 <= base < expected <= 256` alineado a 4,
fichero de perfil existente) y mezclan `registry_gen()` en
`anv_cm_toolchain_gen`. Ninguna rama asume “1 entrada”.

Prueba sintética (sin tocar `profiles/registry.json`; el fragmento real de
`profiles/xmx412-pins.json` sigue todo `REQUIRED-TBD`):

- Segunda entrada sintética en memoria: `kernel fsr4_pre_xmx`,
  `variant synthetic-412-native1080`, `code ab*32`, `input cd*32`,
  `zebin ef*32`, `profile profiles/fsr4-pre-native1080-bmg.json`
  (reuso del fichero existente solo para pasar el check de existencia sin
  crear archivos en el repo), `base 8`, `push 56`, `surfaces 11`.
  **No es un pin 4.1.2.**
- `load()` sobre fichero temporal con las 2 entradas: OK, 2 filas,
  `find_profile` devuelve la vieja (`2e42d33c…` → `(4,52)`) y la sintética
  (`ab*32` → `(8,56)`), `None` para `00*64`, `ff*64` y `REQUIRED-TBD`.
- `registry_gen` sintético `b2c0cc64` ≠ `912cda6a`, estable y ligado al
  contenido (mutar `expected_push_size` lo cambia).
- Con `load_registry` mockeado a las 2 entradas, `adapt()` incrusta
  `h = (h ^ 0xb2c0cc64u)` y ya no contiene `0x912cda6a`, más el comentario
  `LOCAL profile generation`.
- Fail-closed intacto: el fragmento `future_registry_entry_fragment` (todo
  `REQUIRED-TBD`) sigue rechazado por `load()`; duplicados, base
  desalineada (`5`) y perfil inexistente también son `ValueError`; ningún
  digest 4.1.2 (`raw_sha256` de packs) hace hit en el registry real.

Si un builder necesitara un cambio para la 4.1.2 real, no se aplica aquí:
se propondría sin editar. Hoy no hace falta: la capa registry/mapping no
pide cambios. Advertencia conocida: `tools/build_pre_profile.py` sigue
fijado a los hashes/BTIs del PRE 4.0.2x (`EXPECTED_INPUT/ZEBIN/BTIS`); el
perfil 4.1.2 real necesitará su propio aislamiento/auditoría y, en su caso,
nuevo tooling de generación — nunca copiar base-4/push-52 al hash nuevo.

Cubierto por `tests/test_xmx412_bridge_regen.py`
(`RegistryTwoEntryTests`, `FailClosedTests`).

## (d) Secuencia EXACTA para regenerar 0001 cuando exista el perfil 4.1.2

No ejecutada (el perfil no existe: todo `pre_xe2_412` es `REQUIRED-TBD`).
Cuando `profiles/xmx412-pins.json` resuelva cada TBD, en este orden:

```sh
# 1. Aislar el envelope PRE Xe2 (pack 40102, clase native/1080p) y compilar
#    offline con el toolchain fijado (IGC 2.10.10+18926, ocloc 25.18.33578.6,
#    device 0xe20b). Registrar input/zebin/code SHA-256.
mkdir -p analysis/offline-pre-412/full
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/cm-payloads-412/module-XXXX.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412/full" \
  -output pre -options '-vc-codegen'

# 2. Inspeccionar el zebin y auditar el payload (estático, CPU-only).
python tools/inspect_zebin.py analysis/offline-pre-412/full/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/offline-pre-412/full/summary.json
# 3. Generar el NUEVO fichero de perfil (no editar el viejo). Nota: el
#    builder actual está fijado al PRE 4.0.2x; si rechaza el nuevo input,
#    proponer el cambio sin aplicarlo y documentar el nuevo builder/pins.
python tools/build_pre_profile.py analysis/cm-payloads-412/module-XXXX.cmspv \
  analysis/offline-pre-412/full/pre_bmg.bin > profiles/fsr4-pre-412-native1080-bmg.json

# 4. Añadir la NUEVA entrada a profiles/registry.json (conservar la vieja),
#    rellenando future_registry_entry_fragment con code/input/zebin reales,
#    profile nuevo, base/push/surfaces auditados. Validar:
python tools/pre_profile_registry.py <nuevo_code_sha256>
python -m unittest tests.test_profile_selection -v
python -m unittest tests.test_xmx412_pins -v

# 5. Regenerar 0001 (única escritura versionada de esta secuencia) y comprobar:
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux \
  > /tmp/anv-mapping-412-regen.patch
cp /tmp/anv-mapping-412-regen.patch patches/0001-anv-cmk3-explicit-mapping.patch
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest tests.test_profile_selection tests.test_xmx412_bridge_regen -v
```

Efecto esperado de (5): solo cambia el digest embebido
(`0x912cda6a` → nuevo `registry_gen()`) en ambas variantes internas más el
recuento de hunks; la ruta CMK2 global queda intacta y los hashes
desconocidos siguen en legacy por miss.

## Salidas de esta tarea

- `tests/test_xmx412_bridge_regen.py`: 17 tests (determinismo, `apply --check`,
  registry sintético de 2 entradas, fail-closed).
- Este doc (`docs/xmx412-bridge-regen.md`).
- Artefactos efímeros en `/tmp/opencode` (regeneraciones, árbol y build del
  shim, logs): no versionados.
- Ningún parche, perfil, registry ni builder modificado; sin commit.
