# Initial compatibility and plan

## Inputs and traceability

Static analysis of 2026-10-22. No code from the packages was executed.

| File | SHA-256 |
|---|---|
| amd_fidelityfx_upscaler_dx12_xmx.7z | `1364778b46ab3f0734305ad44d23e161d94cd75130e08683acd5ceed85d7155b` |
| OptiScaler_v10.0.0-pre_20261022.7z | `df1380aa37fc17b26524e783f12ccb2f59cb67f966af13240bca3d4cd608a25a` |
| DLL extracted from the XMX mod | `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53` |

Upstream originally analyzed: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
Current base of the patch stack: `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`.
The following lines are relative to `upstream/xess-xmx-linux/`;
for patches they refer to the patch file, not to the final Mesa file.

## Evidence in the mod

The DLL of 25,779,712 bytes includes search strings for `igdext64.dll`,
the INTC variants with and without an underscore, and messages of:

- `CreateDeviceExtensionContext`, requested context 4.20.0.
- `CheckFeatureSupport`: OPTIONS1/XMX and OPTIONS2/SIMD16Required.
- `CreateComputePipelineState`: CM-SPIRV kernels and embedded Xe2 packs.
- `DestroyDeviceExtensionContext`.
- `GetCachedBlob`, associated with diagnostics of a PRE blob (whether it is mandatory is not established).
- Models `4.0.2x`, `4.0.2xm`, and reading of weights from `fsr-original.dll`.
- Explicit failure with magenta diagnostic; conventional fallback disabled.
- PRE ABI message: one table per SurfaceIndex/sampler.

These are extracted strings, not an observed trace nor a complete reconstruction of the flow.

## Shim map

| Area | Finding | Upstream evidence |
|---|---|---|
| Version | Accepts 4.20.0 by comparison against a maximum of 5.20.0; this does not prove full implementation | `shim/src/D3D12ExtensionContext.cpp:7-30`, `shim/src/ExtensionContextBase.h:42-45` |
| Context | [Candidate patch and CPU tests](context-output-fix.md) fix the compatible copy when initializing two inherited D3D12 APIs; the [reuse](context-reuse-fix.md) validates device/version against the granted contract and refreshes outputs (candidate 0003 stacked on 0002, CPU-tested). Not installed | `shim/src/dll/Igdext.def:33`, `shim/src/dll/IgdextApiDll.cpp:343-494` |
| Capabilities | OPTIONS1 and OPTIONS2 implemented; responses based on the detected GPU, with overrides | `shim/src/dll/D3D12Api.cpp:397-426` |
| GPU detection | Wine PCI registry, not necessarily the D3D12 device received; optimistic default if none is detected | `shim/src/dll/GpuInfo.cpp:12-42` |
| PSO CM-SPIR-V | Stores dynamic kernels; does not require a fixed XeSS whitelist | `shim/src/dll/D3D12Api.cpp:218-249`, `shim/CMakeLists.txt:39-43` |
| Compilation | Filters CompileOptions; does not forward InternalOptions; local size depends on concrete defines or falls back to 1,1,1 | `tools/cm-compile.sh:42-54`, `shim/src/dll/D3D12Api.cpp:202-245` |
| Entry point | Packer picks the first non-internal .text section; no general entry point selection | `tools/cmk_pack.py:44-52` |
| Resources | Assumes one table per surface and trailing DWORDs in push constants; does not interpret the general root signature | `tools/cmk_pack.py:89-101`, `patches/0001-anv-cm-kernel-injection.patch:675-720` |
| Samplers | First static sampler or XeSS linear/clamp fallback | same patch `:668-673,786-824` |
| Payload | 128-byte cross-thread limit; argument types not implemented; fixed group count in packer | `tools/cmk_pack.py:62-87`, `tools/cm-compile.sh:54` |
| CachedBlob | Export present but E_NOTIMPL; evaluate whether it only affects the mod's diagnostics | `shim/src/dll/D3D12Api.cpp:120-124` |
| Result | S_OK or a created PSO do not guarantee injection; there is a no-op fallback | `shim/src/dll/D3D12Api.cpp:247-256` |

The match on 'one table per surface' is promising, but it does not demonstrate
that the offsets, samplers, arguments, registers or the vkd3d layout match.

## Research progress

See [pre-resource-map.md](pre-resource-map.md): **690 blocks** recovered by
their length footers, a reconstructed PRE map, and a one-DWORD offset mismatch
identified under the reference VKD3D layout. In PRE the API options are NULL and the
embedded options are preserved. The [offline compilation](offline-pre-compilation.md)
confirmed that IGC consumes them, compiled the PRE for B580 and verified the BTIs. A
hash-pinned profile and a candidate CMK3 reader were added, not installed.
The [later payload audit](pre-payload-audit.md) finds no reads of the four extra fields
before they are overwritten or the program ends, under a full and constant execution
mask in this binary. No addresses had to be invented.

## Pending blockers

1. Complete the format of the non-CM data in 40101 (18 DXBC and six unclassified gaps); the six missing modules have already been recovered.
2. Validate the full and constant execution mask assumed by the audit: the cross-thread fields of args 0/9/10 and private_base_stateless are not read under that condition in the reviewed PRE.
3. Confirm the sampler and the Proton layout to be used for the test; the PRE surface map has already been cross-checked against the zebin.
4. Review the integration of the already-compiled reader inside local Mesa and integrate profile selection/cache identity without globally changing XeSS; see [local build](lab-mesa-build.md).
5. Determine whether configuration is enough or whether changes to the shim, packer or driver are needed.
6. Review IGC compiler and Xe2/Large-GRF device compatibility.

## Implementation milestones

- [x] Create separate workspace, copies and hashes.
- [x] Clone and identify the upstream revision.
- [x] Reproducible static inventory of the DLL.
- [x] Initial map of APIs and ABI risks.
- [x] Resource extractor and initial CM-SPIR-V carving (without running the DLL; no complete pack parser).
- [x] CM footer parser: 690 blocks recovered and disassembled.
- [x] Normal PRE options and root signature reconstructed; sizes of 36 variants verified.
- [x] 22 synthetic CPU tests and 2 optional ones with local artifacts, including the table-offset mismatch model.
- [x] Offline compilation of the Xe2 native_1080 PRE for B580; BTIs confirmed and option control reproduced.
- [x] Hash-pinned profile, offline CMK3 adapter and candidate ANV reader patch for both versions.
- [x] 41 local tests passing, including the validation C block with synthetic layouts.
- [x] Static audit of cross-thread bytes and opaque surface uses; no reads under full mask, with hash evidence.
- [x] 68 local tests passing, including read cases, partial/predicated writes and auditor branches.
- [x] Candidate D3D12 context copy patch: Windows ABI and generated bodies tested on CPU, and the complete shim built with LLVM-MinGW without running the DLL.
- [ ] Validation of the PRE's local mask and dimensions; the [pinned inspector](pre-dispatch-dimensions.md) keeps the gates open.
- [x] CPU build of local Mesa with LLVM 23 and candidate reader; not installed or run on GPU.
- [x] Synthetic DPAS probe compiled, payload audited under static assumptions, and explicit CMK3 heap.
- [x] Vulkan harness compiled without execution and inventory preflight; 96 CPU tests pass.
- [x] Manual preparation with local ICD, hashes, new environment and opt-in launcher; 102 CPU tests pass, no GPU run.
- [x] User ran the synthetic probe on B580: injection and 1,408 correct values, with remaining slots intact; see [evidence](first-synthetic-gpu-result.md).
- [x] Image/sampler probe compiled, audited and prepared for manual test with CPU reference and independent binary readback; 133 CPU tests pass.
- [x] User ran image/sampler on B580: independent binary review confirms 64 values with max error 0 and 1,984 sentinel words intact; see [result](first-image-gpu-result.md).
- [x] [PRE host views](pre-resource-descriptors.md) reconstructed for buffers: `R8_UINT`, SRV of 2,112/128 bytes and lower bound of the native_1080 UAV; D3D12 ABI assertions and 150 CPU tests pass. Image formats/inputs and the oracle remain pending.
- [ ] Runtime integration of the profile and review of the probe/harness contract.
- [ ] With authorization, microtest in a disposable prefix with known GPU output.
- [ ] Only afterwards, reversible per-game integration in Cyberpunk.

## 4.1.2 series (DLL `fadbcb50…b37f44732`, 45,558,272 B) — closed statically

- [x] LZMS decoder for the envelope (header 24 B + chunks, SHA-256 digest by loader `FUN_180029640`); 6 packs, 1,977 CM envelopes; see [envelope](xmx412-pack-envelope.md).
- [x] SPIR-V PRE Xe2 census + equivalent dispatch + 18 variants: entry `fsr4_pre_xmx`, 12 args, single `WorkgroupId`, guards `120×540/240×1080/480×2160`, counts `78/85/1`, grid/modes identical to 4.0.2x; helper rewritten (do not reuse `0x180002df0`); see [census](xmx412-spirv-census.md), [dispatch](xmx412-dispatch.md), [variants](xmx412-variants.md).
- [x] Offline compilation PRE `native_1080` positional (IR `49e069fd…`, envelope `ce372719…` → zebin `b1781bb4…`, code `68b962b5…`, `ze_info` byte-identical to the old one, BTIs `[8,9,1,2,3,4,5,6,7,10,11]`); see [offline 4.1.2](xmx412-offline-compile.md).
- [x] `macl`/`acc0` audit clean under a full constant mask (160 visited, 0 reads, overwrites 20/23/143/179/379; scope one kernel/input/output); see [audit](xmx412-macl-acc0.md) (commit `db2e834`). `runtime_approved=false` remains.
- [x] Bridge re-verified against 4.1.2: 0002/0003 keep, 0001 keeps its shape, registry promoted to 2 entries with a new digest; determinism + `apply --check` + shim 14/14; see [recheck](xmx412-bridge-recheck.md), [regen](xmx412-bridge-regen.md).
- [x] Spider-Man trace runbook pinned (DLL/pack/IR/envelope with SHA-256, contract and checklist); see [runbook](spiderman-trace-runbook.md) and [user checklist](xmx412-user-checklist.md).

## Still open (not runtime, not oracle, not real dispatch)

- [ ] Phase 1 runtime trace in a disposable prefix (user, manual): real grid, 11 tables + sampler, `rootParameters`, DIAG/FNV, pre/post bytes; see [spec](pre-trace-capture-spec.md) and [runbook](spiderman-trace-runbook.md).
- [ ] Output oracle and initial contents (formats of 8 images, bytes of arg 9/10/0, CPU reference); see [contract](pre-controlled-test-contract.md).
- [ ] Real dispatch: mask/local-size, new helper (`0xbbd0`+`0x27bc0`), 4.1.2 variant table (positional names not confirmed), remaining PREs/pass6/other families.

## Success criterion and safety

Do not modify the session's driver or the user's prefixes during analysis.
A runtime experiment must use a disposable prefix and per-process variables,
keep the driver canary, and check deterministic GPU readback plus injection logs.
The overlay, S_OK, or the disappearance of magenta are not considered sufficient.

The [shim baseline compiled from Linux](shim-cross-build.md) with LLVM-MinGW UCRT,
without running the DLL; the MSVC/Windows SDK variant was not compiled. The UCRT
imports still await runtime validation. Patched ANV Mesa compiled locally with
LLVM 23, without installing or running the ICD.
Official IGC/ocloc were extracted locally without installation and compiled a PRE
for B580. That does not demonstrate GPU correctness or compatibility of the remaining stages.
