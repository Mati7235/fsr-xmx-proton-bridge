# Calidad de imagen: FSR 4.1.2 XMX contra XeSS y nativo

Comparación sobre el benchmark integrado de Cyberpunk 2077, con grabaciones
lossless y métricas calculadas contra el render nativo. Fecha: 2026-11-13.

## Condiciones

- 1920x1080, preset Custom, RT local shadows, misma zona del bench.
- Grabación lossless H.264 4:4:4 RGB (`gbrp`, rango completo), 60 fps, con
  `wf-recorder`.
- Referencia nativa: upscaling Off en el juego y `--native` en el launcher
  (sin OptiScaler ni DLL del mod). El resumen del juego marca
  `upscalingType=0` y `FSR4=False`.
- XeSS 2.0.1 vía OptiScaler (`injected: 0` en el log del mod).
- FSR 4.1.2 INT8 y Lite vía el mod, con kernels `Xe2 SIMD16-DPAS`.
- Las corridas grabadas midieron 41,7 (nativa), 35,7 (XeSS), 36,7 (FSR
  INT8) y 28,4 (Lite) fps. Son más lentas que las corridas sin grabar
  (54-55 fps), así que estos videos no sirven para comparar rendimiento.

## Clips

Cada clip arranca en el primer frame con imagen después del hueco negro de
carga y termina justo antes del panel de resultados.

| Clip | Inicio en la fuente | Fin | Duración | Peso |
|---|---:|---:|---:|---:|
| `ref-native.mkv` | 78,768 s | 148,132 s | 69,37 s | 6,4 GB |
| `xess.mkv` | 79,883 s | 149,200 s | 69,32 s | 5,6 GB |
| `fsr4-int8.mkv` | 64,800 s | 134,117 s | 69,32 s | 5,7 GB |
| `fsr4-lite.mkv` | 80,367 s | 149,833 s | 69,47 s | 4,3 GB |

Los MP4 H.264 4:2:0 para comparar están versionados en
`media/quality-cp77/`. Los clips lossless (4:4:4) y los frames a resolución
completa quedan en `analysis/quality-cp77/`, fuera de Git por tamaño.

## Métricas

Crop fijo de 400x225 en (760,100); según la posición cae en la reja, los
edificios o la torre "03". PSNR y SSIM contra la referencia nativa; más alto
es más parecido al nativo.

| Posición | t (s) | Muestra | PSNR full | SSIM full | PSNR crop | SSIM crop | Nitidez |
|---|---:|---|---:|---:|---:|---:|---:|
| 0,20 | 13,8 | nativo | - | - | - | - | 491,9 |
| 0,20 | 13,8 | XeSS | 25,73 | 0,8286 | 27,86 | 0,7135 | 525,2 |
| 0,20 | 13,8 | FSR INT8 | 22,98 | 0,7302 | 24,01 | 0,5985 | 544,6 |
| 0,20 | 13,8 | FSR Lite | 24,91 | 0,8038 | 25,11 | 0,5684 | 538,4 |
| 0,50 | 34,5 | nativo | - | - | - | - | 535,3 |
| 0,50 | 34,5 | XeSS | 22,51 | 0,8847 | 19,51 | 0,7857 | 561,5 |
| 0,50 | 34,5 | FSR INT8 | 23,66 | 0,9100 | 20,85 | 0,8499 | 580,1 |
| 0,50 | 34,5 | FSR Lite | 24,04 | 0,9144 | 20,10 | 0,8788 | 606,6 |
| 0,80 | 55,2 | nativo | - | - | - | - | 581,6 |
| 0,80 | 55,2 | XeSS | 17,15 | 0,7780 | 18,82 | 0,9168 | 677,3 |
| 0,80 | 55,2 | FSR INT8 | 17,66 | 0,7865 | 17,07 | 0,8730 | 638,1 |
| 0,80 | 55,2 | FSR Lite | 18,61 | 0,8302 | 21,19 | 0,9519 | 694,6 |

Nitidez = varianza del Laplaciano sobre luma, frame completo. Los crops
están en `analysis/quality-cp77/report/crop_*.png`.

## Lectura

- Nitidez: las tres variantes superan al nativo en varianza del Laplaciano.
  Eso confirma que agregan detalle de alta frecuencia, no que se vean mejor:
  el oversharpening también sube el número.
- En la escena oscura (0,20) XeSS tiene el mejor PSNR y SSIM. A 0,50 INT8
  gana en PSNR y Lite en SSIM. A 0,80 Lite gana en ambos.
- Lite no es una versión descartable de INT8: usa 6 kernels en vez de 14 y en
  dos de las tres escenas da SSIM más alto y más nitidez.
- El orden no es estable: XeSS gana la escena oscura, Lite gana SSIM en las
  diurnas e INT8 queda en el medio. Ninguno gana en todo el recorrido.
- El PSNR de frame completo incluye peatones y vehículos que no caen en la
  misma posición entre corridas. Por eso el número bajo no significa que el
  upscaler esté mal: la medida útil es la del crop estático.

## Límites

- Una sola corrida por variante. Para afirmar algo más fuerte hace falta
  repetir en otra zona del bench y con otro preset.
- La referencia es el TAA del juego, no ground truth absoluto.
- La captura pasa por el compositor y por la conversión a 60 fps, así que
  agrega diferencias que no son del upscaler.
- El contador del juego dice 64,2 s; el tramo grabado dura ~69 s de reloj por
  tirones y carga.

## Reproducir

```bash
mpv media/quality-cp77/ref-native.mp4
```

El 2x2 de los cuatro, con el mismo crop de 400x225 al doble, está en
`analysis/quality-cp77/compare-crop.mp4` (local): nativo, XeSS, FSR INT8 y
FSR Lite.
