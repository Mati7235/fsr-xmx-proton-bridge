# Synthetic image/sampler kernel probe

This is a lab-authored offline CM kernel, not an FSR kernel. `tools/build_image_probe.py`
assembles and compiles it with the extracted local IGC/ocloc toolchain only; it
does not load a driver or dispatch GPU work. The shared, canonical input/output
contract lives in `tools/image_probe_reference.py`; this builder imports
`contract()` and retains those fields unchanged in `probe-spec.json`.

## Kernel ABI and output

Entry point: `bridge_image_probe`. Entry args are in order: (0) read-only 2D
image, (1) stateful writable buffer, (2) sampler. IGC must emit image and buffer
BTIs for args 0 and 1 in that order; their numeric BTIs are read from zebin
metadata, never guessed. The sampler remains sampler index 0, not a surface BTI.
`llvm.genx.3d.sample.v64f32...` uses the IGC ABI order: opcode, SIMD predicate,
channel mask (`0xf`), `aoffimmi`, sampler index, surface index, then vector
operands. The probe uses `sample_lz` opcode 24 for explicit mip level zero and
the compiler-derived sampler/image indices. The IGC vISA 3D_SAMPLE reference
states that each enabled channel's SIMD lanes are contiguous, with each channel
starting in the next GRF; therefore the `v64f32` return is already channel-major.
No AoS shuffle is applied. Four channel-major `v4f32` chunks per channel are
written with the PRE-observed `llvm.genx.oword.st.v4f32` ABI; output is
`channel*16+lane`.

The signature is documented in Intel's
[vc-intrinsics definition](https://github.com/intel/vc-intrinsics/blob/v0.19.0/GenXIntrinsics/include/llvm/GenXIntrinsics/Intrinsic_definitions.py#L4314-L4329).
Return packing and opcode/channel semantics are documented in IGC's pinned
[3D_SAMPLE reference](https://github.com/intel/intel-graphics-compiler/blob/v2.10.10/documentation/visa/instructions/3D_SAMPLE.md).

The canonical oracle specifies a row-major 2x2 `R32G32B32A32_SFLOAT` image,
normalized U/V coordinates, linear filtering, clamp-to-edge, level 0, and
channel-major expected values. Its texels and coordinates intentionally include
different channels, texel centers, center interpolation, and clamped borders.
This CPU oracle is specific to this synthetic probe and is not an FSR reference.

CMK3 explicit heap mapping: set 0/binding 0 mutable array size 16; image slot 3,
output slot 7; push size 52 with table base 4. Push table mapping is generated
from actual arg-index/BTI metadata: table indices `[0,1]`, elements `[0,0]`, and
compiler-derived BTIs `[arg0,arg1]`. Heap elements 3 and 7 are passed as push
values by the harness; they must not be repeated as CMK3 elements. CM local dimensions are `(1,1,1)`; placeholder
shader workgroup is `(2,1,5)` and canary `(1,1,17)`. The trailing sampler DWORD
at byte 48 is ignored, matching the requested CMK3 reader path. The CMK header
keeps LWS `(1,1,1)`; the reader's hardware local size is `(32,1,1)`. `(2,1,5)` is
only the Vulkan placeholder selector and the requested artifact name
`wg2_1_5.cmk`; it must not be packed as CM LWS.

## Fail-closed payload audit

`audit_image_payload(zebin, native, spirv_disassembly)` and
`pack_image_probe(zebin, audit)` are public helpers for the later preparation
tool. They inspect this probe's metadata and native assembly, not the PRE-pinned
`build_report()` result. Cross-thread bytes are zeroed only after the restricted
native byte-liveness analyzer sees each recognized payload load fully overwritten
or dead before any possible read. Its assumptions are full constant execution
mask, 64-byte GRFs, and agreement between IGA send decoding and native encoding.
Unknown load shapes, any live read, unexpected argument order, changed ABI, or
an audit tied to another zebin refuses packing. This is narrow static evidence,
not a general payload proof or GPU validation.

Build to a new output directory (never overwrite an existing evidence set):

```sh
python tools/build_image_probe.py \
  --toolchain artifacts/extracted/intel-toolchain \
  --out build/image-probe-v01
```

Expected stable artifacts include `probe_bmg.bin`,
`disasm/.text.bridge_image_probe.asm`, `embedded-probe.spvasm`,
`payload-audit.json`, `probe-spec.json`, `placeholder.spv`, `canary.spv`, and
`wg2_1_5.cmk`, alongside sources, logs, summaries, and hashes. Compilation errors
are fatal and preserved; no constants/no-op replacement is accepted. `gpu_validated`
and `runtime_approved` remain false until a separately authorized manual test.

## Offline candidate and checks (2026-10-23)

**Use `build/image-probe-v16` for the manual test, not v15.** The integration
review found that the v15 CMK packet omitted bit 31 of the header's `barriers`
word. That bit is the reader's `cm_has_sampler` flag: native sample instructions
and an immutable Vulkan sampler do not initialize the CM sampler state without
it. v16 sets `0x80000000` (no real barriers), preserves the same audited native
kernel and enables the reader's immutable-sampler path. A CPU regression checks
this exact flag, CM LWS, table indices and zero descriptor elements.

The v16 zebin SHA-256 remains
`7f713f03dc41244e57c18402fa2503ecf2ff478bb4c8e359604331dd656c1460`;
its corrected CMK3 SHA-256 is
`91576c4406d2cd9bb21fd550d0b746b88f975498681443a25711572a794006ba`.
The complete audit and packet were regenerated during preparation of
`build/image-test-v01`, without GPU execution. Both Vulkan marker shaders pass
`spirv-val --target-env vulkan1.1`. The v15 details below remain compilation
history, not approval to run its incomplete packet.

The first five generated attempts failed with IGC `-11`; the source comparison found
structural causes rather than an opaque image limitation: the ext-inst import followed
the memory model, and constants were emitted inside the entry function after its
label. Moving imports/constants to SPIR-V logical sections fixed compilation. A valid
CM-without-image control passed `spirv-val --target-env spv1.1`. The full probe also
assembles; `spirv-val` stops at `OpTypeBufferSurfaceINTEL must appear in a block`, a
known unsupported Intel CM opaque type in the generic validator, not a remaining
constant/import layout diagnostic.

Final offline candidate: `build/image-probe-v15` (local/ignored). IGC reports
`Build succeeded`; native IGA contains a SIMD16 `send.smpl` with `sample_lz`,
the RGBA channel mask `0xf` and sixteen `store.ugm.d32x4t` output sends. The GenX intrinsic
definition documents argument order as opcode, predicate, channel mask, aoffimmi,
sampler, surface, then vector operands. IGC's vISA 3D_SAMPLE reference states each
enabled channel's SIMD lanes are contiguous and each channel starts in the next GRF;
the probe therefore uses channel-major slices directly, with no AoS shuffle.

The compiler-derived zebin BTIs are `[1,2]` for args `[image,output]`. Metadata
shows the image descriptor has no cross-thread pointer field; output arg 1 occupies
offset 8, and `private_base_stateless` offset 0, for a 16-byte cross-thread payload.
The probe-local audit found no possible reads of either 64-byte native payload load
response before overwrite/end under its declared assumptions. `prepare_image_test.py`
`validate_probe()` recomputed the complete audit and CMK byte-for-byte. The CMK has
table indices `[0,1]`, elements `[0,0]`, explicit heap set/binding `(0,0)`, base 4,
push size 52, compiler-derived BTIs, and CM LWS `(1,1,1)`; Vulkan selector remains
the placeholder `(2,1,5)` / file `wg2_1_5.cmk`. The immutable/heap descriptor contract
is still not GPU-validated.

`toolchain.json` records the local executable hash and its `26.35.39758` version
output (the executable is named `ocloc-25.18.1`; querying under the injected toolchain
library path instead returns unsupported-option status 226). The compile command
uses the extracted IGC/ocloc environment and target `0xe20b`. `probe-spec.json`
retains every field from the canonical CPU `contract()` unchanged and adds compile,
payload, and artifact hashes. No GPU dispatch occurred; `gpu_validated` and
`runtime_approved` remain false. Only the corrected v16 packet is used for the
manual workflow; compilation is not evidence of actual image sampling correctness.

SHA-256 for the local v15 evidence set:

| Artifact | SHA-256 |
|---|---|
| `probe.spvasm` | `6d2a9418e6407197b0ed2dc7f3a7db008f66a3b8bb07c84ddaabe1900c54fb61` |
| `probe.spv` | `1212a03c23405772176438a960c5f88275217784551cbf7a8cc4848f990d30d5` |
| `probe_bmg.bin` | `7f713f03dc41244e57c18402fa2503ecf2ff478bb4c8e359604331dd656c1460` |
| `disasm/.text.bridge_image_probe.asm` | `0b99a684a88ba6de59484cbc7f4cfd903f5ba27e6f4aff74e25294c8c76f402c` |
| `wg2_1_5.cmk` | `c14978e5c2a9cc9da1a2b383498038e7db7c0323fdf58185ef579f44c70e2b09` |
