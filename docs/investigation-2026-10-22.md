# First investigation: packs and ABI

## Later update

See [pre-resource-map.md](pre-resource-map.md). The byte-offset parser recovers **690**
blocks, including the six POST that the heuristic carver skipped. In PRE the
CompileOptions/InternalOptions were confirmed **NULL**: the strings travel inside
the bytecode and the shim preserves them. The hypothesis that those options were
lost through the helper's filter is not demonstrated and is corrected for this case.
This document keeps the initial findings as a historical record.

## Result

The DLL's resources were extracted without loading or executing it, the three LZMS
packs were decompressed, and **684 CM-SPIR-V candidates** were recovered that `spirv-dis`
could disassemble. This shows that we can inspect real kernels;
**it does not demonstrate IGC compilation, execution or GPU compatibility**.

## Resources

| RCDATA / language | Compressed bytes | Decompressed bytes | Candidates recovered |
|---|---:|---:|---:|
| 40101 / 1033 | 6,454,442 | 36,151,282 | 246 |
| 40102 / 1033 | 3,777,348 | 23,164,789 | 252 |
| 40103 / 1033 | 2,229,762 | 13,528,965 | 186 |

The exact association between resource ID and architecture/model selection
requires following the DLL's references; it must not be inferred from order alone.
The first pack contains 252 occurrences of the SPIR-V magic but only 246 candidates
passed the current carving: six cases remain to be investigated. Do not call this
process a complete container parser nor claim that it extracted every kernel.

SHA-256 of the decompressed packs:

- 40101: `486b16078b5f90f0b577d5eac3851f81c88f5b0b706444f0d908cdc320223b6c`
- 40102: `8b520078fd9457593d6cf726f79802634a4fcbd5372819f81c7e359ecec39d24`
- 40103: `f6d884bc26735c04ca2fa57d70ed31d3db3de48c3b0444121cf70a2937987999`

## Method and verification

1. `extract_resources.py`: minimal PE parser with the standard library, RVA
   translation and bounded walk of the resource tree. No LoadLibrary nor Wine.
2. Compression API header `0a51e5c0`, algorithm 5 = LZMS, blocks of 65,536 bytes.
3. `binary-refinery==0.11.2` installed in an isolated `.venv` failed with LZMS offset
   errors on the three packs. Partial output was not accepted and lenient mode was not used.
4. wimlib at revision `cd5e231c348c255ae5088873b5a66ee0eb96fa07` was compiled
   **locally**, without `make install`.
5. `decompress_mscf.py` validates the header CRC, size limits, exact size and
   absence of leftover bytes; it uses only the decompression API of the local libwim.
6. `carve_spirv.py` searches for the magic, walks bounded instructions and requires an entry point
   and an OpFunctionEnd end. It keeps offsets, hashes and strings in the gaps.
7. The 684 candidates were disassembled without error. The `spirv-val` validator fails on
   the first module of 40102 with `TypeBufferSurfaceINTEL must appear in a block`.
   Therefore do not claim general SPIR-V semantic validation. It must be cross-checked against
   the Intel/IGC tools for this CM dialect.
8. Twelve synthetic tests of parsers and rejection of malformed inputs pass.
   They do not yet cover an LZMS round-trip nor GPU execution.

Complete artifacts and reports: `analysis/fsr-resources/`, `analysis/kernels-*`,
`analysis/disassembly-check.json`. Everything is excluded from Git.

## Representative kernel

`analysis/kernels-0001/module-0000.spv`, offset 0 of pack 40102:

- Entry point `fsr4_pre_xmx`, model `Kernel`, SPIR-V 1.1.
- Extensions `SPV_INTEL_vector_compute` and `SPV_KHR_no_integer_wrap_decoration`.
- Memory model Physical64/OpenCL.
- SubgroupSize = 1; no literal LocalSize observed in the execution modes.
- Input parameters: **11 surfaces and 1 sampler**:
  - 3 BufferSurfaceINTEL ReadWrite;
  - 1 Image 2D ReadWrite;
  - 7 Image 2D ReadOnly;
  - 1 Sampler.
- Pack 40102 includes 18 variants by name of the 14 PRE/P1..P12/POST families.
- Pack 40103 contains `lite_p1a`, `lite_p1b`, `lite_p2`, `lite_p3`, `i8_p6`,
  `i8_fnb64`, PRE and POST.

The workgroup size must NOT be inferred from the DLL's baseDispatch messages.
The conversion of those parameters to zebin/BTI has not been verified yet.

## Incompatibilities and candidates for adaptation

### 1. GPU information not propagated to the caller

In upstream `shim/src/dll/IgdextApiDll.cpp:343-500`, the original and
Context1 variants create a temporary `INTCExtensionInfo1`, initialize the extensions and do not copy
their results to the caller's `INTCExtensionInfo`. Both receive the old
structure; **Context2**, not Context1, receives the extended one.

The mod contains diagnostics/selection by GTGeneration and Xe2 packages. The real
effect of receiving zeros or uninitialized information still has to be demonstrated,
but it is a concrete incompatibility of the API implementation.

Candidate: explicitly copy the device information base subobject and the
driver fields after success. Do not memcpy 200 bytes into the 192-byte
structure (sizes derived from the Windows x64 ABI, pending static_assert).
Also review the early return for a pre-existing context.

### 2. Compiler options discarded

In the gap immediately after the first 40102 module the following appears:

```text
-vc-payload -Xfinalizer '-noDPASMacro'
 -target-features=+ocl_runtime
```

The first text is repeated in all 252 candidates of that pack. These are adjacent strings,
not a capture of the call arguments: the record format still has to be reconstructed to
establish with certainty CompileOptions vs InternalOptions.

`tools/cm-compile.sh:42-54` only keeps tokens with prefixes `-doubleGRF` or `-ze-`;
it would discard `-vc-payload` and the finalizer configuration. `InternalOptions` is not
persisted either. This alters the compile request relative to the pack's strings; it has not
been determined whether it causes an error or incorrect results.

Candidate: preserve the relevant options and values explicitly and with tests,
include them in the cache identity, and compare the zebin before broadening the
accepted options indiscriminately.

### 3. Sampler and surface table

The observed PRE has **11 surfaces + sampler**. The DLL includes the ABI string
'one table per SurfaceIndex/sampler'. ANV assumes that the last N words of
push constants are surface tables, but treats samplers separately.

A sampler table at the end or interleaved may shift the indices. This is a
concrete layout risk, not an already-proven incompatibility: the real root signature
still has to be reconstructed. The packer accepts explicit `--heap` and `--surf`, but the
helper forces them to `auto`. It could be the minimal adaptation channel if we confirm
the map.

### 4. Aspects not to be confused with support

- Context accepts 4.20.0 by version comparison, not because it implements the whole SDK.
- ShaderInputType must be CM_SPIRV=2; SPIRV=4 is another path.
- GetCachedBlob returns E_NOTIMPL; in the mod it may be diagnostic only.
- S_OK may correspond to a placeholder/no-op. Injection evidence and GPU readback
  are needed to consider the path valid.

## Next stage

1. Reconstruct the pack boundaries/records to extract exact options and
   explain the six unrecovered candidates from 40101.
2. Map references to the DLL's resources, Xe2 selection and root signature creation.
3. Prepare a small context correction with layout/copy tests.
4. Compile a representative kernel offline with the Intel toolchain and
   compare zebin metadata with the packer (does not require running the DLL nor GPU).
5. Only after authorization, isolated GPU microtest; not Cyberpunk as the first test.

## Reproduction

From the root, with the original files already present:

```bash
python tools/extract_resources.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-resources

# Compilar dependencia local; no instalar en el sistema.
git clone https://github.com/ebiggers/wimlib.git upstream/wimlib
git -C upstream/wimlib checkout cd5e231c348c255ae5088873b5a66ee0eb96fa07
(cd upstream/wimlib && ./bootstrap && \
 ./configure --without-ntfs-3g --without-fuse && make -j4)

for n in 0000 0001 0002; do
  python tools/decompress_mscf.py \
    analysis/fsr-resources/resource-$n.bin \
    analysis/fsr-resources/resource-$n.raw \
    --libwim upstream/wimlib/.libs/libwim.so
  python tools/carve_spirv.py \
    analysis/fsr-resources/resource-$n.raw analysis/kernels-$n
done
python -m unittest discover -s tests -v
```

The extractors refuse to overwrite; use new directories when repeating.
A build/autotools toolchain is needed for wimlib and SPIRV-Tools for the
external checks. binary-refinery does not need to be installed for the successful path.

Format/API sources:
- https://wimlib.net/apidoc/group__G__compression.html
- https://github.com/ebiggers/wimlib
- https://github.com/binref/refinery/blob/master/refinery/units/compression/mscf.py
- https://github.com/KhronosGroup/SPIRV-Headers/blob/main/include/spirv/unified1/spirv.core.grammar.json
