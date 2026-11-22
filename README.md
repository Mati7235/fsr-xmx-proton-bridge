# FSR on Intel Arc under Linux

This repository runs AMD FidelityFX Super Resolution 4 on Intel Arc GPUs under Linux with Proton. A patched Mesa ANV driver dispatches the mod's XMX kernels, an `igdext64.dll` shim answers the mod's Intel queries, and a game-local `cabinet.dll` unpacks the models. [docs/how-it-works.md](docs/how-it-works.md) explains each piece. This is experimental research, the results come from one scene per game, and the code is AGPL-3.0-or-later ([LICENSE](LICENSE)) with third-party parts listed in [THIRD_PARTY.md](THIRD_PARTY.md).

## Install

The driver step runs once per machine and needs root, because it writes to `/usr`, `/opt` and `/etc` and changes the Vulkan driver for every account. Log out and back in afterwards:

```bash
cd fsr-xmx-driver
sudo ./install.sh
```

The game step runs once per game, in the folder that holds the `.exe` (for Cyberpunk 2077, `.../bin/x64`), after you copy the files from `PUT-THE-FILES-HERE.txt`:

```bash
cd ".../bin/x64"
./install.sh
```

It checks the `.exe` and the hash of each third-party file before copying, backs up what it overwrites, and prints the Steam launch line. Undo with `./uninstall.sh` per game, then `sudo ./uninstall.sh`. nitec's mod, AMD's FSR 4.1.2 DLL and OptiScaler cannot ship, so rename `OptiScaler.dll` to `dxgi.dll` in the game folder.

## What works

FSR 4 upscaling on XMX with the 4.1.2X INT8 and Lite models, XeFG frame generation through the shim, and ANR as a frame generation provider. Spider-Man Remastered and Cyberpunk 2077 render a correct scene. SCP: 5K is partial: one match, visual confirmation only, anti-cheat untested. No other title has a run on record. Per-game conditions and pins are in [compatibility.md](docs/compatibility.md), and closed lines are in [roadmap.md](docs/roadmap.md).

Do not select the DLSS entries in the mod's menu, because the mod covers FSR only and those entries do not work.

## Comparison videos

| Variant | Video |
|---|---|
| Native | [`ref-native.mp4`](media/quality-cp77/ref-native.mp4) |
| XeSS | [`xess.mp4`](media/quality-cp77/xess.mp4) |
| FSR 4.1.2 INT8 | [`fsr4-int8.mp4`](media/quality-cp77/fsr4-int8.mp4) |
| FSR 4.1.2 Lite | [`fsr4-lite.mp4`](media/quality-cp77/fsr4-lite.mp4) |

Cyberpunk 2077 benchmark crops, same preset and same camera. Load the native clip as A and one variant as B on [hallo.io](https://hallo.io/tools/video/video-compare) and drag the divider; nothing is uploaded. The 800x450 stills are in [`media/quality-cp77/stills/`](media/quality-cp77/stills/).

## Credits

The patched Mesa driver, the Intel shim and most of the groundwork come from [HHHHanasak1/xess-xmx-linux](https://github.com/HHHHanasak1/xess-xmx-linux). This repository applies its patches to Mesa 26.3.1 instead of forking it.

The FSR 4.1.2 XMX models are nitec's work, published as a mod on NexusMods. This repository does not include his DLL, only the checks that confirm the version the measurements used.

OptiScaler, from the [OptiScalers](https://github.com/OptiScalers/OptiScaler) project, puts the upscaler in front of the game. AMD provides the FidelityFX runtime, Intel the XMX kernels and graphics stack, and Valve the Proton and vkd3d-proton plumbing.

## License

Copyright (C) 2026 Matias7235. This project is free software under the GNU Affero General Public License, version 3 or later: you can use, study, change and share it, and a modified version you distribute must publish its source under the same license. [LICENSE](LICENSE) holds the full text and wins over this summary. [THIRD_PARTY.md](THIRD_PARTY.md) lists every other component and its license; none of those binaries are redistributed here, and the upstream checkout is pinned at `f06dc39`. `artifacts/`, `upstream/`, `analysis/` and `build/` are local and ignored by git.
