# PRE Xe2 SPIR-V census: old (4.0.2x) vs new (4.1.2)

CPU-only, static. PROHIBITED: running DLLs, GPU/Wine, touching
`artifacts/original`, games or prefixes. No scene semantics (color/depth/motion) are
assigned and no image formats are inferred.

## Sources and method

- Old: Xe2 pack `analysis/fsr-resources/resource-0001.raw`
  (23 164 789 B, SHA-256 `8b520078…9ecec39d24`), 252 CM envelopes.
  Documented PRE `analysis/fsr-resources/xe2-first.spvasm`
  (16 014 lines, SHA-256 `7ed1d81b…7968db6a9e`), IR 330 108 B,
  `ir_sha256 1d10c34e…2bd44a2`. See
  `docs/pre-controlled-test-contract.md:20-119` and `docs/pre-resource-map.md`.
- New: XMX 4.1.2 build DLL `fadbcb50…b37f44732` (8 resources: 6 packs
  + VERSIONINFO + manifest, see `docs/xmx412-pins.md`),
  Xe2 pack `analysis/fsr-xmx-412/pack-40102.raw`
  (23 682 325 B, SHA-256 `d88aa9d6…995e491`), 252 CM envelopes.
  First PRE (record 0): IR 358 776 B,
  `ir_sha256 49e069fd…21f9f568`,
  `envelope_sha256 ce372719…faac8f34bf0b34aa5b85ab`,
  transient disassembly in `/tmp/opencode` (17 444 lines,
  SHA-256 `7ac12fd2…19dd9d46a2`). The `.spvasm` is not added to the repo.
- Parser: `tools/parse_cm_payloads.py` (verified footers, 97 B trailer,
  `"-vc-payload -Xfinalizer '-noDPASMacro'"` +
  `" -target-features=+ocl_runtime"` in both builds).
  Loader pins: `tools/decompress_xmx412.py:EXPECTED[40102]`
  (verified in `tests/test_xmx412_spirv.py`).
- Disassembly: `spirv-dis` SPIRV-Tools 2026.4 (CPU only). Reproduction without writing
  to the repo:

```bash
python3 -c "import sys; sys.path.insert(0,'tools'); import parse_cm_payloads, pathlib; \
data=pathlib.Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes(); \
recs=parse_cm_payloads.parse(data); \
open('/tmp/opencode/new-pre.spv','wb').write(data[recs[0]['offset']:recs[0]['offset']+recs[0]['ir_size']])"
spirv-dis /tmp/opencode/new-pre.spv -o /tmp/opencode/new-pre.spvasm
python3 -m unittest discover -s tests -p test_xmx412_spirv.py -v
```

The PRE block is 18 variants per pack in both builds
(indices `[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`,
step 14). All the PRE IRs of the same pack share `ir_size`
(old 330 108, new 358 776) but have distinct `ir_sha256` (18/18).
The fine census was done on the 120×540 variant (record 0, the one documented
as `xe2-first`); block stability (entry/args/types/BuiltIns/
ExecutionModes/counts/store) was verified in all 18 new ones by
disassembly.

## Side-by-side table (record 0 vs record 0)

| Aspect | Old 4.0.2x (`xe2-first`) | New 4.1.2 (pack 40102 record 0) | Same? |
|---|---|---|---|
| Entry points | 1× `Kernel %10259 "fsr4_pre_xmx" %__spirv_BuiltInWorkgroupId` | 1× `Kernel %11173 "fsr4_pre_xmx" %__spirv_BuiltInWorkgroupId` | Yes (name/iface; only the SSA id changes) |
| Ordered args | 12: `%587,%591,%595×7,%587,%587,%599` (wrapper `%10259`, inner `%fsr4_pre_xmx` `%605…%616` same order) | 12: `%770,%774,%778×7,%770,%770,%782` (wrapper `%11173`, inner `%fsr4_pre_xmx` `%788…%799` same order) | Yes (pattern; only type-id renumbering) |
| Types (`OpType*`) | `%587=BufferSurfaceINTEL ReadWrite`; `%591=Image 2D Unknown ReadWrite`; `%595=Image 2D Unknown ReadOnly`; `%599=Sampler`. Signature `%603=Function %void %587 %591 %595×7 %587 %587 %599` | `%770=BufferSurfaceINTEL ReadWrite`; `%774=Image 2D Unknown ReadWrite`; `%778=Image 2D Unknown ReadOnly`; `%782=Sampler`. Signature `%786=Function %void %770 %774 %778×7 %770 %770 %782` | Yes (permissions/dims/`Unknown` format identical) |
| Arg details | 0 Buffer RW, 1 Image RW, 2–8 Image RO ×7, 9–10 Buffer RW, 11 sampler | 0 Buffer RW, 1 Image RW, 2–8 Image RO ×7, 9–10 Buffer RW, 11 sampler | Yes |
| `OpTypeImage` | `%void 2D 0 0 0 0 Unknown` + `ReadWrite`/`ReadOnly`; 2D, no format inferred | Identical: `%void 2D 0 0 0 0 Unknown` + `ReadWrite`/`ReadOnly` | Yes (do not invent formats) |
| BuiltIns | Only `WorkgroupId` (`OpDecorate … BuiltIn WorkgroupId`, `OpVariable %_ptr_Input_v3ulong Input`, 2× `OpLoad v3ulong`) | Only `WorkgroupId`, same decoration/variable/loads (`%4100/%4104` vs `%3698/%3702`) | Yes |
| ExecutionModes | `%10259 ContractionOff`, `SubgroupSize 1`, `SharedLocalMemorySizeINTEL 0`, `NamedBarrierCountINTEL 0` | `%11173 ContractionOff`, `SubgroupSize 1`, `SharedLocalMemorySizeINTEL 0`, `NamedBarrierCountINTEL 0` | Yes |
| `LocalSize` | Absent | Absent (do not infer local size from `SubgroupSize 1`) | Yes (absent in both) |
| WorkgroupId guards (record 0) | `OpUGreaterThanEqual %bool … %uint_120` + `… %uint_540`, `BranchConditional` to early return (lines 5177/5183; contract 5166–5185). X/Y only; Z not used | `OpUGreaterThanEqual %bool … %uint_120` + `… %uint_540`, same `BranchConditional` pattern (lines 5838/5844 of the transient one). X/Y only; Z not used | Yes for record 0 |
| Block guards | 18 variants cycle `120×540,240×1080,480×2160` (6 each, repeated order) | 18 variants cycle `120×540,240×1080,480×2160` (6 each, same order) | Yes (NOT “same 120×540” for the whole block; only the first one matches) |
| `OpFunctionCall` counts | `3d_load 78`, `3d_sample 85`, `typed_quad_store 1` (same in the 18 old ones sampled) | `3d_load 78`, `3d_sample 85`, `typed_quad_store 1` (same in the 18 new ones, verified by dis) | Yes |
| Store signature | `llvm.genx.lsc.store.quad.typed.bti.v16i1.v16i32.v48f32`, 10 operands `(pred,i8,i8,i8,i32 surface,u,v,r,lod,data)`, `(%uchar_0,%uchar_0,%uchar_7,…)` | Same function and arity 10, same `(0,0,7,…)` | Yes |
| Mask/channels | `7` = `.xyz` channel-enable, not BTI/surface | `7` = `.xyz`, not BTI/surface | Yes |
| Store surface | `%9780` (`:15312` old), chain `%9780←%3391←%9774←%3397←%9769←%3460←%3749←%3656←%1687`, `%1687=address_convert … %606` | `%10694` (call `%10703`), chain `%10694←%3782←%10688←%3788←%10683←%3851←%4151←%4058←%1920`, `%1920=address_convert … %789` | Pattern yes; SSA ids change |
| Store source | arg 1 Image2D RW (`%606` is the 2nd param of inner `%605…%616`; outer passes args in order; zebin BTI 9, IGA `store_quad…bti[9]`) | arg 1 Image2D RW (`%789` is the 2nd param of inner `%788…%799`; outer `%11174…%11185` in order). No new BTI/zebin is claimed | Yes (arg 1; t6/BTI 7 is not the destination) |
| IR / module | 330 108 B, `Bound 10274`, 16 014 lines, SPIR-V 1.1, `Khronos LLVM/SPIR-V Translator;14`, caps 13, ext `SPV_INTEL_vector_compute`+`SPV_KHR_no_integer_wrap_decoration`, `Physical64 OpenCL` | 358 776 B (+28 668), `Bound 11188`, 17 444 lines, same version/generator/caps/ext/memory | Grows; rest identical |
| CM trailer | 97 B, same 2 strings | 97 B, same 2 strings | Yes |

## Additional syntactic differences (informational, no semantics)

- Total `OpFunctionCall`: 1 403 (old record 0) vs 1 509 (new record 0).
- `oword_st_*` calls: 2 (`v4f32`, `v128i8`) vs 4
  (`v4f32`, `v8i32`, `v4i32`, `v128i8`). No meaning is assigned and they are not counted
  as part of the requested census.
- 128 B header pattern preserved syntactically (`%uint_128`,
  `Aligned 128`, `oword_ld_unaligned_v32i32`/`oword_ld_v32i32` + branches
  `%uint_3/7/9`) in both record 0s; no layouts or contents are inferred.

## Limits

- Counts = syntactic `OpFunctionCall` calls, not pixels nor accesses.
- `Unknown` in `OpTypeImage` = do not infer a Vulkan format/channels/space.
- It does not establish local size, runtime dispatch behavior, execution mask, nor a
  functional oracle. `S_OK`/PSO prove nothing.
- The census does not replace the offline compilation/zebin nor the payload audit of the
  new build (see `docs/xmx412-pins.md` REQUIRED-TBD).

## CPU evidence and pins

`tests/test_xmx412_spirv.py` (21 tests, fail-closed): pack size/SHA,
252 envelopes, 18 PRE at fixed indices, `ir_size` 358 776 + strings,
`ir/envelope SHA` of record 0, 18 distinct SHAs, consistency with
`decompress_xmx412.EXPECTED[40102]`, single entry, 12 ordered args,
single `WorkgroupId`, 4 exact ExecutionModes without `LocalSize`, guard cycle
`[(120,540),(240,1080),(480,2160)]×6`, counts 78/85/1 in all 18,
store signature `(pred,0,0,7,surface,u,v,r,lod,data)` with surface `%10694`
from arg 1 (`%789`), plus synthetic fixtures that reject order change,
guards, surface rebinding, mask and op classes.
