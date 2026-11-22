# ANR FG on Arc B580 under Proton

Date: 2026-11-22. Apex Neural Rendering FG `FG-V.B20` as the
`FGNvngxReplacement` provider of OptiScaler `v10.0.0-dev (b49770e)` in Cyberpunk 2077,
disposable prefix, 1920x1080, SDR, 2X (`max_generated = 1`). Source: the
`nr_fg-*.log` files of ANR (`OptiScaler/custom/Apex Neural Rendering FG/dlssg/`).

## Why ANR was not using XMX

vkd3d-proton creates the `VkDevice` that ANR shares. Its gate
`vkd3d_supports_minimum_coopmat_caps()` requires 16x16x16 f16 and FP8; ANV Xe2
only exposes 8x16x16, so vkd3d removes `VK_KHR_cooperative_matrix` from the
device. ANR logs it as `VK_KHR_cooperative_matrix off` and falls back to
`portable*` programs.

`patches/0005-vkd3d-keep-coopmat-extension.patch` (opt-in
`VKD3D_KEEP_COOPMAT_EXTENSION=1`) keeps the extension on the device without
exposing WMMA to D3D12.

## Results

Median GPU times reported by ANR (ms), same network (`fg-lite-occlusion-v1`,
checkpoint `b7481951…`), first windows of each run:

| Run | vkd3d | Program | pair | phase | out | Total |
|---|---|---|---:|---:|---:|---:|
| 12:42 | Proton Experimental stock | `portable` | 1.846 | 1.432 | 0.039 | ~3.3 |
| 12:52 | Proton Experimental stock | `portable-xmx` | 1.006 | 0.607 | 0.371 | ~2.0 |
| 13:53 | GE-Proton11-12 + 0005 | `coopmat` | 0.857 | 0.500 | 0.369 | ~1.7 |

- The 13:53 run logs `VK_KHR_cooperative_matrix on` and the path order
  `coopmat, portable-xmx, portable`; 2400 generated evaluations, 0 errors.
- The scenes are not identical between runs: the totals are indicative, not a
  benchmark.
- The 2X→6X jump of the first run came from the game (Cyberpunk 2.5 Dynamic MFG,
  `multi-frame count N from evaluate`); `max_generated = 1` pins it to 2X.

## Artifacts with `coopmat`

In the `coopmat` run, black rectangles appear on the road around the cars and
jagged black edges on sidewalks and facades (user screenshot, 1080p, 2X). In the
same places with `portable-xmx` they do not appear. The cause is in the `coopmat`
path on ANV or in the device that `0005` leaves behind (extension and
`cooperativeMatrixRobustBufferAccess` as the driver advertises them); it is not
isolated. Until then `nr_fg.ini` stays at `path = portable-xmx`.

In that run the game ran at about 45 real FPS with `Simulation` 20.9 ms in the
OptiScaler overlay; the user saw 60-70 before. The same scene was not compared
between Proton Experimental and GE-Proton.

## Pending

- Prove that `coopmat` executes `dpas` on ANV (dump of the compiled ISA), not
  just that the extension is enabled.
- Image quality: the user reports a mediocre result on the first test; a
  comparison with captures is still missing.
