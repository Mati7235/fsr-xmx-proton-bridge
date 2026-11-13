# Estado de FSR 4 sobre XMX en upstream (xess-xmx-linux)

Registro de lo que el repo de `xess-xmx-linux` encontró y decidió sobre el
camino FSR 4 XMX, clonado el 2026-11-13 para verificarlo.

## Qué pasó

Upstream **ya tenía FSR 4 sobre XMX funcionando**. No fue un problema técnico
sin resolver: el 2026-11-02 el autor lo abandonó como dirección del proyecto,
en el commit `99445d8` ("Docs: FSR 4 on XMX is no longer developed").

Razones del abandono, en sus palabras (`docs/games.md`, sección
"FSR 4 on XMX (Upscaler Builds from the OptiScaler Discord)"):

1. Sin ganancia de rendimiento significativa sobre XeSS en XMX.
2. Más complejidad de setup.
3. Conflicto con la generación de frames XeSS: la combinación funcionaba,
   pero necesitaba correcciones de imagen para cada juego, justo lo que el
   proyecto evita (OptiScaler es el que se adapta por juego).

Lo que sí probaron: un solo build ("B Boost", FileVersion `4.0.2.1`) en una
sola GPU (Arc B390) y dos juegos. Setup manual, nada automatizado. El doc
quedó archivado para referencia.

## Lo que sus docs ya documentaban

Antes del abandono, `docs/games.md` describía casi toda la receta que este
repo había ido redescubriendo:

- El plugin va como `amd_fidelityfx_upscaler_dx12.dll`; OptiScaler no es
  obligatorio pero se puede usar.
- `fsr-original.dll` sale de AMD FSR SDK 2.4.0 (FSR 4.1.2), y el plugin lee
  los pesos de ahí. `install.sh` y `tools/get-ffx.sh` ya lo descargaban.
- `cabinet.dll` nativo de Windows + `WINEDLLOVERRIDES=cabinet=n,b`, porque
  Wine no implementa las ordinals 40, 43 y 45 que el plugin usa para
  descomprimir sus kernels.
- `FSR4_XMX_LITE=1` para el modelo Lite.
- El parche `0005-anv-cm-sampler-descriptor-table.patch` es obligatorio:
  "older drivers without patch 0005 render corrupted images".

Ese último punto coincide con lo observado acá: el ruido magenta de la
primera traza era el driver viejo sin `0005`, no una ABI rota del PRE.

## Rendimiento que midieron

Arc B390, 1280x800 de render, sin frame generation:

| Upscaler | Cyberpunk 2077 (fps prom.) | CONTROL Resonant (fps) |
|---|---|---|
| XeSS Ultra Quality (XMX) | 57.5 | — |
| FSR 4 en XMX, modelo full | 56.4 | 35 |
| FSR 4 en XMX, Lite | 58.2 / 58.1 | 36 |

Kernels FSR 4: 2.5 ms por frame (full) y 1.9 ms (Lite). Es decir, **Lite es
más rápido**, no igual. Si el overlay muestra el mismo tiempo para ambos
modelos, conviene revisar si Lite está corriendo de verdad.

## Qué aporta este repo entonces

No el puente mínimo, que upstream ya tenía: el camino 4.0.2X ("B Boost") ya
estaba documentado y funcionando. Lo que sí queda como trabajo propio:

- El camino **4.1.2X INT8**, que upstream no probó (ellos quedaron en
  `4.0.2.1`).
- Verificación de que `fsr-original.dll` satisface el contrato de pesos
  (`tools/xmx412_weight_scan.c`), en vez de asumirlo.
- El método de comparar corridas por fingerprint de código nativo
  (`tools/xmx_kernel_set.py`) para descartar fallback silencioso.
- El prototipo CMK3 de mapeo explícito y su generador de parches.

## Lección para el anuncio

Cualquier mensaje a nitec o al hilo debe reconocer que la ruta FSR 4 XMX ya
estaba soportada por `xess-xmx-linux`. Presentarla como un puente nuevo desde
cero sería inexacto. Lo que sí es nuevo es el camino INT8 de 4.1.2 y la
verificación a nivel kernel.
