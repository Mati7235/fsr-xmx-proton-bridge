# Captura de un frame real con RenderDoc (vkd3d-proton, solo inspección)

> ADVERTENCIA DE RENDIMIENTO: capturar con RenderDoc cambia el timing
> (serializa colas, añade sobrecarga de CPU, fuerza sincronización extra).
> Los FPS / frametimes observados bajo captura NO son representativos y una
> regresión aparente bajo RenderDoc NO prueba una regresión real.
> La captura sirve para INSPECCIÓN DE RECURSOS (qué texturas/buffers entran
> al upscaler, dimensiones de dispatch, layout de descriptores), no para
> medir rendimiento. Las mediciones se hacen siempre con `run-full-test.sh`
> sin RenderDoc.

## Viabilidad (qué es seguro y qué es incierto)

Verificado localmente (CPU-only, sin ejecutar el juego):

- RenderDoc instalado: `renderdoccmd` x64 v1.46 (Arch), `qrenderdoc`,
  `/usr/lib/librenderdoc.so`. APIs compiladas: **Vulkan, GL, GLES**
  (NO hay backend D3D12 en esta build Linux).
- Capa de captura registrada: `/etc/vulkan/implicit_layer.d/renderdoc_capture.json`,
  capa `VK_LAYER_RENDERDOC_Capture`, se activa con
  `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` y se desactiva con
  `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46=1`.
- Conclusión: RenderDoc **sí puede capturar** la corrida, pero a nivel
  **Vulkan traducido por vkd3d-proton**, no a nivel D3D12. En la captura se
  ven los `vkCmdDispatch` / pipelines / descriptor sets que vkd3d-proton
  genera a partir del D3D12 del juego y del mod FSR. Los marcadores
  `PIX`/D3D12 aparecen solo en la medida en que vkd3d-proton los propaga
  como nombres de objetos o marcadores de debug.

Limitaciones prácticas conocidas:

1. No se ve el D3D12 original (root signatures, PSOs D3D12) sino su
   traducción a Vulkan. Para correlacionar con el trazo D3D12 sirve el
   `vkd3d.log` (`VKD3D_DEBUG=trace`) que el script guarda junto a la captura.
2. Los kernels CM del driver parcheado (compilados vía `ANV_CM_HELPER`)
   NO se ven como shaders normales: aparecen como dispatches de cómputo
   con blobs internos del driver, sin fuente HLSL/GLSL/SPIR-V legible.
   NO esperes inspeccionar el código del kernel en RenderDoc.
3. RenderDoc 1.46 no maneja bien `VK_EXT_descriptor_buffer`; el launcher ya
   lo desactiva (`VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer`) y el
   script de captura lo mantiene desactivado. No lo reactives.
4. La sesión es Wayland; esta build de RenderDoc lista WSI xlib, XCB y
   KHR_display (sin Wayland nativo). El juego corre vía XWayland, que cae
   en el path xlib/XCB soportado. Si la ventana no responde a F12, probar
   con foco explícito en la ventana del juego (no en el overlay ni en otra
   ventana).
5. MangoHud está forzado OFF bajo captura (engachar Vulkan dos veces
   invalida la captura y el timing). No hay CSV de frametimes en este modo.

Supuestos NO verificados sin ejecutar (inciertos, anotados honestamente):

- Que la versión actual de vkd3d-proton dentro de Proton Experimental no use
  ninguna extensión o patrón que RenderDoc 1.46 no entienda (p. ej. cambios
  recientes de descriptor buffers, mesh shaders, video). Si la captura sale
  vacía o corrupta, ver "si la captura sale vacía".
- Que la tecla F12 llegue al juego a través de Proton/XWayland con el foco
  correcto. Alternativa: `qrenderdoc` → Attach to Running Instance.
- Tamaño manejable del `.rdc` (un frame AAA puede ocupar varios GB; hay
  ~390 GB libres en `/home`, suficiente en principio).

## Requisitos

- Misma máquina y prefijo descartable que la corrida funcional; no se toca
  el sistema ni el prefijo de producción.
- `renderdoccmd` en PATH, `/usr/lib/librenderdoc.so` presente,
  `/etc/vulkan/implicit_layer.d/renderdoc_capture.json` presente.
- Variable `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46` NO fijada (el script
  aborta si lo está, porque la captura saldría vacía).
- Driver candidato, `kernels-candidate/`, `fsr-original.dll` y `compatdata/`
  ya existentes en el directorio del run (el script los reutiliza, no los
  regenera salvo `--fresh-kernels`).

## Comando exacto

Desde el directorio del run:

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-renderdoc.sh int8 ciudad-rdc
# o: ./run-renderdoc.sh lite ciudad-rdc
# o: ./run-renderdoc.sh stock ciudad-rdc
```

Flags opcionales (los mismos que `run-full-test.sh`, menos MangoHud):

- `--proton-log`: además guarda `steam-proton.log` con el log del mod.
- `--fresh-kernels`: recompila kernels en `captures/<tag>-<modelo>-<stamp>/kernels`
  en vez de reutilizar `kernels-candidate/`.

El script es gemelo de `run-full-test.sh` en entorno (mismo Proton, mismo
ICD candidato, mismo `VKD3D_DISABLE_EXTENSIONS`, mismas `ANV_CM_*`, mismo
modo int8/lite/stock) con tres diferencias: (a) envuelve el lanzamiento con
`renderdoccmd capture --opt-hook-children`, (b) fija
`ENABLE_VULKAN_RENDERDOC_CAPTURE=1` y apaga explícitamente todas las demás
capas implícitas **excepto** la de RenderDoc (no se puede usar `'*'` porque
apagaría también la captura), y (c) escribe en `captures/` en vez de
`results/`.

## Tecla y dónde queda el `.rdc`

- Con la ventana del juego en foco, pulsar **F12** (tecla de captura por
  defecto de RenderDoc) en la escena a inspeccionar. Se pueden tomar varios
  frames seguidos; cada uno genera un archivo nuevo.
- Los archivos quedan en `captures/<tag>-<modelo>-<stamp>/spiderman_frame*.rdc`.
- Abrir con: `qrenderdoc captures/<tag>-<modelo>-<stamp>/spiderman_frame<N>.rdc`
- Junto a cada captura quedan `vkd3d.log`, `fingerprint.txt` y `summary.txt`
  (mismo criterio de evidencia de inyección que `run-full-test.sh`).

## Si la captura sale vacía o el juego no arranca

1. **Sin `.rdc` tras F12**: confirmar foco en la ventana del juego y reintentar
   F12. Alternativa: abrir `qrenderdoc` → File → Attach to Running Instance,
   conectarse al proceso y disparar la captura desde la UI.
2. **El juego no arranca bajo `renderdoccmd` pero sí con `run-full-test.sh`**:
   verificar que `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46` no esté fijada en el
   shell (`env | grep RENDERDOC`), y que no haya otro overlay activo
   (MangoHud, OBS, gamescope). El script ya apaga los conocidos; si se
   instaló otro overlay con capa implícita, añadirlo a `LAYERS_DISABLE`.
3. **Captura de 0 bytes o que no abre**: probar `--fresh-kernels` (descarta
   interferencia del caché de kernels) y revisar `vkd3d.log` buscando errores
   de creación de dispositivo Vulkan. Puede ser una extensión que RenderDoc
   1.46 no soporta: reportarlo con la versión de Proton y el log.
4. **El juego arranca pero todo va muy lento / se cuelga**: esperado en parte
   (sobrecarga de captura + `VKD3D_DEBUG=trace`). No es una regresión del
   driver. Si impide llegar a la escena, pedir una variante con trazo
   reducido (no improvisar cambios en el entorno a mano).
5. **`renderdoccmd` se queja de la capa**: re-verificar
   `renderdoccmd version` y el manifiesto
   `/etc/vulkan/implicit_layer.d/renderdoc_capture.json`.

## Cómo volver al launcher normal

Cerrar el juego y seguir midiendo con el launcher sin captura:

```bash
./run-full-test.sh int8 ciudad1
```

Nada del modo captura contamina las mediciones: escribe en `captures/`, no
toca `results/`, y no modifica `compatdata/` más allá del uso normal del
juego. `VK_LOADER_LAYERS_DISABLE` vuelve a su valor del launcher original.

## Qué NO esperar de la captura

- NO ver los kernels CM del driver como shaders normales con fuente
  inspeccionable (son blobs internos del path `ANV_CM_*`, opacos).
- NO ver el pipeline D3D12 original (root signatures, PSOs D3D12): solo su
  traducción a Vulkan hecha por vkd3d-proton.
- NO usar los tiempos de la captura para comparar int8 vs lite vs stock.
- NO tomar la captura como prueba de inyección por sí sola: la prueba de inyección
  sigue siendo `ANV CM:.* injected` en `vkd3d.log` + `fingerprint.txt`,
  igual que en `run-full-test.sh`.
