# Cyberpunk 2077 benchmark: XeSS vs FSR 4.1.2 XMX (2026-11-13)

First performance comparison between the XeSS path and FSR 4 on XMX, on the same machine,
same scene and same settings.

## Conditions

- GPU: Intel Arc B580 (BMG G21), 12216 MB.
- CPU: Ryzen 5 5600X. 16 GB of RAM.
- Game: Cyberpunk 2077 2.5, built-in benchmark (`benchmark.gamedef`).
- 1920x1080, Custom preset (High textures), vsync off, no FPS cap.
- Disposable prefix `compatdata-cp77`, driver from the candidate package
  `xess-xmx-linux-20261113-cmk3`.
- The results come from
  `.../Documents/CD Projekt Red/Cyberpunk 2077/benchmarkResults/*/summary.json`.

## Results

| Run | Upscaler | avg FPS | min FPS | max FPS |
|---|---|---:|---:|---:|
| `cp-xess` | XeSS | 54.44 | 43.85 | 69.65 |
| `cp-int8` | FSR 4.1.2 Full (INT8) | 54.54 | 43.50 | 70.09 |
| `cp-lite` | FSR 4.1.2 Lite | 55.56 | 44.87 | 70.78 |
| `cp1` (previous run) | FSR 4.1.2 Full (INT8) | 54.56 | 43.95 | 69.85 |

Differences from the average:

- Full vs XeSS: +0.18 %, within noise.
- Lite vs XeSS: +2.06 %.
- Lite vs Full: +1.87 %.

Repeatability: two independent runs of the same Full model gave
54.54 and 54.56 FPS (+0.04 %). That is the baseline for judging the differences
above: Lite's +2 % is above the noise, Full's +0.18 % is not.

## Which model actually ran

From the mod's log (`steam-0.log`, captured with `PROTON_LOG=1` and
`WINEDEBUG=+debugstr`):

- Full: `INT8 model: preset weights from fsr-original.dll, bucket 0, Xe2
  SIMD16-DPAS kernels`, plus `INT8 network kernels ready (bucket 0, preset
  weights)`.
- Lite: `Lite model: ...`, with no INT8 lines.
- XeSS: no model line from the mod.

On the driver side, the sets of injected kernels differ:

- Full: 28 injections, 14 unique kernels.
- Lite: 12 injections, 6 unique kernels.
- Intersection: only 1 kernel (the 30400 B sampling kernel).

That confirms Lite runs a different and smaller network, not an alias of Full.

## Reading

It matches what `xess-xmx-linux` found: FSR 4 on XMX does not gain performance over XeSS;
on Full it is statistically tied. Lite's advantage is real but small (+2 %).

The value of FSR 4 on this machine is not performance but image: at the same cost as XeSS
you get a noticeably sharper reconstruction.

## Limits

- One benchmark scene and one resolution.
- Custom preset; other presets and RT were not tested.
- There is no quality oracle: PSNR/SSIM against a reference was not measured.
- The `summary.json` reports `gpuDriverVersion: Radeon software 99.10.2`,
  which is the mod's spoofing, not the real driver (Mesa ANV).
- The runs used the same prefix, so the shader cache state is comparable but not
  identical between the first and the last run.
