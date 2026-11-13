# Profile-per-hash selection and cache identity (candidate, not installed)

## Problem

`profiles/fsr4-pre-native1080-bmg.json` pins one reviewed PRE (native_1080,
B580): input/zebin/code hashes, `table_pc_base = 4`, 11 surfaces,
`expected_push_size = 52` (b0@0, surfaces at 4..44, sampler at 48 on its own
heap). Two gaps remained (`docs/offline-pre-compilation.md:114`):

1. The profile was not connected to any runtime/helper selection: nothing
   decided **which** kernel may use the explicit CMK3 layout.
2. The per-user kernel cache identity (`anv_cm_toolchain_gen`: FNV-1a over
   ocloc/IGC file names and the packer size) did not know about the profile,
   so a profile change would not invalidate previously cached kernels.

## Decision

- **Offline selector, not a driver allowlist.** `profiles/registry.json`
  lists reviewed kernels by native code hash (currently only
  `fsr4_pre_xmx/native_1080`). `tools/pre_profile_registry.py` exposes
  `find_profile(code_sha256)`: a hit returns the reviewed entry, a miss
  returns `None` and the kernel keeps the **legacy CMK2 path**. The driver
  never parses the registry; at runtime the selection travels with the
  artifact itself (CMK3 files carry `table_pc_base` and the expected push
  size, old readers reject their magic). Unknown kernels and every XeSS
  kernel therefore behave exactly as before.
- **Cache identity bump.** `tools/build_anv_mapping_patch.py` now mixes a
  stable digest of the canonical registry content
  (`registry_gen()`, FNV-1a 32-bit, currently `0x3ddd809f` for the two-entry
  registry) into
  `anv_cm_toolchain_gen` in **both** inner Mesa patches. Any registry change
  changes the per-user cache file names, so stale `.cmk` files compiled
  under an older profile are never reused. The regenerated candidate is
  `patches/0001-anv-cmk3-explicit-mapping.patch` (still `apply --check` clean
  against the pinned upstream checkout, still CMK2-compatible).
- **Parametrized validation, scoped to this PRE.** The CMK3 reader keeps
  validating per-file: exact expected push size plus per-surface range
  coverage (`tests/test_profile_selection.py` runs the extracted C block
  against a table: the exact `(4, 52)` reference, split ranges, size
  mismatch, uncovered DWORD, out-of-range/garbage indices, empty ranges,
  mid gaps, and non-registered shapes). The check is coverage-based, not
  base-pinned — a file carries its own base — and it only runs for CMK3
  files, so the legacy tail heuristic for everything else is untouched.

## What is (and is not) integrated

- Integrated as reviewable candidates: registry, selector tool, generator
  bump, regenerated patch, parametrized CPU tests. `registry.json` and the
  profile cross-check each other's hashes (`test_registry_matches_profile_file`).
- **Not** integrated: no helper/runtime reads the registry, no cache is
  written, no driver is built or installed. Runtime integration waits for
  the Fase 1 trace (real layout confirmation) and stays gated on
  `experimental-offline-only`.

## Reproduction (no installs, no GPU)

```bash
python tools/pre_profile_registry.py 2e42d33c13d6c93bfe86fa81b1427c92aa2980df1af0100e011753a067f8ed5f
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux > /tmp/regen.patch
cmp patches/0001-anv-cmk3-explicit-mapping.patch /tmp/regen.patch
git -C upstream/xess-xmx-linux apply --check "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest tests.test_profile_selection -v
```
