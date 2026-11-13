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
