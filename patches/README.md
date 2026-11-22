# Parches experimentales — no instalados

`0001-anv-cmk3-explicit-mapping.patch` modifica **los archivos de parche Mesa** de
xess-xmx-linux, no directamente un driver instalado. Es un parche de segundo nivel
para upstream `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3` (2026-11-13). El lector
CMK3 se inserta en el `anv_cm.c` nuevo de upstream; la ruta CMK2 y el lector del
layer (`layer/src/cmk.c`) quedan intactos.

Generación y comprobación sin modificar upstream:

```bash
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux \
  > analysis/anv-mapping-reproduced.patch
cmp patches/0001-anv-cmk3-explicit-mapping.patch analysis/anv-mapping-reproduced.patch
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
```

La regeneración incorpora el digest del registro de perfiles
(`profiles/registry.json`, vía `tools/pre_profile_registry.py`) en
`anv_cm_toolchain_gen` de ambas variantes internas: cualquier cambio del
registro invalida los kernels cacheados sin alterar la ruta CMK2 global.
Ver `docs/profile-selection-cache-identity.md`.

`.gitattributes` excluye estos diffs anidados del chequeo de whitespace: sus líneas
de contexto contienen espacios significativos. Se validan mediante regeneración,
comparación exacta y `git apply --check`, no recortando esos espacios.

Añade un lector CMK3 local, con base de tablas explícita y comprobación del tamaño
push y cobertura de cada DWORD. Mantiene la ruta CMK2 existente. El formato CMK3
**no es un formato publicado por upstream** y requiere este lector; no usar sus
artefactos con un driver original.

Estado: `git apply --check`, sintaxis de ambos parches internos y validación C
extraída con layouts sintéticos comprobadas. **No compilado dentro de Mesa, no
probado en GPU.** La selección de perfil por hash y el bump de cache identity
son candidatos offline (`profiles/registry.json`,
`tools/pre_profile_registry.py`); el helper runtime sigue sin leerlos.

`0002-shim-context-output.patch` conserva el helper compartido de copia de
outputs. Upstream `662dc6e` ya incorporó esa copia inline en los dos exports
legacy; el parche reemplaza esas copias por el helper para que 0003 lo reutilice
(el comportamiento es equivalente). `0003-shim-context-reuse.patch` extiende la
copia de outputs al path de reutilización D3D12 (valida device y versión contra
el contrato otorgado; apilado **después** de 0002, generado por
`tools/build_context_reuse_patch.py`, CPU-probado en
`tests/test_context_reuse.py`). Ver `docs/context-reuse-fix.md`.

Los payloads de argumentos, dimensiones locales, samplers y otros kernels siguen
pendientes. Ver `docs/offline-pre-compilation.md`. No aplicar a la sesión del
usuario ni instalar servicios/drivers como parte de las pruebas de CPU.

`0005-vkd3d-keep-coopmat-extension.patch` modifica **el checkout de vkd3d-proton**
(worktree `upstream/vkd3d-proton-coopmat`, base `2576c0b4`, la misma revisión que
embarca Proton Experimental `experimental-11.0-20261112`), no ningún Proton ni
prefijo instalado. Con `VKD3D_KEEP_COOPMAT_EXTENSION=1` y un driver que anuncia
`cooperativeMatrix` pero no pasa `vkd3d_supports_minimum_coopmat_caps()`
(caso ANV Xe2 en B580: solo 8x16x16 f16/bf16 y 8x16x32 s8/u8, falta el
16x16x16 f16→f32 exigido), mantiene `VK_KHR_cooperative_matrix` habilitado en
el `VkDevice` (extensión + feature tal como lo anuncia el driver, incluido
`cooperativeMatrixRobustBufferAccess` si el driver lo soporta) para consumidores
interop que comparten el dispositivo (p. ej. el FG de Apex Neural Rendering vía
OptiScaler). Todo lo que expondría WMMA a D3D12 queda apagado como si el gate
hubiera fallado: features float8/coopmat2, `SupportsAGSExtension(WMMA_FP8)` y la
validación de meta `USES_COOPERATIVE_MATRIX` usan el nuevo flag
`supports_minimum_coopmat_caps` en vez del bit crudo, y el target extension
WMMA_FP8 de vkd3d-shader sigue exigiendo `shaderFloat8CooperativeMatrix`
(sin cambios). Sin la variable, el comportamiento es el original.

Comprobación sin tocar el checkout base (`upstream/vkd3d-proton` sigue en
`ef9a02e`, intacto):

```bash
git -C upstream/vkd3d-proton-coopmat stash -q
git -C upstream/vkd3d-proton-coopmat apply --check \
  "$PWD/patches/0005-vkd3d-keep-coopmat-extension.patch"
git -C upstream/vkd3d-proton-coopmat stash pop -q
```

Build x86_64-unicamente en `build/vkd3d-coopmat/` (cross file llvm-mingw propio,
meson del `.venv` local); DLLs listas en `build/vkd3d-coopmat/dist/`.
Ver `build/vkd3d-coopmat/BUILD.md`. **No instalado en ningún prefijo.**

Variante GE-Proton (decisión del usuario 2026-11-22: la compat tool se basa
en GE, no en Experimental): worktree `upstream/vkd3d-proton-ge` en la
revisión exacta que embarca GE-Proton11-12 (`8293130e`, post-`v3.1`,
`vkd3d-1.1-5687-g8293130eb` según el `version` del tarball), con los 3
parches vkd3d de GE aplicados (copias en
`build/vkd3d-coopmat-ge/ge-patches/`: present-waits, no-parent-image,
version-string) y encima el mismo `0005` **sin cambios: aplicó limpio
(`apply --check` OK antes y después de los parches de GE), así que no hay
`0005-...-ge.patch` separado**. Build en `build/vkd3d-coopmat-ge/` con el
mismo cross file y `.venv`; ver `build/vkd3d-coopmat-ge/BUILD.md`.

`0006-vkd3d-load-amdxc-env.patch` (P0 probe, 2026-11-22) agrega una rama
opt-in en `d3d12_device_init_vendor_hacks`: con `VKD3D_LOAD_AMDXC=1` hace
`LoadLibraryA("amdxc64.dll")` sin mirar el `vendorID`, para que el shim
local del prefijo descartable quede cargado antes de que
`amd_fidelityfx_framegeneration_dx12.dll` lo busque con
`GetModuleHandleA/W` (el hack original sólo lo carga para `0x1002`). Sólo
carga la DLL: todas las respuestas siguen viniendo del shim. Sin la
variable el comportamiento es idéntico.

sha256: `f628e19829ada97a6cb02a4980184de2a71440c34b0d642ec05c019db0b8f63f`.
Aplicado sobre `upstream/vkd3d-proton-ge` (después de GE 0001–0003 y
0005), `git apply --check` OK. Build en
`build/vkd3d-coopmat-ge-0006/` (mismo cross file y `.venv`, `-j6`);
DLLs en `dist/`, hashes en su `BUILD.md`. **No instalado en ningún
Proton/prefijo.** Runbook: `analysis/fg-401-static/p0-gate-probe.md`.
