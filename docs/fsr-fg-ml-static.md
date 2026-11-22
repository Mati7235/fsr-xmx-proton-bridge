# Static inventory of FSR ML Frame Generation 4.0.1

Date: 2026-11-22. Static inspection only, CPU-only. The DLL was not executed,
no GPU/Wine, no games or prefixes touched. Full detail (local, not versioned):
`analysis/fg-401-static/report.md`, `inventory.json`,
`ags-wmma.json`.

## Artifacts

| DLL | Version | Size | SHA-256 |
|---|---|---:|---|
| Cyberpunk 2077 `bin/x64/amd_fidelityfx_framegeneration_dx12.dll` | 4.0.1.2740 | 40,085,776 | `02297beedd285e822d3a64f314cf00faf378dcec0edc47ff0c4dd71b3a8c2f18` |
| FidelityFX SDK 2.4.0 `amd_fidelityfx_framegeneration_dx12.dll` | 4.0.2.4555 | 29,679,376 | `e6843252f58b0341a0d80f6a20bc0d840643ee95bc48c22cac08745344577bb6` |
| Cyberpunk 2077 `bin/x64/amd_fidelityfx_loader_dx12.dll` | 2.3.0.2740 | 26,376 | `e2d85aa05a9bd9ed8b38935fdf5199372cca6f74c12015143bb6f945ee1608aa` |

Immutable copies in `artifacts/original/cp2077-bin-x64/`.

## Findings (file offsets of the 4.0.1 DLL)

- A single DLL contains the ML FG and the analytical FG (FSR 3.1): 487 DXBC
  containers, SM 6.6 compute. Effect `FFX_EFFECT_MLFRAMEGENERATION` at `0x10d238`.
- 382 ML passes `mlfi_4k_pass0..190` and `mlfi_8k_pass0..190`; 105 shaders of the
  classic FG (optical flow, `0x2534ea0`).
- Weights: uncompressed block at `0x2b074c` (RVA `0x2b1f4c`), 10,657,332 B;
  table of 128 records of 32 B and payload from `0x2b176c` of 5,324,784
  values. Statistics compatible with **FP16** (0.74 % representable in E4M3,
  uniform mantissa); high confidence but not proven by tracing
  descriptors. Second identical copy at `0x152a400`. The payload is
  byte-identical in 4.0.2 of SDK 2.4.0 (`0xdd704c`).
- Matrices via AGS intrinsics ("magic UAV" `u0`, space `0x7FFF0ADE`): 156 of
  382 passes. Example: `mlfi_8k_pass59` at `0xd3b380`. No non-`mlfi` shader
  uses it.
- AGS census (decoder according to dxil-spirv `34f0ff84`, `dxil_ags.hpp`):
  8,048 `WaveMatrixMulAcc`, all 16x16x16 with F32 accumulator:
  `F16` 6,016 (74.8 %) and `FP8_FP8` 2,032 (25.2 %). FP8 only in
  paired `pass158..186` (15 per variant), with `F32→FP8` conversions in the
  shader. 4k and 8k have identical counts.
- Requirements: wave32 (`32x1x{1,2,4}`, `WaveSizeRange {32}` in 32 passes), maximum
  TGSM 4,096 B in `mlfi`.
- Imports: only `dxgi!CreateDXGIFactory2` relevant; no static AGS/amdxc64/nvapi.

## Implications for Xe2/XMX

- FP16 is native in XMX (`8x16x16 f16→f32` in ANV). FP8→FP16 is exact, so the
  FP8 passes can be emulated exactly by rounding to the FP8 grid and
  multiplying in FP16 with F32 accumulation.
- The blocker is not the data type but the layout: the shaders assume wave32 and
  16x16 matrices with RDNA element distribution; ANV Xe2 uses subgroup 16 and
  M=8. A port must translate matrix semantics, not copy elements per lane.
- Shared memory is low (≤ 4 KB), unlike `k_attn` in the 4.1.2 upscaler.

## 4k pass map (`tools/mlfi_pass_map.py`)

- 4k and 8k have the same normalized IR in the 191 pairs; only resolution
  constants change. The weight offsets are identical: it is enough to port the
  4k variant.
- Histogram of the 191 passes: `param_store` 88, `matmul_f16` 63,
  `param_load` 16, `matmul_fp8` 15, activation 4, resample 3, pack 2. Only the
  78 passes with WMMA need replacement; the rest do not use AGS.
- 60 distinct kernel bodies (20 templates with ≥3 members and 38
  singletons, almost all large matmuls). KxK conv and 1x1 GEMM cannot be
  distinguished statically.
- A single `u0` buffer carries weights and activations. Weights are addressed
  with compile-time constants (659 offsets, invariant between 4k and 8k);
  activations scale with resolution. The 128-record table is not a directory of
  those offsets.
- First candidate to port: `mlfi_4k_pass26` (`0xf7cde0`, `32x1x4`, 9
  `MulAcc` F16).

## Port feasibility

- ML gate: the DLL loads `amdxc64.dll` dynamically and queries
  `AmdExtD3DCreateInterface` (RVA sites `0x6d7b` and `0xfe250`); there are no
  vendor ID checks. On Intel it falls back to the analytical FG.
- In vkd3d-proton without WMMA, pipelines with AGS fail in
  `d3d12_device_validate_shader_meta`: they never reach ANV, so the upscaler's
  CMK bridge cannot intercept them. The upscaler's XMX kernels came from nitec;
  this port requires writing them.
- lavapipe only exposes 8x8x8 without FP8: the reference has to be a CPU
  interpreter of DXIL+AGS with the FP16 blob.
- Local detail: `analysis/fg-401-static/port-feasibility.md`.

## Limits

- It was not tested which buffer binds the weight block to each pass; REA opened the PE
  but returned `provider_unavailable` on cross-references.
- The 128-record table does not close against the payload size.
- 52 shaders could not be disassembled with `llvm-dis`; none contains the magic
  UAV (byte search).

## Reproduction

```sh
python3 -I tools/build_fg_inventory.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/inventory.json
python3 -I tools/ags_wmma_census.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/ags-wmma.json
```

`ags_wmma_census.py` and `mlfi_pass_map.py` re-run on 2026-11-22: output
byte-identical.

```sh
python3 -I tools/mlfi_pass_map.py artifacts/original/cp2077-bin-x64/amd_fidelityfx_framegeneration_dx12.dll --output analysis/fg-401-static/pass-map.json
```
