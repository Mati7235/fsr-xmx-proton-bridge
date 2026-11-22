# VK_AMD_anti_lag (Anti-Lag 2) en ANV — port de software sobre `vk_frame_pacer`

Fecha: 2026-11-22. Mesa base: 26.3.0 (checkout en
`/home/matias/xess-xmx/build-20261113/mesa-src/26.3.0/`, copiado con `cp -a`
a `/home/matias/xess-xmx/mesa-antilag-26.3.0/` para no tocar el original).
Parche: `patches/0004-anv-anti-lag.patch`. GPU target: Intel Arc B580 (Xe2,
`ver == 20`).

## Qué se reutiliza

- `src/vulkan/runtime/vk_frame_pacer.{h,c}`: ya existe en 26.3 y es
  agnóstico de driver. Intercepta `QueueSubmit2`/`QueuePresentKHR` vía la
  dispatch table, inyecta timestamp queries + timeline semaphores por cola,
  y expone `vk_frame_pacer_init/finish/enable/disable/evaluate/calibrate/
  get_user_data`. No se tocó: el port solo lo consume.
- `src/amd/vulkan/radv_anti_lag.c` (152 líneas): referencia lógica. El port
  es la misma máquina de estados (EMA de frame time con alfa 0.5, EMA de
  desviación absoluta con alfa 0.125, queuing delay descontado, recalibración
  cada 8 s, `maxFPS` como piso del delay, sleep con
  `os_time_nanosleep_until`), renombrando `radv_` → `anv_`.

## Qué se agregó (5 archivos, ver parche)

- `src/intel/vulkan/anv_anti_lag.{c,h}` (nuevo): `anv_device_init_anti_lag`,
  `anv_device_finish_anti_lag`, `anv_AntiLagUpdateAMD`. El entrypoint se
  resuelve solo por nombre: `anv_entrypoints.h` generado ya declara
  `anv_AntiLagUpdateAMD` como weak (viene de `src/vulkan/registry/vk.xml`),
  así que definir el símbolo fuerte alcanza — igual que RADV. No existe
  `anv_extensions.py` en 26.3: extensión y feature se generan desde `vk.xml`.
- `src/intel/vulkan/anv_physical_device.c`:
  `.AMD_anti_lag = device->has_reg_timestamp` junto a `.AMD_buffer_marker`,
  y `.antiLag = pdevice->has_reg_timestamp` al final de `get_features`.
  El gate es el mismo que ANV usa para `KHR_calibrated_timestamps`: el
  pacer necesita timestamps calibrados (`vk_frame_pacer_calibrate` +
  `vk_device_get_timestamp`).
- `src/intel/vulkan/anv_device.c`: init tras `init_device_state` (colas y
  dispatch table listos, como exige `vk_frame_pacer_init`), solo si
  `device->vk.enabled_features.antiLag`; error → `goto fail_meta_device`.
  Finish en `anv_DestroyDevice` (tras TRTT, antes de destruir colas) y en el
  path `fail_queues` (no-op si el pacer nunca se inicializó).
- `src/intel/vulkan/meson.build`: alta de `anv_anti_lag.c/.h`.

## Cómo se compila (comandos exactos)

El regen de ninja necesita el pyenv del build original (el python del
sistema no tiene `mako`):

```sh
export PATH=/home/matias/xess-xmx/build-20261113/pyenv/bin:$PATH
cd /home/matias/xess-xmx/mesa-antilag-26.3.0
ninja -C build src/intel/vulkan/libvulkan_intel.so -j8
```

ICD para probar sin instalar:

```sh
S=/tmp/opencode/antilag-scratch
cat > $S/intel_icd.json <<EOF
{
  "file_format_version": "1.0.0",
  "ICD": {
    "library_path": "/home/matias/xess-xmx/mesa-antilag-26.3.0/build/src/intel/vulkan/libvulkan_intel.so",
    "api_version": "1.4"
  }
}
EOF
VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo --summary
VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo | grep -i -e anti_lag -e antiLag
cc tools/antilag_probe.c -lvulkan -o $S/antilag_probe
VK_DRIVER_FILES=$S/intel_icd.json $S/antilag_probe | tee analysis/antilag2-probe.log
```

## Resultados del probe

`analysis/antilag2-probe.log` (`tools/antilag_probe.c`, binario en
`/tmp/opencode/antilag-scratch/antilag_probe`):

```text
deviceName: Intel(R) Arc(tm) B580 Graphics (BMG G21)
driverVersion: 26.3.0
extension VK_AMD_anti_lag: present (spec 1)
feature antiLag: true
vkCreateDevice with VK_AMD_anti_lag: OK
vkAntiLagUpdateAMD: resolved
mode=ON maxFPS=30 frames=60: 1.976 s (32.9 ms/frame)
mode=OFF maxFPS=30 frames=60: 0.000 s (0.0 ms/frame)
RESULT: PASS (expected ON ~= 2 s pacing, OFF << 1 s)
```

## Verificación

`S=/tmp/opencode/antilag-scratch` (ICD con `library_path` absoluto al
`.so` recién compilado).

| Comando | Salida esperada | Salida obtenida |
|---|---|---|
| `VK_DRIVER_FILES=$S/intel_icd.json vulkaninfo --summary` | `deviceName = Intel(R) Arc(TM) B580 Graphics`, driver Mesa 26.3.0 | `deviceName = Intel(R) Arc(tm) B580 Graphics (BMG G21)`, `driverVersion = 26.3.0` ✅ |
| `vulkaninfo \| grep -i -e anti_lag -e antiLag` | `VK_AMD_anti_lag` + `antiLag` | Solo `VK_AMD_anti_lag : extension revision 1` ⚠️ (ver nota) |
| probe `mode=ON maxFPS=30` 60 frames | ≈ 2 s de pacing | `1.976 s (32.9 ms/frame)` ✅ |
| probe `mode=OFF` 60 frames | << 1 s | `0.000 s` ✅ |

Nota: la feature `antiLag` **sí** está expuesta y funcional (el probe la
lee con `vkGetPhysicalDeviceFeatures2`, crea el device con ella y usa el
entrypoint), pero este `vulkaninfo` del sistema no la imprime: su chain de
features es fija y no incluye `VkPhysicalDeviceAntiLagFeaturesAMD` (igual
que no imprime `bufferMarker` de `VK_AMD_buffer_marker`). Limitación del
cliente, no del driver.

## Bugs encontrados durante la verificación

1. **Segfault en `vk_frame_pacer_enable`**: `vk_device_get_timestamp(..,
   VK_TIME_DOMAIN_DEVICE_KHR, ..)` llama `device->get_timestamp`, hook que
   RADV setea en `radv_CreateDevice` pero ANV dejaba en NULL. Fix en
   `anv_anti_lag.c`: `anv_device_get_timestamp` vía
   `intel_gem_read_render_timestamp` (el mismo ioctl que usa
   `anv_GetCalibratedTimestampsKHR`), instalado en
   `anv_device_init_anti_lag`, solo cuando Anti-Lag está habilitado.
2. **El `build/` copiado apuntaba al fuente original** (`Source dir:
   .../build-20261113/mesa-src/26.3.0`): el primer `.so` se compiló sin el
   port. Se borró `build/` y se reconfiguró con `meson setup` + las
   opciones exactas del `meson-log.txt` original, agregando al entorno
   `PKG_CONFIG_PATH=.../build-20261113/local-deps/lib/pkgconfig` y
   `local-deps/bin` (el `SPIRV-LLVM-Translator` precompilado; `meson setup`
   falla sin él con `Dependency "LLVMSPIRVLib" not found`). Solo lectura
   del árbol `build-20261113`; el original no se modificó.

## Switch para desactivar XeLL

`IGDEXT_XELL_CAP=off` (variable de entorno, no hay clave de OptiScaler.ini
involucrada). Se lee en `StartXellHook`
(`upstream/xess-xmx-linux/shim/src/dll/XellHook.cpp`): `off` (o `0`) pone
`g_capAuto = false` sin cap fijo → el shim no retiene los frames en
`xellSleep` y la swap chain le responde al juego. Documentado en
`upstream/xess-xmx-linux/docs/launch-options.md` (`IGDEXT_XELL_CAP=off`:
"Turns the low latency off"). Variantes: `auto[:ms]` (margen), número
`1..1000000` (cap fijo en µs en vez del pacing), `IGDEXT_XELL_CHECK=0` y
`IGDEXT_XELL_POLLS=0` (solo diagnóstico).

## Riesgos conocidos

- **Doble pacing**: Anti-Lag 2 (driver/Vulkan) y XeLL (shim, `xellSleep`)
  duermen el hilo del juego con criterios distintos. Para medir Anti-Lag
  puro, desactivar XeLL con `IGDEXT_XELL_CAP=off`.
- **Extensión AMD en driver Intel**: es solo un nombre; la implementación es
  100 % genérica (`vk_frame_pacer`). La app debe pedir `VK_AMD_anti_lag`
  explícitamente; nada cambia si no se pide.
- **`assert(timestampValidBits == 64)`** en `vk_frame_pacer_enable`
  (`vk_frame_pacer.c`): ANV reporta 64 bits solo en `ver >= 20`
  (`anv_physical_device.c`, Bspec 60411; pre-Xe2 son 36). En Intel viejas,
  llamar con `mode = ON` aborta en builds debug. El gate
  `has_reg_timestamp` no cubre eso: documentado, no "arreglado".
- **`vk_frame_pacer` parchea la dispatch table** (`QueueSubmit2`/
  `QueuePresentKHR`) desde `vk_frame_pacer_init` hasta `finish`: el
  `finish` debe correr antes de `vk_device_finish` (se cumple).

## Qué falta para probarlo en un juego D3D12 (vkd3d-proton ≥ 3.0)

1. Instalar o exponer el ICD compilado al prefix de prueba (descartable) y
   confirmar `vulkaninfo` dentro de ese entorno.
2. Juego con Anti-Lag 2 nativo (menú del juego) o vkd3d-proton ≥ 3.0 con
   soporte `VK_AMD_anti_lag` (ver `upstream/vkd3d-proton`, versión
   pineada en este repo).
3. Comparar latencia/frame-rate con XeLL apagado (`IGDEXT_XELL_CAP=off`)
   vs. Anti-Lag ON, y luego ambos combinados; mirar `igdext_xell.log`
   (`XESS_LOG=1`) para el frame rate real.
4. Validación real = evidencia de inyección + readback determinista de GPU
   (etiqueta de overlay o `S_OK` solos no cuentan, por AGENTS.md).
