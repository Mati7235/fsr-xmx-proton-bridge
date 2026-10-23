# Primer resultado GPU sintético — 2026-10-23

**Resultado positivo del probe sintético DPAS/mapa de recursos en B580. No es
validación de FSR, del kernel PRE real ni de Proton/OptiScaler/Cyberpunk.**

El usuario ejecutó manualmente `build/lab-test-v02/run-manual.py --run-gpu` y
reportó dispositivo `8086:e20b`, salida de éxito del harness y código 0.
La evidencia local está en:

`build/lab-test-v02/runs/20261023-000311-6a2d4eeb/evidence/`

La revisión posterior fue únicamente lectura y comprobaciones CPU: no se volvió
a ejecutar GPU. Los hashes actuales de los artefactos coinciden con el manifiesto
de preparación; el lanzador comprueba esos hashes antes de invocar el harness.

## Evidencia revisada

- `anv_canary`: el ANV adaptado reconoció el placeholder de control.
- `canary-evidence.txt`: marcador correcto y todos los demás words intactos.
- `probe-driver.log`: layout DIRECT (tipo 2), set 0/binding 0, offset 0,
  stride 64; inyección del CMK de 12.160 bytes, 128 GRF y LWS CM `(1,1,1)`.
- El log registra mapa `7 8 0 1 2 3 4 5 6 9 10`, despacho de un grupo y un
  thread. No es una lectura directa de registros GPU ni de su máscara.
- `probe-readback.txt`: el harness comprobó 128 float32 por cada uno de los once
  recursos (**1.408 valores**), cada argumento `i` con resultado `16+i`.
  Los slots 11–15 permanecieron intactos.

El kernel previamente compilado y auditado contiene DPAS nativo. La combinación
de identidad del artefacto, evidencia de inyección y resultados deterministas es
más fuerte que `S_OK`, un marcador o un pipeline creado. Los logs vacíos
`icd-driver.log` y `canary-driver.log` no se usan como prueba; el marcador y el
reporte de canary sí existen. `icd-selection.txt` registra la selección solicitada,
no una inspección independiente de todos los módulos cargados.

## Identidad de los reportes

| Archivo | SHA-256 |
|---|---|
| `probe-driver.log` | `8addac924fad97372113c101edd246bc1511547b06bd5ac25e2b6939434e30d6` |
| `probe-readback.txt` | `b795e00ed04ad4f031c1473340c66843bd896401501f9cba7c906aed891fa1e1` |

Inventario completo local: `analysis/first-gpu-evidence-review.json`. Los reportes
contienen las comprobaciones del harness, no un volcado binario independiente de
los buffers. No se redistribuyen el driver ni otros artefactos binarios.

## Qué queda sin probar

Es una ejecución positiva de un kernel propio con buffers storage y heap
explícito. No demuestra repetibilidad entre ejecuciones, soporte de imágenes o
samplers del PRE, compatibilidad del heap mutable VKD3D, ni las etapas completas
de FSR. El siguiente hito es diseñar un microtest con imágenes/sampler y entradas
controladas para el PRE real, con un criterio de corrección antes de ejecutarlo.
No hay autorización implícita para nuevos experimentos GPU ni para tocar juegos.
