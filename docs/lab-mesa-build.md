# Offline build of Mesa 26.1.2 with LLVM 23

## Result

The local Mesa 26.1.2 checkout, with the lab's CM reader adapted and
LLVM 23.1.1, completed the CPU build. The previous log records the 575 steps
and `analysis/lab-v0.1/mesa-result-llvm23.txt` contains `0` (exit code).
Then `ninja -C build/mesa-26.1.2/out` finished nine remaining incremental
targets, including `libblorp_elk.a`; it reported no errors. The built ANV
artifact is
`build/mesa-26.1.2/out/src/intel/vulkan/libvulkan_intel.so` (27.6 MB).

This only verifies the local build. Vulkan/GPU was not run, the driver was not
installed, and Steam, prefixes, services and the session environment were not
modified. It is not evidence of injection or of a correct readback.

## LLVM compatibility patch

`patches/mesa-26.1.2-llvm23.patch` was preserved; it was already untracked
before this review. It is a four-line adaptation in
`src/compiler/clc/clc_helpers.cpp`: with LLVM 23 `TargetRegistry::lookupTarget`
takes an `llvm::Triple`; earlier versions keep the call with `const
char *`. The local source already contains exactly that adaptation, so the reverse
patch passed `git -C build/mesa-26.1.2 apply --reverse --check`.
A normal `git apply --check` does not apply on a source that already contains
the change; nothing was reverted or re-applied.

Meson found LLVM 23.1.1 and LLVMSPIRVLib 23.1.0.0. The log shows four
deprecated Expat warnings in `intel_decoder.c`; they were kept. No errors
or canaries were suppressed.

## Static review of mask and dimensions

The reader path is in
`build/mesa-26.1.2/src/intel/vulkan/anv_shader_compile.c`:

1. Reads `h.lws[3]` from the CMK and sets `prog_mask = 1 << 2`, `dispatch_width = 32`.
2. Sets `local_size` as `(32*h.lws[0], h.lws[1], h.lws[2])`.
3. The inspected PRE has `simd_size: 1` in `analysis/offline-pre/full/ze_info.yaml`.
   The legacy artifact reproduced by the packer declares `lws 1x1x1`
   (`analysis/offline-pre/full/pack.log`). For those values, the group size
   Mesa computes is `(32,1,1)`.

In `src/intel/compiler/brw/brw_shader.cpp`, `brw_cs_get_dispatch_info` takes
`simd_size = 8 << log2(prog_mask) = 32`, computes
`group_size = local_size[0]*local_size[1]*local_size[2]`, and uses the full mask
when the remainder modulo SIMD is zero. For any positive `lws` that fits in the
types used, the local size above gives `group_size = 32*lws[0]*lws[1]*lws[2]`;
therefore it is a multiple of 32 and `right_mask` comes out as `0xffffffff`. The Xe2
path encodes that value in `COMPUTE_WALKER.ExecutionMask` in
`src/intel/vulkan/genX_cmd_compute.c`.

In `src/intel/vulkan/genX_shader.c`, payload creation reserves
`dispatch.threads` entries and writes the local IDs as `t % lx`,
`(t / lx) % ly`, `t / (lx*ly)`. For the PRE packed as `1x1x1`, the only
entry carries local ID `(0,0,0)` and the walker represents one SIMD32 group.

### Limits of this conclusion

- It is a deduction from the code and the local metadata/CMK; it is not an
  observation of the mask in hardware nor a validation of the dispatch path at runtime.
- The reader does not explicitly validate that `lws` is non-zero, nor all overflow
  cases. The conclusion requires positive, representable values and that the
  packer/probe and the reader interpret the same dimensions.
- `simd_size: 1` in the zebin and `lws 1x1x1` in the CMK document the current
  inputs; they do not prove that the new probe emits them correctly. Its
  diagnosis is left to the agent that maintains `tools/build_lab_probe.py`.
- This does not confirm a constant mask during execution, nor does it take over
  the payload audit of its conditions. It also does not validate the sampler, the
  VKD3D layout, context transfer, injection or the image result.

## Limited reproduction

The original build was recorded in
`analysis/lab-v0.1/mesa-build-llvm23.log` and its status in
`analysis/lab-v0.1/mesa-result-llvm23.txt`. To check whether targets remain:

```sh
ninja -C build/mesa-26.1.2/out
```

This is a local CPU build; do not run the generated ICD as part of this
verification.
