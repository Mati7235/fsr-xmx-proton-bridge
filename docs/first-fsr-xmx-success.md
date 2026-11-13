# Primer FSR 4 sobre XMX funcional en Linux (2026-11-13)

**Resultado funcional en el juego, no solo inyección.** Marvel's Spider-Man
Remastered renderiza la escena correctamente con el mod XMX 4.1.2, el shim y
un driver ANV propio, sobre una Intel Arc B580. La UI y el mundo 3D son
coherentes; el upscaler reporta ~0.99 ms.

Sigue sin ser una validación bit-exacta de FSR: no hay oracle independiente ni
readback determinista del PRE. Es el primer resultado visual/funcional
correcto del proyecto.

## Setup exacto

- Paquete candidato `xess-xmx-linux-20261113-cmk3` (side-by-side, sin instalar
  en el sistema): Mesa 26.3.0 + serie del fork `662dc6e` + shim 861.184 B.
- Driver usado solo por proceso: `VK_DRIVER_FILES` al ICD del candidato,
  `ANV_CM_HELPER` nuevo, `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer`,
  `ANV_CM_DEBUG=1`, `WINEDLLOVERRIDES="cabinet=n,b"`.
- Prefijo descartable del run de traza (saves del usuario copiados), Proton
  Experimental, mod `fadbcb50…`, OptiScaler `Dx12Upscaler = ffx`.
- Comando: `runs/20261112-161210-c1561db6/run-candidate.sh`.

## Evidencia

| Artefacto | Valor |
|---|---|
| Log | `evidence/vkd3d-trace3-20261113.log`, 19.523 líneas |
| SHA-256 | `012ac930a7369d9723234b4e84a9d68aaa6dba7e1827bd72578da3d368c1d957` |
| PRE | `~/.cache/xess-xmx/kernels/e8fca351200197b3_e20b_142835e7.cmk` (CMK2, 30.936 B) |
| Línea clave | `ANV CM: …e8fca351200197b3_e20b_142835e7.cmk: sampler descriptor table after the surfaces (sampler heap found)` |
| Recursos FSR4 detectados | 11 líneas `FSR4 resource detected` |
| Device lost | 0 |

El PRE se compiló con el helper nuevo (gen `142835e7`, distinto de `0913d3f4`
del paquete viejo) y el driver nuevo aplicó la ruta de sampler de tabla:
`table_pc_base = push_size - 4*(nsurf+1) = 52 - 48 = 4` y
`cm_sampler_pc_off = 48`.

## Qué cerró el problema

1. La magia CMK estaba invertida en el parche 0001 heredado: el driver habría
   rechazado todos los kernels. Corregida y con test semántico.
2. El paquete instalado era viejo (`0913d3f4`) y no tenía el soporte de sampler
   de tabla del fork (`0005`), que es lo que corrige el desfase de base
   (8 → 4) y el offset del sampler. La traza anterior con ruido magenta era
   coherente con ese driver, no con una ABI rota del PRE.
3. Los packs del mod 4.1.2 necesitan `Cabinet.dll` (Compression API LZMS), que
   Wine no implementa; el shim juego-local lo aporta.

## Qué no prueba

- Exactitud matemática de FSR ni equivalencia con la implementación de
  referencia (falta oracle).
- Formatos/contenidos reales de las 8 imágenes (falta captura RenderDoc).
- Que el paquete funcione instalado system-wide o en otros juegos/prefijos.
- Repetibilidad entre ejecuciones (una sola sesión).

## Siguiente

Instalación system-wide del paquete candidato (decisión del usuario; rollback
en `backup-20261113`), y después captura RenderDoc para formatos + oracle.
