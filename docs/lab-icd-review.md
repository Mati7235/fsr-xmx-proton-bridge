# Offline ICD review for the manual test

The ELF files were inspected with `readelf`, without loading the driver or running
the harness. ANV exports `vk_icdGetInstanceProcAddr` and
`vk_icdNegotiateLoaderICDInterfaceVersion`. Its 22 direct dependencies and the
two of the harness have files present in the local system paths.
This does not verify dynamic symbol/version resolution, transitive
dependencies, the effective ICD selection or GPU operation.

Local artifacts reviewed:

| Artifact | SHA-256 |
|---|---|
| `build/mesa-26.1.2/out/src/intel/vulkan/libvulkan_intel.so` | `3fc482d67725f417a5194a7d68dc69ffbb29d0795ca354c65c84cd38050843fb` |
| `build/lab-harness/bridge_probe` | `e9ad923a51fdeec10c94ec9e2011e7367a694fe8a1e845dfa34710410b0ac749` |

The detailed local inventory is in `analysis/lab-elf-review.json`. Neither `ldd`,
`vulkaninfo` nor the test executable was used for this inspection. The hashes
identify these builds, not an execution result.

The probe candidate is `build/lab-probe-v10`. It keeps exactly the zebin,
CMK3 and payload audit of v09, but fixes the Vulkan marker shaders: it
only writes the local invocation zero. Both markers pass
`spirv-val --target-env vulkan1.1`. Do not use the historical markers that
concurrently wrote the same DWORD.

For the manual test, the ICD manifest must point by absolute path to this
local ANV; do not replace manifests in `/usr/share/vulkan` or install the
driver. The launcher must re-compare the hashes, use a new HOME/cache and
evidence directory, and pass a bounded environment only to the child process.
The harness also requires a canary, DIRECT/injection evidence and a known readback.

## Residual risk

The experiment uses the same GPU and the same kernel driver as the desktop
session. **It is not hardware isolation**: a failure can hang the GPU or the
session. Save your work before running it. The 20-second fence only
limits a harness wait; it does not guarantee recovery or bound all
driver calls. Do not run it with `sudo` or with Cyberpunk/Steam as a test bench.
A correct synthetic test would not validate full FSR or Proton.
