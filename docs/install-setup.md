# Instalación y setup: FSR4 XMX sobre Intel Linux con xess-xmx-linux

Guía honesta y fail-closed. Todo el stack funcional corre sobre el paquete
`xess-xmx-linux` (driver Mesa ANV parcheado + shim IGDEXT + helper ocloc).
Ese paquete es la pieza central; este repo aporta investigación, shims de
juego y documentación, no un driver propio.

No ejecutes nada como parte de leer esta guía. Cada comando aquí salió de
un archivo leído del repo o del paquete candidato. Si un paso no está
documentado en una fuente, se dice explícitamente.

## 1. Requisitos

- GPU Intel Xe2. Probada: Arc B580. Fuente: `docs/first-fsr-xmx-success.md`
  (B580, render correcto en Spider-Man) y README del paquete (Xe2 probada
  por un contribuidor en B580).
- Mesa del sistema compatible con el driver del paquete. El paquete trae sus
  propios drivers (ver §2) y `tools/session-check.sh` verifica que el driver
  del paquete cargue contra las librerías del sistema. Si falla, la sesión
  vuelve a los drivers stock.
- Proton Experimental. Fuente: `docs/spiderman-trace-runbook.md` (ruta
  `.../steamapps/common/Proton - Experimental/proton`, versión
  `experimental-11.0-20261105c` registrada el día de la traza; re-verificar
  con `cat` porque Steam puede actualizarlo).
- Steam nativo. `install.sh` del paquete solo cubre el Steam nativo
  (SteamOS, paquete de la distribución) y avisa que Flatpak Steam no ve
  `~/.config/environment.d` ni la carpeta del paquete.
- Herramienta de compresión/ocloc que ya trae el paquete. `install.sh` trae
  el bundle del compilador con `tools/get-igc.sh` (IGC + ocloc) si falta en
  `igc/`, y `tools/cm-compile.sh` es el helper que el driver invoca en
  tiempo de ejecución. La descompresión LZMS de los packs del mod se validó
  en este repo con wimlib local (`docs/cabinet-shim.md`), pero en runtime el
  que compila kernels es el helper del paquete.

## 2. Qué piezas hay

Paquete `xess-xmx-linux-20261113-cmk3` (candidato verificado en
`docs/rebuild-20261113.md` y `docs/first-fsr-xmx-success.md`):

- Driver Mesa ANV parcheado en `lib/` (`lib/mesa-*/libvulkan_intel.so`,
  forwarder `lib/libvulkan_intel.so`, ICD en `run/intel_icd.json`).
- Shim `igdext64.dll` en la raíz del paquete.
- Kernels CMK en `kernels/` y caché en `~/.cache/xess-xmx/kernels`.
- Helper `tools/cm-compile.sh` (compilador runtime invocado por el driver).
- Scripts: `install.sh`, `enable.sh`, `disable.sh`, `uninstall.sh`,
  `xmx-launch.sh`, `xmx-stock.sh`, `tools/switch-driver.sh`,
  `tools/session-check.sh`.
- Unidades systemd de usuario y entorno de sesión (ver §4).

Piezas del lado del juego (no vienen en el paquete, no redistribuir):

- Mod FSR4 XMX de nitec: `amd_fidelityfx_upscaler_dx12.dll` del mod 4.1.2.
  Hash fijado en `docs/xmx412-model-selection.md` y en el runbook.
- `fsr-original.dll`: DLL oficial AMD FidelityFX Upscaler DX12 de FSR
  4.1.2, renombrado, colocado junto al DLL del mod (o junto al EXE, o vía
  `FSR4_XMX_LITE_DLL`). Aporta los pesos INT8/Lite. No está en este repo;
  no se fija su SHA-256 aquí. Ver `docs/xmx412-model-selection.md` §4.
- `cabinet.dll` workaround: shim juego-local construido por
  `tools/build_cabinet_shim.py` (ver `docs/cabinet-shim.md`). Solo existe
  junto al juego, nunca en `system32` de prefijos ni en Proton/Wine.
- OptiScaler con `Dx12Upscaler = ffx` (ruta FSR/XMX). Fuente:
  `docs/first-runtime-trace-412.md` y runbook §2.

## 3. Instalación side-by-side (sin tocar el sistema)

Es el modo usado para la primera ejecución funcional. Fuente:
`docs/rebuild-20261113.md` y `docs/first-fsr-xmx-success.md`.

Estructura relevante del paquete (listado leído):

```text
xess-xmx-linux-20261113-cmk3/
  install.sh enable.sh disable.sh uninstall.sh
  xmx-launch.sh xmx-stock.sh igdext64.dll
  lib/ run/intel_icd.json kernels/ igc/ patches/
  tools/switch-driver.sh tools/session-check.sh tools/cm-compile.sh
  docs/ LICENSE THIRD_PARTY.md
```

Pasos:

1. Dejar el paquete activo del usuario sin tocar. El candidato vive en su
   propia carpeta (`/home/matias/xess-xmx/xess-xmx-linux-20261113-cmk3`).
2. Verificación de carga sin instalar, con `XMX_CHECK_LIB` apuntando al
   driver del paquete nuevo. Fuente: `docs/rebuild-20261113.md`
   (`session-check --dry-run` con `XMX_CHECK_LIB` enumera la B580 como
   `Mesa 26.3.0 (git-51c31a484c)`) y `tools/session-check.sh` del paquete
   (`XMX_CHECK_LIB` / `XMX_CHECK_ICD` como overrides solo para pruebas):

```bash
XMX_CHECK_LIB="$PWD/lib/mesa-26.3.0/libvulkan_intel.so" bash tools/session-check.sh --dry-run
```

Nota: la ruta exacta del driver depende de `lib/active` y de las versiones
presentes en `lib/mesa-*/`. El ejemplo usa `mesa-26.3.0` porque el
candidato lista `lib/active` con `26.3.0`. Si tu copia difiere, ajusta con
el listado real de `lib/`, no inventes la versión.

3. Verificación de hashes de partida (solo lectura). Fuente:
   `docs/spiderman-trace-runbook.md` §1:

```bash
cd /home/matias/Proyectos/fsr-xmx-proton-bridge
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
```

El hash esperado del mod está fijado en `docs/xmx412-model-selection.md`
y en el runbook. Si difiere: parar, no continuar.

4. Lanzar el juego solo por proceso con el ICD del candidato y el helper
   nuevo. Fuente: `run-candidate.sh` del run de traza. Variables que ese
   script fija (entorno reemplazado por proceso, nada system-wide):

```bash
export STEAM_COMPAT_DATA_PATH="$PWD/compatdata"
export VK_DRIVER_FILES="<paquete>/run/intel_icd.json"
export VK_LOADER_LAYERS_DISABLE='*'
export VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer
export ANV_CM_KERNEL_DIR="<run>/kernels-candidate"
export ANV_CM_HELPER="<paquete>/tools/cm-compile.sh"
export ANV_CM_DEBUG=1
export WINEDLLOVERRIDES="cabinet=n,b"
export VKD3D_DEBUG=trace
```

El comando Proton exacto y el prefijo descartable están en
`run-candidate.sh` y en el runbook §4. No se reproduce aquí la ruta del
juego porque depende de tu instalación; usa la de tu máquina.

## 4. Instalación system-wide (el camino real)

Este es el mecanismo de instalación real del paquete. Todo lo descrito aquí
salió de `install.sh`, `enable.sh`, `xmx-launch.sh`, `tools/session-check.sh`
y `tools/switch-driver.sh` del paquete candidato.

### Opción A: toda la sesión (`install.sh`)

```bash
./install.sh
```

Lo que hace (resumen fiel del script):

1. Trae el bundle del compilador (`tools/get-igc.sh`), las librerías XeSS
   (`tools/get-xess.sh`) y FidelityFX (`tools/get-ffx.sh`) si faltan.
2. Escribe `~/.config/environment.d/50-xess-xmx.conf`: el ANV parcheado como
   driver Vulkan Intel (`VK_DRIVER_FILES`), `VKD3D_DISABLE_EXTENSIONS`,
   `ANV_CM_KERNEL_DIR`, `ANV_CM_HELPER`, `force_vk_vendor=0`,
   `INTC_ALT_DRIVER_EXTENSIONS_PATH`. Aplica a Steam tras reboot o re-login.
3. Copia el shim `igdext64.dll` en cada Proton con igdext propio y en cada
   prefijo con carpeta `igd_faux`, guardando el original como `.stock`.
4. Instala la unidad `xess-xmx-shim.path` que reinstala el shim tras updates
   de Proton o prefijos nuevos.
5. Instala `xess-xmx-check.service`: antes de cada sesión gráfica corre
   `tools/session-check.sh`; si el driver parcheado no carga, la sesión
   vuelve a los drivers stock en vez de perder la GPU Intel.

Variables de entorno aceptadas por `install.sh`: `XMX_NO_ENV=1` (omite el
paso 2), `XMX_DRIVER=stock|patched|auto` (elige driver), `MESA=<versión>`
(por juego, en sus launch options). Fuente: cabecera de `install.sh` y
README del paquete.

### Opción B: un solo juego (`enable.sh`)

```bash
XMX_APPID=<steam app id> ./enable.sh
```

o, para otros launchers:

```bash
XMX_PREFIX=<carpeta del prefijo> ./enable.sh
```

Variables: `XMX_APPID` o `XMX_PREFIX` (una requerida), `XMX_CONF`
(por defecto `~/.config/xess-xmx.conf`), `XMX_GAME` (si se define,
enable/disable se niegan con el juego en ejecución). Fuente: cabecera de
`enable.sh`.

Lo que hace: copia el shim al prefijo (original como
`igdext64.dll.stock`), escribe el bloque marcado `XESS-XMX` en `XMX_CONF`
con `VK_DRIVER_FILES`, `VKD3D_DISABLE_EXTENSIONS`,
`ANV_CM_KERNEL_DIR`, `ANV_CM_HELPER`, `force_vk_vendor`,
`INTC_ALT_DRIVER_EXTENSIONS_PATH`, y corre el driver check.

Launch options de Steam para ese juego:

```text
/path/to/package/xmx-launch.sh %command%
```

`xmx-launch.sh` solo importa `XMX_CONF` y ejecuta el juego. Fuente:
`xmx-launch.sh` (6 líneas).

### `switch-driver.sh`

```bash
tools/switch-driver.sh
tools/switch-driver.sh 26.3
```

Sin argumento lista los drivers de `lib/mesa-*/` y marca el defecto (`*`
según `lib/active`). Con argumento cambia el defecto; los juegos en marcha
conservan su driver, los nuevos usan el nuevo, sin re-login. Por juego,
`MESA=<versión>` en launch options gana al defecto. Fuente:
`tools/switch-driver.sh`. Nota: el README del paquete documenta
`MESA=26.1` / `MESA=26.3` como ejemplos; usa los valores que liste tu
copia, no esos literales si no existen.

## 5. Rollback

Fuentes: `disable.sh`, `uninstall.sh`, `tools/switch-driver.sh`,
`install.sh` (guarda `.stock`), y el backup
`/home/matias/xess-xmx/backup-20261113/` (hashes, shims, units, env).

- Por juego (revierte `enable.sh`):

```bash
XMX_APPID=<id> ./disable.sh
```

Restaura `igdext64.dll.stock` sobre `igdext64.dll` (o elimina el shim si el
prefijo no tenía stock), elimina `ControlLib.dll` propio, quita el bloque
`XESS-XMX` de `XMX_CONF` y borra `drive_c/igdext_kernels`.

- Cambio de driver: `tools/switch-driver.sh <versión>` o reinstalar el
  paquete viejo. `docs/rebuild-20261113.md` documenta el rollback probado a
  nivel de diseño: `tools/switch-driver.sh 26.3.0-rc1` o reinstalar el
  paquete anterior; los 13 shims de prefijos están respaldados.
- System-wide completo: `./uninstall.sh`. Restaura cada `igdext64.dll`
  desde su `.stock`, elimina el hook de Proton, el entorno y el watcher, y
  pide reboot o re-login. Los kernels compilados quedan en
  `~/.cache/xess-xmx` (borrar esa carpeta los elimina).
- Backup previo a la prueba del candidato: `/home/matias/xess-xmx/backup-20261113/`
  con `hashes.txt`, `shims/`, `units/`, `env/50-xess-xmx.conf`. Si algo no
  cuadra tras instalar el candidato, ese backup es la referencia de
  comparación. No se documenta aquí un comando de restauración automática
  desde el backup porque ninguno de los scripts leídos lo implementa; la
  restauración es `disable.sh` / `uninstall.sh` / reinstalar el paquete
  viejo.

## 6. Prueba en juego

Fuentes: `docs/xmx412-model-selection.md` §5, `docs/cabinet-shim.md` §6,
`run-full-test.sh`, `docs/first-fsr-xmx-success.md`.

1. Con el juego cerrado, copiar junto al ejecutable (la ruta exacta depende
   de tu instalación; el runbook usa el directorio de Spider-Man):
   el `amd_fidelityfx_upscaler_dx12.dll` del mod, el `fsr-original.dll`
   oficial 4.1.2, y el `cabinet.dll` construido por
   `tools/build_cabinet_shim.py`. No copiar `cabinet.dll` a ningún
   `system32` de prefijos.
1b. Copiar también `<paquete>/igdext64.dll` junto al mod. El prefijo de
   Spider-Man ya lo tenía en el DriverStore, pero un prefijo nuevo no, y sin
   el shim el mod aborta con `Intel extension igdext64.dll with required DX12
   exports was not found beside DLL, system search, or DriverStore` y muestra
   magenta. Sin shim tampoco puede consultar la GPU y elige kernels
   `DG2 SIMD8` en vez de `Xe2 SIMD16`.
2. Lanzar con override nativo de Cabinet más el entorno del run:

```bash
export WINEDLLOVERRIDES="cabinet=n,b"
```

3. Variables por proceso para elegir modelo (Steam: `VAR=1 %command%`).
   Fuente: `docs/xmx412-model-selection.md` §5.2 y `run-full-test.sh`:

```text
FSR4_XMX_INT8=1            # 4.1.2X (INT8), PROVIDER_INDEX=8
FSR4_XMX_LITE=1            # 4.1.2X Lite, PROVIDER_INDEX=12
(nada)                     # 4.0.2X stock según el juego
```

No definir ambas a la vez; INT8 gana si hay pesos. No definir
`FSR4_XMX_DLSS*` durante la prueba FSR4 (tienen prioridad).
Para forzar también la etiqueta visible:

```text
FSR4_XMX_PROVIDER_INDEX=8    # etiqueta 4.1.2X
FSR4_XMX_PROVIDER_INDEX=12   # etiqueta 4.1.2X Lite
```

Sin esto, el overlay puede seguir mostrando `4.0.2` aunque el log confirme
INT8/Lite. El log manda, no el overlay.

4. Captura de logs con `run-full-test.sh` (en el run de traza):

```bash
./run-full-test.sh int8 <tag> --proton-log
./run-full-test.sh lite <tag> --proton-log
./run-full-test.sh stock <tag>
```

Flags leídos del script: `--proton-log` (captura además el log propio del
mod con `INT8 model:` / `Lite model:`), `--fresh-kernels`,
`--no-mango`. El script fija por proceso `VK_DRIVER_FILES` al ICD del
candidato, `ANV_CM_HELPER`, `ANV_CM_KERNEL_DIR`, `VKD3D_DISABLE_EXTENSIONS`,
`ANV_CM_DEBUG=1`, `WINEDLLOVERRIDES`, `FSR4_XMX_LITE_DLL` (ruta Windows
`Z:...` hacia el `fsr-original.dll` del run), `FSR_ENV` y
`FSR4_XMX_PROVIDER_INDEX`, y al cerrar el juego genera por corrida
`vkd3d.log`, `fingerprint.txt`, `summary.txt` y, con `--proton-log`,
`steam-proton.log` y `mod-model.txt`.

5. Cómo leer el resultado:

- `summary.txt`: modelo pedido, `injected`, `sampler-heap-ok`, conteos de
  fingerprint. La línea clave aguas abajo es
  `sampler descriptor table after the surfaces (sampler heap found)`.
- `fingerprint.txt`: compara con otra corrida vía
  `tools/xmx_kernel_set.py diff`. Fuente: pie de `run-full-test.sh`.
- `mod-model.txt` (solo con `--proton-log`): conteos de `INT8 model:`,
  `Lite model:`, `without verified`, `PROVIDER_INDEX`. Las líneas
  autoritativas del modelo están en `docs/xmx412-model-selection.md` §5.3:

```text
[FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, ...
[FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, ...
```

Si aparece `Lite/INT8 model requested without verified fsr-original.dll
weights.`, faltan los pesos o el archivo no es el oficial 4.1.2
(checklist en §5.5 del doc de selección de modelo).

## 7. Límites

- Probado solo en Marvel's Spider-Man Remastered, una sola sesión
  funcional documentada (`docs/first-fsr-xmx-success.md`). No hay evidencia
  de otros juegos o prefijos.
- Verificado a nivel kernel (inyección, sampler heap, 11 recursos FSR4,
  0 device lost), no a nivel píxel. Sin oracle independiente ni readback
  determinista del PRE. Un S_OK, el overlay o la creación de shaders no
  acreditan el modelo.
- No redistribuir binarios de terceros: el mod de nitec, el DLL oficial
  AMD 4.1.2, los Proton de Valve, el juego. Rutas de terceros:
  `artifacts/original/` (ignorado por git), `upstream/` (checkouts
  ignorados), `~/.cache/xess-xmx/kernels`.
- Lo no documentado se declara: no hay en las fuentes leídas un comando de
  restauración automática desde `backup-20261113/` (solo referencia), ni un
  hash fijado del `fsr-original.dll` oficial 4.1.2 en este repo, ni una
  receta verificada para juegos distintos de Spider-Man.
