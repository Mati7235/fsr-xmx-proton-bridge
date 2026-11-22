# Spider-Man Remastered: manual trace runbook with the XMX 4.1.2 mod

Phase 1, CPU-only for the preparer; **manual execution by the user** for the
trace. This document does not authorize anything by itself: each execution step
is carried out by the user by hand, in a disposable prefix, without touching Steam,
real prefixes, drivers or services.

State pinned by `tools/prepare_trace_capture_412.py` (verified by
SHA-256 on 2026-11-12):

| Artifact | SHA-256 |
|---|---|
| DLL `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` | `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| PRE Xe2 `native_1080` IR (pack 40102, record 0, offset 0, 358776 B) | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| PRE Xe2 `native_1080` envelope (358873 B, also `analysis/offline-pre-412/module-0000.cmspv`) | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| Packs 40101–40106 raw | see `profiles/xmx412-pins.json` (1977 CM envelopes in total) |

Capture contract: `docs/pre-trace-capture-spec.md` (what to record from the
PRE `native_1080` dispatch); version checklist:
`docs/pre-trace-version-checklist.md`.

## 0. Starting paths and versions (read-only)

`~` stands for the home folder; the Spider-Man folder is wherever Steam or
the user installed it, and the Proton folder shown is the one the run used.

- Game: `~/Juegos/Spiderman/Marvel's Spider-Man Remastered/`,
  executable `Spider-Man.exe` (121,901,008 B observed; re-register on the day
  of the trace, since Steam may update it).
- OptiScaler already installed: `dxgi.dll` + `D3D12_OptiScaler/D3D12Core.dll` +
  `OptiScaler.ini`. The game's current `amd_fidelityfx_upscaler_dx12.dll`
  (`d0dcccc7…`) is **not** the mod.
- Proton: `~/.steam/root/steamapps/common/Proton - Experimental`
  (`version`: `experimental-11.0-20261105c`; launcher `proton`, usage
  `proton run <exe>`).
- Explicit ICD: `/usr/share/vulkan/icd.d/intel_icd.x86_64.json`
  (`api_version 1.4.363`, library `/usr/lib/libvulkan_intel.so`).
- RenderDoc available: `renderdoccmd` / `qrenderdoc` v1.46 (Vulkan support
  compiled in).

## 1. Re-verify starting hashes (read-only, run nothing else)

```bash
cd ~/Proyectos/fsr-xmx-proton-bridge
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
# esperado: fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732
python3 -c "
import sys; sys.path.insert(0,'tools')
import parse_cm_payloads
from pathlib import Path
data = Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes()
r = parse_cm_payloads.parse(data)[0]
print(r)
assert r['ir_sha256'] == '49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568'
assert r['envelope_sha256'] == 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab'
print('PRE native_1080 OK')
"
sha256sum "~/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe"
cat "~/.steam/root/steamapps/common/Proton - Experimental/version"
sha256sum /usr/share/vulkan/icd.d/intel_icd.x86_64.json /usr/lib/libvulkan_intel.so
```

If any hash of the mod differs: stop, do not continue.

## 2. Place the mod DLL (manual action by the user)

Reading the game's `OptiScaler.ini` (verified by direct reading):

- `[Upscalers] Dx12Upscaler = xess` (line 14): OptiScaler intercepts the
  game's DX12 through the XeSS path.
- `[Libraries] FfxDx12SRPath = auto` (lines 810-811, comment
  `amd_fidelityfx_upscaler_dx12.dll`): on `auto`, OptiScaler resolves that
  DLL from the game directory.

Therefore, the exact expected path of the mod is:

```text
~/Juegos/Spiderman/Marvel's Spider-Man Remastered/amd_fidelityfx_upscaler_dx12.dll
```

Manual steps (the user, never automated):

1. Back up the current file outside the game (the current one is `d0dcccc7…`,
   not the mod; do not touch `.optiscaler-backup/`).
2. Copy `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll` over it.
3. Re-verify: `sha256sum` must give `fadbcb50…`.
4. Before capturing, confirm in the OptiScaler overlay/menu (Insert) and
   in its log which backend actually serves the upscale: with
   `Dx12Upscaler=xess`, if the active path is pure XeSS, the PRE trace does not
   apply; only proceed if the FSR/XMX 4.1.2 backend is in use. Record
   what was observed in `evidence/versions/` as a note, without reinterpreting it.

## 3. Scaffold the preparation and the run (CPU-only, run nothing)

```bash
cd ~/Proyectos/fsr-xmx-proton-bridge
python3 tools/prepare_trace_capture_412.py
# crea build/trace-412-<fecha>-<id>/ con manifest.json + run-manual.py
python3 build/trace-412-<fecha>-<id>/run-manual.py --run-trace \
  --icd-manifest /usr/share/vulkan/icd.d/intel_icd.x86_64.json
# crea runs/<run-id>/ con wineprefix-reserved-not-initialized VACÍO (0700)
# y evidence/{env.json,pinned-hashes.json,planned-command.txt,icd-manifest.json,versions/}
```

The launcher requires **both** flags and never initializes the prefix nor spawns
child processes. The reserved `WINEPREFIX` is only initialized inside the
authorized manual run, never before.

## 4. Exact Proton command (manual, once authorized)

Only with the variables from `evidence/env.json` (environment replaced, not
inherited), plus the log redirection outside the game/Steam:

```bash
env -i \
  PATH=/usr/bin:/bin LANG=C LC_ALL=C \
  HOME='<run>/home' XDG_CACHE_HOME='<run>/cache' XDG_CONFIG_HOME='<run>/config' \
  XDG_DATA_HOME='<run>/data' XDG_STATE_HOME='<run>/state' TMPDIR='<run>/tmp' \
  WINEPREFIX='<run>/wineprefix-reserved-not-initialized' \
  VK_DRIVER_FILES=/usr/share/vulkan/icd.d/intel_icd.x86_64.json \
  VK_ICD_FILENAMES=/usr/share/vulkan/icd.d/intel_icd.x86_64.json \
  VKD3D_DEBUG=trace \
  "~/.steam/root/steamapps/common/Proton - Experimental/proton" run \
  "~/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe" \
  > '<run>/evidence/vkd3d-trace.log' 2>&1
```

Notes:

- `VKD3D_DEBUG=trace` is already set in `evidence/env.json`; it is the
  API capture variable of VKD3D-Proton (massive textual log, not a frame).
- In the game, look for a scene with an upscale input of 1920×1080
  (PRE grid `native_1080`); note the real internal resolution observed instead
  of assuming it.
- Expected PCI device on B580: `8086:e20b`; record the real ID from the log.

## 5. Frame capture with RenderDoc (manual, optional complement)

The `VKD3D_DEBUG=trace` log gives the API sequence; the frame with descriptors
is captured with RenderDoc on the Vulkan side:

```bash
renderdoccmd capture --capturefile '<run>/evidence/spiderman-412.rdc' \
  env -i <mismas variables de evidence/env.json> \
  "~/.steam/root/steamapps/common/Proton - Experimental/proton" run \
  "~/Juegos/Spiderman/Marvel's Spider-Man Remastered/Spider-Man.exe"
```

Open the `.rdc` with `qrenderdoc` (CPU, without the game's GPU) and locate the
event `Dispatch(120, 540, 1)`. Any extra layer variable
(`VK_INSTANCE_LAYERS`, …) is a documented deviation from
`evidence/env.json`, not part of the pinned environment.

What to look for in the frame (criteria of spec §2–§8):

- A single `Dispatch` with grid `(120, 540, 1)` for `w=1920, h=1080`
  (formula `x=(w+15)>>4; x+=x&1; y=h>>1`); modes 2–3 do not emit PRE,
  4 → `(1,1,1)`, 5 → `(x,1,1)`, 6 → `(x,0x44,1)`.
- 11 effective descriptor tables (roots 1–11: u0, u1, t0–t6, t7, t8)
  + sampler in root 12; `SetComputeRoot32BitConstant(root 0) = 0`.
- Formats: UAV/SRV `R8_UINT` (`0x3E`); arg 9 SRV `0x1688`, `0x840`
  (2,112 B); arg 10 SRV `0x1688`, `0x80` (128 B); arg 0 UAV
  `NumElements = Width` with `GetDesc.Dimension == 1` and
  `Width >= 8.294.400`.
- Effective `Width` of arg 0 (sizes the UAV; do not assume the exact
  assignment), `GetDesc` per slot, aliasing between slots, states/transitions
  `ResourceBarrier` (`0x40`/`0x400`/`0x800`).
- Bytes before **and** after the dispatch: arg 10 header (128 B), arg 9 (2,112 B),
  float4 register at `base+{0,16}` and the OWORD plane of arg 0
  (`índice = wg_y*960 + wg_x*8`); a full dump is recommended, without initializing
  anything as an empty buffer.

## 6. Fill `evidence/versions/` (one row per item, value + source)

Row-by-row guide of the checklist (all commands are read-only; save each output
with the indicated name):

| # | File | Read-only command |
|---|---|---|
| 1 | `exe.sha256` | `sha256sum "<juego>/Spider-Man.exe"` + size in bytes |
| 2 | `exe.version.txt` | PE version resource (FileVersion/ProductVersion), read without executing |
| 3 | `proton.version.txt` | `cat "<proton>/version"` + path of the Proton directory |
| 4 | `vkd3d.*.sha256` | `sha256sum <proton>/files/lib/wine/x86_64-windows/{d3d12,dxgi}.dll <proton>/files/lib/vkd3d/x86_64-windows/*.dll` of the binaries confirmed by the load log |
| 5 | `vkd3d.version.txt` | version string of the VKD3D build in use (version file or log), without assuming a number |
| 6 | `wine.version.txt` | `"<proton>/files/bin/wine" --version` (outside Steam, without initializing prefixes) |
| 7 | copy of the manifest | `evidence/icd-manifest.json` is already left by the launcher; add `sha256sum` of the manifest used |
| 8 | `icd.library.sha256` | `sha256sum /usr/lib/libvulkan_intel.so` + `api_version` of the manifest |
| 9 | `dll.sha256` | `sha256sum "<juego>/amd_fidelityfx_upscaler_dx12.dll"` → must give `fadbcb50…` (the printed checklist still shows the old hash: note the deviation explicitly) |
| 10 | `pre-412.hashes.txt` | IR `49e069fd…` + envelope `ce372719…` re-verified with the command in §1 (no compiled 4.1.2 zebin exists: `REQUIRED-TBD`, the runtime resolves from pack 40102 of the DLL) |
| 11 | `device.pci.txt` | real PCI ID from the device selection log (`8086:e20b` expected on B580) |
| 12 | `host.context.txt` | `uname -r`, CachyOS/Mesa version (context only) |

Rules: if an item does not apply, note it explicitly; do not reuse
values from another machine or run; no row replaces the output
oracle nor certifies functional correctness.
