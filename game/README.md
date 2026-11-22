# The game step

Download the game folder (`fsr-xmx-game`) and copy it next to the game's `.exe`.
For Cyberpunk 2077 that is `.../bin/x64`. The folder carries its own
`fsr-xmx/` command, so a player never needs the repository. It is produced by
`python3 tools/build_release.py`. Run the driver step first, once per machine.

1. Drop in the files listed in `PUT-THE-FILES-HERE.txt`.
2. Run `./install.sh`, or `./install.sh <game folder>` from anywhere.
3. Paste the line it prints into the Steam launch options.

## What install.sh does

It reads `fsr-xmx/profiles/cyberpunk2077.conf` and checks, before copying
anything, that the `.exe` and the third-party files are here and that the
mod and the AMD DLL match the pinned sha256 and size. Then
`fsr-xmx/fsr-xmx enable` copies the mod, `igdext64.dll`, `cabinet.dll` and
the OptiScaler files, writes the keys the profile pins, and records each
overwritten file in `.fsr-xmx-backup/<timestamp>/manifest.tsv`.

`igdext64.dll` and `cabinet.dll` come from the per-user install in
`~/.local/share/fsr-xmx`, which is why the driver step comes first. The files sit
next to the `.exe` because that is where Wine looks for them.

Options: `--fsr4 lite` for Lite, `--fg anr --anr <zip>` for ANR frame generation.
INT8 with XeFG is the default. ANR also needs the vkd3d-proton DLLs that
`fsr-xmx install-compat-tool` copies into a Steam tool; INT8 works on stock Proton.

## Undo

`./uninstall.sh` restores every backup and compares sha256, so the game folder
ends byte-identical. If a restore fails it names the file and exits non-zero; run
it again to retry.

## What is not here

nitec's mod, `dxgi.dll` and `OptiScaler.ini` are third-party and cannot be
redistributed; `PUT-THE-FILES-HERE.txt` has the hashes and sources.
