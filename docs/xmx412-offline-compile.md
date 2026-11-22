# Offline compilation of PRE 4.1.2 (Xe2, native_1080)

CPU-only. No DLL was executed; no GPU/Wine/driver/prefix/Steam was used.
`artifacts/original` was only read. Offline compilation with the local toolchain
is explicitly allowed (same precedent as
`docs/offline-pre-compilation.md`). No runtime gate: no dispatch,
injection, readback or copy to runtime caches.

## 1. Pinned input

Pack `analysis/fsr-xmx-412/pack-40102.raw`, envelope index 0
(`tools/parse_cm_payloads.py`):

| Field | Value |
|---|---|
| `offset` / `end` | `0` / `358873` |
| `ir_size` / `trailer_size` | `358776` / `97` |
| `ir_sha256` | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| `envelope_sha256` | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| embedded trailer | `-vc-payload -Xfinalizer '-noDPASMacro'` + ` -target-features=+ocl_runtime` |
| content | magic `03 02 23 07`, `fsr4_pre_xmx` in the IR |

Exact slice `data[0:358873]` to `analysis/offline-pre-412/module-0000.cmspv`
(verified against `envelope_sha256`). The `native_1080` variant is assigned by
position inherited from the old census; **not** confirmed against the variant
table of the 4.1.2 DLL (`fadbcb50…`).

Pinned toolchain (`profiles/intel-toolchain.json`): IGC `2.10.10+18926`,
ocloc `25.18.33578.6`, target `0xe20b`. Command (same recipe as
`docs/xmx412-toolchain.md` §2):

```bash
mkdir -p analysis/offline-pre-412/out analysis/compiler-cache
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/offline-pre-412/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412/out" \
  -output pre -options '-vc-codegen'
```

Exit 0, `Build succeeded`; warning about mismatched LLVM triples kept.

## 2. IGC consumes the embedded options (same as the old control)

| Input | zebin SHA-256 | native code SHA-256 | `.misc.buildOptions` |
|---|---|---|---|
| Full, two runs | `b1781bb45a675005a81fb6679ad5f0b02d1252987a0d1f49af38cd4cf13751c2` (identical) | `68b962b5a01984d02b0bbe15bda0c8e3d04dd49ad8a58d93e5c16dbb28f8792c` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` (byte-identical to the old one) |
| Trimmed SPIR-V (`data[0:358776]`) | `ff889fb8a294588e6de85816dfe52c60a3f3bd701ed17ff82ebd39b39f7c2978` | `e941cd977c6ea1b26de76a8460a07bf9c7167f0120a988438210cc3884d57e78` | `-vc-codegen` |

Same BTIs in both outputs; different code. Identifying by kernel/BTIs alone
would be insufficient, as with the old control.

## 3. `ze_info` / BTIs: compiler contract identical to the old one

- `ze_info` byte-identical to the old one (`sha256
  5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c`).
- `execution_env`: `grf_count 128`, `simd_size 1`, `has_dpas true`,
  `has_sample true` (plus `has_fence_for_image_access`,
  `has_no_stateless_write`, `offset_to_skip_per_thread_data_load 128`).
- BTIs by `arg_index 0…10`: `[8,9,1,2,3,4,5,6,7,10,11]`; sampler separate
  (`arg 11`, `sampler_index 0`).
- Non-zero cross-thread payload: `arg0@8`, `arg9@16`, `arg10@24`
  (8 B) + `private_base_stateless@0` (8 B); per-thread `packed_local_ids`
  (6 B). Identical to the old one.
- Embedded IR (`49e069fd…`, 358776 B): entry with 12 parameters in order,
  opaque surfaces 0/9/10 with single use
  `llvm.genx.address.convert.i32.p1intel.buffer_rw_t`, guards
  `WorkgroupId.x >= 120`, `WorkgroupId.y >= 540` (same pattern as the old one).

What changed (expected, the IR went from 330108 to 358776 B):
`code 68b962…` (previously `2e42d33c…`, 30464 B vs 29376 B),
`zebin b1781b…` (previously `3e974d57…`, 395256 B vs 365504 B),
IGA `7773a88b…` (previously `a9c82bbb…`, 2390 lines vs 2310),
`spvasm 7ac12fd2…` (previously `7ed1d81b…`).
Matching the old hashes would have been suspicious, not a success.

## 4. Payload audit: blocked (fail-closed), not safe

`tools/audit_pre_payload.py` (unmodified) rejects the new IGA:

- `build_report`: `Unreviewed CM input` (its old pins intact; correct).
- `parse_isa`: `Unsupported native opcode macl` (line 444 of the ASM:
  `macl (1|M0) r1.0<1>:d r82.14<0;1,0>:d r80.1<0;1,0>:d`,
  preceded by `mul ... acc0...`).

Exact delta vs. the old IGA: a single new `macl` instruction; the rest
parses. The `acc0` flows (252 occurrences) already existed in the old IGA with
an identical pattern, and the auditor treats them the same way (non-GRF) in both binaries.

The profile `profiles/fsr4-pre-412-native1080-payload-audit.json` records
this block (`status static-analysis-blocked`,
`native_byte_liveness.status blocked-unsupported-opcode`,
`possible_reads unknown`), plus the IR evidence that was verified
(surfaces, order, guards, offsets). `runtime_approved false`.
Unclaimed experimental note: treating `macl` as a generic ternary
arithmetic yields 160 visited / zero reads / overwrites at
lines 20/23/143/179/379 (same shape as the old one), but the implicit
semantics of `acc0` in `macl` remain unreviewed: **no `unread` verdict
for 4.1.2**.

For that reason `tools/audit_pre_payload.py` was not touched: the extension would
require modifying an existing file and claiming unreviewed ISA semantics.

## 5. New profile

`profiles/fsr4-pre-412-native1080-bmg.json`
(`experimental-offline-only`): pins `input ce372719…`, `code 68b962…`,
`zebin b1781b…`, `surface_count 11`,
`expected_push_size 52`, `table_pc_base 4`.
Push/base are carried over because the 4.1.2 evidence confirms them mechanically:
same order/BTIs + same `ze_info` → same `pre_layout` derivation
(11 stateful surfaces, separate sampler, offsets 4…44, explicit base 4
instead of the automatic 8). `payload_review` points to the blocked audit, not to
an `unread`.

## 6. Reproduction and tests

```bash
python -m unittest tests.test_xmx412_compile -v
python -m unittest tests.test_xmx412_toolchain -v
```

`tests/test_xmx412_compile.py` (13 tests, CPU only): slice pins,
zebin/code, determinism (identical re-run), trimmed control,
`ze_info`/BTIs/payload/sampler, IR guards, profile equality with the
staging, and fail-closed rejection by the legacy auditor (`Unreviewed CM input`,
`macl`). It skips (rather than falsely passing) if the pack/toolchain/staging are absent.

Staging in `analysis/offline-pre-412/` (ignored by git):
`module-0000.cmspv/.spv`, `out/`, `out-repro/`, `out-stripped/`,
`disasm/`, `embedded.spv/.spvasm`, `metadata/ze_info.yaml`,
`summary.json`.

## 7. Limits

- No dispatch, injection, readback or runtime approval. Do not copy the
  artifact to runtime caches or enable helpers with it.
- `macl`/`acc0` unreviewed; payload audit blocked.
- `native_1080` variant is positional, with no 4.1.2 table; the remaining PREs
  (rows 2–18 of the matrix) and `pass6` are out of scope.
- `grf_count 128` / `simd_size 1` do not generalize to other variants.
