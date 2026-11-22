# PRE native_1080: required initial contents and independent oracle (Phase 2, CPU-only)

Status: spec closed on CPU. No GPU, DLL, game or prefix was run.
It does not authorize PRE dispatch. Everything marked `TRACE_FASE1_REQUIRED` can
only come from the Phase 1 trace (disposable prefix, same `native_1080` path).

Pinned by `tools/inspect_pre_initial_contents.py` + `tests/test_pre_initial_contents.py`:

```bash
python tools/inspect_pre_initial_contents.py analysis/fsr-resources/xe2-first.spvasm
python -m unittest discover -s tests -p test_pre_initial_contents.py -v
```

Pinned hashes: DLL `3eb086566ccc9c24392d98fc83ad0ea54520b87008d1aa1d26aa1c9ea08eba53`,
textual SPIR-V `7ed1d81b8127e9dbb1e0c5befa621060cf7ab47cd82f98f789099b7968db6a9e`,
zebin `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`.

## (a) Table of required content per resource

Legend: STATIC = demonstrated without running anything; `TRACE_FASE1_REQUIRED` =
only the caller's trace can pin it. No formats or scene semantics are invented:
t0…t6 are never named color/depth/motion.

| Resource | Format / permissions | Size | Initial bytes | Valid deterministic values | Provenance |
|---|---|---|---|---|---|
| arg0 u0 (root 1, BTI 8, heap slot 7, push 4) | `BufferSurfaceINTEL ReadWrite`; UAV view `BUFFER R8_UINT`, `FirstElement 0`, `NumElements = Width`. DLL guard: `Dimension == BUFFER (1)`, `factor²·0x7e9000 <= Width <= 0xffffffff`; native_1080 factor 1 → **minimum 8,294,400 B** | runtime Width (≥ 8,294,400 B) | Trace: input/scratch regions + write plane. Do not initialize as an empty readback | Any byte `0x00…0xFF` is valid for `R8_UINT`; the real scene bytes come from the trace | STATIC view; Width and bytes `TRACE_FASE1_REQUIRED` |
| arg1 u1 (root 2, BTI 9, heap slot 8, push 8) | `Image 2D ReadWrite`, `OpTypeImage … Unknown`. Descriptor copied (`CopyDescriptorsSimple` at `0x18001727e`); destination of the typed quad store (mask `7` = channels `.xyz`, surface `%9780` from arg 1) | `TRACE_FASE1_REQUIRED` (full `D3D12_RESOURCE_DESC` + `UAV desc`) | Pre-dispatch trace | No definable filler before knowing format/dims/mip/sample | Binding STATIC; format/dims/content `TRACE_FASE1_REQUIRED` |
| arg2…8 t0…t6 (roots 3…9, BTI 1…7, heap slots 0…6, push 12…36) | `Image 2D ReadOnly`, `Unknown`. Seven copies via helper `0x180002df0` with runtime source indices | `TRACE_FASE1_REQUIRED` per image | Pre-dispatch trace | Must be in the range of the traced format; format still unknown → no filler fixed here | Stock pool of 10 names STATIC (list below); slot←name assignment and format/dims/content `TRACE_FASE1_REQUIRED` |
| arg9 t7 (root 10, BTI 10, heap slot 9, push 40; resource `ctx+0xa80`) | CM `BufferSurface ReadWrite`; D3D SRV `BUFFER R8_UINT`, `FirstElement 0`, `NumElements 0x840`, mapping `0x1688` | Visible window **2,112 B**; backing allocation from trace | Trace | Any valid `R8_UINT` byte; real trace bytes | Extension STATIC; backing and bytes `TRACE_FASE1_REQUIRED` |
| arg10 t8 (root 11, BTI 11, heap slot 10, push 44; resource `ctx+0xa98`) | CM `BufferSurface ReadWrite`; D3D SRV `BUFFER R8_UINT`, `NumElements 0x80`, mapping `0x1688` | **128 B** header, fully visible | Trace: 128 B intact, flags and base preserved verbatim | No invented header; see flag/base rules below | Extension STATIC; content `TRACE_FASE1_REQUIRED` |
| arg11 s0 (root 12, sampler heap 0, push 48) | Sampler MIN/MAG/MIP linear, CLAMP U/V/W, bias 0, maxAniso 1, `ALWAYS`, `MinLOD 0`, `MaxLOD FLT_MAX` | n/a (state) | n/a | State pinned; the ANV fallback partially matches and is not equivalent | STATIC; sampling behavior pending traced formats/coords |
| b0 (root 0) | Constant of 1 DWORD, space 0 | 4 B | `0` (`SetComputeRoot32BitConstant(0,0,0)` at `0x1800173e0`) | Fixed to zero; not a dimensions field | STATIC |

Grid and constants: `w=1920,h=1080 → (120,540,1)` is a candidate derived from
the guards (`WorkgroupId.x < 120`, `y < 540`); local size and runtime mask
remain open (see `docs/pre-dispatch-dimensions.md`). `b0 = 0` always.

### Relation of byte 104 to the OWORD plane of arg0 and the 128 B header (arg10)

Pinned IR (`analysis/fsr-resources/xe2-first.spvasm`):

- The 128 B header is loaded from arg10 (`:5213`/`5220`, aligned/unaligned
  variants depending on branch `3/7/9`, with no semantics assigned to that branch).
- Observed fields used, without semantic names: floats at DWORD offsets
  8–44, 56, 60, 84; integers/addresses at 64–80; flags at byte 100; **base
  (u32) at byte 104** (`:5190-5325`).
- Flag bit `0x400` (`:5225-5227`): if set, early exit via `:1685` with no work.
  A productive dispatch requires it clear, but the trace value decides: if it
  comes set, the expected result is an early exit.
- Bit `0x2000` (`:5593-5602`): selects between `base` and `base+16` for a 16 B
  float4 read from arg0 (`:5606-5612`, variants `:5627`/:5634).
  On this path `base` is a **byte offset relative to arg0**, not a VA.
- Bit `0x200` (`:15970-15973`): if set, early exit without the final store.
  Bit `0x1000` (`:5574-5583`) and field `(flags & 0x18) >> 3`
  (`:5325-5328`) are observed selectors with no semantics assigned.
- Write plane: OWORD index `wg_y·960 + wg_x·8` (`:15977-15993`),
  exclusive end `518400 OWORD = 8.294.400 B` with full 120×540 grid.

Acceptance rules (without inventing values):

1. The trace keeps the 128 B of arg10 verbatim; flags and base are the traced ones.
2. `[base, base+32)` (covers both selections `base`/`base+16` + the 16 B
   read) must fit within the traced `Width` of arg0.
3. The trace must locate the read window `[base, base+32)` and the OWORD write
   plane, and demonstrate there is no destructive alias (read-before-write or
   documented disjoint regions).
4. If `0x400` or `0x200` come set in the trace, the expected result is the
   corresponding early exit, not an image.

### Depth/exposure substitution rules (without expanding them)

From `docs/pre-dispatch-ghidra.md:38-44`, verbatim and without assigning t_i to a scene:
without `r_depth` and with bit0 of the flags, return 0. With `flags&0x18==0`,
`r_input_exposure` (bit2 clear) or `r_auto_exposure_texture` (bit2 set) is required.
`depth/exposure/auto-exposure` substitute the default sources. The exact
slot←name order comes from runtime tables (`+0x8efc`) and the caller's indices:
the mechanism is established, the fixed table is pending the value trace.

Pinned stock pool (UTF-16LE pairs in the DLL, runtime assignment):
`MLSR_Optimized_Constants`, `ScratchBuffer`, `rw_reprojected_color`,
`r_history_color`, `r_velocity`, `r_input_color`, `r_recurrent_0`, `r_depth`,
`r_input_exposure`, `r_auto_exposure_texture`.

## (b) Independent oracle, in order

The synthetic probes (DPAS and image/sampler,
`docs/first-synthetic-gpu-result.md`, `docs/first-image-gpu-result.md`) only
validate their own kernels: 1,408 values and 64 samples + sentinels. **They do
not validate the PRE** nor its typed views, and they are not an oracle.

1. **Range 1 — capture on a reference that works.** Same DLL/input/zebin,
   `native_1080`, 1920×1080, constants `MLSR_Optimized_Constants`, resolution
   of the 10 stock names, on an implementation already validated as correct
   (`S_OK`/overlay/magenta is not enough). It must record, correlated by
   ID/descriptor with roots/slots: `D3D12_RESOURCE_DESC` + heap + size/offset
   per resource; each `CreateSRV/UAV` and `CopyDescriptors*` with format,
   mip/layer/range and final slot; identity of slots 0–10 right before the
   dispatch; the 128 B header of arg10 + arg0 bytes in `[base, base+32)`;
   root-table handles, heap bases/increments, sampler, `Dispatch` grid,
   states/transitions; pre **and** post dumps with canaries; executable/
   versions/hashes; original capture preserved. A bridge capture that still
   fails is evidence of inputs, never an oracle
   (`docs/pre-reference-options.md:8-17`).
2. **Range 2 — CPU validated against Range 1.** A CPU reimplementation that
   reproduces Range 1 byte/bit within justified tolerances on at least one
   fixed input, before it is used. Translating isolated shader operations
   without that validation is not an oracle
   (`docs/pre-reference-options.md:10-12`).
3. **Range 3 — L0/OCL contrast only as bindings.** Same zebin via Level
   Zero or OpenCL, identical inputs, byte comparison. It shares the kernel and
   possibly the compiler core (NEO), so it only contrasts the bindings/backend
   ABI, and never proves FSR correctness
   (`docs/pre-reference-options.md:19-33,42-51`).

Tolerances (justified per format, none invented):

- `R8_UINT` buffers (arg0/9/10 as seen): **tolerance 0, bit-exact**.
  `DXGI_FORMAT_R8_UINT` is an 8-bit unsigned integer; typed views and OWORD
  accesses are bit-exact, with no rounding or filtering on this path.
  One differing byte = failure.
- Images (`Unknown`): **no tolerance fixed until the trace.** After fixing the
  DXGI/Vulkan format: integers → 0; UNORM/SNORM/SRGB → the quantization step of
  the format's spec; FLOAT → IEEE-754 rounding of the traced sequence. No
  epsilon is pre-chosen here.
- **NaN = failure.** Any NaN in a compared region (or finite-reference vs
  NaN-test) is a functional failure: `NaN != todo` (NaN is not equal to anything, not even itself); finite
  scene inputs must not produce NaN. Inf = failure unless the Range 1 reference
  contains it in the same element.

## (c) CPU tests and acceptance gates

`tools/inspect_pre_initial_contents.py` pins the static plan (header offsets,
flag bits, OWORD plane, guards, mask 7) with the IR hash, exposes
`resource_table()` (12 rows, unknowns as `TRACE_FASE1_REQUIRED`),
`oracle_policy()` (order 1>2>3, R8=0, images TBD, NaN=failure) and
`validate_trace_candidate()` (lists missing Phase 1 items and rejects invented
`scene_role` keys). `tests/test_pre_initial_contents.py` (15 tests)
pins all of that with fixtures plus the pinned module; it contains no scene data.

Phase 2 acceptance gates (all must pass; none authorizes GPU on its own):

- G0 Pinned hashes (DLL, IR, zebin) and CPU suite green.
- G1 Phase 1 trace complete: `validate_trace_candidate()` empty (formats,
  dims, views, arg0 `Width`, 128 B header + `[base, base+32)`, grid, local
  size/mask with launcher evidence).
- G2 Initial contents pinned per the table; header/flags/base verbatim;
  no read/write alias on arg0 demonstrated; `b0=0`; sampler pinned.
- G3 Local size, dispatch threadcount/mode and effective mask tested with
  runtime evidence (never `1×1×1`, `simd_size` or SIMD16 widths as a substitute).
- G4 Range 1 oracle captured with the full checklist; Range 2 validated before
  use; Range 3 labeled only as a bindings contrast.
- G5 Comparison with format tolerances (R8 bit-exact, images per the traced
  format), NaN=failure, canaries/guard regions intact, no reads/writes out of range.
- G6 No GPU in Phase 2; Phase 1 and later in a disposable prefix, without touching
  the real Steam/prefix, drivers or services (AGENTS.md).
