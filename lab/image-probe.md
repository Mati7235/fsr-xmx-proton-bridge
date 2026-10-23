# CM image2D + sampler probe (implemented; GPU not run)

This is a separate future probe for image/sampler ABI coverage. It is not FSR,
does not extend the earlier buffer-only result, and is not authorized to run on
GPU by default. Compile the C harness only; do not execute it during offline
review. Any manual execution needs explicit user approval and a new evidence
directory.

## Kernel/build contract

The offline builder emits `bridge_image_probe` as the CM kernel entry
and `wg2_1_5.cmk` (CM local size `(1,1,1)`). The harness also needs a Vulkan
placeholder whose local size selects `wg2_1_5`, plus the existing one-invocation
canary placeholder `(1,1,17)`. The image kernel takes exactly three arguments:

The placeholder workgroup `(2,1,5)` is only the kernel-file selector, not the CM
kernel's local size. The reader scales CM `(1,1,1)` to hardware `(32,1,1)`.

| Argument | Meaning | CMK3 table |
|---|---|---:|
| 0 | read-only sampled image | 3 |
| 1 | storage output buffer | 7 |
| 2 | sampler (non-resource push DWORD) | 0 |

CMK3 must select explicit set 0/binding 0, table base 4, push size 52, and
resource table DWORDs 3 and 7 at byte offsets 4 and 8. The final DWORD at byte
48 is a dummy sampler offset (zero); the actual Vulkan sampler is immutable at
set 1/binding 0. No other kernel arguments or hidden resource bindings are
accepted. The image's mutable descriptor slot is heap element 3; output is
element 7. Other heap elements are sentinel storage buffers, including a
separate sentinel buffer checked for slot 3 after dispatch (the descriptor at
heap element 3 itself is the image, not a buffer).

The Vulkan layout must use `VK_EXT_mutable_descriptor_type` explicitly: enable
the device extension and `mutableDescriptorType`; set 0/binding 0 is a
16-element `VK_DESCRIPTOR_TYPE_MUTABLE_EXT` array whose allowed types include
`STORAGE_BUFFER` and `SAMPLED_IMAGE`; its descriptor pool mutable-type list must
allow the same types. Descriptor writes use storage-buffer descriptors except
element 3, which is a sampled-image descriptor. A second set has binding 0 as
an immutable linear/minification+linear/magnification, clamp-to-edge sampler;
bind that sampler set in pipeline layout set 1. Fail closed if the extension or
feature is absent. Do not substitute a regular storage-buffer binding or rely
on ANV's fallback sampler.

## Deterministic image and reference

The canonical fixture is defined by `tools/image_probe_reference.py::contract()`:
a 2x2 `R32G32B32A32_SFLOAT` image, one mip, row-major texels:

```
(0,0) = (1, 2, 3, 4)       (1,0) = (5, 6, 7, 8)
(0,1) = (9,10,11,12)       (1,1) = (13,14,15,16)
```

Upload through a host staging buffer; transition `UNDEFINED -> TRANSFER_DST`
and then `TRANSFER_DST -> SHADER_READ_ONLY`, with transfer-write to compute
shader-read visibility. Use the exact 16 `U`/`V` vectors in the canonical
module, normalized coordinates, mip 0, linear filtering, and clamp-to-edge. Its
`expected` vector is exactly 64 float32 values, channel-major
(`out[channel*16 + lane]`), with absolute tolerance `1e-5` and relative
tolerance zero. `tests/test_image_harness.py` checks that the C arrays exactly
match this shared contract; no runtime JSON parser is needed. The output buffer
must have a sentinel guard tail, checked unchanged after dispatch.

## Required gates and evidence

`--run-gpu` is mandatory. Before Vulkan instance creation check all three
artifacts, a fresh log directory, resolved local ICD library under the explicit
ICD root, and sanitize inherited loader/`ANV_CM_*` selection in the process.
Invoke using the same interface as the first harness:

```sh
image_probe --run-gpu --probe-dir DIR --log-dir NEW_DIR \\
  --icd-manifest FILE --icd-root DIR
```

Before any target dispatch: enumerate and require PCI `8086:e20b`, check
RGBA32F optimal-image linear-filter support, upload the fixture, run
the canary once only (marker writes from invocation 0 only), check the canary
marker and every sentinel, then compile the target and require ANV injection
and set 0/binding 0 DIRECT layout evidence with nonzero surface stride. Keep
the canary separate from target dispatch logs. Require target dispatch log
`dispatch kernel 2,1,5`; compare all 64 output floats to the fixed shared CPU
oracle and check every guard/sentinel buffer. Fence waits are
bounded; timeout must exit without device-idle/reset attempts. No success may
be inferred from pipeline creation, `S_OK`, marker, or injection log alone.

## Current status / manual handoff

`lab/image_probe.c` now implements the opt-in Vulkan path, including mutable
descriptors, immutable sampler, staged image upload, canary/injection/DIRECT
layout gates, and numerical/sentinel readback. It writes `image-readback.txt`
and a raw `image-readback.bin` of exactly 16 slots x 128 little-endian uint32
(8192 bytes), preserving slot order. Only heap slot 7 words 0..63 may differ
from sentinel. The raw evidence supports independent CPU review without
trusting the C report alone. Strict compilation and CPU-only tests do not
validate actual runtime behavior; no C binary or GPU was run in this work.

The coordinator compiled the harness to `build/image-harness/image_probe` with
`-std=c11 -Wall -Wextra -Werror -pedantic` and Vulkan/libm linkage. An optional
additional GCC `-fanalyzer` build emitted `analyzer-fd-leak` diagnostics for
`dup2(..., STDERR_FILENO)` in the inherited log-redirection helpers. Descriptor 2
is intentionally kept open and restored as process stderr; no analyzer flags
were suppressed and the harness is not claimed to pass that optional analysis.
The strict build above, which does not enable `-fanalyzer`, passed. Runtime
correctness still requires the manual experiment and captured-byte review.
