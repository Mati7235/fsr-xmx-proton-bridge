# Benchmarks

Performance and image quality measured on the Intel Arc B580 with the FSR 4.1.2 XMX mod.
Quality runs capture the screen losslessly and compare each capture against the native
render, the only reference available. Each number comes from a single session, so a
difference smaller than the repeatability spread is noise.

## How a benchmark is run

Runs use the Intel Arc B580 (BMG G21, 12216 MB), a Ryzen 5 5600X with 16 GB, and the driver
`xess-xmx-linux-20261113-cmk3`, inside a disposable prefix (`compatdata-cp77` for
Cyberpunk). Cyberpunk 2077 2.5 runs its built-in benchmark (`benchmark.gamedef`) at
1920x1080, Custom preset (High textures), vsync off and no FPS cap, and writes the numbers
to `.../Documents/CD Projekt Red/Cyberpunk 2077/benchmarkResults/*/summary.json`.

### Recording

`wf-recorder` 0.6.0, from the official repos, records the compositor output losslessly. The
launcher starts it and stops it only with `--record`:

```bash
./run-full-test.sh manual ref-native --game cyberpunk --native --record --proton-log
./run-full-test.sh manual cp-xess     --game cyberpunk --upscaler xess --record --proton-log
./run-full-test.sh int8  cp-int8      --game cyberpunk --record --proton-log
```

`ref-native` sets aside `dxgi.dll` (OptiScaler) and the mod DLL, so the game keeps its TAA.
Turning the upscaler off in the menu does not suffice, because Cyberpunk applies FSR in the
benchmark cutscenes even when it is set to Off. `cp-xess` runs XeSS, `cp-int8` runs FSR
4.1.2, and each run leaves `bench.mkv` in its results folder.

The recording uses `libx264rgb`, `crf=0` (lossless, `Avg QP 0.00`), 4:4:4, 1920x1080, 60
fps and MKV. AV1 and 4:2:0 destroy chrominance exactly where the difference shows.

### Trimming the bench

The recordings include desktop, menu, loading and results. Cut the bench segment once in
each video: start at the first frame with an image after the black loading gap, end just
before the cut to the results screen (dark background, "Average FPS" in orange). The
segment lasts about 69 s of wall clock, although the game counter says 64.2 s.

```bash
ffmpeg -v error -y -ss 79.883 -i bench.mkv -t 69.317 \
  -c:v libx264rgb -crf 0 -preset ultrafast -pix_fmt gbrp -an -sn bench-clip.mkv
```

Put `-ss` before `-i` and re-encode, which cuts exactly to the frame. With `-c copy` the cut
falls on the previous keyframe and can be off by up to 4 s. `libx264rgb -crf 0` stays
lossless over RGB.

### Analysis

Point the tool at the trimmed clips, with `--length` equal to the clip duration:

```bash
python3 tools/bench_quality.py report \
  --ref analysis/quality-cp77/clips/ref-native.mkv \
  --alt "XeSS=analysis/quality-cp77/clips/xess.mkv" \
  --alt "FSR 4.1.2=analysis/quality-cp77/clips/fsr4-int8.mkv" \
  --alt "FSR 4.1.2 Lite=analysis/quality-cp77/clips/fsr4-lite.mkv" \
  --out analysis/quality-cp77/report \
  --length 69 \
  --crop 760,100,400,225
```

The clips start at the same bench frame and the camera follows a fixed timeline, so the
same second maps to the same position even when one clip is 60 fps and another is not. At
30 s the optimal offset between XeSS and Lite is 0, and a one-frame shift makes the MSE 2
to 4 times worse. Against native a residual of 2 or 3 frames remains, which the tool
corrects on its own.

`tools/bench_quality.py report` extracts thumbnails at 1 fps, finds the `--length` window
that best matches the reference (the camera path repeats, the menu background does not),
refines the offset to 60 fps, and extracts the same frames at normalized positions. It then
computes PSNR, SSIM and Laplacian sharpness on the full frame and on the static crop, writes
lossless PNG crops (`crop_*.png`) at double size, and writes `report.md` with the table.

The published comparisons are the H.264 4:2:0 MP4s in `media/quality-cp77/`; the lossless
clips stay local and are used only for measuring. High sharpness is not automatically
better, because oversharpening also raises the Laplacian, so read it with PSNR and SSIM.
Those metrics drop when the upscaler adds detail that native lacks, so they compare the
upscalers with each other and are not an absolute verdict. The crops are the convincing
evidence: text, railings, grilles and fine surfaces at 200%. One scene does not generalize;
a stronger claim needs another area and another preset.

## Cyberpunk 2077 performance (2026-11-13)

| Run | Upscaler | Resolution | Preset | avg FPS | min FPS | max FPS |
|---|---|---|---|---:|---:|---:|
| `cp-xess` | XeSS | 1920x1080 | Custom | 54.44 | 43.85 | 69.65 |
| `cp-int8` | FSR 4.1.2 Full (INT8) | 1920x1080 | Custom | 54.54 | 43.50 | 70.09 |
| `cp-lite` | FSR 4.1.2 Lite | 1920x1080 | Custom | 55.56 | 44.87 | 70.78 |
| `cp1` (previous run) | FSR 4.1.2 Full (INT8) | 1920x1080 | Custom | 54.56 | 43.95 | 69.85 |

Against the XeSS average, Full is +0.18 % and Lite is +2.06 %. Lite is +1.87 % over Full.
Two independent runs of Full gave 54.54 and 54.56 FPS (+0.04 %), which sets the noise floor:
Lite's +2 % is above it, Full's +0.18 % is not.

The mod log (`steam-0.log`, captured with `PROTON_LOG=1` and `WINEDEBUG=+debugstr`)
identifies the model. Full prints
`INT8 model: preset weights from fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels` plus
`INT8 network kernels ready (bucket 0, preset weights)`. Lite prints `Lite model: ...` and
no INT8 lines, and XeSS prints no model line from the mod. On the driver side, Full has 28
injections and 14 unique kernels, Lite has 12 injections and 6 unique kernels, and the
intersection is 1 kernel (the 30400 B sampling kernel). Lite runs a different and smaller
network, not an alias of Full.

That matches what `xess-xmx-linux` found: FSR 4 on XMX does not gain performance over XeSS,
and on Full it is statistically tied. Lite's advantage is real but small, and the value of
FSR 4 here is the image, since at the cost of XeSS it gives a sharper reconstruction.

Limits: one benchmark scene, one resolution and the Custom preset; other presets and ray
tracing were not tested, and these runs measured no quality oracle. The `summary.json`
reports `gpuDriverVersion: Radeon software 99.10.2`, the mod's spoofing and not the real
driver (Mesa ANV). All runs shared one prefix, so the shader cache state is comparable but
not identical between the first and the last run.

## Cyberpunk 2077 image quality (2026-11-13)

Conditions: 1920x1080, Custom preset, RT local shadows, same bench area. Lossless H.264
4:4:4 RGB recording (`gbrp`, full range) at 60 fps with `wf-recorder`. The native reference
sets upscaling Off in the game and `--native` in the launcher (no OptiScaler or mod DLL),
and the game summary marks `upscalingType=0` and `FSR4=False`. XeSS 2.0.1 ran through
OptiScaler (`injected: 0` in the mod log). FSR 4.1.2 INT8 and Lite ran through the mod with
`Xe2 SIMD16-DPAS` kernels. The recorded runs measured 41.7 (native), 35.7 (XeSS), 36.7
(FSR INT8) and 28.4 (Lite) fps, below the 54-55 fps of unrecorded runs, so these videos do
not compare performance. Each clip starts at the first frame with an image after the black
loading gap and ends just before the results panel.

| Clip | Start in source | End | Duration | Size |
|---|---:|---:|---:|---:|
| `ref-native.mkv` | 78.768 s | 148.132 s | 69.37 s | 6.4 GB |
| `xess.mkv` | 79.883 s | 149.200 s | 69.32 s | 5.6 GB |
| `fsr4-int8.mkv` | 64.800 s | 134.117 s | 69.32 s | 5.7 GB |
| `fsr4-lite.mkv` | 80.367 s | 149.833 s | 69.47 s | 4.3 GB |

The lossless clips (4:4:4) and the full-resolution frames stay in `analysis/quality-cp77/`,
outside Git due to their size. Metrics use a fixed crop of 400x225 at (760,100), which
falls on the grille, the buildings or the "03" tower depending on the position. PSNR and
SSIM are measured against native, and higher means more similar to native. Sharpness is the
variance of the Laplacian over luma on the full frame.

| Position | t (s) | Upscaler | PSNR full | SSIM full | PSNR crop | SSIM crop | Sharpness |
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

The crops are in `analysis/quality-cp77/report/crop_*.png`. All three variants beat native
in Laplacian variance, so they add high-frequency detail, not necessarily a better image. In
the dark scene (0.20) XeSS has the best PSNR and SSIM; at 0.50 INT8 wins PSNR and Lite SSIM;
at 0.80 Lite wins both. Lite is not a stripped INT8: it uses 6 kernels instead of 14, and in
two of the three scenes it gives higher SSIM and more sharpness. No variant wins the whole
run, and full-frame PSNR includes pedestrians and vehicles that move between runs, so the
static crop is the useful measure.

Limits: one run per variant, so a stronger claim needs another area of the bench and
another preset. The reference is the game's TAA, not an absolute ground truth. The capture
goes through the compositor and the conversion to 60 fps, which adds differences that do
not come from the upscaler.

## SCP: 5K (2026-11-14)

A PvP match rendered with the FSR 4.1.2 XMX mod, OptiScaler and the candidate Mesa driver.
SCP: 5K (UE 4.27.2, D3D12) rendered on the Intel Arc B580, the user confirmed the visual
result, and the local capture shows the correct scene. This is not a bit-exact validation:
there is no independent oracle and no deterministic readback of the PRE.

| Part | Value |
|---|---|
| Game | SCP: 5K (Alpha Testing), appid 872670, build 20928322, version `0.17.6.1` |
| Executable | `~/Juegos/steamapps/common/5K/WindowsNoEditor/Pandemic/Binaries/Win64/Pandemic.exe` |
| Engine / API | Unreal Engine 4.27.2, D3D12 over vkd3d-proton |
| GPU | Intel Arc B580 (BMG G21, device `0xE20B`), Mesa 26.3.0 |
| Driver | `xess-xmx-linux-20261113-cmk3`, ICD `run/intel_icd.json`, `lib/active=26.3.0` |
| Proton | `experimental-11.0-20261105c-x86_64` |
| OptiScaler | v10.0.0-dev, loaded as `dxgi.dll`; `Dx12Upscaler=ffx`, `UpscalerIndex=0`, `Dxgi=auto`, `LogToFile=true`, `LogLevel=2` |
| Mod | `amd_fidelityfx_upscaler_dx12.dll` 4.1.2, 45,558,272 B, SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| Weights | `fsr-original.dll` 4.1.2, 57,664,272 B, SHA-256 `aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace` |
| Cabinet | game-local shim, 69,632 B, SHA-256 `951a13e3164269556609f9e7673a1d0985cdb6a585e9f19fa65f9f747e77348c` |
| Intel ext | `igdext64.dll` shim, 861,184 B, SHA-256 `ce5776bada42a91169cf724bdbf72021d1b7a3ad946ce1c86d003dd640791a85` |
| Prefix | disposable `analysis/scp5k-optiscaler-run-20261114/compatdata` |
| Launcher | `analysis/scp5k-fsr4xmx-20261114/run-fsr4xmx.sh` (local, ignored by git) |

Per-process environment:

```text
VK_DRIVER_FILES=<paquete>/run/intel_icd.json
VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer
ANV_CM_HELPER=<paquete>/tools/cm-compile.sh
ANV_CM_KERNEL_DIR=<run>/kernels
ANV_CM_DEBUG=1
WINEDLLOVERRIDES="dxgi,cabinet=n,b"
VKD3D_DEBUG=warn
```

`FSR4_XMX_INT8` and `FSR4_XMX_LITE` were not set. The session used the model selector in the
overlay (INT8, then a switch to Lite), and a later run in the loadout menu went back to the
embedded 4.0.2X.

The log is `analysis/scp5k-fsr4xmx-20261114/logs/run1/steam-872670.log` (114,733,173 B,
SHA-256 `7c61640d7d3c3f419a27aeafd6124bb3b8d46a2fc47d02ed232a1d17ecdf2d8f`). These signals
appear in it:

| Signal | Count |
|---|---|
| `INT8 model: preset weights from ...fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels` | 4 events |
| `Lite model: ...` (model change in the overlay) | 1 event |
| `INT8 network kernels ready (bucket 0, preset weights)` | 2 |
| `sampler descriptor table after the surfaces (sampler heap found)` | 9 |
| `FSR4 resource detected` (vkd3d-proton) | 99 |
| `ANV CM: injected ... .cmk` | 244 |
| `PSO create ... hr=0x00000000` | 236 lines |
| `device lost` | 0 |

Representative lines:

```text
[FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
[FSR4 XMX] INT8 network kernels ready (bucket 0, preset weights).
[FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, bucket 0, Xe2 SIMD16-DPAS kernels.
[FSR4 XMX] GPU GTGeneration=20 EU=160 driverBuild=9999 ... XMX=1 | ... SIMD16Required=1 -> Xe2 SIMD16-DPAS kernels
[FSR4 XMX] embedded 18-variant Xe2 (SIMD16 DPAS) pack loaded: ... SHA256 verified.
[FSR4 XMX] runtime geometry=1920x1080 using stock MaxResolution bucket=quality_1080
ANV CM: ~/.cache/xess-xmx/kernels/e8fca351200197b3_e20b_142835e7.cmk: sampler descriptor table after the surfaces (sampler heap found)
ANV CM: injected ~/.cache/xess-xmx/kernels/e8fca351200197b3_e20b_142835e7.cmk (...)
```

The screenshot is `analysis/scp5k-fsr4xmx-20261114/logs/run1/screen-fsr4.png`
(1920x1080, SHA-256 `b4ea38160e8aad7ce17138c5f212886b48d06e70cc15677c8b17c064231cb2e4`),
from the match the user confirmed.

The `OptiScaler.log` repeats `Upscaler support - fsr4: false` and `GPU doesn't support FSR
4, skipping the driver upscaler`, same as the successful Cyberpunk run. That is not the
authoritative indicator: the mod loads as the FFX provider, and the `INT8 model` and
`sampler heap found` lines confirm the path. Do not use the overlay label as proof.

This run proves the 4.1.2 mod loaded, verified the weights in `fsr-original.dll` and injected
`Xe2 SIMD16-DPAS` kernels, with the sampler heap found, 244 CM injected, 99 FSR4 resources
detected, 236 PSO lines at `hr=0` and no device lost. It does not prove mathematical accuracy
or equivalence with reference FSR 4, deterministic readback, or a measured quality or FPS
over more than one session. The overlay label may say `4.0.2` without
`FSR4_XMX_PROVIDER_INDEX`. Online and EAC stability are unverified: this is a multiplayer
game, so use single-player or accept the risk.

Rollback uses `analysis/scp5k-fsr4xmx-20261114/manifest.txt`: restore the official
`amd_fidelityfx_upscaler_dx12.dll` from `backup/`, delete `fsr-original.dll`, `cabinet.dll`
and `igdext64.dll`, restore `OptiScaler.ini`, and stop the unit `scp5k-fsr4xmx-20261114c`.
The kernels stay in `~/.cache/xess-xmx/kernels/`, and `ANV_CM_KERNEL_DIR` was not used. The
base OptiScaler manifest is `analysis/scp5k-optiscaler-20261114.txt`.

## How to reproduce

The commands above cover the whole chain: the three launcher invocations record, the
`ffmpeg` line cuts the clip, and `bench_quality.py report` produces the metrics. The
published comparison clips play with:

```bash
mpv media/quality-cp77/ref-native.mp4
```

The 2x2 grid of the four, with the same 400x225 crop at double size, is in
`analysis/quality-cp77/compare-crop.mp4` (local): native, XeSS, FSR INT8 and FSR Lite.
