# Capturing a real frame with RenderDoc (vkd3d-proton, inspection only)

> PERFORMANCE WARNING: capturing with RenderDoc changes the timing
> (it serializes queues, adds CPU overhead, forces extra synchronization).
> The FPS / frametimes observed under capture are NOT representative, and an
> apparent regression under RenderDoc does NOT prove a real regression.
> The capture is useful for RESOURCE INSPECTION (which textures/buffers enter
> the upscaler, dispatch dimensions, descriptor layout), not for measuring
> performance. Measurements are always done with `run-full-test.sh`
> without RenderDoc.

## Feasibility (what is safe and what is uncertain)

Verified locally (CPU-only, without running the game):

- RenderDoc installed: `renderdoccmd` x64 v1.46 (Arch), `qrenderdoc`,
  `/usr/lib/librenderdoc.so`. Compiled APIs: **Vulkan, GL, GLES**
  (there is NO D3D12 backend in this Linux build).
- Capture layer registered: `/etc/vulkan/implicit_layer.d/renderdoc_capture.json`,
  layer `VK_LAYER_RENDERDOC_Capture`, enabled with
  `ENABLE_VULKAN_RENDERDOC_CAPTURE=1` and disabled with
  `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46=1`.
- Conclusion: RenderDoc **can** capture the run, but at the level of
  **Vulkan as translated by vkd3d-proton**, not at the D3D12 level. The capture
  shows the `vkCmdDispatch` / pipelines / descriptor sets that vkd3d-proton
  generates from the game's D3D12 and the FSR mod. `PIX`/D3D12 markers appear
  only to the extent that vkd3d-proton propagates them as object names or debug
  markers.

Known practical limitations:

1. The original D3D12 (root signatures, D3D12 PSOs) is not visible, only its
   Vulkan translation. To correlate with the D3D12 trace, the `vkd3d.log`
   (`VKD3D_DEBUG=trace`) that the script saves next to the capture is useful.
2. The CM kernels of the patched driver (compiled via `ANV_CM_HELPER`)
   are NOT seen as normal shaders: they appear as compute dispatches with
   internal driver blobs, with no readable HLSL/GLSL/SPIR-V source.
   DO NOT expect to inspect the kernel code in RenderDoc.
3. RenderDoc 1.46 does not handle `VK_EXT_descriptor_buffer` well; the launcher
   already disables it (`VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer`) and the
   capture script keeps it disabled. Do not re-enable it.
4. The session is Wayland; this RenderDoc build lists WSI xlib, XCB and
   KHR_display (no native Wayland). The game runs via XWayland, which falls
   into the supported xlib/XCB path. If the window does not respond to F12, try
   with explicit focus on the game window (not on the overlay or another
   window).
5. MangoHud is forced OFF under capture (hooking Vulkan twice invalidates the
   capture and the timing). There is no frametimes CSV in this mode.

Practical assumptions NOT verified without running (uncertain, honestly noted):

- That the current vkd3d-proton inside Proton Experimental does not use any
  extension or pattern that RenderDoc 1.46 does not understand (e.g. recent
  changes to descriptor buffers, mesh shaders, video). If the capture comes out
  empty or corrupt, see "if the capture comes out empty".
- That the F12 key reaches the game through Proton/XWayland with the correct
  focus. Alternative: `qrenderdoc` → Attach to Running Instance.
- Manageable size of the `.rdc` (a AAA frame can take several GB; there are
  ~390 GB free in `/home`, enough in principle).

## Requirements

- Same machine and disposable prefix as the functional run; the system and the
  production prefix are not touched.
- `renderdoccmd` in PATH, `/usr/lib/librenderdoc.so` present,
  `/etc/vulkan/implicit_layer.d/renderdoc_capture.json` present.
- Variable `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46` NOT set (the script
  aborts if it is, because the capture would come out empty).
- Candidate driver, `kernels-candidate/`, `fsr-original.dll` and `compatdata/`
  already existing in the run directory (the script reuses them and does not
  regenerate them unless `--fresh-kernels` is given).

## Exact command

From the run directory:

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-renderdoc.sh int8 ciudad-rdc
# o: ./run-renderdoc.sh lite ciudad-rdc
# o: ./run-renderdoc.sh stock ciudad-rdc
```

Optional flags (the same as `run-full-test.sh`, minus MangoHud):

- `--proton-log`: also saves `steam-proton.log` with the mod's log.
- `--fresh-kernels`: recompiles kernels into `captures/<tag>-<modelo>-<stamp>/kernels`
  instead of reusing `kernels-candidate/`.

The script is a twin of `run-full-test.sh` in environment (same Proton, same
candidate ICD, same `VKD3D_DISABLE_EXTENSIONS`, same `ANV_CM_*`, same
int8/lite/stock mode) with three differences: (a) it wraps the launch with
`renderdoccmd capture --opt-hook-children`, (b) it sets
`ENABLE_VULKAN_RENDERDOC_CAPTURE=1` and explicitly disables all other implicit
layers **except** the RenderDoc one (`'*'` cannot be used because it would
also disable the capture), and (c) it writes to `captures/` instead of
`results/`.

## Key and where the `.rdc` ends up

- With the game window in focus, press **F12** (RenderDoc's default capture key)
  on the scene to inspect. Several consecutive frames can be taken; each one
  generates a new file.
- Files end up in `captures/<tag>-<modelo>-<stamp>/spiderman_frame*.rdc`.
- Open with: `qrenderdoc captures/<tag>-<modelo>-<stamp>/spiderman_frame<N>.rdc`
- Next to each capture are `vkd3d.log`, `fingerprint.txt` and `summary.txt`
  (same injection-evidence criterion as `run-full-test.sh`).

## If the capture comes out empty or the game does not start

1. **No `.rdc` after F12**: confirm focus on the game window and retry
   F12. Alternative: open `qrenderdoc` → File → Attach to Running Instance,
   connect to the process and trigger the capture from the UI.
2. **The game does not start under `renderdoccmd` but does with `run-full-test.sh`**:
   verify that `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46` is not set in the shell
   (`env | grep RENDERDOC`), and that there is no other active overlay
   (MangoHud, OBS, gamescope). The script already disables the known ones; if
   another overlay was installed with an implicit layer, add it to `LAYERS_DISABLE`.
3. **0-byte capture or one that does not open**: try `--fresh-kernels` (rules
   out interference from the kernel cache) and check `vkd3d.log` for Vulkan
   device creation errors. It may be an extension that RenderDoc 1.46 does not
   support: report it with the Proton version and the log.
4. **The game starts but everything is very slow / hangs**: partly expected
   (capture overhead + `VKD3D_DEBUG=trace`). It is not a driver regression. If
   it prevents reaching the scene, ask for a variant with reduced tracing (do not
   improvise manual environment changes).
5. **`renderdoccmd` complains about the layer**: re-verify
   `renderdoccmd version` and the manifest
   `/etc/vulkan/implicit_layer.d/renderdoc_capture.json`.

## Returning to the normal launcher

Close the game and keep measuring with the launcher without capture:

```bash
./run-full-test.sh int8 ciudad1
```

Nothing from capture mode contaminates the measurements: it writes to `captures/`,
does not touch `results/`, and does not modify `compatdata/` beyond normal game
use. `VK_LOADER_LAYERS_DISABLE` returns to its original launcher value.

## What NOT to expect from the capture

- NOT seeing the driver's CM kernels as normal shaders with inspectable source
  (they are opaque internal blobs of the `ANV_CM_*` path).
- NOT seeing the original D3D12 pipeline (root signatures, D3D12 PSOs): only
  its Vulkan translation made by vkd3d-proton.
- NOT using the capture's timings to compare int8 vs lite vs stock.
- NOT taking the capture as proof of injection by itself: the injection proof
  remains `ANV CM:.* injected` in `vkd3d.log` + `fingerprint.txt`, the same as in
  `run-full-test.sh`.
