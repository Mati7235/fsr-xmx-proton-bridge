# Próxima prueba manual: imagen y sampler

**Preparación terminada:** [comando manual y riesgos](manual-image-test.md).
Se usa `build/image-test-v01` con el candidato corregido `image-probe-v16`.
No se ejecutó GPU durante este desarrollo; falta la evidencia de la prueba manual.

El primer probe validó DPAS y un heap de buffers. El siguiente ejercita una
imagen muestreada y un sampler antes de intentar el PRE real. Es una prueba
sintética propia: no ejecuta código de la DLL ni demuestra FSR completo.

## Contrato común

`tools/image_probe_reference.py` es la fuente de datos y del resultado CPU:

- Imagen 2x2, `R32G32B32A32_SFLOAT`, un mip, cuatro canales distintos.
- Texels por filas: `(1,2,3,4)`, `(5,6,7,8)`, `(9,10,11,12)`, `(13,14,15,16)`.
- Dieciséis coordenadas normalizadas: centros de texel, centro de imagen y
  posiciones fuera de borde para comprobar linear/clamp-to-edge.
- Resultado: 64 float32 en orden canal*16+lane; tolerancia absoluta `1e-5`.
- La muestra central debe dar `(7,8,9,10)`; distingue interpolación de nearest.
- El kernel CM tiene una imagen, un buffer de salida y sampler de índice cero.
- Heap explícito mutable set 0/binding 0 con 16 descriptores; imagen slot 3,
  salida slot 7. CMK3 base push 4, tamaño total 52. No inferir el heap por cola.
- Placeholder `(2,1,5)` separado del probe anterior `(1,1,5)`; canary `(1,1,17)`.

El builder y el harness deben usar esos mismos datos, no derivar cada uno su
propia respuesta de una interpretación distinta de las coordenadas. El código
CPU calcula la interpolación bilineal con centros en `(i+.5)/dimensión` y clamps
por texel; no llama a Vulkan. Sus cinco pruebas cubren centros, media, bordes,
orden de canales y entradas inválidas.

El harness debe capturar además `image-readback.bin`: los dieciséis buffers de
128 words cada uno, en orden de slot, little-endian (8.192 bytes).
`tools/review_image_result.py` vuelve a comprobar esos bytes en CPU de forma
independiente del comparador C: 64 float32 contra la referencia, NaN rechazados,
y los 1.984 words centinela restantes intactos. Exige además identidad de los
artefactos preparados y evidencia de canary, inyección, layout y mapa en logs.
Sus pruebas usan bytes sintéticos; no representan una ejecución GPU.

## Criterio para dejar el candidato manual

1. Compilación CPU del CM con instrucción de muestreo real, BTIs y sampler
   confirmados por zebin/disassembly; no reemplazar muestras por constantes.
2. Auditoría propia del payload; no transferir la conclusión del PRE o del
   primer probe a un binario nuevo sin comprobarlo.
3. Harness compilado con warnings como errores: upload, layouts y barreras de
   imagen, sampler compatible, buffers centinela y readback comparado con la
   referencia. No ejecutar el harness durante la preparación.
4. Preparación con ICD local, hashes completos, directorios nuevos y opt-in
   manual, igual que el probe anterior. Mantener canary y evidencia de inyección.
5. Dejar un comando concreto para el usuario solo cuando esos pasos pasen. El
   experimento puede fallar en GPU; no presentar compilación como éxito runtime.

El PRE real requiere además conocer el contrato de sus buffers, dimensiones,
formatos y criterio de corrección. Se investiga en paralelo: no se lo despacha
con recursos arbitrarios ni se considera correcta una salida por no colgarse.

## Forma de trabajo

Continuar automáticamente con investigación estática, desarrollo, compilación,
pruebas CPU y preparación de candidatos. No cerrar cada hito como si hiciera
falta otra indicación. Los experimentos GPU se dejan al usuario con comando y
riesgos explícitos; no modificar Steam, drivers instalados ni prefijos reales.
