# PRE: dispatch and provenance reconstructed with Ghidra 12.2

Static analysis only of the pinned DLL
`3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`.
No execution of the DLL. The disassembly is Ghidra's representation, not the
original source; the `FUN_*` names are synthesized (PDB referenced but not
available). Ideas verified through a second route are marked as such.

Function: `FUN_1800163c0`, range `0x1800163c0..0x180017b6d` (6,062 bytes,
213 blocks, 1,407 instructions). Decompiled signature:
`(contexto, tabla_registro, command_list)`. Sole caller:
`FUN_1800052e0` (site `0x1800058be` within its range), consistent with the xref
of the llvm-objdump dump.

## Fail-stops (ANSI strings, 1 occurrence each in the binary)

| Condition | String |
|---|---|
| `ctx+0xa94==0 \|\| ctx+0xa80==0 \|\| ctx+0xa88==0` | `[FSR4 XMX] PRE params are not ready; XMX fail-stop will trigger.` |
| a stock binding is missing | `[FSR4 XMX] PRE required stock binding missing; XMX fail-stop will trigger.` |
| null constants or size `< 0x20` | `[FSR4 XMX] PRE constants are incomplete; XMX fail-stop will trigger.` |
| upper 16 bits of flags (`consts+100`) `!= 0x5058` | `[FSR4 XMX] PRE runtime-flag ABI mismatch; XMX fail-stop will trigger.` |
| `GetDesc.Dimension != 1` or `Width < factor²·0x7e9000` or `Width > 0xffffffff` | `[FSR4 XMX] PRE ScratchBuffer layout mismatch; XMX fail-stop will trigger.` |
| `ctx==0 \|\| ctx+0x849==0 \|\| w==0 \|\| h==0` | `PRE runtime geometry is unavailable.` (via `FUN_18001dbf0`) |
| parity ring full | `[FSR4 XMX PARITY] Ring full; capture frame skipped without waiting.` |

## Provenance of the images: stock bindings by wide name

The 7 source indices of `t0..t6` are NOT in the DLL: they are looked up by
UTF-16LE name in tables supplied by the caller (`param_2`), and translated via
the `+0x8efc` table into resource indices. Pinned names (2 UTF-16LE occurrences
each: reference + data):

`MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
`r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`,
`r_depth`, `r_input_exposure`, `r_auto_exposure_texture`.

Observed rules: without `r_depth` and with bit 0 of flags set, return 0. With
`flags&0x18==0`, it requires `r_input_exposure` (if bit 2 is clear) or
`r_auto_exposure_texture` (if bit 2 is set). `depth/exposure/auto-exposure`
substitute default sources. The exact slot←name order depends on those runtime
indices: established mechanism, fixed table pending a value trace. This
delimits the "missing external data": these are the host's tables, not a
secret inside the DLL.

## Dispatch geometry (derived, not observed at runtime)

```text
w = *(u32*)(ctx+0x840);  h = *(u32*)(ctx+0x844);
x = (w + 15) >> 4;  x += x & 1;  y = h >> 1;
modo = FUN_18001c9c0();
2,3 → return 1 (sin dispatch PRE); 4 → (1,1,1); 5 → (x,1,1); 6 → (x,0x44,1);
defecto → Dispatch(x, y, 1)  [slot command-list +0x70]
```

For `w=1920, h=1080`: `(120, 540, 1)`, consistent with the IR guards
(`WorkgroupId.x < 120`, `.y < 540`). The `w/h` values are runtime values of the
context; the formula is static. The CM local size and the effective mask
remain separate gates.

## Calls verified against `d3d12.h` (clang, LLVM-MinGW headers)

`ID3D12GraphicsCommandList`: `Dispatch=0x70`, `ResourceBarrier=0xd0`,
`SetDescriptorHeaps=0xe0`, `SetPipelineState=0xc8`,
`SetComputeRootDescriptorTable=0xf8`, `SetComputeRoot32BitConstant=0x108`;
heap `GetCPUDescriptorHandleForHeapStart=0x48`,
`GetGPUDescriptorHandleForHeapStart=0x50`. Device: `CreateSRV=0x90`,
`CreateUAV=0x98`, `CopyDescriptorsSimple=0xc0`; resource `GetDesc=0x50`.

Observed and matching: `SetComputeRoot32BitConstant(0, 0, 0)` → **b0=0**;
11 roots `1..11` from `DAT_180068988` (RVA `0x68988`) and root 12 sampler via
GPU handle; barriers with states `0x40/0x400/0x800`
(`NON_PIXEL_SHADER_RESOURCE`/`COPY_DEST`/`COPY_SOURCE`) around copies; UAV arg0
with `NumElements=Width` after `GetDesc`.

## Helper `FUN_180002df0` (0x180002df0, 164 bytes, 1 block)

```c
GetCPUDescriptorHandleForHeapStart(*(heap en ctx+0x1b40), &h);
h += incremento_origen * indice_origen;
CopyDescriptorsSimple(dispositivo, 1, base_destino + incremento_destino * slot_destino);
```

Confirms: source heap at `ctx+0x1b40`, copy of 1 descriptor. Second caller:
`FUN_180015920` (another dispatch path, outside the normal PRE).

## Limits

Decompiler-derived; 51 indirect calls without target and 3 computed-call sites
remain unknown. The vtable slots identify the method, they do not prove the
driver's runtime behavior. It does not authorize PRE dispatch: initial
contents, local size/mask and the output oracle are missing.
