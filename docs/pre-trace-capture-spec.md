# PRE native_1080: correlated capture spec for a future authorized trace

## Status and scope

Phase 1, CPU-only. This document **does not authorize** any PRE dispatch or any
GPU/Wine execution. It only defines what a future authorized trace of the
caller (`native_1080` path) must record in a disposable prefix, to resolve the
runtime data that static analysis cannot establish: allocated sizes, image
formats, initial bytes and the effective dispatch values.

Pinned static context (verified locally by SHA-256 on 2026-11-12):

| Artifact | SHA-256 |
|---|---|
| DLL `amd_fidelityfx_upscaler_dx12.dll` | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` |
| `analysis/fsr-xmx-disassembly.txt` | `4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0` |
| local `d3d12.h` (LLVM-MinGW) | `23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e` |
| local `dxgiformat.h` | `8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48` |
| PRE CM envelope (`cm-payloads-0001/module-0000.cmspv`) | `76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b` |
| PRE Xe2 zebin (`offline-pre/full/pre_bmg.bin`) | `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2` |
| native code (`code_sha256` of the profile) | `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f` |
| `offline-pre/full/ze_info.yaml` | `5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c` |
| IGA disassembly of `.text.fsr4_pre_xmx` | `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660` |
| IR `fsr-resources/xe2-first.spvasm` | `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e` |

Analysis references: dispatch and provenance in
[xmx412-dispatch.md](xmx412-dispatch.md) (function `FUN_1800163c0`,
grid formula, stock bindings by name, fail-stops, helper `0x180002df0`,
vtables against `d3d12.h`); contract in
[validation.md](validation.md); typed
views in [xmx412-dispatch.md](xmx412-dispatch.md).

## Goal of the trace

Record, correlated by resource/descriptor ID, everything the normal path
`0x1800163c0..0x180017b6e` consumes right before the first PRE `native_1080`
dispatch, and dump pre/post bytes without modifying the observed state. The
trace is input evidence, not a functional oracle nor a proof of correctness.

## Slot map the trace must resolve

Slots relative to the heap/table used by the normal path (not absolute indices):

| Resource heap slot | Arg | Root | BTI | Expected content (static) |
|---|---|---|---|---|
| 0–6 | 2–8 / t0–t6 | 3–9 | 1–7 | ReadOnly images, copied by helper `0x180002df0`; source index at runtime |
| 7 | 0 / u0 | 1 | 8 | UAV `R8_UINT BUFFER`, `NumElements = Width` (`GetDesc` requires `Dimension == 1`) |
| 8 | 1 / u1 | 2 | 9 | ReadWrite destination image, copied at `0x18001727e` |
| 9 | 9 / t7 | 10 | 10 | SRV `R8_UINT BUFFER`, `NumElements = 0x840` (2,112 B), resource in context `+0xa80` |
| 10 | 10 / t8 | 11 | 11 | SRV `R8_UINT BUFFER`, `NumElements = 0x80` (128 B), resource in context `+0xa98` |
| sampler heap 0 | 11 / s0 | 12 | — | linear/CLAMP sampler (see §6) |

Also `SetComputeRoot32BitConstant(rootIndex=0, value=0, destOffset=0)`:
**b0 = 0**; and `SetComputeRootDescriptorTable` 1…11 from the RVA array
`0x68988` (`0x180017410..0x180017435`), root 12 with the GPU handle of the
sampler heap (`0x180017543`).

## Capture blocks (all correlated by ID)

### 1. Resource creation

For each resource bound to slots 0–10, record the effective creation event
(`CreateCommittedResource`, placed/reserved or import):

- Full `D3D12_RESOURCE_DESC`: `Dimension`, `Width`, `Height`,
  `DepthOrArraySize`, `MipLevels`, `Format`, `SampleDesc`,
  `Layout`, `Flags`.
- `D3D12_HEAP_PROPERTIES` + `D3D12_HEAP_FLAGS`, size and allocation offset
  when applicable.
- Resource ID (object pointer + creation sequence) to be used to correlate
  views, copies and barriers. Follow aliases and copies, not only handle addresses.

### 2. Views and descriptor copies

- Each `CreateShaderResourceView` / `CreateUnorderedAccessView`: associated
  resource (ID from §1), full `D3D12_*_VIEW_DESC` (format, dimension,
  `FirstElement`, `NumElements`, `StructureByteStride`, `Flags`,
  `Shader4ComponentMapping`), mip/layer/range, destination slot and heap.
- Each `CopyDescriptors*` (including the helper `0x180002df0` and the site
  `0x18001727e`): source heap, source index, descriptor increment, destination
  heap, destination slot 0–10, and the ID of the resource the source descriptor
  designated. For t0–t6 also note the selection register
  (`[rsp+0x78]`, `[rsp+0x7c]`, `esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx`).
- Pinned values that must match: arg 9 SRV `R8_UINT`, `0x1688`,
  `0x840`; arg 10 SRV `R8_UINT`, `0x1688`, `0x80`; arg 0 UAV `R8_UINT`,
  `FirstElement = 0`, `NumElements = Width`. Any deviation is recorded as a
  finding; the spec is not "corrected".

### 3. Pre-dispatch identity (`GetDesc` and handle resolution)

Right before the dispatch, for each heap slot 0–10:

- `GetDesc` of the bound resource (the same `+0x50` the DLL uses for arg 0).
- CPU/GPU handle → resource ID resolution from §1; detect aliasing
  (two slots to the same resource) and stale descriptors.
- For arg 0, verify the static guard: `Dimension == 1` and
  `Width >= factor² * 0x7e9000` (native_1080: factor 1, minimum 8,294,400 B),
  `Width <= 0xffffffff`. Record the effective `Width`: it is the size that
  dimensions the UAV; do not assume an exact allocation.

### 4. Buffer bytes: arg 9, arg 10 and arg 0 regions

- Arg 10: the full 128 B header exactly as the kernel loads it, with readable
  bytes and original flags. Fields used by the IR (DWORD offsets 8–84,
  address/bytes at 64–80, flags byte 100, base at byte 104). The base at byte
  104 is a **byte offset relative to the arg 0 buffer** conditioned on bit
  `0x2000` (`base` versus `base+16`), not a VA.
- Arg 9: the 2,112 B visible through the SRV.
- Arg 0: at minimum the 16 B float4 record at `base + {0,16}` and the OWORD
  write plane (`índice = wg_y*960 + wg_x*8`, 16 B per OWORD, exclusive end
  8,294,400 B for a 120×540 grid). Recommended: full pre/post dump of the
  backing resource, since it contains input/scratch regions and output whose
  exact relationships depend on the arg 10 header. Do not initialize it as an
  empty readback buffer.
- Dump pre **and** post dispatch without modifying the observed state; keep the
  original capture intact.

### 5. GPU handles, bases and increments

- `GetGPUDescriptorHandleForHeapStart` of both heaps (resources and sampler),
  CPU/GPU bases, `GetDescriptorHandleIncrementSize` per heap type.
- Effective root table: the 11 GPU handles passed to
  `SetComputeRootDescriptorTable` + the sampler handle to root 12, with the
  slot→arg→BTI correspondence from the table above.
- Source increment used by the helper (`ctx+0x1b40` + `sourceIndex *
  increment`).

### 6. Sampler descriptor

Full `D3D12_SAMPLER_DESC` of slot 0 of the sampler heap: expected static
values MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, `MaxAnisotropy` 1,
ALWAYS comparison, `MinLOD` 0, `MaxLOD` FLT_MAX. Record any deviation and the
actual heap/table used at root 12.

### 7. Context sequence and blobs

- Public boundary: `ffxCreateContext` (`0x180001290`), `ffxDispatch`
  (`0x1800013b0`), `ffxQuery` (`0x180001400`); internal wrapper
  `0x1800058a1..0x1800058e6` and calling site `0x1800058be`
  (`rcx=estado, rdx=registro, r8=interfaz D3D12`).
- Record whether the PRE dispatch **reuses** an already-created
  context/device/queue (known limitation of the context patch, see
  [shim-bridge.md](shim-bridge.md)) or creates a new one, and
  with which parameters (`CreateDeviceExtensionContext` 4.20.0,
  `CheckFeatureSupport` OPTIONS1/XMX and OPTIONS2/SIMD16Required).
- Record calls to `GetCachedBlob` and their result (in the reference shim it
  is E_NOTIMPL; whether it is mandatory is not established).
- Record observed constants/models (`4.0.2x`/`4.0.2xm`, reading of
  `fsr-original.dll`) only as provenance, without attributing semantics.
- Record any fail-stop emitted (strings in
  [xmx412-dispatch.md](xmx412-dispatch.md): params not ready, missing
  stock binding, incomplete constants, ABI `0x5058`, ScratchBuffer layout,
  geometry not available, parity ring full).

### 8. Dispatch grid and transitions

- `ID3D12GraphicsCommandList::Dispatch` arguments: static formula
  `x = (w+15)>>4`, `x += x&1`, `y = h>>1` with `w = *(ctx+0x840)`,
  `h = *(ctx+0x844)`; for 1920×1080: `(120, 540, 1)`. `FUN_18001c9c0` modes:
  2–3 → no PRE dispatch; 4 → `(1,1,1)`; 5 → `(x,1,1)`;
  6 → `(x,0x44,1)`. Record the effective `w/h` and the observed mode.
- `ResourceBarrier` with states (`0x40`/`0x400`/`0x800`) around the copies,
  `SetDescriptorHeaps`, `SetPipelineState`, and the state/transitions of each
  resource pre/post.
- The CM/hardware local size and the execution mask are **not** `Dispatch`
  arguments: they require separate evidence from the driver/launcher (see
  [xmx412-dispatch.md](xmx412-dispatch.md)). Do not substitute
  them with `1×1×1`, `SubgroupSize 1` or the Vulkan selector.

## Correlation by ID and preservation

- Each evidence row cites `resource_id`, `heap_id:slot`, event and sequence. A
  handle without a correlated resource ID is an incomplete capture.
- Observed stock wide names (10, by provenance, not by semantics):
  `MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
  `r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`,
  `r_depth`, `r_input_exposure`, `r_auto_exposure_texture`.
- Store pre/post bytes, the original capture and registered versions
  ([checklist](pre-trace-version-checklist.md)) under `runs/<id>/evidence/`.
- Do not rename t0…t8 to color/depth/etc.; do not reinterpret the `7` in the
  store's `.xyz` mask as a binding; u1 (arg 1/BTI 9) is the store destination,
  t6 (arg 8/BTI 7) is not turned into a UAV by that store.

## What this capture does not establish

Initial format/content of the 8 images, PRE output oracle, functional
correctness, Proton/VKD3D equivalence, nor the validity of reusing these values
outside the traced `native_1080`. The approval criterion remains the one in the
[validation.md](validation.md).
