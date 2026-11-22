# Instalador `fsr-xmx` (v1)

Script de bash + dos ayudantes de Python (solo librería estándar). Sin `sudo`:
todo vive bajo el home. Diseño y decisiones: `docs/installer-design.md`.

## Archivos

- `fsr-xmx`: el ejecutable (`installer/fsr-xmx`).
- `lib/common.sh`: funciones compartidas (perfiles, respaldos, hashes).
- `lib/ini_edit.py`: edita claves de `OptiScaler.ini` por sección, sin tocar
  el resto de los bytes ni los CRLF.
- `lib/vdf.py`: reescribe `compatibilitytool.vdf` de la herramienta de Steam.
- `profiles/cyberpunk2077.conf`: perfil de referencia (appid 1091500,
  `bin/x64`, hashes fijados de mod/fsr-original/OptiScaler/ANR).

## Qué espera el paquete precompilado (`install --from <carpeta>`)

```text
MANIFEST                                  VERSION=...
SHA256SUMS                                <hash>  <ruta relativa>
icd/intel_icd.json
lib/libvulkan_intel.so
igdext64.dll
cabinet.dll
vkd3d-proton/x86_64-windows/d3d12.dll
vkd3d-proton/x86_64-windows/d3d12core.dll
tools/cm-compile.sh
```

`install` verifica **todos** los archivos de `SHA256SUMS` antes de copiar
nada, copia a `~/.local/share/fsr-xmx/versions/<VERSION>/` y recién ahí
cambia el enlace `current` de forma atómica. Si algo no coincide, no deja
nada a medias.

## Árbol que usa

```text
~/.local/share/fsr-xmx/
  current -> versions/<VERSION>/
  versions/<VERSION>/
  profiles/<juego>/state.conf          lo escribe `enable`
  .fsr-xmx-root                        marca de "esto lo instaló fsr-xmx"
~/.cache/fsr-xmx/<appid>/kernels       ANV_CM_KERNEL_DIR
~/.cache/fsr-xmx/<appid>/logs          PROTON_LOG_DIR
<juego>/.fsr-xmx-backup/<fecha>/       copia de lo que se pisó + manifest.tsv
```

## Pruebas

`python3 -I -m unittest discover -s tests -p 'test_installer.py' -v`

Todo corre sobre carpetas temporales con `HOME`/`XDG_*` falsos; nunca toca
Steam, prefijos ni juegos reales.
