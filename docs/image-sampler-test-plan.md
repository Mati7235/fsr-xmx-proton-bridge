# Next manual test: image and sampler

**Preparation finished:** [manual command and risks](manual-image-test.md).
It uses `build/image-test-v01` with the corrected candidate `image-probe-v16`.
No GPU was run during development. The user's first manual test
[has already passed independent review](first-image-gpu-result.md).

The first probe validated DPAS and a buffer heap. The next one exercises a
sampled image and a sampler before attempting the real PRE. It is our own
synthetic test: it does not execute any code from the DLL and does not
demonstrate full FSR.

## Common contract

`tools/image_probe_reference.py` is the source of data and of the CPU result:

- 2x2 image, `R32G32B32A32_SFLOAT`, one mip, four distinct channels.
- Texels by rows: `(1,2,3,4)`, `(5,6,7,8)`, `(9,10,11,12)`, `(13,14,15,16)`.
- Sixteen normalized coordinates: texel centers, image center and off-edge
  positions to check linear/clamp-to-edge.
- Result: 64 float32 in channel*16+lane order; absolute tolerance `1e-5`.
- The central sample must give `(7,8,9,10)`; it distinguishes interpolation
  from nearest.
- The CM kernel has one image, one output buffer and a sampler at index zero.
- Explicit mutable heap set 0/binding 0 with 16 descriptors; image in slot 3,
  output in slot 7. CMK3 base push 4, total size 52. Do not infer the heap from
  the queue.
- Placeholder `(2,1,5)` separate from the previous probe `(1,1,5)`; canary `(1,1,17)`.

The builder and the harness must use these same data, not each derive their
own answer from a different interpretation of the coordinates. The CPU code
computes bilinear interpolation with centers at `(i+.5)/dimensión` and per-texel
clamps; it does not call Vulkan. Its five tests cover centers, averages, edges,
channel order and invalid inputs.

The harness must also capture `image-readback.bin`: the sixteen buffers of
128 words each, in slot order, little-endian (8,192 bytes).
`tools/review_image_result.py` re-checks those bytes on CPU independently of
the C comparator: 64 float32 against the reference, NaNs rejected, and the
remaining 1,984 sentinel words intact. It also requires the identity of the
prepared artifacts and evidence of canary, injection, layout and map in the
logs. Its tests use synthetic bytes; they do not represent a GPU run.

## Criteria for leaving the candidate for manual use

1. CPU build of the CM with a real sampling instruction, BTIs and sampler
   confirmed by zebin/disassembly; do not replace samples with constants.
2. Our own audit of the payload; do not transfer the conclusion of the PRE or
   of the first probe to a new binary without checking it.
3. Harness built with warnings as errors: upload, layouts and image barriers,
   compatible sampler, sentinel buffers, and readback compared against the
   reference. Do not run the harness during preparation.
4. Preparation with local ICD, full hashes, new directories and a manual
   opt-in, same as the previous probe. Keep the canary and injection evidence.
5. Leave a concrete command for the user only when those steps pass. The
   experiment may fail on the GPU; do not present a successful build as a
   runtime success.

The real PRE additionally requires knowing the contract of its buffers,
dimensions, formats and correctness criterion. That is being investigated in
parallel: it is not dispatched with arbitrary resources, and an output is not
considered correct merely because it does not hang.

## Way of working

Continue automatically with static investigation, development, build, CPU
tests and candidate preparation. Do not close each milestone as if another
instruction were needed. GPU experiments are left to the user with an explicit
command and risks; do not modify Steam, installed drivers or real prefixes.
