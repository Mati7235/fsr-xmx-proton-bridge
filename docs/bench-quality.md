# Medir calidad de imagen entre upscalers

Procedimiento para comparar FSR 4.1.2 XMX contra XeSS y contra un render
nativo, con evidencia numérica y visual. Requiere `wf-recorder`, instalado
desde los repos oficiales (`wf-recorder 0.6.0`).

## Por qué no alcanza con el ojo

"Se ve más nítido" es una impresión. Para que sea un dato hacen falta tres
cosas: la misma escena, una referencia y una métrica. La referencia correcta
no es otro upscaler sino el render nativo: el trabajo de FSR es aproximar lo
que verías sin upscaler.

## Grabación

`wf-recorder` graba la salida del compositor sin pérdida. El launcher lo
arranca y lo para solo con `--record`:

```bash
./run-full-test.sh manual ref-native --game cyberpunk --native --record --proton-log
./run-full-test.sh manual cp-xess     --game cyberpunk --upscaler xess --record --proton-log
./run-full-test.sh int8  cp-int8      --game cyberpunk --record --proton-log
```

- `ref-native`: `--native` aparta `dxgi.dll` (OptiScaler) y la DLL del mod
  durante la corrida; el juego queda con su TAA. Apagar el upscaler en el
  menú no alcanza: Cyberpunk aplica FSR en las cinemáticas del bench aunque
  esté en Off.
- `cp-xess`: XeSS.
- `cp-int8`: FSR 4.1.2.
- Cada corrida deja `bench.mkv` en su carpeta de resultados.

Parámetros de grabación: `libx264rgb`, `crf=0` (lossless, `Avg QP 0.00`),
4:4:4, 1920x1080, 60 fps, MKV. Nada de AV1 ni de 4:2:0: destruyen la
crominancia justo donde se nota la diferencia.

Condiciones: misma resolución, mismo preset, mismas opciones gráficas, y
correr el bench completo en las tres.

## Recortar el bench

Las grabaciones completas traen escritorio, menú, carga y resultados. Para
comparar conviene cortar una vez el tramo del bench en cada video:

- **Inicio**: primer frame con imagen después del hueco negro de carga previo.
- **Fin**: justo antes del corte a la pantalla de resultados (fondo oscuro,
  "Average FPS" en naranja).
- Duración típica: ~69 s de reloj, aunque el contador del juego diga 64,2 s.

```bash
ffmpeg -v error -y -ss 79.883 -i bench.mkv -t 69.317 \
  -c:v libx264rgb -crf 0 -preset ultrafast -pix_fmt gbrp -an -sn bench-clip.mkv
```

`-ss` antes de `-i` y re-encode dan un corte exacto al frame. Con `-c copy`
el corte cae en el keyframe anterior y puede errar hasta 4 s. El re-encode
con `libx264rgb -crf 0` es lossless sobre RGB, igual que la grabación. Guardar
los segundos usados en un JSON al lado del clip.

## Análisis

Sobre los clips ya recortados, con `--length` igual a la duración del clip:

```bash
python3 tools/bench_quality.py report \
  --ref analysis/quality-cp77/clips/ref-native.mkv \
  --alt "XeSS=analysis/quality-cp77/clips/xess.mkv" \
  --alt "FSR 4.1.2=analysis/quality-cp77/clips/fsr4-int8.mkv" \
  --alt "FSR 4.1.2 Lite=analysis/quality-cp77/clips/fsr4-lite.mkv" \
  --out analysis/quality-cp77/report \
  --length 69 \
  --crop 760,100,400,225
```

Los clips arrancan en el mismo frame del bench y la cámara sigue una línea de
tiempo fija, así que el mismo segundo corresponde a la misma posición aunque
un clip tenga 60 fps y otro no. Verificado: a los 30 s el offset óptimo entre
XeSS y Lite es 0, y correrse un frame empeora el MSE 2 a 4 veces. Contra la
nativa queda un residuo de 2 o 3 frames, que el tool corrige solo.

Qué hace:

1. Saca miniaturas a 1 fps de cada video.
2. Detecta el bench: busca el tramo de `--length` segundos que **mejor
   coincide entre la referencia y cada video**. El bench repite el mismo
   recorrido de cámara, así que alinearlo da el mínimo error; el menú tiene
   fondo animado pero no está sincronizado entre corridas, y la carga
   directamente cambia. Devuelve el segundo de inicio en la referencia y el
   desfase de cada video. Con clips que ya empiezan en el bench, el tramo es
   el clip completo (`--length` igual a su duración).
3. Ajusta el desfase sub-segundo a 60 fps: un segundo de resolución deja
   hasta medio segundo de error, que con cámara en movimiento es otra escena.
4. Extrae el mismo frame de cada video en posiciones normalizadas.
5. Calcula por frame:
   - **PSNR y SSIM** contra la referencia nativa, sobre el frame completo y
     sobre el crop. El crop es una zona estática y evita pagar el movimiento
     de peatones y vehículos, que no cae igual entre corridas.
   - **Nitidez**: varianza del Laplaciano sobre luma. Es la forma de
     convertir "vaselina" en un número; un upscaler borroso da mucho menos
     que el nativo.
5. Genera crops lado a lado (`crop_*.png`) con etiqueta, al doble de tamaño.
6. Escribe `report.md` con la tabla.

## Cómo leerlo

- La nitidez alta no es automáticamente mejor: oversharpening también sube
  el Laplaciano. Se lee junto con PSNR/SSIM, no en lugar de ellos.
- PSNR y SSIM contra el nativo bajan si el upscaler agrega detalle que el
  nativo no tiene, aunque se vea mejor. Sirven para comparar entre sí a los
  upscalers, no como veredicto absoluto.
- Los crops son la evidencia que convence: texto, barandillas, rejas y
  superficies con detalle fino a 200 %.
- Una sola escena no generaliza. Si se quiere afirmar algo más fuerte,
  repetir con otra zona del bench y otro preset.

## Límites

- Grabar en lossless cuesta rendimiento. Las corridas grabadas midieron 41,7
  (nativa), 35,7 (XeSS), 36,7 (FSR) y 28,4 (Lite) fps promedio, contra 54-55
  sin grabar. Los videos sirven para calidad; el rendimiento se mide en
  corridas sin grabación.
- El contador del juego dice 64,2 s, pero el tramo del bench en la grabación
  dura ~69 s de reloj por tirones y carga. Para recortarlo, el inicio es el
  primer frame con imagen después del hueco negro previo y el fin es el corte
  a la pantalla de resultados, no 64,2 s desde un offset.
- El render nativo no es ground truth absoluto: tiene su propio TAA con
  ghosting. Es la referencia práctica disponible sin hardware AMD.
- El video pasa por la composición del compositor; no es el framebuffer
  crudo. Para eso haría falta RenderDoc, que es otra herramienta y otro
  objetivo.
- La alineación es por segundo; diferencias de un frame en la animación
  agregan ruido a PSNR.
