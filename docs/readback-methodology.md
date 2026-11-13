# Metodología de readback: qué prueba cada comparación y qué no

Herramienta: `tools/fsr_readback_compare.py` (solo CPU, solo biblioteca
estándar con ruta rápida opcional en numpy). Esta nota define cómo leer sus
resultados cuando tengamos capturas RenderDoc de FSR 4 XMX. No usa em dashes.

## 1. Determinismo bit a bit entre dos corridas (`diff` sin tolerancia)

Qué prueba: repetibilidad. Dos capturas con las mismas entradas, mismo
driver, mismos pesos y misma resolución deben producir bytes idénticos.
`diff a.bin b.bin` sale con 0 e `identical: True` solo si los archivos son
bit a bit iguales.

Qué no prueba: corrección. Un upscaler puede ser perfectamente determinista
y aun así producir una imagen incorrecta (pesos equivocados, LUT corrupta,
desplazamiento de UV constante). Determinismo es condición necesaria para
depurar, no evidencia de calidad.

Notas de lectura:

- `--tolerance ABS` separa dos preguntas distintas: "difiere en bits" de
  "difiere más allá de una tolerancia". Con tolerancia, la salida 0
  significa acuerdo dentro del umbral aunque haya bits distintos (por
  ejemplo tras reconversión de formato). Sin tolerancia, cualquier bit
  distinto da salida 1.
- `-0.0` contra `0.0` difiere en bits pero tiene error absoluto 0; la
  herramienta lo reporta como diferencia de bits dentro de tolerancia 0.
- NaN contra cualquier valor (incluso otro NaN con distinto payload) cuenta
  como diferencia con error infinito. Dos corridas deterministas nunca
  deberían producir NaN divergentes; si aparecen, el problema está antes
  (ver `inspect`).

## 2. Plausibilidad de calidad contra una referencia (`metrics`)

Qué prueba: plausibilidad. `metrics candidato.bin referencia.bin` calcula
PSNR y SSIM por canal y en luminancia. La referencia aquí es un upscaling de
comparación disponible en Linux (XeSS o TAAU nativo), no AMD. Un PSNR alto y
un SSIM cercano a 1 indican que el candidato reconstruye detalle de forma
similar a un upscaler razonable.

Qué no prueba: equivalencia con AMD. Ningún umbral de PSNR/SSIM contra XeSS
demuestra que FSR 4 XMX sea correcto, porque no tenemos su salida en
hardware AMD para comparar. Solo descarta fallos gruesos (pantalla plana,
ruido, resolución a la mitad, canales permutados).

Decisiones de diseño relevantes:

- Pico de señal: por defecto 1.0 para formatos float y 255.0 para formatos
  de 8 bits; se puede forzar con `--peak`. El PSNR siempre se reporta junto
  al MSE para que el número sea reinterpretable con otro pico.
- SSIM: media sobre ventanas box de 8x8 sin solapamiento (los bordes usan
  ventanas parciales), con K1=0.01, K2=0.03 y L igual al pico. Se eligió
  box 8x8 en lugar de gaussiana 11x11 porque es exacta con memoria O(1) en
  Python puro; la gaussiana 11x11 con solape exigiría convoluciones que en
  stdlib puro tardarían minutos a 1080p. La ventana usada queda impresa en
  cada corrida (`ssim_window:`).
- Luminancia: Rec.709 (0.2126 R + 0.7152 G + 0.0722 B) para RGB/RGBA; para
  formatos de 1 o 2 canales se usa el primer canal. El alfa se reporta por
  canal pero nunca entra en la luminancia: un alfa roto no debe hundir la
  métrica de calidad de imagen, y un alfa idéntico no debe inflarla.
- NaN/Inf hacen fallar `metrics` con salida 2 y mensaje explícito. PSNR y
  SSIM no están definidos con no finitos, y promediarlos los ocultaría; el
  flujo correcto es `inspect` primero, `metrics` después.

## 3. Por qué no hay oracle bit-exacto de FSR 4 sin hardware AMD

Un oracle bit-exacto exigiría reproducir la misma aritmética que el
hardware: mismo orden de operaciones en cada reducción, mismo redondeo de
cada instrucción matricial XMX, mismos pesos cuantizados y mismo
microcódigo de driver. Nada de eso es público para FSR 4, y la red neuronal
solo existe como binarios para Windows sobre XMX. En una GPU distinta
(RDNA, NVIDIA, Intel iGPU) las instrucciones equivalentes reordenan y
redondean distinto, así que ni siquiera una reimplementación perfecta del
algoritmo daría bytes iguales.

Qué haría falta para tenerlo: una captura de salida de referencia generada
en hardware AMD real con entradas fijas (el par entrada/salida como
vectores de test), o la publicación por parte de AMD de vectores de
referencia. Con eso, `diff` con tolerancia 0 contra el oracle sería la
prueba de equivalencia; sin eso, el techo probatorio es el punto 2.

## 4. Cómo se combina con la evidencia de inyección existente

El criterio de éxito del proyecto sigue siendo conjuntivo. Cada pata
descarta una clase distinta de falso positivo:

1. Inyección (`review_image_result.py` y evidencias de driver): prueba que
   nuestro código corrió en el dispatch correcto y que la salida cruda del
   buffer coincide con el contrato sintético. No dice nada de calidad
   visual.
2. Determinismo (`diff`): prueba que el upscaler es repetible entre
   corridas. Sin esto, cualquier métrica de calidad es ruido.
3. Plausibilidad (`metrics` contra XeSS o TAAU): prueba que la imagen
   reconstruida se parece a un upscaling razonable. Sin esto, un pipeline
   determinista pero visualmente roto pasaría.
4. Ojo humano sobre recortes: ninguna métrica sustituye mirar bordes,
   texto y zonas de alta frecuencia, donde PSNR/SSIM globales promedian y
   esconden artefactos locales.

Ninguna de estas patas por separado, ni siquiera las cuatro juntas, prueba
equivalencia con FSR 4 en hardware AMD. Prueban que el puente hace un
upscaling repetible y visualmente plausible bajo control del test.
