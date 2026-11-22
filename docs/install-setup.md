# Installation and setup: FSR4 XMX on Intel Linux with xess-xmx-linux

Fail-closed guide. The whole working stack runs on the
`xess-xmx-linux` package (patched Mesa ANV driver + IGDEXT shim + ocloc helper).
That package is the central piece; this repo provides research, game shims and
documentation, not a driver of its own.

Do not run anything as part of reading this guide. Every command here came from
a file read from the repo or the candidate package. If a step is not documented
in a source, that is stated explicitly.

## 1. Requirements

- Intel Xe2 GPU. Tested: Arc B580. Source: `docs/compatibility.md`
  (B580, correct rendering in Spider-Man) and the package README (Xe2 tested
  by a contributor on B580).
- System Mesa compatible with the package driver. The package ships its own
  drivers (see §2) and `tools/session-check.sh` verifies that the package
  driver loads against the system libraries. If it fails, the session
  falls back to the stock drivers.
- Proton Experimental. Source: `docs/spiderman-trace-runbook.md` (path
  `.../steamapps/common/Proton - Experimental/proton`, version
  `experimental-11.0-20261105c` recorded on the day of the trace; re-verify
  with `cat` because Steam may update it).
- Native Steam. The package's `install.sh` only covers native Steam
  (SteamOS, distribution package) and warns that Flatpak Steam does not see
  `~/.config/environment.d` or the package folder.
- Compression/ocloc tool that the package already brings. `install.sh` fetches
  the compiler bundle with `tools/get-igc.sh` (IGC + ocloc) if it is missing from
  `igc/`, and `tools/cm-compile.sh` is the helper that the driver invokes at
  runtime. The LZMS decompression of the mod's packs was validated in this repo
  with local wimlib (`docs/cabinet-shim.md`), but at runtime the one that
  compiles kernels is the package's helper.

## 2. What the pieces are

Package `xess-xmx-linux-20261113-cmk3` (candidate verified in
`docs/compatibility.md`):

- Patched Mesa ANV driver in `lib/` (`lib/mesa-*/libvulkan_intel.so`,
  forwarder `lib/libvulkan_intel.so`, ICD in `run/intel_icd.json`).
- Shim `igdext64.dll` at the package root.
- CMK kernels in `kernels/` and cache in `~/.cache/xess-xmx/kernels`.
- Helper `tools/cm-compile.sh` (runtime compiler invoked by the driver).
- Scripts: `install.sh`, `enable.sh`, `disable.sh`, `uninstall.sh`,
  `xmx-launch.sh`, `xmx-stock.sh`, `tools/switch-driver.sh`,
  `tools/session-check.sh`.
- User systemd units and session environment (see §4).

Game-side pieces (not included in the package, do not redistribute):

- nitec's FSR4 XMX mod: `amd_fidelityfx_upscaler_dx12.dll` from the 4.1.2 mod.
  Hash pinned in `docs/xmx412-model-selection.md` and in the runbook.
- `fsr-original.dll`: official AMD FidelityFX Upscaler DX12 DLL from FSR
  4.1.2, renamed, placed next to the mod DLL (or next to the EXE, or via
  `FSR4_XMX_LITE_DLL`). It provides the INT8/Lite weights. It is not in this repo;
  its SHA-256 is not pinned here. See `docs/xmx412-model-selection.md` §4.
- `cabinet.dll` workaround: game-local shim built by
  `tools/build_cabinet_shim.py` (see `docs/cabinet-shim.md`). It exists only
  next to the game, never in prefixes' `system32` nor in Proton/Wine.
- OptiScaler with `Dx12Upscaler = ffx` (FSR/XMX path). Source:
  `docs/validation.md` and runbook §2.

## 3. Side-by-side installation (without touching the system)

This is the mode used for the first functional run. Source:
`docs/compatibility.md`.

Relevant structure of the package (read listing):

```text
xess-xmx-linux-20261113-cmk3/
  install.sh enable.sh disable.sh uninstall.sh
  xmx-launch.sh xmx-stock.sh igdext64.dll
  lib/ run/intel_icd.json kernels/ igc/ patches/
  tools/switch-driver.sh tools/session-check.sh tools/cm-compile.sh
  docs/ LICENSE THIRD_PARTY.md
```

Steps:

1. Leave the user's active package untouched. The candidate lives in its own
   folder (`~/xess-xmx/xess-xmx-linux-20261113-cmk3`).
2. Load verification without installing, with `XMX_CHECK_LIB` pointing to the
   new package's driver. Source: `docs/compatibility.md`
   (`session-check --dry-run` with `XMX_CHECK_LIB` enumerates the B580 as
   `Mesa 26.3.0 (git-51c31a484c)`) and the package's `tools/session-check.sh`
   (`XMX_CHECK_LIB` / `XMX_CHECK_ICD` as overrides for testing only):

```bash
XMX_CHECK_LIB="$PWD/lib/mesa-26.3.0/libvulkan_intel.so" bash tools/session-check.sh --dry-run
```

Note: the exact driver path depends on `lib/active` and on the versions
present in `lib/mesa-*/`. The example uses `mesa-26.3.0` because the
candidate lists `lib/active` with `26.3.0`. If your copy differs, adjust
with the actual listing of `lib/`; do not invent the version.

3. Starting hash verification (read-only). Source:
   `docs/spiderman-trace-runbook.md` §1:

```bash
cd ~/Proyectos/fsr-xmx-proton-bridge
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
```

The expected hash of the mod is pinned in `docs/xmx412-model-selection.md`
and in the runbook. If it differs: stop, do not continue.

4. Launch the game only per process with the candidate's ICD and the new
   helper. Source: `run-candidate.sh` from the trace run. Variables that this
   script sets (environment replaced per process, nothing system-wide):

```bash
export STEAM_COMPAT_DATA_PATH="$PWD/compatdata"
export VK_DRIVER_FILES="<package>/run/intel_icd.json"
export VK_LOADER_LAYERS_DISABLE='*'
export VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer
export ANV_CM_KERNEL_DIR="<run>/kernels-candidate"
export ANV_CM_HELPER="<package>/tools/cm-compile.sh"
export ANV_CM_DEBUG=1
export WINEDLLOVERRIDES="cabinet=n,b"
export VKD3D_DEBUG=trace
```

The exact Proton command and the disposable prefix are in
`run-candidate.sh` and in runbook §4. The game path is not reproduced here
because it depends on your installation; use the one from your machine.

## 4. System-wide installation (the real mechanism)

This is the package's real installation mechanism. Everything described here
came from `install.sh`, `enable.sh`, `xmx-launch.sh`, `tools/session-check.sh`
and `tools/switch-driver.sh` of the candidate package.

### Option A: the whole session (`install.sh`)

```bash
./install.sh
```

What it does (faithful summary of the script):

1. Fetches the compiler bundle (`tools/get-igc.sh`), the XeSS libraries
   (`tools/get-xess.sh`) and FidelityFX (`tools/get-ffx.sh`) if missing.
2. Writes `~/.config/environment.d/50-xess-xmx.conf`: the patched ANV as the Intel
   Vulkan driver (`VK_DRIVER_FILES`), `VKD3D_DISABLE_EXTENSIONS`,
   `ANV_CM_KERNEL_DIR`, `ANV_CM_HELPER`, `force_vk_vendor=0`,
   `INTC_ALT_DRIVER_EXTENSIONS_PATH`. Applies to Steam after reboot or re-login.
3. Copies the `igdext64.dll` shim into each Proton that has its own igdext and
   into each prefix with an `igd_faux` folder, saving the original as `.stock`.
4. Installs the `xess-xmx-shim.path` unit that reinstalls the shim after Proton
   updates or new prefixes.
5. Installs `xess-xmx-check.service`: before each graphical session it runs
   `tools/session-check.sh`; if the patched driver does not load, the session
   falls back to the stock drivers instead of losing the Intel GPU.

Environment variables accepted by `install.sh`: `XMX_NO_ENV=1` (skips step 2),
`XMX_DRIVER=stock|patched|auto` (chooses the driver), `MESA=<version>`
(per game, in its launch options). Source: header of `install.sh` and the
package README.

### Option B: a single game (`enable.sh`)

```bash
XMX_APPID=<steam app id> ./enable.sh
```

or, for other launchers:

```bash
XMX_PREFIX=<game-prefix> ./enable.sh
```

Variables: `XMX_APPID` or `XMX_PREFIX` (one required), `XMX_CONF`
(default `~/.config/xess-xmx.conf`), `XMX_GAME` (if set, enable/disable refuse
while the game is running). Source: header of `enable.sh`.

What it does: copies the shim to the prefix (original as
`igdext64.dll.stock`), writes the block marked `XESS-XMX` into `XMX_CONF`
with `VK_DRIVER_FILES`, `VKD3D_DISABLE_EXTENSIONS`,
`ANV_CM_KERNEL_DIR`, `ANV_CM_HELPER`, `force_vk_vendor`,
`INTC_ALT_DRIVER_EXTENSIONS_PATH`, and runs the driver check.

Steam launch options for that game:

```text
/path/to/package/xmx-launch.sh %command%
```

`xmx-launch.sh` only imports `XMX_CONF` and runs the game. Source:
`xmx-launch.sh` (6 lines).

### `switch-driver.sh`

```bash
tools/switch-driver.sh
tools/switch-driver.sh 26.3
```

Without an argument it lists the drivers in `lib/mesa-*/` and marks the default
(`*` according to `lib/active`). With an argument it changes the default; games
already running keep their driver, new ones use the new one, without re-login.
Per game, `MESA=<version>` in launch options wins over the default. Source:
`tools/switch-driver.sh`. Note: the package README documents
`MESA=26.1` / `MESA=26.3` as examples; use the values your copy lists, not
those literals if they do not exist.

## 5. Rollback

Sources: `disable.sh`, `uninstall.sh`, `tools/switch-driver.sh`,
`install.sh` (keeps `.stock`), and the backup
`~/xess-xmx/backup-20261113/` (hashes, shims, units, env).

- Per game (reverts `enable.sh`):

```bash
XMX_APPID=<id> ./disable.sh
```

Restores `igdext64.dll.stock` over `igdext64.dll` (or removes the shim if the
prefix had no stock), removes its own `ControlLib.dll`, removes the `XESS-XMX`
block from `XMX_CONF` and deletes `drive_c/igdext_kernels`.

- Driver change: `tools/switch-driver.sh <version>` or reinstall the old
  package. `docs/compatibility.md` records the rollback tested at the design
  level: `tools/switch-driver.sh 26.3.0-rc1` or reinstall the previous
  package; the 13 prefix shims are backed up.
- Full system-wide: `./uninstall.sh`. Restores each `igdext64.dll`
  from its `.stock`, removes the Proton hook, the environment and the watcher,
  and asks for a reboot or re-login. Compiled kernels stay in
  `~/.cache/xess-xmx` (deleting that folder removes them).
- Backup taken before testing the candidate: `~/xess-xmx/backup-20261113/`
  with `hashes.txt`, `shims/`, `units/`, `env/50-xess-xmx.conf`. If something does
  not add up after installing the candidate, that backup is the comparison
  reference. No automatic restore command from the backup is documented here,
  because none of the scripts read implement it; restoration is `disable.sh` /
  `uninstall.sh` / reinstalling the old package.

## 6. Game test

Sources: `docs/xmx412-model-selection.md` §5, `docs/cabinet-shim.md` §6,
`run-full-test.sh`, `docs/compatibility.md`.

1. With the game closed, copy next to the executable (the exact path depends on
   your installation; the runbook uses the Spider-Man directory):
   the mod's `amd_fidelityfx_upscaler_dx12.dll`, the official 4.1.2
   `fsr-original.dll`, and the `cabinet.dll` built by
   `tools/build_cabinet_shim.py`. Do not copy `cabinet.dll` into any prefix's
   `system32`.
1b. Also copy `<package>/igdext64.dll` next to the mod. The Spider-Man prefix
    already had it in the DriverStore, but a new prefix does not, and without
    the shim the mod aborts with `Intel extension igdext64.dll with required DX12
    exports was not found beside DLL, system search, or DriverStore` and shows
    magenta. Without the shim it also cannot query the GPU and chooses
    `DG2 SIMD8` kernels instead of `Xe2 SIMD16`.
2. Launch with the native Cabinet override plus the run's environment:

```bash
export WINEDLLOVERRIDES="cabinet=n,b"
```

3. Per-process variables to choose the model (Steam: `VAR=1 %command%`).
   Source: `docs/xmx412-model-selection.md` §5.2 and `run-full-test.sh`:

```text
FSR4_XMX_INT8=1            # 4.1.2X (INT8), PROVIDER_INDEX=8
FSR4_XMX_LITE=1            # 4.1.2X Lite, PROVIDER_INDEX=12
(none)                     # 4.0.2X stock, depending on the game
```

Do not set both at once; INT8 wins if there are weights. Do not set
`FSR4_XMX_DLSS*` during the FSR4 test (they take priority).
To also force the visible label:

```text
FSR4_XMX_PROVIDER_INDEX=8    # label 4.1.2X
FSR4_XMX_PROVIDER_INDEX=12   # label 4.1.2X Lite
```

Without this, the overlay may keep showing `4.0.2` even though the log confirms
INT8/Lite. The log decides, not the overlay.

4. Capturing logs with `run-full-test.sh` (in the trace run):

```bash
./run-full-test.sh int8 <tag> --proton-log
./run-full-test.sh lite <tag> --proton-log
./run-full-test.sh stock <tag>
```

Flags read from the script: `--proton-log` (also captures the mod's own log
with `INT8 model:` / `Lite model:`), `--fresh-kernels`,
`--no-mango`. The script sets per process `VK_DRIVER_FILES` to the candidate
ICD, `ANV_CM_HELPER`, `ANV_CM_KERNEL_DIR`, `VKD3D_DISABLE_EXTENSIONS`,
`ANV_CM_DEBUG=1`, `WINEDLLOVERRIDES`, `FSR4_XMX_LITE_DLL` (Windows path
`Z:...` to the run's `fsr-original.dll`), `FSR_ENV` and
`FSR4_XMX_PROVIDER_INDEX`, and when the game closes it generates per run
`vkd3d.log`, `fingerprint.txt`, `summary.txt` and, with `--proton-log`,
`steam-proton.log` and `mod-model.txt`.

5. How to read the result:

- `summary.txt`: requested model, `injected`, `sampler-heap-ok`, fingerprint
  counts. The key downstream line is
  `sampler descriptor table after the surfaces (sampler heap found)`.
- `fingerprint.txt`: compare with another run via
  `tools/xmx_kernel_set.py diff`. Source: footer of `run-full-test.sh`.
- `mod-model.txt` (only with `--proton-log`): counts of `INT8 model:`,
  `Lite model:`, `without verified`, `PROVIDER_INDEX`. The authoritative model
  lines are in `docs/xmx412-model-selection.md` §5.3:

```text
[FSR4 XMX] INT8 model: preset weights from Z:\...\fsr-original.dll, ...
[FSR4 XMX] Lite model: preset weights from Z:\...\fsr-original.dll, ...
```

If `Lite/INT8 model requested without verified fsr-original.dll
weights.` appears, the weights are missing or the file is not the official 4.1.2
(checklist in §5.5 of the model selection doc).

### Preparing a manual trace

The full steps are in [spiderman-trace-runbook.md](spiderman-trace-runbook.md),
and the capture contract in
[pre-trace-capture-spec.md](pre-trace-capture-spec.md). The order is:

1. Re-verify the starting hashes with runbook §1: mod `fadbcb50…`, IR
   `49e069fd…`, envelope `ce372719…`. If any differs, stop.
2. Generate the run with `tools/prepare_trace_capture_412.py` (runbook §3) and
   leave the reserved `wineprefix-reserved-not-initialized` empty.
3. Back up the game's current `amd_fidelityfx_upscaler_dx12.dll` outside the
   game before copying the mod in. That file is `d0dcccc7…`, not the mod.
4. Fill `runs/<id>/evidence/versions/` with the 12 rows of runbook §6, then save
   the trace log and the pre/post bytes listed in spec §4.

The trace is input evidence, not an oracle. No row replaces the output oracle,
and `S_OK`, the overlay or magenta prove nothing.

## 7. Limits

- Tested only on Marvel's Spider-Man Remastered, one documented functional
  session (`docs/compatibility.md`). There is no evidence
  for other games or prefixes.
- Verified at the kernel level (injection, sampler heap, 11 FSR4 resources,
  0 device lost), not at the pixel level. No independent oracle or deterministic
  readback of the PRE. An S_OK, the overlay or shader creation do not
  certify the model.
- Do not redistribute third-party binaries: nitec's mod, the official AMD 4.1.2
  DLL, Valve's Proton, the game. Third-party paths:
  `artifacts/original/` (git-ignored), `upstream/` (ignored checkouts),
  `~/.cache/xess-xmx/kernels`.
- Undocumented items are declared: the read sources contain no automatic
  restore command from `backup-20261113/` (reference only), no pinned hash of the
  official `fsr-original.dll` 4.1.2 in this repo, and no verified recipe for
  games other than Spider-Man.
