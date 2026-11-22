# Regeneration of the XMX 4.1.2 bridge (CPU-only, no commit)

Scope: re-run the 3 builders and confirm determinism + `apply --check`
against upstream, cross-compile the shim with the 0002→0003 stack, check that
the registry will accept a second entry without code changes, and fix the
exact sequence to regenerate 0001 once the 4.1.2 profile exists.

The original run (2026-11-12) was done against `ef39559`. The update section
below re-validates everything against `662dc6e`; sections (a)–(d) are kept as a
historical record of the earlier run.

Limits respected: no DLL execution, no GPU/Wine, nothing installed, no changes
to `artifacts/original`, `upstream/`, games or prefixes. Offline compilation of
the shim with LLVM-MinGW is allowed (precedent `docs/shim-cross-build.md`). In
the historical run the patches were regenerated only in `/tmp`; the 2026-11-13
update did replace the three versioned patches after adapting the builders.
No commit.

## Update 2026-11-13: base `662dc6e`

Drift `ef39559..662dc6e`: 178 commits, 150 files, +27,845/−6,289 lines.
The full list of commits/files is in
`analysis/upstream-drift-662dc6e.md` (git-ignored). Overlaps with our
contexts:

- `shim/src/dll/IgdextApiDll.cpp`: commit `8f45d12` already copies the context
  outputs into both legacy exports. 0002 now keeps the shared helper and
  replaces those inline copies; 0003 still reuses the helper.
- `tools/cmk_pack.py`, `tools/cm-compile.sh`: new scratch/private memory
  limits, `CM_OUT_DIR` option, CMK2 packaging moved to the driver and
  per-process temporary names. Our CMK3 format and `registry_gen` do not change.
- `patches/0001-anv-cm-kernel-injection.patch` (both variants): rewrite of the
  reader/packer in the new `anv_cm.c`, with `anv_cm_header_ok` and
  `ANV_CM_HEADER_SIZE=472`. The builder was adapted to those anchors; the CMK3
  validation (explicit base, exact push size, range coverage) is kept.
- `layer/`: new CMK2 reader/packer for unpatched ANV. It is a parallel path and
  **does not** understand CMK3; it is out of scope for these patches.
- `docs/`: rewrite and reorganization (`docs/dev/`). The pins of this repo
  were updated separately.

Result of the re-validation:

| Piece | Determinism | `apply --check` | SHA-256 checked-in |
|---|---|---|---|
| 0002 | identical to the builder | OK | `fc00a77d…93f263` |
| 0003 | identical to the builder | OK only; order 0002→0003 | `ef8112d4…554f0c` |
| 0001 | identical to the builder | OK | `88e134a0…d9f2e4` |

- Shim source: SHA-256 `6d32d934…252696`, revision
  `662dc6e8787c1e9ed43e09ef73733046bc1b8dc3`.
- `registry_gen()` is still at **`3ddd809f`** (2-entry registry, no changes).
- Shim cross-build: 14/14, DLL 861,184 B
  `0a0b5462…ca8cf8`, 79 exports, imports KERNEL32/ADVAPI32/UCRT.
- Full suite: **415 tests OK, 3 skips** (`python3 -m unittest discover -s tests`).
- No commit; changes left in the working tree.

## (a) Builder determinism + `apply --check` (historical run ef39559)

Commands (read/write only in `/tmp`, without modifying the repo):

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

Result 2026-11-12:

| Piece | Determinism | `apply --check` | SHA-256 checked-in |
|---|---|---|---|
| 0002 | identical (`diff -q` clean) | OK | `fa9c302b…7f8508` |
| 0003 | identical | OK only; the valid order is 0002→0003 (see stack) | `ef8112d4…554f0c` |
| 0001 | identical | OK | `26383938…c38d70` |

Additional pins:

- Shim source `upstream/xess-xmx-linux/shim/src/dll/IgdextApiDll.cpp`
  SHA-256 `aed09d4f…80ca96`, revision `ef39559d26e083ce1bd1353b2e8c86f33c3c264c`.
- `build_full == build∘build_output` (0003 stacked on 0002) verified on CPU.
- Stack `patch -p1` 0002→0003 in an isolated tree: OK, with
  `CopyExtensionInfo1OutputsToOld(*pExtensionInfo, extensionInfo1)` and 3×
  `liveHalf` present.
- The builders reject modified source (`refusing unpinned source`).
- Covered by `tests/test_xmx412_bridge_regen.py`
  (`BuilderDeterminismTests`, `PatchApplyTests`): 17/17 OK.

No drift: no regeneration differs from the versioned patch.

## (b) Shim cross-compilation, stack 0002→0003 (14/14, no errors)

Exact sequence run (isolated copy in `/tmp`, upstream untouched):

```sh
rm -rf /tmp/opencode/xmx412-shim-stack-v01 && mkdir -p /tmp/opencode/xmx412-shim-stack-v01
cp -a upstream/xess-xmx-linux/shim /tmp/opencode/xmx412-shim-stack-v01/source
patch -p2 --batch --forward -d /tmp/opencode/xmx412-shim-stack-v01/source \
  -i "$PWD/patches/0002-shim-context-output.patch"
patch -p2 --batch --forward -d /tmp/opencode/xmx412-shim-stack-v01/source \
  -i "$PWD/patches/0003-shim-context-reuse.patch"
TC="$PWD/artifacts/extracted/llvm-mingw-20261020-ucrt/llvm-mingw-20261020-ucrt-ubuntu-22.04-x86_64/bin"
cmake -S /tmp/opencode/xmx412-shim-stack-v01/source \
  -B /tmp/opencode/xmx412-shim-stack-v01/obj -G Ninja \
  -DCMAKE_SYSTEM_NAME=Windows -DCMAKE_SYSTEM_PROCESSOR=x86_64 \
  -DCMAKE_CXX_COMPILER="$TC/x86_64-w64-mingw32-clang++" \
  -DCMAKE_RC_COMPILER="$TC/x86_64-w64-mingw32-windres" \
  -DCMAKE_CXX_FLAGS=-fms-extensions -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/opencode/xmx412-shim-stack-v01/obj -j 4
```

Result:

- Configure: `Clang 23.1.4`, `Generating done`, exit 0.
- Build: **[14/14], 0 errors, 0 warnings** in the log
  (`/tmp/opencode/xmx412-shim-stack-v01-build.log`).
- DLL: `obj/igdext64.dll`, 1,616,896 B,
  SHA-256 `3aff7abf…3054d1`, PE32+ AMD64.
- `x86_64-w64-mingw32-objdump -p`: **75 named exports** (same shape as the
  documented baseline), imports `KERNEL32.dll`, `ADVAPI32.dll` + the UCRT family
  (`api-ms-win-crt-*`), no unexpected dynamic `MSVCP`.
- Sources in `/tmp/opencode/xmx412-shim-stack-v01/source` identical to
  `/tmp/opencode/shim-cross-reuse-v01/source` (`diff -r` clean).

Note on hashes: the DLL is not declared bit-reproducible. The previous
documented build (`8afc4973…`, same size and 75 exports) differs only in
timestamp/embedded paths; what is claimed is 14/14 + the same exports/imports
shape, not hash equality. The MSVC/Windows-SDK variant was not compiled; UCRT
is still pending runtime validation, as already known.

## (c) The registry will accept a second entry without code changes

`tools/pre_profile_registry.py` + `tools/build_anv_mapping_patch.py` are
generic with respect to the number of entries: they validate each row (keys,
unique 64-hex `code_sha256`, `0 <= base < expected <= 256` aligned to 4,
existing profile file) and mix `registry_gen()` into
`anv_cm_toolchain_gen`. No branch assumes "1 entry".

Synthetic test (without touching `profiles/registry.json`; the real fragment
of `profiles/xmx412-pins.json` is still all `REQUIRED-TBD`):

- Second synthetic entry in memory: `kernel fsr4_pre_xmx`,
  `variant synthetic-412-native1080`, `code ab*32`, `input cd*32`,
  `zebin ef*32`, `profile profiles/fsr4-pre-native1080-bmg.json`
  (reuses the existing file only to pass the existence check, without creating
  files in the repo), `base 8`, `push 56`, `surfaces 11`.
  **It is not a 4.1.2 pin.**
- `load()` on a temporary file with the 2 entries: OK, 2 rows,
  `find_profile` returns the old one (`2e42d33c…` → `(4,52)`) and the synthetic
  one (`ab*32` → `(8,56)`), `None` for `00*64`, `ff*64` and `REQUIRED-TBD`.
- Synthetic `registry_gen` `b2c0cc64` ≠ `912cda6a`, stable and tied to the
  content (mutating `expected_push_size` changes it).
- With `load_registry` mocked to the 2 entries, `adapt()` embeds
  `h = (h ^ 0xb2c0cc64u)` and no longer contains `0x912cda6a`, plus the comment
  `LOCAL profile generation`.
- Fail-closed intact: the `future_registry_entry_fragment` fragment (all
  `REQUIRED-TBD`) is still rejected by `load()`; duplicates, misaligned base
  (`5`) and a nonexistent profile are also `ValueError`; no 4.1.2 digest
  (`raw_sha256` of packs) hits the real registry.

If a builder needed a change for the real 4.1.2, it is not applied here: it
would be proposed without editing. Today it is not needed: the registry/mapping
layer requires no changes. Known warning: `tools/build_pre_profile.py` is still
pinned to the hashes/BTIs of PRE 4.0.2x (`EXPECTED_INPUT/ZEBIN/BTIS`); the real
4.1.2 profile will need its own isolation/audit and, if applicable, new
generation tooling — never copy base-4/push-52 to the new hash.

Covered by `tests/test_xmx412_bridge_regen.py`
(`RegistryTwoEntryTests`, `FailClosedTests`).

## (d) EXACT sequence to regenerate 0001 once the 4.1.2 profile exists

Not executed (the profile does not exist: every `pre_xe2_412` item is `REQUIRED-TBD`).
When `profiles/xmx412-pins.json` resolves every TBD, in this order:

```sh
# 1. Aislar el envelope PRE Xe2 (pack 40102, clase native/1080p) y compilar
#    offline con el toolchain fijado (IGC 2.10.10+18926, ocloc 25.18.33578.6,
#    device 0xe20b). Registrar input/zebin/code SHA-256.
mkdir -p analysis/offline-pre-412/full
LD_LIBRARY_PATH="$PWD/artifacts/extracted/intel-toolchain/igc/usr/local/lib:$PWD/artifacts/extracted/intel-toolchain/neo/usr/lib/x86_64-linux-gnu" \
XDG_CACHE_HOME="$PWD/analysis/compiler-cache" \
artifacts/extracted/intel-toolchain/neo/usr/bin/ocloc-25.18.1 compile \
  -spirv_input -file "$PWD/analysis/cm-payloads-412/module-XXXX.cmspv" \
  -device 0xe20b -out_dir "$PWD/analysis/offline-pre-412/full" \
  -output pre -options '-vc-codegen'

# 2. Inspeccionar el zebin y auditar el payload (estático, CPU-only).
python tools/inspect_zebin.py analysis/offline-pre-412/full/pre_bmg.bin \
  --kernel fsr4_pre_xmx > analysis/offline-pre-412/full/summary.json
# 3. Generar el NUEVO fichero de perfil (no editar el viejo). Nota: el
#    builder actual está fijado al PRE 4.0.2x; si rechaza el nuevo input,
#    proponer el cambio sin aplicarlo y documentar el nuevo builder/pins.
python tools/build_pre_profile.py analysis/cm-payloads-412/module-XXXX.cmspv \
  analysis/offline-pre-412/full/pre_bmg.bin > profiles/fsr4-pre-412-native1080-bmg.json

# 4. Añadir la NUEVA entrada a profiles/registry.json (conservar la vieja),
#    rellenando future_registry_entry_fragment con code/input/zebin reales,
#    profile nuevo, base/push/surfaces auditados. Validar:
python tools/pre_profile_registry.py <nuevo_code_sha256>
python -m unittest tests.test_profile_selection -v
python -m unittest tests.test_xmx412_pins -v

# 5. Regenerar 0001 (única escritura versionada de esta secuencia) y comprobar:
python tools/build_anv_mapping_patch.py upstream/xess-xmx-linux \
  > /tmp/anv-mapping-412-regen.patch
cp /tmp/anv-mapping-412-regen.patch patches/0001-anv-cmk3-explicit-mapping.patch
git -C upstream/xess-xmx-linux apply --check \
  "$PWD/patches/0001-anv-cmk3-explicit-mapping.patch"
python -m unittest tests.test_profile_selection tests.test_xmx412_bridge_regen -v
```

Expected effect of (5): only the embedded digest changes
(`0x912cda6a` → new `registry_gen()`) in both internal variants plus the hunk
count; the global CMK2 path stays intact, and unknown hashes remain on the
legacy path on a miss.

## Outputs of this task

- `tests/test_xmx412_bridge_regen.py`: 17 tests (determinism, `apply --check`,
  synthetic 2-entry registry, fail-closed).
- This doc (`docs/xmx412-bridge-regen.md`).
- Ephemeral artifacts in `/tmp/opencode` (regenerations, shim tree and build,
  logs): not versioned.
- No patch, profile, registry or builder modified; no commit.
