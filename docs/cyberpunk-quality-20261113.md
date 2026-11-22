# Image quality: FSR 4.1.2 XMX vs XeSS and native

Comparison on the built-in Cyberpunk 2077 benchmark, with lossless recordings
and metrics computed against the native render. Date: 2026-11-13.

## Conditions

- 1920x1080, Custom preset, RT local shadows, same bench area.
- Lossless H.264 4:4:4 RGB recording (`gbrp`, full range), 60 fps, with
  `wf-recorder`.
- Native reference: upscaling Off in the game and `--native` in the launcher
  (no OptiScaler or mod DLL). The game summary marks
  `upscalingType=0` and `FSR4=False`.
- XeSS 2.0.1 via OptiScaler (`injected: 0` in the mod log).
- FSR 4.1.2 INT8 and Lite via the mod, with `Xe2 SIMD16-DPAS` kernels.
- The recorded runs measured 41.7 (native), 35.7 (XeSS), 36.7 (FSR
  INT8) and 28.4 (Lite) fps. They are slower than the unrecorded runs
  (54-55 fps), so these videos are not useful for comparing performance.

## Clips

Each clip starts at the first frame with an image after the black loading
gap and ends just before the results panel.

| Clip | Start in source | End | Duration | Size |
|---|---:|---:|---:|---:|
| `ref-native.mkv` | 78.768 s | 148.132 s | 69.37 s | 6.4 GB |
| `xess.mkv` | 79.883 s | 149.200 s | 69.32 s | 5.6 GB |
| `fsr4-int8.mkv` | 64.800 s | 134.117 s | 69.32 s | 5.7 GB |
| `fsr4-lite.mkv` | 80.367 s | 149.833 s | 69.47 s | 4.3 GB |

The H.264 4:2:0 MP4s for comparison are versioned in
`media/quality-cp77/`. The lossless clips (4:4:4) and the full-resolution
frames stay in `analysis/quality-cp77/`, outside Git due to their size.

## Metrics

Fixed crop of 400x225 at (760,100); depending on the position it falls on the
grille, the buildings or the "03" tower. PSNR and SSIM against the native
reference; higher is more similar to native.

| Position | t (s) | Sample | PSNR full | SSIM full | PSNR crop | SSIM crop | Sharpness |
|---|---:|---|---:|---:|---:|---:|---:|
| 0.20 | 13.8 | native | - | - | - | - | 491.9 |
| 0.20 | 13.8 | XeSS | 25.73 | 0.8286 | 27.86 | 0.7135 | 525.2 |
| 0.20 | 13.8 | FSR INT8 | 22.98 | 0.7302 | 24.01 | 0.5985 | 544.6 |
| 0.20 | 13.8 | FSR Lite | 24.91 | 0.8038 | 25.11 | 0.5684 | 538.4 |
| 0.50 | 34.5 | native | - | - | - | - | 535.3 |
| 0.50 | 34.5 | XeSS | 22.51 | 0.8847 | 19.51 | 0.7857 | 561.5 |
| 0.50 | 34.5 | FSR INT8 | 23.66 | 0.9100 | 20.85 | 0.8499 | 580.1 |
| 0.50 | 34.5 | FSR Lite | 24.04 | 0.9144 | 20.10 | 0.8788 | 606.6 |
| 0.80 | 55.2 | native | - | - | - | - | 581.6 |
| 0.80 | 55.2 | XeSS | 17.15 | 0.7780 | 18.82 | 0.9168 | 677.3 |
| 0.80 | 55.2 | FSR INT8 | 17.66 | 0.7865 | 17.07 | 0.8730 | 638.1 |
| 0.80 | 55.2 | FSR Lite | 18.61 | 0.8302 | 21.19 | 0.9519 | 694.6 |

Sharpness = variance of the Laplacian over luma, full frame. The crops
are in `analysis/quality-cp77/report/crop_*.png`.

## Reading

- Sharpness: all three variants beat native in Laplacian variance.
  That confirms they add high-frequency detail, not that they look better:
  oversharpening also raises the number.
- In the dark scene (0.20) XeSS has the best PSNR and SSIM. At 0.50 INT8
  wins on PSNR and Lite on SSIM. At 0.80 Lite wins on both.
- Lite is not a disposable version of INT8: it uses 6 kernels instead of 14,
  and in two of the three scenes it gives higher SSIM and more sharpness.
- The order is not stable: XeSS wins the dark scene, Lite wins SSIM in the
  daytime scenes, and INT8 sits in the middle. None wins across the whole run.
- Full-frame PSNR includes pedestrians and vehicles that do not fall in the
  same position between runs. So a low number does not mean the upscaler is
  broken: the useful measure is the static crop.

## Limits

- One run per variant. To claim something stronger, repeat in another area
  of the bench and with another preset.
- The reference is the game's TAA, not an absolute ground truth.
- The capture goes through the compositor and the conversion to 60 fps, so it
  adds differences that do not come from the upscaler.
- The game counter says 64.2 s; the recorded segment lasts ~69 s of wall
  clock due to stutters and loading.

## Reproduce

```bash
mpv media/quality-cp77/ref-native.mp4
```

The 2x2 grid of the four, with the same 400x225 crop at double size, is in
`analysis/quality-cp77/compare-crop.mp4` (local): native, XeSS, FSR INT8 and
FSR Lite.
