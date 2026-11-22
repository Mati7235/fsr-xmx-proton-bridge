# Shim bridge

The bridge has two halves: a replacement `igdext64.dll` that answers the Intel D3D12 extension calls the FSR DLL makes, and a patched Mesa ANV driver that builds the
mod's CM kernels for the XMX units. Status is `experimental-offline-only`; nothing here installs, touches a prefix or runs a DLL.

## What the bridge does and does not do

The FSR DLL asks for version 4.20.0 and passes `INTCExtensionInfo` (192 bytes in the 64-bit Windows ABI); the shim adapts it to `INTCExtensionInfo1` (200 bytes) and
calls `D3D12ExtensionContext::InitExtensions`, which fills the device information and three driver outputs. `...Context1` takes the same path and `...Context2`
already receives the wider structure. `CheckFeatureSupport` answers from the detected GPU with overrides, and `_INTC_D3D12_GetCachedBlob` returns `E_NOTIMPL`.

The checks cover compilation, ABI layout and CPU harnesses, not a prefix load, driver injection or correct pixels.

## The two fixed bugs

### Context outputs were never copied back (0002)

Both legacy exports received `INTCExtensionInfo`, adapted the requested version into `INTCExtensionInfo1` and passed it to `InitExtensions`, which filled the device
information and three driver outputs. Neither copied any of it back, so a caller got its input structure back unchanged.

`patches/0002-shim-context-output.patch` assigns seven shared device-info fields (including the fixed-size generation-name array) and the three driver outputs one by
one. It never copies the extended structure wholesale or exposes its GMD-only tail. The driver outputs sit eight bytes later in `INTCExtensionInfo1` because
`INTCDeviceInfo1` adds the GMD fields; the base device-info member has a compatible prefix. Copy-back runs only after successful initialization, keeps the
requested-version input and leaves outputs untouched on failure. D3D11 and `...Context2` are not touched. Upstream `8f45d12` now copies the same fields inline, so on
`662dc6e` the candidate only moves them into the shared `CopyExtensionInfo1OutputsToOld` helper that 0003 reuses.

```sh
python tools/build_context_output_patch.py
python -m unittest -v tests.test_context_output
```

`tests/test_context_output.py` checks the source pin, rejects modified source, applies the patch, and compiles a Clang Windows target against the real `igdext.h`
without C++ standard headers or a Windows SDK, asserting the 192/200 byte layouts and offsets. A host executable with `-fshort-wchar`, the real header and the
generated helper and bodies covers version forwarding, output values, the failure path, canaries, an unchanged caller on failure, and a negative control that removes
the copy. The stubs model the initializer; upstream `D3D12ExtensionContext` does not run.

### A reused context returned S_OK with zeroed outputs (0003)

After 0002 both legacy exports still returned early with `S_OK` when the supplied context already had a D3D12 half (`else { // We already seem to have a context
return S_OK; }` in the three D3D12 functions of `shim/src/dll/IgdextApiDll.cpp`). Reuse therefore reported success with a zeroed output structure.

`patches/0003-shim-context-reuse.patch`, stacked after 0002 and built by `tools/build_context_reuse_patch.py` for `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`, applies
this contract per function:

1. Device identity. The stored `m_pAppDevice` must equal `pDevice`, else `E_INVALIDARG`; a live half is never rebound
   and caller outputs stay untouched.
2. Requested version. The request must be supported by the granted version stored at init
   (`INTCExtensionVersionHelper::IsSupported`), else `E_NOINTERFACE`, the code `InitExtensions` uses. A lower request
   succeeds; a higher one fails instead of silently upgrading the half.
3. Refresh. `InitExtensions` re-runs on the live half into a zeroed temporary with the same device, so the rebind is a
   no-op, and the outputs come back. Legacy callers use the 0002 helper; `Context2` takes a full-structure assignment
   because `INTCExtensionInfo1` is already its caller width, GMD tail included. The granted version is saved and
   restored around the refresh; a failed refresh returns the error and leaves caller and half intact.

The patch touches only `shim/src/dll/IgdextApiDll.cpp`, adds no state or header field, and re-derives outputs instead of caching them; `result`, `FAILED`,
`E_INVALIDARG`, `E_NOINTERFACE` and `INTCExtensionVersionHelper` come from `Stdafx.h`. D3D11 halves keep the same early return but write into the caller struct
directly, so they are out of scope. Behavior changes on purpose: compatible reuse fills outputs, incompatible reuse fails, and callers that relied on the silent path
must handle the new errors. Combined `_INTC_CreateDeviceExtensionContext` flows create the half fresh and are unaffected.

`tests/test_context_reuse.py` (5 tests) covers builder determinism, the source and revision pin, `build_full == build∘build_output`, `patch -p1` stacking 0002 then
0003, the 192/200 layout, and host executables of the generated bodies: init, reuse at the same and a lower version, higher-version and foreign-device rejection with
untouched callers, a failed refresh with a surviving half, granted-version stability, and a `Context2` refresh including `GMDID` and `XeCoresCount`. The original
bodies exit `6`. No DLL runs.

## Code layout

`upstream/xess-xmx-linux/` is the driver fork: `shim/` holds the DLL, `common/` has `lowlat_check.h`, and `layer/` holds a parallel CMK2 reader for unpatched ANV.
`patches/0001-anv-cmk3-explicit-mapping.patch` carries the CMK3 reader and cache identity in `anv_cm.c`; 0002 and 0003 carry the context output copy and the reuse
contract. `tools/` holds the generators (`build_context_output_patch.py`, `build_context_reuse_patch.py`, `build_anv_mapping_patch.py`) and the registry validator
`pre_profile_registry.py`. `profiles/` holds the registry, the PRE profiles and the 4.1.2 staging pins, `tests/` the CPU gates, `analysis/` and `artifacts/` the
local reports, packs and original archives, and `build/` the git-ignored cross-build reports.

## Cross-building the shim

The shim is compiled from Linux for Windows x86-64 with LLVM-MinGW, producing a PE32+ AMD64 DLL. This checks compilation and linking only; it does not load the DLL.

- Upstream base `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3` (re-validation 2026-11-13); the historical baseline was
`ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- Toolchain LLVM-MinGW `20261020`, UCRT, Ubuntu 22.04 x86-64, Clang 23.1.4. Archive
`artifacts/original/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64.tar.xz`, SHA-256 `55064b60b991a1e1e8090b8c2f84e82b22cfe5903d12c159d65064cf5e8ae335`, from
<https://github.com/mstorsjo/llvm-mingw/releases/tag/20261020>.
- Extraction with `tarfile` and the `data` filter into `artifacts/extracted/llvm-mingw-20261020-ucrt/`. The archive
stays immutable; toolchain, upstream sources and DLLs are git-ignored.

`upstream/xess-xmx-linux/shim/` was copied to `build/shim-cross-baseline-v01/source/`, leaving the checkout unmodified. The first build failed at `Trace.cpp:62`
because Clang did not recognize `__try`; `-fms-extensions` fixed it and the exception block was neither removed nor replaced.

```sh
TC="$PWD/artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin"
cmake -S build/shim-cross-baseline-v01/source \
  -B build/shim-cross-baseline-v01/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build build/shim-cross-baseline-v01/obj -j 4
```

The 13 objects and the link finished; `llvm-readobj --file-headers --coff-imports` reports PE32+ AMD64. The baseline DLL is 1,615,360 bytes with SHA-256
`43dec833e340cc75ad36d29200e2c5958c6ded8beb1eca5753c7d94d40f92e01`. That hash identifies this run; the build is not declared bit-for-bit reproducible.
`build/shim-cross-baseline-v01/report.json` records source, DLL and import hashes, and `pe-inspection.txt` keeps the inspection.

`build/shim-cross-context-v01/source/` repeated the build with `patches/0002-shim-context-output.patch` applied with `patch -p2`; only `src/dll/IgdextApiDll.cpp`
changed. The patched DLL is 1,615,872 bytes with SHA-256 `c5b5620f5b8dca1fa44ad853e30cae31a6541a779d896c90810802cc4afbde0d`; the patch used has SHA-256
`fa9c302b4cc3cc9ac4fff746c41c17d94a06e879e37f50da60f116f3337d8508`. Its 75 exports, by name and ordinal, and its imported DLLs match the baseline; the claim does not
extend to addresses or the whole PE.

Newer shim sources include `../../../common/lowlat_check.h`, so an isolated copy must carry `common/` next to `shim/`. The 2026-11-13 run copied both to
`/tmp/opencode/xmx662-shim-stack/tree/`, applied 0002 and 0003 from `tree/shim`, and used the same toolchain and flag.

```sh
cp -a upstream/xess-xmx-linux/shim /tmp/opencode/xmx662-shim-stack/tree/shim
cp -a upstream/xess-xmx-linux/common /tmp/opencode/xmx662-shim-stack/tree/common
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0002-shim-context-output.patch"
patch -p2 --batch --forward -d /tmp/opencode/xmx662-shim-stack/tree/shim \
  -i "$PWD/patches/0003-shim-context-reuse.patch"
cmake -S /tmp/opencode/xmx662-shim-stack/tree/shim \
  -B /tmp/opencode/xmx662-shim-stack/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/opencode/xmx662-shim-stack/obj -j 4
```

Result: 14/14 objects plus the link, 0 errors, 0 warnings. `igdext64.dll` is 861,184 bytes with SHA-256
`0a0b54623be219a7a809eb1b628ebfcc4583bff472c097500be840f69bca8cf8`, PE32+ AMD64, 79 named exports, and imports `KERNEL32.dll`, `ADVAPI32.dll` and the UCRT family
`api-ms-win-crt-*`. It is smaller than the `ef39559` baseline because upstream removed the static kernel tables and moved CMK2 packaging to the driver. Patches used:
0002 `fc00a77dd81b9efc6ef3bd61affaa594752c50ebbb27f5a95bad13d39f93f263`, 0003 `ef8112d46f70f6242de9509926a35e66c6fe417a50947adff86c5caf855f054c`. The DLL was not
run; `build/shim-cross-662dc6e/report.json` holds the report, logs and PE inspection.

An earlier stack run on `ef39559` (`/tmp/opencode/xmx412-shim-stack-v01`) also reached 14/14 with a DLL of 1,616,896 bytes, `3aff7abf…3054d1`, 75 named exports and
imports `KERNEL32`/`ADVAPI32`/UCRT with no dynamic `MSVCP`; its sources equalled `/tmp/opencode/shim-cross-reuse-v01/source`. Hashes differ in timestamps and
embedded paths, so the runs agree on shape, not bytes. The UCRT variant statically links the C++ runtime per the upstream CMake but keeps imports of the UCRT APIs.
It is not equivalent to upstream's MSVC distribution with a fully static CRT, and the availability of those imports in a prefix was not checked.

## Regenerating the packs and the patch stack

Three builders produce the stack from the pinned source. A new PRE needs a compiled kernel, a profile, a registry entry and a regenerated 0001. The 2026-11-12 run
used `ef39559`; the 2026-11-13 update repeated it on `662dc6e` and replaced the three versioned patches. No DLL, GPU, Wine, prefix or original archive was touched.

### Builder determinism

The commands write only in `/tmp` and leave the repository untouched:

```sh
python3 tools/build_context_output_patch.py > /tmp/opencode/regen0002.patch
diff -q patches/0002-shim-context-output.patch /tmp/opencode/regen0002.patch
python3 tools/build_context_reuse_patch.py > /tmp/opencode/regen0003.patch
diff -q patches/0003-shim-context-reuse.patch /tmp/opencode/regen0003.patch
python3 tools/build_anv_mapping_patch.py upstream/xess-xmx-linux > /tmp/opencode/regen0001.patch
diff -q patches/0001-anv-cmk3-explicit-mapping.patch /tmp/opencode/regen0001.patch
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0002-shim-context-output.patch"
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0003-shim-context-reuse.patch"
```

| Base | Patch | Determinism | `apply --check` | SHA-256 |
|---|---|---|---|---|
| `ef39559` (2026-11-12) | 0002 | identical | OK | `fa9c302b…7f8508` |
| `ef39559` | 0003 | identical | OK only in order 0002→0003 | `ef8112d4…554f0c` |
| `ef39559` | 0001 | identical | OK | `26383938…c38d70` |
| `662dc6e` (2026-11-13) | 0002 | identical | OK | `fc00a77d…93f263` |
| `662dc6e` | 0003 | identical | OK only in order 0002→0003 | `ef8112d4…554f0c` |
| `662dc6e` | 0001 | identical | OK | `88e134a0…d9f2e4` |

On `662dc6e` the shim source `upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp` has SHA-256 `6d32d934…252696`, the registry has 2 entries with `registry_gen()`
at `3ddd809f`, and the suite reported 415 tests OK with 3 skips. The 2026-11-12 run pinned the shim source at `aed09d4f…80ca96` on `ef39559` and passed 17/17 tests
in `tests/test_xmx412_bridge_regen.py`; `tests/test_profile_selection.py` adds 8 tests, including parametrized C with 10 layouts. The stack also satisfies
`build_full == build∘build_output` on CPU, `patch -p1` applies 0002 then 0003 in an isolated tree with `CopyExtensionInfo1OutputsToOld(*pExtensionInfo,
extensionInfo1)` and three `liveHalf` sites, and the builders reject modified source with `refusing unpinned source`.

The move from `ef39559` to `662dc6e` covered 178 commits and 150 files (+27,845/−6,289 lines; details in git-ignored `analysis/upstream-drift-662dc6e.md`). Commit
`8f45d12` added the output copy upstream. `tools/cmk_pack.py` and `tools/cm-compile.sh` gained scratch and private memory limits, a `CM_OUT_DIR` option and
per-process temporary names, and moved CMK2 packaging to the driver; the CMK3 format and `registry_gen` did not change. `patches/0001` was rewritten with the new
`anv_cm.c` reader and packer, using `anv_cm_header_ok` and `ANV_CM_HEADER_SIZE=472`; the builder was adapted and keeps the explicit base, exact push size and range
coverage checks. `layer/` gained a parallel CMK2 reader for unpatched ANV; it does not understand CMK3 and stays out of scope.

### A second registry entry

`tools/pre_profile_registry.py` and `tools/build_anv_mapping_patch.py` treat the entry count as data. They validate each row (required keys, unique 64-hex
`code_sha256`, `0 <= base < expected <= 256` aligned to 4, an existing profile file) and mix `registry_gen()` into `anv_cm_toolchain_gen`; no branch assumes one
entry. The acceptance test added a synthetic second entry in memory (`variant synthetic-412-native1080`, `code ab*32`, `input cd*32`, `zebin ef*32`, the existing
4.0.2x profile path, `base 8`, `push 56`, `surfaces 11`); it is not a 4.1.2 pin. With 2 rows loaded, `find_profile` returned the old entry (`2e42d33c…` to `(4,52)`)
and the synthetic one (`ab*32` to `(8,56)`), and `None` for `00*64`, `ff*64` and `REQUIRED-TBD`. A synthetic `registry_gen` of `b2c0cc64` differed from `912cda6a`,
stayed stable, and changed with `expected_push_size`. With `load_registry` mocked to 2 entries, `adapt()` embedded `h = (h ^ 0xb2c0cc64u)`, dropped `0x912cda6a` and
kept the comment `LOCAL profile generation`.

Fail-closed behavior held: `load()` rejected the `future_registry_entry_fragment` (all `REQUIRED-TBD`), duplicate rows, a base of `5` and a missing profile with
`ValueError`. No 4.1.2 digest reached the real registry at that point. `tools/build_pre_profile.py` still pins the 4.0.2x `EXPECTED_INPUT`, `EXPECTED_ZEBIN` and the
11-value `EXPECTED_BTIS`, so a different PRE needs its own review and, if the hashes differ, a builder change proposed separately. Copying base 4 and push 52 onto a
new hash is not allowed.

### Regenerating 0001 for a new PRE

The sequence below is the procedure to follow, and it stays verbatim. It assumes every `REQUIRED-TBD` in `profiles/xmx412-pins.json` has a reviewed value and that the new
profile exists. These checks never ran it for 4.1.2; the profile and registry entry landed later under their own review.

```sh
# 1. Isolate the Xe2 PRE envelope (pack 40102, native/1080p class) and compile
#    it offline with the pinned toolchain (IGC 2.10.10+18926, ocloc 25.18.33578.6,
#    device 0xe20b). Record input/zebin/code SHA-256.
mkdir -p analysis/offline-pre-412/full
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/cm-payloads-412/module-XXXX.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412/full" \
  -output pre -options '-vc-codegen'

# 2. Inspect the zebin and audit the payload (static, CPU-only).
python tools/inspect_zebin.py analysis/offline-pre-412/full/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/offline-pre-412/full/summary.json
# 3. Generate the NEW profile file (do not edit the old one). Note: the
#    current builder is pinned to the 4.0.2x PRE; if it rejects the new input,
#    propose the change without applying it and document the new builder/pins.
python tools/build_pre_profile.py analysis/cm-payloads-412/module-XXXX.cmspv \
  analysis/offline-pre-412/full/pre_bmg.bin > profiles/fsr4-pre-412-native1080-bmg.json

# 4. Add the NEW entry to profiles/registry.json (keep the old one),
#    filling future_registry_entry_fragment with real code/input/zebin,
#    the new profile, and audited base/push/surfaces. Validate:
python tools/pre_profile_registry.py <new_code_sha256>
python -m unittest tests.test_profile_selection -v
python -m unittest tests.test_xmx412_pins -v

# 5. Regenerate 0001 (the only versioned write in this sequence) and check:
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux \
  > /tmp/anv-mapping-412-regen.patch
cp /tmp/anv-mapping-412-regen.patch patches/0001-anv-cmk3-explicit-mapping.patch
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest tests.test_profile_selection tests.test_xmx412_bridge_regen -v
```

Step 5 is the only versioned write. Its expected effect is a new embedded digest in both internal variants plus a hunk count change. The global CMK2 path stays
intact, and an unknown hash still takes the legacy path on a miss.

## Recheck against 4.1.2

The review used strings, imports, docs and the decompressed packs. It made no new disassembly, did not compile the new PRE, and ran no DLL or driver.

| Piece | Old 4.0.2x | New 4.1.2 |
|---|---|---|
| Extracted DLL | `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`, 25,779,712 B, `3eb08656…0eba08eba53` | `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`, 45,558,272 B, `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| Packs | 3 packs, 690 envelopes (`analysis/fsr-resources/manifest.json`) | 6 packs, 1,977 envelopes (`analysis/fsr-xmx-412/manifest.json`, `docs/xmx412-pack-envelope.md`) |
| Pack Xe2 40102 raw | n/a | `analysis/fsr-xmx-412/pack-40102.raw`, 23,682,325 B, `d88aa9d6…995e491`, 252 envelopes |

```sh
python3 tools/inspect_dll.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
strings -a <dll> | grep -i -E "cachedblob|GetCached|blob|4.20.0|root ?sig|0028ZR|FNV1a64|igdext"
llvm-objdump -p <dll>   # Import/Export tables only, no execution
python3 -c "from tools.carve_spirv import carve; ..."       # on pack-40102.raw
python3 -c "from tools.parse_cm_payloads import parse; ..." # on pack-40102.raw
```

The INTC set is identical, with and without the underscore (10 strings): `INTC_D3D12_CheckFeatureSupport`, `INTC_D3D12_CreateComputePipelineState`,
`INTC_D3D12_CreateDeviceExtensionContext`, `INTC_D3D12_GetCachedBlob`, `INTC_DestroyDeviceExtensionContext` and the `_INTC_*` variants. `requested=4.20.0` appears in
DIAG and in 12 fail-stop strings (`Intel extension context 4.20.0 failed [for passN]`), byte-identical to the old DLL. The igdext resolution strings are unchanged
(`Intel DX12 extension igdext64.dll could not be resolved with required exports.` and `... with required DX12 exports was not found beside DLL, system search, or
DriverStore.`). Core imports are unchanged: `d3d12.dll:D3D12SerializeRootSignature`, `dxgi.dll:CreateDXGIFactory2`, `Cabinet.dll` ordinals 40/43/45,
`bcrypt.dll:BCryptHash`. Changes outside the INTC bridge: FSR exports went from 5 to 6 with `OptiPluginInit` at ordinal 1, an OptiScaler plugin entry (the `ffx*` set
is still enumerated and the shim uses igdext). `USER32.dll:MessageBoxA` is new; KERNEL32 gained `CreateThread`, `GetLocalTime`, `GetTickCount64` and
`SetEnvironmentVariableA` and lost `FormatMessageW`; the CRT gained `ceilf`/`exp2`/`logf`/`sqrtf`, `atof`/`atoi`, `realloc`, `strncmp`, `_putenv_s` and
`__stdio_common_vsprintf`. A dialog in a headless prefix is the only risk; the patches do not depend on these. The strings `nvngx_dlss.dll`, `fsr-original.dll`, the
`Skip`/`Hybrid`/`QSkip` variants and `4.1.2X` matter for an environment with unverified weights, not for the INTC or CMK3 paths.

The four blob strings are byte-identical between old and new: the two export names, `[FSR4 XMX] PRE stage-2 dump unavailable: INTC_D3D12_GetCachedBlob export
missing.`, `... failed: hr=0x%08X blob=%p.`, `... blob: hr=0x%08X bytes=%zu FNV1a64=0x%016llx file='%s' write=%s.` and `PRE stage-2 dump path is too long; dump
skipped.`. None carries `fail-stop will trigger`, unlike the 14+14 create/serialize root signature strings and the 12 context strings. A missing export or a failed
`hr` only skips a diagnostic dump, so the shim keeps `E_NOTIMPL`.

The `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB physical heap slots retained.` and DIAG serialized-bytes strings are
byte-identical, and the create/serialize failure counts stay at 14 and 14. The reviewed profile (b0 at 0, 11 surfaces at 4..44, sampler at 48 in a separate heap)
still describes the old PRE, and the new DLL does not contradict it. The DIAG chain only proves that bytes, FNV, `rootParameters` and `flags` can be logged; it fixes
no number. For 4.1.2, require a real DIAG log with `rootParameters==13` (1 constant plus 12 tables) before claiming the geometry survived. Pack 40102 for 4.1.2 holds
252 envelopes in 14 families of 18 variants, with the same names and trailer `-vc-payload -Xfinalizer '-noDPASMacro' -target-features=+ocl_runtime`. The PRE payload
changed: 18 IRs of 358,776 bytes (`49e069fd…`, `20096eef…`) against the old 330,108 bytes (`1d10c34e…`, envelope `76942f6c…`). `tools/parse_cm_payloads.py` found 0
of 252 envelopes matching the registered `envelope_sha256`, and 0 matching the old IR. The registry digests `2e42d33c…`, `76942f6c…` and `3e974d57…` do not appear in
the new pack. The CMK3 reader cannot inherit `table_pc_base=4`, `expected_push_size=52` and `surface_count=11` without an audit of the new binary.

| Patch | Assumption | 4.1.2 evidence | Verdict |
|---|---|---|---|
| 0002 | DLL asks 4.20.0 through 192→200; helper copies 7 device fields and 3 outputs only on success; stubs model the initializer | Same DIAG version and 12 fail-stops; no new context export; `D3D12SerializeRootSignature` import unchanged; the 192/200 CPU asserts remain the guard | keep, no regeneration |
| 0003 | Early `S_OK` reuse lives in the shim, not the DLL; contract is device, version, refresh, restore | Reuse strings identical (`PRE diagnostic fresh CreateDeviceExtensionContext`, `fresh context destroy`, `NEVER DISPATCHED`, `W0 Quarantined…no slot reuse`); no new codes; the context DIAG logs the granted contract (`returnedDriverBuild`, `driverDesc`, `driverVersion`) | keep, stacked 0002→0003 |
| 0001 | Base 4, push 52, 11 surfaces, separate sampler for `2e42d33c…` | 18 IRs of 358,776 B, none registered | change process, not code; do not extend the registry with reused numbers |
| 0001 | CMK3 checks magic, `flags==1`, `nsurf 1..24`, aligned base, exact push, range coverage; CMK2 intact | No evidence breaks the guards; Lite 378, DLSS-K 716, E/F 312 and MX 67 envelopes never match by hash | keep the reader and its limits |
| 0001 | `registry_gen()` invalidates caches when the registry changes | 2 entries and digest `3ddd809f` after the promotion | keep; additions go through the builder |
| all | A miss falls back to legacy CMK2 | Hash-gated selection | keep `experimental-offline-only` |

Follow-up work: leave 0002 and 0003 alone, and after any base move re-run the builders, the `patch -p1` stack and `python -m unittest tests.test_context_output
tests.test_context_reuse -v`. Leave 0001 and the registry shape alone; the 4.1.2 entry went in through the builder, which bumps the digest, and unlisted hashes still
fall back to CMK2. Before a runtime claim, capture `PRE extension context=…`, `PRE root signature serialized … rootParameters … flags=…` and `PRE PSO request …`,
require `rootParameters==13`, stable bytes and FNV, and deterministic GPU readback. `S_OK`, the overlay and the absence of a fail-stop do not count as success
(`docs/compatibility.md`).

## What is pinned

Pins let a regeneration reproduce the same patch or fail loudly, and keep the registry from accepting an unreviewed hash; the values above are the build pins.

| Item | Value |
|---|---|
| 4.1.2 source DLL | `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`, 45,558,272 B |
| Loader digests | commit `7059945`, `tools/decompress_xmx412.py` `EXPECTED`; decompressed sizes `0x21B5796`, `0x1695D15`, `0x28164A1`, `0x2882689`, `0x12AEC75`, `0x531061` |
| Packs | 6 packs with 252/252/378/716/312/67 = 1,977 CM envelopes |
| Non-pack resources | VERSIONINFO 776 B `20ba4d46…78bd072` (FileVersion 4.0.2.1); XML manifest 145 B `d2952e57…68bde04` |

The loader record was cross-checked against `analysis/fsr-xmx-412/manifest.json`, the eight files in `/tmp/opencode/xmx-new/res412/` with recomputed SHA-256, and
`analysis/fsr-xmx-412/pack-40102.raw`. The loader is `FUN_180029640` at RVA `0x29640-0x29b9a`, with anchor string RVA `0x30E010`.

The registry holds two reviewed entries. The 4.0.2x entry is code `2e42d33c…`, input `76942f6c…`, zebin `3e974d57…` and profile
`profiles/fsr4-pre-native1080-bmg.json`. The 4.1.2 entry is code `68b962b5…`, input `ce372719…`, zebin `b1781bb4…` and profile
`profiles/fsr4-pre-412-native1080-bmg.json`. Both use base 4, push 52 and 11 surfaces, with the sampler in a separate heap. `find_profile` returns an entry only for
those reviewed hashes and `None` for everything else, which is the legacy CMK2 path.

`profiles/xmx412-pins.json` is a staging file, not the registry. Do not pass it to `tools/pre_profile_registry.py`; `tests/test_xmx412_pins.py` reads it with
read-only hashing. It pins the 4.1.2 source DLL, the six loader digests, the two non-pack resources and the shape of a future registry entry. Its `pre_xe2_412` block
still says every field is `REQUIRED-TBD`, although `a9c06ab` promoted a resolved entry. Two blockers also remain: no 4.1.2 disassembly artifact is pinned
(`analysis/fsr-xmx-disassembly.txt` and `fsr-xmx-static.json` cover the old `3eb08656…` DLL), and the TBD tests in `tests/test_xmx412_pins.py` still need to become
positive pin tests. Treat the registry as current and update the staging file before relying on its blockers.

## Validation limits

- The UCRT build statically links the C++ runtime but imports the UCRT APIs. No MSVC or Windows SDK build exists, and
the DLL hashes are not bit-reproducible.
- None of these checks loads the DLL in Wine or Proton, injects a kernel, or reads pixels back. A green build is not a
working bridge.
- The 4.1.2 geometry is unproven. It needs `rootParameters==13` in a real DIAG log and deterministic GPU readback
before anyone extends the registry with new numbers.
- The profile and toolchain claim `experimental-offline-only`. Nothing here copies artifacts into runtime caches.

The integration order proposed in phase 4 was:

1. Trace the PRE in a disposable prefix and compare it against the profile (b0 at 0, surfaces 4..44, sampler 48,
   total 52). If it differs, add a variant to `registry.json`, regenerate 0001 (the bump invalidates caches) and add
   parametrized cases.
2. Run a synthetic probe and then a PRE readback against a CPU oracle, with the driver canary and injection logs.
3. Try the game last, reversibly per game.

No Mesa rebuild was made in that phase. `apply --check` of the regenerated 0001 and a synthetic C test of the reader block on CPU covered the driver side instead.

## History

The first base was `ef39559`: shim baseline of 1,615,360 bytes, the phase 4 candidate of 1,616,896 bytes (`8afc4973…`) with 75 exports, one registry entry with
digest `912cda6a`, and 204 tests (183 baseline, 13 from that phase, 8 from parallel commits `603dd4b` and `c565142`). At `662dc6e`, upstream had already added the
output copy in `8f45d12`, so 0002 became a move into the shared helper; the shim reached 79 exports and 861,184 bytes, and the registry reached two entries and
digest `3ddd809f`. The 4.1.2 recheck found a different PRE payload, and `a9c06ab` promoted a compiled 4.1.2 entry with base 4, push 52 and 11 surfaces.
