# PRE native_1080: static contract for a controlled test

## Status and scope

This document specifies what can be prepared for **PRE Xe2 pack 40102,
native_1080**. It does not authorize a dispatch nor declare the bridge compatible. The
pinned DLL (`3eb086…eba53`), the complete pinned CM blob (`76942f…773b`) and the PRE
compiled for Xe2/B580 (`0xe20b`; zebin `3e974d…e01b2`) were analyzed statically. No DLL,
shader or GPU was executed in this work.

The repeatable extraction `python tools/inspect_pre_inputs.py
analysis/fsr-resources/xe2-first.spvasm` validates the SHA-256 of the textual SPIR-V and
extracts types/guards without assigning scene semantics. CPU tests:
`python -m unittest discover -s tests -p test_pre_inputs.py -v`.

## Confirmed contract

### Shader/dispatch

- Entry: `fsr4_pre_xmx`; 12 arguments in this order:
  0 `BufferSurfaceINTEL ReadWrite`, 1 `Image2D ReadWrite`, 2–8 seven
  `Image2D ReadOnly`, 9–10 `BufferSurfaceINTEL ReadWrite`, 11 sampler. In the pinned IGC
  mapping, the respective BTIs are `8,9,1,2,3,4,5,6,7,10,11` and sampler index 0 (source:
  `analysis/offline-pre/full/ze_info.yaml:15-160`, `docs/offline-pre-compilation.md:54-76`).
  The DLL's root signature additionally contains b0 and the s0 table
  (`docs/pre-resource-map.md:123-150`).
- The shader compares `WorkgroupId.x >= 120` and `WorkgroupId.y >= 540` and returns for
  either case (`analysis/fsr-resources/xe2-first.spvasm:5166-5185`). Therefore, to cover
  the full admitted region, the minimum grid candidate is **120×540×1 workgroups**; smaller
  X/Y leave groups unprocessed, larger ones are discarded by the guard. Z is not used in the
  inspected entry. This is a limit derived from the code, **not** a proof that each group
  covers 16×2 pixels nor that the host runtime dispatches this way. The correct local
  dimensions are still not established (do not infer them from `SubgroupSize 1` nor from
  the provisional packer `1×1×1`).
- There are GenX image load/sample calls and a typed quad store. The `OpTypeImage`
  declares format `Unknown`; the images are 2D, but we cannot derive the Vulkan format,
  channels, color space, scale, depth/motion values or test contents. The extractor
  records 78 syntactic `3d_load` calls, 85 `3d_sample` and one `typed_quad_store`; those
  counts are not equivalent to per-pixel reads nor do they assign each operation to a
  resource. Do not rename t0…t8 as color/depth/etc.
- **The store does NOT use BTI 7.** The exact signature in `xe2-first.spvasm:3057-3068` is
  `(predicate, i8, i8, i8, i32 surface, u, v, r, lod, data)`. In the call at `:15312`, the
  three `i8` values are `0,0,7`; the 7 is the channel-enable mask `.xyz`, not a surface nor
  a LOD. The `i32 surface` is `%9780`, with SSA chain
  `%9780 <- %3391 <- %9774 <- %3397 <- %9769 <- %3460 <- %3749 <- %3656 <- %1687`,
  where `%1687` converts the **arg 1 Image2D ReadWrite** (`:3180-3181`, `:5152-5154`,
  `:5238-5250`, `:15278-15312`). The zebin confirms arg 1 → BTI 9 (`ze_info.yaml:138-143`),
  and the final IGA emits two `store_quad.tgm.d32.xyz.a32.bti[9]` with coordinates
  `u,v,r,lod` (`analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm:1972-1973`). It also
  matches root 2 / u1, the ReadWrite image (`pre-resource-map.md:139-142`).
  **Result:** there is no conflict with arg 8/t6; t6 (arg 8, BTI 7) is not the destination
  of that store. Do not reinterpret the 7 as a binding nor change permissions.
- The DLL's root signature and dispatch preserve the D3D separation: u1 is in root 2, t6 in
  root 9; the normal loop calls `SetComputeRootDescriptorTable` with indices 1…11 and the
  handle array (`0x180017410..0x180017435`, `pre-dispatch-snippet.txt:76-89`). In the
  reconstructed map, u1 uses heap slot 8, t6 slot 6 (`pre-resource-map.md:136-150`). No
  conversion of arg 8/t6 to a UAV is needed to explain the store: the destination is arg
  1/u1 itself, whose descriptor must be writable per the signature. The DLL also creates D3D
  views in other branches; without a caller trace, a concrete
  `CreateUnorderedAccessView`/`CreateShaderResourceView` call is not attributed to each
  handle, but that attribution no longer changes the kernel binding.

### ABI and arguments

- The DLL creates b0 as a one-DWORD root constant and roots 1–11 as a per-surface descriptor
  table, plus root 12 as the sampler (`pre-resource-map.md:123-150`). The expected push
  order/offset according to the reference VKD3D is: b0 offset 0; surfaces offsets
  4,8,…,44; sampler offset 48; total range 52 bytes. This is a static VKD3D reference, not
  a capture of Proton in use. In the normal setup the DLL emits a call with the four
  arguments `rootIndex=0, value=0,
  destOffset=0` before the tables (DLL `0x1800173e0`, vtable `+0x108`); the following
  loop binds roots 1–11 at `0x180017410..0x180017435`. Therefore **b0 is fixed to zero**;
  it is not a dimension/scale field that the harness must guess. It does not appear as one of the 12 arguments of the entry nor as a cross-thread
  argument of the zebin. For this kernel it is a root-constant filler not consumed by the
  reviewed IR; keep it at zero.
- The normal PRE ABI needs 11 tables in the resource heap and s0 in a separate sampler heap.
  Pinned profile: explicit base push 4 and the `arg_index -> BTI` correspondence above. The
  candidate CMK3 reader and the profile remain `experimental-offline-only`, not installed
  nor integrated into the runtime.
- The sampler that the DLL creates uses MIN/MAG/MIP linear + CLAMP U/V/W; the ANV fallback
  partially matches, but it is not generally equivalent. Do not omit it in the image/sampler
  test nor assume bilinear exactness without comparing.
- Stateful buffers do have real use; distinguish them from their eight extra payload bytes.
  `u0`/arg 0/BTI 8 (heap slot 7) is a mixed-access buffer: the IR does a 16-byte
  `oword.ld.unaligned.v4f32` (`:5627-5634`) and stores of 16 and 128 bytes (`:5665`,
  `:15993`); the IGA includes `load.ugm...bti[8]` and stores `bti[8]`
  (`.text.fsr4_pre_xmx.asm:139,146,2297`). The float4 access at `:5627` uses an address
  derived from arg 10: its initial 128-byte block is loaded at `:5190-5220` and the fields
  read include offsets 8–84, DWORD/byte offsets 64–80, flags at byte 100 and a base offset in
  bytes relative to arg 0 at byte 104 (`:5261-5325`, `:5573-5602`). There is a guard on bit
  `0x400` of the flags; bit `0x2000` selects between `base` and `base+16` to read float4, and
  the first channel participates in the normalization/comparison. No semantic names are
  deduced for those fields. The final path writes 128 bytes of output per group to arg 0 at
  OWORD index `wg_y*960 + wg_x*8` (`:15977-15993`), when it passes its guard. So arg 0 must
  not be initialized as an empty readback buffer: it contains input/scratch and output
  regions whose exact relationships depend on the arg 10 header.
- The [host reconstruction](pre-resource-descriptors.md) identifies typed `R8_UINT BUFFER`
  views: UAV of arg 0 with `NumElements=Width`, SRV of arg 9 with 2,112 elements/bytes and
  SRV of arg 10 with 128 elements/bytes, from context `+0xa80`/`+0xa98`. For native_1080, the
  DLL requires BUFFER dimension and `8.294.400 <= Width <= 0xffffffff` on arg 0; the minimum
  comes from factor 1 of the variant table, not from assuming an exact allocation. The backing
  resources and their contents are not yet reconstructed. The synthetic probes do not
  automatically validate these typed views.
- The eight extra cross-thread bytes of args 0/9/10 and `private_base_stateless` are
  statically unread before overwrite/end **only under full and constant execution mask** for
  this zebin (`pre-payload-audit.md`). Those are payload fields, not the buffer resources:
  the opaque buffers are still present in the ABI. Keep the mask as an open gate; do not
  supply invented addresses nor generalize the audit.
- The DLL passes NULL CompileOptions and InternalOptions for this path; the complete CM blob
  preserves embedded options consumed by IGC. Input/kernel/hash/target must remain pinned as
  above.

## Safe preparation and criteria

The controlled test must be a future **isolated test in a disposable prefix**, with a
locally chosen ICD/driver chosen explicitly and without touching the user's Steam, real
prefix, services or drivers. Reuse the synthetic harness barrier: canary enabled, explicit
log of real injection, profile/cache identity pinned, DIRECT layout verified,
synchronization/barriers correct and repeatable GPU readback. The positive synthetic DPAS
probe covers only its own kernel/layout, not PRE.

Before the first PRE dispatch, the following are still required:

1. **After the image/sampler probe**, save exact evidence of formats, filters, normalized
   coordinates/texel space, limits, image transition and readback of that probe. Do not
   extrapolate its results automatically to the eight PRE images.
2. Independently determine the format, size, permissions/usage and contents of each image
   and the complete size/layout of the arg 0/9/10 buffers through an authorized caller trace
   (or verifiable documentation of its ABI). Arg 0 requires at least that the 16-byte
   register at `byte104 + {0,16}` and the OWORD write plane do not alias incompatible
   regions; arg 10 must cover the 128-byte header and its derived offsets. The static ABI
   does not give the allocated sizes nor the runtime addresses/offsets.
3. Capture/derive the local dimension of the dispatch on the real path and confirm that the
   effective grid covers 120×540; also verify the execution mask required by the payload
   audit. The `native_1080` size does not by itself establish concrete input sizes nor
   local size.
4. Identify the images by observed provenance/usage (not by intuition) and prepare
   deterministic values that are valid for each confirmed format. An exact capture of the
   resources before the dispatch would be a better oracle than invented patterns.
5. Obtain an independent PRE oracle: the output of the same input/resources/ABI in the
   reference implementation, or a CPU reference validated against it. The shader contains
   reduction/feature/model and weight constants; there is no simple static rule that allows
   declaring an expected output buffer/image. Without an oracle, limiting oneself to
   verifying injection, bounds/guards and absence of corruption outside the output does not
   establish functional correctness. See [reference options](pre-reference-options.md): a
   capture of the bridge that still fails is not automatically an oracle; another frontend
   for the same zebin can cross-check bindings, but it is not another implementation of FSR.
6. Review with hashes the real Proton/VKD3D version, the push layout, heap/sampler, the
   binding map and the lifecycle/synchronization before authorizing runtime.

**PRE approval criterion:** all the gates documented above; a repeatable test with fixed
input in a disposable prefix; evidence of the injection path and of the expected layout;
complete readback compared with the oracle (tolerances justified per format/operation, not
invented), with no differences in canaries/guard regions nor reads/writes out of range.
`S_OK`, PSO creation, an overlay label or the disappearance of magenta are not enough.

## Static evidence and exact limits

- The [pinned dimension inspection](pre-dispatch-dimensions.md) separates `simd_size`,
  native SIMD widths, the local ID payload and the Vulkan selector. It does not determine the
  local size nor validate the runtime mask; both gates remain open. Its inspector rejects
  altered metadata, zebin or disassembly.

- `analysis/fsr-resources/xe2-first.spvasm`: `OpTypeImage` Unknown types on lines 2473–2477;
  guards at 5166–5185; typed store signature/call and SSA at 3057–3068, 3180, 5152–5154,
  5238–5250, 15278–15312. `7` is `.xyz`, surface `%9780` derives from arg 1.
- `analysis/offline-pre/full/ze_info.yaml`: payload/arguments and BTIs; `profiles/` pins the
  input and zebin hashes. The audited IGA disassembly has hash
  `a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`; it is not an
  independent ISA decoder.
- `analysis/pre-dispatch-snippet.txt` documents the assignment of roots 1..11 and root 12
  sampler in the DLL. `docs/pre-resource-map.md` warns that the real Proton layout has not
  yet been cross-checked.
- The synthetic image is not real PRE data; the weights/model and the caller's semantic
  inputs are not reconstructed in this contract. The [dispatch decompiled with
  Ghidra](pre-dispatch-ghidra.md) fixes the grid formula, provenance via stock bindings and
  fail-stops; it does not establish initial contents, local size, runtime mask nor an
  oracle. Nothing here demonstrates a functional PRE, Proton compatibility or a correct
  visual output.
