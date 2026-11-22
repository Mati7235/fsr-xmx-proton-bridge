# FSR on Intel Arc under Linux

This repository makes AMD FidelityFX Super Resolution run on Intel Arc GPUs under Linux
with Proton, and packages the working stack. A patched Mesa ANV driver builds the mod's
kernels, an `igdext64` shim answers Intel queries, and a game-local `cabinet.dll` supplies
the compression API Wine lacks. The driver comes from `xess-xmx-linux`; this repo holds
research, game shims and documentation.

This is experimental research, not a finished product. Two games render correctly and a
third only partly, the results come from one scene each, and the numbers are in
[docs/benchmarks.md](docs/benchmarks.md). The code is released under the GNU Affero General
Public License version 3 or later ([LICENSE](LICENSE)), and [THIRD_PARTY.md](THIRD_PARTY.md)
explains which parts belong to other authors.

## How to install it

Run the driver step once per machine. It needs root because it writes to `/usr`,
`/opt` and `/etc`, and it changes the Vulkan driver for every account:

```bash
cd fsr-xmx-driver
sudo ./install.sh
```

It takes a `snapper` snapshot when installed and adds a Vulkan ICD next to
Mesa's own file instead of replacing it, plus `/etc/environment.d/fsr-xmx.conf`,
which sessions read at login. Log out and back in afterwards.

The game step runs once per game, where the game's `.exe` is (for Cyberpunk
2077, `.../bin/x64`), after you copy the files from `PUT-THE-FILES-HERE.txt`:

```bash
cd ".../bin/x64"
./install.sh
```

It checks the `.exe` and hashes first, backs up what it overwrites, and prints
the Steam launch line. The mod goes next to the `.exe`, where Wine looks. Undo
with `./uninstall.sh` per game, then `sudo ./uninstall.sh`. nitec's mod, AMD's
FSR 4.1.2 DLL and OptiScaler cannot ship; their authors do not allow it, so
rename `OptiScaler.dll` to `dxgi.dll` in the game folder.

## What works today

FSR 4 upscaling on XMX with the 4.1.2X INT8 and Lite models, XeFG frame generation through
the shim, and ANR as a frame generation provider. Spider-Man Remastered and Cyberpunk 2077
render a correct scene. SCP: 5K is partial: one match, visual confirmation only, and the
anti-cheat was not tested. Every benchmark is one scene, and two runs of the same model set
the noise floor, so no second area or preset was measured. Tables are in
[docs/benchmarks.md](docs/benchmarks.md), per-title conditions in
[docs/compatibility.md](docs/compatibility.md).

## The fsr-xmx commands

[docs/install-setup.md](docs/install-setup.md) covers the manual install with
`xess-xmx-linux`, rollback and the in-game test. The `fsr-xmx` command in `installer/`
is the engine behind the two scripts above, and also runs the diagnostics. Everything it
writes under your home needs no `sudo`; only the driver step above does.

```text
fsr-xmx install --from <folder>
fsr-xmx enable <game-folder> --fsr4 int8|lite [--fg xefg|anr]
fsr-xmx doctor <game-folder> --profile <game>
```

## What does not work

FSR frame generation and Anti-Lag 2 are closed, and other titles remain untested, as does
replacing the stock system driver (the driver step only adds an ICD next to it). See
[docs/roadmap.md](docs/roadmap.md).

Do not select the DLSS entries in the mod's upscaler menu. The mod covers FSR only, not
DLSS, so those entries do not work.

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

## Credits

The patched Mesa driver, the Intel shim and most of the groundwork come from
[HHHHanasak1/xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux). Without that
project FSR 4 would have no compute path on Arc at all, and this repository builds on its
patches instead of forking it.

The FSR 4.1.2 XMX models are nitec's work, published as a mod on NexusMods. This
repository does not include his DLL, only the checks that make sure you are running the
version the measurements were taken with.

OptiScaler, from the [OptiScalers](https://github.com/OptiScalers/OptiScaler) project, is
what puts the upscaler in front of the game. AMD provides the FidelityFX runtime, Intel the
XMX kernels and graphics stack, and Valve the Proton and vkd3d-proton plumbing.

## License and provenance

Copyright (C) 2026 Matias7235.

This project is free software under the GNU Affero General Public License, version 3 or
later. You can use it, study it, change it and share it, and if you distribute a modified
version you have to publish its source under the same license. The full text is in
[LICENSE](LICENSE), and it wins over this summary.

[THIRD_PARTY.md](THIRD_PARTY.md) lists every component that comes from someone else, with
its license: nitec's mod, AMD's DLL, Intel's DLL, OptiScaler, Mesa and vkd3d-proton. None of
those binaries are redistributed here, and this repository grants no rights over them.
Upstream `xess-xmx-linux` is pinned at `f06dc39`. The folders `artifacts/`, `upstream/`,
`analysis/` and `build/` are local and ignored by git.
