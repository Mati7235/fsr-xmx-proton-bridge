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
./run-full-test.sh manual ref-native --game cyberpunk --upscaler keep --record --proton-log
./run-full-test.sh manual cp-xess     --game cyberpunk --upscaler xess --record --proton-log
./run-full-test.sh int8  cp-int8      --game cyberpunk --record --proton-log
```

- `ref-native`: en el juego, upscaling **Off** (TAA nativo).
- `cp-xess`: XeSS.
- `cp-int8`: FSR 4.1.2.
- Cada corrida deja `bench.mkv` en su carpeta de resultados.

Parámetros de grabación: `libx264rgb`, `crf=0` (lossless, `Avg QP 0.00`),
4:4:4, 1920x1080, 60 fps, MKV. Nada de AV1 ni de 4:2:0: destruyen la
crominancia justo donde se nota la diferencia.

Condiciones: misma resolución, mismo preset, mismas opciones gráficas, y
correr el bench completo en las tres.

## Análisis

```bash
python3 tools/bench_quality.py report \
  --ref results/ref-native-*/bench.mkv \
  --alt "XeSS=results/cp-xess-*/bench.mkv" \
  --alt "FSR 4.1.2=results/cp-int8-*/bench.mkv" \
  --out analysis/quality-cp77 \
  --crop 760,400,400,225
```

Qué hace:

1. Saca miniaturas a 1 fps de cada video y alinea cada una contra la
   referencia por correlación de contenido (el bench tiene cámara fija, así
   que el offset es estable).
2. Detecta la ventana común de gameplay, ignorando menús y carga.
3. Extrae el mismo frame de cada video en posiciones normalizadas.
4. Calcula por frame:
   - **PSNR y SSIM** contra la referencia nativa.
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

- El render nativo no es ground truth absoluto: tiene su propio TAA con
  ghosting. Es la referencia práctica disponible sin hardware AMD.
- El video pasa por la composición del compositor; no es el framebuffer
  crudo. Para eso haría falta RenderDoc, que es otra herramienta y otro
  objetivo.
- La alineación es por segundo; diferencias de un frame en la animación
  agregan ruido a PSNR.
