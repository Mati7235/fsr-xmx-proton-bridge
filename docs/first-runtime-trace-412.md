# Primera traza runtime 4.1.2 en Spider-Man (2026-11-12)

Solo lectura de evidencias generadas por ejecución manual del usuario.
Ningún dispatch PRE fue autorizado ni ejecutado por el agente.

## Setup

- Juego: Marvel's Spider-Man Remastered (80 GB) en
  `/home/matias/Juegos/Spiderman/Marvel's Spider-Man Remastered/`,
  con OptiScaler (`Dx12Upscaler = ffx`) y mod XMX 4.1.2
  (`amd_fidelityfx_upscaler_dx12.dll` `fadbcb50…`, verificado).
- Prefijo descartable + scaffold:
  `build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/`.
- Saves del usuario copiados al prefijo (slot0/slot1 + prefs).
- Comando: Proton Experimental `proton run` + `STEAM_COMPAT_DATA_PATH`
  + `VKD3D_DEBUG=trace` + (2º intento) `WINEDLLOVERRIDES="cabinet=n,b"`.
- Stack en juego (no nuestro): igdext de Proton Experimental +
  Mesa 26.3.0-rc1 parcheada del usuario
  (`/home/matias/xess-xmx/xess-xmx-linux-20261018`, driver-status ok) +
  nuestro `cabinet.dll` mínimo juego-local (`dbc9c6e`, 70 KB).

## Secuencia observada

1. Primer intento sin shim: abort
   `wine: Call to ... unimplemented function Cabinet.dll.40`
   (log `vkd3d-trace.log`, 85 KB). Wine/Proton no implementa la
   Compression API (verificado: 0 exports en todos los builds locales).
2. Con `cabinet.dll` juego-local: el juego arranca, overlay
   `FFX -> FSR 4.0.2`, upscaler 0.8–0.96 ms (vs ~2 ms sin XMX).
   UI perfecta, mundo 3D = ruido magenta/verde.
3. Guardado `evidence/vkd3d-trace2-20261112.log`
   (`8894270d…`, 7.775.448 B, 50.417 líneas).

## Hallazgos del log y artefactos

- Sin abort de Cabinet: los 6 packs LZMS cargaron vía el shim.
- `d3d12_resource_SetName: FSR4 resource detected` (vkd3d workaround
  activo, docenas de ocurrencias).
- `ANV CM: compiling kernel 60..76, 103..111` (~26 compilaciones,
  toolchain gen `0913d3f4` del bridge instalado, NO nuestro
  `912cda6a`/`3ddd809f`).
- `ANV CM: ...e8fca351200197b3_e20b_0913d3f4.cmk samples but the
  pipeline layout has 0 static samplers (using linear/clamp)` ×4:
  un kernel con sampling compiló con fallback de sampler.
- El shim volcó 112 kernels (`dyn_0..dyn_111` + `.opt` + `map.txt` +
  `anv_canary`) en `compatdata/pfx/drive_c/igdext_kernels/`.
- **`dyn_60.spv` (358.873 B) es `fsr4_pre_xmx`**: magia SPIR-V, pie
  `-vc-payload`, entry confirmado. El PRE SÍ fue enviado al puente.
- `dyn_60.opt` vacío (CompileOptions/InternalOptions NULL, como en
  el análisis estático).
- `dyn_60.spv` vs envelope offline `ce372719…`: **3 bytes difieren**
  (offset 59112–59114): `OpConstant %float %id = 68.45…` (offline)
  → `67.18…` (runtime). Una constante float parcheada por el mod por
  dispatch (probable especialización por resolución/calidad), no
  corrupción.
- **Ningún `.cmk` del caché supera 35 KB** (PRE necesitaría ~360 KB):
  no hay evidencia de que el PRE se haya compilado en ANV en esta
  sesión. Hipótesis principal del ruido: el PRE nunca despachó (o su
  compilación fue rechazada/fallback silencioso) y la cadena aguas
  abajo leyó su buffer de salida sin inicializar. Sin confirmar:
  falta correlacionar `dyn_60` con el contador interno de ANV y
  revisar `compile.log` con timestamps por sesión.

## Lo que esto prueba y lo que no

- Prueba: el camino mod→extensión→VKD3D→ANV funciona de punta a punta
  con nuestro shim de Cabinet; el mod envía el PRE real; XMX hace
  trabajo real (timing).
- No prueba: corrección funcional, bindings del PRE, ni que el
  fallback de sampler sea la causa del ruido. El overlay y el timing
  no son veredicto.

## Pendiente

1. RenderDoc frame con el upscaler activo (formatos reales).
2. Confirmar destino del PRE en ANV (compilado / rechazado / no-op).
3. `evidence/versions/` del run (checklist sin llenar).
4. Decidir instalación de nuestros parches (0002/0003/0001+registry
  `3ddd809f`) sobre el stack del usuario: requiere reconstruir su
  Mesa/shim; no tocar sin aprobación explícita.
