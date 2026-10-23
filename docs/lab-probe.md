# Synthetic DPAS/resource-map probe

This is a lab-authored offline compilation probe, not the FSR kernel. It does not
dispatch work to a GPU and its output is not GPU-validated.

## IGC crash diagnosis

The initial `build/lab-probe-v02/compile.log` reported IGC internal error `-11`.
The imported `llvm.genx.dpas2.v128f32.v128f32.v128i32.v64i32` signature and its
six scalar controls match the PRE SPIR-V in
`analysis/fsr-resources/xe2-first.spvasm` (DPAS declaration around line 3121,
call around line 15810). To isolate the compiler failure, a local CPU-only
control was compiled with the DPAS call removed: it still failed while retaining
the probe's `llvm.genx.oword.st.v128f32` import/call. Removing that store call
made the control compile. Thus the evidence points to the unsupported 128-float
OWord-store intrinsic, not to DPAS. This is specific to this compiler path; it
does not prove the only possible cause of other IGC crashes.

The source now uses the PRE-observed `llvm.genx.oword.st.v4f32` ABI: BTI, OWord
index, and four `f32` values. The PRE computes its second argument as
`byte_offset / 16`; therefore each 128-float result is split into 32
four-float stores with OWord indices 0 through 31. This covers exactly the
512-byte output while using the known-supported intrinsic form.
DPAS operands remain packed FP16 numeric-one data and the real DPAS call remains
in the generated kernel; no constant-result replacement is accepted.

## Cross-thread payload audit and runtime block

`tools/audit_pre_payload.py build_report()` is deliberately tied to the fixed PRE
input/zebin/native/IR hashes, so it is **not applicable as a whole** to this new
probe. The probe build instead audits the exact generated zebin, its embedded
SPIR-V, and its native IGA disassembly before it will zero CMK cross-thread bytes:

- The embedded SPIR-V must match the assembled input. The restricted argument
  audit requires all eleven entry parameters to be opaque read/write buffer
  surfaces, each used exactly once by `llvm.genx.address.convert...`; direct
  pointer loads or additional argument uses fail closed.
- Zebin payload metadata is pinned to eleven stateful/global 8-byte arguments at
  offsets 8..88, the 8-byte `private_base_stateless` at offset 0, and one
  6-byte `packed_local_ids` per-thread field. Any changed or extra payload shape
  is rejected.
- The existing auditor's restricted `audit_native()` byte-liveness routine is
  reused on this probe's own native assembly (not its PRE `build_report`). It
  finds exactly three `bti[255]` cross-thread load responses (64-byte GRFs in
  `r1`, `r2`, `r3`); all three are unread before their complete overwrite. The
  report records the three instruction lines and overwrites. Its explicit
  assumptions are full constant execution mask, 64-byte GRFs, and agreement of
  IGA-decoded send descriptions with native encoding.

This is narrow static evidence for this compiler output, not a general payload
proof or GPU test. If metadata, SPIR-V use, native load shape, hashes, or liveness
change, the packer refuses to emit CMK. `payload-audit.json` is the recorded
evidence for the build below. Runtime remains blocked: no driver injection or
deterministic GPU readback has been validated.

## Explicit heap mapping for the synthetic harness

The Mesa reader's `heap_set == 0xffffffff` path only auto-discovers a
`VK_DESCRIPTOR_TYPE_MUTABLE_EXT` binding with array size at least 1000. The
synthetic Vulkan harness instead declares set 0, binding 0 as
`STORAGE_BUFFER[16]`. The CMK is therefore emitted as **CMK3** with explicit
`heap_set=0`, `heap_binding=0`; CMK3 retains the reviewed table base 4 and
expected push size 52. This is probe-local and does not change the PRE/FSR
profile or the adapter's automatic-heap behavior. The source review in
`lab/README.md` identifies a usable surface-state representation for this binding
in a DIRECT layout. The harness requires the driver's layout/stride log before
dispatching the probe. This gate has not been exercised; descriptor integration
is not runtime-validated.

The reader also maps header `grf_count` directly to `grf_used` and CMK LWS to
`local_size = (lws.x*32, lws.y, lws.z)`. This probe therefore accepts only its
observed 128 GRFs and CM local dimensions `(1,1,1)`; this is a probe-specific
fail-closed restriction, not a claim that the reader validates arbitrary GRF or
dimension values.

## Offline evidence

Reproduction with local IGC `2.10.10+18926` / ocloc `25.18.33578.6`:

```sh
python tools/build_lab_probe.py \
  --toolchain artifacts/extracted/intel-toolchain \
  --out build/lab-probe-v09
```

The build completed successfully. `summary.json` reports `has_dpas=true`,
SIMD size 1, GRF count 128, eleven arguments mapped in order to BTIs 1 through
11, stateful global buffers, 96 bytes of cross-thread payload, and 6 bytes of
per-thread packed local IDs. `disasm/.text.bridge_probe.asm` contains the native
instruction `dpas.8x8 (16|M0) ...`. The generated CMK header is CMK3 with
`(heap_set, heap_binding, table_pc_base) == (0,0,4)` and its extension is
`(flags, expected_push_size) == (1,52)`. The output spec records resource heap
slots `[7,8,0,1,2,3,4,5,6,9,10]` and `gpu_validated: false`.
The output also records `runtime_approved: false`; the v09 reason string predates
the completed source-level descriptor review, not a GPU test. Zebin SHA-256 is
`2766e9c9c44171e7b86e2daded4f7e5d5cacd110e8c88bdb757b6a6d78c9340f`, native
assembly SHA-256 is
`0775e578d67dd1335ed575317f4e27f4323002cddaf04fe92537bab2b7f0570d`, and the
CMK3 SHA-256 is
`7de3eb4bd22de3d10e7de6137929570dfd261fdf716daf9b54e8b6334757560a`.

This verifies offline compilation, native DPAS presence, and compiler-emitted
argument/payload metadata plus the restricted static payload audit only. It does
not verify storage-buffer descriptor integration, resource contents, numerical
readback, injection, or runtime compatibility on any GPU.
