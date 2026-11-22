# FSR 4 XMX: capture contract for real validation (RenderDoc + readback)

Static only, CPU-only. Mod DLL read as data, without loading or executing it:
`artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
(SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`,
45,558,272 bytes). No GPU, Wine, Proton, RenderDoc on a live process, and no
prefixes touched. Every claim comes from a source that was read; anything
that cannot be determined is marked as such.

Sources: `docs/xmx412-model-selection.md`, `docs/xmx412-dispatch.md`,
`docs/xmx412-packs.md`, `docs/xmx412-static-inventory.md`,
`docs/pre-resource-descriptors.md`, `docs/pre-dispatch-dimensions.md`,
`docs/manual-image-test.md`, `docs/first-image-gpu-result.md`,
`docs/spiderman-trace-runbook.md`, `docs/first-runtime-trace-412.md`,
`tools/inspect_dll_412.py`, `tools/inspect_pre_dispatch.py`,
`tools/inspect_pre_inputs.py`, `tools/reconstruct_pre_resources.py`,
`build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/evidence/vkd3d-trace3-20261113.log`
and `.../results/ciudad1-int8-20261113-125925/vkd3d.log`.
Strings verified by direct reading of the binary (ASCII and UTF-16LE, note 1).

## 1. Mod debug facilities: what exists and what it writes

No image dump exists. There is no PNG/DDS/BMP/JPG writer and no `SaveTexture`:
the searches only return fragments (`OpngK~`, `ndds`, `abmp`, with no API name
or output path). The only things the mod writes to disk are `.bin` tensors, a
parity `.csv`, failure SPIR-V and stage-2 blobs. The text channels are
`OutputDebugStringA/W` (imported), `MessageBoxA` (only a notice for a GPU
without XMX, see `docs/xmx412-static-inventory.md:57-87`) and the Proton log.

| Variable / switch | What it does | What it writes and where |
|---|---|---|
| `FSR4_XMX_DEV=1` | Unlocks the Developer tab, Version list, `HiddenEntries`, `Profile` (`docs/xmx412-model-selection.md:191-194`, `0x18006FD90`) | Nothing written to disk by itself; enables UI and views |
| `FSR4_XMX_FS_DIAG` (read with `atoi` in `FUN_180068CF0`; `FS_DIAG` alone does not exist; `docs/xmx412-model-selection.md:442-446`) | `0/2/4` = skip rules shown as colors; bit 8 = stats (`docs/xmx412-model-selection.md:436-440`) | Strings `FSR4_XMX_FS_DIAG=`, `=2`, `=4`; `Skip rules as colours`; `[FSR4 XMX] %s This frame shows magenta (logged once)`; `[FSR4 XMX FATAL] %s Stock fallback is disabled; diagnostic magenta will be shown` |
| Per-pass oracle `FSR4_XMX_P1/P2/P3/P4/P5/P7/P8/P9/P10/P11/P12_OracleCaptureReadback` (UTF-16LE names in the DLL) + `FSR4_P10_U1_OracleCaptureReadback`, with dirs `MLSR-XMX-PASS*-ORACLE-DUMP`, `MLSR-P10-U1-ORACLE-DUMP` | One-shot capture with a GPU readback buffer after completion: `One-shot capture armed: dir=%s ...`, `Capture copy scheduled; files will be written after GPU completion`, `CAPTURED input=%llu bytes FNV1a64=... output=...` | `%s\p1_input.bin` + `%s\p1_output.bin` (same for P2..P5, P10..P12); P7/P8: `input` + `stage2`; P9: `input`, `skip`, `stage2`, `stage3` (`%s\p9_input.bin`, `%s\p9_skip.bin`, `%s\p9_stage2.bin`, `%s\p9_stage3.bin`); P10U1: `%s\p10_input.bin` + `%s\p10_output.bin`. Failures: `Failed to create/map readback buffer`, `Dump directory path is ...`, `Failed to write capture files` |
| PRE parity `MLSR-XMX-PRE-PARITY`, `-TRIGGER`, `-DIR`, `MLSR-XMX-PRE-HOSTPARITY`, `MLSR-XMX-PRE-POSTSTORE-PARITY` | Compares the bytes of the XMX PRE tensor against stock PRE on the same machine; `Trigger observed; multi-frame capture armed` | `%ls\pre_parity_%04u.bin` + `%ls\pre_parity_summary.csv`; logs `frame=%u EXACT: 8294400/8294400 PRE tensor bytes match stock. reset=%u jitter=...`, `BYTE-MISMATCH` / `mismatchGroups=... maxAbs=... sumAbs=... first=(x y c stock xmx) reset jitter mvScale jitterCancel flags`, `HOSTPARITY ... BYTE-EXACT/BYTE-MISMATCH ... stockHash xmxHash`, `Ring full; capture frame skipped`, `TELEMETRY-INVALID: zeroRecords=... Do NOT classify this frame as BYTE-EXACT` |
| Failed-input dump `MLSR-XMX-PRE-DUMP-FAILED-INPUT` | Dumps the selected SPIR-V when it fails | `[FSR4 XMX DIAG] PRE failed selected SPIR-V dump file='%s' bytes=%zu write=%s`; `PRE failed-input dump path too long; dump skipped` |
| Stage-2 dump `MLSR-XMX-PRE-DUMP-STAGE2`, `fsr4_pre_xmx_stage2.bin` | Dumps the compiled blob via `INTC_D3D12_GetCachedBlob` | `[FSR4 XMX] PRE stage-2 GetCachedBlob failed: hr=...`; `PRE stage-2 dump unavailable: ... export missing`; `PRE stage-2 dump path is too long` |
| Profiles `MLSR-PROFILE*`, `MLSR-XMX-PRE-STAGE-PROFILE`, `PASS7/8/9-STAGE-PROFILE`, `MLSR-PROFILE-WHOLE`, `MLSR-PROFILE-PERIOD/SAMPLES`, `PRE PROFILE` | Timings per region with timestamp queries, not pixels | `[FSR4 XMX PRE PROFILE] n=%u diag=%u mode=%s total=... resources=... params=... constants=... bind=... xmx=... post=...`; `[FSR4 WHOLE PROFILE] ... scope=pre..post`; failures `Failed to create ... query heap/readback buffer/...; disabled` |
| Parameter overrides `FSR4_XMX_PRE_Params`, `FSR4_XMX_PRE_ParamsUpload`, `FSR4_XMX_Pass1..12_Params`, `EMBED_PRE/Pass6..9_Params`, `Post_Params`, `Post_Constants`, `Pass6_PackedWeights` (UTF-16LE) | Environment names for params/weights per pass | Exact semantics not determined statically; only the presence of the names. Do not use without reading the call site |
| `r_debug_visualization`, `rw_debug_visualization`, `debug`, `MLSR-PIX-DLL`, `MLSR-PIX-MARKERS` | Resource/marker names, not file output | No path or writer associated in the strings. `WinPixEventRuntime` is only mentioned to request its path |

Note 1: string verification method, read-only as data:

```bash
python3 -c "
import re
data=open('artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll','rb').read()
asc=set(m.decode('ascii') for m in re.findall(rb'[\x20-\x7e]{4,}',data))
u16=set(m.decode('utf-16le') for m in re.findall(rb'(?:[\x20-\x7e]\x00){4,}',data))
s=asc|u16
for k in ['FSR4_XMX_FS_DIAG','ORACLE-DUMP','pre_parity','PRE-DUMP','r_debug_visualization']:
    print(k, sum(1 for x in s if k in x))
"
```

## 2. Contract for the 8 images + PRE/network output

Basis: `tools/inspect_pre_inputs.py:13-60` (12 args of entry `fsr4_pre_xmx`,
 Types `BufferSurfaceINTEL ReadWrite`, `Image 2D ReadOnly/ReadWrite format Unknown`,
 `Sampler`) and `docs/pre-resource-descriptors.md:26-40`
(arg/root/heap map cross-checked against `ze_info.yaml` and SPIR-V).
Retained in 4.1.2: same 10 stock names, same wide multiplicity counts, same
grid and same vtable slots except one extra `+0x78`
(`docs/xmx412-dispatch.md:113-137,203-243`).
Helper rewritten in 4.1.2: translator `0x18000bbd0` (198 B) + barrier
`0x180027bc0` (57 B); the heap no longer comes from `ctx+0x1b40` but from
`0x38f0/0xa78/0x4920/0x4910/0x3910` (`docs/xmx412-dispatch.md:180-201`).

| Arg | Root / register | Relative heap slot | Class in signature | Format and size |
|---:|---|---|---|---|
| 0 (mixed scratch) | 1 / u0 | resources / 7 | UAV `BUFFER`, `R8_UINT` (`0x3E`), `FirstElement=0`, `NumElements = Width` | `GetDesc` requires `Dimension == BUFFER (1)`; lower bound `Width >= factor^2 * 0x7e9000`; for `native_1080` factor 1: minimum **8,294,400 bytes**. Exact Width is a runtime value. See `docs/pre-resource-descriptors.md:47-76`, `docs/xmx412-dispatch.md:158-170` |
| 1 (destination) | 2 / u1 | resources / 8 | Image2D ReadWrite | Descriptor copied with `CopyDescriptorsSimple`; source format and dimensions not recovered in this sequence |
| 2..8 (t0..t6, 7 entries) | 3..9 / t0..t6 | resources / 0..6 | Image2D ReadOnly | Descriptors copied by helper; source indices chosen at runtime (`[rsp+0x78]`, `[rsp+0x7c]`, `esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx` in 4.0.2; revalidate 4.1.2 call sites). Format/dimensions not pinned |
| 9 | 10 / t7 | resources / 9 | SRV `BUFFER`, `R8_UINT`, map `0x1688`, first 0, **0x840 = 2,112 bytes** | Resource of `ctx+0xa80`; fixed view 2,112 B; backing and contents are runtime |
| 10 (header) | 11 / t8 | resources / 10 | SRV `BUFFER`, `R8_UINT`, map `0x1688`, first 0, **0x80 = 128 bytes** | Resource of `ctx+0xa98`; the kernel reads 128 B (DWORDs 8..84, dir/bytes 64..80, flag byte 100, base byte 104; bit `0x400` guard, `0x2000` chooses `base` or `base+16` as the offset in arg 0). See `docs/pre-resource-descriptors.md:78-90` |
| 11 (sampler) | 12 / s0 | sampler heap / 0 | Sampler | MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, ALWAYS, MinLOD 0, MaxLOD FLT_MAX |
| push constants | root 0 | not applicable | `SetComputeRoot32BitConstant(root 0) = 0` (`b0=0`); opcodes `FF 90 08 01 00 00` 1 time; `FF 90 F8` 3 times, `Dispatch` 2 times (`docs/xmx412-dispatch.md:203-243`) | Incomplete constants (`<0x20` in `0x250e9..0x250f5`) or ABI (`consts+100`, high `0x5058`, `docs/xmx412-dispatch.md:139-170`) trigger a fail-stop, not a partial dispatch |

Rules to recognize each resource in RenderDoc (there are no resource names):
view format + visible size + binding order + push constants.
For images, the DXGI/VK format, dimensions and strides **cannot be pinned
statically**: the SPIR-V declares `Unknown`, the descriptors are copied, and
the source is runtime (`docs/pre-resource-descriptors.md:172-190`,
`tools/inspect_pre_inputs.py:116-121`). The first capture must record, by
resource ID and descriptor: the full `D3D12_RESOURCE_DESC`, each
`CreateSRV/UAV` and `CopyDescriptors*`, the GPU handles of the 11 tables +
sampler, the `Dispatch` grid, and the pre and post bytes of args 0/9/10
(`docs/spiderman-trace-runbook.md:151-168`,
`docs/pre-resource-descriptors.md:192-225`).

## 3. How to identify the upscaler dispatch in the capture

1. It is a compute dispatch with a grid derived from the input:
   `x = (w+15)>>4; x += x&1; y = h>>1` (`docs/xmx412-dispatch.md:64-90`).
   For `w=1920,h=1080`: **`(120, 540, 1)`**. The strings `baseDispatch=120x540x1`
   (also `60x270x1`, `30x135x1/2`) in the DLL confirm it.
2. Modes (function `0x18002bed0`, 145 B; call at `0x25a3e`):
   mode 2,3 = return 1 without dispatch; 4 = `(1,1,1)`; 5 = `(x,1,1)`;
   6 = `(x,0x44,1)`; the rest = `Dispatch(x,y,1)` at `0x26394` and `0x263c9`
   (`docs/xmx412-dispatch.md:91-111`).
3. Binding signature: 11 effective tables (roots 1..11: u0, u1, t0..t6, t7,
   t8) + sampler at root 12, `root0 = 0`
   (`docs/spiderman-trace-runbook.md:151-168`). The game's other dispatches
   do not show that combination of grid + 12 roots + `b0=0`.
4. CM kernel: entry `fsr4_pre_xmx`, pack 40102 record 0, `ir_size` 358,776,
   envelope 358,873, `ir_sha256 49e069fd...`, envelope `ce372719...`
   (`docs/xmx412-packs.md:69-90`, `docs/spiderman-trace-runbook.md:9-21`).
   In the runtime log it appears as `dyn_60.spv` (358,873 B) = kernel
   `e8fca351200197b3`, with a 3-byte difference at offset 59112..59114
   (`OpConstant float 68.45...` offline vs `67.18...` runtime: a patch applied
   by the mod's dispatch, not corruption) and a later ANV compilation
   (`docs/first-runtime-trace-412.md:47-62,73-86`).
5. ANV lines that reveal it in `vkd3d-trace3-20261113.log:1298-1305`:
   `compiling kernel e8fca351200197b3 (dyn_60.spv)`, `placeholder wg 61,1,7`,
   `set 0: type 1 bindings 1 descriptors 2048`,
   `set 1: type 1 bindings 3 descriptors 1000002`,
   `samples but the pipeline layout has 0 static samplers`,
   `sampler descriptor table after the surfaces (sampler heap found)`,
   `heap set 1 binding 2: descriptor offset 128 stride 64`,
   `injected ... (30464 bytes code, 128 GRF, lws 1,1,1)`.
   The `placeholder wg 61,1,7` is the packer's selector, not the shader's geometry
   (`docs/pre-dispatch-dimensions.md:38-52`).
6. Game context (not proof by itself): overlay `FFX -> FSR 4.0.2`
   with upscaler 0.8..0.96 ms (vs ~2 ms without XMX), perfect UI, 3D world
   with magenta/green noise; `d3d12_resource_SetName: FSR4 resource detected`
   dozens of times (`docs/first-runtime-trace-412.md:24-36`,
   `vkd3d-trace3-20261113.log:1285-1297`). The overlay shows the provider's
   label, not the model that ran; the log (`INT8/Lite model ...`) is the
   reference (`docs/xmx412-model-selection.md:270-276,448-484`).
7. The run `ciudad1-int8-20261113-125925` injected 174 kernels (`summary.txt`),
   with 74 unique fingerprints and `sampler-heap-ok: 6`; it is evidence of real
   XMX activity, not of correctness.

## 4. What each evidence level allows and does not allow

| Level | What it allows claiming | What it does NOT allow claiming |
|---|---|---|
| Deterministic readback (same bits across runs, `FNV1a64`, `pre_parity` EXACT 8294400/8294400) | Reproducibility of that stack (mod + weights + driver + LWS + sampler). With `reset`/jitter/mvScale fixed and `TELEMETRY-INVALID` frames discarded, two identical runs rule out accidental non-determinism | Functional correctness. Parity compares XMX against stock on the same Intel GPU; neither is an AMD oracle. A stable but wrong buffer (e.g. sampler fallback linear/clamp or auto layout 8 vs 4) still gives EXACT across runs |
| Comparison against an upscaling reference (PSNR/SSIM) | Perceptual closeness with a declared threshold, if the reference, the alignment (reset, jitter, crop, format) and the comparison plan are fixed | Bit-exactness or cause. A high PSNR with a single frame does not prove other presets, resolutions or determinism |
| No bit-exact FSR 4 oracle without AMD hardware | Methodological honesty: the weights are verified by content (FNV-1a64 of blobs `0x6B00`/`0x20000`, `docs/xmx412-model-selection.md:301-335`), the IR 4.1.2 differs by +8.7 % from the old one (`docs/xmx412-packs.md:84-90`), the runtime patches a float constant and the driver recompiles; there is no AMD reference output in the repo | Any claim like "the PRE is bit-exact with official FSR 4". `S_OK`, a created PSO, the overlay or the timing do not prove the model or the pixels (`docs/xmx412-model-selection.md:517-530`) |

Basis for this criterion in the docs: `docs/pre-resource-descriptors.md:226-231`
(descriptor capture is input evidence, not an oracle),
`docs/pre-dispatch-dimensions.md:83-103` (without local size, mask or oracle,
dispatch is not authorized), `docs/manual-image-test.md` and
`docs/first-image-gpu-result.md` (the only validated readback is that of the
synthetic 2x2 RGBA32F kernel with max error 0.0 and 1,984 sentinel words
intact; it does not validate PRE or FSR), `docs/first-runtime-trace-412.md:64-71`
(the mod→VKD3D→ANV path works; bindings and the cause of the noise are not confirmed).

## 5. Left undetermined (not statically assertable)

- DXGI/VK format, dimensions, mip/layer, sample count and strides of the 8
  images (t0..t6 + destination). Requires RenderDoc.
- Exact Width of arg 0 (lower bound only), backing and initial bytes of
  args 0/9/10, contents of the 128 B header. Requires pre/post capture.
- Local size, threadcount and execution mask of the real PRE dispatch
  (`docs/pre-dispatch-dimensions.md:38-103`). The `lws 1,1,1` from the ANV log
  and the `placeholder wg` are bridge/packer decisions, not the shader contract.
- Exact semantics of each `*_Params`/`*_Upload` override, of the
  `FSR4_XMX_FS_DIAG` modes beyond colors/stats, and of `ASKIP/FRAMESKIP/MIDSKIP/
  LIST_SKIP`. Only strings and one documented call site (`atoi` in
  `FUN_180068CF0`).
- Cause of the magenta/green noise (candidates: base layout auto 8 vs 4,
  sampler fallback, LWS; `docs/first-runtime-trace-412.md:81-86`). Without a
  frame capture with real formats it is not decided.
- Any bit-exact output oracle for FSR 4 (section 4).

## 6. Reproduce the static baseline

```bash
sha256sum artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
# fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory tests.test_xmx412_model_strings tests.test_xmx412_dispatch -v
python3 tools/inspect_pre_inputs.py analysis/fsr-resources/xe2-first.spvasm
```
