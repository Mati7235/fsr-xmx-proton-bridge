# Measuring image quality across upscalers

Procedure for comparing FSR 4.1.2 XMX against XeSS and against a native
render, with numerical and visual evidence. Requires `wf-recorder`, installed
from the official repos (`wf-recorder 0.6.0`).

## Why the eye is not enough

"It looks sharper" is an impression. To make it a data point three things are
needed: the same scene, a reference and a metric. The right reference is not
another upscaler but the native render: FSR's job is to approximate what
you would see without an upscaler.

## Recording

`wf-recorder` records the compositor output losslessly. The launcher starts it
and stops it only with `--record`:

```bash
./run-full-test.sh manual ref-native --game cyberpunk --native --record --proton-log
./run-full-test.sh manual cp-xess     --game cyberpunk --upscaler xess --record --proton-log
./run-full-test.sh int8  cp-int8      --game cyberpunk --record --proton-log
```

- `ref-native`: `--native` sets aside `dxgi.dll` (OptiScaler) and the mod DLL
  during the run; the game keeps its TAA. Turning the upscaler off in the
  menu is not enough: Cyberpunk applies FSR in the benchmark cutscenes even
  when it is set to Off.
- `cp-xess`: XeSS.
- `cp-int8`: FSR 4.1.2.
- Each run leaves `bench.mkv` in its results folder.

Recording parameters: `libx264rgb`, `crf=0` (lossless, `Avg QP 0.00`),
4:4:4, 1920x1080, 60 fps, MKV. No AV1 or 4:2:0: they destroy chrominance
exactly where the difference shows.

Conditions: same resolution, same preset, same graphics options, and run the
full bench in all three.

## Trimming the bench

The full recordings include desktop, menu, loading and results. To compare,
it is best to cut the bench segment once in each video:

- **Start**: first frame with an image after the black loading gap before it.
- **End**: just before the cut to the results screen (dark background,
  "Average FPS" in orange).
- Typical duration: ~69 s of wall clock, even though the game counter says 64.2 s.

```bash
ffmpeg -v error -y -ss 79.883 -i bench.mkv -t 69.317 \
  -c:v libx264rgb -crf 0 -preset ultrafast -pix_fmt gbrp -an -sn bench-clip.mkv
```

`-ss` before `-i` and re-encoding give an exact cut to the frame. With `-c copy`
the cut falls on the previous keyframe and can be off by up to 4 s. Re-encoding
with `libx264rgb -crf 0` is lossless over RGB, same as the recording. Save the
seconds used in a JSON next to the clip.

## Analysis

On the already trimmed clips, with `--length` equal to the clip duration:

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

The clips start at the same frame of the bench and the camera follows a fixed
timeline, so the same second corresponds to the same position even if one clip
is 60 fps and another is not. Verified: at 30 s the optimal offset between
XeSS and Lite is 0, and shifting by one frame makes the MSE 2 to 4 times worse.
Against native there is a residual of 2 or 3 frames, which the tool corrects
on its own.

The published versions for comparison are the H.264 4:2:0 MP4s in
`media/quality-cp77/`. The lossless clips are used only for measuring and stay
local.

What it does:

1. Extracts thumbnails at 1 fps from each video.
2. Detects the bench: it looks for the `--length`-second segment that **best
   matches between the reference and each video**. The bench repeats the same
   camera path, so aligning it gives the minimum error; the menu has an
   animated background but is not synchronized between runs, and loading
   changes it directly. It returns the start second in the reference and the
   offset of each video. With clips that already start in the bench, the
   segment is the full clip (`--length` equal to its duration).
3. Refines the sub-second offset to 60 fps: one second of resolution leaves up
   to half a second of error, which with a moving camera is a different scene.
4. Extracts the same frame from each video at normalized positions.
5. Computes per frame:
   - **PSNR and SSIM** against the native reference, on the full frame and on
     the crop. The crop is a static area and avoids paying for the movement of
     pedestrians and vehicles, which does not line up between runs.
   - **Sharpness**: variance of the Laplacian over luma. It is the way to turn
     "vaseline" into a number; a blurry upscaler gives much less than native.
5. Generates side-by-side crops (`crop_*.png`) with labels, at double size.
6. Writes `report.md` with the table.

## How to read it

- High sharpness is not automatically better: oversharpening also raises the
  Laplacian. Read it together with PSNR/SSIM, not instead of them.
- PSNR and SSIM against native drop if the upscaler adds detail that native
  does not have, even if it looks better. They serve to compare the upscalers
  with each other, not as an absolute verdict.
- The crops are the convincing evidence: text, railings, grilles and surfaces
  with fine detail at 200%.
- A single scene does not generalize. To claim something stronger, repeat with
  another area of the bench and another preset.

## Limits

- Recording lossless costs performance. The recorded runs measured 41.7
  (native), 35.7 (XeSS), 36.7 (FSR) and 28.4 (Lite) fps on average, against 54-55
  without recording. The videos are good for quality; performance is measured in
  runs without recording.
- The game counter says 64.2 s, but the bench segment in the recording lasts
  ~69 s of wall clock due to stutters and loading. To trim it, the start is the
  first frame with an image after the previous black gap and the end is the cut
  to the results screen, not 64.2 s from an offset.
- The native render is not an absolute ground truth: it has its own TAA with
  ghosting. It is the practical reference available without AMD hardware.
- The video goes through the compositor's composition; it is not the raw
  framebuffer. For that, RenderDoc would be needed, which is another tool and
  another target.
- Alignment is per second; one-frame differences in the animation add noise to
  PSNR.
