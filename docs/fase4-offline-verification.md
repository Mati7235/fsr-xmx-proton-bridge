# Phase 4: shim/ANV bridge ready for integration (CPU only, not installed)

Goal achieved: the bridge is in candidate state, compiled and CPU-probed,
awaiting the Phase 1 trace to confirm the real layout.
Nothing was installed, Steam/prefixes were not touched, no DLL/GPU/Wine was executed.

> Update 2026-11-13: the patches were regenerated against `662dc6e`.
> The registry still has 2 entries and `registry_gen()=0x3ddd809f`; the full suite
> passes 415 tests (3 skips) and the new cross-build is in
> `docs/shim-cross-build.md`. The figures in the table below are the
> historical run on `ef39559`.

## Verified in this phase

| Component | Evidence |
|---|---|
| D3D12 reuse (0003 over 0002) | `tools/build_context_reuse_patch.py` deterministic and pinned; `patch -p1` stacked `0002 -> 0003`; `tests/test_context_reuse.py` (5 tests: pin, rejection, stack, Windows ABI, CPU harness with device/version matrices and Context2; the original exits `6` without refresh) |
| Profile-per-hash selector | `profiles/registry.json` + `tools/pre_profile_registry.py`; `find_profile` returns the entry only for the reviewed code hash, `None` (legacy path) for the rest |
| Cache identity bump | `registry_gen() = 912cda6a` mixed into `anv_cm_toolchain_gen` in both variants; `patches/0001-...` regenerated, `git apply --check` clean; `tests/test_profile_selection.py` (8 tests: registry, identity, legacy intact, parametrized C with 10 layouts) |
| Shim cross-build (full stack) | Isolated copy in `/tmp`, `patch -p2` 0002+0003, cmake+ninja with the existing LLVM-MinGW: **14/14 targets, 0 errors/warnings**, `igdext64.dll` 1,616,896 B `8afc4973…`, PE32+ AMD64, 75 named exports, imports KERNEL32/ADVAPI32/UCRT (same shape as the documented baseline; UCRT pending runtime validation, as already known) |
| Full suite | **204 tests OK** (183 baseline + 13 from this phase + 8 from parallel commits `603dd4b`/`c565142`) |
| Full Mesa build | **Not rebuilt**: there is no source tree in `build/` (only previous logs). Covered by `apply --check` of the regenerated 0001 + synthetic C validation of the reader block on CPU. The Mesa build documented in `lab-mesa-build.md` remains the evidence of driver compilation |

## Verdict: configuration vs. code changes

**Configuration (no new code):** `IGDEXT_*` overrides, the pinned IGC/ocloc
toolchain (`profiles/intel-toolchain.json` + `registry.json`), per-hash PRE
selection (only `registry.json`), the `(4, 52)` layout of this PRE (profile),
and the identity bump (generated automatically when regenerating 0001).

**Code changes (candidates, require runtime validation before installing):**
0002 (copy at init), 0003 (validation + refresh on reuse), 0001 regenerated
(CMK3 reader + identity). All three preserve global behavior: D3D11 halves
intact, CMK2 path intact, unknown hashes → legacy, and new errors only where
previously there was a silent `S_OK` without outputs.

## Proposed integration order

1. **Phase 1 trace** (disposable prefix): real Vulkan layout of the PRE.
   Compare against the profile (b0@0, surfaces 4..44, sampler 48, total 52).
2. **If it matches:** freeze profile/registry. If it differs: new variant in
   `registry.json` + regenerate 0001 (the bump invalidates caches by itself) +
   parametrized cases. No change in code shape is expected.
3. **Disposable runtime:** synthetic probe → PRE readback against a CPU oracle
   (`docs/pre-resource-descriptors.md:192-231`), with driver canary and injection
   logs. Only then consider a reversible installation.
4. **Game (Cyberpunk):** last, reversible per game.

Nothing above copies artifacts to runtime caches nor activates the helper with
these profiles; the status remains `experimental-offline-only`.
