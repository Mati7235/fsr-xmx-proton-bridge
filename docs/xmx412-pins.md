# XMX 4.1.2 pins: what is fixed, what blocks registry promotion

Staging file: `profiles/xmx412-pins.json` (NOT the registry — never feed it to
`tools/pre_profile_registry.py`). Gate: `tests/test_xmx412_pins.py` (CPU-only,
read-only hashing, no DLL execution).

## Already pinned (verified against artifacts on disk)

- **Source DLL** SHA-256 `fadbcb50…b37f44732` (= `analysis/fsr-xmx-412/manifest.json`
  origin; resdir input pin).
- **Loader digests** for all six packs, fixed by commit `7059945`
  (`tools/decompress_xmx412.py` `EXPECTED`): compressed size + SHA-256,
  decompressed size (= loader imm32 `0x21B5796, 0x1695D15, 0x28164A1,
  0x2882689, 0x12AEC75, 0x531061`) + SHA-256, CM envelope counts
  (252/252/378/716/312/67 = 1977). Re-checked here against
  `analysis/fsr-xmx-412/manifest.json`, all eight files in
  `/tmp/opencode/xmx-new/res412/` (recomputed SHA-256), and the Xe2
  decompressed pack `analysis/fsr-xmx-412/pack-40102.raw`.
- **Non-pack resources**: VERSIONINFO (type 16, id 1, 776 bytes,
  `20ba4d46…78bd072`, reports FileVersion 4.0.2.1) and the XML manifest
  (type 24, id 2, 145 bytes, `d2952e57…68bde04`).
- **Registry acceptance probe**: `find_profile` returns `None` for every
  4.1.2 digest today (legacy CMK2 path), which is the correct fail-closed
  state — global XeSS behavior is unchanged.

## REQUIRED-TBD (promotion blockers — never invent)

1. **4.1.2 disassembly hash**: `analysis/fsr-xmx-disassembly.txt` and
   `analysis/fsr-xmx-static.json` cover the OLD 4.0.2x DLL (`3eb08656…`),
   not this one. No 4.1.2 disassembly artifact is pinned.
2. **PRE Xe2 4.1.2 kernel pins** (`pre_xe2_412`): `code_sha256`,
   `input_sha256`, `zebin_sha256`, `table_pc_base`, `expected_push_size`,
   `surface_count`, `variant`, `profile` are all `REQUIRED-TBD`. The old
   4.0.2x PRE pins (`2e42d33c…`, base 4, push 52) MUST NOT be reused.
3. **Profile file**: no `profiles/*412*.json` exists; payload audit +
   `remaining_reviews` (as in the 4.0.2x profile) are pending.

## Promotion checklist

1. Isolate the Xe2 PRE envelope (`fsr4_pre_xmx`, native/1080p-class) from
   pack 40102 (Xe2 SIMD16 bucket).
2. Compile offline with the pinned toolchain
   (`profiles/intel-toolchain.json`: IGC `2.10.10+18926`, ocloc
   `25.18.33578.6`, device `0xe20b`) → record `input/zebin/code` SHA-256.
3. Static payload audit + new profile JSON under `profiles/`.
4. Fill the `future_registry_entry_fragment` values into
   `profiles/registry.json` (new entry; keep the old one), satisfying
   `load()` rules: required keys, unique 64-hex `code_sha256`,
   `0 <= base < expected <= 256` with 4-byte alignment, profile file exists.
5. `registry_gen()` changes automatically invalidate cached kernels via
   `anv_cm_toolchain_gen` — confirm `tests/test_profile_selection.py`
   still gates the legacy path.
6. Extend `tests/test_xmx412_pins.py` TBD tests into positive pin tests.
