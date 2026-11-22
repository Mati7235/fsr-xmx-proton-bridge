# Lab probes

Two synthetic probes live in this directory, both authored here and both separate
from the FSR kernel. `lab/bridge_probe.c` maps eleven resource-buffer arguments
through a DPAS kernel (`wg1_1_5.cmk`). `lab/image_probe.c` samples a 2x2 image
through a mutable descriptor set (`wg2_1_5.cmk`). Neither probe demonstrates
bridge behaviour, and neither runs on a GPU without `--run-gpu`.

The offline builders are `tools/build_lab_probe.py` and
`tools/build_image_probe.py`. They compile with the extracted local IGC/ocloc
toolchain, write to an output directory, and never load a driver. The shared
image contract lives in `tools/image_probe_reference.py`. The CPU tests are
`tests/test_lab_harness.py`, `tests/test_lab_probe.py`,
`tests/test_image_harness.py`, `tests/test_image_probe.py` and
`tests/test_image_reference.py`; none of them invoke Vulkan or the C binaries.

## Buffer probe

`bridge_probe.c` needs Vulkan headers and the Vulkan loader at link time. Use the
local Mesa build headers if present; do not install packages for this step. For
this checkout:

```sh
mkdir -p build/lab-harness
cc -std=c11 -Wall -Wextra -Werror \
  -Ibuild/mesa-26.1.2/include \
  lab/bridge_probe.c -o build/lab-harness/bridge_probe -lvulkan
```

Compilation is CPU-only. Running the executable without arguments reports
CPU-only mode and creates no Vulkan instance. GPU execution requires the explicit
`--run-gpu` opt-in.

Only use a disposable, deliberately prepared environment with the patched ANV
driver and the expected probe artifacts. The probe directory must contain
`placeholder.spv`, `canary.spv`, and `wg1_1_5.cmk` from
`tools/build_lab_probe.py`. Choose a new log directory for every run:

```sh
build/lab-harness/bridge_probe --run-gpu \
  --probe-dir /path/to/generated/probe \
  --log-dir /path/to/new/evidence-directory \
  --icd-manifest /path/to/local/mesa/icd.json \
  --icd-root /path/to/local/mesa/build
```

The harness resolves the ICD manifest `library_path` and requires that library to
be a regular file inside the supplied local Mesa build root. It then sets
`VK_DRIVER_FILES` and `VK_ICD_FILENAMES` to that manifest and removes inherited
Vulkan driver/layer selectors and all inherited `ANV_CM_*` variables before
setting the four probe values. It sets `VK_LOADER_LAYERS_DISABLE=*` in the child
process so loader layers, including implicit layers, stay off.
`icd-selection.txt` records the selected manifest, library and root. That records
the requested loader configuration, not which shared object the loader mapped;
`icd-driver.log` holds instance-creation diagnostics. The program does not set
`WINEPREFIX`, change the parent environment, or alter Steam, Proton prefixes,
drivers, or services.

Before device creation or submission it requires Vulkan to enumerate PCI
vendor/device `8086:e20b`. A missing artifact, ICD, local library, canary,
non-target GPU, layout evidence, or readback mismatch fails closed. A passing
readback alone does not prove bridge functionality.

The canary uses the `(1,1,17)` shader from the builder. The ANV injection patch
recognizes that workgroup size, writes `anv_canary` under `ANV_CM_SPV_DIR`, and
then lets the marker placeholder run. The harness checks the marker contents, the
marker word in buffer 0, and that every other word in all 16 storage buffers is
still sentinel. The target shader is separate: its `(1,1,5)` placeholder selects
the static `wg1_1_5.cmk` path. Both marker shaders come from
`build/lab-probe-v10` or a build of the same source. The historical v09 markers
wrote unconditionally from every invocation and raced.

### Descriptor layout contract

The first generator emitted `heap_set = 0xffffffff` (auto-discovery). In the
local Mesa source, `anv_shader_compile.c` auto-discovery only accepts a
`VK_DESCRIPTOR_TYPE_MUTABLE_EXT` binding with at least 1000 descriptors. The
synthetic shader instead uses set 0/binding 0 as a 16-element storage-buffer
array. The corrected generator (verified in `build/lab-probe-v09`) encodes
`heap_set=0` and `heap_binding=0` in CMK3 with table base 4 and push size 52.
Older auto-heap outputs are incompatible and this harness does not compensate for
them.

The explicit-set path in `anv_shader_compile.c` accepts any non-null set index,
then copies that binding `descriptor_surface_offset` and
`descriptor_surface_stride`; it does not validate the binding descriptor type or
layout type. `genX_cmd_buffer.c` later computes
`set->desc_offset + offset + index * stride` and uses it as a surface-state
binding-table entry. Mesa `VK_DESCRIPTOR_TYPE_STORAGE_BUFFER` has a usable
surface-state representation in a DIRECT layout: `anv_descriptor_data_for_type`
and `anv_descriptor_size` include a surface and give each descriptor a nonzero
surface stride. Xe2/BMG selects DIRECT by default because `verx10 >= 125`
disables indirect descriptors, and the local driver option
`force_indirect_descriptors` can override that. In an INDIRECT layout a storage
buffer goes through its indirect descriptor data and provides no per-element
surface-state array for this CM path to index. The harness therefore requires the
ANV compile log to report `heap set 0 binding 0`, a nonzero stride, and layout
type DIRECT (enum value 2) before it accepts output. That runtime gate has not
been run.

The harness uses a conventional descriptor-set layout (no
`VK_DESCRIPTOR_SET_LAYOUT_CREATE_DESCRIPTOR_BUFFER_BIT_EXT` flag), with binding 0
of type `STORAGE_BUFFER` and array size 16. This is a synthetic DIRECT-layout
contract, not a claim about the vkd3d-proton mutable heap or the FSR pipeline
layout. Local offsets, stride and descriptor contents remain runtime questions.

For the target dispatch the harness initializes all 16 storage buffers to a
sentinel, pushes 52 bytes (one leading DWORD, eleven table indices from byte 4,
and a trailing non-resource sampler DWORD), and maps tables to heap slots
`[7,8,0,1,2,3,4,5,6,9,10]`. It requires driver logs to show kernel injection and
dispatch separately from `canary-driver.log`, and checks all 128 float32 words in
each output surface against `16 + argument_index`. Heap slots 11 through 15 must
stay unchanged. These checks do not validate the generated kernel metadata, the
actual driver patch, or the full CM/Vulkan ABI.

Evidence files, created without overwriting, are `anv_canary`,
`icd-selection.txt`, `icd-driver.log`, `canary-driver.log`,
`canary-evidence.txt`, `probe-driver.log`, and `probe-readback.txt`. The queue
wait uses a 20-second fence timeout. On timeout the process exits without
`vkDeviceWaitIdle`, resource cleanup, or a device reset, which limits host-side
waiting but does not recover from a GPU or driver hang. The timeout cannot bound a
blocking `vkQueueSubmit`, and pipeline compilation and instance/device creation
have no timeout. Any failed gate means the probe has not passed.

## Building the CM kernels offline

Both builders take `--toolchain` and `--out`. Build into a new directory and never
overwrite an existing evidence set. The DPAS probe:

```sh
python tools/build_lab_probe.py \
  --toolchain artifacts/extracted/intel-toolchain \
  --out build/lab-probe-v09
```

The image probe:

```sh
python tools/build_image_probe.py \
  --toolchain artifacts/extracted/intel-toolchain \
  --out build/image-probe-v01
```

Compilation errors are fatal and preserved; no constants or no-op replacement is
accepted. `gpu_validated` and `runtime_approved` stay false until a separately
authorized manual test.

### IGC `-11` crash

The initial `build/lab-probe-v02/compile.log` reported IGC internal error `-11`.
The imported `llvm.genx.dpas2.v128f32.v128f32.v128i32.v64i32` signature and its
six scalar controls match the PRE SPIR-V in
`analysis/fsr-resources/xe2-first.spvasm` (DPAS declaration near line 3121, call
near line 15810). A local CPU-only control compiled with the DPAS call removed
still failed while it kept the probe `llvm.genx.oword.st.v128f32` import and call.
Removing that store call made the control compile, so the evidence points at the
unsupported 128-float OWord-store intrinsic, not at DPAS. This applies to this
compiler path only.

The source now uses the PRE-observed `llvm.genx.oword.st.v4f32` ABI: BTI, OWord
index, and four `f32` values. The PRE computes its second argument as
`byte_offset / 16`, so each 128-float result becomes 32 four-float stores with
OWord indices 0 through 31, which covers the 512-byte output. DPAS operands stay
packed FP16 numeric-one data and the real DPAS call stays in the kernel.

### Payload audit

`tools/audit_pre_payload.py build_report()` is tied to the fixed PRE
input/zebin/native/IR hashes, so it does not apply as a whole to these probes.
Each probe audits its own generated zebin, embedded SPIR-V, and native IGA
disassembly before it zeroes CMK cross-thread bytes:

- The embedded SPIR-V must match the assembled input. The restricted argument
  audit requires all eleven entry parameters to be opaque read/write buffer
  surfaces, each used once by `llvm.genx.address.convert...`; direct pointer loads
  or extra argument uses fail closed.
- Zebin payload metadata is pinned to eleven stateful/global 8-byte arguments at
  offsets 8 through 88, the 8-byte `private_base_stateless` at offset 0, and one
  6-byte `packed_local_ids` per-thread field. Any other payload shape is rejected.
- The `audit_native()` byte-liveness routine runs on the probe own native assembly.
  It finds three `bti[255]` cross-thread load responses (64-byte GRFs in `r1`,
  `r2`, `r3`) and reports that all three are fully overwritten before any read.
  Its assumptions are a full constant execution mask, 64-byte GRFs, and agreement
  between IGA send decoding and native encoding.

`payload-audit.json` records the result. If metadata, SPIR-V use, native load
shape, hashes, or liveness change, the packer refuses to emit CMK.

The Mesa reader maps header `grf_count` to `grf_used` and CMK LWS to
`local_size = (lws.x*32, lws.y, lws.z)`, so the probe accepts only its observed
128 GRFs and CM dimensions `(1,1,1)`.

### DPAS probe result

With local IGC `2.10.10+18926` and ocloc `25.18.33578.6`, `build/lab-probe-v09`
completed. `summary.json` reports `has_dpas=true`, SIMD size 1, 128 GRFs, eleven
arguments mapped in order to BTIs 1 through 11, stateful global buffers, 96 bytes
of cross-thread payload, and 6 bytes of per-thread packed local IDs.
`disasm/.text.bridge_probe.asm` contains `dpas.8x8 (16|M0) ...`. The CMK header is
CMK3 with `(heap_set, heap_binding, table_pc_base) == (0,0,4)` and extension
`(flags, expected_push_size) == (1,52)`. The output spec records heap slots
`[7,8,0,1,2,3,4,5,6,9,10]` and `gpu_validated: false`. Zebin SHA-256 is
`2766e9c9c44171e7b86e2daded4f7e5d5cacd110e8c88bdb757b6a6d78c9340f`, native
assembly SHA-256 is
`0775e578d67dd1335ed575317f4e27f4323002cddaf04fe92537bab2b7f0570d`, and the
CMK3 SHA-256 is
`7de3eb4bd22de3d10e7de6137929570dfd261fdf716daf9b54e8b6334757560a`.

This verifies offline compilation, native DPAS presence, compiler-emitted
argument and payload metadata, and the restricted static payload audit. It does
not verify descriptor integration, resource contents, numerical readback,
injection, or runtime compatibility.

## Image/sampler probe

The builder emits `bridge_image_probe` and `wg2_1_5.cmk` with CM local size
`(1,1,1)`. The Vulkan placeholder workgroup `(2,1,5)` only selects the kernel
file; the reader scales CM `(1,1,1)` to hardware `(32,1,1)`. The kernel takes
three arguments:

| Argument | Meaning | CMK3 table |
|---|---|---:|
| 0 | read-only sampled image | 3 |
| 1 | storage output buffer | 7 |
| 2 | sampler (non-resource push DWORD) | 0 |

CMK3 selects explicit set 0/binding 0, table base 4, push size 52, and resource
table DWORDs 3 and 7 at byte offsets 4 and 8. The DWORD at byte 48 is a zero dummy
sampler offset; the real sampler is immutable at set 1/binding 0. The image
descriptor occupies heap element 3 and the output element 7, while the remaining
elements are sentinel storage buffers. Since heap element 3 holds the image and
not a buffer, the harness checks a separate sentinel buffer for slot 3.

The sample call is `llvm.genx.3d.sample.v64f32...` with IGC ABI order: opcode,
SIMD predicate, channel mask (`0xf`), `aoffimmi`, sampler index, surface index,
then vector operands. The probe uses `sample_lz` opcode 24 for explicit mip level
zero. IGC vISA 3D_SAMPLE states that each enabled channel SIMD lanes are
contiguous and each channel starts in the next GRF, so the `v64f32` return is
already channel-major and the probe applies no AoS shuffle. Output is
`channel*16+lane`, written as four channel-major `v4f32` chunks through
`llvm.genx.oword.st.v4f32`.

The Vulkan layout must enable `VK_EXT_mutable_descriptor_type` and the
`mutableDescriptorType` feature. Set 0/binding 0 is a 16-element
`VK_DESCRIPTOR_TYPE_MUTABLE_EXT` array whose allowed types include
`STORAGE_BUFFER` and `SAMPLED_IMAGE`, and the descriptor pool mutable-type list
must allow the same types. Descriptor writes use storage-buffer descriptors except
element 3, which is a sampled-image descriptor. A second set has binding 0 as an
immutable linear/minification+linear/magnification, clamp-to-edge sampler, bound
as set 1 of the pipeline layout. The harness fails closed if the extension or
feature is absent.

### Image fixture and oracle

`tools/image_probe_reference.py::contract()` defines a 2x2
`R32G32B32A32_SFLOAT` image, one mip, row-major texels:

```
(0,0) = (1, 2, 3, 4)       (1,0) = (5, 6, 7, 8)
(0,1) = (9,10,11,12)       (1,1) = (13,14,15,16)
```

The harness uploads through a host staging buffer, transitions `UNDEFINED ->
TRANSFER_DST` then `TRANSFER_DST -> SHADER_READ_ONLY`, and waits for
transfer-write to compute-shader-read visibility. It uses the 16 `U`/`V` vectors
from the canonical module, normalized coordinates, mip 0, linear filtering, and
clamp-to-edge. `expected` holds 64 float32 values in channel-major order
(`out[channel*16 + lane]`), compared with absolute tolerance `1e-5` and relative
tolerance zero. `tests/test_image_harness.py` checks that the C arrays match the
shared contract, so no runtime JSON parser is needed. The output buffer has a
sentinel guard tail that must stay unchanged.

### Running the image probe

Compile the harness as a separate binary, for example
`build/image-harness/image_probe`, with `-std=c11 -Wall -Wextra -Werror -pedantic`
and Vulkan/libm linkage. The opt-in invocation mirrors the buffer probe:

```sh
build/image-harness/image_probe --run-gpu --probe-dir DIR --log-dir NEW_DIR \
  --icd-manifest FILE --icd-root DIR
```

`--run-gpu` is mandatory. Before Vulkan instance creation the harness checks all
three artifacts, a fresh log directory, and a resolved local ICD library under the
explicit ICD root, and it sanitizes inherited loader and `ANV_CM_*` selection.
Before any target dispatch it enumerates PCI `8086:e20b`, checks RGBA32F
optimal-image linear-filter support, uploads the fixture, runs the canary once
(marker writes from invocation 0 only), and checks the canary marker and every
sentinel. It then compiles the target and requires ANV injection plus set
0/binding 0 DIRECT layout evidence with nonzero surface stride. Canary and target
logs stay separate. Target dispatch must log `dispatch kernel 2,1,5`, all 64
output floats must match the fixed CPU oracle, and every guard and sentinel buffer
must be unchanged. Fence waits are bounded and a timeout exits without
device-idle or reset. Pipeline creation, `S_OK`, a marker, or an injection log
alone never count as success.

The harness writes `image-readback.txt` and `image-readback.bin`, exactly 16 slots
of 128 little-endian uint32 (8192 bytes) in slot order. Only heap slot 7 words 0
through 63 may differ from sentinel, which lets a reviewer check the bytes without
trusting the C report.

### Image probe result

`build/image-probe-v16` is the candidate for the manual test. v15 omitted bit 31
of the CMK header `barriers` word, which is the reader `cm_has_sampler` flag:
native sample instructions and an immutable Vulkan sampler do not initialize CM
sampler state without it. v16 sets `0x80000000`, keeps the same audited native
kernel, and enables the reader immutable-sampler path. A CPU regression checks
that flag, CM LWS, table indices, and the zero descriptor elements. The v16 zebin
SHA-256 is `7f713f03dc41244e57c18402fa2503ecf2ff478bb4c8e359604331dd656c1460`
and its CMK3 SHA-256 is
`91576c4406d2cd9bb21fd550d0b746b88f975498681443a25711572a794006ba`. Both Vulkan
marker shaders pass `spirv-val --target-env vulkan1.1`.

The compiler-derived zebin BTIs are `[1,2]` for args `[image,output]`. Metadata
shows no cross-thread pointer field for the image, arg 1 at offset 8, and
`private_base_stateless` at offset 0, for a 16-byte cross-thread payload. The
probe-local audit found no possible read of either 64-byte native payload load
before overwrite or end under its declared assumptions. `prepare_image_test.py`
`validate_probe()` recomputed the full audit and the CMK byte for byte.

`toolchain.json` records the local executable hash and its `26.35.39758` version
output; the executable is named `ocloc-25.18.1`, and querying under the injected
toolchain library path instead returns unsupported-option status 226. The compile
command uses the extracted IGC/ocloc environment and target `0xe20b`.
`probe-spec.json` keeps every field from `contract()` unchanged and adds compile,
payload, and artifact hashes. The user's first manual run of v16 passed independent
GPU readback review; see
[the result and its limits](../docs/validation.md). That review covers
this synthetic image, not FSR.
