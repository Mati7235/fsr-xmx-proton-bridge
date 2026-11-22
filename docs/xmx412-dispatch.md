# XMX 4.1.2: equivalent PRE dispatch (static, CPU-only)

Static analysis only of the pinned DLL
`fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` (45,558,272 bytes). No execution
of the DLL, no GPU/Wine, no touching `artifacts/original`, games or prefixes. The 4.1.2 disassembly
was read without Ghidra/REA (the provider was unavailable, `GHIDRA_INSTALL_DIR` not set): PE parsing
with stdlib plus `llvm-objdump -d`. The payload audit adds IGA output and the census adds
`spirv-dis` output; the model strings were reviewed separately in Ghidra 12.2 (see
[xmx412-model-selection.md](xmx412-model-selection.md)). The `FUN_*` names of the old DLL are
Ghidra-synthesized; here RVAs `0x…` are used (VA = `0x180000000` + RVA).

Pinned in `tests/test_xmx412_dispatch.py` (fail-closed). The offline compile recipe and the expected
`ze_info` BTIs live in [xmx412-toolchain.md](xmx412-toolchain.md); the registry pins and the profile
status live in [shim-bridge.md](shim-bridge.md).

## The dispatch a shim must reproduce

One `Dispatch` of `fsr4_pre_xmx`, with every input bound:

- Grid `(120, 540, 1)` for `1920×1080`, from `x = ((w+15)>>4); x += x&1; y = h>>1`.
- 13 root parameters: `b0`, eleven resource tables (roots 1..11) and one sampler table (root 12),
  for 12 tables and 52 push bytes.
- 12 arguments in fixed order (buffer, image, seven images, two buffers, sampler).
- UAV slot 7, SRV slots 9 and 10, seven copied images in slots 0..6, destination image slot 8,
  sampler 0.
- A 52-byte push range with the first table at offset 4; the bridge uses 8.
- Seven fail-stop strings and ten stock names that a broken binding trips.

## DLL and PE

| | old | 4.1.2 |
|---|---|---|
| SHA-256 | `3eb08656…08eba53` | `fadbcb50…37f44732` |
| size | 25,779,712 | 45,558,272 |
| ImageBase | `0x180000000` | `0x180000000` |
| `.text` | vsize `0x52aff` vaddr `0x1000` | vsize `0x7762f` vaddr `0x1000` |
| `.rdata` | vaddr `0x54000` | vaddr `0x79000` |

Old build SHA-256: `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`.

## Equivalent PRE dispatch: `0x180024e00..0x18002666a`

Logic equivalent to the old `FUN_1800163c0` (`0x1800163c0..0x180017b6d`, 6,062 B, exclusive end
`0x180017b6e`):

- 4.1.2 entry: RVA `0x24e00` (VA `0x180024e00`). Prologue with cookie
  (`mov %rsp,%r11 … sub $0x270,%rsp`) and gate `ctx+0xa94==0 || ctx+0xa80==0 || ctx+0xa88==0` →
  fail-stop `PRE params are not ready` (jump to `0x2666a`). Logical range `0x24e00..0x2666a` = 6,250
  B (+188 B vs old).
- `.pdata` splits it into three entries (same logic, separate unwind): `[0x24e00,0x24e5a)` 90 B +
  `[0x24e5a,0x25147)` 749 B + `[0x25163,0x2666a)` 5,383 B (gap `0x25147..0x25163` = epilogue/ret).
  The old one was a single entry.
- Only direct caller: `E8` at RVA `0x8e3a` (`e8 c1 bf 01 00` → `0x24e00`) inside the function
  `[0x8a1c,0x99b7)` (3,995 B). Analogous to the old call site `0x1800058be` in `FUN_1800052e`.
  Verified by sweeping all `E8` in `.text` (1 single hit).
- The second half contains the 10 stock names, the gates for constants, ABI and ScratchBuffer, slot
  selection via table `+0x8efc`, the `GetDesc`/bounds checks, the barriers and the final dispatch.

Pinned RIP-relative LEAs (site → chain):

| site RVA | target RVA | string |
|---|---|---|
| `0x25110` | `0x311790` | `PRE runtime-flag ABI mismatch…` |
| `0x26635` | `0x311890` | `PRE runtime geometry is unavailable.` |
| `0x26646` | `0x311840` | `PRE ScratchBuffer layout mismatch…` |
| `0x26652` | `0x311740` | `PRE constants are incomplete…` |
| `0x2665e` | `0x3116f0` | `PRE required stock binding missing…` |
| `0x2666a` | `0x3115a0` | `PRE params are not ready…` |
| `0x24ea9` | `0x3115e8` | `MLSR_Optimized_Constants` (table) |
| `0x24ef2` | `0x311620` | `ScratchBuffer` (table) |

Plus 49 LEAs to the first table (`0x3101e8..0x310410`) spread across `0x19782..0x25232`, with the
PRE cluster at `0x24ea9..0x25232` (see `test_lea_anchors_point_at_strings`).

## Dispatch geometry (derived, not observed at runtime)

Identical to the old one, byte for byte in intent:

```text
w = *(u32*)(ctx+0x840);  h = *(u32*)(ctx+0x844);
x = (w + 15) >> 4;  x += x & 1;  y = h >> 1;
```

4.1.2 evidence (`llvm-objdump`, VA `0x180…`):

- `0x26094: add $15, %eax` (`83 C0 0F`), `0x26097: shr %edi` (`D1 EF`, `y = h>>1`),
  `0x26099: shr $4, %eax` (`C1 E8 04`).
- `0x2609c: mov %eax, %r15d` (`44 8B F8`), `and %r13d, %r15d` (`45 23 FD`), `add %eax, %r15d`
  (`44 03 F8`).
- `r13d == 1` set at `0x25d55: mov $1, %r13d` (`41 BD 01 00 00 00`) with no rewrite up to the grid
  (verified by grepping `r13` in `0x24e5a..0x26700`). Then `x += x&1` uses `r13d` as the immediate
  `1`, same as the old `x += x&1`.
- `ctx+0x849==0`, `w==0`, `h==0` → `PRE runtime geometry…` via `0x02d710` (in `0x26062..0x2608e`),
  same as the old (`ctx==0 || ctx+0x849==0 || w==0 || h==0`).

For `w=1920,h=1080`: `(120,540,1)`. The DLL strings confirm it: `PRE … baseDispatch=120x540x1` (also
`60x270x1`, `30x135x1/2` for other passes, 13 occurrences of `baseDispatch`, same as the old one).

## Modes (equivalent to `FUN_18001c9c0`)

Mode = return value of the function at RVA `0x2bed0` (pdata `[0x2bed0,0x2bf61)`, 145 B, same size as
the old `FUN_18001c9c0` at `[0x1c9c0,0x1ca51)`, 145 B, relocated).

- Call site: `0x25a3e: E8 8D 64 00 00` → `0x2bed0`, result in `0x68(%rsp)`, then
  `0x25e7e: mov 0x68(%rsp), %esi`.
- `0x25e82: cmp $2, %esi; je 0x2662e` and `0x26055: cmp $3, %esi; je 0x2662e` → `2,3 → return 1`
  (`0x2662e: mov $1, %al; jmp …`), no dispatch.
- `0x260a5: cmp $4, %esi; … mov %r13d,%r15d; mov %r13d,%edi` → `4 → (1,1,1)` (r13d=1).
- `0x260b2: cmp $5, %esi; … mov %r13d,%edi` → `5 → (x,1,1)`.
- `0x260bc: cmp $6, %esi; mov $0x44,%eax; cmove %eax,%edi` → `6 → (x,0x44,1)`.
- Default → `Dispatch(x,y,1)` at `0x26394` and `0x263c9` (`FF 50 70` = `call *0x70(%rax)`), with
  `b0=0` via `SetComputeRoot32BitConstant` (`FF 90 08 01 00 00` = `*0x108`).

## Root signature and slot map

The old build builds the signature at `0x18002c13f..0x18002c4bd`: root 0 is a 32-bit constant `b0`,
roots 1..11 hold one resource descriptor each, root 12 holds sampler `s0`; visibility ALL, space 0,
range offset 0, flags 0, version 1.0, no static samplers. The `dil == 0` branch binds roots 1..11 at
`0x180017410..0x180017435` from RVA array `0x68988` (`SetComputeRootDescriptorTable` at
`0x180017428`) and root 12 at `0x180017543`; the `dil != 0` branch is not covered.

| arg | root | register | PRE type | heap slot | push | BTI |
|---:|---:|---|---|---:|---:|---:|
| 0 | 1 | u0 | BufferSurface ReadWrite, UAV `BUFFER` `R8_UINT` | resources / 7 | 4 | 8 |
| 1 | 2 | u1 | Image2D ReadWrite | resources / 8 | 8 | 9 |
| 2 | 3 | t0 | Image2D ReadOnly | resources / 0 | 12 | 1 |
| 3 | 4 | t1 | Image2D ReadOnly | resources / 1 | 16 | 2 |
| 4 | 5 | t2 | Image2D ReadOnly | resources / 2 | 20 | 3 |
| 5 | 6 | t3 | Image2D ReadOnly | resources / 3 | 24 | 4 |
| 6 | 7 | t4 | Image2D ReadOnly | resources / 4 | 28 | 5 |
| 7 | 8 | t5 | Image2D ReadOnly | resources / 5 | 32 | 6 |
| 8 | 9 | t6 | Image2D ReadOnly | resources / 6 | 36 | 7 |
| 9 | 10 | t7 | BufferSurface ReadWrite, SRV `BUFFER` 2,112 B | resources / 9 | 40 | 10 |
| 10 | 11 | t8 | BufferSurface ReadWrite, SRV `BUFFER` 128 B | resources / 10 | 44 | 11 |
| 11 | 12 | s0 | sampler | sampler heap / 0 | 48 | none |

The slot is relative to the heap this path uses. `t7`/`t8` stay SRV ranges despite their ReadWrite
SPIR-V type; the destination image is arg 1/u1/BTI 9, and the `7` in the `0,0,7` store mask enables
`.xyz`. BTI and push 52/base 4 come from the old `ze_info` (see the BTI table in
[xmx412-toolchain.md](xmx412-toolchain.md)); the reviewed 4.1.2 profile uses the same base 4, push
52 and 11 surfaces ([shim-bridge.md](shim-bridge.md)), but this page does not re-derive its per-arg
BTIs (open, 2026-11-22).

## Descriptors the normal path materializes

Old build; the 4.1.2 helper differs (below).

- Arg 0 gets an `R8_UINT` `BUFFER` UAV, `FirstElement=0`, `NumElements=resource.Width`, in heap slot
  7 (`0x180017184..0x1800171ff`, `Format=0x3e` at `0x1800171c2`), after `GetDesc` (`+0x50`) reports
  `Dimension=1`.
- Args 2..8: seven calls to helper `0x180002df0` at `0x18001711b..0x18001717f`, source indices from
  `[rsp+0x78]`, `[rsp+0x7c]`, `esi`, `[rbp-0x80]`, `[rbp-0x7c]`, `edi`, `ebx`.
- Arg 1: `CopyDescriptorsSimple` at `0x18001727e` into slot 8 from another image descriptor that
  never becomes a view desc here.
- Args 9 and 10: `CreateShaderResourceView` at `0x1800172e1..0x180017367` from `ctx+0xa80` and
  `ctx+0xa98`, `Format=0x3e`, `ViewDimension=1`, mapping `0x1688`, `StructureByteStride=0`,
  `Flags=0`, `NumElements` `0x840` and `0x80`; `0x3e` is also written at `0x1800172fd`.

The public boundary is `ffxCreateContext` `0x180001290`, `ffxDispatch` `0x1800013b0` and `ffxQuery`
`0x180001400`; the wrapper at `0x1800058a1..0x1800058e6` passes the context, the registry and the
D3D12 interface to the PRE. No PE import names `CreateCommittedResource`, `CreateShaderResourceView`
or `CreateUnorderedAccessView`, yet the dump shows these vtable calls, so a missing import does not
mean nothing is allocated. The views carry no format, dimensions or initial bytes; the synthetic
probe (64 values, 1,984 sentinels) validates only itself.

Closing the gap needs an authorized trace in a disposable prefix, correlated by resource and
descriptor ID: each `D3D12_RESOURCE_DESC`, heap properties and allocation size, every view and copy
with its final slot, the identity of slots 0..10, the bytes of args 0, 9 and 10, root-table handles,
sampler descriptor, grid and barriers, before and after the dispatch, without modifying the state.
`tools/reconstruct_pre_resources.py` recovers the static part into
`analysis/pre-resource-descriptors.json`; the dump it reads is `analysis/fsr-xmx-disassembly.txt`,
SHA-256 `4007779c416772def4eecdd20acefb5d52deb6c8d0f0f895473761653f4e66b0`, and
`tests/test_pre_resources.py` checks the copy windows.

## What arg 0 and arg 10 carry

The kernel writes 128 B per group in OWORD units at index `wg_y * 960 + wg_x * 8` (SPIR-V
`:15977-15993`). Under the guards `wg_x < 120` and `wg_y < 540` the exclusive end of the last write
is:

```text
((539 * 960) + (119 * 8) + 8) OWORD * 16 bytes/OWORD
= 518400 * 16
= 8,294,400 bytes
```

The capacity check uses a different register than the dimension check. The factor in `eax` comes
from field `+0x24` of `table[selector - 1]`, stride `0x4f0`, selector in the DWORD `context+0x830`,
or is 1 by default (`0x180016984..0x1800169df`). The gate is `Width >= factor² * 0x7e9000` and
`Width <= 0xffffffff` (`0x180016973..0x180016a0e`). Direct extraction gives `native_1080` selector 1
with factor 1, so the lower bound is 8,294,400 B; the 2160/4320 variants carry factors 2/4. The
check restricts capacity, not the runtime `Width`, and it does not imply RGBA8.

Arg 10 carries a 128 B header. The kernel reads DWORDs at offsets 8..84, address/byte fields at
64..80, flags at byte 100 and a base at byte 104 (SPIR-V `:5190-5325`, `:5573-5602`). Bit `0x400` of
the flags is a guard, and bit `0x2000` selects `base` or `base+16` for a 16 B float4 read from arg 0
(`:5573-5614`, `oword.ld.unaligned` at `:5606-5612`). Here `base` is an offset into arg 0, not a
virtual address. The other header offsets need the caller's ABI before they get a semantic name. Arg
0 also has reads and scratch selected by arg 10, so it is not an empty readback.

## Bridge push layout: the one-slot offset

Reference VKD3D (`upstream/vkd3d-proton`, `ef9a02e873715c9e2da0d6db8a236aca8380b303`) at
`libs/vkd3d/state.c:670-731,891-919` gives 4 bytes to the constant and one DWORD to every table,
samplers included, for 4 + 12*4 = 52 bytes; resources occupy [4,48) and the sampler [48,52).
`libs/vkd3d/command.c:7711-7717,7760-7766` repacks the tables in order into that range.

The ANV patch (`patches/0001-anv-cm-kernel-injection.patch:700-720`) computes
`base = push_size - 4 * nsurf = 52 - 4*11 = 8`, so it reads [8,12,...,48], roots 2..12: `u0` is
skipped and the sampler DWORD is read as a resource table. The correct read is [4,8,...,44], roots
1..11. Under this reference layout and the packer's surface order the offset is a static
incompatibility. The real Proton layout and BTI order are not corroborated at runtime (open,
2026-11-22).

The sampler template sits at RVA `0x72a20`: Filter `0x15` (MIN_MAG_MIP_LINEAR), Address U/V/W `3`
(CLAMP), created at `0x18002cc23..0x18002cc8b` with LOD bias 0, anisotropy 1, comparison ALWAYS,
border 0, MinLOD 0, MaxLOD FLT_MAX. ANV does not consume that dynamic sampler and falls back to
linear/clamp; filter and border match, but ANV uses MaxLOD=14, so this is a partial match, not a
second proven blocker.

The minimal adaptation is proposed, not applied: carry per-kernel metadata for where the surface
table starts and its order instead of moving all XeSS kernels to base 4; for this PRE expect base 4
and eleven surfaces and exclude the sampler DWORD; keep resource-heap slot selection separate from
sampler handling; keep the full CM blob with its footer; fix the GPU information that
`CreateDeviceExtensionContext`/`Context1` do not copy to the caller. Copying the DLL is not enough.

## Stock name table: the same 10

| name | wide count 4.1.2 | wide count old | ascii 4.1.2 | ascii old |
|---|---|---|---|---|
| `MLSR_Optimized_Constants` | 2 | 2 | 2 | 2 |
| `ScratchBuffer` | 3 | 3 | 51 | 48 |
| `rw_reprojected_color` | 2 | 2 | 0 | 0 |
| `r_history_color` | 2 | 2 | 0 | 0 |
| `r_velocity` | 2 | 2 | 1 | 1 |
| `r_input_color` | 2 | 2 | 1 | 1 |
| `r_recurrent_0` | 2 | 2 | 0 | 0 |
| `r_depth` | 2 | 2 | 0 | 0 |
| `r_input_exposure` | 2 | 2 | 2 | 2 |
| `r_auto_exposure_texture` | 2 | 2 | 2 | 2 |

The first wide cluster (table) is at offsets `0x3101e8..0x310410` (RVAs `0x3115e8..0x311810`); the
second cluster is scattered (`0x31b444..0x31d4a4`); the third, an isolated `ScratchBuffer`, is at
`0x320e32` (RVA `0x322232`). Same layout as the old one (`0x67a08..0x67c30`, `0x71a44..0x73620`,
`0x77082`). Selection rules by table `+0x8efc` and the `depth/exposure/auto-exposure` substitutions
are preserved (sequence `movslq …; mov %…; cmovne …` at `0x252b7..0x2538c`, same as the old one).
Only change: 3 extra ascii `ScratchBuffer` strings (48→51) from new passes; the rest is identical.

## Fail-stops: exact strings and counts

All ASCII, 1 occurrence each (same as the old one):

- `[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.` (off `0x3101a0`, RVA
  `0x3115a0`)
- `[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.` (off `0x3102f0`, RVA
  `0x3116f0`)
- `[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.` (off `0x310340`, RVA
  `0x311740`)
- `[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.` (off `0x310390`, RVA
  `0x311790`)
- `[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.` (off `0x310440`, RVA
  `0x311840`)
- `PRE runtime geometry is unavailable.` (off `0x310490`, RVA `0x311890`, direct NUL; the rest
  LF+NUL)
- `[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.` (off `0x30f280`, RVA
  `0x310680`)

Gates verified in disassembly:

- params: `0x24e2e/0x24e3e/0x24e4c` (`0xa94/0xa80/0xa88`), same.
- bindings: `test %eax/%ecx/%ebx/%edx/%r8d/%r9d; je …` in `0x25303..0x2532f`, same.
- constants: `test %rax; je` + `cmp $0x20,(%rcx)` in `0x250e9..0x250f5`, same (`<0x20`).
- ABI: `mov 0x64(%rax),%ecx; and $0xffff0000,%eax; cmp $0x50580000` in `0x250fb..0x25109`, same
  (`consts+100`, high `0x5058`).
- ScratchBuffer: `GetDesc` (`*0x50`), `Dimension==1`, `Width >= factor²*0x7e9000`,
  `Width <= 0xffffffff` in `0x253b7..0x2544f` (`imul $0x7e9000`), same.

Requested anchors, already present in the old one (retained, not new):

- `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB physical heap slots retained.`
  (off `0x30f660`, RVA `0x310a60`, count 1 in both; ref at `0x4174b`).
- `[FSR4 XMX] Failed to load PRE CM-SPIRV; XMX fail-stop will trigger.` (off `0x30f400`, RVA
  `0x310800`, count 1 in both; refs at `0x40f2e/0x41016/0x42786`).

## Copy helper: it is not the same

Old: `0x180002df0`, 164 B, 1 block: `GetCPUDescriptorHandleForHeapStart(heap en ctx+0x1b40)` + 1
descriptor via `CopyDescriptorsSimple` (device `+0xC0`).

4.1.2 in the PRE:

- `0x18000bbd0`, 198 B (`[0xbbd0,0xbc96)`): index translator
  (`movslq (%rdx),%r14; shl $6; add 0x4920…; shl $5…; …; call 0x274a0…`), called ~9 times with
  `r8d = 2/4` and `rdx = 0x48/0x58/0x74/0x78/0x7c(%rsp)…` (at `0x25632..0x256ee`), plus later calls
  for `0x44/0x70`. It does not use `ctx+0x1b40`.
- `0x180027bc0`, 57 B (`[0x27bc0,0x27bf9)`): barrier (`call *0xD0(%rax)` + `movl $0,0x4910(%rbx)`),
  called before the copies (at `0x256fe`, `0x26340`…).
- `ctx+0x1b40` appears only 1 time in the whole DLL (at `0x2a71e`, dispatcher `0x2a670` with offsets
  `0x100/0xa00/0x1200/0x1a00/0x1a40/0x1b40`), outside the PRE. The PRE heap now comes from
  `0x38f0/0xa78/0x4920/0x4910/0x3910…` (see `0x25d…/0x25e…`).

Conclusion: helper rewritten and split (barrier + translator); signature and heap differ. Do not
reuse the 164 B one.

## Vtables verified against the pinned LLVM-MinGW headers

Pinned headers (hashes equal to the old ones):

- `d3d12.h` SHA-256 `23935395fe8939ac0ca71c5b34cd7b21a689ff5e9641846563613f24bc0dd85e`,
  `dxgiformat.h` `8a4e770d3022aff667b7d4f03f0cf5a068ecde87f357c9791f275954c1461c48`, both under
  `artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/generic-w64-mingw32/include/`.
- Compile-time `static_assert` (toolchain clang) in the test: `CreateSRV==0x90`, `CreateUAV==0x98`,
  `CopyDescriptorsSimple==0xC0`, `GetCPUDescriptorHandleForHeapStart==0x48`,
  `GetGPUDescriptorHandleForHeapStart==0x50`, `GetDesc==0x50`, `Dispatch==0x70`,
  `ResourceBarrier==0xD0`, `SetDescriptorHeaps==0xE0`, `SetPipelineState==0xC8`,
  `SetComputeRootDescriptorTable==0xF8`, `SetComputeRoot32BitConstant==0x108`, plus `R8_UINT==0x3e`,
  `BUFFER==1`, `0x1688`, offsets of `D3D12_*_DESC`.

Raw opcodes in the PRE range `0x24e00..0x2666a` (pinned counts):

| pattern | slot | count 4.1.2 | count old |
|---|---|---|---|
| `FF 50 48` | heap `+0x48` | 2 | 2 |
| `FF 50 50` | resource `+0x50` GetDesc | 4 | 4 |
| `FF 50 58` | GPU heap `+0x58` | 1 | 1 |
| `FF 50 70` | command list `+0x70` Dispatch | 2 | 2 |
| `FF 50 78` | `+0x78` | 9 | 8 |
| `FF 90 90 00 00 00` | device `+0x90` CreateSRV | 2 | 2 |
| `FF 90 C0 00 00 00` | device `+0xC0` CopyDescriptorsSimple | 1 | 1 |
| `FF 90 C8 00 00 00` | `+0xC8` SetPipelineState | 1 | 1 |
| `FF 90 D0 00 00 00` | `+0xD0` ResourceBarrier | 12 | 12 |
| `FF 90 E0 00 00 00` | `+0xE0` SetDescriptorHeaps | 1 | 1 |
| `FF 90 E8 00 00 00` | `+0xE8` | 1 | 1 |
| `FF 90 F8 00 00 00` | `+0xF8` SetComputeRootDescriptorTable | 3 | 3 |
| `FF 90 08 01 00 00` | `+0x108` SetComputeRoot32BitConstant | 1 | 1 |
| `FF 90 A8 01 00 00` | `+0x1A8` | 7 | 7 |

`CreateUAV (+0x98)` does not appear as `FF 90 98…` but is loaded into `r10`
(`mov 0x98(%rdx),%r10; call *%r10` at `0x25d04` and `0x25ddd`), same as the old one (`0x171f3`).
`GetDesc`, `SetComputeRoot32BitConstant(0,0,0)` → `b0=0`, `NumElements=0x840/0x80`,
`ComponentMapping=0x1688`, `Format=0x3e (R8_UINT)`, states `0x40/0x400/0x800` preserved. Single
difference: an extra `*0x78` at `0x255b4` (9 vs 8).

## Payload audit: macl and acc0

The 4.1.2 IGA (2390 lines, `analysis/offline-pre-412/disasm/.text.fsr4_pre_xmx.asm`, sha
`7773a88b…`) adds one `mul acc0` that feeds a `macl` near the 32 B seed in `r2` (seed at line 11):

```text
L6024:                                                            // 441
(W)     mul (1|M0)               acc0.0<1>:d   r82.14<0;1,0>:d   r80.2<0;1,0>:uw  // 442
        shl (1|M0)               r1.1<1>:d     r80.0<0;1,0>:d    3:w               {Compacted}  // 443
        macl (1|M0)              r1.0<1>:d     r82.14<0;1,0>:d   r80.1<0;1,0>:d   {Compacted}  // 444
```

`macl` is unconditional and writes only `r1.0` (GRF bytes 64..67) from `r82.14` (bytes 5304..5307)
and `r80.1` (bytes 5124..5127), plus an implicit `acc0.0` read. IGC's `createMach/createMacl`
(commit `66d1f97ea95492de78c400af9dba65a0b637460f`) leaves `AccWrCtrl` clear and always reads
`acc0.0`; IGA `RegDeps.cpp` marks `MACL/MACH` as implicit `acc` writers as an over-approximation,
and the audit keeps that as a no-kill so `taint` cannot be cleared unsoundly. Mesa wires `MACL` on
Xe2 as opcode 83, 2 sources and 1 destination (commit `73701c305e9ddc4087a3f68a372193a841cebed9`).
The instruction has no `send`, no indirect addressing (`r[`/`a0.` absent in the kernel) and no
explicit operand in `r2.0..r2.7` (GRF bytes 128..159); the payload offsets under analysis are 0..31
and `{Compacted}` changes nothing.

The kernel has 253 lines with `acc0` (old 252), 179 explicit group-0 writes, 218 explicit group-0
reads and 9 implicit group-0 reads (8 `mac` at lines 2328-2354 plus 1 `macl` at 444); `mach` does
not appear. The flow-sensitive audit unions taint at joins, lets `sel` replace it and reaches a
fixed point on backedges: 160 instructions visited, 0 reads, overwrites at lines 20 (0..1), 23
(2..3), 143 (4..15), 179 (4..31) and 379 (4..31), identical to the old build. `macl` (idx 415) never
has live bytes, and every raw `acc` write that reads `r2` runs after `grf_live` is empty, so
`acc_live` stays empty. A tainted `acc2` does not contaminate group 0; `acc0`→`acc1` does.

Verdict: no read before overwrite or end, under a full and constant mask and 64 B GRFs.
`profiles/fsr4-pre-412-native1080-payload-audit.json` moved to `static-analysis-only` /
`unread-before-overwrite-or-end` (was `static-analysis-blocked`) and keeps `runtime_approved=false`;
`build_report` still rejects on the old pins, the intended fail-closed check. `mach` and unknown
opcodes stay rejected. This covers one kernel and authorizes no runtime; the audit runs with
`python3 -m unittest tests.test_xmx412_payload_macl tests.test_pre_payload_audit -v`.

## CM envelopes

A CM block ends with a footer that declares its own length, so the SPIR-V end does not have to be
guessed by walking instructions:

```text
SPIR-V [N bytes]
string A, NUL-terminated
string B, NUL-terminated
u64 little-endian: N
u64 little-endian: full footer size
11 bytes: "-vc-payload"
```

Pack 40101 carries `-vc-payload` and a 70-byte footer, 40102 carries
`-vc-payload -Xfinalizer '-noDPASMacro'` and 97 bytes, and 40103 mixes both. The second string is
always ` -target-features=+ocl_runtime`; its leading space and the quotes of the first are part of
the bytes. `tools/parse_cm_payloads.py` checks magic, bounds and both strings and recovers 252 + 252
+ 186 = 690 blocks; the layout and the inventory are in
[xmx412-pack-envelope.md](xmx412-pack-envelope.md). The six
POST modules the old carver missed came from reading `-vc-payload` as an instruction (word
`0x2d63762d`, false count 11619).

The length is copied untrimmed: pack 40101 is IR 329008 + footer 70 = 329078, pack 40102 is IR
330108 + 97 = 330205, and all 18 variants of both packs match `IR + footer`. Table evidence: RVA
`0x56160`, stride `0x4f0`, PRE at `+0xd8`, offset `+8`, length `+0x10`; alternative table RVA
`0x613b0`, stride `0xf0`, offset `+0`, length `+8`. The PRE function `0x18002bb60..0x18002d447`
builds the INTC descriptor at `0x18002c8cf..0x18002c914` with pointer `+8`, length `+16`,
`ShaderInputType=2` (CM_SPIRV) at `+24` and `CompileOptions`/`InternalOptions` NULL at `+32`/`+40`;
`CreateComputePipelineState` is called at `0x18002cb00`. The shim persists all of
`CS.BytecodeLength` in DynKernelId (`shim/src/dll/D3D12Api.cpp:43-81`).

Pack selection runs through `0x1800329d0`, which queries OPTIONS2 and writes `+0x834` from
`SIMD16Required` and the query result (`0x180032d07..29`); `FSR4_XMX_DPAS` can replace it, and a
non-null flag selects 40102, the Xe2 pack. Loader `0x18001a450` maps selectors 0/1/2 to RCDATA
40101/40102/40103. Packs come from xess-xmx-linux revisions
`ef39559d26e083ce1bd1353b2e8c86f33c3c264c` and `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`.

## SPIR-V census: old 4.0.2x against 4.1.2

Old: `analysis/fsr-resources/resource-0001.raw` (23,164,789 B, SHA-256 `8b520078…9ecec39d24`), 252
envelopes, documented PRE `analysis/fsr-resources/xe2-first.spvasm` (16,014 lines, SHA-256
`7ed1d81b…7968db6a9e`), IR 330,108 B, `ir_sha256 1d10c34e…2bd44a2`. New: pack
`analysis/fsr-xmx-412/pack-40102.raw` (23,682,325 B, SHA-256 `d88aa9d6…995e491`), 252 envelopes,
record 0 with IR 358,776 B, `ir_sha256 49e069fd…21f9f568` and
`envelope_sha256 ce372719…faac8f34bf0b34aa5b85ab`; its 17,444-line disassembly (SHA-256
`7ac12fd2…19dd9d46a2`, `spirv-dis` from SPIRV-Tools 2026.4) stays transient in `/tmp/opencode`.

Both packs hold 18 PRE variants at step 14 (indices
`[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`); inside a pack all PREs share
`ir_size` and differ in `ir_sha256` (18/18).

| Aspect | old `xe2-first` | new pack 40102 record 0 |
|---|---|---|
| Entry | 1 `Kernel %10259 "fsr4_pre_xmx" %__spirv_BuiltInWorkgroupId` | 1 `Kernel %11173 …`, same name and interface |
| Args | 12: `%587,%591,%595×7,%587,%587,%599` | 12: `%770,%774,%778×7,%770,%770,%782` |
| Types | `BufferSurfaceINTEL ReadWrite`, `Image 2D Unknown ReadWrite`, `Image 2D Unknown ReadOnly ×7`, `Sampler` | identical, type ids renumbered |
| BuiltIns | `WorkgroupId` only, 2 `OpLoad v3ulong` | same, loads `%4100`/`%4104` against `%3698`/`%3702` |
| ExecutionModes | `ContractionOff`, `SubgroupSize 1`, `SharedLocalMemorySizeINTEL 0`, `NamedBarrierCountINTEL 0` | same four |
| `LocalSize` | absent | absent |
| Guards | `OpUGreaterThanEqual` against `120` and `540`, lines 5177/5183 | same pattern, lines 5838/5844 |
| Variant cycle | `120×540, 240×1080, 480×2160`, 6 each | same order, 6 each |
| `OpFunctionCall` | `3d_load 78`, `3d_sample 85`, `typed_quad_store 1` | same three counts |
| Store | `llvm.genx.lsc.store.quad.typed.bti.v16i1.v16i32.v48f32`, 10 operands `(pred,i8,i8,i8,i32 surface,u,v,r,lod,data)`, `(0,0,7,…)`, surface from arg 1 | same signature, arity and `(0,0,7,…)` |
| Module | 330,108 B, `Bound 10274`, SPIR-V 1.1, `Khronos LLVM/SPIR-V Translator;14`, 13 caps, `SPV_INTEL_vector_compute`+`SPV_KHR_no_integer_wrap_decoration`, `Physical64 OpenCL` | 358,776 B (+28,668), `Bound 11188`, same version, generator, caps and extensions |
| Trailer | 97 B, two strings | 97 B, two strings |

The `7` is the `.xyz` channel enable, not a BTI or surface. The old store surface `%9780` (`:15312`)
keeps its chain `%9780←%3391←%9774←%3397←%9769←%3460←%3749←%3656←%1687`, the new one `%10694` (call
`%10703`) keeps `%10694←%3782←%10688←%3788←%10683←%3851←%4151←%4058←%1920`, and both stay bound to
arg 1 Image2D ReadWrite (inner `%605…%616` and `%788…%799`, outer `%11174…%11185` in order), so
t6/BTI 7 is not the destination. Totals differ in `OpFunctionCall` (1,403 old against 1,509 new) and
`oword_st_*` (2, `v4f32` and `v128i8`, against 4, `v4f32`, `v8i32`, `v4i32` and `v128i8`). The 128 B
header pattern survives in both (`%uint_128`, `Aligned 128`, `oword_ld_unaligned_v32i32` and
`oword_ld_v32i32`, branches `%uint_3/7/9`) and infers no layout. Counts are syntactic calls, not
pixels or accesses, and `Unknown` in `OpTypeImage` is not a Vulkan format.
`tests/test_xmx412_spirv.py` (21 tests) pins the pack, the 18 indices, `ir_size` 358,776, the record
0 SHAs, 18 distinct `ir_sha256`, the guard cycle `[(120,540),(240,1080),(480,2160)]×6` and the
counts 78/85/1.

## Local size and mask gate: undetermined

The analysis does not determine the required local size of `fsr4_pre_xmx` (open, 2026-11-22). Treat
it as a gate; `1×1×1`, `SubgroupSize 1` and the packer's workgroup selector are not substitutes.

| Quantity | Pinned evidence | Conclusion |
|---|---|---|
| Required local size (X,Y,Z) | full `.ze_info`, reviewed IR | no local-size attribute found; not established |
| Compiler SIMD size | `execution_env.simd_size: 1` | the field is 1; not a local dimension |
| Instruction lanes | pinned IGA disassembly | `simd16` operations appear; does not fix the workgroup |
| Threadcount and driver dispatch | nothing pinned, no observed PRE dispatch | unknown |
| Vulkan workgroup selector | packer placeholder | `1,1,1` is not a shader contract or grid |
| Grid | guards `WorkgroupId.x >= 120`, `y >= 540` (IR SHA-256 `7ed1d81b…7968db6a9e`) | `120×540×1` is a minimal candidate from bounds, not the host's grid |

The six-byte `packed_local_ids`, `simd_size: 1`, the IGA instruction widths and the physical thread
count are different quantities, and no demonstrated conversion between them yields the local
dimensions.

One driver configuration follows from the local Mesa tree, and it is not a PRE requirement.
`build/mesa-26.1.2/src/intel/vulkan/anv_shader_compile.c:1725-1734` turns `lws` into
`cs->local_size = (32*lws.x, lws.y, lws.z)` with `prog_mask = 1 << 2`, so `lws=(1,1,1)` becomes
`(32,1,1)`. `src/intel/compiler/brw/brw_shader.cpp:993-1027` gives SIMD32, 32-lane groups, one
thread and `right_mask=0xffffffff`, and `src/intel/vulkan/genX_cmd_compute.c:638-647` passes
`ExecutionMask = dispatch.right_mask` to the Xe2 `COMPUTE_WALKER`; the old `GPGPU_WALKER` lower mask
is not evidence here. That is a conditional configuration of one tree, not proof that `lws=1` is the
contract.

`analysis/pre-payload/report.json` shows the four extra payload fields are unread before overwrite
or end, conditional on a full and constant mask. The profile stays `experimental-offline-only` with
`runtime_approved=false`.

```sh
python tools/inspect_pre_dispatch.py \
  analysis/offline-pre/full/ze_info.yaml \
  analysis/pre-payload/disasm/.text.fsr4_pre_xmx.asm \
  analysis/offline-pre/full/pre_bmg.bin \
  --spirv-assembly analysis/fsr-resources/xe2-first.spvasm
python -m unittest discover -s tests -p test_pre_dispatch.py -v
```

The inspector accepts only the three pinned artifacts and fails on truncation or modification.
`.ze_info` SHA-256 `5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c`, zebin
`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`, IGA
`a9c82bbfccc535959e73ddd6b80fb209ed8a12bf8607927f62078b43b6215660`; with `--spirv-assembly` it pins
the IR text at `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`. Only
`BuiltIn WorkgroupId` appears in the declarations (`:120`), loaded at `:5166,5172`, and the entry
modes carry no `LocalSize`; that does not prove the native payload is unused.

## What the shim must not do

- Do not overwrite a field the game still reads. The kernel writes arg 0 and reads it back through
  arg 10's `base`, and arg 0 also holds scratch selected by arg 10. The 128 B header of arg 10
  belongs to the caller.
- Do not assume a dispatch dimension. The grid comes from `ctx+0x840`/`ctx+0x844`, and the local
  size, thread count and mask are still open (2026-11-22). The BTI table and push base 4 are
  old-build evidence; do not copy the `base 4`/`push 52` numbers onto another PRE without its own
  review ([shim-bridge.md](shim-bridge.md)).
- Do not pin `FSR4_XMX_DPAS` or a variant index to hide a detection failure, and do not rename
  variants from the old census when the 4.1.2 table disagrees.
- Do not pass the trimmed `.spv` where the full `.cmspv` is required, and do not assume the compiler
  reproduces the original request from the trimmed IR.
- Do not invent image formats, channels or scene names, and do not treat ReadWrite in the SPIR-V
  type as a UAV range for `t7`/`t8`.
- Do not use the sampler index to address the resource heap, and do not move every XeSS kernel to
  base 4.
- Do not read `S_OK`, a created PSO or a created view as proof of a correct dispatch.

## Limits

- Static and derived. 51 indirect calls and runtime tables (`+0x8efc`, `0x9608/0x9400`,
  `0x2a30/0x2ab8…`) do not resolve to values: the slots identify the method, not the driver.
- The root signature, descriptor materialization and 52-byte push layout come from the old build.
  The reviewed 4.1.2 profile carries the same base 4, push 52 and 11 surfaces, but nothing here
  confirms that its helper fills the same slots at runtime (open, 2026-11-22).
- No value trace, no initial contents, no local size or mask, no output oracle. None of this
  authorizes a PRE dispatch; only the normal PRE was reconstructed, and the other stages need their
  own analysis.
- Census counts are syntactic and assign no semantics; the payload audit covers one kernel under an
  assumed full mask; IGA and SPIR-V evidence do not validate the driver's behaviour. `S_OK` or a
  created PSO proves nothing.
