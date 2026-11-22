# XMX 4.1.2 embedded pack envelope

Static, CPU-only analysis of the six compressed packs in the new XMX build
(DLL SHA-256 `fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`).
No DLL code was executed; no driver, Steam, prefix, GPU, or Wine state was touched.

## Result

The "envelope" is a stock **MS Compression API LZMS buffer** per pack: a
24-byte header followed by LZMS chunks. There is no custom cipher and no
trailing metadata block — the old pipeline (`tools/decompress_mscf.py` +
local libwim) decodes all six packs with exact size matches. Integrity is
enforced by the loader with a one-shot **BCryptHash SHA-256** over the
decompressed bytes compared against a compiled-in hex digest.

## Envelope layout (per RCDATA pack, type 10)

| Offset | Size | Field |
|---|---|---|
| 0 | 4 | Magic `0A 51 E5 C0` |
| 4 | 2 | Header size = 24 |
| 6 | 1 | Header CRC (low byte of CRC-32 over bytes 0–5 then 7–23) |
| 7 | 1 | Algorithm = 5 (`COMPRESS_ALGORITHM_LZMS`, local `compressapi.h`) |
| 8 | 4 | Decompressed size (u32; equals the loader's expected size) |
| 12 | 4 | Zero |
| 16 | 4 | Block size = 65536 |
| 20 | 4 | Zero |
| 24 | … | Chunk stream: repeated `{u32 chunk_len, bytes}`; a chunk whose length equals the remaining output is stored verbatim |

Example header (`resource-0001.bin`, pack 40102):
`0a51e5c0 1800 a405 155d6901 00000000 00010000 0000b41d` then chunk data.

## Loader (Ghidra, static only)

Function `FUN_180029640` (RVA `0x29640–0x29b9a`, `.pdata` unwind range
`0x296B5–0x29B41`), referenced by the anchor string
`[FSR4 XMX] embedded pack %u invalid: …` at `.rdata` RVA `0x30E010`:

1. Index clamp: any index > 5 falls back to 0.
2. Pack select by index → `(RCDATA id, expected size imm32, expected SHA-256)`:
   `40101…40106` (`MOV ESI, 0x9CA5…0x9CAA`), sizes `0x21B5796, 0x1695D15,
   0x28164A1, 0x2882689, 0x12AEC75, 0x531061`.
3. `GetModuleHandleExW(6, own-address)` → `FindResourceW(h, id, 10)` →
   `LoadResource` → `SizeofResource` → `LockResource`, each with its own
   `RCDATA resource %u is missing` / `LoadResource/LockResource failed` log.
4. `malloc(expected)` → Cabinet.dll **ordinal 40**
   (`CreateDecompressor`, `ECX = 5` = LZMS) → **ordinal 43** (`Decompress`
   over the full resource, output capped at the expected size) → the output
   length must equal the expected size exactly, else the `invalid` log fires
   with `compressed/decompressed/expected/error/sha256/expected`.
5. **Ordinal 45** releases the decompressor; `BCryptHash(0x41, …)` runs a
   one-shot SHA-256 (`0x41` = `BCRYPT_SHA256_ALG_HANDLE`) over exactly the
   decompressed bytes into a 32-byte buffer, hex-encoded (`%02x`) and
   `strcmp`'d against the compiled-in digest.
6. Success is cached per index (pointer/size/loaded flag under a mutex) and
   logged as `[FSR4 XMX] embedded %s pack loaded: %lu -> %zu bytes …,
   SHA256 verified.` Failure frees the buffer and returns NULL.

Imports observed: `Cabinet.dll` ordinals 40/43/45 only, `bcrypt.dll`
`BCryptHash` only. No AES/ChaCha/decrypt strings exist in the image.

## Pack inventory (all verified: sizes, SHA-256, CM counts)

| Idx | RCDATA | Bucket name (loader) | Compressed | Decompressed | SHA-256 (decompressed) | CM envelopes |
|---|---|---|---|---|---|---|
| 0 | 40101 | 18-variant DG2 (SIMD8 DPAS) | 6 107 632 | 35 346 326 | `4c63d10c…aa88ab8d` | 252 |
| 1 | 40102 | 18-variant Xe2 (SIMD16 DPAS) | 3 856 836 | 23 682 325 | `d88aa9d6…995e491` | 252 |
| 2 | 40103 | FSR 4.1.2 Lite (DG2) | 6 960 934 | 42 034 337 | `a3731f5b…70eb7d5` | 378 |
| 3 | 40104 | DLSS K (DG2 + Xe2/Xe3) | 8 031 050 | 42 477 193 | `a9ea6724…7054ea` | 716 |
| 4 | 40105 | DLSS E / F | 3 421 152 | 19 590 261 | `7ac547ee…57d246fa` | 312 |
| 5 | 40106 | DLSS-MX (DG2) | 1 001 522 | 5 443 681 | `03c18858…5a331ac3` | 67 |

Total: 1 977 CM envelopes (old 4.0.2x build: 690 over three packs).
Two small resources are not packs: `VERSIONINFO` (type 16, id 1,
`FileVersion 4.0.2.1`, "AMD FidelityFX Upscaler Library (FSR 4 and DLSS on
Intel XMX)") and the XML manifest (type 24, id 2).

## Pack contents (entry names via `tools/carve_spirv.py` + footer parser)

- **40101 / 40102** — full FSR chain, 14 families × 18 variants
  (`fsr4_pre_xmx`, `p1/p2_h1_hybrid`, `p3_xmx_n32`, `p4/p5_fused_low128`,
  `pass6_xmx_runtime`, `p7/p8/p9_stage0_xmx`, `p10_fused_low128`,
  `p11_fused_low128_ct2d`, `p12_h1_hybrid`, `post_xmx`). 40101 additionally
  holds 18 DXBC candidates in gaps and only 12 of 18 `post_xmx` carve cleanly
  (252 envelopes → 246 carved), mirroring the old build's 40101 profile;
  40102 carves 252/252.
- **40103 (Lite)** — `fsr4_pre/post_xmx`, `lite_p1a/p1b/p2/p3`, `i8_p6`,
  `i8_fnb64`, plus `p10/p11` fused kernels; 378 envelopes (old 40103: 186).
- **40104 (DLSS K)** — 716 small kernels: `k_gemm` ×174, `k_linear` ×160,
  `k_attn` ×126, `k_mlp` ×126, `k_block` ×50, `k_stage` ×48, `k_adapt` ×32.
- **40105 (DLSS E/F)** — 312 kernels: `e_conv` ×240, `e_stage` ×64,
  `e_adapt` ×8.
- **40106 (DLSS-MX)** — 67 kernels: `k_gemm` ×19, `m_layer` ×18,
  `k_mlp` ×10, `m_stage` ×10, `m_attn` ×8, `m_adapt` ×2.
- Every envelope trailer has the same shape, but the option string varies by
  bucket: 40101 carries S1, 40102 carries S2, 40103 splits between S1 and S2,
  and 40104 to 40106 split between S2 and S3. The
  `-ze-exp-register-file-size=256` flag appears only in the three DLSS packs.
  Packs 40104 to 40106 additionally reference `dpas2`/`dpasw` in gap strings.

Bucket-to-pack association above comes from the loader's own index→name
table, not from pack ordering. `tools/decompress_xmx412.py` pins the same six
bucket names next to the sizes and digest of each pack, and
`tools/parse_cm_payloads.py` reads the CM envelopes back from the decoded bytes
with no per-pack constants.

## Dynamic fields per bucket

In the 24-byte container only the `total` field at offset 8 and the CRC byte at
offset 6 change between packs, and the CRC covers the new total. Magic, header
size 24, algorithm 5, both reserved words and block size 65536 are identical in
all six headers.

The CM envelope itself starts at a SPIR-V header, ends after the option trailer,
and carries a 16-byte footer of two little-endian u64 values (`ir_size`,
`trailer_size`) immediately before the `-vc-payload` marker. The parser accepts
a trailer between 27 and 4096 bytes, requires exactly two NUL-terminated ASCII
option strings, and rejects overlaps.

Three option strings occur, all with the second string
` -target-features=+ocl_runtime`:

- S1: `-vc-payload`
- S2: `-vc-payload -Xfinalizer '-noDPASMacro'`
- S3: `-vc-payload -ze-exp-register-file-size=256 -Xfinalizer '-noDPASMacro'`

| Bucket | Header `total` | CM envelopes | Trailer bytes | IR size range | Option strings |
|---|---:|---:|---|---:|---|
| 18-variant DG2 | 35 346 326 | 252 | 70 | 31 464 to 357 612 | S1 ×252 |
| 18-variant Xe2 | 23 682 325 | 252 | 97 | 22 528 to 358 776 | S2 ×252 |
| FSR 4.1.2 Lite | 42 034 337 | 378 | 70, 97 | 18 416 to 358 816 | S1 ×189, S2 ×189 |
| DLSS K | 42 477 193 | 716 | 97, 128 | 25 880 to 258 376 | S2 ×442, S3 ×274 |
| DLSS E / F | 19 590 261 | 312 | 97, 128 | 35 092 to 143 712 | S2 ×192, S3 ×120 |
| DLSS-MX | 5 443 681 | 67 | 97, 128 | 18 128 to 162 952 | S2 ×49, S3 ×18 |

Every envelope size equals `ir_size + trailer_size`, and the trailer includes
the 16-byte footer, the option strings and the marker text, so the table values
also fix each bucket's envelope range. Trailer length follows the option string:
70 bytes marks S1, 97 marks S2 and 128 marks S3, while the 16-byte footer layout
stays the same in every envelope.

To re-derive the counts for one pack, decode it first and point the parser at a
new output directory:

```sh
python3 tools/parse_cm_payloads.py analysis/fsr-xmx-412/pack-40102.raw \
  /tmp/opencode/cm-payloads-40102
```
