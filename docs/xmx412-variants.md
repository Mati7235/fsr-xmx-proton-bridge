# XMX 4.1.2: 18 Xe2 PRE variants (pack 40102)

CPU-only, static. PROHIBITED: running DLLs, GPU/Wine, touching
`artifacts/original`, games or prefixes. No scene semantics
(color/depth/motion) are assigned, and image formats are not inferred.

## Sources and method

- Xe2 pack `analysis/fsr-xmx-412/pack-40102.raw` (23 682 325 B, SHA-256
  `d88aa9d6…995e491`), 252 CM envelopes, parser `tools/parse_cm_payloads.py`
  (footers verified, trailer 97 B, `"-vc-payload -Xfinalizer '-noDPASMacro'"` +
  `" -target-features=+ocl_runtime"`).
- The 18 PREs are the envelopes with `fsr4_pre_xmx` in the IR, at CM indices
  `[0,14,28,42,56,70,84,98,112,126,140,154,168,182,196,210,224,238]`
  (step 14). All share `ir_size 358776`, `trailer 97`,
  `envelope 358873`, the same two strings, `entry %11173 "fsr4_pre_xmx"`,
  12 ordered args, a single `WorkgroupId`, 4 ExecutionModes without `LocalSize`,
  counts `78/85/1` and store `typed_quad_bti (0,0,7)` with surface `%10694`
  from arg 1. See `tests/test_xmx412_variants.py` (16 tests, fail-closed)
  and `docs/xmx412-spirv-census.md` for the fine-grained census of record 0.
- Disassembly: `spirv-dis` SPIRV-Tools 2026.4 (CPU only) on each exact slice
  `data[offset:offset+358776]`.
- Offline compilation: pinned toolchain `profiles/intel-toolchain.json`
  (IGC `2.10.10+18926`, ocloc `25.18.33578.6`), target `0xe20b` (B580),
  `-options '-vc-codegen'`, in `analysis/offline-pre-412-variants/`
  (ignored; do not use `analysis/offline-pre-412/`, which belongs to another agent running in parallel).
  The 18 compile with exit 0 (`Build succeeded` + warning about mismatched triples
  kept, not suppressed).
- Variant order assumed from the old census
  (`analysis/pre-reconstruction.json` `native_1080 … drs_4320`,
  `rec_idx = 14*k`, `index = k+1`). The variant table of the new DLL
  (`fadbcb50…`) is not re-parsed here: the `Variante` column is invalidated
  if that DLL reorders the PREs relative to the old census (report, do not rename
  blindly). The hypothesis holds structurally (see § Confirmation).

## Full table (confirmed)

`grid` = guards `WorkgroupId.x/y` (`OpUGreaterThanEqual %uint_X/Y`, a single
occurrence each, X/Y only; Z is not used). `factor` = cycle `[1,2,4]×6` inherited
from the old census (`test_pre_resources.py:96`, `table_dword_at_0x24`) and
correlated with suffix/grid; `min Width = factor²·0x7e9000` (old DLL;
formula retained, not re-derived from the new DLL). `IR` always 358 776 B.

| # | Variant (assumed) | `rec_idx` | `offset` | grid guards | factor / min Width | `ir_sha256` | `envelope_sha256` | zebin / code (offline `0xe20b`) |
|---:|---|---|---:|---|---|---|---|---|
| 1 | `native_1080` | 0 | 0 | 120×540 | 1 / 8 294 400 | `49e069fd…21f9f568` | `ce372719…b85ab` | `b1781bb4…13751c2` / `68b962b5…28f8792c` |
| 2 | `native_2160` | 14 | 1315712 | 240×1080 | 2 / 33 177 600 | `20096eef…83d7ebb29` | `ee5553e3…027597` | `6a8f0fe6…bca2e6` / `ba7f966a…697b87` |
| 3 | `native_4320` | 28 | 2631424 | 480×2160 | 4 / 132 710 400 | `b4eacd68…0efc5e` | `281e11fc…efe616` | `dede3aed…7a62fa` / `0ad99755…1930f09` |
| 4 | `quality_1080` | 42 | 3947072 | 120×540 | 1 / 8 294 400 | `4516209c…7979722` | `bc2b0cf3…13a558` | `35fe9a6e…6999f4` / `88ccb2ff…05426a` |
| 5 | `quality_2160` | 56 | 5262784 | 240×1080 | 2 / 33 177 600 | `781497a6…83a7e35` | `c7af3e98…fa66` | `05e99861…0eeed` / `cce6dbab…7fadb` |
| 6 | `quality_4320` | 70 | 6578496 | 480×2160 | 4 / 132 710 400 | `530315c6…0940950` | `3414bc91…2333d4` | `1d747d50…a043d8` / `a5ba59b0…8d55` |
| 7 | `balanced_1080` | 84 | 7894144 | 120×540 | 1 / 8 294 400 | `58681903…a394a1f3` | `a6673041…a84a1` | `4fe17d55…e4275` / `46c43ce5…323638` |
| 8 | `balanced_2160` | 98 | 9209856 | 240×1080 | 2 / 33 177 600 | `fdd506a0…cffe9f` | `0dc3e2dd…f12d` | `096a231f…fac5c` / `83e1bc5c…aaf29` |
| 9 | `balanced_4320` | 112 | 10525568 | 480×2160 | 4 / 132 710 400 | `0d02fd9f…6be9c8` | `457c98b4…08da` | `5921d268…17718` / `ec826861…e1630` |
| 10 | `performance_1080` | 126 | 11841216 | 120×540 | 1 / 8 294 400 | `13d79716…21b7d2` | `00239bc0…a954e` | `2580f661…5cd89` / `5daf0d65…34c4b65` |
| 11 | `performance_2160` | 140 | 13156928 | 240×1080 | 2 / 33 177 600 | `44ddd92c…937aa4` | `5ffb99bb…10ddf` | `f4d93730…4632a` / `0bb8b07d…03599` |
| 12 | `performance_4320` | 154 | 14472640 | 480×2160 | 4 / 132 710 400 | `cc0d724a…64d313` | `4d6437df…2414` | `250ddd1a…832d` / `1437b715…60d6` |
| 13 | `ultraperf_1080` | 168 | 15788288 | 120×540 | 1 / 8 294 400 | `9fdea8f9…4386f` | `4f16b9c1…9c1b` | `e7640611…3176` / `67ad3899…48d81` |
| 14 | `ultraperf_2160` | 182 | 17103984 | 240×1080 | 2 / 33 177 600 | `6f2805c2…81ad4` | `50a9da87…8aaa3` | `cb80102b…30b6` / `679b9162…ad584` |
| 15 | `ultraperf_4320` | 196 | 18419680 | 480×2160 | 4 / 132 710 400 | `ae23ffef…ebf3f8` | `87a6d240…3634e` | `503f1269…26f7` / `46c84cb9…e7af65` |
| 16 | `drs_1080` | 210 | 19735312 | 120×540 | 1 / 8 294 400 | `1692bc85…964f64` | `e1bb7ba5…63c6` | `e481a5f8…4c2e5` / `04268212…1c68` |
| 17 | `drs_2160` | 224 | 21051008 | 240×1080 | 2 / 33 177 600 | `b289069b…694cd` | `436e5cb0…3440` | `243f845f…b535` / `5a589d02…680a` |
| 18 | `drs_4320` | 238 | 22366704 | 480×2160 | 4 / 132 710 400 | `c674bc37…eb27` | `ed03b05e…d05e` | `4c7b2796…83cd` / `b3c63d8f…52c1` |

Full hashes (64 hex) in `tests/test_xmx412_variants.py: VARIANTS` and
`OFFLINE_BUILDS`. IR/envelope SHAs verified by exact slice + footer;
zebin/code SHAs by `tools/inspect_zebin.py` (`fsr4_pre_xmx`).

## Confirmation of the cycle and factors

- Guard cycle **confirmed** by disassembly of the 18:
  `[(120,540),(240,1080),(480,2160)]×6` in `rec_idx` order (6 of each,
  interleaved, not grouped). Each `_1080` guards `120×540`,
  each `_2160` guards `240×1080`, each `_4320` guards `480×2160`. It matches the census
  (`docs/xmx412-spirv-census.md:63`) and the derived dispatch formula
  (`x=(w+15)>>4; x+=x&1; y=h>>1` → `1920×1080→120×540×1`,
  `docs/xmx412-dispatch.md:64-89`).
- Factors **confirmed as a cycle** `[1,2,4]×6` in the same order (inherited
  from the old census; `pre-reconstruction.json` + `test_pre_resources.py:96`).
  Suffix→factor→grid correlation: `_1080→1→120×540`,
  `_2160→2→240×1080`, `_4320→4→480×2160`. The 4.1.2 DLL table was not re-parsed;
  if that table reorders, the `Variante` column falls (see limits).
- Rest bit-identical to the old census except PRE+pass6 (already pinned in
  `docs/xmx412-toolchain.md:42-54`): the 18 new PREs share `ir_size`
  358 776 (old 330 108) with 18 distinct `ir_sha256`; the other 216
  envelopes are bit-identical by index to the old build.

## Offline compilation (the 18)

Command per variant (input `.cmspv` = IR+footer, never a trimmed `.spv`):

```bash
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/offline-pre-412-variants/module-00-rec0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412-variants/out-00-rec0000" \
  -output pre -options '-vc-codegen'
python tools/inspect_zebin.py analysis/offline-pre-412-variants/out-00-rec0000/pre_bmg.bin \
  --kernel fsr4_pre_xmx
```

Results (all):

- Exit 0, `Build succeeded` on all 18 (warning about mismatched LLVM triples
  kept, same as `docs/offline-pre-compilation.md:29`).
- Same `execution_env` on the 18: `grf_count 128`, `simd_size 1`,
  `has_dpas true`, `has_sample true` (+ `has_fence_for_image_access true`,
  `has_no_stateless_write true`, `offset_to_skip_per_thread_data_load 128`).
- Same BTI order on the 18: `[8,9,1,2,3,4,5,6,7,10,11]` by
  `arg_index 0…10` + separate sampler (same as the old census,
  `docs/xmx412-toolchain.md:158-184`). Any deviation would have been new
  evidence; there was none.
- Same `code_size 30464` on the 18 (old `native_1080`: 29 376).
- `zebin_sha256`/`code_sha256` **differ** on the 18 (expected: the IRs differ in
  guards) and differ from the old pin (`zebin 3e974d…`, `code
  2e42d33c…`); matching would have been suspicious.
- `per_thread`: `packed_local_ids size 6`; cross-thread `arg0@8`, `arg9@16`,
  `arg10@24` (8 B each) + `private_base_stateless@0` (8 B), same as the old one.

## Limits

- Variant names = inherited hypothesis, not proof of the 4.1.2 table.
  Do not rename blindly; do not use for profiling/caching without review.
- `Unknown` in `OpTypeImage` = do not infer Vulkan format/channels/space.
- Counts = syntactic `OpFunctionCall` calls, not pixels or accesses.
- Does not establish local size, runtime dispatch behavior, execution
  mask, or a functional oracle. `S_OK`/PSO prove nothing.
- Offline compilation ≠ GPU correctness. No dispatch, injection, readback or
  runtime approval. Do not copy to the runtime cache or enable helpers.
- `analysis/offline-pre-412-variants/` and `analysis/compiler-cache/` are
  ignored by git; only code, tests and docs are versioned.

## Evidence and reproduction

- `tests/test_xmx412_variants.py` (16 tests): size/SHA of the pack, 252
  envelopes, 18 PREs at fixed indices, full table of offsets/IR/envelope SHAs/
  options, guard/factor cycles + suffix correlation, single entry,
  12 ordered args, single `WorkgroupId`, 4 ExecutionModes without `LocalSize`,
  counts 78/85/1 and store `%10694`/mask 7/origin arg 1 on the 18, BTIs
  `[8,9,1,2,3,4,5,6,7,10,11]` + env + `code_size` + zebin/code SHAs when the
  offline artifacts are present, plus synthetic fixtures that reject
  order change, guards, rebinding, mask, op classes and an extra entry.
- `python -m unittest tests.test_xmx412_variants -v`
- `python -m unittest tests.test_xmx412_spirv -v` (fine-grained census, already green)
