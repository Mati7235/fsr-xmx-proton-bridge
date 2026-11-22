# Offline compilation and first map prototype

## Summary without jargon

The mod's initial recipe **does compile for a B580 with the tool used by
xess-xmx-linux**. We now know the real order the generated code expects.
We also built a prototype that keeps that order and separates the
sampler's slot, instead of guessing by taking the last slots.

We did not run that code on the GPU. The prototype was not installed and
was not connected to Steam. Compiling does not prove that it processes an
image correctly.

## Tools and scope

- IGC `2.10.10+18926`, ocloc `25.18.33578.6` (binary ocloc-25.18.1).
- Official packages downloaded and extracted **without installation** into
  `artifacts/extracted/intel-toolchain/`.
- SHA-256 hashes were checked against the publications; see `profiles/intel-toolchain.json`.
- Explicit target `0xe20b`, identified locally as B580/Battlemage G21.
- The offline compiler was used, without loading the DLL, launching the game or dispatching on the GPU.
- Input: first PRE of the Xe2 40102 pack, variant native_1080, with its full CM footer.
- Original reference upstream shim/ANV: `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`;
  current base of the patch stack: `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`.
- Reference VKD3D layout: `ef9a02e873715c9e2da0d6db8a236aca8380b303`.

## 1. Build and option control

With the full input and `-options '-vc-codegen'`:

- Exit 0, `Build succeeded`; warning about different LLVM triples, kept in the log.
- Zebin: 365504 bytes, `.text.fsr4_pre_xmx`: 29376 bytes.
- GRF count **128**, SIMD size **1**, `has_dpas=true`, `has_sample=true`.
- Cross-thread payload: the legacy packer computes 32 bytes; per-thread: 64 bytes.
- No `grf_count > 128` in this PRE; that does not allow generalizing to other variants.

The full build was repeated, and a control was run with the CM footer removed:

| Input | SHA-256 of native code | Registered build options |
|---|---|---|
| Full, two identical runs | `2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f` | `-vc-codegen  -Xfinalizer '-noDPASMacro'` |
| SPIR-V without footer | `31418b6e18b394a874ea6dcc2ff667e48f5305f623fb66955ee39862c46d7346` | `-vc-codegen` |

**Confirmed for this combination:** the compiler consumes options from the
CM footer; they were not simply decorative text, and they are not removed by
the helper's external filter. Both outputs have the same BTI map but
different code, so identifying them only by kernel name or BTIs would be
insufficient. The profile generator pins both the SHA-256 of the full input
and that of the reviewed zebin, and it rejects the control without options.

SHA-256 of full input:
`76942f6cff52b09ea8fef63adfce8b4119fcd45c8c0586c913eedb9e35fe773b`

SHA-256 of full zebin, reproduced twice:
`3e974d57678d95d0d9fbc2819acc22e5356589018545f53c9086afcccd8e01b2`

## 2. Order confirmed by the compiler

BTI is the internal binding-table index (slot number) that the GPU code uses;
it is not the root parameter number or the relative slot within the heap.

| Arg | Compiler BTI | Expected D3D12 root | Register | Expected push offset |
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
| 11 | —, sampler index 0 | 12 | s0 | 48, separate heap |

There are eleven stateful surfaces and one sampler. The argument types match
the PRE inspected earlier. The packer's order by `arg_index` is what this
correspondence requires; it is not yet a trace of GPU reads.

## 3. Prototype development, without installation

New pieces:

- `tools/inspect_zebin.py`: reads the ELF and the restricted form of `.ze_info`; exact kernel names, without confusing prefixes. It is not a general YAML parser.
- `tools/build_pre_profile.py`: generates a profile for **one reviewed input and one reviewed output**, rejects identity/option changes, and verifies BTIs and the environment.
- `profiles/fsr4-pre-native1080-bmg.json`: evidence and an explicit map per argument.
- `tools/apply_cmk_mapping.py`: converts a reviewed local CMK2 into an **experimental CMK3 format of this project**, without altering the native code.
- `tools/build_anv_mapping_patch.py`: generates a patch for the two upstream ANV patches, keeping the checkout intact.
- `patches/0001-anv-cmk3-explicit-mapping.patch`: generated, reviewable candidate.

The new format does not silently reuse CMK2: an old reader rejects `CMK3`
by its magic. It keeps the 472-byte legacy header and adds 8 bytes before the
code: flags `1` (explicit base) and expected push size `52`.
The native code starts at byte **480**.

The candidate reader:

1. Still reads CMK2 with its previous behavior.
2. For CMK3, checks flags, nsurf, alignment and extension.
3. Requires an exact maximum push size of 52 bytes according to the profile.
4. Uses 64-bit arithmetic to check that every DWORD is covered by a range.
5. Still detects the heap automatically, but **does not replace the explicit base 4**
   with the tail inference that gave 8.

The adapter checks the identity of the native code and the BTIs before it
emits the new header. The sampler is not among the eleven surfaces.

**Important limits:** the reader patch was not compiled inside Mesa and was
not applied to an installed driver. It was checked that it applies to the
pinned checkout and that the internal Mesa patches keep valid syntax. The
inserted C validation block was compiled and run on CPU with synthetic
structures; this is not a build of the rest of the driver. Profile selection
by hash and the cache identity bump are offline candidates
(`profiles/registry.json`, `tools/pre_profile_registry.py`,
`docs/profile-selection-cache-identity.md`); the runtime helper still does not read them.

## 4. What is missing before a GPU test

The compiler reveals details that we must not treat as resolved:

- Stateful buffer args 0, 9 and 10 also have **8-byte** fields at cross-thread offsets **8, 16 and 24**. The upstream packer leaves them at zero.
- `private_base_stateless` occupies **8 bytes at offset 0**; it also stays at zero.
- **Later progress:** the [static payload audit](pre-payload-audit.md)
  finds no reads of the four fields before they are overwritten or the program ends, assuming a full and constant execution mask. No need to initialize them with addresses was identified in this binary; the mask still needs to be validated.
- Local dimensions 1x1x1 used when packing are provisional; SIMD1 does not prove them.
- The sampler still uses the driver's fallback, not the real dynamic descriptor.
- The layout of the Proton version to be used at runtime still needs to be identified.
- Returning GPU information from the context still needs to be fixed/covered.
- Other kernels and variants are not covered by this profile.

 For that reason, the profile and the CMK3 artifact carry the status **experimental-offline-only**.
Do not copy them to a runtime cache. Do not enable the helper with them yet.

## 8. 4.1.2 promotion (current status, no runtime)

The 4.1.2 series closed the gap this document left in §4/§7:

- New profile `profiles/fsr4-pre-412-native1080-bmg.json`
  (`experimental-offline-only`): `input ce372719…`, `code 68b962b5…`,
  `zebin b1781bb4…`, `surface_count 11`, `push 52`, `base 4` (same derivation
  as the old one: same order/BTIs + same `ze_info`).
- Audit `profiles/fsr4-pre-412-native1080-payload-audit.json`:
  `static-analysis-only` / `unread-before-overwrite-or-end`
  (160 visited, 0 reads); see [macl/acc0](xmx412-macl-acc0.md).
  `runtime_approved=false` remains.
- `profiles/registry.json` already has **2 entries** (old `2e42d33c…` +
  new `68b962b5…`). The cache digest `registry_gen()` went from
  `0x912cda6a` (1 entry) to **`0x3ddd809f`** (2 entries), embedded in
  `patches/0001-anv-cmk3-explicit-mapping.patch` (both `anv_cm_toolchain_gen`
  variants). Miss → legacy CMK2 path, with no global change.
- Compilation/audit details in [offline 4.1.2](xmx412-offline-compile.md);
  bridge recheck/regen in [recheck](xmx412-bridge-recheck.md) and
  [regen](xmx412-bridge-regen.md).

What is missing (not runtime): authorized Phase 1 trace (real grid, tables,
DIAG `rootParameters==13`, pre/post bytes), output oracle, mask/
local-size, new helper and 4.1.2 variant table. `profiles/xmx412-pins.json`
remains as staging with `REQUIRED-TBD` (documentation debt, does not block
the registry already promoted). Nothing is copied to runtime caches or installed.

## 5. Reproduction

Download from the URLs and verify the hashes in `profiles/intel-toolchain.json`.
Both IGC debs contain `data.tar.gz`; the ocloc one contains `data.tar.zst`.
Extract only those files; do not run maintainer scripts or install packages.

Example build from the project root, with the extractions present:

```bash
mkdir -p analysis/offline-pre/full
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/cm-payloads-0001/module-0000.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre/full" \
  -output pre -options '-vc-codegen'

python tools/inspect_zebin.py analysis/offline-pre/full/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/offline-pre/full/summary.json
python tools/build_pre_profile.py analysis/cm-payloads-0001/module-0000.cmspv \
  analysis/offline-pre/full/pre_bmg.bin > analysis/offline-pre/profile-reproduced.json

# Packer upstream previamente leído; solo escribe este artefacto local.
CMK_GC=1,1,1 CMK_GRF_BYTES=64 python upstream/xess-xmx-linux/tools/cmk_pack.py \
  analysis/offline-pre/full/pre_bmg.bin fsr4_pre_xmx 1 1 1 \
  analysis/offline-pre/full/pre-legacy.cmk --heap auto --surf auto
python tools/apply_cmk_mapping.py analysis/offline-pre/full/pre-legacy.cmk \
  profiles/fsr4-pre-native1080-bmg.json analysis/offline-pre/full/pre-explicit.cmk3

# Solo comprobar el parche, NO aplicarlo ni instalar drivers.
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest discover -s tests -v
```

The adapter refuses to overwrite outputs. Build artifacts remain ignored by
Git; only code, documentation, patch and metadata are versioned.
