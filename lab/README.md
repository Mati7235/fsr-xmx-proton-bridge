# Synthetic Vulkan DPAS/resource-map harness

This harness is for a future, explicitly authorized GPU experiment. It is not
the FSR kernel and is not a functional bridge. The current generated artifacts
are experimental: do not infer final DPAS metadata or Vulkan/CM ABI validation
from a successful offline build.

## Offline compile only

`bridge_probe.c` needs Vulkan headers and the Vulkan loader at link time. Use the
local Mesa build's headers if present; do not install packages for this step.
For this checkout:

```sh
mkdir -p build/lab-harness
cc -std=c11 -Wall -Wextra -Werror \
  -Ibuild/mesa-26.1.2/include \
  lab/bridge_probe.c -o build/lab-harness/bridge_probe -lvulkan
```

Compilation is CPU-only. **Do not run** the resulting executable as part of
offline inspection. With no arguments it is designed to report that it is in
CPU-only mode without creating a Vulkan instance. GPU execution requires the
explicit `--run-gpu` opt-in.

## Future GPU invocation (not run here)

Only use a disposable, deliberately prepared test environment with the patched
ANV driver and the expected local probe artifacts. The probe directory must
contain `placeholder.spv`, `canary.spv`, and `wg1_1_5.cmk` from
`tools/build_lab_probe.py`. Choose a **new** log directory for every run:

```sh
build/lab-harness/bridge_probe --run-gpu \
  --probe-dir /path/to/generated/probe \
  --log-dir /path/to/new/evidence-directory \
  --icd-manifest /path/to/local/mesa/icd.json \
  --icd-root /path/to/local/mesa/build
```

The harness resolves the ICD manifest's `library_path` and requires that library
to be a regular file inside the explicitly supplied local Mesa build root. It
then sets `VK_DRIVER_FILES` and `VK_ICD_FILENAMES` for this process to that exact
manifest and removes inherited Vulkan driver/layer selectors and **all**
inherited `ANV_CM_*` variables before setting the four probe-specific values.
`icd-selection.txt` records the selected manifest/library/root. This confirms
the requested loader configuration, not independently which shared object the
loader ultimately mapped; `icd-driver.log` records instance-creation diagnostics.
The program does not set `WINEPREFIX`, change the parent/session environment, or
alter Steam, Proton prefixes, drivers, or services.

Before device creation or submission, it requires Vulkan to enumerate PCI
vendor/device `8086:e20b`. Any missing artifact, ICD, local library, canary,
non-target GPU, layout evidence, or readback mismatch fails closed. A passing
readback is not by itself proof of bridge functionality.

The canary uses the builder's `(1,1,17)` shader. The upstream injection patch
recognizes that workgroup size, writes `anv_canary` under `ANV_CM_SPV_DIR`, and
then lets the marker placeholder shader run. The harness checks the marker's
contents, the marker word in buffer 0, and that every other word in all 16
storage buffers is still sentinel. This is separate from the synthetic target
shader, whose `(1,1,5)` placeholder selects the static `wg1_1_5.cmk` path.

## Descriptor-layout integration contract

The initial generator emitted `heap_set = 0xffffffff` (auto-discovery). In the
local Mesa source, `anv_shader_compile.c` auto-discovery only accepts a
`VK_DESCRIPTOR_TYPE_MUTABLE_EXT` binding with at least 1000 descriptors. The
synthetic shader instead uses set 0/binding 0 as a 16-element storage-buffer
array. The corrected generator (verified in `build/lab-probe-v09`) explicitly
encodes `heap_set=0` and `heap_binding=0` in CMK3 with table base 4 and push size
52. Older auto-heap outputs are incompatible; this harness does not patch or
compensate for them.

The explicit-set path in `anv_shader_compile.c` currently accepts any non-null
set index, then copies that binding's `descriptor_surface_offset` and
`descriptor_surface_stride`; it does not validate the binding's descriptor type
or layout type. `genX_cmd_buffer.c` later computes
`set->desc_offset + offset + index * stride` and uses it as a surface-state
binding-table entry. Mesa's ordinary `VK_DESCRIPTOR_TYPE_STORAGE_BUFFER`
descriptor has a usable surface-state representation in a **DIRECT** layout:
the local `anv_descriptor_data_for_type`/`anv_descriptor_size` path includes a
surface and gives each descriptor a nonzero surface stride. Xe2/BMG selects
DIRECT by default because `verx10 >= 125` disables indirect descriptors; the
local driver option `force_indirect_descriptors` can override that. In an
INDIRECT layout a storage buffer is represented through its indirect descriptor
data and does not provide the per-element surface-state array this CM path
indexes. The harness therefore requires ANV's own compile log to report
`heap set 0 binding 0`, a nonzero stride, and layout type DIRECT (enum value 2)
before accepting output. This runtime gate has not been run here.

The harness uses a conventional descriptor-set layout (no
`VK_DESCRIPTOR_SET_LAYOUT_CREATE_DESCRIPTOR_BUFFER_BIT_EXT` flag), binding 0
of type `STORAGE_BUFFER`, array size 16. This is a synthetic DIRECT-layout
contract, not a claim about vkd3d-proton's mutable descriptor heap or FSR's
pipeline layout. The exact local offsets/stride and descriptor contents remain
runtime questions; do not infer them from the source-level layout alone.

For the target dispatch it initializes all 16 storage buffers to a sentinel,
pushes 52 bytes (one leading DWORD, eleven table indices beginning at byte 4,
and a trailing non-resource sampler/dummy DWORD), and maps tables to heap slots
`[7,8,0,1,2,3,4,5,6,9,10]`. It requires driver logs to show kernel injection
and dispatch separately from `canary-driver.log`, and checks all 128 float32
words in each output surface against `16 + argument_index`. Heap slots 11–15
must remain unchanged. These checks are deliberately strict; they do not
replace validation of the generated kernel's metadata, actual driver patch, or
the complete CM/Vulkan ABI.

Evidence files (created without overwriting) are `anv_canary`,
`icd-selection.txt`, `icd-driver.log`, `canary-driver.log`,
`canary-evidence.txt`, `probe-driver.log`, and `probe-readback.txt`. The queue
wait uses a 20-second fence timeout. On timeout the process exits immediately
without `vkDeviceWaitIdle`, resource cleanup, or an attempted device reset; this
limits host-side waiting but does **not** guarantee recovery from a GPU/driver
hang. The timeout cannot bound a blocking `vkQueueSubmit` call. Pipeline
compilation and instance/device creation also have no timeout. A failure in any
gate or check means the probe has **not** passed.

`tests/test_lab_harness.py` exercises a small Python CPU reference model for the
slot permutation, canary sentinels, and expected outputs, plus source-level
safety gates. It does not invoke Vulkan or the C binary and is not a substitute
for testing the C readback path on hardware.
