# ANR FG en Arc B580 bajo Proton

Fecha: 2026-11-22. Apex Neural Rendering FG `FG-V.B20` como proveedor
`FGNvngxReplacement` de OptiScaler `v10.0.0-dev (b49770e)` en Cyberpunk 2077,
prefijo descartable, 1920x1080, SDR, 2X (`max_generated = 1`). Fuente: los
`nr_fg-*.log` de ANR (`OptiScaler/custom/Apex Neural Rendering FG/dlssg/`).

## Por qué ANR no usaba XMX

vkd3d-proton crea el `VkDevice` que ANR comparte. Su gate
`vkd3d_supports_minimum_coopmat_caps()` exige 16x16x16 f16 y FP8; ANV Xe2
solo expone 8x16x16, así que vkd3d quita `VK_KHR_cooperative_matrix` del
dispositivo. ANR lo registra como
`VK_KHR_cooperative_matrix off` y cae a programas `portable*`.

`patches/0005-vkd3d-keep-coopmat-extension.patch` (opt-in
`VKD3D_KEEP_COOPMAT_EXTENSION=1`) mantiene la extensión en el dispositivo sin
exponer WMMA a D3D12.

## Resultados

Medianas de GPU que reporta ANR (ms), misma red (`fg-lite-occlusion-v1`,
checkpoint `b7481951…`), primeras ventanas de cada corrida:

| Corrida | vkd3d | Programa | pair | phase | out | Total |
|---|---|---|---:|---:|---:|---:|
| 12:42 | Proton Experimental stock | `portable` | 1,846 | 1,432 | 0,039 | ~3,3 |
| 12:52 | Proton Experimental stock | `portable-xmx` | 1,006 | 0,607 | 0,371 | ~2,0 |
| 13:53 | GE-Proton11-12 + 0005 | `coopmat` | 0,857 | 0,500 | 0,369 | ~1,7 |

- La corrida 13:53 registra `VK_KHR_cooperative_matrix on` y el orden de
  caminos `coopmat, portable-xmx, portable`; 2400 evaluaciones generadas, 0
  errores.
- Las escenas no son idénticas entre corridas: los totales son orientativos,
  no un benchmark.
- El salto 2X→6X de la primera corrida venía del juego (Dynamic MFG de
  Cyberpunk 2.5, `multi-frame count N from evaluate`); `max_generated = 1`
  lo fija en 2X.

## Pendiente

- Probar que `coopmat` ejecuta `dpas` en ANV (dump del ISA compilado), no
  solo que la extensión está habilitada.
- Calidad de imagen: el usuario reporta resultado mediocre en la primera
  prueba; falta comparación con capturas.
