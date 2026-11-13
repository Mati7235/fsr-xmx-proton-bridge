# Bench de Cyberpunk 2077: XeSS vs FSR 4.1.2 XMX (2026-11-13)

Primera comparación de rendimiento entre el camino XeSS y FSR 4 sobre XMX en
la misma máquina, misma escena y mismos ajustes.

## Condiciones

- GPU: Intel Arc B580 (BMG G21), 12216 MB.
- CPU: Ryzen 5 5600X. 16 GB de RAM.
- Juego: Cyberpunk 2077 2.5, benchmark integrado (`benchmark.gamedef`).
- 1920x1080, preset Custom (texturas High), vsync off, sin límite de FPS.
- Prefijo descartable `compatdata-cp77`, driver del paquete candidato
  `xess-xmx-linux-20261113-cmk3`.
- Los resultados salen de
  `.../Documents/CD Projekt Red/Cyberpunk 2077/benchmarkResults/*/summary.json`.

## Resultados

| Corrida | Upscaler | avg FPS | min FPS | max FPS |
|---|---|---:|---:|---:|
| `cp-xess` | XeSS | 54.44 | 43.85 | 69.65 |
| `cp-int8` | FSR 4.1.2 Full (INT8) | 54.54 | 43.50 | 70.09 |
| `cp-lite` | FSR 4.1.2 Lite | 55.56 | 44.87 | 70.78 |
| `cp1` (corrida previa) | FSR 4.1.2 Full (INT8) | 54.56 | 43.95 | 69.85 |

Diferencias sobre el promedio:

- Full contra XeSS: +0.18 %, dentro del ruido.
- Lite contra XeSS: +2.06 %.
- Lite contra Full: +1.87 %.

Repetibilidad: dos corridas independientes del mismo modelo Full dieron
54.54 y 54.56 FPS (+0.04 %). Esa es la base para juzgar las diferencias
anteriores: el +2 % de Lite está por encima del ruido, el +0.18 % de Full
no.

## Qué modelo corrió de verdad

Del log del mod (`steam-0.log`, capturado con `PROTON_LOG=1` y
`WINEDEBUG=+debugstr`):

- Full: `INT8 model: preset weights from fsr-original.dll, bucket 0, Xe2
  SIMD16-DPAS kernels`, más `INT8 network kernels ready (bucket 0, preset
  weights)`.
- Lite: `Lite model: ...`, sin líneas de INT8.
- XeSS: ninguna línea de modelo del mod.

Del lado del driver, los conjuntos de kernels inyectados difieren:

- Full: 28 inyecciones, 14 kernels únicos.
- Lite: 12 inyecciones, 6 kernels únicos.
- Intersección: 1 solo kernel (el de muestreo de 30400 B).

Eso confirma que Lite ejecuta una red distinta y más chica, no un alias de
Full.

## Lectura

Coincide con lo que encontró `xess-xmx-linux`: FSR 4 sobre XMX no gana
rendimiento sobre XeSS; en Full queda estadísticamente empatado. La ventaja
de Lite es real pero chica (+2 %).

El valor de FSR 4 en este equipo no es el rendimiento sino la imagen: con el
mismo costo que XeSS se obtiene una reconstrucción notablemente más nítida.

## Límites

- Una sola escena de benchmark y una sola resolución.
- Preset Custom; no se probaron otros presets ni RT.
- No hay oracle de calidad: no se midió PSNR/SSIM contra referencia.
- El `summary.json` reporta `gpuDriverVersion: Radeon software 99.10.2`,
  que es el spoofing del mod, no el driver real (Mesa ANV).
- Las corridas se hicieron con el mismo prefijo, así que el estado de caché
  de shaders es comparable pero no idéntico entre la primera y la última.
