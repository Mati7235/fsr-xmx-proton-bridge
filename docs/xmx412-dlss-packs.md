# XMX 4.1.2 DLSS packs (40104–40106) — execution path

Static analysis, CPU-only, of the three DLSS packs of the 4.1.2 build
(DLL SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`).
No code from the DLL or from the packs was executed; no driver, Steam,
prefixes, GPU, Wine or `artifacts/original` was touched. The 7z
`nvngx_dlssd_xmx.7z` was only listed, read-only (`7z l`: one
`nvngx_dlssd.dll` of 179 233 280 B, `2026-11-10 09:17:17`); nothing was
extracted or executed from it.
Tools: `tools/decompress_xmx412.py` + `tools/parse_cm_payloads.py` +
`tools/carve_spirv.py` (stdlib + local libwim, image never loaded).
Pins verified in `tests/test_xmx412_dlss.py` (21 CPU tests, fail-closed).

Short answer: **the DLSS kernels use the same igdext CM-SPIRV path as FSR
(Kernel + `SPV_INTEL_vector_compute`, `BufferSurfaceINTEL`
ReadWrite, DPAS/BTI, no samplers). They are not classic CUDA/NGX.**
They share the loader `FUN_180029640` with the FSR packs.

## Table pack → kernels → path → relevance for the bridge

| RCDATA (idx) | Bucket (loader) | Verified kernels | Execution path | Relevance for the bridge |
|---|---|---|---|---|
| 40104 (3) | DLSS K (DG2 + Xe2/Xe3) | 716: `k_gemm`×174, `k_linear`×160, `k_attn`×126, `k_mlp`×126, `k_block`×50, `k_stage`×48, `k_adapt`×32 | CM-SPIRV Kernel, `SPV_INTEL_vector_compute`, `BufferSurfaceINTEL` ReadWrite in 716/716, 64/716 with 1 `OpTypeImage` 2D Unknown, 0 samplers, DPAS2/DPASW + `lsc.load.bti`/`oword` | Same path as FSR: the CMK3/ANV reader for buffers + DPAS + BTI is reused. No samplers to port. Different blocker: weights `nvngx_dlss.dll` + `ScratchBuffer` + `token grid`, not `fsr-original.dll` nor PRE magenta. |
| 40105 (4) | DLSS E / F | 312: `e_conv`×240, `e_stage`×64, `e_adapt`×8 | Same: 312/312 `BufferSurface` ReadWrite, 40/312 with 1 2D Unknown image, 0 samplers, `dpas2` + `lsc.store/load.bti` + `scatter4.typed`/`3d.load` in a minority | Same. Convolutional (`e_conv`) + typed stores; no `sampler_t` nor `3d.sample`. If the bridge handles buffers + one Unknown image, it covers E/F without a dynamic sampler. |
| 40106 (5) | DLSS-MX (DG2) | 67: `k_gemm`×19, `m_layer`×18, `k_mlp`×10, `m_stage`×10, `m_attn`×8, `m_adapt`×2 | Same: 67/67 `BufferSurface` ReadWrite, 3/67 with 1 2D Unknown image, 0 samplers, `dpas2`/`dpasw` | Mixed variant `k_` + `m_`; same conclusion. Small volume (5.4 MB), useful as a test case for the reader. |

Total DLSS: **1 095** envelopes (716+312+67). Total for the six packs: 1 977.

Verified sizes (compressed → decompressed, raw SHA-256):

- 40104: 8 031 050 → 42 477 193, `a9ea6724…7054ea`
- 40105: 3 421 152 → 19 590 261, `7ac547ee…57d246fa`
- 40106: 1 001 522 → 5 443 681, `03c18858…5a331ac3`

`raw.count(SPIRV_MAGIC) == cm_envelopes` in all three (716/312/67).
Gaps: 712/307/66 gaps, all zero (`all_zero`), zero DXBC candidates.
The FSR packs 40102/40103 also have zero gaps; only 40101 has
18 DXBC + 24 non-zero gaps. DLSS is pure CM plus zero padding.

## Names and args/types

- Entry points via `tools/carve_spirv.py` (OpEntryPoint, `model=6` Kernel in
  1 095/1 095): distributions above, sum == envelopes. Fails closed if it differs.
- Input interface: **1–2 × `v3i64` `Input`** (cross-thread payload,
  not descriptors):
  - 40104: 282×1, 434×2; 40105: 272×1, 40×2; 40106: 23×1, 44×2.
  - Never `BufferSurface`/`Image` directly in the interface; the surfaces go
    via BTI/internal stateless (immediates) + `BufferSurface` state.
- Internal types per module:
  - `OpTypeBufferSurfaceINTEL` (opcode 6086, `access=2` ReadWrite): **1 per
    module in 1 095/1 095**, as a function parameter type
    (`OpTypeFunction` with `(i32, BufferSurface)`). Same as FSR.
  - `OpTypeImage` (`dim=1` 2D, `depth=0`, `arrayed=0`, `ms=0`, `sampled=0`,
    `format=0` Unknown): 64/716, 40/312, 3/67. FSR 40101: 36/252 with 2
    images. Unknown format identical to the PRE.
  - `OpTypeSampler` (26) and `OpTypeSampledImage` (27): **0 in 1 095/1 095**.
    FSR has 18–36 modules with a sampler; DLSS none. In IR: zero
    `p2opencl.sampler_t`, zero `3d.sample`; only `3d.load` (64/16/2),
    `scatter4.typed` + `lsc.store.quad.typed.bti` in the minority with an image,
    plus `address.convert ...p1opencl.image2d_{ro,rw}_t`.
  - Rest: `lsc.load.bti`, `oword.ld/st`, `vload/vstore`, `rdregion/wrregion`,
    `dpas2` (`v128f32…`, `v64f32…`), `dpasw` (`v64f32…`), `fence`, `lsc.*.slm`.
    `dpas2`/`dpasw` are in **`llvm.genx.*` names inside the IR**, not in
    gaps (correction to the “gap strings” statement of the previous envelope).
- Execution modes per module: `31`, `35(1)`, `5618`, `6417` in 100 %,
  same as FSR 40101/40103. `5618(0)` is the majority (390/716, 272/312, 38/67)
  plus variants `8192/4096/2048/3072/…`; same CM vector-compute profile.
- Extensions per module: `SPV_INTEL_vector_compute` +
  `SPV_KHR_no_integer_wrap_decoration` in 1 095/1 095,
  `OpenCL.std` in 1 095/1 095. No CUDA/NGX extensions.
- Trailers (`-vc-payload` + verified lengths):
  - B always `␣-target-features=+ocl_runtime` (716/312/67).
  - A: 40104 `…'-noDPASMacro'`×442 + `…-ze-exp-register-file-size=256…`×274;
    40105 ×192+×120; 40106 ×49+×18. FSR 40101 is `-vc-payload` only;
    40102/DLSS carry `-noDPASMacro`. `register-file-size=256` only in DLSS.

## igdext/CM-SPIRV or classic CUDA/NGX?

CM-SPIRV via igdext, evidence:

1. Binary: SPIR-V Kernel + vector-compute + `BufferSurface` + DPAS/BTI in
   100 %; Unknown images without samplers; same modes as FSR; zero gaps without
   DXBC/CUDA/NGX. Search for `ngx/cuda/nvngx/dxbc` (lowercase) in the raw packs:
   absent (except `dxbc`, omitted due to x86 noise; the uppercase `DXBC` marker
   is zero via `gaps[].dxbc_candidates == []`).
2. DLL (read-only, `artifacts/extracted/fsr-xmx-412/…dll`):
   zero `k_gemm/k_linear/e_conv/m_layer`, zero `CUDA`, zero `NVNGX/NGX`,
   zero `40104/40105/40106`. Only lowercase weight-file references:
   `nvngx_dlss.dll` (8 strings: “requested without verified
   nvngx_dlss.dll weights … K/E-F/M”, “with the K weights (or reconstruction
   tables not bit-exact)”, presets L/M).
3. The same DLL does include the Intel route: `igdext64.dll` (17),
   `INTC_D3D12_*` (`CreateDeviceExtensionContext`, `CheckFeatureSupport`,
   `CreateComputePipelineState`, `GetCachedBlob`), `CM-SPIRV` (29),
   `OPTIONS1/OPTIONS2`, `root signature`, `production ABI`.
4. FSR vs DLSS logs: `Failed to load P6 N32…` / `P7 FullFusion…` /
   `P1 H1 DPAS…` / `P10 X1 Low128…` exist **only for the FSR leg**
   (35 `Failed to load…`, 6 `FullFusion`). None `Failed to load k_*` /
   `e_*`. The DLSS leg logs differently: `DLSS K/E-F/MX … initialization/
   output dispatch failed`, `ScratchBuffer too small`, `requested without
   verified nvngx…`, `DLSS K ready: %u kernels, %zu params bytes, token grid
   %ux%u`, `DLSS %s ready: %u kernels…`, `needs the depth buffer` (MX),
   profiles `DLSS-KX/MX/LX/EX/FX`, `FSR4_XMX_DLSSK/DLSSM/DLSSE`, `[DLSSK PROFILE]
   …`, `[DLSSK ASKIP]…`. That is, the same compilation path, with a different
   dispatcher/weights.

## Do they share the loader `FUN_180029640`?

Yes. `tools/decompress_xmx412.EXPECTED` pins `index = rid-40101` for
40101–40106 (DLSS = 3,4,5), exact `res_size/raw_size/SHA-256/cm_envelopes`,
`MOV ESI 0x9CA5…0x9CAA`, sizes `0x21B5796…0x531061`, clamp `>5→0`,
`GetModuleHandleExW→FindResourceW(h,id,10)→LoadResource→SizeofResource→
LockResource`, `Cabinet.dll` ordinals 40/43/45 (`ECX=5` LZMS, 64 KiB),
`BCryptHash(0x41)` SHA-256 + `strcmp` against the compiled digest, cache by
index under a mutex, logs `embedded pack %u invalid: …` /
`embedded %s pack loaded: … SHA256 verified` with `bucket=%s`
(`DLSS K (DG2 + Xe2/Xe3)`, `DLSS E / F`, `DLSS-MX (DG2)`). No AES/ChaCha.
See `docs/xmx412-pack-envelope.md`. The three DLSS packs verify through that
same path (`packs_from_resdir` + `decode_and_verify` in the tests).

## Contrast with the DLL strings (summary)

| Signal | FSR (40101–40103) | DLSS (40104–40106) |
|---|---|---|
| `Failed to load P6 N32…` / `P7 FullFusion…` / `P1…P12…` | Present (35) | Absent for `k_/e_/m_`; DLSS does not log per kernel |
| `CM-SPIRV PSO creation failed` / `igdext64.dll for passN` | Present per pass | No per-kernel equivalent; global `igdext` + shared `CreateComputePipelineState` |
| `DLSS K/E-F/MX … ScratchBuffer/token grid/kernels/weights` | N/A | Present (68 `DLSS…`, 34 `ScratchBuffer`, 19 `weights`, 4 `token grid`) |
| `k_gemm/e_conv…` in DLL | N/A (only in packs) | Absent in DLL (only in SPIR-V) |
| `CUDA/NVNGX/NGX` | Absent | Absent (only the `nvngx_dlss.dll` weight file) |
| `embedded pack %u invalid` / `embedded %s pack loaded` / buckets | Shared | Shared (same table 0–5) |

## Relevance for the bridge

- **There is no CUDA/NGX backend to bridge.** If the shim + ANV already create
  `CreateDeviceExtensionContext 4.20.0` + `CreateComputePipelineState` for
  CM-SPIRV with `BufferSurface` + DPAS + BTI + `Unknown` images without
  samplers, the 1 095 DLSS kernels travel the same path as the PRE/FSR passes.
  Priority stays on FSR (magenta/fail-stop, tables per SurfaceIndex/sampler,
  `pre-resource-map.md`).
- **Differences to isolate:** weights outside the pack (`nvngx_dlss.dll`
  verified, bit-exact reconstruction tables), `ScratchBuffer` per bucket,
  `token
  grid %ux%u` instead of `baseDispatch` FSR, presets `KX/MX/LX/EX/FX` and env
  `FSR4_XMX_DLSSK/DLSSM/DLSSE`, no `sampler_t`/`3d.sample` (smaller surface than FSR). Do not reuse the PRE
  oracle nor assume the same BTI/offsets.
- **Settled risks:** strings do not prove dispatch; `S_OK`/overlay is not
  success; injection evidence + deterministic readback is required, as in
  `docs/compatibility.md`. DLSS-MX (67 kernels, 5 MB) is the cheapest candidate
  if an isolated DLSS dispatcher is ever tested, always in a disposable prefix
  and never in the game (Spider-Man uses a separately patched
  `nvngx_dlssd.dll`, not analyzed here beyond the `7z l`).

## Limitations

- Static and CPU-only; no Ghidra/REA with execution, no IGC/ocloc, no Wine.
- Kernel names via `carve_spirv` + verified footers; not a full parser of the
  pack (weights/params between envelopes not classified, except zero gaps).
- `OpTypeImage Unknown` without format/dims; concrete BTIs and runtime
  `ScratchBuffer` require a trace (see `pre-trace-capture-spec.md` for FSR).
- The patched game DLL (`nvngx_dlssd_xmx.7z`) is out of scope beyond the
  listing; no Proton/GPU compatibility is claimed.
