# Compressed packs and the game-local cabinet shim

The XMX 4.1.2 mod ships six compressed packs. This document covers how they are
read, verified and rebuilt on Linux, and the minimal `Cabinet.dll` substitute
that loads them under Wine/Proton. The DLL was read as bytes and never loaded;
no GPU, Wine, Steam, prefix, driver or `artifacts/original` state was touched.

## 1. What a pack is

A pack is a stock MS Compression API LZMS buffer: a 24-byte header followed by
LZMS chunks, stored one per RCDATA resource of type 10 with ids 40101 to 40106.
[`docs/xmx412-pack-envelope.md`](xmx412-pack-envelope.md) has the byte layout,
accepted fields, loader walk and bucket contents.

The header's `total` must equal the decompressed size the loader expects, and
the bytes must hash to a digest compiled into the mod. Loader `FUN_180029640`
calls `FindResourceW`, allocates `expected` bytes, then Cabinet ordinals 40
(algorithm 5), 43 (output capped at that size), 45 and `BCryptHash` SHA-256.
Ordinal 43 must report `Produced == expected` exactly, or the loader logs
`embedded pack %u invalid` and returns `NULL`.

## 2. Pack inventory

All six packs decode with exact size matches. Their SHA-256 values match the
stored raws and the pins in `tools/decompress_xmx412.py` (commit 7059945):

| Pack | Bucket | Compressed | Raw | raw SHA-256 (prefix) | CM |
|---|---|---|---|---|---|
| 40101 | DG2 | 6 107 632 | 35 346 326 | `4c63d10c…aa88ab8d` | 252 |
| 40102 | Xe2 | 3 856 836 | 23 682 325 | `d88aa9d6…995e491` | 252 |
| 40103 | Lite | 6 960 934 | 42 034 337 | `a3731f5b…70eb7d5` | 378 |
| 40104 | DLSS K | 8 031 050 | 42 477 193 | `a9ea6724…7054ea` | 716 |
| 40105 | DLSS E / F | 3 421 152 | 19 590 261 | `7ac547ee…57d246fa` | 312 |
| 40106 | DLSS-MX | 1 001 522 | 5 443 681 | `03c18858…5a331ac3` | 67 |

Total 1 977 CM envelopes, against 690 in the old 4.0.2x build (252+252+186).
Decoded packs live in `analysis/fsr-xmx-412/` (git-ignored).

## 3. Rebuilding and verifying a pack

`tools/decompress_xmx412.py` decodes the packs with local libwim LZMS and fails
closed on size, SHA-256 and CM-count mismatches; `tools/decompress_mscf.py` is
the older 4.0.2x decoder. `tools/parse_cm_payloads.py` reads CM envelopes back
from the length footers, `tools/carve_spirv.py` carves SPIR-V with a heuristic
walk, and `spirv-dis` (SPIRV-Tools 2026.4) disassembles exact IR slices.
Re-running the 4.1.2 decoder into `/tmp/opencode/xmx412-repro` with
`--libwim upstream/wimlib/.libs/libwim.so` is byte-identical: every pack matched
the stored raw and the pinned digest.

`tests/test_xmx412_packs.py` holds 12 tests, OK on 2026-11-22, pinning the focus
counts, the 1 977 total, the DLL SHA-256, the stored raws, a byte-identical
re-run, the CM and carve counts, the gap profile, disassembly of every focus IR
and the 40102 PRE block.

## 4. CM block inventory

| Pack | CM envelopes | SPIR-V magics | Carved (`carve_spirv`) | `spirv-dis` ok | Gaps | DXBC in gaps | Non-zero non-DXBC gaps |
|---|---|---|---|---|---|---|---|
| 40101 DG2 | 252 | 252 | 246 | 252/252 | 251 (227 zero) | 18 × 33 786 B | 6 × 134 938 B (weights-like) |
| 40102 Xe2 | 252 | 252 | 252 | 252/252 | 251 (all zero, max 15 B) | 0 | 0 |
| 40103 Lite | 378 | 378 | 378 | 378/378 | 377 (all zero, max 255 B) | 0 | 0 |

All 882 focus-pack IRs disassemble (0 failures). The 40101 gaps hold 18 DXBC
candidates (`declared_size` ~33 764/33 772, 7 chunks each) and 6 opaque
134 938-byte blobs with no `DXBC` marker, at offsets 1 918 694, 7 809 766,
13 700 838, 19 591 910, 25 482 966 and 31 373 990, plus zero paddings of 7 to
14 bytes.

Six 40101 CM envelopes do not carve: all `fsr4_post_xmx`, `ir_size` 189 728, at
CM indices 13, 55, 97, 139, 181 and 223. They disassemble cleanly from the exact
IR slice. The heuristic scans to the next magic instead of the footer-pinned
`ir_size`, runs into gap bytes and rejects the module; the CM footer parser
stays authoritative.

40101 and 40102 each cover 14 families × 18 variants, and 40101 carves only 12
of its 18 `post_xmx`. 40103 holds 36 `p10` + 36 `p11` + 144 `post_xmx` + 6
`pre_xmx` + 18 `i8_fnb64` + 6 `i8_p6` + 48 `lite_p1a` + 24 `lite_p1b` + 36
`lite_p2` + 24 `lite_p3`. Every 40101 envelope carries S1, every 40102 S2, and
40103 both (189 + 189). Packs 40104 to 40106 were re-checked for counts only:
716/312/67 envelopes, 712/307/66 gaps, all zero-filled, no DXBC. Family names
are in `docs/xmx412-pack-envelope.md`.

### The PRE block in 40102

CM envelope index 0 at pack offset 0 of 40102 (`fsr4_pre_xmx`, Kernel id 11173)
has `ir_size` 358 776, `trailer_size` 97 and `envelope_size` 358 873. Its
`ir_sha256` is
`49e069fd7ad17af19589195e274d8a1af191af363608f71d0a50ad0a21f9f568` and its
envelope hash
`ce3727191553be4759973d1cd0cfb050de2d39ea07faac8f34bf0b34aa5b85ab`; the SPIR-V
header is v1.1 at Bound 11188 (17 444 lines, old 16 014). The old reference
(`analysis/fsr-resources/resource-0001-first.spv`) has `ir_size` 330 108,
`ir_sha256`
`1d10c34ef21007bdc11c93647ef9ea482f7988e1aee705e082c7eb1722bd44a2` and Bound
10274, so the new block is +28 668 IR bytes (+8.7 %) and +914 Bound. The 18
`pre_xmx` envelopes sit at every 14th CM index in 40101 and 40102.

## 5. The cabinet shim

Wine's `cabinet.dll` (all local Proton/GE/cachyos builds and `/usr/lib/wine`)
exports no Compression API function, only FDI/FCI, and the machine has no native
Microsoft `cabinet.dll`. The mod aborts with
`wine: Call from ... to unimplemented function Cabinet.dll.40, aborting` (log in
`build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/vkd3d-trace.log`;
after the abort the log holds only FSR4/vkd3d messages and no valid injection).

The 4.1.2 DLL (`fadbcb50…`) and the old 4.0.2x one (`3eb086…`) import only
ordinals 40/43/45, by ordinal and without name, and only `BCryptHash` (ordinal
36) from `bcrypt.dll`. No build of the mod can load packs under the current Wine
without this shim, which exports those 3 ordinals for LZMS only, is not a
Cabinet reimplementation, and has not run under Wine.

### Exports and ordinals

| Ordinal | Real MS name | Signature (x86-64, `compressapi.h` of the toolchain) | Verified role in the loader |
|---|---|---|---|
| 40 | `CreateDecompressor` | `BOOL(DWORD Algorithm, PCOMPRESS_ALLOCATION_ROUTINES AllocationRoutines, PDECOMPRESSOR_HANDLE Handle)` | Called with `Algorithm = 5` (`COMPRESS_ALGORITHM_LZMS`) before each pack |
| 43 | `Decompress` | `BOOL(HANDLE, PVOID In, SIZE_T InSize, PVOID Out, SIZE_T OutSize, PSIZE_T Produced)` | Decompresses the full resource; the loader requires `Produced == expected` exactly |
| 45 | `CloseDecompressor` | `void(HANDLE)` | Frees the decompressor before `BCryptHash` |

Ordinal 45 is `CloseDecompressor`, not `DestroyDecompressor`; `compressapi.h`
and Microsoft's exports agree, and the loader imports by ordinal, so the name
matters only to humans and tools.

### Decompression and LZMS

`CreateDecompressor` accepts `5` (`LZMS`) and `5 | COMPRESS_RAW`
(`0x20000000`); any other algorithm returns `FALSE` with `ERROR_NOT_SUPPORTED`.
A `NULL` allocation table uses the process heap, and custom callbacks pass
through a thread-local slot.

`Decompress` in buffer mode validates the 24-byte container (magic
`0A 51 E5 C0`, size 24, header CRC-32 low byte, algorithm 5, reserved fields
zeroed, `total` 1 to 128 MiB, block 1 to 64 MiB), walks `{u32 len, bytes}` and
decodes each block into `min(block, total - written)` bytes with wimlib's raw
LZMS, or copies it verbatim when `len` equals the remaining size. It fails
closed on truncation, leftovers, bad magic/CRC/fields, `OutSize < total`
(`ERROR_INSUFFICIENT_BUFFER`) and null parameters, while `OutSize > total`
succeeds and reports `total`. `COMPRESS_RAW` treats the input as one raw block,
tested with the first chunk of 40102.

The decoder is 4 wimlib TUs compiled as-is from `upstream/wimlib @ cd5e231…`
(revision in `report.json`): `lzms_decompress.c`, `lzms_common.c`,
`decompress_common.c` and `compress_common.c` (only for
`make_canonical_huffman_code`). No global wimlib init; the wrapper targets
`lzms_decompressor_ops` directly, and `cpu_features = 0` forces the portable x86
filter path, with the SSE4.2 route bit-identical, tested. The DLL depends on
`KERNEL32.dll` and the api-sets `api-ms-win-crt-runtime-l1-1-0` and
`api-ms-win-crt-stdio-l1-1-0`, with no network, drivers or direct UCRT, and is
PE32+ x86-64 at about 70 KB.

### Handle lifecycle and allocators

`CreateDecompressor` allocates a context with magic `0x4341425348494D00`, stores
the algorithm, a raw-mode flag and a copy of the allocation routines, and
creates a wimlib LZMS decompressor with a 64 MiB capacity. `check_ctx()` accepts
a handle only when the pointer is non-null, the magic matches and the decoder
pointer is set, so a closed handle fails with `ERROR_INVALID_PARAMETER`;
`CloseDecompressor` clears the magic, frees the decoder and the context, and
rejects a second call as a no-op.

Both routines must arrive together; a table with only `Allocate` or `Free` is
rejected with `ERROR_INVALID_PARAMETER`. The wrapper installs the caller table
in a thread-local slot around create and free, and the wimlib stubs read it, so
every wimlib allocation goes through the callbacks. 16-byte alignment
over-allocates 32 bytes and stores the offset in the byte before the aligned
block; the Windows build uses `GetProcessHeap` without routines, the host twin
libc.

### Build modes

```sh
python3 tools/build_cabinet_shim.py
```

`--windows-only` builds the DLL, `--host-only` the test `.so`, and
`--verify-only` re-checks an existing DLL; the default builds both and writes
`report.json`. Sources compile with `x86_64-w64-mingw32-clang -c` and the flags
`-O2 -DNDEBUG -ffreestanding -Wall -Iupstream/wimlib/include`, then link with
`-shared` and the generated `cabinet.def`. The host twin uses `gcc`, or `clang`
when absent, with `-O2 -DNDEBUG -fPIC -shared -fvisibility=hidden -Wall`.

The toolchain is `artifacts/extracted/llvm-mingw-20261020-ucrt/` (Clang 23.1.4);
the wrapper and `.def` are embedded in the script, the only versioned source,
and the 4 TUs compile in place from `upstream/wimlib`, read-only. Outputs land
in `build/cabinet-shim/` (ignored by git): `cabinet.dll`, `src/`, `obj/`,
`test/libcabinet_shim_test.so` and `report.json` with the revisions, hashes,
exports, imports and commands.

The script verifies PE32+ x86-64, exactly 40/43/45 with the MS names, and
imports within the allowed list, and fails closed when the LLVM-MinGW clang,
`llvm-readobj`, `x86_64-w64-mingw32-objdump`, any of the four wimlib TUs or
`upstream/wimlib/include/wimlib/decompressor_ops.h` is missing. The PE timestamp
varies the SHA per run, so re-running the tests establishes equivalence.

### CPU tests

```sh
python3 -m unittest tests.test_cabinet_shim
```

24 tests, OK on 2026-11-22: the export and import contract over the PE, a
byte-identical decode of the 6 packs against `analysis/fsr-xmx-412/` through the
host twin, and rejections. `StaticBinaryTests` checks the PE with `llvm-readobj`
and `x86_64-w64-mingw32-objdump`, including `HeapAlloc` and `SetLastError`.
`SixPackDecodeTests` checks the mod DLL SHA-256
`fadbcb50c523df01c9350747cc726edb4ecbf1a99e7ed629bf73cdbb37f44732`, extracts
packs 40101 to 40106 and compares every byte with the pinned raw.
`RejectionTests` mutates one header field at a time (offsets 4, 6, 7, 12, 16,
20) and covers unsupported algorithms, short and larger buffers, nulls, zeros,
double `Close`, a synthetic verbatim chunk, a RAW block with a real chunk and
custom callbacks. `ReportTests` re-hashes both binaries against `report.json`.

Each class skips with a printed message when its inputs are missing, so a
missing build never counts as a pass. The pack tests need `build/cabinet-shim/`,
the extracted 4.1.2 DLL and `analysis/fsr-xmx-412/pack-4010N.raw`; the report
test needs the build outputs, and no test loads the DLL into Wine.

### Limits and errors

The shim leaves out the rest of the Compression API: 30 `CreateCompressor`,
31/41 `Set*Information`, 32/42 `Query*Information`, 33 `Compress`, 34/44
`Reset*` and 35 `CloseCompressor`, plus FDI/FCI, `Extract`, `GetDllVersion`,
MSZIP, XPRESS, `DllRegisterServer` and Authenticode. Slots 41/42/44 exist empty
(RVA 0), so importing them fails cleanly. A `n,b` override makes any other
Cabinet consumer in the prefix fall back to Wine's builtin, which also lacks the
API, so installation stays game-local; if Wine or Proton implements the API,
deleting the file is enough. The shim has not run under Wine, and the 24 CPU
tests cover the host twin.

Failures return `FALSE` and set one of these thread errors: 87
`ERROR_INVALID_PARAMETER` (bad or freed handle, null arguments, half an
allocation table), 50 `ERROR_NOT_SUPPORTED` (algorithm other than 5), 122
`ERROR_INSUFFICIENT_BUFFER` (`OutSize < total`), 287
`ERROR_BAD_COMPRESSION_BUFFER` (bad fields or sizes, truncation, leftovers,
LZMS failure) or 1627 `ERROR_FUNCTION_FAILED` (allocation failure).

## 6. Game-local installation

1. Copy `build/cabinet-shim/cabinet.dll` next to `Spider-Man.exe`. Do not copy
   it into any prefix's `system32`/`syswow64` nor into Proton/Wine directories:
   the shim is partial and must exist only next to the game.
2. Launch with a native-first override for Cabinet, added to the rest of the
   trace run's environment: `WINEDLLOVERRIDES="cabinet=n,b"`.
3. Expected success: the abort `unimplemented function Cabinet.dll.40`
   disappears and the log shows packs loaded with FSR4 resources downstream.
   `embedded pack %u invalid` instead means the shim worked and the problem is
   elsewhere; note the bytes and abort the capture.
4. Reversal: delete the file from the game directory.
