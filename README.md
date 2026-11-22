# FSR on Intel Arc under Linux

This repository makes AMD FidelityFX Super Resolution run on Intel Arc GPUs under Linux
with Proton, and packages the working stack. A patched Mesa ANV driver builds the mod's
kernels, an `igdext64` shim answers Intel queries, and a game-local `cabinet.dll` supplies
the compression API Wine lacks. The driver comes from `xess-xmx-linux`; this repo holds
research, game shims and documentation.

## What works today

FSR 4 upscaling on XMX with the 4.1.2X INT8 and Lite models, XeFG frame generation through
the shim, and ANR as a frame generation provider. It rendered correctly in Spider-Man
Remastered, Cyberpunk 2077 and SCP: 5K. Every benchmark is one scene, and two runs of the
same model set the noise floor, so no second area or preset was measured. Tables are in
[docs/benchmarks.md](docs/benchmarks.md), per-title conditions in
[docs/compatibility.md](docs/compatibility.md).

## Install

[docs/install-setup.md](docs/install-setup.md) covers the manual install with
`xess-xmx-linux`, rollback and the in-game test. The installer in `installer/` does the
same without `sudo` and tells you what to paste into the Steam launch options.

```text
fsr-xmx install --from <folder>
fsr-xmx enable <game-folder> --fsr4 int8|lite [--fg xefg|anr]
fsr-xmx doctor <game-folder> --profile <game>
```

## What does not work

FSR frame generation and Anti-Lag 2 are closed, and the DLSS packs, other titles and a
system-wide install remain untested. See [docs/roadmap.md](docs/roadmap.md).

## Comparison videos

| Variant | Video |
|---|---|
| Native | [`ref-native.mp4`](media/quality-cp77/ref-native.mp4) |
| XeSS | [`xess.mp4`](media/quality-cp77/xess.mp4) |
| FSR 4.1.2 INT8 | [`fsr4-int8.mp4`](media/quality-cp77/fsr4-int8.mp4) |
| FSR 4.1.2 Lite | [`fsr4-lite.mp4`](media/quality-cp77/fsr4-lite.mp4) |

Cyberpunk 2077 benchmark crops, same preset and same camera. Open
[hallo.io](https://hallo.io/tools/video/video-compare), load the native video as A and one
variant as B, then drag the divider; nothing is uploaded. The H.264 files play in any
browser, and the 800x450 stills are in
[`media/quality-cp77/stills/`](media/quality-cp77/stills/).

## How to find things

| Document | What it answers |
|---|---|
| [compatibility.md](docs/compatibility.md) | Which games and models work, and under what conditions |
| [install-setup.md](docs/install-setup.md) | Side-by-side and system-wide install, rollback, game test |
| [benchmarks.md](docs/benchmarks.md) | FPS and image metrics, and how a run is recorded |
| [roadmap.md](docs/roadmap.md) | Closed lines, open questions, out of scope |
| [validation.md](docs/validation.md) | What evidence counts as proof, and what does not |
| [xmx412-model-selection.md](docs/xmx412-model-selection.md) | INT8, Lite and DLSS model choice, weights contract |
| [xmx412-dispatch.md](docs/xmx412-dispatch.md) | The PRE dispatch a shim must reproduce |
| [xmx412-toolchain.md](docs/xmx412-toolchain.md) | Compiler pins, offline compile, DLL inventory |
| [xmx412-pack-envelope.md](docs/xmx412-pack-envelope.md) | Pack layout and embedded CM envelopes |
| [shim-bridge.md](docs/shim-bridge.md) | Shim bugs, cross-build, pack regeneration |
| [cabinet-shim.md](docs/cabinet-shim.md) | LZMS packs and the game-local `cabinet.dll` |
| [anr-fg-xmx.md](docs/anr-fg-xmx.md) | ANR frame generation timings and limits |
| [spiderman-trace-runbook.md](docs/spiderman-trace-runbook.md), [pre-trace-capture-spec.md](docs/pre-trace-capture-spec.md), [pre-trace-version-checklist.md](docs/pre-trace-version-checklist.md) | Manual trace steps, what to record, version rows |

## License and provenance

Third-party binaries are not redistributed, and this repo grants no rights over upstream
models, DLLs or code; check their licenses (`THIRD_PARTY.md` in the package, and the
licenses of AMD, Intel, nitec and Valve). Upstream `xess-xmx-linux` is pinned at `f06dc39`,
and `artifacts/`, `upstream/`, `analysis/` and `build/` are local and ignored.
