# PRE native_1080: static reconstruction of resources

## Result

Analysis of the pinned DLL `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`
and of the PRE Xe2 `40102/native_1080`. It is static: the DLL was not executed, there
was no new capture, and there was no PRE dispatch. The synthetic image/sampler test
reported by the user (64 correct values and 1,984 sentinel words intact) only validates
that probe; it does not provide descriptors or data for the PRE resources.

**Bounded conclusion:** the normal path does materialize D3D12 views for PRE buffers and
copies image descriptors. The pinned local LLVM-MinGW headers allow identifying the COM
methods and the layouts used. Even so, the formats and dimensions of the source images,
the real size of the backing resources, and the initial bytes cannot be deduced from
these views. The DLL contains indirect D3D12 operations; the absence of direct imports
did not imply that it did not create views or copy descriptors.

## Exact map that is recovered

The normal dispatch path is `0x1800163c0..0x180017b6e` (`dil == 0`); it loads the RVA
array `0x68988` and binds roots 1–11 at `0x180017410..0x180017435`, and root 12 with the
sampler heap at `0x180017543`. The argument/BTI map was cross-checked with
`analysis/offline-pre/full/ze_info.yaml` and the pinned SPIR-V:

| PRE resource | Arg | Root/register | Relative heap/slot | Descriptor class in the signature | Recovered format/size |
|---|---:|---|---|---|---|
| mixed-access buffer | 0 | 1 / u0 | resources / 7 | UAV `BUFFER`, `R8_UINT`, `FirstElement=0`; `NumElements=resource.Width` | `GetDesc` requires `Dimension=BUFFER (1)` and `Width <= 0xffffffff`; the minimum depends on a factor from the variant table. For native_1080, factor 1: `Width >= 8.294.400 bytes`. The exact Width is runtime. |
| destination image | 1 | 2 / u1 | resources / 8 | Image2D ReadWrite | An image descriptor is copied to slot 8 via `CopyDescriptorsSimple`; the source descriptor and format are not recovered in this sequence. |
| image t0 | 2 | 3 / t0 | resources / 0 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t1 | 3 | 4 / t1 | resources / 1 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t2 | 4 | 5 / t2 | resources / 2 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t3 | 5 | 6 / t3 | resources / 3 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t4 | 6 | 7 / t4 | resources / 4 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t5 | 7 | 8 / t5 | resources / 5 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| image t6 | 8 | 9 / t6 | resources / 6 | Image2D ReadOnly | Source descriptor copied by helper `0x180002df0`, source index received from the caller; source format/dimensions pending. |
| buffer | 9 | 10 / t7 | resources / 9 | SRV `BUFFER`, `R8_UINT`, first element 0, 2,112 elements / bytes | Resource comes from context `+0xa80`; the view covers 2,112 B. Backing allocation and initial contents not deduced. |
| buffer header | 10 | 11 / t8 | resources / 10 | SRV `BUFFER`, `R8_UINT`, first element 0, 128 elements / bytes | Resource comes from context `+0xa98`; view/header of 128 B. Backing allocation and header bytes are runtime. |
| sampler | 11 | 12 / s0 | sampler heap / 0 | sampler | MIN/MAG/MIP linear; CLAMP U/V/W; bias 0, max anisotropy 1, comparison ALWAYS, MinLOD 0, MaxLOD FLT_MAX. |

Slot numbers are relative to the heap/table used by the normal path, not absolute
indices. `t7` and `t8` are SRVs according to the root signature even though their CM
types are ReadWrite. The destination image is arg 1/u1/BTI 9, not arg 8/t6; the `7` in
the `0,0,7` mask of the typed-quad store enables the `.xyz` channels, it is not a binding.

## Recoverable buffer data

### Arg 0 / u0

PRE generates a 128-byte write per group, in OWORD units, at index
`wg_y * 960 + wg_x * 8` (SPIR-V `:15977-15993`). With the domain accepted by the guards,
`wg_x < 120`, `wg_y < 540`, the exclusive end of the last write is:

```text
((539 * 960) + (119 * 8) + 8) OWORD * 16 bytes/OWORD
= 518400 * 16
= 8,294,400 bytes
```

The final store has that coverage if the full 120×540 grid is dispatched and the groups
pass their guard. In addition, the DLL calls `ID3D12Resource::GetDesc` on the buffer
selected as arg 0 and compares `Dimension` with `edx=1`, that is,
`D3D12_RESOURCE_DIMENSION_BUFFER`. **The factor in `eax` is a different value:** it is
loaded from field `+0x24` of `tabla[selector - 1]`, with stride `0x4f0` and the selector
in the DWORD `contexto+0x830`, or it is 1 by default (`0x180016984..0x1800169df`). Do not
confuse the two registers. It then checks `Width >= factor² * 0x7e9000` and
`Width <= 0xffffffff` (`0x180016973..0x180016a0e`; the indirect `GetDesc` is at
`+0x50`). Direct extraction from the pinned table identifies `native_1080` as selector 1,
with factor 1, so its lower bound is **8,294,400 B**. The 2160/4320 variants have factors
2/4, not other resource dimensions. It then uses `Width` as the `NumElements` of an
`R8_UINT` UAV in heap slot 7 (`0x180017184..0x1800171ff`). This does demonstrate a
capacity restriction on the resource in this path, but not its exact runtime Width; it
does not imply RGBA8. Arg 0 also has reads and scratch selected by arg 10. Do not
initialize it as an empty readback.

### Arg 10 / t8

The shader loads 128 bytes from arg 10 as a header. The fields used include DWORDs at
offsets 8–84, address/byte fields at 64–80, flags at byte 100, and a base at byte 104
(SPIR-V `:5190-5325`, `:5573-5602`). Bit `0x400` of the flags is a guard; bit `0x2000`
chooses between `base` and `base+16` for the float4 read. A 16-byte float4 is read from
arg 0 using `base` or `base+16` as the byte offset (`:5573-5614`, particularly the
`oword.ld.unaligned` at `:5606-5612`). Therefore, in this IR path, `base` **is not
consumed as a VA**: it is an offset relative to the arg 0 buffer, conditioned by the
`0x2000` flag. This identifies a relationship between resources, not the assigned
length/alignment of arg 0 nor the validity of the data the host places there. The other
header offsets must not receive semantic names without the caller's ABI either.

### Arg 9 / t7 and arg 10 / t8

`ID3D12Device::CreateShaderResourceView` is called with the resource from state `+0xa80`
for slot 9 and `+0xa98` for slot 10 (`0x1800172e1..0x180017367`). Both descriptions have
`Format=0x3e` (`DXGI_FORMAT_R8_UINT`), `ViewDimension=1` (`D3D12_SRV_DIMENSION_BUFFER`),
`Shader4ComponentMapping=0x1688` (`D3D12_DEFAULT_SHADER_4_COMPONENT_MAPPING`),
`FirstElement=0`, `StructureByteStride=0`, `Flags=0`. `NumElements` is 0x840
(2,112 bytes) for arg 9 and 0x80 (128 bytes) for arg 10. The first element is typed,
not `RAW` (the flags are zero). SRVs limit the visible range, but they do not report the
Width of each backing resource nor its initial contents. Arg 10 contains at least the 128
bytes that the kernel loads; the DWORDs of that header are entries supplied by the caller,
not values initialized by this descriptor.

## Caller graph: APIs, handle tables and view creation

The pinned dump (`analysis/fsr-xmx-disassembly.txt`, SHA-256
`4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0`) gives a direct
call-xref to `0x1800163c0`: `0x1800058be` inside the context path at
`0x1800058a1..0x1800058e6`. That function is an internal wrapper, not an exported
boundary. The public FFX boundary includes `ffxCreateContext` (`0x180001290`),
`ffxDispatch` (`0x1800013b0`) and `ffxQuery` (`0x180001400`); the wrapper calls the PRE
setup/dispatch with `rcx=estado`, `rdx=registro` and `r8=interfaz D3D12` (x64
convention). The source image descriptors are read/copied from the context's source heap;
this copy block does not show who created those images.

The vtable attribution is cross-checked against `ID3D12Device`/`ID3D12DescriptorHeap` in
the pinned local headers (SHA below): `+0x48` on the descriptor heap is
`GetCPUDescriptorHandleForHeapStart`; `+0x90`, `+0x98` and `+0xc0` on the device are
`CreateShaderResourceView`, `CreateUnorderedAccessView` and `CopyDescriptorsSimple`. The
`0x3e` written at `0x1800171c2`/`0x1800172fd` is the D3D12 `Format` field, not a callback
type nor an FFX request.

- The arg 0 buffer receives an `R8_UINT` UAV of type `BUFFER`, `FirstElement=0`,
  `NumElements=resource.Width`, stride/counter/flags zero, in heap slot 7. The path calls
  `GetDesc`, requires BUFFER dimension and applies the capacity limit that depends on the
  variant factor documented above.
- Arg 9 / t7: `CreateShaderResourceView` with resource `[context+0xa80]`, SRV
  `R8_UINT BUFFER`, `NumElements=0x840`, destined for heap slot 9.
- Arg 10 / t8: analogous with `[context+0xa98]`, `NumElements=0x80`, slot 10.
- Args 2–8 / t0–t6: at `0x18001711b..0x18001717f` the helper `0x180002df0` is invoked
  seven times, with destination 0..6 and source indices selected in `r8d`: slot 0 takes
  `[rsp+0x78]`, slot 1 `[rsp+0x7c]`, slot 2 `esi`, slot 3 `[rbp-0x80]`, slot 4
  `[rbp-0x7c]`, slot 5 `edi` and slot 6 `ebx`. Those values are selected in the dispatch
  from the resource register (`r13`); they are not format constants. The helper obtains
  the initial CPU handle of the source heap at `[context+0x1b40]`, adds
  `sourceIndex * descriptorIncrement` and calls `ID3D12Device::CopyDescriptorsSimple`
  (`+0xc0`) to copy it into the internal PRE heap. This establishes the provenance per
  descriptor, not the format or dimensions of the source texture.
- Arg 1 / u1, heap slot 8: the normal branch also calls `CopyDescriptorsSimple`
  (`0x18001727e`) with destination index 8; the source is another image descriptor. The
  source is not materialized as a `D3D12_*_VIEW_DESC` in this block, so the image format
  is not derived here.

The loop at `0x180017410..0x180017435` binds the 11 tables; root 12 binds the sampler.
The only direct call-xref to `0x1800163c0` remains `0x1800058be`. The DLL selects resources
stored in the context and creates/copies their views, but this dump does not recover who
created the source resources nor the initial bytes of the images/buffers. The
reconstruction has not completed the chain from the public entry point to each
creator/handle; it does not demonstrate that this chain is absent from the DLL. A record
of the effective dispatch values would require a capture.

The extractor `tools/reconstruct_pre_resources.py` pins DLL, dump and header hashes,
recovers the SRV/UAV, the relationship between context and heap slots, and the windows of
the descriptor copies, without loading the DLL:

```bash
python tools/reconstruct_pre_resources.py \
  artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-xmx-disassembly.txt
python -m unittest discover -s tests -p test_pre_resources.py -v
```

The optional tests with local artifacts cross-check the table of the 18 variants and
compile assertions against the real Windows headers: vtable and structure offsets,
`R8_UINT=62`, `BUFFER=1` and component mapping `0x1688`. This is syntactic compilation,
not execution of a DLL. The full local report is kept in
`analysis/pre-resource-descriptors.json`.

## What constrains image dimensions and formats

The IR fixes 2D images and the grid guard `120×540×1`; it does not fix the width/height of
the images, the DXGI/Vulkan format, the number of physical channels, mip/layer, sample
count, the concrete descriptor permissions, or the allocated bytes. `native_1080` is a
variant selector of the kernel, not a D3D12 description of each resource. The sample/load
operations of the IR demonstrate usage, not the description chosen by the host. The
dynamic descriptor pointing to the resource does not appear materialized in the root
signature nor in the constant slot table.

The static investigation of the DLL locates the creation of the root signature at
`0x18002c13f..0x18002c4bd`, the sampler at `0x18002cc23..0x18002cc8b`, and the normal
dispatch indicated above. Inspection of the PE imports (`llvm-objdump -p`) finds no direct
imports of `CreateCommittedResource`, `CreateShaderResourceView` or
`CreateUnorderedAccessView`. That only describes the import table. The dump does show
direct calls through D3D12 vtables to create views and copy descriptors. It does not
resolve a `CreateCommittedResource` allocation call nor rule out other creation paths.
"I did not find an import" is not equivalent to "the DLL does not allocate resources".

## Required oracle and minimal capture

It remains pending to follow the source indices to the routines that create and fill each
view/resource; it has not been shown to be impossible to resolve statically. An
alternative is an authorized host trace on the same `native_1080` path, before the first
PRE dispatch. It must record, correlated by resource/descriptor ID:

1. `CreateCommittedResource` / placed/reserved resource or import, with the complete
   `D3D12_RESOURCE_DESC` (dimension, width, height, depth/array, mip, format, sample count,
   layout, flags), heap properties and allocation size/offset where applicable.
2. Each `CreateShaderResourceView`/`CreateUnorderedAccessView` and `CopyDescriptors*`:
   associated resource, `D3D12_*_VIEW_DESC`, format, mip/layer/range, final slot and heap.
   Also follow aliases/copies, not only handle addresses.
3. `GetDesc`/identity of the resources bound to heap slots 0–10 just before the dispatch;
   input values/bytes of the buffers in args 0/9/10. For arg 10, keep the 128-byte header
   and the bytes of arg 0 referenced by the offset at byte 104, with readable limits and
   original flags; do not treat it as a virtual address.
4. GPU root-table handles, heap bases/increment, sampler desc, `Dispatch` grid and
   resource state/transitions. The local CM/hardware size requires separate evidence: it
   is not an argument of `ID3D12GraphicsCommandList::Dispatch`. Dump pre- and
   post-dispatch data without modifying the observed state.

An instrumented D3D12 trace in a **disposable prefix** or verifiable documentation of the
caller can complete the descriptions/identities that the copied descriptors do not carry.
That trace is input evidence, not a functional correctness oracle, nor proof that
Proton/VKD3D correctly implemented PRE. Record executable/versions/hashes, correlate IDs
and handles with roots/slots, save pre/post bytes and preserve the original capture; the
result of the synthetic probe is not a substitute.

Once the source resources are identified, sizes/layouts can be fixed and a reproducible
input can be created. A comparison of the PRE output against an independent reference
implementation (or a CPU oracle validated against it) will still be needed to claim
functional correctness; a descriptor capture, injection, non-corruption of guards or
absence of errors does not replace it.

## Independent corroboration with REA

See [static REA evidence](rea-static-evidence.md): complete imports without direct
resource creation, 5 FFX exports and 5 resources with hashes identical to the local
manifest. With Ghidra 12.2 available, the [dispatch was decompiled](pre-dispatch-ghidra.md):
stock bindings by name, grid formula, fail-stops and the copy helper.

## Reproduction and pinned evidence

```bash
sha256sum artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll \
  analysis/fsr-xmx-disassembly.txt
llvm-objdump -p artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll
```

Results at the time of writing: DLL SHA-256 `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`;
disassembly SHA-256 `4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0`.
Additional references: `docs/pre-resource-map.md:123-150`,
`docs/pre-controlled-test-contract.md:20-65,88-108`,
`analysis/offline-pre/full/ze_info.yaml:15-160`,
`analysis/fsr-resources/xe2-first.spvasm:5166-5185,5190-5325,5573-5634,15977-15993`,
`analysis/pre-dispatch-snippet.txt:76-89`. Headers cross-checked:
`artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/d3d12.h`
SHA-256 `23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e` and `dxgiformat.h`
SHA-256 `8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48`. The disassembly
SHA identifies the file used for the addresses; it does not independently certify the
correctness of its decoding.
