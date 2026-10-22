# Parches experimentales — no instalados

`0001-anv-cmk3-explicit-mapping.patch` modifica **los archivos de parche Mesa** de
xess-xmx-linux, no directamente un driver instalado. Es un parche de segundo nivel
para upstream `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.

Generación y comprobación sin modificar upstream:

```bash
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux \
  > analysis/anv-mapping-reproduced.patch
cmp patches/0001-anv-cmk3-explicit-mapping.patch analysis/anv-mapping-reproduced.patch
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
```

`.gitattributes` excluye estos diffs anidados del chequeo de whitespace: sus líneas
de contexto contienen espacios significativos. Se validan mediante regeneración,
comparación exacta y `git apply --check`, no recortando esos espacios.

Añade un lector CMK3 local, con base de tablas explícita y comprobación del tamaño
push y cobertura de cada DWORD. Mantiene la ruta CMK2 existente. El formato CMK3
**no es un formato publicado por upstream** y requiere este lector; no usar sus
artefactos con un driver original.

Estado: `git apply --check`, sintaxis de ambos parches internos y validación C
extraída con layouts sintéticos comprobadas. **No compilado dentro de Mesa, no
probado en GPU, no integrado al helper ni a su cache identity.**

Los payloads de argumentos, dimensiones locales, samplers y otros kernels siguen
pendientes. Ver `docs/offline-pre-compilation.md`. No aplicar a la sesión del
usuario ni instalar servicios/drivers como parte de las pruebas de CPU.
