# Installer design

This is a design record, not a tutorial; the steps are in each download folder's `README.md`. The
scripts work and `tools/build_release.py` assembles them; the binary bundle the driver step
consumes is not packaged yet.

## Goal

A player downloads two folders and runs one script from each. The driver step runs once per
machine; the game step runs once per game. Neither needs this repository, a compiler, or an agent.

`python3 tools/build_release.py` creates `fsr-xmx-game` and `fsr-xmx-driver` under
`build/release/`. Each is self-contained: the scripts from `game/` or `driver/`, plus its own copy
of the `fsr-xmx` command with `lib/common.sh`, `lib/ini_edit.py`, `lib/vdf.py` and
`profiles/cyberpunk2077.conf`. The builder skips `.dll`, `.ini`, `.zip`, `.7z`, `__pycache__` and
`.git`, so no third-party file enters a download.

## What ships

`fsr-xmx-game` holds `install.sh`, `uninstall.sh`, `find-cli.sh`, `PUT-THE-FILES-HERE.txt`,
`README.md` and `fsr-xmx/`. `fsr-xmx-driver` holds the same shape without the payload list.
`find-cli.sh` prefers `fsr-xmx/fsr-xmx` next to the script, so the download's copy wins.

Both scripts call the same command, which also runs diagnostics on its own:

```text
fsr-xmx doctor [<game-folder>] [--profile <game>]
fsr-xmx install --from <folder>
fsr-xmx install-compat-tool --ge-dir <GE-Proton folder>
fsr-xmx enable <game-folder> --fsr4 int8|lite [--fg xefg|anr]
fsr-xmx disable <game-folder>
fsr-xmx run [--profile <game>] [--trace] -- <command...>
fsr-xmx uninstall
```

`doctor` changes nothing. It checks the Intel card, its kernel driver, the Vulkan loader, `python3`
and Steam, verifies the active install against `SHA256SUMS`, and compares the DLLs in every tool
with a `.fsr-xmx-manifest`. For a game folder it checks the pinned files, the INI keys and
`PENDING_RESTORE`.

## The binary bundle

`install --from` consumes a folder that `build_release.py` does not produce. The engine validates
this layout before copying anything:

```text
MANIFEST
SHA256SUMS
icd/intel_icd.json
lib/libvulkan_intel.so
igdext64.dll
cabinet.dll
vkd3d-proton/x86_64-windows/d3d12.dll
vkd3d-proton/x86_64-windows/d3d12core.dll
tools/cm-compile.sh
```

Every path in `SHA256SUMS` must exist and match, and the list must name the five runtime files:
`igdext64.dll`, `cabinet.dll`, the ICD and the two vkd3d DLLs. The engine copies the folder to
`~/.local/share/fsr-xmx/versions/<VERSION>/` and switches `current` in one rename only after the
copy verifies. Without `--from`, `download_release` prints the planned Releases pattern and fails.

## Root and disk layout

Only the driver step needs root. When `snapper` is installed, `install.sh` takes a snapshot of the
`root` config first, prints the number and never deletes it. It writes the per-user install with
`fsr-xmx install --from`, then these machine-wide paths:

```text
/usr/lib/fsr-xmx/libvulkan_intel.so
/usr/share/vulkan/icd.d/fsr-xmx-intel_icd.json
/opt/fsr-xmx/igdext64.dll
/opt/fsr-xmx/cabinet.dll
/opt/fsr-xmx/created.tsv
/etc/environment.d/fsr-xmx.conf
```

The ICD is a second file next to Mesa's `intel_icd` file. The script rewrites its `library_path` to
the library above and never replaces Mesa's file. `/etc/environment.d` applies at login, so the
script prints the `export` for the current session. The file carries `VK_DRIVER_FILES`,
`ANV_CM_HELPER`, `ANV_CM_KERNEL_DIR` and `WINEDLLOVERRIDES`, not the FSR model variables. The script
refuses to continue when any target already exists.

The game step needs no root. The per-user root `~/.local/share/fsr-xmx` holds `.fsr-xmx-root`,
`current` pointing into `versions/`, and `profiles/<game>/state.conf`. The cache holds
`~/.cache/fsr-xmx/<appid>/kernels` and `~/.cache/fsr-xmx/<appid>/logs`. The game folder holds
`.fsr-xmx-backup/<timestamp>` with `files/` and `manifest.tsv`. The marker records that the engine
created the root, so `uninstall` will not delete a folder it does not own. `FSR_XMX_HOME`,
`FSR_XMX_CACHE` and `FSR_XMX_STEAM` override the locations for tests.

`install-compat-tool` copies the named GE-Proton folder to
`compatibilitytools.d/GE-Proton-XMX/`, swaps in the bundle's two vkd3d DLLs and records their
hashes. It never edits the source folder and does not follow updates.

## Activation per launch

`enable` writes `state.conf` with the appid, model, frame generation mode, extension blocklist, DLL
overrides and backup folder. `run` reads that state and exports the environment for one process:
`VK_DRIVER_FILES` pointing at the ICD in the active install, `VK_LOADER_LAYERS_DISABLE='*'`, the
profile's `VKD3D_DISABLE_EXTENSIONS`, `ANV_CM_HELPER`, `ANV_CM_KERNEL_DIR` for the appid,
`ANV_CM_DEBUG=1`, `WINEDLLOVERRIDES` with `dxgi` and `cabinet` as `n,b`, `PROTON_LOG=1`,
`PROTON_LOG_DIR`, `VKD3D_DEBUG` at `warn` or `trace`, and the `FSR4_XMX_*` variables for the chosen
model. An ANR profile adds `VKD3D_KEEP_COOPMAT_EXTENSION=1`. Then `run` `exec`s the command. It
writes no environment file into the game, the prefix or the session. The Steam line is one entry:

```text
fsr-xmx run --profile cyberpunk2077 -- %command%
```

`run` finds the profile from the name, the folder, a path in the command or `SteamAppId`, and asks
for `--profile` when several games match none.

## Enable, disable and the backup model

Before copying, `enable` checks the profile's `.exe`, that the game is closed, and that the driver
install exists. It verifies nitec's mod and AMD's `fsr-original.dll` by pinned sha256 and size, and
any OptiScaler or ANR archive before extraction. The game folder receives the mod,
`fsr-original.dll`, `igdext64.dll`, `cabinet.dll`, OptiScaler's `dxgi.dll`, `OptiScaler.ini` and,
for ANR, the `OptiScaler/custom/Apex Neural Rendering FG` tree. The INI edit works by section and
key, keeps the CRLF endings, and reports each changed key.

Every overwritten file goes to `.fsr-xmx-backup/<timestamp>/files/<relative path>`. The manifest
beside it starts with `FORMAT`, `GAME_DIR` and `CREATED`, then holds one row per path: `replaced`
with the original hash, `added` for a path that did not exist, or `mkdir` for a directory the step
created. A file whose bytes already match is neither copied nor recorded.

`disable` walks the backup folders from newest to oldest. It restores every `replaced` file with
`cp -p`, removes every `added` path and removes the directories it created. It then compares the
sha256 of each restored file with the hash recorded before the change and checks that every added
path is gone. A mismatch or a missing backup names the file and exits non-zero.

A failed restore leaves the backup folder unmarked. `disable` writes `PENDING_RESTORE` in
`state.conf`, keeps the game set up and retries next run; `doctor` lists the same paths. Only a
clean run writes the `applied` markers and renames the state file. The backup folder stays until
the player deletes it. `uninstall` refuses while any game still has `state.conf`, removes the tool
folders that carry `.fsr-xmx-manifest` and the per-user root when the marker is present, and leaves
the shader cache.

The driver step keeps `/opt/fsr-xmx/created.tsv`, one `dir` or `file <hash> <path>` row per created
path. `driver/uninstall.sh` refuses when a listed file changed, removes the paths in reverse and
calls `fsr-xmx uninstall`, so Vulkan returns to Mesa even if a game step is pending.

## Deliberately excluded

Anti-Lag 2 is closed. OptiScaler's XeLL and LatencyFlex cover low latency, so reopening needs a game
that asks for `VK_AMD_anti_lag` and cannot use either.

FSR frame generation is closed. It needs the AGS WMMA path and a 16x16x16 matrix that Xe2 cannot
express, and every skipped pass produces a duplicated frame. Patch 0006 was removed with that work.

Patching vkd3d-proton stays out of scope for the upscaler. Patch 0005 only kept the cooperative
matrix extension for ANR's shared device. The bundle still carries the two vkd3d DLLs and
`install-compat-tool` copies them into a separate `GE-Proton-XMX` tool. The default INT8 and XeFG
path runs on stock Proton, and the installer does not modify the Proton build already installed.

The DLSS packs inside nitec's mod are not offered. Packs 40104 to 40106 are compiled into the DLL,
but they need NVIDIA's `nvngx_dlss.dll` weights and nobody verified them on Intel. The menu lists
DLSS entries that fail for the same reason, so the README warns against selecting them.

## Licensing and sourcing

This repository ships no prebuilt binaries. The patched Mesa driver and the `igdext64` shim come
from `xess-xmx-linux` at a pinned revision; `cabinet.dll` is built from
`tools/build_cabinet_shim.py`. That package carries its own license and `THIRD_PARTY.md`, and this
repo grants no rights over upstream code or models.

Three inputs cannot be redistributed: nitec's FSR 4 XMX mod, OptiScaler and AMD's official
`fsr-original.dll`. The player supplies all three. The profile pins the mod and the AMD DLL by
sha256 and size, and the OptiScaler and ANR archives by sha256. OptiScaler comes from its official
GitHub release; nitec's permission is still pending. Archives stay under `artifacts/original`, and
`upstream/` is ignored.

## Open items

The driver bundle is not packaged. There is no folder for `install --from`, no build script here,
and the glibc range of a future build is unverified. The GitHub release is not published either.
`download_release` is a stub, so every install today starts from a local folder, and nitec's
permission is pending. Only Cyberpunk 2077 has a profile; other titles, Flatpak Steam and a second
machine remain untested, and the doctor warns about Flatpak instead of pretending its paths are
visible.
