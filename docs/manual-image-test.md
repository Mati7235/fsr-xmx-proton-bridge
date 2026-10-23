# Segunda prueba manual: imagen y sampler

**Preparada, todavía no ejecutada en GPU.** Comprueba el muestreo real de una
textura 2x2 con filtrado lineal y bordes clamp. Es un kernel propio, no el PRE ni
FSR completo. No usa Cyberpunk, OptiScaler ni Proton.

Guardá tu trabajo y cerrá juegos/cargas GPU: un fallo puede colgar la GPU o la
sesión. El timeout no garantiza recuperación. No uses `sudo`.

## Ejecutar en este equipo

```bash
python3 /home/matias/Proyectos/fsr-xmx-proton-bridge/build/image-test-v01/run-manual.py --run-gpu
```

El flag autoriza esa ejecución manual concreta. Sin él se rechaza el lanzamiento.
El agente no ejecutó el harness ni GPU durante la preparación.

Antes de invocar el harness se verifican hashes de driver, ICD, harness, kernel,
marcadores, auditoría y referencia CPU. Se crea un HOME/caché nuevo por ejecución
y se usa solo el ICD local. No se instalan drivers ni se alteran Steam o prefijos
existentes. Se reserva un directorio `WINEPREFIX` nuevo sin inicializar Wine; el
harness es nativo. No hay aislamiento de hardware respecto del escritorio.

## Qué debe comprobar

- PCI `8086:e20b`, extensión de descriptores mutables y soporte de RGBA32F lineal.
- Canary del driver adaptado y ausencia de cambios en los demás words.
- Inyección CM y layout DIRECT antes del despacho del kernel objetivo.
- 64 valores float32 de la imagen contra la referencia CPU, incluidos centros,
  interpolación y bordes; tolerancia absoluta `1e-5`, NaN rechazados.
- Los otros 1.984 words de buffers permanecen centinela, incluida la cola de salida.

La preparación v16 corrige orden SPIR-V, firma de muestreo, orden de canales,
índices de heap y bandera de sampler del paquete. No usar los intentos v01–v15.
La auditoría estática es restringida y no sustituye este experimento.

Si pasa, el harness imprime:

```text
Image probe passed canary, injection/layout gates, all 64 oracle samples, and sentinel checks.
```

El lanzador imprime además el código de salida y la ruta de la ejecución bajo
`build/image-test-v01/runs/`. Mandame esa salida y la ruta, tanto si pasa como si
falla. No hace falta pegar el contenido binario en el chat.

## Evidencia e inspección CPU independiente

En `runs/ID-DE-EJECUCION/evidence/` quedan canary, selección ICD, logs de inyección
y despacho, `image-readback.txt` y **`image-readback.bin`**. Este último contiene
los 16 buffers completos (8.192 bytes), no solo un reporte de que coincidieron.
Permite volver a comprobar los valores sin ejecutar GPU ni confiar únicamente en
el comparador C.

Desde la raíz del repositorio, opcionalmente:

```bash
python3 tools/review_image_result.py \
  --manifest build/image-test-v01/manifest.json \
  --evidence-dir "build/image-test-v01/runs/ID-DE-EJECUCION/evidence"
```

Reemplazá `ID-DE-EJECUCION` por la ruta que imprimió el lanzador. El revisor exige
también logs de canary/inyección/mapa y los hashes actuales de la preparación.
Un readback correcto sin esa evidencia no se acepta como prueba de esta ruta.
No borres controles ni pases a Cyberpunk para esquivar un fallo.

## Regenerar solo la preparación

Si cambian archivos o recompilás, desde la raíz:

```bash
python3 tools/prepare_image_test.py --probe-dir build/image-probe-v16
```

Esto solo regenera auditoría, compara el paquete CMK3 completo y prepara nuevos
ICD/manifiesto/lanzador. No ejecuta el C ni Vulkan. Imprime un comando manual
para el directorio nuevo; nunca sobrescribe una preparación anterior.
