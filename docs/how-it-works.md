# How our patches make FSR 4 run on XMX

FSR 4 normally runs through AMD's driver library `amdxcffx64.dll` and expects AMD hardware. nitec's 4.1.2 mod replaces that path with Intel C-for-Metal kernels for XMX, and four pieces run it on an Arc B580 without AMD's driver: a patched Mesa ANV driver that dispatches the kernels, our CMK3 mapping patch that tells the driver where the PRE kernel's descriptors live, `igdext64.dll` answering the mod's Intel queries, and a game-local `cabinet.dll` that unpacks the models.

## The driver has no FSR path

Mesa's Intel driver compiles SPIR-V and knows nothing about the mod's `.cmk` kernel container, so stock ANV never loads a native kernel and never binds the descriptor tables that kernel reads. Upstream `xess-xmx-linux` adds that path, and we apply its Mesa 26.3.1 series from `upstream/xess-xmx-linux/patches/mesa-26.3/` to the Mesa tarball instead of forking. The checkout is pinned at `f06dc39`.

1. `0001-anv-cm-kernel-injection.patch` adds `src/intel/vulkan/anv_cm.c` and `genX_cm.c`, where `anv_cm_kernel_replace()` opens the `.cmk` file that `ANV_CM_HELPER` compiled from the kernel's SPIR-V and swaps it in for the shim's placeholder shader.
2. `0002-anv-cm-debug-tools.patch` adds the `ANV_CM_*` inspection switches and buffer-object capture used to check an injection.
3. `0003-anv-cm-xe2-large-grf.patch` turns `STATE_COMPUTE_MODE` Large GRF Mode on around a kernel that uses 256 GRF, and off before any other compute walker. Without it a 256-register kernel runs in 128-register mode on Xe2, its threads never retire and the engine hangs with an `rcs/ccs` reset after the job timeout.
4. `0005-anv-cm-sampler-descriptor-table.patch` accounts for the sampler table when it derives the table base (`push_size - 4*(nsurf+1)`, which gives 4 for the PRE) and takes the sampler from the descriptor table (`cm_sampler_from_heap`, `cm_sampler_pc_off`). Without it the base stays 8 and the sampler falls back to linear/clamp, and the image is corrupted.
5. `0006-anv-cmat-vars-before-jay.patch` lowers the `function_temp` variables that `brw_nir_lower_cmat` leaves behind before Jay sees them. Without it Jay hits `UNREACHABLE("All derefs should've been lowered")` and Cyberpunk 2077 crashes while compiling a compute shader.
6. `0007-jay-avoid-lowering-helper-predication.patch` backports Mesa MR 46045, which stops tracking helper lanes when demote lowers to terminate. Mesa 26.3.1 carries the commit before it, and fragment shaders can hang the GPU without this one.

The series skips 0004 because upstream dropped it.

## Our patch

`patches/0001-anv-cmk3-explicit-mapping.patch` is 418 lines and edits `anv_cm.c` inside their 0001 before Mesa sees it.

A kernel finds its input images through a list of dword offsets in the push constants, and the driver has to know the byte where that list starts. Upstream derives it from the push size: the last `nsurf` dwords, or after 0005 the last `nsurf + 1` when a sampler table closes the list. That gives 4 for the 4.1.2 PRE (52 push bytes, 11 surfaces at offsets 4 to 44, sampler at 48), but it trusts the shape of every kernel.

CMK3 states the shape instead. The packer writes `flags` (must be 1) and the expected push size after the header, `anv_cm_header_ok()` accepts the magic, and `anv_cm_kernel_replace()` reads `table_pc_base` from the file, requires `push_size == mapping[1]` and every `table_pc_base + 4 * table_idx[k]` inside a declared `push_constant_ranges` entry, and skips the derivation. A mismatch fails with `ANV CM: invalid CMK3 mapping in %s` or `ANV CM: CMK3 push layout mismatch in %s` instead of binding a wrong descriptor. `anv_cm_toolchain_gen` mixes the registry digest `0x3ddd809f` so a profile change invalidates cached kernels.

Without the patch the stock `anv_cm_header_ok()` rejects `CMK3` at the magic check and the kernel does not inject. A build that only relaxed the magic would dispatch an audited kernel with geometry taken from a heuristic instead of the profile.

## The shim answers as Intel

At start the mod resolves `igdext64.dll` and calls `_INTC_D3D12_CreateDeviceExtensionContext` at version 4.20.0 with a 192-byte `INTCExtensionInfo`. The shim adapts it to the 200-byte `INTCExtensionInfo1` and calls `D3D12ExtensionContext::InitExtensions`, which fills the device information and three driver outputs.

`patches/0002-shim-context-output.patch` writes those fields from one `CopyExtensionInfo1OutputsToOld` helper that 0003 reuses. Before upstream `8f45d12` added the same copy inline, neither legacy export copied any of them back, so the mod read the structure it had passed in instead of the GPU and driver the shim found.

`patches/0003-shim-context-reuse.patch` fixes the second create against an existing D3D12 half, which returned early with `S_OK` and zeroed outputs, so a caller could not tell a live context from an unanswered one. It checks the stored `m_pAppDevice` against `pDevice` (`E_INVALIDARG`), checks the requested version with `INTCExtensionVersionHelper::IsSupported` (`E_NOINTERFACE`), then re-runs `InitExtensions` into a zeroed temporary to refill the outputs.

Both patches touch `shim/src/dll/IgdextApiDll.cpp`. `tests/test_context_output.py` and `tests/test_context_reuse.py` compile and run the generated bodies on the host, and neither patch has run in a prefix. [shim-bridge.md](shim-bridge.md) has the byte layouts and the pins.

## The cabinet the game needs

The 4.1.2 mod keeps its kernels in six LZMS packs (resources 40101 to 40106, 1,977 CM envelopes) and decompresses each one through the Windows Compression API. Wine's `cabinet.dll` exports only FDI/FCI, so the first call aborts with `wine: Call from ... to unimplemented function Cabinet.dll.40, aborting`. The mod imports three ordinals: 40 `CreateDecompressor`, called with algorithm 5 (LZMS); 43 `Decompress`, which must report `Produced == expected` or the loader logs `embedded pack %u invalid`; and 45 `CloseDecompressor`. Our `cabinet.dll` exports those three over wimlib's LZMS decoder. The driver step copies it to `/opt/fsr-xmx/` and writes `WINEDLLOVERRIDES=dxgi,cabinet=n,b` to `/etc/environment.d/fsr-xmx.conf`; `fsr-xmx enable` copies it next to the game's `.exe` so Wine loads it ahead of the builtin.

## Models and where they come from

`fsr-original.dll` is AMD's official FSR 4.1.2 upscaler, renamed, and it carries the weights of both 4.1.2 models. The mod reads `FSR4_XMX_INT8` and `FSR4_XMX_LITE` at start, and with either set to `1` it loads the INT8 pair or the Lite pair from that DLL. When the weights are missing it falls to the next branch and logs `Lite/INT8 model requested without verified fsr-original.dll weights.`

## What the evidence shows

Marvel's Spider-Man Remastered and Cyberpunk 2077 rendered a correct scene with the 4.1.2 mod: injections in the log, a sampler heap found and no device lost. SCP: 5K ran one match with visual confirmation only, and its anti-cheat was not tested. No other title has a run on record. Per-title conditions and the pins are in [compatibility.md](compatibility.md).
