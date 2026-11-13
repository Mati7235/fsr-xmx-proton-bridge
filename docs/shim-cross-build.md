# Compilación cruzada del shim, sin ejecución

Se compiló el shim completo desde Linux para Windows x86-64. Esto comprueba
compilación/enlace, **no** que Wine/Proton cargue la DLL ni que FSR funcione.
No se instaló el toolchain, no se ejecutó la DLL y no se alteró ningún prefijo.

## Procedencia

- Upstream: `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3` (revalidación
  2026-11-13); la baseline histórica de este documento se tomó sobre
  `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- Toolchain: LLVM-MinGW `20261020`, UCRT, Ubuntu 22.04 x86-64, Clang 23.1.4.
- Archivo original local:
  `artifacts/original/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64.tar.xz`.
- SHA-256 comprobado contra el digest del release de GitHub:
  `55064b60b991a1e1e8090b8c2f84e82b22cfe5903d12c159d65064cf5e8ae335`.
- Release: <https://github.com/mstorsjo/llvm-mingw/releases/tag/20261020>.
- Extracción local con `tarfile`, filtro `data`, dentro de
  `artifacts/extracted/llvm-mingw-20261020-ucrt/`.

El archivo original permanece inmutable. Toolchain, fuentes upstream y DLLs
generadas quedan ignorados por Git; no se redistribuyen aquí.

## Baseline y configuración

Se copió `upstream/xess-xmx-linux/shim/` a
`build/shim-cross-baseline-v01/source/`, sin modificar el checkout upstream.
La primera compilación falló en `Trace.cpp:62`: `__try` no reconocido.
Se habilitaron las extensiones Microsoft de Clang mediante `-fms-extensions`;
no se eliminó ni reemplazó el bloque de manejo de excepciones.

Comandos de configuración, una vez preparada la copia de fuentes:

```sh
TC="$PWD/artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin"
cmake -S build/shim-cross-baseline-v01/source \
  -B build/shim-cross-baseline-v01/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build build/shim-cross-baseline-v01/obj -j 4
```

Los 13 objetos y el enlace terminaron correctamente. La inspección estática con
`llvm-readobj --file-headers --coff-imports` identifica una DLL PE32+ AMD64.
La DLL baseline tiene 1.615.360 bytes y SHA-256
`43dec833e340cc75ad36d29200e2c5958c6ded8beb1eca5753c7d94d40f92e01`.
Ese hash identifica esta ejecución: no se declara una build bit-a-bit reproducible.
El reporte local `build/shim-cross-baseline-v01/report.json` registra hashes de
fuentes, DLL e imports; `pe-inspection.txt` conserva la inspección completa.

## Límites de esta build

### Variante con corrección de contexto

Se copió el baseline a `build/shim-cross-context-v01/source/` y se aplicó
`patches/0002-shim-context-output.patch` con `patch -p2` desde esa copia.
Solo cambió `src/dll/IgdextApiDll.cpp`. Se repitieron la configuración y el build
anteriores sustituyendo `shim-cross-baseline-v01` por `shim-cross-context-v01`.

Los 13 objetos y el enlace terminaron correctamente. La DLL parcheada tiene
1.615.872 bytes y SHA-256
`c5b5620f5b8dca1fa44ad853e30cae31a6541a779d896c90810802cc4afbde0d`.
El parche usado tiene SHA-256
`fa9c302b4cc3cc9ac4fff746c41c17d94a06e879e37f50da60f116f3337d8508`.
Los 75 exports (nombre y ordinal) y la lista de DLLs importadas coinciden con el
baseline. No se afirma que las direcciones o todo el PE sean idénticos.
El reporte y la inspección están en `build/shim-cross-context-v01/report.json`
y `pe-inspection.txt`. Ver [corrección y tests CPU](context-output-fix.md).

### Revalidación sobre 662dc6e (stack 0002→0003)

La copia aislada debe incluir `common/`, porque el shim nuevo incluye
`../../../common/lowlat_check.h`. Se copiaron `shim/` y `common/` a
`/tmp/opencode/xmx662-shim-stack/tree/`, se aplicaron los parches nuevos con
`patch -p2` desde `tree/shim`, y se configuró/compiló con el mismo LLVM-MinGW
`20261020` UCRT y `-fms-extensions`.

```sh
cp -a upstream/xess-xmx-linux/shim /tmp/opencode/xmx662-shim-stack/tree/shim
cp -a upstream/xess-xmx-linux/common /tmp/opencode/xmx662-shim-stack/tree/common
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0002-shim-context-output.patch"
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0003-shim-context-reuse.patch"
cmake -S /tmp/opencode/xmx662-shim-stack/tree/shim \
  -B /tmp/opencode/xmx662-shim-stack/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/opencode/xmx662-shim-stack/obj -j 4
```

Resultado: **14/14 objetos + enlace, 0 errores, 0 warnings**. DLL
`igdext64.dll` de 861.184 bytes, SHA-256
`0a0b54623be219a7a809eb1b628ebfcc4583bff472c097500be840f69bca8cf8`,
PE32+ AMD64, **79 exports con nombre**, imports `KERNEL32.dll`,
`ADVAPI32.dll` y familia UCRT `api-ms-win-crt-*`. La DLL es más pequeña que la
baseline de `ef39559` porque upstream eliminó las tablas de kernels estáticos y
movió el empaquetado CMK2 al driver. Los parches usados son 0002
(`fc00a77dd81b9efc6ef3bd61affaa594752c50ebbb27f5a95bad13d39f93f263`) y 0003
(`ef8112d46f70f6242de9509926a35e66c6fe417a50947adff86c5caf855f054c`).
No se ejecutó la DLL. El reporte local queda en
`build/shim-cross-662dc6e/report.json` (ignorado por Git), junto con los logs y
la inspección PE.

### Validación pendiente

La variante UCRT enlaza el runtime C++ estáticamente según el CMake upstream,
pero **mantiene imports de las API de UCRT**, además de KERNEL32 y ADVAPI32.
No equivale a la distribución MSVC con CRT totalmente estático de upstream.
No se comprobó disponibilidad de esos imports en ningún prefijo.

No hay prueba de carga, llamadas reales de contexto, detección de GPU ni
inyección bajo Proton. No copiar este artefacto a un juego como si estuviera
validado; una prueba runtime posterior requiere autorización y entorno descartable.
