# Minimal substitute cabinet.dll (game-local)

Partial substitute for `Cabinet.dll` that exists only to unblock loading of the
embedded packs of the XMX mod under Wine/Proton. It is not a reimplementation of
Cabinet: it exports only the 3 ordinals of the Compression API that the loader
uses, and only for LZMS. No execution under Wine in this phase (CPU-only); see §7.

## 1. Problem and evidence

- Spider-Man + XMX 4.1.2 mod (DLL `fadbcb50…`, old 4.0.2x `3eb086…`)
  aborts when loading packs:
  `wine: Call from ... to unimplemented function Cabinet.dll.40, aborting`
  (full log in
  `build/trace-412-20261112-141514-064f0301/runs/20261112-161210-c1561db6/vkd3d-trace.log`;
  after the abort there are only FSR4/vkd3d messages, with no valid injection).
- The loader is `FUN_180029640` (`docs/xmx412-pack-envelope.md`): by index it
  resolves `FindResourceW → malloc(expected) → Cabinet ordinal 40` (with
  algorithm 5 as the first argument) `→ ordinal 43` (decompresses the full
  resource, output limited to the expected size; the size must match
  **exactly**) `→ ordinal 45` (frees) `→ BCryptHash SHA-256` and compares
  with the compiled digest. Failure ⇒ `embedded pack %u invalid` and `NULL`.
- Verified statically: both DLLs import from `Cabinet.dll` **only**
  ordinals 40/43/45 (by ordinal, without name), and from `bcrypt.dll` only
  `BCryptHash` (ordinal 36).
- Verified: Wine's `cabinet.dll` (all local Proton/GE/cachyos builds and
  `/usr/lib/wine`) does not export **any** Compression API function
  (only FDI/FCI). There is no native Microsoft `cabinet.dll` on the machine.
  Conclusion: no build of the mod can load packs under the current Wine without
  this (or another) contribution.
- The required semantics were already validated in the repo:
  `tools/decompress_mscf.py` + `tools/decompress_xmx412.py` decompress
  the 6 packs with local libwim (LZMS, 64 KiB blocks, exact size + SHA
  mandatory).

## 2. What it implements

| Ordinal | Real MS name | Signature (x86-64, `compressapi.h` of the toolchain) | Verified role in the loader |
|---|---|---|---|
| 40 | `CreateDecompressor` | `BOOL(DWORD Algorithm, PCOMPRESS_ALLOCATION_ROUTINES AllocationRoutines, PDECOMPRESSOR_HANDLE Handle)` | Called with `Algorithm = 5` (`COMPRESS_ALGORITHM_LZMS`) before each pack |
| 43 | `Decompress` | `BOOL(HANDLE, PVOID In, SIZE_T InSize, PVOID Out, SIZE_T OutSize, PSIZE_T Produced)` | Decompresses the full resource; the loader requires `Produced == expected` exactly |
| 45 | `CloseDecompressor` | `void(HANDLE)` | Frees the decompressor before `BCryptHash` |

Naming note: the task called it `DestroyDecompressor`; the real name in the SDK
(`compressapi.h`, confirmed in the exports of Microsoft's `cabinet.dll`:
CreateDecompressor→40, Decompress→43, CloseDecompressor→45) is `CloseDecompressor`.
The loader imports **by ordinal**, so the name only matters for humans and tools;
the correct MS names are exported with the correct ordinals.

Behavior:

- `CreateDecompressor` accepts `5` (`LZMS`) and `5 | COMPRESS_RAW`
  (`0x20000000`); any other algorithm ⇒ `FALSE` + `ERROR_NOT_SUPPORTED`.
  `AllocationRoutines == NULL` uses the process heap; if custom callbacks are
  passed they are respected (via TLS around create/free).
- `Decompress` in buffer mode validates the 24-byte container (magic
  `0A 51 E5 C0`, size 24, header CRC-8, algorithm 5, reserved fields zeroed,
  `total` 1…128 MiB, block 1…64 MiB), walks `{u32 len, bytes}` and per block
  calls wimlib's raw LZMS decoder or copies verbatim when `len == resto`
  (same as `tools/decompress_mscf.py`). Fails closed on: truncation, leftover
  bytes, bad magic/CRC/fields, `OutSize < total` (`ERROR_INSUFFICIENT_BUFFER` —
  this is what enforces the loader's exact size), null parameters.
  `OutSize > total` is accepted and reports the exact `total`.
- `Decompress` in `COMPRESS_RAW` mode decodes the input as a single raw LZMS
  block (via helper, tested with the first real chunk of 40102; the loader does
  not use this mode).
- Invalid handles, double `Close` and `NULL` do not hang or corrupt
  (tested in `tests/test_cabinet_shim.py`).
- LZMS decoder: 4 wimlib TUs compiled as-is from the local checkout
  (`upstream/wimlib @ cd5e231…`, revision pinned in `report.json`):
  `lzms_decompress.c`, `lzms_common.c`, `decompress_common.c` and
  `compress_common.c` (the latter only for `make_canonical_huffman_code`,
  needed for the adaptive Huffman rebuild). No global wimlib init: the wrapper
  targets `lzms_decompressor_ops` directly.
  `cpu_features = 0` forces the portable path of the x86 filter (the SSE4.2
  route is only an optimization; bit-identical results, tested).
- DLL load dependencies: only `KERNEL32.dll` (heap + errors + CRT startup)
  and the api-sets `api-ms-win-crt-runtime-l1-1-0` /
  `api-ms-win-crt-stdio-l1-1-0` from MinGW startup. No network, drivers,
  FDI/FCI or direct UCRT. Binary: PE32+ x86-64, ~70 KB.

## 3. What it does NOT implement

- Rest of the Compression API: 30 `CreateCompressor`, 31/41 `Set*Information`,
  32/42 `Query*Information`, 33 `Compress`, 34/44 `Reset*`,
  35 `CloseCompressor`. Slots 41/42/44 in the export table exist
  empty (RVA 0): importing them fails cleanly.
- FDI/FCI, `Extract`, `GetDllVersion`, etc. This shim does **not** include them;
  Wine's `cabinet.dll` does.
- Compressors or other algorithms (MSZIP/XPRESS). `Create` with another
  algorithm fails with `ERROR_NOT_SUPPORTED`.
- No `DllRegisterServer`, no Authenticode signature (irrelevant under Wine).

## 4. Reproducible build

```sh
python3 tools/build_cabinet_shim.py
```

- Toolchain: `artifacts/extracted/llvm-mingw-20261020-ucrt/` (Clang 23.1.4,
  precedent in `docs/shim-cross-build.md`). Nothing is installed and no
  produced binary is run: only compile + link + inspect.
- Sources: wrapper + `.def` embedded in the script (the only versioned source);
  the 4 TUs are compiled **in place** from `upstream/wimlib`
  (read-only, never modified).
- Outputs (all under `build/cabinet-shim/`, ignored by git):
  `cabinet.dll`, `src/`, `obj/`, `test/libcabinet_shim_test.so` (host twin
  with the same sources for tests via ctypes, without Wine) and
  `report.json` (wimlib rev, SHA-256 of TUs/wrapper/DLL/.so, exports,
  imports and exact commands; the DLL is pinned by its SHA).
- The script itself verifies: PE32+ x86-64, exports exactly
  40/43/45 with the MS names, and imports within the allowed list.
  Any drift fails the build.
- The DLL's SHA identifies the run: the linker stamps the time in the PE
  header (same precedent as the XESS shim in `docs/shim-cross-build.md`; it is
  not declared bit-for-bit reproducible). Functional equivalence between builds
  is established by re-running the tests.

## 5. CPU verification

```sh
python3 -m unittest tests.test_cabinet_shim
```

24 tests, OK on 2026-11-12. They cover:

- Contract of exports/imports over the PE (ordinals, names, PE32+,
  DLL allowlist).
- The **6 packs** decompress byte-identical to `analysis/fsr-xmx-412/` via the
  host twin (same sources as the DLL), with SHA-256 and size from the pins in
  `tools/decompress_xmx412.py`.
- Rejections: unsupported algorithm, short buffer (inexact size), larger buffer
  (reports the exact one), truncated, leftover, bad magic/CRC/fields,
  nulls and zeros, double `Close`, synthetic verbatim chunk, RAW block
  with a real chunk, and custom allocation callbacks.

## 6. Game-local installation (manual, with the game closed)

1. Copy `build/cabinet-shim/cabinet.dll` next to `Spider-Man.exe`.
   Do not copy it into any prefix's `system32`/`syswow64` nor into Proton/Wine
   directories: the shim is partial and must exist only next to the game.
2. Launch with native-first override for Cabinet, added to the rest of the
   trace run's environment:
   `WINEDLLOVERRIDES="cabinet=n,b"`.
3. Expected success: the abort `unimplemented function
   Cabinet.dll.40` disappears and the log shows packs loaded / FSR4 resources downstream. If
   `embedded pack %u invalid` appears, the shim worked and the problem is
   something else (note the bytes and abort the capture).
4. Reversal: delete the file from the game directory.

## 7. Risks, limits and what is missing

- Partial lookalike: it does not implement FDI/FCI or anything outside 40/43/45. With the
  `n,b` override, another Cabinet consumer in that prefix would fall back to
  Wine's builtin (which does not have them either) or fail; that is why
  installation is game-local only.
- Never loaded under Wine yet: the first real load is the user's next run.
  The 24 CPU tests cover the host twin, not the Wine loader.
- The DLL's SHA varies with the PE timestamp (same precedent as the XESS shim);
  functional equivalence is established by re-running the tests.
- If Wine/Proton ever implements the Compression API, this shim stops being
  needed (deleting the file is enough).
...[truncated 3881 chars]
</content>
