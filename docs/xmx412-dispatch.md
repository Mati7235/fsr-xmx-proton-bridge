# XMX 4.1.2: equivalent PRE dispatch (static, CPU-only)

Static analysis only of the pinned DLL
`fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
(45,558,272 bytes). No execution of the DLL, no GPU/Wine, no touching
`artifacts/original`, games or prefixes. No Ghidra/REA: the REA provider
was unavailable (`GHIDRA_INSTALL_DIR` not set); the evidence comes from PE
parsing with stdlib + `llvm-objdump -d` (disassembly only). The `FUN_*`
names of the old DLL are Ghidra-synthesized; here RVAs `0x…` are used
(VA = `0x180000000` + RVA).

Pinned in `tests/test_xmx412_dispatch.py` (fail-closed).

## DLL and PE

| | old | 4.1.2 |
|---|---|---|
| SHA-256 | `3eb08656…08eba53` | `fadbcb50…37f44732` |
| size | 25,779,712 | 45,558,272 |
| ImageBase | `0x180000000` | `0x180000000` |
| `.text` | vsize `0x52aff` vaddr `0x1000` | vsize `0x7762f` vaddr `0x1000` |
| `.rdata` | vaddr `0x54000` | vaddr `0x79000` |

## Equivalent PRE dispatch: `0x180024e00..0x18002666a`

Logic equivalent to the old `FUN_1800163c0`
(`0x1800163c0..0x180017b6d`, 6,062 B):

- 4.1.2 entry: RVA `0x24e00` (VA `0x180024e00`).
  Prologue with cookie (`mov %rsp,%r11 … sub $0x270,%rsp`) and gate
  `ctx+0xa94==0 || ctx+0xa80==0 || ctx+0xa88==0` → fail-stop
  `PRE params are not ready` (jump to `0x2666a`).
  Logical range `0x24e00..0x2666a` = 6,250 B (+188 B vs old).
- `.pdata` splits it into three entries (same logic, separate unwind):
  `[0x24e00,0x24e5a)` 90 B + `[0x24e5a,0x25147)` 749 B +
  `[0x25163,0x2666a)` 5,383 B (gap `0x25147..0x25163` = epilogue/ret).
  The old one was a single entry.
- Only direct caller: `E8` at RVA `0x8e3a`
  (`e8 c1 bf 01 00` → `0x24e00`) inside the function
  `[0x8a1c,0x99b7)` (3,995 B). Analogous to the old call site `0x1800058be`
  in `FUN_1800052e`. Verified by sweeping all `E8` in `.text`
  (1 single hit).
- The second half contains the 10 stock names, the gates for constants/
  ABI/ScratchBuffer, slot selection via table `+0x8efc`, the
  `GetDesc`/bounds checks, the barriers and the final dispatch.

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

Plus 49 LEAs to the first table (`0x3101e8..0x310410`) spread across
`0x19782..0x25232`, with the PRE cluster at `0x24ea9..0x25232`
(see `test_lea_anchors_point_at_strings`).

## Dispatch geometry (derived, not observed at runtime)

Identical to the old one, byte for byte in intent:

```text
w = *(u32*)(ctx+0x840);  h = *(u32*)(ctx+0x844);
x = (w + 15) >> 4;  x += x & 1;  y = h >> 1;
```

4.1.2 evidence (`llvm-objdump`, VA `0x180…`):

- `0x26094: add $15, %eax` (`83 C0 0F`), `0x26097: shr %edi`
  (`D1 EF`, `y = h>>1`), `0x26099: shr $4, %eax` (`C1 E8 04`).
- `0x2609c: mov %eax, %r15d` (`44 8B F8`),
  `and %r13d, %r15d` (`45 23 FD`), `add %eax, %r15d` (`44 03 F8`).
- `r13d == 1` set at `0x25d55: mov $1, %r13d` (`41 BD 01 00 00 00`)
  with no rewrite up to the grid (verified by grepping `r13` in
  `0x24e5a..0x26700`). Then `x += x&1` uses `r13d` as the immediate `1`,
  same as the old `x += x&1`.
- `ctx+0x849==0`, `w==0`, `h==0` → `PRE runtime geometry…`
  via `0x02d710` (in `0x26062..0x2608e`), same as the old
  (`ctx==0 || ctx+0x849==0 || w==0 || h==0`).

For `w=1920,h=1080`: `(120,540,1)`. The DLL strings confirm it:
`PRE … baseDispatch=120x540x1` (also `60x270x1`, `30x135x1/2` for other
passes, 13 occurrences of `baseDispatch`, same as the old one).

## Modes (equivalent to `FUN_18001c9c0`)

Mode = return value of the function at RVA `0x2bed0`
(pdata `[0x2bed0,0x2bf61)`, 145 B — same size as the old
`FUN_18001c9c0` at `[0x1c9c0,0x1ca51)`, 145 B; relocated).

- Call site: `0x25a3e: E8 8D 64 00 00` → `0x2bed0`,
  result in `0x68(%rsp)`, then `0x25e7e: mov 0x68(%rsp), %esi`.
- `0x25e82: cmp $2, %esi; je 0x2662e` and
  `0x26055: cmp $3, %esi; je 0x2662e` → `2,3 → return 1`
  (`0x2662e: mov $1, %al; jmp …`), no dispatch.
- `0x260a5: cmp $4, %esi; … mov %r13d,%r15d; mov %r13d,%edi`
  → `4 → (1,1,1)` (r13d=1).
- `0x260b2: cmp $5, %esi; … mov %r13d,%edi` → `5 → (x,1,1)`.
- `0x260bc: cmp $6, %esi; mov $0x44,%eax; cmove %eax,%edi`
  → `6 → (x,0x44,1)`.
- Default → `Dispatch(x,y,1)` at `0x26394` and `0x263c9`
  (`FF 50 70` = `call *0x70(%rax)`), with `b0=0` via
  `SetComputeRoot32BitConstant` (`FF 90 08 01 00 00` = `*0x108`).

Identical to what is documented in `docs/pre-dispatch-ghidra.md`.

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

The first wide cluster (table) is at offsets `0x3101e8..0x310410`
(RVAs `0x3115e8..0x311810`); the second cluster is scattered
(`0x31b444..0x31d4a4`); the third, an isolated `ScratchBuffer`, is at
`0x320e32` (RVA `0x322232`). Same layout as the old one
(`0x67a08..0x67c30`, `0x71a44..0x73620`, `0x77082`).
Selection rules by table `+0x8efc` and the
`depth/exposure/auto-exposure` substitutions are preserved (sequence
`movslq …; mov %…; cmovne …` at `0x252b7..0x2538c`, same as the old one).
Only change: 3 extra ascii `ScratchBuffer` strings (48→51) from new
passes; the rest is identical.

## Fail-stops: exact strings and counts

All ASCII, 1 occurrence each (same as the old one):

- `[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.`
  (off `0x3101a0`, RVA `0x3115a0`)
- `[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.`
  (off `0x3102f0`, RVA `0x3116f0`)
- `[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.`
  (off `0x310340`, RVA `0x311740`)
- `[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.`
  (off `0x310390`, RVA `0x311790`)
- `[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.`
  (off `0x310440`, RVA `0x311840`)
- `PRE runtime geometry is unavailable.`
  (off `0x310490`, RVA `0x311890`, direct NUL; the rest LF+NUL)
- `[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.`
  (off `0x30f280`, RVA `0x310680`)

Gates verified in disassembly:

- params: `0x24e2e/0x24e3e/0x24e4c` (`0xa94/0xa80/0xa88`), same.
- bindings: `test %eax/%ecx/%ebx/%edx/%r8d/%r9d; je …` in
  `0x25303..0x2532f`, same.
- constants: `test %rax; je` + `cmp $0x20,(%rcx)` in
  `0x250e9..0x250f5`, same (`<0x20`).
- ABI: `mov 0x64(%rax),%ecx; and $0xffff0000,%eax; cmp $0x50580000`
  in `0x250fb..0x25109`, same (`consts+100`, high `0x5058`).
- ScratchBuffer: `GetDesc` (`*0x50`), `Dimension==1`,
  `Width >= factor²*0x7e9000`, `Width <= 0xffffffff` in
  `0x253b7..0x2544f` (`imul $0x7e9000`), same.

Requested anchors, already present in the old one (retained, not new):

- `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB physical heap slots retained.`
  (off `0x30f660`, RVA `0x310a60`, count 1 in both; ref at `0x4174b`).
- `[FSR4 XMX] Failed to load PRE CM-SPIRV; XMX fail-stop will trigger.`
  (off `0x30f400`, RVA `0x310800`, count 1 in both; refs at
  `0x40f2e/0x41016/0x42786`).

## Copy helper: it is not the same

Old: `0x180002df0`, 164 B, 1 block:
`GetCPUDescriptorHandleForHeapStart(heap en ctx+0x1b40)` + 1 descriptor
via `CopyDescriptorsSimple` (device `+0xC0`).

4.1.2 in the PRE:

- `0x18000bbd0`, 198 B (`[0xbbd0,0xbc96)`): index translator
  (`movslq (%rdx),%r14; shl $6; add 0x4920…; shl $5…; …; call 0x274a0…`),
  called ~9 times with `r8d = 2/4` and `rdx = 0x48/0x58/0x74/0x78/0x7c(%rsp)…`
  (at `0x25632..0x256ee`), plus later calls for `0x44/0x70`.
  It does not use `ctx+0x1b40`.
- `0x180027bc0`, 57 B (`[0x27bc0,0x27bf9)`): barrier
  (`call *0xD0(%rax)` + `movl $0,0x4910(%rbx)`), called before the copies
  (at `0x256fe`, `0x26340`…).
- `ctx+0x1b40` appears only 1 time in the whole DLL (at `0x2a71e`,
  dispatcher `0x2a670` with offsets `0x100/0xa00/0x1200/0x1a00/0x1a40/0x1b40`),
  outside the PRE. The PRE heap now comes from
  `0x38f0/0xa78/0x4920/0x4910/0x3910…` (see `0x25d…/0x25e…`).

Conclusion: helper rewritten and split (barrier + translator);
signature and heap differ. Do not reuse the 164 B one.

## Vtables verified against the pinned LLVM-MinGW headers

Pinned headers (hashes equal to the old ones):

- `d3d12.h` SHA-256 `23935395…0dd85e`, `dxgiformat.h` `8a4e770d…461c48`.
- Compile-time `static_assert` (toolchain clang) in the test:
  `CreateSRV==0x90`, `CreateUAV==0x98`, `CopyDescriptorsSimple==0xC0`,
  `GetCPUDescriptorHandleForHeapStart==0x48`,
  `GetGPUDescriptorHandleForHeapStart==0x50`, `GetDesc==0x50`,
  `Dispatch==0x70`, `ResourceBarrier==0xD0`, `SetDescriptorHeaps==0xE0`,
  `SetPipelineState==0xC8`, `SetComputeRootDescriptorTable==0xF8`,
  `SetComputeRoot32BitConstant==0x108`, plus `R8_UINT==0x3e`,
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
(`mov 0x98(%rdx),%r10; call *%r10` at `0x25d04` and `0x25ddd`), same as
the old one (`0x171f3`). `GetDesc`, `SetComputeRoot32BitConstant(0,0,0)`
→ `b0=0`, `NumElements=0x840/0x80`, `ComponentMapping=0x1688`,
`Format=0x3e (R8_UINT)`, states `0x40/0x400/0x800` preserved.

Single difference: an extra `*0x78` at `0x255b4` (9 vs 8). Rest identical.

## What changed vs the old one (summary)

1. Size and layout: 25.7→45.5 MB; `.text` `0x52aff→0x7762f`;
   PRE `0x163c0 (6.062 B, 1 pdata)` → `0x24e00 (6.250 B, 3 pdata)`.
2. Entry and caller relocated: `0x163c0←0x58be (FUN_52e0)`
   → `0x24e00←0x8e3a ([0x8a1c,0x99b7))`; mode `0x1c9c0 (145 B)`
   → `0x2bed0 (145 B)`, same size, same semantics 2..6.
3. Grid and modes identical (including the `r13d=1` trick at `0x25d55`,
   `(x+15)>>4`, `x+=x&1`, `y=h>>1`, `(1,1,1)/(x,1,1)/(x,0x44,1)`).
4. Stock: same 10 names, same wide multiplicities
   (`ScratchBuffer` 3, rest 2); ascii identical except
   `ScratchBuffer` 48→51.
5. Fail-stops: same 7 strings, count 1, same gates
   (params/bindings/`<0x20`/ABI `0x5058`/ScratchBuffer/geometry/parity).
6. `0028ZR` anchors and `Failed to load PRE CM-SPIRV` already existed
   (count 1 in both); retained, not new.
7. Helper: 164 B `0x2df0 (ctx+0x1b40)` → `0xbbd0 (198 B)` +
   `0x27bc0 (57 B)`, heap via `0x38f0/0xa78/0x4920`, different signature.
8. Vtables: same slots and counts, except `+0x78` 8→9.

## Limits

- Static and derived; 51 indirect calls and runtime tables
  (`+0x8efc`, `0x9608/0x9400`, `0x2a30/0x2ab8…`) still do not resolve
  to values. The slots identify the method; they do not prove the driver.
- No Ghidra/REA (provider unavailable); no value trace, initial contents,
  local size/mask or output oracle. It does not authorize PRE dispatch.
