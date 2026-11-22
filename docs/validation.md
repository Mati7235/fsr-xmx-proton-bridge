# Validation: how to prove that something works

This document answers one question for a new maintainer: what evidence makes a
claim about this bridge acceptable, and what does each piece prove. It replaces
the old capture contract, readback methodology, RenderDoc guide, PRE test
contract and the session reports.

## The rule

An overlay label, a shim log line or a returned `S_OK` does not count as
success. Neither does a created pipeline state, a shader that compiled, a
disappeared magenta tint or a plausible frame time.

A result needs injection evidence and deterministic GPU readback together.
Injection means the kernel we built ran on the dispatch we intended, shown by
`ANV CM:.* injected` in `vkd3d.log` with `fingerprint.txt` and the driver lines
that name the kernel id, local size and descriptor sets. Deterministic readback
means bytes from the GPU match a fixed expectation bit for bit, with canaries and
guard regions intact. Injection alone says the code ran, not what it computed.
Readback alone can be a stale buffer that nothing wrote this frame.

## The evidence ladder

Cheap evidence is useful only while it keeps its own claim.

| Evidence | What it allows claiming | What it does not allow claiming |
|---|---|---|
| Synthetic microtest with readback | injection and deterministic readback for that probe's format, layout and sampler | anything about PRE, other formats, writable images or the mod's dynamic sampler |
| Resource capture: RenderDoc frame or caller trace | which resources, views, copies, handles, formats and grid reach the dispatch | correctness; this is input evidence, not an oracle |
| `diff` without tolerance | repeatability of the same stack | correctness; a stable but wrong buffer stays stable and wrong |
| `diff --tolerance ABS` | agreement within a declared threshold, for example after a format conversion | bit equality |
| `metrics` PSNR/SSIM against XeSS or TAAU | perceptual plausibility within a declared threshold | equivalence with AMD FSR 4 |
| `pre_parity` EXACT 8294400/8294400 | the XMX PRE tensor matches the stock PRE on the same Intel GPU, repeatably | that either tensor is correct; parity against a local fallback is not an AMD reference |
| Human eye on crops | local artefacts that global metrics average out | anything bitwise, any other scene or preset |

The criterion is conjunctive. Injection ties our code to the correct dispatch and
to the synthetic contract, with no claim about quality. Determinism makes any
quality metric meaningful. Plausibility separates a working upscaler from a
deterministic but broken one. A human eye on crops catches local artefacts that
global PSNR and SSIM average out. All four still do not prove equivalence with
FSR 4 on AMD hardware; they prove plausibility under the control of the test.

Reading a comparison: `diff a.bin b.bin` exits 0 and prints `identical: True`
only for bit-for-bit equal files, and without `--tolerance` any differing bit
gives exit 1. `-0.0` against `0.0` differs in bits with absolute error 0. NaN
against any value, including another NaN with a different payload, counts as a
difference with infinite error; two deterministic runs should never produce
diverging NaNs, and if they do the fault is earlier and `inspect` runs first.

### Why there is no bit-exact oracle

A bit-exact oracle would need the same order of operations in every reduction,
the same rounding of each XMX matrix instruction, the same quantized weights and
the same driver microcode. None of that is public for FSR 4, and another GPU
reorders and rounds differently. Only a reference output pair from real AMD
hardware, or AMD publishing reference vectors, would create one. With that pair,
`diff` at tolerance 0 against the oracle is the equivalence proof; without it,
the ceiling is the plausibility row.

## Capturing a frame with RenderDoc

> PERFORMANCE WARNING: capturing with RenderDoc changes the timing
> (it serializes queues, adds CPU overhead, forces extra synchronization).
> The FPS / frametimes observed under capture are NOT representative, and an
> apparent regression under RenderDoc does NOT prove a real regression.
> The capture is useful for RESOURCE INSPECTION (which textures/buffers enter
> the upscaler, dispatch dimensions, descriptor layout), not for measuring
> performance. Measurements are always done with `run-full-test.sh`
> without RenderDoc.

Verified locally without running the game: `renderdoccmd` x64 v1.46 (Arch),
`qrenderdoc` and `/usr/lib/librenderdoc.so`, with Vulkan, GL and GLES compiled in
and no D3D12 backend. The layer is
`/etc/vulkan/implicit_layer.d/renderdoc_capture.json`, enabled by
`ENABLE_VULKAN_RENDERDOC_CAPTURE=1` and disabled by
`DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46=1`. The capture therefore records Vulkan
as translated by vkd3d-proton, not D3D12.

Known limits:

1. D3D12 root signatures and PSOs appear only as their Vulkan translation;
   correlate with the `vkd3d.log` saved beside the capture (`VKD3D_DEBUG=trace`).
2. CM kernels from `ANV_CM_HELPER` appear as compute dispatches with internal
   driver blobs and no readable HLSL, GLSL or SPIR-V. Do not expect to read them.
3. RenderDoc 1.46 mishandles `VK_EXT_descriptor_buffer`; keep it disabled through
   `VKD3D_DISABLE_EXTENSIONS=VK_EXT_descriptor_buffer` as the launcher does.
4. The session is Wayland and this build lists only WSI xlib, XCB and
   KHR_display, so the game runs under XWayland; focus the game window itself if
   F12 does nothing. MangoHud is forced off, because hooking Vulkan twice breaks
   the capture.

The run needs the same machine and disposable prefix as the functional run, with
`renderdoccmd` in `PATH` and `DISABLE_VULKAN_RENDERDOC_CAPTURE_1_46` unset, since
the script aborts otherwise. The candidate driver, `kernels-candidate/`,
`fsr-original.dll` and `compatdata/` must already exist in the run directory,
which the script reuses unless `--fresh-kernels` is given. A AAA frame can take
several GB, and `/home` had roughly 390 GB free.

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-renderdoc.sh int8 ciudad-rdc
# o: ./run-renderdoc.sh lite ciudad-rdc
# o: ./run-renderdoc.sh stock ciudad-rdc
```

`--proton-log` also saves `steam-proton.log` with the mod's log, and
`--fresh-kernels` recompiles into `captures/<tag>-<modelo>-<stamp>/kernels`. The
script mirrors `run-full-test.sh` and adds the capture wrapper, the RenderDoc
layer and the `captures/` output.

Focus the game window and press F12; every press writes a new file to
`captures/<tag>-<modelo>-<stamp>/spiderman_frame*.rdc`, opened with
`qrenderdoc`. Beside each capture sit `vkd3d.log`, `fingerprint.txt` and
`summary.txt`, with the same injection criterion as `run-full-test.sh`. If the
capture is empty, confirm focus or attach from `qrenderdoc`; if the game starts
only under `run-full-test.sh`, check `env | grep RENDERDOC` and extend
`LAYERS_DISABLE`; after a 0-byte file, retry with `--fresh-kernels`.

Afterwards close the game and measure without capture:

```bash
./run-full-test.sh int8 ciudad1
```

Capture mode writes to `captures/`, leaves `results/` alone and does not modify
`compatdata/` beyond normal game use. Do not take the capture as proof of
injection: that proof stays `ANV CM:.* injected` plus `fingerprint.txt`.

## Deterministic readback

The tool is `tools/fsr_readback_compare.py` (CPU only, standard library, with an
optional numpy fast path). `inspect` reads a dump with an explicit format and
size, and exits 2 instead of inventing an interpretation on a mismatch. `diff`
compares two runs without tolerance: same inputs, driver, weights and resolution
must give identical bytes.

`metrics candidato.bin referencia.bin` computes PSNR and SSIM per channel and on
luminance. The reference is a comparison upscaler available on Linux (XeSS or
native TAAU), never AMD. It rules out gross failures such as a flat screen,
noise, half resolution or permuted channels, and it cannot show equivalence with
AMD. NaN or Inf make it exit 2, so `inspect` runs first.

Three inspectors cover the static side. `tools/inspect_dll_412.py` inventories the
4.1.2 DLL, `tools/inspect_pre_dispatch.py` reads the pinned PRE dispatch from the
disassembly, and `tools/inspect_pre_inputs.py` reads the pinned SPIR-V contract.
None of them loads the DLL or touches a GPU, and each rejects input whose hash
differs from the pin.

Peak signal defaults to 1.0 for float formats and 255.0 for 8-bit formats, and
`--peak` overrides it; PSNR always comes with the MSE. SSIM averages
non-overlapping 8x8 box windows with K1=0.01, K2=0.03 and L equal to the peak,
printed as `ssim_window:`. Luminance uses Rec.709 (0.2126 R + 0.7152 G + 0.0722
B) for RGB and RGBA and the first channel otherwise, with alpha left out.

### Getting the dumps

The mod has its own GPU readback, so RenderDoc is not needed here.
`run-full-test.sh` runs in the disposable, git-ignored directory:

```bash
cd build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6
./run-full-test.sh int8 oracle1 --oracle-all --proton-log --dry-run   # revisar primero
./run-full-test.sh int8 oracle1 --oracle-all --proton-log
./run-full-test.sh int8 oracle2 --oracle-all --proton-log
```

Both runs must use the same area, resolution and preset. The dump is one-shot on
the first useful frame, so different scenes give different tensors by content.

| Variable | Effect |
|---|---|
| `FSR4_XMX_P1..P12_OracleCaptureReadback=1` | arms the one-shot dump of the pass |
| `MLSR-XMX-PASSn-ORACLE-DUMP=<ruta Windows>` | directory for `pN_input.bin` / `pN_output.bin` |
| `MLSR-XMX-PRE-PARITY=1` and `MLSR-XMX-PRE-PARITY-DIR` | parity of the PRE tensor against the stock path |
| `MLSR-XMX-PRE-HOSTPARITY=1`, `MLSR-XMX-PRE-POSTSTORE-PARITY=1` | additional hash checks |

Names with hyphens cannot go through `export`, so the script injects them with
`env` when launching Proton. Each `summary.txt` reports `oracle-armed`,
`oracle-captured`, `oracle-files`, `pre-parity-exact` and `pre-parity-mismatch`:

```bash
python3 tools/fsr_readback_compare.py inspect results/oracle1-*/oracle/p9_output.bin --format rgba32f --width 1920 --height 1080
python3 tools/fsr_readback_compare.py diff results/oracle1-*/oracle/p9_output.bin results/oracle2-*/oracle/p9_output.bin
```

The oracle writes `%s\p1_input.bin` and `%s\p1_output.bin` (same for P2..P5 and
P10..P12); P7 and P8 write `input` and `stage2`; P9 writes `input`, `skip`,
`stage2` and `stage3`. The parity path writes `%ls\pre_parity_%04u.bin` and
`%ls\pre_parity_summary.csv`, and logs `EXACT: 8294400/8294400 PRE tensor bytes
match stock`, `BYTE-MISMATCH`, `TELEMETRY-INVALID: zeroRecords=... Do NOT
classify this frame as BYTE-EXACT` and `Ring full; capture frame skipped`.

There is no image dump in the mod: no PNG, DDS, BMP or JPG writer and no
`SaveTexture`. `FSR4_XMX_FS_DIAG` (`atoi` in `FUN_180068CF0`; `FS_DIAG` alone
does not exist) shows skip rules as colours at `0/2/4` and stats at bit 8, and
`FSR4_XMX_DEV=1` unlocks the Developer tab. Profiling switches (`MLSR-PROFILE*`,
`PRE PROFILE`) give timings, never pixels. All strings above were read from the
binary as data, never executed.

## The PRE native_1080 test contract

This section says what a real validation of PRE Xe2 pack 40102 at `native_1080`
must capture and satisfy. It does not authorize a dispatch and does not declare
the bridge compatible.

The artifacts are pinned and were never executed: DLL
`artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`
(`3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`), CM envelope
`76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`, and the PRE
compiled for Xe2/B580 (`0xe20b`, zebin
`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`). The 4.1.2
mod moves the pins to DLL
`artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
(`fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`,
45,558,272 bytes), IR `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568`
(358,776 B) and envelope
`ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` (358,873 B).

The entry is `fsr4_pre_xmx` with 12 arguments and BTIs `8,9,1,2,3,4,5,6,7,10,11`
plus sampler index 0. There are no resource names, so identify each resource by
view format, visible size, binding order and push constants.

| Heap slot | Arg | Root | BTI | Class | Format and size |
|---:|---|---:|---:|---|---|
| 0-6 | 2-8 / t0-t6 | 3-9 | 1-7 | Image2D ReadOnly | copied by the helper, source index chosen at runtime; format and dimensions unpinned |
| 7 | 0 / u0 | 1 | 8 | UAV `BUFFER` | `R8_UINT` (`0x3E`), `FirstElement=0`, `NumElements = Width`; `GetDesc` requires `Dimension == BUFFER (1)` and `Width >= factor^2 * 0x7e9000`, so at least 8,294,400 bytes at `native_1080` |
| 8 | 1 / u1 | 2 | 9 | Image2D ReadWrite | destination, copied with `CopyDescriptorsSimple`; format and dimensions not recovered |
| 9 | 9 / t7 | 10 | 10 | SRV `BUFFER` | `R8_UINT`, map `0x1688`, first 0, `0x840` = 2,112 bytes, from `ctx+0xa80` |
| 10 | 10 / t8 | 11 | 11 | SRV `BUFFER` | `R8_UINT`, map `0x1688`, first 0, `0x80` = 128 bytes, from `ctx+0xa98` |
| sampler | 11 / s0 | 12 | - | Sampler | MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, ALWAYS, MinLOD 0, MaxLOD FLT_MAX |
| push | root 0 | 0 | - | `SetComputeRoot32BitConstant(root 0) = 0` | surfaces at offsets 4..44, sampler at 48, total range 52 bytes; `b0` stays 0 |

Facts a test must not re-guess:

- The shader guards on `WorkgroupId.x >= 120` and `WorkgroupId.y >= 540`, so the
  minimum grid is 120x540x1; smaller X or Y leaves groups unprocessed.
- The grid formula is `x = (w+15)>>4; x += x&1; y = h>>1`. For 1920x1080 it gives
  **`(120, 540, 1)`**, and `baseDispatch=120x540x1`, `60x270x1` and `30x135x1/2`
  confirm it. Modes: 2 and 3 return without a dispatch, 4 gives `(1,1,1)`, 5
  gives `(x,1,1)`, 6 gives `(x,0x44,1)`, the rest give `Dispatch(x,y,1)`.
- The store does not use BTI 7: `0,0,7` in `(predicate, i8, i8, i8, i32 surface,
  u, v, r, lod, data)` is the channel mask `.xyz`, the surface comes from arg 1,
  and the IGA emits `store_quad.tgm.d32.xyz.a32.bti[9]`. t6 at BTI 7 is not the
  destination.
- Arg 0 is not an empty readback buffer: it holds input, scratch and the output
  plane written 128 bytes per group at OWORD index `wg_y*960 + wg_x*8`, and the
  float4 read at `base + {0,16}` depends on the 128-byte header of arg 10. The
  extra cross-thread bytes are unread only under full execution mask. Do not omit
  the sampler or assume bilinear exactness: the ANV fallback only partially
  matches the DLL's sampler.

A capture must record what [pre-trace-capture-spec.md](pre-trace-capture-spec.md)
lists slot by slot: the full `D3D12_RESOURCE_DESC`, heap properties, resource IDs
that survive aliases, each view and `CopyDescriptors*` with its source index and
destination, the t0 to t6 selection registers (`[rsp+0x78]`, `[rsp+0x7c]`,
`esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx` on 4.0.2), both heap starts and
increments, the 11 table handles plus root 12, the sampler, the `Dispatch`
arguments and the barriers (`0x40`, `0x400`, `0x800`). Resolve each slot through
`GetDesc`, detect aliasing, and confirm `Dimension == 1` and
`Width >= 8,294,400` for arg 0. Dump before and after without modifying the
observed state: the 128-byte header of arg 10, the 2,112 bytes of arg 9, and the
16-byte record at `base + {0,16}` plus the OWORD plane of arg 0.

The local size and execution mask are not `Dispatch` arguments. They need driver
or launcher evidence; `1x1x1`, `SubgroupSize 1` and the Vulkan selector do not
replace it, and `lws 1,1,1` or `placeholder wg 61,1,7` are bridge decisions. ANV
names the same kernel `e8fca351200197b3` from `dyn_60.spv` and logs `injected ...
(30464 bytes code, 128 GRF, lws 1,1,1)`.

### Gates before the first PRE dispatch

The test runs isolated in a disposable prefix, with a locally chosen ICD and
driver, without touching Steam, real prefixes, services or drivers. The manual
steps are in [spiderman-trace-runbook.md](spiderman-trace-runbook.md) and the
version rows in
[pre-trace-version-checklist.md](pre-trace-version-checklist.md). Reuse the
synthetic harness barrier: canary enabled, explicit log of real injection,
profile and cache identity pinned, DIRECT layout verified, synchronization
correct and repeatable GPU readback. The positive synthetic DPAS probe covers
only its own kernel and layout, not PRE.

All of these remain open:

1. Save the image and sampler probe evidence exactly (formats, filters,
   coordinates, texel space, limits, transitions, readback); do not extrapolate
   from it to the eight PRE images.
2. Determine the format, size, permissions, usage and contents of each image and
   the full layout of args 0, 9 and 10 from an authorized caller trace. Arg 0
   needs `base + {0,16}` and the OWORD plane clear of incompatible regions; arg
   10 must cover its 128-byte header.
3. Derive the real local dimension, confirm the grid covers 120x540, and verify
   the execution mask required by the payload audit.
4. Identify images by provenance and usage, and build deterministic values valid
   for each confirmed format; an exact capture beats invented patterns.
5. Obtain an independent PRE oracle: the same input, resources and ABI through a
   reference implementation, or a CPU reference validated against it. No static
   rule produces an expected output, so without an oracle only injection, guards
   and absence of out-of-range corruption can be checked. A capture of the bridge
   that still fails is not an oracle.
6. Review with hashes the Proton and VKD3D version, the push layout, the heap and
   sampler, the binding map, and the lifecycle with synchronization.

The approval criterion is all gates above, a repeatable test with fixed input in
a disposable prefix, evidence of the injection path and expected layout, and a
complete readback compared with the oracle with tolerances justified per format
and operation. Canaries and guard regions must show no differences. `S_OK`, a
created PSO, an overlay label or the disappearance of magenta are not enough.

## What has been proven so far

These rows hold the facts that single-session reports established. None is a
functional proof of FSR 4.

| Run | What it established | What it did not establish |
|---|---|---|
| REA static inspection of the pinned 4.0.2 DLL, 2026-11-12, read as data only | PE32+ x86_64. 16 imported DLLs and 167 functions, 0 delay-imports. `d3d12.dll` imports only `D3D12SerializeRootSignature` and `dxgi.dll` only `CreateDXGIFactory2`; no `CreateCommittedResource`, `CreateShaderResourceView`, `CreateUnorderedAccessView` or `CopyDescriptors*` appears directly. 5 exports and 5 resources whose hashes match `analysis/fsr-resources/manifest.json` | who creates the images, what they contain initially, whether PRE may run. It confirms that views and resources travel through D3D12 vtables received from the host |
| Synthetic image/sampler probe on the B580, 2026-10-23, run by the user, PCI `8086:e20b`, exit code 0 | 2x2 sampled RGBA32F image, one mip, immutable linear/clamp sampler. The 64 sampled float32 values match the CPU reference with maximum absolute error 0.0, and 1,984 sentinel words stay intact in an 8,192-byte dump. DIRECT heap type 2, set 0/binding 0, offset 0/stride 64, sampler in the second set, injection of 1,280 bytes, 128 GRF, CM LWS `(1,1,1)`, selector `(2,1,5)` with indices `3 7` | other formats, writable images, the mod's dynamic sampler, repeatability across runs, and anything about PRE or full FSR |
| First 4.1.2 runtime trace on Spider-Man, 2026-11-12, manual run, log read only | The mod to extension to VKD3D to ANV path works with the game-local `cabinet.dll`. Six LZMS packs loaded, `d3d12_resource_SetName: FSR4 resource detected` appears dozens of times, and the shim dumped 112 kernels. `dyn_60.spv` (358,873 B) is `fsr4_pre_xmx` and `dyn_60.opt` is empty. It differs from the offline envelope by 3 bytes at 59112..59114, an `OpConstant float` patched per dispatch (68.45 offline, 67.18 runtime). `map.txt` correlates it with kernel id `e8fca351200197b3` and a 30,936-byte CMK2 blob, so ANV compiled and injected it. The overlay read `FFX -> FSR 4.0.2` at 0.8 to 0.96 ms against about 2 ms without XMX, with a correct UI and a 3D world of magenta and green noise | functional correctness, the PRE's real bindings, or the cause of the noise. Four `samples but the pipeline layout has 0 static samplers` lines mean ANV failed open with linear/clamp sampling, the shim's LWS and an auto-inferred base layout (generation `0913d3f4`), and nobody has separated those three suspects |
| `ciudad1-int8-20261113-125925` | 174 injected kernels, 74 unique fingerprints and `sampler-heap-ok: 6`, per `summary.txt` | correctness; it is evidence of real XMX activity only |

The reviewed trace log is `evidence/vkd3d-trace2-20261112.log` (7,775,448 B,
50,417 lines).

The image probe was reviewed with `tools/review_image_result.py` and its prepared
manifest, which checks the hashes, the canary, the injection and map log and the
binary dump independently of the C comparator. Hashes: `probe-driver.log`
`1ae5b571518c8131ef46247e82a040ec26b020c59a9051bf3fd16665f44756ca`,
`image-readback.bin`
`f84be4a8d77b9951b64a80b2235b78a85f4124f64d0e1db6bbe1f571d13c8b77`, and
`image-readback.txt`
`0b8ab6c95995d6d04059a3ea742a14c6a1959b277c2f399089dc5c223a11de13`. The
result lives in `analysis/image-gpu-result-20261023-005649.json`, not in an
edited manifest.

The REA exports, all without forwarders: `ffxConfigure` 1 `0x180001240`,
`ffxCreateContext` 2 `0x180001290`, `ffxDestroyContext` 3 `0x180001340`,
`ffxDispatch` 4 `0x1800013b0`, `ffxQuery` 5 `0x180001400`, matching
`analysis/fsr-xmx-disassembly.txt`. REA had no disassembly provider here, so it
produced no new pseudocode or CFG; that limits the scope of the evidence, not its
validity.

## What is still unproven

- The DXGI or Vulkan format, dimensions, mip levels, layers, sample count and
  strides of the eight images. RenderDoc is the tool for this.
- The exact `Width` of arg 0 beyond the 8,294,400-byte lower bound, the backing
  and initial bytes of args 0, 9 and 10, and the 128-byte header contents.
- The local size, thread count and execution mask of the real PRE dispatch.
- The semantics of each `*_Params` and `*_Upload` override, of
  `FSR4_XMX_FS_DIAG` beyond colours and stats, and of `ASKIP`, `FRAMESKIP`,
  `MIDSKIP` and `LIST_SKIP`.
- The cause of the magenta and green noise. Candidates are the auto base layout 8
  against the documented 4, the sampler fallback, and the LWS.
- Any bit-exact output oracle for FSR 4.
- Whether the 4.1.2 patches (`0002`, `0003`, `0001` plus registry `3ddd809f`)
  remove the noise, and whether Proton or VKD3D invalidate values traced at one
  resolution. Installing them needs a rebuilt Mesa and shim and explicit
  approval.

## Reproducing the static baseline

```bash
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
# fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory tests.test_xmx412_model_strings tests.test_xmx412_dispatch -v
python3 tools/inspect_pre_inputs.py analysis/fsr-resources/xe2-first.spvasm
python3 -m unittest discover -s tests -p test_pre_inputs.py -v
sha256sum analysis/fsr-resources/xe2-first.spvasm
# 7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e
# IGA disassembly: a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660
```

The dimension inspector rejects altered metadata, zebin or disassembly output. Do
not edit it to accept a changed file.
