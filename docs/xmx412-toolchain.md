# XMX 4.1.2 toolchain and offline compile reference

CPU-only. No DLL is executed, no GPU, Wine, driver, prefix or Steam state is
touched, and `artifacts/original` stays read-only. Offline compilation with the
local IGC/ocloc is allowed because it runs on the CPU and dispatches nothing.

This page is the build reference: the pinned compiler, the exact command, the
expected binary and the cache key. Dispatch geometry and the slot map live in
[docs/xmx412-dispatch.md](xmx412-dispatch.md), and model or pack selection in
[docs/xmx412-model-selection.md](xmx412-model-selection.md).

A build shows that the compiler accepts the payload and reports the binding map.
It does not show that the kernel reads an image correctly, because nothing is
dispatched. Both profiles and the CMK3 artifact stay `experimental-offline-only`.

## Toolchain pins

`profiles/intel-toolchain.json` pins the packages:

- IGC `2.10.10+18926`, ocloc `25.18.33578.6` (binary `ocloc-25.18.1`).
- Target `0xe20b` (B580 / Battlemage G21).

| Deb | SHA-256 |
|---|---|
| `artifacts/original/intel-toolchain/igc-core.deb` | `ec3b8e6bb3d6371d3b9963c32ddb1d5315e6b0c3f4ae1d91a7515b5a8907ffe6` |
| `artifacts/original/intel-toolchain/igc-opencl.deb` | `0c631f25cd8394a2f7640f9e35b593cc98ca3fbe922419c5cb20b2281477ef4c` |
| `artifacts/original/intel-toolchain/ocloc.deb` | `c772db8891539890237d50c357af1480b22cbd859c0b8afb5355f605a818d758` |

The packages were extracted without installation: both IGC debs contain
`data.tar.gz`, the ocloc deb contains `data.tar.zst`, and no maintainer script
ran. Layout:

- `artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1`
- `artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu/libocloc.so`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigc.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libiga64.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigdfcl.so.2.10.10+18926`
- `artifacts/extracted/intel-toolchain/igc/usr/local/lib/libopencl-clang2.so.15`

Check the pin without loading the DLL:

```bash
sha256sum artifacts/original/intel-toolchain/*.deb
ls artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 \
   artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu/libocloc.so \
   artifacts/extracted/intel-toolchain/igc/usr/local/lib/libigc.so.2.10.10+18926
python -m unittest tests.test_xmx412_toolchain -v
```

`tests/test_xmx412_toolchain.py` fails closed on any hash or layout drift and
skips only when the ignored local artifacts are absent.

Upstream references: the original shim/ANV is
`ef39559d26e083ce1bd1353b2e8c86f33c3c264c`, the current base of the patch stack
is `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`, and the VKD3D layout is
`ef9a02e873715c9e2da0d6db8a236aca8380b303`.

## Input: envelope 0 of pack 40102

Pack `analysis/fsr-xmx-412/pack-40102.raw` (bucket `18-variant Xe2 (SIMD16
DPAS)`, from commit `7059945`):

- `raw_size 23682325`, `raw_sha256
  d88aa9d67b3b039934927ce6dfea407bed0280370ed9170281533b62d995e491`.
- 252 CM envelopes, all `trailer 97` with the same embedded options.
- 18 PRE (`ir_size 358776`, previously `330108`) + 18 `pass6` (`31824`/`31808`,
  previously `31748`/`31732`); the other 216 envelopes are bit-identical to the
  old census (same `ir_sha256` per index).
- Each IR contains `fsr4_pre_xmx` / `fsr4_pass6_xmx_runtime` depending on family.

PRE `native_1080` is the first envelope of the pack:

| Field | Value |
|---|---|
| Pack | `analysis/fsr-xmx-412/pack-40102.raw` |
| `offset` | `0` |
| `ir_size` | `358776` |
| `trailer_size` | `97` |
| `envelope_size` / `end` | `358873` / `358873` |
| `ir_sha256` | `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` |
| `envelope_sha256` | `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab` |
| `embedded_string_a` | `-vc-payload -Xfinalizer '-noDPASMacro'` |
| `embedded_string_b` | ` -target-features=+ocl_runtime` |
| Content | magic `03 02 23 07` at offset 0, `fsr4_pre_xmx` in the IR |

If `tools/parse_cm_payloads.py` does not return this exact block, the PRE is not
identifiable. Report it and stop; do not compile another index.

Materialize the input without running the DLL. The `.cmspv` includes IR and
footer, so do not use the trimmed `.spv`; the control below shows that the
compiler reads its options from the footer.

```bash
python3 -c "
from pathlib import Path
data = Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes()
blob = data[0:358873]
out = Path('analysis/xmx412-pre-native1080/module-0000.cmspv')
out.parent.mkdir(parents=True, exist_ok=True)
out.write_bytes(blob)
import hashlib
assert hashlib.sha256(blob).hexdigest() == 'ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab'
print('staged', out, len(blob))
"
```

The `native_1080` label comes from the position in the old census
(`pre-reconstruction.json`, variant `index 1`, `pack_40102 offset 0`). The
variant table of the 4.1.2 DLL (`fadbcb50…`) has not confirmed it.

## Compile a kernel offline

Exact command for the 4.1.2 PRE:

```bash
mkdir -p analysis/xmx412-pre-native1080/out analysis/compiler-cache
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/xmx412-pre-native1080/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/xmx412-pre-native1080/out" \
  -output pre -options '-vc-codegen'
```

The first 4.0.2x build used the same command with input
`analysis/cm-payloads-0001/module-0000.cmspv` and output directory
`analysis/offline-pre/full`. Nothing else changed.

Exit 0 prints `Build succeeded`. The warning about mismatched LLVM triples stays
in the log and is never suppressed.

Inspect the result on the CPU:

```bash
python tools/inspect_zebin.py analysis/xmx412-pre-native1080/out/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/xmx412-pre-native1080/summary.json
```

`tools/build_pre_profile.py` rejects this new input by design, because it pins
the old `input 76942f…` / `zebin 3e974d…`. Compare BTIs and `ze_info` by hand
against the table below until a new profile review happens.

## The compiler reads the options from the CM footer

The full build was repeated, and a control was run with the CM footer removed.

| Series | Input | zebin SHA-256 | native code SHA-256 | `.misc.buildOptions` |
|---|---|---|---|---|
| 4.0.2x | Full, two identical runs | `3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2` | `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` |
| 4.0.2x | SPIR-V without footer | (not pinned) | `31418b6e18b394a874ea6dcc2ff667e48f5305f623fb66955ee39862c46d7346` | `-vc-codegen` |
| 4.1.2 | Full, two runs | `b1781bb45a675005a81fb6679ad5f0b02d1252987a0d1f49af38cd4cf13751c2` | `68b962b5a01984d02b0bbe15bda0c8e3d04dd49ad8a58d93e5c16dbb28f8792c` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` |
| 4.1.2 | Trimmed SPIR-V (`data[0:358776]`) | `ff889fb8a294588e6de85816dfe52c60a3f3bd701ed17ff82ebd39b39f7c2978` | `e941cd977c6ea1b26de76a8460a07bf9c7167f0120a988438210cc3884d57e78` | `-vc-codegen` |

For this combination the compiler consumed the options embedded in the CM
footer. They are not decorative text and the helper's external filter does not
remove them. Both outputs of each series share the BTI map and differ in code,
so a kernel name or a BTI map alone cannot identify a build. The profile
generator pins the SHA-256 of the full input (`76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`
for 4.0.2x) and of the reviewed zebin, and it rejects the control without
options.

## Expected content of the binary

BTI is the binding table index inside the GPU code. It is not the root
parameter number and not the relative slot inside the heap. The packer's order by
`arg_index` is what the correspondence requires; it is not yet a trace of GPU
reads.

| Arg | BTI | Root | Register | Push |
|---:|---:|---:|---|---:|
| 0 | 8 | 1 | u0 | 4 |
| 1 | 9 | 2 | u1 | 8 |
| 2 | 1 | 3 | t0 | 12 |
| 3 | 2 | 4 | t1 | 16 |
| 4 | 3 | 5 | t2 | 20 |
| 5 | 4 | 6 | t3 | 24 |
| 6 | 5 | 7 | t4 | 28 |
| 7 | 6 | 8 | t5 | 32 |
| 8 | 7 | 9 | t6 | 36 |
| 9 | 10 | 10 | t7 | 40 |
| 10 | 11 | 11 | t8 | 44 |
| 11 | sampler 0 | 12 | s0 | 48 (separate heap) |

Eleven stateful surfaces plus one sampler. `expected_push_size 52`,
`table_pc_base 4`.

`execution_env` from `profiles/fsr4-pre-native1080-bmg.json` and `ze_info.yaml`:
`grf_count 128`, `simd_size 1`, `has_dpas true`, `has_sample true`,
`has_fence_for_image_access true`, `has_no_stateless_write true`,
`offset_to_skip_per_thread_data_load 128`.

Cross-thread payload: `arg0@8`, `arg9@16`, `arg10@24` (8 B each) plus
`private_base_stateless@0` (8 B), which the packer leaves at zero. Per-thread
payload: `packed_local_ids` size 6. The legacy packer computes 32 bytes
cross-thread and 64 bytes per thread.

The 4.1.2 build keeps the same contract and changes the sizes, because the IR
grew from 330108 to 358776 B:

- `ze_info` is byte-identical to the old one, SHA-256
  `5546d5172c3094110fe25fd34922bcf1d4842fb1b0e97b9a42afc32c2ffe8f7c`.
- `code 68b962…` (previously `2e42d33c…`), 30464 B against 29376 B, the size of
  `.text.fsr4_pre_xmx` in both builds.
- `zebin b1781b…` (previously `3e974d57…`, 395256 B vs 365504 B).
- IGA `7773a88b…` (previously `a9c82bbb…`, 2390 lines vs 2310).
- `spvasm 7ac12fd2…` (previously `7ed1d81b…`).

The new kernel's payload audit is `static-analysis-only` /
`unread-before-overwrite-or-end` (160 visited, 0 reads, overwrites at lines
20/23/143/179/379, `runtime_approved=false`) in
`profiles/fsr4-pre-412-native1080-payload-audit.json`. The `macl` at line 444 and
`acc0` review is in the payload audit section of
[docs/xmx412-dispatch.md](xmx412-dispatch.md);
`tools/audit_pre_payload.py` still rejects the input on its old pins and still
rejects `mach`.

## Minimum compile matrix

Variant order assumed from the old census (`pre-reconstruction.json`
`native_1080 … drs_4320`, `rec_idx = 14k`). Every PRE shares `ir_size 358776`,
envelope `358873` and the same footer. SHA-12 prefixes are a sanity check only;
the full pin of `native_1080` is in the table above and in the test. Recompute
the rest with `tools/parse_cm_payloads.py` before compiling.

| # | Variant (assumed) | `rec_idx` | `offset` | `ir_sha12` | `env_sha12` |
|---|---|---:|---:|---|---|
| 1 | `native_1080` | 0 | 0 | `49e069fd7ad1` | `ce3727191553` |
| 2 | `native_2160` | 14 | 1315712 | `20096eefd6ea` | `ee5553e3d31d` |
| 3 | `native_4320` | 28 | 2631424 | `b4eacd686aa9` | `281e11fc87bb` |
| 4 | `quality_1080` | 42 | 3947072 | `4516209c2f75` | `bc2b0cf3eb0f` |
| 5 | `quality_2160` | 56 | 5262784 | `781497a65e8d` | `c7af3e98a45a` |
| 6 | `quality_4320` | 70 | 6578496 | `530315c68368` | `3414bc91df06` |
| 7 | `balanced_1080` | 84 | 7894144 | `58681903c962` | `a6673041f400` |
| 8 | `balanced_2160` | 98 | 9209856 | `fdd506a063ea` | `0dc3e2dd165d` |
| 9 | `balanced_4320` | 112 | 10525568 | `0d02fd9f232b` | `457c98b43110` |
| 10 | `performance_1080` | 126 | 11841216 | `13d797165e10` | `00239bc0fe38` |
| 11 | `performance_2160` | 140 | 13156928 | `44ddd92c95086` | `5ffb99bbc8c9` |
| 12 | `performance_4320` | 154 | 14472640 | `cc0d724ae018` | `4d6437df94cf` |
| 13 | `ultraperf_1080` | 168 | 15788288 | `9fdea8f98f92` | `4f16b9c138a5` |
| 14 | `ultraperf_2160` | 182 | 17103984 | `6f2805c29197` | `50a9da87b25c` |
| 15 | `ultraperf_4320` | 196 | 18419680 | `ae23ffef499a` | `87a6d240ee8e` |
| 16 | `drs_1080` | 210 | 19735312 | `1692bc855b02` | `e1bb7ba59ae5` |
| 17 | `drs_2160` | 224 | 21051008 | `b289069b36ae` | `436e5cb09cd5` |
| 18 | `drs_4320` | 238 | 22366704 | `c674bc372fe5` | `ed03b05e97c5` |

Phases:

1. Only `native_1080` (row 1): compile, inspect, apply the success criterion
   below.
2. Rest of the PREs (rows 2 to 18): same command per block
   (`data[offset:offset+358873]`), without profiling or caching until row 1
   closes.
3. `pass6` (18 blocks at `rec_idx 6,20,…`, `ir 31824/31808`) is outside this
   matrix; it needs its own census and kernel. The remaining 12 families are not
   recompiled because they are bit-identical to the old build.

If the variant tables of the 4.1.2 DLL (`fadbcb50…`) reorder the PREs relative
to the old census, the `Variant` column is invalid. Do not rename blindly;
report the real table and stop.

## Cache key and profile selection

`profiles/fsr4-pre-native1080-bmg.json` pins one reviewed PRE (native_1080,
B580): input, zebin and code hashes, `table_pc_base = 4`, 11 surfaces and
`expected_push_size = 52` (b0@0, surfaces at 4..44, sampler at 48 on its own
heap). Two gaps remained. Nothing decided which kernel may use the explicit CMK3
layout, and the per-user cache identity (`anv_cm_toolchain_gen`, FNV-1a over the
ocloc and IGC file names plus the packer size) did not include the profile, so a
profile change would not invalidate kernels cached earlier.

### Selection by native code hash

`profiles/registry.json` lists reviewed kernels by native code hash: today
`fsr4_pre_xmx/native_1080` appears twice, as the old `2e42d33c…` and the new
`68b962b5…`. `tools/pre_profile_registry.py` exposes `find_profile(code_sha256)`:
a hit returns the reviewed entry, a miss returns `None` and the kernel keeps the
legacy CMK2 path. The driver never parses the registry; the selection travels
inside the artifact, because a CMK3 file carries `table_pc_base` and the expected
push size and old readers reject its magic. Unknown kernels and every XeSS kernel
behave as before.

### Cache identity

`tools/build_anv_mapping_patch.py` mixes `registry_gen()`, an FNV-1a 32-bit
digest of the canonical registry content, into `anv_cm_toolchain_gen` in both
inner Mesa patches. It moved from `0x912cda6a` with one entry to `0x3ddd809f`
with two. A registry change renames the per-user cache files, so a stale `.cmk`
compiled under an older profile is never reused; a miss takes the legacy CMK2
path and changes nothing globally. The regenerated candidate
`patches/0001-anv-cmk3-explicit-mapping.patch` stays `apply --check` clean
against the pinned checkout and stays CMK2-compatible.

### The CMK3 container

An old reader rejects `CMK3` by its magic, so the new format is never reused
silently. A CMK3 file keeps the 472-byte legacy header and adds 8 bytes before
the code, flags `1` (explicit base) and expected push size `52`; native code
starts at byte 480. The reader keeps its CMK2 behavior and, for CMK3, checks
flags, nsurf, alignment and extension, requires an exact maximum push size of 52
bytes, and uses 64-bit arithmetic to confirm that every DWORD is covered by a
range. It still detects the heap automatically but keeps the explicit base 4
instead of the tail inference that gave 8.

The check runs per file and only for CMK3, so the legacy tail heuristic is
untouched elsewhere. `tests/test_profile_selection.py` runs the extracted C block
against a table: the exact `(4, 52)` reference, split ranges, size mismatch,
uncovered DWORD, out-of-range and garbage indices, empty ranges, mid gaps and
non-registered shapes. It tests coverage, not a fixed base, because the file
carries its own base, and `test_registry_matches_profile_file` cross-checks
`registry.json` against the profile.

### What is not integrated

No helper or runtime reads the registry, no cache is written, and no driver is
built or installed. The reader patch was not compiled inside Mesa and not applied
to an installed driver; it applies to the pinned checkout, the internal Mesa
patches keep valid syntax, and the inserted C block runs on the CPU against
synthetic structures, which is not a build of the rest of the driver. Runtime
integration waits for the Phase 1 trace of the real layout and stays gated on
`experimental-offline-only`.

Regenerate and check, with no installs and no GPU:

```bash
python tools/pre_profile_registry.py 2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux > /tmp/regen.patch
cmp patches/0001-anv-cmk3-explicit-mapping.patch /tmp/regen.patch
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest tests.test_profile_selection -v
```

## Offline success criterion

- `ocloc` exits 0 with `Build succeeded`, and the mismatched-triples warning stays
  in the log.
- Order and BTIs equal the table above: `[8,9,1,2,3,4,5,6,7,10,11]` by
  `arg_index 0…10` plus a separate sampler, push 52, base 4. Any deviation is new
  evidence: record the real `ze_info.yaml` and hashes, do not force the map.
- `code_sha256` and `zebin_sha256` differ from the old pin, because the IR changed
  from `330108` to `358776` B. A match would be suspicious.
- `simd_size 1`, `has_dpas` and `has_sample` are re-checked. A `grf_count` above
  128 or another divergent environment does not generalize to other variants:
  report it per variant.
- No GPU gate exists: no dispatch, injection, readback, runtime approval or copy
  to the runtime cache.

## Reproduction and tests

```bash
python -m unittest tests.test_xmx412_compile -v
python -m unittest tests.test_xmx412_toolchain -v
python3 -c "
import sys; sys.path.insert(0,'tools')
import parse_cm_payloads
from pathlib import Path
recs = parse_cm_payloads.parse(Path('analysis/fsr-xmx-412/pack-40102.raw').read_bytes())
print(len(recs), sum(1 for r in recs if r['ir_size']==358776))
print(recs[0])
"
```

`tests/test_xmx412_compile.py` holds 13 CPU-only tests: slice pins, zebin and
code, determinism (identical re-run), trimmed control,
`ze_info`/BTIs/payload/sampler, IR guards, profile equality with the staging, and
fail-closed rejection by the legacy auditor (`Unreviewed CM input`, `macl`). It
skips when the pack, the toolchain or the staging is absent.

Staging in `analysis/offline-pre-412/` (ignored by git):
`module-0000.cmspv/.spv`, `out/`, `out-repro/`, `out-stripped/`, `disasm/`,
`embedded.spv/.spvasm`, `metadata/ze_info.yaml`, `summary.json`. The embedded IR
(`49e069fd…`, 358776 B) has one entry with 12 parameters in order, opaque
surfaces 0/9/10 with a single use of
`llvm.genx.address.convert.i32.p1intel.buffer_rw_t`, and guards
`WorkgroupId.x >= 120`, `WorkgroupId.y >= 540`, the same pattern as the old one.

`tools/apply_cmk_mapping.py` converts a reviewed local CMK2 into the project's
CMK3 without altering the native code and refuses to overwrite an output.
`tools/build_anv_mapping_patch.py` writes the ANV patch and leaves the checkout
intact. Build outputs stay ignored by git.

## History: the 4.0.2x offline build

The 4.0.2x series was the first offline compile: IGC produced a zebin for the
B580 from the first PRE of pack 40102 (`native_1080`, 330108 B of IR) with
`-options '-vc-codegen'`, exit 0 at 365504 B and `.text.fsr4_pre_xmx` 29376 B.
That build produced the BTI map still in use, the first `native_1080` profile
(`2e42d33c…`, input `76942f…`, zebin `3e974d…`) and the CMK3 prototype with
explicit base 4 and push 52. The 4.1.2 series replaced input, outputs and
profile, and added the registry and the cache identity bump. Everything still
valid from the 4.0.2x run is folded into the sections above.

## Appendix A: 4.1.2 DLL static inventory

Static inspection only, CPU-only, 2026-11-12. The DLL was not executed, and no
GPU, Wine, game or prefix was touched.

### Artifact and method

- `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`
- SHA-256: `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`
- Size: 45,558,272 bytes, PE32+, x86_64 (`machine 0x8664`, `bits 64`), 6 sections.

The old DLL was inventoried in `docs/compatibility.md` and
`analysis/fsr-xmx-static.json`: `3eb08656…ea08eba53`, 25,779,712 bytes.

`tools/inspect_dll_412.py` uses the standard library only. It calls
`tools/inspect_dll.inspect()` without modifying it and adds exports, imports,
resources, VERSIONINFO/manifest and model markers; it never loads the DLL.
Output goes to `analysis/xmx412-static.json`, which git ignores, and
`tests/test_xmx412_inventory.py` pins the result and fails closed. Controls were
`llvm-readobj --coff-imports/--coff-exports/--coff-resources` and the REA tools
`inspect_native_exports`, `inspect_pe_imports` and `inspect_pe_resources` at full
coverage.

```sh
python3 tools/inspect_dll_412.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll --output /tmp/opencode/xmx412.json
python3 -m unittest tests.test_xmx412_inventory -v
```

### Exports

| Name | Ordinal | RVA |
|---|---|---|
| `OptiPluginInit` | 1 | `0x18006fc20` |
| `ffxConfigure` | 2 | `0x180001fc0` |
| `ffxCreateContext` | 3 | `0x180002020` |
| `ffxDestroyContext` | 4 | `0x1800020d0` |
| `ffxDispatch` | 5 | `0x180002140` |
| `ffxQuery` | 6 | `0x1800021a0` |

The old DLL had 5 FFX exports at ordinals 1 to 5. The new one has 6 and adds
`OptiPluginInit` at ordinal 1, which shifts the FFX exports to ordinals 2 to 6.
There are no forwarders, and the local parse matches `llvm-readobj` and REA.

### Imports

17 DLLs, 181 functions, 0 delay imports, imphash
`0c1bdb71ec72f8dcd180853c7323ac13`.

| DLL | Functions | Detail |
|---|---:|---|
| `KERNEL32.dll` | 65 | includes `CreateThread`, `GetTickCount64`, `LoadResource/LockResource/SizeofResource/FindResourceW`, `LoadLibraryW/ExW`, `GetProcAddress` |
| `USER32.dll` | 1 | `MessageBoxA` (new against the old DLL) |
| `dxgi.dll` | 1 | only `CreateDXGIFactory2` |
| `d3d12.dll` | 1 | only `D3D12SerializeRootSignature` |
| `MSVCP140.dll` | 24 | STL, locale, mutex |
| `Cabinet.dll` | 3 | ordinals 40/43/45, no names |
| `bcrypt.dll` | 1 | only `BCryptHash` |
| `VCRUNTIME140_1.dll` | 1 | `__CxxFrameHandler4` |
| `VCRUNTIME140.dll` | 16 | `memcpy/memmove/memset/memcmp`, exceptions |
| `api-ms-win-crt-*.dll` (8) | 69 | stdio, heap, string, runtime, convert, math, environment, locale |

No direct import of `CreateCommittedResource`, `CreateShader/Descriptor` or
`CopyDescriptors*` exists; the DLL creates resources and views through the host's
D3D12 vtables. `igdext64.dll` is not a static import; the DLL resolves it at
runtime with `LoadLibraryW` and `GetProcAddress` on `%s\%s\igdext64.dll` in
`DriverStore`.
`CreateDeviceExtensionContext2` appears nowhere, in bytes or strings; only
`INTC_D3D12_CreateDeviceExtensionContext`. `CachedBlob` is a string
(`INTC_D3D12_GetCachedBlob`, `_INTC_D3D12_GetCachedBlob`, `PRE stage-2
GetCachedBlob …`) with no static import because it is an igdext export. The ten
INTC names with and without `_` are `CheckFeatureSupport`,
`CreateComputePipelineState`, `CreateDeviceExtensionContext`, `GetCachedBlob` and
`DestroyDeviceExtensionContext`, the same set as the old DLL. The old DLL had 16
DLLs, 167 functions and 0 delay imports; the new one adds `USER32.dll` with
`MessageBoxA` and about 14 functions such as `CreateThread`, `GetTickCount64`,
`atoi/atof`, `log2f/exp2` and `wcstombs_s` to `wcsstr`.

### PE resources

8 resources out of 19 examined entries. The local parse and
`tools/decompress_xmx412.py` `EXPECTED` agree with REA.

| Type | Name | Bytes | SHA-256 |
|---:|---:|---:|---|
| 10 | 40101 | 6107632 | `8e260219…454e9b9b5` |
| 10 | 40102 | 3856836 | `58557640…3501134d7651` |
| 10 | 40103 | 6960934 | `48963849…901f929f458` |
| 10 | 40104 | 8031050 | `2c93c489…326d9d25fa1` |
| 10 | 40105 | 3421152 | `4cff7b12…6f9e90acb2f` |
| 10 | 40106 | 1001522 | `579f610f…038862d20b0de` |
| 16 | 1 | 776 | `20ba4d46…5e78bd072` |
| 24 | 2 | 145 | `d2952e57…dfd68bde04` |

Resource 16/1 is VERSIONINFO: `CompanyName Advanced Micro Devices, Inc.`,
`FileDescription AMD FidelityFX Upscaler Library (FSR 4 and DLSS on Intel XMX)`,
`FileVersion 4.0.2.1`, `ProductName AMD FidelityFX Upscaler (Intel XMX build)`,
`ProductVersion 4.0.2.1`, `LegalCopyright Copyright (C) 2025-2026`. Resource 24/2
is a minimal manifest of 145 bytes with only `assembly` and
`manifestVersion='1.0'`. The old DLL had 5 resources (40101 to 40103, 16/1 and
24/2); the new one adds 40104 to 40106 for DLSS K / E-F / MX.

### Version and model markers

The DLL carries `4.0.2X` in 8 strings (`4.0.2X`, `4.0.2X ASkip/Hybrid/QSkip/Skip`
and combinations) and `4.1.2X` in 2 (`4.1.2X`, `4.1.2X Lite`), plus `FSR 4.1.2
Lite (DG2)`. Lite and INT8 markers are `FSR4_XMX_LITE`, `FSR4_XMX_INT8`,
`Lite/INT8 model requested without verified fsr-original.dll weights`,
`fsr-original.dll` and `embedded Lite XMX resource pack is missing or invalid`.
DG2 and Xe2 markers are `18-variant DG2 (SIMD8 DPAS)`, `18-variant Xe2 (SIMD16
DPAS)`, `DG2 SIMD8-DPAS`, `Xe2/Xe3 SIMD16-DPAS`, `DLSS K (DG2 + Xe2/Xe3)` and
`DLSS-MX (DG2)`. About 87 DLSS markers exist (`DLSS K/E/F/MX/LX/EX/FX`,
`nvngx_dlss.dll`, `FFX_DLSSK/M_*_XMX`, profiles, `DlssLdrTest`), and
`OptiPluginInit` appears once. `4.20.0` appears in 27 strings with
`requested=4.20.0`. Passes 1 to 12 carry `Failed to load/create/serialize`,
`hybrid enabled`, `full-fusion enabled`, `fused-all host mode` and
`baseDispatch 120x540x1 / 60x270x1 / 30x135x2 / 30x135x1`;
`pass13_params.bin` appears with no pass 13 messages. 32 DIAG strings cover
`PRE extension context`, `root signature FNV1a64`,
`SPIR-V bytes/magic/manifestSHA256`, `2160-vs-1080` and `PRE PROFILE`, plus the
ABI line `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler;
ZB physical heap slots retained`, `Stock fallback is disabled; diagnostic magenta`
and `DriverStore`. Model selection detail is in
[docs/xmx412-model-selection.md](xmx412-model-selection.md).

### Corroboration

REA agrees with these tables: exports `ev_d1cea06b…0906e` (6/6), imports
`ev_a1f49e0e…93cb13` (17/181/0) and resources `ev_544cdced…4e19432` (8/8), each
equal to the local parse and to `llvm-readobj` or `decompress_xmx412.EXPECTED`.
REA here has no disassembler (Ghidra, Hopper, IDA and Kuna are not configured)
and no `analyze_function`, pseudocode or CFG, which does not invalidate the PE
inventory.

## Appendix B: limits

- Presence of a string or an import does not prove execution, API requirements,
  Linux compatibility or GPU correctness. No execution, no network, no new
  disassembly.
- `native_1080` is positional, with no 4.1.2 variant table. The remaining PREs
  (rows 2 to 18), `pass6` and the other kernels are out of scope, and
  `grf_count 128` with `simd_size 1` does not generalize to other variants.
- Local dimensions 1x1x1 used when packing are provisional, SIMD1 does not prove
  them, and the sampler still uses the driver's fallback instead of the real
  dynamic descriptor. The payload audit covers one kernel, one input and one
  output under a full and constant mask.
- Runtime items stay open: the Proton version layout, the GPU information
  returned from the context, the Phase 1 trace, the output oracle, the DIAG check
  `rootParameters==13` and the mask gate.
- `tools/inspect_dll.py` stays intact with its 6 original keys; the extended
  inventory lives in `tools/inspect_dll_412.py`.
