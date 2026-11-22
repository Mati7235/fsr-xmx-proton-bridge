# Bridge recheck against DLL 4.1.2 (static, CPU-only)

Method: static inspection only. The DLL was not executed; no GPU/Wine/prefixes.
`artifacts/original`, `upstream/`, games and prefixes were not touched. No existing file
is modified: this doc is the only output.

## Compared artifacts

| Piece | Old | New 4.1.2 |
|---|---|---|
| Extracted DLL | `artifacts/extracted/fsr-xmx/amd_fidelityfx_upscaler_dx12.dll`, 25,779,712 B, SHA-256 `3eb08656…0eba08eba53` | `artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll`, 45,558,272 B, SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732` |
| Packs | 3 packs, 690 envelopes (`analysis/fsr-resources/manifest.json`) | 6 packs, 1,977 envelopes (`analysis/fsr-xmx-412/manifest.json`, doc `docs/xmx412-pack-envelope.md`) |
| Pack Xe2 40102 raw | — | `analysis/fsr-xmx-412/pack-40102.raw`, 23,682,325 B, SHA-256 `d88aa9d6…995e491`, 252 envelopes |

Static commands used (read-only, no execution):

```sh
python3 tools/inspect_dll.py artifacts/extracted/fsr-xmx-412/amd_fidelityfx_upscaler_dx12.dll
strings -a <dll> | grep -i -E "cachedblob|GetCached|blob|4.20.0|root ?sig|0028ZR|FNV1a64|igdext"
llvm-objdump -p <dll>   # solo tablas Import/Export, no ejecución
python3 -c "from tools.carve_spirv import carve; ..."       # sobre pack-40102.raw
python3 -c "from tools.parse_cm_payloads import parse; ..." # sobre pack-40102.raw
```

## Extension API and version (applies to 0002/0003)

New evidence (DLL 4.1.2, `strings -a` + `inspect_dll.py`):

- Same INTC set as the old one, with and without underscore (10 strings, identical):
  `INTC_D3D12_CheckFeatureSupport`, `INTC_D3D12_CreateComputePipelineState`,
  `INTC_D3D12_CreateDeviceExtensionContext`, `INTC_D3D12_GetCachedBlob`,
  `INTC_DestroyDeviceExtensionContext` (+ variants `_INTC_*`).
- `requested=4.20.0` present in DIAG and in 12 fail-stop strings
  (`Intel extension context 4.20.0 failed [for passN]`), byte-identical to the old one.
- igdext resolution identical: `Intel DX12 extension igdext64.dll could not be
  resolved with required exports.` + `... with required DX12 exports was not found
  beside DLL, system search, or DriverStore.` (unchanged).
- Core imports unchanged: `d3d12.dll:D3D12SerializeRootSignature`,
  `dxgi.dll:CreateDXGIFactory2`, `Cabinet.dll` ordinals 40/43/45,
  `bcrypt.dll:BCryptHash`. Read-only via `llvm-objdump -p`.

Differences that do NOT touch the INTC bridge (recorded, not patched):

- FSR exports 5 → 6: `OptiPluginInit` is added (ordinal 1; the `ffx*` set is still
  enumerated). It is an OptiScaler plugin entry, not an INTC export; the shim uses igdext, not `ffx*`.
- New import `USER32.dll:MessageBoxA` (previously absent) + minor additions in
  KERNEL32 (`CreateThread`, `GetLocalTime`, `GetTickCount64`,
  `SetEnvironmentVariableA`; `FormatMessageW` removed) and CRT (`ceilf/exp2/logf/sqrtf`,
  `atof/atoi`, `realloc`, `strncmp`, `_putenv_s`, `__stdio_common_vsprintf`).
  Environmental risk only (dialogs in a headless prefix), with no effect on the patches.

## GetCachedBlob (question: did it become mandatory?)

New evidence: the 4 blob strings are byte-identical old/new:

- `INTC_D3D12_GetCachedBlob` / `_INTC_D3D12_GetCachedBlob` (dynamic resolution).
- `[FSR4 XMX] PRE stage-2 dump unavailable: INTC_D3D12_GetCachedBlob export missing.`
- `[FSR4 XMX] PRE stage-2 GetCachedBlob failed: hr=0x%08X blob=%p.`
- `[FSR4 XMX] PRE stage-2 blob: hr=0x%08X bytes=%zu FNV1a64=0x%016llx file='%s' write=%s.`
- Plus `PRE stage-2 dump path is too long; dump skipped.` (identical).

None of them carries `fail-stop will trigger` (unlike the 14+14 of
create/serialize root signature and the 12 context ones). It remains a
diagnostic/stage-2 dump path that tolerates `export missing` and a failed `hr`.
Verdict: **keep** the shim's `E_NOTIMPL` (`shim/src/dll/D3D12Api.cpp:120-124`
per `docs/compatibility.md:47`). No change.

## Root signature b0 + 11 tables + sampler (DIAG/FNV question)

New evidence:

- `[FSR4 XMX 0028ZR] PRE production ABI: one table per SurfaceIndex/sampler; ZB
  physical heap slots retained.` — byte-identical old/new.
- `[FSR4 XMX DIAG] PRE root signature serialized bytes=%zu FNV1a64=0x%016llx
  rootParameters=%u flags=0x%X.` — byte-identical old/new.
- create/serialize root signature counts identical: 14 `Failed to create ...`,
  14 `Failed to serialize ...`, plus `root signature creation/serialization failed`.
- `PRE sampler heap creation failed` and `PRE Intel capabilities ... OPTIONS1/OPTIONS2 ...`
  identical; `CheckFeatureSupport` audit-missing identical.

Reading: the assumption of the reviewed profile (b0@0 + 11 surfaces at 4..44 +
sampler at 48 in a separate heap, `profiles/fsr4-pre-native1080-bmg.json`,
`docs/offline-pre-compilation.md:54-76`) **still holds for that old PRE**
because the new DLL does not contradict the declared ABI. But the DIAG chain only
proves future observability (bytes + FNV + `rootParameters` + `flags` loggable),
not the geometry: it fixes no number statically.
Verdict: **keep** the reader/map for the reviewed hash; for 4.1.2 require
a real DIAG log with the expected `rootParameters==13` (1 constant + 12 tables) before
claiming the geometry is preserved. No patch change.

## base-4/push-52 geometry (question: still valid in 4.1.2?)

New evidence (static, packs already decompressed):

- New 40102: 252 envelopes, 14 families × 18 variants, same names
  (`fsr4_pre_xmx`, `p1/p2_h1_hybrid`, `p3_xmx_n32`, ... `post_xmx`) and same trailer
  `-vc-payload -Xfinalizer '-noDPASMacro' -target-features=+ocl_runtime`.
- BUT the PRE content changed: IR `358.776` B × 18 ( SHAs `49e069fd…`,
  `20096eef…`, …) versus the old IR `330.108` B (`1d10c34e…`, envelope
  `76942f6c…`). With `tools/parse_cm_payloads.py`: **0 of 252** new envelopes
  match the `envelope_sha256` in the registry (`76942f6c…`), and **0** match the old
  IR. The `code_sha256 2e42d33c…` / `input_sha256 76942f6c…` /
  `zebin_sha256 3e974d57…` from `profiles/registry.json` does not appear in the new pack.
- Conclusion: the new pack carries a different, unreviewed binary geometry (different size;
  BTI/order not audited for this binary). The CMK3 reader cannot inherit
  `table_pc_base=4` / `expected_push_size=52` / `surface_count=11` blindly.

## Table: assumption → new evidence → verdict per patch

### `patches/0002-shim-context-output.patch` (doc `docs/context-output-fix.md`)

| Bridge assumption | New 4.1.2 evidence | Verdict |
|---|---|---|
| DLL requests `RequestedExtensionVersion 4.20.0` via `INTCExtensionInfo(192B)→Info1(200B)` | DIAG `requested=4.20.0 … GTGen/EU/gpuMHz/TDP/fillRate` + 12 identical `4.20.0` fail-stops; no new version | **keep** |
| Helper copies 7 device-info + 3 driver outputs only on success; D3D11/`Context2` out of scope | Same context failure strings; no new context export; `D3D12SerializeRootSignature` import unique and unchanged | **keep**, no regeneration |
| `InitExtensions` fills outputs; the stub models them | No observable static change; the CPU Asserts 192/200 of the patch remain the guard | **keep** |

### `patches/0003-shim-context-reuse.patch` (doc `docs/context-reuse-fix.md`)

| Bridge assumption | New 4.1.2 evidence | Verdict |
|---|---|---|
| Early-`S_OK` reuse without refresh exists in the shim (not in the DLL) | Reuse/diagnostic strings identical (`PRE diagnostic fresh CreateDeviceExtensionContext`, `fresh context destroy`, `NEVER DISPATCHED`, `W0 Quarantined…no slot reuse`); no new reuse semantics in the DLL | **keep** |
| Contract: same device → `S_OK` + refresh; major version → `E_NOINTERFACE`; different device → `E_INVALIDARG`; no rebind | No new codes or context exports; `DestroyDeviceExtensionContext` unchanged; context fail-stop unchanged | **keep**, stacked 0002→0003 |
| Refresh re-runs `InitExtensions` on the live half and restores `m_SupportedExtVersion` | No evidence against it in strings/imports; context DIAG logs the granted contract (`returnedDriverBuild/driverDesc/driverVersion…`) | **keep** |

### `patches/0001-anv-cmk3-explicit-mapping.patch` + `profiles/registry.json` (docs `docs/profile-selection-cache-identity.md`, `docs/offline-pre-compilation.md`)

| Bridge assumption | New 4.1.2 evidence | Verdict |
|---|---|---|
| `table_pc_base=4`, `expected_push_size=52`, 11 surfaces, separate sampler (only PRE `native_1080` hash `2e42d33c…`) | New 40102 PRE = 18 IRs of 358,776 B, none matches a registered IR/envelope; new geometry not compiled/audited | **change process, not code**: do NOT extend the registry; do NOT reuse base-4/push-52 outside the reviewed hash |
| CMK3 reader validates: magic `CMK3`, flags==1, `nsurf 1..24`, aligned base, exact push + coverage by ranges; CMK2 intact | No DLL change invalidates those guards; new packs (Lite 378, DLSS-K 716, E/F 312, MX 67: `k_gemm/k_linear/e_conv/m_layer…`) never hit by hash | **keep** reader and limits as they are |
| `registry_gen()=0x912cda6a` invalidates caches when the registry changes | Registry intact (1 entry); digest needs no change | **keep**; any future addition must go through `tools/build_anv_mapping_patch.py` (automatic bump) |
| Global effect null: miss → legacy CMK2 | Confirmed by hash-gated design; 4.1.2 adds no surfaces to the reviewed profile | **keep** `experimental-offline-only`, no runtime |

## Proposed concrete changes (NOT applied, no commit)

1. **0002 / 0003: do not touch.** Only re-verify determinism when appropriate:
   `python tools/build_context_output_patch.py`,
   `python tools/build_context_reuse_patch.py` + `patch -p1` 0002→0003 in an isolated tree
   + `python -m unittest tests.test_context_output tests.test_context_reuse -v`.
   There is no new evidence requiring a rewrite of the helper or the reuse contract.
2. **0001 / registry: do not touch.** Keep 1 entry (`PRE 4.0.2x native_1080`,
   `code 2e42d3…`, base 4, push 52) and the digest `0x912cda6a`. The reader still
   rejects on magic/flags/nsurf/coverage; the unknown (all of 4.1.2 and the
   DLSS K/E/F/MX packs) falls back to CMK2 on miss.
3. **To support 4.1.2 (separate milestone, CPU-only):** compile offline the candidate
   `native_1080` of the new 40102 with the pinned toolchain
   (`profiles/intel-toolchain.json`: IGC `2.10.10+18926`, ocloc `25.18.33578.6`,
   device `0xe20b`), inspect BTIs with `tools/inspect_zebin.py`, generate a
   **new** profile file (do not edit the old one) via `tools/build_pre_profile.py`,
   add a **new** registry entry with its own `code/input/zebin_sha256`,
   regenerate with `tools/build_anv_mapping_patch.py` (cache identity bump) and
   extend `tests/test_profile_selection.py` with the new `(base,push)` row;
   copying base-4/push-52 to the new hash without that audit is prohibited.
4. **Before any runtime:** capture the new DIAG lines
   (`PRE extension context=…`, `PRE root signature serialized … rootParameters …
   flags=…`, `PRE PSO request …`) and require `rootParameters==13` and stable bytes/FNV
   plus deterministic GPU readback; `S_OK`/magenta/absence of fail-stop does not
   suffice (criterion `docs/compatibility.md:103-108`). `GetCachedBlob` is still not
   a gate: a failed `hr` or `export missing` should only log the dump, never
   fail-stop.
5. **Environment note (docs only, no patch):** record `OptiPluginInit`,
   `USER32!MessageBoxA` and the strings `nvngx_dlss.dll` / `fsr-original.dll` /
   variants `Skip/Hybrid/QSkip` + `4.1.2X` as considerations for a headless prefix
   and for unverified weights; they do not change the INTC/CMK3 bridge.

## Limits of this review

Strings + imports + docs/packs; no new disassembly, no compilation of the new PRE,
no DLL or driver execution. The version/API identity is evidence of contract
compatibility, not proof of GPU correctness or layout. The 4.1.2 geometry remains
explicitly **not validated** until milestones 3–4.
