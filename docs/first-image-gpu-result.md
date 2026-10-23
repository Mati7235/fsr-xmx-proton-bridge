# Primer resultado GPU de imagen/sampler — 2026-10-23

**Resultado positivo del kernel sintético de imagen/sampler en B580.** El usuario
ejecutó manualmente `build/image-test-v01/run-manual.py --run-gpu`; reportó PCI
`8086:e20b`, comprobaciones del harness aprobadas y código de salida 0.

La revisión posterior solo leyó los archivos de esta ejecución:

`build/image-test-v01/runs/20261023-005649-3b96a43b/evidence/`

No se lanzó otra prueba GPU. Se usó `tools/review_image_result.py` con el
manifiesto preparado: verifica hashes actuales, canary, log de inyección/mapa y
el volcado binario **independientemente del comparador C**.

## Resultado comprobado

- Los 64 float32 muestreados coinciden con la referencia CPU: **error absoluto
  máximo 0.0**. Incluye cuatro canales, centros de texel, interpolación central y
  coordenadas fuera del borde con clamp-to-edge.
- Los otros **1.984 words centinela** siguen intactos, incluida la cola del buffer
  de salida y los buffers no usados. El volcado tiene los 8.192 bytes esperados.
- Canary reconocido; su reporte confirma marcador y demás words intactos.
- Log: heap DIRECT (tipo 2), set 0/binding 0, offset 0/stride 64; sampler en el
  segundo set del pipeline. Inyección de **1.280 bytes**, 128 GRF, CM LWS `(1,1,1)`.
- Dispatch del selector `(2,1,5)` con índices `3 7`; walker con un grupo y un
  thread. Son logs del driver, no captura directa de registros de hardware.

Los hashes de los archivos actuales coinciden con la preparación. El kernel
fijado contiene `sample_lz` nativo, máscara RGBA y escritura de los resultados;
el paquete CMK3 habilita el sampler. No basta solo con crear el pipeline ni con
un código de salida exitoso: aquí existe evidencia de inyección y bytes de salida.

| Evidencia | SHA-256 |
|---|---|
| `probe-driver.log` | `1ae5b571518c8131ef46247e82a040ec26b020c59a9051bf3fd16665f44756ca` |
| `image-readback.bin` | `f84be4a8d77b9951b64a80b2235b78a85f4124f64d0e1db6bbe1f571d13c8b77` |
| `image-readback.txt` | `0b8ab6c95995d6d04059a3ea742a14c6a1959b277c2f399089dc5c223a11de13` |

Reportes locales: `analysis/image-gpu-result-20261023-005649.json` y
`analysis/image-gpu-evidence-hashes-20261023-005649.json`. No se modificaron el
spec ni el manifiesto de preparación para marcar éxito: sus estados offline
identifican la procedencia del artefacto; este resultado se registra aparte.

## Alcance y continuación

Quedan comprobados una imagen sampled RGBA32F 2x2, un mip, sampler inmutable
linear/clamp y el heap mutable del microtest. No prueba otros formatos, imágenes
writable, el sampler dinámico del mod ni repetibilidad en múltiples ejecuciones.
Tampoco valida el PRE real, FSR completo, Proton u OptiScaler/Cyberpunk.

La continuación es reconstruir formatos, tamaños y contenido de los recursos PRE
desde el host y cubrir la devolución de información del contexto del shim. No se
despacha PRE con recursos arbitrarios ni se infiere permiso para nuevas pruebas
GPU por cuenta del agente.
