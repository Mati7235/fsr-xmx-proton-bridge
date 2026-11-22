# Compatibility: what works today

This page records what runs today, on which hardware, with which game and Proton build. Static
analysis dates from 2026-10-22, runtime results from 2026-11-12 to 2026-11-14. Anything the tree
or the cited documents cannot confirm is marked unverified.

## Compatibility table

Works means the game rendered a correct scene, the mod's kernels were injected, the sampler heap
was found and the device was not lost. It does not mean bit-exact FSR output, because no oracle
exists.

| Game | Upscaler and model | Resolution | Status | Conditions |
|---|---|---|---|---|
| Marvel's Spider-Man Remastered | FSR 4 XMX, embedded 4.0.2X by default, 4.1.2X INT8 with `FSR4_XMX_INT8=1` | not recorded; the trace targeted 1920x1080 | works | candidate package, game-local `cabinet.dll`, Proton Experimental `experimental-11.0-20261105c` |
| Cyberpunk 2077 2.5 | FSR 4.1.2X INT8 and Lite | 1920x1080 | works | candidate package, `compatdata-cp77` prefix, Custom preset, built-in benchmark |
| SCP: 5K 0.17.6.1 | FSR 4.1.2X INT8, then Lite from the overlay | 1920x1080 | partial | one match, visual confirmation only, EAC untested |
| The mod's DLSS path | DLSS-K, MX, LX, EX, FX | none | untested | packs 40104 to 40106 ship in the DLL, no run |
| Any other title | FSR 4 XMX | none | unverified | no run on record |
| Any 4.1.2 game without the game-local `cabinet.dll` | FSR 4.1.2 mod | any | broken | Wine aborts on `unimplemented function Cabinet.dll.40` |

## The stack the runs used

- Intel Arc B580, BMG G21, `0xE20B`, 12,216 MB, on package `xess-xmx-linux-20261113-cmk3`: Mesa
  26.3.0 (`git-51c31a484c`), fork base `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`, patches 0001
  (CMK3), 0002, 0003 and the mandatory 0005 sampler table.
- Pins, all SHA-256. Mod `amd_fidelityfx_upscaler_dx12.dll` 45,558,272 B:
  `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`.
  Weights `fsr-original.dll` 57,664,272 B:
  `aad4fccccb29084a655f9a4f9f613bd22c8c03fb4a0f8840148cc6543b4ccace`.
  Shim `igdext64.dll` 861,184 B:
  `ce5776bada42a91169cf724bdbf72021d1b7a3ad946ce1c86d003dd640791a85`.
  Cabinet shim 69,632 B:
  `951a13e3164269556609f9e7673a1d0985cdb6a585e9f19fa65f9f747e77348c`, game-local.
- Proton Experimental `experimental-11.0-20261105c` (also `-x86_64`; Cyberpunk did not record its
  build) with its vkd3d-proton. Pinned layout `ef9a02e873715c9e2da0d6db8a236aca8380b303`; runtime
  DLL hashes were not saved.
- OptiScaler v10.0.0-dev as `dxgi.dll`, `Dx12Upscaler = ffx`, under per-process variables only:
  `VK_DRIVER_FILES`, `ANV_CM_HELPER`, `ANV_CM_KERNEL_DIR`, `ANV_CM_DEBUG=1`,
  `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer`, `WINEDLLOVERRIDES="cabinet=n,b"`; rollback
  in `~/xess-xmx/backup-20261113/`.

## Per-title detail

### Marvel's Spider-Man Remastered

The first functional result came from this game on 2026-11-13 (details below). The 4.1.2 DLL
serves its embedded 4.0.2X model by default; a run with `FSR4_XMX_INT8=1` confirmed 4.1.2X INT8
from the kernel set, not the overlay. A 2026-11-12 trace gave a correct UI and magenta and green
3D noise with driver generation `0913d3f4`, which lacks 0005; the candidate removed the noise.

### Cyberpunk 2077

Cyberpunk 2077 2.5, built-in benchmark at 1920x1080, Custom preset with High textures, vsync off
and no cap. The mod log identifies `INT8 model: preset weights from fsr-original.dll, bucket 0,
Xe2 SIMD16-DPAS kernels` and `Lite model: ...`. Full had 28 injections and 14 unique kernels,
Lite had 12 and 6, and one kernel is shared, so Lite runs a smaller network, not an alias.

Average FPS was 54.44 for XeSS, 54.54 for Full INT8 and 55.56 for Lite: Full is tied and Lite is
2.06 percent above. Recorded quality runs fell from 41.7 to 28.4 fps, so they measure image only.

### SCP: 5K

SCP: 5K build 20928322, version `0.17.6.1`, appid 872670, Unreal Engine 4.27.2 on D3D12. A match
rendered correctly with the 4.1.2 mod and OptiScaler after switching INT8 to Lite in the overlay.
The log counts 244 `ANV CM: injected`, 99 `FSR4 resource detected`, 236
`PSO create ... hr=0x00000000` and 0 device lost. OptiScaler repeats
`Upscaler support - fsr4: false`, as in the working Cyberpunk run, so the label is not
authoritative. EAC is untested.

## Why upstream dropped FSR 4 on XMX

Upstream `xess-xmx-linux` already had FSR 4 on XMX working. On 2026-11-02 the author dropped it as
a project direction, in commit `99445d8` ("Docs: FSR 4 on XMX is no longer developed"). It was not
a technical blocker.

Their `docs/games.md`, section "FSR 4 on XMX (Upscaler Builds from the OptiScaler Discord)", gives
three reasons: no significant performance gain over XeSS on XMX, more setup complexity, and a
conflict with XeSS frame generation, where the combination worked but needed image corrections
per game, which the project avoids because OptiScaler is the one that adapts per game.

They tested one build ("B Boost", FileVersion `4.0.2.1`) on one GPU (Arc B390) and two games,
manually. Their doc was archived for reference, and it already described most of the recipe this
repo rediscovered: plugin `amd_fidelityfx_upscaler_dx12.dll` with OptiScaler optional;
`fsr-original.dll` from AMD FSR SDK 2.4.0 (FSR 4.1.2) as the weight source, already fetched by
`install.sh` and `tools/get-ffx.sh`; native `cabinet.dll` plus `WINEDLLOVERRIDES=cabinet=n,b`,
because Wine lacks ordinals 40, 43 and 45; `FSR4_XMX_LITE=1` for Lite; and mandatory
`0005-anv-cm-sampler-descriptor-table.patch`, since "older drivers without patch 0005 render
corrupted images". The last point matches the local evidence.

Their measured performance, Arc B390 at 1280x800 render and no frame generation:

| Upscaler | Cyberpunk 2077 (avg fps) | CONTROL Resonant (fps) |
|---|---|---|
| XeSS Ultra Quality (XMX) | 57.5 | - |
| FSR 4 on XMX, full model | 56.4 | 35 |
| FSR 4 on XMX, Lite | 58.2 / 58.1 | 36 |

The FSR 4 kernels took 2.5 ms per frame in full and 1.9 ms in Lite, so Lite is faster rather than
equal; an overlay showing the same time for both models suggests Lite is not running.

What this repo adds is the 4.1.2X INT8 path upstream never tested (they stayed at `4.0.2.1`), the
`fsr-original.dll` weight check (`tools/xmx412_weight_scan.c`) and kernel fingerprint comparison
(`tools/xmx_kernel_set.py`) to rule out a silent fallback, plus the CMK3 prototype.

## The first functional run (2026-11-13)

Marvel's Spider-Man Remastered rendered the scene correctly with the XMX 4.1.2 mod, the shim and a
custom ANV driver. The UI and the 3D world were coherent and the upscaler reported about 0.99 ms.
It is the project's first correct visual and functional result, not a bit-exact validation: there
is no independent oracle and no deterministic readback of the PRE.

The setup used the candidate package side by side, the per-process variables above, a disposable
prefix of the trace run with the user's saves, Proton Experimental, mod `fadbcb50…` and OptiScaler
`Dx12Upscaler = ffx`.

| Artifact | Value |
|---|---|
| Log | `evidence/vkd3d-trace3-20261113.log`, 19,523 lines |
| SHA-256 | `012ac930a7369d9723234b4e84a9d68aaa6dba7e1827bd72578da3d368c1d957` |
| PRE | `~/.cache/xess-xmx/kernels/e8fca351200197b3_e20b_142835e7.cmk` (CMK2, 30,936 B) |
| Key line | `ANV CM: …e8fca351200197b3_e20b_142835e7.cmk: sampler descriptor table after the surfaces (sampler heap found)` |
| FSR4 resources detected | 11 `FSR4 resource detected` lines |
| Device lost | 0 |

The PRE was compiled with the new helper (gen `142835e7`, not `0913d3f4`) and the driver applied
the table sampler path: `table_pc_base = push_size - 4*(nsurf+1) = 52 - 48 = 4` and
`cm_sampler_pc_off = 48`.

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-candidate.sh &> vkd3d-trace3.log
```

Three problems closed on the way: the inherited 0001 patch had the CMK magic inverted, which
would have rejected every kernel, and a semantic test now covers the fix; the installed package
was old (`0913d3f4`) and lacked the fork's table-sampler support (0005), which fixes the base
offset mismatch (8 to 4) and the sampler offset; and the 4.1.2 packs need `Cabinet.dll` (LZMS
Compression API), which Wine does not implement and the game-local shim provides.

The run does not prove mathematical exactness, the real formats and contents of the 8 images, that
the package works system-wide or in other games, or repeatability beyond one session. A
system-wide installation remains a user decision, with rollback in `backup-20261113`.

## What is broken or missing

- There is no deterministic readback and no independent oracle. A working scene proves the path
  runs and looks plausible, not that FSR matches AMD hardware.
- The candidate package is not installed system-wide; every result used a per-process ICD and the
  user's active package stayed intact. DLSS, every other title and repeatability are untested.
- The overlay can show `4.0.2` while INT8 or Lite runs. The `INT8 model:` and `Lite model:` lines
  decide; `FSR4_XMX_PROVIDER_INDEX=8` or `12` changes only the label.
- Wine has no Compression API, so 4.1.2 packs need the game-local `cabinet.dll`. A prefix without
  `igdext64.dll` aborts with magenta and falls back to DG2 SIMD8 kernels instead of Xe2 SIMD16.
- Drivers without 0005 render corrupted images, and an old package without the table sampler path
  reproduces the 2026-11-12 magenta trace. The PRE payload audits stay `runtime_approved=false`.

## Static findings that still apply

Static analysis of 2026-10-22, with no package code executed.

| File | SHA-256 |
|---|---|
| amd_fidelityfx_upscaler_dx12_xmx.7z | `1364778b46ab3f0734305ad44d23e161d94cd75130e08683acd5ceed85d7155b` |
| OptiScaler_v10.0.0-pre_20261022.7z | `df1380aa37fc17b26524e783f12ccb2f59cb67f966af13240bca3d4cd608a25a` |
| DLL extracted from the XMX mod | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` |

Upstream originally analyzed `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`; the current patch base
is `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`, 178 commits later. Line numbers are relative to
`upstream/xess-xmx-linux/`; for patches they name the patch file, not the final Mesa file.

The 25,779,712 byte DLL carries strings for `igdext64.dll`, the INTC variants,
`CreateDeviceExtensionContext` at 4.20.0, `CheckFeatureSupport` for OPTIONS1/XMX and
OPTIONS2/SIMD16Required, `CreateComputePipelineState` with CM-SPIRV and Xe2 packs,
`GetCachedBlob`, models `4.0.2x` and `4.0.2xm` with weights from `fsr-original.dll`, a magenta
failure with fallback disabled, and one table per SurfaceIndex/sampler. These are extracted
strings, not a trace.

The shim answers the Intel D3D12 calls and the patched ANV driver builds the CM kernels. Two
CPU-tested shim fixes, the context output copy (0002) and the reused context `S_OK` (0003), are
not installed; see [shim-bridge.md](shim-bridge.md).

Later analysis recovered 690 CM blocks by their footers and 1,977 CM envelopes in 6 packs. The
4.1.2 PRE `native_1080` compiled offline for the B580 (`b1781bb4…` zebin, `68b962b5…` code, BTIs
`[8,9,1,2,3,4,5,6,7,10,11]`); the pins are in [shim-bridge.md](shim-bridge.md). The
suite passed 416 tests with 3 skips on 2026-11-13.

The fork's `0005-anv-cm-sampler-descriptor-table` patch computes
`table_pc_base = push_size - 4*(nsurf+1)`, which gives 4 for the PRE (11 surfaces, one sampler,
push 52), and sets `cm_sampler_pc_off = 48`. A per-profile gate added during the rebuild
duplicated it, broke 0005 and was reverted.
