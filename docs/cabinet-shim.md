# cabinet.dll sustituto mínimo (juego-local)

Sustituto parcial de `Cabinet.dll` que solo existe para desbloquear la carga
de los packs embebidos del mod XMX bajo Wine/Proton. No es una
reimplementación de Cabinet: exporta únicamente los 3 ordinales de la
Compression API que el loader usa, solo para LZMS. Sin ejecución bajo Wine
en esta fase (CPU-only); ver §7.

## 1. Problema y evidencia

- Spider-Man + mod XMX 4.1.2 (DLL `fadbcb50…`, vieja 4.0.2x `3eb086…`)
  aborta al cargar packs:
  `wine: Call from ... to unimplemented function Cabinet.dll.40, aborting`
  (log completo en
  `build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/vkd3d-trace.log`;
  tras el abort solo hay mensajes de FSR4/vkd3d, sin inyección válida).
- El loader es `FUN_180029640` (`docs/xmx412-pack-envelope.md`): por índice
  resuelve `FindResourceW → malloc(expected) → Cabinet ordinal 40` (con el
  algoritmo 5 en el primer argumento) `→ ordinal 43` (descomprime el recurso
  completo, salida limitada al tamaño esperado; el tamaño debe coincidir
  **exactamente**) `→ ordinal 45` (libera) `→ BCryptHash SHA-256` y compara
  con el digest compilado. Fallo ⇒ `embedded pack %u invalid` y `NULL`.
- Verificado estáticamente: ambas DLL importan de `Cabinet.dll` **solo**
  los ordinales 40/43/45 (por ordinal, sin nombre), y de `bcrypt.dll` solo
  `BCryptHash` (ordinal 36).
- Verificado: `cabinet.dll` de Wine (todos los Proton/GE/cachyos locales y
  `/usr/lib/wine`) no exporta **ninguna** función de Compression API
  (solo FDI/FCI). No hay ninguna `cabinet.dll` nativa de Microsoft en la
  máquina. Conclusión: ninguna build del mod puede cargar packs bajo Wine
  actual sin este (u otro) aporte.
- La semántica necesaria ya estaba validada en el repo:
  `tools/decompress_mscf.py` + `tools/decompress_xmx412.py` descomprimen
  los 6 packs con libwim local (LZMS, bloques de 64 KiB, tamaño exacto + SHA
  obligatorios).

## 2. Qué implementa

| Ordinal | Nombre MS real | Firma (x86-64, `compressapi.h` del toolchain) | Rol verificado en el loader |
|---|---|---|---|
| 40 | `CreateDecompressor` | `BOOL(DWORD Algorithm, PCOMPRESS_ALLOCATION_ROUTINES AllocationRoutines, PDECOMPRESSOR_HANDLE Handle)` | Llamada con `Algorithm = 5` (`COMPRESS_ALGORITHM_LZMS`) antes de cada pack |
| 43 | `Decompress` | `BOOL(HANDLE, PVOID In, SIZE_T InSize, PVOID Out, SIZE_T OutSize, PSIZE_T Produced)` | Descomprime el recurso completo; el loader exige `Produced == expected` exacto |
| 45 | `CloseDecompressor` | `void(HANDLE)` | Libera el descompresor antes del `BCryptHash` |

Nota de nomenclatura: la tarea lo llamaba `DestroyDecompressor`; el nombre
real en el SDK (`compressapi.h`, confirmado en los exports de la
`cabinet.dll` de Microsoft: CreateDecompressor→40, Decompress→43,
CloseDecompressor→45) es `CloseDecompressor`. El loader importa **por
ordinal**, así que el nombre solo importa para humanos y herramientas; se
exportan los nombres MS correctos con los ordinales correctos.

Comportamiento:

- `CreateDecompressor` acepta `5` (`LZMS`) y `5 | COMPRESS_RAW`
  (`0x20000000`); cualquier otro algoritmo ⇒ `FALSE` + `ERROR_NOT_SUPPORTED`.
  `AllocationRoutines == NULL` usa el heap del proceso; si se pasan
  callbacks propios se respetan (vía TLS alrededor de crear/liberar).
- `Decompress` en modo buffer valida el contenedor de 24 bytes (magia
  `0A 51 E5 C0`, tamaño 24, CRC-8 de cabecera, algoritmo 5, reservas a cero,
  `total` 1…128 MiB, bloque 1…64 MiB), recorre `{u32 len, bytes}` y por
  bloque llama al decodificador LZMS crudo de wimlib o copia verbatim
  cuando `len == resto` (igual que `tools/decompress_mscf.py`). Fallo
  cerrado ante: truncado, bytes sobrantes, magia/CRC/campos mal,
  `OutSize < total` (`ERROR_INSUFFICIENT_BUFFER` — esto es lo que impone el
  tamaño exacto del loader), parámetros nulos. `OutSize > total` se acepta
  e informa el `total` exacto.
- `Decompress` en modo `COMPRESS_RAW` decodifica la entrada como un único
  bloque LZMS crudo (vía auxiliar, probada con el primer chunk real de
  40102; el loader no usa este modo).
- Handles inválidos, doble `Close` y `NULL` no cuelgan ni corrompen
  (probado en `tests/test_cabinet_shim.py`).
- Decodificador LZMS: 4 TUs de wimlib compilados tal cual desde el checkout
  local (`upstream/wimlib @ cd5e231…`, rev fijada en `report.json`):
  `lzms_decompress.c`, `lzms_common.c`, `decompress_common.c` y
  `compress_common.c` (este último solo por `make_canonical_huffman_code`,
  necesario para el rebuild adaptativo de Huffman). Sin init global de
  wimlib: el wrapper ataca `lzms_decompressor_ops` directamente.
  `cpu_features = 0` fuerza la ruta portable del filtro x86 (la vía SSE4.2
  es solo optimización; resultados bit-idénticos, probado).
- Dependencias de carga de la DLL: solo `KERNEL32.dll` (heap + errores +
  arranque CRT) y los api-sets `api-ms-win-crt-runtime-l1-1-0` /
  `api-ms-win-crt-stdio-l1-1-0` del arranque MinGW. Nada de red, drivers,
  FDI/FCI ni UCRT directo. Binario: PE32+ x86-64, ~70 KB.

## 3. Qué NO implementa

- Resto de Compression API: 30 `CreateCompressor`, 31/41 `Set*Information`,
  32/42 `Query*Information`, 33 `Compress`, 34/44 `Reset*`,
  35 `CloseCompressor`. Los slots 41/42/44 de la tabla de exports existen
  vacíos (RVA 0): importarlos falla limpiamente.
- FDI/FCI, `Extract`, `GetDllVersion`, etc. Este shim **no** los trae; la
  `cabinet.dll` de Wine sí los tiene.
- Compresores ni otros algoritmos (MSZIP/XPRESS). `Create` con otro
  algoritmo falla con `ERROR_NOT_SUPPORTED`.
- No hay `DllRegisterServer`, ni firma Authenticode (irrelevante bajo Wine).

## 4. Construcción reproducible

```sh
python3 tools/build_cabinet_shim.py
```

- Toolchain: `artifacts/extracted/llvm-mingw-20261020-ucrt/` (Clang 23.1.4,
  precedente en `docs/shim-cross-build.md`). No se instala nada ni se
  ejecuta ningún binario producido: solo compilar + enlazar + inspeccionar.
- Fuentes: wrapper + `.def` embebidos en el script (única fuente
  versionada); los 4 TUs se compilan **in situ** desde `upstream/wimlib`
  (solo lectura, nunca se modifican).
- Salidas (todo bajo `build/cabinet-shim/`, ignorado por git):
  `cabinet.dll`, `src/`, `obj/`, `test/libcabinet_shim_test.so` (gemelo
  host con las mismas fuentes para tests vía ctypes, sin Wine) y
  `report.json` (rev wimlib, SHA-256 de TUs/wrapper/DLL/.so, exports,
  imports y comandos exactos; la DLL queda fijada por su SHA).
- El propio script verifica: PE32+ x86-64, exports exactamente
  40/43/45 con los nombres MS, e imports dentro de la lista permitida.
  Cualquier deriva falla el build.
- El SHA de la DLL identifica la ejecución: el linker estampa la hora en
  la cabecera PE (mismo precedente que el shim XESS en
  `docs/shim-cross-build.md`; no se declara bit-a-bit reproducible). La
  equivalencia funcional entre builds se establece re-ejecutando los tests.

## 5. Verificación CPU

```sh
python3 -m unittest tests.test_cabinet_shim
```

24 tests, OK el 2026-11-12. Cubren:

- Contrato de exports/imports sobre el PE (ordinales, nombres, PE32+,
  allowlist de DLLs).
- Los **6 packs** descomprimen byte-idénticos a `analysis/fsr-xmx-412/` vía
  el gemelo host (mismas fuentes que la DLL), con SHA-256 y tamaño de los
  pines de `tools/decompress_xmx412.py`.
- Rechazos: algoritmo no soportado, buffer corto (tamaño inexacto), buffer
  mayor (informa el exacto), truncado, sobrante, magia/CRC/campos mal,
  nulos y ceros, doble `Close`, chunk verbatim sintético, bloque RAW con
  chunk real, y callbacks de asignación propias.

## 6. Instalación juego-local (manual, con el juego cerrado)

1. Copiar `build/cabinet-shim/cabinet.dll` al lado de `Spider-Man.exe`.
   No copiarla a ningún `system32`/`syswow64` de prefijos ni a directorios
   de Proton/Wine: el shim es parcial y solo debe existir junto al juego.
2. Lanzar con override nativo-primero para Cabinet, sumado al resto del
   entorno del run de traza:
   `WINEDLLOVERRIDES="cabinet=n,b"`.
3. Éxito esperado: desaparece el abort `unimplemented function
   Cabinet.dll.40` y el log muestra packs cargados/recursos FSR4 aguas
   abajo. Si aparece `embedded pack %u invalid`, el shim funcionó y el
   problema es otro (anotar bytes y abortar la captura).
4. Reversión: borrar el archivo del directorio del juego.

## 7. Riesgos, límites y qué falta

- Sosías parcial: no implementa FDI/FCI ni nada fuera de 40/43/45. Con el
  override `n,b`, otro consumidor de Cabinet en ese prefijo caería al
  builtin de Wine (que tampoco los tiene) o fallaría; por eso la
  instalación es solo juego-local.
- Nunca cargado bajo Wine todavía: la primera carga real es el próximo run
  del usuario. Los 24 tests CPU cubren el gemelo host, no el loader de
  Wine.
- El SHA de la DLL varía por timestamp PE (mismo precedente que el shim
  XESS); la equivalencia funcional se establece re-ejecutando los tests.
- Si Wine/Proton implementa la Compression API algún día, este shim deja
  de hacer falta (borrar el archivo basta).
...[truncated 3881 chars]
