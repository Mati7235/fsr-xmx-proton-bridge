# PRE options and resource reconstruction

## In short

PRE is the initial stage that prepares the data before upscaling. We reconstructed
its request to the driver and the order of its resource slots, without running
the mod. We found a one-slot offset in the bridge's automatic mapping when
comparing it with the VKD3D reference code. It is not yet a GPU test.

We also corrected an earlier suspicion: the options found next to the kernel
travel **inside the bytecode block**. The two API options pointers are NULL in the
inspected PRE. There is no evidence that the helper's external options filter
removes these embedded options.

## Later progress

The [offline compilation of the PRE](offline-pre-compilation.md) has already confirmed the BTIs
and the consumption of the embedded options. A candidate CMK3 profile and reader
exist, not yet installed or validated on GPU. The pending sections of
this document describe the state before that compilation.

## Scope and revisions

- DLL SHA-256: `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`.
- xess-xmx-linux (original analysis): `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`;
  current base of the patch stack: `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`.
- Reference VKD3D: `ef9a02e873715c9e2da0d6db8a236aca8380b303`, cloned locally
  in `upstream/vkd3d-proton`. **It does not identify the installed Proton**.
- Only the normal PRE was reconstructed. The other stages require their own analysis.
- All the following data is static; the DLL was not loaded with Wine/LoadLibrary.

## 1. The CM blocks have a footer with verifiable lengths

Recovered format, without including the pack's alignment padding:

```text
SPIR-V [N bytes]
cadena A terminada en NUL
cadena B terminada en NUL
u64 little-endian: N
u64 little-endian: tamaño del pie completo
11 bytes: "-vc-payload"
```

The full footer starts at A and includes the final marker. There is no need to
guess the end of the SPIR-V by walking instructions: the footer declares its length.
The strings are ASCII and each footer has exactly two NUL terminators.

Observed values:

| Pack | String A | String B | Footer |
|---|---|---|---:|
| 40101 | `-vc-payload` | ` -target-features=+ocl_runtime` | 70 bytes |
| 40102 | `-vc-payload -Xfinalizer '-noDPASMacro'` | the same | 97 bytes |
| 40103 | both variants depending on the record | the same | 70 or 97 bytes |

The leading space of B and the single quotes of A are preserved. Do not normalize
them or rebuild a shell line from them.

`tools/parse_cm_payloads.py` validates the consistency of each footer with the initial magic,
the buffer bounds and both strings. It recovers **252 + 252 + 186 = 690 blocks**.
All extracted IRs were disassembled with `spirv-dis`, without errors. This is **not**
equivalent to `spirv-val`, IGC compilation or GPU correctness.

Pack 40101 also contains 18 DXBC containers detected by magic and size, and
six additional gaps with non-null content not yet classified. It is not claimed
that the whole pack format has been decoded.

### The six missing modules

They are real and recoverable POST modules. The earlier carver interpreted the first bytes
of `-vc-payload` as an instruction: word `0x2d63762d`, false count 11619. When
there was a large gap after the POST it could keep advancing through data unrelated to
the SPIR-V. It was not evidence of kernel corruption. The new parser uses the
footers and recovers the 18 POST variants of 40101.

## 2. What the DLL actually sends to the API

PRE function: `0x18002bb60..0x18002d447`.

- `0x18002c8cf..0x18002c914`: builds the INTC descriptor.
- Bytecode pointer at descriptor `+8`; length at `+16`.
- ShaderInputType at `+24` = **2, CM_SPIRV**.
- CompileOptions `+32` = **NULL**.
- InternalOptions `+40` = **NULL**.
- `0x18002cb00`: indirect call to CreateComputePipelineState.

The length is copied from the table of the selected variant, with no later trimming.
The tables were read directly from the DLL and cross-checked with the footers:

| PRE native_1080 | IR | Footer | Real BytecodeLength |
|---|---:|---:|---:|
| Pack 40101 | 329008 | 70 | **329078** |
| Pack 40102 | 330108 | 97 | **330205** |

The **18 variants of both packs** match exactly `IR + pie`, without
padding. Table evidence: RVA `0x56160`, stride `0x4f0`, PRE at `+0xd8`,
offset at `+8` and length at `+0x10` of the PRE record; alternative table RVA
`0x613b0`, stride `0xf0`, offset `+0`, length `+8`.

The shim persists all the bytes of `CS.BytecodeLength` in DynKernelId
(`shim/src/dll/D3D12Api.cpp:43-81`). Therefore, on this path there is no explicit trimming
of the footer. **Pending:** verify with IGC/ocloc that the embedded options are interpreted and
which binary they generate. Do not pass the trimmed `.spv` to the compiler assuming it reproduces
the original request exactly: use the full `.cmspv` for that comparison.

### Xe2 pack selection

The selection function at `0x1800329d0` queries OPTIONS2 and writes the context flag
`+0x834` according to `SIMD16Required` and the success of the query (`0x180032d07..29`).
The flag is not a direct comparison of GTGeneration. The environment value
`FSR4_XMX_DPAS`, if the override path is processed, replaces it depending on whether it is 16 or not.
A non-null flag selects pack 40102; the failure diagnostic calls it the Xe2 pack.
The loader `0x18001a450` maps selectors 0/1/2 to RCDATA 40101/40102/40103.

Do not pin those overrides to hide an incorrect detection during the tests.

## 3. Resource map: which slot is which

A *root signature* is the list of slots the shader expects. A
*descriptor* is the card that points to the real resource. A *sampler* indicates how to read
a texture (for example, interpolating and limiting coordinates to the edges).

Root signature construction: `0x18002c13f..0x18002c4bd`.

- Root 0: one 32-bit constant, b0, space 0.
- Roots 1..11: eleven resource tables, one descriptor per table.
- Root 12: sampler table, one descriptor s0.
- Visibility ALL; space 0; range offset 0; flags 0.
- Root signature 1.0; **zero static samplers**.

Normal dispatch path, `0x1800163c0..0x180017b6e`, branch `dil == 0`:
`SetComputeRootDescriptorTable` at `0x180017428` assigns roots 1..11 using the RVA array
`0x68988`; the final assignment at `0x180017543` uses root 12 for the sampler heap.
The alternative branch `dil != 0` uses another scheme and is not covered by this map.

| Root | Register | Parameter type expected in PRE | Relative slot in resource heap | Reference push offset |
|---:|---|---|---:|---:|
| 0 | b0 | one-DWORD constant | — | 0 |
| 1 | u0 | BufferSurface ReadWrite | 7 | 4 |
| 2 | u1 | Image2D ReadWrite | 8 | 8 |
| 3 | t0 | Image2D ReadOnly | 0 | 12 |
| 4 | t1 | Image2D ReadOnly | 1 | 16 |
| 5 | t2 | Image2D ReadOnly | 2 | 20 |
| 6 | t3 | Image2D ReadOnly | 3 | 24 |
| 7 | t4 | Image2D ReadOnly | 4 | 28 |
| 8 | t5 | Image2D ReadOnly | 5 | 32 |
| 9 | t6 | Image2D ReadOnly | 6 | 36 |
| 10 | t7 | BufferSurface ReadWrite | 9 | 40 |
| 11 | t8 | BufferSurface ReadWrite | 10 | 44 |
| 12 | s0 | sampler (separate heap) | 0 of the sampler heap | 48 |

**Limit:** the order and slots of the tables are reconstructed. The type column
matches the entry point parameter order; it is not yet a check of the BTIs of the
compiled zebin. We have not yet identified each texture as
'color', 'depth', 'motion vectors', etc. Do not invent those names.
Nor confuse the CM-type ReadWrite access with UAV range: t7/t8 are SRV ranges
according to the root signature, even though their SPIR-V type is declared ReadWrite.

Relative slots = GPU base G + increment S * slot. They are not real physical addresses
nor absolute indices of the user's session.

## 4. Concrete offset when compared with the bridge

In reference VKD3D, `libs/vkd3d/state.c:670-731,891-919`:

- The constant contributes 4 bytes.
- All tables, including the sampler one, contribute one DWORD each.
- Total push size = **4 + 12*4 = 52 bytes**.
- The resource tables occupy `[4,48)`; the sampler occupies `[48,52)`.

`libs/vkd3d/command.c:7711-7717,7760-7766` repacks the tables by order and emits those
DWORDs in the range. The table count does not exclude samplers.

The current ANV patch uses (`patches/0001-anv-cm-kernel-injection.patch:700-720`):

```text
base = push_size - 4 * nsurf
     = 52 - 4*11
     = 8
```

Therefore it would read offsets `[8,12,...,48]`, corresponding to roots **2..12**, instead of
`[4,8,...,44]`, roots **1..11**. u0 is skipped and the index of table s0
is treated as if it pointed to the resource heap.

It is a concrete static incompatibility **under this reference layout and the
surface order assumed by the packer**. It remains to corroborate the layout of the
real Proton version and the BTI order before considering it proven at runtime.

### Sampler: partial match, not another proven blocker

Template at RVA `0x72a20`: Filter `0x15` = MIN_MAG_MIP_LINEAR and AddressU/V/W `3` = CLAMP.
Creation at `0x18002cc23..0x18002cc8b`; LOD bias 0, anisotropy 1, comparison ALWAYS,
border 0, MinLOD 0, MaxLOD FLT_MAX according to the descriptor assignments.

ANV does not take that dynamic sampler: without a static sampler it uses a linear/clamp fallback.
Filter and border modes match, but this is not general dynamic sampler support
nor full state equivalence (for example ANV MaxLOD=14). It remains to check
which sampling instructions PRE uses and how it interprets its coordinates.

## 5. Proposed minimal adaptation (not applied)

1. Explicit metadata channel per kernel/layout so that the helper/packer indicates
   where the surface table starts and its order; **do not** change all
   XeSS kernels globally to base 4.
2. For this reference PRE, expected base 4 and eleven surfaces; exclude the
   sampler DWORD. Confirm the `arg_index -> BTI` order with IGC first.
3. Separate resource heap/slot selection from sampler handling. Do not use
   the sampler index to access the resource heap.
4. Keep the full CM blob with its embedded options when compiling offline.
5. Independently fix the GPU information that is not copied to the
   caller in CreateDeviceExtensionContext/Context1.

Copying DLLs is not enough. The next useful milestone is to compile this PRE offline and
examine its zebin: arguments, BTIs, GRFs, payloads and effects of the options.
It does not require running Cyberpunk nor the mod's DLL.

## Reproduction of this stage

```bash
# Requiere los packs ya descomprimidos de la primera investigación.
for n in 0000 0001 0002; do
  python tools/parse_cm_payloads.py \
    analysis/fsr-resources/resource-$n.raw analysis/cm-payloads-$n
done
python tools/reconstruct_pre.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  > analysis/pre-reconstruction.json
python -m unittest discover -s tests -v
```

The parser keeps two files per record: `.spv` for disassembly and `.cmspv`
with the full footer to reproduce the input to the compiler. Generated reports:
`analysis/cm-payloads-*/manifest.json`, `analysis/cm-payloads-verification.json`,
`analysis/pre-reconstruction.json`, `analysis/recovered-six.json`.
Third-party and derived files are not added to Git.
