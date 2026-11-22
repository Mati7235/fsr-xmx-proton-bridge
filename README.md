# FSR4 XMX bridge on Intel Linux

Experimental bridge to run the nitec FSR4 XMX mod on Intel Linux using
`xess-xmx-linux`: its patched Mesa ANV driver builds the mod's CM kernels and
runs them on the XMX units instead of the DP4a path of Wine/Proton. Compatibility
research, not a product.

## Current status

First working run of FSR 4 on XMX in Marvel's Spider-Man Remastered (2026-11-13)
with the side-by-side candidate package (`xess-xmx-linux-20261113-cmk3`, Mesa
26.3.0 + shim + registry 4.1.2).
See: `docs/first-fsr-xmx-success.md` and `docs/rebuild-20261113.md`.

- Tested on Spider-Man: 4.0.2X (base path, full functional evidence) and
  4.1.2X INT8 (run with `FSR4_XMX_INT8=1` and 4.1.2 in OptiScaler: it dispatches
  its own network passes; the model was inferred from the kernel set).
- Tested on Cyberpunk 2077 (built-in benchmark): 4.1.2X INT8 and Lite, confirmed
  by log (`INT8 model:` and `Lite model: 2`) and by different kernel sets. FPS in
  `docs/cyberpunk-bench-20261113.md`; quality in
  `docs/cyberpunk-quality-20261113.md`.
- Tested on SCP: 5K (UE4.27.2, DX12): 4.1.2X INT8 and Lite, with XMX injection
  confirmed by log and rendering in a match; see `docs/scp5k-fsr4xmx-20261114.md`.
- Not tested yet: the DLSS path. The Lite/INT8 weights are verified at the file
  level.
- Verified at kernel level: injection, sampler heap, 11 FSR4 resources, 0 device
  lost. No independent oracle and no deterministic readback.
- Not installed system-wide: the user's active package remains intact; the
  candidate runs only per process. Rollback in `backup-20261113/`.

Installation guide and real setup: `docs/install-setup.md`.
Upstream context: FSR 4 on XMX was already supported in `xess-xmx-linux` and was
abandoned as a product direction in November 2026, not for a technical blocker.
See `docs/upstream-fsr4-status.md`.

## Comparison videos

| Variant | Video |
|---|---|
| Native | [`ref-native.mp4`](media/quality-cp77/ref-native.mp4) |
| XeSS | [`xess.mp4`](media/quality-cp77/xess.mp4) |
| FSR 4.1.2 INT8 | [`fsr4-int8.mp4`](media/quality-cp77/fsr4-int8.mp4) |
| FSR 4.1.2 Lite | [`fsr4-lite.mp4`](media/quality-cp77/fsr4-lite.mp4) |

Cyberpunk 2077 benchmark crops, same preset and same camera. The MP4 files are
versioned here; the lossless clips used for measurement are in
`analysis/quality-cp77/` (local, ignored by Git because of their size).

1. Open [hallo.io](https://hallo.io/tools/video/video-compare).
2. Load the native video as A and one variant as B.
3. Choose `Slider`, press play and drag the divider. The tool syncs the timeline
   and corrects the drift.

Nothing is uploaded: the comparison runs in the browser. The MP4 files are
H.264 4:2:0 so that any browser or editor can open them. The 800x450 stills are
in [`media/quality-cp77/stills/`](media/quality-cp77/stills/).

## Architecture

1. Patched ANV driver: injects and builds CM kernels with ocloc at runtime.
2. `igdext64.dll` shim: answers Intel queries and delivers CM placeholders.
3. Package helper `tools/cm-compile.sh`: builds each kernel on first use.
4. FSR4 XMX mod + `fsr-original.dll` + game-local `cabinet.dll`: the mod emits
   the PRE and the packs; OptiScaler plugs it in as `Dx12Upscaler = ffx`.

## Key docs

| Doc | What it fixes |
|---|---|
| `docs/install-setup.md` | Side-by-side and system-wide installation, rollback, in-game test |
| `docs/upstream-fsr4-status.md` | What was found and why upstream abandoned the FSR 4 XMX path |
| `docs/first-fsr-xmx-success.md` | Exact setup and evidence of the first functional run |
| `docs/rebuild-20261113.md` | What was built in the candidate package and what is missing |
| `docs/xmx412-model-selection.md` | INT8/Lite/Hybrid selection, `fsr-original.dll` contract, recipe |
| `docs/cabinet-shim.md` | Game-local Cabinet shim for the mod's LZMS packs |
| `docs/spiderman-trace-runbook.md` | Manual trace runbook in Spider-Man with Proton Experimental |
| `docs/bench-quality.md` | Lossless recording, benchmark crop and quality metrics |
| `docs/cyberpunk-bench-20261113.md` | FPS in Cyberpunk: native, XeSS, FSR INT8 and Lite |
| `docs/cyberpunk-quality-20261113.md` | Quality measured in Cyberpunk and limits of the method |
| `docs/scp5k-fsr4xmx-20261114.md` | Setup and evidence of SCP: 5K with FSR 4.1.2 XMX |

## Tools (`tools/`)

- `tools/inspect_dll.py`: static inventory of DLLs (strings, SHA-256).
- `tools/parse_cm_payloads.py`: extraction of CM blocks by offsets and lengths.
- `tools/decompress_mscf.py`, `tools/decompress_xmx412.py`: LZMS decompression of
  packs with a local wimlib.
- `tools/xmx_kernel_set.py`: fingerprint and diff of kernels between runs.
- `tools/bench_quality.py`: recording alignment, PSNR/SSIM/sharpness and crops.
- `tools/build_cabinet_shim.py`: builds the game-local `cabinet.dll`.
- `tools/prepare_trace_capture_412.py`: CPU-only scaffolding for the trace run.

## License and provenance

Third-party binaries are not redistributed, and this repo grants no rights over
upstream models, DLLs or code; check their respective licenses
(`THIRD_PARTY.md` in the package, licenses of AMD/Intel/nitec/Valve).

## Provenance

- Upstream `xess-xmx-linux`: `662dc6e` (178 commits since `ef39559`).
- Package patches: `0001` CM injection (CMK3, magic fixed), `0002` debug,
  `0003` Large GRF for Xe2, `0005` sampler descriptor table, plus the
  `patches/mesa-26.3/` series (`0004` Jay, `0006` cmat).
- This repo ignores `artifacts/original/`, `artifacts/extracted/`, `upstream/`,
  `analysis/` and `build/` (local artifacts, not redistributed).
