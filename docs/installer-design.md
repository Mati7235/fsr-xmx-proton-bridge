# Diseño del instalador `fsr-xmx`: FSR 4 XMX plug-and-play en Intel Arc

Documento de diseño, no código. Estado actual: todo se hace a mano con
lanzadores por juego (`analysis/antilag2-cp77/run.sh`, `hosts/matias-pc`
en el repo de config) y con el paquete `xess-xmx-linux` activado por
proceso. El objetivo es que cualquier persona con una Intel Arc / Xe2 en
Arch (y, si sale gratis, en cualquier Linux) logre lo mismo con un
script que descarga binarios precompilados verificados, sin leer el repo
y sin un agente de IA. Sin `sudo` en ningún paso: todo vive bajo el home
del usuario.

Decisiones ya tomadas por el usuario y que este diseño respeta:

- Los binarios que compilamos (Mesa ANV parcheado, nuestro vkd3d-proton)
  se distribuyen PRECOMPILADOS, compilados en CI sobre una base glibc
  vieja para que corran en Arch/Ubuntu/Fedora/etc. El script los descarga
  y verifica con `SHA256SUMS`. Nada se compila en la máquina del usuario.
- Funciones v1: escalado FSR 4 en XMX (modelos INT8 y Lite), XeFG (frame
  generation de Intel vía el shim `igdext64`) y ANR FG (Apex Neural
  Rendering; necesita nuestro vkd3d-proton con
  `VKD3D_KEEP_COOPMAT_EXTENSION=1`). Anti-Lag 2 queda fuera: el juego no
  llama a la función en Cyberpunk y el `amdxc64.dll` de Proton es un
  módulo propio de Wine, no la librería real (ver doc de `cp2077-xmx` en
  el repo de config).

## 1. Inventario del setup que funciona hoy (2026-11-22)

Todo lo de abajo se leyó de archivos reales, no de memoria.

- Paquete activo: `~/xess-xmx/xess-xmx-linux-20261120` (262 MB; `lib`
  31 MB, `igc` 228 MB, `kernels` vacío porque se compilan en uso).
  - Upstream: `HHH…/xess-xmx-linux` tag `20261120`, commit `f06dc39`.
    Checkout local en `upstream/xess-xmx-linux`, misma revisión.
  - Mesa 26.3.1, tarball oficial con sha256 fijado en `MANIFEST.txt`.
    Parches upstream `patches/mesa-26.3/0001,0002,0003,0005,0006,0007` más
    el nuestro `0004-anv-anti-lag.patch` (en este repo:
    `patches/0004-anv-anti-lag.patch`).
  - `run/intel_icd.json` apunta a
    `<paquete>/lib/libvulkan_intel.so` (forwarder compilado de
    `icd/xmx-icd.c`; el driver real está en `lib/mesa-26.3.1/`,
    sha `24e931c6…`). ICD declara API 1.4.348.
  - `igdext64.dll` del paquete: 862.208 bytes, sha256 `678a1a15…049a3`.
  - Helper de compilación runtime: `tools/cm-compile.sh` (solo shell
    POSIX, corre ocloc del bundle `igc/`). Scripts: `install.sh`,
    `enable.sh`, `disable.sh`, `uninstall.sh`, `xmx-launch.sh`,
    `xmx-stock.sh`, `tools/switch-driver.sh`, `tools/session-check.sh`,
    `tools/proton-hook.py`, `tools/steam-libraries.sh`, `tools/fsr-fg.sh`.
  - Nuestro repo aporta a ese paquete los parches `0001` (inyección CMK3),
    `0002`/`0003` (contexto del shim), `0004` (Anti-Lag 2) y `0005`
    (vkd3d keep-coopmat, ver abajo). `0004` ya está integrado en el
    paquete 20261120 (el `MANIFEST.txt` lo dice).
- Lanzador actual: `analysis/antilag2-cp77/run.sh` (copia viva en el repo
  de config como `hosts/matias-pc/xess-xmx/cp2077/run.sh`). Variables que
  fija por proceso y por qué:
  - `STEAM_COMPAT_{CLIENT_INSTALL_PATH,DATA_PATH,APP_ID}` + `SteamAppId`
    / `SteamGameId`: prefijo descartable `compatdata`, nunca el de
    producción (appid 1091500).
  - `VK_DRIVER_FILES=<paquete>/run/intel_icd.json`: usa nuestro ANV solo
    en este proceso, sin tocar la sesión.
  - `VK_LOADER_LAYERS_DISABLE='*'`: ningún layer (MangoHUD, etc.) se
    mete en el medio del camino CM.
  - `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer,VK_EXT_descriptor_heap,VK_KHR_present_wait2`:
    el valor de referencia sale de `tools/steam-libraries.sh`
    (`XMX_VKD3D_OFF`); sin esto el driver parcheado falla.
  - `ANV_CM_HELPER=<paquete>/tools/cm-compile.sh` + `ANV_CM_KERNEL_DIR`
    (carpeta de kernels por corrida) + `ANV_CM_DEBUG=1`: compilación
    runtime de kernels CM y log de inyección.
  - `WINEDLLOVERRIDES="dxgi,cabinet=n,b"`: OptiScaler (`dxgi.dll`) y
    nuestro `cabinet.dll` como nativos.
  - `PROTON_LOG=1`, `PROTON_LOG_DIR`, `VKD3D_DEBUG=warn` (`trace` solo
    con `--trace`): diagnóstico.
  - Opcionales: `IGDEXT_XELL_CAP=off` (`--no-xell`, apaga XeLL y con eso
    XeFG), `XESS_FG=N` (`--xess-fg`, FG nativo del juego 2–8; hoy no se
    usa porque pelea con XeFG), `force_vk_vendor=4098` (`--spoof-amd`,
    solo para probar Anti-Lag; rompe XeSS/XMX), `WINEDEBUG=+amdxc`,
    `PROTON_ENABLE_WAYLAND=1` (`--wayland`, así se usa siempre acá: fue
    lo que destrabó el cursor), gamescope opcional.
  - El doctor `xmx-doctor.sh <perfil> [--fix]` (repo de config,
    `games/cp2077.conf`) revisa sin tocar: igualdad sha256 de los tres
    `igdext64.dll` (paquete/juego/prefijo), secciones `[Spoofing]` y
    `[FrameGen]` del ini, `compile_failed.txt`, el valor de
    `VKD3D_DISABLE_EXTENSIONS`, juego abierto, entorno de sesión
    apuntando al paquete viejo. `--fix` corrige con backup `.bak-<fecha>`
    y se niega a tocar el ini con el juego abierto.
- Carpeta del juego (solo lectura):
  `/home/matias/Juegos/steamapps/common/Cyberpunk 2077/bin/x64`.
  Archivos nuestros o de mods (el resto es del juego):
  - `amd_fidelityfx_upscaler_dx12.dll` (mod FSR4 XMX 4.1.2):
    45.558.272 bytes, sha256 `fadbcb50…b37f44732`.
  - `fsr-original.dll` (AMD oficial FSR 4.1.2, aporta los pesos INT8/Lite):
    57.664.272 bytes, sha256 `aad4fccc…0148cc65`.
  - `igdext64.dll`: 862.208 bytes, sha256 `678a1a15…049a3`, IDÉNTICO al
    del paquete (el doctor los igualó).
  - `cabinet.dll`: 69.632 bytes, sha256 `951a13e3…fa65f9f74`,
    construido por `tools/build_cabinet_shim.py` (shim juego-local para
    los packs LZMS del mod; nunca en `system32`).
  - `dxgi.dll` (OptiScaler v10 pre-release): 28.150.784 bytes.
  - `OptiScaler/` con `custom/Apex Neural Rendering FG/` y
    `D3D12_OptiScaler/`; `OptiScaler.ini` (1915 líneas, CRLF) con lo que
    importa: `Dx12Upscaler = ffx`, `FGInput=nvngxfg`, `FGOutput = XeFG`,
    `FGNvngxReplacement=Apex Neural Rendering FG`, `Fsr4GpuSupport/Preset/Model = auto`,
    `[Spoofing]` con `SpoofedVendorId = 0x8086`,
    `SpoofedDeviceId = 0xE20B`, `Dxgi = false`.
- `artifacts/original/` (ignorado por git, solo local): `amd_fidelityfx_upscaler_dx12_xmx.7z`
  (4.0.2x), `amd_fidelityfx_upscaler_dx12_xmx412.7z` (4.1.2),
  `nvngx_dlssd_xmx.7z`, `OptiScaler_v10.0.0-pre_20261022.7z`,
  `FidelityFX-SDK-2.4.0.zip`, `anr-FG-V.B20/` (full 11,7 MB + addon
  4,1 MB, ambos verificados contra `SHA256SUMS-upstream.txt`),
  `cp2077-bin-x64/` (copias con `SOURCE.txt` + `SHA256SUMS` de los
  `amd_fidelityfx_{framegeneration,loader}_dx12.dll` del juego).
  Ningún `SOURCE.txt` global; la procedencia vive en esos archivos y en
  `docs/compatibility.md`. Licencias: ver §2, nada se redistribuye.
- GPU probada: Intel Battlemage G21 (Arc B580, PCI `8086:e20b`), driver
  `xe`/`i915` del kernel. Proton: Experimental del 2026-11-15
  (`experimental-11.0-20261115`-era; el build de vkd3d se fijó contra la
  revisión `2576c0b4` = `experimental-11.0-20261112`). En
  `compatibilitytools.d` hay además GE-Proton y proton-cachyos.

## 2. Lista de componentes: nuestro vs de terceros

### Nuestro (compilable desde este repo + upstreams, redistribuible con fuente)

| Pieza | Fuente | Licencia | Cómo se distribuye |
|---|---|---|---|
| Mesa ANV parcheado (`libvulkan_intel.so` + forwarder + `run/intel_icd.json`) | Mesa oficial + `patches/mesa-26.3/*` de xess-xmx-linux + nuestros `0001`–`0004` | MIT | precompilado en CI + tarball de fuentes/parches con oferta de fuente |
| Shim `igdext64.dll` (+ `ControlLib.dll`) | `shim/` de xess-xmx-linux + nuestros `0002`/`0003` | MIT | precompilado en CI |
| Nuestros `d3d12.dll` + `d3d12core.dll` (vkd3d-proton + `0005`) | vkd3d-proton base `2576c0b4` + `patches/0005-vkd3d-keep-coopmat-extension.patch` | LGPL-2.1 | precompilados en CI; ver §3 cómo llegan al juego sin redistribuir Proton |
| `cabinet.dll` juego-local | `tools/build_cabinet_shim.py` de este repo | MIT (nuestro) | se compila en CI con llvm-mingw o lo construye el script; es código nuestro, sin problema de licencia |
| `fsr-xmx` (script instalador + `fsr-xmx run` wrapper) | nuevo en este repo | MIT | código fuente en el repo, se baja con git o como tarball |

### Terceros (JAMÁS redistribuir binarios; el script los descarga o los pide)

| Pieza | Origen oficial | Licencia | Estrategia |
|---|---|---|---|
| OptiScaler | releases oficiales en `github.com/OptiScalers/OptiScaler` (GPL). Versión en uso: `v10.0.0-pre_20261022` | GPL | el script descarga el release oficial por URL fija + sha256 fijado; también vale que el usuario ponga su archivo y el script lo verifique |
| ANR FG | releases oficiales en `github.com/apex-compute/ANR`, tag `FG-V.B20`: `anr-fg-V.B20-full.zip` + `anr-fg-V.B20-addon.zip`, verificados contra su `SHA256SUMS.txt` de upstream | la que diga su repo (revisar en v1; el zip trae su licencia) | descarga directa del release oficial + verificación contra el `SHA256SUMS` de upstream (tenemos copia local de referencia). El zip `-source` (GPL, 133 MB) no hace falta |
| FSR 4.1.2 oficial (`fsr-original.dll`, pesos INT8/Lite) | SDK o DLL oficial de AMD (hoy sale de una instalación/juego con FSR 4.1.2; el hash en uso es `aad4fccc…`) | licencia binaria de AMD, no redistribuible | EL USUARIO LA APORTA. El script la acepta por path o la busca en lugares conocidos, verifica que sea la 4.1.2 oficial (sha256 + tamaño 57.664.272) y la copia junto al mod. Nunca la descargamos nosotros |
| Mod FSR4 XMX (`amd_fidelityfx_upscaler_dx12.dll` 4.1.2 de nitec) | mod de nitec (distribución por NexusMods; sin URL pública directa estable). Hash en uso `fadbcb50…b37f44732`, 45.558.272 bytes | la del autor, no redistribuible | EL USUARIO LO APORTA (lo baja de NexusMods con su cuenta). El script verifica hash/tamaño y lo coloca. Plan B si el autor publica URL directa: descarga + verificación, con su permiso |
| Intel XeSS FG libs (`libxess_fg.dll`, `libxell.dll`, `libxess.dll`) | `github.com/intel/xess` vía `tools/get-xess.sh` del paquete | Intel Simplified Software License, no redistribuible | el instalador reutiliza `get-xess.sh` en la máquina del usuario (descarga Intel → usuario, nosotros solo el script) |
| AMD FSR DLLs firmadas (loader/upscaler/FG del SDK 2.4.0) | `GPUOpen-LibrariesAndSDKs/FidelityFX-SDK` vía `tools/get-ffx.sh` | licencia binaria AMD | igual: `get-ffx.sh` en la máquina del usuario |
| IGC/ocloc (`igc/`, 228 MB) | Intel (lo trae `tools/get-igc.sh`) | MIT pero pesado y por plataforma | `get-igc.sh` en la máquina del usuario; NO va en nuestro release (el paquete 20261120 lo copió del anterior, ni siquiera lo reconstruyó) |
| Proton / Steam Runtime | Valve | sus licencias | nunca se tocan ni se redistribuyen; ver §3 |

## 3. Arquitectura

### Raíz de instalación

Todo bajo el home, sin sudo, sin system-wide:

```text
~/.local/share/fsr-xmx/
  release/            # lo descargado y verificado (Mesa precompilado, vkd3d DLLs, cabinet, shims)
  profiles/<juego>/   # un perfil por juego: env, hashes esperados, ini deseado, backups
  backups/            # copias .bak-<fecha> de todo lo que se pisa en carpetas de juegos
  proton/             # la “compat tool” generada (ver abajo)
  kernels -> ~/.cache/fsr-xmx/kernels   # caché de kernels CM (respeta XDG)
```

`~/.local/bin/fsr-xmx` (o `~/.local/share/fsr-xmx/bin/fsr-xmx` con symlink):
el único ejecutable que el usuario toca.

Nada en `~/.config/environment.d`, nada en systemd de usuario, nada en
`/etc`, nada en el Steam instalado. La selección del driver es POR PROCESO
(`VK_DRIVER_FILES`), nunca de sesión. Esto es una decisión consciente
contra `install.sh` de upstream (que escribe `50-xess-xmx.conf` y cambia
toda la sesión): lo nuestro no puede dejar al usuario sin GPU si el
driver falla, porque si el ICD no carga el juego simplemente no arranca
y el resto del escritorio sigue intacto. El `session-check.sh` de upstream
existe justamente porque el modo system-wide puede romper la sesión;
nosotros evitamos esa clase de fallo por construcción.

### Cómo se lanza cada juego: wrapper, no launch options a mano

El usuario pega UNA línea en las opciones de lanzamiento de Steam:

```text
~/.local/bin/fsr-xmx run --profile cp2077 %command%
```

`fsr-xmx run` fija las mismas variables que hoy fija `run.sh`
(`VK_DRIVER_FILES` al ICD de nuestro release, `VK_LOADER_LAYERS_DISABLE`,
`VKD3D_DISABLE_EXTENSIONS`, `ANV_CM_*`, `WINEDLLOVERRIDES`,
`VKD3D_KEEP_COOPMAT_EXTENSION=1` cuando el perfil pide ANR, más las
`FSR4_XMX_*` del modelo) y hace `exec` del comando. Sin archivos de
entorno intermedios que se pudran (`XMX_CONF` de upstream es un archivo
que otro proceso puede editar a destiempo; variables por proceso no).

Para correr fuera de Steam (o con Proton suelto) el wrapper acepta
`fsr-xmx run --proton <ruta> --exe <ruta> -- ...`, que es lo que `run.sh`
hace hoy a mano.

### Nuestro vkd3d-proton sin redistribuir el Proton de Valve

Hecho clave (leído del script `proton` en `BUILD.md`): cada lanzamiento
re-copia **incondicionalmente** `d3d12/d3d12core.dll` desde
`<Proton>/files/.../vkd3d-proton/` al `system32` del prefijo. Por eso
reemplazar DLLs dentro del prefijo NO sirve: se pierde en el próximo
arranque. Y copiar DLLs sueltos en la carpeta del juego es frágil
(depende del orden de búsqueda de Wine, no verificado).

Opciones evaluadas:

1. **Copia local del Proton del usuario como Steam compatibility tool
   (ELEGIDA).** El instalador copia (reflink en btrfs, casi gratis)
   `~/.local/share/Steam/steamapps/common/Proton - Experimental` (o el
   GE-Proton que elija el usuario) a
   `~/.local/share/Steam/compatibilitytools.d/FSR-XMX-Proton/` y
   reemplaza ahí dentro solo los dos archivos
   `files/lib/wine/vkd3d-proton/x86_64-windows/{d3d12,d3d12core}.dll`
   por los nuestros (con backup `.stock`). Agrega el `compatibilitytool.vdf`
   mínimo para que Steam la liste como “FSR XMX Proton”. El usuario elige
   esa tool en Propiedades del juego → Compatibilidad. Nada del Proton
   original se toca; borrar nuestra carpeta revierte todo. Costo: ~1 GB
   lógicos por copia, pero en btrfs con reflink son solo los bloques
   cambiados (los dos DLL, ~5 MB). En filesystems sin reflink es una copia
   completa: el instalador avisa del tamaño antes de hacerlo.
2. Copia por juego fuera de Steam (`$release/proton-vkd3d-test` como en
   `BUILD.md`): sirve para probar, pero Steam no la usa para juegos de la
   biblioteca; solo vale como modo `--proton` manual. Se mantiene como
   fallback, no como camino principal.
3. `WINEDLLPATH` con nuestros DLL: orden de búsqueda no confirmado frente
   a `system32`; descartada hasta tener prueba.
4. Parchear el Proton instalado: modifica software de Valve, se pierde en
   cada update de Proton, imposible de auditar para el usuario. Descartada.

Riesgo heredado conocido: forzar la extensión rompió `vkCreateDevice` en
un driver NVIDIA (vkd3d-proton#3076); por eso `0005` es opt-in por env var
y el wrapper solo la exporta en perfiles ANR.

### Cómo llegan las DLLs al prefijo y al juego

- vkd3d: el Proton copiado las lleva puestas; el prefijo las recibe solo
  en cada arranque, como siempre. Nada que hacer por juego.
- `igdext64.dll`: el wrapper verifica sha256 en tres lugares (paquete /
  carpeta del juego / driver store del prefijo) como hace `xmx-doctor.sh`
  hoy, y `enable` lo iguala con backup. No se instala ningún watcher
  systemd (upstream sí lo pone; nosotros preferimos verificar en cada
  `run` y en `doctor`: menos piezas móviles, mismo efecto).
- Archivos en la carpeta del juego (mod XMX, `fsr-original.dll`,
  `cabinet.dll`, OptiScaler, ANR): los pone `fsr-xmx enable` con backup
  y verificación de hash; `disable` los quita y restaura.

## 4. Spec del CLI

```text
fsr-xmx install [--proton experimental|ge|cachy] [--with-anr] [--with-xess-fg]
fsr-xmx doctor [--profile <juego>]
fsr-xmx enable <dir-juego> [--fsr4 int8|lite] [--fg xefg|anr|off]
fsr-xmx disable <dir-juego>
fsr-xmx uninstall [--keep-kernels]
fsr-xmx update
fsr-xmx run --profile <juego> [--] <comando...>
```

Qué hace cada uno (todos idempotentes: correr dos veces deja lo mismo; todo
lo que pisa un archivo del usuario deja `.bak-<fecha>`):

- `install`: crea el árbol de §3; descarga el release precompilado
  (Mesa+shims+cabinet+vkd3d DLLs) y verifica `SHA256SUMS`; corre
  `get-igc.sh`/`get-xess.sh`/`get-ffx.sh` (descargas Intel/AMD directas al
  usuario); genera la compatibility tool de §3 desde el Proton elegido;
  instala el symlink en `~/.local/bin` (crea el dir si falta; si no está
  en `PATH`, lo dice). Escribe `release/MANIFEST` con versiones y hashes.
  No toca Steam, prefijos ni juegos.
- `doctor`: solo lectura (sale 1 si hay problemas). Revisa: GPU Intel con
  PCI `8086:*` y driver `xe`/`i915` cargado; Vulkan loader presente
  (`vulkaninfo` o `libvulkan.so.1`); Steam nativo vs Flatpak (Flatpak: no
  ve `~/.local/share`, se avisa y se apunta a paths del sandbox);
  release descargado y hashes OK; compatibility tool presente y sus dos
  DLLs con el hash nuestro; por perfil: `igdext64` iguales en los tres
  lugares, `OptiScaler.ini` con las secciones esperadas, mod y
  `fsr-original.dll` con hash correcto, `compile_failed.txt` (avisa,
  no borra). Es el `xmx-doctor.sh` actual promovido a subcomando, con los
  valores de referencia leídos del release (no hardcodeados).
- `enable <dir-juego>`: detecta el juego (Cyberpunk primero; Steam appid
  por cercanía si el dir está bajo `steamapps/common`, si no pide
  `--appid` para el prefijo de producción); verifica hashes de lo que ya
  haya; copia mod/shims/OptiScaler/ANR con backup; escribe o ajusta
  `OptiScaler.ini` por sección (nunca por número de línea; respeta CRLF;
  se niega con el juego abierto, detectado por `pgrep -af <exe>`);
  `--fsr4 int8|lite` elige las env `FSR4_XMX_INT8=1` / `FSR4_XMX_LITE=1`
  del perfil (`stock` = ninguna, solo si el juego trae su propio 4.0.2);
  `--fg xefg|anr|off` elige `FGOutput` + `FGNvngxReplacement` y si el
  perfil exporta `VKD3D_KEEP_COOPMAT_EXTENSION=1`; imprime la línea de
  Steam a pegar y el comando de verificación (`doctor --profile`).
- `disable <dir-juego>`: quita lo que puso `enable` (mod, pesos, cabinet,
  OptiScaler, ANR, `igdext64` juego-local si no tenía stock) y restaura
  cada `.bak`; deja el perfil archivado como `<juego>.disabled`.
- `uninstall`: borra la compatibility tool, el árbol `~/.local/share/fsr-xmx`
  (pregunta; `--keep-kernels` conserva `~/.cache/fsr-xmx`), el symlink y
  los perfiles; ofrece `disable` primero para cada juego habilitado. Nunca
  toca el Proton original, la biblioteca de Steam ni archivos del sistema.
- `update`: baja el `SHA256SUMS` + manifiesto del release nuevo, compara
  versión, descarga, verifica y cambia el symlink `release/current`;
  conserva el release anterior hasta que `doctor` dé verde con el nuevo
  (rollback = volver el symlink).
- Perfiles (`profiles/<juego>.conf`, formato `KEY=valor` como hoy):
  `GAME_NAME`, `GAME_EXE`, `APPID`, `FSR4=int8|lite|stock`,
  `FG=xefg|anr|off`, más lo derivado (env del wrapper, hashes esperados,
  ajustes de ini). Cyberpunk 2077 es el perfil de referencia; el formato
  admite otros juegos cambiando esas líneas, igual que hoy con
  `games/cp2077.conf`.

Chequeos de hardware/entorno (`doctor` y pre-`install`): lspci `8086`
serie Arc/Battlemage/Xe2 (lista de PCI IDs en el release, ampliable);
`/sys/class/drm/renderD*/device/vendor` con driver `xe` (acepta `i915`
viejo con aviso); Vulkan loader (`command -v vulkaninfo`,
`ldconfig -p | grep libvulkan`); distingue Steam nativo
(`~/.local/share/Steam`) de Flatpak (`~/.var/app/com.valvesoftware.Steam`);
disco libre para la compatibility tool (avisa si no hay reflink/COW).

## 5. CI y releases

- Jobs de GitHub Actions (o forja equivalente; publicar necesita el visto
  bueno explícito del usuario, ver abajo):
  1. `mesa`: checkout Mesa oficial (versión fijada, tarball con sha256)
     + parches `patches/mesa-26.3/*` de xess-xmx-linux (pin al tag usado)
     + nuestros `0001`/`0004`; build con las `meson OPTS` de
     `rebuild-driver.sh`; artefactos: `libvulkan_intel.so`,
     forwarder `xmx-icd.c`, `intel_icd.json`, `igdext64.dll`,
     `ControlLib.dll`, `layer/` si aplica.
  2. `vkd3d`: checkout vkd3d-proton al commit fijado + submódulos +
     nuestro `0005`; cross llvm-mingw; artefactos: `d3d12.dll`,
     `d3d12core.dll` (x86_64; i386 solo si el perfil lo necesita).
  3. `shims`: `cabinet.dll` (nuestro) + empaquetado.
  4. `release`: junta todo + `SHA256SUMS` firmado + `MANIFEST` (commits,
     tags, hashes de tarballs, comandos de build) + tarball de fuentes
     (parches + scripts + submódulos pineados).
- Base de build: imagen con glibc VIEJA para que el binario corra en
  todos lados (Steam Runtime `sniper` SDK o Ubuntu 22.04, a decidir en el
  primer build; criterio: el `libvulkan_intel.so` resultante debe cargar
  en Arch actual y en Ubuntu 22.04). Verificar con `ldd` y con
  `session-check.sh --dry-run` contra el driver construido.
- Versionado: `fsr-xmx-<fecha>-<mesa>-<vkd3d>` (ej.
  `20261120-mesa26.3.1-vkd3d2576c0b4`); `SHA256SUMS` por release;
  `latest` como symlink/redirect, nunca como archivo sin hash.
- Fuentes y licencias: el release incluye oferta de fuente completa
  (LGPL de vkd3d-proton lo exige; MIT de Mesa/shims lo agradece):
  tarball con los checkouts exactos + parches + scripts de build para
  reproducir los binarios. `THIRD_PARTY.md` actualizado por release.
- Publicar (GitHub Releases o similar) SOLO con aprobación explícita del
  usuario en ese momento; este diseño no autoriza nada.

## 6. Lenguaje y dependencias

Bash POSIX (`#!/bin/sh`, estilo `cm-compile.sh`: corre hasta bajo `dash`)
para `install`/`run`/`enable`/`doctor`: cero dependencias de lenguaje,
funciona en cualquier base Arch. Si alguna parte necesita estructuras de
datos (parseo de ini por sección, JSON del manifiesto), Python 3 stdlib
SOLO (sin pip, sin venv en la máquina del usuario; Arch trae python
siempre). Nada de Rust/Go/Node: instalar un toolchain para correr un
instalador contradice el objetivo plug-and-play.

Dependencias esperadas en un Arch base (todo en `base`/`extra`, nada de
AUR): `curl` (descargas; fallback a `wget`), `sha256sum` (coreutils),
`tar`, `unzip` (para zips de ANR/OptiScaler; fallback `bsdtar` o python
stdlib `zipfile` si falta), `7z` SOLO si algún archivo exigido sigue en
`.7z` (preferir que el release use `.zip`/`.tar.xz`; si el mod de nitec
llega en `.7z`, el script lo dice y sugiere `p7zip` de extra, o acepta el
contenido ya extraído por el usuario). `vulkaninfo` (paquete
`vulkan-tools`) solo para `doctor --verbose`; el chequeo básico usa
`ldconfig`/paths sin él. `lspci` (`pciutils`) con fallback a
`/sys/class/drm`. Todo chequeo de dependencias falla con mensaje que dice
el paquete exacto (`pacman -S …`, y el equivalente `apt`/`dnf` si se
detecta esa distro).

## 7. Riesgos, incógnitas y milestone v1

Riesgos (con su mitigación en el diseño):

- El driver precompilado no carga en la distro del usuario (glibc,
  libLLVM, SPIRV-Tools): mitigado con base de build vieja + `lib/bundled`
  (ya existe en upstream) + `doctor` que lo detecta antes de tocar nada.
- Update de Proton Experimental cambia vkd3d base y nuestros DLL
  desincronizan: la compatibility tool es una copia congelada (no sigue
  updates), `update` del release avisa cuando el pin queda viejo.
- `NVIDIA`-style `vkCreateDevice` roto con coopmat en otro driver: opt-in
  por perfil ANR, rollback quitando la env.
- NexusMods sin URL directa para el mod: el usuario lo aporta; el diseño
  no depende de automatizarlo.
- Dos generadores de frames a la vez (XeFG + XESS_FG del juego): el perfil
  por defecto no exporta `XESS_FG`; documentado como en el doc de
  `cp2077-xmx`.

Incógnitas (preguntas al usuario en el mensaje final):

1. ¿Pinneamos Proton Experimental o GE-Proton como base de la tool?
2. ¿El release vive en GitHub Releases de este repo o en otro lado?
3. ¿`fsr-original.dll` 4.1.2 puede mencionarse por nombre de archivo
   exacto/origen en el README público, o mejor instrucciones genéricas?
4. ¿Soporte Flatpak Steam en v1 o solo aviso?

Milestone v1 (mínimo shippable): `doctor` (solo lectura) + `install`
(Mesa precompilado + tool de compatibilidad + IGC/XeSS/FFX) + `enable`
Cyberpunk con FSR4 INT8 + `run` wrapper. Criterio de done: en una Arch
limpia con B580, sin haber leído el repo, `install → enable → pegar línea
en Steam → jugar con FSR 4.1.2X INT8` y `doctor` en verde. Después: Lite,
XeFG (ya funciona, solo empaquetar), ANR (falta corrida real que muestre
el `Keeping VK_KHR_cooperative_matrix…` en log).
