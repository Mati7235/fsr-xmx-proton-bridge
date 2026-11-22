# Design of the `fsr-xmx` installer: plug-and-play FSR 4 XMX on Intel Arc

Design document, not code. Current state: everything is done by hand with
per-game launchers (`analysis/antilag2-cp77/run.sh`, `hosts/matias-pc` in the
config repo) and with the `xess-xmx-linux` package enabled per process. The
goal is that anyone with an Intel Arc / Xe2 on Arch (and, if it comes for
free, on any Linux) can get the same result with a script that downloads
verified precompiled binaries, without reading the repo and without an AI
agent. No `sudo` in any step: everything lives under the user's home.

Decisions already made by the user that this design respects:

- The binaries we build (patched Mesa ANV, our vkd3d-proton) are distributed
  PRECOMPILED, built in CI on an old glibc base so they run on Arch/Ubuntu/
  Fedora/etc. The script downloads them and verifies them with `SHA256SUMS`.
  Nothing is built on the user's machine.
- v1 features: FSR 4 scaling on XMX (INT8 and Lite models), XeFG (Intel frame
  generation via the `igdext64` shim) and ANR FG (Apex Neural Rendering; it
  needs our vkd3d-proton with `VKD3D_KEEP_COOPMAT_EXTENSION=1`). Anti-Lag 2 is
  out of scope: the game does not call the function in Cyberpunk, and Proton's
  `amdxc64.dll` is Wine's own module, not the real library (see the
  `cp2077-xmx` doc in the config repo).

## 1. Inventory of the setup that works today (2026-11-22)

Everything below was read from real files, not from memory.

- Active package: `~/xess-xmx/xess-xmx-linux-20261120` (262 MB; `lib`
  31 MB, `igc` 228 MB, `kernels` empty because they are built on use).
  - Upstream: `HHH…/xess-xmx-linux` tag `20261120`, commit `f06dc39`.
    Local checkout in `upstream/xess-xmx-linux`, same revision.
  - Mesa 26.3.1, official tarball with a pinned sha256 in `MANIFEST.txt`.
    Upstream patches `patches/mesa-26.3/0001,0002,0003,0005,0006,0007` plus
    our own `0004-anv-anti-lag.patch` (in this repo:
    `patches/0004-anv-anti-lag.patch`).
  - `run/intel_icd.json` points to `<paquete>/lib/libvulkan_intel.so`
    (forwarder built from `icd/xmx-icd.c`; the real driver is in
    `lib/mesa-26.3.1/`, sha `24e931c6…`). The ICD declares API 1.4.348.
  - `igdext64.dll` from the package: 862,208 bytes, sha256 `678a1a15…049a3`.
  - Runtime build helper: `tools/cm-compile.sh` (POSIX shell only, runs the
    ocloc from the `igc/` bundle). Scripts: `install.sh`,
    `enable.sh`, `disable.sh`, `uninstall.sh`, `xmx-launch.sh`,
    `xmx-stock.sh`, `tools/switch-driver.sh`, `tools/session-check.sh`,
    `tools/proton-hook.py`, `tools/steam-libraries.sh`, `tools/fsr-fg.sh`.
  - Our repo adds to that package the patches `0001` (CMK3 injection),
    `0002`/`0003` (shim context), `0004` (Anti-Lag 2) and `0005`
    (vkd3d keep-coopmat, see below). `0004` is already integrated in
    package 20261120 (the `MANIFEST.txt` says so).
- Current launcher: `analysis/antilag2-cp77/run.sh` (live copy in the config
  repo as `hosts/matias-pc/xess-xmx/cp2077/run.sh`). Variables it sets per
  process, and why:
  - `STEAM_COMPAT_{CLIENT_INSTALL_PATH,DATA_PATH,APP_ID}` + `SteamAppId`
    / `SteamGameId`: a disposable `compatdata` prefix, never the production
    one (appid 1091500).
  - `VK_DRIVER_FILES=<paquete>/run/intel_icd.json`: uses our ANV only in this
    process, without touching the session.
  - `VK_LOADER_LAYERS_DISABLE='*'`: no layer (MangoHUD, etc.) gets in the
    middle of the CM path.
  - `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer,VK_EXT_descriptor_heap,VK_KHR_present_wait2`:
    the reference value comes from `tools/steam-libraries.sh`
    (`XMX_VKD3D_OFF`); without it the patched driver fails.
  - `ANV_CM_HELPER=<paquete>/tools/cm-compile.sh` + `ANV_CM_KERNEL_DIR`
    (kernel folder per run) + `ANV_CM_DEBUG=1`: runtime compilation of CM
    kernels and injection log.
  - `WINEDLLOVERRIDES="dxgi,cabinet=n,b"`: OptiScaler (`dxgi.dll`) and
    our `cabinet.dll` as native.
  - `PROTON_LOG=1`, `PROTON_LOG_DIR`, `VKD3D_DEBUG=warn` (`trace` only
    with `--trace`): diagnostics.
  - Optional: `IGDEXT_XELL_CAP=off` (`--no-xell`, turns XeLL off and with it
    XeFG), `XESS_FG=N` (`--xess-fg`, the game's native FG 2–8; not used today
    because it fights with XeFG), `force_vk_vendor=4098` (`--spoof-amd`,
    only to test Anti-Lag; breaks XeSS/XMX), `WINEDEBUG=+amdxc`,
    `PROTON_ENABLE_WAYLAND=1` (`--wayland`, this is what is always used here:
    it is what unlocked the cursor), optional gamescope.
  - The doctor `xmx-doctor.sh <perfil> [--fix]` (config repo,
    `games/cp2077.conf`) checks without touching: sha256 equality of the three
    `igdext64.dll` files (package/game/prefix), the `[Spoofing]` and
    `[FrameGen]` sections of the ini, `compile_failed.txt`, the value of
    `VKD3D_DISABLE_EXTENSIONS`, whether the game is open, and whether the
    session environment points to the old package. `--fix` corrects with a
    `.bak-<fecha>` backup and refuses to touch the ini while the game is open.
- Game folder (read-only):
  `/home/matias/Juegos/steamapps/common/Cyberpunk 2077/bin/x64`.
  Our files or mod files (the rest belongs to the game):
  - `amd_fidelityfx_upscaler_dx12.dll` (FSR4 XMX 4.1.2 mod):
    45,558,272 bytes, sha256 `fadbcb50…b37f44732`.
  - `fsr-original.dll` (official AMD FSR 4.1.2, provides the INT8/Lite
    weights): 57,664,272 bytes, sha256 `aad4fccc…0148cc65`.
  - `igdext64.dll`: 862,208 bytes, sha256 `678a1a15…049a3`, IDENTICAL to the
    one in the package (the doctor made them match).
  - `cabinet.dll`: 69,632 bytes, sha256 `951a13e3…fa65f9f74`,
    built by `tools/build_cabinet_shim.py` (game-local shim for the LZMS
    packs of the mod; never in `system32`).
  - `dxgi.dll` (OptiScaler v10 pre-release): 28,150,784 bytes.
  - `OptiScaler/` with `custom/Apex Neural Rendering FG/` and
    `D3D12_OptiScaler/`; `OptiScaler.ini` (1915 lines, CRLF) with what
    matters: `Dx12Upscaler = ffx`, `FGInput=nvngxfg`, `FGOutput = XeFG`,
    `FGNvngxReplacement=Apex Neural Rendering FG`, `Fsr4GpuSupport/Preset/Model = auto`,
    `[Spoofing]` with `SpoofedVendorId = 0x8086`,
    `SpoofedDeviceId = 0xE20B`, `Dxgi = false`.
- `artifacts/original/` (git-ignored, local only): `amd_fidelityfx_upscaler_dx12_xmx.7z`
  (4.0.2x), `amd_fidelityfx_upscaler_dx12_xmx412.7z` (4.1.2),
  `nvngx_dlssd_xmx.7z`, `OptiScaler_v10.0.0-pre_20261022.7z`,
  `FidelityFX-SDK-2.4.0.zip`, `anr-FG-V.B20/` (full 11.7 MB + addon
  4.1 MB, both verified against `SHA256SUMS-upstream.txt`),
  `cp2077-bin-x64/` (copies with `SOURCE.txt` + `SHA256SUMS` of the
  game's `amd_fidelityfx_{framegeneration,loader}_dx12.dll`).
  There is no global `SOURCE.txt`; provenance lives in those files and in
  `docs/compatibility.md`. Licenses: see §2, nothing is redistributed.
- Tested GPU: Intel Battlemage G21 (Arc B580, PCI `8086:e20b`), kernel
  `xe`/`i915` driver. Base of the compat tool: **GE-Proton**
  (user decision 2026-11-22; GE carries amdxc/FSR4-MLFG patches and the env
  vars `FSR4_UPGRADE`/`MLFG_UPGRADE` useful for the FG work, and it ships
  versioned releases that are easy to pin; Proton Experimental
  stays as the manual fallback). Current pin: `GE-Proton11-12`
  (2026-11-03; vkd3d-proton `8293130e`, post-`v3.1`). `compatibilitytools.d`
  may also contain other installed Protons.

## 2. Component list: ours vs third-party

### Ours (buildable from this repo + upstreams, redistributable with source)

| Piece | Source | License | How it is distributed |
|---|---|---|---|
| Patched Mesa ANV (`libvulkan_intel.so` + forwarder + `run/intel_icd.json`) | Official Mesa + `patches/mesa-26.3/*` from xess-xmx-linux + our `0001`–`0004` | MIT | precompiled in CI + source/patch tarball with a source offer |
| Shim `igdext64.dll` (+ `ControlLib.dll`) | `shim/` from xess-xmx-linux + our `0002`/`0003` | MIT | precompiled in CI |
| Our `d3d12.dll` + `d3d12core.dll` (vkd3d-proton + `0005`) | vkd3d-proton base = the one shipped by the pinned GE-Proton (`8293130e` for GE-Proton11-12) + GE's vkd3d patches + `patches/0005-vkd3d-keep-coopmat-extension(-ge).patch` | LGPL-2.1 | precompiled in CI; see §3 for how they reach the game without redistributing Proton |
| Game-local `cabinet.dll` | `tools/build_cabinet_shim.py` from this repo | MIT (ours) | built in CI with llvm-mingw or by the script; it is our code, no license issue |
| `fsr-xmx` (installer script + `fsr-xmx run` wrapper) | new in this repo | MIT | source code in the repo, obtained with git or as a tarball |

### Third-party (NEVER redistribute binaries; the script downloads them or asks for them)

| Piece | Official origin | License | Strategy |
|---|---|---|---|
| OptiScaler | official releases at `github.com/OptiScalers/OptiScaler` (GPL). Version in use: `v10.0.0-pre_20261022` | GPL | the script downloads the official release from a fixed URL + pinned sha256; it is also fine for the user to supply their own file and the script verifies it |
| ANR FG | official releases at `github.com/apex-compute/ANR`, tag `FG-V.B20`: `anr-fg-V.B20-full.zip` + `anr-fg-V.B20-addon.zip`, verified against their upstream `SHA256SUMS.txt` | whatever their repo says (review in v1; the zip carries its own license) | direct download of the official release + verification against the upstream `SHA256SUMS` (we keep a local reference copy). The `-source` zip (GPL, 133 MB) is not needed |
| Official FSR 4.1.2 (`fsr-original.dll`, INT8/Lite weights) | AMD's official SDK or DLL (today it comes from an installation/game with FSR 4.1.2; the hash in use is `aad4fccc…`) | AMD binary license, not redistributable | THE USER PROVIDES IT. The script accepts it by path or looks for it in known locations, verifies it is the official 4.1.2 (sha256 + size 57,664,272) and copies it next to the mod. We never download it ourselves |
| FSR4 XMX mod (`amd_fidelityfx_upscaler_dx12.dll` 4.1.2 from nitec) | nitec's mod (distributed via NexusMods; no stable direct public URL). Hash in use `fadbcb50…b37f44732`, 45,558,272 bytes | the author's, not redistributable | THE USER PROVIDES IT (downloads it from NexusMods with their account). The script verifies hash/size and places it. Plan B if the author publishes a direct URL: download + verification, with their permission |
| Intel XeSS FG libs (`libxess_fg.dll`, `libxell.dll`, `libxess.dll`) | `github.com/intel/xess` via `tools/get-xess.sh` from the package | Intel Simplified Software License, not redistributable | the installer reuses `get-xess.sh` on the user's machine (download from Intel → user; we only supply the script) |
| Signed AMD FSR DLLs (loader/upscaler/FG from SDK 2.4.0) | `GPUOpen-LibrariesAndSDKs/FidelityFX-SDK` via `tools/get-ffx.sh` | AMD binary license | same: `get-ffx.sh` on the user's machine |
| IGC/ocloc (`igc/`, 228 MB) | Intel (provided by `tools/get-igc.sh`) | MIT but heavy and per-platform | `get-igc.sh` on the user's machine; NOT in our release (package 20261120 copied it from the previous one, it did not even rebuild it) |
| Proton / Steam Runtime | Valve | their licenses | never touched or redistributed; see §3 |

## 3. Architecture

### Installation root

Everything under the home, no sudo, no system-wide:

```text
~/.local/share/fsr-xmx/
  release/            # lo descargado y verificado (Mesa precompilado, vkd3d DLLs, cabinet, shims)
  profiles/<juego>/   # un perfil por juego: env, hashes esperados, ini deseado, backups
  backups/            # copias .bak-<fecha> de todo lo que se pisa en carpetas de juegos
  proton/             # la “compat tool” generada (ver abajo)
  kernels -> ~/.cache/fsr-xmx/kernels   # caché de kernels CM (respeta XDG)
```

`~/.local/bin/fsr-xmx` (or `~/.local/share/fsr-xmx/bin/fsr-xmx` with a symlink):
the only executable the user touches.

Nothing in `~/.config/environment.d`, nothing in user systemd, nothing in
`/etc`, nothing in the installed Steam. Driver selection is PER PROCESS
(`VK_DRIVER_FILES`), never session-wide. This is a deliberate decision
against upstream's `install.sh` (which writes `50-xess-xmx.conf` and changes
the whole session): ours cannot leave the user without a GPU if the driver
fails, because if the ICD does not load the game simply does not start and
the rest of the desktop stays intact. Upstream's `session-check.sh` exists
precisely because system-wide mode can break the session; we avoid that
class of failure by construction.

### How each game is launched: wrapper, not hand-typed launch options

The user pastes ONE line into Steam's launch options:

```text
~/.local/bin/fsr-xmx run --profile cp2077 %command%
```

`fsr-xmx run` sets the same variables that `run.sh` sets today
(`VK_DRIVER_FILES` pointing to the ICD from our release, `VK_LOADER_LAYERS_DISABLE`,
`VKD3D_DISABLE_EXTENSIONS`, `ANV_CM_*`, `WINEDLLOVERRIDES`,
`VKD3D_KEEP_COOPMAT_EXTENSION=1` when the profile asks for ANR, plus the
`FSR4_XMX_*` of the model) and then `exec`s the command. No intermediate
environment files that rot (upstream's `XMX_CONF` is a file that another
process can edit at the wrong time; per-process variables cannot).

To run outside Steam (or with a standalone Proton) the wrapper accepts
`fsr-xmx run --proton <ruta> --exe <ruta> -- ...`, which is what `run.sh`
does by hand today.

### Our vkd3d-proton without redistributing Valve's Proton

Key fact (read from the `proton` script in `BUILD.md`): every launch
**unconditionally** re-copies `d3d12/d3d12core.dll` from
`<Proton>/files/.../vkd3d-proton/` into the prefix's `system32`. That is why
replacing DLLs inside the prefix does NOT work: it is lost on the next
launch. And copying loose DLLs into the game folder is fragile (it depends on
Wine's search order, not verified).

Options evaluated:

1. **Local copy of the user's GE-Proton as a Steam compatibility tool
   (CHOSEN, user decision 2026-11-22).** The installer copies (reflink on
   btrfs, almost free) `GE-Proton11-12` (or whichever pin the release
   states) from `~/.local/share/Steam/compatibilitytools.d/` to
   `~/.local/share/Steam/compatibilitytools.d/FSR-XMX-Proton/`, and replaces
   inside it only the two files
   `files/lib/wine/vkd3d-proton/x86_64-windows/{d3d12,d3d12core}.dll`
   with ours (with a `.stock` backup). It adds a minimal `compatibilitytool.vdf`
   so Steam lists it as "FSR XMX Proton". The user picks that tool in the
   game's Properties → Compatibility. Nothing of the original Proton is
   touched; deleting our folder reverts everything. Cost: ~1 GB logical per
   copy, but on btrfs with reflink only the changed blocks take space (the
   two DLLs, ~5 MB). On filesystems without reflink it is a full copy: the
   installer warns about the size before doing it.
2. Per-game copy outside Steam (`$release/proton-vkd3d-test` as in
   `BUILD.md`): useful for testing, but Steam does not use it for library
   games; it is only valid as a manual `--proton` mode. Kept as a fallback,
   not as the main path.
3. `WINEDLLPATH` with our DLLs: search order not confirmed against
   `system32`; discarded until there is proof.
4. Patching the installed Proton: modifies third-party software, is lost on
   every Proton update, and impossible for the user to audit. Discarded.

Note: the re-copy-on-every-launch behavior was also verified in the
`proton` script of GE-Proton11-12 (`setup_prefix`: `try_copy` does `remove` +
always copies `d3d12`/`d3d12core.dll` to `system32`/`syswow64` with
`d3d12=n` overrides). The same applies: replacing DLLs in the prefix does not work.

Known inherited risk: forcing the extension broke `vkCreateDevice` on an
NVIDIA driver (vkd3d-proton#3076); that is why `0005` is opt-in via an env
var and the wrapper only exports it in ANR profiles.

### How the DLLs reach the prefix and the game

- vkd3d: the copied Proton carries them; the prefix receives them on every
  launch, as always. Nothing to do per game.
- `igdext64.dll`: the wrapper verifies sha256 in three places (package /
  game folder / prefix driver store), as `xmx-doctor.sh` does today, and
  `enable` makes them match with a backup. No systemd watcher is installed
  (upstream does install one; we prefer verifying on every `run` and in
  `doctor`: fewer moving parts, same effect).
- Files in the game folder (XMX mod, `fsr-original.dll`,
  `cabinet.dll`, OptiScaler, ANR): `fsr-xmx enable` puts them there with a
  backup and hash verification; `disable` removes them and restores.

## 4. CLI spec

```text
fsr-xmx install [--proton ge] [--with-anr] [--with-xess-fg]
fsr-xmx doctor [--profile <juego>]
fsr-xmx enable <dir-juego> [--fsr4 int8|lite] [--fg xefg|anr|off]
fsr-xmx disable <dir-juego>
fsr-xmx uninstall [--keep-kernels]
fsr-xmx update
fsr-xmx run --profile <juego> [--] <comando...>
```

What each one does (all idempotent: running twice leaves the same result; everything
that overwrites a user file leaves a `.bak-<fecha>`):

- `install`: creates the tree from §3; downloads the precompiled release
  (Mesa+shims+cabinet+vkd3d DLLs) and verifies `SHA256SUMS`; runs
  `get-igc.sh`/`get-xess.sh`/`get-ffx.sh` (direct Intel/AMD downloads to the
  user); generates the compatibility tool of §3 from the pinned GE-Proton;
  installs the symlink in `~/.local/bin` (creates the dir if missing; if it is
  not in `PATH`, it says so). Writes `release/MANIFEST` with versions and hashes.
  It does not touch Steam, prefixes or games.
- `doctor`: read-only (exits 1 if there are problems). Checks: Intel GPU with
  PCI `8086:*` and the `xe`/`i915` driver loaded; Vulkan loader present
  (`vulkaninfo` or `libvulkan.so.1`); native Steam vs Flatpak (Flatpak: cannot
  see `~/.local/share`, in v1 it only warns and points to sandbox paths);
  release downloaded and hashes OK; compatibility tool present and its two
  DLLs with our hash; per profile: `igdext64` identical in the three
  places, `OptiScaler.ini` with the expected sections, mod and
  `fsr-original.dll` with the correct hash, `compile_failed.txt` (warns,
  does not delete). It is today's `xmx-doctor.sh` promoted to a subcommand, with the
  reference values read from the release (not hardcoded).
- `enable <dir-juego>`: detects the game (Cyberpunk first; Steam appid
  by proximity if the dir is under `steamapps/common`, otherwise asks for
  `--appid` for the production prefix); verifies hashes of whatever is already
  there; copies mod/shims/OptiScaler/ANR with a backup; writes or adjusts
  `OptiScaler.ini` by section (never by line number; respects CRLF;
  refuses when the game is open, detected with `pgrep -af <exe>`);
  `--fsr4 int8|lite` chooses the env `FSR4_XMX_INT8=1` / `FSR4_XMX_LITE=1`
  of the profile (`stock` = none, only if the game ships its own 4.0.2);
  `--fg xefg|anr|off` chooses `FGOutput` + `FGNvngxReplacement` and whether
  the profile exports `VKD3D_KEEP_COOPMAT_EXTENSION=1`; prints the Steam line
  to paste and the verification command (`doctor --profile`).
- `disable <dir-juego>`: removes what `enable` put there (mod, weights, cabinet,
  OptiScaler, ANR, game-local `igdext64` if there was no stock one) and restores
  each `.bak`; archives the profile as `<juego>.disabled`.
- `uninstall`: deletes the compatibility tool, the `~/.local/share/fsr-xmx` tree
  (asks; `--keep-kernels` keeps `~/.cache/fsr-xmx`), the symlink and
  the profiles; offers `disable` first for each enabled game. It never
  touches the original Proton, the Steam library or system files.
- `update`: downloads the new release's `SHA256SUMS` + manifest, compares
  version, downloads, verifies and switches the `release/current` symlink;
  keeps the previous release until `doctor` is green with the new one
  (rollback = switch the symlink back).
- Profiles (`profiles/<juego>.conf`, `KEY=valor` format as today):
  `GAME_NAME`, `GAME_EXE`, `APPID`, `FSR4=int8|lite|stock`,
  `FG=xefg|anr|off`, plus what is derived (wrapper env, expected hashes,
  ini adjustments). Cyberpunk 2077 is the reference profile; the format
  supports other games by changing those lines, just as `games/cp2077.conf`
  does today.

Hardware/environment checks (`doctor` and pre-`install`): lspci `8086`
Arc/Battlemage/Xe2 series (PCI ID list in the release, extendable);
`/sys/class/drm/renderD*/device/vendor` with the `xe` driver (accepts the old
`i915` with a warning); Vulkan loader (`command -v vulkaninfo`,
`ldconfig -p | grep libvulkan`); distinguishes native Steam
(`~/.local/share/Steam`) from Flatpak (`~/.var/app/com.valvesoftware.Steam`);
free disk for the compatibility tool (warns if there is no reflink/COW).

## 5. CI and releases

- GitHub Actions jobs (or equivalent forge; publishing needs the user's
  explicit approval, see below):
  1. `mesa`: checkout of official Mesa (pinned version, tarball with sha256)
     + patches `patches/mesa-26.3/*` from xess-xmx-linux (pinned to the tag used)
     + our `0001`/`0004`; build with the `meson OPTS` from
     `rebuild-driver.sh`; artifacts: `libvulkan_intel.so`,
     forwarder `xmx-icd.c`, `intel_icd.json`, `igdext64.dll`,
     `ControlLib.dll`, `layer/` if applicable.
  2. `vkd3d`: checkout of vkd3d-proton at the commit shipped by the pinned GE-Proton (plus its vkd3d patches) + submodules +
     our `0005` (the `-ge` version if a rebase was needed); llvm-mingw cross build; artifacts: `d3d12.dll`,
     `d3d12core.dll` (x86_64; i386 only if the profile needs it).
  3. `shims`: our `cabinet.dll` + packaging.
  4. `release`: puts everything together + signed `SHA256SUMS` + `MANIFEST` (commits,
     tags, tarball hashes, build commands) + source tarball
     (patches + scripts + pinned submodules).
- Build base: image with an OLD glibc so the binary runs everywhere (Steam
  Runtime `sniper` SDK or Ubuntu 22.04, to be decided at the first build;
  criterion: the resulting `libvulkan_intel.so` must load on current Arch and
  on Ubuntu 22.04). Verify with `ldd` and with
  `session-check.sh --dry-run` against the built driver.
- Versioning: `fsr-xmx-<fecha>-<mesa>-<ge>-<vkd3d>` (e.g.
  `20261122-mesa26.3.1-ge11-12-vkd3d8293130e`); `SHA256SUMS` per release;
  `latest` as a symlink/redirect, never as a file without a hash.
- Sources and licenses: the release includes a full source offer
  (vkd3d-proton's LGPL requires it; Mesa/shims' MIT appreciates it):
  tarball with the exact checkouts + patches + build scripts to reproduce the
  binaries. `THIRD_PARTY.md` updated per release.
- Publishing: the precompiled binaries go to the GitHub Releases of this repo,
  but NOT YET (user decision 2026-11-22: publish later, with explicit approval
  at that moment); this design authorizes nothing.

## 6. Language and dependencies

POSIX Bash (`#!/bin/sh`, `cm-compile.sh` style: runs even under `dash`)
for `install`/`run`/`enable`/`doctor`: zero language dependencies, works on any
Arch base. If any part needs data structures (ini parsing by section, the
manifest's JSON), Python 3 stdlib ONLY (no pip, no venv on the user's machine;
Arch always ships Python). No Rust/Go/Node: installing a toolchain to run an
installer contradicts the plug-and-play goal.

Expected dependencies on a base Arch (all in `base`/`extra`, nothing from
AUR): `curl` (downloads; fallback to `wget`), `sha256sum` (coreutils),
`tar`, `unzip` (for ANR/OptiScaler zips; fallback `bsdtar` or Python
stdlib `zipfile` if missing), `7z` ONLY if some required file is still in
`.7z` (prefer that the release uses `.zip`/`.tar.xz`; if nitec's mod arrives
as `.7z`, the script says so and suggests `p7zip` from extra, or accepts the
already-extracted content from the user). `vulkaninfo` (package
`vulkan-tools`) only for `doctor --verbose`; the basic check uses
`ldconfig`/paths without it. `lspci` (`pciutils`) with a fallback to
`/sys/class/drm`. Every dependency check fails with a message that names the
exact package (`pacman -S …`, and the `apt`/`dnf` equivalent if that distro
is detected).

## 7. Risks, unknowns and milestone v1

Risks (with their mitigation in the design):

- The precompiled driver does not load on the user's distro (glibc,
  libLLVM, SPIRV-Tools): mitigated with an old build base + `lib/bundled`
  (already exists upstream) + `doctor` that detects it before touching anything.
- A GE-Proton update changes the base vkd3d and our DLLs fall out of sync:
  the compatibility tool is a frozen copy (it does not follow updates), and
  `update` of the release warns when the pin gets old.
- `NVIDIA`-style broken `vkCreateDevice` with coopmat on another driver: opt-in
  per ANR profile, rollback by removing the env var.
- NexusMods has no direct URL for nitec's mod: the user provides it and the
  script verifies hash/size; hosting/redistribution only with their explicit
  permission (user decision 2026-11-22: nitec's permission has to be requested;
  until then, the user provides it). The design does not depend on automating it.
- Two frame generators at once (XeFG + the game's XESS_FG): the default profile
  does not export `XESS_FG`; documented as in the `cp2077-xmx` doc.

Decisions already made by the user (2026-11-22, previously unknowns):

1. Tool base: GE-Proton (not Proton Experimental). Resolved.
2. Precompiled binaries go to the GitHub Releases of this repo, but nothing
   is published yet. Resolved (pending the moment of publishing).
3. nitec's XMX DLLs: permission has to be requested; until then the user
   provides them and the script verifies them by hash. Open: managing the
   permission.
4. Flatpak Steam: in v1 it only warns. Resolved.

Remaining unknown (for the public README):

1. Can `fsr-original.dll` 4.1.2 be mentioned by exact file name/origin in the
   public README, or are generic instructions better?

Milestone v1 (minimum shippable): `doctor` (read-only) + `install`
(precompiled Mesa + compatibility tool + IGC/XeSS/FFX) + `enable`
Cyberpunk with FSR4 INT8 + `run` wrapper. Done criterion: on a clean Arch
with a B580, without having read the repo, `install → enable → paste line
in Steam → play with FSR 4.1.2X INT8` y `doctor` green. Afterwards: Lite,
XeFG (already works, just package it), ANR (a real run showing the
`Keeping VK_KHR_cooperative_matrix…` in the log is still missing).
