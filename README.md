# Puente FSR4 XMX sobre Intel Linux

Puente experimental para correr el mod FSR4 XMX de nitec sobre Intel Linux
usando `xess-xmx-linux`: su driver Mesa ANV parcheado compila los kernels
CM del mod y los ejecuta en las unidades XMX en vez de la ruta DP4a de
Wine/Proton. Investigación de compatibilidad, no un producto.

## Estado actual

Primera ejecución funcional de FSR 4 sobre XMX en Marvel's Spider-Man
Remastered (2026-11-13) con el paquete candidato side-by-side
(`xess-xmx-linux-20261113-cmk3`, Mesa 26.3.0 + shim + registry 4.1.2).
Ver: `docs/first-fsr-xmx-success.md` y `docs/rebuild-20261113.md`.

- Probado en Spider-Man: 4.0.2X (ruta base, evidencia funcional completa) y
  4.1.2X INT8 (corrida con `FSR4_XMX_INT8=1` y 4.1.2 en OptiScaler: despacha
  sus propios passes de red; el modelo quedó inferido del set de kernels).
- Probado en Cyberpunk 2077 (bench integrado): 4.1.2X INT8 y Lite,
  confirmados por log (`INT8 model:` y `Lite model: 2`) y por sets de kernels
  distintos. FPS en `docs/cyberpunk-bench-20261113.md`; calidad en
  `docs/cyberpunk-quality-20261113.md`.
- No probado todavía: el camino DLSS. Los pesos Lite/INT8 están verificados a
  nivel archivo.
- Verificado a nivel kernel: inyección, sampler heap, 11 recursos FSR4,
  0 device lost. Sin oracle independiente ni readback determinista.
- No instalado system-wide: el paquete activo del usuario sigue intacto;
  el candidato corre solo por proceso. Rollback en `backup-20261113/`.

Guía de instalación y setup real: `docs/install-setup.md`.
Contexto de upstream: FSR 4 sobre XMX ya estaba soportado en `xess-xmx-linux`
y se abandonó como dirección de producto en noviembre de 2026, no por un
bloqueo técnico. Ver `docs/upstream-fsr4-status.md`.

## Arquitectura

1. Driver ANV parcheado: inyecta y compila kernels CM con ocloc en runtime.
2. Shim `igdext64.dll`: responde queries Intel y entrega placeholders CM.
3. Helper `tools/cm-compile.sh` del paquete: compila cada kernel al primer uso.
4. Mod FSR4 XMX + `fsr-original.dll` + `cabinet.dll` juego-local: el mod
   emite el PRE y los packs; OptiScaler lo enchufa como `Dx12Upscaler = ffx`.

## Docs clave

| Doc | Qué fija |
|---|---|
| `docs/install-setup.md` | Instalación side-by-side y system-wide, rollback, prueba en juego |
| `docs/upstream-fsr4-status.md` | Qué encontró y por qué abandonó upstream el camino FSR 4 XMX |
| `docs/first-fsr-xmx-success.md` | Setup exacto y evidencia de la primera ejecución funcional |
| `docs/rebuild-20261113.md` | Qué se construyó en el paquete candidato y qué falta |
| `docs/xmx412-model-selection.md` | Selección INT8/Lite/Hybrid, contrato de `fsr-original.dll`, receta |
| `docs/cabinet-shim.md` | Shim juego-local de Cabinet para los packs LZMS del mod |
| `docs/spiderman-trace-runbook.md` | Runbook de traza manual en Spider-Man con Proton Experimental |
| `docs/bench-quality.md` | Grabación lossless, recorte del bench y métricas de calidad |
| `docs/cyberpunk-bench-20261113.md` | FPS en Cyberpunk: nativo, XeSS, FSR INT8 y Lite |
| `docs/cyberpunk-quality-20261113.md` | Calidad medida, clips y límites del método |

## Comparar calidad de imagen

Los recortes del bench y los proxies están en `analysis/quality-cp77/` (local,
ignorado por Git). Para comparar dos variantes con slider:

1. Abrir `https://hallo.io/tools/video/video-compare`.
2. Cargar `analysis/quality-cp77/proxies/ref-native.mp4` como A y uno de
   `xess.mp4`, `fsr4-int8.mp4` o `fsr4-lite.mp4` del mismo directorio como B.
3. Elegir `Slider`, dar play y arrastrar el divisor. La herramienta sincroniza
   la línea de tiempo y corrige la deriva.

No se sube nada: la comparación corre en el navegador. Usar los proxies
H.264 4:2:0; los clips lossless son 4:4:4 y el navegador puede no
decodificarlos.

Para stills, `analysis/quality-cp77/pairs/` tiene el mismo crop a 800x450 por
escena y variante (`0.80-native.png` contra `0.80-fsr4-lite.png`, etc.),
listo para un slider de imágenes (imgico, DualView). El 2x2 de los cuatro
está en `analysis/quality-cp77/compare-crop.mp4`.

## Herramientas (`tools/`)

- `tools/inspect_dll.py`: inventario estático de DLLs (cadenas, SHA-256).
- `tools/parse_cm_payloads.py`: extracción de bloques CM por pies y longitudes.
- `tools/decompress_mscf.py`, `tools/decompress_xmx412.py`: descompresión
  LZMS de packs con wimlib local.
- `tools/xmx_kernel_set.py`: fingerprint y diff de kernels entre corridas.
- `tools/bench_quality.py`: alineación de grabaciones, PSNR/SSIM/nitidez y crops.
- `tools/build_cabinet_shim.py`: construye el `cabinet.dll` juego-local.
- `tools/prepare_trace_capture_412.py`: andamiaje CPU-only del run de traza.

## Licencia y procedencia

Los binarios de terceros no se redistribuyen y este repo no concede derechos
sobre modelos, DLLs o código upstream; consultar sus licencias respectivas
(`THIRD_PARTY.md` del paquete, licencias de AMD/Intel/nitec/Valve).

## Procedencia

- Upstream `xess-xmx-linux`: `662dc6e` (178 commits desde `ef39559`).
- Parches del paquete: `0001` inyección CM (CMK3, magia corregida),
  `0002` debug, `0003` Large GRF para Xe2, `0005` tabla de descriptores
  sampler, más serie `patches/mesa-26.3/` (`0004` Jay, `0006` cmat).
- Este repo ignora `artifacts/original/`, `artifacts/extracted/` y
  `upstream/` (checkouts locales, no redistribuidos).

## Límites

- Solo Spider-Man, una sesión funcional. Nada aquí acredita otros juegos.
- Sin oracle: no hay equivalencia matemática con la referencia ni captura
  RenderDoc de formatos reales.
- S_OK, overlay o shaders creados no prueban el modelo; el log manda.
- Nunca tocar Steam, prefijos reales, drivers o sistema sin aprobación
  explícita; los experimentos runtime usan prefijo descartable.
