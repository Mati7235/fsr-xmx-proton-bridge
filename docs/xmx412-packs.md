# XMX 4.1.2 packs: reproducibility and CM block inventory (40101/40102/40103)

Static, CPU-only verification. The DLL was read as bytes and never loaded;
no GPU, Wine, Steam, prefix, driver, or `artifacts/original` state was
touched. Decoder: `tools/decompress_xmx412.py` (local libwim LZMS) with
fail-closed size/SHA-256/CM-count gates. Parser: `tools/parse_cm_payloads.py`
(verified length footers). Carve heuristic: `tools/carve_spirv.py`.
Disassembler: `spirv-dis` (SPIRV-Tools 2026.4) over exact IR slices.

Inputs: DLL SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`,
decoded packs in `analysis/fsr-xmx-412/` (git-ignored), old reference
`analysis/fsr-resources/resource-0001-first.spv` + `xe2-first.spvasm`.
Tests: `tests/test_xmx412_packs.py` (12 tests, all pass).

## (a) Reproducibility: re-running the decompressor is byte-identical

Re-ran `tools/decompress_xmx412.py` on the DLL into `/tmp/opencode/xmx412-repro`
(`--libwim upstream/wimlib/.libs/libwim.so`). All six packs decode with exact
size matches and SHA-256 identical to the stored raws and to the pins in
`tools/decompress_xmx412.py` (commit 7059945):

| Pack | Compressed | Raw | raw SHA-256 (prefix) | CM |
|---|---|---|---|---|
| 40101 | 6 107 632 | 35 346 326 | `4c63d10c…aa88ab8d` | 252 |
| 40102 | 3 856 836 | 23 682 325 | `d88aa9d6…995e491` | 252 |
| 40103 | 6 960 934 | 42 034 337 | `a3731f5b…70eb7d5` | 378 |
| 40104 | 8 031 050 | 42 477 193 | `a9ea6724…7054ea` | 716 |
| 40105 | 3 421 152 | 19 590 261 | `7ac547ee…57d246fa` | 312 |
| 40106 | 1 001 522 | 5 443 681 | `03c18858…5a331ac3` | 67 |

Total 1 977 envelopes (old 4.0.2x build: 252+252+186 = 690). No discrepancy:
every byte count, digest, and envelope count above equals the 7059945 pins.

## (b/c) Block inventory: CM envelopes, spirv-dis, carve, gaps

| Pack | CM envelopes | SPIR-V magics | Carved (`carve_spirv`) | `spirv-dis` ok | Gaps | DXBC in gaps | Non-zero non-DXBC gaps |
|---|---|---|---|---|---|---|---|
| 40101 DG2 | 252 | 252 | 246 | 252/252 | 251 (227 zero) | 18 × 33 786 B | 6 × 134 938 B (weights-like) |
| 40102 Xe2 | 252 | 252 | 252 | 252/252 | 251 (all zero, max 15 B) | 0 | 0 |
| 40103 Lite | 378 | 378 | 378 | 378/378 | 377 (all zero, max 255 B) | 0 | 0 |

Notes:

- All 882 focus-pack IRs disassemble with `spirv-dis` (0 failures). The
  `.spvasm` label in the task refers to this disassembly step.
- 40101 gap detail: 18 DXBC candidates (`declared_size` ~33 764/33 772,
  7 chunks each) plus 6 opaque 134 938-byte blobs with no `DXBC` marker
  (offsets 1 918 694, 7 809 766, 13 700 838, 19 591 910, 25 482 966,
  31 373 990) alongside the usual tiny zero paddings (7–14 B).
- 40101 carve gap: the 6 CM envelopes missing from `carve_spirv` output are
  all `fsr4_post_xmx` with `ir_size` 189 728 (CM indices 13, 55, 97, 139,
  181, 223). They disassemble cleanly from the exact IR slice; the
  heuristic walk (which scans to the next magic instead of stopping at the
  footer-pinned `ir_size`) runs past the IR into gap bytes and rejects the
  module. The CM footer parser stays authoritative.
- Entry census (carved): 40101/40102 each cover 14 families × 18 variants
  (`fsr4_pre_xmx`, `p1/p2_h1_hybrid`, `p3_xmx_n32`, `p4/p5_fused_low128`,
  `pass6_xmx_runtime`, `p7/p8/p9_stage0_xmx`, `p10/p11_fused_low128(_ct2d)`,
  `p12_h1_hybrid`, `post_xmx`; 40101 carves only 12/18 `post_xmx`).
  40103: 36 `p10` + 36 `p11` + 144 `post_xmx` + 6 `pre_xmx` + 18 `i8_fnb64`
  + 6 `i8_p6` + 48 `lite_p1a` + 24 `lite_p1b` + 36 `lite_p2` + 24 `lite_p3`.
- Options strings: every 40101 envelope is `-vc-payload` /
  ` -target-features=+ocl_runtime`; every 40102 envelope is
  `-vc-payload -Xfinalizer '-noDPASMacro'` /
  ` -target-features=+ocl_runtime`; 40103 mixes both (189 + 189).
- 40104–40106 re-verified only for counts this pass: 716/312/67 envelopes,
  712/307/66 gaps, all gaps zero-filled, no DXBC. Six-pack total unchanged.

## (d) PRE Xe2 block identified in 40102

CM envelope index 0 at pack offset 0 (first block of the Xe2 pack):

- Entry `fsr4_pre_xmx` (Kernel, id 11173 in the carved module 0000;
  carve offset/size equal the CM offset/`ir_size`, carve blob SHA equals
  the CM `ir_sha256`).
- `ir_size` 358 776, `trailer_size` 97, `envelope_size` 358 873.
- Options: `-vc-payload -Xfinalizer '-noDPASMacro'` /
  ` -target-features=+ocl_runtime` (identical strings to the old build).
- `ir_sha256` `49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568`,
  envelope `ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab`.
- SPIR-V header: v1.1, generator Khronos LLVM/SPIR-V Translator (14),
  Bound 11188, Schema 0; disassembles to 17 444 lines (old: 16 014).

Old reference (`analysis/fsr-resources/resource-0001-first.spv`, CM index 0
of old pack 40102): `ir_size` 330 108, same trailer (97) and option strings,
`ir_sha256` `1d10c34ef21007bdc11c93647ef9ea482f7988e1aee705e082c7eb1722bd44a2`,
Bound 10274. Delta new − old: **+28 668 IR bytes (+8.7 %), +914 Bound**.
Per-variant stride is preserved (18 `pre_xmx` envelopes at every 14th CM
index in both 40101 and 40102).

## Discrepancies vs 7059945

None. Envelope counts (252/252/378/716/312/67, total 1 977), sizes,
digests, 40101 carve profile (246/252, 18 DXBC), option strings, and the
old-build 690 total all reproduce exactly.

## Limitations

- `carve_spirv` is heuristic, not a container parser; CM footer records are
  authoritative where they disagree (the six 40101 `post_xmx` cases).
- Gap blobs (DXBC candidates, 134 938-byte weights-like regions, zero pads)
  are classified by header/shape only, not fully parsed.
- Embedded `-vc-payload` strings are recorded as data, not as proof of
  non-NULL INTC API option pointers.
- No functional/GPU validation was performed (out of scope for this task).
